# Session Progress Log

## Current State

**Last Updated:** 2026-09-25
**Active Feature:** none — provider template system removed (custom-only provider creation); feat-023 remains the only todo feature

## Status

### What's Done

- [x] Harness initialized (AGENTS.md, feature_list.json, progress.md, init.sh, init.ps1, session-handoff.md)
- [x] `docs/ARCHITECTURE.md` v2: 6 节标准结构（系统目标→模块→数据流→选型→约束→非目标）；选型已定 Chroma + OpenAI 兼容接口 + Gmail 只读 scope
- [x] feat-001 DONE: pyproject + src/memoria, editable install OK, init.ps1 green
- [x] feat-002 DONE: src/memoria/rag/{parse,chunk,embed,store,ingest}.py; 8 passed
  - doc_id = hash(origin) → 同路径重 ingest 原子替换，无重复向量
  - delete → where={doc_id} 全删，无孤儿向量（红线✓）
  - search 返回 (doc_id, chunk, start) 引用三元组
  - Embedder 为 Protocol：Fake（测试/离线）+ OpenAI 兼容（env 配置）
- [x] CI: `.github/workflows/ci.yml` (push/PR 跑 pytest, py3.14)；AGENTS.md 已注明；无 CD（无部署目标，见非目标#5）

- [x] feat-003 DONE: rag/retrieve.py（向量+关键词重排，加权合分）+ rag/answer.py（[n]→引用三元组）+ llm.py（ChatLLM 协议，email 复用）; 14 passed
  - 无命中不调 LLM，直接返回"无法回答"（防幻觉，省调用）
  - 越界引用 [9] 自动丢弃
  - 中文关键词按 bigram 切分（\w+ 整串无交集的坑已修）
  - FakeChat（测试）+ OpenAICompatibleChat（env 配置）
- [x] feat-004 DONE: wiki/pages.py（Wiki 类 + extract_links + 默认 schema.md）; 21 passed
  - ensure_layout 建 raw//wiki/，schema 缺才写（用户改动永不覆盖）
  - write_page 路径钳制：非法名直接拒，raw/ 代码级不可写（红线✓）
  - build_index 从 [[链接]] 重生成 index.md；append_log 记变更
- [x] feat-005 DONE: wiki/ops.py（ingest/query/lint）; 28 passed
  - ingest：`## [[页名]]` 分节解析，超 max_pages(10) 截断并记 log；垃圾输出零写入
  - query：先读 index 选页（非法页名过滤），再带页正文回答
  - lint：断链+孤立纯静态；矛盾只查有链接关系的页对（有界 max_pairs），YES 才报
- [x] feat-006 DONE: mail/{rules,classify,gmail}.py; 34 passed
  - 规则层先行：验证码/交易 → protected，永无归档路径（红线✓，混合邮件保护优先）
  - LLM 分类（营销/通知/待办）+ 一句话摘要；垃圾输出回退 通知+snippet
  - archive 双门禁：仅营销+非保护 → candidate；archive 必须 confirmed=True（否则 PermissionError）
  - pyproject 新增 google-api-python-client；凭据归调用方，模块只收 service 对象
- [x] feat-007 DONE: graph/{state,nodes,graph}.py; 39 passed
  - router（LLM 一词分类，垃圾输入回退问答）→ qa / mail / ingest 三分支
  - 节点零重复逻辑：qa=rag.answer，mail=classify+request_archive，ingest=wiki.ingest+lint
  - confirm_archive 用 interrupt：无 pending 直接过；有 pending 则暂停等人工 resume（批准/拒绝双测）
  - mail_archive 只执行 approved 且在 pending 内的 id
- [x] feat-008 DONE: sync.py（dual_ingest/hybrid_answer/archive_qa/archive_fact）; 44 passed
  - 双写：IngestResult 加 text 字段，向量+Wiki 单次解析
  - 混合查询：Wiki 先行 → LLM 充分性门（默认 fallback 到 RAG，不冒薄答案风险）→ 细节合并，引用穿透
  - 沉淀：问归档 synthesis 页（问题消毒防路径逃逸）；邮件事实入页（重复摘录去重）
- [x] feat-009 DONE: cli.py + __main__.py（`python -m memoria {ingest|ask|lint}`）; 48 passed
  - 薄封装：argparse → sync/wiki 函数；真实客户端走 env（MEMORIA_CHROMA/WIKI/LLM_*/EMBED_*）
  - main(argv, deps) 可注入 fakes，离线可测
