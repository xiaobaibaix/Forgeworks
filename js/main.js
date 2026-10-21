/* Forgeworks · js/main.js */
/* ---------- 快捷键 ---------- */
document.addEventListener('keydown',e=>{
  if(e.key==='Escape' && !document.getElementById('mask').classList.contains('hide')) closeModal();
  if((e.metaKey||e.ctrlKey) && e.key==='s'){ e.preventDefault(); saveState(); }
});

/* ---------- 启动 ---------- */
document.getElementById('btnSave').onclick=saveState;
document.getElementById('btnReset').onclick=()=>{
  if(!confirm('确认恢复预填数据？当前所有修改将丢失。')) return;
  S=JSON.parse(JSON.stringify(SEED));
  normalizeAssets(S);
  saveState(); clearCostCache(); clearIconCache(); // 版本戳：直接从 main.js 自己的 src 里读 ?v=，保证与资源版本号一致
(function(){
  const el = document.getElementById('buildStamp');
  if(!el) return;
  const tag = document.querySelector('script[src*="js/main.js"]');
  const v = tag ? (tag.getAttribute('src').split('?v=')[1] || '') : '';
  el.textContent = v ? 'build ' + v : (typeof BUILD_STAMP !== 'undefined' ? BUILD_STAMP : '');
})();
render(); toast('已恢复预填数据');
};

// 所有脚本已载入，现在才构建视图表（见 router.js 里的说明）
VIEWS = makeViews();

// 启动时读取 URL hash，支持直接打开 #balance / #solve 等视图
(function initFromHash(){
  const h=(location.hash||'').replace('#','');
  if(h && VIEWS[h]) cur=h;
})();

// 探测 Forge Bridge（tools/bridge.py）。异步、非阻塞：
// 离线时 renderSync 会显示启动指引，其余功能完全不受影响。
(function initSync(){
  if(typeof syncPing !== 'function') return;
  syncPing(true).then(function(online){
    if(typeof renderProjectChip === 'function') renderProjectChip();
    if(!online) return;
    syncWatchEvents(function(){
      // 事件到来时，若正停在同步页就局部刷新（避免打断用户操作）
      if(cur === 'sync'){ syncLoadManifest().then(function(){ renderSyncLog(); renderSyncTable(); renderSyncSummary(); }); }
    });
    // 首次探测成功 → 若在同步页，整页重绘一次（显示绑定/导出区）
    if(cur === 'sync') render();
  });
})();
// 版本戳：直接从 main.js 自己的 src 里读 ?v=，保证与资源版本号一致
(function(){
  const el = document.getElementById('buildStamp');
  if(!el) return;
  const tag = document.querySelector('script[src*="js/main.js"]');
  const v = tag ? (tag.getAttribute('src').split('?v=')[1] || '') : '';
  el.textContent = v ? 'build ' + v : (typeof BUILD_STAMP !== 'undefined' ? BUILD_STAMP : '');
})();
render();
