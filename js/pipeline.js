const PIPELINE = {assetId:null, graph:null, providers:{}, selected:null, busy:false, source:'local', zoom:1};
const PIPELINE_STORE_PREFIX = 'fw.pipeline.';

const PIPELINE_NODE_LABELS = {
  prompt:'描述词', textToImage:'概念图生成', imageTo3D:'图生 3D', decimate:'减面',
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
  decimate:{in:['mesh'],out:['mesh']}, styleApply:{in:['mesh'],out:['mesh']},
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

async function pipelineLoad(assetId){
  PIPELINE.assetId = assetId;
  PIPELINE.providers = {};
  PIPELINE.source = 'local';
  let graph = null;
  if(pipelineBridgeReady()){
    try{
      const result = await pipelineApi('pipeline/graph/' + encodeURIComponent(assetId));
      graph = result.graph;
      PIPELINE.source = 'bridge';
    }catch(_){ /* 读不到就退回浏览器本地图 */ }
    try{
      const providers = await pipelineApi('pipeline/providers');
      PIPELINE.providers = providers.providers || {};
    }catch(_){ PIPELINE.providers = {}; }
  }
  PIPELINE.graph = graph || pipelineLocalRead(assetId) || pipelineBlankGraph(assetId);
  PIPELINE.selected = PIPELINE.graph.nodes[0] && PIPELINE.graph.nodes[0].id || null;
}

async function pipelineCreateTemplate(template){
  if(pipelineBridgeReady()){
    try{
      const result = await pipelineApi('pipeline/graph/template', {assetId:PIPELINE.assetId, template});
      PIPELINE.graph = result.graph;
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
      const result = await pipelineApi('pipeline/graph/save', {assetId:PIPELINE.assetId, graph:PIPELINE.graph});
      PIPELINE.graph = result.graph;
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
  const nodeX = Number.isFinite(x) ? Math.max(0, x - PIPELINE_NODE_WIDTH / 2) : 100 + (index % 4) * 280;
  const nodeY = Number.isFinite(y) ? Math.max(0, y - 70) : 100 + Math.floor(index / 4) * 190;
  PIPELINE.graph.nodes.push({id, type, x:nodeX, y:nodeY, params:{}});
  PIPELINE.selected = id;
  pipelineSave().catch(error => toast(error.message));
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
  const state=node&&node.result&&node.result.providerTask&&node.result.providerTask.state;
  if(state==='queued'||state==='running'){toast('Provider 任务尚在运行，当前不能取消或删除这个节点');return;}
  PIPELINE.graph.nodes=PIPELINE.graph.nodes.filter(node=>node.id!==nodeId);
  PIPELINE.graph.edges=PIPELINE.graph.edges.filter(edge=>edge.from!==nodeId&&edge.to!==nodeId);
  PIPELINE.selected=PIPELINE.graph.nodes[0]&&PIPELINE.graph.nodes[0].id||null;
  pipelineSave().catch(error=>toast(error.message));
}

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
      node.x=Math.max(0,baseX+(next.clientX-startX)/PIPELINE.zoom);
      node.y=Math.max(0,baseY+(next.clientY-startY)/PIPELINE.zoom);
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
  return PIPELINE.graph.edges.map(edge => `<path d="${pipelineEdgePath(edge)}"/>`).join('');
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
  meta.textContent = ` · graph rev ${PIPELINE.graph.revision||0} · ${PIPELINE.graph.nodes.length} 节点 / ${PIPELINE.graph.edges.length} 连线 · 存储 ${PIPELINE.source==='bridge'?'Bridge 项目目录':'浏览器本地'} · manifest ${manifest}`;
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
  const zoomer = document.querySelector('.pipeline-zoomer');
  const canvas = document.querySelector('.pipeline-canvas');
  if(!zoomer || !canvas) return;
  const width = canvas.offsetWidth || 1700;
  const height = canvas.offsetHeight || 650;
  canvas.style.transform = `scale(${PIPELINE.zoom})`;
  zoomer.style.width = (width * PIPELINE.zoom) + 'px';
  zoomer.style.height = (height * PIPELINE.zoom) + 'px';
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
  const rect = canvas.getBoundingClientRect();
  const localX = (event.clientX - rect.left) / PIPELINE.zoom;
  const localY = (event.clientY - rect.top) / PIPELINE.zoom;
  PIPELINE.zoom = next;
  pipelineApplyZoom();
  const base = scroll.getBoundingClientRect();
  scroll.scrollLeft = localX * next - (event.clientX - base.left);
  scroll.scrollTop = localY * next - (event.clientY - base.top);
}

function pipelinePanCanvas(scroll){
  scroll.addEventListener('contextmenu', event => event.preventDefault());
  scroll.addEventListener('wheel', pipelineWheel, {passive:false});
  scroll.addEventListener('pointerdown', event => {
    if(event.button !== 2) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const baseLeft = scroll.scrollLeft;
    const baseTop = scroll.scrollTop;
    scroll.classList.add('panning');
    scroll.setPointerCapture(event.pointerId);
    const move = next => {
      scroll.scrollLeft = baseLeft - (next.clientX - startX);
      scroll.scrollTop = baseTop - (next.clientY - startY);
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

function pipelineAssetTarget(){
  if(typeof S === 'undefined') return null;
  const machine = (S.machines || []).find(item => item.id === PIPELINE.assetId);
  if(machine) return {kind:'machine', machine};
  const item = (S.items || []).find(value => value.id === PIPELINE.assetId);
  if(item) return {kind:'item', item};
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
  if(node.type === 'lod') return (output.levels || []).map(level => 'L' + level.level + ' ' + level.parts + ' 件').join(' / ');
  if(node.type === 'collision') return (output.size || []).join('×') + ' m';
  if(node.type === 'animation') return output.parts + ' 件' + (output.kinds && output.kinds.length ? ' · ' + output.kinds.join('、') : '');
  if(node.type === 'metadata') return (output.formats || []).join(' / ');
  return '';
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

async function pipelineRun(nodeId, through){
  if(PIPELINE.busy) return;
  if(!pipelineBridgeReady()){ pipelineRunLocal(nodeId, through); return; }
  pipelineDeriveLocalStages();
  try{
    const saved = await pipelineApi('pipeline/graph/save', {assetId:PIPELINE.assetId, graph:PIPELINE.graph});
    PIPELINE.graph = saved.graph;
    PIPELINE.source = 'bridge';
  }catch(_){ pipelineRunLocal(nodeId, through); return; }
  PIPELINE.busy = true;
  renderPipelineView();
  try{
    const result = await pipelineApi('pipeline/run', {assetId:PIPELINE.assetId,nodeId,through:!!through});
    PIPELINE.graph = result.graph;
    const blocked = PIPELINE.graph.nodes.filter(node => node.result && node.result.state === 'blocked').length;
    toast(blocked ? '本地步骤已执行；远程生成/GLB 校验等待 Provider 或模型输入' : '流水线步骤已执行');
  }catch(error){toast(error.message);}
  PIPELINE.busy = false;
  renderPipelineView();
}

async function pipelineSubmitRemote(nodeId){
  const node=PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  if(!node || !['textToImage','imageTo3D'].includes(node.type)) return;
  if(!pipelineBridgeReady()){toast('远程提交需要 Bridge 在线并绑定项目');return;}
  if(!PIPELINE.providers.tripo || !PIPELINE.providers.tripo.configured){toast('先在 tools/bridge_config.json 配置 Tripo API key');return;}
  const estimated=node.type==='textToImage'?5:(node.params.texture?40:30);
  if(!window.confirm(`此操作会调用 Tripo，当前公开价目估算约 ${estimated} credits（$${(estimated/100).toFixed(2)}）；最终以任务实耗为准。现在提交？`)) return;
  try{
    await pipelineSave();
    const result=await pipelineApi('pipeline/provider/submit',{assetId:PIPELINE.assetId,nodeId,confirmRemote:true});
    PIPELINE.graph=result.graph;
    toast('已提交 Tripo 任务：'+result.taskId);
    renderPipelineView();
  }catch(error){toast(error.message);}
}

async function pipelinePollRemote(nodeId){
  if(!pipelineBridgeReady()){toast('查询远程任务需要 Bridge 在线并绑定项目');return;}
  try{
    const result=await pipelineApi('pipeline/provider/poll',{assetId:PIPELINE.assetId,nodeId});
    PIPELINE.graph=result.graph;
    toast('Tripo 状态：'+result.task.state+(result.task.progress!=null?' · '+result.task.progress+'%':''));
    renderPipelineView();
  }catch(error){toast(error.message);}
}

function pipelineNodeCard(node){
  const state = node.result && node.result.providerTask && node.result.providerTask.state || node.result && node.result.state || 'dirty';
  const selected = PIPELINE.selected === node.id;
  const params = node.type === 'prompt'
    ? `<textarea data-param="text" rows="3" placeholder="输入模型描述词">${pipelineEscape(node.params.text || '')}</textarea>`
    : `<label>参数 <input data-param="json" value="${pipelineEscape(JSON.stringify(node.params || {}))}"></label>`;
  const taskOutput=node.result&&node.result.providerTask&&node.result.providerTask.output||node.result&&node.result.output||{};
  const outputFile=taskOutput.modelPath||taskOutput.imagePath;
  const outputLink=outputFile&&pipelineBridgeReady()?`<a class="pipeline-output" href="/api/pipeline/output/${encodeURIComponent(PIPELINE.assetId)}/${encodeURIComponent(outputFile.split('/').pop())}" download>下载输出</a>`:'';
  const history=(node.result&&node.result.history||[]).map(item=>`<small>旧版本 ${pipelineEscape(item.taskId)} ${pipelineEscape(item.output&&item.output.modelPath||item.output&&item.output.imagePath||'')}</small>`).join('');
  const stageSummary=pipelineStageSummary(node);
  const inPorts=pipelinePorts(node.type,'in').map(port=>`<span class="pipeline-port pipeline-port-in" data-in-node="${pipelineEscape(node.id)}" data-in-port="${pipelineEscape(port)}" title="输入 ${pipelineEscape(port)}" style="top:${pipelinePortTop(node.type,'in',port)}px"></span>`).join('');
  const outPorts=pipelinePorts(node.type,'out').map(port=>`<span class="pipeline-port pipeline-port-out" data-out-node="${pipelineEscape(node.id)}" data-out-port="${pipelineEscape(port)}" title="输出 ${pipelineEscape(port)} · 拖到下游输入端" style="top:${pipelinePortTop(node.type,'out',port)}px"></span>`).join('');
  return `<article class="pipeline-node ${selected?'selected':''}" data-node="${pipelineEscape(node.id)}" style="left:${Number(node.x)||0}px;top:${Number(node.y)||0}px">
    ${inPorts}${outPorts}
    <header><b>${pipelineEscape(PIPELINE_NODE_LABELS[node.type] || node.type)}</b><span>${pipelineEscape(state)}</span></header>
    <small>${pipelineEscape(node.id)}${node.result&&node.result.providerTask&&node.result.providerTask.progress!=null?' · '+node.result.providerTask.progress+'%':''}</small>${params}${stageSummary?`<small class="pipeline-stage">${pipelineEscape(stageSummary)}</small>`:''}
    <div class="pipeline-node-actions"><button data-run="${pipelineEscape(node.id)}">运行</button><button data-through="${pipelineEscape(node.id)}">运行到此</button>${['textToImage','imageTo3D'].includes(node.type)?`<button data-remote="${pipelineEscape(node.id)}">远程提交</button>${node.result&&node.result.providerTask?`<button data-poll="${pipelineEscape(node.id)}">查询任务</button>`:''}`:''}<button data-delete-node="${pipelineEscape(node.id)}">删除</button></div>${outputLink}${history}
    ${node.result && node.result.error?`<small class="pipeline-error">${pipelineEscape(node.result.error)}</small>`:''}
  </article>`;
}

function renderPipelineView(){
  const view=document.getElementById('view');
  if(!view) return;
  const oldScroll=document.querySelector('.pipeline-scroll');
  const keepScroll=oldScroll?{left:oldScroll.scrollLeft,top:oldScroll.scrollTop}:null;
  const bridgeReady=pipelineBridgeReady();
  const candidates=[...S.machines.map(machine=>({id:machine.id,name:machine.name,kind:'machine'})),...S.items.map(item=>({id:item.id,name:item.name,kind:'item'}))];
  if(!candidates.length){view.innerHTML='<div class="card"><p>当前没有可建立流水线的机器或物品。</p></div>';return;}
  if(!PIPELINE.assetId && candidates[0]) PIPELINE.assetId=candidates[0].id;
  if(!PIPELINE.graph){
    view.innerHTML='<div class="card"><p>正在读取资产流水线…</p></div>';
    pipelineLoad(PIPELINE.assetId).then(renderPipelineView).catch(error=>{view.innerHTML=`<div class="card">${pipelineEscape(error.message)}</div>`;});
    return;
  }
  const providerNames=Object.keys(PIPELINE.providers||{});
  const selected=candidates.find(item=>item.id===PIPELINE.assetId);
  const machine= S.machines.find(item=>item.id===PIPELINE.assetId);
  const item= S.items.find(value=>value.id===PIPELINE.assetId);
  const promptNode=PIPELINE.graph.nodes.find(node=>node.type==='prompt');
  if(promptNode && !promptNode.params.text && machine && typeof machinePrompt==='function') promptNode.params.text=machinePrompt(machine,{withTech:true});
  if(promptNode && !promptNode.params.text && item && typeof itemPrompt==='function') promptNode.params.text=itemPrompt(item,{withTech:true});
  const edgeSvg=pipelineEdgeSvg();
  view.innerHTML=`<div class="pipeline-toolbar card">
    <div class="pt-field"><label for="pipelineAsset">资产</label>
      <select id="pipelineAsset">${candidates.map(item=>`<option value="${pipelineEscape(item.id)}" ${item.id===PIPELINE.assetId?'selected':''}>${pipelineEscape(item.name)} · ${pipelineEscape(item.id)}</option>`).join('')}</select></div>
    <div class="pt-field"><label for="pipelineTemplate">模板</label>
      <select id="pipelineTemplate">${PIPELINE_TEMPLATES.map(template=>`<option value="${template.id}">${template.label}</option>`).join('')}</select></div>
    <div class="pt-btns">
      <button id="pipelineMake">新建模板</button><button id="pipelineEstimate">批量预估</button><button id="pipelineArrange">自动布局</button><button id="pipelineSave">保存图</button><button id="pipelineZoomReset" title="滚轮缩放 · 按住右键拖动平移 · 点击复位">100%</button><button id="pipelineRunAll" class="primary">运行全部（本地节点）</button>
    </div>
    <div class="pt-note">
      <span>远程 Provider：${bridgeReady
        ? (providerNames.map(name=>`${pipelineEscape(name)} ${PIPELINE.providers[name].configured?'已配置':'未配置'}`).join(' · ')||'未配置')
        : 'Bridge 未连接（离线只能编辑与运行本地步骤）'}</span>
      ${bridgeReady
        ? '<span>远程任务需逐次确认；额度预估按当前公开价目，最终以任务实耗为准。</span>'
        : '<span>图保存在本机浏览器；启动 Bridge 并绑定项目后，同一资产自动改用项目目录里的图。</span>'}
    </div>
  </div>
  <div class="pipeline-shell"><aside class="pipeline-palette"><b>节点</b>${Object.entries(PIPELINE_NODE_LABELS).map(([type,label])=>`<button data-add="${type}">${label}</button>`).join('')}</aside>
  <div class="pipeline-scroll"><div class="pipeline-zoomer"><div class="pipeline-canvas" style="width:${Math.max(1700,...PIPELINE.graph.nodes.map(node=>(Number(node.x)||0)+260))}px;height:${Math.max(650,...PIPELINE.graph.nodes.map(node=>(Number(node.y)||0)+210))}px"><svg>${edgeSvg}</svg>${PIPELINE.graph.nodes.map(pipelineNodeCard).join('')}</div></div></div></div>
  <div class="card"><b>${pipelineEscape(selected&&selected.name||PIPELINE.assetId)}</b><span id="pipelineMeta"></span>
  <div style="font-family:var(--mono);font-size:10.5px;color:var(--text-3);margin-top:4px">工作区：${pipelineEscape(bridgeReady&&SYNC.status.project.root ? SYNC.status.project.root+'/Forgeworks' : '未绑定（浏览器本地）')}</div>
  <div class="pipeline-ports-hint">拖动节点两侧圆点连线：左侧输入端口各保留一条连线（新连线替换旧的），右侧输出可同时接多个下游；拖动中按 Esc 取消。滚轮缩放，按住右键拖动平移，工具条上的百分比按钮复位视角。</div>
  <div class="pipeline-edge-list">${PIPELINE.graph.edges.map((edge,index)=>`<span>${pipelineEscape(edge.from)}.${pipelineEscape(edge.out)} → ${pipelineEscape(edge.to)}.${pipelineEscape(edge.in)} <button data-remove-edge="${index}">断开</button></span>`).join('')}</div></div>`;
  document.getElementById('pipelineAsset').onchange=async event=>{PIPELINE.graph=null;await pipelineLoad(event.target.value);renderPipelineView();};
  document.getElementById('pipelineMake').onclick=()=>pipelineCreateTemplate(document.getElementById('pipelineTemplate').value).catch(error=>toast(error.message));
  document.getElementById('pipelineEstimate').onclick=()=>{const kind=document.getElementById('pipelineTemplate').value;const count=kind==='machine'?S.machines.length:S.items.length;const estimate=pipelineEstimate(kind,count);toast(`${estimate.assets} 个资产：约 ${estimate.lowCredits}–${estimate.highCredits} credits（$${estimate.lowUsd.toFixed(2)}–$${estimate.highUsd.toFixed(2)}）；以任务实际实耗为准`);};
  document.getElementById('pipelineSave').onclick=()=>pipelineSave().catch(error=>toast(error.message));
  document.getElementById('pipelineArrange').onclick=pipelineArrange;
  document.getElementById('pipelineZoomReset').onclick=()=>{
    PIPELINE.zoom=1;
    pipelineApplyZoom();
    const scroll=view.querySelector('.pipeline-scroll');
    if(scroll){scroll.scrollLeft=0;scroll.scrollTop=0;}
  };
  document.getElementById('pipelineRunAll').onclick=()=>pipelineRun(null,false);
  view.querySelectorAll('[data-add]').forEach(button=>button.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;
    event.preventDefault();
    pipelineStartPaletteDrag(button,event);
  }));
  view.querySelectorAll('[data-node]').forEach(card=>{
    pipelineDragCard(card);
    card.onclick=event=>{
      if(event.target.closest('button,select,input,textarea,.pipeline-port')) return;
      if(PIPELINE.selected===card.dataset.node) return;
      PIPELINE.selected=card.dataset.node;
      view.querySelectorAll('.pipeline-node').forEach(item=>item.classList.toggle('selected',item.dataset.node===PIPELINE.selected));
    };
  });
  pipelineWirePorts(view);
  const scroll=view.querySelector('.pipeline-scroll');
  if(scroll){
    pipelinePanCanvas(scroll);
    pipelineApplyZoom();
    if(keepScroll){scroll.scrollLeft=keepScroll.left;scroll.scrollTop=keepScroll.top;}
  }
  pipelinePaintMeta();
  view.querySelectorAll('[data-run]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRun(button.dataset.run,false);});
  view.querySelectorAll('[data-through]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRun(button.dataset.through,true);});
  view.querySelectorAll('[data-remote]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineSubmitRemote(button.dataset.remote);});
  view.querySelectorAll('[data-poll]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelinePollRemote(button.dataset.poll);});
  view.querySelectorAll('[data-remove-edge]').forEach(button=>button.onclick=()=>pipelineRemoveEdge(Number(button.dataset.removeEdge)));
  view.querySelectorAll('[data-delete-node]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRemoveNode(button.dataset.deleteNode);});
  view.querySelectorAll('[data-param="text"]').forEach(input=>input.onchange=()=>{const node=PIPELINE.graph.nodes.find(item=>item.id===input.closest('[data-node]').dataset.node);if(node){node.params.text=input.value;pipelineSave({quiet:true}).catch(error=>toast(error.message));}});
  view.querySelectorAll('[data-param="json"]').forEach(input=>input.onchange=()=>{const node=PIPELINE.graph.nodes.find(item=>item.id===input.closest('[data-node]').dataset.node);try{node.params=JSON.parse(input.value);pipelineSave({quiet:true}).catch(error=>toast(error.message));}catch(_){toast('参数必须是合法 JSON');}});
}
