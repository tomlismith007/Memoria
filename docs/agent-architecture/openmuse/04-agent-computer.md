# OpenMuse 核心设计 · 04 浏览器与 Linux Computer

> 研究对象：`CopilotKit/OpenMuse` — 个人 agent，MIT，TypeScript；HEAD `1ac68f3`（main，2026-10-11）
> 路径相对仓库根，`文件:行` 均为实读行号；结论只来自源码
> 本篇聚焦：浏览器 worker（`apps/worker/src/browser.ts`、`server.ts`、`downloads.ts`）、服务端 browser 客户端（`apps/server/src/browser.ts`）、Docker computer（`computer.ts` 全文 771 行、`computer-backend.ts`、`apps/computer/Dockerfile`、`files.py`）、E2B desktop（`computer-e2b-desktop.ts`）、模型侧工具面（`computer-tools.ts`）
> 与 [../04b-openmuse-alpha-surfaces.md](../04b-openmuse-alpha-surfaces.md) §2 重叠处只做引用 + 增量；04b 未覆盖的 stale-executor restart fencing、中断不重放的四条路径、E2B 流 tag 围栏、files.py 的 symlink 拒绝在本篇首次完整覆盖

---

## 1. 定位与全景

两个独立的执行环境，都在"进程/容器边界之外"：

- **浏览器 worker**（`apps/worker`）：独立 Node 进程 + 持久 Chromium，服务端通过 HTTP + Bearer token 访问。
- **Linux computer**（`apps/computer`）：Docker 容器（默认）或 E2B VM（可选）。

```
server 进程（Hono）
  ├─ BrowserService ──HTTP+Bearer──► worker 进程（:8790）
  │    持久 Chromium（launchPersistentContext + 独立 profile）/ 出站代理（只连已验证 IP）
  │    下载监控（10 MiB + %PDF- 校验）/ 每会话串行队列
  └─ ComputerService
       ├─ DockerProvider ──docker exec──► 容器（nonroot / 无网 / 只读根 / cap drop ALL）
       └─ E2BDesktopProvider ──SDK──► E2B VM（网络开启 / 有 sudo / 15min 空闲 pause）
            两者共用：30s 命令上限 / 128 KB 输出上限 / 五状态回执 / 租约
```

**核心共同点**：都有**租约**（computer 的 180 秒 lease，浏览器的每会话串行队列），都**不重放中断的工作**，都把"结果未知"显式建模。

## 2. 浏览器 worker 的进程模型

### 2.1 HTTP 契约

服务端配置：`workerUrl`（`BROWSER_WORKER_URL`，无 scheme 自动补 `http://`，`config.ts:90-95`）+ `workerToken`（`WORKER_TOKEN`）。

调用（`browser.ts:73-107`）：`fetch(workerUrl + path, { headers: {Authorization: \`Bearer ${workerToken}\`}, signal: AbortSignal.any([signal, AbortSignal.timeout(45000)]) })`。**双重 signal**：调用方 signal（用户停止）与 45 秒硬超时合成；catch 里先 `throwIfAborted()`——若是用户停止则抛取消而非 503（错误归因准确）；503（worker 不可达）与 502（worker 返回错误）分离。

worker 侧认证（`worker/src/server.ts:42-63`）：启动即校验 `token.length < 32` 抛错；`tokenHash = sha256("Bearer " + token)`；只有 `/health` 免认证，其余用 `timingSafeEqual(sha256(header), tokenHash)` 比对。**只比对 hash**（不保存原文），常量时间比较。

路由：`POST /sessions`、`POST /sessions/:id/(navigate|close|input)`、`GET /sessions/:id/(read|screenshot|downloads)`、`GET /downloads/:downloadId`（`server.ts:73-104`）。超时参数：`requestTimeout=30_000`、`headersTimeout=10_000`、`keepAliveTimeout=5_000`、`maxRequestsPerSocket=100`（`server.ts:119-122`）。

**健康检查短缓存**（`browser.ts:50-63`）：结果缓存 15 秒、超时 2 秒——snapshot 会频繁调用，不能每次都打真实请求。

### 2.2 持久化与六个安全启动参数（`worker/src/browser.ts:176-203`）

```ts
context = await chromium.launchPersistentContext(profileDir, {
  // Chromium does not need the worker API credential in its environment.
  env: { HOME, PATH, LANG },   // 只给这三项
  headless: true, viewport: { width: 1280, height: 800 },
  proxy: { server: proxy.url, bypass: "<-loopback>" },
  serviceWorkers: "block", acceptDownloads: true, downloadsPath: tempDirectory, timeout: 25_000,
  args: ["--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
         "--disable-extensions", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"],
});
```

