# OpenMuse 核心设计 · 00 总览

> 研究对象：`CopilotKit/OpenMuse` — "A personal agent with a browser, terminal, files, and work that keeps going"，MIT，TypeScript
> HEAD：`1ac68f3`（main，2026-10-11 tarball；2026-10-12 开工前 `git ls-remote` 探测，上游未变）
> 源码位置：`C:\Users\tom\AppData\Local\Temp\agentresearch\openmuse-fresh`（无 `.git`，为完整 tarball 解包）
> 本篇是系列总览：跨维度共同模式、在既有研究中的定位、对 Memoria 的优先级迁移清单。各维度结论的证据均在其对应文档内，本篇不重复给行号。
> 与既有 [04-openmuse.md](../04-openmuse.md)（2026-10-03 整体架构）与 [04b-openmuse-alpha-surfaces.md](../04b-openmuse-alpha-surfaces.md)（2026-10-11 表面级深读，863 行）的关系：本系列是它们的**分维度标准化重组 + 增量深挖**。04b 已深读的主题（AG-UI 事件流、九态状态机、租约、审批隔离、文档纪律）在本系列只做一句话引用 + 新证据；04b 未覆盖的主题（vault 凭据加密、rate-limit、SSRF egress、OpenBot、幂等键、TaskWorker 内部实现）在本系列有独立完整覆盖。

## 1. 系列导航

| 文档 | 维度 | 核心源文件 | 一句话核心设计 |
|---|---|---|---|
| [01-agent-loop.md](01-agent-loop.md) | 对话循环与客户端队列 | `engine/conversation.ts`、`engine/tanstack-agent.ts`、`mobile/conversation-queue.ts` | AG-UI 事件流 + 三层流式中间件补上游转换器缺陷；对话只负责委派，52 行队列管住单 run 互斥 |
| [02-task-engine.md](02-task-engine.md) | 持久任务引擎 | `engine/worker.ts`、`engine/service.ts`、`domain/agent.ts` | 九态状态机 + jsonb CAS 租约 + 恢复=重放；审批单即回执，TaskWorker 以 guard/checkpoint 自证租约 |
| [03-approval-isolation.md](03-approval-isolation.md) | 审批与对话通道隔离 | `actions.ts`、`db.ts::claim`、`engine/model.ts` | "no tool to approve them"：审批是对话之外的一等实体，hash 绑内容、If-Match 绑版本、幂等键派生 id |
| [04-agent-computer.md](04-agent-computer.md) | 浏览器与 Linux computer | `computer.ts`、`computer-backend.ts`、`worker/browser.ts` | 独立进程 worker + attach 前 zod 复核隔离白名单；五状态命令回执，中断只标记不重放 |
| [05-integrations.md](05-integrations.md) | 外部集成 | `integrations/vault.ts`、`integrations/google.ts`、`backends/openbot.ts` | AES-256-GCM 版本化信封存 token；读默认写追加 scopes + ETag 快照审批 + If-Match 执行锁 |
| [06-security.md](06-security.md) | 安全边界 | `worker/network.ts`、`rate-limit.ts`、`auth.ts`、`docs/TELEMETRY.md` | 出站只允许公网单播地址（IPv4 逐段拒绝 + IPv6 段白名单）；限流 pre-auth 且 key 不取自调用方凭据 |
| [07-data-platform.md](07-data-platform.md) | 数据平台 | `db.ts`、`config.ts` | 一切实体一张 `records(owner,kind,id,data jsonb)` 表；CAS 是唯一并发原语，PGlite/Postgres 同构 |
| [08-surfaces-and-doc-discipline.md](08-surfaces-and-doc-discipline.md) | 次表面与文档纪律 | `engine/finance.ts`、`engine/routes.ts`、`docs/FEATURES.md` | 六个次表面里四个不经模型；四件套文档互相咬合，"Planned extensions are not claims of current support" |

## 2. 跨维度共同模式

这 8 个维度不是 8 套独立技术，反复出现的是同一批底层决策：

