# Hermes Agent 核心设计 · 02 记忆系统

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时，MIT，Python 3.14 + Node
> HEAD：`97a9ae8e`（main，2026-10-11 本地浅克隆）；路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦记忆系统：SQLite 状态库（state.db）、MEMORY.md/USER.md 策展记忆、FTS5/CJK 跨会话召回、会话生命周期、上下文压缩与可靠性工程
> 约定：结论只来自源码；未定位到的机制明确标注"未定位到"

---

## 1. 定位与全景

Hermes 的记忆分**两层三类**：一层是 SQLite 单文件状态库（`state.db`）承载的全部原始对话史（会话/消息/工具输出），一层是 agent 自己策展的蒸馏记忆（`MEMORY.md`/`USER.md` 两个小文件）。三类信息通道：

1. **原始转录**（引用型）：所有 session/message 落 SQLite，靠 FTS5 关键词检索召回，`session_search` 工具暴露给模型，绝不整段进 prompt；
2. **策展记忆**（记忆型）：模型通过 `memory` 工具增删改 `~/.hermes/memories/MEMORY.md`（agent 环境笔记，2200 字符上限）与 `USER.md`（用户画像，1375 字符上限），以**冻结快照**进系统 prompt（`tools/memory_tool_store.py:1-4`、`tools/memory_tool.py:2-5`）；
3. **项目上下文**（指令型）：SOUL.md（身份）/ AGENTS.md 链（项目规则）按优先级发现装载进系统 prompt（`agent/prompt_builder.py:1857-1883`）。

```
每轮 turn
  │
  ├─ 系统prompt（会话开始时构建，前缀缓存稳定）
  │    ├─ SOUL.md / 项目上下文文件        prompt_builder.py:1857-1883
  │    ├─ MEMORY.md + USER.md 冻结快照     system_prompt.py:516-541
  │    └─ 外部 memory provider 块(可选)     system_prompt.py:529-540
  │
  ├─ 本轮用户消息 + <memory-context> 召回块   turn_context.py:902-930（外部 provider 才有）
  │
  ├─ 工具循环：memory 工具写 MEMORY.md；session_search 查 SQLite 全史
  │
  └─ 轮末 finalizer：sync_turn 落库 → 每 10 轮 fork 后台 review agent
       问"该不该存记忆"→ 直写 memory 工具     turn_finalizer.py:775-792
```

状态库本体是一个 1719 行的门面类 `SessionDB`，由 16 个 mixin 组装而成（`hermes_state.py:461-466`），类 docstring 一句话定义并发模型："many reader threads, one writer (WAL)"（`hermes_state.py:466`）。仓库根目录共 34 个 `hermes_state_*.py` 模块，第 7 节展开为什么拆这么细。

## 2. 数据模型（核心表）

全部 DDL 集中在 `hermes_state_common.py` 的 `SCHEMA_SQL`（372 行起）。核心表：

- **`sessions`**（`hermes_state_common.py:382-447`）：一行一个会话。除 id/source/model/timestamp 外值得注意的列：`parent_session_id`（压缩/分支/委派产生的谱系边，FOREIGN KEY 回 sessions 自身，445 行）、`title` + `title_source`（带来源的标题，421-422）、`archived`/`auto_archived`/`pinned`/`hidden` 生命周期位（439-442）、6 个 `compression_*` 计数与冷却列（430-435）、token/成本核算列（404-420）、`rewind_count`（438）。
- **`messages`**（449-480）：`role/content/tool_calls/timestamp/token_count` 之外，有三个记忆系统专用机制列：`_compressed_summary`（压缩交接行标记，468）、`active`（软删除——rewind 置 0，469）、`api_content`（"本轮实际发给 API 的字节"边车，包含注入的 memory-context，重放时字节稳定，471）。
- **`session_model_usage`**（482-502）：按 (session, model, billing_*, task) 复合主键的用量聚合。
- **`system_prompts`**（377-380）：`hash → prompt` 去重表，sessions 经 `system_prompt_hash` 外键引用，避免每行重复存大 prompt。
- **协调表**：`compression_locks`（568-573，会话级压缩互斥）与 `session_turn_leases`（575-580，对话级 turn 租约）都是 `holder + expires_at` 租约行；`gateway_heartbeats`（559-566）记录多进程后端存活，孤儿清扫靠它区分"死了"和"闲着"；`conversation_generations`（544-549）是每 peer 单调计数器，注释明说**永不回收**——回收会造成 ABA 复用已退役的 prompt-cache 亲和身份（523-543）。
- **FTS 虚表**：见第 4 节。

## 3. MEMORY.md 与 agent-curated 记忆

### 3.1 容量与数据结构

