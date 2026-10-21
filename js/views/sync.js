/* Forgeworks · js/views/sync.js
   ============================================================
   同步面板 —— 项目绑定 / 导出 / 状态核对 / 事件日志
   ------------------------------------------------------------
   这是「同步」系统的操作中心（设计：docs/sync-design.md §7.2）。
   Bridge 不在线时显示启动指引，所有功能优雅降级。
   ============================================================ */

let _syncBusy = false;

function syncEscape(value){
  return String(value == null ? '' : value).replace(/[&<>"']/g, c=>({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  })[c]);
}

function _syncRecentHTML(proj){
  const recent = (SYNC.projects && SYNC.projects.recent) || [];
  if(!recent.length) return '';
  const current = proj && proj.root;
  return `<div style="margin-top:14px;border-top:1px solid var(--border);padding-top:10px">
    <div style="font-size:11px;color:var(--text-3);margin-bottom:4px">最近项目</div>
    ${recent.map(item=>`<div style="display:flex;align-items:center;gap:8px;padding:4px 0">
      <button class="sm" data-recent="${syncEscape(item.root)}" ${item.exists === false ? 'disabled' : ''}>${item.root === current ? '当前' : '打开'}</button>
      <div style="min-width:0;flex:1">
        <div style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${syncEscape(item.name || item.root)} <span class="pill">${item.kind === 'ue' ? 'UE' : '工作区'}</span>${item.exists === false ? ' <span style="color:var(--red);font-size:10.5px">目录不存在</span>' : ''}</div>
        <div style="font-family:var(--mono);font-size:10.5px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${syncEscape(item.root)}</div>
      </div></div>`).join('')}
  </div>`;
}

function renderSync(){
  const v = document.getElementById('view');
  const on = SYNC.online;
  const st = SYNC.status || {};
  const proj = st.project;

  v.innerHTML = `
    <div class="card">
      <h3>Forge Bridge</h3>
      ${on ? `
        <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px;margin-top:8px">
          <div>Bridge <strong>v${syncEscape(st.bridge || '?')}</strong> <span style="color:var(--accent)">在线</span></div>
          <div>Blender ${st.blender && st.blender.found
            ? `<strong>${syncEscape(st.blender.version || '')}</strong> <span style="color:var(--accent)">可用</span>
               <span style="color:var(--text-3);font-size:10.5px">${syncEscape(st.blender.path)}</span>`
            : '<span style="color:var(--text-3)">未找到（校验/缩略图功能降级）</span>'}</div>
        </div>
      ` : `
        <div class="issue warn" style="margin-top:8px"><span class="ic">!</span><div>
          Bridge 不在线。同步功能需要它（浏览器自身无法写项目目录、无法调 Blender）。<br>
          启动方式：<code>python3 tools/bridge.py</code>（在 Forgeworks 目录下），
          然后刷新本页。不想同步时，工具其余功能不受影响。
        </div></div>
      `}
    </div>

    ${on ? `
    <div class="card">
      <h3>项目绑定</h3>
      ${proj && proj.root ? `
        <div style="font-size:12px;margin-top:6px">
          已绑定：<strong>${syncEscape(proj.name || '未命名项目')}</strong>
          <span class="pill">${proj.kind === 'ue' ? 'UE 项目' : '工作区'}</span>
          <div style="font-family:var(--mono);font-size:11px;color:var(--text-2);margin-top:2px">${syncEscape(proj.root)}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:4px">
            工作区：<code>${syncEscape(proj.root)}/Forgeworks/</code>（_Source 中间文件 + _Sync 清单，不进 Content/）
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <button id="syRescan">重新扫描目录</button>
          <button id="syUnbind">解除绑定</button>
          <button id="syPick">切换文件夹…</button>
        </div>
      ` : `
        <p class="hint">选择任意文件夹作为工作区；含 <code>.uproject</code> 的目录会自动识别为 UE 项目。
        Bridge 会在里面创建 <code>Forgeworks/</code>：_Source 放中间文件（GLB/图标/元数据），_Sync 放同步清单。</p>
        <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
          <button class="primary" id="syPick">选择文件夹并绑定…</button>
        </div>
        <div style="display:flex;gap:8px;margin-top:8px">
          <input id="syPath" placeholder="/path/to/project（也可以直接输入路径）" spellcheck="false"
                 style="flex:1;font-family:var(--mono);font-size:12px">
          <button id="syBind">绑定</button>
        </div>
        <div id="syBindErr" style="color:var(--red);font-size:11.5px;margin-top:6px"></div>
      `}
      ${_syncRecentHTML(proj)}
    </div>

    ${proj ? `
    <div class="card">
      <h3>资产导出</h3>
      <p class="hint">
        导出会把每个机器的 GLB（含风格材质）+ 等轴测预览写进
        <code>_Source/Machines/&lt;ID&gt;/</code>，并记录三把 hash 用于判断「待更新」。
        导出前会做质量门禁（三角面 vs 风格规格）。
      </p>
      <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
        <button class="primary" id="syExportAll" ${_syncBusy ? 'disabled' : ''}>
          导出全部机器（${S.machines.length}）</button>
        <button id="syExportStale" ${_syncBusy ? 'disabled' : ''}>只导出待更新/缺失</button>
        <button id="syReScan2">核对磁盘状态</button>
      </div>
      <div id="syProgress" style="font-size:11.5px;color:var(--text-2);margin-top:8px"></div>
      <div id="sySummary" style="margin-top:10px"></div>
    </div>

    <div class="card">
      <h3>资产明细</h3>
      <div id="syTable" style="margin-top:6px"></div>
    </div>

    <div class="card">
      <h3>外部修改冲突 <span class="pill">${SYNC.conflicts.length}</span></h3>
      <div id="syConflicts"></div>
    </div>

    <div class="card">
      <h3>Unreal Engine 资产</h3>
      <p class="hint">在 UE 5.8.3 编辑器 Python 控制台运行 <code>ue/fw_sync.py</code> 导入 GLB；再运行 <code>ue/fw_registry.py</code> 刷新 AssetRegistry 快照。UE 不可用时可先完成其余设计工作。</p>
      <div style="display:flex;gap:8px;align-items:center;margin:8px 0">
        <button id="syUERefresh">刷新 UE 资产</button>
        <span style="font-size:11px;color:var(--text-3)">${SYNC.ueAssets.length} 个 UE StaticMesh</span>
      </div>
      <div id="syUETable"></div>
    </div>
    ` : ''}
    ` : ''}

    ${SYNC.log.length ? `
    <div class="card">
      <h3>操作日志</h3>
      <div id="syLog" style="font-size:11.5px;margin-top:4px;
           max-height:180px;overflow:auto;font-family:var(--mono);line-height:1.9"></div>
    </div>` : ''}
  `;

  renderSyncSummary();
  renderSyncTable();
  renderSyncConflicts();
  renderSyncUETable();
  renderSyncLog();

  /* ---------- 绑定 ---------- */
  const bindBtn = document.getElementById('syBind');
  if(bindBtn) bindBtn.onclick = async ()=>{
    const p = document.getElementById('syPath').value.trim();
    if(!p){ document.getElementById('syBindErr').textContent = '请输入路径'; return; }
    bindBtn.disabled = true; bindBtn.textContent = '绑定中…';
    try{
      const r = await syncBindProject(p);
      if(!r.ok) document.getElementById('syBindErr').textContent = r.error || '绑定失败';
      else render();
    }catch(e){
      document.getElementById('syBindErr').textContent = '请求失败：' + e.message;
    }finally{ bindBtn.disabled = false; bindBtn.textContent = '绑定'; }
  };
  const un = document.getElementById('syUnbind');
  if(un) un.onclick = async ()=>{ await syncUnbindProject(); render(); };

  const pick = document.getElementById('syPick');
  if(pick) pick.onclick = async ()=>{
    const err = document.getElementById('syBindErr');
    const label = pick.textContent;
    pick.disabled = true; pick.textContent = '等待系统对话框…';
    try{
      const picked = await syncPickFolder();
      if(picked && picked.ok && picked.path){
        const r = await syncBindProject(picked.path);
        if(r && r.ok){ render(); return; }
        if(err) err.textContent = (r && r.error) || '绑定失败';
        else syncLog('绑定失败：' + ((r && r.error) || ''), 'warn');
      }else if(picked && !picked.cancelled && err){
        err.textContent = picked.error || '没有选择目录';
      }
    }catch(e){
      if(err) err.textContent = '选择失败：' + e.message;
      else syncLog('选择失败：' + e.message, 'warn');
    }finally{
      if(pick.isConnected){ pick.disabled = false; pick.textContent = label; }
    }
  };

  v.querySelectorAll('[data-recent]').forEach(button=>button.onclick = async ()=>{
    if(button.dataset.recent === (proj && proj.root)) return;
    button.disabled = true;
    try{
      const r = await syncBindProject(button.dataset.recent);
      if(!r || !r.ok) syncLog('打开项目失败：' + ((r && r.error) || '未知错误'), 'warn');
    }catch(e){ syncLog('打开项目失败：' + e.message, 'warn'); }
    render();
  });

  const resc = document.getElementById('syRescan') || document.getElementById('syReScan2');
  if(resc) resc.onclick = async ()=>{
    resc.disabled = true;
    try{
      const r = await syncScan();
      if(r && r.report){
        const bad = Object.keys(r.report).filter(k=>r.report[k]!=='exported');
        syncLog(bad.length ? '核对：' + bad.length + ' 个资产异常（' + bad.join(', ') + '）' : '核对：全部正常', bad.length?'warn':'ok');
      }
      render();
    }catch(e){ syncLog('核对失败：'+e.message,'warn'); render(); }
  };
  const ueRefresh = document.getElementById('syUERefresh');
  if(ueRefresh) ueRefresh.onclick = async ()=>{
    ueRefresh.disabled = true;
    await syncLoadUEAssets();
    render();
  };

  /* ---------- 导出 ---------- */
  const ea = document.getElementById('syExportAll');
  if(ea) ea.onclick = ()=>_doExport(S.machines.map(m=>m.id));
  const es = document.getElementById('syExportStale');
  if(es) es.onclick = ()=>{
    const ids = S.machines.filter(m=>{
      const s = machineSyncState(m).state;
      return s === 'stale' || s === 'missing' || s === 'tampered' || s === 'none';
    }).map(m=>m.id);
    if(!ids.length){ toast('没有需要导出的资产'); return; }
    _doExport(ids);
  };
}

function renderSyncConflicts(){
  const el = document.getElementById('syConflicts');
  if(!el) return;
  if(!SYNC.conflicts.length){ el.innerHTML = '<span class="hint">没有待裁决的外部修改。Bridge 每 1.5 秒检查一次已导出文件。</span>'; return; }
  el.innerHTML = SYNC.conflicts.map(conflict=>`<div style="padding:9px 0;border-bottom:1px solid var(--border)">
    <div><strong>${syncEscape(conflict.id)}</strong> · <code>${syncEscape(conflict.path)}</code> · ${syncEscape(conflict.createdAt)}</div>
    <div style="display:flex;gap:6px;margin-top:7px;flex-wrap:wrap">
      <button class="sm" data-conflict="${syncEscape(conflict.id)}" data-choice="keep-tool" ${conflict.toolAvailable?'':'disabled title="旧版未保存工具副本"'}>保留工具版本</button>
      <button class="sm" data-conflict="${syncEscape(conflict.id)}" data-choice="keep-disk">采纳磁盘版本</button>
      <button class="sm" data-conflict="${syncEscape(conflict.id)}" data-choice="save-copy">另存磁盘副本</button>
    </div></div>`).join('');
  el.querySelectorAll('[data-conflict]').forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    const conflict=SYNC.conflicts.find(item=>item.id===button.dataset.conflict);
    try{
      const result=await syncResolveConflict(conflict,button.dataset.choice);
      if(!result.ok) throw new Error(result.error||'裁决失败');
      syncLog('冲突已处理：'+conflict.id+'（'+button.dataset.choice+'）','ok');
    }catch(error){ syncLog('冲突处理失败：'+error.message,'warn'); }
    await syncLoadManifest(); await syncLoadConflicts(); render();
  });
}

