# OpenMuse 核心设计 · 03 审批与对话通道隔离

> 研究对象：`CopilotKit/OpenMuse` — 个人 agent，MIT，TypeScript；HEAD `1ac68f3`（main，2026-10-11）
> 路径相对仓库根，`文件:行` 均为实读行号；结论只来自源码
> 本篇聚焦：审批域模型（`packages/domain/src/index.ts`）、审批服务（`apps/server/src/actions.ts` 全文 218 行）、执行锁 SQL（`db.ts::claim`/`recoverInterruptedActions`）、任务侧接入（`engine/service.ts::prepare`、`engine/model.ts`）、目标解析（`workspace.ts::prepare`）、Google 侧 If-Match
> 与 [../04b-openmuse-alpha-surfaces.md](../04b-openmuse-alpha-surfaces.md) §11 重叠处只做引用 + 增量；04b 未覆盖的 hash 绑定、version 绑定、outcomeUnknown 对账、幂等键派生、过期与并发决策在本篇首次完整覆盖

---

## 1. 定位与全景

全部外部写操作（发邮件、建/改/删日历事件）都必须经过审批。核心不是"加一道确认对话框"，而是**审批对象活在对话之外**：它是 `records(kind="actions")` 的持久实体，有生命周期、过期时间、内容指纹；对话工具面里**没有任何工具能批准它**。

`engine/model.ts:331` 的任务 prompt 原文：

```
External writes require prepare_email/prepare_event; there is no tool to approve them.
```

```
模型侧（对话或任务内）只能调 prepare_email / prepare_event
  ▼  AgentService.prepare（service.ts:754-793）
  ├─ guard() 自证租约 + 校验 connectionId 未变（任务级账号绑定）
  ├─ ActionService.propose（actions.ts:39-101）
  │    幂等 id = sha256(key) 或 randomUUID → prepare 解析目标（读当前事件 → target + etag）
  │    hash = sha256({input, connection, target, targetVersion})；expiresAt = now + 30min
  │    落库 awaiting_review + 写 activity
  └─ checkpoint({actionId}) → 任务转 waiting_approval
  ▼  人（原生 App 审批界面，不是对话）：POST /api/actions/:id {hash, decision}
  ▼  ActionService.decide（actions.ts:102-207）
  ├─ 1 hash 比对  2 status 必须 awaiting_review（幂等）  3 任务必须在 running/waiting_approval
  ├─ 4 过期检查（过期则 CAS 成 expired 并 409）  5 connected + connection/account 三重比对
  ├─ 6 db.claim → CAS 到 executing（原子认领，含任务存在性二次校验）
  └─ 7 execute（携带 targetVersion → If-Match）→ 8 终态 succeeded / failed / outcome_unknown
```

## 2. 审批对象模型

### 2.1 `ActionProposal`（`index.ts:143-167`）

字段分五组：**目标**（`target?: CalendarEvent` 是 prepare 时读到的快照、`targetVersion?: string` 是它的 etag）；**归属**（`taskId?`、`account?`、`connectionId?`）；**内容**（`id`、`title` 由服务端写就而非模型转述、`kind`、`data`）；**状态**（八态 `awaiting_review`/`executing`/`succeeded`/`failed`/`outcome_unknown`/`denied`/`cancelled`/`expired`）；**凭据与时间**（`hash` 内容指纹、`createdAt`/`expiresAt`、`result?`/`error?`）。

**八态**（对比任务九态）：多了 `outcome_unknown`，没有 `paused`/`scheduled`/`waiting_*`——审批是"一次性决策 + 一次性执行"，不是可暂停的工作流。

### 2.2 四种提案类型（`index.ts:128-139`）

`email.send` / `calendar.create` / `calendar.update` / `calendar.delete`，discriminated union。两处值得注意的校验：

- **subject 禁止换行**（`index.ts:75-80`）：`refine((s) => !/[\r\n]/.test(s), "Subject must be a single line")`——防邮件头注入（`\r\n` 可插入额外头字段）；998 是 RFC 5322 行长度上限；
- **eventDraftSchema 的 superRefine**（`:98-127`）：end > start；all-day 用 date-only、timed 用带显式 offset 的 ISO；timeZone 必须被 `Intl.DateTimeFormat` 接受。

## 3. 幂等键 → sha256 派生 id

`actions.ts:39-52`：

