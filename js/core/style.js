/* Forgeworks · js/core/style.js
   ============================================================
   风格引擎 —— 项目的美术单一来源（single source of truth）
   ------------------------------------------------------------
   本项目以前有四套风格各说各话：
     prompts.js 的 STYLE_BLOCK      → 描述词
     MACHINE_BRIEFS[].palette       → 32 个建筑各自手写的配色
     viewer3d.js 的 MATERIAL_PRESETS→ 3D 预览材质
     icons.js / CATEGORY_TONE       → 图标与体块预览
   结果是「预览里看到的」和「描述词让 AI 生成的」不是一个风格。

   本模块把这四者统一到一处，并提供**强制统一**的能力：
     - getStyle()      返回当前有效风格（基线 + 用户覆盖）
     - fitColor()      把任意颜色校正进该风格的「角色带」
     - stylePalette()  派生出成套的完整色板
     - styleCheck()    扫描全部内容，报告哪些颜色破坏统一

   核心思路
   --------
   **色相负责区分功能，饱和度/明度负责统一风格。**
   所以 fitColor() 保留色相（冶炼还是橙色、化工还是绿色），
   但把饱和度和明度压进该角色规定的区间内 —— 视觉上就成套了。
   ============================================================ */

/* ---------- 存储（跟内容数据分开，避免导出内容时串味） ---------- */
const LS_STYLE_KEY = 'forgeworks.style.v1';

let styleState = loadStyleState();

function loadStyleState(){
  let s = null;
  try{
    const raw = localStorage.getItem(LS_STYLE_KEY);
    if(raw){
      const p = JSON.parse(raw);
      // 旧数据可能带 presetId，单风格之后只保留旋钮覆盖
      if(p && p.overrides && typeof p.overrides === 'object') s = { overrides:p.overrides };
    }
  }catch(e){ console.warn('style load fail', e); }
  if(!s) s = { overrides:{} };
  return s;
}
function saveStyleState(){
  try{ localStorage.setItem(LS_STYLE_KEY, JSON.stringify(styleState)); }
  catch(e){ console.warn('style save fail', e); }
}

/* ============================================================
   一、读取与切换
   ============================================================ */

function stylePreset(){ return STYLE_PRESET; }

/** 某个旋钮的当前值（覆盖优先，其次基线隐含值，最后旋钮默认值） */
function knobValue(key){
  const k = STYLE_KNOBS.find(x=>x.key===key);
  if(!k) return 0;
  if(styleState.overrides[key] !== undefined && styleState.overrides[key] !== null){
    const v = Number(styleState.overrides[key]);
    if(!isNaN(v)) return v;
  }
  // 基线可以隐含旋钮值
  const p = stylePreset();
  if(p.knobs && p.knobs[key] !== undefined) return Number(p.knobs[key]);
  return k.def;
}

/**
 * 当前有效风格 = 基线（深拷贝）+ 旋钮值 + 派生色板
 * 每次调用都重新计算，所以改了旋钮立刻生效，不需要手动失效缓存。
 */
function getStyle(){
  const p = stylePreset();
  const knobs = {};
  STYLE_KNOBS.forEach(k=>{ knobs[k.key] = knobValue(k.key); });
  const st = {
    id: p.id, name: p.name, tagline: p.tagline, eraHint: p.eraHint,
    form: p.form, surface: p.surface, present: p.present,
    matMap: p.matMap, matTweak: p.matTweak, spec: p.spec, icon: p.icon,
    knobs,
    isDirty: Object.keys(styleState.overrides).length > 0,
  };
  // 磨损度覆盖基线里的定性描述
  st.wearLabel = wearLabel(knobs.wear);
  st.detailLabel = detailLabel(knobs.detail);
  st.palette = stylePalette(st, p);
  st.negative = styleNegative(st, p);
  return st;
}

/** 风格变了要通知下游重画（图标缓存、3D 材质、体块预览） */
function _bumpStyleDependents(){
  if(typeof clearIconCache === 'function') clearIconCache();
}

