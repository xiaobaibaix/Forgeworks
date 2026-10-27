/* Forgeworks · js/views/balance.js */
/* ---------- 物料平衡视图 ---------- */
// 正向换算的原料输入状态（按物品记忆，避免每次切换清空）
let FWD_INPUTS = {};

function renderBalance(){
  const v=document.getElementById('view');
  if(!S.items.length){
    v.innerHTML = emptyHint('当前项目还没有物品，先到「物品」页新增。');
    addBtn('+ 新增物品');
    return;
  }
  // 默认选一个 T4 模块，最能体现链条深度
  if(!window._balTarget || !S.items.some(i=>i.id===window._balTarget)){
    const t4 = S.items.find(i=>i.type==='module') || S.items[S.items.length-1];
    window._balTarget = t4.id;
  }
  const opts = S.items.map(i=>{
    const produced = S.recipes.some(r=>r.outputs.some(o=>o.amount>0&&o.item===i.id));
    return `<option value="${i.id}" ${window._balTarget===i.id?'selected':''}>${produced?'':'[原料] '}${i.name} (T${i.tier})</option>`;
  }).join('');

  v.innerHTML=`
  <div class="card">
    <h3>物料平衡换算</h3>
    <p class="hint">定量回答三个问题：<strong>做 1 个要吃什么</strong>（单位成本）、<strong>要 N 个要备多少料</strong>（反向）、<strong>有多少料能产几个</strong>（正向）。</p>
    <div class="row" style="max-width:720px">
      <div class="field" style="margin:0"><label>目标物品</label><select id="balTarget">${opts}</select></div>
      <div class="field" style="margin:0;flex:0 0 150px"><label>目标数量（个）</label><input id="balAmount" type="number" value="10" min="0.01" step="1"></div>
    </div>
  </div>
  <div id="balOut"></div>`;

  document.getElementById('balTarget').onchange=e=>{
    window._balTarget=e.target.value;
    runBalance();
  };
  document.getElementById('balAmount').oninput=()=>runBalance();
  runBalance();
}

