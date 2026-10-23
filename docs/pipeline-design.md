# Forgeworks · 资产生成流水线（节点图）· 设计计划书

> 状态：**草案，待评审**。本文只做设计，不含实现。
> 日期：2026-10-21 · 版本 v0.1
> 姊妹篇：`docs/sync-design.md`（UE 资产同步系统）。本文管「资产怎么生成」，那边管「生成完怎么进 UE」。

---

## 0. 给决策者的三句话

1. **你要的"描述词→三视图→模型→减面→编辑→导出"这条链，每一步都有现成的 API 或本地能力**，调研结论写在 §3——最省事的组合是 Tripo（一家打通文生三视图 + 三视图生模型 + API 侧减面，带 PBR 贴图，$0.2~0.5/模型），本地兜底是 Blender（已实测可用）。
2. **节点图形态可行，但要控制野心**：UE 蓝图那种"任意节点任意连线+执行时求值"的通用图编辑器工作量巨大。建议做**"模板流水线 + 可视化节点图 + 有限编辑"**——节点类型固定（约 10 种），可以增删改参数、改连线顺序、分叉重试，但不做自定义节点。这样能覆盖你要的全部流程，工作量减半。
3. **成本控制是设计核心不是附加**：一次三视图+模型的生成要花 $0.3~0.7，32 个建筑全跑一遍就是 $10~25。所以每个节点的输出**必须缓存落盘**，重跑时只重跑失败/被改的节点——这是"差量执行"设计，也是节点图比"一键生成"强的地方：它天然把一次生成拆成了可独立重试的步骤。

---

## 1. 需求定位

### 1.1 现状与缺口

现在工具里只有**描述词**（`js/data/prompts.js` 产出的 machinePrompt/itemPrompt）。从描述词到"带材质带贴图的最终模型"中间隔着：

```
描述词 ──?──▶ 三视图 ──?──▶ 白模+PBR ──?──▶ 减面 ──?──▶ 风格对齐 ──?──▶ 编辑 ──?──▶ 导出
```

每一步目前都要**人工**：复制描述词去文生图网站、下载三视图、上传到图生3D网站、下载 GLB、开 Blender 减面……流程断裂，资产散落各处，而且**风格在第 一 步之后就失控了**（生成模型的贴图不会遵守我们的风格色板）。

### 1.2 目标

把这条链变成工具内的**可视化流水线**：

- 节点图形态（类 UE 蓝图的观感），描述词节点连线到三视图节点、再连到模型节点
- 每个节点可以单独运行、单独重试、单独查看输出
- 大模型接入（文生图、图生3D）由 Bridge 统一代理，密钥不进前端
- 生成的模型**自动过风格引擎对齐**（这是本工具区别于"手动跑网站"的核心价值）
- 全程产物落盘到 `_Source/pipeline/`，接上 sync-design 的导出系统

### 1.3 与姊妹篇的分工

| 关注点 | 本文（pipeline） | sync-design |
|---|---|---|
| 资产怎么**生成** | ✅ 节点图 + 大模型 | — |
| 资产怎么**进 UE** | 只到最后写 `_Source/` 为止 | ✅ 目录约定 + UE 导入 + 反向加载 |
| manifest | 写 `pipeline` 字段 | 读它做状态 |

---

## 2. 核心概念：流水线 = DAG

```
                    ┌─────────┐
                    │ 描述词   │  从工具数据自动生成（machinePrompt + styleBrief）
                    └────┬────┘
                         │
                    ┌────▼─────────┐
                    │ 三视图生成    │  文生图 API（Tripo multiview / 豆包 / CogView）
                    └────┬─────────┘
                         │
              ┌──────────▼──────────┐
              │ 模型生成（图生3D）    │  Tripo multiview-to-model / Meshy
              └──────────┬──────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼────┐     ┌─────▼─────┐    ┌─────▼─────┐
   │ 减面     │     │ 风格对齐   │    │ 质量门禁   │   三个后处理可并行/可选
   └────┬────┘     └─────┬─────┘    └─────┬─────┘
        └────────────────┼────────────────┘
                    ┌────▼────┐
                    │ 手动编辑 │  网页 3D / Blender（可选，人工触发）
                    └────┬────┘
                    ┌────▼────┐
                    │ 导出     │  写 _Source/ → 接 sync-design
                    └─────────┘
```

