# DeepSeek Harness 架构设计研究（deepseek-ai/deepseek-harness）

> 研究对象：`deepseek-ai/deepseek-harness` — "Everything is a Plugin."，约 24 万 star，MIT
> 技术栈：TypeScript pnpm monorepo，底层框架 **Cordis**（cordiverse/cordis，论文 arXiv:2608.25512 "A Programming Paradigm for Spatiotemporal Composability"）
> 状态：**developer preview**（官方明示"未做安全审计，不要当唯一安全控制"，见 `SAFETY.md`）
> 形态：`dsh` CLI + 5 个 profile（web / headless / sdk / sdk-minimal / acp）+ Electron 桌面 + Python SDK
> 本仓库中英文档齐全（`.zh.md` 一一对应），本文结论主要出自 `docs/` 与 `packages/` 源码，路径相对仓库根目录。

---

## 1. 项目概览

- apps：`cli`、`web`、`desktop`、`desktop-host`。
- packages（约 40+）：`core/`（session、tools、agent、agent-loop、scope、system-prompt…）、`llm/`、`compaction/`（5 个包）、`sandbox/`、`guard/`、`hooks/`、`skills/`、`mcp/`、`lsp/`、`browser-use/`、`computer-use/`、`ptc-runtime/`、`goal/`、`plan/`、`schedule/`、`jobs/`、`identity/`、`credentials/`、`deliverables/`、`attachment/`、`preset/`、`bundle/`、`boot/`、`sdk/`、`acp/`、`experimental/` 等。
- 文档即架构：`docs/architecture.zh.md`、`docs/agent-lifecycle.zh.md`、`docs/capability-seams.zh.md`、`docs/cordis-primer.zh.md`、`docs/config-catalog.zh.md`、`docs/event-producer-consumer.zh.md`、`docs/subsystems/*.md`，每个包都有 README（中英双语）——**设计决策（Agent Note）存放在 `.agents/notes/` 并带日期编号**。

## 2. 底层范式：Cordis（一切皆插件）

`docs/architecture.zh.md` 开篇即定义：

- 插件向**共享上下文**（`ctx`）贡献三类东西：**服务**（services）、**类型化事件**（typed events）、**可逆副作用**（reversible effects）；
- **不存在需要打补丁的特权内核**：模型适配器、工具注册表、会话日志、agent loop 本身都是插件，每个都能从配置替换；
- 各项注册都是副作用，**插件卸载时自动撤销**——扩展 = 把插件挂到别的插件旁边。

每个核心包在 `ctx` 上有一个键位（架构文档表格）：

| 包 | 职责 | ctx 键 |
|---|---|---|
| core/session | 仅追加的 SessionEvent 日志 + 内存存储 | `ctx.sessions` |
| core/system-prompt | 提示词片段与工具 schema 组装 | `ctx.systemPrompt` |
| core/tools | 作用域化工具注册表 + 带把关执行流水线 | `ctx.tools` |
| core/agent + agent-loop | Agent 接口 / 默认驱动器 | `ctx.agents` / `ctx.agentLoop` |
| llm/llm | 消息与流式词汇表、适配器 seam | `ctx.llm` |

## 3. 组装：Profile / Bundle / Patch

- **profile** = 具名组装（存于 Harness home），列出叠放的 bundle、树外插件、自己的 `cordis.patch.yml`。
- **bundle** = Cordis 配置项 + 挂载代码的分发格式（`package.json` 的 `dsh.bundle` 字段）。
- 叠层顺序（空条目列表之上）：bundle（按 profile 列出顺序）→ profile 的 `cordis.patch.yml` → home 级 → 任意 `--patch` overlay。**一条 patch 按 id 定位条目，替换其整个 config 或插入新条目**。
- `dsh-base` 是共享第一层：模型适配器、工具、持久化、沙箱与审批策略、设置、凭据、遥测；`dsh-web-app`/`dsh-headless`/`dsh-sdk-app`/`dsh-acp-app` 各自增挂一层；`dsh-sdk-minimal` 是刻意例外（完整显式 SDK 配置树，不用 dsh-base）。
- `dsh --profile web --dump-config` 打印生效配置树——**"打印出的任何条目都可以被你的 patch 替换"**。
- HMR 由 YAML 控制：base 开 `dsh-hmr`，headless/sdk/acp 关。
- `scripts/verify-application-entrypoints.ts` 强制所有 Node 应用入口走 `dsh` 启动器，拒绝绕行路径。

