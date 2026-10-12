# Talorys 核心设计 · 03 语义召回

> 研究对象：`rociiu/talorys` — 单用户个人 agent（Cloudflare Durable Object），v0.1.4，HEAD `2cc547c`
> 路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦：`apps/agent/src/semantic/` 全部 9 个文件——配置与阈值工程、向量存储、索引器、混合召回（RRF + 三层地板 + 拉入）、接缝设计、独立迁移轨道
> 本篇是全系列的核心篇：Talorys 的语义召回是既有研究中唯一完整给出"召回阈值工程"的样本

---

## 1. 定位与全景

语义召回是**默认关闭**的可选模块（`config.ts:50-55`，`enabled: false`）。关闭时 Talorys 的行为与从未安装该模块完全一致——模块通过 `RunnerExtensions` 接缝（`hooks.ts:8-13`）替换两处上游行为：记忆选择器与工具集。

```
开启后的每轮聊天
  │
  ├─ selectSemanticMemories(query)                        recall.ts:279-289
  │    ├─ runIndexer({maxEmbed: 50})   懒索引一批 pending  indexer.ts:91
  │    ├─ hybridSearch(query, limit: 8)                   recall.ts:138-161
  │    │    ├─ embedQuery（受每日上限保护）                 recall.ts:77-91
  │    │    ├─ scanVectors（三层地板）                      recall.ts:110-131
  │    │    ├─ keywordHits（上游 FTS5）                     recall.ts:142
  │    │    ├─ rrf（k=60 融合）                             recall.ts:63-71
  │    │    └─ pullInNewer（新版本拉入）                     recall.ts:178-223
  │    ├─ preference 保底 4 条（上游规则）                   recall.ts:283-286
  │    └─ applyM1（时近性排序 + saved 前缀）+ newer-wins 注   recall.ts:256-289
  │
  └─ semanticTools(ctx)   工具原位替换                       tools.ts:67-75
```

模块文件职责（9 个文件，约 1.3k 行）：

| 文件 | 行数 | 职责 |
|---|---|---|
| `config.ts` | 175 | 配置 schema、按模型默认值表、legacy 读取映射 |
| `embeddings.ts` | 180 | Embedder 接口、Workers AI 实现、Mock 实现、向量编解码、哈希、用量记录 |
| `vectorStore.ts` | 232 | 唯一的向量表 SQL 入口、缓存 tripwire、归一化/点积、迁移 v2 |
| `indexer.ts` | 189 | pending 判定、懒索引、并发纪律、后台索引/回填 |
| `recall.ts` | 289 | 三层地板扫描、RRF、pullInNewer、M1、完整选择链 |
| `migrations.ts` | 100 | 独立迁移轨道（track "slim"）、dropSemanticData |
| `routes.ts` | 231 | 配置/状态/搜索/重建 API、写路径中间件 |
| `tools.ts` | 75 | 工具原位替换（hybrid 搜索 + 写后索引） |
| `hooks.ts` | 13 | RunnerExtensions 接口 |
| `index.ts` | 76 | 扩展组装、never-enabled 缓存、安装器种子 |

## 2. 配置与阈值工程（`config.ts`）

### 2.1 配置四字段（10-25）

```ts
semanticConfigSchema = z.object({
  enabled: z.boolean(),
  model: z.string().regex(/^@(cf|hf)\/[\w.\-/]+$/, "Must be a Workers AI model id"),
  maxEmbeddingsPerDay: z.number().int().min(0).max(10_000),
  vectorFloor: z.object({
    absolute: z.number().min(0).max(1),
    relative: z.number().min(0).max(1),
    backstop: z.number().min(0).max(1),   // 注释：Lowest cosine for a top-k fallback hit; never above `absolute`.
  }),
})
```

默认值：`{enabled: false, model: "@cf/baai/bge-m3", maxEmbeddingsPerDay: 500, vectorFloor: {0.55, 0.1, 0.4}}`（50-55）。

### 2.2 按模型分别定默认值（31-45）

```ts
const BGE_M3_FLOOR: VectorFloor = { absolute: 0.55, relative: 0.1, backstop: 0.4 };
const BGE_EN_FLOOR: VectorFloor = { absolute: 0.5, relative: 0.1, backstop: 0.35 };
// 注释：Floor defaults per embedding model; the English bge models score higher cosines than bge-m3.
export const MODEL_FLOOR_DEFAULTS = {
  "@cf/baai/bge-m3": BGE_M3_FLOOR,
  "@cf/baai/bge-small-en-v1.5": BGE_EN_FLOOR,
  "@cf/baai/bge-base-en-v1.5": BGE_EN_FLOOR,
  "@cf/baai/bge-large-en-v1.5": BGE_EN_FLOOR,
};
export function floorDefaultsFor(model) { return {...(MODEL_FLOOR_DEFAULTS[model] ?? BGE_M3_FLOOR)}; }
```

