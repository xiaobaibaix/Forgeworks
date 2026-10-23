/* Forgeworks · js/ui/providers.js */
/* ---------- 生成服务 Provider ---------- */

const PROVIDERS = {ccswitch:[], ccswitchAvailable:false, configPath:'', tests:{}, loadedAt:0, loading:false, loadError:''};

function providerLoad(){
  if(PROVIDERS.loading) return Promise.resolve(PROVIDERS);
  PROVIDERS.loading = true;
  return pipelineApi('providers').then(result=>{
    PIPELINE.providers = result.providers || {};
    PROVIDERS.ccswitch = Array.isArray(result.ccswitch) ? result.ccswitch : [];
    PROVIDERS.ccswitchAvailable = !!result.ccswitchAvailable;
    PROVIDERS.configPath = result.configPath || '';
    PROVIDERS.loadError = '';
    return PROVIDERS;
  }).catch(error=>{
    PROVIDERS.loadError = error.message;
    throw error;
  }).finally(()=>{
    PROVIDERS.loading = false;
    PROVIDERS.loadedAt = Date.now();
  });
}

function providerEnsureLoaded(){
  if(!SYNC.online || PROVIDERS.loading) return;
  if(Date.now() - PROVIDERS.loadedAt < 30000) return;
  providerLoad().then(()=>{
    if(cur === 'project') render();
  }).catch(()=>{
    if(cur === 'project') render();
  });
}

function providerTestHTML(name){
  const test = PROVIDERS.tests[name];
  if(!test) return '';
  if(test.state === 'pending') return '<span style="color:var(--text-3)">测试中…</span>';
  if(test.ok) return `<span style="color:var(--accent)">连通${test.latencyMs != null ? ' · ' + test.latencyMs + ' ms' : ''}</span>`;
  return `<span style="color:var(--red)">${pipelineEscape(test.error || '连接失败')}</span>`;
}

function providerRenderTestSlot(name){
  const slot = document.getElementById('provTest-' + name);
  if(slot) slot.innerHTML = providerTestHTML(name);
}

async function providerRunTest(name){
  PROVIDERS.tests[name] = {state:'pending'};
  providerRenderTestSlot(name);
  let result;
  try{
    const response = await pipelineApi('providers/test', {provider:name});
    result = response.result || {ok:false, error:'Provider 未返回结果'};
  }catch(error){
    result = {ok:false, error:error.message};
  }
  PROVIDERS.tests[name] = Object.assign({state:'done'}, result);
  providerRenderTestSlot(name);
}

function providerRowHTML(name){
  const info = (PIPELINE.providers || {})[name] || {};
  const label = name === 'ark' ? '火山方舟 Ark' : 'Tripo';
  const detail = name === 'ark'
    ? [info.endpoint, info.image_model, info.model3d_model].filter(Boolean).join(' · ')
    : '云端文生图 / 图生模型';
  return `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 0;border-top:1px solid var(--border)">
    <div style="min-width:150px;font-size:12px"><strong>${label}</strong>
      ${info.configured ? '<span class="tag t0">已配置</span>' : '<span class="tag t5">未配置</span>'}</div>
    <div style="flex:1;min-width:200px;font-family:var(--mono);font-size:10.5px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${pipelineEscape(detail || '未填写 Endpoint / 模型')}</div>
    <button class="sm" data-provtest="${name}">测试连通性</button>
    <span id="provTest-${name}" style="font-size:11px;min-width:70px">${providerTestHTML(name)}</span>
  </div>`;
}

function providerCcswitchHTML(){
  if(!PROVIDERS.ccswitchAvailable){
    return '<div style="font-size:11px;color:var(--text-3);margin-top:6px">未找到 <code>~/.cc-switch/cc-switch.db</code>，无法导入。</div>';
  }
  const list = PROVIDERS.ccswitch || [];
  if(!list.length){
    return '<div style="font-size:11px;color:var(--text-3);margin-top:6px">cc-switch 中没有可导入的火山 Seedream / Seed3D 配置。</div>';
  }
  return `<div style="margin-top:6px">${list.map(item=>`<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:6px 0;border-top:1px solid var(--border)">
    <div style="min-width:180px;font-size:12px">${pipelineEscape(item.name)} <span class="pill">${item.field === 'image_model' ? '图像' : '3D 模型'}</span></div>
    <div style="flex:1;min-width:220px;font-family:var(--mono);font-size:10.5px;color:var(--text-3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${pipelineEscape(item.model)} · Key ${pipelineEscape(item.keyHint)}</div>
    <button class="sm" data-ccimport="${pipelineEscape(item.id)}">导入</button>
  </div>`).join('')}</div>`;
}

function providerCardHTML(){
  const warning = PROVIDERS.loadError
    ? `<div class="issue warn" style="margin-top:8px"><span class="ic">!</span><div>读取 Provider 状态失败：${pipelineEscape(PROVIDERS.loadError)}</div></div>`
    : '';
  return `<div class="card">
    <h3>生成服务 · Provider</h3>
    <div style="font-size:11px;color:var(--text-3);margin-top:2px">供「生成管线」远程文生图 / 图生模型使用；密钥只写入本机 <code>tools/bridge_config.json</code>，不会进入项目或仓库。</div>
    ${warning}
    ${providerRowHTML('ark')}
    ${providerRowHTML('tripo')}
    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
      <button class="primary" id="provOpen">配置 Provider</button>
      <button id="provReload">刷新状态</button>
    </div>
    <div style="border-top:1px solid var(--border);margin-top:12px;padding-top:10px">
      <div style="font-size:12px;font-weight:600">从 cc-switch 导入</div>
      ${providerCcswitchHTML()}
    </div>
  </div>`;
}

