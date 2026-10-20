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
    UPROPERTY(EditAnywhere, BlueprintReadOnly) FName TierUnlock;
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
