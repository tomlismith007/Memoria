# Memoria 个人 Agent 升级设计指南

> 依据：[agent-architecture/04b-openmuse-alpha-surfaces.md](agent-architecture/04b-openmuse-alpha-surfaces.md)（OpenMuse 全表面深读，下称 **04b**）与 [agent-architecture/hermes/00-overview.md](agent-architecture/hermes/00-overview.md)（hermes-agent 八维度深读，下称 **hermes/N**），全部机制结论的行号证据在对应研究文档内，本指南只引章节不重复取证。
> 基线：2026-10-12，196 tests green，feat-001..065 完成（038/039 todo，046 wont-fix）。
> 本文是设计文档不是实施记录；立项与否见 §6 建议清单，未经确认不动 feature_list.json。

## 0. 决策记录（grilling 澄清结论，2026-10-12）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 基座定位 | **Memoria 本体升级为准个人 agent**（LangGraph 保持生产编排器）；hermes 不做基座，两份 hermes 研究降为"模式参考库" |
| D2 | 审批形态 | 采纳 OpenMuse 审批实体化：ActionProposal{hash+30min 过期+单次消费+独立端点}，列为 **P0** |
| D3 | 入口（v1） | 仅 Web，桌面/移动 UI 兼容（feat-020 响应式底子延续维护） |
| D4 | 文档纪律 | 最小包采纳：VERIFICATION.md + limitation 字段 + 红线三处同文 + 计划文档免责句 |
| D5 | 新硬边界 | 能力不暴露 / 审批与对话通道永久分离 / 结果未知不假装成功（§4.2） |
| D6 | 任务引擎 v1 | 最小持久任务引擎，**唯一 kind：邮件定时分拣**；kind 枚举预留但不预建空壳 |
| D7 | 提案覆盖集 | 归档确认 + 文档删除 + 向量重建，三类破坏性/外部动作统一走提案 |
| D8 | 记忆层 | 最小记忆层：有界条数、可编辑可遗忘、无后台 nudge |
| D9 | 范围裁剪 | v1 不建 skill/自改进体系；MCP server 缓做（等第二消费方） |
| D10 | 对话流 | SSE + ConversationQueue 语义列 **P1**（紧随任务引擎） |
| D11 | 邮件通电 | 生产接入真实 Gmail 列 **P1 第一位**（P0 审批实体化的验收依赖它） |
| D12 | 交付形态 | 本指南一份 + §6 建议立项清单；feature_list.json 待审后另批更新 |

## 1. 现状与差距

### 1.1 复用资产（不动）

LangGraph 编排（全读写路径经图）、手写检索核心（recall@4=3/3，MRR=1.00）、wiki Markdown SSOT、Chroma 向量库、`net.py` SSRF 安全层、`config.py/config_routes.py` 供应商子系统、React 前端与响应式布局（feat-020）、SqliteSaver 会话记忆（KEEP_RECENT_TOKENS 预算）。

### 1.2 差距清单（每条标注研究证据）

