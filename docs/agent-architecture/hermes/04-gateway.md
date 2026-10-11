# Hermes Agent 核心设计 · 04 Gateway

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时（MIT，Python 3.14 + Node）
> HEAD：`97a9ae8e`（main，2026-10-11 本地浅克隆）；本文维度：**Gateway 多平台消息网关**（`gateway/` 130+ 文件约 6.4 万行，另有 `plugins/platforms/` 平台插件）
> 路径相对仓库根目录；每条结论标注 `文件:行号` 实读证据；README 转述不进正文；未定位到的机制明确标注。

---

## 1. 定位与全景

Gateway 是一个**独立的常驻进程**，把 Telegram/Discord/Slack/WhatsApp/Signal/Email 等 IM 上的对话桥接到**进程内**的 agent 循环；同一个进程里还并存另外两种"网关形态"（TUI 的 stdio JSON-RPC 后端、ACP 适配器）。全链路：

```
Telegram / Discord / Slack / WhatsApp / Signal / webhook / api_server …
   │  平台 SDK / HTTP（plugins/platforms/<name>/adapter.py 或 gateway/platforms/<name>.py）
   ▼
BasePlatformAdapter.handle_message()          gateway/platforms/base.py:4038
   │  _active_sessions 守卫（每会话一个 asyncio.Event，base.py:1989）
   │  忙时：bypass 命令直通 / 其余排队进 _pending_messages（base.py:4080, run_busy.py:105）
   ▼  set_message_handler 绑定的回调（run_adapters.py:1355）
GatewayInboundMixin._handle_message           gateway/run_inbound.py:1285
   │  身份准入 → estop 门 → 运行中快速道 → 空闲 slash 分发 → 会话槽位哨兵
   ▼
GatewayTurnMixin._handle_message_with_agent   gateway/run_turn.py:2144
   ▼
_run_agent → _run_agent_inner（4265）
   │  TurnRunner.run_sync 提交进无界线程池（turn_executor.py:9；run.py:4281）
   ▼  agent.run_conversation（agent/conversation_loop.py:1709）——同进程直调，无队列无 HTTP
AIAgent（每 delta 回调 stream_delta_callback，agent/chat_completion_helpers.py:2880）
   │  queue.Queue → GatewayStreamConsumer.run() 异步任务（stream_consumer.py:146,544）
   ▼
adapter.send / edit_message / send_draft / send_stream_frame（逐平台实现）
```

- `GatewayRunner` 由 **19 个 mixin** 拼成（run_inbound/run_turn/run_busy/slash_*/shutdown…），类注释一句话："manages adapter lifecycles, routes messages to/from the agent"（`gateway/run.py:3353-3369`）。
- 平台适配器两种来源：内置（`gateway/platforms/`：whatsapp_cloud、signal、weixin、qqbot、yuanbao、bluebubbles、webhook、api_server…）与插件（`plugins/platforms/`：telegram、discord、irc…），通过 `platform_registry.PlatformEntry` 自注册，网关按注册表实例化、无 if/elif 链（`gateway/platform_registry.py:1-15,29`）。

## 2. 进程模型与通信

- **入口**：`pyproject.toml:557-560` 定义 `hermes`（hermes_cli.main）、`hermes-agent`、`hermes-acp` 三个 console script；`hermes gateway start` 走 `cli.py:1591` 直接 `from gateway.run import start_gateway`；`gateway/run.py:5948` 的 `main()` 是网关自己的 CLI 入口，最后 `asyncio.run(start_gateway(config))`（`run.py:6027`）。
- **单进程单事件循环 + 每轮一线程**。`start_gateway`（`run.py:5750`）做主机附着/重复实例守卫/信号处理后常驻；turn 体重为**同步函数** `TurnRunner.run_sync`，经 `_UnboundedThreadExecutor` 提交——注释明说 `ThreadPoolExecutor(max_workers=None)` 并非无界（min(32, cpu+4) 仍是隐形队列），所以自实现"一线程一项、无线程队列"（`gateway/turn_executor.py:9-17`）；executor 在 `run.py:4281 _get_executor` 取用。
- **通信方式＝同进程直调 + 回调**。网关持有 `AIAgent`，在 executor 线程里直接调 `agent.run_conversation(...)`（`gateway/run_turn_runner.py:1724`；签名 `agent/conversation_loop.py:1709`）；没有跨进程队列。唯一的"跨线程桥"是两个 `queue.Queue`：模型 delta 从 agent 工作线程 `on_delta()` 入队，网关事件循环里的 `GatewayStreamConsumer.run()` 出队并限频编辑平台消息（`gateway/stream_consumer.py:1-7,146,527-534,544`）。
- **会话密钥走 contextvars 而非 os.environ**：`run_sync` docstring 专门解释——os.environ 是进程全局，两个 Discord 线程并发会互相覆盖，工具线程回退读 env 会把审批提示路由错会话（#24100）（`gateway/run_turn_runner.py:1884-1906`）。
- 另外两个网关形态对照：`tui_gateway/` 是 TUI/Desktop 的 **stdio JSON-RPC** 后端（Node Ink 渲染层 ↔ Python 会话/工具层，server→client 请求会阻塞 agent 线程等同一 `srq-<n>` id 的响应帧，`tui_gateway/AGENTS.md`）；`acp_adapter/` 是 **ACP 协议适配器**（stdout 保留给 ACP JSON-RPC，`acp_adapter/entry.py:1-10`）。三者共享同一套 agent，只是传输不同。
- **适配器接线只有四个回调**：runner 启动时对每个 adapter `set_message_handler` / `set_busy_session_handler` / `set_authorization_check` / `set_platform_event_handler`（`gateway/run_adapters.py:1355-1366`）——adapter 不知道 GatewayRunner 的任何细节，只持有这四个注入的 callable。
- 崩溃兜底进 main()：进程先注册身份台账 + Windows job-object、再武装启动看门狗（先于配置加载与 DB 打开，防"活 PID 僵尸"），退出用 `os._exit` 绕过 Py_FinalizeEx 对卡死非守护线程的 join（#53107）（`gateway/run.py:5967-5976,6029-6038,6039-6082`）。Windows 无 `add_signal_handler`，另有轮询 planned-stop 标记文件的线程兜住 `hermes gateway stop` 的排水（#33778，`run.py:5864+`）。

