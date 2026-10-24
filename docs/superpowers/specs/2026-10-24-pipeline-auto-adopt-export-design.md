# 管线产物自动回填资产并导出

- 日期：2026-10-24
- 状态：已确认，待实施
- 相关文档：`docs/pipeline-design.md`、`docs/HANDOFF.md`
- 适用范围：机器、物品、元素的 AI 图标；机器、物品的 AI 3D 模型

## 1. 背景

当前管线（`js/pipeline.js` + `tools/fw_pipeline.py` + `tools/bridge.py`）只把 Provider 产物存进资产目录下的 `pipeline/outputs/`。生成结果与资产数据、同步导出是三条互不相连的链路：

- `S.machines/items/elements` 没有机器图标、没有 AI 模型字段；
- `js/views/machines.js` 的图标列始终用程序化等轴测 SVG；
- `syncExportMachine` 始终用 `createViewer3D` 重建程序化几何再导出；
- `fw_pipeline.execute_local` 的 `export` 节点被无条件标为 blocked；
- 用户必须手动去同步页重新生成、导出，生成结果本身不会落到资产上。

结果是“生成了就生成了”。本设计把轮询成功后的产物回填到资产，复用现有 `export/asset` 与 `project/publish` 链路完成项目落盘和 UE 发布。

## 2. 目标与非目标

### 2.1 目标

1. Provider 任务成功后，前端自动把图片/模型应用到对应资产，并写入项目内容。
2. 自动把资产导出到 `_Source/<中文分类>/<中文名>/`；配置了 UE 目标时自动发布到 UE 导出目录。
3. 机器的 AI GLB 替换程序化几何用于预览和导出；物品的 AI GLB 作为附加网格导出；元素只回填图标。
4. AI 机器支持整体变换（位置/旋转/缩放）与“适配占地”，不支持逐部件编辑。
5. 手动“导出全部”不会把已应用的 AI 资产覆盖回程序化几何。
6. 管线节点卡片能显示“已应用到哪个资产”，导出节点状态与 manifest 一致。

### 2.2 非目标

- 不新增远程生成接口，不修改 Provider 协议。
- 不自动重新生成；只应用 Provider 已经产出的结果。
- 不支持非 GLB 模型格式。
- 不支持 AI 模型的逐部件变换/材质/贴图编辑。
- 不做失败自动重试；失败后由用户再次触发。
- 不改变手工 `mesh`/`mat`/`modelStatus` 的语义。

## 3. 核心决策

| 决策 | 选择 |
|---|---|
| 执行位置 | 浏览器端，在 Provider 轮询成功后执行 |
| 导出方式 | 复用 `/api/export/asset`，不新增资产导出接口 |
| 发布方式 | 复用 `project/publish`（`syncPublishUE`） |
| 机器模型 | AI GLB 替换程序化几何 |
| 物品模型 | AI GLB 作为额外 `mesh` 角色导出到 UE |
| 元素 | 只回填图标 |
| AI 编辑粒度 | 整体变换，不支持单部件 |
| 幂等依据 | 资产上的 `generated` 来源记录，而不是图节点状态 |

## 4. 数据模型

### 4.1 新增字段

三类资产统一增加：

```js
asset.icon       = ''            // 128px data URL，只用于 UI
asset.iconSource = ''            // '' | 'generated' | 'upload'
asset.generated  = {             // 已应用的管线产物来源，幂等依据
  image: { taskId, file, at } | undefined,
  model: { taskId, file, at } | undefined,
}
```

机器和物品额外增加：

```js
asset.model = {
  source: 'ai',
  provider: 'tripo' | 'ark',
  file: 'model_<taskId>.glb',    // pipeline/outputs 下的 basename
  taskId: '<Provider taskId>',
  nodeId: '<管线节点 id>',
  generatedAt: '2026-10-24T12:00:00.000Z',
  transform: {
    position: { x: 0, y: 0, z: 0 },
    rotation: { x: 0, y: 0, z: 0 },   // 弧度，Euler XYZ
    scale:    { x: 1, y: 1, z: 1 },
  },
  autoFit: true,
  triangles: 12345,
}
```

字段说明：

