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
2. **Read this file** completely
3. **Read project docs if present** (`docs/ARCHITECTURE.md`, `docs/PRODUCT.md`, README, or equivalent)
4. **Run verification** (`./init.sh` on bash, `./init.ps1` on Windows/pwsh) to verify environment is healthy
5. **Read `feature_list.json`** to see current feature state
6. **Review recent commits** with `git log --oneline -5`

If baseline verification is failing, repair that first before adding new scope.

## Working Rules

- **One feature at a time**: Pick exactly one unfinished feature from `feature_list.json`
- **Verification required**: Don't claim done without running verification commands
- **Update artifacts**: Before ending session, update `progress.md` and `feature_list.json`
- **Stay in scope**: Don't modify files unrelated to the current feature
- **Leave clean state**: Next session must be able to run `./init.sh` immediately

## Required Artifacts

- `feature_list.json` — Feature state tracker (source of truth)
- `progress.md` — Session continuity log
- `init.sh` — Standard startup and verification path
- `session-handoff.md` — Optional, for larger sessions

## Definition of Done

A feature is done only when ALL of the following are true:

- [ ] Target behavior is implemented
- [ ] Required verification actually ran (tests / lint / type-check)
- [ ] Evidence recorded in `feature_list.json` or `progress.md`
- [ ] Repository remains restartable from standard startup path

## End of Session

Before ending a session:

1. Update `progress.md` with current state
2. Update `feature_list.json` with new feature status
3. Record any unresolved risks or blockers
4. Commit with descriptive message once work is in safe state
5. Leave repo clean enough for next session to run `./init.sh` / `./init.ps1` immediately

## Verification Commands

```bash
# Full verification (recommended)
./init.sh      # bash
./init.ps1     # Windows / pwsh
```

Required checks:
- `python -m pytest -q` (local: `./init.ps1` / `./init.sh`; CI: `.github/workflows/ci.yml` runs it on every push/PR)

## Escalation

If you encounter:
- **Architecture decisions**: Consult project architecture docs if present, otherwise ask user
- **Unclear requirements**: Check product/requirements docs if present, otherwise ask user
- **Repeated test failures**: Update progress, flag for human review
- **Scope ambiguity**: Re-read `feature_list.json` for definition of done; red lines are in `docs/ARCHITECTURE.md` § Invariants — when in doubt, stop and ask
