/* Forgeworks · js/data/prompts.js
   ============================================================
   美术需求描述词库
   ------------------------------------------------------------
   本文件不生成任何资源，只负责把「数据」翻译成「可执行的美术指令」。
   产出可以直接喂给：
     - 文生图（概念图 / 图标）
     - 文生 3D（Tripo / Meshy / Rodin 等）
     - 或者交给美术当建模任务书

   分三层：
     1. MACHINE_BRIEFS   每个建筑的个性描述（形态/部件/配色/细节）
     2. CATEGORY_STYLE   按功能分类的兜底风格
     3. STYLE_BLOCK      全局风格约束 + 技术规格 + 负向词
   ============================================================ */

/* ---------- 全局风格（所有资源共用） ---------- */
const STYLE_BLOCK = {
  render: '低多边形体素风格（voxel / low-poly），硬边方盒体块，几乎无曲面（管道与罐体除外）',
  shading: '平直着色（flat shading），单一面只有一种色，不做细腻渐变',
  lighting: '中性三点光，主光偏暖（模拟恒星），阴影短而硬',
  background: '纯白或透明背景，无地面投影，居中构图',
  camera: '3/4 等轴视角（isometric），能同时看到顶面和两个侧面',
  detailRule: '细节靠「体块的凹凸与配色分区」表达，不靠贴图纹理',
};

const TECH_SPEC = {
  machine: '三角面 400~900；贴图 512×512（或纯顶点色）；轴心在底面中心；1 格 = 1 米；朝向 +X 为正面',
  item: '三角面 100~300；贴图 256×256 或纯色；轴心在几何中心；1 个 = 0.5 米',
  icon: '512×512 或矢量；透明背景；居中；不要投影',
};

const NEGATIVE = [
  '写实照片质感', '圆润有机曲面', '高频噪声纹理', 'PBR 磨损细节',
  '文字或水印', '人类角色', '现代工业设备（叉车/集装箱卡车）',
  '柔和棚拍光', '强烈景深', '霓虹赛博朋克配色',
];

/* ---------- 按功能分类的风格兜底 ---------- */
const CATEGORY_STYLE = {
  '采集': {
    silhouette: '低矮基座 + 向上伸展的塔架',
    parts: ['方形基座', '支撑结构', '采集头或钻杆', '料斗', '警示灯'],
    accent: '琥珀黄',
    heightRatio: 1.6,
  },
  '分离': {
    silhouette: '扁平基座 + 一到两个罐体 + 顶部连通管路',
    parts: ['基座', '罐体', '连通管', '阀门', '检修梯'],
    accent: '青蓝',
    heightRatio: 1.15,
  },
  '冶炼': {
    silhouette: '厚重基座 + 高炉主体 + 高耸烟囱',
    parts: ['基座', '炉体', '烟囱', '出料口', '炉门（发光）'],
    accent: '橙红（热）',
    heightRatio: 1.9,
  },
  '合金': {
    silhouette: '宽大基座 + 门型框架 + 中央压头',
    parts: ['基座', '立柱', '横梁', '压头', '液压缸'],
    accent: '钢青',
    heightRatio: 1.4,
  },
  '化工': {
    silhouette: '多个圆柱罐 + 密集管路',
    parts: ['罐体组', '管路', '法兰', '泵', '压力表'],
    accent: '黄绿',
    heightRatio: 1.3,
  },
  '加工': {
    silhouette: '工作台 + 龙门架或机械臂',
    parts: ['工作台', '龙门架', '主轴/刀头', '控制面板'],
    accent: '蓝灰',
    heightRatio: 1.2,
  },
  '组装': {
    silhouette: '大跨度厂房 + 屋脊 + 传送带出入口',
    parts: ['厂房主体', '屋脊', '卷帘门', '传送带口', '顶部通风'],
    accent: '青绿',
    heightRatio: 1.35,
  },
  '回收': {
    silhouette: '料斗 + 处理塔 + 排放口',
    parts: ['料斗', '处理塔', '排放管', '滤网', '警示标识'],
    accent: '土黄',
    heightRatio: 1.5,
  },
};

/* ---------- 每个建筑的个性描述 ----------
   form  : 一眼能看懂的外形
   parts : 必须出现的可辨识部件
   palette: 主色 + 副色
   note  : 让模型"像这个东西"的关键细节
   ---------------------------------------- */
