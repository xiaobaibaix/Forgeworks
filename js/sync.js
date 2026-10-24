/* Forgeworks · js/sync.js
   ============================================================
   同步引擎（前端侧）—— 与本地 Bridge 的通信层
   ------------------------------------------------------------
   Bridge（tools/bridge.py）负责文件系统；本文件负责：
     - 探测 Bridge 是否在线（离线时所有同步功能优雅降级）
     - 三把 hash 的状态机（sync-design §4.3）：
         contentHash  机器数据变了 → stale
         styleHash    风格/配色变了 → stale
         overridesHash 3D 编辑器的变换覆盖变了 → stale（本期预留）
     - 导出流程：离屏渲染 → toGLB → base64 → POST 给 Bridge 落盘
     - manifest 缓存，供机器列表/同步面板读取

   注意：本模块所有函数都是异步的，调用方要处理离线情况。
   ============================================================ */

const SYNC = {
  online: false,          // Bridge 是否在线
  probing: true,          // 首次探测未返回时，页面先显示「正在连接」而不是离线引导
  checkedAt: 0,
  status: null,           // /api/status 的结果
  manifest: null,         // 项目 manifest 缓存（Bridge 在线时以它为准）
  ueManifest: null,       // UE 导出目标里的 manifest（只含已发布资产）
  projects: { current: null, recent: [] },   // 当前项目 + 最近打开过的项目
  content: null,          // 项目内容基线快照（判断本地改了哪些实体）
  contentRoot: null,      // 已载入内容的项目根，防止未载入时用本地数据覆盖项目
  contentRevision: '',    // 基线对应的 project.json revision（乐观锁）
  contentTimer: null,
  contentSaving: false,
  contentStale: false,    // 编辑器打开期间收到的外部修改，关闭后再载入
  contentReloaded: false, // 本次载入是否真的换掉了内存里的 S（用于首屏补渲染）
  contentSavedAt: 0,
  clientId: Math.random().toString(36).slice(2) + Date.now().toString(36),
  ueAssets: [],
  conflicts: [],
  lastScan: null,
  log: [],                // 事件日志（SSE 或操作产生）
};

/* ---------- 基础请求 ---------- */

async function syncApi(route, body){
  const opts = body !== undefined
    ? { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body) }
    : {};
  const r = await fetch('/api/' + route, opts);
  let data = null;
  try{ data = await r.json(); }catch(_){}
  if(!r.ok){
    // 409/404 带结构化错误（如 revision 冲突），交给调用方判断
    if(data && typeof data === 'object'){ data.httpStatus = r.status; return data; }
    throw new Error('HTTP ' + r.status);
  }
  return data === null ? {} : data;
}

/** 探测 Bridge（2 秒超时）。不会抛异常，失败只置 online=false。 */
async function syncPing(force){
  if(!force && Date.now() - SYNC.checkedAt < 15000) return SYNC.online;
  SYNC.checkedAt = Date.now();
  SYNC.probing = true;
  try{
    const ctl = new AbortController();
    const t = setTimeout(()=>ctl.abort(), 2000);
    const r = await fetch('/api/status', { signal: ctl.signal });
    clearTimeout(t);
    if(!r.ok) throw new Error('HTTP ' + r.status);
    SYNC.status = await r.json();
    SYNC.online = !!(SYNC.status && SYNC.status.ok);
    if(SYNC.online){
      await syncLoadProjects();
      await syncLoadProjectContent();
      await syncLoadManifest(); await syncLoadUEManifest();
      await syncLoadUEAssets(); await syncLoadConflicts();
    }
  }catch(e){
    SYNC.online = false;
    SYNC.status = null;
  }finally{
    SYNC.probing = false;
  }
  return SYNC.online;
}

async function syncLoadProjects(){
  if(!SYNC.online){ SYNC.projects = { current:null, recent:[] }; return SYNC.projects; }
  try{
    const r = await syncApi('projects');
    SYNC.projects = (r && r.ok)
      ? { current:r.current || null, recent:Array.isArray(r.recent) ? r.recent : [] }
      : { current:null, recent:[] };
    if(r && r.ok && SYNC.status){
      SYNC.status.project = r.current || null;
      SYNC.status.ueTarget = r.ueTarget || null;
    }
  }catch(e){ SYNC.projects = { current:null, recent:[] }; }
  return SYNC.projects;
}

/** 让 Bridge 弹系统目录选择框；返回 {ok, path} 或 {ok:false, cancelled:true} */
async function syncPickFolder(){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线' };
  return syncApi('project/pick', {});
}

async function syncLoadManifest(){
  if(!SYNC.online){ SYNC.manifest = null; return null; }
  try{
    const r = await syncApi('manifest');
    SYNC.manifest = (r && r.ok) ? r.manifest : null;
  }catch(e){ SYNC.manifest = null; }
  return SYNC.manifest;
}

async function syncLoadUEAssets(){
  if(!SYNC.online || !SYNC.status || !SYNC.status.project){ SYNC.ueAssets = []; return []; }
  try{
    const result = await syncApi('ue/assets');
    SYNC.ueAssets = result && result.ok && Array.isArray(result.assets) ? result.assets : [];
  }catch(e){ SYNC.ueAssets = []; }
  return SYNC.ueAssets;
}

async function syncLoadConflicts(){
  if(!SYNC.online || !SYNC.status || !SYNC.status.project){ SYNC.conflicts = []; return []; }
  try{
    const result = await syncApi('conflicts');
    SYNC.conflicts = result && result.ok && Array.isArray(result.conflicts) ? result.conflicts : [];
  }catch(e){ SYNC.conflicts = []; }
  return SYNC.conflicts;
}

/* ---------- 项目内容（project.json） ---------- */

