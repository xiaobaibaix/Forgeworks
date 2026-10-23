# 导出到 Unreal Engine

把 Forgeworks 里设计的内容变成 UE 的 DataTable 资产。

---

## 一、定义 C++ 结构体

在项目模块的头文件里加入以下结构体（注意必须继承 `FTableRowBase`）：

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "StarEraContentTypes.generated.h"

USTRUCT(BlueprintType)
struct FStarEraItemAmount
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString ItemId;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) float Amount = 0.f;
};

USTRUCT(BlueprintType)
struct FStarEraItemDef : public FTableRowBase
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FName Type;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Value = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FLinearColor Color;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;

    // ---- 资源字段 ----
    UPROPERTY(EditAnywhere, BlueprintReadOnly) bool bHasCustomIcon = false;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) TSoftObjectPtr<UStaticMesh> MeshPath;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) TSoftObjectPtr<UMaterialInterface> MaterialPath;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FName ModelStatus;

    // 运行时从图集填充
    UPROPERTY(BlueprintReadOnly) FVector2D IconUV0 = FVector2D::ZeroVector;
    UPROPERTY(BlueprintReadOnly) FVector2D IconUV1 = FVector2D::OneVector;
};

USTRUCT(BlueprintType)
struct FStarEraMachineDef : public FTableRowBase
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FName Category;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 FootprintX = 1;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 FootprintY = 1;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 PowerDraw = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;
};

USTRUCT(BlueprintType)
struct FStarEraRecipeDef : public FTableRowBase
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FName MachineType;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FName Category;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) float CycleTime = 1.f;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) float PowerDraw = 0.f;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FStarEraItemAmount> Inputs;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FStarEraItemAmount> Outputs;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;
};

USTRUCT(BlueprintType)
struct FStarEraTechDef : public FTableRowBase
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Cost = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FString> Prerequisites;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FString> Unlocks;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;
};

USTRUCT(BlueprintType)
struct FStarEraElementDef : public FTableRowBase
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Symbol;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FLinearColor Color;
};
```

---

## 二、导出 JSON

给 5 个结构体分别建空 DataTable 资产（名字必须是 `DT_ItemDef` / `DT_MachineDef` /
`DT_RecipeDef` / `DT_TechDef` / `DT_ElementDef`），放在 `/Game/Data/` 下。

在 Forgeworks 的「导出」页点 **下载 JSON**，把文件放到：

```
<项目>/Content/Data/StellarEra_Content.json
```

---

## 三、运行导入脚本

在 UE 编辑器的 Python 控制台：

```python
exec(open(r"D:/Projects/StellarEra/Tools/import_datatables.py").read())
import_all()
```

或指定路径：

```python
import_all(
    json_path=r"D:/Projects/StellarEra/Content/Data/StellarEra_Content.json",
    dest_dir=r"D:/Projects/StellarEra/Content/Data",
)
```

脚本会**删除旧资产并重建**，避免残留行。

---

## 四、CSV 方式（备选）

不想跑 Python 也可以用「导出」页的 5 个 CSV，直接拖进 Content Browser 导入。
字段名已对齐结构体属性名，但有两个坑：

1. **字段名不能叫 `Name`** —— 与 UE 内部的 Row Name 列冲突，所以用的是 `DisplayName`
2. **Reimport 会完全覆盖** —— 编辑器里手改的值会消失，保持设计器为唯一数据源

CSV 数组语法（本项目已按规范生成）：

| 类型 | 格式 |
|---|---|
| `TArray<FString>` | `("a","b")` |
| `TArray<FStruct>` | `((ItemId="X",Amount=2.0))` |
| 空数组 | `()` |

文件带 UTF-8 BOM，Excel 打开中文不乱码；UE 读取 CJK 也需要 BOM。

---

## 五、图标图集接入

图标不写进 CSV，走图集：

1. 「资源」页点 **导出图标图集 (PNG)** → `StellarEra_IconSheet_128.png`（8 列网格）
2. 点 **导出图集坐标 (JSON)** → 每格 UV
3. UE 里把 PNG 导入为 `Texture2D`，Texture Group 设为 `UI`
4. 用 Material 或 UI Brush 按 UV 取子区域

图集坐标格式：

```json
{
  "cell": 128, "cols": 8, "rows": 10, "width": 1024, "height": 1280,
  "frames": {
    "ORE_FE": { "x": 0, "y": 0, "w": 128, "h": 128,
                "u0": 0, "v0": 0, "u1": 0.125, "v1": 0.1 }
  }
}
```

---

## 六、游戏侧读取

```cpp
UDataTable* ItemTable = LoadObject<UDataTable>(nullptr,
    TEXT("/Game/Data/DT_ItemDef.DT_ItemDef"));

const FStarEraItemDef* Def = ItemTable->FindRow<FStarEraItemDef>(
    TEXT("ORE_FE"), TEXT("ItemDef"));

