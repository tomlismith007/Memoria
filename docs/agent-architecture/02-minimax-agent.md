# MiniMax Mini-Agent 架构设计研究（MiniMax-AI/Mini-Agent）

> 研究对象：`MiniMax-AI/Mini-Agent` — "A minimal yet professional single agent demo project"，约 3k star
> 技术栈：Python（pydantic + httpx + tiktoken + anthropic/openai SDK + mcp + agent-client-protocol），核心代码约 1000 行
> 定位：展示 agent 的**核心执行流水线**与生产化升级方向——是六个研究对象中最小的一个，价值在于"最小可用骨架长什么样"
> 路径相对仓库根目录；核心逻辑集中在 `mini_agent/agent.py`（523 行）。

---

## 1. 项目概览

- 主包 `mini_agent/`：`agent.py`（循环）、`llm/`（`base.py` 抽象 + `anthropic_client.py` + `openai_client.py` + `llm_wrapper.py`）、`tools/`（`base.py` + bash/file/note/skill/mcp 六类工具）、`schema/schema.py`（Message）、`config.py`、`retry.py`、`logger.py`、`acp/`（Agent Client Protocol 服务器，供编辑器接入）、`cli.py`。
- `skills/` 内置一组 Claude Skills 格式的技能（`agent_skills_spec.md` 为规范）：`document-skills`（docx/pptx/pdf 的 OOXML 脚本族）、`mcp-builder`、`skill-creator`、`webapp-testing` 等——仓库行数大头在此（21k 行中核心逻辑仅约 1/20）。
- 双 LLM 后端（Anthropic + OpenAI）同一 `LLMClient` 抽象；工具 schema 双格式（`to_schema()` Anthropic / `to_openai_schema()` OpenAI）。

## 2. 整体架构

```
cli.py ──> Agent（agent.py：循环 + 上下文 + 摘要）
             ├─ LLMClient（llm/：Anthropic | OpenAI，统一 Message/usage）
             ├─ tools/{bash, file, note, skill, mcp}
             ├─ retry.py（指数退避）
             └─ logger.py（每次 run 一个日志文件，记录请求/响应/工具结果）
acp/server.py ── Agent Client Protocol（编辑器侧驱动同一 Agent）
```

- 没有框架依赖：不用 LangChain/LangGraph，纯 asyncio 手写循环——"minimal"的立场本身就是设计声明。
- 工作区概念：构造时强制 `workspace_dir.mkdir(parents=True, exist_ok=True)`，并把 `## Current Workspace`（绝对路径 + 相对路径解析规则）**追加进 system prompt**——模型的所有文件操作锚定在一个目录。

## 3. Agent 执行流水线（完整时序）

`agent.py::run()`，`while step < max_steps`（默认 50）：

1. **取消检查**（`cancel_event`，`asyncio.Event`，外部如 ESC 键设置）——命中则 `_cleanup_incomplete_messages()` 后返回"Task cancelled"；
2. **上下文检查**：`await self._summarize_messages()`（见 §4，必要时压缩后再进本步）；
3. **LLM 调用**：`self.llm.generate(messages, tools)`；异常分两类——`RetryExhaustedError`（报重试次数与最后一次异常）与其他；**错误以字符串返回而不是抛出**，循环优雅终止；
4. 累计 API 上报 token（`response.usage.total_tokens` → `self.api_total_tokens`，供下轮压缩判定）；
5. 追加 assistant 消息（含 thinking、tool_calls）；**无 tool_calls → 返回 content（任务完成）**；
6. **逐个串行执行工具**：
   - 未知工具 → 失败 `ToolResult("Unknown tool")`（回灌模型可自行纠正）；
   - 工具抛异常 → 捕获一切异常转成 `ToolResult(success=False, error=类型名+消息+traceback)`——**工具永不把异常漏进循环**；
   - 每个工具后再次检查取消；
7. `step++`；步数耗尽返回 `"Task couldn't be completed after N steps."`。

取消语义（`_check_cancelled` 在步首、工具执行前、每个工具后三处检查）：**只在安全检查点停**；`_cleanup_incomplete_messages()` 删除最后一条未完成的 assistant 消息及其后所有工具结果，保证消息序列仍符合 API 协议（assistant-tool_calls 与 tool 结果成对）。

