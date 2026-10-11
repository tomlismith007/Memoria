# Hermes Agent 核心设计 · 06 人格设计

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时，MIT，Python 3.14 + Node
> HEAD：`97a9ae8e`（main，2026-10-11 本地浅克隆）；路径相对仓库根目录，`文件:行` 均为实际读到的行号
> 本篇聚焦人格：SOUL.md 身份文件本体、system prompt 三层装配管线中人格各层的位置、/personality 运行时切换、人格与记忆/技能的边界
> 约定：结论只来自源码；未定位到的机制明确标注"未定位到"

---

## 1. 定位与全景

Hermes 的人格不是一个文件而是一套**分层槽位**，每层回答不同的问题、住在不同的地方、有不同的信任级别与修改通道：

| 层 | 回答的问题 | 住处 | 进 prompt 的位置 |
|---|---|---|---|
| SOUL.md | "你是谁、怎么说话" | `~/.hermes/SOUL.md`（每 profile 一份） | stable 层 identity 槽（`agent/system_prompt.py:544-550`） |
| 默认身份 | （无 SOUL.md 时的兜底） | 硬编码 `DEFAULT_AGENT_IDENTITY`（`agent/prompt_builder.py:159-168`） | 同上，fallback |
| personality 覆盖层 | "换一种语气/人设" | config.yaml `display.personality`（名字）或 `agent.system_prompt`（手写覆盖） | context 层 ephemeral 段，**每次 API 调用时注入、不缓存**（`agent/turn_context.py:1340-1341`） |
| USER.md | "用户是谁" | `~/.hermes/memories/USER.md` | volatile 层 memory 块（`agent/system_prompt.py:516-541`） |
| 项目上下文 | "这个项目怎么干活" | `.hermes.md`/`AGENTS.md`/`CLAUDE.md`/`.cursorrules` | context 层（`agent/prompt_builder.py:1857-1883`） |

装配总原则写在 system prompt 模块 docstring：prompt 按 stable/context/volatile 三层用 `\n\n` 连接，**一次构建终身复用**（只有上下文压缩触发重建），"so the upstream prefix cache stays warm"（`agent/system_prompt.py:1-9`）。人格工程的一切设计都围绕这个约束展开：身份层必须逐字节稳定，可变的人格走缓存之外的旁路。

```
build_system_prompt(agent, system_message)          # agent/system_prompt.py:800-809
├─ stable   ① identity: SOUL.md 或 DEFAULT_AGENT_IDENTITY
│           ② help guidance（占位→按 skills 索引回填两种变体）
│           ③ 行为纪律块（config 可关）+ 工具感知 guidance + 模型门控纪律
│           ④ skills.auto_load 预载块 + coding posture 前缀
├─ context  ⑤ system_message（ephemeral，API 时另注入）    # L770-772
│           ⑥ 项目上下文（四类文件先到先得一种）           # L773
│           ⑦ worktree 快照 + 环境探针/bot 协议/平台提示    # L774-779
└─ volatile ⑧ <available_skills> 索引                     # L780-783
            ⑨ MEMORY.md/USER.md 冻结块 + 外部记忆 provider 块
            ⑩ 冻结 plugin sections + profile 行 + 时间行
→ "\n\n".join(stable, context, volatile)，缓存 agent._cached_system_prompt
```

## 2. SOUL.md 本体：逐段拆解

仓库根的 `SOUL.md` 只有 667 字节、一个无换行结尾的段落，内容与 `DEFAULT_AGENT_IDENTITY` **逐字相同**——出厂即把默认身份同时发布成可编辑文件（对比 `SOUL.md:1` 与 `agent/prompt_builder.py:161-168`）。逐句拆解其写法：

1. **身份声明**："You are Hermes Agent, built by Nous Research."——一句定名，无背景故事、无公司叙事。
2. **长度配比律（sizing rule）**："match the length of your reply to the weight of the ask — a one-line question gets a one-line answer, and finished work gets a short report of what changed, what's verified, and what's left, never a replay of the process."——回复长度是问题重量的函数；完工汇报的三要素（改了什么/验证了什么/剩什么）。
3. **具名禁令**：No filler（"Great question," "I'd be happy to"）、不复述请求、不重总结自己说过的话、不旁白用户看得见的工具调用——每条都是可判定的行为，不是"要简洁"这类形容词。
4. **诚实与独立判断**："Plain claims over adjectives; when unsure, say so plainly. Agree because it's right, not because the user said it."
5. **深度购票制（earned-depth escape hatch）**："Depth is earned — give it when the user asks for detail, teaches, or the stakes demand it, not by default."