**这是全部研究里最重要的设计之一**：不同 embedding 模型的余弦分布不同（bge-m3 压缩了分布，分数整体偏低；英文 bge 分数偏高），因此阈值**必须按模型分别定**，未知模型回落 bge-m3 值。换模型而不换阈值 = 召回质量静默退化。

### 2.3 legacy 读取映射（57-70, 105-107）

旧默认模型（bge-small 存的 0.5/0.1、无 backstop）**读取时**映射为新默认值，存储永不改写：

```ts
function isLegacyDefault(model, floor) {
  if (model !== LEGACY_DEFAULT_MODEL) return false;       // "@cf/baai/bge-small-en-v1.5"
  if (floor === undefined) return true;
  // 只有恰好是 {absolute: 0.5, relative: 0.1} 两字段时才算 legacy 默认
  return Object.keys(f).length === 2 && f.absolute === 0.5 && f.relative === 0.1;
}
```

读取逻辑（97-130）的关键分支：

1. key 不存在 → 返回 null（"从未启用"），除非传了 db 且能查到 key 存在但解析失败 → 返回 defaults（"启用过但值坏了"）。
2. 非对象 → defaults。
3. legacy 默认 → 映射为新默认模型 + 新默认地板。
4. 模型非法 → 回落默认模型（但保留 enabled）。
5. `backstop > absolute` 且**存储里确实有 backstop 字段** → defaults（配置非法）；若无该字段（backstop 是新增的）→ 把 backstop 降到 absolute（兼容旧配置）。

这套"读取时兼容、存储永不改写"的迁移纪律，让配置格式演进不需要写数据迁移。

### 2.4 写入校验（137-170）

`mergeSemanticConfig` 三个额外规则：

- **换模型且地板仍是旧模型默认值 → 地板跟着切到新模型默认**（142-146，`resetFloor` 条件）；自定义过地板则保留。
- `backstop > absolute` → `ValidationError`（154-156，明确报错而非静默）。
- `writeSemanticConfig` 在**启用时先建 schema 再写 key**（165-170，注释："enabling creates the schema before the key is written, so a failed migration never records the feature as on"）——顺序即正确性。

## 3. 向量存储（`vectorStore.ts`）

### 3.1 表结构（21-27, 迁移 v2）

```sql
CREATE TABLE tal_semantic_vectors (
  memory_id TEXT PRIMARY KEY, model TEXT NOT NULL, dims INTEGER NOT NULL,
  content_hash TEXT NOT NULL, vector BLOB NOT NULL, updated_at TEXT NOT NULL)
```

- **model + dims 双隔离**：跨模型或跨维度的行永不参与打分（`scanVectors` 只读当前 model+dims）。
- `content_hash`：SHA-256 of `content + "\n" + category`（`embeddings.ts:153-155`）——增量重嵌的判据。
- **v1→v2 迁移**（`VECTOR_TABLE_V2` 20-27）：base64 TEXT → 小端 Float32 BLOB，四步同事务：CREATE v2 → INSERT SELECT → DROP → RENAME；`convertLegacyVectors`（107-116）在同一事务里把 TEXT 行转 BLOB 并归一化。

### 3.2 向量表示：归一化 + 点积（59-76）

```ts
export function normalize(v) { /* 单位长度；零向量保持零 */ }
export function dot(a, b) { return a.length !== b.length ? 0 : Σ a[i]*b[i]; }  // 单位向量的余弦
```

**没有向量数据库**：归一化后余弦就是点积，暴力扫描。文档实测：5000 条记忆扫描 ≤5ms（`docs/semantic-recall.md`）。这是"个人规模下不引入向量库"的论据。

### 3.3 BLOB 绑定绕行（78-89）

```ts
/** Hex of the little-endian Float32 bytes, bound through `unhex(?)`: the upstream `Database`
 *  wrapper JSON-stringifies a typed array, so a BLOB cannot be bound directly. */
function toHex(v: Float32Array): string { /* ... */ }
```

上游 `Database.normalize`（`db/database.ts:33-38`）对非原始类型做 `JSON.stringify`——typed array 会被序列化成对象字符串。解法：手工转 hex，SQL 里 `unhex(?)`。这是**包装层与底层能力冲突时绕过包装**的范例，注释明确交代了原因。

### 3.4 缓存与 tripwire（44-53, 216-232）

```ts
interface VectorCache { model: string; dims: number; count: number; vectors: Map<string, Float32Array>; }
const caches = new WeakMap<Database, VectorCache>();   // 每 DO 一份

export function cachedVectors(db, model, dims) {
  const count = countFor(db, model, dims);              // SELECT count(*)
  const cache = caches.get(db);
  if (cache && cache.model === model && cache.dims === dims && cache.count === count) return cache.vectors;
  /* 重载 */
}
```

