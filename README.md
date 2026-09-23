# Memoria — 个人智能知识库与知识复利系统

> **RAG 管「找得全」，Wiki 管「记得牢」，邮件分拣管「不错漏」，LangGraph 编排状态机，极简胶囊圆角 Web 交互。**

---

## 🌟 核心理念与架构特点

Memoria 是一套专为个人打造的本地智能知识管理系统，解决传统 RAG 知识库「答案零散、不可溯源、越用越散」与笔记软件「整理成本高、不能自主沉淀」的痛点：

1. **手写核心检索（~100 行）**：向量相似度 + 关键词重排 + 来源引用映射，逻辑清爽透明，LangChain 仅用于底层集成。
2. **知识复利循环（Dual-Write & Self-Compiling Wiki）**：
   - 摄入资料时，一边切片存入本地 Chroma 向量库，一边由 LLM 编译为具备 `[[双向链接]]` 的 Wiki 词条网络。
   - 高质量问答一键归档为 synthesis 页面，知识越用越厚。
3. **安全邮件分拣中心（Mail Triage with Hard Invariants）**：
   - 规则层优先拦截验证码与交易邮件，**物理级禁止自动归档（系统红线）**。
   - 营销邮件归档前必须经过人工弹窗二次确认。
4. **编辑级极简前端设计系统（[DESIGN.md](file:///d:/Memoria/DESIGN.md)）**：
   - 基于 **React 19 + TypeScript + Tailwind CSS**。
   - 温暖骨白画布（`#FAFAF9`）、炭黑字阶（`#18181B`）、高阶圆角卡片（`rounded-3xl` / `rounded-2xl`）、微触觉胶囊按键（`rounded-full`）、黑曜石黑（`#09090b`）圆形发送键。
   - 首屏居中搜索条，首条提问后平滑落底吸附。

---

## 🚀 核心功能模块

### 1. 🔍 问答与逐句溯源 (AskView)
- **居中沉浸式首屏**：初始提问框居中展示，无干扰信息；发送首条提问后平滑下沉并吸附在屏幕底部（`fixed bottom-0`）。
- **多轮会话追问流**：支持连续追问、打字骨架态动效与自动平滑滚动。
- **逐句溯源交互**：正文中每个引用角标 `[1]`、`[2]` 点击可即时联动查看原文档哈希、切片序号与字符偏移量。
- **一键沉淀 Wiki**：满意的回答一键归档为 Wiki 综合词条。

### 2. 📖 知识漫游与双向链接 (WikiView)
- **实时索引目录**：按 `index.md` 自动聚合知识大纲，支持动态过滤搜索。
- **网状双向漫游**：正文中的所有 `[[词条链接]]` 均可点击直接跳转，并在页面底部自动列出反向链接（Backlinks）。
- **静态 Lint 体检**：自动扫描断链、孤立页面与逻辑冲突。

### 3. ✉️ 邮件安全分拣中心 (MailView)
- **受保护邮件专区**：验证码与交易邮件强标识保护，绝不提供归档路径。
- **营销邮件人工确认门禁**：复选框自由勾选，归档必须人工在确认弹窗中核对确认。

### 4. 📥 资料双写摄入中心 (IngestView)
- **多源格式拖拽上传**：支持 PDF、Markdown、TXT 拖拽解析与长文本直接粘贴。
- **双写即时反馈**：直观展示切片向量入库数量与 LLM 提取编译的 Wiki 页面明细。

### 5. ⚙️ 模型配置与连通性诊断 (SettingsModal)
- **灵活适配**：原生兼容 OpenAI、DeepSeek、Ollama 及各类 OpenAI 兼容网关。
- **一键获取模型列表 (Fetch Models)**：向远端发起请求，自动拉取可用模型并支持快速点选填入。
- **全链路测试连接 (Test Connectivity)**：即时对 LLM 与 Embedding 进行网络往返测试，反馈翡翠绿/玫瑰红诊断卡片与毫秒级延迟（如 `240ms`）。

---

## 🛑 系统红线（Red Lines — 永不违反）

- **验证码 / 交易邮件永不自动归档**；任何归档必须人工确认。
- **`raw/` 目录只读不写**，LLM / Agent 永不向 `raw/` 写入数据。
- **删文档必须删掉其全部向量**（无孤儿向量残留）。
- **回答必须带句级来源引用**（哪句话来自哪篇文档哪一段）。
- **检索核心手写**；LangChain 仅用于 connector/loader；编排采用 LangGraph 状态机。

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

### 3. 可选：配置 Gmail 真实邮件拉取

若需要连接个人 Gmail 邮箱进行邮件分拣：
1. 在 [Google Cloud Console](https://console.cloud.google.com/) 启用 Gmail API 并创建桌面应用客户端凭据，下载保存为 `data/credentials.json`。
2. 运行一键授权助手启动本地浏览器完成认证：
   ```bash
   python scripts/auth_gmail.py
   ```
3. 授权成功后生成 `data/token.json`，Web 邮件中心即可无缝读取真实邮件！

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
- **后端单元测试**（58 项测试，含 RAG 向量原子删除、LangGraph 中断恢复、Wiki 断链体检、Web API 代理等）：
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
│   ├── web/                 # Web API 服务: app.py, config.py
│   ├── sync.py              # RAG × Wiki 双写、混合查询与知识沉淀
│   └── cli.py               # 命令行工具
├── frontend/                # 前端工程 (React 19 + TypeScript + Tailwind)
│   ├── src/
│   │   ├── components/ui/   # 胶囊圆角组件系统 (PillButton, RoundedCard, SettingsModal...)
│   │   ├── views/           # 页面视图 (AskView, WikiView, MailView, IngestView)
│   │   └── api.ts           # 前端 API 封装
│   └── tailwind.config.js   # 骨白、黑曜石黑与高阶圆角主题配置
├── tests/                   # 离线自动化测试套件 (58 passed)
├── scripts/                 # 工具脚本 (auth_gmail.py)
├── docs/                    # 架构与产品文档 (ARCHITECTURE.md)
├── data/                    # 本地数据持久化 (Chroma 库、Wiki 纯文本)
├── feature_list.json        # 交付功能跟踪清单 (Source of Truth)
├── progress.md              # 进度日志
├── session-handoff.md       # 多会话交接文件
├── DESIGN.md                # 视觉与设计系统规范
├── AGENTS.md                # AI Agent 行为规范与红线
├── run_web.py               # Web 服务启动器
├── init.ps1                 # Windows 标准初始化与校验脚本
└── init.sh                  # Linux/macOS 标准初始化与校验脚本
```

---

## 📄 开源许可证

MIT License.
