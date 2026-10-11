# ZCode 架构设计研究（zai-org/ZCode）

> 研究对象：`zai-org/ZCode` — Z.ai 的 coding agent harness（"Powerful, intelligent, extensible"）
> 语言/规模：TypeScript monorepo，约 3208 个 `.ts` + 765 个 `.tsx` 文件（不含 node_modules）；Apache-2.0
> 形态：Electron 桌面端 + Web 端 + CLI + 服务端；本文聚焦 Agent 运行时（`apps/zcode-cli/packages/core`）
> 所有路径相对仓库根目录；结论均来自源码与 `AGENTS.md`/`architecture-policy.yaml`，推测处已标注。

---

## 1. 项目概览

- 定位：全平台 coding agent harness。桌面 Electron（`packages/desktop`：main / host / renderer 三层）、Web 客户端（`packages/web` + `packages/server`）、CLI 运行时（`apps/zcode-cli`）、共享 UI 库（`packages/ui`，React + Zustand）。
- 明确的进程职责边界（`AGENTS.md`「进程、协议与远程控制」一节）：
  - Desktop Main 只做窗口、原生操作、进程调度、消息转发，**不承载 task/session 业务状态**；
  - Desktop 与 Agent 通过 stdio 通信，协议定义在 `packages/shared/src/zcode-protocol/index.ts`，要求"严格类型 + 运行时校验"；
  - 手机远控 / 远程 workspace 复用同一 Host 与会话运行时，不为远端另起 Agent；
  - 外部 relay 只做鉴权、配对、心跳、转发，**不保存业务状态**（任务队列、快照）。
- 上游依赖在 `packages/provider`（provider 抽象）与 `packages/provider-node`（Node 侧实现）隔离，UI/服务层不直接接触模型 SDK。

## 2. 整体架构

### 2.1 目录分层

```
packages/            # 平台与服务层
  desktop / web / server / ui / services / rpc / shared / client / provider /
  provider-node / zcode-cua / zcode-server-cli / model-option-map / formal-proof
apps/zcode-cli/      # Agent 运行时（内含自己的小 monorepo）
  packages/
    core             # Agent 核心：turn machine、context builder、compaction、tool、permission、memory、subagent、workflow、hooks
    contracts        # 跨进程序列化协议（ModelMessage、TurnState、CompactBoundaryPayload 等）
    cli / tui        # 交互层
    adapters / bootstrap / runtime 装配
    dynamic-workflow(-runtime)   # 工作流编排
    node-repl-host   # node REPL 工具宿主
    bundled-skills / browser-use-plugin / superpowers-plugin  # 技能与插件
    telemetry / i18n / debug / shared-types
packages/services/src  # 业务服务：session、storage、model-provider、memory、plugins、mcp-sync、usage-stats、credential、oauth、broadcast …
packages/shared/src    # 协议与类型（zcode-protocol、model-config、usage-stats）
```

### 2.2 机器可检查的架构治理（最有特色的一层）

`architecture-policy.yaml` 把架构约束写成数据，由 `pnpm architecture:check` 执行：

- 每个模块声明 `roots`、`requires`（允许依赖的模块）、`publicEntrypoints`（唯一公开入口，如 `packages/services/src/storage/contract.ts`）、`layers`/`layerOrder`（domain → app → adapters）、`owner`（责任人域）。
- 全局红线：`maxFileLines: 400`、`maxContractLines: 300`、`maxPublicMethods: 12`、`forbidCycles: true`、`forbidDeepImports: true`（禁止绕过入口深导入）。
- 存量模块标 `managed: false`（legacy），新模块强制 `managed: true`——治理规则可以渐进收紧而不是一次性重写。
- 配套：`pnpm knip`（未使用依赖/导出）、`pnpm dep:refs`（导出引用查询）、`pnpm architecture:context <module-id>`（给 agent 读的"模块阅读包"）。

> 借鉴点：把"架构规范"从 README 口头约定变成 CI 可执行清单，且入口文件即契约（`contract.ts`）。

## 3. Agent 循环与任务编排

### 3.1 Turn 状态机

`apps/zcode-cli/packages/core/src/agent/turn-machine.ts` + `turn-state.ts`：