1. **单表 + CAS 贯穿一切。** 没有独立的任务表/审批表/通知表——tasks/actions/goals/monitors/ideas/memories/artifacts/notifications/run-events/files/browsers/credentials/sessions 全部是 `records(owner,kind,id,data jsonb)` 的行（`apps/server/src/db.ts:176-178`）。所有"至多一次"语义都建立在同一条 SQL 上：`UPDATE … WHERE … AND data @> $expected RETURNING data`（`db.ts:69-81`）。任务领取、审批认领、里程碑勾选、通知去重、监控推进，用的是同一个原语。
2. **确定性优先于模型。** 能不用模型的地方一律不用：finance 是 101 行纯函数 CSV 状态机（`engine/finance.ts`）；Ideas 由三条正则生成（`engine/service.ts:578-633`）；监控比对是文本 hash 与行级 diff（`engine/page-diff.ts`）；`setMilestoneDone` 是纯 SQL。模型只在"开放式任务执行"与"结构化选择排序"两个位置出现。
3. **"模型可见面"与"执行面"分离。** 审批卡展示服务端写就的 `title + target`，不是模型转述；approve/deny 走 `/api/actions/:id` 专属通道，对话里**没有任何工具能批准**（`engine/model.ts:331` 原文 "there is no tool to approve them"）；任务完成必须由服务端状态 + 回执证明（"Never claim task completion before server status and receipt confirm it"，`conversation.ts:389`）。
4. **存引用不存值。** 富工具消息只保留 task ID，前端从已认证端点实时拉状态；会过期的 file/preview URL 由服务端现签发，绝不写进线程消息（`docs/RICH-THREADS.md:26`）。这条规则同时解决了缓存失效、URL 腐烂与权限过期三个问题。
5. **恢复 = 重放，不是"续跑内存状态"。** 任务执行的每一步都 checkpoint 到库（`worker.ts:149-161`）；进程崩溃后任务被重新认领，从头读 `task.state` 继续；命令中断只标记 `interrupted` 并写明"结果未知，检查后再重试"，**永不自动重放**（`computer.ts:291-313`）。
6. **失败必须有明确语义，且不隐式重试。** 线程锁 hold（不是失败）、错误不隐式重发（"Never resend it implicitly"）、`outcomeUnknown`（写操作可能已发生，须先对账）、`refused`（策略拒绝，永不重试）——每种失败都指向一个不同的用户动作，没有一种叫"再试一次也许就好了"。
7. **框架默认行为要审计，其缺陷要显式绕开。** 三层流式中间件补的是上游转换器 bug（`splitTextAtToolCalls`，附 `ponytail:` 注释说明升级条件）；`textOnlyToolResult` 防截图 JSON 进持久线程；`reportStepLimit` 防步数打满时静默停止。三处都在注释里写明了"为什么这里必须有一层自己的代码"。

## 3. 在既有研究中的定位

对照本目录 `../README.md` 的六家横向对比与 [hermes/](../hermes/00-overview.md)、[talorys/](../talorys/00-overview.md)：

- **形态**：与 hermes、talorys 同属"个人 agent"，但 OpenMuse 是**唯一把 durable work 做成一等产品面**的样本——talorys 的调度是"提醒 + 摘要"，hermes 是 cron 投递，OpenMuse 是九态任务状态机 + 租约 + 审批 + 目标/里程碑。Memoria 的 `mail_triage` 异步批处理与它映射最直接。
- **循环**：六家 + hermes + talorys 的循环都是"本进程内跑完一轮"；OpenMuse 的对话循环**故意很短**（maxSteps 6/16），长活一律 `delegate_task` 交给 worker 进程。这是全部研究里唯一的"对话层与执行层进程级分离"样本。
- **压缩**：**唯一明确不做上下文压缩的一家**——依赖 CopilotKit Intelligence 持久化线程并靠"存引用现取值"回避膨胀。它提供的对照价值不是"怎么做压缩"，而是"哪些上下文根本不必进 prompt"。
- **审批**：与 talorys 的 prepare/commit 提案制同构，但强制力更强（8 层结构强制 vs talorys 的"轮次内无执行路径"），且多了 hash 绑内容、If-Match 绑版本、幂等键派生 id、`outcomeUnknown` 四个 talorys 没有的机制。与 Memoria feat-066 提案制可直接逐项对照。
- **安全**：全部研究里**唯一给出完整 SSRF/egress 校验实现**的样本（IPv4 逐段拒绝表 + IPv6 段白名单 + DNS 全量地址检查 + 代理只连已验证 IP）。hermes/talorys 都是"不出站"或"未涉及"，OpenMuse 是"必须出站所以必须校验"。
- **数据平台**：与 talorys 的单 DO SQLite 同为单文件数据库，但 OpenMuse 走"一张 jsonb 表 + CAS"路线，talorys 走"规范化多表 + 迁移"。两个独立实现对照，能看出**单用户规模下 jsonb 单表在并发正确性上更省心**。
- **文档纪律**：04b 已深读，本系列 08 篇按"四件套如何咬合 + 与 talorys 的对照"重组。

## 4. 对 Memoria 的优先级迁移清单

