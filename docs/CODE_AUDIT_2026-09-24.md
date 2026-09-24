# Memoria 代码审查报告

- **审查日期：** 2026-09-24
- **审查对象：** `D:\Memoria`
- **审查类型：** 前端、后端、路由/API、模块边界、死代码、过度封装、代码复用、文件长度
- **审查模式：** 只读静态审查
- **代码修改：** 无
- **报告文件：** `docs/CODE_AUDIT_2026-09-24.md`

## 1. 执行摘要

本次审查没有发现大批完全未使用的业务模块，但发现三类明显的结构冗余：

1. **配置系统双轨运行**：旧的 flat/preset 配置 API 与新的 provider/model API 同时存在。
2. **编排系统双轨运行**：LangGraph 图编排与 Web/CLI 直接函数调用同时存在，且语义不完全一致。
3. **前后端各有一个总控制器**：`SettingsModal.tsx` 和 `web/app.py` 分别承载了过多状态、流程和路由职责。

最高价值的审查结论不是“立即删除更多代码”，而是先做两个产品/架构决策：

- LangGraph 是否必须成为正式生产编排器。
- 旧 `/api/config` 与 presets 是否仍有仓库外消费者。

在这两个问题没有明确前，直接删除 graph 或旧 API 可能破坏项目定位或外部兼容性。

## 2. 审查范围与方法

### 2.1 覆盖范围

- `frontend/src`
- `frontend/package.json`、`frontend/tsconfig.json`、Vite/Tailwind 配置
- `src/memoria`
- `run_web.py`
- `scripts`
- `tests`
- `pyproject.toml`
- `README.md`
- `docs/ARCHITECTURE.md`
- `init.sh`、`init.ps1`
- GitHub Actions 配置

### 2.2 排除范围

- `.git`
- `.zcode`
- `node_modules`
- `dist`
- `__pycache__`
- `.pytest_cache`
- `.egg-info`
- 其他生成物

### 2.3 使用的只读检查

- 文件树扫描
- `rg` 符号引用扫描
- Python 源码、测试和配置读取
- TypeScript 严格未使用检查：

```text
frontend/node_modules/.bin/tsc --noEmit --noUnusedLocals --noUnusedParameters --pretty false
```

该检查发现了 10 个未使用导入、状态或函数诊断。

本次没有执行会生成构建产物的生产构建，也没有修改源码、测试、配置或运行数据。报告新增本身是唯一文件变更。

## 3. 项目规模

| 区域 | 规模 | 说明 |
|---|---:|---|
| `src/memoria/rag` | 368 行 | 解析、切分、嵌入、存储、检索、回答 |
| `src/memoria/wiki` | 229 行 | Wiki 页面和 ingest/query/lint |
| `src/memoria/mail` | 231 行 | 规则、分类、Gmail、OAuth |
| `src/memoria/graph` | 161 行 | LangGraph 状态机 |
| `src/memoria/web` | 1,085 行 | FastAPI 和配置 |
| `src/memoria` 其余模块 | 674 行 | CLI、LLM、网络、sync |
| `frontend/src` | 3,787 行 | React/TypeScript 前端 |
| `tests` | 1,784 行 | Python 测试 |
| `test_smoke.py` | 2 行 | 根目录烟测 |

生产代码统计约为 6,658 行，测试代码约为 1,784 行。后端测试/生产代码比例约为 62.1%，前端生产代码约 3,787 行，但没有前端行为测试文件。

当前测试规模与项目状态记录一致：后端约 102 个参数化测试用例。审查期间没有重新运行完整测试套件。

## 4. 优先级定义

| 优先级 | 含义 |
|---|---|
| P0 | 结构性分叉或未来必然继续产生重复实现的问题，应先做架构决策 |
| P1 | 高收益、低到中等风险的复杂度清理，或明确的重复状态中心 |
| P2 | 中等收益的重复、预留 API、公开类型或未使用配置 |
| P3 | 低收益维护项，不建议优先处理 |

本报告的 P0/P1 主要表示代码复杂度和架构分叉风险，不等同于已经确认的安全漏洞或线上故障。

## 5. P0：最高优先级结构问题

