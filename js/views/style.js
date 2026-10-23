/* Forgeworks · js/views/style.js
   ============================================================
   风格视图 —— 项目美术风格的控制面板
   ------------------------------------------------------------
   这一页是「风格」的唯一入口，改动立刻影响：
     - 所有资产的生成描述词
     - 3D 预览的材质与强调色
     - 物品图标的配色
     - 体块预览的配色
     - GLB 导出携带的风格元数据

   交互要点：
     滑块用 oninput 做「局部刷新」，不重建整页（否则拖到一半滑块失焦）。
   ============================================================ */

/** 预览用的代表性建筑（各分类挑一个，换风格能立刻看出差别） */
function stylePreviewMachines(){
  const cats = ['采集','冶炼','组装','化工'];
  return cats.map(c => (S.machines || []).find(m => m.cat === c)).filter(Boolean).slice(0, 3);
}
/** 预览用的代表性物品 */
function stylePreviewItems(){
  const types = ['raw','concentrate','ingot','part','module','fluid'];
  return types.map(t => (S.items || []).find(i => i.type === t)).filter(Boolean).slice(0, 6);
}

/** 一个小色块 */
function sw(hex, size, title){
  const s = size || 14;
  return `<span class="swatch" title="${title || hex}"
    style="background:${hex};width:${s}px;height:${s}px;
           box-shadow:inset 0 0 0 1px rgba(0,0,0,.14)"></span>`;
}

/* ============================================================
   各区块的 HTML
   ============================================================ */

/** 旋钮滑块 */
function styleKnobRows(st){
  return STYLE_KNOBS.map(function(k){
    const val = st.knobs[k.key];
    const base = (stylePreset().knobs && stylePreset().knobs[k.key] !== undefined)
      ? Number(stylePreset().knobs[k.key]) : k.def;
    const dirty = styleState.overrides[k.key] !== undefined;
    const disp = (k.unit === '%') ? (val > 0 ? '+' + val : String(val)) + k.unit
               : (k.unit === '×') ? val.toFixed(2) + k.unit
               : (k.unit === '') ? val.toFixed(2)
               : val + k.unit;
    return `<div style="margin-bottom:11px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">
        <span style="width:64px;font-size:12px">${k.label}</span>
        <input type="range" data-sknob="${k.key}"
               min="${k.min}" max="${k.max}" step="${k.step}" value="${val}"
               style="flex:1;padding:0">
        <span style="width:52px;text-align:right;font-family:var(--mono);font-size:11px"
              data-sknobval="${k.key}">${disp}</span>
        ${dirty ? `<span class="pill" style="font-size:10px">改过</span>` : ''}
      </div>
      <div style="font-size:10.5px;color:var(--text-3);margin-left:72px;line-height:1.5">${k.hint}</div>
    </div>`;
  }).join('');
}

/** 色板（含校正前后对比） */
function stylePaletteHTML(st){
  const rows = [
    ['structure','结构/基座'], ['metal','主体金属'], ['metalDark','暗部金属'],
    ['metalLite','亮部金属'], ['glass','玻璃'], ['glow','发光'], ['hazard','警示'],
  ];
  const body = rows.map(function(r){
    const role = r[0], label = r[1];
    const after = st.palette[role], before = st.palette.raw[role];
    const f = fitColor(before, role, st);
    const band = toneBand(role, st);
    const changed = f.changed;
    return `<tr>
      <td style="white-space:nowrap">${sw(after, 18)} <span style="margin-left:6px">${label}</span></td>
      <td style="font-family:var(--mono);font-size:11px">${after}</td>
      <td style="font-family:var(--mono);font-size:11px;color:${changed ? 'var(--amber)' : 'var(--text-3)'}">
        ${before}${changed ? ' → ' + after : ''}</td>
      <td style="font-size:11px;color:var(--text-3);white-space:nowrap">
        S ${Math.round(band.sat[0])}~${Math.round(band.sat[1])}%
        · L ${Math.round(band.lig[0])}~${Math.round(band.lig[1])}%</td>
      <td style="font-size:11px;color:var(--text-3)">${band.note}</td>
    </tr>`;
  }).join('');

  const accents = Object.keys(st.palette.accent).map(function(cat){
    const after = st.palette.accent[cat], before = st.palette.accentRaw[cat];
    const drift = colorDrift(before, 'accent', st);
    return `<div style="display:flex;align-items:center;gap:5px;font-size:11px">
      ${sw(after, 16)}
      <span>${cat}</span>
      <span style="font-family:var(--mono);color:var(--text-3)">${after}</span>
      ${drift.severity !== 'ok'
        ? `<span style="color:var(--amber);font-size:10px" title="原色 ${before}">偏${Math.round(drift.drift)}</span>`
        : ''}
    </div>`;
  }).join('');

  return `<table><thead><tr>
      <th style="width:150px">角色</th><th style="width:78px">采用</th>
      <th style="width:150px">基线原色</th><th style="width:150px">允许区间</th><th>说明</th>
    </tr></thead><tbody>${body}</tbody></table>
    <div style="margin-top:12px">
      <div style="font-size:11.5px;color:var(--text-2);margin-bottom:6px">
        <strong>分类强调色</strong>（色相区分功能，饱和度/明度已统一到强调色带内）</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px">${accents}</div>
    </div>`;
}