```ts
const id = idempotencyKey === undefined ? randomUUID()
  : createHash("sha256").update(idempotencyKey).digest("hex");
if (idempotencyKey !== undefined) {
  const existing = await this.db.get<ActionProposal>(owner, "actions", id);
  if (existing) return existing;
}
```

**关键区分**：`undefined` 时走 `randomUUID`（每次都是新提案，如 sample 种子数据 `workspace.ts:272`）；带 key 时 id 确定，重放返回已有提案。

调用方传的 key：

| 调用方 | key | 证据 |
|---|---|---|
| 任务内（document 回复） | `${task.id}:document-reply` | `service.ts:768,1051` |
| 任务内（模型 prepare_email） | `sha256(JSON.stringify(data))` | `model.ts:249` |
| 任务内（模型 prepare_event） | `sha256(JSON.stringify(data))` | `model.ts:267` |

**模型侧用内容 hash 作 key**：同一任务里重复提交**完全相同**的草稿 → 返回同一张审批单；内容有任何变化 → 新审批单。配合 prompt 的 "Once ask_user or a prepare tool pauses the task, stop"（`model.ts:331`）形成双保险。

落库分支（`actions.ts:90-98`）：

```ts
const saved = idempotencyKey === undefined
  ? await this.db.put(owner, "actions", proposal)
  : await this.db.insertIfAbsent(owner, "actions", proposal);
if (!saved) {   // 并发下输了：读回赢家的提案
  const existing = await this.db.get<ActionProposal>(owner, "actions", id);
  if (!existing) throw new AppError("Prepared action could not be loaded", 409);
  return existing;
}
```

带 key 时用 `insertIfAbsent`（`ON CONFLICT DO NOTHING RETURNING`）——两个并发请求都通过了前置 `get`（都返回 null）时，插入阶段仍只有一个成功。

## 4. hash 绑定：审批确切内容

### 4.1 指纹构造（`actions.ts:77-86`）

```ts
hash: createHash("sha256").update(JSON.stringify({
  input, connection, target: prepared?.target, targetVersion: prepared?.targetVersion,
})).digest("hex"),
```

指纹覆盖四样东西：待执行内容（`input`）、连接（`connection`，含 id 与 account）、目标快照（`target`）、目标版本（`targetVersion`）。

注意 `input` 是 prepare **之后**的版本（`:58`）：`const input = proposalSchema.parse(prepared?.input ?? parsed);`——所以服务端在 prepare 阶段补全的字段（如 `calendar.delete` 时从 Google 读到的真实 title，`workspace.ts:402-406`）也进入指纹。

### 4.2 校验点（`actions.ts:108-111`）

客户端提交的 `hash` 必须与库里一致（不符则 409 "This proposal changed. Open its latest review before deciding."）。**UI 展示的 hash 与执行的 hash 是同一个**。

**解决什么**：审批的本质是"人同意了一件具体的事"。没有 hash 绑定时，"同意"这个动作可被重放到内容已变的提案上（TOCTOU）。hash 让"同意"与"内容"在密码学上绑定。

### 4.3 hash 与 If-Match 的分工

- **hash**：绑定"人看到的内容" vs "将要执行的内容"——**审批时刻**的一致性；
- **targetVersion (If-Match)**：绑定"prepare 时读到的目标" vs "执行时目标"——**prepare 到 execute 之间**的外部变更检测。

hash 里包含 `targetVersion`，所以 etag 变化会导致 hash 变化（第一道闸拒绝）；`decide` 里的 If-Match 是第二道闸，防"审批通过到执行完成"之间的变化。

## 5. version 绑定：If-Match 执行锁

### 5.1 prepare 阶段抓快照（`workspace.ts:392-410`）

三点：**`email.send` 校验附件存在**（逐个 `files.get`，抛 404）；**`calendar.create` 不抓快照**（无既有目标）；**`calendar.delete` 用服务端读到的 title 覆盖客户端值**（`data: {...input.data, title: reviewed.event.title}`）——审批卡展示的是**服务端确认过的**标题，不是模型或客户端说的。其余走 `reviewEvent(calendarId, eventId)` 返回 `{target: reviewed.event, targetVersion: reviewed.version}`。

### 5.2 ETag 读取（`google.ts:577-583`）

`eventVersion(event, expectedVersion?)`：**无 etag 即拒绝**（"Google event has no ETag; prepare a fresh review"，不降级为"不检查"）；`singleLine(event.etag)` 防 etag 里混入换行（header 注入防御）；`expectedVersion !== undefined && version !== expectedVersion` 则抛 409 "This event changed since review. Prepare a new action."。

