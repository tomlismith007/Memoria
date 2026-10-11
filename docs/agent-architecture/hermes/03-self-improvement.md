# Hermes Agent 核心设计 · 03 自改进

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时，MIT，Python 3.14 + Node
> HEAD：`97a9ae8e`（main，2026-10-11 本地浅克隆）；路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦自改进闭环：skill 作为程序性记忆的格式与两级披露、自动创建/更新链路（background_review fork）、index 维护与缓存、curator 生命周期、轨迹导出与训练闭环
> 约定：结论只来自源码；未定位到的机制明确标注"未定位到"

---

## 1. 定位与全景

Hermes 把"自我改进"拆成**两个闭环**：一个在线（会话内即时生效的 skill 增删改），一个离线（轨迹导出供模型训练）。在线闭环的分工：

```
每轮结束（turn_finalizer）
  ├─ 迭代数达阈值 → spawn background_review fork（后台线程）
  │    └─ 重放对话快照 → 自问"该存什么 skill/记忆" → 直接调 skill_manage/memory 写盘
  ├─ 空闲数日 → curator（生命周期管理：stale→archive、LLM 整合 fork，opt-in）
  └─ skill 变更 → skills_index_delta 在下一轮 user-note 通道宣布差异（不动 system prompt）
写盘位置：~/.hermes/skills/（或 skills.create_dir）；生效：下一轮即可 skill_view 加载
```

模块映射：skill 文件解析与目录栈在 `agent/skill_utils.py`；写工具在 `tools/skill_manager_tool.py`（动作派发表 `tools/skill_manager_tool.py:720`）；审查 fork 在 `agent/background_review.py`（prompt 文本也在这里，`agent/background_review.py:357`）；生命周期在 `agent/curator.py` + `tools/skill_usage.py`；索引新鲜度在 `agent/skills_index_delta.py`。定位口号写在 skill 工具 docstring 里：**"Skills are the agent's procedural memory (narrow 'how to do X'); MEMORY.md/USER.md are broad, declarative"**（`tools/skill_manager_tool.py:1-6`）。

仓库根还有个易混淆点：`skills/` 与 `optional-skills/` 是**出厂自带**技能包（构建时装进用户技能目录），运行时用户态技能库在 `~/.hermes/skills/`（profile 隔离）。本篇讲的是运行时那一套。

## 2. Skill 文件格式与两级披露

### 2.1 目录布局与 frontmatter

- 一个 skill = 一个目录：`<skills>/[category/]<skill>/SKILL.md` + 可选 `references/ templates/ scripts/ assets/` 四类支持目录（`tools/skill_manager_tool.py:5-6`）。支持目录**不会被当作独立 skill 扫描**，只能经 `skill_view(skill, file_path=...)` 显式加载——这就是渐进披露的第二级（`agent/skill_utils.py:29-31`）。
- frontmatter 用 YAML，解析失败降级为逐行 `key:value` 切分（`agent/skill_utils.py:66-86`）。真实样例（`skills/email/email-inbox-triage/SKILL.md:1-12`）：`name / description / version / author / license / platforms / metadata.hermes.{tags, related_skills}`。条件字段还有 `environments`（kanban/docker/s6 运行环境门，仅"要不要出现在索引"的 offer-time 过滤，显式加载永远成功，`agent/skill_utils.py:109-169`）与 `requires_apps`（未知名字 fail-closed 隐藏，`agent/skill_utils.py:172-191`）。
- description 是一级披露的全部内容：**截断到 60 字符**进系统 prompt 索引（`SKILL_PROMPT_DESC_LIMIT = 60`，`agent/skill_utils.py:822-839`）。创建时若超限，工具直接把"系统 prompt 会显示成什么样"回显给作者模型（`tools/skill_manager_tool.py:417-424`）。

### 2.2 两级披露的运转

