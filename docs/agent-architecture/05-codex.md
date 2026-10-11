# OpenAI Codex 架构设计研究（openai/codex）

> 研究对象：`openai/codex` — "Lightweight coding agent that runs in your terminal"，约 12.8 万 star
> 技术栈：**Rust 核心**（`codex-rs` workspace，约 140 个 crate）+ TypeScript SDK/CLI（`codex-cli/`、`sdk/`，早期实现，现以 Rust 为准）；Apache-2.0
> 形态：CLI/TUI（`cli`、`tui`）、headless `exec`、IDE 集成 `app-server`、云任务 `cloud-tasks`、实时语音 `realtime-webrtc`
> `docs/` 目录的 sandbox/execpolicy 等主题只留外链（developers.openai.com），实现细节以源码为准；本文全部结论出自 `codex-rs` 源码。

---

## 1. 项目概览

- 主 workspace `codex-rs/`：核心循环在 `core/`，协议在 `protocol/`，工具在 `tools/`，沙箱在 `sandboxing/`/`linux-sandbox/`/`windows-sandbox-rs/`，持久化在 `rollout/`/`history/`，多 agent 在 `agent-identity`/`agent-roles`/`agent-graph-store`/`agent-message-board-client`。
- 提示词全部模板化：`codex-rs/prompts/templates/`（compact/guardian/permissions/review/realtime/multi_agent），以 `include_str!` 编译进二进制（`prompts/src/compact.rs`）。
- 大量独立小 crate：`apply-patch`（可独立执行的补丁工具）、`execpolicy`、`network-proxy`、`secrets`、`keyring-store`、`workload-identity`、`process-hardening`——安全相关能力各自成 crate。

## 2. 整体架构：Op/Event 协议解耦

`protocol/src/protocol.rs` 定义两个核心 enum：

- **`Op`**（Submission 队列的操作）：`Interrupt`、`InterruptIfNoPendingInput{turn_id, reply: oneshot}`、`TurnInput{request, mode, reply}`、`RecoverTurn`（恢复被中断的 turn）、`SuspendTurnAndShutdown`、`ThreadSettings`/`TurnSettings`（不启动 turn 的设置变更，与 turn 共用同一提交队列以保证顺序）、`InterAgentCommunication`（跨 agent 通信也走正常提交生命周期）、`ExecApproval`/`PatchApproval`（审批回执）等。
  - 特点：**每个需要应答的 Op 都带 `oneshot::Sender`**——UI 与核心之间是请求-应答语义，而不是裸事件。
- **`EventMsg`**（核心向外发的事件）：`TurnStarted`/`TurnComplete`（v1 别名 `task_started/task_complete`）、`ContextCompacted`、`Warning`、`GuardianWarning`、`ModelReroute`、`SafetyBuffering`（输出等安全审查）、`TokenCount`、`ThreadRolledBack`、`AuthRecoveryStarted/Completed` 等。

`app-server`（JSON-RPC over stdio/UDS）把 Op/Event 桥接给 IDE；`tui`、`exec`、SDK 都是同一核心的不同前端。

## 3. Agent 循环与 turn 语义

- `core/src/session/turn.rs` 是循环主体（约 3000+ 行）：一个 turn 内按 **step**（一次模型请求及其工具）推进；每个 turn 开始前先做 `maybe_run_previous_model_inline_compact` + `context_window_token_status` 预检。
- 取消用 `CancellationToken`（tokio_util）；`Op::InterruptIfNoPendingInput` 支持条件中断——"该 turn 没有排队输入才中断"，应答先于取消完成（避免竞态窗口）。
- `RecoverTurn`/`SuspendTurnAndShutdown`：中断不是终点，turn 可以被恢复或挂起后关机（长期任务友好）。
- step 上下文 `StepContext`、world state `WorldState`（`core/src/context/world_state.rs`）——把"环境当前状态"建成独立快照对象，供压缩后的上下文重建使用。

## 4. 上下文与记忆机制（重点）

### 4.1 上下文窗口状态机

`core/src/session/context_window.rs::context_window_token_status` 返回结构化状态：

- `token_limit_reached`：自动压缩预算（见下）或**全窗口硬顶**触达；
- `full_context_window_limit = context_window × effective_context_window_percent / 100`（模型元数据里带窗口使用百分比）；
- `turn_end_compaction_threshold_reached`：`model_post_turn_compact_threshold_percent`——**turn 结束时的"顺路压缩"阈值**，不在 turn 中途打断，等 turn 完成再压。

