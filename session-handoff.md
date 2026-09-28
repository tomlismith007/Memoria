# Session Handoff

## Current Objective

- Goal: Maintain the full-stack Memoria personal knowledge system — React 19 + TypeScript + Tailwind frontend, FastAPI Web API, LangGraph orchestration.
- Current status: feat-001..feat-059 completed（除 feat-046 wont-fix）。2026-09-28 本轮完成 **ponytail-audit 全仓库审查 → 规划 → feat-058/059 执行 → 浏览器端到端验收** 全闭环。
- Working tree: clean（三个提交：feat-058 后端 / feat-059 前端 / 文档与状态同步）。

## 本轮做了什么（2026-09-28）

1. **ponytail-audit**：整棵代码树审查，8 项发现（净约 -485 行 / 0 依赖），报告在会话记录中；对照 `docs/CODE_AUDIT_2026-09-24.md` 确认其 15 项中 11 项已修复。
2. **规划**：`docs/NEXT_PLAN.md` 重写为本轮计划（含 6 项决策拍板与理由、"本轮不做"清单、E2E 方案）。
3. **feat-058 后端**：删 presets 子系统与 flat `GET/POST /api/config` 路由（前端零调用）；新增 `pick_model_id` / `resolve_active_chat_model` 统一 7 处重复推导，**禁止跨类型回退**；`provider_auth_headers` 抽取；`api_mail_triage` 去重复调用；`api_activate_provider` 分支合并；mail `__init__` 砍无调用重导出。
4. **feat-059 前端**：删 localStorage 供应商镜像（5 key + 8 处调用 + 迁移分支）；AskView 抽 `<AskInput>`、历史校验器 120→35 行；删 5 文件 72 处 `dark:` 变体。
5. **端到端验收**：详见 `progress.md` 2026-09-28 两条记录。要点：health 对用户真实配置**立即如实报告** `llm.ready:false`（自愈逻辑生效）；设置 CRUD 全流程、真实问答失败路径（假网关 DNS 快速失败 → 带原因的错误卡片）、localStorage 镜像零残留、历史加载器坏档/好档双场景、UI 删除闭环全部通过。
6. **feat-060 用户实测问题修复**（同日第二轮）：药丸点击=添加/选中（不再隐式激活）、后端激活跨类型 400 守卫、类型转换清空失效 embed 选择器。详见 progress.md 同日第三条。

## 用户配置两处待修（代码已自愈/已修，数据需用户在 UI 操作）

1. `data/settings.json` 的 `active_chat_model = "BAAI/bge-large-zh-v1.5"` 是硅基流动的
   **embedding** 模型（旧跨类型回退所致）。代码侧 health 如实报未配置 + 运行时自愈；
   用户在设置里把对话模型切回任一 chat 模型即根治。
2. 硅基流动的 15 个模型当初全部按 embedding 类型导入（含 Qwen 等真对话模型）。
   feat-060 之后：对话页签点药丸即可把错类型条目**纠正为对话模型**（upsert 语义），
   再点"使用"激活。
3. 取模型失败系用户本地代理 fake-IP DNS（198.18.0.0/15）被 net.py SSRF 防护拒绝——
   **用户明确要求不改代码**，代理关闭/换 redir-host 模式即恢复。

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| 后端全量 | `python -m pytest -q` | **184 passed** | feat-058 轮 182（-4 删 +2 增），feat-060 轮 +2（激活类型守卫、转换清空 embed 选择器） |
| 前端构建 | `cd frontend && npm run build` | green | CSS 37.84→35.25 kB、JS 327.90→323.56 kB（dark: 清理瘦身） |
| 全量回归 | `pwsh -NoProfile -File ./init.ps1` | green | pytest + build 全绿（feat-058 轮；feat-060 轮另行全量 pytest 184 + build） |
| 浏览器 E2E | control-browser，8010 端口生产构建 | 全场景通过 | 见 progress.md；settings.json 备份→还原，真实数据零污染 |
| API 联动 | `curl /api/health` | 通过 | 自愈报告（llm false）→ E2E 激活后双 ready + 模型名联动 |

**E2E 环境注意事项**（下轮浏览器验收直接复用）：Playwright `click()` 在 IAB 会因 actionability
等待超时；`cua`/`dom_cua` 间歇失灵；**evaluate 派发真实 DOM click 稳定**（React 输入用 native
setter + input 事件）；lucide-react 0.475 的 MoreVertical 图标类名是 `lucide-ellipsis-vertical`；
截图后端偶发卡死，重开标签页恢复；服务进程可能被外部终止（0xC000013A），重启即可。

## Key Decisions

- **presets/flat 配置面删除**（用户委托执行审计建议）：前端 api.ts 零调用 + 单用户本地应用；旧 settings.json 的 `presets` 字段由 pydantic extra=ignore 忽略，无迁移。被删路由现在 404。
- **推导统一语义**：`pick_model_id` 严格按类型、永不跨类型回退；`resolve_active_chat_model` 只信任指向 active provider 下真实启用 chat 模型的选择器。行为变更三条记录在 NEXT_PLAN.md，有测试背书。
- **保留 flat Settings 字段**（只删路由）：env 回退（`_environment_settings`）与 activate_settings 的 fallback 镜像仍依赖它们。
- **本轮明确不做**（勿重复讨论）：`capability_status` 的 llm key 真实性检查（401 失败模式良性，避免波及 feat-047..049 契约）；embed 选择器类型校验；表单回填 effect 依赖数组调整。
- **红线全部未动且有测试**：is_protected 逐封先行、confirm_archive 白名单、raw/ 路径钳制、删文档 paranoia guard、citations_complete、手写检索核心、safe_request 全覆盖。
- 沿用既定决策：LangGraph 唯一编排器；`history` 无 reducer；不引入 tiktoken；feat-038/039 仍 todo 未被要求。

## Commit State

```
fced0a2 docs(audit): 同步规划、架构与状态文件 (feat-058/059 收尾)
9e7f205 feat(audit): 后端为唯一事实源，前端去镜像与死样式 (feat-059)
7bd5db7 feat(audit): 删除 presets/flat 配置面，统一 active 模型推导 (feat-058)
```

合计 +522/−1040（净 −518 行）。

## Next Session Startup

1. 运行 `pwsh -NoProfile -File ./init.ps1`（预期 184 passed + build green）。
2. 阅读 `AGENTS.md` → `docs/ARCHITECTURE.md`（§7.5 新增第 5 条选择器信任规则）→ `docs/NEXT_PLAN.md` → `feature_list.json`（feat-058/059 含 evidence）→ `progress.md`（2026-09-28 三条）→ 本文件。
3. **建议转告用户**：在设置里把对话模型从 `BAAI/bge-large-zh-v1.5` 切回商汤任一 chat 模型（UI 一键），即根治配置腐化；届时 health 将显示双 ready，问答链路完整可用。
4. 剩余可选项：feat-038（多步 ingest 图循环）、feat-039（SSE 流式）——均为 `todo`，未被要求时不要动。
5. 未登记的可选优化（需用户确认）：embedding 向量缓存、`KEEP_RECENT_TOKENS` 接真 tokenizer、`/api/agent` 前端入口。

## Notes

- 红线不可动：验证码/交易邮件永不自动归档；`raw/` 只读；删文档必删全部向量；回答句级溯源；检索核心手写。
- 标准启动命令 `python run_web.py`（8000 端口可能被用户的旧进程占用——先 `netstat` 检查，必要时用 `--port 8010` 起验收实例，勿杀用户进程）。
- GitHub 网络不稳定：优先 `raw.githubusercontent.com` 与 `api.github.com`。
