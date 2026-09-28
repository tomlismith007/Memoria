# Memoria — Architecture

## 1. 系统目标

Memoria 是单用户本地知识系统：RAG 管"找得全"，Wiki 管"记得牢"，外加轻量 AI 邮件分类，配合现代化极简前端交互。
建成后做到：任何文档可问（答案句句有出处）、知识越用越厚（问答沉淀回 Wiki）、邮件不错过重要事（验证码/交易永不误归档）。
附带目标：核心检索链路可讲清每一行（~100 行手写核心），适合作为 RAG/LangGraph 实战项目展示。

## 2. 模块划分

### 模块 1：RAG 知识库问答

Flow: 文档上传 → 解析（PDF / Markdown / 网页）→ 切分 → 向量化入库 → 提问 → 混合检索 → 生成带引用的回答。

Required details:
- **来源引用**：每个回答句映射到（文档，段落/chunk，字符偏移量）。
- **增量更新**：删除文档必须删除它的全部向量（无孤儿向量）。

### 模块 2：LLM Wiki（知识复利层）

Karpathy 式三层结构：
- `raw/` — 原始资料，**只读不写**（agent/LLM 永不写入）
- `wiki/` — LLM 生成维护的 Markdown 页面，`[[双向链接]]`、`index.md` 目录、`log.md` 日志
- `schema.md` — 写作规范，给 LLM 读，wiki 页面必须遵守

核心操作（三个）：
- **ingest** — 新资料进来，LLM 读完更新约 10 个相关页面
- **query** — 先读 `index.md` 定位再深入回答
- **lint** — 断链、孤立页、矛盾检测

### 模块 3：AI 邮件分类（轻量）

Flow: Gmail API 拉邮件 → 两级分类：
1. **规则层先行**：验证码 / 交易特征直接放行 —— **永不自动归档（红线）**
2. **LLM 分类**：营销 / 通知 / 待办事项 + 一句话摘要
3. 营销邮件一键归档 —— **人工点确认，不自动执行**

### 模块 4：Web 服务与极简前端 (Web API & UI Dashboard)

FastAPI 后端服务挂载静态前端，提供 RESTful 接口与极致现代感界面：
- **后端 API**：`/api/agent` (自由文本，由图内 router 决定分支), `/api/ask` (混合检索问答), `/api/wiki` (页面及反向链接), `/api/mail` (分拣与归档确认), `/api/ingest` (文件与文本双写), `/api/config/providers*` + `/api/config/models|test` (供应商/模型配置、模型列表拉取与连通性测试；旧的 flat `/api/config` 与 presets 面已于 feat-058 删除——前端零调用)。
  - `web/app.py` 负责路由与图调用；`web/config.py` + `web/config_routes.py` 是模型/供应商配置子系统，两者职责已分开。
- **入口与路由的分工**：结构化端点（`/api/ask`、`/api/ingest`、`/api/mail`）的 URL 已表明意图，故在 invoke 时预设 `intent` 字段，router 节点识别到预设值即跳过 LLM 往返。`/api/agent` 是自由文本入口，**刻意不预设 intent**，由 router 节点调 LLM 决定分支——这是生产环境中唯一真正走通 `add_conditional_edges` 动态路由的路径，使图的路由能力持续被真实流量验证而非仅存在于测试中。
- **前端系统**（React 19 + TypeScript + Tailwind CSS，设计规范详见 [docs/DESIGN.md](DESIGN.md)）：
  - **AskView**：首屏居中搜索框，首条提问后落底吸附；连续追问流、句级溯源切片卡片展开、一键归档至 Wiki。
  - **WikiView**：`index.md` 索引目录树，Markdown 实时渲染与双向 `[[链接]]` 漫游，底部呈现双向反向链接 (Backlinks)。
  - **MailView**：交易/验证码物理级不可归档保护，营销邮件人工确认弹窗 (Confirm Modal)。
  - **IngestView**：PDF/Markdown/TXT 拖拽上传与即时双写反馈。
  - **SettingsModal**：模型参数配置、远端模型列表一键拉取 (Fetch Models)、全链路接口连通性与毫秒级延迟诊断卡片。

