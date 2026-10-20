/* Forgeworks · js/views/prompts.js
   ============================================================
   美术需求视图
   ------------------------------------------------------------
   把每个建筑/物品的「生成描述词」摆出来，方便：
     - 直接复制去喂文生图 / 文生 3D
     - 整包导出成任务书交给美术
     - 用等轴测体块预览检查占地与体量是否合理

   注意：本页不生成任何资源文件，只输出文字与预览图。
   ============================================================ */

let PROMPT_FILTER = 'machine';     // machine | item | all
const ISO_ROT = {};                // { machineId: 0..3 } 体块旋转状态

function renderPrompts(){
  const v = document.getElementById('view');

  const mCount = S.machines.length;
  const iCount = S.items.length;

  let h = `<div class="card">
    <h3>美术需求 · 生成描述词</h3>
    <p class="hint">
      每个建筑/物品都有一条可直接使用的描述词。本页<strong>不生成资源</strong>，
      只负责把数据翻译成美术可执行的指令 —— 复制去文生图/文生 3D，或导出交给美术。
    </p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
      <button class="primary" id="prExportMd">导出全部描述词 (Markdown)</button>
      <button id="prExportJson">导出 (JSON)</button>
      <button id="prExportTxt">导出建筑任务书 (纯文本)</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      ${[
        ['machine','建筑',mCount],
        ['item','物品',iCount],
        ['all','全部',mCount+iCount],
      ].map(([k,label,n])=>{
        const active = PROMPT_FILTER===k;
        return `<button class="sm" data-pfilter="${k}"
          style="${active?'background:var(--accent);color:#fff;border-color:var(--accent)':''}">${label} (${n})</button>`;
      }).join('')}
    </div>
    <div style="margin-top:12px;font-size:11.5px;color:var(--text-2);background:var(--panel-2);
         padding:10px 12px;border-radius:8px;line-height:1.8">
      <strong>统一风格约束（所有资源共用）</strong><br>
      渲染：${STYLE_BLOCK.render}<br>
      光影：${STYLE_BLOCK.shading}；${STYLE_BLOCK.lighting}<br>
      视角：${STYLE_BLOCK.camera}<br>
      负向词：${NEGATIVE.join('、')}
    </div>
  </div>`;

  /* ---------- 建筑 ---------- */
  if(PROMPT_FILTER === 'machine' || PROMPT_FILTER === 'all'){
    h += `<div class="card"><h3>建筑（${mCount}）</h3>
      <p class="hint">等轴测体块预览用于核对占地与体量比例，不是最终模型。点「旋转」换视角。</p></div>`;
    h += `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px">`;
    S.machines.forEach(m=>{
      const rot = ISO_ROT[m.id] || 0;
      const brief = MACHINE_BRIEFS[m.id] || {};
      const prompt = machinePrompt(m, {withTech:true});
      h += `<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;overflow:hidden">
        <div style="display:flex;gap:12px;padding:12px;border-bottom:1px solid var(--border)">
          <div style="flex:0 0 auto;background:var(--panel-2);border-radius:8px;overflow:hidden">
            <div id="iso-${m.id}">${isoPreview(m, rot, 132)}</div>
          </div>
          <div style="min-width:0;flex:1">
            <div style="font-size:13px;font-weight:500;margin-bottom:2px">${m.name}</div>
            <div style="font-size:10.5px;color:var(--text-3);font-family:var(--mono);
                 margin-bottom:6px;overflow:hidden;text-overflow:ellipsis">${m.id}</div>
            <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px">
              <span class="pill">${m.cat}</span>
              <span class="pill">${m.footprint}</span>
              ${tierTag(m.tier)}
            </div>
            <div style="display:flex;gap:4px;flex-wrap:wrap">
              <button class="sm primary" data-view3d="${m.id}">3D 查看</button>
              <button class="sm" data-rot="${m.id}">⟳ 换角度</button>
              <button class="sm" data-copy="${m.id}">复制描述词</button>
              <button class="sm" data-view="${m.id}">全文</button>
            </div>
          </div>
        </div>
        <div style="padding:10px 12px;font-size:11.5px;color:var(--text-2);line-height:1.7">
          ${brief.form ? `<strong>形态</strong> ${brief.form}` : ''}
          ${brief.note ? `<br><strong>细节</strong> ${brief.note}` : ''}
        </div>
      </div>`;
    });
    h += `</div>`;
  }

  /* ---------- 物品 ---------- */
  if(PROMPT_FILTER === 'item' || PROMPT_FILTER === 'all'){
    h += `<div class="card" style="margin-top:16px"><h3>物品（${iCount}）</h3>
      <p class="hint">物品描述词按类型模板生成，主色取自物品自身配色。</p></div>`;
    h += `<div class="scroll-x"><table>
      <thead><tr><th>图标</th><th>物品</th><th>类型</th><th>形态</th><th>操作</th></tr></thead><tbody>`;
    S.items.forEach(it=>{
      h += `<tr>
        <td>${iconHTML(it, 26)}</td>
        <td>${it.name}<br><code style="font-size:10px;color:var(--text-3)">${it.id}</code></td>
        <td><span class="pill">${typeLabel(it.type)}</span></td>
        <td style="color:var(--text-2);font-size:11.5px">${ITEM_FORM[it.visual||it.type]||''}</td>
        <td><button class="sm" data-copyitem="${it.id}">复制</button></td>
      </tr>`;
    });
    h += `</tbody></table></div>`;
  }

  v.innerHTML = h;

  /* ---------- 绑定 ---------- */
  v.querySelectorAll('[data-pfilter]').forEach(b=>{
    b.onclick = ()=>{ PROMPT_FILTER = b.dataset.pfilter; renderPrompts(); };
  });
  v.querySelectorAll('[data-view3d]').forEach(b=>{
    b.onclick = ()=>open3DViewer(b.dataset.view3d);
  });
  v.querySelectorAll('[data-rot]').forEach(b=>{
    b.onclick = ()=>{
      const id = b.dataset.rot;
      ISO_ROT[id] = ((ISO_ROT[id]||0) + 1) & 3;
      const m = machineOf(id);
      const box = document.getElementById('iso-'+id);
      if(box && m) box.innerHTML = isoPreview(m, ISO_ROT[id], 132);
    };
  });
  v.querySelectorAll('[data-copy]').forEach(b=>{
    b.onclick = ()=>{
      const m = machineOf(b.dataset.copy);
      if(m) copyText(machinePrompt(m, {withTech:true}));
    };
  });
  v.querySelectorAll('[data-copyitem]').forEach(b=>{
    b.onclick = ()=>{
      const it = itemOf(b.dataset.copyitem);
      if(it) copyText(itemPrompt(it, {withTech:true}));
    };
  });
  v.querySelectorAll('[data-view]').forEach(b=>{
    b.onclick = ()=>showPromptModal(b.dataset.view);
  });
  document.getElementById('prExportMd').onclick = ()=>download('美术需求描述词.md', promptsMarkdown(), 'text/markdown');
  document.getElementById('prExportJson').onclick = ()=>download('美术需求描述词.json', JSON.stringify(promptsJSON(),null,2), 'application/json');
  document.getElementById('prExportTxt').onclick = ()=>download('建筑建模任务书.txt', machineBriefText(), 'text/plain');
}

