# OpenMuse 核心设计 · 07 数据平台

> 研究对象：`CopilotKit/OpenMuse` — 个人 agent，MIT，TypeScript；HEAD `1ac68f3`（main，2026-10-11）
> 路径相对仓库根，`文件:行` 均为实读行号；结论只来自源码
> 本篇聚焦：单表记录层（`apps/server/src/db.ts` 全文 180 行）、CAS 原语族、查询模式与索引、`setMilestoneDone` 的并发保真、幂等写入、双后端切换、schema 演进
> 与 [../04b-openmuse-alpha-surfaces.md](../04b-openmuse-alpha-surfaces.md) §0 重叠处只做引用 + 增量；04b 未覆盖的 kind 全清单、`data->>` 查询模式与索引策略、jsonb 数组并发保真的 SQL 细节、schema 演进（未定位到的部分）在本篇首次完整覆盖

---

## 1. 定位与全景

OpenMuse 的数据平台是一张表。

```sql
CREATE TABLE IF NOT EXISTS records(
  owner text NOT NULL, kind text NOT NULL, id text NOT NULL,
  data jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(owner, kind, id)
)
```

（`db.ts:176-178`）

**没有第二张表**。tasks、actions、goals、monitors、ideas、memories、artifacts、notifications、run-events、files、browsers、credentials、sessions、activity、imports、settings…… 全部是这张表的行。

```
Store（业务无关的 12 个方法）
  ├─ 读：get / list / listByGoalId / listByStatus / scan
  ├─ 写：put（upsert）/ insertIfAbsent / compareAndSwap / take（删除并返回）
  └─ 专用：claim / setMilestoneDone / updateCredential / recoverInterruptedActions
       ├─ PGlite（嵌入式，进程内）    └─ Postgres（pg.Pool max=5）
```

**设计取舍**：个人 agent 的实体数量与查询复杂度都低（"给我 owner 的全部任务""按 status 找""按 goalId 找"），但**并发正确性要求高**（任务认领、审批决策、监控推进都是"至多一次"）。单表 + jsonb + 条件 UPDATE 恰好匹配：不需要 schema 迁移来加字段，不需要 join，而 CAS 用一条 SQL 就能表达。

## 2. 一切实体的 kind 清单

从全仓 `db.put/get/list/insertIfAbsent/compareAndSwap/take` 调用点汇总：

| kind | 内容 | 主要写入点 |
|---|---|---|
| `tasks` | `AgentTask` | `service.ts:244` |
| `actions` | `ActionProposal` | `actions.ts:92-93,204` |
| `goals` / `monitors` / `ideas` | `Goal` / `Monitor` / `Idea` | `service.ts:371,426,598` |
| `memories` | `AgentMemory` | `conversation.ts:376`；`routes.ts:99-108` |
| `agent-artifacts` | `AgentArtifact` | `service.ts:751` |
| `notifications` | `AgentNotification` | `service.ts:728` |
| `run-events` / `runs` | `RunEvent` / 执行台账（id = leaseId） | `worker.ts:164,192,205` |
| `files` | `Artifact`（PDF 元数据，字节在磁盘） | `files.ts:98,101` |
| `browsers` / `browser-downloads` / `chat-browsers` | 浏览器会话与映射 | `browser.ts:125,287,200` |
| `search-sessions` | conversation → 匿名 session id | `search.ts:51` |
| `activity` | `ActivityEntry`（审批审计） | `actions.ts:209` |
| `agent-settings` | `AgentIdentity` + `lastIdeasAt` | `service.ts:130,635` |
| `settings` | google 连接开关 / seeded 标记 | `workspace.ts:284-285` |
| `credentials` | Google token（加密 secret + generation） | `google-auth.ts:63,124` |
| `imports` / `mail` / `events` | 附件映射 / 缓存邮件 / 缓存日历 | `workspace.ts:506,122,271` |
| `monitor-pages` / `sample-pages` | 监控页面行快照 / sample 假页面 | `service.ts:1140,1073` |
| `jev_threads` / `jev_panels` / `jev_evidence` / `jev_mail_evidence` | JEV 面板状态机与证据 | `jev/service.ts:61,266,348,358,365` |
| `computer-commands` / `computer-desktop-commands` / `computer-desktop-actions` / `computer-desktop-screens` / `computer-state` | computer 回执、桌面动作、截图、租约 | `computer.ts:226,633,674,683,702,714`；`computer-backend.ts:74,328` |