## 3. 消息全链路（以一条 Telegram 消息为例）

**第 1 跳：适配器接收与守卫。** `TelegramAdapter` 继承 `BasePlatformAdapter`（`plugins/platforms/telegram/adapter.py:514`）。`handle_message()` 先打身份（`_drop_unresolved`，base.py:4070），再查 `_active_sessions` 守卫：无守卫→同步安装守卫后 `create_task(_process_message_background(...))`（`base.py:3955-3956,4086`）；有守卫→`_handle_message_while_active`：`/stop`、`/new`、`/approve`、`/deny` 等 bypass 命令**内联直派**（排队会泄漏成用户文本或死锁），其余文本入 `_pending_messages`（`base.py:4080-4100`；设计动机见 `gateway/AGENTS.md` "两条消息守卫"节）。文本还会先做防抖合并（连打几条合成一条，`base.py:2573-2613`）。

**第 2 跳：网关准入管线。** `_handle_message`（`gateway/run_inbound.py:1285`）依次：

- `_hm_admit_event` 身份准入（拒绝路径含未授权通知 owner 与配对码回复，`run_inbound.py:31` 导入的 `pairing_code_reply`）；
- estop 暂停门（1317）与挂起回复拦截（1321）；
- 运行中快速道 `_hm_handle_running_session_message`（1329）；
- 空闲 slash 分发（1332）与 Telegram topic 大厅提醒（1338-1343）；
- 外部排水期拒绝新轮（1345-1348）；
- **领取会话槽位**：塞 `_AGENT_PENDING_SENTINEL` 哨兵，防止在多个 await 之间第二条消息绕过"已在运行"检查拉起重复 agent（1352-1358 注释原文）；
- `run_post_admission_hook` 插件消费（fail-open，`run_inbound_consumer.py:1-8`）；
- `_handle_message_with_agent`（1372）。

**第 3 跳：运行中消息的处置**（`run_inbound.py:693-740`）：`busy_input_mode` 三态——默认 `interrupt`（打断当前 agent，`run.py:3362` 类默认）；`queue` 进 FIFO；`steer` 注入进行中的轮次。打断本身有优先级：支持活动转向的 runtime 优先把**纯文本更正** redirect 进进行中的轮（保留已显示上下文），语音/媒体或旧 runtime 才走 `running_agent.interrupt(text)`——打断文本经 `_pending_messages` 传递给下一轮，绝不双份缓冲（会无界增长）（`run_inbound.py:668-692`）。两个自动降级：agent 有活跃子代理时打断会级联杀死 delegate_task（#30170）、压缩进行中打断会在旧 parent 上起新轮（#56391），都改为排队（731-740）。哨兵期间的 `/stop` 强制清槽解锁（711-714）。

**第 4 跳：turn 准备与执行。** `_handle_message_with_agent` 解析会话、准备历史，调 `_run_agent`（`run_turn.py:2197-2210`）→ `_run_agent_inner`（4265）：构建 `TurnContext`（`gateway/turn_context.py:14-102`，全轮共享的可变状态包，`message` 是唯一可重绑字段，43 行）、spawn 六个伴随任务——进度排水、工具日志、流消费者轮询、agent 追踪、**中断监视（每 200ms 轮询 adapter 的 pending interrupt，另设 backup check 防监视任务本身死亡漏中断）**、长运行"还在干活"通知（4311-4330；`run_turn.py:3335-3364,3365-3386`）——然后 `_run_agent_start_turn_worker` 把 `turn_runner.run_sync` 提进线程池（4334；`run_turn.py:3416`）。`run_sync` 内部解析模型/凭证→建流消费者→`_wire_turn_agent_callbacks` 把 `stream_delta_callback` 绑到 agent（`run_turn_runner.py:1963-1977,1268`）→ `_load_turn_history` → `agent.run_conversation`。轮次结果带 `run_still_current` 代数检查：轮被 `/new`/`/stop` 取代后旧结果直接丢弃（`run_turn.py:2231-2232`）。

**第 5 跳：响应成形与投递。** 回到事件循环后 `_hmwa_shape_agent_response` 清洗、附 footer（流式已送达正文时 footer 改为尾随发送，`run_turn.py:2224-2237`）、持久化 transcript，最后 `_hmwa_deliver_turn_response`（2259）。投递走 adapter：Telegram `send()` 在 per-chat 锁内先试 Bot API 10.1 rich 快路径，否则 `truncate_message` 按 4096 UTF-16 单位分块（`plugins/platforms/telegram/adapter.py:3618-3674`）；per-chat 发送锁保证同一聊天的两条分块回复不交错（#114396，`adapter.py:3649-3651`）。`finally` 里恢复一次性模型覆盖、清持久 turn 标记、释放槽位与 turn 租约（`run_inbound.py:1388-1403`）。