### 4.2 自动压缩预算的两种口径

- `model_auto_compact_token_limit` 可配 `Scope::Total`（整个活动上下文）或 `Scope::BodyAfterPrefix`（只数**初始前缀之后新增**的 token）；
- `BodyAfterPrefix` 用 `AutoCompactWindow.prefill_input_tokens` 做基线（`state/auto_compact_window.rs`）：窗口对象带 `window_number`、UUIDv7 的 `first/previous/window_id`、`prefill`（`ServerObserved` 优先于 `Estimated`）、以及**每个窗口只送一次**的 `token_budget_reminder_delivered` / `auto_compact_fallback_delivered` 标记——提醒不重复轰炸，换窗自动复位（`advance()`）。
- `buffered_auto_compact_limit = scope_limit + fallback_buffer_tokens`：**只有存在 fallback prompt 时才留 fallback 缓冲**（注释明确"Only reserve the fallback buffer when there is a fallback prompt to use it"）。

### 4.3 压缩的四条实现路径

`core/src/compact*.rs` 家族：

1. **本地摘要压缩**（`compact.rs`）：调模型生成 handoff summary；`COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000` 限制送入摘要的用户消息体量；
   - 摘要 prompt（`prompts/templates/compact/prompt.md`）：*"CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task"*——列"进度与关键决策 / 重要上下文与用户偏好 / 待办与下一步 / 继续所需的关键数据"，四条要求；
   - 回灌前缀（`summary_prefix.md`）：*"Another language model started to solve this problem and produced a summary… You also have access to the state of the tools that were used"*——**把工具状态与摘要并列**交给接续模型。
2. **token 预算压缩**（`compact_token_budget.rs`）：**跳过模型摘要，直接换新上下文窗口**；注释明确"仍建模为 compaction"——pre/post hook 与 `ContextCompaction` turn item 观察到与摘要压缩完全一致的生命周期（可观测性优先于实现差异）。
3. **远程压缩**（`compact_remote_history.rs` / `compact_remote_v2.rs` + `compact_remote_v2_images.rs` / `_image_budget_tests.rs`）：由服务端接管历史摘要，客户端带图片预算管理——压缩本身是服务能力，本地保留降级路径（`compact_model_fallback.rs`）。
4. **触发时机**：Pre-turn（`InitialContextInjection::DoNotInject`，压缩后下一 turn 重新注入初始上下文）与 Mid-turn inline（`BeforeLastUserMessage`——模型被训练为"压缩摘要是最后一条历史"，因此必须把初始上下文注入到最后一条真实用户消息之上）。

### 4.4 压缩的元数据与哈希

`CompactedHistoryMetadata`：`input_goal_ids`（压缩覆盖的目标项）、`window_number/window_ids`、`compaction_response_id`、`compaction_model_hash`、`reviewer_compaction_hash`；`turn.rs::comp_hash_changed`：**前后两个 turn 的压缩兼容哈希都存在且不同才触发重压缩**——模型升级后历史与新模型不兼容时自动重压。

### 4.5 上下文管理器

`core/src/context_manager/`：`history.rs`（历史归一/裁剪，测试里可见"长行截断""执行错误行截断"）、`normalize.rs`、`updates.rs`、`history_user_authorization.rs`（历史里的用户授权语义）。

### 4.6 记忆系统

`codex-rs/memories/` 拆成 `read/` 与 `write/` 两个 crate：read 带 `citations.rs`（记忆引用出处）、`usage.rs`、`metrics.rs`；write 带 `control.rs`、`extensions/ad_hoc.rs`——**记忆的读写是两条独立流水线**，读取带引用与用量计量，写入有控制面。

### 4.7 Guardian（自动审批审查者）

`guardian-context/` crate（action/authorization/budget/composition/cursor/enforcement）+ `prompts/templates/guardian/`（`policy.md`、`classifier_instructions.md`、`node_repl_policy.md`）：一个独立模型审查者自动评估命令风险；`turn.rs` 里 `guardian_budget_compacted` 处理"审查者预算被压缩"的失败关闭语义（"token-budget resets must fail closed and retire the reviewer"）。

## 5. 缓存设计

- **上游 prompt cache**：请求携带 `prompt_cache_key`（`core/src/client.rs`），且**作用域绑定 parent thread**（`client_tests.rs::internal_session_prompt_cache_key_is_scoped_to_parent_thread`）——同会话系列的请求命中同一缓存前缀，跨会话不串。
- token 计量分 input/output/reasoning + cached（`TokenUsage`），`TokenCount` 事件实时推给 UI。
- 窗口基线缓存（§4.2 的 prefill 基线）避免重复估算。

