# Talorys 核心设计 · 04 工具系统与审批

> 研究对象：`rociiu/talorys` — 单用户个人 agent（Cloudflare Durable Object），v0.1.4，HEAD `2cc547c`
> 路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦：工具定义形状（`tools/registry.ts`）、三级权限、destructive 的 prepare/commit 提案制、ToolExecutor 四层预算、审批生命周期（`db/repositories/pending-actions.ts`）、工具实现范例
> 本篇是"destructive 审批"这一模式的完整样本，与 Memoria feat-066 提案制直接对应

---

## 1. 定位与全景

Talorys 的工具系统有两个不变量：

1. **能力面显式收窄**：`tools/index.ts:8-13` 注释原文——"Tools may only touch the owner's own data through the service layer: no shell, code execution, credentials or arbitrary network access."全部工具（19 个）只通过 `Services` 层触数据。
2. **破坏性动作在轮次内没有执行路径**：`destructive` 工具不是"加了确认参数的普通工具"，而是**另一种形状**——只有 `prepare`（解析目标）与 `commit`（执行），且 `commit` 只能由 owner 通过 API 触发。

```
工具定义（defineTool）
  ├─ ImmediateTool  : permission = read | write   →  execute(input, ctx)
  └─ DestructiveTool: permission = destructive    →  prepare(input, ctx) → {targetId, summary}
                                                     commit(targetId, ctx)

轮次内执行（ToolExecutor.execute）
  ├─ 校验：可用性 → 全局预算 → 每工具上限 → zod → 重复签名
  ├─ immediate  → execute
  └─ destructive → prepare → pendingActions.create → 返回"等待批准"提示给模型

轮次外执行（POST /actions/:id/approve，API 专属）
  └─ runApprovedAction：条件 UPDATE 原子认领 → commit(targetId)
```

## 2. 工具定义形状（`tools/registry.ts:24-59`）

### 2.1 公共基座（24-32）

```ts
interface BaseTool<S extends z.ZodType> {
  name: string;
  description: string;
  input: S;                              // zod schema（既校验输入也投影给模型）
  maxCallsPerTurn?: number;              // 单轮该工具调用上限（与全局预算叠加）
  label: (input: z.infer<S>) => string;  // UI 卡片文案，如 `Adding task "Buy milk"`
}
```

### 2.2 两种形状（34-49）

```ts
export interface ImmediateTool<S, R> extends BaseTool<S> {
  permission: "read" | "write";
  execute: (input, ctx: ToolContext) => R | Promise<R>;
}

/** A destructive tool never runs during the agent's turn. `prepare` resolves the target
 *  without changing anything; `commit` runs only after the owner approves that exact action. */
export interface DestructiveTool<S> extends BaseTool<S> {
  permission: "destructive";
  prepare: (input, ctx) => PreparedAction | Promise<PreparedAction>;
  commit: (targetId: string, ctx) => unknown;
}

/** The exact target of a destructive call, resolved before anything changes. */
export interface PreparedAction {
  targetId: string;
  summary: string;   // 展示给 owner 的审批卡文案，如 `Delete task "Buy milk"`
}
```

- **类型层面就分离**：`ToolDefinition = ImmediateTool | DestructiveTool`，TypeScript 保证 destructive 没有 `execute`、immediate 没有 `prepare/commit`。
- `defineTool`（51-53）只是恒等函数——给字面量提供类型推断。
- `ToolError`（61-66）：工具错误类型；执行器与审批路径都特判它（业务错误 vs 意外错误）。

### 2.3 工具上下文（8-15）

```ts
export interface ToolContext {
  services: Services;
  timezone: string;
  mode: "chat" | "scheduled";     // "scheduled" = 自动化运行（只读 + notify）
  conversationId?: string;        // 破坏性提案的归属会话
}
```

`mode` 是**权限降级的载体**：调度运行时执行器只暴露 read 工具（§4.1）。

## 3. ToolExecutor 四层预算（`registry.ts:76-151`）