## 4. 上下文与记忆机制（重点）

### 4.1 token 计量：双通道

`_estimate_tokens()`（`agent.py`）：

- 本地估算：`tiktoken` `cl100k_base` 精确编码；**content（字符串或 block 列表）、thinking、tool_calls 三者都计入**，另加每条消息 4 token 元数据开销；tiktoken 不可用时降级为 `字符数 / 2.5` 粗估（`_estimate_tokens_fallback`）；
- API 实测：每次响应后更新 `self.api_total_tokens`。

默认 `token_limit = 80000`，注释明确"Summary triggered when tokens exceed this value"。

### 4.2 摘要策略：按"用户意图"切分（重点）

`_summarize_messages()` 的策略（docstring 原文）：

- **保留全部 user 消息**（用户意图不可丢）；只压缩每个 user→user 区间内的 agent 执行过程；
- 结果结构：`system → user1 → summary1 → user2 → summary2 → …`（最后一轮若仍在执行也压缩）；
- 摘要消息以 **user 角色**注入：`"[Assistant Execution Summary]\n\n{summary}"`；
- 触发条件：本地估算 **或** API 上报任一超限；
- `_skip_next_token_check`：压缩完成后跳过下一次检查（等 API 报告真实 token，避免连续触发）——与 ZCode 的 `willRetriggerNextTurn` 同题不同解。

`_create_summary()` 每轮单独一次 LLM 调用，prompt 四条硬要求：聚焦完成的任务与调用的工具 / 保留关键执行结果 / 1000 词以内英文 / **不包含用户相关内容**。失败降级：返回纯文本轮次概要（assistant 消息 + 工具名 + 结果预览）——**摘要失败不阻断主流程**。

## 5. 缓存设计

- **无 prompt cache 主动控制、无响应缓存、无工具结果缓存**（源码未找到相关机制——诚实记录）；
- 但**计量侧感知缓存**：`llm/anthropic_client.py` 明确合并 `cache_read_input_tokens` 与 `cache_creation_input_tokens` 进总 input token（L235-244），保证压缩判定不被缓存计费口径误导；
- 会话恢复：`logger.py` 每次运行独立日志文件（请求/响应/工具结果全量落盘），可事后审计，但无运行中恢复机制。

## 6. 工具调用机制

`tools/base.py`：

- `Tool` 基类四要素：`name / description / parameters（JSON Schema）/ async execute`；两个投影方法 `to_schema()`（Anthropic：`name/description/input_schema`）与 `to_openai_schema()`（`type:"function"` 包裹）——**同一工具双协议出口**；
- `ToolResult{success, content, error}`（pydantic）统一结果契约；
- 展示与回灌分离：工具参数展示截断 200 字符/值、结果展示截断 300 字符，但**完整内容进消息历史**——UI 不撒谎也不丢信息；
- 内置工具：`bash_tool`（shell）、`file_tools`（读/写/编辑）、`note_tool`（JSON 文件存储的笔记，DEVELOPMENT_GUIDE 给了 PostgreSQL/向量库扩展示例）、`skill_tool` + `skill_loader`、`mcp_loader`。

### MCP 集成（`tools/mcp_loader.py`）

- 四种连接：`stdio / sse / http / streamable_http`；
- **独立超时三件套** `MCPTimeoutConfig`：连接 10s、工具执行 60s、SSE 读 120s（全局可调）——外部工具的每个故障面都有预算；
- `AsyncExitStack` 管理连接生命周期。

### 技能系统（Progressive Disclosure）

- 两级披露：对话 agent 先见技能名清单（便宜），`get_skill` 工具按需加载完整 SKILL.md（"Progressive Disclosure (Level 2)"，`tools/skill_tool.py` 文件头注释）；
- 技能不存在时错误消息**附带可用技能列表**（模型可自纠）。

## 7. 提示词与规则系统

- system prompt 单一字符串 + 自动追加的 workspace 段；无 AGENTS.md 分层加载、无 slash command、无子代理——极简是刻意的；
- 摘要 prompt、摘要 system prompt 内联硬编码（`agent.py`），修改需动代码——这是它"demo"属性的边界，PRODUCTION_GUIDE 也如实指出。

