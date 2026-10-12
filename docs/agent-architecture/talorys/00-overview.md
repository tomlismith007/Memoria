# Talorys 核心设计 · 00 总览

> 研究对象：`rociiu/talorys` — "Your personal AI agent in your own Cloudflare account"，v0.1.4，MIT
> HEAD：`2cc547c`（main，提交于 2026-10-11；2026-10-12 本地浅克隆，约 1.2 万行 TS/TSX）
> 本篇是系列总览：跨维度共同模式、在既有研究中的定位、对 Memoria 的优先级迁移清单。
> 各维度结论的证据均在其对应文档内，本篇不重复给行号。

## 1. 系列导航

| 文档 | 维度 | 核心源文件 | 一句话核心设计 |
|---|---|---|---|
| [01-agent-loop.md](01-agent-loop.md) | 主循环与上下文 | `agent/runner.ts`、`agent/memory.ts`、`agent/prompt.ts` | async generator 单函数轮次；审批结局注记回灌历史；溢出 ≥8 条才摘要（避免每轮一次 AI 调用） |
| [02-memory.md](02-memory.md) | 记忆系统 | `db/repositories/memories.ts`、`tools/memories.ts` | FTS5 关键词召回 + 4 条最近偏好保底；精确重复刷新 updated_at；遗忘是真删（含向量） |
| [03-semantic-recall.md](03-semantic-recall.md) | 语义召回 | `semantic/`（9 文件） | 三层召回地板（按 embedding 模型分别定默认值）+ RRF 融合 + pullInNewer 新版本拉入；无向量库的 BLOB 工程 |
| [04-tools-approval.md](04-tools-approval.md) | 工具与审批 | `tools/registry.ts`、`db/repositories/pending-actions.ts` | 三级权限；destructive 是另一种工具形状（prepare 解析目标 / commit 批准后执行）；条件 UPDATE 原子认领至多一次 |
| [05-scheduling.md](05-scheduling.md) | 调度与自动化 | `agent/scheduling.ts`、`packages/shared/src/recurrence.ts` | 单 pending one-shot + 触发后重排 + onStart 对账；自写 DST 语义；防重复三闸 |
| [06-provider-budget.md](06-provider-budget.md) | Provider 与预算 | `ai/`、`services/usage.ts`、`packages/shared/src/constants.ts` | 三方法 provider 接口；确定性 mock 走真实工具管线；六计数器 + 硬天花板 |
| [07-security.md](07-security.md) | 安全与认证 | `auth/auth-service.ts`、`api/middleware.ts`、`packages/create-talorys/` | 密码本地 PBKDF2；会话存 HMAC；限流同步占位防竞态；CSRF 三层；提案审批代码强制 |
| [08-data-platform.md](08-data-platform.md) | 数据平台与交付 | `db/`、`services/backup.ts`、`api/`、`packages/create-talorys/` | 单 DO SQLite；追加式迁移 + 独立语义轨道；备份导入幂等；SSE 端点并发认领；安装器幂等对账 |

## 2. 跨维度共同模式

这 8 个维度不是 8 套独立技术，反复出现的是同一批底层决策：