**排队链的递归续跑**：turn 结束时 `_run_agent_drain_pending` 从 `adapter._pending_messages` 取出队首（`run_turn.py:3628,3677-3684`），有则先 `_run_agent_deliver_first_response`（3736）——流式对账确认正文已上屏就只补发媒体，未确认才补发文本；发成功的文本置 `result["already_sent"]=True`，防止后续完成路径再发一遍（#81052，`run_turn.py:3787-3796`）——然后 `_run_agent_queued_followup` **递归调 `_run_agent`** 跑下一条（3811+），并先清掉中断事件防自打断死循环（3830 附近）。`/queue` 的 FIFO 溢出链在 `run_busy.py:105-160`：槽位占着就追加进 `SessionState.conversation.queued_events`，槽位空了逐个 promote；忙窗口异常结束会把孤儿溢出项在下次新事件时按到达序"救回"（#28503）。

## 4. 并发与 turn 租约

三层机制解决"多平台/多聊天同时来消息"：

```
消息 M2 到达（M1 的 turn 仍在跑）
 ├─ 闸门1  adapter._active_sessions[skey] 存在？      base.py:1989,4074
 │          → bypass 命令内联直派，其余进 _pending_messages   base.py:4080
 ├─ 闸门2  runner._is_session_running(skey)？          run_inbound.py:1329
 │          → busy_input_mode: interrupt|queue|steer    run_inbound.py:703-729
 └─ 闸门3  SessionTurnLease（按解析后 session_id）      turn_lease.py:98
           → 等不到锁 fail-closed，回"另一轮正在运行"   run_inbound.py:1373-1382
```

1. **适配器层 per-session 守卫**：`_active_sessions: dict[str, asyncio.Event]`（`base.py:1989`），同一 session 键的第二条消息进排队/打断分支；带陈旧锁自愈（owner task 已退出则清守卫，防"Interrupting..."卡死，`base.py:3924-3942`）。
2. **网关层会话槽位 + run generation**：`_claim_active_session_slot` 塞哨兵领槽，每轮领一个 `_run_generation`，finally 释放时带代数——旧轮的解栈不能释放新一轮的槽（`run_inbound.py:1350-1358,1398-1403`）。
3. **TurnLease（`gateway/turn_lease.py`）**：解决 routing key 与 session_id **多对一**的问题——`switch_session()` 让两个聊天键映射同一 transcript，两键交替 flush 会造成 `user;user` 楔子（docstring 1-10 行）。`SessionTurnLeaseRegistry` 按**解析后的 session_id** 发 asyncio 租约：transcript 加载前 acquire、dispatch 层 finally release、身份校验的幂等 release（165-179）、等待超时**fail-closed** 抛 `TurnLeaseTimeoutError`（调用方回"另一轮正在运行"，不进入未串行化区域；32-39,122-137；`run_inbound.py:1373-1382`）。压缩导致的中途换 session id 用 `rebind` 把**同一个**租约别名到新 id（139-163）。上限 512 条、只逐出空闲项（21,89-96）。默认等待 5s（25）。

多平台同时来消息的实际排队顺序：不同 session 互不阻塞（每轮独占线程）；同一 session 串行为"当前轮 → pending 队列"。`/queue` 显式 FIFO 在 `run_busy.py:105-137`（溢出回吐 `_pending_messages`）。

## 5. 平台适配与身份

- **统一基类 + 每平台一个 adapter**：`BasePlatformAdapter` 抽象 `send/edit_message/delete_message`（`base.py:2735-2782`），并声明能力位：`splits_long_messages`、`SUPPORTS_MESSAGE_EDITING`、`supports_async_delivery`、`draft_stream_is_message`（Slack 原生流）、`REQUIRES_EDIT_FINALIZE`（钉钉 AI 卡片类需要显式 finalize 编辑）等（`base.py:2070-2089,2736`；Telegram 侧 `adapter.py:543-545`）。平台差异收敛在 adapter 内（如 Telegram 的 MarkdownV2+UTF-16 计长 `adapter.py:520,577-579`；Discord 在 `plugins/platforms/discord/adapter.py`）。
- **注册表而非硬编码**：`PlatformEntry` 含 name/factory/被动依赖探针 `check_fn`/主动安装器 `ensure_deps_fn`——两者拆开是因为合并写过会出"status 显示顺便 pip install"和"永不懒安装"两种事故（#79812 注释，`platform_registry.py:44-58`）。插件经 `PluginContext.register_platform()` 注册（1-15）。
- **身份单一解析点**：`session_identity.resolve_identity`（`gateway/session_identity.py:191`）对每条入站事件**一次性**回答"哪个 bot 收的/谁能准入/在哪跑"，冻结成 `RoutingIdentity`（:42）钉在 source 上；intake（收到事件的 bot）与 delivery（回答的 bot）分离（`gateway/authz_mixin.py:254,285`），重启恢复的会话经 `restore_identity`（:151）重新钉身份，杜绝"按启发式回落到默认 bot"。
- **whatsapp_identity.py 的独有任务**：WhatsApp 桥会把同一个人暴露成 LID（`999@lid`）或手机号 JID（`1555@s.whatsapp.net`）——授权和会话键若各自解析必然漂移。它提供规范化（剥 `:`/`@`/`+`，:29-32）、经桥的 `lid-mapping-*.json` 传递展开别名集（:69-99，含路径穿越防御 :82）、取**最短别名**为规范身份（:102-112）。
- **未授权者走配对码而非静态白名单**：未知用户收到一次性 8 位配对码（32 字符无歧义字母表、1 小时过期、每平台最多 3 个待审、10 分钟限速、5 次失败锁定、数据文件 chmod 0600、码不进日志），owner 在 CLI 侧批准——OWASP/NIST SP 800-63-4 参数直接写在 docstring（`gateway/pairing.py:1-10,33-37`）。WhatsApp 别名展开被复用进配对身份（:22）。
- **typing/状态呈现也是基类能力**：`set_status_text`（`base.py:1926`）供 Slack 类"文字 typing"平台使用；turn 结束统一 `_hmwa_stop_typing_for_turn`（`run_turn.py:2229`）。
- 会话键/传输列持久化：`sessions.transport_profile` 列记录"哪个 bot 可向此会话投递"（`gateway/AGENTS.md` Profile scope 节；DB 侧 mixin `hermes_state_gateway.py:1-3`——路由索引、peers、孤儿、心跳、handoff 都在 SessionDB 上）。