`MemoryStore` 是"有界的文件背书策展记忆"（`tools/memory_tool_store.py:1`）：条目用 `"\n§\n"` 分隔符存进纯 Markdown 文件（25 行），**预算按字符数**（模型无关，152 行）：MEMORY.md 默认 2200 字符、USER.md 默认 1375，可经 config `memory.memory_char_limit/user_char_limit` 覆盖（`tools/memory_tool.py:56`）。容量小是刻意的——它是**每轮都随系统 prompt 进上下文的工作记忆**，不是归档库。

### 3.2 谁写：memory 工具 + 后台 review nudge

单一 `memory` 工具支持 `add/replace/remove` 或一个批量 `operations` 列表（`tools/memory_tool_store.py:458-463`）。批量是**全有或全无**：任何一个 op 失败或最终态超预算则整个不落盘，且预算只对**最终状态**检查——所以超限时模型可以在同一个 batch 里"删旧的 + 加新的"一次通过（504-509）。

扩容不是调大上限，而是**逼模型自己整理**：`add` 超限时错误消息返回 `current_entries` 全量条目 + 明确指令"retry as ONE operations batch that removes or shortens stale entries … AND adds this entry"（342-351）；`_render_block` 在系统 prompt 块头里常驻 `当前用量/上限 百分比`（544-550）。防失控护栏：每轮最多 3 次整理失败，超过后返回 TERMINAL 结果"停止重试 memory 调用，先回答用户"（150、170-185）——记忆副作用永不阻塞回复。

**周期 nudge**：`agent_init.py:1301,1325` 设 `_memory_nudge_interval = 10`（config `memory.nudge_interval`）。轮末 `finalize_turn` 里 `_tick_memory_nudge` 每 N 轮置一次 `_should_review_memory`（`agent/turn_context.py:752-761`），触发 `_spawn_background_review`（`agent/turn_finalizer.py:775-792`，刻意排在交付之后、"never competes with the user's task"）：fork 一个继承运行时的 review agent，把对话快照喂给固定 prompt "Review the conversation above and consider saving to memory…"（`agent/background_review.py:1-6, 375-380`）。路由规则写死在 prompt 里（362-374）：USER.md 存"用户是谁"，MEMORY.md 存"运行环境的事实"，一条事实只进一个库。review agent 直写 memory 工具，不碰主对话与前缀缓存（background_review.py:3-5）。

### 3.3 谁读：冻结快照进系统 prompt

`_memory_parts` 把 `store.format_for_system_prompt("memory"/"user")` 拼进系统 prompt（`agent/system_prompt.py:516-525`）。关键设计：**快照在 `load_from_disk` 时冻结**（`tools/memory_tool_store.py:187-218`），会话中途的写入只落盘、不改快照（524-527 的 docstring 明说"mid-session writes don't touch it, preserving the prefix cache"）——代价是本轮写的记忆下一轮才可见，换来的是 prompt 前缀字节稳定。压缩交接注记反复强调"MEMORY.md/USER.md remains fully authoritative regardless of compaction"（`agent/context_compressor.py:5358`）。

### 3.4 写入审批：记忆写可以走人工闸门

memory 工具的写不是直通磁盘：`_gate_or_stage` 先过 write_approval 闸门——放行、拒绝、或**staged（暂存待批）**三态（`tools/memory_tool.py:84-102`）。暂存路径的关键一步是 `_pin_matched_entries`（64-81）：把 replace/remove 当前锁内选中的**完整条目**记录进待批记录，审批通过时只对那条原文生效，重放时若条目已变则拒绝（"审批者审过的就是生效的那条"）。同理，批量操作的 resolve 也是锁内干跑（`tools/memory_tool_store.py:465-470`）。这与人审闸门共享同一套机制，而不需要记忆系统自建审批流。

### 3.5 防御与可靠性细节（值得抄的边角）

