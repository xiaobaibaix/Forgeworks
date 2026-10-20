"""
StellarEra 内容数据 → UE 5.8 DataTable 导入脚本
================================================================

在 UE 编辑器的 Python 控制台运行，或用 -ExecutePythonScript 启动参数调用。

用法：
    import stellarera_import
    stellarera_import.import_all(
        json_path=r"D:/Projects/StellarEra/Content/Data/StellarEra_Content.json",
        dest_dir=r"D:/Projects/StellarEra/Content/Data",
    )

或者更简单：
    exec(open(r"D:/Projects/StellarEra/Tools/stellarera_import.py").read())
    import_all()

依赖：
    - unreal 模块（UE 内置）
    - 标准库 json / os / csv（无需额外安装）

生成的资产：
    DT_ItemDef, DT_MachineDef, DT_RecipeDef, DT_TechDef, DT_ElementDef
"""

import unreal
import json
import os

# ============================================================
# 行结构定义（与 UE 侧 C++ 结构体对应）
# ============================================================
#
# FItemDef:
#   Id: str, DisplayName: str, Tier: int, Type: str, Value: int,
#   Color: str, Desc: str
#
# FMachineDef:
#   Id: str, DisplayName: str, Tier: int, Category: str,
#   FootprintX: int, FootprintY: int, PowerDraw: int, Desc: str
#
# FItemAmount:
#   ItemId: str, Amount: float
#
# FRecipeDef:
#   Id: str, DisplayName: str, MachineType: str, Category: str, Tier: int,
#   CycleTime: float, PowerDraw: float, TierUnlock: str,
#   Inputs: TArray<FItemAmount>, Outputs: TArray<FItemAmount>, Desc: str
#
# FTechDef:
#   Id: str, DisplayName: str, Tier: int, Cost: int,
#   Prerequisites: TArray[str], Unlocks: TArray[str], Desc: str
#
# FElementDef:
#   Id: str, Symbol: str, DisplayName: str, Tier: int, Color: str
# ============================================================


def _log(msg, level="info"):
    if level == "warning":
        unreal.log_warning("[StellarEra] " + str(msg))
    elif level == "error":
        unreal.log_error("[StellarEra] " + str(msg))
    else:
        unreal.log("[StellarEra] " + str(msg))


def _hex_to_linear(hex_str):
    """sRGB hex 转 UE 线性 RGBA 数组。颜色在编辑器里更准。"""
    try:
        h = hex_str.lstrip("#")
        if len(h) != 6:
            return [1.0, 1.0, 1.0, 1.0]
        srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        # sRGB → linear
        def to_lin(c):
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        return [to_lin(c) for c in srgb] + [1.0]
    except Exception:
        return [1.0, 1.0, 1.0, 1.0]


# ============================================================
# DataTable 导入核心
# ============================================================

def _import_datatable(json_path, dest_dir, table_name, row_struct_name, row_mapper):
    """
    通用导入流程：
      1. 读 JSON
      2. 组装行数据
      3. 创建/覆盖 DataTable 资产
    """
    unreal_dir = unreal.Paths.convert_relative_path_to_full(dest_dir)
    os.makedirs(unreal_dir, exist_ok=True)

    asset_path = os.path.join(unreal_dir, table_name + ".uasset")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 找结构体
    struct = None
    for candidate in unreal.load_object(None, "/Script/Engine." + row_struct_name):
        struct = candidate
        break
    if struct is None:
        # 有些情况下需要用 AssetTools 工厂创建
        _log("未找到结构体 %s，尝试反射查找" % row_struct_name, "warning")

    # 组装行
    rows = []
    for src in data:
        row = row_mapper(src)
        if row is not None:
            rows.append(row)

    # 删除旧资产
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.EditorAssetLibrary.delete_asset(asset_path)

    # 创建 DataTable
    factory = unreal.DataTableFactory()
    factory.struct = struct
    asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        table_name, unreal_dir, unreal.DataTable, factory
    )
    if asset is None:
        _log("创建 DataTable 失败: " + table_name, "error")
        return None

    # 填充
    asset.get_editor_property("row_struct")  # 确保结构正确

    # 用 DataTableFunctionLibrary 写入行
    for row in rows:
        try:
            unreal.DataTableFunctionLibrary.add_row(asset, row)
        except Exception as e:
            _log("写入行失败: %s" % e, "warning")

    unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
    _log("已生成 %s (%d 行)" % (table_name, len(rows)))
    return asset


