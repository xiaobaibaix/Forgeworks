/* Forgeworks · js/engines/viewer3d.js
   ============================================================
   3D 体块查看器（基于 three.js WebGL）
   ------------------------------------------------------------
   three.js 本地 vendored（js/vendor/three.min.js, r147 UMD），
   不依赖 CDN，离线可用。

   能力：
     - 轨道拖动 360° 环绕 / 滚轮缩放 / 阻尼惯性 / 双击复位
     - 材质系统：metalness / roughness / emissive / 透明
     - 材质预设：整栋建筑一键换材质风格
     - 程序化动画：转动 / 摆动 / 平移 / 浮动 / 自发光脉动
     - 粒子系统：火星、烟雾、气泡、碎屑
     - 实时阴影
     - 导出当前视角 PNG
     - 导出 GLB 模型（可直接导入 UE / Blender）

   依赖加载顺序（见 index.html）：
     three.min.js → OrbitControls.js → GLTFExporter.js → 本文件
   ============================================================ */

/* ============================================================
   一、材质定义
   ============================================================ */

const MATERIALS = {
  concrete:  { name:'混凝土', color:'#c6c3bc', metal:0.04, rough:0.92, emissive:0,    alpha:1,    pattern:'grain' },
  steel:     { name:'钢材',   color:'#a4a9b1', metal:0.82, rough:0.34, emissive:0,    alpha:1,    pattern:'none'  },
  steelDark: { name:'暗钢',   color:'#6f757d', metal:0.78, rough:0.52, emissive:0,    alpha:1,    pattern:'none'  },
  steelLite: { name:'亮钢',   color:'#d6dae0', metal:0.72, rough:0.26, emissive:0,    alpha:1,    pattern:'none'  },
  glass:     { name:'玻璃',   color:'#8fb8d8', metal:0.10, rough:0.08, emissive:0.06, alpha:0.42, pattern:'none'  },
  rust:      { name:'锈铁',   color:'#9a6b4a', metal:0.30, rough:0.88, emissive:0,    alpha:1,    pattern:'noise' },
  clean:     { name:'洁净白', color:'#e8eaec', metal:0.08, rough:0.42, emissive:0,    alpha:1,    pattern:'none'  },
  ceramic:   { name:'陶瓷',   color:'#ddd8cc', metal:0.02, rough:0.55, emissive:0,    alpha:1,    pattern:'grain' },
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
  const preset = MATERIAL_PRESETS[presetKey] || MATERIAL_PRESETS.industrial;
  const key = preset.map[role] || ROLE_MAT[role] || 'steel';
  const base = MATERIALS[key] || MATERIALS.steel;
  if(role === 'glow') return Object.assign({}, base, { color: accentColor, emissive: 1.0 });
  return base;
}

/* ============================================================
   二、建筑体块构成（带材质角色 + 动画描述）
   ============================================================ */

const ACCENT_BY_CAT = {
  '采集':'#d9a441', '分离':'#5fa8c4', '冶炼':'#e07b39', '合金':'#8fa3b8',
  '化工':'#6fb86f', '加工':'#7d8b9e', '组装':'#3fa887', '回收':'#b09a6a',
};

function parseFootprint(fp){
  const a = String(fp || '1×1').split(/[×xX]/).map(n => parseFloat(n) || 1);
  return [a[0], a[1] || a[0]];
}

/** 动画描述符：spin / bob / slide / swing / pulse */
function anim(kind, o){ return Object.assign({ kind: kind }, o); }

/**
 * 把一个建筑展开成带材质与动画的长方体（纯数据，不依赖 three）
 */
