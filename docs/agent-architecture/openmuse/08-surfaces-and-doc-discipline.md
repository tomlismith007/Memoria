# OpenMuse 核心设计 · 08 次表面与文档纪律

> 研究对象：`CopilotKit/OpenMuse` — 个人 agent，MIT，TypeScript；HEAD `1ac68f3`（main，2026-10-11）
> 路径相对仓库根，`文件:行` 均为实读行号；结论只来自源码
> 本篇聚焦：六个次表面的机制共性（Ideas / Goals / Documents / Finance / Personal context / Rich Threads）、HTTP 路由面（`engine/routes.ts`）、文档四件套的咬合（`docs/FEATURES.md`、`VERIFICATION.md`、`EXPERIENCE.md`、`ROADMAP.md`）、演示脚本化（`docs/DEMO.md`）
> 与 [../04b-openmuse-alpha-surfaces.md](../04b-openmuse-alpha-surfaces.md) §4-§10/§12 重叠处只做引用 + 增量；本篇按**机制维度**重组，不复制 04b 的 10 表面结构

---

## 1. 定位与全景

```
次表面                 驱动方式                  是否经模型   持久化
──────────────────────────────────────────────────────────────────
Ideas                  三条正则 + hash 去重          否        ideas
Goals & Tracking       Goal ↔ task 双向联动          否        goals/tasks/monitors
Documents              附件→PDF→typed input→审批      否*      tasks/files/actions
Finance                101 行纯函数 CSV 状态机        否        tasks/agent-artifacts
Personal context       三字段 editable/forgettable     否        memories/agent-settings
Rich Threads           CopilotKit Intelligence        —        （外部）
```

\* Documents 的表单**填充**由模型驱动（`fill_pdf` 工具），但"该填哪些字段"由用户 typed input 提供；链路本身的推进是确定性状态机。

**六者共享的模式**：**确定性优先**（五个完全不经模型）；**幂等 id**（Ideas 用内容 hash、Goals 用固定 id、Documents 用 `deterministicFileId`）；**来源可溯**（Ideas/Documents 带 `evidence`、Finance 带 CSV 行数、Memory 带 `source`）；**人可干预**（Ideas 三态、Memory 可编辑可遗忘、Goal 暂停级联暂停任务）。

## 2. Ideas：三条正则 + hash 去重 + 已处理集排除

### 2.1 三条规则（`service.ts:578-633`）

```ts
// 规则 1：有附件 + 关键词 → document 类建议
for (const mail of w.mail.filter((m) => !obsolete("document", m.id) && m.attachments.length &&
  /form|permission|complete|fill|sign/i.test(`${m.subject} ${m.body}`)).slice(0, 5)) {
  const id = hash(`document:${mail.id}:${mail.body}`);
  await this.db.insertIfAbsent(owner, "ideas", { id, title: `I can help with ${mail.subject}`, … });
}
// 规则 2：协调类关键词 → agent 类建议
for (const mail of w.mail.filter((m) => !obsolete("agent", m.id) &&
  /coffee|meet|available|schedule/i.test(`${m.subject} ${m.body}`)).slice(0, 5)) {
  await this.db.insertIfAbsent(owner, "ideas", { id: hash(`coordination:${mail.id}`), … });
}
// 规则 3：无里程碑的活跃目标 → plan 类建议
for (const goal of await this.db.listByStatus<Goal>(owner, "goals", "active"))
  if (!goal.milestones.length) {
    const id = hash(`goal:${goal.id}:${goal.description}`);
    await this.db.insertIfAbsent(owner, "ideas", { id, …, evidence: [{ id: goal.id, kind: "user", … }] });
  }
```

**正则而非模型**；**每条规则最多 5 条**（`.slice(0, 5)`）防一次生成几十条建议。**正则的局限如实存在**：`"We need to complete the report"` 会命中 `complete` 产生 document 建议（有 `m.attachments.length` 兜底）；协调类规则没有附件要求，误报率更高（`"available"` 是常见词）。**这是有意的取舍**：宁可多给一条可驳回的建议，也不漏掉真实机会——可驳回（`dismiss`）是误报的出口。

### 2.2 三种 id 构造的差异

```ts
hash(`document:${mail.id}:${mail.body}`)      // 规则 1：含正文
hash(`coordination:${mail.id}`)               // 规则 2：只含邮件 id
hash(`goal:${goal.id}:${goal.description}`)   // 规则 3：含目标描述
```

**规则 1 的 id 含 `mail.body`**——邮件正文变化（新回复）会生成新建议；规则 2 只含 `mail.id`——同一邮件的协调建议只产生一次。**差异是有意的**：文档处理需要看最新正文（可能有新要求），协调建议只看"这封邮件提到聚会"这个事实。

### 2.3 已处理集排除（`service.ts:555-577`）

