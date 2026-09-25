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

## Notes for Next Session

- Read `docs/ARCHITECTURE.md` first — it holds the full spec from the product brief.
- Red lines are absolute: no auto-archive, raw/ read-only, delete vectors on doc delete, cite every sentence.
- Standard launch command: `python run_web.py`.
- Standard verification command: `./init.ps1`.
