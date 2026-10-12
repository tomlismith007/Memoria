# OpenMuse 核心设计 · 02 持久任务引擎

> 研究对象：`CopilotKit/OpenMuse` — 个人 agent，MIT，TypeScript；HEAD `1ac68f3`（main，2026-10-11）
> 路径相对仓库根，`文件:行` 均为实读行号；结论只来自源码，未定位到的机制明确标注
> 本篇聚焦：任务域模型（`packages/domain/src/agent.ts`）、状态机与合法迁移、TaskWorker 内部实现（`apps/server/src/engine/worker.ts` 全文 257 行）、任务编排与监控（`engine/service.ts`）、任务内模型执行（`engine/model.ts`）
> 与 [../04b-openmuse-alpha-surfaces.md](../04b-openmuse-alpha-surfaces.md) §3 重叠处只做引用 + 增量；04b 未覆盖的 TaskWorker 内部（`inFlight`/`LostLeaseError`/`guard`/`checkpoint`/心跳 CAS 失败）在本篇首次完整覆盖

---

## 1. 定位与全景

任务引擎是产品核心（"work that keeps going"）。形状是**进程内 tick 循环 + 数据库租约**：没有消息队列、没有独立 scheduler、没有分布式协调。`TaskWorker` 每 1 秒扫描 `tasks`，用一条 CAS 抢占，用心跳维持，用 `checkpoint` 推进，用 `guard` 自证。

```
对话工具 delegate_task / REST POST /api/agent/tasks / 监控唤醒 / Ideas 接受
  ▼  AgentService.createTask（幂等 + 上限 100 + 计划模板）→ status="queued"
TaskWorker.tick()  每 1000ms（worker.ts:53）
  ├─ scan("tasks") 全表 → 四种到期判据 + inFlight 排除
  ├─ waiting_approval 特殊分支：审批过期则标 expired；仍在审则跳过
  ├─ 并发上限：inFlight.size + eligible.length >= 3 即停（worker.ts:89）
  └─ run()：CAS 抢租约 → heartbeat(leaseMs/3) → execute → checkpoint 终态
       └─ settled 回调 → publishOutcome（通知 + 里程碑 + 监控暂停）
  ▼  AgentService.execute 按 kind 分派：document / monitor / finance / 其他→executeModelTask
```

## 2. 数据模型

### 2.1 AgentTask（`agent.ts:26-49`）

字段分四组：**身份与内容**（`id`/`title`/`prompt`/`kind`/`goalId?`/`milestoneId?`）；**进度**（`plan: TaskStep[]`、`evidence: Evidence[]`、`artifactIds: string[]`）；**输入与状态**（`input`、`state: Record<string, unknown>`）；**调度与租约**（`status`、`createdAt`/`updatedAt`/`nextRunAt?`、`leaseId?`/`leaseUntil?`、`attempts`、`actionId?`、`result?`/`error?`/`question?`）。

- **`state`** 是**恢复的载体**——每步把"下次要用什么"写进去：`source`/`filledId`（document）、`sessionId`/`lastHash`/`matched`/`alertSequence`/`failures`（monitor）、`operations`（模型工具幂等缓存）、`browserId`。进程重启后从 `state` 重建，不依赖内存。
- **`leaseId` + `leaseUntil`**：租约二字段（§4）。
- **`plan: TaskStep[]`**：五态步骤（`pending`/`running`/`succeeded`/`failed`/`waiting`），`createTask` 按 kind 生成模板，模型可经 `set_plan` 重写（`model.ts:96-106`）。
- **`evidence: Evidence[]`**：`{id, kind: "mail"|"file"|"web"|"user", title, excerpt, url?}`。

### 2.2 九态与合法迁移

`TaskStatus`（`agent.ts:3-12`）：`queued / running / waiting_approval / waiting_input / scheduled / paused / succeeded / failed / cancelled`。终态集合 `terminal = {"succeeded","failed","cancelled"}`（`service.ts:51`）。

