const PIPELINE = {assetId:null, kind:'machine', graph:null, providers:{}, selected:null, busy:false, source:'local', archive:null, zoom:1, pan:{x:0,y:0}, returnTo:null, remote:{}, pollers:{}, partsRunning:{}, applyQueue:{}, applyStatus:{}, applyErrors:{}, applyNodes:{}};
const PIPELINE_STORE_PREFIX = 'fw.pipeline.';
const PIPELINE_LAST_ASSET_KEY = 'fw.pipeline.lastAsset';

const PIPELINE_NODE_LABELS = {
  prompt:'描述词', textToImage:'概念图生成', imageTo3D:'图生 3D', decimate:'减面',
  partSpec:'分件规划', partImage:'逐件效果图', partModel:'逐件模型', assemble:'装配',
  styleApply:'风格对齐', uv:'UV 展开', lod:'LOD 分级', collision:'碰撞体',
  animation:'动画', metadata:'元数据', validate:'质量门禁', manualEdit:'人工精修',
  variant:'变体', export:'导出', imageExport:'图标导出'
};

const PIPELINE_LOCAL_STAGES = ['uv', 'lod', 'collision', 'animation', 'metadata'];

const PIPELINE_NODE_WIDTH = 230;
const PIPELINE_PORT_BASE = 46;
const PIPELINE_PORT_STEP = 18;
const PIPELINE_PORT_SIZE = 12;
const PIPELINE_ZOOM_MIN = 0.45;
const PIPELINE_ZOOM_MAX = 1.8;

const PIPELINE_PORTS = {
  prompt:{out:['text']}, textToImage:{in:['text'],out:['image']}, imageTo3D:{in:['image'],out:['mesh']},
  decimate:{in:['mesh'],out:['mesh']},
  partSpec:{in:['text','mesh'],out:['contract']}, partImage:{in:['text','contract'],out:['contract']},
  partModel:{in:['contract'],out:['contract']}, assemble:{in:['contract'],out:['mesh']},
  styleApply:{in:['mesh'],out:['mesh']},
  uv:{in:['mesh'],out:['mesh']}, lod:{in:['mesh'],out:['mesh']}, collision:{in:['mesh'],out:['mesh']},
  animation:{in:['mesh'],out:['mesh']}, metadata:{in:['mesh'],out:['mesh']},
  validate:{in:['mesh'],out:['report']}, manualEdit:{in:['mesh'],out:['mesh']},
  variant:{in:['mesh'],out:['mesh']}, export:{in:['mesh','report']}, imageExport:{in:['image']}
};

function pipelinePorts(type, side){
  return (PIPELINE_PORTS[type] || {})[side] || [];
}

function pipelinePortTop(type, side, port){
  const ports = pipelinePorts(type, side);
  return PIPELINE_PORT_BASE + Math.max(0, ports.indexOf(port)) * PIPELINE_PORT_STEP;
}

function pipelinePortCenterY(type, side, port){
  return pipelinePortTop(type, side, port) + PIPELINE_PORT_SIZE / 2;
}

