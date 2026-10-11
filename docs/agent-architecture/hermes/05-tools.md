# Hermes Agent 核心设计 · 05 工具系统

> 研究对象：`NousResearch/hermes-agent` — 自我进化个人 agent 运行时（MIT，Python 3.14 + Node）
> HEAD：`97a9ae8e`（2026-10-11 本地浅克隆）；本文维度：**工具系统**（`tools/` 281 个文件约 10.5 万行）
> 路径相对仓库根目录；每条结论标注 `文件:行号` 实读证据；README 转述一律不进正文。
> 审批机制本身另文研究，本文只描述工具链路上的审批接口点。

---

## 1. 定位与全景

工具系统是四层结构：**自注册工具文件 → 全局注册表 → toolset 选择/可见面投影 → dispatch 管线**。

```
tools/*.py（每个文件 import 时自注册）        tools/registry.py（零依赖单例）
  registry.register(name, toolset,              ToolEntry{schema,handler,check_fn,
    schema, handler, check_fn)  ──import──▶      max_result_size_chars, ...}
                                                        │
model_tools.get_tool_definitions()  ◀──查询──  registry.get_definitions()
  ├─ toolsets.py 选名（core 束 + platform_toolsets）
  ├─ check_fn TTL 过滤（30s 缓存/进程级）
  ├─ 动态 schema rewriter（只提在场工具）
  ├─ schema_sanitizer（llama.cpp 兼容）
  └─ tool_search 渐进披露（超预算折叠成 3 个桥工具）
        │  OpenAI function 数组
        ▼
模型 tool_call ──▶ model_tools.handle_function_call()
  coerce_tool_args → 桥分流 → middleware → pre_hook/审批 guard
  → registry.dispatch(handler) → 结果截断/规范化 → post_hook
        │                          │
        ▼                          ▼
  执行后端                    process_registry.completion_queue
  terminal: environments/     （后台委派/后台进程完成 → 新 turn 回灌）
  browser:  agent-browser daemon + CDPSupervisor
  MCP:      mcp_tool_*（client）/ mcp_serve.py（server）
```

与常见框架不同：**没有工具基类**。一个工具就是一个模块级 `registry.register()` 调用 + 一个返回 JSON 字符串的 handler 函数；注册表同时承担 schema 收集、dispatch、可用性探测（TTL 缓存）与错误包装（`tools/registry.py:1-6, tools/AGENTS.md:9-17`）。

四层各自的职责边界：

1. **工具文件**（`tools/*.py`）：只做一件事——import 时自注册；schema、handler、可用性探测全部在注册时声明。
2. **注册表**（`tools/registry.py`）：进程级单例；写侧（注册/去注册/插件覆盖裁决）与读侧（快照/schema/dispatch）用 RLock + generation 计数隔离，MCP 刷新一边写、模型调用一边读（`tools/registry.py:427-444`）。
3. **可见面投影**（`model_tools.py` + `toolsets.py`）：把"注册表里有什么"变成"这个会话的模型看到什么"——toolset 选择、check_fn 过滤、动态改写、渐进披露。
4. **dispatch 管线**（`model_tools.handle_function_call`）：一次调用的全部横切关注点（coercion、middleware、审批 guard、观测 hook、错误规范化）都在这一条链上，registry.dispatch 只做最后一跳。

## 2. 工具定义与注册