- 记忆进系统 prompt = 持久注入面：所有写入过威胁扫描（strict scope），加载时命中的条目在快照里替换为 `[BLOCKED: …]` 占位符，但**原始文本保留在 live 列表**供用户查看删除（`tools/memory_tool_store.py:28-31, 187-201`）。
- 外部漂移检测：文件里出现单条超整库上限的"条目"= 有人绕过工具追加自由文本，任何 replace 都会丢它——此时拒绝写入、存 `.bak.<ts>` 快照并给出补救指引（44-54、591-606）。
- 文件存在但不可读（被锁/权限/编码坏）时拒绝一切写入：把不可读当空文件保存 = 清空记忆（57-63、552-568，解码刻意 strict，`errors="replace"` 会产生会被持久化的有损视图）。
- 写锁是独立 `.lock` 文件上的 fcntl/msvcrt 锁，让记忆文件本身可原子替换（222-261）；写文件是 temp+rename 原子写（582-589）。
- replace 的 `old_text` 匹配做排版折叠（弯引号→直引号、em dash→连字符、空白归一），因为"模型会重新打字"（66-77）。
- **出口脱敏**：凡是发往 memory provider（尤其外部插件）的内容——turn 文本、messages 转录切片、工具参数、委派结果——统一过 `_redact_for_provider`，密钥永不原样进 provider 存档（`agent/memory_manager.py:190-226, 599-629`，issue #115104）；脱敏还学习"本次被掩码的 token"，在其余字段里补杀同一密钥（222-226）。
- **召回块去重**：多个 provider 合并的 prefetch 常重复同一事实，`_drop_repeated_recall_lines` 按 section 去掉自包含重复 bullet——因为召回块会以 `api_content` 边车形式"每轮重放、付费一次直到滚出上下文"（326-369）。带续行的 bullet 永不删，防删掉出处后张冠李戴（339-346）。
- **有界关停**：`shutdown_all` 对后台写队列给 5 秒 FIFO 排水，超时则明确报告放弃了几个写/几个 prefetch（`agent/memory_manager.py:943-977`）——守护线程卡死不阻塞进程退出，但丢什么说清楚。

### 3.6 外部 provider 契约（plugin 化边界）

`MemoryProvider`（`agent/memory_provider.py:84-206`）定义了完整的生命周期钩子：`initialize → system_prompt_block / prefetch / sync_turn（每轮）→ 工具分发 → shutdown`，外加 `on_session_end`（会话结束提取）、`on_session_switch`（/resume、/branch、压缩轮换时重绑会话态）、`on_pre_compress`、`on_memory_write`（镜像内置 memory 工具的写，只镜像真实落盘的 add/replace/remove，`agent/memory_manager.py:873-922`）。约束：内置 provider 恒在，**外部只允许一个**（防止工具 schema 膨胀与后端打架，`agent/memory_manager.py:1-5, 434-444`）；provider 工具不得遮蔽核心工具名（471-483）；琐碎输入（"ok"/"thanks"）跳过召回省一轮往返（`agent/memory_provider.py:66-81`）。

## 4. FTS5 检索与跨会话召回

### 4.1 三个索引的分工

- **`messages_fts`**（主词索引，`hermes_state_common.py:785-791`）：external-content FTS5，经 `messages_fts_src` 视图读 `messages`（777-783）；tool 角色的行只索引前 8192 字符（`FTS_TOOL_CONTENT_PREFIX_CHARS=8_192`，316 行；投影函数 `_fts_indexed_content_sql` 319-321）。v23 起视图/触发器/回填共用同一个投影表达式——注释记录了血泪史：投影曾依赖会漂移的高水位键，导致 FTS5 integrity-check 与已存 token 不一致、索引反复损坏（765-772）。
- **`messages_fts_trigram`**（898-911）：trigram 分词解决 unicode61 把 CJK 拆成单字破坏短语匹配的问题（857-860）。但 trigram 需要 ≥3 字符词元，1-2 字的中文/韩文查询（"项目"、"구글"）全部漏到 LIKE 全表扫描——实测多 GB 库上每次 3-6s CPU（`hermes_state_fts.py:33-39`）。因此它排除 tool 行与 cron/subagent 会话：后者在大装机量上占 ~70% 消息字节，而索引成本是覆盖文本的 ~2.6 倍（`hermes_state_common.py:862-879`）。
- **`messages_fts_cjk`**（`hermes_state_fts.py:40-54`）：自制 ~250 行 C 扩展 `cjk_unicode61`（`native/fts5_cjk/fts5_cjk.c`，252 行）包装 unicode61，把 CJK 连续串重发为重叠 bigram（Lucene CJKAnalyzer 语义），FTS5 短语语义使 bigram 序列等价于**索引速度的 2 字符起子串匹配**。扩展按 best-effort 加载：`.so` 缺失或加载失败时**降级不报错**，且无 tokenizer 的进程会主动 DROP cjk 触发器保写入存活、在 state_meta 里留 `fts_cjk_stale` 面包屑禁止读端供数，等下次在有能力的主机上 `optimize-storage` 重建（`hermes_state_fts.py:112-127, 243-318`）。

### 4.2 查询路由：一条主链路

`search_messages`（`hermes_state_search.py:1063-1084`，慢查询打点默认 1000ms）的核心路由 `_search_messages_impl`（1086 起）：