- 一条流水线 = 一个资产（机器/物品）的生成历史
- 节点间传递的是**文件引用**（不是内联数据）：每个节点输出写到
  `_Source/pipeline/<assetId>/<node序号>_<类型>/`，边只存路径
- 好处：缓存天然成立、断点续跑免费、任何一步都能回看/回滚/单独重跑

---

## 3. 节点类型清单

每个节点：**输入 → 处理 → 输出**。处理位置分三类：`前端`（纯 JS）、`Bridge`（本地 Python）、`远程`（大模型 API）。

### 3.1 `prompt` 描述词节点

| | |
|---|---|
| 输入 | 无（从工具数据取） |
| 处理（前端） | `machinePrompt(m)` / `itemPrompt(it)` + `styleBrief(st, {full:true})`，已有 |
| 输出 | `prompt.txt`（单文件，含风格约束） |
| 参数 | source: `auto`（跟随数据自动）/ `manual`（手写覆盖）；viewMode: `3-view`（三视图专用措辞，见 §5） |
| 成本 | 0 |
| 说明 | 数据改了/风格改了 → 此节点标脏 → 下游全部标脏（差量执行会提示，**不会自动花钱**） |

### 3.2 `textToImage` 三视图生成节点

| | |
|---|---|
| 输入 | `prompt.txt` |
| 处理（远程） | 文生图 API |
| 输出 | `view_front.png` / `view_side.png` / `view_top.png`（或一张 sheet） |
| 参数 | provider、model、width/height、negative、seed |
| 成本 | Tripo `generate_multiview_image` 10 credits（$0.10）；豆包/即梦约 ¥0.04~0.1/张 |

**Provider 候选**（Bridge 侧抽象，可换）：

| Provider | 端点 | 优势 | 备注 |
|---|---|---|---|
| **Tripo multiview** | `generate_multiview_image` | 专为 3D 生成服务的多视图，与它的 multiview-to-model 无缝衔接 | 10 credits |
| 火山方舟（豆包/即梦） | 文生图 API | 你已有账号；中文 prompt 友好 | 生成的是普通图，需要 prompt 里明确"三视图排布" |
| 智谱 CogView | 文生图 | 你已有账号 | 同上 |
| Tripo generate_image | flux.1 / gpt-4o / gemini | 模型可选 | 5-10 credits |

### 3.3 `imageTo3D` 模型生成节点（核心）

| | |
|---|---|
| 输入 | 三视图 PNG × 1~4 |
| 处理（远程） | 图生3D API |
| 输出 | `raw.glb`（含网格 + PBR 贴图：basecolor / normal / metallic-roughness） |
| 参数 | provider、model、faceLimit、texture quality、seed |
| 成本 | Tripo H3.1 multiview→3D：$0.20（无贴图）/ $0.30（标准贴图）/ $0.40（精细）；Meshy-6：~$0.40 |

**Tripo 关键参数**（与我们的需求完美对位）：

| 参数 | 用途 | 我们的用法 |
|---|---|---|
| `multiview-to-model` | 2-4 张正交图 → 模型 | **主路径**，吃三视图节点输出 |
| `face_limit` | 直接控制面数（48~2,000,000） | 设 20000，后端先粗控 |
| `smart_low_poly` | 干净的手工感低模拓扑（500~20,000 面） | 体素风格直接开 |
| `quad=true` | 四边面输出（FBX） | UE 里改拓扑友好，暂不用 |
| `pbr=true` | PBR 贴图 | 开，材质要的 |
| `export_orientation` | 朝向轴 | `+x`（与我们的约定一致） |
| `model_seed` / `texture_seed` | 固定种子复现 | **必须存进节点**，同 seed 同输入=同结果 |
| `compress=geometry` | meshopt 压缩 | 可开，减小传输 |

**输出质量分层**：P2 Preview（原生四边面，48~50,000 面，游戏向）> H3.1（高精度）> Turbo（快）。**体素风格建议先试 P2 或 H3.1+smart_low_poly**。

### 3.4 `decimate` 减面节点

生成模型常常几十万面，UE 体素风格只要 ~900。三级策略，按优先级自动选择：

