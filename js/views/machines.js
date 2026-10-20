/* Forgeworks · js/views/machines.js */
/* ---------- 机器 ---------- */
function renderMachines(){
  const v=document.getElementById('view');
  v.innerHTML=tableHTML([
    {t:'ID',w:'150px',f:r=>`<code>${r.id}</code>`},
    {t:'名称',w:'140px',f:r=>r.name},
    {t:'分类',w:'90px',f:r=>`<span class="pill">${r.cat}</span>`},
    {t:'纪元',w:'80px',f:r=>tierTag(r.tier)},
    {t:'占地',w:'70px',f:r=>`<code>${r.footprint}</code>`},
    {t:'耗电kW',w:'80px',f:r=>`<code>${r.power}</code>`},
    {t:'可执行配方',w:'110px',f:r=>{
      const n=S.recipes.filter(rc=>rc.machine===r.id).length;
      return n?`<span class="pill">${n} 条</span>`:'<span style="color:var(--red)">无</span>';
    }},
    {t:'说明',f:r=>`<span style="color:var(--text-2)">${r.desc||''}</span>`},
  ], S.machines);
  bindRows(v, i=>openEditor('machines', S.machines[i].id));
  addBtn('+ 新增机器');
}