### 5.1 `SettingsModal.tsx` 是 1,638 行的前端状态中心

**位置：** `frontend/src/components/ui/SettingsModal.tsx:45-1638`

**现状：**

一个组件同时负责：

- Provider 创建、编辑、删除和激活
- 模型获取、添加、编辑、删除
- 模型标签维护
- Provider 连接测试
- 单模型连接测试
- localStorage 读取和写入
- 后端 `settings.json` 同步
- Provider 缓存迁移
- Toast、加载态和错误态
- Provider 侧栏、表单、模型面板、诊断面板和弹窗

该文件约有 31 个 `useState` 调用，状态定义集中在 `SettingsModal.tsx:45-112`。

**重复逻辑证据：**

| 重复流程 | 位置 |
|---|---|
| 保存已有 Provider | `SettingsModal.tsx:400-447` |
| 保存新建 Provider | `SettingsModal.tsx:451-523` |
| Provider 连接测试 | `SettingsModal.tsx:553-593` |
| 单模型连接测试 | `SettingsModal.tsx:597-636` |
| 获取模型按钮 | `SettingsModal.tsx:1103-1114`、`1257-1267` |
| 模型标签推导 | `SettingsModal.tsx:273-279`、`324-329`、`365-370` |

**影响：**

- UI、业务、API、持久化和错误处理全部耦合。
- 任何配置改动都可能触及同一文件的大范围代码。
- localStorage 与后端配置同步逻辑容易分叉。
- 测试需要通过整个设置面板间接覆盖，局部复用困难。

**建议的最小拆分边界：**

```text
useProviderSettings()   // 状态、API、持久化和错误处理
ProviderSidebar         // Provider 列表和状态
ProviderForm            // 创建/编辑 Provider
ModelList               // 模型列表和模型操作
ConnectionDiagnostics   // Provider/模型测试结果
```

建议先抽离数据和 API 逻辑，再拆 JSX。不要为了拆分一次性引入过多通用 UI 抽象。

---

### 5.2 `web/app.py` 集中 23 个路由和全部运行时装配

**位置：**

- 请求模型与安全辅助：`src/memoria/web/app.py:39-180`
- 依赖初始化与配置激活：`src/memoria/web/app.py:183-267`
- 全部 API 路由：`src/memoria/web/app.py:269-768`
- 静态文件挂载：`src/memoria/web/app.py:772-776`

`create_app()` 同时装配：

- 健康检查
- 旧配置 API
- Provider/Model API
- RAG 问答
- Wiki
- Gmail
- Ingest
- 静态前端

**影响：**

- 配置业务与邮件、问答、摄入路由处于同一个闭包工厂中。
- 路由级复用和单元隔离较弱。
- 修改配置逻辑时容易影响其他业务路径。
- 文件行数和职责集中度都明显高于其他后端模块。

**建议：**

按业务边界拆成四个路由模块即可：

```text
config_routes.py
knowledge_routes.py
mail_routes.py
ingest_routes.py
```

再将 Chroma、Wiki、LLM、Embedder 的装配放入一个最小运行时依赖模块。路由负责 HTTP 参数和响应，业务状态转换保持在小型纯函数中。

---

### 5.3 LangGraph 与实际 Web/CLI 链路平行存在

**定义位置：**

- `src/memoria/graph/graph.py:14-39`
- `src/memoria/graph/nodes.py:15-84`
- `src/memoria/graph/state.py`
- `src/memoria/graph/__init__.py:3-6`

**生产调用证据：**

- Web 问答直接调用 `hybrid_answer()`：`src/memoria/web/app.py:609-612`
- Web 摄入直接调用 `dual_ingest()`：`src/memoria/web/app.py:747-751`
- Web 邮件直接调用分类和归档函数：`src/memoria/web/app.py:683-744`
- CLI 直接调用 `dual_ingest()` / `hybrid_answer()`：`src/memoria/cli.py:42-59`
- `build_graph()` 的生产调用方为 0，当前只有 `tests/test_graph.py` 使用。

两套编排的语义也不一致：

