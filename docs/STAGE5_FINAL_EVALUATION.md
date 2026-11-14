# Stage 5：端到端 Demo 与最终验收

日期：2026-11-14，Asia/Shanghai。已实现 Streamlit 中文界面、独立业务 Pipeline、Folium 地图、图片标注、下载、地图初始化和求解后独立机位验证。未重做 Stage 1～4 算法，未修改历史三张照片的视觉/匹配/求解输出。

## 功能与实际联调

| 项目 | 实际结果 |
| --- | --- |
| 依赖 | uv 安装 Streamlit、Folium、streamlit-folium 成功，其余复用已有依赖 |
| Web 服务 | 启动与重启两次；HTTP 首页和 `/_stcore/health` 均 200，记录见 [web_health.json](evaluation/stage5/web_health.json) |
| 页面入口 | Streamlit AppTest 执行真实 main.py，三个离线案例、模式切换、无密钥、零地标、无可行解、初始化失败重绘均无 Traceback |
| 在线业务 | 真实 LocalizationPipeline 串联现有预处理、VisionAnalyzer、MapMatcher、PoseSolver，额外调用 qwen3.8-flash **1 次成功、0 重试** |
| 重复执行 | 同图再次执行命中本会话完整缓存，无第二次模型请求；配置变化复用视觉缓存，并显式标注仅重算地图/几何 |
| 图片 | 原图保留，独立 PNG 标注在预处理后的尺寸上绘制，涵盖 EXIF 旋转测试；ID、名称、框、中心及不确定提示可下载 |
| 地图 | 多区域、地标、搜索代表点、朝向、视线、聚焦、图层与属性；单地标不添加机位；离线 JS/CSS/图标内嵌，不依赖 CDN 或瓦片 |
| 初始化 | demo-setup 在现有三个有效区域上均返回 reused；测试覆盖空库导入、重复导入、失败、不覆盖有效或损坏数据库 |
| 下载 | JSON/GeoJSON 可解析、PNG 尺寸和像素检查通过，页面有三个下载组件 |

运行环境及版本：[environment.json](evaluation/stage5/environment.json)。Python 3.11.18 / Windows，Streamlit 1.67.0、Folium 0.20.0、streamlit-folium 0.27.4，实际版本以锁文件与环境记录为准。无需 GPU。uv 项目缓存放入 Git 忽略的 `.cache/uv`，正常启动不再依赖额外缓存环境变量。

**未覆盖人工浏览器操作**：本环境采用 AppTest + 组件 HTML/数据检查 + 两次服务 HTTP 健康检查，未声称已人工逐项点击真实浏览器上传、下载、地图拖动或检查在线 OSM 瓦片。页面组件、下载载荷和本地地图资源已自动验证；这不等同人工视觉验收。

## 在线真实 Pipeline 案例

从 Commons 合法下载新增北外滩照片，署名 **Bechology / CC BY-SA 4.0**，详见 [素材来源](evaluation/stage5/ATTRIBUTION.md)。这张照片包含东方明珠、上海中心及多栋建筑，使用原图视觉信息执行真实算法，未向 Pipeline 提供照片标题、城市、来源或机位坐标。

唯一真实请求记录：[live_requests.json](evaluation/stage5/live_requests.json)。使用 `.env` 的指定模型和百炼地址，测试进程内仅将超时设为 180 秒、重试设为 0，以控制不超过 2 次请求；未改写 `.env`。本阶段最终只发出 **1 次**，没有使用其他收费模型。重新渲染/重复同图测试没有额外请求。

结果：识别 7 个对象，5 个对象取得地图候选，几何求解输出 **5 个 AMBIGUOUS 区域**，PoseSolver 耗时约 **4.060 秒**。东方明珠、上海中心有对应名称；其余若干高楼仍被候选命名为金茂/环球，未经独立身份确认，部分低分候选存在错配风险，不能把“5 个匹配对象”说成“5 个已正确确认的真实地标”。

完整 [Pipeline JSON](evaluation/stage5/north_bund_pipeline.json)、[GeoJSON](evaluation/stage5/north_bund.geojson)、[标注图](evaluation/stage5/north_bund_annotated.png) 与 [本地交互地图 HTML](evaluation/stage5/north_bund_map.html) 均保存。页面在线模式没有读取这些文件伪装实时推理。

## 既有三个离线案例

| 照片 | 展示结果 | 未掩盖的限制 |
| --- | --- | --- |
| 北京 CBD | 中国尊/央视总部；2 个机位区域，AMBIGUOUS | 约 2.414 km² 的首区域，代表点、朝向及地图边界限制均展示，不称精确机位 |
| 广州天际线 | 广州塔/东西塔多身份组合；8 个区域，SEARCH_LIMITED | 西塔错误 Top-1、东塔备选和未细化粗候选仍保留 |
| 上海东方明珠 | 正确地标及其他身份备选；0 个区域，INSUFFICIENT_EVIDENCE | 单地标没有可确定摄影机点，地图只画实体 |

离线模式直接读取 Stage 2.1/3/4 的真实历史结果，明确标注“离线复现实验结果，非本次实时模型推理”。测试禁止 socket/HTTP/SQLite 访问仍可加载所有案例与下载载荷。地图底图离线时为空白几何背景，不伪装为已下载离线街道瓦片；在线模式可使用署名的 OSM 瓦片。

## 独立机位来源与防泄露

尝试核验 **4 张**照片，取得 **3 张明确 Camera location** 的来源坐标，其中两张既有照片、一张新增照片；广州旧图仅有猎德大桥描述。记录见 [camera_source_attempts.json](evaluation/stage5/camera_source_attempts.json) 和 [camera_truth.json](evaluation/stage5/camera_truth.json)。

