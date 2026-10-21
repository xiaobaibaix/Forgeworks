/* Forgeworks · js/views/recipes.js */
/* ---------- 配方 ---------- */
function renderRecipes(){
  const v=document.getElementById('view');
  const byCat={};
  S.recipes.forEach(r=>{(byCat[r.cat]=byCat[r.cat]||[]).push(r)});
  let h='';
  Object.keys(byCat).forEach(c=>{
    h+=`<div style="margin:14px 0 8px;display:flex;align-items:center;gap:8px">
      <span class="pill" style="font-size:11px">${c}</span>
      <span style="font-size:12px;color:var(--text-2)">${byCat[c].length} 条</span></div>`;
    h+=tableHTML([
      {t:'ID',w:'150px',f:r=>`<code>${r.id}</code>`},
      {t:'配方',w:'130px',f:r=>r.name},
      {t:'机器',w:'120px',f:r=>`<span class="pill">${machineOf(r.machine)?.name||'<span style="color:var(--red)">缺失</span>'}</span>`},
      {t:'输入',f:r=>r.inputs.map(i=>`<span class="pill">${itemOf(i.item)?.name||i.item} ×${i.amount}</span>`).join(' ') || '—'},
      {t:'输出',f:r=>r.outputs.filter(o=>o.amount>0).map(o=>`<span class="pill" style="background:var(--accent-soft);color:#0f6e56">${itemOf(o.item)?.name||o.item} ×${o.amount}</span>`).join(' ') || '—'},
      {t:'周期',w:'65px',f:r=>`<code>${r.cycle}s</code>`},
      {t:'速率',w:'90px',f:r=>{
        const outAmt=r.outputs.filter(o=>o.amount>0).reduce((s,o)=>s+o.amount,0);
        return outAmt?`<code>${(outAmt*60/r.cycle).toFixed(1)}/min</code>`:'—';
      }},
      {t:'耗电',w:'80px',f:r=>`<code>${r.power}kW</code>`},
    ], byCat[c]);
  });
  v.innerHTML=h;
  const tables=v.querySelectorAll('.tbl-wrap');
  let ti=0; const flat=[];
  Object.keys(byCat).forEach(c=>byCat[c].forEach(r=>flat.push(r)));
  tables.forEach(tb=>{
    tb.querySelectorAll('tbody tr').forEach(tr=>{
      const r=flat[ti++]; tr.onclick=()=>openEditor('recipes', r.id);
    });
  });
  addBtn('+ 新增配方');
}
