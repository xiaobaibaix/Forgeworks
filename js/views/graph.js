/* Forgeworks · js/views/graph.js */
/* ---------- 依赖图谱 ---------- */
function renderGraph(){
  const v=document.getElementById('view');
  const tierColor=t=>({0:'#9fe1cb',1:'#85b7eb',2:'#ef9f27',3:'#a3b1c4',4:'#7f77dd',5:'#e24b4a'}[t]||'#b4b2a9');
  // 计算每个物品的层级（最长路径深度）
  const depth={};
  const producers={};
  S.recipes.forEach(r=>r.outputs.filter(o=>o.amount>0).forEach(o=>{
    (producers[o.item]=producers[o.item]||[]).push(r);
  }));
  const visiting=new Set();
  function d(item){
    if(depth[item]!==undefined) return depth[item];
    if(visiting.has(item)) return 0;
    visiting.add(item);
    const ps=producers[item]||[];
    let mx=0;
    ps.forEach(r=>r.inputs.forEach(i=>{ mx=Math.max(mx, d(i.item)+1); }));
    visiting.delete(item);
    depth[item]=mx;
    return mx;
  }
  S.items.forEach(i=>d(i.id));
  const maxD=Math.max(...Object.values(depth),0);
  // 分层
  const layers={};
  S.items.forEach(i=>{ (layers[depth[i.id]]=layers[depth[i.id]]||[]).push(i); });
  let h=`<div class="card"><h3>T0 → T5 生产链深度图</h3>
    <p class="hint">按「最长上游路径」自动分层。左侧为原料，右侧为最终宏构。箭头方向 = 消耗 → 产出。</p></div>`;
  h+='<div class="chart-box"><div style="display:flex;gap:14px;align-items:flex-start">';
  Object.keys(layers).sort((a,b)=>a-b).forEach(L=>{
    h+=`<div style="flex:1;min-width:120px"><div style="font-size:10.5px;color:var(--text-3);text-align:center;margin-bottom:8px">层 ${L}</div>`;
    layers[L].forEach(it=>{
      h+=`<div style="background:${tierColor(it.tier)}22;border:1px solid ${tierColor(it.tier)};border-radius:6px;
        padding:4px 7px;margin-bottom:4px;font-size:11px;display:flex;align-items:center;gap:5px">
        <span class="swatch" style="background:${it.color};width:8px;height:8px;margin:0"></span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${it.name}</span></div>`;
    });
    h+='</div>';
  });
  h+='</div></div>';
  // 统计
  h+=`<div class="grid2" style="margin-top:14px">
    <div class="card"><h3>压缩比分析</h3><p class="hint">物流压力 = 原料流量 / 成品流量</p>
      <table><tbody>
      <tr><td>原料层总物品数</td><td><code>${(layers[0]||[]).length}</code></td></tr>
      <tr><td>最终层物品数</td><td><code>${(layers[maxD]||[]).length}</code></td></tr>
      <tr><td>生产链总深度</td><td><code>${maxD} 层</code></td></tr>
      <tr><td>最长单链物品数</td><td><code>${maxD+1}</code></td></tr>
      </tbody></table></div>
    <div class="card"><h3>配比健康度</h3><p class="hint">每个物品的产出/消耗比</p>
      <div class="scroll-x"><table><thead><tr><th>物品</th><th>产出配方</th><th>被消耗</th><th>状态</th></tr></thead><tbody>`;
  S.items.forEach(it=>{
    const np=(producers[it.id]||[]).length;
    const nc=S.recipes.filter(r=>r.inputs.some(i=>i.item===it.id)).length;
    let st='<span class="pill" style="background:var(--accent-soft);color:#0f6e56">平衡</span>';
    if(np===0 && nc===0) st='<span class="pill" style="background:var(--red-soft);color:#a32d2d">孤立</span>';
    else if(np===0 && nc>0) st='<span class="pill" style="background:var(--red-soft);color:#a32d2d">无来源</span>';
    else if(np>1) st='<span class="pill" style="background:var(--blue-soft);color:#185fa5">多分支</span>';
    h+=`<tr><td>${it.name}</td><td><code>${np}</code></td><td><code>${nc}</code></td><td>${st}</td></tr>`;
  });
  h+='</tbody></table></div></div>';
  v.innerHTML=h;
}
