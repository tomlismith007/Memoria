# Memoria 升级整改 Spec

> 基于五个开源 agent 项目的源码调研 + Memoria 现有代码核对。
> 调研对象：`zai-org/ZCode`、`deepseek-ai/deepseek-harness`、`earendil-works/pi`、
> `anomalyco/opencode`、`MiniMax-AI/minimax-code`。
> 本 spec 是跨会话的决策依据；执行状态记录在 `feature_list.json`（feat-040 ~ feat-046）。

---

## 1. 背景与目标

### 1.1 调研结论：五个项目如何管理 LLM 缓存

| 项目 | 稳定性策略 | 核心手法 |
|---|---|---|
| deepseek-harness | 涌现式（emergent） | 追加日志 + 纯函数投影 → 请求天然是前驱的追加扩展 |
| opencode | 不可变基线 | Context Epoch：system 前缀字节冻结，变更转为按时间追加的 System 消息 |
| pi | 单调增长 | 工具列表永不缩短，删除用对话内 `tool_removal` 块表达 |
| ZCode | 声明式 | `cacheHint: stable\|dynamic` 标注 → 编译成固定三段 system 消息 |
| minimax-code | 诊断式 | 抓原始请求体分类 `IDENTICAL/APPEND_ONLY/DIVERGED`，RFC 6901 指针定位断点 |

**deepseek-harness 最激进**（`packages/core/agent-loop/src/agent.ts:652` 对整个请求
`Object.freeze`，配 `invariant.ts:40` 独立重算比对）。其 Agent Note 明确写下了拒绝理由：

> Detect-and-report 只能在事后捕获违规；违规请求仍可构造并上线。拒绝之，取而代之的是
> 接口层不可表示性。

即：缓存前缀稳定性不是被管理出来的，而是被证明无法破坏的。

**minimax-code 的 `cachePolicyFingerprint` 有一处反直觉设计**（`prefix-comparator.ts:272`）
值得记住：它故意**排除 breakpoint 位置**参与指纹，因为把尾部断点前移到每条新消息是标准
友好写法，若当成策略变更，会把每一次追加都藏进新 epoch。

### 1.2 Memoria 的现状（已核对代码）

**事实 1 — 没有任何缓存标记。** `src/memoria/llm.py` 全文无 `cache_control`、无
`prompt_cache_key`。8 个 `llm.chat()` 调用点全部走裸 HTTP。

**事实 2 — prompt 结构本应友好。** 5 个 SYSTEM 常量均为模块级固定字符串：

| 常量 | 位置 | 内容特征 |
|---|---|---|
| `ROUTER_SYSTEM` | `graph/nodes.py:14` | 固定字符串 |
| `GATE_SYSTEM` | `sync.py:20` | 固定字符串 |
| `SYSTEM` | `rag/answer.py:13` | 固定字符串 |
| `SYSTEM` | `mail/classify.py:20` | 固定字符串（f-string 插值 `CATEGORIES`） |
| wiki 维护者 | `wiki/ops.py:50` | **内联字面量，未提取为常量** |

这五个都是天然可缓存前缀，却未被利用。

**事实 3 — 一处结构性反缓存。** `wiki/ops.py:43`：

```python
known = "\n\n".join(f"## [[{n}]]\n{body}" for n, body in pages.items() if body)
```

每次 ingest 把**全部现有页面正文**拼进 prompt，且排在 `material` 之后。ingest 改一次页面，
下一个字节就变。wiki 越大，重写越多，缓存命中率越低——与优化目标完全相反。

**事实 4 — 邮件分拣是 N 次往返。** `graph/nodes.py:61`：
`triages = [classify(e, llm) for e in emails]`，20 封邮件 = 20 次 HTTP。

**事实 5 — history 按轮数而非 token 截断。** `graph/nodes.py:37` 的
`state.get("history", [])[-6:]`。中英文混排下 6 轮可能 3k token 也可能 20k。

**事实 6 — 检索核心无需改动。** `rag/retrieve.py` 49 行手写混合检索，与本轮所有整改项
无关，保持原样。

### 1.3 目标

1. 让 LLM 前缀缓存真正生效，降低重复调用的成本与延迟
2. 消除 N+1 的邮件分类往返
3. 让上下文预算与 token 而非轮数对齐
4. 锁定既有设计决策，防止后续误改

**非目标（明确不做）**：不引入 LLM 工具调用；不做多用户；不引入 tiktoken；
不做架构门禁 CI（成本高、收益低，见 §6）。

---

## 2. 整改项总览

| ID | 名称 | 优先级 | 依赖 | 风险 |
|---|---|---|---|---|
| feat-040 | 拆分 wiki ingest prompt 为稳定前缀 + 变动后缀 | P0 | — | 中 |
| feat-041 | 发送显式缓存标记（cache_control） | P0 | feat-040 | 低 |
| feat-042 | history 改为 token 预算截断 | P1 | — | 低 |
| feat-043 | 邮件分类批量调用 | P1 | — | 中 |
| feat-044 | 锁定 history 的 reducer 决策 | P1 | — | 无 |
| feat-045 | router 死代码决策 | P2 | 需产品输入 | 低 |
| feat-046 | 架构门禁（评估后不做） | P2 | — | — |