| 级 | 方法 | 位置 | 效果 | 成本 |
|---|---|---|---|---|
| 1 | **API 侧**：`face_limit` / `smart_low_poly` | 远程（3.3 的参数） | 生成时就是低模，拓扑最干净 | 0（参数） |
| 2 | **Blender Decimate** | Bridge → `blender -b` | 质量好，可控制坍塌比/保持边界 | 0（本地，~1s） |
| 3 | **浏览器 meshopt simplify** | 前端 | 无需外部依赖，质量中等 | 0 |

设计：节点参数 `method: auto` 时按 1→2→3 兜底（生成时已达标就 skip）。
Blender 已实测可用（0.15s 导入 + 修改器 + 导出全程 <2s）。

### 3.5 `styleApply` 风格对齐节点（本工具的差异化价值）

生成模型的贴图是 AI 自由发挥的，**必然偏离我们的风格色板**。此节点做自动对齐：

1. 读 GLB 里每个材质槽的 `baseColorFactor` 与贴图平均色
2. 用风格引擎 `fitColor()` 校正到角色带（色相保留，S/L 拉回）
3. 贴图级：Canvas 重染（HSL 逐像素校正，256/512 贴图前端几十毫秒）
4. 金属/粗糙度按风格 `matMap` 对应的 MATERIALS 表覆写
5. 输出 `styled.glb` + 对齐报告（每个材质槽的校正量）

**这是"手动跑网站"做不到的**：网站生成的模型拿回来还得手动调色，这里一步到位。

### 3.6 `validate` 质量门禁节点

沿用 sync-design 的验收标准，自动检查：

- 三角面数 ≤ 风格规格（`spec.machine` 的 900）→ 超则黄灯/红灯
- 网格数 == 1（Tripo 可能输出多网格 → 自动 merge 或警告）
- 材质槽数 ≤ 8（UE 槽太多影响性能）
- 尺寸合理性：包围盒 vs footprint（`auto_size` 参数 + 本地 `fitToFootprint` 已有）
- 底部对齐（min_z ≈ 0，已有的 fitToFootprint 逻辑可复用）

输出：`report.json`，不合格可配置为**阻断**或**警告**。

### 3.7 `manualEdit` 手动编辑节点（人工断点）

- 不是自动节点，是**流程标记**：流水线跑到这里暂停
- 打开方式二选一：网页 3D 编辑器（sync-design P4）/ Blender（生成 `.blend` 打开）
- 完成信号：用户点"完成编辑"→ 节点变 done，取 `edited.glb` 继续
- 编辑产物优先级最高（见 §7 单一来源）

### 3.8 `export` 导出节点

把最终 GLB + 贴图写进 `_Source/机器/<中文名>/` 标准位置，更新 manifest，触发 sync-design 的 UE 导入流程。到此本文职责结束。

### 3.9 `variant` 变体节点（可选，后期）

生成结果不满意 → 从任一节点**分叉**重试（不同 seed / 不同 provider），保留多版本对比，选一个继续。这是节点图相对"一键流程"的第二个优势：**历史不是线，是树**。

---

## 4. Provider 抽象与密钥管理

### 4.1 Bridge 侧统一抽象

```python
# tools/fw_providers.py（设计示意）
class GenProvider:
    name: str
    def text_to_image(self, prompt, opts) -> list[Path]      # 三视图
    def image_to_3d(self, images, opts) -> Path               # GLB
    def estimate_cost(self, kind, opts) -> float              # 预估美元

class TripoProvider(GenProvider): ...     # multiview 端点链
class MeshyProvider(GenProvider): ...     # 备选
class ArkProvider(GenProvider): ...       # 火山方舟文生图（你已有账号）
class ZhipuProvider(GenProvider): ...     # 智谱 CogView
class LocalFallback(GenProvider): ...     # 不花钱：程序化图元直接产 GLB（现有能力）
```

**关键约束：所有 API 调用只发生在 Bridge**。前端只发"运行节点 N"的指令。理由：
1. 密钥不进浏览器、不进 localStorage、不进 git
2. CORS 由 Bridge 代理解决（Tripo/Meshy 不一定允许浏览器直连）
3. 下载的 GLB 由 Bridge 直接落盘（不用先到前端再传回来）

