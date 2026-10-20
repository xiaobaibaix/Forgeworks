/* Forgeworks · js/core/io.js */
/* ---------- 下载 ---------- */
/**
 * 复制文本。file:// 下 navigator.clipboard 可能不存在（非安全上下文），
 * 降级到隐藏 textarea + document.execCommand('copy')。
 */
function copyText(text){
  const fallback = ()=>{
    try{
      const ta=document.createElement('textarea');
      ta.value=text;
      ta.style.position='fixed'; ta.style.left='-9999px'; ta.style.top='0';
      document.body.appendChild(ta);
      ta.focus(); ta.select();
      const ok = document.execCommand && document.execCommand('copy');
      document.body.removeChild(ta);
      toast(ok?'已复制到剪贴板':'复制失败，请手动下载 JSON');
    }catch(e){
      toast('复制失败，请手动下载 JSON');
    }
  };
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(()=>toast('已复制到剪贴板')).catch(fallback);
  }else{
    fallback();
  }
}

function download(name, content, mime){
  const blob=new Blob([content],{type:mime||'text/plain;charset=utf-8'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download=name;
  document.body.appendChild(a); a.click();
  setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},100);
}
function dlCsv(name, content){
  download(name+'.csv','﻿'+content,'text/csv;charset=utf-8'); // BOM 保证 Excel 中文不乱码
  toast('已导出 '+name+'.csv');
}

/* ---------- 图标上传：缩放后转 dataURL ---------- */
/**
 * 把用户选的图片缩到 128×128 以内再转 dataURL。
 * 直接存原图会让 localStorage 爆掉（5MB 配额，75 个物品）。
 */
function readIconFile(file, maxSize){
  maxSize = maxSize || 128;
  return new Promise((resolve, reject)=>{
    const reader = new FileReader();
    reader.onerror = ()=>reject(new Error('文件读取失败'));
    reader.onload = ()=>{
      const img = new Image();
      img.onerror = ()=>reject(new Error('图片解析失败'));
      img.onload = ()=>{
        try{
          const ratio = Math.min(1, maxSize/Math.max(img.width, img.height));
          const w = Math.max(1, Math.round(img.width*ratio));
          const h = Math.max(1, Math.round(img.height*ratio));
          const cv = document.createElement('canvas');
          cv.width = w; cv.height = h;
          const ctx = cv.getContext('2d');
          if(!ctx) throw new Error('Canvas 不可用');
          ctx.clearRect(0,0,w,h);
          ctx.drawImage(img, 0, 0, w, h);
          // PNG 保留透明通道；如果文件很大则降到 JPEG
          let out = cv.toDataURL('image/png');
          if(out.length > 60000){
            // 铺白底再转 JPEG，避免透明区变黑
            const cv2 = document.createElement('canvas');
            cv2.width=w; cv2.height=h;
            const c2 = cv2.getContext('2d');
            c2.fillStyle='#ffffff'; c2.fillRect(0,0,w,h);
            c2.drawImage(img,0,0,w,h);
            out = cv2.toDataURL('image/jpeg', 0.88);
          }
          resolve(out);
        }catch(e){ reject(e); }
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}