function renderSyncUETable(){
  const el = document.getElementById('syUETable');
  if(!el) return;
  const rows = SYNC.ueAssets.map(asset=>{
    const machine = S.machines.find(item=>item.id === asset.id);
    const exported = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[asset.id];
    const designSize = exported && exported.meta && exported.meta.sizeCm;
    const bounds = asset.bounds || {};
    const ueSize = [bounds.x, bounds.y, bounds.z].map(value=>Number(value || 0));
    const delta = designSize && designSize.length === 3
      ? ueSize.map((value, index)=>Math.round(value - Number(designSize[index])))
      : null;
    const size = ueSize.map(value=>syncEscape(Math.round(value))).join('×');
    const difference = delta ? ` <span style="color:${delta.some(value=>Math.abs(value)>2)?'var(--amber)':'var(--text-3)'}">(${delta.map(value=>value>0?'+':'').join('×')} cm)</span>` : '';
    return {id:asset.id, name:machine?machine.name:'外部资产', size, difference, triangles:asset.triangles, objectPath:asset.objectPath};
  });
  if(!rows.length){ el.innerHTML = '<span class="hint">尚无快照。导入或编辑资产后点击刷新。</span>'; return; }
  el.innerHTML = tableHTML([
    {t:'ID',w:'120px',f:r=>`<code>${syncEscape(r.id)}</code>`},
    {t:'设计资产',w:'110px',f:r=>syncEscape(r.name)},
    {t:'UE 尺寸(cm)',w:'130px',f:r=>`${r.size}${r.difference}`},
    {t:'三角面',w:'76px',f:r=>syncEscape(r.triangles)},
    {t:'UE 对象路径',f:r=>`<code>${syncEscape(r.objectPath)}</code>`},
  ], rows);
}