每个轮次新建一个执行器（`runner.ts:158`），携带工具集、上下文、`{maxToolCalls}`。

### 3.1 可用性过滤（97-101）

```ts
available(): ToolDefinition[] {
  if (this.limits.maxToolCalls <= 0) return [];                     // 预算为 0 → 无工具
  return this.tools.filter((t) => this.ctx.mode === "chat" || t.permission === "read" || t.name === "notify_owner");
}
```

调度模式：只有 `read` 与 `notify_owner`——**"计划任务降权"落在工具过滤这一行**。

### 3.2 执行前的五道闸（111-133）

```ts
async execute(name, rawInput, callId?) {
  const tool = this.find(name);                                      // 1. 存在且在可用集
  if (!tool) throw new ToolError(`Tool "${name}" is not available.`);
  if (this.calls >= this.limits.maxToolCalls) {                      // 2. 全局预算
    throw new ToolError("Tool call limit reached for this request. Answer the owner with the information you already have.");
  }
  const used = this.perTool.get(name) ?? 0;
  if (tool.maxCallsPerTurn !== undefined && used >= tool.maxCallsPerTurn) {   // 3. 每工具上限
    throw new ToolError(`"${name}" was already used ${used} times in this request. Do not call it again.`);
  }
  const parsed = tool.input.safeParse(rawInput ?? {});               // 4. zod 校验
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    throw new ToolError(`Invalid input${issue ? ` at "${issue.path.join(".")}": ${issue.message}` : ""}.`);
  }
  const signature = `${name}:${stableStringify(parsed.data)}`;        // 5. 重复签名检测
  const repeats = this.signatures.get(signature) ?? 0;
  if (repeats >= 1) {
    throw new ToolError("This exact call was already made in this request. Use the earlier result instead of repeating it.");
  }
  this.calls++; this.perTool.set(name, used + 1); this.signatures.set(signature, repeats + 1);
  ...
}
```

**每条错误消息都是给模型的指令**，不只是失败通知：

- 全局预算耗尽 → "Answer the owner with the information you already have."（用已有信息作答，别硬撑）
- 每工具上限 → "Do not call it again."
- 重复调用 → "Use the earlier result instead of repeating it."（用早先的结果）

`stableStringify`（153-158）：对象键排序后序列化——`{a:1,b:2}` 与 `{b:2,a:1}` 视为同一签名。**内容签名检测是循环防护的廉价兜底**：模型陷入"调同一个工具同一参数"的死循环时，第二次调用就被拒绝并被告知改用已有结果。

### 3.3 破坏性分支（134-149）