| 起始 → 目标 | 触发 | 证据 |
|---|---|---|
| — → `queued` / `paused` | `createTask`（held 或 goal 已暂停时 paused） | `service.ts:228` |
| `queued` → `running` | worker CAS 抢租约 | `worker.ts:133-139` |
| `scheduled` → `running` | `Date.parse(nextRunAt) <= now` | `worker.ts:83` |
| `running`（租约过期）→ `running` | 重认领 | `worker.ts:84` |
| `running` → `waiting_approval` | 模型 prepare 工具 / 恢复时 action 未决 | `model.ts:258,282`；`service.ts:819` |
| `running` → `waiting_input` | `ask_user` / document 缺字段 / 无模型 / 模型未确认完成 | `model.ts:291,24-27,390-395`；`service.ts:1011-1019` |
| `running` → `scheduled` | monitor 正常观察完成 | `service.ts:1157-1158` |
| `running` → `succeeded` | `finish_task` / document 审批成功 / finance 完成 | `model.ts:312`；`service.ts:810,888` |
| `running` → `failed` | 非租约类异常 | `worker.ts:226-238` |
| `running` → `queued` | `LostLeaseError` 或 signal aborted | `worker.ts:213-220` |
| `waiting_approval` → `running` | 审批单已不在 `awaiting_review`/`executing` | `worker.ts:110` |
| `waiting_input` → `queued` | 用户 `answer()` | `service.ts:344-357` |
| `scheduled` → `paused` | monitor 连续失败 ≥5 | `service.ts:848` |
| `paused` → `queued` | `control(resume)` / `activateMonitor` | `service.ts:270-277,440-459` |
| 任意非终态 → `paused` / `cancelled` | `control()` | `service.ts:270-277` |
| `failed` → `queued`/`waiting_approval` | `control(retry)` | `service.ts:251-277` |

**两条易忽略的规则**：

1. **`retry` 只对 `failed` 开放**（`service.ts:251-252` 原文 "Only failed tasks can be retried"）；若任务带 `actionId` 而审批单不是 `succeeded`，直接 409："Check the reviewed action before retrying; its outcome may be uncertain. Start a new task when reconciled."（`service.ts:278-285`）——**重试不绕过未决审批**。
2. **三种控制动作严格度不同**：`cancel` 对已成功任务拒绝（"This task is already complete"，`:249-250`）；`pause` 对终态或已暂停**幂等返回**（`:255`）；`resume` 只对 `paused` 有效。

### 2.3 七类审计事件（`agent.ts:54`）

`plan / step / observation / approval / result / error / status`。写入统一走 `event()`，而 `event()` **先 guard 再写**（`worker.ts:162-172`）——丢租约的任务不会留下伪造审计行。

分工：`run-events` 是任务内细粒度轨迹（UI 详情页读它，`service.ts:184-186`）；`notifications` 是面向人的幂等收件箱（§7）。

## 3. 任务创建：幂等、上限与计划模板

### 3.1 幂等（`service.ts:192-196`）

```ts
const id = idempotencyKey ? hash(`task:${idempotencyKey}`) : randomUUID();
const existing = await this.db.get<AgentTask>(owner, "tasks", id);
if (existing) return existing;
```

`hash` = sha256 hex（`service.ts:47`）。key 由上层构造：对话侧 `requestKey:delegate_task:<args hash>`，Ideas 侧 `idea:<ideaId>`（`:708`），监控侧 `monitor:<monitorId>`（`:415`）。**key 带前缀**防不同 kind 的键空间碰撞。

### 3.2 校验、上限与计划模板

- `milestoneId` 必须伴随 `goalId`（422）；`goalId` 必须存在（404）；`milestoneId` 必须在该 goal 里（404）（`service.ts:197-201`）；
- **非终态任务上限 100** → 409 "Finish or cancel some tasks before adding more"（`:202-206`）。上限的意义：`tick` 会 `scan("tasks")` 全表、`snapshot` 会全量返回；100 是"个人 agent"规模的显式收窄，避免"没人清理就膨胀"。
- **四套计划模板**（`:207-220`）：`document`（Find the source document / Fill a new copy / Prepare a reply / Wait for your decision / Record the outcome）、`monitor`（Check the source / Compare with the last observation / Report a meaningful change）、`finance`（Validate transactions / Calculate the summary / Save your tracker）、`agent`|`plan`（Understand the outcome / Plan the work / Use connected tools / Return a result）。模板创建时即写入 `plan`，之后整体重写——**进度从第一天就可展示**，不必等模型先 `set_plan`。

### 3.3 `state.connectionId` 快照（`service.ts:232-235`）

创建时记录当时的 Google 连接 id；执行外部动作前比对（`:762-767`）：不等则 409 "Google connection changed during this task. Start a new task using the current account."——"任务创建于账号 A、执行于账号 B"的串号风险在**任务粒度**被拦住。

## 4. TaskWorker 内部实现（04b 未覆盖）

### 4.1 `inFlight`：进程内的"已接手"集合（`worker.ts:28-29`）