function setKnob(key, val){
  const k = STYLE_KNOBS.find(x=>x.key===key);
  if(!k) return;
  const v = Math.max(k.min, Math.min(k.max, Number(val)));
  // 等于基线默认值时不存，保持"未修改"状态
  const p = stylePreset();
  const base = (p.knobs && p.knobs[key] !== undefined) ? Number(p.knobs[key]) : k.def;
  if(Math.abs(v - base) < 1e-6) delete styleState.overrides[key];
  else styleState.overrides[key] = v;
  saveStyleState();
  _bumpStyleDependents();
}
function resetKnobs(){
  styleState.overrides = {};
  saveStyleState();
  _bumpStyleDependents();
}

/* ============================================================
   二、颜色校正 —— 风格统一的核心
   ============================================================ */

/** 某角色在当前风格下的 [sat区间, lig区间]（已应用旋钮） */
function toneBand(role, st){
  const t = STYLE_TONES[role] || STYLE_TONES.metal;
  const k = st.knobs;
  let sat = t.sat.slice();
  let lig = t.lig.slice();

  // 饱和度：整体平移
  const sb = k.satBoost || 0;
  sat = [ Math.max(0, Math.min(100, sat[0] + sb)),
          Math.max(0, Math.min(100, sat[1] + sb)) ];
  if(sat[0] > sat[1]) sat = [sat[1], sat[0]];

  // 明度：以中性点为中心按 contrast 缩放（拉开明暗层次）
  const mid = 52, c = k.contrast || 1;
  lig = lig.map(v => Math.max(0, Math.min(100, mid + (v - mid) * c)));
  if(lig[0] > lig[1]) lig = [lig[1], lig[0]];

  return { sat, lig, label:t.label, area:t.area, note:t.note };
}

/**
 * 把任意颜色校正进指定角色的带内（色相保留）
 * @returns {hex, before, satDelta, ligDelta, band}
 */
function fitColor(hex, role, st){
  st = st || getStyle();
  const band = toneBand(role, st);
  const r = clampSL(hex, band.sat, band.lig);
  return {
    hex: r.hex, before: hex,
    hue: r.h, sat: r.s, lig: r.l,
    satAfter: r.cs, ligAfter: r.cl,
    satDelta: r.satDelta, ligDelta: r.ligDelta,
    band,
    changed: Math.abs(r.satDelta) > 0.5 || Math.abs(r.ligDelta) > 0.5,
  };
}

/** 只报告，不改色 —— 供一致性检查用 */
function colorDrift(hex, role, st){
  const f = fitColor(hex, role, st);
  const amt = Math.abs(f.satDelta) + Math.abs(f.ligDelta);
  return { drift: amt, severity: amt > 26 ? 'high' : amt > 12 ? 'mid' : amt > 4 ? 'low' : 'ok', fit:f };
}

/* ============================================================
   三、派生色板
   ============================================================ */

function stylePalette(st, preset){
  preset = preset || stylePreset();
  const raw = preset.palette;
  const out = { raw:{}, accent:{}, accentRaw:{} };

  ['structure','metal','metalDark','metalLite','glass','glow','hazard'].forEach(role=>{
    const roleKey = role === 'hazard' ? 'hazard'
                  : role === 'glow' ? 'glow' : role;
    out[role] = fitColor(raw[role], roleKey, st).hex;
    out.raw[role] = raw[role];
  });

  Object.keys(raw.accent || {}).forEach(cat=>{
    out.accent[cat] = fitColor(raw.accent[cat], 'accent', st).hex;
    out.accentRaw[cat] = raw.accent[cat];
  });
  return out;
}

/** 分类强调色（未知分类兜底） */
function accentFor(cat, st){
  st = st || getStyle();
  const a = st.palette.accent;
  if(a && a[cat]) return a[cat];
  for(const c of ACCENT_FALLBACK_ORDER){ if(a && a[c]) return a[c]; }
  return st.palette.metal;
}

/* ============================================================
   四、负向词与材质参数
   ============================================================ */

function styleNegative(st, preset){
  preset = preset || stylePreset();
  const list = (preset.negative || []).slice();
  // 磨损度低时，把"做旧"类词反过来加进负向
  if((st.knobs.wear || 0) < 0.2 && list.indexOf('锈迹斑驳') < 0) list.push('锈迹与做旧');
  // 细节密度低时，避免密密麻麻的构件
  if((st.knobs.detail || 0) < 0.3) list.push('密集管路与法兰');
  return list;
}