1. 显式 `role_filter=['tool']` → 直接 LIKE 扫描（tool 行不在 trigram/cjk 索引里，1110-1112）；
2. 非 CJK → `messages_fts` MATCH + BM25 排序（1130）；损坏异常 → `_enter_fts_fail_open` 原子摘除全部 FTS 触发器 + 留 `fts_stale` 面包屑，用 LIKE 兜底**宁可降级不可阻塞写入**（`hermes_state_fts.py:354-426`）;
3. CJK → cjk 索引优先、trigram 兜底（1126-1128 + 1171-1174）；
4. 全部命中为空时补两级松弛：拉丁词与相邻 CJK 粘连导致漏检 → 子串索引重试（1157-1174）；多词 AND 过严 → OR 宽松重试，rank 序保证覆盖词多的行靠前（1176-1183）；
5. 重建进行中 → 用有界 LIKE 扫描补 `(progress, high_water]` 缺口，"旧消息在重建中永不消失"（1146-1155）。

高水位/进度双标记（`fts_rebuild_high_water`/`fts_rebuild_progress`）让新消息的触发器在回填期间照常工作：触发器 WHEN 条件是 `id > high_water OR id <= progress`（`hermes_state_common.py:793-806`）。重建本身分块限流：500 行一块，块间隔 `max(0.2s, 块耗时×4)`——注释记录一次阻塞重建在 25GB 库上握写锁 16 分钟（`hermes_state_fts.py:428-436`）。

存量迁移同样工程化：v11-v22 的旧内联 FTS DDL 完整保留（`hermes_state_common.py:976-986`），"从不给新库执行"，靠 `optimize_fts_storage` 显式迁移；旧影子表 DROP 会阻塞数分钟，所以先改名成 `fts_v22_trash_*` 让后台 worker 分块清空再删（`hermes_state_fts.py:438-441`）。查询入口也有边界：用户 FTS 输入上限 2048 字符（`hermes_state_common.py:329`），`_sanitize_fts5_query` 保留成对引号短语、剥掉不配对特殊字符（`hermes_state_search.py:818`）。

### 4.3 会话时间线（检索之后的导航）

`hermes_state_timeline.py` 是"只读 prompt 索引 + 有界转录跳转；**不做全转录物化**"（1-3）：为 UI/客户端按 prompt 粒度列会话梗概，合成提示（后台委派完成通知等）被 `_SYNTHETIC_PROMPT` 正则滤掉（12-16），压缩交接行经 `project_compaction_message_for_display` 投影（4-6）。它与 `get_anchored_view` 一起构成"先发现、再锚定、再跳转"的三段式导航，任何一步都不把整会话灌进内存。

### 4.4 召回工具：LLM 不参与检索

`session_search` 工具（`tools/session_search_tool.py:1-8`）四种形状由参数推断：DISCOVERY（query，FTS5 命中按**谱系去重**）、SCROLL（session_id + around_message_id，锚点窗口）、READ（整个会话，2000 字符/消息截断，26-29）、BROWSE（最近会话）。"No LLM calls — every shape returns actual DB messages"（第 8 行）。发现形状的预算控制很细：FTS 只取 `id/session_id/role/snippet/...` 投影当"计划输入"（50 行），扫描 300 行再按谱系去重（43 行），默认只**水化排名第一的命中**、其余给梗概（adaptive detail），`exclude_session_ids` 让 agent 标记本轮已查过的会话但封顶 20 个防列表失控（45、180）。两个排序纪律：kanban/subagent/tool 来源完全隐藏，cron 来源**降级不排除**——cron 的重复词表会在裸 BM25 下淹没用户自己的会话，注释称之为"recall blindness"（15-27）。命中后用 `get_anchored_view`（`hermes_state_search.py:732-778`）取锚点窗口 + 会话首尾 bookend，一次调用同时拿到"目标"和"结局"。LLM 摘要与 FTS 的配合方式不是"检索前先摘要"，而是**压缩副产物**：每个会话的压缩交接行（`_compressed_summary=1`）本身可被检索命中，作为该会话的语义入口。

## 5. 会话生命周期