### 4.2 密钥管理

```
Forgeworks/                    ← 工具仓库根
├── tools/bridge_config.json   ← 密钥与偏好（.gitignore 已排除）
└── tools/bridge_config.example.json  ← 模板（入库）
```

```jsonc
// bridge_config.example.json
{
  "providers": {
    "tripo": { "api_key": "", "default_model": "v3.1-20260211" },
    "meshy": { "api_key": "" },
    "ark":   { "api_key": "", "endpoint": "" },
    "zhipu": { "api_key": "" }
  },
  "blender": {
    "candidates": [
      "/Volumes/KingstonXS1000Media/app/Blender.app/Contents/MacOS/Blender",
      "/Applications/Blender.app/Contents/MacOS/Blender"
    ]
  }
}
```

界面上的密钥配置页只在 Bridge 本地起作用，写进这个文件。

---

## 5. 三视图的 Prompt 工程（决定生成质量的关键）

### 5.1 三视图专用模板

三视图不是"三张普通图"，prompt 必须明确排布与视角，否则模型生 3D 时对不齐：

```
【输出形式】正交三视图设定图（character/prop turnaround sheet）：
  一张图内左右并排三个视角：正视 FRONT | 侧视 SIDE | 顶视 TOP
  每个视角独立完整、姿态与朝向严格一致、比例严格一致
【构图】白底；无阴影投影；无地面；无文字标注；视角之间留白分隔
【投影视角】正交投影（orthographic），无透视畸变
——以下为内容——
{machinePrompt 的主体/形态/部件部分}
——以下为风格——
{styleBrief 的形态/着色/配色约束}
【负向】透视变形、俯仰角、多视角比例不一致、背景元素、文字水印、{风格负向词}
```

### 5.2 现有资产能直接复用的

- `machinePrompt()` 的【主体】【形态】【必须包含的部件】——直接拼进模板
- `styleBrief()` 的【形态】【着色】【配色约束】——保证三视图风格统一
- 风格引擎的负向词——追加"透视变形、视角比例不一致"两条三视图特有负向

### 5.3 备选：三张独立图 vs 一张 sheet

| 方式 | 优点 | 缺点 |
|---|---|---|
| 一张 sheet（3 视图并排） | 一致性最好（同一次生成） | 分辨率被分摊；部分模型对 sheet 理解差 |
| 三张独立图（同 seed） | 每张分辨率高 | 三张之间比例可能漂移 |

Tripo `generate_multiview_image` 输出的就是多视图格式，直接喂 `multiview-to-model`，**首选这条**。豆包/CogView 生成 sheet 后再由 Bridge 切成三张。

---

## 6. 执行引擎

### 6.1 差量执行（省钱的核心）

每个节点状态：`idle / dirty / running / done / failed / skipped`。

```
运行整条流水线：
1. 拓扑排序（DAG）
2. 逐节点：
   - 节点 done 且上游未变      → skip（不花钱，秒过）
   - 节点 done 但上游 hash 变了 → dirty → 重跑
   - 节点 failed               → 重试
3. 每个节点完成 → 输出落盘 → 记录 { inputHash, paramsHash, outputHash, cost, seed }
```

**Hash 链**：`节点输出 hash = f(上游输出 hash, 本节点参数 hash)`。任何上游变化沿 DAG 传播为 dirty，但**传播只标记，不自动执行**——用户看着节点图上的黄色标记决定跑不跑（避免风格一改就自动烧几十美元）。

### 6.2 运行时交互

- 每个节点可单独点「运行」→ 只跑这一个（上游没准备好则先跑上游）
- 「运行到此处」→ 从头跑到该节点
- 「运行整条」→ 全部
- 远程节点运行中显示进度（Tripo 是任务制：POST 拿 task_id → 轮询 status，Bridge 轮询后 SSE 推给前端）
- 预估成本在运行前显示：「本次将消耗约 $0.40（三视图 0.10 + 模型 0.30）」，确认后才扣

### 6.3 失败与重试

- API 失败（429/5xx）→ 指数退避自动重试 3 次
- 内容失败（生成结果 validate 不过）→ 节点标 failed + 报告；一键"换 seed 重跑"
- 断点续跑天然成立（缓存即状态）

---

## 7. 数据存储与单一来源