- 一条 turn 的生命周期是显式状态机，`TurnPhase` 共 10 相：
  `idle → processing_input → awaiting_model_response → streaming → scheduling_tools → (awaiting_permission ↔) executing_tools → aggregating_results → completing / error`
- 非法迁移直接抛 `CoreErrorType.InvalidTurnPhase`（`transition()` 内先 `canTransitionTo` 校验）——状态机不允许"静默跨相"。
- `TurnState` 记录 `toolCalls`（带 `status/scheduledAt`）、`toolResults`、`pendingInputs`、`pendingPermissions/resolvedPermissions`、`traceId/turnId`。
- **用户输入排队**：turn 进行中到达的新输入走 `queuePendingInput()` / `drainPendingInputs()`，由 `acceptsPendingInput` 控制准入；AGENTS.md 说这是 runtime `CommandInbox` 串行 admission，Renderer 只保留草稿与乐观 overlay——即"输入什么时候能打断、什么时候排队"是协议级契约。
- 权限等待是一等相：`startToolExecution()` 检查是否有 `waiting_permission` 的工具，有则先进入 `AwaitingPermission`。

### 3.2 并发与取消

- trace 语义贯穿全程：`traceId + turnId` 出现在 CompactBoundary、权限请求、微压缩 payload 里，便于跨端追踪一次 turn 的完整因果链。
- ESC/abort 语义在 AGENTS.md 中以"stream/snapshot/queue/重连"双链路约束（桌面实时链路 `desktop-continuous` 与手机恢复链路 `web-remote-replayable` 必须同时验证）。

## 4. 上下文与记忆机制

### 4.1 System prompt 组装：ContextBuilder

`apps/zcode-cli/packages/core/src/context/builder.ts` 是最值得精读的文件之一。固定顺序：

1. `cli_prefix` —— "You are ZCode…" 短身份块；
2. 稳定行为体（identity / output-style 变体）；**workflow 子代理**与 `customSystemPrompt` 互斥，同时出现直接抛错（"大声失败而不是默默二选一"）；
3. 动态 system 段：desktop 上下文（仅 `zcode_desktop` surface）、Dynamic Behavior、Session Guidance、**Memory**、Env Info、Output Style、Context Management、Git System Context；
4. Skills 清单 —— 作为 **meta_user** 注入（system-reminder 形态，模拟 provider 的 block 布局），且仅当工具表里真的注册了 `Skill` 工具才注入，否则模型会"相信自己有不存在的能力"；
5. meta_user 上下文：用户指令 + **memory 索引** + 当前日期；
6. 自定义 section。

每个 section 携带元数据：`injectionTarget: "system" | "meta_user"`、`cacheHint: "stable" | "dynamic"`、`chars/tokens`（本地估算）。`orderSectionsForInjection()` 最终把顺序重排为：system/stable → system/dynamic → meta_user/stable → meta_user/dynamic——**为 prompt cache 前缀对齐服务**。

### 4.2 记忆系统：一事实一文件 + 索引

`core/src/context/sections/memory.ts` 生成注入给模型的记忆协议（与 ZCode 自身行为一致）：

- 持久目录 `memoryRoot`，**每个记忆一个文件**，frontmatter：`name`（kebab slug）/`description`（召回相关性判断用）/`metadata.type`（`user | feedback | project | reference`）；
- 正文用 `[[name]]` 互链，链接可指向尚不存在的记忆（作为"待写"标记）；
- `MEMORY.md` 是**索引**：每会话注入上下文的只有索引行（`- [Title](file.md) — hook`），正文不进索引；
- 写入纪律：先查重、更新而非新建、删错的、不记仓库本身可推导的内容（代码结构、git 历史、AGENTS.md）。

### 4.3 Token 估算

`core/src/compact/manual.ts::estimateMessageTokens()`：
- 按字符数 / `ESTIMATED_TOKEN_CHAR_DIVISOR` 估算；
- **assistant 的 toolCalls 输入单独计入**（旧实现只读 content，大工具入参被漏算，注释里明确记录了这个修复原因）；
- reasoning block 单独投影计入（可见正文投影 `modelMessageContentToText` 会隐藏 reasoning，但 provider 上下文里它占 token）。