const MACHINE_BRIEFS = {
  MC_DRILL: {
    form: '低矮方形基座，中央竖一根粗壮钻塔，基座侧面伸出斜向矿料溜槽',
    parts: ['方形基座', '三段式钻塔', '旋转钻杆', '斜溜槽', '顶部黄色警示灯'],
    palette: '锈红 #8b6b4a + 深钢灰 #3d3d3b',
    note: '钻杆上做出螺旋纹路的起伏；溜槽口有矿石碎块堆积',
  },
  MC_HAND: {
    form: '一把插在地面上的手动采矿镐，柄朝上',
    parts: ['木柄', '铁镐头', '地面小土堆'],
    palette: '木棕 #6b5a42 + 铁灰 #9a9da3',
    note: '这是唯一的"非机械"资源，要做得简陋、手工感强',
  },
  MC_TIDAL_PUMP: {
    form: '圆形水台 + 中央竖管 + 四周倾斜的潮汐挡板',
    parts: ['圆形基台', '竖管', '四片斜挡板', '出水口', '水位标尺'],
    palette: '青蓝 #6fa8c4 + 混凝土灰 #8e8d88',
    note: '挡板要有被水流冲刷的磨损感；基台边缘可做水渍色块',
  },
  MC_DEEP_DRILL: {
    form: '巨大方形井架，四条腿撑起高塔，中央是通往地下的钻管',
    parts: ['四腿井架', '顶部滑轮组', '粗钻管', '地面井口', '吊索'],
    palette: '深钢灰 #4a4a48 + 橙警示 #c47a3a',
    note: '井口要能看出"深"——用同心方形台阶向内收',
  },
  MC_METEOR_CAP: {
    form: '低矮圆盘 + 向上张开的四瓣捕获爪',
    parts: ['圆盘基座', '四瓣机械爪', '中央缓冲垫', '姿态推进器'],
    palette: '钛银 #b4b8bd + 蓝指示 #378add',
    note: '爪内侧做防撞格纹；整体要有"太空设备"的洁净感（比地面设备更干净）',
  },
  MC_GAS_TOWER: {
    form: '细高的多层格构塔，塔身有环状进气口，顶部是锥形集气罩',
    parts: ['格构塔身', '环状进气环', '锥形集气罩', '底部锚固'],
    palette: '浅银 #c2c7cd + 青色气体 #6fb3d9',
    note: '进气环之间留空隙，看得出是"一层一层"的',
  },
  MC_SORT: {
    form: '一张长条工作台，台面有斜置的筛网，两端各一个料箱',
    parts: ['长条台面', '倾斜筛网', '进料箱', '出料箱', '支腿'],
    palette: '木棕 #8b6b4a + 铁灰 #8a8d92',
    note: '最简单的一台机器，故意做得像"工坊手工设备"而非工业产线',
  },
  MC_ARC: {
    form: '矮胖的炉体，正面有发光的炉门，顶部接一根粗烟囱',
    parts: ['方形炉体', '拱形炉门（橙光）', '粗烟囱', '出钢口', '风管'],
    palette: '钢灰 #6b6e73 + 炉火橙 #e07b39',
    note: '炉门必须是自发光材质；炉体下部做出被烤黑的色带',
  },
  MC_ALLOY_PRESS: {
    form: '门型框架，中央一根粗压头悬在上方，下方是模具台',
    parts: ['底座', '两根粗立柱', '顶部横梁', '液压压头', '模具槽'],
    palette: '钢青 #7d838c + 液压黄 #c8b53a',
    note: '立柱要比横梁粗，体现"承受压力"；压头与模具之间留一道缝隙',
  },
  MC_EVAP: {
    form: '三层堆叠的浅盘，每层边缘有溢流口，顶部是锥形集汽罩',
    parts: ['三层浅盘', '溢流口', '锥形罩', '支撑柱'],
    palette: '浅灰 #a8adb5 + 盐白 #d8dce0',
    note: '层与层之间要留空隙；盘内可做浅色盐结晶色块',
  },
  MC_CHLOR_ALKALI: {
    form: '两排并列的电解槽，槽间有铜排连接，两侧各一个储罐',
    parts: ['电解槽组', '铜排', '两个侧罐', '排气管'],
    palette: '黄绿 #7fc47f + 铜色 #b87333',
    note: '铜排是横向的亮色条带，是这台机器的视觉记忆点',
  },
  MC_VAC_IND: {
    form: '圆柱形真空腔体，侧面有观察窗，上方是感应线圈',
    parts: ['圆柱腔体', '圆形观察窗（发光）', '感应线圈', '真空泵'],
    palette: '钛银 #989ba1 + 紫色 #7f77dd',
    note: '观察窗要有内部紫色辉光；腔体要显得"密封"（无缝隙）',
  },
  MC_DISTILL: {
    form: '细高的分馏柱，柱身分段，顶部有回流弯管',
    parts: ['分馏柱', '分段法兰', '回流弯管', '底部再沸器'],
    palette: '钢灰 #7d838c + 硫黄 #c8b53a',
    note: '分段感要明显——每段之间有一圈加粗法兰',
  },
  MC_MAG: {
    form: '一条倾斜的传送带，带上方悬着电磁铁，带尾是分料口',
    parts: ['倾斜传送带', '悬挂电磁铁', '分料斗', '支架'],
    palette: '深灰 #5d5b57 + 铜线圈 #c07a3a',
    note: '电磁铁下方画磁力线感的浅色块，暗示"正在吸附"',
  },
  MC_CENTRIFUGE: {
    form: '高大圆柱外壳 + 顶部旋转盘 + 侧面一圈管道接口',
    parts: ['圆柱外壳', '顶部转盘', '环形管道接口', '控制柜'],
    palette: '不锈钢 #aeb4ba + 辐射绿 #5f9e4f',
    note: '要有"高速旋转"的暗示——转盘上做放射状凹槽',
  },
  MC_ETCH: {
    form: '密闭箱体，正面是玻璃观察面，内部可见基板夹持架',
    parts: ['箱体', '玻璃观察面（半透明）', '基板夹持架', '化学品接口'],
    palette: '浅灰 #a8adb5 + 绿光 #3f7a4a',
    note: '玻璃面要半透明，能看见内部一层层基板',
  },
  MC_LATHE: {
    form: '长条床身 + 左侧主轴箱 + 中滑板上方一个刀塔',
    parts: ['长条床身', '主轴箱', '刀塔', '尾座', '排屑槽'],
    palette: '铸铁灰 #6e7480 + 黄警示 #c8b53a',
    note: '床身的导轨要有明显的"长条形凸起"',
  },
  MC_CARBONIZER: {
    form: '高大立式炉 + 顶部进料斗 + 底部出料口，炉身裹着保温层',
    parts: ['立式炉体', '顶部料斗', '底部出料', '保温层分段', '温度表'],
    palette: '深灰 #4a4a48 + 暗红 #8a3a2a',
    note: '保温层做成一块块拼接的板，暗示高温',
  },
  MC_MAG_FACTORY: {
    form: '方形厂房 + 屋顶一根排气管 + 侧面成品输出口',
    parts: ['方形厂房', '排气管', '输出口', '门', '屋顶通风'],
    palette: '紫灰 #7a5a8a + 钢灰 #8a8d92',
    note: '整体要"低矮宽大"，和冶炼的"高瘦"形成对比',
  },
  MC_BATTERY: {
    form: '两排竖直的电池组架，架子有横向分层',
    parts: ['电池架', '横向分层', '母线排', '冷却管'],
    palette: '蓝灰 #4a6e8a + 铜色 #c07a3a',
    note: '分层里要有"一格一格的电池单元"，可用小方块阵列',
  },
  MC_ROLLER: {
    form: '两组上下叠放的轧辊，两侧是厚重的机架',
    parts: ['上下轧辊', '两侧机架', '进料导板', '出料导板'],
    palette: '钢灰 #8a8d92 + 亮银（辊面）',
    note: '轧辊要能看出是"圆柱"，是这台机器唯一的曲面元素',
  },
  MC_PRESS: {
    form: '方形机架，中央下压的冲头，下方是模具凹槽',
    parts: ['机架', '冲头', '模具', '导向柱'],
    palette: '钢灰 #7d838c + 深色模具',
    note: '比合金压力机小一号，结构更简单',
  },
  MC_SUPER_MILL: {
    form: '细长的拉丝塔，多组导轮垂直排列，底部是收线盘',
    parts: ['高塔', '多组导轮', '收线盘', '冷却液槽'],
    palette: '青蓝 #5fa8c4 + 银白',
    note: '要有"细线"的暗示——导轮之间用极细的线连接',
  },
  MC_CONCRETE: {
    form: '低矮圆筒搅拌罐 + 倾斜出料槽 + 顶部进料斗',
    parts: ['卧式圆筒', '进料斗', '出料槽', '支架'],
    palette: '混凝土灰 #8e8d88 + 锈迹',
    note: '整体要"脏"——大面积灰，加不规则锈斑色块',
  },
  MC_FUEL_SYNTH: {
    form: '反应塔 + 两个球形储罐 + 密集管线',
    parts: ['反应塔', '球形储罐', '管线', '火炬（顶部）'],
    palette: '钢灰 + 橙火焰',
    note: '顶部火炬可以有一小簇自发光火焰',
  },
  MC_CARBON_CAP: {
    form: '方形箱体 + 顶部多根竖立的吸附柱 + 侧面进气格栅',
    parts: ['箱体', '吸附柱阵列', '进气格栅', '排放口'],
    palette: '灰绿 #6a7a6a + 深色格栅',
    note: '吸附柱要"排成阵列"，是这台机器的识别特征',
  },
  MC_ASSEMBLY: {
    form: '方盒子 + 顶部一条横梁 + 悬挂的机械臂',
    parts: ['盒体', '顶部横梁', '悬臂', '前端夹爪', '传送带口'],
    palette: '青绿 #1d9e75 + 钢灰',
    note: '机械臂要能看出"可动"——关节处留缝',
  },
  MC_PRECISION: {
    form: '更大更方的厂房，正面是整排玻璃窗，内部可见多台设备',
    parts: ['大厂房', '整排玻璃窗', '屋顶管线', '双开门'],
    palette: '青绿 #1d9e75 + 玻璃蓝',
    note: '玻璃窗要能透出内部暖光，和外面的冷色形成对比',
  },
  MC_LIFEFAB: {
    form: '圆角方舱 + 顶部环形通风口 + 侧面气闸门',
    parts: ['方舱主体', '环形通风口', '气闸门', '外部管线'],
    palette: '白 #d8dce0 + 青绿点缀',
    note: '唯一"干净"的建筑——大面积白，几乎无锈迹',
  },
  MC_WINDER: {
    form: '卧式机台 + 一个可旋转的绕线骨架 + 侧面线轴架',
    parts: ['机台', '绕线骨架', '线轴架', '计数器'],
    palette: '钢灰 + 铜色线材',
    note: '骨架上要有"缠绕的线圈"——用同心圆环表示',
  },
  MC_CLEANROOM: {
    form: '大跨度洁净厂房，全白，正面是整面玻璃幕墙',
    parts: ['厂房主体', '玻璃幕墙', '顶部 FFU 阵列', '气闸'],
    palette: '纯白 #e8eaec + 浅蓝玻璃',
    note: '最高级的建筑——必须显得"一尘不染"，线条极简',
  },
  MC_ORBITAL_DOCK: {
    form: '巨型开放式桁架结构，中央是环形建造平台，四周伸出对接臂',
    parts: ['主桁架', '环形平台', '四根对接臂', '吊装龙门', '导航灯'],
    palette: '深灰桁架 + 蓝紫能量光',
    note: '这是全场最大的建筑——12×12 格，必须能看出"尺度感"，'
        + '桁架要稀疏通透，不要做成实心方块',
  },
  MC_CAR: {
    subject: '轮式载具',
    form: '方正的两厢小型汽车，短前悬、平直车尾，四个车轮对称接地；'
        + '车身长宽高比例约 4.2 × 1.8 × 1.5 米',
    parts: ['方正车身', '车顶', '前挡风玻璃', '两侧车窗', '四个轮胎与轮毂',
            '前保险杠', '后保险杠', '前灯与尾灯', '外后视镜'],
    palette: '车漆主色 #d5d9dc + 深色玻璃 #3d4a55 + 黑橡胶 #2a2a2a',
    note: '四个轮子必须清楚可见并接地，轮拱切出方形凹口；'
        + '前灯与尾灯用不同形状的小面积自发光色块区分车头车尾；'
        + '不要做成赛车、装甲车或卡车，保持普通民用小型车轮廓',
    spec: '三角面 900~1600；贴图 512×512（或纯顶点色）；轴心在四轮接地点中心；'
        + '1 格 = 1 米；车头朝 +X',
  },
  MC_EXCAVATOR: {
    subject: '履带式工程机械',
    form: '履带式液压挖掘机：矩形履带底盘，上部回转平台与发动机舱，前部两节式动臂连接铲斗，'
        + '驾驶室位于车体左前侧；车身长宽高比例约 7 × 2.6 × 3 米',
    parts: ['车体', '履带底盘', '动臂', '铲斗', '驾驶室'],
    palette: '工程黄 #d6a51f + 深钢灰 #3a3d40 + 黑橡胶履带与镀铬液压杆',
    note: '左右履带必须平行且接地，履带板节清楚；动臂与斗杆的销轴铰点要能看出可动关系；'
        + '铲斗带斗齿，驾驶室玻璃通透；不要做成轮式挖掘机或坦克',
    spec: '三角面 1200~2200；贴图 512×512（或纯顶点色）；轴心在两履带接地中心；'
        + '1 格 = 1 米；车头朝 +X',
  },
};