- **schema 格式**：OpenAI function calling 的 dict——`{"name", "description", "parameters": {type/object/properties}}`。注册时立刻校验：schema 非 dict 或 `parameters` 非 object 直接 raise，把 400 挡在启动期而不是请求期（`tools/registry.py:678-686`）。
- **注册入口**：`registry.register(name=, toolset=, schema=, handler=, check_fn=, requires_env=, is_async=, max_result_size_chars=, dynamic_schema_overrides=, override=)`（`tools/registry.py:666-743`）。`check_fn` 是可用性探测（API key、docker 二进制在不在）；`max_result_size_chars` 是每工具结果上限；`dynamic_schema_overrides` 是零参函数，每次取 schema 时浅合并进 schema，用于随运行时配置变化的描述（`tools/registry.py:196-197, 859-869`）。
- **自动发现**：`discover_builtin_tools()` 扫 `tools/*.py` + `tools/<pkg>/tool.py`（包内只扫这一个入口文件，其余都是库），对每个文件做 AST 判定——模块体（含模块级 for 循环）里有 `registry.register(...)` 调用就 import（`tools/registry.py:69-84, 87-93`）。AST 判定结果按 `(mtime_ns, size)` 落盘到 `~/.hermes/cache/tool_discovery_cache.json`，把 ~145ms/百文件 的扫描变成缓存读（`tools/registry.py:96-100, 144-178`）。任何 import 失败只 WARNING 不炸启动（`tools/registry.py:137-140`）。
- **handler 契约**：必须返回 JSON 字符串，唯一例外是"给模型像素"的多模态信封 `{"_multimodal": True, "content": [text, image_url...], "text_summary": str}`；`_normalize_handler_result` 精确接受这两种形状，其余类型一律转成结构化 error 字符串，保证下游日志/预算/持久化拿到的东西永远可切片可计量（`tools/registry.py:876-891`）。
- **错误包装**：`tool_error()` 产出 `{"error": ...}` 且 error body 封顶 2048 字符（日志保留 8192），防止插值出来的原始异常在重试中无限堆高上下文（`tools/registry.py:26-39, 1022-1025`）；dispatch 边界还会二次封顶直接 `json.dumps({"error": str(e)})` 的 handler（`tools/registry.py:42-56`）。
- **注册冲突策略**：跨 toolset 同名 shadow 一律拒绝（含 MCP 对 MCP），除非显式 `override=True`；插件覆盖内建工具还需要运维在 config.yaml 里 opt-in `allow_tool_override`，且插件归属绑死在 handler 定义时的 `__globals__`，lambda 回调也洗不掉（`tools/registry.py:697-730, 588-615`）。同 toolset 重注册（MCP 重连刷新）保持允许；deregister 有对称的所有权检查，插件不能删别人的工具后占空位（`tools/registry.py:745-794`）。
- **toolset 别名**：`register_toolset_alias` 支持一个别名指向 canonical toolset 名（MCP server 名→`mcp-<server>` 即靠它），冲突时 WARNING 覆盖，toolset 最后一个工具被删时别名一并清（`tools/registry.py:526-543, 797-799`）。
- **代表样本**：文件类工具在 `tools/file_tools.py` 一次性注册四个（read_file/write_file/patch/search_files），都带 `check_fn`（惰性导入避免循环依赖，`tools/file_tools.py:1147-1150`）、`max_result_size_chars=100_000`、部分带 `dynamic_schema_overrides`（`tools/file_tools.py:1396-1421`）。注册的完整形态（官方模板，`tools/AGENTS.md:29-39`）：

  ```python
  registry.register(name="example_tool", toolset="example",
      schema={"name": "example_tool", "description": "...", "parameters": {...}},
      handler=lambda args, **kw: example_tool(param=args.get("param", ""),
                                              task_id=kw.get("task_id")),
      check_fn=check_requirements, requires_env=["EXAMPLE_API_KEY"])
  ```

  handler 的位置参数从 `args` dict 取，`task_id`/`session_id` 这类调度上下文从 `**kw` 取——dispatch 时由 `_kwargs_accepted_by` 按 handler 签名过滤注入（`tools/registry.py:1033-1043`）。terminal 的 schema 见 §5；browser 表驱动批量注册见 §6。

## 3. toolset 与模型可见面

- **两层结构**：`toolsets.py` 里有单个 `TOOLSETS` dict（web/browser/terminal/file/…约 28 个键）与 `_HERMES_CORE_TOOLS` 默认束（约 55 个工具名，所有平台基础 toolset 都继承它）；**注册只让 registry 认识工具，被某个 toolset 点名才会暴露**（`tools/AGENTS.md:40-42`；`toolsets.py:11-39, 67`）。
- **开关持久化**：`hermes tools`（curses UI）或 Web 设置页的 toggle 都写 config.yaml 的 `platform_toolsets.<platform>` 列表（`hermes_cli/web_routers/tools.py:281-310`；`hermes_cli/tools_config.py:557-570`：显式保存的列表是对平台原生 default-off 工具集的 opt-in）。运行时 `_get_platform_tools` 读它解析成平台工具集名，遗留别名（`hermes` → `hermes-cli` + `hermes-api-server`）在此展开（`hermes_cli/tools_config.py:554-590`）。
- **可见面合成**：`_select_tool_names` 先并集 enabled、再**永远最后**减 disabled——即使复合 bundle（hermes-cli）重新带上某工具，disabled 也严格剔除（`model_tools.py:315-337`）。`get_tool_definitions()` 在 quiet 模式下按缓存键 memoize（LRU 上限 8），键覆盖 registry generation、config.yaml mtime 签名、profile scope、委派子进程上下文、kanban 上下文——任一变化自动失效（`model_tools.py:205, 214-253, 256-279`）；返回浅拷贝，防止 run_agent 往共享列表 append 导致重复工具名 400（`model_tools.py:229-253`）。
- **check_fn 过滤**：可用性探测 TTL 30s 进程级缓存，key 是 `(fn, profile scope)`；30s 内翻转 `hermes tools` 开关一两个 turn 内生效（`tools/registry.py:223-233`）。两次防抖设计：成功后 60s 宽限窗口内的失败视为抖动，供上次结果 True 且**不缓存**（下轮重探）；核心工具在进程内曾可用而探测现在失败时，一次性 WARNING 指名被丢弃的核心工具（`tools/registry.py:348-384`）。多路复用网关下浏览器控制类请求绕过整个缓存（会话身份三键全在时），防止一个 Browser 会话的活工具漏进另一个（`tools/registry.py:263-291`）。
- **动态 schema rewriter**：`_DYNAMIC_SCHEMA_REWRITERS` 表对 10 个工具的 schema 做投影期改写——`execute_code` 只列出真实可用的 sandbox 工具；`browser_navigate` 只在 `web_search/web_extract` 在场时才在描述里提它们；`delegate_task` 裁掉不在场兄弟工具的禁用行；`browser_exec` 在 terminal 不在场时整个丢弃（防止无终端会话经浏览器工具重获宿主执行）；输入类工具描述动态注入"绝不输入密码/卡号"的 vault 警示。原则：**模型永远听不到不在场工具的名字**（`model_tools.py:349-476, 479-490`；规则出处 `tools/AGENTS.md:45-48`）。这就是"schema 描述不许硬编码引用其他 toolset 工具"这条纪律的执行机制。
- **渐进披露（Tool Search）**：当 deferrable 面（MCP/插件工具）超过上下文窗口预算占比时，把它们从模型可见数组折叠成 `tool_search / tool_describe / tool_call` 三个桥工具；核心工具永不折叠；目录无状态、每次从活跃 tool-defs 重建（`tools/tool_search.py:1-5`；装配点 `model_tools.py:529-541`）。桥调用在 dispatch 入口先分流：`tool_search/tool_describe` 是目录读，`tool_call` 解包成真实工具名**重新走一遍完整 handle_function_call**，让下游所有 hook/审批看到真名（`model_tools.py:703-749, 902-922`）；且解包后还要过会话目录成员校验 + 具体 schema 校验，防止受限会话经桥摸到全注册表（`model_tools.py:736-748`）。桥工具自身用泛型 `arguments: object` schema，因此真实参数校验必须在解包时对被折叠工具的具体 schema 做（`model_tools.py:744-747`）。
- **不同入口看到不同工具面**：是。平台 toolset 之外，GUI 客户端会话由网关按 session 平台折入 `project/desktop_ui/catalog`（`toolsets.py:70-71`）；kanban 派工 worker 强制注入 kanban 工具；委派子进程的上下文参与缓存键（`model_tools.py:322-324, 278`）。最极端的例子是 webhook 入口：外部 webhook 载荷是不可信第三方内容，`hermes-webhook` 平台束只含 web_search/web_extract/vision_analyze/clarify 四个无文件无执行的工具（`toolsets.py:41-42, 234`）。`toolset_distributions.py` 则是另一回事：给批量数据生成按概率采样 toolset 组合的分布表，`+` 复合键一次摇签保住共现保证（`toolset_distributions.py:14-46, 67-93`）。

