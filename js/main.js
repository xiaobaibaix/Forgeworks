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
// 版本戳：直接从 main.js 自己的 src 里读 ?v=，保证与资源版本号一致
(function(){
  const el = document.getElementById('buildStamp');
  if(!el) return;
  const tag = document.querySelector('script[src*="js/main.js"]');
  const v = tag ? (tag.getAttribute('src').split('?v=')[1] || '') : '';
  el.textContent = v ? 'build ' + v : (typeof BUILD_STAMP !== 'undefined' ? BUILD_STAMP : '');
})();
render();
