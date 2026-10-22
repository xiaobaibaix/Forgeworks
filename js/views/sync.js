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
        <div style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${syncEscape(item.name || item.root)} <span class="pill">${item.kind === 'ue' ? 'UE' : 'Forgeworks'}</span>${item.exists === false ? ' <span style="color:var(--red);font-size:10.5px">目录不存在</span>' : ''}</div>
        <div style="font-family:var(--mono);font-size:10.5px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${syncEscape(item.root)}</div>
      </div></div>`).join('')}
  </div>`;
}

function syncUECardHTML(){
  const target = SYNC.status && SYNC.status.ueTarget;
  const manifest = SYNC.ueManifest;
  const counts = syncUESummary();
  const exportedCount = manifest && manifest.assets ? Object.keys(manifest.assets).length : 0;
  const publishedAt = manifest && manifest.publishedAt
    ? String(manifest.publishedAt).replace('T', ' ').slice(0, 16) : '';
  return `<div class="card">
    <h3>UE 导出目标</h3>
    ${target ? `
      <div style="font-size:12px;margin-top:6px">
        已设置：<strong>${syncEscape(target.name || target.root)}</strong>
        <span class="pill">${target.kind === 'ue' ? 'UE 项目' : '文件夹'}</span>
        <div style="font-family:var(--mono);font-size:11px;color:var(--text-2);margin-top:2px">${syncEscape(target.root)}</div>
        <div style="font-size:11px;color:var(--text-3);margin-top:4px">
          只复制 GLB 与清单到 <code>${syncEscape(target.forgeworksRoot || target.root + '/Forgeworks')}</code>；
          描述词、生成管线、预览等内部资料留在 Forgeworks 项目里。
        </div>
        <div style="font-size:11px;color:var(--text-3);margin-top:4px">
          UE 清单：${exportedCount} 个资产${publishedAt ? ' · 最近导出 ' + syncEscape(publishedAt) : ''}
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
        <button class="primary" id="syUEPublishAll" ${_syncBusy ? 'disabled' : ''}>
          导出全部机器（${S.machines.length}）</button>
        <button id="syUEPublishStale" ${_syncBusy ? 'disabled' : ''}>只导出待更新/未导出</button>
        <button id="syUERefreshManifest">刷新 UE 清单</button>
        <button id="syUETargetPick">更换目标…</button>
      </div>
      <div id="syUEProgress" style="font-size:11.5px;color:var(--text-2);margin-top:8px"></div>
      <div style="margin-top:8px;font-size:12px">
        已导出 ${counts.exported} · 待导出 ${counts.stale} · 未导出 ${counts.none}
      </div>
    ` : `
      <p class="hint">
        选择一个 UE 项目目录作为导出目标。导出时 Bridge 会把 GLB 与清单复制到
        <code>&lt;UE项目&gt;/Forgeworks/</code>，不会写入 Content/，也不会带出描述词与管线。
      </p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <input id="syUePath" placeholder="/path/to/YourUEProject（含 .uproject）" spellcheck="false"
               style="flex:1;min-width:200px;font-family:var(--mono);font-size:12px">
        <button class="primary" id="syUeSet">设置目标</button>
        <button id="syUePick">选择文件夹…</button>
      </div>
      <div id="syUeErr" style="color:var(--red);font-size:11.5px;margin-top:6px"></div>
    `}
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
          Bridge 不在线。同步需要本地服务（浏览器自身无法写项目目录、无法调 Blender）。
          不想同步时，工具其余功能不受影响。
        </div></div>
        <div class="setup-steps">
          <div class="setup-step"><span class="n">01</span><div>
            <b>启动 Bridge</b><p>在 Forgeworks 目录运行 <code>python3 tools/bridge.py</code>，然后刷新本页。</p>
          </div></div>
          <div class="setup-step"><span class="n">02</span><div>
            <b>新建或打开项目</b><p>Forgeworks 项目独立保存设计数据、描述词、管线与资源文件。</p>
          </div></div>
          <div class="setup-step"><span class="n">03</span><div>
            <b>导出到 UE</b><p>设置 UE 导出目标后，只把 GLB 和清单复制过去。</p>
          </div></div>
        </div>
      `}
    </div>

    ${on ? `
    <div class="card">
      <h3>Forgeworks 项目</h3>
      ${proj && proj.root ? `
        <div style="font-size:12px;margin-top:6px">
          已打开：<strong>${syncEscape(proj.name || '未命名项目')}</strong>
          <span class="pill">Forgeworks 项目</span>
          <div style="font-family:var(--mono);font-size:11px;color:var(--text-2);margin-top:2px">${syncEscape(proj.root)}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:4px">
            项目保存全部设计数据与生成资源（描述词、生成管线、预览、GLB 等）；
            UE 只接收导出的副本。内容：<code>project.json</code>，资源：<code>_Source/</code>，清单：<code>_Sync/</code>。
          </div>
          <div id="syContentState" style="font-size:11px;color:var(--text-3);margin-top:4px">
            ${SYNC.contentRoot === proj.root
              ? (SYNC.contentSavedAt
                  ? '项目内容已保存（' + syncEscape(new Date(SYNC.contentSavedAt).toLocaleTimeString('zh-CN')) + '）'
                  : (SYNC.content ? '已载入项目内容' : '项目尚无内容，保存后会写入'))
              : '正在载入项目内容…'}
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <button class="primary" id="sySaveProject">保存项目</button>
          <button id="syRescan">重新扫描目录</button>
          <button id="syPick">打开其他项目…</button>
          <button id="syUnbind">关闭项目</button>
        </div>
      ` : `
        <p class="hint">
          Forgeworks 项目是一个独立的资源工程：设计数据、描述词、生成管线、贴图和导出的 GLB 都保存在项目目录里。
          UE 项目只是导出目标，不会收到描述词、管线等内部资料。
        </p>
        <div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-top:10px">
          <div style="font-size:12px;font-weight:600;margin-bottom:6px">新建项目</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <input id="syNewParent" placeholder="父目录，例如 /Users/you/Projects" spellcheck="false"
                   style="flex:1;min-width:200px;font-family:var(--mono);font-size:12px">
            <button id="syNewPickParent">选择父目录…</button>
          </div>
          <div style="display:flex;gap:8px;margin-top:6px;flex-wrap:wrap">
            <input id="syNewName" placeholder="项目名称" spellcheck="false" style="flex:1;min-width:160px;font-size:12px">
            <button class="primary" id="syNewCreate">新建项目</button>
          </div>
          <div id="syNewErr" style="color:var(--red);font-size:11.5px;margin-top:6px"></div>
        </div>
        <div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-top:10px">
          <div style="font-size:12px;font-weight:600;margin-bottom:6px">打开已有项目</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <input id="syPath" placeholder="/path/to/ForgeworksProject" spellcheck="false"
                   style="flex:1;min-width:200px;font-family:var(--mono);font-size:12px">
            <button id="syBind">打开</button>
            <button id="syPick">选择文件夹…</button>
          </div>
          <div id="syBindErr" style="color:var(--red);font-size:11.5px;margin-top:6px"></div>
        </div>
      `}
      ${_syncRecentHTML(proj)}
    </div>

    ${proj ? syncUECardHTML() : ''}

    ${proj ? `
    <div class="card">
      <h3>项目资源</h3>
      <p class="hint">
        资源生成写进当前 Forgeworks 项目的 <code>_Source/Machines/&lt;ID&gt;/</code>：
        GLB（含风格材质）、等轴测预览与 hash 记录。这些是项目的完整资源，
        比导出给 UE 的内容多；导出到 UE 时只挑选其中的 GLB。
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
      <h3>材质贴图（AI）</h3>
      <p class="hint">
        每个材质一张中性灰度细节图，导出 GLB 时作为贴图内嵌；颜色仍由风格色板决定，同一套贴图可被所有风格复用。
        生成走 Tripo <code>seedream_v5</code>（1K），按张计费；结果缓存在 <code>_Source/Materials/&lt;风格&gt;/</code>。
      </p>
      <div id="syTexNotice"></div>
      <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
        <button class="primary" id="syTexAll">生成全部缺失</button>
        <button id="syTexRefresh">刷新目录</button>
      </div>
      <div id="syTextures" style="margin-top:10px"></div>
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

  /* ---------- 材质贴图 ---------- */
  _loadTexturePanel();
  const texAll = document.getElementById('syTexAll');
  if(texAll) texAll.onclick = ()=>_submitTextures(_missingTextureKeys());
  const texRefresh = document.getElementById('syTexRefresh');
  if(texRefresh) texRefresh.onclick = async ()=>{
    texRefresh.disabled = true;
    await syncLoadTextures(true);
    renderSyncTextures();
    texRefresh.disabled = false;
  };

  /* ---------- 项目 ---------- */
  const bindBtn = document.getElementById('syBind');
  if(bindBtn) bindBtn.onclick = async ()=>{
    const p = document.getElementById('syPath').value.trim();
    const err = document.getElementById('syBindErr');
    if(!p){ err.textContent = '请输入路径'; return; }
    bindBtn.disabled = true; bindBtn.textContent = '打开中…';
    try{
      const r = await syncOpenProject(p);
      if(!r.ok) err.textContent = r.error || '打开失败';
      else render();
    }catch(e){
      err.textContent = '请求失败：' + e.message;
    }finally{
      if(bindBtn.isConnected){ bindBtn.disabled = false; bindBtn.textContent = '打开'; }
    }
  };
  const un = document.getElementById('syUnbind');
  if(un) un.onclick = async ()=>{ await syncUnbindProject(); render(); };

  const saveBtn = document.getElementById('sySaveProject');
  if(saveBtn) saveBtn.onclick = async ()=>{
    saveBtn.disabled = true; saveBtn.textContent = '保存中…';
    try{
      await syncSaveProjectNow();
      render();
    }finally{
      if(saveBtn.isConnected){ saveBtn.disabled = false; saveBtn.textContent = '保存项目'; }
    }
  };

  const newPickParent = document.getElementById('syNewPickParent');
  if(newPickParent) newPickParent.onclick = async ()=>{
    const err = document.getElementById('syNewErr');
    const label = newPickParent.textContent;
    newPickParent.disabled = true; newPickParent.textContent = '等待系统对话框…';
    try{
      const picked = await syncPickFolder();
      if(picked && picked.ok && picked.path){
        document.getElementById('syNewParent').value = picked.path;
      }else if(picked && !picked.cancelled && err){
        err.textContent = picked.error || '没有选择目录';
      }
    }catch(e){
      if(err) err.textContent = '选择失败：' + e.message;
    }finally{
      if(newPickParent.isConnected){ newPickParent.disabled = false; newPickParent.textContent = label; }
    }
  };

  const newCreate = document.getElementById('syNewCreate');
  if(newCreate) newCreate.onclick = async ()=>{
    const parent = document.getElementById('syNewParent').value.trim();
    const name = document.getElementById('syNewName').value.trim();
    const err = document.getElementById('syNewErr');
    if(!parent){ err.textContent = '请选择父目录'; return; }
    if(!name){ err.textContent = '请输入项目名称'; return; }
    newCreate.disabled = true; newCreate.textContent = '创建中…';
    try{
      const r = await syncCreateProject(parent, name);
      if(!r.ok) err.textContent = r.error || '创建失败';
      else render();
    }catch(e){
      err.textContent = '请求失败：' + e.message;
    }finally{
      if(newCreate.isConnected){ newCreate.disabled = false; newCreate.textContent = '新建项目'; }
    }
  };

  const pick = document.getElementById('syPick');
  if(pick) pick.onclick = async ()=>{
    const err = document.getElementById('syBindErr');
    const label = pick.textContent;
    pick.disabled = true; pick.textContent = '等待系统对话框…';
    try{
      const picked = await syncPickFolder();
      if(picked && picked.ok && picked.path){
        const r = await syncOpenProject(picked.path);
        if(r && r.ok){ render(); return; }
        if(err) err.textContent = (r && r.error) || '打开失败';
        else syncLog('打开项目失败：' + ((r && r.error) || ''), 'warn');
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
      const r = await syncOpenProject(button.dataset.recent);
      if(!r || !r.ok) syncLog('打开项目失败：' + ((r && r.error) || '未知错误'), 'warn');
    }catch(e){ syncLog('打开项目失败：' + e.message, 'warn'); }
    render();
  });

  /* ---------- UE 导出 ---------- */
  const ueSet = document.getElementById('syUeSet');
  if(ueSet) ueSet.onclick = async ()=>{
    const path = document.getElementById('syUePath').value.trim();
    const err = document.getElementById('syUeErr');
    if(!path){ err.textContent = '请输入 UE 项目路径'; return; }
    ueSet.disabled = true; ueSet.textContent = '设置中…';
    try{
      const r = await syncSetUETarget(path);
      if(!r.ok) err.textContent = r.error || '设置失败';
      else render();
    }catch(e){
      err.textContent = '请求失败：' + e.message;
    }finally{
      if(ueSet.isConnected){ ueSet.disabled = false; ueSet.textContent = '设置目标'; }
    }
  };
  const uePick = document.getElementById('syUePick');
  if(uePick) uePick.onclick = async ()=>{
    const err = document.getElementById('syUeErr');
    if(err) err.textContent = '';
    try{
      const picked = await syncPickFolder();
      if(picked && picked.ok && picked.path){
        const r = await syncSetUETarget(picked.path);
        if(r && r.ok){ render(); return; }
        if(err) err.textContent = (r && r.error) || '设置失败';
      }else if(picked && !picked.cancelled && err){
        err.textContent = picked.error || '没有选择目录';
      }
    }catch(e){
      if(err) err.textContent = '选择失败：' + e.message;
    }
  };
  const ueTargetPick = document.getElementById('syUETargetPick');
  if(ueTargetPick) ueTargetPick.onclick = async ()=>{
    try{
      const picked = await syncPickFolder();
      if(picked && picked.ok && picked.path){
        const r = await syncSetUETarget(picked.path);
        if(!r.ok) syncLog('设置 UE 导出目标失败：' + ((r && r.error) || ''), 'warn');
        render();
      }
    }catch(e){ syncLog('设置 UE 导出目标失败：' + e.message, 'warn'); }
  };
  const ueRefreshManifest = document.getElementById('syUERefreshManifest');
  if(ueRefreshManifest) ueRefreshManifest.onclick = async ()=>{
    await syncLoadUEManifest();
    render();
  };
  const uePublishAll = document.getElementById('syUEPublishAll');
  if(uePublishAll) uePublishAll.onclick = ()=>_doPublishUE(S.machines.map(m=>m.id));
  const uePublishStale = document.getElementById('syUEPublishStale');
  if(uePublishStale) uePublishStale.onclick = ()=>{
    const ids = S.machines.filter(m=>machineUEState(m).state !== 'exported').map(m=>m.id);
    if(!ids.length){ toast('UE 侧已是最新'); return; }
    _doPublishUE(ids);
  };

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

/* ---------- UE 导出执行 ---------- */

async function _doPublishUE(ids){
  if(_syncBusy) return;
  _syncBusy = true;
  const prog = document.getElementById('syUEProgress');
  if(prog) prog.textContent = '正在导出 ' + ids.length + ' 个资产…';
  try{
    const r = await syncPublishUE(ids);
    if(!r.ok){
      const detail = (r.errors || []).map(e=>e.id + '：' + e.error).join('；');
      syncLog('导出到 UE 失败：' + (detail || r.error || '未知错误'), 'warn');
      toast('导出到 UE 失败');
    }else{
      const msg = 'UE 导出完成：' + (r.published || []).length + ' 个' +
        ((r.skipped || []).length ? '，跳过 ' + r.skipped.length + ' 个' : '');
      syncLog(msg, 'ok');
      toast(msg);
    }
  }catch(e){
    syncLog('导出到 UE 中断：' + e.message, 'warn');
    toast('导出到 UE 中断：' + e.message);
  }finally{
    _syncBusy = false;
    render();
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
    { t:'UE', w:'88px', f:r=>ueStateTag(machineUEState(r.m).state) },
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

/* ---------- 材质贴图 ---------- */

let _texPollTimer = null;

function _texCatalog(){
  return (typeof FW_TEX !== 'undefined') ? FW_TEX.catalog : null;
}

function _texSpecs(){
  const catalog = _texCatalog();
  return catalog && Array.isArray(catalog.specs) ? catalog.specs : [];
}

function _texItem(key){
  const catalog = _texCatalog();
  return (catalog && catalog.items && catalog.items[key]) || null;
}

function _texActiveKeys(){
  return _texSpecs().map(spec=>spec.key).filter(key=>{
    const item = _texItem(key);
    return item && (item.state === 'queued' || item.state === 'running');
  });
}

function _missingTextureKeys(){
  return _texSpecs().map(spec=>spec.key).filter(key=>{
    const item = _texItem(key);
    return !item || ['none', 'failed', 'missing'].indexOf(item.state || 'none') >= 0;
  });
}

async function _loadTexturePanel(){
  const el = document.getElementById('syTextures');
  if(!el) return;
  if(!_texCatalog()) el.innerHTML = '<span class="hint">读取贴图目录…</span>';
  await syncLoadTextures(false);
  renderSyncTextures();
  _scheduleTexturePoll();
}

function renderSyncTextures(){
  const el = document.getElementById('syTextures');
  if(!el) return;
  const catalog = _texCatalog();
  const notice = document.getElementById('syTexNotice');
  if(!catalog){
    if(notice) notice.innerHTML = '';
    el.innerHTML = '<span class="hint">未能读取贴图目录（Bridge 离线、未绑定项目或请求失败）。</span>';
    return;
  }
  if(notice){
    notice.innerHTML = catalog.providerReady
      ? `<div style="font-size:11px;color:var(--text-3);margin-top:6px">缓存目录：<code>${syncEscape(catalog.dir)}</code></div>`
      : `<div class="issue warn" style="margin-top:8px"><span class="ic">!</span><div>
          贴图生成未配置。把 Tripo API Key 写进 <code>tools/bridge_config.json</code> 的
          <code>providers.tripo.api_key</code>，重启 Bridge 后再生成。
        </div></div>`;
  }
  const allButton = document.getElementById('syTexAll');
  if(allButton) allButton.disabled = !catalog.providerReady || !_missingTextureKeys().length;

  const meta = {
    ready:   { label:'已生成',  color:'var(--accent)' },
    queued:  { label:'排队中',  color:'var(--text-2)' },
    running: { label:'生成中',  color:'var(--amber)' },
    failed:  { label:'失败',    color:'var(--red)' },
    missing: { label:'文件缺失', color:'var(--red)' },
    none:    { label:'未生成',  color:'var(--text-3)' },
  };
  const specs = _texSpecs();
  el.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px">
    ${specs.map(spec=>{
      const item = _texItem(spec.key) || {};
      const state = item.state || 'none';
      const view = meta[state] || meta.none;
      const busy = state === 'queued' || state === 'running';
      const thumb = state === 'ready' && item.file && typeof fwTextureUrl === 'function'
        ? `<img src="${fwTextureUrl(catalog.styleId, spec.key, item)}" alt="${syncEscape(spec.name)}贴图"
               style="width:52px;height:52px;object-fit:cover;border:1px solid var(--border);border-radius:6px;background:var(--panel-2)">`
        : `<span style="display:flex;align-items:center;justify-content:center;width:52px;height:52px;
               border:1px dashed var(--border);border-radius:6px;font-family:var(--mono);font-size:10px;color:var(--text-3)">
             ${state === 'running' ? (Number(item.progress) || 0) + '%' : state === 'queued' ? '排队' : '—'}</span>`;
      const button = busy
        ? '<button class="sm" disabled>生成中</button>'
        : state === 'ready'
          ? `<button class="sm" data-tex="${syncEscape(spec.key)}" data-force="1" ${catalog.providerReady ? '' : 'disabled'}>重新生成</button>`
          : `<button class="sm" data-tex="${syncEscape(spec.key)}" ${catalog.providerReady ? '' : 'disabled title="需要配置 Tripo API Key"'}>生成</button>`;
      return `<div style="display:flex;gap:10px;align-items:flex-start;padding:8px;border:1px solid var(--border);border-radius:8px">
        ${thumb}
        <div style="min-width:0;flex:1">
          <div style="font-size:12px;font-weight:600">${syncEscape(spec.name)}</div>
          <div style="font-family:var(--mono);font-size:10px;color:var(--text-3)">${syncEscape(spec.key)}</div>
          <div style="font-size:10.5px;color:${view.color};margin-top:3px" ${item.error ? `title="${syncEscape(item.error)}"` : ''}>
            ${view.label}${state === 'ready' && item.size ? ' · ' + Math.round(item.size / 1024) + ' KB' : ''}
          </div>
          <div style="margin-top:6px">${button}</div>
        </div>
      </div>`;
    }).join('')}
  </div>`;

  el.querySelectorAll('[data-tex]').forEach(button=>{
    button.onclick = ()=>_submitTextures([button.dataset.tex], button.dataset.force === '1');
  });
}

async function _submitTextures(keys, force){
  if(!keys || !keys.length){ toast('没有需要生成的贴图'); return; }
  const names = keys.map(key=>{
    const spec = _texSpecs().find(item=>item.key === key);
    return spec ? spec.name : key;
  }).join('、');
  if(!window.confirm(`将调用 Tripo 生成 ${keys.length} 张材质贴图（${names}），可能产生费用。继续？`)) return;
  try{
    const result = await syncSubmitTextures(keys, force);
    if(!result || !result.ok){
      syncLog('贴图生成失败：' + ((result && result.error) || '未知错误'), 'warn');
      toast('贴图生成失败：' + ((result && result.error) || '未知错误'));
      return;
    }
    const submitted = (result.submitted || []).length;
    syncLog(`已提交 ${submitted} 张材质贴图` +
            (submitted < keys.length ? `（${keys.length - submitted} 张已存在或进行中）` : ''), 'ok');
    renderSyncTextures();
    _scheduleTexturePoll();
  }catch(error){
    syncLog('贴图生成失败：' + error.message, 'warn');
    toast('贴图生成失败：' + error.message);
  }
}

function _scheduleTexturePoll(){
  if(_texPollTimer){ clearTimeout(_texPollTimer); _texPollTimer = null; }
  if(!_texActiveKeys().length) return;
  _texPollTimer = setTimeout(async ()=>{
    _texPollTimer = null;
    if(!document.getElementById('syTextures')) return;
    const keys = _texActiveKeys();
    for(let i = 0; i < keys.length; i++){
      try{ await syncPollTexture(keys[i]); }catch(error){ /* 单张失败不影响其余 */ }
    }
    renderSyncTextures();
    _scheduleTexturePoll();
  }, 3000);
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
