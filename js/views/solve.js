/* Forgeworks · js/views/solve.js */
/* ---------- 求解器 ---------- */
function renderSolve(){
  const v=document.getElementById('view');
  const opts=S.items.map(i=>`<option value="${i.id}">${i.name} (T${i.tier})</option>`).join('');
  v.innerHTML=`
  <div class="card">
    <h3>产线求解器</h3>
    <p class="hint">选定目标物品与目标速率，递归展开完整生产链，计算每级所需机器数、总耗电，并检测循环依赖。</p>
    <div class="row" style="max-width:760px">
      <div class="field" style="margin:0"><label>目标物品</label><select id="svTarget">${opts}</select></div>
      <div class="field" style="margin:0;flex:0 0 130px"><label>目标速率（个/分）</label><input id="svRate" type="number" value="10" min="0.1" step="1"></div>
      <div class="field" style="margin:0;flex:0 0 auto;display:flex;align-items:flex-end"><button class="primary" id="svRun">求解</button></div>
    </div>
  </div>
  <div id="svOut"></div>`;
  document.getElementById('svRun').onclick=runSolve;
  document.getElementById('svTarget').value='MOD_AUTOMATION';
  document.getElementById('svRate').value=10;
  runSolve();
}
function runSolve(){
  const out=document.getElementById('svOut');
  const t=document.getElementById('svTarget');
  const rate=parseFloat(document.getElementById('svRate').value)||0;
  if(rate<=0){ out.innerHTML=''; return; }
  const res=solve(t.value, rate);
  let h='';
  // 多分支配方选择器
  const branchItems = [...new Set(res.tree.map(n=>{
    const prods=S.recipes.filter(r=>r.outputs.some(o=>o.amount>0&&o.item===n.recipe.outputs.find(oo=>oo.item).item));
    return n.recipe.outputs.find(o=>o.amount>0)?.item;
  }).filter(Boolean))];
  const multi = S.items.filter(it=>{
    const n=S.recipes.filter(r=>r.outputs.some(o=>o.amount>0&&o.item===it.id)).length;
    return n>1 && branchItems.includes(it.id);
  });
  if(multi.length){
    h+=`<div class="card"><h3>分支配方选择</h3>
      <p class="hint">这些物品有多种产出配方。指定用哪条，产线会按你的选择展开（不指定则自动选速率最高的）。</p>
      <div class="row" style="flex-wrap:wrap;gap:10px">`;
    multi.forEach(it=>{
      const prods=S.recipes.filter(r=>r.outputs.some(o=>o.amount>0&&o.item===it.id));
      h+=`<div class="field" style="margin:0;min-width:220px;flex:1"><label>${it.name}</label>
        <select data-ovr="${it.id}"><option value="">（自动）</option>
        ${prods.map(p=>{ const outAmt=p.outputs.filter(o=>o.amount>0).reduce((s,o)=>s+o.amount,0);
          return `<option value="${p.id}" ${SOLVE_OVERRIDES[it.id]===p.id?'selected':''}>${p.name} · ${(outAmt*60/p.cycle).toFixed(1)}/分</option>`;
        }).join('')}</select></div>`;
    });
    h+=`</div></div>`;
  }
  // 汇总表
  const rows=Object.values(res.byRecipe).sort((a,b)=>b.rate-a.rate);
  h+=`<div class="card"><h3>产线汇总</h3>
    <p class="hint">目标：${itemOf(t)?.name} ${rate}/分 · 共 ${rows.length} 种配方 · 总耗电 <strong>${res.totalPower.toFixed(0)} kW</strong></p>
    <div class="scroll-x"><table>
    <thead><tr><th>配方</th><th>机器</th><th>速率(个/分)</th><th>机器数</th><th>耗电(kW)</th><th>周期</th></tr></thead><tbody>`;
  rows.forEach(r=>{
    h+=`<tr><td>${r.recipe.name}</td><td>${machineOf(r.recipe.machine)?.name||'?'}</td>
      <td><code>${r.rate.toFixed(2)}</code></td><td><code>${r.machines}</code></td>
      <td><code>${r.power.toFixed(0)}</code></td><td><code>${r.recipe.cycle}s</code></td></tr>`;
  });
  h+=`</tbody></table></div></div>`;
  // 树
  h+=`<div class="card"><h3>生产链结构</h3><p class="hint">点击展开/折叠。括号内为该节点机器数。</p><div class="tree" id="svTree"></div></div>`;
  if(res.issues.length){
    h+=`<div class="card"><h3>求解提示</h3>`;
    res.issues.forEach(i=>{ h+=`<div class="issue ${i.lv}"><span class="ic">${i.lv==='err'?'✕':'!'}</span><div>${i.msg}</div></div>`; });
    h+='</div>';
  }
  out.innerHTML=h;
  // 分支配方：改变即重算
  out.querySelectorAll('[data-ovr]').forEach(sel=>{
    sel.onchange=()=>{
      const id=sel.dataset.ovr;
      if(sel.value) SOLVE_OVERRIDES[id]=sel.value; else delete SOLVE_OVERRIDES[id];
      runSolve();
    };
  });
  // 渲染树
  const treeEl=document.getElementById('svTree');
  function node(n){
    if(!n) return '';
    const r=n.recipe;
    const kids=n.kids.map(node).join('');
    const hasKids=n.kids.length>0;
    return `<details class="tierbox" ${n.depth<2?'open':''}>
      <summary><span class="tn-target">${r.name}</span>
        <span class="tn-mach">×${n.machines} ${machineOf(r.machine)?.name||''}</span>
        <span class="tn-rate">${n.rate.toFixed(2)}/分</span>
        <span class="tn-cycle">${r.cycle}s</span>
        <span class="pill">${r.power}kW/台</span></summary>
      <div class="inner">${hasKids?kids:'<div style="color:var(--text-3);font-size:11px">原料（无上游配方）</div>'}</div>
    </details>`;
  }
  treeEl.innerHTML=res.root?node(res.root):'<div class="empty">无解</div>';
}
