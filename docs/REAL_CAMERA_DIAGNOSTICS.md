# 真实机位测试集扩充与粗定位误差诊断

请求批次 UTC 范围：2026-11-17T12:53:44.898018+00:00 — 2026-11-18T09:42:25.030814+00:00。

本阶段不调权重、容差、搜索预算或区域保留参数，不增加根据机位的特殊规则；没有连续优化。新增可选诊断记录不参与评分与筛选，旧算法及历史结果保持原样。

## 数据集与隔离

筛选 14 个 Commons 文件，排除 1 张明确拼接全景和 1 张尚未核实当前地图覆盖内目标身份的旧照片（不据此断言坐标错误）；新增12张。初筛10张多地标与2张压力样本；独立复核发现 photo_12 的远景塔楼身份尚不能逐栋确认，最终按9张明确多地标与3张压力样本报告。原冻结标签保留，修正见 post_review.json；所有12张仍保留在机位指标中，没有按成绩剔除。7 张上海、2 张北京、3 张广州；未扩展 OSM 覆盖，没有新地图请求。不同距离、昼夜、施工期、遮挡及远距离公路视角均保留，不按模型成绩筛除。公共元数据服务曾间歇 HTTP 失败，有限重试后取得全部所需来源快照；非视觉调用。

所有参考点均来自明确的 Commons `Location`/`Location dec` 相机模板，排除 Object location、EXIF GPS 与地标坐标。Q1=独立测量；Q2=摄影者自报且空间语义明确、未经独立测量；Q3=含义/位置存疑、排除。此次全部 Q2，accuracy_m=null；数字精度不代表测量精度，以下是对自报位置的样本偏差。没有声称普遍准确率。

预先按摄影者/拍摄批次分组，6 development、6 holdout；同摄影者 Shinrya 两张、同次 2019-11-12 两张均留在 holdout，避免相似图跨组泄露。保留集只给整体指标和阶段失败分类，不做逐点参考位置诊断；两张旧例单列 legacy_diagnostic，不混入新增样本。没有使用任何一组调参，本次已经查看保留集评估结果，未来调参若使用它则必须另建新保留集。

采集/人工审核后先冻结 dataset_freeze.json、inference_inputs.json。后者只包含中性 ID、去元数据 JPEG 路径及哈希。模型只收到重新编码图片，MapMatcher 不接收城市限制，PoseSolver 不接收来源、作者、文件名语义、GPS 或参考坐标。所有 solve 结束、结果和输入哈希写入 inference_manifest.json 后才进行独立后评估，评估前后检查推理文件未变。

## 新增照片

