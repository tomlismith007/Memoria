# Memoria — 个人智能知识库与知识复利系统

> **RAG 管「找得全」，Wiki 管「记得牢」，邮件分拣管「不错漏」，LangGraph 编排状态机，极简胶囊圆角 Web 交互。**

---

## 🌟 核心理念与架构特点

Memoria 是一套专为个人打造的本地智能知识管理系统，解决传统 RAG 知识库「答案零散、不可溯源、越用越散」与笔记软件「整理成本高、不能自主沉淀」的痛点：

1. **自研检索层（不依赖检索框架）**：向量召回由 Chroma 承担，其上的关键词重排、IDF 混合打分与来源引用映射全部手写在 `src/memoria/rag/`（`retrieve.py` / `answer.py`），逻辑透明可逐行讲清；仓库内无 LangChain / LlamaIndex 等检索框架依赖。
2. **知识复利循环（Dual-Write & Self-Compiling Wiki）**：
   - 摄入资料时，一边切片存入本地 Chroma 向量库，一边由 LLM 编译为具备 `[[双向链接]]` 的 Wiki 词条网络。
   - 高质量问答一键归档为 synthesis 页面，知识越用越厚。
3. **安全邮件分拣中心（Mail Triage with Hard Invariants）**：
   - 规则层优先拦截验证码与交易邮件，**物理级禁止自动归档（系统红线）**。
   - 一切归档都必须经过 hash 绑定提案的人工批准（审批通道与对话通道隔离）。
   - Gmail 就绪后由任务引擎定时分拣，token 以 Fernet 加密落盘。
4. **破坏性动作提案制 + 有界记忆层**：
   - 归档 / 删文档 / 重建索引三类破坏性动作统一走提案审批：内容 hash 绑定、30 分钟过期、单次消费、执行结果可审计（含"结果未知"一等态）。
   - 记忆层有界（上限 100 条）、可编辑、可遗忘，问答时以"仅为数据"的数据块注入 prompt。