- 一级：system prompt 里的 `<available_skills>` 索引块，每行 `- name: 60字符描述`（渲染在 `agent/prompt_builder.py:1472-1487`），配一段强制措辞："Before replying, scan the skills below... you MUST load it with skill_view(name)"、还有"If a skill has issues, fix it with skill_manage(action='patch')"（`agent/prompt_builder.py:1466-1470`）——索引本身就在教模型如何**修**技能。
- 二级：`skill_view(name)` 返回全文 + `usage_hint` 指向支持文件（`tools/skills_tool.py:640`）；工具头注释自述为 "list and view skill documents (progressive disclosure)"（`tools/skills_tool.py:2`）。
- 值得抄的作者纪律：真实 skill `hermes-agent`（本项目自己的操作手册，ESSENTIAL_SKILLS 永不可禁用，`agent/skill_utils.py:256-258`）自述 "**This skill is a hub.** The body covers identity, quick start, spawning/orchestration, and hard invariants. Everything else lives in reference files — load the matching reference (below) before answering"（`skills/autonomous-ai-agents/hermes-agent/SKILL.md:22-25`）。
- 索引条目的解析口径与 `skill_view` 一致：按 frontmatter `name`、目录名、相对路径三个别名建立所有权（`agent/skill_utils.py:452-487`）；focus 模式把非编程类降级成 `[names only]` 一行——"never hidden, every name stays visible"（`agent/system_prompt.py:301-303`、`agent/prompt_builder.py:1445-1459`）。

## 3. 自动创建/更新链路（background_review fork）——本篇主链路

### 3.1 触发：谁调起 fork

- 每轮收尾检查：`_should_review_skills = agent._skill_nudge_interval > 0 and agent._iters_since_skill >= agent._skill_nudge_interval and "skill_manage" in agent.valid_tool_names`（`agent/turn_finalizer.py:763-768`）。`_iters_since_skill` 按**工具迭代数**累加（`agent/provider_projection.py:45`、`agent/codex_runtime.py:704`），默认阈值 10，config 键 `skills.creation_nudge_interval`（`agent/agent_init.py:1380-1382`）。
- spawn 总闸在 `run_agent.py:752-782`（`_spawn_background_review`）：delegate 子代理深度 >0 不跑；config `auxiliary.background_review.enabled` 关闭不跑；**交付之后才跑**（"runs AFTER delivery so it never competes with the user's task"），cron 等无人在场场景用 `skip_background_review` 压掉——注释给出成本账："the fork costs ~30K tokens / event with no human-in-the-loop benefit"（`agent/turn_finalizer.py:778-791`）。管理本地 llama-server 的 review 进 idle 队列等机器空闲，被新一轮抢占的 review 有界重排队（≤3 次，`run_agent.py:780-782`、`run_agent.py:825-840`）。
- 另有显式触发：`/refine` 命令（"Review this conversation now and save lessons to memory/skills"，`hermes_cli/commands.py:156`），走 `explicit=True` 路径不受 idle 门控。
- 配置读取 **fail-open**：读不到 config 时审查保持开启并 WARN（`agent/background_review.py:228-240`）。

### 3.2 fork 构造：缓存平价是第一设计约束

`build_cache_parity_fork`（`agent/background_review.py:956-1041`）构造一个"寄生"的 AIAgent：

- 继承父 agent 的**活的运行时**（provider/model/凭据/凭证池，`agent/background_review.py:245-275`）；同模型路径下**逐字节继承父的 `_cached_system_prompt` 与 `tools[]`**——"the fork's outbound HTTP request hits the same Anthropic/OpenRouter prefix cache the parent warmed... measured impact (~26% end-to-end cost reduction on Sonnet 4.5)"（`agent/background_review.py:1000-1005`）。广告的 tools[] 与派发权限分离："Dispatch stays behind the review whitelist; advertising is not permission"（`agent/background_review.py:945-951`）。
- 持久化完全隔离：`_persist_disabled = True`、`_session_db = None`，fork 与父共享 session_id 但不写 state.db——否则 fork 的 harness turn 会被下一个活轮次读回成"常驻指令"（`agent/background_review.py:985-999` 的注释块）。
- 派发白名单（`_review_tool_whitelist`，`agent/background_review.py:1079-1146`）：`memory`+`skills` 工具集 + 只读的 `read_file`/`search_files`；**写工具（write_file/patch/terminal）保持拒绝**——"autonomous maintenance must go through skill_manage's validation"。拒绝只读工具曾造成灾难："~142 denials + ~204 read-before-write refusals over 2 days... starved the self-improvement loop"（`agent/background_review.py:1091-1097`）。危险命令守卫在 fork 线程上自动 resolve 为 "deny"，防 input() 死锁（`agent/background_review.py:1042-1048`）。
- 路由到不同模型时（config `auxiliary.background_review.{provider,model}`），前缀缓存必然 miss，fork 改为重放对话摘要（digest）而非全文（`agent/background_review.py:956-977`）。