按性价比排序（落点文档标注在括号内）：

1. **审批与对话通道隔离的 8 层结构（03）**：Memoria 红线"验证码/交易邮件永不自动归档，任何归档必须人工确认"目前是**instructed**（prompt 声明）；OpenMuse 的做法可以让它变成**enforced**——归档提案是对话之外的一等实体，对话工具面里根本没有"批准归档"这个工具。落点：`app/` 的归档节点与提案表。
2. **jsonb CAS 原语 + 单表记录层（07）**：`data @> expected` 条件 UPDATE + `data || patch` 合并 + `RETURNING`，一条 SQL 覆盖"认领/推进/去重"三类需求。Memoria 的 SQLite 可直接用 `json_extract` 等价实现。落点：feat-068 任务引擎的并发控制。
3. **租约 + 心跳 + 过期重认领（02）**：`leaseId + leaseUntil`，心跳间隔 = 租期/3，心跳 CAS 失败即 abort。进程崩溃自愈不依赖内存。落点：feat-068 的 worker 循环。
4. **幂等键 → sha256 派生 id（03/07）**：`idempotencyKey ? hash(key) : randomUUID()`，重放返回已有实体而非新建。同一模式在 tasks/monitors/actions/files 四处复用。落点：邮件分拣的重复投递防护。
5. **`outcomeUnknown` 语义（05）**：写操作超时/5xx/响应不可解析 → 标 `outcome_unknown` 而非 `failed`，要求用户先对账再重试。落点：任何外部写（SMTP 发信、IMAP 标记已读）。
6. **中断只标记不重放 + "结果未知"文案（04）**：`interrupted` 回执 + "inspect files before running it again"。落点：feat-068 任务中断路径。
7. **SSRF 校验的**方法**（06）**：仅允许 http/https；发请求前校验 host，并拒绝 localhost、环回、私有和保留地址。Memoria 若引入任何"用户给 URL 我去抓"的功能（如邮件里的链接预览），这是必查项。落点：未来的 URL 抓取工具。
8. **限流 pre-auth + key 不取自调用方凭据（06）**：任何"检查 + 慢异步"组合的通用竞态修复。落点：Memoria 若有对外端点。
9. **确定性产卡不经模型（08）**：finance 的 101 行状态机思路——Memoria 的邮件分拣规则命中判断不该交给模型。
10. **三层流式中间件的"补上游缺陷"纪律（01）**：`ponytail:` 注释写明升级条件（上游修好就删）。落点：Memoria SSE 端点（feat-039）。

**明确不搬**：CopilotKit Intelligence 线程持久化（SaaS 依赖，Memoria 自建）；PGlite/Postgres 双后端（Memoria 用 SQLite，只搬 CAS 原语）；浏览器 worker + Linux computer 全套（超出 RAG 问答 + 邮件分拣范围）；JEV 结构化选择面板（TypeSafe 外部服务 + 面板状态机，Memoria 交互面用不上）；E2B desktop（平台耦合）；`maxSteps 6/16` 的具体数字（取决于工具粒度）；CopilotKit AG-UI 协议本身（Memoria 已有 SSE，只搬事件语义）。

## 5. 方法说明

- 与既有 8 篇同源同法：全部结论基于本地 tarball 源码精读（非 README 转述），每篇附证据索引（结论 → 源码 `文件:行`），行号为实读；
- 上游 HEAD 探测：2026-10-12 执行 `git ls-remote https://github.com/CopilotKit/OpenMuse HEAD`，返回 `1ac68f3909f2478ab6280883f1ab5ea65eb5719d`，与本地树一致，故未重新拉取；
- 精读范围：`apps/server/src` 全部 35 文件、`apps/worker/src` 全部 8 文件、`packages/{domain,backends,integrations}/src` 全部、`docs/*.md` 全部、`ROADMAP.md`、`SECURITY.md`；`apps/mobile/src` 抽查（chat.tsx / conversation-queue.ts / conversation-run.ts / date-time.ts，涉及结论标注"抽查"）；
- 一处文档与代码的出入：`docs/VERIFICATION.md:33` 声称覆盖 DST gap，实测 `tests/google.test.ts:558` 校验的是无效日期 `2026-02-29` 而非 DST；DST 间隙处理实际在 `apps/mobile/src/date-time.ts:5-24`（客户端，非服务端）。本系列以代码为准；
- 04b 已覆盖的表面（Chat/Computer/Activity/Ideas/Goals/Documents/Finance/Gmail/Personal context/Rich Threads）在本系列按**机制维度**重组，不复制其 10 表面结构。