```ts
// Tasks this worker has started and not yet settled, including ones still being claimed.
private inFlight = new Set<string>();
```

三处用法：tick 过滤器排除（`:81`）；并发上限 `inFlight.size + eligible.length >= 3`（`:89`，**含"正在抢但还没抢到"的**）；`stop()` 等待清空（`:61`）。`inFlight.add` 在 `run()` **被调用前**执行（`:116-117`），`.finally()` 删除——覆盖"CAS 还没返回"的窗口。

**它是进程内优化，不是正确性来源**：即使两个进程同时认领，只有一个的 `expected` 能匹配（`:133-140`，`if (!task) return;`）。

### 4.2 到期判据（`worker.ts:79-86`）

```ts
const due = records.filter(({ value: t }) =>
  !this.inFlight.has(t.id) &&
  (t.status === "queued" ||
    (t.status === "scheduled" && Date.parse(t.nextRunAt ?? "") <= this.now()) ||
    (t.status === "running" && Date.parse(t.leaseUntil ?? "") <= this.now()) ||
    t.status === "waiting_approval"));
```

- `running` 只有**租约过期**才可跑——这就是崩溃自愈入口，不需要"死进程检测"；
- `waiting_approval` **每 tick 都进候选**，不是为了跑，而是检查审批单状态；
- `Date.parse(undefined ?? "")` = `NaN`，`NaN <= now` 为 `false`——缺 `leaseUntil` 的 running 任务不会因字段缺失被误认领（依赖 JS 语义的隐式保护）。

### 4.3 `waiting_approval` 特殊分支（`worker.ts:90-111`）

读 `actionId` 对应的审批单：**已过期**（`action.status === "awaiting_review" && Date.parse(expiresAt) <= now`）→ CAS 成 `expired`，然后**继续推入 eligible**；**仍在 `awaiting_review`/`executing`** → `continue` 跳过；**不存在或其他状态**（succeeded/failed/denied/outcome_unknown）→ 推入 eligible，让任务自己读 action 决定下一步。

三种情形：

1. **审批单已过期** → CAS 成 `expired`，**继续推入 eligible**——任务被唤醒后读到 action 状态不对，抛错进 failed 路径（`service.ts:815-818`）。任务由此得到明确结局，不会永久悬停。
2. **仍在 `awaiting_review`/`executing`** → `continue` 跳过。
3. **不存在或其他状态**（succeeded/failed/denied/outcome_unknown）→ 推入 eligible，让任务自己读 action 决定下一步。

**这是"审批单即回执"的调度侧体现**：任务不需要被通知，它每 tick 都来看一眼审批单。

### 4.4 认领 CAS（`worker.ts:126-140`）

```ts
const leaseId = randomUUID(), leaseMs = this.options.leaseMs ?? 60000;
const expected = { status: previous.status, leaseId: previous.leaseId ?? null };
if (previous.status === "running") expected.leaseUntil = previous.leaseUntil;
const task = await this.db.compareAndSwap(owner, "tasks", previous.id, expected, {
  status: "running", leaseId, leaseUntil: now + leaseMs, attempts: previous.attempts + 1 });
if (!task) return;
```

`expected` 三字段各有用途：`status` 防认领已 pause/cancel 的任务（tick 读到旧快照）；`leaseId` 防认领刚被别的 worker 抢走的；**`leaseUntil`（仅当原状态是 running）防两个 worker 同时认领同一过期任务**——两者读到相同的 `leaseUntil`，只有一个能 CAS 成功。`attempts + 1` 在认领时递增（含正在跑的这次）。

### 4.5 `guard()` / `checkpoint()`（`worker.ts:144-161`）

```ts
const guard = async () => {
  const latest = await this.db.get<AgentTask>(owner, "tasks", taskId);
  if (controller.signal.aborted || latest?.leaseId !== leaseId || latest.status !== "running")
    throw new LostLeaseError();
};
const checkpoint = async (patch) => {
  const next = await this.db.compareAndSwap(owner, "tasks", taskId,
    { leaseId, status: "running" }, { ...patch, updatedAt: … });   // 只有持租约者能写
  if (!next) throw new LostLeaseError();
  task = next; return next;
};
```

`guard()` 三条件任一成立即抛：本地 abort；库里的 `leaseId` 已不是我的；`status` 已不是 `running`。**调用位置就是安全边界**——`checkpoint`/`event`/`prepare` 前、每次 browser/computer 操作前（`service.ts:761,981,1023,1080,1122,1152`；`model.ts:66,82,94,169`）。**每个外部副作用前都要重新自证**，这是租约从"软锁"变成"硬约束"的关键。