### 3.3 审查 prompt：写什么、不写什么

prompt 是这套系统真正的"宪法"（`agent/background_review.py:357-560`），三份变体：memory-only、skill-only、combined（L375/L440/L511）。skill 版要点：

- **主动姿态**："Be ACTIVE — most sessions produce at least one skill update, even if small. A pass that does nothing is a missed learning opportunity"（`agent/background_review.py:441-442`）。
- 目标形态是**类级（class-level）skill** + SKILL.md 常驻规则 + 少量 topical `references/`，而非每会话一个窄技能、也非伞形技能囤积 per-session 文件（L443-445）。
- 修正优先级四级：1) patch **本会话加载过的** skill → 2) patch 现有伞形 → 3) 加支持文件（references/templates/scripts 各归其位）→ 4) 才准建新技能，且名字必须类级——"NOT a PR number, error string, codename..."（L462-487）。
- 用户风格抱怨是**一等 skill 信号**："Frustration signals like 'stop doing X'... are FIRST-CLASS skill signals, not just memory signals"（L448-451）。
- **负面清单**（`_DO_NOT_CAPTURE_BLOCK`，L405-438）最精彩：环境性故障（缺二进制/未装包）不是规则；对工具的**负面断言会硬化成 agent 自我引用数月的拒答**（"These harden into refusals the agent cites against itself for months"）；未解决的失败不得写成"reliable workflow"——"That presents an untested sequence of failures as validated guidance"。
- 同一课学两次 = 一条规则，先搜后加；修错就地改那句，不许追加 "UPDATE: actually..."（L398-404）。

### 3.4 执行与护栏：写盘直达，但戴着镣铐

- fork 直接调 `skill_manage` 工具写 `~/.hermes/skills/`（创建动作 `_create_skill`，`tools/skill_manager_tool.py:453-496`：校验 name/category/frontmatter/size → 重名拒绝 → 目录 mkdir（EEXIST 仅空白目录可用，"anything else... is someone else's: never adopt"）→ 原子写）。
- **Read-before-write 是硬闸**：背景审查 fork 内 patch 已有 SKILL.md 或覆盖已有支持文件前，必须在**本次审查内** `skill_view` 过该文件；"Content quoted earlier in the conversation transcript does NOT count"（`agent/background_review.py:490-496`）。实现为 ContextVar 读标记集 + 写守卫（`tools/skill_manager_guards.py:28-60`）；`read_file` 也注册读标记（`agent/background_review.py:1092-1097`）。`_guarded_write` 流程：读守卫 → 原子写 → 安全扫描，扫描被拦则**回滚原文件/删除新文件**（`tools/skill_manager_tool.py:396-415`）。
- 事后安全扫描是 **opt-in**（`skills.guard_agent_created` 默认 False，`tools/skill_manager_tool.py:60-76`），但 terminal 工具跑同样的代码不受此门——自动审查的额外限制是白名单与守卫，不是扫描。
- 禁区：审查 fork "Never delete a skill here"，重叠技能只许在回复里提一句，交给 curator 处理（`agent/background_review.py:506-508`）。外部目录与项目技能对自主维护**只读**（"autonomous lifecycle maintenance treats them as read-only"，`agent/skill_utils.py:694-704`）。
- 生效即时性：写盘即完成——下一轮模型按索引调 `skill_view` 就能读到新内容。索引层面的"系统 prompt 里那份 `<available_skills>` 已过时"问题由 §4.2 的 delta 通道解决。

### 3.5 产出的记账与观测

