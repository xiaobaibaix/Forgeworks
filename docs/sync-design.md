# Forgeworks ⇄ UE 资产同步系统 · 设计计划书

> 状态：**草案，待评审**。本文只做设计，不含实现。
> 日期：2026-10-21 · 版本 v0.1
> 姊妹篇：`docs/pipeline-design.md`（资产生成流水线/节点图）。本文管「生成完怎么进 UE」，那边管「资产怎么生成」（描述词→三视图→模型→减面→导出，含大模型接入）。两篇共用 P0 的 Bridge 地基。

---

## 0. 给决策者的三句话

1. **能做，但要纠正一个前提**：浏览器无法直接生成 `.uasset`（UE 的二进制资产格式），所以"导出到 UE 项目文件夹"的正确形态是——工具产出**中间格式 + 清单**，由 UE 侧的脚本负责把它们变成 `.uasset`。这是硬限制，绕不过去。
2. **不需要嵌入 Blender，但它已被实测证明可以当"实时后端"用**：Blender 是原生桌面应用无法嵌进网页，但实测（本机 `/Volumes/KingstonXS1000Media/app/Blender.app`，5.2.0 LTS arm64）后台模式 **0.15 秒**就能完成"导入工具产出的 GLB → 读网格/材质/元数据"，渲染缩略图 6 秒/张。见 §2.6。你想要的"选中、拖动、坐标轴、父子关系"用 three.js 做，Blender 负责精修和出图。
3. **主架构建议用「本地 Bridge 服务」而非浏览器文件 API**：因为 Bridge 能 spawn 子进程（调 Blender、调 UE），而浏览器的 File System Access API 不能。代价是需要跑一个 Python 服务——你现在已经在跑了（`tools/serve.py`）。

---

## 1. 需求拆解

把你说的拆成可验收的功能点：

| 编号 | 需求 | 类型 |
|---|---|---|
| F1 | 绑定一个 UE 项目里的特定文件夹作为资产根 | 配置 |
| F2 | 目录为空 → 可导出全部资源到该目录 | 写 |
| F3 | 机器列表每项显示导出状态标记 | UI |
| F4 | 导出内容包含：模型、材质、法线贴图、图标等 | 生成 |
| F5 | 按"级别目录"（每个机器一个子目录）组织 | 约定 |
| F6 | 工具内随时调整材质/贴图/模型，改动及时反馈到目录 | 双向 |
| F7 | 目录已有内容 → 反向加载进工具查看与修改 | 读 |
| F8 | 3D 视图显示坐标轴 | 视图 |
| F9 | 支持局部/全局坐标系切换 | 视图 |
| F10 | 显示模型部件之间的父子关系 | 视图 |
| F11 | 可选中部件并用 gizmo 移动/旋转/缩放 | 编辑 |
| F12 | （可选）嵌入 Blender 做精修 | 扩展 |

**需求里隐含但没说清的关键点**（必须在实现前定下来，见 §10）：
- F6 的"及时"是秒级自动同步，还是点按钮同步？
- F7 的"反向加载"，加载的是**模型的几何**，还是**UE 里的资产路径与设置**？
- 工具里的模型是程序化生成的（8 种图元拼装），用户在 3D 里挪动一个部件后，**这个改动存在哪**？

---

## 2. 技术现实检查

### 2.1 硬限制：`.uasset` 不能由浏览器生成

UE 的 `.uasset` 不是"模型文件"，是 **UObject 的二进制序列化快照**，一个包里包含：

- 包文件摘要（PackageFileSummary）：引擎版本、许可证版本、总大小、**包 GUID**
- Name Table / Import Table / Export Table（对象引用图）
- 每个 UObject 的属性序列化（按 `UStruct` 的反射布局，含对齐与位域）
- 依赖关系与本地化命名表
- 可选压缩/加密块（Oodle）

要凭空写出合法的 `.uasset`，等于在 JS 里重新实现 UE 的 `UPackage` 序列化 + 版本兼容 + 反射布局。**不现实，也不该做**——任何一个 UE 小版本改动都可能让它失效。

**结论**：工具产出的必须是中间格式。`.uasset` 只能由 UE 自己生成。

### 2.2 中间格式选型

| 格式 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **glTF 2.0 / GLB** | UE 5.x 原生支持（Interchange）；PBR 材质完整；二进制单文件；three.js 双向可读写 | 单位是**米**，UE 是**厘米**（100× 陷阱） | ✅ **主选** |
| FBX | UE 老牌支持，动画更成熟 | 二进制闭源；three.js 需额外 loader；材质表达能力弱 | 备选（仅动画需要时） |
| OBJ | 简单 | 无材质、无层级、无 PBR | ❌ |
| USD | UE 5.x 支持，Pixar 生态 | 生态偏影视；three.js 支持弱 | 暂不考虑 |

材质与贴图单独出 PNG（UE 侧再组装成 Material），因为 GLB 内嵌贴图在 UE 里会变成"内嵌子资产"，不利于美术后期替换。

### 2.3 已否决 / 降级的方案

| 方案 | 判定 | 理由 |
|---|---|---|
| **A. 前端用 File System Access API 直接读写项目目录** | ⚠️ 降级为**备选** | 实测 Chrome 155 全支持（`showDirectoryPicker` / `createWritable` / `FileSystemObserver` 目录监听 / handle 可存 IndexedDB）。但：① 不能 spawn 子进程 → 无法调 UE / Blender；② Safari / Firefox 不支持；③ 每次会话要用户手势重新授权；④ 无法读 `.uasset` 内部信息。**适合"轻量只读预览"，不适合做主同步通道** |
| **B. 把 Blender 嵌入网页** | ❌ 不可行 | Blender 是原生桌面应用（C/C++/Python），没有 WebAssembly 版本，没有官方 embedding API。所谓"网页版 Blender"都是远程串流（Blender 官方实验项目也是串流） |
| **C. 直接写 `.uasset`** | ❌ 不可行 | 见 §2.1 |
| **D. 只导出不反向加载** | ❌ 不满足 F7 | — |
| **E. 前端直接调 UE 命令行** | ❌ 不可行 | 浏览器不能启动本地进程。这正是需要 Bridge 的原因 |