## 4. 执行链路

主链逐跳（`model_tools.handle_function_call`，`model_tools.py:872-965`）：

```
coerce_tool_args(name, args)            # schema 引导类型修复（见下）
  → _LEGACY_TOOL_ALIASES                # 旧名映射 (model_tools.py:892)
  → _dispatch_bridge_tool               # tool_search/describe/call 分流 (703-749)
  → connector 名校验                    # 会话没开 connectors 直接拒 (924-930)
  → _apply_request_middleware           # tool_request 中间件改参 fail-open (932-934)
  → _pre_dispatch_guards                # pre_tool_call hook + ACP 审批 (940)
  → notify_other_tool_call              # 非读类调用重置连续读循环计数 (946-951)
  → _execute_tool                       # middleware → registry.dispatch (955)
  → _emit(post_tool_call)               # 观测 hook，status 由结果推导 (958)
  → _apply_transform_tool_result_hook   # 插件可替换最终结果串 (959)
```

逐跳说明：

1. **参数 coercion**：`coerce_tool_args` 按 registry 里的 JSON Schema 修复模型常见的类型错误——`"42"`→int、`"true"`→bool、JSON 编码字符串→数组/对象（含容器内递归）、裸标量包成单元素数组；schema 不允许 null 的字段才尝试转换，**修不动就保留原值**（保守，不猜）（`tools/arg_coercion.py:1-7, 20-80`）。先做 sanitizer 反改名映射（模型看到的是改写后的 key）（`tools/arg_coercion.py:31-36`）。
2. **别名与桥分流**：legacy 工具名映射；Tool Search 桥工具提前分流（§3）。
3. **请求 middleware**：`tool_request` 中间件可改参，fail-open（`model_tools.py:752-762, 932-934`）。
4. **pre-dispatch guards**（审批接口点，接口如下）：
   - 插件 `pre_tool_call` hook：一次调用同时返回 block 消息与改参，block 则整条短路（`model_tools.py:775-787`）；
   - ACP/Zed 编辑审批：任何文件变更前拦截，且 guard 自身抛错时对 write_file/patch **fail-closed**（`model_tools.py:789-800`）；
   - 审批通过 thread-local callback 注入 terminal 工具（`tools/terminal_tool.py:88-100`），网关模式走 `tools/approval.py` 的 per-session 队列（`submit_pending`/`resolve_gateway_approval`/yolo 旁路，`tools/approval.py:139, 244, 276-281`）。
5. **执行**：`_execute_tool` 绑定审批观测上下文（turn/tool_call/session id），经 `tool_execution` middleware 后调 `registry.dispatch`（`model_tools.py:822-845`）。dispatch 里 kwargs 按 handler 签名过滤（窄签名插件 handler 不被注入字段弄崩，`tools/registry.py:903-905, 1033-1043`）；`is_async` 的 handler 经 `_run_async` 桥接（`tools/registry.py:905-909`）。`execute_code` 特殊：`enabled_tools` 用调用方传入而非进程全局，防止子代理改写父级 sandbox 工具集（`model_tools.py:827-830`）。
6. **结果回灌**：`_normalize_handler_result` 规范化（§2）→ `post_tool_call` 观测 hook（status 从结果推导，`model_tools.py:676-700, 658-673`）→ `transform_tool_result` hook 可替换最终字符串（`model_tools.py:848-865`）→ 返回 JSON 字符串进消息历史。
7. **例外通道**：`todo`/`memory` 这类需要活 AIAgent 状态的"agent 级工具"在到达 handle_function_call 之前就被 `INLINE_TOOL_EXECUTORS` 表拦截执行（`agent/inline_tool_executors.py:1-7`；`tools/AGENTS.md:62-64`）。agent 循环自持工具（delegate 的控制动作等）被 `_AGENT_LOOP_TOOLS` 挡回（`model_tools.py:937-938`）。