# ============================================================
# 各表映射
# ============================================================

def _map_item(src):
    row = unreal.DataTableRowHandle()
    row.row_name = src["id"]

    item = unreal.StarEraItemDef() if hasattr(unreal, "StarEraItemDef") else None
    if item is None:
        return None

    item.set_editor_property("id", src["id"])
    item.set_editor_property("display_name", src.get("name", src["id"]))
    item.set_editor_property("tier", int(src.get("tier", 0)))
    item.set_editor_property("type", src.get("type", "raw"))
    item.set_editor_property("value", int(src.get("value", 0)))
    item.set_editor_property("color", _hex_to_linear(src.get("color", "#888780")))
    item.set_editor_property("desc", src.get("desc", ""))

    # ---- 资源字段 ----
    # 图标：自定义图标是内嵌 dataURL，Python 侧不直接写入资产，
    # 而是记录"是否有自定义图标"，实际贴图走图集（IconSheet + IconAtlas）。
    item.set_editor_property("has_custom_icon", bool(src.get("icon")))
    # 模型：软引用路径，留空表示未绑定
    mesh_path = (src.get("mesh") or "").strip()
    mat_path = (src.get("mat") or "").strip()
    if hasattr(item, "set_editor_property"):
        try:
            item.set_editor_property("mesh_path", mesh_path)
            item.set_editor_property("material_path", mat_path)
            item.set_editor_property("model_status", src.get("modelStatus", "primitive"))
        except Exception:
            # 若结构体还没加这些字段，跳过而不中断整表导入
            pass

    row.row = item
    return row


def _map_machine(src):
    if not hasattr(unreal, "StarEraMachineDef"):
        return None
    row = unreal.DataTableRowHandle()
    row.row_name = src["id"]

    m = unreal.StarEraMachineDef()
    m.set_editor_property("id", src["id"])
    m.set_editor_property("display_name", src.get("name", src["id"]))
    m.set_editor_property("tier", int(src.get("tier", 0)))
    m.set_editor_property("category", src.get("cat", ""))
    m.set_editor_property("footprint_x", int(src.get("fx", 1)))
    m.set_editor_property("footprint_y", int(src.get("fy", 1)))
    m.set_editor_property("power_draw", int(src.get("power", 0)))
    m.set_editor_property("desc", src.get("desc", ""))

    row.row = m
    return row


def _map_recipe(src):
    if not hasattr(unreal, "StarEraRecipeDef"):
        return None
    row = unreal.DataTableRowHandle()
    row.row_name = src["id"]

    r = unreal.StarEraRecipeDef()
    r.set_editor_property("id", src["id"])
    r.set_editor_property("display_name", src.get("name", src["id"]))
    r.set_editor_property("machine_type", src.get("machine", ""))
    r.set_editor_property("category", src.get("cat", ""))
    r.set_editor_property("tier", int(src.get("tier", 0)))
    r.set_editor_property("cycle_time", float(src.get("cycle", 1.0)))
    r.set_editor_property("power_draw", float(src.get("power", 0.0)))
    r.set_editor_property("tier_unlock", src.get("unlock", "E0"))
    r.set_editor_property("desc", src.get("desc", ""))

    inputs = []
    for i in src.get("inputs", []):
        if hasattr(unreal, "StarEraItemAmount"):
            ia = unreal.StarEraItemAmount()
            ia.set_editor_property("item_id", i.get("item", ""))
            ia.set_editor_property("amount", float(i.get("amount", 0.0)))
            inputs.append(ia)
    r.set_editor_property("inputs", inputs)

    outputs = []
    for o in src.get("outputs", []):
        if hasattr(unreal, "StarEraItemAmount"):
            oa = unreal.StarEraItemAmount()
            oa.set_editor_property("item_id", o.get("item", ""))
            oa.set_editor_property("amount", float(o.get("amount", 0.0)))
            outputs.append(oa)
    r.set_editor_property("outputs", outputs)

    row.row = r
    return row


