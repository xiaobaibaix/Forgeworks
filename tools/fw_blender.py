#!/usr/bin/env python3
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fw_spec


def _arguments():
    values = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('inspect', 'decimate', 'measure', 'assemble',
                                          'cut', 'fit', 'mate'),
                        default='inspect')
    parser.add_argument('--input')
    parser.add_argument('--inputs', nargs='+')
    parser.add_argument('--plan')
    parser.add_argument('--out-dir')
    parser.add_argument('--parts', type=int, default=2)
    parser.add_argument('--axis', choices=('x', 'y', 'z'), default='z')
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


def _bounds_meters(objects):
    from mathutils import Vector
    corners = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not corners:
        return []
    lower = [min(point[i] for point in corners) for i in range(3)]
    upper = [max(point[i] for point in corners) for i in range(3)]
    return [round(upper[i] - lower[i], 6) for i in range(3)]


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
        report['boundsBefore'] = _bounds_meters(objects)
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
        report['boundsAfter'] = _bounds_meters(objects)

        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB')
        if not os.path.isfile(args.output):
            report['errors'].append('未生成减面后的 GLB')
        report['valid'] = not report['errors']
    except Exception as error:
        report['errors'].append(str(error))

    return report


def _mesh_objects():
    import bpy
    return [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']


def _object_bounds(obj):
    from mathutils import Vector
    matrix = obj.matrix_world
    points = [matrix @ Vector(vertex.co) for vertex in obj.data.vertices]
    if not points:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return ([min(point[i] for point in points) for i in range(3)],
            [max(point[i] for point in points) for i in range(3)])


def _bounds(objects):
    boxes = [_object_bounds(obj) for obj in objects]
    return ([min(box[0][i] for box in boxes) for i in range(3)],
            [max(box[1][i] for box in boxes) for i in range(3)])


def _measure(args):
    import bpy

    report = {'valid': True, 'mode': 'measure', 'files': [], 'errors': []}
    paths = args.inputs or ([args.input] if args.input else [])
    if not paths:
        report['errors'].append('缺少待测量文件')
        return report
    for path in paths:
        try:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=path)
            objects = _mesh_objects()
            if not objects:
                raise RuntimeError('文件里没有网格')
            lower, upper = _bounds(objects)
            details = []
            for obj in objects:
                obj_lower, obj_upper = _object_bounds(obj)
                details.append({'name': obj.name,
                                'min': [round(value, 6) for value in obj_lower],
                                'max': [round(value, 6) for value in obj_upper]})
            report['files'].append({
                'path': path,
                'min': [round(value, 6) for value in lower],
                'max': [round(value, 6) for value in upper],
                'meshCount': len(objects),
                'triangles': _count_triangles(objects),
                'objects': details,
            })
        except Exception as error:
            report['errors'].append('%s：%s' % (os.path.basename(path), error))
    report['valid'] = not report['errors']
    return report


