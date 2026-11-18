"""Render transparent benchmark tables from finalized measurements, not predictions."""
import json
from collections import Counter
from pathlib import Path
from run_camera_benchmark import ROOT,OUT,save

LABEL={'baseline':'A 搜索基线','robust_only':'B 鲁棒几何','identity_only':'C 联合身份','joint_full':'D 完整'}

def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def num(x,digits=2):return '—' if x is None else f'{x:.{digits}f}'

def main():
 refs=read('dataset_references.json')['samples'];rows=read('post_evaluation/metrics.json');summaries=read('post_evaluation/summary.json')
 ledger=read('api_requests.json');audits=read('post_evaluation/point_diagnostics.json')
 attr=['# 真实照片来源与署名','', '照片均为合法公开许可的 Commons 派生副本。<=1600 px，重新 JPEG 编码，移除所有 EXIF/GPS/IPTC，未裁切。许可证沿用各原作；作者未为本项目背书。下载地址、原始/处理后 SHA-256、页面 revision ID、元数据快照、参考坐标完整保存在 dataset_references.json 与 sources/。','']
 for r in refs:
  if r['split']=='legacy_diagnostic':continue
  attr+= [f"- **{r['id']}** [{r['title']}]({r['source_url']}) — {r['author'].strip()}；[{r['license']}]({r['license_url']})；分组 {r['split']}。"]
 attr += ['', '## 旧例派生副本', '', '- legacy_beijing_cbd：N509FZ，[Parkview Green and CBD skyline (20210927131419).jpg](https://commons.wikimedia.org/wiki/File:Parkview_Green_and_CBD_skyline_(20210927131419).jpg)，[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。', '- legacy_north_bund：Bechology，[Oriental Pearl Tower view from the North Bund, Oct. 21st, 2026.jpg](https://commons.wikimedia.org/wiki/File:Oriental_Pearl_Tower_view_from_the_North_Bund,_Oct._21st,_2026.jpg)，[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。', '', '两旧例 JPEG 去元数据并重新编码；annotations/ 额外叠加预测框、中心和标签，沿用各自许可。OSM © OpenStreetMap contributors / ODbL，见 ../stage3/ATTRIBUTION.md。']
 (OUT/'ATTRIBUTION.md').write_text('\n'.join(attr)+'\n',encoding='utf-8')
 text=['# 真实机位测试集扩充与粗定位误差诊断','',f"请求批次 UTC 范围：{ledger[0]['started_at_utc']} — {ledger[-1]['started_at_utc']}。",'',
 '本阶段不调权重、容差、搜索预算或区域保留参数，不增加根据机位的特殊规则；没有连续优化。新增可选诊断记录不参与评分与筛选，旧算法及历史结果保持原样。','',
 '## 数据集与隔离','',
 '筛选 14 个 Commons 文件，排除 1 张明确拼接全景和 1 张尚未核实当前地图覆盖内目标身份的旧照片（不据此断言坐标错误）；新增12张。初筛10张多地标与2张压力样本；独立复核发现 photo_12 的远景塔楼身份尚不能逐栋确认，最终按9张明确多地标与3张压力样本报告。原冻结标签保留，修正见 post_review.json；所有12张仍保留在机位指标中，没有按成绩剔除。7 张上海、2 张北京、3 张广州；未扩展 OSM 覆盖，没有新地图请求。不同距离、昼夜、施工期、遮挡及远距离公路视角均保留，不按模型成绩筛除。公共元数据服务曾间歇 HTTP 失败，有限重试后取得全部所需来源快照；非视觉调用。','',
 '所有参考点均来自明确的 Commons `Location`/`Location dec` 相机模板，排除 Object location、EXIF GPS 与地标坐标。Q1=独立测量；Q2=摄影者自报且空间语义明确、未经独立测量；Q3=含义/位置存疑、排除。此次全部 Q2，accuracy_m=null；数字精度不代表测量精度，以下是对自报位置的样本偏差。没有声称普遍准确率。','',
 '预先按摄影者/拍摄批次分组，6 development、6 holdout；同摄影者 Shinrya 两张、同次 2019-11-12 两张均留在 holdout，避免相似图跨组泄露。保留集只给整体指标和阶段失败分类，不做逐点参考位置诊断；两张旧例单列 legacy_diagnostic，不混入新增样本。没有使用任何一组调参，本次已经查看保留集评估结果，未来调参若使用它则必须另建新保留集。','',
 '采集/人工审核后先冻结 dataset_freeze.json、inference_inputs.json。后者只包含中性 ID、去元数据 JPEG 路径及哈希。模型只收到重新编码图片，MapMatcher 不接收城市限制，PoseSolver 不接收来源、作者、文件名语义、GPS 或参考坐标。所有 solve 结束、结果和输入哈希写入 inference_manifest.json 后才进行独立后评估，评估前后检查推理文件未变。','',
 '## 新增照片','', '| ID | 来源/作者 | 集合 | 人工可辨地标 | Camera location | 质量 |','|---|---|---|---|---|---|']
 for r in refs:
  if r['split']=='legacy_diagnostic':continue
  loc=r['reference'];text.append(f"| {r['id']} | [{r['title']}]({r['source_url']}) / {r['author'].strip()} | {r['split']} | {('远景身份未确认；初筛IFC/CTF标签不作真值' if r['id']=='photo_12' else ', '.join(r['human_reference_landmarks']) or '仅通用 CBD 建筑，具体身份不确定')} | {loc['latitude']}, {loc['longitude']} | Q2，误差界未知 |")
 text+=['','照片/原下载地址/许可/完整哈希：[数据与署名](evaluation/real_camera_diagnostics/ATTRIBUTION.md)、`dataset_references.json`。地标清单不是完整实例分割答案，photo_12 的初筛身份已明确降级；不据未经确认的标签统计身份准确率。未使用模型预测填充标准答案。','',
 '## 实际调用与缓存','', '首轮使用现有 60s 超时；仅对超时失败图按冻结顺序做一次显式恢复（120s），模型、提示词和几何参数不变，未改 .env；成功图从不重调。总预算20次仍在每次发送时强制检查。账本 finished_at_utc 为该次 Pipeline 尝试完成时间（可能包含 D 几何），不能直接当 API 服务时延；恢复轮另记 api_response_at_utc。','',f"新增实际视觉 HTTP 请求 {len(ledger)} 次（预算上限 20，SDK retries=0）。账本状态：{dict(Counter(r['status'] for r in ledger))}。模型固定 qwen3.8-flash，端点沿用本地配置；未切换模型。成功识别只保存一份，几何组复用相同 vision/matches。失败未被写成空成功。原始成功响应与 token usage 在 raw_responses/、api_requests.json；实际账单不可获取，不估计确定费用，超时也不能认定免费。","", '| 图片 | 请求次数 | 结果 | token usage |','|---|---:|---|---|']
 for r in refs:
  if r['split']=='legacy_diagnostic':continue
  calls=[c for c in ledger if c['sample_id']==r['id']]
  text.append(f"| {r['id']} | {len(calls)} | {'; '.join(c['status']+':'+c.get('code','') for c in calls) or '未请求'} | {json.dumps([c.get('usage') for c in calls],ensure_ascii=False)} |")
 text+=['','## 固定 A/B/C/D 对照','',
 'A=Stage5.1A-Fix 搜索增强（5.1B 控制组）；B=只启用 robust_geometry；C=只启用 joint_identity；D=robust+joint+dual_regions+后置 visibility。四组均 24000 总点、4500 单身份、最多 12 个身份；R=5000 m、粗间距180–600 m/细60 m、分片750 m、分数窗口0.08，权重0.40/0.20/0.25/0.15全部沿用。输入、OSM SQLite SHA、配置固定且无城市提示。','',
 '公平性边界：上限相同不等于实际点数/坐标相同；联合身份会分摊更多组合，鲁棒评分也会改变细化位置。D 首先通过实际 LocalizationPipeline 取得完整结果，A/B/C 随后从缓存跑；计时只取 solver.elapsed_seconds，不含视觉等待、匹配或文件写入，单次计时存在缓存/机器负载差异。新增诊断开销包含在此次计时中，不直接与历史耗时视为同环境基准。','',
 '| 集合 | 组 | 总数 | 可计算 Top-1 | 无距离结果 | 中位 m | P90 m | Top3/5/10 区域命中（分母含流程失败） |','|---|---|---:|---:|---:|---:|---:|---|']
 for s in summaries:
  text.append(f"| {s['split']} | {LABEL[s['group']]} | {s['total_samples']} | {s['valid_distance_samples']} | {s['no_distance_samples']} | {num(s['error_distribution']['median_m'])} | {num(s['error_distribution']['p90_m'])} | "+' / '.join(f"{s['preferred_topk'][str(k)]['hits']}/{s['total_samples']}" for k in (3,5,10))+' |')
 text+=['','无距离结果不填0米。Top-K 的端到端分母包含 API/匹配失败，不能把缺少推理输出的行解读成几何错位；完整误差分布 n/p25/p75/p90/min/max 与失败阶段计数在 post_evaluation/summary.json。','',
 '| 图片 | 组 | Top1 m | Top3/5/10 | 最近Preferred m | Preferred km² | Feasible km²/含参考点 | 点数/可靠地标/搜索身份 | 秒 | 阶段 |','|---|---|---:|---|---:|---:|---|---|---:|---|']
 for r in rows:
  text.append(f"| {r['case']} | {LABEL[r['group']]} | {num(r['top1_point_distance_m'])} | "+('/'.join('是' if r['preferred_topk_hits'][str(k)] else '否' for k in (3,5,10)) if 'searched_points' in r else '未运行')+f" | {num(r['nearest_region_distance_m'])} | {num(r.get('preferred_area_m2',0)/1e6) if 'preferred_area_m2' in r else '—'} | {num(r.get('feasible_area_m2',0)/1e6) if 'feasible_area_m2' in r else '—'}/{('是' if r.get('feasible_contains_reference') else '否') if 'searched_points' in r else '未运行'} | {r.get('searched_points','—')}/{r.get('reliable_landmarks','—')}/{r.get('searched_hypotheses','—')} | {num(r.get('seconds'))} | {r['stage']} |")
 text+=['','## 已有样点的阶段归因','',
 'record_diagnostic_trace 默认 False。启用时仅记录已有点：hard_feasible、phase、score/components、UNKNOWN/OUTLIER、FOV、同身份分数排名、窗口阈值和 selection_stage；不改变选择。观察器一致性测试要求同一输入诊断前后几何/分数/面积/样点数逐项相等。','',
 '阶段标签：hard_rejected（已搜索但物理拒绝）、visual_rejected（通过硬约束但旧视觉模型拒绝）、below_score_window（已评分但低于所在分片/分量阈值）、cell_clipping_or_no_component_membership（达到窗口但裁剪/成员归属未进入输出模式）、region_cap（形成区域后因输出上限丢失）、preferred（保留）。200m 内没样点只表示该半径未采样，不推断绝对不可能；搜索域是否包含参考点另看几何，有限网格不是连续覆盖证明。','',
 '逐点诊断只针对 development 与两张旧例；post_evaluation/point_diagnostics.json 保存每身份的全域/附近阶段计数、最近已有样点、附近最高分样点、排名、分项、阈值、丢弃原因与最终区域排名。没有在真实坐标处补点或重跑求解。','', '| 样本/组 | 最近实际样点 m | 200m 内阶段计数 |','|---|---:|---|']
 for a in audits:
  text.append(f"| {a['case']} / {LABEL[a['group']]} | {num(a['nearest_sample_m'])} | {json.dumps(a['nearby_stage_counts'],ensure_ascii=False)} |")
 text+=['','## 根因证据、假设与下一步','',
 '每例视觉/地图身份审查、北京/北外滩评分差异与区域截断证据见 [根因分析](REAL_CAMERA_ROOT_CAUSES.md)。数据支持的问题与尚未验证的解释必须分开；本阶段未据此调整权重或参数。','',
 '## 自动化测试与开发失败','', '最终 uv run pytest -q：391 passed in 29.91s，0 failed，0 skipped，包含原有378项。定向13项全部通过。真实超时、开发中测试守卫误报、Windows路径兼容与零采样null修复均如实记录在 [VALIDATION.md](evaluation/real_camera_diagnostics/VALIDATION.md)，没有跳过失败测试。','', '## 复现命令与边界','', '```powershell','uv run python scripts/collect_camera_dataset.py','uv run python scripts/freeze_camera_dataset.py','uv run python scripts/run_camera_benchmark.py --live','uv run python scripts/retry_camera_failures.py','uv run python scripts/run_camera_benchmark.py','uv run python scripts/diagnose_camera_benchmark.py','uv run python scripts/audit_camera_assumptions.py','uv run python scripts/render_camera_annotations.py','uv run python scripts/report_camera_root_causes.py','uv run python scripts/report_camera_benchmark.py','uv run pytest -q','```','',
 '采集在冻结后只验哈希、不再下载；冻结脚本拒绝覆盖。核心指标离线复核从 diagnose 开始，不需要 Key/模型；若本地不存在SQLite则跳过详细评分重审，已有审计文件仍可阅读。详细重审有数据库时强制核对原SHA，不接受不同快照。run 不加 --live 只复用成功视觉缓存，失败不会自动再次付费；缺少原 SHA 地图时拒绝悄悄换数据。完整几何 JSON 以 gzip 保存，未删失败输出。OSM 继续 © OpenStreetMap contributors / ODbL；不提交数据库和原始 Overpass 大缓存。']
 (ROOT/'docs/REAL_CAMERA_DIAGNOSTICS.md').write_text('\n'.join(text)+'\n',encoding='utf-8')

if __name__=='__main__':main()
