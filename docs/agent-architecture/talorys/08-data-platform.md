# Talorys 核心设计 · 08 数据平台与交付

> 研究对象：`rociiu/talorys` — 单用户个人 agent（Cloudflare Durable Object），v0.1.4，HEAD `2cc547c`
> 路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦：单 DO SQLite 架构（`db/`）、追加式迁移纪律、备份导出/导入（`services/backup.ts`）、HTTP API 面与 SSE（`api/`）、安装器交付（`packages/create-talorys/`）
> 安全相关的认证/CSRF 另见 [07-security.md](07-security.md)

---

## 1. 定位与全景

Talorys 的"数据平台"只有三层：一个 Durable Object、一个 SQLite、一套追加式迁移。没有 ORM、没有连接池、没有副本、没有缓存层——**所有复杂度都被"单实例 + 同步 SQLite"这个前提消掉**。

```
Cloudflare Pages（前端 SPA，公开 URL）
  │  service binding（后端不可公开访问）
  ▼
私有 Worker（Hono API，workers_dev: false）
  │  onRequest → 转发进 DO
  ▼
TalorysAgent（Durable Object，单实例 "personal-agent"）
  ├─ Database（同步 SQLite 薄包装）           db/database.ts
  ├─ Repositories（10 个，一行一方法）         db/repositories/
  ├─ Services（settings/usage/activity/auth）  services/
  ├─ migrate()（追加式迁移，首次访问时执行）     db/migrations.ts
  └─ 语义模块独立迁移轨道（track "slim"）        semantic/migrations.ts
```

关键前提（决定了后面所有设计）：**DO 是单实例、单线程、同步 SQLite**——所以可以用进程内缓存 + 行数 tripwire（03 篇）、同步事务做原子认领（04 篇）、单 shot 日程（05 篇）。

## 2. Database 薄包装（`db/database.ts`）

```ts
/**
 * Thin, synchronous wrapper around Durable Object SQLite storage.
 * All queries use bound parameters; never interpolate values into SQL.
 */
export class Database {
  all<T>(query: string, ...params: unknown[]): T[] { return this.storage.sql.exec(query, ...params.map(normalize)).toArray() as T[]; }
  one<T>(query, ...params): T | null { const rows = this.all<T>(query, ...params); return rows[0] ?? null; }
  run(query, ...params): {changes: number} {
    const cursor = this.storage.sql.exec(query, ...params.map(normalize));
    cursor.toArray();                                   // Drain the cursor so the statement fully executes.
    return {changes: cursor.rowsWritten};
  }
  /** Runs `fn` atomically. Throwing rolls the transaction back. */
  transaction<T>(fn: () => T): T { return this.storage.transactionSync(fn); }
}

function normalize(value: unknown): SqlValue {
  if (value === undefined || value === null) return null;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number" || typeof value === "string") return value;
  return JSON.stringify(value);                          // 对象/数组自动序列化
}
```

四个要点：

- **全参数绑定**（注释 6："never interpolate values into SQL"）——唯一的动态 SQL 是 `usage.ts` 的列名，用封闭 union 保证安全（06 篇 §5.2）。
- `run` 显式 drain cursor（注释 22-23）：DO 的 SQL 是惰性游标，不消费完语句不会完整执行。
- `normalize`（33-38）：boolean → 0/1；对象/数组 → JSON 字符串——调用方可以直接传 JS 值。**副作用**：typed array 也会被 JSON 序列化，所以向量要走 hex + `unhex()`（03 篇 §3.3）。
- `transactionSync`：同步事务，抛错自动回滚——所有多步写（迁移、审批认领、备份导入）都靠它。

辅助函数：

- `now()` / `newId()`（40-41）：ISO 时间戳 / `crypto.randomUUID()`。
- `likePattern(q)`（44-46）：转义 `\%_` 后加 `%` 包裹——LIKE 注入防护。
- `ftsQuery(q, maxTerms=8)`（49-61）：自由文本 → FTS5 MATCH（详见 02 篇 §3）；**停用词表 60 词**含对话动词。

