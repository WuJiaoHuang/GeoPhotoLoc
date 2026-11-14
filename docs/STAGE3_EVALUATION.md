# Stage 3：OSM 地标获取与实体匹配验收

执行日期：2026-11-14，Asia/Shanghai。完成有限区域地图获取、真实几何解析、SQLite 持久化、保留歧义的实体匹配与区域一致性检查。**没有调用视觉模型或收费地图，没有求解摄影机位。**

## 真实地图覆盖

实际从 [Overpass 公共接口](https://overpass-api.de/api/interpreter) 顺序获取三个有限区域。覆盖范围用于准备 Demo 地图库，不是摄影师位置或 GPS 先验。查询命名要素、建筑轮廓及塔类要素，不获取可能扩展至全国的公交线路/行政区关系。服务端查询超时 45 秒、HTTP 超时 90 秒，响应最多 32 MiB/30,000 要素，明确 User-Agent，429/502/503/504 与网络异常有限退避重试。

| 区域 | bbox（南、西、北、东） | 有效要素 | 有名称/别名 | 完整面轮廓 | OSM 基准时间 UTC |
| --- | --- | --- | --- | --- | --- |
| 上海 | 31.215,121.475,31.265,121.535 | 12,456 | 6,398 | 7,358 | 2026-11-13 17:00:51 |
| 北京 | 39.899,116.440,39.928,116.478 | 3,481 | 1,713 | 2,081 | 2026-11-13 17:00:51 |
| 广州 | 23.100,113.306,23.140,113.340 | 5,241 | 3,233 | 2,715 | 2026-11-13 17:01:50 |
| 合计 | 三个独立有限区域 | **21,178** | **11,344** | **12,154** | — |

精确查询、来源与获取时间见 [imports.json](evaluation/stage3/imports.json)，OSM 署名和 ODbL 许可见 [ATTRIBUTION.md](evaluation/stage3/ATTRIBUTION.md)。最终复测从成功缓存读取，保留原始获取时间，没有伪装为再次下载。

北京首次遇到 HTTP 502，后续有限顺序尝试成功。开发中发现 `out ... geom center` 会只返回中心，已改为 `out meta geom`、重新获取三个区域并添加回归测试，没有把中心冒充轮廓交付。

当前有效覆盖包括 4,765 个 node、12,154 个完整面、4,257 个完整线/其他几何、2 个部分几何，中心回退为 0。修复的无效源几何标记为部分几何；闭合道路仍保留为线，建筑轮廓与 multipolygon 孔洞保留，缺失片段不跨缺口连接。解析器仍支持仅中心回退，并明确标注不足。

重复导入后同 OSM 类型/ID 的重复组为 **0**。刷新替换区域成员关系，历史记录仍可按 ID 查询，但早期查询留下的 1,265 条非当前区域成员记录不参与名称、范围检索或匹配。统计见 [database_validation.json](evaluation/stage3/database_validation.json)。大规模原始响应与 SQLite 均位于 Git 忽略的 `.cache/geophotoloc/`。

## 真实验证流程与独立比较

直接使用 Stage 2.1 的三份原始 `VisionExtractionResult`，没有编辑名称、候选、中心、框、关系或置信度。输入字节哈希见 [vision_input_hashes.json](evaluation/stage3/vision_input_hashes.json)。

`scripts/evaluate_stage3.py` 在导入后调用 `MapMatcher(store).match(vision)`，**没有传入地区、照片文件名、样本 ID 或人工答案**。先进行全库名称种子检索，由命中实体的区域成员关系生成候选覆盖区域，再在这些区域重查其他对象并构建一致组合。生产模块不读取 `docs/` 或测试答案，没有名称到城市的特殊规则。

`scripts/compare_stage3.py` 在结果保存后单独进行离线比较，使用 Stage 2.1 已有照片身份/人工物体对应，以及独立核对的 [7 个真实 OSM 实体摘录](evaluation/stage3/reference_entities.json)。这些参考数据不参与导入或匹配。

## 实体与真实坐标

下表为纬度、经度，均为真实 OSM 建筑几何内部的代表点，**不是入口、拍摄点或 GPS**。完整几何、标签、精度、评分依据和来源保存在各候选 JSON。

| 真实照片目标 | 核验实体 | 代表点纬度、经度 | 结果 |
| --- | --- | --- | --- |
| 东方明珠 | [way 40778038](https://www.openstreetmap.org/way/40778038) | 31.241946,121.495260 | Top-1 正确，1.000；上海中心仍为错误备选 |
| 广州塔 | [way 584204634](https://www.openstreetmap.org/way/584204634) | 23.109014,113.319148 | Top-1 正确，1.000；另保留较弱广州塔楼候选 |
| 广州东塔 | [way 299687657](https://www.openstreetmap.org/way/299687657) | 23.120553,113.320877 | 正确实体 Top-2，0.908；Top-1 错排为西塔，0.966 |
| 广州西塔 | [way 184738716](https://www.openstreetmap.org/way/184738716) | 23.120251,113.317864 | 地图有数据；视觉无独立对象，没有补造图像地标 |
| 中国尊 | [way 599547918](https://www.openstreetmap.org/way/599547918) | 39.911501,116.460236 | `CITIC Tower (China Zun)` 命中 `CITIC Tower`，Top-1 正确，0.879 |
| 央视总部 | [relation 7820447](https://www.openstreetmap.org/relation/7820447) | 39.913823,116.457389 | `CCTV Headquarters` 跨语言命中，Top-1 正确，0.940 |
| 侨福芳草地 | [way 156297801](https://www.openstreetmap.org/way/156297801) | 39.918040,116.442677 | 地图有名称和轮廓；视觉仅通用描述，未匹配 |

这些评分是检索启发式，不是概率，所有 `identity_certain` 均为 false。“Top-1 正确”是单独离线核验结论，不是匹配器自行确认身份。

## 每张照片的候选与空间一致性

**北京 CBD**：[完整结果](evaluation/stage3/beijing_cbd_matches.json)。中国尊 `lm_1` 与央视 `lm_2` 各返回一个正确候选，构成北京双地标组合，状态 `TENTATIVE`；另外 5 个对象均明确返回未匹配原因。央视 relation 与同 Wikidata 的园区 way 保留等价引用，不作为两个物体重复支持。

`Fortune Financial Center` 在当前覆盖中没有可用正确名称/别名，不能把上海 `Oriental Financial Centre` 仅因共享 Financial Centre 等常见词而匹配过去；特异词检查已拒绝这种模糊假阳性。本次只记录名称与索引缺口，不声称该建筑在整个 OSM 中不存在。

**广州天际线**：[完整结果](evaluation/stage3/guangzhou_skyline_matches.json)。`lm_1` 的 Top-3 为广州塔、西塔、东塔的较弱变体；`lm_2` 的 Top-3 为西塔、东塔、上海 International Finance Center。领先区域为广州，最多支持 2 个不同对象，状态 `AMBIGUOUS`。上海弱候选只能单独形成低支持地区假设，不能与广州塔拼成跨城组合。

东西塔都位于合理近邻范围，名称和视觉备选存在混淆，当前区域/距离检查无法识别照片框究竟对应哪一栋；保留 Top-1 错误，不用人工答案调换排名。当前有界组合搜索拒绝了 2 次重复实体分配；此值是检查触发次数，不是穷举所有组合的数量。

`lm_3` 的 `Haixinsha Island` 没有命中类型兼容的命名岛屿实体；英文 Haixinsha 命中的是轨道交通站点，已过滤，不能拿站点坐标冒充岛屿。`lm_4` 只有 CCB 建筑描述，也不强制匹配。没有使用人工补充坐标或名称表填补结果。

**东方明珠**：[完整结果](evaluation/stage3/oriental_pearl_matches.json)。首选东方明珠，第二候选上海中心来自视觉模型的 `Shanghai TV Tower` 备选，仍保留为歧义。两种组合都在上海覆盖内，但都只由单个图像对象支持，不能确立唯一地区，更不能给出摄影机位。

## 样本统计

[独立比较结果](evaluation/stage3/comparison.json)：

- 7 个固定真实参考目标中，6 个在视觉输出中有对象，西塔为视觉阶段漏检。
- 对 6 个对象，**Top-1 正确 4 个，Top-1 错误但正确实体在 Top-K 中 1 个，未匹配 1 个**。正确身份 Top-K 覆盖 5/6；多个候选列表同时包含错误实体，不是“Top-K 全部正确”。
- 其中有具体名称/候选线索的 5 个固定目标均包含正确 Top-K 身份；芳草地只有通用描述，不计为命名识别成功。
- 全部 12 个视觉对象中 5 个有候选、7 个未匹配，没有将一个物体的多个名字分裂为漏检的其他对象。
- 领先地图覆盖分别是北京、广州、上海；这是实体共同区域假设，不等于真实拍摄城市或位置已被确认。
- 互逆图像关系按对象对、轴向去重：北京 76→38，广州 22→11，东方明珠 0→0。关系不重复计权，也不直接参与地图东西/南北判断。
- 只有 3 张选择性旅游照片，**不宣称普遍准确率**，不把不确定候选升级为自动确认身份。

## 测试与实际命令

`uv run pytest`：**245 passed，0 failed，0 skipped**，包含此前 185 项和新增 60 项 Stage 3 测试。覆盖 node/way/relation、拼接轮廓/孔洞、坐标轴、缺失/重复字段、短中文别名、SQLite 事务/持久化/重复导入、跨语言和模糊名称、类别冲突、Top-K、无名称、单/多目标、多区域、重复实体分配、距离筛选、互逆去重、超时/网络/429/502/503/504、缓存及 CLI UTF-8 JSON。离线 OSM 测试使用固定合成拓扑样例，不冒充真实来源数据。

```powershell
uv run python scripts/evaluate_stage3.py --online
# 成功获取后，以下复测只读缓存，不再次下载：
uv run python scripts/evaluate_stage3.py
uv run python scripts/compare_stage3.py
uv run python -m geophotoloc.cli map-import --region shanghai --offline
uv run python -m geophotoloc.cli map-match docs/evaluation/stage2_1/results/beijing_cbd.json --output .cache/geophotoloc/beijing_cli_matches.json
uv run pytest
```

实际 CLI 导入显示 cache=True、stale=False；无地区提示的北京 CLI 返回中国尊与央视两候选。`.env`、凭据、SQLite、原始大规模响应和临时缓存均不提交。

## Stage 4 接口与遗留问题

公开接口：`geophotoloc.maps.OverpassClient`、`LandmarkStore`、`import_region`、`MapMatcher`、`MatchConfig`、`match_landmarks`。主要模型通过 `geophotoloc.models` 导出，完整模型位于 `geophotoloc.models.maps`。

`MapMatcher(store).match(vision)` / `match_landmarks(vision, store)` 返回 `MapMatchingResult`。候选包含 `MapLandmark` 的真实坐标、几何、精度、坐标语义、OSM/Wikidata 身份、评分组件及来源；组合包含图像 ID→实体 ID 分配、共同区域、最大地标间距离和检查依据。

尚未解决：东西塔排序、错误视觉别名传播、通用描述无身份、OSM 多语言名称缺口、低分模糊候选假阳性。空间一致性仅检查共同区域、实体唯一性及默认 15 km 的两两距离，使用有界 beam，不证明真实视场同时可见。低支持地区可保留，输出截断有警告，不伪装成全球唯一地区。

Stage 4 应保留歧义，区分轮廓、部分几何、真实 node 与代表点，不把地图代表点当作入口或相机位置，也不把图像左右当作地图东西。本阶段未实现摄影机位搜索或完整几何约束求解。