def _map_tech(src):
    if not hasattr(unreal, "StarEraTechDef"):
        return None
    row = unreal.DataTableRowHandle()
    row.row_name = src["id"]

    t = unreal.StarEraTechDef()
    t.set_editor_property("id", src["id"])
    t.set_editor_property("display_name", src.get("name", src["id"]))
    t.set_editor_property("tier", int(src.get("tier", 0)))
    t.set_editor_property("cost", int(src.get("cost", 0)))
    t.set_editor_property("prerequisites", src.get("prereqs", []))
    t.set_editor_property("unlocks", src.get("unlocks", []))
    t.set_editor_property("desc", src.get("desc", ""))

    row.row = t
    return row


def _map_element(src):
    if not hasattr(unreal, "StarEraElementDef"):
        return None
    row = unreal.DataTableRowHandle()
    row.row_name = src["id"]

    e = unreal.StarEraElementDef()
    e.set_editor_property("id", src["id"])
    e.set_editor_property("symbol", src.get("symbol", src["id"]))
    e.set_editor_property("display_name", src.get("name", src["id"]))
    e.set_editor_property("tier", int(src.get("tier", 0)))
    e.set_editor_property("color", _hex_to_linear(src.get("color", "#888780")))

    row.row = e
    return row


# ============================================================
# 入口
# ============================================================

def import_all(json_path=None, dest_dir=None):
    """
    主入口。参数可省略，默认读取项目内默认路径。
    """
    project_dir = unreal.Paths.project_dir()

    if json_path is None:
        json_path = os.path.join(project_dir, "Content", "Data", "StellarEra_Content.json")
    if dest_dir is None:
        dest_dir = os.path.join(project_dir, "Content", "Data")

    if not os.path.isfile(json_path):
        _log("找不到 JSON: %s" % json_path, "error")
        _log("请先在内容设计器中导出 JSON 并放到该路径", "warning")
        return

    _log("开始导入，数据源: %s" % json_path)
    _log("目标目录: %s" % dest_dir)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 预处理机器占地
    for m in data.get("machines", []):
        fp = str(m.get("footprint", "1x1"))
        parts = fp.replace("×", "x").split("x")
        try:
            m["fx"] = int(parts[0])
            m["fy"] = int(parts[1]) if len(parts) > 1 else int(parts[0])
        except Exception:
            m["fx"] = 1
            m["fy"] = 1

    jobs = [
        ("DT_ItemDef",    "StarEraItemDef",    "items",    _map_item),
        ("DT_MachineDef", "StarEraMachineDef", "machines", _map_machine),
        ("DT_RecipeDef",  "StarEraRecipeDef",  "recipes",  _map_recipe),
        ("DT_TechDef",    "StarEraTechDef",    "techs",    _map_tech),
        ("DT_ElementDef", "StarEraElementDef", "elements", _map_element),
    ]

    ok = 0
    for table_name, struct_name, key, mapper in jobs:
        if key not in data:
            _log("跳过 %s（JSON 中无 %s）" % (table_name, key), "warning")
            continue

        # 把该类数据临时写到一个独立 JSON，复用 _import_datatable
        tmp_json = os.path.join(dest_dir, "_tmp_%s.json" % key)
        os.makedirs(dest_dir, exist_ok=True)
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(data[key], f, ensure_ascii=False)

        # 逐行映射（因为要传 python dict 而不是整份）
        rows = []
        for src in data[key]:
            row = _make_row_handle(src, mapper)
            if row is not None:
                rows.append(row)

        asset_path = os.path.join(unreal.Paths.convert_relative_path_to_full(dest_dir),
                                  table_name + ".uasset")
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            unreal.EditorAssetLibrary.delete_asset(asset_path)

        factory = unreal.DataTableFactory()
        factory.set_editor_property("struct", _find_struct(struct_name))
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            table_name,
            unreal.Paths.convert_relative_path_to_full(dest_dir),
            unreal.DataTable,
            factory
        )
        if asset is None:
            _log("创建失败: " + table_name, "error")
            continue

        for row in rows:
            try:
                unreal.DataTableFunctionLibrary.add_row(asset, row)
            except Exception as e:
                _log("写入失败 %s: %s" % (row.row_name, e), "warning")

        unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
        _log("✓ %s  (%d 行)" % (table_name, len(rows)))
        ok += 1

        os.remove(tmp_json)

    _log("导入完成，成功 %d/5 张表" % ok)
    _log("提示：若结构体类型报错，说明 UE 侧的 FStruct 尚未创建——"
         "请先按本文件头部的注释定义 C++ 结构体并重新编译。", "warning")