const SYNC_CONTENT_COLLECTIONS = ['elements','items','machines','recipes','techs'];

function syncCloneJSON(value){
  return JSON.parse(JSON.stringify(value));
}

/** 载入项目内容；force=true 时即使已载入也重新读。项目没有内容时保留当前 S。 */
async function syncLoadProjectContent(force){
  const proj = SYNC.status && SYNC.status.project;
  if(!SYNC.online || !proj || !proj.root){ SYNC.contentRoot = null; return null; }
  if(!force && SYNC.contentRoot === proj.root) return SYNC.content;
  try{
    const r = await syncApi('project/content');
    if(!r || !r.ok) throw new Error((r && r.error) || '读取失败');
    const content = r.content || null;
    const previous = JSON.stringify(S);
    SYNC.contentRoot = proj.root;
    SYNC.contentRevision = r.revision || '';
    SYNC.contentStale = false;
    if(content && Array.isArray(content.items) && Array.isArray(content.recipes)){
      S = content;
      normalizeAssets(S);
      syncSaveLocal();
      if(typeof clearCostCache === 'function') clearCostCache();
      if(typeof clearIconCache === 'function') clearIconCache();
    }
    SYNC.contentReloaded = !!content && JSON.stringify(S) !== previous;
    // 基线必须与 S 分离，否则编辑会同时改掉基线，三方合并失效
    if(content){
      SYNC.content = syncCloneJSON(content);
      normalizeAssets(SYNC.content);
    }else{
      SYNC.content = null;
    }
    return content;
  }catch(e){
    SYNC.contentRoot = null;
    syncLog('读取项目内容失败，暂时只保存到浏览器：' + e.message, 'warn');
    return null;
  }
}

function syncEntityMap(list){
  const map = {};
  (Array.isArray(list) ? list : []).forEach(function(row){
    if(row && row.id != null) map[String(row.id)] = row;
  });
  return map;
}

/** 单集合三方合并：以最后载入的内容为基线，本地改动优先于远端冲突。 */
function syncMergeCollection(coll, baseContent, latestContent){
  const baseList = Array.isArray(baseContent[coll]) ? baseContent[coll] : [];
  const localList = Array.isArray(S[coll]) ? S[coll] : baseList;
  const latestList = Array.isArray(latestContent[coll]) ? latestContent[coll] : [];
  const baseJson = JSON.stringify(baseList);
  const localJson = JSON.stringify(localList);
  const latestJson = JSON.stringify(latestList);
  if(localJson === baseJson) return { list: latestList, conflicts: 0 };
  if(latestJson === baseJson) return { list: localList, conflicts: 0 };

  const base = syncEntityMap(baseList);
  const local = syncEntityMap(localList);
  const remote = syncEntityMap(latestList);
  const ids = [];
  const seen = {};
  latestList.concat(localList).forEach(function(row){
    if(!row || row.id == null) return;
    const key = String(row.id);
    if(!seen[key]){ seen[key] = true; ids.push(key); }
  });
  const out = [];
  let conflicts = 0;
  ids.forEach(function(key){
    const hasBase = Object.prototype.hasOwnProperty.call(base, key);
    const hasLocal = Object.prototype.hasOwnProperty.call(local, key);
    const hasRemote = Object.prototype.hasOwnProperty.call(remote, key);
    const baseValue = hasBase ? JSON.stringify(base[key]) : null;
    const localValue = hasLocal ? JSON.stringify(local[key]) : null;
    const remoteValue = hasRemote ? JSON.stringify(remote[key]) : null;
    if(localValue === baseValue){
      if(hasRemote) out.push(remote[key]);
    }else if(remoteValue === baseValue){
      if(hasLocal) out.push(local[key]);
    }else if(hasLocal){
      out.push(local[key]);
      if(hasRemote) conflicts += 1;
    }else if(hasRemote){
      out.push(remote[key]);
    }
  });
  return { list: out, conflicts: conflicts };
}

/** 409 后用最新远端内容合并本地修改，返回双方都改过的实体数。 */
function syncMergeContent(latest){
  if(!latest || typeof latest !== 'object') return 0;
  const base = (SYNC.content && typeof SYNC.content === 'object') ? SYNC.content : {};
  const merged = syncCloneJSON(latest);
  let conflicts = 0;
  SYNC_CONTENT_COLLECTIONS.forEach(function(coll){
    const result = syncMergeCollection(coll, base, latest);
    merged[coll] = result.list;
    conflicts += result.conflicts;
  });
  Object.keys(S).forEach(function(key){
    if(!(key in merged)) merged[key] = S[key];
  });
  S = merged;
  normalizeAssets(S);
  syncSaveLocal();
  if(typeof clearCostCache === 'function') clearCostCache();
  if(typeof clearIconCache === 'function') clearIconCache();
  const baseCopy = syncCloneJSON(latest);
  normalizeAssets(baseCopy);
  SYNC.content = baseCopy;
  return conflicts;
}

function syncSaveLocal(){
  if(typeof saveLocalState === 'function') return saveLocalState();
  try{ localStorage.setItem(LS_KEY, JSON.stringify(S)); return true; }catch(e){ return false; }
}

/** 内容未载入时不写项目，避免用本地旧数据覆盖项目文件。 */
function syncScheduleContentSave(){
  const proj = SYNC.status && SYNC.status.project;
  if(!SYNC.online || !proj || !proj.root) return false;
  if(SYNC.contentRoot !== proj.root) return false;
  clearTimeout(SYNC.contentTimer);
  SYNC.contentTimer = setTimeout(function(){ syncFlushContent(); }, 400);
  return true;
}

