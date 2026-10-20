/* Forgeworks · js/views/eras.js */
/* ---------- 纪元 ---------- */
function renderEras(){
  const v=document.getElementById('view');
  v.innerHTML=tableHTML([
    {t:'纪元',w:'80px',f:r=>`<span class="pill">${r.id}</span>`},
    {t:'名称',w:'110px',f:r=>r.name},
    {t:'新增元素',f:r=>r.elements.map(e=>{
      const el=S.elements.find(x=>x.id===e);
      return el?`<span class="pill"><span class="swatch" style="background:${el.color};margin-right:4px"></span>${el.name}</span>`:`<span style="color:var(--red)">${e}</span>`;
    }).join(' ')||'—'},
    {t:'星球类型',w:'170px',f:r=>r.planets},
    {t:'代表机器',w:'200px',f:r=>r.machines},
    {t:'已实现配方',w:'120px',f:r=>{
      const n=S.recipes.filter(rc=>rc.unlock===r.id).length;
      return `<span class="pill">${n} 条</span>`;
    }},
  ], S.eras);
  bindRows(v, i=>openEditor('eras', S.eras[i].id));
  addBtn('+ 新增纪元');
}