每个参数堵一类旁路：

| 参数 | 堵住什么 |
|---|---|
| `env` 只给 HOME/PATH/LANG | Chromium 子进程**拿不到 WORKER_TOKEN**（注释原文） |
| `proxy: {server, bypass: "<-loopback>"}` | 全部流量走已验证代理；`<-loopback>` **移除 Chromium 隐式的环回绕过** |
| `serviceWorkers: "block"` | Service worker 可绕过代理拦截请求 |
| `--disable-quic` | QUIC/UDP 会绕过 HTTP 代理 |
| `--force-webrtc-ip-handling-policy=disable_non_proxied_udp` | WebRTC 可泄露真实 IP 并建立非代理 UDP 通道 |
| `--host-resolver-rules=MAP * ~NOTFOUND` | **浏览器层再禁一次 DNS**——只有代理能解析（见 [06 篇](06-security.md) §2.8） |

**cookies 持久化**（`:146,214-222`）：关闭时 `context.storageState({path: "storage.json"})`，重开时 `addCookies`。**会话元数据从磁盘恢复，恢复态一律 `closed`**（`:50-61`）——进程重启后 Chromium 确实不在跑，元数据不能撒谎。

### 2.3 会话生命周期与串行队列

- **默认 3 个活跃会话、30 分钟空闲关闭**（`:44`）；
- **每会话串行队列**（`:68-77`）：`previous.catch(() => {}).then(fn)`——人机输入与 agent 调用**天然排队**，不会出现"agent 正在 navigate，用户同时点链接"的竞态。服务端侧也有对应 `serial`（`browser.ts:64-72`）；
- **非活跃会话的 console 直接 409**（`:78-88`）："Open this browser session before using its console."；
- **空闲清扫**（`:292-298`）：每 60 秒扫一次。

### 2.4 attach 前的复核

服务端把 worker 返回的会话写库前**先解析**（`browser.ts:121-127`）：

```ts
private async save(owner: string, payload: unknown, expectedId: string) {
  const session = sessionSchema.parse(payload);
  if (session.id !== expectedId)
    throw new AppError("Browser worker returned a different session", 502);
  await this.db.put(owner, "browsers", session);
  return this.decorate(owner, session);
}
```

`sessionSchema`（`:11-17`）校验 `id/title/url/status(枚举)/updatedAt`；`readSchema`（`:18-23`）另限 `title ≤300`、`text ≤100_000`。**id 一致性检查**防"worker 状态错乱返回了别人的会话"。

**"先记归属再调 worker"**（`:130` 注释）："Record ownership before calling the worker, including when its response is lost."——若响应丢失，库里仍有归属记录，profile 不会变孤儿。

同类设计（`:194-205`）：

```ts
// Persist the association before contacting the worker so failed/lost responses
// and later chat turns keep using the same profile instead of exhausting its limit.
const association = (await this.db.get<ChatBrowser>(owner, "chat-browsers", threadId))
  ?? (await this.db.insertIfAbsent(owner, "chat-browsers", { id: threadId, sessionId: randomUUID() }))
  ?? (await this.db.get<ChatBrowser>(owner, "chat-browsers", threadId));
```

**线程 → 会话绑定先落库、后联系 worker**，且用 `insertIfAbsent` + 读回处理并发。保证同一对话的所有 `browse_web` 复用同一 profile，且不会因失败反复创建把 3 个配额耗光。

### 2.5 下载三重防护（`worker/src/downloads.ts`）

1. **先落 pending 日志**（`:90-92`）："A worker restart can now report an interrupted transfer even if Chromium never reaches its completion callback."
2. **100ms 轮询临时目录，超限即 cancel**（`:103-115`）；
3. **流式逐字节计数 + `%PDF-` 前缀校验**（`:118-146`）。

`MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024`（`:9`）。服务前**再查一次大小**（`browser.ts:379-388`）。**重启恢复**（`downloads.ts:30-54`）：`pending` 且无元数据的传输清理半成品并改写 `failed`（"Clear unpublished files first so an incomplete cleanup can be retried."）。**一条重要约束**（`:148-163`）："Once metadata is visible, its PDF must remain available even if clearing the transfer journal fails. Restart recovery reconciles that journal."——**元数据可见后 PDF 必须保留**，宁可留下孤儿 journal 条目，也不能让用户看到列在列表里却下不来的文件。

## 3. 浏览器 console：人工共驾

`decorate()`（`browser.ts:114-120`）每次返回会话时**现签**两个 URL：