### 2.4 采用方案：本地 Bridge 服务

**核心判断**：既然需要一个能读写文件、能启动子进程的东西，那就放在 Python 服务里。前端只做 UI 和 3D。

```
┌──────────────────────────────────────────────────────────────┐
│ 浏览器（Forgeworks UI）                                       │
│  ├ 内容设计（现有 14 个视图）                                  │
│  ├ 3D 编辑器（three.js + TransformControls + 大纲树）          │
│  └ 同步面板（导出状态、差异、冲突）                            │
└────────────────┬─────────────────────────────────────────────┘
                 │ HTTP + SSE（事件推送）
┌────────────────▼─────────────────────────────────────────────┐
│ Forgeworks Bridge（Python 本地服务，:8787）                    │
│  ├ 静态文件服务（现有 serve.py 的能力）                        │
│  ├ /api/fs/*      项目目录读写、扫描、hash                     │
│  ├ /api/export/*  生成 GLB / 贴图 / 图标 / 清单                │
│  ├ /api/import/*  反向读取（扫描目录 + 读 UE 清单）            │
│  ├ /api/proc/*    启动子进程（Blender / UnrealEditor-Cmd）      │
│  └ FileSystemObserver（watchdog）→ SSE 推送变化                │
└────────────────┬─────────────────────────────────────────────┘
                 │ 文件系统
┌────────────────▼─────────────────────────────────────────────┐
│ <UE项目>/Forgeworks/                                          │
│  ├ _Source/     ← 工具写（GLB / PNG / JSON，UE 不扫描）        │
│  ├ _Sync/       ← 清单与状态（manifest.json、conflicts）       │
│  └ （UE 侧再导入到 /Game/Forgeworks/，uasset 那侧）            │
└────────────────┬─────────────────────────────────────────────┘
                 │ UE 编辑器内 Python 监听器
┌────────────────▼─────────────────────────────────────────────┐
│ Unreal Editor                                                 │
│  └ fw_sync.py：轮询/长连 Bridge → Interchange 导入 → 回写状态  │
└──────────────────────────────────────────────────────────────┘
```

**为什么 Bridge 优于纯浏览器方案**：

| 能力 | Bridge | 纯浏览器 FSA API |
|---|---|---|
| 读写任意路径 | ✅ 配置里写死也行 | ⚠️ 每次手势授权 |
| 启动 Blender | ✅ `subprocess` | ❌ |
| 启动 UE Python | ✅ | ❌ |
| 目录变化推送 | ✅ watchdog | ⚠️ FileSystemObserver（新，仅 Chrome） |
| 浏览器兼容 | ✅ 全部 | ❌ 仅 Chromium |
| 需要额外进程 | ⚠️ 要跑 Python | ✅ 不用 |
| 读 `.uasset` 头部 | ✅ Python 可解析 | ❌ |

**代价**：多一个进程。但项目已经在用 `tools/serve.py` 了，把它升级即可，用户无感。

### 2.5 关于 Blender 的真实建议（已实测）

**实测结论（2026-10-21，Blender 5.2.0 LTS，本机移动硬盘 arm64）**：

| 验证项 | 结果 | 耗时 |
|---|---|---|
| 后台模式启动 + 建体块 + 导出 GLB + 重新导入 | ✅ 全通 | **0.27 s** |
| 读取 Forgeworks 产出的真实 GLB（91228 字节） | ✅ 1 物体 / 1 网格 / **5 材质槽** / 2240 顶点 | **0.15 s** |
| 元数据传递 | ✅ `root.name = "MC_DRILL"`，`root.keys() = ['forgeworks']` | — |
| 尺寸换算 | ✅ 2.0 × 1.954 × 2.791 m（Y-up→Z-up 自动转换正确） | — |
| 材质参数 | ✅ M_base 金属 0.02/粗糙 0.94（混凝土）、M_body 0.55/0.44（钢）与定义一致 | — |
| 底部对齐 | ✅ min_z = 0 | — |
| EEVEE 渲染 512×512 缩略图 | ✅ 204 KB PNG | 6.1 s |

**这意味着 Blender 可以作为 Bridge 的"实时后端工具"调用**——不是让用户手动开 Blender，而是 Bridge 在需要时 `blender -b -P script.py`，亚秒级完成装配、校验，6 秒级出渲染图。

集成方式（三档，按需选）：

| 档 | 做法 | 前置条件 | 价值 |
|---|---|---|---|
| **1. 校验 + 缩略图**（推荐先做） | Bridge 调 Blender 导入 GLB → 校验网格数/材质数/包围盒 → 渲染 256×256 缩略图给列表用 | 装 Blender（已有） | 导出即有"真实渲染图"，且能在进 UE **之前**发现几何问题 |
| 2. `.blend` 生成脚本 | 工具产 Python 脚本，用户在 Blender 里 Run Script 一键重建整个建筑（带材质与命名） | 无 | 给美术一个起点，不用从零建模 |
| 3. 精修回灌 | 美术在 Blender 里改完导出 GLB，工具检测 `<name>.edited.glb` 优先于程序化几何 | 写约定 | 支持手工细节 |

**Blender 路径问题**：你的 Blender 在移动硬盘（`/Volumes/KingstonXS1000Media/app/Blender.app`），挂载点会变。Bridge 需要：
- 配置文件里存路径（支持数组，多个候选）
- 启动时探测：`/Volumes/*/app/Blender.app/Contents/MacOS/Blender`、`/Applications/Blender.app/...`、PATH 里的 `blender`
- 探测结果缓存，盘没挂载时降级（缩略图改用前端 SVG，报"Blender 不可用"）

**何时该用 Blender，何时不该**：