同样值得注意的是 SOUL.md **刻意不写的东西**：没有能力清单（"我会浏览网页/能跑终端"）、没有工具列表、没有输出格式模板。能力声明由 `HERMES_AGENT_HELP_GUIDANCE` 承担且只指向外部文档权威（"the documentation ... is your authoritative reference"，`agent/prompt_builder.py:170-178`）；"会做什么"住在技能索引里（03 篇 §2.2）。身份文件只管语气与判断方式，能力与流程是另外两套可独立演进的机制。

文件形态上 SOUL.md 也是"最素"的：纯散文、无 frontmatter、无章节标题——对比每个 SKILL.md 都有 YAML 头和版本号，身份不需要被机器解析，它只需要被模型读到。装载管线对它做的仅有：剥历史遗留的 Bot Mode 段、注入扫描、按上下文窗口截断（`agent/prompt_builder.py:1669-1699`）。

源码注释把这层设计哲学说明白了：**"A behavior spec (sizing rule, named prohibitions, earned-depth escape hatch), not a trait list — trait lists change nothing."**（`agent/prompt_builder.py:160-161`）——特质清单改变不了行为，只有可判定的行为规范才行。同一注释还有条维护者军规："models UNDER-explore by default; never re-add an exploration-thrift line"。

## 3. System prompt 装配管线：人格各层在哪个槽位

### 3.1 stable 层（身份与纪律，逐字节稳定）

`build_system_prompt_parts`（`agent/system_prompt.py:734-797`）的 stable 段顺序：

1. **identity 槽**：`_identity_parts` 优先读 SOUL.md（`load_soul_md`，经 `_pb` 传入 profile home）；读到就用它，读不到落 `DEFAULT_AGENT_IDENTITY`（`agent/system_prompt.py:544-550`）。SOUL.md 属于 stable 层——它是"这个 profile 的恒常身份"，改文件要等下次重建才生效。
2. **help guidance 槽**（占位后回填）：先放 `HERMES_AGENT_HELP_GUIDANCE_NO_SKILLS`，若 skills 工具在且索引里渲染出了 `hermes-agent` 行，替换成带 `skill_view(name='hermes-agent')` 指针的版本——"the variant is chosen after the skills index is built; this slot holds its position"（`agent/system_prompt.py:746-757`）。这段话本身是**能力声明**："the documentation ... is your authoritative reference"、"so you don't guess or invent workarounds"（`agent/prompt_builder.py:170-178`）。
3. 行为纪律块（task completion / parallel tool call，config 键可关）、工具感知 guidance（memory/skills/kanban 各自只在工具装载时注入，`agent/system_prompt.py:274-298`）、模型门控的 tool-use 执行纪律（`_model_gate` 支持 true/false/模型子串列表，L41-52）。
4. `skills.auto_load` 的预载技能块（resolved once per agent lifecycle，`agent/system_prompt.py:317-341`）与 coding posture 前缀。
5. **自我位置认知**：volatile 层还有一段 `_active_profile_line`，告诉模型当前 profile 的名字、自己读写哪个 home、其他 profile 的 skills/plugins/cron/memories 在哪——并明确"Do NOT modify another profile's skills/plugins/cron/memories unless the user explicitly directs you to"（`agent/system_prompt.py:373-410`）。这段放在 volatile 层是因为它内嵌 home 路径——"the stable prefix then stays byte-identical across every profile (and home) on the host"（L786-789）。身份不仅包括"我是谁"，还包括"我住在哪个数据目录里"。

### 3.2 context 层（项目与可变人格）

