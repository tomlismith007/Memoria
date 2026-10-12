# Talorys 核心设计 · 06 Provider 抽象与预算守卫

> 研究对象：`rociiu/talorys` — 单用户个人 agent（Cloudflare Durable Object），v0.1.4，HEAD `2cc547c`
> 路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦：AI Provider 三方法接口（`ai/provider.ts`）、Workers AI 实现（`ai/workers-ai.ts`）、确定性 Mock（`ai/mock.ts`）、错误分类、用量计数器与限额双层（`services/usage.ts`、`packages/shared/src/constants.ts`）
> 预算的强制执行点分布在 runner（每轮）、执行器（每轮工具）、调度（每日 AI 运行）——本篇与 01/04/05 篇交叉

---

## 1. 定位与全景

Talorys 的 AI 接入有两层抽象：

```
AIProvider（三方法接口）
  ├─ generate            单次生成（摘要用）
  ├─ stream              纯文本流（mock 内部转发到 generateWithTools）
  └─ generateWithTools   带工具的流式生成（主循环用）

实现
  ├─ CloudflareWorkersAIProvider  （生产；AI SDK 的 workers-ai-provider）
  └─ MockAIProvider               （dev / 测试 / demo；确定性意图路由，走真实工具管线）

provider === null 是一等状态
  └─ 聊天抛 AI_UNAVAILABLE（文案说明其余功能照常）；任务/笔记/记忆/提醒/自动化全量可用
```

预算守卫分布在四个执行点，共享一个计量服务：

| 执行点 | 限制 | 落点 |
|---|---|---|
| 每轮聊天 | 输出 token / 上下文 token / 推理轮 / 工具调用 | `runner.ts` + `tools/registry.ts` |
| 每轮每工具 | maxCallsPerTurn | 各工具定义 |
| 每日 AI 请求 | maxAiRequestsPerDay | `usage.canUseAi` |
| 每日调度 AI 运行 | maxScheduledAiRunsPerDay | `usage.canRunScheduledAi` |
| 每日嵌入请求 | maxEmbeddingsPerDay（独立表） | `semantic/embeddings.ts` |

## 2. Provider 接口（`ai/provider.ts`）

### 2.1 消息与请求形状（4-36）

```ts
export interface ModelMessage { role: "user" | "assistant"; content: string; }   // 无 system role

export interface GenerateRequest {
  system: string;                    // 独立字段，不进 messages
  messages: ModelMessage[];
  maxOutputTokens: number;
  temperature?: number;
  signal?: AbortSignal;
}

export interface ProviderTool {
  name: string; description: string;
  inputSchema: z.ZodType;                                        // zod 直传
  execute: (input: unknown, callId: string) => Promise<unknown>;  // 执行闭包由调用方提供
}

export interface ToolRequest extends GenerateRequest {
  tools: ProviderTool[];
  maxIterations: number;                    // 模型往返上限（每次可含多个工具调用）
  toolBudgetExhausted: () => boolean;       // 预算耗尽 → 强制文本作答
}

export type AgentEvent =
  | {type: "text"; delta: string}
  | {type: "tool-start"; id: string; name: string; input: unknown}
  | {type: "tool-end"; id: string; name: string; output: unknown; error?: string}
  | {type: "usage"; usage: Usage};
```

设计要点：

- **system 是独立字段**，不是 messages 的一条——与 provider 的 instructions/system 参数直接对应，且避免模型把它当对话内容。
- **`ProviderTool.execute` 是调用方注入的闭包**（`runner.ts:167`：`(toolInput, callId) => executor.execute(t.name, toolInput, callId)`）——provider 只负责"让模型调用它"，**全部纪律（预算/权限/重复检测/审批）在闭包内，provider 层无感知也无法绕过**。
- `toolBudgetExhausted` 回调：让 provider 在预算耗尽时强制 `toolChoice: "none"`（见 §3.2）——把执行器状态透传进 provider 决策。

### 2.2 token 估算（56-58）

```ts
/** Rough token estimate (≈4 chars/token) used for budgeting and local usage estimates. */
export function estimateTokens(text: string): number { return Math.ceil(text.length / 4); }
```

**全应用统一的估算尺子**：窗口裁剪、摘要触发判断、计量回落都用它。粗估（4 字符/token）对英文够用、对中文偏乐观——但它只用于预算决策，真实用量优先用 provider 实测（见 §5.3）。

### 2.3 错误分类（60-93）