| 照片 | 来源声明 | 坐标（纬度、经度） | 可用性 |
| --- | --- | --- | --- |
| 北京 CBD | [原图页面 Camera location / Location 模板](https://commons.wikimedia.org/wiki/File:Parkview_Green_and_CBD_skyline_(20210927131419).jpg) | 39.921150,116.435464 | 摄影机来源坐标，不是中国尊/央视位置 |
| 东方明珠近景 | [原图页面 Camera location / Location dec](https://commons.wikimedia.org/wiki/File:Oriental_Pearl_Tower_in_Shanghai.jpg) | 31.240411666667,121.496930 | 摄影机来源坐标，不是塔中心 |
| 北外滩 | [原图页面 Camera location / Location](https://commons.wikimedia.org/wiki/File:Oriental_Pearl_Tower_view_from_the_North_Bund,_Oct._21st,_2026.jpg) | 31.247889,121.492517 | 明确相机位置，不是图像主题地点 |
| 广州天际线 | [原图 Taken from Liede Bridge 说明](https://commons.wikimedia.org/wiki/File:GuangzhouSkyline2020.jpg) | 无精确点位 | 仅粗地点，不计算米制误差 |

上述相机位置为摄影者/来源页面自报，**不是独立测绘级真值，测量精度未知**；保留原始模板小数位不代表相应精度。没有将 EXIF GPS、OSM 地标中心、城市名或“某桥”描述替代为精确摄影机真值。

推理与评估分离：`LocalizationPipeline.run(image_path)` 不接收真值；MapMatcher/PoseSolver API 未增加真值参数，既有搜索参数、地图覆盖、身份排序未依真值调整。`validate_stage5_online.py` 只读图像和本地库；**结果保存后**，独立 `evaluate_stage5_truth.py` 才读取相机坐标。页面展示的是已生成的历史指标，不向在线推理传入来源机位。测试检查接口和调用边界。

## 真实机位评估：包含失败

完整指标：[camera_evaluation.json](evaluation/stage5/camera_evaluation.json)。最近区域距离在以来源真值为原点的局部投影中测量，代表点水平距离使用 PyProj 椭球距离；这些仅为求解后的评估。

| 案例 | 结果状态 / 区域数 | 真值包含 / 排名 | 到最近区域 | 到 Top-1 代表点 | Top-1 面积 | 参与求解对象 |
| --- | --- | --- | --- | --- | --- | --- |
| 北京 | AMBIGUOUS / 2 | 否 / 无 | 624.10 m | 2559.02 m | 2.41355 km² | 2 |
| 东方明珠 | INSUFFICIENT_EVIDENCE / 0 | 无可行输出 / 无 | 不计算 | 不计算 | 不计算 | 0（只有 1 个图像对象，未执行机位搜索） |
| 北外滩 | AMBIGUOUS / 5 | 否 / 无 | 19.08 m | 60.14 m | 0.98325 km² | 5（含未确认身份） |
| 广州 | SEARCH_LIMITED / 8 | 无精确真值 | 不计算 | 不计算 | 历史结果中保留 | 2/组合 |

**没有候选区域包含来源真值的成功样本**，没有隐藏这项失败。北京来源坐标在原地图覆盖外，故不能命中；未据此扩张覆盖后重跑。东方明珠证据不足，不生成 0 米之类虚构误差。北外滩真值在已搜索范围内，但不在最终多边形，尽管距首个代表点约 60.14 m，仍判为未包含；未用该坐标调整 FOV、主点、过滤或分数窗口。

只有 3 个相机坐标样本，且坐标精度未知、地标身份有歧义。**不能宣称系统通用定位误差约 60 米、稳定米级定位、94% 准确率或统计置信度。** 实测结果证明演示/证据链可运行，同时暴露覆盖截断、单地标不足和区域生成/模型近似局限。

## 自动化验收与复现

最终全部测试结果以最后一次 `uv run pytest` 输出为准；当前 **300 passed，0 failed，0 skipped**，含原 270 项和 Stage 5 的 30 项新测试。覆盖 Pipeline 真实接口串联、Mock HTTP、无密钥/网络/超时/限流/账户错误、缓存不重复收费、上传损坏/大小、EXIF 标注、离线无网络无数据库、地图/多区域/无虚构点、JSON/GeoJSON/PNG、初始化幂等/失败保留、页面入口和重绘、机位距离指标及真值隔离。

```powershell
uv sync --locked
uv run python -m geophotoloc.cli demo-setup
uv run streamlit run src/geophotoloc/app/main.py
uv run pytest
uv run python scripts/evaluate_stage5_truth.py
```

真实联调脚本为 `scripts/validate_stage5_online.py`，有落盘两次 HTTP 总上限和历史结果防重复；不应把它当成每次演示的默认步骤。普通在线界面只在用户点击时请求。

## 遗留问题与交付边界

功能 Demo 可启动，在线真实 Pipeline 和完全离线展示均实现，三张旧案例保持原貌，失败和不确定性可见。新环境不需要提交过的 SQLite，可直接离线演示，或用 demo-setup 有界初始化。

仍未解决：定位准确性不足、北京覆盖外真值、东西塔/普通高楼身份歧义、单地标无解、未知内参/三维可见性、采样区域近似和 OSM 不完整；没有根据验证集作弊调参。Streamlit 测试组合不能替代人工浏览器全面观察，在线瓦片还需要网络。字体在当前 Windows 环境正常，其他系统没有中文字体时图像中文字可能受字体覆盖影响，页面文本仍由浏览器显示。

因此达到**功能与可复现实验 Demo**交付条件，不等于通过准确定位产品验收或证明具有普遍定位精度。导师演示应同时展示两个成功的流程（离线复现、真实在线串联）与上述失败的定位指标。