## 3. 核心数据流

三条流水线，共用一份输入：

**（1）摄入双写** — 同一份文档进来，两条流水线并行：
`解析 → 切分 → 向量化 → 向量库（给 RAG）`
`LLM 阅读 → 编译 wiki 页 → 更新交叉引用 + index.md + log.md（给 Wiki）`

**（2）查询混合** — 问问题时：
`先读 Wiki（index.md 定位，高精度、有引用、答案稳定）`
`→ Wiki 答不上或要细节 → 向量检索补 raw 原文`
简单事实问 Wiki，开放探索问 RAG。

**（3）沉淀回写（复利）** — 高质量问答归档成 wiki 的 synthesis 页面；
邮件抽出的关键信息（如服务到期日）写进 wiki。知识越用越厚。

## 4. 技术选型与取舍

| 决策点 | 选择 | 理由 / 取舍 |
|---|---|---|
| 编排 | LangGraph（不用 LCEL 单链路） | **项目决策：LangGraph 是正式生产编排器**，Web API 与 CLI 的全部读写路径都经由编译后的图，不存在第二条编排链路。系统是状态机：意图路由、多步 ingest、人工确认节点；LCEL 只适合单链。LLM 节点挂 `RetryPolicy(max_attempts=3)` 重试瞬时网关错误，`confirm_archive` 中断节点不重试 |
| 检索核心 | 自己手写（`rag/retrieve.py`：向量召回 + IDF 加权关键词重排） | 面试能讲清每一行。**LangChain 目前不是依赖**——`pyproject.toml` 只装了 `langgraph`，仓库内无 LangChain 运行时依赖；集成需求出现时再引入。检索质量规则见 §7.6 |
| 向量库 | Chroma（本地，零服务器） | 单机开箱即用；数据量/多租户需求出现再迁 Qdrant。cosine 距离空间，引用信息存于 metadata（`doc_id`/`chunk`/`start`/`end`） |
| LLM / Embedding | 公网 HTTPS/443 的 OpenAI-compatible 接口（`MEMORIA_LLM_*` / `MEMORIA_EMBED_*` / `data/settings.json`） | 统一公网网关配置；不接受 HTTP、本机、内网或非 443 端口。`llm.py` 归一化三种协议（`chat_completions` / `anthropic_messages` / `openai_responses`），保持供应商无关。Anthropic 路径下发前缀缓存标记，其余协议刻意不发（见 §7.2） |
| 出站网络 | 自研 `net.py` 安全层（`safe_request`） | 基于 `http.client` + `ssl` 手写 SSRF 防护：仅 HTTPS/443、拒绝私网 IP、DNS 解析后**锁定 IP 连接并保留 hostname TLS 身份**（堵 DNS 重绑定）、重定向 ≤3 跳、响应体设上限。所有 LLM/Embedding/连通性测试请求必须走这里 |
| Web API 服务 | FastAPI + Uvicorn | 异步高性能、自动生成 OpenAPI 文档、轻量可靠。`config.py` + `config_routes.py` 承载模型与供应商配置子系统（provider/model API，单一配置轨道） |
| 前端工程 | Vite + React 19 + TypeScript 5.7 + Tailwind v3 | 秒级构建、类型安全；圆角卡片 (`rounded-3xl`) 与胶囊按键 (`rounded-full`) 设计系统。**无状态管理库、无 markdown 库、无组件库**——`useState` + 手写 `MarkdownRenderer.tsx` + 7 个自建 UI 基础组件；运行时依赖仅 `react` / `react-dom` / `lucide-react` |
| 邮件接入 | Gmail API + OAuth（本地离线/交互授权生成 token.json） | 最小权限（只读 + 归档写权限）；凭据只放本地密钥文件，永不入库 |
| 文档解析 | pypdf（PDF）/ Markdown 直接读 / 网页抽取 | 够用优先；重型解析（OCR、复杂表格）需求出现再换 |
| 测试 | pytest（182 项，全离线） | `FakeChat` / `FakeEmbedder`（32 维哈希词袋）注入，全套件零网络调用，约 13 秒跑完 |
| Python 环境 | >= 3.11 | 本机 3.14，CI 亦用 3.14；标准库优先，离线单元测试 100% 模拟隔离 |