- 写了什么由 `summarize_background_review_actions` 从审查 fork 的 tool 结果里提取人类可读摘要：只认 `memory`/`skill_manage` 两个"notify 工具"的成功调用（辅助工具成功不算工作，`agent/background_review.py:615-626`），verbose 模式把 patch 的 old/new 各截 80 字符回显（L581-598）；已有快照里的 tool 消息跳过，避免把继承结果当新工作重报（L699-733，#14944）。notification_mode=off 时一个字都不向用户展示——自动学习默认安静。
- **成本记账归还父会话**：fork 无 DB，`_record_review_usage_to_parent` 把 six 项计数（in/out/cache_read/cache_write/reasoning/api_calls）经 aux-accounting 只写 `session_model_usage`，"never the transcript or sessions row"（`agent/background_review.py:759-787`）。每次审查结束打一行 completion 日志把成本显形（L804-812）。
- 结果分类成 `none / skill / memory / skill+memory` 四值（前缀匹配本地化标签，`agent/background_review.py:789-802`），供下游统计审查命中率。
- 连 OpenRouter 的 provider 路由 pin（`providers_order` 等 6 个属性）也要逐字节继承——"prompt caches live per UPSTREAM provider, so a fork without the parent's pins can land on a different upstream and miss the warm cache even with byte-identical prompt/tools bytes"（`agent/background_review.py:814-822`）。

### 3.6 非自动路径：斜杠命令与预处理（同一写库的另一面）

- 每个 unique 技能自动注册成斜杠命令 `/skill-name`（slug 化，保留 Unicode 字母以支持 CJK 技能名，`agent/skill_commands.py:33-37、444-478`）；与核心命令撞名则跳过注册并提示改用 `/skill <name>`（L429-441）。`/work 修一下标题` 这类调用被展开成一条 user 消息：激活头 + **技能全文** + `[Skill directory: ...]` + 已解析的技能配置块 + 支持文件清单，用户指令缀在尾部（`_build_skill_message`，`agent/skill_commands.py:331-381`）。静态脚手架与易变指令的边界用 `register_stable_prefix` 显式声明给缓存规划器（L366-381，#81867）。
- 会话级预载有两条：`hermes -s <skill>`（CLI 启动参数，禁用技能按"缺失"上报而非报错）与 config `skills.auto_load`（每次新会话全量注入，"Treat its instructions as active guidance for the duration of this session"，`agent/skill_commands.py:829-900`）。
- SKILL.md 支持两种装载期预处理（默认模板开、内联 shell 关，`agent/skill_preprocessing.py:142-156`）：`${HERMES_SKILL_DIR}`/`${HERMES_SESSION_ID}` 模板变量（解析不了就原样保留让作者看见），以及 `` !`cmd` `` 内联 shell 展开——输出截 4000 字符、失败返回标记字符串而不抛异常（L15-86）。内联 shell 对 **hub 社区技能一律关闭**：lock 里 trust_level=community 的安装树即使被 `--force` 装上也不自动执行（"auto-executing it on view would re-arm exactly what the gate refused"，L99-139，#63307）。
- 编辑型技能包可整包进批处理：`tools/skill_manager_batch.py` 提供 batch 动作并保证回滚不会误删批前已存在的技能（`tools/skill_manager_batch.py:142`）。Web 仪表盘也走同一个 `_create_skill`（`hermes_cli/web_routers/skills.py:419-426`）——写路径只有一条，多入口。

## 4. Skills index 的维护

### 4.1 构建与缓存