| 场景 | 用什么 | 理由 |
|---|---|---|
| 挪部件、转角度、改尺寸 | 网页 3D 编辑器 | 秒开，无需切应用 |
| 换材质参数 | 网页材质面板 | 参数直连 GLB 材质槽 |
| 加螺纹、倒角、布尔、雕刻 | Blender | 程序化图元做不到 |
| UV 展开、烘焙法线 | Blender | 必须专用工具 |
| 骨骼动画 | Blender | three.js 端不做 |

### 2.6 GLB → Blender 链路实测报告（附录）

测试样本：`MC_DRILL`（地质钻机），Forgeworks 实际导出的 GLB，91228 字节。

| 项 | 浏览器侧（meta） | Blender 侧实测 | 判定 |
|---|---|---|---|
| 网格数 | 1（合并后） | 1 | ✅ |
| 材质槽 | 5（M_base/M_dark/M_body/M_light/M_accent） | 5，名字一致 | ✅ |
| 尺寸 | 2 × 2.791 × 1.954 m（X,Y,Z，Y-up） | 2.0 × 1.954 × 2.791 m（X,Y,Z，Z-up） | ✅ Y/Z 自动换算正确 |
| 顶点 | 2242 | 2240 | ✅（±2 为合并容差） |
| 底部对齐 | pivot: bottom-center | min_z = 0 | ✅ |
| extras 元数据 | style/palette/knobs/animations | `root['forgeworks']` 可读 | ✅ |
| 材质参数 | metal 0.02/0.55/0.45 | 0.02/0.55/0.45 | ✅ |

**发现的质量问题**：三角面 **2580**，超出设计规格（400~900）约 3 倍。原因：32 个部件 + 圆柱段数偏高（默认 20 段）。这需要在 P1 加**导出质量门禁**：
- 导出时统计三角面，超过风格规格（`spec.machine` 里的 900）→ 黄色告警
- 超过 2×（1800）→ 红色，建议降圆柱段数（20 → 12 足够体素风格）

---

## 3. 目录与命名约定

### 3.1 UE 项目侧结构

```
StellarEra/                                 ← UE 项目根（F1 绑定这一层）
├── StellarEra.uproject                     ← 用来验证确实选对了目录
├── Config/
├── Content/
│   └── Forgeworks/                         ← UE 资产根（uasset 在这）
│       ├── Machines/
│       │   └── MC_DRILL/
│       │       ├── SM_MC_DRILL.uasset
│       │       ├── M_MC_DRILL.uasset
│       │       └── T_MC_DRILL_Basecolor.uasset
│       ├── Items/Icons/
│       └── Materials/Master/
├── Forgeworks/                             ← ★ 工具工作区（不在 Content 下！）
│   ├── _Source/                            工具写的中间文件
│   │   ├── Machines/MC_DRILL/
│   │   │   ├── MC_DRILL.glb
│   │   │   ├── MC_DRILL.meta.json
│   │   │   └── tex/
│   │   │       ├── T_MC_DRILL_basecolor.png
│   │   │       ├── T_MC_DRILL_normal.png
│   │   │       └── T_MC_DRILL_orm.png
│   │   ├── Items/Icons/ICON_ORE_FE.png
│   │   └── Data/DT_*.csv
│   ├── _Sync/
│   │   ├── manifest.json                   同步真相来源
│   │   ├── ue_assets.json                  UE 侧回写的资产清单
│   │   └── conflicts/                      冲突留档
│   └── README.md                           给美术看的说明
└── Saved/
```

**关键设计：`Forgeworks/` 放在项目根，不放在 `Content/` 下。**

理由：UE 会扫描 `Content/` 并把无法识别的文件报告为"无效资产"警告，还会拖慢资产注册。放在根目录则完全隔离，且方便 `.gitignore` 只忽略 `_Source`。

**命名规范**（UE 前缀惯例，必须遵守，否则 UE 侧类型推断会错）：

| 类型 | 前缀 | 示例 |
|---|---|---|
| Static Mesh | `SM_` | `SM_MC_DRILL` |
| Material | `M_` | `M_MC_DRILL` |
| Material Instance | `MI_` | `MI_MC_DRILL` |
| Texture | `T_` | `T_MC_DRILL_basecolor` |
| Texture 后缀 | — | `_basecolor` / `_normal` / `_orm` / `_emissive` / `_roughness` |
| Icon | `ICON_` | `ICON_ORE_FE` |
| DataTable | `DT_` | `DT_MachineDef` |

### 3.2 每个机器的目录（F5「级别目录」）

一个机器一个子目录，机器目录内**平铺**（不再按贴图类型分子目录），理由：UE 导入时一个目录对应一个资产集合，平铺更容易批量操作。

```
_Source/Machines/MC_DRILL/
├── MC_DRILL.glb              网格（单网格 + N 材质槽）
├── MC_DRILL.meta.json        元数据（部件层级、变换、动画、材质绑定）
├── tex/T_MC_DRILL_basecolor.png
├── tex/T_MC_DRILL_normal.png
├── tex/T_MC_DRILL_orm.png    Occlusion-Roughness-Metallic 打包
└── ICON_MC_DRILL.png         列表用缩略图
```

---

## 4. 数据存储约定

### 4.1 谁是"主"？——单一来源原则

这是双向同步最容易失控的地方。必须先定主从：

| 数据类型 | 主（Master） | 从（Derived） | 说明 |
|---|---|---|---|
| 内容定义（物品/配方/机器参数） | **Forgeworks** | UE DataTable | 工具是设计器，UE 是消费方 |
| 模型几何（程序化图元 + 变换） | **Forgeworks** | `_Source/*.glb` → `.uasset` | 工具生成，UE 导入 |
| 材质参数 | **Forgeworks** | `_Source/*.glb` + meta | 同上 |
| 模型精修（Blender 雕的细节） | **外部 `.blend`** | 回灌到 Forgeworks | 唯一例外：美术手工资产优先 |
| UE 侧的资产路径/导入设置 | **UE** | 回写到 `ue_assets.json` | 工具只读 |
| 关卡摆放 | **UE** | — | 工具不碰 |

**简言之：设计数据工具为主，引擎侧资产引擎为主，中间靠清单对齐。** 冲突时按此表判定谁是赢家。

