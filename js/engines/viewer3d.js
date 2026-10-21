/* Forgeworks · js/engines/viewer3d.js
   ============================================================
   3D 建筑预览器（基于 three.js WebGL）
   ------------------------------------------------------------
   three.js 本地 vendored（js/vendor/three.min.js, r147 UMD），不走 CDN，离线可用。

   几何体系统（关键）：
     不再是清一色方块。支持 8 种图元，按建筑功能选用：
       box    基座、机架、控制柜
       cyl    罐体、烟囱、立柱、主轴、滚筒
       cone   料斗、锥形集尘罩、钻头（上下半径可不同 = 圆台）
       sphere 球形储罐、半球封头、指示器
       torus  法兰、加强箍、环形轨道、阀门手轮
       pipe   两点之间的管道（自动计算朝向与长度）
       prism  棱柱（三角屋顶、六角罐）
       dome   半球封头（罐体封顶）

   能力：
     - 轨道拖动 360° / 滚轮缩放 / 阻尼惯性 / 双击复位
     - 材质：metalness / roughness / emissive / 透明 + 5 套预设
     - 程序化动画：spin / bob / slide / swing / pulse
     - 粒子：火星、烟雾、气泡、碎屑
     - 实时阴影 + PMREM 环境反射
     - 导出 PNG / GLB
   ============================================================ */

/* ============================================================
   一、材质
   ============================================================ */

const MATERIALS = {
  concrete:  { name:'混凝土', color:'#a5a29b', metal:0.02, rough:0.94, emissive:0,    alpha:1,    pattern:'grain' },
  steel:     { name:'钢材',   color:'#868d96', metal:0.55, rough:0.44, emissive:0,    alpha:1,    pattern:'none'  },
  steelDark: { name:'暗钢',   color:'#4a5058', metal:0.50, rough:0.58, emissive:0,    alpha:1,    pattern:'none'  },
  steelLite: { name:'亮钢',   color:'#aab1ba', metal:0.42, rough:0.46, emissive:0,    alpha:1,    pattern:'none'  },
  glass:     { name:'玻璃',   color:'#8fb8d8', metal:0.10, rough:0.08, emissive:0.06, alpha:0.42, pattern:'none'  },
  rust:      { name:'锈铁',   color:'#9a6b4a', metal:0.30, rough:0.88, emissive:0,    alpha:1,    pattern:'noise' },
  clean:     { name:'洁净白', color:'#d8dbde', metal:0.08, rough:0.42, emissive:0,    alpha:1,    pattern:'none'  },
  ceramic:   { name:'陶瓷',   color:'#cdc8ba', metal:0.02, rough:0.55, emissive:0,    alpha:1,    pattern:'grain' },
  glow:      { name:'炉火',   color:'#e07b39', metal:0.00, rough:1.00, emissive:1.0,  alpha:1,    pattern:'none'  },
  glowBlue:  { name:'能量光', color:'#6fa8f0', metal:0.00, rough:1.00, emissive:1.0,  alpha:1,    pattern:'none'  },
  glowGreen: { name:'生物光', color:'#5fd6a8', metal:0.00, rough:1.00, emissive:0.9,  alpha:1,    pattern:'none'  },
};

const ROLE_MAT = {
  base:'concrete', body:'steel', dark:'steelDark',
  light:'steelLite', glass:'glass', accent:'accent', glow:'glow',
};

const MATERIAL_PRESETS = {
  industrial: { name:'工业钢（默认）',
    map:{ base:'concrete', body:'steel', dark:'steelDark', light:'steelLite', glass:'glass' } },
  rusted: { name:'锈蚀工业',
    map:{ base:'rust', body:'rust', dark:'steelDark', light:'rust', glass:'glass' } },
  cleanroom: { name:'洁净实验室',
    map:{ base:'clean', body:'clean', dark:'steelLite', light:'clean', glass:'glass' } },
  ceramic: { name:'陶瓷装甲',
    map:{ base:'ceramic', body:'ceramic', dark:'steelDark', light:'clean', glass:'glass' } },
  void: { name:'深空合金',
    map:{ base:'steelDark', body:'steelDark', dark:'steelDark', light:'steel', glass:'glowBlue' } },
};

function resolveMaterial(role, accentColor, presetKey){
  if(role === 'accent'){
    return { name:'强调色', color:accentColor, metal:0.45, rough:0.40, emissive:0.12, alpha:1, pattern:'none' };
  }
  // 容错：如果 role 其实是材质名（历史上误用过），直接用该材质，避免静默回退
  if(!ROLE_MAT[role] && MATERIALS[role]) return MATERIALS[role];

  // presetKey 可能是「风格 id」，也可能是旧体系的「材质方案名」
  let map = null;
  if(typeof STYLE_PRESETS !== 'undefined' && STYLE_PRESETS[presetKey]){
    map = STYLE_PRESETS[presetKey].matMap;
  }
  if(!map && MATERIAL_PRESETS[presetKey]) map = MATERIAL_PRESETS[presetKey].map;
  if(!map) map = MATERIAL_PRESETS.industrial.map;

  const key = map[role] || ROLE_MAT[role] || 'steel';
  const base = MATERIALS[key] || MATERIALS.steel;
  if(role === 'glow') return Object.assign({}, base, { color: accentColor, emissive: 1.0 });
  return base;
}

/* ============================================================
   二、建筑几何构成
   ============================================================ */

// 兜底用的分类强调色。正常情况走风格引擎的 accentFor()，
// 只有风格模块没加载时才用这份（否则 3D 预览和描述词会是两个色系）。
const ACCENT_BY_CAT = {
  '采集':'#d9a441', '分离':'#5fa8c4', '冶炼':'#e07b39', '合金':'#8fa3b8',
  '化工':'#6fb86f', '加工':'#7d8b9e', '组装':'#3fa887', '回收':'#b09a6a',
};

/** 当前项目风格 id（风格模块没加载时返回 null） */
function currentStyleId(){
  return (typeof styleState !== 'undefined' && styleState) ? styleState.presetId : null;
}
/** 分类强调色：跟随项目风格 */
function categoryAccent(cat){
  if(typeof accentFor === 'function') return accentFor(cat);
  return ACCENT_BY_CAT[cat] || '#8a97a8';
}

function parseFootprint(fp){
  const a = String(fp || '1×1').split(/[×xX]/).map(n => parseFloat(n) || 1);
  return [a[0], a[1] || a[0]];
}

function anim(kind, o){ return Object.assign({ kind: kind }, o); }

/**
 * 把一个建筑展开成一组图元（纯数据，不依赖 three）
 * 每个图元：{ kind, ...几何参数, role, mat, anim }
 */