## 5. 缓存设计

### 5.1 上游 prompt cache（三层 ephemeral 断点）

`context/builder.ts::assembleSystemMessages()` 把 system prompt 拆成**恰好 3 条 system 消息**，每条都带 `cacheControl: { type: "ephemeral" }`：

1. `cli_prefix`（最稳定）；
2. stable 行为主体；
3. dynamic 系统段（会话相关，但同会话内稳定）。

随后 `runtime/helpers/provider-request-messages.ts` 对完整消息序列做 `finalizeLatestNonSystemMessageCacheControl()`：在**最后一条非 system 消息**上再打一个 cache 断点（`cacheControlIndex` 写入 diagnostics），支持 `skipCacheWrite`。即：system 三段 + 对话尾部共 4 个增量缓存锚点，覆盖"稳定前缀 + 滚动尾部"两种复用模式。

### 5.2 缓存与压缩的联动

`compact/policy.ts` 的 `AutoCompactTokenOverride` 允许用 **provider 实测 usage**（`cacheReadTokens/cacheWriteTokens/baseTokenCount/contextUsageTokenCount`）替代本地估算作为压缩触发依据（`tokenSource: "estimate" | "provider_usage"`）——缓存命中数本身就是最准的上下文体积信号。

### 5.3 其他缓存

- 会话恢复：`packages/services/src/session/` 有 `taskIndexRepo.ts`、`legacyTaskSessionFile.ts`、`tasksDatabase/`、`sessionRealtimePort.ts`（实时链路）与恢复链路（`web-remote-replayable`）的区分。
- `packages/services/src/usage-stats/` 有 `bigmodelUsageQuotaProvider` 等用量配额缓存。
- 工具文件快照：`core/src/tool/read-file-state.ts` 记录文件读取状态（供 edit 匹配与变更检测）。

## 6. 压缩/记忆压缩机制（两级压缩，重点）

`apps/zcode-cli/packages/core/src/compact/` 是完整实现，全部常量可查。

### 6.1 微压缩（microcompact，本地、无损上下文结构）

`compact/microcompact.ts`：把**旧工具结果**替换为占位文本 `"[Old tool result content cleared]"`，不调用模型：

- 触发：`thresholdTokens`（默认由 autoCompact 阈值推导：`min(阈值×0.9, 阈值−2000)`，`buildDefaultMicrocompactThreshold`）或**空闲 60 分钟**（`DEFAULT_MICROCOMPACT_IDLE_THRESHOLD_MINUTES` → `MicrocompactTrigger.TimeBased`）；
- 清除对象：按"assistant 轮次"分组（`groupByAssistantStartedRounds`），从最旧开始清，**保留最近 5 组**（`DEFAULT_MICROCOMPACT_KEEP_RECENT_TOOL_RESULTS = 5`）；
- 只清白名单工具（Read/Bash/Grep/Glob/WebFetch/WebSearch/Edit/Write/ApplyPatch）；错误结果默认不清（`clearErrorResults`）；含 image/video/file 的媒体结果**受保护不清**（`hasMediaToolResultContent`）；已清过的不重复清；
- **最小收益闸门**：节省 < 256 tokens（`DEFAULT_MICROCOMPACT_MIN_TOKEN_SAVINGS`）则放弃，回滚为原消息——避免缓存前缀被破坏却没省到 token。

### 6.2 全量压缩（模型摘要式）

`compact/policy.ts` + `manual.ts` + `prompt.ts`：

