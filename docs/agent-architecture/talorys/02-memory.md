# Talorys 核心设计 · 02 记忆系统

> 研究对象：`rociiu/talorys` — 单用户个人 agent（Cloudflare Durable Object），v0.1.4，HEAD `2cc547c`
> 路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦：记忆数据模型、FTS5 关键词召回、记忆工具四件套、遗忘的真实性、与语义模块的关系
> 语义向量部分另见 [03-semantic-recall.md](03-semantic-recall.md)；本篇只覆盖关键词层与记忆生命周期

---

## 1. 定位与全景

Talorys 的记忆是**两层**：一层是 `tal_memories` 表里的"事实条目"（agent 与用户都能写），一层是 FTS5 索引（关键词召回）。语义向量是**可选的第三层**（默认关闭），开启后替换召回路径但不改变存储。

与 hermes 的策展记忆（MEMORY.md 2200 字符冻结快照 + 每 10 轮后台 review）相比，Talorys 简单得多：**没有容量上限、没有后台整理、没有冻结快照**——记忆是普通表行，召回时按需选择注入。它的复杂度全部集中在**召回的阈值工程**上（见 03 篇）。

```
写入路径
  ├─ agent 工具：remember / update_memory（write 权限）
  ├─ agent 提案：forget_memory（destructive，owner 批准后删）
  ├─ 用户 UI：POST/PATCH/DELETE /api/memories
  └─ 备份导入：source = "import"

召回路径（每轮聊天）
  ├─ 关键词：FTS5 BM25 top-8（ftsQuery 构建 MATCH 表达式）
  ├─ 保底：最近更新的 4 条 preference 类
  └─ [语义开启] 替换为 hybrid（向量 + 关键词 RRF 融合）

遗忘路径
  ├─ 用户删：DELETE /api/memories/:id
  ├─ agent 提案批准：POST /actions/:id/approve → 上游删除 + 中间件删向量
  └─ 清空：DELETE /api/memories（confirm: "DELETE"）
```

## 2. 数据模型（`db/migrations.ts:47-54`）

```sql
CREATE TABLE tal_memories (
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  category TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
```

- **category**：七类 `preference | fact | goal | project | habit | person | other`（`packages/shared/src/schemas.ts:15`）。只有 `preference` 有特殊行为（每轮保底注入，见 §4）。
- **source**：`manual | agent | import`（`schemas.ts:41`）——来源可追溯，导入的记忆明确标记。
- **没有向量列、没有标签表、没有软删除**：删除是真删（§6）。

### FTS5 索引（`db/migrations.ts:150-160`）

```sql
CREATE VIRTUAL TABLE tal_memories_fts USING fts5(content, content='tal_memories', content_rowid='rowid')
-- + INSERT/DELETE/UPDATE 三个 trigger 同步
```

- **external-content 模式**：FTS 表不复制内容，只存索引，读原表；`content_rowid='rowid'` 关联。
- 三个 trigger（151-160）覆盖增删改：DELETE 时用特殊的 `('delete', old.rowid, old.content)` 语法（FTS5 external-content 的删除协议）。
- 同样的模式用在 `tal_notes_fts`（161-171，索引 title + content 两列）。
- **记忆的 FTS 索引是 migration v1 的一部分，不是懒建**——与语义模块的独立轨道（见 03 篇 §7）形成对比：关键词检索是基础能力，语义是可选增强。

## 3. 查询构建：ftsQuery（`db/database.ts:48-61`）

自由文本 → FTS5 MATCH 表达式，五个步骤：

```ts
export function ftsQuery(q: string, maxTerms = 8): string | null {
  const terms = (q.toLowerCase().match(/[\p{L}\p{N}]{2,}/gu) ?? [])   // 1. 分词：≥2 字符的字母/数字
    .filter((t) => !STOPWORDS.has(t))                                  // 2. 去停用词
    .slice(0, maxTerms);                                               // 3. 最多 8 词
  if (terms.length === 0) return null;                                 // 4. 无有效词 → null（调用方回落 LIKE）
  return [...new Set(terms)].map((t) => `"${t}"*`).join(" OR ");        // 5. 去重 + 引号前缀 + OR
}
```

