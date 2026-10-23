/* Forgeworks · js/views/machines.js */
/* ---------- 机器 ---------- */

/**
 * 机器列表。
 *
 * 交互设计：
 *   - 点击任意一行 → 直接弹出该机器的 3D 预览（最主要的用途）
 *   - 行尾「编辑」按钮 → 打开参数编辑弹窗
 *   按钮必须 stopPropagation，否则会同时触发行点击把 3D 弹窗顶掉。
 *   - 「同步」列只在 Bridge 在线时显示（sync-design F3 的导出标记）
 */
function renderMachines(){
  const v=document.getElementById('view');
  const showSync = SYNC.online && SYNC.status && SYNC.status.project;

  const cols = [
    {t:'图标',w:'54px',f:r=>isoPreview(r, 0, 40)},
    {t:'ID',w:'150px',f:r=>`<code>${r.id}</code>`},
    {t:'名称',w:'130px',f:r=>r.name},
    {t:'分类',w:'80px',f:r=>`<span class="pill">${r.cat}</span>`},
    {t:'等级',w:'72px',f:r=>tierTag(r.tier)},
    {t:'占地',w:'66px',f:r=>`<code>${r.footprint}</code>`},
    {t:'耗电kW',w:'78px',f:r=>`<code>${r.power}</code>`},
    {t:'可执行配方',w:'100px',f:r=>{
      const n=S.recipes.filter(rc=>rc.machine===r.id).length;
      return n?`<span class="pill">${n} 条</span>`:'<span style="color:var(--red)">无</span>';
    }},
  ];
  if(showSync){
    cols.push({t:'同步',w:'104px',f:r=>syncStateTag(machineSyncState(r).state)});
    cols.push({t:'UE 导入',w:'90px',f:r=>{
      const ue = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[r.id]
        && SYNC.manifest.assets[r.id].ue;
      if(!ue) return '<span style="color:var(--text-3)">未导入</span>';
      const currentMesh = (((SYNC.manifest.assets[r.id].files || {}).mesh || [])[0] || {}).sha1;
      const current = !ue.sourceSha1 || ue.sourceSha1 === currentMesh;
      return `<span class="pill" style="color:${current?'var(--accent)':'var(--amber)'}">${current?'已导入':'源已更新'}</span>`;
    }});
  }
  cols.push(
    {t:'说明',f:r=>`<span style="color:var(--text-2)">${r.desc||''}</span>`},
    {t:'操作',w:'96px',f:r=>
      `<button class="sm" data-m3d="${r.id}" title="查看 3D 预览">3D</button>
       <button class="sm" data-medit3d="${r.id}" title="编辑 3D 部件">部件</button>
       <button class="sm" data-medit="${r.id}" title="编辑参数">编辑</button>`},
  );

  v.innerHTML=tableHTML(cols, S.machines);

  // 行点击 → 3D 预览
  bindRows(v, i=>open3DViewer(S.machines[i].id));

  // 行内按钮（阻止冒泡，避免触发上面的行点击）
  v.querySelectorAll('[data-m3d]').forEach(function(b){
    b.onclick = function(e){ e.stopPropagation(); open3DViewer(b.dataset.m3d); };
  });
  v.querySelectorAll('[data-medit]').forEach(function(b){
    b.onclick = function(e){ e.stopPropagation(); openEditor('machines', b.dataset.medit); };
  });
  v.querySelectorAll('[data-medit3d]').forEach(function(b){
    b.onclick = function(e){ e.stopPropagation(); open3DEditor(b.dataset.medit3d); };
  });

  // 同步状态汇总条（Bridge 在线且已绑定时）
  if(showSync){
    const counts = syncSummary();
    const total = S.machines.length;
    const chips = Object.keys(counts).map(k=>{
      const m = SYNC_STATE_META[k] || { label:k, color:'var(--text-3)' };
      return `<span class="pill" style="color:${m.color}">${m.label} ${counts[k]}</span>`;
    }).join(' ');
    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;'
      + 'margin-top:10px;padding:9px 12px;background:var(--panel-2);'
      + 'border:1px solid var(--border);border-radius:8px;font-size:11.5px';
    bar.innerHTML = `<span>${total} 个资产：${chips}</span>`
      + `<button class="sm" id="mcGoSync" style="margin-left:auto">去同步页导出</button>`;
    v.appendChild(bar);
    const go = document.getElementById('mcGoSync');
    if(go) go.onclick = function(){ cur='sync'; render(); };
  }

  // 提示条
  const hint = document.createElement('div');
  hint.style.cssText = 'margin-top:10px;font-size:11.5px;color:var(--text-3)';
  hint.textContent = '点击任意一行查看该机器的 3D 预览；点「编辑」修改参数。';
  v.appendChild(hint);

  addBtn('+ 新增机器');
}
