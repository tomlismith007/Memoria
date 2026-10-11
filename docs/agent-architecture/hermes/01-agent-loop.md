# Hermes Agent 核心设计 · 01 Agent 主循环

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时，MIT，Python 3.14 + Node
> HEAD：`97a9ae8e`（main，2026-10-11 本地浅克隆）
> 本文维度：**conversation_loop 主循环**——一个 turn 从用户输入到回复完成的完整生命线
> 约定：路径相对仓库根；行号证据为该 HEAD 实读；`turn_*` 系列是循环拆出的 phase 帮手（见 §2）。

---

## 1. 定位与全景

hermes 的循环不是"一个 while 里塞全部逻辑"，而是**一个瘦 while + 十余个纯函数 phase**：`conversation_loop.py` 只剩 1859 行，其中真正的循环体只有 ~60 行；每个阶段（迭代准备、请求组装、压缩门、API 重试、工具轮、收尾）各自是 `agent/turn_*.py` 里一个带 dataclass verdict 的函数，经 `_run_phase` 按 `inspect.signature` 反射回灌循环局部变量（`conversation_loop.py:1476-1494`）。`_LoopState` dataclass 集中声明全部循环局部变量，注释直言"新增输入/输出只需要加一个字段，别的什么都不用动"（`conversation_loop.py:1381-1388`）。

```
run_agent.main() ── AIAgent(...) ── agent.run_conversation(user_query)        run_agent.py:1536
                        │
        run_conversation (包装层：导出 turn 边界 / 失败 turn 收口)           conversation_loop.py:1709
                        │
        _run_conversation_turn                                                conversation_loop.py:1547
                        │
   ┌─ build_turn_context（每 turn 一次的 setup）                            turn_context.py:1029
   │     恢复 system prompt → 建会话行 → 追加用户行 → turn 开头压缩
   │     → 记忆预取 → api_content sidecar 盖章
   │
   └─ while api_call_count < max_iterations and iteration_budget.remaining > 0   :1648-1650
        ① begin_iteration     重定向/中断/预算检查，消费迭代额度            turn_iteration_prep.py:352
        ② prepare_iteration   /steer 排水、参数消毒、角色交替修复            turn_iteration_prep.py:144
        ③ assemble_api_request 组装请求副本+量压力                           turn_request_assembly.py:106
        ④ run_preflight_gate  压缩门（超阈值→压缩或退出）                    turn_preflight.py:57
        ⑤ _run_api_retry_loop  guard→build→call→check，错误恢复             conversation_loop.py:1497
        ⑥ apply_retry_restarts  消费 restart 标志（重发/继续/结束）           turn_iteration_prep.py:437
        ⑦ normalize_model_response                                            turn_response_intake.py
        ⑧ run_tool_round（有 tool_calls）──→ 工具执行、结果回灌、工具后压缩  turn_tool_round.py:46
             │ continue → 回到 ①
          finish_text_response（纯文本）──→ 空回复恢复/stop 门/续写       turn_final_response.py
             │ break → 跳出
        finalize_turn（预算摘要、收尾、落盘、微压缩、审查钩子）              turn_finalizer.py
```

- "继续调工具还是结束"由 ⑧ 分叉：`run_tool_round if s.assistant_message.tool_calls else finish_text_response`，前者 verdict=`continue` 进入下一迭代，后者 `break` 结束 turn（`conversation_loop.py:1684-1692`）。
- 顶层还有 codex_app_server 全托管模式与 scripted prelude（预编排工具调用）两条旁路（`conversation_loop.py:1642-1647`）。
- 包装层保证每个出口（成功/部分/中断/重试耗尽）都带 `{turn_id, current_turn_user_idx}` 边界戳，并负责失败 turn 的收口（`conversation_loop.py:1726-1732, 1813-1856`）。

## 2. 循环骨架

### 2.1 一个 turn 的生命周期