async function syncFlushContent(retried){
  if(SYNC.contentTimer){ clearTimeout(SYNC.contentTimer); SYNC.contentTimer = null; }
  const root = SYNC.contentRoot;
  const proj = SYNC.status && SYNC.status.project;
  if(!SYNC.online || !root || !proj || proj.root !== root) return { ok:false, skipped:true };
  SYNC.contentSaving = true;
  try{
    const r = await syncApi('project/content', {
      content: S,
      baseRevision: SYNC.contentRevision,
      source: 'ui',
      clientId: SYNC.clientId,
    });
    if(r && r.ok){
      SYNC.contentRevision = r.revision || SYNC.contentRevision;
      SYNC.contentSavedAt = Date.now();
      SYNC.content = syncCloneJSON(S);
      SYNC.contentStale = false;
      return r;
    }
    if(r && r.conflict && !retried){
      const latest = await syncApi('project/content');
      if(latest && latest.ok){
        const conflicts = syncMergeContent(latest.content);
        SYNC.contentRevision = latest.revision || '';
        if(typeof render === 'function') render();
        if(conflicts && typeof toast === 'function'){
          toast('已合并外部修改；' + conflicts + ' 个实体双方都改过，保留本地版本');
        }
        syncLog('项目内容被外部修改，已合并后重试保存', 'warn');
        return await syncFlushContent(true);
      }
    }
    syncLog('项目内容保存失败：' + ((r && r.error) || '未知错误'), 'warn');
    return r;
  }catch(e){
    syncLog('项目内容保存失败：' + e.message, 'warn');
    return { ok:false, error: e.message };
  }finally{
    SYNC.contentSaving = false;
  }
}

/** 外部写入后重新载入内容；仅在编辑器关闭且无待保存改动时调用。 */
async function syncReloadContent(reason){
  if(!SYNC.online) return;
  const content = await syncLoadProjectContent(true);
  if(!content) return;
  if(typeof render === 'function') render();
  if(typeof toast === 'function') toast('已载入最新项目内容');
  syncLog((reason || '外部修改') + '：已同步最新内容', 'ok');
}

/** 弹窗关闭后补上编辑器打开期间跳过的外部更新。 */
function syncResumeAfterModal(){
  if(!SYNC.contentStale) return;
  if(SYNC.contentTimer) return;    // 本地还有待保存改动，交给保存时的合并处理
  SYNC.contentStale = false;
  syncReloadContent('外部修改');
}

/** 立即保存（浏览器本地备份 + 项目文件）。 */
async function syncSaveProjectNow(){
  syncSaveLocal();
  return syncFlushContent();
}

/* ---------- UE 导出目标 ---------- */

async function syncLoadUEManifest(){
  const target = SYNC.status && SYNC.status.ueTarget;
  if(!SYNC.online || !target){ SYNC.ueManifest = null; return null; }
  try{
    const r = await syncApi('ue/manifest');
    SYNC.ueManifest = (r && r.ok) ? r.manifest : null;
  }catch(e){ SYNC.ueManifest = null; }
  return SYNC.ueManifest;
}

/** manifest 记录里是否含某个角色的文件（老记录可能只有 mesh）。 */
function hasAssetFile(rec, role){
  const files = (rec && rec.files) || {};
  return !!(files[role] && files[role].length);
}

/** UE 侧状态：none=未导出，stale=设计已变或缺图标，exported=与设计一致。 */
function machineUEState(m){
  const rec = SYNC.ueManifest && SYNC.ueManifest.assets && SYNC.ueManifest.assets[m.id];
  if(!rec) return { state:'none', rec:null };
  const meta = rec.meta || {};
  const aiStale = m.model && m.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || meta.modelHash !== machineModelHash(m))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (meta.contentHash && meta.contentHash !== machineContentHash(m))
             || (meta.styleHash   && meta.styleHash   !== machineStyleHash(m));
  return { state: stale ? 'stale' : 'exported', rec };
}

/** 物品图标 hash：自定义图标、类型/颜色、名称、当前风格任一变化都要重导出 */
function itemIconHash(it){
  return syncDataHash({
    id: it.id, name: it.name, type: it.visual || it.type, color: it.color || '',
    customIcon: (it.icon || '').trim(), iconSource: it.iconSource || '',
    style: styleCacheTag(),
  });
}

function itemUEState(it){
  const rec = SYNC.ueManifest && SYNC.ueManifest.assets && SYNC.ueManifest.assets[it.id];
  if(!rec) return { state:'none', rec:null };
  const meta = rec.meta || {};
  const aiStale = it.model && it.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || meta.modelHash !== itemModelHash(it))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (meta.iconHash && meta.iconHash !== itemIconHash(it));
  return { state: stale ? 'stale' : 'exported', rec };
}

/** 元素图标 hash：自定义图标、符号/名称/等级/颜色、当前风格任一变化都要重导出 */
function elementIconHash(el){
  return syncDataHash({
    id: el.id, name: el.name, symbol: el.symbol || '', tier: el.tier,
    color: el.color || '', customIcon: (el.icon || '').trim(), style: styleCacheTag(),
  });
}

function elementUEState(el){
  const rec = SYNC.ueManifest && SYNC.ueManifest.assets && SYNC.ueManifest.assets[el.id];
  if(!rec || rec.kind !== 'element') return { state:'none', rec:null };
  const meta = rec.meta || {};
  const stale = !hasAssetFile(rec, 'icon')
             || (meta.iconHash && meta.iconHash !== elementIconHash(el));
  return { state: stale ? 'stale' : 'exported', rec };
}

function syncProjectReady(){
  return !!(SYNC.online && SYNC.status && SYNC.status.project);
}

async function syncResolveConflict(conflict, choice){
  const result = await syncApi('conflicts/resolve', {id:conflict.id, conflictId:conflict.conflictId, choice});
  if(result && result.ok){ await syncLoadManifest(); await syncLoadConflicts(); }
  return result;
}