/* ---------- 物品的形态描述 ---------- */
const ITEM_FORM = {
  raw:        '不规则的原矿块，表面粗糙，有 2~3 个明显棱面',
  concentrate:'一小堆精矿颗粒或粉末，堆成锥形，边缘散落碎粒',
  ingot:      '标准梯形金属锭，顶面平整，侧面有轻微拔模斜度',
  part:       '精密机械零件，轮廓规整，有明确的加工面',
  material:   '堆叠的板材/砖块，每层之间有一道细缝',
  module:     '方形模块，一面上有电路或接口阵列',
  mega:       '大型结构件，尺度感强，带桁架或环状结构',
  byproduct:  '碎屑或废料堆，形状不规则，颜色灰暗',
  fluid:      '液滴或气泡形态，半透明',
};

/* ---------- 组装提示词 ---------- */

function _joinParts(parts){ return parts.map(p=>'· '+p).join('\n'); }

/**
 * 建筑 / 机器的生成描述词
 * @param {object} m  machine 数据
 * @param {object} opt {target:'3d'|'concept', lang:'zh'|'en', withTech:bool}
 */
function machinePrompt(m, opt){
  opt = opt || {};
  const st = getStyle();                       // 风格引擎（js/core/style.js）
  const brief = MACHINE_BRIEFS[m.id] || {};
  const cat = CATEGORY_STYLE[m.cat] || {};
  const form = brief.form || cat.silhouette || '方盒状工业建筑';
  const parts = brief.parts || cat.parts || ['主体', '底座'];
  const fp = m.footprint || '1×1';

  // 配色：优先用 MACHINE_BRIEFS 手写的文字描述（"锈红""深钢灰"这类质感词有用），
  // 但把里面的十六进制色值校正进风格带 —— 保留质感，统一色值。
  let palette;
  if(brief.palette){
    palette = fitBriefPalette(brief.palette, st).text;
  }else{
    palette = `${accentFor(m.cat, st)}（强调）+ ${st.palette.structure}（结构）`
            + ` + ${st.palette.metal}（主体金属）`;
  }

  let p = '';
  p += `【主体】${st.form.body}的${brief.subject || '工业建筑'}：${m.name}（${m.cat}类，占地 ${fp} 格）\n`;
  p += `【形态】${form}\n`;
  p += `【必须包含的部件】\n${_joinParts(parts)}\n`;
  p += `【配色】${palette}\n`;
  if(brief.note) p += `【关键细节】${brief.note}\n`;
  // 风格约束（精简版，完整版在风格页/导出里）
  p += styleBrief(st, { withNegative:false });
  if(opt.withTech !== false){
    p += `【技术规格】${brief.spec || st.spec.machine}\n`;
    p += `【负向】${st.negative.join('、')}\n`;
  }
  return p;
}

