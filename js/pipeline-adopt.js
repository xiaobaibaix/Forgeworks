/* Forgeworks · js/pipeline-adopt.js
 * Provider 任务成功后：把概念图/模型写进资产、导出到项目 _Source，并在配置了 UE 目标时发布。
 * 依赖：fw* GLB 工具、sync.js、pipeline.js。所有请求同源，不接触 Provider 原始接口。
 */
(function(){
  'use strict';

  function pipelineFindAsset(kind, assetId){
    if(kind === 'machine') return (S.machines || []).find(function(item){ return item.id === assetId; });
    if(kind === 'item') return (S.items || []).find(function(item){ return item.id === assetId; });
    return (S.elements || []).find(function(item){ return item.id === assetId; });
  }

  function iconPath(kind, assetId){
    return kind === 'machine' ? assetId + '_icon.png' : assetId + '.png';
  }

  /** 旧数据把上传图标回填成 iconSource:''，不能只看 'upload' 标记。 */
  function hasCustomIcon(asset){
    return !!(asset.icon && asset.icon.trim()) && asset.iconSource !== 'generated';
  }

  /** 资产与 manifest 只记录 basename；原始路径留在管线存档。 */
  function baseName(file){
    return String(file || '').replace(/\\/g, '/').split('/').pop();
  }

  function imageB64(dataUrl){
    const text = String(dataUrl || '');
    const comma = text.indexOf(',');
    if(comma < 0) throw new Error('图片数据为空');
    return text.slice(comma + 1);
  }

  function loadImage(url){
    return new Promise(function(resolve, reject){
      const img = new Image();
      img.crossOrigin = 'anonymous';       // Bridge 带 ACAO:*，file:// 页面也能读像素
      img.onload = function(){ resolve(img); };
      img.onerror = function(){ reject(new Error('图片加载失败')); };
      img.src = url;
    });
  }

  function cropSquare(img, size){
    const width = img.naturalWidth || img.width;
    const height = img.naturalHeight || img.height;
    const side = Math.min(width, height);
    if(!side) throw new Error('图片尺寸无效');
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d');
    if(!ctx) throw new Error('Canvas 不可用');
    ctx.drawImage(img, (width - side) / 2, (height - side) / 2, side, side, 0, 0, size, size);
    return canvas.toDataURL('image/png');
  }

  function modelMeta(asset){
    return {
      source: 'ai',
      provider: asset.model.provider || '',
      file: baseName(asset.model.file),
      taskId: asset.model.taskId || '',
      nodeId: asset.model.nodeId || '',
      generatedAt: asset.model.generatedAt || '',
      triangles: asset.model.triangles || 0,
      transform: fwNormalizeTransform(asset.model.transform),
      autoFit: asset.model.autoFit !== false,
    };
  }

  function adoptMeta(asset, kind){
    const style = getStyle();
    const styleMeta = {presetId: style.id, name: style.name};
    if(kind === 'machine'){
      const meta = {
        name: asset.name, category: asset.cat, footprint: asset.footprint, tier: asset.tier,
        style: {presetId: style.id, name: style.name, accent: accentFor(asset.cat, style)},
        contentHash: machineContentHash(asset),
        styleHash: machineStyleHash(asset),
        modelHash: machineModelHash(asset),
        iconSource: asset.iconSource || '',
        model: asset.model ? modelMeta(asset) : null,
      };
      // 没有模型时不要写入 triangles:0，避免图标导出覆盖已有 mesh 的统计
      if(asset.model) meta.triangles = asset.model.triangles || 0;
      return meta;
    }
    if(kind === 'item'){
      return {
        name: asset.name, type: asset.type, visual: asset.visual || null,
        tier: asset.tier, color: asset.color || '',
        customIcon: !!(asset.icon && asset.icon.trim()),
        iconSource: asset.iconSource || '', size: 256, style: styleMeta,
        iconHash: itemIconHash(asset), modelHash: itemModelHash(asset),
        model: asset.model ? modelMeta(asset) : null,
      };
    }
    return {
      name: asset.name, symbol: asset.symbol || '', tier: asset.tier, color: asset.color || '',
      customIcon: !!(asset.icon && asset.icon.trim()),
      iconSource: asset.iconSource || '', size: 256, style: styleMeta,
      iconHash: elementIconHash(asset),
    };
  }

  async function persistAsset(){
    if(typeof saveLocalState === 'function') saveLocalState();
    if(typeof syncSaveProjectNow !== 'function') return '';
    try{
      const saved = await syncSaveProjectNow();
      if(saved && saved.ok === false && !saved.skipped){
        return '项目内容保存失败，资产仅保存在浏览器本地';
      }
    }catch(_){
      return '项目内容保存失败，资产仅保存在浏览器本地';
    }
    return '';
  }

  async function exportAsset(asset, kind, files){
    try{
      await pipelineApi('export/asset', {
        kind: kind, id: asset.id, files: files, meta: adoptMeta(asset, kind),
      });
      const manifest = await syncLoadManifest();
      if(!manifest) return {ok:false, error:'导出后无法刷新项目清单'};
      return {ok:true};
    }catch(error){
      return {ok:false, error:error.message || String(error)};
    }
  }

  async function publishIfConfigured(assetId, kind){
    const target = typeof SYNC !== 'undefined' && SYNC.status && SYNC.status.ueTarget;
    if(!target) return {ok:true, skipped:true, reason:'no-target'};
    const rec = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[assetId];
    const need = kind === 'machine' ? ['mesh', 'icon'] : ['icon'];
    if(!rec || need.some(function(role){ return !hasAssetFile(rec, role); })){
      return {ok:true, skipped:true, reason:'not-ready'};
    }
    try{
      const result = await syncPublishUE([assetId]);
      if(result && result.ok) return result;
      const errors = result && Array.isArray(result.errors) ? result.errors : [];
      const first = errors.length
        ? (typeof errors[0] === 'string'
            ? errors[0]
            : (errors[0] && errors[0].error) || JSON.stringify(errors[0]))
        : '';
      return {ok:false, error: first || (result && result.error) || '发布失败'};
    }catch(error){
      return {ok:false, error: error && error.message ? error.message : String(error)};
    }
  }

  async function adoptImage(asset, kind, task, file, nodeId){
    // 自定义/上传图标永远优先；机器已有模型图标时概念图不覆盖。两者都不被概念图覆盖
    if(hasCustomIcon(asset)){
      return {ok:true, skipped:true, note:'已保留自定义图标，未用概念图覆盖'};
    }
    const machineHasModel = kind === 'machine' && !!asset.model;
    if(machineHasModel && asset.icon){
      return {ok:true, skipped:true, note:'机器已使用 AI 模型图标，概念图仅保留在管线存档'};
    }
    let icon, icon256;
    try{
      const img = await loadImage(pipelineOutputURLFor(asset.id, kind, file));
      icon = cropSquare(img, 128);        // 资产数据只存 128px
      icon256 = cropSquare(img, 256);     // 写入 _Source 的导出图
    }catch(error){
      return {ok:false, error:'读取概念图失败: ' + error.message};
    }
    const at = new Date().toISOString();
    const name = baseName(file);
    asset.icon = icon;
    asset.iconSource = 'generated';
    asset.generated = asset.generated || {};
    asset.generated.image = {
      taskId: task.taskId || '', nodeId: nodeId, at: at, file: name, from: 'image',
    };
    const saveWarning = await persistAsset();
    const exported = await exportAsset(asset, kind, {
      icon: {path: iconPath(kind, asset.id), b64: imageB64(icon256)},
    });
    if(!exported.ok) return Object.assign({}, exported, {applied:true});
    // 机器已有模型但没有图标（缩略图失败）时，明确这是概念图补的图标
    const result = machineHasModel
      ? {ok:true, note:'已用概念图补充机器图标（模型未提供图标）'}
      : {ok:true};
    if(saveWarning) result.warning = saveWarning;
    return result;
  }

  async function adoptModel(asset, kind, task, file, nodeId){
    if(kind === 'element') return {ok:false, error:'元素只支持图标，不支持 3D 模型'};
    const name = baseName(file);
    let scene, transform, baked;
    try{
      const response = await fetch(pipelineOutputURLFor(asset.id, kind, name));
      if(!response.ok) throw new Error('HTTP ' + response.status);
      scene = await fwLoadGLBScene(await response.arrayBuffer());
      transform = fwComputeFitTransform(scene, kind,
        kind === 'machine' ? asset.footprint : '');
      baked = await new Promise(function(resolve, reject){
        fwBakeGLBScene(scene, transform, {
          name: asset.id,
          forgeworks: {generator:'Forgeworks', source:'pipeline-ai',
                       id:asset.id, name:asset.name, kind:kind},
        }, function(result, error){
          if(error) reject(error); else resolve(result);
        });
      });
    }catch(error){
      return {ok:false, error:'处理模型失败: ' + error.message};
    }

    // 先统计并拒绝空模型，避免把零面模型写进资产后才在导出阶段失败
    let triangles = 0;
    try{ triangles = fwCountTriangles(scene); }
    catch(error){ return {ok:false, error:'统计模型三角面失败: ' + (error.message || String(error))}; }
    if(!(triangles > 0)) return {ok:false, error:'模型没有可导出的三角面'};

    // 缩略图失败不应丢弃已经烘焙好的模型：模型与 mesh 照常落地，图标稍后手动重试
    let thumb128 = '', thumb256 = '', thumb512 = '', thumbError = '';
    try{
      thumb128 = fwRenderGLBThumbnail(scene, transform, 128);
      thumb256 = fwRenderGLBThumbnail(scene, transform, 256);
      if(kind === 'machine') thumb512 = fwRenderGLBThumbnail(scene, transform, 512);
    }catch(error){
      thumbError = error.message || String(error);
      thumb128 = ''; thumb256 = ''; thumb512 = '';   // 部分失败时宁可都不写，避免空图标
    }

    const at = new Date().toISOString();
    asset.model = {
      source:'ai', provider: task.provider || '', file: name,
      taskId: task.taskId || '', nodeId: nodeId, generatedAt: at,
      transform: fwNormalizeTransform(transform), autoFit: true,
      triangles: triangles,
    };
    asset.generated = asset.generated || {};
    asset.generated.model = {
      taskId: task.taskId || '', nodeId: nodeId, at: at, file: name,
    };

    let iconChanged = false;
    if(thumb128 && kind === 'machine' && !hasCustomIcon(asset)){
      asset.icon = thumb128;
      asset.iconSource = 'generated';
      asset.generated.image = {
        taskId: task.taskId || '', nodeId: nodeId, at: at, file: name, from: 'model',
      };
      iconChanged = true;
    }else if(thumb128 && kind === 'item' && !(asset.icon && asset.icon.trim())){
      asset.icon = thumb128;
      asset.iconSource = 'generated';
      asset.generated.image = {
        taskId: task.taskId || '', nodeId: nodeId, at: at, file: name, from: 'model',
      };
      iconChanged = true;
    }

    const saveWarning = await persistAsset();
    const files = {mesh: {path: asset.id + '.glb', b64: bufToB64(baked)}};
    if(iconChanged){
      files.icon = {path: iconPath(kind, asset.id), b64: imageB64(thumb256)};
    }
    if(kind === 'machine' && thumb512){
      files.preview = {path: asset.id + '_preview.png', b64: imageB64(thumb512)};
    }
    const exported = await exportAsset(asset, kind, files);
    if(!exported.ok) return Object.assign({}, exported, {applied:true});
    const result = {ok:true, triangles: asset.model.triangles};
    result.warning = [thumbError ? '模型已应用，但缩略图生成失败：' + thumbError : '', saveWarning]
      .filter(Boolean).join('；') || undefined;
    return result;
  }

  async function adoptAsset(assetId, kind, slot, nodeId, task, file){
    const asset = pipelineFindAsset(kind, assetId);
    if(!asset) return {ok:false, error:'资产已删除: ' + assetId};
    const result = slot === 'image'
      ? await adoptImage(asset, kind, task, file, nodeId)
      : await adoptModel(asset, kind, task, file, nodeId);
    // skipped 表示本次没有改动资产（已有模型/上传图标），不应再触发导出
    if(!result.ok || result.skipped) return result;
    const published = await publishIfConfigured(asset.id, kind);
    if(!published.ok){
      return Object.assign({}, result, {
        warning:'已应用，但导出 UE 失败：' + (published.error || '未知错误'),
      });
    }
    if(published.skipped && published.reason === 'no-target'){
      const note = '已应用到项目（未设置 UE 目标）：' + asset.name;
      return Object.assign({}, result, {
        note: result.warning ? note + '（' + result.warning + '）' : note,
      });
    }
    if(published.skipped && published.reason === 'not-ready'){
      const note = '已应用到项目，但 UE 发布跳过：缺少网格或图标';
      return Object.assign({}, result, {
        warning: result.warning ? note + '；' + result.warning : note,
      });
    }
    return result;
  }

  function refreshExportNode(assetId, kind){
    if(cur !== 'pipeline' || PIPELINE.assetId !== assetId || PIPELINE.kind !== kind) return;
    if(!pipelineBridgeReady() || !PIPELINE.graph) return;
    const terminal = PIPELINE.graph.nodes.find(function(node){
      return node.type === 'export' || node.type === 'imageExport';
    });
    if(!terminal) return;
    pipelineApi('pipeline/run', {assetId:assetId, kind:kind, nodeId:terminal.id})
      .then(function(result){
        if(PIPELINE.assetId !== assetId || PIPELINE.kind !== kind) return;
        PIPELINE.graph = result.graph;
        renderPipelineView();
      })
      .catch(function(){ /* 导出节点刷新失败不影响已落地的资产 */ });
  }

  /** 早期失败不经队列；仍要写状态、留日志并提示，否则用户只看到“生成完成”。 */
  function reportApplyFailure(assetId, message, nodeId){
    PIPELINE.applyStatus[assetId] = '应用失败';
    PIPELINE.applyErrors[assetId] = message;
    PIPELINE.applyNodes[assetId] = nodeId;
    if(typeof syncLog === 'function') syncLog('自动应用失败：' + message, 'warn');
    toast('应用失败：' + message);
    if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
    return {ok:false, error:message};
  }

  /**
   * Provider 任务成功后的落地入口。
   * force=true 用于用户点“重新应用”；自动轮询按 generated.<slot>.taskId 幂等。
   */
  function pipelineAdoptTask(assetId, kind, nodeId, nodeType, task, force){
    if(!task || task.state !== 'success'){
      return Promise.resolve(reportApplyFailure(assetId, '任务尚未成功', nodeId));
    }
    if(nodeType !== 'textToImage' && nodeType !== 'imageTo3D' && nodeType !== 'decimate' && nodeType !== 'assemble'){
      return Promise.resolve({ok:true, skipped:true});
    }
    // 元素只支持图标：先于就绪检查跳过，避免误报“Bridge 未连接”
    const slot = nodeType === 'textToImage' ? 'image' : 'model';
    if(slot === 'model' && kind === 'element') return Promise.resolve({ok:true, skipped:true});
    if(typeof pipelineBridgeReady !== 'function' || !pipelineBridgeReady()){
      return Promise.resolve(reportApplyFailure(assetId, 'Bridge 未连接', nodeId));
    }
    if(typeof syncProjectReady !== 'function' || !syncProjectReady()){
      return Promise.resolve(reportApplyFailure(assetId, '未打开 Forgeworks 项目', nodeId));
    }
    const output = task.output || {};
    const file = slot === 'image' ? output.imagePath : output.modelPath;
    if(!file) return Promise.resolve(reportApplyFailure(assetId, '任务没有输出文件', nodeId));
    const asset = pipelineFindAsset(kind, assetId);
    if(!asset) return Promise.resolve(reportApplyFailure(assetId, '资产已删除: ' + assetId, nodeId));
    const done = asset.generated && asset.generated[slot];
    if(!force && done && done.taskId && done.taskId === task.taskId){
      return Promise.resolve({ok:true, skipped:true});
    }

    const key = kind + ':' + assetId;
    const previous = PIPELINE.applyQueue[key] || Promise.resolve();
    PIPELINE.applyStatus[assetId] = '应用中…';
    PIPELINE.applyErrors[assetId] = '';
    PIPELINE.applyNodes[assetId] = nodeId;
    if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();

    const next = previous.then(function(){
      // 排队期间前一次应用可能已完成，必须重新检查幂等，避免同一任务导出两次
      const latest = pipelineFindAsset(kind, assetId);
      const doneNow = latest && latest.generated && latest.generated[slot];
      if(!force && doneNow && doneNow.taskId && doneNow.taskId === task.taskId){
        return {ok:true, skipped:true, duplicate:true};
      }
      return adoptAsset(assetId, kind, slot, nodeId, task, file);
    }).then(function(result){
      if(!result.ok){
        PIPELINE.applyStatus[assetId] = result.applied ? '导出失败' : '应用失败';
        PIPELINE.applyErrors[assetId] = result.error || '未知错误';
        PIPELINE.applyNodes[assetId] = nodeId;
        if(typeof syncLog === 'function') syncLog('自动应用失败：' + PIPELINE.applyErrors[assetId], 'warn');
        toast((result.applied ? '已应用到资产，但导出失败：' : '应用失败：') + PIPELINE.applyErrors[assetId]);
        if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
        else render();
        return result;
      }
      if(result.duplicate){
        PIPELINE.applyStatus[assetId] = '已应用';
        PIPELINE.applyErrors[assetId] = '';
        PIPELINE.applyNodes[assetId] = nodeId;
        if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
        return result;
      }
      if(result.skipped){
        PIPELINE.applyStatus[assetId] = '已跳过';
        PIPELINE.applyErrors[assetId] = result.note || '';
        PIPELINE.applyNodes[assetId] = nodeId;
        if(result.note) toast(result.note);
        if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
        else render();
        return result;
      }
      PIPELINE.applyStatus[assetId] = '已应用';
      PIPELINE.applyErrors[assetId] = result.warning || '';
      PIPELINE.applyNodes[assetId] = nodeId;
      const what = slot === 'image' ? 'AI 图标' : (task.provider === 'blender' ? '减面模型' : 'AI 模型');
      toast(result.note || result.warning || ('已应用' + what + '：' + asset.name));
      if(cur === 'pipeline' && PIPELINE.assetId === assetId) refreshExportNode(assetId, kind);
      else render();
      return result;
    }, function(error){
      PIPELINE.applyStatus[assetId] = '应用失败';
      PIPELINE.applyErrors[assetId] = error.message || String(error);
      PIPELINE.applyNodes[assetId] = nodeId;
      if(typeof syncLog === 'function') syncLog('自动应用失败：' + PIPELINE.applyErrors[assetId], 'warn');
      toast('应用失败：' + PIPELINE.applyErrors[assetId]);
      if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
      return {ok:false, error:PIPELINE.applyErrors[assetId]};
    });

    PIPELINE.applyQueue[key] = next;
    next.finally(function(){
      if(PIPELINE.applyQueue[key] === next) delete PIPELINE.applyQueue[key];
    });
    return next;
  }

  window.pipelineFindAsset = pipelineFindAsset;
  window.pipelineAdoptTask = pipelineAdoptTask;
})();