## 5. terminal 后端抽象

- **抽象**：`BaseEnvironment`（ABC）统一 **spawn-per-call** 模型——每条命令起一个新 `bash -c`，初始化时抓一次 shell 会话快照（env/函数/别名）并在每条命令前 re-source；CWD 用带内 stdout 标记（远程）或临时文件（本地）跨命令持久（`tools/environments/base.py:1-6, 358-417`）。工具层拿到的永远是 `execute()` 结果 dict。
- **后端表**：`_ENV_BUILDERS = {local, docker, singularity, modal, daytona, vercel_sandbox, ssh}`，未知 env_type 落到插件后端构建器——加后端=加表项，不写 elif（`tools/terminal_tool_backends.py:233-235, 238-259`；规则 `tools/AGENTS.md:81-88`）。选择靠 `TERMINAL_ENV`（默认 local），每个后端有独立 requirements 检查器（如 Vercel 要 runtime+SDK+OIDC token 三选一组合，`tools/terminal_tool_backends.py:262-289`）。
- **生命周期**：环境按 task_id 缓存在 `_active_environments`（委派/浏览器/kankan 各自的 task_id 隔离会话）；5 分钟无活动 teardown，但**有活跃后台进程的环境续命**（`tools/terminal_tool_lifecycle.py:126-173`）。atexit 统一清理；前台命令登记在进程级 `_live_foreground` 表，宿主进程退出时硬杀预算 0.5s（`tools/environments/base.py:77-131`）。
- **前台/后台**：schema 把策略写进参数描述——前台 timeout 上限 600s（`FOREGROUND_MAX_TIMEOUT`），超限的前台调用自动转成 tracked 后台进程并告知"别重跑"；`background=true` 返回 session_id，`notify`（bool=退出通知 / pattern 数组=就绪信号）、`heartbeat`（N 秒增量输出）、`persist_on_release`（跨会话清理存活）各司其职（`tools/terminal_tool.py:79, 1506-1559`）。`_handle_terminal` 包装层做参数纠偏：模型把 execute_code 的 `code` 误发过来时指出正确用法；前台带 notify/pty/persist 直接拒绝并给出改写后的正确调用（防止 46 个子代理会话各重试 4 次那种死循环，注释引了真实事故，`tools/terminal_tool.py:1562-1609`）。
- **环境变量单口**：所有子进程（terminal、execute_code、后台进程、委派子进程、ACP/MCP stdio 子进程）的 env 都从 `environments/local.py::build_subprocess_env` 走，链路是 sanitize（合并 base/extra env）→ `_scrub_credentials`（按 `inherit_credentials` 决定保留哪些密钥）→ profile home 钉扎（`tools/environments/local.py:276-345`）；为某 profile 服务的孩子用 `served_profile_child_env`（剥掉启动 profile 的 .env 残留、钉住目标 home、只叠目标自己的密钥）（`tools/environments/local.py:386-445`）。`os.environ.copy()` 直接传会钉死启动 profile——contextvars 不跨进程边界，必须在 `Popen` 前解析（`tools/AGENTS.md:98-107`）。
- **结果后处理**（`finalize_foreground_result`，`tools/terminal_tool_result.py:211-245`）：记录本会话持久 CWD（只认命令自己报的 cwd 标记）→ sudo 注解 → 输出 transform hook → **head/tail 截断**（§7）→ strip ANSI → **命令感知的密钥 redact**（env-dump 命令走 KEY=value 强掩码，源码 dump 跳过该遍防误伤）→ exit code 解释 + 失败恢复提示（`tools/terminal_tool_result.py:160-172`）。
- **后台进程终止纪律**：teardown 只先 SIGTERM 记录的**父进程**，等它自己退出并收割子女（`terminal.daemon_term_grace_seconds` 宽限）；然后 SIGTERM 快照里的幸存者，最后对两次都无视的 SIGKILL——顺序反了会把会收割子女树的监督者（Chromium/Electron 收割 zygote、shell trap）的正常退出 0 变成 SIGTRAP core dump（`tools/process_registry_termination.py:33-120`；纪律陈述 `tools/AGENTS.md:114-123`）。`heartbeat=N` 的后台进程由 `process_registry.py` 单一守护定时线程驱动全会话心跳，增量输出走完成队列，每个渲染 watch_match 的面板都必须同时渲染 heartbeat（`tools/terminal_tool.py:1542-1547`；`tools/AGENTS.md:146-148`）。

## 6. browser 工具族