```ts
const sentIds = new Set(w.mail.filter((mail) => /^Sent\b/i.test(mail.label)).map((mail) => mail.id));
const completedSources = new Set((await this.db.listByStatus<AgentTask>(owner, "tasks", "succeeded"))
  .filter((task) => typeof task.input.messageId === "string")
  .map((task) => `${task.kind}:${task.input.messageId}`));
const obsolete = (kind, messageId) => typeof messageId === "string" &&
  (sentIds.has(messageId) || completedSources.has(`${kind}:${messageId}`));
// Retire earlier suggestions as well as preventing new duplicates. A concurrent
// acceptance wins its own compare-and-swap and is never overwritten here.
for (const idea of await this.db.listByStatus<Idea>(owner, "ideas", "new"))
  if (obsolete(idea.kind, idea.input.messageId))
    await this.db.compareAndSwap(owner, "ideas", idea.id, { status: "new" }, { status: "dismissed" });
```

**两条排除规则**：**已回复**（label 以 `Sent` 开头）——`docs/FEATURES.md` 的表述 "Sent replies and completed matching work are excluded"；**已有成功任务处理过**（`kind:messageId` 组合）。

**注释里的并发纪律**：CAS 带条件——若用户在这一瞬间点了"接受"，CAS 失败，建议**不会被误驳回**。**已处理集的键是 `kind:messageId`** 而非只有 messageId——同一封邮件可以既产生 document 建议（填表单）又产生 agent 建议（安排聚会），两者互不排除。

### 2.4 刷新节流（`service.ts:110-124`）

```ts
if (!value.lastIdeasAt || Date.now() - Date.parse(value.lastIdeasAt) > 15 * 60000)
  await this.refreshIdeas(owner).catch(async () => {
    await this.notify(owner, "Source refresh needs attention",
      "Reconnect the source or refresh Ideas to see the error.", undefined,
      `source-error:${Math.floor(Date.now() / 3600000)}`);
  });
```

**15 分钟节流**由 `maintain()` 的 60 秒循环 + `lastIdeasAt` 实现。失败通知按**小时**聚合——避免每 60 秒报一次错。

### 2.5 接受与任务联动（`service.ts:638-718`）

```ts
if (idea.status === "new") {
  // A task already working on (or done with) the same email is opened instead of copied.
  const handling = (await this.db.list<AgentTask>(owner, "tasks")).find((task) =>
    task.kind === kind && task.input.messageId === input.messageId &&
    task.status !== "failed" && task.status !== "cancelled");
  if (handling) return /* CAS 指向 handling.id */;
  const claimed = await this.db.compareAndSwap<Idea>(owner, "ideas", id, { status: "new" },
    { status: "accepted", taskId: hash(`task:idea:${id}`), prompt: prompt ?? idea.prompt });
  …
}
```

**"已有人在做就打开而非复制"**——接受建议前先找同一邮件的活跃任务，找到就把建议指向它。这是"幂等"在**语义层**的实现，不只是 id 去重。

**两阶段 CAS**：先把建议标 `accepted` 并写入**预定的** taskId（`hash("task:idea:" + id)`），再创建任务。若创建失败，`maintain()` 会发现"accepted 但任务不存在"并重试（`service.ts:94-109`）。**接受时自动建 goal**（`:689-698`）：若建议没有 `goalId`，用 `hash("idea-goal:" + id)` 自动创建——形成"建议 → 目标 → 任务"的链条。

## 3. Goals：双向联动

**任务 → 里程碑**（`service.ts:911-927`）：任务成功时，若属于某 goal 且**自身不是里程碑任务**，被追加为该 goal 的一个**已完成里程碑**（`id = task.id`）。CAS + 最多 8 次重试 + 幂等判据。详见 [07 篇](07-data-platform.md) §3.1 的丢更新分析。

**目标 → 任务**（`service.ts:374-386`）：`compareAndSwap(owner, "goals", id, {}, patch)` 保存后，若 `patch.status === "paused"` 则遍历 `listByGoalId` 的全部任务，对非终态且非 paused 的逐个 `control(..., "pause")`。**暂停目标级联暂停其全部未完成任务**——"目标"作为容器的语义体现。

注意 `compareAndSwap(owner, "goals", id, {}, patch)` 的 expected 是**空对象 `{}`**——任何行都满足 `data @> {}`，所以这是"无条件更新 + 存在性检查"（不存在返回 null）。**这是一个利用 `@>` 语义的技巧：空对象是"永真条件"**。

**Goal 创建**（`:360-373`）：里程碑 id 用 `randomUUID()`（不是标题派生）——因为标题可重命名（`setMilestoneDone` 的注释明确提到 "preserving concurrent … renames"）。

## 4. Finance：101 行纯函数 CSV 状态机

### 4.1 纯函数证明

