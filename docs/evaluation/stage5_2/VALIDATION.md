# Stage 5.2 实际执行、修复和失败记录

2026-11-18至19日在当前仓库执行。开始时main=a5f579637942d3e319eaa136be9acb5f0a4d2b59，工作区干净，已pull --ff-only。未发现适用AGENTS.md。阅读README、Stage5.1B、REAL_CAMERA_DIAGNOSTICS/ROOT_CAUSES及原VALIDATION，检查实际Solver/匹配/页面后开始。

## 实际命令

```powershell
uv run pytest -q tests/test_stage52_selection.py
uv run python scripts/run_stage52.py --solve-only
uv run pytest -q tests/test_stage52_refinement.py tests/test_stage52_demo.py
uv run python scripts/run_stage52.py --refine-only
uv run python scripts/evaluate_stage52.py
uv run python scripts/report_stage52.py
uv run python scripts/export_stage52_demo.py --case photo_02
uv run streamlit run src/geophotoloc/app/main.py --server.headless true --server.port 8510 --browser.gatherUsageStats false
uv run --with playwright python .cache/verify_stage52_browser.py
uv run pytest -q
```

Chrome使用本机已安装浏览器，Playwright只作为临时验收工具，未改pyproject.toml/uv.lock。实际启动8510本地服务，未发布外网站点。静态HTML及截图位于demo/；浏览器接受记录包含真实图层开关、默认隐藏参考和显式评估后的参考Tooltip验证。

## 运行与测试

原391项全部通过。第一次全量（新增测试尚未全部完成）：405 passed in 28.36s。最终全量：411 passed in 35.49s，0 failed，0 skipped。最终构造/集成定向17 passed in 4.92s。

最终12个有视觉缓存案例均完成E和S0/S1/S2（10张新增+2旧例），2张历史API超时保持未执行。原2张证据不足压力图不制造区域，新增每算法有效Top-1 8/12。A/B/C/D原结果直接引用，没有改写；严格比较D/E原分数、实际网格和Feasible，12例全部一致。推理与层结果指纹冻结后才读取参考点；后评估再次校验原文件未变。

## 真实发现的失败及修复

- 首次E公平性守卫把新内存GeoJSON的tuple与加载旧JSON的list当作几何不同而拒绝；保存再读后证实完全相同，改用JSON模式归一化比较，未改变数据。
- 构造集成曾1 failed/24 passed：局部米制包含关系正确，但转WGS84后的直线弦存在6.85e-11平方度细缝，不能把平方度误作米制误差。展示层再次求交保证显示嵌套，不放大buffer；最终米制面积不拿平方度计算。
- 新UI单测曾2失败，分别为Folium JSON转义的中文断言和测试夹具漏geojson；补齐夹具/检查正确编码表示，断言仍验证三层、真实数值和参考隔离。
- 真实S层构造触发GEOS TopologyException。整体MultiPolygon make_valid可能由偶奇填充抹掉约4.75km²，安全面积守卫拒绝运行；逐组件修复再精确并集保留面积，记录area_delta，超过阈值仍拒绝。加入零面积尖刺、微重叠和实质自交拒绝回归。
- 初版E使用几何哈希做平局顺序，新增submicrometre测试真实出现1 failed/6 deselected：同样点/同分，仅几何1e-8m扰动就换保留模式。改为毫米稳定坐标键，哈希只作标识，7个选择测试全部通过。保留development_initial中的源、配置指纹和完整评估指标；完整初版压缩运行输出在本地.cache/stage52_initial。之后只重跑最终版本一次，未改评分、FOV、距离或输出预算。
- 首次真实浏览器地图空白，报L未定义及失败重试导致的重复变量；原内联header脚本并未被streamlit-folium执行。改为本地资源data URL依赖并重启自己的本地服务，实际地图绘制/开关和参考显示均通过，page_errors=[]。没有引入外网CDN。
- 浏览器自动化曾因Streamlit虚拟表格隐藏a11y单元格、透明checkbox被label覆盖而超时；分别等待节点附着并核验真实地图、点击用户实际可见标签，未用强制点击或绕过应用状态。最终独立评估确有参考Tooltip，默认无参考。临时日志的GBK输出问题通过UTF-8检查解决。

所有失败均已修复或明确保留为旧样本失败，没有跳过失败测试。没有因为E指标不够好再调参。权重0.40/0.20/0.25/0.15、距离5km、750m分片和每身份8区域均沿用。

## 约束与复现

run_stage52.py不读取dataset_references，不调用VisionAnalyzer/百炼/Overpass。新增请求0，原请求账本仍17次。普通离线Demo不连接SQLite/网络，参考仅在显式独立评估读取；Mock在线集成一次识别后重复运行命中缓存。保留原development/holdout划分，不宣称独立泛化。

原Stage1～5.1B、真实机位诊断数据、视觉/地图原JSON均不修改。当前代码的legacy策略保持旧核心结果；需要原字节级源码/输出可回到上述main基准提交。新JSON字段有兼容默认值。完整最终Pose/层输出、所有区域审计、配置输入与网格SHA均保留；SQLite、API Key、.env、临时下载/浏览器缓存不提交。

S0/S1/S2是对固定E/D候选总体的条件消融，不是全球纯语义搜索器；面积受距离、有限覆盖和预算先验影响。S2附加构造时间复用已算几何分数，完整E求解耗时另列，不冒充端到端耗时。

浏览器验收脚本已原样保留为scripts/verify_stage52_browser.py；复现时启动上述本地服务后运行 uv run --with playwright python scripts/verify_stage52_browser.py（需本机Chrome）。交付前严格解析42份JSON/压缩JSON，扫描实际凭据及Token格式均通过；旧评估数据、几何、视觉、地图模块和依赖锁文件没有修改。delivery_manifest.json冻结本阶段文件SHA256。