- **创建**：turn 开始即 `ensure_db_session` 建行（"system prompt populated => non-NULL"，`agent/turn_context.py:783-790`）；来源标签（cli/telegram/cron/subagent/…）贯穿全库（`hermes_state.py:1-4` 模块 docstring），`session_key`（source+chat+thread 的路由键）上建索引支撑多平台同键续话（`hermes_state_common.py:727`）。
- **标题**：三级来源 `user > llm > derived` 排名，`_set_session_title` 是**单事务 CAS**——读当前 title/title_source，条件 UPDATE 带 `AND title IS ? AND title_source IS ?`，并发的 `/title` 与在飞的自动命名不会互相覆盖（`hermes_state_titles.py:83-122`）；同谱系续会话自动编号 "my session #2"（23-35）；canonical Bot Chat 的名字即身份，禁止改名（104-110）。
- **压缩轮换**：见第 6 节——压缩不改写原会话，而是结束父行、发布子行（`parent_session_id` 边），会话链是 append-only 谱系。
- **归档/保留**：`archive_stale_sessions(idle_days)` 归档闲置会话（`hermes_state_maintenance.py:295`）；`prune_sessions(older_than_days=90)` 删结束行（322）；启动时 `maybe_auto_prune_and_vacuum` 幂等自动维护——24h 最小间隔、VACUUM 另有 30 天节流且要求 freelist 比例超阈值（"小清理别触发整库重写"）（421-447）。
- **rewind（/undo）**：`rewind_user_turn`（`hermes_state_rewind.py:45-135`）是"持久化历史操作"——**durable transcript 是权威，内存热历史必须与之核对一致**，warm/durable 的 user turn 数或目标文本不等则 `RuntimeError` 拒绝（85-92）；实现是软删除（`active=0`）而非物理删行，复合压缩载体重放时保留隐藏交接脚手架（107-119）。
- **删除的向量纪律**：删会话行会级联触发 FTS delete 触发器同步摘索引（`hermes_state_common.py:808-822`）——"删文档必须删掉它的全部向量"的同构纪律，Hermes 用触发器保证索引与正本永远一致。

## 6. 记忆压缩

压的是**上下文窗口里的 transcript**，不是 SQLite 里的历史。触发：`ContextCompressor` 默认 `threshold_percent=0.50`（有效输入预算的 50%，`agent/context_compressor.py:2804`；阈值公式 `(context_length - max_tokens) * threshold_percent` 再护底，2770-2794），小窗口模型有上浮下限（2755-2759）。

压缩与 SQLite 的关系是**会话轮换**而非原地改写：`_publish_rotated_compaction`（`agent/conversation_compression.py:3317-3385`）在一个事务里"publish closure + child + handoff so no reader sees an empty child"（3342-3343）——父会话以 `end_reason='compression'` 结束，子会话携带压缩后的消息 + 摘要交接行，`agent.session_id` 重指向子会话。谱系查询 `get_compression_chain` 沿 `parent_session_id` 单向前进，明确排除 reset 分叉/委派子会话/分支，避免"续链被劫持"（`hermes_state_compression.py:29-49`），带 1000 步防环上限（81）。

失败治理自成体系：sessions 行上的 `compression_failure_cooldown_until/…streak` 列（`hermes_state_common.py:430-435`）记录各级冷却（split 失败 60s，`conversation_compression.py:66-68`）；`compression_locks` 表 + 租约保证一会话一压缩（`hermes_state_compression.py:61-75` 的 CAS 式租约认领）。与记忆系统的接缝在 `on_pre_compress` 钩子（`agent/memory_manager.py:807-843`）：压缩前把原始 transcript 交给 provider 提取洞见喂进摘要 prompt，v2 API 支持 fail-closed checkpoint——`require_checkpoint=True` 时提取失败则**保留未压缩 transcript**（839-842）。

## 7. 可靠性工程（为何拆 34 个模块）

并发模型（`hermes_state.py` 模块 docstring 1-4 + 类定义 461-466）：**单文件 SQLite、WAL 日志、多进程共享**——CLI/gateway/TUI/cron/桌面后端多个进程同时打开同一个 `state.db`，进程内多读线程 + 单写连接（`_lock` 保护，596）。这解释了绝大多数防御模块：

| 模块 | 防的事故（注释原文证据） |
|---|---|
| `hermes_state_wal.py` | NFS/SMB/WSL1 上 WAL 报 `locking protocol`、ZFS 并发突发下 `-shm` 损坏 → 自动降级 DELETE 日志模式（17-21）；`journal_size_limit=64MiB` 防 WAL 无限膨胀（28-31） |
| `hermes_state_readpool.py` | 无界只读连接钉住 fd 到进程死 → EMFILE。池上限 8/文件、24/进程，拿不到许可**降级到写锁**而非排队——"慢读可恢复，进程级 fd 耗尽不可恢复"（1-5, 47-63） |
| `hermes_state_lockguard.py` | POSIX 锁按进程生效，进程内任何第三方 `close()` 那两个文件都会取消 SQLite 的 WAL 锁（sqlite.org/howtocorrupt §2.2）→ 用 `F_OFD_SETLK` 在 SQLite 自己的描述符上加**描述符级**锁，杂散 close 无法取消（1-15） |
| `hermes_state_repair.py` | 无法治愈的损坏类在每次启动重复修复，每次 ~900MB 取证备份，报告装机量累计 105 次/89GB 相同死拷贝 → 持久化 attempt 账本拒绝第 N 次尝试（37-41） |
| `hermes_state_maintenance.py` | 结束行才可删，但 cron/kanban 进程死了不写 ended_at → 启动孤儿清扫按 `gateway_heartbeats` 心跳区分死活（551-558；421-447） |
| 写耐心分级 | 转录写（失败即中断回合）60s、普通写 20s、活动心跳（响应关键路径上）0.5s；SQLite 确定性 busy handler 在多进程下会护送拥塞，所以短超时 + 随机抖动重试（`hermes_state.py:469-501`） |
| 文件身份校验 | 每次写前比对 (st_dev, st_ino, application_id)，库被 mv/cp 掉包后在原句柄上"原地手术"（619-624） |
| 每 50 写 PASSIVE checkpoint | 防/checkpoint 雪崩（501, 1045-1046） |