- **ephemeral system prompt（人格覆盖层）**：调用方传入的 `system_message` 是 context 层第一段（`agent/system_prompt.py:770-772`）。但实际注入走的是另一条路：`agent.ephemeral_system_prompt` 在**每次 API 请求时**追加到 effective system 之后——"`ephemeral_system_prompt`) is added at API time only — messages stays untouched"（`agent/turn_context.py:1247、1340-1341`）。这是 /personality 能"下轮生效"又不污染缓存前缀的机制基础。
- **项目上下文文件**：`build_context_files_prompt` 只装**一种**项目上下文，先到先得：`.hermes.md`/`HERMES.md`（走到 git root）→ `AGENTS.md` 目录链（git root 向下逐目录合并，`AGENTS.override.md` 优先于 `AGENTS.md`，重复内容去重）→ `CLAUDE.md`（仅 cwd）→ `.cursorrules`+`.cursor/rules/*.mdc`（仅 cwd），输出统一包上 "# Project Context ... should be followed" 头（`agent/prompt_builder.py:1857-1883`、`agent/prompt_builder.py:1806-1832`）。SOUL.md 独立于这条竞争链——已作为 identity 槽加载时传 `skip_soul=True` 防止注入两次（L1868-1878、`agent/system_prompt.py:713-726`）。
- **注入扫描的信任分级**（`agent/prompt_builder.py:83-110`）：项目带进来的 AGENTS.md/.cursorrules 命中注入模式直接 **BLOCK**（内容换成 `[BLOCKED: ...]` 占位）；用户自己 HERMES_HOME 里的 SOUL.md 命中只 **WARN 并照常加载**——"SOUL.md sits in the same trust class as config.yaml"，用户在安全指南里写"ignore previous instructions"这种例子不该毁掉整个身份文件（#112570）；`hermes profile install <git-url>` 装进来的第三方 SOUL.md 则 fail-closed 照 BLOCK（由 distribution manifest 判定归属，`agent/prompt_builder.py:1683-1694`）。

### 3.3 volatile 层（最易变，垫底保前缀）

顺序（`agent/system_prompt.py:780-797`）：skills 索引 → memory 块（`_memory_parts`：MEMORY.md 块头 "MEMORY (your personal notes)"、USER.md 块头 "USER PROFILE (who the user is)"，`tools/memory_tool_store.py:24-27、548-557`）→ 冻结的 plugin sections（恢复进程可从持久化 prompt 里按帧解析回来，`agent/system_prompt.py:138-167`）→ profile 行 → 时间行。两个值得注意的稳定化工程：

- memory 进 prompt 的是**装载时冻结快照**："Frozen load-time snapshot (NOT live state — mid-session writes don't touch it, preserving the prefix cache)"（`tools/memory_tool_store.py:524-527`）。
- 时间行只有日期、时区当天恒定；跨天会话在压缩重建时补一行 "Today's date (as of the last context rebuild)"——"the cache prefix is already invalidated at that boundary"（`agent/system_prompt.py:489-513`）；Bot Mode 永驻会话干脆去掉日期（"a birth date pinned in a months-long session is misinformation"，`agent/system_prompt.py:344-365`）。

### 3.4 装配的字节稳定性工程（人格为何能"稳定如一"）

身份要稳定，前提是它所在的 prompt 前缀在会话期逐字节不变。围绕装配有一组专门的冻结机制：

- **workspace 快照钉扎**：coding posture 的工作区探测结果按 cwd 键存在 agent 上（`_frozen_workspace_snapshot`），重建时重放而非重新探测——"re-probing at the compaction rebuild re-emits different bytes for any repo that moved and defeats the keep-prompt fast path"；恢复的 agent 从持久化 prompt 里解析出旧快照来播种（`agent/system_prompt.py:664-693`）。
- **plugin sections 冻结**：每次会话只渲染一次并冻结；重建边界渲染失败则回退上一次的字节（"fail-open guard, not a freeze"），恢复路径直接从持久化 prompt 按帧解析（`agent/system_prompt.py:113-135、138-167`）。
- **会话起始时间的血统追溯**：`Conversation started:` 取血统根 session id 里内嵌的铸造时间——压缩会轮转 session id、每个新 id 带自己的时间戳，不回溯血统根会让"永驻会话"在数月后悄悄改姓出生日期（`agent/system_prompt.py:176-222`）。
- **可观测性配套**：`context_file_sources.py` 对每次装配给出逐文件清单（loaded/truncated/shadowed/blocked/flagged/empty/unreadable/suppressed 八态 + token 估算），"one discovery walk, so the listing cannot drift from the prompt"（`agent/context_file_sources.py:1-13、25-34`）——人格层不是黑盒，`/context` 能看到每个槽位载入了什么、为什么没载入。

## 4. AGENTS.md 与 SOUL.md 的分工