/* ---------- 描述词全文弹窗 ---------- */
function showPromptModal(machineId){
  const m = machineOf(machineId);
  if(!m) return;
  const p = machinePrompt(m, {withTech:true});
  const rot = ISO_ROT[m.id] || 0;
  document.getElementById('modal').innerHTML = `
    <header><h3>${m.name} · 描述词</h3><span class="x" id="mX">×</span></header>
    <div class="content">
      <div style="display:flex;gap:16px;align-items:flex-start;margin-bottom:16px">
        <div style="background:var(--panel-2);border-radius:10px;padding:4px">${isoPreview(m, rot, 180)}</div>
        <div style="flex:1">
          <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px">
            <span class="pill">${m.cat}</span><span class="pill">${m.footprint}</span>${tierTag(m.tier)}
          </div>
          <div style="font-size:11.5px;color:var(--text-2);line-height:1.8">
            <strong>建模状态</strong> ${(MODEL_LABELS[m.modelStatus||'primitive']||{}).t||'—'}<br>
            <strong>占用机时</strong> ${m.power} kW
          </div>
          <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
            <button class="sm" id="pmRot">⟳ 换视角</button>
            <button class="sm primary" id="pmCopy">复制描述词</button>
          </div>
        </div>
      </div>
      <label>描述词（可直接粘贴给文生图 / 文生 3D）</label>
      <textarea id="pmText" style="height:300px;width:100%">${p}</textarea>
    </div>
    <footer><button id="pmClose">关闭</button></footer>`;
  document.getElementById('mask').classList.remove('hide');
  document.getElementById('mX').onclick = closeModal;
  document.getElementById('pmClose').onclick = closeModal;
  document.getElementById('pmCopy').onclick = ()=>copyText(p);
  document.getElementById('pmRot').onclick = ()=>{
    ISO_ROT[m.id] = ((ISO_ROT[m.id]||0)+1)&3;
    showPromptModal(m.id);
  };
}