- `icon` 只存 128px 缩略图，避免撑爆 localStorage / `content.json`。
- 导出用 256px PNG 在应用时直接写入 `_Source`，不回流到资产数据。
- `model.file` 必须是 basename。`/api/pipeline/output/` 路由只接受 `(model|image)_<id>.<ext>`，并按 `outputs/` 目录解析（`tools/bridge.py:1493`）。
- 原始 GLB 留在管线存档；资产只保存引用与变换。每次导出时重新读取并烘焙。
- `generated.image` / `generated.model` 记录最后一次成功应用的 Provider 任务，用于：
  - 重复轮询时跳过相同任务；
  - 节点卡片判断“是否已应用”；
  - 恢复程序化几何时判断图标是否来自模型。

### 4.2 归一化

`normalizeAssets`（`js/core/state.js`）为三类资产补齐：

```js
if(typeof a.icon !== 'string') a.icon = '';
if(typeof a.iconSource !== 'string') a.iconSource = '';
if(!a.generated || typeof a.generated !== 'object') a.generated = {};
if(kind !== 'element' && a.model && a.model.source !== 'ai') a.model = null;
```

要求：

- 机器、物品、元素都执行，不只物品。
- 不覆盖已有 `icon` / `model` / `ui3d` / `mesh` / `mat`。
- `model.transform` 缺字段时补默认值，但 `autoFit` 存在时保留。

### 4.3 编辑器保存必须合并旧对象

`commitEditor`（`js/ui/editor.js:323`）当前用新对象整体替换旧对象，会丢失：

- 机器的 `ui3d.parts`；
- 新增的 `model` / `generated` / `iconSource`；
- 其他未在表单中出现的字段。

改为：

```js
const existing = S[coll].find(x => x.id === id) || {};
obj = Object.assign({}, existing, obj);
```

再执行 ID 冲突检查与写回。这样新字段无需出现在每个表单里也能保留。

同时，图标提交需要维护 `iconSource`：

- 本次上传了图标 → `iconSource = 'upload'`；
- 点了“恢复自动生成” → `iconSource = ''`，清除 `icon`，保留 `generated` 记录用于追溯；
- 未改动 → 沿用原值。

### 4.4 生成产物的路径与访问

- 图片：`task.output.imagePath` = `outputs/image_<taskId>.<ext>`。
- 模型：`task.output.modelPath` = `outputs/model_<taskId>.glb`。
- URL 构造函数改为接受显式资产：

```js
function pipelineOutputURLFor(assetId, kind, file){
  return '/api/pipeline/output/' + encodeURIComponent(assetId) + '/' +
    encodeURIComponent(String(file).split('/').pop()) +
    '?kind=' + encodeURIComponent(kind);
}
function pipelineOutputURL(file){
  return pipelineOutputURLFor(PIPELINE.assetId, PIPELINE.kind, file);
}
```

自动回填发生在任意页面，不能依赖 `PIPELINE.assetId`。

## 5. 自动应用流程

新增 `js/pipeline-adopt.js`，在 `index.html` 中于 `js/pipeline.js` 之前引入。入口：

```js
async function pipelineAdoptTask(assetId, kind, nodeId, task)
```

调用点：

1. `pipelinePollLoop`（`js/pipeline.js:811`）在 `task.state === 'success'` 后；
2. `pipelineSubmitRemote`（`js/pipeline.js:848`）在提交响应直接为 `success` 后。

调用点不等待应用完成，避免阻塞轮询；应用内部串行排队。

### 5.1 串行队列

```js
PIPELINE.applyQueue[assetId] = (PIPELINE.applyQueue[assetId] || Promise.resolve())
  .then(() => pipelineAdoptTaskInner(assetId, kind, nodeId, task))
  .catch(error => { /* 记录错误，不阻断后续 */ });
```

同一资产可能有 `textToImage` 与 `imageTo3D` 两个任务接近同时完成；串行保证“概念图先落地，模型图后覆盖”的顺序。

### 5.2 `textToImage` 成功

1. 通过 `pipelineOutputURLFor(assetId, kind, task.output.imagePath)` 取图。
2. 中心裁切为正方形：
   - `side = min(width, height)`；
   - 源矩形居中；
   - 目标 128px 写入 `asset.icon`；
   - 目标 256px 作为导出 PNG 的 base64。
3. `asset.iconSource = 'generated'`。
4. `asset.generated.image = { taskId, file: basename(imagePath), at }`。
5. `POST /api/export/asset`：
   - `kind` 为资产类型；
   - `files.icon = { path: '<ID>_icon.png', b64 }`；
   - `meta` 带 `iconHash`（物品/元素）或 `contentHash`/`styleHash`（机器）。
6. 保存项目内容。