- **每次读先比行数**（`count` tripwire）：不一致即重载——捕获带外插入/删除（如直接 SQL 操作、并发请求），不需要版本号或失效通知。
- **写路径同调用更新缓存**（131-155）：`upsertVectors` 在事务提交后同步更新缓存与计数；`deleteVector` / `deleteAllVectors` / `purgeOrphanVectors` 同样（122-126 的 `forget` 保持计数一致）。
- 注释原文（4-12）："Every write below changes SQLite and the cache in the same synchronous call, so the cache never needs to expire. A read compares the cached row count with SQLite and reloads on a mismatch… an eviction simply loads again."
- 前提是 DO 的单实例 + 同步 SQLite 语义——**这是平台耦合部分，搬思想不搬机制**。

### 3.5 孤儿清理（174-182）

```ts
export function purgeOrphanVectors(db) {
  return db.all(`DELETE FROM tal_semantic_vectors WHERE memory_id NOT IN (SELECT id FROM tal_memories) RETURNING memory_id`).length;
}
```

- `RETURNING` 让删除与计数一步完成，同时返回被删 id 用于缓存同步。
- 孤儿来源：向量行比记忆行活得久（删除路径漏了、导入覆盖、崩溃）。每次索引 pass 开头先清（`indexer.ts:121`）。

## 4. 索引器（`indexer.ts`）

### 4.1 pending 判定（`pendingMemories` 39-52）

一条记忆需要（重新）嵌入的条件——四选一：

```ts
if (v?.model !== model || (dims > 0 && v.dims !== dims) || v.content_hash !== hash) pending.push(...)
// v 为 undefined（无行）也命中第一项
```

- 按 `updated_at ASC` 排序（39-43）——最旧的先嵌，保证长时间未处理的不被饿死。
- `contentHash` 是 async（WebCrypto），所以判定逐条 await；`embeddingText` = `content + "\n" + category`（`embeddings.ts:153-155`）。

### 4.2 并发纪律：单 pass + 单 follow-up（69-114）

```ts
interface IndexerState { running: Promise<IndexReport>; next?: FollowUp; }
const passes = new WeakMap<Database, IndexerState>();

export function runIndexer(ctx, {maxEmbed}) {
  const state = passes.get(ctx.db);
  if (!state) return startPass(ctx, maxEmbed);
  if (state.next) { state.next.ctx = ctx; state.next.maxEmbed = Math.max(state.next.maxEmbed, maxEmbed); }
  else { const next = {ctx, maxEmbed}; next.promise = state.running.then(() => startPass(next.ctx, next.maxEmbed)); state.next = next; }
  return state.next.promise;
}
```

- **每库至多一个运行中 pass + 一个排队 follow-up**（注释 81："so no memory is embedded twice"）。
- 运行中来新调用 → 合并进已有 follow-up（取最新 ctx 与更大 batch）——"a memory saved mid-pass is still embedded; later callers share that follow-up"。
- pass 结束前检查 `passes.get(ctx.db) === state && !state.next` 才清理（110-112）——避免清掉 follow-up 的状态。
- **永不 reject**（88）：embed 失败进 report 的 `error` 字段，记忆保持 pending 等下次。

### 4.3 单次 pass 的执行（116-162）

顺序：`config.enabled` 检查 → `ensureSemanticSchema` → **purge 孤儿** → 算 pending → 无 embedder 则 `skipped: "no-embedder"` → 无 pending 则返回 → **每日上限检查** → 截批 → embed → 校验向量数量与维度 → `upsertVectors`。

两个关键细节：

- **失败的 embed 调用也计入每日上限**（133-138）：

```ts
try { vectors = await embedder.embed(texts); }
finally { recordEmbeddings(db, day, 1, texts.reduce((n, t) => n + estimateTokens(t), 0)); }
// 注释：The call was made, so it counts against the cap even when it failed.
```

防错误重试风暴烧穿免费额度——这是"成本防线也要防自己"的范例。

- **向量校验**（139-141）：数量与维度不符直接抛错（进 report.error），不落库部分结果——批量要么全成功要么全 pending。

### 4.4 后台入口（164-189）

- `startBackgroundIndex`：不 await 的索引 + `waitUntil` 交接（runtime 支持时）；失败只 warn。
- `startBackgroundBackfill`：**循环批处理**直到无 pending / 触顶 / 空批 / 失败——用于换模型或启用后的全量回填。

## 5. 混合召回（`recall.ts`）

### 5.1 查询嵌入的降级（`embedQuery` 77-91）