`checkpoint` 的 CAS 条件 `{leaseId, status:"running"}` 保证"只有持租约者能写"，`task = next` 让调用方拿到最新版本。

### 4.6 心跳与 CAS 失败处理（`worker.ts:174-190`）

`setInterval` 每 `Math.max(10, Math.floor(leaseMs / 3))`（60s 租约 → 20s 心跳，下界 10ms 防测试传入过小租期）用 CAS 续 `leaseUntil`，`.then((value) => { if (!value) controller.abort(); }).catch(() => controller.abort())`。**心跳 CAS 失败 = 丢租约 → 立刻 abort**（长耗时工具会被 signal 打断）；**数据库异常也 abort**——库不可用时不能假装还持有租约，这是 fail-closed。

### 4.7 终态与错误分支（`worker.ts:191-256`）

`try` 分支：写 `runs`（`id = leaseId`，执行台账，与 `run-events` 任务内轨迹分工不同）→ `execute()` → `checkpoint({...result, leaseId: null, leaseUntil: null})` → 更新 `runs` 终态。

`catch` 分支两条路：**丢租约/abort → 回 `queued`**（不是 failed——任务没失败，只是这次没跑成，`attempts` 已 +1）；**真错误 → `failed` + 写 error 事件**（且 `event(...).catch()` 吞掉写事件本身的失败，审计写入失败不能掩盖原始错误）。两条路都更新 `runs` 状态（`interrupted` 或 `failed`）。`finally` 清心跳并从 `active` 移除。

### 4.9 恢复 = 重放（本篇重点结论）

| 崩溃时刻 | 库里状态 | 恢复路径 |
|---|---|---|
| 认领后、execute 前 | `running` + 有效租约 | 租约到期（≤60s）→ 重认领 → `execute` 从头跑 |
| execute 中 | `running` + 心跳停止 | 租约到期 → 重认领 → 从 `task.state` 重建 |
| checkpoint 后 | `running` + 新 state | 同上，但 state 已前进——**已完成的步骤不重做** |
| 终态写入后、publishOutcome 前 | `succeeded` 但无通知 | `maintain()` 补偿扫描（§8） |

**准确含义**：不是"续跑内存里的执行栈"，而是"从库里读回 `state`，重新执行 `execute()` 的分派逻辑"。前提是每个 kind 的 `execute` 分支都是**幂等的状态推进**：

- document：`if (!source)` 找邮件；`if (filledId)` 跳过填充；有 `actionId` 走审批路径（`service.ts:974-1060`）；
- monitor：每次重新观察，用 `state.lastHash` 判断变化（`service.ts:1061-1193`）；
- 模型任务：`operations` 表缓存每个工具调用结果（`model.ts:77-87`），重放时命中缓存直接返回。

**"重放安全"的前提是每个 kind 的 execute 都写成状态机**——这是本引擎最重要的设计约束，也是最难照抄的部分。

## 5. 任务执行分派（`service.ts:794-891`）

### 5.1 审批路径优先（`service.ts:804-820`）

`if (task.actionId)` 时先读审批单，四分支：**已成功** → 结果写进 `state.approvalResult` 并清空 `actionId`（document 类直接 `finish`）；**仍在等审**（`awaiting_review`/`executing`）→ 返回 `{status: "waiting_approval"}`；**其他状态** → 抛 `Reviewed action ${status}: ${error}` 进 failed；**审批单丢失** → 抛 "The linked review could not be found"。

`approvalResult` 的用途（`model.ts:331` prompt 原文）："When an approved result is in saved state, continue from it and never duplicate it."——审批通过后重启的任务不会重复发送邮件。

### 5.2 模型执行（`model.ts`）

- **无模型时降级**（`:22-27`）：返回 `waiting_input` + "A model is required for this open-ended task. Configure MODEL and its provider key on the server, then reply 'continue'. **The document, monitor and finance workflows can run without a model.**"——能力面显式收窄并指出哪些还能用。
- **工具串行化**（`:37-47`）：provider 可能请求并行工具，但 checkpoint 必须有序，所以 `toolQueue` 串行化全部工具调用。
- **`cached` 幂等**（`:77-87`）：`sha256(name + JSON.stringify(args))` 作 `operations` 的键，命中即返回。
- **`outcome` 短路**（`:60-65`）：一旦某工具设置 `outcome`，后续工具调用返回 `{paused: true, …}` 并提示 "The task is waiting or finished; do not perform more actions."
- **超时**：模型 run 硬上限 **5 分钟**（`:352-356`）。
- **`shouldContinue`**（`:330`）：`agentLoopStrategy: maxIterations(16) && shouldContinue()`——`outcome` 一旦设置循环立即结束。
- **未确认完成**（`:389-396`）：`outcome` 为空时返回 `waiting_input` + "The agent reached the end of this run without confirming completion. Give it a follow-up instruction to continue."——**绝不假装成功**。