## 6. 流式输出的平台化

`GatewayStreamConsumer`（`gateway/stream_consumer.py:99`）是核心：**同步 agent 回调 → 队列 → 异步任务限频编辑一条平台消息**。三 transports：edit（逐次 editMessageText）、draft（Telegram 草稿动画）、native（企业微信 msgtype stream，流即消息）。默认关闭：`StreamingConfig.enabled: bool = False`（`gateway/config.py:489`），编辑间隔 0.8s、缓冲阈值 24 码点、光标" ▉"（:481-483）。

- **一个 tick 的生命周期**（`stream_consumer.py:653-691,574-608`）：

```
on_delta() 线程入队 ──► queue.Queue ──► run() 异步任务（事件循环侧）
                                          │ _drain_queue()：文本折叠进 _accumulated，
                                          │ 控制哨兵（_DONE/_NEW_SEGMENT/_FLUSH/边界）单独成 tick
                                          ▼
                              _should_edit(tick)？──否──► sleep(0.05) 继续排水
                                          │是
                              _seal_overflow_heads() → _push_update(cursor 后缀)
                                          ▼
                       got_done? → _finalize_turn → return（flags 留给网关对账）
```

- **生产侧**：agent 线程 `on_delta(text)` 入队；`None` 表示工具边界→`on_segment_break()` finalize 当前段、下一段成为新消息（527-534）。`finish(final_text)` 把**权威 final_response**（含流后增补）排进队，drain 循环采纳为 finalize 载荷（536-542,693-710）——只有流过东西的消费者才采纳，避免抢走网关的 final 发送权。
- **节流与打断**：`_should_edit` 按间隔/阈值放行，flood 退避期间只有服务器要求的间隔能触发（729-750）；"NO"→"NO_REPLY"这类沉默标记未成形前推迟编辑（749-750）；`_run_still_current()` 为 False（`/new`、`/stop`）直接弃流（551-553）。每 tick `drain → seal 溢出头 → push`，循环尾 `sleep(0.05)`（554-610）。
- **transport 三选一在 run() 开头解析**：native 优先（声明了 native 的 adapter 不能 edit），seed 空帧失败→降级 edit；draft 再退一档，bump draft_id 让下一段动画成新预览（630-651；解析器在 `stream_consumer_transport.py:127,151`）。编辑退避上限 30s（Telegram retry_after 语义），更长交给 strike 计数进 fallback（`stream_consumer_transport.py:17`）。`fresh_final_after_seconds`（Telegram 专属移植自 openclaw#72038）让长回复的 final 改发新消息使平台时间戳反映完成时刻，并把所有旧预览删掉（`stream_consumer.py:67-72,153`）。
- **长文本分片**：首次发送即溢出→`_split_first_send` 密封头块、尾部留作活预览（752-797）；已发消息溢出→`_seal_overflow_heads` 循环切头（805-822）。真正切块由 `truncate_message` 完成：**跨块保代码围栏**（前块闭合、后块以同语言标签重开）、`(1/3)` 指示符、不切进行中的行内反引号（`base.py:4873-4933`）。
- **think 隐藏**：`StreamThinkFilterMixin` 对流式 delta 做渐进 `<think>` 抑制，与 CLI 共享 `agent/think_scrubber.py` 的标签原语，保证中间显示与最终清洗一致；块边界判定防止正文提到标签误触发（`stream_consumer_think.py:1-19,24-50`）。
- **TTS 语音**：`StreamingTTSConsumer`（`gateway/streaming_tts_consumer.py`）与文本流**并联 tee**（delta 同时喂两个 sink，`run_turn_runner.py:968-976`）：句级切块入 256 容量队列（:46），循环任务逐句合成 PCM 写给 adapter，首个 PCM 块到达才开 handle（:203）；结局三态 completed/partial/aborted，"发过声就抑制整文件 TTS 重放"（:117-123）。
- **sticker**：入站贴纸经视觉工具描述一次，按 `file_unique_id` 缓存在 `~/.hermes/sticker_cache.json`（原子写+锁），再以"[用户发了贴纸…它画的是…]"注入文本（`gateway/sticker_cache.py:1-5,60-97`）。
- **审批边界也过流**：`close_for_approval_prompt()` 经 `_APPROVAL_BOUNDARY` 哨兵让 run() 先 finalize 当前流、发送占位"⏸ 等待审批中..."，审批后按 reopen 决定降级或重开流（`stream_consumer.py:57,382-405,471-501`）。
- **防重复发送是头号不变量**：`delivered_final_matches` 三态对账（True/False/None，330-358），全量对账过的 finalize 不重发；"`gateway/AGENTS.md` 流式投递契约"用四条从线上事故提炼的规则（帧前缀稳定、消费者声明 final、interim 发送打 `_interim_send` 标记、以编辑而非新发对账）固化这套语义（interim 元数据工厂 `run.py:486`）。
- **类型化流事件走 adapter 渲染**：`GatewayEventDispatcher.dispatch` 把 `MessageChunk/MessageStop/Commentary/ToolCallChunk/LongToolHint/GatewayNotice` 路由给 adapter 格式化，工具行入同一条进度队列避免与网关排水竞争（`gateway/stream_dispatch.py:1-14,66-84`）；外层 `try/except` 保证"呈现永不炸进 agent 工作线程"（:62-66）。