async function pipelineApi(route, body){
  const response = await fetch('/api/' + route, body === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  const result = await response.json();
  if(!response.ok || !result.ok) throw new Error(result.error || ('HTTP ' + response.status));
  return result;
}

function pipelineEscape(value){
  return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function pipelineBridgeReady(){
  return !!(SYNC.online && SYNC.status && SYNC.status.project);
}

function pipelineLocalRead(assetId){
  try{
    const raw = localStorage.getItem(PIPELINE_STORE_PREFIX + assetId);
    if(!raw) return null;
    const graph = JSON.parse(raw);
    return graph && Array.isArray(graph.nodes) && Array.isArray(graph.edges) ? graph : null;
  }catch(_){ return null; }
}

function pipelineLocalWrite(assetId, graph){
  try{ localStorage.setItem(PIPELINE_STORE_PREFIX + assetId, JSON.stringify(graph)); return true; }
  catch(_){ return false; }
}

function pipelineRememberLastAsset(assetId, kind){
  try{ localStorage.setItem(PIPELINE_LAST_ASSET_KEY, JSON.stringify({id:assetId, kind})); }catch(_){}
}

function pipelineLastAsset(){
  try{
    const raw = localStorage.getItem(PIPELINE_LAST_ASSET_KEY);
    const saved = raw ? JSON.parse(raw) : null;
    return saved && saved.id ? saved : null;
  }catch(_){ return null; }
}

function pipelineHasArchive(assetId){
  const graph = pipelineLocalRead(assetId);
  return !!(graph && graph.nodes && graph.nodes.length);
}

function pipelineBlankGraph(assetId){
  return {schemaVersion:1, assetId, revision:0, nodes:[], edges:[], updatedAt:null};
}

function pipelineBump(graph){
  graph.revision = (Number(graph.revision) || 0) + 1;
  graph.updatedAt = new Date().toISOString();
  return graph;
}

function pipelineStarterGraph(assetId, template){
  let nodes = [
    {id:'prompt', type:'prompt', x:60, y:100, params:{text:''}},
    {id:'image', type:'textToImage', x:300, y:100, params:{provider:'tripo'}},
    {id:'model', type:'imageTo3D', x:540, y:100, params:{provider:'tripo', texture:false}},
    {id:'style', type:'styleApply', x:780, y:100, params:{}},
    {id:'uv', type:'uv', x:1020, y:100, params:{mode:'primitive'}},
    {id:'lod', type:'lod', x:1260, y:100, params:{levels:3}},
    {id:'collision', type:'collision', x:1500, y:100, params:{type:'box'}},
    {id:'animation', type:'animation', x:1740, y:100, params:{mode:'ue-rebuild'}},
    {id:'metadata', type:'metadata', x:1980, y:100, params:{formats:['csv','json']}},
    {id:'validate', type:'validate', x:2220, y:100, params:{maxTriangles:20000}},
    {id:'export', type:'export', x:2460, y:100, params:{}},
  ];
  let edges = [
    {from:'prompt', out:'text', to:'image', in:'text'},
    {from:'image', out:'image', to:'model', in:'image'},
    {from:'model', out:'mesh', to:'style', in:'mesh'},
    {from:'style', out:'mesh', to:'uv', in:'mesh'},
    {from:'uv', out:'mesh', to:'lod', in:'mesh'},
    {from:'lod', out:'mesh', to:'collision', in:'mesh'},
    {from:'collision', out:'mesh', to:'animation', in:'mesh'},
    {from:'animation', out:'mesh', to:'metadata', in:'mesh'},
    {from:'metadata', out:'mesh', to:'validate', in:'mesh'},
    {from:'validate', out:'report', to:'export', in:'report'},
    {from:'metadata', out:'mesh', to:'export', in:'mesh'},
  ];
  if(template === 'icon'){
    nodes = [nodes[0], nodes[1], {id:'imageExport', type:'imageExport', x:600, y:100, params:{}}];
    edges = [
      {from:'prompt', out:'text', to:'image', in:'text'},
      {from:'image', out:'image', to:'imageExport', in:'image'},
    ];
  }else if(template === 'item'){
    nodes[2].params.faceLimit = 10000;
    nodes[2].params.smartLowPoly = true;
    nodes[2].params.texture = false;
  }else if(template === 'parts'){
    nodes = [
      nodes[0], nodes[1], nodes[2],
      {id:'partSpec', type:'partSpec', x:780, y:100, params:{parts:3, axis:'x'}},
      {id:'partImage', type:'partImage', x:1020, y:100, params:{provider:'tripo', size:'1K', outputFormat:'png'}},
      {id:'partModel', type:'partModel', x:1260, y:100, params:{provider:'tripo', texture:false, faceLimit:3000}},
      {id:'assemble', type:'assemble', x:1500, y:100, params:{fit:'contain', overlap:0.02}},
    ];
    [['style','styleApply',{}],['uv','uv',{mode:'primitive'}],['lod','lod',{levels:3}],
     ['collision','collision',{type:'box'}],['animation','animation',{mode:'ue-rebuild'}],
     ['metadata','metadata',{formats:['csv','json']}],['validate','validate',{maxTriangles:20000}],
     ['export','export',{}]].forEach(([id,type,params],index)=>{
      nodes.push({id, type, x:1740 + index * 240, y:100, params});
    });
    edges = [
      {from:'prompt', out:'text', to:'image', in:'text'},
      {from:'image', out:'image', to:'model', in:'image'},
      {from:'model', out:'mesh', to:'partSpec', in:'mesh'},
      {from:'prompt', out:'text', to:'partSpec', in:'text'},
      {from:'partSpec', out:'contract', to:'partImage', in:'contract'},
      {from:'partImage', out:'contract', to:'partModel', in:'contract'},
      {from:'partModel', out:'contract', to:'assemble', in:'contract'},
      {from:'assemble', out:'mesh', to:'style', in:'mesh'},
      {from:'style', out:'mesh', to:'uv', in:'mesh'},
      {from:'uv', out:'mesh', to:'lod', in:'mesh'},
      {from:'lod', out:'mesh', to:'collision', in:'mesh'},
      {from:'collision', out:'mesh', to:'animation', in:'mesh'},
      {from:'animation', out:'mesh', to:'metadata', in:'mesh'},
      {from:'metadata', out:'mesh', to:'validate', in:'mesh'},
      {from:'validate', out:'report', to:'export', in:'report'},
      {from:'metadata', out:'mesh', to:'export', in:'mesh'},
    ];
  }else{
    template = 'machine';
  }
  return {schemaVersion:1, assetId, template, revision:0, nodes, edges};
}

function pipelineTopoOrder(graph){
  const ids = graph.nodes.map(node=>node.id);
  const indegree = new Map(ids.map(id=>[id, 0]));
  const outgoing = new Map(ids.map(id=>[id, []]));
  graph.edges.forEach(edge=>{
    if(!indegree.has(edge.from) || !indegree.has(edge.to)) return;
    indegree.set(edge.to, indegree.get(edge.to) + 1);
    outgoing.get(edge.from).push(edge.to);
  });
  const queue = ids.filter(id=>indegree.get(id) === 0);
  const order = [];
  while(queue.length){
    const id = queue.shift();
    order.push(id);
    outgoing.get(id).forEach(next=>{
      indegree.set(next, indegree.get(next) - 1);
      if(indegree.get(next) === 0) queue.push(next);
    });
  }
  ids.forEach(id=>{ if(!order.includes(id)) order.push(id); });
  return order;
}

function pipelineGraphTime(graph){
  const value = graph && graph.updatedAt ? Date.parse(graph.updatedAt) : 0;
  return Number.isFinite(value) ? value : 0;
}

/** 远端空白图不能覆盖本地存档；两边都有内容时取更新时间较新的一份 */
function pipelinePickGraph(remote, local){
  const remoteNodes = remote && Array.isArray(remote.nodes) ? remote.nodes.length : 0;
  const localNodes = local && Array.isArray(local.nodes) ? local.nodes.length : 0;
  if(!remoteNodes) return localNodes ? local : remote;
  if(!localNodes) return remote;
  return pipelineGraphTime(local) > pipelineGraphTime(remote) ? local : remote;
}

async function pipelineLoad(assetId){
  PIPELINE.assetId = assetId;
  const target = pipelineAssetTarget(assetId);
  PIPELINE.kind = target ? target.kind : 'machine';
  pipelineRememberLastAsset(assetId, PIPELINE.kind);
  PIPELINE.providers = {};
  PIPELINE.source = 'local';
  PIPELINE.archive = null;
  const local = pipelineLocalRead(assetId);
  let remote = null;
  if(pipelineBridgeReady()){
    try{
      const result = await pipelineApi('pipeline/graph/' + encodeURIComponent(assetId) + '?kind=' + encodeURIComponent(PIPELINE.kind));
      remote = result.graph;
      PIPELINE.archive = result.archive || null;
    }catch(_){ /* 读不到就退回浏览器本地图 */ }
    try{
      const providers = await pipelineApi('providers');
      PIPELINE.providers = providers.providers || {};
    }catch(_){ PIPELINE.providers = {}; }
  }
  PIPELINE.graph = pipelinePickGraph(remote, local) || pipelineBlankGraph(assetId);
  PIPELINE.source = remote && PIPELINE.graph === remote ? 'bridge' : 'local';
  if(PIPELINE.source === 'bridge' && PIPELINE.graph.nodes.length) pipelineLocalWrite(assetId, PIPELINE.graph);
  const localWins = !!(local && local.nodes.length)
    && !(remote && remote.nodes.length && pipelineGraphTime(remote) >= pipelineGraphTime(local));
  if(pipelineBridgeReady() && localWins){
    try{
      const saved = await pipelineApi('pipeline/graph/save', {assetId, kind:PIPELINE.kind, graph:PIPELINE.graph});
      PIPELINE.graph = saved.graph;
      PIPELINE.source = 'bridge';
      PIPELINE.archive = saved.archive || PIPELINE.archive;
    }catch(_){ /* 迁移失败时继续用本地存档 */ }
  }
  PIPELINE.selected = PIPELINE.graph.nodes[0] && PIPELINE.graph.nodes[0].id || null;
}

function pipelineEnter(assetId, returnTo){
  PIPELINE.assetId = assetId;
  PIPELINE.graph = null;
  PIPELINE.selected = null;
  PIPELINE.returnTo = returnTo || null;
  PIPELINE.zoom = 1;
  PIPELINE.pan.x = 0;
  PIPELINE.pan.y = 0;
  cur = 'pipeline';
  render();
  syncHash('pipeline');
}

function pipelineReturnLabel(){
  const target = PIPELINE.returnTo;
  if(!target) return '';
  if(target.modal === '3d') return '← 返回 3D 预览';
  if(target.modal === 'editor') return '← 返回资产编辑';
  return '← 返回资源页';
}

function pipelineReturn(){
  const target = PIPELINE.returnTo;
  if(!target) return;
  PIPELINE.returnTo = null;
  cur = target.view || 'assets';
  render();
  syncHash(cur);
  if(target.modal === '3d') open3DViewer(target.assetId);
  else if(target.modal === 'editor') openEditor(target.coll || 'items', target.assetId);
}

function pipelineOpenAsset(assetId, kind){
  const coll = kind === 'machine' ? 'machines' : (kind === 'item' ? 'items' : 'elements');
  const targetView = kind === 'machine' ? 'machines' : 'assets';
  cur = targetView;
  render();
  syncHash(targetView);
  openEditor(coll, assetId);
}

async function pipelineCreateTemplate(template){
  if(pipelineBridgeReady()){
    try{
      const result = await pipelineApi('pipeline/graph/template', {assetId:PIPELINE.assetId, kind:PIPELINE.kind, template});
      PIPELINE.graph = result.graph;
      PIPELINE.archive = result.archive || PIPELINE.archive;
      PIPELINE.source = 'bridge';
      PIPELINE.selected = 'prompt';
      renderPipelineView();
      return;
    }catch(error){ toast('Bridge 建模板失败，改用本地模板：' + error.message); }
  }
  PIPELINE.graph = pipelineBump(pipelineStarterGraph(PIPELINE.assetId, template));
  PIPELINE.source = 'local';
  if(!pipelineLocalWrite(PIPELINE.assetId, PIPELINE.graph)) toast('浏览器本地存储不可用，改动不会被保存');
  PIPELINE.selected = 'prompt';
  renderPipelineView();
}

async function pipelineSave(options){
  const quiet = !!(options && options.quiet);
  if(pipelineBridgeReady()){
    try{
      const result = await pipelineApi('pipeline/graph/save', {assetId:PIPELINE.assetId, kind:PIPELINE.kind, graph:PIPELINE.graph});
      PIPELINE.graph = result.graph;
      PIPELINE.archive = result.archive || PIPELINE.archive;
      PIPELINE.source = 'bridge';
      if(quiet){ pipelinePaintChrome(); return; }
      renderPipelineView();
      return;
    }catch(error){ toast('Bridge 保存失败，改存浏览器本地：' + error.message); }
  }
  pipelineBump(PIPELINE.graph);
  PIPELINE.source = 'local';
  if(!pipelineLocalWrite(PIPELINE.assetId, PIPELINE.graph)) toast('浏览器本地存储不可用，改动不会被保存');
  if(quiet){ pipelinePaintChrome(); return; }
  renderPipelineView();
}

function pipelineAddNode(type, x, y){
  if(!PIPELINE.graph || !PIPELINE_NODE_LABELS[type]) return;
  let index = 1;
  while(PIPELINE.graph.nodes.some(node=>node.id===type+'_'+index)) index++;
  const id = type + '_' + index;
  const nodeX = Number.isFinite(x) ? x - PIPELINE_NODE_WIDTH / 2 : 100 + (index % 4) * 280;
  const nodeY = Number.isFinite(y) ? y - 70 : 100 + Math.floor(index / 4) * 190;
  const node = {id, type, x:nodeX, y:nodeY, params:{}};
  PIPELINE.graph.nodes.push(node);
  PIPELINE.selected = id;
  const canvas = document.querySelector('.pipeline-canvas');
  if(!canvas){ pipelineSave().catch(error => toast(error.message)); return; }
  canvas.insertAdjacentHTML('beforeend', pipelineNodeCard(node));
  const card = canvas.lastElementChild;
  document.querySelectorAll('.pipeline-node').forEach(item=>item.classList.toggle('selected', item.dataset.node === id));
  canvas.style.width = Math.max(parseFloat(canvas.style.width) || 1700, nodeX + 260) + 'px';
  canvas.style.height = Math.max(parseFloat(canvas.style.height) || 650, nodeY + 210) + 'px';
  pipelineWireCard(card);
  pipelineApplyZoom();
  pipelineSave({quiet:true}).catch(error => toast(error.message));
}

function pipelineReachable(fromId, targetId){
  const seen = new Set();
  const stack = [fromId];
  while(stack.length){
    const id = stack.pop();
    if(id === targetId) return true;
    if(seen.has(id)) continue;
    seen.add(id);
    PIPELINE.graph.edges.forEach(edge => { if(edge.from === id) stack.push(edge.to); });
  }
  return false;
}

function pipelineConnect(sourceId, targetId, inPort){
  const source = PIPELINE.graph.nodes.find(node => node.id === sourceId);
  const target = PIPELINE.graph.nodes.find(node => node.id === targetId);
  if(!source || !target || sourceId === targetId) return false;
  const out = pipelinePorts(source.type, 'out');
  const input = pipelinePorts(target.type, 'in');
  const common = inPort && out.includes(inPort) && input.includes(inPort)
    ? inPort
    : out.find(port => input.includes(port));
  if(!common){toast('两个节点没有兼容的端口');return false;}
  if(pipelineReachable(targetId, sourceId)){toast('这条连线会形成循环');return false;}
  PIPELINE.graph.edges = PIPELINE.graph.edges.filter(edge => !(edge.to === targetId && edge.in === common));
  PIPELINE.graph.edges.push({from:sourceId,out:common,to:targetId,in:common});
  pipelineSave({quiet:true}).catch(error => toast(error.message));
  return true;
}

function pipelineArrange(){
  const byId=new Map(PIPELINE.graph.nodes.map(node=>[node.id,node]));
  const depth=new Map(), visit=(id,seen=new Set())=>{
    if(depth.has(id))return depth.get(id);
    if(seen.has(id))return 0;
    seen.add(id);
    const parents=PIPELINE.graph.edges.filter(edge=>edge.to===id).map(edge=>edge.from);
    const value=parents.length?1+Math.max(...parents.map(parent=>visit(parent,seen))):0;
    depth.set(id,value);return value;
  };
  const rows={};
  PIPELINE.graph.nodes.forEach(node=>{const level=visit(node.id);(rows[level]=rows[level]||[]).push(node);});
  Object.entries(rows).forEach(([level,nodes])=>nodes.forEach((node,index)=>{node.x=60+Number(level)*290;node.y=60+index*205;}));
  pipelineSave().catch(error=>toast(error.message));
}

function pipelineRemoveEdge(index){
  PIPELINE.graph.edges.splice(index,1);
  pipelineSave({quiet:true}).catch(error=>toast(error.message));
}

function pipelineRemoveNode(nodeId){
  const node=PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  if(!node) return;
  const state=node.result&&node.result.providerTask&&node.result.providerTask.state;
  if(state==='queued'||state==='running'){toast('Provider 任务尚在运行，当前不能取消或删除这个节点');return;}
  PIPELINE.graph.nodes=PIPELINE.graph.nodes.filter(item=>item.id!==nodeId);
  PIPELINE.graph.edges=PIPELINE.graph.edges.filter(edge=>edge.from!==nodeId&&edge.to!==nodeId);
  if(PIPELINE.selected===nodeId) PIPELINE.selected=null;
  const card=[...document.querySelectorAll('.pipeline-node')].find(item=>item.dataset.node===nodeId);
  if(!card){ pipelineSave().catch(error=>toast(error.message)); return; }
  card.remove();
  pipelineSave({quiet:true}).catch(error=>toast(error.message));
}

document.addEventListener('keydown', event=>{
  if(event.key!=='Delete' && event.key!=='Backspace') return;
  if(!PIPELINE.graph || !PIPELINE.selected) return;
  if(!PIPELINE.graph.nodes.some(node=>node.id===PIPELINE.selected)) return;
  if(!document.querySelector('.pipeline-canvas')) return;
  if(typeof modalState!=='undefined' && modalState) return;
  if(event.target && event.target.closest && event.target.closest('input,textarea,select,[contenteditable="true"]')) return;
  event.preventDefault();
  pipelineRemoveNode(PIPELINE.selected);
});

function pipelineDragCard(card){
  const header=card.querySelector('header');
  header.onpointerdown=event=>{
    if(event.button!==0)return;
    event.preventDefault();
    const node=PIPELINE.graph.nodes.find(item=>item.id===card.dataset.node);
    const startX=event.clientX,startY=event.clientY,baseX=Number(node.x)||0,baseY=Number(node.y)||0;
    card.classList.add('dragging');
    header.setPointerCapture(event.pointerId);
    const move=next=>{
      node.x=baseX+(next.clientX-startX)/PIPELINE.zoom;
      node.y=baseY+(next.clientY-startY)/PIPELINE.zoom;
      card.style.left=node.x+'px';card.style.top=node.y+'px';pipelinePaintEdges();
    };
    const end=()=>{card.classList.remove('dragging');header.removeEventListener('pointermove',move);header.removeEventListener('pointerup',end);header.removeEventListener('pointercancel',end);pipelineSave({quiet:true}).catch(error=>toast(error.message));};
    header.addEventListener('pointermove',move);header.addEventListener('pointerup',end,{once:true});header.addEventListener('pointercancel',end,{once:true});
  };
}

function pipelineEdgePath(edge){
  const from = PIPELINE.graph.nodes.find(node => node.id === edge.from);
  const to = PIPELINE.graph.nodes.find(node => node.id === edge.to);
  if(!from || !to) return '';
  const x1 = (Number(from.x) || 0) + PIPELINE_NODE_WIDTH;
  const y1 = (Number(from.y) || 0) + pipelinePortCenterY(from.type, 'out', edge.out);
  const x2 = Number(to.x) || 0;
  const y2 = (Number(to.y) || 0) + pipelinePortCenterY(to.type, 'in', edge.in);
  return `M${x1} ${y1} C${x1+70} ${y1},${x2-70} ${y2},${x2} ${y2}`;
}

function pipelineEdgeSvg(){
  const active = new Set(PIPELINE.graph.nodes.filter(node => pipelineNodeBusy(node)).map(node => node.id));
  return PIPELINE.graph.edges.map(edge => {
    const hot = active.has(edge.from) || active.has(edge.to);
    return `<path${hot ? ' class="pipeline-edge-active"' : ''} d="${pipelineEdgePath(edge)}"/>`;
  }).join('');
}

function pipelinePaintEdges(){
  const svg = document.querySelector('.pipeline-canvas>svg');
  if(!svg) return;
  svg.innerHTML = pipelineEdgeSvg();
}

function pipelinePaintMeta(){
  const meta = document.querySelector('#pipelineMeta');
  if(!meta || !PIPELINE.graph) return;
  const assets = (SYNC.manifest && SYNC.manifest.assets) || {};
  const manifest = assets[PIPELINE.assetId] && assets[PIPELINE.assetId].state || '未导出';
  const archive = PIPELINE.source === 'bridge' && PIPELINE.archive
    ? PIPELINE.archive.path + (PIPELINE.archive.legacy ? '（旧存档，下次保存迁入）' : '')
    : '浏览器本地';
  meta.textContent = ` · graph rev ${PIPELINE.graph.revision||0} · ${PIPELINE.graph.nodes.length} 节点 / ${PIPELINE.graph.edges.length} 连线 · 存档 ${archive} · manifest ${manifest}`;
}

function pipelinePaintEdgeList(){
  const list = document.querySelector('.pipeline-edge-list');
  if(!list || !PIPELINE.graph) return;
  list.innerHTML = PIPELINE.graph.edges.map((edge,index)=>`<span>${pipelineEscape(edge.from)}.${pipelineEscape(edge.out)} → ${pipelineEscape(edge.to)}.${pipelineEscape(edge.in)} <button data-remove-edge="${index}">断开</button></span>`).join('');
  list.querySelectorAll('[data-remove-edge]').forEach(button=>button.onclick=()=>pipelineRemoveEdge(Number(button.dataset.removeEdge)));
}

/** 静默保存只重画连线和统计，不重建 DOM —— 重建会丢滚动位置并造成闪烁 */
function pipelinePaintChrome(){
  pipelinePaintEdges();
  pipelinePaintMeta();
  pipelinePaintEdgeList();
}

function pipelineApplyZoom(){
  const canvas = document.querySelector('.pipeline-canvas');
  if(!canvas) return;
  const {x, y} = PIPELINE.pan;
  const zoom = PIPELINE.zoom;
  // 用 zoom 而非 transform: scale，放大时浏览器按新尺寸重排重绘，文字不会发虚
  canvas.style.zoom = zoom;
  canvas.style.transform = `translate(${x / zoom}px, ${y / zoom}px)`;
  const scroll = document.querySelector('.pipeline-scroll');
  if(scroll) scroll.style.backgroundPosition = `${x}px ${y}px`;
  const label = document.getElementById('pipelineZoomReset');
  if(label) label.textContent = Math.round(PIPELINE.zoom * 100) + '%';
}

function pipelineCanvasPoint(clientX, clientY){
  const canvas = document.querySelector('.pipeline-canvas');
  if(!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  return {x:(clientX - rect.left) / PIPELINE.zoom, y:(clientY - rect.top) / PIPELINE.zoom};
}

function pipelineWheel(event){
  const scroll = event.currentTarget;
  const canvas = document.querySelector('.pipeline-canvas');
  if(!canvas || event.target.closest('textarea,input,select')) return;
  event.preventDefault();
  const next = Math.min(PIPELINE_ZOOM_MAX, Math.max(PIPELINE_ZOOM_MIN, PIPELINE.zoom * Math.exp(-event.deltaY * 0.0015)));
  if(next === PIPELINE.zoom) return;
  const base = scroll.getBoundingClientRect();
  const cursorX = event.clientX - base.left;
  const cursorY = event.clientY - base.top;
  PIPELINE.pan.x = cursorX - (cursorX - PIPELINE.pan.x) / PIPELINE.zoom * next;
  PIPELINE.pan.y = cursorY - (cursorY - PIPELINE.pan.y) / PIPELINE.zoom * next;
  PIPELINE.zoom = next;
  pipelineApplyZoom();
}

function pipelinePanCanvas(scroll){
  scroll.addEventListener('contextmenu', event => event.preventDefault());
  scroll.addEventListener('wheel', pipelineWheel, {passive:false});
  scroll.addEventListener('pointerdown', event => {
    if(event.button !== 2) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const baseX = PIPELINE.pan.x;
    const baseY = PIPELINE.pan.y;
    scroll.classList.add('panning');
    scroll.setPointerCapture(event.pointerId);
    const move = next => {
      PIPELINE.pan.x = baseX + (next.clientX - startX);
      PIPELINE.pan.y = baseY + (next.clientY - startY);
      pipelineApplyZoom();
    };
    const end = () => {
      scroll.classList.remove('panning');
      scroll.removeEventListener('pointermove', move);
      scroll.removeEventListener('pointerup', end);
      scroll.removeEventListener('pointercancel', end);
    };
    scroll.addEventListener('pointermove', move);
    scroll.addEventListener('pointerup', end);
    scroll.addEventListener('pointercancel', end);
  });
}

function pipelineStartPaletteDrag(button, event){
  const type = button.dataset.add;
  const scroll = document.querySelector('.pipeline-scroll');
  if(!PIPELINE.graph || !PIPELINE_NODE_LABELS[type] || !scroll) return;
  const ghost = document.createElement('div');
  ghost.className = 'pipeline-ghost';
  ghost.textContent = PIPELINE_NODE_LABELS[type];
  document.body.appendChild(ghost);
  const startX = event.clientX;
  const startY = event.clientY;
  let moved = false;
  const place = next => { ghost.style.left = next.clientX + 'px'; ghost.style.top = next.clientY + 'px'; };
  const inside = next => {
    const rect = scroll.getBoundingClientRect();
    return next.clientX >= rect.left && next.clientX <= rect.right && next.clientY >= rect.top && next.clientY <= rect.bottom;
  };
  place(event);
  const move = next => {
    if(!moved && Math.hypot(next.clientX - startX, next.clientY - startY) > 5) moved = true;
    place(next);
    ghost.classList.toggle('over', inside(next));
  };
  const finish = next => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', finish);
    window.removeEventListener('pointercancel', finish);
    ghost.remove();
    if(moved && inside(next)){
      const point = pipelineCanvasPoint(next.clientX, next.clientY);
      if(point) pipelineAddNode(type, point.x, point.y);
      return;
    }
    if(!moved && !inside(next)) pipelineAddNode(type);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', finish);
  window.addEventListener('pointercancel', finish);
}

function pipelineWirePorts(view){
  view.querySelectorAll('[data-out-node]').forEach(port => {
    port.addEventListener('pointerdown', event => {
      if(event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      pipelineStartWire(port, event);
    });
  });
}

function pipelineStartWire(port, event){
  const svg = document.querySelector('.pipeline-canvas>svg');
  const canvas = svg && svg.closest('.pipeline-canvas');
  if(!svg || !canvas) return;
  const sourceId = port.dataset.outNode;
  const outPort = port.dataset.outPort;
  const card = port.closest('[data-node]');
  const origin = port.getBoundingClientRect();
  const base = canvas.getBoundingClientRect();
  const startX = (origin.left + origin.width / 2 - base.left) / PIPELINE.zoom;
  const startY = (origin.top + origin.height / 2 - base.top) / PIPELINE.zoom;

  const temp = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  temp.setAttribute('class', 'pipeline-wire-temp');
  svg.appendChild(temp);

  const targets = Array.from(document.querySelectorAll('[data-in-node]'))
    .filter(item => item.dataset.inNode !== sourceId && item.dataset.inPort === outPort);
  targets.forEach(item => item.classList.add('compatible'));

  const cursor = next => ({x:(next.clientX - base.left) / PIPELINE.zoom, y:(next.clientY - base.top) / PIPELINE.zoom});
  const draw = to => {
    temp.setAttribute('d', `M${startX} ${startY} C${startX+70} ${startY},${to.x-70} ${to.y},${to.x} ${to.y}`);
  };
  draw(cursor(event));

  const move = next => {
    draw(cursor(next));
    const hit = document.elementFromPoint(next.clientX, next.clientY);
    const target = hit && hit.closest('[data-in-node]');
    targets.forEach(item => item.classList.toggle('compatible-hover', !!target && item === target));
  };

  const finish = next => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', finish);
    window.removeEventListener('pointercancel', finish);
    temp.remove();
    targets.forEach(item => item.classList.remove('compatible', 'compatible-hover'));
    document.removeEventListener('keydown', cancel, true);
    const hit = document.elementFromPoint(next.clientX, next.clientY);
    const inPort = hit && hit.closest('[data-in-node]');
    if(inPort && inPort.dataset.inPort === outPort && inPort.dataset.inNode !== sourceId){
      pipelineConnect(sourceId, inPort.dataset.inNode, inPort.dataset.inPort);
      return;
    }
    const node = hit && hit.closest('[data-node]');
    if(node && node !== card) pipelineConnect(sourceId, node.dataset.node);
  };

  const cancel = keyEvent => {
    if(keyEvent.key !== 'Escape') return;
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', finish);
    window.removeEventListener('pointercancel', finish);
    temp.remove();
    targets.forEach(item => item.classList.remove('compatible', 'compatible-hover'));
    document.removeEventListener('keydown', cancel, true);
  };

  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', finish);
  window.addEventListener('pointercancel', finish);
  document.addEventListener('keydown', cancel, true);
}

function pipelineAssetTarget(assetId){
  if(typeof S === 'undefined') return null;
  const id = assetId || PIPELINE.assetId;
  const machine = (S.machines || []).find(item => item.id === id);
  if(machine) return {kind:'machine', machine};
  const item = (S.items || []).find(value => value.id === id);
  if(item) return {kind:'item', item};
  const element = (S.elements || []).find(value => value.id === id);
  if(element) return {kind:'element', element};
  return null;
}

/** UV/LOD/碰撞/动画/元数据不依赖 Provider，直接由资产图层引擎推导 */
function pipelineDeriveStage(node){
  const target = pipelineAssetTarget();
  if(!target) return {ok:false, error:'资产不在当前项目里，无法本地推导'};
  if(target.kind !== 'machine') return {ok:false, error:'资产图层目前只对机器资产生效'};
  if(typeof fwAssetAspects !== 'function') return {ok:false, error:'资产图层引擎未加载'};
  const aspects = fwAssetAspects(target.machine);
  if(!aspects) return {ok:false, error:'无法推导资产图层'};
  const output = aspects[node.type];
  if(!output) return {ok:false, error:'该阶段没有可输出的数据'};
  return {ok:true, output};
}

function pipelineDeriveLocalStages(){
  (PIPELINE.graph ? PIPELINE.graph.nodes : []).forEach(node => {
    if(!PIPELINE_LOCAL_STAGES.includes(node.type)) return;
    const derived = pipelineDeriveStage(node);
    node.result = node.result || {};
    if(derived.ok){
      node.result.state = 'done';
      node.result.output = derived.output;
      node.result.source = 'forgeworks-ui';
      node.result.updatedAt = new Date().toISOString();
      delete node.result.error;
    }else{
      node.result.state = 'blocked';
      node.result.error = derived.error;
      delete node.result.source;
    }
  });
}

function pipelineStageSummary(node){
  const output = node.result && node.result.output;
  if(!output) return '';
  if(node.type === 'uv') return (output.channels || []).join(',');
  if(node.type === 'lod') return (output.levels || []).map(level => 'L' + level.level + ' ' + level.triangles + ' 面').join(' / ');
  if(node.type === 'collision') return (output.size || []).join('×') + ' m';
  if(node.type === 'animation') return output.parts + ' 件' + (output.kinds && output.kinds.length ? ' · ' + output.kinds.join('、') : '');
  if(node.type === 'metadata') return (output.formats || []).join(' / ');
  if(node.type === 'decimate' && output.trianglesBefore != null && output.trianglesAfter != null){
    return output.trianglesBefore + ' → ' + output.trianglesAfter + ' 面';
  }
  if(node.type === 'assemble' && output.parts != null){
    return output.parts + ' 件' + (output.triangles != null ? ' · ' + output.triangles + ' 面' : '');
  }
  return '';
}

/** 减面结果没有 providerTask，用节点输出拼一个可复用的任务标识。 */
function pipelineDecimateTaskId(node, output){
  const faces = output && output.targetFaces != null ? output.targetFaces : '';
  const after = output && output.trianglesAfter != null ? output.trianglesAfter : '';
  return 'decimate:' + node.id + ':' + faces + ':' + after;
}

function pipelineApplyTaskFor(node){
  if(!node) return null;
  if(node.type === 'decimate'){
    const output = node.result && node.result.state === 'done' ? node.result.output : null;
    if(!output || !output.meshPath) return null;
    return {
      state:'success', provider:'blender',
      taskId:pipelineDecimateTaskId(node, output),
      output:{modelPath:output.meshPath},
    };
  }
  if(node.type === 'assemble'){
    const output = node.result && node.result.state === 'done' ? node.result.output : null;
    if(!output || !output.meshPath) return null;
    return {
      state:'success', provider:'blender',
      taskId:'assemble:' + node.id + ':' + (output.triangles != null ? output.triangles : ''),
      output:{modelPath:output.meshPath},
    };
  }
  return node.result && node.result.providerTask || null;
}

function pipelineRunLocal(nodeId, through){
  const graph = PIPELINE.graph;
  const order = pipelineTopoOrder(graph);
  if(nodeId && !order.includes(nodeId)){ toast('目标节点不存在'); return; }
  const run = !nodeId ? order : (through ? order.slice(0, order.indexOf(nodeId) + 1) : [nodeId]);
  run.forEach(id=>{
    const node = graph.nodes.find(item=>item.id === id);
    if(!node) return;
    node.result = node.result || {};
    if(PIPELINE_LOCAL_STAGES.includes(node.type)){
      const derived = pipelineDeriveStage(node);
      if(derived.ok){
        node.result.state = 'done';
        node.result.output = derived.output;
        node.result.source = 'forgeworks-ui';
        node.result.updatedAt = new Date().toISOString();
        delete node.result.error;
      }else{
        node.result.state = 'blocked';
        node.result.error = derived.error;
        delete node.result.source;
      }
    }else if(node.type === 'prompt'){
      node.result.state = 'done';
      node.result.updatedAt = new Date().toISOString();
      node.result.output = {text:String((node.params && node.params.text) || '')};
      delete node.result.error;
    }else if(node.type === 'textToImage' || node.type === 'imageTo3D'){
      const task = node.result.providerTask || {};
      if(task.state === 'success'){ node.result.state = 'done'; delete node.result.error; }
      else if(task.state === 'queued' || task.state === 'running'){ node.result.state = task.state; }
      else{
        node.result.state = 'blocked';
        node.result.error = '远程生成未执行：离线状态无法提交 Provider 任务';
      }
    }else if(node.type === 'partImage' || node.type === 'partModel'){
      node.result.state = 'blocked';
      node.result.error = '逐件生成需要 Bridge + Provider 在线，逐个部件提交';
    }else if(node.type === 'partSpec' || node.type === 'assemble'){
      node.result.state = 'blocked';
      node.result.error = node.type === 'partSpec' ? '分件规划需要 Bridge 与 Blender' : '装配需要 Bridge 与 Blender';
    }else{
      node.result.state = 'blocked';
      node.result.error = '该处理器需要 Bridge 在线执行；当前只完成本地描述词步骤';
    }
  });
  pipelineBump(graph);
  PIPELINE.source = 'local';
  if(!pipelineLocalWrite(PIPELINE.assetId, graph)) toast('浏览器本地存储不可用，运行结果不会被保存');
  const blocked = graph.nodes.filter(node => node.result && node.result.state === 'blocked').length;
  toast(blocked ? '本地步骤已执行；远程生成需 Bridge + Provider' : '流水线步骤已执行');
  renderPipelineView();
}

function pipelineParts(node){
  const parts = node && node.result && node.result.parts;
  if(!parts || typeof parts !== 'object') return [];
  return Object.entries(parts).map(([id, entry])=>Object.assign({id}, entry || {}));
}

function pipelinePartEntry(nodeId, partId){
  const node = PIPELINE.graph && PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  const parts = node && node.result && node.result.parts;
  return parts && parts[partId] || null;
}

function pipelinePartState(entry){
  return entry && entry.state || 'pending';
}

function pipelinePartLabel(entry){
  return entry && (entry.name || entry.id) || '部件';
}

async function pipelinePartPoll(nodeId, partId, attempt){
  await new Promise(resolve=>setTimeout(resolve, attempt === 0 ? 1500 : 4000));
  if(!pipelineBridgeReady()) throw new Error('Bridge 已断开，逐件生成中止');
  const result = await pipelineApi('pipeline/provider/poll', {assetId:PIPELINE.assetId, kind:PIPELINE.kind, nodeId, partId});
  PIPELINE.graph = result.graph;
  pipelineRefreshNode(nodeId);
  const entry = pipelinePartEntry(nodeId, partId);
  const state = pipelinePartState(entry);
  if(state === 'success') return entry;
  if(['failed','cancelled','banned'].includes(state)){
    throw new Error((entry && entry.error) || (pipelinePartLabel(entry) + ' 生成失败'));
  }
  if(attempt >= 900) throw new Error(pipelinePartLabel(entry) + ' 生成超时');
  return pipelinePartPoll(nodeId, partId, attempt + 1);
}

async function pipelineSubmitPart(nodeId, partId){
  const result = await pipelineApi('pipeline/provider/submit', {assetId:PIPELINE.assetId, kind:PIPELINE.kind, nodeId, partId, confirmRemote:true});
  PIPELINE.graph = result.graph;
  pipelineRefreshNode(nodeId);
  const entry = pipelinePartEntry(nodeId, partId);
  const state = pipelinePartState(entry);
  if(state === 'success') return entry;
  if(state === 'queued' || state === 'running') return pipelinePartPoll(nodeId, partId, 0);
  throw new Error((entry && entry.error) || (pipelinePartLabel(entry) + ' 提交失败'));
}

async function pipelineRunPart(nodeId, partId){
  const node = PIPELINE.graph && PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  const entry = pipelinePartEntry(nodeId, partId);
  if(!node || !entry || !['partImage','partModel'].includes(node.type)) return;
  if(PIPELINE.partsRunning[nodeId]){toast('该节点正在逐件运行，请等当前部件结束');return;}
  if(!pipelineBridgeReady()){toast('逐件生成需要 Bridge 在线并绑定项目');return;}
  const waiting = ['queued','running'].includes(pipelinePartState(entry));
  if(!waiting){
    const provider = pipelineNodeProvider(node);
    const info = PIPELINE.providers[provider];
    if(!info || !info.configured){toast(`先在「项目」页配置 ${provider} API key`);return;}
    if(!window.confirm(`将对「${pipelinePartLabel(entry)}」调用 ${provider==='ark'?'Ark':'Tripo'} 单独生成，按件计费。现在提交？`)) return;
  }
  PIPELINE.partsRunning[nodeId] = true;
  try{
    if(waiting) await pipelinePartPoll(nodeId, partId, 0);
    else await pipelineSubmitPart(nodeId, partId);
    toast(pipelinePartLabel(entry) + ' 已生成');
  }catch(error){toast(error.message);}
  delete PIPELINE.partsRunning[nodeId];
  renderPipelineView();
}

async function pipelineRunParts(nodeId){
  const node = PIPELINE.graph && PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  if(!node || !['partImage','partModel'].includes(node.type)) return;
  if(PIPELINE.partsRunning[nodeId]){toast('该节点正在逐件运行，请等当前部件结束');return;}
  if(!pipelineBridgeReady()){toast('逐件生成需要 Bridge 在线并绑定项目');return;}
  let entries = pipelineParts(node);
  if(!entries.length){
    try{
      const result = await pipelineApi('pipeline/run', {assetId:PIPELINE.assetId, kind:PIPELINE.kind, nodeId, through:true});
      PIPELINE.graph = result.graph;
      entries = pipelineParts(PIPELINE.graph.nodes.find(item=>item.id===nodeId));
      pipelineRefreshNode(nodeId);
    }catch(error){toast(error.message);return;}
  }
  const pending = entries.filter(entry=>pipelinePartState(entry) !== 'success');
  if(!pending.length){toast('所有部件都已生成');return;}
  const provider = pipelineNodeProvider(node);
  const info = PIPELINE.providers[provider];
  if(!info || !info.configured){toast(`先在「项目」页配置 ${provider} API key`);return;}
  const label = provider==='ark'?'Ark':'Tripo';
  const action = node.type==='partImage' ? '逐件效果图' : '逐件模型';
  if(!window.confirm(`将逐个对 ${pending.length} 个部件调用 ${label} 生成${action}，每个部件单独计费。现在开始？`)) return;
  PIPELINE.partsRunning[nodeId] = true;
  try{
    await pipelineSave({quiet:true});
    let done = entries.filter(entry=>pipelinePartState(entry) === 'success').length;
    for(const item of pending){
      const state = pipelinePartState(pipelinePartEntry(nodeId, item.id));
      if(state === 'queued' || state === 'running') await pipelinePartPoll(nodeId, item.id, 0);
      else await pipelineSubmitPart(nodeId, item.id);
      done += 1;
      toast(`${pipelinePartLabel(item)} 完成（${done}/${entries.length}）`);
    }
    toast(`${action}已全部生成`);
  }catch(error){toast(error.message);}
  delete PIPELINE.partsRunning[nodeId];
  renderPipelineView();
}

async function pipelineRun(nodeId, through){
  if(PIPELINE.busy) return;
  if(!pipelineBridgeReady()){ pipelineRunLocal(nodeId, through); return; }
  if(nodeId && !through){
    const target = PIPELINE.graph && PIPELINE.graph.nodes.find(node=>node.id===nodeId);
    if(target && ['partImage','partModel'].includes(target.type)){ pipelineRunParts(nodeId); return; }
  }
  pipelineDeriveLocalStages();
  try{
    const saved = await pipelineApi('pipeline/graph/save', {assetId:PIPELINE.assetId, kind:PIPELINE.kind, graph:PIPELINE.graph});
    PIPELINE.graph = saved.graph;
    PIPELINE.archive = saved.archive || PIPELINE.archive;
    PIPELINE.source = 'bridge';
  }catch(_){ pipelineRunLocal(nodeId, through); return; }
  PIPELINE.busy = true;
  renderPipelineView();
  try{
    const result = await pipelineApi('pipeline/run', {assetId:PIPELINE.assetId,kind:PIPELINE.kind,nodeId,through:!!through});
    PIPELINE.graph = result.graph;
    const blocked = PIPELINE.graph.nodes.filter(node => node.result && node.result.state === 'blocked').length;
    toast(blocked ? '本地步骤已执行；远程生成/GLB 校验等待 Provider 或模型输入' : '流水线步骤已执行');
  }catch(error){toast(error.message);}
  PIPELINE.busy = false;
  renderPipelineView();
}

function pipelineNodeProvider(node){
  const wanted=String(node&&node.params&&node.params.provider||'').toLowerCase();
  const configured=Object.keys(PIPELINE.providers||{}).filter(name=>PIPELINE.providers[name]&&PIPELINE.providers[name].configured);
  if(configured.includes(wanted)) return wanted;
  return configured[0]||wanted||'tripo';
}

const PIPELINE_STATE_LABELS = {dirty:'待运行', blocked:'阻塞', queued:'排队中', running:'生成中',
  success:'完成', done:'完成', failed:'失败', cancelled:'已取消', banned:'已封禁', submitting:'提交中'};

function pipelineStateLabel(state, progress){
  const label = PIPELINE_STATE_LABELS[state] || state || '';
  return progress != null && (state === 'queued' || state === 'running') ? label + ' ' + progress + '%' : label;
}

function pipelineNodeState(node){
  const transient = node && PIPELINE.remote[node.id];
  if(transient) return transient;
  const task = node && node.result && node.result.providerTask;
  if(task && task.state) return task.state;
  return node && node.result && node.result.state || 'dirty';
}

function pipelineNodeBusy(node){
  return ['submitting', 'queued', 'running'].includes(pipelineNodeState(node));
}

function pipelinePollKey(assetId, kind, nodeId){
  return assetId + '|' + kind + '|' + nodeId;
}

function pipelineRefreshNode(nodeId){
  if(cur !== 'pipeline' || !PIPELINE.graph) return;
  const node = PIPELINE.graph.nodes.find(item => item.id === nodeId);
  if(!node) return;
  const card = [...document.querySelectorAll('.pipeline-node')].find(item => item.dataset.node === nodeId);
  if(!card) return;
  pipelineDisposeNodePreview(nodeId);
  card.outerHTML = pipelineNodeCard(node);
  const next = [...document.querySelectorAll('.pipeline-node')].find(item => item.dataset.node === nodeId);
  if(next){
    pipelineWireCard(next);
    pipelineMountNodePreviews(next);
  }
  pipelinePaintEdges();
  pipelinePaintMeta();
}

function pipelinePollLoop(assetId, kind, nodeId, attempt, delay, nodeType){
  const key = pipelinePollKey(assetId, kind, nodeId);
  if(PIPELINE.pollers[key]) return;
  if(!nodeType && PIPELINE.assetId === assetId && PIPELINE.kind === kind && PIPELINE.graph){
    const polled = PIPELINE.graph.nodes.find(item=>item.id === nodeId);
    nodeType = polled ? polled.type : '';
  }
  PIPELINE.pollers[key] = setTimeout(async () => {
    delete PIPELINE.pollers[key];
    if(!pipelineBridgeReady()) return;
    try{
      const result = await pipelineApi('pipeline/provider/poll', {assetId, kind, nodeId});
      const task = result.task || {};
      const current = PIPELINE.assetId === assetId && PIPELINE.kind === kind;
      if(current){
        PIPELINE.graph = result.graph;
        pipelineRefreshNode(nodeId);
      }
      if(task.state === 'queued' || task.state === 'running'){
        pipelinePollLoop(assetId, kind, nodeId, 0, 4000, nodeType);
        return;
      }
      if(current){
        const label = task.provider === 'ark' ? 'Ark' : (task.provider === 'tripo' ? 'Tripo' : 'Provider');
        toast(task.state === 'success'
          ? label + ' 生成完成'
          : label + ' 任务' + pipelineStateLabel(task.state) + (task.error ? '：' + task.error : ''));
      }
      if(task.state === 'success'){
        pipelineAdoptTask(assetId, kind, nodeId, nodeType, task);
      }
    }catch(error){
      if(attempt < 3) pipelinePollLoop(assetId, kind, nodeId, attempt + 1, 5000, nodeType);
      else toast('查询远程任务失败：' + error.message);
    }
  }, delay == null ? 1500 : delay);
}

function pipelineTrackRemote(nodeId){
  const key = pipelinePollKey(PIPELINE.assetId, PIPELINE.kind, nodeId);
  if(PIPELINE.pollers[key]){ clearTimeout(PIPELINE.pollers[key]); delete PIPELINE.pollers[key]; }
  const node = PIPELINE.graph && PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  pipelinePollLoop(PIPELINE.assetId, PIPELINE.kind, nodeId, 0, undefined, node && node.type);
}

async function pipelineSubmitRemote(nodeId){
  const node=PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  if(!node || !['textToImage','imageTo3D'].includes(node.type)) return;
  if(!pipelineBridgeReady()){toast('远程提交需要 Bridge 在线并绑定项目');return;}
  const provider=pipelineNodeProvider(node);
  const info=PIPELINE.providers[provider];
  if(!info || !info.configured){toast(`先在「项目」页配置 ${provider} API key`);return;}
  const label=provider==='ark'?'火山方舟 Ark':'Tripo';
  const model=provider==='ark'?(node.type==='textToImage'?'Seedream 5.0 Pro':'Seed3D 2.0'):(node.type==='textToImage'?'Seedream v5':'v3.1');
  const estimated=provider==='ark'?0:(node.type==='textToImage'?5:
    (node.params.texture?(node.params.textureQuality==='detailed'?50:40):30)+(node.params.smartLowPoly===false?0:10));
  const price=estimated?`，当前公开价目估算约 ${estimated} credits（$${(estimated/100).toFixed(2)}）`:'';
  if(!window.confirm(`此操作会调用 ${label}（${model}）${price}；最终以任务实耗为准。现在提交？`)) return;
  PIPELINE.remote[nodeId]='submitting';
  pipelineRefreshNode(nodeId);
  try{
    await pipelineSave();
    const result=await pipelineApi('pipeline/provider/submit',{assetId:PIPELINE.assetId,kind:PIPELINE.kind,nodeId,confirmRemote:true});
    PIPELINE.graph=result.graph;
    delete PIPELINE.remote[nodeId];
    const task=((PIPELINE.graph.nodes.find(item=>item.id===nodeId)||{}).result||{}).providerTask||{};
    toast(task.state==='success' ? `${label} 生成完成` : `已提交 ${label} 任务：${task.taskId||result.taskId}`);
    pipelineRefreshNode(nodeId);
    if(task.state==='queued'||task.state==='running') pipelineTrackRemote(nodeId);
    if(task.state==='success') pipelineAdoptTask(PIPELINE.assetId,PIPELINE.kind,nodeId,node.type,task);
  }catch(error){
    delete PIPELINE.remote[nodeId];
    pipelineRefreshNode(nodeId);
    toast(error.message);
  }
}

async function pipelinePollRemote(nodeId){
  if(!pipelineBridgeReady()){toast('查询远程任务需要 Bridge 在线并绑定项目');return;}
  try{
    const result=await pipelineApi('pipeline/provider/poll',{assetId:PIPELINE.assetId,kind:PIPELINE.kind,nodeId});
    PIPELINE.graph=result.graph;
    const task=result.task||{};
    const label=task.provider==='ark'?'Ark':(task.provider==='tripo'?'Tripo':'Provider');
    toast(label+' 状态：'+pipelineStateLabel(task.state, task.progress));
    pipelineRefreshNode(nodeId);
    if(task.state==='queued'||task.state==='running') pipelineTrackRemote(nodeId);
    const polled=PIPELINE.graph&&PIPELINE.graph.nodes.find(item=>item.id===nodeId);
    if(task.state==='success'&&polled) pipelineAdoptTask(PIPELINE.assetId,PIPELINE.kind,nodeId,polled.type,task);
  }catch(error){toast(error.message);}
}

function pipelineWireCard(card){
  pipelineDragCard(card);
  card.onclick=event=>{
    if(event.target.closest('button,select,input,textarea,.pipeline-port')) return;
    if(PIPELINE.selected===card.dataset.node) return;
    PIPELINE.selected=card.dataset.node;
    document.querySelectorAll('.pipeline-node').forEach(item=>item.classList.toggle('selected',item.dataset.node===PIPELINE.selected));
  };
  pipelineWirePorts(card);
  card.querySelectorAll('[data-run]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRun(button.dataset.run,false);});
  card.querySelectorAll('[data-through]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRun(button.dataset.through,true);});
  card.querySelectorAll('[data-remote]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineSubmitRemote(button.dataset.remote);});
  card.querySelectorAll('[data-poll]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelinePollRemote(button.dataset.poll);});
  card.querySelectorAll('[data-part-retry]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRunPart(button.dataset.partRetry,button.dataset.partId);});
  card.querySelectorAll('[data-preview-model]').forEach(button=>button.onclick=event=>{event.stopPropagation();openPipelineModelPreview(button.dataset.previewModel);});
  card.querySelectorAll('[data-apply]').forEach(button=>button.onclick=event=>{
    event.stopPropagation();
    const node=PIPELINE.graph.nodes.find(item=>item.id===button.dataset.apply);
    const task=pipelineApplyTaskFor(node);
    if(task) pipelineAdoptTask(PIPELINE.assetId,PIPELINE.kind,node.id,node.type,task,true);
  });
  card.querySelectorAll('[data-open-asset]').forEach(button=>button.onclick=event=>{
    event.stopPropagation();
    pipelineOpenAsset(PIPELINE.assetId,PIPELINE.kind);
  });
  card.querySelectorAll('[data-node-model]').forEach(figure=>figure.onclick=event=>{event.stopPropagation();openPipelineModelPreview(figure.dataset.nodeModel);});
  card.querySelectorAll('[data-delete-node]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRemoveNode(button.dataset.deleteNode);});
  card.querySelectorAll('[data-param]').forEach(input=>input.onchange=()=>{
    const node=PIPELINE.graph.nodes.find(item=>item.id===card.dataset.node);
    if(!node) return;
    const key=input.dataset.param;
    if(key==='text'){node.params.text=input.value;}
    else if(key==='json'){
      try{node.params=JSON.parse(input.value);}catch(_){toast('参数必须是合法 JSON');return;}
    }
    else if(input.type==='checkbox'){node.params[key]=input.checked;}
    else if(key==='provider'){if(input.value) node.params[key]=input.value; else delete node.params[key];}
    else if(input.type==='number'){
      const raw=input.value.trim();
      if(!raw){delete node.params[key];}
      else{
        const number=Number(raw);
        if(!Number.isFinite(number)){toast('请输入有效数字');return;}
        const decimal=key==='overlap'||(input.step&&input.step.indexOf('.')>=0);
        node.params[key]=decimal?number:Math.trunc(number);
      }
    }
    else{
      const raw=input.value.trim();
      if(raw) node.params[key]=raw; else delete node.params[key];
    }
    pipelineSave({quiet:true}).catch(error=>toast(error.message));
  });
}

let _pipelinePreview = null;

function pipelineDisposeScene(scene){
  scene.traverse(object=>{
    if(object.geometry) object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : (object.material ? [object.material] : []);
    materials.forEach(material=>{
      Object.keys(material).forEach(key=>{
        const value = material[key];
        if(value && value.isTexture) value.dispose();
      });
      material.dispose();
    });
  });
}

function pipelineClosePreview(){
  const ctx = _pipelinePreview;
  if(!ctx) return;
  _pipelinePreview = null;
  cancelAnimationFrame(ctx.raf);
  document.removeEventListener('keydown', ctx.onKey);
  if(ctx.observer) ctx.observer.disconnect();
  ctx.controls.dispose();
  pipelineDisposeScene(ctx.scene);
  ctx.renderer.dispose();
  if(ctx.renderer.forceContextLoss) ctx.renderer.forceContextLoss();
}

function openPipelineModelPreview(url){
  if(!url) return;
  if(!haveThree() || !THREE.GLTFLoader){ alert('three.js / GLTFLoader 未加载，无法预览模型。'); return; }
  pipelineClosePreview();
  document.getElementById('modal').innerHTML = `
    <header><h3>模型预览 · ${pipelineEscape(PIPELINE.assetId || '')}</h3><span class="x" id="pmX">×</span></header>
    <div class="content" style="padding:0">
      <div style="position:relative;background:#f2f0ec">
        <canvas id="pmCanvas" style="display:block;width:100%;height:440px"></canvas>
        <div style="position:absolute;left:12px;top:10px;font-size:11px;color:#5f5e5a;background:rgba(255,255,255,.85);padding:4px 9px;border-radius:6px;pointer-events:none">拖动旋转 · 滚轮缩放 · 双击复位</div>
        <div id="pmStatus" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:#5f5e5a;background:rgba(242,240,236,.86);pointer-events:none">加载模型…</div>
      </div>
      <div style="padding:10px 20px;border-top:1px solid var(--border);display:flex;gap:8px;align-items:center">
        <button class="sm" id="pmSpin">暂停旋转</button>
        <button class="sm" id="pmReset">复位</button>
        <span style="flex:1"></span>
        <span id="pmInfo" style="font-size:11px;color:var(--text-3);font-family:var(--mono)"></span>
      </div>
    </div>`;
  document.getElementById('mask').classList.remove('hide');

  const status = document.getElementById('pmStatus');
  const info = document.getElementById('pmInfo');
  const canvas = document.getElementById('pmCanvas');
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf2f0ec);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 4000);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.6;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8f8a80, 1.2));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.5);
  keyLight.position.set(5, 9, 7);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0xffffff, .6);
  rimLight.position.set(-6, 4, -5);
  scene.add(rimLight);
  const grid = new THREE.GridHelper(10, 20, 0xc9c4ba, 0xe2ded6);
  scene.add(grid);

  const resize = ()=>{
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const ctx = {renderer, scene, camera, controls, raf:0, onKey:null, observer:null};
  _pipelinePreview = ctx;
  resize();
  if(typeof ResizeObserver === 'function'){
    ctx.observer = new ResizeObserver(resize);
    ctx.observer.observe(canvas);
  }

  let fitView = ()=>{};
  new THREE.GLTFLoader().load(url, gltf=>{
    if(_pipelinePreview !== ctx) return;
    const model = gltf.scene || (gltf.scenes && gltf.scenes[0]);
    if(!model){ status.textContent = '模型为空'; return; }
    const holder = new THREE.Group();
    holder.add(model);
    scene.add(holder);
    const box = new THREE.Box3().setFromObject(holder);
    const size = new THREE.Vector3();
    box.getSize(size);
    const center = new THREE.Vector3();
    box.getCenter(center);
    holder.position.copy(center).multiplyScalar(-1);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    fitView = ()=>{
      const radius = maxDim * 1.65;
      camera.near = Math.max(0.01, maxDim / 200);
      camera.far = radius * 30;
      camera.position.set(radius * 0.78, radius * 0.55, radius * 0.95);
      camera.updateProjectionMatrix();
      controls.target.set(0, 0, 0);
      controls.update();
      grid.position.y = -size.y / 2;
    };
    fitView();
    status.style.display = 'none';
    info.textContent = size.x.toFixed(2) + ' × ' + size.y.toFixed(2) + ' × ' + size.z.toFixed(2) + ' m';
  }, undefined, error=>{
    if(_pipelinePreview !== ctx) return;
    status.textContent = '模型加载失败：' + (error && error.message || error);
  });

  const animate = ()=>{
    if(_pipelinePreview !== ctx) return;
    controls.update();
    renderer.render(scene, camera);
    ctx.raf = requestAnimationFrame(animate);
  };
  ctx.raf = requestAnimationFrame(animate);

  const close = ()=>{ pipelineClosePreview(); closeModal(); };
  document.getElementById('pmX').onclick = close;
  ctx.onKey = event=>{ if(event.key === 'Escape') close(); };
  document.addEventListener('keydown', ctx.onKey);
  const spin = document.getElementById('pmSpin');
  spin.onclick = ()=>{
    controls.autoRotate = !controls.autoRotate;
    spin.textContent = controls.autoRotate ? '暂停旋转' : '自动旋转';
  };
  document.getElementById('pmReset').onclick = ()=>fitView();
  canvas.ondblclick = ()=>fitView();
}

const _pipelineNodePreviews = new Map();

function pipelineDisposeNodePreview(nodeId){
  const ctx = _pipelineNodePreviews.get(nodeId);
  if(!ctx) return;
  _pipelineNodePreviews.delete(nodeId);
  cancelAnimationFrame(ctx.raf);
  pipelineDisposeScene(ctx.scene);
  ctx.renderer.dispose();
  if(ctx.renderer.forceContextLoss) ctx.renderer.forceContextLoss();
}

function pipelineDisposeAllNodePreviews(){
  [..._pipelineNodePreviews.keys()].forEach(pipelineDisposeNodePreview);
}

function pipelineMountNodePreviews(root){
  if(!root || !haveThree() || !THREE.GLTFLoader) return;
  root.querySelectorAll('[data-node-model]').forEach(figure=>{
    const nodeId = figure.dataset.nodeModelId;
    if(!nodeId || _pipelineNodePreviews.has(nodeId)) return;
    const canvas = figure.querySelector('canvas');
    if(canvas) pipelineMountNodePreview(figure, nodeId, canvas);
  });
}

function pipelineMountNodePreview(figure, nodeId, canvas){
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.02, 4000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8f8a80, 1.25));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.5);
  keyLight.position.set(5, 9, 7);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0xffffff, .55);
  rimLight.position.set(-6, 4, -5);
  scene.add(rimLight);
  const ctx = {renderer, scene, camera, raf:0, holder:null};
  _pipelineNodePreviews.set(nodeId, ctx);

  const resize = ()=>{
    const rect = canvas.getBoundingClientRect();
    if(rect.width < 1 || rect.height < 1) return;
    renderer.setSize(Math.round(rect.width), Math.round(rect.height), false);
    camera.aspect = rect.width / Math.max(1, rect.height);
    camera.updateProjectionMatrix();
  };
  resize();

  new THREE.GLTFLoader().load(figure.dataset.nodeModel, gltf=>{
    if(_pipelineNodePreviews.get(nodeId) !== ctx){
      if(gltf.scene) pipelineDisposeScene(gltf.scene);
      return;
    }
    const model = gltf.scene || (gltf.scenes && gltf.scenes[0]);
    if(!model){ figure.classList.add('failed'); return; }
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    model.position.sub(center);
    const holder = new THREE.Group();
    holder.add(model);
    scene.add(holder);
    ctx.holder = holder;
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const radius = maxDim * 1.7;
    camera.near = Math.max(0.01, maxDim / 200);
    camera.far = radius * 30;
    camera.position.set(radius * .7, radius * .5, radius * .95);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
  }, undefined, ()=>{
    if(_pipelineNodePreviews.get(nodeId) === ctx) figure.classList.add('failed');
  });

  const animate = ()=>{
    if(_pipelineNodePreviews.get(nodeId) !== ctx) return;
    if(ctx.holder) ctx.holder.rotation.y += 0.012;
    renderer.render(scene, camera);
    ctx.raf = requestAnimationFrame(animate);
  };
  ctx.raf = requestAnimationFrame(animate);
}

