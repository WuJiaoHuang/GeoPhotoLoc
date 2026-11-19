"""Render all frozen metrics, including failures, without changing inference."""
import json
from run_stage53 import ROOT,OUT


def main():
 rows=json.loads((OUT/'evaluation/metrics.json').read_text(encoding='utf-8'));summary=json.loads((OUT/'evaluation/summary.json').read_text(encoding='utf-8'))
 diagnostics=json.loads((OUT/'evaluation/point_diagnostics.json').read_text(encoding='utf-8'))
 def num(x,d=3):return '—' if x is None else f'{x:.{d}f}'
 lines=['# Stage 5.3：可靠性分级与保守精化评估','',
 '使用原冻结12张新增照片及2张旧例，同一地图SHA、E候选网格、身份组合和完整几何评分。正式推理仅一轮，先固定规则/合成测试，再完成全部推理与SHA冻结，最后独立读取Camera location。没有新视觉或OSM请求。development/holdout已用于历史诊断，不是独立泛化验证；参考均为Q2摄影者自报、精度未知。','',
 'S0/S1/S2逐字段直接复制Stage5.2缓存，不重算不覆盖；S1与S1-R并列，S2-R只继承S1-R。共同总体仍由原E自适应网格生成，受既有几何引导/距离先验/有限预算影响，不能解释为独立纯语义搜索。','',
 '## 全部新增样本汇总','', '| 阶段 | 总数 | 有网格 | 含参考 | 非空样本面积中位km² |','|---|---:|---:|---:|---:|']
 for r in summary:lines.append(f"| {r['stage']} | {r['total']} | {r['nonempty']} | {r['covered']}/{r['nonempty']} | {num(r['median_area_m2']/1e6 if r['median_area_m2'] is not None else None)} |")
 lines+=['','## 全部逐照片结果','',
 'H/S/U为去重后的点×关系记录数（跨身份重复观测分别计算），不是独立照片数；一条边可能在不同点属于不同等级。原S1/S2未分级，记—而不是0。区域数为最终并集连通面数；完整几何另在JSON保存有界排名区域数。通过数为点×身份记录，S2为最终优选成员数。时间是已有几何缓存后的层构造耗时，不是端到端视觉/完整求解时间。','',
 '| 照片 | 阶段 | 面积km² | 相对S0缩小 | 含参考 | 最近区域m | 通过/总点 | H/S/U | 连通区域 | 层秒 | 状态 |',
 '|---|---|---:|---:|---|---:|---|---|---:|---:|---|']
 for r in rows:
  counts=r.get('relation_point_counts');h='—' if counts is None else '/'.join(str(counts.get(k,0)) for k in ('HARD','SOFT','UNKNOWN'))
  reduction=r.get('reduction_from_s0');contains=r.get('reference_contains')
  lines.append(f"| {r['case']} | {r['stage']} | {num(r['area_m2']/1e6 if r['area_m2'] is not None else None)} | {'—' if reduction is None else format(reduction,'.2%')} | {'—' if contains is None else ('是' if contains else '否')} | {num(r.get('nearest_region_distance_m'),2)} | {r.get('passed_points','—')}/{r.get('actual_points','—')} | {h} | {r.get('region_count','—')} | {num(r.get('phase_seconds'))} | {r['status']} |")
 lines+=['','## 重点案例：关系筛选与几何优选分别归因','']
 for key in ('photo_04','photo_05','photo_08','legacy_beijing_cbd','legacy_north_bund'):
  rs={r['stage']:r for r in rows if r['case']==key}
  lines.append(f"- {key}：S1→S1-R面积 {rs['S1']['area_m2']/1e6:.3f}→{rs['S1-R']['area_m2']/1e6:.3f}km²，覆盖 {rs['S1']['reference_contains']}→{rs['S1-R']['reference_contains']}；S2→S2-R面积 {rs['S2']['area_m2']/1e6:.3f}→{rs['S2-R']['area_m2']/1e6:.3f}km²，覆盖 {rs['S2']['reference_contains']}→{rs['S2-R']['reference_contains']}。")
  p=next(r for r in diagnostics if r['case']==key)['nearest_existing_points'][0]
  lines.append(f"  最近已有样点（跨身份取最近）：距参考{p['distance_m']:.2f}m，{p['hypothesis_id']}，原可行性={p['feasible']}，原分数={p['score']:.8f}，硬拒绝原因={p['reasons']}，新HARD冲突={p['hard_conflicts']}，SOFT诊断均值={p['soft_score']}。仅描述该已有点，不断言连续参考位置的建筑内部/身份真值。")
 lines+=['',
 'photo_04：旧S1用明确名称/轮廓直接硬筛，存在自报位置被排除的反例。新策略缺独立身份/完整可见证据，降为SOFT，恢复范围不等于证明原身份或参考准确。若S2-R仍不含参考，应归于原物理约束/投影评分/分数窗口及有界优选链，而非新关系硬排除。',
 'photo_05：旧S1含参考但S2不含。新路径关系层保留后仍应独立检查S2-R；不能把完整几何/模式选择丢失归为左右关系问题。',
 'photo_04与photo_08的最近已有点原已因known_standing_surface_conflict拒绝；S1-R不会解除原物理限制。photo_05和北京、北外滩的最近点物理可行且新HARD冲突为0；输出缺失或低排名仍需归到原评分/窗口/区域保留链，不是新SOFT惩罚。这里未单凭一个样点确认整条链的唯一根因。',
 'photo_08、北京旧例：关系证据不足，零硬收缩是预期保守结果，无法消除机位歧义。北外滩：保留参考区域也不能解决同分模式排序不稳定，原E评分/预算没有调整。',
 '每身份最近的已有采样点、完整原评分分项、可行性原因和新关系分级见evaluation/point_diagnostics.json；只诊断已搜索点，没有在真值新采样或重新打分。因采样面近似、参考误差及2D假设，单一最近样点不等价连续位置证明。','',
 '## 已确认、未确认与后续最小项','',
 '已确认：冻结输入未提供独立身份或完整可见轮廓证明，因此本轮真实数据没有HARD关系；S1-R保持S0，不取得真实空间缩减。这是保守安全性对照，不是“改进定位精度”。合成场景能在证据齐全且角度充分分离时产生HARD并缩小范围。',
 '尚未确认：每张真实图的具体身份/遮挡真值、相机自报误差和完整可见性。地图identity_certain及名称精确命中不是独立正确性证明。后续优先建立不含机位坐标的身份/可见轮廓证据标注，再验证HARD的真实效用；先诊断S2缓存评分与选择丢弃原因，不按这批参考反复调权重。',
 'SOFT对每候选点取1/0.5/0均值，无SOFT则null，UNKNOWN完全中立。没有把均值当作概率，也没有据此改变覆盖或原几何排序。分布、null数量、HARD满足/冲突/静态合格但几何不可定点计数均在metrics.json，逐点代码在压缩完整输出。','',
 'photo_01/03保持历史视觉请求失败，未运行；photo_09/11无足够独立锚点、空区域距离为null；photo_12距离先验外，S0即不含参考。所有失败列出，未隐藏或补0米。','',
 '## 运行与Demo验收','',
 '详见[实际命令与失败记录](evaluation/stage5_3/VALIDATION.md)。Demo在“空间精化离线”选择“Stage 5.3 可靠性分级”，保留Stage5.2选择、在线定位及E物理/优选层。参考仅主动勾选独立评估显示。浏览器截图和验收JSON在demo/。',
 '[关系规则](STAGE5_3_SPATIAL_RELATIONS.md) · [完整指标](evaluation/stage5_3/evaluation/metrics.json) · [汇总](evaluation/stage5_3/evaluation/summary.json)',
 '', '照片及OSM署名许可沿用[原清单](evaluation/real_camera_diagnostics/ATTRIBUTION.md)。']
 (ROOT/'docs/STAGE5_3_EVALUATION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

if __name__=='__main__':main()
