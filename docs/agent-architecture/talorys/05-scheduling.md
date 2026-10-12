# Talorys 核心设计 · 05 调度与自动化

> 研究对象：`rociiu/talorys` — 单用户个人 agent（Cloudflare Durable Object），v0.1.4，HEAD `2cc547c`
> 路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦：递归规则与 DST 语义（`packages/shared/src/recurrence.ts`）、调度服务（`agent/scheduling.ts`）、三种自动化 kind、启动对账与补跑
> 与 hermes 的 cron（`hermes/07-scheduling.md`）同属 at-most-once 调度设计，两个独立实现互相验证了同一组不变量

---

## 1. 定位与全景

Talorys 的调度建立在 Cloudflare Agents SDK 的 `schedule()` 之上（DO alarm 的封装），但所有可靠性逻辑都是自己写的：

```
用户/API 创建自动化
  └─ AutomationService.create → computeNextRun → scheduler.schedule（SDK 单 shot）→ 存 schedule_id
       │
触发（DO alarm → runAutomation）
  └─ AutomationService.fire(automationId, scheduleId, execute)
       ├─ 三闸防重复：存在性 / schedule_id 一致 / 非 running
       ├─ startRun 落回执 → status = running
       ├─ execute（三种 kind 之一）
       ├─ finishRun 落回执
       ├─ 检查 owner 是否在等待期间改动（ownsSchedule）
       └─ arm 下一次（锚定 max(now, 刚触发的槽位)）

启动（DO onStart）
  └─ AutomationService.reconcile()
       └─ 每个启用自动化的 schedule_id 必须在 SDK 里真实存在 → 否则修复
            ├─ 错过 < 24h → 排到 now+1s 补跑一次
            └─ 错过 ≥ 24h → 只 arm 下一次
```

核心设计：**每个启用的自动化恰好持有一个 pending one-shot SDK schedule**（注释 `scheduling.ts:9-12`）——不用 cron 表达式、不用重复日程，触发后自己算下一次。这个选择让"墙钟规则在 DST 与时区变更下正确"成为可能。

## 2. 递归规则与 DST 语义（`packages/shared/src/recurrence.ts`）

### 2.1 五种 ScheduleSpec（21-40）

```ts
export const scheduleSpecSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("once"), at: z.string().regex(/^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$/)
      .refine(/* isValidCalendarDate */) }),                                    // 本地墙钟，非 UTC
  z.object({ type: z.literal("daily"), time: hhmm }),
  z.object({ type: z.literal("weekly"), days: z.array(z.number().int().min(0).max(6)).min(1).max(7), time: hhmm }),
  z.object({ type: z.literal("monthly"), day: z.number().int().min(1).max(31), time: hhmm }),
  z.object({ type: z.literal("interval"), minutes: z.number().int().min(15).max(60 * 24 * 31) }),
]);
```

- **全部墙钟时间**（`YYYY-MM-DDTHH:MM` 本地时间），不是 UTC——用户说"每天 9 点"就是本地 9 点。
- `isValidCalendarDate`（17-19）拒绝 2026-02-31 这类不存在的日期。
- `interval` 下限 15 分钟、上限 31 天——防误配高频任务烧配额。

### 2.2 DST 语义（头注 4-12）

```
Daylight-saving behaviour:
 - A wall time that does not exist (spring-forward gap) runs at the first
   valid instant after the gap, e.g. 02:30 becomes 03:30.
 - A wall time that occurs twice (fall-back overlap) runs once, at the
   earlier occurrence.
```

**这是显式声明的产品语义**，不是实现细节。实现（`zonedTimeToUtc` 108-128）：

```ts
const wall = Date.UTC(year, month - 1, day, hour, minute);          // 墙钟当 UTC 的毫秒
const before = timeZoneOffsetMs(wall - 36 * 3600_000, timeZone);    // 转换前偏移
const after  = timeZoneOffsetMs(wall + 36 * 3600_000, timeZone);    // 转换后偏移
const candidates = [...new Set([wall - before, wall - after])]
  .filter((t) => { const p = getZonedParts(new Date(t), timeZone);   // 候选必须能还原墙钟时间
    return p.year === year && p.month === month && p.day === day && p.hour === hour && p.minute === minute; })
  .sort((a, b) => a - b);                                            // 排序 → 取最早
if (candidates.length > 0) return new Date(candidates[0]!);           // 正常 / 秋拨重叠 → 较早者
return new Date(wall - before);                                      // 春拨缺口 → 用转换前偏移（落在缺口后）
```