5. **编辑级极简前端设计系统（[docs/DESIGN.md](file:///d:/Memoria/docs/DESIGN.md)）**：
   - 基于 **React 19 + TypeScript + Tailwind CSS**。
   - 温暖骨白画布（`#FAFAF9`）、炭黑字阶（`#18181B`）、高阶圆角卡片（`rounded-3xl` / `rounded-2xl`）、微触觉胶囊按键（`rounded-full`）、黑曜石黑（`#09090b`）圆形发送键。
   - 首屏居中搜索条，首条提问后平滑落底吸附。

---

## 🚀 核心功能模块

### 1. 🔍 问答与逐句溯源 (AskView)
- **居中沉浸式首屏**：初始提问框居中展示，无干扰信息；发送首条提问后平滑下沉并吸附在屏幕底部（`fixed bottom-0`）。
- **多轮会话追问流**：支持连续追问、打字骨架态动效与自动平滑滚动；会话历史本地持久化，刷新可恢复。
- **逐句溯源交互**：正文中每个引用角标 `[1]`、`[2]` 点击可即时联动查看原文档哈希、切片序号与字符偏移量。
- **SSE 流式回答**：`POST /api/ask/stream` 推送 `start → delta → citations → done|error` 事件。
- **对话队列**：回答生成期间输入框保持可编辑，Enter 入队（Up next 条）；发送/停止同位切换，停止或失败都暂停队列且永不隐式重发。
- **一键沉淀 Wiki**：满意的回答一键归档为 Wiki 综合词条。
- **记住这条**：把回答要点写入有界记忆层（内容去重），后续问答自动带入。

### 2. 📖 知识漫游与双向链接 (WikiView)
- **实时索引目录**：按 `index.md` 自动聚合知识大纲，支持动态过滤搜索。
- **网状双向漫游**：正文中的所有 `[[词条链接]]` 均可点击直接跳转，并在页面底部自动列出反向链接（Backlinks）。
- **静态 Lint 体检**：自动扫描断链、孤立页面与逻辑冲突。

### 3. ✉️ 邮件安全分拣中心 (MailView)
- **受保护邮件专区**：验证码与交易邮件强标识保护，绝不提供归档路径。
- **归档一律走提案审批**：勾选营销邮件后在确认弹窗核对并批准，实际执行经 hash 绑定提案（30 分钟有效、单次消费）；若执行失败，提案保留在审批中心可重试或撤销。
- **未连接引导**：未授权 Gmail 时显示横幅与授权步骤，并区分"收件箱为空"与"未连接"。
- **定时分拣**：Gmail 就绪后由任务引擎按间隔自动分拣并生成待审提案。

### 4. 📥 资料双写摄入中心 (IngestView)
- **多源格式拖拽上传**：支持 PDF、Markdown、TXT 拖拽解析与长文本直接粘贴。
- **双写即时反馈**：直观展示切片向量入库数量与 LLM 提取编译的 Wiki 页面明细。
- **删除与重建索引**：同样经提案审批执行；删除会同时清除该文档的全部向量（红线）。

### 5. ⚙️ 模型配置与连通性诊断 (SettingsModal)
- **公网网关适配**：仅支持公网 HTTPS/443 网关，支持 OpenAI Chat Completions、Anthropic Messages、OpenAI Responses 三种协议，填写自定义公网地址。
- **对话/向量双轨**：对话模型与向量模型各自独立的供应商与激活模型，互不串用。
- **一键获取模型列表 (Fetch Models)**：向远端发起请求，自动拉取可用模型并支持快速点选填入。
- **全链路测试连接 (Test Connectivity)**：即时对 LLM 与 Embedding 进行网络往返测试，反馈翡翠绿/玫瑰红诊断卡片与毫秒级延迟（如 `240ms`）。

### 6. 🛡️ 审批中心与运行动态 (ApprovalCenter)
- **待审徽标**：顶栏显示待审提案数量。
- **提案评审**：展示归档/删除/重建索引三类提案的完整载荷（邮件清单、文档名、重建篇数）与内容哈希。
- **唯一批准通道**：`POST /api/proposals/{id}/decide` 是全系统唯一的批准入口，对话通道无法触达破坏性动作。
- **运行动态**：展示定时任务状态（下次运行、尝试次数、最近错误）与 append-only 通知收件箱。

---

## 🛑 系统红线（Red Lines — 永不违反）

- **验证码 / 交易邮件永不自动归档**；任何归档必须人工确认。
- **`raw/` 目录只读不写**，LLM / Agent 永不向 `raw/` 写入数据。
- **删文档必须删掉其全部向量**（无孤儿向量残留）。
- **回答必须带句级来源引用**（哪句话来自哪篇文档哪一段）。
- **检索核心自己手写**；LangChain 只用 integrations；编排用 LangGraph 状态机。

---

## 🛠️ 快速启动

### 1. 环境准备与依赖安装

系统要求 Python >= 3.11（推荐 3.11+）及 Node.js >= 18：

```bash
# 1. 克隆仓库并安装 Python 依赖（开发模式）
git clone <repo-url>
cd Memoria
pip install -e ".[dev]"

# 2. 安装前端依赖并构建生产产物
cd frontend
npm install
npm run build
cd ..
```

### 2. 启动服务与前端界面

运行根目录的专属一键启动器，服务将自动启动并在默认浏览器中打开：

```bash
python run_web.py
```

- **Web 界面地址**：[http://127.0.0.1:8000](http://127.0.0.1:8000)
- **OpenAPI 交互式文档**：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

*(首次进入可点击右上角「设置」配置您的 API Key，并使用「获取模型」与「测试连接」验证连通性)*

### 3. 命令行入口（与 Web 共用同一张 LangGraph 图）

CLI 不含业务逻辑，所有子命令都经由编译后的图执行，与 Web API 是同一条编排路径：

```bash
python -m memoria ask "服务 A 何时到期"      # 混合检索问答，预设 intent，跳过 router
python -m memoria ingest 资料.pdf             # 双写摄入
python -m memoria lint                        # Wiki 断链 / 孤立页体检
python -m memoria agent "帮我看看最近的邮件"   # 自由文本，由图内 router 决定分支
```

`agent` 子命令刻意不预设意图，会多付一次 router 的 LLM 往返换取自动分流；其余子命令的意图已由参数表明，直接走对应分支。

### 4. 可选：配置 Gmail 真实邮件拉取

若需要连接个人 Gmail 邮箱进行邮件分拣：
1. 生成 token 加密密钥（token 以 Fernet 加密落盘，**缺少该密钥会拒绝读写**）：
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   将输出设为环境变量 `TOKEN_ENCRYPTION_KEY`（写入系统环境变量或启动前 `set` / `export`）。
2. 在 [Google Cloud Console](https://console.cloud.google.com/) 启用 Gmail API 并创建桌面应用客户端凭据，下载保存为 `data/credentials.json`。
3. 运行一键授权助手启动本地浏览器完成认证：
   ```bash
   python scripts/auth_gmail.py
   ```
4. 授权成功后生成加密的 `data/token.json`，Web 邮件中心即可读取真实邮件。

---

## 🧪 自动化测试与工程验证

本项目基于严苛的 Agentic Harness 规范运作，所有关键路径均具备 100% 离线测试覆盖：

```bash
# Windows / pwsh 全流程验证（推荐）
./init.ps1

# Linux / macOS / bash 全流程验证
./init.sh
```

手动执行单项检验：
- **后端单元测试**（276 项测试，含 RAG 向量原子删除、LangGraph 中断恢复与 router 动态路由、Wiki 断链体检、模型配置就绪度判定、Web API 代理与公网 HTTPS/443 配置安全等）：
  ```bash
  python -m pytest -q
  ```
- **前端类型检查与打包**：
  ```bash
  cd frontend && npm run build
  ```

---

## 📁 目录结构

```text
Memoria/
├── src/memoria/             # 后端核心源码
│   ├── rag/                 # RAG 模块: parse, chunk, embed, store, retrieve, answer
│   ├── wiki/                # Wiki 模块: pages, ops (ingest/query/lint)
│   ├── mail/                # Mail 模块: rules, classify, gmail, auth
│   ├── graph/               # LangGraph 编排: state, nodes, graph
│   ├── web/                 # Web API 服务: app.py, config.py, config_routes.py
│   ├── records.py           # 单表记录存储 (kind/id/data + CAS，提案/任务/记忆/通知共用)
│   ├── proposals.py         # 破坏性动作的 hash 绑定提案审批（唯一批准通道）
│   ├── tasks.py             # 最小持久任务引擎 + 通知收件箱
│   ├── memory.py            # 有界可编辑可遗忘的记忆层
│   ├── net.py               # 出站 HTTPS 安全层 (SSRF 防护, IP 锁定, 重定向/体积上限)
│   ├── llm.py               # 供应商无关的 Chat LLM 客户端 (三种协议)
│   ├── sync.py              # RAG × Wiki 双写、混合查询与知识沉淀
│   └── cli.py               # 命令行工具 (与 Web 同一张图；agent 子命令走 router)
├── frontend/                # 前端工程 (React 19 + TypeScript + Tailwind)
│   ├── src/
│   │   ├── components/      # 组件：ui/ (胶囊圆角基础组件) + settings/ (供应商配置) + ApprovalCenter.tsx
│   │   ├── views/           # 页面视图 (AskView, WikiView, MailView, IngestView)
│   │   └── api.ts           # 前端 API 封装 (含 SSE 流式客户端)
│   └── tailwind.config.js   # 骨白、黑曜石黑与高阶圆角主题配置
├── tests/                   # 离线自动化测试套件 (276 passed，含 conftest.py 共享测试替身)
├── scripts/                 # 工具脚本 (auth_gmail.py)
├── docs/                    # 架构、设计、验证与升级路线文档
│   └── agent-architecture/  # 开源 agent 架构研究沉淀 (hermes/ talorys/ openmuse/ 等)
├── data/                    # 本地数据持久化 (Chroma 库、Wiki 纯文本、records/token，已 gitignore)
├── feature_list.json        # 交付功能跟踪清单 (Source of Truth)
├── progress.md              # 进度日志
├── session-handoff.md       # 多会话交接文件
├── AGENTS.md                # AI Agent 行为规范与红线
├── run_web.py               # Web 服务启动器
├── init.ps1                 # Windows 标准初始化与校验脚本
└── init.sh                  # Linux/macOS 标准初始化与校验脚本
```

---

## 📄 开源许可证

MIT License.