| ID | 来源/作者 | 集合 | 人工可辨地标 | Camera location | 质量 |
|---|---|---|---|---|---|
| photo_01 | [Shanghai Skyline 2020.jpg](https://commons.wikimedia.org/wiki/File:Shanghai_Skyline_2020.jpg) / Shihu7 | development | 东方明珠, 上海环球金融中心, 金茂大厦, 上海中心大厦 | 31.234424590833335, 121.48834991444444 | Q2，误差界未知 |
| photo_02 | [Shanghai, China skyline.jpg](https://commons.wikimedia.org/wiki/File:Shanghai%2C_China_skyline.jpg) / Quintin Soloviev | development | 东方明珠, 上海环球金融中心, 金茂大厦, 上海中心大厦 | 31.236828, 121.487136 | Q2，误差界未知 |
| photo_03 | [Shanghai Skyline from the Bund.jpg](https://commons.wikimedia.org/wiki/File:Shanghai_Skyline_from_the_Bund.jpg) / Wilson Hui from Calgary, Canada | development | 东方明珠, 上海环球金融中心, 金茂大厦, 上海中心大厦 | 31.231894, 121.493725 | Q2，误差界未知 |
| photo_04 | [Flickr - Shinrya - Shanghai Skyline at Day.jpg](https://commons.wikimedia.org/wiki/File:Flickr_-_Shinrya_-_Shanghai_Skyline_at_Day.jpg) / Pete Stewart from Perth, Australia | holdout | 上海环球金融中心, 金茂大厦, 震旦国际大楼 | 31.229389, 121.478233 | Q2，误差界未知 |
| photo_05 | [Flickr - Shinrya - Shanghai Skyline HDR.jpg](https://commons.wikimedia.org/wiki/File:Flickr_-_Shinrya_-_Shanghai_Skyline_HDR.jpg) / Pete Stewart from Perth, Australia | holdout | 上海环球金融中心, 金茂大厦, 震旦国际大楼 | 31.247709, 121.472618 | Q2，误差界未知 |
| photo_06 | [20191112 Lujiazui skyline-2.jpg](https://commons.wikimedia.org/wiki/File:20191112_Lujiazui_skyline-2.jpg) / Balon Greyjoy | holdout | 东方明珠, 上海环球金融中心, 上海中心大厦 | 31.232172, 121.4910167 | Q2，误差界未知 |
| photo_07 | [20191112 Lujiazui skyline-13.jpg](https://commons.wikimedia.org/wiki/File:20191112_Lujiazui_skyline-13.jpg) / Balon Greyjoy | holdout | 东方明珠, 上海环球金融中心, 金茂大厦, 上海中心大厦 | 31.237353, 121.484918 | Q2，误差界未知 |
| photo_08 | [Beijing Central Business District (20240826163226).jpg](https://commons.wikimedia.org/wiki/File:Beijing_Central_Business_District_%2820240826163226%29.jpg) / HoweyYuan | development | 中央电视台总部大楼, 中国尊 | 39.911116, 116.454704 | Q2，误差界未知 |
| photo_09 | [Beijing CBD in 2026.jpg](https://commons.wikimedia.org/wiki/File:Beijing_CBD_in_2026.jpg) / Renek78 | holdout | 仅通用 CBD 建筑，具体身份不确定 | 39.907731, 116.463806 | Q2，误差界未知 |
| photo_10 | [Guangzhou skyline (6343573781).jpg](https://commons.wikimedia.org/wiki/File:Guangzhou_skyline_%286343573781%29.jpg) / kevinmcgill from Den Bosch, Netherlands | development | 广州国际金融中心, 星海音乐厅 | 23.10624, 113.298804 | Q2，误差界未知 |
| photo_11 | [广州塔晨曦Scenery in Guangzhou, China - panoramio (1).jpg](https://commons.wikimedia.org/wiki/File:%E5%B9%BF%E5%B7%9E%E5%A1%94%E6%99%A8%E6%9B%A6Scenery_in_Guangzhou%2C_China_-_panoramio_%281%29.jpg) / jiang-wen-jie | development | 广州塔 | 23.104338, 113.308858 | Q2，误差界未知 |
| photo_12 | [City Skyline, Shot on Xinhua Kuaisulu, Guangzhou.jpg](https://commons.wikimedia.org/wiki/File:City_Skyline%2C_Shot_on_Xinhua_Kuaisulu%2C_Guangzhou.jpg) / YikyuenG | holdout | 远景身份未确认；初筛IFC/CTF标签不作真值 | 23.083172, 113.392589 | Q2，误差界未知 |

照片/原下载地址/许可/完整哈希：[数据与署名](evaluation/real_camera_diagnostics/ATTRIBUTION.md)、`dataset_references.json`。地标清单不是完整实例分割答案，photo_12 的初筛身份已明确降级；不据未经确认的标签统计身份准确率。未使用模型预测填充标准答案。

## 实际调用与缓存

首轮使用现有 60s 超时；仅对超时失败图按冻结顺序做一次显式恢复（120s），模型、提示词和几何参数不变，未改 .env；成功图从不重调。总预算20次仍在每次发送时强制检查。账本 finished_at_utc 为该次 Pipeline 尝试完成时间（可能包含 D 几何），不能直接当 API 服务时延；恢复轮另记 api_response_at_utc。

新增实际视觉 HTTP 请求 17 次（预算上限 20，SDK retries=0）。账本状态：{'failed': 7, 'success': 10}。模型固定 qwen3.8-flash，端点沿用本地配置；未切换模型。成功识别只保存一份，几何组复用相同 vision/matches。失败未被写成空成功。原始成功响应与 token usage 在 raw_responses/、api_requests.json；实际账单不可获取，不估计确定费用，超时也不能认定免费。

| 图片 | 请求次数 | 结果 | token usage |
|---|---:|---|---|
| photo_01 | 2 | failed:API_TIMEOUT; failed:API_TIMEOUT | [null, null] |
| photo_02 | 2 | failed:API_TIMEOUT; success: | [null, {"completion_tokens": 1259, "prompt_tokens": 2772, "total_tokens": 4031, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 523, "rejected_prediction_tokens": null, "text_tokens": 735}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 1652, "text_tokens": 1120}}] |
| photo_03 | 2 | failed:API_TIMEOUT; failed:API_TIMEOUT | [null, null] |
| photo_04 | 1 | success: | [{"completion_tokens": 2647, "prompt_tokens": 1794, "total_tokens": 4441, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 1450, "rejected_prediction_tokens": null, "text_tokens": 1196}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 674, "text_tokens": 1120}}] |
| photo_05 | 2 | failed:API_TIMEOUT; success: | [null, {"completion_tokens": 2313, "prompt_tokens": 1794, "total_tokens": 4107, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 1097, "rejected_prediction_tokens": null, "text_tokens": 1215}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 674, "text_tokens": 1120}}] |
| photo_06 | 1 | success: | [{"completion_tokens": 3999, "prompt_tokens": 2772, "total_tokens": 6771, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 2993, "rejected_prediction_tokens": null, "text_tokens": 1005}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 1652, "text_tokens": 1120}}] |
| photo_07 | 2 | failed:API_TIMEOUT; success: | [null, {"completion_tokens": 1403, "prompt_tokens": 2772, "total_tokens": 4175, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 496, "rejected_prediction_tokens": null, "text_tokens": 906}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 1652, "text_tokens": 1120}}] |
| photo_08 | 1 | success: | [{"completion_tokens": 3530, "prompt_tokens": 2872, "total_tokens": 6402, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 2335, "rejected_prediction_tokens": null, "text_tokens": 1194}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 1752, "text_tokens": 1120}}] |
| photo_09 | 1 | success: | [{"completion_tokens": 1932, "prompt_tokens": 2522, "total_tokens": 4454, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 1374, "rejected_prediction_tokens": null, "text_tokens": 557}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 256, "image_tokens": 1402, "text_tokens": 1120}}] |
| photo_10 | 1 | success: | [{"completion_tokens": 2475, "prompt_tokens": 2522, "total_tokens": 4997, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 1285, "rejected_prediction_tokens": null, "text_tokens": 1189}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 1402, "text_tokens": 1120}}] |
| photo_11 | 1 | success: | [{"completion_tokens": 3453, "prompt_tokens": 1547, "total_tokens": 5000, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 2556, "rejected_prediction_tokens": null, "text_tokens": 896}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 0, "image_tokens": 427, "text_tokens": 1120}}] |
| photo_12 | 1 | success: | [{"completion_tokens": 3707, "prompt_tokens": 3022, "total_tokens": 6729, "completion_tokens_details": {"accepted_prediction_tokens": null, "audio_tokens": null, "reasoning_tokens": 2777, "rejected_prediction_tokens": null, "text_tokens": 929}, "prompt_tokens_details": {"audio_tokens": null, "cache_write_tokens": null, "cached_tokens": 1024, "image_tokens": 1902, "text_tokens": 1120}}] |