**system owner 下的三类**：`sessions`（登录会话，id = token 摘要，`auth.ts:24-28`）、`oauth`（OAuth state，10 分钟过期，`google-auth.ts:124`）、`worker-status`（worker 心跳，`worker.ts:69-72`）。

**观察一**：`kind` 命名不一致——复数（`tasks`/`goals`）、带前缀单数（`agent-settings`/`agent-artifacts`）、"子实体用父名"（`monitor-pages`/`chat-browsers`）。这不是设计缺陷，而是**渐进式演进的痕迹**：新实体加一个 kind 字符串即可，无需迁移。

**观察二**：**单例实体用固定 id**——`credentials` 用 `id='google'`，`agent-settings` 用 `id='identity'`，`settings` 用 `id='google'`/`id='seeded'`。

## 3. CAS 原语族

### 3.1 `compareAndSwap`：核心原语（`db.ts:69-81`）

```ts
async compareAndSwap<T>(owner, kind, id, expected: Record<string, unknown>, patch: Record<string, unknown>): Promise<T | null> {
  const result = await this.db.query(
    "UPDATE records SET data=data || $5::jsonb,updated_at=now() WHERE owner=$1 AND kind=$2 AND id=$3 AND data @> $4::jsonb RETURNING data",
    [owner, kind, id, JSON.stringify(expected), JSON.stringify(patch)],
  );
  return (result.rows[0]?.data as T | undefined) ?? null;
}
```

| 片段 | 语义 |
|---|---|
| `data=data \|\| $5::jsonb` | **浅合并**：patch 的顶层键覆盖旧值，未提及的键保留 |
| `data @> $4::jsonb` | **包含**：`data` 必须包含 `expected` 的所有键值对（递归包含，数组按"包含元素"语义） |
| `RETURNING data` | 返回合并后的完整对象 |
| 返回 `null` | CAS 失败（条件不满足） |

**为什么用 `||` 而不是整体替换**：patch 只需写出"变化的字段"，其余字段（包括并发写入的字段）自动保留。

**`@>` 的语义细节**（迁移时的坑）：

- `{"a": 1, "b": 2} @> {"a": 1}` → true（**多余键不影响**）；
- `{"a": null} @> {"a": null}` → **true**（`null` 是有效值）；
- `{"a": 1} @> {"a": null}` → **false**。

最后两条很重要：`worker.ts:129` 用 `leaseId: previous.leaseId ?? null` 作为 expected——**当 `leaseId` 是 `null` 时，只有库里也是 `null` 才能匹配**。这正是想要的行为（未租出的任务才能被认领）。

**嵌套对象递归包含**：`{"state": {"a": 1, "b": 2}} @> {"state": {"a": 1}}` → true。所以 `worker.ts:439` 的 `{ status: "paused", state: { resumingMonitor: true } }` 只要求 `state.resumingMonitor === true`。

**数组的包含语义**：`{"a": [1,2,3]} @> {"a": [1]}` → true（子集）。所以 `service.ts:921` 的 `{ milestones: goal.milestones }` 做的是"里程碑列表包含全部旧里程碑"——若并发添加了新里程碑，包含关系仍成立，CAS 会成功并**覆盖掉并发新增的**。`publishOutcome` 用 CAS + 最多 8 次重试 + 幂等判据（`milestones.some(m => m.id === task.id)`）来缓解（`service.ts:911-927`），但**丢更新窗口只在"两个任务同时完成且属于同一 goal"时出现**——个人部署下极罕见。

### 3.2 其余原语

| 方法 | SQL 要点 | 用于 |
|---|---|---|
| `put`（`:55-61`） | `ON CONFLICT DO UPDATE SET data=excluded.data`——**整体替换** | 持有完整对象的场景 |
| `insertIfAbsent`（`:98-108`） | `ON CONFLICT DO NOTHING RETURNING`——冲突返回 `null` | 幂等创建 |
| `take`（`:134-140`） | `DELETE … RETURNING data` | 单次消费（OAuth state、真删记忆） |
| `claim`（`:116-128`） | `jsonb_set` + 任务存在性子查询 | 审批原子认领（[03 篇](03-approval-isolation.md) §6.3） |
| `updateCredential`（`:144-150`） | `jsonb_set` + `connectionId` 条件；返回 boolean | 刷新写回（[05 篇](05-integrations.md) §3.4） |
| `recoverInterruptedActions`（`:129-133`） | `data \|\| patch`，**唯一不带 owner 的 UPDATE** | 启动全局对账（[03 篇](03-approval-isolation.md) §7.4） |