拆分的元原则在模块 docstring 里反复出现：拆出来是为了"tests patch `hermes_state_wal.<name>`"（`hermes_state_wal.py:3-4`）——每个可靠性策略独立成可打补丁、可测试的单元；以及每个策略都带一个 issue 编号的血泪故事（#86747、#98573、#100436、#118026…），**注释记录事故→代码承载对策**。另外四个小模块补全生命周期：

- `hermes_state_health.py`：每库路径一个进程级**粘滞损坏闩锁**——结构损坏曾表现为侧栏空白 + readiness 绿灯 + /api/sessions 500，各表面各自猜测没人说"库坏了"（#72046，1-9）；闩锁永不自愈，"在 ok 和 corrupt 之间闪烁正是它要消灭的静默失败"（16-19），FTS 范围的损伤走 fail-open 不进此闩锁。
- `hermes_state_guard.py`：测试隔离守卫——pytest 上下文的进程**永远打不开生产 state.db**（env 传递，子进程也受保护）；实地事故是"pytest fixture 行落进了生产库、pytest 子进程在活 WAL 写者底下翻转了日志模式"（1-8）。
- `hermes_state_registry.py`：同路径共享单实例 + 引用计数 + 代际感知退休（1-11）；`close()` 在共享实例上只减引用（hermes_state.py:644-647，#90837）——否则一个调用方关掉别人还在用的库。
- `hermes_state_schema.py`：自愈式迁移——迁移前探测触发器变体、按 legacy/v23 分支重建，CREATE TRIGGER 的 `IF NOT EXISTS` 无法修复"同 body 已存在但形态不对"的触发器，所以先 DROP 再重放 DDL（250-270, 306-326）。

## 8. 设计规范清单（可直接照抄）

1. 记忆双层：原始史全量落库只检索不进 prompt；策展记忆小容量进 prompt。
2. 策展记忆有字符预算，超预算的错误消息**返回全部现有条目**并要求一个 batch 内"删旧+加新"。
3. 系统 prompt 里的记忆块用**加载时冻结快照**，保前缀缓存；写入落盘但本会话不生效。
4. 记忆写入过注入扫描；命中条目快照置 `[BLOCKED]` 但保留原文供用户处置。
5. 每 N 轮 fork 后台 review agent 问"该存什么记忆"，直写 memory 工具、不碰主对话。
6. FTS 索引坏了**摘触发器保写入**，读端 LIKE 兜底，留面包屑等重建。
7. 外部内容 FTS 的投影函数单点定义，视图/触发器/回填共用，integrity-check 永不漂移。
8. 检索工具零 LLM 调用，返回真实 DB 消息 + 锚点窗口 + 首尾 bookend。
9. 压缩 = 会话轮换（父结束、子续写），谱系 append-only，`parent_session_id` 单向边。
10. 标题/租约/锁全部单事务 CAS；"读写一事务，并发写输给先到者"。
11. 多进程共享单 SQLite：WAL + 读写分离 + 描述符配额 + OFD 锁护卫 + 文件身份校验。
12. 每个可靠性策略注释里带 issue 编号与量化事故（105 次修复/89GB 死备份）。

## 9. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| 冻结的 MEMORY.md 快照 + `api_content` 边车 | 中途写记忆导致 prompt 前缀漂移、缓存全 miss |
| 超预算错误携带 current_entries + batch 全或无 | 模型反复 add 失败死循环、记忆只增不减 |
| 每轮整理失败上限 3 次即 TERMINAL | 记忆副作用卡死用户回复 |
| cjk_unicode61 bigram tokenizer | 1-2 字 CJK 词漏进 LIKE 全表扫（3-6s/查询） |
| cron 来源降级不排除 | 自动化词表在 BM25 下淹没用户会话（recall blindness） |
| FTS fail-open（摘触发器 + 面包屑） | 索引损坏阻塞一切写入 |
| 高水位 + 进度双标记触发器 | 回填期间新消息既不丢也不重复入索引 |
| 压缩轮换（新会话）而非原地改写 | 半写状态被读者看到；原会话可审计 |
| `on_pre_compress` fail-closed checkpoint | 压缩丢提取洞见且不可逆 |
| rewind 校验 warm vs durable | 内存/磁盘不一致时 undo 静默错删 |
| 读连接许可制（拿不到就降级） | 多会话网关进程 EMFILE 全局瘫痪 |
| OFD 锁护卫 WAL 代际 | 进程内第三方 close() 撤销 POSIX 锁 → 库损坏 |
| 修复尝试持久账本 | 不可治愈损坏每次启动重复 900MB 备份 |