/** 给 3D 查看器用的材质参数（当前风格） */
function matParams(st){
  st = st || getStyle();
  const tw = st.matTweak || {};
  return {
    map: st.matMap,
    metalAdd: (tw.metalAdd || 0) + ((st.knobs.metal - 0.5) * 0.5),
    roughAdd: (tw.roughAdd || 0) + ((st.knobs.wear - 0.3) * 0.35),
    emissiveScale: (tw.emissiveScale || 1) * (st.knobs.glow || 1),
  };
}

/**
 * 3D 查看器的材质下拉里既有风格 id 也有旧材质方案名，这里统一解析。
 * @param {string} id 风格 id 或 MATERIAL_PRESETS 的 key
 * @returns {map, metalAdd, roughAdd, emissiveScale} 或 null
 */
function matParamsFor(id){
  // 旧体系：纯材质方案（industrial / rusted / ...）
  if(typeof MATERIAL_PRESETS !== 'undefined' && MATERIAL_PRESETS[id]){
    return { map: MATERIAL_PRESETS[id].map, metalAdd:0, roughAdd:0, emissiveScale:1 };
  }
  if(id !== STYLE_PRESET.id) return null;
  return matParams(getStyle());
}

/* ============================================================
   五、风格文案（供描述词与导出复用）
   ============================================================ */

/**
 * 一段可以直接塞进描述词的风格约束
 * @param {object} opt {full:bool} full=true 输出完整版（导出/风格页），
 *                                 默认精简版（嵌进每个建筑的描述词，避免重复一大段）
 */
function styleBrief(st, opt){
  st = st || getStyle();
  opt = opt || {};
  const full = !!opt.full;
  let s = '';
  s += `【风格】${st.name}：${st.tagline}\n`;
  s += `【形态】${st.form.body}；${st.form.bevelNote}\n`;
  s += `【着色】${st.surface.shading}\n`;
  s += `【材质】${st.surface.pbr}；磨损度 ${st.wearLabel}\n`;
  if(full || (st.knobs.detail || 0) !== 0.5) s += `【细节密度】${st.detailLabel}\n`;

  if(full){
    s += `【配色约束】结构 ${st.palette.structure}；主体 ${st.palette.metal}；`
       + `暗部 ${st.palette.metalDark}；亮部 ${st.palette.metalLite}；`
       + `玻璃 ${st.palette.glass}；发光 ${st.palette.glow}；警示 ${st.palette.hazard}\n`;
    const acc = st.palette.accent;
    if(acc && Object.keys(acc).length){
      s += `【分类强调色】` + Object.keys(acc).map(k=>k+' '+acc[k]).join('；') + `\n`;
    }
  }
  s += `【饱和纪律】大面积结构低饱和（≤${Math.round(toneBand('structure', st).sat[1])}%），`
     + `强调色可到 ${Math.round(toneBand('accent', st).sat[1])}% 但只用于小面积\n`;
  s += `【呈现】${st.present.lighting}；${st.present.background}；${st.present.camera}\n`;
  if(full || opt.withNegative !== false){
    if(opt.withNegative !== false) s += `【负向】${st.negative.join('、')}\n`;
  }
  return s;
}

/**
 * 推断一组配色的角色分工。
 *
 * 不能简单地"第一个是强调色" —— 实际数据里顺序不统一：
 *   '锈红 #8b6b4a + 深钢灰 #3d3d3b'  强调在前
 *   '钢灰 #6b6e73 + 炉火橙 #e07b39'  强调在后
 * 所以按**饱和度**判断：最艳的那个是强调色，其余按明度分暗部/结构/亮部。
 * （这也是美术的直觉：强调色就是那个最跳的）
 */
function assignPaletteRoles(hexes){
  if(!hexes || !hexes.length) return [];
  const hsls = hexes.map(function(h){ return hexToHsl(h); });

  // 单色：低饱和当结构色，否则当强调色
  if(hexes.length === 1){
    return [ hsls[0].s < 22 ? 'structure' : 'accent' ];
  }

  let maxIdx = 0, maxS = -1;
  hsls.forEach(function(c, i){ if(c.s > maxS){ maxS = c.s; maxIdx = i; } });

  return hsls.map(function(c, i){
    if(i === maxIdx) return 'accent';
    if(c.l < 42) return 'metalDark';
    if(c.l > 70) return 'metalLite';
    return 'structure';
  });
}