```ts
if (!embedder) return null;                                        // 无 embedder
if (embeddingsToday(db, day) >= config.maxEmbeddingsPerDay) return null;  // 触顶
try { ... } catch { console.warn(...); return null; }              // AI 错误
finally { recordEmbeddings(db, day, 1, estTokens(query)); }         // 调用即计数
```

三种失败全部返回 null → 召回降级为**纯关键词**（`hybridSearch` 里 `queryVector && embedder ? scanVectors(...) : []`，141）。**召回永不因语义层失败而失败**。

### 5.2 三层地板扫描（`scanVectors` 110-131）

```ts
const { absolute, relative, backstop } = ctx.config.vectorFloor;
// 1. 全量点积（只扫当前 model + dims 的缓存向量）
// 2. 排序：余弦降序 → updated_at 降序 → id 升序
// 3. 保留：top 命中 ≥ absolute，且所有保留项 ≥ absolute 且 ≥ top.cosine - relative
const kept = top && top.cosine >= absolute
  ? all.filter(s => s.cosine >= absolute && s.cosine >= top.cosine - relative) : [];
// 4. 不足 FALLBACK_K=4 时用 backstop 补足
if (kept.length < FALLBACK_K) { /* 从剩余里取 ≥ backstop 的，按序补，跳过记忆已消失的行 */ }
return kept.slice(0, CANDIDATES_PER_LIST).map(...);   // CANDIDATES_PER_LIST = 50
```

三个地板的分工：

| 地板 | 值（bge-m3） | 作用 |
|---|---|---|
| `absolute` | 0.55 | **绝对下限**：最高命中都低于它 → 整个向量列表为空（"这个问题与记忆无关"） |
| `relative` | 0.1 | **相对下限**：保留项必须距最佳命中 0.1 以内（防止"最佳 0.56、次佳 0.42"时把弱命中当相关） |
| `backstop` | 0.4 | **兜底**：合格命中不足 4 条时放宽到 0.4 补足——语义相近但分数低的记忆仍有出场机会 |

**实测依据**（注释 93-100，日期 2026-10-10，bge-m3）：

> 网球问题（"我能像常人一样打网球吗"）对 "I only have one arm" 打 0.427、对 "I have no arms" 打 0.435——都低于 0.55 地板，靠 backstop 补进来。
> 登山问题对 "I'm afraid of heights" 打 0.512、对 "My knee surgery was in August" 打 0.409——同上。
> "what's the capital of France?" 最高 0.384——低于 backstop，保持为空（不硬凑）。
> 问候语（"hello"）最高约 0.51——会带进最多 4 条低相关记忆（已知局限）。

这段注释是**阈值可审计性的完整样本**：每个数字有正例（应该召回）与反例（应该为空），换模型时照着这些例子重测即可。

补足细节（122-129）：跳过 `updated === null` 的行（记忆已消失、等待 purge）——**悬空向量不占 fallback 名额**。

### 5.3 RRF 融合（63-71, 138-161）

```ts
export function rrf(lists: string[][], k = RRF_K): Map<string, number> {
  for (const list of lists) list.forEach((id, i) => scores.set(id, (scores.get(id) ?? 0) + 1 / (k + i + 1)));
}
```

- **k=60**（`RRF_K`，经典取值）；1-based 排名；出现在多个列表的 id 分数累加。
- 融合两个列表：向量命中（≤50 条）+ 关键词命中（`services.memories.search(query, 50)`）。
- 平局裁决链（153-159）：fused 分 → 余弦 → updated_at 新 → id 小。
- 记忆查找双路（150）：`memories.get(id) ?? ctx.services.memories.get(id)`——关键词命中已带行数据，向量命中需回查（注释："A vector row can outlive its memory until the next indexer purge"）。

### 5.4 pullInNewer 新版本拉入（178-223）——本篇最重要机制

**问题**：记忆库里"我开特斯拉"（旧）与"我卖了特斯拉换了大众"（新）是两条独立条目。查询命中的可能是旧的那条——模型只看到旧事实，回答错误。

**解法**：每个被选中的命中，检查是否有**严格更新且语义高度相似**的记忆，有就一并拉入：

```ts
for (const puller of [...out]) {
  const own = vectors.get(puller.memory.id);
  for (const [id, vector] of vectors) {
    if (seen.has(id) || vector.length !== own.length) continue;
    const c = dot(own, vector);
    if (c < threshold) continue;                        // threshold = newerDuplicateCosine(model)
    const memory = ctx.services.memories.get(id);
    if (memory && isNewer(memory, puller.memory)) candidates.push({memory, cosine: c});
  }
  candidates.sort(/* 余弦降序 → id 升序 */);
  for (const {memory} of candidates.slice(0, MAX_NEWER_PER_HIT)) {  // 至多 2 条
    /* 插到 puller 之后；列表满时丢弃最弱的"未拉入任何东西"的命中 */
    const hit = {memory, cosine: null, fused: puller.fused};         // 继承 puller 的 fused 分
    out.splice(at++, 0, hit); seen.add(memory.id); pulled.add(hit); pullers.add(puller);
  }
}
```