/**
 * 物品（道具/图标）的生成描述词
 */
function itemPrompt(it, opt){
  opt = opt || {};
  const st = getStyle();
  const form = ITEM_FORM[it.visual || it.type] || '小型物件';
  const kind = typeLabel(it.type);
  // 用风格校正后的颜色，保证「图标看到的」=「让 AI 生成的」
  const fit = itemFitColor(it, st);

  let p = '';
  p += `【主体】${st.form.body}的游戏物品：${it.name}（${kind}，T${it.tier}）\n`;
  p += `【形态】${form}\n`;
  p += `【配色】主色 ${fit.hex}${it.desc ? '；' + it.desc : ''}\n`;
  p += styleBrief(st, { withNegative:false });
  if(opt.withTech !== false){
    p += `【技术规格】${st.spec.item}\n`;
    p += `【负向】${st.negative.join('、')}\n`;
  }
  return p;
}

/**
 * 元素（周期表图标）的生成描述词
 */
function elementPrompt(el, opt){
  opt = opt || {};
  const st = getStyle();
  const fit = fitColor(el.color || '#888780', 'accent', st);
  const symbol = el.symbol || el.id;

  let p = '';
  p += `【主体】${st.form.body}风格的元素图标：${el.name}（${symbol}，T${el.tier}）\n`;
  p += `【形态】2D 游戏图标，圆角方形底板，居中元素符号 ${symbol}，底部小字名称，右上角等级角标\n`;
  p += `【配色】主色 ${fit.hex}\n`;
  p += styleBrief(st, { withNegative:false });
  if(opt.withTech !== false){
    p += `【技术规格】${st.spec.item}\n`;
    p += `【负向】${st.negative.join('、')}\n`;
  }
  return p;
}

