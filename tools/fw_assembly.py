"""装配数据的纯函数；不依赖 fw_pipeline，避免循环导入。"""

BBOX_DRIFT_LIMIT = 0.01


def assembly_for_node(graph, by_id, node_id):
    """读取上游 assembly 输出；未接线返回 None，接线但未就绪则报错。"""
    edge = next((edge for edge in graph.get('edges') or []
                 if edge.get('to') == node_id and edge.get('in') == 'assembly'), None)
    if not edge:
        return None
    source = (by_id or {}).get(edge.get('from'))
    if not source:
        raise ValueError('ASSEMBLY_MISSING: assembly 上游节点不存在')
    result = source.get('result') or {}
    state = result.get('state')
    if result and state not in ('done', None):
        raise ValueError('ASSEMBLY_MISSING: 上游装配未就绪（%s）' % (state or '未运行'))
    assembly = (result.get('output') or {}).get('assembly')
    if not isinstance(assembly, dict):
        raise ValueError('ASSEMBLY_MISSING: 上游节点没有 assembly 结果')
    return assembly


def retarget_assembly(assembly, mesh_path):
    """把装配里的网格路径换到新 GLB，端口与 mate 记录原样保留。"""
    mesh_path = str(mesh_path)
    parts = [dict(part, meshPath=mesh_path) for part in assembly.get('parts') or []]
    updated = dict(assembly)
    updated['meshPath'] = mesh_path
    updated['parts'] = parts
    return updated


def bbox_drift(before, after):
    """三个轴上包围盒尺寸的最大相对变化；缺数据时返回 0。"""
    if not (isinstance(before, (list, tuple)) and isinstance(after, (list, tuple))
            and len(before) == len(after) == 3):
        return 0.0
    drift = 0.0
    for old, new in zip(before, after):
        try:
            old, new = float(old or 0), float(new or 0)
        except (TypeError, ValueError):
            continue
        if old <= 0:
            continue
        drift = max(drift, abs(new - old) / old)
    return drift