`apps/server/src/engine/finance.ts` 全文 **100 行**（`wc -l` = 100）：唯一 import 是 `import { z } from "zod";`（`:1`）；全文 grep 无 `fetch`/`fs.`/`require`/`await`/`process.`/`new Date`；无模块级可变状态、无随机数；唯一调用点在 `service.ts:868`。**同一份 CSV 永远得到同一份报告**。

### 4.2 手写 CSV 状态机（`finance.ts:8-40`）

```ts
const rows: string[][] = [];
let row: string[] = [], cell = "", quoted = false;
for (let i = 0; i <= csv.length; i++) {
  const c = csv[i];
  if (c === '"') {
    if (quoted && csv[i + 1] === '"') { cell += '"'; i++; }
    else if (!quoted && cell.length) throw new Error("Invalid quoted CSV field");
    else { quoted = !quoted; if (!quoted) { const next = csv[i + 1];
      if (next !== undefined && next !== "," && next !== "\n" &&
          !(next === "\r" && (csv[i + 2] === "\n" || csv[i + 2] === undefined)))
        throw new Error("Invalid quoted CSV field"); } }
  } else if (!quoted && (c === "," || c === "\n" || c === undefined)) {
    row.push(cell.replace(/\r$/, "")); cell = "";
    if (c !== ",") { if (row.some((v) => v.trim())) rows.push(row); row = []; }
  } else if (c !== undefined) cell += c;
}
```

**三个状态变量** + 循环上界 `i <= csv.length` 让 `c === undefined` 充当 **EOF 终结符**（"最后一行没有换行符"也能正确落盘）。

**严格的引号处理**：引号内 `""` → 转义为一个 `"`；引号内出现非 `""` 的引号 → 闭合，且**后面必须紧跟 `,` / `\n` / CRLF / EOF**，否则报错（堵住 `"abc"def`）；不在引号态且 cell 非空时遇 `"` → 报错（`abc"def`）。**空行跳过**：`row.some((v) => v.trim())`。

### 4.3 校验清单

大小 ≤500000 字符（`:5`）；剥离 UTF-8 BOM `0xfeff`（`:7`，注释理由 "Excel and many bank exports start a UTF-8 CSV with a byte order mark. It is not part of the first header."）；引号闭合（循环后 `if (quoted) throw`，`:41`）；表头必须含 `date,description,amount,category` 且无重复（`:42-50`）；行数 1–5000 且每行列数等于表头长度（`:51-55`）；日期过 `z.iso.date()`（`:59`）；金额匹配 `/^[-+]?\d+(?:\.\d{1,2})?$/` 且转 cents 后 `isSafeInteger` 且 `≤1e12`（`:59,64`，**转 cents 再校验避免浮点误差累积**）。

### 4.4 分类与汇总（`finance.ts:75-100`）

```ts
const expenses = transactions.filter((t) => t.cents > 0).reduce((n, t) => n + t.cents, 0),
  income = -transactions.filter((t) => t.cents < 0).reduce((n, t) => n + t.cents, 0);
…
if (t.cents > 0) grouped.set(t.category, (grouped.get(t.category) ?? 0) + t.cents);
```

**金额符号约定**（`:2` 注释原文）："CSV amounts use positive expenses and negative income. No currency conversion is inferred." 正数 = 支出、负数 = 收入（取反求和）；只对支出按 `category` 分组降序；空 category 兜底 `"Uncategorized"`（`:71`）；输出的 `amountConvention` 字段把这个约定**写进结果**（`:99`）：

```ts
amountConvention: "Positive expenses; negative income. Values use the source currency; no currency conversion.",
```

**这是"数据自带解释"的做法**：报告里带上"这些数字怎么读"，消费者不需要去读代码。

### 4.5 产卡不经模型（`service.ts:865-889`）

```ts
if (task.kind === "finance") {
  await context.event("step", "Analyzing the imported transactions");
  const csv = z.string().parse(task.input.csv);
  const data = analyzeSpending(csv);
  const artifact = await this.artifact(owner, task, "finance", "Spending tracker",
    `${data.count} transactions · ${data.spending.toFixed(2)} spent`, data);
  task = await context.checkpoint({ artifactIds: [artifact.id], evidence: [{…}] });
  return this.finish(task, context, artifact.summary);
}
```

**整个 finance 任务不调用模型**：`execute` 分派时直接走 finance 分支，不进 `executeModelTask`。所以"没有配置 MODEL 也能用"（`model.ts:26` 原文："The document, monitor and finance workflows can run without a model."）。

## 5. Documents：全链路状态机

**第一段：找源文件**（`service.ts:974-996`）——三层容错：邮件必须在当前快照里（否则明确报错"Choose a current email with a PDF attachment to start this task"）；必须有附件；**文件已在库里就用库里的，404 才去导入**（避免重复导入）。

**第二段：要 typed input**（`:997-1020`）：

