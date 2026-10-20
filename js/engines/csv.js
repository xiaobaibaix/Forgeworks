/* Forgeworks · js/engines/csv.js */
/* ---------- CSV 构造 ---------- */
function csvCell(v){
  const s=String(v==null?'':v);
  return /[",\n]/.test(s) ? '"'+s.replace(/"/g,'""')+'"' : s;
}
function csvRows(headers, rows){
  return [headers.map(csvCell).join(',')].concat(rows.map(r=>r.map(csvCell).join(','))).join('\n');
}
function itemCsv(){
  return csvRows(['Id','DisplayName','Tier','Type','Value','Color','Desc','HasCustomIcon','MeshPath','MaterialPath','ModelStatus'],
    S.items.map(i=>[
      i.id, i.name, i.tier, i.type, i.value, i.color, i.desc||'',
      (i.icon && i.icon.trim()) ? 'True' : 'False',
      i.mesh||'', i.mat||'', i.modelStatus||'primitive',
    ]));
}
function elementCsv(){
  return csvRows(['Id','Symbol','DisplayName','Tier','Color'],
    S.elements.map(e=>[e.id,e.symbol,e.name,e.tier,e.color]));
}
function machineCsv(){
  return csvRows(['Id','DisplayName','Tier','Category','FootprintX','FootprintY','PowerDraw','Desc'],
    S.machines.map(m=>{
      const [a,b]=(m.footprint||'1x1').split(/[×xX]/);
      return [m.id,m.name,m.tier,m.cat,parseInt(a)||1,parseInt(b)||1,m.power,m.desc||''];
    }));
}
function recipeCsv(){
  // UE DataTable CSV 数组语法：
  //   TArray<FItemAmount> → ((ItemId="ORE_FE",Amount=2.0),(ItemId="X",Amount=1.0))
  //   注意：内层引号由 CSV 自身的转义处理（""），不要在值里手写 \"
  const fmtItems=arr=>'('+arr.filter(o=>o.amount>0)
    .map(o=>`(ItemId="${o.item}",Amount=${o.amount})`).join(',')+')';
  return csvRows(['Id','DisplayName','MachineType','Category','Tier','CycleTime','PowerDraw','TierUnlock','Inputs','Outputs','Desc'],
    S.recipes.map(r=>[
      r.id,r.name,r.machine,r.cat,r.tier,r.cycle,r.power,r.unlock,
      fmtItems(r.inputs),fmtItems(r.outputs),r.desc||''
    ]));
}
function techCsv(){
  // TArray<FString> → ("T_E0_BASIC","T_E1_BRINE")
  const fmtStrs=arr=>'('+arr.map(s=>`"${s}"`).join(',')+')';
  return csvRows(['Id','DisplayName','Tier','Cost','Prerequisites','Unlocks','Desc'],
    S.techs.map(t=>[
      t.id,t.name,t.tier,t.cost,
      fmtStrs(t.prereqs),fmtStrs(t.unlocks),t.desc||''
    ]));
}
function mdExport(){
  let h='# StellarEra 配方速查表\n\n> 由内容设计器导出 · '+new Date().toLocaleString('zh-CN')+'\n\n';
  const cats=[...new Set(S.recipes.map(r=>r.cat))];
  cats.forEach(c=>{
    const rs=S.recipes.filter(r=>r.cat===c);
    h+=`\n## ${c}\n\n| Id | 配方 | 机器 | 输入 | 输出 | 周期 | 速率 | 耗电 | 解锁 |\n|---|---|---|---|---|---|---|---|---|\n`;
    rs.forEach(r=>{
      const outAmt=r.outputs.filter(o=>o.amount>0).reduce((s,o)=>s+o.amount,0);
      const rate=outAmt?((outAmt*60/r.cycle).toFixed(1)+'/min'):'—';
      h+=`| \`${r.id}\` | ${r.name} | ${machineOf(r.machine)?.name||'缺失'} | `+
        (r.inputs.map(i=>`${itemOf(i.item)?.name||i.item}×${i.amount}`).join(' + ')||'—')+' | '+
        (r.outputs.filter(o=>o.amount>0).map(o=>`${itemOf(o.item)?.name||o.item}×${o.amount}`).join(' + ')||'—')+
        ` | ${r.cycle}s | ${rate} | ${r.power}kW | ${r.unlock} |\n`;
    });
  });
  h+=`\n\n## 物品表\n\n| Id | 名称 | 等级 | 类型 | 价值 | 说明 |\n|---|---|---|---|---|---|\n`;
  S.items.forEach(i=>{ h+=`| \`${i.id}\` | ${i.name} | T${i.tier} | ${typeLabel(i.type)} | ${i.value} | ${i.desc||''} |\n`; });
  h+=`\n\n## 机器表\n\n| Id | 名称 | 分类 | 等级 | 占地 | 耗电 | 说明 |\n|---|---|---|---|---|---|---|\n`;
  S.machines.forEach(m=>{ h+=`| \`${m.id}\` | ${m.name} | ${m.cat} | T${m.tier} | ${m.footprint} | ${m.power}kW | ${m.desc||''} |\n`; });

  // 物料平衡附录
  h+=`\n\n## 物料平衡表\n\n> 每生产 1 个成品所需的基础原料总量。用于检查数值曲线。\n\n`;
  h+=`| 物品 | 等级 | 原料总量 | 原料种类 | 工序数 | 电耗kWh | 主要原料 |\n|---|---|---|---|---|---|---|\n`;
  const rows = S.items
    .filter(i=>['part','material','module','mega','concentrate','ingot'].includes(i.type))
    .map(i=>{
      const u = unitCost(i.id);
      const tot = Object.values(u.raws).reduce((s,v)=>s+v,0);
      const top = Object.entries(u.raws).sort((a,b)=>b[1]-a[1]).slice(0,3)
        .map(([id,v])=>`${itemOf(id)?.name||id}×${fmtNum(v)}`).join(', ');
      return {item:i, tot, kinds:Object.keys(u.raws).length, steps:Object.keys(u.cycles).length, kwh:u.totalPower, top};
    })
    .filter(x=>x.tot>0)
    .sort((a,b)=>a.item.tier - b.item.tier || b.tot - a.tot);
  rows.forEach(x=>{
    h+=`| ${x.item.name} | T${x.item.tier} | ${fmtNum(x.tot)} | ${x.kinds} | ${x.steps} | ${fmtNum(x.kwh)} | ${x.top} |\n`;
  });

  h+=`\n\n## 单件成本速查（T4/T5）\n\n`;
  const bigRows = rows.filter(x=>x.item.tier>=4);
  bigRows.forEach(x=>{
    const u = unitCost(x.item.id);
    h+=`### ${x.item.name}（T${x.item.tier}）\n\n`;
    h+=`- 基础原料：${Object.entries(u.raws).sort((a,b)=>b[1]-a[1])
      .map(([id,v])=>`${itemOf(id)?.name||id} ×${fmtNum(v)}`).join('，')}\n`;
    h+=`- 工序数：${Object.keys(u.cycles).length} 道，机时 ${fmtNum(u.totalMachineSeconds)} 秒，电耗 ${fmtNum(u.totalPower)} kWh\n`;
    const bp = Object.entries(u.byproducts).filter(([,v])=>v>1e-9);
    if(bp.length) h+=`- 副产物：${bp.map(([id,v])=>`${itemOf(id)?.name||id} ×${fmtNum(v)}`).join('，')}\n`;
    h+=`\n`;
  });

  return h;
}
