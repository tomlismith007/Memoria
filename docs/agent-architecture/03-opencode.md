# OpenCode（v2）架构设计研究（anomalyco/opencode）

> 研究对象：`anomalyco/opencode`（原 sst/opencode，"The open source coding agent"），约 21 万 star
> 技术栈：Bun + TypeScript，**Effect-TS** 函数式运行时；默认分支 `dev`
> 形态：TUI / 桌面 / Web / server / SDK(js, sdk-next) / plugin / ACP / containers / slack，共 30+ 包的 monorepo
> 所有路径相对仓库根目录；结论来自源码精读，推测处已标注。

---

## 1. 项目概览

- monorepo 包：`packages/` 下 33 个，含 `opencode`（主服务）、`core`（v2 内核）、`llm`、`server`、`tui`、`plugin`、`sdk`、`sdk-next`、`protocol`、`schema`、`function`、`console`/`enterprise`（云控制面）、`containers`、`effect-drizzle-sqlite` 等。
- 代码运行时**全面 Effect-TS 化**：服务以 `Context.Service` + `Layer` 声明，跨进程用 `LayerNode` 组装；`packages/opencode/src` 下几乎所有模块都是 `Service`/`layer` 二元结构。
- 依赖方向有硬规则（`AGENTS.md`）：
  - `Schema → Core → Protocol → Server`；
  - Client 运行时可依赖 Schema 与 Protocol，**永不依赖 Core/Server**；
  - `sdk-next` 组合 Client + Core + Server；
  - Protocol 或 Server HttpApi 改动后必须 `bun run generate`，禁止手改 `src/generated`。

## 2. 整体架构

- `packages/opencode/src` 模块域：`session`（循环/消息/压缩/指令/revert/todo）、`tool`、`agent`、`permission`、`config`、`provider`、`server`、`bus`、`storage`、`skill`、`mcp`、`lsp`、`plugin`、`share`、`snapshot`、`worktree`、`acp`、`ide`、`background`、`control-plane`。
- `packages/core/src/session` 是 v2 内核：`execution/`（执行调度）、`runner/`（单次续跑）、`compaction.ts`、`store.ts`/`sql.ts`/`projector.ts`（事件投影持久化）、`context-epoch.ts`、`run-coordinator.ts`。
- server 层（`packages/opencode/src/server/`）：HTTP + 事件流（`event.ts`）、`projectors.ts`（把领域事件投影给 UI）、`mdns.ts`（局域网发现）、`tui-event.ts`；多端共享同一 server 事件协议。

## 3. Agent 循环与任务编排

### 3.1 持久化执行（durable execution）——最有辨识度的设计

`packages/core/src/session/execution/execution.ts` + `runner/index.ts`：

- `SessionExecution.Service` 接口只有四个动作：`active`（本进程持有的活跃执行集合）、`resume`（空闲时启动或加入进行中的执行）、`wake`（注册新落库的工作，"Repeated wakeups may coalesce"——重复唤醒合并）、`interrupt`。
- `SessionRunner` 的语义注释直白：**"Runs one local continuation from already-recorded Session history"**——执行不是"一个跑在内存里的循环"，而是"从已落库的会话历史里续跑下一段"。进程崩溃/重启后，新进程可以凭存储里的历史继续 `resume`。
- `RunError` 是显式联合类型：`LLMError | SessionRunnerModel.Error | MessageDecodeError | ContextSnapshotDecodeError | SystemContext.InitializationBlocked | ToolOutputStore.Error`——每一类失败都有对应的恢复策略入口。
- 这套模型把 agent 循环从"长驻 Promise"改造成"事件驱动的续跑单元"，天然支持断点恢复、多端接管、闲时执行。

### 3.2 步数上限的工具禁用

`packages/core/src/session/runner/max-steps.ts`：达到 agent 配置的 `steps` 上限后，注入 `MAX_STEPS_PROMPT`——用一段"CRITICAL"级指令明确"工具已禁用、必须文本收尾、需汇报已完成/未完成/建议"，并把"此约束覆盖一切其他指令（包括用户要求继续编辑）"写死。用**禁用工具表**而非硬中止来收敛循环，让模型自己产出交接文本。

### 3.3 子代理与内置 agent

