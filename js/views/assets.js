/* Forgeworks · js/views/assets.js */
/* ---------- 资源视图（图标 / 模型）---------- */
let ASSET_FILTER = 'all';

function renderAssets(){
  const v=document.getElementById('view');
  const stats = {
    total: S.items.length,
    custom: S.items.filter(i=>i.icon && i.icon.trim()).length,
    auto: S.items.filter(i=>!(i.icon && i.icon.trim())).length,
    noModel: S.items.filter(i=>i.modelStatus==='none').length,
    primitive: S.items.filter(i=>i.modelStatus==='primitive').length,
    needed: S.items.filter(i=>i.modelStatus==='needed').length,
    done: S.items.filter(i=>i.modelStatus==='done').length,
    hasMesh: S.items.filter(i=>i.mesh && i.mesh.trim()).length,
  };

  let h=`<div class="grid2" style="margin-bottom:16px">
    <div class="stat"><div class="v">${stats.total}</div><div class="k">物品总数</div></div>
    <div class="stat"><div class="v" style="color:var(--accent)">${stats.auto}</div><div class="k">自动生成图标</div></div>
    <div class="stat"><div class="v" style="color:var(--blue)">${stats.custom}</div><div class="k">自定义图标</div></div>
    <div class="stat"><div class="v" style="color:var(--amber)">${stats.needed}</div><div class="k">待建模</div></div>
  </div>`;

  h+=`<div class="card">
    <h3>图标与模型资源</h3>
    <p class="hint">
      图标由「物品颜色 × 物品类型」算法生成，无需美术资源即可让每个物品有可辨识的视觉。
      可以逐个上传替换，也可以整包导出成 UE 图集。
    </p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      <button class="primary" id="asSheet">导出图标图集 (PNG)</button>
      <button id="asAtlas">导出图集坐标 (JSON)</button>
      <button id="asSvg">导出全部图标 (SVG)</button>
      <button id="asZipNote">导出说明 (Markdown)</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      ${['all','custom','primitive','needed','done','none'].map(f=>{
        const label = f==='all'?'全部':f==='custom'?'已自定义图标':f==='primitive'?'基础几何体':
                      f==='needed'?'待建模':f==='done'?'已完成':'无需模型';
        const n = f==='all'?S.items.length : f==='custom'?stats.custom : S.items.filter(i=>i.modelStatus===f).length;
        const active = ASSET_FILTER===f;
        return `<button class="sm" data-filter="${f}" style="${active?'background:var(--accent);color:#fff;border-color:var(--accent)':''}">${label} (${n})</button>`;
      }).join('')}
    </div>
  </div>`;

  // 过滤
  let list = S.items;
  if(ASSET_FILTER==='custom') list = list.filter(i=>i.icon && i.icon.trim());
  else if(ASSET_FILTER!=='all') list = list.filter(i=>i.modelStatus===ASSET_FILTER);

  // 网格卡片
  h+=`<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(156px,1fr));gap:10px">`;
  list.forEach(it=>{
    const ms = MODEL_LABELS[it.modelStatus] || MODEL_LABELS.primitive;
    const hasCustom = !!(it.icon && it.icon.trim());
    const hasMesh = !!(it.mesh && it.mesh.trim());
    h+=`<div class="asset-card" data-item="${it.id}"
      style="background:var(--panel);border:1px solid var(--border);border-radius:10px;
             padding:12px;cursor:pointer;transition:.12s;text-align:center">
      <div style="width:56px;height:56px;margin:0 auto 8px;display:flex;align-items:center;justify-content:center;
                  background:var(--panel-2);border-radius:8px;border:1px solid var(--border)">
        ${iconHTML(it, 44)}
      </div>
      <div style="font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"
           title="${it.name}">${it.name}</div>
      <div style="font-size:10px;color:var(--text-3);font-family:var(--mono);margin-bottom:6px;
                  white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${it.id}</div>
      <div style="display:flex;gap:3px;justify-content:center;flex-wrap:wrap">
        ${tierTag(it.tier)}
        <span class="tag" style="background:${ms.bg};color:${ms.fg}">${ms.t}</span>
      </div>
      ${hasCustom?`<div style="font-size:9.5px;color:var(--blue);margin-top:4px">自定义图标</div>`:''}
      ${hasMesh?`<div style="font-size:9.5px;color:var(--accent);margin-top:2px">已绑模型</div>`:''}
      <button class="sm" data-genicon="${it.id}"
        style="margin-top:6px;font-size:10px;padding:3px 8px">生成图标 →</button>
    </div>`;
  });
  h+=`</div>`;

  // 建模任务清单
  const needBuild = S.items.filter(i=>i.modelStatus==='needed' || i.modelStatus==='primitive');
  h+=`<div class="card" style="margin-top:16px">
    <h3>建模任务清单</h3>
    <p class="hint">按类型给出建议的建模方式。你项目用 UE 内置 mesh，所以大部分物品可以用基础几何体拼。</p>
    <div class="scroll-x"><table>
      <thead><tr><th>图标</th><th>物品</th><th>类型</th><th>模型状态</th><th>网格路径</th><th>建模建议</th></tr></thead><tbody>`;
  needBuild.forEach(it=>{
    const ms = MODEL_LABELS[it.modelStatus];
    h+=`<tr>
      <td>${iconHTML(it, 22)}</td>
      <td>${it.name}<br><code style="font-size:10px;color:var(--text-3)">${it.id}</code></td>
      <td><span class="pill">${typeLabel(it.type)}</span></td>
      <td><span class="tag" style="background:${ms.bg};color:${ms.fg}">${ms.t}</span></td>
      <td>${it.mesh?`<code style="font-size:10px">${it.mesh}</code>`:'<span style="color:var(--text-3)">—</span>'}</td>
      <td style="color:var(--text-2);font-size:11.5px">${modelHint(it)}</td>
    </tr>`;
  });
  h+=`</tbody></table></div></div>`;

  v.innerHTML=h;

  // 交互
  v.querySelectorAll('[data-filter]').forEach(b=>{
    b.onclick=()=>{ ASSET_FILTER=b.dataset.filter; renderAssets(); };
  });
  v.querySelectorAll('.asset-card').forEach(c=>{
    c.onmouseenter=()=>{ c.style.borderColor='var(--accent)'; c.style.transform='translateY(-1px)'; };
    c.onmouseleave=()=>{ c.style.borderColor='var(--border)'; c.style.transform='none'; };
    c.onclick=()=>openEditor('items', c.dataset.item);
  });
  v.querySelectorAll('[data-genicon]').forEach(b=>{
    b.onclick=function(e){
      e.stopPropagation();
      pipelineEnter(b.dataset.genicon, {view:'assets', assetId:b.dataset.genicon});
    };
  });
  document.getElementById('asSheet').onclick=()=>exportIconSheet();
  document.getElementById('asAtlas').onclick=()=>exportAtlasJSON();
  document.getElementById('asSvg').onclick=()=>exportSvgPack();
  document.getElementById('asZipNote').onclick=()=>download('图标资源说明.md', iconDocMarkdown(), 'text/markdown');
}