- 取 ±36h 的偏移量（>24h，保证跨越任何 DST 转换）生成两个候选，验证候选能还原墙钟时间——**验证式实现**比查 DST 表更稳。
- 春拨缺口：两个候选都还原不出目标墙钟时间 → 用转换前偏移，自然落在缺口后第一个有效时刻（02:30 → 03:30）。
- 秋拨重叠：两个候选都有效 → 排序取较早（只跑一次）。

### 2.3 下一次计算（`computeNextRun` 139-171）

```ts
if (spec.type === "interval") return new Date(after.getTime() + spec.minutes * 60_000);
if (spec.type === "once") { const t = zonedTimeToUtc(...); return t > after ? t : null; }   // 过期 → null
// daily/weekly/monthly：从 after 的本地日期开始，最多走 400 天
for (let i = 0; i < 400; i++) {
  if (matches) { const t = zonedTimeToUtc(y, mo, d, h, mi, timeZone); if (t > after) return t; }
  cursor.setUTCDate(cursor.getUTCDate() + 1);
}
```

- **`interval` 是纯算术**（`after + N 分钟`）——不受 DST 影响，因为它是"时长"不是"墙钟"。
- `once` 已过期返回 **null**（调用方据此把自动化置为 completed）。
- 步行 400 天（注释："400 covers every monthly/weekly rule"）——足够覆盖任何周/月规则的下一次命中。
- **monthly 的 day 钳到当月天数**（163）：`d === Math.min(spec.day, daysInMonth(y, mo))`——31 日在 2 月即 28/29 日。
- 严格 `t > after`：下一次必须严格晚于当前时刻。

### 2.4 其他工具函数

- `getZonedParts`（86-98）：用 `Intl.DateTimeFormat` 的 `formatToParts` 取本地年/月/日/时/分/秒/星期；**formatter 按 timeZone 缓存**（54-73）——Intl 构造昂贵，缓存是关键优化。
- `timeZoneOffsetMs`（101-105）：`asUtc - floor(instant/1000)*1000`——把"本地时间当 UTC"与真实时刻的差作为偏移。
- `isValidTimeZone`（75-82）：构造 formatter 试探（抛错即非法）。
- `describeSchedule`（175-189）：人类可读描述（"Every Monday, Wednesday at 09:00" / "Every 2 hour(s)"）——存进 `schedule_description` 供 UI 显示。

## 3. 调度服务（`agent/scheduling.ts`）

### 3.1 Scheduler 抽象（13-18）

```ts
export interface Scheduler {
  schedule(at: Date, automationId: string): Promise<string>;   // 返回 schedule id
  cancel(scheduleId: string): Promise<void>;
  exists(scheduleId: string): Promise<boolean>;
}
```

由 `talorys-agent.ts:39-48` 实现（包 SDK 的 `this.schedule()` / `cancelSchedule()` / `getScheduleById()`）。**抽象让调度服务不依赖 SDK**——测试可注入内存实现，且 `exists` 是 reconcile 的关键能力。

### 3.2 创建与武装（44-54, 96-107）

```ts
async create(input) {
  const schedule = scheduleSpecSchema.parse(input.schedule);
  if ((input.kind === "reminder" || input.kind === "agent_prompt") && !input.message.trim())
    throw new ValidationError(input.kind === "reminder" ? "A reminder needs a message." : "An AI automation needs a prompt.");
  const first = computeNextRun(schedule, this.tz(), new Date());
  if (!first) throw new ValidationError("That time is in the past. Choose a future time.");
  const automation = this.repo.create({...input, schedule});
  this.activity.record("automation.created", `Created automation "${automation.name}"`);
  return automation.enabled ? this.arm(automation) : automation;
}

private async arm(automation, after = new Date()): Promise<Automation> {
  const next = computeNextRun(automation.schedule, this.tz(), after);
  if (!next) return this.repo.update(automation.id, {status: "completed", enabled: false, next_run: null, schedule_id: null});
  const scheduleId = await this.scheduler.schedule(next, automation.id);
  return this.repo.update(automation.id, {status: "scheduled", next_run: next.toISOString(), schedule_id: scheduleId});
}
```