```ts
consoleUrl: this.auth.sign(owner, `/api/browsers/${session.id}/console`),
previewUrl: this.auth.sign(owner, `/api/browsers/${session.id}/preview`),
```

签名（`auth.ts:42-48`）：HMAC-SHA256 覆盖 `owner\npath\nexpires`，**15 分钟有效**。校验（`:49-66`）：`expires` 纯数字、未过期、`signature` 64 位十六进制，最后 `timingSafeEqual`。

**续期方式**：没有 refresh 端点——客户端重新 GET 会话（任何返回 `decorate` 的响应）就得到新 URL。测试 `tests/browser.test.ts:59-70` 把时钟推后 16 分钟验证旧 URL 401、新 URL 可用。

签名路由白名单（`app.ts:133-141`）：

```ts
const signedRoute = /^\/api\/files\/[^/]+\/content$|^\/api\/browsers\/[^/]+\/(?:preview|console)$/.test(c.req.path);
const owner = signedRoute && c.req.query("signature")
  ? auth.verify(new URL(c.req.url)) : await auth.owner(c.req.header("authorization"));
```

**`owner` 是签名覆盖的一部分**——URL 里的 owner 参数无法篡改。

**console 页面**（`browser.ts:292-294` + `browser-console.ts`）：把签名 preview URL 嵌进 HTML，人工在页面里 POST 输入到自己那个 console URL。**控制权转移 = 给人一个带签名的浏览器遥控器**，不需要额外 takeover API。

## 4. Docker computer

### 4.1 隔离面（enforced，逐项证据）

| 项 | 值 | 证据 |
|---|---|---|
| 基础镜像 | `node:22.22.0-bookworm-slim` | `Dockerfile:1` |
| 非 root | `USER 1000:1000`；创建 `--user 1000:1000`；inspect 校验 | `Dockerfile:14`；`computer-backend.ts:121,228-229` |
| 只读系统文件 | `--read-only`；校验 `h.ReadonlyRootfs` | `computer-backend.ts:129,232` |
| 无网络 | `--network none`；校验 `h.NetworkMode === "none"`；`network = "disabled"` | `computer-backend.ts:75,135,237-238` |
| cap drop | `--cap-drop ALL` + `no-new-privileges` | `computer-backend.ts:233-236` |
| 资源上限 | `--memory 512m`、`--memory-swap 512m`、`--cpus 1`、`--pids-limit 128` | `computer-backend.ts:136-143,241-248` |
| tmpfs | `rw,nosuid,nodev,noexec,size=67108864,mode=1777`（精确串比对） | `computer-backend.ts:151-152,251-252` |
| 无宿主挂载 | 只挂一个命名 volume 到 `/workspace`；inspect 校验 volume 唯一 | `computer-backend.ts` 创建参数 |
| ENTRYPOINT | `["/usr/bin/sleep"]` + `CMD ["infinity"]`（精确 JSON 比对） | `Dockerfile:15-16`；`computer-backend.ts:126-128` |
| 环境变量白名单 | 只允许 `PATH/HOME/LANG/NODE_VERSION/YARN_VERSION` | `computer-backend.ts:122-125` |

**没有任何宿主回退**（`computer.ts:84-86` 注释原文）：

```ts
// The only host process this provider can launch is Docker. User input is an argv
// element or stdin, never a host shell program. Do not add a shell fallback here.
```

`docs/COMPUTER.md:7-22` 印证："If Docker is unavailable, the app reports the connection error. There is no fallback that executes commands on the API host."

### 4.2 attach 前 inspect 复核（`computer-backend.ts:112-163`）

```ts
const result = z.array(inspectionSchema).length(1).safeParse(raw);
if (!result.success) throw new AppError("Computer isolation inspection failed; refusing to attach", 409);
// 逐项白名单：Name / Image / User==="1000:1000" / WorkingDir / labels 全等 / Env 白名单 /
// Entrypoint==='["/usr/bin/sleep"]' / Cmd==='["infinity"]' / ReadonlyRootfs / NetworkMode==="none" …
if (!safe) throw new AppError("Computer ownership or isolation does not match this deployment; refusing to attach", 409);
```

**每一次 attach 都重新验证**，不只创建时。理由：容器可能在两次 attach 之间被手动 `docker update` 改了配置，或根本是别的部署创建的。`identity.labels` 逐项比对实现归属校验。

### 4.3 命令执行与回执

`computer-backend.ts:281-301`：