## 7. slash 命令与权限

- **注册**：命令定义在 `hermes_cli/commands.py`（`resolve_command` :398）；网关侧**没有 if/elif 链**，两张表按命名约定反射出 handler：`_PLAIN_COMMANDS`（运行中也可用：status/approve/deny/pause/…）与 `_IDLE_COMMANDS`（仅空闲：model/sessions/rollback/…），`_command_handler_table(names)` 把 `x` 映射到 `_handle_x_command`（别名 bg→background，`gateway/run_busy.py:910-929`）。文档纪律写在 `gateway/AGENTS.md`："No `if canonical == ...` chains"。
- **分发**：空闲路径 `_hm_dispatch_idle_commands`（`run_inbound.py:1233`）→ `_hm_resolve_command`（:811）→ `pre_command` 观察者与 `command:<canonical>` 拦截器 hook（可 deny/handled/rewrite，766-810，运行中路径故意不 fire——慢插件不得妨碍操作员逃生舱）。运行中路径 `_dispatch_busy_slash_command`：先找 mid-run 变体 `_busy_<key>_command`（/queue 的入队、/stop 的打断），再按 `busy_policy == "dispatch"` 走普通 handler，否则拒绝文本（`run_busy.py:965-998`）。
- **权限（`gateway/slash_access.py`）**：在 `allow_from` 之外的**第二根轴**——同一个人允许聊天，但哪些 slash 命令能跑由它管。每作用域（dm/group，镜像 allow_from 的两份配置键，:24-27）两个名单：`allow_admin_from`（全量命令）与 `user_allowed_commands`（非管理员额外可跑的命令）；未配 admin 名单＝该作用域不启用门控（向后兼容），启用后无人名单则只剩 `{"help","whoami"}` 只读底线（:19,52-58）。空白 chat_type 歧义时**解析到受门控的一侧**，绝不落入无门控作用域（:124-130）。multiplex 下按**收到消息的 bot 所属 profile** 的配置判定，查不到 fail-closed（:137-158）。调用点在 slash 分发处（`run_busy.py:1120-1124`、`slash_commands.py:324-326`）。
- **与 agent 的关系**：slash handler 是网关自身的状态操作（/model、/sessions、/approve…），直接操作 GatewayRunner 与 SessionDB，不产生 agent 轮次；聊天正文才进 `_handle_message_with_agent`。例外如 `/goal`、`/loop` 有 mid-run 白名单动词（`run_busy.py:962-965`）。最大的一个 mixin 是会话类：/new、/resume、/sessions、/branch、/title、/save、/undo、/retry、/topic、/compress 全部只改写 transcript 与会话路由（`gateway/slash_commands_session.py:1-4`）。
- **Telegram 侧的两个体验补丁**：BotCommand 菜单有 100/scope 上限，inline 模式（`@bot <query>`）把全部命令/技能做成可搜索选择器，点选即以用户身份走正常命令路径（`plugins/platforms/telegram/inline_picker.py:1-7`）；断线窗口内 PTB 已 ack 但无法派发的事件持有在队列里，重连后重派并移交给替换 adapter（`telegram_held_inbound.py:1-2`）。

## 8. 可靠性机制