def _assemble(args):
    import bpy
    from math import radians

    report = {'valid': False, 'mode': 'assemble', 'parts': [], 'errors': []}
    if not args.plan or not os.path.isfile(args.plan):
        report['errors'].append('缺少装配计划')
        return report
    if not args.output:
        report['errors'].append('缺少装配输出路径')
        return report
    try:
        with open(args.plan, encoding='utf-8') as stream:
            plan = json.load(stream)
        parts = plan.get('parts') if isinstance(plan, dict) else None
        if not isinstance(parts, list) or not parts:
            raise RuntimeError('装配计划没有部件')

        bpy.ops.wm.read_factory_settings(use_empty=True)
        for index, item in enumerate(parts):
            path = item.get('mesh')
            if not isinstance(path, str) or not os.path.isfile(path):
                raise RuntimeError('部件文件不存在：%s' % path)
            before = {obj.name for obj in bpy.context.scene.objects}
            bpy.ops.import_scene.gltf(filepath=path)
            imported = [obj for obj in bpy.context.scene.objects
                        if obj.name not in before and obj.type == 'MESH']
            if not imported:
                raise RuntimeError('部件 %s 没有网格' % (item.get('id') or index))
            bpy.ops.object.select_all(action='DESELECT')
            for obj in imported:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = imported[0]
            if len(imported) > 1:
                bpy.ops.object.join()
            joined = bpy.context.view_layer.objects.active
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            joined.name = item.get('name') or item.get('id') or ('part_%d' % index)
            joined.data.name = joined.name
            joined['partId'] = item.get('id') or joined.name
            scale = float(item.get('scale') or 1.0)
            joined.scale = (scale, scale, scale)
            joined.rotation_euler = (0.0, 0.0, radians(float(item.get('rotationZ') or 0)))
            translate = item.get('translate') or [0, 0, 0]
            joined.location = tuple(float(value) for value in translate)

        # 挂接件（铲斗）按动臂真实网格补位：包围盒近似会在减面后留下可见缝。
        report['snaps'] = []
        snaps = plan.get('snaps') if isinstance(plan, dict) else None
        if isinstance(snaps, list):
            from mathutils.kdtree import KDTree

            bpy.context.view_layer.update()
            objects_by_id = {obj.get('partId'): obj for obj in bpy.context.scene.objects
                             if obj.type == 'MESH'}
            for snap in snaps:
                if not isinstance(snap, dict):
                    continue
                source = objects_by_id.get(snap.get('part'))
                target = objects_by_id.get(snap.get('to'))
                if source is None or target is None or source is target:
                    continue
                tree = KDTree(len(target.data.vertices))
                for index, vertex in enumerate(target.data.vertices):
                    tree.insert(target.matrix_world @ vertex.co, index)
                tree.balance()
                best = None
                for vertex in source.data.vertices:
                    world = source.matrix_world @ vertex.co
                    point, index, distance = tree.find(world)
                    if best is None or distance < best[0]:
                        best = (distance, point - world)
                if best is None:
                    continue
                gap, delta = best
                planar = (delta.x ** 2 + delta.z ** 2) ** 0.5
                record = {'part': snap.get('part'), 'to': snap.get('to'),
                          'gap': round(gap, 4), 'planarGap': round(planar, 4)}
                if 0.003 <= planar <= 0.5:
                    overlap = 0.01
                    factor = (planar + overlap) / planar
                    source.location.x += delta.x * factor
                    source.location.z += delta.z * factor
                    record['moved'] = [round(delta.x * factor, 4),
                                       round(delta.z * factor, 4)]
                else:
                    record['moved'] = [0.0, 0.0]
                report['snaps'].append(record)
            bpy.context.view_layer.update()

        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        try:
            bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB',
                                      export_extras=True)
        except TypeError:
            bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB')
        for obj in _mesh_objects():
            lower, upper = _object_bounds(obj)
            obj.data.calc_loop_triangles()
            report['parts'].append({
                'id': obj.get('partId') or obj.name,
                'name': obj.name,
                'min': [round(value, 6) for value in lower],
                'max': [round(value, 6) for value in upper],
                'location': [round(value, 6) for value in obj.location],
                'triangles': len(obj.data.loop_triangles),
            })
        if not os.path.isfile(args.output):
            report['errors'].append('未生成装配 GLB')
    except Exception as error:
        report['errors'].append(str(error))
    report['valid'] = not report['errors']
    return report


def _cut(args):
    import bpy

    report = {'valid': False, 'mode': 'cut', 'files': [], 'errors': []}
    if not args.input or not os.path.isfile(args.input):
        report['errors'].append('GLB 文件不存在')
        return report
    if not args.out_dir:
        report['errors'].append('缺少输出目录')
        return report
    count = max(1, int(args.parts or 1))
    axis = {'x': 0, 'y': 1, 'z': 2}[args.axis]
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=args.input)
        meshes = _mesh_objects()
        if not meshes:
            raise RuntimeError('模型没有网格')
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        if len(meshes) > 1:
            bpy.ops.object.join()
        source = bpy.context.view_layer.objects.active
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        lower, upper = _object_bounds(source)
        size = [upper[i] - lower[i] for i in range(3)]
        if size[axis] <= 1e-6:
            raise RuntimeError('该轴向没有厚度，无法切分')

        os.makedirs(args.out_dir, exist_ok=True)
        import bmesh

        step = size[axis] / count
        # 切面留一点重叠，避免相邻件在装配后出现可见缝隙
        epsilon = max(size[axis] * 0.001, 1e-4)
        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        for index in range(count):
            start = lower[axis] + step * index - (epsilon if index else 0.0)
            end = lower[axis] + step * (index + 1) + (epsilon if index < count - 1 else 0.0)
            center = [(lower[i] + upper[i]) / 2 for i in range(3)]
            # 布尔求交在非流形网格上会产出越界面，改用平面切分
            bm = bmesh.new()
            bm.from_mesh(source.data)
            plane = list(center)
            plane[axis] = start
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                                   dist=1e-6, plane_co=plane, plane_no=normal,
                                   clear_inner=True)
            plane[axis] = end
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                                   dist=1e-6, plane_co=plane, plane_no=normal,
                                   clear_outer=True)
            mesh = bpy.data.meshes.new('FW_Cut_%d' % index)
            for material in source.data.materials:
                mesh.materials.append(material)
            bm.to_mesh(mesh)
            bm.free()
            mesh.update()
            if not mesh.polygons:
                report['errors'].append('切片 %d 为空' % index)
                bpy.data.meshes.remove(mesh)
                continue

            piece = bpy.data.objects.new('FW_Cut_%d' % index, mesh)
            bpy.context.scene.collection.objects.link(piece)
            path = os.path.join(args.out_dir, 'part_%d.glb' % index)
            bpy.ops.object.select_all(action='DESELECT')
            piece.select_set(True)
            bpy.context.view_layer.objects.active = piece
            bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True)
            part_lower, part_upper = _object_bounds(piece)
            mesh.calc_loop_triangles()
            report['files'].append({
                'index': index,
                'file': path,
                'min': [round(value, 6) for value in part_lower],
                'max': [round(value, 6) for value in part_upper],
                'triangles': len(mesh.loop_triangles),
            })
            bpy.data.objects.remove(piece, do_unlink=True)
            bpy.data.meshes.remove(mesh)
    except Exception as error:
        report['errors'].append(str(error))
    report['valid'] = not report['errors'] and bool(report['files'])
    return report


