/* Forgeworks · js/ui/table.js */
/* ---------- 通用表格 ---------- */
function tableHTML(cols, rows){
  let h='<div class="tbl-wrap scroll-x"><table><thead><tr>'+
    cols.map(c=>`<th style="${c.w?`width:${c.w}`:''}">${c.t}</th>`).join('')+'</tr></thead><tbody>';
  rows.forEach((r,i)=>{
    h+=`<tr data-i="${i}">`+cols.map(c=>`<td>${c.f(r)}</td>`).join('')+'</tr>';
  });
  return h+'</tbody></table></div>';
}
function bindRows(container, onClick){
  container.querySelectorAll('tbody tr').forEach(tr=>{
    tr.onclick=()=>onClick(+tr.dataset.i);
  });
}
function tierTag(t){ return `<span class="tag t${t}">T${t}</span>`; }
function typeLabel(t){
  return {raw:'原料',concentrate:'精矿',ingot:'锭/气体',part:'零件',material:'材料',
          module:'模块',mega:'宏构',byproduct:'副产物',fluid:'流体'}[t]||t;
}
function addBtn(label){
  const b=document.createElement('button');
  b.className='primary'; b.textContent=label;
  b.onclick=()=>openEditor(cur);
  document.getElementById('headActions').appendChild(b);
  return b;
}
