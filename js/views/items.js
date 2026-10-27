/* Forgeworks · js/views/items.js */
/* ---------- 物品 ---------- */
function renderItems(){
  const v=document.getElementById('view');
  if(!S.items.length){
    v.innerHTML = emptyHint('当前项目还没有物品。');
    addBtn('+ 新增物品');
    return;
  }
  const byTier = {};
  S.items.forEach(it=>{(byTier[it.tier]=byTier[it.tier]||[]).push(it)});
  let h='';
  Object.keys(byTier).sort().forEach(t=>{
    h+=`<div style="margin-bottom:8px;display:flex;align-items:center;gap:8px">
      ${tierTag(t)}<span style="font-size:12px;color:var(--text-2)">${byTier[t].length} 项</span></div>`;
    h+=tableHTML([
      {t:'图标',w:'46px',f:r=>iconHTML(r, 24)},
      {t:'ID',w:'150px',f:r=>`<code>${r.id}</code>`},
      {t:'名称',w:'130px',f:r=>r.name},
      {t:'类型',w:'80px',f:r=>`<span class="pill">${typeLabel(r.type)}</span>`},
      {t:'价值',w:'65px',f:r=>`<code>${r.value}</code>`},
      {t:'原料成本',w:'95px',f:r=>{
        // 原料类型永远显示"原料"，不计算自指成本
        if(r.type==='raw') return `<span style="color:var(--text-3)">原料</span>`;
        const produced = S.recipes.some(rc=>rc.outputs.some(o=>o.amount>0&&o.item===r.id));
        if(!produced) return `<span style="color:var(--text-3)">—</span>`;
        const u = unitCost(r.id);
        const tot = Object.values(u.raws).reduce((s,v)=>s+v,0);
        if(!(tot>0)) return `<span style="color:var(--text-3)">—</span>`;
        // 性价比 = 价值 / 原料件数，偏离太多说明数值可能失衡
        const ratio = r.value>0 ? r.value/tot : 0;
        const warn = ratio>0 && (ratio>10 || ratio<0.2);
        return `<code style="${warn?'color:var(--amber)':''}">${fmtNum(tot)}</code>`+
               `<span style="font-size:10.5px;color:var(--text-3)"> /价${fmtNum(ratio)}</span>`;
      }},
      {t:'说明',f:r=>`<span style="color:var(--text-2)">${r.desc||''}</span>`},
    ], byTier[t]);
  });
  v.innerHTML=h;
  // 逐表绑定
  const tables=v.querySelectorAll('.tbl-wrap');
  let ti=0;
  const flat=[];
  Object.keys(byTier).sort().forEach(t=>byTier[t].forEach(it=>flat.push(it)));
  tables.forEach(tb=>{
    tb.querySelectorAll('tbody tr').forEach(tr=>{
      const it=flat[ti++];
      tr.onclick=()=>openEditor('items', it.id);
    });
  });
  addBtn('+ 新增物品');
}
