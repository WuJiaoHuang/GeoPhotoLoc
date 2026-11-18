"""Render causal evidence from saved traces and explicitly separate hypotheses."""
import json
from pathlib import Path
from run_camera_benchmark import ROOT,OUT,save

def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def fmt(x):return '—' if x is None else f'{x:.2f}'

def main():
 metrics=read('post_evaluation/metrics.json');audits=read('post_evaluation/detailed_score_audits.json');review=read('post_review.json')
 evidence=[]
 text=['# 粗定位误差根因分析','',
 '本报告使用冻结结果后评估；没有按参考坐标改变任何评分、范围、分片、区域数量上限或 OSM 匹配。相机坐标为Q2自报，以下“误差”只表示到该来源坐标的偏差。200m是统一诊断邻域，不是成功验收阈值。点数为点–身份组合记录，可能重复同一地理位置，不是独立拍摄点数量。','',
 '## 已确认：区域上限确实丢弃高分或同分的参考点附近候选','',
 'D 的 750m 分片先使用各自局部分数窗口；随后 diversified_regions 每身份仅留8个模式。优选首个高分模式后，空间最远点多样性选择不保证保留其余高分或同分模式。这是现有策略的可复现实验缺陷，尚不能据此断言某一替换策略能提高泛化精度。本阶段保持算法不变。','',
 '| 样本 | 最近已搜索点 m | 200m内阶段计数（点–身份记录） |','|---|---:|---|']
 for a in audits:
  if a['group']!='joint_full':continue
  text.append(f"| {a['case']} | {fmt(a['nearest_sample_m'])} | {json.dumps(a['nearby_stage_counts'],ensure_ascii=False)} |")
  examples=[(h['hypothesis_id'],e) for h in a['hypotheses'] for e in h.get('examples',[]) if e['distance_m']<=200 and e['trace'].get('feasible')]
  if examples:
   hid,near=max(examples,key=lambda pair:pair[1]['trace']['score']);top=a['top1']['best_score'] if a['top1'] else None
   evidence.append(dict(case=a['case'],hypothesis_id=hid,nearby_best=near,top1_score=top,
       score_difference=(top['score']-near['trace']['score']) if top else None,
       interpretation='Global rank lower bound uses strictly greater scores; rank 1 can be a multi-way tie, never proves uniqueness'))
 text+=['','### 北京旧例：搜索、硬约束与窗口均不是主要丢失环节','',
 'D最近实际样点68.24m；附近7条物理可行记录全被 region_cap 丢弃，没有 below_score_window。该身份4500次搜索→4378物理/视觉通过→4371满足窗口并成为模式成员→仅139个成员留在8个区域中。最近点0.39354761，阈值0.31354761；Top-1为0.39854761，相差仅0.005。','',
 '两者投影0.4642857143、身份0.2599047143、几何0.2857142857完全相同，归一化Huber损失都为0；顺序从0.5变0.525，乘0.20恰好贡献0.005。因此单纯增大投影权重不能在这两个零残差位置之间提供新信息。五个UNKNOWN在两处相同，未使用OUTLIER，不能归因为异常点删除。参考附近的全局分数名次下界1378也主要反映大量近似平局，不能等同1377个位置被证明更准确。','',
 'A/B/C/D的Top-1仍为1894.47/3362.40/1894.47/3362.40m。B的巨大Preferred含参考点，D缩小优选集合后反而漏掉；不是以大面积Feasible包含率宣布成功。','',
 '### 北外滩旧例：输出截断、身份与排名同时存在问题','',
 'D参考200m内46条已搜索记录，2条硬拒绝、41条 region_cap、3条preferred；44条物理可行记录无一因分数窗口丢弃。最近已搜索点12.41m。hyp_1例：2000次搜索→1847物理/视觉通过→1825满足窗口/成员→仅29个成员保留在8个区域。','',
 '最近12.41m样点分数0.40396839、高于其窗口0.39045326，却被区域上限丢弃；该假设UNKNOWN包含东方明珠lm_1，并将上海中心lm_2作为OUTLIER，只剩2个可靠坐标锚，不可视为正确身份组合。另一个136.04m样点得分0.58638491、全局名次下界34，同样因上限丢弃；191.47m样点0.59113429被保留，但其单元不包含参考坐标。Top-1为0.61248873，偏差1870.76m，最近Preferred151.27m。','',
 'A/B/C/D Top-1为63.75/1950.68/2104.10/1870.76m。不能把A单例低误差当作身份/相机已正确，也不能把D恢复96区域当精度改善。OUTLIER确实在部分位置删除已知塔楼，而Top-1无需删除，说明机制受空间假设和不确定身份影响；这是可观察的评分偏移，不足以证明应将惩罚改成某个特定数值。','',
 '### 新诊断样本 photo_02：独立新增的并列最高分丢失证据','',
 '四主塔楼身份形态与预先人工清单相容。146.15m样点得分0.97770833，为并列全局最高分（无严格更高的点），投影1、顺序0.9166667、身份0.9775、几何1、Huber损失0，无UNKNOWN/OUTLIER，却因region_cap丢弃。D该图Top-1偏差571.36m、最近Preferred30.60m；附近32条被上限丢弃、6条硬拒绝、2条保留。这个新增案例说明区域保留问题并非只由两个旧例推断。','',
 '同时，同分点分布广说明评分未必可辨识，保留该点也不等于解决Top-1。不能仅通过扩大区域或保留更多模式提高包含率来冒充定位提升。','',
 '## 相机模型：已有不一致线索，仍属假设而非校准','',
 '独立后评估只将两已辨塔楼的OSM代表方向与图像x代入点投影一致性计算，没有生成机位：旧北京隐含水平FOV约34.43°，北外滩约21.79°，都低于固定列表60/75/90/110/130°。结果见camera_assumption_audit.json。','',
 '这不是镜头FOV测量：bbox可见中心不等于OSM代表点投影，建筑角宽、裁切、畸变、俯仰及相机坐标自报误差均未排除；同侧射线可能多解，工具报告较小可行解。不能据此把FOV直接改成21.79或34.43来追求命中。它支持下一阶段先以独立标定/合成投影测试检验相机模型适用范围。','',
 '## 每例视觉/地图证据与仍待验证的解释','']
 for key,notes in review['cases'].items():
  row=next((r for r in metrics if r['case']==key and r['group']=='joint_full'),None)
  text+=['### '+key,'']
  if row:text.append(f"D阶段：`{row['stage']}`；Top-1 {fmt(row['top1_point_distance_m'])}m；最近Preferred {fmt(row['nearest_region_distance_m'])}m。")
  text+=['','已确认：'+ '；'.join(notes['confirmed'])+'。','','仍待验证：'+'；'.join(notes['hypotheses'])+'。','']
 text+=['## 如何解释新增样本失败','',
 'photo_01/03：服务超时，没有视觉结果，四组几何均未执行，不能计成几何失败或填0米。photo_09：只提供通用对象，未猜名，地图候选为空；photo_11：单明确地标且无足够可靠同区锚，拒绝精确输出符合预定边界。','',
 'photo_02：有搜索、有高分、有同分上限丢失。photo_08：最近24.0m，附近15条硬拒绝、19条低于窗口、13条上限丢弃，是混合损失；仅保留区域不能解决全部错误。photo_10：最近56.2m，附近28条全在上限丢失，但附近最高例分数约0.307、名次下界7894，身份漏检/误配和评分也存在，不能都归因截断。','',
 'photo_12：所有实际身份距离搜索域均不包含来源相机点；D Top-1约9592.64m、最近Preferred3661.49m。固定5km域不适配该远距离自报机位/候选组合；不是“已搜索到正确位置但排名差”。其真实逐栋身份尚不确定，不更改参考点或R掩盖失败。','',
 'photo_04/05/06/07属于独立保留集，不给逐点真实位置诊断或据此调参，仅披露原始输出、总体指标与上游身份/阶段审查。photo_06 D排名第2的Preferred包含参考点，但Top-1仍约1397.40m，不能说精确定位成功。photo_05的可见名称错误、photo_07的江/行政区候选都说明语义不确定性仍在。','',
 '## 下一阶段优先项（本阶段未实施）','',
 '1. **region_selection.py / fixed.py 的区域表示与限额**：首先在不读真值的单元/合成场景中证明并列高分模式不会被无说明地丢失，记录区域级而非仅点级流转。对平坦似然区使用诚实的不确定性表示，并同时约束面积和Top-K；不是把上限加大来包含真值。证据最直接：两旧例及新增photo_02。','',
 '2. **robust_scoring.py 的可辨识性与相机假设**：先分析零残差平局、可靠身份和坐标可靠性的区别、不同UNKNOWN/OUTLIER支持数下分数的可比性。用独立校准场景验证FOV范围/部分可见轮廓，分开报告身份先验与空间证据；不能只按两个参考点改0.40/0.20/0.25/0.15。','',
 '3. **maps/matching.py 与视觉证据契约**：针对Citi/CITIC、场馆混淆、同一个实体被不同观测竞争、河流/行政区等非点锚建立独立身份标注和负例测试；保留UNKNOWN，可靠锚点计数目前主要表示坐标/物理独立性，不等于人工确认身份数。photo_04/05/07/08/10/11有实际例证。','',
 '4. **采样与性能**：旧例及新增诊断集已经在参考附近采样，优先级低于保留/可辨识性。长距photo_12属于域假设边界，先定义适用距离，不能按该坐标扩R。性能sample为10s/999样本的B组局部抽样：union_all叶样本355（35.5%），robust assess调用栈551（55.2%），不是全流程占比；A另有bearing循环栈快照。原始folded数据已保存，未为达标关闭逻辑。','',
 '## 已确认与未确认的边界','',
 '已确认：相同输入可复现、窗口后区域上限丢失、零投影残差平局、部分错误名称/候选、固定距离域不覆盖某些来源点、API超时和计算开销。未确认：哪个新权重最优、真实镜头FOV、每个未知楼的唯一身份、屋顶/桥上高度、Q2参考测量误差、任何普遍准确率。','',
 '独立保留集本轮已被评估；若下阶段将其用于方案选择/调参，就应再建未触碰的保留集，不能用同一批成绩宣称泛化提升。全部历史Stage5.1A/Fix/B文件保持原样。']
 save(OUT/'post_evaluation/ranking_evidence.json',evidence)
 (ROOT/'docs/REAL_CAMERA_ROOT_CAUSES.md').write_text('\n'.join(text)+'\n',encoding='utf-8')

if __name__=='__main__':main()