## 10. 对 Memoria 的可迁移结论

Memoria 现状：wiki Markdown 为 SSOT + Chroma 向量库 + SqliteSaver checkpoint；红线要求回答带来源引用、检索核心手写、删文档必须删掉全部向量。Hermes 的记忆体系与它正好构成"**记忆型知识 vs 引用型知识**"的分工镜像：

适合搬：

- **双层记忆的分工表**（Hermes 的 USER.md/MEMORY.md 路由 prompt，`agent/background_review.py:362-374`）：Memoria 的 wiki 已经是"引用型知识"SSOT（带来源、可检索），可以补一层 2200 字符级的**记忆型知识**（用户偏好、问答风格、常见误检索模式）——小、贵、每轮在场；wiki 大、廉价、按需检索。两者在 prompt 里显式声明"一条事实只进一个库"。Hermes 的教训同样适用： USER.md 管用户，MEMORY.md 管环境，"misrouting it puts it where the next session won't look"（background_review.py:370-372）。
- **冻结快照 + 前缀缓存纪律**：Memoria 若把 wiki 摘要动态拼进系统 prompt 会打爆 prompt cache；学 Hermes 在会话开始装载快照、中途写盘下会话生效（`tools/memory_tool_store.py:524-527`）；注入进用户消息的检索召回若需重放，用 `api_content` 边车思想把"实际发送的字节"持久化（`agent/turn_context.py:119-139`）。
- **超预算整理协议**（错误消息携带现有条目 + batch 原子性 + 每轮失败上限）：wiki 条目增长时的自动精简可以直接照抄这套"逼模型自己合并"的协议，不需要额外守护进程；Hermes 还证明成功写会重置失败预算（`tools/memory_tool_store.py:529-542`）。
- **FTS5 做引用型知识的第二索引**：Chroma 向量检索召回语义近邻，但 Memoria 红线要求精确溯源（哪篇文档哪一段）；Hermes 证明 external-content FTS5 + 触发器同步 + CJK bigram 扩展（`native/fts5_cjk/`，MIT，252 行 C，可直接编译加载）能在 SQLite 里低成本做精确子串检索，且中文 2 字词查询是向量检索的已知盲区。LangChain 只用 integrations 的约束下，FTS5 走 sqlite3 原生即可，不算引入检索框架。"删文档删向量"的红线在 Hermes 有同构实现：删行触发器同步摘 FTS 索引（`hermes_state_common.py:808-822`）。
- **fail-open 检索纪律**：索引损坏降级 LIKE/向量兜底、绝不阻塞主链路写入，留面包屑等重建（`hermes_state_fts.py:354-426`）——Memoria 的向量库重建期间问答不应瘫痪。
- **会话轮换式压缩**：LangGraph checkpoint 若长对话压缩，学"父结束子续写"的谱系模式保留可审计性，配合 Memoria 的来源引用红线（摘要行本身可追溯）；压缩前给记忆提取留 fail-closed 检查点（`agent/memory_manager.py:807-843`）。
- **检索工具零 LLM、形状按参数推断**（`tools/session_search_tool.py:1-8`）：Memoria 的问答 agent 可以用同一模式暴露"查 wiki 历史"工具——discovery 返回命中文档 + 顶部结果全文水化，避免每轮把整库灌进上下文；cron 式自动化内容**降级不排除**的排序纪律同样适用于 Memoria 的邮件索引。

不适合搬：

- **34 个 state 模块的可靠性体系**：那是多进程网关 + 多平台（telegram/cron/kanban）单文件库的代价；Memoria 单人应用、Chroma 承担检索、SqliteSaver 只存 checkpoint，WAL + busy_timeout 足够，readpool/OFD lockguard/修复账本/文件身份校验是过度工程。
- **gateway/telegram/kanban 领域 mixin** 与 Memoria 无关。
- **`api_content` 边车的全量重放机制**：Memoria 不做多平台消息重放，成本大于收益；只取其"存下实际发送字节"的思想用于调试。
- **外部 memory provider 插件体系**（`agent/memory_provider.py`）：单用户单库用不上第二记忆后端，YAGNI。

## 11. 证据索引