## 4. Session 与事件日志（重点）

`docs/subsystems/session.zh.md` + `packages/core/session/src/types.ts`：

- **`Session` 是类型化 `SessionEvent` 的仅追加（append-only）日志**，是 agent 交互完整历史的唯一真源；
- **LLM 消息历史从日志派生，从不单独存储**（`deriveMessages()` 投影）；回放 = 从同一组事件重新派生；
- **事件词汇可通过 TS 声明合并扩展**：压缩 seam 添加 `compaction/start|summary|end`，hook 协议添加 `hook/invoked|result`——第三方插件能无侵入地新增持久事件类型；
- **"模型可见即已记录"**：每个模型请求都必须能从日志重建，新增模型可见输入就必须新增会话事件；修改消息内容只能注册**纯消息投影**；
- `assistant/message` 内嵌产生它的**精确紧凑原始流**（settlement 持久化一次）；`assistant/attempt` 只保留已到 settlement 的失败/重试/取消尝试（不进模型历史）——重试语义可审计；
- 持久化格式带**世代（generation）**：`session.jsonl[.zstd]`（v0）→ `session.vN.jsonl[.zstd]`（v1+）；已提交 generation 路径**绝不重命名/替换/删除**，迁移是相邻 `vN → vN+1` 链；被 `turn/start` 封住的 restart 尾部由 migration 补 `turn/end`；
- **投影 seam** `ctx.sessionProjections`：增量折叠已提交事件，host 用 `stateOf()` 读类型化状态，UI 载体用 `snapshot()` 拿裁剪视图；host 必须显式依赖该服务，禁止静默默认值。

## 5. Agent 生命周期：turn/step 代数（重点）

`docs/architecture.zh.md`「轮次流程」的完整事件时序：

```text
turn/start
  claim next-step input + one queued message
  assemble prompt sections + tool schemas; project runtime context
  → agent/pre-step（可改写/拒绝已领取消息；首次领取被拒或为空 → 关闭无 step 的轮次）
  step/start
  agent/request → prepareCall（取消时不提交 system 与 user）
  从日志派生并冻结模型历史
  流式调用 → llm/stream → agent/assistant-stream(chunk*) → assistant/message
  tool/call* → tools/pre-execute → tools/execure → tools/post-execute → tool/result*
  step/end
  （工具欠新请求，或新输入到达 → 领取 → 下一个 step）
→ agent/turn-stopping
turn/end
```

- **step = 一次模型请求 + 它调用的工具；turn = 零或多个 step**，在领取首条输入前打开、不再欠工作时关闭——"轮次可以为空"是一等语义；
- 事件分三域：**会话事件**（持久事实，重载后仍在）、**agent 事件** `agent/*`（实时扩展点，观察/拦截进行中的工作）、**能力事件**（向 seam 附加策略，如 `fs/*`、`tools/*`、`telemetry/*`）；
- `agent/pre-step`、`agent/request`、`llm/stream`、`tools/*` 是 **waterfall 事件**——监听器必须调用 `next()` 委托，否则链断；`agent/turn-stopping` 是 serial 事件；
- 输入走统一 inbox；注入上下文（文件变更通知、子目录 AGENTS.md、skill 内容、cron 通知）作为 `agent.inject()` 合成 `user/message`，用 `source` 字段区分；
- **系统提示词即 surface 节点**：prompt 只经 `system/message` 历史传递——空渲染文本清除所有生效系统节点（模型不再看到旧 prompt）；支持缓存的分支可在缓存前缀之后追加非空更新；取消发生在任何异步阶段，system 与 user 都不提交。

## 6. 工具调用机制（重点）

`docs/subsystems/tools.zh.md` + `packages/core/tools/src/schema.ts`：

- `ToolDefinition` = 面向模型的 `ToolSchema` + **强制的 `ToolOutputDefinition`** + `execute` + 调度元数据 + 可选投影回调：
  - `ToolOutputDefinition`：`schema`（对每个成功规范值校验的原始 JSON Schema）+ `render(args, value)`（从已校验参数与值到 Native/model 内容的**纯投影**）+ `presentationMeta`（可重放的展示投影）；
  - `execute(args, exec)`：**只返回 canonical 无损 JSON 值**；必须观察 `exec.signal`，只在自己负责的工作静默后 settle；注册表通过 around-dispatch 信号替换保留取消语义，但不能硬杀同进程代码；
  - `projectContent`（post-execute 前安装执行准备内容）/ `finalizeContent`（物化前的最后一英里转换，必须 total 不抛错）；
  - `timeoutMs`：协作式超时预算，由 `dsh-tool-call-timeout-policy`（一个 `tools/execute` 包装器）执行，**绝不发给模型**；声明它即承诺实现能响应 `exec.signal` 达到静默；
  - `isConcurrencySafe`：与兄弟调用重叠的**纯同步分类器**——只有字面 `true` 才开启并行；省略/异常/非 true 一律互斥；**此元数据对模型不可见**。