`finish`（`service.ts:892-900`）把全部 plan 步骤置 succeeded——模板步骤不会残留 `pending`。

## 6. 审批闭环（`service.ts:754-793`）

`prepare()` 的关键步骤：`guard()` 自证 → 校验 `connection.id === task.state.connectionId`（变了则 409 "Google connection changed during this task."）→ `actions.propose(owner, input, \`${task.id}:${key}\`, task.id)` → 若提案 `succeeded` 直接返回（**审批通过后重启的任务不会重新提案**）→ 若非 `awaiting_review`/`executing` 则抛错带状态与原因 → `checkpoint({actionId})` → 只有 `awaiting_review` 才写 approval 事件。

**最精妙的一处**（`:777-785`）：checkpoint 失败（通常是丢租约）时，若任务已被用户暂停/取消，**自动 deny 掉刚创建的审批单**：

```ts
const current = await this.db.get<AgentTask>(owner, "tasks", task.id);
if (proposal.status === "awaiting_review" &&
    (current?.status === "paused" || current?.status === "cancelled"))
  await this.actions.decide(owner, proposal.id, proposal.hash, "deny");
```

否则会出现"任务已取消但审批卡还挂在 UI 上等人批准"的孤儿审批。这是"提案创建"与"任务生命周期"之间的补偿逻辑。幂等键 `${task.id}:${key}` 保证同一任务同一内容只产生一张审批单（见 [03 篇](03-approval-isolation.md) §3）。

## 7. 监控任务：退避、去重与状态竞争

### 7.1 2^n 退避与报警 key（`service.ts:822-863`）

```ts
const failures = Number(task.state.failures ?? 0) + 1;
// Each streak of failures (after a success or a resume) gets its own alerts.
const failureStreak = Number(task.state.failureStreak ?? 0) + (failures === 1 ? 1 : 0);
const nextCheckAt = new Date(Date.now() + Math.min(60, 2 ** failures) * 60000).toISOString();
```

退避 = `min(60, 2^failures)` 分钟：1→2min，2→4min，3→8min，4→16min，5→32min，6→64→**capped 60min**。`failures >= 5` 时任务转 `paused`（`:848`）。

`failureStreak` 只在"失败链的第一次失败"递增——每次成功或恢复后的新一轮失败会得到**新的报警 key**：

```ts
notice: { title: "Watch needs attention", body: detail,
  key: `watch-error:${task.id}:${failureStreak}:${failures >= 5 ? "paused" : "retry"}` }
```

注释原文："Each streak of failures (after a success or a resume) gets its own alerts."——持续失败不刷屏，但**恢复后再次失败会重新报警**。

**报警 key 去重机制**（`:719-729`）：通知 `id = key ? hash(key) : randomUUID()` + `insertIfAbsent`，天然去重。全仓 key 模式：`task-done:<id>`（`:909`）、`task-error:<id>:<attempts>`（`:935`）、`input:<id>:<hash(question)>`（`:943`）、`review:<actionId>`（`:951`）、`monitor:<id>:<alertSequence>:<hash>`（`:1178`）、`watch-error:<id>:<streak>:<retry|paused>`（`:859`）、`idea-recovery:<id>`（`:107`）、`source-error:<epochHour>`（`:121`）。

### 7.2 `alertSequence`：为什么需要单调序号（`service.ts:1116-1120`）

```ts
// A notification-worthy observation is a new event, even when the page text is
// identical to an earlier one (a change back to a seen state, or a condition that
// cleared and reappeared). Commit its sequence with the outcome so publication
// retries still deduplicate on the same saved notice key.
const alertSequence = Number(task.state.alertSequence ?? 0) + (shouldNotify ? 1 : 0);
```

key = `monitor:<id>:<alertSequence>:<currentHash>`。若只用 hash，"页面变回曾经见过的状态"会命中旧 key 而不报警。序号把"第几次报警"编码进 key，同时**与 outcome 一起提交**——发布重试时用同一 key，不会重复通知。