仓库自带的 `AGENTS.md`（`AGENTS.md:1-12`）是给"开发这个 repo 的 AI 助手与人类贡献者"看的开发指南：自我声明为 hub + 路由表（各目录的 AGENTS.md 在进入该目录时自动加载），受 `python scripts/check` 的 12k 字符上限约束（"so it loads whole on 128k+ models: long form goes in the guide"）。它的第一条非技术信条是 **"Never give up on the right solution."**（`AGENTS.md:6`）——连贡献规范都以行为准则开场，与 SOUL.md 的写作法一脉相承。它规定的是**在这个代码库里怎么干活**（"Per-conversation prompt caching is sacred"、"The core is a narrow waist; capability lives at the edges"，`AGENTS.md:20-22`），经 §3.2 的项目上下文链进入 prompt——与"你是谁"无关。

值得注意的是分工的**反向约束**：AGENTS.md 里也不写人格。这份文件通篇是工程纪律与贡献 rubric（`AGENTS.md:26-40`），出现的"行为准则"都作用于开发场景。若 Hermes 的贡献者把自己的沟通偏好写进 repo AGENTS.md，它只会作用于"在这个仓库里工作的会话"——而用户的 SOUL.md 在所有会话恒常。两个文件的可见范围（project cwd vs profile home）就是分工的物理边界。

分工总结：**SOUL.md 是跨会话恒常的自我（profile 级，用户可编辑，信任级别等同 config.yaml）；AGENTS.md 是项目级的工作规范（随 checkout 走，低信任，扫描可拦）；USER.md 是对用户的认知（模型经 memory 工具维护）；personality 是风格覆盖（config 持久化的名字，env/config 双入口）**。四者进 prompt 的层、信任级别、修改通道全部不同——"什么信息住在哪"被当成架构决策而非习惯。

## 5. 人格的运行时可变性：/personality

### 5.1 状态模型（hermes_cli/personality.py，单文件单属主）

- 三个 config 键职责分明：`display.personality` 存**选中的名字**（空 = 无覆盖）；`agent.system_prompt` 是**用户手写的自由覆盖**，"personality code never writes it"（`hermes_cli/personality.py:1-8`）；`agent.personalities`（及顶层 `personalities:` 遗留块）存用户自定义/覆盖内建的人设，按名叠加（L94-105）。
- **14 个内建人设**是单句 prompt：helpful / concise / technical / creative / teacher 之外还有 kawaii、catgirl、pirate、shakespeare、surfer、noir、uwu、philosopher、hype（`hermes_cli/personality.py:19-34`）——每个都是一段风格指令，如 noir 是整段第一人称侦探小说腔。
- 结构化定义也支持：dict 形态可带 `system_prompt`/`tone`/`style`/`description` 字段，渲染时拼成 prompt 文本（L49-62）。
- 空值拼法宽容：`NEUTRAL_PERSONALITY_NAMES = {"", "none", "default", "neutral"}` 都表示"无覆盖"（L16-17）；未知名直接抛错并列出全部可用人设（L107-113）——不静默回退到默认人设。
- 解析优先级：`resolve_ephemeral_system_prompt` 先看 `display.personality` 是否指到已知人设，否则退 `agent.system_prompt`（L125-130）；env `HERMES_EPHEMERAL_SYSTEM_PROMPT` 又在两者之前（`gateway/run_config_loaders.py:93-97`）。
- **唯一合法写路径**：`persist_personality` 用原子 round-trip YAML 更新把名字写进 `config.yaml` 的 `display.personality`（保留注释与顺序），chmod 600，绝不碰 `agent.system_prompt`（`hermes_cli/personality.py:133-146`）。

### 5.2 生效时序

- **gateway**：`/personality` 处理器列出/切换人设（`gateway/slash_commands_model.py:621-644`）：无参数时列出全部人设，当前选中项打标记、第一项固定为 none 选项；每轮解析 ephemeral prompt 时都**重读当前 profile 的 config**——"routed multiplex profiles get their own display.personality / agent.system_prompt instead of a boot-time snapshot... /personality edits take effect on the next turn"（`gateway/run_config_loaders.py:130-141`）。channel/thread 级 `channel_overrides.system_prompt` 优先于全局（L132-137）。
- **CLI/TUI**：改系统提示状态的 slash 命令**默认推迟到下个会话**，opt-in `--now`——这是仓库级军规（"Slash commands that change system-prompt state defer to the next session, with an opt-in --now"，`AGENTS.md:20-23`）。
- **codex 通道**：/personality 就地改 agent 后，live 的 CodexAppServerSession 因 prompt 组成变化被退役，"the new thread carries the current one"（`agent/codex_runtime.py:599-604`）；对 codex 本体则传 `personality: "none"` 剥掉它的身份——"Hermes supplies the agent identity through its own system prompt"（`agent/transports/codex_app_server_session.py:272-274`）——**人格唯一来源原则**：不允许下层运行时再叠一层自己的身份。