```ts
const fields = z.record(z.string(), z.union([z.string(), z.boolean()])).optional().parse(task.input.fields);
if (!fields || !Object.keys(fields).length) {
  const names = file.fields?.filter((f) => f.type !== "unsupported").map((f) => f.name).join(", ");
  if (!names) throw new Error("This PDF has no supported fillable fields. Open it in Files to review it.");
  return { status: "waiting_input",
    question: `Enter the form values you want to use. Supported fields: ${names}. The original PDF will stay intact.`,
    state: { ...task.state, source, missingFields: … } };
}
```

**问题文案自带三个信息**：要填什么（字段名列表）、怎么填、以及**原件不会被改**（"The original PDF will stay intact."）。**无可用字段时明确报错**（不是静默失败）。

**第三段：填充 + 提案**（`:1021-1059`）：`if (!filledId)` 才填充（重启后的任务不会重复填充，`deterministicFileId` 也保证同一份内容同一 id）；回信地址从原邮件取（`to: [source.mail.from]`）、**主题自动加 `Re:`**（若还没有）、**threadId 与 replyToMessageId 都带上**（保证回信进同一会话）；默认正文只在用户没提供 `task.input.reply` 时使用；最后调 `prepare(..., "document-reply", ctx)` 生成审批单并返回 `waiting_approval`。

**plan 三段同步推进**：第一段后 `i === 0 ? "succeeded" : "pending"`（`:993`）；第三段后 `i <= 1 ? "succeeded"`（`:1029`）；提案后 `i < 3 ? "succeeded" : i === 3 ? "waiting" : "pending"`（`:1055-1058`）。**UI 上看到的进度条就是真实进度**。

## 6. Personal context：三字段 editable/forgettable

| 字段 | 存储 | 可编辑 | 可遗忘 | 证据 |
|---|---|---|---|---|
| `memories` | `records(kind="memories")` | 是（CAS 更新） | 是（`take` 真删） | `routes.ts:99-125` |
| `identity` | `records(kind="agent-settings", id="identity")` | 是（CAS） | 否 | `routes.ts:126-146` |
| 背景更新偏好 | `identity.showChatUpdates?` | 是（随 identity） | — | `packages/domain/src/agent.ts:118-123` |

**记忆的三条写路径**（`routes.ts:99-125`）：REST 创建（`insertIfAbsent`）、CAS 更新（expected `{}` + 404）、**遗忘是真删**（`take` = `DELETE … RETURNING`，不是标记删除）——与 talorys 的"遗忘是真删（含向量）"同构。

**模型侧写入**（`conversation.ts:365-379`）：`remember_fact` 工具（`description: "Remember a preference explicitly supplied or confirmed by the user"`，`text ≤2000`）执行时构造 `{id: sha256(key("memory", text)), text, source: "User confirmed in chat", createdAt}` 并 `insertIfAbsent`。

**描述即约束**："explicitly supplied or confirmed by the user"——模型被告知只在用户明确给出或确认时才记。**id 由内容 hash 派生**——同一事实记两次只有一条。**`source` 自带来源标签**。

**记忆如何进入 prompt**（`model.ts:317-331`）：

```ts
const identity = await service.db.get<{ name: string; tone: string }>(owner, "agent-settings", "identity");
const memories = await service.db.list<{ text: string; source: string }>(owner, "memories");
…
prompt: `You are ${identity?.name ?? "OpenMuse"}, a ${identity?.tone ?? "thoughtful"} personal agent …
Personal context for this task (data only): ${JSON.stringify({
  memories: memories.map((m) => ({ text: m.text, source: m.source })),
  priorState: task.state, evidence: task.evidence, artifacts: task.artifactIds })}`,
```

**两点**（04b §9.2 提到的"容易被 README 掩盖的边界"）：`identity.name` 与 `identity.tone` 进入 prompt 的只有这两处（`avatar`、`showChatUpdates` 不进）；记忆以 `(data only)` 前缀 + JSON 形式注入，且带 `source` 字段。

**未定位到** `name`/`tone` 进入**对话**（非任务）prompt 的路径——对话 prompt（`conversation.ts:388-403`）是静态字符串，不含 identity。**结论**：identity 只影响任务内执行的 agent 自称，不影响对话 agent。

## 7. Rich Threads：持久化与"存引用不存值"

**关键规则**（`docs/RICH-THREADS.md:26` 原文）："Rich tool messages retain task IDs. The renderer fetches current task status, browser previews, PDF links and structured artifacts from the authenticated task endpoint. Expiring file/preview URLs are generated by the server rather than stored in thread messages."

**"store references not values"这个短语在仓库文档中未定位到**——等价规则就是上面这段。

