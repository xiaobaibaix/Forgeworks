/* Forgeworks · js/ui/editor.js */
/* ---------- 编辑器弹窗 ---------- */
function openEditor(coll, id){
  const isNew=!id;
  let d = isNew ? null : S[coll].find(x=>x.id===id);
  modalState={coll,id,isNew};
  const titleMap={elements:'元素',items:'物品',machines:'机器',recipes:'配方',techs:'科技'};
  document.getElementById('modal').innerHTML=`
    <header><h3>${isNew?'新增':'编辑'}${titleMap[coll]}</h3><span class="x" id="mX">×</span></header>
    <div class="content" id="mBody"></div>
    <footer>
      ${!isNew?'<button class="danger" id="mDel">删除</button>':''}
      <div style="flex:1"></div>
      <button id="mCancel">取消</button>
      <button class="primary" id="mOk">保存</button>
    </footer>`;
  document.getElementById('mask').classList.remove('hide');
  document.getElementById('mX').onclick=closeModal;
  document.getElementById('mCancel').onclick=closeModal;
  document.getElementById('mOk').onclick=()=>commitEditor();
  const del=document.getElementById('mDel');
  if(del) del.onclick=()=>{
    if(!confirm(`确认删除「${d.name||d.id}」？引用它的配方会变成悬空引用。`)) return;
    if(coll==='recipes') S.recipes=S.recipes.filter(x=>x.id!==id);
    else S[coll]=S[coll].filter(x=>x.id!==id);
    closeModal(); clearCostCache(); clearIconCache(); render(); toast('已删除');
  };
  renderEditorForm(coll, d, isNew);
}
function closeModal(){
  document.getElementById('mask').classList.add('hide'); modalState=null;
  if(typeof syncResumeAfterModal === 'function') syncResumeAfterModal();
}

/** 表单快照与图标待保存状态，用于判断进入管线前是否真有未保存修改 */
function editorFormSnapshot(names){
  return JSON.stringify(names.map(name=>{
    const el = document.getElementById('f_'+name);
    return el ? el.value : '';
  }));
}

function editorIconDirty(){
  const prev = document.getElementById('iconPrev');
  return !!(prev && (prev.dataset.pending || prev.dataset.cleared));
}

function editorConfirmLeave(dirty){
  return !dirty || confirm('进入生成管线？当前未保存的修改会丢失。');
}

/** 图标资源区（预览 + 上传 + 恢复自动 + 可选生成按钮），物品与元素共用 */
function iconResourceHTML(opt){
  opt = opt || {};
  const hasCustom = !!opt.hasCustom;
  return `<div style="border-top:1px solid var(--border);margin:16px 0 12px;padding-top:14px">
    <div style="font-size:12px;font-weight:500;margin-bottom:10px">图标</div>
    <div style="display:flex;gap:14px;align-items:flex-start">
      <div id="iconPrev" title="点击「上传图标」选择文件，或把图片拖到这里"
           style="width:72px;height:72px;flex:0 0 72px;display:flex;align-items:center;
           justify-content:center;background:var(--panel-2);border:1px solid var(--border);border-radius:10px">
        ${opt.previewHTML||''}
      </div>
      <div style="flex:1">
        <div id="iconHint" style="font-size:11px;color:var(--text-3);margin-bottom:8px">
          ${hasCustom?'当前使用<strong>自定义图标</strong>':'当前使用<strong>自动生成图标</strong>'}
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <label class="sm" style="display:inline-block;padding:6px 12px;border:1px solid var(--border-2);
                 border-radius:7px;cursor:pointer;font-size:12px;background:var(--panel)">
            上传图标<input type="file" id="iconFile" accept="image/*" style="display:none">
          </label>
          <button class="sm" id="iconClear" ${hasCustom?'':'disabled'}>恢复自动生成</button>
          ${opt.showGenerate?'<button class="sm" id="iconGen">生成图标 →</button>':''}
        </div>
        <div style="font-size:10.5px;color:var(--text-3);margin-top:6px">
          上传或拖入的图片会自动缩放到 128×128 并转成内嵌数据，避免撑爆 localStorage。
        </div>
      </div>
    </div>
  </div>`;
}