| 流程 | LangGraph | Web/CLI 实际路径 |
|---|---|---|
| QA | `graph/nodes.py:27-32` 纯 RAG | `sync.py:50-64` Wiki-first 混合回答 |
| Ingest | `graph/nodes.py:68-84` 只写 Wiki | `sync.py:29-39` RAG + Wiki 双写 |
| Mail | Graph 节点返回 triage 和 pending archive | Web 直接执行分类与归档 |

**结论：**

这不是一个简单的薄包装，而是两套可能继续分叉的编排实现。

**必须二选一：**

1. 将 Web/CLI 统一接入 `build_graph()`，使 Graph 成为唯一生产编排器；
2. 删除 graph 实现、相关测试和 `langgraph` 依赖，并同步修改 README 与架构文档。

在产品方向确认前，不建议直接删除。

## 6. P1：高优先级重复和状态问题

### 6.1 旧 `/api/config` 与 presets API 没有第一方前端调用方

**旧路由：**

| 方法 | 路径 | 位置 |
|---|---|---|
| GET | `/api/config` | `src/memoria/web/app.py:272-275` |
| POST | `/api/config` | `src/memoria/web/app.py:276-286` |
| POST | `/api/config/presets` | `src/memoria/web/app.py:288-318` |
| POST | `/api/config/presets/{name}/apply` | `src/memoria/web/app.py:320-329` |
| DELETE | `/api/config/presets/{name}` | `src/memoria/web/app.py:331-342` |

**对应数据结构：**

- `ModelPreset`：`src/memoria/web/config.py:27-35`
- `Settings.presets`：`src/memoria/web/config.py:61-74`
- 预设清洗：`src/memoria/web/config.py:141-159`
- 预设序列化：`src/memoria/web/app.py:97-109`
- 总配置输出中的 presets：`src/memoria/web/app.py:135-151`

当前前端 `frontend/src/api.ts:82-186` 使用的是 Provider/Model API，没有调用这些旧接口。旧接口主要由 `tests/test_web_api.py` 维护。

**结论：** 如果没有仓库外客户端，这是最明确的可删除兼容层候选。删除前需要确认外部 API 消费者，而不是仅依据前端调用数量决定。

---

### 6.2 Provider 激活状态转换逻辑重复

重复出现在：

- `activate_settings()`：`src/memoria/web/app.py:209-262`
- 保存 Provider：`src/memoria/web/app.py:373-444`
- 激活 Provider：`src/memoria/web/app.py:570-600`
- 删除模型后的 active model 更新：`src/memoria/web/app.py:527-544`

这些路径都处理：

- active provider
- active chat model
- active embed model
- `llm_base_url`
- `llm_api_key`
- `llm_model`

**建议：** 抽出一个纯函数，例如 `resolve_active_models(settings)`，让路由只提交用户意图。不需要复杂工厂或继承体系。

---

### 6.3 前端 localStorage 与后端配置存在双状态源

缓存 key 重复定义于：

- `SettingsModal.tsx:35-38`
- `AskView.tsx:144-146`
- `AskView.tsx:169-171`

写入 localStorage：

- `SettingsModal.tsx:117-125`

`AskView` 通过 `storage` 事件监听：

- `AskView.tsx:190-191`

浏览器通常不会在同一个页面自身的 `localStorage.setItem()` 后触发对应的 `storage` 事件，因此设置保存后问答页的当前模型显示可能延迟到刷新或组件重新挂载。

**建议：**

优先将 active provider/model 提升到 `App` 状态，由 `SettingsModal` 通过回调通知 `App`，再传给 `AskView`。如果暂时保留 localStorage，至少集中 key、读取和解析函数。

---

### 6.4 Gmail OAuth 脚本与 Web 邮件路由未在默认启动路径装配

- Gmail service 只在 `create_app()` 参数中注入：`src/memoria/web/app.py:206-207`
- 邮件路由使用 `mail_service`：`src/memoria/web/app.py:683-690`、`731-737`
- 默认启动路径：`run_web.py:43-44`
- `get_gmail_service()`：`src/memoria/mail/auth.py:55-64`
- 授权脚本调用：`scripts/auth_gmail.py:63-64`

授权脚本与 Web 邮件页面之间没有一个默认生产组合根把 Gmail service 连接起来。

