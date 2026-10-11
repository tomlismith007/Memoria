# Hermes Agent 核心设计 · 00 总览

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时，MIT，Python 3.14 + Node
> HEAD：`97a9ae8e`（main，2026-10-11 本地浅克隆，18,220 文件 / 8,399 个 .py）
> 本篇是系列总览：跨维度共同模式、在既有 6 家研究中的定位、对 Memoria 的优先级迁移清单。
> 各维度结论的证据均在其对应文档内，本篇不重复给行号。

## 1. 系列导航

| 文档 | 维度 | 核心源文件 | 一句话核心设计 |
|---|---|---|---|
| [01-agent-loop.md](01-agent-loop.md) | Agent 主循环 | `agent/conversation_loop.py` | 瘦 while + 十余个纯函数 phase；持久 transcript 与 api 发送副本物理分离（api_content sidecar）保前缀缓存字节级稳定 |
| [02-memory.md](02-memory.md) | 记忆系统 | `hermes_state.py` + 34 个 `hermes_state_*.py` | 有界策展记忆（MEMORY.md 2200 字符冻结快照 + 超限逼模型原子整理）+ FTS5 三索引跨会话召回 + fail-open 纪律 |
| [03-self-improvement.md](03-self-improvement.md) | 自改进 | `agent/skill_*.py`、`background_review.py` | 每轮按工具迭代数 fork 后台 review agent，在白名单+read-before-write 护栏下直接写 skill 与记忆 |
| [04-gateway.md](04-gateway.md) | Gateway | `gateway/`（单进程， Telegram/Discord/Slack/WhatsApp/Signal/Email） | 网关与 agent 同进程直调；三层并发闸门 + fail-closed 租约；防重复发送工程化为对账状态机 |
| [05-tools.md](05-tools.md) | 工具系统 | `tools/`、`toolsets.py`、`mcp_serve.py` | 可见面是投影不是注册（toolset 选择 + TTL 过滤 + schema rewriter）；执行单条管线；输出治理靠截断+落盘句柄 |
| [06-persona.md](06-persona.md) | 人格设计 | `SOUL.md`、`agent/system_prompt.py`、`prompt_builder.py` | 人格是分层槽位：SOUL.md 进 stable 层，/personality 走 ephemeral 旁路；人格文件排除在模型可写面之外 |
| [07-scheduling.md](07-scheduling.md) | 调度 | `cron/`（job/occurrence/scheduler_*） | 分发前推进 next_run_at + CAS 认领 + 投递台账 = 完整 at-most-once；每次触发是一次独立 agent 会话 |
| [08-security.md](08-security.md) | 安全与审批 | `tools/approval*.py`（9 模块）、`SECURITY.md` | "对抗 LLM 的唯一边界是 OS"；不可绕 floor（先于 bypass）→ allowlist → 正则检测 → guardian LLM → 人 → 持久化决定 |

## 2. 跨维度共同模式

这 8 个维度不是 8 套独立技术，反复出现的是同一批底层决策：

1. **前缀缓存是一等公民，凌驾于很多"顺手"设计之上。** system prompt 每会话冻结（06）、记忆快照加载时冻结、中途写盘本会话不生效（02）、临时注入全挂 api_content sidecar 不动历史行（01）、fork 的 review agent 逐字节继承父会话 prompt/tools 以保缓存平价（03）。凡是"会变的东西"都被推到前缀之后或 sidecar 里。
2. **持久化先于执行，对账先于重发。** 工具执行前先落 transcript（01）、cron 分发前推进 next_run_at + CAS 认领（07）、投递四态台账"attempting 崩溃必须带恢复标记，从不静默重发"（04/07）。崩溃恢复不靠内存。
3. **模型可见面最小化。** 不在场的工具名字永远不进请求（05）、人格文件排除在模型可写面之外（06）、内部元数据不进 prompt。与既有研究里 ZCode 的"registry.toContracts()"、DeepSeek Harness 的"白名单 3 字段"同一条规律。
4. **fail-open 与 fail-closed 按领域定向。** 检索（FTS5）损坏时摘触发器保写入、LIKE 兜底（02）——可用性优先；安全审批的 floor 不可绕、cron 无人值守表面默认 deny（08）——确定性优先。方向错了比缺功能更糟。
5. **护栏做在能力层，不做在提示词层。** review fork 只拿到白名单工具（03）、审批 floor 是代码而非 prompt（08）、危险命令 11 条 hardline 先于一切 bypass 模式（08）。SECURITY.md 原文：进程内一切启发式都不是边界，唯一边界是 OS。
6. **工程复杂度都来自同一个根因：多进程/多平台共享单一状态。** 34 个 state 模块（WAL/readpool/lockguard/repair）、网关租约按解析后 session_id 串行化、cron 所有权 CAS——单人单机用不到这个规模，但每个模块对应一类**真实事故**，读的时候看事故类型比看代码更有价值（02）。