**关键约束：feat-040 与 feat-041 必须成组交付。** 单独做任一项都无效——
feat-040 不做，feat-041 缓存的仍是每次全变的前缀；feat-041 不做，feat-040 省下的
token 仍全额计费。

---

## 3. 详细设计

### 3.1 feat-040 · 拆分 wiki ingest prompt

**问题**：`ops.ingest()` 把全部页面正文塞进 prompt，且位置在 material 之后。

**方案**：三段式组装，把「稳定且可缓存」的部分前置。

```python
# 稳定段：仅随页面增删变化，跨多次 ingest 高度重叠
index_block = "\n".join(f"- [[{n}]]" for n in sorted(pages))

# 选择段：按关键词相关性挑 top-K，避免全量正文进 prompt
selected = _select_relevant(pages, material, k=10)

# 变动段：仅选中页面的正文
bodies = "\n\n".join(f"## [[{n}]]\n{pages[n]}" for n in selected)
```

`_select_relevant` 复用 `rag/retrieve.py` 的 `keyword_score`，不新增算法。
它已实现中英文分词（CJK 走字符二元组），直接可用。

**prompt 最终形态**：

```
system(固定) | index_block(稳定) | material(变动) | bodies(变动)
```

**行为变更**：LLM 看到的现有页面从「全部」变为「top-10 相关」。
`_parse_sections` 仍只接受返回中出现过的页名，schema 不变。

**验收标准**：
1. 既有 3 个 ingest 测试（`test_ingest_writes_pages_rebuilds_index_logs`、
   `test_ingest_caps_at_max_pages`、`test_ingest_ignores_garbage_output`）全绿
2. 新增测试：页面数 > 10 时，断言发给 LLM 的 user prompt **不含**未选中页面的正文
3. 新增测试：`_select_relevant` 对中英文混合查询都能选出相关页
4. `wiki.append_log` 记录选中页数，便于事后观察选择质量

**风险与缓解**：选错页面会导致 LLM 漏更新。缓解：K=10 与现有 `max_pages=10` 对齐
（原本就是一次最多改 10 页，所以看到 10 页正文不算削减）；`index_block` 仍给出全量页面名，
LLM 知道有哪些页存在，可以主动要求未展开的页。

### 3.2 feat-041 · 发送显式缓存标记

**问题**：无标记。Anthropic 走隐式前缀缓存，前缀微变即整段失效。

**方案**：在 `build_chat_request` 按协议下发。

```python
if protocol == API_FORMAT_ANTHROPIC_MESSAGES:
    body["system"] = [{
        "type": "text",
        "text": system,
        "cache_control": {"type": "ephemeral"},
    }]
```

`chat_completions` 路径加 `prompt_cache_key`（按会话稳定值），需先确认目标网关支持——
**若不支持则不加，不要盲发**。

**范围限制（对齐 ZCode 的做法）**：ZCode 的
`providerOptionsForCacheControl` 无条件下发 `anthropic`，其他 provider 拿不到标记。
Memoria 用户可配任意公网网关，故**只在确认支持的协议上加**。

**验收标准**：
1. 新增测试：anthropic 协议下 `system` 为带 `cache_control` 的数组结构
2. 新增测试：`chat_completions` 路径不因不支持而报错
3. 既有 `normalize_api_format` / `build_chat_request` 测试全绿
4. 手动验证：设置页「测试连接」对 anthropic 网关仍成功

**风险**：低——只加字段不改行为。但**必须先做 feat-040**，否则缓存的是仍全变的前缀。

### 3.3 feat-042 · history 改为 token 预算截断

**问题**：`[-6:]` 按轮数截断，与 context window 无关。

**方案**：

```python
# ponytail: 字符估算，非真 tokenizer。升级路径是接 tiktoken。
KEEP_RECENT_TOKENS = 20_000   # 对齐 pi 的默认值
```

从尾部向前累加 `len(question) + len(answer)`，超出预算即停。中英文都按同一系数
（CJK 约 1.5 char/token，英文约 4 char/token，取 1.5 是保守侧）。

**验收标准**：
1. 既有 `test_qa_route_carries_history_for_follow_ups` 全绿
2. 新增测试：超长历史被截断到预算内，且保留最近轮次
3. 新增测试：短历史不被截断（不误伤）

**风险**：低。`ponytail:` 注释锁住估算的性质。

### 3.4 feat-043 · 邮件分类批量调用

**问题**：N 封邮件 N 次往返。

**方案**：一次调用返回多行，扩展现有 `_parse` 为 `_parse_batch`。
沿用 `classify.py:47` 已有的容错思路（正则抽取 + fallback）。

```
system(固定) | 邮件列表(变动)
→ "1. 类别：营销 / 摘要：..."
  "2. 类别：通知 / 摘要：..."
```