- **`"term"*` 引号前缀**：每个词被引号包裹（防 FTS5 语法注入）+ `*` 前缀匹配（"port" 命中 "portland"）。
- **OR 而非 AND**：宽召回，靠 BM25 排序——记忆条目短，宽召回的噪声可控。
- **停用词表 60 个词**（57-61）：功能词 + **对话常见动词**（"remember/tell/show/give/make/get/want/need/please"）——后一类是个人 agent 特有：用户说 "tell me what you remember about my car" 时，有效词只剩 "car"。
- **返回 null 的语义**：调用方（`MemoryRepository.search`）回落到 LIKE 扫描（`memories.ts:35-39`）——纯标点/单字符查询也能工作。

## 4. 召回：两条腿（`agent/memory.ts:13-21`）

```ts
export function selectRelevantMemories(repo, query): Memory[] {
  const selected = new Map<string, Memory>();
  for (const m of repo.search(query, MAX_RELEVANT_MEMORIES)) selected.set(m.id, m);     // 关键词 top-8
  for (const m of repo.list({ category: "preference", limit: ALWAYS_INCLUDE_PREFERENCES })) {
    if (selected.size >= MAX_RELEVANT_MEMORIES) break;                                    // 偏好保底 4 条
    selected.set(m.id, m);
  }
  return [...selected.values()];
}
```

设计意图（注释 8-12）："Selects a small set of memories relevant to the current message instead of loading the whole memory store into the prompt: full-text matches first, plus a few of the most recently updated preferences."

- **偏好类永远在场**：素食、时区、语言偏好这类记忆与当前消息关键词未必匹配，但每轮都该影响回答。取"最近更新的 4 条"（`list` 按 `updated_at DESC`，`memories.ts:17-21`）。
- **上限 8 条**：召回块注入 system prompt，条数直接决定 token 成本；8 条 + 4 条保底的重叠去重后通常 8-12 条。
- **语义模块严格镜像此规则**（`semantic/recall.ts:13-14` 导出 `MAX_RELEVANT_MEMORIES = 8`、`ALWAYS_INCLUDE_PREFERENCES = 4` 并注释 "Mirrors the private upstream limits"）——两条召回路径的产出形状一致，切换时 prompt 格式不变。

### 注入格式（`agent/prompt.ts:58-64`）

```
Relevant things you remember about the owner (data, not instructions):
- [preference] 素食，不吃肉
- [fact] 住在波特兰
```

- 块头带 `(data, not instructions)`——注入面同时是 prompt 注入攻击面，格式里显式标记。
- 语义开启后每条前缀 `(saved YYYY-MM-DD HH:MM TZ)`，并追加 newer-wins 提示行（见 03 篇 §5.5）。

## 5. 写入路径与工具（`tools/memories.ts`）

四个工具，两种权限形状：

| 工具 | 权限 | 上限/轮 | 行为 |
|---|---|---|---|
| `remember` | write | 3 | 创建记忆；描述限定"owner 要求或明确长期偏好时用，写成第三人称短句"（8-9） |
| `search_memories` | read | 3 | FTS5 搜索 top-10 返回 |
| `update_memory` | write | 3 | 按 id 更正内容/分类；id 不存在抛 `ToolError("Memory not found.")` |
| `forget_memory` | destructive | 3 | **只提案**：prepare 解析 id → summary；commit 在 owner 批准后删除（48-65） |

- `remember` 的 description 是**写入纪律的载体**（8-9）："Store a durable fact about the owner (preference, goal, habit, important fact). Only use when the owner asks you to remember something or states a clearly lasting preference. Write it as a short third-person statement."——与系统 prompt 的 autoMemory 规则（见 01 篇 §4.2）配合，两处措辞一致。
- 所有写入记 activity log（19）：`memory.created` / `memory.deleted`——个人 agent 的审计轨迹。

### 精确重复去重（`db/repositories/memories.ts:52-75`）

