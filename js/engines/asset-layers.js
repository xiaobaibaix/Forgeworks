/* Forgeworks · js/engines/asset-layers.js
   ============================================================
   资产图层：把「几何 / 材质 / UV / LOD / 碰撞体 / 动画 / 元数据」
   统一成可开关、可持久化的检查层，供 3D 预览、流水线节点、GLB 导出共用。

   图层只影响预览与标注，不改变资产的真实数据：
     白模 / 各贴图通道 / 线框 / UV 棋盘 / 碰撞盒 / LOD 预览
   关掉的图层不会被写进导出的 GLB（导出始终是全量资产）。
   ============================================================ */

const FW_LAYER_DEFAULTS = {
  clay: false,             // 白模：关掉配色与全部贴图
  albedo: true,
  roughness: true,
  normal: true,
  wireframe: false,
  uv: false,               // UV 棋盘
  collision: false,
  particles: true,
  animations: true,
  lod: 0,                  // 0 = 全量，1 = 轻量，2 = 最省
  collisionHeight: null,   // null = 跟随几何高度
};

/** 读取某台机器保存的图层状态（缺省项回落到默认值） */
function fwLayersOf(machine){
  const saved = (machine && machine.ui3d && machine.ui3d.layers) || {};
  const layers = Object.assign({}, FW_LAYER_DEFAULTS, saved);
  layers.lod = Math.max(0, Math.min(2, Number(layers.lod) || 0));
  if(layers.collisionHeight != null && !(Number(layers.collisionHeight) > 0)) layers.collisionHeight = null;
  return layers;
}

function fwSaveLayers(machine, layers){
  if(!machine) return layers;
  machine.ui3d = machine.ui3d || {};
  machine.ui3d.layers = Object.assign({}, layers);
  if(typeof saveState === 'function') saveState();
  return layers;
}

/** 写入单个图层并持久化；返回归一化后的完整状态 */
function fwSetLayer(machine, key, value){
  if(!(key in FW_LAYER_DEFAULTS)) return fwLayersOf(machine);
  const layers = fwLayersOf(machine);
  layers[key] = value;
  return fwSaveLayers(machine, fwLayersOf({ui3d:{layers:layers}}));
}

/* ---------- 占地 / 碰撞体 ---------- */

function fwParseFootprint(fp){
  const values = String(fp || '1×1').split(/[×xX]/).map(function(value){ return parseFloat(value) || 1; });
  return [values[0], values[1] || values[0]];
}

/** 由 footprint 推出盒碰撞；高度默认取几何高度 */
function fwCollisionBox(machine, height){
  const fp = fwParseFootprint(machine && machine.footprint);
  const own = (machine && machine.ui3d && machine.ui3d.layers) || {};
  const chosen = height != null ? Number(height)
    : (own.collisionHeight != null ? Number(own.collisionHeight) : null);
  const autoHeight = (typeof buildMachineParts === 'function')
    ? buildMachineParts(machine, currentStyleId()).H : 1;
  const h = (chosen > 0) ? chosen : autoHeight;
  return {
    type: 'box',
    w: Math.round(fp[0] * 1000) / 1000,
    d: Math.round(fp[1] * 1000) / 1000,
    h: Math.round(h * 1000) / 1000,
  };
}

/* ---------- UV 棋盘 ---------- */

let _fwUvChecker = null;

/** 8×8 棋盘 + 坐标轴标记，用来检查 UV 方向、接缝和重复率 */
function fwUvCheckerTexture(){
  if(_fwUvChecker) return _fwUvChecker;
  const size = 512, cells = 8, cell = size / cells;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  for(let y = 0; y < cells; y++){
    for(let x = 0; x < cells; x++){
      const odd = (x + y) % 2 === 1;
      ctx.fillStyle = odd ? '#d8d5cd' : '#8f8c85';
      ctx.fillRect(x * cell, y * cell, cell, cell);
    }
  }
  ctx.lineWidth = 2;
  ctx.strokeStyle = 'rgba(40,40,40,.35)';
  for(let i = 0; i <= cells; i++){
    ctx.beginPath(); ctx.moveTo(i * cell, 0); ctx.lineTo(i * cell, size); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, i * cell); ctx.lineTo(size, i * cell); ctx.stroke();
  }
  ctx.fillStyle = '#e8523d';
  ctx.fillRect(0, 0, cell, cell);
  ctx.fillStyle = '#2f7fd6';
  ctx.fillRect(0, size - cell, cell, cell);
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 26px monospace';
  ctx.fillText('U', cell * 0.3, size - cell * 0.28);
  ctx.fillText('V', cell * 0.3, cell * 0.78);

  _fwUvChecker = fwMakeTexture(canvas, false);
  _fwUvChecker.name = 'uv_checker';
  _fwUvChecker.userData.mimeType = 'image/png';
  return _fwUvChecker;
}

/* ---------- LOD 预算 ---------- */