机器在尚未应用模型时先用这张概念图作为图标；模型应用后会被模型渲染图覆盖。物品/元素的概念图就是最终图标。

### 5.3 `imageTo3D` 成功

只处理 `machine` 与 `item`。`element` 忽略。

1. 读取 `task.output.modelPath`，通过输出 URL 取 `ArrayBuffer`。
2. `GLTFLoader.parse` 得到场景；遍历网格设置 `castShadow = receiveShadow = true`。
3. 计算 `Box3`，生成默认变换（见 §6.2）。
4. 用同一场景渲染 256px 透明底 PNG（见 §6.5 的 `renderGLBThumbnail`）。
5. 烘焙 GLB（见 §6.4 与 §6.5 的 `bakeGLBScene`）。
6. 更新资产：

```js
asset.model = { ... };
asset.generated.model = { taskId, file: basename(modelPath), at };
if(kind === 'machine'){          // 机器图标始终以模型渲染图为准
  asset.icon = thumb128;
  asset.iconSource = 'generated';
}else if(!asset.icon){           // 物品没有概念图时才用模型图兜底
  asset.icon = thumb128;
  asset.iconSource = 'generated';
}
```

7. `POST /api/export/asset`：
   - `files.mesh = { path: '<ID>.glb', b64: bakedGLB }`；
   - `files.icon = { path: '<ID>_icon.png', b64 }`（机器或物品无概念图时）；
   - 机器额外 `files.preview = { path: '<ID>_preview.png', b64: render512 }`；
   - `meta`：
     - 机器：`contentHash`、`styleHash`、`triangles`、`sizeCm`、`model`（provider/taskId/file/transform）；
     - 物品：`iconHash`、`modelHash`、`model`。
8. 保存项目内容。
9. 若 `SYNC.status.ueTarget` 存在：`await syncPublishUE([assetId])`。
10. 刷新 UI 与管线卡片。

### 5.4 幂等

应用前检查：

```js
if(node.type === 'textToImage' && asset.generated?.image?.taskId === task.taskId) return;
if(node.type === 'imageTo3D' && asset.generated?.model?.taskId === task.taskId) return;
```

用户重新提交任务会得到新 `taskId`，因此会再次应用。重复轮询同一任务不会重复写盘。

### 5.5 保存顺序

1. 先改内存中的资产并 `saveState()`。
2. 再 `POST /api/export/asset`。
3. 最后 `syncPublishUE`。

即使导出失败，资产仍保留模型引用，UI 可以预览；同步页会显示 `stale/none`，用户可重试。失败不会回滚本地资产。

## 6. 3D 载入、预览与整体变换

### 6.1 `createViewer3D` 的 AI 分支

`createViewer3D(canvas, machine)` 保持同步返回，新增：

- `whenModelReady()` → `Promise<{ok, error, size}>`；
- `setAIModelTransform(transform)`；
- `getAIModelInfo()`；
- `fitCameraToObject()`；
- `toThumbnail(size)`。

行为：

1. 若 `machine.model?.source === 'ai'` 且 `haveThree()` / `THREE.GLTFLoader` 可用：
   - 先按原逻辑构建程序化几何并显示；
   - 异步加载 `pipelineOutputURLFor(machine.id, 'machine', machine.model.file)`；
   - 成功后把 `gltf.scene` 加入 `holder`，应用 `model.transform`，隐藏程序化网格组；
   - 调整相机取景、地面尺寸与阴影范围；
   - 失败时保留程序化几何，`whenModelReady` resolve `{ok:false, error}`。
2. 若没有 AI 模型：`whenModelReady` 立即 resolve `{ok:true, procedural:true}`，行为与现在完全一致。
3. `dispose` 需要释放 AI 场景的 geometry/material/texture，并清空 holder 引用。

注意：

- 程序化 `meshes` 数组保留，作为回退与 `getParts()` 的数据源；AI 模式下 `getParts()` 返回空数组。
- 预览不应自动改写资产里的 `transform`。若 `transform` 缺失，viewer 在内存中计算一个适配值用于显示；持久化只发生在应用流程或用户点击“适配占地/保存”时。

### 6.2 默认变换

坐标系：glTF/three.js Y-up，单位米，底面中心为原点。

机器：

```js
const [bw, bd] = parseFootprint(machine.footprint);   // "3×3" → [3,3]，失败回退 [2,2]
const size = bbox.getSize(new THREE.Vector3());
const scale = Math.min(bw / size.x, bd / size.z) || 1;
const center = bbox.getCenter(new THREE.Vector3());
transform.scale = { x: scale, y: scale, z: scale };
transform.rotation = { x: 0, y: 0, z: 0 };
transform.position = {
  x: -center.x * scale,
  y: -bbox.min.y * scale,
  z: -center.z * scale,
};
```