阈值按模型实测（22-38）：

```ts
export const NEWER_DUPLICATE_COSINE = 0.7;
/* 注释：Measured on bge-small: Bug/Tesla 0.72-0.79 and Portland/Denver 0.748 pull in;
   Porsche/Bug 0.523, Porsche/Tesla 0.589 and vegetarian/jazz 0.684 do not. */
export const NEWER_DUPLICATE_COSINE_BY_MODEL = { "@cf/baai/bge-m3": 0.57 };
/* 注释：bge-m3 compresses its cosines: Bug/Tesla 0.579-0.654 and Portland/Denver 0.767 pull in;
   Porsche vs the car memories 0.524-0.554 do not. Unrelated preference pairs reach 0.60-0.78,
   accepted because preferences are padded in anyway. */
```

**注释坦白承认了误报**：bge-m3 下无关的偏好对余弦可达 0.60-0.78，会触发拉入——但接受这个代价，因为偏好类记忆本来就会被保底注入（拉入不增加多少噪声）。这是"知情的取舍"而非疏漏。

约束与细节：

- **只用缓存向量，零 embed 调用**（176）——拉入不产生额外成本。
- **拉入者继承 puller 的 fused 分**（215）：不改变排序位置；拉入的记忆**不再二次拉入**（`pullers` / `pulled` 集合，186）。
- `isNewer` 判定（166-168）：`updated_at` 更晚，或同 updated_at 但 `created_at` 更晚。
- 列表满时（202-213）：从尾部往前找第一个"不是 puller、不是被拉入、也不是拉入者"的命中丢弃；找不到则跳过本次拉入（"when there is none the pull is skipped"）。
- 只比较**等长向量**（193，`vector.length !== own.length`）——维度未知时也不误比。

### 5.5 时近性格式化与冲突提示（225-272）

**M1（applyM1，256-263）**：排序新者优先（updated_at → created_at → id），每条内容前缀：

```
(saved 2026-10-10 14:05 PDT) 我卖了特斯拉换了大众
```

- `savedAt`（239-250）用 `Intl.DateTimeFormat("en-CA", {...hourCycle: "h23", timeZoneName: "short"})` 的 `formatToParts` 拼 `YYYY-MM-DD HH:MM TZ`；未知时区回落 UTC；裸 "GMT" 显示为 "UTC"。
- **前缀成本 ~10 token/条**，换来模型对每条记忆的时间感知。

**newer-wins 提示（21, 265-272）**：≥2 条记忆时，列表末尾追加一行**伪记忆**：

```ts
export const NEWER_WINS_NOTE = "If two memories conflict, the more recently saved one is current.";
export function newerWinsNote(): Memory {
  const epoch = "1970-01-01T00:00:00.000Z";
  return {id: "semantic-newer-wins-note", content: NEWER_WINS_NOTE, category: "other", source: "agent",
          created_at: epoch, updated_at: epoch};
}
```

- 注释明确："It is never stored, embedded or returned by search; it exists only in the list handed to the runner's prompt."——**只存在于 prompt 的伪记忆**，固定 id，永不落库。
- 与 `(saved …)` 前缀配合：模型看到时间戳 + 一行冲突规则，就能自己裁决"哪条是最新的"。

### 5.6 完整选择链（279-289）

```ts
export async function selectSemanticMemories(ctx, query) {
  await runIndexer(ctx, {maxEmbed: LAZY_INDEX_BATCH});                 // 懒索引一批（50）
  const selected = new Map();
  for (const h of await hybridSearch(ctx, query, {limit: MAX_RELEVANT_MEMORIES})) selected.set(...);  // hybrid top-8
  for (const m of ctx.services.memories.list({category: "preference", limit: ALWAYS_INCLUDE_PREFERENCES})) {
    if (selected.size >= MAX_RELEVANT_MEMORIES) break;                 // 偏好保底
    selected.set(m.id, m);
  }
  const memories = applyM1([...selected.values()], tz);                // 时近性 + saved 前缀
  return memories.length >= 2 ? [...memories, newerWinsNote()] : memories;  // newer-wins 注
}
```

## 6. Embedder 抽象（`embeddings.ts`）

