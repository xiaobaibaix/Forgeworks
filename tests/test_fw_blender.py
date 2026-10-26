import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import tempfile
import time
import urllib.request
import unittest
import base64
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'fw_blender.py'
sys.path.insert(0, str(ROOT / 'tools'))
bridge_args = sys.argv
sys.argv = [sys.argv[0]]
import bridge
import fw_parts
sys.argv = bridge_args


def find_blender():
    blender = os.environ.get('FW_BLENDER') or shutil.which('blender')
    if not blender:
        candidates = ['/Volumes/KingstonXS1000Media/app/Blender.app/Contents/MacOS/Blender', '/Applications/Blender.app/Contents/MacOS/Blender']
        blender = next((candidate for candidate in candidates if Path(candidate).is_file()), None)
    return blender


def run_blender(blender, arguments, timeout=120):
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / 'report.json'
        result = subprocess.run(
            [blender, '--background', '--factory-startup', '--python-exit-code', '1',
             '--python', str(SCRIPT), '--', '--report', str(report)] + arguments,
            capture_output=True, text=True, timeout=timeout)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(report.read_text())


def _write_glb(path, document, binary):
    json_chunk = json.dumps(document, separators=(',', ':')).encode()
    json_chunk += b' ' * ((4 - len(json_chunk) % 4) % 4)
    binary.extend(b'\0' * ((4 - len(binary) % 4) % 4))
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    path.write_bytes(
        struct.pack('<4sII', b'glTF', 2, total)
        + struct.pack('<I4s', len(json_chunk), b'JSON') + json_chunk
        + struct.pack('<I4s', len(binary), b'BIN\0') + binary
    )


def make_box_glb(path, size=(1.0, 1.0, 2.0), closed=True):
    # size 按 Blender 的 X/Y/Z 给；glTF 是 Y 轴朝上，写文件时把 Z 高度换到 Y
    half = [value / 2 for value in (size[0], size[2], size[1])]
    points = [(-half[0], -half[1], -half[2]), (half[0], -half[1], -half[2]),
              (half[0], half[1], -half[2]), (-half[0], half[1], -half[2]),
              (-half[0], -half[1], half[2]), (half[0], -half[1], half[2]),
              (half[0], half[1], half[2]), (-half[0], half[1], half[2])]
    triangles = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
                 (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    if not closed:
        triangles = triangles[2:]

    positions = b''.join(struct.pack('<3f', *point) for point in points)
    indices = b''.join(struct.pack('<3H', *triangle) for triangle in triangles)
    binary = bytearray(positions)
    while len(binary) % 4:
        binary.append(0)
    index_offset = len(binary)
    binary.extend(indices)
    document = {
        'asset': {'version': '2.0'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]}],
        'materials': [{'name': 'M_box'}],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions), 'target': 34962},
            {'buffer': 0, 'byteOffset': index_offset, 'byteLength': len(indices), 'target': 34963},
        ],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': len(points), 'type': 'VEC3',
             'min': [-half[0], -half[1], -half[2]], 'max': [half[0], half[1], half[2]]},
            {'bufferView': 1, 'componentType': 5123, 'count': len(triangles) * 3,
             'type': 'SCALAR', 'min': [0], 'max': [len(points) - 1]},
        ],
    }
    _write_glb(path, document, binary)


