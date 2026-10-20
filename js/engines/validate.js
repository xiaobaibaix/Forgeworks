/* Forgeworks · js/engines/validate.js */
/* ---------- 校验 ---------- */
function validate(){
  const issues = [];
  const err=(m,loc)=>issues.push({lv:'err',msg:m,loc:loc||''});
  const warn=(m,loc)=>issues.push({lv:'warn',msg:m,loc:loc||''});
  const info=(m,loc)=>issues.push({lv:'info',msg:m,loc:loc||''});

  // ID 唯一
  for(const coll of ['items','machines','recipes','techs','elements']){
    const seen={};
    S[coll].forEach(x=>{
      if(seen[x.id]) err(`重复 ID "${x.id}"`, coll);
      seen[x.id]=1;
      // 元素允许化学符号格式（Fe / He3 / H2O），其余要求全大写
      if(coll==='elements'){
        // 允许化学符号（Fe / He3 / H2O）与游戏自定义族名（REE）
        if(!/^([A-Z][a-z]?\d*|[A-Z][A-Z0-9]*)$/.test(x.id)) warn(`元素 ID "${x.id}" 不符合化学符号格式`, coll);
      } else if(!/^[A-Z][A-Z0-9_]*$/.test(x.id)){
        warn(`ID "${x.id}" 不符合大写命名规范`, coll);
      }
    });
  }

  // 配方引用完整性
  S.recipes.forEach(r=>{
    if(!machineOf(r.machine)) err(`配方「${r.name}」引用了不存在的机器 ${r.machine}`, r.id);
    if(r.cycle<=0) err(`配方「${r.name}」周期必须 > 0`, r.id);
    if(r.power<0) err(`配方「${r.name}」耗电不能为负`, r.id);
    if(!r.inputs.length) err(`配方「${r.name}」没有任何输入`, r.id);
    if(!r.outputs.length) err(`配方「${r.name}」没有任何输出`, r.id);
    r.inputs.forEach(i=>{ if(!itemOf(i.item)) err(`配方「${r.name}」输入引用不存在的物品 ${i.item}`, r.id); });
    r.outputs.forEach(o=>{ if(o.amount>0 && !itemOf(o.item)) err(`配方「${r.name}」输出引用不存在的物品 ${o.item}`, r.id); });
  });

  // 速率一致性：单位产出耗电（按 tier 内相对比较，避免误报高阶配方）
  const byTierEnergy = {};
  S.recipes.forEach(r=>{
    const outAmt = r.outputs.filter(o=>o.amount>0).reduce((s,o)=>s+o.amount,0);
    if(outAmt<=0 || r.power<=0) return;
    const rate = outAmt*60/r.cycle;
    const perUnit = r.power/rate;
    const t = r.tier;
    (byTierEnergy[t] = byTierEnergy[t]||[]).push(perUnit);
  });
  Object.values(byTierEnergy).forEach(arr=>{
    arr.sort((a,b)=>a-b);
    arr.med = arr[Math.floor(arr.length/2)];
  });
  S.recipes.forEach(r=>{
    const outAmt = r.outputs.filter(o=>o.amount>0).reduce((s,o)=>s+o.amount,0);
    if(outAmt<=0) return;
    const rate = outAmt*60/r.cycle;
    const perUnit = r.power/rate;
    const med = byTierEnergy[r.tier]?.med;
    if(med && perUnit > med*8){
      warn(`配方「${r.name}」单位能耗 ${perUnit.toFixed(1)} kW/(个/分)，是同 tier 中位数的 ${(perUnit/med).toFixed(0)} 倍`, r.id);
    }
    if(perUnit > 0 && perUnit < med*0.05){
      info(`配方「${r.name}」单位能耗 ${perUnit.toFixed(3)} 仅为同 tier 中位数的 ${(perUnit/med*100).toFixed(0)}%，检查是否漏填耗电`, r.id);
    }
  });

  // 物品可获得性
  const producers = {};
  S.recipes.forEach(r=>r.outputs.forEach(o=>{
    if(o.amount<=0) return;
    (producers[o.item] = producers[o.item]||[]).push(r);
  }));
  // 原料类型：由采集机器直接产出，不需要配方
  const sourceItems = new Set(S.items.filter(i=>i.type==='raw').map(i=>i.id));
  S.items.forEach(it=>{
    if(!producers[it.id] && !sourceItems.has(it.id)){
      err(`物品「${it.name}」无任何产出配方且不是原料`, it.id);
    }
    // 反向检查：标为原料却有产出配方
    if(it.type==='raw' && producers[it.id] && producers[it.id].length){
      const realProducers = producers[it.id].filter(p=>p.cat!=='回收');
      if(realProducers.length){
        warn(`物品「${it.name}」标为原料，但配方「${realProducers[0].name}」能生产它 —— ` +
             `若是加工产物应改为「精矿/锭」`, it.id);
      } else {
        info(`物品「${it.name}」是原料，另有回收配方「${producers[it.id][0].name}」可闭环补充（合理）`, it.id);
      }
    }
  });
  // 一致性：一个物品有多个产出配方（分支）— 提示
  S.items.forEach(it=>{
    if(producers[it.id] && producers[it.id].length>1){
      info(`物品「${it.name}」有 ${producers[it.id].length} 条产出配方（分支设计）`, it.id);
    }
  });

  // 副产物必须有去向
  const consumed = new Set();
  S.recipes.forEach(r=>r.inputs.forEach(i=>consumed.add(i.item)));
  S.recipes.forEach(r=>{
    const main = r.outputs.filter(o=>o.amount>0);
    if(main.length>1){
      main.slice(1).forEach(o=>{
        if(!consumed.has(o.item)) warn(`副产物「${itemOf(o.item)?.name||o.item}」没有任何配方消耗它`, r.id);
      });
    }
  });

  // Tier 连续性：允许原料直跳一级（压缩设计），但中间级跳跃要提示
  const rawTierSet = new Set(S.items.filter(i=>i.type==='raw').map(i=>i.tier));
  S.recipes.forEach(r=>{
    const outs = r.outputs.filter(o=>o.amount>0);
    if(!outs.length) return;
    const outTier = Math.min(...outs.map(o=>itemOf(o.item)?.tier??0));
    const inTiers = r.inputs.map(i=>({tier:itemOf(i.item)?.tier??0, isRaw:(itemOf(i.item)?.type==='raw')}));
    const maxIn = Math.max(...inTiers.map(x=>x.tier));
    if(outTier - maxIn > 1){
      const allRaw = inTiers.every(x=>x.isRaw);
      const lv = allRaw ? 'info' : 'warn';
      const msg = allRaw
        ? `配方「${r.name}」原料直跳 T${maxIn}→T${outTier}（压缩设计，确认这是有意的）`
        : `配方「${r.name}」跨级过多（T${maxIn}→T${outTier}），中间加工层可能缺失`;
      (lv==='info'?info:warn)(msg, r.id);
    }
  });

  // 科技树
  S.techs.forEach(t=>{
    t.unlocks.forEach(u=>{ if(!recipeById(u)) err(`科技「${t.name}」解锁了不存在的配方 ${u}`, t.id); });
    t.prereqs.forEach(p=>{ if(!S.techs.find(x=>x.id===p)) err(`科技「${t.name}」的前置科技 ${p} 不存在`, t.id); });
    if(t.cost<=0) warn(`科技「${t.name}」研究成本 <= 0`, t.id);
  });
  // 科技循环（用 DFS 三色标记，只在回边时报告）
  const techState = {};
  function techDfs(id, path){
    if(techState[id]===1){ err(`科技依赖存在循环：${[...path, id].join(' → ')}`, id); return; }
    if(techState[id]===2) return;
    techState[id]=1; path.push(id);
    const tech = S.techs.find(x=>x.id===id);
    if(tech) tech.prereqs.forEach(p=>{ if(S.techs.some(x=>x.id===p)) techDfs(p, path); });
    path.pop(); techState[id]=2;
  }
  S.techs.forEach(t=>techDfs(t.id, []));

  // 配方循环依赖（物品级）
  const graph = {};
  S.recipes.forEach(r=>{
    const outs = r.outputs.filter(o=>o.amount>0).map(o=>o.item);
    r.inputs.forEach(i=>{ (graph[i.item]=graph[i.item]||[]).push(...outs); });
  });
  const state={}, stack=[];
  function dfs(n){
    if(state[n]===1){ err(`配方存在循环依赖：${[...stack, n].join(' → ')}`, n); return; }
    if(state[n]===2) return;
    state[n]=1; stack.push(n);
    (graph[n]||[]).forEach(m=>{ if(!state[m]) dfs(m); });
    stack.pop(); state[n]=2;
  }
  Object.keys(graph).forEach(n=>{ if(!state[n]) dfs(n); });

  // 纪元覆盖
  S.eras.forEach(e=>{
    e.elements.forEach(el=>{ if(!S.elements.find(x=>x.id===el)) warn(`纪元 ${e.id} 引用了不存在的元素 ${el}`, e.id); });
  });

  return issues;
}