- 预算常量：默认上下文窗 200k（`DEFAULT_COMPACT_CONTEXT_WINDOW`）；**有效窗口 = contextWindow − min(maxOutputTokens, 21k)**（provider 窗口是输入输出共享，压缩阈值分母必须扣掉输出预留）；再减 13k buffer（`AUTOCOMPACT_BUFFER_TOKENS`）得到触发阈值；摘要生成自身的 max output = 20k。
- 触发判定 `shouldAutoCompact()` 返回结构化 `AutoCompactDecision`，reason 五态：`disabled / not_enough_messages / circuit_breaker / below_threshold / above_threshold`；连续失败 3 次熔断（`MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES`）。
- 摘要 prompt（`compact/prompt.ts`）工程细节非常密集：
  - 头尾双重禁工具指令（"Tool calls will be REJECTED and will waste your only turn"）；
  - 要求先 `<analysis>` 后 `<summary>`；
  - 9 段固定模板：Primary Request / Key Technical Concepts / **Files and Code Sections（要求保留代码片段）** / Errors and fixes（含用户纠偏）/ Problem Solving / **All user messages（非工具结果的用户消息全量保留）** / Pending Tasks / Current Work / Optional Next Step（要求引用最近对话原文防止任务漂移）；
  - **安全相关约束必须逐字保留**（"These MUST be preserved verbatim in the summary so they continue to apply after compaction"）；
  - 支持用户自定义压缩侧重点（`Compact Instructions` 注入）。
- 收尾（`buildCompactSummaryMessage`）：摘要消息可附 `transcriptPath`（"需要压缩前细节就去读完整记录"）、`recentMessagesPreserved`、`replStateCleared`（REPL 变量失效要显式告知）、`suppressFollowup`（禁止模型复述摘要直接续干）。
- 边界元数据 `CompactBoundaryPayload`（`manual.ts::buildManualCompactBoundary`）记录：pre/postCompactTokenCount、summarized/keptMessageCount、`lastSummarizedMessageId`、preservedSegment、`willRetriggerNextTurn`、traceId/turnId——压缩本身是可审计事件。
- "不够压缩"的判定不是条数而是**轮次数 ≥ 2 且有 assistant 消息**（`hasEnoughMessagesToCompact`）。
- 摘要失败重试：`MAX_COMPACT_PROMPT_TOO_LONG_RETRIES = 3`，重试时插入标记 `"[earlier conversation truncated for compaction retry]"`。

### 6.3 消息历史与媒体预算

`core/src/runtime/helpers/` 下有一族 helper 专管发给 provider 前的最终投影：`provider-request-messages.ts`（系统提醒重排、相邻 user 合并、latest real user 索引）、`media-budget.ts` / `compact-media.ts` / `media-capability.ts`（图片/视频按模型能力与 token 预算降级，`cacheControl` 在剥离 metadata 前先记录），`agent/message-history.ts` 是带 `cacheControl` 的历史存储。

## 7. 工具调用机制

`core/src/tool/`（约 117 个 handler 文件）：

- **注册表**（`registry.ts`）：`ToolRegistryImpl` 支持**别名机制**，且 canonical 永远优先于 alias——后注册的真实工具会顶掉指向它的旧别名并告警，避免兼容别名劫持工具身份；`toContracts()` 输出给模型。
- **调度器**（`scheduler.ts`）：基于依赖图并行。`ToolScheduleItem` 带 `dependencies / canRunParallel / readOnly / destructive / concurrentSafe / sideEffectScope`；默认并发 10（`DEFAULT_MAX_CONCURRENCY`）；只读工具来自 `READ_ONLY_TOOLS` 集合。即"哪些调用能并行"不是模型决定，而是 harness 按副作用与依赖推导。
- **可见性投影**：`provider-visible-order.ts`（暴露给模型的工具顺序）、`tool-visibility.ts`、`json-schema.ts`（入参 schema 生成）、`model-contract.ts`。
- **输入治理**：`input-normalization.ts`、`input-validation-model-content.ts`、`tool-input-validation-issues.ts`、`path-normalization.ts`、`path-policy.ts`、`bash-timeout-policy.ts`。
- 内置工具族（从 `tool/handlers/` 目录可数）：Read/Write/Edit（`edit-matchers.ts`、`diff.ts`）、Bash（后台生命周期、超时、图片输出、git 运行时安全）、Grep/Glob（bundled 原生二进制 ripgrep/ugrep/bfs，见 `apps/zcode-cli/dependencies/native-search/`）、WebFetch/WebSearch、AskUserQuestion、Agent（子代理，`agent.ts`）、Skill、AmendWorkflow 系列、memory 文件权限等。
- Bash 只读判定被拆成约 15 个文件（argv 直读、各 flag 家族、git 子命令族、multiword 命令族）——权限判定追求可枚举可测试，而不是一条大正则。

