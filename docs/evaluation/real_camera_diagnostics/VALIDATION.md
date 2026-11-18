# 执行与验证记录

本批次2026-11-17采集/首轮推理，2026-11-18完成超时恢复、离线对照和后评估。真实请求的UTC时间、返回token usage、成功/失败见api_requests.json。未改变.env，未发地图请求。

## 实际执行

```powershell
uv run python scripts/collect_camera_dataset.py
uv run python scripts/freeze_camera_dataset.py
uv run pytest -q tests/test_camera_diagnostics.py
uv run python scripts/run_camera_benchmark.py --live
uvx py-spy dump --pid 25204
uvx py-spy record --pid 25204 --duration 10 --format raw --output docs/evaluation/real_camera_diagnostics/performance_sample.folded
uv run python scripts/retry_camera_failures.py
uv run python scripts/run_camera_benchmark.py
uv run python scripts/diagnose_camera_benchmark.py
uv run python scripts/audit_camera_assumptions.py
uv run python scripts/render_camera_annotations.py
uv run python scripts/report_camera_root_causes.py
uv run python scripts/report_camera_benchmark.py
uv run pytest -q
```

采集14个文件元数据，12张通过相机语义/许可检查，2张未入集；部分公共元数据HTTP暂时失败，经有限重试恢复。冻结后collect只验证图像SHA，不覆盖。freeze拒绝重写已有冻结文件（预期安全行为，不是再运行步骤）。profile命令中的PID仅为该次实际进程，不能在重现时照搬旧PID。

真实API首轮12次：7成功/5超时。显式恢复轮5次：3成功/2超时。总17次：10成功/7超时，12张图仅10份有效视觉JSON；01/03均两次超时，不伪造结果。SDK自动重试0，最多每图一次超时恢复，预算20。费用未知，超时不能认定免费。所有成功图通过现有LocalizationPipeline，A/B/C/D只复用相同视觉和匹配文件。

最终共有48份完整求解JSON gzip（10张新增成功视觉+2张旧例，每图4组）；另2张API失败在56行评估中保留，几何未运行。2张有视觉的压力样本未输出区域，最终每组新增Top-1距离有效8/12，缺失4/12。统计同时披露失败阶段和各集合分母。

## 自动化测试

首次全量：385 passed in 98.32s，0 failed，0 skipped（此时新增测试尚未全部补齐）。最终全量：391 passed in 29.91s，0 failed，0 skipped，原有378项全部通过。最终定向：13 passed in 0.34s。

覆盖：Camera/Object location区别；20次预算、重复成功保护与超时恢复次数；分数窗口/裁剪/区域上限阶段数值；诊断开关前后候选、分数、几何、面积、点数完全相同；分组隔离、图像元数据去除和哈希；统计分位数与失败分类；参考读取前校验manifest；Windows路径兼容；FOV同侧非单调/双解一致性；零采样距离必须null。

两张旧例八组额外逐项比对了历史regions和feasible_regions完整字段及实际采样点数，全部精确相等，见legacy_equivalence.json。不把不同日期/机器负载下耗时差异当算法加速。

## 实际发现的开发/运行失败及处理

- 初始定向测试两次出现同一个1 failed/4 passed：字符串守卫误把终端日志的regions=当作给匹配器提供区域先验。改为检查相关构造器的AST关键字，保留并加强了隔离断言，未删除测试。
- 首次后评估在读取参考点之前被完整性守卫拒绝：Windows manifest路径使用反斜杠而期望集合用正斜杠。统一规范化并校验原文件哈希，新增Windows路径回归，之后完整后评估成功。
- 开发审查发现无可搜索假设时nearest_sample_m可能为Infinity；修复为null并增加严格JSON回归。发现同侧射线FOV关系并非全局单调，替换为解析一致性诊断并验证多解；两者只涉及新评估工具，没有改定位评分。
- 部分临时终端检查使用系统GBK默认编码读取UTF-8失败，改为显式UTF-8；未改写源数据。公开下载短暂HTTP失败已记录；视觉7次超时仍作为失败保留，未切换模型。

## 可复现边界

没有根据参考点调参。推理输入与原始JSON、匹配、配置、地图SHA和完整推理输出均冻结；所有后评估前后验证原文件哈希。核心指标只依赖这些文件，详细评分重审需要本机保留的原SHA SQLite；不提交大规模原始OSM、SQLite、下载缓存、.env或凭据。新鲜在线地图不能被宣称为相同快照。

诊断集给出逐点流转；保留集只提供总体指标、原始输出和阶段审查，不按参考点逐点调参。本轮保留集已被查看，未来若用于开发，需另设新的独立保留集。
