# 尺寸规格、连接点与分层装配设计

- 日期：2026-10-27
- 状态：已确认，待实施
- 相关文档：`docs/pipeline-design.md`、`docs/HANDOFF.md`、`docs/superpowers/specs/2026-10-24-pipeline-auto-adopt-export-design.md`
- 适用范围：机器管线的整体效果图、单件效果图、单件 3D 模型、减面、组装与导出

## 1. 背景

当前机器管线已经能完成“整体效果图 → 单件效果图 → 单件 3D 模型 → 减面 → 组装”，但组装仍然是**包围盒启发式布局**：

- `fw_parts.assemble_parts` 按角色（body/track/boom/bucket/cab）和包围盒比例摆放部件；
- `fw_blender.py` 对铲斗和动臂做一次 KDTree 最近点吸附，只能消掉可见缝，不知道真实的销孔位置；
- 单件模型没有目标尺寸，3D 生成模型的大小和朝向每次都可能不同；
- 单件效果图只产出图片，不产出连接点数据；
- 一个 `assemble` 节点一次性吸收所有部件，任何一件出错都会影响整机，且误差不可定位。

实际表现就是：铲斗与动臂之间出现可见缝，减面后缝隙更明显，靠补丁吸附无法稳定复现。根因不是吸附算法，而是**缺少尺寸基准和连接点契约**。

## 2. 目标与非目标

### 2.1 目标

1. 以**结构化 spec** 作为尺寸和连接关系的唯一事实来源，可人工查看和修改。
2. 从整体效果图提取整机比例、部件尺寸和连接关系；绝对尺寸由用户输入或机型模板锚定。
3. 单件 3D 模型下载后自动校准：朝向规范化、按目标尺寸缩放、记录实际包围盒和误差。
4. 单件效果图阶段确定性产出连接点（端口）数据，随部件传递到装配。
5. 新增二元 `mate` 节点：只把有直接连接关系的两个装配体按端口刚性对齐，输出子装配；子装配再参与下一级。
6. 三视图分两类：AI 概念三视图用于生成参考；Blender 正交尺寸图从真实网格渲染，用于尺寸验收。
7. 每一级装配都有可读的误差报告（间隙、轴向角误差、包围盒偏差），缺端口不静默兜底。
8. 旧图和旧 `assemble` 节点保持可用；新能力是附加式的。

### 2.2 非目标

- 不把视觉模型当作精确量具；vision 只提供比例、角色和连接关系。三视图是尺寸节点唯一的图像输入，用于比例估计，仍不做像素测量。
- 尺寸不再来自模板预设或单张 3/4 效果图：整体概念图 → 整体三视图 → `blueprint(scope=overall)`；单件图 → 单件三视图 → 同一个 `blueprint(scope=part)`。
- 不做自动 CAD 重建，不生成工程级制造图。
- 不支持任意曲面接触和柔性连接；P3 只支持销轴、法兰、贴合面三类端口。
- 不改变 Provider 协议，不新增远程模型服务。
- 不自动发起付费调用；`blueprint`、`threeView`、单件图、单件模型都走现有 `confirmRemote` 门禁。
- 不自动迁移现有挖掘机图；迁移由用户显式触发。
- 不改变 `schemaVersion`，旧图仍按版本 1 加载。

## 3. 核心决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 尺寸事实来源 | 结构化 spec JSON，可编辑 | 视觉比例不可靠，必须有人可修正的契约 |
| 绝对尺寸锚 | `blueprint.params.overallLengthM`，缺省时用机型模板，再缺则报错 | 没有锚就无法把比例变成米 |
| 连接点来源 | spec + 角色模板确定性生成，不依赖图像识别 | 图像模型给不出可靠坐标 |
| 端口坐标 | 包围盒归一化 `[0,1]³`，校准后换算为米 | 缩放后仍有效 |
| 装配粒度 | 二元 `mate`，端口刚性对齐 | 误差可定位、可回滚，符合直接连接关系 |
| 装配树 | 从连接图生成生成森林，按根角色后序遍历 | 避免环，保证每级只处理直接连接 |
| 默认缩放 | 均匀缩放；轴向比例误差 >5% 告警 | 不默认拉伸变形 |
| 三视图 | AI 概念图 + Blender 正交精确图 | 前者像，后者准 |
| 减面位置 | 单件减面后保留装配端口，再进入 mate | 沿用用户现有 10k 减面要求 |
| 兼容策略 | 新类型附加，旧 `assemble` 保留 | 不破坏现有项目图 |

## 4. 总体架构

### 4.1 分层