/* ---------- 项目管理 ---------- */

function syncProjectsPayload(r){
  if(!r || !r.ok) return;
  if(SYNC.status){
    SYNC.status.project = r.project || null;
    SYNC.status.ueTarget = r.ueTarget || null;
  }
}

/** 打开已有 Forgeworks 项目（旧版 <UE>/Forgeworks 布局也能识别）。 */
async function syncOpenProject(path){
  await syncFlushContent();
  const r = await syncApi('project/bind', { path });
  if(r && r.ok){
    syncProjectsPayload(r);
    SYNC.contentRoot = null; SYNC.content = null;
    syncLog('已打开项目：' + r.project.name + '（' + r.project.root + '）', 'ok');
    await syncLoadProjects();
    await syncLoadProjectContent();
    await Promise.all([syncLoadManifest(), syncLoadUEManifest(), syncLoadUEAssets(), syncLoadConflicts()]);
  }
  return r;
}

async function syncCreateProject(parent, name){
  await syncFlushContent();
  const r = await syncApi('project/create', { parent, name });
  if(r && r.ok){
    syncProjectsPayload(r);
    SYNC.contentRoot = r.project.root;
    SYNC.content = S;
    syncLog('已新建项目：' + r.project.name + '（' + r.project.root + '）', 'ok');
    await syncLoadProjects();
    await syncSaveProjectNow();          // 新项目立即写入当前设计数据
    await Promise.all([syncLoadManifest(), syncLoadUEManifest(), syncLoadUEAssets(), syncLoadConflicts()]);
  }
  return r;
}

async function syncSetUETarget(path){
  const r = await syncApi('project/ue-target', { path });
  if(r && r.ok){
    if(SYNC.status) SYNC.status.ueTarget = r.ueTarget;
    syncLog('UE 导出目标：' + r.ueTarget.root, 'ok');
    await Promise.all([syncLoadProjects(), syncLoadUEManifest()]);
  }
  return r;
}

async function syncPublishUE(ids){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线' };
  const r = await syncApi('project/publish', ids ? { ids: ids } : {});
  if(r && r.ok){
    syncLog('已导出到 UE：' + (r.published || []).join('、'), 'ok');
    await Promise.all([syncLoadUEManifest(), syncLoadManifest()]);
  }
  return r;
}

async function syncUnbindProject(){
  await syncFlushContent();
  const r = await syncApi('project/unbind', {});
  SYNC.manifest = null;
  SYNC.ueManifest = null;
  SYNC.ueAssets = [];
  SYNC.conflicts = [];
  SYNC.content = null;
  SYNC.contentRoot = null;
  if(SYNC.status){ SYNC.status.project = null; SYNC.status.ueTarget = null; }
  await syncLoadProjects();
  return r;
}

/** 侧栏顶部的项目切换器：始终可见，点开进入项目页 */
function renderProjectChip(){
  const el = document.getElementById('projectChip');
  if(!el) return;
  const project = SYNC.status && SYNC.status.project;
  const ueTarget = SYNC.status && SYNC.status.ueTarget;
  const name = project ? (project.name || project.root) : '未打开项目';
  const kind = project ? (ueTarget ? '项目 · UE 已就绪' : 'Forgeworks 项目')
                       : (SYNC.online ? '点击新建或打开' : 'Bridge 未启动');
  el.innerHTML = `<button class="project-chip"
    title="${syncEscape(project ? project.root : '在项目页新建或打开项目')}">
    <span class="pc-label">项目</span>
    <span class="pc-name">${syncEscape(name)}</span>
    <span class="pc-kind"><i class="dot ${project ? 'on' : ''}"></i>${syncEscape(kind)}</span>
  </button>`;
  el.querySelector('button').onclick = ()=>{ cur = 'project'; render(); syncHash('project'); };
}

/* ---------- 状态机（三把 hash，sync-design §4.3） ---------- */

/** 简单确定性 hash（复用 icons.js 的 FNV-1a；同步场景不需要密码学强度） */
function syncDataHash(obj){
  return hashStr(JSON.stringify(obj)).toString(16);
}

/** 模型身份 + 整体变换的 hash；没有模型时返回“空模型”的稳定值 */
function assetModelHash(model){
  if(!model) return syncDataHash(null);
  return syncDataHash({
    source: model.source || '',
    file: model.file || '',
    taskId: model.taskId || '',
    transform: typeof fwNormalizeTransform === 'function'
      ? fwNormalizeTransform(model.transform) : (model.transform || null),
    autoFit: model.autoFit !== false,
  });
}
function machineModelHash(m){ return assetModelHash(m.model); }
function itemModelHash(it){ return assetModelHash(it.model); }

/** 机器数据的 contentHash：影响几何/语义/图标/模型的字段 */
function machineContentHash(m){
  return syncDataHash({
    id: m.id, name: m.name, cat: m.cat, footprint: m.footprint,
    tier: m.tier, power: m.power,
    icon: (m.icon || '').trim(),
    iconSource: m.iconSource || '',
    model: machineModelHash(m),
  });
}

/** 风格的 styleHash：预设 + 旋钮 + 该机器的强调色（配色变了资产要重导） */
function machineStyleHash(m){
  const st = getStyle();
  return syncDataHash({
    presetId: st.id,
    overrides: (typeof styleState !== 'undefined') ? styleState.overrides : {},
    accent: accentFor(m.cat, st),
  });
}