```ts
if (tool.permission !== "destructive") return await tool.execute(parsed.data, this.ctx);

if (!this.ctx.conversationId) throw new ToolError(`"${name}" needs the owner's approval and can only be used in chat.`);
const prepared = await tool.prepare(parsed.data, this.ctx);
const action = this.ctx.services.pendingActions.create({
  conversation_id: this.ctx.conversationId,
  tool: tool.name,
  target_id: prepared.targetId,
  summary: prepared.summary,
});
if (callId) this.approvals.set(callId, action);       // 供 tool-end 事件挂审批卡
return {
  status: "awaiting_owner_approval",
  action: prepared.summary,
  note: "Nothing has changed yet. The owner now sees an Approve button for exactly this action. Briefly tell them what you proposed. Do not call this tool again for the same item and do not claim it is done.",
};
```

- **`prepare` 不改变任何东西**：解析目标（如按标题找任务）并生成 summary；找不到目标直接抛 `ToolError`（由各工具的 prepare 实现，如 `tasks.ts:145-148`）。
- 返回给模型的是一个**结构化状态 + 明确指令**：告诉它"什么都没变"、"别重复调用"、"别声称已完成"。模型据此向用户口头说明提案。
- `conversationId` 缺失（调度模式）→ 直接拒绝：破坏性动作只能在聊天里提案。

### 3.4 审批执行：`runApprovedAction`（160-181）

```ts
export async function runApprovedAction(tools, ctx, actionId): Promise<PendingAction> {
  const pending = ctx.services.pendingActions;
  const stored = pending.get(actionId);
  if (!stored) throw new NotFoundError("This action no longer exists.");
  const tool = tools.find((t) => t.name === stored.tool);
  if (tool?.permission !== "destructive") throw new NotFoundError("This action no longer exists.");
  if (!pending.resolve(actionId, "approved")) {                        // 原子认领
    const status = pending.view(actionId)?.status;
    throw new AppError("CONFLICT", status === "expired" ? "This request expired. Ask again to get a new one." : "This action was already handled.");
  }
  try {
    await tool.commit(stored.target_id, ctx);                          // 只对当初展示的目标
  } catch (error) {
    pending.markFailed(actionId, error instanceof ToolError ? error.message : "The action failed.");
    if (!(error instanceof ToolError)) console.error("Approved action failed", error);
  }
  return pending.view(actionId)!;
}
```

四个关键点：

1. **`resolve` 是条件 UPDATE**（见 §5.1）——同一提案至多被认领一次，并发点击 Approve 只有一个成功。
2. **commit 用存储的 `target_id`**，不用请求参数——"only on the target that was shown"（注释 161-163）。审批者批准的是当初那张卡上写的目标。
3. 工具名回查（168-169）：提案里的工具必须仍是 destructive 且存在（防工具改名/移除后的悬空提案）。
4. commit 失败 → `markFailed` 留痕（177-179），错误消息截 300 字符；非业务错误额外 console.error。

## 4. 审批生命周期（`db/repositories/pending-actions.ts`）

### 4.1 表与状态机（`db/migrations.ts:178-189`）

```sql
CREATE TABLE tal_pending_actions (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES tal_conversations(id) ON DELETE CASCADE,
  tool TEXT NOT NULL,
  target_id TEXT NOT NULL,
  summary TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','cancelled','failed')),
  error TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  resolved_at TEXT
)
```

- 存储四态 + **视图五态**：`present()`（20-23）把"pending 但已过 expires_at"显示为 `expired`——过期是时间推导的，不需要定时任务改状态。
- `PendingActionStatus` 五值（`packages/shared/src/schemas.ts:72`）：`pending | approved | cancelled | expired | failed`。

### 4.2 TTL 与清理（5, 32-50）

```ts
export const PENDING_ACTION_TTL_MS = 30 * 60_000;     // 30 分钟
// create 时：
expires_at = created_at + 30min;
// 顺带清理：
db.run(`DELETE FROM tal_pending_actions WHERE created_at < ?`, now - 30 天);
```

30 分钟批准窗口（防"隔天误点旧卡片"）+ 创建时顺带清理 30 天前的旧记录（**惰性清理，无定时任务**）。

### 4.3 原子认领（61-73）

```ts
/** Atomically moves a pending, unexpired action to `status`. Returns false if it was
 *  already resolved or has expired, so an action can run at most once. */