### 4.2 `manifest.json`（同步真相来源）

```jsonc
{
  "schemaVersion": 1,
  "forgeworksVersion": "20261021e",
  "project": {
    "name": "StellarEra",
    "uproject": "StellarEra.uproject",
    "boundAt": "2026-10-21T10:30:00+08:00"
  },
  "style": {
    "presetId": "voxel-industrial",
    "overrides": { "wear": 0.35 },
    "paletteHash": "a3f9..."          // 风格变了要让资产过期
  },
  "assets": {
    "MC_DRILL": {
      "kind": "machine",
      "state": "exported",            // 见 §4.3 状态机
      "sourceDir": "_Source/Machines/MC_DRILL",
      "files": {
        "mesh":   { "path": "MC_DRILL.glb", "size": 91208, "sha1": "9c1e...", "mtime": "2026-10-21T10:31:02Z" },
        "meta":   { "path": "MC_DRILL.meta.json", "sha1": "77ab..." },
        "tex": [
          { "path": "tex/T_MC_DRILL_basecolor.png", "sha1": "e0a1..." },
          { "path": "tex/T_MC_DRILL_normal.png",    "sha1": "4b2c..." }
        ],
        "icon":   { "path": "ICON_MC_DRILL.png", "sha1": "..." }
      },
      "ue": {
        "contentPath": "/Game/Forgeworks/Machines/MC_DRILL",
        "importedAt": "2026-10-21T10:31:40Z",
        "importedBy": "fw_sync.py@0.1",
        "assets": {
          "mesh":     "/Game/Forgeworks/Machines/MC_DRILL/SM_MC_DRILL.SM_MC_DRILL",
          "material": "/Game/Forgeworks/Machines/MC_DRILL/M_MC_DRILL.M_MC_DRILL"
        },
        "importOptions": { "uniformScale": 100, "combineMeshes": true, "generateLightmapUV": true }
      },
      "contentHash": "b71d...",       // 决定"是否过期"
      "styleHash": "a3f9...",         // 风格变了也要重导
      "overridesHash": "c0de..."      // 3D 编辑器里的变换改动
    }
  }
}
```

### 4.3 资产状态机（F3 的标记就是它）

```
                  ┌──────────┐
   从未导出 ──────▶│  none    │ 灰色 · 未导出
                  └────┬─────┘
                       │ 导出
                  ┌────▼─────┐
                  │ exported │ 绿色 ✓ 已导出，且内容未变
                  └────┬─────┘
        内容/风格/变换改动│
                  ┌────▼─────┐
                  │  stale   │ 黄色 ⟳ 有改动待重导
                  └────┬─────┘
                       │ 目录被外部删了
                  ┌────▼─────┐
                  │ missing  │ 红色 ✕ 记录里有、磁盘上没有
                  └──────────┘

   外部同时改了 ──▶ conflict  橙色 ⚠ 需人工裁决（留档到 _Sync/conflicts/）
```

**判断"是否过期"的三把哈希**：
- `contentHash`：机器数据（名称/占地/分类/配方关联）的 hash
- `styleHash`：当前风格预设 + 旋钮 + 该机器的强调色的 hash
- `overridesHash`：3D 编辑器里做的变换覆盖的 hash

三者任一变化 → `stale`。这样**改了风格，所有资产自动变黄**，符合直觉。

### 4.4 冲突解决

冲突只可能发生在"工具认为已导出"且"磁盘文件被外部改过"时：

1. Bridge 用 `sha1` 检测 `_Source` 下的文件是否被外部改动
2. 若 `sha1(磁盘) != manifest.files[x].sha1` → 标记 `conflict`
3. 界面上给三个选项：**用我的覆盖磁盘** / **用磁盘的覆盖我的** / **另存为副本**（默认，最安全）
4. 两边都留档到 `_Sync/conflicts/<id>-<时间戳>/`

**`_Source` 下的文件视为"工具生成物"，外部改动默认会被覆盖**——但覆盖前一定提示，不静默。唯一例外：如果同时存在 `<name>.blend` 或 `<name>.edited.glb`，视为"美术精修版"，工具**不覆盖**，改为读它的几何。

---

## 5. 同步协议

### 5.1 导出流程（F2/F4/F6）

```
用户点「导出」或改动触发
   │
   ├─1 前端收集：机器数据 + 当前风格 + overrides
   │     POST /api/export/machine { id, data, style, overrides }
   │
   ├─2 Bridge 生成（服务端做，因为要写二进制 + 可能调 Blender）
   │     a. 构建图元（复用 buildMachineParts 的逻辑，需要移植到 Python 或由前端传几何）
   │     b. 写 _Source/Machines/<ID>/<ID>.glb
   │     c. 写 <ID>.meta.json（层级 / 变换 / 材质槽 / 动画 / 风格快照）
   │     d. 生成贴图：程序化生成 basecolor / normal / ORM（见下）
   │     e. 生成图标 PNG（前端 SVG → 栅格化，或服务端用 cairosvg）
   │     f. 更新 manifest.json（写 sha1 / mtime / state=exported）
   │
   ├─3 通知 UE（若连接）
   │     SSE → UE 侧 Python 监听器：{ type:"import", ids:["MC_DRILL"] }
   │
   └─4 UE 导入后回写
         POST /api/ue/report { id, ue:{contentPath, assets, importOptions} }
         Bridge 更新 manifest.ue + state
         SSE → 前端刷新标记
```

**关键决策：几何构建放哪？**

现有 `buildMachineParts()` 是 JS。两个选择：

| 方案 | 优点 | 缺点 |
|---|---|---|
| **甲：前端构建 → 传 GLB 二进制给 Bridge** | 复用现有代码，零重复；three.js 的 GLTFExporter 已验证可用 | 大文件走 HTTP（GLB 约 90KB，可接受） |
| 乙：Bridge 用 Python 重建几何 | 服务端可批量、可无头 | 要重写 900 行几何逻辑，必然漂移 |