**必须保留的约束**：规则层先行不变。`classify()` 里的 `is_protected(email.subject, email.snippet)`
是红线保护，必须**逐封独立执行**，不能因为批量而跳过。批量只作用于 LLM 分类与摘要那一步。

**验收标准**：
1. 新增测试：10 封邮件只产生 1 次 LLM 调用
2. 新增测试：LLM 返回部分行时，缺失项走 fallback 而不崩溃
3. 既有 `test_mail_triage.py` 全绿
4. 既有红线测试全绿（受保护邮件仍不可归档）

**风险**：中——批量解析的容错比单条复杂。若实现受阻，可回退到「分批 5 封一次」。

### 3.5 feat-044 · 锁定 reducer 决策

**问题**：`state.py` 全字段无 reducer，`history` 靠 `[-6:]` 手工截断。
若有人给 `history` 加 `operator.add`，会变成双重累加（节点内已手动 `turns + [新]`）。

**方案**：只加注释，不改行为。

```python
# ponytail: history 故意不用 operator.add reducer。checkpointer 回放时已传入
# 累积的 turns，节点内手工截断后写回；加 reducer 会双重累加。
# 升级路径：改用 LangGraph add_messages 语义。
history: list  # 详见上方注释
```

**验收标准**：注释存在；`test_graph.py` 全绿。**风险**：无。

### 3.6 feat-045 · router 死代码（需产品决策）

**问题**：`app.py` 四个 `invoke` 全部预设 intent，router 的 LLM 分支生产从不执行。
`nodes.py:19` 的注释承认这是有意的，但 `graph.py:33-38` 的动态路由能力
从未在真实流量下被验证。

**两个方案**：

- **A（保守，推荐）**：保留 router，注释说明是为自由文本入口预留，
  并在 `feature_list.json` 记一条待办。若确实要加 `/api/agent` 端点则立刻实现。
- **B（激进）**：删掉 router 节点，`add_conditional_edges` 改静态边，
  承认「Web 按 endpoint 分流」这一事实。

**这不是技术问题，是产品定位问题。** 需与 `CODE_AUDIT_2026-09-24.md` 提出的
「LangGraph 是否必须成为正式生产编排器」一并决策。

**风险**：低，但**需人工拍板**，不由实现者决定。

### 3.7 feat-046 · 架构门禁（结论：不做）

ZCode 有 `architecture-policy.yaml` + `pnpm architecture:check` 机械强制
（单文件 ≤400 行、契约 ≤300 行、公开方法 ≤12、禁循环依赖），存量违规进 baseline。

**结论：不做。** 理由：Memoria 是单人项目，CI 门禁的维护成本高于收益。
改为在 `AGENTS.md` 加一条「单文件超 400 行需在 commit message 说明理由」，
用纪律替代门禁。本项标记为 `wont-fix` 并记录理由，避免下次重复讨论。

---

## 4. 执行顺序

```
第 1 组（必须成对）:
  feat-040 拆分 wiki ingest prompt
    ↓
  feat-041 发送缓存标记

第 2 组（可并行，互不依赖）:
  feat-042 history token 预算
  feat-043 邮件批量分类
  feat-044 reducer 注释

第 3 组（需人工决策）:
  feat-045 router 死代码
  feat-046 记为 wont-fix
```

---

## 5. 验证与完成标准

每项完成后必须：
1. `python -m pytest -q` 全绿（当前基线 118 passed）
2. 新增的针对性测试存在且通过（`AGENTS.md`：非平凡逻辑需要检查）
3. 在 `feature_list.json` 填 `evidence`
4. 在 `progress.md` 记录验证输出

整组完成时额外要求：
- `cd frontend && npm run build` 通过（本轮无前端改动，应仍然通过）
- README 的测试数字与实际一致

---

## 6. 明确不借鉴的设计

| 来源做法 | 为何不做 |
|---|---|
| deepseek 的 `Object.freeze` + 独立重算 invariant | 需事件溯源日志作为前提。Memoria 状态由 `SqliteSaver` 管、节点是同步函数，改造量极大。缓存收益的九成可由 feat-040/041 拿到 |
| pi 的 `failToolCallsFromTruncatedMessage` | Memoria **不用 LLM 工具调用**。8 个 `llm.chat()` 全是「给数据要文本」，无工具参数流，不存在参数被截断的场景 |
| ZCode 的 DAG 工具调度器 | 同上，无工具执行并发问题 |
| 引入 tiktoken 精确计数 | 多一个依赖。feat-042 的字符估算够用，有精度问题再上 |
| 架构门禁 CI | 见 §3.7 |

---

## 7. 参考

- 调研原始记录见会话记录；仓库地址：
  `github.com/zai-org/ZCode`、`github.com/deepseek-ai/deepseek-harness`（分支 `master`）、
  `github.com/earendil-works/pi`、`github.com/anomalyco/opencode`（分支 `dev`）、
  `github.com/MiniMax-AI/minimax-code`
- 相关既有文档：`docs/ARCHITECTURE.md`（技术选型）、`docs/CODE_AUDIT_2026-09-24.md`（待决问题）