### 7.3 `shouldNotify` 三条件（`service.ts:1092-1112`）

```ts
const matched = monitor.condition === "change" ? Boolean(previousHash && previousHash !== currentHash)
  : monitor.condition === "contains" ? text.toLowerCase().includes(monitor.value.toLowerCase())
  : this.matchesPrice(text, Number(monitor.value));
const previouslyMatched = Boolean(task.state.matched);
const quiet = Boolean(baseline?.timelessHash && baseline.timelessHash === timelessHash);
const shouldNotify = matched && !quiet && (monitor.condition === "change" || !previouslyMatched);
```

`change`：hash 变了就算匹配；`contains`/`price_below`：只在**从"未匹配"变为"匹配"**时通知（持续满足的条件不重复报警）；`quiet`：整页只有相对时间变化时静默（见 [08 篇](08-surfaces-and-doc-discipline.md) §4）。

`matchesPrice` 只认显式美元符号（`:1195-1198`）：`/(?:\$|USD)\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)/g`。`watch_page` 描述写明："Price checks detect explicit USD or dollar prices; no booking is performed."

**baseline 保护**（`:1099-1113`）：`monitor-pages` 保存上次页面行与 `timelessHash`，但**只有它的 hash 与已提交 baseline 一致时才使用**——注释："Saved lines can run ahead of a lost task outcome; use them only for the committed baseline."（页面写入发生在 checkpoint 之前，若那次 run 丢了租约，页面数据会比任务状态新）。

### 7.4 pause/cancel 与租约的竞争（`service.ts:480-553`）

核心顺序：

```ts
// Mark the paused task before activating the monitor so no worker can claim it in between.
const marked = await this.db.compareAndSwap(owner, "tasks", task.id,
  { status: "paused", leaseId: task.leaseId ?? null },
  { state: { ...task.state, resumingMonitor: true } });
```

**先标记任务（`resumingMonitor: true`），再激活监控**。这保证 worker 在这一瞬间看到的是"paused + resumingMonitor"的任务，而 `activateMonitor` 只在看到该标记时才把它转成 `queued`（`:434-448`）。若顺序反过来，worker 可能在两步之间认领任务并开始观察——而用户刚点的"恢复"还没生效。

**失败回滚**（`:502-521`）：若激活后 `activateMonitor` 没能把任务转成 queued（另一请求抢先），撤销标记并回滚 monitor 状态；注释："Another request or maintenance may have finished this resume first."

**`updatedAt` 围栏**（`:539-540`）：

```ts
// updatedAt fences out a whole run finishing in between, which would move the baseline.
{ status: task.status, leaseId: task.leaseId ?? null, updatedAt: task.updatedAt },
```

`controlMonitor(check)` 强制"立即检查"时，CAS 条件带上 `updatedAt`——若中间有一整轮 run 完成了（会更新 `updatedAt`），放弃本次强制检查。理由：那一轮已把 baseline 推进，再"强制检查"没有意义且可能产生重复报警。

## 8. `maintain()` 与 `publishOutcome`

### 8.1 每 60 秒的对账扫描（`service.ts:85-128`）

四项：**重放 `publishOutcome`**（进程在"终态已提交"与"通知已发布"之间崩溃时补偿；通知幂等，重复调用无副作用）；**重激活监控**（只对 `paused` + `resumingMonitor`/`initializingMonitor` 生效，幂等）；**修复"已接受但任务不存在"的 Ideas**（失败则通知 "Open the idea again after making room for another task."，因为 100 上限）；**Ideas 15 分钟刷新**（失败按小时聚合通知）。

**与 worker.tick 的分工**：tick 处理"该跑的跑起来"，maintain 处理"该发的发出去、该修的修回来"。两者都不依赖内存状态，可随时重启。

### 8.2 终态发布（`service.ts:901-968`）

- **四类通知**：`succeeded` → `task-done:<id>`；`failed` → `task-error:<id>:<attempts>`；`waiting_input` → `input:<id>:<hash(question)>`；`waiting_approval` → `review:<actionId>`。
- **目标联动**：成功的任务若属于某 goal 且自身不是里程碑任务，被追加为该 goal 的一个**已完成里程碑**（`id = task.id`）。最多 8 次 CAS 重试；幂等判据在前。**丢更新窗口只在"两个任务同时完成且属于同一 goal"时出现**（见 [07 篇](07-data-platform.md) §3.1）。
- **监控暂停时序**（`:959-967`）：注释 "A watch pauses after repeated failures only once that task outcome has committed."——CAS 条件 `{status: "active", error: task.error} → {status: "paused"}`，由**任务终态提交后**的 publish 阶段设置，条件带 `error` 匹配防止把用户手动暂停的监控误改。
- **`state.notice` 通用通知通道**（`:954-958`）：`scheduled` 状态或"paused 且带 error"的任务，若 `state.notice` 符合 `{title, body, key}`，就用它发通知。这让**任意任务实现**都能声明"我需要发一条可去重的通知"。

