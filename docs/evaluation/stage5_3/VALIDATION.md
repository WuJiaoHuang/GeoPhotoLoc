# Stage 5.3 实际执行记录

2026-11-19，当前main起点55e15dd9c94507e9b12b5301beac2ff51a62d9ff，工作区干净，git pull --ff-only origin main显示已最新。复核Stage5.2实现、模型、Demo、测试、评估及原始网格/评分缓存；无适用AGENTS.md。未修改历史数据、视觉输出、地图快照、依赖或原几何评分。

## 实际命令

```powershell
uv run pytest -q tests/test_stage53_relations.py
uv run pytest -q tests/test_stage53_relations.py tests/test_stage53_refinement.py tests/test_stage52_refinement.py
uv run python scripts/run_stage53.py
uv run python scripts/evaluate_stage53.py
uv run python scripts/report_stage53.py
uv run streamlit run src/geophotoloc/app/main.py --server.headless true --server.port 8511 --browser.gatherUsageStats false
uv run --with playwright python scripts/verify_stage53_browser.py
uv run pytest -q
```

最终全量实际通过：**433 passed in 49.81s，0 failed，0 skipped**。原411项全部保留；新增22项。合成/边界加原空间层定向25 passed in 2.33s。旧S0/S1/S2逐字段相等、网格SHA相等、12份真实完整输出包含关系与SOFT算术均值/null语义有自动化断言。

## 正式真实实验

规则和源码SHA先写rules_frozen_before_inference.json，再执行一次完整正式推理；12份已有视觉案例全部成功完成，另2份历史视觉失败不重试。空网格压力样本仍为空。最后冻结inference_manifest.json，独立评估脚本先校验SHA，再读取参考机位。原结果直接复制，未重新求解E或更改阈值；后评估/报告为展示字段完善执行过多次，没有重跑正式推理或调整规则。

新VLM/Overpass请求均0；原账本仍17次。费用无新增API用量；未估计历史费用。SOFT均值未影响排序，完整几何仅消费原缓存分数。所有新/旧5层的70行指标及逐候选记录均保存。运行已冻结，run_stage53.py检测正式manifest存在即拒绝覆盖；可直接离线评估/展示。独立干净实验目录重算需要原SHA的本地SQLite快照，不能自动下载替代数据。下载/SQLite/浏览器临时缓存不提交。

## 开发过程中发现并修复的失败

- 第一轮关系测试15 failed/1 passed：合成SimpleNamespace地图夹具缺name/aliases，复用真实same_physical_entity接口时AttributeError。补全夹具契约，没有修改实体判同算法或删断言。
- 补全后1 failed/15 passed：测试预期漏掉现有image_x自动生成的b/c边，实际三条SOFT边均值为(0+0.5+1)/3=0.5；明确修正为三边预期，保留去重与均值验证。随后关系/构造测试17通过，加入硬证据合成构造及旧层回归后25通过。
- 页面测试1 failed/22 passed：Streamlit表格把None显示为Pandas NaN；使用isna验证缺失项，仍逐项断言两新层的0/20/5计数和全部层顺序。
- 第一次真实浏览器参考标记断言失败：固定5秒等待早于大GeoJSON组件重建完成；改为最多30秒轮询真实Leaflet Tooltip，未强制注入标记或绕过应用状态。最终五层、实际图层开关、默认隐藏与主动评估参考均通过，page_errors=[]。浏览器工具为临时Playwright+已安装Chrome，未改项目依赖。
- 第一轮全量进程回执在客户端续接时不可读取，因此再次实际执行全量并保存日志；最终433/49.81s为可读实际结果，没有推断通过。

## Demo与限制

demo/browser_acceptance.json记录真实Chrome交互；photo04_parallel_layers.png和photo04_independent_evaluation.png分别为默认与独立评估界面。Stage5.2模式/在线路径保持，新增版本显式可选；默认不读参考文件。地图资源打包本地，无外网底图。S1与S1-R并列，S2/S2-R分别继承对应关系层。

本轮没有独立身份及完整可见轮廓证据，因此真实HARD为0且S1-R未缩小。避免了一例旧S1参考排除，不代表可靠性分级在真实场景已取得精确定位提升。S2-R仍只有2/8非空新增样本含参考；Q2参考误差未知，旧holdout已查看，不是泛化验证。后续应补独立身份/可见性证据并诊断原物理掩膜及评分选择链，不能为这批参考坐标调规则。

交付检查：严格解析20份JSON/压缩JSON（含交付清单），实际.env凭据及常见Token模式扫描通过，未提交.env、SQLite、原始地图、虚拟环境或缓存；旧Stage5.2及更早评估数据没有修改。冻结算法源码SHA核验一致。delivery_manifest.json记录本阶段交付文件SHA。
