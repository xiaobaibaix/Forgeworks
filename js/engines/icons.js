/* Forgeworks · js/engines/icons.js */
/* ---------- 程序化图标引擎 ----------
   思路：不给 75 个物品逐个做贴图，而是用「颜色 × 类型」算法生成。
   - 颜色取自物品自身的 color 字段（已经在数据里了）
   - 形状按物品 type 区分（矿石/精矿/锭/零件/模块/宏构/副产物/流体）
   - 同类型内部用 ID 哈希做微扰动，避免看起来完全一样
   - 输出 SVG，矢量无损，可批量导出成图集
   ---------------------------------------- */

// FNV-1a 哈希，用于确定性的"随机"扰动
function hashStr(s){
  let h = 2166136261;
  for(let i=0;i<s.length;i++){ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

function hexToHsl(hex){
  let c = String(hex||'#888780').replace('#','');
  if(c.length===3) c = c.split('').map(x=>x+x).join('');
  if(c.length!==6) c = '888780';
  const r=parseInt(c.slice(0,2),16)/255, g=parseInt(c.slice(2,4),16)/255, b=parseInt(c.slice(4,6),16)/255;
  const mx=Math.max(r,g,b), mn=Math.min(r,g,b);
  let h=0, s=0, l=(mx+mn)/2;
  if(mx!==mn){
    const d = mx-mn;
    s = l>0.5 ? d/(2-mx-mn) : d/(mx+mn);
    if(mx===r) h = ((g-b)/d + (g<b?6:0));
    else if(mx===g) h = ((b-r)/d + 2);
    else h = ((r-g)/d + 4);
    h *= 60;
  }
  return {h, s:s*100, l:l*100};
}
function hslToHex(h,s,l){
  h = ((h%360)+360)%360; s = Math.max(0,Math.min(100,s))/100; l = Math.max(0,Math.min(100,l))/100;
  const k = n => (n + h/30) % 12;
  const a = s * Math.min(l, 1-l);
  const f = n => l - a * Math.max(-1, Math.min(k(n)-3, Math.min(9-k(n), 1)));
  const to = x => Math.round(255*Math.max(0,Math.min(1,x))).toString(16).padStart(2,'0');
  return '#'+to(f(0))+to(f(8))+to(f(4));
}
// 调整明度/饱和度得到同色系的深浅
function shade(hex, dl, ds=0){
  const {h,s,l} = hexToHsl(hex);
  return hslToHex(h, s+ds, l+dl);
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
  const b = item.color || '#888780';
  const dk = shade(b, -22);       // 暗部
  const lt = shade(b,  20);       // 亮部
  const mid = b;
  const seed = hashStr(item.id || 'x');
  // 取哈希的不同位做 -4..4 的偏移
  const j = n => ((seed >> ((n*4)%28)) % 9) - 4;
  const edge = 'stroke="rgba(0,0,0,.30)" stroke-width="1.6" stroke-linejoin="round"';
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

/** 图标 URL：有自定义图标就用自定义，否则用生成的
 *  生成的 SVG 会做 URL 编码，成本不低，所以按 id+类型+颜色 缓存。
 */
const _iconURLCache = new Map();
function iconURL(item){
  if(item.icon && item.icon.trim()) return item.icon.trim();
  const key = (item.id||'') + '|' + (item.visual || item.type || '') + '|' + (item.color||'');
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
