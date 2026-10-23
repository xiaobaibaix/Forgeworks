# Forgeworks · 交接文档

> **续接入口（2026-10-21，当前有效）**：本文件下面的详细历史记录较长且部分过时；新会话先读本节，再按需查阅后续章节。工作目录为 `/Users/a260420/workspace/WorkBuddy/2026-10-20-14-48-15/Forgeworks`。用户要求“先都做完”，本阶段已扩展同步系统和生成管线，但仍有明确未完成项；不要把它描述成全部完成。

## 当前状态与续接顺序

### 已落地的范围

- **P2/P3 UE 同步**：`ue/fw_sync.py` 在 UE Editor 中导入 GLB 并回报结果；`ue/fw_registry.py` 扫描 AssetRegistry；Bridge 校验并记录报告；同步视图展示状态。实现已在工作区，未在 Windows + UE 5.8 实机验收。
- **P4/P5 3D 编辑**：稳定部件 ID、位置/旋转/缩放数值编辑、显隐、网格吸附、撤销/重做、重置；PBR 参数/颜色、贴图上传与移除、恢复风格及 GLB 导出路径已接入。缺少拖拽 gizmo、local/world 切换、选中部件聚焦高亮；GLB 材质因子与 Alpha 导出尚未回归验证。
- **P6 冲突处理**：Bridge watcher、冲突双版本留档、keep-tool / keep-disk / save-copy，以及 Blender 精修文件覆盖保护已实现。save-copy 在有工具基线时恢复工具版本，无基线时采用磁盘版本并更新 hash。真实 Blender 精修回灌及事件延迟仍待验收。
- **Q0–Q2 流水线**：新增 `tools/fw_pipeline.py`、`tools/fw_providers.py`、`js/pipeline.js`、`js/views/pipeline.js`、`css/pipeline.css`。有 graph schema、typed ports、DAG 检查、持久化、dirty 签名、节点图 UI、Tripo 文生图/图生 3D 提交和手动轮询。尚未实现多视角 API、自动轮询、retry/cancel/恢复、3D 预览；本次没有发远程请求。
- **Q3–Q5 仍不完整**：未实现 Blender 减面与风格重染、完整 GLB 门禁/流水线导出、历史版本选择/对比/回滚、批量队列执行。目前只保留 Provider 输出和任务历史，预算估算是按公开价目的静态估值。

### 安全与执行边界

- `tools/bridge_config.json` 是本地私密配置，API key 不进前端、不写入交接文档；状态接口只公开是否配置。`tools/bridge_config.example.json` 是可提交模板。
- 远程生成提交需要显式点击和二次确认；任务轮询/下载会访问 Provider 网络。除非用户之后明确要求生成，本交接续接默认只做本地工具实现，不调用付费生成服务。
- 远程 Windows/UE Editor 验收需要目标机器和工程；当前 macOS 工作区不能代替该验收。
- 用户明确要求**没有说“提交”就不得 commit**；也不得 push、tag 或改 remote。完成后停在工作区。

### 下一会话先做

1. 读 `AGENTS.md`（若存在）与用户提供的仓库约定。该约定要求写代码前阅读 `~/.Codex/docs/` 下四份 red8 / 子模块 / MVC / MVVM 规范；本次检查这些用户级文档不存在。继续工作时先重新确认是否已提供，缺失则沿用已确认的约定并避免臆造规范内容。
2. 查看 `git status --short`，保留所有现有未提交改动。当前工作树有大量源码新文件；`.codegraph/`、`.playwright-mcp/` 等未跟踪目录也在现场，未确认用途前不要清理。
3. 重点复核最近改动的 `tools/bridge.py`、`tools/fw_pipeline.py`、`tools/fw_providers.py` 的异常路径、历史任务增长和文件路径校验；特别留意 provider 输出下载失败后的任务状态持久化。只修复有证据的问题。
4. 按用户指示完成剩余本机可实现部分，再整理无法在本机验收的清单。**不要运行测试**，除非用户明确要求测试/验证；可在交付前做静态语法/差异检查并准确说明。
5. 若修改任何 `js/**` 或 `css/**`，按项目约定运行 `python3 tools/stamp.py` 更新 `index.html` 与 `tests/smoke.html` 版本戳。不要提交。

### 此工作区的已知验证边界

本交接整理时没有新跑测试套件或真实 Provider 请求。更早的基线冒烟结果见历史章节，不代表本次新增的同步/管线功能已通过端到端验收。交付时分别标注静态检查、自动化测试、浏览器验证和 UE/Blender 实机验收，不能互相替代。

---

> 写于 2026-10-21 10:58（GMT+8）。当前会话在此暂停。
> 用途：让下一个会话（或你自己）在**不看历史对话**的前提下，10 分钟内接上工作。

## 续接更新（2026-10-21 下午）

原文下方的任务状态是在本轮改动之前写的；以本节为准。

| 区域 | 当前工作区状态 | 尚未完成/限制 |
|---|---|---|
| P2 UE 导入 / P3 AssetRegistry 回扫 | 脚本、Bridge 校验回报、前端状态视图已实现；本机可做静态与 Python 校验 | 必须在 Windows + UE 5.8 Editor 中验收导入、保存和真实 AssetRegistry |
| P4 部件编辑 | 稳定部件 ID、变换/显隐覆盖、数值编辑、网格吸附开关、撤销/重做、重置、预览与 GLB 导出已实现 | 尚无 TransformControls 拖拽 gizmo、局部/全局模式和部件聚焦高亮 |
| P5 材质编辑 | PBR 数值、颜色、贴图上传/移除、恢复风格和导出保留材质已实现 | GLB 因子/Alpha 导出回归未验证 |
| P6 外部文件冲突 | Bridge watcher、两版本留档、keep-tool/keep-disk/save-copy、精修文件覆盖保护已实现 | 需做真实 Blender 编辑回灌与三秒事件延迟验收 |
| Q0 Provider | Tripo 服务端配置读取、text-to-image 与 image-to-model 提交/手动轮询、图片/GLB 安全下载、输出落盘已实现；界面提交前需逐次确认 | 本次未发出远程请求；当前未配置 key；未做本地 fake HTTP adapter 测试；Multiview API 和自动轮询尚未接入 |
| Q1 流水线数据层 | 图 schema、typed ports、DAG 环检测、图落盘、dirty 签名、本地 prompt/imageExport、Provider 任务状态已实现 | retry/cancel/进程恢复、真实本地 Blender 处理器仍待补 |
| Q2 节点图 | SVG 连线、节点卡、拖动、自动布局、连接/断开、参数与运行状态视图已实现 | 尚无重试/取消和 3D 输出预览；连接校验最终由 Bridge 执行 |
| Q3 | 本机 Tripo 输出有 GLB 格式/体积检查 | Blender 减面、PBR 风格重染、真实 GLB 门禁与最终同步 manifest 导出尚未实现 |
| Q4 | 重跑 Provider 节点会保留 taskId 命名的历史输出文件和任务记录 | 图上版本选取/并排对比与回滚 UI 尚未实现 |
| Q5 | 机器/物品/图标模板已分开；批量预估入口按当前公开价目计算 image/3D credits 与 USD 区间 | 单价会变；估算不是实时报价，最终以 Provider 返回的 credits_consumed 为准；尚未实现批量队列运行 |
| 材质贴图（AI） | 8 类材质的中性灰贴图生成、目录缓存、同步页管理 UI、3D 预览按材质映射、GLB 内嵌贴图均已实现；`tests/test_textures.py` 通过 | 未配置 Tripo key，未发出真实生成请求；GLB 内嵌用本地注入的 CanvasTexture 验证（1 image / 5 materials 全部带 baseColorTexture） |

