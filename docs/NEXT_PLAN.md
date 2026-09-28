# Memoria 下一步执行计划

> 制定时间：2026-09-28（ponytail-audit 全仓库审查完成后）
> 触发原因：对整棵代码树的 ponytail-audit 发现 8 项可削减点（净约 -485 行 / 0 依赖），
> 其中一项已在用户真实配置中造成可观察的腐化。基线：184 tests passed + 前端构建绿。

---

## 1. 本轮决策（审计发现 → 用户委托执行，此处记录拍板结果）

| 决策 | 结论 | 依据 |
|---|---|---|
| 旧 presets 子系统 | **删** | 前端 `api.ts` 零调用；单用户本地应用无仓库外消费者；`data/settings.json` 的 `presets` 为空数组。旧审计 6.1 悬置 4 天未获保留理由 |
| flat `GET/POST /api/config` 路由 | **删** | 前端只用 `/api/config/providers*`、`/api/config/models`、`/api/config/test`；flat 字段本身保留（env 回退 + active 镜像仍依赖） |
| localStorage 供应商镜像 | **删** | App.tsx 已使后端成为唯一事实源；镜像只剩初始帧防闪烁，却带来 8 处手工同步穿线 |
| 模型推导跨类型回退 | **删** | `data/settings.json` 实测已腐化：`active_chat_model = "BAAI/bge-large-zh-v1.5"`（硅基流动的 embedding 模型被当成对话模型激活）。严格按类型选取是根因修复 |
| 39 处 `dark:` 变体 | **删** | 全应用为浅色单主题（body/调色板/index.css 均无暗色设计），无切换开关；系统深色偏好下当前渲染为半深半浅的破碎 UI |
| `capability_status` 对 llm 增加 key 真实性检查 | **不做** | embed 侧检查源于 feat-049 事故；llm 侧占位 key 的失败模式是快速 401 而非静默超时，改语义会波及 feat-047..049 的测试契约。出现实害再做 |

## 2. 执行项

### feat-058 · 后端：配置双轨收敛与模型推导统一

1. **删 presets 子系统**：`/api/config/presets` 三条路由、`PresetSaveRequest`、`_public_preset`、
   `ModelPreset`、`Settings.presets` 字段及 `_sanitize_settings` 的 presets 清洗分支、
   `_public_settings`（唯一调用方是被删路由）、4 个 presets/flat 测试。
   旧 `settings.json` 中的 `presets` 字段由 pydantic extra=ignore 静默忽略，无迁移需求。
2. **删 flat 配置路由**：`GET/POST /api/config` 两路由及其测试（key 保留语义随路由消亡；
   provider 路由自身的 key 保留语义保留且有测试覆盖）。
3. **统一模型推导**（根因修复）：
   - `config.py` 新增 `pick_model_id(provider, model_type)`：返回第一个**启用的指定类型**
     模型 id，无则返回 `""` —— 不再跨类型回退（绝不把 embedding 模型激活为 chat）。
   - 新增 `resolve_active_chat_model(settings)`：active 选择器只有指向**该 active provider
     下真实启用的 chat 模型**时才被采信，否则回退到 `pick_model_id`。
     修复用户配置中已存在的 chat=embedding 腐化（health 与运行时一致地纠正）。
   - 替换 7 处重复推导：`activate_settings`（app.py）、`capability_status`（config.py）、
     `api_save_provider` / `api_delete_provider` / `api_save_provider_model` /
     `api_delete_provider_model` / `api_activate_provider`（config_routes.py）。
4. **杂项收缩**：`api_mail_triage` 每封邮件只调一次 `request_archive`（改用 `archive_candidate`
   属性）；`api_activate_provider` 两分支合并、响应 dict 只写一次；`llm.py` 抽
   `provider_auth_headers` 供 `build_chat_request` 与 `config._model_auth_headers` 共用；
   `mail/__init__` 去掉无人调用的 `is_transaction` / `is_verification` / `CATEGORIES` 重导出。