## 6. 工具调用机制

`codex-rs/tools/src/`：

- **工具发现与注册**：`tool_discovery.rs`、`tool_definition.rs`、`tool_spec.rs`、`tool_config.rs`（按模式/权限启停工具）、`json_schema.rs`、`indirect_namespace_prefixes.rs`（间接命名空间前缀——MCP 工具命名治理）。
- **动态工具**：`dynamic_tool.rs`、`mcp_tool.rs`（MCP 工具适配）、**`tool_search.rs`**——工具太多时不全量注入 schema，让模型先搜索再调用。
- **code-mode**：`code_mode.rs` + 独立 `code-mode-runtime`/`code-mode-host`/`code-mode-protocol` crate + `v8-poc`——把多个工具调用编译成一段 JS 在 V8 里跑，减少往返。
- **apply-patch**：独立 crate 且是**可独立执行文件**（`standalone_executable.rs`、`main.rs`）：解析（`parser.rs`）、定位（`seek_sequence.rs`）、文件更新（`file_update.rs`）。给模型专用补丁通道而非通用写文件。
- **输出治理**：`tool_output.rs` + `codex_utils_output_truncation`（`truncate_text`、`approx_token_count`、`TruncationPolicy`）；`image_detail.rs` 管图像精度档位。
- **审批流**：工具执行产生 `ExecApproval` 请求事件，用户决定经 `Op::ExecApproval` 回传（`ReviewDecision`）。

## 7. 沙箱与安全（重点）

- **三平台沙箱**（`sandboxing/src/`）：macOS `seatbelt.rs`（SBPL profile）、Linux `landlock.rs` + `linux_pid_namespace.rs`、Windows `windows-sandbox-rs` + `windows-sandbox-service`（服务化沙箱）、备选 `bwrap.rs`；统一由 `manager.rs` 与 `policy_transforms.rs` 协调。
- **网络**：`network-proxy` crate 独立代理出网流量；`network access` 默认关（workspace-write 模式下需显式开）。
- **提权**：`shell-escalation` crate——沙箱内失败的命令可"提权重跑一次"（审批后出沙箱执行）。
- **execpolicy**（`execpolicy/src/`）：声明式策略（`policy.rs`/`rule.rs`/`parser.rs`/`amend.rs`/`decision.rs`）+ `sandbox_migration.rs`（从正则拦截迁移到沙箱的路径）；配套独立检查器 `execpolicycheck`。
- **权限提示模板**（`prompts/templates/permissions/`）：`approval_policy/{never,on_request,unless_trusted}.md` × `sandbox_mode/{read_only,workspace_write,danger_full_access}.md` 的正交组合，**审批策略与沙箱模式是两个独立维度**，各自的解释文本模板化注入。
- 其他：`secrets`/`keyring-store`（凭据隔离）、`process-hardening`、`attestation.rs`、`user-verification`。

## 8. 持久化与恢复

- **rollout**（`codex-rs/rollout/` + `core/src/responses_metadata.rs`）：会话历史以 rollout 文件持久化（`ResponseItemEnvelope` 逐条封装，含 `CodexHarnessMetadata`），`rollout-trace` 记推理 trace（`InferenceTraceContext`）。
- `history/` crate 管跨会话命令/消息历史；`thread-store` 管线程元数据。
- 压缩检查点 `CompactedItem` 随 rollout 持久化（§4.4），`ThreadRolledBack` 事件保留 legacy 回放语义（"live rollback operations are unsupported"——旧文件的回滚只保证能回放）。

## 9. 扩展机制

- **MCP**：`rmcp-client`（Rust MCP 客户端）、`codex-mcp`、`tools/mcp_tool.rs`、`connectors/`（连接器目录）。
- **Skills**：`skills/` crate（`loading/invocation/mentions/parser/model`，frontmatter 解析 + @mention 触发）。
- **多 agent**：`agent-identity`/`agent-roles`/`agent-graph-store`/`agent-message-board-client`（agent 间留言板）+ `Op::InterAgentCommunication` + `prompts/src/model_messages/multi_agent.rs`。
- **Hooks**：`hooks/` crate + `core/src/hook_runtime.rs`（pre/post compact hook，见 §4.3）。
- **插件**：`plugin/`、`core-plugins/`、`tools/request_plugin_install.rs`（运行时安装插件要过审批）。