def make_glb(path):
    binary = bytearray()
    views = []
    accessors = []
    primitives = []

    for material in range(5):
        points = [(-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.0, 1.0, 0.5)]
        positions = b''.join(struct.pack('<3f', *point) for point in points)
        while len(binary) % 4:
            binary.append(0)
        position_offset = len(binary)
        binary.extend(positions)
        views.append({'buffer': 0, 'byteOffset': position_offset, 'byteLength': len(positions), 'target': 34962})
        position_accessor = len(accessors)
        accessors.append({'bufferView': len(views) - 1, 'componentType': 5126, 'count': 3, 'type': 'VEC3', 'min': [-0.5, 0.0, -0.5], 'max': [0.5, 1.0, 0.5]})

        indices = struct.pack('<3H', 0, 1, 2)
        while len(binary) % 4:
            binary.append(0)
        index_offset = len(binary)
        binary.extend(indices)
        views.append({'buffer': 0, 'byteOffset': index_offset, 'byteLength': len(indices), 'target': 34963})
        index_accessor = len(accessors)
        accessors.append({'bufferView': len(views) - 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR', 'min': [0], 'max': [2]})
        primitives.append({'attributes': {'POSITION': position_accessor}, 'indices': index_accessor, 'material': material})

    document = {
        'asset': {'version': '2.0'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': primitives}],
        'materials': [{'name': f'M_{index}'} for index in range(5)],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': views,
        'accessors': accessors,
    }
    json_chunk = json.dumps(document, separators=(',', ':')).encode()
    json_chunk += b' ' * ((4 - len(json_chunk) % 4) % 4)
    binary.extend(b'\0' * ((4 - len(binary) % 4) % 4))
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    path.write_bytes(
        struct.pack('<4sII', b'glTF', 2, total)
        + struct.pack('<I4s', len(json_chunk), b'JSON') + json_chunk
        + struct.pack('<I4s', len(binary), b'BIN\0') + binary
    )


class BlenderPipelineTest(unittest.TestCase):
    def test_valid_glb_reports_mesh_materials_bounds_and_thumbnail(self):
        blender = os.environ.get('FW_BLENDER') or shutil.which('blender')
        if not blender:
            candidates = ['/Volumes/KingstonXS1000Media/app/Blender.app/Contents/MacOS/Blender', '/Applications/Blender.app/Contents/MacOS/Blender']
            blender = next((candidate for candidate in candidates if Path(candidate).is_file()), None)
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / 'sample.glb'
            thumbnail = temp / 'sample.png'
            report = temp / 'report.json'
            make_glb(source)
            result = subprocess.run([
                blender, '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', str(SCRIPT), '--', '--input', str(source),
                '--thumbnail', str(thumbnail), '--report', str(report),
                '--expected-meshes', '1', '--expected-materials', '5',
            ], capture_output=True, text=True, timeout=120)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report.read_text())
            self.assertTrue(data['valid'], data)
            self.assertEqual(data['meshCount'], 1)
            self.assertEqual(data['materialSlots'], 5)
            self.assertEqual(len(data['boundsMeters']), 3)
            self.assertTrue(all(size > 0 for size in data['boundsMeters']))
            self.assertTrue(thumbnail.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            # 资产方面字段：缺少 UV / 贴图不应判失败，但字段必须存在
            self.assertFalse(data['uvPresent'])
            self.assertEqual(data['uvLayers'], [])
            self.assertEqual(data['imageCount'], 0)
            self.assertEqual(data['normalMapSlots'], 0)
            self.assertEqual(data['animationCount'], 0)
            self.assertEqual(len(data['materialDetails']), 5)
            self.assertEqual(data['forgeworks'], {})

    def test_decimate_reduces_triangles_and_writes_glb(self):
        blender = os.environ.get('FW_BLENDER') or shutil.which('blender')
        if not blender:
            candidates = ['/Volumes/KingstonXS1000Media/app/Blender.app/Contents/MacOS/Blender', '/Applications/Blender.app/Contents/MacOS/Blender']
            blender = next((candidate for candidate in candidates if Path(candidate).is_file()), None)
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / 'sample.glb'
            output = temp / 'decimated.glb'
            report = temp / 'report.json'
            make_glb(source)
            result = subprocess.run([
                blender, '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', str(SCRIPT), '--', '--mode', 'decimate',
                '--input', str(source), '--output', str(output),
                '--report', str(report), '--target-faces', '3',
            ], capture_output=True, text=True, timeout=120)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report.read_text())
            self.assertTrue(data['valid'], data)
            self.assertEqual(data['trianglesBefore'], 5)
            self.assertLess(data['trianglesAfter'], data['trianglesBefore'])
            self.assertTrue(output.read_bytes().startswith(b'glTF'))

    def test_measure_reports_object_bounds(self):
        blender = find_blender()
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'box.glb'
            make_box_glb(source, (1.0, 2.0, 3.0))
            data = run_blender(blender, ['--mode', 'measure', '--inputs', str(source)])

            self.assertTrue(data['valid'], data)
            entry = data['files'][0]
            for axis, expected in enumerate((0.5, 1.0, 1.5)):
                self.assertAlmostEqual(entry['min'][axis], -expected, places=4)
                self.assertAlmostEqual(entry['max'][axis], expected, places=4)
            self.assertEqual(entry['meshCount'], 1)
            self.assertEqual(len(entry['objects']), 1)

    def test_cut_slices_stay_within_slabs(self):
        blender = find_blender()
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / 'open_box.glb'
            # 开放网格能暴露布尔求交越界的问题
            make_box_glb(source, (2.0, 2.0, 2.0), closed=False)
            data = run_blender(blender, ['--mode', 'cut', '--input', str(source),
                                         '--out-dir', str(temp / 'parts'),
                                         '--parts', '3', '--axis', 'z'])

            self.assertTrue(data['valid'], data)
            self.assertEqual(len(data['files']), 3)
            epsilon = 2.0 * 0.001
            step = 2.0 / 3
            for item in data['files']:
                low = -1.0 + step * item['index'] - epsilon
                high = -1.0 + step * (item['index'] + 1) + epsilon
                self.assertGreaterEqual(item['min'][2], low - 1e-4)
                self.assertLessEqual(item['max'][2], high + 1e-4)
                self.assertLessEqual(max(abs(value) for value in item['min'][:2]), 1.0 + 1e-4)
                self.assertLessEqual(max(abs(value) for value in item['max'][:2]), 1.0 + 1e-4)

    def test_assemble_places_parts_by_plan(self):
        blender = find_blender()
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / 'box.glb'
            make_box_glb(source, (1.0, 1.0, 1.0))
            plan = temp / 'plan.json'
            plan.write_text(json.dumps({'parts': [
                {'id': 'a', 'name': 'part_a', 'mesh': str(source),
                 'scale': 1, 'translate': [0, 0, 0], 'rotationZ': 0},
                {'id': 'b', 'name': 'part_b', 'mesh': str(source),
                 'scale': 2, 'translate': [3, 0, 0], 'rotationZ': 0},
            ]}), encoding='utf-8')
            output = temp / 'assembly.glb'
            data = run_blender(blender, ['--mode', 'assemble', '--plan', str(plan),
                                         '--output', str(output)])

            self.assertTrue(data['valid'], data)
            self.assertEqual(len(data['parts']), 2)
            self.assertTrue(output.read_bytes().startswith(b'glTF'))

            measured = run_blender(blender, ['--mode', 'measure', '--inputs', str(output)])
            objects = measured['files'][0]['objects']
            self.assertEqual(len(objects), 2)
            centers = sorted(round((item['min'][0] + item['max'][0]) / 2, 3) for item in objects)
            self.assertEqual(centers, [0.0, 3.0])
            widths = sorted(round(item['max'][0] - item['min'][0], 3) for item in objects)
            self.assertEqual(widths, [1.0, 2.0])

    def test_assemble_snaps_bucket_to_boom_in_xz(self):
        blender = find_blender()
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            source = temp / 'box.glb'
            make_box_glb(source, (1.0, 1.0, 1.0))
            plan = temp / 'plan.json'
            plan.write_text(json.dumps({'parts': [
                {'id': 'boom', 'name': 'boom', 'mesh': str(source),
                 'scale': 1, 'translate': [0, 0, 0], 'rotationZ': 0},
                {'id': 'bucket', 'name': 'bucket', 'mesh': str(source),
                 'scale': 1, 'translate': [1.2, 0, 0], 'rotationZ': 0},
            ], 'snaps': [{'part': 'bucket', 'to': 'boom'}]}), encoding='utf-8')
            output = temp / 'assembly.glb'
            report_path = temp / 'report.json'
            result = subprocess.run([
                blender, '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', str(SCRIPT), '--', '--mode', 'assemble',
                '--plan', str(plan), '--output', str(output), '--report', str(report_path),
            ], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report_path.read_text())
            self.assertTrue(data['valid'], data)
            snap = data['snaps'][0]
            self.assertAlmostEqual(snap['planarGap'], 0.2, places=3)
            self.assertAlmostEqual(snap['moved'][0], -0.21, places=3)
            self.assertAlmostEqual(snap['moved'][1], 0.0, places=3)
            locations = {part['id']: part['location'] for part in data['parts']}
            self.assertAlmostEqual(locations['bucket'][0], 0.99, places=3)

            measured = run_blender(blender, ['--mode', 'measure', '--inputs', str(output)])
            boxes = {item['name']: item for item in measured['files'][0]['objects']}
            self.assertAlmostEqual(boxes['bucket']['min'][0], 0.49, places=2)
            self.assertAlmostEqual(boxes['boom']['max'][0], 0.5, places=3)

    def test_layout_and_assemble_roundtrip(self):
        blender = find_blender()
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'box.glb'
            make_box_glb(source, (1.0, 1.0, 2.0))
            for name in ('a', 'b'):
                (root / (name + '.glb')).write_bytes(source.read_bytes())
            parts = [{'id': 'a', 'name': 'A', 'mesh': 'a.glb'},
                     {'id': 'b', 'name': 'B', 'mesh': 'b.glb'}]
            layout_path = root / 'parts' / 'layout_assemble.json'
            output = root / 'outputs' / 'assembly.glb'

            first = fw_parts.assemble_parts(parts, str(output), str(layout_path), str(root),
                                            assembly_prompt='叠在一起', blender_path=blender,
                                            asset_id='T', node_id='assemble')
            self.assertTrue(first['warnings'])
            self.assertEqual(first['engine'], 'blender')
            layout = fw_parts.load_layout(str(layout_path))
            self.assertEqual([item['mesh'] for item in layout['parts']], ['a.glb', 'b.glb'])
            self.assertEqual(layout['assemblyPrompt'], '叠在一起')
            self.assertAlmostEqual(layout['parts'][1]['translate'][0], 1.52)
            self.assertTrue(Path(output).with_suffix('.report.json').is_file())

            for item in layout['parts']:
                item['translate'] = [0.0, 0.0, 0.0]
                item['ground'] = False
            fw_parts.save_layout(str(layout_path), layout)
            second = fw_parts.assemble_parts(parts, str(output), str(layout_path), str(root),
                                             blender_path=blender, asset_id='T', node_id='assemble')
            self.assertFalse(any('自动' in warning for warning in second['warnings']))
            self.assertTrue(output.read_bytes().startswith(b'glTF'))

            rebuilt = run_blender(blender, ['--mode', 'measure', '--inputs', str(output)])
            original = run_blender(blender, ['--mode', 'measure', '--inputs', str(source)])
            for axis in range(3):
                self.assertAlmostEqual(rebuilt['files'][0]['min'][axis],
                                       original['files'][0]['min'][axis], places=3)
                self.assertAlmostEqual(rebuilt['files'][0]['max'][axis],
                                       original['files'][0]['max'][axis], places=3)

    def test_bridge_queues_validation_and_serves_thumbnail(self):
        blender = bridge.find_blender(force=True)
        if not blender:
            self.skipTest('Blender executable not found')

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            project = temp / 'ue'
            project.mkdir()
            (project / 'Fixture.uproject').write_text('{}')
            old_state = dict(bridge._state)
            old_state_file = bridge.STATE_FILE
            bridge.STATE_FILE = str(temp / 'bridge-state.json')
            bridge._state.clear()
            try:
                self.assertTrue(bridge.open_project(str(project))['ok'])
                server = bridge.Bridge(('127.0.0.1', 0), bridge.BridgeHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    source = temp / 'fixture.glb'
                    make_glb(source)
                    body = {
                        'kind': 'machine',
                        'id': 'TEST_MACHINE',
                        'files': {'mesh': {'path': 'TEST_MACHINE.glb', 'b64': base64.b64encode(source.read_bytes()).decode()}},
                        'meta': {'materials': 5, 'footprint': '2×2'},
                    }
                    request = urllib.request.Request(
                        f'http://127.0.0.1:{server.server_address[1]}/api/export/asset',
                        data=json.dumps(body).encode(),
                        headers={'Content-Type': 'application/json'},
                        method='POST',
                    )
                    with urllib.request.urlopen(request, timeout=10) as response:
                        self.assertTrue(json.loads(response.read())['ok'])

                    record = bridge.load_manifest()['assets']['TEST_MACHINE']
                    self.assertEqual(record.get('meta', {}).get('blender', {}).get('state'), 'queued')
                    deadline = time.time() + 45
                    record = None
                    while time.time() < deadline:
                        record = bridge.load_manifest()['assets']['TEST_MACHINE']
                        state = record.get('meta', {}).get('blender', {}).get('state')
                        if state in ('ready', 'failed', 'unavailable'):
                            break
                        time.sleep(0.2)

                    self.assertEqual(record['meta']['blender']['state'], 'ready', record['meta'].get('blender'))
                    thumbnail_request = urllib.request.Request(
                        f'http://127.0.0.1:{server.server_address[1]}/api/thumbnail/machine/TEST_MACHINE'
                    )
                    with urllib.request.urlopen(thumbnail_request, timeout=10) as response:
                        self.assertEqual(response.headers.get_content_type(), 'image/png')
                        self.assertTrue(response.read().startswith(b'\x89PNG\r\n\x1a\n'))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
            finally:
                bridge.STATE_FILE = old_state_file
                bridge._state.clear()
                bridge._state.update(old_state)


if __name__ == '__main__':
    unittest.main()