```
┌──────────────────────────────────────────────────────────────┐
│ Spec 层                                                       │
│ 整体效果图 ──► blueprint ──► spec.json（尺寸/角色/连接/端口） │
│                    │                                          │
│                    └──► threeView ──► AI 概念三视图（参考）   │
├──────────────────────────────────────────────────────────────┤
│ Part 层                                                       │
│ spec ──► partImage（每件）──► 单件图 + ports                  │
│ 单件图 + spec + ports ──► partModel ──► 校准后的单件 assembly │
│ assembly ──► decimate（保留端口）──► 10k 单件 assembly        │
├──────────────────────────────────────────────────────────────┤
│ Assembly 层                                                   │
│ assembly(bucket) + assembly(boom) ──► mate ──► asm_boom       │
│ asm_boom + assembly(body)         ──► mate ──► asm_body       │
│ asm_body + assembly(cab/track)    ──► mate ──► asm_root       │
├──────────────────────────────────────────────────────────────┤
│ Verify 层                                                     │
│ asm_root ──► validate/尺寸报告 ──► Blender 正交尺寸图 ──► 导出 │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 挖掘机目标链

```
bucket + boom        → mate → asm_boom
asm_boom + body      → mate → asm_body
asm_body + cab       → mate → asm_body_cab
asm_body_cab + track → mate → asm_root
asm_root.mesh        → validate → export
```

每一级的输入都只有直接连接的装配体，符合“不要把所有模型一次性汇聚到一个节点”的原则。

### 4.3 新旧路径并存

- 旧图：`partModel → decimate(mesh) → assemble(part) → export`，行为不变。
- 新图：`partModel(assembly) → decimate(assembly) → mate(assembly) → export`。
- `partModel` 只有在接了 `spec` 输入时才输出带校准和端口的 `assembly`；否则只输出旧 `part`/`mesh`。
- 旧 `assemble` 的 KDTree 吸附保留，仅服务旧路径；新路径缺端口直接报错，不吸附。

## 5. 数据模型

### 5.1 spec

spec 由 `blueprint` 节点产出，保存到 `<asset>/pipeline/spec.json`，也可由 UI 直接编辑。

```json
{
  "schemaVersion": 1,
  "assetId": "MC_EXCAVATOR",
  "units": "m",
  "overall": {
    "lengthM": 7.2,
    "widthM": 2.4,
    "heightM": 3.1,
    "source": "user",
    "confidence": 0.9
  },
  "assembly": {
    "rootRole": "body"
  },
  "parts": {
    "body": {
      "role": "body",
      "sizeM": [4.2, 1.6, 1.4],
      "forward": "+X",
      "confidence": 0.8,
      "ports": [
        {
          "id": "boom_base",
          "type": "pin",
          "anchor": [0.62, 0.5, 0.7],
          "axis": [1, 0, 0],
          "normal": [0, 0, 1],
          "radiusM": 0.08
        }
      ]
    },
    "boom": {
      "role": "boom",
      "sizeM": [3.6, 0.5, 0.7],
      "forward": "+X",
      "confidence": 0.75,
      "ports": [
        {
          "id": "base_pin",
          "type": "pin",
          "anchor": [0.02, 0.5, 0.5],
          "axis": [-1, 0, 0],
          "normal": [0, 0, 1],
          "radiusM": 0.08
        },
        {
          "id": "tip_pin",
          "type": "pin",
          "anchor": [0.98, 0.5, 0.35],
          "axis": [1, 0, 0],
          "normal": [0, 0, 1],
          "radiusM": 0.06
        }
      ]
    },
    "bucket": {
      "role": "bucket",
      "sizeM": [1.15, 1.2, 1.05],
      "forward": "+X",
      "confidence": 0.7,
      "ports": [
        {
          "id": "ear_pin",
          "type": "pin",
          "anchor": [0.02, 0.5, 0.78],
          "axis": [-1, 0, 0],
          "normal": [0, 0, 1],
          "radiusM": 0.06
        }
      ]
    }
  },
  "connections": [
    {
      "id": "c_boom_base",
      "a": "boom:base_pin",
      "b": "body:boom_base",
      "joint": "pin"
    },
    {
      "id": "c_bucket_boom",
      "a": "bucket:ear_pin",
      "b": "boom:tip_pin",
      "joint": "pin"
    }
  ],
  "notes": []
}
```

字段规则：

- `parts` 的 key 是角色名，与现有 `part_role()` 的取值一致：body/track/wheel/boom/bucket/cab/roof/door/window。
- `sizeM` 是目标包围盒尺寸，顺序为 `[X, Y, Z]`，单位米。
- `forward` 是部件朝向，允许 `+X/-X/+Y/-Y/+Z/-Z`；用于校准时的符号消歧。
- `anchor` 是包围盒归一化坐标，`[0,1]³`；允许略微超出范围，但会告警。
- `axis` 是端口外指方向，`normal` 是绕轴旋转的参考方向，二者均为部件局部单位向量。
- `connections` 的端点写成 `role:port`；同一个端口最多参与一条主连接，环由装配树处理。
- `assembly.rootRole` 缺省为 `body`；没有 body 时取连接图中度数最高的角色。
- `overall.source` 取 `user`、`template`、`vision`；`vision` 不能单独提供绝对尺寸。
- `confidence` 低于 0.4 的部件在 UI 标黄，但不阻断。

### 5.2 端口（ports）

端口是 spec 在部件上的解析结果，随部件结果传递：

```json
{
  "partId": "partModel_bucket",
  "role": "bucket",
  "sizeM": [1.15, 1.2, 1.05],
  "fit": {
    "mode": "uniform",
    "scale": 0.83,
    "aspectError": 0.04,
    "rotationDeg": [0, 0, 90],
    "measuredBbox": {"min": [-0.58, -0.60, 0.0], "max": [0.57, 0.60, 1.05]},
    "grounded": false
  },
  "ports": [
    {
      "id": "ear_pin",
      "type": "pin",
      "anchorNorm": [0.02, 0.5, 0.78],
      "pos": [-0.55, 0.0, 0.82],
      "axis": [-1, 0, 0],
      "normal": [0, 0, 1],
      "radiusM": 0.06
    }
  ]
}
```

- `pos` 是校准后部件局部坐标系中的米制位置。
- `axis`/`normal` 经过同一校准旋转。
- `fit` 只在校准启用时存在；没有 spec 的旧部件不产生 `fit`。

### 5.3 assembly

```json
{
  "schemaVersion": 1,
  "assemblyId": "asm_boom",
  "assetId": "MC_EXCAVATOR",
  "meshPath": "outputs/asm_boom.glb",
  "parts": [
    {"partId": "partModel_bucket", "role": "bucket", "meshPath": "outputs/bucket_10k.glb"},
    {"partId": "partModel_boom", "role": "boom", "meshPath": "outputs/boom_10k.glb"}
  ],
  "connectors": [
    {
      "id": "bucket:ear_pin",
      "owner": "bucket",
      "frame": {"pos": [0.0, 0.0, 0.0], "axis": [-1, 0, 0], "normal": [0, 0, 1]},
      "radiusM": 0.06
    },
    {
      "id": "boom:tip_pin",
      "owner": "boom",
      "frame": {"pos": [0.0, 0.0, 0.0], "axis": [1, 0, 0], "normal": [0, 0, 1]},
      "radiusM": 0.06
    }
  ],
  "mates": [
    {
      "id": "c_bucket_boom",
      "a": "bucket:ear_pin",
      "b": "boom:tip_pin",
      "offsetM": -0.002,
      "gapM": 0.0,
      "axisErrorDeg": 0.2,
      "status": "ok"
    }
  ],
  "warnings": []
}
```

- `meshPath` 是子装配导出文件，路径相对资产目录。
- `parts` 保留来源部件列表，导出时作为 GLB 内的多个 mesh 对象，不合并、不改名。
- `connectors` 是子装配局部坐标系中的端口；子装配参与下一级 `mate` 时直接使用。
- `mates` 是形成该子装配的内部连接记录，根装配汇总所有级别。

### 5.4 部件结果扩展

`partImage` 结果新增：

```json
{"output": {"generated_image_url": "...", "ports": [ /* 端口列表；此阶段只有 anchorNorm/axis/normal/radiusM，无米制 pos */ ]}}
```

`blueprint(scope=part)` 结果新增：

```json
{"output": {"measure": {
  "schemaVersion": 1, "scope": "part", "role": "wheel", "partId": "threeView_wheel",
  "sizeM": [4.0, 1.7, 0.7], "forward": "+X", "confidence": 0.7,
  "anchor": {"overallLengthM": 4.2, "template": "car"},
  "views": {"sheet": "outputs/threeview_wheel_sheet.png"}, "notes": ""}}}