/**
 * 计算单个机器的同步状态（不请求网络，纯本地对比）。
 * 返回：none | exported | stale | missing | tampered | external
 *   none      从未导出
 *   exported  已导出且内容/风格都没变
 *   stale     已导出但 hash 变了（待重导）
 *   missing   Bridge 记录里有、但磁盘上没了（scan 后）
 *   tampered  文件被外部改过（scan 后）
 *   external  磁盘上有这个目录，但 manifest 没记录（外部创建）
 */
function machineSyncState(m){
  const mf = SYNC.manifest;
  if(!mf || !mf.assets || !mf.assets[m.id]){
    return { state:'none', rec:null };
  }
  const rec = mf.assets[m.id];
  const diskState = rec.state || 'exported';       // Bridge scan 写入的磁盘状态
  if(diskState === 'missing')   return { state:'missing',  rec };
  if(diskState === 'tampered')  return { state:'tampered', rec };
  if(diskState === 'conflict')  return { state:'conflict', rec };
  // 磁盘没问题，但内容/风格可能已改（stale 判断：hash 存在 Bridge manifest 的 meta 里）
  const saved = rec.meta || {};
  const ch = machineContentHash(m);
  const sh = machineStyleHash(m);
  const aiStale = m.model && m.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || saved.modelHash !== machineModelHash(m))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (saved.contentHash && saved.contentHash !== ch)
             || (saved.styleHash   && saved.styleHash   !== sh);
  return { state: stale ? 'stale' : 'exported', rec };
}

/** 物品图标在项目里的同步状态（manifest 的磁盘状态 + iconHash） */
function itemSyncState(it){
  const mf = SYNC.manifest;
  if(!mf || !mf.assets || !mf.assets[it.id]) return { state:'none', rec:null };
  const rec = mf.assets[it.id];
  const diskState = rec.state || 'exported';
  if(diskState !== 'exported') return { state: diskState, rec };
  const saved = rec.meta || {};
  const aiStale = it.model && it.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || saved.modelHash !== itemModelHash(it))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (saved.iconHash && saved.iconHash !== itemIconHash(it));
  return { state: stale ? 'stale' : 'exported', rec };
}

/** 元素图标在项目里的同步状态（同物品；用 kind 防止与同名物品互认） */
function elementSyncState(el){
  const mf = SYNC.manifest;
  if(!mf || !mf.assets || !mf.assets[el.id]) return { state:'none', rec:null };
  const rec = mf.assets[el.id];
  if(rec.kind !== 'element') return { state:'none', rec:null };
  const diskState = rec.state || 'exported';
  if(diskState !== 'exported') return { state: diskState, rec };
  const saved = rec.meta || {};
  const stale = !hasAssetFile(rec, 'icon')
             || (saved.iconHash && saved.iconHash !== elementIconHash(el));
  return { state: stale ? 'stale' : 'exported', rec };
}

/* ---------- 材质贴图 ---------- */

async function syncLoadTextures(force){
  if(!SYNC.online || typeof fwReloadTextures !== 'function') return null;
  return fwReloadTextures(!!force);
}

async function syncSubmitTextures(keys, force){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线' };
  const st = getStyle();
  const r = await syncApi('materials/texture/submit', {
    styleId: st.id,
    keys: keys,
    force: !!force,
    size: '1K',
    confirmRemote: true,
    styleHint: [st.name, st.tagline, st.eraHint].filter(Boolean).join('；'),
  });
  if(r && r.ok) await syncLoadTextures(true);
  return r;
}

async function syncPollTexture(key){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线' };
  const styleId = getStyle().id;
  const r = await syncApi('materials/texture/poll', { styleId: styleId, key: key });
  if(r && r.ok && r.catalog && r.catalog.items && typeof FW_TEX !== 'undefined' && FW_TEX.catalog){
    FW_TEX.catalog.items = r.catalog.items;
  }
  if(r && r.ok && r.item && r.item.state === 'ready' && typeof fwLoadTextureItem === 'function'){
    await fwLoadTextureItem(styleId, key, r.item);
  }
  return r;
}

/* ---------- 导出 ---------- */

function bufToB64(buf){
  const u8 = new Uint8Array(buf);
  let s = '';
  const CH = 0x8000;                       // 分块避免 String.fromCharCode 栈溢出
  for(let i = 0; i < u8.length; i += CH){
    s += String.fromCharCode.apply(null, u8.subarray(i, i + CH));
  }
  return btoa(s);
}

/**
 * 导出单个机器到 Bridge（→ _Source/机器/<中文名>/）。
 * 流程：离屏 canvas → createViewer3D → toGLB → base64 → POST。
 * 同时带质量门禁信息（三角面 vs 风格规格）。
 */