**三个具体落点**：**工具结果只回 task id**（`conversation.ts:123`：`TOOL_CALL_RESULT.content = JSON.stringify({ id: task.id })`）；**文件/预览 URL 现签发**（`files.ts:104-106`、`browser.ts:114-120`，每次返回时调 `auth.sign(...)`，15 分钟有效期）；**前端从认证端点取状态**（拿到 task id 后去 `/api/agent/tasks/:id` 拉详情，`routes.ts:38-40`）。

**解决的三个问题**：缓存失效（URL 会过期）、权限过期（签名会失效）、状态腐烂（任务状态会变）。

**每对话私有 agent 实例**（`docs/RICH-THREADS.md:22`）："Selecting a saved conversation mounts a private `useAgent({ agentId, runtimeAgentId, threadId })` instance and calls `copilotkit.connectAgent` to replay the thread. Visited chats remain mounted during navigation, preserving their drafts and queues. Stop explicitly requests `copilotkit.stopAgent`."——这解释了为什么队列、草稿、错误横幅都是**每对话独立**的。

**验证边界**（`docs/RICH-THREADS.md:42`）："They do not replace a live account test for Intelligence WebSocket persistence/replay. That test requires a configured project key."——**明确声明 mock 测试不能替代什么**。

## 8. HTTP 路由面（`engine/routes.ts` 全文 168 行）

挂载于 `/api/agent`（`app.ts:159`）。

| 行 | 方法 + 路径 | 用途 |
|---|---|---|
| 31 | GET `/` | owner 快照 |
| 32-37 | POST `/tasks` | 建任务，201，可带 `requestId` 幂等键 |
| 38-40 | GET `/tasks/:id` | 任务详情（含 events/artifacts/files/browsers） |
| 41-46 | POST `/tasks/:id/control` | pause/resume/cancel/retry |
| 47-59 | POST `/tasks/:id/input` | 回答输入（answer + 可选 fields） |
| 60-62 | POST `/goals` | 建目标，201 |
| 63-66 | POST `/goals/:id` | 更新（status/milestones patch） |
| 67-77 | POST `/goals/:id/milestones/:milestoneId` | 勾选里程碑 |
| 78-80 | POST `/monitors` | 建监控，201 |
| 81-86 | POST `/monitors/:id/control` | pause/resume/stop/check |
| 87 | POST `/ideas/refresh` | 刷新建议 |
| 88-98 | POST `/ideas/:id` | accept/dismiss（可带 prompt） |
| 99-108 | POST `/memories` | 建记忆，201 |
| 109-120 | POST `/memories/:id` | CAS 更新 |
| 121-125 | POST `/memories/:id/forget` | `take` 删除 |
| 126-146 | POST `/identity` | CAS 写 identity，冲突 409 |
| 147-149 | GET `/notifications` | 列通知 |
| 150-160 | POST `/notifications/:id/read` | CAS 标记已读 |
| 161-166 | POST `/sample-page` | 仅 sample 模式，否则 404 |

**路由层的三条纪律**：**不认证**（认证在 `app.ts:133-144` 中间件，路由只读 `c.get("owner")`）；**每个调用把 owner 作为第一参数**；**模式限定的端点显式 404**：

```ts
app.post("/sample-page", async (c) => {
  if (service.config.mode !== "sample") throw new AppError("Not found", 404);
  …
});
```

**注意 control 与 input 是分开的**——"控制任务"与"回答任务"是两种不同的用户意图。`control` 有四个动作且各有前置校验（见 [02 篇](02-task-engine.md) §2.2），`input` 只接受 `waiting_input` 状态的任务。

**幂等键的两种传递方式**：请求体字段（`routes.ts:33-36` 的 `requestId`，REST 调用方显式提供）；工具参数 hash（`conversation.ts:338`，对话内自动派生）。

## 9. 文档四件套的咬合

### 9.1 FEATURES.md：能力边界的三列声明

三列表头（`:7-8`）：`| Area | Current implementation | Remaining extension |`。代表行（`:9,14,16`）：

```
| Chat / delegated work | Native CopilotKit chat, direct mail and time-bounded primary calendar reads, durable tasks and confirmed outcomes | Live model/provider acceptance testing |
| Gmail / Calendar | Google OAuth; complete threads; saved drafts; calendar/event CRUD with reviewed versions | Live Google acceptance, recurrence editing, other connectors |
| Generated results | Plans/reports/comparisons, finance CSV metrics, and scripts in the private Linux workspace | Managed tool installation/versioning and image/audio generation |
```

**每行都是"已实现 | 未实现"配对**——不允许出现只有"已实现"没有边界的行。**三层免责措辞**（`:3,21-23,25`）：定位句（"This inventory describes the current implementation and remaining extensions. Live providers and optional infrastructure require separate configuration and validation."）；具体限制（"The Linux computer is disabled until configured on the server and has no network access."、"The sample agent's canned replies do not provide this model tool."）；**末段**：