- `Embedder` 接口三成员：`model` / `dims` / `embed(texts)`（16-20）。
- `MODEL_DIMS`（9-14）：已知维度的模型表（bge-small 384 / base 768 / large 1024 / m3 1024）；未知模型 `dims` 从 0 开始，取首个成功响应的长度，之后必须一致（注释 22-26）。
- `WorkersAiEmbedder.embed`（41-58）：一次调用嵌一批；响应数量不符 / 维度不符 / 非有限数 → 抛错。**校验在落库前**。
- `MockEmbedder`（83-103）：FNV-1a 哈希词袋 384 维 + 五个概念组（car~tesla~vw、vegetarian~dinner、peanut~allergic、city~portland、heights~mountains~knee）——**让改写句在余弦上真正接近**，dev/test/demo 能测到"语义相近"行为而不只是 CRUD。
- `contentHash`（158-161）：SHA-256 hex。
- 用量记录 `embeddingsToday` / `recordEmbeddings`（167-180）：`tal_semantic_usage` 表按 UTC 日累计 `embedding_requests` 与 `embedded_tokens_estimate`——**与聊天的 AI 请求额度分开计**（注释 165-166）。

`createEmbedder`（109-114）：demo 模式 → Mock；dev + `TALORYS_MOCK_AI=1` → Mock；有 AI binding → Workers AI；否则 null。

## 7. 接缝设计与独立迁移轨道

### 7.1 RunnerExtensions（`hooks.ts` 8-13）

```ts
export interface RunnerExtensions {
  selectMemories(query: string): Promise<Memory[]>;   // 替换上游 selectRelevantMemories
  tools: ToolDefinition[];                            // 替换上游 ALL_TOOLS
}
```

Runner 构造时传入即生效、不传即原样（`runner.ts:109, 159` 的 `this.ext ? ... : ...` 三元）。**两个字段覆盖全部语义集成点**。

### 7.2 工具原位替换（`tools.ts`）

```ts
export function semanticTools(sem): ToolDefinition[] {
  const wrapped = {
    search_memories: wrapSearchMemories(sem),   // 只换 execute，返回 hybrid 命中
    search: wrapSearch(sem),                    // 保留上游其他字段，只换 memories 段
    remember: wrapIndexAfter(sem, "remember"),  // 上游写入后触发后台索引
    update_memory: wrapIndexAfter(sem, "update_memory"),
  };
  return ALL_TOOLS.map((t) => wrapped[t.name] ?? t);
}
```

- 注释（60-66）明确："Everything but `execute` is the upstream definition, so ToolExecutor enforces the same permissions, per-turn caps and scheduled read-only mode."——**包装不绕过任何纪律**。
- `forget_memory` **不包**：它只提案，向量清理在 approve 路由里（§7.3）。
- `wrapSearch`（33-45）保留上游 `search` 的其他结果段（任务/笔记），只替换 `memories` 段。

### 7.3 写路径 HTTP 中间件（`routes.ts:46-128`）

中间件包住上游路由，在响应成功后执行副作用：

| 路由 | 方法 | 副作用 |
|---|---|---|
| `/memories` | POST | 后台索引（新记忆） |
| `/memories` | DELETE | purge 全部向量 |
| `/memories/*` | DELETE | purge 该 id 的向量 |
| `/memories/*` | PATCH | 后台索引（内容变了） |
| `/import` | POST | 后台索引 |
| `/actions/*/approve` | POST | 若提案是 `forget_memory` 且记忆真的没了 → purge 向量 |

关键纪律（56-69 注释）："Errors are logged and swallowed: a memory write never fails or changes because of this module."——try/catch 包住全部副作用，失败只 warn。

approve 中间件（111-128）的顺序很讲究：**先查 pending action 拿 target_id**（审批前），`await next()`（上游执行删除），**再确认记忆真的不存在**才 purge（126）——"the vector stays when the memory still exists (the action failed or was already handled)"。

### 7.4 独立迁移轨道（`migrations.ts`）

头注四条规则（5-15）：

```
- Applied lazily: no `tal_semantic_*` table exists until the feature is first enabled.
- Never ALTER or DROP upstream `tal_*` tables, and never add triggers to them.
- Never read, write or migrate other `tal_sem_*` tables; only `dropSemanticData` removes them.
- Never edit or reorder an existing migration; add a new one.
```

- 版本记录在 `tal_semantic_schema`（单行表，带 `track = "slim"` 字段）——与上游 `tal_schema` 完全分离。
- 每条迁移与版本 bump 同事务（62-73），`after` 回调（如 `convertLegacyVectors`）也在同一事务里。
- `dropSemanticData`（90-100）：**虚表先删**（它们的 shadow table 会跟着走），再删剩余的 `tal_sem%` 表，最后清缓存。上游数据零触碰。

### 7.5 组装与缓存（`index.ts`）

