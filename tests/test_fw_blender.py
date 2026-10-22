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
sys.argv = bridge_args


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