```ts
"/usr/bin/timeout", "--signal=TERM", "--kill-after=2s", "30s", "/bin/bash", "--noprofile", "--norc", "-c", command,
…
{ timeoutMs: 35000, signal },
```

容器内 `timeout 30s`（TERM 后 2 秒 KILL）；宿主侧 35 秒兜底；`--noprofile --norc` 不读用户 shell 配置。**输出上限**（`computer.ts:27,50-82`）：`computerOutputLimit = 128 * 1024`；stdout 与 stderr **共享**预算；硬顶 `Math.min(maxOutputBytes, 15 * 1024 * 1024)`。

**五状态回执**（`packages/domain/src/computer.ts:7`）：

```ts
status: "running" | "succeeded" | "failed" | "timed_out" | "interrupted";
```

终态判定顺序（`computer.ts:542-556`）：`interrupted` > `timed_out` > `succeeded`/`failed`。`timedOut = result.timedOut || result.exitCode === 124`（`:499`）——**exit 124 是 `timeout` 命令的约定退出码**，两条路径都识别。

**回执按 provider 分 kind 存放**（`computer.ts:201-204`）："Receipts are kept per provider, so Docker history never shows up on the desktop."

| provider | kind |
|---|---|
| docker | `computer-commands`（`computer-backend.ts:74`） |
| e2b-desktop | `computer-desktop-commands`（`:328`） |
| 桌面动作 / 租约 / 截图 | `computer-desktop-actions` / `computer-state`+`lease` / `computer-desktop-screens` |

模型经 `computer_status` 读（`computer-tools.ts:49-56`）；用户经 `GET /api/computer`（`computer-routes.ts:13`）。

**命令幂等**（`computer.ts:424-432`）：`hash("computer-command:" + idempotencyKey)` 作 id，命中旧回执直接返回，**不重放**。幂等键来自工具层 `${scope}:${operationId}`（`computer-tools.ts:72-80`）。模型指令（`computer-tools.ts:13-14` 原文）："Use a distinct operationId for each intended command, reuse it for a duplicate request, and never automatically retry an interrupted or timed-out command."

## 5. 租约与 stale-executor restart fencing

### 5.1 Lease 结构与抢占（`computer.ts:29,174-184,224-252`）

```ts
type Lease = {
  id: string; token: string; expiresAt: number;
  stopping: boolean; stopInFlight: boolean; stopAttempt: string; stopConfirmed: boolean;
  executorDone: boolean; operation: "command" | "operation";
};
// leaseDuration = 180000
```

九个字段。抢占：未过期的租约 → 409 "Computer is busy. Wait for the current operation to finish."；过期的用 CAS 抢；没有的用 `insertIfAbsent`。

### 5.2 executorDone 门闩（`computer.ts:262-271`）

注释原文："A stopped command must acknowledge completion before a new lifecycle can begin. A delayed Docker client can otherwise exec into a restarted box." 实现：`if (kind === "command")` 时 CAS `{token: lease.token} → {executorDone: true}`。**释放租约前，命令类操作必须先确认执行者已完成**——场景是一个 Docker exec 客户端因网络延迟还在飞，此时租约过期、新生命周期开始、容器被重启，那个延迟的 exec 会打进新容器。释放条件要求 `stopConfirmed && executorDone` 都成立（`:282-290`）。

### 5.3 执行前二次校验（`computer.ts:456-483`）

**执行前再读一次租约**：`!active || active.token !== lease.token || active.stopping || active.expiresAt <= Date.now()` → 以 "Stopped before execution" 中断，**绝不执行**。防的是"检查通过之后、真正 exec 之前"租约被抢。

### 5.4 Stop 的意图先落库（`computer.ts:374-388`）

```ts
// Record intent before Docker Stop so a concurrently exiting command
// cannot report success over the user's interruption.
```

先把 running 回执改成 `interrupted`（stderr 原文 "Stopped by the user. Inspect the workspace before repeating this command."），再调 Docker Stop。否则一个恰好在同时退出的命令会把自己的 `succeeded` 写上去。

### 5.5 超时/中断 → 停整个沙箱（`computer.ts:499-540`）

注释原文："A lost Docker client cannot cancel exec reliably. Stop the whole sandbox to ensure no unknown command continues after the lease is released." **为什么停整个容器**：Docker 客户端丢了之后，容器里的进程还在跑且无法可靠单独杀掉；停整个沙箱是唯一能保证"租约释放后没有未知命令在运行"的手段。停止失败时保持锁定并提示："Could not confirm the computer stopped. It remains locked; retry Stop after checking the computer provider."

### 5.6 回归测试（`tests/computer.test.ts`）