**行为变更声明**（均有测试背书）：(a) 无启用的 chat 模型时 active_chat_model 落 `""`
而非回退到任意类型模型；(b) active_chat_model 不属于 active provider 的启用 chat 模型时
按未配置处理并自动纠正；(c) 删除路由返回 404。

### feat-059 · 前端：状态源统一与死样式清理

1. **删 localStorage 供应商镜像**：5 个 storage key、`syncToLocalStorage` 及全部 8 处调用点、
   后端为空时的缓存回传迁移分支、`setProviders((prev)=>{副作用; return prev})` 变通写法。
   后端 `GET /api/config/providers` 是唯一事实源；打开设置时 loading 态已有。
2. **AskView 收敛**：两份提问表单抽为本文件内 `<AskInput>`（差异仅高度/阴影/占位符，
   以 size prop 表达）；约 120 行手写 localStorage 历史校验器（`isRecord`/`isCitation`/
   `isAskResponse`）缩为约 35 行宽容加载器（version 检查 + 最小形状过滤 + try/parse，
   坏档清空，写入端 `persistMessages` 不变）。
3. **删 39 处 `dark:` 变体**：ProviderDetailForm / ModelFormDialog / DeleteConfirmDialog /
   ProviderSidebar / SettingsModal。浅色模式下渲染零变化；深色偏好下从"半破碎"变为
   "一致的浅色"。

## 3. 本轮不做（已评估）

| 项 | 理由 |
|---|---|
| `capability_status` 的 llm key 真实性检查 | 见决策表；失败模式良性，避免波及 feat-047..049 契约 |
| `capability_status` 校验 active provider 的 enabled 态 | 同类语义扩张；enabled=False 时 activate_settings 已回退 flat 字段，无实害 |
| embed 侧选择器的类型归属校验 | 写入侧路由已只选 embedding 类型，观察到的腐化在 chat 侧；等出现实害再做 |
| feat-038 / feat-039 | 仍为 optional，未被要求 |
| `useProviderConfig` 表单回填 effect 的依赖数组 | 当前行为正确（靠切 provider/tab 触发），加依赖会在输入 key 时清空表单，反而变差 |

## 4. 验证方案

1. `python -m pytest -q` 全绿（新增 `pick_model_id` / `resolve_active_chat_model` 焦点测试，
   删除 4 个 presets/flat 测试，更新 2 个 load_settings 测试）
2. `cd frontend && npm run build` 通过
3. `pwsh -NoProfile -File ./init.ps1` 全量回归
4. **浏览器端到端验收**（Computer Use / control-browser，生产构建经 FastAPI 静态挂载）：
   - 安全前置：备份 `data/settings.json`；以 `MEMORIA_CHECKPOINT_DB` 指向临时文件启动，
     全程不触碰真实 checkpoints/chroma；真实 wiki 只读
   - 场景：首页渲染与就绪徽标 → 设置弹窗双栏 → 新建供应商（公网 HTTPS 校验）→
     手工加模型并激活 → embedding 页签激活 → health 徽标联动 → AskView 提问走真实
     链路（成功或优雅报错均为有效验收）→ Wiki 页渲染与反链 → Mail/Ingest 页渲染 →
     localStorage 无 `memoria_*_cache` 残留（feat-059 验证）→ UI 删除 E2E 供应商 →
     恢复 settings.json 备份
5. `feature_list.json` 登记 feat-058/059 + evidence；`progress.md`、`session-handoff.md`、
   `ARCHITECTURE.md`（API 面 / 行数 / 测试数）、`README.md`（测试数）同步

## 5. 执行顺序

```
feat-058 后端（删 → 统一 → 杂项）→ pytest
    ↓
feat-059 前端（镜像 → AskView → dark:）→ tsc + build
    ↓
文档与状态同步 → init.ps1 全量 → 浏览器端到端验收 → 提交
```