```
The implementation and validation details are in [VERIFICATION.md](VERIFICATION.md).
Planned extensions are not claims of current support. Priorities are tracked in the [roadmap](../ROADMAP.md).
```

**"Planned extensions are not claims of current support."**（`:25`）——本系列反复引用的文档纪律核心。

### 9.2 VERIFICATION.md：验收矩阵 + Boundary 列

结构：`## Automated checks`（`:5`）→ `## Agent browser verification`（`:14`）→ `## Feature acceptance matrix`（`:25`）→ `## Release fixes and interface polish`（`:44`）→ `## Reproduce`（`:58`）→ `## Still outside this release`（`:80`）。

**Boundary 列表头**（`:27`）：`| Area | Evidence | Boundary |`。代表行：

```
:29  | CopilotKit chat | Real runtime streams AG-UI events; … | Live model quality and provider-account acceptance are pending. |
:33  | Gmail / Calendar | Real adapter code with controlled HTTP fixtures covers … | No live Google credentials were supplied. A real-account acceptance run remains required. |
:34  | Browser | Actual Chromium screenshots … | A separate Chromium worker; no automatic booking/payment or hostile-tenant isolation. |
:39  | Identity / memory | Edit, persist, and forget paths are tested through the authenticated API. | Single owner per deployment. |
```

**Boundary 列是这份文档的灵魂**——每行都写明"这个证据不能证明什么"。`:78` 的总括："No real mail was sent, purchase made, or private Google account connected during release verification." `## Still outside this release`（`:80-82`）列出未实现项：健康/银行/社交/WhatsApp 连接器、托管工具注册表、语音/媒体生成、自动购买预订、移动推送、多租户身份、完整桌面 VM 隔离。**这份文档主动列出自己的缺口**。

### 9.3 EXPERIENCE.md：交互合同

全文 26 行，四个小节：`## Conversation and work`（`:5-11`）、`## Transparency and control`（`:13-18`）、`## Visual language`（`:20-22`）、`## Boundaries`（`:24-26`）。核心交互合同（`:7-11` 原文节选）：

```
- The composer stays available during replies. Its send arrow changes to a stop square in the
  same position inside the input pill, then returns when the run ends. Stopping preserves the current draft.
- Follow-ups appear in a visible queue and run in order. Stopping a reply pauses that queue;
  it does not cancel delegated tasks. A new submission can continue immediately when no
  follow-ups are held. An existing paused queue resumes through **Send queued messages**.
- Open chats and their drafts remain mounted while navigating. Queued messages are held in the
  open app, not a server inbox; keep the app open until they are sent. Delegated tasks are durable server work.
```

**每条都是"用户可观察的行为 + 边界"**：队列"held in the open app, not a server inbox"（`:10`）——把限制写进合同。**与代码的对应**：`chat.tsx:976-1000`（按钮 label 在 `Send message`/`Stop reply` 间切换）、`chat.tsx:787-827`（队列 UI 的 `Up next`/`Messages on hold` 文案）、`conversation-queue.ts:45`（不隐式重发）。

### 9.4 ROADMAP.md：三层措辞防"承诺当现实"

结构（全文 32 行）：`:3` 定位句（"The release is a personal-agent alpha: … The [reference inventory](docs/FEATURES.md) is broader than this release."）→ `## Shipped locally`（`:5-12`，6 条已交付）→ `## Integration acceptance next`（`:14-20`，5 条 `- [ ]`）→ `## Product extensions`（`:22-30`，7 条 `- [ ]`）→ `:32` 收尾：

```
Each item needs its own authentication, capability boundaries, failure behavior,
and end-to-end evidence before it becomes a supported feature.
No dates or third-party API access are promised.
```

**三层防线**：**第一层** `alpha` + "reference inventory is broader than this release"；**第二层** 分节命名（`Shipped locally` vs `Integration acceptance next` vs `Product extensions`）+ **未勾选复选框**；**第三层** 每项需"自身的认证、能力边界、失败行为、端到端证据"才成为 supported，且**不承诺日期、不承诺三方 API 访问**。**"Shipped locally"这一节名的精妙**：不是 "Shipped"，而是 "Shipped **locally**"——明确限定"这些能力在本地模式可用，live 模式需另配"。

### 9.5 四件套的咬合方式

`FEATURES.md`（能力清单）→ `VERIFICATION.md`（每项功能的证据 + Boundary）→ `ROADMAP.md`（优先级 + 未完成 + 不承诺什么）；`EXPERIENCE.md`（交互合同）横挂三者之外。