/* ---------- 导出：Markdown ---------- */
function promptsMarkdown(){
  let h = `# Forgeworks · 美术需求描述词\n\n`;
  h += `> 导出时间：${new Date().toLocaleString('zh-CN')}\n`;
  h += `> 本文档只描述需求，不包含任何资源文件。\n\n`;
  h += `## 统一风格约束\n\n`;
  h += `| 项 | 内容 |\n|---|---|\n`;
  h += `| 渲染 | ${STYLE_BLOCK.render} |\n`;
  h += `| 光影 | ${STYLE_BLOCK.shading}；${STYLE_BLOCK.lighting} |\n`;
  h += `| 视角 | ${STYLE_BLOCK.camera} |\n`;
  h += `| 背景 | ${STYLE_BLOCK.background} |\n`;
  h += `| 细节原则 | ${STYLE_BLOCK.detailRule} |\n\n`;
  h += `**负向词**：${NEGATIVE.join('、')}\n\n`;
  h += `**技术规格**\n\n`;
  h += `- 建筑：${TECH_SPEC.machine}\n`;
  h += `- 物品：${TECH_SPEC.item}\n`;
  h += `- 图标：${TECH_SPEC.icon}\n\n`;

  h += `---\n\n## 一、建筑（${S.machines.length}）\n\n`;
  S.machines.forEach(m=>{
    h += `### ${m.name}\n\n`;
    h += `| 项 | 值 |\n|---|---|\n`;
    h += `| ID | \`${m.id}\` |\n`;
    h += `| 分类 | ${m.cat} |\n`;
    h += `| 占地 | ${m.footprint} |\n`;
    h += `| 纪元 | T${m.tier} |\n`;
    h += `| 耗电 | ${m.power} kW |\n\n`;
    h += `\`\`\`\n${machinePrompt(m,{withTech:true})}\`\`\`\n\n`;
  });

  h += `---\n\n## 二、物品（${S.items.length}）\n\n`;
  h += `| 物品 | ID | 类型 | 主色 | 形态要求 |\n|---|---|---|---|---|\n`;
  S.items.forEach(it=>{
    h += `| ${it.name} | \`${it.id}\` | ${typeLabel(it.type)} | ${it.color} | ${ITEM_FORM[it.visual||it.type]||'—'} |\n`;
  });

  return h;
}

/* ---------- 导出：JSON（给自动化管线用） ---------- */
function promptsJSON(){
  return {
    tool: 'Forgeworks',
    exportedAt: new Date().toISOString(),
    style: STYLE_BLOCK,
    negative: NEGATIVE,
    techSpec: TECH_SPEC,
    machines: S.machines.map(m=>({
      id: m.id, name: m.name, category: m.cat, footprint: m.footprint, tier: m.tier,
      form: (MACHINE_BRIEFS[m.id]||{}).form || '',
      parts: (MACHINE_BRIEFS[m.id]||{}).parts || [],
      palette: (MACHINE_BRIEFS[m.id]||{}).palette || '',
      note: (MACHINE_BRIEFS[m.id]||{}).note || '',
      prompt: machinePrompt(m, {withTech:true}),
      modelStatus: m.modelStatus || 'primitive',
      meshPath: m.mesh || '',
    })),
    items: S.items.map(it=>({
      id: it.id, name: it.name, type: it.type, tier: it.tier, color: it.color,
      form: ITEM_FORM[it.visual||it.type] || '',
      prompt: itemPrompt(it, {withTech:true}),
    })),
  };
}

/* ---------- 导出：纯文本任务书（给美术/外包） ---------- */
function machineBriefText(){
  let h = 'FORGEWORKS · 建筑建模任务书\n';
  h += '='.repeat(56) + '\n\n';
  h += `生成时间：${new Date().toLocaleString('zh-CN')}\n`;
  h += `建筑总数：${S.machines.length}\n\n`;
  h += '统一规范\n' + '-'.repeat(56) + '\n';
  h += `风格：${STYLE_BLOCK.render}\n`;
  h += `视角：${STYLE_BLOCK.camera}\n`;
  h += `规格：${TECH_SPEC.machine}\n`;
  h += `禁止：${NEGATIVE.join('、')}\n\n`;

  S.machines.forEach((m, i)=>{
    const b = MACHINE_BRIEFS[m.id] || {};
    h += `\n[${String(i+1).padStart(2,'0')}] ${m.name}  (${m.id})\n`;
    h += '-'.repeat(56) + '\n';
    h += `分类：${m.cat}    占地：${m.footprint}    纪元：T${m.tier}\n`;
    h += `外形：${b.form || '—'}\n`;
    h += `部件：${(b.parts||[]).join(' / ') || '—'}\n`;
    h += `配色：${b.palette || '—'}\n`;
    if(b.note) h += `要点：${b.note}\n`;
    h += `\n`;
  });

  h += '\n' + '='.repeat(56) + '\n';
  h += '完\n';
  return h;
}