## 6. 人格与记忆/技能的边界

边界由 background_review 的路由块立法（`agent/background_review.py:361-371`）：

- **USER.md**："who the user is — persona, preferences, communication and work style, personal details they revealed, and expectations about how you should behave."——注意"expectations about how you should behave"归用户画像：那是**用户对 agent 的要求**，不是 agent 的性格。
- **MEMORY.md**："facts about the ENVIRONMENT you operate in — tool quirks, project conventions, config gotchas, paths and endpoints."——环境事实，与人格无关。
- **skill**："how to do this class of task for this user"——程序性知识。风格抱怨的处理规则："when the user expressed a style/format/workflow preference, the update belongs in the SKILL.md body, not just in memory"（L498-503）；combined prompt 更进一步："A user-preference lesson lives in exactly ONE place: the skill that governs the task when one exists, USER.md only for cross-cutting preferences no skill owns — never both"（L549-554）。
- **SOUL.md / personality**：不在任何自动写通道里。skill_manage/file 工具对 SOUL.md 这类"protected instruction files"有写守卫（`tools/file_tools_write_guards.py:179-190` 列出 agents.md/claude.md/soul.md/.cursorrules；skills_guard 对改 `.hermes/SOUL.md` 的技能内容直接判 dangerous，`tools/skills_guard.py:471`）。**性格只能由人改**：自动审查连 USER.md 都只按路由写，SOUL.md 完全在模型的可写面之外。

USER.md/MEMORY.md 本身的工程细节也服务这个边界（`tools/memory_tool_store.py`）：

- 文件格式极简：条目以 `\n§\n` 分隔（ENTRY_DELIMITER，L21），预算按**字符数**而非 token（"model-independent"，L1-4）；进 prompt 时渲染成块头 + 使用率百分比 + 条目（`_render_block`，L548-557）——模型随时能看到"画像还剩多少空间"。
- memory 内容也过注入扫描，且用 strict scope："memory enters the system prompt, so a poisoned entry persists across sessions"（L28-31）。
- 写成功的响应**刻意不回显条目列表**："echoing entries invites the model to 'find more to fix' and re-issue the same ops"，并附固定尾注 "Write saved. This update is complete — do not repeat it."（L529-538）——人格维护的循环终止是设计出来的，不是模型自觉。

由此形成清晰的四分法：**性格（SOUL/personality，人写）→ 用户画像（USER.md，模型按路由写）→ 环境事实（MEMORY.md，同上）→ 做事方法（skill，模型自主改进，见 03 篇）**。delegate 子代理继承工作区上下文但显式跳过 SOUL.md——"identity belongs to the parent"（`tools/delegate_tool_progress.py:199-206`）：人格不随委派复制。

## 7. 设计决策取舍

1. **行为规范而非人设故事**：默认身份全文没有一个形容词性格词，全是可判定规则（§2）；源码注释明说"trait lists change nothing"。
2. **人格层级 = 缓存层级**：恒常身份进 stable（换人设=换 prompt=新会话/重建才生效），风格覆盖走 API 时旁路（下轮生效、零缓存代价）——可变性与缓存开销被显式定价。
3. **人格单一来源**：codex 的 `personality: "none"` 表明 Hermes 拒绝身份叠加——所有身份表述必须出自自己装配的 prompt，防两层人设打架。
4. **信任分级进 prompt**：同一个 SOUL.md，用户自己写的命中注入模式照载，git 装进来的就拦——文件内容可信度由**所有权**决定，不由文件名决定。
5. **人格不在自动改进面上**：自改进闭环（03 篇）覆盖 skill/memory，唯独绕开 SOUL.md；性格漂移只能来自人的编辑。
6. **记忆条目极简 + 用量自报**：`\n§\n` 分隔的条目 + 字符预算 + prompt 里渲染"剩余空间百分比"——人格相关的写入（USER/MEMORY）被设计成有限资源下的策展，不是无限日志（`tools/memory_tool_store.py:1-31、548-557`）。
7. **人格装配全程可观测**：八态逐文件清单让"模型为什么这样说话"可审计到具体文件（`agent/context_file_sources.py:25-34`）——人格调试不靠猜。

