# VERIFICATION — 验证与局限记录

> 2026-10-12 · 本地离线 fixture（Windows 11 / Python 3.14 / Node 22）。本文记录**已验证的行为及其边界**；它不构成"所有计划能力均已完成"的声明——计划项见 `PERSONAL_AGENT_UPGRADE.md` 与 `feature_list.json` 的 todo 条目。
> 纪律（feat-067）：每行 Boundary 必填——"什么没覆盖"与"什么覆盖了"同等重要。能力边界三处同文（模型 prompt 合同 + UI 文案 + 本文 Boundary 列），改一处必须改三处（AGENTS.md Change Discipline）。

## Automated checks

- `python -m pytest -q` → **231 passed, 0 failed, 0 skipped**（2 个第三方 DeprecationWarning：chromadb/anyio，非本项目代码）。全套件 100% 离线：LLM/Embedder/Gmail/图全部注入 fake，零网络调用。
- `cd frontend && npm run build` → green（tsc strict 零诊断 + vite 产出）。
- `pwsh -NoProfile -File ./init.ps1` → 全量门禁 green（以上两项）。
- **本次未跑/未覆盖的机器检查**：浏览器手工验收未执行（feat-066 审批中心 / feat-069 邮件横幅 UI 仅到构建级验证）；**真实 Gmail 账号端到端验收未执行**（授权→拉信→分拣→提案→归档全链路需要真账号，见邮件行 Boundary）；前端无组件级自动化测试（tsc + build 是唯一机器检查）；CI（GitHub Actions py3.14）结果独立于本地记录。

## Feature acceptance matrix

| Area | Evidence | Boundary |
|---|---|---|
| RAG 检索与引用 | tests/test_rag_eval.py：recall@4 = 3/3，MRR = 1.00（feat-053 IDF 调优后基线）；test_rag_answer.py 12 个含引用契约 | 评测语料仅 4 文档 3 查询（小语料结论，大语料教训已由 test_narrow_recall_window_finds_nothing 钉住）；引用校验只验 [n] 覆盖，不验引用内容与句义一致 |
| Wiki 编译 / lint | tests/test_wiki_ops.py 13 个：ingest prompt 三段式缓存前缀、跨次 ingest 目录块逐字不变、矛盾检测 | 页面选择为关键词 top-K（无向量召回参与）；矛盾检测 deep=true 才跑，每链接对一次 LLM 调用（成本受 max_pairs 限制） |
| 邮件分拣与红线 | tests/test_mail_triage.py 10 个：10 封仅 1 次 LLM 调用、保护状态逐封独立（LLM 全标营销仍拦住验证码/交易）、批量残缺回退 | **真实 Gmail 账号端到端验收未执行**（feat-069 已完成生产接线与 token 加密，离线测试覆盖到"token 存在→非交互构建"与"缺 key 拒绝"，但授权→拉信→归档全链路需真账号跑一次）；规则层仅特征串匹配，长尾依赖 LLM 层兜底；营销归档始终需人工提案批准 |
| 定时任务与通知收件箱（feat-068） | tests/test_tasks.py 8 个（at-most-once：claim 即推进 next_run_at；崩溃重放靠 idem_key 去重；过期租约重认领；失败按 attempts 幂等通知；收件箱 append-only 只能标读）+ test_web_api 注入 engine 的端点测试 | 失败重试为固定间隔（无 2^n 退避）；心跳假设单进程执行；引擎随 create_app 启动（Gmail 未就绪则不启动），无独立 worker 进程；通知无推送，仅审批中心面板查看 |
| Gmail 连接与 token 加密（feat-069） | tests/test_mail_auth.py 8 个（Fernet roundtrip/缺 key 读写拒绝/legacy 明文过同一 key 门/60s 提前刷新/非交互永不弹浏览器）+ test_web_api.py 4 个（health mail 能力、坏 token 降级不阻塞启动、triage mail_ready） | token 密钥来自环境变量，无密钥管理服务；刷新去重为进程内锁（单进程假设）；加密文件格式无版本字段（换算法需重授权） |
| 提案审批（feat-066） | tests/test_proposals.py 9 个（六道闸/过期/恢复/outcome_unknown）+ test_web_api.py（提案制删除/重建/归档全链路、hash 不符 409、重启 executing→outcome_unknown、对话通道无批准路径） | 归档执行经图完成（本机 SqliteSaver），未做双进程并发验收；提案过期清算在 decide 时惰性判定，后台定时清算待 P1 worker；审批中心 UI 未做浏览器手工验收 |
| 文档删除与重建 | test_web_api.py：删除后 store.count()==0 且 doc_id 不在 documents()（红线）、raw 消失、404；重建后 total_chunks 不变 | 删除仅移除向量与 raw 文件，已编译 Wiki 页面刻意保留（记录在提案 payload 与 log.md） |
| Web API 与图编排 | tests/test_graph.py 13 个（路由/中断/恢复/提案回执）+ tests/test_web_api.py 70+（全端点）| 无鉴权、仅绑 127.0.0.1（单用户边界，PERSONAL_AGENT_UPGRADE §4.4）；`/api/agent` 无前端调用方（CLI agent 子命令为实际自由文本路径） |
| 出站网络（SSRF） | tests/test_net.py：仅 HTTPS/443、私网拒绝、DNS 重绑定窗口封堵、重定向 ≤3、响应上限 | 自研 http.client 层（feat-065 评估保留）；无证书钉扎；代理 fake-IP 环境会误拒（feat-060 记录，用户环境已知） |
| 配置与连通性 | tests/test_web_api.py 配置段（脱敏、跨类型拒绝、批量保存、自愈解析） | 连通性测试只发最小请求，不校验模型实际回答质量 |
| 前端交互 | npm run build（tsc strict 零诊断）；历史验收：feat-020 响应式 390/320/1280 无横向溢出、feat-030/031 浏览器验收存档 gui-test-screenshots/ | 本轮（feat-066/069）UI 无浏览器截图存档；无组件级单测；SSE 流式未实现（feat-039 todo） |

## Release fixes（2026-10-12）

- **records CAS 放弃 json_patch**：SQLite `json_patch` 是 RFC 7396 merge-patch，补丁中的 `null` 会**删除**目标键——实测 `result: {"raw_removed": None}` 被静默吞掉导致 test_delete_document_without_raw_file_still_purges_vectors 失败。**复现在修复前即失败**；改为 Python 侧读-校验-写（进程锁内原子，假设与 SqliteSaver 相同的单进程部署）后全部通过。`ponytail:` 注释记录了多进程升级路径。
- 顺手加固：records.py 的 SQL 全参数化（json_extract 路径走绑定参数），消除动态 SQL 拼接面。
- **google Credentials 时区约定**：google 库内部用 naive UTC 比较 expiry，测试传入 aware datetime 会在库内 TypeError——_needs_refresh 按库约定处理（naive 视为 UTC）。

## Reproduce

```powershell
pwsh -NoProfile -File ./init.ps1        # 全量门禁：pytest 231 + frontend build
python -m pytest -q                     # 仅后端
cd frontend; npm run build              # 仅前端
# Gmail 生产验收（需真账号，Boundary 见矩阵邮件行）：
#   设置 TOKEN_ENCRYPTION_KEY → python scripts/auth_gmail.py → python run_web.py → MailView
```

## Still outside this release

- 真实 Gmail 账号端到端验收（授权→拉信→分拣→提案→归档）
- SSE 流式 + ConversationQueue——feat-039
- 最小记忆层——feat-071
- monitor / MCP server / skill 体系——明确不做（PERSONAL_AGENT_UPGRADE §4.4），条件触发才立项
