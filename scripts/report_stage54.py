"""Render complete D/E/F metrics and automatic layers without touching inference."""
import json
from run_stage54 import ROOT,OUT


def main():
 rows=json.loads((OUT/'evaluation/comparison.json').read_text(encoding='utf-8'));summary=json.loads((OUT/'evaluation/summary.json').read_text(encoding='utf-8'));layers=json.loads((OUT/'evaluation/ablation.json').read_text(encoding='utf-8'))
 changes=json.loads((OUT/'evaluation/ranking_changes.json').read_text(encoding='utf-8'));near=json.loads((OUT/'evaluation/existing_points.json').read_text(encoding='utf-8'))
 def n(v,d=2):return '—' if v is None else f'{v:.{d}f}'
 def hit(r,k):return r.get('topk',r.get('preferred_topk_hits',{})).get(str(k),False)
 text=['# Stage 5.4：单图自动空间关系与多假设排序评估','',
 '本轮仅使用原冻结12新增照片+2旧例、原视觉/地图JSON及同SHA本地OSM快照。规则和源码先固定，通过合成与无真值排序测试后正式比较一轮；全部推理结果冻结后才读自报Camera location。没有新视觉或OSM请求，没有人工身份确认输入。旧development和已查看holdout标记保持，不作独立泛化验证。','',
 '## 全部新增样本汇总','', '| 算法 | 总数 | 有效Top1 | 中位m | P90m | Top3/5/10包含数（分母12） |','|---|---:|---:|---:|---:|---|']
 for r in summary:
  if r['split']=='all_new':text.append(f"| {r['algorithm']} | {r['total']} | {r['valid']} | {n(r['median_m'])} | {n(r['p90_m'])} | {'/'.join(str(r['topk'][str(k)]) for k in (3,5,10))} |")
 text+=['','## 全部逐照片D/E/F','',
 '| 样本 | 组 | Top1m | 最近优选m | 优选面积km² | 区域数 | 包含排名 | Top3/5/10 | 秒 | 状态 |','|---|---|---:|---:|---:|---:|---|---|---:|---|']
 for key in dict.fromkeys(r['case'] for r in rows):
  for algo in ('D','E','F'):
   r=next(x for x in rows if x['case']==key and x['algorithm']==algo);area=r.get('preferred_area_m2')
   text.append(f"| {key} | {algo} | {n(r.get('top1_point_distance_m'))} | {n(r.get('nearest_region_distance_m'))} | {n(area/1e6 if area is not None else None,3)} | {r.get('output_regions',r.get('candidate_regions','—'))} | {r.get('containing_ranks','—')} | {'/'.join('是' if hit(r,k) else '否' for k in (3,5,10))} | {n(r.get('seconds'),3)} | {r.get('status',r.get('failure_stage','UNAVAILABLE'))} |")
 text+=['','## 自动关系确实是否改变排序','', '| 样本 | 同几何模式 | 共同模式排名变化 | 新保留/丢弃模式 | 关系分最小/均值/最大 | 可用视觉关系（跨身份） |','|---|---:|---:|---|---|---:|']
 for c in changes:
  r=next(r for r in rows if r['case']==c['case'] and r['algorithm']=='F');d=r['relation_distribution']
  text.append(f"| {c['case']} | {c['common_modes']} | {c['changed_common_ranks']} | {c['new_modes']}/{c['dropped_modes']} | {n(d['min'],3)}/{n(d['mean'],3)}/{n(d['max'],3)} | {d['usable_visual_relations']} |")
 text+=['','模式以身份ID+规范化几何SHA对应，不用会随保留顺序变化的区域ID对应；新/丢弃和共同模式排序变化分开报告。全体点×身份的分布可能被UNKNOWN的0.5稀释，不能以范围0～1就声称可靠区分了正确机位。原几何分档优先，关系只能在同档内作用。','',
 '## A0/A1/A2 全样本','', '| 样本 | 层 | 面积km² | 含参考 | 最近m | 通过/实际点 |','|---|---|---:|---|---:|---|']
 for r in layers:
  a=r['area_m2'];c=r['reference_contains'];text.append(f"| {r['case']} | {r['stage']} | {n(a/1e6 if a is not None else None,3)} | {'—' if c is None else ('是' if c else '否')} | {n(r.get('nearest_region_distance_m'))} | {r.get('passed_points','—')}/{r.get('actual_points','—')} |")
 text+=['','A1=A0，只有软评分，没有虚构面积收缩。A2直接使用F实际有界输出，不冒充物理可行层。几何面积用局部米制，点数是点×身份记录；优选成员数不是唯一空间点数量。A0仍是E自适应网格的条件总体，并非独立的全球纯语义搜索。','', '## 重点案例与失败归因','']
 for key in ('photo_02','legacy_north_bund','legacy_beijing_cbd','photo_04'):
  e=next(r for r in rows if r['case']==key and r['algorithm']=='E');f=next(r for r in rows if r['case']==key and r['algorithm']=='F')
  text.append(f"- {key}：E→F包含排名 {e.get('containing_ranks')}→{f.get('containing_ranks')}；Top1 {n(e.get('top1_point_distance_m'))}→{n(f.get('top1_point_distance_m'))}m；最近优选 {n(e.get('nearest_region_distance_m'))}→{n(f.get('nearest_region_distance_m'))}m。")
  pts=next(r for r in near if r['case']==key)['existing_points']
  if pts:
   p=pts[0];text.append(f"  最近已有采样点距参考{p['distance_m']:.2f}m，原可行={p['feasible']}，原分={p['score']}，自动关系分={p['relation_score']}，F处置={p['selection_stage']}，原拒绝原因={p['reasons']}。没有在参考位置增采样或重评分。")
 text+=['',
 'photo_04的原站立约束保持；自动关系无法复活物理硬拒绝点。北京与北外滩的几何/身份多解及大规模同分模式仍受预算限制。近参考已有样点的分数、每边权重/一致性、身份组合、原投影分项及截断审计保留在evaluation/existing_points.json和完整F pose；单一样点不证明连续参考位置的物理可行性。',
 'photo_01/03为历史API失败，未重试；photo_09无具体身份、photo_11单独可靠锚不足，保留低证据而非零米；photo_12远景与5km先验不适配。没有改变参考坐标、原身份候选或物理/FOV设置。','',
 '## 改善、退化与未解决问题','']
 for key in dict.fromkeys(r['case'] for r in rows):
  e=next(r for r in rows if r['case']==key and r['algorithm']=='E');f=next(r for r in rows if r['case']==key and r['algorithm']=='F');a=e.get('top1_point_distance_m');b=f.get('top1_point_distance_m')
  text.append(f"- {key}："+('无有效Top1，不计算改善。' if a is None or b is None else ('改善' if b<a-1e-3 else '退化' if b>a+1e-3 else '基本不变')+f'，Top1差值F−E={b-a:.2f}m。'))
 text+=['',
 '空间关系若只改变同档顺序，不保证米级误差下降；身份混淆、partial OSM、2D宽角区间、未知实际可见部分/内参和自报机位精度限制仍存在。自动权重不是独立身份证明，也不是正确位置概率。结果无论好坏均保持本轮规则，未按参考反复调参。','',
 '## 端到端、Demo与实际执行','',
 'LocalizationPipeline默认F，run只接收一张图片路径；Mock验证真实地图匹配、联合身份搜索、关系排序、A层输出和重复图片一次有效视觉调用。缺地图/Key、无身份和单锚继续明确报错或证据不足。旧显式配置/开关保留，离线按版本选择。',
 '[实际命令、失败和pytest](evaluation/stage5_4/VALIDATION.md) · [自动规则](STAGE5_4_AUTOMATIC_RELATIONS.md) · [完整JSON](evaluation/stage5_4/evaluation/comparison.json)。Demo截图与浏览器验收位于demo/，参考默认隐藏、仅主动评估显示。照片和OSM许可沿用[原清单](evaluation/real_camera_diagnostics/ATTRIBUTION.md)。']
 (ROOT/'docs/STAGE5_4_EVALUATION.md').write_text('\n'.join(text)+'\n',encoding='utf-8')

if __name__=='__main__':main()