## 9. PGlite 单进程 vs Postgres 多 worker 的边界

- **PGlite**（无 `databaseUrl` 时）：进程内嵌，`TaskWorker` 与 HTTP 请求同进程，`inFlight` + CAS 双保险；
- **Postgres**（有 `databaseUrl`）：可多进程。`inFlight` 退化为纯优化，正确性完全落在 CAS 上——`expected.leaseUntil` 的比较（`worker.ts:132`）是为多 worker 准备的关键字段；
- **`createPool` 挂 error 监听**（`db.ts:153-157`）注释原文："Idle clients can be disconnected by a database restart; without a listener pg's `error` event crashes the process."

**未定位到**多实例部署配置或文档，也没有 advisory lock。**结论**：多 worker 是"CAS 允许"而非"已验证"的形态。

## 10. 与既有研究的对照

- **与 04b §3 的关系**：04b 已给出状态机全貌、租约字段、checkpoint、pause/resume/cancel 语义差异、monitor 复合状态机、三条并发纪律。增量：`inFlight` 三处用法与"为什么它只是优化"、`LostLeaseError` 的两个抛出点、心跳 CAS 失败即 abort、`resume` 的"先标记再激活"顺序证明、`updatedAt` 围栏理由、`alertSequence` 完整推导、`maintain()` 四项对账、`publishOutcome` 的目标联动与监控暂停时序。
- **与 talorys 调度（[../talorys/05-scheduling.md](../talorys/05-scheduling.md)）**：两者都用 CAS 保证"至多一次"，但对象不同——talorys 是"单 shot 日程 + 触发后重排 + 三闸防重复"，OpenMuse 是"持续租约 + 心跳续期"。talorys 的 CAS 建立在 Cloudflare DO 单实例同步 SQLite 上（不需要租约）；OpenMuse 的 CAS 必须显式携带租约字段，因为它假设可能有第二个 worker。**这是"单实例语义"与"可多实例语义"的成本差**。
- **与 hermes 调度（[../hermes/07-scheduling.md](../hermes/07-scheduling.md)）**：hermes 用"分发前推进 next_run_at + CAS 认领 + 投递台账"三件套；OpenMuse 用"租约 + 心跳 + `runs` 台账"。两者独立收敛到"台账 + CAS"，但 OpenMuse 多一层**长任务**支持——hermes 的 cron 是短执行，租约不是必需；OpenMuse 的任务可能跑几分钟，所以必须有心跳。
- **与 04-openmuse.md §3.2 的关系**：旧研究写"失败任务回 `queued` 清租约、`attempts++`，配 retry/backoff"。**结论已修正**：只有 `LostLeaseError`/abort 回 `queued`；真错误直接进 `failed`，没有自动 backoff（唯一退避在 monitor 分支，且是"检查失败"而非"任务失败"）。
- **与 ZCode 状态机（[../01-zcode.md](../01-zcode.md)）**：ZCode 是"10 相显式状态机，非法迁移抛错"；OpenMuse 的**非法迁移由 CAS 的 `expected` 隐式拒绝**而非显式校验表。效果相同（状态不可跳跃），但 ZCode 错误更可诊断，OpenMuse 代码更少。

## 11. 对 Memoria 的可迁移结论

**适合搬（7 条）**：