resolve(id, status: "approved" | "cancelled"): boolean {
  const at = now();
  return this.db.run(
    `UPDATE tal_pending_actions SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending' AND expires_at > ?`,
    status, at, id, at,
  ).changes === 1;
}
```

**条件 UPDATE 是唯一的并发控制**：`WHERE status='pending' AND expires_at > now` 让"检查 + 变更"原子完成，`changes === 1` 即认领成功。单 DO 的同步 SQLite 语义下这就是 CAS。

### 4.4 审批卡实时状态（75-82）

```ts
/** Refreshes approval cards stored on messages with each action's current status. */
withCurrentStatus(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => m.tools.some((t) => t.approval)
    ? {...m, tools: m.tools.map((t) => (t.approval ? {...t, approval: this.view(t.approval.id) ?? t.approval} : t))}
    : m);
}
```

- 消息里存的是**审批卡快照**（创建时的状态）；读取会话时用当前状态刷新——历史卡片始终显示最新状态（已批准/已取消/已过期）。
- 调用点：`runner.ts:110-111`（组装上下文前）与 `api/routes/chat.ts:27`（读会话时）。

### 4.5 结局回灌（`runner.ts:36-48`）

```ts
const APPROVAL_OUTCOME = {
  pending: "waiting for the owner's approval",
  approved: "approved by the owner and done",
  cancelled: "declined by the owner",
  expired: "expired without approval",
  failed: "approved but failed",
};
function withApprovalOutcomes(m: ChatMessage): ChatMessage {
  const notes = m.tools.flatMap((t) => (t.approval ? [`[${t.approval.summary}: ${APPROVAL_OUTCOME[t.approval.status]}]`] : []));
  return notes.length ? {...m, content: `${m.content}\n\n${notes.join("\n")}`.trim()} : m;
}
```

模型在后续轮次看到形如 `[Delete task "Buy milk": approved by the owner and done]` 的注记——**闭环反馈**：它知道自己的提案被批准了还是被拒了，不会重复提案也不会谎报"已删除"。

## 5. API 面（`api/routes/chat.ts:130-143`）

```ts
/** Owner approval of a destructive action the agent proposed. The agent has no way to call this. */
chatRoutes.post("/actions/:id/approve", async (c) => {
  const s = c.env.agent.services;
  const action = await runApprovedAction(ALL_TOOLS, {services: s, timezone: ..., mode: "chat"}, c.req.param("id"));
  return c.json({ action });
});