物品：

```js
const maxDim = Math.max(size.x, size.y, size.z) || 1;
const scale = 1 / maxDim;             // 最大边归一到 1m
// position 公式与机器相同
```

结果：

- 水平方向不超出占地格（机器）；
- 物品最大边为 1m；
- 底部贴地，水平居中。

用户修改任意位置/旋转/缩放字段后，`autoFit = false`；“适配占地”重新计算并设回 `true`。

### 6.3 透明底缩略图

`toThumbnail(size)`：

1. 保存当前 `scene.background`、地面/边线/碰撞盒/粒子的可见性、renderer 尺寸、camera aspect。
2. `scene.background = null`；隐藏辅助对象；`renderer.setClearColor(0x000000, 0)`。
3. 相机按 AI 模型 `Box3` 取景：3/4 视角、fov 36、目标为包围盒中心。
4. `renderer.setSize(size, size, false)`；`camera.aspect = 1`；render。
5. `canvas.toDataURL('image/png')`。
6. 恢复所有临时状态。

`WebGLRenderer` 创建参数改为 `alpha: true`。正常预览始终设置 `scene.background`，视觉效果不变。

256px PNG 用于导出；128px 由 256px 再缩放得到。

### 6.4 烘焙 GLB

`bakeAIModelGLB(scene, transform, machine)`：

1. 将 `gltf.scene` 放入 `THREE.Group` holder。
2. 应用 `transform`（position/rotation/scale）。
3. 设置 `holder.name = machine.id`。
4. 写入 `userData.forgeworks`：id/name/category/footprint/tier/source/taskId/transform/unit/pivot。
5. `new THREE.GLTFExporter().parse(holder, onDone, onError, { binary: true, onlyVisible: true })`。
6. 遍历网格统计三角面数与尺寸，返回 `{buffer, meta}`。

导出时保留节点变换，UE 导入会应用；不强制把几何烘平，避免破坏多节点结构。

### 6.5 独立 GLB 辅助

物品没有 3D 查看器，自动应用也发生在查看器之外，因此把 GLB 处理拆成不依赖 `createViewer3D` 的独立函数（放在 `js/engines/glb.js`，或 `viewer3d.js` 顶部）：

```js
loadGLBScene(urlOrBuffer)                    // → Promise<{scene, bbox, size}>
computeFitTransform(bbox, kind, footprint)   // → transform（纯函数，可单测）
renderGLBThumbnail(scene, transform, size)   // → Promise<dataURL>，内部创建临时 renderer
bakeGLBScene(scene, transform, machine)      // → Promise<{buffer, meta}>
```

- `createViewer3D` 的 AI 分支内部复用 `loadGLBScene` 与 `computeFitTransform`。
- 自动应用流程（§5.3）复用 `computeFitTransform`、`renderGLBThumbnail`、`bakeGLBScene`。
- `syncExportItem` 复用 `bakeGLBScene`；不需要为物品创建查看器。
- `renderGLBThumbnail` 内部创建 `alpha: true` 的临时 `WebGLRenderer`，渲染后立即 `dispose()`，避免占用主查看器。
- `computeFitTransform` 是纯函数，输入包围盒尺寸/最小点/中心点、资产类型与占地，输出 §6.2 的变换，可在 smoke 测试中直接验证。

### 6.6 预览弹窗与编辑器

`open3DViewer`：

- 显示“加载 AI 模型…”状态；
- `whenModelReady()` 后显示 `AI 模型 · <provider> · <triangles> 三角面`；
- AI 模式下隐藏部件列表，提示整体变换入口；
- “导出 GLB”按钮继续调用 `toGLB`，AI 模式导出 AI 模型。

`open3DEditor`（`js/views/editor3d.js`）：

- 等待 `whenModelReady()`。
- 程序化模型：现有逐部件编辑完全不变。
- AI 模型：
  - 不显示部件列表；
  - 显示整体变换字段：位置 XYZ、旋转 XYZ（度）、缩放 XYZ；
  - 提供“适配占地”（重新计算默认变换）、“重置变换”（回到应用时的初始变换）、“恢复程序化几何”；
  - 修改即写入 `machine.model.transform` 并 `saveState()`；
  - 撤销/重做只记录整体变换快照。
