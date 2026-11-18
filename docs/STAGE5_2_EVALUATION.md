# Stage 5.2：区域筛选修复与空间精化验收

本阶段使用上一阶段冻结的12张新增照片（9张明确多地标、3张压力样本）及2张旧例。保持development/holdout原划分；这些holdout已被查看，只用于回归/诊断，不作独立泛化证明。所有Camera location均为Q2自报，测量误差界未知。没有新增视觉/API请求或地图下载，也没有三维/连续优化。

## 对导师三个问题的回答

1. **语义检索能建立有限初始范围，但不是机位答案。** S0使用地图实体身份组合、固定5km观察距离和有限共同采样覆盖；多身份、普通楼和超距照片仍失败。建筑中心从不当摄影者位置。

2. **相对关系可以缩小条件候选域，但真实收益受身份和关系可靠性限制。** 逐身份收缩与多身份并集均报告；并集中的弱约束假设可能抵消强约束假设收益。确有缩小后排除参考点的失败，不把面积变小当作成功。

3. **完整精化更集中，但不能保证保留正确位置或改善Top-1。** E修复质量优先机制，仍有不可区分的同分模式超过预算；S2的缩小混合了物理约束、视场/投影评分和有限优选，不全归功左右关系。实际数据如下，未反复调参追成绩。

## 根因、策略与有界取舍

旧diversified_regions选第一个高分模式后主要按空间最远距离，允许低分远处模式挤掉其他高分模式。新E保持D采样/评分/身份组合不变，只替换最终保留与排序：分数保留六位小数形成数值近似并列档→轮廓几何质量→独立坐标可靠地标数量；同质量档内部才使用空间分散。它不是校准概率，也没有把0.005任意当作同分。

同档相交/相接模式可作精确并集，仅在单Polygon且合并面积不超过原750m分片面积时合并；不做凸包、不加buffer、不跨不相接位置合并。每身份最多8区域、最多12身份；每区最大0.5625km²，全局上限96区域，仍可能遗漏高分模式。对被保留面覆盖的重复模式不再占额度。

平局顺序以高分已有样点的毫米级坐标键为准，哈希仅为审计标识；多样性距离同样按毫米稳定化。初版用几何哈希排序，新增测试证明1e-8m扰动会改变模式，因此修复此数值稳定性Bug后重跑一次最终E，未改权重/距离/FOV/数量预算。初版源与完整指标保存在development_initial/，原始临时压缩输出保留在本机.cache/stage52_initial/。此规则不保证任意量化边界扰动下绝对不变。

完整selection_audit记录所有原模式合并来源、区域界、最佳已有点、几何SHA、质量、面积、保留/丢弃原因、同分超额证据。无法同时保证面积紧凑、包含所有高分模式和数量有界：本实现守面积/数量预算，明确报告未保留模式，不宣称全保留。

## 实验公平性与兼容

A/B/C/D直接引用冻结旧结果，文件未改。E使用同一OSM SQLite SHA、原始vision/matches及D配置，仅selection_strategy不同。逐例严格比较全体采样坐标/phase/分数/分项和Feasible：均相同。旧默认strategy=legacy；Stage52PoseSolver明确启用E，旧Solver仍可复现旧结果。新增字段兼容旧JSON，历史原始文件字节保持。

E耗时为本次完整solve（含搜索、区域、后置可见性），旧A/B/C/D耗时是历史测量，不能作同环境加速结论。S0/S1/S2复用E分数，其附加时间另列，不能当完整在线延迟。

