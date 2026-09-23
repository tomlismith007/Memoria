# Session Progress Log

## Current State

**Last Updated:** 2026-09-22
**Active Feature:** all 8 features completed

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

### What's In Progress

- [ ] feat-008 RAG×Wiki integration — DONE (see below)

### What's Next

1. Real-key smoke test (MEMORIA_LLM_*/MEMORIA_EMBED_* with a compatible endpoint)
2. `git init` + initial commit (repo is not yet under version control)
3. Next scope (if any): CLI entry, scheduled email pull

## Blockers / Risks

- [ ] No `bash` on this Windows machine — `./init.sh` cannot run here; use `./init.ps1`. Risk: agent following AGENTS.md blindly runs init.sh and fails. Mitigation: AGENTS.md documents both.

## Decisions Made

- **LangGraph over LangChain LCEL**: system is a state machine (routing, multi-step ingest, human-confirm nodes), not a single chain.
- **Hand-write core retrieval** (~100 lines: vector search + rerank + generate); LangChain only for integrations.
- **Feature granularity**: 8 features, one at a time; red lines encoded in AGENTS.md § Red Lines.

## Evidence of Completion

- [x] feat-001: `python -m pytest -q` → green (smoke)
- [x] feat-002: `python -m pytest -q` → `8 passed` (tests/test_rag_ingest.py, offline)
- [x] feat-003: `python -m pytest -q` → `14 passed` (tests/test_rag_answer.py, offline)
- [x] feat-004: `python -m pytest -q` → `21 passed` (tests/test_wiki_structure.py, offline)
- [x] feat-005: `python -m pytest -q` → `28 passed` (tests/test_wiki_ops.py, offline)
- [x] feat-006: `python -m pytest -q` → `34 passed` (tests/test_mail_triage.py, offline)
- [x] feat-007: `python -m pytest -q` → `39 passed` (tests/test_graph.py, offline)
- [x] feat-008: `python -m pytest -q` → `44 passed` (tests/test_sync.py, offline)

## Notes for Next Session

- Read `docs/ARCHITECTURE.md` first — it holds the full spec from the product brief.
- Red lines are absolute: no auto-archive, raw/ read-only, delete vectors on doc delete, cite every sentence.