- `Agent.Info` schema（`packages/opencode/src/agent/agent.ts`）：`name / description / mode(subagent|primary|all) / permission(Ruleset) / model / prompt / options / steps / temperature / topP / hidden / color`。
- 内置非对话 agent：`compaction`（专用压缩 agent，可配独立模型）、`explore`、`summary`、`title`，各有独立 prompt txt（`agent/prompt/*.txt`）。
- agent 生成器：`generate()` 用 `generateObject` 从一段描述生成 `{ identifier, whenToUse, systemPrompt }`——"描述转子代理"是产品能力而非外部工具。
- 子代理权限继承与裁剪：`agent/subagent-permissions.ts`。

## 4. 上下文与记忆机制

### 4.1 System prompt：按 provider 家族分版本

`packages/opencode/src/session/system.ts::provider()`：

- 按 `model.api.id` 匹配选择 prompt 变体：`anthropic / beast(gpt-4|o1|o3) / astra(gpt-6) / codex / gpt / gemini / kimi / trinity / meta(muse)` + `default`，全部是独立 txt 资源（`session/prompt/*.txt`）。
- 注入环境块 `<env>`：working directory、workspace root、是否 git 仓库、平台、今天日期；另有 `<available_references>`（可访问的附加目录及描述）。
- 由 `SystemPrompt.Service` 提供 `environment / skills / mcp` 三段动态内容——skills 清单和 MCP 工具说明不是硬编码进 prompt，而是运行时服务化输出。

### 4.2 规则文件：跟着"读过的文件"走

`packages/opencode/src/session/instruction.ts` 的 `extract()`：扫描历史中 `read` 工具的已完成结果，从 `part.state.metadata.loaded` 里收集读过的路径——**指令解析与工具执行联动**：AGENTS.md/规则文件被模型真实读过后才进入后续上下文体系（配合 `resolve()` 把 `@file` 引用展开为内容）。未读的大规则文件不会偷偷占上下文。

### 4.3 压缩：overflow → prune → select → summary 四段流水线

**溢出判定**（`session/overflow.ts`）：

- `usable = model.limit.input − reserved`（模型给 input 上限时），否则 `context − maxOutputTokens`；
- `reserved` 默认 `min(20_000, maxOutputTokens)`（`COMPACTION_BUFFER`），可 `cfg.compaction.reserved` 覆盖；
- 溢出 = `tokens.total ≥ usable`，其中 total 兜底为 `input+output+cache.read+cache.write`（**缓存 token 计入体积**）。

**剪枝 prune**（`session/compaction.ts`，零模型调用）：

- 从尾部回扫，保护最近 `PRUNE_PROTECT = 40_000` tokens 的工具输出；更早的已完成工具输出打 `time.compacted` 标记，渲染时变成 `"[Old tool result content cleared]"`；
- 只有预计回收 > `PRUNE_MINIMUM = 20_000` tokens 才动手；`skill` 工具受保护；遇到摘要消息即停；前 2 个 turn 不动。

**保留尾段 select**：

- 尾部保留预算 `preserveRecentBudget = clamp(usable × 0.25, 2_000, 15_000)`，可 `cfg.compaction.preserve_recent_tokens` 覆盖；`cfg.compaction.tail_turns` 可限定保留最近 N 个 turn；
- 预算不足以整段保留时 `splitTurn()` 从 turn 内部二分找能装进剩余预算的起点——**turn 内部分级保留**。

**摘要 summary**（`packages/core/src/session/compaction.ts`）：

- 序列化输入：用户消息/助手文本/reasoning/工具调用与结果逐条转文本，工具输出截断到 `TOOL_OUTPUT_MAX_CHARS = 2000`，附件转 `[Attached mime: name]`；
- 摘要输出 token 上限 `SUMMARY_OUTPUT_TOKENS = 4_096`；
- **固定模板**（`SUMMARY_TEMPLATE`）：`Objective / Important Details / Work State{Completed, Active, Blocked} / Next Move(1,2…) / Relevant Files`，规则包括"空段也要保留""短句 bullet 不写散文""精确保留路径/符号/命令/错误串/URL""不得提及摘要过程本身"；
- **增量合并而非重摘**：`SUMMARY_UPDATE_INSTRUCTIONS` 要求把 `<prior-summary>` 与 `<conversation>` 合成新摘要——"prior 里已完成且不再需要的才可丢弃""冲突时以对话为准""把完成的从 Active 移到 Completed"。历史里已完成的压缩对（user+summary assistant 消息）会被隐藏，不再重复进输入（`completedCompactions()` + `hidden` 集合）；
- 压缩可被插件改写：`experimental.session.compacting`（替换 prompt/注入 context）、`experimental.chat.messages.transform`（替换消息序列）。