function buildMachineParts(m, presetKey){
  const fp = parseFootprint(m.footprint);
  const W = fp[0], D = fp[1];
  // 强调色跟随项目风格；没指定材质方案时也默认用当前风格
  const accent = categoryAccent(m.cat);
  const key = presetKey || currentStyleId() || 'industrial';
  const tweak = (typeof matParamsFor === 'function') ? (matParamsFor(key) || null) : null;
  const parts = [];
  const roleCounts = {};

  function push(p){
    roleCounts[p.role] = (roleCounts[p.role] || 0) + 1;
    p.partId = m.id + ':' + p.role + ':' + roleCounts[p.role];
    p.mat = resolveMaterial(p.role, accent, key);
    // 应用风格/方案的全局材质微调（金属感、粗糙度、发光倍率）
    if(tweak){
      p.mat = Object.assign({}, p.mat, {
        metal: Math.max(0, Math.min(1, (p.mat.metal||0) + (tweak.metalAdd||0))),
        rough: Math.max(0, Math.min(1, (p.mat.rough||0) + (tweak.roughAdd||0))),
        emissive: Math.max(0, Math.min(1.6, (p.mat.emissive||0) * (tweak.emissiveScale||1))),
      });
    }
    parts.push(p);
  }
  // 长方体
  const box = (x,y,z, w,h,d, role, a)=>push({kind:'box', c:[x,y,z], s:[w,h,d], role:role, anim:a});
  // 圆柱（r2 可用于圆台）
  const cyl = (x,y,z, r,h, role, a, seg)=>push({kind:'cyl', c:[x,y,z], r:r, h:h, seg:seg||20, role:role, anim:a});
  // 圆台 / 圆锥：rTop 上半径，rBot 下半径
  const cone= (x,y,z, rTop,rBot,h, role, a, seg)=>push({kind:'cone', c:[x,y,z], r1:rTop, r2:rBot, h:h, seg:seg||20, role:role, anim:a});
  // 球
  const sph = (x,y,z, r, role, a)=>push({kind:'sphere', c:[x,y,z], r:r, role:role, anim:a});
  // 半球封头（朝上）
  const dome= (x,y,z, r, role, a)=>push({kind:'dome', c:[x,y,z], r:r, role:role, anim:a});
  // 圆环：默认绕 X 轴转 90°，即水平放置的箍
  const tor = (x,y,z, r,tube, role, a)=>push({kind:'torus', c:[x,y,z], r:r, tube:tube, role:role, anim:a});
  // 竖立的环（绕 Y 轴）
  const torV= (x,y,z, r,tube, role, a)=>push({kind:'torusV', c:[x,y,z], r:r, tube:tube, role:role, anim:a});
  // 两点之间的管道
  const pipe= (a0,a1, r, role)=>push({kind:'pipe', a:a0, b:a1, r:r, role:role});
  // 棱柱（n 边，竖向）
  const prism=(x,y,z, r,h,n, role, a, rotY)=>push({kind:'prism', c:[x,y,z], r:r, h:h, sides:n, rotY:rotY||0, role:role, anim:a});

  let particles = null;
  const R = Math.min(W, D);        // 短边，用来定径向尺寸

  /* ---------------- 通用基座 ---------------- */
  box(0, 0.09, 0, W*0.94, 0.18, D*0.94, 'base');
  cyl(0, 0.19, 0, R*0.44, 0.04, 'dark', null, 24);   // 基座上的机械底盘

  switch(m.cat){

    /* ================= 采集：井架 + 钻杆 + 料斗 ================= */
    case '采集': {
      const tw = R*0.30;                 // 塔体半径
      const th = 1.75 + R*0.12;          // 塔高
      const baseY = 0.2;

      // 四根立柱
      [[-1,-1],[1,-1],[-1,1],[1,1]].forEach(function(s){
        cyl(s[0]*tw*0.78, baseY + th/2, s[1]*tw*0.78, tw*0.07, th, 'body', null, 10);
      });
      // 三道水平加强箍
      for(let i=1;i<=3;i++){
        tor(0, baseY + th*(i/3.4), 0, tw*0.80, tw*0.055, 'dark');
      }
      // 顶部平台 + 天轮罩
      box(0, baseY + th + 0.06, 0, tw*1.9, 0.12, tw*1.9, 'body');
      cyl(0, baseY + th + 0.24, 0, tw*0.52, 0.26, 'light', null, 16);
      cone(0, baseY + th + 0.46, 0, tw*0.54, tw*0.20, 0.12, 'dark', null, 16);
      // 顶部警示灯
      sph(0, baseY + th + 0.60, 0, tw*0.16, 'accent',
          anim('pulse', {speed:2.4, min:0.35, max:2.2}));

      // 钻杆（旋转）+ 钻头（圆锥，尖朝下）
      cyl(0, baseY + 0.78, 0, tw*0.15, 1.35, 'light', anim('spin', {axis:'y', speed:2.4}), 14);
      cone(0, 0.36, 0, tw*0.15, 0.02, 0.34, 'dark', null, 14);

      // 侧向料斗（上宽下窄的圆台）
      const hx = W*0.33, hz = D*0.30;
      cone(hx, 0.74, hz, R*0.24, R*0.09, 0.52, 'dark', anim('bob', {amp:0.03, speed:1.8}), 14);
      // 溜槽：从料斗斜向塔体
      pipe([hx*0.92, 0.52, hz*0.92], [tw*0.5, 0.30, tw*0.5], R*0.045, 'dark');
      // 料斗支腿
      cyl(hx, 0.34, hz, R*0.05, 0.30, 'dark', null, 8);

      // 动力柜 + 电缆管
      box(-W*0.34, 0.42, D*0.28, W*0.16, 0.44, D*0.14, 'body');
      pipe([-W*0.34, 0.64, D*0.24], [-tw*0.6, 0.9, 0.0], R*0.03, 'dark');

      particles = { kind:'dust', origin:[0, 0.26, 0], rate:14, spread:W*0.30,
                    life:1.6, color:'#b9b2a4', size:0.06, blending:'normal' };
      break;
    }

    /* ================= 分离：立式罐组 + 旋流器 + 管路 ================= */
    case '分离': {
      const tA = R*0.30, hA = 1.05;
      const yA = 0.2;
      // 主罐：柱体 + 半球封头 + 法兰
      cyl(-W*0.20, yA + hA/2, -D*0.06, tA, hA, 'body', null, 24);
      dome(-W*0.20, yA + hA, -D*0.06, tA, 'light');
      tor(-W*0.20, yA + 0.10, -D*0.06, tA*1.06, tA*0.07, 'dark');
      tor(-W*0.20, yA + hA - 0.06, -D*0.06, tA*1.04, tA*0.06, 'dark');
      // 罐内液位（发光细柱）
      cyl(-W*0.20, yA + hA*0.35, -D*0.06, tA*0.55, hA*0.55, 'glowGreen',
          anim('pulse', {speed:0.9, min:0.25, max:1.1}), 16);

      // 副罐
      const tB = R*0.22, hB = 0.72;
      cyl(W*0.26, yA + hB/2, D*0.16, tB, hB, 'light', anim('bob', {amp:0.02, speed:1.1}), 20);
      dome(W*0.26, yA + hB, D*0.16, tB, 'light');

      // 旋流器：柱体 + 下锥
      const cx = -W*0.20, cz = -D*0.06;
      cyl(cx, yA + hA + 0.42, cz, R*0.18, 0.44, 'accent', anim('spin', {axis:'y', speed:3.2}), 18);
      cone(cx, yA + hA + 0.06, cz, R*0.18, R*0.045, 0.30, 'dark', null, 18);

      // 连通管路
      pipe([cx + tA*0.9, yA + hA*0.82, cz], [W*0.26 - tB*0.8, yA + hB*0.72, D*0.16], R*0.035, 'dark');
      pipe([W*0.26, yA + hB + 0.02, D*0.16], [W*0.26, yA + hB + 0.34, D*0.16], R*0.035, 'dark');
      pipe([W*0.26, yA + hB + 0.34, D*0.16], [cx + tA*0.6, yA + hB + 0.34, cz], R*0.035, 'dark');

      // 阀门（小手轮）
      torV(cx + tA + 0.12, yA + hA*0.82, cz, R*0.075, R*0.018, 'accent');
      cyl(cx + tA + 0.06, yA + hA*0.82, cz, R*0.032, 0.12, 'dark', null, 8);

      particles = { kind:'bubble', origin:[W*0.26, yA + hB, D*0.16], rate:8, spread:W*0.10,
                    life:1.4, color:'#9fd0e8', size:0.07, blending:'normal' };
      break;
    }

    /* ================= 冶炼：高炉（炉腹 + 炉腰 + 炉喉 + 烟囱 + 风口）================= */
    case '冶炼': {
      const br = R*0.42;          // 炉腹半径
      const y0 = 0.2;

      // 炉基 + 炉缸
      cyl(0, y0 + 0.10, 0, br*1.24, 0.20, 'base', null, 28);
      cyl(0, y0 + 0.42, 0, br*1.10, 0.46, 'body', null, 28);

      // 炉腹（下宽上窄）
      cone(0, y0 + 0.90, 0, br*0.80, br*1.10, 0.50, 'body', null, 28);
      // 炉腰（竖直段）
      cyl(0, y0 + 1.30, 0, br*0.80, 0.30, 'dark', null, 28);
      // 炉身（收窄）
      cone(0, y0 + 1.72, 0, br*0.58, br*0.80, 0.54, 'body', null, 28);
      // 炉喉 + 炉顶锥
      cyl(0, y0 + 2.06, 0, br*0.58, 0.14, 'dark', null, 24);
      cone(0, y0 + 2.24, 0, br*0.30, br*0.58, 0.22, 'dark', null, 24);

      // 炉腰加强箍
      tor(0, y0 + 1.30, 0, br*0.84, br*0.045, 'light');

      // 环形风管（bustle pipe）+ 风口
      tor(0, y0 + 1.02, 0, br*1.02, br*0.055, 'dark');
      for(let i=0;i<8;i++){
        const a = i * Math.PI / 4;
        const px = Math.cos(a)*br*0.94, pz = Math.sin(a)*br*0.94;
        pipe([Math.cos(a)*br*1.06, y0 + 1.02, Math.sin(a)*br*1.06], [px, y0 + 0.86, pz], br*0.035, 'dark');
      }

      // 出铁口（发光）+ 渣口
      cyl(0, y0 + 0.22, br*1.06, br*0.12, 0.10, 'glow',
          anim('pulse', {speed:1.7, min:0.6, max:2.4}), 12);
      // 炉门（正面发光的方形门洞）
      box(0, y0 + 0.44, br*1.12, br*0.46, br*0.42, 0.04, 'glow',
          anim('pulse', {speed:1.7, min:0.55, max:2.2}));

      // 烟囱：柱体 + 法兰 + 锥形帽
      const chx = br*1.15, chz = br*0.55;
      const chH = 1.35;
      cyl(chx, y0 + 2.10 + chH/2, chz, br*0.19, chH, 'dark', null, 20);
      tor(chx, y0 + 2.30, chz, br*0.21, br*0.035, 'light');
      tor(chx, y0 + 2.30 + chH*0.55, chz, br*0.21, br*0.035, 'light');
      cone(chx, y0 + 2.10 + chH + 0.12, chz, br*0.26, br*0.19, 0.24, 'dark', null, 20);
      // 烟囱从炉顶引出
      pipe([br*0.30, y0 + 2.34, br*0.20], [chx, y0 + 2.34, chz], br*0.10, 'dark');

      // 热风围管 + 上升管
      cyl(-br*1.20, y0 + 1.30, -br*0.30, br*0.10, 1.10, 'dark', null, 14);
      pipe([-br*1.20, y0 + 1.85, -br*0.30], [-br*1.20, y0 + 1.85, 0], br*0.075, 'dark');

      // 检修平台
      tor(0, y0 + 1.95, 0, br*0.70, br*0.03, 'light');
      tor(0, y0 + 1.05, 0, br*1.30, br*0.025, 'light');

      particles = {
        kind:'ember', origin:[0, y0 + 0.30, br*1.14], rate:26, spread:br*0.30,
        life:1.5, color:'#ffb066', size:0.075, blending:'additive',
        smoke: { origin:[chx, y0 + 2.10 + chH + 0.24, chz], rate:7, spread:br*0.12,
                 life:2.8, color:'#9aa0a6', size:0.26, blending:'normal' },
      };
      break;
    }

    /* ================= 合金：四柱压力机 ================= */
    case '合金': {
      const y0 = 0.2;
      const spanX = W*0.34, spanZ = D*0.30;
      const colH = 1.35;

      // 四根立柱（圆柱）
      [[-1,-1],[1,-1],[-1,1],[1,1]].forEach(function(s){
        cyl(s[0]*spanX, y0 + colH/2, s[1]*spanZ, R*0.085, colH, 'dark', null, 14);
        // 柱脚
        cyl(s[0]*spanX, y0 + 0.05, s[1]*spanZ, R*0.13, 0.10, 'base', null, 14);
      });
      // 上横梁
      box(0, y0 + colH + 0.09, 0, spanX*2 + R*0.28, 0.20, spanZ*2 + R*0.28, 'body');
      // 主液压缸
      cyl(0, y0 + colH + 0.42, 0, R*0.19, 0.48, 'light', null, 18);
      dome(0, y0 + colH + 0.66, 0, R*0.19, 'light');
      // 压头（上下往复）
      cyl(0, y0 + 0.86, 0, R*0.26, 0.44, 'dark', anim('bob', {amp:0.20, speed:2.0}), 18);
      // 模具台
      box(0, y0 + 0.26, 0, R*0.92, 0.28, R*0.92, 'base');
      box(0, y0 + 0.44, 0, R*0.52, 0.10, R*0.52, 'accent',
          anim('pulse', {speed:2.0, min:0.5, max:1.8}));
      // 下顶出缸
      cyl(0, y0 + 0.09, 0, R*0.20, 0.16, 'dark', null, 16);

      // 液压管路
      pipe([R*0.22, y0 + colH + 0.42, 0], [spanX, y0 + colH + 0.20, spanZ*0.8], R*0.035, 'dark');
      pipe([-R*0.22, y0 + colH + 0.42, 0], [-spanX, y0 + colH + 0.20, spanZ*0.8], R*0.035, 'dark');
      // 蓄能器（球）
      sph(spanX*1.05, y0 + 0.55, -spanZ*1.05, R*0.18, 'light');
      cyl(spanX*1.05, y0 + 0.26, -spanZ*1.05, R*0.05, 0.32, 'dark', null, 10);

      particles = { kind:'spark', origin:[0, y0 + 0.50, 0], rate:12, spread:R*0.5,
                    life:1.0, color:'#ffd08a', size:0.05, blending:'additive' };
      break;
    }

    /* ================= 化工：罐区 + 球罐 + 管网 ================= */
    case '化工': {
      const y0 = 0.2;
      const specs = [
        { x:-W*0.27, z:-D*0.22, r:R*0.165, h:1.05 },
        { x: W*0.26, z:-D*0.24, r:R*0.145, h:0.80 },
        { x: W*0.20, z: D*0.26, r:R*0.135, h:1.24 },
      ];
      specs.forEach(function(s, i){
        cyl(s.x, y0 + s.h/2, s.z, s.r, s.h, 'light', i===1 ? anim('bob',{amp:0.02, speed:0.9}) : null, 24);
        dome(s.x, y0 + s.h, s.z, s.r*0.86, 'light');
        tor(s.x, y0 + 0.08, s.z, s.r*1.06, s.r*0.09, 'dark');
        tor(s.x, y0 + s.h*0.55, s.z, s.r*1.04, s.r*0.06, 'dark');
        // 液位窗
        cyl(s.x + s.r*0.92, y0 + s.h*0.45, s.z, s.r*0.10, s.h*0.55,
            i===2 ? 'glowGreen' : 'glowBlue',
            anim('pulse', {speed:0.7 + i*0.2, min:0.3, max:1.4}), 12);
      });

      // 球形储罐（带支腿）
      const sx = -W*0.28, sz = D*0.24, sr = R*0.155;
      sph(sx, y0 + sr + 0.18, sz, sr, 'body');
      [[-1,-1],[1,-1],[0,1]].forEach(function(s){
        cyl(sx + s[0]*sr*0.62, y0 + 0.12, sz + s[1]*sr*0.62, sr*0.10, 0.24, 'dark', null, 8);
      });

      // 管网：横向主管 + 竖向支管
      pipe([specs[0].x, y0 + 1.02, specs[0].z], [specs[1].x, y0 + 0.98, specs[1].z], R*0.045, 'dark');
      pipe([specs[0].x, y0 + 1.02, specs[0].z], [specs[2].x, y0 + 1.02, specs[2].z], R*0.045, 'dark');
      pipe([specs[2].x, y0 + 1.02, specs[2].z], [specs[2].x, y0 + 1.40, specs[2].z], R*0.045, 'dark');
      pipe([sx, y0 + sr + 0.30, sz], [sx, y0 + 1.20, sz], R*0.045, 'dark');
      // 法兰
      tor(specs[0].x + R*0.12, y0 + 1.02, specs[0].z, R*0.075, R*0.02, 'light');
      // 压力表（小圆盘）
      torV(specs[2].x + specs[2].r + 0.10, y0 + 0.95, specs[2].z, R*0.07, R*0.02, 'accent');
      // 检修梯
      cyl(specs[0].x - specs[0].r - 0.10, y0 + 0.55, specs[0].z, R*0.025, 1.0, 'dark', null, 6);

      particles = { kind:'bubble', origin:[specs[0].x, y0 + 0.9, specs[0].z], rate:10, spread:W*0.10,
                    life:2.0, color:'#8fe0b8', size:0.08, blending:'normal' };
      break;
    }

    /* ================= 加工：机床 + 龙门 + 主轴 ================= */
    case '加工': {
      const y0 = 0.2;
      // 床身
      box(0, y0 + 0.16, 0, W*0.72, 0.32, D*0.48, 'body');
      // 导轨
      box(-W*0.16, y0 + 0.34, 0, W*0.10, 0.05, D*0.44, 'light');
      box( W*0.16, y0 + 0.34, 0, W*0.10, 0.05, D*0.44, 'light');

      // 两根立柱
      cyl(-W*0.30, y0 + 0.60, -D*0.20, R*0.075, 0.80, 'dark', null, 12);
      cyl( W*0.30, y0 + 0.60, -D*0.20, R*0.075, 0.80, 'dark', null, 12);

      // 龙门横梁（左右进给）
      box(0, y0 + 1.02, -D*0.20, W*0.68, 0.13, D*0.14, 'body',
          anim('slide', {axis:'x', amp:W*0.16, speed:0.8}));
      // 主轴（旋转）+ 刀锥
      cyl(0, y0 + 0.86, 0, R*0.10, 0.36, 'light', anim('spin', {axis:'y', speed:7.0}), 14);
      cone(0, y0 + 0.62, 0, R*0.10, R*0.02, 0.14, 'accent', null, 14);

      // 控制柜 + 屏幕
      box(W*0.28, y0 + 0.40, D*0.26, W*0.18, 0.44, D*0.12, 'dark');
      box(W*0.28, y0 + 0.50, D*0.33, W*0.12, 0.20, 0.02, 'glowBlue',
          anim('pulse', {speed:1.4, min:0.4, max:1.5}));
      // 排屑器
      box(-W*0.34, y0 + 0.18, D*0.22, W*0.14, 0.14, D*0.30, 'dark');
      // 冷却液管
      pipe([-R*0.16, y0 + 0.72, 0], [-W*0.20, y0 + 0.44, D*0.10], R*0.022, 'dark');

      particles = { kind:'spark', origin:[0, y0 + 0.58, 0], rate:9, spread:W*0.14,
                    life:0.9, color:'#ffd9a0', size:0.045, blending:'additive' };
      break;
    }

    /* ================= 组装：厂房 + 人字顶 + 行车 ================= */
    case '组装': {
      const span = Math.max(W, D);
      const hh = 0.62 + 0.085 * span;      // 厂房净高
      const y0 = 0.2;

      // 厂房主体（棱柱切角 = 八边形，显得不是纯方盒）
      prism(0, y0 + hh/2, 0, W*0.44, hh, 8, 'body', null, Math.PI/8);
      // 屋顶：四棱锥（person 屋顶）
      cone(0, y0 + hh + 0.13, 0, 0.03, W*0.47, 0.26, 'light', null, 4);
      // 屋脊通风口
      box(0, y0 + hh + 0.36, 0, W*0.14, 0.10, D*0.14, 'accent',
          anim('pulse', {speed:1.2, min:0.4, max:1.6}));
      cyl(0, y0 + hh + 0.44, 0, W*0.05, 0.10, 'dark', null, 12);

      // 正面玻璃带（贴在外侧，微透明）
      box(0, y0 + hh*0.52, D*0.415, W*0.72, hh*0.34, 0.03, 'glass');
      // 卷帘门
      box(0, y0 + hh*0.26, D*0.43, W*0.26, hh*0.48, 0.04, 'dark');
      // 门口雨棚
      box(0, y0 + hh*0.52, D*0.47, W*0.30, 0.05, D*0.12, 'light');

      // 屋顶行车导轨 + 行车（横向移动）
      box(0, y0 + hh - 0.06, 0, W*0.80, 0.05, 0.06, 'dark');
      box(0, y0 + hh - 0.06, 0, W*0.80, 0.05, 0.06, 'dark');
      box(0, y0 + hh - 0.14, 0, W*0.20, 0.12, D*0.22, 'accent',
          anim('slide', {axis:'x', amp:W*0.24, speed:0.55}));

      // 侧面管道 + 外部机组
      pipe([-W*0.42, y0 + hh*0.7, -D*0.30], [-W*0.42, y0 + 0.30, -D*0.30], R*0.035, 'dark');
      box(-W*0.40, y0 + 0.30, -D*0.34, W*0.14, 0.28, D*0.14, 'light');

      // 大跨度：四角塔架
      if(span >= 6){
        [[-0.38,-0.38],[0.38,-0.38],[-0.38,0.38],[0.38,0.38]].forEach(function(s){
          cyl(s[0]*W, y0 + hh + 0.75, s[1]*D, W*0.028, 1.15, 'dark', null, 10);
          sph(s[0]*W, y0 + hh + 1.36, s[1]*D, W*0.022, 'accent',
              anim('pulse', {speed:1.6, min:0.3, max:1.8}));
        });
      }

      particles = { kind:'dust', origin:[0, y0 + 0.40, D*0.44], rate:6, spread:W*0.26,
                    life:2.2, color:'#c8ccd2', size:0.07, blending:'normal' };
      break;
    }

    /* ================= 回收：料斗 + 处理塔 + 排放管 ================= */
    case '回收': {
      const y0 = 0.2;
      // 进料斗：上宽下窄的圆台（倒锥）
      cone(0, y0 + 0.30, 0, R*0.34, R*0.10, 0.56, 'base',
           anim('bob', {amp:0.025, speed:2.6}), 18);
      // 处理塔主体
      cyl(0, y0 + 0.86, 0, R*0.30, 0.60, 'body', null, 24);
      tor(0, y0 + 0.60, 0, R*0.32, R*0.04, 'dark');
      dome(0, y0 + 1.16, 0, R*0.30, 'light');
      // 顶部指示环
      tor(0, y0 + 1.20, 0, R*0.26, R*0.035, 'accent',
          anim('pulse', {speed:1.0, min:0.3, max:1.6}));

      // 排放管：上升段 + 弯头 + 水平段
      const px = R*0.36, pz = R*0.30;
      cyl(px, y0 + 1.30, pz, R*0.08, 1.30, 'dark', null, 14);
      sph(px, y0 + 1.95, pz, R*0.085, 'dark');
      pipe([px, y0 + 1.95, pz], [px*1.7, y0 + 1.95, pz*1.6], R*0.075, 'dark');
      // 滤网（细密圆环）
      for(let i=0;i<3;i++){
        tor(px, y0 + 1.45 + i*0.18, pz, R*0.095, R*0.012, 'light');
      }
      // 检修平台
      tor(0, y0 + 1.02, 0, R*0.36, R*0.022, 'light');
      // 底部出渣口
      cyl(-R*0.34, y0 + 0.24, 0, R*0.09, 0.16, 'glow',
          anim('pulse', {speed:1.2, min:0.3, max:1.6}), 10);

      particles = { kind:'smoke', origin:[px, y0 + 1.95, pz], rate:9, spread:W*0.06,
                    life:2.6, color:'#a8a49c', size:0.24, blending:'normal' };
      break;
    }

    default: {
      // 兜底：通用方箱 + 顶部圆环
      box(0, 0.2 + 0.50, 0, W*0.70, 1.0, D*0.70, 'body');
      tor(0, 0.2 + 1.05, 0, W*0.22, 0.04, 'accent');
      break;
    }
  }

  // 高纪元追加细节：侧挂管束 + 铭牌
  if(m.tier >= 3){
    pipe([-W*0.40, 0.2, -D*0.36], [-W*0.40, 0.2 + 0.5, -D*0.36], R*0.03, 'dark');
    box(W*0.40, 0.34, -D*0.36, W*0.08, 0.16, D*0.04, 'accent');
  }

  const H = parts.reduce(function(mx,p){
    let top = p.c ? p.c[1] : 0;
    if(p.kind === 'box') top += p.s[1]/2;
    else if(p.kind === 'cyl' || p.kind === 'cone' || p.kind === 'prism') top += p.h/2;
    else if(p.kind === 'sphere' || p.kind === 'dome') top += p.r;
    else if(p.kind === 'torus' || p.kind === 'torusV') top += p.tube;
    else if(p.kind === 'pipe') top = Math.max(p.a[1], p.b[1]);
    return Math.max(mx, top);
  }, 0.5);

  return {parts:parts, W:W, D:D, H:H, accent:accent, particles:particles};
}

