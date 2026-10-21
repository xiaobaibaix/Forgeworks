/* Forgeworks · js/data/styles.js
   ============================================================
   风格预设库 —— 项目美术的「宪法」
   ------------------------------------------------------------
   为什么需要这个模块
   ------------------
   生成类美术资源最容易翻车的地方不是单个模型的质量，而是**成套感**：
   每个模型单看都不错，摆在一起却像从六个不同项目里拼来的。

   根因通常是：配色是逐个手写的，彼此不在一个饱和度/明度带上。
   比如「钢蓝」饱和 14%、「琥珀黄」饱和 69%，放一起必然打架。

   本模块的解法不是"写一份风格文档让人自觉遵守"，而是**让引擎强制统一**：
     1. 定义若干套完整预设（每套 = 一个自洽的世界观）
     2. 每套给出「角色层级」——不同部位允许不同饱和度，但都在规定带内
     3. 运行时用 fitToBand() 把手写色校正进带内（色相保留 → 功能仍可区分）
     4. 一致性检查把偏离了多少如实报出来

   一句话：**色相负责区分功能，饱和度/明度负责统一风格。**

   一套预设覆盖的维度
   ------------------
     form      形态语言：体块感、倒角、曲面容忍度、细节密度、轮廓倾向
     surface   表面与着色：着色方式、PBR 取向、磨损度
     palette   受限色板：结构/金属/强调/发光/危险 + 饱和度明度带
     present   呈现：灯光、背景、视角
     matMap    材质映射（联动 3D 查看器的 role → material）
     spec      技术规格
     negative  负向词
     icon      图标参数
   ============================================================ */

/* ============================================================
   一、角色层级（所有预设共用，是"统一"的算法基础）
   ------------------------------------------------------------
   美术里的经典法则：**饱和度 × 面积 ≈ 常数**。
   大面积的基座必须低饱和（否则整个画面很吵），
   小面积的指示灯可以更艳（它是视觉焦点）。

   所以"统一"不是把所有颜色压成同一个饱和度，
   而是按角色分层，每层有自己的 [satMin,satMax] / [ligMin,ligMax]。
   ============================================================ */

const STYLE_TONES = {
  //              饱和度区间      明度区间       面积权重  说明
  structure: { sat:[ 6, 20], lig:[52, 66], area:0.45, label:'结构/基座', note:'大面积，必须退后' },
  metal:     { sat:[ 8, 24], lig:[42, 58], area:0.28, label:'主体金属', note:'中等面积，中性' },
  metalDark: { sat:[ 8, 26], lig:[24, 38], area:0.12, label:'暗部金属', note:'阴影/框架' },
  metalLite: { sat:[ 6, 18], lig:[62, 76], area:0.08, label:'亮部金属', note:'高光/面板' },
  glass:     { sat:[20, 46], lig:[56, 74], area:0.05, label:'玻璃/视窗', note:'小面积通透' },
  accent:    { sat:[44, 72], lig:[38, 60], area:0.04, label:'强调色',   note:'功能识别，小而准' },
  glow:      { sat:[60, 92], lig:[46, 66], area:0.02, label:'发光',     note:'最小面积，最强' },
  hazard:    { sat:[56, 84], lig:[44, 62], area:0.02, label:'警示',     note:'危险标识，克制使用' },
};

/* ============================================================
   二、可调旋钮（用户可在界面上覆盖预设）
   ------------------------------------------------------------
   预设是"别人的答案"，旋钮是"你的项目"。
   覆盖值存在 localStorage，跟内容数据分开。
   ============================================================ */