- `neverEnabled` WeakMap（13）：缓存"从未启用"的答案，未启用的安装每次聊天只付一次 settings 读（注释 20-23）。
- `semanticExtensions`（53-76）**永不抛错**：外层 try/catch 返回 undefined（回落上游行为）；`selectMemories` 内层 try/catch 返回关键词选择（注释 61："Recall must never fail a turn"）。
- `seedSemanticDefault`（40-47）：安装器写的 Worker var `TALORYS_SEMANTIC_DEFAULT=on` 只在**配置 key 缺失**时种一次；已有 key（包括用户关掉的）永远优先——"Settings stays the source of truth"。

## 8. 状态与运维 API（`routes.ts:130-231`）

- `GET /semantic/config`：当前配置 + `ever_enabled`。
- `PUT /semantic/config`：写入 + 缓存失效；**模型变更时 dropVectorCache**（143）；启用或换模型后触发后台回填（145-151）。
- `GET /semantic/status`（156-174）：enabled / schema 版本 / embedder 类型（mock|workers-ai|none）/ 向量数 / pending 数 / 今日用量 / 上限——**永不嵌向量、永不建表**（注释 155）。
- `DELETE /semantic/data`（177-185）：`confirm: "DELETE"` → drop 全部 `tal_sem%` 表 + 配置 key + 缓存。**记忆本身不动**。
- `GET /semantic/search`（193-209）：hybrid 命中带 cosine / fused / saved 时间戳（调试与 UI 用）。
- `POST /semantic/reindex`（212-231）：先 `deleteAllVectors` 再循环 `runIndexer` 直到无 pending / 触顶 / 空批；返回 embedded / pending / capped / error。

## 9. 与既有研究的对照

- **对比 hermes 的 FTS5 三索引**（`hermes/02-memory.md` §4）：hermes 在关键词层做到极致（trigram + 自研 CJK bigram 扩展 + fail-open），**语义层完全没有**；Talorys 相反——关键词层极简（单 FTS5 + OR 前缀查询），语义层做到极致。两者互补，是"关键词路线"与"向量路线"的两个样本。
- **对比 hermes 的检索护栏**：hermes 用"kanban/subagent/tool 来源完全隐藏，cron 来源降级不排除"（来源级过滤）；Talorys 用"三层地板 + 相对距离"（分数级过滤）。分数级过滤更通用（不依赖来源标注），来源级过滤更便宜。
- **pullInNewer vs hermes 的压缩交接**：hermes 的旧事实靠压缩摘要带进上下文（"以最新为准"写进摘要）；Talorys 在**检索层**强制成对出现。检索层方案更精确（不依赖压缩时机），但依赖向量质量。
- **无向量库**：与 OpenCode 的"用持久化执行替代缓存依赖"同属"按规模选择工具"的思路；5000 条 ≤5ms 的实测数字给了"什么时候可以不引入向量库"的判据。
- **失败降级链**：与 ZCode/Mini-Agent 的"摘要失败降级纯文本"同族——Talorys 的语义层有**三层降级**（embed 失败 → 关键词；索引失败 → 保持 pending；扩展组装失败 → 上游行为）。

## 10. 对 Memoria 的可迁移结论

1. **三层地板（03 篇 §5.2）**：`absolute`（绝对下限，最高命中低于它则整个列表为空）+ `relative`（相对距离，防弱命中搭车）+ `backstop`（兜底补足 top-K）。Memoria 检索核心（手写）当前若只有单一阈值，这是最直接的升级；**数字必须用 Memoria 自己的 embedding 模型重测**，方法照抄：准备正例（应该召回）与反例（应该为空）问题集，记录实测余弦区间。
2. **按模型默认值表 + legacy 读取映射（§2.2/2.3）**：阈值与 embedding 模型绑定；换模型时地板跟随切换（用户自定义过则保留）；旧配置读取时兼容、存储永不改写。
3. **向量即派生数据纪律包（§3）**：
   - 同请求删除（删记忆/文档 = 同事务删向量）；
   - 功能关闭时也删（§7.3 注释"forgetting is real"）；
   - 孤儿清理（`NOT IN` + RETURNING）；
   - `content_hash` 增量重嵌判据；
   - 不进备份、reindex 入口；
   - 悬空向量不占 fallback 名额。
   这是 Memoria"删文档必须删掉它的全部向量"红线的完整工程模板。