## 5. 关键约束（红线 — 永不违反）

- 验证码 / 交易邮件永不自动归档；任何归档必须人工确认
- `raw/` 目录只读，LLM/agent 不写入
- 删文档必须同时删其全部向量（无孤儿向量）
- 每个回答句必须可溯源到（文档，段落/chunk，字符偏移量）
- 检索核心自己写，LangChain 只做 connector/loader
- 用 LangGraph 编排，不用 LCEL 单链路
- 所有出站 LLM / Embedding 请求必须走 `net.py` 安全层，不得直接调用 `requests` 或 `urllib`

## 6. 横切关注点：出站网络安全 (net.py)

`net.py` 不属于上述任何一个模块，但被 RAG 嵌入、Wiki 编译、邮件 LLM 分类、设置页连通性测试共同依赖，因此单列。

用户可在设置中自定义公网网关地址，这构成 SSRF 攻击面。`safe_request` 的强制策略：

1. **仅 HTTPS + 443 端口** —— 拒绝 HTTP、本机地址、内网网段
2. **DNS 解析后锁定 IP** —— `_PinnedHTTPSConnection` 连向已校验的 IP，同时保留原始 hostname 作为 TLS SNI/证书校验身份，关闭校验与连接之间的 DNS 重绑定窗口
3. **重定向 ≤ 3 跳**，每跳重新走 IP 校验
4. **响应体上限**（`max_bytes`），防止超大响应耗尽内存
5. 违规一律抛 `SafeRequestError`，不静默降级

新增任何需要访问外部网络的代码路径时，必须复用 `safe_request` 而非自行发请求。

## 7. 横切关注点：LLM 上下文与调用成本

与 `net.py` 同理，这条约束跨越所有模块，因此单列。8 个 `llm.chat()` 调用点分布在 RAG、Wiki、邮件、编排四条路径上，任何一处违反都会推高全局成本。

### 7.1 Prompt 必须「稳定前缀优先」布局

Provider 的前缀缓存只在**字节完全相同**的前缀上命中，因此 prompt 的书写顺序本身是性能约束：

```
[固定 SYSTEM] → [稳定块：仅随页面增删变化] → [变动块：本次输入 / top-K 正文]
```

**违反示例（feat-040 修复前）**：`wiki/ops.py ingest()` 曾把全部页面正文拼在 material 之后，每次 ingest 改一个页面就重写整个 prompt，缓存永不命中。现已改为「稳定页名目录 → material → top-K 选中页正文」。

新增 prompt 时，稳定内容（固定指令、长期不变的目录）必须排在变动内容之前。

### 7.2 显式缓存标记只发给支持它的协议

`llm.py build_chat_request` 仅在 `anthropic_messages` 路径下发 `cache_control: {type: ephemeral}`。

**不得**向 `chat_completions` / `openai_responses` 盲发 `prompt_cache_key`——用户可配置任意公网网关，无法假定其支持该字段，给兼容端发送陌生字段可能导致请求被拒。新增协议前须先确认支持情况。

### 7.3 上下文按 token 预算裁剪，不按轮数

`graph/nodes.py` 的 `KEEP_RECENT_TOKENS = 20_000` 从最新一轮往回累加，超预算即丢最旧。**禁止**改回固定轮数截断（如 `[-6:]`）：中英文混排下 6 轮可能是 3k 也可能是 20k token，无法与 context window 对齐。

字符估算系数 1.5 char/token 取 CJK 保守侧（英文约 4）。升级路径是接 tiktoken，见该处 `ponytail:` 注释。

### 7.4 循环内的 LLM 调用必须折叠

**禁止**在遍历循环里逐个调用 LLM。`graph/nodes.py` 的邮件分拣曾用 `[classify(e, llm) for e in emails]`，N 封邮件 N 次 HTTP 往返；现已改为 `classify_batch()` 单次调用。

折叠调用时**红线判定不得一并折叠**：`is_protected` 仍逐封独立执行，批量只作用于 LLM 分类与摘要那一步。