1. **进入**：`run_conversation` 先置 `agent._turn_user_intervened = False`，用 `native_turn_images` 上下文挂住本轮原生图片，再调 `_run_conversation_turn`（`conversation_loop.py:1737-1759`）。
2. **prologue**：`build_turn_context` 做"每 turn 一次"的全部 setup（详见 §3），任何异常之外还专门接 `PreflightCompressionTimedOut`——turn 开头的预压缩超时会以 typed 恢复契约结束 turn（`conversation_loop.py:1613-1614, 1361-1377`）。
3. **迭代条件**：`api_call_count < agent.max_iterations` 且 `iteration_budget.remaining > 0`，或 `_budget_grace_call`（预算耗尽后给一次无工具的宽限调用，`conversation_loop.py:1648-1650`；`turn_iteration_prep.py:408-411`）。
4. **退出条件全景**：
   - 用户/系统中断（`turn_iteration_prep.py:382-388`）；
   - 迭代预算耗尽（`turn_iteration_prep.py:412-416`）与 review fork 输入 token 预算（`turn_iteration_prep.py:392-400`）；
   - 重试全部失败无响应（`turn_iteration_prep.py:556-560`）；
   - redirect/rebuilt 重启次数超过 `max_retries`（防"无限退款"锁死 turn 租约，`turn_iteration_prep.py:469-484, 527-537`）；
   - 外层循环异常累计达 `_MAX_OUTER_LOOP_ERRORS = 8`（`conversation_loop.py:235-237`）；
   - 压缩耗尽/超时/延迟（§6）。
5. **预算耗尽兜底**：`finalize_turn` 里若还有 `max_iterations` 兜底位，会注入 `MAX_ITERATIONS_SUMMARY_REQUEST` 用户行、发起一次**无工具**的摘要请求（仅一次空摘要重试，`turn_finalizer.py:150-163`；`chat_completion_helpers.py:2309-2363`）。
6. **execute_code 退款**：一轮只有 `execute_code`（编程式工具调用）时退还迭代额度，"便宜的 RPC 式调用不该吃预算"（`turn_tool_round.py:197-200`）。

### 2.2 重试内层（每次 API 调用）

`_run_api_retry_loop` 是第二层 while（`conversation_loop.py:1497-1526`）：`nous_rate_limit_guard`（另一会话已记录 Nous 限流则先跳过/切 fallback）→ `build_api_request` → `perform_api_call` → `check_api_response`；`InterruptedError` 走 `handle_api_interrupt`，其余异常走 `handle_api_error`。两层循环通过 verdict 的 `action`（`return/break/continue/fallthrough`）通信——`"break"` 一律表示"离开重试循环回到外层"，语义固定（`conversation_loop.py:1498-1501`）。

### 2.3 每次迭代的缓存安全预备（prepare_iteration）

- /steer 指令作为**独立 user 行**插到最新 tool 行之后，绝不涂改已持久化的 tool 行（否则回放分叉、打碎 prompt cache）（`turn_iteration_prep.py:175-181`）；
- 迭代预算 90% 时在最新 tool 结果尾部一次性注入 system 通知（`turn_iteration_prep.py:48-99`）；
- 修复 role 交替（tool→user / user→user 尾巴会让严格 provider 返回空内容并空转），修复后用 `_reanchor` 重锚 `current_turn_user_idx`，防陈旧索引把本轮写入打到历史行上（`turn_iteration_prep.py:222-254`）。

## 3. 上下文组装与窗口管理

### 3.1 双层结构：持久 transcript + 每次 API 的发送副本

这是整个循环最重要的不变量。`messages` 是**持久事实**（会被 `_flush_messages_to_session_db` 落 SQLite），`api_messages` 是**发送副本**（结构性克隆 `_clone_message_for_send`，深层容器不共享，#80498 防止发送路径改写渗回持久历史，`conversation_loop.py:1018-1026`）。`build_api_messages`（`turn_context.py:1236-1344`）从 transcript 构造发送副本：

- 历史行回放 `api_content` sidecar——"上次实际发送的字节"存在行字典的私有字段上，回放时原样替换 content，**保证 prompt-cache 前缀跨 turn 字节级稳定**（`turn_context.py:1243-1249, 1298-1305`）；
- 弹掉 `api_content` 和全部持久化专用字段（严格 provider 拒绝未知键，`turn_context.py:1280-1282`）；
- system 消息 = 会话级缓存 prompt + 每调用级 `ephemeral_system_prompt`，**临时上下文只进 user 行和 ephemeral 区，永不进缓存的 system prompt**（`turn_context.py:1336-1343`）。