/** 只接受文件名，杜绝 ../ 与盘符路径；Bridge 端也按 basename 解析。 */
function pipelineOutputURLFor(assetId, kind, file){
  if(!file) return '';
  const name = String(file).replace(/\\/g, '/').split('/').pop();
  if(!name || name === '.' || name === '..') return '';
  return '/api/pipeline/output/' + encodeURIComponent(assetId) + '/' +
    encodeURIComponent(name) + '?kind=' + encodeURIComponent(kind);
}

function pipelineOutputURL(file){
  if(!pipelineBridgeReady() || !PIPELINE.assetId) return '';
  return pipelineOutputURLFor(PIPELINE.assetId, PIPELINE.kind, file);
}

const PIPELINE_PROVIDER_OPTIONS = [{value:'',label:'自动'},{value:'tripo',label:'Tripo'},{value:'ark',label:'Ark'}];
const PIPELINE_MODEL_OPTIONS = [{value:'',label:'默认'},{value:'v3.1-20260211',label:'v3.1'},{value:'v3.0-20250812',label:'v3.0'}];

function pipelineParamRow(label, control){
  return `<label><span>${pipelineEscape(label)}</span>${control}</label>`;
}
function pipelineParamText(node, key, label, placeholder){
  const value = node.params[key] == null ? '' : node.params[key];
  return pipelineParamRow(label, `<input data-param="${key}" type="text" value="${pipelineEscape(value)}" placeholder="${pipelineEscape(placeholder || '')}">`);
}
function pipelineParamNumber(node, key, label, attrs, placeholder){
  const value = node.params[key] == null ? '' : node.params[key];
  return pipelineParamRow(label, `<input data-param="${key}" type="number" ${attrs || ''} value="${pipelineEscape(value)}" placeholder="${pipelineEscape(placeholder || '')}">`);
}
function pipelineParamCheck(node, key, label, fallback){
  const on = node.params[key] == null ? !!fallback : !!node.params[key];
  return pipelineParamRow(label, `<input data-param="${key}" type="checkbox" ${on ? 'checked' : ''}>`);
}
function pipelineParamSelect(node, key, label, options, fallback){
  const value = node.params[key] == null ? '' : String(node.params[key]);
  return pipelineParamRow(label, `<select data-param="${key}">${options.map(option =>
    `<option value="${pipelineEscape(option.value)}" ${(value || fallback) === option.value ? 'selected' : ''}>${pipelineEscape(option.label)}</option>`).join('')}</select>`);
}
function pipelineParamForm(node){
  if(node.type === 'textToImage'){
    return `<div class="pipeline-params">
      ${pipelineParamSelect(node, 'provider', '平台', PIPELINE_PROVIDER_OPTIONS, '')}
      ${pipelineParamText(node, 'size', '分辨率', '1K / 1.5K / 2K')}
      ${pipelineParamSelect(node, 'outputFormat', '格式', [{value:'png',label:'PNG'},{value:'jpeg',label:'JPEG'}], 'png')}
      ${pipelineParamCheck(node, 'watermark', '水印', false)}
      <small class="pipeline-params-hint">Ark 可选 1K/1.5K/2K；也可填像素尺寸，如 2048x1152。</small>
    </div>`;
  }
  if(node.type === 'imageTo3D'){
    const textureOn = !!node.params.texture;
    return `<div class="pipeline-params">
      ${pipelineParamSelect(node, 'provider', '平台', PIPELINE_PROVIDER_OPTIONS, '')}
      ${pipelineParamSelect(node, 'tripoModel', 'Tripo 模型', PIPELINE_MODEL_OPTIONS, '')}
      ${pipelineParamNumber(node, 'faceLimit', '面数上限', 'min="500" max="150000" step="500"', '20000')}
      ${pipelineParamCheck(node, 'texture', '生成贴图', false)}
      ${pipelineParamCheck(node, 'pbr', 'PBR 材质', textureOn)}
      ${pipelineParamSelect(node, 'textureQuality', '贴图精度', [{value:'standard',label:'标准'},{value:'detailed',label:'精细'},{value:'',label:'默认'}], 'standard')}
      ${pipelineParamCheck(node, 'smartLowPoly', '智能低模', true)}
      ${pipelineParamCheck(node, 'autoSize', '自动尺寸', false)}
      ${pipelineParamSelect(node, 'orientation', '朝向', [{value:'default',label:'默认'},{value:'align_image',label:'对齐参考图'}], 'default')}
      ${pipelineParamNumber(node, 'modelSeed', '模型种子', 'min="0" step="1"', '随机')}
      ${pipelineParamNumber(node, 'textureSeed', '贴图种子', 'min="0" step="1"', '随机')}
      <small class="pipeline-params-hint">面数/贴图参数仅 Tripo 生效；PBR 需先开启贴图。</small>
    </div>`;
  }
  if(node.type === 'partSpec'){
    return `<div class="pipeline-params">
      ${pipelineParamNumber(node, 'parts', '部件数', 'min="2" max="12" step="1"', '3')}
      ${pipelineParamSelect(node, 'axis', '粗切轴', [{value:'x',label:'X 横向'},{value:'y',label:'Y 纵向'},{value:'z',label:'Z 深度'}], 'x')}
      <small class="pipeline-params-hint">由 Blender 把整机模型均分粗切，再按描述词的【必须包含的部件】改名；先跑图生 3D。</small>
    </div>`;
  }
  if(node.type === 'partImage'){
    return `<div class="pipeline-params">
      ${pipelineParamSelect(node, 'provider', '平台', PIPELINE_PROVIDER_OPTIONS, '')}
      ${pipelineParamText(node, 'size', '分辨率', '1K / 1.5K / 2K')}
      ${pipelineParamSelect(node, 'outputFormat', '格式', [{value:'png',label:'PNG'},{value:'jpeg',label:'JPEG'}], 'png')}
      <small class="pipeline-params-hint">逐件文生图：整机描述 + 本件名称/说明 + 单件纯色背景；每个部件单独计费。</small>
    </div>`;
  }
  if(node.type === 'partModel'){
    return `<div class="pipeline-params">
      ${pipelineParamSelect(node, 'provider', '平台', PIPELINE_PROVIDER_OPTIONS, '')}
      ${pipelineParamNumber(node, 'faceLimit', '面数上限', 'min="500" max="150000" step="500"', '3000')}
      ${pipelineParamCheck(node, 'texture', '生成贴图', false)}
      <small class="pipeline-params-hint">逐件图生 3D：读取上一步该部件的效果图，产物写回分件契约。</small>
    </div>`;
  }
  if(node.type === 'assemble'){
    return `<div class="pipeline-params">
      ${pipelineParamSelect(node, 'fit', '适配方式', [{value:'contain',label:'等比装入'},{value:'height',label:'按高度对齐'}], 'contain')}
      ${pipelineParamNumber(node, 'overlap', '重叠量', 'min="-0.2" max="0.5" step="0.01"', '0.02')}
      <small class="pipeline-params-hint">由 Blender 按契约包围盒装配各部件；满意后「应用装配」写入资产模型。</small>
    </div>`;
  }
  if(node.type === 'decimate'){
    return `<div class="pipeline-params">
      ${pipelineParamNumber(node, 'targetFaces', '目标面数', 'min="50" max="2000000" step="50"', '900')}
      <small class="pipeline-params-hint">由 Blender Decimate 执行；每次运行生成一个新 GLB，满意后手动「应用减面」。</small>
    </div>`;
  }
  return `<label>参数 <input data-param="json" value="${pipelineEscape(JSON.stringify(node.params || {}))}"></label>`;
}