| 集合 | 组 | 有效Top-1/总数 | 中位m | P90m | Top3/5/10区域命中 |
|---|---|---|---:|---:|---|
| all_new | A | 8/12 | 1468.99 | 4233.76 | 1/12/1/12/1/12 |
| all_new | B | 8/12 | 1220.79 | 4578.55 | 2/12/2/12/2/12 |
| all_new | C | 8/12 | 1304.94 | 3795.24 | 2/12/2/12/2/12 |
| all_new | D | 8/12 | 1247.61 | 4818.36 | 1/12/1/12/1/12 |
| all_new | E | 8/12 | 1247.61 | 3993.23 | 0/12/0/12/2/12 |
| development | A | 3/6 | 601.68 | 2663.20 | 1/6/1/6/1/6 |
| development | B | 3/6 | 576.28 | 2349.17 | 1/6/1/6/1/6 |
| development | C | 3/6 | 451.06 | 2131.92 | 1/6/1/6/1/6 |
| development | D | 3/6 | 571.36 | 2332.06 | 0/6/0/6/0/6 |
| development | E | 3/6 | 571.36 | 2223.86 | 0/6/0/6/1/6 |
| holdout | A | 5/6 | 1544.53 | 4681.83 | 0/6/0/6/0/6 |
| holdout | B | 5/6 | 1299.81 | 5867.49 | 1/6/1/6/1/6 |
| holdout | C | 5/6 | 1332.06 | 4672.58 | 1/6/1/6/1/6 |
| holdout | D | 5/6 | 1397.40 | 6421.26 | 1/6/1/6/1/6 |
| holdout | E | 5/6 | 1397.40 | 4960.37 | 0/6/0/6/1/6 |
| legacy_diagnostic | A | 2/2 | 979.11 | 1711.40 | 1/2/1/2/1/2 |
| legacy_diagnostic | B | 2/2 | 2656.54 | 3221.23 | 1/2/1/2/2/2 |
| legacy_diagnostic | C | 2/2 | 1999.29 | 2083.14 | 1/2/1/2/1/2 |
| legacy_diagnostic | D | 2/2 | 2616.58 | 3213.24 | 0/2/0/2/0/2 |
| legacy_diagnostic | E | 2/2 | 3130.00 | 4137.40 | 0/2/0/2/0/2 |

## 北京、北外滩与photo_02重点结果

| 样本 | 组 | Top1m | 最近Preferredm | Preferred km² | 包含排名 | 全局最高质量仍遗漏模式数 |
|---|---|---:|---:|---:|---|---:|
| photo_02 | D | 571.36 | 30.60 | 8.162 | [] | 旧版本未记录 |
| legacy_beijing_cbd | D | 3362.40 | 1855.56 | 1.969 | [] | 旧版本未记录 |
| legacy_north_bund | D | 1870.76 | 151.27 | 6.646 | [] | 旧版本未记录 |
| photo_02 | E | 571.36 | 0.00 | 8.735 | [6, 16, 23, 46, 85] | 0 |
| legacy_beijing_cbd | E | 4389.25 | 237.86 | 3.236 | [] | 38 |
| legacy_north_bund | E | 1870.76 | 0.00 | 5.906 | [13, 51, 68, 79, 86] | 0 |

包含参考点但排名较后/面积较大，不构成精确定位成功。E若Top-1未改善或更差，保留该失败；不会据此再调策略。局部最高质量遗漏总数与全局最高质量遗漏分开统计，不能把各身份弱假设的局部最高分说成整张图最高分。

## 所有样本A/B/C/D/E与失败