## 固定 A/B/C/D 对照

A=Stage5.1A-Fix 搜索增强（5.1B 控制组）；B=只启用 robust_geometry；C=只启用 joint_identity；D=robust+joint+dual_regions+后置 visibility。四组均 24000 总点、4500 单身份、最多 12 个身份；R=5000 m、粗间距180–600 m/细60 m、分片750 m、分数窗口0.08，权重0.40/0.20/0.25/0.15全部沿用。输入、OSM SQLite SHA、配置固定且无城市提示。

公平性边界：上限相同不等于实际点数/坐标相同；联合身份会分摊更多组合，鲁棒评分也会改变细化位置。D 首先通过实际 LocalizationPipeline 取得完整结果，A/B/C 随后从缓存跑；计时只取 solver.elapsed_seconds，不含视觉等待、匹配或文件写入，单次计时存在缓存/机器负载差异。新增诊断开销包含在此次计时中，不直接与历史耗时视为同环境基准。

| 集合 | 组 | 总数 | 可计算 Top-1 | 无距离结果 | 中位 m | P90 m | Top3/5/10 区域命中（分母含流程失败） |
|---|---|---:|---:|---:|---:|---:|---|
| all_new | A 搜索基线 | 12 | 8 | 4 | 1468.99 | 4233.76 | 1/12 / 1/12 / 1/12 |
| all_new | B 鲁棒几何 | 12 | 8 | 4 | 1220.79 | 4578.55 | 2/12 / 2/12 / 2/12 |
| all_new | C 联合身份 | 12 | 8 | 4 | 1304.94 | 3795.24 | 2/12 / 2/12 / 2/12 |
| all_new | D 完整 | 12 | 8 | 4 | 1247.61 | 4818.36 | 1/12 / 1/12 / 1/12 |
| development | A 搜索基线 | 6 | 3 | 3 | 601.68 | 2663.20 | 1/6 / 1/6 / 1/6 |
| development | B 鲁棒几何 | 6 | 3 | 3 | 576.28 | 2349.17 | 1/6 / 1/6 / 1/6 |
| development | C 联合身份 | 6 | 3 | 3 | 451.06 | 2131.92 | 1/6 / 1/6 / 1/6 |
| development | D 完整 | 6 | 3 | 3 | 571.36 | 2332.06 | 0/6 / 0/6 / 0/6 |
| holdout | A 搜索基线 | 6 | 5 | 1 | 1544.53 | 4681.83 | 0/6 / 0/6 / 0/6 |
| holdout | B 鲁棒几何 | 6 | 5 | 1 | 1299.81 | 5867.49 | 1/6 / 1/6 / 1/6 |
| holdout | C 联合身份 | 6 | 5 | 1 | 1332.06 | 4672.58 | 1/6 / 1/6 / 1/6 |
| holdout | D 完整 | 6 | 5 | 1 | 1397.40 | 6421.26 | 1/6 / 1/6 / 1/6 |
| legacy_diagnostic | A 搜索基线 | 2 | 2 | 0 | 979.11 | 1711.40 | 1/2 / 1/2 / 1/2 |
| legacy_diagnostic | B 鲁棒几何 | 2 | 2 | 0 | 2656.54 | 3221.23 | 1/2 / 1/2 / 2/2 |
| legacy_diagnostic | C 联合身份 | 2 | 2 | 0 | 1999.29 | 2083.14 | 1/2 / 1/2 / 1/2 |
| legacy_diagnostic | D 完整 | 2 | 2 | 0 | 2616.58 | 3213.24 | 0/2 / 0/2 / 0/2 |