/** 绑定图标资源区的交互；renderAuto 接收 makeTmp() 的临时对象，返回 <img> HTML */
function bindIconResource(opt){
  opt = opt || {};
  const makeTmp = opt.makeTmp || (()=>({}));
  const renderAuto = opt.renderAuto || (tmp=>iconHTML(tmp, 52));
  const prev = document.getElementById('iconPrev');
  const hint = document.getElementById('iconHint');
  const clearBtn = document.getElementById('iconClear');
  const setHint = html=>{ const h = document.getElementById('iconHint'); if(h) h.innerHTML = html; };

  const applyIconFile = async f=>{
    if(!f) return;
    if(f.type && !/^image\//.test(f.type)){ toast('请选择图片文件'); return; }
    try{
      const dataUrl = await readIconFile(f);
      prev.innerHTML = `<img src="${dataUrl}" width="52" height="52" style="border-radius:6px">`;
      prev.dataset.pending = dataUrl;   // 提交时读取
      setHint('当前使用<strong>自定义图标</strong>（待保存）');
      if(clearBtn) clearBtn.disabled = false;
      toast('图标已载入，点保存生效');
    }catch(err){ toast('图标读取失败：'+err.message); }
  };

  const fileInput = document.getElementById('iconFile');
  if(fileInput) fileInput.onchange = e=>{
    const f = e.target.files[0];
    fileInput.value = '';   // 清空后同一个文件才能再次触发 change
    applyIconFile(f);
  };

  if(prev){
    prev.ondragover = e=>{ e.preventDefault(); prev.style.borderColor = 'var(--accent)'; };
    prev.ondragleave = ()=>{ prev.style.borderColor = ''; };
    prev.ondrop = e=>{
      e.preventDefault(); prev.style.borderColor = '';
      applyIconFile(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]);
    };
  }

  if(clearBtn) clearBtn.onclick = ()=>{
    delete prev.dataset.pending;
    prev.dataset.cleared = '1';
    prev.innerHTML = renderAuto(makeTmp());
    setHint('已恢复<strong>自动生成图标</strong>（待保存）');
    toast('已恢复自动生成（待保存）');
  };

  const gen = document.getElementById('iconGen');
  if(gen && opt.onGenerate) gen.onclick = opt.onGenerate;

  return { prev, hint, makeTmp, renderAuto };
}