function buildMachineParts(m, presetKey){
  const fp = parseFootprint(m.footprint);
  const W = fp[0], D = fp[1];
  const accent = ACCENT_BY_CAT[m.cat] || '#8a97a8';
  const parts = [];
  const add = function(x,y,z, w,h,d, role, a){
    parts.push({
      c:[x,y,z], s:[w,h,d], role: role,
      mat: resolveMaterial(role, accent, presetKey || 'industrial'),
      anim: a || null,
    });
  };

  let particles = null;

  add(0, 0.09, 0, W*0.94, 0.18, D*0.94, 'base');

  switch(m.cat){
    case '采集': {
      const tw = W*0.26;
      add(0, 0.18 + 0.75, 0, tw, 1.5, tw, 'body');
      add(0, 0.18 + 1.62, 0, tw*0.5, 0.24, tw*0.5, 'dark');
      add(0, 0.18 + 1.82, 0, tw*0.22, 0.16, tw*0.22, 'accent',
          anim('pulse', {speed:2.4, min:0.35, max:1.6}));
      add(W*0.32, 0.55, D*0.30, W*0.22, 0.5, D*0.22, 'dark',
          anim('bob', {amp:0.035, speed:1.6}));
      add(0, 0.18 + 0.55, 0, tw*0.16, 0.9, tw*0.16, 'light',
          anim('spin', {axis:'y', speed:2.2}));
      particles = { kind:'dust', origin:[0, 0.24, 0], rate:14, spread:W*0.35,
                    life:1.6, color:'#b9b2a4', size:0.05, blending:'normal' };
      break;
    }
    case '分离': {
      add(-W*0.20, 0.18 + 0.42, -D*0.08, W*0.36, 0.84, D*0.36, 'body');
      add( W*0.24, 0.18 + 0.31,  D*0.14, W*0.30, 0.62, D*0.30, 'light',
          anim('bob', {amp:0.03, speed:1.1}));
      add(0, 0.18 + 1.02, 0, W*0.62, 0.10, D*0.12, 'dark');
      add(-W*0.20, 0.18 + 0.90, 0, W*0.10, 0.16, D*0.10, 'accent',
          anim('pulse', {speed:1.8, min:0.4, max:1.5}));
      add( W*0.24, 0.18 + 0.70, 0, W*0.09, 0.14, D*0.09, 'accent');
      add(0, 0.18 + 1.14, 0, W*0.14, 0.12, D*0.14, 'accent',
          anim('spin', {axis:'y', speed:3.0}));
      particles = { kind:'bubble', origin:[W*0.24, 0.5, D*0.14], rate:8, spread:W*0.12,
                    life:1.4, color:'#9fd0e8', size:0.07, blending:'normal' };
      break;
    }
    case '冶炼': {
      add(0, 0.18 + 0.62, 0, W*0.62, 1.24, D*0.62, 'body',
          anim('bob', {amp:0.012, speed:1.2}));
      add(W*0.22, 0.18 + 1.05, D*0.20, W*0.18, 1.9, D*0.18, 'dark');
      // 炉门：自发光脉动 —— 熔炼的核心表现
      add(0, 0.18 + 0.30, D*0.33, W*0.26, 0.42, D*0.04, 'glow',
          anim('pulse', {speed:1.7, min:0.55, max:1.8}));
      add(-W*0.34, 0.18 + 0.36, 0, W*0.12, 0.36, D*0.24, 'dark');
      particles = {
        kind:'ember', origin:[0, 0.45, D*0.36], rate:26, spread:W*0.14,
        life:1.5, color:'#ffb066', size:0.075, blending:'additive',
        smoke: { origin:[W*0.22, 2.25, D*0.20], rate:7, spread:W*0.06,
                 life:2.6, color:'#9aa0a6', size:0.22, blending:'normal' },
      };
      break;
    }
    case '合金': {
      const cw = W*0.10;
      add(-W*0.32, 0.18 + 0.60, -D*0.30, cw, 1.2, cw, 'dark');
      add( W*0.32, 0.18 + 0.60, -D*0.30, cw, 1.2, cw, 'dark');
      add(-W*0.32, 0.18 + 0.60,  D*0.30, cw, 1.2, cw, 'dark');
      add( W*0.32, 0.18 + 0.60,  D*0.30, cw, 1.2, cw, 'dark');
      add(0, 0.18 + 1.28, 0, W*0.70, 0.18, D*0.70, 'body');
      add(0, 0.18 + 0.92, 0, W*0.22, 0.52, D*0.22, 'dark',
          anim('bob', {amp:0.22, speed:2.0}));
      add(0, 0.18 + 0.18, 0, W*0.40, 0.26, D*0.40, 'accent',
          anim('pulse', {speed:2.0, min:0.6, max:1.5}));
      particles = { kind:'spark', origin:[0, 0.5, 0], rate:12, spread:W*0.22,
                    life:1.0, color:'#ffd08a', size:0.05, blending:'additive' };
      break;
    }
    case '化工': {
      add(-W*0.24, 0.18 + 0.50, -D*0.16, W*0.30, 1.0, D*0.30, 'light');
      add( W*0.22, 0.18 + 0.40, -D*0.20, W*0.26, 0.8, D*0.26, 'light',
          anim('bob', {amp:0.025, speed:0.9}));
      add( W*0.10, 0.18 + 0.58,  D*0.24, W*0.24, 1.16, D*0.24, 'body');
      add(0, 0.18 + 1.10, 0, W*0.66, 0.09, D*0.10, 'dark');
      add(-W*0.24, 0.18 + 0.78, 0, W*0.08, 0.14, D*0.08, 'glowGreen',
          anim('pulse', {speed:0.8, min:0.4, max:1.4}));
      particles = { kind:'bubble', origin:[-W*0.24, 0.9, -D*0.16], rate:10, spread:W*0.10,
                    life:2.0, color:'#8fe0b8', size:0.08, blending:'normal' };
      break;
    }
    case '加工': {
      add(0, 0.18 + 0.18, 0, W*0.72, 0.36, D*0.46, 'body');
      add(-W*0.30, 0.18 + 0.55, -D*0.18, W*0.09, 0.74, D*0.09, 'dark');
      add( W*0.30, 0.18 + 0.55, -D*0.18, W*0.09, 0.74, D*0.09, 'dark');
      add(0, 0.18 + 0.96, -D*0.18, W*0.66, 0.14, D*0.12, 'body',
          anim('slide', {axis:'x', amp:W*0.16, speed:0.8}));
      add(0, 0.18 + 0.72, 0, W*0.12, 0.36, D*0.12, 'accent',
          anim('spin', {axis:'y', speed:6.0}));
      add(W*0.26, 0.18 + 0.40, D*0.24, W*0.20, 0.30, D*0.10, 'dark',
          anim('pulse', {speed:1.4, min:0.5, max:1.3}));
      particles = { kind:'spark', origin:[0, 0.62, 0], rate:9, spread:W*0.16,
                    life:0.9, color:'#ffd9a0', size:0.04, blending:'additive' };
      break;
    }
    case '组装': {
      const span = Math.max(W, D);
      const hh = 0.66 + 0.095 * span;
      add(0, 0.18 + hh/2, 0, W*0.82, hh, D*0.82, 'body');
      add(0, 0.18 + hh + 0.09, 0, W*0.54, 0.18, D*0.54, 'light');
      add(0, 0.18 + hh*0.42, D*0.42, W*0.30, hh*0.44, D*0.04, 'glass');
      add(0, 0.18 + hh + 0.24, 0, W*0.16, 0.12, D*0.16, 'accent',
          anim('pulse', {speed:1.2, min:0.4, max:1.4}));
      add(0, 0.18 + hh - 0.10, 0, W*0.24, 0.14, D*0.24, 'accent',
          anim('slide', {axis:'x', amp:W*0.22, speed:0.55}));
      if(span >= 6){
        [[-0.37,-0.37],[0.37,-0.37],[-0.37,0.37],[0.37,0.37]].forEach(function(s){
          add(s[0]*W, 0.18 + hh + 0.55, s[1]*D, W*0.055, 1.1, D*0.055, 'dark');
        });
      }
      particles = { kind:'dust', origin:[0, 0.42, D*0.42], rate:6, spread:W*0.30,
                    life:2.2, color:'#c8ccd2', size:0.06, blending:'normal' };
      break;
    }
    case '回收': {
      add(0, 0.18 + 0.22, 0, W*0.34, 0.44, D*0.34, 'base',
          anim('bob', {amp:0.03, speed:2.6}));
      add(0, 0.18 + 0.68, 0, W*0.56, 0.52, D*0.56, 'body');
      add(W*0.20, 0.18 + 1.10, D*0.18, W*0.14, 1.1, D*0.14, 'dark');
      add(0, 0.18 + 0.98, 0, W*0.20, 0.10, D*0.20, 'accent',
          anim('pulse', {speed:1.0, min:0.4, max:1.4}));
      particles = { kind:'smoke', origin:[W*0.20, 1.75, D*0.18], rate:9, spread:W*0.08,
                    life:2.4, color:'#a8a49c', size:0.22, blending:'normal' };
      break;
    }
    default: {
      add(0, 0.18 + 0.50, 0, W*0.70, 1.0, D*0.70, 'body');
      add(0, 0.18 + 1.05, 0, W*0.40, 0.10, D*0.40, 'accent');
    }
  }

  if(m.tier >= 3){
    add(-W*0.38, 0.18 + 0.24, 0, W*0.10, 0.28, D*0.10, 'dark');
    add( W*0.38, 0.18 + 0.24, 0, W*0.10, 0.28, D*0.10, 'dark');
  }

  const H = parts.reduce(function(mx,p){ return Math.max(mx, p.c[1] + p.s[1]/2); }, 0.5);
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
  if(typeof THREE.OrbitControls !== 'function' && typeof THREE.OrbitControls !== 'object'){
    throw new Error('OrbitControls 未加载，请检查 js/vendor/OrbitControls.js');
  }

  const state = {
    autoRotate: false,
    playing: true,
    speed: 1,
    preset: 'industrial',
    time: 0,
    disposed: false,
    needsRender: true,
    particles: [],
  };

  let geo = buildMachineParts(machine, state.preset);

  /* ---------- 渲染器 ---------- */
  const renderer = new THREE.WebGLRenderer({
    canvas: canvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,     // 导出 PNG 需要
  });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  if('outputEncoding' in renderer) renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.shadowMap.enabled = true;
  if(THREE.PCFSoftShadowMap) renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  /* ---------- 场景 ---------- */
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#f2f0ec');

  // 环境贴图：金属材质没有环境反射会发白/发黑，用 RoomEnvironment 生成一张
  if(THREE.PMREMGenerator && THREE.RoomEnvironment){
    try{
      const pmrem = new THREE.PMREMGenerator(renderer);
      pmrem.compileEquirectangularShader();
      const envRT = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04);
      scene.environment = envRT.texture;
    }catch(e){
      console.warn('环境贴图生成失败，退回纯灯光照明', e);
    }
  }

  const radius = Math.sqrt(geo.W*geo.W + geo.D*geo.D + geo.H*geo.H) / 2;

  const camera = new THREE.PerspectiveCamera(36, 1, 0.05, 200);
  const target = new THREE.Vector3(0, geo.H * 0.34, 0);

  const hemi = new THREE.HemisphereLight(0xffffff, 0x9aa0a6, 0.42);
  scene.add(hemi);

  const key = new THREE.DirectionalLight(0xfff4e6, 1.05);
  key.position.set(-radius*2.2, radius*3.2, radius*2.0);
  key.castShadow = true;
  key.shadow.mapSize.width = 1024;
  key.shadow.mapSize.height = 1024;
  (function(){
    const s = radius * 2.2;
    const c = key.shadow.camera;
    c.left = -s; c.right = s; c.top = s; c.bottom = -s;
    c.near = 0.1; c.far = radius * 12;
    c.updateProjectionMatrix();
  })();
  scene.add(key);

  const rim = new THREE.DirectionalLight(0xcfe0ff, 0.30);
  rim.position.set(radius*2.6, radius*1.4, -radius*2.2);
  scene.add(rim);

  const bounce = new THREE.DirectionalLight(0xffffff, 0.18);
  bounce.position.set(0, -1, 0);
  scene.add(bounce);

  /* ---------- 地面 ---------- */
  const groundGeo = new THREE.PlaneGeometry(geo.W * 1.9, geo.D * 1.9);
  const groundMat = new THREE.MeshStandardMaterial({
    color: 0xe4e1db, roughness: 0.95, metalness: 0.0,
  });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = 0.001;
  ground.receiveShadow = true;
  scene.add(ground);

  // footprint 虚线边框
  const edgePts = [
    new THREE.Vector3(-geo.W/2, 0.004, -geo.D/2),
    new THREE.Vector3( geo.W/2, 0.004, -geo.D/2),
    new THREE.Vector3( geo.W/2, 0.004,  geo.D/2),
    new THREE.Vector3(-geo.W/2, 0.004,  geo.D/2),
    new THREE.Vector3(-geo.W/2, 0.004, -geo.D/2),
  ];
  const edgeGeo = new THREE.BufferGeometry().setFromPoints(edgePts);
  const edgeMat = new THREE.LineDashedMaterial({ color: 0x8a8880, dashSize: 0.12, gapSize: 0.08 });
  const edgeLine = new THREE.Line(edgeGeo, edgeMat);
  if(edgeLine.computeLineDistances) edgeLine.computeLineDistances();
  scene.add(edgeLine);

  /* ---------- 部件 ---------- */
  const group = new THREE.Group();
  scene.add(group);
  const meshes = [];

  const geoCache = {};
  function boxGeo(w,h,d){
    const k = w.toFixed(3)+'|'+h.toFixed(3)+'|'+d.toFixed(3);
    if(!geoCache[k]) geoCache[k] = new THREE.BoxGeometry(w,h,d);
    return geoCache[k];
  }

  function makeThreeMaterial(mat){
    const c = new THREE.Color(mat.color);
    const emissiveColor = mat.emissive > 0 ? c.clone() : new THREE.Color(0x000000);
    return new THREE.MeshStandardMaterial({
      color: c,
      metalness: mat.metal,
      roughness: mat.rough,
      emissive: emissiveColor,
      emissiveIntensity: mat.emissive,
      transparent: mat.alpha < 1,
      opacity: mat.alpha,
      flatShading: true,
      side: THREE.FrontSide,
      envMapIntensity: 0.85,
    });
  }

  function buildMeshes(){
    // 清空
    for(let i=meshes.length-1;i>=0;i--){
      const m = meshes[i];
      group.remove(m.mesh);
      if(m.mesh.material) m.mesh.material.dispose();
      meshes.splice(i,1);
    }
    geo.parts.forEach(function(p){
      const mat = makeThreeMaterial(p.mat);
      const mesh = new THREE.Mesh(boxGeo(p.s[0], p.s[1], p.s[2]), mat);
      mesh.position.set(p.c[0], p.c[1], p.c[2]);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
      meshes.push({ mesh: mesh, part: p, base: { x:p.c[0], y:p.c[1], z:p.c[2] } });
    });
  }
  buildMeshes();

  /* ---------- 粒子 ---------- */
  const MAX_P = 300;
  let emberPoints = null, smokePoints = null, emberPos = null, smokePos = null;

  function makePoints(count, color, size, blending){
    const g = new THREE.BufferGeometry();
    const arr = new Float32Array(count * 3);
    g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
    g.setDrawRange(0, 0);
    const m = new THREE.PointsMaterial({
      color: new THREE.Color(color),
      size: size,
      sizeAttenuation: true,
      transparent: true,
      opacity: blending === 'additive' ? 0.95 : 0.7,
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
      const ang = Math.random() * Math.PI * 2;
      const r = Math.random() * cfg.spread;
      state.particles.push({
        x: cfg.origin[0] + Math.cos(ang) * r * 0.5,
        y: cfg.origin[1],
        z: cfg.origin[2] + Math.sin(ang) * r * 0.5,
        vx: (Math.random()-0.5) * (smoke ? 0.10 : 0.30),
        vy: (smoke ? 0.30 : 0.5) + Math.random() * (smoke ? 0.25 : 0.5),
        vz: (Math.random()-0.5) * (smoke ? 0.10 : 0.30),
        age: 0,
        life: cfg.life * (0.75 + Math.random()*0.5),
        smoke: !!smoke,
      });
    }
    if(state.particles.length > MAX_P*2) state.particles.splice(0, state.particles.length - MAX_P*2);
  }

  function spawnParticles(dt){
    const cfg = geo.particles;
    if(!cfg) return;
    const n = cfg.rate * dt;
    let c = Math.floor(n) + (Math.random() < (n % 1) ? 1 : 0);
    if(c > 0) emit(cfg, false, c);
    if(cfg.smoke){
      const ns = cfg.smoke.rate * dt;
      let cs = Math.floor(ns) + (Math.random() < (ns % 1) ? 1 : 0);
      if(cs > 0) emit(cfg.smoke, true, cs);
    }
  }

  function stepParticles(dt){
    const arr = state.particles;
    for(let i=arr.length-1;i>=0;i--){
      const p = arr[i];
      p.age += dt;
      if(p.age >= p.life){ arr.splice(i,1); continue; }
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.z += p.vz * dt;
      p.vy -= (p.smoke ? 0.015 : 0.42) * dt;
      if(p.smoke) p.vy += 0.04 * dt;
    }
  }

  function syncParticles(){
    let ei = 0, si = 0;
    for(let i=0;i<state.particles.length;i++){
      const p = state.particles[i];
      if(p.smoke){
        if(si < MAX_P && smokePos){
          smokePos.setXYZ(si, p.x, p.y, p.z);
          si++;
        }
      } else {
        if(ei < MAX_P && emberPos){
          emberPos.setXYZ(ei, p.x, p.y, p.z);
          ei++;
        }
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
      const a = p.anim;

      // 重置到基准
      m.mesh.position.set(m.base.x, m.base.y, m.base.z);
      m.mesh.rotation.set(0,0,0);

      if(!a) continue;

      if(a.kind === 'spin'){
        const ang = t * a.speed;
        if(a.axis === 'x') m.mesh.rotation.x = ang;
        else if(a.axis === 'z') m.mesh.rotation.z = ang;
        else m.mesh.rotation.y = ang;
      }
      else if(a.kind === 'bob'){
        m.mesh.position.y = m.base.y + Math.sin(t * a.speed) * a.amp;
      }
      else if(a.kind === 'slide'){
        const off = Math.sin(t * a.speed) * a.amp;
        if(a.axis === 'x') m.mesh.position.x = m.base.x + off;
        else m.mesh.position.z = m.base.z + off;
      }
      else if(a.kind === 'swing'){
        m.mesh.rotation.z = Math.sin(t * a.speed) * a.amp;
      }
      else if(a.kind === 'pulse'){
        const k = Math.sin(t * a.speed) * 0.5 + 0.5;
        const val = a.min + (a.max - a.min) * k;
        m.mesh.material.emissiveIntensity = val;
      }
    }
  }

  /* ---------- 相机 & 控制 ---------- */
  const HOME = { yaw: -0.72, pitch: 0.62, dist: radius * 3.4 };

  function placeCamera(yaw, pitch, dist){
    const tx = Math.sin(yaw) * Math.cos(pitch) * dist;
    const ty = Math.sin(pitch) * dist;
    const tz = Math.cos(yaw) * Math.cos(pitch) * dist;
    camera.position.set(tx, ty + target.y, tz);
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
    controls.minDistance = radius * 1.25;
    controls.maxDistance = radius * 9;
    controls.minPolarAngle = 0.18;
    controls.maxPolarAngle = Math.PI * 0.53;   // 不钻到地下
    controls.autoRotateSpeed = 1.6;
    controls.update();
  }

  /* ---------- 尺寸 ---------- */
  function resize(){
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    return {w:w, h:h};
  }
  resize();

  /* ---------- 主循环 ---------- */
  const clock = new THREE.Clock();
  let rafId = 0;

  function tick(dtOverride){
    if(state.disposed) return;
    const dt = (typeof dtOverride === 'number') ? dtOverride : Math.min(0.05, clock.getDelta());

    if(state.playing){
      const scaled = dt * state.speed;
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
  // 看门狗：rAF 被抑制时（headless / 后台标签 / 低电量模式）降级为定时器
  let timerMode = false;
  let lastRafAt = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  rafId = requestAnimationFrame(loop);
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
      // 同名部件的 mat 已随 geo 重建，直接更新现有 material
      const latest = geo.parts[i];
      if(!latest) continue;
      m.part = latest;
      const mat = m.mesh.material;
      const c = new THREE.Color(latest.mat.color);
      mat.color.copy(c);
      mat.metalness = latest.mat.metal;
      mat.roughness = latest.mat.rough;
      if(latest.mat.emissive > 0){
        mat.emissive.copy(c);
        mat.emissiveIntensity = latest.mat.emissive;
      } else {
        mat.emissive.setHex(0x000000);
        mat.emissiveIntensity = 0;
      }
      mat.transparent = latest.mat.alpha < 1;
      mat.opacity = latest.mat.alpha;
      mat.needsUpdate = true;
      // 动画状态也要更新
      m.part.anim = latest.anim;
    }
    rebuildParticles();
    state.needsRender = true;
  }

  /* ---------- 对外 API ---------- */
  return {
    dispose: function(){
      state.disposed = true;
      cancelAnimationFrame(rafId);
      clearInterval(watchdog);
      if(controls && controls.dispose) controls.dispose();
      for(let i=0;i<meshes.length;i++){
        const m = meshes[i];
        if(m.mesh.material) m.mesh.material.dispose();
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
      state.needsRender = true;
    },
    getAutoRotate: function(){ return !!(controls && controls.autoRotate); },
    setPlaying: function(v){ state.playing = !!v; },
    getPlaying: function(){ return state.playing; },
    setSpeed: function(v){ state.speed = Math.max(0.1, Math.min(3, v)); },
    getSpeed: function(){ return state.speed; },
    setPreset: applyPreset,
    getPreset: function(){ return state.preset; },
    reset: function(){
      placeCamera(HOME.yaw, HOME.pitch, HOME.dist);
      if(controls){ controls.target.copy(target); controls.update(); }
      state.needsRender = true;
    },
    redraw: function(){ renderer.render(scene, camera); },
    /** 确定性推进（测试/截图用）：按固定步长跑 n 步 */
    _advance: function(seconds, step){
      const s = step || 0.016;
      const n = Math.max(1, Math.ceil(seconds / s));
      for(let i=0;i<n;i++) tick(s);
      return state.time;
    },
    _tickOnce: function(dt){ tick(typeof dt === 'number' ? dt : 0.016); },
    toPNG: function(){
      renderer.render(scene, camera);
      return renderer.domElement.toDataURL('image/png');
    },
    /** 导出 GLB（可直接拖进 UE / Blender） */
    toGLB: function(onDone){
      if(!THREE.GLTFExporter){ onDone(null, new Error('GLTFExporter 未加载')); return; }
      const exporter = new THREE.GLTFExporter();
      // 导出前把地面/边线隐藏，只导出建筑本体
      const wasGround = ground.visible, wasEdge = edgeLine.visible;
      ground.visible = false; edgeLine.visible = false;
      const pe = emberPoints ? emberPoints.visible : false;
      const ps = smokePoints ? smokePoints.visible : false;
      if(emberPoints) emberPoints.visible = false;
      if(smokePoints) smokePoints.visible = false;

      exporter.parse(group, function(result){
        ground.visible = wasGround; edgeLine.visible = wasEdge;
        if(emberPoints) emberPoints.visible = pe;
        if(smokePoints) smokePoints.visible = ps;
        onDone(result, null);
      }, function(err){
        ground.visible = wasGround; edgeLine.visible = wasEdge;
        onDone(null, err);
      }, { binary: true });
    },
    _debug: function(){
      return {
        time: state.time,
        particles: state.particles.length,
        preset: state.preset,
        meshes: meshes.length,
        playing: state.playing,
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

  const presetOpts = Object.keys(MATERIAL_PRESETS)
    .map(function(k){ return '<option value="'+k+'">'+MATERIAL_PRESETS[k].name+'</option>'; }).join('');

  document.getElementById('modal').innerHTML =
    '<header><h3>' + m.name + ' · 3D 预览</h3><span class="x" id="v3Close">×</span></header>' +
    '<div class="content" style="padding:0">' +
      '<div style="position:relative;background:#f2f0ec">' +
        '<canvas id="v3Canvas" style="display:block;width:100%;height:400px"></canvas>' +
        '<div style="position:absolute;left:12px;top:10px;font-size:11px;color:#5f5e5a;' +
             'background:rgba(255,255,255,.85);padding:4px 9px;border-radius:6px;pointer-events:none">' +
          '拖动旋转 · 滚轮缩放 · 右键平移禁用</div>' +
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
          '<button class="sm" id="v3Shot">导出 PNG</button>' +
          '<button class="sm primary" id="v3Glb">导出 GLB</button>' +
        '</div>' +
        '<div style="font-size:11.5px;color:var(--text-2);line-height:1.7">' +
          '<span class="pill">' + m.cat + '</span> <span class="pill">' + m.footprint + '</span> ' +
          tierTag(m.tier) +
          '<span style="margin-left:6px">体块由 three.js 实时渲染；动画与材质为示意。' +
          '导出的 GLB 可直接拖进 UE / Blender 当占位模型用。</span>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<footer>' +
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
  document.getElementById('v3Preset').onchange = function(e){ V.setPreset(e.target.value); };
  document.getElementById('v3Shot').onclick = function(){
    const url = V.toPNG();
    downloadDataURL(url, m.id + '_view3d.png');
    toast('已导出当前视角');
  };
  document.getElementById('v3Glb').onclick = function(e){
    e.target.disabled = true;
    e.target.textContent = '导出中…';
    V.toGLB(function(buffer, err){
      e.target.disabled = false;
      e.target.textContent = '导出 GLB';
      if(err || !buffer){ toast('导出失败：' + (err ? err.message : '无数据')); return; }
      const blob = new Blob([buffer], { type: 'model/gltf-binary' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = m.id + '.glb';
      document.body.appendChild(a); a.click();
      setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 200);
      toast('已导出 ' + m.id + '.glb');
    });
  };
  document.getElementById('v3CopyPrompt').onclick = function(){
    copyText(machinePrompt(m, {withTech:true}));
  };
}

/** 下载 dataURL（供 PNG 导出用） */
function downloadDataURL(dataUrl, filename){
  const a = document.createElement('a');
  a.href = dataUrl; a.download = filename;
  document.body.appendChild(a); a.click();
  setTimeout(function(){ a.remove(); }, 100);
}
