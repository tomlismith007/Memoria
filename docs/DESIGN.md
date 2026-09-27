# Design System: Memoria

> **Visual Theme**: Utilitarian Minimalism · Rounded Cards · Capsule & Pill Architecture  
> **Tech Stack**: React 19 + TypeScript 5.7 + Tailwind CSS v3 + Lucide Icons (Clean SVG primitives)  
> **Aesthetic Reference**: Apple Dynamic Island / Linear / Notion / Craft editorial style. Clean, tactile, breathing, distraction-free.

---

## 1. Visual Atmosphere & Philosophy

Memoria 的前端界面追求 **“克制、高级、触觉感明确的编辑级极简主义（Editorial Minimalism）”**。  
设计围绕三大视觉支柱展开：
1. **温暖骨白底色与呼吸感留白**：拒绝刺眼的纯白（`#FFFFFF`）全屏直白呈现，使用温暖的骨白/浅灰底色（`#FAFAF9`），配合充裕的内边距与段落行高，呈现出如高质量纸质笔记本的阅读体验。
2. **高阶圆角卡片（Rounded Cards）**：以 `rounded-2xl`（16px）与 `rounded-3xl`（24px）作为核心容器语言。卡片使用极其细微的 1px 细线边框（`border-zinc-200/80`），搭配超漫反射、低透明度的柔和微阴影，杜绝工业化 SaaS 的厚重塑料感。
3. **胶囊按键（Pill UI）与触觉反馈**：所有交互控件（主操作按钮、标签徽标、双向链接 `[[Wiki]]`、来源引用 `[1]`、顶部导航栏）均采用胶囊圆角（`rounded-full`），并在用户悬浮、点击激活时提供精准的物理按压收缩动效（`active:scale-[0.98]`）。

---

## 2. 颜色规范 (Color Tokens)

坚持 **“单色主调（Monochrome）+ 语义化低饱和粉彩（Muted Pastels）”** 原则。严禁使用任何高饱和紫色/霓虹渐变。

| 语义角色 | 变量/类名 | 色值 (Hex) | 用途说明 |
|---|---|---|---|
| **Canvas** | `bg-canvas` | `#FAFAF9` (Stone-50/Zinc-50 偏暖) | 全局底层背景，温和护眼 |
| **Card Surface** | `bg-surface` | `#FFFFFF` | 主卡片、弹窗与浮层容器背景 |
| **Subtle Surface** | `bg-subtle` | `#F4F4F5` (Zinc-100) | 次级嵌套卡片、未激活胶囊背景、输入框底色 |
| **Primary Text** | `text-primary` | `#18181B` (Zinc-900) | 正文、大标题（**严禁使用绝对纯黑 `#000000`**） |
| **Secondary Text** | `text-muted` | `#71717A` (Zinc-500) | 副标题、时间戳、次要元数据说明 |
| **Border Line** | `border-whisper` | `#E4E4E7` (Zinc-200) | 1px 细线边界、卡片分割线、输入框边框 |
| **Dark Pill Fill** | `bg-zinc-900` | `#18181B` | 主胶囊操作按钮背景，文字纯白 `#FAFAF9` |
| **Wiki Tag Pastel** | `bg-emerald-50` / `text-emerald-700` | `#ECFDF5` / `#047857` | Wiki 页面标签、`[[双向链接]]` 胶囊徽标 |
| **Citation Pastel** | `bg-blue-50` / `text-blue-700` | `#EFF6FF` / `#1D4ED8` | RAG 问答逐句引用胶囊 `[1]`，段落定位高亮 |
| **Protected Amber** | `bg-amber-50` / `text-amber-800` | `#FFFBEB` / `#92400E` | 验证码/交易邮件受保护胶囊（不可归档红线标示） |
| **Archive Candidate** | `bg-rose-50` / `text-rose-700` | `#FEF2F2` / `#B91C1C` | 营销邮件待归档胶囊、删除确认操作 |

---

## 3. 排版体系 (Typography)