const STYLE_KNOBS = [
  { key:'satBoost',  label:'饱和度',   min:-40, max:40, step:2,  def:0,   unit:'%',
    hint:'整体加减饱和度。往负走更沉稳写实，往正走更卡通鲜明。' },
  { key:'contrast',  label:'明暗对比', min:0.6, max:1.5, step:0.05, def:1, unit:'×',
    hint:'结构色与强调色的明度差。高对比更醒目，低对比更柔和。' },
  { key:'wear',      label:'磨损度',   min:0,  max:1,  step:0.05, def:0.3, unit:'',
    hint:'做旧程度。0 = 崭新出厂，1 = 严重风化。' },
  { key:'metal',     label:'金属感',   min:0,  max:1,  step:0.05, def:0.5, unit:'',
    hint:'金属度加成。高 = 反射强更像合金，低 = 更像喷涂钢板。' },
  { key:'glow',      label:'发光强度', min:0,  max:1.5, step:0.05, def:0.8, unit:'×',
    hint:'炉火/指示灯/能量光的亮度倍率。' },
  { key:'detail',    label:'细节密度', min:0,  max:1,  step:0.05, def:0.5, unit:'',
    hint:'允许的表面细节量。低 = 大色块，高 = 管路法兰密布。' },
];

/* ============================================================
   三、风格预设
   ------------------------------------------------------------
   每套都面向 StellarEra 的题材（体素行星 + 太空工业 + 多纪元），
   但气质不同 —— 对应不同的行星环境 / 纪元 / 势力。
   ============================================================ */