if (Def)
{
    // Def->DisplayName / Def->Tier / Def->Color ...
}
```

`FindRow` 是哈希查找，但每次都要构造 `FName`，高频调用建议包一层缓存：

```cpp
UFUNCTION(BlueprintPure, Category="StarEra")
static FStarEraItemDef GetItemDef(FName ItemId);
```

---

## 数据流总览

```
Forgeworks（浏览器，localStorage）
        │
        ├─ 导出 JSON ──────────────┐
        ├─ 导出 5×CSV ─────────────┤
        └─ 导出 图标图集 PNG+JSON ─┤
                                   ▼
                        UE Content/Data/
                                   │
                        import_datatables.py
                                   ▼
                  DT_ItemDef / DT_MachineDef / DT_RecipeDef
                  DT_TechDef / DT_ElementDef  (+ 图集贴图)
```

---

# 3D 体块 → UE（GLB 导入）

## 一、导出

在「机器」列表点击任意一行（或行尾「3D」按钮）打开 3D 预览，弹窗右下角 **导出 GLB**。

导出后的结构经过专门处理，**为 UE 优化**：

| 处理 | 为什么 |
|---|---|
| **合并成 1 个网格** | 不合并的话，30 个部件会变成 30 个独立 StaticMesh 资产，根本没法用 |
| **按材质角色分槽** | 1 个网格 + N 个材质槽（通常 4~6 个），和 UE 的多材质槽模型一致 |
| **材质命名 `M_body` / `M_glow`** | 导入 UE 后材质实例名可读，不是 `Material_0` |
| **节点名 = 机器 ID** | 静态网格资产直接叫 `MC_ARC` |
| **等比缩放到占地内** | 3×3 的建筑严格不超过 3×3 米，铺排时不会互相穿插 |
| **底部对齐 y=0** | 轴心在底面中心，拖进关卡直接落地 |
| **extras 写入动画参数** | GLB 是静态网格，动画需在 UE 重建，这里把参数一起带过去 |

`extras` 里的数据结构：

```json
{
  "forgeworks": {
    "id": "MC_ARC", "name": "电弧熔炉",
    "category": "冶炼", "footprint": "3×3", "tier": 0,
    "unit": "meter (1 unit = 1 grid)",
    "pivot": "bottom-center",
    "materialSlots": ["M_base","M_dark","M_body","M_light","M_glow"],
    "animations": [
      { "part":"cyl", "role":"glow", "kind":"pulse", "params":{"speed":1.7,"min":0.6,"max":2.4} }
    ]
  }
}
```

## 二、导入 UE

1. 把 `.glb` 拖进 Content Browser
2. 导入对话框（Interchange glTF）里：
   - **Import Uniform Scale = 1**（glTF 单位是米，UE 自动 ×100 转厘米）
   - 勾选 **Generate Missing Collisions**（会生成简单凸包碰撞）
   - **Import Materials** 保持勾选
3. 生成的资产：
   - `MC_ARC`（Static Mesh，1 个网格，N 个材质槽）
   - `M_body` / `M_dark` / ... 材质实例
4. 拖进关卡，缩放保持 1.0 —— 尺寸就是 3×3 米（300×300 uu）

## 三、能保证什么 / 不能保证什么

**能保证：**

| 项 | 说明 |
|---|---|
| 网格结构 | 1 个 StaticMesh，N 个材质槽，命名可读 |
| 尺寸 | 1 格 = 1 米，导入后 ×100 = 厘米；不超过声明占地 |
| 轴心 | 底面中心，落地即对齐 |
| 朝向 | glTF Y-up → UE Z-up 自动转换，正面朝 +X |
| PBR 参数 | baseColor / metallic / roughness / emissive 会带过去 |
| 碰撞 | 导入时勾选即可自动生成简单碰撞 |
| 顶点数 | 单建筑约 2k~5k，属于 blockout 量级 |

**不能保证（必须知道）：**

| 项 | 原因 | 怎么办 |
|---|---|---|
| **动画** | GLB 只导出静态姿势（当前姿态）。旋转/浮动/脉动是 JS 程序化的 | 参数在 `extras.animations` 里，在 UE 里用 Timeline 或材质参数重建 |
| **自发光强度 > 1** | glTF 规范里 `emissiveFactor` 上限是 1.0，脉动峰值 2.4 会被截断 | UE 里给材质加 Emissive 乘数（2~3）才有辉光 |
| **材质观感** | glTF PBR 是「参数级」迁移，不含环境反射、色调映射 | UE 里套自己的后处理与反射球 |
| **贴图 / 法线** | 没有导出贴图（几何是纯色块） | 需要的话自己展 UV / 做材质 |
| **透明** | 玻璃材质的 alpha 在部分导入设置下会变不透明 | 导入后把该材质槽改成 Translucent |
| **LOD** | 没有 LOD | 项目里用 Auto LOD |
| **UV** | 用的是几何体默认 UV，不是为贴图设计的 | 展 UV 后重做材质 |

## 四、这套东西的定位

**明确的 blockout / 占位模型**，不是最终美术资产。

它解决的问题是：**在美术进场之前，让策划和程序能验证占位体积、铺排间距、
动画逻辑与建筑朝向**。等真实模型做好后，把机器数据里的 `mesh` 字段指向真模型即可，
DataTable 里的其余字段（占地、耗电、配方）完全不用改。