async function syncExportMachine(id, opt){
  opt = opt || {};
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线（先启动 tools/bridge.py）' };
  const m = machineOf(id);
  if(!m) return { ok:false, error:'机器不存在: ' + id };
  if(!haveThree()) return { ok:false, error:'three.js 未加载' };

  // 1. 离屏生成 GLB；AI 模型先等加载完成，再取缩略图与烘焙结果
  if(typeof fwTexturesReady === 'function') await fwTexturesReady();
  const cv = document.createElement('canvas');
  cv.width = 64; cv.height = 64;
  const isAI = !!(m.model && m.model.source === 'ai');
  let V = null, glbBuf = null, glbErr = null, meta = null;
  let aiThumb256 = '', aiThumb512 = '';
  try{
    V = createViewer3D(cv, m);
    if(isAI){
      const ready = await V.whenModelReady();
      if(!ready.ok) throw new Error('AI 模型加载失败: ' + ready.error);
      aiThumb256 = V.toThumbnail(256);
      aiThumb512 = V.toThumbnail(512);
    }
    await new Promise(function(resolve){
      V.toGLB(function(result, err, mt){
        glbBuf = result; glbErr = err; meta = mt; resolve();
      });
    });
  }catch(e){
    glbErr = e;
  }finally{
    if(V && V.dispose) V.dispose();
  }
  if(glbErr || !glbBuf) return { ok:false, error:'GLB 生成失败: ' + (glbErr && glbErr.message) };

  // 2. 质量门禁
  const st = getStyle();
  const budget = parseInt((st.spec.machine.match(/(\d+)\s*~\s*(\d+)/) || [])[2], 10) || 900;
  const gate = {
    triangles: meta.triangles || 0,
    budget: budget,
    over: (meta.triangles || 0) > budget,
    severe: (meta.triangles || 0) > budget * 2,
    sizeCm: meta.sizeCm,
    materials: meta.materials,
  };

  // 3. 图标：上传优先；AI 模型用 256 缩略图；程序化几何用等轴测
  const previewSvg = isoPreview(m, 0, 132);
  const previewSvgFile = {
    path: m.id + '_preview.svg',
    b64: btoa(unescape(encodeURIComponent(previewSvg))),
  };
  let iconB64, previewFile;
  try{
    if(m.icon && m.iconSource !== 'generated'){
      iconB64 = await imagePngB64(m.icon, 256, '上传图标 ' + m.id);
      previewFile = previewSvgFile;
    }else if(isAI){
      if(!aiThumb256 || !aiThumb512) throw new Error('AI 缩略图不可用');
      iconB64 = aiThumb256.slice(aiThumb256.indexOf(',') + 1);
      previewFile = {
        path: m.id + '_preview.png',
        b64: aiThumb512.slice(aiThumb512.indexOf(',') + 1),
      };
    }else{
      iconB64 = await machineIconB64(m, 256);
      previewFile = previewSvgFile;
    }
  }catch(e){
    return { ok:false, error:'机器图标生成失败: ' + e.message };
  }

  // 4. POST 给 Bridge
  const body = {
    kind: 'machine',
    id: m.id,
    files: {
      mesh:    { path: m.id + '.glb', b64: bufToB64(glbBuf) },
      preview: previewFile,
      icon:    { path: m.id + '_icon.png', b64: iconB64 },
    },
    meta: {
      name: m.name, category: m.cat, footprint: m.footprint, tier: m.tier,
      triangles: gate.triangles, triangleBudget: budget,
      materials: gate.materials, sizeCm: gate.sizeCm,
      style: { presetId: st.id, name: st.name,
               accent: accentFor(m.cat, st) },
      gate: gate,
      textures: typeof FW_TEX !== 'undefined' ? Object.keys(FW_TEX.items) : [],
      contentHash: machineContentHash(m),
      styleHash: machineStyleHash(m),
      modelHash: machineModelHash(m),
      iconSource: m.iconSource || '',
      model: isAI ? {
        source: 'ai', provider: m.model.provider || '', file: m.model.file || '',
        taskId: m.model.taskId || '', triangles: gate.triangles,
        transform: fwNormalizeTransform(m.model.transform),
        autoFit: m.model.autoFit !== false,
      } : null,
    },
  };
  const r = await syncApi('export/asset', body);
  if(r && r.ok){
    syncLog('导出 ' + m.id + '：' + (r.files.mesh ? r.files.mesh[0] : '') +
            ((r.files.icon && r.files.icon[0]) ? ' + ' + r.files.icon[0] : '') +
            '（' + gate.triangles + ' 三角面' + (gate.over ? '，超预算 ' + budget + ' ⚠' : '') + '）',
            gate.severe ? 'warn' : 'ok');
    await syncLoadManifest();
  }
  return { ok: !!(r && r.ok), gate, response: r };
}

/** 批量导出（顺序执行，避免同时创建多个 WebGL 上下文） */
async function syncExportAll(ids, onProgress){
  const results = [];
  for(let i = 0; i < ids.length; i++){
    if(onProgress) onProgress(i, ids.length, ids[i]);
    results.push({ id: ids[i], r: await syncExportMachine(ids[i]) });
  }
  if(onProgress) onProgress(ids.length, ids.length, null);
  return results;
}

/** 把图片地址渲染成透明底 PNG 的 base64（图标 / 等轴测 SVG 共用）。 */
function imagePngB64(src, size, label){
  size = size || 256;
  return new Promise(function(resolve, reject){
    const img = new Image();
    img.onload = function(){
      try{
        const cv = document.createElement('canvas');
        cv.width = size; cv.height = size;
        const ctx = cv.getContext('2d');
        if(!ctx) throw new Error('Canvas 不可用');
        ctx.drawImage(img, 0, 0, size, size);
        const dataUrl = cv.toDataURL('image/png');
        resolve(dataUrl.slice(dataUrl.indexOf(',') + 1));
      }catch(e){ reject(e); }
    };
    img.onerror = function(){ reject(new Error(label + ' 加载失败')); };
    img.src = src;
  });
}

/** 把物品图标（自动生成 SVG 或自定义位图）渲染成透明底 PNG 的 base64 */
function iconPngB64(it, size){
  return imagePngB64(iconURL(it), size || 256, '图标 ' + it.id);
}

/** 把等轴测预览 SVG 渲染成透明底 PNG 的 base64（机器图标）。 */
function machineIconB64(m, size){
  const svg = isoPreview(m, 0, size || 256);
  return imagePngB64('data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg),
                     size || 256, '机器图标 ' + m.id);
}