### 5.3 执行时下发 If-Match（`google.ts:842,857`）

```ts
{ "If-Match": this.eventVersion(current, expectedVersion) }   // updateEvent
{ "If-Match": this.eventVersion(current, expectedVersion) }   // deleteEvent
```

执行前**再读一次**事件，把"执行时的 etag"与"审批时的 etag"比对，同时把 etag 作为 `If-Match` 下发——即便两次读之间又有变化，Google 侧的条件写也会拒绝。

### 5.4 缺 targetVersion → fail-closed（`workspace.ts:451-455`）

```ts
if ((input.kind === "calendar.update" || input.kind === "calendar.delete") && !targetVersion)
  throw new AppError("This calendar review predates target-version checks. Prepare a new review.", 409);
```

**老提案不允许执行**，文案明确说"prepare a new review"而非"试试看"。

### 5.5 重放检测（`google.ts:543-554`）

```ts
if (event.id !== eventId) throw new Error("Google returned a different event");
if (event.recurrence !== undefined || event.recurringEventId !== undefined)
  throw new RecurringEventError();
```

返回的事件 id 必须匹配（防串号）；**循环事件显式拒绝**——对 recurrence 做 update/delete 的语义与单次事件不同，OpenMuse 选择不支持而非"尽量猜"。

## 6. 审批过期与并发决策

### 6.1 过期检查（`actions.ts:121-135`）

过期时主动 CAS 成 `expired`，条件带 `{status: "awaiting_review", hash, expiresAt}`（防与并发决策打架）；**CAS 失败说明状态已变（比如刚被批准）→ 读回现状返回，不报错**；CAS 成功则抛 409 "This review expired. Create a fresh proposal."。

**过期不是被动等待**：主动 CAS 改成 `expired`（条件带 `hash` 与 `expiresAt`，防与并发决策打架）。过期时间 30 分钟（`:88`）。另一入口在 TaskWorker tick（`worker.ts:98-109`），两条路径用同一 CAS 条件。

### 6.2 前置校验顺序（`actions.ts:102-149`）

顺序：**hash 比对**（不符 → 409 "This proposal changed."）→ **状态幂等**（非 `awaiting_review` 直接返回现状，重复点批准不报错，返回当前状态让 UI 同步）→ **任务状态**（带 `taskId` 的批准要求任务在 `running`/`waiting_approval`，否则 409 "Resume the task before approving this action. Cancelled tasks cannot execute."）→ **过期检查**（§6.1）→ **connected 检查** → **三重连接比对**（`connection.id` 与 `connection.account` 都要匹配，防"提案时用 a@x.com，批准时已切到 b@x.com"）。

### 6.3 原子认领：`db.claim`（`db.ts:116-128`）

```sql
UPDATE records AS action SET data=jsonb_set(data,'{status}',$4::jsonb),updated_at=now()
WHERE owner=$1 AND kind='actions' AND id=$2 AND data->>'status'='awaiting_review'
  AND (data->>'expiresAt')::timestamptz>$3::timestamptz
  AND ($4::jsonb <> '"executing"'::jsonb OR data->>'taskId' IS NULL OR EXISTS (
    SELECT 1 FROM records task WHERE task.owner=action.owner AND task.kind='tasks'
    AND task.id=action.data->>'taskId' AND task.data->>'status' IN ('running','waiting_approval')
  )) RETURNING data
```

三条件同时成立才允许：状态是 `awaiting_review`（防重复决策）；未过期（在 SQL 里比对）；**若要转 `executing` 且属于某任务，该任务必须仍在 `running`/`waiting_approval`**。

第 3 条的意义：应用层已检查过一次任务状态（§6.2），但那与 `claim` 之间有时间窗。**把检查搬进 SQL，窗口消失**。`$4::jsonb <> '"executing"'::jsonb` 表示"只有批准才需要这项检查"，deny 不需要。`RETURNING data` 让"认领成功"与"读取状态"是同一次操作。

### 6.4 认领失败与执行后二次校验（`actions.ts:156-182`）

**认领失败不报错**：另一个并发决策赢了，读回当前值返回，让 UI 显示一致状态。**认领之后再查一次任务**（`:167-182`）：若任务已取消则**回滚审批单状态**（`executing` → `awaiting_review`）并抛 409——因为**什么都没执行**，提案仍应可决策（用户恢复任务就能再批准）。