**建议：**

后续应在启动组合根中显式创建 Gmail service，或者明确把 Gmail 标记为库/测试能力。此项属于普通功能审查，不建议在本次只读审查中修改。

## 7. P1/P2：前端明确可删除项

### 7.1 未使用依赖

- `clsx`：`frontend/package.json:12`
- `tailwind-merge`：`frontend/package.json:16`

`frontend/src` 中没有对应 import 或调用。若没有近期 class 合并计划，可以删除并更新 lockfile。

---

### 7.2 未使用导入、状态和函数

严格未使用检查发现：

| 文件 | 行号 | 符号 |
|---|---:|---|
| `frontend/src/components/ui/SettingsModal.tsx` | 8 | `ChevronDown` |
| `frontend/src/components/ui/SettingsModal.tsx` | 12 | `Globe` |
| `frontend/src/components/ui/SettingsModal.tsx` | 13 | `Key` |
| `frontend/src/components/ui/SettingsModal.tsx` | 15 | `Link2` |
| `frontend/src/components/ui/SettingsModal.tsx` | 22 | `Server` |
| `frontend/src/components/ui/SettingsModal.tsx` | 84 | `showModelSelectionPanel` |
| `frontend/src/views/MailView.tsx` | 9 | `Tag` |
| `frontend/src/views/WikiView.tsx` | 6 | `FileText` |
| `frontend/src/views/WikiView.tsx` | 79-98 | `renderWikiContent` |

`showModelSelectionPanel` 的 setter 被调用但没有读取位置。实际显示条件在 `SettingsModal.tsx:1159` 使用模型列表长度。

`renderWikiContent` 没有调用方，实际 Wiki 页面通过 `MarkdownRenderer` 渲染：

- `WikiView.tsx:216-219`
- `MarkdownRenderer.tsx:20-94`

因此 `renderWikiContent` 是重复的 Markdown/Wiki 链接解析实现，可以删除而不影响当前页面。

---

### 7.3 未使用 API wrapper

- `frontend/src/api.ts:31`：`api.health`

后端 `/api/health` 路由位于 `src/memoria/web/app.py:268-270`，可以作为运维探针保留；但前端 wrapper 当前没有任何调用方。

`App.tsx:37-40` 的“本地就绪”是静态展示，并未调用 `api.health()`。

---

### 7.4 未使用 UI 配置分支

当前没有未使用的组件文件，但以下配置没有实际使用方：

- `RoundedCard.tsx:5`：`hoverEffect`
- `RoundedCard.tsx:19`：`flat` variant
- `PillButton.tsx:25`：`lg` size
- `PillButton.tsx:33`：`wiki` variant

如果没有明确扩展计划，这些属于 YAGNI 配置面。

---

### 7.5 非必要公开类型导出

以下类型目前只在本文件内使用：

- `PillBadgeProps`：`frontend/src/components/ui/PillBadge.tsx:3`
- `PillButtonProps`：`frontend/src/components/ui/PillButton.tsx:3`
- `RoundedCardProps`：`frontend/src/components/ui/RoundedCard.tsx:3`
- `WikiPageSummary`：`frontend/src/types.ts:15`

如果项目不将前端类型作为独立公共包发布，可以去掉不必要的 `export`。这属于低风险 API 表面收敛，不影响运行时。

## 8. P2/P3：后端可删除或可合并项

### 8.1 `rag.ingest.delete_document` 是单行包装器

- 包装器：`src/memoria/rag/ingest.py:33-36`
- 实际实现：`src/memoria/rag/store.py:31-34`
- 导出：`src/memoria/rag/__init__.py:6,24`
- 测试调用：`tests/test_rag_ingest.py:61`

没有生产调用方。如果不存在外部公共 API 兼容要求，测试可以直接调用 store，删除该包装器。

---

### 8.2 `archive_fact` 只有测试调用

- 实现：`src/memoria/sync.py:84-92`
- 测试调用：`tests/test_sync.py:75-78`
- 架构文档描述：`docs/ARCHITECTURE.md:61-63`