function pipelineNodeCard(node){
  const state = pipelineNodeState(node);
  const busy = pipelineNodeBusy(node);
  const selected = PIPELINE.selected === node.id;
  const task = node.result && node.result.providerTask;
  const applyTask = pipelineApplyTaskFor(node);
  const currentAsset = pipelineFindAsset(PIPELINE.kind, PIPELINE.assetId);
  const applySlot = node.type === 'textToImage' ? 'image'
    : ((node.type === 'imageTo3D' || node.type === 'decimate' || node.type === 'assemble') && PIPELINE.kind !== 'element' ? 'model' : '');
  const generated = (currentAsset && currentAsset.generated) || {};
  const applied = !!(applySlot && applyTask && applyTask.taskId
    && generated[applySlot] && generated[applySlot].taskId === applyTask.taskId);
  const applyOwner = (PIPELINE.applyNodes || {})[PIPELINE.assetId] || '';
  const applyMine = !applyOwner || applyOwner === node.id;
  const applyStatus = applySlot && applyMine ? (PIPELINE.applyStatus[PIPELINE.assetId] || '') : '';
  const applyError = applySlot && applyMine ? (PIPELINE.applyErrors[PIPELINE.assetId] || '') : '';
  const applyReady = !!(applySlot && applyTask && applyTask.state === 'success' && applyTask.output
    && (applySlot === 'image' ? applyTask.output.imagePath : applyTask.output.modelPath));
  const exportOutput = node.type === 'export' && node.result && node.result.state === 'done'
    && node.result.output && node.result.output.sourceDir ? node.result.output : null;
  const appliedDate = applied && generated[applySlot] && generated[applySlot].at
    ? new Date(generated[applySlot].at) : null;
  const appliedWhen = appliedDate && Number.isFinite(appliedDate.getTime())
    ? appliedDate.toLocaleString('zh-CN') : '';
  const progress = task && task.progress;
  const params = node.type === 'prompt'
    ? `<textarea data-param="text" rows="3" placeholder="输入模型描述词">${pipelineEscape(node.params.text || '')}</textarea>`
    : pipelineParamForm(node);
  const taskOutput=applyTask&&applyTask.output||node.result&&node.result.output||{};
  const outputFile=taskOutput.modelPath||taskOutput.meshPath||taskOutput.imagePath;
  const outputURL=pipelineOutputURL(outputFile);
  const outputLink=outputURL?`<a class="pipeline-output" href="${pipelineEscape(outputURL)}" download>下载输出</a>`:'';
  const imageURL=pipelineOutputURL(taskOutput.imagePath);
  const modelURL=pipelineOutputURL(taskOutput.modelPath||taskOutput.meshPath);
  let media='';
  if(node.type==='textToImage'){
    media=imageURL
      ? `<figure class="pipeline-node-media"><img src="${pipelineEscape(imageURL)}" alt="生成图" loading="lazy"></figure>`
      : `<div class="pipeline-node-media empty">${busy?'生成中…':'未生成图像'}</div>`;
  }else if(node.type==='imageTo3D'||node.type==='decimate'||node.type==='assemble'){
    media=modelURL
      ? `<figure class="pipeline-node-media model" data-node-model="${pipelineEscape(modelURL)}" data-node-model-id="${pipelineEscape(node.id)}" title="点击放大查看"><canvas aria-label="3D 模型预览"></canvas></figure><button class="pipeline-node-preview" data-preview-model="${pipelineEscape(modelURL)}">预览 3D 模型</button>`
      : `<div class="pipeline-node-media empty">${busy?'生成中…':(node.type==='decimate'?'未生成减面模型':(node.type==='assemble'?'未生成装配模型':'未生成模型'))}</div>`;
  }
  const history=(node.result&&node.result.history||[]).slice().reverse();
  const historyHTML=history.length?`<details class="pipeline-history"><summary>历史版本 ${history.length}</summary><div class="pipeline-history-list">${history.map(item=>{
    const file=item.output&&(item.output.imagePath||item.output.modelPath)||'';
    const url=pipelineOutputURL(file);
    const thumb=item.output&&item.output.imagePath&&url?`<img src="${pipelineEscape(url)}" alt="历史生成图" loading="lazy">`:'';
    const when=item.submittedAt?new Date(item.submittedAt*1000).toLocaleString('zh-CN'):'';
    const name=pipelineEscape(item.taskId||'任务')+(when?' · '+pipelineEscape(when):'');
    return `<a class="pipeline-history-item" href="${pipelineEscape(url||'#')}" ${url?'download':''}>${thumb}<span>${name}<em>${pipelineEscape(pipelineStateLabel(item.state||''))}</em></span></a>`;
  }).join('')}</div></details>`:'';
  const taskError=task&&task.state==='failed'?task.error:'';
  const error=(['success','done'].includes(state)?'':node.result&&node.result.error)||taskError;
  const showPoll=task&&((['success','failed','cancelled','banned'].indexOf(task.state)<0)
    ||(node.type==='textToImage'&&!(task.output&&task.output.imagePath)));
  const stageSummary=pipelineStageSummary(node);
  const partEntries=['partImage','partModel'].includes(node.type)?pipelineParts(node):[];
  const partDone=partEntries.filter(entry=>pipelinePartState(entry)==='success').length;
  const headerLabel=partEntries.length
    ? pipelineStateLabel(state, progress) + ' · ' + partDone + '/' + partEntries.length
    : pipelineStateLabel(state, progress);
  const partList=partEntries.length?`<div class="pipeline-parts">${partEntries.map(entry=>{
    const partState=pipelinePartState(entry);
    const partImage=pipelineOutputURL((entry.output||{}).imagePath);
    const partModel=pipelineOutputURL((entry.output||{}).modelPath);
    const thumb=partImage?`<img src="${pipelineEscape(partImage)}" alt="" loading="lazy">`:'';
    const modelLink=partModel?`<a class="pipeline-part-link" href="${pipelineEscape(partModel)}" download>模型</a>`:'';
    const retry=['pending','failed','queued','running'].includes(partState)
      ? `<button data-part-retry="${pipelineEscape(node.id)}" data-part-id="${pipelineEscape(entry.id)}">${partState==='failed'?'重试':(['queued','running'].includes(partState)?'继续':'生成')}</button>`:'';
    return `<div class="pipeline-part ${pipelineEscape(partState)}">${thumb}<span>${pipelineEscape(pipelinePartLabel(entry))}</span><em>${pipelineEscape(pipelineStateLabel(partState))}</em>${modelLink}${retry}</div>`;
  }).join('')}</div>`:'';
  const runLabel=['partImage','partModel'].includes(node.type)?'逐件生成':'运行';
  const inPorts=pipelinePorts(node.type,'in').map(port=>`<span class="pipeline-port pipeline-port-in pipeline-port-${pipelineEscape(port)}" data-in-node="${pipelineEscape(node.id)}" data-in-port="${pipelineEscape(port)}" title="输入 ${pipelineEscape(port)}" style="top:${pipelinePortTop(node.type,'in',port)}px"></span>`).join('');
  const outPorts=pipelinePorts(node.type,'out').map(port=>`<span class="pipeline-port pipeline-port-out pipeline-port-${pipelineEscape(port)}" data-out-node="${pipelineEscape(node.id)}" data-out-port="${pipelineEscape(port)}" title="输出 ${pipelineEscape(port)} · 拖到下游输入端" style="top:${pipelinePortTop(node.type,'out',port)}px"></span>`).join('');
  return `<article class="pipeline-node ${selected?'selected':''} ${busy?'is-running':''}" data-node="${pipelineEscape(node.id)}" style="left:${Number(node.x)||0}px;top:${Number(node.y)||0}px">
    ${inPorts}${outPorts}
    <header><b>${pipelineEscape(PIPELINE_NODE_LABELS[node.type] || node.type)}</b><span>${pipelineEscape(headerLabel)}</span></header>
    <small>${pipelineEscape(node.id)}${progress!=null?' · '+progress+'%':''}</small>${params}${media}${partList}${stageSummary?`<small class="pipeline-stage">${pipelineEscape(stageSummary)}</small>`:''}
    <div class="pipeline-node-actions"><button data-run="${pipelineEscape(node.id)}">${runLabel}</button><button data-through="${pipelineEscape(node.id)}">运行到此</button>${['textToImage','imageTo3D'].includes(node.type)?`<button data-remote="${pipelineEscape(node.id)}">远程提交</button>${showPoll?`<button data-poll="${pipelineEscape(node.id)}">查询任务</button>`:''}`:''}<button data-delete-node="${pipelineEscape(node.id)}">删除</button>${applyReady ? `<button data-apply="${pipelineEscape(node.id)}">${applied ? '重新应用' : (node.type === 'decimate' ? '应用减面' : (node.type === 'assemble' ? '应用装配' : '应用结果'))}</button>` : ''}${applied ? `<button data-open-asset="${pipelineEscape(node.id)}">打开资产</button>` : ''}</div>${outputLink}${historyHTML}
    ${exportOutput ? `<small class="pipeline-stage">已导出：${pipelineEscape(exportOutput.sourceDir)}</small>` : ''}
    ${applied
      ? `<small class="pipeline-stage">已应用到 ${pipelineEscape((currentAsset && currentAsset.name) || '资产')}${appliedWhen ? ' · ' + pipelineEscape(appliedWhen) : ''}</small>`
      : (applyStatus ? `<small class="pipeline-stage">${pipelineEscape(applyStatus)}</small>` : '')}
    ${applyError ? `<small class="${applyStatus === '已跳过' ? 'pipeline-stage' : 'pipeline-error'}">${pipelineEscape(applyError)}</small>` : ''}
    ${error?`<small class="pipeline-error">${pipelineEscape(error)}</small>`:''}
  </article>`;
}