/* ---------- 等轴测体块预览 ----------
   不生成模型文件，只在界面上用 SVG 画一个体块，
   让设计者能直观看到「占地尺寸 + 体量比例」是否合理。
   支持 4 个 90° 转角。
   ---------------------------------------- */

// 每个分类的体块构成：[dx, dy, w, d, h, z0, tone]
// 坐标单位 = 格，原点在 footprint 中心
const CATEGORY_MASSING = {
  '采集': [
    [0,0, 0.92,0.92, 0.22, 0,      'base'],
    [0,0, 0.30,0.30, 1.55, 0.22,   'body'],
    [0,0, 0.16,0.16, 1.95, 0.22,   'accent'],
  ],
  '分离': [
    [0,0, 0.94,0.94, 0.18, 0,      'base'],
    [-0.22,-0.10, 0.42,0.42, 0.85, 0.18, 'body'],
    [0.24,0.14, 0.38,0.38, 0.62, 0.18,   'body'],
    [0,0, 0.14,0.62, 0.10, 1.02,   'accent'],
  ],
  '冶炼': [
    [0,0, 0.94,0.94, 0.25, 0,      'base'],
    [-0.08,0, 0.56,0.56, 1.25, 0.25, 'body'],
    [0.26,0.22, 0.18,0.18, 1.85, 0.25, 'accent'],
  ],
  '合金': [
    [0,0, 0.94,0.94, 0.20, 0,      'base'],
    [-0.34,-0.28, 0.14,0.14, 1.15, 0.20, 'body'],
    [0.34,0.28, 0.14,0.14, 1.15, 0.20,   'body'],
    [0,0, 0.72,0.16, 0.16, 1.35,   'body'],
    [0,0, 0.22,0.22, 0.50, 0.85,   'accent'],
  ],
  '化工': [
    [0,0, 0.94,0.94, 0.16, 0,      'base'],
    [-0.24,-0.16, 0.34,0.34, 0.95, 0.16, 'body'],
    [0.22,-0.20, 0.30,0.30, 0.78, 0.16,  'body'],
    [0.12,0.24, 0.28,0.28, 1.10, 0.16,   'body'],
    [0,0, 0.68,0.10, 0.08, 1.05,   'accent'],
  ],
  '加工': [
    [0,0, 0.94,0.94, 0.20, 0,      'base'],
    [0,0, 0.70,0.42, 0.35, 0.20,   'body'],
    [-0.30,-0.20, 0.12,0.12, 0.85, 0.20, 'accent'],
    [0.30,-0.20, 0.12,0.12, 0.85, 0.20,  'accent'],
    [0,0, 0.72,0.12, 0.12, 1.00,   'accent'],
  ],
  '组装': [
    [0,0, 0.96,0.96, 0.24, 0,      'base'],
    [0,0, 0.80,0.80, 0.78, 0.24,   'body'],
    [0,0, 0.50,0.50, 0.22, 1.02,   'accent'],
  ],
  '回收': [
    [0,0, 0.94,0.94, 0.18, 0,      'base'],
    [0,0, 0.34,0.34, 0.45, 0.18,   'base'],
    [0,0, 0.56,0.56, 0.92, 0.63,   'body'],
    [0.24,0.20, 0.14,0.14, 1.45, 0.63, 'accent'],
  ],
};