```ts
export function classifyAiError(error: unknown): AppError {
  if (error instanceof AppError) return error;
  const lower = errorMessage(error).toLowerCase();
  if (lower.includes("4006") || lower.includes("free allocation") || lower.includes("neurons"))
    return new AppError("AI_QUOTA_EXHAUSTED",
      "Your Cloudflare account has used its Workers AI allocation for today. Tasks, notes, memories and reminders keep working; chat will resume when the quota resets.");
  if (lower.includes("3040") || lower.includes("capacity") || lower.includes("429") || lower.includes("rate limit") || lower.includes("too many"))
    return new AppError("AI_UNAVAILABLE", "Workers AI is busy right now. Please try again in a moment.");
  if (lower.includes("5007") || lower.includes("no such model") || lower.includes("model not found"))
    return new AppError("AI_UNAVAILABLE", "The configured AI model is not available. Choose another model in Settings.");
  if (lower.includes("abort")) return new AppError("AI_UNAVAILABLE", "The response was cancelled.");
  console.error("Workers AI error", message);
  return new AppError("AI_UNAVAILABLE", "The AI model could not respond. Please try again.");
}
```

- 平台错误码（4006 配额 / 3040 容量 / 5007 模型不存在）→ 稳定应用错误码（`AI_QUOTA_EXHAUSTED` / `AI_UNAVAILABLE`）。
- **错误消息带影响面与出路**："Tasks, notes, memories and reminders keep working"（配额耗尽时哪些还能用）、"Choose another model in Settings"（模型不存在时怎么办）。
- `errorMessage`（87-93）递归展开 `cause` 链——AI SDK 的错误常把真实原因藏在 cause 里。

## 3. Workers AI 实现（`ai/workers-ai.ts`）

### 3.1 构造与模型配置（10-25）

```ts
constructor(binding: Ai, private readonly modelId: string) { this.workersai = createWorkersAI({binding}); }
private model() {
  return this.workersai(this.modelId, { chat_template_kwargs: { enable_thinking: false } });
}
```

**`enable_thinking: false`**（注释 6-8："Reasoning ('thinking') is disabled by default to keep Neuron usage low."）——成本决策写进 provider 构造。

### 3.2 generateWithTools 的四个关键设置（51-82）

```ts
const result = streamText({
  model: this.model(), instructions: req.system, messages: req.messages,
  maxOutputTokens: req.maxOutputTokens, temperature: req.temperature,
  abortSignal: req.signal, maxRetries: 1,
  ...(hasTools ? {
    tools,
    stopWhen: stepCountIs(req.maxIterations),                         // 1. 推理轮上限
    prepareStep: ({stepNumber}) =>                                    // 2. 末步/预算耗尽 → 强制文本
      stepNumber >= req.maxIterations - 1 || req.toolBudgetExhausted() ? {toolChoice: "none"} : {},
  } : {}),
  onError: ({error}) => { streamError = error; },                     // 3. 流内错误捕获
});
```

1. **`stopWhen: stepCountIs(maxIterations)`**：模型往返上限（默认 4）——执行器的工具预算之外的第二道。
2. **`prepareStep` 强制文本作答**（注释 74："On the last allowed step, or once the tool budget is spent, force a plain-text answer."）——**保证轮次必有文字产出**，而不是以工具调用收尾。这是"工具预算耗尽"与"最后一步"两个条件的并集。
3. **`onError` 捕获 + 流后重抛**（79-81, 120）：AI SDK 的 streamText 可能在流内静默吞错；显式保存 `streamError` 并在流结束后抛出，交给 `classifyAiError`。
4. `maxRetries: 1`：一次重试——个人部署不追求极致可靠，避免重试放大配额消耗。

### 3.3 流事件映射（85-116）

```ts
for await (const part of result.fullStream) {
  case "text-delta":  yield {type: "text", delta: part.text};
  case "tool-call":   yield {type: "tool-start", id: part.toolCallId, name: part.toolName, input: part.input};
  case "tool-result": yield {type: "tool-end", id: part.toolCallId, name: part.toolName, output: part.output};
  case "tool-error":  yield {type: "tool-end", id: part.toolCallId, name: part.toolName, output: null, error: msg};
  case "finish":      yield {type: "usage", usage: {inputTokens: part.totalUsage.inputTokens ?? 0, outputTokens: part.totalUsage.outputTokens ?? 0}};
  case "error":       throw part.error;
}
```

- **tool-error 映射为 tool-end + error 字段**——工具抛错不是流的中断，而是模型可读的结果（模型看到错误后可以自纠）。
- `finish` 事件带 `totalUsage`（**整个多步循环的累计**，不是最后一步）——计量准确性。

## 4. 确定性 Mock（`ai/mock.ts`）

### 4.1 设计意图（注释 4-9）