- “恢复程序化几何”：
  - confirm 后删除 `machine.model`、`machine.generated.model`；
  - 若当前图标来自模型（`iconSource === 'generated'` 且 `generated.model.at >= generated.image?.at`），删除 `machine.icon` 与 `iconSource`，图标回退到 `isoPreview`；
  - `saveState()`，关闭编辑器，toast“已恢复程序化几何，需重新导出”。

## 7. 导出与 UE 发布

### 7.1 `export/asset` 按角色合并

`tools/bridge.py:1273` 的 `export_asset` 当前用本次 `written` 和 `meta_data` 整体替换 manifest 记录。部分导出（只有 icon、或只有 mesh）会抹掉其它角色。改为：

```python
with _manifest_lock:
    mf = load_manifest() or {'schemaVersion': 1, 'assets': {}}
    rec = mf['assets'].setdefault(asset_id, {})
    previous_files = rec.get('files') if isinstance(rec.get('files'), dict) else {}
    merged_files = dict(previous_files)
    merged_files.update(written)

    previous_meta = rec.get('meta') if isinstance(rec.get('meta'), dict) else {}
    merged_meta = dict(previous_meta)
    merged_meta.update(meta_data)

    rec.update({
        'kind': kind,
        'state': 'exported',
        'sourceDir': rel_dir,
        'files': merged_files,
        'exportedAt': now_iso(),
        'exportedBy': 'bridge-%s' % BRIDGE_VERSION,
        'meta': merged_meta,
    })
    save_manifest(mf)
```

规则：

- 本次提供的角色整体替换该角色条目；
- 本次未提供的角色保留上次记录；
- `meta` 浅合并，本次提供的键覆盖旧值；
- 本次未写 mesh 时不排 Blender 检查队列（沿用 `written.get('mesh')`）。

### 7.2 物品 UE 角色

`tools/fw_project.py:21`：

```python
UE_EXPORT_ROLES = {
    'machine': ('mesh', 'icon'),
    'item':    ('icon', 'mesh'),
    'element': ('icon',),
}
```

`_publish_asset` 的 `required = roles[0]` 保持不变：

- machine 必须有 mesh；
- item 必须有 icon，mesh 可选；
- element 必须有 icon。

### 7.3 手动导出

`syncExportMachine(id)`：

- 程序化：现有路径不变。
- AI：
  1. `createViewer3D` 加载 AI 模型，`await whenModelReady()`；
  2. `toGLB` 导出 AI 模型；
  3. `toThumbnail(256)` 生成图标；
  4. `toThumbnail(512)` 生成 preview；
  5. POST `mesh` + `icon` + `preview`；
  6. meta 带 `contentHash`/`styleHash`/`model`。

`syncExportItem(id)`：

- 程序化/普通物品：现有路径不变。
- AI：
  - 若有 `it.model`，额外烘焙并 POST `files.mesh = { path: '<ID>.glb', b64 }`；
  - meta 增加 `modelHash`、`model`；
  - 图标处理见 §7.4。

`syncExportElement(id)`：沿用现有流程；仅按 §7.4 的规则，在“生成图标且 manifest 已有 icon”时跳过重新编码图标。生成图标的 256px 文件已在应用时写入。

AI 机器的自定义图标：若 `m.iconSource === 'upload'` 且 `m.icon` 非空，`syncExportMachine` 的图标改为从 `m.icon` 生成 256px（复用 `imagePngB64`），不要用模型渲染图覆盖用户上传的图标；mesh 仍然用 AI 模型。

### 7.4 生成图标的质量保持

`asset.icon` 只有 128px，手动重导时若从它放大到 256px 会糊。规则：

- 若 `asset.iconSource === 'generated'` 且 manifest 已有该资产的 `icon` 角色：
  - 物品/元素重导时不重新编码、不重发 `icon`，只发 `mesh`（如有变化）和更新后的 `meta`；
  - 在 manifest 里保留原 256px 文件。
- 若 `iconSource === 'upload'` 或 manifest 没有 icon：
  - 按现有逻辑从 `asset.icon` 生成 256px 并提交。
- 机器不受影响：AI 机器每次都从模型重新渲染 256px。

`export_asset` 的合并语义保证“只发 meta / 只发 mesh”不会丢 icon。

### 7.5 管线 export 节点

`tools/fw_pipeline.py:231` 的 `execute_local`：