**选甲**。GLB 已经是成熟产物（测试验证 90840 字节 / 1 网格 / 5 材质槽），直接上传即可。Bridge 只负责落盘 + 清单 + 通知。

前端上传：
```js
const glb = await V.toGLBBlob();           // 已有 toGLB，加个返回 Blob 的重载
await fetch('/api/export/machine', {
  method: 'POST',
  body: JSON.stringify({ id, glb: base64(glb), meta, tex: {...} })
});
```
> 注：90KB 的 GLB 用 base64 是 120KB，HTTP 完全无压力。贴图若到 1MB 级，改用 `multipart/form-data` 二进制直传。

### 5.2 ⚠️ 单位与轴向陷阱（必须写进代码）

**两个陷阱，都会让模型"看起来不对"：**

1. **单位**：glTF 规范 1 unit = 1 米，UE 1 unit = 1 厘米。
   直接导入 → 模型只有 1/100 大小。必须 `import_uniform_scale = 100.0`。
   （实测确认：Blender 读取同一 GLB 得到 2.791 米，说明 GLB 本身是对的，错只在 UE 导入参数。）

2. **轴向**：glTF 是 **Y-up**（Y 是高），UE 和 Blender 都是 **Z-up**（Z 是高）。
   - Blender 导入 glTF 会**自动**做 Y→Z 转换（实测：glTF 的 Y=2.791 变成 Blender 的 Z=2.791 ✅）
   - UE 的 Interchange/GLTF 导入器同样自动转换
   - **但注意**：浏览器 meta 里的 `sizeM: [x, y, z]` 是 glTF 坐标（y=高），
     而 Blender/UE 里量出来是 `[x, z, y]`。做尺寸对比校验时要按轴对应，不能直接比数组。

验收标准（写死）：
- UE 里量 SM 包围盒 ≈ `200 × 195 × 279` 厘米（不是 2.0 厘米）
- Z 轴（高）≈ 279 cm
- 底部在原点（Z min ≈ 0）

### 5.3 UE 5.8.3 的两个坑（实测来源）

1. **`AssetTools.import_asset_tasks` 在 commandlet 里会崩**（缺 Slate application）。
   → 用 `unreal.InterchangeManager.get_interchange_manager_scripted().import_scene(...)`。
2. **5.8.3 的 automated import 不再自动保存资产**（5.7.3 会保存）。
   → 导入后必须 `unreal.EditorAssetLibrary.save_directory(dest, only_if_is_dirty=False, recursive=True)`，否则磁盘上什么都没有，但脚本会"报告成功"。

这两条必须写进 UE 脚本和验收清单，否则会出现"工具说导出了、UE 里找不到"的诡异现象。

### 5.4 贴图生成策略

法线贴图（F4 要求）怎么来？程序化图元本身没有法线贴图。三个选项：

| 方案 | 做法 | 质量 | 工作量 |
|---|---|---|---|
| **甲：不生成，用引擎默认平法线** | 硬表面模型本来就可以不用法线贴图 | 够用 | 0 |
| 乙：程序化生成细节法线 | 用 Canvas 生成噪声/拉丝/划痕法线，平铺 | 中等 | 中 |
| 丙：从高模烘焙 | 需要 Blender + 高低模 | 高 | 大 |

**建议：默认甲（不生成），提供乙作为可选开关。** 因为体素风格的核心是"平直着色 + 大色块"，法线贴图反而会破坏风格。这一点建议在风格预设里加字段 `needsNormalMap: false`。

同理 ORM 贴图：单色材质的情况下，直接用材质参数比贴图更好维护。

**如果确实需要贴图**，走乙方案：Bridge 用 Pillow 生成 512×512 的 PNG（噪声/条纹/网格），写进 `tex/`。这个纯粹是"让 UE 里有东西可挂"。

### 5.5 反向加载（F7）

分两个层次，**建议先做轻的**：

| 层次 | 数据来源 | 能拿到什么 | 难度 |
|---|---|---|---|
| **L1：清单级** | UE 侧 Python 扫 `AssetRegistry` → 写 `ue_assets.json` | 每个资产是否存在、路径、类型、依赖、大致包围盒 | 低 |
| L2：几何级 | 解析 `.uasset` 头部 / 或 UE 导出 GLB 回读 | 真实三角面、材质参数 | 高 |

L1 的产物：
```jsonc
// _Sync/ue_assets.json（由 UE 侧写）
{
  "generatedAt": "2026-10-21T10:35:00Z",
  "assets": [
    {
      "objectPath": "/Game/Forgeworks/Machines/MC_DRILL/SM_MC_DRILL.SM_MC_DRILL",
      "class": "StaticMesh",
      "bounds": { "x": 200.0, "y": 195.0, "z": 340.0 },
      "triangles": 612,
      "materialSlots": ["M_MC_DRILL"],
      "dependencies": ["/Game/Forgeworks/Machines/MC_DRILL/M_MC_DRILL"]
    }
  ]
}
```

工具读到它后：
- 在机器列表显示"UE 侧已存在 ✓ / 有 612 三角面"
- 显示"UE 里的尺寸 vs 设计尺寸"的差异（**这个很有用**，能立刻发现单位错了）
- 若 UE 侧存在但 manifest 里没有 → 标记 `external`（目录里翻出来的，可"收养"进来）

**L2 暂不做**。理由：几何的真相应该在工具里，UE 只是消费方。真要看 UE 里的模型，用 UE 自己看更方便。

> 如果需要 L2，最省力的路径是：UE 侧 Python 把资产导出成 GLB 到 `_Sync/ue_export/`，工具再读。但这会造成"两个几何真相"，容易出问题。

---

## 6. 3D 视图精细化设计

### 6.1 现状与差距

