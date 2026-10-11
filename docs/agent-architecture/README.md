# 开源 Agent 架构设计研究

本目录沉淀了 6 个开源 coding/personal agent 的架构研究，每份文档覆盖：整体架构、agent 循环与编排、上下文与记忆、**记忆压缩机制**、缓存设计、工具调用机制、提示词与规则系统、权限与安全、扩展机制、设计规范清单、知识点与可迁移结论，并附证据索引（结论 → 源码文件）。

另有 [04b-openmuse-alpha-surfaces.md](04b-openmuse-alpha-surfaces.md)：对 OpenMuse（2026-10-11 main 1ac68f3）按 README 声明的 10 个表面逐个对照源码的深读沉淀 + 三个重点深读（持久任务引擎 / 审批与对话通道隔离 / 文档纪律）+ 横切模式与 Memoria 迁移清单；是 [04-openmuse.md](04-openmuse.md) 的表面级补充。

另有 [hermes/](hermes/00-overview.md) 子目录：对 **NousResearch/hermes-agent**（自我进化个人 agent 运行时）按 8 个维度（主循环/记忆/自改进/Gateway/工具/人格/调度/安全）的深读研究，每维度一份文档。

| 文档 | 仓库 | 语言/规模 | 一句话定位 |
|---|---|---|---|
| [01-zcode.md](01-zcode.md) | [zai-org/ZCode](https://github.com/zai-org/ZCode) | TS，3.2k 文件 | 全平台 harness；两级压缩 + 机器可检查架构治理 |
| [02-minimax-agent.md](02-minimax-agent.md) | [MiniMax-AI/Mini-Agent](https://github.com/MiniMax-AI/Mini-Agent) | Python，核心约 1k 行 | 最小专业骨架；按用户意图切分的摘要策略 |
| [03-opencode.md](03-opencode.md) | [anomalyco/opencode](https://github.com/anomalyco/opencode) | TS/Effect，33 包 | 持久化执行（durable runner）；prune→select→summary 压缩流水线 |
| [04-openmuse.md](04-openmuse.md) | [CopilotKit/openmuse](https://github.com/CopilotKit/openmuse) | TS，94 文件 | 个人 agent；租约式持久任务 + 证据溯源 + 人机审批隔离 |
| [05-codex.md](05-codex.md) | [openai/codex](https://github.com/openai/codex) | Rust，约 140 crate | Op/Event 协议 + 压缩统一生命周期 + 三平台沙箱 |
| [06-deepseek-harness.md](06-deepseek-harness.md) | [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | TS/Cordis，40+ 包 | "一切皆插件"；事件溯源会话 + 能力 seam |

## 横向对比

### Agent 循环与编排

| | 循环模型 | 取消/中断 | 并行工具 |
|---|---|---|---|
| ZCode | Turn 显式状态机（10 相，非法迁移抛错） | 状态机相内取消；输入排队（CommandInbox） | 依赖图 + sideEffectScope 推导，并发上限 10 |
| Mini-Agent | while + max_steps（默认 50） | asyncio.Event 安全检查点 + 清理不成对消息 | 无（串行） |
| OpenCode | durable runner：从已落库历史续跑（resume/wake/interrupt） | interrupt 一等接口，唤醒可合并 | 按 agent 权限与工具定义 |
| OpenMuse | AG-UI 事件流 + 委派给持久任务（maxSteps 6/16） | stop 暂停客户端队列 | 无（对话层串行；任务层靠 worker 租约） |
| Codex | Op（带 oneshot 应答）→ Event；turn 内多 step | Interrupt / InterruptIfNoPendingInput / RecoverTurn / Suspend | 并行执行 + code-mode（V8 跑编排脚本） |
| DeepSeek Harness | turn/step 代数 + waterfall/serial 事件 | 每个异步阶段取消"不提交 system 与 user" | isConcurrencySafe 仅字面 true 开启 |

### 记忆压缩（重点对比）

| | 触发 | 第一级（零模型成本） | 第二级（模型摘要） | 特色 |
|---|---|---|---|---|
| ZCode | 阈值 = 窗口 − min(输出预留 21k) − 13k buffer；provider usage 可校准 | 微压缩：清旧工具结果（保最近 5 组、保媒体、保错误；<256 token 收益则回滚） | 9 段固定模板；安全指令逐字保留；带 transcriptPath | 空闲 60min 也触发；轮次数≥2 才压；失败熔断 3 次 |
| Mini-Agent | tiktoken 估算或 API 实测 > 80k | 无 | 按用户意图切分：保全部 user 消息，压 user→user 区间 | 摘要失败降级纯文本；压后跳过一次检查 |
| OpenCode | tokens ≥ usable（input − min(20k, maxOutput)）；缓存 token 计入 | prune：保护最近 40k 工具输出，清更早的（收益 >20k 才动手） | 增量合并：固定 5 段模板 + prior-summary 合并规则；compaction 专用 agent | 尾段保留预算 clamp(usable×0.25, 2k, 15k)；turn 内二分 splitTurn |
| OpenMuse | 无（依赖 CopilotKit Intelligence） | — | — | 用"存引用现取值"回避上下文膨胀 |
| Codex | scope（Total / BodyAfterPrefix 前缀后新增）+ 全窗口百分比硬顶；turn 结束顺路压缩 | 纯换窗（token 预算压缩，不摘要） | handoff 摘要（面向"下一个 LLM"）；另有远程摘要 | 压缩兼容哈希变化自动重压；提醒每窗一次 |
| DeepSeek Harness | token meter（独立服务）判定压力；溢出错误即触发 | tool-result-pruner：头+middle pruned+尾；原图永远在日志 | compaction-basic：一次额外模型请求，只留摘要文本 | 图片永久省略并注明只读路径；声明缓存复用边界 |

### 缓存设计

| | 上游 prompt cache | 本地缓存 |
|---|---|---|
| ZCode | system 拆 3 条各带 ephemeral 断点 + 尾部消息 1 个（cacheControlIndex） | 会话任务库、文件读取状态 |
| Mini-Agent | 无主动控制；计量合并 Anthropic 缓存 token | 每 run 日志文件 |
| OpenCode | 未注入 cache_control；用持久化执行替代缓存依赖 | SQLite/文件双存储投影 |
| OpenMuse | 依赖 provider | 浏览器 profile 落盘；短时效控制台凭证续期 |
| Codex | `prompt_cache_key` 绑定 parent thread | rollout 文件 + prefill 基线 |
| DeepSeek Harness | 系统提示词 surface 节点 + "缓存前缀之后追加更新" | generation 化不可变 JSONL |

### 工具调用

| | 定义方式 | 模型可见面 | 值得注意 |
|---|---|---|---|
| ZCode | ToolEntry + 别名机制（canonical 优先） | registry.toContracts() | Bash 只读判定拆 15 个文件可枚举 |
| Mini-Agent | Tool 基类 + JSON Schema，双协议投影 | name/description/parameters | MCP 三超时；技能两级披露 |
| OpenCode | zod/JSONSchema 双支持；.txt 文档随工具同目录 | 插件 ToolDefinition | invalid 工具兜底；输出落盘 2000 行/50KB/7 天 TTL |
| OpenMuse | zod + execute 三元组 | AG-UI 工具事件 | 审批不走对话通道；exit receipts |
| Codex | tool_spec/tool_definition + 动态发现 | tool_search 按需取 schema | apply-patch 独立可执行；code-mode JS 编排 |
| DeepSeek Harness | ToolDefinition + 强制 ToolOutputDefinition | **白名单 3 字段**，其余永不泄漏 | canonical 输出 + 纯 render 投影 |

## 共同模式（六家都做的）

1. **两级压缩**：先用零模型成本手段（清/剪工具输出）腾空间，省不够再调模型摘要。
2. **摘要保"用户意图/安全约束"，压"执行过程"**；摘要失败必须降级而非中断。
3. **压缩是带元数据的事件**（边界、前后 token 数、触发原因），可审计可再触发。
4. **工具执行永不抛异常进循环**：一切错误回灌为模型可读、可自纠的结果。
5. **上下文/token 计量覆盖工具入参与 reasoning**，并与 provider 实测 usage 校准。
6. **取消是一等语义**：检查点 + 消息一致性修复（不成对消息清理或"不提交"规则）。
7. **模型可见面最小化**：内部元数据（超时、并发安全、执行函数）永不进模型请求。
8. **会话持久化与恢复**从"能不能做"变成"核心循环的形状"（OpenCode/Codex 最彻底）。

## 对 Memoria（LangGraph + RAG）的推荐迁移清单

按性价比排序（详见各文档第 12/13 节）：

1. Evidence 溯源结构 `{kind, title, excerpt, url}`（OpenMuse）→ 直接落地"回答带来源引用"红线；
2. 两级压缩流水线 + 摘要模板 + 增量合并语义（OpenCode/ZCode）→ 会话上下文管理节点；
3. "保留用户消息、摘要执行区间"的切分（Mini-Agent）→ 问答会话天然匹配；
4. token 计量双通道 + 工具入参/thinking 计入（ZCode/Mini-Agent）→ 压缩触发器；
5. `waiting_approval` 一等状态 + 审批通道与对话隔离（OpenMuse）→ 邮件归档人工确认；
6. durable task 租约/心跳/审计事件（OpenMuse）→ 异步批处理任务；
7. MCP 三超时与工具异常全捕获（Mini-Agent）；
8. token 预算压缩的"前缀后新增"口径（Codex）→ 系统 prompt 较大的场景。

## 研究方法说明

- 全部仓库已浅克隆至 `C:\Users\tom\AppData\Local\Temp\agentresearch\`（约 700MB，可随时删除），文档结论基于源码与官方文档精读，非 README 转述；
- 克隆时间：2026-10-03；各仓库当日 HEAD 状态；
- 每篇文档的"证据索引"表给出结论 → 源码路径映射，便于复核。
