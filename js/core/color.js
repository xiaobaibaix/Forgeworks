/* Forgeworks · js/core/color.js
   ============================================================
   颜色工具（全局唯一定义）
   ------------------------------------------------------------
   图标引擎、风格引擎、体块预览都要做 HSL 变换，
   以前各自定义了一套（icons.js 的 hexToHsl / prompts.js 的 shadeHex），
   现在收敛到这里，避免多份实现导致颜色对不上。

   注意：必须在 engines/icons.js 之前加载。
   ============================================================ */

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

/** 调整明度/饱和度得到同色系的深浅 */
function shade(hex, dl, ds){
  ds = ds || 0;
  const {h,s,l} = hexToHsl(hex);
  return hslToHex(h, s+ds, l+dl);
}

/** 把 sat / lig 限制在 [min,max] 内，色相保留 —— 风格统一的核心操作 */
function clampSL(hex, satRange, ligRange){
  const {h,s,l} = hexToHsl(hex);
  const sMin = satRange ? satRange[0] : 0,   sMax = satRange ? satRange[1] : 100;
  const lMin = ligRange ? ligRange[0] : 0,   lMax = ligRange ? ligRange[1] : 100;
  const cs = Math.max(sMin, Math.min(sMax, s));
  const cl = Math.max(lMin, Math.min(lMax, l));
  return { hex: hslToHex(h, cs, cl), h, s, l, cs, cl,
           satDelta: cs - s, ligDelta: cl - l };
}

/** 两色混合，t=0 取 a，t=1 取 b */
function mixHex(a, b, t){
  const A = hexToHsl(a), B = hexToHsl(b);
  // 色相走最短弧
  let dh = ((B.h - A.h + 540) % 360) - 180;
  return hslToHex(A.h + dh*t, A.s + (B.s-A.s)*t, A.l + (B.l-A.l)*t);
}

/** 相对亮度（WCAG），用于判断文字该用黑还是白 */
function relLum(hex){
  let c = String(hex||'#888780').replace('#','');
  if(c.length===3) c = c.split('').map(x=>x+x).join('');
  const n = parseInt(c,16);
  const ch = v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
  return 0.2126*ch((n>>16)&0xff) + 0.7152*ch((n>>8)&0xff) + 0.0722*(n&0xff);
}
