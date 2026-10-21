/* Forgeworks · js/engines/material-textures.js
   ============================================================
   材质贴图（AI 生成的细节图 → 中性灰度 → 运行时按风格色板着色）

   为什么转灰度：
     贴图如果自带颜色，会盖掉风格引擎的色板，换风格就失效。
     这里把 AI 图压成「中性明度细节」，material.color 继续管色相，
     于是同一张图能被所有风格复用。
   ============================================================ */

const FW_TEX = {
  styleId: null,
  catalog: null,
  items: {},          // materialKey -> { map, roughness, normal }
  errors: {},
  loading: {},
  loadingCatalog: null,
  waiters: [],
  listeners: [],
};

const FW_TEX_COLOR_SIZE = 512;
const FW_TEX_ROUGH_SIZE = 256;
const FW_TEX_NORMAL_SIZE = 256;

function fwTextureFor(key){
  const entry = key && FW_TEX.items[key];
  return entry && entry.map ? entry.map : null;
}

function fwRoughnessFor(key){
  const entry = key && FW_TEX.items[key];
  return entry && entry.roughness ? entry.roughness : null;
}

function fwNormalFor(key){
  const entry = key && FW_TEX.items[key];
  return entry && entry.normal ? entry.normal : null;
}

function fwOnTexturesChanged(fn){
  FW_TEX.listeners.push(fn);
  return function(){
    FW_TEX.listeners = FW_TEX.listeners.filter(function(item){ return item !== fn; });
  };
}

function fwNotifyTextures(key){
  FW_TEX.listeners.forEach(function(fn){
    try{ fn(key); }catch(_){ /* 单个订阅者出错不影响其他视图 */ }
  });
}

function fwDisposeTextures(){
  Object.keys(FW_TEX.items).forEach(function(key){
    const entry = FW_TEX.items[key];
    if(entry.map) entry.map.dispose();
    if(entry.roughness) entry.roughness.dispose();
    if(entry.normal) entry.normal.dispose();
  });
  FW_TEX.items = {};
  FW_TEX.errors = {};
}

/** 去饱和 + 亮度归一：AI 图只保留细节起伏，颜色交给风格色板 */
function fwNeutralCanvas(image, size, mean, contrast){
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(image, 0, 0, size, size);
  const frame = ctx.getImageData(0, 0, size, size);
  const data = frame.data;
  const target = Math.round(mean * 255);
  for(let i = 0; i < data.length; i += 4){
    const lum = 0.2126*data[i] + 0.7152*data[i+1] + 0.0722*data[i+2];
    const value = Math.max(0, Math.min(255, target + (lum - 128) * contrast));
    data[i] = data[i+1] = data[i+2] = value;
    data[i+3] = 255;
  }
  ctx.putImageData(frame, 0, 0);
  return canvas;
}

/** 用同一份明度图派生粗糙度：亮处略光滑，暗处略粗糙 */
function fwRoughnessCanvas(colorCanvas, size){
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(colorCanvas, 0, 0, size, size);
  const frame = ctx.getImageData(0, 0, size, size);
  const data = frame.data;
  for(let i = 0; i < data.length; i += 4){
    const lum = data[i];
    const value = Math.max(150, Math.min(255, 236 + (128 - lum) * 0.35));
    data[i] = data[i+1] = data[i+2] = value;
    data[i+3] = 255;
  }
  ctx.putImageData(frame, 0, 0);
  return canvas;
}

/** 由明度派生切线空间法线贴图：AI 细节在侧光下呈现起伏 */
function fwNormalCanvas(colorCanvas, size, strength){
  const source = document.createElement('canvas');
  source.width = size;
  source.height = size;
  const sctx = source.getContext('2d', { willReadFrequently: true });
  sctx.drawImage(colorCanvas, 0, 0, size, size);
  const pixels = sctx.getImageData(0, 0, size, size).data;
  const height = new Float32Array(size * size);
  for(let i = 0; i < height.length; i++) height[i] = pixels[i * 4] / 255;

  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const frame = ctx.createImageData(size, size);
  const data = frame.data;
  const k = strength || 2.2;
  for(let y = 0; y < size; y++){
    const up = ((y - 1 + size) % size) * size;
    const down = ((y + 1) % size) * size;
    const row = y * size;
    for(let x = 0; x < size; x++){
      const left = height[row + ((x - 1 + size) % size)];
      const right = height[row + ((x + 1) % size)];
      const dx = (right - left) * k;
      const dy = (height[down + x] - height[up + x]) * k;
      const len = Math.sqrt(dx*dx + dy*dy + 1);
      const i = (row + x) * 4;
      data[i]     = Math.round((-dx / len * 0.5 + 0.5) * 255);
      data[i + 1] = Math.round(( dy / len * 0.5 + 0.5) * 255);
      data[i + 2] = Math.round(( 1 / len * 0.5 + 0.5) * 255);
      data[i + 3] = 255;
    }
  }
  ctx.putImageData(frame, 0, 0);
  return canvas;
}