/* ---------- 导出执行 ---------- */

async function _doExport(ids){
  if(_syncBusy) return;
  _syncBusy = true;
  const prog = document.getElementById('syProgress');
  const btn = document.getElementById('syExportAll');
  if(btn){ btn.disabled = true; btn.textContent = '导出中…'; }
  let warn = 0, fail = 0;
  try{
    const rs = await syncExportAll(ids, (i, n, id)=>{
      if(prog) prog.textContent = id ? `正在导出 ${i+1}/${n}：${id}` : `完成 ${n} 个`;
    });
    rs.forEach(x=>{
      if(!x.r.ok) fail++;
      else if(x.r.gate && x.r.gate.over) warn++;
    });
    const msg = `导出完成：${rs.length - fail} 成功` +
      (warn ? `，${warn} 个超三角面预算` : '') + (fail ? `，${fail} 失败` : '');
    syncLog(msg, fail ? 'warn' : 'ok');
    toast(msg);
  }catch(e){
    syncLog('导出中断：' + e.message, 'warn');
    toast('导出中断：' + e.message);
  }finally{
    _syncBusy = false;
    render();   // 重绘（含进度清空与按钮恢复）
  }
}

/* ---------- 汇总条 ---------- */

function renderSyncSummary(){
  const el = document.getElementById('sySummary');
  if(!el) return;
  const counts = syncSummary();
  const parts = Object.keys(counts).map(k=>{
    const m = SYNC_STATE_META[k] || { label:k, color:'var(--text-3)' };
    return `<span class="pill" style="color:${m.color}">${m.label} ${counts[k]}</span>`;
  }).join(' ');
  const total = Object.keys(counts).reduce((a,k)=>a+counts[k],0);
  el.innerHTML = `<span style="font-size:12px">${total} 个资产：${parts}</span>`;
}

