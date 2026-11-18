"""Stage 5.2 reports from frozen outputs, including failures and counterexamples."""
import json
from pathlib import Path
from run_stage52 import ROOT,OUT


def load(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def fmt(x,n=2):return '—' if x is None else f'{x:.{n}f}'
def km(x):return fmt(x/1e6,3) if x is not None else '—'
def hits(r):
 v=r.get('topk',r.get('preferred_topk_hits'))
 return '无排名/未运行' if v is None else '/'.join('是' if v.get(str(k),False) else '否' for k in (3,5,10))


def main():
 comparison=load('evaluation/comparison.json');layers=load('evaluation/refinement.json');summary=load('evaluation/summary.json');checks=load('inference_checks.json')
 main=['# Stage 5.2：区域筛选修复与空间精化验收','',
 '本阶段使用上一阶段冻结的12张新增照片（9张明确多地标、3张压力样本）及2张旧例。保持development/holdout原划分；这些holdout已被查看，只用于回归/诊断，不作独立泛化证明。所有Camera location均为Q2自报，测量误差界未知。没有新增视觉/API请求或地图下载，也没有三维/连续优化。','',
 '## 对导师三个问题的回答','',
 '1. **语义检索能建立有限初始范围，但不是机位答案。** S0使用地图实体身份组合、固定5km观察距离和有限共同采样覆盖；多身份、普通楼和超距照片仍失败。建筑中心从不当摄影者位置。','',
 '2. **相对关系可以缩小条件候选域，但真实收益受身份和关系可靠性限制。** 逐身份收缩与多身份并集均报告；并集中的弱约束假设可能抵消强约束假设收益。确有缩小后排除参考点的失败，不把面积变小当作成功。','',
 '3. **完整精化更集中，但不能保证保留正确位置或改善Top-1。** E修复质量优先机制，仍有不可区分的同分模式超过预算；S2的缩小混合了物理约束、视场/投影评分和有限优选，不全归功左右关系。实际数据如下，未反复调参追成绩。','',
 '## 根因、策略与有界取舍','',
 '旧diversified_regions选第一个高分模式后主要按空间最远距离，允许低分远处模式挤掉其他高分模式。新E保持D采样/评分/身份组合不变，只替换最终保留与排序：分数保留六位小数形成数值近似并列档→轮廓几何质量→独立坐标可靠地标数量；同质量档内部才使用空间分散。它不是校准概率，也没有把0.005任意当作同分。','',
 '同档相交/相接模式可作精确并集，仅在单Polygon且合并面积不超过原750m分片面积时合并；不做凸包、不加buffer、不跨不相接位置合并。每身份最多8区域、最多12身份；每区最大0.5625km²，全局上限96区域，仍可能遗漏高分模式。对被保留面覆盖的重复模式不再占额度。','',
 '平局顺序以高分已有样点的毫米级坐标键为准，哈希仅为审计标识；多样性距离同样按毫米稳定化。初版用几何哈希排序，新增测试证明1e-8m扰动会改变模式，因此修复此数值稳定性Bug后重跑一次最终E，未改权重/距离/FOV/数量预算。初版源与完整指标保存在development_initial/，原始临时压缩输出保留在本机.cache/stage52_initial/。此规则不保证任意量化边界扰动下绝对不变。','',
 '完整selection_audit记录所有原模式合并来源、区域界、最佳已有点、几何SHA、质量、面积、保留/丢弃原因、同分超额证据。无法同时保证面积紧凑、包含所有高分模式和数量有界：本实现守面积/数量预算，明确报告未保留模式，不宣称全保留。','',
 '## 实验公平性与兼容','',
 'A/B/C/D直接引用冻结旧结果，文件未改。E使用同一OSM SQLite SHA、原始vision/matches及D配置，仅selection_strategy不同。逐例严格比较全体采样坐标/phase/分数/分项和Feasible：均相同。旧默认strategy=legacy；Stage52PoseSolver明确启用E，旧Solver仍可复现旧结果。新增字段兼容旧JSON，历史原始文件字节保持。','',
 'E耗时为本次完整solve（含搜索、区域、后置可见性），旧A/B/C/D耗时是历史测量，不能作同环境加速结论。S0/S1/S2复用E分数，其附加时间另列，不能当完整在线延迟。','',
 '| 集合 | 组 | 有效Top-1/总数 | 中位m | P90m | Top3/5/10区域命中 |','|---|---|---|---:|---:|---|']
 for r in summary:
  main.append(f"| {r['partition']} | {r['algorithm']} | {r['valid']}/{r['total']} | {fmt(r['median_m'])} | {fmt(r['p90_m'])} | "+'/'.join(f"{r['topk'][str(k)]['hits']}/{r['total']}" for k in (3,5,10))+' |')
 main+=['','## 北京、北外滩与photo_02重点结果','', '| 样本 | 组 | Top1m | 最近Preferredm | Preferred km² | 包含排名 | 全局最高质量仍遗漏模式数 |','|---|---|---:|---:|---:|---|---:|']
 for r in comparison:
  if r['case'] in ('legacy_beijing_cbd','legacy_north_bund','photo_02') and r['algorithm'] in ('D','E'):
   main.append(f"| {r['case']} | {r['algorithm']} | {fmt(r.get('top1_point_distance_m'))} | {fmt(r.get('nearest_region_distance_m'))} | {km(r.get('preferred_area_m2'))} | {r.get('containing_ranks',[])} | {r.get('globally_top_quality_omitted','旧版本未记录')} |")
 main+=['','包含参考点但排名较后/面积较大，不构成精确定位成功。E若Top-1未改善或更差，保留该失败；不会据此再调策略。局部最高质量遗漏总数与全局最高质量遗漏分开统计，不能把各身份弱假设的局部最高分说成整张图最高分。','',
 '## 所有样本A/B/C/D/E与失败','', '| 样本 | 组 | 状态 | Top1m | 最近Preferredm | Preferred km² | Top3/5/10 | 区域数 | 秒 |','|---|---|---|---:|---:|---:|---|---:|---:|']
 for r in sorted(comparison,key=lambda r:(r['case'],r['algorithm'])):
  main.append(f"| {r['case']} | {r['algorithm']} | {r.get('status',r.get('stage','未执行'))} | {fmt(r.get('top1_point_distance_m'))} | {fmt(r.get('nearest_region_distance_m'))} | {km(r.get('preferred_area_m2'))} | {hits(r)} | {r.get('output_regions',r.get('candidate_regions','—'))} | {fmt(r.get('seconds'),3)} |")
 main+=['','photo_01/03仍为原视觉超时，无几何结果；photo_09普通场景无身份、photo_11单可靠锚点，保持证据不足；不填0米。远景photo_12与5km距离先验不适配，不能改参考点掩盖。身份混淆、错误地图候选与旧失败沿用上一阶段逐例记录，未改原视觉JSON。','',
 '所有单区域面积、Feasible覆盖与面积、区域数、截断原因/最高质量遗漏及点证据在evaluation/comparison.json、E_point_diagnostics.json和完整E输出；源输入与配置/网格SHA在inference_checks.json和inference_manifest.json。','',
 '## Demo与API','',
 '新增“空间精化离线”模式：照片/识别→地图实体→S0/S1/S2图层与面积/缩减率，另列E物理可行与软关系优选层。参考点只在明确勾选独立评估时加载并叠加，在线推理不接收。在线原功能保留，可选启用Stage5.2并复用已有视觉缓存。','',
 '浏览器验收修复了实际阻断Bug：streamlit-folium通过dependency URL执行脚本，不执行旧内联header脚本，曾出现L未定义空白地图。改用已有本地Leaflet/jQuery/CSS的data URL依赖，静态导出和组件都不访问CDN。无新增项目运行依赖。','',
 '[实际浏览器验收](evaluation/stage5_2/demo/browser_acceptance.json)、[截图](evaluation/stage5_2/demo/offline_refinement_photo02.png)、[页面概览](evaluation/stage5_2/demo/offline_refinement_overview.png)、[自包含离线地图](evaluation/stage5_2/demo/refinement_photo_02.html)。','',
 'Python：Stage52PoseSolver(store, PoseSearchConfig(record_diagnostic_trace=True)).solve(vision,matching)；build_spatial_refinement(vision,matching,pose,bounds)给出经过Pydantic校验的同网格层。单个可靠地标不制造精确机位。','',
 '## 未解决与最小后续项','',
 '大量零残差同分解、身份/坐标可靠性区别、误匹配及2D/视场假设仍限制结果。仅精确名称和完整轮廓也不等于真实身份确认，S1存在收缩后丢参考的反例。先独立验证身份和相机参考质量，再评估同分模式的紧凑表示；不引入3D重建/连续优化，不按个别参考点调权重。数值稳定修复与机制修复不能当作泛化提升。','',
 '[完整空间消融](STAGE5_2_SPATIAL_ABLATION.md)；[实际命令、失败与测试](evaluation/stage5_2/VALIDATION.md)。照片署名沿用[来源](evaluation/real_camera_diagnostics/ATTRIBUTION.md)，OSM © OpenStreetMap contributors / ODbL。']
 (ROOT/'docs/STAGE5_2_EVALUATION.md').write_text('\n'.join(main)+'\n',encoding='utf-8')
 spatial=['# Stage 5.2 同网格S0/S1/S2空间关系消融','',
 '这是条件消融，不是全球检索精度评估。共同总体来自已冻结D/E实际自适应搜索：身份、距离域、粗/细/补充坐标相同，细网格曾受完整几何引导。S0算子不再使用图像左右/朝向/投影筛点，但不能将这套共同总体当作独立生成的纯语义搜索器。未访问的连续空间仍未知；不能把采样覆盖损失归因空间关系。','',
 '对每身份h，在相同局部AEQD米制系：S0_h = union(所有距离合格既有样点的粗/细单元) ∩ 原固定距离搜索域；不应用建筑/水域站立掩膜。S1_h = union(保守关系未冲突的相同样点单元) ∩ S0_h。S2_h = 在S1通过样点上复用完整几何分数、原物理掩膜和E选择 ∩ S1_h。每城市先取身份并集再计算面积，三个不交验证城市相加；不是简单叠加重叠面积。','',
 '因此局部米制S2⊆S1⊆S0；GeoJSON转WGS84直线弦后再次作交集保证展示包含关系。S2与保留软顺序的E Preferred不同，不能混为D/E对照组。区域面积按原米制几何，不按平方度计算。','',
 'S1门控：坐标可靠、模型身份明确、主名称精确命中、完整有效建筑/塔/桥等面轮廓；互逆边去重，显式关系与x冲突时不使用该对。比较完整角区间的顺时针短弧顺序，未知朝向，绝不将地图东西直接当图像左右。重叠、反向、包围观察者、缺轮廓、身份不确定均为不可判定并保留。精确词义门控仍不证明身份正确。','',
 'S0/S1无排名，Top1不存在，Top-K=null。S2按E质量策略排名但分数不为概率。实际点数为同一距离合格总体（先共同排除距离先验不符点）；逐身份同时保存原访问数/距离拒绝数、可信关系/冲突/不可定计数。可靠地标数是参与假设的坐标可靠图像ID并集，不是人工确证身份数；可信关系锚在逐身份trusted_landmarks单列。','',
 '复用记录使用1e-6m采样坐标，完整原分数未重新拟合。传输后极小无效环只允许逐组件make_valid后精确并集，面积变化不得超过max(1e-4m²,原面积1e-9)；大改动拒绝，不加buffer。整块MultiPolygon偶奇填充可能错误擦除大片区域，故有组件修复回归。geometry_repairs保存每次变化。','',
 'S2阶段耗时只为缓存分数后的附加构造；另列E完整solve时间。完整端到端还包括视觉、匹配与显示，未重调付费模型。','',
 '| 样本 | 层 | 面积km² | 相对上层缩小 | 含参考 | 最近区域m | 点数/通过 | 可靠ID/关系 | Top3/5/10 | 附加秒 |','|---|---|---:|---:|---|---:|---|---|---|---:|']
 for r in layers:
  reduction=r.get('reduction_from_previous');ratio='—' if reduction is None else f'{reduction:.2%}'
  contains='未运行' if r['reference_contains'] is None else '是' if r['reference_contains'] else '否'
  spatial.append(f"| {r['case']} | {r['stage']} | {km(r['area_m2'])} | {ratio} | {contains} | {fmt(r['nearest_region_distance_m'])} | {r.get('actual_points','—')}/{r.get('passed_points','—')} | {r.get('reliable_landmarks','—')}/{r.get('reliable_relations','—')} | {hits(r)} | {fmt(r.get('phase_seconds'),3)} |")
 positive=[r for r in layers if not r['case'].startswith('legacy_') and r['stage']=='S0' and (r['area_m2'] or 0)>0]
 reductions=[r for r in layers if not r['case'].startswith('legacy_') and r['stage']=='S1' and (r['area_m2'] or 0)>0]
 spatial+=['','## 条件收益与失败','',f"新增照片中共同总体非空{len(positive)}/12；S0覆盖参考{sum(r['reference_contains'] for r in positive)}/{len(positive)}。S1在{sum((r.get('reduction_from_previous') or 0)>1e-9 for r in reductions)}/{len(reductions)}个非空例中缩小并集，覆盖参考{sum(r['reference_contains'] for r in reductions)}/{len(reductions)}。空/超时与单锚例均单列，不当成0米成功。",'',
 '逐身份S1面积往往比多身份并集收缩更多：UNKNOWN/弱身份假设可保留宽域。完整每身份前后面积在evaluation/refinement.json，不仅展示选定正确身份的最好结果。','',
 'photo_04说明强缩小也能错排自报位置；photo_08和北京旧例没有通过门控的可靠关系，S1没有收益；photo_12在S0已被固定距离先验排除。photo_02和北外滩旧例要同时检查S1保留与S2保留、面积和Top-K，不把S2全部缩小量归功左右关系。','',
 '本轮已经查看原holdout，统计只描述这批案例。约束真值误差、身份混淆及未校准视场仍可能让精化丢掉正确位置；不能声称相对关系总能安全缩小范围。','',
 '[主报告与D/E对照](STAGE5_2_EVALUATION.md)、[原始结果](evaluation/stage5_2/evaluation/refinement.json)。']
 (ROOT/'docs/STAGE5_2_SPATIAL_ABLATION.md').write_text('\n'.join(spatial)+'\n',encoding='utf-8')

if __name__=='__main__':main()