### 7.5 配置缺失必须早暴露，不能伪装成网络故障

`Settings` 的 `embed_base_url` / `embed_model` / `llm_model` 带有默认值
（`text-embedding-3-small` 等），因此**无法从这些字段区分"用户选的"和"从没配过"**。
真正的信号是 `active_embed_provider_id` / `active_embed_model` 这类空字符串选择器。

由此产生的失真路径（feat-047..049 修复）：

```
未配向量模型 → 默认值兜底 → 指向 api.deepseek.com → 连接超时 180s
            → WinError 10060 → 用户完全不知道该去设置里改什么
```

强制规则：

1. `/api/health` 必须报告 `capabilities.{llm,embed}.ready` 与 `reason`，
   `status` 字段仅表示进程存活，不得代表依赖可用
2. 依赖 `/api/agent`（问答分支）、`/api/ask`、`/api/ingest` 在调用图之前
   校验就绪状态，未就绪时返回**带指引的 502**，不得让请求跑到网络层超时
3. 判定就绪必须校验 API Key 为真实值——`sk-1234567890` 这类设置期占位串
   会被误判为已配置（`_key_is_real`）
4. 前端顶栏状态徽标必须与提示条一致，不得在缺失配置时仍显示"本地就绪"
5. `active_chat_model` 只有指向 active provider 下**真实启用的 chat 模型**才被采信；
   跨类型（如 embedding 模型）或失效的选择器按未配置处理并自动回退
   （`resolve_active_chat_model`）。任何写入 active 选择器的路由必须用
   `pick_model_id` 按类型选取，禁止回退到任意类型模型——该回退曾把真实配置的
   active chat 模型腐化成 embedding 模型（feat-058 修复）

新增依赖 LLM 能力的路径时，一并接入 `capability_status` 判定。

### 7.6 检索质量规则（feat-050..054）

检索质量决定 RAG 的上限。以下四条是硬规则，评测见 `tests/test_rag_eval.py`：

1. **`k` 是召回阶段，`top_n` 才是重排窗口** —— 关键词重排只能重排**已进入候选池**
   的文档。实测 41 份文档、目标埋在第 20 位时，`k=8` **完全召回不到**，
   `k>=15` 命中。当前 `k=30`（延迟 2.35ms → 5.89ms，相对秒级 LLM 往返可忽略）。
   **`top_n=4` 刻意保持不变** —— 它直接决定 LLM 的 token 成本，是另一个权衡。

2. **切分必须落在语义边界** —— 固定窗口会把句子从中间切断，嵌入模型编码的是
   残缺语义。**红线**：切点可以变，偏移语义不能变，必须恒满足
   `chunk.text == source[chunk.start:chunk.end]`。

3. **关键词命中必须按 IDF 加权** —— 字符二元组无法区分跨词碎片（`候需`）与真词
   （`提前`），二者字符层面同构。解法不是过滤而是**加权**：df≈100% 的碎片权重
   趋近下限。`keyword_score(query, text, df=None)` 保留两参签名，缺省退化为原行为。

4. **改动检索必须先有评测** —— `tests/test_rag_eval.py` 是回归守卫。
   当前基线：recall@4 = 3/3，MRR = **1.00**（3 条查询全部首位命中）。
   记录在 `docs/RAG_UPGRADE_PLAN.md`。

**评测语料的规模决定结论的适用范围**：小语料上「k 无影响」并不代表大语料下也无影响。
该教训已由 `test_narrow_recall_window_finds_nothing` 固化。

## 8. 非目标（明确不做）

1. 不做多用户 / 复杂鉴权体系 —— 单用户本地知识系统
2. 不做模型微调 —— 只用现成大模型与通用 Embedding 进行 RAG 与 Wiki 编译
3. 邮件只做分类 + 归档确认 —— 不做自动回复 / 自动发送
4. Wiki 保持 Markdown 纯文件存储为单一事实来源（SSOT）—— 前端为交互投影，不绑定专有数据库
5. 初期单机本地运行 —— 不做分布式 / 高可用部署
6. 检索以中英文为主 —— 不做多语言专项优化