**`insertIfAbsent` + 读回的三段式**（`service.ts:195-196`）：

```ts
const existing = await this.db.get<AgentTask>(owner, "tasks", id);
if (existing) return existing;
…
await this.db.insertIfAbsent(owner, "tasks", task);
return (await this.db.get<AgentTask>(owner, "tasks", id)) ?? task;   // 读回赢家
```

**最后一步的"读回"是必要的**：并发时 `insertIfAbsent` 返回 null，需要读回另一个请求插入的版本。

## 4. `setMilestoneDone`：jsonb 数组的并发保真（`db.ts:82-97`）

```sql
UPDATE records SET data=jsonb_set(data, '{milestones}', (
  SELECT jsonb_agg(CASE WHEN item->>'id'=$3
    THEN item || jsonb_build_object('done', $4::boolean) ELSE item END ORDER BY ordinal)
  FROM jsonb_array_elements(data->'milestones') WITH ORDINALITY AS milestones(item, ordinal)
)), updated_at=now()
WHERE owner=$1 AND kind='goals' AND id=$2
  AND EXISTS (SELECT 1 FROM jsonb_array_elements(data->'milestones') item WHERE item->>'id'=$3)
RETURNING data
```

注释原文（`:82-83`）："Update only the selected checkbox against the current row, preserving concurrent additions, renames, reordering and other milestones' completion state."

**逐步解析**：`jsonb_array_elements(...) WITH ORDINALITY` **展开当前（最新）行**的数组并带序号 → `CASE WHEN item->>'id' = $3 THEN item || jsonb_build_object('done', $4) ELSE item END` 只改目标项（**其他项原样保留**，包括并发新增的、被重命名的）→ `ORDER BY ordinal` **保持原顺序**（并发重排的结果被保留）→ `jsonb_agg` 重新聚合 → `jsonb_set` 写回 → `EXISTS (...)` 要求目标里程碑存在（否则不更新，返回 null → 404）。

**为什么不能用 CAS**：CAS 的 `||` 是**顶层键替换**——`{ milestones: [...] }` 会整体覆盖数组。若用户在勾选的同时另一个请求新增了里程碑，勾选会把新增的抹掉。

**通用价值**：任何"jsonb 数组里改一个元素"的场景都可以用这个模式——"展开最新行 → 逐项条件变换 → 保序聚合 → 写回"，全部在一条语句内完成，无读-改-写窗口。

**迁移到 SQLite**：SQLite 无 `jsonb_agg`/`WITH ORDINALITY`，需用 `json_each` + 应用层重组，或应用层乐观锁（读 → 改 → `WHERE data = <原值>` 写回）实现等价语义。

## 5. 查询模式与索引

### 5.1 五个读方法（`db.ts:15-115`）

```ts
get(owner, kind, id)                  // 主键精确查
list(owner, kind)                     // ORDER BY updated_at DESC, id
listByGoalId(owner, kind, goalId)     // WHERE data->>'goalId' = $3
listByStatus(owner, kind, status)     // WHERE data->>'status' = $3
scan(kind)                            // 跨 owner，返回 {owner, value}
```

`list` 的排序（`:28`）：`ORDER BY updated_at DESC,id`——**二级排序键 `id` 保证同毫秒写入的顺序稳定**。这与 talorys 的 `ORDER BY created_at ASC, rowid ASC` 是同一纪律的两个实现。

### 5.2 `data->>'status'` 模式与类型转换

`->>'key'` 把 jsonb 字段**以文本形式**取出：数字会变成字符串（`1` → `"1"`），所以数值/时间比较需要显式转换——`claim` 里就用了 `(data->>'expiresAt')::timestamptz>$3::timestamptz`（`:120`）。

### 5.3 索引策略（未定位到）

`db.ts:176-178` 只建了主键 `PRIMARY KEY(owner,kind,id)`，**没有任何二级索引**：

- `get`/`put`/`compareAndSwap`/`take` 走主键索引——快；
- `list`/`listByStatus`/`listByGoalId` 在 `(owner, kind)` 前缀上可走主键索引的一部分，但 `data->>'status'` 的过滤是**逐行求值**（无 GIN 索引）；
- **`scan(kind)` 完全没有 owner 前缀，全表扫描**。