- **wake.py（后台完成唤醒）**：后台进程/委托完成时唤醒既有会话。push 型 adapter 走合成 `MessageEvent(internal=True)`，且要求**具体接纳回执**（`event._gateway_accepted` 未置 True 即抛 `WakeNotAccepted`——handler 返回 None 不算接纳，:79-88）；无状态 api_server 则带 `X-Hermes-Session-Id` 自 POST `/v1/chat/completions`（600s 超时、429 退避重试 2/5/10s，:22-27,185-256）。委托完成**绝不**自 POST 成新 `role=user` 轮——那会越过悬置的人工确认门（#85957），改为持久化一条 delivery 行（:142-182）。失败一律 raise 让上游回卷游标重试，不静默丢事件（:9-10）。
- **shutdown_watchdog.py（冻结循环兜底）**：systemd 只能复活死进程，救不了冻结的事件循环。四件套：OS 线程关停看门狗（超 `drain_timeout+60s` grace 即 dump 栈 + `os._exit`）、心跳文件（supervisor 区分"进程活着"与"循环冻着"）、生命周期线程看门狗（3 次持续 miss 判冻死）、self-rescheduling floor timer 保证 selector 等待有界（docstring :1-8；常量 :33-43）。
- **流消费者 fallback（`stream_consumer_fallback.py`）**：渐进编辑被打爆/不支持后转入"续块新消息"模式，`_send_new_chunk` 串链 reply_to；配合 `_MAX_FLOOD_STRIKES = 3`（`stream_consumer.py:104`）与 Telegram 侧 `FALLBACK_ON_FINAL_EDIT_FLOOD`（`adapter.py:544`）。
- **投递台账（`delivery_ledger.py`）**：final 响应的四态义务账（pending→attempting→delivered/failed，含 abandoned），进程在 finalize 与平台 ACK 之间崩溃时按语义恢复：pending 直接重发；attempting 平台**可能**已收到，重发须带恢复标记——"从不静默重发一次语义不明的发送"（docstring :1-8）。配合 turn marker handoff：投递成功的轮把持久标记交给生命周期，接收方只在台账见行后清除（`run_inbound.py:1391-1394`）。
- **警示通知（`warning_notifications.py`）**：引擎诊断与助手回复分家——`DiagnosticText` 标记类 + `render_notification` 只在呈现 sink 处按 `suppress_warning_notifications` 决定是否渲染（:6-15,65-75）；诊断类唤醒可静音整轮呈现，但**人类内容永不静音**（:49-62）。
- **进程级**：`status.py`（2151 行）管 PID 文件、runtime lock、按 (scope, 进程启动时间指纹) 的 scoped lock（防两 profile 共用一个 bot token 凭证）、`gateway_state.json` 运行时状态与 restart-storm 检测（:56-121,203,307-315,462-505）。状态写盘是**单写者后台线程**（`_RuntimeStatusWriter` 带代数等待/flush，:56-121），事件循环级：`start_gateway` 安装**只吞已知瞬时网络错误**的 loop 异常处理器——一个未处理的 telegram.TimedOut 会杀掉整个进程带走所有会话（#31066/#31110，`run.py:5838-5842`）。
- **持久化侧的网关状态**：`hermes_state_gateway.py` 是 SessionDB 的网关 mixin——路由索引、peers、孤儿恢复、心跳、handoff；压缩世系用递归 CTE 找出"resume 必须留在同一路由 peer 上"的整条链（:15-27）。Telegram DM 的 topic 模式（每 DM 一个话题开关、intro/pinned 消息 id）持久化在 `telegram_dm_topic_mode` 表，主键 (profile_name, chat_id)（`hermes_state_telegram.py:21-36`）。
- **审批（网关侧呈现）**：agent 线程把待审批命令入队后**阻塞**在 `threading.Event`（`tools/approval_gateway_wait.py:1-31`），1s 切片轮询以喂活动心跳（防止用户还在打字时网关不活动看门狗杀掉 agent，:38-66）；`/approve` 解最旧、`/approve all` 解全部，每个阻塞线程一个独立 entry（docstring :4-7）。`_approval_notify_sync` 在网关侧暂停 typing、关闭原生流、发按钮卡（`send_exec_approval`）或降级为 `/approve` 文本说明，命令先经 `_redact_approval_command` 去密（`run_turn_runner.py:1455-1530`；`run.py:577-590`）。按钮发送超时按"可能已送达"处理不补发（防重复卡），连接器 egress 拒绝则**不回落文本**（那正是要堵的泄漏）并 RAISE 拆除中央队列项（:1495-1530）。纯文本会话没有裸文本 yes/no 匹配——"conversational yes 不能执行危险命令"，只认 `/approve`/`/deny`（`run_inbound.py:1325-1326`）。

## 9. 设计规范清单（可直接照抄）

1. **网关与 agent 同进程直调**，跨线程只留两个 queue.Queue（delta 流、进度），无自定义 RPC。
2. **turn 体是同步函数跑在专用线程**；事件循环永远不被模型调用阻塞。
3. **会话键传播用 contextvars**，禁写 `os.environ["HERMES_SESSION_KEY"]`。
4. **身份一次解析、处处复用**（RoutingIdentity 钉在 source 上），intake/delivery adapter 分离，禁止按启发式回落默认 bot。
5. **每会话哨兵槽位 + run generation**，防"多个 await 之间的重复 agent"；释放带代数。
6. **transcript 串行化用租约**：按解析后 session_id、fail-closed 超时、身份校验幂等释放、压缩换 id 走 rebind。
7. **流式是可选层**（默认 off），stream 消费者对 final 发送只"对账"不"抢权"（delivered_final_matches 三态）。
8. **分块保围栏、保语言标签、带 (n/m) 指示符**；切分点避让行内代码。
9. **审批阻塞在工具线程，呈现走网关**；命令红action；超时≠失败、egress 拒绝≠可回落文本。
10. **一切投递有台账**；语义不明的发送宁可带恢复标记重发，不可静默。
11. **看门狗分层**：启动看门狗（先于一切副作用武装）→ 关停看门狗（OS 线程）→ 循环活性看门狗 → 心跳文件给 supervisor。
12. **命令表反射注册**（命名约定 + 两张白名单表），新增命令不碰分发代码。
13. **呈现层永不打断 agent**：流事件 dispatch、通知渲染、hook 回调全部 swallow 异常（`stream_dispatch.py:62-66`）。
14. **平台能力用类属性声明**（splits_long_messages / REQUIRES_EDIT_FINALIZE / supports_async_delivery…），上层按能力分支而非按平台名分支。