## 3. 迁移纪律（`db/migrations.ts`）

### 3.1 三条规则（头注 3-11）

```
Versioned, append-only schema migrations for Talorys data.

Rules:
 - Never edit or reorder an existing migration; add a new one.
 - Migrations must be non-destructive (no DROP of owner data).
 - All tables are prefixed `tal_` so they never collide with the
   Agents SDK's internal `cf_agents_*` tables.
```

第三条特别值得注意：**前缀是防框架冲突**，不是命名偏好——SDK 自己也在同一个 SQLite 里建表。

### 3.2 执行器（196-222）

```ts
export function migrate(db, migrations = MIGRATIONS): number {
  db.run(`CREATE TABLE IF NOT EXISTS tal_schema (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL, updated_at TEXT NOT NULL)`);
  const current = db.one(`SELECT version FROM tal_schema WHERE id = 1`)?.version ?? 0;
  let version = current;
  for (const m of migrations) {
    if (m.version <= version) continue;
    db.transaction(() => {                                  // 迁移与版本 bump 同一事务
      for (const statement of m.statements) db.run(statement);
      db.run(`INSERT INTO tal_schema (id, version, updated_at) VALUES (1, ?, ?)
              ON CONFLICT(id) DO UPDATE SET version = excluded.version, updated_at = excluded.updated_at`, m.version, iso);
    });
    version = m.version;
  }
  return version;
}
```

- **版本表单行**（`CHECK (id = 1)`）——只有一个"当前版本"。
- **每条迁移与版本号 bump 同事务**（注释 196-198："a failure leaves the previous version intact"）——迁移失败不会留下"半迁移"状态。
- 全部 `CREATE TABLE IF NOT EXISTS` / `CREATE VIRTUAL TABLE IF NOT EXISTS`（22-171）——**幂等 DDL**，即使版本表被重建也能安全重跑。

### 3.3 当前两个版本

| 版本 | 名称 | 内容 |
|---|---|---|
| 1 | initial schema | 13 张表 + FTS5 虚表与触发器：settings / conversations / messages / memories / projects / tasks / notes / automations / automation_runs / notifications / activity / sessions / login_attempts / usage_daily + memories_fts + notes_fts（含 6 个同步 trigger） |
| 2 | pending destructive actions | `tal_pending_actions`（04 篇 §4.1） |

### 3.4 独立语义轨道（`semantic/migrations.ts`）

语义模块自持一套迁移（`tal_semantic_schema`，track `"slim"`），头注四条规则（5-15）：

```
- Applied lazily: no `tal_semantic_*` table exists until the feature is first enabled.
- Never ALTER or DROP upstream `tal_*` tables, and never add triggers to them.
- Never read, write or migrate other `tal_sem_*` tables; only `dropSemanticData` removes them.
- Never edit or reorder an existing migration; add a new one.
```

**两条独立轨道共享一个数据库**，互不触碰——这是"可选模块"在存储层的落地方式。`SemanticMigration` 接口多一个 `after` 回调（19-22），在同一事务内跑数据转换（如 base64 → BLOB 向量）。

## 4. Repository 层（`db/repositories/`，10 个文件）

统一的形态：构造注入 `Database`，方法一一对应 SQL，**不做业务逻辑**（业务在 services / tools / runner）。

| 文件 | 关键方法 | 值得注意 |
|---|---|---|
| `conversations.ts` | list/get/require/create/rename/setSummary/delete/messages/addMessage/lastMessage | 工具活动 JSON 列；`withCurrentStatus` 配合；rowid 二级排序（01 篇 §5） |
| `memories.ts` | list/search/get/create/update/delete/clear/count | FTS5 BM25 + LIKE 回落；精确重复刷新 updated_at（02 篇 §5） |
| `tasks.ts` | list/resolve/create/update/complete/delete | `resolve(ref)` 标题/ID 双解析，不唯一返回 null |
| `notes.ts` / `projects.ts` | CRUD + resolve | notes 有 FTS5（title + content） |
| `automations.ts` | list/create/update/startRun/finishRun/pruneRuns | 回执存 automation_name 快照（05 篇 §5） |
| `notifications.ts` | create/list/unreadCount/markRead | 未读数配合 DO state |
| `pending-actions.ts` | create/get/view/resolve/withCurrentStatus/markFailed | 条件 UPDATE 原子认领（04 篇 §4.3） |