/**
 * 把手写配色里的十六进制色校正进风格带，文字描述保留。
 * 比如 '锈红 #8b6b4a + 深钢灰 #3d3d3b' —— "锈红""深钢灰"这些质感描述是有用的，
 * 但具体色值可能偏离风格，所以按角色校正后替换。
 * @returns {text, changed, drift, count, roles}
 */
function fitBriefPalette(text, st){
  st = st || getStyle();
  const src = String(text || '');
  const hexes = src.match(HEX_RE);
  if(!hexes || !hexes.length) return { text: src, changed:false, drift:0, count:0, roles:[] };

  const roles = assignPaletteRoles(hexes);
  let i = 0, drift = 0;
  const out = src.replace(HEX_RE, function(h){
    const f = fitColor(h, roles[i] || 'metal', st);
    drift += Math.abs(f.satDelta) + Math.abs(f.ligDelta);
    i++;
    return f.hex;
  });
  return { text: out, changed: drift > 1, drift: Math.round(drift), count: i, roles: roles };
}

/** 物品颜色的「风格校正值」—— 图标与描述词都用它，保证两者一致 */
function itemFitColor(it, st){
  st = st || getStyle();
  const role = (it.type === 'raw' || it.type === 'ore' || it.type === 'byproduct')
    ? 'metal' : 'accent';
  const f = fitColor(it.color || '#888780', role, st);
  // 发光类物品（能量/等离子体）走 glow 角色
  if(it.type === 'fluid' || /等离子|等离子|能量|plasma/i.test(it.name || '')){
    return fitColor(it.color || '#888780', 'glow', st);
  }
  return f;
}

/* ============================================================
   六、一致性检查
   ------------------------------------------------------------
   扫描全部内容，找出「破坏成套感」的颜色。
   分三批：建筑配色 / 物品主色 / 图标与体块配色。
   ============================================================ */

const HEX_RE = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/g;

function styleCheck(){
  const st = getStyle();
  const issues = [];
  const scan = (label, hex, role, where, fix)=>{
    const d = colorDrift(hex, role, st);
    if(d.severity === 'ok') return;
    issues.push({
      kind: label, where, role,
      hex, fit: d.fit.hex, drift: Math.round(d.drift),
      severity: d.severity,
      sat: Math.round(d.fit.sat), lig: Math.round(d.fit.lig),
      satAfter: Math.round(d.fit.satAfter), ligAfter: Math.round(d.fit.ligAfter),
      band: d.fit.band,
      fix: fix || null,
    });
  };

  // 1. 建筑：MACHINE_BRIEFS 里手写的 palette
  Object.keys(MACHINE_BRIEFS).forEach(id=>{
    const b = MACHINE_BRIEFS[id];
    if(!b || !b.palette) return;
    const m = machineOf(id);
    (String(b.palette).match(HEX_RE) || []).forEach(h=>{
      scan('建筑配色', h, 'accent', (m ? m.name : id) + '（' + id + '）',
           '把该色换成风格派生色，或在描述词里改用分类强调色');
    });
  });

  // 2. 物品：color 字段（图标与模型都用它）
  (S.items || []).forEach(it=>{
    if(!it.color) return;
    scan('物品主色', it.color,
         (it.type === 'raw' || it.type === 'ore') ? 'metal' : 'accent',
         it.name + '（' + it.id + '）',
         '换成风格色板内的同色相颜色');
  });

  // 3. 体块预览的兜底色（CATEGORY_TONE）—— 只验证「兜底值是否与风格同步」，
  //    正常渲染路径走 stylePalette()，不走它，所以优先级低。
  Object.keys(CATEGORY_TONE).forEach(cat=>{
    scan('兜底预览色', CATEGORY_TONE[cat], 'accent', cat + ' 类预览（兜底）',
         '无需改，正常渲染走风格色板；此值仅在风格模块缺失时生效');
  });

  // 4. 图标兜底调色（MASSING_TONE）—— 只查 top 面。
  //    left/right 是人为压暗的面色（差 22~27 明度），按角色带检查必然报偏离，
  //    那是等轴测投影的高光/暗面区分，属于正常，不能算偏离。
  Object.keys(MASSING_TONE).forEach(role=>{
    const toneRole = (role === 'base') ? 'structure' : (role === 'accent' ? 'accent' : 'metal');
    scan('兜底体块色', MASSING_TONE[role].top, toneRole, role + '.top（兜底）', null);
  });

  const bySev = { high:0, mid:0, low:0 };
  const byKind = {};
  issues.forEach(i=>{
    bySev[i.severity]++;
    if(!byKind[i.kind]) byKind[i.kind] = { total:0, high:0, mid:0, low:0 };
    byKind[i.kind].total++;
    byKind[i.kind][i.severity]++;
  });
  return {
    styleId: st.id, styleName: st.name,
    total: issues.length, bySeverity: bySev, byKind,
    issues: issues.sort((a,b)=> b.drift - a.drift),
  };
}

