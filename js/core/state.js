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
  (target.items||[]).forEach(it=>{
    if(typeof it.icon !== 'string') it.icon = '';                    // '' = 使用自动生成图标
    if(typeof it.mesh !== 'string') it.mesh = '';                    // UE 静态网格路径
    if(typeof it.mat !== 'string') it.mat = '';                      // 材质路径
    if(typeof it.visual !== 'string') it.visual = '';                // 图标形态覆盖
    if(!it.modelStatus) it.modelStatus = defaultModelStatus(it.visual || it.type);
  });
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
function saveState(){
  try{ localStorage.setItem(LS_KEY, JSON.stringify(S)); toast('已保存到浏览器本地'); }
  catch(e){ toast('保存失败：'+e.message); }
}
function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(t._t); t._t = setTimeout(()=>t.classList.remove('on'), 2200);
}