`require(id)` 模式：`get` 返回 null，`require` 抛 `NotFoundError`——调用方按需选择。

## 5. 备份与恢复（`services/backup.ts`）

### 5.1 导出（5-26）

```ts
/** Builds a portable backup. Sessions, login attempts and credentials are never exported. */
export function exportData(s: Services): Backup {
  return {
    format: BACKUP_FORMAT, version: BACKUP_VERSION, exported_at: iso, app_version: TALORYS_VERSION,
    data: {
      settings: s.settings.get(),
      conversations: db.all(`SELECT id, title, summary, summary_upto, created_at, updated_at FROM tal_conversations ORDER BY created_at`),
      messages: db.all(`SELECT id, conversation_id, role, content, tools, status, error, created_at FROM tal_messages ORDER BY created_at`),
      memories: db.all(`SELECT * FROM tal_memories ORDER BY created_at`),
      tasks: ..., notes: ..., projects: ...,
      automations: db.all(`SELECT id, name, kind, message, schedule, enabled, created_at, updated_at FROM tal_automations`)
        .map((a) => ({...a, schedule: JSON.parse(String(a.schedule)), enabled: a.enabled === 1})),
    },
  };
}
```

- **七类用户数据**，无 sessions / login_attempts / usage / activity / pending_actions。
- **向量不在备份里**（派生数据，03 篇 §7）——导入后 lazy 重嵌或 reindex。
- 导出时做类型还原（schedule JSON 解析、enabled 布尔化）——便携格式不泄露存储细节。
- `format` + `version` 字段（`BACKUP_FORMAT = "talorys-backup"`, `BACKUP_VERSION = 1`）。

### 5.2 导入（28-150）

**五层防御**，每层解决一类失败：

1. **schema 校验在前**（49-50）：`backupSchema.safeParse(raw)` 失败即拒。
2. **版本门**（52-54）：`backup.version > BACKUP_VERSION` → 拒绝并提示先升级（"This backup was made by a newer Talorys (format vN). Update Talorys first."）——**前向不兼容显式拒绝**，不猜测。
3. **单事务 + 按 id upsert**（60-143）：

```ts
const summary = db.transaction((): ImportSummary => {
  for (const p of d.projects) db.run(`INSERT ... ON CONFLICT(id) DO UPDATE SET ...`);
  const projectExists = (id) => typeof id === "string" && !!db.one(`SELECT 1 AS x FROM tal_projects WHERE id = ?`, id);
  for (const c of d.conversations) ...
  for (const m of d.messages) {
    if (!db.one(`SELECT 1 AS x FROM tal_conversations WHERE id = ?`, m.conversation_id)) continue;   // 外键前置检查
    db.run(`INSERT INTO tal_messages ... ON CONFLICT(id) DO NOTHING`);                                // 消息永不覆盖
    messages++;
  }
  for (const m of d.memories) db.run(`... ON CONFLICT(id) DO UPDATE SET content, category, updated_at`);
  for (const t of d.tasks) ...;  for (const n of d.notes) ...;
  for (const a of d.automations) {
    const schedule = scheduleSpecSchema.safeParse(a.schedule);
    if (!schedule.success) continue;                                                                   // 非法日程静默跳过
    ...
  }
  if (d.settings && Object.keys(d.settings).length > 0) s.settings.update(d.settings as never);         // 校验合并
  return {...};
});
```

   - **幂等**（注释 43-47）："Records are upserted by id, so importing the same backup twice is harmless and nothing that exists only locally is deleted."
   - 外键完整性**手工保证**：messages 只在所属会话存在时插入（78）；tasks/notes 的 project_id 用 `projectExists` 校验后置 null（104, 111）。
   - **messages 用 DO NOTHING**（81）：已有消息永不覆盖——保护本地更新的状态（如审批卡）。
   - **枚举兜底 `pick`**（40-41）：`pick(v, allowed, fallback)` ——导入数据的枚举值非法时回落默认，不拒绝整包。
   - 导入的记忆 `source` 强制 `"import"`（92）；自动化的 `kind` 用 `pick` 兜底（118）。

