/* Forgeworks · js/engines/balance.js */
/* ---------- 物料平衡引擎 ----------
   思路：追踪「毛需求(gross need)」与「毛产出(gross produce)」，
   净需求 = 需求 - 产出。净需求 > 0 的物品必须从外部输入（原料/进口）。
   净需求 < 0 的是副产物盈余。
   ------------------------------------ */

// 选配方：优先覆盖指定，否则选主产出效率最高的
function pickRecipe(itemId, prods){
  if(SOLVE_OVERRIDES[itemId]){
    const r = recipeById(SOLVE_OVERRIDES[itemId]);
    if(r && prods.includes(r)) return r;
  }
  return prods.slice().sort((a,b)=>{
    const ao = a.outputs.find(o=>o.item===itemId&&o.amount>0);
    const bo = b.outputs.find(o=>o.item===itemId&&o.amount>0);
    // 每周期产出量高者优先；同则周期短者优先
    if(ao.amount !== bo.amount) return bo.amount - ao.amount;
    return a.cycle - b.cycle;
  })[0];
}

/**
 * 物料平衡展开
 * @param itemId 目标物品
 * @param amount 目标数量
 * @returns {
 *   need, produce, net,      // {itemId: amount}
 *   cycles,                  // {recipeId: {recipe, cycles}}
 *   raws,                    // 净需求的基础原料 {itemId: amount}
 *   byproducts,              // 副产物盈余 {itemId: amount}
 *   totalPower, totalMachineSeconds,
 *   blocked, depth, ok
 * }
 */
function expandAmount(itemId, amount, opts={}){
  const need={}, produce={}, cycles={}, blocked=new Set(), chainMax={depth:0};
  const producersOf = id => S.recipes.filter(r=>r.outputs.some(o=>o.amount>0 && o.item===id));

  function walk(id, amt, chain, depth){
    if(!(amt>1e-9)) return;
    chainMax.depth = Math.max(chainMax.depth, depth);
    need[id] = (need[id]||0) + amt;

    // 硬性叶子：type='raw' 的物品永远不再展开（即使它有回收配方）。
    // 语义依据：原料是由采集机器从地质中获得的，回收配方只是补充手段，
    // 不应改变"它需要从外部投入"这个事实。
    const def = itemOf(id);
    if(def && def.type === 'raw') return;

    const prods = producersOf(id);
    if(!prods.length) return;               // 叶子：外部供给

    if(chain.has(id)){ blocked.add(id); return; }  // 循环依赖，停止展开

    const r = pickRecipe(id, prods);
    const mainOut = r.outputs.find(o=>o.item===id && o.amount>0);
    if(!mainOut) return;

    const cyc = amt / mainOut.amount;
    if(!cycles[r.id]) cycles[r.id] = {recipe:r, cycles:0};
    cycles[r.id].cycles += cyc;

    r.outputs.filter(o=>o.amount>0).forEach(o=>{
      produce[o.item] = (produce[o.item]||0) + cyc*o.amount;
    });

    const nc = new Set(chain); nc.add(id);
    r.inputs.forEach(i=>walk(i.item, cyc*i.amount, nc, depth+1));
  }
  walk(itemId, amount, new Set(), 0);

  // 净需求
  const net={};
  new Set([...Object.keys(need), ...Object.keys(produce)]).forEach(id=>{
    const n = (need[id]||0) - (produce[id]||0);
    if(Math.abs(n) > 1e-9) net[id] = n;
  });

  // 净需求为正且（是原料类型 或 无产出配方）= 基础原料
  const raws={}, byproducts={};
  Object.entries(net).forEach(([id, v])=>{
    const def = itemOf(id);
    const isRawType = def && def.type === 'raw';
    const hasProducer = producersOf(id).length > 0;
    if(v > 0 && (isRawType || !hasProducer)) raws[id] = v;
    else if(v < 0) byproducts[id] = -v;
  });

  // 电耗与机时
  let totalPower=0, totalMachineSeconds=0;
  Object.values(cycles).forEach(c=>{
    const sec = c.cycles * c.recipe.cycle;          // 该配方总机时(秒)
    totalMachineSeconds += sec;
    totalPower += sec * c.recipe.power / 3600;      // kWh
  });

  return {need, produce, net, cycles, raws, byproducts,
          totalPower, totalMachineSeconds, blocked:[...blocked],
          depth:chainMax.depth, ok:blocked.size===0};
}

// 单位成本（每产出 1 个需要多少原料），带缓存
const _unitCostCache = {};
function unitCost(itemId){
  const key = itemId + '|' + (SOLVE_OVERRIDES[itemId]||'');
  if(!_unitCostCache[key]){
    _unitCostCache[key] = expandAmount(itemId, 1);
  }
  return _unitCostCache[key];
}
function clearCostCache(){ Object.keys(_unitCostCache).forEach(k=>delete _unitCostCache[k]); }

/**
 * 正向换算：给定原料库存，能产出多少目标物品
 * @param targetId 目标
 * @param rawAvail {itemId: availableAmount}
 * @returns {maxProduce, bottleneck, perUnit, detail:[{id, need, avail, canMake, isBottleneck}]}
 */
function forwardFromRaws(targetId, rawAvail){
  const u = unitCost(targetId);
  const detail = [];
  let maxProduce = Infinity, bottleneck = null;

  Object.entries(u.raws).forEach(([id, perUnit])=>{
    const avail = rawAvail[id] ?? 0;
    const canMake = perUnit > 0 ? avail / perUnit : Infinity;
    const d = {id, perUnit, avail, canMake};
    detail.push(d);
    if(canMake < maxProduce){ maxProduce = canMake; bottleneck = id; }
  });

  if(!detail.length) { maxProduce = 0; }
  // 并列瓶颈：完全配套时多个原料的 canMake 相同，都应该标记（含浮点容差）
  const eps = Math.max(1e-6, Math.abs(maxProduce) * 1e-6);
  const tied = detail.filter(d=>Math.abs(d.canMake - maxProduce) <= eps);
  detail.forEach(d=>{ d.isBottleneck = Math.abs(d.canMake - maxProduce) <= eps; });
  detail.sort((a,b)=>a.canMake - b.canMake);

  return {maxProduce: isFinite(maxProduce)?maxProduce:0, bottleneck, tied, perUnit:u, detail};
}

/**
 * 反向换算：要产出 N 个，需要多少原料
 * 其实就是 expandAmount 乘以 N（线性），但这里给出展示友好的结构
 */
function backwardToRaws(targetId, amount){
  const r = expandAmount(targetId, amount);
  const list = Object.entries(r.raws)
    .map(([id, v])=>({id, amount:v}))
    .sort((a,b)=>b.amount-a.amount);
  return {...r, rawList:list};
}
