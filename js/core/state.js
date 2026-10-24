/* Forgeworks · js/core/state.js */
/* ---------- 状态 ---------- */
let S = loadState();
let cur = 'elements';
let modalState = null;

/**
 * 资源字段补全。
 * 老数据（或从 JSON 导入的数据）可能没有 icon / mesh / modelStatus，
 * 这里补齐默认值，避免各视图到处判空。
 */
function normalizeAssets(target){
  ['elements','items','machines','recipes','techs'].forEach(k=>{
    if(!Array.isArray(target[k])) target[k]=[];   // MCP 可能只写入部分集合
  });
  (target.elements||[]).forEach(el=>{
    if(typeof el.icon !== 'string') el.icon = '';
    if(typeof el.iconSource !== 'string') el.iconSource = '';
    if(!el.generated || typeof el.generated !== 'object') el.generated = {};
    delete el.model;                                                  // 元素不生成 3D 模型
  });
  (target.items||[]).forEach(it=>{
    if(typeof it.icon !== 'string') it.icon = '';
    if(typeof it.mesh !== 'string') it.mesh = '';
    if(typeof it.mat !== 'string') it.mat = '';
    if(typeof it.visual !== 'string') it.visual = '';
    if(!it.modelStatus) it.modelStatus = defaultModelStatus(it.visual || it.type);
    if(typeof it.iconSource !== 'string') it.iconSource = '';
    if(!it.generated || typeof it.generated !== 'object') it.generated = {};
    it.model = normalizeAIModel(it.model);
  });
  (target.machines||[]).forEach(m=>{
    if(typeof m.icon !== 'string') m.icon = '';
    if(typeof m.iconSource !== 'string') m.iconSource = '';
    if(!m.generated || typeof m.generated !== 'object') m.generated = {};
    m.model = normalizeAIModel(m.model);
  });
}

/** 只保留 AI 模型；旧数据或程序化模型返回 null */
function normalizeAIModel(model){
  if(!model || model.source !== 'ai') return null;
  return {
    source: 'ai',
    provider: typeof model.provider === 'string' ? model.provider : '',
    file: typeof model.file === 'string' ? model.file : '',
    taskId: typeof model.taskId === 'string' ? model.taskId : '',
    nodeId: typeof model.nodeId === 'string' ? model.nodeId : '',
    generatedAt: typeof model.generatedAt === 'string' ? model.generatedAt : '',
    triangles: Number.isFinite(Number(model.triangles)) ? Number(model.triangles) : 0,
    autoFit: model.autoFit !== false,
    transform: normalizeModelTransform(model.transform),
  };
}

/** 整体变换补全；ratio 轴缺省为 1，位移/旋转缺省为 0 */
function normalizeModelTransform(transform){
  const t = transform || {};
  const axis = (value, fallback)=>{
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  };
  const p = t.position || {}, r = t.rotation || {}, s = t.scale || {};
  return {
    position: {x:axis(p.x,0), y:axis(p.y,0), z:axis(p.z,0)},
    rotation: {x:axis(r.x,0), y:axis(r.y,0), z:axis(r.z,0)},
    scale:    {x:axis(s.x,1), y:axis(s.y,1), z:axis(s.z,1)},
  };
}
// 按类型推断默认模型需求
function defaultModelStatus(type){
  if(type==='fluid') return 'none';        // 流体不需要网格
  if(type==='mega') return 'needed';       // 宏构必须专门建模
  if(type==='module') return 'needed';
  if(type==='part') return 'needed';
  return 'primitive';                      // 矿石/精矿/锭/材料/副产物可用基础几何体
}

function loadState(){
  let s = null;
  try{
    const raw = localStorage.getItem(LS_KEY);
    if(raw){ const p = JSON.parse(raw); if(p && p.items && p.recipes) s = p; }
  }catch(e){ console.warn('load fail', e); }
  if(!s) s = JSON.parse(JSON.stringify(SEED));
  normalizeAssets(s);
  return s;
}
function saveLocalState(){
  try{ localStorage.setItem(LS_KEY, JSON.stringify(S)); return true; }
  catch(e){ console.warn('save local fail', e); return false; }
}
function saveState(){
  if(!saveLocalState()){ toast('保存失败：浏览器本地存储不可用'); return; }
  const toProject = typeof syncScheduleContentSave === 'function' && syncScheduleContentSave();
  toast(toProject ? '已保存到项目' : '已保存到浏览器本地');
}
function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(t._t); t._t = setTimeout(()=>t.classList.remove('on'), 2200);
}