```

`partModel` 结果新增：

```json
{
  "output": {
    "model_url": "...",
    "localPath": "outputs/model_<taskId>.glb",
    "measure": { /* 上游 measure；无则为 null */ },
    "measureHash": "<sha256>",
    "fit": { /* 同 5.2；targetSizeM 记录实际目标尺寸 */ },
    "ports": [ /* 同 5.2 */ ],
    "assembly": { /* 单件 assembly，见 5.3 */ }
  }
}
```

`decimate` 输入 assembly 时，结果新增：

```json
{"output": {"meshPath": "outputs/bucket_10k.glb", "assembly": { /* 端口保留 */ }}}
```

`mate` 结果新增：

```json
{"output": {"meshPath": "model_mate_<nodeId>.glb", "assembly": { /* a.parts+b.parts */ },
  "assemblyPath": "parts/asm_<nodeId>.json", "connection": "c_roof_body",
  "portA": "body:roof_mount", "portB": "roof:mount",
  "gapM": 0.0, "appliedOffsetM": 0.002, "axisErrorDeg": 0.0,
  "warnings": [], "mateHash": "<sha256>", "engine": "blender"}}
```

### 5.5 节点参数

| 节点 | 新参数 | 默认值 | 说明 |
|---|---|---|---|
| `blueprint` | `provider` | `ark` | 视觉 Provider |
| | `scope` | `overall` | `overall` 写 `spec.json`；`part` 只产出 `measure` |
| | `role` | 空 | `scope=part` 时的部件角色 |
| | `overallLengthM` | 空 | 整机长度锚；空则查机型模板 |
| | `template` | `excavator` | 机型模板名 |
| | `prompt` | 空 | 额外视觉提示 |
| | `specLocked` | `false` | 锁定时保留现有 `spec.json`（仅整体） |
| `threeView` | `provider` | `ark` | 图像 Provider |
| | `prompt` | 空 | 三视图风格提示 |
| | `annotate` | `false` | 是否用 Pillow 叠加标注 |
| `partImage` | 无新增 | | 从 spec/ports 输入读取 |
| `partModel` | `fitMode` | `uniform` | `uniform` 或 `perAxis` |
| | `ground` | `false` | 是否把包围盒最低点落到 z=0 |
| | `measure` | 无 | 尺寸优先取上游 measure，其次 `spec.parts[role].sizeM` |
| `mate` | `connection` | 空 | 使用 spec 中的 connection id；空则按角色唯一匹配 |
| | `offsetM` | `-0.002` | 负值为重叠，正值为间隙 |
| | `alignTwist` | `true` | 是否用 normal 约束绕轴旋转 |
| | `ground` | `false` | 装配后整体落到 z=0 |
| `decimate` | `preserveAssembly` | `true` | assembly 输入时保留端口 |

### 5.6 文件布局

```
<asset>/pipeline/
  spec.json                         # 资产级 spec
  graph.json                        # 现有管线图
  parts/
    layout_assemble.json            # 旧组装布局，保留
    part_<partId>.fit.json          # 部件校准报告
    asm_<nodeId>.json               # 装配体 sidecar
  outputs/
    threeview_<nodeId>_sheet.png    # AI 概念三视图原图
    threeview_<nodeId>_front.png    # 本地裁切
    threeview_<nodeId>_annotated.png
    threeview_<nodeId>_exact_front.png  # Blender 正交尺寸图
    model_<taskId>.glb
    asm_<nodeId>.glb
```

所有路径按现有约定存相对资产目录的 POSIX 路径，避免 Windows 反斜杠进入 JSON。

## 6. 节点与端口变更

### 6.1 新端口类型

| 类型 | 含义 | 消费者 |
|---|---|---|
| `spec` | 5.1 的 spec JSON | `threeView`、`partImage`、`partModel` |
| `ports` | 5.2 的端口列表 | `partModel`、assembly 结果与报告 |
| `assembly` | 5.3 的装配体 | `decimate`、`mate` |

端口类型按现有规则精确匹配；新增类型只做附加，不改旧类型。

### 6.2 `NODE_TYPES` 变更

在 `tools/fw_pipeline.py` 的 `NODE_TYPES` 中新增/修改：

```python
'blueprint': {'in': {'image': 'image', 'spec': 'spec', 'text': 'text'},
              'out': {'spec': 'spec', 'measure': 'measure'}},