chatRoutes.post("/actions/:id/cancel", (c) => { /* resolve(id, "cancelled") */ });
```

- **审批通道是 API 专属**：工具集里没有"批准"工具，模型无法自我批准。注释原文："The agent has no way to call this."
- `approve` 与 `cancel` 都是 POST + CSRF 头（见 07 篇），会话 cookie 认证。
- 语义模块的中间件挂在 `/actions/*` 上，在 approve 成功后清理 `forget_memory` 的向量（见 03 篇 §7.3）。

## 6. 工具实现范例（`tools/tasks.ts`、`tools/memories.ts`）

### 6.1 六个工具一览（`tools/index.ts:14-21`）

`taskTools`(5) + `noteTools` + `projectTools` + `memoryTools`(4) + `reminderTools` + `searchTools`，共 19 个。启动时检查重名（23-27）：

```ts
const names = new Set<string>();
for (const t of ALL_TOOLS) { if (names.has(t.name)) throw new Error(`Duplicate tool name: ${t.name}`); names.add(t.name); }
```

### 6.2 五件套 + 两个模式的完整样例（`tasks.ts:44-155`）

| 工具 | 权限 | 上限 | label 样例 |
|---|---|---|---|
| `create_task` | write | 5 | `Adding task "Buy milk"` |
| `list_tasks` | read | 3 | `Checking open tasks` |
| `update_task` | write | 5 | `Updating task "Buy milk"` |
| `complete_task` | write | 10 | `Completing "Buy milk"` |
| `delete_task` | **destructive** | 3 | `Proposing to delete "Buy milk"` |

**destructive 完整实现**（138-155）：

```ts
defineTool({
  name: "delete_task",
  description: "Propose permanently deleting a task. The owner must approve it in the app before anything is deleted.",
  permission: "destructive",
  maxCallsPerTurn: 3,
  input: z.object({ task: z.string().min(1).describe("Task id or exact/partial title") }),
  label: (i) => `Proposing to delete "${i.task}"`,
  prepare: (i, ctx) => {
    const task = resolveTask(i.task, ctx);                                 // 解析（可能抛 ToolError）
    return { targetId: task.id, summary: `Delete task ${quoteTitle(task.title)}` };
  },
  commit: (id, ctx) => {
    const task = ctx.services.tasks.get(id);                               // 目标可能已被别处删除
    if (!task) throw new ToolError("This task no longer exists.");
    ctx.services.tasks.delete(task.id);
    ctx.services.activity.record("task.deleted", `Deleted task "${task.title}" (approved agent action)`);
  },
})
```

- **description 自述"需要批准"**（140）——模型知道这个工具的产出是提案而非执行。
- `label` 用 "Proposing to…" 与 commit 的 "Deleted…" 区分阶段（UI 文案层面也体现提案制）。
- `commit` 里再查一次目标存在性（150-151）：从提案到批准之间目标可能消失。
- activity log 标注 `(approved agent action)`——审计时区分"agent 提案 + 人工批准"与"用户直接操作"。

### 6.3 错误文案即修复指令

| 场景 | 错误消息 | 文件:行 |
|---|---|---|
| 日期格式错 | `Could not understand the date "X". Use YYYY-MM-DD or YYYY-MM-DDTHH:MM.` | `tasks.ts:14` |
| 任务匹配不到唯一项 | `No single task matches "X". List tasks to find the exact one.` | `tasks.ts:20` |
| 项目不存在 | `Project "X" does not exist. Create it first with create_project.` | `tasks.ts:27` |
| 工具不可用 | `Tool "X" is not available.` | `registry.ts:113` |
| 预算耗尽 | `…Answer the owner with the information you already have.` | `registry.ts:115` |

模式统一：**说明问题 + 给出正确的下一步动作**。

### 6.4 呈现层压缩（`presentTask` 32-42）

```ts
export function presentTask(t: Task, tz: string) {
  return { id: t.id, title: t.title, status: t.status, priority: t.priority,
           due: formatLocal(t.due_at, tz),                                   // owner 本地时区
           ...(t.description ? {description: t.description.slice(0, 300)} : {}) };  // 描述截断
}
```

工具返回值是**为模型压缩过的呈现**：日期转本地时区、描述截 300 字符、空字段省略——控制 token 且减少模型误解。

### 6.5 目标解析（`resolve` 模式）

- 任务：`ctx.services.tasks.resolve(ref)`——id 或标题（精确/部分）；**匹配不唯一时返回 null**，工具抛错让模型先 list（`tasks.ts:18-22`）。
- 记忆：按 id（`memories.ts:54-57`），不存在抛 `ToolError("Memory not found.")`。
- 项目：`resolveProject`（24-30）三态——undefined 保持、null/"" 清空、其他解析。

## 7. 与既有研究的对照

- **对比 OpenMuse**（`04b-openmuse-alpha-surfaces.md`）：OpenMuse 的审批是 `waiting_approval` 一等状态 + 审批通道与对话隔离 + exit receipts；Talorys 是 prepare/commit 两函数 + pending 表 + 结局注记。OpenMuse 更重（任务引擎级），Talorys 更轻（单表 + 条件 UPDATE）。**Talorys 的形态与 Memoria feat-066 提案制更接近**。
- **对比 hermes**（`hermes/08-security.md`）：hermes 的审批是"不可绕 floor → allowlist → 正则 → guardian LLM → 人 → 持久化决定"的多层链，Talorys 是单一结构（destructive 类型）；hermes 面对的是 shell/网络等开放能力，Talorys 的能力面本身收窄到"只碰自己的数据"，所以一层结构够用——**威胁模型决定防御层数**。
- **对比 ZCode/DeepSeek Harness 的模型可见面最小化**：它们做的是"内部元数据不进请求"；Talorys 做的是"执行能力不进轮次"——同一个思路推到极致。
- **重复签名检测**：六家 + hermes 均无显式实现（ZCode 的 Bash 只读判定、Codex 的 sandbox 是别的维度）；Talorys 用 20 行解决了工具死循环的一个主要形态。
- **审批结局注记**：全部研究中唯一实现；最接近的是 hermes 的压缩交接注记（目的不同）。

## 8. 对 Memoria 的可迁移结论

1. **prepare/commit 分离（§2.2）**：Memoria 提案制（feat-066）若当前是"工具带 confirmed 参数"，升级为两函数形状——目标解析与执行彻底分离，审批卡展示的是**服务端解析出的确切目标**而非模型转述。这是"审批者审的就是生效的那条"的保证。
2. **原子认领（§4.3）**：`UPDATE … WHERE status='pending' AND expires_at > now` + `changes===1`。Memoria 若用 SQLite 可直接照抄；并发双击 Approve 只会执行一次。
3. **审批卡实时状态刷新（§4.4）**：消息存快照 + 读取时刷新——历史卡片永远显示最新状态；避免"审批完了卡片还显示 pending"。
4. **结局注记回灌历史（§4.5）**：五态映射 + 一行注记。成本极低，防重复提案与谎报完成。
5. **TTL + 惰性清理（§4.2）**：30 分钟窗口 + 创建时顺带清理旧记录（无定时任务）。
6. **重复签名检测（§3.2）**：`name + 键排序 JSON`；错误消息"use the earlier result"。
7. **错误文案即修复指令（§6.3）**：Memoria 工具错误应统一模式"问题 + 正确下一步"。
8. **呈现层压缩（§6.4）**：工具返回值按需裁剪（时区转换、长文本截断、空字段省略）——检索结果注入时尤其重要（呼应 hermes 篇的三层防溢出）。
9. **调度降权在工具过滤层（§3.1）**：`mode === "scheduled"` 只给 read + notify；Memoria 的定时分拣（feat-068）与邮件自动化应同样把"只读"落在工具集而不是 prompt。
10. **activity 标注人工批准（§6.2）**：`(approved agent action)`——审计轨迹区分自动与人工。

**不适合搬**：`stableStringify` 的完整实现（Memoria 若用 JSON 规范化有现成库）；19 个工具的具体集合（产品面不同）；"无 shell/无网络"的能力收窄（Memoria 邮件需要出站，只搬"能力面显式清单"的表述纪律）。

## 9. 证据索引

| 结论 | 文件:行 |
|---|---|
| 能力面收窄声明 + 工具清单 + 重名检查 | `apps/agent/src/tools/index.ts:8-27` |
| BaseTool 五件套 | `apps/agent/src/tools/registry.ts:24-32` |
| ImmediateTool / DestructiveTool 类型分离 | `apps/agent/src/tools/registry.ts:34-49` |
| PreparedAction（targetId + summary） | `apps/agent/src/tools/registry.ts:17-22` |
| ToolContext（mode 降权载体） | `apps/agent/src/tools/registry.ts:8-15` |
| 可用性过滤（scheduled 只读） | `apps/agent/src/tools/registry.ts:97-101` |
| 五道闸 + 错误即指令 | `apps/agent/src/tools/registry.ts:111-133` |
| stableStringify 内容签名 | `apps/agent/src/tools/registry.ts:153-158` |
| 破坏性分支（prepare + create + 返回指令） | `apps/agent/src/tools/registry.ts:134-149` |
| runApprovedAction（原子认领 + 用存储目标） | `apps/agent/src/tools/registry.ts:160-181` |
| pending 表 DDL + 四态 CHECK | `apps/agent/src/db/migrations.ts:178-189` |
| TTL 30 分钟 + 惰性清理 30 天 | `apps/agent/src/db/repositories/pending-actions.ts:5,32-50` |
| resolve 条件 UPDATE（至多一次） | `apps/agent/src/db/repositories/pending-actions.ts:61-73` |
| withCurrentStatus 卡片刷新 | `apps/agent/src/db/repositories/pending-actions.ts:75-82` |
| 结局五态映射 + 注记注入 | `apps/agent/src/agent/runner.ts:36-48` |
| approve/cancel API（agent 无法调用） | `apps/agent/src/api/routes/chat.ts:130-143` |
| delete_task 完整 destructive 实现 | `apps/agent/src/tools/tasks.ts:138-155` |
| 错误文案即修复指令（四处样例） | `apps/agent/src/tools/tasks.ts:14,20,27`、`registry.ts:113,115` |
| presentTask 呈现压缩 | `apps/agent/src/tools/tasks.ts:32-42` |
| 目标解析 resolve 模式 | `apps/agent/src/tools/tasks.ts:18-30`、`tools/memories.ts:54-57` |
| 五态枚举 | `packages/shared/src/schemas.ts:72-82` |