/** 实时预览：建筑体块 + 物品图标 + 描述词片段 */
function stylePreviewHTML(st){
  const ms = stylePreviewMachines();
  const its = stylePreviewItems();

  const massing = ms.map(function(m){
    return `<div style="text-align:center">
      ${isoPreview(m, 0, 132)}
      <div style="font-size:11px;margin-top:2px">${m.name}</div>
      <div style="font-size:10px;color:var(--text-3)">${m.cat} · ${accentFor(m.cat, st)}</div>
    </div>`;
  }).join('');

  const icons = its.map(function(it){
    const f = itemFitColor(it, st);
    return `<div style="text-align:center">
      ${iconHTML(it, 40)}
      <div style="font-size:10.5px;margin-top:2px">${it.name}</div>
      <div style="font-size:9.5px;color:var(--text-3);font-family:var(--mono)">${f.hex}</div>
    </div>`;
  }).join('');

  const sample = ms.length ? machinePrompt(ms[0]) : '';

  return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div>
        <div style="font-size:11.5px;color:var(--text-2);margin-bottom:6px">
          <strong>建筑体块预览</strong>（配色跟随风格）</div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">${massing}</div>
      </div>
      <div>
        <div style="font-size:11.5px;color:var(--text-2);margin-bottom:6px">
          <strong>物品图标</strong>（与描述词同一套色）</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap">${icons}</div>
      </div>
    </div>
    <div style="margin-top:14px">
      <div style="font-size:11.5px;color:var(--text-2);margin-bottom:6px">
        <strong>描述词样例</strong>（${ms.length ? ms[0].name : '—'}，换风格会自动改写）</div>
      <pre style="margin:0;padding:10px 12px;background:var(--panel-2);
           border:1px solid var(--border);border-radius:8px;font-size:11px;
           line-height:1.65;white-space:pre-wrap;max-height:220px;overflow:auto"
      >${sample.replace(/</g,'&lt;')}</pre>
    </div>`;
}

/** 一致性检查 */
function styleCheckHTML(){
  const r = styleCheck();
  if(!r.total){
    return `<div class="issue ok"><span class="ic">✓</span><div>
      全部配色都在「${r.styleName}」的允许区间内，成套感没问题。</div></div>`;
  }
  const sevColor = { high:'var(--red)', mid:'var(--amber)', low:'var(--text-3)' };
  const sevLabel = { high:'明显偏离', mid:'轻微偏离', low:'可接受' };
  const rows = r.issues.slice(0, 40).map(function(i){
    return `<tr>
      <td>${sw(i.hex, 14)}</td>
      <td><span style="color:${sevColor[i.severity]}">${sevLabel[i.severity]}</span></td>
      <td>${i.where}</td>
      <td style="font-size:11px;color:var(--text-3)">${i.kind} · ${i.role}</td>
      <td style="font-family:var(--mono);font-size:11px">
        ${i.hex} <span style="color:var(--text-3)">→</span> ${i.fit}</td>
      <td style="font-size:11px;color:var(--text-3);white-space:nowrap">
        S ${i.sat}→${i.satAfter} · L ${i.lig}→${i.ligAfter}</td>
    </tr>`;
  }).join('');

  const KIND_META = {
    '建筑配色':   { color:'var(--red)',
      hint:'MACHINE_BRIEFS 里手写的色值。描述词里已自动换成校正色，但这些源数据建议改掉。' },
    '物品主色':   { color:'var(--amber)',
      hint:'图标与模型会自动校正后使用。若某物品颜色按设定就该是原色，可忽略。' },
    '兜底预览色': { color:'var(--text-3)',
      hint:'正常渲染走风格色板，此值仅在风格模块缺失时生效，一般无需处理。' },
    '兜底体块色': { color:'var(--text-3)',
      hint:'同上。' },
  };
  const kindCards = Object.keys(r.byKind).map(function(k){
    const m = KIND_META[k] || { color:'var(--text-3)', hint:'' };
    const d = r.byKind[k];
    return `<div style="padding:9px 11px;border:1px solid var(--border);border-radius:8px;
                background:var(--panel-2)">
      <div style="display:flex;align-items:baseline;gap:6px">
        <strong style="font-size:12px">${k}</strong>
        <span style="font-size:16px;font-family:var(--mono);color:${m.color}">${d.total}</span>
        ${d.high ? `<span class="pill" style="font-size:10px;color:var(--red)">明显 ${d.high}</span>` : ''}
      </div>
      <div style="font-size:10.5px;color:var(--text-3);line-height:1.5;margin-top:3px">${m.hint}</div>
    </div>`;
  }).join('');

  return `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
             gap:8px;margin-bottom:12px">${kindCards}</div>
    <div style="font-size:11px;color:var(--text-3);margin-bottom:8px;line-height:1.6">
      共 <strong>${r.total}</strong> 处偏离（明显 ${r.bySeverity.high} / 轻微 ${r.bySeverity.mid} / 可接受 ${r.bySeverity.low}）。
      描述词、图标、3D 预览<strong>都已自动使用「→」右侧的校正色</strong>，
      所以生成结果本身是统一的；这里列出来是为了让你知道<strong>哪些源数据值得改</strong>。
    </div>
    <div class="tbl-wrap scroll-x"><table><thead><tr>
      <th style="width:30px"></th><th style="width:76px">程度</th><th>位置</th>
      <th style="width:130px">类型</th><th style="width:150px">原色 → 采用</th>
      <th style="width:130px">S / L 变化</th>
    </tr></thead><tbody>${rows}</tbody></table></div>
    ${r.total > 40 ? '<div style="font-size:11px;color:var(--text-3);margin-top:6px">仅显示偏离最大的 40 条。</div>' : ''}`;
}

/* ============================================================
   主渲染
   ============================================================ */

function renderStyle(){
  const v = document.getElementById('view');
  const st = getStyle();

  v.innerHTML = `
    <div class="card">
      <h3>项目风格</h3>
      <p class="hint">
        风格是项目美术的<strong>单一来源</strong>：改这里的设置，描述词、3D 预览材质、
        物品图标、体块预览、GLB 元数据会<strong>全部跟着变</strong>。
        引擎会把每个颜色校正进「角色带」内 —— <strong>色相负责区分功能，饱和度/明度负责统一风格</strong>。
      </p>
      <div style="font-size:12px;color:var(--text-2);margin-top:8px">
        <strong>${st.name}</strong> · ${st.tagline}
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
        <button class="primary" id="styExportJson">导出风格 JSON</button>
        <button id="styCopyBrief">复制完整风格描述</button>
        <button id="styFixPalette">修正建筑配色（生成代码）</button>
        <button id="styResetKnobs" ${st.isDirty ? '' : 'disabled'}>恢复默认值</button>
      </div>
      <div id="styFixOut"></div>
    </div>

    <div class="card">
      <h3>微调</h3>
      <p class="hint">基线是起点，这里的覆盖值是"你的项目"，单独保存，不影响内容数据。</p>
      <div id="styKnobs" style="margin-top:12px">${styleKnobRows(st)}</div>
    </div>

    <div class="card">
      <h3>色板</h3>
      <p class="hint">「基线原色 → 采用」列出了引擎做了多少校正。校正量大说明该色本来就不在这套风格里。</p>
      <div id="styPalette" style="margin-top:10px">${stylePaletteHTML(st)}</div>
    </div>

    <div class="card">
      <h3>实时预览</h3>
      <div id="styPreview" style="margin-top:6px">${stylePreviewHTML(st)}</div>
    </div>

    <div class="card">
      <h3>风格一致性检查</h3>
      <p class="hint">扫描全部建筑配色、物品主色、预览配色，找出破坏成套感的颜色。</p>
      <div id="styCheck" style="margin-top:10px">${styleCheckHTML()}</div>
    </div>
  `;

  /* ---------- 绑定：滑块 ----------
     oninput 只刷新「预览/色板/检查」三块 + 数值标签，
     不重建整页，否则拖到一半滑块会失焦。 */
  v.querySelectorAll('[data-sknob]').forEach(function(el){
    el.oninput = function(){
      setKnob(el.dataset.sknob, el.value);
      refreshStyleLive();
    };
    el.onchange = function(){ render(); };   // 松手后完整重渲染（刷新"改过"标记等）
  });

  /* ---------- 绑定：导出 ---------- */
  const expBtn = document.getElementById('styExportJson');
  if(expBtn) expBtn.onclick = function(){
    download('forgeworks_style.json', JSON.stringify(styleToJson(), null, 2), 'application/json');
    toast('已导出 forgeworks_style.json');
  };
  const copyBtn = document.getElementById('styCopyBrief');
  if(copyBtn) copyBtn.onclick = function(){
    copyText(styleBrief(getStyle(), { full:true }));
  };
  const resetBtn = document.getElementById('styResetKnobs');
  if(resetBtn) resetBtn.onclick = function(){
    resetKnobs();
    render();
    toast('已恢复默认值');
  };

  /* ---------- 绑定：配色修正（诊断 → 行动） ---------- */
  const fixBtn = document.getElementById('styFixPalette');
  if(fixBtn) fixBtn.onclick = function(){
    const snippet = styleFixSnippet();
    const box = document.getElementById('styFixOut');
    if(box){
      const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      const n = Object.keys(stylePaletteFixTable()).length;
      box.innerHTML = `
        <div class="issue ${n ? '' : 'ok'}" style="margin-top:12px">
          <span class="ic">${n ? '✎' : '✓'}</span>
          <div>${n ? `已生成 <strong>${n}</strong> 个建筑的配色修正，并复制到剪贴板。
                粘贴到 <code>js/data/prompts.js</code> 的 <code>MACHINE_BRIEFS</code> 即可固化。`
              : `当前风格下所有建筑配色都合规，无需修正。`}</div>
        </div>
        <pre style="margin:10px 0 0;padding:10px 12px;background:var(--panel-2);
             border:1px solid var(--border);border-radius:8px;font-size:11px;
             line-height:1.6;max-height:260px;overflow:auto;white-space:pre"
        >${esc(snippet)}</pre>`;
    }
    copyText(snippet);
  };
}

/** 局部刷新（滑块拖动时调用） */
function refreshStyleLive(){
  const st = getStyle();
  const set = (id, html)=>{ const el = document.getElementById(id); if(el) el.innerHTML = html; };
  set('styPalette', stylePaletteHTML(st));
  set('styPreview',  stylePreviewHTML(st));
  set('styCheck',    styleCheckHTML());
  // 数值标签
  STYLE_KNOBS.forEach(function(k){
    const el = document.querySelector('[data-sknobval="' + k.key + '"]');
    if(!el) return;
    const val = st.knobs[k.key];
    el.textContent = (k.unit === '%') ? (val > 0 ? '+' + val : String(val)) + k.unit
                   : (k.unit === '×') ? val.toFixed(2) + k.unit
                   : (k.unit === '') ? val.toFixed(2)
                   : val + k.unit;
  });
}