## 7. `outcomeUnknown` 语义与对账

### 7.1 判定（`actions.ts:193-203`）

```ts
const unknown = error instanceof Error &&
  (("outcomeUnknown" in error && error.outcomeUnknown === true) ||
    ("code" in error && error.code === "outcome_unknown"));
finished = { ...claimed, status: unknown ? "outcome_unknown" : "failed",
  error: error instanceof Error ? error.message : "Execution failed" };
```

**两种错误形状都识别**：属性 `outcomeUnknown === true`（Google 侧）或 `code === "outcome_unknown"`（OpenBot 侧）。适配器可自由选择形状。

### 7.2 产生条件（`google.ts:610-640`）

```ts
// Credential failures happen before dispatch, so their outcome is definite.
} catch {
  if (write) throw new OutcomeUnknownError();
  throw new Error("Could not reach Google; check the connection and try again");
}
if (write && (response.status >= 500 || response.status === 408)) throw new OutcomeUnknownError();
try { return await readJson(response); }
catch { if (write) throw new OutcomeUnknownError(); throw new Error("Google returned an invalid or oversized response"); }
```

**三类 → outcome_unknown**（仅写操作）：网络异常（请求可能已送达）、5xx/408（服务端可能已处理）、响应不可解析/超限（返回了什么但我们读不懂）。

**一类 → 确定失败**：凭据失败（注释原文 "Credential failures happen before dispatch, so their outcome is definite."）——请求根本没发出去。**读操作永远不 `outcome_unknown`**（读无副作用）。

响应 schema 不符也抛 `OutcomeUnknownError`（`:806-814,824-828,844-848`）——**收到 200 但响应格式不认识**，同属"可能已发生"。

### 7.3 对账流程（用户侧）

错误文案（`google.ts:20-28`）："Google may have completed this action. Check Google before trying again."

`service.ts:278-285` 的 retry 拦截：

```ts
if (a && a.status !== "succeeded")
  throw new AppError("Check the reviewed action before retrying; its outcome may be uncertain. Start a new task when reconciled.", 409);
```

**任务重试被显式阻断**：只要审批单不是 `succeeded`，`retry` 就 409。用户必须先去 Google 确认，确认后再"Start a new task"。

### 7.4 服务重启对账（`db.ts:129-133`）

```sql
UPDATE records SET data=data || '{"status":"outcome_unknown","error":"Server restarted during execution. Check the provider before creating another action."}'::jsonb
WHERE kind='actions' AND data->>'status'='executing'
```

**启动时一次性把残留的 `executing` 全标为 `outcome_unknown`**。进程在"认领成功"与"写完终态"之间崩溃时会留下 `executing`——这条 SQL 把它转成明确的不确定状态并给出对账指引。用 `||`（jsonb 合并）而非 `jsonb_set`：整条 UPDATE 只写两个字段，其余保留。

### 7.5 任务侧的对账闭环

任务在 `waiting_approval` 被唤醒后（[02 篇](02-task-engine.md) §4.3），`execute` 读到 action 状态不是 `awaiting_review`/`executing` 时抛 `` `Reviewed action ${action.status}: ${action.error ?? "No further action was taken"}` ``（`service.ts:815-818`）。错误消息含状态与原因 → 任务进 `failed` → `publishOutcome` 发通知（key `task-error:<id>:<attempts>`）→ 用户看到"任务需要关注" + 具体原因。**对账链条完整闭合**。

## 8. 隔离的 8 层结构

| # | 层 | 机制 | 证据 |
|---|---|---|---|
| 1 | **工具面** | 只有 `prepare_email`/`prepare_event`，**没有 approve 工具** | `model.ts:244-285`；`conversation.ts:149-380` 工具清单无审批工具 |
| 2 | **prompt 声明** | "there is no tool to approve them" | `model.ts:331` |
| 3 | **数据面** | 审批是 `records(kind="actions")` 的独立实体 | `db.ts:119` |
| 4 | **HTTP 面** | 决策走 `/api/actions/:id`，与对话端点分离 | `app.ts:133-144`；`engine/routes.ts` 无 approve 路由 |
| 5 | **内容绑定** | hash 覆盖 input + connection + target + targetVersion | `actions.ts:77-86,110-111` |
| 6 | **版本绑定** | If-Match + etag 重读比对 | `google.ts:577-583,842,857` |
| 7 | **状态机** | 八态；`executing` 是认领标记，`claim` 原子校验任务存在性 | `db.ts:116-128` |
| 8 | **连接绑定** | connectionId + account 双重比对，任务侧还有 `state.connectionId` 快照 | `actions.ts:138-149`；`service.ts:762-767` |