// 单个资产的体块覆盖：分类体块描述不出具体物件时按 id 定制
const MACHINE_MASSING = {
  MC_CAR: [
    [-0.325, 0.38, 0.14, 0.14, 0.52, 0.02, 'dark'],
    [-0.325,-0.38, 0.14, 0.14, 0.52, 0.02, 'dark'],
    [ 0.325, 0.38, 0.14, 0.14, 0.52, 0.02, 'dark'],
    [ 0.325,-0.38, 0.14, 0.14, 0.52, 0.02, 'dark'],
    [0,0, 0.86,0.84, 0.52, 0.34, 'body'],
    [0.03,0, 0.49,0.75, 0.42, 0.86, 'glass'],
    [0.03,0, 0.45,0.69, 0.07, 1.28, 'body'],
    [ 0.44,0, 0.04,0.80, 0.16, 0.36, 'dark'],
    [-0.44,0, 0.04,0.80, 0.16, 0.36, 'dark'],
    [ 0.435, 0.27, 0.03,0.20, 0.10, 0.62, 'hot'],
    [ 0.435,-0.27, 0.03,0.20, 0.10, 0.62, 'hot'],
    [-0.455, 0.27, 0.03,0.20, 0.10, 0.62, 'hot'],
    [-0.455,-0.27, 0.03,0.20, 0.10, 0.62, 'hot'],
  ],
};