| 能力 | 现在 | 目标（F8-F11） |
|---|---|---|
| 坐标轴 | ❌ 无 | `AxesHelper` + 可读标签 + 地面网格 |
| 局部/全局 | ❌ 无 | gizmo 空间切换，界面显示当前坐标系 |
| 父子关系 | ⚠️ 部件平铺数组，无层级 | 树形结构 + 大纲面板 + 层级连线可选显示 |
| 选中 | ❌ 无 | 点击 / 大纲点选，高亮描边 |
| 移动旋转缩放 | ❌ 无 | `TransformControls` + 吸附 + 数值输入 |
| 撤销 | ❌ 无 | 栈式撤销/重做（至少 50 步） |

### 6.2 层级模型（F10 的基础）

现在 `buildMachineParts()` 返回**平铺**的 `parts[]`。要支持父子关系，需要改成树：

```js
// 现在
parts = [ {kind:'box', c:[0,0.09,0], role:'base'}, {kind:'cyl', ...}, ... ]

// 目标
parts = [
  { id:'root',              kind:'group', parent:null,  transform:{...} },
  { id:'base',              kind:'box',   parent:'root', transform:{...}, geo:{...} },
  { id:'tower',             kind:'group', parent:'root', transform:{...} },
  { id:'tower/column',      kind:'cyl',   parent:'tower', transform:{...} },
  { id:'tower/drill',       kind:'cyl',   parent:'tower', transform:{...}, anim:{spin} },
]
```

**改造策略（不破坏现有渲染）**：
- 保留 `c:[x,y,z]` 绝对坐标作为"初始位置"
- 层级只用于**组织与继承**：父节点的变换会累加到子节点
- 初始状态下所有节点的局部变换 = 单位矩阵，所以渲染结果与现在**完全一致**（这一点必须用截图对比验证）

这样改造风险可控：渲染管线不变，只是多了一层矩阵合成。

**语义分组**（比纯几何分组更有用）：按功能分组而不是按图元类型：
```
MC_SMELTER
├─ 基座
├─ 炉体
│  ├─ 炉膛（发光）
│  ├─ 炉门
│  └─ 出料口
├─ 烟囱
│  ├─ 管身
│  └─ 顶罩
└─ 检修梯
```
这个分组需要在 `buildMachineParts` 的 32 个 case 里逐个标注 `group`。工作量不小但一次到位。

**折中方案**：先自动按 `role` + 空间邻近聚类生成分组（基座 / 主体 / 附属 / 发光件），允许后续手工覆盖。这样不用改 32 个 case。

### 6.3 变换编辑（F11）

用 three.js 的 `TransformControls`（r147 的 `examples/js/controls/TransformControls.js`，需 vendor 进来）：

```js
const gizmo = new THREE.TransformControls(camera, renderer.domElement);
gizmo.addEventListener('dragging-changed', e => orbit.enabled = !e.value);
gizmo.addEventListener('objectChange', () => { /* 更新数值面板 + 标脏 */ });
gizmo.setSpace('local' | 'world');        // F9
gizmo.setMode('translate' | 'rotate' | 'scale');
gizmo.setTranslationSnap(0.05);            // 5cm 吸附
gizmo.setRotationSnap(THREE.MathUtils.degToRad(15));
gizmo.attach(selectedObject);
```

配套交互：

| 操作 | 实现 |
|---|---|
| 选中 | `Raycaster` 命中子物体 → 向上找可编辑节点 → 高亮 |
| 多选 | Shift/Cmd 点击累加；gizmo 附着到多选的临时父节点 |
| 局部/全局切换 | 快捷键 `X` 或按钮；HUD 显示当前空间 |
| 吸附 | 按住 `Ctrl` 临时关闭吸附（Blender 习惯） |
| 数值输入 | 侧栏 `Position / Rotation / Scale` 三个输入组，双向绑定 |
| 聚焦 | 双击大纲项 → 相机飞向该物体 |
| 隐藏/独显 | 大纲项上的眼睛图标 |
| 撤销 | `Cmd+Z` / `Cmd+Shift+Z`，记录 transform 快照 |

### 6.4 变换数据存哪？（关键设计）

用户挪动部件后，改动必须能：
1. 立刻反映在 3D 里
2. 导出时写进 GLB
3. 下次打开还在
4. 能一键还原成程序化默认

**设计：`overrides` 差异层**

```jsonc
// S.machines[i].ui3d
{
  "overrides": {
    "tower/drill": {
      "pos":   [0, 0.15, 0],       // 相对初始位置偏移
      "rot":   [0, 0, 15],          // 度，XYZ 欧拉
      "scale": [1, 1, 1.2]
    },
    "base/leg_L": { "hidden": true }
  },
  "version": 1
}
```

- **不覆盖原始程序化定义**：`buildMachineParts()` 永远产出"出厂状态"
- 应用顺序：`出厂几何 → 叠加 overrides → GLB`
- "还原"按钮 = 删掉该节点的 override
- `overridesHash` 用于判断是否需要重新导出

这样即使以后改了 `buildMachineParts` 的算法，用户的编辑也不会丢（只是偏移量可能不再合适，但至少可见可改）。

### 6.5 材质编辑

选中物体 → 侧栏显示其材质槽：

| 参数 | 控件 | 写入目标 |
|---|---|---|
| 基色 | 取色器 + 十六进制输入 | GLB `pbrMetallicRoughness.baseColorFactor` |
| 金属度 | 滑块 0-1 | `metallicFactor` |
| 粗糙度 | 滑块 0-1 | `roughnessFactor` |
| 自发光 | 取色器 + 强度 | `emissiveFactor`（注意 glTF 上限 1.0） |
| 透明度 | 滑块 + 开关 | `alphaMode` / `baseColorFactor.a` |
| 贴图槽 | basecolor / normal / ORM 三个上传位 | GLB `images` + `textures` |

**材质分两层**（避免冲突）：
- **风格层**：由风格引擎的 `matMap` 决定用哪种材质（steel / rust / ceramic…）
- **覆盖层**：单机器级别的参数覆盖（存在 `ui3d.matOverrides`）

界面上明确显示"当前值来自：风格（体素工业）"或"已被本机器覆盖"，并提供"恢复跟随风格"。

### 6.6 视图布局