const STYLE_PRESETS = {

  /* ---- 1. 体素工业（默认）----------------------------------
     读得懂的工业化。方盒体块、平着色、中饱和。
     适合：主星殖民地、游戏前中期、玩家最常看到的建筑。 */
  'voxel-industrial': {
    id:'voxel-industrial',
    name:'体素工业',
    tagline:'硬边方盒 + 平直着色 + 中饱和，一眼读懂的工业化',
    eraHint:'主星殖民地',
    form: {
      body:'低多边形体素风格，硬边方盒体块',
      bevel:0.05,
      curveAllow:'pipe-tank',
      detailDensity:'medium',
      silhouette:'按功能：采集竖高、化工铺开、组装紧凑',
      bevelNote:'几乎无曲面，管道与罐体除外',
    },
    surface: {
      shading:'平直着色（flat shading），单一面一种色，不做细腻渐变',
      pbr:'半哑光喷涂钢 + 混凝土',
      wear:'used', wearNote:'有使用痕迹但结构完好：边角掉漆、轻微锈斑、粉尘积灰',
      texReliance:'low', texNote:'细节靠体块凹凸与配色分区，不靠贴图纹理',
    },
    palette: {
      structure:'#a5a29b',
      metal:'#868d96',
      metalDark:'#4a5058',
      metalLite:'#aab1ba',
      glass:'#8fb8d8',
      glow:'#e07b39',
      hazard:'#c8b53a',
      // 分类强调色（色相区分功能，引擎会把 sat/lig 校正进 accent 带）
      accent:{
        '采集':'#c9a227', '分离':'#5fa8c9', '冶炼':'#de7d3c', '合金':'#6d8fa8',
        '化工':'#7fc47f', '加工':'#7d8fa0', '组装':'#3fa887', '回收':'#b09a6a',
      },
    },
    present: {
      lighting:'中性三点光，主光偏暖（模拟恒星），阴影短而硬',
      background:'纯白或透明背景，无地面投影，居中构图',
      camera:'3/4 等轴视角（isometric），能同时看到顶面和两个侧面',
    },
    matMap:{ base:'concrete', body:'steel', dark:'steelDark', light:'steelLite', glass:'glass', glow:'glow' },
    matTweak:{ metalAdd:0, roughAdd:0, emissiveScale:1 },
    spec:{
      machine:'三角面 400~900；贴图 512×512（或纯顶点色）；轴心在底面中心；1 格 = 1 米；朝向 +X 为正面',
      item:'三角面 100~300；贴图 256×256 或纯色；轴心在几何中心；1 个 = 0.5 米',
      icon:'512×512 或矢量；透明背景；居中；不要投影',
    },
    negative:['写实照片质感','圆润有机曲面','高频噪声纹理','PBR 过度磨损细节',
              '文字或水印','人类角色','现代物流设备（叉车/集装箱卡车）',
              '柔和棚拍光','强烈景深','霓虹赛博朋克配色'],
    icon:{ satScale:1.0, ligScale:1.0, stroke:0.22, shapeBias:'angular' },
  },

  /* ---- 2. 硬表面科幻 --------------------------------------
     倒角硬边、深空合金、冷色 + 青蓝能量光。
     适合：轨道站、纪元 3+ 的高科技公司、玩家后期基地。 */
  'hardsurface-scifi': {
    id:'hardsurface-scifi',
    name:'硬表面科幻',
    tagline:'倒角硬边 + 深空合金 + 冷色调，青蓝能量光点缀',
    eraHint:'轨道设施',
    form:{
      body:'硬表面（hard surface）机械形态，倒角边、嵌板分割线清晰',
      bevel:0.35,
      curveAllow:'pipe-tank',
      detailDensity:'dense',
      silhouette:'紧凑块状 + 外露骨架，机械感强',
      bevelNote:'允许倒角与小圆角，但整体仍是硬边机械，不是有机曲面',
    },
    surface:{
      shading:'平直着色为主，倒角处可轻微过渡',
      pbr:'金属合金，中等反射，带阳极氧化涂层',
      wear:'pristine', wearNote:'维护良好：只有极轻微划痕，密封严整',
      texReliance:'low', texNote:'靠嵌板分割与倒角表达细节，可少量发光条',
    },
    palette:{
      structure:'#4a5058',
      metal:'#6d757f',
      metalDark:'#2f343c',
      metalLite:'#aab1ba',
      glass:'#6fa8f0',
      glow:'#6fa8f0',
      hazard:'#e8b53a',
      accent:{
        '采集':'#4a90c4', '分离':'#5fa8c9', '冶炼':'#c47a4a', '合金':'#7d8fa0',
        '化工':'#4fb3a0', '加工':'#6d8fa8', '组装':'#3fa887', '回收':'#8a8d92',
      },
    },
    present:{
      lighting:'冷调主光 + 边缘补光，硬阴影，轻微环境反射',
      background:'深灰或透明背景，微弱地面反射，居中构图',
      camera:'3/4 等轴视角，略带俯视以展示顶面嵌板',
    },
    matMap:{ base:'steelDark', body:'steel', dark:'steelDark', light:'steelLite', glass:'glowBlue', glow:'glowBlue' },
    matTweak:{ metalAdd:0.15, roughAdd:-0.12, emissiveScale:1.15 },
    spec:{
      machine:'三角面 600~1200；贴图 1024×1024 或顶点色 + 嵌板法线；轴心底面中心；1 格 = 1 米',
      item:'三角面 150~400；贴图 512×512；轴心几何中心；1 个 = 0.5 米',
      icon:'512×512；透明背景；可带轻微外发光',
    },
    negative:['写实照片质感','圆润有机形态','锈迹斑驳','蒸汽朋克齿轮外露',
              '文字或水印','人类角色','暖色木质','柔和棚拍光','强烈景深'],
    icon:{ satScale:0.85, ligScale:0.92, stroke:0.18, shapeBias:'angular' },
  },

  /* ---- 3. 风化边陲 ----------------------------------------
     锈迹、磨损、土黄暖色。殖民早期的将就感。
     适合：外缘星球、废弃矿区、纪元 1 的拓荒阶段。 */
  'weathered-frontier': {
    id:'weathered-frontier',
    name:'风化边陲',
    tagline:'锈迹 + 补焊 + 土黄暖色，殖民早期的将就感',
    eraHint:'外缘拓荒',
    form:{
      body:'粗犷体块，构件尺度不一，可见补丁与临时加固',
      bevel:0.02,
      curveAllow:'pipe-tank',
      detailDensity:'medium',
      silhouette:'低矮敦实，横向铺开，抗风沙感',
      bevelNote:'几乎无曲面，允许不规则与不对称（修过）',
    },
    surface:{
      shading:'平直着色，粗糙无光泽',
      pbr:'锈蚀钢材与再生混凝土，几乎无反射',
      wear:'weathered', wearNote:'重度风化：大面积锈层、补焊痕、油渍、贴的警示胶带',
      texReliance:'medium', texNote:'锈迹与污渍是风格的一部分，允许中等贴图依赖',
    },
    palette:{
      structure:'#9a9187',
      metal:'#9a6b4a',
      metalDark:'#4a4038',
      metalLite:'#a89a86',
      glass:'#a8b0a0',
      glow:'#e07b39',
      hazard:'#c8a83a',
      accent:{
        '采集':'#b08a3a', '分离':'#7d9a8a', '冶炼':'#c46a3a', '合金':'#8a8d92',
        '化工':'#8aa86a', '加工':'#8a8578', '组装':'#7a9a6a', '回收':'#a8875a',
      },
    },
    present:{
      lighting:'强侧光（低角度恒星），长而硬的阴影，暖色环境光',
      background:'土黄或透明背景，可带轻微沙尘，居中构图',
      camera:'3/4 等轴视角，略低角度以强调敦实感',
    },
    matMap:{ base:'concrete', body:'rust', dark:'steelDark', light:'steel', glass:'glass', glow:'glow' },
    matTweak:{ metalAdd:-0.15, roughAdd:0.18, emissiveScale:0.95 },
    spec:{
      machine:'三角面 400~900；贴图 1024×1024（锈迹需要分辨率）；轴心底面中心；1 格 = 1 米',
      item:'三角面 100~300；贴图 512×512；轴心几何中心；1 个 = 0.5 米',
      icon:'512×512；透明背景；可带轻微噪点做旧',
    },
    negative:['崭新出厂质感','高反射抛光金属','镜面','霓虹发光',
              '文字或水印','人类角色','未来感全息','柔和棚拍光','强烈景深'],
    icon:{ satScale:0.8, ligScale:0.9, stroke:0.26, shapeBias:'rough' },
  },

  /* ---- 4. 洁净轨道 ----------------------------------------
     白 + 浅蓝，高亮低饱和，实验室气质。
     适合：轨道研究所、医疗/生物模块、纪元 4 的精密制造。 */
  'cleanroom-orbit': {
    id:'cleanroom-orbit',
    name:'洁净轨道',
    tagline:'白 + 浅蓝，高亮低饱和，无尘实验室气质',
    eraHint:'轨道研究设施',
    form:{
      body:'简洁几何体，圆角过渡，封闭性好，外露构件少',
      bevel:0.5,
      curveAllow:'free',
      detailDensity:'sparse',
      silhouette:'规整立方与圆柱组合，留白多',
      bevelNote:'允许曲面与大圆角，整体干净利落',
    },
    surface:{
      shading:'平直着色，高亮低饱和，大面积浅色',
      pbr:'哑光涂层 + 少量不锈钢，反射弱',
      wear:'pristine', wearNote:'洁净无尘：无锈迹无油渍，接缝严密',
      texReliance:'none', texNote:'纯色分区，几乎不用贴图，靠形体说话',
    },
    palette:{
      structure:'#dfe2e5',
      metal:'#c8ccd2',
      metalDark:'#8a9099',
      metalLite:'#eef1f4',
      glass:'#a8c8e8',
      glow:'#5fa8d9',
      hazard:'#d8a83a',
      accent:{
        '采集':'#7a9ab5', '分离':'#8ab5c9', '冶炼':'#c99a7a', '合金':'#9aa8b8',
        '化工':'#9ac49a', '加工':'#a8b0bc', '组装':'#8ac4a8', '回收':'#b5ada0',
      },
    },
    present:{
      lighting:'均匀柔和的无影光，高通调，阴影极淡',
      background:'纯白背景，无投影，居中构图',
      camera:'3/4 等轴视角，构图留白较多',
    },
    matMap:{ base:'clean', body:'clean', dark:'steelLite', light:'clean', glass:'glass', glow:'glowBlue' },
    matTweak:{ metalAdd:-0.1, roughAdd:0.08, emissiveScale:0.9 },
    spec:{
      machine:'三角面 300~700；贴图 512×512 或纯顶点色；轴心底面中心；1 格 = 1 米',
      item:'三角面 80~250；贴图 256×256 或纯色；轴心几何中心；1 个 = 0.5 米',
      icon:'512×512；透明背景；高亮，不要重描边',
    },
    negative:['锈迹','油污','污渍做旧','暗色调','粗糙混凝土',
              '文字或水印','人类角色','重工业烟囱','硬阴影','强烈景深'],
    icon:{ satScale:0.7, ligScale:1.12, stroke:0.14, shapeBias:'round' },
  },

  /* ---- 5. 柴油朋克铸造 ------------------------------------
     重工业、暗色 + 炉火橙、高对比。
     适合：熔炼星球、重工业区、高能耗建筑群。 */
  'dieselpunk-foundry': {
    id:'dieselpunk-foundry',
    name:'柴油朋克铸造',
    tagline:'暗色铸铁 + 炉火橙，高对比的重工业压迫感',
    eraHint:'熔炼工业带',
    form:{
      body:'厚重铸铁体块，铆钉与加强筋外露，管道粗壮',
      bevel:0.1,
      curveAllow:'pipe-tank',
      detailDensity:'dense',
      silhouette:'高大厚重，竖向烟囱与桁架，体量压迫感强',
      bevelNote:'主体硬边，允许铆钉/加强筋等小尺度重复构件',
    },
    surface:{
      shading:'平直着色，暗部深沉，高光集中在炉口与边缘',
      pbr:'铸铁与耐候钢，中等粗糙，局部高温氧化变色',
      wear:'used', wearNote:'高温工况：炉体氧化变色、烟熏黑渍、局部烧蚀',
      texReliance:'medium', texNote:'烟熏与氧化色是风格核心，允许中等贴图依赖',
    },
    palette:{
      structure:'#6b6e73',
      metal:'#5c6169',
      metalDark:'#2e3238',
      metalLite:'#8a8d92',
      glass:'#c88a4a',
      glow:'#f08a3a',
      hazard:'#d84a3a',
      accent:{
        '采集':'#c88a3a', '分离':'#6d8fa0', '冶炼':'#e8732a', '合金':'#7d838c',
        '化工':'#a8a84a', '加工':'#6b7580', '组装':'#8a7a5a', '回收':'#8a6a4a',
      },
    },
    present:{
      lighting:'暗环境 + 强炉火内光，高对比，硬阴影',
      background:'深灰或透明背景，可带火星与烟雾，居中构图',
      camera:'3/4 等轴视角，略低角度以强调高大体量',
    },
    matMap:{ base:'steelDark', body:'steelDark', dark:'steelDark', light:'steel', glass:'glass', glow:'glow' },
    matTweak:{ metalAdd:0.08, roughAdd:0.1, emissiveScale:1.3 },
    spec:{
      machine:'三角面 500~1100；贴图 1024×1024（烟熏需要分辨率）；轴心底面中心；1 格 = 1 米',
      item:'三角面 120~350；贴图 512×512；轴心几何中心；1 个 = 0.5 米',
      icon:'512×512；透明背景；可带暖色内发光',
    },
    negative:['明亮轻快配色','塑料感','崭新无痕','白色洁净',
              '文字或水印','人类角色','霓虹冷光','柔和棚拍光','强烈景深'],
    icon:{ satScale:1.1, ligScale:0.88, stroke:0.3, shapeBias:'angular' },
  },

  /* ---- 6. 异星共生 ----------------------------------------
     允许曲面，生物质感，绿紫生物光。
     适合：异星生态星球、生物冶炼、特殊纪元内容。 */
  'bio-xeno': {
    id:'bio-xeno',
    name:'异星共生',
    tagline:'有机曲面 + 陶瓷外壳，绿紫生物光流转',
    eraHint:'异星生态带',
    form:{
      body:'有机形态与工业结构共生：骨架是机械，外壳是生物质',
      bevel:0.6,
      curveAllow:'free',
      detailDensity:'medium',
      silhouette:'不对称生长感，鼓包与脉络，局部有触须状管路',
      bevelNote:'允许曲面与有机过渡，但保留可辨识的工业构件',
    },
    surface:{
      shading:'平直着色为主，生物质处可柔和过渡',
      pbr:'陶瓷/几丁质外壳，半透，局部湿润反光',
      wear:'used', wearNote:'活体磨损：外壳有生长纹、苔藓样附着、分泌液残留',
      texReliance:'medium', texNote:'脉络与生长纹需要一定贴图表现',
    },
    palette:{
      structure:'#8a8d92',
      metal:'#7d8a7d',
      metalDark:'#3d4a3d',
      metalLite:'#b8c0b0',
      glass:'#8ad0a8',
      glow:'#5fd6a8',
      hazard:'#c4a83a',
      accent:{
        '采集':'#7fc47f', '分离':'#5fa8c9', '冶炼':'#c47a8a', '合金':'#8a7ab5',
        '化工':'#9ad65f', '加工':'#7fb59a', '组装':'#5fd6a8', '回收':'#a89a6a',
      },
    },
    present:{
      lighting:'冷调环境光 + 生物内发光，中等对比',
      background:'深青或透明背景，可带孢子微粒，居中构图',
      camera:'3/4 等轴视角，能看出有机起伏',
    },
    matMap:{ base:'ceramic', body:'ceramic', dark:'steelDark', light:'clean', glass:'glass', glow:'glowGreen' },
    matTweak:{ metalAdd:-0.2, roughAdd:0.06, emissiveScale:1.1 },
    spec:{
      machine:'三角面 500~1000；贴图 1024×1024（脉络需要分辨率）；轴心底面中心；1 格 = 1 米',
      item:'三角面 120~350；贴图 512×512；轴心几何中心；1 个 = 0.5 米',
      icon:'512×512；透明背景；可带生物光晕',
    },
    negative:['纯机械无机感','锈迹铁锈','塑料玩具感','呆板对称',
              '文字或水印','人类角色','金属高反射','柔和棚拍光','强烈景深'],
    icon:{ satScale:0.95, ligScale:1.0, stroke:0.16, shapeBias:'organic' },
  },
};

const DEFAULT_STYLE_ID = 'voxel-industrial';

/* ---------- 分类强调色的兜底顺序 ---------- */
const ACCENT_FALLBACK_ORDER = ['加工','组装','分离','冶炼','化工','合金','采集','回收'];

/* ============================================================
   四、风格文案助手
   ------------------------------------------------------------
   把预设的内部字段翻译成"能直接读给生成模型"的自然语言。
   放在这里而不是视图里，是为了让导出 JSON / Markdown 也能复用。
   ============================================================ */

function stylePresetList(){
  return Object.keys(STYLE_PRESETS).map(k=>STYLE_PRESETS[k]);
}

/** 磨损度的中文描述 */
function wearLabel(v){
  v = Number(v)||0;
  if(v < 0.2) return '崭新（pristine）';
  if(v < 0.45) return '有使用痕迹（used）';
  if(v < 0.75) return '明显磨损（worn）';
  return '严重风化（weathered）';
}

/** 细节密度的中文描述 */
function detailLabel(v){
  v = Number(v)||0;
  if(v < 0.3) return '极简（大色块，构件少）';
  if(v < 0.6) return '中等（主要构件清晰）';
  return '密集（管路法兰与加强筋密布）';
}