- **进程模型**：浏览器工具不自己驱动 CDP，而是 spawn **agent-browser daemon**（外部 CLI，Rust），每会话一个 socket 目录 + pid 文件；Python 侧管会话缓存、健康与清理（`tools/browser_tool_session.py:1-3, 130-192`）。会话默认 120s 不活动超时，孤儿宽限 = max(3600, 20×超时)（`tools/browser_tool.py:394-413`）。
- **超时自愈**：每个会话 key 挂一个 `SuspectableBackend` 适配器——命令超时的线程**无锁**写 suspect 标记；下一次任何命令过 `_get_session_info` 咽点时 `ensure_healthy()` 先回收可疑会话再继续（`tools/browser_tool.py:425-458`）。
- **CDPSupervisor**：每 task_id 一个持久 WebSocket 监听 `Page/Runtime/Target` 事件（顶页+自动附着的 OOPIF/worker），把 pending 对话框与 frame 树做成线程安全快照；**它不在任何工具 schema 里**——产物经由 `browser_snapshot`/`browser_dialog` 到达模型；进程全局 `SUPERVISOR_REGISTRY` 幂等管理启停（`tools/browser_supervisor.py:1-8, 98-135, 501-508`）。`browser_cdp` 的 `Runtime.evaluate` 走 supervisor 快路径省 subprocess（`tools/browser_tool.py:1049-1062`）。
- **清理纪律**：浏览器会话清理只挂 atexit，**不挂 SIGINT/SIGTERM**——避免 sys.exit 路径重入；daemon 侧另有 idle 自毁定时器（agent-browser 0.24+），但其时长必须与 Python 侧租约感知的 janitor 协调（bot 的有头 Chromium 场景 daemon 看不见租约，决定权在 Python janitor，`tools/browser_tool_session.py:178-202`；atexit 约定 `tools/browser_tool.py:470`）。
- **注册形态**：`_BROWSER_TOOL_TABLE` 驱动的 for 循环一次性注册全部 browser_* 工具（toolset="browser"），handler 统一过 `routed_browser_handler`（本地/云后端路由）+ `record_browser_call`（观测）（`tools/browser_tool.py:1360-1373`）。真实用户 profile 场景用单个共享会话 `_REAL_PROFILE_SESSION`，避免并发任务在同一拷贝的 user-data-dir 上互起 Chromium（`tools/browser_tool.py:263-270`）。
- **与普通工具的关系**：browser 是普通注册表工具，但有两处工具面级联动——`browser.backend=browser-use` 时 `browser_exec` 替换其余 browser 工具（`tools/AGENTS.md:76-78`；`toolsets.py:22` 注释）；`browser_exec` 能跑宿主 Python，故要求 terminal 工具在场，否则从可见面丢弃（`model_tools.py:388-392`）。

## 7. 异步委派与输出治理

**异步委派**（`delegate_task(background=true)`）：

- 父 agent 把子任务派到模块级 **daemon 线程池**（永不 join 的 daemon executor，防止后台工作挂死硬退出），立即返回 delegation id（`tools/async_delegation.py:8, 32-36`）。
- **批量与 completion 单元**：一次委派可以是单任务或批量；后台批量默认作为**一个**完成事件回报，开启 `delegation.independent_completions` 后按 **unit** 拆分——共享 `group` 的任务合并回报、未分组的任务各自完成即报；一次调用的所有 unit 共享**一个池槽**（`slot_key`），容量判定按 slot 数而非 unit 数，拆分汇报不会比整批多占容量（`tools/async_delegation.py:637, 730-764, 843-862`；`tools/AGENTS.md:130-135`）。角色两种：`leaf`（默认，禁 delegate_task）与 `orchestrator`（可保留 delegate_task，需 `delegation.orchestrator_enabled`，深度受 `max_spawn_depth` 默认 2 限，深度>0 一律同步跑）（`tools/AGENTS.md:135-151`）。
- 完成时事件推入与后台进程**共享**的 `process_registry.completion_queue`，CLI/网关空闲时 drain——结果**永远以新 turn 出现，绝不在 turn 中间插入**，天然继承去重与崩溃恢复接线（`tools/async_delegation.py:5-8, 940-945`）；完成事件同时写持久 ledger。
- 容量与保留：默认并发 3 个 async child；内存保留 50 条完成记录；持久 ledger 7 天/1000 条 pending；重启重放只发 48h 内的完成（周末结果仍可送达）；delivery claim 是 300s 租约，可被重新认领（`tools/async_delegation.py:38-48`）。另有**孤儿完成清扫**：owner 在本进程运行期间死亡（如桌面端重载）的 pending 行，交付循环每 30s 扫一次、60s 冷却后重新提供——投递 claim 是结清行的唯一方式，丢弃副本的消费者会把行退回（`tools/async_delegation.py:50-56`）。
- **停滞检测不用墙钟超时**："重活不能因为跑得久被杀"——监控线程按注入的 progress_fn 采样进度，冻结 450s（工具内 1200s）才给 120s 宽限走正常 finalize，永不返回才强制 stalled（`tools/async_delegation.py:51-60`）。
- **恢复提示（recovery hints）**：owner 进程死亡（OOM/崩溃）后，恢复事件不再只说"结果未知+transcript 路径"，而是内联每个 transcript 的**最后 20 行（封顶 2000 字符）**和 owner 工作目录的**一行 git 快照**（branch@sha+脏文件数），让父 agent 不做取证就能决定继续还是重派；全程 best-effort 有界，git 走 5s 超时+非交互 env（`tools/async_delegation_recovery_hints.py:1-9, 16-18, 42-70`）。
- 子代理工具面收窄：`DELEGATE_BLOCKED_TOOLS`（delegate_task/clarify/memory/send_message/cronjob_manage/start_chat——禁递归、禁用户交互、禁共享记忆写入、禁跨平台副作用、禁以父名义排程），orchestrator 角色可解除 delegate_task（`tools/delegate_tool_toolsets.py:14-23`；`tools/delegate_tool.py:58`；`tools/AGENTS.md:125-139`）。

