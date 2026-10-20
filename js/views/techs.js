/* Forgeworks · js/views/techs.js */
/* ---------- 科技 ---------- */
function renderTechs(){
  const v=document.getElementById('view');
  const byTier={};
  S.techs.forEach(t=>{(byTier[t.tier]=byTier[t.tier]||[]).push(t)});
  let h='';
  Object.keys(byTier).sort().forEach(t=>{
    h+=`<div style="margin:14px 0 8px">${tierTag(t)}</div>`;
    h+=tableHTML([
      {t:'ID',w:'130px',f:r=>`<code>${r.id}</code>`},
      {t:'科技',w:'140px',f:r=>r.name},
      {t:'成本',w:'80px',f:r=>`<code>${r.cost}</code>`},
      {t:'前置',f:r=>r.prereqs.map(p=>`<span class="pill">${S.techs.find(x=>x.id===p)?.name||p}</span>`).join(' ')||'—'},
      {t:'解锁配方',f:r=>r.unlocks.map(u=>`<span class="pill" style="background:var(--accent-soft);color:#0f6e56">${recipeById(u)?.name||u}</span>`).join(' ')||'—'},
      {t:'说明',f:r=>`<span style="color:var(--text-2)">${r.desc||''}</span>`},
    ], byTier[t]);
  });
  v.innerHTML=h;
  const tables=v.querySelectorAll('.tbl-wrap');
  let ti=0; const flat=[];
  Object.keys(byTier).sort().forEach(t=>byTier[t].forEach(x=>flat.push(x)));
  tables.forEach(tb=>{ tb.querySelectorAll('tbody tr').forEach(tr=>{
    const t=flat[ti++]; tr.onclick=()=>openEditor('techs', t.id);
  });});
  addBtn('+ 新增科技');
}