function fwPartTriangles(p){
  switch(p.kind){
    case 'box': return 12;
    case 'cyl': case 'cone': return (p.seg || 20) * 4;
    case 'prism': return (p.sides || 6) * 4;
    case 'sphere': return (p.seg || 20) * (p.segH || 14) * 2 - (p.seg || 20) * 2;
    case 'dome': return (p.seg || 20) * (p.segH || 10) * 2 - (p.seg || 20);
    case 'torus': return (p.segT || 8) * (p.seg || 28) * 2;
    case 'torusV': return (p.segT || 8) * (p.seg || 24) * 2;
    case 'pipe': return (p.seg || 12) * 4;
    default: return 12;
  }
}

/**
 * 单个图元降到指定 LOD 细分：只改面数，部件集合不变。
 * 方块没有可减的面，低模档位维持 12 面。
 */
function fwLodPart(p, level){
  if(!(level > 0)) return p;
  const low = level >= 2;
  const radial = function(base, min){
    return Math.max(min, Math.round(base * (low ? 0.3 : 0.55)));
  };
  const q = Object.assign({}, p);
  switch(p.kind){
    case 'cyl': case 'cone':
      q.seg = radial(p.seg || 20, low ? 4 : 6);
      break;
    case 'prism':
      q.sides = radial(p.sides || 6, 3);
      break;
    case 'sphere':
      q.seg = low ? 8 : 12; q.segH = low ? 6 : 8;
      break;
    case 'dome':
      q.seg = low ? 8 : 12; q.segH = low ? 4 : 6;
      break;
    case 'torus': case 'torusV':
      q.seg = low ? 8 : 12; q.segT = low ? 4 : 6;
      break;
    case 'pipe':
      q.seg = low ? 6 : 8;
      break;
  }
  return q;
}

/**
 * 派生三档 LOD：保持全部部件，只按档位降低图元细分（面数）。
 * 这是 UE 自动 LOD / decimate 的预览近似，导出时仍以 L0 为准。
 */
function fwLodPlan(machine, presetKey){
  const geo = buildMachineParts(machine, presetKey);
  const total = geo.parts.reduce(function(sum, p){ return sum + fwPartTriangles(p); }, 0);
  const levels = [0, 1, 2].map(function(level){
    const triangles = geo.parts.reduce(function(sum, p){
      return sum + fwPartTriangles(fwLodPart(p, level));
    }, 0);
    return { level: level, parts: geo.parts.length, triangles: triangles };
  });
  return { parts: geo.parts.length, totalTriangles: total, geometry: geo, levels: levels };
}

/* ---------- 资产方面汇总 ---------- */

/** 面向 UI / 流水线 / GLB extras 的统一资产描述 */
function fwAssetAspects(machine, presetKey){
  if(!machine) return null;
  const plan = fwLodPlan(machine, presetKey);
  const geo = plan.geometry;
  const box = fwCollisionBox(machine);
  const animParts = geo.parts.filter(function(part){ return !!part.anim; });
  const kinds = {};
  animParts.forEach(function(part){ kinds[part.anim.kind] = true; });
  const tex = (typeof FW_TEX !== 'undefined') ? FW_TEX.items : {};
  let albedo = 0, roughness = 0, normal = 0;
  Object.keys(tex).forEach(function(key){
    if(tex[key].map) albedo++;
    if(tex[key].roughness) roughness++;
    if(tex[key].normal) normal++;
  });
  return {
    geometry: {
      parts: plan.parts,
      triangles: plan.totalTriangles,
      footprint: [geo.W, geo.D],
      height: Math.round(geo.H * 1000) / 1000,
      pivot: 'bottom-center',
    },
    material: {
      slots: new Set(geo.parts.map(function(part){ return part.role; })).size,
      palette: true,
      textures: { albedo: albedo, roughness: roughness, normal: normal },
    },
    uv: {
      present: true,
      channels: ['TEXCOORD_0'],
      source: 'primitive',
      note: '程序化图元自带 UV；需要更精细的排布时在 Blender 重展',
    },
    lod: {
      levels: plan.levels.map(function(level){
        return { level: level.level, parts: level.parts, triangles: level.triangles };
      }),
      source: 'segment decimation',
    },
    collision: {
      type: 'box',
      size: [box.w, box.h, box.d],
      pivot: 'bottom-center',
    },
    animation: {
      parts: animParts.length,
      kinds: Object.keys(kinds),
      mode: 'ue-rebuild',
    },
    metadata: {
      id: machine.id,
      name: machine.name,
      category: machine.cat,
      footprint: machine.footprint,
      tier: machine.tier,
      formats: ['UE DataTable CSV', 'GLB userData JSON'],
    },
  };
}

/** 图层状态的一行摘要（预览面板顶部） */
function fwLayerSummary(layers){
  const off = [];
  if(layers.clay) off.push('白模');
  if(!layers.albedo) off.push('无基础色');
  if(!layers.roughness) off.push('无粗糙度');
  if(!layers.normal) off.push('无法线');
  if(layers.wireframe) off.push('线框');
  if(layers.uv) off.push('UV 棋盘');
  if(layers.collision) off.push('碰撞盒');
  off.push('LOD L' + (layers.lod || 0));
  return off.join(' · ');
}