| # | 差距 | 证据 | 严重度 |
|---|---|---|---|
| G1 | **审批与对话同通道**：邮件归档确认走图内 interrupt + `/api/mail/archive` 的 `Command(resume)`，与聊天 invoke 共用 Web 通道——被注入的邮件正文理论上可诱导"在对话里点头" | 04b §11.3（OpenMuse 的八层结构强制 vs 我们的一层） | 🔴 P0 |
| G2 | **邮件生产不通电**：`create_app` 的 `mail_service` 恒为 None，MailView 永远空列表，`fetch_messages` 仅测试可达 | 本仓 2026-10-11 审查；feat 列表 | 🔴 P1 |
| G3 | **无持久任务引擎**：SqliteSaver 只解决"图状态存下来"，不解决"谁来跑、跑多久、崩了谁接手"；定时分拣无处安放 | 04b §3.2（单表 CAS 租约配方） | 🔴 P1 |
| G4 | **破坏性动作无提案语义**：文档删除/重建索引只有一次性 UI 确认，无 hash 绑定、无单次消费、无过期 | 04b §11.1-11.2 | 🔴 P0（与 G1 同批解决） |
| G5 | **写操作无 outcome_unknown 态**：归档执行遇结果未知（网络断/超时）无独立语义，重试可能重复处理验证码类邮件 | 04b §8.3（OutcomeUnknownError 四层防御） | 🟠 P0 |
| G6 | **无 agent 记忆层**：用户偏好/习惯类事实无家可归（wiki 是引用型知识，对话历史会过期） | 04b §9.1（三字段 editable/forgettable 配方） | 🟠 P1 |
| G7 | **对话无流式无队列**：feat-039 todo；发送时禁输入、无 follow-up 语义、失败隐式重发风险 | 04b §1.2（ConversationQueue 52 行配方） | 🟠 P1 |
| G8 | **文档纪律缺口**：feature_list evidence 只记"过了什么"不记"没覆盖什么"，无日期会过时，红线只在 AGENTS.md 单处存在 | 04b §12.6-12.7（VERIFICATION 咬合链） | 🟠 P0（成本最低） |
| G9 | **Gmail token 明文**：token.json 本地明文，无加密、无刷新去重、无 generation 失效 | 04b §8.1（encryptSecret fail-closed 配方） | 🟡 随 G2 一并做 |
| G10 | **PDF 入库无消毒无 receipt**：解析无魔数/加密检查，无"解析到一半"的可见性 | 04b §6.3（enforced vs instructed 分级方法） | 🟡 随引擎顺带 |

## 2. 目标架构

```
Web UI（桌面 + 移动响应式，feat-020 底子）
  │ REST + SSE（P1）
  ▼
FastAPI（web/app.py + config_routes.py + [新] proposals 路由）
  │ 认证端点二分：对话/查询走 invoke；破坏性动作只走 /api/proposals/{id}/decide
  ▼
LangGraph（生产编排器，红线不变）
  ├─ qa：wiki-first + RAG fallback，句句带引用；[新] 注入记忆层（"data only"+untrusted 免责同句）
  ├─ mail_triage → confirm 节点：[改] interrupt 载荷分型 {type:"approval", proposal_id} / {type:"input",...}
  ├─ ingest：双写（向量 + wiki）
  ├─ [新] tasks worker（进程内 tick）：records 单表 CAS 租约，kind:"mail_triage" 定时拉信→分类→生成提案
  └─ confirm 白名单复查保留（纵深第二层，不因提案而删）
存储：
  data/memoria.db（[新] 单表 records(kind,id,data jsonb/json)：task/proposal/memory/notification）
  data/chroma + data/wiki（不变）+ data/settings.json（不变）
  data/checkpoints.sqlite（LangGraph 会话，不变）
```

**两条架构主轴**（来自两家的共同纪律，04b §13.1 / hermes/00 §2）：

1. **单表 + CAS**：任务、提案、记忆、通知都是 `records` 表的行；一切并发正确性靠"把读到的前提放进 UPDATE 的 WHERE"（SQLite 用 `json_extract` 条件更新等价实现 jsonb 包含匹配）。不引入 Celery/Redis/消息队列。
2. **恢复 = 重放 + 幂等闸**：不做精确断点续跑；任务 state 里缓存已完成的工具结果，重跑命中即跳过外部副作用；已批准动作有 actionId 式重放检查，绝不重复执行。

## 3. 分阶段路线

### P0 — 安全地基（先于一切功能）

#### P0.1 提案审批子系统（对应 G1/G4/G5）

**做什么**：新增 `memoria/proposals.py` + records 表 kind:`proposal`，字段对齐 OpenMuse ActionProposal（04b §11.1）：`{id, kind: archive|delete_doc|reindex, payload(精确草案), content_hash, expires_at(30 分钟), status: awaiting_review|executing|succeeded|failed|outcome_unknown|denied|cancelled|expired, result?, error?}`。