```
_Source/pipeline/MC_DRILL/
├── 01_prompt/
│   └── prompt.txt               (+ output.json：hash/cost)
├── 02_textToImage/
│   ├── view_front.png  view_side.png  view_top.png
│   └── output.json             (provider/model/seed/cost)
├── 03_imageTo3D/
│   ├── raw.glb                 (Tripo 原始输出，含 PBR)
│   └── output.json             (task_id/face_count/材质槽/seed)
├── 04_decimate/
│   └── low.glb
├── 05_styleApply/
│   ├── styled.glb
│   └── align_report.json       (每个材质槽校正量)
├── 06_validate/
│   └── report.json
├── 07_manualEdit/              (可选)
│   └── edited.glb / work.blend
└── graph.json                  流水线定义（节点/边/参数）
```

**几何真相的优先级**（并入 sync-design §4.1 的主从表）：

```
edited.glb（人工精修） > styled.glb（风格对齐后） > low.glb > raw.glb
                > 程序化图元（现有 buildMachineParts，保底）
```

程序化图元从"唯一真相"退化为**免费的兜底与对照**——这很重要：AI 生成的模型没有程序化版本的"占地/比例"保证，validate 节点要用程序化包围盒做参照。

`manifest.json`（sync-design）增加：

```jsonc
"MC_DRILL": {
  "pipeline": {
    "graphVersion": 3,
    "lastRun": "2026-10-21T11:00:00Z",
    "nodes": { "01_prompt":"done", "02_textToImage":"done", "03_imageTo3D":"dirty", ... },
    "totalSpent": 0.40,
    "activeOutput": "05_styleApply/styled.glb"
  }
}
```

---

## 8. 节点图 UI 设计

### 8.1 形态（类蓝图观感，但功能收敛）

```
┌────────────┬───────────────────────────────────────────────────────┐
│ 节点面板    │  画布（SVG 连线层 + DOM 节点层）                        │
│            │                                                       │
│ ▸ 输入类    │   ┌──────────┐    ┌───────────┐    ┌────────────┐    │
│   描述词    │   │ 描述词 ●━━│━━━▶│ 三视图 ●━━│━━━▶│ 图生3D      │    │
│   参考图    │   │ ✓ auto   │    │ ⟳ dirty   │    │ ○ idle     │    │
│ ▸ 生成类    │   └──────────┘    │ Tripo     │    │ faceLimit   │    │
│   三视图    │                    │ $0.10     │    │ 20000       │    │
│   图生3D    │                    └───────────┘    └────────────┘    │
│ ▸ 处理类    │                                                       │
│   减面      │   ┌─────────┐ ┌─────────┐ ┌─────────┐                │
│   风格对齐  │   │ 减面 ●━━│ │ 风格 ●━━│ │ 门禁 ●━━│ ──▶ ┌──────┐  │
│   质量门禁  │   └─────────┘ └─────────┘ └─────────┘      │ 导出 │  │
│ ▸ 输出类    │                                           └──────┘  │
│   手动编辑  │  [运行整条 $0.40] [运行到选中] [只跑选中] [差量提示：3 个节点过期] │
│   导出      │                                                       │
└────────────┴───────────────────────────────────────────────────────┘
```

### 8.2 节点卡片

```
┌────────────────────────┐
│ 图生3D          ⋯ ⚙ ✕  │  标题 + 菜单 + 设置 + 删除
│ ────────────────────── │
│ provider   Tripo    ▾  │  参数区（每类型固定表单）
│ model      H3.1     ▾  │
│ faceLimit  [20000]     │
│ seed       [48213] 🎲  │  骰子 = 换 seed 重试
│ ────────────────────── │
│ ▶ 运行   成本 ~$0.30   │
│ ● done · 18,742 面     │  状态灯 + 摘要
│ [缩略图]  [查看 GLB]    │  输出预览（点开 3D 预览复用 viewer3d）
└────────────────────────┘
○ 输入端口              ● 输出端口
```

### 8.3 实现选型