- `textToImage` / `imageTo3D`：保持现状。
- `imageExport`：保持现状。
- `export`：不再无条件 blocked。读取 `forgeworks_root/_Sync/manifest.json` 中该资产的记录：
  - machine：`files.mesh` 与 `files.icon` 均非空；
  - item：`files.icon` 非空；
  - element：`files.icon` 非空。
  - 满足：`state = 'done'`，`output = {sourceDir, files, exportedAt}`；
  - 不满足：`state = 'blocked'`，`error = '尚未导出到项目；请先完成生成与同步导出'`。
- 其余未实现阶段保持 blocked。

应用成功后，前端对 `export` 节点单独调用一次 `pipeline/run`（`nodeId='export'`, `through=false`）刷新状态；若当前不在该资产的管线页，跳过，卡片状态在下次进入时自然刷新。

## 8. UI 改动

### 8.1 机器列表（`js/views/machines.js`）

- 图标列改为 `machineIconHTML(r, 40)`：

```js
function machineIconHTML(m, size){
  if(m && m.icon) return `<img src="${m.icon}" width="${size}" height="${size}"
    style="border-radius:6px;object-fit:contain;background:var(--panel-2)" alt="">`;
  return isoPreview(m, 0, size);
}
```

- 名称或 ID 旁显示 `AI` 小标签（`r.model?.source === 'ai'`）。
- 「部件」按钮文案：AI 模式显示「变换」，程序化显示「部件」。
- 同步列与 UE 列逻辑不变。

### 8.2 机器编辑器（`js/ui/editor.js`）

在现有字段后追加：

1. 图标资源区：复用 `iconResourceHTML` / `bindIconResource`：
   - `previewHTML: d ? machineIconHTML(d, 52) : ''`；
   - `hasCustom: !!(d && d.icon && d.icon.trim())`；
   - `showGenerate: !isNew`；
   - `generateLabel: 'AI 生成 →'`（扩展 `iconResourceHTML`，默认仍为「生成图标 →」）。
2. 模型状态区：
   - 程序化：显示“程序化几何”；
   - AI：显示 provider、任务 ID、生成时间、三角面数；
   - 按钮「生成模型 →」：确认未保存修改后进入管线；
   - 不在此处放变换输入，变换走 3D 编辑器。

提交时按 §4.3 合并旧对象，并写入 `icon` / `iconSource`。

### 8.3 物品编辑器

- 现有图标区不变；“生成图标 →”进入元素/图标模板。
- 模型区增加 AI 状态：
  - 有 `model`：显示 provider/时间/三角面 + 「移除 AI 模型」；
  - 无：显示“程序化/未生成” + 「生成模型 →」。
- “移除 AI 模型”：删除 `model` 与 `generated.model`，保留物品图标。
- 手工 `mesh`/`mat`/`modelStatus` 字段保留，并注明“AI 模型优先用于自动导出”。

### 8.4 元素编辑器

- 图标区显示来源：`generated` → “AI 生成”，`upload` → “自定义”。
- 不改其它字段。

### 8.5 资源页（`js/views/assets.js`）

- 物品/元素图标已经走 `iconURL`，生成图标写入 `asset.icon` 后自动生效，无需改渲染。
- 有 AI 模型的物品加 `AI` 标签。

### 8.6 管线节点卡（`js/pipeline.js`）

- `imageTo3D` / `textToImage` 卡片：
  - 任务成功且 `asset.generated.model/image.taskId === 当前 taskId` → 显示“已应用到 <资产名>”；
  - 提供「打开资产」按钮（机器 → 机器页；物品/元素 → 资源页）；
  - 应用失败显示 `applyError`。
- `export` 节点：显示 server 返回的 `output.sourceDir`/`exportedAt` 或阻塞原因。
- 模板下拉默认值：元素 `icon`，物品 `item`，机器 `machine`。

### 8.7 3D 预览 / 编辑器

见 §6.6。

## 9. 状态与 hash

### 9.1 机器

`machineContentHash`（`js/sync.js:509`）追加：

```js
icon: m.icon ? syncDataHash(m.icon) : '',
model: m.model ? syncDataHash({
  file: m.model.file, taskId: m.model.taskId, transform: m.model.transform,
}) : '',
```

影响：

- 换图标 → `stale`；
- 换模型或改变换 → `stale`；
- 重新导出后 meta 写入新 hash → `exported`。

`machineStyleHash` 不变。

### 9.2 物品

`itemIconHash` 已包含 `it.icon`，无需改。

新增：