无距离结果不填0米。Top-K 的端到端分母包含 API/匹配失败，不能把缺少推理输出的行解读成几何错位；完整误差分布 n/p25/p75/p90/min/max 与失败阶段计数在 post_evaluation/summary.json。

| 图片 | 组 | Top1 m | Top3/5/10 | 最近Preferred m | Preferred km² | Feasible km²/含参考点 | 点数/可靠地标/搜索身份 | 秒 | 阶段 |
|---|---|---:|---|---:|---:|---|---|---:|---|
| photo_01 | A 搜索基线 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_01 | B 鲁棒几何 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_01 | C 联合身份 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_01 | D 完整 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_02 | A 搜索基线 | 601.68 | 是/是/是 | 0.00 | 2.06 | 64.38/是 | 9000/4/2 | 10.69 | candidate_ranking_or_model_mismatch |
| photo_02 | B 鲁棒几何 | 171.10 | 是/是/是 | 0.00 | 2.20 | 64.16/是 | 9000/4/2 | 11.64 | candidates_produced_not_necessarily_correct |
| photo_02 | C 联合身份 | 371.52 | 是/是/是 | 0.00 | 44.80 | 74.95/是 | 24000/4/12 | 23.98 | candidate_ranking_or_model_mismatch |
| photo_02 | D 完整 | 571.36 | 否/否/否 | 30.60 | 8.16 | 74.95/是 | 24000/4/12 | 34.71 | candidate_ranking_or_model_mismatch |
| photo_03 | A 搜索基线 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_03 | B 鲁棒几何 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_03 | C 联合身份 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_03 | D 完整 | — | 未运行 | — | — | —/未运行 | —/—/— | — | vision_api_or_schema_failure |
| photo_04 | A 搜索基线 | 1544.53 | 否/否/否 | 483.87 | 4.83 | 66.93/否 | 24000/7/9 | 134.18 | candidate_ranking_or_model_mismatch |
| photo_04 | B 鲁棒几何 | 1549.36 | 否/否/否 | 1.02 | 53.53 | 66.90/否 | 24000/7/9 | 205.79 | candidate_ranking_or_model_mismatch |
| photo_04 | C 联合身份 | 1637.69 | 否/否/否 | 372.03 | 4.96 | 67.37/否 | 24000/6/12 | 65.82 | candidate_ranking_or_model_mismatch |
| photo_04 | D 完整 | 1664.20 | 否/否/否 | 1172.25 | 6.84 | 67.37/否 | 24000/7/12 | 240.81 | candidate_ranking_or_model_mismatch |
| photo_05 | A 搜索基线 | 1133.00 | 否/否/否 | 605.41 | 3.27 | 60.19/是 | 24000/6/9 | 23.36 | candidate_ranking_or_model_mismatch |
| photo_05 | B 鲁棒几何 | 1141.77 | 否/否/否 | 0.00 | 36.32 | 60.09/是 | 24000/6/9 | 41.24 | candidate_ranking_or_model_mismatch |
| photo_05 | C 联合身份 | 1277.82 | 否/否/否 | 488.97 | 15.63 | 66.97/是 | 24000/5/12 | 24.11 | candidate_ranking_or_model_mismatch |
| photo_05 | D 完整 | 1097.82 | 否/否/否 | 865.63 | 5.03 | 67.04/是 | 24000/6/12 | 47.41 | candidate_ranking_or_model_mismatch |
| photo_06 | A 搜索基线 | 1660.83 | 否/否/否 | 638.10 | 5.29 | 64.95/是 | 18000/4/4 | 29.99 | candidate_ranking_or_model_mismatch |
| photo_06 | B 鲁棒几何 | 1299.81 | 是/是/是 | 0.00 | 23.85 | 64.81/是 | 18000/4/4 | 49.97 | candidate_ranking_or_model_mismatch |
| photo_06 | C 联合身份 | 1332.06 | 是/是/是 | 0.00 | 54.56 | 74.35/是 | 24000/3/12 | 51.97 | candidate_ranking_or_model_mismatch |
| photo_06 | D 完整 | 1397.40 | 是/是/是 | 0.00 | 10.34 | 74.36/是 | 24000/4/12 | 90.01 | candidate_ranking_or_model_mismatch |
| photo_07 | A 搜索基线 | 1393.46 | 否/否/否 | 578.27 | 1.38 | 51.12/是 | 9600/5/4 | 8.84 | candidate_ranking_or_model_mismatch |
| photo_07 | B 鲁棒几何 | 733.31 | 否/否/否 | 316.05 | 3.01 | 50.93/是 | 9600/5/4 | 15.48 | candidate_ranking_or_model_mismatch |
| photo_07 | C 联合身份 | 441.36 | 否/否/否 | 67.44 | 2.19 | 63.21/否 | 6000/4/3 | 7.46 | candidate_ranking_or_model_mismatch |
| photo_07 | D 完整 | 848.31 | 否/否/否 | 67.44 | 2.79 | 62.93/否 | 6000/5/3 | 12.78 | candidate_ranking_or_model_mismatch |
| photo_08 | A 搜索基线 | 498.17 | 否/否/否 | 263.07 | 0.11 | 69.05/否 | 9000/4/2 | 25.60 | candidate_ranking_or_model_mismatch |
| photo_08 | B 鲁棒几何 | 576.28 | 否/否/否 | 384.46 | 0.69 | 68.96/否 | 9000/4/2 | 42.36 | candidate_ranking_or_model_mismatch |
| photo_08 | C 联合身份 | 451.06 | 否/否/否 | 146.03 | 49.73 | 78.27/否 | 24000/2/12 | 62.60 | candidate_ranking_or_model_mismatch |
| photo_08 | D 完整 | 514.56 | 否/否/否 | 382.67 | 6.84 | 78.26/否 | 24000/4/12 | 105.13 | candidate_ranking_or_model_mismatch |
| photo_09 | A 搜索基线 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_specific_identity_evidence |
| photo_09 | B 鲁棒几何 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_specific_identity_evidence |
| photo_09 | C 联合身份 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_specific_identity_evidence |
| photo_09 | D 完整 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_specific_identity_evidence |
| photo_10 | A 搜索基线 | 3178.58 | 否/否/否 | 405.32 | 45.97 | 145.58/是 | 24000/2/7 | 74.22 | candidate_ranking_or_model_mismatch |
| photo_10 | B 鲁棒几何 | 2792.40 | 否/否/否 | 981.75 | 57.13 | 145.58/是 | 24000/2/7 | 92.62 | candidate_ranking_or_model_mismatch |
| photo_10 | C 联合身份 | 2552.13 | 否/否/否 | 755.12 | 16.56 | 144.30/是 | 24000/2/6 | 72.20 | candidate_ranking_or_model_mismatch |
| photo_10 | D 完整 | 2772.24 | 否/否/否 | 2049.77 | 3.52 | 144.32/是 | 24000/2/6 | 93.58 | candidate_ranking_or_model_mismatch |
| photo_11 | A 搜索基线 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_reliable_observations |
| photo_11 | B 鲁棒几何 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_reliable_observations |
| photo_11 | C 联合身份 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_reliable_observations |
| photo_11 | D 完整 | — | 否/否/否 | — | 0.00 | 0.00/否 | 0/0/0 | 0.00 | vision_insufficient_reliable_observations |
| photo_12 | A 搜索基线 | 6695.83 | 否/否/否 | 3659.26 | 25.76 | 72.62/否 | 4500/2/1 | 14.67 | reference_outside_assignment_distance_search_domains |
| photo_12 | B 鲁棒几何 | 8746.24 | 否/否/否 | 3659.26 | 70.03 | 72.66/否 | 4500/2/1 | 16.46 | reference_outside_assignment_distance_search_domains |
| photo_12 | C 联合身份 | 6695.83 | 否/否/否 | 3659.26 | 25.76 | 72.62/否 | 4500/2/1 | 14.08 | reference_outside_assignment_distance_search_domains |
| photo_12 | D 完整 | 9592.64 | 否/否/否 | 3661.49 | 1.50 | 72.66/否 | 4500/2/1 | 16.61 | reference_outside_assignment_distance_search_domains |
| legacy_beijing_cbd | A 搜索基线 | 1894.47 | 否/否/否 | 320.48 | 23.51 | 74.32/是 | 4500/2/1 | 12.73 | candidate_ranking_or_model_mismatch |
| legacy_beijing_cbd | B 鲁棒几何 | 3362.40 | 是/是/是 | 0.00 | 74.15 | 74.32/是 | 4500/2/1 | 16.31 | candidate_ranking_or_model_mismatch |
| legacy_beijing_cbd | C 联合身份 | 1894.47 | 否/否/否 | 320.48 | 23.51 | 74.32/是 | 4500/2/1 | 12.20 | candidate_ranking_or_model_mismatch |
| legacy_beijing_cbd | D 完整 | 3362.40 | 否/否/否 | 1855.56 | 1.97 | 74.32/是 | 4500/2/1 | 16.06 | candidate_ranking_or_model_mismatch |
| legacy_north_bund | A 搜索基线 | 63.75 | 是/是/是 | 0.00 | 6.66 | 63.44/是 | 24000/4/6 | 83.08 | candidates_produced_not_necessarily_correct |
| legacy_north_bund | B 鲁棒几何 | 1950.68 | 否/否/是 | 0.00 | 3.86 | 62.92/是 | 24000/3/6 | 144.59 | candidate_ranking_or_model_mismatch |
| legacy_north_bund | C 联合身份 | 2104.10 | 是/是/是 | 0.00 | 17.21 | 68.70/是 | 24000/3/12 | 96.12 | candidate_ranking_or_model_mismatch |
| legacy_north_bund | D 完整 | 1870.76 | 否/否/否 | 151.27 | 6.65 | 68.71/是 | 24000/3/12 | 193.47 | candidate_ranking_or_model_mismatch |