// 分类配色（体块用）—— 保留作为兜底，实际渲染走风格引擎的 stylePalette()
const MASSING_TONE = {
  base:   {top:'#c9c6bf', left:'#9d9a93', right:'#b5b2ab'},
  body:   {top:'#a8adb5', left:'#7c8188', right:'#9299a1'},
  accent: {top:'#ef9f27', left:'#b8761a', right:'#d68d21'},
  hot:    {top:'#e07b39', left:'#a85626', right:'#c66a30'},
  dark:   {top:'#5c626b', left:'#34383f', right:'#484e56'},
  glass:  {top:'#a9c7dc', left:'#6f93aa', right:'#8cb0c6'},
};
// 按分类给体块染色（风格引擎不可用时兜底）
const CATEGORY_TONE = {
  '采集':'#c9a227', '分离':'#6fa8c4', '冶炼':'#e07b39', '合金':'#9aa8b8',
  '化工':'#7fc47f', '加工':'#8a97a8', '组装':'#3fa887', '回收':'#b09a6a',
};

/** 把一个颜色拆成等轴测体块的三个面（顶面亮、左面暗、右面中） */
function toneFaces(hex){
  return { top: shade(hex, 7), left: shade(hex, -27), right: shade(hex, -13) };
}

/**
 * 画一个等轴测体块预览
 * @param {object} m machine
 * @param {number} rot 0..3  每次 +90°
 * @param {number} size 画布边长
 */