```js
function itemModelHash(it){
  return syncDataHash(it.model ? {
    file: it.model.file, taskId: it.model.taskId, transform: it.model.transform,
  } : null);
}
```

`itemSyncState` 增加：

```js
const stale = (saved.iconHash && saved.iconHash !== itemIconHash(it))
           || (saved.modelHash && saved.modelHash !== itemModelHash(it));
```

`syncExportItem` 的 meta 写入 `modelHash`。

### 9.3 元素

`elementIconHash` 已包含 `el.icon`，无需改。

### 9.4 meta 完整性

每次 `export/asset` 都写入当前能计算的完整 hash：

- 机器：`contentHash` + `styleHash`；
- 物品：`iconHash` + `modelHash`；
- 元素：`iconHash`。

服务端 meta 合并保证部分导出不会丢掉其它键。

## 10. 错误处理、幂等与并发

| 场景 | 行为 |
|---|---|
| 资产不存在 | 跳过，toast“资产已删除”，记录错误到同步日志 |
| 图片下载失败 | 不写资产；保留 Provider 输出；toast |
| GLB 下载/解析失败 | 保留已成功的图标；不写 `model`；toast |
| 渲染缩略图失败 | 仍写入 `model` 和 mesh；图标回退到概念图或程序化；toast |
| `export/asset` 失败 | 保留本地资产；不发布 UE；toast + 同步页可重试 |
| `export/asset` 冲突/保护 | 不覆盖磁盘；保留本地资产；提示去同步页处理 |
| 无 UE 目标 | 只写项目；toast“已应用到项目（未设置 UE 目标）” |
| Bridge 离线/未绑定项目 | 不应用；输出留在管线存档 |
| 重复轮询 | `generated` taskId 去重 |
| 同一资产多个任务同时成功 | 按 `applyQueue` 串行 |
| 用户正在编辑 | 不强制关闭弹窗；后台完成应用，弹窗保留 |

所有自动写入都必须经过现有 Bridge 同源校验；不新增绕过路径。

## 11. 兼容与迁移

- 老资产没有新字段：`normalizeAssets` 补齐，不改变现有行为。
- 老 manifest 没有 `model` / `modelHash`：同步状态判断使用 `saved.xxx && ...` 的既有模式，缺键不等于 stale。
- 老 `files` 记录只有 `mesh` 没有 `icon`：机器同步状态原本就判 stale，行为不变。
- 旧 `_Source/pipeline/<id>/` 存档：`resolve_output` 已兼容 legacy 路径；`model.file` 使用 basename 即可访问。
- 旧程序化 GLB：重新导出会生成 AI 版本；未应用 AI 的资产继续走程序化。
- 不迁移、不删除任何已有文件。

## 12. 测试

### 12.1 Python 单元测试

`tests/test_fw_project.py`：

1. item 的 `UE_EXPORT_ROLES` 同时复制 icon 与 mesh；
2. item 只有 icon、没有 mesh 时仍可发布；
3. machine 缺 mesh 时发布失败；
4. 发布 manifest 中 item 记录包含两个角色。

`tests/test_fw_pipeline.py`：

1. manifest 有 machine 的 mesh+icon → export 节点 done；
2. 缺 icon → blocked；
3. item 有 icon → done（无 mesh 也可以）；
4. 无 manifest → blocked。

`tests/test_bridge_projects.py` 或新增测试：

1. `export_asset` 先写 icon、再写 mesh，最终 `files` 同时含两者；
2. 先写 mesh、再写 icon，最终 `meta` 同时保留两批键；
3. 同一角色重复导出时被新条目替换，不重复累加；
4. 部分导出不触发 Blender 队列（没有 mesh）。

### 12.2 前端 smoke（`tests/smoke.html`）

1. `normalizeAssets` 为 machines/items/elements 补齐 `icon`/`iconSource`/`generated`；
2. 物品/机器 `model.transform` 默认值补齐；
3. `machineIconHTML` 在 `m.icon` 存在时输出 `<img>`，否则输出 SVG；
4. `pipelineOutputURLFor` 对 `outputs/model_x.glb` 生成 basename URL；
5. 默认变换计算：给定 bbox 与 footprint，验证缩放、居中、贴地；
6. `commitEditor` 合并旧对象：模拟带 `ui3d` 的机器保存后 `ui3d` 仍在。

### 12.3 手工验收