## 8. 权限与安全

- `core/src/permission/`：`service.ts`（allow/deny 决策入口，plan-mode 转移单独策略化）、`broker.ts`、`rule-matching.ts`、`plan-mode-policy.ts`；子代理权限模式只有 `auto | plan`（`subagent/profile.ts::AgentPermissionMode`，从 frontmatter 解析）。
- `core/src/tool/executor/` 的权限执行链：`permission-flow.ts`、`permission-input-recheck.ts`（执行前重查，防 TOCTOU）、`permission-responder-race.ts`（响应竞态）、`permission-rules-persistence.ts`（规则持久化）、`memory-file-permission.ts`。
- Bash 命令级策略：`bash-command-permission-policy.ts` + `bash-command-rule-evaluator.ts` + 只读策略族。
- hooks 信任体系：`core/src/hooks/` 含 `workspace-hook-trust-coordinator / trust-evaluation / runtime-admission / review-flow`——工作区 hook（用户项目里的钩子脚本）有独立信任评估与审查流，默认不信任。

## 9. 扩展机制

- **插件**：`packages/services/src/plugins/` + `plugin-sync`；CLI 侧 `core/src/plugin-reference`。
- **技能**：`apps/zcode-cli/packages/bundled-skills/skills/`（目录式技能，内置 `dynamic-workflows`）；`core/src/agent/loaded-skills.ts` 负责加载与注入。
- **MCP**：`core/src/mcp/`（含 `image-normalization.ts`）；服务侧 `services/src/mcp-sync/`、`official-mcp/`。
- **子代理**：`core/src/subagent/profile.ts` —— 用 frontmatter 定义（含 `permissionMode`），由 `agent.ts` 工具派生。
- **工作流**：`core/src/workflow/` + `dynamic-workflow(-runtime)` —— 用 TypeScript 脚本编排多子代理，带类型检查与编译诊断（对应本文档写作时 harness 的 CreateWorkflow 机制）。
- **REPL 宿主**：`node-repl-host` + `core/src/repl/`，把无状态工具调用升级为有状态 JS 执行环境（压缩时 REPL 状态清空要显式告知模型）。

## 10. 状态持久化

- 会话/任务：`packages/services/src/session/` 的 `tasksDatabase/`、`taskIndexRepo.ts`、`automationRepo.ts`（定时自动化）、`offPeakTaskRepo.ts`（闲时任务队列）。
- 存储层有明确分层契约：`packages/services/src/storage/contract.ts`（domain/app/adapters 三层，`architecture-policy.yaml` 唯一列了 `layerOrder` 的模块）。
- 配置迁移有专门测试：`packages/services/test/providerConfigMigration.test.ts`、`importedClaudeRecovery.test.ts`（从 Claude Code 配置导入的恢复测试）。

## 11. 设计规范清单（可直接照抄）

1. **规范可执行化**：架构约束写进 `architecture-policy.yaml`（文件行数上限、公开入口、禁止环依赖），CI 强制；存量模块 legacy 渐进纳管。
2. **状态机一等公民**：turn 生命周期显式建模，非法迁移抛错；权限等待是状态机的一个相，不是回调标志位。
3. **压缩两级化**：先本地微压缩（清旧工具结果，保媒体、保错误、保最近 5 组），省不够 256 token 就回滚；再用模型摘要压缩，摘要模板 9 段固定。
4. **安全约束逐字保留**：压缩摘要时用户的安全指令 verbatim 保留。
5. **最小收益闸门**：任何有缓存代价的变更都要算"省的 token 是否值得破坏缓存前缀"。
6. **缓存断点分层**：system 拆 3 条各带 ephemeral 断点 + 对话尾 1 个，稳定段与动态段分离。
7. **token 估算必须覆盖工具入参与 reasoning**，与 provider 实测 usage 可互换（`tokenOverride`）。
8. **模型可见面投影**：工具的执行函数、内部字段绝不进 schema；注入什么（skills 清单）取决于工具表真实内容。
9. **canonical 优先于 alias**：兼容别名不得劫持真实工具身份。
10. **并行由 harness 推导**：副作用范围（`sideEffectScope`）+ 依赖图 + 只读集合 → 并行分组，不信模型自述。
11. **协议改动带运行时校验**：跨进程消息（`packages/shared/src/zcode-protocol`）严格类型 + 校验。
12. **UI 不持有业务事实**：Main/renderer 只留草稿与乐观 overlay，会话状态归 Host/CLI runtime。
13. **日志分级制度化**：debug（高频原始数据，生产不落盘）/info/warn/error 各自职责写进 AGENTS.md。
14. **修复原因入注释**：bug 修复用中文注释写明原因与依据（本仓库源码注释大量体现，如 token 估算、微压缩媒体保护）。

