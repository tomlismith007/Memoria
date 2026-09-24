# Session Handoff

## Current Objective

- Goal: Maintain the full-stack Memoria personal knowledge system with React 19 + TypeScript + Tailwind CSS frontend, FastAPI Web API, and LangGraph orchestration.
- Current status: feat-001..feat-031 completed; feat-023 citation-integrity follow-up remains todo only.
- Working tree: contains audit cleanup, configuration route split, SettingsModal display split, minimal model-settings UI, and independent chat/embedding provider separation. The untracked `.zcode/` path remains unrelated; browser evidence is under `gui-test-screenshots/`.

## Completed This Session

- [x] feat-027: embedded Ponytail and harness discipline into `AGENTS.md`.
- [x] feat-028: removed confirmed dead code, consolidated repeated validators and mail categories, tightened HTTP ingest handling, and split 14 configuration routes into `src/memoria/web/config_routes.py`.
- [x] feat-029: extracted `ProviderTemplatePicker`, `ProviderSidebar`, and `DeleteConfirmDialog` from `SettingsModal.tsx` without moving state or async flows.
- [x] feat-030: simplified the model settings interface to match the requested minimal reference layout while preserving all Provider/Model behavior.
- [x] feat-031: removed manual chat/embedding model inputs and added independent chat and embedding provider tabs with separate activation state.

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| strict frontend types | `tsc --noEmit --noUnusedLocals --noUnusedParameters` | pass | 0 diagnostics |
| focused backend tests | `python -m pytest tests/test_web_api.py -q` | 33 passed | includes embedding/chat isolation |
| frontend build | `npm run build` in `frontend/` | OK | TypeScript + Vite production build |
| full init | `./init.ps1` | green | 103 pytest tests + frontend build |
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
4. Leave feat-023 as todo unless a separate implementation request is provided.
5. Standard verification command: `./init.ps1` on Windows/Pwsh, `./init.sh` on Bash.