| 样本 | 组 | 状态 | Top1m | 最近Preferredm | Preferred km² | Top3/5/10 | 区域数 | 秒 |
|---|---|---|---:|---:|---:|---|---:|---:|
| legacy_beijing_cbd | A | SEARCH_LIMITED | 1894.47 | 320.48 | 23.507 | 否/否/否 | 8 | 12.731 |
| legacy_beijing_cbd | B | SEARCH_LIMITED | 3362.40 | 0.00 | 74.151 | 是/是/是 | 8 | 16.314 |
| legacy_beijing_cbd | C | SEARCH_LIMITED | 1894.47 | 320.48 | 23.507 | 否/否/否 | 8 | 12.196 |
| legacy_beijing_cbd | D | SEARCH_LIMITED | 3362.40 | 1855.56 | 1.969 | 否/否/否 | 8 | 16.064 |
| legacy_beijing_cbd | E | SEARCH_LIMITED | 4389.25 | 237.86 | 3.236 | 否/否/否 | 8 | 3.475 |
| legacy_north_bund | A | SEARCH_LIMITED | 63.75 | 0.00 | 6.658 | 是/是/是 | 16 | 83.082 |
| legacy_north_bund | B | SEARCH_LIMITED | 1950.68 | 0.00 | 3.857 | 否/否/是 | 48 | 144.586 |
| legacy_north_bund | C | SEARCH_LIMITED | 2104.10 | 0.00 | 17.206 | 是/是/是 | 56 | 96.125 |
| legacy_north_bund | D | SEARCH_LIMITED | 1870.76 | 151.27 | 6.646 | 否/否/否 | 96 | 193.467 |
| legacy_north_bund | E | SEARCH_LIMITED | 1870.76 | 0.00 | 5.906 | 否/否/否 | 96 | 41.890 |
| photo_01 | A | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_01 | B | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_01 | C | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_01 | D | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_01 | E | VISION_UNAVAILABLE | — | — | — | 否/否/否 | — | — |
| photo_02 | A | SEARCH_LIMITED | 601.68 | 0.00 | 2.062 | 是/是/是 | 10 | 10.691 |
| photo_02 | B | SEARCH_LIMITED | 171.10 | 0.00 | 2.197 | 是/是/是 | 16 | 11.644 |
| photo_02 | C | SEARCH_LIMITED | 371.52 | 0.00 | 44.802 | 是/是/是 | 89 | 23.980 |
| photo_02 | D | SEARCH_LIMITED | 571.36 | 30.60 | 8.162 | 否/否/否 | 96 | 34.710 |
| photo_02 | E | SEARCH_LIMITED | 571.36 | 0.00 | 8.735 | 否/否/是 | 96 | 32.051 |
| photo_03 | A | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_03 | B | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_03 | C | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_03 | D | vision_api_or_schema_failure | — | — | — | 否/否/否 | 0 | — |
| photo_03 | E | VISION_UNAVAILABLE | — | — | — | 否/否/否 | — | — |
| photo_04 | A | SEARCH_LIMITED | 1544.53 | 483.87 | 4.826 | 否/否/否 | 25 | 134.180 |
| photo_04 | B | SEARCH_LIMITED | 1549.36 | 1.02 | 53.531 | 否/否/否 | 72 | 205.790 |
| photo_04 | C | SEARCH_LIMITED | 1637.69 | 372.03 | 4.956 | 否/否/否 | 71 | 65.816 |
| photo_04 | D | SEARCH_LIMITED | 1664.20 | 1172.25 | 6.840 | 否/否/否 | 96 | 240.805 |
| photo_04 | E | SEARCH_LIMITED | 1664.20 | 79.28 | 8.729 | 否/否/否 | 96 | 55.177 |
| photo_05 | A | SEARCH_LIMITED | 1133.00 | 605.41 | 3.273 | 否/否/否 | 35 | 23.360 |
| photo_05 | B | SEARCH_LIMITED | 1141.77 | 0.00 | 36.322 | 否/否/否 | 72 | 41.237 |
| photo_05 | C | SEARCH_LIMITED | 1277.82 | 488.97 | 15.627 | 否/否/否 | 80 | 24.114 |
| photo_05 | D | SEARCH_LIMITED | 1097.82 | 865.63 | 5.035 | 否/否/否 | 96 | 47.414 |
| photo_05 | E | SEARCH_LIMITED | 1097.82 | 440.82 | 7.312 | 否/否/否 | 96 | 46.519 |
| photo_06 | A | SEARCH_LIMITED | 1660.83 | 638.10 | 5.287 | 否/否/否 | 14 | 29.995 |
| photo_06 | B | SEARCH_LIMITED | 1299.81 | 0.00 | 23.846 | 是/是/是 | 32 | 49.975 |
| photo_06 | C | SEARCH_LIMITED | 1332.06 | 0.00 | 54.558 | 是/是/是 | 86 | 51.966 |
| photo_06 | D | SEARCH_LIMITED | 1397.40 | 0.00 | 10.338 | 是/是/是 | 96 | 90.015 |
| photo_06 | E | SEARCH_LIMITED | 1397.40 | 0.00 | 15.313 | 否/否/是 | 96 | 37.192 |
| photo_07 | A | SEARCH_LIMITED | 1393.46 | 578.27 | 1.377 | 否/否/否 | 6 | 8.844 |
| photo_07 | B | SEARCH_LIMITED | 733.31 | 316.05 | 3.014 | 否/否/否 | 32 | 15.476 |
| photo_07 | C | SEARCH_LIMITED | 441.36 | 67.44 | 2.195 | 否/否/否 | 12 | 7.465 |
| photo_07 | D | SEARCH_LIMITED | 848.31 | 67.44 | 2.793 | 否/否/否 | 24 | 12.784 |
| photo_07 | E | SEARCH_LIMITED | 848.31 | 67.44 | 2.636 | 否/否/否 | 24 | 12.266 |
| photo_08 | A | SEARCH_LIMITED | 498.17 | 263.07 | 0.112 | 否/否/否 | 16 | 25.599 |
| photo_08 | B | SEARCH_LIMITED | 576.28 | 384.46 | 0.688 | 否/否/否 | 16 | 42.355 |
| photo_08 | C | SEARCH_LIMITED | 451.06 | 146.03 | 49.730 | 否/否/否 | 96 | 62.599 |
| photo_08 | D | SEARCH_LIMITED | 514.56 | 382.67 | 6.837 | 否/否/否 | 96 | 105.135 |
| photo_08 | E | SEARCH_LIMITED | 514.56 | 15.32 | 7.890 | 否/否/否 | 96 | 22.232 |
| photo_09 | A | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.000 |
| photo_09 | B | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.000 |
| photo_09 | C | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.001 |
| photo_09 | D | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.001 |
| photo_09 | E | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.000 |
| photo_10 | A | SEARCH_LIMITED | 3178.58 | 405.32 | 45.969 | 否/否/否 | 56 | 74.216 |
| photo_10 | B | SEARCH_LIMITED | 2792.40 | 981.75 | 57.132 | 否/否/否 | 56 | 92.616 |
| photo_10 | C | SEARCH_LIMITED | 2552.13 | 755.12 | 16.565 | 否/否/否 | 48 | 72.205 |
| photo_10 | D | SEARCH_LIMITED | 2772.24 | 2049.77 | 3.524 | 否/否/否 | 48 | 93.577 |
| photo_10 | E | SEARCH_LIMITED | 2636.98 | 1762.51 | 9.013 | 否/否/否 | 48 | 20.788 |
| photo_11 | A | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.001 |
| photo_11 | B | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.001 |
| photo_11 | C | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.003 |
| photo_11 | D | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.003 |
| photo_11 | E | INSUFFICIENT_EVIDENCE | — | — | 0.000 | 否/否/否 | 0 | 0.001 |
| photo_12 | A | SEARCH_LIMITED | 6695.83 | 3659.26 | 25.762 | 否/否/否 | 8 | 14.670 |
| photo_12 | B | SEARCH_LIMITED | 8746.24 | 3659.26 | 70.029 | 否/否/否 | 8 | 16.463 |
| photo_12 | C | SEARCH_LIMITED | 6695.83 | 3659.26 | 25.762 | 否/否/否 | 8 | 14.075 |
| photo_12 | D | SEARCH_LIMITED | 9592.64 | 3661.49 | 1.501 | 否/否/否 | 8 | 16.609 |
| photo_12 | E | SEARCH_LIMITED | 7157.82 | 4997.46 | 3.249 | 否/否/否 | 8 | 3.605 |