- `:171` "restart waits until a delayed pre-stop Docker execution acknowledges completion"
- `:269` "an expired lease from a dead executor recovers as interrupted without replay"
- `:361` "a command marked dead after the lease check is never executed"

`docs/VERIFICATION.md:35` 总述："stale-executor restart fencing, retryable Stop, and interrupted recovery without replay"。

## 6. 中断恢复：四条路径，全部不重放

| # | 场景 | 机制 | 证据 |
|---|---|---|---|
| 1 | **租约失效/过期的残留 running 回执** | 快照/列表时把 `running` CAS 成 `interrupted` | `computer.ts:291-313` |
| 2 | **幂等键命中** | 返回旧回执，不 exec | `computer.ts:427-433` |
| 3 | **执行中异常/信号** | catch 后标 `interrupted: true` | `computer.ts:487-498` |
| 4 | **桌面动作派发前** | 先落 `interrupted` 意图回执 | `computer.ts:673-680` |

路径 1 的文案（`:291-313`）："Execution was interrupted. Its outcome is unknown; inspect files before running it again."

路径 4 的注释与文案（`:673-680`）：

```ts
// Save intent before dispatch: a process crash must not erase uncertain input.
"Desktop input is being dispatched; its outcome is unknown until confirmed.
Inspect a fresh screenshot before repeating the action; do not automatically retry it."
```

**相邻机制**：`db.ts:129-133` 的 `recoverInterruptedActions` 把服务重启时残留的 `executing` 审批标为 `outcome_unknown`（见 [03 篇](03-approval-isolation.md) §7.4）。

**四条路径的共同点**：都不尝试判断"到底执行了没有"，而是**统一标为"未知"并要求人检查**。这是 fail-closed 在副作用不可撤销场景下的正确形态。

## 7. PDF 字节保真导入导出

**进沙箱**（`computer.ts:756-766`）：

```ts
if (bytes.length > 10 * 1024 * 1024 || Buffer.from(bytes.subarray(0, 5)).toString() !== "%PDF-")
  throw new AppError("Choose a PDF of 10 MB or smaller", 422);
return this.file<{ path: string }>(owner, "write_pdf", path, undefined, Buffer.from(bytes).toString("base64"));
```

**传输通道**：整个请求是 JSON `{operation, path, text, base64}`，走 **stdin**（不是 argv，避免长度限制与 shell 转义）。Docker 用 `docker exec -i`（`computer-backend.ts:302-318`）；E2B 用 1 MiB 分块 `sendStdin`（`computer-e2b-desktop.ts:645-651`，注释 "Encode once: separate string slices can split a surrogate pair"）。

容器内（`apps/computer/files.py`）：`json.loads(sys.stdin.buffer.read(15 * 1024 * 1024))`（`:14`）、`base64.b64decode(..., validate=True)`（`:66`）、`%PDF-` 检查（`:68`）、10 MB 上限（`:70-71`）、**临时文件 + fsync + `os.replace` 原子替换**（`:79-86`）。`validate=True` 拒绝非法 base64 字符。

**出沙箱**（`computer.ts:767-770`）：

```ts
async pdfBytes(owner: string, path: string) {
  const result = await this.file<{ path: string; base64: string }>(owner, "read_pdf", path);
  return { name: posix.basename(path), bytes: Buffer.from(result.base64, "base64") };
}
```

`read_pdf` 输出预算 **15 MB**，超时秒数随大小动态增长（`:588-592`）：

```ts
// On E2B the request crosses the network on stdin after the process starts, so
// the limit accounts for upload and expected download (PDF JSON can reach 14 MB).
const seconds = 8 + Math.ceil(Math.max(input.length, expectedOutput) / (1024 * 1024));
```

**symlink 拒绝**（`files.py:1,10,49,72-76`）：

```python
"""Fixed stdin JSON filesystem API; every opened component rejects symlinks."""
```

用 `O_NOFOLLOW` 打开**路径的每一段**。防"沙箱内先造一个指向 /etc 的符号链接再让 agent 读写"。**未定位到** `Dockerfile` 或 `docs/COMPUTER.md` 里对它的明文描述——**这条只在代码里，文档没写**。

**字节保真：未定位到显式校验**。这条链路上没有"声明长度 vs 实际长度"或校验和比对。实际防护是：base64 `validate=True`、10 MB 上限、`%PDF-` 魔数、`JSON.parse(result.stdout)`（`computer.ts:599-603`，失败即 502）。