## 10. 可观测性

- `otel`/`otel-trace-websocket`（OpenTelemetry，trace 可经 websocket 实时查看）；`analytics` crate 记录结构化产品事件——压缩有完整的 `CodexCompactionEvent{Implementation, Phase, Reason, Status, Strategy, Trigger}` 枚举维度（`compact.rs` 顶部 use 可见）。

## 11. 设计规范清单（可直接照抄）

1. **Op 带应答通道**：每个需要结果的提交都携带 `oneshot::Sender`，UI 不轮询。
2. **压缩是统一生命周期**：本地摘要/纯换窗/远程压缩三种实现共用 hook、turn item、分析事件。
3. **窗口对象化**：窗口编号 + UUID + prefill 基线 + 每窗一次的提醒标记。
4. **提醒只送一次**：token 预算提醒/降级提示按窗口去重。
5. **turn 结束顺路压缩**：`post_turn_compact_threshold_percent` 把压缩挪到不打扰执行的时机。
6. **前缀口径可选**：压缩预算可只数"前缀之后"的新增 token。
7. **兼容哈希重压**：模型能力变化（hash 变化）自动重压旧历史。
8. **审批与沙箱正交**：approval_policy × sandbox_mode 两个维度独立配置与解释。
9. **压缩摘要面向"下一个 LLM"**：handoff 语义 + 工具状态并列交接。
10. **安全能力 crate 化**：沙箱/策略/凭据/代理各自独立成库，可单独测试与替换。

## 12. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| `InitialContextInjection` 双模式 | mid-turn 压缩后模型看不到初始上下文导致行为漂移 |
| fallback buffer 按需预留 | 无降级路径时白留 13k+ 缓冲，浪费可用窗口 |
| prefill 基线（ServerObserved 优先） | 系统前缀巨大时"总 token"口径永远超限 |
| `tool_search` 动态工具发现 | 工具 schema 注入挤占上下文 |
| code-mode（V8 跑工具编排脚本） | 50 个工具调 50 次的往返延迟 |
| apply-patch 独立可执行 | 补丁工具可被 shell 直接调用/单独测试 |
| Guardian 预算 fail-closed | 审查者失效时宁停不裸奔 |
| compaction 全链路埋点（Strategy/Trigger/Phase） | 压缩质量不可归因就无法调优 |

## 13. 对我方项目（LangGraph + RAG）的可迁移结论

适合搬：
- "压缩 = 统一生命周期事件"的建模（Memoria 的会话压缩可发出同构事件供审计）；
- 压缩预算的"前缀后新增"口径（系统 prompt 很大的 RAG 应用尤其受益）；
- 提醒每窗一次的去重；
- handoff 式摘要 + 工具状态并列；
- 审批策略与执行沙箱（只读/工作区写/全权）正交建模。

不适合搬：
- 140 crate 的 Rust 工程化与三平台沙箱（Python 侧用子进程 + 容器即可）；
- 服务端远程压缩（依赖 OpenAI 后端能力）。

## 14. 证据索引

| 结论 | 文件 |
|---|---|
| Op/Event 协议 | `codex-rs/protocol/src/protocol.rs`（Op≈L590，EventMsg≈L1358） |
| 压缩主流程/初始上下文注入 | `codex-rs/core/src/compact.rs` |
| token 预算压缩=换窗 | `codex-rs/core/src/compact_token_budget.rs` |
| 窗口对象/每窗一次提醒 | `codex-rs/core/src/state/auto_compact_window.rs` |
| 窗口状态/预算口径/缓冲 | `codex-rs/core/src/session/context_window.rs` |
| turn 预检与 guardian 语义 | `codex-rs/core/src/session/turn.rs`（≈L1310-773） |
| 摘要 prompt/交接前缀 | `codex-rs/prompts/templates/compact/prompt.md`、`summary_prefix.md` |
| prompt_cache_key 作用域 | `codex-rs/core/src/client_tests.rs`（L1407）、`client.rs` |
| 工具族 | `codex-rs/tools/src/`（tool_search、code_mode、mcp_tool…） |
| 三平台沙箱 | `codex-rs/sandboxing/src/`（seatbelt/landlock/bwrap/manager） |
| execpolicy | `codex-rs/execpolicy/src/` |
| 审批/沙箱模板 | `codex-rs/prompts/templates/permissions/` |
| 记忆读写分离 | `codex-rs/memories/read|write/` |
| Guardian | `codex-rs/guardian-context/src/`、`prompts/templates/guardian/` |