### 3.2 system prompt 的会话级冻结

`_restore_or_build_system_prompt`（`conversation_loop.py:741-880`）优先从 session DB 恢复上次逐字节存储的 prompt；`_stored_prompt_matches_runtime` 校验 Model/Provider/Session ID/cwd 四个身份行，cwd 变了算内容变化要重建，平台（TUI/桌面）变了**不算**——接口陈旧由 `stage_surface_switch_note` 在请求尾部补注，不动缓存前缀（`conversation_loop.py:883-910`）。工具数组同样按会话"冻结"（`_restore_pinned_tools`），注释算过账：工具数组序列化在 system prompt 之前，丢掉旧工具集会改写 token 0 起的前缀（`conversation_loop.py:800-810`）。

### 3.3 记忆与插件上下文的注入点

每 turn 开头 `_memory_turn_start_and_prefetch` 通知 memory provider 并一次性预取外部记忆（琐碎 prompt 跳过），文本经 `compose_user_api_content` 拼进**当前 user 行**（多模态 turn 则作为一个 text part），API 时注入、落盘时保留 sidecar（`turn_context.py:902-931, 1193-1203`）。落库走 `set_message_api_content` 双通道，防止先行落库的行丢掉 sidecar 导致重放分叉（`turn_context.py:933-976`）。

### 3.4 发送前的最后清洗与压强测量（assemble_api_request）

顺序是载荷敏感的（`turn_request_assembly.py:111-113`）：MoA 聚合上下文 → prefill 插入 → ContextEngine `select_context` 钩子（fail-open，异常时用原请求，`conversation_loop.py:1277-1324`）→ 消毒 → 逐出过期截图 → 丢弃 thinking-only 行/合并相邻 user 行 → **空白规范化 + tool-call 参数 JSON 规范化**（KV-cache 复用要求跨 turn 字节一致，`turn_request_assembly.py:188-193`）→ 孤立代理对剥离 → **最后才注入 cache_control 断点**（`turn_request_assembly.py:205-230`）。

窗口管理在两处做"压强"测量：优先用 usage 锚（provider 上次真实 `prompt_tokens` + 增量估计），退化为粗估并 **floor 在 provider 最后一次真实报数上**——非 ASCII 文本粗估会低估 ~2x，本地 provider 静默截断时全靠这个 floor 报警（`turn_request_assembly.py:266-281`；`conversation_loop.py:392-419`）。原生 Codex Responses 压缩会裁剪线上负载，故换 route 感知估算，否则"通用估计高估几个数量级，触发一次主请求根本不需要的 600 秒本地压缩"（`conversation_loop.py:83-109`）。

## 4. 工具结果回灌

### 4.1 执行顺序：先落盘、再执行（durability 不变量）

`run_tool_round`（`turn_tool_round.py:46-230`）的顺序是硬约束：校验/去重/限额 → 追加 assistant tool_calls 行 → **把 tool-call turn 写进 SessionDB** → 才执行工具。注释："resume 必须能看到已执行块——假如一个破坏性工具重启了 Hermes"（`turn_tool_round.py:53-56, 128-150`）。落库失败直接以 `session_persistence_failed` 结束 turn，绝不从纯进程内存状态跑工具。混合批次里无效调用也保留在 assistant 行（每个 call 都要有匹配 result），但换成错误文本的 tool 行（`turn_tool_round.py:101-125`）。

### 4.2 结果回灌：三层防溢出

1. **工具内自限**（各工具自己的 cap）；
2. **spillover 落盘**：`maybe_persist_tool_result` 超过工具阈值就把全文写到 `$HERMES_HOME/cache/spillover/{id}.txt`，上下文里只留 preview + 路径；写盘后**校验字节数再宣称"已保存"**，不完整就降级为有界内联截断（`tool_executor.py:1120`；`tools/tool_result_storage.py:293-334, 93-120`）；
3. **批次聚合预算**：`enforce_turn_budget` 按大小降序逐个把最大结果换落盘，直到本 turn 工具输出总量低于预算；多模态结果只 spill 最大的 text part，图片不动（`tool_executor.py:1194-1209`；`tool_result_storage.py:359-391`）。