- **arm 是幂等的单一职责**：算下一次 → 排日程 → 存 id。`once` 型算不出下一次 → 置 completed 并停用。
- `disarm`（109-111）：有 schedule_id 就 cancel（幂等）。

### 3.3 更新与删除（56-94）

- `update`（56-73）：**只有 timing 变了才重新武装**（`timingChanged = schedule 变 || enabled 变`）；先 disarm 再 arm——防旧日程残留。
- `delete`（75-80）：先 disarm 再删行——**不留悬空日程**。
- `rearmAll`（86-94）：遍历全部自动化，先 disarm，启用的重新 arm，停用但残留 schedule_id 的显式置 paused——用于时区变更/导入后。

### 3.4 触发与防重复三闸（113-152）

```ts
async fire(automationId, scheduleId, execute) {
  const automation = this.repo.get(automationId);
  if (!automation?.enabled || automation.schedule_id !== scheduleId || automation.status === "running") return;   // 三闸
  const run = this.repo.startRun(automation);
  this.repo.update(automation.id, {status: "running"});
  let lastResult = null, lastError = null;
  try {
    const outcome = await execute(automation);
    lastResult = outcome.result.slice(0, 2000);
    this.repo.finishRun(run.id, outcome.status, lastResult, null);
  } catch (error) {
    lastError = error instanceof Error ? error.message : String(error);
    this.repo.finishRun(run.id, "error", null, lastError);
    this.activity.record("automation.failed", `Automation "${automation.name}" failed: ${lastError}`);
  }
  const current = this.repo.get(automation.id);
  this.repo.pruneRuns();
  // The owner can pause, delete or reschedule while the executor awaits AI.
  // Keep the completed run receipt without claiming a replacement schedule.
  if (!current) return;                                                            // 被删除
  const ownsSchedule = current.enabled && current.schedule_id === scheduleId;
  const updated = this.repo.update(automation.id, {last_run, last_result, last_error, run_count: current.run_count + 1,
    ...(ownsSchedule ? {schedule_id: null, status: lastError ? "failed" : "scheduled"} : {})});
  if (!ownsSchedule) return;                                                       // 被暂停/重排
  const slot = automation.next_run ? new Date(automation.next_run) : new Date();
  const after = new Date(Math.max(Date.now(), slot.getTime()));                     // 锚定 max(now, 槽位)
  const rearmed = await this.arm(updated, after);
  if (lastError && rearmed.enabled) this.repo.update(automation.id, {status: "failed"});
}
```

**三闸的分工**（注释 114-116："Stale schedules (automation deleted, paused or re-armed since) are ignored, so double execution cannot happen"）：

| 闸 | 判据 | 拦截的场景 |
|---|---|---|
| 存在且启用 | `!automation?.enabled` | 自动化已删除 / 已暂停 |
| schedule_id 一致 | `automation.schedule_id !== scheduleId` | 触发的是已被替换的旧日程（re-arm 后的残留 alarm） |
| 非 running | `automation.status === "running"` | 重复回调 / 上一次还没跑完 |

**执行期间的 owner 变更保护**（133-146）：

- `current` 为 null（被删）→ 保留回执，**不认领替换日程**。
- `ownsSchedule`（仍启用且 schedule_id 未变）才更新日程字段并 arm 下一次；否则只更新回执数据。

**下一次调度锚定**（147-150）：`max(now, 刚触发的槽位)`——如果执行耗时 3 分钟而 interval 是 15 分钟，下一次是"槽位 + 15 分钟"而不是"now + 15 分钟"，防止长执行导致快进连发。若执行时间超过整个间隔，锚定 now 保证不排到过去。

**回执独立于状态**（119-131）：`startRun` / `finishRun` 写 `tal_automation_runs` 表（含 automation_name 快照），状态失败也要有记录；`pruneRuns`（134）防膨胀。

