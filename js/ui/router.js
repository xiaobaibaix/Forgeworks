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

function makeViews(){
  return {
    elements:{title:'元素', sub:'游戏内元素周期表', render:()=>renderElements()},
    items:{title:'物品', sub:'矿物、精矿、零件、模块、宏构', render:()=>renderItems()},
    machines:{title:'机器', sub:'采集 / 分离 / 冶炼 / 加工 / 组装', render:()=>renderMachines()},
    recipes:{title:'配方', sub:'生产链的核心', render:()=>renderRecipes()},
    techs:{title:'科技树', sub:'恒星纪元解锁链', render:()=>renderTechs()},
    eras:{title:'恒星纪元', sub:'元素与星球类型解锁', render:()=>renderEras()},
    style:{title:'风格', sub:'项目美术风格的单一来源', render:()=>renderStyle()},
    assets:{title:'资源', sub:'物品图标与模型', render:()=>renderAssets()},
    prompts:{title:'美术需求', sub:'建筑/物品的生成描述词', render:()=>renderPrompts()},
    validate:{title:'校验', sub:'数据健康检查', render:()=>renderValidate()},
    balance:{title:'物料平衡', sub:'原料 ↔ 成品 双向换算', render:()=>renderBalance()},
    solve:{title:'产线求解器', sub:'目标物品 → 完整生产链', render:()=>renderSolve()},
    graph:{title:'依赖图谱', sub:'生产链结构可视化', render:()=>renderGraph()},
    export:{title:'导出', sub:'JSON / UE DataTable CSV / Markdown', render:()=>renderExport()},
  };
}

function renderNav(){
  const nav=document.getElementById('nav');
  const groups=[
    ['内容定义',['elements','items','machines','recipes','techs','eras']],
    ['美术资源',['style','assets','prompts']],
    ['分析工具',['validate','balance','solve','graph']],
    ['输出',['export']],
  ];
  let h='';
  groups.forEach(([g,keys])=>{
    h+=`<div class="nav-group">${g}</div>`;
    keys.forEach(k=>{
      // 只对「数据类」视图显示条目数；工具类视图不显示无意义的 0
      const dataViews = ['elements','items','machines','recipes','techs','eras','assets','prompts'];
      let cnt = '';
      if(dataViews.includes(k)){
        const n = k==='elements' ? S.elements.length
                : k==='eras'     ? S.eras.length
                : k==='assets'   ? S.items.length
                : k==='prompts'  ? S.machines.length + S.items.length
                : S[k].length;
        cnt = `<span class="cnt">${n}</span>`;
      }
      h+=`<div class="nav-item ${cur===k?'active':''}" data-v="${k}">${VIEWS[k].title}${cnt}</div>`;
    });
  });
  nav.innerHTML=h;
  nav.querySelectorAll('.nav-item').forEach(el=>el.onclick=()=>{
    cur=el.dataset.v;
    render();                       // 先切换视图，确保 UI 一定响应
    syncHash(cur);                  // 再尝试同步 URL（失败不影响切换）
  });
}

function render(){
  renderNav();
  const v=VIEWS[cur];
  document.getElementById('viewTitle').textContent=v.title;
  document.getElementById('viewSub').textContent=v.sub;
  document.getElementById('headActions').innerHTML='';
  document.getElementById('view').innerHTML='';
  v.render();
  updateStat();
}
function updateStat(){
  document.getElementById('statLine').textContent =
    `${S.items.length} 物品 · ${S.machines.length} 机器 · ${S.recipes.length} 配方 · ${S.techs.length} 科技`;
}
