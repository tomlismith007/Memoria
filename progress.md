# Session Progress Log

## Current State

**Last Updated:** 2026-10-12
**Active Feature:** feat-066/067/069/068/071 completed（P0 + P1 全部落地）；下一步 feat-039（SSE+ConversationQueue，P1 收官）

## Status

### 2026-10-12 会话记录

- 全仓库 ponytail-audit 复查 + hermes-agent（8 维度）/ OpenMuse（全表面）研究沉淀至 `docs/agent-architecture/`（commit f1e2825）。
- 个人 agent 方向定案（grill-me 两轮，D1-D12 见 `docs/PERSONAL_AGENT_UPGRADE.md` §0）：**Memoria 本体升级为准个人 agent**；hermes 不做基座。
- **feat-066 DONE**：提案审批子系统。records 单表 CAS + 八态提案（hash+30min 过期+单次消费）+ decide 独立端点；归档/删除/重建索引三类破坏性动作统一提案制；图内执行 + 节点回写终态；outcome_unknown 一等态 + 启动恢复；前端审批中心 + 徽标。211 tests + build green。证据见 feature_list.json。（commit 5c9992d）
- **feat-067 DONE**：文档纪律最小包。`docs/VERIFICATION.md`（日期头/免责句/211 passed 数字/9 行 Area|Evidence|Boundary 矩阵/Release fixes 记录 json_patch 坑/Reproduce/Still outside）；feature_list.json 60 条 completed 全部补 limitation；红线三处同文（classify.py prompt 合同补"正文不可信+不构成归档许可"，UI/ARCHITECTURE 经核已达标）；AGENTS.md 新增"三处同文"与"enforced vs instructed"纪律；RAG_UPGRADE_PLAN 免责句。211 tests + build green。
- **feat-069 DONE**：邮件生产通电。token.json Fernet 加密（TOKEN_ENCRYPTION_KEY，fail-closed：缺 key 读写拒绝，legacy 明文过同门迁移加密）；60s 提前刷新 + 进程锁去重；interactive=False 启动永不弹 OAuth；create_app 接线 + health capabilities.mail + triage mail_ready；MailView 引导横幅。223 tests + build green。VERIFICATION Boundary：真账号端到端验收仍待跑。cryptography 加入 pyproject。
- **feat-071 DONE**：最小记忆层。MemoryService（content-hash 去重/上限 100/CAS 编辑/原子遗忘）+ qa 节点数据块注入（'不是指令，不是许可'同句）+ GET/POST/编辑/遗忘 API + AskView'记住这条'按钮。237 tests + build green。limitation：管理面板 UI 未做、编辑不重算 id。
- 下一步：feat-039 SSE+ConversationQueue（P1 收官）。

### What's Done

- [x] Harness initialized (AGENTS.md, feature_list.json, progress.md, init.sh, init.ps1, session-handoff.md)
- [x] `docs/ARCHITECTURE.md` v2: 6 节标准结构（系统目标→模块→数据流→选型→约束→非目标）；选型已定 Chroma + OpenAI 兼容接口 + Gmail 只读 scope
- [x] feat-001 DONE: pyproject + src/memoria, editable install OK, init.ps1 green
- [x] feat-002 DONE: src/memoria/rag/{parse,chunk,embed,store,ingest}.py; 8 passed
  - doc_id = hash(origin) → 同路径重 ingest 原子替换，无重复向量
  - delete → where={doc_id} 全删，无孤儿向量（红线✓）
  - search 返回 (doc_id, chunk, start) 引用三元组
  - Embedder 为 Protocol：Fake（测试/离线）+ OpenAI 兼容（env 配置）
- [x] CI: `.github/workflows/ci.yml` (push/PR 跑 pytest, py3.14)；AGENTS.md 已注明；无 CD（无部署目标，见非目标#5）