### 3.5 启动对账 `reconcile`（154-175）

```ts
/** Makes sure every enabled automation has a live SDK schedule. Recovers from
 *  interrupted runs and lost schedules; a recently missed run executes once. */
async reconcile(): Promise<{repaired: number}> {
  let repaired = 0;
  for (const a of this.repo.list()) {
    if (!a.enabled) continue;
    const alive = a.schedule_id ? await this.scheduler.exists(a.schedule_id) : false;
    if (alive && a.status !== "running") continue;                        // 健康 → 跳过
    repaired++;
    if (a.schedule_id) await this.scheduler.cancel(a.schedule_id);
    const missedAt = a.next_run ? Date.parse(a.next_run) : NaN;
    if (!Number.isNaN(missedAt) && missedAt <= Date.now() && Date.now() - missedAt < MAX_CATCH_UP_MS) {
      const scheduleId = await this.scheduler.schedule(new Date(Date.now() + 1000), a.id);   // 补跑一次
      this.repo.update(a.id, {schedule_id: scheduleId, status: "scheduled"});
    } else {
      await this.arm(a);                                                   // 只排下一次
    }
  }
  return {repaired};
}
```

调用点在 DO `onStart`（`talorys-agent.ts:55-63`），带 try/catch（对账失败不阻塞启动）并把修复数写 activity log（"Recovered N schedule(s) after restart"）。

**补跑窗口**：`MAX_CATCH_UP_MS = 24 * 3600_000`（21）。判据是 `next_run`（原定时刻）：

- 错过 < 24h → 排到 `now + 1s` 补跑一次（**一次，不是补齐所有错过的**）。
- 错过 ≥ 24h → 直接 arm 下一次（陈旧任务无补跑价值）。
- `status === "running"` 的自动化即使 schedule 存活也进修复分支——**中断的运行需要重新武装**（进程崩溃留下的 running 状态）。

## 4. 三种自动化 kind（`talorys-agent.ts:101-142`）

```ts
private async executeAutomation(a: Automation) {
  switch (a.kind) {
    case "reminder": {
      // Simple reminders never use AI.
      s.notifications.create({title: "Reminder", body: a.message || a.name, automation_id: a.id});
      return {status: "success", result: "Reminder delivered"};
    }
    case "task_digest": { /* 纯 SQL 汇总，见下 */ }
    case "agent_prompt": {
      if (!s.usage.canRunScheduledAi(settings.limits)) {
        s.notifications.create({title: a.name, body: "Skipped: the daily budget for scheduled AI runs was reached. Adjust it in Settings → AI.", automation_id: a.id});
        return {status: "skipped", result: "Scheduled AI budget reached"};
      }
      const text = await this.runner().runScheduledPrompt(a.message);
      s.notifications.create({title: a.name, body: text, automation_id: a.id});
      return {status: "success", result: text.slice(0, 300)};
    }
  }
}
```

### 4.1 降级分层

| kind | 用 AI？ | 产出 | 失败/超额行为 |
|---|---|---|---|
| `reminder` | **否** | 通知（消息文本） | 不适用 |
| `task_digest` | **否** | 通知（overdue + today + open 汇总） | 不适用 |
| `agent_prompt` | 是（read-only 工具） | 通知（模型回复 ≤200 词） | **跳过 + 解释性通知**（非静默失败） |

**两种确定性 kind 永不调用 AI**——"AI 配额耗尽或宕机时全部照常工作"不是口号，是这两个 case 分支的直接后果。

### 4.2 task_digest 的实现（110-127）

```ts
const bounds = localDayBounds(settings.timezone);
const overdue = s.tasks.list({view: "overdue", limit: 20});
const today = s.tasks.list({view: "today", dayStart: bounds.start, dayEnd: bounds.end, limit: 20})
  .filter((t) => !overdue.some((o) => o.id === t.id));                  // 去重（overdue 可能同时 due today）
const open = s.tasks.list({status: "open", limit: 200}).length;
const line = (t) => `- ${t.title}${t.due_at ? ` (due ${formatLocal(t.due_at, settings.timezone)})` : ""}${priority 高 ? ` · ${t.priority}` : ""}`;
const parts = [overdue 段, today 段, `${open} open task(s) in total.`].filter(Boolean);
if (a.message) parts.unshift(a.message);                                 // 用户自定义前缀
s.notifications.create({title: a.name, body: parts.join("\n\n"), automation_id: a.id});
```