function renderPipelineView(){
  const view=document.getElementById('view');
  if(!view) return;
  pipelineDisposeAllNodePreviews();
  if(cur !== 'pipeline') return;
  if(SYNC.probing && !SYNC.online){
    view.innerHTML='<div class="card"><p>正在连接 Forge Bridge…</p></div>';
    return;
  }
  const bridgeReady=pipelineBridgeReady();
  const candidates=[...S.machines.map(machine=>({id:machine.id,name:machine.name,kind:'machine'})),...S.items.map(item=>({id:item.id,name:item.name,kind:'item'})),...(S.elements||[]).map(element=>({id:element.id,name:element.name,kind:'element'}))];
  if(!candidates.length){view.innerHTML='<div class="card"><p>当前没有可建立流水线的机器或物品。</p></div>';return;}
  if(!PIPELINE.assetId){
    const last = pipelineLastAsset();
    const hit = last && candidates.find(item=>item.id===last.id && item.kind===last.kind);
    PIPELINE.assetId = (hit || candidates[0]).id;
  }
  if(!PIPELINE.graph){
    view.innerHTML='<div class="card"><p>正在读取资产流水线…</p></div>';
    pipelineLoad(PIPELINE.assetId).then(renderPipelineView).catch(error=>{if(cur==='pipeline') view.innerHTML=`<div class="card">${pipelineEscape(error.message)}</div>`;});
    return;
  }
  const providerNames=Object.keys(PIPELINE.providers||{});
  const selected=candidates.find(item=>item.id===PIPELINE.assetId);
  const machine= S.machines.find(item=>item.id===PIPELINE.assetId);
  const item= S.items.find(value=>value.id===PIPELINE.assetId);
  const element= (S.elements||[]).find(value=>value.id===PIPELINE.assetId);
  const promptNode=PIPELINE.graph.nodes.find(node=>node.type==='prompt');
  if(promptNode && !promptNode.params.text && machine && typeof machinePrompt==='function') promptNode.params.text=machinePrompt(machine,{withTech:true});
  if(promptNode && !promptNode.params.text && item && typeof itemPrompt==='function') promptNode.params.text=itemPrompt(item,{withTech:true});
  if(promptNode && !promptNode.params.text && element && typeof elementPrompt==='function') promptNode.params.text=elementPrompt(element,{withTech:true});
  const edgeSvg=pipelineEdgeSvg();
  const defaultTemplate = PIPELINE.kind === 'element' ? 'icon'
    : (PIPELINE.kind === 'item' ? 'item' : 'machine');
  view.innerHTML=`<div class="pipeline-toolbar card">
    <div class="pt-field"><label for="pipelineAsset">资产</label>
      <select id="pipelineAsset">${candidates.map(item=>{
        const archived=pipelineHasArchive(item.id);
        return `<option value="${pipelineEscape(item.id)}" ${item.id===PIPELINE.assetId?'selected':''}>${archived?'🟢 ':''}${pipelineEscape(item.name)} · ${pipelineEscape(item.id)}${archived?' · 已存档':''}</option>`;
      }).join('')}</select></div>
    <div class="pt-field"><label for="pipelineTemplate">模板</label>
      <select id="pipelineTemplate">${PIPELINE_TEMPLATES.map(template=>`<option value="${template.id}" ${template.id===(PIPELINE.graph.template || defaultTemplate)?'selected':''}>${template.label}</option>`).join('')}</select></div>
    <div class="pt-btns">
      ${PIPELINE.returnTo?`<button id="pipelineBack">${pipelineReturnLabel()}</button>`:''}
      <button id="pipelineMake">新建模板</button><button id="pipelineEstimate">批量预估</button><button id="pipelineArrange">自动布局</button><button id="pipelineSave">保存图</button><button id="pipelineZoomReset" title="滚轮缩放 · 按住右键拖动平移 · 点击复位">100%</button><button id="pipelineRunAll" class="primary">运行全部（本地节点）</button>
    </div>
    <div class="pt-note">
      <span>远程 Provider：${bridgeReady
        ? (providerNames.map(name=>`${pipelineEscape(name)} ${PIPELINE.providers[name].configured?'已配置':'未配置'}`).join(' · ')||'未配置') + ' <span style="color:var(--text-3)">（在「项目」页配置）</span>'
        : 'Bridge 未连接（离线只能编辑与运行本地步骤）'}</span>
      ${bridgeReady
        ? '<span>远程任务需逐次确认；额度预估按当前公开价目，最终以任务实耗为准。</span>'
        : '<span>每个资产单独存档在本机浏览器；启动 Bridge 并打开项目后，自动写回该资产文件夹下的 pipeline/。</span>'}
    </div>
  </div>
  <div class="pipeline-shell"><aside class="pipeline-palette"><b>节点</b>${Object.entries(PIPELINE_NODE_LABELS).map(([type,label])=>`<button data-add="${type}">${label}</button>`).join('')}</aside>
  <div class="pipeline-scroll"><div class="pipeline-canvas" style="width:${Math.max(1700,...PIPELINE.graph.nodes.map(node=>(Number(node.x)||0)+260))}px;height:${Math.max(650,...PIPELINE.graph.nodes.map(node=>(Number(node.y)||0)+210))}px"><svg>${edgeSvg}</svg>${PIPELINE.graph.nodes.map(pipelineNodeCard).join('')}</div></div></div>
  <div class="card"><b>${pipelineEscape(selected&&selected.name||PIPELINE.assetId)}</b><span id="pipelineMeta"></span>
  <div style="font-family:var(--mono);font-size:10.5px;color:var(--text-3);margin-top:4px">项目：${pipelineEscape(bridgeReady&&SYNC.status.project.root ? SYNC.status.project.root : '未打开（浏览器本地）')}</div>
  <div class="pipeline-ports-hint">拖动节点两侧圆点连线：左侧输入端口各保留一条连线（新连线替换旧的），右侧输出可同时接多个下游；拖动中按 Esc 取消。滚轮缩放，按住右键拖动平移，工具条上的百分比按钮复位视角。</div>
  <div class="pipeline-edge-list">${PIPELINE.graph.edges.map((edge,index)=>`<span>${pipelineEscape(edge.from)}.${pipelineEscape(edge.out)} → ${pipelineEscape(edge.to)}.${pipelineEscape(edge.in)} <button data-remove-edge="${index}">断开</button></span>`).join('')}</div></div>`;
  document.getElementById('pipelineAsset').onchange=async event=>{PIPELINE.graph=null;await pipelineLoad(event.target.value);renderPipelineView();};
  const pipelineBackButton=document.getElementById('pipelineBack');
  if(pipelineBackButton)pipelineBackButton.onclick=pipelineReturn;
  document.getElementById('pipelineMake').onclick=()=>pipelineCreateTemplate(document.getElementById('pipelineTemplate').value).catch(error=>toast(error.message));
  document.getElementById('pipelineEstimate').onclick=()=>{const kind=document.getElementById('pipelineTemplate').value;const count=['machine','parts'].includes(kind)?S.machines.length:S.items.length;const estimate=pipelineEstimate(kind,count);toast(`${estimate.assets} 个资产：约 ${estimate.lowCredits}–${estimate.highCredits} credits（$${estimate.lowUsd.toFixed(2)}–$${estimate.highUsd.toFixed(2)}）；以任务实际实耗为准`);};
  document.getElementById('pipelineSave').onclick=()=>pipelineSave().catch(error=>toast(error.message));
  document.getElementById('pipelineArrange').onclick=pipelineArrange;
  document.getElementById('pipelineZoomReset').onclick=()=>{
    PIPELINE.zoom=1;
    PIPELINE.pan.x=0;
    PIPELINE.pan.y=0;
    pipelineApplyZoom();
  };
  document.getElementById('pipelineRunAll').onclick=()=>pipelineRun(null,false);
  view.querySelectorAll('[data-add]').forEach(button=>button.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;
    event.preventDefault();
    pipelineStartPaletteDrag(button,event);
  }));
  view.querySelectorAll('[data-node]').forEach(pipelineWireCard);
  pipelineMountNodePreviews(view.querySelector('.pipeline-canvas'));
  PIPELINE.graph.nodes.forEach(node=>{
    const task=node.result&&node.result.providerTask;
    if(task&&(task.state==='queued'||task.state==='running')) pipelinePollLoop(PIPELINE.assetId,PIPELINE.kind,node.id,0,1200,node.type);
  });
  const scroll=view.querySelector('.pipeline-scroll');
  if(scroll){
    pipelinePanCanvas(scroll);
    pipelineApplyZoom();
  }
  pipelinePaintMeta();
  view.querySelectorAll('[data-remove-edge]').forEach(button=>button.onclick=()=>pipelineRemoveEdge(Number(button.dataset.removeEdge)));
}