async function providerImportCcswitch(id, button){
  if(button){ button.disabled = true; button.textContent = '导入中…'; }
  try{
    const result = await pipelineApi('providers/ccswitch/import', {id});
    PIPELINE.providers = result.providers || {};
    PROVIDERS.ccswitch = Array.isArray(result.ccswitch) ? result.ccswitch : [];
    PROVIDERS.ccswitchAvailable = !!result.ccswitchAvailable;
    PROVIDERS.tests = {};
    PROVIDERS.loadedAt = Date.now();
    toast('已从 cc-switch 导入火山 Ark 配置');
    if(cur === 'project') render();
    providerRunTest('ark');
  }catch(error){
    toast(error.message);
    if(button && button.isConnected){ button.disabled = false; button.textContent = '导入'; }
  }
}

function providerBindCard(){
  const open = document.getElementById('provOpen');
  if(open) open.onclick = () => openProviderSettings();
  const reload = document.getElementById('provReload');
  if(reload) reload.onclick = async ()=>{
    reload.disabled = true; reload.textContent = '刷新中…';
    try{ await providerLoad(); }
    catch(error){ toast(error.message); }
    finally{
      if(reload.isConnected){ reload.disabled = false; reload.textContent = '刷新状态'; }
      if(cur === 'project') render();
    }
  };
  document.querySelectorAll('[data-provtest]').forEach(button=>{
    button.onclick = () => providerRunTest(button.dataset.provtest);
  });
  document.querySelectorAll('[data-ccimport]').forEach(button=>{
    button.onclick = () => providerImportCcswitch(button.dataset.ccimport, button);
  });
}

function providerSettingsHTML(){
  const rows = PIPELINE.providers || {};
  const mark = name => (rows[name] && rows[name].configured)
    ? '<span class="tag t0">已配置</span>' : '<span class="tag t5">未配置</span>';
  const ark = rows.ark || {};
  const field = (id, label, value, type, hint) => `<div class="field"><label for="${id}">${label}</label>
    <input id="${id}" type="${type || 'text'}" autocomplete="off" value="${pipelineEscape(value || '')}">
    ${hint ? `<div style="font-size:11px;color:var(--text-3);margin-top:4px">${hint}</div>` : ''}</div>`;
  return `
    <div class="field"><label for="provArkKey">火山 Ark API Key ${mark('ark')}</label>
      <input id="provArkKey" type="password" autocomplete="off" placeholder="留空保持不变">
      <div style="font-size:11px;color:var(--text-3);margin-top:4px">Seedream 文生图与 Seed3D 图生模型共用这一个 Key。</div>
      <label style="margin-top:6px"><input type="checkbox" id="provArkClear"> 清除已保存的 Key</label></div>
    ${field('provArkEndpoint', 'Ark Endpoint', ark.endpoint || 'https://ark.cn-beijing.volces.com/api/v3', 'text', '只接受 https 火山域名；/api/compatible 会自动改写为 /api/v3。')}
    <div class="row">
      ${field('provArkImage', 'Seedream 图像模型', ark.image_model || 'doubao-seedream-5-0-pro-260628')}
      ${field('provArk3d', 'Seed3D 模型', ark.model3d_model || 'doubao-seed3d-2-0-260328')}
    </div>
    <div class="field" style="border-top:1px solid var(--border);padding-top:12px"><label for="provTripKey">Tripo API Key ${mark('tripo')}</label>
      <input id="provTripKey" type="password" autocomplete="off" placeholder="留空保持不变">
      <label style="margin-top:6px"><input type="checkbox" id="provTripClear"> 清除已保存的 Key</label></div>
    <div style="font-size:11px;color:var(--text-3);line-height:1.6">密钥只写入本机的 <code>tools/bridge_config.json</code>（已 gitignore），不会进入项目文件或仓库；保存后立即生效，无需重启 Bridge。</div>`;
}

function openProviderSettings(){
  if(!SYNC.online){ toast('Bridge 未连接，无法保存 Provider 配置'); return; }
  modalState = {providerSettings:true};
  document.getElementById('modal').innerHTML = `
    <header><h3>Provider 设置</h3><span class="x" id="mX">×</span></header>
    <div class="content" id="mBody">${providerSettingsHTML()}</div>
    <footer><div style="flex:1"></div><button id="mCancel">取消</button><button class="primary" id="mOk">保存</button></footer>`;
  document.getElementById('mask').classList.remove('hide');
  document.getElementById('mX').onclick = closeModal;
  document.getElementById('mCancel').onclick = closeModal;
  document.getElementById('mOk').onclick = () => saveProviderSettings().catch(error => toast(error.message));
}

async function saveProviderSettings(){
  const val = id => (document.getElementById(id) || {}).value || '';
  const checked = id => !!(document.getElementById(id) || {}).checked;
  const result = await pipelineApi('providers/save', {providers:{
    ark:{api_key:val('provArkKey'), endpoint:val('provArkEndpoint'),
         image_model:val('provArkImage'), model3d_model:val('provArk3d'),
         clearKey:checked('provArkClear')},
    tripo:{api_key:val('provTripKey'), clearKey:checked('provTripClear')}
  }});
  PIPELINE.providers = result.providers || {};
  PROVIDERS.ccswitch = Array.isArray(result.ccswitch) ? result.ccswitch : [];
  PROVIDERS.ccswitchAvailable = !!result.ccswitchAvailable;
  PROVIDERS.tests = {};
  PROVIDERS.loadedAt = Date.now();
  closeModal();
  toast(result.remoteExecutionAvailable ? 'Provider 配置已保存' : 'Provider 配置已保存（尚未填写任何 Key）');
  render();
}