/* ============================================================
   三、查看器（three.js）
   ============================================================ */

function haveThree(){
  return typeof THREE !== 'undefined' && !!THREE.WebGLRenderer;
}

function createViewer3D(canvas, machine){
  if(!haveThree()){
    throw new Error('three.js 未加载，请检查 js/vendor/three.min.js');
  }
  // 关键：r147 默认 legacyMode=true，十六进制颜色会被当成线性值直接用，
  // 再经 sRGB 输出后整体被提亮，看起来"白塑料"。必须开启颜色管理。
  if(THREE.ColorManagement){
    THREE.ColorManagement.legacyMode = false;
  }
  if(!THREE.OrbitControls){
    throw new Error('OrbitControls 未加载，请检查 js/vendor/OrbitControls.js');
  }

  const state = {
    autoRotate: false,
    playing: true,
    speed: 1,
    // 默认跟随项目风格，而不是写死 'industrial'
    preset: currentStyleId() || 'industrial',
    time: 0,
    disposed: false,
    needsRender: true,
    particles: [],
  };

  let geo = buildMachineParts(machine, state.preset);

  /* ---------- 渲染器 ---------- */
  const renderer = new THREE.WebGLRenderer({
    canvas: canvas, antialias: true, alpha: false, preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  if('outputEncoding' in renderer) renderer.outputEncoding = THREE.sRGBEncoding;
  if(THREE.ACESFilmicToneMapping){
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.02;
  }
  renderer.shadowMap.enabled = true;
  if(THREE.PCFSoftShadowMap) renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  /* ---------- 场景与光照 ---------- */
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#eceae6');

  if(THREE.PMREMGenerator && THREE.RoomEnvironment){
    try{
      const pmrem = new THREE.PMREMGenerator(renderer);
      pmrem.compileEquirectangularShader();
      const envRT = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04);
      scene.environment = envRT.texture;
    }catch(e){ console.warn('环境贴图生成失败', e); }
  }

  const radius = Math.sqrt(geo.W*geo.W + geo.D*geo.D + geo.H*geo.H) / 2;

  const camera = new THREE.PerspectiveCamera(36, 1, 0.05, 400);
  const target = new THREE.Vector3(0, geo.H * 0.36, 0);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9098, 0.34));

  const key = new THREE.DirectionalLight(0xfff4e6, 0.95);
  key.position.set(-radius*2.2, radius*3.2, radius*2.0);
  key.castShadow = true;
  key.shadow.mapSize.width = 1024;
  key.shadow.mapSize.height = 1024;
  (function(){
    const s = radius * 2.4;
    const c = key.shadow.camera;
    c.left=-s; c.right=s; c.top=s; c.bottom=-s; c.near=0.1; c.far=radius*14;
    c.updateProjectionMatrix();
  })();
  scene.add(key);

  const rim = new THREE.DirectionalLight(0xcfe0ff, 0.26);
  rim.position.set(radius*2.6, radius*1.4, -radius*2.2);
  scene.add(rim);

  /* ---------- 地面 ---------- */
  const groundGeo = new THREE.PlaneGeometry(geo.W*1.9, geo.D*1.9);
  const groundMat = new THREE.MeshStandardMaterial({ color:0xd8d5cf, roughness:0.96, metalness:0 });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI/2;
  ground.position.y = 0.001;
  ground.receiveShadow = true;
  scene.add(ground);

  const edgePts = [
    new THREE.Vector3(-geo.W/2, 0.004, -geo.D/2),
    new THREE.Vector3( geo.W/2, 0.004, -geo.D/2),
    new THREE.Vector3( geo.W/2, 0.004,  geo.D/2),
    new THREE.Vector3(-geo.W/2, 0.004,  geo.D/2),
    new THREE.Vector3(-geo.W/2, 0.004, -geo.D/2),
  ];
  const edgeGeo = new THREE.BufferGeometry().setFromPoints(edgePts);
  const edgeMat = new THREE.LineDashedMaterial({ color:0x8a8880, dashSize:0.12, gapSize:0.08 });
  const edgeLine = new THREE.Line(edgeGeo, edgeMat);
  if(edgeLine.computeLineDistances) edgeLine.computeLineDistances();
  scene.add(edgeLine);

  /* ---------- 几何体工厂 ---------- */
  const geoCache = {};
  function partGeometry(p){
    const key = JSON.stringify(p.kind === 'pipe'
      ? ['pipe', p.r, Math.hypot(p.b[0]-p.a[0], p.b[1]-p.a[1], p.b[2]-p.a[2]).toFixed(3)]
      : [p.kind, p.s, p.r, p.r1, p.r2, p.h, p.tube, p.sides, p.seg]);
    if(geoCache[key]) return geoCache[key];

    let g;
    switch(p.kind){
      case 'cyl':   g = new THREE.CylinderGeometry(p.r, p.r, p.h, p.seg || 20); break;
      case 'cone':  g = new THREE.CylinderGeometry(p.r1, p.r2, p.h, p.seg || 20); break;
      case 'sphere':g = new THREE.SphereGeometry(p.r, 20, 14); break;
      case 'dome':  g = new THREE.SphereGeometry(p.r, 20, 10, 0, Math.PI*2, 0, Math.PI/2); break;
      case 'torus': g = new THREE.TorusGeometry(p.r, p.tube, 8, 28); g.rotateX(Math.PI/2); break;
      case 'torusV':g = new THREE.TorusGeometry(p.r, p.tube, 8, 24); break;
      case 'prism': g = new THREE.CylinderGeometry(p.r, p.r, p.h, p.sides || 6); break;
      case 'pipe': {
        const len = Math.hypot(p.b[0]-p.a[0], p.b[1]-p.a[1], p.b[2]-p.a[2]);
        g = new THREE.CylinderGeometry(p.r, p.r, len, 12);
        break;
      }
      default:      g = new THREE.BoxGeometry(p.s[0], p.s[1], p.s[2]);
    }
    geoCache[key] = g;
    return g;
  }

  function makeThreeMaterial(mat){
    const c = new THREE.Color(mat.color);
    return new THREE.MeshStandardMaterial({
      color: c,
      metalness: mat.metal,
      roughness: mat.rough,
      emissive: mat.emissive > 0 ? c.clone() : new THREE.Color(0x000000),
      emissiveIntensity: mat.emissive,
      transparent: mat.alpha < 1,
      opacity: mat.alpha,
      flatShading: p_flatShading(mat),
      side: THREE.FrontSide,
      envMapIntensity: 0.55,
    });
  }
  // 曲面图元用平滑着色，方块保持平面着色
  function p_flatShading(mat){ return true; }

  /* ---------- 部件网格 ---------- */
  const group = new THREE.Group();
  scene.add(group);
  const meshes = [];

  const UP = new THREE.Vector3(0,1,0);

  function buildMeshes(){
    for(let i=meshes.length-1;i>=0;i--){
      const m = meshes[i];
      group.remove(m.mesh);
      if(m.mesh.material) m.mesh.material.dispose();
      meshes.splice(i,1);
    }
    geo.parts.forEach(function(p){
      const mat = makeThreeMaterial(p.mat);
      // 着色模式：低多边形图元（方块/棱柱/低段数锥）用平面着色保留硬边，
      // 高段数曲面才用平滑法线。否则 4 段锥屋顶会被照成一颗圆顶。
      if(p.kind === 'box' || p.kind === 'prism'){
        mat.flatShading = true;
      }else if(p.kind === 'cyl' || p.kind === 'cone'){
        mat.flatShading = (p.seg || 20) <= 8;
      }else{
        mat.flatShading = false;
      }
      mat.needsUpdate = true;

      const g = partGeometry(p);
      const mesh = new THREE.Mesh(g, mat);
      mesh.userData.fwPartId = p.partId;

      if(p.kind === 'pipe'){
        const a = new THREE.Vector3(p.a[0], p.a[1], p.a[2]);
        const b = new THREE.Vector3(p.b[0], p.b[1], p.b[2]);
        const dir = new THREE.Vector3().subVectors(b, a);
        mesh.position.copy(a).add(b).multiplyScalar(0.5);
        mesh.quaternion.setFromUnitVectors(UP, dir.clone().normalize());
      } else {
        mesh.position.set(p.c[0], p.c[1], p.c[2]);
        if(p.rotY) mesh.rotation.y = p.rotY;
      }

      const override = machine.ui3d && machine.ui3d.parts && machine.ui3d.parts[p.partId];
      if(override){
        if(override.hidden) mesh.visible = false;
        applyPartOverride(mesh, p, override);
      }

      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
      meshes.push({
        mesh: mesh, part: p, role: p.role, id: p.partId,
        baseMaterial: mat.clone(),
        base: {
          pos: mesh.position.clone(),
          rot: mesh.rotation.clone(),
          quat: mesh.quaternion.clone(),
        },
      });
    });
  }

  function applyPartOverride(mesh, part, override){
    const transform = override.transform || {};
    const pos = transform.position || {};
    const rot = transform.rotation || {};
    const scale = transform.scale || {};
    mesh.position.x += Number(pos.x) || 0;
    mesh.position.y += Number(pos.y) || 0;
    mesh.position.z += Number(pos.z) || 0;
    mesh.rotation.x += Number(rot.x) || 0;
    mesh.rotation.y += Number(rot.y) || 0;
    mesh.rotation.z += Number(rot.z) || 0;
    mesh.scale.set(Number(scale.x) || 1, Number(scale.y) || 1, Number(scale.z) || 1);
    const material = override.material || {};
    if(material.color) mesh.material.color.set(material.color);
    if(material.textureData && THREE.TextureLoader){
      mesh.material.map = new THREE.TextureLoader().load(material.textureData, function(){ mesh.material.needsUpdate = true; });
    }
    if(Number.isFinite(material.metallic)) mesh.material.metalness = material.metallic;
    if(Number.isFinite(material.roughness)) mesh.material.roughness = material.roughness;
    if(Number.isFinite(material.emissive)) mesh.material.emissiveIntensity = material.emissive;
    if(Number.isFinite(material.alpha)){
      mesh.material.opacity = material.alpha;
      mesh.material.transparent = material.alpha < 1;
      mesh.material.needsUpdate = true;
    }
  }
  buildMeshes();

  /**
   * 适配占地：模型不能超出 footprint。
   * 否则 3×3 的建筑在 UE 里会覆盖到相邻格子，铺排时互相穿插。
   * 做法是整体等比缩放（保持比例），代价是高度略降。
   */
  function fitToFootprint(){
    group.updateMatrixWorld(true);
    const bb = new THREE.Box3().setFromObject(group);
    const size = new THREE.Vector3(); bb.getSize(size);
    if(size.x < 1e-6 || size.z < 1e-6) return 1;
    const k = Math.min(1, geo.W / size.x, geo.D / size.z);
    group.scale.setScalar(k);
    // 贴地：包围盒底部对齐 y=0，保证 UE 里 pivot 在底面
    group.updateMatrixWorld(true);
    const bb2 = new THREE.Box3().setFromObject(group);
    if(Math.abs(bb2.min.y) > 1e-4){
      group.position.y -= bb2.min.y;
      group.updateMatrixWorld(true);
    }
    return k;
  }
  const fitScale = fitToFootprint();

  /* ---------- 粒子 ---------- */
  const MAX_P = 300;
  let emberPoints = null, smokePoints = null, emberPos = null, smokePos = null;

  function makePoints(count, color, size, blending){
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count*3), 3));
    g.setDrawRange(0, 0);
    const m = new THREE.PointsMaterial({
      color: new THREE.Color(color), size: size, sizeAttenuation: true,
      transparent: true, opacity: blending === 'additive' ? 0.95 : 0.7,
      depthWrite: false,
      blending: blending === 'additive' ? THREE.AdditiveBlending : THREE.NormalBlending,
    });
    const p = new THREE.Points(g, m);
    p.frustumCulled = false;
    return p;
  }

  function rebuildParticles(){
    if(emberPoints){ scene.remove(emberPoints); emberPoints.geometry.dispose(); emberPoints.material.dispose(); emberPoints = null; }
    if(smokePoints){ scene.remove(smokePoints); smokePoints.geometry.dispose(); smokePoints.material.dispose(); smokePoints = null; }
    emberPos = smokePos = null;
    state.particles.length = 0;
    const cfg = geo.particles;
    if(!cfg) return;
    emberPoints = makePoints(MAX_P, cfg.color, cfg.size, cfg.blending || 'additive');
    scene.add(emberPoints);
    emberPos = emberPoints.geometry.getAttribute('position');
    if(cfg.smoke){
      smokePoints = makePoints(MAX_P, cfg.smoke.color, cfg.smoke.size, 'normal');
      scene.add(smokePoints);
      smokePos = smokePoints.geometry.getAttribute('position');
    }
  }
  rebuildParticles();

  function emit(cfg, smoke, count){
    for(let i=0;i<count;i++){
      const ang = Math.random()*Math.PI*2;
      const r = Math.random()*cfg.spread;
      state.particles.push({
        x: cfg.origin[0] + Math.cos(ang)*r*0.5,
        y: cfg.origin[1],
        z: cfg.origin[2] + Math.sin(ang)*r*0.5,
        vx: (Math.random()-0.5)*(smoke?0.10:0.30),
        vy: (smoke?0.30:0.5) + Math.random()*(smoke?0.25:0.5),
        vz: (Math.random()-0.5)*(smoke?0.10:0.30),
        age: 0,
        life: cfg.life*(0.75+Math.random()*0.5),
        smoke: !!smoke,
      });
    }
    if(state.particles.length > MAX_P*2) state.particles.splice(0, state.particles.length - MAX_P*2);
  }

  function spawnParticles(dt){
    const cfg = geo.particles;
    if(!cfg) return;
    const n = cfg.rate*dt;
    const c = Math.floor(n) + (Math.random() < (n%1) ? 1 : 0);
    if(c > 0) emit(cfg, false, c);
    if(cfg.smoke){
      const ns = cfg.smoke.rate*dt;
      const cs = Math.floor(ns) + (Math.random() < (ns%1) ? 1 : 0);
      if(cs > 0) emit(cfg.smoke, true, cs);
    }
  }

  function stepParticles(dt){
    const arr = state.particles;
    for(let i=arr.length-1;i>=0;i--){
      const p = arr[i];
      p.age += dt;
      if(p.age >= p.life){ arr.splice(i,1); continue; }
      p.x += p.vx*dt; p.y += p.vy*dt; p.z += p.vz*dt;
      p.vy -= (p.smoke ? 0.015 : 0.42)*dt;
      if(p.smoke) p.vy += 0.04*dt;
    }
  }

  function syncParticles(){
    let ei = 0, si = 0;
    for(let i=0;i<state.particles.length;i++){
      const p = state.particles[i];
      if(p.smoke){
        if(si < MAX_P && smokePos){ smokePos.setXYZ(si, p.x, p.y, p.z); si++; }
      } else {
        if(ei < MAX_P && emberPos){ emberPos.setXYZ(ei, p.x, p.y, p.z); ei++; }
      }
    }
    if(emberPos){ emberPos.needsUpdate = true; emberPoints.geometry.setDrawRange(0, ei); }
    if(smokePos){ smokePos.needsUpdate = true; smokePoints.geometry.setDrawRange(0, si); }
  }

  /* ---------- 动画 ---------- */
  function applyAnimations(t){
    for(let i=0;i<meshes.length;i++){
      const m = meshes[i];
      const p = m.part;
      if(p.kind === 'pipe') continue;              // 管道是静态的

      m.mesh.position.copy(m.base.pos);
      m.mesh.rotation.copy(m.base.rot);

      const a = p.anim;
      if(!a) continue;

      if(a.kind === 'spin'){
        const ang = t*a.speed;
        if(a.axis === 'x') m.mesh.rotation.x = m.base.rot.x + ang;
        else if(a.axis === 'z') m.mesh.rotation.z = m.base.rot.z + ang;
        else m.mesh.rotation.y = m.base.rot.y + ang;
      }
      else if(a.kind === 'bob'){
        m.mesh.position.y = m.base.pos.y + Math.sin(t*a.speed)*a.amp;
      }
      else if(a.kind === 'slide'){
        const off = Math.sin(t*a.speed)*a.amp;
        if(a.axis === 'x') m.mesh.position.x = m.base.pos.x + off;
        else m.mesh.position.z = m.base.pos.z + off;
      }
      else if(a.kind === 'swing'){
        m.mesh.rotation.z = m.base.rot.z + Math.sin(t*a.speed)*a.amp;
      }
      else if(a.kind === 'pulse'){
        const k = Math.sin(t*a.speed)*0.5 + 0.5;
        m.mesh.material.emissiveIntensity = a.min + (a.max - a.min)*k;
      }
    }
  }

  /* ---------- 相机 ---------- */
  const HOME = { yaw:-0.72, pitch:0.58, dist: radius*3.2 };

  function placeCamera(yaw, pitch, dist){
    camera.position.set(
      Math.sin(yaw)*Math.cos(pitch)*dist,
      Math.sin(pitch)*dist + target.y,
      Math.cos(yaw)*Math.cos(pitch)*dist
    );
    camera.lookAt(target);
  }
  placeCamera(HOME.yaw, HOME.pitch, HOME.dist);

  let controls = null;
  if(THREE.OrbitControls){
    controls = new THREE.OrbitControls(camera, canvas);
    controls.target.copy(target);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.enablePan = false;
    controls.minDistance = radius*1.2;
    controls.maxDistance = radius*9;
    controls.minPolarAngle = 0.18;
    controls.maxPolarAngle = Math.PI*0.53;
    controls.autoRotateSpeed = 1.6;
    controls.update();
  }

  /* ---------- 尺寸 ---------- */
  function resize(){
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    renderer.setSize(w, h, false);
    camera.aspect = w/h;
    camera.updateProjectionMatrix();
    return {w:w, h:h};
  }
  resize();

  /* ---------- 主循环 ---------- */
  const clock = new THREE.Clock();
  let rafId = 0;
  let timerMode = false;
  let lastRafAt = (typeof performance !== 'undefined' ? performance.now() : Date.now());

  function tick(dtOverride){
    if(state.disposed) return;
    const dt = (typeof dtOverride === 'number') ? dtOverride : Math.min(0.05, clock.getDelta());
    if(state.playing){
      const scaled = dt*state.speed;
      state.time += scaled;
      spawnParticles(scaled);
      stepParticles(scaled);
      applyAnimations(state.time);
      syncParticles();
    }
    if(controls && controls.update) controls.update();
    renderer.render(scene, camera);
  }

  function loop(){
    if(state.disposed) return;
    rafId = requestAnimationFrame(loop);
    lastRafAt = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    tick();
  }
  rafId = requestAnimationFrame(loop);

  // 看门狗：rAF 被抑制时（headless / 后台标签 / 低电量模式）降级为定时器
  const watchdog = setInterval(function(){
    if(state.disposed){ clearInterval(watchdog); return; }
    const nowP = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    if(!timerMode && nowP - lastRafAt > 400){
      timerMode = true;
      cancelAnimationFrame(rafId);
      setInterval(function(){
        if(state.disposed) return;
        tick();
      }, 16);
    }
  }, 500);

  /* ---------- 材质预设 ---------- */
  function applyPreset(presetKey){
    state.preset = presetKey;
    geo = buildMachineParts(machine, presetKey);
    for(let i=0;i<meshes.length;i++){
      const m = meshes[i];
      const latest = geo.parts[i];
      if(!latest) continue;
      m.part = latest;
      if(m.mesh.material) m.mesh.material.dispose();
      m.baseMaterial.dispose();
      m.baseMaterial = makeThreeMaterial(latest.mat);
      m.mesh.material = m.baseMaterial.clone();
      const mat = m.mesh.material;
      const c = new THREE.Color(latest.mat.color);
      mat.color.copy(c);
      mat.metalness = latest.mat.metal;
      mat.roughness = latest.mat.rough;
      if(latest.mat.emissive > 0){
        mat.emissive.copy(c);
        mat.emissiveIntensity = latest.mat.emissive;
      }else{
        mat.emissive.setHex(0x000000);
        mat.emissiveIntensity = 0;
      }
      mat.transparent = latest.mat.alpha < 1;
      mat.opacity = latest.mat.alpha;
      mat.needsUpdate = true;
      m.part.anim = latest.anim;
      const override = machine.ui3d && machine.ui3d.parts && machine.ui3d.parts[m.id];
      if(override) applyPartOverride(m.mesh, latest, override);
    }
    rebuildParticles();
    state.needsRender = true;
  }

  return {
    dispose: function(){
      state.disposed = true;
      cancelAnimationFrame(rafId);
      clearInterval(watchdog);
      if(controls && controls.dispose) controls.dispose();
      for(let i=0;i<meshes.length;i++){
        if(meshes[i].mesh.material) meshes[i].mesh.material.dispose();
        meshes[i].baseMaterial.dispose();
      }
      Object.keys(geoCache).forEach(function(k){ geoCache[k].dispose(); });
      groundGeo.dispose(); groundMat.dispose();
      edgeGeo.dispose(); edgeMat.dispose();
      if(emberPoints){ emberPoints.geometry.dispose(); emberPoints.material.dispose(); }
      if(smokePoints){ smokePoints.geometry.dispose(); smokePoints.material.dispose(); }
      renderer.dispose();
    },
    setAutoRotate: function(v){
      state.autoRotate = !!v;
      if(controls) controls.autoRotate = !!v;
    },
    getAutoRotate: function(){ return !!(controls && controls.autoRotate); },
    setPlaying: function(v){ state.playing = !!v; },
    getPlaying: function(){ return state.playing; },
    setSpeed: function(v){ state.speed = Math.max(0.1, Math.min(3, v)); },
    getSpeed: function(){ return state.speed; },
    setPreset: applyPreset,
    getPreset: function(){ return state.preset; },
    getParts: function(){
      return meshes.map(function(entry){
        return {id:entry.id, role:entry.role, kind:entry.part.kind, visible:entry.mesh.visible};
      });
    },
    setPartOverride: function(id, override){
      const entry = meshes.find(function(item){ return item.id === id; });
      if(!entry) return false;
      const mesh = entry.mesh;
      mesh.position.copy(entry.base.pos);
      mesh.rotation.copy(entry.base.rot);
      mesh.quaternion.copy(entry.base.quat);
      mesh.scale.set(1,1,1);
      mesh.visible = !(override && override.hidden);
      if(mesh.material !== entry.baseMaterial) mesh.material.dispose();
      mesh.material = entry.baseMaterial.clone();
      if(override) applyPartOverride(mesh, entry.part, override);
      state.needsRender = true;
      return true;
    },
    reset: function(){
      placeCamera(HOME.yaw, HOME.pitch, HOME.dist);
      if(controls){ controls.target.copy(target); controls.update(); }
    },
    redraw: function(){ renderer.render(scene, camera); },
    toPNG: function(){ renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); },
    /**
     * 导出 GLB（面向 UE 的静态网格）
     *
     * 关键处理：把 N 个部件按「材质角色」合并成 **1 个网格 + N 个材质槽**。
     * 不合并的话，UE 会把每个方块/圆柱都当成独立 StaticMesh 资产，
     * 一个建筑就变成 30 个资产，根本没法用。
     */
    toGLB: function(onDone){
      if(!THREE.GLTFExporter){ onDone(null, new Error('GLTFExporter 未加载')); return; }
      const MergeUtils = THREE.BufferGeometryUtils;
      if(!MergeUtils || !MergeUtils.mergeBufferGeometries){
        onDone(null, new Error('BufferGeometryUtils 未加载，无法合并网格'));
        return;
      }

      // 1. 按 role 分桶（同 role = 同材质）
      const buckets = {};
      const order = [];
      for(let i=0;i<meshes.length;i++){
        const m = meshes[i];
        if(!m.mesh.visible) continue;
        const role = m.role || 'body';
        const override = machine.ui3d && machine.ui3d.parts && machine.ui3d.parts[m.id];
        const key = override && override.material ? role + '_' + m.id : role;
        if(!buckets[key]){ buckets[key] = { role:key, mat:m.mesh.material, geos:[] }; order.push(key); }
        m.mesh.updateWorldMatrix(true, false);
        const g = m.mesh.geometry.clone();
        g.applyMatrix4(m.mesh.matrixWorld);
        // 统一去掉多余属性，保证可合并
        if(g.attributes.uv2) g.deleteAttribute('uv2');
        buckets[role].geos.push(g);
      }

      // 2. 每个桶先合并，再整体按 group 合并
      const perMat = [];
      const materials = [];
      order.forEach(function(role){
        const b = buckets[role];
        let g;
        if(b.geos.length === 1){
          g = b.geos[0];
        }else{
          g = MergeUtils.mergeBufferGeometries(b.geos, false);
          b.geos.forEach(function(x){ x.dispose(); });
        }
        if(!g) return;
        perMat.push(g);
        const m = b.mat.clone();
        m.name = 'M_' + role;              // UE 里的材质槽名
        materials.push(m);
      });

      let finalGeo;
      if(perMat.length === 1){
        finalGeo = perMat[0];
      }else{
        finalGeo = MergeUtils.mergeBufferGeometries(perMat, true);   // useGroups = true
        perMat.forEach(function(x){ x.dispose(); });
      }
      if(!finalGeo){ onDone(null, new Error('几何合并失败')); return; }

      finalGeo.computeBoundingBox();
      const bb = finalGeo.boundingBox;
      const size = new THREE.Vector3();
      bb.getSize(size);

      const out = new THREE.Mesh(finalGeo, materials);
      out.name = machine.id;               // UE 里的静态网格资产名

      // 把动画意图与元数据写进 glTF extras，UE 侧可读到
      // （GLB 本身是静态网格，动画需在 UE 里重建，这里给出参数）
      const animSpec = [];
      meshes.forEach(function(m){
        if(!m.part.anim) return;
        animSpec.push({
          part: m.part.kind || 'box',
          role: m.part.role,
          kind: m.part.anim.kind,
          params: Object.assign({}, m.part.anim, { kind: undefined }),
        });
      });
      // 风格元数据：UE 侧能追溯这批模型属于哪套风格、色板是什么
      let styleMeta = null;
      if(typeof getStyle === 'function'){
        const stt = getStyle();
        styleMeta = {
          presetId: stt.id,
          presetName: stt.name,
          tagline: stt.tagline,
          accent: categoryAccent(machine.cat),
          palette: {
            structure: stt.palette.structure, metal: stt.palette.metal,
            metalDark: stt.palette.metalDark, metalLite: stt.palette.metalLite,
            glow: stt.palette.glow, hazard: stt.palette.hazard,
          },
          knobs: stt.knobs,
        };
      }
      out.userData = {
        forgeworks: {
          generator: 'Forgeworks',
          id: machine.id,
          name: machine.name,
          category: machine.cat,
          footprint: machine.footprint,
          tier: machine.tier,
          unit: 'meter (1 unit = 1 grid)',
          pivot: 'bottom-center',
          materialSlots: materials.map(function(mm){ return mm.name; }),
          animations: animSpec,
          style: styleMeta,
        },
      };

      const exporter = new THREE.GLTFExporter();
      exporter.parse(out, function(result){
        const meta = {
          materials: materials.length,
          vertices: finalGeo.attributes.position ? finalGeo.attributes.position.count : 0,
          // 三角面数（质量门禁用：规格见风格预设 spec.machine，超限要告警）
          triangles: finalGeo.index
            ? Math.round(finalGeo.index.count / 3)
            : (finalGeo.attributes.position ? Math.round(finalGeo.attributes.position.count / 3) : 0),
          sizeM: [ +size.x.toFixed(3), +size.y.toFixed(3), +size.z.toFixed(3) ],
          sizeCm: [ Math.round(size.x*100), Math.round(size.y*100), Math.round(size.z*100) ],
        };
        finalGeo.dispose();
        materials.forEach(function(m){ m.dispose(); });
        onDone(result, null, meta);
      }, function(err){
        finalGeo.dispose();
        onDone(null, err);
      }, { binary: true, onlyVisible: true });
    },
    _advance: function(seconds, step){
      const s = step || 0.016;
      const n = Math.max(1, Math.ceil(seconds / s));
      for(let i=0;i<n;i++) tick(s);
      return state.time;
    },
    _debug: function(){
      const kinds = {};
      meshes.forEach(function(m){ const k = m.part.kind || 'box'; kinds[k] = (kinds[k]||0)+1; });
      group.updateMatrixWorld(true);
      const bb = new THREE.Box3().setFromObject(group);
      const sz = new THREE.Vector3(); bb.getSize(sz);
      return {
        time: state.time, particles: state.particles.length, preset: state.preset,
        meshes: meshes.length, playing: state.playing, kinds: kinds,
        footprint: [geo.W, geo.D],
        fitScale: +fitScale.toFixed(4),
        bbox: {
          min: [ +bb.min.x.toFixed(3), +bb.min.y.toFixed(3), +bb.min.z.toFixed(3) ],
          size: [ +sz.x.toFixed(3), +sz.y.toFixed(3), +sz.z.toFixed(3) ],
        },
      };
    },
  };
}

