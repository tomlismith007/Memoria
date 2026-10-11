# Hermes Agent 核心设计 · 07 调度（cron）

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时（MIT，Python 3.14 + Node）
> HEAD：`main` @ `97a9ae8e`（本地浅克隆，2026-10-11）；本文所有行号出自该版本。
> 范围：`cron/`（39 个模块约 1.85 万行）+ `gateway/run.py` 的 ticker 接线；README 转述一律不入正文，结论均以 `文件:行号` 落证据。

---

## 1. 定位全景

cron 是 Hermes 的"无人值守运行时"：把一个 prompt（或脚本）按 cron/interval/one-shot 计划变成**一次独立的 agent 会话**，把产出投递到聊天平台，失败时通过 incident 体系通知人。

```
gateway 主进程（每主机一个，多路复用多个 profile）
  ├─ housekeeping 线程（60s tick）──> cron ticker（InProcessCronScheduler，可被外部 provider 替换）
  │      └─ scheduler_tick.tick()
  │           ① 抢 tick 文件锁（同机一次只有一个 tick）
  │           ② get_due_jobs()：jobs.json 全量扫描 + 自愈 + 预推进 next_run_at
  │           ③ ThreadPoolExecutor 并行 _process_due_job
  │                └─ claim_job_for_fire（跨进程 at-most-once CAS）
  │                     └─ run_one_job → run_job（新建一次 agent 会话）
  │                          └─ 交付：delivery_queue(sqlite) / bot_chat_pending(json)
  ├─ housekeeping 每 tick drain 交付队列 → Telegram/Discord/Slack/... 适配器
  └─ executions.db：运行账本（claimed→running→completed/failed）+ incidents 表
cron/jobs.json：job 定义 + 调度状态（next_run_at/fire_claim/pending_slot/repeat/unreachable_retry/quota_hold）
```

