/* Forgeworks · Per-part 3D editor */
let _partEditor = null;

function editor3dEscape(value){
  return String(value == null ? '' : value).replace(/[&<>"']/g, ch=>({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  })[ch]);
}

function open3DEditor(machineId){
  const machine = machineOf(machineId);
  if(!machine) return;
  if(_partEditor) _partEditor.dispose();
  const modal = document.getElementById('modal');
  modal.innerHTML = `<header><h3>${editor3dEscape(machine.name)} · 部件编辑器</h3><span class="x" id="e3dClose">×</span></header>
    <div class="content" style="padding:0"><div style="display:grid;grid-template-columns:minmax(280px,1fr) 300px;min-height:520px">
      <canvas id="e3dCanvas" style="width:100%;height:520px;background:#f2f0ec"></canvas>
      <aside style="padding:12px;border-left:1px solid var(--border);overflow:auto">
      <div style="display:flex;gap:6px;flex-wrap:wrap"><button id="e3dUndo">撤销</button><button id="e3dRedo">重做</button><button id="e3dReset">复位部件</button><button id="e3dSnap">吸附：开</button></div>
        <div id="e3dParts" style="max-height:150px;overflow:auto;margin:10px 0"></div>
        <div id="e3dFields"></div>
      </aside>
    </div></div><footer><button class="primary" id="e3dDone">完成</button></footer>`;
  document.getElementById('mask').classList.remove('hide');
  const viewer = createViewer3D(document.getElementById('e3dCanvas'), machine);
  _partEditor = viewer;
  const ensureParts = ()=>{
    machine.ui3d = machine.ui3d || {parts:{}};
    machine.ui3d.parts = machine.ui3d.parts || {};
    return machine.ui3d.parts;
  };
  const partState = ()=>machine.ui3d && machine.ui3d.parts || {};
  let selected = null;
  const undo = [], redo = [];
  let snapEnabled = true;
  const clone = value=>JSON.parse(JSON.stringify(value || {}));
  const saveSnapshot = stack=>{
    stack.push(clone(partState()));
    if(stack.length > 50) stack.shift();
  };
  const persist = ()=>{
    ensureParts();
    saveState();
  };
  const apply = ()=>{
    const entry = partState()[selected];
    viewer.setPartOverride(selected, entry || null);
    viewer.redraw();
  };
  const renderParts = ()=>{
    const el = document.getElementById('e3dParts');
    el.innerHTML = viewer.getParts().map(part=>`<button class="sm" data-e3d-part="${editor3dEscape(part.id)}" style="display:block;width:100%;text-align:left;margin:2px 0;${part.id===selected?'border-color:var(--accent)':''}">${editor3dEscape(part.role)} · ${editor3dEscape(part.kind)}</button>`).join('');
    el.querySelectorAll('[data-e3d-part]').forEach(button=>button.onclick=()=>{
      selected = button.dataset.e3dPart;
      renderParts(); renderFields();
    });
  };
  const renderFields = ()=>{
    const el = document.getElementById('e3dFields');
    if(!selected){ el.innerHTML = '<span class="hint">选择一个部件以编辑。</span>'; return; }
    const state = partState()[selected] || {};
    const t = state.transform || {};
    const p = t.position || {}, r = t.rotation || {}, s = t.scale || {};
    const mat = state.material || {};
    const field = (label, key, value, min, max, step)=>`<label style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin:5px 0;font-size:11px">${label}<input data-e3d-value="${key}" type="number" value="${Number(value)}" min="${min}" max="${max}" step="${step}" style="width:110px"></label>`;
    el.innerHTML = `<strong>${editor3dEscape(selected)}</strong>
      ${field('位置 X','px',p.x||0,-20,20,0.01)}${field('位置 Y','py',p.y||0,-20,20,0.01)}${field('位置 Z','pz',p.z||0,-20,20,0.01)}
      ${field('旋转 X°','rx',(r.x||0)*180/Math.PI,-360,360,1)}${field('旋转 Y°','ry',(r.y||0)*180/Math.PI,-360,360,1)}${field('旋转 Z°','rz',(r.z||0)*180/Math.PI,-360,360,1)}
      ${field('缩放 X','sx',s.x||1,0.05,10,0.05)}${field('缩放 Y','sy',s.y||1,0.05,10,0.05)}${field('缩放 Z','sz',s.z||1,0.05,10,0.05)}
      <label style="display:block;margin:8px 0;font-size:11px"><input type="checkbox" id="e3dHidden" ${state.hidden?'checked':''}> 隐藏部件</label>
      <hr><label style="font-size:11px">覆盖颜色 <input id="e3dColor" type="color" value="${editor3dEscape(mat.color||'#868d96')}"></label>
      <label style="display:block;font-size:11px;margin:6px 0">贴图 <input id="e3dTexture" type="file" accept="image/png,image/jpeg,image/webp"></label>
      <div style="font-size:10px;color:var(--text-3)">${mat.textureData?'已绑定贴图':'无贴图'} · 最大 512 KB</div>
      <button id="e3dRemoveTexture" style="margin-top:4px" ${mat.textureData?'':'disabled'}>移除贴图</button>
      ${field('金属度','metallic',mat.metallic||0,0,1,0.01)}${field('粗糙度','roughness',mat.roughness||0.5,0,1,0.01)}
      ${field('发光','emissive',mat.emissive||0,0,1.6,0.05)}${field('透明度','alpha',mat.alpha===undefined?1:mat.alpha,0.05,1,0.05)}
      <button id="e3dStyle" style="margin-top:6px">恢复风格材质</button>`;
    el.querySelectorAll('[data-e3d-value]').forEach(input=>input.onchange=()=>{
      saveSnapshot(undo); redo.length=0;
      const item = ensureParts()[selected] = ensureParts()[selected] || {};
      item.transform = item.transform || {position:{},rotation:{},scale:{x:1,y:1,z:1}};
      const map = {px:['position','x'],py:['position','y'],pz:['position','z'],rx:['rotation','x'],ry:['rotation','y'],rz:['rotation','z'],sx:['scale','x'],sy:['scale','y'],sz:['scale','z'],metallic:['material','metallic'],roughness:['material','roughness'],emissive:['material','emissive'],alpha:['material','alpha']};
      const [section, axis] = map[input.dataset.e3dValue];
      if(['position','rotation','scale'].includes(section)){
        item.transform = item.transform || {};
        item.transform[section] = item.transform[section] || {};
      }else item.material = item.material || {};
      let value = Number(input.value);
      if(snapEnabled){
        const increment = section === 'position' ? 0.1 : section === 'rotation' ? Math.PI/12 : section === 'scale' ? 0.1 : 0;
        if(increment) value = Math.round(value/increment)*increment;
        input.value = section === 'rotation' ? String(Math.round(value*180/Math.PI)) : String(value);
      }
      if(section === 'rotation') value *= Math.PI/180;
      if(section === 'material') value = Math.max(0,Math.min(axis==='emissive'?1.6:1,value));
      if(['position','rotation','scale'].includes(section)) item.transform[section][axis] = value;
      else item.material[axis] = value;
      apply(); persist();
    });
    const hidden = document.getElementById('e3dHidden');
    hidden.onchange = ()=>{ saveSnapshot(undo); redo.length=0; ensureParts()[selected] = Object.assign({}, partState()[selected] || {}, {hidden:hidden.checked}); apply(); persist(); };
    document.getElementById('e3dColor').onchange = event=>{
      saveSnapshot(undo); redo.length=0;
      const item = ensureParts()[selected] = ensureParts()[selected] || {};
      item.material = item.material || {}; item.material.color = event.target.value; apply(); persist();
    };
    document.getElementById('e3dTexture').onchange = event=>{
      const file = event.target.files && event.target.files[0];
      if(!file) return;
      if(!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > 512*1024){
        toast('贴图仅支持 PNG/JPEG/WebP，且不超过 512 KB'); event.target.value=''; return;
      }
      const reader = new FileReader();
      reader.onload = ()=>{
        saveSnapshot(undo); redo.length=0;
        const item = ensureParts()[selected] = ensureParts()[selected] || {};
        item.material = item.material || {}; item.material.textureData = String(reader.result);
        apply(); persist(); renderFields();
      };
      reader.readAsDataURL(file);
    };
    document.getElementById('e3dRemoveTexture').onclick = ()=>{
      const item = partState()[selected];
      if(!item || !item.material) return;
      saveSnapshot(undo); redo.length=0;
      delete item.material.textureData;
      if(!Object.keys(item.material).length) delete item.material;
      apply(); persist(); renderFields();
    };
    document.getElementById('e3dStyle').onclick = ()=>{
      saveSnapshot(undo); redo.length=0;
      if(machine.ui3d && machine.ui3d.parts && machine.ui3d.parts[selected]){
        delete machine.ui3d.parts[selected].material; apply(); persist(); renderFields();
      }
    };
  };
  renderParts();
  renderFields();
  document.getElementById('e3dUndo').onclick=()=>{
    if(!undo.length) return; saveSnapshot(redo); machine.ui3d.parts=undo.pop(); apply(); renderFields(); persist();
  };
  document.getElementById('e3dRedo').onclick=()=>{
    if(!redo.length) return; saveSnapshot(undo); machine.ui3d.parts=redo.pop(); apply(); renderFields(); persist();
  };
  document.getElementById('e3dReset').onclick=()=>{
    if(!selected || !confirm('复位所选部件的变换和材质？')) return;
    saveSnapshot(undo); redo.length=0;
    delete ensureParts()[selected]; apply(); renderFields(); persist();
  };
  document.getElementById('e3dSnap').onclick=event=>{
    snapEnabled=!snapEnabled;
    event.target.textContent='吸附：'+(snapEnabled?'开':'关');
  };
  const close = ()=>{ viewer.dispose(); _partEditor=null; closeModal(); };
  document.getElementById('e3dClose').onclick=close;
  document.getElementById('e3dDone').onclick=close;
}