4. **事务外重排日程**（145-147）：

```ts
// Arm (or disarm) imported schedules outside the data transaction (SDK schedules are separate rows).
// A backup can change timezone even when all scheduled automations are local.
if (summary.automations > 0 || s.settings.get().timezone !== previousTimezone) await s.automations.rearmAll();
```

   - SDK 日程不在 SQLite 事务里 → 数据提交后再 arm；**时区变化也要重排**（所有墙钟规则都变了）。

5. **审计**（148）：`activity.record("data.imported", ...)`。

## 6. HTTP API 面（`api/`）

### 6.1 组装（`api/app.ts`）

```ts
export function createApi() {
  const app = new Hono<AppEnv>().basePath("/api");
  app.onError((err) => errorResponse(err));
  app.notFound(() => errorResponse(new NotFoundError("Unknown API route")));
  app.use("*", securityHeaders);
  app.use("*", csrfProtection);
  app.use("*", requireSession);
  // First, so its middleware wraps the upstream /memories and /import handlers.
  app.route("/", semanticRoutes);
  app.route("/", systemRoutes);
  app.route("/auth", authRoutes);
  app.route("/", chatRoutes);
  app.route("/", dataRoutes);
  app.route("/", automationRoutes);
  return app;
}
```

- **中间件顺序即防线顺序**：安全头 → CSRF → 会话 → 路由。
- **语义路由先挂**（注释 32）：它的中间件要包住后面 `dataRoutes` 的 `/memories` 与 `/import` 处理器（03 篇 §7.3）——**路由注册顺序决定中间件包裹关系**。
- API 跑在 DO 内（注释 18-21）："so no data ever leaves the private backend."

### 6.2 路由分组

| 路由文件 | 覆盖 |
|---|---|
| `routes/auth.ts` | login / logout / session / password / sessions 管理 |
| `routes/chat.ts` | conversations CRUD + SSE `/chat` + `/chat/cancel` + `/actions/:id/approve|cancel` |
| `routes/data.ts` | tasks / notes / projects / memories / search / backup 导出导入 |
| `routes/automations.ts` | automations CRUD + runs + notifications |
| `routes/system.ts` | health / settings / activity / usage |
| `semantic/routes.ts` | 语义配置/状态/搜索/重建（挂在前面） |

### 6.3 SSE 端点（`routes/chat.ts:57-121`）——值得细读的并发处理