## 已有样点的阶段归因

record_diagnostic_trace 默认 False。启用时仅记录已有点：hard_feasible、phase、score/components、UNKNOWN/OUTLIER、FOV、同身份分数排名、窗口阈值和 selection_stage；不改变选择。观察器一致性测试要求同一输入诊断前后几何/分数/面积/样点数逐项相等。

阶段标签：hard_rejected（已搜索但物理拒绝）、visual_rejected（通过硬约束但旧视觉模型拒绝）、below_score_window（已评分但低于所在分片/分量阈值）、cell_clipping_or_no_component_membership（达到窗口但裁剪/成员归属未进入输出模式）、region_cap（形成区域后因输出上限丢失）、preferred（保留）。200m 内没样点只表示该半径未采样，不推断绝对不可能；搜索域是否包含参考点另看几何，有限网格不是连续覆盖证明。

逐点诊断只针对 development 与两张旧例；post_evaluation/point_diagnostics.json 保存每身份的全域/附近阶段计数、最近已有样点、附近最高分样点、排名、分项、阈值、丢弃原因与最终区域排名。没有在真实坐标处补点或重跑求解。

| 样本/组 | 最近实际样点 m | 200m 内阶段计数 |
|---|---:|---|
| photo_02 / A 搜索基线 | 12.25 | {"below_score_window": 3, "preferred": 5, "hard_rejected": 3, "region_cap": 1, "visual_rejected": 6} |
| photo_02 / B 鲁棒几何 | 7.64 | {"preferred": 7, "below_score_window": 8} |
| photo_02 / C 联合身份 | 8.61 | {"preferred": 32, "region_cap": 9, "hard_rejected": 11, "below_score_window": 9, "visual_rejected": 2} |
| photo_02 / D 完整 | 8.61 | {"region_cap": 32, "hard_rejected": 6, "preferred": 2} |
| photo_08 / A 搜索基线 | 26.56 | {"visual_rejected": 4, "hard_rejected": 6} |
| photo_08 / B 鲁棒几何 | 26.56 | {"below_score_window": 6, "hard_rejected": 8} |
| photo_08 / C 联合身份 | 24.04 | {"hard_rejected": 14, "visual_rejected": 26, "region_cap": 4, "below_score_window": 1} |
| photo_08 / D 完整 | 24.04 | {"hard_rejected": 15, "below_score_window": 19, "region_cap": 13} |
| photo_10 / A 搜索基线 | 42.27 | {"visual_rejected": 16, "below_score_window": 6} |
| photo_10 / B 鲁棒几何 | 25.32 | {"below_score_window": 13, "region_cap": 11} |
| photo_10 / C 联合身份 | 56.18 | {"visual_rejected": 16, "below_score_window": 2} |
| photo_10 / D 完整 | 56.18 | {"region_cap": 28} |
| photo_11 / A 搜索基线 | — | {} |
| photo_11 / B 鲁棒几何 | — | {} |
| photo_11 / C 联合身份 | — | {} |
| photo_11 / D 完整 | — | {} |
| legacy_beijing_cbd / A 搜索基线 | 68.24 | {"below_score_window": 9} |
| legacy_beijing_cbd / B 鲁棒几何 | 68.24 | {"preferred": 7} |
| legacy_beijing_cbd / C 联合身份 | 68.24 | {"below_score_window": 9} |
| legacy_beijing_cbd / D 完整 | 68.24 | {"region_cap": 7} |
| legacy_north_bund / A 搜索基线 | 43.45 | {"visual_rejected": 36, "hard_rejected": 5, "preferred": 15, "region_cap": 2} |
| legacy_north_bund / B 鲁棒几何 | 26.41 | {"below_score_window": 30, "hard_rejected": 4, "region_cap": 3, "preferred": 1} |
| legacy_north_bund / C 联合身份 | 3.52 | {"visual_rejected": 30, "preferred": 36, "hard_rejected": 8, "region_cap": 4, "below_score_window": 13} |
| legacy_north_bund / D 完整 | 12.41 | {"region_cap": 41, "hard_rejected": 2, "preferred": 3} |