'threeView': {'in': {'image': 'image', 'spec': 'spec', 'text': 'text'},
              'out': {'sheet': 'image', 'front': 'image', 'side': 'image', 'top': 'image'}},
'partImage': {'in': {'text': 'text', 'image': 'image', 'spec': 'spec'},
              'out': {'image': 'image', 'ports': 'ports'}},
'partModel': {'in': {'image': 'image', 'spec': 'spec', 'ports': 'ports', 'measure': 'measure'},
              'out': {'part': 'part', 'mesh': 'mesh', 'assembly': 'assembly'}},
'decimate': {'in': {'mesh': 'mesh', 'assembly': 'assembly'},
             'out': {'mesh': 'mesh', 'part': 'part', 'assembly': 'assembly'}},
'mate': {'in': {'a': 'assembly', 'b': 'assembly', 'spec': 'spec'},
         'out': {'assembly': 'assembly', 'mesh': 'mesh'}},
'validate': {'in': {'mesh': 'mesh'}, 'out': {'report': 'report'}},
```

`scope=part` 的 `blueprint` 只写 `measure`，绝不写 `spec.json`；多个 `scope=overall` 写者会产生 `SPEC_WRITER_DUPLICATE` 警告。小汽车模板的端口成对取相反轴向（`body:roof_mount` 与 `roof:mount`、`body:wheel_mount` 与 `wheel:wheel_mount`），轮组只保留一个中心港，`mate` 每对部件只走一条 connection。

`PROVIDER_TYPES` 增加 `blueprint`、`threeView`；`LOCAL_STAGE_TYPES` 不变。`MULTI_INPUTS` 不变，`mate` 使用两个单输入端口。Provider 类型映射增加 `threeView → textToImage`、`blueprint → vision`；`partImage`/`partModel` 保持现有映射。

### 6.3 Bridge 映射

`tools/bridge.py`：

- `PROVIDER_NODE_TYPES` 增加 `blueprint`、`threeView`。
- `blueprint` 走 `/chat/completions` 视觉分析，同步返回 `output.spec`；不创建轮询任务，任务 id 记为 `spec_<sha1>`。
- `threeView` 走现有 `textToImage` 提交/轮询，返回一张三格拼图；裁切和标注在本地后处理完成。
- 新增 `POST /api/pipeline/spec/chain`：读取 `<asset>/pipeline/spec.json`，调用 `fw_spec.build_mate_tree`，返回 `{nodes, edges, warnings}`；前端只应用，不重复实现树逻辑。
- 两者都必须在请求体带 `confirmRemote: true`，并校验 loopback origin，沿用现有门禁。
- 错误信息中的 `api_key` 一律脱敏；不把 Provider 原始响应整段写日志。

### 6.4 前端镜像

`js/pipeline.js` 需要同步：

- 节点定义、端口名、颜色、标签：`blueprint`（尺寸规格）、`threeView`（三视图）、`mate`（连接装配）。
- 端口类型颜色：`spec` 金色、`ports` 青色、`assembly` 紫色。
- 节点参数表单：见 5.5。
- `blueprint` 结果面板：spec JSON 查看/编辑、校验状态、confidence 标色、锁定开关。
- `partImage` 结果面板：端口列表（id/type/axis/anchor）。
- `partModel` 结果面板：校准报告（scale/aspectError/rotation）、端口列表。
- `mate` 结果面板：间隙、轴向角误差、连接端口、警告。
- 图操作“根据连接图生成装配链”：调用 `POST /api/pipeline/spec/chain` 获取节点/边计划，应用到画布并自动排布；重复执行时先询问是否替换现有链。
- 旧图加载不因新类型报错；未知类型仍按现有错误路径处理。

### 6.5 校验规则

- `mate` 的两个输入必须是 `assembly`；不允许 `part` 直连。
- `partModel` 的 `spec` 输入可选；接了 spec 才启用校准和 assembly 输出。
- `decimate` 的 `assembly` 输入和 `mesh` 输入互斥，同时存在时报错。
- `blueprint` 的 `overallLengthM` 为空且模板没有对应机型时，节点报 `SPEC_UNANCHORED`。
- 连接图有环时，`fw_spec.build_mate_tree` 保留生成森林，环上的边记入 `warnings`，不阻断。
- 同一个端口出现在两条主连接中时，第二条记 `warning` 并跳过。

## 7. 执行流程

### 7.1 `blueprint`

1. 读取上游整体图；读取 `overallLengthM` 或机型模板。
2. 调用 `fw_providers.analyze_spec`，提示词要求只输出 JSON，字段严格按 5.1。
3. 校验：`schemaVersion`、单位、部件角色、连接端点、尺寸为正、锚点在允许范围。
4. 用绝对锚和比例计算 `parts.sizeM`：vision 给出各部件的相对比例，`blueprint` 先按整体包围盒分别归一化，再按 `overall.lengthM`/`widthM`/`heightM` 的绝对锚换算成米；三个轴分别计算，不用单一长度乘所有轴。
5. 写入 `<asset>/pipeline/spec.json`；一个资产只保留一份 spec，多个 `blueprint` 节点时以最后成功且未锁定的结果为准，并在结果中告警；`specLocked` 为 true 时只校验不覆盖。
6. 节点结果保存 `spec`、`providerTask`、`warnings`、`confidence`；spec 内容哈希一并保存，下游节点用该哈希参与 dirty 判断。
7. 任何字段缺失用模板补齐，并在 `notes` 中标注来源；无法补齐则报错。
8. `scope=part` 时改用 `fw_providers.analyze_dimensions`：输入是上游单件三视图 sheet，prompt 带整机锚与角色，只返回 `sizeM`/`forward`/`confidence`；结果写入节点 `output.measure`，不写 `spec.json`。`spec.parts[role].sizeM` 只作为锚与校验上限，不覆盖 measure。

### 7.2 `threeView`

1. 读取整体图和 spec。
2. 生成提示词：正交前/侧/顶三视图、同一比例、白底、无透视、三格等宽横排、不要文字。
3. 走 `textToImage` 提交/轮询，得到拼图。
4. 本地按三等分裁切为 front/side/top；裁切失败时保留原图并告警。
5. `annotate=true` 时用 Pillow 叠加：
   - 三个面板边框和标题；
   - 整体长/宽/高示意尺寸线（基于面板外框，不声称是像素测量）；
   - 部件尺寸表（从 spec 读取，精确数字）；
   - 端口标记：按 `anchor` 在视图框内画示意圆点和 id；这是示意位置，不是从图像像素测量的真实位置。
6. 输出 `threeview_<nodeId>_sheet.png`、`_annotated.png`、`_front/side/top.png`。
7. 三视图是尺寸节点**唯一**的图像输入：`blueprint` 用它估计比例，再把比例乘到整机绝对锚上；仍然不做像素测量，也不把面板外框当作量具。

### 7.3 `partImage`

1. 读取上游文本、整体图、spec。
2. 用 `_part_image_prompt` 拼接：
   - 角色和中文名；
   - `sizeM` 的目标尺寸；
   - 端口清单（id、type、位置描述）；
   - “单件、正交视角、白底、不要其他部件”。
3. 参考图优先用 `threeView` 的对应视图；没有则用整体图。
4. 生成后，把 spec 中该角色的 ports 解析为 `ports` 输出；只含 `anchorNorm/axis/normal/radiusM`，不含米制 `pos`，`pos` 在 `partModel` 校准后才填。
5. `partModel` 若同时收到 `ports` 输入，以该输入为准；否则回读 spec 中同角色端口。端口优先级固定为：`ports` 输入 > spec。
6. 图像模型不负责生成端口坐标；端口来自 spec，节点只做确定性合并。

### 7.4 `partModel` + fit

1. 上游单件图提交 `imageTo3D`，轮询下载 GLB。
2. 如果接了 `spec`：
   - 调用 Blender `fit` 模式，输入 GLB、目标 `sizeM`、`fitMode`、`ground`、`forward`、ports；
   - 输出校准后的 GLB、`fit` 报告、米制 `ports`；
   - 生成单件 `assembly` 包装（parts 只有自己，connectors 为端口）。
3. 如果没有 spec：保持旧行为，只输出 `part`/`mesh`。
4. 校准是幂等的：结果已存在且输入 GLB/spec 哈希未变时跳过。

### 7.5 `mate`

1. 读取 a、b 两个上游 assembly 结果；读取 `connection` 参数。
2. 从 spec 取 connection，定位 `a` 侧端口和 `b` 侧端口；父装配接节点 `a`，子装配接节点 `b`，spec connection 的 `a`/`b` 端点只用于定位端口，不要求与节点 `a`/`b` 同名；没有 connection 时按角色和端口 id 自动匹配，唯一才使用。
3. 调用 Blender `mate` 模式，输入两个 GLB、两个端口 frame、`offsetM`、`alignTwist`。
4. 输出子装配 GLB、合并后的 parts、变换后的 connectors、mate 报告。
5. 结果写入 `parts/asm_<nodeId>.json`；节点结果保存 `assembly` 和 `meshPath`。
6. 幂等键：a/b 的 meshPath + 端口 + 参数哈希。

### 7.6 自动装配链

前端动作“根据连接图生成装配链”：

1. 读取 spec 的 `connections`、`parts`、`assembly.rootRole`。
2. 请求 `POST /api/pipeline/spec/chain`，由 Python 的 `fw_spec.build_mate_tree` 返回节点/边计划；前端只负责应用，不重复实现树逻辑。
3. 以根角色为根做后序遍历：先叶子连接，生成 `mate` 节点；父连接消费子装配。
4. 自动布局：每级向右一列，纵向按连接顺序排开；避免覆盖现有节点。
5. 生成边：`partModel.assembly → decimate.assembly → mate.a/b`；根 `mate.mesh → validate/export`。
6. 已存在同名链时弹出确认，替换或取消；不自动删除旧 `assemble` 节点。

### 7.7 根装配验证与导出

1. 根 `mate` 输出 `assembly` 和 `mesh`。
2. `validate` 节点新增 `assembly` 输入和装配模式：
   - 整机包围盒 vs spec `overall`，每轴偏差 >3% 告警；
   - 最低点与地面偏差 >5mm 告警；
   - 每个 mate 的 `gapM`/`axisErrorDeg` 汇总；
   - 缺端口、跳过连接、环边列出。
3. `mesh` 继续走现有 `export`；`report` 一并写入。
4. Blender 正交尺寸图从根 GLB 渲染，作为最终尺寸验收图。

## 8. Blender 算法

### 8.1 fit

输入：GLB、目标 `sizeM`、`fitMode`、`ground`、`forward`、ports、可选 `orientationOverride`。

1. 导入并合并同部件的 mesh 对象（保留材质）。
2. 计算世界包围盒 `m = [mx,my,mz]`。
3. 生成 24 个朝向候选（3 个轴的 6 种置换 × 4 种行列式为 +1 的符号组合；排除镜像，保持几何不变形）。
4. 评分：
   - `bboxScore = Σ((m_perm_i - t_i) / t_i)²`；
   - `forwardBonus`：候选的 +X 与 `forward` 一致时减 0.05；
   - `portBonus`：端口 `anchor` 落在候选预期侧时减 0.02；无端口时省略。
5. 取最低分候选；分差 <0.01 时记 `orientationAmbiguous` 警告。
6. 应用旋转到 mesh，重算包围盒。
7. 缩放：
   - 均匀：`s = Σ(t_i * m_i) / Σ(m_i²)`；
   - 逐轴：`s_i = t_i / m_i`，仅 `fitMode='perAxis'` 时使用。
8. 应用缩放；`ground=true` 时平移使 `bbox.min.z = 0`。
9. 应用变换，重算包围盒，写 `fit`：
   - `scale`、`rotationDeg`（Euler XYZ，单位度）、`measuredBbox`、`aspectError = max_i |s*m_i - t_i| / t_i`；
   - `aspectError > 0.05` 警告；`> 0.15` 且 `uniform` 时报错，提示切 `perAxis`。
10. 端口变换：`pos = bbox_min + anchorNorm * (bbox_max - bbox_min)`；`axis`/`normal` 乘旋转矩阵并归一化。
11. 导出校准 GLB，保留对象名。

### 8.2 mate

输入：a GLB + 端口 A、b GLB + 端口 B、`offsetM`、`alignTwist`。

1. 导入 a、b 的所有部件对象；计算各自 assembly 局部 frame。
2. 取端口：
   - `A = {pos, axis, normal}`，`B = {pos, axis, normal}`，均为各自装配体局部坐标。
3. 旋转：
   - `q1 = A.axis.rotation_difference(-B.axis)`；
   - `alignTwist` 且两 normal 有效时，计算绕 `A.axis` 的扭转角，使 `q2(B.normal) ≈ A.normal`；
   - 总旋转 `q = q2 * q1`。
4. 平移：`t = A.pos + A.axis * offsetM - q * B.pos`。
5. 对 b 的所有对象应用 `(q, t)`；重算 b 的 connectors。
6. 计算误差：
   - `targetPos = A.pos + A.axis * offsetM`；
   - `gapM = (targetPos - B'.pos) · A.axis`，是目标位置与落位之间的残余误差，理想为 0；
   - `appliedOffsetM = (A.pos - B'.pos) · A.axis`，负值表示重叠，报告中保留符号；
   - `axisErrorDeg = acos(clamp((-B'.axis) · A.axis, -1, 1))`。
7. `axisErrorDeg > 5` 报错；`1 < axisErrorDeg <= 5` 告警；`offset` 偏差 >0.5mm 告警。
8. 合并：
   - 以 a 的 assembly frame 为子装配 frame；
   - a 的 parts/connectors 保持不变；
   - b 的 parts/connectors 用 `(q,t)` 变换后加入；
   - 记录 mate。
9. 导出子装配 GLB（多 mesh 对象），写 sidecar JSON。

### 8.3 子装配局部 frame

- 子装配 frame 永远是“a 侧”的 frame；b 被变换进来。
- 下一级 mate 把整个子装配当 b 时，所有对象和 connectors 一起乘变换。
- 不把子装配合并成单 mesh，避免丢失部件名和端口归属。
- 根导出时再按需应用世界变换；默认根在原点、z=0。

### 8.4 减面保留端口

`decimate` 输入 assembly 时：

1. 遍历 parts 的每个 GLB，按 `decimateFaces` 对每个对象加 Decimate 修改器并应用。
2. 保留对象名、角色、端口；端口位置不重新拟合（销孔是抽象点，不依赖表面顶点）。
3. 重新导出子装配 GLB；包围盒变化 >1% 时告警。
4. 如果用户需要“减面后重新校准”，在 decimate 前加 fit 或在 partModel 调整目标；默认不二次缩放。

### 8.5 正交尺寸图

1. 加载根装配 GLB。
2. 正交相机：前视 `-Y`、侧视 `+X`、顶视 `+Z`；使用 Workbench 引擎，白底、无透视。
3. 每视图渲染到 `threeview_<nodeId>_exact_<view>.png`。
4. 用实测包围盒和每部件 bbox 叠加尺寸线/标签；数字来自网格，像素位置来自 Blender 投影。
5. 该图与 AI 概念三视图分开命名，UI 明确标注“精确尺寸图”。

## 9. 三视图与标注

### 9.1 AI 概念三视图

- 一次生成三格横排拼图，减少付费调用。
- 提示词要求：orthographic front/side/top、same scale、plain white background、no perspective、no text、three equal panels。
- 本地裁切为三张；若模型没有严格三等分，保留原图并在结果中告警。
- 用途：`blueprint` 的唯一图像输入（整体与单件共用同一节点类型）、`partImage` 参考图、人工理解结构；只做比例估计，**不做像素测量**。

### 9.2 标注

Pillow 12.3.0 已确认可用。标注内容：

- 面板边框、视图标题（前/侧/顶）。
- 整体尺寸示意线：沿面板外框画 L/W/H 箭头，数字来自 spec `overall`；明确是“示意”，不是像素测量。
- 部件尺寸表：角色、目标 `sizeM`、confidence、端口数。
- 端口标记：按 `anchor` 投影到视图平面，画圆点和端口 id。
- 字体：优先 `C:/Windows/Fonts/msyh.ttc`，其次 `arial.ttf`，都没有则用 Pillow 默认字体并改用英文标签。
- 输出 PNG；不覆盖原图。

### 9.3 Blender 精确图

- 从校准后的单件或根装配渲染，数字与网格一致。
- 用于验收：整机尺寸、每部件尺寸、端口在视图中的位置。
- 免费、本地；每次构建后可重新生成。

## 10. 错误处理与校验

| 代码 | 触发 | 行为 |
|---|---|---|
| `SPEC_MISSING` | `partModel`/`mate` 需要 spec 但没有 | 节点 error，下游 blocked |
| `SPEC_INVALID` | JSON/schema/单位/端口非法 | 节点 error，列出字段路径 |
| `SPEC_UNANCHORED` | 没有 `overallLengthM` 且模板无匹配 | `blueprint` error，提示输入长度 |
| `SPEC_LOW_CONFIDENCE` | 部件 confidence < 0.4 | warning，UI 标黄，不阻断 |
| `FIT_ASPECT_MISMATCH` | `aspectError > 5%` | warning；>15% 且 uniform 时 error |
| `FIT_ORIENTATION_AMBIGUOUS` | 朝向候选分差 < 0.01 | warning，提示检查 `forward` |
| `PORT_MISSING` | spec 有 connection 但端口不存在 | 节点 error，列出端口 id |
| `MATE_CONNECTOR_MISSING` | mate 输入 assembly 没有目标端口 | 节点 error，不回退吸附 |
| `MATE_AXIS_ERROR` | `axisErrorDeg > 1` | warning；>5 时 error |
| `MATE_OFFSET_MISMATCH` | `gapM` 或 `appliedOffsetM` 与目标偏差 >0.5mm | warning |
| `ASSEMBLY_CYCLE` | 连接图有环 | warning，环边跳过 |
| `DECIMATE_BBOX_DRIFT` | 减面后包围盒变化 >1% | warning |
| `PROVIDER_CONFIRM_REQUIRED` | 未带 `confirmRemote` | 拒绝提交，不产生费用 |
| `PROVIDER_KEY_MISSING` | 未配置 key | 节点 error，不泄露配置 |

原则：

- 有 spec/ports 时绝不静默回退到包围盒吸附。
- 部分件缺失时，`mate` 可以按现有 `preserve_absent` 思路跳过该连接并记录 warning，但根报告必须列出；默认不跳过，除非节点参数显式允许。
- 所有 error 写入节点结果 `error`，UI 显示可读消息和字段路径。

## 11. 兼容与迁移

### 11.1 兼容

- `schemaVersion` 保持 1；新节点/端口类型是附加式。
- 旧图 `partModel → decimate → assemble` 不变；`assemble`、KDTree 吸附、`layout_assemble.json` 保留。
- `partModel` 只有接了 `spec` 才启用 fit 和 assembly 输出；旧图没有 spec 边，行为完全一致。
- `decimate` 新增 assembly 端口，但旧 `mesh` 边仍按原路径执行。
- `NODE_TYPES` 的新增类型同步到 `js/pipeline.js`；旧图加载时不会出现未知类型。
- 现有测试中的 `NODE_TYPES` 断言需要扩展，不删除旧断言。

### 11.2 迁移

- 不自动改现有挖掘机图。
- 用户确认后，用“根据连接图生成装配链”动作生成新链；旧 `assemble` 节点保留为对照，验证通过后再手动删除。
- 或者新建“分层装配”模板，复制现有生成节点，替换组装段。
- 迁移前先为当前图做一次备份（复制 `graph.json`），动作执行前提示。

## 12. 安全与付费门禁

- `tools/bridge_config.json` 含 Ark API key，已被 gitignore；仅在现有 Provider 加载逻辑中使用，不打印、不输出、不提交。
- `blueprint`、`threeView`、`partImage`、`partModel` 的远程调用都必须带 `confirmRemote: true`，并校验 loopback origin。
- 任何 Provider 请求失败时，错误信息只保留 HTTP 状态和脱敏后的消息；不打印请求头、key、完整响应。
- 测试只用 mock `_ark_request`；不发起真实付费调用。
- 本次设计文档只写文件，不提交 git；是否提交由用户决定。

## 13. 测试策略

### 13.1 单元测试

- `tests/test_fw_spec.py`
  - spec 合法/非法校验：缺失字段、负尺寸、非法角色、非法 connection。
  - 归一化锚点 → 米制坐标；旋转后的 axis/normal。
  - 24 朝向候选评分：已知盒子 + 目标尺寸，选出正确朝向；镜像候选不得入选。
  - `build_mate_tree`：挖掘机连接图 → 后序链；环 → warning；重复端口 → warning。
- `tests/test_fw_assembly.py`
  - assembly 结果结构、端口合并、子装配局部 frame。
  - 缺端口 error；错误 connection error。
- `tests/test_fw_providers.py`
  - `analyze_spec` 解析 fenced JSON、非法 JSON、缺 key。
- `tests/test_bridge_providers.py`
  - blueprint 必须 `confirmRemote`；mock 返回 spec；key 不出现在结果。
  - threeView submit/poll 用 mock，不触网。

### 13.2 Blender 集成测试

- `tests/test_fw_blender.py`
  - fit：2×1×0.5 的盒子，目标 4×2×1，`scale=2`、`aspectError≈0`；轴向翻转正确。
  - fit 端口：anchor `[0.5,0.5,0.5]` → 校准后 bbox 中心。
  - mate：两个盒子，端口相对位置偏移和 90° 旋转，mate 后 gap≈0、axisError≈0，b 的变换正确。
  - mate 缺端口：返回 error，不产生输出。
  - decimate assembly：减面后端口保留、对象名保留。
- 用临时目录和测试 GLB，不触碰资产目录。

### 13.3 管线测试

- `tests/test_fw_pipeline.py`
  - `NODE_TYPES` 包含新类型和端口。
  - `execute_local` 的 blueprint/partModel fit/mate 分支用 mock，验证幂等和错误。
  - 没有 spec 的旧图执行结果不变。
- `tests/test_fw_parts.py`
  - 旧 `assemble` 和 snap 测试继续通过。
  - 新 assembly 结果不经过旧 assemble。

### 13.4 手工验收

- 加载挖掘机图，加 `blueprint`，填 `overallLengthM=7.2`，确认后生成 spec。
- 检查 spec 编辑、confidence 标色、`spec.json` 落盘。
- 逐件 `partModel` 校准，检查 fit 报告和端口。
- 确认后再跑 `threeView`，检查 AI 三视图和标注图。
- 生成装配链，逐级 mate，检查每级报告和根尺寸图。
- 全程不点击未确认的付费按钮；不暴露配置。

已知环境问题：Windows 上 `chmod`、`pywinpty`、路径分隔符相关的 3 个既有测试失败与本设计无关；新测试不得增加失败。

## 14. 分期实施

### P1：尺寸规格 + 校准 + 端口（地基）

交付：

1. `tools/fw_spec.py`：schema 常量、`validate_spec`、`resolve_ports`、`build_mate_tree`、机型模板、fit 计划。
2. `tools/fw_providers.py`：`analyze_spec`（视觉 JSON）。
3. `tools/bridge.py`：`blueprint` 提交/结果落盘、确认门禁。
4. `tools/fw_pipeline.py`：`NODE_TYPES` 扩展、`blueprint` 分支、`partModel` fit 钩子、校验。
5. `tools/fw_blender.py`：`fit` 模式。
6. `tools/fw_parts.py`：旧组装逻辑不变，P1 只做兼容性回归。
7. `js/pipeline.js`：节点定义、spec 编辑/查看、端口展示、参数表单。
8. 测试：`test_fw_spec.py`、`test_fw_providers.py` 扩展、`test_fw_blender.py` fit、`test_fw_pipeline.py`。

退出标准：挖掘机 5 个部件接入 spec 后校准到目标尺寸，fit 报告可读，端口随部件输出；旧图测试全绿。

### P2：三视图与标注

交付：

1. `tools/fw_views.py`：Pillow 裁切/标注、字体回退、尺寸表、端口投影。
2. `threeView` 节点 + bridge 映射 + 前端。
3. `fw_blender.py` 正交渲染精确尺寸图。
4. 测试：mock provider、标注输出结构、裁切失败降级。
5. 手工：用户确认后跑一次真实三视图，检查参考质量。

退出标准：AI 三视图和标注图可生成；Blender 精确图与实测包围盒一致；未确认时零付费调用。

### P3：分层装配

交付：

1. `tools/fw_assembly.py`：assembly 结果、端口合并、mate 计划、树后序。
2. `fw_blender.py`：`mate` 模式、assembly 减面保留端口。
3. `fw_pipeline.py`：`mate` 分支、`decimate` assembly 输入、根报告。
4. 前端：`mate` 节点、assembly 端口、自动装配链、报告面板。
5. 迁移动作/模板；挖掘机图迁移由用户触发。
6. 测试：`test_fw_assembly.py`、mate/decimate 集成、管线分支。

退出标准：挖掘机按 bucket+boom → body → cab → track 链装配；每级 gap/axis 报告可读；根尺寸在 spec 容差内；缺端口报错；旧路径不回退。

## 15. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 视觉 spec 比例不准 | 部件尺寸偏差 | spec 可编辑、confidence 标色、模板补齐、用户在 UI 修正 |
| 绝对尺寸缺失 | 无法校准 | `overallLengthM` 必填或模板匹配，否则 `SPEC_UNANCHORED` |
| 3D 模型朝向不确定 | 校准选错轴 | 24 个正交旋转候选 + forward + 端口分布评分，排除镜像；分差小告警，支持手动覆盖 |
| 端口来自 spec 而非图像 | 端口位置可能与模型表面不符 | 端口只作为装配锚点，允许 ±半径误差；报告暴露；后续可用视觉微调 |
| AI 三视图不一致 | 参考图误导 | 明确概念图属性；精确尺寸图从网格渲染 |
| 子装配变换累积误差 | 根装配偏移 | 每级报告 gap/axis；根 bbox 校验；必要时从根重新计算 |
| 减面改变包围盒 | 尺寸漂移 | 减面后告警；fit 在减面前完成；必要时二次 fit |
| 连接图有环 | 装配链不唯一 | 生成森林 + 环边 warning，人工确认 |
| 新节点 UI 复杂度 | 使用门槛 | 自动装配链动作、默认参数、报告面板；旧图零改动 |
| 付费调用误触 | 费用 | `confirmRemote` 门禁、测试全 mock、UI 明确标注付费节点 |

## 16. 验收标准

1. `spec.json` 通过 schema 校验，可人工修改；缺少绝对锚时明确报错。
2. 单件模型校准后目标尺寸误差：均匀模式下最大轴向偏差 ≤5% 不告警；>5% 告警，>15% 且 uniform 时报错；`aspectError` 在报告中可见。
3. 每个部件输出端口列表，`pos/axis/normal` 与校准后的部件一致。
4. 两个测试盒子的 mate：`gapM` ≤0.5mm、`axisErrorDeg` ≤0.5°（构造数据下接近 0）。
5. 挖掘机装配链按直接连接关系逐级生成；根装配无可见断缝，根包围盒与 spec 偏差 ≤3%。
6. 缺端口、缺 spec、连接图环、校准朝向歧义都有明确状态，不静默兜底。
7. AI 三视图只在用户确认后调用；标注数字来自 spec；精确尺寸图来自 Blender 网格。
8. 旧图、旧 `assemble`、snap 测试继续通过；所有新增测试不触网。
9. 配置 key 不出现在日志、结果、错误和 git 中。
10. 本次只写设计文档，不提交 git；实现按 P1→P2→P3 分期，每期结束跑全量测试。

## 17. 已决事项

- 尺寸事实来源：结构化 spec（用户选择）。
- 实施范围：P1/P2/P3 全做（用户选择）。
- 绝对尺寸锚：`overallLengthM` 或机型模板，不靠视觉猜。
- 连接点：spec + 角色模板确定性生成，不靠图像识别。
- 装配粒度：二元 `mate`，子装配逐级传递。
- 默认缩放：均匀；`perAxis` 需显式选择。
- 三视图：AI 概念图 + Blender 正交精确图，两者分开命名。
- 减面：单件减面并保留 assembly 端口，再进入 mate。
- 兼容：旧 `assemble` 和 snap 保留；新路径缺端口不吸附。
- 安全：所有付费调用需 `confirmRemote`；本次不提交、不跑真实付费调用。