**输出治理**：

- 三个全局上限，config `tool_output` 节可调：`max_bytes=50000`（terminal/execute_code/MCP 结果）、`max_lines=2000`、`max_line_length=2000`（`tools/tool_output_limits.py:13-15, 34-53`）。
- **单一截断算法**：head 40% / tail 60%（错误早出现、最新输出最重要），中间一条统一措辞的 `... [OUTPUT TRUNCATED - N chars omitted out of M total] ...` 标记，让所有识别标记的下游代码只见一种形状（`tools/tool_output_truncate.py:12-32`）。
- **截断不是丢弃**：超窗的完整输出由 collector 落盘为 spill 文件，结果里带 `full_output_path` 句柄并明示"用 search_files/read_file 翻，别重跑命令"；落盘副本做同 pass redact + lstat 校验的独占写入（防 symlink 调包），失败则连句柄带文件一起丢（`tools/terminal_tool_result.py:175-197`；`tools/environments/base_output.py:171-179`）。
- 分级：全局 `max_result_size_chars`（每工具可覆写，file 类 100k）→ error body 2048 → 委派 summary 另有预算（`tools/registry.py:928-936`；`tools/file_tools.py:1396-1421`；`tools/AGENTS.md:144`）。
- 文本类工具按 `BINARY_EXTENSIONS`（约 80 个扩展名，PDF 刻意缺席）跳过二进制；`OPAQUE_DOCUMENT_EXTENSIONS`（OOXML/ODF 等）禁止纯文本覆写——read_file 自动抽取过内容，把文本写回去会毁文档（`tools/binary_extensions.py:1-35`）。

## 8. MCP 集成

**双向都有，形态不同**：

```
外部 MCP server                     外部 MCP client (Claude Code/Cursor)
 stdio/HTTP/SSE                          stdio
     │                                        ▲
mcp_tool.py（client，后台事件循环      mcp_serve.py（server）
 每 server 一个长活 Task）              暴露 10 个消息/审批工具
     │                                        │
     └── registry.register(toolset="mcp-<server>") ──┘
```

- **client（消费外部 MCP）**：`tools/mcp_tool.py` 连 config.yaml `mcp_servers`（stdio / Streamable HTTP / SSE 三种传输），每个 server 作为长活 Task 跑在一个后台事件循环线程上（anyio cancel scope 要求单 Task），发现的工具注册进 registry，toolset 名 `mcp-<server>` 并配别名（`tools/mcp_tool.py:1-7`；`tools/mcp_tool_registration.py:135, 353-366`）。周边设施：stdio 命令先过 OSV 恶意包预检（fail-open、12s 墙钟上限，`tools/mcp_tool.py:42-51`）；调用层有信任门（per-profile 信任记录，`tools/mcp_tool_handlers.py:52-88`）、熔断器、stdio 死亡赛跑与一次重试（`tools/mcp_tool_handlers.py:327-435`）。MCP 刷新时先 deregister 自己 toolset 前缀的工具再重注册——`mcp-*` toolset 豁免跨 toolset shadow 检查（`tools/registry.py:745-753`）。
- **server（把 Hermes 暴露为 MCP）**：`mcp_serve.py` 提供 `hermes mcp serve` ——一个 **stdio MCP server**，任何 MCP 客户端（Claude Code/Cursor/Codex）配置 `{"mcpServers": {"hermes": {"command": "hermes", "args": ["mcp", "serve"]}}}` 即可接入。暴露 10 个工具：conversations_list / conversation_get / messages_read / attachments_fetch / events_poll / events_wait / messages_send / channels_list / permissions_list_open / permissions_respond（对齐 OpenClaw 的 9 工具通道桥 + 自有 channels_list）（`mcp_serve.py:1-7, 459-683`）。实现直接用 `mcp.server.MCPServer` 的 `@server.tool()`——**docstring 变 description、函数签名变 input schema**，无手写 schema（`mcp_serve.py:26-29, 692-706`）。值得注意的是 `permissions_list_open/permissions_respond`：外部 MCP 客户端能列出并裁决 Hermes 的待审批请求——审批通道也被 MCP 化了（`mcp_serve.py:662-683`）。

## 9. 设计规范清单（可直接照抄）