function isoPreview(m, rot, size){
  rot = rot || 0; size = size || 168;
  const fp = String(m.footprint || '1×1').split(/[×xX]/).map(n=>parseFloat(n)||1);
  const W = fp[0], D = fp[1] || fp[0];
  const blocks = MACHINE_MASSING[m.id] || CATEGORY_MASSING[m.cat] || CATEGORY_MASSING['加工'];

  // 配色跟随当前风格（风格引擎没加载时兜底到 CATEGORY_TONE）
  let accentBase, faceBase, faceBody, faceHot, faceDark, faceGlass;
  if(typeof getStyle === 'function'){
    const st = getStyle();
    accentBase = accentFor(m.cat, st);
    faceBase   = toneFaces(st.palette.structure);
    faceBody   = toneFaces(st.palette.metal);
    faceHot    = toneFaces(st.palette.glow);
    faceDark   = toneFaces(st.palette.metalDark);
    faceGlass  = toneFaces(st.palette.glass);
  }else{
    accentBase = CATEGORY_TONE[m.cat] || '#8a97a8';
    faceBase = MASSING_TONE.base; faceBody = MASSING_TONE.body; faceHot = MASSING_TONE.hot;
    faceDark = MASSING_TONE.dark; faceGlass = MASSING_TONE.glass;
  }

  // 视野自适应：格数越大缩放越小
  const scale = size / (Math.max(W,D) * 2.6 + 3.2);
  const cx = size/2, cy = size*0.66;

  const rotXY = (x,y)=>{
    switch(rot & 3){
      case 1: return [-y, x];
      case 2: return [-x, -y];
      case 3: return [y, -x];
      default: return [x, y];
    }
  };
  // 等轴投影
  const P = (x, y, z)=>{
    const [rx, ry] = rotXY(x, y);
    return [ cx + (rx - ry) * 0.866 * scale,
             cy + (rx + ry) * 0.5 * scale - z * scale ];
  };
  const poly = (pts, fill, stroke)=>{
    return `<polygon points="${pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}" `
         + `fill="${fill}" stroke="${stroke||'rgba(0,0,0,.22)'}" stroke-width=".7"/>`;
  };

  // 按「深度」排序，远的先画（painter's algorithm）
  const items = blocks.map((b, i)=>{
    const [dx,dy,w,d,h,z0,tone] = b;
    const [rx, ry] = rotXY(dx*W, dy*D);
    return {b, depth: rx + ry, i};
  }).sort((a,b2)=> a.depth - b2.depth);

  let svg = '';
  items.forEach(({b})=>{
    const [dx,dy,w,d,h,z0,tone] = b;
    // 坐标换算到「格」单位
    const x0 = dx*W, y0 = dy*D;
    const hw = (w*W)/2, hd = (d*D)/2;
    const col = tone==='accent'
      ? {top:accentBase, left:shade(accentBase,-28), right:shade(accentBase,-14)}
      : tone==='hot' ? faceHot
      : tone==='base' ? faceBase
      : tone==='dark' ? faceDark
      : tone==='glass' ? faceGlass
      : faceBody;

    const c = [[-hw,-hd],[hw,-hd],[hw,hd],[-hw,hd]];
    const top = c.map(([ddx,ddy])=>P(x0+ddx, y0+ddy, z0+h));
    const right = [P(x0+hw, y0-hd, z0+h), P(x0+hw, y0+hd, z0+h), P(x0+hw, y0+hd, z0), P(x0+hw, y0-hd, z0)];
    const left  = [P(x0-hw, y0+hd, z0+h), P(x0+hw, y0+hd, z0+h), P(x0+hw, y0+hd, z0), P(x0-hw, y0+hd, z0)];

    svg += poly(left, col.left);
    svg += poly(right, col.right);
    svg += poly(top, col.top);
  });

  // 地面网格（footprint 轮廓）
  const gridPts = [
    P(-W/2,-D/2,0), P(W/2,-D/2,0), P(W/2,D/2,0), P(-W/2,D/2,0)
  ];
  const grid = `<polygon points="${gridPts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}" `
             + `fill="rgba(0,0,0,.045)" stroke="rgba(0,0,0,.25)" stroke-width=".8" stroke-dasharray="3 2"/>`;

  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" `
       + `xmlns="http://www.w3.org/2000/svg">${grid}${svg}</svg>`;
}

// 颜色明暗调整（供体块用，避免依赖 icons.js 的 HSL 实现顺序）
function shadeHex(hex, delta){
  let c = String(hex||'#888780').replace('#','');
  if(c.length===3) c = c.split('').map(x=>x+x).join('');
  const n = parseInt(c,16);
  const cl = v => Math.max(0, Math.min(255, v));
  const r = cl((n>>16) + delta), g = cl(((n>>8)&0xff) + delta), b = cl((n&0xff) + delta);
  return '#' + [r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');
}