每个 tool 结果 append 后立刻 `_flush_session_db_after_tool_progress`（`tool_executor.py:1141-1143`）；批次收尾顺序是"先预算执法、再注入 /steer"，保证 steer 标记不被截断替换（`tool_executor.py:1198-1207`）。压缩还会做确定性工具结果 prune：纯本地、无 LLM、保尾部，只在"收回量达标"时提交以让 cache break 保持偶发（`turn_preflight.py:376-395`）。

## 5. 取消/中断/错误恢复

### 5.1 中断如何进入循环

三个入口汇聚到同一套语义：

- **迭代边界**：`begin_iteration` 检查 `agent._interrupt_requested`，记 issuer（用户 vs 系统）后 break（`turn_iteration_prep.py:382-388`）。
- **流式路径**：`StreamingWaitMonitor` 的监控线程每 0.3s 轮询，发现中断即 abort（`chat_completion_stream_monitor.py:87-89`）。
- **非流式路径**：主线程 poll 循环发现 `_interrupt_requested`，先标 `cancelled=True` 再强关请求级 client（绝不关共享 client——SSL-BIO 中途释放 TLS FD 曾损坏无关 SQLite，#67142），worker 把传输错误当取消吞掉，主线程抛 `InterruptedError`（`chat_completion_nonstream.py:256-270`）。

`handle_api_interrupt`（`turn_api_call.py:170-210`）区分三种结局：pending redirect 存在 → 清中断位、保留纠偏文本、武装 restart（"用户在转向，不是在停止"）；已流出部分文本 → 以 assistant 行持久化（`display_metadata.interrupted`），循环字节（runaway repetition）则换成隐藏占位行防回放时重新播种循环；什么都没有 → `"Operation interrupted: waiting for model response (Ns elapsed)"`。

### 5.2 用户转向（redirect）与响应竞态

`_apply_active_turn_redirect` 把检查点（"Visible response before the interruption: ..."）+ 用户纠偏拼成 `api_content` sidecar 挂在 user 行上；屏幕上不显示的占位 assistant 行只用来保住角色交替，"脚手架字节绝不能落在里面，否则模型会复读它"（`conversation_loop.py:322-362`）。请求与 redirect 跨线程竞速：响应落地时发现 redirect 已插入 → 丢弃陈旧响应、武装重建（`turn_api_call.py:147-155`）。重启会退款（`api_call_count -= 1` + `iteration_budget.refund()`），但 `restart_count` 超过 `max_retries` 就停止退款结束 turn——"无限退款会把 turn 租约永远占住"（`turn_iteration_prep.py:467-490`）。

### 5.3 错误恢复流水线

`handle_api_error`（`turn_api_error.py:52-221`）是固定顺序的恢复链：解释器退出即弃（进程在退，重试/换凭证/fallback 全是徒劳）→ 分类前恢复 → `classify_api_error`（`turn_api_error.py:111-123`）→ 分类后恢复 → `route_classified_error` → `recover_from_overflow`（413 类 → 压缩）→ `settle_unrecovered_error`：

- 本地校验错误（ValueError/TypeError）不重试直接走 fallback/终态，但 `json.JSONDecodeError`、provider SSE 坏帧、SSL 错误属于瞬态要重试（`turn_api_error.py:224-237`）；
- Copilot 过期凭证伪装成 400：先单次重换凭证重试同一 provider（`turn_api_error.py:311-328`）；
- 非重试错误 → 激活 fallback 链并以 `"break"` 退出重试循环——"这是承重结构：restart 处理器会对 fallback 的上下文窗口重跑 preflight"（`turn_api_error.py:334-354`）；
- `max_retries` 耗尽 → 主传输恢复（重建 client 一次）→ fallback → 有界自动恢复阶梯（`turn_recovery_autorecover`）→ typed 终态结果（`turn_api_error.py:363-404`）；
- 否则计算退避并**可中断睡眠**（退避中来了 redirect/中断也能正确转身，`turn_api_error.py:406-426`）。

重试在模型请求层只有 SDK 内建重试和这里的外层重试；工具层没有重试，失败即成为错误文本的 tool 行回灌。