## 8. 设计规范清单（可直接照抄）

1. 身份文件一篇、一段、无换行结尾亦可；只写可判定行为（长度律/具名禁令/购票制），不写特质形容词。
2. 默认身份同时以"硬编码常量 + 仓库根 SOUL.md"双形态发布，兜底与可编辑两全。
3. 身份读不到就 fallback，不空转；identity 槽永远有内容。
4. 人格覆盖层走 API 时注入的 ephemeral 段，不进缓存前缀；持久化只存"名字"，prompt 文本由代码从注册表解析。
5. 人设注册表 = 内建 dict + 用户 config 按名覆盖 + 手写 `agent.system_prompt` 兜底；写路径唯一（原子 YAML round-trip）。
6. 项目上下文四类文件先到先得只装一种；AGENTS.override.md 优先；SOUL.md 独立于该链且防双重注入。
7. 注入扫描按所有权分级：用户自有身份文件 WARN+载入，随 checkout 来的 BLOCK，第三方 distribution fail-closed BLOCK。
8. 记忆进 prompt 用装载时冻结快照；跨天会话只在压缩重建边界补日期行。
9. 下层 agent 运行时（codex 等）一律剥掉自带身份，人格只从一个 system prompt 出。
10. 自动学习路由表写死"一个事实只进一个库"；人格文件不在任何自动写通道内。
11. 子代理/委派路径跳过身份文件——人格属于主会话，不随任务复制。
12. 身份文件保持纯散文（无 frontmatter/版本），机器要解析的是技能索引，不是人格。

## 9. 知识点表

| 做法 | 解决的问题 |
|---|---|
| 行为规范式身份（sizing rule + 具名禁令） | 特质形容词式人设对模型行为无约束力 |
| SOUL.md == DEFAULT_AGENT_IDENTITY 双形态 | 出厂人格可被用户覆盖，无文件时仍有兜底 |
| ephemeral prompt API 时注入 | /personality 下轮生效且不动缓存前缀 |
| display.personality 只存名字 | 人设文本改了立即跟随，config 不存副本 |
| persist_personality 唯一写路径 | 多入口写 config.yaml 造成注释丢失/竞态 |
| 项目上下文"只装一种" | 多套指令文件同时进 prompt 互相打架 |
| AGENTS.override.md | 个人本地修改不污染 git 跟踪的项目指令 |
| 注入扫描按所有权分级 | 用户安全指南里的示例措辞误伤自己的身份文件 |
| memory 冻结快照 | 会话中途写记忆破坏前缀缓存 |
| codex personality:"none" | 双层身份（codex 自带 + Hermes 注入）打架 |
| delegate 跳过 SOUL.md | 子代理不该复制父 agent 的人格 |
| Bot Mode 去日期行 | 永驻会话里被钉死的出生日期变成错误信息 |
| profile 行告知自己住在哪个 home | 模型把默认 profile 与当前 profile 的数据混写 |
| 未名人设显式报错并列出全表 | 拼错人设名静默落回默认，用户以为切换成功 |
| 写成功不回显条目 + 固定尾注 | 模型循环"再修一遍"刚写好的记忆 |
| entry 分隔符 + 字符预算 + 用量百分比 | 记忆膨胀无感知，直到挤掉重要条目 |
| hermes-agent skill 永不可禁用（ESSENTIAL） | 系统 prompt 指向的操作手册不会因配置失误消失 |

## 10. 对 Memoria 的可迁移结论

适合搬：