- [x] docs/DESIGN.md DONE: 圆角卡片 (rounded-2xl/3xl) + 胶囊按键 (rounded-full) + 温暖骨白与低饱和粉彩规范
- [x] feat-010 DONE: Web API service (FastAPI 暴露 /api/ask, /api/wiki, /api/mail, /api/ingest, 挂载静态前端); 55 passed total
- [x] feat-011 DONE: 前端工程搭建与 docs/DESIGN.md 胶囊/圆角卡片组件系统 (PillButton, RoundedCard, PillBadge, SegmentedNav, ConfirmModal)
- [x] feat-012 DONE: 问答与 Wiki 双向链接交互界面 (AskView 句级溯源切片展示与一键沉淀 Wiki; WikiView 索引与双向反向链接漫游)
- [x] feat-013 DONE: 邮件安全分拣中心与双写摄入界面 (MailView 交易/验证码物理级保护不提供归档，营销邮件强制人工弹窗二次确认；IngestView 拖拽上传与即时双写反馈)
- [x] feat-014 DONE: 对话历史流与富文本 Markdown 渲染引擎 (AskView 连续追问会话、自动滚动、行内 [[Wiki]] 词条与 [n] 引用芯片交互解析)
- [x] feat-015 DONE: 模型与环境变量设置抽屉 (SettingsModal 与后端 /api/config 接口，支持拉取可用模型与连通性延迟诊断)
- [x] feat-016 DONE: Gmail 本地 OAuth 鉴权工具 (scripts/auth_gmail.py 与 memoria/mail/auth.py 开箱即用生成凭据令牌)
- [x] feat-019 DONE: 本地 Web 安全边界（配置 Key 脱敏/空值保留、localhost CORS、邮件新鲜候选门禁、raw 路径穿越防护）；全量 70 passed，前端构建通过
- [x] feat-017 DONE: 配置历史预设（服务端最多 10 个快照、Key 脱敏响应、保存/应用/删除、旧配置兼容）；全量 73 passed，前端构建通过
- [x] feat-018 DONE: 问答历史 localStorage 持久化（版本化 envelope、刷新/Tab 恢复、归档状态、新建会话清空、损坏数据回退）；全量 73 passed，浏览器冒烟通过
- [x] feat-020 DONE: 移动端响应式 UI（窄屏图标导航、44px 触控、Header 收缩、五个页面长文本重排）；390/320px 无横向滚动，桌面导航无回归
- [x] feat-021 DONE: 统一 SSRF 安全出站层（公网 HTTPS/443、DNS 全结果校验与 IP pinning、同源重定向、identity/响应大小限制）；全量 92 passed
- [x] feat-022 DONE: 删除本地模型供应商路线，配置与出站统一公网 HTTPS/443；旧非法预设过滤，配置 API 即时拒绝 HTTP/localhost/非 443；全量 95 passed，前端构建通过
- [x] feat-024 DONE: 纯自定义供应商管理界面重构与刷新零丢失双重持久化；两栏式供应商布局（左侧供应商列表/状态指示点，右侧Base URL、格式、API Key及模型列表维护，模型测试与标签管理），后端 settings.json 与前端 localStorage 双重持久化，AskView 对话端当前模型展示与直接切换；全量 97 passed，前端构建通过 (0 errors)
- [x] feat-025 DONE: 供应商协议贯通；OpenAI 兼容 Chat Completions、Claude/Anthropic Messages、OpenAI Responses 三种协议可选并持久化，模型列表、连通性测试和实际聊天按协议构造请求；全量 102 passed，标准 init.sh 绿灯
- [x] feat-026 DONE: 彻底移除添加供应商弹窗，改为右侧面板直接内联新建；点击「添加供应商」直接在右侧进入空白表单模式，输入供应商名称、Base URL、协议与 API Key，直接调用「获取模型」一键拉取并选取模型，可在未保存前一键「测试当前配置」，点击「保存并生效供应商」自动落盘持久化并设为激活状态，提供「取消」按钮安全回退；全量 102 passed，前端构建 0 错误
- [x] UI 精细打磨: 提问对话框首屏居中沉浸、发送后平滑落底吸附、纤长胶囊外形 (h-11/12, max-w-4xl)、黑曜石黑 (#09090b) 圆形发送按钮、移除底部说明小字
- [x] Launcher: `python run_web.py` 一键启动全栈服务并在浏览器中自动打开
- [x] Harness & Verification: `init.ps1` 同时验证 101 项后端测试与前端 `npm run build`，100% 绿灯
- [x] feat-027: `AGENTS.md` 固化 Ponytail 最小实现阶梯、根因修复、复用优先、安全例外、harness 五子系统与证据闭环；`validate-harness` 100/100
- [x] feat-028: 按代码审查报告完成低风险死代码清理、重复配置校验收敛、邮件类别单一来源和 HTTP 入口收紧；将 14 个配置路由拆到 `web/config_routes.py`，保留运行时激活闭包与 API 契约；`init.ps1` 101 passed + frontend build green
- [x] feat-029: 将 ProviderTemplatePicker、ProviderSidebar、DeleteConfirmDialog 从 SettingsModal 拆为纯受控组件；主文件 1,932→1,642 行，状态/API/localStorage 仍集中；修复 390px Provider 头部与模型操作行挤压；`init.ps1` 101 passed + frontend build green，浏览器模板/侧栏/删除确认/移动端冒烟通过
- [x] feat-030: 按用户参考图将模型设置收敛为极简双栏；压缩标题/说明、去除重复徽章与重复入口、合并模型区、简化模板选择器和模型行；保留 Provider/Model 全部状态与 API 流程；`SettingsModal.tsx` 1,642→1,571 行；`init.ps1` 101 passed + frontend build green，1280px/390px 浏览器验收通过
- [x] feat-031: 删除对话/向量手填输入框；设置页新增对话模型与向量模型页签；后端新增 `active_embed_provider_id`，向量 Provider 保存/激活/删除与对话 Provider 完全隔离；embedding-only 连通性测试支持；全量 103 passed + frontend build green，1280px/390px 浏览器验收通过

### What's In Progress

- [ ] 无；feat-001..feat-031 已完成，feat-023 仅登记为 todo。

### What's Next

1. `SettingsModal` 下一刀仅拆 ModelListItem / ModelFormDialog 等纯展示区，不抽状态 hook
2. `feat-023` 仅登记引用完整性后续计划，尚未实现
3. 保持全套测试与 Harness 门禁（`./init.ps1`）100% 绿灯通过

## Blockers / Risks

- [ ] No `bash` on this Windows machine — `./init.sh` cannot run here; use `./init.ps1`. Risk: agent following AGENTS.md blindly runs init.sh and fails. Mitigation: AGENTS.md documents both.
- [ ] feat-019 残余边界：CORS 不是认证；`data/settings.json` 仍以本地明文保存 Key；邮件候选集合仅适用于单用户单 worker。
- [ ] feat-018 边界：localStorage 恢复的是前端时间线，不会自动作为模型上下文；未完成请求在刷新后不恢复。
- [ ] feat-029 残余边界：`SettingsModal.tsx` 仍有 1,762 行并集中 Provider/Model 状态与异步流程；后续仍应拆 `ModelListItem` / `ModelFormDialog` 纯展示区。
- [ ] feat-031 残余边界：切换向量模型不会自动重建既有向量索引；不同向量模型的维度/语义空间可能不兼容，需要人工重建或后续校验。

## Decisions Made

- **LangGraph over LangChain LCEL**: system is a state machine (routing, multi-step ingest, human-confirm nodes), not a single chain.
- **Hand-write core retrieval** (~100 lines: vector search + rerank + generate); LangChain only for integrations.
- **Feature granularity**: 31 features, one at a time; red lines encoded in AGENTS.md § Red Lines.
- **Minimalist Capsule Design**: Canvas `#FAFAF9`, Obsidian Black `#09090b` accents, `rounded-3xl` cards, `rounded-full` pills, zero decorative emoji / heavy drop-shadows.

## Evidence of Completion

- [x] feat-001: `python -m pytest -q` → green (smoke)
- [x] feat-002: `python -m pytest -q` → `8 passed` (tests/test_rag_ingest.py, offline)
- [x] feat-003: `python -m pytest -q` → `14 passed` (tests/test_rag_answer.py, offline)
- [x] feat-004: `python -m pytest -q` → `21 passed` (tests/test_wiki_structure.py, offline)
- [x] feat-005: `python -m pytest -q` → `28 passed` (tests/test_wiki_ops.py, offline)
- [x] feat-006: `python -m pytest -q` → `34 passed` (tests/test_mail_triage.py, offline)
- [x] feat-007: `python -m pytest -q` → `39 passed` (tests/test_graph.py, offline)
- [x] feat-008: `python -m pytest -q` → `44 passed` (tests/test_sync.py, offline)
- [x] feat-009: `python -m pytest -q` → `48 passed` (tests/test_cli.py, offline)
- [x] feat-010: `tests/test_web_api.py` 6 tests pass; 54 passed total
- [x] feat-011: `npm run build` in `frontend/` succeeds cleanly; design system complete
- [x] feat-012: AskView & WikiView with citations and backlinks implemented
- [x] feat-013: MailView & IngestView with protected safety rules and confirm modal implemented
- [x] feat-015: Settings drawer + /api/config runtime switching + 获取模型 (Fetch Models) & 测试连接 (Test Connectivity) 连通性诊断卡片 (58 pytest tests passed)
- [x] feat-016: scripts/auth_gmail.py + memoria/mail/auth.py turnkey Gmail OAuth helper
- [x] feat-019: `pwsh -NoProfile -File ./init.ps1` → 70 passed + frontend build green; config secrets redacted, empty keys preserved, CORS allowlist enforced, stale/unknown mail IDs blocked, unsafe ingest paths rejected
- [x] feat-017: `pwsh -NoProfile -File ./init.ps1` → 73 passed + frontend build green; up to 10 redacted server-side presets with save/apply/delete and legacy settings compatibility
- [x] feat-018: `pwsh -NoProfile -File ./init.ps1` → 73 passed + frontend build green; browser smoke verified refresh/tab restoration, citation and archive metadata, new-session clearing, and corrupt JSON fallback
- [x] feat-020: `pwsh -NoProfile -File ./init.ps1` → 73 passed + frontend build green; browser verification at 390×844 and 320×800 confirmed no page-level horizontal overflow across all views and Settings; desktop navigation preserved at 1280×720
- [x] feat-021: `python -m pytest -q` → 92 passed (baseline) + frontend build green; all direct requests.get/post call sites migrated to the SSRF-safe standard-library client
- [x] feat-022: `python -m pytest -q` → 95 passed; `npm run build` → OK; public HTTPS/443-only network/configuration policy, legacy filtering, API rejection coverage, and residue search clean
- [x] feat-024: `powershell -File ./init.ps1` → 97 passed + frontend build green; custom provider CRUD, model management, dual persistence in settings.json & localStorage, and active model switcher
- [x] feat-025: `./init.sh` → 102 passed + frontend build green; Chat Completions / Anthropic Messages / OpenAI Responses request matrices, provider protocol persistence, model-list and connectivity auth, legacy defaults, and unknown-format rejection
- [x] feat-026: `./init.ps1` → 102 passed + frontend build green (0 errors); SettingsModal inline right-panel creation workflow, draft model management, pre-save config test API, zero popup windows
- [x] feat-027: `AGENTS.md` harness review and update; `validate-harness.mjs` → 100/100; `./init.ps1` → 102 passed + frontend build green
- [x] feat-028: audit-driven cleanup and config route split; focused Web API tests → 31 passed; full `./init.ps1` → 101 passed + frontend build green; `git diff --check` passed
- [x] feat-029: SettingsModal first pure-UI split → 1,642 lines; strict TypeScript → 0 diagnostics; `./init.ps1` → 101 passed + frontend build green; browser smoke covered template picker, sidebar, delete confirmation, and 390px layout; evidence in `gui-test-screenshots/feat-029/`
- [x] feat-030: model settings visual simplification → 1,571 lines; strict TypeScript → 0 diagnostics; `./init.ps1` → 101 passed + frontend build green; browser acceptance at 1280×720 and 390×844 covered empty/template/provider/model views and delete confirmation; evidence in `gui-test-screenshots/feat-030/`
- [x] feat-031: chat/embedding separation; focused Web API tests → 33 passed; full `./init.ps1` → 103 passed + frontend build green; browser verified manual model inputs removed and vector tab at desktop/mobile; evidence in `gui-test-screenshots/feat-031/`
- [x] UI Refinements: Centered slender search bar, Obsidian black circular submit button, smooth bottom anchoring, 模型快速选择胶囊、网络耗时/诊断反馈卡片
- [x] Remove provider template system (2026-09-25): `ProviderTemplatePicker.tsx` deleted; `SettingsModal.tsx` 添加供应商 now enters a blank custom draft via `handleStartCreate`; `ProviderSidebar` prop `showTemplatePicker` removed and `onOpenTemplatePicker` → `onAddProvider`; `grep -rin template frontend/src` → 0 hits; `cd frontend && npm run build` → tsc + vite green
- [x] Model settings visual quieting (2026-09-25): unified detail column to `max-w-2xl`; model list merged into single `rounded-lg border divide-y` container with soft-gray active rows; create-mode name input now borderless inline text (no autoFocus box); sidebar selected state `bg-zinc-200/70` fill (no border/shadow); footer `border-t` removed and spacing tightened (space-y-5/p-6/pt-3); diagnostics/empty-state radii → `rounded-lg`. Verified in real browser with temp provider+models (restored after): desktop screenshots of populated form, model list, and draft state. Full `./init.ps1` → 103 passed + frontend build green
- [x] Ask page model badge fix (2026-09-25): AskView previously read `memoria_*` localStorage cache keys (unreliably synced by SettingsModal; `storage` event doesn't fire same-tab), so it fell back to 自定义供应商/默认模型. Now App.tsx owns the display: fetches `/api/config/providers` on mount and on settings-modal close, resolves active provider name + active chat model (`m.name || m.id`), passes `activeModelInfo` to AskView (both badge sites). Browser-verified: shows 商汤 / sensenova-6.8-flash-lite; `npm run build` green
- [x] Homepage model picker (2026-09-25): capsule badge is now a cascading selector (Cherry Studio-style per user reference) — trigger shows 当前模型 provider/model + chevron; menu lists current selection with check, provider rows with fly-out submenu of chat models (name + tags + current check), and 管理模型 opens the settings modal. Selecting calls `api.activateProvider(providerId, modelId, "chat")` then refreshes; submenu renders at menu root (NOT inside the overflow-y-auto list, which clipped it). Removed the 使用 button from SettingsModal model rows (activation now lives on the homepage; 设为当前 in more-menu kept). Browser-verified full switch flow glm-5.2 ↔ sensenova-6.8-flash-lite with backend sync; `./init.ps1` gate → 103 pytest passed + build green
- [x] Official LangChain/LangGraph agent skills installed (2026-09-25): 8 skills from `langchain-ai/langchain-skills` (official LangChain GitHub org, MIT) pinned to commit `f179d57c66da0911556ce4960b55dd1f3f3b8480` — ecosystem-primer, langchain-{fundamentals,middleware,dependencies,rag}, langgraph-{fundamentals,persistence,human-in-the-loop} (+ references/). Every file git-blob-sha1 verified against the official repo tree; provenance at `.agents/skills/.langchain-skills-install.json`. `npx skills` git clone failed (github.com:443 unreachable) so files were fetched via raw.githubusercontent and hash-verified instead; `npx skills ls` → all 8 recognized as project-local
- [x] Picker placement fix (2026-09-25): conversation-state badge sits above the bottom input, so its menu opened downward past the viewport (page scrollbar + clipped menu). `ModelPickerBadge` gained `placement` prop — bottom badge opens upward (`bottom-full mb-2`) with bottom-aligned submenu, and right-aligned menus fly the submenu LEFT (`sm:right-full`) to avoid horizontal overflow. Seeded a temp ask-history entry to reproduce the conversation state (removed after); verified no vertical/horizontal scrollbars with menu and submenu open; `npm run build` green
- [x] feat-023 citation integrity (2026-09-25): red-line enforcement — `rag/answer.py` new `citations_complete()` checks every sentence (CJK/latin/bullet split) carries an in-range `[n]`; sentence regex glues trailing markers after 句号 to the preceding sentence; `wiki/ops.py query` requires a `[[页名]]` source; `sync.py HybridAnswer` ANDs wiki+rag halves; `/api/ask` returns `citations_verified`; AskView shows amber 部分内容未溯源 badge when false. `./init.ps1` → 107 pytest (+4) + frontend build green; strict tsc 0 diagnostics
- [x] feat-034 conversation memory (2026-09-25): graph state gained history ([{question, answer}], last 6 turns); qa node folds prior turns into the user message as a transcript (all LLM backends/fakes stay single-turn; follow-ups resolve references); conversation_id = LangGraph thread_id, persisted by SqliteSaver across restarts; /api/ask accepts+returns conversation_id (auto-mints when absent); AskView generates, persists (localStorage), and rotates session_id on new-session. Graph-level test asserts the follow-up prompt carries the prior turn; web-level test asserts same-id memory, clean memory on a new id, and auto thread creation. `./init.ps1` → 116 pytest + frontend build green; strict tsc 0 diagnostics
- [x] feat-035 LLM retry (2026-09-25): graph LLM nodes (router/qa/mail_triage/ingest) carry langgraph RetryPolicy(max_attempts=3) — transient-only retries (connection/timeout/429/5xx); the interrupt-bearing confirm node is retry-free. FlakyChat test: two ConnectionErrors then success → ingest completes with llm.calls == 3. `./init.ps1` → 116 pytest + frontend build green; strict tsc 0 diagnostics
- [x] feat-036 contradiction lint wiring (2026-09-25): /api/wiki/pages?deep=true runs wiki_lint with llm (one call per linked pair; default stays LLM-free for cost), lint.contradictions in response; WikiView gained an AI 矛盾检测 button and rose contradiction badges in the lint banner. `./init.ps1` → 118 pytest + frontend build green; strict tsc 0 diagnostics
- [x] feat-037 mail fact write-back (2026-09-25): POST /api/mail/fact (page name rejects traversal, archive_fact dedups, origin=mail:{msg_id}) + MailView inline 摘录进 Wiki action for 通知/待办 mails (page + fact inputs prefilled from summary). Tests cover write+dedup+400. `./init.ps1` → 118 pytest + frontend build green; strict tsc 0 diagnostics
- [x] feat-033 wire LangGraph into Web API (2026-09-25): architecture red line landed — create_app compiles the graph with SqliteSaver (data/checkpoints.sqlite, check_same_thread=False, JsonPlusSerializer allowlist for Email/Triage) and recompiles after model settings change; /api/ask, /api/mail/triage, /api/mail/archive, /api/ingest(/file) all execute through the graph (web layer = HTTP<->state only); graph qa node now wraps hybrid_answer (wiki-first + rag fallback preserved), ingest node dual-writes via source_path (agent never writes raw/), router skips its LLM call when the caller presets intent; mail archive flows through interrupt -> Command(resume) keyed by triage thread_id; confirm node whitelists against pending_archive and re-checks protected; latest_candidates dual-track HITL deleted; MailView stores and returns thread_id. New dep: langgraph-checkpoint-sqlite 3.1.1 (pyproject updated). `./init.ps1` → 113 pytest (+3) + frontend build green; strict tsc 0 diagnostics
- [x] feat-032 document deletion closed loop (2026-09-25): red-line surface — `GET /api/documents` maps raw/ files to doc_ids via public `doc_id_for_origin` (sha256 of resolved path) + new `ChromaStore.documents()` chunk counts, with a separate `vector_only` section for URL-ingested or orphaned docs; `DELETE /api/documents/{doc_id}` purges ALL vectors, hard-fails if any remain, removes the matching raw file, and logs to log.md (404 unknown); IngestView gained a document library with delete confirmation. `./init.ps1` → 110 pytest (+3) + frontend build green; strict tsc 0 diagnostics
- [x] feat-040..044 LLM 缓存与调用开销整改 (2026-09-27): 基于五个开源 agent 源码调研（`zai-org/ZCode`、`deepseek-ai/deepseek-harness`、`earendil-works/pi`、`anomalyco/opencode`、`MiniMax-AI/minimax-code`）制定 `docs/UPGRADE_SPEC.md` 并执行 P0/P1 五项。`python -m pytest -q` → **130 passed**（+12）；`npm run build` green。
  - **feat-040 wiki ingest prompt 拆分**（缓存前提）：`wiki/ops.py` 新增 `_select_relevant()`，复用 `rag.retrieve.keyword_score`（已有 CJK 二元组分词，未新增算法）。`ingest()` 由「material + 全部页面正文」改为「稳定目录 index_block（仅页名）→ 变动 material → top-K 选中页正文」三段式，目录排最前形成可复用前缀；原布局每次 ingest 重写整个 prompt，前缀缓存永不命中。log 追加「展开 N/M 页正文」便于事后观察选择质量。
  - **feat-041 显式缓存标记**：`llm.py build_chat_request` 的 anthropic_messages 路径，system 由字符串改为 `[{type:text, text, cache_control:{type:ephemeral}}]`。**chat_completions / openai_responses 刻意不发**——无法假定用户自配的任意网关支持 `prompt_cache_key`，盲目下发等于给兼容端塞未知字段（对齐 ZCode 的处理范围）。
  - **feat-042 history 按 token 预算**：`graph/nodes.py` 新增 `_recent_turns()`，`KEEP_RECENT_TOKENS=20_000`（对齐 pi 默认值），系数 1.5 char/token 取 CJK 保守侧，替换原 `[-6:]` 轮数截断。已加 `ponytail:` 注释声明是字符估算非真 tokenizer，升级路径是接 tiktoken。
  - **feat-043 邮件批量分类**：`mail/classify.py` 新增 `classify_batch()`，`classify()` 单封签名保留（既有测试零改动）。`graph/nodes.py` 的 `[classify(e, llm) for e in emails]`（N 次 HTTP）→ 1 次。**红线：is_protected 仍逐封独立执行**，批量只折叠 LLM 调用；单封时回退到 `classify()` 以免白付批量 prompt 成本。
  - **feat-044 锁定 reducer 决策**：`graph/state.py` history 字段加 `ponytail:` 注释，说明故意不用 `operator.add`（checkpointer 回放已传入累积 turns，加 reducer 会双重累加），并给出升级路径。顺带修正同文件 docstring 的陈旧事实：原文写 MemorySaver，实际 `app.py` 用 SqliteSaver。
  - **实现中发现并修正的两处真实缺陷**：① `_parse_batch` 原按行独立解析，类别与摘要在不同行时会丢摘要——改为按编号跨行累积，由新增测试暴露；② `test_web_api.py` 的 `SmartChat` fixture 仍按单封格式回复，批量后 m2 营销邮件误判为不可归档——fixture 增加批量提示词分支。
  - **未做（已记录决策）**：feat-045 router 死代码（`app.py` 四个 invoke 全部预设 intent，router 的 LLM 分支生产从不执行）标记 `blocked`，需先回答「LangGraph 是否必须成为正式生产编排器」；feat-046 架构门禁 CI 标记 `wont-fix`（单人项目成本高于收益，改用 commit message 纪律）。
- [x] feat-045 LangGraph 正式生产编排器 (2026-09-27): 用户拍板「LangGraph 必须成为正式生产编排器」，解开 CODE_AUDIT 自 2026-09-24 起悬置的定位问题。方案 A 落地：`python -m pytest -q` → **137 passed**（基线 130，+7）；`npm run build` green。
  - **新增 `POST /api/agent`**：自由文本入口，**刻意不预设 `intent`**，由图内 router 节点调 LLM 决定分支。这是生产环境里唯一真正走通 `add_conditional_edges` 动态路由的路径——此前四个结构化端点全部预设 intent，router 的 LLM 分支只在测试中被执行过。响应按 intent 返回 qa / ingest / 邮件 三种形态；邮件分支停在人工确认中断并返回 `thread_id` 供 `/api/mail/archive` 续用，红线链路不变。
  - **CLI 全面改为经图编排**：`cli.py` 原先直调 `sync.dual_ingest` / `sync.hybrid_answer`，是第二条未经验证的编排链路。现 `ingest`/`ask` 改走 `compiled_graph.invoke`，新增 `agent` 子命令（CLI 侧的 router 入口）。`lint` 因图中无对应分支仍直调 `wiki.lint`——它是只读文件审计，不参与编排，不是第三条编排路径。
  - **结构化子命令继续预设 intent**：URL 与参数已表明意图，重问模型是纯浪费。跳过逻辑是有意设计，已改写 `nodes.py` 的 router 注释说明这点，避免后人误读为死代码。
  - **新增守卫测试**：`test_cli_runs_through_the_graph` 用 monkeypatch 让 `sync.hybrid_answer` / `sync.dual_ingest` 抛 `AssertionError`，若 CLI 哪天又绕过图会立刻失败——这比断言输出格式更能防回归。另有 router 触发/跳过、ingest 分支形态等 6 个测试。
  - **手工验证**：`python -m memoria --help` 列出四个子命令；`python -m memoria agent "测试"` 的 traceback 停在 `During task with name 'router'`，从侧面证明 CLI 确实把请求交给了 router 节点（网络失败是沙箱无网关所致，非缺陷）。
  - **浏览器验收（2026-09-27，ZCode 内置 Computer Use）**：`python run_web.py` 起服务后逐视图检查。四个标签页（问答与溯源 / 知识漫游 / 邮件安全 / 文档双写）全部正常渲染，无控制台报错、无布局破损；设置弹窗的对话模型页（6 个模型、当前 badge、测试/保存 footer）与向量模型页均正常，SettingsModal 的四文件拆分工作良好。UI 对后端 502 的错误呈现正确（显示红色「请求遇到问题」而非静默失败或白屏）。**真实 LLM 端到端验证通过**：直接调用商汤网关跑通 feat-040 改造后的 `wiki.ingest()`，LLM 编译出「服务 A / 续费政策 / 续费提醒日程」三个页面，界面上正确渲染出结构化 Markdown、Wiki Lint 诊断（0 断链 3 孤立页）与正/反向链接面板；`wiki.query()` 返回带 `[[页名]]` 引用的回答。
  - **验收中发现的既有配置缺陷（非本次改动引入）**：`data/settings.json` 的嵌入配置不完整——`active_embed_provider_id` 与 `active_embed_model` 均为空，`embed_base_url` 回退到 `https://api.deepseek.com/v1` 但无有效凭据（实测 401）。由于 `rag/retrieve.py:43` 的 `embedder.embed()` 在问答与摄入路径上必被调用，导致 `/api/ask` 与 `/api/ingest` 一律 502。设置界面「向量模型」页正确显示「暂无模型」，与文件状态一致。已确认：① 商汤网关不提供 `/embeddings` 端点（`sensenova-embedding` / `embedding-2` / `BAAI/bge-m3` 均 404）；② `data/settings.json` 未被 git 跟踪，本次改动一行未碰。**需用户在设置界面补一个可用的 embedding 供应商才能恢复问答与摄入**。验收产生的临时 wiki 页面与 raw 文件已清理。
- [x] feat-047..049 配置缺失早暴露 (2026-09-27): 承接上一条发现的 502。**真正的问题不是"配置坏了"，而是"坏了也没人知道"**：`/api/health` 报 ok 而系统完全不可用；配置缺失被三层静默兜底吞掉（`config.py` 的默认值、`app.py` 的 `"no-key"`），最终伪装成"连接超时"。计划见 `docs/NEXT_PLAN.md`。`python -m pytest -q` → **145 passed**（137 → 145，+8）；`npm run build` green。
  - **根因分析（决定了全部三项设计）**：`Settings` 的 `embed_base_url` / `embed_model` 带默认值（`text-embedding-3-small`），**无法从这些字段区分"用户选的"和"从没配过"**；真正的信号是 `active_embed_provider_id` / `active_embed_model` 这类空选择器。而 `create_app` 启动时根本不加载 settings（只在配置路由被调用时才读），所以健康检查对此完全失明。
  - **feat-047**：`config.py` 新增 `capability_status()` 作为唯一判定处（健康检查、端点守卫、前端提示条共用，避免三处各写一遍）；`create_app` 启动时 `load_settings()` 并跟踪 `current_settings`。`status` 字段语义不变（仍表示进程存活），新增 `capabilities` 明细。**实现中发现并修正的缺陷**：首版用 `embed_api_key and embed_model` 判就绪，被实际配置里的设置期占位串 `sk-1234567890` 骗过，导致 `/api/health` 仍报 `embed.ready: true`。补 `_key_is_real()` + `_PLACEHOLDER_KEYS` 后才正确。
  - **feat-048**：`app.py` 新增 `_require(capability)` 守卫，在 `api_ask` / `run_ingest`（含 `/api/ingest/file`）/ `api_agent` 的问答分支调用图之前校验。仅拦截配置确实缺失的情况；注入依赖（测试）与 demo mode 一律放行，其他错误不被吞掉。
  - **feat-049**：`App.tsx` 启动时与设置关闭后拉 `/api/health`，未就绪时在 main 顶部渲染琥珀色提示条（原因 + 「去设置」按钮）。**顺带修掉一个自相矛盾**：顶栏徽标原本恒显示绿点 +「本地就绪」，与提示条冲突，改为未就绪时显示琥珀点 +「配置待补全」。
  - **实测对比（同一份坏配置）**：修复前 `/api/ask` → 180 秒超时 + `[WinError 10060] 由于连接方在一段时间后没有正确答复`；修复后**即时**返回 `未配置向量模型：请在「设置 → 向量模型」中添加并启用一个 embedding 供应商后重试。`/api/health` 的 `capabilities.embed.ready` 由错误的 `true` 变为正确的 `false`。
  - **浏览器验收（ZCode Computer Use）**：提示条文案与后端 `reason` 完全一致；「去设置」点击后设置弹窗可见（Playwright `click()` 超时，改用 `cua` 坐标点击，与既有记录一致）；顶栏徽标已切换为琥珀点 +「配置待补全」，与提示条无矛盾。
- [x] Repo-wide ponytail cleanup (2026-09-26): audit-driven, zero-behavior-change pass.
  - **Test defect fixed**: `tests/test_graph.py` defined `test_qa_route_wiki_sufficient_and_router_skipped` and `test_ingest_route_source_path_dual_writes` twice (byte-identical); the later `def` shadowed the earlier one, so 11 definitions collected as 9 tests. Duplicates removed — still 118 total, but the 9 real ones now genuinely run.
  - **Backend dead code deleted**: `rag/ingest.delete_document` (pure delegate; the red-line test now calls `store.delete_document` directly), `web/__init__.create_app` re-export, `config._is_public_url(allow_empty=…)` param (never passed), `net._host_header` port ternary (dead — `_validate_url` already forces 443, so the param was dropped too), and `app.py`'s `except HTTPException: raise` (no `HTTPException` is raised outside `web/`).
  - **Frontend dead code deleted**: `export default SettingsModal`, `RoundedCard.hoverEffect` + `variant="flat"`, `PillButton.variant="wiki"` + `size="lg"`, `export` on `DocumentInfo`/`VectorOnlyDoc`/`WikiPageSummary` and the three self-referencing props interfaces. `SettingsModal` now imports the existing `DeleteConfirmTarget` instead of re-declaring the shape inline.
  - **Duplication removed**: 6 copies of the model-tag heuristic → one `deriveTag` helper (this fixed a real bug — the bulk-import path omitted the `|| id.includes("vl")` check, so `*-vl*` models were labelled Chat when imported via 全部添加); `handleTestConnection` + `handleTestModel` → one `runConnectionTest(modelId?)` (this deleted 28 lines of provably unreachable branches — both call sites render only under `selectedProvider || isCreatingNew`, so the 3rd/4th dispatch arms could never run); 4 copies of the HTTPS Base URL rule under 3 wordings → one `requireHttpsUrl`; 2 copies each of the tag-split expression and the model-form reset.
  - **SettingsModal split**: 1,695 → 148 lines. New `settings/useProviderConfig.ts` (logic), `settings/ProviderDetailForm.tsx` (detail JSX + empty state), `settings/ModelFormDialog.tsx` (add/edit modal). `SettingsModal.tsx` is now just the modal shell, header, tab strip, sidebar mount, render switch, and dialog mounts.
  - **Verification**: `python -m pytest -q` → 118 passed; `npx tsc --noEmit --noUnusedLocals --noUnusedParameters` → 0 diagnostics; `npm run build` → green. Also diffed every `className=` and every Chinese UI string between the pre-split file and the four new files — identical after reverting one agent-introduced `py-1`→`py-2` padding change on the create-cancel button.
  - **Deliberately out of scope** (user decision): the 5 unused preset/legacy `/api/config` routes were kept; backend structural rework (`activate_settings`, `test_model_connectivity`, `_first_chat_model`) and the view-layer shared components were deferred.
  - **Browser acceptance (2026-09-26, ZCode in-app browser)**: exercised the refactored settings modal end to end — detail view (sidebar, Base URL, API 格式 select, masked API Key + eye toggle, 6 model rows with test/edit/delete, 当前 badge, 测试/保存 footer); create mode (draft row in sidebar, borderless name input, default `https://`, 取消/创建 footer, 暂无模型 empty state); `ModelFormDialog` add-model modal (ID/name/tags fields, 6 preset chips, 保存模型); embedding tab (向量模型 active, both embedding-specific notes — 向量接口固定使用 OpenAI 兼容 /embeddings and the vector-index rebuild warning); `DeleteConfirmDialog` (确认删除模型？ with the model name interpolated, proving the imported `DeleteConfirmTarget` type). Tag-preset round-trip verified against the `splitTags` helper: `Chat, 128K` → `+视觉` → `Chat, 128K, 视觉` → clicking the already-present `+128K` correctly no-ops (dedup) → `+Embedding` → `Chat, 128K, 视觉, Embedding`. Cancel was clicked rather than confirming the delete, and `/api/config/providers` was re-read afterwards to confirm all 6 models (incl. `sensenova-6.8-flash-lite`) are intact. The reverted `py-1` padding was measured in the live DOM: class list contains `py-1`, computed padding 4px/4px, button 44×24px. The other 3 views (知识漫游 / 邮件安全 / 文档双写) render their content, RoundedCard empty states and PillButton actions unchanged. Mobile 390×844: no horizontal overflow anywhere on any view; the settings modal keeps its two-column layout (card 366px, sidebar 80px + detail 284px) and the model row's action buttons wrap cleanly.
  - **Tooling note**: in this IAB, Playwright `click()` timed out on every target while `cua.click` at the element's measured center worked; screenshots additionally required ~2 s of settle time to avoid catching the `animate-fade-in` mid-transition, and the screenshot backend wedged at 390 px until the tab was reopened. Layout claims were therefore verified by measured `getBoundingClientRect` / computed styles as well as pixels.

- [x] feat-050..054 RAG 检索质量升级 (2026-09-28): 基于 Context7 查得的 Chroma / LangChain 当前文档 + 代码实测探针制定 `docs/RAG_UPGRADE_PLAN.md` 并全部落地。`python -m pytest -q` → **182 passed**（145 → 182，+37）；`npm run build` green。**评测基线：MRR 0.83 → 1.00**（3/3 查询全部首位命中）。
  - **feat-050 评测基线（先有尺子）**：4 份主题互斥文档 + 3 条可判定查询，测 recall@4 与首个正确块排名。**方案经实测修正**：初稿用相同向量（flat embedder）隔离关键词项是无效的——向量相同时 `combined_score` 的向量项对所有候选相等，排序退化为 `store.search` 的任意返回顺序，重排根本没被测到（实测「苹果多少钱」正确文档 kw=0.25 却排在 kw=0.0 之后）。改用 FakeEmbedder 测真实混合管线。
  - **feat-051 语义边界切分**：`chunk_text` 原为纯固定窗口，实测在句子中间硬切（'...需要提前 30 天发起续费' 结尾断在句中）。改为在标点/子句边界切。**红线约束**：切点可变、偏移语义不可变，`chunk.text == source[chunk.start:chunk.end]` 在 size∈{50,80,120,200,400} × overlap∈{0,10,25} 全部组合下成立。
  - **feat-052 中文分词去噪**：**范围经实测收窄**——`re.findall(r'\w+')` 本身已按标点切分，跨句碎片本就不存在；句内碎片（`候需` vs `提前`）在无词典前提下字符层面同构、原理性不可解。故只做可解部分：过滤纯停用词 run。跨词碎片交由 IDF 处理。代码内 `ponytail:` 注释记录了该限制与升级路径。
  - **feat-053 IDF 加权**：`keyword_score(query, text, df=None)` 保留两参签名（缺省退化为原行为，`retrieve` 与 `wiki/ops._select_relevant` 两处调用点零改动）。平滑 IDF `log((N+1)/(df+1))+1`，`retrieve` 从候选池构建 DF 表。**效果实测**：feat-050 记录的唯一弱点「服务什么时候到期」从第 2 位升至第 1 位。
  - **feat-054 扩大 k：8 → 30**。**判断被实测推翻**：小语料（4 份文档）下 k 放宽无任何变化，一度下调优先级；构造 41 份文档、目标埋在第 20 位的语料后推翻——`k=8` **完全召回不到**（答案里没有任何「到期」内容），`k>=15` 命中第 3。延迟实测 2.35ms → 5.89ms，相对秒级 LLM 往返可忽略。`top_n=4` 刻意不变（它才是 LLM token 成本）。已由 `test_narrow_recall_window_finds_nothing` 锁定该失败模式。
  - **教训记录**：评测语料的规模决定结论的适用范围。小语料上的「无变化」不等于「无影响」——这条已写入 `ARCHITECTURE.md` §7.6。
  - **遗留未做**：query 向量缓存（多轮追问时重发）、Chroma `configuration` 迁移（旧写法仍可用非缺陷）、嵌入/响应缓存、jieba 等语义分词器（碎片已被 IDF 压低，若仍不够需重新讨论「检索核心自己写」红线）。

## Notes for Next Session

- Read `docs/ARCHITECTURE.md` first — it holds the full spec from the product brief.
- Red lines are absolute: no auto-archive, raw/ read-only, delete vectors on doc delete, cite every sentence.
- Standard launch command: `python run_web.py`.
- Standard verification command: `./init.ps1`.