**咬合的具体证据**：`FEATURES.md:25` 指向 `VERIFICATION.md` 与 `../ROADMAP.md`；`VERIFICATION.md:58` 的 `## Reproduce` 指向 `DEMO.md`；`ROADMAP.md:3` 指向 `docs/FEATURES.md`；`EXPERIENCE.md:8` 的 send/stop 合同 ↔ `chat.tsx:976-1000` 的实现 ↔ `VERIFICATION.md:44-56` 的 "Release fixes and interface polish"。**三处必须同时改**：这与 Memoria 的 `AGENTS.md` 红线纪律（"红线的同一句话在三处重复"）是同一原则——OpenMuse 的版本是"文档四件套 + 代码文案五处一致"。

## 10. 演示脚本化与真实模型演示的区分

**四层结构**（`docs/DEMO.md:11` 原文）："The model responses use [CopilotKit AI Mock](https://github.com/CopilotKit/aimock). The app runs its actual CopilotKit agent and `browse_web` tool against a real Chromium worker. The script requests a page, waits for the real tool result, and extracts headlines or overview text from that result. It does not supply browser results or invent page content."

1. **模型被 mock**（AI Mock 提供脚本化回复）；2. **agent 与工具是真的**；3. **浏览器是真的**；4. **脚本等待真实工具结果再生成下一步**——不预设浏览器会返回什么。

**这一层的精妙**：mock 只替换"模型的决策"，不替换"工具的执行"。所以演示验证的是"应用与工具流"，不是"模型的推理"。

**明确区分**（`:31`）："Captures are trimmed and paced for readability, including brief slowdowns of the browser card and faster transitions into takeover. **This is a reproducible demonstration of the app and tool flow; it is not an evaluation of a live model's reasoning.**"——一句话划清界限，且**说明了剪辑**（不假装是原始录制）。

桌面段同等声明（`:49`）："the same AI Mock model and real Chromium tool flow described above, plus the actual `search_mail` and `read_mail_thread` tools against an **isolated fictional mailbox**."——演示用虚构邮箱不碰真实数据。

**凭据边界**（`:71,89`）："The runner reads only the Intelligence key from the project's private `.env` … it does not pass provider or Google credentials."；"The built-in demo token is public and scoped to this local demo; **it is not a deployment credential**."——主动说明一个看起来像凭据的东西**不是**凭据。`docs/VERIFICATION.md:22` 的对应表述："Recorded responses are scripted page excerpts, not live-model reasoning."

## 11. 与既有研究的对照

- **与 04b §4-§10 的关系**：04b 已逐个深读 10 个表面。本篇按**机制维度**重组为六个次表面 + 路由面 + 文档纪律，不复制其结构。增量：Ideas 三种 id 构造的**差异理由**、退役建议的 CAS 并发纪律、"已有人在做就打开而非复制"、`updateGoal` 的 `expected={}` 技巧、Finance 的**纯函数证明方法**（import 清单 + grep 清单）、Documents 三段的容错层次与 plan 同步、`remember_fact` 的"描述即约束"、identity 只进任务 prompt 的边界证据、routes.ts 全 19 条路由的枚举、四件套咬合的具体指向、DEMO 的四层结构与剪辑声明。
- **与 talorys 总览（[../talorys/00-overview.md](../talorys/00-overview.md) §2）**：talorys 的"三种自动化里两种完全不碰 AI"（提醒、任务摘要）与 OpenMuse 的"六个次表面里五个不经模型"是同一规律的两个样本。**"确定性优先于模型"是个人 agent 的共同选择**——个人场景的正确性要求高于创造性，而模型的不确定性是成本而非特性。
- **与 hermes 总览（[../hermes/00-overview.md](../hermes/00-overview.md)）**：hermes 的"策展记忆 + 后台 review"是**模型驱动的自我改进**；OpenMuse 的 Ideas 是**正则驱动的建议生成**。两者都在解决"agent 主动提出下一步"，但 hermes 让模型想、OpenMuse 让规则找。**OpenMuse 的路线更可控**（可解释、零成本、可测试），**hermes 的路线更开放**（能发现规则没想到的机会）。
- **与 ZCode 架构治理（[../01-zcode.md](../01-zcode.md)）**：ZCode 有"机器可检查的架构治理"（文档与代码一致性可自动验证）；OpenMuse 的四件套是**人工维护的一致性**（无自动检查）。前者成本高但不会腐化，后者成本低但依赖纪律。
- **与 04-openmuse.md §8 的关系**：旧研究写"诚实的功能清单：已实现/未实现双列声明，验证方式逐条记录"。**结论一致，本篇补充四件套的互相指向与三层措辞的具体形态**。

## 12. 对 Memoria 的可迁移结论

**适合搬（7 条）**：