- [x] feat-003 DONE: rag/retrieve.py（向量+关键词重排，加权合分）+ rag/answer.py（[n]→引用三元组）+ llm.py（ChatLLM 协议，email 复用）; 14 passed
  - 无命中不调 LLM，直接返回"无法回答"（防幻觉，省调用）
  - 越界引用 [9] 自动丢弃
  - 中文关键词按 bigram 切分（\w+ 整串无交集的坑已修）
  - FakeChat（测试）+ OpenAICompatibleChat（env 配置）
- [x] feat-004 DONE: wiki/pages.py（Wiki 类 + extract_links + 默认 schema.md）; 21 passed
  - ensure_layout 建 raw//wiki/，schema 缺才写（用户改动永不覆盖）
  - write_page 路径钳制：非法名直接拒，raw/ 代码级不可写（红线✓）
  - build_index 从 [[链接]] 重生成 index.md；append_log 记变更
- [x] feat-005 DONE: wiki/ops.py（ingest/query/lint）; 28 passed
  - ingest：`## [[页名]]` 分节解析，超 max_pages(10) 截断并记 log；垃圾输出零写入
  - query：先读 index 选页（非法页名过滤），再带页正文回答
  - lint：断链+孤立纯静态；矛盾只查有链接关系的页对（有界 max_pairs），YES 才报
- [x] feat-006 DONE: mail/{rules,classify,gmail}.py; 34 passed
  - 规则层先行：验证码/交易 → protected，永无归档路径（红线✓，混合邮件保护优先）
  - LLM 分类（营销/通知/待办）+ 一句话摘要；垃圾输出回退 通知+snippet
  - archive 双门禁：仅营销+非保护 → candidate；archive 必须 confirmed=True（否则 PermissionError）
  - pyproject 新增 google-api-python-client；凭据归调用方，模块只收 service 对象
- [x] feat-007 DONE: graph/{state,nodes,graph}.py; 39 passed
  - router（LLM 一词分类，垃圾输入回退问答）→ qa / mail / ingest 三分支
  - 节点零重复逻辑：qa=rag.answer，mail=classify+request_archive，ingest=wiki.ingest+lint
  - confirm_archive 用 interrupt：无 pending 直接过；有 pending 则暂停等人工 resume（批准/拒绝双测）
  - mail_archive 只执行 approved 且在 pending 内的 id
- [x] feat-008 DONE: sync.py（dual_ingest/hybrid_answer/archive_qa/archive_fact）; 44 passed
  - 双写：IngestResult 加 text 字段，向量+Wiki 单次解析
  - 混合查询：Wiki 先行 → LLM 充分性门（默认 fallback 到 RAG，不冒薄答案风险）→ 细节合并，引用穿透
  - 沉淀：问归档 synthesis 页（问题消毒防路径逃逸）；邮件事实入页（重复摘录去重）
- [x] feat-009 DONE: cli.py + __main__.py（`python -m memoria {ingest|ask|lint}`）; 48 passed
  - 薄封装：argparse → sync/wiki 函数；真实客户端走 env（MEMORIA_CHROMA/WIKI/LLM_*/EMBED_*）
  - main(argv, deps) 可注入 fakes，离线可测