- **覆盖三类动作**（D7）：归档邮件（payload=邮件快照+目标分类）、删除文档（payload=doc_id+将删向量数+raw 文件名）、重建索引（payload=影响文档数+当前向量维度）。
- **独立端点**：`POST /api/proposals/{id}/decide`（body 带 `hash` + `decision`）——与对话/聊天通道物理分离；decide 六道闸照抄 04b §11.2 第 7 步（hash 校验→幂等返回→状态合法性→过期 CAS→归属校验→单条 SQL 原子 claim）。
- **outcome_unknown**：执行层把"网络错误但结果未知"与"确定失败"分开（Gmail API 超时 ≠ 归档失败）；outcome_unknown 禁止重试，UI 提示人工核对（04b §8.3 配方）。
- **级联失效**：会话/任务 cancel 自动 deny 未决提案；后台清算过期提案（mail_triage worker tick 顺带，不另起定时器）。
- **前端**：AskView/MailView 之外的"待办审批"入口（顶栏徽标计数），审批页逐字段展示"将被执行的确切内容 + 过期时间 + 'Your approval applies only to the details shown above'"；提交必须回传 hash。

**怎么与 LangGraph 衔接**（关键设计）：
- `confirm_archive` 节点保留白名单复查（纵深第二层），但 interrupt 载荷改为 `{type:"approval", proposal_id}`；
- `/api/mail/archive` 不再直接 `Command(resume)`——改为创建提案；
- decide 成功后由**服务端 decide 路径**发出 `Command(resume={proposal_id, decision})`，前端与对话通道均无 resume 能力；
- interrupt 载荷分型（D2）：`approval` 型只能由 decide 端点解除，`input` 型走表单答案（为 P1 记忆层/document 式缺字段复用预留）。

**验收**（按 §3.4 VERIFICATION 模板写）：双击 decide 只成功一次；hash 不符 409；过期提案 decide 被拒且转 expired；执行中断电重启后提案转 outcome_unknown 而非假装成功；对话通道（/api/ask、/api/agent）无任何可达的归档执行路径（测试断言工具面/路由面 grep）。

#### P0.2 文档纪律最小包（对应 G8，D4）

1. 新建 `docs/VERIFICATION.md`：日期头+免责句、Automated checks（具体数字+明记未跑项）、Feature acceptance matrix（Area|Evidence|**Boundary** 必填）、Reproduce 命令块、Still outside this release——模板字段照抄 04b §12.7。
2. `feature_list.json` 每条 completed 特征补 `limitation` 字段（"已实现但有边界"第三态；存量特征按当前认知补，新特征完成时必填）。
3. **红线三处同文**：`is_protected`/归档禁令落到 ① 分类 prompt 合同（"受保护类邮件不是归档许可"）② MailView 确认 UI 文案（验证码/交易类禁用按钮并显示原因）③ ARCHITECTURE.md（已有）——改一处必须改三处，写进 AGENTS.md 的 Change Discipline。
4. `docs/RAG_UPGRADE_PLAN.md` 头部加"Planned extensions are not claims of current support"免责句。

### P1 — 引擎与通电

#### P1.1 最小持久任务引擎（对应 G3，D6）

**做什么**：`memoria/tasks/`（engine.py + models.py），records 表 kind:`task`；worker 为 FastAPI 进程内线程（tick 1s），参数对齐 OpenMuse（04b §3.2）：租期 60s、心跳 20s（`max(10, leaseMs/3)`）、过期 running 重认领、`attempts` 递增、优雅停机 abort 后任务回 queued。

- **唯一 kind：`mail_triage`**（D6）——定时拉 Gmail → `classify_batch`（红线：is_protected 仍逐封独立执行，批量只折叠 LLM 调用）→ 受保护类直接放行显示 → 营销/通知类生成**归档提案**（不执行）→ 通知（幂等 key）。执行间隔用户可配（settings，默认 30 分钟）。
- **kind 枚举预留**：`Monitor`/`digest` 只在类型定义里留位，不写任何实现（D6 防空壳）。
- **恢复=重放**：任务 state 缓存"本批已处理 msg_id→分类结果"，重跑先查缓存；分发前推进 `next_run_at` + CAS 认领防重复分发（04b §13.1 纪律 2）。
- **通知收件箱**（P1.1 顺带，records kind:`notification`）：幂等 key（`task-error:{id}:{attempts}` 式）、append-only、只能标读不能清除（04b §9.3）——前端顶栏徽标与 P0.1 审批入口共用。

