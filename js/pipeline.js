const PIPELINE = {assetId:null, graph:null, providers:{}, selected:null, busy:false, source:'local'};
const PIPELINE_STORE_PREFIX = 'fw.pipeline.';

const PIPELINE_NODE_LABELS = {
  prompt:'描述词', textToImage:'概念图生成', imageTo3D:'图生 3D', decimate:'减面',
  styleApply:'风格对齐', validate:'质量门禁', manualEdit:'人工精修', variant:'变体', export:'导出', imageExport:'图标导出'
};

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
    {id:'prompt', type:'prompt', x:80, y:100, params:{text:''}},
    {id:'image', type:'textToImage', x:340, y:100, params:{provider:'tripo'}},
    {id:'model', type:'imageTo3D', x:600, y:100, params:{provider:'tripo', texture:false}},
    {id:'style', type:'styleApply', x:860, y:100, params:{}},
    {id:'validate', type:'validate', x:1120, y:100, params:{maxTriangles:20000}},
    {id:'export', type:'export', x:1380, y:100, params:{}},
  ];
  let edges = [
    {from:'prompt', out:'text', to:'image', in:'text'},
    {from:'image', out:'image', to:'model', in:'image'},
    {from:'model', out:'mesh', to:'style', in:'mesh'},
    {from:'style', out:'mesh', to:'validate', in:'mesh'},
    {from:'validate', out:'report', to:'export', in:'report'},
    {from:'style', out:'mesh', to:'export', in:'mesh'},
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

async function pipelineSave(){
  if(pipelineBridgeReady()){
    try{
      const result = await pipelineApi('pipeline/graph/save', {assetId:PIPELINE.assetId, graph:PIPELINE.graph});
      PIPELINE.graph = result.graph;
      PIPELINE.source = 'bridge';
      renderPipelineView();
      return;
    }catch(error){ toast('Bridge 保存失败，改存浏览器本地：' + error.message); }
  }
  pipelineBump(PIPELINE.graph);
  PIPELINE.source = 'local';
  if(!pipelineLocalWrite(PIPELINE.assetId, PIPELINE.graph)) toast('浏览器本地存储不可用，改动不会被保存');
  renderPipelineView();
}

function pipelineAddNode(type){
  if(!PIPELINE.graph || !PIPELINE_NODE_LABELS[type]) return;
  let index = 1;
  while(PIPELINE.graph.nodes.some(node=>node.id===type+'_'+index)) index++;
  const id = type + '_' + index;
  PIPELINE.graph.nodes.push({id, type, x:100 + (index % 4) * 280, y:100 + Math.floor(index / 4) * 190, params:{}});
  PIPELINE.selected = id;
  pipelineSave().catch(error => toast(error.message));
}

function pipelineConnect(sourceId, targetId){
  const source = PIPELINE.graph.nodes.find(node => node.id === sourceId);
  const target = PIPELINE.graph.nodes.find(node => node.id === targetId);
  if(!source || !target) return;
  const out = {prompt:['text'],textToImage:['image'],imageTo3D:['mesh'],decimate:['mesh'],styleApply:['mesh'],manualEdit:['mesh'],variant:['mesh'],validate:['report']}[source.type] || [];
  const input = {textToImage:['text'],imageTo3D:['image'],decimate:['mesh'],styleApply:['mesh'],validate:['mesh'],manualEdit:['mesh'],variant:['mesh'],export:['mesh','report'],imageExport:['image']}[target.type] || [];
  const common = out.find(port => input.includes(port));
  if(!common){toast('两个节点没有兼容的端口');return;}
  PIPELINE.graph.edges = PIPELINE.graph.edges.filter(edge => !(edge.from === sourceId && edge.to === targetId && edge.out === common));
  PIPELINE.graph.edges.push({from:sourceId,out:common,to:targetId,in:common});
  pipelineSave().catch(error => toast(error.message));
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
  pipelineSave().catch(error=>toast(error.message));
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
    header.setPointerCapture(event.pointerId);
    const move=next=>{node.x=Math.max(0,baseX+next.clientX-startX);node.y=Math.max(0,baseY+next.clientY-startY);card.style.left=node.x+'px';card.style.top=node.y+'px';pipelinePaintEdges();};
    const end=()=>{header.removeEventListener('pointermove',move);header.removeEventListener('pointerup',end);pipelineSave().catch(error=>toast(error.message));};
    header.addEventListener('pointermove',move);header.addEventListener('pointerup',end,{once:true});
  };
}

