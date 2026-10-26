const PIPELINE_TEMPLATES = [
  {id:'machine',label:'机器',kind:'machine',imageCredits:[5,5],modelCredits:[30,30]},
  {id:'item',label:'物品',kind:'item',imageCredits:[5,5],modelCredits:[30,30]},
  {id:'parts',label:'分件装配',kind:'machine',imageCredits:[20,35],modelCredits:[160,240]},
  {id:'icon',label:'图标',kind:'icon',imageCredits:[5,10],modelCredits:[0,0]},
];

function pipelineEstimate(templateId, count){
  const template=PIPELINE_TEMPLATES.find(item=>item.id===templateId)||PIPELINE_TEMPLATES[0];
  const assets=Math.max(0,Number(count)||0);
  const low=(template.imageCredits[0]+template.modelCredits[0])*assets;
  const high=(template.imageCredits[1]+template.modelCredits[1])*assets;
  return {assets,lowCredits:low,highCredits:high,lowUsd:low/100,highUsd:high/100};
}