```ts
chatRoutes.post("/chat", async (c) => {
  const input = await body(c, chatRequestSchema, 64 * 1024);
  const agent = c.env.agent;
  if (input.conversation_id && agent.activeRuns.has(input.conversation_id))
    throw new AppError("CONFLICT", "A response is already being generated in this conversation.");
  const controller = new AbortController();
  // Claim the conversation now, before any await, so a concurrent request sees the conflict.
  if (input.conversation_id) agent.activeRuns.set(input.conversation_id, controller);

  const {readable, writable} = new TransformStream<Uint8Array, Uint8Array>();
  const writer = writable.getWriter();
  let clientGone = false;

  const send = async (event: ChatStreamEvent) => {
    if (clientGone) return;
    try { await writer.write(encoder.encode(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`)); }
    catch { clientGone = true; controller.abort(); }      // 浏览器断开 → 停止生成省额度
  };

  const run = async () => {
    let conversationId = input.conversation_id;
    try {
      await writer.write(encoder.encode(`: stream open\n\n`));       // 注释行：立即打开流
      for await (const event of agent.runner().chat({...})) {
        if (event.type === "start") { conversationId = event.conversation_id; agent.activeRuns.set(conversationId, controller); }
        await send(event);
      }
    } catch (error) { /* 错误也走 SSE error 事件 */ }
    finally {
      if (conversationId && agent.activeRuns.get(conversationId) === controller) agent.activeRuns.delete(conversationId);
      try { await writer.close(); } catch { /* already closed */ }
    }
  };
  void run();                                            // DO 在响应流打开期间保持存活

  return new Response(readable, {headers: {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-store, no-transform",
    "x-accel-buffering": "no",
  }});
});
```

六个关键点：

1. **并发认领在任何 await 之前**（63-65，注释明说）：同会话已有流 → `CONFLICT`。这是"检查 + 设置"的同步原子性，与 04 篇的审批认领同源。
2. **`TransformStream` 手工写**：不用 Hono 的 streaming helper——因为要在 `run()` 里精细控制写入与关闭。
3. **`: stream open` 注释行**（85）：SSE 规范允许注释行，立即冲刷连接让前端知道流已建立。
4. **写失败 = 客户端断开**（77-79）：置 `clientGone` + `controller.abort()`——**停止生成以节省 AI 额度**（注释原文）。后续事件直接丢弃。
5. **新会话的认领延后**（92-94）：`start` 事件才知道新会话 id，此时补认领。
6. **清理用身份比对**（103）：`activeRuns.get(conversationId) === controller` 才删除——不会误删后来者的认领。

响应头三个：`no-store, no-transform`（禁缓存与改写）、`x-accel-buffering: no`（禁代理缓冲）。

前端消费（抽查 `apps/web/src/lib/api.ts:56-76`）：`fetch` + `res.body.pipeThrough(new TextDecoderStream()).getReader()` 手解析——不用 EventSource，因为需要 POST + 自定义 CSRF 头。

### 6.4 取消与审批（123-143）

- `/chat/cancel`：按 conversation_id 找 controller 并 abort（幂等，返回 `{cancelled: boolean}`）。
- `/actions/:id/approve`：`runApprovedAction`（04 篇 §3.4）。
- `/actions/:id/cancel`：`resolve(id, "cancelled")`。

## 7. 安装器交付（`packages/create-talorys/`）

### 7.1 流程（`install.ts:144-336`）

```
检查系统要求（Node 版本 + 模板信息）
  → 检测 Cloudflare CLI（bundled wrangler + 全局 CLI）
  → 校验目标目录安全（assertSafeTarget）
  → 读/建 manifest（幂等：存在即对账）
  → 确保 Cloudflare 认证（whoami；未登录则开浏览器登录）
  → 选账号（单账号自动；多账号交互或 --account-id）
  → 分配资源名（allocateNames：查重最多 5 次）
  → 计算缺失 secrets（listSecrets 对差集；密码缺失才询问）
  → 确认部署计划（交互）
  → scaffold 项目（模板渲染）
  → 部署 Worker（首次创建 SQLite DO namespace）
  → 写 secrets（走 stdin）
  → 部署 Pages（创建项目 + 部署 dist）
  → 健康检查（verifyDeployment：前端↔后端连通）
  → manifest 标记 deployed