## 10. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| `_AGENT_PENDING_SENTINEL` 槽位哨兵 | 多个 await 之间第二条消息拉起重复 agent |
| TurnLease 按 session_id + rebind | 两个聊天键写同一 transcript 交错 flush（user;user 楔子） |
| busy_input_mode 三态 + 子代理/压缩自动降级 | 打断级联杀死 delegate_task / 压缩中打断分叉会话 |
| 流消费者 finish(final_text) 权威载荷 | 流后增补（footer 等）丢失或重复发送 |
| `_stream_ledger` 与 `_accumulated` 分离 | 溢出密封头块后对账载荷被截断误判 |
| thinking 过滤器与最终 scrubber 共享原语 | 中间显示与最终清洗不一致（think 泄漏到聊天） |
| 审批等待 1s 切片 + 活动心跳 | 用户考虑时 agent 被不活动看门狗误杀 |
| delivery ledger 四态 + 恢复标记 | 崩溃在 send 与 ACK 之间：静默丢或重复发 |
| check_fn/ensure_deps_fn 拆分 | status 显示顺便 pip install / 依赖永不懒安装 |
| 唤醒回执 `_gateway_accepted` | "handler 没抛异常"被误当"事件已被 agent 接纳" |
| os._exit 收尾 + 显式释放 PID/锁 | 卡死的非守护线程让网关半死不活，supervisor 无法重启 |
| 贴纸描述按 file_unique_id 落盘缓存 | 同一贴纸反复调用视觉模型 |
| held-inbound 队列移交替换 adapter | 断线窗口内已 ack 的事件被静默丢弃 |
| FIFO 溢出链 + 孤儿救回 | 忙窗口异常结束后排队消息消失或乱序 |
| per-chat 发送锁 + 出站 slot 预算 | 两条并发分块回复在平台上交错 |
| `_interim_send` 元数据标记 | 中途消息被误当 final 密封进活动流 |

## 11. 对 Memoria 的可迁移结论

**适合搬**：

- **"网关薄、agent 直调"的进程模型**：Memoria 若接 Telegram/邮件入口，不需要消息总线——一个进程内 adapter 回调直接进 LangGraph 的 `astream`，跨线程只用 `asyncio.Queue` 桥接流式 token。Hermes 证明 6 万行的复杂度都花在**平台怪癖与故障恢复**，不在传输层。
- **入口即会话槽位 + 代数**：Memoria 现在只有 Web UI，但"同一会话的第二个请求在图运行期间到达"是真实场景；`_AGENT_PENDING_SENTINEL`（claim-before-await）+ run generation 的释放语义可以直接映射为"会话级锁 + 请求代数"。
- **三层并发闸门的最小版**：Memoria 单用户也值得抄两条——(a) 每会话哨兵槽位（`_handle_message` 的 claim-before-await，防重复拉起图执行）；(b) TurnLease 的 fail-closed 思想（等不到锁就回"上一轮还在跑"，绝不并发写同一会话历史——对应 Memoria 红线"删文档必须删掉它的全部向量"这类不可并发操作）。
- **审批映射到 MailView 人工确认**：Hermes 的模式是"agent 线程阻塞在 `threading.Event` + 网关发卡片/文本 + `/approve` 携带 request_id 解锁 + 命令先脱敏 + 超时≠失败"。Memoria 的"验证码/交易邮件归档必须人工确认"可做成同一状态机：归档动作先持久化 pending 行（相当于 delivery ledger 的 pending 态），Web UI/IM 推确认卡，确认后才执行，崩溃恢复按行语义走——**确认状态落库而非留在对话框里**。直接对应的映射：

```
Hermes                                Memoria
tools/approval_gateway_wait           归档确认等待（LangGraph interrupt 或等价 Event）
/approve <request_id>                 MailView 的"确认归档"按钮（带同一 request_id）
_pending_approvals + 台账             确认状态落 state 存储，重启可恢复
 Redact 后再展示                      邮件正文/主题在确认卡里不携带可执行链接
 超时≠失败（卡保持 armed）             确认卡过期不等于"已拒绝归档"，需显式撤回
```
- **流式对账而非抢权**：Web UI 用 SSE 天然免分片，但"部分输出已展示 + 最终结果不同"的重复问题同构；`delivered_final_matches` 的"记录用户实际看到的文本再对账"可以直接搬到前端渲染层。
- **警示与回复分家**：`warning_notifications.py` 的 DiagnosticText 标记 + 只在呈现 sink 判断静音，适合 Memoria 的"检索失败/索引落后"类通知不冒充助手回复。
- **唤醒要回执、失败要上抛**：Memoria 的邮件分类批处理完成后若要"推一条结果"给用户，`wake.py` 的两条纪律直接可用——adapter 必须显式接纳（回执位），投递失败必须 raise 让调用方重试而非静默丢（对应红线"回答必须带来源引用"之外的另一半：**结果必须可证明送达**）。

**不适合搬**：

