/* Forgeworks · js/views/machines.js */
/* ---------- 机器 ---------- */

/**
 * 机器列表。
 *
 * 交互设计：
 *   - 点击任意一行 → 直接弹出该机器的 3D 预览（最主要的用途）
 *   - 行尾「编辑」按钮 → 打开参数编辑弹窗
 *   按钮必须 stopPropagation，否则会同时触发行点击把 3D 弹窗顶掉。
 */
function renderMachines(){
  const v=document.getElementById('view');
  v.innerHTML=tableHTML([
    {t:'ID',w:'150px',f:r=>`<code>${r.id}</code>`},
    {t:'名称',w:'130px',f:r=>r.name},
    {t:'分类',w:'80px',f:r=>`<span class="pill">${r.cat}</span>`},
    {t:'纪元',w:'72px',f:r=>tierTag(r.tier)},
    {t:'占地',w:'66px',f:r=>`<code>${r.footprint}</code>`},
    {t:'耗电kW',w:'78px',f:r=>`<code>${r.power}</code>`},
    {t:'可执行配方',w:'100px',f:r=>{
      const n=S.recipes.filter(rc=>rc.machine===r.id).length;
      return n?`<span class="pill">${n} 条</span>`:'<span style="color:var(--red)">无</span>';
    }},
    {t:'说明',f:r=>`<span style="color:var(--text-2)">${r.desc||''}</span>`},
    {t:'操作',w:'96px',f:r=>
      `<button class="sm" data-m3d="${r.id}" title="查看 3D 预览">3D</button>
       <button class="sm" data-medit="${r.id}" title="编辑参数">编辑</button>`},
  ], S.machines);

  // 行点击 → 3D 预览
  bindRows(v, i=>open3DViewer(S.machines[i].id));

  // 行内按钮（阻止冒泡，避免触发上面的行点击）
  v.querySelectorAll('[data-m3d]').forEach(function(b){
    b.onclick = function(e){ e.stopPropagation(); open3DViewer(b.dataset.m3d); };
  });
  v.querySelectorAll('[data-medit]').forEach(function(b){
    b.onclick = function(e){ e.stopPropagation(); openEditor('machines', b.dataset.medit); };
  });

  // 提示条
  const hint = document.createElement('div');
  hint.style.cssText = 'margin-top:10px;font-size:11.5px;color:var(--text-3)';
  hint.textContent = '点击任意一行查看该机器的 3D 预览；点「编辑」修改参数。';
  v.appendChild(hint);

  addBtn('+ 新增机器');
}