def _fit(args):
    import bpy
    from mathutils import Matrix

    report = {'valid': True, 'mode': 'fit', 'errors': []}
    try:
        if not args.plan:
            raise ValueError('fit 模式需要 --plan')
        with open(args.plan, encoding='utf-8') as stream:
            plan = json.load(stream)
        source = str(plan.get('input') or args.input or '')
        output = str(plan.get('output') or args.output or '')
        if not source or not os.path.isfile(source):
            raise ValueError('fit 输入 GLB 不存在')
        if not output:
            raise ValueError('fit 缺少输出路径')
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=source)
        objects = _mesh_objects()
        if not objects:
            raise ValueError('fit 输入没有网格')
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        if len(objects) > 1:
            bpy.ops.object.join()
        target = bpy.context.view_layer.objects.active
        bpy.context.view_layer.update()
        lower, upper = _object_bounds(target)
        measured = [upper[index] - lower[index] for index in range(3)]
        target_size = plan.get('targetSizeM')
        if target_size is None:
            raise ValueError('fit 缺少 targetSizeM')
        fit = fw_spec.choose_orientation(
            measured, target_size, plan.get('forward', '+X'),
            plan.get('fitMode', 'uniform'))
        rotation = fit['matrix']
        scale = fit.get('scalePerAxis') or [fit['scale']] * 3
        rotation_matrix = Matrix((
            (rotation[0][0], rotation[0][1], rotation[0][2], 0.0),
            (rotation[1][0], rotation[1][1], rotation[1][2], 0.0),
            (rotation[2][0], rotation[2][1], rotation[2][2], 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        scale_matrix = Matrix((
            (scale[0], 0.0, 0.0, 0.0),
            (0.0, scale[1], 0.0, 0.0),
            (0.0, 0.0, scale[2], 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        target.matrix_world = scale_matrix @ rotation_matrix @ target.matrix_world
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        if plan.get('ground'):
            bpy.context.view_layer.update()
            lower, upper = _object_bounds(target)
            target.location.z -= lower[2]
            bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
        bpy.context.view_layer.update()
        lower, upper = _object_bounds(target)
        ports = fw_spec.resolve_ports(plan.get('ports') or [],
                                      {'min': lower, 'max': upper}, rotation)
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=output, export_format='GLB')
        if not os.path.isfile(output):
            raise RuntimeError('fit 未生成 GLB')
        report['fit'] = {
            'mode': plan.get('fitMode', 'uniform'),
            'scale': round(float(fit['scale']), 9),
            'scalePerAxis': [round(float(value), 9) for value in fit['scalePerAxis']],
            'aspectError': round(float(fit['aspectError']), 9),
            'rotationDeg': fit['rotationDeg'],
            'measuredBbox': {'min': [round(float(value), 6) for value in lower],
                             'max': [round(float(value), 6) for value in upper]},
            'grounded': bool(plan.get('ground')),
            'ambiguous': bool(fit.get('ambiguous')),
        }
        report['ports'] = ports
        report['triangles'] = _count_triangles([target])
    except Exception as error:
        report['valid'] = False
        report['errors'].append(str(error))
    return report


def _mate(args):
    import bpy
    from mathutils import Matrix, Quaternion, Vector

    report = {'valid': False, 'mode': 'mate', 'errors': []}
    if not args.plan or not os.path.isfile(args.plan):
        report['errors'].append('缺少装配计划')
        return report
    try:
        with open(args.plan, encoding='utf-8') as stream:
            plan = json.load(stream)
        source_a = str(plan.get('a') or '')
        source_b = str(plan.get('b') or '')
        output = str(plan.get('output') or args.output or '')
        if not source_a or not os.path.isfile(source_a):
            raise RuntimeError('a 侧装配 GLB 不存在：%s' % source_a)
        if not source_b or not os.path.isfile(source_b):
            raise RuntimeError('b 侧装配 GLB 不存在：%s' % source_b)
        if not output:
            raise RuntimeError('mate 缺少输出路径')
        rotation = plan.get('rotation') or [0, 0, 0, 1]
        translation = plan.get('translation') or [0, 0, 0]
        offset = float(plan.get('offsetM') or 0.0)

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=source_a)
        objects_a = _mesh_objects()
        known = {obj.name for obj in bpy.context.scene.objects}
        bpy.ops.import_scene.gltf(filepath=source_b)
        objects_b = [obj for obj in bpy.context.scene.objects
                     if obj.name not in known and obj.type == 'MESH']
        if not objects_a:
            raise RuntimeError('a 侧 GLB 没有网格')
        if not objects_b:
            raise RuntimeError('b 侧 GLB 没有网格')

        quat = Quaternion((rotation[3], rotation[0], rotation[1], rotation[2]))
        move = Matrix.Translation(Vector(translation)) @ quat.to_matrix().to_4x4()
        for obj in objects_b:
            obj.matrix_world = move @ obj.matrix_world
        bpy.context.view_layer.update()
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects_a + objects_b:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects_a[0]
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.context.view_layer.update()

        frame_a = plan.get('frameA') or {}
        frame_b = plan.get('frameB') or {}
        axis_a = Vector(frame_a.get('axis') or [1, 0, 0]).normalized()
        pos_b = quat @ Vector(frame_b.get('pos') or [0, 0, 0]) + Vector(translation)
        axis_b = (quat @ Vector(frame_b.get('axis') or [1, 0, 0])).normalized()
        target = Vector(frame_a.get('pos') or [0, 0, 0]) + axis_a * offset
        gap = (target - pos_b).dot(axis_a)
        applied = (Vector(frame_a.get('pos') or [0, 0, 0]) - pos_b).dot(axis_a)
        axis_error = math.degrees(math.acos(max(-1.0, min(1.0, (-axis_b).dot(axis_a)))))

        ground_shift = [0.0, 0.0, 0.0]
        if plan.get('ground'):
            lower, _upper = _bounds(objects_a + objects_b)
            ground_shift = [0.0, 0.0, -lower[2]]
            for obj in objects_a + objects_b:
                obj.location.z += ground_shift[2]
            bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
            bpy.context.view_layer.update()

        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        try:
            bpy.ops.export_scene.gltf(filepath=output, export_format='GLB',
                                      export_extras=True)
        except TypeError:
            bpy.ops.export_scene.gltf(filepath=output, export_format='GLB')
        if not os.path.isfile(output):
            raise RuntimeError('mate 未生成装配 GLB')

        lower, upper = _bounds(objects_a + objects_b)
        report.update({
            'gapM': round(gap, 6),
            'appliedOffsetM': round(applied, 6),
            'axisErrorDeg': round(axis_error, 4),
            'groundShift': [round(value, 6) for value in ground_shift],
            'warnings': [],
            'bounds': {'min': [round(value, 6) for value in lower],
                       'max': [round(value, 6) for value in upper]},
            'objects': [obj.name for obj in objects_a + objects_b],
            'parts': [],
            'triangles': _count_triangles(objects_a + objects_b),
        })
        for obj in objects_a + objects_b:
            obj_lower, obj_upper = _object_bounds(obj)
            report['parts'].append({'name': obj.name,
                                    'min': [round(value, 6) for value in obj_lower],
                                    'max': [round(value, 6) for value in obj_upper]})
        if axis_error > 5:
            report['errors'].append('MATE_AXIS_ERROR: 端口轴向偏差 %.1f°' % axis_error)
        elif axis_error > 1:
            report['warnings'].append('MATE_AXIS_ERROR: 端口轴向偏差 %.1f°' % axis_error)
        if abs(applied + offset) > 0.0005:
            report['warnings'].append('MATE_OFFSET_DRIFT: 落位偏差 %.1f mm'
                                      % ((applied + offset) * 1000))
        report['valid'] = not report['errors']
    except Exception as error:
        report['errors'].append(str(error))
        report['valid'] = False
    return report


def main():
    args = _arguments()
    handlers = {'inspect': _inspect, 'decimate': _decimate,
                'measure': _measure, 'assemble': _assemble, 'cut': _cut,
                'fit': _fit, 'mate': _mate}
    try:
        report = handlers[args.mode](args)
    except Exception as error:
        report = {'valid': False, 'errors': [str(error)]}
    _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get('valid') else 1


if __name__ == '__main__':
    sys.exit(main())