| 结论 | 文件:行 |
|---|---|
| 记忆双层定位 / SessionDB 模块 docstring | `hermes_state.py:1-4` |
| SessionDB 16 mixin 组装 / "many readers one writer" | `hermes_state.py:461-466` |
| sessions/messages/用量/协调表 DDL | `hermes_state_common.py:372-610` |
| session_key 路由索引 | `hermes_state_common.py:727` |
| session_search 发现预算（300 行扫描/自适应水化/排除上限） | `tools/session_search_tool.py:43-50, 180` |
| conversation_generations 永不回收（ABA） | `hermes_state_common.py:523-549` |
| 主 FTS + 视图投影 + 高水位触发器 | `hermes_state_common.py:773-854, 316-321` |
| trigram 表与 cron/subagent 排除理由 | `hermes_state_common.py:857-895` |
| CJK 索引 DDL / trigram 3 字符缺陷 / 扩展加载 / fail-open | `hermes_state_fts.py:20-54, 112-127, 354-426` |
| cjk_unicode61 扩展本体 | `native/fts5_cjk/fts5_cjk.c`（252 行）、`native/fts5_cjk/README.md` |
| MemoryStore 预算/分隔符/冻结快照/漂移/锁 | `tools/memory_tool_store.py:25, 152, 187-218, 524-527, 591-606, 222-261` |
| 超预算整理协议 / batch 原子性 / 失败上限 | `tools/memory_tool_store.py:342-351, 458-522, 150-185` |
| 记忆目录与 config 上限 | `tools/memory_tool.py:38-61` |
| MemoryManager fan-out / recall 块 / pre_compress checkpoint | `agent/memory_manager.py:372-388, 807-843` |
| provider 出口脱敏 / 召回去重 / 有界关停 | `agent/memory_manager.py:190-226, 326-369, 943-977` |
| memory 写审批三态 + 条目钉扎 | `tools/memory_tool.py:64-102` |
| 外部 provider 契约与单外部上限 | `agent/memory_provider.py:84-206`；`agent/memory_manager.py:434-444` |
| 记忆进系统 prompt | `agent/system_prompt.py:516-541` |
| 每轮召回注入 + trivial prompt 门 | `agent/turn_context.py:893-930, 108-116`；`agent/memory_provider.py:66-81` |
| nudge 间隔与后台 review | `agent/agent_init.py:1301-1325`；`agent/turn_context.py:744-761`；`agent/turn_finalizer.py:775-792`；`agent/background_review.py:1-8, 362-380` |
| 上下文文件优先级与动态上限 | `agent/prompt_builder.py:1161-1182, 1777-1883` |
| 压缩阈值 0.50 与预算公式 | `agent/context_compressor.py:2755-2794, 2804` |
| 压缩会话轮换发布 | `agent/conversation_compression.py:3317-3385` |
| 压缩谱系/租约/链上限 | `hermes_state_compression.py:29-81, 61-75` |
| 标题 CAS 与谱系编号 | `hermes_state_titles.py:23-35, 83-154` |
| rewind 持久历史权威 | `hermes_state_rewind.py:1-8, 45-135` |
| session_search 工具 / cron 降级 / 消息截断 | `tools/session_search_tool.py:1-29, 652-680` |
| 搜索路由 / 缺口补充 / OR 松弛 | `hermes_state_search.py:1063-1183` |
| 查询输入上限 / 旧 FTS 迁移 / 分块限流 | `hermes_state_common.py:325-326, 976-986`；`hermes_state_fts.py:428-441` |
| 时间线只读索引 | `hermes_state_timeline.py:1-16` |
| 损坏闩锁 / 测试守卫 / 共享注册表 / 触发器自愈 | `hermes_state_health.py:1-19`；`hermes_state_guard.py:1-8`；`hermes_state_registry.py:1-11`；`hermes_state_schema.py:250-270` |
| 锚点视图 | `hermes_state_search.py:732-778` |
| WAL 兼容降级 / size limit | `hermes_state_wal.py:17-31, 86-93` |
| 读池许可 / 进程上限 | `hermes_state_readpool.py:1-5, 47-63` |
| OFD 锁护卫动机 | `hermes_state_lockguard.py:1-15` |
| 修复账本 / 89GB 事故 | `hermes_state_repair.py:37-41` |
| 自动维护 / 孤儿清扫 | `hermes_state_maintenance.py:295, 322, 421-447` |
| 写耐心分级 / checkpoint 节奏 | `hermes_state.py:469-501, 1045-1046` |
| 压缩注记"记忆始终权威" | `agent/context_compressor.py:5358` |
| SOUL.md/项目上下文装载优先级 | `agent/prompt_builder.py:1857-1883`；`agent/context_file_sources.py:25-34` |
