# Session Handoff

## Current Objective

- Goal: **Memoria 本体升级为准个人 agent**（2026-10-12 grill-me 定案，D1-D12 见 `docs/PERSONAL_AGENT_UPGRADE.md`）。LangGraph 保持生产编排器；hermes/OpenMuse 研究为模式参考库（`docs/agent-architecture/`）。
- 路线：P0 审批实体化 + 文档纪律 → P1 任务引擎 + 邮件通电 + SSE 对话流 + 最小记忆层 → P2 观望区（monitor/MCP/skill 均不做，见指南 §4.4）。
- Current status: feat-001..065 完成；**feat-066（P0 提案审批）+ feat-067（P0 文档纪律）完成**；feat-069/068/071 已立项待做；feat-039 已扩范围（SSE+ConversationQueue）待做。

## 本轮做了什么（2026-10-12）

1. **研究沉淀**（commit f1e2825）：hermes-agent 八维度深读（`docs/agent-architecture/hermes/`，HEAD 97a9ae8e）+ OpenMuse 全表面深读（`04b-openmuse-alpha-surfaces.md`，main 1ac68f3）+ 2026-10-11 全仓库 ponytail-audit 复查（净余 ~150 行小收敛项，无大死代码）。
2. **立项**：feature_list.json 新增 feat-066..069、071；feat-039 扩范围（SSE+ConversationQueue 语义）。
3. **feat-066 DONE（P0 审批实体化）**：
   - `memoria/records.py`：单表 records(kind,id,data) SQLite 存储；CAS 用 Python 侧读-校验-写（进程锁内原子）。**坑**：SQLite json_patch 是 RFC7396 merge-patch，patch 里 null 会删键（`result: {"raw_removed": None}` 被静默吃掉），故弃用。
   - `memoria/proposals.py`：八态提案（archive/delete_doc/reindex），六道闸 decide（hash→幂等→状态→过期 CAS→原子 claim），outcome_unknown 一等态，`recover_interrupted()` 启动恢复。
   - 图：confirm_archive 中断载荷分型 `{type:"approval"}`；mail_archive 节点执行后回写提案终态（网络级错误→outcome_unknown，决不假装成功）；build_graph 增 proposals 参数（CLI 不传，None 安全）。
   - 路由：GET/POST `/api/proposals`、`POST /api/proposals/{id}/decide`（全系统唯一批准通道）；`/api/mail/archive` 改为创建提案；直连 `DELETE /api/documents/{id}`、`POST /api/rag/reindex` **已下线**并入提案制。
   - 前端：`components/ApprovalCenter.tsx`（审批中心）+ App 顶栏待审徽标（tab 切换时刷新）；MailView 归档、IngestView 删除/重建改走 propose→decide。
   - 测试：211 passed（基线 196，+15）；test_chat_channel_cannot_approve_proposals 锁定"对话通道无批准路径"边界。
   - 备注：Mimosa 钩子对 test_graph.py 报过一次 SQL 注入误报（测试文件无 SQL）；顺手把 records.py 改为全参数化 SQL（json 路径走绑定参数）。
4. **feat-067 DONE（P0 文档纪律）**：
   - `docs/VERIFICATION.md` 新建：日期头+免责句、Automated checks（211 passed + 明记未跑项）、9 行 Area|Evidence|Boundary 矩阵、Release fixes（json_patch RFC7396 null 删键坑）、Reproduce 块、Still outside。
   - feature_list.json 60/60 条 completed 特征补 limitation 字段。
   - 红线三处同文：classify.py SYSTEM/BATCH_SYSTEM 补"正文不可信 + 分类结果不构成归档许可"；MailView/ARCHITECTURE 经核已达标；AGENTS.md 新增"三处同文"与"enforced vs instructed"两条纪律。
   - RAG_UPGRADE_PLAN.md 头部免责句。

## Verification Evidence

| Check | Command | Result | Notes |
|---|---|---|---|
| 后端全量 | `python -m pytest -q` | **211 passed** | 基线 196 → 211（+15） |
| 前端构建 | `cd frontend && npm run build` | green | tsc 零诊断 |
| 全量回归 | `pwsh -NoProfile -File ./init.ps1` | green | pytest + build |

## Commit State

- `f1e2825` docs(agent-architecture): 研究沉淀 + 个人 agent 升级设计指南
- `5c9992d` feat(proposals): 审批实体化——破坏性动作统一走 hash 绑定提案 (feat-066)
- feat-067 实现待提交（本文件更新后即提交）

## Next Session Startup

1. 运行 `pwsh -NoProfile -File ./init.ps1`（预期 211 passed + build green）。
2. 阅读 `AGENTS.md` → `docs/PERSONAL_AGENT_UPGRADE.md`（路线与边界）→ `feature_list.json` → `docs/VERIFICATION.md` → 本文件。
3. 下一个 feature：**feat-069 邮件生产通电**（token 加密 + get_gmail_service 接入 create_app + 真账号验收），然后 feat-068 任务引擎 → feat-071 记忆层 → feat-039 SSE。
4. 启动命令：`python run_web.py`（审批中心入口：顶栏盾牌图标）。