function fwMakeTexture(canvas, linear){
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.anisotropy = 4;
  texture.userData.mimeType = 'image/jpeg';
  if(!linear) texture.encoding = THREE.sRGBEncoding;
  texture.needsUpdate = true;
  return texture;
}

function fwTextureUrl(styleId, key, item){
  const version = item.sha1 || item.mtime || '';
  return '/api/materials/texture/file?style=' + encodeURIComponent(styleId) +
         '&key=' + encodeURIComponent(key) + '&v=' + encodeURIComponent(version);
}

function fwLoadOne(styleId, key, item){
  if(FW_TEX.loading[key]) return FW_TEX.loading[key];
  const promise = new Promise(function(resolve){
    const image = new Image();
    image.onload = function(){
      try{
        const colorCanvas = fwNeutralCanvas(image, FW_TEX_COLOR_SIZE, 0.86, 0.55);
        const roughCanvas = fwRoughnessCanvas(colorCanvas, FW_TEX_ROUGH_SIZE);
        const normalCanvas = fwNormalCanvas(colorCanvas, FW_TEX_NORMAL_SIZE, 2.2);
        const map = fwMakeTexture(colorCanvas, false);
        const roughness = fwMakeTexture(roughCanvas, true);
        const normal = fwMakeTexture(normalCanvas, true);
        map.name = key + '_albedo';
        roughness.name = key + '_rough';
        normal.name = key + '_normal';
        if(FW_TEX.items[key]){
          if(FW_TEX.items[key].map) FW_TEX.items[key].map.dispose();
          if(FW_TEX.items[key].roughness) FW_TEX.items[key].roughness.dispose();
          if(FW_TEX.items[key].normal) FW_TEX.items[key].normal.dispose();
        }
        FW_TEX.items[key] = { map: map, roughness: roughness, normal: normal };
        delete FW_TEX.errors[key];
      }catch(error){
        FW_TEX.errors[key] = error && error.message || '贴图处理失败';
      }
      delete FW_TEX.loading[key];
      fwNotifyTextures(key);
      resolve();
    };
    image.onerror = function(){
      FW_TEX.errors[key] = '贴图加载失败';
      delete FW_TEX.loading[key];
      fwNotifyTextures(key);
      resolve();
    };
    image.src = fwTextureUrl(styleId, key, item);
  });
  FW_TEX.loading[key] = promise;
  return promise;
}

/** 拉取当前风格的贴图目录并装载到 THREE。离线/未绑定项目时静默降级为空。 */
async function fwReloadTextures(force){
  const styleId = (typeof currentStyleId === 'function' && currentStyleId()) || 'industrial';
  if(!force && FW_TEX.styleId === styleId && FW_TEX.catalog) return FW_TEX.catalog;
  if(!force && FW_TEX.loadingCatalog) return FW_TEX.loadingCatalog();
  const load = loadTexturesCatalog(styleId);
  FW_TEX.loadingCatalog = function(){ return load; };
  try{ return await load; }finally{ FW_TEX.loadingCatalog = null; }
}

async function loadTexturesCatalog(styleId){
  let payload = null;
  try{
    const response = await fetch('/api/materials/textures?style=' + encodeURIComponent(styleId));
    payload = await response.json();
  }catch(_){
    payload = null;
  }
  if(!payload || !payload.ok){
    if(FW_TEX.styleId !== styleId){ fwDisposeTextures(); FW_TEX.styleId = styleId; FW_TEX.catalog = null; }
    return FW_TEX.catalog;
  }
  fwDisposeTextures();
  FW_TEX.styleId = styleId;
  FW_TEX.catalog = payload;
  const jobs = [];
  Object.keys(payload.items || {}).forEach(function(key){
    const item = payload.items[key];
    if(item && item.state === 'ready' && item.file) jobs.push(fwLoadOne(styleId, key, item));
  });
  await Promise.all(jobs);
  return FW_TEX.catalog;
}

/** 单张就绪后增量装载（轮询用，避免整套重下载） */
async function fwLoadTextureItem(styleId, key, item){
  if(!item || item.state !== 'ready' || !item.file) return;
  if(FW_TEX.catalog && FW_TEX.catalog.items) FW_TEX.catalog.items[key] = item;
  await fwLoadOne(styleId || FW_TEX.styleId, key, item);
}

/** 导出前调用：确保目录已拉取、所有图片解码完成 */
async function fwTexturesReady(){
  await fwReloadTextures(false);
  const active = Object.keys(FW_TEX.loading);
  if(active.length) await Promise.all(active.map(function(key){ return FW_TEX.loading[key]; }));
}