```
┌───────────────┬──────────────────────────────────┬──────────────┐
│ 大纲 Outliner │         3D 视口                   │ 属性 Inspector│
│               │                                  │              │
│ ▾ MC_SMELTER  │   [X/Y/Z 轴][网格]                │ 变换         │
│   ▾ 炉体      │                                  │  X [ 0.000]  │
│     • 炉膛 ●  │        ┌───┐                     │  Y [ 1.250]  │
│     • 炉门    │        │   │ ← gizmo 箭头         │  Z [ 0.000]  │
│     • 出料口  │        └───┘                     │ 旋转         │
│   ▸ 烟囱      │                                  │  …           │
│   • 基座      │  [局部/全局] [位移|旋转|缩放]      │ 材质         │
│               │  吸附 5cm  显示网格  线框          │  …           │
└───────────────┴──────────────────────────────────┴──────────────┘
```

---

## 7. 界面设计

### 7.1 机器列表的导出标记（F3）

在现有表格加一列「同步」：

| ID | 名称 | 分类 | … | 同步 | 操作 |
|---|---|---|---|---|---|
| `MC_DRILL` | 地质钻机 | 采集 | | `●` 绿 ✓ | 3D / 编辑 |
| `MC_SMELTER` | 电弧熔炉 | 冶炼 | | `⟳` 黄 | 3D / 编辑 |
| `MC_ARC` | 电弧炉 | 冶炼 | | `○` 灰 | 3D / 编辑 |
| `MC_X` | 已删的旧机器 | — | | `✕` 红 | — |

顶部工具条：
```
[全部导出] [仅导出过期的 (5)] [导入清单] [重新扫描] [打开目录]
```
状态汇总条：`32 个资产 · 24 已导出 · 5 待更新 · 1 缺失 · 2 未导出`

### 7.2 同步面板（新视图）

独立的「同步」视图，展示：
- 绑定状态（项目路径、uproject 校验结果、最后同步时间）
- 全量资产表（含真实文件大小、sha1 前 8 位、UE 侧资产路径）
- 差异详情（哪些文件变了、是内容变了还是风格变了）
- 冲突列表与裁决入口
- 日志（最近 50 条同步操作）

---

## 8. 分阶段实施计划

| 期 | 内容 | 产出 | 验收标准 | 预估 |
|---|---|---|---|---|
| **P0** 地基 | Bridge 服务升级（`/api/fs`、`/api/export`、SSE）+ 目录约定 + manifest 读写 | `tools/bridge.py`、`docs/sync-design.md` | 能绑定项目目录、能创建目录树、manifest 能读写、SSE 能推送 | 中 |
| **P1** 导出 | GLB/贴图/图标/元数据落盘 + 状态机 + 机器列表标记 + **质量门禁** | `js/sync.js`、`js/views/sync.js` | 点导出 → 目录里出现完整文件树；标记正确变色；删文件后变红；三角面超 900 告警 / 超 1800 红灯 | 中 |
| **P1.5** Blender 通道 | Bridge 探测 Blender → 导入 GLB 校验（网格/材质/包围盒）→ EEVEE 渲染缩略图 | `tools/fw_blender.py` | MC_DRILL 导出后 3 秒内列表出现真实渲染缩略图；网格数≠1 或材质数≠5 时报错 | 小（已验证可行） |
| **P2** UE 导入 | `fw_sync.py`（UE 侧）+ Interchange 导入 + 单位 scale + 保存 + 回写 | `ue/fw_sync.py`、`docs/ue-import.md` 增补 | 在 Windows UE 5.8.3 上：点导出 → UE 里出现**正确尺寸**的 SM + 材质；manifest 回写资产路径 | 中（坑多，需实测） |
| **P3** 反向加载 | UE 侧扫 AssetRegistry → `ue_assets.json` → 工具展示 | `ue/fw_registry.py` | 工具能显示"UE 侧已有 612 三角面、尺寸 200×195×340cm"；尺寸不符时告警 | 小 |
| **P4** 3D 编辑 | 层级树 + 大纲 + 选中 + TransformControls + 局部/全局 + 吸附 + 撤销 | 改造 `viewer3d.js`、新增 `js/views/editor3d.js` | 能选中一个部件、拖动、看坐标轴、切局部/全局、Cmd+Z 撤销；初始渲染与改造前像素级一致 | **大** |
| **P5** 材质编辑 | 材质面板 + 参数覆盖 + 贴图上传 + 恢复跟随风格 | `js/views/editor3d.js` 扩展 | 改基色 → 3D 立刻变 → 导出 → GLB 里 `baseColorFactor` 正确 | 中 |
| **P6** 实时与冲突 | watchdog 监听 + 冲突检测 + 裁决界面 + `.blend` 精修回灌 | `tools/bridge.py` 扩展 | 外部删文件 → 界面 3 秒内变红；外部改文件 → 弹冲突裁决 | 中 |

**依赖关系**：P0 → P1 → P1.5 / P2 / P3（可并行）→ P4 → P5 → P6

**建议的推进顺序**：先 P0+P1+P1.5（工具侧闭环 + Blender 缩略图，**全部可在 Mac 上验证**，不依赖 UE），再 P2/P3（需要 Windows 实测），P4 可以穿插做（纯前端）。

> P1.5 放在 P2 之前是有意的：Blender 校验能在模型进 UE **之前**拦住几何问题
> （网格碎片化、材质槽丢失、尺寸异常），省掉 UE 侧排查时间。而且 Mac 上就能跑。

---