**对比**：浏览器下载链路有精确字节计数与 byte-identical 测试（`apps/worker/tests/worker-checks.ts:92` "download bytes must match the controlled PDF"；`tests/browser.test.ts:369,434,477` 的 `assert.deepEqual(await readFile(pdf), bytes)`）。**这是两条链路的不对称**——若要迁移，应补上长度比对。

## 8. E2B desktop：与 Docker 的差异

| 维度 | Docker | E2B desktop |
|---|---|---|
| 网络 | `disabled` | `enabled`（`SECURITY.md:29`："Internet access is an egress path that OpenMuse does not review"） |
| 隔离来源 | 容器（共享内核） | 独立 VM |
| 只读根 / cap drop / pids 限制 | 有 | **无**（`docs/COMPUTER.md:108`） |
| user 权限 | 1000:1000 | 有免密 sudo（`docs/COMPUTER.md:108`） |
| 空闲行为 | 一直运行 | 15 分钟自动 pause（`computer-e2b-desktop.ts:17`） |
| 命令输出上限 | 128 KB | 1 MB（`outputCeiling`） |
| 盒内磁盘输出上限 | tmpfs 64 MB | 32 MB（`diskCeiling`） |
| 命令超时 | 30s | 同样 30s（`:189-217` 注释："with the same 30 second limit as Docker"） |
| 桌面流观看 | — | 30 分钟（`desktopIdleMs`） |

`docs/COMPUTER.md:107-114` 明确声明："Docker isolation does not provide a dedicated operating-system VM or a hostile-tenant security guarantee."——**文档如实说明两种隔离强度的差异**。

**attach 的 fail-closed 复核**（`:387-414`）：

```ts
// Fail-closed analog of the Docker inspection: refuse to attach to anything this
// deployment did not create. Sandbox.list omits lifecycle, so getInfo checks it.
```

校验 metadata 全等、template 匹配、`lifecycle?.onTimeout === "pause"` 且 `!autoResume`。

**流 URL 的 tag 围栏**（`:148-171`）：

```ts
// Exit bits: 1 = x11vnc runs, 2 = noVNC listens, 4 = `known` started it.
const up = await setup(streamState(known ? streamTag(known) : "-"), user);
if (up === 7 && known) return known;
// The auth key lives only in the SDK object that started the stream, so a
// stream this process did not start, or a half-started one, is restarted.
…
// Marks which URL the running stream belongs to, so a URL cached by this process is
// never returned after another process restarted the stream with a new password.
const streamTag = (url: string) => createHash("sha256").update(url).digest("hex").slice(0, 16);
```

**问题**：进程 A 缓存了流 URL；进程 B 重启了流（新密码）；进程 A 再返回缓存 URL → 用户拿到失效的 URL。**解法**：盒内 tag 文件记录"当前运行的流属于哪个 URL 的 hash"，返回缓存前用 exit bits（1|2|4）确认"这个流是我启动的且完整在跑"。

**控制权转移的真相**（`docs/COMPUTER.md:53`）：

```
Treat it as a bearer secret: anyone holding it gets full keyboard and mouse control
until the next Stop. It carries a VNC password, and VNC authentication uses only its first 8 characters.
```

**未定位到**第一方代码里的 `holder: "bot" | "human"` 字段——只在 `packages/backends/src/openbot.ts:53-60` 的 OpenBot 契约里（未接入部署，见 [05 篇](05-integrations.md) §6）。OpenMuse 自身的"接管"就是"给人一个签名 URL 的 VNC 流"，**没有显式的控制权状态机**。

**缓存句柄失效**（`:470-482`）：keepAlive 失败 → 重查 → 若已非 running 则 `forget(id)` 并 409，**绝不隐式 resume**（注释 `:351-357`："Later operations reuse the cached handle, which fails on a paused box instead of resuming it after a Stop."）。`stop` = `pause`（`:454-460`）且显式清缓存。

**输入不确定性**（`:542-550`）：注释原文 "xdotool dispatches sequentially: a later failure can follow a delivered click or Return. A nonzero exit cannot confirm that no input occurred." 与 "A lost response cannot tell us whether xdotool delivered the input. Capture a screenshot if possible, but never replay the input here."——**非零退出码不能证明"没点下去"**（xdotool 顺序派发，前面的点击可能已生效），两条路径都只置 `uncertain = true`。

## 9. 模型侧工具面（`computer-tools.ts`）

| 工具 | 关键约束 |
|---|---|
| `run_computer_command` | 幂等键 `${scope}:${operationId}` |
| `computer_status` | 读快照（含最近 100 条回执） |
| `write_pdf` / `read_pdf` | 10 MB / `%PDF-` |
| `use_desktop` | 截图**仅本步可见**（`:123-137`） |
| 文件操作 | 走 files.py，symlink 拒绝 |