```
Deterministic provider for local development, automated tests and the
documented demo mode. It never calls a model: it recognises a few simple
intents, routes them through the real tool pipeline (so limits and
validation apply), and streams a templated reply.
```

**三用**（dev / test / demo）+ **走真实管线**（限额、校验、审批全部生效）——这是 mock 与"假数据返回"的本质区别。

### 4.2 意图路由（`planTools` 69-111）

七条正则，覆盖主要工具：

| 输入 | 工具 | 说明 |
|---|---|---|
| `remember (that) X` | `remember` | category 固定 preference |
| `add/create (a) task (to): X` | `create_task` | |
| `add/create/write (a) note: X` | `create_note` | title 取前 80 字符 |
| `complete/finish/mark (the) task X (as done)` | `complete_task` | |
| `delete/remove (the) task X` | `delete_task` | 描述里说"I've asked to delete… Approve it above" |
| `list/show (my) tasks` / `what should i work on` | `list_tasks` | view: open |
| `remind me in N minutes to X` | `create_reminder` | |
| `search/find X` | `search` | |

- 每条计划带 `describe(output)` 生成自然语言回复（如 "Added the task \"X\"."）——回复不是模板套话，而是基于真实工具输出。
- **destructive 的 describe 体现提案语义**（84）："I've asked to delete \"X\". Approve it above if you want it gone."——mock 也遵守提案制措辞。

### 4.3 执行与流式（25-60）

```ts
for (const step of plan) {
  const tool = req.tools.find((t) => t.name === step.name);
  if (!tool) continue;                                        // 工具不可用（如 scheduled 模式）→ 跳过
  if (calls >= req.maxIterations * 4 || req.toolBudgetExhausted()) break;   // 遵守预算
  calls++;
  const id = `mock_${calls}`;
  yield {type: "tool-start", id, name: tool.name, input: step.input};
  try { const output = await tool.execute(step.input, id); yield {type: "tool-end", id, name: tool.name, output};
        reply += step.describe(output); }
  catch (error) { yield {type: "tool-end", ..., error: message}; reply += `I couldn't complete that: ${message}`; }
}
```

- **调用的是 `tool.execute`（即 runner 注入的闭包）**——预算、权限、zod 校验、重复检测、审批全部生效。
- 工具抛错也转成回复文本（"I couldn't complete that: …"）——与真实 provider 的错误回灌一致。
- 流式按词切片 + `chunkDelayMs = 25`（注释 53："Paces output like a real model so streaming paths are exercised."）——**测试流式 UI 的路径**（SSE 分片、前端增量渲染）。
- 无匹配意图时的兜底（47-49）：`(Demo mode) You said: "X". Connect Workers AI for real answers — tasks, notes, memories and reminders work either way.`

### 4.4 与 MockEmbedder 的分工

- `MockAIProvider`：聊天与工具（正则意图）。
- `MockEmbedder`（`semantic/embeddings.ts:83-103`）：哈希词袋 + 概念组，让语义相近的句子余弦接近。
- 两者独立选择（`createEmbedder` 与 `TalorysAgent.aiProvider`），但共享 demo 模式开关。

## 5. 用量与限额（`services/usage.ts` + `constants.ts`）

### 5.1 限额双层（`constants.ts`）

```ts
export const DEFAULT_LIMITS = {
  maxOutputTokens: 1024, maxToolCalls: 6, maxAgentIterations: 4, maxContextTokens: 6000,
  maxScheduledAiRunsPerDay: 6, maxAiRequestsPerDay: 200,
} as const;

/** Hard ceilings the owner cannot exceed through settings. */
export const LIMIT_CEILINGS = {
  maxOutputTokens: 4096, maxToolCalls: 20, maxAgentIterations: 10, maxContextTokens: 32000,
  maxScheduledAiRunsPerDay: 48, maxAiRequestsPerDay: 2000,
} as const;
```

- **默认值 + 硬天花板**：设置页可调，但 `LIMIT_CEILINGS` 是 owner 无法越过的上限（注释原文："Hard ceilings the owner cannot exceed through settings"）。
- 天花板约为默认值的 4-6 倍——留给"我知道自己在做什么"的用户，但拦住"把 200 改成 200000"的误操作。

### 5.2 六计数器（`usage.ts:4, 17-25`）

```ts
type Counter = "ai_requests" | "input_tokens" | "output_tokens" | "tool_calls" | "scheduled_ai_runs" | "ai_errors";