/* ---------- 图标导出 ---------- */

/**
 * 导出精灵图集：把全部图标画进一张 PNG，并给出每个图标的 UV 坐标。
 * 这是 UE 导入最实用的形式（一张贴图 + 一份坐标表）。
 */
async function exportIconSheet(cell){
  cell = cell || 128;
  const cols = 8;
  const items = S.items;
  const rows = Math.ceil(items.length / cols);
  const W = cols*cell, H = rows*cell;

  if(typeof document.createElement('canvas').getContext !== 'function'){
    toast('当前环境不支持 Canvas，请用「导出全部图标 (SVG)」'); return;
  }
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  if(!ctx){ toast('Canvas 初始化失败'); return; }

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0,0,W,H);
  // 每格画淡边框，方便在 UE 里切图
  ctx.strokeStyle = 'rgba(0,0,0,.08)';
  ctx.lineWidth = 1;

  const atlas = {cell, cols, rows, width:W, height:H, frames:{}};
  toast('正在合成图集，请稍候…');

  for(let i=0;i<items.length;i++){
    const it = items[i];
    const cx = (i%cols)*cell, cy = Math.floor(i/cols)*cell;
    try{
      await drawIconToCanvas(ctx, it, cx, cy, cell);
    }catch(e){
      // 单张失败不影响整体
      console.warn('icon draw fail', it.id, e);
    }
    ctx.strokeRect(cx+0.5, cy+0.5, cell-1, cell-1);
    atlas.frames[it.id] = {x:cx, y:cy, w:cell, h:cell,
      u0:+(cx/W).toFixed(6), v0:+(cy/H).toFixed(6),
      u1:+((cx+cell)/W).toFixed(6), v1:+((cy+cell)/H).toFixed(6)};
  }

  canvas.toBlob(blob=>{
    if(!blob){ toast('图集生成失败'); return; }
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=`StellarEra_IconSheet_${cell}.png`;
    document.body.appendChild(a); a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},150);
    toast(`图集已导出 ${W}×${H}（${items.length} 个图标）`);
  }, 'image/png');

  // 顺手把坐标存起来，供 atlas JSON 复用
  window._lastAtlas = atlas;
}