- **主字体 (Sans-Serif)**: 系统字体栈，无网络字体依赖
  - 实际取值（`tailwind.config.js` → `fontFamily.sans`）：`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
  - 标题注重字间距收敛：`tracking-tight`（`-0.02em`）；全局 `body` 字距为 `-0.01em`
  - 正文排版：`line-height: 1.6`（`leading-relaxed`），最大阅读宽度限制为 `max-w-3xl`
  - 如需引入 Geist Sans / Plus Jakarta Sans，须同时补 `@font-face` 或网络字体加载，并更新本节
- **等宽字体 (Monospace)**: `SF Mono`, `JetBrains Mono`, `monospace`（系统栈，无网络字体依赖）
  - 用于代码块、`doc_id` 散列值、段落偏移量、时间戳与快捷键指示（`<kbd>`）
- **禁止项**: 严禁在界面中使用默认 `Times New Roman`、`Georgia` 等老式通用衬线字体；严禁使用通用表情符号（Emoji）。

---

## 4. 核心组件规范 (Component Specifications)

### 4.1 胶囊按键系统 (Pill Buttons: `rounded-full`)

1. **主交互胶囊 (Primary Pill Button)**
   - 样式：`rounded-full bg-zinc-900 text-zinc-50 font-medium text-sm px-5 py-2.5 shadow-sm hover:bg-zinc-800 active:scale-[0.98] transition-all duration-150 inline-flex items-center gap-2`
   - 应用：发起提问、确认归档、开始导入文档。
2. **次级胶囊 (Secondary Pill Button)**
   - 样式：`rounded-full bg-zinc-100 hover:bg-zinc-200/80 text-zinc-800 font-medium text-sm px-4 py-2 active:scale-[0.98] transition-all inline-flex items-center gap-1.5`
   - 应用：过滤选项、取消、重试、模式切换。
3. **轮廓胶囊 (Outline Pill Button)**
   - 样式：`rounded-full border border-zinc-200 bg-white hover:bg-zinc-50 text-zinc-700 font-medium text-sm px-4 py-2 transition-all`
   - 应用：沉淀问答到 Wiki、导出 Markdown。
4. **胶囊标签与双向链接 (Capsule Badges & [[Wiki]] Links)**
   - 双向链接标签：`rounded-full px-2.5 py-0.5 text-xs font-medium bg-emerald-50/80 text-emerald-800 border border-emerald-200/60 hover:bg-emerald-100 hover:border-emerald-300 transition-colors inline-flex items-center gap-1 cursor-pointer`
   - 引用序号标签 `[n]`：`rounded-full px-2 py-0.2 text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200/60 hover:bg-blue-100 cursor-pointer ml-1 select-none`

### 4.2 圆角卡片系统 (Rounded Cards: `rounded-2xl` & `rounded-3xl`)

1. **主视图面板 (Primary View Card)**
   - 样式：`bg-white rounded-3xl border border-zinc-200/80 p-6 md:p-8 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.03)] transition-all`
   - 结构：顶部标题与右侧胶囊快捷操作区，中段主要内容区，底部状态与微元信息。
2. **内部嵌入项卡片 (Nested Item Card)**
   - 样式：`bg-zinc-50/70 hover:bg-zinc-50 rounded-2xl border border-zinc-100 hover:border-zinc-200 p-4 transition-all duration-150`
   - 应用：问答中的来源切片卡片（展示 chunk 摘要与偏移量）、邮件列表单项卡片、Wiki 目录列表项。
3. **浮动胶囊搜索框 (Floating Capsule Input Bar)**
   - 样式：`rounded-full bg-white border border-zinc-200/90 pl-5 pr-2 py-2 flex items-center shadow-[0_2px_12px_-2px_rgba(0,0,0,0.05)] focus-within:ring-2 focus-within:ring-zinc-900/10 focus-within:border-zinc-400 transition-all`
   - 内置：左侧极简搜索图标，中间无边框 Input，右侧放置胶囊提交按键。

---

## 5. 核心页面模块布局规范

### 5.1 顶部浮动胶囊导航 (Floating Pill Navigation)
- 居中悬浮胶囊栏：`rounded-full bg-white/90 backdrop-blur-md border border-zinc-200/80 p-1.5 shadow-sm inline-flex items-center gap-1`
- 四大核心 Tab 切换（图标一律使用 Lucide SVG 矢量图标，禁止 Emoji）：
  - **问答与综合 (Ask)**：知识检索与混合回答
  - **知识漫游 (Wiki)**：双向链接页面浏览与断链审计
  - **邮件分拣 (Mail)**：受保护邮件与人工归档门禁
  - **文档摄入 (Ingest)**：拖拽上传与双写进度

### 5.2 问答与引文溯源界面 (Ask View)
- **居中探索区**：输入框周围保持充裕的呼吸空间。
- **Wiki 优先卡片**：如果 Wiki 中已有稳定总结，以高亮卡片直接呈现，附带关联的 `[[Wiki条目]]` 胶囊。
- **补充细节与引用卡片**：
  - 回答段落中的每个 `[n]` 均为可交互胶囊。
  - 点击 `[n]`，右侧或下方即时弹出平滑淡入的“溯源切片卡片”（显示原文档名称、段落序号与原文片段）。
- **知识沉淀胶囊**：问答完成后，在卡片右上角提供 `[ 沉淀为 Wiki 页面 ]` 胶囊按键，一键调用 `archive_qa`。

### 5.3 Wiki 漫游界面 (Wiki Explorer View)
- **双栏圆角布局**：
  - 左侧（窄）：`index.md` 索引目录卡片，支持实时过滤与 Lint 状态（断链数、孤立页数警示胶囊）。
  - 右侧（宽）：Markdown 页面渲染卡片，标题、正文与 `## 来源` 严谨呈现。所有的 `[[词条]]` 自动编译为可点击的双向跳转胶囊。