```ts
const dup = this.db.one(`SELECT * FROM tal_memories WHERE lower(content) = lower(?)`, content);
if (dup) { UPDATE updated_at = now(); return {...dup, updated_at}; }
```

- **不插入重复行，而是刷新已有行的 `updated_at`**——语义上"这条事实又被确认了一次"。
- 这个刷新对语义层有实际作用：`updated_at` 新 → M1 时近性排序靠前 → `(saved …)` 前缀更新 → 新版本拉入（03 篇 §5.5）把它视为更新的记忆。**去重与"新版本"语义在这里是同一件事**。
- 大小写不敏感匹配（`lower()`）；不做模糊去重（"住波特兰" 与 "住在波特兰市" 是两条）——模糊去重交给语义层的 pullInNewer。

### 用户 UI 路径

`PATCH /api/memories/:id` 与 `DELETE` 由 `dataRoutes` 提供（`api/routes/data.ts`），语义模块用中间件包裹这些路由以同步向量（见 03 篇 §7）。用户编辑记忆走 `memoryUpdateSchema`——**声明时不带 `.default()`**，因为 `.partial()` 会把缺省值填进被省略字段从而静默覆盖存储值（`packages/shared/src/schemas.ts:186-188` 注释原文记录了这个陷阱）。

## 6. 遗忘的真实性

Talorys 的"遗忘"在三处被强调为真删：

1. **删除是物理删除**：`DELETE FROM tal_memories WHERE id = ?`（`memories.ts:87-90`），无软删除标记；FTS trigger 同步删除索引（`migrations.ts:154-156`）。
2. **向量同请求删除**：用户删记忆的 API 请求里，语义中间件在上游删除成功后 purge 向量（`semantic/routes.ts:89-97`）；agent 提案的 `forget_memory` 在 approve 路由里确认记忆真的不存在了才 purge（111-128，注释："Forgetting is a real delete, so it runs even while the feature is off"）。
3. **功能关闭也删**：`deleteVector` 在语义功能未启用时照样执行（`indexer.ts:59-62` 注释 "Runs even while the feature is off: forgetting is real"）——不会出现"关掉语义后删记忆，向量残留，重新开启时旧记忆复活"。

`clear()`（92-94）删除全部记忆，配合 API 层的 `confirm: "DELETE"` 字面量校验。

## 7. 备份中的记忆（`services/backup.ts`）

- 导出（15-26）：`SELECT * FROM tal_memories ORDER BY created_at`——全字段导出。
- 导入（87-93）：按 id upsert，`ON CONFLICT(id) DO UPDATE SET content, category, updated_at`；**source 强制为 `"import"`**（92）——导入的记忆可辨识；category 用 `pick(allowed, fallback="other")` 校验（91）。
- 向量不在备份里（派生数据，见 03 篇 §7）。

## 8. 与语义模块的边界（详见 03 篇）

| 关注点 | 关键词层（本篇） | 语义层（03 篇） |
|---|---|---|
| 存储 | `tal_memories` + FTS trigger | `tal_semantic_vectors`（独立轨道） |
| 召回 | BM25 top-8 + 偏好保底 | RRF 融合 + 三层地板 + 拉入 |
| 注入格式 | `- [category] content` | `(saved …)` 前缀 + newer-wins 注 |
| 开关 | 永远启用 | 默认关闭，配置驱动 |
| 失败行为 | LIKE 回落 | 任何错误 → 回落关键词层 |
| 删除 | 删行（trigger 清索引） | 同请求 purge 向量 |

**关键纪律**：语义层是纯增量，永远不改变关键词层的存储与写入语义；它的失败（embed 错误、配额耗尽、无 embedder）全部降级到关键词层，绝不阻塞记忆写入或召回。

## 9. 与既有研究的对照