- 索引由 `build_skills_system_prompt` 渲染，解析优先级与 `skill_view` 完全一致：trusted project > local profile > `skills.create_dir` > `external_dirs`（四级 tier，`agent/skill_utils.py:381-403`；渲染器 `agent/prompt_builder.py:1361-1389`）。同层级同名是**拒绝而非猜测**——"Inside ONE tier two different skills sharing a name stay ambiguous — refused, never guessed"（`agent/skill_utils.py:383-384`），同名不同层则高层 shadow 低层并一次性 warn（`agent/skill_utils.py:452-487`）。
- 项目本地技能（`<root>/.hermes/skills`、`.agents/skills`）是提示注入向量：只有 repo 在 `skills.trusted_project_dirs` 里才加载，且每个 SKILL.md 过 skills_guard 扫描，"dangerous" 判定隔离（fail-closed：扫描器崩溃也隔离），扫描缓存放 HERMES_HOME 而非仓库内（`agent/skill_utils.py:490-644`，防 `git pull` 把恶意 skill 塞进已信任仓库 #48974）。
- 索引带磁盘快照缓存（manifest + snapshot，`agent/prompt_builder.py:1213-1258`），mid-session 装载技能 skill 进 prompt 有 `register_stable_prefix` 声明缓存断点（`agent/skill_commands.py:366-381`）。
- `skills/index-cache/` 是 **hub 商店目录缓存**（第三方 skill 市场的目录 JSON：anthropics/skills、lobehub 各一份，含 `trust_level` 字段），由 `tools/skills_hub.py:65` 解析——与运行时索引无关，勿混淆。

### 4.2 变更如何到达模型（skills_index_delta）

system prompt 一次构建终身复用以保前缀缓存，会话中途装/删的 skill 就到不了索引。解法（`agent/skills_index_delta.py:1-15`，移植自 cloudflare/cloudflare-os#267）：

- 每轮把"prompt 携带的索引"与"现在会重建出的索引"对比，把**全量差异**作为一条一次性 note 附在下一条 user 消息上（per-turn note 通道，位于缓存前缀之后）："Now available (load with skill_view(name)...)" / "No longer available: ..."（L26-66）。note 记录全量差而非增量，"so the prompt plus the newest note is the complete record of what the model was told"（L12-13）。
- 差异状态从"prompt 索引 ∪ 最新 note"推导（`_announced` 反向解析转录里的 note，L87-97），压缩重建 prompt 后若索引已含先前 note 的内容则不再重复（L121-126）。
- `/reload-skills` 重扫并返回 added/removed diff，但**故意不失效 system prompt 缓存**——"skills are called by name, so /reload-skills costs no cache reset"（`agent/skill_commands.py:661-668`）。

## 5. Curator：生命周期与整合（第二角色）

- 触发是**不活跃驱动**（无 cron daemon）：agent 空闲且距上次运行超过 `interval_hours`（默认 7 天，最短空闲 2 小时）时 `maybe_run_curator()` 自动推进生命周期状态（`agent/curator.py:1-8`、`agent/curator.py:23-26`）。
- 状态机：active → stale（14 天未用）→ archived（30 天，移入 `.archive/`，**永不删除，只归档**）；`pinned` 技能豁免一切自动转换；只碰 `created_by: agent` 标记的技能（skill_manage 写入的显式标记，"never inferred from location"，`tools/skill_usage.py:1-6`）。用量遥测在 sidecar `.usage.json`（键为技能名，不进 SKILL.md，跨进程文件锁原子写）。
- LLM 整合 fork（把碎片技能合并成伞形）**opt-in**：`DEFAULT_CONSOLIDATE = False`，`hermes curator run --consolidate` 可单次覆盖（`agent/curator.py:25-26`、`agent/curator.py:147`）。整合要求模型输出带围栏 YAML 块（`consolidations:` / `prunings:` 列表），解析器只认这个结构（`agent/curator.py:545-566`）；整合重命名后由 cron 任务重写引用（`agent/curator.py:682-683`）。
- **整合 fork 的硬规则写进 prompt**（`agent/curator.py:289-340`）：不碰 bundled/hub/外部目录技能；永不删除（"Archiving... is the maximum destructive action. Archives are recoverable; deletion is not."）；pinned 与受保护内建（plan）完全跳过；被 cron 引用的技能不许 prune（curator 会重写 cron 引用所以可整合）；**用量计数不得作为整合或裁剪依据**（"use=0 is not evidence a skill is valuable; it's absence of evidence either way"，30 天以下的新技能不许归档）。正文超 ~24k 字符的 SKILL.md 本身就是整合目标——skill_view 会把全文载入上下文（`agent/curator.py:312-314`）。
- **审批边界**：`--dry-run` 模式跳过 stale/archive 转换，fork 的 prompt 头部加 DRY-RUN 横幅——"These are the actions you RECOMMEND, not actions you took. A downstream reviewer will read the report and decide whether to approve a live run"，意外做了变更须在摘要里自首以便回滚（`agent/curator.py:266-288`、`agent/curator.py:881-896、915-928`）；报告仍写 REPORT.md。首次安装种子 `last_run_at` 并推迟一个周期，"a fresh install/update never mutates the library on its first tick"（`agent/curator.py:161-177`）。