三层持久化分工明确：**jobs.json** 存"谁该在什么时候跑"（flock 串行化）；**executions.db** 存"每次尝试的账本与 incident"；**deliveries.db + bot_chat_pending/** 存"结果怎么送到人手里"。跨进程正确性全部靠文件锁 + 带时间戳的 claim，无内存共享假设。

## 2. 核心机制

### 2.1 job 数据模型与状态机

- job 记录分两类字段：**authored**（人/agent 写的：name/prompt/skills/schedule/deliver/failure_deliver 等 19 个，`cron/job_definition.py:13-18`）与**scheduler 拥有的**（next_run_at、state、run 计数、各类 claim）。`merge_job_definition` 合并外部 authored store 时只刷新前者、保留后者（`cron/job_definition.py:21-45`）——这是"定义"与"运行状态"的清晰分界。
- 状态是派生而非存储真值：`effective_job_state` 从 `enabled` + pause 标记推导出 paused/scheduled，terminal 的 `completed`/`error` 才是存储态（`cron/jobs.py:542-560`）。`is_job_runnable` 要求 enabled 与无 pause 标记同时成立，"半暂停"记录永不触发（`cron/jobs.py:536-539`）；due 扫描遇到半暂停直接自禁（`_self_disable_half_paused`，`cron/jobs.py:3343-3345`）。
- 一次运行结束由 `mark_job_run` 收口：写 last_run_at/last_status、清 fire_claim/run_claim/pending_slot、`repeat.completed` 递增并重算 next_run_at（`cron/jobs.py:2450-2517`，`_advance_after_run` L2399-2447）。recurring 的 next_run_at 算不出来时置 `state=error` 且**保持 enabled**——把缺依赖静默降级成"已完成"会丢掉整个计划（#16265 注释，`cron/jobs.py:2434-2445`）。`completed` 的 one-shot 记录保留 7 天供检视后被清扫（`cron/jobs.py:2819-2845`）。
- 调度表达：`parse_schedule` 接受 cron 表达式、`every 30m` 自然语言、one-shot（`cron/jobs.py:787`）。`compute_next_run` 对 cron 用 croniter 且**锚定配置时区的墙上时钟**（不是 UTC 偏移），并对 DST 回拨小时枚举两个 fold 取严格晚于基准的候选（`cron/jobs.py:1178-1242`）。

### 2.2 tick 全流程：谁醒、怎么抢、怎么执行、怎么记录

**谁醒**：gateway 的 housekeeping 线程每 60s 一拍；cron trigger 现挂在 `CronScheduler` provider 抽象后面（默认 `InProcessCronScheduler`），旧的内嵌 ticker 只是 deprecated shim（`gateway/run.py:4812-4816`）；另有"cron ticker 监护"每拍检查 ticker 线程死没死（`gateway/run.py:4768-4771`）。housekeeping 侧还有配套角色：misfire 追赶 sweep（每 5 拍，供外部 provider 复用）、交付队列 drain 与文件 watch（`gateway/run.py:4766-4767, 4758-4761`）；启动后第一拍即跑 overdue 检查而非等 60s（L4781 注释）。ticker 自己的心跳/成功时刻写成 marker 文件，供 `hermes cron status` 判断"写心跳的进程还活着吗"（`cron/jobs.py:1252-1341`）。

**进 tick 的四道闸**（`cron/scheduler_tick.py:33-101`）：
1. `retirement.work()`：进程退役（更新/关闭）期间不再收新 tick（L38-41）；
2. **陈旧代码让位**：进程下的 checkout 被更新过且更新的 gateway 持 runtime 锁时，本进程主动抛 `CronTickYielded` 让位（L83-86）——防止新旧代码混跑；
3. **tick 文件锁**：同 home 一次只允许一个 tick（gateway ticker vs 独立 daemon vs 手动 tick 互斥，L44-57）；store 不可写则标记 degraded 只扫 MCP 孤儿；
4. **ESTOP / can_dispatch**：`hermes pause` 或 gateway 在排空既有工作时跳过分发（L94-101）；ESTOP 只跳过新分发、绝不触碰在跑的任务（L93-97）。

**due 扫描即自愈**（`_get_due_jobs_locked`，`cron/jobs.py:3319-3363`）：单条记录畸形只跳过自己（L3338-3351）；`_evaluate_due_job`（`cron/jobs.py:3236-3316`）按固定顺序处理——先恢复缺失的 next_run_at、修时区漂移、重挂 error 态的 recurring，然后才判断到期；落后超过一个周期+宽限的积压**快进折叠成一次**（防 burst，`cron/jobs.py:2877-2885` 与 `_fast_forward_missed_recurring` L3117）。

**预推进 + pending_slot（at-most-once 的关键）**：recurring job 在分发**前**就在锁内推进 next_run_at（`cron/scheduler_tick.py:140-143`）——崩溃重放不会每次重启都重跑。但这留下"已推进、未认领"的丢失窗口，`pending_slot` 盖章记录该瞬间与盖章者；认领时清除； owner 死亡或租约过期后恢复一次并走正常迟到/快进策略，绝不 N 次重放（`cron/occurrences.py:58-103`，#107485）。

**一次 tick 的时间线（recurring job 为例）**：
1. T+0 ticker 醒来，过四道闸后 `get_due_jobs()` 在 flock 内扫描；
2. `_evaluate_due_job` 判定 09:00 的 occurrence 到期，**同一把锁里**写回：新的 next_run_at（09:30）、`last_dispatch` 迟到分类、`pending_slot` 盖章（`cron/jobs.py:3296-3315`）；
3. 返回 due 快照，`_submit_with_guard` 注册 running、建 `claimed` 账本行（`cron/scheduler.py:4311-4337`）；
4. 线程池 worker 醒来，`claim_job_for_fire` 赢得 CAS、清 pending_slot、绑定 occurrence 身份（`cron/scheduler.py:4244-4262`）；
5. `run_job` 起 agent 会话；心跳线程每 60s 续 fire_claim（`cron/constants.py:8`），账本 `progress_at` 由 stamper 刷新；
6. 结束：`mark_job_run`（写状态/清 claim/重算 next_run_at）+ `finish_execution`（终态一次写）；投递经队列异步出门。

**认领与执行**：`_submit_with_guard` 先进程内注册 running 集合去重，再写 `create_execution`（账本行，状态 `claimed`，`cron/executions.py:213-233`），才投进线程池（`cron/scheduler.py:4266-4362`）；worker 真正开跑前才 `claim_job_for_fire`（`cron/scheduler.py:4241-4263`）。该 claim 是跨进程 CAS：在 per-job fence + jobs flock 下，若存在比 TTL（300s，`cron/constants.py:9`）新的 fire_claim 则失败；成功则盖 `fire_claim={at,by:machine_id:uuid}`、清 pending_slot、对 recurring 再推进 next_run_at，让陈旧重投递无法重复触发（`cron/jobs.py:2736-2802`）。occurrence 身份只绑"调度 tick 的火"：手动 run-now 不盖 occurrence，避免把未来的槽位记成已完成（`cron/jobs.py:2761-2780`）。one-shot 另有 `claim_dispatch` 在副作用前消费 `repeat.completed`，保证至多 times 次（`cron/scheduler.py:3331-3342`）。

**记录**：run 结束统一走 `mark_job_run`（带 `expected_fire_owner` 的乐观锁——owner 换人时丢弃陈旧完成，`cron/jobs.py:2484-2491`）+ `finish_execution`（账本终态只许写一次，`cron/executions.py:312-335`）。

### 2.3 job 执行 = 一次独立 agent 会话

- `run_job` 为每次触发新建 `cron_{job_id}_{时间戳}` 会话 ID 与全新 AIAgent（`cron/scheduler.py:2553-2581`），结束即 teardown——不 teardown 会在每 tick 泄漏 fd 直到 EMFILE（`cron/scheduler.py:2645-2657`）。**无跨运行的对话记忆**；连续性靠 `context_from`：把该 job 最近一次非静默输出（上限 8000 字符）以"上次跑到哪、别重复汇报"的数据块注入 prompt（`cron/scheduler_prompt.py:1-6`，`_SELF_CONTEXT_INTRO`/`_MAX_CONTEXT_CHARS` 同文件 L50-55 区域）。
- 进 agent 前有一串 gate（`_prepare_job_prompt`，`cron/scheduler.py:2224-2311`）：config.yaml 解析失败拒绝运行（防把账单算到用户没选的 provider）、空 payload 直接暂停、**脚本 wake gate**——预跑 `script` 字段的脚本，末行输出 `{"wakeAgent": false}` 则本次完全跳过 LLM（`cron/scheduler.py:2262-2281`）；组装后的 prompt 过注入扫描器，命中则本次不跑并写 BLOCKED 文档（L2288-2306，见 08 篇）。
- **监控门**：`monitor_script`/`monitor_url` 先跑，输出哈希与上次相同则 agent 不跑；**新快照在 agent 运行前先落盘**——检测时刻即状态边界，agent 失败不会对同一内容反复告警（`cron/monitor.py:126-171`）。
- 无人值守但有 liveness 双边缘（`cron/scheduler_liveness.py:1-10`）：watchdog 用 `threading.Event.wait`（内核超时，卡死的事件循环关不掉它）轮询 agent 空闲时长，超过限值就中断（L25-49，#94285）；同时 `ExecutionProgressStamper` 在空闲短时刷新账本 `progress_at`，让"按最后活跃时间"算的 stale 回收既能收走卡死的 worker、又不误收多小时的健康任务（L52-77）。fire_claim 本身由独立线程心跳续期（`cron/scheduler.py:2688-2770`）。
- 运行身份用 ContextVar 绑定（`cron/execution_identity.py:1-12`）：`ctx.current_cron_execution()` 只在赢下 `claimed→running` CAS 后绑定，随 `contextvars.copy_context()` 跟到工作线程，委派子 agent 读到 None——模型输出无法触碰它（工具子进程不共享解释器）。
- **运行产物三层落盘**：① 输出文档——prompt 与响应各带长度框架头写入 job 输出目录（`_run_doc_header`/`_RESPONSE_FRAME` 拼装，`cron/scheduler.py:2597-2603`；`save_job_output` 在 `cron/jobs.py:3403`）；② fire 审计行——`_FireAudit` 在 agent 构造成功后创建，成功/失败各写一行，**agent 存在之前的失败不产生审计行**（`cron/scheduler.py:2502-2524, 2582, 2605, 2626-2628`）；③ 会话收尾——`_finalize_cron_session` 在 finally 中落 session 状态（`cron/scheduler.py:2642-2644`），session_db 以 `_BoundedCronSessionDB` 包装限制暴露面（L1455-1464）。job 可声明 `workdir`，run scope 把 cwd 设成任务目录（`cron/scheduler.py:2564-2566, 1506`）。
- **模型降级链**：job 可钉住路由，未钉时走配置的 fallback 链；降级生效时在最终回复前 prepend 一条告知性 notice 随报告一起投递（`cron/scheduler.py:2588-2592`，链定义在 `_job_fallback_chain` L97-108）。
- 秘密作用域：投递适配器要解析凭证，`_install_fire_secret_scope` 让 `get_secret()` 在作用域外 fail closed——作用域必须横跨"构建→运行→投递→记账"全程，finally 里复位（`cron/scheduler.py:3326-3330, 3508-3517`）。

### 2.4 交付：at-most-once 的三级队列

- 主通道 `deliveries.db`（sqlite）：重启安全的 cron worker 在 gateway cgroup 外跑，无法持有平台适配器对象，于是把最终发送排队；gateway 逐行认领。**认领后 gateway 死亡 → 标 `unknown`，永不重试**：宁可丢一条投递，不冒重复发送的险（模块 docstring，`cron/delivery_queue.py:1-8`）。状态机 `pending→delivering→delivered/failed/unknown/suppressed`（`cron/delivery_queue.py:110-136`）；`recover_abandoned` 用进程 UUID + pid + 启动时间三重判活围栏死 owner（L282-315）。
- 终态行把 payload 清空只留有界元数据 + tombstone（`cron/delivery_queue.py:39-74`）——投递队列不存历史消息内容。
- Bot Chat（本地 TUI/Desktop 回合）是伪平台 `bot-chat[:profile]`（`cron/scheduler_delivery.py:1016-1023`）：不能即时投就落 `bot_chat_pending/*.json` 延迟投递，drain 时先标记 claimed 再执行，错误不授权重放（`cron/bot_chat_delivery.py:86-144`）。gateway 每拍 drain 队列且用文件 watch 让新入队的发送即刻出门（`gateway/run.py:4758-4761, 4791-4799`）。
- 目标解析：`deliver` 是逗号分隔的平台列表，`all` 展开为配置了 home chat 的平台，`local`（默认空值）= 不投递；失败通知可走独立的 `failure_deliver` 通道（`cron/scheduler_delivery.py:1079-1109`，`_normalize_deliver_value` L1000-1009）。路由 token 在**触发时**解析——job 的寿命比平台接线长（`cron/scheduler_delivery.py:1012-1015`）。
- 进入配额保持时只发**一次**带窗口结束时间的失败提醒，此后 provider 不可用期间不再告警（`cron/quota_hold.py:153-163`）。
- 静默协议：agent 回复 `[SILENT]`（整条/首行/末行）抑制投递——"没值得报的"是一种一等输出（`cron/scheduler.py:526, 546-568`）；空回复则记软失败，不冒充 ok（`cron/scheduler.py:3422-3425`）。

### 2.5 失败处理：重试、退避、incident、用户通知

- **模型不可达重跑**（借鉴 Claude Cowork）：仅当失败是瞬时网络/DNS 且 agent 零次 API 调用（什么都没执行、没花钱）时，recurring job 按 5/15/30 分钟阶梯自动重跑，跑完放弃等自然周期；任何"够到模型"的运行（无论成败）重置阶梯（`cron/unreachable_retry.py:1-18, 33, 135-166`）。重跑不计入 `repeat.completed`（`ladder_rung`，`cron/jobs.py:2399-2423`）。
- **配额窗口保持**：provider 明示"X 秒后重开"（429 retry-after）时，把 job 停到窗口结束后而不是每个 tick 都撞一次；稀疏 cron 可在窗口结束做一次 off-lattice 的恢复火，其余 coalesce 到第一个合法时刻（`cron/quota_hold.py:112-150`）。
- **incident 台账**：executions.db 里的 `cron_incidents` 表按 `(job_id, 归一化错误签名)` 去重——签名把"603s"这类时长掩成 `#s`（同因失败不因数字抖动分裂），sha256 前 12 位；生命周期 `detected→alerted→resolved/closed`：closed 是操作者 ack 后对该签名永久静音，resolved 是恢复后又复发会重新拉响（`cron/incidents.py:1-10, 32, 131-134, 156-197, 242-257`）。调度器侧按 `cron.failure_repeat_alert_hours` 抑制重复告警（`cron/scheduler.py:328-355`），job 恢复即 resolve 全部 open incident（L379-389）。
- **失败连击提醒**：recurring job 连败 `cron.failure_nudge_threshold`（默认 3）次，失败通知里追加"值得审查 / 怎么暂停"的操作建议（`cron/scheduler.py:133-158`）。投递失败不算进 streak，单独记 sticky 的 `last_delivery_error`（`cron/jobs.py:2381-2391`）。
- **崩溃与中断路径的记账纪律**：`_run_one_job_body` 的兜底 except 捕获 `BaseException` 而非 Exception——否则 Ctrl-C/CancelledError 逃逸后，one-shot 的 dispatch 已消费但 last_run_at 永远写不上，job 卡死到 TTL（`cron/scheduler.py:3453-3464`）。记账前先区分：transport 取消 → 记 interrupted；fire claim 换主 → 陈旧 worker 不许在替补运行的账上写失败、也不许补发失败告警（L3472-3496）；投递已成功后才丢失所有权 → 保留已投递运行的终态（L3427-3445，#105861）。死 owner 留下的 `claimed`/`running` 行由恢复路径定案为"结果未知"，错误文案直说"是否产生过副作用无从知晓"（`cron/executions.py:338-346`）。

### 2.6 ownership/liveness 解决什么并发问题

一台主机一个 gateway 进程复用所有 profile，还可能同时存在 CLI、独立 daemon、外部 provider、重启安全的外部 worker。Hermes 把"谁拥有这次触发"拆成四层各管一件事：

1. **tick 锁**（flock）：同一 home 同时只有一个 tick 在扫（`cron/scheduler_tick.py:44-57`）；
2. **fire_claim**（jobs.json 里的 CAS 租约，TTL 300s + 心跳）：N 个副本抢同一次触发时恰好一个赢（`cron/jobs.py:2736-2802`）；
3. **进程内 running 集合**：上一 tick 的运行还没完就跳过本 tick 的重入（`cron/scheduler.py:4311-4314`）；
4. **账本判活**：claim 的 `by=host:pid[:token]`，本机可验证 pid 死亡才允许提前缩短 TTL，其余一律 fail-safe（`cron/scheduler_ownership.py:151-165`）；"这个进程是否为某 home 的 ticker"与"另一个活的 gateway 是否正在 tick 它"是两个独立谓词，**探针失败一律回答"否"——所有权只接受确证，不接受猜测**（`cron/scheduler_ownership.py:1-16, 79-148`）。

### 2.7 suggestions 与 blueprints：agent 建议你装定时任务

- **suggestion** 是"可直接运行的 job spec"，用户一键接受（真正调 `create_job`）或驳回（按 `dedup_key` 永久闩死不再提）；四个来源：`catalog`（内置 starters）/`blueprint`（skill 里的 blueprint 块）/`usage`（自省复盘）/`integration`（连接账号）；pending 上限 5 条防刷屏；**没有任何自动创建路径——consent-first**（`cron/suggestions.py:1-8, 37-39, 167-190`）。catalog 种子可反复重播：已被驳回/接受的 dedup key 由 store 层跳过，重播幂等（`cron/suggestion_catalog.py:118-143`）。接受路径上若 job 已落库但注册失败，suggestion 仍标记 accepted——重试不允许造出第二份拷贝（`cron/suggestions.py:184-188`）。
- **catalog** 是内置清单：每日简报、重要邮件监控（轮询收件箱→LLM 评分紧急度→只推送过阈值者，无事回 `[SILENT]`）、周回顾、工作日启动提醒（`cron/suggestion_catalog.py:37-115`）——注意"重要邮件监控"在 Hermes 里就是一个带分类脚本的定时任务，与 Memoria 的邮件分拣同构。
- **blueprint** 是表单化模板：槽位 schema（time/enum/text/weekdays），`schedule_template` 钉死周期、只留人类该填的部分；`fill_blueprint` 校验成 `create_job` kwargs——**没有第二套 job 引擎**（`cron/blueprint_catalog.py:1-6`）。enum 槽可声明非 strict，此时 options 只是建议、真校验留给下游调度器（如 deliver 槽，合法值取决于用户接了哪些平台，L45-59）。
- 防自毁：create_job 全路径拒绝包含 `hermes gateway restart/stop` 等 lifecycle 命令的 job spec（命令形锚定，不误伤散文），否则 job 杀掉自己的宿主进程→supervisor 复活→auto-resume 重跑→SIGTERM 循环（`cron/lifecycle_guard.py:1-9`）。

### 2.8 存储与生命周期卫生

- **completed one-shot 留检 7 天**：终态记录保留在 jobs.json 供 `cronjob list` 检视，`_sweep_completed_oneshots` 按 last_run_at 过期清除；解析不出 last_run_at 的记录**宁可保留也不猜进删除**（`cron/jobs.py:2817-2819, 2838-2845`）。
- job 输出目录有 keep-N 裁剪（`_cron_output_keep`/`_prune_job_output`，`cron/jobs.py:3376-3403`）；suggestions 的 accepted 记录在确认 job 存在后清除、dismissed 保留以维持 dedup 闩（`cron/suggestions.py:193-202`）。
- 磁盘不可写是**一等状态**而非异常：tick 锁创建失败、due-scan 修复写不回、advance 失败各有 `store_health.note_unwritable` 降级路径，每分钟最多重探一次（`cron/scheduler_tick.py:44-57, 131-135`，`cron/jobs.py:3353-3358`）。

## 3. 设计决策取舍

- **jobs.json（flock+全量重写）而不是 DB 存调度状态**：换来崩溃后 grep 可读、外部工具可编辑，代价是每次 claim/load/save 全量 I/O；代码里到处为这条代价做补偿（如 dispatch 失败路径特意跳过 `clear_run_claim` 的全量读，`cron/scheduler.py:4272-4294`）。
- **预推进 + pending_slot** 是 at-most-once 与不丢触发的折中：先推进防重放，再盖章防丢失，恢复只走一次（`cron/occurrences.py:58-69`）。
- **投递 unknown 而非重试**：把"可能已送达"定义为不可重放状态，宁可漏报不重复（`cron/delivery_queue.py:1-8`）——与执行侧"零 API 调用才重试"是同一条原则的两面：**只有能证明无副作用的东西才允许自动重跑**（`cron/unreachable_retry.py:7-13`）。
- **每个错误分支都长注释带 issue 号**：4437 行的 scheduler.py 里大量逻辑是给具体事故编号打的补丁（#58720 teardown 顺序、#10200 EMFILE、#38758 one-shot 预消费……），健壮性是事故驱动的累积而非先验设计。
- **croniter 是硬依赖但可缺失**：缺失时 recurring job 算不出 next_run_at，选择置 `state=error` 并保留 enabled + 可恢复语义，而不是禁用或标记完成——调度器宁可显式生病也不假死（`cron/jobs.py:1197-1203, 2434-2445, 563-576`）。
- **并行度按 profile 分池**：`max_parallel_jobs` 是 per-profile 配置，单一进程全局池会被先 tick 的 profile 定型并强加给其他 profile，所以池按 home key 分开并随 profile 退出回收（`cron/scheduler.py:1205-1228`，`cron/scheduler_ownership.py:36-63`）。
- **agent 自报失败是一等语义**：agent 可以在子委派失败后主动声明本 run 语义失败（失败标记），走既有失败路径而非伪造健康结果（`cron/scheduler.py:3394-3401`）——承认"模型比调度器更早知道成败"。
- **occurrence 身份只在调度 tick 绑定**：手动 fire 不绑身份，宁可让手动运行不进 dedup 账，也不能把未来槽位标成已完成（一次真实事故：19:53 的手动运行吃掉了次日 19:00 的 occurrence，`cron/jobs.py:2761-2780`）——dedup 的粒度选择本身就是设计决策。
- **60s tick + 到期判断下推**：ticker 固定节拍，真正的"漏跑追赶/快进/时区修复"都在 due 扫描内做，让外部 provider 也能复用同一套扫描（`gateway/run.py:4747-4748`）。

## 4. 设计规范清单（可直接照抄）

1. job 定义与调度状态分字段管理；合并外部定义只覆盖 authored 字段。
2. 状态优先派生（enabled+pause 标记），只有 terminal 态落盘；半暂停记录必须自愈或拒绝触发。
3. 分发前推进 next_run_at + pending_slot 盖章：崩溃窗口既不重放也不丢失。
4. 跨进程触发 = 带 TTL 的 CAS fire_claim + 独立心跳线程 + owner 换人时丢弃陈旧完成。
5. 执行账本三态 `claimed→running→completed/failed`，终态一次写入，unstarted 有专门的 settle 路径。
6. 积压折叠：错过 N 个周期只补跑一次，绝不 burst。
7. 结果投递走持久队列，claim 后死亡标 unknown 永不重试；终态行清空 payload。
8. `[SILENT]` 是一等的"无需打扰"；空回复记软失败。
9. 失败去重靠归一化签名（时长掩码），incident 有 detected/alerted/resolved/closed 四态，恢复自动 resolve、ack 永久静音。
10. 自动重试只给"可证明零副作用"的失败；配额窗口停火而非撞墙。
11. agent 自建议的自动化必须 consent-first，dedup_key 闩死驳回项。
12. 禁止 job 杀宿主：lifecycle 命令在 create 时拒绝。
13. 磁盘不可写走 degraded 降级而非崩溃；每个写路径都有 `note_unwritable` 记账。
14. 保留终态记录供检视但有过期清扫；解析不出的记录宁可保留不猜删。

## 5. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| pending_slot 盖章 + 一次性恢复 | 预推进后进程死亡，occurrence 永久丢失（#107485） |
| fire_claim TTL+心跳+owner 令牌 | 崩溃后 lease 死锁；陈旧 runner 覆盖新 runner 的账 |
| due 扫描内联自愈（时区/缺字段/error 态） | jobs.json 手编/降级后调度静默失效 |
| wake gate `{"wakeAgent": false}` | 便宜脚本能省掉 99% 的无谓 LLM 调用 |
| monitor 哈希先落盘再跑 agent | agent 失败导致同一变更反复告警 |
| 交付 unknown 围栏 | gateway 死后重复发送或假确认 |
| incident 签名去重 + repeat_alert_hours | 同一错误每次运行都 ping 操作者 |
| 零 API 调用才走重试阶梯 | mid-run 副作用被加倍 |
| ContextVar 运行身份 + 委派子上下文隔离 | 并行 job 串身份；模型输出伪造运行身份 |
| 建议去重键 + pending 上限 | agent 变成建议刷屏机 |
| 陈旧代码让位（tick 前 yield gate） | 运行中热更新后新旧代码混跑、双 ticker 抢火 |
| agent teardown 硬上界 + 延迟到投递后 | 每 tick 泄漏 fd 直到 EMFILE（#10200/#58720） |
| one-shot 预消费 dispatch（claim_dispatch） | tick 中途死亡后 one-shot 无限重放（#38758） |
| 交付 tombstone + 终态行清 payload | 投递历史无限累积且残留消息内容 |
| 重复告警节流（failure_repeat_alert_hours） | 长期故障变成每周期一次的噪音 ping |
| recovered 自动 resolve / ack 永久静音 | 修好后台账永远显示几十条 open incident |
| context_from 封顶 8000 字符 | 上一轮输出无限膨胀进下一轮 prompt |
| failure_deliver: local 结构性退出 | 失败通知打不该打的渠道；无此字段则跟随 deliver |
| 失败分类放在 except 内且自身永不抛出 | 分类失败掩盖真实错误 |

## 6. 对 Memoria（LangGraph + RAG）的可迁移结论

适合搬：
- **"重要邮件监控"这个 catalog 形态**（`cron/suggestion_catalog.py:57-80`）：轮询→按规则评分→只推送过阈值→无事静默，正好套在 Memoria 手动触发的邮件分拣上；Memoria 的 LangGraph 编排可直接扮演 wake gate + monitor 的角色（脚本门在后端、LLM 在前）。
- **incident 签名台账**（归一化+时长掩码+四态）：Memoria 的邮件归档审批一旦异步化，失败通知必须有 dedup，否则每个收件人失败都弹一次 interrupt。
- **[SILENT] 协议 + 空回复软失败**：给"无事发生"一个机器可判的输出约定，通知管道才敢做抑制。
- **投递队列的 unknown 围栏**：若 Memoria 未来把"归档确认通知"推到 IM，同一套 claim/unknown 语义直接可用。
- **wake gate / monitor 门**：先跑便宜的确定性检查（新邮件数、向量库增量）再决定是否唤醒 LLM，对单人系统是纯省钱的。
- **落地次序建议**：第一步只搬"一次触发=一次会话 + context_from 连续性 + 输出落盘审计"这一条主链路（Memoria 用 LangGraph checkpoint 已有半套）；第二阶段才考虑通知队列与 incident；多副本所有权永远不需要。

不适合搬：
- **多进程/多副本所有权全套**（fire_claim、tick 锁、runtime 锁让位、profile 复用）：Memoria 单人单实例、LangGraph 单进程，file-lock CAS 军备竞赛是 Hermes 多宿主形态的税，搬来是纯复杂度。
- **jobs.json 全量重写 + 手编容错**：Memoria 用 Postgres/sqlite 持久化即可，不需要为 JSON 文件补丁那一层归一化。
- **外部 worker/PM 依赖引导**（`cron/worker_bootstrap.py`）：这是 Hermes 自更新架构的伴生复杂度。

## 7. 证据索引

| 结论 | 文件 |
|---|---|
| authored 字段/定义合并 | `cron/job_definition.py`（L13-18、L21-45） |
| 状态派生/runnable/terminal/error 可恢复 | `cron/jobs.py`（L536-576） |
| run 收口/repeat/error 不静默禁用 | `cron/jobs.py`（L2362-2517，#16265 注释 L2434-2445） |
| next_run 计算与 DST fold | `cron/jobs.py`（L1178-1242） |
| tick 四道闸/预推进/并行池 | `cron/scheduler_tick.py`（L33-182）、`gateway/run.py`（L4744-4816） |
| due 扫描与自愈/快进/半暂停自禁 | `cron/jobs.py`（L2877-2885、L3117、L3236-3363） |
| pending_slot 与 occurrence 去重 | `cron/occurrences.py`（L22-103） |
| fire_claim CAS/occurrence 绑定规则 | `cron/jobs.py`（L2722-2802）、`cron/constants.py`（L9-17） |
| 一次 tick 的时间线 | `cron/jobs.py`（L3296-3315）、`cron/scheduler.py`（L4244-4337、L2688-2770） |
| 分发守卫/账本创建 | `cron/scheduler.py`（L4241-4362）、`cron/executions.py`（L213-335） |
| 一次会话执行/prompt gate/wake gate/注入阻断 | `cron/scheduler.py`（L2224-2311、L2526-2657） |
| 运行产物（输出文档/审计/会话收尾/workdir） | `cron/scheduler.py`（L1455-1464、L2502-2524、L2597-2603、L2642-2644）、`cron/jobs.py`（L3403） |
| 秘密作用域横跨投递 | `cron/scheduler.py`（L3326-3330、L3508-3517） |
| context_from 连续性 | `cron/scheduler_prompt.py`（L1-6、L50-55 区域） |
| watchdog/进度戳 | `cron/scheduler_liveness.py`（L25-77） |
| 运行身份 ContextVar | `cron/execution_identity.py`（L1-12） |
| 交付队列/unknown 围栏/裁剪 | `cron/delivery_queue.py`（L1-8、L39-74、L110-136、L228-315） |
| bot-chat 延迟投递 | `cron/bot_chat_delivery.py`（L1-5、L86-144）、`cron/scheduler_delivery.py`（L1016-1023） |
| deliver/failure_deliver 目标解析 | `cron/scheduler_delivery.py`（L1000-1009、L1079-1109） |
| [SILENT]/空回复软失败/agent 自报失败 | `cron/scheduler.py`（L526-568、L3397-3401、L3422-3425） |
| 重试阶梯/配额保持 | `cron/unreachable_retry.py`（L1-33、L135-166）、`cron/quota_hold.py`（L38、L112-150） |
| incident 台账 | `cron/incidents.py`（L1-10、L32、L131-134、L156-257） |
| 崩溃/中断记账纪律（BaseException/owner 换主/未知结局文案） | `cron/scheduler.py`（L3427-3507）、`cron/executions.py`（L338-346） |
| per-profile 并行池 | `cron/scheduler.py`（L1205-1228）、`cron/scheduler_ownership.py`（L36-63） |
| 存储卫生/降级路径 | `cron/jobs.py`（L2817-2845、L3376-3403、L3353-3358）、`cron/scheduler_tick.py`（L44-57、L131-135）、`cron/suggestions.py`（L193-202） |
| ticker 心跳 marker/misfire sweep | `cron/jobs.py`（L1252-1341）、`gateway/run.py`（L4766-4767、L4781） |
| 失败连击提醒/告警节流 | `cron/scheduler.py`（L133-158、L328-355） |
| ownership 谓词与判活 | `cron/scheduler_ownership.py`（L1-16、L79-165） |
| 建议系统/目录/蓝图 | `cron/suggestions.py`（L1-8、L37-39、L167-190）、`cron/suggestion_catalog.py`（L37-115）、`cron/blueprint_catalog.py`（L1-6） |
| monitor 门 | `cron/monitor.py`（L126-171） |
| lifecycle 自毁防护 | `cron/lifecycle_guard.py`（L1-9） |
| 外部 worker 引导 | `cron/worker_bootstrap.py`（L1-35） |
| 路由 token 触发时解析/bot-chat 不进 all | `cron/scheduler_delivery.py`（L1012-1023） |
| suggestion 接受幂等/catalog 重播 | `cron/suggestions.py`（L184-188）、`cron/suggestion_catalog.py`（L118-143） |