## 根因证据、假设与下一步

每例视觉/地图身份审查、北京/北外滩评分差异与区域截断证据见 [根因分析](REAL_CAMERA_ROOT_CAUSES.md)。数据支持的问题与尚未验证的解释必须分开；本阶段未据此调整权重或参数。

## 自动化测试与开发失败

最终 uv run pytest -q：391 passed in 29.91s，0 failed，0 skipped，包含原有378项。定向13项全部通过。真实超时、开发中测试守卫误报、Windows路径兼容与零采样null修复均如实记录在 [VALIDATION.md](evaluation/real_camera_diagnostics/VALIDATION.md)，没有跳过失败测试。

## 复现命令与边界

```powershell
uv run python scripts/collect_camera_dataset.py
uv run python scripts/freeze_camera_dataset.py
uv run python scripts/run_camera_benchmark.py --live
uv run python scripts/retry_camera_failures.py
uv run python scripts/run_camera_benchmark.py
uv run python scripts/diagnose_camera_benchmark.py
uv run python scripts/audit_camera_assumptions.py
uv run python scripts/render_camera_annotations.py
uv run python scripts/report_camera_root_causes.py
uv run python scripts/report_camera_benchmark.py
uv run pytest -q
```

采集在冻结后只验哈希、不再下载；冻结脚本拒绝覆盖。核心指标离线复核从 diagnose 开始，不需要 Key/模型；若本地不存在SQLite则跳过详细评分重审，已有审计文件仍可阅读。详细重审有数据库时强制核对原SHA，不接受不同快照。run 不加 --live 只复用成功视觉缓存，失败不会自动再次付费；缺少原 SHA 地图时拒绝悄悄换数据。完整几何 JSON 以 gzip 保存，未删失败输出。OSM 继续 © OpenStreetMap contributors / ODbL；不提交数据库和原始 Overpass 大缓存。