4. **失败的 embed 也计配额（§4.3）**：防错误重试风暴烧穿配额——Memoria 若接入计费 embedding API，这条必须抄。
5. **pullInNewer 新版本拉入（§5.4）**：Memoria wiki 知识复利场景（同一事实多版本）需要"旧版本永不单独出现"；实现要点：严格更新判定（updated_at → created_at）、按模型阈值、至多 2 条、继承分数、不二次拉入、只用缓存向量。
6. **`(saved …)` 前缀 + newer-wins 一行注（§5.5）**：~10 token/条的成本换模型的时间感知与冲突裁决能力；Memoria 记忆层（feat-071）注入格式可即刻采用（newer-wins 提示放 system 段更自然）。
7. **RRF 融合（§5.3）**：k=60，多路召回融合的最省调参方案；平局裁决链（分数 → 余弦 → 时间 → id）保证确定性。
8. **索引器并发纪律（§4.2）**：单 pass + 单 follow-up、运行中调用合并——Memoria 若有后台索引任务，避免重复嵌入的设计可直接借用。
9. **接缝设计（§7.1/7.2）**：扩展替换"选择器 + 工具集"两个点即可整体切换语义行为；工具包装只换 execute、保留全部纪律。Memoria 若要加语义检索，应做成可开关的增量模块而非改造检索核心。
10. **写路径副作用吞错（§7.3）**："a memory write never fails or changes because of this module"——派生数据的同步永不影响主写入的成功。

**不适合搬**：DO 缓存 tripwire 机制（依赖单实例同步语义；Memoria 用 SQLite 时按进程内缓存 + 显式失效即可）；bge 模型的具体数字（必须自测）；`RETURNING` 与 `unhex()` 的 SQLite 方言细节（Memoria 若用其他数据库需等价物）；伪记忆行（Memoria 注入是真实数据块）。

## 11. 证据索引

| 结论 | 文件:行 |
|---|---|
| 配置 schema 四字段 + 每日上限 + 地板校验 | `apps/agent/src/semantic/config.ts:10-25` |
| 按模型地板默认值表 + 未知模型回落 | `apps/agent/src/semantic/config.ts:31-45` |
| legacy 默认读取映射（不写存储） | `apps/agent/src/semantic/config.ts:57-70,97-130` |
| 换模型地板跟随切换 | `apps/agent/src/semantic/config.ts:137-158` |
| 启用先建 schema 再写 key | `apps/agent/src/semantic/config.ts:160-170` |
| 向量表 DDL（model+dims+hash 双隔离） | `apps/agent/src/semantic/vectorStore.ts:20-27`、`migrations.ts:23-40` |
| 归一化/点积/hex 绑定绕行 | `apps/agent/src/semantic/vectorStore.ts:59-89` |
| 缓存 tripwire（行数比对） | `apps/agent/src/semantic/vectorStore.ts:44-53,216-232` |
| 孤儿清理（NOT IN + RETURNING） | `apps/agent/src/semantic/vectorStore.ts:174-182` |
| pending 判定四条件 | `apps/agent/src/semantic/indexer.ts:39-52` |
| 单 pass + follow-up 并发纪律 | `apps/agent/src/semantic/indexer.ts:69-114` |
| 失败 embed 也计配额 | `apps/agent/src/semantic/indexer.ts:129-141` |
| 后台索引/回填入口 | `apps/agent/src/semantic/indexer.ts:164-189` |
| 查询嵌入三路降级 | `apps/agent/src/semantic/recall.ts:77-91` |
| 三层地板扫描 + 实测数字注释 | `apps/agent/src/semantic/recall.ts:93-131` |
| RRF k=60 + 平局裁决链 | `apps/agent/src/semantic/recall.ts:63-71,138-161` |
| pullInNewer（阈值/限制/继承/丢弃策略） | `apps/agent/src/semantic/recall.ts:178-223` |
| 拉入阈值按模型 + 实测正反例 | `apps/agent/src/semantic/recall.ts:22-40` |
| M1 时近性 + savedAt 格式化 | `apps/agent/src/semantic/recall.ts:225-263` |
| newer-wins 伪记忆（只进 prompt） | `apps/agent/src/semantic/recall.ts:21,265-272` |
| 完整选择链 | `apps/agent/src/semantic/recall.ts:279-289` |
| Embedder 接口/维度自适应/校验 | `apps/agent/src/semantic/embeddings.ts:9-58` |
| MockEmbedder 概念组 | `apps/agent/src/semantic/embeddings.ts:61-103` |
| contentHash / 用量表分离 | `apps/agent/src/semantic/embeddings.ts:153-180` |
| RunnerExtensions 两字段接缝 | `apps/agent/src/semantic/hooks.ts:8-13` |
| 工具原位替换（只换 execute） | `apps/agent/src/semantic/tools.ts:9-75` |
| 写路径中间件（吞错 + approve 顺序） | `apps/agent/src/semantic/routes.ts:46-128` |
| 独立迁移轨道四规则 + dropSemanticData | `apps/agent/src/semantic/migrations.ts:5-15,56-100` |
| never-enabled 缓存 + 永不抛错的扩展组装 | `apps/agent/src/semantic/index.ts:12-76` |
| 运维 API（status/reindex/data 删除） | `apps/agent/src/semantic/routes.ts:130-231` |
| 召回设计总述与实测数据 | `docs/semantic-recall.md` |