**压缩的存储形态**：压缩是**消息的一部分**——user 消息带 `CompactionPart`（含 `tail_start_id` 指向保留尾段起点），assistant 消息带 `summary: true`。回放时（`session.ts` 第 725 行附近）按 `tail_start_id` 截断——压缩结果可重放、可恢复，与"持久化执行"模型自洽。

## 5. 缓存设计

- 未见主动的 provider prompt-cache 控制注入；缓存治理体现在**计量与决策**层：每条 assistant 消息持久化 `tokens: {input, output, reasoning, cache: {read, write}}` 与 `cost`，压缩的溢出判定把 cache read/write 一并计入——**用实测用量而非估算驱动压缩**。
- 持久化执行 + 事件投影让"恢复会话"不依赖内存缓存：任何进程都能从 store 重建（`core/src/session/store.ts`、`projector.ts`）。
- 指令内容缓存：`Instruction.Service` 对规则文件做集合缓存（`systemPaths`），避免每次请求重扫磁盘。

## 6. 工具调用机制

`packages/opencode/src/tool/`：

- **注册**：`registry.ts` 组合三源——内置工具、插件 `ToolDefinition`（`@opencode-ai/plugin`）、MCP；schema 同时支持 zod 与 `@ai-sdk/provider` 的 JSONSchema7。`Tool.InferDef` 从定义推导 TS 类型。
- **内置工具清单**（目录实证）：`read / edit / write / glob / grep / apply_patch / shell / webfetch / websearch / lsp / skill / task（子代理）/ todowrite / question / plan（enter+exit）/ external-directory / code-mode / mcp-websearch / invalid`。每个工具配同名的 `.txt` 文档（`read.txt`、`task.txt`……），文档与实现同目录同版本。
- **invalid 工具**：`invalid.ts` 注册一个接住"模型发出的非法工具调用"的占位工具，把错误变成对话内可恢复信号，而不是中断整轮。
- **输出截断落盘**（`tool/truncate.ts`）：`MAX_LINES = 2000`、`MAX_BYTES = 50KB`（可由配置 `tool_output` 覆盖）；超限时全文写入 truncation 目录（**7 天保留期**，`cleanup()` 按天清理），模型只拿到预览 + "去读保存的文件"提示。超大输出不占上下文也不丢失。
- **计划工具对**：`plan-enter/plan-exit`（`plan.ts`）——进入计划模式后限制写操作，退出需走工具调用，形成模式闭环。

## 7. 权限与安全

- `Agent.Info.permission` 是 `PermissionV1.Ruleset`（`packages/core/src/v1/permission`）；评估入口 `permission/evaluate.ts`，按 `(tool, pattern)` 匹配产生动作。
- 子代理权限由 `agent/subagent-permissions.ts` 从主 agent 派生/收敛（例如 task 工具是否可用决定子代理能否再嵌套）。
- 危险面控制靠组合：agent 级 ruleset + plan 模式 + `external-directory` 工具（越目录访问显式授权）。

## 8. 扩展机制

- **Plugin**（`packages/plugin`）：TS 插件可注册自定义工具（`ToolDefinition`）、订阅事件、挂 hook（含压缩 hook，见 §4.3）；plugin 的注入点分布在 `registry.ts`、`agent.ts`、`compaction.ts`。
- **MCP**：`mcp/`（含 `catalog.ts` 工具目录），工具并入同一注册表与权限体系。
- **Skills**：`skill/` 服务 + `SkillTool`，清单由 `SystemPrompt.Service.skills` 注入。
- **ACP / IDE / Slack / 容器**：`acp/`（editor 集成协议）、`ide/`、`slack/` 包、`containers/`（沙箱容器）。
- **自定义命令与 share**：`command/`、`share/`（会话公开分享）。

## 9. 状态持久化与多端

- 存储双轨：文件式 `storage/storage.ts`（`NotFoundError` 语义）+ SQLite 投影（`effect-drizzle-sqlite`、`core/src/session/store.ts` / `sql.ts` / `projector.ts`）；消息是"消息 + parts"结构（`message-v2.ts`、`SessionV1.WithParts`），工具结果、附件、压缩标记都是 part。
- 会话快照与回退：`snapshot/` + `session/revert.ts`（按消息回退文件改动）。
- 多端：单一 server 事件协议（`server/event.ts` + `projectors.ts`）供 TUI/Web/桌面共同消费；`control-plane/` 承接云托管形态。