### 5.4 部分完成消息与失败收口

turn 结束前 `finalize_turn` 是所有恢复 `break` 的唯一咽喉：空终态时若流已送出文本则以流文本为准（"空白尾巴不许冻结"，`turn_finalizer.py:225-237`）；"已交付的 final_response ⇒ transcript 里有 assistant 行"在该收口强制成立（`turn_finalizer.py:240-276`）。失败 turn 若让 durable 尾巴停在 user 行，`_close_durable_failed_turn` 会补一条 Hermes 自署的 assistant 边界行（错误文本强制脱敏后才可入持久层，`conversation_loop.py:1813-1856, 1772-1810`）；上下文压强类失败被显式排除——"往已超限的会话里追加行是 #1630 增长循环"。

## 6. 压缩的触发与衔接

### 6.1 四个触发点

| 触发点 | 位置 | 压强来源 |
|---|---|---|
| turn 开头（idle + preflight） | `turn_context_compaction.py:129-141` | 预检估算 |
| 每次 API 前 preflight 门 | `turn_preflight.py:57` | 组装期测得的 `request_pressure_tokens` |
| 工具结果之后 post-tool | `turn_preflight.py:244` | usage 锚 → `last_prompt_tokens` → 粗估（`turn_preflight.py:282-295`） |
| turn 结束微压缩 | `turn_finalizer.py:287-328` | 滚动吸收最老未压缩交换 |

`should_compress` 判定极简：`tokens >= threshold_tokens` 且未被 block（`context_compressor.py:2994-3007`）；阈值 = `context_length × threshold_percent`（`context_compressor.py:2218-2224`）。block 理由三类：摘要失败 cooldown、结构化 no-op backoff、"provider 证实无效的压缩≥2 次"熔断（`context_compressor.py:3009-3026`）。

### 6.2 门的守门规则（turn_preflight.py:88-119）

资格 = `compression_enabled` 且消息数 >1 且 `compression_attempts < max_compression_attempts`（默认 3，`conversation_loop.py:1637`）。通过后：受管本地 llama.cpp 先尝试**扩窗口**（最后手段，扩成即退回本 pass，`turn_preflight.py:106-112`；`conversation_loop.py:452-473`），否则 `agent._compress_context(..., trigger="pre_api"|"post_tool")`（`turn_preflight.py:147-150, 315-317`）。压缩用的是 auxiliary_client 的独立模型链（"main provider → OpenRouter → Nous Portal → custom → native Anthropic"，`auxiliary_client.py:1-4`；`conversation_compression.py:875-881`），与主循环中断互相保护（`auxiliary_client.py:212-233`）。

### 6.3 压缩之后循环如何继续

- post-tool 压缩后经 `apply_retry_restarts` 的 `restart_with_compressed_messages` 分支：退款一次调用、重锚当前 user 行索引、`continue` 重进循环（`turn_iteration_prep.py:496-523`）；该重启也计入 `retry_count` 防止"压了但没压够"死循环（`turn_iteration_prep.py:499-501`）。
- 压缩若只留下一份"参考交接"（reference handoff）成为唯一活跃 user turn → 跳过模型调用，以固定短句结束（恢复的旧回复不许复读，`conversation_loop.py:177-206`）。
- 锁/瞬态阻塞导致的 no-op 是"临时延迟不是不可压缩证据"：退还 attempt、软结束为 `compression_deferred`，**绝不分类成 `compression_exhausted`**（那会触发网关清会话，`turn_preflight.py:318-345`；`conversation_loop.py:1089-1121`）。
- 耗尽兜底：重建后的请求仍超限 → `_provider_overflow_exhausted_result` fail-closed（`conversation_loop.py:1124-1149`）；压缩宿主超时 → 终态文案 + "无消息被丢弃，请 /new"（`conversation_loop.py:199-206`）。
- 预算再武装（anti-thrash 反面）：只有 provider 真实报数低于阈值才能把 `compression_attempts` 清零，粗估无权再武装（`conversation_loop.py:213-221`；`turn_usage.py:140-155`）。

## 7. 流式 vs 非流式