**这在个人规模下是可接受的**（任务上限 100、实体总量在千级），但**没有任何注释说明这是有意的取舍**。迁移时若数据量增长，需补 `(kind)` 与 `((data->>'status'))` 的索引。

### 5.4 `scan` 的实现（`db.ts:109-115`）

```ts
"SELECT jsonb_build_object('owner',owner,'value',data) AS data FROM records WHERE kind=$1 ORDER BY updated_at ASC"
```

**用 `jsonb_build_object` 把 owner 与 data 包成一个对象**——`Row` 类型（`{data: Record<string, unknown>}`）不用改，返回形状统一。调用点：`worker.ts:78`（每 tick 扫全部任务）、`service.ts:90-110`（maintain）、`routes.ts:31`（快照）。

## 6. 幂等写入的四种形态

| 形态 | SQL/机制 | 用于 | 语义 |
|---|---|---|---|
| **key 派生 id + 先查** | `get` → `insertIfAbsent` → 读回 | tasks/monitors/actions/notifications | 同 key 返回同一实体 |
| **deterministicFileId** | sha256 前 128 位伪装 v5 UUID | files | id 本身确定 |
| **`link` 原子发布** | 临时文件 → `link` → `EEXIST` 读回 | files（字节） | 字节层幂等 |
| **内容 hash 作 key** | `sha256(JSON.stringify(args))` | operations / prepare 工具 | 同参数返回同结果 |

第一种的完整写法见 §3.2。**`hash()` 里带前缀**（`task:`、`monitor:`、`action:`）防不同 kind 的键空间碰撞。第四种见 `model.ts:77-87`（operations 表）与 `model.ts:249,267`（prepare 工具的内容 hash）。

## 7. 双后端切换（`db.ts:153-180`）

`createStore` 二选一：有 `databaseUrl` 走 `pg.Pool({ connectionString, max: 5 })`；否则 PGlite 嵌入式（`new PGlite(dataDir)` + `waitReady`）。**抽象只有两个方法**（`db.ts:8-11`）：`query(sql, params) => {rows}` + `close()`。**PGlite 与 Postgres 的 SQL 方言完全兼容**（PGlite 就是 WASM 版 Postgres）——所以不需要方言适配层，只需适配"调用形状"。这是"双后端"成本极低的原因。

**pool error 监听的必要性**（`:153` 注释原文）："Idle clients can be disconnected by a database restart; without a listener pg's `error` event crashes the process." **数据目录权限**：`mkdir(dirname(dataDir), { recursive: true, mode: 0o700 })`——只有 owner 可访问。

## 8. Schema 演进策略

**明确结论：OpenMuse 没有 schema 迁移机制。**

- 无 migration 目录、无版本号表、无 `ALTER TABLE`；
- 唯一的 DDL 是 `CREATE TABLE IF NOT EXISTS records(...)`；
- 实体结构由 `packages/domain` 的 TypeScript 接口定义，但**不是运行时校验**（除少数 zod schema 用于输入校验）；
- **读取时不校验**（`get<T>` 是纯类型断言：`(result.rows[0]?.data as T | undefined) ?? null`）。

**演进靠三样东西**：

1. **jsonb 的天然灵活性**——加字段不需要 DDL；
2. **可选字段 + 默认值**——如 `AgentTask` 的 `nextRunAt?`、`leaseId?`、`question?`；
3. **代码里的兼容分支**——如 `workspace.ts:451-455` 对"没有 targetVersion 的老提案"直接拒绝：

```ts
if ((input.kind === "calendar.update" || input.kind === "calendar.delete") && !targetVersion)
  throw new AppError("This calendar review predates target-version checks. Prepare a new review.", 409);
```

**这是"拒绝老数据"而非"迁移老数据"的策略**——fail-closed，且文案告诉用户怎么办。

**代价**：老数据永久留在库里（没有清理），且任何"必须存在的字段"的缺失都要靠代码分支处理。对个人部署可接受；对需要长期演进的产品是技术债。

**迁移建议**：若 Memoria 采用单表 jsonb，应**同时引入 `schema_version` 字段**（写在每行 data 里），这样"拒绝老数据"至少可查询、可统计、可批量处理。

## 9. 存储分层：什么进库，什么进磁盘