1. 工具=模块级自注册，发现走 AST 判定 + mtime 落盘缓存；import 失败降级 WARNING 不炸启动。
2. handler 只准返回 JSON 字符串（唯一例外多模态信封），错误一律 `{"error": ...}` 且封顶。
3. 注册≠暴露：工具必须被 toolset 点名才可见；disabled 永远最后减。
4. schema 描述不许硬编码引用其他 toolset 的工具——交叉引用由可见面合成期按在场集合动态注入。
5. `check_fn` 回答可达性/opt-in，TTL 30s + 60s 失败宽限；"谁在对端"这类会话属性绝不进 check_fn。
6. 可用性探测失败先疑自身（抖动宽限），核心工具降级要一次性点名 WARNING。
7. 参数 coercion 保守：修不动保留原值，bare 标量包数组而非拒绝。
8. terminal 后端=表项不是 elif；每命令新 bash -c + 会话快照 re-source + CWD 带内标记。
9. 截断统一 head/tail 40/60 + 单一标记；截断必附落盘句柄，鼓励翻读而非重跑。
10. 后台工作：完成走队列、以新 turn 回灌；停滞检测按进度不按墙钟；恢复事件内联取证材料。
11. 递归收窄：子代理禁委派/禁用户交互/禁共享状态写入。
12. 幽灵词防御：模型可见描述里的每个工具名都要在该会话在场。

## 10. 知识点与最佳实践

| 做法 | 解决的问题 |
|---|---|
| import 时自注册 + AST 发现缓存 | 工具清单免手工维护，启动扫描 145ms→缓存读 |
| handler 契约（JSON 串 or 多模态信封） | 下游日志/预算/持久化拿到的东西永远可计量 |
| 注册期 schema 校验 | 病态 schema 400 整个 turn 且难归因 |
| check_fn TTL+抖动宽限 | 探测抖动静默剥掉整个 toolset、子代理报"工具不存在" |
| 动态 schema rewriter | 模型幻觉调用未配置工具；无终端会话经 browser_exec 重获宿主执行 |
| 定义缓存键含 registry generation + config mtime | 长命网关进程看不到配置热更新 |
| tool_search 渐进披露 | MCP 工具面撑爆上下文；受限会话经桥摸到全注册表 |
| coerce_tool_args schema 引导 | 模型发 "42"/JSON 字符串导致工具层类型崩 |
| CWD 带内标记 + 只认自报 cwd | 被杀命令报不出 cwd 时把别人会话的目录记成自己的 |
| 超限前台自动转后台+notify | 模型为长任务设置荒唐 timeout 干等 |
| suspect 会话无锁标记+咽点回收 | 超时后的死会话被反复复用 |
| supervisor 快照并入 browser_snapshot | 对话框/iframe 状态没有工具可查 |
| 完成=队列事件=新 turn | 后台结果插进进行中的 turn 毁掉状态机 |
| 48h 重放上限 + 300s claim 租约 | 崩溃重启后周末旧结果全量重放、投递死锁 |
| 恢复事件内联 transcript 尾+git 快照 | 父 agent 为判断是否重派被迫开文件取证 |
| spill 文件 + full_output_path 句柄 | 截断丢信息诱发代价高昂的重跑 |
| 二进制/不透明文档扩展名表 | read_file 抽取+write_file 回写静默毁掉 OOXML |
| MCP stdio OSV 预检 + per-profile 信任门 | 供应链投毒与多 profile 信任越权 |
| webhook 工具面白名单（仅 4 个无执行工具） | 不可信第三方载荷无文件/系统执行面 |
| 终止先父后子的信号纪律 | 会收割子女树的监督者被误杀成 core dump |
| 定义缓存返回浅拷贝 | 共享列表被 append 后重复工具名触发 HTTP 400 |
| slot_key 共享池槽 | 批量拆分成多个完成单元后容量虚增 |

## 11. 对 Memoria 的可迁移结论

Memoria 现状：**没有工具体系**——LangGraph 节点即"工具"，检索/问答/邮件分类都是图内节点；红线要求回答带来源引用、归档需人工确认、`raw/` 只读。hermes 的工具系统面向"通用个人 agent"，多数机制对 Memoria 过重，但以下约定在"若做 MCP server 暴露 memoria_ask / memoria_ingest"时直接可用：

**适合搬（低成本高确定性）**：

- **MCP server 的零 schema 面**：`mcp_serve.py` 用 `@server.tool()` 让 docstring/签名直接变 schema（`mcp_serve.py:26-29`）——Memoria 暴露 `memoria_ask`/`memoria_ingest` 用同款形态即可，stdio 起步，不必先上 HTTP。服务端直接读自己的 state（hermes 的 server 就是读 `state.db` 与 sessions 目录，`mcp_serve.py:48-57`），不需要把内部函数改造成工具协议。
- **handler 契约与错误封顶**：所有工具结果必须是可序列化、可计量的 JSON 字符串；error 字段封顶（hermes 取 2048）。`memoria_ask` 的返回天然应该带 `{kind, title, excerpt, doc_id}` 溯源数组——与红线"回答必须带来源引用"同构（`tools/registry.py:876-891, 1022-1025`）。
- **输出落盘而非丢弃**：大结果（如 ingest 的全量分块日志）超窗时 spill 到文件 + 结果里给路径句柄"用某工具翻，别重跑"；Memoria 无文件工具，但等价做法是"句柄指向 DB 查询参数"（`tools/terminal_tool_result.py:175-197`）。
- **可见面最小化纪律**：描述里不提不可用能力、每个参数描述写清"何时该用/何时不该用"（terminal schema 的 `notify`/`background` 描述是范本，`tools/terminal_tool.py:1516-1552`）。MCP 工具面越小说明越清晰。
- **参数 coercion 保守修复**：若接 MCP client，`"42"`/JSON 字符串的 schema 引导修复几乎零成本（`tools/arg_coercion.py:20-80`）。
- **异步完成的"新 turn 回灌"模型**：ingest 长任务若做异步，完成事件入队、由编排层以新消息回灌——绝不中途插入（`tools/async_delegation.py:5-8`）。
- **在 LangGraph 里的对应物**：Memoria 无需 registry——图节点本身就是"注册表"，节点名即工具名。值得照抄的是**边界约定**而非机制：节点返回值统一 JSON 形状、错误结构化封顶、对外（MCP）面与图内节点共享同一批边界函数而不是各写一份。