function drawIconToCanvas(ctx, item, x, y, size){
  return new Promise((resolve, reject)=>{
    const img = new Image();
    img.onload = ()=>{
      // 留 8% 边距
      const pad = size*0.08;
      ctx.drawImage(img, x+pad, y+pad, size-pad*2, size-pad*2);
      resolve();
    };
    img.onerror = ()=>reject(new Error('svg load fail'));
    img.src = iconURL(item);
  });
}

function exportAtlasJSON(){
  if(!window._lastAtlas){
    toast('请先点「导出图标图集」，坐标基于上次导出的图集');
    return;
  }
  const data = window._lastAtlas;
  download('StellarEra_IconAtlas.json', JSON.stringify(data,null,2), 'application/json');
  toast('图集坐标已导出');
}

/** 导出全部图标为独立 SVG 文件（逐个下载，量大时较慢） */
function exportSvgPack(){
  const items = S.items;
  if(items.length > 120 && !confirm(`将逐个下载 ${items.length} 个 SVG，确定继续？`)) return;
  let i = 0;
  const step = ()=>{
    if(i >= items.length){ toast(`已导出 ${items.length} 个 SVG`); return; }
    const it = items[i++];
    // 自定义图标是位图，跳过
    if(it.icon && it.icon.trim()){
      step(); return;
    }
    download(`${it.id}.svg`, makeIconSVG(it, 128), 'image/svg+xml');
    setTimeout(step, 120);   // 间隔，避免浏览器拦截批量下载
  };
  step();
}

/** 资源说明文档 */
function iconDocMarkdown(){
  let h = `# StellarEra 图标资源说明\n\n`;
  h += `> 由内容设计器自动生成 · ${new Date().toLocaleString('zh-CN')}\n\n`;
  h += `## 图标生成规则\n\n`;
  h += `图标由「物品颜色 × 物品类型」算法生成，不依赖美术资源。\n\n`;
  h += `| 类型 | 图标形状 |\n|---|---|\n`;
  h += `| 原料 raw | 不规则矿石块（ID 哈希扰动轮廓） |\n`;
  h += `| 精矿 concentrate | 料堆 + 颗粒 |\n`;
  h += `| 锭 ingot | 梯形锭 + 顶面高光 |\n`;
  h += `| 零件 part | 齿轮（8 齿） |\n`;
  h += `| 模块 module | 电路基板 |\n`;
  h += `| 宏构 mega | 环形结构 |\n`;
  h += `| 副产物 byproduct | 矿石块 |\n`;
  h += `| 流体 fluid | 液滴 |\n\n`;
  h += `## 导入 UE\n\n`;
  h += `1. 点「导出图标图集 (PNG)」得到 \`StellarEra_IconSheet_128.png\`（8 列网格）\n`;
  h += `2. 点「导出图集坐标 (JSON)」得到 \`StellarEra_IconAtlas.json\`（含每格 UV）\n`;
  h += `3. 在 UE 里把 PNG 导入为 Texture2D，Texture Group 设为 \`UI\`，关闭 Mip 或设为 Sharpen\n`;
  h += `4. 创建 Material 或直接做成 UI Brush，用 UV 坐标取子区域\n`;
  h += `5. 若需要独立贴图，改用「导出全部图标 (SVG)」，再批量转 PNG\n\n`;
  h += `## 模型状态说明\n\n`;
  h += `| 状态 | 含义 | 数量 |\n|---|---|---|\n`;
  Object.entries(MODEL_LABELS).forEach(([k,v])=>{
    const n = S.items.filter(i=>i.modelStatus===k).length;
    h += `| ${v.t} | ${k} | ${n} |\n`;
  });
  h += `\n## 物品图标清单\n\n| ID | 名称 | 类型 | 图标 | 模型状态 | 网格路径 |\n|---|---|---|---|---|---|\n`;
  S.items.forEach(it=>{
    const ms = MODEL_LABELS[it.modelStatus];
    h += `| \`${it.id}\` | ${it.name} | ${typeLabel(it.type)} | ${(it.icon&&it.icon.trim())?'自定义':'自动生成'} | ${ms.t} | ${it.mesh||'—'} |\n`;
  });
  return h;
}
