# Session Handoff

## Current Objective

- Goal: Maintain the full-stack Memoria personal knowledge system — React 19 + TypeScript + Tailwind frontend, FastAPI Web API, LangGraph orchestration.
- Current status: feat-001..feat-045 completed. The 2026-09-25 roadmap (feat-023, feat-032..feat-037) landed earlier; this session (2026-09-27) added **feat-040..feat-045** — a five-item LLM cost-and-caching remediation derived from studying five open-source agent codebases, plus the project decision that **LangGraph is the formal production orchestrator**.
- Working tree: **dirty and uncommitted**. It carries changes from two sessions: the 2026-09-26 SettingsModal refactor (split into `settings/useProviderConfig.ts`, `ProviderDetailForm.tsx`, `ModelFormDialog.tsx`; 1695 → 148 lines) and the 2026-09-27 cache/cost work. Nothing from either session is committed. See "Commit State" below.

## Completed This Session (2026-09-27)

- [x] **调研与规划**：源码研究五个开源 agent —— `zai-org/ZCode`、`deepseek-ai/deepseek-harness`、`earendil-works/pi`、`anomalyco/opencode`、`MiniMax-AI/minimax-code`。产出 `docs/UPGRADE_SPEC.md`（缓存机制对比表、六条代码级现状事实、逐项验收标准、四项「明确不借鉴」的决定及理由）。执行前已与用户确认完整规划。
- [x] **feat-040** 拆分 wiki ingest prompt：`wiki/ops.py` 新增 `_select_relevant()`（复用 `rag.retrieve.keyword_score`，其 CJK 二元组分词已存在，未新增算法）。`ingest()` 改为「稳定页名目录 → 变动 material → top-K 选中页正文」三段式。原布局把全部页面正文拼在 material 之后，每次 ingest 重写整个 prompt，前缀缓存永不命中。
- [x] **feat-041** 显式缓存标记：`llm.py` 的 `anthropic_messages` 路径 system 改为 `[{type:text, text, cache_control:{type:ephemeral}}]`。**刻意不发给** `chat_completions` / `openai_responses`——无法假定用户自配网关支持 `prompt_cache_key`。
- [x] **feat-042** history 按 token 预算：`graph/nodes.py` 新增 `_recent_turns()`，`KEEP_RECENT_TOKENS=20_000`（对齐 pi 默认值），系数 1.5 char/token 取 CJK 保守侧，替换 `[-6:]` 轮数截断。附 `ponytail:` 注释声明是字符估算。
- [x] **feat-043** 邮件批量分类：`mail/classify.py` 新增 `classify_batch()`（`classify()` 单封签名保留，既有测试零改动），N 次 HTTP → 1 次。红线保持：`is_protected` 仍逐封独立执行。
- [x] **feat-044** 锁定 reducer 决策：`graph/state.py` 的 `history` 加 `ponytail:` 注释说明为何故意不用 `operator.add`。顺带修正同文件 docstring 的陈旧事实（原文写 MemorySaver，实际是 `SqliteSaver`）。
- [x] **文档同步**：`docs/ARCHITECTURE.md` 新增第 7 节「横切关注点：LLM 上下文与调用成本」（prompt 稳定前缀布局、缓存标记的发送边界、token 预算裁剪、循环内调用折叠），技术选型表与测试数字同步。README 测试数字 118 → 130。

### 实现中发现并修正的三处真实问题

1. `_parse_batch` 原按行独立解析，但类别与摘要在不同行 → 摘要丢失。改为按编号跨行累积。由新增测试暴露。
2. `tests/test_web_api.py` 的 `SmartChat` fixture 仍按单封格式回复，批量后 m2 营销邮件误判为不可归档 → fixture 增加批量提示词分支。
3. 一处失败的测试假设：`keyword_score` 是覆盖率指标（分母为查询词数），所有页面都有基线分，所以「相关页必然入选」只在页面数 ≤ K 时成立。改用 `max_pages=2` 强制截断来真正验证选择行为。