`_should_stream` 默认开（即使没有消费者——流是断流健康检查手段），ACP/外部进程 provider 关闭（`turn_api_call.py:46-64`）。两条路径共享 `check_api_response` 与错误链，差异全在看守方式：

- **流式**：`interruptible_streaming_api_call`（`chat_completion_helpers.py:3993-4006`）→ `StreamingWaitMonitor` 守护线程 30s 心跳续网关活性、60s 静默出"等待说明"、本地端点轮询模型加载进度替代假心跳、超过 stale 阈值杀流（`chat_completion_stream_monitor.py:59-89`）。
- **非流式**：`_NonStreamRequest` 把请求放 worker 线程，主线程 0.3s poll 四种 kill：TTFB（连上了但无首个事件）、progress（有生命周期事件无实质进展）、idle（事件停了）、stale（总超时）——kill 后让重试循环重连（`chat_completion_nonstream.py:272-319, 186-254`）；跨请求 stale 连击触发熔断（`chat_completion_helpers.py:553-575`）。
- 中断在两条路径都转成 `InterruptedError` 由 `handle_api_interrupt` 统一收口（§5.1）。

## 8. token/usage 计量在循环里的位置

每次成功响应后 `check_api_response` 调 `record_response_usage`（`turn_response_check.py:195`；`turn_usage.py:73-297`），一个函数折叠五处：compressor `update_from_response`（真实 usage 是压缩压强的权威，`turn_usage.py:126`）、usage 锚捕获（锚定显示与压缩计算，`turn_usage.py:134-138`）、会话级 token/成本计数器（`turn_usage.py:174-181`）、带 cache 命中率/写放大的日志行（`turn_usage.py:205-210`）、state.db 的 token-delta 队列（入队不即写，防冷库 UPDATE 拖住工具循环，`turn_usage.py:251-280`）。无 usage 的响应只保留"请求确实发生"的计数并消费挂起的压缩裁决（`turn_usage.py:85-99`）。压缩预算的再武装也发生在这里（§6.3）。

## 9. 设计规范清单（机器可检查）

1. **持久 transcript 与发送副本分离**：发送路径一切改写只落 `_clone_message_for_send` 克隆（`conversation_loop.py:1018-1026`）。
2. **历史行逐字节回放**：`api_content` sidecar 保证 prompt-cache 前缀跨 turn 稳定（`turn_context.py:1298-1305`）。
3. **system prompt 每会话构建一次并持久化**；临时内容只进 user 行/ephemeral 区（`turn_context.py:1336-1343`）。
4. **工具执行前先落盘 tool-call turn**；落库失败即终止 turn（`turn_tool_round.py:128-150`）。
5. **工具结果三层防溢出**：工具内 cap → spillover 落盘（写后校验）→ turn 聚合预算（`tool_result_storage.py:293-391`）。
6. **压缩压强优先真实 usage**：锚 > `last_prompt_tokens` > 粗估，粗估 floor 在 provider 真实报数上（`turn_preflight.py:282-295`）。
7. **压缩退款/延迟/耗尽三态分明**：临时阻塞绝不记为耗尽（`turn_preflight.py:318-345`）。
8. **所有重启退款有上限**（`restart_count` ≤ `max_retries`），防无限退款锁死 turn（`turn_iteration_prep.py:467-490`）。
9. **已交付的 final_response ⇒ assistant 行**在 finalize 单点强制（`turn_finalizer.py:240-276`）。
10. **中断保留已流出文本**，循环字节换隐藏占位防回放再播种（`turn_api_call.py:196-206`）。
11. **错误先分类再恢复**：本地校验错误不重试；瞬态传输错误必须重试；fallback 激活后必须重跑 preflight（`turn_api_error.py:334-354`）。
12. **usage 每次成功响应折叠五处**且无 usage 时也计数（`turn_usage.py:73-99`）。