function runBalance(){
  const out=document.getElementById('balOut');
  const targetId=window._balTarget;
  const amount=parseFloat(document.getElementById('balAmount').value)||0;
  const it=itemOf(targetId);
  if(!it) { out.innerHTML=''; return; }

  const hasRecipe = S.recipes.some(r=>r.outputs.some(o=>o.amount>0&&o.item===targetId));
  if(!hasRecipe){
    out.innerHTML=`<div class="card"><div class="issue info"><span class="ic">i</span>
      <div><strong>${it.name}</strong> 是基础原料，没有产出配方。它由采集机器直接产出，不需要上游输入。</div></div>
      <p class="hint" style="margin-top:12px">要看它被用来做什么，切到「依赖图谱」或「配方」页。</p></div>`;
    return;
  }

  const u = unitCost(targetId);           // 单位成本
  let h='';

  /* ---------- ① 单位成本 ---------- */
  const rawEntries = Object.entries(u.raws).sort((a,b)=>b[1]-a[1]);
  const rawTotal = rawEntries.reduce((s,[,v])=>s+v,0);

  h+=`<div class="card">
    <h3>① 单位成本 · 每生产 1 个「${it.name}」</h3>
    <p class="hint">这是最核心的数字：一个成品要吃掉多少基础原料，以及中间要过几道工序。</p>`;

  if(!rawEntries.length){
    h+=`<div class="issue warn"><span class="ic">!</span><div>未解析出基础原料（可能整条链都是外部供给，或存在循环）。</div></div>`;
  } else {
    h+=`<div class="scroll-x"><table>
      <thead><tr><th>基础原料</th><th>每单位需要</th><th>占比</th><th>可视化</th></tr></thead><tbody>`;
    rawEntries.forEach(([id,amt])=>{
      const r=itemOf(id);
      const pct = rawTotal>0 ? (amt/rawTotal*100) : 0;
      const barW = Math.max(2, pct*1.6);
      h+=`<tr>
        <td><span class="swatch" style="background:${r?.color||'#999'}"></span>${r?.name||id}</td>
        <td><code>${fmtNum(amt)}</code></td>
        <td><code>${pct.toFixed(1)}%</code></td>
        <td><div style="background:var(--accent);height:8px;border-radius:3px;width:${barW}px;opacity:.55"></div></td>
      </tr>`;
    });
    h+=`</tbody></table></div>`;
    h+=`<div style="display:flex;gap:18px;margin-top:12px;flex-wrap:wrap;font-size:12px">
      <div><span style="color:var(--text-3)">原料种类</span> <strong>${rawEntries.length}</strong> 种</div>
      <div><span style="color:var(--text-3)">原料总件数</span> <strong>${fmtNum(rawTotal)}</strong></div>
      <div><span style="color:var(--text-3)">加工工序</span> <strong>${Object.keys(u.cycles).length}</strong> 道</div>
      <div><span style="color:var(--text-3)">总机时</span> <strong>${fmtNum(u.totalMachineSeconds)}</strong> 秒</div>
      <div><span style="color:var(--text-3)">总电耗</span> <strong>${fmtNum(u.totalPower)}</strong> kWh</div>
    </div>`;
  }
  h+=`</div>`;

  /* ---------- ② 中间产物与工序 ---------- */
  const cycEntries = Object.entries(u.cycles).sort((a,b)=>{
    const ta = itemOf(a[1].recipe.outputs.find(o=>o.amount>0)?.item)?.tier ?? 0;
    const tb = itemOf(b[1].recipe.outputs.find(o=>o.amount>0)?.item)?.tier ?? 0;
    return ta - tb;   // 从低阶到高阶
  });
  h+=`<div class="card">
    <h3>② 工序链 · 每 1 个「${it.name}」要跑哪些配方</h3>
    <p class="hint">按阶级从低到高排列。「循环次数」是这条配方要执行多少次才能凑够产量。</p>
    <div class="scroll-x"><table>
      <thead><tr><th>阶级</th><th>配方</th><th>机器</th><th>输入</th><th>输出</th><th>循环次数</th><th>机时</th><th>电耗</th></tr></thead><tbody>`;
  cycEntries.forEach(([rid,c])=>{
    const r=c.recipe;
    const mainItem = r.outputs.find(o=>o.amount>0);
    const tier = itemOf(mainItem?.item)?.tier ?? 0;
    const sec = c.cycles * r.cycle;
    const kwh = sec * r.power / 3600;
    h+=`<tr>
      <td>${tierTag(tier)}</td>
      <td>${r.name}</td>
      <td><span class="pill">${machineOf(r.machine)?.name||'?'}</span></td>
      <td>${r.inputs.map(i=>`<span class="pill">${itemOf(i.item)?.name||i.item} ×${fmtNum(c.cycles*i.amount)}</span>`).join(' ')}</td>
      <td>${r.outputs.filter(o=>o.amount>0).map(o=>`<span class="pill" style="background:var(--accent-soft);color:#0f6e56">${itemOf(o.item)?.name||o.item} ×${fmtNum(c.cycles*o.amount)}</span>`).join(' ')}</td>
      <td><code>${fmtNum(c.cycles)}</code></td>
      <td><code>${fmtNum(sec)}s</code></td>
      <td><code>${fmtNum(kwh)}</code></td>
    </tr>`;
  });
  h+=`</tbody></table></div>`;

  // 副产物
  const byp = Object.entries(u.byproducts).filter(([,v])=>v>1e-9).sort((a,b)=>b[1]-a[1]);
  if(byp.length){
    h+=`<div style="margin-top:14px"><div style="font-size:12px;font-weight:500;margin-bottom:6px">每单位副产物（可回收/需处理）</div>
      <div>${byp.map(([id,v])=>{
        const r=itemOf(id);
        return `<span class="pill" style="margin-right:6px">${r?.name||id} ×${fmtNum(v)}</span>`;
      }).join('')}</div></div>`;
  }
  h+=`</div>`;

  /* ---------- ③ 反向换算：要 N 个 ---------- */
  if(amount>0){
    const b = backwardToRaws(targetId, amount);
    h+=`<div class="card">
      <h3>③ 反向换算 · 要产出 ${fmtNum(amount)} 个「${it.name}」</h3>
      <p class="hint">完整采购/开采清单。按这个备料，理论上刚好够。</p>
      <div class="scroll-x"><table>
        <thead><tr><th>基础原料</th><th>需要总量</th><th>按单条传送带 Mk3 折算</th></tr></thead><tbody>`;
    b.rawList.forEach(x=>{
      const r=itemOf(x.id);
      // 假设 1 分钟为交付窗口，Mk3 = 120/分
      h+=`<tr>
        <td><span class="swatch" style="background:${r?.color||'#999'}"></span>${r?.name||x.id}</td>
        <td><code>${fmtNum(x.amount)}</code></td>
        <td><code>${fmtNum(x.amount/120)}</code> 分钟 @120/分</td>
      </tr>`;
    });
    h+=`</tbody></table></div>
      <div style="display:flex;gap:18px;margin-top:12px;flex-wrap:wrap;font-size:12px">
        <div><span style="color:var(--text-3)">总机时</span> <strong>${fmtNum(b.totalMachineSeconds)}</strong> 秒</div>
        <div><span style="color:var(--text-3)">总电耗</span> <strong>${fmtNum(b.totalPower)}</strong> kWh</div>
        <div><span style="color:var(--text-3)">机器总占用</span> <strong>${fmtNum(b.totalMachineSeconds/60)}</strong> 机器·分钟</div>
      </div>
    </div>`;
  }

  /* ---------- ④ 正向换算：有原料能产多少 ---------- */
  const rawIds = Object.keys(u.raws);
  if(rawIds.length){
    // 默认库存：精确给「刚好能产 10 个」的量，比例一致，初始结果就是 10
    const defaultFor = id => Math.round(u.raws[id] * 10 * 1000) / 1000;
    if(!FWD_INPUTS[targetId]) {
      FWD_INPUTS[targetId] = {};
      rawIds.forEach(id=>{ FWD_INPUTS[targetId][id] = defaultFor(id); });
    }
    rawIds.forEach(id=>{
      if(FWD_INPUTS[targetId][id]===undefined) FWD_INPUTS[targetId][id] = defaultFor(id);
    });

    const avail = FWD_INPUTS[targetId];
    const fwd = forwardFromRaws(targetId, avail);

    h+=`<div class="card">
      <h3>④ 正向换算 · 有多少料，能产几个「${it.name}」</h3>
      <p class="hint">改任意一个原料的数量，立刻重算。产量受<strong>最短缺的那个原料</strong>限制。</p>
      <div class="scroll-x"><table>
        <thead><tr><th>基础原料</th><th>每单位需要</th><th>你的库存</th><th>可产数量</th><th>状态</th></tr></thead><tbody>`;
      fwd.detail.forEach(d=>{
        const r=itemOf(d.id);
        const isTied = fwd.tied.length > 1;
        // 唯一瓶颈才标红；多种原料同时配套时显示"配套"，避免满屏红
        const status = !d.isBottleneck
          ? `<span class="tag" style="background:var(--accent-soft);color:#0f6e56">充足</span>`
          : isTied
            ? `<span class="tag" style="background:var(--amber-soft);color:#854f0b">配套</span>`
            : `<span class="tag" style="background:var(--red-soft);color:#a32d2d">瓶颈</span>`;
        const rowBg = (d.isBottleneck && !isTied) ? 'background:var(--red-soft)' : '';
        h+=`<tr style="${rowBg}">
          <td><span class="swatch" style="background:${r?.color||'#999'}"></span>${r?.name||d.id}</td>
          <td><code>${fmtNum(d.perUnit)}</code></td>
          <td><input type="number" min="0" step="10" data-fwd="${d.id}" value="${d.avail}"
               style="width:100px;padding:3px 6px;font-size:11px"></td>
          <td><code>${fmtNum(d.canMake)}</code></td>
          <td>${status}</td>
        </tr>`;
      });
      h+=`</tbody></table></div>`;

      h+=`<div style="margin-top:16px;padding:14px 16px;background:var(--accent-soft);border-radius:10px;
            display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        <div>
          <div style="font-size:11px;color:#0f6e56">按当前库存最多能产出</div>
          <div style="font-size:26px;font-weight:500;font-family:var(--mono);color:#04342c;line-height:1.2">${fmtNum(fwd.maxProduce)}</div>
          <div style="font-size:11px;color:#0f6e56">个 ${it.name}</div>
        </div>
        ${fwd.bottleneck?`<div style="border-left:1px solid rgba(15,110,86,.3);padding-left:14px">
          <div style="font-size:11px;color:#0f6e56">${fwd.tied.length>1?`并列瓶颈（${fwd.tied.length} 种配套）`:'瓶颈原料'}</div>
          <div style="font-size:14px;font-weight:500;color:#04342c">${fwd.tied.map(t=>itemOf(t.id)?.name).join(' / ')}</div>
          <div style="font-size:11px;color:#0f6e56">每再补 ${fmtNum(u.raws[fwd.bottleneck]||1)} 个可多产 1 个</div>
        </div>`:''}
      </div>
      <div style="margin-top:10px;font-size:11px;color:var(--text-3)">
        提示：这里只按「新开采的原料」计算，未抵扣副产物。实际产线中副产物若能回收可降低成本。
      </div>
    </div>`;
  }

  /* ---------- ⑤ 全局成本排行 ---------- */
  h += renderCostRanking(targetId);
  out.innerHTML = h;

  // 统一绑定量输入（只绑一次，避免重建丢失）
  out.querySelectorAll('[data-fwd]').forEach(inp=>{
    inp.oninput = ()=>{
      FWD_INPUTS[targetId][inp.dataset.fwd] = parseFloat(inp.value)||0;
      runBalanceKeepFocus(inp.dataset.fwd);
    };
  });
}