| 方案 | 判断 |
|---|---|
| **自研（SVG 连线 + DOM 节点）** | ✅ **推荐**。已有 SVG 绘图经验（依赖图谱视图）；无外部依赖（项目原则：本地 vendor、离线可用）；节点类型固定约 10 种，不需要通用图引擎的能力 |
| Rete.js | ❌ 插件体系复杂、样式难统一、UMD 支持差（项目用 file:// 兼容的普通 script） |
| Drawflow | ⚠️ 够轻，但自定义执行模型要绕它的 API，且停更风险 |
| LiteGraph.js | ⚠️ 面向实时求值（每帧执行），与我们的"任务制、可缓存、要花钱"模型不匹配 |

自研工作量集中在三块：拖拽/框选/连线交互（~600 行）、端口类型检查（~100 行）、自动布局（~150 行，按 DAG 层次排布即可）。

**端口类型**（防接错线）：

| 类型 | 颜色 | 产出节点 | 消费节点 |
|---|---|---|---|
| text | 灰 | prompt | textToImage |
| image | 蓝 | textToImage | imageTo3D |
| mesh | 绿 | imageTo3D / decimate / styleApply / manualEdit | 后续所有 |
| report | 紫 | validate | export（门禁不过则阻断） |

---

## 9. 与同步系统的衔接

```
pipeline（本文）                       sync（姊妹篇）
──────────────────────                ──────────────────────
export 节点写 _Source/机器/<中文名>/ ─▶ manifest 状态机变 exported
                                       ─▶ UE 侧 fw_sync.py 导入
                                       ─▶ 回写 ue 资产路径
graph.json 的状态                      ─▶ manifest.pipeline（§7）
风格 hash 变化                          ─▶ 节点 dirty（要重新 styleApply，
                                          但模型可以复用 —— 差量省钱）
```

**风格变化的省钱路径**：风格只影响 `prompt`（三视图措辞）与 `styleApply`（颜色对齐）。改风格后：
- 如果愿意接受现有几何 → 只重跑 `styleApply`（$0，本地）
- 如果想让三视图也换风格 → 重跑 `textToImage` + `imageTo3D`（$0.4/个，节点图会让你明确看到这条成本线）

---

## 10. 分期实施计划

| 期 | 内容 | 产出 | 验收标准 | 预估 |
|---|---|---|---|---|
| **Q0** Provider 接入 | Bridge 的 provider 抽象 + Tripo 首个实现 + 密钥管理 + 任务轮询 | `tools/fw_providers.py` | 手动 curl 级：描述词→三视图→GLB 全链通，落盘 | 中 |
| **Q1** 流水线数据层 | graph.json 读写 + 节点执行器框架 + hash 链 + 差量标记 | `js/pipeline.js` | 改参数 → 只有该节点及下游变 dirty；重跑只执行 dirty | 中 |
| **Q2** 节点图 UI | 画布 + 节点卡 + 连线 + 拖拽 + 端口类型检查 + 自动布局 | `js/views/pipeline.js` | 从模板一键建流水线；连线可增删；运行时状态实时刷新 | **大** |
| **Q3** 风格对齐 + 门禁 | styleApply（GLB 材质/贴图重染）+ validate | 同上扩展 | 生成模型经对齐后配色落在风格色板内；超面数被拦 | 中 |
| **Q4** 变体与对比 | 分叉重试 + 多版本保留 + 对比视图 | 同上扩展 | 不满意的模型换 seed 重跑，旧版本不丢 | 中 |
| **Q5** 模板库 | 按资产类型（机器/物品/图标）的流水线模板 + 批量跑 | `js/pipeline-templates.js` | 新建机器自动带默认流水线；批量预估总成本 | 小 |

依赖：Q0 依赖 sync-design 的 **P0（Bridge）**。其余可与 sync 的 P2-P6 并行推进。

**建议顺序**：先做 sync-P0（Bridge 地基，两边共用）→ Q0（打通一个真实生成，看到效果再投入 UI）→ Q1 → Q2。

---