**不做**：分布式 worker、消息队列、websocket 推送（单人系统 1s tick + 轮询足够，04b §3 落点 5）。

#### P1.2 邮件生产通电（对应 G2/G9，D11）

- `create_app()` 启动时若 `token.json` 存在 → `get_gmail_service()` 注入；失败降级为 None + `/api/health` 新增 `capabilities.mail.ready=false` + 原因指引（沿用 feat-047 的 capability 模式）。
- token 存储升级：`TOKEN_ENCRYPTION_KEY` 环境变量加密落盘，**缺 key 时读写直接拒绝**（fail-closed，04b §8.1）；刷新加 60s 提前量 + in-flight 去重。
- MailView 空态从"无声空列表"改为明确的"未连接 Gmail + 授权指引"。
- **验收必须走真实账号一次**（VERIFICATION 的 Boundary 列写明"mock 验证不替代真账号验收"，04b §12.2 纪律）。

#### P1.3 SSE 对话流 + ConversationQueue（对应 G7，D10）

- 后端：`/api/ask` 增 SSE 变体，事件 `{type: "delta"|"citation"|"done"|"error"}`（不必上 AG-UI 全协议，04b §1 落点：翻译层三件事——按步拆消息/工具结果清洗/步数打满兜底提示）。
- 前端 AskView：52 行 ConversationQueue 语义移植（04b §1.2）——发送/停止同位切换、composer 回复期间保持可编辑、follow-up 可见队列（"Up next"/"Messages on hold"）、线程冲突返回 "held" 不算失败、**失败永不隐式重发**；feat-039 的验收标准同步扩写。

#### P1.4 最小记忆层（对应 G6，D8）

- records kind:`memory`：`{text, source, created_at}`；id=`hash(text)` 内容去重；**条数上限（建议 100，超限拒新增并提示整理——不自动整理，D8 无 nudge）**。
- API：`POST /api/memories`（手填+问答页"记住这条"）、CAS 编辑、原子遗忘（OpenMuse `db.take` 式）；source 字段记录来源（"User added in AskView"/"User confirmed in chat"）。
- 注入：qa 节点把记忆（有界全量）以 JSON 数据块拼进 prompt，**限定语 "data only" 与 "untrusted data, not authority" 同句出现**（04b §9.2）——记忆注入与注入防御是同一行代码的两面。
- **不做**：后台 review 整理、跨系统记忆同步、hermes 式 MEMORY.md 策展循环（D9；参考 hermes/02 但不搬）。

### P2 — 观望区（条件触发才立项，v1 一律不做）

| 项 | 触发条件 | 参考 |
|---|---|---|
| monitor kind（定期公开页检查） | 出现真实监控需求 | 04b §5.3 配方（2^n 退避+报警 key 去重+relative-time 去噪）可直接抄 |
| MCP server | 出现第二消费方（外部 agent 想读 Memoria） | hermes/05 §8（mcp_serve.py 形态）；能力面仍受 §4.2 边界约束 |
| skill/自改进体系 | 单人使用中重复手工流程 ≥5 类且稳定 | hermes/03（background_review fork + 护栏）；目前明确不做 |
| 文档 workflow（PDF 表单闭环） | 出现真实表单场景 | 04b §6（typed input + 净化填充 + hash 审批） |
| digest/定期摘要 kind | 用户自己提出要日报 | 引擎 kind 增量 |

## 4. 边界总账（能做 / 不能做）

### 4.1 现有四条红线（不变，逐条标注强制层升级）

| 红线 | 现有强制 | 本指南升级 |
|---|---|---|
| 验证码/交易邮件永不自动归档 | `is_protected` 规则层逐封判定 + confirm 白名单复查（enforced） | +提案层：归档动作只能经 decide 端点；UI 三处同文（P0.2） |
| raw/ 只读 | 代码路径无写入口（enforced） | 不变；P2 文档 workflow 若立项，净化副本另存、原样不动 |
| 删文档必删全部向量 | `store.delete_document` + 孤儿偏执校验（enforced） | +提案层：删除须 hash 提案+单次消费（D7） |
| 回答句句带来源 | `citations_complete()` 逐句校验（enforced） | +Evidence 结构统一 `{kind,title,excerpt,url}`（P1 起新代码一律用它） |