## 10. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| phase 函数 + `_LoopState` 反射回灌 | 1859 行循环拆成可单测函数而不丢共享状态 |
| api_content sidecar / 字节级前缀稳定 | 注入临时上下文后 prompt cache 每轮 miss |
| persist-before-execute 工具轮 | 破坏性工具重启进程后 resume 丢已执行块 |
| spillover 落盘 + 写后校验 | 大工具输出撑爆上下文 / 半截文件谎称已保存 |
| 粗估 floor 在真实 usage 上 | CJK 等非 ASCII 低估 2x 导致静默截断死亡螺旋 |
| 压缩 attempt 预算 + 熔断 + 再武装门 | 压缩失败无限循环烧钱、粗估误触发 600s 本地压缩 |
| 重启退款有 restart_count 上限 | redirect/fallback 无限退款把 turn 租约占死 |
| 非流式 worker + 四种 watchdog kill | provider 半开连接挂死整个 turn |
| 退避期间可中断睡眠 | 重试等待吞掉用户转向/停止 |
| final_response ⇒ assistant 行收口 | 恢复路径返回文本但 transcript 尾是 tool 行，下一 turn 重放"未回答"积压 |
| 失败 turn 补 assistant 边界行 | 严格 provider 见 tool→user 序列返回空内容 |
| usage 锚 + token-delta 入队 | 冷 SQLite 写拖住工具循环；显示口径与压缩口径分离 |

## 11. 对 Memoria（LangGraph）的可迁移结论

### 适合搬

- **"压强优先真实 usage"**：`nodes.py:20-34` 的 `KEEP_RECENT_TOKENS + 1.5 chars/token` 粗估可以直接挂一个 post-llm hook 记录 provider 真实 `prompt_tokens` 作为 floor/锚（Hermes `turn_preflight.py:282-295` 的三级来源 + `conversation_loop.py:392-419` 的 floor 思路），qa 节点的截断就不必再"宁少勿多"；这也是消掉 `nodes.py:15-18` ponytail 注记（换 tiktoken）之外的更便宜路径。
- **截断保留 sidecar 语义**：qa 节点把历史拼进 user 消息（`nodes.py:63-69`），被 `_recent_turns` 裁掉的轮次等于 Hermes 的"压缩丢行"。可借鉴其 `_DB_PERSISTED_MARKER` 思路：裁剪决策只做一次并写回 state（state.py:22 已有 reducer 约定），避免同一 turn 内多次进入 qa 时重复裁剪出不同前缀。
- **先落盘再执行**：邮件分类的 `mail_triage` 批处理（`nodes.py:87-102`）在调 LLM 前先把批次持久化，Hermes 的 `session_persistence_failed` 即终止 turn（`turn_tool_round.py:128-150`）对应到 Memoria 就是"分类结果未持久化就不触发任何归档动作"——与"归档必须人工确认"红线同构。
- **延迟与耗尽的语义分离**：graph.py:23 的 `RetryPolicy(max_attempts=3)` 只覆盖"可重试错误"；Hermes 的三态（退款重试/临时延迟 `compression_deferred`/终态 `exhausted`，`turn_preflight.py:318-345`）说明 LangGraph 节点也该把"压缩器忙""预算未到"从异常里摘出来作为正常返回值，避免 retry 烧在注定失败的分支。
- **每 turn 一次的 setup 与每迭代一次的清洗分层**：`build_turn_context` vs `prepare_iteration` 的划分对 LangGraph 的等价物是"`make_qa` 闭包外做一次的（store/embedder 绑定）"与"每次 `qa(state)` 调用内做的（历史裁剪、消毒）"——现在 Memoria 每次问答都重跑 `_recent_turns`，多轮工具化的qa（若引入）需要 Hermes 式的重锚（`turn_iteration_prep.py:248-254`）。

### 不适合搬

- **双层 while + verdict 反射回灌**：Hermes 的 `_run_phase`/`_LoopState` 是为"单进程手写循环 + 十几个可热插拔恢复阶段"服务的；LangGraph 的条件边/reducer 已承担同样的控制流职责，照搬只会多一层没有测试价值的反射。
- **prompt-cache 断点编排（`build_prompt_cache_plan`）与跨 provider fallback 链**：Memoria 是单人系统、qa 无工具循环，前缀字节工程和 provider 漫游的复杂度收益为负；需要的是选一个稳定后端 + `RetryPolicy`。
- **非流式四 watchdog / 流式 monitor 全套**：解决的是 gateway 长驻会话与 1800s 不活超时（`turn_tool_round.py:227-229`），Memoria 的 FastAPI 请求-响应模型用标准客户端超时即可。
- **API 行内补 system notice（迭代预算 90% 注入等）**：依赖"最新 tool 行是唯一可变尾巴"的 append-only 语义；Memoria history reducer 是整列表替换，硬搬会破坏状态可追溯性。

