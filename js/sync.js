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
  checkedAt: 0,
  status: null,           // /api/status 的结果
  manifest: null,         // manifest 缓存（Bridge 在线时以它为准）
  projects: { current: null, recent: [] },   // 当前项目 + 最近绑定过的目录
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
  if(!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

/** 探测 Bridge（2 秒超时）。不会抛异常，失败只置 online=false。 */
async function syncPing(force){
  if(!force && Date.now() - SYNC.checkedAt < 15000) return SYNC.online;
  SYNC.checkedAt = Date.now();
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
      await syncLoadManifest(); await syncLoadUEAssets(); await syncLoadConflicts();
    }
  }catch(e){
    SYNC.online = false;
    SYNC.status = null;
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

async function syncResolveConflict(conflict, choice){
  const result = await syncApi('conflicts/resolve', {id:conflict.id, conflictId:conflict.conflictId, choice});
  if(result && result.ok){ await syncLoadManifest(); await syncLoadConflicts(); }
  return result;
}

/* ---------- 绑定项目 ---------- */

async function syncBindProject(path){
  const r = await syncApi('project/bind', { path });
  if(r && r.ok){
    syncLog('已绑定项目：%s（%s）'.replace('%s', r.project.name).replace('%s', r.project.root), 'ok');
    await syncLoadProjects();
    await syncLoadManifest();
    await syncLoadUEAssets();
    await syncLoadConflicts();
    if(SYNC.status) SYNC.status.project = r.project;
  }
  return r;
}

async function syncUnbindProject(){
  const r = await syncApi('project/unbind', {});
  SYNC.manifest = null;
  SYNC.ueAssets = [];
  SYNC.conflicts = [];
  if(SYNC.status) SYNC.status.project = null;
  await syncLoadProjects();
  return r;
}

/** 侧栏顶部的项目切换器：始终可见，点开进入同步页 */
function renderProjectChip(){
  const el = document.getElementById('projectChip');
  if(!el) return;
  const project = SYNC.status && SYNC.status.project;
  const name = project ? (project.name || project.root) : '未绑定项目';
  const kind = project ? (project.kind === 'ue' ? 'UE 项目' : '工作区') : (SYNC.online ? '点击选择目录' : 'Bridge 未启动');
  el.innerHTML = `<button class="project-chip"
    title="${syncEscape(project ? project.root : '在同步页绑定项目目录')}">
    <span class="pc-label">项目</span>
    <span class="pc-name">${syncEscape(name)}</span>
    <span class="pc-kind"><i class="dot ${project ? 'on' : ''}"></i>${syncEscape(kind)}</span>
  </button>`;
  el.querySelector('button').onclick = ()=>{ cur = 'sync'; render(); syncHash('sync'); };
}

/* ---------- 状态机（三把 hash，sync-design §4.3） ---------- */

/** 简单确定性 hash（复用 icons.js 的 FNV-1a；同步场景不需要密码学强度） */
function syncDataHash(obj){
  return hashStr(JSON.stringify(obj)).toString(16);
}

/** 机器数据的 contentHash：影响几何/语义的字段 */
function machineContentHash(m){
  return syncDataHash({
    id: m.id, name: m.name, cat: m.cat, footprint: m.footprint,
    tier: m.tier, power: m.power,
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
  const stale = (saved.contentHash && saved.contentHash !== ch)
             || (saved.styleHash   && saved.styleHash   !== sh);
  return { state: stale ? 'stale' : 'exported', rec };
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
 * 导出单个机器到 Bridge（→ _Source/Machines/<ID>/）。
 * 流程：离屏 canvas → createViewer3D → toGLB → base64 → POST。
 * 同时带质量门禁信息（三角面 vs 风格规格）。
 */
async function syncExportMachine(id, opt){
  opt = opt || {};
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线（先启动 tools/bridge.py）' };
  const m = machineOf(id);
  if(!m) return { ok:false, error:'机器不存在: ' + id };
  if(!haveThree()) return { ok:false, error:'three.js 未加载' };

  // 1. 离屏生成 GLB（复用 3D 预览的完整管线，含风格材质与合并）
  const cv = document.createElement('canvas');
  cv.width = 64; cv.height = 64;
  let V = null;
  let glbBuf = null, glbErr = null, meta = null;
  try{
    V = createViewer3D(cv, m);
    await new Promise(function(resolve){
      V.toGLB(function(result, err, mt){
        glbBuf = result; glbErr = err; meta = mt; resolve();
      });
    });
  }finally{
    if(V && V.dispose) V.dispose();
  }
  if(glbErr || !glbBuf) return { ok:false, error:'GLB 生成失败: ' + (glbErr && glbErr.message) };

  // 2. 质量门禁（sync-design §5 风险 R14：三角面超预算）
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

  // 3. 等轴测预览（SVG 文本直接落盘，Bridge 不区分文件类型）
  const previewSvg = isoPreview(m, 0, 132);

  // 4. POST 给 Bridge
  const body = {
    kind: 'machine',
    id: m.id,
    files: {
      mesh:    { path: m.id + '.glb', b64: bufToB64(glbBuf) },
      preview: { path: m.id + '_preview.svg', b64: btoa(unescape(encodeURIComponent(previewSvg))) },
    },
    meta: {
      name: m.name, category: m.cat, footprint: m.footprint, tier: m.tier,
      triangles: gate.triangles, triangleBudget: budget,
      materials: gate.materials, sizeCm: gate.sizeCm,
      style: { presetId: st.id, name: st.name,
               accent: accentFor(m.cat, st) },
      gate: gate,
      contentHash: machineContentHash(m),
      styleHash: machineStyleHash(m),
    },
  };
  const r = await syncApi('export/asset', body);
  if(r && r.ok){
    syncLog('导出 ' + m.id + '：' + (r.files.mesh ? r.files.mesh[0] : '') +
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
      syncLogEvent(ev);
      // 项目或 manifest 变了 → 刷新缓存（另一处界面/外部脚本触发的）
      if(ev.kind === 'manifest.scanned' || ev.kind === 'asset.exported' || ev.kind === 'project.bound'
          || ev.kind === 'asset.conflict' || ev.kind === 'asset.conflict_resolved'){
        Promise.all([syncLoadManifest(), syncLoadConflicts()]).then(function(){ if(onEvent) onEvent(ev); });
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
  const map = {
    'project.bound':   ['已绑定项目', 'ok'],
    'project.unbound': ['已解除绑定', 'info'],
    'asset.exported':  ['资产已导出：' + (ev.data && ev.data.id || ''), 'ok'],
    'manifest.scanned':['目录核对完成', 'info'],
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

/** 汇总所有机器的同步状态（机器列表顶栏/同步面板共用） */
function syncSummary(){
  const counts = {};
  S.machines.forEach(function(m){
    const s = SYNC.online ? machineSyncState(m).state : (SYNC.checkedAt ? 'unknown' : 'offline');
    counts[s] = (counts[s] || 0) + 1;
  });
  return counts;
}
