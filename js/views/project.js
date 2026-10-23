/* Forgeworks · js/views/project.js */
/* ---------- 项目 ---------- */

function _projectRecentHTML(proj){
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

function renderProject(){
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
          Bridge 不在线。新建或打开项目需要本地服务（浏览器自身无法写项目目录）。
          工具其余功能不受影响。
        </div></div>
        <div class="setup-steps">
          <div class="setup-step"><span class="n">01</span><div>
            <b>启动 Bridge</b><p>在 Forgeworks 目录运行 <code>python3 tools/bridge.py</code>，然后刷新本页。</p>
          </div></div>
          <div class="setup-step"><span class="n">02</span><div>
            <b>新建或打开项目</b><p>Forgeworks 项目独立保存设计数据、描述词、管线与资源文件。</p>
          </div></div>
          <div class="setup-step"><span class="n">03</span><div>
            <b>生成并同步</b><p>资产生成与导出到 UE 在「同步」页完成。</p>
          </div></div>
        </div>
      `}
    </div>

    ${on ? providerCardHTML() : ''}

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
      ${_projectRecentHTML(proj)}
    </div>
    ` : ''}
  `;

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

  const resc = document.getElementById('syRescan');
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

  providerBindCard();
  if(on) providerEnsureLoaded();
}
