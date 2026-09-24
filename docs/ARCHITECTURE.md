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
- **后端 API**：`/api/ask` (混合检索问答), `/api/wiki` (页面及反向链接), `/api/mail` (分拣与归档确认), `/api/ingest` (文件与文本双写), `/api/config` (模型参数、模型列表拉取与连通性测试)。
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
| 编排 | LangGraph（不用 LCEL 单链路） | 系统是状态机：意图路由、多步 ingest、人工确认节点；LCEL 只适合单链 |
| 检索核心 | 自己手写（向量检索+重排+生成 ~100 行） | 面试能讲清每一行；LangChain 只用 integrations（向量库连接器、文档加载器） |
| 向量库 | Chroma（本地，零服务器） | 单机开箱即用；数据量/多租户需求出现再迁 Qdrant |
| LLM / Embedding | 公网 HTTPS/443 的 OpenAI-compatible 接口（`MEMORIA_LLM_*` / `MEMORIA_EMBED_*` / `data/settings.json`） | 统一公网网关配置；不接受 HTTP、本机、内网或非 443 端口 |
| Web API 服务 | FastAPI + Uvicorn | 异步高性能、自动生成 OpenAPI 文档、轻量可靠 |
| 前端工程 | Vite + React 19 + TypeScript + Tailwind CSS | 秒级构建、类型安全；圆角卡片 (`rounded-3xl`) 与胶囊按键 (`rounded-full`) 设计系统 |
| 邮件接入 | Gmail API + OAuth（本地离线/交互授权生成 token.json） | 最小权限（只读 + 归档写权限）；凭据只放本地密钥文件，永不入库 |
| 文档解析 | pypdf（PDF）/ Markdown 直接读 / 网页抽取 | 够用优先；重型解析（OCR、复杂表格）需求出现再换 |
| Python 环境 | >= 3.11 | 本机 3.14；标准库优先，离线单元测试 100% 模拟隔离 |

## 5. 关键约束（红线 — 永不违反）

- 验证码 / 交易邮件永不自动归档；任何归档必须人工确认
- `raw/` 目录只读，LLM/agent 不写入
- 删文档必须同时删其全部向量（无孤儿向量）
- 每个回答句必须可溯源到（文档，段落/chunk，字符偏移量）
- 检索核心自己写，LangChain 只做 connector/loader
- 用 LangGraph 编排，不用 LCEL 单链路

## 6. 非目标（明确不做）

1. 不做多用户 / 复杂鉴权体系 —— 单用户本地知识系统
2. 不做模型微调 —— 只用现成大模型与通用 Embedding 进行 RAG 与 Wiki 编译
3. 邮件只做分类 + 归档确认 —— 不做自动回复 / 自动发送
4. Wiki 保持 Markdown 纯文件存储为单一事实来源（SSOT）—— 前端为交互投影，不绑定专有数据库
5. 初期单机本地运行 —— 不做分布式 / 高可用部署
6. 检索以中英文为主 —— 不做多语言专项优化
