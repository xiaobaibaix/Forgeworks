/* Forgeworks · js/engines/viewer3d.js
   ============================================================
   轻量 3D 体块查看器（Canvas 2D 软件渲染，零依赖）
   ------------------------------------------------------------
   为什么不用 three.js：
     1. 本项目承诺"零依赖、离线可用"，引入 600KB 的库会破坏这个前提
     2. 当前阶段模型就是程序化的方块堆，不需要 PBR / 骨骼 / 蒙皮
     3. 自己画只需要 ~300 行，而且能完全控制交互手感

   能力：
     - 鼠标左键拖动 = 360° 自由环绕（yaw 无限制，pitch 有极角限制）
     - 滚轮 / 双指 = 缩放
     - 双击 = 复位
     - 可选自动旋转
     - 导出当前视角 PNG

   渲染原理：
     盒子 → 旋转变换 → 透视投影 → 画家算法排序 → 平面着色 → 描边
   ============================================================ */

/* ---------- 建筑体块构成 ----------
   每个部件: { c:[x,y,z], s:[w,h,d], col }
   坐标系：y 向上，原点在地面中心，单位 = 格
   ---------------------------------------- */

const PART_COLORS = {
  base:  '#c6c3bc',   // 混凝土基座
  body:  '#a4a9b1',   // 主体钢构
  dark:  '#6f757d',   // 暗部/管道
  light: '#d6dae0',   // 亮部/外壳
  glass: '#8fb8d8',   // 玻璃
};

// 各分类的强调色
const ACCENT_BY_CAT = {
  '采集':'#d9a441', '分离':'#5fa8c4', '冶炼':'#e07b39', '合金':'#8fa3b8',
  '化工':'#6fb86f', '加工':'#7d8b9e', '组装':'#3fa887', '回收':'#b09a6a',
};

function parseFootprint(fp){
  const a = String(fp || '1×1').split(/[×xX]/).map(n => parseFloat(n) || 1);
  return [a[0], a[1] || a[0]];
}

/**
 * 把一个建筑展开成若干长方体
 * @returns {{parts: Array, W:number, D:number, H:number}}
 */