## 8. 生产级能力（按 PRODUCTION_GUIDE 归纳）

- 已实现（demo 级）：重试/退避、日志落盘、token 双通道计量、取消、MCP 超时、ACP 编辑器接入；
- 部署指引：容器化 + **CPU/内存/磁盘限额**（docker-compose 示例）+ **Linux 最小权限账户**（nonroot、受限 workspace 目录、敏感目录访问限制）——把"agent 能摸到什么"当作部署问题而非纯软件问题；
- 明示的升级方向（Guide 原文小节）：高级上下文管理、模型 fallback、幻觉检测与纠错。

## 9. 测试与质量保障

`tests/` 16 个文件，覆盖即设计意图：`test_agent.py`（循环）、`test_bash_tool.py`（shell 安全）、`test_mcp.py`、`test_skill_loader/tool.py`、`test_llm_clients.py`（双后端）、`test_tool_schema.py`（schema 双格式）、`test_session_integration.py`、`test_acp.py`、`test_markdown_links.py`、`test_terminal_utils.py`。

## 10. 设计规范清单（可直接照抄）

1. **工具永不抛异常**：一切异常转 `ToolResult(success=False)`，含 traceback；
2. **未知工具返回可自纠错误**（附可用列表，技能同理）；
3. **取消只在安全检查点**，停机后清理不成对消息，维持 API 协议一致性；
4. **token 计量覆盖 thinking 与 tool_calls**，本地估算与 API 实测双通道；
5. **摘要保用户消息、压执行过程**，摘要失败降级为纯文本概要；
6. **压缩后跳过一次检查**，防止连环触发；
7. **外部工具连接三超时**（连接/执行/流读）分开设；
8. **展示截断、回灌完整**；
9. **错误字符串化返回**，主循环不因单步失败崩溃。

## 11. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| user→user 区间摘要 | 全量摘要丢用户意图；全量保留塞爆窗口 |
| 摘要失败回退纯文本 | 摘要调用本身失败时主任务不中断 |
| 清理不成对消息 | 中断后下次请求因孤立 tool_calls 被拒 |
| 每消息 +4 token 开销估算 | 消息数多时系统性低估 |
| MCP 超时三件套 | SSE 挂起拖死整个 agent |
| 技能两级披露 | 几十个技能的说明挤占每轮上下文 |
| ACP 服务器 | 同一 Agent 内核服务 IDE 与 CLI 两种前端 |

## 12. 对我方项目（LangGraph + RAG）的可迁移结论

适合搬：
- "保留用户消息、摘要执行区间"的压缩切分（与 Memoria 的问答会话结构天然匹配）；
- token 双通道（tiktoken 估算 + API usage 校准）与每消息固定开销；
- `ToolResult` 契约 + 异常全捕获 + 未知工具自纠错误；
- MCP 三超时配置；
- 检查点取消 + 不成对消息清理。

不适合搬：
- 手写循环本身——Memoria 已用 LangGraph，其 checkpointer/中断语义覆盖此处大部分需求；
- 单一 system prompt 字符串（缺少规则分层，ZCode/OpenCode 的分层加载更可扩展）。

## 13. 证据索引

| 结论 | 文件 |
|---|---|
| 循环/取消/清理/工具执行 | `mini_agent/agent.py::run`、`_check_cancelled`、`_cleanup_incomplete_messages` |
| token 估算与降级 | `mini_agent/agent.py::_estimate_tokens`、`_estimate_tokens_fallback` |
| 摘要策略与防连触发 | `mini_agent/agent.py::_summarize_messages`、`_create_summary`、`_skip_next_token_check` |
| 工具契约与双 schema | `mini_agent/tools/base.py` |
| MCP 三超时 | `mini_agent/tools/mcp_loader.py::MCPTimeoutConfig` |
| 技能两级披露 | `mini_agent/tools/skill_tool.py`（文件头注释）、`skill_loader.py` |
| Anthropic 缓存 token 合并 | `mini_agent/llm/anthropic_client.py`（L235-244） |
| 重试参数 | `mini_agent/retry.py::RetryConfig` |
| 部署限额/最小权限 | `docs/PRODUCTION_GUIDE.md`（§3） |