Docker 模式模型指令（`:13-14` 原文节选）："The computer is a single-owner Docker Linux container with bash, Python, Node and git, not a full VM or graphical desktop. … Commands are limited to 30 seconds and output is capped; **report failure, timeout, interruption and truncation honestly from the receipt**. Use a distinct operationId for each intended command, reuse it for a duplicate request, and never automatically retry an interrupted or timed-out command."

**"report … honestly from the receipt"**——模型被告知要读回执而不是凭印象报告，与对话 prompt 的 "Never claim task completion before server status and receipt confirm it" 是同一条纪律在两处重申。

## 10. 与既有研究的对照

- **与 04b §2 的关系**：04b 已给出浏览器 worker 进程模型、Docker 隔离边界、命令 receipts、停止/重启恢复、PDF transfer、COMPUTER.md 相符性核查。增量：Chromium 六个启动参数各自堵的旁路（尤其 `<-loopback>` 与 `--host-resolver-rules` 的双重 DNS 禁止）、`executorDone` 门闩与"延迟 Docker 客户端 exec 进重启后容器"的场景、Stop 的意图先落库、超时停整个沙箱的理由、四条中断路径的完整枚举、E2B 流 tag 围栏与 exit bits、`files.py` 的逐段 `O_NOFOLLOW`、computer 链路**缺少字节长度校验**这一反面证据。
- **与 talorys 数据平台（[../talorys/08-data-platform.md](../talorys/08-data-platform.md)）**：talorys 明确"无 shell、无代码执行、无任意网络访问"（`tools/index.ts:11-13`），OpenMuse 选择"有 shell 但有界（30s/128KB/无网）"。**两种能力面收窄策略**：talorys 靠"不给工具"，OpenMuse 靠"给工具但强约束"。后者表达力更强、风险面更大，所以需要 inspect 复核 + 租约 + 回执三重结构。
- **与 hermes 工具（[../hermes/05-tools.md](../hermes/05-tools.md)）**：hermes 的工具执行在进程内、无隔离边界；OpenMuse 把执行面推到进程/容器外。这是"个人 agent 要不要给代码执行"的两种答案。
- **与 ZCode 的沙箱（[../01-zcode.md](../01-zcode.md)）**：ZCode 的 Bash 只读判定拆 15 个文件可枚举（命令级）；OpenMuse 用容器边界（环境级）。**"命令白名单"vs"环境隔离"**是两条路线，后者在"agent 需要跑任意 Python"时更实用。
- **与 04-openmuse.md §6 的关系**：旧研究写"Linux computer 是 nonroot Docker、默认无网络、单 owner 容器、持久 /workspace；每条命令 saved output and exit receipts"。**结论一致，本篇补充 enforced 的具体证据行号与 inspect 复核机制**。

## 11. 对 Memoria 的可迁移结论

**适合搬（6 条）**：

1. **中断只标记不重放 + "结果未知"文案（`computer.ts:291-313,673-680`）**：Memoria 的邮件操作（IMAP 标记、SMTP 发送）超时后绝不能自动重试。落点：邮件工具层的错误分支，与 [03 篇](03-approval-isolation.md) 的 `outcome_unknown` 配合。
2. **幂等键 → 回执 id + 命中即返回（`computer.ts:424-432`）**：同一 `operationId` 重复调用返回同一回执。落点：任何"执行 + 记录"的工具。
3. **意图先落库再执行（`computer.ts:374-388,673-680`）**：崩溃不会抹掉"我打算做什么"。落点：需要人工确认的归档操作——先写"拟归档"记录再执行。
4. **执行前二次校验（`computer.ts:456-483`）**：检查通过到真正执行之间的窗口必须再校验一次。落点：任何"检查权限 → 慢操作"的组合。
5. **外部依赖 attach 前复核配置（`computer-backend.ts:112-163`）**：不只在创建时验证，每次使用前都验证。落点：Memoria 若引入外部服务（embedding、SMTP），每次调用前复核配置未变。
6. **文件传输的字节校验（本篇发现的不对称）**：Memoria 若有文件传输，**补上长度比对**——这是 OpenMuse 自己都缺的一环。

**不适合搬（4 条）**：浏览器 worker 全套（超出 RAG + 邮件分拣范围，且需要独立进程 + Playwright + 出站代理的运维成本）；Docker computer 全套（Memoria 不需要代码执行面）；E2B desktop（平台耦合）；签名 URL 控制台（无"人工共驾浏览器"场景）。