/** 导出单个物品（图标 + 可选 AI 模型）到 Bridge（→ _Source/物品/图标/<中文名>/）。 */
async function syncExportItem(id){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线（先启动 tools/bridge.py）' };
  const it = (S.items || []).find(function(item){ return item.id === id; });
  if(!it) return { ok:false, error:'物品不存在: ' + id };

  const rec = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[it.id];
  const skipIcon = it.iconSource === 'generated' && hasAssetFile(rec, 'icon');
  const files = {};
  if(!skipIcon){
    try{
      files.icon = { path: it.id + '.png', b64: await iconPngB64(it, 256) };
    }catch(e){
      return { ok:false, error:'图标生成失败: ' + e.message };
    }
  }

  let modelMeta = null;
  if(it.model && it.model.source === 'ai'){
    try{
      const url = pipelineOutputURLFor(it.id, 'item', it.model.file);
      const response = await fetch(url);
      if(!response.ok) throw new Error('HTTP ' + response.status);
      const scene = await fwLoadGLBScene(await response.arrayBuffer());
      const transform = (it.model.autoFit === false && it.model.transform)
        ? fwNormalizeTransform(it.model.transform)
        : fwComputeFitTransform(scene, 'item', '');
      const baked = await new Promise(function(resolve, reject){
        fwBakeGLBScene(scene, transform, {
          name: it.id,
          forgeworks: { generator:'Forgeworks', source:'pipeline-ai',
                        id:it.id, name:it.name, kind:'item' },
        }, function(result, error){
          if(error) reject(error); else resolve(result);
        });
      });
      files.mesh = { path: it.id + '.glb', b64: bufToB64(baked) };
      modelMeta = {
        source:'ai', provider: it.model.provider || '', file: it.model.file || '',
        taskId: it.model.taskId || '', triangles: fwCountTriangles(scene),
        transform: fwNormalizeTransform(transform),
        autoFit: it.model.autoFit !== false,
      };
    }catch(e){
      return { ok:false, error:'AI 模型导出失败: ' + e.message };
    }
  }

  const st = getStyle();
  const body = {
    kind: 'item',
    id: it.id,
    files: files,
    meta: {
      name: it.name, type: it.type, visual: it.visual || null,
      tier: it.tier, color: it.color || '',
      customIcon: !!(it.icon && it.icon.trim()),
      iconSource: it.iconSource || '',
      size: 256,
      style: { presetId: st.id, name: st.name },
      iconHash: itemIconHash(it),
      modelHash: itemModelHash(it),
      model: modelMeta,
    },
  };
  const r = await syncApi('export/asset', body);
  if(r && r.ok){
    const iconName = r.files && r.files.icon ? r.files.icon[0] : '';
    syncLog('导出 ' + it.id + '：' + (iconName || '仅更新元数据') +
            (r.files && r.files.mesh ? ' + ' + r.files.mesh[0] : ''), 'ok');
    await syncLoadManifest();
  }
  return { ok: !!(r && r.ok), response: r };
}

/** 批量导出物品图标（照顺序跑，避免同时解码过多图片） */
async function syncExportAllItems(ids, onProgress){
  const results = [];
  for(let i = 0; i < ids.length; i++){
    if(onProgress) onProgress(i, ids.length, ids[i]);
    results.push({ id: ids[i], r: await syncExportItem(ids[i]) });
  }
  if(onProgress) onProgress(ids.length, ids.length, null);
  return results;
}

/** 导出单个元素图标到 Bridge（→ _Source/元素/<中文名>/<ID>.png）。 */
async function syncExportElement(id){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线（先启动 tools/bridge.py）' };
  const el = (S.elements || []).find(function(x){ return x.id === id; });
  if(!el) return { ok:false, error:'元素不存在: ' + id };

  const rec = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[el.id];
  const skipIcon = el.iconSource === 'generated' && hasAssetFile(rec, 'icon');
  const files = {};
  if(!skipIcon){
    try{
      files.icon = {
        path: el.id + '.png',
        b64: await imagePngB64(elementIconURL(el), 256, '元素图标 ' + el.id),
      };
    }catch(e){
      return { ok:false, error:'图标生成失败: ' + e.message };
    }
  }

  const st = getStyle();
  const body = {
    kind: 'element',
    id: el.id,
    files: files,
    meta: {
      name: el.name, symbol: el.symbol || '', tier: el.tier, color: el.color || '',
      customIcon: !!(el.icon && el.icon.trim()),
      iconSource: el.iconSource || '',
      size: 256,
      style: { presetId: st.id, name: st.name },
      iconHash: elementIconHash(el),
    },
  };
  const r = await syncApi('export/asset', body);
  if(r && r.ok){
    syncLog('导出元素 ' + el.id + '：' +
            ((r.files && r.files.icon) ? r.files.icon[0] : '仅更新元数据'), 'ok');
    await syncLoadManifest();
  }
  return { ok: !!(r && r.ok), response: r };
}

/** 批量导出元素图标（顺序执行） */
async function syncExportAllElements(ids, onProgress){
  const results = [];
  for(let i = 0; i < ids.length; i++){
    if(onProgress) onProgress(i, ids.length, ids[i]);
    results.push({ id: ids[i], r: await syncExportElement(ids[i]) });
  }
  if(onProgress) onProgress(ids.length, ids.length, null);
  return results;
}

/* ---------- 扫描核对 ---------- */

async function syncScan(){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线' };
  const r = await syncApi('manifest/scan', {});
  SYNC.lastScan = r;
  await syncLoadManifest();
  return r;
}

/* ---------- SSE 事件 ---------- */

let _sseSource = null;