| 数据 | 位置 | 理由 |
|---|---|---|
| 所有实体元数据 | `records.data`（jsonb） | 需要 CAS 与查询 |
| PDF 字节 | `dataDir/files/<id>.pdf`（0o600） | 大小与二进制；库里只存元数据 + `size` |
| 浏览器 profile / cookies | worker 的 `WORKER_DATA_DIR` / `storage.json` | Playwright 管理 |
| 签名密钥 | `dataDir/session-signing-key`（0o600） | 需要跨重启稳定 |
| 加密的 Google token | `records.data.secret`（`credentials` kind） | 加密后是文本，可进库 |

**文件路径防穿越**（`files.ts:116-122`）：

```ts
private pathFor(id: string): string {
  assertFileId(id);
  const directory = resolve(this.config.dataDir, "files");
  const resolved = resolve(directory, `${id}.pdf`);
  if (!resolved.startsWith(`${directory}${sep}`)) throw new AppError("File not found", 404);
  return resolved;
}
```

`assertFileId` 先用正则校验 id 形状（UUID v1-v8 + 变体位），再做路径前缀校验——**双重防御**。

## 10. 与既有研究的对照

- **与 talorys 数据平台（[../talorys/08-data-platform.md](../talorys/08-data-platform.md)）**：talorys 是**规范化多表 + 追加式迁移**（`db/migrations.ts`），OpenMuse 是**单表 jsonb + 无迁移**。两者都建立在单文件 SQLite/PGlite 上，走向相反：talorys 的迁移体系让 schema 演进可审计但每次加字段要写迁移；OpenMuse 的单表让加字段零成本但老数据没有版本标记。**结论**：单用户规模下 OpenMuse 的路线开发速度更快；一旦需要"清理老数据"或"多版本共存"，talorys 的路线更可靠。**Memoria 应采用中间形态：单表 + `schema_version` 字段**。
- **与 hermes 记忆（[../hermes/02-memory.md](../hermes/02-memory.md)）**：hermes 用文件系统（MEMORY.md + JSONL）而非数据库。三者（talorys/OpenMuse/hermes）在"个人 agent 的持久化"上给出三个答案：规范化表 / 单表 jsonb / 文件。**OpenMuse 的独特点是 CAS 是一等原语**——另外两家都没把"至多一次"抽象成数据层的通用能力。
- **与 04b §0 的关系**：04b 已给出"没有独立的任务表/审批表/通知表——一切实体都是 records 一张表的行"与 CAS 的核心地位。增量：**kind 全清单**（含 system owner 下的 sessions/oauth/worker-status）、`@>` 的语义细节（`null` 匹配、嵌套递归、数组子集）与它在 `publishOutcome` 里的丢更新窗口、`setMilestoneDone` 的 SQL 逐步解析、**无二级索引**这一事实与影响、`claim` 用 `jsonb_set` 而非 `||` 的原因、双后端抽象只有两个方法、**无迁移机制**的明确结论与"拒绝老数据"策略。
- **与 04-openmuse.md 的关系**：旧研究未涉及数据层细节。本篇是首次覆盖。

## 11. 对 Memoria 的可迁移结论

**适合搬（6 条）**：

1. **CAS 原语（`db.ts:69-81`）**：`UPDATE … WHERE … AND <条件> RETURNING data`，条件用"期望值包含"表达，patch 用"浅合并"表达。Memoria 的 SQLite 等价物：`UPDATE records SET data = json_patch(data, :patch) WHERE … AND <逐字段条件> RETURNING data`。落点：feat-068 任务引擎。
2. **`insertIfAbsent` + 读回的三段式（`db.ts:98-108`）**：幂等创建的标准写法。落点：所有"按 key 创建"的入口。
3. **`setMilestoneDone` 的数组保真模式（`db.ts:84-97`）**：任何"jsonb 数组改一个元素"的场景。**Memoria 若用 SQLite，需应用层乐观锁替代**（读 → 改 → `WHERE data = <原值>` 写回）。
4. **`data->>'status'` 查询模式 + 显式类型转换（`db.ts:120`）**：jsonb 取字段是文本，时间/数值比较必须显式 cast。
5. **`take`（删除并返回）用于单次消费（`db.ts:134-140`）**：OAuth state、一次性令牌、真删记忆。
6. **主键三级设计 `(owner, kind, id)`（`db.ts:177`）**：owner 在最前，天然支持"按 owner 查全部某 kind"。

**次选（2 条）**：`ORDER BY updated_at DESC, id` 的二级排序键（`:28`）；`recoverInterruptedActions` 式启动对账（`:129-133`）。