## 12. 知识点与最佳实践（它解决了什么问题）

| 做法 | 解决的问题 |
|---|---|
| 微压缩 + 全量压缩两级 | 全量压缩贵且毁缓存；多数场景只需清旧工具结果 |
| 空闲 60min 也触发微压缩 | 长会话挂机后回来，缓存已失效，顺手清结果零成本 |
| `hasEnoughMessagesToCompact` 按轮次 | 按条数压缩会切碎一轮推理，摘要质量崩 |
| 摘要里强制"All user messages"清单 | 模型改需求后旧需求丢失导致任务漂移 |
| 摘要带 transcriptPath | 摘要必然丢细节，给出可回溯的原文地址 |
| `willRetriggerNextTurn` 标记 | 压缩后仍超阈值时下一轮主动再压，避免请求 400 |
| 权限 input-recheck | 审批通过到执行之间输入可能已变（TOCTOU） |
| 媒体结果保护 + 能力降级 | 图片被清掉后模型幻觉"看过图"；不支持图的模型请求直接 400 |
| Skills 只在 Skill 工具存在时注入 | 防止模型调用不存在的工具 |
| 别名与 canonical 分离 | 插件生态里同名工具覆盖引发的安全与行为回归 |

## 13. 对我方项目（LangGraph + RAG）的可迁移结论

适合搬：
- 两级压缩与"最小收益闸门"（LangGraph 的 `RemoveMessage`/checkpointer 场景完全适用）；
- 压缩边界作为带元数据的事件（`CompactBoundaryPayload` 思路）持久化，供审计与再触发；
- 记忆"一事实一文件 + 索引注入"——与 Memoria 的知识复利定位天然契合；
- token 估算要覆盖工具入参与 reasoning，并接受 provider usage 校准；
- 权限规则可枚举化（Bash 只读策略族的文件拆分方式）。

不适合搬：
- 机器可检查架构治理适合大团队 monorepo，小仓库用 lint 分层即可；
- 三进程（main/host/renderer）+ relay 的多端语义，单机 RAG 应用用不到；
- 200k 窗口假设的常量体系需按自家模型重标定。

## 14. 证据索引

| 结论 | 文件 |
|---|---|
| 架构治理规则/上限 | `architecture-policy.yaml` |
| 进程与协议边界、日志分级 | `AGENTS.md` |
| Turn 状态机 10 相与非法迁移抛错 | `apps/zcode-cli/packages/core/src/agent/turn-machine.ts`、`turn-state.ts` |
| 微压缩常量/白名单/媒体保护 | `.../core/src/compact/microcompact.ts` |
| 压缩阈值/输出预留/熔断 | `.../core/src/compact/policy.ts` |
| 摘要 9 段模板/安全指令逐字保留 | `.../core/src/compact/prompt.ts` |
| 轮次分组/估算含 toolCalls/reasoning | `.../core/src/compact/manual.ts` |
| system 三段缓存断点/section 顺序 | `.../core/src/context/builder.ts` |
| 记忆协议（一事实一文件） | `.../core/src/context/sections/memory.ts` |
| 工具调度依赖图/并发 10 | `.../core/src/tool/scheduler.ts` |
| 别名与 canonical | `.../core/src/tool/registry.ts` |
| 缓存锚点/媒体预算 | `.../core/src/runtime/helpers/provider-request-messages.ts`、`media-budget.ts` |
| 子代理权限模式 | `.../core/src/subagent/profile.ts` |
| 会话/任务持久化 | `packages/services/src/session/`（taskIndexRepo、tasksDatabase） |