运行时安全约束：API key 只放在 gitignore 的 `tools/bridge_config.json`；Provider 配置状态接口只返回是否配置；远程提交需二次确认。运行手动任务查询会联网，但不会新建生成任务。

批量额度推算采用 2026-10-21 查阅的 Tripo 官方公开值：文生图 5 credits；H3.1 无贴图图生 3D 20 credits、smart-low-poly 加 10 credits；1 credit = 0.01 USD。图标模板按 5–10 credits/张。单价可能变动，estimate 仅作启动前预算，最终以 Provider 的 `credits_consumed` 为准。

---

## 0. 一句话现状

工具本体（15 视图 + 风格引擎）**已完成可用**，上一轮冒烟测试 48 项。
「UE 资产同步」P0/P1 全链路与 P1.5 Blender 校验/缩略图已完成并验证；P2 UE 导入需 Windows 环境，后续 P3–P6 仍待开展。当前状态和限制见 §11–§12。

---

## 1. 项目在哪 / 怎么跑

| 项 | 值 |
|---|---|
| 本地路径 | `/Users/a260420/workspace/WorkBuddy/2026-10-20-14-48-15/Forgeworks` |
| 远端 | `git@github.com:xiaobaibaix/Forgeworks.git`（分支 `main`，已推送到 `f049f57`） |
| 仓库名 | Forgeworks —— 为 StellarEra（UE 5.8 体素宇宙工厂游戏）服务的内容设计工具 |
| 形态 | **纯前端静态站**，无构建步骤，无 npm 依赖（three.js 等以 UMD 脚本手放在 `js/vendor/`） |

### 启动方式

```bash
cd /Users/a260420/workspace/WorkBuddy/2026-10-20-14-48-15/Forgeworks

# 默认：界面 + Bridge 一起起（同步、Blender、管线都可用），端口 8787
python3 tools/serve.py

# 只要静态界面、不启 Bridge
python3 tools/serve.py --static
```

`serve.py` 现在直接交给 `tools/bridge.py` 执行，所以同源、只占一个端口。
必须走 HTTP，`file://` 下 `fetch('/api/...')` 连不上 Bridge。

### 测试

```bash
bash tests/run.sh        # headless Chrome 跑 48 项冒烟测试，输出 JSON 到 stdout
```

### 改完前端必做：打版本戳

浏览器缓存是这个项目历史上浪费最多时间的地方。改了任何 `js/**` / `css/**` 后：

```bash
python3 tools/stamp.py
```

它会自动递进版本号（当前为 `?v=20261021s`），并改写 `index.html` 和 `tests/smoke.html` 里全部 `src`/`href`。

---

## 2. 已完成的功能（可用状态）

### 2.1 内容设计本体 —— 15 个视图

导航分三组：**元素→物品→机器→配方→科技**（内容）／**美术资源**（风格→资产）／**输出与同步**（导出→同步）。项目工程由侧栏顶部项目 chip 进入独立「项目」页，不占导航位。

| 视图 | 文件 | 状态 |
|---|---|---|
| 元素 / 物品 / 机器 / 配方 / 科技 | `js/views/{elements,items,machines,recipes,techs}.js` | ✅ |
| 资产（物品 / 元素图标与模型） | `js/views/assets.js` | ✅ |
| 校验 / 物料平衡 / 求解器 / 依赖图谱 | `js/views/{validate,balance,solve,graph}.js` + `js/engines/*` | ✅ |
| 导出（CSV / Markdown / JSON） | `js/views/export.js` + `js/engines/csv.js` | ✅ |
| 3D 预览 + GLB 导出 | `js/engines/viewer3d.js` | ✅（three.js r147） |
| **风格引擎** | `js/core/style.js` + `js/data/styles.js` + `js/views/style.js` | ✅ |
| **项目** | `js/views/project.js` | ✅ 新建 / 打开 / 保存 + Bridge 状态 |
| **同步** | `js/sync.js` + `js/views/sync.js` | ✅ 资产生成 / 导出 / 状态核对；P0/P1 已实测 |

### 2.2 风格引擎（上一期刚做完，是本期同步功能的地基）

一句话：**风格是描述词、模型配色、图标、材质参数的唯一来源。**

- 唯一一套风格基线（`STYLE_PRESET`，`voxel-industrial`），含形态语言、表面处理、色板、呈现、材质映射、规格、负向词、图标参数。
- `fitColor(hex, role, st)` 按角色带强制校正（`STYLE_TONES`：structure / metal / accent / glow / hazard，色相负责区分功能，饱和度×明度负责统一风格）。
- 一致性检查 `styleCheck()` + 配色修正闭环 `stylePaletteFixTable()`。
- 存储：`localStorage['forgeworks.style.v1']`，与内容数据**分开**存。
- 调旋钮时清图标缓存（缓存键含 `overrides`）。

### 2.3 实测已验证的事实（别重复验证）

| 事实 | 数值 |
|---|---|
| GLB 可被 UE 导入 | 91208 字节 / 1 网格 / 5 材质槽 / 2.00×1.95m |
| Blender 位置 | 移动硬盘 `/Volumes/KingstonXS1000Media/app/Blender.app/...`，**5.2.0**，Bridge 已能探测到 |
| Blender 后台导入 GLB 校验 | 0.15s |
| Blender EEVEE 渲染缩略图 | 256×256，MC_DRILL 端到端约 1.87s |
| 三角面实测 vs 规格 | 2580 vs 规格上限 900（见风险 R14，已加门禁但**未实测**） |

---

## 3. 本期（同步系统）已做完的部分

设计计划书：`docs/sync-design.md`（776 行）、`docs/pipeline-design.md`（539 行）。**两份都还没经你评审**，§10 / §12 共 11 个决策问题待拍板（见 §6）。

### 3.1 `tools/bridge.py`（534 行）—— 单测全过 ✅

浏览器自身**不能**写项目目录、不能调 Blender、不能生成 `.uasset`，所以必须有个本地进程中转。

**启动**：`python3 tools/serve.py [端口]`（推荐，等同 `tools/bridge.py`），默认 **8787**。它同时是静态服务器（带 `no-store` + CORS）和 REST + SSE。

**目录约定**（关键，别改）：

```
<UE项目根>/
├── *.uproject
└── Forgeworks/            ← 项目根下，不进 Content/（避免 UE 扫到 .glb/.png 报警告）
    ├── _Source/           ← 中间文件：GLB / 图标 / 元数据
    │   ├── 机器/<中文名>/
    │   ├── 物品/图标/<中文名>/
    │   ├── 数据/
    │   └── 材质/<风格>/
    └── _Sync/
        └── manifest.json  ← 同步的真相来源
```

命名规范：`SM_` 静态网格 / `M_` 材质 / `MI_` 材质实例 / `T_` 贴图 / `ICON_` 图标 / `DT_` DataTable。

**API**：

| 方法 | 路由 | 作用 |
|---|---|---|
| GET | `/api/status` | Bridge 版本 + 已绑定项目 + Blender 探测结果 |
| GET | `/api/project/info` | manifest + 项目根 |
| GET | `/api/manifest` | 清单原文 |
| GET | `/api/events` | **SSE** 长连接（心跳 15s），文件变化/导出完成推送 |
| POST | `/api/project/bind` | 绑定（校验 `.uproject` + 建目录树 + 初始化 manifest） |
| POST | `/api/project/unbind` | 解绑 |
| POST | `/api/manifest/scan` | 扫磁盘，sha1 核对 → exported / missing / tampered |
| POST | `/api/export/asset` | 落盘（base64 → 文件 → 更新 manifest） |

