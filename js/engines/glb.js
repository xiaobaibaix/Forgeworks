/* Forgeworks · js/engines/glb.js */
/* 独立 GLB 工具：不依赖 UI，供 viewer3d / pipeline-adopt 共用。 */
(function(){
  function axisNumber(value, fallback){
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function fwNormalizeTransform(transform){
    const t = transform || {};
    const p = t.position || {}, r = t.rotation || {}, s = t.scale || {};
    return {
      position: {x:axisNumber(p.x,0), y:axisNumber(p.y,0), z:axisNumber(p.z,0)},
      rotation: {x:axisNumber(r.x,0), y:axisNumber(r.y,0), z:axisNumber(r.z,0)},
      scale:    {x:axisNumber(s.x,1), y:axisNumber(s.y,1), z:axisNumber(s.z,1)},
    };
  }

  function fwApplyGLBTransform(object, transform){
    const t = fwNormalizeTransform(transform);
    object.position.set(t.position.x, t.position.y, t.position.z);
    object.rotation.set(t.rotation.x, t.rotation.y, t.rotation.z);
    object.scale.set(t.scale.x, t.scale.y, t.scale.z);
    object.updateMatrixWorld(true);
  }

  /** 解析 GLB 字节为 THREE 场景；失败时 reject Error */
  function fwLoadGLBScene(buffer){
    return new Promise(function(resolve, reject){
      if(!THREE.GLTFLoader){ reject(new Error('GLTFLoader 未加载')); return; }
      const loader = new THREE.GLTFLoader();
      loader.parse(buffer, '', function(gltf){
        const root = gltf.scene || (gltf.scenes && gltf.scenes[0]);
        if(!root){ reject(new Error('GLB 中没有场景')); return; }
        root.traverse(function(node){
          if(node.isMesh){
            node.castShadow = true;
            node.receiveShadow = true;
          }
        });
        resolve(root);
      }, function(error){
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  }

  /**
   * 计算整体变换：
   * - machine 等比缩放至占地内，底面贴地、水平居中；
   * - item 等比缩放至最长边 1，底面贴地、水平居中。
   */
  function fwComputeFitTransform(object, kind, footprint){
    const bbox = new THREE.Box3().setFromObject(object);
    if(bbox.isEmpty()) throw new Error('模型包围盒为空');
    const size = bbox.getSize(new THREE.Vector3());
    const center = bbox.getCenter(new THREE.Vector3());
    let scale = 1;
    if(kind === 'machine'){
      const fp = (typeof parseFootprint === 'function') ? parseFootprint(footprint) : [1, 1];
      const bw = Number(fp[0]) || 1, bd = Number(fp[1]) || 1;
      scale = Math.min(bw / (size.x || 1), bd / (size.z || 1)) || 1;
    }else{
      const maxDim = Math.max(size.x, size.y, size.z) || 1;
      scale = 1 / maxDim;
    }
    return {
      position: {x:-center.x * scale, y:-bbox.min.y * scale, z:-center.z * scale},
      rotation: {x:0, y:0, z:0},
      scale:    {x:scale, y:scale, z:scale},
    };
  }

  /** 透明背景缩略图；克隆场景避免把实时模型移出 viewer */
  function fwRenderGLBThumbnail(scene, transform, size){
    const px = Math.max(32, Math.round(size || 256));
    const canvas = document.createElement('canvas');
    canvas.width = px; canvas.height = px;
    const renderer = new THREE.WebGLRenderer({
      canvas: canvas, alpha: true, antialias: true, preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(1);
    renderer.setSize(px, px, false);
    renderer.setClearColor(0x000000, 0);
    if('outputEncoding' in renderer && THREE.sRGBEncoding) renderer.outputEncoding = THREE.sRGBEncoding;

    const renderScene = new THREE.Scene();
    const holder = new THREE.Group();
    holder.add(scene.clone(true));
    fwApplyGLBTransform(holder, transform);
    renderScene.add(holder);

    const bbox = new THREE.Box3().setFromObject(holder);
    const center = bbox.getCenter(new THREE.Vector3());
    const radius = bbox.getBoundingSphere(new THREE.Sphere()).radius || 1;
    const camera = new THREE.PerspectiveCamera(35, 1, radius / 100, radius * 100);
    camera.position.copy(center).addScaledVector(
      new THREE.Vector3(1, 1.15, 1).normalize(), radius * 2.6);
    camera.lookAt(center);

    renderScene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.copy(center).add(new THREE.Vector3(radius, radius * 1.6, radius));
    renderScene.add(key);

    try{
      renderer.render(renderScene, camera);
      return canvas.toDataURL('image/png');
    }finally{
      renderer.dispose();
      if(renderer.forceContextLoss) renderer.forceContextLoss();
    }
  }

  /** 把整体变换与元数据烘焙进单文件 GLB；克隆避免影响实时场景 */
  function fwBakeGLBScene(scene, transform, userData, callback){
    if(!THREE.GLTFExporter){ callback(null, new Error('GLTFExporter 未加载')); return; }
    const holder = new THREE.Group();
    holder.name = (userData && userData.name) || 'AI_Model';
    holder.userData = Object.assign({}, userData || {});
    holder.add(scene.clone(true));
    fwApplyGLBTransform(holder, transform);
    const size = new THREE.Box3().setFromObject(holder).getSize(new THREE.Vector3());
    const extras = Object.assign({}, holder.userData.forgeworks || {}, {
      source: 'pipeline-ai',
      bounds: {x:+size.x.toFixed(3), y:+size.y.toFixed(3), z:+size.z.toFixed(3)},
    });
    holder.userData.forgeworks = extras;
    const exporter = new THREE.GLTFExporter();
    exporter.parse(holder, function(result){
      callback(result, null);
    }, function(error){
      callback(null, error instanceof Error ? error : new Error(String(error)));
    }, {binary: true, onlyVisible: true});
  }

  function fwCountTriangles(root){
    let total = 0;
    root.traverse(function(node){
      if(!node.isMesh || !node.geometry) return;
      const geometry = node.geometry;
      const position = geometry.attributes && geometry.attributes.position;
      if(geometry.index) total += geometry.index.count / 3;
      else if(position) total += position.count / 3;
    });
    return Math.round(total);
  }

  function fwCountMaterials(root){
    const seen = new Set();
    root.traverse(function(node){
      if(!node.isMesh || !node.material) return;
      (Array.isArray(node.material) ? node.material : [node.material]).forEach(function(mat){
        if(mat) seen.add(mat.uuid);
      });
    });
    return seen.size;
  }

  window.fwNormalizeTransform = fwNormalizeTransform;
  window.fwApplyGLBTransform = fwApplyGLBTransform;
  window.fwLoadGLBScene = fwLoadGLBScene;
  window.fwComputeFitTransform = fwComputeFitTransform;
  window.fwRenderGLBThumbnail = fwRenderGLBThumbnail;
  window.fwBakeGLBScene = fwBakeGLBScene;
  window.fwCountTriangles = fwCountTriangles;
  window.fwCountMaterials = fwCountMaterials;
})();