- [x] docs/DESIGN.md DONE: 圆角卡片 (rounded-2xl/3xl) + 胶囊按键 (rounded-full) + 温暖骨白与低饱和粉彩规范
- [x] feat-010 DONE: Web API service (FastAPI 暴露 /api/ask, /api/wiki, /api/mail, /api/ingest, 挂载静态前端); 55 passed total
- [x] feat-011 DONE: 前端工程搭建与 docs/DESIGN.md 胶囊/圆角卡片组件系统 (PillButton, RoundedCard, PillBadge, SegmentedNav, ConfirmModal)
- [x] feat-012 DONE: 问答与 Wiki 双向链接交互界面 (AskView 句级溯源切片展示与一键沉淀 Wiki; WikiView 索引与双向反向链接漫游)
- [x] feat-013 DONE: 邮件安全分拣中心与双写摄入界面 (MailView 交易/验证码物理级保护不提供归档，营销邮件强制人工弹窗二次确认；IngestView 拖拽上传与即时双写反馈)
- [x] feat-014 DONE: 对话历史流与富文本 Markdown 渲染引擎 (AskView 连续追问会话、自动滚动、行内 [[Wiki]] 词条与 [n] 引用芯片交互解析)
- [x] feat-015 DONE: 模型与环境变量设置抽屉 (SettingsModal 与后端 /api/config 接口，支持拉取可用模型与连通性延迟诊断)
- [x] feat-016 DONE: Gmail 本地 OAuth 鉴权工具 (scripts/auth_gmail.py 与 memoria/mail/auth.py 开箱即用生成凭据令牌)
- [x] feat-019 DONE: 本地 Web 安全边界（配置 Key 脱敏/空值保留、localhost CORS、邮件新鲜候选门禁、raw 路径穿越防护）；全量 70 passed，前端构建通过
- [x] feat-017 DONE: 配置历史预设（服务端最多 10 个快照、Key 脱敏响应、保存/应用/删除、旧配置兼容）；全量 73 passed，前端构建通过
- [x] feat-018 DONE: 问答历史 localStorage 持久化（版本化 envelope、刷新/Tab 恢复、归档状态、新建会话清空、损坏数据回退）；全量 73 passed，浏览器冒烟通过
- [x] feat-020 DONE: 移动端响应式 UI（窄屏图标导航、44px 触控、Header 收缩、五个页面长文本重排）；390/320px 无横向滚动，桌面导航无回归
- [x] feat-021 DONE: 统一 SSRF 安全出站层（公网 HTTPS/443、DNS 全结果校验与 IP pinning、同源重定向、identity/响应大小限制）；全量 92 passed
- [x] feat-022 DONE: 删除本地模型供应商路线，配置与出站统一公网 HTTPS/443；旧非法预设过滤，配置 API 即时拒绝 HTTP/localhost/非 443；全量 95 passed，前端构建通过
- [x] feat-024 DONE: 纯自定义供应商管理界面重构与刷新零丢失双重持久化；两栏式供应商布局（左侧供应商列表/状态指示点，右侧Base URL、格式、API Key及模型列表维护，模型测试与标签管理），后端 settings.json 与前端 localStorage 双重持久化，AskView 对话端当前模型展示与直接切换；全量 97 passed，前端构建通过 (0 errors)
- [x] feat-025 DONE: 供应商协议贯通；OpenAI 兼容 Chat Completions、Claude/Anthropic Messages、OpenAI Responses 三种协议可选并持久化，模型列表、连通性测试和实际聊天按协议构造请求；全量 102 passed，标准 init.sh 绿灯
- [x] feat-026 DONE: 彻底移除添加供应商弹窗，改为右侧面板直接内联新建；点击「添加供应商」直接在右侧进入空白表单模式，输入供应商名称、Base URL、协议与 API Key，直接调用「获取模型」一键拉取并选取模型，可在未保存前一键「测试当前配置」，点击「保存并生效供应商」自动落盘持久化并设为激活状态，提供「取消」按钮安全回退；全量 102 passed，前端构建 0 错误
- [x] UI 精细打磨: 提问对话框首屏居中沉浸、发送后平滑落底吸附、纤长胶囊外形 (h-11/12, max-w-4xl)、黑曜石黑 (#09090b) 圆形发送按钮、移除底部说明小字
- [x] Launcher: `python run_web.py` 一键启动全栈服务并在浏览器中自动打开
- [x] Harness & Verification: `init.ps1` 同时验证 101 项后端测试与前端 `npm run build`，100% 绿灯
- [x] feat-027: `AGENTS.md` 固化 Ponytail 最小实现阶梯、根因修复、复用优先、安全例外、harness 五子系统与证据闭环；`validate-harness` 100/100
- [x] feat-028: 按代码审查报告完成低风险死代码清理、重复配置校验收敛、邮件类别单一来源和 HTTP 入口收紧；将 14 个配置路由拆到 `web/config_routes.py`，保留运行时激活闭包与 API 契约；`init.ps1` 101 passed + frontend build green
- [x] feat-029: 将 ProviderTemplatePicker、ProviderSidebar、DeleteConfirmDialog 从 SettingsModal 拆为纯受控组件；主文件 1,932→1,642 行，状态/API/localStorage 仍集中；修复 390px Provider 头部与模型操作行挤压；`init.ps1` 101 passed + frontend build green，浏览器模板/侧栏/删除确认/移动端冒烟通过
- [x] feat-030: 按用户参考图将模型设置收敛为极简双栏；压缩标题/说明、去除重复徽章与重复入口、合并模型区、简化模板选择器和模型行；保留 Provider/Model 全部状态与 API 流程；`SettingsModal.tsx` 1,642→1,571 行；`init.ps1` 101 passed + frontend build green，1280px/390px 浏览器验收通过
- [x] feat-031: 删除对话/向量手填输入框；设置页新增对话模型与向量模型页签；后端新增 `active_embed_provider_id`，向量 Provider 保存/激活/删除与对话 Provider 完全隔离；embedding-only 连通性测试支持；全量 103 passed + frontend build green，1280px/390px 浏览器验收通过
- [x] feat-065: 全仓库 ponytail-audit 整改，分三批独立提交。删 3 份结论已被反转的计划文档（1088 行）、裁剪 progress.md 的 Evidence 段（-1219 行文档与状态）、`.agents/` 取消跟踪；删后端 4 处写死没人读 + 前端 6 个零引用 hook 键 / 10 个零引用 tailwind 色 / 15+ 个未读响应字段；模型保存的单条与批量路由合并到 `_apply_model_saves`（config_routes.py 547→514）。净减 1263 行，跟踪文件 102→88。196 passed + frontend build green

### What's In Progress

- [ ] 无；feat-001..feat-064 已完成，feat-023 已完成。

### What's Next

1. feat-038（多步摄入图循环）与 feat-039（SSE 流式回答）均标记为可选，未排期
2. 保持全套测试与 Harness 门禁（`./init.ps1`）100% 绿灯通过

## Blockers / Risks

- [ ] No `bash` on this Windows machine — `./init.sh` cannot run here; use `./init.ps1`. Risk: agent following AGENTS.md blindly runs init.sh and fails. Mitigation: AGENTS.md documents both.
- [ ] feat-019 残余边界：CORS 不是认证；`data/settings.json` 仍以本地明文保存 Key；邮件候选集合仅适用于单用户单 worker。
- [ ] feat-018 边界：localStorage 恢复的是前端时间线，不会自动作为模型上下文；未完成请求在刷新后不恢复。
- [ ] feat-024 残余边界：Provider/Model 状态与异步流程集中在 `useProviderConfig.ts`（908 行，79 个返回键）；本次精简只删了 6 个无引用键，尚未拆分。
- [ ] feat-031 残余边界：切换向量模型不会自动重建既有向量索引；不同向量模型的维度/语义空间可能不兼容，需要人工重建或后续校验。

## Decisions Made

- **LangGraph over LangChain LCEL**: system is a state machine (routing, multi-step ingest, human-confirm nodes), not a single chain.
- **Hand-write core retrieval** (~100 lines: vector search + rerank + generate); LangChain only for integrations.
- **Feature granularity**: 31 features, one at a time; red lines encoded in AGENTS.md § Red Lines.
- **Minimalist Capsule Design**: Canvas `#FAFAF9`, Obsidian Black `#09090b` accents, `rounded-3xl` cards, `rounded-full` pills, zero decorative emoji / heavy drop-shadows.

## Notes for Next Session

- Read `docs/ARCHITECTURE.md` first — it holds the full spec from the product brief.
- Red lines are absolute: no auto-archive, raw/ read-only, delete vectors on doc delete, cite every sentence.
- Standard launch command: `python run_web.py`.
- Standard verification command: `./init.ps1`.