photo_01/03仍为原视觉超时，无几何结果；photo_09普通场景无身份、photo_11单可靠锚点，保持证据不足；不填0米。远景photo_12与5km距离先验不适配，不能改参考点掩盖。身份混淆、错误地图候选与旧失败沿用上一阶段逐例记录，未改原视觉JSON。

所有单区域面积、Feasible覆盖与面积、区域数、截断原因/最高质量遗漏及点证据在evaluation/comparison.json、E_point_diagnostics.json和完整E输出；源输入与配置/网格SHA在inference_checks.json和inference_manifest.json。

## Demo与API

新增“空间精化离线”模式：照片/识别→地图实体→S0/S1/S2图层与面积/缩减率，另列E物理可行与软关系优选层。参考点只在明确勾选独立评估时加载并叠加，在线推理不接收。在线原功能保留，可选启用Stage5.2并复用已有视觉缓存。

浏览器验收修复了实际阻断Bug：streamlit-folium通过dependency URL执行脚本，不执行旧内联header脚本，曾出现L未定义空白地图。改用已有本地Leaflet/jQuery/CSS的data URL依赖，静态导出和组件都不访问CDN。无新增项目运行依赖。

[实际浏览器验收](evaluation/stage5_2/demo/browser_acceptance.json)、[截图](evaluation/stage5_2/demo/offline_refinement_photo02.png)、[页面概览](evaluation/stage5_2/demo/offline_refinement_overview.png)、[自包含离线地图](evaluation/stage5_2/demo/refinement_photo_02.html)。

Python：Stage52PoseSolver(store, PoseSearchConfig(record_diagnostic_trace=True)).solve(vision,matching)；build_spatial_refinement(vision,matching,pose,bounds)给出经过Pydantic校验的同网格层。单个可靠地标不制造精确机位。

## 未解决与最小后续项

大量零残差同分解、身份/坐标可靠性区别、误匹配及2D/视场假设仍限制结果。仅精确名称和完整轮廓也不等于真实身份确认，S1存在收缩后丢参考的反例。先独立验证身份和相机参考质量，再评估同分模式的紧凑表示；不引入3D重建/连续优化，不按个别参考点调权重。数值稳定修复与机制修复不能当作泛化提升。

[完整空间消融](STAGE5_2_SPATIAL_ABLATION.md)；[实际命令、失败与测试](evaluation/stage5_2/VALIDATION.md)。照片署名沿用[来源](evaluation/real_camera_diagnostics/ATTRIBUTION.md)，OSM © OpenStreetMap contributors / ODbL。
