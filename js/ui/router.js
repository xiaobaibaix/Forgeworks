/* Forgeworks · js/ui/router.js */
/* ---------- 视图路由 ---------- */

/**
 * 同步 URL hash（纯装饰功能，绝不能影响主流程）
 * 注意：file:// 协议下 document.origin 是 null，history.replaceState 会抛
 * SecurityError。必须 try/catch，否则点击导航会被异常打断。
 */
function syncHash(v){
  try{
    if(location.hash !== '#'+v) history.replaceState(null,'','#'+v);
  }catch(e){
    // file:// 下不支持，静默忽略；用 location.hash 兜底（部分浏览器允许）
    try{ if(location.hash !== '#'+v) location.hash = v; }catch(_){}
  }
}

/**
 * 视图注册表。
 *
 * ⚠️ 必须延迟构建：这个文件先于各 views/*.js 加载，
 * 如果在顶层直接写 `{render: renderItems}`，加载时就会去解析一个还不存在的
 * 函数名，抛 ReferenceError。改成函数，由 main.js 在全部脚本载入后调用。
 */
let VIEWS = null;

/* 导航分组：侧栏与页头面包屑共用这一份定义，避免两处漂移 */
const NAV_GROUPS=[
  ['内容定义',['elements','items','machines','recipes','techs']],
  ['美术资源',['style','assets','prompts']],
  ['分析工具',['validate','balance','solve','graph']],
  ['输出与同步',['export','sync','pipeline']],
];

/* 仍留在分组里以保持面包屑，但不渲染侧栏入口 */
const NAV_HIDDEN=['pipeline'];

const NAV_ICONS={
  elements:'<path d="M12 3l7.5 4.4v9.2L12 21l-7.5-4.4V7.4z"/><path d="M12 8v8M9 12h6"/>',
  items:'<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  machines:'<circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>',
  recipes:'<path d="M4 7h5l3 5h8M4 17h5l3-5"/><circle cx="20" cy="12" r="1.6"/>',
  techs:'<path d="M12 3v5M6 21v-5M18 21v-5M12 8l-6 3v5M12 8l6 3v5"/>',
  style:'<path d="M12 3a9 9 0 100 18h1.4a1.8 1.8 0 001.2-3.1 1.8 1.8 0 011.3-3.1H18a3 3 0 003-3A9 9 0 0012 3z"/><circle cx="8.5" cy="10" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="15.5" cy="10" r="1"/>',
  assets:'<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M4 18l5-5 4 4 2-2 5 5"/>',
  prompts:'<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M18 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  validate:'<path d="M12 3l7 3v5c0 4.4-2.9 7.8-7 10-4.1-2.2-7-5.6-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
  balance:'<path d="M12 4v16M6 20h12M5 8h14M5 8l-2.5 5a3 3 0 005 0zM19 8l-2.5 5a3 3 0 005 0z"/>',
  solve:'<circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M8 6h5a5 5 0 015 5v0a5 5 0 01-5 5h-2a4 4 0 00-4 4"/>',
  graph:'<circle cx="6" cy="6" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="12" cy="18" r="2"/><path d="M7.8 6.4l8.2.4M7 7.8l4 8.4M16.8 8.8l-3.8 7.4"/>',
  export:'<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
  sync:'<path d="M20 11a8 8 0 10-2.3 6.3M20 5v6h-6"/>',
  pipeline:'<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5M3 17l9 5 9-5"/>',
};

function navIcon(k){
  return `<svg class="ni" viewBox="0 0 24 24" aria-hidden="true">${NAV_ICONS[k]||''}</svg>`;
}

