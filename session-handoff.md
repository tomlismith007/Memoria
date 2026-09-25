# Session Handoff

## Current Objective

- Goal: Maintain the full-stack Memoria personal knowledge system with React 19 + TypeScript + Tailwind CSS frontend, FastAPI Web API, and LangGraph orchestration.
- Current status: feat-001..feat-037 completed (2026-09-25 landed the whole mandatory roadmap: feat-023 citation integrity, feat-032 document deletion, feat-033 LangGraph wiring, feat-034 conversation memory, feat-035 LLM retry, feat-036 contradiction lint, feat-037 mail fact write-back). Every agent flow (ask/mail/ingest) runs through the compiled LangGraph graph with SqliteSaver persistence, per-conversation threads, and transient-error retry. Only optional enhancements remain: feat-038 (ingest graph loop) and feat-039 (SSE streaming).
- Working tree: clean as of 2026-09-25 — the 2026-09-25 roadmap (feat-023, feat-032..feat-037) is committed together with the settings-UI leftovers from the prior session (template removal landed separately in `feat(settings)`). Browser evidence lives untracked under `gui-test-screenshots/`; local agent tooling state stays untracked (`.zcode/`).

## Completed This Session

- [x] feat-023: citation integrity enforcement — `citations_complete()` per-sentence `[n]` coverage in `rag/answer.py` (trailing markers after 句号 glued to the preceding sentence; out-of-range refs do not cover), `[[页名]]` requirement in `wiki/ops.py query`, AND-combined flag on `HybridAnswer`, `citations_verified` in `/api/ask` response, amber 未溯源 warning badge in AskView.
- [x] feat-032: document deletion closed loop — `GET /api/documents` (raw files mapped to doc_ids via public `doc_id_for_origin` + `ChromaStore.documents()` chunk counts; `vector_only` section) and `DELETE /api/documents/{doc_id}` (purge all vectors → orphan paranoia guard → remove raw file → log.md, 404 unknown); IngestView document library with delete confirmation. No browser-evidence screenshots yet for feat-032 (API tests + build only).
- [x] feat-033: web API runs on the LangGraph graph — SqliteSaver checkpointer in `create_app` (serde allowlist registers Email/Triage; recompile after settings switch); qa node wraps `hybrid_answer`, ingest node dual-writes via `source_path`, router skips its LLM call on preset intent; mail archive = `interrupt` → `Command(resume)` on the triage `thread_id` (confirm node whitelists + re-checks protected); `latest_candidates` dual-track deleted; new dep `langgraph-checkpoint-sqlite`. No browser-evidence screenshots yet (API tests + build only).
- [x] feat-034: conversation memory — `history` in graph state (last 6 turns), qa node folds the transcript into the user message; conversation_id = graph thread (SqliteSaver persists across restarts); `/api/ask` accepts+returns conversation_id; AskView session id persisted in localStorage and rotated on 新建会话.
- [x] feat-035: LLM retry — `RetryPolicy(max_attempts=3)` on router/qa/mail_triage/ingest (transient-only); confirm node stays retry-free (interrupt). FlakyChat test proves 3-attempt recovery.
- [x] feat-036: contradiction lint wiring — `/api/wiki/pages?deep=true` runs the LLM contradiction check (default stays LLM-free); `lint.contradictions` in response; WikiView AI 矛盾检测 button + rose contradiction badges.
- [x] feat-037: mail fact write-back — `POST /api/mail/fact` (page traversal rejected, dedup via archive_fact, origin=mail:{msg_id}); MailView inline 摘录进 Wiki action for 通知/待办 mails.
- Roadmap note: only optional enhancements feat-038 (multi-step ingest graph loop) and feat-039 (SSE streaming) remain; each needs its own session if requested.
- [x] Roadmap: feat-032..feat-039 registered as todo in `feature_list.json` (document deletion closed loop → wire LangGraph into Web API → conversation memory → retry → wiki write-back → optional graph-loop/SSE).

- [x] feat-027: embedded Ponytail and harness discipline into `AGENTS.md`.
- [x] feat-028: removed confirmed dead code, consolidated repeated validators and mail categories, tightened HTTP ingest handling, and split 14 configuration routes into `src/memoria/web/config_routes.py`.
- [x] feat-029: extracted `ProviderTemplatePicker`, `ProviderSidebar`, and `DeleteConfirmDialog` from `SettingsModal.tsx` without moving state or async flows.
- [x] feat-030: simplified the model settings interface to match the requested minimal reference layout while preserving all Provider/Model behavior.
- [x] feat-031: removed manual chat/embedding model inputs and added independent chat and embedding provider tabs with separate activation state.
- [x] Template removal: deleted the provider template system (`ProviderTemplatePicker.tsx` and all `showTemplatePicker` wiring); "添加供应商" now opens a blank custom provider draft directly (`handleStartCreate`).
- [x] Model settings visual quieting: detail column unified to one width, model rows merged into a single divided container, borderless create-mode title, soft-gray sidebar selection, tightened spacing/radii. Verified via real-browser screenshots with temporary API-seeded data (settings.json restored afterward).

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| full init | `./init.ps1` | green | **118 pytest tests + frontend build** (roadmap 2026-09-25: +4 feat-023, +3 feat-032, +3 feat-033, +2 feat-034, +1 feat-035, +2 feat-036/037 net) |
| strict frontend types | `tsc --noEmit --noUnusedLocals --noUnusedParameters` | pass | 0 diagnostics |
| focused graph/web tests | `python -m pytest tests/test_graph.py tests/test_web_api.py -q` | 50 passed | interrupt/resume, router skip, SqliteSaver on-disk, conversation memory, retry, deep lint, mail fact, no-orphan-vectors red line |
| browser smoke | local `http://127.0.0.1:8000/` | pass | 1280×720 and 390×844 |
| browser evidence | `gui-test-screenshots/feat-029/`, `feat-030/`, `feat-031/` | archived screenshots | settings, templates, vector tab, desktop/mobile |

## Key Decisions

- Chat and embedding now use separate activation state: `active_provider_id/active_chat_model` and `active_embed_provider_id/active_embed_model`.
- Saving or activating an embedding provider no longer changes the chat provider or `llm_*` runtime fields.
- Manual chat/embedding model inputs were removed; chat models are selected through “使用” in the model list.
- The embedding provider API is fixed to OpenAI-compatible `/embeddings`; embedding-only connectivity tests skip the chat gateway.
- Switching embedding models may require rebuilding the existing vector index; index rebuild is intentionally out of scope.
- `SettingsModal` remains the state and side-effect owner; no Context, reducer, global store, or large provider hook was introduced.
- `feat-023` remains a plan-only entry; citation integrity is not implemented.

## Next Session Startup

1. Run `pwsh -NoProfile -File ./init.ps1` (or `./init.sh` on Bash).
2. Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `feature_list.json`, `progress.md`, and this file.
3. If continuing SettingsModal cleanup, extract only `ModelListItem` and `ModelFormDialog` as controlled display components; do not add a state hook yet.
4. Roadmap is complete except optional feat-038 (multi-step ingest graph loop) and feat-039 (SSE streaming) — pick one only if the user asks; otherwise maintain/verify per startup workflow.
5. Standard verification command: `./init.ps1` on Windows/Pwsh, `./init.sh` on Bash.