## 11. 风险清单

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| S1 | **API 生成的模型风格漂移**（AI 贴图不遵守色板） | 最终资产不成套 | styleApply 节点强制校正；实在不行"贴图全弃、纯色材质"模式（体素风格反而合适） |
| S2 | 三视图比例不一致 → 生成模型歪 | 返烧钱 | Tripo multiview 端点原生对齐；validate 门禁查对称性；seed 固定可复现 |
| S3 | **费用失控**（批量跑 32×重试） | 真金白银 | 差量执行 + 运行前成本确认 + 每资产花费上限 + totalSpend 记录 |
| S4 | API 政策/价格变动（Tripo 价格 2026 年内调过多次） | 预算失真 | Provider 抽象可换；成本显示为"预估，以 consumed_credits 实测为准"（Meshy 返回实耗） |
| S5 | 网络不通 / 服务商在境外 | 生成不可用 | LocalFallback（程序化图元）永远可用，流水线降级为现有能力 |
| S6 | 节点图 UI 工期超预期 | 阻塞后续期 | Q2 拆两步：先"纵向列表+运行按钮"的简化视图（1 周级），后补完整画布 |
| S7 | 生成模型多网格/非水密 | UE 导入问题 | validate 门禁 + BufferGeometryUtils 合并（已有） |
| S8 | 密钥泄漏 | 财务风险 | 密钥只在 Bridge 进程内存与 gitignore 的配置文件；前端只见"已配置/未配置" |
| S9 | API 返回 GLB 与声明规格不符（面数超标） | 门禁误判 | 以 Bridge 落盘后本地实读为准（Blender/meshopt 校验） |

---

## 12. 待你决策的问题

**Q1. 首个 Provider 选谁？**
- (a) **Tripo**（推荐：multiview 端点链完整、免费层 300 credits/月 + 新 API 用户 2000 credits ≈ $20 额度，够把 32 个建筑各试一遍）
- (b) Meshy（插件生态好，但免费层只有 100 credits/月、API 需 $20/月订阅）
- (c) 火山方舟/智谱做三视图 + Tripo 只做图生3D（组合：三视图用你已有的国内账号，模型生成用 Tripo）
- (d) 先 LocalFallback（不花钱，纯程序化，先把流水线框架跑通再加 API）

**Q2. 三视图用一家端到端，还是拼接两家？**
- (a) Tripo multiview 端到端（一致性最好）
- (b) 国内文生图做三视图 + Tripo 只做模型（省钱、中文友好，但 sheet 切图比例可能漂移）

**Q3. UI 先做简化版还是直接上完整画布？**
- (a) 先"纵向步骤条 + 运行按钮"（快 1 周级见效，见 S6）
- (b) 直接做完整节点画布（一步到位，周期长）

**Q4. 生成模型的贴图怎么定位？**
- (a) **用 AI 贴图，但强制过 styleApply 校正**（推荐：有细节又成套）
- (b) 弃贴图，纯色顶点色（最稳，体素风格成立，省 styleApply 的贴图重染）
- (c) 两档都留，按资产选

**Q5. 花费上限？**（单资产 / 单次批量 / 月度，超过要弹确认）

---

## 附 A：成本速算（Tripo H3.1，2026-10 价格）

| 操作 | 单价 | 32 个建筑一遍 | 备注 |
|---|---|---|---|
| 三视图（multiview image） | $0.10 | $3.20 | |
| 图生3D（标准贴图） | $0.30 | $9.60 | face_limit 内 |
| 图生3D（无贴图） | $0.20 | $6.40 | 配纯色方案 b |
| 重试平均 1.5× | — | ×1.5 | 换 seed 是常态 |
| **合计（贴图方案）** | | **≈ $19** | 新用户免费额度（$20）基本覆盖首次 |
| **合计（纯色方案）** | | **≈ $13** | |

## 附 B：节点类型速查

| 类型 | 处理位置 | 输入 | 输出 | 花钱 |
|---|---|---|---|---|
| prompt | 前端 | 工具数据 | text | ✕ |
| textToImage | 远程 | text | image×1~4 | $0.05~0.10 |
| imageTo3D | 远程 | image×1~4 | mesh | $0.20~0.40 |
| decimate | Bridge/前端 | mesh | mesh | ✕ |
| styleApply | 前端 | mesh | mesh | ✕ |
| validate | 前端 | mesh | report | ✕ |
| manualEdit | 人工 | mesh | mesh | ✕ |
| variant | 远程 | 任意 | 同类型 | 同上游 |
| export | Bridge | mesh+report | 落盘 | ✕ |

---

*待评审。确认 §12 的五个问题后，按「sync-P0（Bridge）→ Q0（Provider 打通）」的顺序开始。*