1. **"Planned extensions are not claims of current support" 的写法（`FEATURES.md:25`）**：Memoria 的 `feature_list.json` 已有状态字段，但缺少**面向读者的**"这条不承诺"声明。落点：README 或 PRODUCT 文档的能力清单。
2. **Boundary 列（`VERIFICATION.md:27`）**：每行证据都写明"不能证明什么"。与 `AGENTS.md` 的 "Enforced vs instructed" 纪律同源。落点：`docs/VERIFICATION.md`。
3. **交互合同写进文档（`EXPERIENCE.md:7-11`）**：把"队列在打开的 app 内、不是服务端 inbox"这类限制写成合同。落点：Memoria 的 UI 行为文档。
4. **确定性优先（Ideas/Finance 模式）**：邮件分拣的规则命中判断不该交给模型。落点：`mail_triage` 的分类器（正则/规则优先，模型兜底）。
5. **Ideas 的"已处理集排除"（`service.ts:555-577`）**：`sentIds` + `completedSources` 两个集合。Memoria 的邮件分拣需要同类逻辑（已归档的、已处理的邮件不再提示）。落点：分拣任务的状态过滤。
6. **"已有人在做就打开而非复制"（`service.ts:651-673`）**：语义层幂等。落点：任何"用户可能重复触发同一操作"的入口。
7. **演示脚本化 + 明确区分（`DEMO.md:11,31`）**：Memoria 的验收演示若用 offline scripted-LLM（既有模式），应同样声明"这是流程演示，不是模型能力评估"。

**次选（2 条）**：内容 hash 作去重 id 的三种粒度（`service.ts:586,608,621`——按"什么变化才算新"选择）；`updateGoal` 的 `expected={}` 技巧（`:379`）。

**不适合搬（3 条）**：Ideas 的具体正则（Memoria 的邮件语料不同，正则需要重写；**但"正则优先 + 可驳回"的形态可搬**）；`agent-settings` 单例存 identity（若不需要"agent 人格"可省）；Rich Threads 的 CopilotKit 接线（SaaS 依赖）。

## 13. 证据索引

| 结论 | 文件:行 |
|---|---|
| Ideas 三条规则（正则 + slice(0,5)）/ 三种 id 构造差异 | `apps/server/src/engine/service.ts:578-633` |
| 已处理集排除 + 退役旧建议的 CAS 纪律 / 15 分钟节流 + 按小时聚合 | `apps/server/src/engine/service.ts:110-124,555-577` |
| 接受建议：先找已处理任务 / 两阶段 CAS + 自动建 goal | `apps/server/src/engine/service.ts:651-717` |
| 任务 → 里程碑（幂等 + CAS 重试） | `apps/server/src/engine/service.ts:911-927` |
| 目标暂停级联暂停任务 / `expected={}` 技巧 / Goal 创建 | `apps/server/src/engine/service.ts:360-386` |
| Finance 纯函数（唯一 import + 无 I/O）/ BOM 剥离 / CSV 状态机 / 引号校验 | `apps/server/src/engine/finance.ts:1-41` |
| Finance 表头/行数/列数/日期/金额校验 / 符号约定 + amountConvention | `apps/server/src/engine/finance.ts:2,42-100` |
| Finance 分支不调模型 | `apps/server/src/engine/service.ts:865-889` |
| Document 三段（找源文件/typed input/填充+提案）与 plan 同步 | `apps/server/src/engine/service.ts:974-1059` |
| 记忆 REST 三条路径（创建/CAS 更新/take 删除） | `apps/server/src/engine/routes.ts:99-125` |
| remember_fact 工具（描述即约束 + hash id + source） | `apps/server/src/engine/conversation.ts:365-379` |
| identity 与 memories 进任务 prompt（data only + JSON）/ identity 不进对话 prompt | `apps/server/src/engine/model.ts:317-331`；`apps/server/src/engine/conversation.ts:388-403` |
| 存引用不存值 / 每对话私有 agent / mock 不替代 live 测试 | `docs/RICH-THREADS.md:22,26,42` |
| 工具结果只回 task id / 文件与浏览器 URL 现签发 | `apps/server/src/engine/conversation.ts:123`；`apps/server/src/files.ts:104-106`；`apps/server/src/browser.ts:114-120` |
| routes.ts 全 19 条路由 / 模式限定端点显式 404 | `apps/server/src/engine/routes.ts:31-166` |
| FEATURES 三列表头 + 代表行 + "Planned extensions…" | `docs/FEATURES.md:7-25` |
| VERIFICATION Boundary 列表头 + 代表行 + 未实现清单 + "not live-model reasoning" | `docs/VERIFICATION.md:22,27-39,78-82` |
| EXPERIENCE 交互合同（含"非服务端 inbox"）/ 边界节 | `docs/EXPERIENCE.md:7-11,24-26` |
| ROADMAP 三层措辞 + 不承诺日期 | `ROADMAP.md:3,5-30,32` |
| DEMO 四层结构 / 明确区分 + 剪辑声明 / 虚构邮箱 / 凭据边界 | `docs/DEMO.md:11,31,49,71,89` |
| 四件套互相指向 | `docs/FEATURES.md:25`；`docs/VERIFICATION.md:58`；`ROADMAP.md:3` |