- **显式允许列表投影**：注册表 `schemas()` 只投影 `name/description/parameters` 三个字段；`output/execute/projectContent/finalizeContent/timeoutMs/isConcurrencySafe/presentCall/presentResult` **绝不泄漏进模型请求**；
- `ToolSchema.deferLoading`：工具定义可延迟加载（先给模型目录，用到再取 schema）；
- 并行契约有专门 Agent Note（`.agents/notes/implemented/feature/2026-07-10-parallel-tool-call-execution.md`）：开启并行的执行**不得变更父级拥有的状态**，共享状态必须容忍并发，记录器竞争只在可交换或 fail-closed 时允许。

## 7. 记忆压缩机制（compaction 家族，重点）

`packages/compaction/` 拆成五个包，每包一责，全部可独立挂载：

| 包 | 职责 | 挂载点 |
|---|---|---|
| `compaction/` | 共享约定：所有后端与触发器用的操作与摘要格式 | `ctx.compaction` |
| `compaction-basic/` | token 压力上升自动把较早历史压为摘要；**上下文溢出错误后压缩并重试该请求** | 注册 `ctx.compaction` |
| `compaction-tool-result-pruner/` | 压缩触发后，把超预算工具输出替换为"受限头部 + middle pruned 标记 + 受限尾部" | `ctx.toolResultPruner` |
| `compaction-image-offload/` | 支持图片的路由以 `IMAGE_OFFLOAD_REQUIRED` 拒绝请求时，**永久**把超预算图片替换为"注明附件与只读路径"的文本后重试 | 监听 `agent/request-error` |
| `command-compact/` | 按需 `/compact` 命令，与运行中轮次串行化 | 注册 `ctx.commands` |

设计要点（README 原文语义）：

- 压缩 = **一次额外模型请求，只保留返回的摘要文本**；明确声明能力边界：无法缩减 system prompt、工具定义与会话前缀，无法拆分单个不可分单元（如一次超大工具调用）；
- 修剪器**不发起模型调用**，且可能已足够缓解压力使压缩跳过摘要；字符预算只是近似，压力判定归 token meter；
- 完整原始结果**始终保留在会话日志**（模型看到的与记录的是两层），可精确回放；
- 图片省略**不消耗 provider 重试预算**，切换路由/恢复/回放都保留该选择；**provider 缓存只能复用到第一条被修改消息之前**——文档明说缓存失效代价；
- 阈值与保留支持**按模型路由覆盖**（同一后端服务不同上下文大小的模型）；
- 依赖显式化：组合缺 LLM、会话存储或 token 测量时**插件加载失败**（fail-fast，不静默降级）。

token 测量独立成 LLM 家族服务（`dsh-token-meter`）——"何时压缩"与"如何压缩"解耦。

## 8. 能力 seam（capability seams）

`docs/capability-seams.zh.md`：一个 seam 三角色——**Service Definition**（声明接口）/ **Service Provider**（实现）/ **Consumer**（通常为面向模型的工具）；一包可兼任多角色，但单角色不构成 seam。

- 替换一个 provider 即改变整个产品：文件系统与进程 provider 共享同一执行世界——把它们指向远程沙箱，**Bash、PTY、LSP 一起搬走**，无需 per-工具 fork；
- subagent provider 同理：从"新建子 agent"到"把轮次委派给另一个产品"都在同一接口后；
- `ctx.agentTeams`：实验性协作 seam——持久 roster、任务板、mailbox，构建在可继续（resumable）subagent 之上。

## 9. 缓存设计

- prompt 缓存治理内建在请求组装里：系统提示词以 surface 节点承载，"具备能力的路由可在**缓存前缀之后**追加非空更新"——前缀稳定性是设计目标（§5）；
- 图片省略文档明确"provider 缓存只能复用到第一条被修改的消息之前"——**把缓存失效当作一等可推理后果**；
- 会话持久化的 generation 机制让"缓存/回放/迁移"共享同一不可变源。