function renderEditorForm(coll, d, isNew){
  const b=document.getElementById('mBody');
  const F=(name,label,val,type='text',extra='')=>
    `<div class="field"><label>${label}</label><input type="${type}" id="f_${name}" value="${val??''}" ${extra}></div>`;
  const SEL=(name,label,val,opts)=>
    `<div class="field"><label>${label}</label><select id="f_${name}">${opts.map(o=>
      `<option value="${o.v}" ${o.v===val?'selected':''}>${o.t}</option>`).join('')}</select></div>`;

  if(coll==='elements'){
    const hasCustom = !!(d && d.icon && d.icon.trim());
    b.innerHTML = F('id','ID（建议 元素符号，如 Fe）', d?.id||'','text','required') +
      F('name','名称', d?.name||'') + F('symbol','符号', d?.symbol||'') +
      F('color','颜色（hex）', d?.color||'#888780') +
      SEL('tier','等级', String(d?.tier??0), [0,1,2,3].map(t=>({v:String(t),t:'T'+t}))) +
      iconResourceHTML({ previewHTML: d?elementIconHTML(d,52):'', hasCustom, showGenerate:!isNew });

    const makeTmp = ()=>({
      id:document.getElementById('f_id').value,
      name:document.getElementById('f_name').value,
      symbol:document.getElementById('f_symbol').value,
      color:document.getElementById('f_color').value,
      tier:document.getElementById('f_tier').value,
      icon:'',
    });
    const watchedFields = ['id','name','symbol','color','tier'];
    const initialForm = editorFormSnapshot(watchedFields);
    bindIconResource({
      makeTmp,
      renderAuto: tmp=>elementIconHTML(tmp, 52),
      onGenerate: ()=>{
        if(!d) return;
        const dirty = editorFormSnapshot(watchedFields) !== initialForm || editorIconDirty();
        if(!editorConfirmLeave(dirty)) return;
        const fromView = cur;
        closeModal();
        pipelineEnter(d.id, {view: fromView, assetId: d.id, modal: 'editor', coll: 'elements'});
      },
    });

    // 字段变化时刷新自动图标预览（自定义/待保存状态不覆盖）
    const refreshAuto = ()=>{
      const prev = document.getElementById('iconPrev');
      if(prev.dataset.pending) return;
      if(!prev.dataset.cleared && d && d.icon && d.icon.trim()) return;
      prev.innerHTML = elementIconHTML(makeTmp(), 52);
    };
    ['f_id','f_name','f_symbol','f_color','f_tier'].forEach(n=>{
      const el = document.getElementById(n);
      if(el){ el.oninput = refreshAuto; el.onchange = refreshAuto; }
    });
  }
  else if(coll==='items'){
    const hasCustom = !!(d && d.icon && d.icon.trim());
    b.innerHTML = F('id','ID（大写+下划线）', d?.id||'','text','required') +
      F('name','名称', d?.name||'') +
      SEL('tier','等级', String(d?.tier??0), [0,1,2,3,4,5].map(t=>({v:String(t),t:'T'+t}))) +
      SEL('type','类型', d?.type||'raw',
        ['raw','concentrate','ingot','part','material','module','mega','byproduct','fluid'].map(t=>({v:t,t:typeLabel(t)}))) +
      F('value','价值', d?.value??1,'number') + F('color','颜色', d?.color||'#888780') +
      F('desc','说明', d?.desc||'') +
      iconResourceHTML({ previewHTML: d?iconHTML(d,52):'', hasCustom, showGenerate:!isNew }) +
      `<div style="border-top:1px solid var(--border);margin:14px 0 12px;padding-top:14px">
        <div style="font-size:12px;font-weight:500;margin-bottom:10px">模型</div>
        <div class="row">
          <div class="field"><label>模型状态</label>
            <select id="f_modelStatus">${Object.entries(MODEL_LABELS).map(([k,v])=>
              `<option value="${k}" ${(d?.modelStatus||'primitive')===k?'selected':''}>${v.t}</option>`).join('')}
            </select>
          </div>
        </div>
        ${F('mesh','静态网格路径（如 /Game/Meshes/SM_Ore_Iron）', d?.mesh||'')}
        ${F('mat','材质路径（可选）', d?.mat||'')}
        <div style="font-size:11px;color:var(--text-3);background:var(--panel-2);padding:8px 10px;
             border-radius:7px;margin-top:-4px" id="modelHintBox">
          建议：${d?modelHint(d):'选择类型后显示建模建议'}
        </div>
      </div>`;

    const makeItemTmp = ()=>({
      id:document.getElementById('f_id').value,
      type:document.getElementById('f_type').value,
      color:document.getElementById('f_color').value,
      icon:'',
    });
    const watchedFields = ['id','name','tier','type','value','color','desc','modelStatus','mesh','mat'];
    const initialForm = editorFormSnapshot(watchedFields);
    bindIconResource({
      makeTmp: makeItemTmp,
      renderAuto: tmp=>iconHTML(tmp, 52),
      onGenerate: ()=>{
        if(!d) return;
        const dirty = editorFormSnapshot(watchedFields) !== initialForm || editorIconDirty();
        if(!editorConfirmLeave(dirty)) return;
        const fromView = cur;
        closeModal();
        pipelineEnter(d.id, {view: fromView, assetId: d.id, modal: 'editor'});
      },
    });
    // 类型/颜色变化时刷新自动图标预览
    const refreshAuto = ()=>{
      const prev = document.getElementById('iconPrev');
      if(prev.dataset.pending) return;
      if(!prev.dataset.cleared && d && d.icon && d.icon.trim()) return;
      const tmp = makeItemTmp();
      prev.innerHTML = iconHTML(tmp, 52);
      const box = document.getElementById('modelHintBox');
      if(box) box.textContent = '建议：' + modelHint(tmp);
    };
    document.getElementById('f_type').onchange = refreshAuto;
    document.getElementById('f_color').oninput = refreshAuto;
  }
  else if(coll==='machines'){
    b.innerHTML = F('id','ID', d?.id||'','text','required') + F('name','名称', d?.name||'') +
      SEL('cat','分类', d?.cat||'加工',
        ['采集','分离','冶炼','合金','化工','加工','组装','回收'].map(c=>({v:c,t:c}))) +
      SEL('tier','等级', String(d?.tier??0), [0,1,2,3,4].map(t=>({v:String(t),t:'T'+t}))) +
      F('footprint','占地（如 3×3）', d?.footprint||'2×2') +
      F('power','耗电 kW', d?.power??100,'number') + F('desc','说明', d?.desc||'');
  }
  else if(coll==='recipes'){
    const ioRows=(list,prefix)=> (list||[]).map((o,i)=>`
      <div class="io-row">
        <select class="io-item" data-p="${prefix}" data-i="${i}">
          <option value="">— 选择物品 —</option>
          ${S.items.map(it=>`<option value="${it.id}" ${it.item===o.item?'selected':''}>T${it.tier} ${it.name}</option>`).join('')}
        </select>
        <input class="io-amt" type="number" step="0.1" min="0" value="${o.amount}" data-p="${prefix}" data-i="${i}">
        <button class="sm danger io-del" data-p="${prefix}" data-i="${i}">×</button>
      </div>`).join('');
    b.innerHTML = F('id','ID', d?.id||'','text','required') + F('name','配方名', d?.name||'') +
      SEL('machine','机器', d?.machine||(S.machines[0]?.id||''),
        S.machines.map(m=>({v:m.id,t:m.name}))) +
      SEL('cat','分类', d?.cat||'加工',
        ['分离','冶炼','合金','化工','零件','模块','宏构','回收'].map(c=>({v:c,t:c}))) +
      `<div class="row">
        <div class="field"><label>周期（秒）</label><input type="number" step="0.1" min="0.1" id="f_cycle" value="${d?.cycle??1}"></div>
        <div class="field"><label>耗电 kW</label><input type="number" step="1" min="0" id="f_power" value="${d?.power??100}"></div>
      </div>`+
      `<div class="field"><label>输入</label><div class="io-list" id="ioInputs">${ioRows(d?.inputs,'in')}</div>
        <button class="sm" id="addIn" style="margin-top:6px">+ 添加输入</button></div>`+
      `<div class="field"><label>输出</label><div class="io-list" id="ioOutputs">${ioRows(d?.outputs,'out')}</div>
        <button class="sm" id="addOut" style="margin-top:6px">+ 添加输出</button></div>`+
      F('desc','说明', d?.desc||'');
    document.getElementById('addIn').onclick=()=>addIorow('ioInputs','in');
    document.getElementById('addOut').onclick=()=>addIorow('ioOutputs','out');
    b.querySelectorAll('.io-del').forEach(btn=>{
      btn.onclick=()=>{
        const {p,i}=btn.dataset;
        const list=document.getElementById(p==='in'?'ioInputs':'ioOutputs');
        list.querySelector(`.io-row[data-i="${i}"]`)?.remove();
        renumber(p==='in'?'ioInputs':'ioOutputs');
      };
    });
  }
  else if(coll==='techs'){
    b.innerHTML = F('id','ID', d?.id||'','text','required') + F('name','名称', d?.name||'') +
      SEL('tier','等级', String(d?.tier??0), [0,1,2,3,4].map(t=>({v:String(t),t:'T'+t}))) +
      F('cost','研究成本', d?.cost??100,'number') +
      `<div class="field"><label>前置科技（多选）</label><select multiple size="6" id="f_prereqs" style="height:auto">
        ${S.techs.filter(t=>t.id!==id).map(t=>`<option value="${t.id}" ${d?.prereqs?.includes(t.id)?'selected':''}>${t.name}</option>`).join('')}
      </select><div style="font-size:11px;color:var(--text-3);margin-top:4px">按住 Cmd/Ctrl 多选</div></div>`+
      `<div class="field"><label>解锁配方（多选）</label><select multiple size="10" id="f_unlocks" style="height:auto">
        ${S.recipes.map(r=>`<option value="${r.id}" ${d?.unlocks?.includes(r.id)?'selected':''}>${r.name}</option>`).join('')}
      </select></div>`+
      F('desc','说明', d?.desc||'');
  }
}
function addIorow(listId, prefix){
  const list=document.getElementById(listId);
  const i=list.querySelectorAll('.io-row').length;
  const div=document.createElement('div');
  div.className='io-row'; div.dataset.i=i;
  div.innerHTML=`<select class="io-item" data-p="${prefix}" data-i="${i}">
      <option value="">— 选择物品 —</option>
      ${S.items.map(it=>`<option value="${it.id}">T${it.tier} ${it.name}</option>`).join('')}</select>
    <input class="io-amt" type="number" step="0.1" min="0" value="1" data-p="${prefix}" data-i="${i}">
    <button class="sm danger io-del" data-p="${prefix}" data-i="${i}">×</button>`;
  div.querySelector('.io-del').onclick=()=>{div.remove();renumber(listId);};
  list.appendChild(div);
}
function renumber(listId){
  document.getElementById(listId).querySelectorAll('.io-row').forEach((r,i)=>{
    r.dataset.i=i;
    r.querySelectorAll('[data-i]').forEach(x=>x.dataset.i=i);
  });
}
function commitEditor(){
  const {coll,id,isNew}=modalState;
  const g=n=>document.getElementById('f_'+n)?.value;
  let obj=null;
  if(coll==='elements'){
    const prev = document.getElementById('iconPrev');
    let iconVal = '';
    if(prev && prev.dataset.pending) iconVal = prev.dataset.pending;
    else if(prev && prev.dataset.cleared) iconVal = '';
    else iconVal = S.elements.find(x=>x.id===id)?.icon || '';
    obj={id:g('id').trim(),name:g('name').trim(),symbol:g('symbol').trim(),
      color:g('color').trim(),tier:+g('tier'),icon:iconVal};
  }
  else if(coll==='items'){
    // 图标：优先取刚上传的，其次看是否点了"恢复自动"，否则沿用原值
    const prev = document.getElementById('iconPrev');
    let iconVal = '';
    if(prev && prev.dataset.pending) iconVal = prev.dataset.pending;
    else if(prev && prev.dataset.cleared) iconVal = '';
    else iconVal = S.items.find(x=>x.id===id)?.icon || '';
    obj={id:g('id').trim(),name:g('name').trim(),tier:+g('tier'),
      type:g('type'),value:+g('value')||0,color:g('color').trim(),desc:g('desc'),
      icon:iconVal,
      mesh:(g('mesh')||'').trim(),
      mat:(g('mat')||'').trim(),
      modelStatus:g('modelStatus')||'primitive'};
  }
  else if(coll==='machines') obj={id:g('id').trim(),name:g('name').trim(),cat:g('cat'),
    tier:+g('tier'),footprint:g('footprint').trim(),power:+g('power')||0,desc:g('desc')};
  else if(coll==='recipes'){
    const readIO=(listId,prefix)=>[...document.getElementById(listId).querySelectorAll('.io-row')]
      .map(r=>({
        item:r.querySelector('.io-item').value,
        amount:parseFloat(r.querySelector('.io-amt').value)||0
      })).filter(o=>o.item && o.amount>0);
    obj={id:g('id').trim(),name:g('name').trim(),machine:g('machine'),cat:g('cat'),
      cycle:+g('cycle')||1,power:+g('power')||0,
      inputs:readIO('ioInputs','in'),outputs:readIO('ioOutputs','out'),desc:g('desc')};
  }
  else if(coll==='techs') obj={id:g('id').trim(),name:g('name').trim(),tier:+g('tier'),
    cost:+g('cost')||0,
    prereqs:[...document.getElementById('f_prereqs').selectedOptions].map(o=>o.value),
    unlocks:[...document.getElementById('f_unlocks').selectedOptions].map(o=>o.value),
    desc:g('desc')};

  if(!obj.id){ toast('ID 不能为空'); return; }
  if(!obj.name){ toast('名称不能为空'); return; }
  if(S[coll].some(x=>x.id===obj.id && x.id!==id)){ toast('ID 已存在：'+obj.id); return; }

  if(isNew){ S[coll].push(obj); }
  else {
    const arr = S[coll];
    const i=arr.findIndex(x=>x.id===id);
    arr[i]=obj;
  }
  saveState(); closeModal(); clearCostCache(); clearIconCache(); render(); toast('已保存');
}
