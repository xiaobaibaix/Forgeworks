/* Forgeworks · js/core/lookup.js */
/* ---------- 索引 ---------- */
function idx(arr, key='id'){ const m={}; arr.forEach(x=>m[x[key]]=x); return m; }
function itemOf(id){ return S.items.find(x=>x.id===id); }
function machineOf(id){ return S.machines.find(x=>x.id===id); }
function recipeById(id){ return S.recipes.find(x=>x.id===id); }
