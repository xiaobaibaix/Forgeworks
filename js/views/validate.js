/* Forgeworks · js/views/validate.js */
/* ---------- 校验 ---------- */
function renderValidate(){
  const v=document.getElementById('view');
  const issues=validate();
  const errs=issues.filter(i=>i.lv==='err').length;
  const warns=issues.filter(i=>i.lv==='warn').length;
  const infos=issues.filter(i=>i.lv==='info').length;
  let h=`<div class="grid2" style="margin-bottom:16px">
    <div class="stat"><div class="v" style="color:${errs?'var(--red)':'var(--accent)'}">${errs}</div><div class="k">错误（阻断）</div></div>
    <div class="stat"><div class="v" style="color:${warns?'var(--amber)':'var(--text-3)'}">${warns}</div><div class="k">警告</div></div>
    <div class="stat"><div class="v" style="color:var(--text-3)">${infos}</div><div class="k">提示</div></div>
  </div>`;
  if(!issues.length){
    h+=`<div class="issue info"><span class="ic">✓</span><div>全部检查通过，数据可以导出。</div></div>`;
  } else {
    const order={err:0,warn:1,info:2};
    issues.slice().sort((a,b)=>order[a.lv]-order[b.lv]).forEach(i=>{
      const ic = i.lv==='err'?'✕':i.lv==='warn'?'!':'i';
      h+=`<div class="issue ${i.lv}"><span class="ic">${ic}</span><div>${i.msg}</div>${i.loc?`<span class="loc">${i.loc}</span>`:''}</div>`;
    });
  }
  v.innerHTML=h;
}
