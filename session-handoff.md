# Session Handoff

## Current Objective

- Goal: Maintain the full-stack Memoria personal knowledge system — React 19 + TypeScript + Tailwind frontend, FastAPI Web API, LangGraph orchestration.
- Current status: feat-001..feat-065 completed（除 feat-046 wont-fix，feat-038/039 为可选 todo）。2026-10-01 完成全仓库 ponytail-audit 整改（feat-065），净减 1263 行。
- Working tree: clean（全量 196 个单元测试通过，前端构建 100% 通过）。

## 本轮做了什么（2026-10-01）

0. **feat-065 全仓库精简（ponytail-audit 整改）**，三批独立提交：
   - 批次1 `95708cb` 文档与状态：删 CODE_AUDIT_2026-09-24 / UPGRADE_SPEC / NEXT_PLAN（1088 行，结论均已被后续提交反转，无人引用）；**保留 RAG_UPGRADE_PLAN.md**（检索评测基线 recall@4=3/3 MRR=1.00 的唯一出处，被 ARCHITECTURE.md:190 与 test_rag_eval.py:15 引用）；裁掉 progress.md 的 Evidence 段（内容在 feature_list 已有副本且测试数全过时）；`.agents/`（122KB vendored）取消跟踪并入 .gitignore。
   - 批次2 `0975041` 已证实的死代码：后端 `active_embed_model` 请求字段、`DocumentFrequency.size`、graph 的 `failed_ids`、`cli._graph` 的 `args`，以及 3 处永远取默认值的旋钮；前端 `useProviderConfig` 6 个零引用返回键（原本返回 79 键）、tailwind 10 个零引用色 + no-op borderRadius、types/api 15+ 个从未读取的响应字段、三份重复的 Props 接口、`ProviderEmptyState` 内联进 SettingsModal。
   - 批次3 `a5a7c4b` 结构重复：`api_save_provider_model` 与 `api_save_provider_models_batch` 合并到 `_apply_model_saves`（config_routes.py 547→514），保留「空 id 单个 400 / 批量跳过」「单响应带 model 键」「空批量 no-op」三条契约，并新增测试钉住它们。

   **审查建议但明确不做**（均已复核否决，理由见 feature_list.json feat-065 的 description）：
   - `CustomModel.tags` 被误判为死字段，实为 ModelFormDialog 的用户可编辑标签输入
   - graph/nodes.py 5 个闭包工厂改普通函数：LangGraph `add_node` 只传一个 `state`，改后只是把闭包搬进 graph.py 变成 5 个 lambda
   - 三处 modal 合一：实际只共用 overlay+panel 两层，ModalShell 本身反而更长
   - SegmentedNav 参数化：它是移动端底部导航（图标独占 44px），与 SettingsModal 的紧凑内联控件语义不同
   - net.py 传输层换 requests：SSRF 策略层，风险最高，留作独立一批

### 上一轮（2026-09-29）

1. **Phase 1 (feat-061) 启动自举与诊断放行**：
   - 冷启动自举激活：`create_app()` 加载 settings 后显式调用 `activate_settings(current_settings)`，内存运行时立即与 `settings.json` 对齐，重启后不再回退至环境变量空配置。
   - 向量测试放行空 LLM URL：解封纯向量连通性诊断 400 死锁。
   - 新建对话供应商显式激活：补齐 `api.activateProvider(..., 'chat')`。
   - 门禁安全：`/api/ask` 和 `/api/agent` 补齐 `_require("llm")`；禁止激活已禁用供应商。

2. **Phase 2 (feat-062) 出站协议与模型健壮性**：
   - `safe_request` 透明解压缩：支持 `gzip` 与 `deflate` 流式内存安全解压缩并带防 zip-bomb 保护，解封反代网关压缩响应；请求头自带 `Accept-Encoding: gzip, deflate, identity`。
   - `OpenAICompatibleEmbedder` 分块切片：按 16 批次请求向量，兼容缺省 index 字段响应；空输入快速返回 `[]`。
   - 推理模型兼容：`extract_chat_text` 兼容 `content is None`，优先读取 `reasoning_content` / `reasoning`（支持 DeepSeek-R1 / reasoner 等思考模型）。
   - 路径哈希规范化：`load_document` 强制执行 `Path(source).resolve()`，杜绝相对路径摄入导致的孤儿向量。

3. **Phase 3 (feat-063) 模型交互与类型一致性**：
   - 智能模型类型推导：前端拉取模型时根据 ID/Tag 自动识别 embedding 与 chat 类型，避免错类型全量导入污染。
   - 模型编辑弹窗类型切换：`ModelFormDialog` 支持显式切换 Chat 与 Embedding 类型并持久化。
   - 协议保持：向量页签保存供应商保留原 `api_format`。
   - 批量模型保存后端接口：`POST /api/config/providers/{provider_id}/models/batch`，前端“全部添加”一次性原子提交，解决并发竞争写损坏。

4. **Phase 4 (feat-064) 向量一致性与交互闭环**：
   - 向量重构接口：`ChromaStore` 新增 `reset_collection()`，提供 `POST /api/rag/reindex` 接口，在切换向量模型或维度不一致时，清空向量集合并重新切片向量化 `data/raw/` 现有全部原始文档。
   - Prompt 前缀缓存调优：RAG 问答与 Wiki 检索及问答将全局稳定的目录索引（`目录：`）与召回上下文（`资料：`、`页面：`）置于动态用户问题（`问题：`）之前，最大化利用现代 LLM Prefix Caching 降低延迟与成本。
   - 前端摄入页重建索引按钮：`IngestView.tsx` 文档库新增一键重建向量索引功能；`App.tsx` 首页模型选择器激活失败时弹出明确错误提示。

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| 后端全量 | `python -m pytest -q` | **196 passed** | 基线 195 → 196（+1 feat-065 契约测试） |
| 前端构建 | `cd frontend && npm run build` | green | 1607 modules transformed, 0 error |
| 全量回归 | `pwsh -NoProfile -File ./init.ps1` | green | pytest 196 passed + frontend build green |

## Commit State

- `95708cb` chore(harness): 清理已执行完的计划文档与状态文件膨胀 (feat-065 批次1)
- `0975041` refactor: 删除 ponytail-audit 证实的死代码 (feat-065 批次2)
- `a5a7c4b` refactor(config): 合并模型保存的重复路径 (feat-065 批次3)

## Next Session Startup

1. 运行 `pwsh -NoProfile -File ./init.ps1`（预期 196 passed + build green）。
2. 阅读 `AGENTS.md` → `docs/ARCHITECTURE.md` → `feature_list.json` → `progress.md` → 本文件。
3. 启动命令：`python run_web.py`。