- [x] **feat-045** LangGraph 正式生产编排器（用户拍板）：新增 `POST /api/agent` 自由文本入口，刻意不预设 `intent`，由 router 节点决定分支——这是生产中唯一真正走通 `add_conditional_edges` 的路径。`cli.py` 全面改为经图编排（原直调 `sync.dual_ingest`/`hybrid_answer`，是第二条未验证链路），新增 `agent` 子命令。`lint` 因图中无对应分支仍直调 `wiki.lint`（只读文件审计，非编排路径）。新增守卫测试用 monkeypatch 让 `sync.*` 抛错以证明 CLI 确实走图。手工验证：`python -m memoria agent "测试"` 的 traceback 停在 `During task with name 'router'`，证明请求确实交给了 router 节点。

### 未做（已记录决策，勿重复讨论）

- **feat-046**（`wont-fix`）：架构门禁 CI。ZCode 有 `architecture-policy.yaml` + `pnpm architecture:check` 机械强制（单文件 ≤400 行、契约 ≤300、公开方法 ≤12、禁循环依赖）。评估结论：单人项目维护成本高于收益，`config_routes.py` 555 行超门槛但无实际阻塞。改用 commit message 纪律。

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| 后端全量 | `python -m pytest -q` | **137 passed** (12.9s) | 基线 118 → +19：wiki 5、answer 2、graph 1、mail 4（feat-040..043），cli 4 + web 3（feat-045） |
| 前端构建 | `cd frontend && npm run build` | green | 1607 modules |
| 专项 | `pytest tests/test_wiki_ops.py` | 13 passed | 含 5 个新增缓存布局测试 |
| 专项 | `pytest tests/test_rag_answer.py` | 12 passed | 含 2 个缓存标记边界测试 |
| 专项 | `pytest tests/test_mail_triage.py` | 10 passed | 含 4 个批量分类测试（含红线） |
| 专项 | `pytest tests/test_graph.py` | 10 passed | 含 token 预算截断测试 |
| 专项 | `pytest tests/test_cli.py` | 7 passed | 含 4 个 CLI 走图的守卫测试 |
| 手工 | `python -m memoria --help` / `agent "测试"` | pass | 四子命令可见；agent 的 traceback 停在 router 节点，证明路由真实发生 |

**尚未做的验证**：本轮无浏览器验证（纯后端改动，未触及 UI）。`feat-041` 的 `cache_control` 未经真实 Anthropic 网关验证——仅离线断言了请求体结构。若要确认缓存实际命中，需用真实网关观察 `cache_read_input_tokens`。`/api/agent` 的邮件分支（停在人工确认中断并返回 thread_id）只有单元测试覆盖，未做过端到端手工验证。

## Commit State

**工作区脏，未提交。** 本次会话与上次会话的改动混在一起：

- 2026-09-27（本次）：`src/memoria/{wiki/ops.py, llm.py, graph/nodes.py, graph/state.py, mail/classify.py, mail/__init__.py}` + 5 个测试文件 + `docs/{UPGRADE_SPEC.md, ARCHITECTURE.md}` + `README.md`、`feature_list.json`、`progress.md`
- 2026-09-26（上次）：`frontend/src/components/ui/{SettingsModal.tsx, PillBadge.tsx, PillButton.tsx, RoundedCard.tsx}`、`frontend/src/types.ts`、`src/memoria/{net.py, web/*, rag/*}`、`tests/{test_graph.py, test_rag_ingest.py}` + 3 个新增 settings 组件

`git status` 中的其余后端改动（`net.py`、`web/{app,config}.py`、`rag/{__init__,ingest}.py`、`web/__init__.py`）**已核对，属 2026-09-26 的 ponytail 死代码清理**，对应 `progress.md` 中记录的：`_host_header` 死端口三元组（`_validate_url` 已强制 443，参数随之删除）、`rag/ingest.delete_document` 纯委托删除、`config._is_public_url(allow_empty=…)` 未使用参数、`web/__init__` 的 `create_app` 再导出、`app.py` 的 `except HTTPException: raise`。