## 10. 安全

`SAFETY.md`：developer preview、未审计；沙箱与审批"降低风险但不保证隔离"；建议最小权限、一次性 VM/容器、备份、检查插件与命令。沙箱/审批/凭据由 `dsh-base` 统一供给（`sandbox/`、`guard/`、`credentials/` 包），可被 patch 替换为远程执行世界。

## 11. 设计规范清单（可直接照抄）

1. **一切皆插件，无特权内核**：核心循环也是可替换组件；注册是可撤销副作用。
2. **日志即真源，历史是投影**：append-only 事件 + 派生消息；"模型可见即已记录"。
3. **事件词汇可声明合并扩展**，第三方能新增持久事件类型而不改内核。
4. **waterfall/serial 事件语义显式**：监听器必须 `next()`；协议里写明谁串行谁瀑布。
5. **模型面最小暴露**：`schemas()` 白名单三字段，执行/超时/并发元数据永不进请求。
6. **工具输出走 canonical 值 + 纯渲染**：执行返回数据，展示是纯函数，二者可独立测试与重放。
7. **压缩家族化**：测量（token meter）与策略（basic/pruner/image-offload/command）解耦，每包一个职责，按需挂载。
8. **降级显式化**：缺依赖就加载失败；图片替换是"永久决策"且声明缓存代价。
9. **世代化不可变存储**：已提交 generation 绝不改写，迁移是相邻链。
10. **配置可整树导出**：`--dump-config` 的每个条目都可被 patch 替换。

## 12. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| "先修 pruner 再压缩" | 模型摘要又贵又慢；多数压力只是工具输出堆积 |
| 溢出错误 → 压缩 → 重试同一请求 | 溢出作为可恢复错误而非终态 |
| image-offload 永久替换 + 注明只读路径 | 模型反复撞同一张超预算图；且仍能按路径找原图 |
| 摘要只保留文本 | 压缩产物可控可审计，不夹带工具状态 |
| `isConcurrencySafe` 仅字面 true 开启 | 默认串行防数据竞争，并行需显式证明 |
| `exec.signal` 协作式取消 + 不能硬杀 | 超时承诺与实现能力绑定，防止僵尸任务 |
| profile/patch 分层 + dump-config | "改一行配置换一个模型/沙箱"而不改代码 |
| 每个设计决策一篇日期化 Agent Note | 架构演化可考古，AI 协作开发的知识沉淀 |

## 13. 对我方项目（LangGraph + RAG）的可迁移结论

适合搬：
- "事件日志为真源、消息历史为投影"——LangGraph 的 checkpointer 事件化改造方向；
- 压缩流水线分层：token meter（测量）/ pruner（零成本）/ summarizer（有成本）/ 命令（手动）各自独立成"节点"；
- 工具定义"canonical 输出 + 纯渲染投影"，模型面白名单三字段；
- 溢出 → 压缩 → 重试的恢复闭环；
- 图片/大附件的"占位文本 + 只读路径"模式（RAG 的原文件引用同理）。

不适合搬：
- Cordis 全家桶：Python 生态没有等价的"可撤销副作用插件树"，LangGraph 的图编排 + 依赖注入已够用；
- JSONL generation 存储链——SQLite + 版本表即可；
- 多 profile/patch 组装对单一产品是过度设计。

## 14. 证据索引

| 结论 | 文件 |
|---|---|
| 无特权内核/profile/patch 叠层/turn 时序 | `docs/architecture.zh.md` |
| Session 事件溯源/派生历史/世代格式 | `docs/subsystems/session.zh.md`、`packages/core/session/src/types.ts` |
| seam 三角色/替换 provider 即换产品 | `docs/capability-seams.zh.md` |
| ToolDefinition/ToolOutputDefinition/白名单 | `docs/subsystems/tools.zh.md`、`packages/core/tools/src/schema.ts` |
| compaction 家族与边界 | `packages/compaction/README.zh.md`、`compaction-basic/`、`compaction-tool-result-pruner/`、`compaction-image-offload/` 各 README.zh.md |
| 安全立场 | `SAFETY.zh.md` |
| 入口治理 | `scripts/verify-application-entrypoints.ts` |
| 并行工具契约 | `.agents/notes/implemented/feature/2026-07-10-parallel-tool-call-execution.md`（路径见 tools 文档引用） |