function buildMachineParts(m){
  const [W, D] = parseFootprint(m.footprint);
  const acc = ACCENT_BY_CAT[m.cat] || '#8a97a8';
  const parts = [];
  const add = (x,y,z, w,h,d, col)=>parts.push({c:[x,y,z], s:[w,h,d], col});

  // 所有建筑共有的基座
  add(0, 0.09, 0, W*0.94, 0.18, D*0.94, PART_COLORS.base);

  switch(m.cat){
    case '采集': {
      const tw = W*0.26;
      add(0, 0.18 + 0.75, 0, tw, 1.5, tw, PART_COLORS.body);           // 塔身
      add(0, 0.18 + 1.62, 0, tw*0.5, 0.24, tw*0.5, PART_COLORS.dark);  // 塔顶
      add(0, 0.18 + 1.82, 0, tw*0.22, 0.16, tw*0.22, acc);             // 警示灯
      add(W*0.32, 0.55, D*0.30, W*0.22, 0.5, D*0.22, PART_COLORS.dark); // 料斗
      add(0, 0.18 + 0.55, 0, tw*0.16, 0.9, tw*0.16, PART_COLORS.light); // 钻杆
      break;
    }
    case '分离': {
      add(-W*0.20, 0.18 + 0.42, -D*0.08, W*0.36, 0.84, D*0.36, PART_COLORS.body);
      add( W*0.24, 0.18 + 0.31,  D*0.14, W*0.30, 0.62, D*0.30, PART_COLORS.light);
      add(0, 0.18 + 1.02, 0, W*0.62, 0.10, D*0.12, PART_COLORS.dark);  // 管路
      add(-W*0.20, 0.18 + 0.90, 0, W*0.10, 0.16, D*0.10, acc);         // 阀门
      add( W*0.24, 0.18 + 0.70, 0, W*0.09, 0.14, D*0.09, acc);
      break;
    }
    case '冶炼': {
      add(0, 0.18 + 0.62, 0, W*0.62, 1.24, D*0.62, PART_COLORS.body);   // 炉体
      add(W*0.22, 0.18 + 1.05, D*0.20, W*0.18, 1.9, D*0.18, PART_COLORS.dark); // 烟囱
      add(0, 0.18 + 0.30, D*0.33, W*0.26, 0.42, D*0.04, acc);           // 炉门（发光）
      add(-W*0.34, 0.18 + 0.36, 0, W*0.12, 0.36, D*0.24, PART_COLORS.dark); // 风管
      break;
    }
    case '合金': {
      const cw = W*0.10;
      add(-W*0.32, 0.18 + 0.60, -D*0.30, cw, 1.2, cw, PART_COLORS.dark);
      add( W*0.32, 0.18 + 0.60, -D*0.30, cw, 1.2, cw, PART_COLORS.dark);
      add(-W*0.32, 0.18 + 0.60,  D*0.30, cw, 1.2, cw, PART_COLORS.dark);
      add( W*0.32, 0.18 + 0.60,  D*0.30, cw, 1.2, cw, PART_COLORS.dark);
      add(0, 0.18 + 1.28, 0, W*0.70, 0.18, D*0.70, PART_COLORS.body);   // 顶梁
      add(0, 0.18 + 0.92, 0, W*0.22, 0.52, D*0.22, PART_COLORS.dark);   // 压头
      add(0, 0.18 + 0.18, 0, W*0.40, 0.26, D*0.40, acc);                // 模具
      break;
    }
    case '化工': {
      add(-W*0.24, 0.18 + 0.50, -D*0.16, W*0.30, 1.0, D*0.30, PART_COLORS.light);
      add( W*0.22, 0.18 + 0.40, -D*0.20, W*0.26, 0.8, D*0.26, PART_COLORS.light);
      add( W*0.10, 0.18 + 0.58,  D*0.24, W*0.24, 1.16, D*0.24, PART_COLORS.body);
      add(0, 0.18 + 1.10, 0, W*0.66, 0.09, D*0.10, PART_COLORS.dark);
      add(-W*0.24, 0.18 + 0.78, 0, W*0.08, 0.14, D*0.08, acc);
      break;
    }
    case '加工': {
      add(0, 0.18 + 0.18, 0, W*0.72, 0.36, D*0.46, PART_COLORS.body);   // 工作台
      add(-W*0.30, 0.18 + 0.55, -D*0.18, W*0.09, 0.74, D*0.09, PART_COLORS.dark);
      add( W*0.30, 0.18 + 0.55, -D*0.18, W*0.09, 0.74, D*0.09, PART_COLORS.dark);
      add(0, 0.18 + 0.96, -D*0.18, W*0.66, 0.14, D*0.12, PART_COLORS.body); // 龙门梁
      add(0, 0.18 + 0.72, 0, W*0.12, 0.36, D*0.12, acc);                // 主轴
      add(W*0.26, 0.18 + 0.40, D*0.24, W*0.20, 0.30, D*0.10, PART_COLORS.dark); // 控制面板
      break;
    }
    case '组装': {
      // 厂房高度随占地增长，否则 12×12 的巨型建筑会扁成一块垫子
      const span = Math.max(W, D);
      const hh = 0.66 + 0.095 * span;
      add(0, 0.18 + hh/2, 0, W*0.82, hh, D*0.82, PART_COLORS.body);       // 厂房
      add(0, 0.18 + hh + 0.09, 0, W*0.54, 0.18, D*0.54, PART_COLORS.light); // 屋脊
      add(0, 0.18 + hh*0.42, D*0.42, W*0.30, hh*0.44, D*0.04, PART_COLORS.glass); // 卷帘门
      add(0, 0.18 + hh + 0.24, 0, W*0.16, 0.12, D*0.16, acc);             // 通风
      // 大跨度加四角塔，撑出"巨型结构"的感觉
      if(span >= 6){
        [[-0.37,-0.37],[0.37,-0.37],[-0.37,0.37],[0.37,0.37]].forEach(([sx,sz])=>{
          add(sx*W, 0.18 + hh + 0.55, sz*D, W*0.055, 1.1, D*0.055, PART_COLORS.dark);
        });
      }
      break;
    }
    case '回收': {
      add(0, 0.18 + 0.22, 0, W*0.34, 0.44, D*0.34, PART_COLORS.base);   // 料斗
      add(0, 0.18 + 0.68, 0, W*0.56, 0.52, D*0.56, PART_COLORS.body);
      add(W*0.20, 0.18 + 1.10, D*0.18, W*0.14, 1.1, D*0.14, PART_COLORS.dark); // 排放管
      add(0, 0.18 + 0.98, 0, W*0.20, 0.10, D*0.20, acc);
      break;
    }
    default: {
      add(0, 0.18 + 0.50, 0, W*0.70, 1.0, D*0.70, PART_COLORS.body);
      add(0, 0.18 + 1.05, 0, W*0.40, 0.10, D*0.40, acc);
    }
  }

  // 纪元越高，多加几块细节（体现"更复杂"）
  if(m.tier >= 3){
    add(-W*0.38, 0.18 + 0.24, 0, W*0.10, 0.28, D*0.10, PART_COLORS.dark);
    add( W*0.38, 0.18 + 0.24, 0, W*0.10, 0.28, D*0.10, PART_COLORS.dark);
  }

  const H = parts.reduce((mx,p)=>Math.max(mx, p.c[1] + p.s[1]/2), 0.5);
  return {parts, W, D, H};
}

