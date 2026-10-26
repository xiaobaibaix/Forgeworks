#!/usr/bin/env python3
import argparse
import json
import os
import sys


def _arguments():
    values = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('inspect', 'decimate'), default='inspect')
    parser.add_argument('--input')
    parser.add_argument('--thumbnail')
    parser.add_argument('--output')
    parser.add_argument('--target-faces', type=int, default=900)
    parser.add_argument('--report', required=True)
    parser.add_argument('--expected-meshes', type=int, default=1)
    parser.add_argument('--expected-materials', type=int, default=5)
    return parser.parse_args(values)


def _write_report(path, report):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False)


def _render_thumbnail(bpy, Vector, objects, bounds, output):
    scene = bpy.context.scene
    center = Vector([(bounds[0][i] + bounds[1][i]) / 2 for i in range(3)])
    dimensions = [bounds[1][i] - bounds[0][i] for i in range(3)]
    scale = max(dimensions)

    camera_data = bpy.data.cameras.new('FW_ThumbnailCamera')
    camera = bpy.data.objects.new('FW_ThumbnailCamera', camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = scale * 2.2
    camera.location = center + Vector((scale * 1.7, -scale * 2.6, scale * 1.8))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = camera

    light_data = bpy.data.lights.new('FW_ThumbnailKey', 'AREA')
    light = bpy.data.objects.new('FW_ThumbnailKey', light_data)
    scene.collection.objects.link(light)
    light_data.energy = 1300
    light_data.shape = 'DISK'
    light_data.size = scale * 1.5
    light.location = center + Vector((scale * 1.2, -scale * 1.6, scale * 2.4))
    light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()

    fill_data = bpy.data.lights.new('FW_ThumbnailFill', 'AREA')
    fill = bpy.data.objects.new('FW_ThumbnailFill', fill_data)
    scene.collection.objects.link(fill)
    fill_data.energy = 500
    fill_data.size = scale * 1.8
    fill.location = center + Vector((-scale * 1.8, scale * 1.5, scale * 0.8))
    fill.rotation_euler = (center - fill.location).to_track_quat('-Z', 'Y').to_euler()

    engine_ids = {item.identifier for item in scene.render.bl_rna.properties['engine'].enum_items}
    engine = next((name for name in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE') if name in engine_ids), None)
    if engine is None:
        raise RuntimeError('当前 Blender 没有可用的 EEVEE 渲染引擎')
    scene.render.engine = engine
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = True
    scene.render.filepath = output
    scene.view_settings.view_transform = 'Standard'
    bpy.ops.render.render(write_still=True)


def _plain(value):
    if hasattr(value, 'to_dict'):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _socket_image(material, input_name):
    """沿连接向上游找第一个图像节点（Base Color / Roughness / Normal 都可能隔几层）。"""
    if not material or not material.node_tree:
        return None
    for node in material.node_tree.nodes:
        if node.type != 'BSDF_PRINCIPLED':
            continue
        socket = node.inputs.get(input_name)
        if socket is None:
            continue
        seen = set()
        stack = [link.from_node for link in socket.links]
        while stack:
            current = stack.pop()
            if current.name in seen:
                continue
            seen.add(current.name)
            if current.type == 'TEX_IMAGE' and current.image:
                return current.image.name
            for item in current.inputs:
                stack.extend(link.from_node for link in item.links)
    return None


def _material_report(material):
    nodes = list(material.node_tree.nodes) if material and material.node_tree else []
    textures = {
        'albedo': _socket_image(material, 'Base Color'),
        'roughness': _socket_image(material, 'Roughness'),
        'normal': _socket_image(material, 'Normal'),
    }
    return {
        'name': material.name if material else None,
        'nodeTypes': sorted({node.type for node in nodes}),
        'textures': textures,
    }


def _inspect(args):
    import bpy
    from mathutils import Vector

    report = {
        'valid': False,
        'meshCount': 0,
        'materialSlots': 0,
        'boundsMeters': [],
        'triangleCount': 0,
        'uvPresent': False,
        'uvLayers': [],
        'imageCount': 0,
        'images': [],
        'materialDetails': [],
        'normalMapSlots': 0,
        'animationCount': 0,
        'forgeworks': {},
        'errors': [],
    }

    if not args.thumbnail:
        report['errors'].append('缺少缩略图输出路径')
        return report
    if not args.input or not os.path.isfile(args.input):
        report['errors'].append('GLB 文件不存在')
        return report

    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=args.input)
        objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
        report['meshCount'] = len(objects)
        report['materialSlots'] = sum(len(obj.material_slots) for obj in objects)
        report['triangleCount'] = sum(len(obj.data.loop_triangles) for obj in objects)

        uv_names = set()
        image_names = set()
        materials = []
        seen_materials = set()
        for obj in objects:
            for layer in obj.data.uv_layers:
                uv_names.add(layer.name)
            for slot in obj.material_slots:
                material = slot.material
                if not material or material.name in seen_materials:
                    if material:
                        seen_materials.add(material.name)
                    continue
                seen_materials.add(material.name)
                detail = _material_report(material)
                materials.append(detail)
                for image in detail['textures'].values():
                    if image:
                        image_names.add(image)
        report['uvLayers'] = sorted(uv_names)
        report['uvPresent'] = bool(uv_names)
        report['images'] = sorted(image_names)
        report['imageCount'] = len(image_names)
        report['materialDetails'] = materials
        report['normalMapSlots'] = sum(1 for item in materials if item['textures'].get('normal'))
        report['animationCount'] = len(bpy.data.actions)
        for obj in objects:
            extra = obj.get('forgeworks') or (obj.data.get('forgeworks') if obj.data else None)
            if extra:
                report['forgeworks'] = _plain(extra)
                break

        if objects:
            corners = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
            lower = [min(point[i] for point in corners) for i in range(3)]
            upper = [max(point[i] for point in corners) for i in range(3)]
            report['boundsMeters'] = [round(upper[i] - lower[i], 6) for i in range(3)]
            report['bottomZ'] = round(lower[2], 6)
            for obj in objects:
                obj.data.calc_loop_triangles()
            report['triangleCount'] = sum(len(obj.data.loop_triangles) for obj in objects)

        if report['meshCount'] != args.expected_meshes:
            report['errors'].append('网格数 %d，预期 %d' % (report['meshCount'], args.expected_meshes))
        if report['materialSlots'] != args.expected_materials:
            report['errors'].append('材质槽数 %d，预期 %d' % (report['materialSlots'], args.expected_materials))
        if len(report['boundsMeters']) != 3 or not all(size > 0 for size in report['boundsMeters']):
            report['errors'].append('包围盒尺寸无效')
        if report.get('bottomZ', 0) < -0.02 or report.get('bottomZ', 0) > 0.02:
            report['errors'].append('模型底部未贴地：%.4fm' % report['bottomZ'])

        if objects:
            _render_thumbnail(bpy, Vector, objects, (lower, upper), args.thumbnail)
        report['valid'] = not report['errors'] and os.path.isfile(args.thumbnail)
        if not os.path.isfile(args.thumbnail):
            report['errors'].append('未生成缩略图')
    except Exception as error:
        report['errors'].append(str(error))

    return report


def _count_triangles(objects):
    for obj in objects:
        obj.data.calc_loop_triangles()
    return sum(len(obj.data.loop_triangles) for obj in objects)


def _decimate(args):
    import bpy

    report = {
        'valid': False,
        'mode': 'decimate',
        'meshCount': 0,
        'trianglesBefore': 0,
        'trianglesAfter': 0,
        'targetFaces': int(args.target_faces or 0),
        'ratio': 0,
        'errors': [],
    }
    if not args.output:
        report['errors'].append('缺少减面输出路径')
        return report
    if not args.input or not os.path.isfile(args.input):
        report['errors'].append('GLB 文件不存在')
        return report

    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=args.input)
        objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
        report['meshCount'] = len(objects)
        if not objects:
            report['errors'].append('模型没有可减面的网格')
            return report

        before = _count_triangles(objects)
        report['trianglesBefore'] = before
        target = max(1, min(int(args.target_faces or 0), before))
        report['targetFaces'] = target
        if before <= target:
            report['errors'].append('当前面数 %d 已不高于目标 %d，无需减面' % (before, target))
            return report

        ratio = target / before
        report['ratio'] = round(ratio, 6)
        for obj in objects:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            modifier = obj.modifiers.new('FW_Decimate', 'DECIMATE')
            modifier.decimate_type = 'COLLAPSE'
            modifier.ratio = max(0.001, min(1.0, ratio))
            modifier.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        report['trianglesAfter'] = _count_triangles(objects)

        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB')
        if not os.path.isfile(args.output):
            report['errors'].append('未生成减面后的 GLB')
        report['valid'] = not report['errors']
    except Exception as error:
        report['errors'].append(str(error))

    return report


def main():
    args = _arguments()
    handlers = {'inspect': _inspect, 'decimate': _decimate}
    try:
        report = handlers[args.mode](args)
    except Exception as error:
        report = {'valid': False, 'errors': [str(error)]}
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get('valid') else 1


if __name__ == '__main__':
    sys.exit(main())