### 4.2 三条新硬边界（D5，全部 enforced 层落地）

1. **能力不暴露原则**：任何自动执行体（图内节点、worker、未来 MCP 工具）的可用动作集合里，**不存在**"删除文档/执行归档/写 raw/ 的直接路径"——危险动作只能"生成提案"。边界做在能力层（工具面/路由面缺口），绝不依赖提示词请求模型"别这么做"（04b §11.3；hermes/08 的 floor 思想：拿不到的能力就是不存在的能力）。
2. **审批与对话通道永久分离**：结构化偏好选择（JEV 式面板）可进对话；**副作用确认（归档/删除/重建）只能走独立 decide 端点**，对话消息、工具参数、SSE 事件里没有可达的批准路径（04b §11.3 的九层结构，测试断言锁定）。
3. **结果未知不假装成功**：所有外部写操作三态 `succeeded / failed / outcome_unknown`；outcome_unknown 禁自动重试，必须人工核对后闭环（04b §8.3）——这是"验证码邮件不被重复处理"的前提。

### 4.3 enforced vs instructed 分级（新增约束时必填）

每条新约束必须声明强度并在文档明示（方法学来自 04b §2.6/§8）：
- **enforced**（代码强制）：容器/SQL/路由层不可绕过——net.py SSRF、提案 decide 闸、is_protected 判定、能力面缺口；
- **instructed**（prompt 纪律）：辅助层，必须同时在 VERIFICATION 的 Boundary 列声明"仅 instruction"——如"引用必须是检索结果原文"这类语义级要求。
- 反模式：把 enforced 的事写进 prompt（冗余无害但别只写 prompt）；把 instructed 的事当 enforced 宣传（OpenMuse 的 desktop 教训）。

### 4.4 v1 明确不做（D9 + 非目标不变）

不建 skill/自改进体系（LangGraph 节点即能力）；MCP server 缓做；不引入 hermes/OpenMuse/CopilotKit 任何运行时依赖（只抄模式）；不做多用户/鉴权扩展（单用户本地不变，API 仍只绑 127.0.0.1）；不做模型微调；不做邮件自动回复/发送；不做移动原生 App（响应式 Web 覆盖）；monitor/digest 等 kind 不预建；不加 websocket 长连接。

## 5. 引用索引

| 主题 | 出处 |
|---|---|
| 任务引擎配方（租约/心跳/恢复=重放/通知幂等） | 04b §3（行号证据在其证据索引表） |
| 提案审批八层结构 / 防注入条款全集 / JEV 面板 | 04b §11 |
| outcome_unknown 四层防御 / OAuth 加密与刷新 | 04b §8 |
| ConversationQueue / SSE 翻译层 / 内联卡存引用现取值 | 04b §1 |
| 记忆三字段 editable/forgettable / 注入与免责同句 | 04b §9 |
| monitor 退避与去噪 / Ideas 已处理集排除 | 04b §5、§4 |
| VERIFICATION 咬合链 / 文档规范七条 / 三处同文 | 04b §12 |
| 前缀缓存纪律（会话冻结快照、sidecar、恢复不破缓存） | hermes/01、hermes/02 |
| 审批 floor 思想（能力不暴露的哲学来源） | hermes/08 |
| 通知 append-only / 网关 turn 租约（P2 若做 IM 入口再取） | hermes/04 |
| enforced vs instructed 分级方法学 | 04b §2.6、§8 |

## 6. 立项清单（**已立项并全部完成**——066/067/068/069/071 已写入 feature_list.json 且 completed；070 未另立新号，改为扩 feat-039 范围后完成）

