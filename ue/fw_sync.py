import json
import os
import re
import urllib.request
import datetime


BRIDGE_URL = 'http://127.0.0.1:8787'
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MACHINE_ID = re.compile(r'^[A-Za-z0-9_]+$')


def _safe_relative_path(value):
    normalized = str(value or '').replace('\\', '/')
    if not normalized or normalized.startswith('/') or any(part in ('', '.', '..') for part in normalized.split('/')):
        raise ValueError('invalid relative asset path')
    return normalized


def build_import_plan(manifest, forgeworks_root, asset_ids=None):
    assets = (manifest or {}).get('assets') or {}
    selected = set(asset_ids) if asset_ids else set(assets)
    plan = []
    for asset_id in sorted(selected):
        if not MACHINE_ID.fullmatch(asset_id):
            raise ValueError('invalid machine id: %s' % asset_id)
        record = assets.get(asset_id)
        if not record or record.get('kind') != 'machine':
            continue
        mesh_records = (record.get('files') or {}).get('mesh') or []
        mesh = mesh_records[0] if isinstance(mesh_records, list) else mesh_records
        relative_path = _safe_relative_path(mesh.get('path'))
        source_path = os.path.realpath(os.path.join(forgeworks_root, '_Source', 'Machines', asset_id, relative_path))
        machine_root = os.path.realpath(os.path.join(forgeworks_root, '_Source', 'Machines', asset_id))
        if os.path.commonpath((source_path, machine_root)) != machine_root or not os.path.isfile(source_path):
            raise ValueError('missing or unsafe mesh file for %s' % asset_id)
        metadata = record.get('meta') or {}
        expected_size = metadata.get('sizeCm')
        if not expected_size and isinstance(metadata.get('sizeM'), (list, tuple)):
            expected_size = [float(value) * 100 for value in metadata['sizeM']]
        plan.append({
            'id': asset_id,
            'sourcePath': source_path,
            'contentPath': '/Game/Forgeworks/Machines/%s' % asset_id,
            'assetName': 'SM_%s' % asset_id,
            'sha1': mesh.get('sha1'),
            'expectedSizeCm': expected_size,
            'importOptions': {'uniformScale': 100.0, 'combineMeshes': True, 'generateLightmapUV': True},
        })
    return plan


def validate_measured_size(expected, measured):
    if not expected:
        return
    if len(expected) != 3:
        raise ValueError('manifest expected size must contain three dimensions')
    actual = [measured['x'], measured['y'], measured['z']]
    for target, value in zip(expected, actual):
        target = float(target)
        if target <= 0 or abs(value - target) > max(2.0, target * 0.08):
            raise RuntimeError('UE 尺寸与导出规格不符：预期 %s cm，实际 %.2f cm；检查 GLTF 导入单位设置' % (target, value))


def _read_manifest():
    with urllib.request.urlopen(BRIDGE_URL + '/api/manifest', timeout=5) as response:
        result = json.loads(response.read().decode('utf-8'))
    if not result.get('ok') or not result.get('manifest'):
        raise RuntimeError('Forgeworks Bridge 未绑定 UE 项目')
    return result['manifest']


def _post_report(payload):
    request = urllib.request.Request(
        BRIDGE_URL + '/api/ue/report',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode('utf-8'))


def _set_if_supported(target, property_name, value):
    try:
        target.set_editor_property(property_name, value)
    except Exception:
        pass


def _measure_mesh(unreal, asset_path):
    mesh = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not mesh or not isinstance(mesh, unreal.StaticMesh):
        raise RuntimeError('imported StaticMesh not found: %s' % asset_path)
    bounds = mesh.get_bounds()
    extent = bounds.box_extent
    size = {'x': float(extent.x) * 2, 'y': float(extent.y) * 2, 'z': float(extent.z) * 2}
    materials = []
    for item in mesh.get_editor_property('static_materials'):
        materials.append(str(item.get_editor_property('material_slot_name')))
    return mesh, {'bounds': size, 'triangles': int(mesh.get_num_triangles(0)), 'materialSlots': materials}


def import_assets(asset_ids=None):
    import unreal

    manifest = _read_manifest()
    project_root = (manifest.get('project') or {}).get('root')
    if not project_root:
        raise RuntimeError('manifest 未记录 UE 项目根目录')
    forgeworks_root = os.path.join(project_root, 'Forgeworks')
    plan = build_import_plan(manifest, forgeworks_root, asset_ids)
    manager_class = getattr(unreal, 'InterchangeManager', None)
    if not manager_class:
        raise RuntimeError('启用 Interchange Framework 插件后再运行')
    manager = manager_class.get_interchange_manager_scripted()
    if not manager:
        raise RuntimeError('Interchange Manager 不可用')
    reports = []
    for item in plan:
        try:
            source_data = manager.create_source_data(item['sourcePath'])
            parameters = unreal.ImportAssetParameters()
            _set_if_supported(parameters, 'is_automated', True)
            _set_if_supported(parameters, 'replace_existing', True)
            _set_if_supported(parameters, 'run_synchronous', True)
            _set_if_supported(parameters, 'destination_name', item['assetName'])
            if not manager.import_asset(item['contentPath'], source_data, parameters):
                raise RuntimeError('Interchange import failed')
            if not unreal.EditorAssetLibrary.save_directory(item['contentPath'], False, True):
                raise RuntimeError('UE could not save imported assets')
            object_path = item['contentPath'] + '/' + item['assetName'] + '.' + item['assetName']
            _, measured = _measure_mesh(unreal, object_path)
            validate_measured_size(item.get('expectedSizeCm'), measured['bounds'])
            ue = {
                'contentPath': item['contentPath'],
                'importedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'importedBy': 'fw_sync.py',
                'assets': {'mesh': object_path, 'materials': measured['materialSlots']},
                'importOptions': item['importOptions'],
                'bounds': measured['bounds'],
                'triangles': measured['triangles'],
                'materialSlots': measured['materialSlots'],
                'sourceSha1': item['sha1'],
            }
            response = _post_report({'id': item['id'], 'ue': ue})
            if not response.get('ok'):
                raise RuntimeError(response.get('error', 'Bridge rejected UE report'))
            reports.append({'id': item['id'], 'ok': True, 'ue': ue})
        except Exception as exception:
            reports.append({'id': item['id'], 'ok': False, 'error': str(exception)})
            unreal.log_error('[Forgeworks] %s: %s' % (item['id'], exception))
    return reports


def run():
    reports = import_assets()
    success = sum(1 for report in reports if report['ok'])
    print('[Forgeworks] UE import finished: %s/%s successful' % (success, len(reports)))
    return reports


if __name__ == '__main__':
    run()