## 6. 轨迹导出与 evals：离线训练闭环

- **运行时轨迹导出**：`save_trajectory` 把对话转成 ShareGPT 格式按 `completed` 追加到 `trajectory_samples.jsonl` / `failed_trajectories.jsonl`，跨进程文件锁防 JSONL 交错（`agent/trajectory.py:37-58`）。开关在 `run_agent.py` 控制台入口（`save_trajectories` flag，`run_agent.py:1489-1520`）与批跑器 `batch_runner.py:273`。格式转换时把 `<REASONING_SCRATCHPAD>` 归一成 `<think>`（`agent/trajectory.py:11-14`），并检测未闭合的 scratchpad（L18-19）——训练数据里的推理痕迹是专门处理过的。
- **后处理**：`trajectory_compressor.py` 是独立 CLI，把轨迹压进 token 预算——保护头（system/human/首 gpt/首 tool）与最后 N 轮，中间按需摘要，绝不拆散 `<tool_call>/<tool_response>` 对（`trajectory_compressor.py:1-9`）。
- **任务生成**：`mini_swe_runner.py` 在 local/docker/modal 环境跑任务并写出 Hermes 轨迹格式，"compatible with batch_runner.py and trajectory_compressor.py"（`mini_swe_runner.py:1-8`）。
- **明确边界：仓库内没有 RL 训练器或在线权重更新**。`evals/` 目录（约 80 个子目录/脚本）是线协议/回归评测（gateway wire、compaction、provider fallback 等），不是训练循环。Hermes 的"自改进"在运行时 = skill 闭环；轨迹导出服务的是**离线模型训练**（Nous 侧用），二者通过 JSONL 文件松耦合，仓库内未定位到任何把 eval 结果自动反馈回 skill/prompt 的代码。
- evals 也有少量自改进相关观测面：`evals/prompt_footprint`、`evals/tool_search`、`evals/toolperf_abeval` 等目录名提示它们测的是 prompt 体积与工具选择质量——是**人看的回归基线**，不回写运行时（基于目录清单，未逐个精读）。
- 技能自身也带版本字段（`version: 3.2.0`，`skills/autonomous-ai-agents/hermes-agent/SKILL.md:3`），但未定位到任何消费该字段做迁移/兼容判断的运行时代码——目前是纯元数据。

## 7. 护栏总账：什么能自动做，什么需要人

| 动作 | 自动性 | 依据 |
|---|---|---|
| 审查 fork 新建/patch 技能、写 MEMORY/USER.md | 自动（写盘直达） | `agent/background_review.py:1-7`、白名单 L1079-1146 |
| 修改既有内容 | 自动但须本次审查内重新读过（read-before-write） | `agent/background_review.py:490-496` |
| 删除技能 | 审查 fork 永不；curator 永不，只归档 | `agent/background_review.py:506-508`、`agent/curator.py:306-308` |
| 外部/项目技能的自主维护 | 只读（用户显式指令的工具调用才可写） | `agent/skill_utils.py:694-704` |
| LLM 整合/裁剪 | opt-in + dry-run 报告 + 人工跑 `hermes curator run` 批准 | `agent/curator.py:266-288、881-928` |
| 危险命令 | 审查线程自动 deny | `agent/background_review.py:1042-1048` |
| 事后安全扫描 | opt-in（`skills.guard_agent_created`），被拦回滚 | `tools/skill_manager_tool.py:60-76、396-415` |
| 项目技能装载 | 需 repo 级一次性信任 + 每次内容变更重扫描 | `agent/skill_utils.py:490-644` |

## 8. 设计决策取舍