**已单测通过**：绑定 → 建目录树 → 导出 → manifest 记录 → scan 三态转换（exported→missing→tampered→重导→exported）→ 非法输入拒绝（`../hack` 路径穿越、未知 kind）→ Blender 移动硬盘探测。

**安全**：拒绝 `..` 路径与非法 ID；配置文件 `tools/bridge_config.json` 与状态文件 `tools/.bridge_state.json` 已在 `.gitignore` 排除（密钥只在 Bridge，前端只见"已配置/未配置"）。

### 3.2 `js/sync.js`（307 行）—— 已写完 ✅

前端同步引擎。语法检查通过。

```js
const SYNC = { online, checkedAt, status, manifest, lastScan, log }
syncPing(force)                  // 2s 超时探测，不抛异常，离线优雅降级
syncBindProject(path) / syncUnbindProject()
machineContentHash(m)            // id/name/cat/footprint/tier/power
machineStyleHash(m)              // presetId + overrides + accentFor(m.cat)
machineSyncState(m)              // → none|exported|stale|missing|tampered|external
syncExportMachine(id, opt)       // 离屏 canvas → createViewer3D → toGLB + 等轴测图标 PNG → base64 → POST
syncExportAll(ids, onProgress)
syncScan() / syncWatchEvents(onEvent)
syncStateTag(state) / syncSummary()
```

**三把 hash 状态机**：`contentHash`（几何/语义变了要重导）+ `styleHash`（换风格/改配色要重导）+ Bridge 侧 `sha1`（文件被外部改过要告警）。

**质量门禁**（在 `syncExportMachine` 内）：从 `st.spec.machine` 正则 `(\d+)\s*~\s*(\d+)` 取上限（默认 900），产出 `gate = {triangles, budget, over, severe, sizeCm, materials}`。**阈值逻辑写了，但没在真实数据上跑过。**

**角色**：`syncExportMachine` POST `mesh`（.glb）、`preview`（等轴测 SVG 留档）和 `icon`（256×256 PNG，供 UE 使用）。旧记录没有 `icon` 时会被标记为 `stale`，可用「只导出待更新/缺失」一键补齐。

### 3.3 `js/views/sync.js`（245 行）—— ⚠️ 有语法错误，见 §4

同步面板：Bridge 状态卡（含 Blender 版本与路径）／项目绑定／资产导出（全部 / 只导出待更新 / 核对磁盘）／资产明细表（ID·名称·状态·三角面·材质槽·尺寸cm·风格·导出时间·操作）／操作日志。

### 3.4 已接入的其它改动

- `js/views/machines.js`：机器列表加「同步」列（仅 Bridge 在线且已绑定时显示）+ 顶部状态汇总条 + 跳转按钮。
- `js/main.js`：启动时异步探测 Bridge（离线不影响其余功能），并挂 SSE 监听。
- `index.html` / `tests/smoke.html`：加载 `js/sync.js`、`js/views/sync.js`（顺序：`sync.js` 在 `core/io.js` 之后；`views/sync.js` 在 `views/export.js` 之前）。

---

## 4. 历史问题：同步视图模板字符串未闭合（已解决，见 §11）

**现象**：冒烟测试 **47 / 48**，失败项：

```json
{ "name": "视图 sync", "ok": false, "detail": "EXCEPTION: renderSync is not defined" }
```

**根因**（已定位到行，不是疑难杂症）：`js/views/sync.js` 里模板字符串嵌套层数太多，最外层 `v.innerHTML = \`` 始终没被闭合。

具体是 **`renderSync()` 第 37 行** `${on ? \`` 打开的那一层，一直没关：

- 第 40 行 `${proj && proj.root ? \`…\` : \`…\`}` —— 正确闭合
- 第 64 行 `${proj ? \`…\` : ''}` —— 第 86 行 `` ` : ''} `` 正确闭合了这一层
- **但第 37 行那一层的 `` `} `` 没有写**

于是第 88 行起的「操作日志」被吞进了第 37 行的模板里，第 94 行的反引号关掉的是第 37 层，最外层还开着 → `;` 报 `Unexpected token`。

```
js/views/sync.js:94
  `;
   ^