## 10. 设计规范清单（可直接照抄）

1. **执行 = 已落库历史的续跑**，唤醒可合并、中断是一等接口——所有"长任务"按这个抽象写。
2. **压缩是消息 part，不是覆盖**：带 `tail_start_id` 的可重放边界，压缩后依然可回到完整历史。
3. **摘要增量合并**并写明合并语义（冲突以新为准、完成的下沉），避免每次重摘丢信息。
4. **模板固定 5 段、空段保留**，禁止"提及摘要过程"的元话语。
5. **工具输出超限落盘 + TTL**，上下文只留预览与路径。
6. **invalid 工具兜底**：把模型的格式错误变成可恢复对话轮。
7. **每个工具一个 .txt 文档**，与实现同目录同 PR 演进。
8. **prompt 按模型家族分版本**，不要一份 prompt 走天下。
9. **Effect 服务化**：`Service` 接口 + `Layer` 装配 + 显式错误联合类型；错误类型即恢复策略清单。
10. **AGENTS.md 工程规范**：禁星号导入/导入别名、`const` 优先、避免 try/catch（用 Effect 错误通道）、单次使用的逻辑不抽函数、重型模块动态导入。

## 11. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| durable runner（resume/wake/interrupt） | 长任务进程崩溃即丢；多端同时操作互相踩 |
| 压缩前先零成本剪枝（prune 20k 门槛） | 动辄调模型做摘要，贵且慢；多数空间被旧工具输出占着 |
| 尾段保留预算 = usable×0.25 夹在 2k~15k | 摘要后"最近工作"细节全丢，模型接不上手头活 |
| splitTurn turn 内二分 | 整 turn 保留导致预算浪费或全丢 |
| 缓存 token 计入溢出判定 | 只看 input 会把已缓存部分重复计费/提前压缩 |
| 指令文件跟随 read 工具结果 | 大 AGENTS.md 未被用到也常驻上下文 |
| MAX_STEPS 禁工具而非杀循环 | 硬中止导致没有交接文本，用户不知进度 |
| skill 工具输出受 prune 保护 | 技能内容被清后模型行为规范失效 |
| 压缩专用 agent 可配独立模型 | 用便宜模型做摘要，主模型不被压缩请求污染 |

## 12. 对我方项目（LangGraph + RAG）的可迁移结论

适合搬：
- "先剪枝、后摘要"两级压缩与固定模板增量合并（可直接做成 LangGraph 的 context 管理节点）；
- 工具输出截断落盘 + 路径回读（RAG 场景的长检索结果同样适用）；
- 压缩边界可重放（Memoria 的会话表可存 `tail_start_id` 等价物）；
- invalid 工具兜底与 per-provider prompt 变体。

不适合搬：
- Effect-TS 服务栈与事件投影双存储——Python 侧用 checkpointer + 单库即可；
- 33 包 monorepo 的云控制面/企业形态。

## 13. 证据索引

| 结论 | 文件 |
|---|---|
| 依赖方向/generate 规则/分支与提交规范 | `AGENTS.md` |
| 溢出判定与 reserved 语义 | `packages/opencode/src/session/overflow.ts` |
| prune/select/summary 流水线与常量 | `packages/opencode/src/session/compaction.ts` |
| 摘要模板/合并规则/序列化 | `packages/core/src/session/compaction.ts` |
| durable 执行四接口 | `packages/core/src/session/execution/execution.ts`、`runner/index.ts` |
| MAX_STEPS 禁工具文案 | `packages/core/src/session/runner/max-steps.ts` |
| 按 provider 选 prompt/env 块 | `packages/opencode/src/session/system.ts` |
| 指令跟随 read 结果 | `packages/opencode/src/session/instruction.ts` |
| Agent schema 与内置 agent | `packages/opencode/src/agent/agent.ts`、`agent/prompt/*.txt` |
| 工具注册/清单/invalid | `packages/opencode/src/tool/registry.ts`、`tool/` 目录 |
| 截断落盘 2000 行/50KB/7 天 | `packages/opencode/src/tool/truncate.ts` |
| 压缩 part 与 tail_start_id 回放 | `packages/opencode/src/session/session.ts`（~L725） |