function syncWatchEvents(onEvent){
  if(!SYNC.online || _sseSource) return;
  try{
    _sseSource = new EventSource('/api/events');
    _sseSource.onmessage = function(e){
      let ev = null;
      try{ ev = JSON.parse(e.data); }catch(_){}
      if(!ev) return;
      // 自己保存触发的事件不重复处理，避免每次自动保存都打断界面
      if(ev.kind === 'content.changed' && ev.data && ev.data.clientId === SYNC.clientId) return;
      syncLogEvent(ev);
      // 项目或 manifest 变了 → 刷新缓存（另一处界面/外部脚本触发的）
      if(ev.kind === 'project.opened' || ev.kind === 'project.created' || ev.kind === 'project.unbound'
          || ev.kind === 'project.ue_target'){
        Promise.all([syncLoadProjects(), syncLoadProjectContent(true), syncLoadManifest(), syncLoadUEManifest()])
          .then(function(){ if(onEvent) onEvent(ev); });
      }else if(ev.kind === 'content.changed'){
        if(SYNC.contentSaving || (typeof modalState !== 'undefined' && modalState) || SYNC.contentTimer){
          SYNC.contentStale = true;
          syncLog('检测到外部内容修改，编辑器关闭后同步', 'warn');
          if(onEvent) onEvent(ev);
        }else{
          syncReloadContent('AI/外部修改').then(function(){ if(onEvent) onEvent(ev); });
        }
      }else if(ev.kind === 'manifest.scanned' || ev.kind === 'asset.exported'
          || ev.kind === 'asset.published' || ev.kind === 'asset.conflict'
          || ev.kind === 'asset.conflict_resolved'){
        Promise.all([syncLoadManifest(), syncLoadUEManifest(), syncLoadConflicts()])
          .then(function(){ if(onEvent) onEvent(ev); });
      }else if(onEvent) onEvent(ev);
    };
    _sseSource.onerror = function(){ /* Bridge 重启时静默断开，下轮 ping 重连 */ };
  }catch(e){ /* 老浏览器/file:// 下没有 SSE，静默 */ }
}

/* ---------- 日志 ---------- */

function syncLog(msg, level){
  SYNC.log.unshift({ msg: msg, level: level || 'info', at: new Date().toLocaleTimeString('zh-CN') });
  if(SYNC.log.length > 60) SYNC.log.length = 60;
}
function syncLogEvent(ev){
  if(ev.kind === 'texture.progress') return;   // 进度已在贴图面板实时显示
  const map = {
    'project.opened':   ['已打开项目', 'ok'],
    'project.created':  ['已新建项目', 'ok'],
    'project.unbound':  ['已关闭项目', 'info'],
    'project.ue_target':['UE 导出目标已更新', 'info'],
    'asset.exported':   ['资产已导出：' + (ev.data && ev.data.id || ''), 'ok'],
    'asset.published':  ['已导出到 UE：' + ((ev.data && ev.data.assets) || []).join('、'), 'ok'],
    'manifest.scanned': ['目录核对完成', 'info'],
    'content.changed':  ['项目内容已由 ' + ((ev.data && ev.data.source) || '外部') + ' 更新', 'info'],
  };
  const m = map[ev.kind] || [ev.kind, 'info'];
  syncLog(m[0], m[1]);
}

/* ---------- 状态展示辅助 ---------- */

const SYNC_STATE_META = {
  none:     { label:'未导出', color:'var(--text-3)',   icon:'○' },
  exported: { label:'已导出', color:'var(--accent)',   icon:'✓' },
  stale:    { label:'待更新', color:'var(--amber)',    icon:'⟳' },
  missing:  { label:'文件丢失', color:'var(--red)',    icon:'✕' },
  tampered: { label:'被外部修改', color:'#d97706',     icon:'⚠' },
  conflict: { label:'冲突待裁决', color:'var(--red)', icon:'⚠' },
  external: { label:'外部资产', color:'var(--blue)',   icon:'+' },
};

function syncStateTag(state){
  const m = SYNC_STATE_META[state] || SYNC_STATE_META.none;
  return `<span class="pill" style="color:${m.color};border-color:${m.color}40"
    title="${m.label}">${m.icon} ${m.label}</span>`;
}

const UE_STATE_META = {
  none:     { label:'未导出', color:'var(--text-3)', icon:'○' },
  exported: { label:'已导出', color:'var(--accent)', icon:'✓' },
  stale:    { label:'待导出', color:'var(--amber)',  icon:'⟳' },
};

function ueStateTag(state){
  const m = UE_STATE_META[state] || UE_STATE_META.none;
  return `<span class="pill" style="color:${m.color};border-color:${m.color}40"
    title="${m.label}">${m.icon} ${m.label}</span>`;
}

/** UE 侧汇总：机器、物品图标、元素图标合计的已发布/待重导/未导出。 */
function syncUESummary(){
  const counts = { exported:0, stale:0, none:0 };
  S.machines.forEach(function(m){ counts[machineUEState(m).state]++; });
  (S.items || []).forEach(function(it){ counts[itemUEState(it).state]++; });
  (S.elements || []).forEach(function(el){ counts[elementUEState(el).state]++; });
  return counts;
}

/** 汇总所有机器的同步状态（机器列表顶栏/同步面板共用） */
function syncSummary(){
  const counts = {};
  S.machines.forEach(function(m){
    const s = SYNC.online ? machineSyncState(m).state : (SYNC.checkedAt ? 'unknown' : 'offline');
    counts[s] = (counts[s] || 0) + 1;
  });
  return counts;
}

/** 汇总所有物品图标的同步状态 */
function itemSyncSummary(){
  const counts = {};
  (S.items || []).forEach(function(it){
    const s = SYNC.online ? itemSyncState(it).state : (SYNC.checkedAt ? 'unknown' : 'offline');
    counts[s] = (counts[s] || 0) + 1;
  });
  return counts;
}

/** 汇总所有元素图标的同步状态 */
function elementSyncSummary(){
  const counts = {};
  (S.elements || []).forEach(function(el){
    const s = SYNC.online ? elementSyncState(el).state : (SYNC.checkedAt ? 'unknown' : 'offline');
    counts[s] = (counts[s] || 0) + 1;
  });
  return counts;
}
