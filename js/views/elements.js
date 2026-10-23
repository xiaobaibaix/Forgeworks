/* Forgeworks · js/views/elements.js */
/* ---------- 元素 ---------- */
function renderElements(){
  const v=document.getElementById('view');
  v.innerHTML = tableHTML([
    {t:'图标',w:'46px',f:r=>elementIconHTML(r, 24)},
    {t:'颜色',w:'60px',f:r=>`<span class="swatch" style="background:${r.color}"></span>`},
    {t:'ID',w:'90px',f:r=>`<code>${r.id}</code>`},
    {t:'名称',f:r=>r.name},
    {t:'符号',w:'80px',f:r=>r.symbol},
    {t:'等级',w:'100px',f:r=>tierTag(r.tier)},
    {t:'用于',f:r=>{
      const uses=S.recipes.filter(rc=>rc.inputs.some(i=>i.item===r.id)).length;
      return uses?`<span class="pill">${uses} 条配方</span>`:'<span style="color:var(--text-3)">未使用</span>';
    }},
  ], S.elements);
  bindRows(v, i=>openEditor('elements', S.elements[i].id));
  addBtn('+ 新增元素');
}