1. **租约 + 心跳 + 过期重认领（`worker.ts:126-190`）**：`leaseId`/`leaseUntil` + 心跳间隔=租期/3 + **心跳 CAS 失败即 abort**。feat-068 最直接的升级：崩溃自愈不依赖内存，长任务不因重启永久卡住。落点：`app/` 任务 worker 的认领与心跳。
2. **`guard()` 在每个副作用前自证（`worker.ts:144-148`）**：不要只在循环开头检查一次。落点：所有会写库或调外部服务的任务步骤。
3. **丢租约回 `queued`，真错误进 `failed`（`worker.ts:212-239`）**：两种失败语义分离，前者可自动重试，后者必须人工介入。落点：feat-068 的错误分支。
4. **`inFlight` + CAS 双保险（`worker.ts:28-29,116-117`）**：进程内集合挡重复投递（性能），CAS 挡一切（正确性）。
5. **幂等键 → sha256 派生 id + 先查再插（`service.ts:192-196`）**：邮件分拣重复投递防护；同一模式在 tasks/monitors/actions/files 四处复用。落点：`mail_triage` 入口。
6. **通知 id 由 key 派生 + `insertIfAbsent` 去重（`service.ts:719-729`）**：报警不刷屏的最小实现，无需额外"已通知"表。落点：通知收件箱（feat-068 已有雏形）。
7. **`maintain()` 式对账扫描（`service.ts:85-128`）**：每 60 秒重放"已提交但未发布"的副作用。因为所有副作用都幂等，重放零成本。落点：任何"落库 + 通知"两步操作。

**次选（3 条）**：`alertSequence` 单调序号（`:1116-1120`，只在"状态变回曾见值也要报警"时需要）；`updatedAt` 围栏（`:539-540`，防"强制检查"与"整轮 run 完成"竞争）；`resume` 的"先标记再激活"顺序（`:484-486`，跨两表原子性补偿）。

**不适合搬（3 条）**：

- **`scan(kind)` 全表扫描**（`db.ts:109-115`）：个人规模（上限 100）可接受，Memoria 若任务量更大需索引或分页。**这是明确用产品上限换来的简化**。
- **`state: Record<string, unknown>` 无 schema**：恢复语义全靠每个 kind 的 execute 自己约定；照抄需在每个 kind 旁写明 state 契约。
- **PGlite/Postgres 双后端**：Memoria 用 SQLite，只搬 CAS 原语（见 [07 篇](07-data-platform.md)）。

## 12. 证据索引

| 结论 | 文件:行 |
|---|---|
| 九态定义 / Evidence / TaskStep / RunEvent 七类 / AgentTask 全字段 / Goal-Monitor-Idea 形状 | `packages/domain/src/agent.ts:3-134` |
| TaskWorker 类与 inFlight / tick 四种到期判据 / 并发上限 3 / waiting_approval 分支 | `apps/server/src/engine/worker.ts:23-113` |
| 认领 CAS（expected 三字段）/ guard 三条件 / checkpoint CAS / event 先 guard / 心跳 leaseMs/3 + 失败即 abort | `apps/server/src/engine/worker.ts:124-190` |
| runs 执行台账 / 丢租约回 queued / 真错误进 failed / settled 回调 | `apps/server/src/engine/worker.ts:192-255` |
| createTask 幂等 + 上限 100 + 计划模板 / control 四动作严格度 / answer 唤醒 | `apps/server/src/engine/service.ts:192-359` |
| updateGoal 暂停级联 / createMonitor URL 校验 / activateMonitor 两分支 | `apps/server/src/engine/service.ts:374-460` |
| controlMonitor resume 的"先标记再激活"顺序 + 回滚 + updatedAt 围栏 | `apps/server/src/engine/service.ts:480-553` |
| refreshIdeas 三条正则与去重 / notify 的 key 派生 id | `apps/server/src/engine/service.ts:554-637,719-729` |
| prepare 的连接绑定 + 补偿 deny + approval 事件 / execute 分派与审批路径四分支 | `apps/server/src/engine/service.ts:754-820` |
| monitor 失败退避 2^n capped 60min / finance 分支与 finish | `apps/server/src/engine/service.ts:822-900` |
| publishOutcome 四类通知 + 目标联动 + 监控暂停时序 | `apps/server/src/engine/service.ts:901-968` |
| document 状态机三段 / observe 的 matched-quiet-shouldNotify-alertSequence / matchesPrice | `apps/server/src/engine/service.ts:969-1198` |
| maintain 四项对账 | `apps/server/src/engine/service.ts:85-128` |
| 模型任务：无模型降级 / operations 幂等 / outcome 短路 / 5 分钟超时 / 未确认完成 | `apps/server/src/engine/model.ts:22-27,37-87,244-294,326-332,352-356,389-396` |
| CAS 原语 SQL / setMilestoneDone / claim / scan / 双后端选择与 pool error 监听 | `apps/server/src/db.ts:69-115,153-180` |
| 任务域 REST 路由（含 control/input） / worker 心跳可见性 | `apps/server/src/engine/routes.ts:32-59`；`apps/server/src/engine/service.ts:149-165` |