1. **产品约束先于技术选型，能力面显式收窄。** "Tools may only touch the owner's own data through the service layer: no shell, code execution, credentials or arbitrary network access"（`tools/index.ts:11-13`）；三种自动化里两种（提醒、任务摘要）**完全不碰 AI**；provider 为 null 是一等状态（聊天明确报错、其余功能全量可用）。降级不是事后补的，是产品定义的一部分——与 hermes 的"fail-open/fail-closed 按领域定向"同一条规律。
2. **"模型可见面"与"执行面"分离。** 审批卡展示的是服务端写就的 `targetId + summary`，不是模型转述；approve 是 API 专属通道（代码注释："The agent has no way to call this"）；历史消息里的审批结局注记由服务端生成。模型**能说的事**与**能做的事**之间隔着一层服务端写就的记录。
3. **所有"至多一次"都用原子认领/条件更新，不靠内存标志。** 审批 resolve 用 `UPDATE … WHERE status='pending' AND expires_at > now`；调度 fire 用 schedule_id 一致性 + running 态三闸；索引器用单 pass + follow-up 状态机；登录限流用同步占位（beginAttempt）。这是单 DO 同步 SQLite 语义给的底气，也是分布式系统"CAS 认领"模式的单机化。
4. **实测数字进注释。** 三层地板的每个阈值、pullInNewer 的按模型阈值、摘要触发阈值——注释里带**正反例的实测余弦区间与日期**（如 bge-m3 实测 2026-10-10："网球问题" 0.427/0.435、"首都"问题最高 0.384 应保持为空）。数字有出处，换模型就知道要重测——这是"可审计工程决策"的具体形态。
5. **派生数据与真源分离。** 向量是派生数据：不进备份、可重建（reindex）、同请求删除、孤儿定期清；消息上的工具活动是 JSON 列，读时解析失败回落空数组；DO state 只放未读数这种可重算缓存。真源永远是 SQLite 表。
6. **每条日志类表都有寿命。** activity 1000 条环形、login_attempts 24h 清理、pending_actions 30 天清理 + 30 分钟 TTL、automation_runs 定期 prune、sessions 20 条上限——个人部署不会因为"没人清理"而膨胀。
7. **框架默认行为要审计。** `onBeforeSubAgent` 覆写为 404：不覆写时 Agents SDK 会把 `/sub/...` 转发给带空数据库的新 facet、绕过登录限流。一行覆写堵住 SDK 内部机制带来的旁路。

## 3. 在既有研究中的定位

对照本目录 `../README.md` 的六家横向对比与 [hermes/](../hermes/00-overview.md)：

- **形态**：六家全是 coding/通用 harness；Talorys 与 hermes 同属"个人 agent"，但 Talorys 是**唯一把产品形态收窄到"聊天+记忆+任务+定时"并全程围绕单用户约束做工程决策**的样本。它与 Memoria 的产品面直接同构（问答/记忆/任务/邮件定时对应自动化），映射成本最低。
- **循环**：与 Mini-Agent 同属"单函数瘦循环"一档，但事件流形状（`AsyncGenerator<ChatStreamEvent>`）让 SSE、取消、落库在同一个 for-await 里闭环；`withApprovalOutcomes`（审批结局注记）是六家+hermes 都没有的机制。
- **压缩**：比六家都简单——只有滑窗 + 阈值摘要，无两级压缩、无工具输出剪枝。但"溢出 ≥8 条才摘要"的**调用节流**思路是六家没有的：它们都在解决大上下文，没人解决"小上下文下别每轮都付费"。
- **记忆**：比 hermes 的策展记忆（MEMORY.md + 后台 review）轻得多，但**语义召回是全部研究中唯一完整给出"阈值工程"的样本**——三层地板、按模型默认值、拉入阈值、实测记录，可直接作为 Memoria 检索阈值的对照物。
- **工具审批**：与 OpenMuse 的 `waiting_approval` 一等状态同构，但形态更小（prepare/commit 两个函数 vs 任务引擎 + 审批通道隔离），与 Memoria feat-066 提案制几乎一一对应，可直接比对差异（Talorys 多：原子认领、TTL、结局注记、重复签名检测）。
- **调度**：与 hermes cron 的 at-most-once 三件套同构（hermes：分发前推进 next_run_at + CAS 认领 + 投递台账；Talorys：schedule_id 一致性 + running 态 + onStart 对账），两个独立实现互相验证了同一组不变量。
- **安全**：威胁模型最明确的一家（单用户 + 互联网可达 pages.dev）；安装器卫生（secrets 走 stdin、spawn 无 shell、错误输出清洗）是六家+hermes 都没有的维度。
- **平台**：唯一深度绑定 Cloudflare Durable Object 的样本。DO 的"单实例 + 同步 SQLite + alarm"语义是它敢用内存缓存 tripwire、单 shot 日程、同步事务认领的前提——搬结论时要区分**思想**（可迁移）与**机制**（平台耦合）。

## 4. 对 Memoria 的优先级迁移清单