/* ---------- 明细表 ---------- */

function renderSyncTable(){
  const el = document.getElementById('syTable');
  if(!el) return;
  el.innerHTML = tableHTML([
    { t:'ID', w:'120px', f:r=>`<code>${syncEscape(r.m.id)}</code>` },
    { t:'名称', w:'110px', f:r=>syncEscape(r.m.name) },
    { t:'状态', w:'96px', f:r=>syncStateTag(r.s.state) },
    { t:'Blender', w:'90px', f:r=>{
        const b = r.s.rec && r.s.rec.meta && r.s.rec.meta.blender;
        if(b && b.state === 'ready'){
          const image = ((r.s.rec.files || {}).thumbnail || [])[0] || {};
          return `<img src="/api/thumbnail/machine/${encodeURIComponent(r.m.id)}?v=${syncEscape(image.sha1 || b.checkedAt || '')}"
                       alt="Blender 渲染缩略图" title="Blender 校验通过"
                       style="display:block;width:56px;height:56px;object-fit:contain;background:var(--panel-2);border:1px solid var(--border);border-radius:6px">`;
        }
        const labels = {queued:'排队中',processing:'处理中',failed:'校验失败',unavailable:'未启用'};
        return `<span style="font-size:10.5px;color:${b && b.state === 'failed'?'var(--red)':'var(--text-3)'}">${labels[b && b.state] || '—'}</span>`;
      }},
    { t:'三角面', w:'76px', f:r=>{
        const tri = r.s.rec && r.s.rec.meta && r.s.rec.meta.triangles;
        const bud = r.s.rec && r.s.rec.meta && r.s.rec.meta.triangleBudget || 900;
        return tri !== undefined
          ? `<span style="font-family:var(--mono);color:${tri>bud?'var(--amber)':'inherit'}">${syncEscape(tri)}</span>`
          : '<span style="color:var(--text-3)">—</span>';
      }},
    { t:'材质槽', w:'58px', f:r=>{
        const mm = r.s.rec && r.s.rec.meta && r.s.rec.meta.materials;
        return mm !== undefined ? syncEscape(mm) : '<span style="color:var(--text-3)">—</span>';
      }},
    { t:'尺寸(cm)', w:'90px', f:r=>{
        const sc = r.s.rec && r.s.rec.meta && r.s.rec.meta.sizeCm;
        return sc ? `<span style="font-family:var(--mono);font-size:10.5px">${syncEscape(sc[0])}×${syncEscape(sc[1])}×${syncEscape(sc[2])}</span>`
                  : '<span style="color:var(--text-3)">—</span>';
      }},
    { t:'风格', w:'110px', f:r=>{
        const sty = r.s.rec && r.s.rec.meta && r.s.rec.meta.style;
        return sty ? `<span class="pill">${syncEscape(sty.name || sty.presetId)}</span>` : '<span style="color:var(--text-3)">—</span>';
      }},
    { t:'导出时间', w:'96px', f:r=>{
        const t = r.s.rec && r.s.rec.exportedAt;
        return t ? `<span style="font-size:10.5px;color:var(--text-3)">${syncEscape(String(t).replace('T',' ').slice(5,16))}</span>`
                 : '<span style="color:var(--text-3)">—</span>';
      }},
    { t:'操作', w:'76px', f:r=>`<button class="sm" data-syex="${syncEscape(r.m.id)}" ${_syncBusy ? 'disabled' : ''}>${r.s.state==='exported'?'重导':'导出'}</button>` },
  ], S.machines.map(m=>({ m, s: machineSyncState(m) })));

  el.querySelectorAll('[data-syex]').forEach(b=>{
    b.onclick = async ()=>{
      _doExport([b.dataset.syex]);
    };
  });
}

/* ---------- 日志 ---------- */

function renderSyncLog(){
  const el = document.getElementById('syLog');
  if(!el) return;
  const color = { ok:'var(--accent)', warn:'var(--amber)', info:'var(--text-2)' };
  el.innerHTML = SYNC.log.map(l=>
    `<div><span style="color:var(--text-3)">${syncEscape(l.at)}</span>
     <span style="color:${color[l.level]||'inherit'}"> ${syncEscape(l.msg)}</span></div>`
  ).join('');
}
