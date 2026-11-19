# Stage 5.4 实际执行与失败记录

2026-11-19在当前仓库开发。开始main=46ead51a6d5343ef3e54f7dc6722e92fde303b52，工作区干净。首次pull遇schannel TLS握手失败，随后再次git pull --ff-only origin main成功，已最新；无覆盖历史提交。复核Stage5.2/5.3代码、测试、既有评估和实际Pipeline接口，未重新选型。

## 实际命令

```powershell
uv run pytest -q tests/test_stage54_automatic.py tests/test_stage54_pipeline.py tests/test_stage52_selection.py tests/test_app_pipeline.py
uv run pytest -q tests/test_stage54_demo.py tests/test_app_page.py tests/test_stage53_demo.py
uv run python scripts/run_stage54.py
uv run python scripts/evaluate_stage54.py
uv run python scripts/report_stage54.py
uv run streamlit run src/geophotoloc/app/main.py --server.headless true --server.port 8512 --browser.gatherUsageStats false
uv run --with playwright python scripts/verify_stage54_browser.py
uv run pytest -q
```

真实执行最终全量：**454 passed in 56.91s，0 failed，0 skipped**。原433项全部保留，新增21项。关系/单图/原选择器与Pipeline定向33 passed in 1.95s；页面定向9 passed in 9.25s；单图及同网格构造后续定向3 passed in 0.68s。最终全量已包含后续新增的精确合并回归、正式真实缓存校验及全部Stage5.2/5.3测试。

## 推理冻结、同输入与正式对照

rules_frozen_before_inference.json记录预定公式、六位小数排序、合并/预算约束及源码规范LF SHA。正式轮之前使用合成场景和不含机位参考的测试固定规则。F完整重跑原D/E搜索，12个有效视觉缓存逐例严格验证：配置除selection_strategy外相同、完整采样坐标/phase/原分数及分项SHA相同、原Feasible序列化字段相同。没有新视觉请求或地图下载；原API请求账本仍17次。没有读取用户照片文件名/来源作为城市或身份提示，正常Pipeline.run只接收图片路径。

首例photo_02启动校验发生tuple/list表示误报：内存GeoJSON tuple与冻结JSON list直接比较不等。第一次计算未保留；第二次为定位校验原因保留到本机.cache/stage54_guard_photo_02.json.gz，确认序列化后物理区域严格相同，且配置/trace本来相同。修复的是评估运行器的JSON比较，不是算法或阈值。正式轮复用第二次只读诊断输出，再计算其余11例；因此首例实际多计算1次，最终只有一轮固定规则正式比较，没有利用参考坐标迭代。诊断缓存不提交，完整有效结果已提交。

全部F/A层保存后才冻结inference_manifest.json；独立evaluate_stage54.py先校验全部SHA，之后才读dataset_references。正式推理没有camera reference，未在参考点补采样或重新评分。原D/E输出只读引用，Stage5.2/5.3数据不改。formal manifest存在时运行器拒绝覆盖；直接重评估/离线Demo不需数据库或API。重算需在独立干净实验目录使用相同SHA的本地SQLite，不自动下载替代地图。

A0直接复制原S0，A1同几何/面积/点集合，给出全体关系分布而非虚构收缩；A2几何严格等于F实际区域并集，面积等于F.preferred_area_m2。完整F包含全体点关系、每边视觉权重/身份/一致性/加权分、区域截断质量与关系分。身份仍多候选，缺失关系null为中性0.5排序贡献，不作为概率。

## 开发发现的其他失败及修复

- 首轮10 failed/23 passed：复用的合成SimpleNamespace候选缺原MapMatchCandidate.score字段，补全新测试夹具契约；没有降低正式模型校验或删除用例。之后该定向33项通过。
- 报告生成首次KeyError status：历史D的API失败行使用stage而没有status，报告兼容历史字段；完整缺失Top1/距离仍为null，不填0。修复仅影响展示，不重跑推理或改变指标。
- 无测试被跳过或删除；没有根据本轮真实误差调整权重、FOV、距离、区域上限或关系公式。

## 单照片端到端与Demo

Mock测试只传一张照片，真实执行现有MapMatcher、Stage54多身份搜索、关系评分、区域选择和A层输出；重复同照片只调用一次Mock视觉接口并命中缓存。没有城市、GPS、身份确认、相机参数或人工标注输入。默认Pipeline为F，显式旧search_config保留原路径；在线UI默认F，旧路线可选。

真实本机Chrome浏览器验收已完成，使用临时uv --with playwright，不修改项目依赖/锁文件，不下载浏览器。实际选择Stage5.4、验证A0/A1/A2及F代表样点、开关A1使Leaflet图层数量增加、默认无参考Tooltip，主动勾选独立评估后才出现参考标记，page_errors=[]。截图photo02_automatic.png、photo02_evaluation.png及browser_acceptance.json在demo/。地图JS/CSS本地资源，无CDN；未发布外网站点。旧历史独立评估也增加主动加载开关。

## 结果限制

8/12新增照片有有效Top1，2张历史视觉失败和2张低证据不计虚假米级误差。E→F总体中位1247.61m不变，P90 3993.23m不变；Top5包含由0/12变1/12，Top10仍2/12。photo_02 Top1 571.36→224.34m、最低包含排名6→4；北外滩最低仍13，北京和photo_04仍失败。photo_02优选面积8.735→8.874km²，北外滩5.906→6.125km²，不能把排序局部改善当作整体范围更精确。

本轮只描述已有小样本，旧holdout已查看不是泛化验证；自报Camera location精度未知。关系软证据无法解除原物理硬拒绝，也不能保证大量同几何档模式的正确排名。完整D/E/F、42行A层、失败阶段、分布与逐例排名变化全部保留。

交付检查：严格解析全部JSON/压缩JSON（交付清单生成前33份）；实际本地凭据及常见Token模式扫描通过。冻结算法源码规范LF SHA保持一致，Stage5.2/5.3及更早评估/地图/视觉数据未修改。未提交.env、SQLite、原始OSM、虚拟环境或临时缓存。pytest_result.txt保留本次真实终端测试输出，delivery_manifest.json冻结交付文件SHA。