def _find_struct(struct_name):
    """在已加载的类里找 RowStruct。"""
    try:
        found = unreal.load_object(None, "/Script/Engine." + struct_name)
        if found:
            return found
    except Exception:
        pass
    # 退路：让用户在编辑器里手动指定
    _log("未自动找到 %s，请在 DataTable 工厂里手动设置 RowStruct" % struct_name, "warning")
    return None


def _make_row_handle(src, mapper):
    """mapper 返回一个 DataTableRowHandle 或 None。"""
    try:
        return mapper(src)
    except Exception as e:
        _log("映射失败 %s: %s" % (src.get("id", "?"), e), "warning")
        return None


# ============================================================
# UE 侧 C++ 结构体参考（复制到你的模块头文件）
# ============================================================
#
# USTRUCT(BlueprintType)
# struct FStarEraItemAmount {
#     GENERATED_BODY()
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString ItemId;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) float Amount = 0.f;
# };
#
# USTRUCT(BlueprintType)
# struct FStarEraItemDef {
#     GENERATED_BODY()
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FName Type;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Value = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FLinearColor Color;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;
#
#     // ---- 资源字段（新增） ----
#     // 图标走图集：IconSheet 贴图 + IconAtlas 里的 UV，这里只标记是否自定义
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) bool bHasCustomIcon = false;
#     // 模型软引用，空字符串表示未绑定
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) TSoftObjectPtr<UStaticMesh> MeshPath;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) TSoftObjectPtr<UMaterialInterface> MaterialPath;
#     // none / primitive / needed / done
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FName ModelStatus;
#     // 图标在图集中的 UV（运行时由 IconAtlas 填充，也可以手动指定）
#     UPROPERTY(BlueprintReadOnly) FVector2D IconUV0 = FVector2D::ZeroVector;
#     UPROPERTY(BlueprintReadOnly) FVector2D IconUV1 = FVector2D::OneVector;
# };
#
# USTRUCT(BlueprintType)
# struct FStarEraMachineDef {
#     GENERATED_BODY()
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FName Category;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 FootprintX = 1;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 FootprintY = 1;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 PowerDraw = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;
# };
#
# USTRUCT(BlueprintType)
# struct FStarEraRecipeDef {
#     GENERATED_BODY()
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FName MachineType;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FName Category;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) float CycleTime = 1.f;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) float PowerDraw = 0.f;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FName TierUnlock;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FStarEraItemAmount> Inputs;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FStarEraItemAmount> Outputs;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;
# };
#
# USTRUCT(BlueprintType)
# struct FStarEraTechDef {
#     GENERATED_BODY()
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Cost = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FString> Prerequisites;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) TArray<FString> Unlocks;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Desc;
# };
#
# USTRUCT(BlueprintType)
# struct FStarEraElementDef {
#     GENERATED_BODY()
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Id;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Symbol;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Tier = 0;
#     UPROPERTY(EditAnywhere, BlueprintReadOnly) FLinearColor Color;
# };
# ============================================================