1. 机器管线跑通 `textToImage` → `imageTo3D`：
   - 机器列表出现 AI 图标；
   - 3D 预览显示 AI 模型；
   - `_Source/机器/<中文名>/` 出现 `<ID>.glb`、`<ID>_icon.png`、`<ID>_preview.png`；
   - manifest 记录 `files.mesh`/`files.icon`/`meta.model`。
2. 配置 UE 目标后，`<UE>/Forgeworks/` 自动出现对应文件。
3. 物品管线跑通后，资源页图标更新，`_Source/物品/图标/<中文名>/` 同时有 icon 与 GLB。
4. 元素管线跑通后，只更新图标，不产生 mesh。
5. “导出全部”后，AI 机器的 GLB 仍是 AI 模型，不是程序化几何。
6. 3D 编辑器改变整体缩放/旋转 → 同步状态变 `stale` → 重新导出生效。
7. “恢复程序化几何”后，预览与导出回到程序化路径。
8. 重复轮询同一任务不产生重复文件/重复导出。
9. 无 UE 目标时自动应用与项目导出成功，toast 明确说明未发布 UE。
10. 浏览器关闭后重新打开，资产图标/模型引用仍在（项目 `content.json` 已保存）。

## 13. 改动清单

新增：

- `js/pipeline-adopt.js`
- `js/engines/glb.js`（GLB 场景加载、适配变换、缩略图、烘焙）
- 本设计文档

修改：

- `index.html`（在 `viewer3d.js` 前引入 `js/engines/glb.js`，并引入 `js/pipeline-adopt.js`）
- `js/pipeline.js`（轮询钩子、URL 辅助、节点卡、模板默认值、导出节点刷新）
- `js/engines/viewer3d.js`（AI 加载、`whenModelReady`、透明缩略图、烘焙、整体变换、相机适配）
- `js/views/editor3d.js`（AI 整体变换面板、恢复程序化几何）
- `js/ui/editor.js`（机器图标/模型区块、物品模型区块、`commitEditor` 合并、`generateLabel`）
- `js/core/state.js`（`normalizeAssets` 全量补齐）
- `js/sync.js`（AI 导出分支、hash、生成图标保真、发布）
- `js/views/machines.js`（图标列、AI 标签、按钮文案）
- `js/views/assets.js`（AI 标签）
- `tools/bridge.py`（`export_asset` files/meta 合并）
- `tools/fw_project.py`（item 角色含 mesh）
- `tools/fw_pipeline.py`（export 节点 manifest 检查）
- `tests/test_fw_project.py`
- `tests/test_fw_pipeline.py`
- `tests/test_bridge_projects.py` 或新增测试
- `tests/smoke.html`

## 14. 验收标准

- Provider 任务成功且浏览器保持打开时，无需用户点击“导出”，资产图标/模型与 `_Source` 在轮询返回 success 后 60 秒内更新。
- 配置 UE 目标时，同一流程自动完成 UE 发布；无目标时不报错、不阻塞。
- 所有自动写入都可从 manifest 追溯（资产 ID、任务 ID、文件、hash、时间）。
- 手动导出与批量导出不会回退 AI 资产。
- 任何失败都不会删除已有资产文件或已有 manifest 记录。
- 现有程序化资产、手工图标、手工 mesh 路径行为不变。

## 15. 风险与缓解

| 风险 | 缓解 |
|---|---|
| AI GLB 纹理在 GLTFExporter 中丢失 | 在导出后检查 `meta.materials` 与贴图数量；失败时保留原始 GLB 并提示，不阻塞图标 |
| Provider 模型尺度差异大 | 首次应用按占地/1m 自动适配；用户可整体缩放 |
| 浏览器关闭导致任务未应用 | 用户需保持页面打开；重进管线时对已有 `success` 任务提供「应用结果」按钮（复用 `pipelineAdoptTask`） |
| 自动发布覆盖 UE 侧手工修改 | 沿用现有 publish 行为；不新增自动覆盖规则；用户可在同步页看到状态 |
| `content.json` 变大 | 只在资产里存 128px 缩略图与短引用；原图/GLB 留在磁盘 |
| 并发轮询/应用竞态 | 每资产串行队列 + `generated.taskId` 去重 |
| 编辑器保存丢失 `ui3d` | `commitEditor` 合并旧对象 |

### 15.1 兜底：手动应用已有结果

管线节点卡在任务 `success` 但 `generated` 中尚未记录该任务时，显示「应用结果」按钮，调用同一个 `pipelineAdoptTask`。这覆盖浏览器中途关闭、自动应用失败等场景，不新增后端逻辑。