- **纯 SQL + 字符串拼装**：无模型、无网络、可预测。
- 时区正确：`localDayBounds` 算 owner 本地日的起止；`formatLocal` 显示本地时间。
- 返回结果字符串（`"3 overdue, 2 due today"`）存进回执。

### 4.3 agent_prompt 的预算检查（128-140）

- `canRunScheduledAi`（`usage.ts:57-59`）= `scheduled_ai_runs < maxScheduledAiRunsPerDay && canUseAi(limits)`——**双重检查**（调度额度 + 总 AI 额度）。
- 超额 → `status: "skipped"` + 通知说明原因与调整位置——用户知道"为什么今天没有摘要"，而不是以为系统坏了。

## 5. 数据模型（`db/migrations.ts:84-119`）

```sql
CREATE TABLE tal_automations (
  id, name, kind, message, schedule(JSON), enabled, status, schedule_id, next_run,
  last_run, last_result, last_error, run_count, created_at, updated_at)

CREATE TABLE tal_automation_runs (
  id, automation_id, automation_name, started_at, finished_at, status, result, error)

CREATE TABLE tal_notifications (id, title, body, automation_id, read_at, created_at)
CREATE INDEX tal_runs_started ON tal_automation_runs(started_at)
```

- `status` 五态（`packages/shared/src/schemas.ts:105`）：`scheduled | running | paused | completed | failed`。
- `schedule_id` 是与 SDK 的关联键（对账与三闸的判据）；`next_run` 是补跑判据。
- **runs 表存 automation_name 快照**（103）：自动化删除后回执仍可读。
- `notifications` 带 `read_at`，未读数缓存在 DO state（`talorys-agent.ts:90-93`）——前端轮询成本极低。

## 6. 与既有研究的对照

- **对比 hermes cron**（`hermes/07-scheduling.md`）：hermes 的 at-most-once 三件套是"分发前推进 next_run_at + CAS 认领 + 投递台账"；Talorys 是"三闸（存在性/schedule_id 一致/非 running）+ onStart 对账 + 补跑窗口"。**两套独立实现验证了同一组不变量**：认领要原子、重复触发要能被识别、崩溃后要能对账。差异在机制——hermes 用 CAS + 台账（多进程/多平台），Talorys 用单 DO 的同步语义 + SDK 日程存在性检查。
- **对比 ZCode/OpenCode 的调度**：那两家是 coding harness，无用户级定时任务；hermes 与 Talorys 是仅有的两个"个人 agent 定时"样本。
- **DST 语义显式声明**：全部研究中唯一一家把"春拨缺口跑在 03:30、秋拨重叠只跑一次"写进头注并实现的。hermes 的 cron 用标准 cron 库语义，未声明 DST 行为。
- **补跑窗口 24h**：hermes 的 at-most-once 不含补跑（错过即错过）；Talorys 的"错过 <24h 补一次"是产品化选择——个人提醒/摘要错过后补跑有价值，陈旧补跑无价值。
- **锚定 max(now, 槽位)**：hermes 的"分发前推进 next_run_at"解决的是同类问题（防重复），Talorys 的锚定解决"长执行后快进连发"，两者互补。
- **确定性 kind 永不调 AI**：与 hermes 的"fail-open/fail-closed 按领域定向"同源——Talorys 把"不用 AI"当作可用性设计。

## 7. 对 Memoria 的可迁移结论

