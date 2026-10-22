import json
import os
import re
import urllib.request


BRIDGE_URL = 'http://127.0.0.1:8787'
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAFE_OBJECT_PATH = re.compile(r'^/Game/Forgeworks/Machines/([A-Za-z0-9_]+)/([A-Za-z0-9_.]+)$')


def target_forgeworks_root():
    local = os.path.join(PROJECT_ROOT, 'Forgeworks')
    if os.path.isdir(local):
        return local
    with urllib.request.urlopen(BRIDGE_URL + '/api/project/info', timeout=5) as response:
        info = json.loads(response.read().decode('utf-8'))
    if not info.get('ok') or not info.get('root'):
        raise RuntimeError('尚未从 Forgeworks 导出资产')
    root = info['root']
    return root if os.path.basename(root) == 'Forgeworks' else os.path.join(root, 'Forgeworks')


def normalize_assets(assets):
    rows = []
    for asset in assets or []:
        match = SAFE_OBJECT_PATH.fullmatch(str(asset.get('objectPath') or ''))
        if not match or asset.get('class') != 'StaticMesh':
            continue
        bounds = asset.get('bounds') or {}
        clean_bounds = {}
        for axis in ('x', 'y', 'z'):
            value = bounds.get(axis)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                break
            clean_bounds[axis] = float(value)
        if len(clean_bounds) != 3:
            continue
        triangles = asset.get('triangles')
        if isinstance(triangles, bool) or not isinstance(triangles, int) or triangles < 0:
            continue
        slots = [str(slot) for slot in asset.get('materialSlots', []) if str(slot)]
        dependencies = [str(path) for path in asset.get('dependencies', []) if str(path).startswith('/Game/')]
        rows.append({
            'id': match.group(1),
            'objectPath': match.group(0),
            'class': 'StaticMesh',
            'bounds': clean_bounds,
            'triangles': triangles,
            'materialSlots': slots,
            'dependencies': dependencies,
        })
    return sorted(rows, key=lambda item: item['objectPath'])


def collect_assets(unreal):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    data = registry.get_assets_by_path('/Game/Forgeworks/Machines', recursive=True)
    rows = []
    for asset_data in data or []:
        class_name = str(getattr(asset_data, 'asset_class_path', getattr(asset_data, 'asset_class', '')))
        if 'StaticMesh' not in class_name:
            continue
        mesh = asset_data.get_asset()
        if not mesh:
            continue
        path = getattr(asset_data, 'object_path', None)
        if path is None:
            path = asset_data.get_editor_property('object_path')
        path = str(path)
        bounds = mesh.get_bounds().box_extent
        dependencies = []
        try:
            dependencies = [str(item) for item in registry.get_dependencies(asset_data.package_name)]
        except Exception:
            pass
        slots = [str(item.get_editor_property('material_slot_name')) for item in mesh.get_editor_property('static_materials')]
        rows.append({
            'objectPath': path,
            'class': 'StaticMesh',
            'bounds': {'x': bounds.x * 2, 'y': bounds.y * 2, 'z': bounds.z * 2},
            'triangles': mesh.get_num_triangles(0),
            'materialSlots': slots,
            'dependencies': dependencies,
        })
    return normalize_assets(rows)


def write_snapshot(assets, path=None):
    target = path or os.path.join(target_forgeworks_root(), '_Sync', 'ue_assets.json')
    snapshot = {'schemaVersion': 1, 'generatedAt': None, 'assets': normalize_assets(assets)}
    import datetime
    snapshot['generatedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temp_path = target + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
    os.replace(temp_path, target)
    return snapshot


def run():
    import unreal
    snapshot = write_snapshot(collect_assets(unreal))
    unreal.log('[Forgeworks] Registry snapshot: %s assets' % len(snapshot['assets']))
    return snapshot


if __name__ == '__main__':
    run()