**不适合搬**：

- 注册表/发现/AST 缓存/插件 override 全套——Memoria 工具个位数，一个 dict 够了；这是 hermes 281 文件规模才需要的基础设施。
- terminal 后端矩阵、browser 族、check_fn 多 profile 缓存——单人单机 RAG 无此拓扑。
- tool_search 渐进披露——Memoria 工具面远低于触发预算。

**谨慎借鉴**：hermes 的审批队列把"待审批"做成可列出/可裁决的持久对象（`tools/approval.py:244`；`mcp_serve.py:662-683`）——Memoria 的"归档必须人工确认"若做成 LangGraph interrupt + 一个 `memoria_pending_approvals` 查询接口，比纯内存 interrupt 更抗重启，但需先验证 LangGraph checkpointer 已覆盖该需求（未在本文范围内验证）。

## 12. 证据索引

| 结论 | 文件:行 |
|---|---|
| 注册表自述/发现链/多模态契约 | `tools/AGENTS.md:9-21` |
| 注册参数与 schema 校验 | `tools/registry.py:666-743, 678-686` |
| AST 发现 + mtime 缓存 + 包入口约定 | `tools/registry.py:69-93, 96-141` |
| handler 结果规范化 / 错误封顶 | `tools/registry.py:876-891, 26-56, 1022-1031` |
| shadow 拒绝与插件 override opt-in | `tools/registry.py:697-730, 588-615` |
| check_fn TTL/宽限/核心降级 WARNING | `tools/registry.py:223-233, 348-384` |
| 定义缓存键/浅拷贝/最后减 disabled | `model_tools.py:205, 214-253, 256-279, 315-337` |
| 动态 schema rewriters | `model_tools.py:349-490` |
| tool_search 桥与解包重派 | `tools/tool_search.py:1-5`; `model_tools.py:703-749, 902-922` |
| dispatch 主链/coercion/守卫/middleware | `model_tools.py:872-965, 765-800, 822-845`; `tools/arg_coercion.py:20-80` |
| 内联工具拦截表 | `agent/inline_tool_executors.py:1-7` |
| core 束与 toolset 规则 | `toolsets.py:11-39, 70-71, 234`; `tools/AGENTS.md:40-42, 160-181` |
| 平台开关持久化 | `hermes_cli/web_routers/tools.py:281-310`; `hermes_cli/tools_config.py:554-590` |
| 采样分布（数据生成用） | `toolset_distributions.py:14-46, 67-93` |
| terminal 后端表/抽象/生命周期 | `tools/terminal_tool_backends.py:233-259`; `tools/environments/base.py:1-6, 77-131`; `tools/terminal_tool_lifecycle.py:126-173` |
| terminal schema/参数纠偏 | `tools/terminal_tool.py:79, 1506-1559, 1562-1609` |
| env 单口/结果后处理 | `tools/environments/local.py:350-445`; `tools/terminal_tool_result.py:160-245` |
| 输出限制/head-tail 截断 | `tools/tool_output_limits.py:13-15`; `tools/tool_output_truncate.py:12-32` |
| spill 落盘与 redact | `tools/terminal_tool_result.py:175-197` |
| 二进制/不透明文档表 | `tools/binary_extensions.py:1-35` |
| 浏览器 daemon/会话/自愈 | `tools/browser_tool_session.py:1-3, 130-192`; `tools/browser_tool.py:263-270, 394-413, 425-458` |
| CDPSupervisor/注册循环 | `tools/browser_supervisor.py:1-8, 98-135, 501-508`; `tools/browser_tool.py:1049-1062, 1360-1373` |
| 异步委派队列/保留/停滞检测 | `tools/async_delegation.py:5-60, 940-945` |
| 恢复提示内联取证 | `tools/async_delegation_recovery_hints.py:1-9, 16-18, 42-70` |
| 子代理工具收窄 | `tools/delegate_tool_toolsets.py:14-23`; `tools/delegate_tool.py:58` |
| MCP client 注册/预检/信任门 | `tools/mcp_tool.py:1-7, 42-51`; `tools/mcp_tool_registration.py:135, 353-366`; `tools/mcp_tool_handlers.py:52-88, 327-435` |
| MCP server 工具面 | `mcp_serve.py:1-7, 26-29, 459-683, 692-706` |
| 审批接口点 | `model_tools.py:775-800`; `tools/terminal_tool.py:88-100`; `tools/approval.py:139, 244, 276-281` |