即：**后端改动可干净地拆成两个提交**（2026-09-26 清理 / 2026-09-27 cache+cost），前端 `SettingsModal` 等属上次的 UI 重构。仍建议提交前完整过一遍 `git diff`，但不必再追查来源。

## Key Decisions

- **LangGraph 是正式生产编排器**（用户 2026-09-27 拍板，解开 `CODE_AUDIT_2026-09-24.md` 悬置三天的定位问题）。推论：不保留任何绕过图的第二条编排链路。`cli.py` 已改完；`lint` 是唯一仍直调 `wiki.lint` 的地方，因图中无对应分支，而它是只读文件审计而非编排。结构化端点预设 `intent` 以省掉 router 的 LLM 往返是有意设计，不是待清理的死代码。
- **Prompt 布局是性能约束，不是排版偏好**：provider 前缀缓存只在字节完全相同的前缀上命中，稳定内容必须排在变动内容之前。已写入 `ARCHITECTURE.md` §7.1。
- **缓存标记只发给确认支持的协议**：盲发给兼容端发陌生字段可能直接被拒。范围对齐 ZCode 的做法。
- **批量折叠调用不折叠红线判定**：`is_protected` 逐封独立执行，批量只作用于 LLM 分类摘要。
- **`history` 故意不用 reducer**：checkpointer 回放已传入累积 turns，节点内自行裁剪；加 `operator.add` 会双重累加。已在代码注释锁定，防止后人「顺手修正」。
- **不借鉴 deepseek 的 `Object.freeze` + 独立重算 invariant**：需事件溯源日志作为前提，改造量极大，缓存收益的九成可由稳定前缀 + 显式标记拿到。
- **不引入 tiktoken**：多一个依赖，字符估算够用。
- **不换 TypeScript**：约束不在语言层——LangGraph 是 Python 优先，ChromaDB/pypdf/Google API 客户端都是 Python 生态。五家 agent 选 TS 的真实原因是「一套代码喂 CLI + web + 桌面」，Memoria 的 FastAPI ↔ React 是干净的 HTTP 边界，不共享类型。

## Next Session Startup

1. 运行 `pwsh -NoProfile -File ./init.ps1`（Bash 下 `./init.sh`）。
2. 阅读 `AGENTS.md` → `docs/ARCHITECTURE.md`（注意新增第 7 节）→ `docs/UPGRADE_SPEC.md` → `feature_list.json` → `progress.md` → 本文件。
3. **先处理 Commit State**：逐个 `git diff` 确认来源不明的文件，再决定提交拆分。提交信息应区分 2026-09-26 的 SettingsModal 重构与 2026-09-27 的 cache/cost 工作。
4. **若继续 feat-045 的后续**：`/api/agent` 目前只有后端与测试，无前端入口。是否加 AskView 的自由文本模式由用户决定。
5. 剩余可选项：feat-038（多步 ingest 图循环）、feat-039（SSE 流式）—— 均为 `todo`，未被要求时不要动。
6. **可考虑的后续优化**（未登记为 feature，需用户确认）：`chat_completions` 路径的 `prompt_cache_key` 支持（需先确认目标网关）、embedding 向量缓存（当前每次查询都重新 embedding）、`KEEP_RECENT_TOKENS` 接真 tokenizer。

## Notes

- 红线不可动：验证码/交易邮件永不自动归档；`raw/` 只读；删文档必删全部向量；回答句级溯源；检索核心手写。
- 标准启动命令 `python run_web.py`，界面 http://127.0.0.1:8000
- GitHub 网络不稳定：优先 `raw.githubusercontent.com` 与 `api.github.com`，`github.com` HTML 常超时；`codeload.github.com` 可下 tarball。deepseek-harness 的默认分支是 `master` 而非 `main`。
