/* Forgeworks · js/engines/solver.js */
/* ---------- 产线求解器 ---------- */
// 可选：指定某些物品用哪条配方产出
let SOLVE_OVERRIDES = {};   // { itemId: recipeId }

function solve(targetId, targetRate){
  const issues=[]; const tree=[];
  const visited=new Set();
  const producersOf = id => S.recipes.filter(r=>r.outputs.some(o=>o.amount>0 && o.item===id));

  function expand(itemId, rate, depth, chain){
    const prods = producersOf(itemId);
    if(!prods.length){ issues.push({lv:'warn',msg:`「${itemOf(itemId)?.name||itemId}」无产出配方，视为外部供给`}); return; }
    // 选配方：优先用覆盖指定，否则选"单位速率最高"的那条
    let r;
    if(SOLVE_OVERRIDES[itemId]){
      r = recipeById(SOLVE_OVERRIDES[itemId]);
      if(!r || !prods.includes(r)){ issues.push({lv:'warn',msg:`物品「${itemOf(itemId)?.name}」的指定配方无效，回退自动选择`}); r=null; }
    }
    if(!r){
      const scored = prods.map(p=>{
        const main = p.outputs.find(o=>o.item===itemId && o.amount>0);
        const outAmt = p.outputs.filter(o=>o.amount>0).reduce((s,o)=>s+o.amount,0);
        return {p, rate: outAmt*60/p.cycle};
      }).sort((a,b)=>b.rate-a.rate);
      r = scored[0].p;
      if(prods.length>1) issues.push({lv:'info',msg:`「${itemOf(itemId)?.name}」有 ${prods.length} 条产出配方，已选速率最高的「${r.name}」（${scored[0].rate.toFixed(1)}/分）`});
    }
    const mainOut = r.outputs.find(o=>o.item===itemId && o.amount>0);
    if(!mainOut) return;
    const perCycleMain = mainOut.amount;
    const cyclesNeeded = rate / perCycleMain;         // 需要的循环数(次/分)
    const machines = Math.ceil(cyclesNeeded * r.cycle / 60);
    const power = machines * r.power;

    const node = {recipe:r, machines, power, rate, depth, kids:[], chain:[...chain, r.id]};
    tree.push(node);

    // 循环检测
    const key = r.id+'@'+itemId;
    if(visited.has(key)){
      issues.push({lv:'warn',msg:`检测到循环依赖，涉及 ${r.id}`}); return;
    }
    visited.add(key);

    r.inputs.forEach(inp=>{
      const inRate = cyclesNeeded * inp.amount;
      const kid = expand(inp.item, inRate, depth+1, node.chain);
      if(kid) node.kids.push(kid);
    });
    visited.delete(key);
    return node;
  }
  const root = expand(targetId, targetRate, 0, []);
  // 汇总
  const byRecipe = {};
  tree.forEach(n=>{
    const k=n.recipe.id;
    if(!byRecipe[k]) byRecipe[k]={recipe:n.recipe, machines:0, power:0, rate:0};
    byRecipe[k].machines += n.machines; byRecipe[k].power += n.power; byRecipe[k].rate += n.rate;
  });
  const totalPower = Object.values(byRecipe).reduce((s,x)=>s+x.power,0);
  return {root, tree, byRecipe, totalPower, issues, targetId, targetRate};
}