按性价比排序（落点文档标注在括号内）：

1. **三层召回地板 + 按模型默认值表（03）**：`absolute/relative/backstop` 三个数 + "不足 4 条用 backstop 补足"的兜底逻辑，是 Memoria 检索核心（手写检索）最缺的阈值纪律；关键动作是把 Talorys 的**方法**（手测正反例、按模型分别定默认）用 Memoria 自己的 embedding 模型重做一遍，数字不可直接抄。
2. **向量即派生数据的纪律包（03）**：同请求删除（删记忆/文档 = 同事务删向量，功能关闭时也删）+ 孤儿清理 + content_hash 增量重嵌 + 不进备份 + reindex 入口。这是"删文档必须删掉它的全部向量"红线的工程化模板。
3. **pullInNewer 新版本拉入 + `(saved …)` 前缀 + newer-wins 一行注（03）**：被取代的旧事实永不脱离继任者到达模型——Memoria wiki 知识复利场景（同一事实多版本）直接需要；`(saved …)` 前缀与 newer-wins 提示是 ~10 token/条成本的冲突消解，可在记忆层即刻采用。
4. **调度 onStart 对账 + 24h 补跑窗口（05）**：三闸防重复 + "错过 <24h 补跑一次、超 24h 只重排"的补偿策略，对 feat-068 定时分拣的漏跑补偿直接可用。
5. **限额双层 + 六计数器 + 计量回落（06）**：settings 可调 + `LIMIT_CEILINGS` 硬天花板 + provider 实测优先/本地估算回落。Memoria 目前无任何预算防线，个人部署 + 计费 API 场景这是成本收益最高的一项。
6. **destructive prepare/commit + 审批结局注记（04）**：feat-066 提案制的两个增量——目标解析与执行分离（审批卡展示确切目标）、历史注记让模型看到提案结局（防重复提案/谎报完成）。
7. **duplicate-call 内容签名检测（04）**：`name + 键排序 JSON` 签名，同签名第二次直接拒绝并指示用已有结果——LangGraph 工具循环的廉价循环兜底。
8. **beginAttempt 同步占位（07）**：限额检查与失败占位在异步慢操作（PBKDF2）之前同步完成，否则并发请求会在慢哈希窗口内全部通过检查。任何"检查 + 慢异步"组合的通用竞态修复。
9. **RRF 融合（03）**：k=60 的倒数排名融合，Memoria 多路召回（关键词+向量）融合的最省调参方案。
10. **工具错误文案写成修复指令（04）**："Use YYYY-MM-DD or YYYY-MM-DDTHH:MM"、"List tasks to find the exact one"——错误即纠偏提示，模型自纠而非反复撞墙。

**明确不搬**：DO 平台耦合机制（alarm 单 shot、service binding、缓存 tripwire——搬思想不搬机制）；MockAIProvider 的正则意图路由（Memoria 已有更通用的 offline scripted-LLM 模式）；bge 模型的阈值数字（换模型分布即变）；"无出站网络"的能力收窄（Memoria 邮件维度天然需要 IMAP/SMTP，只搬"能力面显式清单"的表述纪律）；prompt-only 伪记忆行（Memoria 记忆注入是真实数据块，newer-wins 提示放 system 段更自然）。

## 5. 方法说明

- 与既有 7 篇同源同法：全部结论基于本地浅克隆源码精读（非 README 转述），每篇附证据索引（结论 → 源码 `文件:行`）；
- 克隆时间 2026-10-12，HEAD `2cc547c`（v0.1.4）；克隆位置 `C:\Users\tom\AppData\Local\Temp\agentresearch\talorys`（与既有研究仓库同目录，可删除）；
- 后端（apps/agent 全部、packages/shared、packages/create-talorys、docs/ 全部）逐文件精读；前端（apps/web）按文档与关键文件抽查，涉及前端的结论明确标注"抽查"；
- 一处文档与代码的出入：`docs/security.md:55-57` 仍描述旧的 `confirmed: true` 确认机制，现行代码是更强的 prepare/commit 提案制（`tools/registry.ts:39-47`）——本系列以代码为准。
