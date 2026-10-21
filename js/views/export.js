/* Forgeworks · js/views/export.js */
/* ---------- 导出 ---------- */
function renderExport(){
  const v=document.getElementById('view');
  v.innerHTML=`
  <div class="grid2">
    <div class="card">
      <h3>JSON 完整数据</h3>
      <p class="hint">包含全部五类数据。可用于版本管理、diff、CI 校验。</p>
      <button class="primary" id="exJson">下载 JSON</button>
      <button id="exJsonCopy">复制到剪贴板</button>
    </div>
    <div class="card">
      <h3>UE DataTable CSV</h3>
      <p class="hint">每张表一个 CSV，列名对齐 UE DataTable 字段。放入 Content/Data/ 后用 DataTable 导入器载入。</p>
      <button id="exCsvItem">DT_ItemDef.csv</button>
      <button id="exCsvMachine">DT_MachineDef.csv</button>
      <button id="exCsvRecipe">DT_RecipeDef.csv</button>
      <button id="exCsvTech">DT_TechDef.csv</button>
      <button id="exCsvElement">DT_ElementDef.csv</button>
      <button id="exCsvAll">全部打包（逐个下载）</button>
    </div>
    <div class="card">
      <h3>Markdown 速查表</h3>
      <p class="hint">生成与《配方速查表》同格式的文档。</p>
      <button class="primary" id="exMd">下载 配方速查表.md</button>
    </div>
    <div class="card">
      <h3>导入</h3>
      <p class="hint">导入此前导出的 JSON，将覆盖当前全部数据（建议先保存）。</p>
      <input type="file" id="exImport" accept=".json" style="font-size:11px">
    </div>
  </div>
  <div class="card">
    <h3>UE 侧接入说明</h3>
    <p class="hint">推荐的 DataTable 结构与导入步骤</p>
    <div class="scroll-x"><table><thead><tr><th>表名</th><th>对应结构体</th><th>关键字段</th><th>行数</th></tr></thead><tbody>
      <tr><td><code>DT_ItemDef</code></td><td><code>FItemDef</code></td><td>Id / DisplayName / Tier / Type / Value / Color<br>HasCustomIcon / MeshPath / MaterialPath / ModelStatus</td><td><code>${S.items.length}</code></td></tr>
      <tr><td><code>DT_MachineDef</code></td><td><code>FMachineDef</code></td><td>Id / DisplayName / Tier / Footprint / PowerDraw</td><td><code>${S.machines.length}</code></td></tr>
      <tr><td><code>DT_RecipeDef</code></td><td><code>FRecipeDef</code></td><td>Id / MachineType / Inputs[] / Outputs[] / CycleTime</td><td><code>${S.recipes.length}</code></td></tr>
      <tr><td><code>DT_TechDef</code></td><td><code>FTechDef</code></td><td>Id / Cost / Prerequisites[] / Unlocks[]</td><td><code>${S.techs.length}</code></td></tr>
      <tr><td><code>DT_ElementDef</code></td><td><code>FElementDef</code></td><td>Id / Symbol / Name / Color / Tier</td><td><code>${S.elements.length}</code></td></tr>
    </tbody></table></div>
    <div style="margin-top:12px;font-size:11.5px;color:var(--text-2);background:var(--panel-2);
         padding:10px 12px;border-radius:8px">
      <strong>图标贴图不在 CSV 里。</strong>图标走图集方案：先到「资源」页导出
      <code>IconSheet.png</code> + <code>IconAtlas.json</code>，再把 PNG 导入为 Texture2D，
      用 UV 坐标取子区域。CSV 里的 <code>HasCustomIcon</code> 只是标记是否有手绘图标。
    </div>
  </div>`;

  document.getElementById('exJson').onclick=()=>{
    download('StellarEra_Content.json', JSON.stringify(S,null,2), 'application/json');
  };
  document.getElementById('exJsonCopy').onclick=()=>{
    copyText(JSON.stringify(S,null,2));
  };
  document.getElementById('exCsvItem').onclick=()=>dlCsv('DT_ItemDef', itemCsv());
  document.getElementById('exCsvMachine').onclick=()=>dlCsv('DT_MachineDef', machineCsv());
  document.getElementById('exCsvRecipe').onclick=()=>dlCsv('DT_RecipeDef', recipeCsv());
  document.getElementById('exCsvTech').onclick=()=>dlCsv('DT_TechDef', techCsv());
  document.getElementById('exCsvElement').onclick=()=>dlCsv('DT_ElementDef', elementCsv());
  document.getElementById('exCsvAll').onclick=()=>{
    dlCsv('DT_ItemDef', itemCsv()); setTimeout(()=>dlCsv('DT_MachineDef', machineCsv()),250);
    setTimeout(()=>dlCsv('DT_RecipeDef', recipeCsv()),500);
    setTimeout(()=>dlCsv('DT_TechDef', techCsv()),750);
    setTimeout(()=>dlCsv('DT_ElementDef', elementCsv()),1000);
  };
  document.getElementById('exMd').onclick=()=>download('配方速查表.md', mdExport(), 'text/markdown');
  document.getElementById('exImport').onchange=e=>{
    const f=e.target.files[0]; if(!f) return;
    const rd=new FileReader();
    rd.onload=()=>{ try{
        const p=JSON.parse(rd.result);
        if(!p.items||!p.recipes) throw new Error('格式不符');
        S=p; saveState(); clearCostCache(); clearIconCache(); FWD_INPUTS={}; render(); toast('导入成功');
      }catch(err){ toast('导入失败：'+err.message); } };
    rd.readAsText(f);
  };
}