邮件路由和 Graph 都没有接入它。若这是计划中的“邮件事实写入 Wiki”能力，应接入真实流程；否则应删除函数和测试，避免文档与实现继续分叉。

---

### 8.3 邮件分类类别有两个来源

- `CATEGORIES`：`src/memoria/mail/classify.py:14`
- 重新导出：`src/memoria/mail/__init__.py:2,8`
- 解析器硬编码类别：`src/memoria/mail/classify.py:49-57`

`CATEGORIES` 没有被业务逻辑使用，解析器又单独硬编码了“营销、通知、待办”。建议用一个来源驱动解析和验证，或者删除常量和 re-export。

---

### 8.4 细分邮件规则函数公开导出没有外部调用

- `is_verification`：`src/memoria/mail/rules.py:35-40`
- `is_transaction`：`src/memoria/mail/rules.py:43-46`
- 公开 re-export：`src/memoria/mail/__init__.py:4,13-16`

生产 Web 层只使用聚合后的 `is_protected`。如果没有外部库消费者，可以停止公开导出两个细分函数。

---

### 8.5 三个 Pydantic 模型重复协议验证器

重复位置：

- `src/memoria/web/config.py:55-59`
- `src/memoria/web/config.py:81-85`
- `src/memoria/web/config.py:96-100`

建议使用一个小型共享类型约束或基类，不需要复杂工厂。

---

### 8.6 `load_document()` 接受 HTTP，但底层只允许 HTTPS

- URL 入口：`src/memoria/rag/parse.py:25-28`
- URL 安全校验：`src/memoria/net.py:76-88`
- 出站限制：`src/memoria/net.py:248-250`

`load_document()` 将 `http://` 和 `https://` 都识别为 URL，但网络层最终只接受 HTTPS。建议入口只接受 HTTPS，避免声明了永远无法成功的 HTTP 分支。

---

### 8.7 无信息量的根目录烟测

- `test_smoke.py:1-2` 只有 `assert True`
- `pyproject.toml:28` 将根目录纳入 testpath

该测试贡献一个用例但不验证任何行为，可以删除。

---

### 8.8 明确未使用 import

- `run_web.py:12`：`Path`
- `src/memoria/mail/auth.py:5`：`os`
- `src/memoria/web/app.py:13`：`Form`

这些符号只有 import 行，没有实际使用。

---

### 8.9 `requests` 依赖暂不能直接删除

- 声明位置：`pyproject.toml:14`
- 源码没有直接 `import requests`
- Google OAuth 使用 `google.auth.transport.requests`：`src/memoria/mail/auth.py:8`

Google 认证依赖链可能需要 `requests`，不能仅凭项目源码没有直接 import 就删除直接依赖。应先检查依赖元数据和安装约束。

## 9. 路由与 API 设计审查

### 9.1 前端导航是内存 tab，不是 URL 路由

位置：

- `frontend/src/App.tsx:12`：`activeTab`
- `frontend/src/App.tsx:13`：`selectedWikiPage`
- `frontend/src/App.tsx:16-18`：Wiki 导航处理
- `frontend/src/App.tsx:35`：`SegmentedNav`
- `frontend/src/App.tsx:57-61`：条件渲染 View
- `frontend/src/components/ui/SegmentedNav.tsx:3`：四个字符串 tab

当前没有：

- `react-router`
- `BrowserRouter`
- `Routes`
- `useNavigate`
- `history.pushState`

**当前方案的适用性：**

对于只有四个平级 tab 的本地单页工作台，当前 state 方案是足够简单的，不建议为了“路由正规化”立即增加 `react-router`。

**限制：**

- 刷新后回到 `ask`。
- 浏览器前进/后退不会切换 tab。
- Wiki 页面不能通过 URL 分享。
- 外部链接无法直接打开某个 Wiki 页面。

如果未来确实需要深链接，优先使用原生 `URLSearchParams + history.pushState`；只有出现多级页面、嵌套路由或复杂路由状态时再引入路由库。

### 9.2 第一方前端与后端路由对齐情况