- multiplex_profiles 多 profile 密钥作用域全套（Memoria 单用户单 home，用不上）；hosted rooms/kanban/relay 子系统同理。
- 逐平台的洪控/UTF-16 计长/rich 消息降级——只有真接 Telegram 时才需要，且可只在 adapter 一个文件内实现（Hermes 的 `ADDING_A_PLATFORM.md` 路线本身就是"平台怪癖关在 adapter 里"）。
- 四层看门狗全家族：Memoria 单进程 Web 服务用 systemd/进程管理器 + 一个心跳文件即可，循环活性看门狗属于常驻多适配器网关的问题域。

## 12. 证据索引

| 结论 | 文件:行 |
|---|---|
| 排队链递归 / 首响应补发 / FIFO | `gateway/run_turn.py:3628-3684,3736-3830`；`gateway/run_busy.py:105-160` |
| 适配器四回调接线 | `gateway/run_adapters.py:1355-1366` |
| 类型化流事件 dispatch | `gateway/stream_dispatch.py:1-14,62-84` |
| transport 解析 / 编辑退避上限 | `gateway/stream_consumer_transport.py:17,127,151`；`stream_consumer.py:630-651` |
| 配对码准入 | `gateway/pairing.py:1-10,33-37` |
| Telegram held-inbound / inline 命令选择器 | `plugins/platforms/telegram/telegram_held_inbound.py:1-2`；`inline_picker.py:1-7` |
| 会话类 slash mixin | `gateway/slash_commands_session.py:1-4` |
| 状态写盘单写者 / 压缩世系 CTE / topic 表 | `gateway/status.py:56-121`；`hermes_state_gateway.py:15-27`；`hermes_state_telegram.py:21-36` |
| Windows planned-stop 轮询线程 | `gateway/run.py:5864+` |
| 脱敏 / interim 元数据 | `gateway/run.py:569,577,486` |
| console scripts / 网关入口链 | `pyproject.toml:557-560`；`cli.py:1591`；`gateway/run.py:5948,6027` |
| start_gateway 主体 / loop 异常处理 / 信号 | `gateway/run.py:5750,5838-5842,5858-5864` |
| GatewayRunner 19 mixin / 会话状态 | `gateway/run.py:3353-3369,3410-3427` |
| 无界线程执行器 / executor 取用 | `gateway/turn_executor.py:9-17`；`gateway/run.py:4281,4249` |
| 入站管线与槽位哨兵 / finally 释放 | `gateway/run_inbound.py:1285-1403` |
| 运行中消息三态与降级 | `gateway/run_inbound.py:693-740` |
| turn 装配 / run_sync 步骤 | `gateway/run_turn.py:4265-4334`；`gateway/run_turn_runner.py:1963-1978` |
| stream_delta_callback 绑定 / agent 直调 | `gateway/run_turn_runner.py:1268,1724`；`agent/conversation_loop.py:1709` |
| 流消费者主循环 / 节流 / finalize / 对账 | `gateway/stream_consumer.py:544-610,729-750,849-904,330-358` |
| 分块保围栏 | `gateway/platforms/base.py:4873-4933` |
| Telegram send/rich/4096/utf16 | `plugins/platforms/telegram/adapter.py:514-545,577-579,3618-3674` |
| 流配置默认值 / 默认关闭 | `gateway/config.py:481-507`；`run_turn_runner.py:935-946` |
| TurnLease 全语义 | `gateway/turn_lease.py:1-25,98-179` |
| handle_message 守卫 / 忙时排队 | `gateway/platforms/base.py:1989,3955-3956,4038-4100` |
| 身份解析 / intake/delivery | `gateway/session_identity.py:42,151,191`；`gateway/authz_mixin.py:254,285` |
| WhatsApp 身份规范化 | `gateway/whatsapp_identity.py:29-112` |
| 命令表 / busy 分发 / 权限 | `gateway/run_busy.py:910-998,1120-1124`；`gateway/slash_access.py:19-158` |
| 审批阻塞 / 网关呈现 | `tools/approval_gateway_wait.py:1-66`；`gateway/run_turn_runner.py:1455-1530` |
| 流上审批边界 | `gateway/stream_consumer.py:57,382-405,471-501` |
| wake / 回执 / 委托不越审批门 | `gateway/wake.py:1-10,22-27,79-88,142-256` |
| 看门狗四件套 | `gateway/shutdown_watchdog.py:1-43,56-90` |
| 投递台账语义 | `gateway/delivery_ledger.py:1-8` |
| TTS 消费者 / 贴纸缓存 | `gateway/streaming_tts_consumer.py:1-8,46,117-123,203`；`gateway/sticker_cache.py:1-5,60-97` |
| think 过滤 / 围栏修补 / fallback | `gateway/stream_consumer_think.py:1-19`；`stream_consumer_fences.py:16-38`；`stream_consumer_fallback.py:1-11` |
| 警示分家 | `gateway/warning_notifications.py:6-15,49-75` |
| 状态库网关侧 / Telegram topic 表 | `hermes_state_gateway.py:1-3`；`hermes_state_telegram.py:21-36` |
| 平台注册表 / 插件清单 | `gateway/platform_registry.py:1-58`；`plugins/platforms/telegram/plugin.yaml:1-10` |
| TUI/ACP 形态 | `tui_gateway/AGENTS.md`（进程模型节）；`acp_adapter/entry.py:1-10` |
| main() 看门狗武装 / os._exit 收尾 | `gateway/run.py:5967-5976,6029-6082` |