1. **写盘直达，审批靠结构不靠人**：background_review 不产生"提案等人批"，而是白名单 + read-before-write + 禁删 + 只归档四道结构闸把风险压住。换来的是自改进零等待；代价是自动审查可能写错内容——用 `_DO_NOT_CAPTURE_BLOCK` 的 prompt 宪法与 curator 的事后归档兜底。
2. **缓存平价优先于一切**：fork 逐字节继承 system prompt/tools[]、持久化隔离、note 通道避开前缀——自改进的每次观测都被设计成"不弄脏主对话的缓存"。
3. **程序性知识与陈述性知识物理分离**：skill（怎么做事）/ MEMORY.md（环境事实）/ USER.md（用户是谁）三库互斥写入，一个事实只进一个库（`agent/background_review.py:361-371`）；重复写入被明确定义为失败模式（"until both hit their size limits"，#30220）。
4. **审查 prompt 是活文档**：大量规则来自真实事故的 issue 号（#30220、#63307、#12260……），prompt 注释即变更记录——把"模型行为事故"编译成下一版 prompt 约束。
5. **宁可 fail-open 也不静默失效**：审查配置读不开就保持开启并 WARN（`agent/background_review.py:232-240`）；投影扫描器读不了 hub lock 就视为社区技能、关掉内联 shell（`agent/skill_preprocessing.py:129-131`）。

## 9. 设计规范清单（可直接照抄）

1. skill = 目录 + SKILL.md（YAML frontmatter，description ≤60 字符）+ references/templates/scripts/assets 四类支持目录。
2. 两级披露：系统 prompt 只放索引行；正文按需 `skill_view`；支持文件按需 `skill_view(name, file_path=)`。
3. 自动创建入口单一（`skill_manage`），写盘位置固定（profile skills 目录或 `skills.create_dir`），写完即生效。
4. 后台审查 fork：继承父运行时与缓存前缀，持久化隔离，派发白名单只含 memory/skills/只读工具。
5. Read-before-write 硬闸：改已有内容必须本次会话内重新读过；转录里出现过的引用不算。
6. 自主审查永不删除；删除/归档只归 curator，且只归档不删、pinned 豁免、只碰 `created_by: agent` 的技能。
7. 索引变更走 per-turn note 通道宣布全量差，不动 system prompt 字节。
8. 同层同名拒绝解析（ambiguity refused, never guessed）；跨层 shadow 高层优先。
9. 审查 prompt 明确"负面清单"：环境性故障、工具负面断言、未验证的失败序列不配成为规则。
10. 轨迹导出（ShareGPT JSONL）+ 压缩器 + 批跑器构成离线训练原料链，与在线 skill 闭环解耦。

## 10. 知识点表

| 做法 | 解决的问题 |
|---|---|
| skill 作为程序性记忆，独立于 MEMORY/USER | 会话经验跨会话复用但不污染用户画像 |
| 迭代数阈值触发后台审查（默认 10） | 每轮都审查太贵，完全不审则学不到 |
| fork 缓存平价（继承 prompt/tools[]/session_id） | 后台学习把主对话的 prefix cache 打穿（实测省 ~26%） |
| 派发白名单 + 只读工具放行 | 写权限失控；同时避免拒绝风暴饿死学习循环 |
| read-before-write 硬闸 | 凭转录印象 patch 把技能改坏 |
| `_DO_NOT_CAPTURE_BLOCK` 负面清单 | 把一次性故障固化成永久自我设限 |
| skills_index_delta note 通道 | 索引陈旧 vs 重建 prompt 破坏缓存的两难 |
| curator 只归档不删 + pinned | 自动维护误删仍在用的技能 |
| `created_by: agent` 显式标记 | 自动生命周期误碰用户手写技能 |
| description 60 字符硬截断 + 创建时回显 | 索引膨胀挤占上下文 |
| 轨迹 JSONL + 文件锁追加 | 多进程写同一训练文件交错损坏 |

## 11. 对 Memoria 的可迁移结论

适合搬：