| 业务 | 前端调用 | 后端定义 |
|---|---|---|
| Ask | `AskView.tsx:219` | `app.py:608-629` |
| Wiki 列表/详情 | `WikiView.tsx:33,48` | `app.py:631-666` |
| Mail | `MailView.tsx:30,65` | `app.py:682-744` |
| Ingest | `IngestView.tsx:31,45` | `app.py:746-770` |
| Providers/models | `SettingsModal.tsx:157-191` | `app.py:362-606` |
| Fetch/Test/Activate | `SettingsModal.tsx:262,565,602,679` | `app.py:344-360,546-606` |

主要业务路由是对齐的。

### 9.3 API 契约漂移

1. `/api/health` 有后端路由和前端 wrapper，但前端没有调用。
2. 前端 `CustomProvider` 声明 `api_key`：`frontend/src/types.ts:68-78`；后端公开响应只返回 `api_key_set` 和 `masked_api_key`：`src/memoria/web/app.py:122-132`。
3. 后端连通性响应包含 LLM 和 Embedding 字段：`src/memoria/web/config.py:221-228`；前端主要声明和展示 LLM 字段：`frontend/src/api.ts:129-161`。
4. 邮件响应同时返回 `id` 和 `msg_id`，值相同：`frontend/src/types.ts:35-45`、`src/memoria/web/app.py:699-702`；归档接口使用 `msg_id`：`frontend/src/api.ts:53-60`。

这些属于 API 契约清理项，优先级低于配置双轨和双编排问题。

## 10. 文件长度与职责审查

| 排名 | 文件 | 行数 | 结论 |
|---:|---|---:|---|
| 1 | `frontend/src/components/ui/SettingsModal.tsx` | 1,638 | 明确过度集中 |
| 2 | `tests/test_web_api.py` | 782 | 测试覆盖面大，文件偏长 |
| 3 | `src/memoria/web/app.py` | 781 | 明确过度集中 |
| 4 | `frontend/src/views/AskView.tsx` | 530 | 存在重复提问表单 |
| 5 | `src/memoria/net.py` | 318 | 长度合理，安全逻辑复杂 |
| 6 | `src/memoria/web/config.py` | 299 | 配置协议和持久化集中 |
| 7 | `frontend/src/views/MailView.tsx` | 287 | 暂不需要拆分 |
| 8 | `frontend/src/views/WikiView.tsx` | 284 | 有死代码和重复解析器 |
| 9 | `frontend/src/components/ui/MarkdownRenderer.tsx` | 208 | 合理 |
| 10 | `frontend/src/views/IngestView.tsx` | 203 | 合理 |

`SettingsModal.tsx` 单独占前端生产代码约 43%，是最明显的前端拆分候选。`create_app()` 从 `src/memoria/web/app.py:183-778` 延伸约 596 行，包含配置、依赖初始化、23 个 API 路由和静态文件挂载，是最明显的后端拆分候选。

## 11. 代码复用与重复实现

### 11.1 前端重复流程

- Provider 保存：`SettingsModal.tsx:400-523`
- 连接测试：`SettingsModal.tsx:553-636`
- 获取模型 UI：`SettingsModal.tsx:1103-1114`、`1257-1267`
- 标签推导：`SettingsModal.tsx:273-279`、`324-329`、`365-370`
- 提问表单：`AskView.tsx:297-324`、`495-522`

`AskView` 的两套提问表单可以复用一个本地输入组件，不需要引入通用表单框架。

### 11.2 后端重复流程

- Provider 查找、404 和 models 列表替换：`app.py:447-469`、`472-518`、`521-544`、`547-568`、`571-606`
- 协议字段 validator：`config.py:55-58`、`81-84`、`96-99`
- Provider 激活状态推导：`app.py:209-262`、`373-444`、`570-600`

### 11.3 Markdown 重复实现

- `WikiView.tsx:79-98`：`renderWikiContent`
- `MarkdownRenderer.tsx:20-94`：统一 `renderInline`
- `MarkdownRenderer.tsx:102-204`：块级 Markdown 解析

实际页面已经使用 `MarkdownRenderer`，因此 `WikiView.renderWikiContent` 可以作为明确死代码删除。

## 12. 不建议误删或替换的部分

### 12.1 `src/memoria/net.py`

该模块承担：