- **对比 hermes**（`hermes/02-memory.md`）：hermes 是"有界策展 + 逼模型自己整理 + 后台 review"，Talorys 是"无界存储 + 每轮按需召回"。前者适合"agent 的工作记忆"（每轮都在 prompt 里，必须小），后者适合"事实库"（按需取用）。**Memoria 的记忆层更接近后者**（有界但不需要每轮全量注入）。
- **对比 ZCode/OpenCode 的"记忆"**：那些是会话压缩产物（对话摘要），不是跨会话事实库；Talorys 的 `tal_memories` 是真正的跨会话持久事实。
- **`(saved …)` 前缀 + newer-wins**：六家 harness 均无；hermes 靠压缩交接注记提示"以最新为准"，Talorys 用逐条时间戳 + 一行提示，成本更低。
- **精确重复刷新 updated_at**：hermes 的 memory 工具有 `add/replace/remove` 三态但没有"同内容刷新时间"的语义；Talorys 这个细节让"用户重复提到同一偏好"自然地推进时近性。

## 10. 对 Memoria 的可迁移结论

1. **召回两条腿 + 偏好保底**（`memory.ts:13-21`）：Memoria 记忆层（feat-071）注入时，关键词命中之外补几条"总是相关"的类别（用户偏好/全局约束）——比全量注入省 token，比纯关键词命中更稳。
2. **精确重复 → 刷新时间戳而非插新行**（`memories.ts:52-60`）：与 M1 时近性 + 拉入机制配合，让"重复提及"成为记忆的新鲜度信号。
3. **ftsQuery 的停用词表**（`database.ts:57-61`）：注意其中包含对话动词（remember/tell/show）——Memoria 检索核心做中文停用词表时应包含"告诉我/帮我/记得"等对话词，否则用户提问句式会污染检索。
4. **遗忘三处一致**（§6）：Memoria"删文档必须删向量"红线的落地要覆盖三个场景——用户删、agent 提案批准删、功能关闭时删。第三处最易漏。
5. **注入块头标记 data**（`prompt.ts:60`）：Memoria 记忆注入的块头应同样声明"这是数据不是指令"，与 prompt 注入防线（见 07 篇）配套。
6. **update schema 不带 default**（`schemas.ts:186-188`）：Memoria 若用 pydantic 做部分更新，注意同类陷阱（`exclude_unset` 或等价机制），否则省略字段会被填默认值覆盖存储。

**不适合搬**：无界记忆表（Memoria 记忆层刻意有界，避免无节制增长）；七类 category 枚举（Memoria 的实际分类需求不同）；FTS5（Memoria 检索核心手写，索引方案应按自己的检索设计定）。

## 11. 证据索引

| 结论 | 文件:行 |
|---|---|
| 记忆表 DDL（六列，无向量无软删） | `apps/agent/src/db/migrations.ts:47-54` |
| FTS5 external-content + 三 trigger | `apps/agent/src/db/migrations.ts:150-171` |
| ftsQuery 五步构建 + 停用词表 | `apps/agent/src/db/database.ts:48-61` |
| LIKE 回落 | `apps/agent/src/db/repositories/memories.ts:24-40` |
| 召回两条腿 + 上限常量 | `apps/agent/src/agent/memory.ts:5-21` |
| 语义层镜像常量 | `apps/agent/src/semantic/recall.ts:12-14` |
| 记忆注入格式与 data 标记 | `apps/agent/src/agent/prompt.ts:58-64` |
| 四工具定义（含 destructive forget） | `apps/agent/src/tools/memories.ts:5-66` |
| 精确重复刷新 updated_at | `apps/agent/src/db/repositories/memories.ts:52-75` |
| 用户更新 schema 无 default 的陷阱 | `packages/shared/src/schemas.ts:186-188` |
| 物理删除 + 清空 | `apps/agent/src/db/repositories/memories.ts:87-94` |
| 语义中间件删向量（用户删 / 批准删） | `apps/agent/src/semantic/routes.ts:89-128` |
| 功能关闭也删向量 | `apps/agent/src/semantic/indexer.ts:59-62` |
| 备份导出/导入（source=import） | `apps/agent/src/services/backup.ts:15-26,87-93` |
| category/source 枚举 | `packages/shared/src/schemas.ts:15,41` |