**为什么是 8 层而不是 1 层**：每层单独都可被绕过（prompt 可被注入说服、HTTP 端点可被 CSRF 若没 session、状态机可被并发竞争），叠加后攻击者需同时绕过所有层。

## 9. `activity` 审计（`actions.ts:208-217`）

```ts
private async record(owner, action: ActionProposal, detail: string) {
  await this.db.put(owner, "activity", {
    id: randomUUID(), actionId: action.id, title: action.title,
    detail, date: new Date(this.now()).toISOString(), status: action.status,
  });
}
```

四个记录点：`propose` 后（"Ready for your review"）、`deny`（"Declined; no changes made"）、`approve`（"Approved; execution started"）、执行终态（`finished.result ?? finished.error ?? finished.status`）。

**追加式**（随机 id，永不覆盖），能看到一张审批单的完整轨迹。与 `run-events`（任务内轨迹）互补：`activity` 面向"外部动作"。

## 10. 与 Talorys prepare/commit 的逐项对照

| 维度 | Talorys | OpenMuse |
|---|---|---|
| 提案形状 | `pending_actions` 表 + 工具返回 pending 对象 | `records(kind="actions")` + 八态 |
| 目标解析 | prepare 解析 targetId + summary | prepare 读 Google 事件 → `target` + `targetVersion`(etag) |
| 执行路径 | commit 工具（轮次内有执行路径） | `ActionService.decide`（对话内**完全没有**） |
| 内容指纹 | 无 | `sha256(input + connection + target + targetVersion)` |
| 版本绑定 | 无 | etag + If-Match + 执行前重读比对 |
| 幂等 | 无（每次 prepare 新建） | `sha256(key)` 派生 id + `insertIfAbsent` |
| 过期 | 30 分钟 TTL + 定期清理 | 30 分钟 + 两个主动过期入口（decide / worker tick） |
| 并发决策 | `UPDATE … WHERE status='pending' AND expires_at > now` | `db.claim`（额外校验任务存在性）+ 认领失败静默返回现状 |
| 结局回灌 | `withApprovalOutcomes` 注记进历史消息 | `state.approvalResult` + `finish`（任务无历史） |
| 不确定结局 | 无 | `outcome_unknown` + 服务重启对账 + retry 拦截 |
| 强制力 | "轮次内没有执行路径" | 8 层叠加 |

**核心差异**：Talorys 的强制力来自"destructive 是另一种工具形状"（一个函数无法被误调）；OpenMuse 来自"审批是对话外的实体 + 内容与版本双重绑定"。Talorys 更简洁，OpenMuse 更能抵抗并发与外部变更。

**对 Memoria 的含义**：feat-066 目前接近 Talorys 形态。增量按性价比：(1) hash 绑内容（防 TOCTOU）；(2) 幂等键派生 id；(3) 过期与并发决策的原子认领；(4) 版本绑定（仅当 Memoria 有"外部可变目标"时，如 IMAP 的 UIDVALIDITY/UID 组合）。

## 11. 与既有研究的对照

- **与 04b §11 的关系**：04b 已给出"审批对象活在对话之外"、生命周期 10 步、结构强制 8 层与 `no tool to approve them`。增量：hash 的**四元组构造**与 TOCTOU 作用、`claim` SQL 里任务存在性子查询的完整语义（含 `$4::jsonb <> '"executing"'::jsonb` 的意图）、`outcomeUnknown` 的**三类产生条件与一类确定失败**、`recoverInterruptedActions` 的重启对账、幂等键的**两种模式**、`emailDraftSchema` 的 header 注入防御、`prepare` 失败时的补偿 deny。
- **与 talorys 工具审批（[../talorys/04-tools-approval.md](../talorys/04-tools-approval.md)）**：见 §10。共同点：目标解析与执行分离、审批卡展示服务端写就的内容、原子认领、TTL。差异：OpenMuse 多内容指纹、版本绑定、幂等键、不确定结局四类——都是"外部世界可能在决策时变化"的应对，Talorys 的单 DO 环境不需要。
- **与 hermes 工具（[../hermes/05-tools.md](../hermes/05-tools.md)）**：hermes 的工具审批是"对话内确认"（用户在下条消息同意）；OpenMuse 明确切断这条路径。两者对"prompt 注入能否说服模型批准"的假设不同：hermes 认为用户在场即可，OpenMuse 认为对话内容不可信（因为工具结果会进对话），所以必须物理隔离。
- **与 04-openmuse.md §3.3 的关系**：旧研究写"`waiting_approval` 是任务状态机的一等状态……审批通道与对话通道物理隔离"。**结论一致，本篇给出 8 层的逐层证据与四个新机制**。