- 公网地址限制
- HTTPS/443 限制
- DNS 全结果校验
- IP pinning
- 同源重定向
- 响应大小和压缩限制

它不是普通重复封装，也不应直接替换为 `urllib.request` 或 `requests`。

### 12.2 手写 RAG 检索核心

项目架构明确要求检索核心手写，LangChain 只用于 integrations。该部分不是本次审查的删除对象。

### 12.3 主要 UI 组件文件

已确认以下组件都有实际引用：

- `SegmentedNav`：`App.tsx:2,35`
- `SettingsModal`：`App.tsx:8,53`
- `AskView`：`App.tsx:3,57`
- `WikiView`：`App.tsx:4,58`
- `MailView`：`App.tsx:5,59`
- `IngestView`：`App.tsx:6,60`
- `MarkdownRenderer`：`AskView.tsx:11,432`、`WikiView.tsx:16,216`
- `ConfirmModal`：`MailView.tsx:12,275`
- `PillButton`、`PillBadge`、`RoundedCard`

### 12.4 Vite `preview` 脚本

`frontend/package.json:9` 的 `preview` 没有被仓库脚本调用，但属于 Vite 标准运维入口，不应直接视为死代码。

### 12.5 `requests` 直接依赖

源码没有直接 import，但 Google OAuth 传输链可能需要它。应先验证依赖元数据，不应凭静态 import 扫描直接删除。

## 13. 建议执行顺序

### 第一批：低风险清理

1. 删除前端未使用 import、状态和 `renderWikiContent`。
2. 删除 `clsx`、`tailwind-merge`。
3. 删除未使用的 `api.health` 前端 wrapper。
4. 删除无行为覆盖的 `test_smoke.py`。
5. 删除 `run_web.py` 的 `Path`、`mail/auth.py` 的 `os` 和 `web/app.py` 的 `Form` 未使用 import。
6. 合并三个重复的 `api_format` validator。

### 第二批：结构收敛

1. 决定旧 `/api/config` 和 presets 是否仍有外部消费者。
2. 决定 LangGraph 是正式编排器还是演示模块。
3. 将 `SettingsModal` 拆成数据 hook 与 4 个业务 UI 区域。
4. 将 `web/app.py` 按配置、知识、邮件、摄入拆成四个路由模块。
5. 统一前后端 active provider/model 的状态来源。

### 第三批：边界确认后处理

1. Gmail service 是否接入默认启动组合根。
2. `archive_fact` 是接入邮件流程还是删除。
3. 是否需要深链接和浏览器历史。
4. 是否保留前后端双重配置持久化。
5. 是否为前端补充最小行为测试和 CI 构建门禁。

## 14. 净收益估算

### 立即或低风险可清理

- 约 50–100 行前端死代码、未使用 import 和重复状态
- 2 个前端依赖：`clsx`、`tailwind-merge`
- 1 个无行为覆盖的根目录烟测
- 3 个明确未使用 import

### 条件性清理

- 旧 `/api/config` 和 presets：约 200–400 行实现与测试，但需要确认外部消费者
- LangGraph：约 160 行生产代码、约 140 行测试和 1 个依赖，但需要确认产品架构方向
- `SettingsModal` 拆分和 `web/app.py` 拆分主要减少耦合，不一定净减少总行数

### 总体估算

在不改变产品架构和不牺牲安全边界的前提下，保守估计可以减少约 400–700 行代码或测试，并移除 2 个明确未使用的前端依赖。最大收益来自配置 API 和 LangGraph 的二选一决策，而不是简单删除零散工具函数。

## 15. 审查结论

当前项目不是“代码太多所以应该全面重写”的状态，而是一个功能已经完整、但架构边界开始出现分叉的状态。

最值得执行的不是大规模重构，而是：

1. 先确认旧配置 API 是否真的需要保留。
2. 确认 LangGraph 是否是正式生产架构。
3. 删除明确无调用的前端和后端死代码。
4. 以最小边界拆分 `SettingsModal` 和 `web/app.py`。
5. 保持手写 RAG 核心和安全网络层不变。

本次审查只新增本报告文件，未修改任何源码、测试、配置或状态文件。