**部分可搬**：**串行队列（`browser.ts:68-77`）**——若 Memoria 有"同一资源的多路并发操作"（如同一邮箱的并发 IMAP 操作），每资源一个串行队列是最省心的互斥方案，比锁表简单。落点：邮箱操作的会话级串行。

## 12. 证据索引

| 结论 | 文件:行 |
|---|---|
| worker 环境变量与端口 / token ≥32 + hash 比对 + /health 免认证 / 路由表与超时 | `apps/worker/src/index.ts:3-10`；`apps/worker/src/server.ts:42-122` |
| 服务端 → worker 的 HTTP 契约（双 signal）/ 健康检查 15s 缓存 | `apps/server/src/browser.ts:50-107` |
| 会话 schema 校验 + id 一致性 / 先记归属再调 worker / 线程→会话绑定先落库 | `apps/server/src/browser.ts:11-23,121-138,194-227` |
| 服务端每会话串行 / worker 每会话串行 / 非活跃会话 console 409 | `apps/server/src/browser.ts:64-72`；`apps/worker/src/browser.ts:68-88` |
| Chromium 启动参数六项 / 磁盘恢复会话（强制 closed）/ 会话默认 3 个 30min | `apps/worker/src/browser.ts:44,50-61,176-203` |
| cookies storageState 持久化 / 空闲清扫 60s | `apps/worker/src/browser.ts:146,214-222,292-298` |
| 下载三重防护（pending 日志/轮询/流式计数）/ 服务前复查大小 / 元数据可见后 PDF 必须保留 | `apps/worker/src/downloads.ts:9,30-54,90-92,103-146,148-163`；`apps/worker/src/browser.ts:379-388` |
| 签名 URL（15min HMAC 覆盖 owner/path/expires）/ decorate 现签 / 签名路由白名单 | `apps/server/src/auth.ts:42-66`；`apps/server/src/browser.ts:114-120`；`apps/server/src/app.ts:133-141` |
| Docker 隔离参数（read-only/cap-drop/network none/资源） | `apps/server/src/computer-backend.ts:220-263` |
| inspect 白名单逐项校验 / 无宿主回退注释 / Dockerfile | `apps/server/src/computer-backend.ts:112-163`；`apps/server/src/computer.ts:84-86`；`apps/computer/Dockerfile:1-17` |
| 30s timeout + 35s 宿主兜底 / 输出上限 128KB / 硬顶 15MB | `apps/server/src/computer-backend.ts:281-301`；`apps/server/src/computer.ts:27,50-82` |
| 五状态回执 + exit 124 判定 / 回执按 provider 分 kind / 命令幂等 | `packages/domain/src/computer.ts:7`；`apps/server/src/computer.ts:201-204,424-433,499,542-556`；`apps/server/src/computer-backend.ts:74,328` |
| Lease 九字段 + 180s / 抢占 CAS / busy 409 / executorDone 门闩 | `apps/server/src/computer.ts:29,174-184,224-290` |
| 执行前二次校验 / Stop 意图先落库 / 超时停整个沙箱 | `apps/server/src/computer.ts:374-388,456-483,499-540` |
| 中断恢复四条路径 / 服务重启审批对账 | `apps/server/src/computer.ts:291-313,427-433,487-498,673-680`；`apps/server/src/db.ts:129-133` |
| PDF 进出（10MB + %PDF- + base64）/ read_pdf 15MB 预算 / files.py 逐段 O_NOFOLLOW + 原子替换 | `apps/server/src/computer.ts:588-592,756-770`；`apps/computer/files.py:1,14,49,53-60,66-86` |
| E2B 差异（网络/输出/空闲/磁盘上限）/ fail-closed inspect / 流 tag 围栏 | `apps/server/src/computer-e2b-desktop.ts:17-30,148-171,189-217,387-414` |
| E2B 缓存句柄失效不隐式 resume / 输入 uncertain | `apps/server/src/computer-e2b-desktop.ts:351-357,470-482,542-550` |
| 桌面流 URL 是 bearer secret / Docker vs E2B 隔离强度声明 / 无 Docker 无回退 | `docs/COMPUTER.md:7-22,53,101-114` |
| Docker 模型指令 / 截图仅本步可见 / 幂等键 / PDF 导入导出工具 | `apps/server/src/computer-tools.ts:13-14,72-80,106-112,123-137,156-164` |
| 回归测试（fencing / 不重放）/ E2B 出网不被审查 | `tests/computer.test.ts:171,269,361`；`docs/VERIFICATION.md:35`；`SECURITY.md:29` |