- **行为规范式身份写作**：Memoria 的 `schema.md`（wiki 写作规范）可以直接套用 SOUL.md 的句法——长度律、具名禁令、"深度购票制"。规范里每条都该是可判定动作，删掉所有"应当友好/专业"式形容词。当前 Memoria 的 schema.md 若是特质清单风格，这是最便宜的一处升级。
- **分层槽位 + 各层一个修改通道**：Memoria 有 AGENTS.md（harness）与 wiki（知识库），正好对应 Hermes 的"项目规范 / 恒常知识"分层；把"什么信息允许进哪一层、由谁修改"写成一张表（类似本文 §1），能预防 wiki 页里混入系统指令、AGENTS.md 里混入领域知识的互相污染。
- **"一个事实只进一个库"路由**：Memoria 的 wiki 与 RAG 检索语料将来若加用户偏好/会话记忆，先写路由规则再写存储——Hermes 的 #30220（同一课写进两个库直到双双爆仓）是现成前车之鉴。
- **写成功不回显 + 固定终止尾注**：Memoria 的 LangGraph wiki 维护节点若让 LLM 增改 wiki 页，工具响应应只报"已写入"而不回显全文，并明示"本次更新已完成"——防止模型在同一轮里反复重写刚改过的页。
- **人格文件排除在自动写通道外**：Memoria 的红线是"归档必须人工确认"；同理，任何自动整理流程（含未来的 LLM wiki 维护节点）应显式排除 schema.md/AGENTS.md 这类规范文件，只允许它们被人工编辑。
- **注入扫描按所有权分级**：Memoria 的 RAG 语料若接受外部导入（邮件、网页），对导入内容命中注入模式应 BLOCK，对用户自写文档 WARN——同一把扫描器、两套信任级别。
- **装配可观测清单**：Memoria 的 prompt 由多个 LangGraph 节点拼装（system/检索片段/wiki 摘要/历史），可照八态清单做一个"本轮 prompt 各来源载入了什么、为何截断"的诊断输出——回答带来源引用的红线之外，prompt 本身也可溯源。

不适合搬：

- **14 个内建人设与 /personality 切换**：Memoria 是单人知识系统，无多人设需求；一个 schema.md 即可。
- **三 tier 缓存装配工程**：Memoria 用 LangGraph，prompt 每次由图节点组装，没有跨轮 prefix cache 需要保护；冻结快照/时间行字节稳定等工程不适用。
- **profile 体系**：单实例系统无需 per-profile SOUL.md 隔离。
- **codex 通道的身份剥离**：Memoria 无嵌套第三方 agent 运行时。

## 11. 证据索引

| 结论 | 文件 |
|---|---|
| SOUL.md 本体（667 字节单段） | `SOUL.md:1`（整文件） |
| DEFAULT_AGENT_IDENTITY 及设计注释 | `agent/prompt_builder.py:159-168` |
| 三层装配总述/identity 槽/槽位回填 | `agent/system_prompt.py:1-9、544-550、746-757` |
| ephemeral prompt API 时注入 | `agent/turn_context.py:1247、1340-1341` |
| 项目上下文四类文件先到先得/AGENTS 链 | `agent/prompt_builder.py:1788-1883` |
| 注入扫描所有权分级 | `agent/prompt_builder.py:83-110`、`agent/prompt_builder.py:1683-1694` |
| SOUL.md 装载/分布归属/防双注入 | `agent/prompt_builder.py:1653-1699`、`agent/system_prompt.py:713-726` |
| memory 冻结快照/块头 | `tools/memory_tool_store.py:24-27、524-527、548-557` |
| 时间行字节稳定/Bot Mode 去日期 | `agent/system_prompt.py:344-365、489-513` |
| /personality 状态模型/内建人设/唯一写路径 | `hermes_cli/personality.py:1-8、19-34、125-146` |
| gateway 下轮生效/channel 覆盖 | `gateway/run_config_loaders.py:93-141`、`gateway/slash_commands_model.py:621-644` |
| codex 身份剥离/会话退役 | `agent/codex_runtime.py:599-604`、`agent/transports/codex_app_server_session.py:272-274` |
| USER/MEMORY/skill 边界路由 | `agent/background_review.py:361-371、498-503、549-554` |
| 记忆条目格式/写成功不回显 | `tools/memory_tool_store.py:21、28-31、529-538` |
| profile 自我位置认知行 | `agent/system_prompt.py:373-410、786-789` |
| /personality 列表 UI/未知名报错 | `hermes_cli/personality.py:16-17、107-113`、`gateway/slash_commands_model.py:621-644` |
| SOUL.md 写守卫/技能禁改 | `tools/file_tools_write_guards.py:179-190`、`tools/skills_guard.py:471` |
| delegate 不继承人格 | `tools/delegate_tool_progress.py:199-206` |
| 仓库 AGENTS.md 分工与 slash 军规 | `AGENTS.md:1-12、20-23、26-40` |
| SOUL.md 无 frontmatter/装载管线动作 | `agent/prompt_builder.py:1669-1699` |