SyntaxError: Unexpected token ';'
```

**修法（改 1 处，加 1 行）**：在第 86 行 `` ` : ''}` `` 之后、第 88 行 `${SYNC.log.length ? \`` 之前，补上第 37 层的闭合：

```js
    ${proj ? `
    …（资产导出 + 资产明细两张卡）…
    ` : ''}
    `}                              ← 加这两行：反引号 + 右花括号，闭合第 37 行的 ${on ? `…`}
                                    ← 更推荐：把这段拆成独立变量（见下）
    ${SYNC.log.length ? `
```

**更稳的修法**（推荐，防止再犯）：别再堆嵌套模板。`renderSync()` 里先把三块拼成独立变量，再放进外层：

```js
const htmlBridge   = on  ? `…状态卡…`   : `…离线指引…`;
const htmlBind     = on  ? `…项目绑定…` : '';
const htmlExport   = (on && proj) ? `…资产导出 + 资产明细…` : '';
const htmlLog      = SYNC.log.length ? `…操作日志…` : '';
v.innerHTML = htmlBridge + htmlBind + htmlExport + htmlLog;
```

**修完验证**：

```bash
/Users/a260420/.workbuddy/binaries/node/versions/22.22.2-6/bin/node --check js/views/sync.js
bash tests/run.sh          # 目标 48/48
```

其余改动过的文件 `node --check` **全部通过**（`js/sync.js`、`js/views/machines.js`、`js/main.js`、`js/core/style.js`、`js/core/color.js`、`js/data/styles.js`、`js/views/style.js`、`js/engines/viewer3d.js`、`js/engines/icons.js`）。

---

## 5. 下一步任务清单（按建议顺序）

任务编号沿用当前会话的编号。

| # | 任务 | 状态 | 说明 |
|---|---|---|---|
| — | **修 §4 的语法错误** | ✅ 完成 | 修复后 48/48；同时修复 Bridge 路由偏移与全局同名 hash 冲突，详见 §11 |
| 17 | **P0+P1 全链路实测** | ✅ 完成 | 详见 §11；同步页点击按钮直连 Bridge 仍受当前浏览器环境隔离限制 |
| 18 | P1.5 Blender 通道（校验 + 缩略图） | ✅ 完成 | `tools/fw_blender.py`；MC_DRILL 真实 GLB 验证通过，详见 §12 |
| 19 | P2 UE 导入（Interchange + 单位 scale + 保存 + 回写） | ⚪ 未开始 | **需要 Windows 实测**，Mac 做不了 |
| 20 | P3 反向加载（扫 AssetRegistry → 工具展示） | ⚪ 未开始 | `ue/fw_registry.py` |
| 21 | P4 3D 编辑（层级树 + TransformControls + 局部/全局 + 撤销） | ⚪ 未开始 | **工作量最大**，且要保住现有渲染不回归 |
| 22 | P5 材质编辑 | ⚪ 未开始 | |
| 23 | P6 实时与冲突（watchdog + 裁决界面） | ⚪ 未开始 | |
| — | 流水线 Q0：Provider 接入（Tripo） | ⚪ 未开始 | **等用户配 key**，见 §6 |

### 任务 #17 具体怎么做（下一步就是它）

**重要澄清**：`/tmp/FakeUEProject` 里现在有文件（`_Source/Machines/MC_DRILL/MC_DRILL.glb` + `ICON_MC_DRILL.png` + `_Sync/manifest.json`），但那批是**用 curl 直接打 Bridge API 做的单测产物**（manifest 里该条 `"meta": {}` 就是证据）。**前端 → Bridge 的链路一次都没真正跑过。**

步骤：

1. 修完 §4。
2. `python3 tools/bridge.py`（终端 A）。
3. 浏览器开 `http://127.0.0.1:8787/`，进「同步」页，绑定 `/tmp/FakeUEProject`。
4. 点「导出全部机器」（32 个）。观察：
   - `_Source/机器/<中文名>/` 下是否出现 `.glb` + `_preview.svg`
   - manifest 里每条的 `meta` 是否有 `contentHash`/`styleHash`/`gate`（**这是三把 hash 状态机第一次真正生效**）
   - 质量门禁报的三角面数是多少（对照规格上限 900，验证 R14 到底多严重）
5. 改一台机器的 footprint → 回列表看标记是否变 `stale (⟳)`。
6. 去磁盘删掉一个 `.glb` → 点「核对磁盘状态」→ 标记应变 `missing (✕)`。
7. 改风格旋钮 → 全部应变 `stale`。

---

## 6. 等你拍板的 11 个决策问题

这两组问题直接决定架构，**建议先回答再往下做**。原文在 `docs/sync-design.md §10` 和 `docs/pipeline-design.md §12`。

### 同步侧（sync-design §10）

| # | 问题 | 我的推荐 |
|---|---|---|
| Q1 | 同步"及时"到什么程度？(a) 点按钮 / (b) 改动后 2s 防抖自动写 / (c) 双向实时 | **(a)** 起步最可控 |
| Q2 | `Forgeworks/` 放项目根还是 `Content/` 下？ | **(a) 项目根**（UE 不会报无效资产、好 gitignore）→ 代码已按此实现 |
| Q3 | UE 侧导入由谁触发？(a) 你手动点 / (b) UE 内常驻监听自动导入 / (c) 无头 commandlet | **(a)** 零插件最简单 |
| Q4 | 3D 编辑粒度：只改整体 / 每个部件独立变换+层级 / 还能增删部件 | 你要的效果是**每个部件**，即 P4 一整期 |
| Q5 | 贴图怎么办？(a) 不生成纯色 / (b) 程序化噪声 / (c) Blender 手工 | **(a)** 法线贴图反而破坏体素风格 |
| Q6 | Blender 通道做哪一档？(a) 校验+缩略图 / (b) +.blend 生成 / (c) +精修回灌 / (d) 不集成 | **(a)** 已实测可行，能在进 UE 前拦住几何问题 |

### 流水线侧（pipeline-design §12）

| # | 问题 | 我的推荐 |
|---|---|---|
| Q1 | 首个 Provider？(a) Tripo / (b) Meshy / (c) 国内文生图+Tripo / (d) 先 LocalFallback | **(a) Tripo**（免费额度 ≈ $20，够 32 个建筑各试一遍） |
| Q2 | 三视图端到端还是拼两家？ | **(a)** Tripo multiview 端到端，一致性最好 |
| Q3 | UI 先简化版（纵向步骤条）还是直接完整画布？ | **(a)** 先简化版，快 1 周级见效 |
| Q4 | 生成模型的贴图定位？(a) AI 贴图但强制过 styleApply / (b) 弃贴图纯色 / (c) 两档都留 | **(a)** 有细节又成套 |
| Q5 | 花费上限？（单资产 / 单次批量 / 月度） | **待你给数** |

> 你上一轮的指令「**先不真实的生成，暂时只做工具，你做好以后我再连大模型生成然后进行测试**」等价于 Q1 选 (d) LocalFallback。所以流水线侧目前**接口留好但不调用**，等你配 key。

---

## 7. 踩过的坑（别再踩）

| 坑 | 解法 |
|---|---|
| **浏览器缓存**让人以为代码没改 | `?v=` 版本戳 + `tools/stamp.py` + Bridge 发 `no-store`。`no-store` 只对未来响应生效，老缓存还得靠版本戳 |
| three.js r147 默认 `ColorManagement.legacyMode = true` → **白塑料感** | 显式设 `false`；配 `PMREMGenerator`+`RoomEnvironment`+`ACESFilmicToneMapping` |
| 低段数圆柱/圆锥被平滑成圆顶 | `flatShading` 在 `seg ≤ 8` 时开 `true`（box/prism 恒 true） |
| `file://` 下 ES module 被 CORS 拦截、`history.replaceState` 抛 `SecurityError` | 必须走 HTTP |
| 图标换风格不刷新 | 缓存键加入 `styleCacheTag()`（presetId + overrides） |
| 配色修正表"修了还剩 20 个色不合规" | 根因是固定把第一个色当强调色。改成 `assignPaletteRoles()` 按**饱和度**找最艳的作强调色，其余按明度分档 |
| 一致性检查误报"等轴测面色不合规" | left/right 面是人为压暗的面色（差 22~27 明度），只查 top 面 |
| **`.uasset` 不能由浏览器生成**（硬限制） | 只能生成 GLB/PNG，UE 侧再导入 |
| glTF 1 unit = 1m，UE 1 unit = 1cm | 必须 `import_uniform_scale=100`（风险 R1） |
| glTF **Y-up**，UE/Blender **Z-up** | Blender 导入自动换算（已实测确认） |
| UE 5.8.3：`AssetTools.import_asset_tasks` 在 commandlet 崩溃 | 改用 `InterchangeManager`（R3） |
| UE 5.8.3：自动导入**不再自动保存** | 必须 `EditorAssetLibrary.save_directory(..., only_if_is_dirty=False, recursive=True)`（R2） |
| Blender 在移动硬盘，盘符会变 | 多候选路径 + `glob('/Volumes/*/app/Blender.app/...')` + 10 分钟缓存 |
| 含 `blender` 的复合 bash 命令会被安全策略拦截 | 先 Write 脚本文件，再单独 Bash 执行 |
| headless Chrome 截图 | 需 `--use-gl=swiftshader --enable-unsafe-swiftshader`；`--virtual-time-budget` 与 swiftshader 同时用会卡死；截图每次要新建 `--user-data-dir` |

---

## 8. Git 状态（**尚未提交**）

```
当前工作区已包含 §11–§12 所列的同步与 Blender 实现文件；具体状态以 `git status --short` 为准。
```

此前同步实现尚未提交；当前工作区继续保留未提交状态。

---

## 9. 文件速查

```
Forgeworks/
├── index.html                  入口，脚本顺序有讲究（见 §9.1）
├── README.md                   426 行，含架构说明
├── css/                        样式
├── js/
│   ├── core/    config.js  color.js  state.js  lookup.js  style.js  io.js
│   ├── data/    styles.js  seed.js  prompts.js
│   ├── engines/ icons.js  viewer3d.js  validate.js  solver.js  balance.js  csv.js
│   ├── ui/      table.js  router.js  editor.js
│   ├── views/   style.js elements.js items.js machines.js recipes.js
│   │            techs.js assets.js validate.js
│   │            balance.js solve.js graph.js sync.js export.js
│   ├── sync.js                 同步引擎（307 行）
│   └── vendor/  three.min.js OrbitControls RoomEnvironment
│                GLTFExporter BufferGeometryUtils
├── tools/
│   ├── bridge.py               534 行，Bridge 服务
│   ├── bridge_config.example.json
│   ├── serve.py                纯静态服务（无同步）
│   ├── stamp.py                版本戳
│   ├── import_datatables.py    UE 侧 DataTable 导入
│   └── DT_*.csv                导出的 DataTable 样例
├── docs/
│   ├── sync-design.md          776 行，同步设计计划书（待评审）
│   ├── pipeline-design.md      539 行，流水线设计计划书（待评审）
│   ├── ue-import.md            314 行，UE 导入踩坑记录
│   ├── sample-content.json
│   └── HANDOFF.md              ← 本文
└── tests/
    ├── run.sh                  headless 冒烟测试
    ├── smoke.html              48 项测试页
    └── _dumpglb.html           导出真实 GLB 取样本（给 Blender 验证用）
```

自研 JS 约 6800 行（不含 vendor）。

### 9.1 `index.html` 脚本加载顺序（**有依赖，别乱动**）

1. `core/config.js` → `core/color.js` → `data/styles.js`（**styles 必须在 style 之前**）
2. `data/seed.js` → `data/prompts.js`
3. `core/state.js` → `core/lookup.js` → `core/style.js`
4. `vendor/three*.js` 全家
5. `engines/icons.js`（**color.js 必须在它之前**）→ 其余 engines
6. `core/io.js` → `sync.js`
7. `ui/*` → `views/*`（`views/style.js` 在最前，`views/sync.js` 在 `views/export.js` 之前）
8. `main.js`

注意：风格相关的函数可以在**更早加载的文件里调用**，只要调用发生在**函数体内**（运行时才求值），不要在文件顶层立即执行。

---

## 10. 恢复工作的第一条命令

```bash
cd /Users/a260420/workspace/WorkBuddy/2026-10-20-14-48-15/Forgeworks
/Users/a260420/.workbuddy/binaries/node/versions/22.22.2-6/bin/node --check js/views/sync.js
```

然后按 §4 改，跑 `bash tests/run.sh` 到 48/48，接着做 §5 的任务 #17。

---

*文末备注：本文最初写于续接工作开始前；后续进展见 §11–§12。*

---

## 11. 2026-10-21 续接记录

- 修复 `js/views/sync.js` 中未闭合的 `on` 条件模板字符串；`node --check` 通过。
- 修复 `tools/bridge.py` 中 GET/POST 路由截取偏移：`/api/` 后应从索引 5 截取，否则路由名保留前导 `/`，所有 API 均无法匹配。
- 修复 `js/sync.js` 的 `syncHash` 全局命名冲突：`js/ui/router.js` 同名函数覆盖了数据哈希实现，导致 hash 缺失并把 URL 改成 `#[object Object]`。数据哈希函数改名为 `syncDataHash`。
- `tests/smoke.html` 浏览器运行结果：48/48 通过，0 个运行时错误。`bash tests/run.sh` 在当前执行环境无法启动 Chrome（进程异常退出），故通过浏览器测试页直接读取结果验证。
- 浏览器侧生成 32 台机器的 GLB payload：32/32 成功，共约 3.49 MB；所有 payload 都带有效 `contentHash` / `styleHash`。通过同机 API 测试 harness 提交真实 Bridge 后，`/tmp/FakeUEProject` 的 manifest 有 32 项，每项均写入 GLB、预览和 hash 元数据。
- Bridge 状态、项目清单和扫描 API 正常。按计划删除 MC_DRILL 网格后扫描返回 `missing`；用浏览器生成的 payload 恢复后再次扫描返回 `exported`。
- 前端状态机验证通过：未改内容为 `exported`，改占地或切换风格为 `stale`，恢复后回到 `exported`。但当前浏览器测试页面由静态服务器提供，工具无法将它与 Bridge 端口直连，因此**尚未验证在同步页直接点击按钮完成同源导出**。
- 质量门禁实测：20/32 台机器超过预算，均超过 1800 的严重阈值；最大 6032 三角面。门禁已把数据写入导出元数据并标红，按设计继续导出。
- 前端资源版本戳先递进到 `20261021g`；P1.5 完成时到 `20261021h`，审查修正后当前为 `20261021i`。
- 用户级规范文件 `~/.Codex/docs/` 在当前机器不存在，未能读取。
- 浏览器资源版本戳已递进到 `20261021i`。

## 12. P1.5 Blender 通道（2026-10-21）

- 新增 `tools/fw_blender.py`：以 Blender 后台模式导入 GLB，校验网格数、材质槽、包围盒和落地位置，并用 EEVEE 输出 256×256 PNG 缩略图及 JSON 报告。
- Bridge 为机器 GLB 添加串行后台队列，完成校验后把缩略图写入 `_Source/机器/<中文名>/<ID>_preview.png`（按 manifest 的 `sourceDir` 定位），并在 manifest 记录状态、校验报告、大小和哈希；新增 `/api/thumbnail/machine/<ID>` 图片端点。失败或未安装 Blender 时 manifest 会保留相应状态。
- 同步面板增加 Blender 状态与缩略图列。浏览器注入状态验证了缩略图展示路径。
- 新增 `tests/test_fw_blender.py`，含 Blender 报告测试及 Bridge 异步队列/缩略图 API 集成测试；运行结果 2 项通过。
- 真实 `MC_DRILL` GLB 验证：有效、1 网格、5 材质槽、尺寸约 2.00×1.95×2.79 m、2580 三角面；缩略图 API 返回 `image/png`，端到端约 1.87 秒。
- 完整浏览器冒烟：48/48 通过，运行时错误 0。`node --check`、Python 编译检查和 `git diff --check` 均通过。
- P1.5 尚未在 Windows/UE 中验证；P2 UE 导入、P3 反向加载及其余后续项仍待开展。三角面超预算问题见 §11。
- 用户明确禁止未授权提交；交接文档原 §8 中建议提交的命令不适用，所有更改留在工作区，未提交、未推送。
- 后续只读代码审查发现并修正：EEVEE 引擎标识按 Blender 可用枚举兼容选择；后台任务绑定提交时的项目根目录，manifest 网格哈希匹配后才替换正式缩略图，异常会记录失败并继续消费队列；同步面板转义来自 Bridge/manifest 的动态文本，避免 HTML 注入；行级导出共用批量导出的忙碌锁；缩略图缓存键改用文件哈希。
- 复验：`python3 tests/test_fw_blender.py -v` 在提权环境 2/2 通过（普通沙箱不允许绑定回环端口且 Blender Metal 初始化会崩溃）；Node/Python 语法检查和 `git diff --check` 通过；浏览器冒烟页 48/48、runtimeErrors 0。恶意 HTML 字符串验证以文本显示，未创建注入节点、未执行事件处理器。

## 13. 材质贴图（AI）通道（2026-10-21）

**目的**：GLB 原先只有 5 个纯色 PBR 材质槽（`images: 0 / textures: 0`）。本期给每类材质生成一张细节贴图，导出时内嵌进 GLB；颜色仍由风格色板决定。

- `tools/fw_textures.py`：8 类材质规格（`concrete / steel / steelDark / steelLite / glass / rust / clean / ceramic`）、中性灰提示词、目录读写（`_Source/材质/<风格>/textures.json`）、提交/轮询/落盘、路径与体积校验（单张 ≤ 20 MB）。
- `tools/bridge.py`：`GET materials/textures`、`GET materials/texture/file`、`POST materials/texture/submit`、`POST materials/texture/poll`。提交要求同源回环 + `confirmRemote:true`，并推 `texture.progress` SSE。
- `js/engines/material-textures.js`：拉取目录、把 AI 图压成中性明度（`fwNeutralCanvas`）、派生粗糙度、装载为 `THREE.CanvasTexture`（JPEG 内嵌）。同一套图可被任何风格复用。
- `js/engines/viewer3d.js`：材质按 `mat.key` 挂 `map` / `roughnessMap`；目录异步到达后 `applyTextures()` 刷新，导出前在 `syncExportMachine` 等 `fwTexturesReady()`，GLTFExporter 才能把已解码的贴图写进 GLB。
- `js/views/sync.js`：新增「材质贴图（AI）」卡片——逐材质状态、缩略图、生成/重新生成、生成全部缺失；有排队/生成中任务时每 3 秒轮询一次。
- 启用方式：项目页「生成服务 · Provider」填写 Tripo API Key（写入 gitignore 的 `tools/bridge_config.json`，即时生效）；也可手改文件。未配置时卡片显示指引并禁用生成按钮。
- `tests/test_textures.py`：9 项通过（目录归一化/丢未知键/丢文件、路径穿越拒绝、提示词、提交去重与 force、轮询成功/失败落盘、文件端点）。
- 验证边界：未配置 key，未发真实生成请求；GLB 内嵌用页面内注入的 64×64 CanvasTexture 验证——1 image、1 texture、5 个材质全部带 `baseColorTexture`，`mimeType: image/jpeg`。

### 13.1 火山方舟 Ark Provider（图像 / 3D）（2026-10-23）

- `tools/fw_providers.py` 按节点 `params.provider` 选择 `tripo` / `ark`；Pipeline 提交时若标注的 provider 未配置，回退到已配置的一项（材质贴图仍固定 Tripo）。
- Ark 图像：`POST /api/v3/images/generations`，模型 `doubao-seedream-5-0-pro-260628`，同步返回图片 URL。
- Ark 3D：`POST /api/v3/contents/generations/tasks`，模型 `doubao-seed3d-2-0-260328`；`content` 用 `image_url`（data URI 或 https）传图，可选 `text`。轮询 `GET /api/v3/contents/generations/tasks/{id}`，成功后 `content.file_url` 是 ZIP，下载后解出 GLB。
- 下载白名单扩展 `*.volces.com`；ZIP 内 GLB 仍做 magic 与声明长度校验。
- 启用方式：项目页「生成服务 · Provider」填写 Ark API Key、Endpoint 与两个模型名（写入 gitignore 的 `tools/bridge_config.json`，即时生效）；也可手改文件。`endpoint` 可空，默认 `https://ark.cn-beijing.volces.com/api/v3`。
- 配置接口：`GET /api/providers` 只回 `configured`/`endpoint`/模型名，永不回传密钥；`POST /api/providers/save` 仅接受本地同源页面，`clearKey:true` 删除已存 Key，Endpoint 必须是 https 火山域名，文件落盘后权限 0600。
- cc-switch 导入：`POST /api/providers/ccswitch/import` 只读 `~/.cc-switch/cc-switch.db`（`mode=ro`），只挑 `app_type='claude'` 且 `env.ANTHROPIC_MODEL` 含 `seedream` / `seed3d` 的火山配置；候选列表 `GET /api/providers` 的 `ccswitch` 字段只给名称、模型与 Key 末四位（`…504e`）。导入后写入 ark 的 key / endpoint / 对应模型，不会覆盖 tripo。
- 连通性测试：`POST /api/providers/test` 做只读鉴权探测，不产生计费任务。Ark 用 `GET {endpoint}/models`（200 通过 / 401 失败）；Tripo v3 没有只读账户接口，探测不存在的任务 `/v3/tasks/00000000-0000-0000-0000-000000000000`，返回 404 视为鉴权通过、401 报 Key 无效。

## 14. 资产七方面 + 图层化预览 + 管线阶段（2026-10-21）

**用户要求**：白模（几何）、材质、UV、LOD、碰撞体、动画、元数据这七项，既要在生成管线里各是一个阶段，也要在 3D 展示里逐项可见、可开关（例如临时去掉材质、去掉法线贴图）。

**新增 `js/engines/asset-layers.js`**（`index.html` 与 `tests/smoke.html` 都要在 `viewer3d.js` 之前加载）：

- `normalizeLayers()` / `fwLodPlan()` / `fwCollisionBox()` / `fwAssetAspects()` / `fwLayerSummary()`。
- LOD 是确定性的“按部件体积隐藏”预览：L1 藏 35%、L2 藏 60%，导出恒为 L0。
- 碰撞盒由 footprint + 自动高度（`collisionHeight` 可覆盖）生成，不参与渲染导出。

**`js/engines/viewer3d.js`**：

- 预览态 `state.layers`（clay / albedo / roughness / normal / wireframe / uv / collision / particles / animations / lod / collisionHeight）只影响显示；`baseMaterial` 保真材质，`exportMaterial(entry)` 在导出时重建真材质，所以任何图层开关都不会污染 GLB。
- 新增浮动「资产图层」面板、LOD 三档下拉、碰撞高度输入，以及顶部的七方面摘要条；API 增加 `getLayers / setLayer / getLodInfo / getAspects / getCollision`。
- GLB `extras.forgeworks` 增写 `uv / lod / collision / layers`。
- 顺带修复既有导出 Bug：按部件覆盖材质时桶键是 `role + '_' + id`，旧代码写死 `buckets[role]` 会抛错。

**`js/pipeline.js` + `tools/fw_pipeline.py`**：

- 起始图扩为 11 节点：`prompt → image → model → style → uv → lod → collision → animation → metadata → validate → export`。
- `PIPELINE_LOCAL_STAGES = ['uv','lod','collision','animation','metadata']`，浏览器端用 `fwAssetAspects()` 推导并写 `source: 'forgeworks-ui'`。
- Python 无法复算浏览器签名，因此 `save_graph` / `execute_local` 对 `source == 'forgeworks-ui' && state == 'done'` 的结果原样保留；未推导时该节点标 `blocked` 并提示回工具里运行。
- 节点卡显示阶段摘要（UV 通道 / LOD 三档件数 / 碰撞尺寸 / 动画部件与类型 / 元数据格式）。

**`tools/fw_blender.py` + 测试**：

- 报告新增 `uvPresent / uvLayers / imageCount / images / materialDetails / normalMapSlots / animationCount / forgeworks`；缺 UV 不判失败。
- 新增 `tests/test_fw_pipeline.py`（3 项），`tests/test_fw_blender.py` 补七方面断言。

**验证**：Python 21 项通过；冒烟页 54/54、runtimeErrors 0；浏览器实测管线 11 节点，运行后五个本地阶段 `done`（如 `L0 20 件 / L1 14 件 / L2 9 件`、`2×2.886×2 m`、`3 件 · pulse、spin、bob`），远程节点在 Bridge 离线时按预期 `blocked`。版本戳 `?v=20261021zzzc`。未提交。

### 端口与拖拽连线（同日补充）

- 端口表抽成 `PIPELINE_PORTS`（`js/pipeline.js`），与 Python `NODE_TYPES` 一一对应；节点卡两侧渲染圆点，左侧输入、右侧输出。
- 连线路由：输出圆点 `pointerdown` 起线 → 跟随鼠标 → 松开在输入圆点（或目标卡片任意位置，自动选第一个兼容端口）。拖拽中高亮所有同类型输入端口，`Esc` 取消。
- 语义：**一个输出可接多个下游**（fan-out，JS 与 Python 均允许）；**一个输入端口只保留一条连线**，新连线替换旧的；自连和成环在客户端直接拒绝（`pipelineReachable`），不再等 Bridge 报错。
- 连线端点按端口几何计算（`pipelineEdgePath`），替代原先写死的 `+225/+75`；原来的下拉框已移除。
- 验证：浏览器实测拖拽 `uv → collision`（替换原 `lod → collision`）、`uv` 同时连 `lod` 与 `collision`（多输出）、拖到卡片空白处、`Esc` 取消、不兼容端口拒绝均符合预期；冒烟页新增 1 项「流水线端口：多输出与单输入替换」，55/55。版本戳 `?v=20261021a`。未提交。

### 交互闪烁、画布缩放与拖放（同日补充）

- **闪烁根因**：每次保存都调 `renderPipelineView()` 重建 `view.innerHTML`，节点 DOM、SVG、滚动位置全部销毁重建。
- **修复**：`pipelineSave({quiet:true})` + `pipelinePaintChrome()`，只重画 SVG 连线、统计行（`#pipelineMeta`）和连线列表；拖动节点结束、连线、断开、参数修改、选中节点都不再重建 DOM。全量渲染仅用于切换资产、建模板、增删节点、运行，且会继承当前缩放与滚动位置。
- **缩放**：`.pipeline-zoomer` 按 `画布尺寸 × zoom` 撑开滚动范围，`.pipeline-canvas` 用 `transform:scale`；滚轮以光标为锚点（0.45–1.8），工具条百分比按钮复位到 100% 并回到左上角。
- **平移**：画布内按住右键拖动（已 `preventDefault` 掉右键菜单），拖动中加 `.panning` 光标；画布视口改为 `height:calc(100vh - 300px)`，纵横方向都在画布内部滚动。
- **调色板拖放**：按下节点按钮即拖出 ghost，松手落在画布内按落点居中新建（`pipelineCanvasPoint` 换算到画布坐标），单击按钮仍按默认位置新增。
- **验证**：157% 缩放下光标锚点误差 <1px、右键拖动平移、拖放落点与 `node.x/y` 完全一致；拖动/连线/改参数/选中期间 `.pipeline-canvas` 元素身份不变（零重建）。冒烟页 55/55、runtimeErrors 0；Python 4/4。版本戳 `?v=20261021c`。未提交。

### 节点堆叠层级与删除失效（同日补充）

- **现象**：从调色板拖进来的节点与已有节点重叠时删不掉；相邻节点的连接圆点还会浮在更前面卡片的上方。
- **根因**：`.pipeline-node` 没有 `z-index`，未形成堆叠上下文，而 `.pipeline-port` 的 `z-index:2` 直接参与画布层级——任何卡片的端口都会盖住所有卡片。端口压住别人的「删除」按钮时，点击被端口接管（开始拉线），删除永远不触发。
- **修复**：卡片 `z-index:1` 自成一堆叠层，端口只在卡片内部浮起；选中卡片 `z-index:3`，拖动中加 `.dragging` 提到 `z-index:4`。
- **验证**：构造「A 的输出端口正好压住 B 的删除按钮」，修复前 `elementsFromPoint` 命中端口，修复后命中按钮；真实鼠标拖入节点后点击删除可移除；重叠卡片截图中端口不再浮到前景卡片上。冒烟页 55/55、runtimeErrors 0；Python 4/4。版本戳 `?v=20261021e`。未提交。

## 15. Forgeworks 项目工程 / UE 导出目标分离（2026-10-22）

**用户要求**：真正存各种资源的应是一个独立「项目工程」（类似商业软件），而不是直接写进 UE 项目目录；导出时才把 UE 用得到的部分复制过去。描述词、生成管线、预览等 UE 不用的东西留在项目里。需要「新建项目 / 打开项目 / 导出到 UE」。

### 两层目录

```
<Forgeworks 项目>/
├── forgeworks.project.json     项目标记（名称、创建时间）
├── project.json                全部内容（主存储；localStorage 仅离线兜底）
├── _Source/{机器,物品/图标,材质,数据}/
└── _Sync/{manifest.json,tool_versions,conflicts}/

<UE 项目>/Forgeworks/
├── _Source/机器/<中文名>/<ID>.glb       只复制 mesh 角色
├── _Source/机器/<中文名>/<ID>_icon.png  只复制 icon 角色
├── _Source/物品/图标/<中文名>/<ID>.png   只复制 icon 角色
└── _Sync/{manifest.json,ue_assets.json}
```

- 目录名用资产显示名（`meta.name`），同名/非法字符时追加 `-<ID>`，最终回退到 `<ID>`；目录内文件名与 UE 对象名（`SM_<ID>`）仍用稳定 ASCII。`manifest.assets[<ID>].sourceDir` 是目录唯一真相。

- `project.json` 由 Bridge 读写；内容变更防抖 400ms 回写，`contentRoot === 项目根` 才允许写，避免旧数据覆盖新项目。
- **导出到 UE** 只复制机器 GLB/图标 PNG、物品图标 PNG + 导出清单；`preview` / `thumbnail` / `pipeline` / `prompt` 不复制。`meta`（contentHash/styleHash/sizeCm/iconHash）原样带去，用于 `stale` 判定与尺寸校验。
- 导出状态机在项目层比较：项目 `contentHash/styleHash` vs UE manifest → `none | stale | exported`；同步表新增 UE 列。
- **旧版迁移**：旧状态指向 `<UE>` 时，项目根迁移为 `<UE>/Forgeworks`（补写项目标记），且**不自动设 UE 目标**（导出根等于项目根会自拷贝）。`set_ue_target` / `publish_to_ue` 均拒绝相同目录。
- UE 侧 `ue/fw_registry.py` 改为本地优先：先找 `PROJECT_ROOT/Forgeworks`，找不到再问 `/api/project/info`。

### Bridge API

`GET /api/project/info`、`GET|POST /api/project/content`、`POST /api/project/bind`（原 `bind_project`，语义改为项目根）、`POST /api/project/create`、`POST /api/project/ue-target`、`POST /api/project/publish`、`GET /api/ue/manifest`。**升级后必须重启 `tools/bridge.py` 才会出现新路由。**

### 前端

- `js/sync.js`：`SYNC.projects / content / contentRoot / ueManifest`，`syncCreateProject / syncOpenProject / syncSetUETarget / syncPublishUE / syncUnbindProject`，内容防抖保存与 SSE 重载。
- `js/views/sync.js`：「Forgeworks 项目」卡（打开态/新建/打开/最近项目）、「UE 导出目标」卡（设置/更换/导出全部/只导出待更新）、资源表 UE 列。
- `js/core/state.js`：保存时优先写项目，失败回退 localStorage。
- 侧栏底部项目 chip 显示当前项目与 UE 就绪状态。

### 测试与验证

- 新增 `tests/test_bridge_projects.py`：独立项目创建/打开、旧版迁移不设 UE 目标、旧版 UE 根不能当导出目标、发布机器 GLB+图标、物品图标导出+发布。
- `tests/test_fw_blender.py` 改用 `open_project`。Python 全套通过；`node --check` 通过。
- Playwright 隔离环境实测（8788 端口 + `/tmp` 工程）：新建项目 → 设置 UE 目标 → 导出 MC_HAND（项目内得到 GLB + SVG/PNG 预览）→ 发布到 UE；UE 目录只有 `MC_HAND.glb` 与 `_Sync/manifest.json`，无 preview/pipeline/prompt；表格 UE 列变为「已导出」，汇总显示 `已导出 1 · 待导出 0 · 未导出 31`。
- 隔离环境已清理；用户本机 8787 的 Bridge 需重启才能加载新路由。未提交。

## 16. 物品图标导出（2026-10-22）

**用户要求**：物品图标同样要用在 UE 里，必须随项目保存并导出到 UE。

- **项目侧**：`js/sync.js` 新增 `iconPngB64`（`iconURL` → Image → canvas → 透明底 256×256 PNG）、`syncExportItem`、`syncExportAllItems`，POST `kind: 'item'` 到 `/api/export/asset`；Bridge 落到 `<项目>/_Source/物品/图标/<中文名>/<ID>.png`。自定义上传图标与自动生成 SVG 走同一条路径。
- **状态**：`itemIconHash` 覆盖自定义图标、类型/颜色与当前风格；`itemSyncState` / `itemUEState` 与机器同样的 `none | stale | exported` 状态机。
- **UE 发布**：`fw_project.UE_EXPORT_ROLES` 改为按类型声明（machine→mesh，item→icon），`publish_to_ue` 默认选两类资产；角色缺失分别报错/跳过。（机器图标在 §17 补入 `machine→mesh+icon`。）
- **清单合并修复**：部分发布（如只发待更新的图标）原先会用本次结果覆盖 UE manifest，导致之前发布的机器记录消失；现改为读旧清单后合并再写。
- **UI**：「项目资源」新增物品图标区块（导出全部 / 只导出待更新 + 状态汇总）；UE 卡按钮改为「导出全部资产（机器 N · 图标 M）」，待更新选择与汇总都包含物品；资产明细表新增类型列并列出物品图标。
- **验证**：Python 41 项全过（新增物品发布、缺图标报错、部分发布不清旧记录、Bridge 导出+发布图标）；冒烟页 55/55。Playwright 实测 75 张图标写入项目并发布到 UE，UE manifest 107 个资产（32 机器 + 75 图标），目录只含 PNG/GLB/清单。版本戳 `?v=20261022j`。

## 17. 机器图标导出（2026-10-23）

**用户要求**：机器不能只导 GLB，图标也要给 UE。

- **项目侧**：`syncExportMachine` 用 `isoPreview(m, 0, 256)` 生成与界面同视角的 SVG，再经 canvas 渲染成透明底 256×256 PNG，作为 `icon` 角色写入 `<项目>/_Source/机器/<中文名>/<ID>_icon.png`；`preview` SVG 仍留档。
- **抽取复用**：`iconPngB64` 与新的 `machineIconB64` 共用 `imagePngB64(src, size, label)`（Image → canvas → PNG base64）。
- **状态**：`machineSyncState` / `machineUEState` 增加 `hasAssetFile(rec, 'icon')` 判断；旧记录没有图标即标记 `stale`，可一键补导。
- **UE 发布**：`fw_project.UE_EXPORT_ROLES['machine'] = ('mesh', 'icon')`，mesh 仍为必需角色，icon 缺失时只发 GLB（兼容旧资产）。
- **UI**：同步页文案改为「机器 GLB/图标 PNG、物品图标 PNG 与清单」。
- **测试**：`test_fw_project` 发布用例断言 `M1.glb` 与 `M1_icon.png` 都到 UE、preview/pipeline 不复制，并新增「无图标旧资产只发 GLB」用例；Python 42 项全过。

## 18. 中文资源目录（2026-10-23）

**用户要求**：导出的资产文件夹用中文，而不是英文/ID。

- **目录布局**：项目与 UE 导出目录统一为 `_Source/机器/<中文名>/`、`_Source/物品/图标/<中文名>/`、`_Source/元素/<中文名>/`、`_Source/数据/`、`_Source/材质/<风格>/`；UE 内容路径同步为 `/Game/Forgeworks/机器/<中文名>`。
- **元素资产**：每元素只含 PNG 图标（`<ID>.png`，256×256 透明底，自动生成或自定义），不参与 GLB；可在「生成管线」用图标模板产出概念图，管线存档落在元素自己的文件夹；与物品一样只镜像到磁盘，不导入 UE 内容浏览器。
- **命名**：`meta.name` → NFC、压缩空白、替换 `/\:*?"<>|` 与 `#%&'{}~` 等非法字符；空名、Windows 保留名、超长名回退到资产 ID；同分类重名追加 `-<ID>`，仍冲突再追加序号。
- **不变量**：目录内文件名保持 `<ID>.glb` / `<ID>_icon.png` / `<ID>_preview.svg`；UE 对象名保持 `SM_<ID>`，回报与注册表都从对象名解析 ID，不依赖目录名。
- **真相来源**：`manifest.assets[<ID>].sourceDir`。Bridge 的扫盘、冲突归档、Blender 队列、缩略图、发布，以及 `fw_pipeline`、`fw_sync` 全部按它定位，不再拼英文路径。
- **迁移**：manifest 增加 `layoutVersion: 2`。Bridge 打开项目/启动时调用 `fw_project.migrate_layout`，按 ID 排序逐个整目录移动（含 `pipeline/`、`.blend`、`.edited.glb`）并即时写回 manifest，可中断重跑；`_Source/Materials` 合并进 `材质`。绑定 UE 目标/发布时调用 `migrate_ue_export` 迁移 `<UE>/Forgeworks/_Source`，目标已存在时保留旧目录并记录，不覆盖。
- **UE 侧**：`fw_sync.py` 从 `sourceDir` 推导磁盘路径与 `contentPath`，旧 `/Game/Forgeworks/Machines/<ID>/SM_<ID>` 仅在目标不存在时重命名；`fw_registry.py` 递归扫描 `/Game/Forgeworks`，按 `SM_<ID>` 去重并优先中文路径。
- **状态**：机器改动 `name` 会触发 `contentHash` 变化；物品 `itemIconHash` 也纳入 `name`，改名后会标记待更新并随下次导出移动目录。

## 19. AI 接入：MCP + 安全写入 + 实时同步（2026-10-23）

- **MCP**：新增 `tools/mcp_forgeworks.py`（stdlib stdio JSON-RPC，零依赖），`.mcp.json` 注册项目级 `forgeworks` server；启动 Bridge 后 AI 可读状态、列/读/增删改实体、扫描、发布、读写并运行生成管线。详见 `docs/ai-mcp.md`。
- **乐观锁**：`GET /api/project/content` 返回 `revision`（`project.json` 字节 sha256）；`POST /api/project/content` 可带 `baseRevision`，不匹配返回 409 且不落盘。
- **实体接口**：`POST /api/content/entity`、`POST /api/content/entity/delete` 在进程内锁下做单实体 read-modify-write；集合白名单为 elements/items/machines/recipes/techs。
- **实时同步**：写入成功后广播 `content.changed`（含 `revision`、`source`、`clientId`）。页面忽略自身事件；编辑器打开或本地有待保存改动时延迟同步，其余立即重载重绘。
- **界面冲突合并**：自动保存带 `baseRevision`；遇到 409 时以最后载入内容为基线做三方合并（单方改动直接采用，双方都改保留本地并提示），用新 revision 重试一次。
- **验证**：`tests/test_bridge_projects.py` 覆盖 revision/409、实体增删与非法输入；`tests/test_mcp_forgeworks.py` 覆盖 MCP 协议与工具转发。