1. **onStart 对账 + 补跑窗口（§3.5）**：Memoria 定时分拣（feat-068）的漏跑补偿——启动时检查"每个启用的任务是否有活着的日程"，错过 <24h 补一次、超 24h 只重排。判据用原定时刻（next_run）而非"上次运行时刻"。
2. **防重复三闸（§3.4）**：`启用 + schedule_id 一致 + 非 running`。Memoria 若用 APScheduler 等库，注意它的 job id 语义——Talorys 的"触发的 schedule_id 必须等于当前存储的 id"能拦住所有"旧日程残留触发"。
3. **执行期间 owner 变更保护（§3.4）**：完成回执但**不认领替换日程**（`ownsSchedule` 检查）——用户在执行中暂停/删除/重排，不会被自动化跑完后的"重新武装"覆盖。
4. **锚定 max(now, 槽位)（§3.4）**：长执行后不连发；Memoria 的 interval 型任务（如每 N 分钟分拣）直接需要。
5. **DST 语义显式声明 + 验证式实现（§2.2）**：Memoria 若支持"每天 9 点"这类墙钟规则，必须处理 DST；实现可用 Talorys 的"±36h 双偏移候选 + 还原验证"法，语义照抄（缺口后移、重叠取早）。
6. **确定性任务不碰 AI（§4.1）**：Memoria 的提醒/汇总类定时任务应做成纯确定性；只有需要判断的（如"这封邮件要不要标记"）才调模型——可用性优先。
7. **超额跳过要解释（§4.3）**：预算耗尽写一条说明性通知（含调整位置），不静默失败。
8. **回执独立于状态 + 名称快照（§5）**：任务删除后回执仍可读；Memoria 任务引擎的运行历史表应存任务名快照。
9. **Scheduler 抽象（§3.1）**：`schedule/cancel/exists` 三方法接口——`exists` 是 reconcile 的前提；抽象让调度服务可测试。

**不适合搬**：DO alarm 的单 shot 机制（Memoria 用自己的调度器，搬"单 pending + 触发后重排"的思想）；SDK `getScheduleById`（等价物按 Memoria 的调度库实现）；400 天步行上限（够用但可换成数学计算，非关键）。

## 8. 证据索引

| 结论 | 文件:行 |
|---|---|
| 五种 ScheduleSpec + 日历日期校验 | `packages/shared/src/recurrence.ts:21-40,17-19` |
| DST 语义声明（缺口后移/重叠取早） | `packages/shared/src/recurrence.ts:4-12` |
| zonedTimeToUtc 验证式实现（±36h 双候选） | `packages/shared/src/recurrence.ts:108-128` |
| computeNextRun（interval 纯算术/once 过期 null/400 天步行/monthly 钳位） | `packages/shared/src/recurrence.ts:139-171` |
| formatter 按 timeZone 缓存 | `packages/shared/src/recurrence.ts:54-73` |
| describeSchedule 人类可读描述 | `packages/shared/src/recurrence.ts:175-189` |
| Scheduler 三方法抽象 | `apps/agent/src/agent/scheduling.ts:13-18` |
| Scheduler 的 SDK 实现 | `apps/agent/src/agent/talorys-agent.ts:39-48` |
| create/arm/disarm（once → completed） | `apps/agent/src/agent/scheduling.ts:44-54,96-111` |
| update 只在 timing 变时重排 / delete 先 disarm | `apps/agent/src/agent/scheduling.ts:56-80` |
| rearmAll（时区变更/导入后） | `apps/agent/src/agent/scheduling.ts:86-94` |
| fire 三闸 + 回执 + ownsSchedule + 锚定 | `apps/agent/src/agent/scheduling.ts:113-152` |
| MAX_CATCH_UP_MS = 24h 补跑窗口 | `apps/agent/src/agent/scheduling.ts:21,158-175` |
| reconcile 实现与 onStart 调用 | `apps/agent/src/agent/scheduling.ts:154-175`、`talorys-agent.ts:55-63` |
| 三种 kind 的降级分层 | `apps/agent/src/agent/talorys-agent.ts:101-142` |
| task_digest 纯 SQL 汇总 | `apps/agent/src/agent/talorys-agent.ts:110-127` |
| agent_prompt 预算检查 + 跳过通知 | `apps/agent/src/agent/talorys-agent.ts:128-140` |
| automations/runs/notifications 表 | `apps/agent/src/db/migrations.ts:84-119` |
| 状态五态枚举 | `packages/shared/src/schemas.ts:105` |
| canRunScheduledAi 双重检查 | `apps/agent/src/services/usage.ts:53-59` |
| 未读数缓存在 DO state | `apps/agent/src/agent/talorys-agent.ts:90-93` |