```

### 7.2 Manifest 与幂等（`manifest.ts`）

`talorys.json` 记录：`manifest_version / installation_id / account_id / account_name / worker_name / pages_project_name / public_url / deployment_version / agent_name / timezone / semantic / status / steps / created_at / updated_at`。

- **每步 `markStep`**：进度可恢复（"steps" 数组）。
- **重跑 = 对账**（`install.ts:165-168`）：已有 manifest → "Found installation X — updating/resuming safely. Existing data is never deleted."；资源名沿用 manifest 里的（不重新分配）。
- **失败写回**（312-315）：`status: "failed"`，下次重跑从断点继续。
- **密码永不覆盖**（202-206）：`missingSecrets` 对差集；`--update` 模式不重问密码。

### 7.3 资源命名（`config.ts`）

`resourceNames(installationId)`：Worker 名、Pages 项目名、installation_id 都基于随机 id——避免与账号内已有资源冲突（`allocateNames` 最多试 5 次）。

### 7.4 健康检查（`verify.ts`）

`verifyDeployment(url, {fetch, timeoutMs, onWait})`：等 Pages 站点可达（新站点需要几分钟）+ 检查前端能连到后端。失败给出恢复指引（"Re-run the same command to resume; nothing will be duplicated."）。`TALORYS_TEST_VERIFY_ORIGIN` 环境变量供打包 CLI 测试用（无法访问真实 pages.dev 时）。

### 7.5 更新与重置（`install.ts:340-358`）

- `update` 模式：要求已有 manifest，走同一 install 流程（对账）。
- `resetPassword`：认证 → 选账号 → 确认 Worker 存在 → 询问新密码 → 写新 secret（`includeSessionSecret: false`——session secret 不变）。DO 侧的指纹检测自动丢弃 override 并撤销全部会话（07 篇 §3.1）。

## 8. 与既有研究的对照

- **对比 hermes 的 34 个 state 模块**（`hermes/02-memory.md`）：hermes 为多进程/多平台共享状态付出了巨大工程复杂度（WAL/readpool/lockguard/repair）；Talorys 用"单 DO + 同步 SQLite"把这类问题整体消除。**架构前提决定工程复杂度**——这是两篇最值得对照的一对。
- **对比 DeepSeek Harness 的世代化不可变存储**：它用 generation 化 JSONL（绝不改写已提交文件）；Talorys 用"追加式迁移 + 幂等 DDL + 单行版本表"。两者都达到"可安全升级"，但 Talorys 的 SQLite 路径轻得多。
- **对比 OpenCode 的 SQLite/文件双存储**：OpenCode 为持久化执行做了双存储投影；Talorys 单一存储 + SSE 直推，无投影层。
- **备份导入的幂等性**：六家 + hermes 均无"用户可导出的便携备份"（它们是本地工具，数据在用户文件系统里）；Talorys 因为是"部署在别人账号里"，备份是产品必需——**交付形态决定数据责任**。
- **SSE 的并发认领 + 断连中止**：与 hermes 的"投递四态台账"同属"通道可靠性"问题，但 Talorys 的解法轻（内存 Map + AbortController），因为单 DO 无跨进程并发。
- **安装器**：六家 + hermes 均为 clone-and-run；Talorys 的"一条命令部署到用户自己的账号"是唯一的 SaaS 化交付，因此需要幂等对账、健康检查、断点恢复、密码不覆盖这一整套。

## 9. 对 Memoria 的可迁移结论

1. **迁移三规则（§3.1）**：永不编辑已有迁移 / 非破坏性 / 前缀防冲突（若同库有其他组件）。Memoria 若用 SQLite + 版本表，这三条可直接写进迁移模块头注。
2. **迁移与版本 bump 同事务（§3.2）**：失败留旧版本完好；配合幂等 DDL（`IF NOT EXISTS`）可安全重跑。
3. **可选模块独立迁移轨道（§3.4）**：Memoria 的语义/邮件等可选模块应有自己的版本表与规则（懒建表、永不动核心表）——模块可卸载且核心不受影响。
4. **备份导入五层防御（§5.2）**：schema 校验 → 版本门（前向不兼容显式拒绝）→ 单事务按 id upsert（幂等）→ 外键前置检查 + 枚举兜底 → 事务外副作用（重排日程）。Memoria 若要支持导出/导入（知识库迁移、用户数据备份），这是完整模板。
5. **派生数据不进备份（§5.1）**：向量/索引可重建，备份只带真源——与 03 篇的派生数据纪律一致。
6. **SSE 并发认领在任何 await 之前（§6.3）**：Memoria 的 SSE 端点（feat-039）与 ConversationQueue 应检查同一会话的并发保护是否也是"同步认领"——异步检查有竞态窗口。
7. **写失败 = 客户端断开 → abort 省额度（§6.3）**：Memoria 的 SSE 路径应有等价的断连检测。
8. **`no-store, no-transform` + `x-accel-buffering: no`（§6.3）**：SSE 响应头的完整清单，防中间层缓存/缓冲。
9. **路由注册顺序即中间件包裹关系（§6.1）**：Memoria 若用 FastAPI/Starlette，中间件与路由的包裹顺序同样要显式设计（语义钩子包住核心写路由）。
10. **安装器/部署的幂等对账（§7）**：Memoria 的 init 脚本或部署流程若会被重跑，应记录步骤进度（manifest 模式）、不覆盖已有凭据、失败可断点续跑。
11. **`require` vs `get` 双方法（§4）**：Repository 层提供"返回 null"与"抛错"两个入口，调用方按语义选择——减少每处调用点的判空样板。

**不适合搬**：Durable Object（平台耦合）；`transactionSync`（取决于存储实现）；Cloudflare 特有的部署工具链（wrangler/service binding）；`cursor.toArray()` drain（DO SQL 特有）；单行版本表（若 Memoria 用 Alembic 等成熟迁移工具，不必自建）。

## 10. 证据索引

| 结论 | 文件:行 |
|---|---|
| Database 薄包装（绑定/归一化/drain/事务） | `apps/agent/src/db/database.ts:1-41` |
| likePattern / ftsQuery / 停用词表 | `apps/agent/src/db/database.ts:43-61` |
| 迁移三规则（追加式/非破坏/前缀） | `apps/agent/src/db/migrations.ts:3-11` |
| 迁移与版本 bump 同事务 + 幂等 DDL | `apps/agent/src/db/migrations.ts:196-222` |
| v1 全表结构 + FTS5 触发器 | `apps/agent/src/db/migrations.ts:18-172` |
| v2 pending_actions | `apps/agent/src/db/migrations.ts:174-191` |
| 语义独立轨道四规则 + after 回调 | `apps/agent/src/semantic/migrations.ts:5-22,56-100` |
| Repository 清单与职责 | `apps/agent/src/db/repositories/*.ts`（10 文件） |
| conversations：工具 JSON/审批快照/rowid 排序 | `apps/agent/src/db/repositories/conversations.ts:21-29,104-144` |
| memories：FTS5 + LIKE 回落 + 去重刷新 | `apps/agent/src/db/repositories/memories.ts:24-40,52-75` |
| 备份导出七类（不含 secrets） | `apps/agent/src/services/backup.ts:5-26` |
| 导入五层防御（版本门/事务/外键/枚举/重排） | `apps/agent/src/services/backup.ts:43-150` |
| API 组装与中间件顺序 | `apps/agent/src/api/app.ts:18-41` |
| SSE 端点（同步认领/断连中止/响应头） | `apps/agent/src/api/routes/chat.ts:53-121` |
| 取消与审批路由 | `apps/agent/src/api/routes/chat.ts:123-143` |
| 前端 SSE 消费（fetch + reader） | `apps/web/src/lib/api.ts:56-76`（抽查） |
| 安装器流程与幂等对账 | `packages/create-talorys/src/install.ts:144-336` |
| Manifest 字段与 markStep | `packages/create-talorys/src/manifest.ts` |
| 资源命名与查重 | `packages/create-talorys/src/config.ts`、`install.ts:85-94` |
| 健康检查与恢复指引 | `packages/create-talorys/src/verify.ts`、`install.ts:298-310` |
| 密码重置（session secret 不变） | `packages/create-talorys/src/install.ts:340-358` |
| 备份格式常量 | `packages/shared/src/constants.ts`（BACKUP_FORMAT / BACKUP_VERSION） |