increment(counters, date = new Date()) {
  const day = UsageService.day(date);
  this.db.run(`INSERT INTO tal_usage_daily (day) VALUES (?) ON CONFLICT(day) DO NOTHING`, day);
  for (const [key, amount] of Object.entries(counters)) {
    if (!amount) continue;
    // Column names come from the closed Counter union above, never from input.
    this.db.run(`UPDATE tal_usage_daily SET ${key} = ${key} + ? WHERE day = ?`, Math.round(amount), day);
  }
}
```

- **列名来自封闭 union，永非输入**（代码注释自证）——动态 SQL 的安全性靠类型而非转义。
- 按 UTC 日分桶（`day()` 13-15 用 `toISOString().slice(0,10)`）。
- `sum(from, to)`（36-51）支持区间查询（`today` / `lastDays`）——设置页显示"今天/最近 7 天"。
- 表结构（`db/migrations.ts:140-148`）：`day PRIMARY KEY` + 六列。

### 5.3 计量：实测优先，估算回落（`runner.ts:170-211`）

```ts
s.usage.increment({ai_requests: 1});                        // 发起前计数
let usageRecorded = false;
for await (const event of this.provider.generateWithTools({...})) {
  ...
  } else if (event.type === "usage") {
    usageRecorded = true;
    s.usage.increment({input_tokens: event.usage.inputTokens, output_tokens: event.usage.outputTokens});
  }
}
if (!usageRecorded) {                                        // provider 没报 → 本地估算补记
  s.usage.increment({
    input_tokens: estimateTokens(system) + window.messages.reduce((n, m) => n + estimateTokens(m.content), 0),
    output_tokens: estimateTokens(text),
  });
}
s.usage.increment({tool_calls: executor.callCount});
```

- **`ai_requests` 在发起前自增**——按"发起"计不按"成功"计（配合 `ai_errors` 单独计数）。
- 计量双通道：provider 实测（`finish` 事件的 totalUsage）优先；无实测（mock、异常路径）用 `estimateTokens` 估算。
- `tool_calls` 用执行器的实际计数（`executor.callCount`）——不是模型声称的调用数。

### 5.4 额度检查（53-59）

```ts
canUseAi(limits): boolean { return this.today().ai_requests < limits.maxAiRequestsPerDay; }
canRunScheduledAi(limits): boolean {
  return this.today().scheduled_ai_runs < limits.maxScheduledAiRunsPerDay && this.canUseAi(limits);
}
```

- 聊天检查在 `runner.ts:101-106`（抛 `AI_LIMIT_REACHED`，文案含"adjustable in Settings → AI"）。
- 调度检查在 `talorys-agent.ts:129-136`（跳过 + 通知）。
- **嵌入请求独立计数**（`tal_semantic_usage` 表，`embeddings.ts:167-180`）——语义召回不占聊天的 `ai_requests` 额度。

### 5.5 ActivityLog（`usage.ts:62-76`）

```ts
record(type, summary) {
  this.db.run(`INSERT INTO tal_activity (...)`, crypto.randomUUID(), type, summary.slice(0, 500), iso);
  this.db.run(`DELETE FROM tal_activity WHERE id NOT IN (SELECT id FROM tal_activity ORDER BY created_at DESC LIMIT 1000)`);
}
```

- **环形上限 1000 条**，每次写入顺带清理——无定时任务。
- summary 截 500 字符；type 是事件类型（`task.created` / `memory.deleted` / `automation.failed` / `data.imported` / `privacy.history_cleared`…）。
- `list(limit)` 供设置页展示。

## 6. 与既有研究的对照

- **对比 ZCode/Mini-Agent 的 token 计量**：它们用 tiktoken 精确估算或 provider usage 校准；Talorys 用 4 字符/token 粗估 + provider 实测回落——**精度更低但零依赖**，适合"预算决策"而非"成本核算"。README 也明说计量是估算（`usage.ts:6-9` 注释："These are estimates made by Talorys, not Cloudflare's billing figures"）。
- **对比 OpenMuse/Codex 的预算**：它们关注单轮内的 token 预算；Talorys 是**双层 + 跨天**（单轮限额 + 每日额度 + 调度独立额度）——个人部署的成本防线形态。
- **硬天花板**：六家 + hermes 均无"用户可调但不可越界"的设计；这是"给用户自由但防自伤"的样本。
- **mock 走真实管线**：与 Memoria 的 offline scripted-LLM server 模式同族（都让测试覆盖真实路径）；Talorys 的 mock 是**进程内 provider**，Memoria 的是**HTTP server**——后者能测网络路径，前者更轻。
- **`enable_thinking: false`**：把成本决策写进 provider 构造，而非留给用户配置——与"确定性任务不用 AI"同源的保守取向。
- **失败的 embed 也计配额**（03 篇 §4.3）：预算防线"防自己"的细节，六家均无。

## 7. 对 Memoria 的可迁移结论

1. **限额双层（§5.1）**：默认值 + `LIMIT_CEILINGS` 硬天花板。Memoria 目前无预算防线——这是性价比最高的一项：六个数字 + 一个 max 校验即可。
2. **六计数器 + 按日分桶（§5.2）**：`ai_requests / input_tokens / output_tokens / tool_calls / scheduled_ai_runs / ai_errors`；列名封闭 union（Python 里可用 Literal 枚举 + 白名单校验）。
3. **计量双通道（§5.3）**：provider 实测优先、本地估算回落；`ai_requests` 按发起计；`tool_calls` 用执行器实际计数。Memoria 接入任何计费 LLM API 时都需要这套。
4. **嵌入请求独立计数（§5.4）**：语义检索的嵌入调用不占聊天额度——两类成本分开看，才能分别调参。
5. **额度耗尽文案带影响面与出路（§2.3/§5.4）**：告诉用户"什么还能用"与"去哪里调整"。Memoria 的降级提示应照此写。
6. **错误分类映射平台码（§2.3）**：配额/容量/模型不存在 → 稳定应用错误码 + 中文可读消息；`cause` 链递归展开。
7. **确定性 mock 走真实工具管线（§4）**：Memoria 的 offline scripted-LLM 已覆盖此思路；可补的是"mock 也遵守提案制措辞"与"按词切片模拟流式"两个细节。
8. **`prepareStep` 强制文本作答（§3.2）**：预算耗尽或最后一步强制 `toolChoice: "none"`——**保证轮次必有文字产出**。Memoria 的 LangGraph 工具节点应加等价保证（避免以工具调用收尾导致用户看到空白）。
9. **环形日志上限（§5.5）**：activity 1000 条、写入时顺带清理——Memoria 的日志类表都应有显式寿命。

**不适合搬**：4 字符/token 的粗估（中文场景偏差大，Memoria 应实测或引入更准估算）；`enable_thinking: false` 的硬编码（Memoria 的推理需求不同）；AI SDK 的 `prepareStep`/`stopWhen` API（LangGraph 有等价机制）；Workers AI 的错误码字符串匹配（Memoria 的 provider 错误形状不同）。

## 8. 证据索引

| 结论 | 文件:行 |
|---|---|
| ModelMessage/GenerateRequest（system 独立字段） | `apps/agent/src/ai/provider.ts:4-15` |
| ProviderTool 执行闭包由调用方注入 | `apps/agent/src/ai/provider.ts:22-28` |
| ToolRequest（maxIterations + toolBudgetExhausted） | `apps/agent/src/ai/provider.ts:30-36` |
| AgentEvent 四类事件 | `apps/agent/src/ai/provider.ts:38-42` |
| AIProvider 三方法接口 | `apps/agent/src/ai/provider.ts:44-53` |
| estimateTokens 统一估算尺 | `apps/agent/src/ai/provider.ts:55-58` |
| classifyAiError 平台码映射 + 文案出路 | `apps/agent/src/ai/provider.ts:60-93` |
| enable_thinking: false 成本决策 | `apps/agent/src/ai/workers-ai.ts:6-25` |
| stopWhen / prepareStep 强制文本 / onError | `apps/agent/src/ai/workers-ai.ts:62-82` |
| 流事件映射（tool-error → tool-end） | `apps/agent/src/ai/workers-ai.ts:85-121` |
| Mock 三用意图 + 走真实管线 | `apps/agent/src/ai/mock.ts:4-9,25-60` |
| planTools 七条意图正则 | `apps/agent/src/ai/mock.ts:69-111` |
| 流式切片 + 节奏延迟 | `apps/agent/src/ai/mock.ts:50-55` |
| 限额默认值 + 硬天花板 | `packages/shared/src/constants.ts` |
| 六计数器 + 封闭 union 列名 | `apps/agent/src/services/usage.ts:4,17-25` |
| 计量双通道（实测优先/估算回落） | `apps/agent/src/agent/runner.ts:170-211` |
| 额度检查（聊天/调度） | `apps/agent/src/services/usage.ts:53-59`、`runner.ts:101-106`、`talorys-agent.ts:129-136` |
| 嵌入用量独立表 | `apps/agent/src/semantic/embeddings.ts:163-180` |
| ActivityLog 环形 1000 条 | `apps/agent/src/services/usage.ts:62-76` |
| 用量表 DDL | `apps/agent/src/db/migrations.ts:140-148` |
| 设置项（limits/temperature/autoMemory/demoMode） | `apps/agent/src/services/settings.ts:6-15` |