## 12. 对 Memoria 的可迁移结论

**适合搬（6 条）**：

1. **"对话工具面里没有批准工具"（`model.ts:331`）**：Memoria 红线"任何归档必须人工确认"目前是 instructed（prompt 声明），这是把它变成 **enforced** 的最小改动。落点：`app/` 的归档提案与审批端点。
2. **hash 绑内容（`actions.ts:77-86,110-111`）**：提案应带内容指纹，决策时比对。落点：提案表加 `hash` 列。
3. **幂等键派生 id（`actions.ts:45-52`）**：邮件分拣可能对同一封邮件重复提案；用 `sha256("archive:<messageId>")` 作 id 天然去重。
4. **过期 + 原子认领（`actions.ts:121-160`、`db.ts:116-128`）**：两个用户动作（或一个用户 + 一个定时清理）同时决策时的正确性。
5. **`outcome_unknown` 语义（`actions.ts:193-203`、`google.ts:610-640`）**：任何外部写（IMAP 移动邮件、SMTP 发信）超时后都必须区分"确定失败"与"可能已发生"。落点：邮件操作的工具层。
6. **"不确定就不许重试"的拦截（`service.ts:278-285`）**：直接 409 并给出对账指引，比"提示用户小心"更强。

**不适合搬（3 条）**：etag/If-Match 版本绑定（IMAP 无 etag，应找等价物如 UIDVALIDITY+UID）；`activity` 独立审计表（Memoria 已有 progress/日志体系，加 `actionId` 字段即可）；八态审批状态机（`executing` 是为"长执行 + 崩溃恢复"准备的，短操作可省）。

## 13. 证据索引

| 结论 | 文件:行 |
|---|---|
| ActionProposal 八态与全字段 / 四种提案类型 / subject 禁换行 / 时区校验 | `packages/domain/src/index.ts:71-167` |
| propose 幂等（sha256 派生 id + 先查）/ prepare 后 parse / hash 四元组 / expiresAt 30min | `apps/server/src/actions.ts:39-58,77-88` |
| put vs insertIfAbsent + 并发读回 | `apps/server/src/actions.ts:90-98` |
| decide 的 hash 比对 / 已决返回现状 / 任务状态前置校验 / 过期 CAS + 失败读回 | `apps/server/src/actions.ts:108-135` |
| connected + connection id/account 双重比对 / claim 调用 + 认领失败静默返回 | `apps/server/src/actions.ts:136-160` |
| 执行后二次任务校验 + 回滚 / outcomeUnknown 两种错误形状 / activity 追加式审计 | `apps/server/src/actions.ts:167-217` |
| claim SQL（含任务存在性子查询）/ recoverInterruptedActions | `apps/server/src/db.ts:116-133` |
| prepare：连接绑定 + 补偿 deny + approval 事件 / 审批路径四分支 | `apps/server/src/engine/service.ts:754-820` |
| retry 拦截（不确定不许重试）/ cancel 时自动 deny 未决审批 | `apps/server/src/engine/service.ts:278-285,320-324` |
| 模型侧 prepare_email/prepare_event / "there is no tool to approve them" | `apps/server/src/engine/model.ts:244-285,331` |
| workspace.prepare（附件校验 / create 跳过 / delete 覆盖 title）/ workspace.execute | `apps/server/src/workspace.ts:392-481` |
| OutcomeUnknownError 类与文案 / eventVersion（无 etag 即拒绝 + 不匹配 409） | `packages/integrations/src/google.ts:20-28,577-583` |
| 三类 outcome_unknown 产生点 / 响应 schema 不符 / If-Match 下发 / 重放检测 | `packages/integrations/src/google.ts:543-554,610-640,806-857` |
| worker tick 里的审批过期分支 / 审批单即回执 | `apps/server/src/engine/worker.ts:90-111`；`apps/server/src/engine/service.ts:815-819` |
