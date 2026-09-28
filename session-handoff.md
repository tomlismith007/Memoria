# Session Handoff

## Current Objective

- Goal: Maintain the full-stack Memoria personal knowledge system — React 19 + TypeScript + Tailwind frontend, FastAPI Web API, LangGraph orchestration.
- Current status: feat-001..feat-064 completed（除 feat-046 wont-fix）。2026-09-29 完成模型切换/设置治理 4 个阶段（feat-061 启动自举与测试放行、feat-062 出站协议与健壮性、feat-063 类型推导与批量保存、feat-064 向量重建与 Prompt 前缀缓存优化）全部闭环。
- Working tree: clean（全量 195 个单元测试通过，前端构建 100% 通过）。

## 本轮做了什么（2026-09-29）

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
| 后端全量 | `python -m pytest -q` | **195 passed** | 基线 184 → 195（+11 焦点测试） |
| 前端构建 | `cd frontend && npm run build` | green | 1607 modules transformed, 0 error |
| 全量回归 | `pwsh -NoProfile -File ./init.ps1` | green | pytest 195 passed + frontend build green |

## Commit State

- `147e996` fix(app): 服务启动自举激活、向量测试放行与显式激活修复 (feat-061)
- `acad141` fix(net): 支持响应透明解压缩、向量分批切片与推理模型兼容 (feat-062)
- `2d6e60b` fix(settings): 模型类型推导、表单类型切换与批量保存 (feat-063)

## Next Session Startup

1. 运行 `pwsh -NoProfile -File ./init.ps1`（预期 195 passed + build green）。
2. 阅读 `AGENTS.md` → `docs/ARCHITECTURE.md` → `feature_list.json` → `progress.md` → 本文件。
3. 启动命令：`python run_web.py`。