function makeViews(){
  return {
    elements:{title:'元素', sub:'游戏内元素周期表', render:()=>renderElements()},
    items:{title:'物品', sub:'矿物、精矿、零件、模块、宏构', render:()=>renderItems()},
    machines:{title:'机器', sub:'采集 / 分离 / 冶炼 / 加工 / 组装', render:()=>renderMachines()},
    recipes:{title:'配方', sub:'生产链的核心', render:()=>renderRecipes()},
    techs:{title:'科技树', sub:'配方解锁链', render:()=>renderTechs()},
    style:{title:'风格', sub:'项目美术风格的单一来源', render:()=>renderStyle()},
    assets:{title:'资源', sub:'物品图标与模型', render:()=>renderAssets()},
    prompts:{title:'美术需求', sub:'建筑/物品的生成描述词', render:()=>renderPrompts()},
    validate:{title:'校验', sub:'数据健康检查', render:()=>renderValidate()},
    balance:{title:'物料平衡', sub:'原料 ↔ 成品 双向换算', render:()=>renderBalance()},
    solve:{title:'产线求解器', sub:'目标物品 → 完整生产链', render:()=>renderSolve()},
    graph:{title:'依赖图谱', sub:'生产链结构可视化', render:()=>renderGraph()},
    sync:{title:'同步', sub:'项目工程 · 资源生成 · 导出到 UE', render:()=>renderSync()},
    pipeline:{title:'生成管线', sub:'资产生成图 · 本地优先 · 按需运行', render:()=>renderPipeline()},
    export:{title:'导出', sub:'JSON / UE DataTable CSV / Markdown', render:()=>renderExport()},
  };
}

function renderNav(){
  const nav=document.getElementById('nav');
  let h='';
  NAV_GROUPS.forEach(([g,keys],gi)=>{
    h+=`<div class="nav-group"><span class="ng-i">${String(gi+1).padStart(2,'0')}</span><span>${g}</span></div>`;
    keys.forEach(k=>{
      if(NAV_HIDDEN.indexOf(k)!==-1) return;
      // 只对「数据类」视图显示条目数；工具类视图不显示无意义的 0
      const dataViews = ['elements','items','machines','recipes','techs','assets','prompts'];
      let cnt = '';
      if(dataViews.includes(k)){
        const n = k==='elements' ? S.elements.length
                : k==='assets'   ? S.items.length
                : k==='prompts'  ? S.machines.length + S.items.length
                : S[k].length;
        cnt = `<span class="cnt">${n}</span>`;
      }
      h+=`<div class="nav-item ${cur===k?'active':''}" data-v="${k}" role="link" tabindex="0"
        ${cur===k?'aria-current="page" ':''}title="${VIEWS[k].title}">${navIcon(k)}<span class="lbl">${VIEWS[k].title}</span>${cnt}</div>`;
    });
  });
  const scrollTop=nav.scrollTop;
  nav.innerHTML=h;
  nav.scrollTop=scrollTop;          // 重绘导航不应把列表滚回顶部
  const go=el=>{
    cur=el.dataset.v;
    render();                       // 先切换视图，确保 UI 一定响应
    syncHash(cur);                  // 再尝试同步 URL（失败不影响切换）
  };
  nav.querySelectorAll('.nav-item').forEach(el=>{
    el.onclick=()=>go(el);
    el.onkeydown=e=>{
      if(e.key==='Enter' || e.key===' '){ e.preventDefault(); go(el); }
    };
  });
}

function menuGroupOf(key){
  const hit=NAV_GROUPS.find(([,keys])=>keys.includes(key));
  return hit ? hit[0] : '';
}

function render(){
  renderNav();
  if(typeof renderProjectChip==='function') renderProjectChip();
  const v=VIEWS[cur];
  document.getElementById('viewTitle').textContent=v.title;
  document.getElementById('viewSub').textContent=v.sub;
  const crumb=document.getElementById('viewCrumb');
  if(crumb) crumb.textContent=menuGroupOf(cur);
  document.getElementById('headActions').innerHTML='';
  document.getElementById('view').innerHTML='';
  v.render();
  updateStat();
}
function updateStat(){
  const el=document.getElementById('statLine');
  if(!el) return;
  const stats=[['物品',S.items.length],['机器',S.machines.length],
               ['配方',S.recipes.length],['科技',S.techs.length]];
  el.innerHTML=stats.map(([k,n])=>`<span><em>${k}</em><b>${n}</b></span>`).join('');
}