| 编号 | 阶段 | 名称 | 依赖 | 状态 |
|---|---|---|---|---|
| feat-066 | P0 | 提案审批子系统（archive/delete_doc/reindex 三 kind + decide 端点 + interrupt 分型） | 无 | completed |
| feat-067 | P0 | 文档纪律最小包（VERIFICATION.md + limitation 字段 + 红线三处同文 + 免责句） | 无 | completed |
| feat-068 | P1 | 最小持久任务引擎 + mail_triage kind + 通知收件箱 | feat-066、069 | completed |
| feat-069 | P1 | 邮件生产通电（get_gmail_service 接入 + token 加密 + health capability） | 无 | completed |
| feat-070 | P1 | SSE 流式 + ConversationQueue（**改造既有 feat-039 的范围**，不另立新号） | 无 | completed（并入 feat-039） |
| feat-071 | P1 | 最小记忆层（三字段 + API + qa 注入） | 无 | completed |

落地顺序（实际执行）：066/067 并行先行；069 完成后 068 接上；039 扩范围与 071 殿后。六项验收证据见 `docs/VERIFICATION.md` 矩阵与 `feature_list.json` 的 evidence 字段。

## 7. 第二轮：上下文内核强化（2026-10-12，已完成）

第一轮（P0/P1）解决了**安全地基与通电**；第二轮转向**上下文内核**——prompt 里装什么、装多少、超了怎么办、花在哪。

### 7.1 决策记录（grilling 澄清结论）

| # | 决策 | 结论 |
|---|---|---|
| K1 | 范围 | 只做"上下文内核"（预算统一 + 两级压缩 + 计量）与 prompt 面收敛；运行时观测/工具面/子代理**不在本轮** |
| K2 | 硬边界 | ≤3 feature、零新依赖、**不动图拓扑**、不动前端、**prompt 稳定前缀布局冻结** |
| K3 | 落点 | 新建叶子模块 `memoria/context.py`（`wiki` 不得反向依赖 `graph`）；计量用 `ChatLLM` 装饰器而非改 9 个调用点 |
| K4 | 压缩形态 | 第一级零成本裁注入块；第二级超阈值才摘要并**写回 state.history**；失败一律降级为丢弃 |
| K5 | 验收 | 离线回归测试 + 计数器可断言；真模型压缩质量对比如实写进 VERIFICATION Boundary |

### 7.2 落地清单

| 编号 | 名称 | 依赖 | 状态 |
|---|---|---|---|
| feat-075 | prompt 面收敛（9 条 system prompt 具名 + AST 禁止内联 + 字节锁定） | 无 | completed |
| feat-073 | 统一上下文预算（`context.py`）+ 计量（`CountingLLM`） | 无 | completed |
| feat-074 | 两级压缩（闸门 512 token，摘要写回 state.history） | feat-073 | completed |

三项合计 **+39 tests**（238 → 277）；浏览器验收轮次另 +2（feat-076 测试隔离），当前基线 **279**，无新增依赖，图拓扑未变（仍为单遍 DAG）。机制细节与两条硬约束（闸门只数新淘汰内容、压缩失败必须降级）记在 `docs/ARCHITECTURE.md §7.7`。

### 7.3 本轮明确不做（复核研究文档后的取舍）

| 候选 | 来源 | 不做的理由 |
|---|---|---|
| 结构化 run 事件 / 落库计量 | talorys/06 §5 六计数器 | 无多进程、无长时任务，当前无消费者；计数器进程内 + 三处外露已够 |
| 调度 onStart 对账 + 补跑 | talorys/05 §3.4 | 单 pending 任务引擎刚落地，对账收益要等真实漏跑证据 |
| 工具面契约（ToolResult / 未知工具兜底） | 02-minimax §10、06-dsh §6 | Memoria 无 LLM 工具面，这是"扩能力"不是"强化内核" |
| 审批结局注记回灌历史 | talorys/01 §9 | 提案制已落地，但把结局注记进 prompt 属行为变更，需独立验收 |
| 记忆自动整理 / 巩固循环 | hermes/02 §3 | 自动写长期状态是信任面变更，需独立可见性设计 |
| 三层召回地板（阈值纪律） | talorys/03 §8 | 是检索质量方向（另一条线），且数字必须用 Memoria 自己的 embedding 重标定 |

---

*本指南自身遵守 P0.2 纪律：以上全部为设计意图（planned extensions），不是当前已实现能力的声明；实现以 feature_list.json 立项后的 evidence 为准。*
