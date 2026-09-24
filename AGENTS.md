# AGENTS.md

Project harness for reliable agent-assisted development.

Memoria = RAG 知识库问答 + LLM Wiki（知识复利）+ 轻量 AI 邮件分类，LangGraph 编排。
Full spec: `docs/ARCHITECTURE.md` (read it before implementing any module).

## Red Lines (never violate — see docs/ARCHITECTURE.md § Invariants)

- 验证码/交易邮件**永不自动归档**；任何归档必须人工确认
- `raw/` 只读不写
- 删文档必须删掉它的全部向量
- 回答必须带来源引用（哪句话来自哪篇文档哪一段）
- 检索核心自己手写；LangChain 只用 integrations；编排用 LangGraph

## Startup Workflow

Before writing code:

1. **Confirm working directory** with `pwd`
2. **Read this file completely**
3. **Read project docs if present** (`docs/ARCHITECTURE.md`, `docs/PRODUCT.md`, README, or equivalent)
4. **Run verification** (`./init.sh` on bash, `./init.ps1` on Windows/pwsh) to verify environment is healthy
5. **Read `feature_list.json` to see current feature state**
6. **Review recent commits** with `git log --oneline -5`
7. **Check `progress.md` and `session-handoff.md` for blockers, working-tree state, and the next step**

If baseline verification is failing, repair that first before adding new scope. On this Windows checkout, prefer `./init.ps1`; use `./init.sh` only where Bash is available.

## Operating Stance: Lazy Senior Developer

Use the Ponytail ladder after understanding the real flow. Stop at the first rung that holds:

1. **Does this need to exist?** Reject speculative scope (YAGNI).
2. **Is it already in this codebase?** Search for an existing helper, type, component, or pattern before writing anything.
3. **Can the standard library do it?** Prefer it over a new package.
4. **Can a native platform feature do it?** Prefer native HTML/CSS/browser/DB behavior over custom machinery.
5. **Is an installed dependency enough?** Do not add a dependency for a few lines of code.
6. **Can it be one line?** Use the smallest correct implementation.
7. **Only then:** write the minimum code that works.

This is a design discipline, not permission to skip reading. Trace the complete flow and inspect the relevant files before choosing the smallest change.

## Change Discipline

- **Understand before editing:** follow the actual callers, data flow, and user-visible path; grep every caller of a function being changed.
- **Fix root causes:** repair the shared boundary once rather than patching every symptom or sibling path.
- **Prefer deletion and reuse:** the fewest-file, shortest correct diff wins; no speculative interfaces, factories, config knobs, or scaffolding “for later.”
- **Do not simplify away safety:** preserve trust-boundary validation, error handling that prevents data loss, security, accessibility, and explicitly requested behavior.
- **Name deliberate shortcuts:** if a simple implementation has a real ceiling, add a concise `ponytail:` comment stating the ceiling and the upgrade path. Do not hide the limitation.
- **Avoid unrequested prose in code:** match surrounding naming, style, and comment density.

## Ponytail Review Modes

Use the companion Ponytail modes when their scope is explicitly useful, not by reflex:

- `ponytail-review` — inspect the current diff for unnecessary abstraction, duplication, and code that can be deleted.
- `ponytail-audit` — rank whole-repository simplification opportunities; do not run it for an unrelated narrow fix.
- `ponytail-debt` — harvest `ponytail:` comments into a deliberate debt ledger when shortcuts are being revisited.
- `ponytail-gain` — show benchmarked lazy-solution trade-offs; it is a comparison aid, not a promise about this repository.

These modes supplement the normal startup and verification workflow; they do not replace tests, security review, or the project red lines.

## Harness Model

The repository is a five-subsystem harness; keep all five aligned:

- **Instructions:** this file routes startup, invariants, scope, and done criteria.
- **State:** `feature_list.json` is the feature source of truth; `progress.md` and `session-handoff.md` preserve cross-session context.
- **Verification:** `init.sh` / `init.ps1` are the standard restartable checks; use the narrowest useful check while iterating, then the full entrypoint before claiming completion.
- **Scope:** choose exactly one unfinished feature, respect dependencies, and do not mark a feature complete without its defined behavior and evidence.
- **Lifecycle:** update state, record blockers, and leave the next session able to run the standard entrypoint immediately.

## Working Rules

- **One feature at a time:** pick exactly one unfinished feature from `feature_list.json` unless the task is explicitly harness maintenance.
- **Evidence before status:** a feature is not done without the requested behavior, relevant tests/checks, and recorded evidence.
- **Stay in scope:** do not modify unrelated files or silently expand requirements.
- **Non-trivial logic needs a check:** leave the smallest runnable regression check (an assert or focused test) for branches, loops, parsers, security paths, and money/data-loss paths.
- **Fail closed on uncertainty:** consult the architecture/product docs first; stop for architecture decisions, unclear requirements, destructive actions, or repeated failures that need human review.

## Definition of Done

A feature is done only when ALL of the following are true:

- [ ] Target behavior is implemented at the root cause
- [ ] Required verification actually ran (tests / lint / type-check / build)
- [ ] A focused check exists for non-trivial logic
- [ ] Evidence is recorded in `feature_list.json` or `progress.md`
- [ ] No known security, data-loss, or scope regression is introduced
- [ ] Repository remains restartable from the standard startup path

## End of Session

Before ending a session:

1. Update `progress.md` with current state and verification evidence
2. Update `feature_list.json` with the feature status
3. Refresh `session-handoff.md` when the current objective, blockers, or next step changed
4. Record unresolved risks or blockers
5. Review the diff and leave the repository clean enough for the next session to run `./init.sh` / `./init.ps1` immediately
6. Commit with a descriptive message once the work is in a safe state, if the user has requested a commit

## Verification Commands

```bash
# Full verification (recommended)
./init.sh      # bash
./init.ps1     # Windows / pwsh
```

Required checks:
- `python -m pytest -q` (local: `./init.ps1` / `./init.sh`; CI: `.github/workflows/ci.yml` runs it on every push/PR)
- Frontend build when applicable: `cd frontend && npm run build`

## Escalation

If you encounter:
- **Architecture decisions:** consult `docs/ARCHITECTURE.md`; ask the user if the docs do not decide it
- **Unclear requirements:** check product/requirements docs first; otherwise ask the user
- **Repeated test failures:** update `progress.md` and flag for human review
- **Scope ambiguity:** re-read `feature_list.json` for the definition of done and the red lines above
- **Destructive or external actions:** confirm before deleting data, publishing, sending, or changing user-visible state
