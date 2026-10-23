/* Forgeworks · js/engines/icons.js */
/* ---------- 程序化图标引擎 ----------
   思路：不给 75 个物品逐个做贴图，而是用「颜色 × 类型」算法生成。
   - 颜色取自物品自身的 color 字段（已经在数据里了）
   - 形状按物品 type 区分（矿石/精矿/锭/零件/模块/宏构/副产物/流体）
   - 同类型内部用 ID 哈希做微扰动，避免看起来完全一样
   - 输出 SVG，矢量无损，可批量导出成图集

   颜色工具（hexToHsl / hslToHex / shade / clampSL / mixHex）统一在
   js/core/color.js —— 风格引擎也要用同一套，多份实现会导致颜色对不上。
   ---------------------------------------- */

// FNV-1a 哈希，用于确定性的"随机"扰动
function hashStr(s){
  let h = 2166136261;
  for(let i=0;i<s.length;i++){ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}


/** 对 SVG path 里的所有数字做确定性微扰，让同类物品不至于完全一样 */
function jitterPath(d, seed, amp){
  let i = 0;
  return d.replace(/-?\d+(?:\.\d+)?/g, (m)=>{
    const v = parseFloat(m);
    const off = ((seed >>> ((i*5) % 27)) % (amp*2+1)) - amp;
    i++;
    // 保留一位小数
    return String(Math.round((v + off) * 10) / 10);
  });
}

/**
 * 生成图标内部的 SVG 图形（64×64 坐标系）
 */
function iconInner(item){
  // ── 基色走风格校正 ─────────────────────────────
  // 以前直接用 item.color，结果图标跟描述词、3D 预览各用一套色。
  // 现在统一从风格引擎取，保证「看到的图标」=「让 AI 生成的模型」。
  let b = item.color || '#888780';
  let edgeA = 0.30, edgeW = 1.6;
  if(typeof itemFitColor === 'function'){
    const st = getStyle();
    b = itemFitColor(item, st).hex;
    const ic = st.icon || {};
    // 预设自己的图标偏好（饱和/明度/描边），注意 satBoost 已在 fitColor 里算过，不重复叠加
    const h0 = hexToHsl(b);
    b = hslToHex(h0.h, h0.s * (ic.satScale || 1), h0.l * (ic.ligScale || 1));
    edgeA = ic.stroke !== undefined ? ic.stroke : 0.30;
    edgeW = Math.max(0.9, Math.min(2.6, (ic.stroke || 0.22) * 7.3));
  }
  const dk = shade(b, -22);       // 暗部
  const lt = shade(b,  20);       // 亮部
  const mid = b;
  const seed = hashStr(item.id || 'x');
  // 取哈希的不同位做 -4..4 的偏移
  const j = n => ((seed >> ((n*4)%28)) % 9) - 4;
  const edge = `stroke="rgba(0,0,0,${edgeA.toFixed(2)})" stroke-width="${edgeW.toFixed(1)}" stroke-linejoin="round"`;
  // visual 字段可以覆盖图标形态（例如卤水：type=raw 用于物料平衡，但视觉是液体）
  const T = item.visual || item.type;

  switch(T){
    case 'raw': {                   // 不规则矿石块（4 套轮廓 + 逐项微扰）
      const variant = seed % 4;
      const J = (d)=>jitterPath(d, seed, 2);   // ±2px 扰动，形状可辨但各不相同
      if(variant === 0){
        return `<path d="${J('M29,7 L39,21 L36,42 L46,49 L20,52 L23,24 Z')}" fill="${mid}" ${edge}/>
                <path d="M29,7 L39,21 L32,30 L23,24 Z" fill="${lt}" opacity=".75"/>
                <path d="M32,30 L36,42 L46,49 L34,48 Z" fill="${dk}" opacity=".55"/>`;
      }
      if(variant === 1){
        return `<path d="${J('M7,39 L25,25 L41,27 L57,40 L47,52 L15,52 Z')}" fill="${mid}" ${edge}/>
                <path d="M25,25 L41,27 L43,38 L23,37 Z" fill="${lt}" opacity=".70"/>
                <path d="M15,44 L26,41 L30,51 L16,51 Z" fill="${dk}" opacity=".55"/>`;
      }
      if(variant === 2){
        return `<path d="${J('M9,51 L17,30 L27,39 L34,13 L44,31 L55,25 L53,51 Z')}" fill="${mid}" ${edge}/>
                <path d="M34,13 L44,31 L36,34 L28,26 Z" fill="${lt}" opacity=".72"/>
                <path d="M17,30 L27,39 L24,50 L14,50 Z" fill="${dk}" opacity=".50"/>`;
      }
      return `<path d="${J('M8,48 L14,32 L27,27 L36,35 L30,49 Z')}" fill="${mid}" ${edge}/>
              <path d="${J('M34,50 L39,37 L50,33 L58,41 L54,52 Z')}" fill="${shade(b,-8)}" ${edge}/>
              <path d="M14,32 L27,27 L30,36 L18,38 Z" fill="${lt}" opacity=".70"/>
              <path d="M39,37 L50,33 L52,43 L40,45 Z" fill="${lt}" opacity=".50"/>`;
    }
    case 'concentrate': {           // 精矿堆 + 颗粒
      return `<path d="M9,50 Q13,31 27,27 Q34,24 39,29 Q51,33 55,50 Z" fill="${mid}" ${edge}/>
              <path d="M27,27 Q34,24 39,29 Q36,36 27,34 Z" fill="${lt}" opacity=".7"/>
              <circle cx="25" cy="41" r="3" fill="${lt}" opacity=".85"/>
              <circle cx="36" cy="45" r="2.6" fill="${lt}" opacity=".6"/>
              <circle cx="44" cy="39" r="2.2" fill="${dk}" opacity=".55"/>`;
    }
    case 'ingot': {                 // 梯形锭（带顶面）
      return `<path d="M17,45 L21,29 L43,29 L47,45 Z" fill="${mid}" ${edge}/>
              <path d="M21,29 L25,20 L39,20 L43,29 Z" fill="${lt}" ${edge}/>
              <path d="M25,20 L23,29 M39,20 L41,29" stroke="${dk}" stroke-width="1.3" opacity=".45"/>
              <path d="M21,36 L43,36" stroke="${dk}" stroke-width="1" opacity=".3"/>`;
    }
    case 'part': {                  // 齿轮（机械零件）
      let teeth = '';
      for(let i=0;i<8;i++){
        teeth += `<rect x="29" y="7" width="6" height="11" rx="1.6" fill="${mid}" transform="rotate(${i*45} 32 32)"/>`;
      }
      return `${teeth}
              <circle cx="32" cy="32" r="17" fill="${mid}" ${edge}/>
              <circle cx="32" cy="32" r="9" fill="${dk}" opacity=".85"/>
              <circle cx="32" cy="32" r="4" fill="${lt}"/>`;
    }
    case 'material': {              // 材料：堆叠板材/砖块
      return `<path d="M10,44 L32,33 L54,44 L32,55 Z" fill="${dk}" ${edge}/>
              <path d="M10,35 L32,24 L54,35 L32,46 Z" fill="${mid}" ${edge}/>
              <path d="M10,26 L32,15 L54,26 L32,37 Z" fill="${lt}" ${edge}/>
              <path d="M32,15 L54,26 L32,37 L10,26 Z" fill="${shade(b,10)}" opacity=".55"/>`;
    }
    case 'module': {                // 电路基板
      return `<rect x="11" y="11" width="42" height="42" rx="7" fill="${mid}" ${edge}/>
              <rect x="18" y="18" width="13" height="13" rx="2" fill="${lt}" opacity=".9"/>
              <rect x="35" y="18" width="11" height="5" rx="1.5" fill="${dk}" opacity=".7"/>
              <rect x="35" y="27" width="11" height="5" rx="1.5" fill="${dk}" opacity=".7"/>
              <rect x="18" y="36" width="28" height="9" rx="2" fill="${dk}" opacity=".45"/>
              <circle cx="22" cy="24" r="2" fill="${dk}" opacity=".8"/>`;
    }
    case 'mega': {                  // 轨道结构：环 + 节点
      // 4 个轨道节点，读起来像空间站而不是靶心
      const nodes = [0,90,180,270].map(a=>{
        const rad = a*Math.PI/180;
        const cx = 32 + Math.cos(rad)*21, cy = 32 + Math.sin(rad)*21;
        return `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="5" fill="${lt}" ${edge}/>`;
      }).join('');
      return `<circle cx="32" cy="32" r="21" fill="none" stroke="${mid}" stroke-width="5"/>
              <circle cx="32" cy="32" r="21" fill="none" stroke="${dk}" stroke-width="1.2" opacity=".5"/>
              <path d="M32,17 L32,47 M17,32 L47,32" stroke="${shade(b,-12)}" stroke-width="2" opacity=".55"/>
              ${nodes}
              <circle cx="32" cy="32" r="7" fill="${mid}" ${edge}/>
              <circle cx="32" cy="32" r="3" fill="${lt}"/>`;
    }
    case 'fluid': {                 // 液滴
      return `<path d="M32,11 C32,11 48,30 48,39.5 A16,16 0 0,1 16,39.5 C16,30 32,11 32,11 Z" fill="${mid}" ${edge}/>
              <ellipse cx="26" cy="38" rx="4.2" ry="6.2" fill="${lt}" opacity=".55"/>
              <path d="M40,34 A10,10 0 0,1 38,44" stroke="${dk}" stroke-width="1.6" opacity=".35" fill="none"/>`;
    }
    case 'byproduct': {             // 副产物：碎石堆
      return `<path d="M14,49 L19,35 L31,32 L39,40 L34,50 Z" fill="${mid}" ${edge}/>
              <path d="M36,50 L41,40 L52,38 L56,47 L50,52 Z" fill="${shade(b,-10)}" ${edge}/>
              <path d="M19,35 L31,32 L33,41 L21,42 Z" fill="${lt}" opacity=".6"/>
              <circle cx="46" cy="45" r="2.2" fill="${dk}" opacity=".6"/>`;
    }
    default: {                      // 兜底：立方体
      return `<path d="M32,10 L52,21 L52,43 L32,54 L12,43 L12,21 Z" fill="${mid}" ${edge}/>
              <path d="M32,10 L52,21 L32,32 L12,21 Z" fill="${lt}" opacity=".8"/>`;
    }
  }
}

/** 生成完整 SVG 字符串；size 只影响属性，viewBox 保持 64 */
function makeIconSVG(item, size){
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${size||64}" height="${size||64}">`+
         iconInner(item)+`</svg>`;
}

/** 当前风格的缓存标识（调旋钮会变，图标必须跟着重画） */
function styleCacheTag(){
  if(typeof styleState === 'undefined') return '';
  return JSON.stringify(styleState.overrides || {});
}

/** 图标 URL：有自定义图标就用自定义，否则用生成的
 *  生成的 SVG 会做 URL 编码，成本不低，所以按 id+类型+颜色+风格 缓存。
 *  —— 缓存键必须带风格，否则换了风格图标还是旧的。
 */
const _iconURLCache = new Map();
function iconURL(item){
  if(item.icon && item.icon.trim()) return item.icon.trim();
  const key = styleCacheTag() + '|' + (item.id||'') + '|'
            + (item.visual || item.type || '') + '|' + (item.color||'');
  const hit = _iconURLCache.get(key);
  if(hit) return hit;
  const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(makeIconSVG(item, 64));
  _iconURLCache.set(key, url);
  return url;
}
function clearIconCache(){ _iconURLCache.clear(); }

/** 图标 img 标签 */
function iconHTML(item, size){
  const s = size || 20;
  return `<img src="${iconURL(item)}" width="${s}" height="${s}" alt="" `+
         `style="vertical-align:middle;border-radius:4px;object-fit:contain">`;
}

/* ---------- 元素图标：周期表元素牌 ---------- */

function xmlEscape(text){
  return String(text === undefined || text === null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** 元素牌内部图形（64×64）：圆角方块 + 符号 + 名称 + 等级角标 */
function elementIconInner(el){
  let b = (el && el.color) || '#888780';
  if(typeof fitColor === 'function' && typeof getStyle === 'function'){
    const st = getStyle();
    b = fitColor(b, 'accent', st).hex;
    const ic = st.icon || {};
    const h0 = hexToHsl(b);
    b = hslToHex(h0.h, h0.s * (ic.satScale || 1), h0.l * (ic.ligScale || 1));
  }
  const lt = shade(b, 20), dk = shade(b, -22);
  const fg = relLum(b) > 0.45 ? '#1b1a18' : '#ffffff';
  const gid = 'elg' + hashStr(String((el && el.id) || (el && el.symbol) || 'x'));

  const sym = String((el && el.symbol) || (el && el.id) || '?');
  const symSize = sym.length <= 2 ? 24 : sym.length === 3 ? 18 : 14;

  let name = String((el && el.name) || '');
  if(name.length > 8) name = name.slice(0, 7) + '…';
  const nameSize = name.length <= 4 ? 8 : name.length <= 6 ? 7 : 6.2;

  const tier = (el && el.tier !== undefined && el.tier !== null && el.tier !== '')
    ? String(el.tier) : '';

  return `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">`
       + `<stop offset="0" stop-color="${lt}"/><stop offset="1" stop-color="${dk}"/>`
       + `</linearGradient></defs>`
       + `<rect x="2" y="2" width="60" height="60" rx="9" fill="url(#${gid})" `
       + `stroke="rgba(0,0,0,.28)" stroke-width="1.2"/>`
       + `<rect x="3.6" y="3.6" width="56.8" height="56.8" rx="7.6" fill="none" `
       + `stroke="${fg}" stroke-opacity=".16"/>`
       + `<text x="32" y="30" text-anchor="middle" dominant-baseline="central" `
       + `font-family="ui-sans-serif,system-ui,sans-serif" font-weight="700" `
       + `font-size="${symSize}" fill="${fg}">${xmlEscape(sym)}</text>`
       + (name ? `<text x="32" y="53" text-anchor="middle" fill="${fg}" fill-opacity=".85" `
               + `font-family="ui-sans-serif,system-ui,sans-serif" font-size="${nameSize}">`
               + `${xmlEscape(name)}</text>` : '')
       + (tier ? `<text x="56" y="11" text-anchor="end" fill="${fg}" fill-opacity=".75" `
               + `font-family="ui-sans-serif,system-ui,sans-serif" font-size="7.5">`
               + `T${xmlEscape(tier)}</text>` : '');
}

function makeElementIconSVG(el, size){
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" `
       + `width="${size || 64}" height="${size || 64}">${elementIconInner(el)}</svg>`;
}

/** 元素图标 URL：自定义优先，否则生成并缓存（缓存键含风格，换风格自动失效） */
function elementIconURL(el){
  const custom = (el && el.icon) ? String(el.icon).trim() : '';
  if(custom) return custom;
  const key = 'el|' + styleCacheTag() + '|' + ((el && el.id) || '') + '|'
            + ((el && el.symbol) || '') + '|' + ((el && el.name) || '') + '|'
            + (el && el.tier !== undefined && el.tier !== null ? el.tier : '') + '|'
            + ((el && el.color) || '');
  const hit = _iconURLCache.get(key);
  if(hit) return hit;
  const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(makeElementIconSVG(el, 64));
  _iconURLCache.set(key, url);
  return url;
}

function elementIconHTML(el, size){
  const s = size || 20;
  return `<img src="${elementIconURL(el)}" width="${s}" height="${s}" alt="" `+
         `style="vertical-align:middle;border-radius:4px;object-fit:contain">`;
}

// 模型状态的中文标签
const MODEL_LABELS = {
  none:{t:'无需模型', bg:'var(--bg)', fg:'var(--text-3)'},
  primitive:{t:'基础几何体', bg:'var(--blue-soft)', fg:'#185fa5'},
  needed:{t:'需专门建模', bg:'var(--amber-soft)', fg:'#854f0b'},
  done:{t:'模型已完成', bg:'var(--accent-soft)', fg:'#0f6e56'},
};
// 按类型给出建模建议
function modelHint(item){
  const map = {
    raw:        '用 UE Sphere/Cube 加轻微缩放与旋转即可，矿石块不需要精细拓扑',
    concentrate:'用 Cube 压扁 + 顶点扰动，或直接用一个低模土堆',
    ingot:      '用 Cube 缩放成梯形（或 3 段挤出），材质做金属高光即可',
    part:       '需要中模：齿轮可用圆柱 + 布尔切齿，或用现成齿轮生成器',
    module:     '需要中模：立方体倒角 + 表面电路贴花（用贴图代替建模细节）',
    mega:       '需要高模/独立资产：宏大结构，建议单独做 LOD 与远景版本',
    byproduct:  '用 2~3 个 Cube 随机拼成一个碎石堆',
    fluid:      '无需网格：液体用材质 + 容器表现，UI 里只需图标',
  };
  return map[item.type] || '按需处理';
}