## 9. 风险清单

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **单位错 100 倍** | 模型进 UE 变成螺丝钉 | 强制 `import_uniform_scale=100`；验收时量包围盒；工具界面显示"设计尺寸 2.0m = UE 200cm" |
| R2 | **UE 5.8.3 自动导入不保存** | 脚本报成功但 UE 里没有 | 导入后强制 `save_directory`；验收标准写死"文件夹里必须有 .uasset" |
| R3 | `AssetTools.import_asset_tasks` 在 commandlet 崩溃 | 无法无头批量导入 | 改用 InterchangeManager；或只在编辑器内跑 |
| R4 | GLB 导入后网格被拆成多个 | 材质槽对应错乱 | 用 `mergeBufferGeometries` 已合并；导入参数 `combine_meshes`；验收检查"1 个 SM" |
| R5 | **Mac 无法测 UE 集成** | 关键路径未验证就交付 | P2 明确要求 Windows 实测；Mac 侧只做文件落盘验证 |
| R6 | 浏览器缓存导致看到旧代码 | 排查成本高 | `tools/stamp.py` 版本戳（已解决） |
| R7 | UE 编辑器占用文件锁 | 导入失败 | 检测 `Saved/` 下锁文件；提示关闭编辑器；或改为"生成中间文件 → 用户手动点导入" |
| R8 | 大贴图走 HTTP 慢 | 卡顿 | 默认不生成贴图；需要时用 multipart 二进制直传；>4MB 提示 |
| R9 | 3D 层级改造破坏现有渲染 | 32 个建筑全变形 | 初始局部变换=单位矩阵；改造前后截图逐像素对比；测试加"包围盒不变"断言 |
| R10 | override 与实际几何脱节 | 用户编辑后改了算法，部件跑偏 | override 存相对偏移不是绝对值；提供"重置该节点"；导出前校验包围盒异常告警 |
| R11 | **Blender 在移动硬盘**，挂载点不稳定（`/Volumes/KingstonXS1000Media`） | Blender 通道失效 | 多候选路径探测 + 缓存 + 未挂载时降级（缩略图改用前端 SVG，标"Blender 不可用"） |
| R12 | Blender 5.2 API 与 4.x 有差异（Principled BSDF 输入改名等） | 脚本在新版上崩 | 脚本里做属性存在性检查（`if "X" in node.inputs`）；版本探测写进 manifest |
| R13 | EEVEE 渲染缩略图 6s/张，32 个建筑 = 3 分钟 | 批量重导慢 | 单进程批量渲染（省启动开销）+ 256×256 + 只在几何/材质变化时重渲 + 队列化后台跑 |
| R14 | 三角面超预算（实测 2580 vs 规格 900） | UE 侧性能、LOD 成本 | P1 质量门禁；圆柱段数 20→12（体素风格足够）；必要时做 meshopt 压缩 |

---

## 10. 待你决策的问题

这几个直接决定架构，建议先回答再动手：

**Q1. 同步的"及时"到什么程度？**
- (a) 点按钮才同步（最可控，推荐起步）
- (b) 改动后 2 秒防抖自动写文件（体验好，但容易制造大量 IO 和冲突）
- (c) 双向实时（工具改→目录，目录改→工具，最难，冲突多）

**Q2. `Forgeworks/` 放项目根还是 `Content/` 下？**
- (a) 项目根（推荐：UE 不会报无效资产、好 gitignore）
- (b) `Content/Forgeworks/`（省事，但 UE 会扫描到 `.glb`/`.png` 并报警告）

**Q3. UE 侧导入由谁触发？**
- (a) 工具写文件后就完事，你在 UE 里手动点「导入」（最简单，零插件）
- (b) 工具通过 Bridge 通知 UE 内的常驻 Python 监听器自动导入（体验最好，需在 UE 里跑一个脚本，且 UE 得开着）
- (c) 工具调 `UnrealEditor-Cmd` 无头导入（能批处理，但编辑器开着时会冲突，且启动慢）

**Q4. 3D 编辑的粒度：只改整体变换，还是要改每个部件？**
- 只改整体（简单，1 天）
- 每个部件独立变换 + 层级（你要的效果，约 P4 一整期）
- 还要能增删部件（工作量大很多）

**Q5. 贴图怎么办？**
- (a) 不生成，用纯色材质（推荐，符合体素风格，法线贴图反而破坏风格）
- (b) 程序化生成噪声/划痕贴图（折中）
- (c) 你在 Blender 里手工做（质量最好，但要走外部流程）

**Q6. Blender 通道做到哪一档？**
（已实测：你的 Blender 5.2.0 在移动硬盘可用，后台模式 0.15s 完成 GLB 导入校验，6s 出缩略图）
- (a) 档 1：校验 + 缩略图（**推荐**，已验证可行，Mac 上就能跑，能在进 UE 前拦住几何问题）
- (b) 档 1 + 档 2：再加 `.blend` 生成脚本（给美术一个建模起点）
- (c) 档 1+2+3：再加精修回灌（美术在 Blender 改完，工具优先用他的版本）
- (d) 暂不集成 Blender

---

## 附：本方案对现有代码的改动面

| 文件 | 改动 | 性质 |
|---|---|---|
| `tools/serve.py` | 升级为 `bridge.py`（+ API + SSE + watchdog） | 扩展 |
| `tools/fw_blender.py` | 新增：Blender 调用脚本（导入校验 + 缩略图渲染 + `.blend` 生成） | 新增 |
| `js/engines/viewer3d.js` | 加层级、选中、gizmo；`toGLB` 加返回 Blob | 中改 |
| `js/views/editor3d.js` | 新增：3D 编辑器视图（大纲 + 属性 + 视口） | 新增 |
| `js/sync.js` | 新增：与 Bridge 通信、状态机、hash | 新增 |
| `js/views/sync.js` | 新增：同步面板 | 新增 |
| `js/views/machines.js` | 加「同步」列 | 小改 |
| `js/data/styles.js` | 加 `needsNormalMap`、三角面预算等字段 | 小改 |
| `js/main.js` | 启动时探测 Bridge 是否在线（离线则禁用同步功能） | 小改 |
| `ue/fw_sync.py` | 新增：UE 侧导入 + 回写 | 新增 |
| `ue/fw_registry.py` | 新增：UE 侧扫 AssetRegistry | 新增 |
| `tests/_dumpglb.html` | 已有：headless 导出 GLB 的验证页（P1.5 用它取样本） | 已建 |
| `docs/sync-design.md` | 本文 | 新增 |

---

*待评审。确认 §10 的六个问题后，我按 P0 开始实现。*