/* ---------- 几何 & 投影 ---------- */

// 长方体 8 顶点（本地坐标，中心在 c）
function boxVerts(p){
  const [cx,cy,cz] = p.c, [w,h,d] = p.s;
  const x=w/2, y=h/2, z=d/2;
  return [
    [cx-x, cy-y, cz-z], [cx+x, cy-y, cz-z], [cx+x, cy-y, cz+z], [cx-x, cy-y, cz+z],
    [cx-x, cy+y, cz-z], [cx+x, cy+y, cz-z], [cx+x, cy+y, cz+z], [cx-x, cy+y, cz+z],
  ];
}
// 6 个面（顶点索引，全部按「从外部看逆时针」排列，保证法线朝外）
// 绕序错了会导致背面剔除把正面剔掉，模型看起来像纸片、能看穿
const BOX_FACES = [
  [4,7,6,5], // 顶 +y
  [0,1,2,3], // 底 -y
  [3,2,6,7], // 前 +z
  [1,0,4,5], // 后 -z
  [1,5,6,2], // 右 +x
  [0,3,7,4], // 左 -x
];

/**
 * 3D 查看器
 * @param {HTMLCanvasElement} canvas
 * @param {object} machine
 */
function createViewer3D(canvas, machine){
  const state = {
    yaw: -0.62,
    pitch: 0.40,
    zoom: 1,
    dragging: false,
    lastX: 0, lastY: 0,
    autoRotate: false,
    raf: 0,
    disposed: false,
  };

  const geo = buildMachineParts(machine);
  const radius = Math.sqrt(geo.W*geo.W + geo.D*geo.D + geo.H*geo.H) / 2;

  function resize(){
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    if(canvas.width !== w*dpr || canvas.height !== h*dpr){
      canvas.width = w*dpr;
      canvas.height = h*dpr;
    }
    return {w, h, dpr};
  }

  function render(){
    const {w, h, dpr} = resize();
    const ctx = canvas.getContext('2d');
    if(!ctx) return;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,w,h);

    // 背景：淡淡的径向渐变，让体块有对比
    const bg = ctx.createRadialGradient(w*0.5, h*0.42, 10, w*0.5, h*0.5, Math.max(w,h)*0.75);
    bg.addColorStop(0, '#ffffff');
    bg.addColorStop(1, '#eceae6');
    ctx.fillStyle = bg;
    ctx.fillRect(0,0,w,h);

    const cy = Math.cos(state.yaw), sy = Math.sin(state.yaw);
    const cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);

    // 相机距离：按包围球自适应
    const D = radius * 3.1 / state.zoom;
    const focal = Math.min(w, h) * 0.95;

    // 旋转（yaw 绕 Y，pitch 绕 X）→ 视空间坐标
    function toView(v){
      const [x0,y0,z0] = v;
      const x1 =  x0*cy - z0*sy;
      const z1 =  x0*sy + z0*cy;
      const y2 =  y0*cp - z1*sp;
      const z2 =  y0*sp + z1*cp;
      return [x1, y2, z2];
    }
    // 视空间 → 屏幕
    function toScreen(p){
      const depth = D - p[2];
      if(depth < 0.05) return null;
      const s = focal / depth;
      return [w*0.5 + p[0]*s, h*0.62 - p[1]*s, depth];
    }

    // 收集所有面（用几何法线判定朝向，比屏幕绕序更可靠）
    const faces = [];
    geo.parts.forEach(part=>{
      const vv = boxVerts(part).map(toView);
      const sv = vv.map(toScreen);
      if(sv.some(v=>v===null)) return;
      BOX_FACES.forEach(idx=>{
        const a = vv[idx[0]], b = vv[idx[1]], c = vv[idx[2]];
        const ux = b[0]-a[0], uy = b[1]-a[1], uz = b[2]-a[2];
        const wx = c[0]-a[0], wy = c[1]-a[1], wz = c[2]-a[2];
        // 叉积得法线
        const nx = uy*wz - uz*wy;
        const ny = uz*wx - ux*wz;
        const nz = ux*wy - uy*wx;
        // 相机在 +z 侧看向原点：法线 z 分量 <= 0 即为背面
        if(nz <= 0) return;
        const len = Math.hypot(nx, ny, nz) || 1;
        const poly = idx.map(i=>sv[i]);
        const depth = (poly[0][2]+poly[1][2]+poly[2][2]+poly[3][2]) / 4;
        faces.push({
          poly, depth, col: part.col,
          n: [nx/len, ny/len, nz/len],
        });
      });
    });

    // 画家算法：远的先画
    faces.sort((a,b)=> b.depth - a.depth);

    // 光照方向（视空间，固定在相机右上方）
    const L = [-0.38, 0.68, 0.62];
    const Ln = Math.hypot(...L);
    const Lx = L[0]/Ln, Ly = L[1]/Ln, Lz = L[2]/Ln;

    faces.forEach(f=>{
      const [nx, ny, nz] = f.n;
      const diff = Math.max(0, nx*Lx + ny*Ly + nz*Lz);
      // 环境光兜底，避免背光面全黑；顶面略微提亮
      const shade = 0.52 + 0.48 * diff + (ny > 0.7 ? 0.06 : 0);
      ctx.fillStyle = tint(f.col, Math.min(1.18, shade));
      ctx.strokeStyle = 'rgba(0,0,0,.28)';
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(f.poly[0][0], f.poly[0][1]);
      for(let i=1;i<f.poly.length;i++) ctx.lineTo(f.poly[i][0], f.poly[i][1]);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    });

    // 地面网格（footprint 轮廓）
    const groundProject = (v)=>toScreen(toView(v));
    drawGround(ctx, groundProject, geo);

    // 角标：视角角度
    ctx.fillStyle = 'rgba(0,0,0,.35)';
    ctx.font = '11px ui-monospace, Menlo, monospace';
    const deg = (r)=>Math.round(r * 180 / Math.PI);
    ctx.fillText(`yaw ${deg(state.yaw)}°  pitch ${deg(state.pitch)}°`, 10, h - 10);
  }

  function drawGround(ctx, project, g){
    const hy = 0;
    const c = [[-g.W/2,-hy,-g.D/2],[g.W/2,-hy,-g.D/2],[g.W/2,-hy,g.D/2],[-g.W/2,-hy,g.D/2]];
    const pts = c.map(project);
    if(pts.some(p=>!p)) return;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for(let i=1;i<pts.length;i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0,0,0,.05)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,.20)';
    ctx.setLineDash([4,3]);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // 颜色明暗
  function tint(hex, k){
    let c = String(hex||'#999').replace('#','');
    if(c.length===3) c = c.split('').map(x=>x+x).join('');
    const n = parseInt(c,16);
    const cl = v => Math.max(0, Math.min(255, Math.round(v)));
    const r = cl(((n>>16)&255) * k);
    const g = cl(((n>>8)&255) * k);
    const b = cl((n&255) * k);
    return `rgb(${r},${g},${b})`;
  }

  let needsRender = true;
  function loop(){
    if(state.disposed) return;
    if(needsRender || state.autoRotate){
      if(state.autoRotate) state.yaw += 0.012;
      render();
      needsRender = false;
    }
    state.raf = requestAnimationFrame(loop);
  }

  /* ---------- 交互 ---------- */
  function onDown(e){
    state.dragging = true;
    const p = e.touches ? e.touches[0] : e;
    state.lastX = p.clientX; state.lastY = p.clientY;
    canvas.style.cursor = 'grabbing';
    if(e.cancelable) e.preventDefault();
  }
  function onMove(e){
    if(!state.dragging) return;
    const p = e.touches ? e.touches[0] : e;
    const dx = p.clientX - state.lastX;
    const dy = p.clientY - state.lastY;
    state.lastX = p.clientX; state.lastY = p.clientY;
    state.yaw += dx * 0.012;                       // 水平拖动：无限制，可 360° 转
    state.pitch = Math.max(-0.35, Math.min(1.50, state.pitch + dy * 0.010));
    needsRender = true;
    if(e.cancelable) e.preventDefault();
  }
  function onUp(){
    state.dragging = false;
    canvas.style.cursor = 'grab';
  }
  function onWheel(e){
    state.zoom = Math.max(0.45, Math.min(3.4, state.zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
    needsRender = true;
    e.preventDefault();
  }
  function onDblClick(){
    state.yaw = -0.62; state.pitch = 0.40; state.zoom = 1;
    needsRender = true;
  }

  canvas.style.cursor = 'grab';
  canvas.style.touchAction = 'none';
  canvas.addEventListener('mousedown', onDown);
  canvas.addEventListener('touchstart', onDown, {passive:false});
  window.addEventListener('mousemove', onMove);
  window.addEventListener('touchmove', onMove, {passive:false});
  window.addEventListener('mouseup', onUp);
  window.addEventListener('touchend', onUp);
  canvas.addEventListener('wheel', onWheel, {passive:false});
  canvas.addEventListener('dblclick', onDblClick);

  loop();

  return {
    dispose(){
      state.disposed = true;
      cancelAnimationFrame(state.raf);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('touchmove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('touchend', onUp);
    },
    setAutoRotate(v){ state.autoRotate = !!v; needsRender = true; },
    getAutoRotate(){ return state.autoRotate; },
    reset(){ onDblClick(); },
    redraw(){ needsRender = true; },
    // 导出当前视角 PNG
    toPNG(){
      render();
      return canvas.toDataURL('image/png');
    },
  };
}

/* ---------- 3D 查看弹窗 ---------- */

let _activeViewer = null;

function open3DViewer(machineId){
  const m = machineOf(machineId);
  if(!m) return;
  if(_activeViewer){ _activeViewer.dispose(); _activeViewer = null; }

  document.getElementById('modal').innerHTML = `
    <header>
      <h3>${m.name} · 3D 体块</h3>
      <span class="x" id="v3Close">×</span>
    </header>
    <div class="content" style="padding:0">
      <div style="position:relative;background:#f2f0ec">
        <canvas id="v3Canvas" style="display:block;width:100%;height:420px"></canvas>
        <div style="position:absolute;left:12px;top:10px;font-size:11px;color:var(--text-3);
             background:rgba(255,255,255,.82);padding:4px 9px;border-radius:6px;pointer-events:none">
          拖动旋转 · 滚轮缩放 · 双击复位
        </div>
      </div>
      <div style="padding:14px 20px;border-top:1px solid var(--border)">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
          <button class="sm" id="v3Reset">复位视角</button>
          <button class="sm" id="v3Auto">自动旋转</button>
          <button class="sm" id="v3Shot">导出当前视角 PNG</button>
          <span style="flex:1"></span>
          <span class="pill">${m.cat}</span>
          <span class="pill">${m.footprint}</span>
          ${tierTag(m.tier)}
        </div>
        <div style="font-size:11.5px;color:var(--text-2);line-height:1.8">
          这是按「占地 + 分类」程序化生成的<strong>体块占位模型</strong>，
          用于核对尺度与体量比例。真实模型做好后可在「物品/机器」编辑里填网格路径。
        </div>
      </div>
    </div>
    <footer>
      <button id="v3CopyPrompt">复制描述词</button>
      <button class="primary" id="v3CloseBtn">关闭</button>
    </footer>`;

  document.getElementById('mask').classList.remove('hide');
  const canvas = document.getElementById('v3Canvas');
  _activeViewer = createViewer3D(canvas, m);

  const close = ()=>{
    if(_activeViewer){ _activeViewer.dispose(); _activeViewer = null; }
    closeModal();
  };
  document.getElementById('v3Close').onclick = close;
  document.getElementById('v3CloseBtn').onclick = close;
  document.getElementById('v3Reset').onclick = ()=>_activeViewer && _activeViewer.reset();
  document.getElementById('v3Auto').onclick = (e)=>{
    if(!_activeViewer) return;
    const next = !_activeViewer.getAutoRotate();
    _activeViewer.setAutoRotate(next);
    e.target.style.background = next ? 'var(--accent)' : '';
    e.target.style.color = next ? '#fff' : '';
    e.target.textContent = next ? '停止旋转' : '自动旋转';
  };
  document.getElementById('v3Shot').onclick = ()=>{
    if(!_activeViewer) return;
    const url = _activeViewer.toPNG();
    const a = document.createElement('a');
    a.href = url; a.download = `${m.id}_view3d.png`;
    document.body.appendChild(a); a.click();
    setTimeout(()=>a.remove(), 100);
    toast('已导出当前视角');
  };
  document.getElementById('v3CopyPrompt').onclick = ()=>copyText(machinePrompt(m, {withTech:true}));
}