- **"审查 prompt + 结构闸"模式**：Memoria 的 wiki 写作规范（schema.md）可以照 Hermes 的方式分层——目标形态（什么算一篇好 wiki 页）、修正优先级（先改已有页再建新页）、负面清单（哪些一次性信息不配进 wiki）。Memoria 的 LangGraph 工作流里加一个"事后审查节点"比实时学习便宜得多。
- **两级披露**：Memoria 的 RAG 检索已是"索引→取回"两级，wiki 层面可复用：系统提示只放 wiki 页标题+一句话描述（≤60 字符），正文按需检索——这正是现有 RAG 形态，Hermes 证明了它对"技能库"同样成立。
- **read-before-write 与只归档不删**：Memoria 红线"删文档必须删掉它的全部向量"与 Hermes "never delete, only archive" 互补——自动维护对 wiki 页只做 stale 标记与归档，物理删除必须人工确认并同步删向量。
- **三库互斥写入**：Memoria 若引入记忆，务必像 USER.md/MEMORY.md/skill 那样先定义"一个事实只进一个库"的路由规则，否则重复写入会把两个库都撑爆。
- **description 长度硬约束 + 创建时回显**：对 wiki 页摘要同样适用。

不适合搬：

- **skill 目录栈/四级优先级/斜杠命令投影**：Memoria 无 skill 体系，wiki 是单一受控语料，不需要 shadowing 解析。
- **background_review 的缓存平价 fork**：Memoria 用 LangGraph 单人问答，无长会话 prefix cache 压力；审查做成图内节点即可，不值得复制 fork 隔离机制。
- **hub 商店/quarantine/整套装**：单机单人系统无第三方技能供应链。
- **轨迹导出训练闭环**：无自研模型训练需求，属 Nous 侧基础设施。

## 12. 证据索引

| 结论 | 文件 |
|---|---|
| skill=程序性记忆；目录布局 | `tools/skill_manager_tool.py:1-6` |
| frontmatter 解析/支持目录/60字符截断 | `agent/skill_utils.py:29-31、66-86、822-839` |
| 两级披露（索引行 + skill_view(file_path)） | `agent/prompt_builder.py:1466-1487`、`tools/skills_tool.py:2、640` |
| 创建/patch/守卫/扫描回滚 | `tools/skill_manager_tool.py:396-496、516-557` |
| 读前写守卫实现 | `tools/skill_manager_guards.py:28-60` |
| 审查触发阈值/默认 10/交付后运行 | `agent/turn_finalizer.py:763-791`、`agent/agent_init.py:1380-1382` |
| fork 构造/缓存平价/持久化隔离 | `agent/background_review.py:912-1041`（~26% 注释 L1000-1005） |
| 审查白名单/拒绝风暴教训 | `agent/background_review.py:1079-1146` |
| 审查 prompt 三变体/路由块/负面清单 | `agent/background_review.py:357-560` |
| 索引四级优先/同名拒绝/项目隔离 | `agent/skill_utils.py:381-487、490-644` |
| index delta note 通道 | `agent/skills_index_delta.py:1-15、87-136` |
| /reload-skills 不动缓存 | `agent/skill_commands.py:661-695` |
| curator 生命周期/整合 opt-in/YAML 块 | `agent/curator.py:1-26、147、545-566` |
| 整合硬规则/24k 正文目标/用量不作为依据 | `agent/curator.py:289-340` |
| dry-run 横幅/审批边界/首跑种子 | `agent/curator.py:161-177、266-288、881-928` |
| 用量遥测/created_by 标记 | `tools/skill_usage.py:1-6` |
| 轨迹导出/压缩器/SWE 跑批 | `agent/trajectory.py:37-58`、`trajectory_compressor.py:1-9`、`mini_swe_runner.py:1-8` |
| 审查产出摘要/成本归还父会话 | `agent/background_review.py:615-626、699-812` |
| provider 路由 pin 继承 | `agent/background_review.py:814-822` |
| hub 目录缓存（勿与运行时索引混淆） | `tools/skills_hub.py:65`、`skills/index-cache/` |
| 斜杠命令展开/缓存断点/预载 | `agent/skill_commands.py:331-381、829-900` |
| 模板变量与内联 shell 信任域 | `agent/skill_preprocessing.py:15-86、99-139、142-156` |
| focus 模式 names-only 降级 | `agent/system_prompt.py:301-314`、`agent/prompt_builder.py:1445-1459` |