### 5.4 邮件安全分拣界面 (Mail Triage View — 红线守护)
- **受保护邮件（Protected）**：
  - 顶部显眼区域陈列，带有琥珀色金底胶囊 `[ 保护: 交易/验证码 ]`，**不提供任何归档按键**，展示一句话摘要。
- **待归档营销邮件（Candidate）**：
  - 带有灰色/红色低饱和胶囊 `[ 营销推广 ]`。
  - **红线交互**：提供弹窗确认流程（Human Confirmation Modal），用户必须在弹出的圆角卡片中主动勾选并点击 `[ 确认归档选中的 N 封邮件 ]`，方可触发 LangGraph resume 恢复流。

---

## 6. 微交互与动效规范 (Motion & Tactile Interaction)

1. **按压力度微缩 (Tactile Press)**：
   - 所有按钮在 `:active` 状态使用 `transform: scale(0.98)`，过渡时间 `150ms cubic-bezier(0.16, 1, 0.3, 1)`。
2. **卡片悬浮升起 (Card Subtle Elevation)**：
   - 悬浮在卡片上时：微调边框明度（`border-zinc-300`）与微弱阴影（`shadow-[0_4px_16px_-4px_rgba(0,0,0,0.06)]`），严禁夸张的大距离位移。
3. **内容渐入过渡 (Staggered Fade-in)**：
   - 检索命中项或邮件列表采用阶梯淡入：`opacity: 0; transform: translateY(6px)` 平滑过渡到 `opacity: 1; transform: translateY(0)`。

---

## 7. 负向约束与反模式 (Banned AI Clichés)

- ❌ **严禁使用纯黑背景或纯黑字体**：禁止 `#000000`，统一使用 `#18181B`。
- ❌ **严禁使用 Emoji 代替图标**：所有图标必须使用清晰语义的 SVG 矢量图标（Lucide 或 Radix Icons）。
- ❌ **严禁直角或轻微圆角按钮**：所有按键统一使用 `rounded-full` 胶囊形态；卡片统一使用 `rounded-2xl` 或 `rounded-3xl`。
- ❌ **严禁厚重阴影与高斯模糊泛滥**：杜绝大半径黑色投影（如 Tailwind 的 `shadow-2xl`），只允许使用柔和超漫反射微阴影。
- ❌ **严禁 AI 流行语/假太空文案**：禁止在界面上出现 “Elevate your knowledge”、“Next-Gen AI” 等虚浮用语，保持工具的工程师严谨气质与极简克制感。