## 3. 在既有 6 家研究中的定位

对照本目录 `../README.md` 的六家横向对比：

- **循环**：hermes 的"瘦 while + phase 函数 + dataclass verdict"与 ZCode 的"显式状态机"是两个极端，但都比 Mini-Agent 的裸 while 工程化；对单人项目，hermes 的形态更容易局部读懂。
- **压缩**：hermes 与 ZCode/OpenCode 同属"真实 usage 锚定 + 多触发点"流派（01/02），验证了既有研究的共同模式 1（两级压缩）；它的特色是压缩触发点内嵌在循环 phase 里而非独立服务。
- **记忆**：六家里只有 OpenMuse 有"记忆 editable/forgettable"；hermes 的"有界策展 + 逼模型自己整理 + 每 10 轮后台 review"是目前研究中**最完整的个人记忆机制**，这是它区别于 coding harness 的核心。
- **自改进**：六家均无；hermes 的 background_review fork + skill 写盘是独有维度，也是"个人 agent 长出来"的机制核心（03）。
- **网关/调度**：六家均无（ZCode 是 IDE harness，不需要 IM 入口）；hermes 在这两块的工程密度（对账状态机、at-most-once）接近生产消息系统。

## 4. 对 Memoria 的优先级迁移清单

按性价比排序（落点文档标注在括号内）：

1. **红线落地方式升级（08）**：把"验证码/交易永不自动归档"从节点内 if 判断升级为"先于一切 bypass 的静态 floor"（不可被任何模式/配置关闭），分类 LLM 改三值输出（APPROVE/DENY/ESCALATE，不确定一律 interrupt）。这是现有红线防御的加固，不是新功能。
2. **MCP server 形态（05）**：`mcp_serve.py` 的 `@server.tool()` + docstring 即 schema 是 Memoria 暴露 `memoria_ask/ingest/wiki_fact` 的直接模板；照抄其可见面最小化纪律（只暴露 4 个工具，删除/归档/raw 写不出现）。
3. **记忆分工协议（02/03）**：hermes 侧用 MEMORY.md 有界策展模式；Memoria 保持 wiki+RAG 引用型知识 SSOT。两侧只通工具不通存储——具体机制见 02 的"冻结快照 + 原子 batch 整理"。
4. **定时任务（07）**：若给 Memoria 加邮件定时分拣，直接采用其 at-most-once 三件套（分发前推进时间戳 + CAS 认领 + 投递台账）；其 blueprint 里"重要邮件监控"与 Memoria 邮件分拣同构，可抄产品形态。
5. **工具结果三层防溢出（01/05）**：cap → 超窗 spill 落盘给 `full_output_path` 让模型翻读 → turn 聚合预算。Memoria 的检索结果注入 prompt 前值得加这层（目前只有 top_n=4 的数量控制）。
6. **api_content sidecar（01）**：Memoria 已做前缀缓存调优（feat-040/041/064），sidecar 模式（临时注入不污染历史行）是下一步把缓存命中率做稳的结构保证。
7. **人格槽位（06）**：SOUL.md stable 层 + ephemeral 旁路的分层值得个人 agent 采纳；Memoria 本体不需要。

**明确不搬**：34 个 state 模块的多进程可靠性军备库（单人单机过度工程，02 已论证）、1572 行 shell 正则变体库（08，guardian LLM + floor 已覆盖主要风险）、网关对账状态机的全部复杂度（只有多平台并发才需要）、browser 工具族（超出知识系统范围）、RL 训练闭环（运行时只是导出轨迹，离线训练不是个人项目该背的）。

## 5. 方法说明

- 与既有 6 篇同源同法：全部结论基于本地浅克隆源码精读（非 README 转述），每篇附证据索引（结论 → 源码文件:行）；
- 克隆时间 2026-10-11，HEAD `97a9ae8e`；克隆位置 `C:\Users\tom\AppData\Local\Temp\agentresearch\hermes-agent`（与既有 6 仓同目录）；
- 6 个研究代理并行完成，各维度文档 220-262 行；本总览由横读各篇摘要与正文标题写成，转引结论请以对应维度文档的证据索引为准。