**不适合搬（4 条）**：**`||` 浅合并用于数组字段**（会整体覆盖，见 §3.1 的丢更新窗口）；**无二级索引**（个人规模可接受，Memoria 若数据量更大需补索引；注意 `scan(kind)` 是全表扫描）；**无 schema 版本标记**（迁移时至少要加 `schema_version`）；**PGlite/Postgres 双后端**（Memoria 用 SQLite，只搬 CAS 原语；若坚持双后端，抽象只需 `query(sql, params)` + `close()` 两个方法）。

**必须注意的反面证据**：**`get<T>` 不做运行时校验**（`db.ts:24`）——读出来直接 `as T`，schema 不符时错误会在使用点爆发而非读取点。Memoria 若照抄，需在关键路径加 zod 校验（OpenMuse 自己在少数地方这么做了，如 `worker.ts:92-96` 对 action 的 `{status, expiresAt}` 做窄类型读取）。

## 12. 证据索引

| 结论 | 文件:行 |
|---|---|
| Database 抽象只有 query/close 两方法 | `apps/server/src/db.ts:8-11` |
| get / list（ORDER BY updated_at DESC,id） | `apps/server/src/db.ts:15-32` |
| listByGoalId（data->>'goalId'）/ listByStatus（data->>'status'） | `apps/server/src/db.ts:33-54` |
| put（upsert 整体替换）/ remove | `apps/server/src/db.ts:55-68` |
| compareAndSwap（`data @> expected` + `data \|\| patch` + RETURNING） | `apps/server/src/db.ts:69-81` |
| setMilestoneDone（jsonb_set + WITH ORDINALITY + 保序聚合） | `apps/server/src/db.ts:82-97` |
| insertIfAbsent（ON CONFLICT DO NOTHING RETURNING） | `apps/server/src/db.ts:98-108` |
| scan（jsonb_build_object + 全表） | `apps/server/src/db.ts:109-115` |
| claim（jsonb_set + 任务存在性子查询 + 时间 cast） | `apps/server/src/db.ts:116-128` |
| recoverInterruptedActions（无 owner 的全局对账） | `apps/server/src/db.ts:129-133` |
| take（删除并返回）/ updateCredential（jsonb_set + connectionId 条件） | `apps/server/src/db.ts:134-150` |
| createPool max=5 + error 监听理由 / createStore 双后端 + 唯一 DDL + 0o700 | `apps/server/src/db.ts:153-180` |
| 主键 PRIMARY KEY(owner,kind,id) 且无二级索引 | `apps/server/src/db.ts:176-178` |
| 幂等键三段式（get → insertIfAbsent → 读回） | `apps/server/src/engine/service.ts:192-196,243-245` |
| publishOutcome 的里程碑 CAS + 幂等判据 | `apps/server/src/engine/service.ts:911-927` |
| 通知 key 派生 id / monitor 的 CAS / 监控 pause/resume 的 CAS 条件 | `apps/server/src/engine/service.ts:466-553,719-729,1124-1138` |
| worker 认领 CAS / checkpoint CAS / 心跳 CAS / tick 的 scan 全表 | `apps/server/src/engine/worker.ts:78-86,126-161,174-190` |
| 审批 propose 的 insertIfAbsent + 读回 / activity 追加式写入 | `apps/server/src/actions.ts:90-98,208-217` |
| 文件字节落盘（0o600 + wx）/ 路径防穿越双重防御 / deterministicFileId | `apps/server/src/files.ts:11,23-40,64-83,116-122` |
| 文件导入 insertIfAbsent + 读回 | `apps/server/src/files.ts:97-102` |
| OAuth state 落库与 take 消费 / 凭据 CAS / 凭据条件更新 | `apps/server/src/google-auth.ts:56-72,124-131,147,205-234` |
| session 摘要存储 + 24h | `apps/server/src/auth.ts:23-29` |
| worker 心跳写 worker-status / 快照读 worker-status（15s 判活） | `apps/server/src/engine/worker.ts:66-75`；`apps/server/src/engine/service.ts:149-165` |
| 无迁移机制（唯一 DDL）/ 老数据拒绝策略 | `apps/server/src/db.ts:176-178`；`apps/server/src/workspace.ts:451-455` |
| 窄类型读取的示例 | `apps/server/src/engine/worker.ts:92-96` |