/* ============================================================
   四、3D 查看弹窗
   ============================================================ */

let _activeViewer = null;

function open3DViewer(machineId){
  const m = machineOf(machineId);
  if(!m) return;
  if(_activeViewer){ _activeViewer.dispose(); _activeViewer = null; }

  if(!haveThree()){
    alert('three.js 未加载。请检查 js/vendor/three.min.js 是否存在。');
    return;
  }

  // 材质下拉 = 项目风格（推荐，与描述词同源）+ 旧材质方案（快速试效果）
  const curStyle = currentStyleId();
  let presetOpts = '';
  if(typeof STYLE_PRESETS !== 'undefined'){
    presetOpts += '<optgroup label="项目风格（与描述词同源）">'
      + stylePresetList().map(function(p){
          return '<option value="'+p.id+'">'+p.name+'</option>';
        }).join('')
      + '</optgroup>';
  }
  presetOpts += '<optgroup label="材质方案（仅改渲染，不改描述词）">'
    + Object.keys(MATERIAL_PRESETS)
        .map(function(k){ return '<option value="'+k+'">'+MATERIAL_PRESETS[k].name+'</option>'; }).join('')
    + '</optgroup>';
  const defaultKey = curStyle || 'industrial';

  document.getElementById('modal').innerHTML =
    '<header><h3>' + m.name + ' · 3D 预览</h3><span class="x" id="v3Close">×</span></header>' +
    '<div class="content" style="padding:0">' +
      '<div style="position:relative;background:#f2f0ec">' +
        '<canvas id="v3Canvas" style="display:block;width:100%;height:420px"></canvas>' +
        '<div style="position:absolute;left:12px;top:10px;font-size:11px;color:#5f5e5a;' +
             'background:rgba(255,255,255,.85);padding:4px 9px;border-radius:6px;pointer-events:none">' +
          '拖动旋转 · 滚轮缩放 · 双击复位</div>' +
      '</div>' +
      '<div style="padding:12px 20px;border-top:1px solid var(--border)">' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">' +
          '<button class="sm" id="v3Play">暂停动画</button>' +
          '<div style="display:flex;align-items:center;gap:6px">' +
            '<span style="font-size:11px;color:var(--text-3)">速度</span>' +
            '<input type="range" id="v3Speed" min="0.25" max="2" step="0.25" value="1" style="width:88px;padding:0">' +
            '<span id="v3SpeedVal" style="font-size:11px;font-family:var(--mono);width:30px">1.0x</span>' +
          '</div>' +
          '<div style="display:flex;align-items:center;gap:6px">' +
            '<span style="font-size:11px;color:var(--text-3)">材质</span>' +
            '<select id="v3Preset" style="padding:4px 8px;font-size:11px">' + presetOpts + '</select>' +
          '</div>' +
          '<button class="sm" id="v3Auto">自动旋转</button>' +
          '<button class="sm" id="v3Reset">复位</button>' +
          '<button class="sm" id="v3Parts">编辑部件</button>' +
          '<button class="sm" id="v3Shot">导出 PNG</button>' +
          '<button class="sm primary" id="v3Glb">导出 GLB</button>' +
        '</div>' +
        '<div style="font-size:11.5px;color:var(--text-2);line-height:1.7">' +
          '<span class="pill">' + m.cat + '</span> <span class="pill">' + m.footprint + '</span> ' +
          tierTag(m.tier) +
          '<span style="margin-left:6px">由圆柱/圆锥/球体/圆环/管道/棱柱组合而成，' +
          '动画与材质为示意。导出的 GLB 可直接拖进 UE / Blender。</span>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<footer>' +
      '<button id="v3Edit">编辑参数</button>' +
      '<button id="v3CopyPrompt">复制描述词</button>' +
      '<button class="primary" id="v3CloseBtn">关闭</button>' +
    '</footer>';

  document.getElementById('mask').classList.remove('hide');
  const canvas = document.getElementById('v3Canvas');

  let V;
  try{
    V = createViewer3D(canvas, m);
  }catch(e){
    document.getElementById('modal').innerHTML =
      '<header><h3>无法初始化 3D 视图</h3><span class="x" id="e3x">×</span></header>' +
      '<div class="content"><div class="issue err"><span class="ic">✕</span><div>' +
      String(e.message) + '</div></div>' +
      '<p class="hint" style="margin-top:12px">常见原因：浏览器/驱动不支持 WebGL，或 vendor 文件缺失。</p></div>' +
      '<footer><button class="primary" id="e3ok">知道了</button></footer>';
    document.getElementById('e3x').onclick = closeModal;
    document.getElementById('e3ok').onclick = closeModal;
    return;
  }
  _activeViewer = V;

  function close(){
    if(_activeViewer){ _activeViewer.dispose(); _activeViewer = null; }
    closeModal();
  }
  document.getElementById('v3Close').onclick = close;
  document.getElementById('v3CloseBtn').onclick = close;
  document.getElementById('v3Reset').onclick = function(){ V.reset(); };
  document.getElementById('v3Parts').onclick = function(){ close(); open3DEditor(m.id); };
  document.getElementById('v3Auto').onclick = function(e){
    const next = !V.getAutoRotate();
    V.setAutoRotate(next);
    e.target.style.background = next ? 'var(--accent)' : '';
    e.target.style.color = next ? '#fff' : '';
  };
  document.getElementById('v3Play').onclick = function(e){
    const next = !V.getPlaying();
    V.setPlaying(next);
    e.target.textContent = next ? '暂停动画' : '播放动画';
  };
  document.getElementById('v3Speed').oninput = function(e){
    const v = parseFloat(e.target.value) || 1;
    V.setSpeed(v);
    document.getElementById('v3SpeedVal').textContent = v.toFixed(1) + 'x';
  };
  const presetSel = document.getElementById('v3Preset');
  presetSel.value = defaultKey;      // 默认选中项目风格
  presetSel.onchange = function(e){ V.setPreset(e.target.value); };
  document.getElementById('v3Shot').onclick = function(){
    downloadDataURL(V.toPNG(), m.id + '_view3d.png');
    toast('已导出当前视角');
  };
  document.getElementById('v3Glb').onclick = function(e){
    e.target.disabled = true;
    e.target.textContent = '导出中…';
    V.toGLB(function(buffer, err, meta){
      e.target.disabled = false;
      e.target.textContent = '导出 GLB';
      if(err || !buffer){ toast('导出失败：' + (err ? err.message : '无数据')); return; }
      const blob = new Blob([buffer], { type:'model/gltf-binary' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = m.id + '.glb';
      document.body.appendChild(a); a.click();
      setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 200);
      const info = meta
        ? ' · 1 网格 / ' + meta.materials + ' 材质槽 · ' + meta.sizeCm.join('×') + ' cm'
        : '';
      toast('已导出 ' + m.id + '.glb' + info);
    });
  };
  document.getElementById('v3Edit').onclick = function(){
    close();                                  // 先释放 WebGL 上下文
    openEditor('machines', m.id);
  };
  document.getElementById('v3CopyPrompt').onclick = function(){
    copyText(machinePrompt(m, {withTech:true}));
  };
}

function downloadDataURL(dataUrl, filename){
  const a = document.createElement('a');
  a.href = dataUrl; a.download = filename;
  document.body.appendChild(a); a.click();
  setTimeout(function(){ a.remove(); }, 100);
}