// 重算但保持输入框焦点
let _focusField = null;
function runBalanceKeepFocus(field){
  _focusField = field;
  runBalance();
  requestAnimationFrame(()=>{
    if(!_focusField) return;
    const el = document.querySelector(`[data-fwd="${_focusField}"]`);
    if(el){ el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    _focusField = null;
  });
}

/* ---------- 全局原料成本排行 ---------- */
function renderCostRanking(currentTarget){
  const rows = S.items
    .filter(i=>['part','material','module','mega','ingot','concentrate'].includes(i.type))
    .map(i=>{
      const u = unitCost(i.id);
      const rawTotal = Object.values(u.raws).reduce((s,v)=>s+v,0);
      return {item:i, rawTotal, rawKinds:Object.keys(u.raws).length,
              steps:Object.keys(u.cycles).length, kwh:u.totalPower, ok:Object.keys(u.raws).length>0};
    })
    .filter(x=>x.ok)
    .sort((a,b)=>b.rawTotal-a.rawTotal);

  if(!rows.length) return '';
  const maxRaw = rows[0].rawTotal;

  let h=`<div class="card">
    <h3>⑤ 全局原料成本排行</h3>
    <p class="hint">所有可制造物品的「每单位基础原料总量」，从高到低。用来检查数值曲线是否有断层。</p>
    <div class="scroll-x"><table>
      <thead><tr><th>物品</th><th>阶级</th><th>原料总量</th><th>原料种类</th><th>工序数</th><th>电耗 kWh</th><th>相对成本</th></tr></thead><tbody>`;
  rows.forEach(x=>{
    const pct = maxRaw>0 ? x.rawTotal/maxRaw*100 : 0;
    const isCur = x.item.id===currentTarget;
    h+=`<tr style="${isCur?'background:var(--accent-soft)':''}">
      <td><span class="swatch" style="background:${x.item.color}"></span>${x.item.name}${isCur?' ←':''}</td>
      <td>${tierTag(x.item.tier)}</td>
      <td><code>${fmtNum(x.rawTotal)}</code></td>
      <td><code>${x.rawKinds}</code></td>
      <td><code>${x.steps}</code></td>
      <td><code>${fmtNum(x.kwh)}</code></td>
      <td><div style="background:var(--purple);height:8px;border-radius:3px;width:${Math.max(2,pct*1.2)}px;opacity:.5"></div></td>
    </tr>`;
  });
  h+=`</tbody></table></div></div>`;
  return h;
}

// 取整到人类友好的数（1/2/5 × 10^n）
function niceRound(n){
  if(!(n>0)) return 0;
  const mag = Math.pow(10, Math.floor(Math.log10(n)));
  const norm = n / mag;
  let pick;
  if(norm <= 1) pick = 1;
  else if(norm <= 2) pick = 2;
  else if(norm <= 5) pick = 5;
  else pick = 10;
  return pick * mag;
}

// 数字格式化：大了用 k/M，小了保留有效位
function fmtNum(n){
  if(n===null||n===undefined||!isFinite(n)) return '—';
  const a=Math.abs(n);
  if(a===0) return '0';
  if(a>=1e6) return (n/1e6).toFixed(2)+'M';
  if(a>=1e4) return (n/1e3).toFixed(1)+'k';
  if(a>=100) return n.toFixed(0);
  if(a>=10) return n.toFixed(1);
  if(a>=1) return n.toFixed(2);
  if(a>=0.01) return n.toFixed(3);
  return n.toExponential(1);
}