## 12. 证据索引

| 结论 | 文件:行 |
|---|---|
| 循环入口/包装层/失败收口 | `agent/conversation_loop.py:1709-1766, 1813-1856` |
| turn 循环体与 phase 调用顺序 | `agent/conversation_loop.py:1547-1706` |
| 迭代条件与宽限调用 | `agent/conversation_loop.py:1648-1650`；`agent/turn_iteration_prep.py:408-416` |
| `_LoopState`/`_run_phase` 机制 | `agent/conversation_loop.py:1381-1494` |
| 重试内层 guard→build→call→check | `agent/conversation_loop.py:1497-1526` |
| 外层异常上限 8 | `agent/conversation_loop.py:235-237` |
| begin_iteration（中断/预算/退款） | `agent/turn_iteration_prep.py:352-417` |
| redirect 重启与上限 | `agent/turn_iteration_prep.py:467-537` |
| steer 排水/交替修复/重锚 | `agent/turn_iteration_prep.py:175-254` |
| 请求组装顺序与压强测量 | `agent/turn_request_assembly.py:106-285` |
| `build_api_messages` sidecar 回放 | `agent/turn_context.py:1236-1344` |
| turn prologue（记忆预取/sidecar 盖章） | `agent/turn_context.py:1029-1214, 893-976` |
| system prompt 冻结与身份校验 | `agent/conversation_loop.py:741-910` |
| 工具轮：先落盘再执行/混合批次/守门 | `agent/turn_tool_round.py:46-230` |
| 工具结果 append 与 spillover/预算 | `agent/tool_executor.py:1113-1209`；`tools/tool_result_storage.py:293-391, 93-120` |
| preflight 门/扩窗/超时/延迟 | `agent/turn_preflight.py:57-225` |
| post-tool 压缩与 prune | `agent/turn_preflight.py:244-396` |
| `should_compress`/阈值/熔断 | `agent/context_compressor.py:2994-3026, 2218-2224` |
| 压缩软延迟/耗尽契约 | `agent/conversation_loop.py:1089-1149, 199-221` |
| API 调用/流式决策/中断/限流 guard | `agent/turn_api_call.py:46-288` |
| 错误恢复链/本地错误判定/退避 | `agent/turn_api_error.py:52-237, 253-426` |
| 流式 monitor 心跳/stale kill | `agent/chat_completion_stream_monitor.py:59-89` |
| 非流式 worker/四 watchdog/中断强关 | `agent/chat_completion_nonstream.py:272-319, 186-270` |
| 迭代耗尽摘要调用 | `agent/chat_completion_helpers.py:2309-2363`；`agent/turn_finalizer.py:124-195` |
| finalize：流恢复/收尾/微压缩 | `agent/turn_finalizer.py:225-328` |
| usage 折叠/锚/再武装/落库队列 | `agent/turn_usage.py:73-297`；`agent/turn_response_check.py:195` |
| turn 开头 idle+preflight 压缩 | `agent/turn_context_compaction.py:129-189` |
| 辅助模型路由链（压缩摘要用） | `agent/auxiliary_client.py:1-4`；`agent/conversation_compression.py:875-881` |
| 默认迭代上限 / CLI max_turns | `run_agent.py:241, 1471`（`agent/iteration_budget.py:1-16` 的 docstring 称默认 500，与 `run_agent.py:241` 的 `sys.maxsize` 不一致，以代码为准） |
| Memoria 现状（qa/预算/RetryPolicy） | `src/memoria/graph/nodes.py:15-102`；`src/memoria/graph/graph.py:23` |

*未定位到：独立的"窗口滑动管理器"模块——窗口管理分散在压缩四触发点与请求组装压强测量中，无单一 owner；`chat_completion_helpers.py` 内 `build_api_kwargs` 的参数级组装细节未展开（4000+ 行，属请求层而非循环层）。*