/* ============================================================
   七、配色修正表（把诊断变成行动）
   ------------------------------------------------------------
   一致性检查能告诉你"哪些配色不统一"，但光知道没用。
   这里生成一份「修正后的 palette」，可以直接粘贴回 prompts.js。
   ============================================================ */

function stylePaletteFixTable(){
  const st = getStyle();
  const out = {};
  if(typeof MACHINE_BRIEFS === 'undefined') return out;
  Object.keys(MACHINE_BRIEFS).forEach(function(id){
    const b = MACHINE_BRIEFS[id];
    if(!b || !b.palette) return;
    const r = fitBriefPalette(b.palette, st);
    if(!r.changed) return;
    out[id] = { before: b.palette, after: r.text, drift: r.drift, count: r.count };
  });
  return out;
}

/** 生成可直接粘贴回 js/data/prompts.js 的代码片段 */
function styleFixSnippet(){
  const t = stylePaletteFixTable();
  const ids = Object.keys(t);
  const st = getStyle();
  if(!ids.length) return '// 当前风格（' + st.name + '）下没有需要修正的建筑配色。';

  // 按偏离量从大到小，改最值得改的
  ids.sort(function(a,b){ return t[b].drift - t[a].drift; });

  let s = '// ===== 由 Forgeworks 风格引擎生成（' + new Date().toLocaleString('zh-CN') + '）=====\n';
  s += '// 风格：' + st.name + ' — ' + st.tagline + '\n';
  s += '// 用法：把下面各条 palette 覆盖 js/data/prompts.js 里 MACHINE_BRIEFS 的同名项。\n';
  s += '// 注意：不改也不会出错 —— 描述词渲染时会自动校正；改了是把校正结果固化下来。\n\n';
  s += 'const PALETTE_FIX = {\n';
  ids.forEach(function(id){
    s += '  ' + id + ': {\n';
    s += '    // 原：' + t[id].before + '（偏离 ' + t[id].drift + '）\n';
    s += "    palette: '" + String(t[id].after).replace(/\\/g,'\\\\').replace(/'/g, "\\'") + "',\n";
    s += '  },\n';
  });
  s += '};\n';
  return s;
}

/* ============================================================
   八、导出
   ============================================================ */

/** 导出成 JSON（可交给美术，或存进 UE 项目当风格基线） */
function styleToJson(){
  const st = getStyle();
  return {
    version: 1,
    presetId: st.id, presetName: st.name, tagline: st.tagline, eraHint: st.eraHint,
    overrides: styleState.overrides,
    knobs: st.knobs,
    form: st.form, surface: st.surface, present: st.present,
    palette: st.palette,
    toneBands: Object.keys(STYLE_TONES).reduce((o,r)=>{
      const b = toneBand(r, st);
      o[r] = { label:b.label, area:b.area, note:b.note,
               sat:b.sat.map(Math.round), lig:b.lig.map(Math.round) };
      return o;
    }, {}),
    material: { map: st.matMap, params: matParams(st) },
    spec: st.spec,
    negative: st.negative,
    icon: st.icon,
    brief: styleBrief(st),
  };
}
