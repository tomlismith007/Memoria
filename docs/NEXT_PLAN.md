# Memoria 下一步执行计划

> 制定时间：2026-09-27（feat-040..045 验收完成后）
> 触发原因：浏览器验收时发现 `/api/ask` 与 `/api/ingest` 全部 502，但 `/api/health`
> 仍返回 `{"status":"ok"}`。系统"报告健康但实际不可用"，且错误信息对用户不可行动。

---

## 1. 问题诊断

### 1.1 现象

浏览器验收时，`POST /api/ask` 与 `POST /api/ingest` 均返回 502：

```
摄入失败: [WinError 10060] 由于连接方在一段时间后没有正确答复或连接尝试失败。
```

而 `GET /api/health` 返回 `{"status": "ok", "version": "0.1.0"}`。

### 1.2 根因（已核实）

`data/settings.json` 的嵌入配置不完整：

| 字段 | 实际值 |
|---|---|
| `active_embed_provider_id` | `""`（空） |
| `active_embed_model` | `""`（空） |
| `embed_base_url` | `https://api.deepseek.com/v1`（回退值） |
| `embed_api_key` | 无有效凭据（实测 401） |

`rag/retrieve.py:43` 的 `embedder.embed()` 在问答与摄入路径上**必被调用**（混合检索
的向量侧），因此这两条路径必然失败。纯 wiki 路径与 chat 调用本身正常。

**已排除与本次改动的关系**：`data/settings.json` 未被 git 跟踪；feat-040..045 一行未碰。

### 1.3 真正的问题不是"配置坏了"，而是"坏了也没人知道"

配置缺失被三层静默兜底吞掉：

1. `config.py:71` — `embed_model` 空 → 默认 `text-embedding-3-small`
2. `config.py:23` — `embed_base_url` 空 → 默认 `https://api.openai.com/v1`
3. `app.py:197` — `api_key` 空 → 填字面量 `"no-key"`

结果是：用户看到的是一个指向 `api.deepseek.com` 的请求失败，而真实原因是
"你还没配置向量模型"。设置界面里「向量模型 → 暂无模型」这行提示与实际症状之间
没有任何联系。

`/api/health` 只检查进程存活，不检查依赖可用性，所以在系统完全不可用时仍报 ok。

---

## 2. 本轮目标

**让配置问题在发生时就可见、可行动，而不是伪装成网络故障。**

不做的事：无法替用户决定该用哪个 embedding 服务（商汤网关实测不提供
`/embeddings`：`sensenova-embedding` / `embedding-2` / `BAAI/bge-m3` 均 404）。
本轮只负责让缺口暴露得清楚。

---

## 3. 执行项

### feat-047 · `/api/health` 报告依赖就绪度

**问题**：恒返回 ok，不反映 LLM / embedding 配置状态。

**方案**：扩展为返回各能力的状态与原因，保持向后兼容（`status` 字段语义不变，
仍为 `"ok"`，新增 `capabilities` 明细）。

```json
{
  "status": "ok",
  "version": "0.1.0",
  "capabilities": {
    "llm":  {"ready": true,  "model": "...", "reason": ""},
    "embed": {"ready": false, "model": "", "reason": "未配置向量模型，请在设置中补充"}
  }
}
```

**就绪判定**：`embed.ready = bool(active_embed_model or embed_model 已被显式设置)`
且 provider 存在。仅检查配置，不发起网络请求（保持 health 快速、无副作用）。

**验收**：
- 已配置 chat、未配置 embed → `status` 仍 ok，`capabilities.embed.ready == false`
- 两者都配置 → 均为 true
- 既有 `/api/health` 测试仍绿（`assert resp.json() == {...}` 需相应放宽）

### feat-048 · 配置缺失时给出可行动的 502

**问题**：错误信息是 `WinError 10060`，用户不知道该去设置里改什么。

**方案**：`/api/ask` 与 `/api/ingest` 在调用图之前检查 embedder 就绪状态，
未就绪时直接返回明确的中文提示，而不是让请求跑到网络层超时。

```
502 {"detail": "未配置向量模型：请在「设置 → 向量模型」中添加并启用一个
embedding 供应商后重试。"}
```

**不吞掉真实错误**：仅在配置确实缺失时提前拦截；其他 502 仍带原始异常。

**验收**：
- embed 未配置 → 502 且 detail 含"向量模型"与"设置"
- embed 已配置 → 走原有路径，错误行为不变
- 既有 ingest/ask 测试全绿

### feat-049 · 前端在配置缺失时给出指向性提示

**问题**：设置页显示"暂无模型"，但问答页只显示原始错误，两者无关联。

**方案**：`App.tsx` 启动时拉一次 `/api/health`，若 `capabilities.embed.ready`
为 false，在问答与摄入视图显示一条可点击的提示条（引导到设置弹窗），
而非等用户提问后才看到 502。

**验收**：
- embed 未配置时，问答视图顶部出现提示条
- 点击提示条打开设置弹窗
- embed 已配置时不显示
- 前端构建通过，tsc 无新增诊断

### 文档同步
- `docs/ARCHITECTURE.md`：§7 新增"配置缺失必须早暴露"条目
- `README.md`：测试数字同步
- `progress.md` / `session-handoff.md`：记录本轮与 feat-047..049

---

## 4. 执行顺序

```
feat-047 /api/health 报告就绪度        ← 基础，后续项依赖它
    ↓
feat-048 后端 502 给出可行动提示
    ↓
feat-049 前端启动提示条
```

三项共用一个判定函数（放 `web/config.py`），避免三处各写一遍判断。

---

## 5. 验证与完成标准

- `python -m pytest -q` 全绿（当前基线 137）
- `cd frontend && npm run build` 通过
- 浏览器验收：清空向量模型配置 → 重启服务 → 访问首页应看到提示条；
  `/api/health` 应显示 `capabilities.embed.ready == false`
- 每项在 `feature_list.json` 填 evidence，`progress.md` 记证据

---

## 6. 本轮不做（已评估）

| 项 | 理由 |
|---|---|
| 内置默认 embedding（如本地 sentence-transformers） | 引入重依赖（torch），违反"标准库优先/不加依赖换几行代码"的准则；且用户已有可用网关，只需补配置 |
| 自动探测可用 embedding 模型 | 需遍历各 provider 的模型列表猜测，成本高、误判多，不如让用户显式选择 |
| feat-038 多步 ingest 图循环 | 与当前 502 问题无关，且是 optional；等本轮修完再看是否真需要 |
| feat-039 SSE 流式 | 同上。可在修完配置问题后评估：若用户在意首字延迟再做 |
| `/api/agent` 的前端入口 | 有价值但独立；建议在配置问题修完后单独一轮，避免混在一起难以验收 |