function pipelinePaintEdges(){
  const svg=document.querySelector('.pipeline-canvas>svg');
  if(!svg)return;
  svg.innerHTML=PIPELINE.graph.edges.map(edge=>{
    const from=PIPELINE.graph.nodes.find(node=>node.id===edge.from),to=PIPELINE.graph.nodes.find(node=>node.id===edge.to);
    if(!from||!to)return '';
    const x1=(Number(from.x)||0)+230,y1=(Number(from.y)||0)+75,x2=Number(to.x)||0,y2=(Number(to.y)||0)+75;
    return `<path d="M${x1} ${y1} C${x1+70} ${y1},${x2-70} ${y2},${x2} ${y2}"/>`;
  }).join('');
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
    if(node.type === 'prompt'){
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
  if(PIPELINE.source !== 'bridge'){
    try{
      const saved = await pipelineApi('pipeline/graph/save', {assetId:PIPELINE.assetId, graph:PIPELINE.graph});
      PIPELINE.graph = saved.graph;
      PIPELINE.source = 'bridge';
    }catch(_){ pipelineRunLocal(nodeId, through); return; }
  }
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
  return `<article class="pipeline-node ${selected?'selected':''}" data-node="${pipelineEscape(node.id)}" style="left:${Number(node.x)||0}px;top:${Number(node.y)||0}px">
    <header><b>${pipelineEscape(PIPELINE_NODE_LABELS[node.type] || node.type)}</b><span>${pipelineEscape(state)}</span></header>
    <small>${pipelineEscape(node.id)}${node.result&&node.result.providerTask&&node.result.providerTask.progress!=null?' · '+node.result.providerTask.progress+'%':''}</small>${params}
    <div class="pipeline-node-actions"><button data-run="${pipelineEscape(node.id)}">运行</button><button data-through="${pipelineEscape(node.id)}">运行到此</button>${['textToImage','imageTo3D'].includes(node.type)?`<button data-remote="${pipelineEscape(node.id)}">远程提交</button>${node.result&&node.result.providerTask?`<button data-poll="${pipelineEscape(node.id)}">查询任务</button>`:''}`:''}<button data-delete-node="${pipelineEscape(node.id)}">删除</button></div>
    <div class="pipeline-ports"><select data-connect-from="${pipelineEscape(node.id)}"><option value="">连接到…</option>${PIPELINE.graph.nodes.filter(other=>other.id!==node.id).map(other=>`<option value="${pipelineEscape(other.id)}">${pipelineEscape(PIPELINE_NODE_LABELS[other.type])} · ${pipelineEscape(other.id)}</option>`).join('')}</select></div>${outputLink}${history}
    ${node.result && node.result.error?`<small class="pipeline-error">${pipelineEscape(node.result.error)}</small>`:''}
  </article>`;
}

function renderPipelineView(){
  const view=document.getElementById('view');
  if(!view) return;
  const bridgeReady=pipelineBridgeReady();
  const assets=(SYNC.manifest && SYNC.manifest.assets)||{};
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
  const edgeSvg=PIPELINE.graph.edges.map(edge=>{
    const from=PIPELINE.graph.nodes.find(node=>node.id===edge.from), to=PIPELINE.graph.nodes.find(node=>node.id===edge.to);
    if(!from||!to)return '';
    const x1=(Number(from.x)||0)+225,y1=(Number(from.y)||0)+75,x2=Number(to.x)||0,y2=(Number(to.y)||0)+75;
    return `<path d="M${x1} ${y1} C${x1+70} ${y1},${x2-70} ${y2},${x2} ${y2}"/>`;
  }).join('');
  view.innerHTML=`<div class="pipeline-toolbar card">
    <div class="pt-field"><label for="pipelineAsset">资产</label>
      <select id="pipelineAsset">${candidates.map(item=>`<option value="${pipelineEscape(item.id)}" ${item.id===PIPELINE.assetId?'selected':''}>${pipelineEscape(item.name)} · ${pipelineEscape(item.id)}</option>`).join('')}</select></div>
    <div class="pt-field"><label for="pipelineTemplate">模板</label>
      <select id="pipelineTemplate">${PIPELINE_TEMPLATES.map(template=>`<option value="${template.id}">${template.label}</option>`).join('')}</select></div>
    <div class="pt-btns">
      <button id="pipelineMake">新建模板</button><button id="pipelineEstimate">批量预估</button><button id="pipelineArrange">自动布局</button><button id="pipelineSave">保存图</button><button id="pipelineRunAll" class="primary">运行全部（本地节点）</button>
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
  <div class="pipeline-scroll"><div class="pipeline-canvas" style="width:${Math.max(1700,...PIPELINE.graph.nodes.map(node=>(Number(node.x)||0)+260))}px;height:${Math.max(650,...PIPELINE.graph.nodes.map(node=>(Number(node.y)||0)+210))}px"><svg>${edgeSvg}</svg>${PIPELINE.graph.nodes.map(pipelineNodeCard).join('')}</div></div></div>
  <div class="card"><b>${pipelineEscape(selected&&selected.name||PIPELINE.assetId)}</b> · graph rev ${PIPELINE.graph.revision||0} · ${PIPELINE.graph.nodes.length} 节点 / ${PIPELINE.graph.edges.length} 连线 · 存储 ${PIPELINE.source==='bridge'?'Bridge 项目目录':'浏览器本地'} · manifest ${pipelineEscape(assets[PIPELINE.assetId]&&assets[PIPELINE.assetId].state||'未导出')}
  <div style="font-family:var(--mono);font-size:10.5px;color:var(--text-3);margin-top:4px">工作区：${pipelineEscape(bridgeReady&&SYNC.status.project.root ? SYNC.status.project.root+'/Forgeworks' : '未绑定（浏览器本地）')}</div>
  <div class="pipeline-edge-list">${PIPELINE.graph.edges.map((edge,index)=>`<span>${pipelineEscape(edge.from)}.${pipelineEscape(edge.out)} → ${pipelineEscape(edge.to)}.${pipelineEscape(edge.in)} <button data-remove-edge="${index}">断开</button></span>`).join('')}</div></div>`;
  document.getElementById('pipelineAsset').onchange=async event=>{PIPELINE.graph=null;await pipelineLoad(event.target.value);renderPipelineView();};
  document.getElementById('pipelineMake').onclick=()=>pipelineCreateTemplate(document.getElementById('pipelineTemplate').value).catch(error=>toast(error.message));
  document.getElementById('pipelineEstimate').onclick=()=>{const kind=document.getElementById('pipelineTemplate').value;const count=kind==='machine'?S.machines.length:S.items.length;const estimate=pipelineEstimate(kind,count);toast(`${estimate.assets} 个资产：约 ${estimate.lowCredits}–${estimate.highCredits} credits（$${estimate.lowUsd.toFixed(2)}–$${estimate.highUsd.toFixed(2)}）；以任务实际实耗为准`);};
  document.getElementById('pipelineSave').onclick=()=>pipelineSave().catch(error=>toast(error.message));
  document.getElementById('pipelineArrange').onclick=pipelineArrange;
  document.getElementById('pipelineRunAll').onclick=()=>pipelineRun(null,false);
  view.querySelectorAll('[data-add]').forEach(button=>button.onclick=()=>pipelineAddNode(button.dataset.add));
  view.querySelectorAll('[data-node]').forEach(card=>{pipelineDragCard(card);card.onclick=event=>{if(!event.target.closest('button,select,input,textarea')&&PIPELINE.selected!==card.dataset.node){PIPELINE.selected=card.dataset.node;renderPipelineView();}};});
  view.querySelectorAll('[data-run]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRun(button.dataset.run,false);});
  view.querySelectorAll('[data-through]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRun(button.dataset.through,true);});
  view.querySelectorAll('[data-remote]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineSubmitRemote(button.dataset.remote);});
  view.querySelectorAll('[data-poll]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelinePollRemote(button.dataset.poll);});
  view.querySelectorAll('[data-remove-edge]').forEach(button=>button.onclick=()=>pipelineRemoveEdge(Number(button.dataset.removeEdge)));
  view.querySelectorAll('[data-delete-node]').forEach(button=>button.onclick=event=>{event.stopPropagation();pipelineRemoveNode(button.dataset.deleteNode);});
  view.querySelectorAll('[data-connect-from]').forEach(select=>select.onchange=()=>{if(select.value)pipelineConnect(select.dataset.connectFrom,select.value);});
  view.querySelectorAll('[data-param="text"]').forEach(input=>input.onchange=()=>{const node=PIPELINE.graph.nodes.find(item=>item.id===input.closest('[data-node]').dataset.node);if(node){node.params.text=input.value;pipelineSave().catch(error=>toast(error.message));}});
  view.querySelectorAll('[data-param="json"]').forEach(input=>input.onchange=()=>{const node=PIPELINE.graph.nodes.find(item=>item.id===input.closest('[data-node]').dataset.node);try{node.params=JSON.parse(input.value);pipelineSave().catch(error=>toast(error.message));}catch(_){toast('参数必须是合法 JSON');}});
}
