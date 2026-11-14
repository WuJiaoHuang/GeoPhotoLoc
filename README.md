# GeoPhotoLoc — 端到端旅拍机位粗定位 Demo

已完成 Stage 1～5：旅游照片 → 视觉地标/图像关系 → OSM 实体 Top-K → 几何候选区域 → 中文交互地图。输出粗定位候选及不确定性，不把地标中心当摄影机位，不承诺精确定位。

## 最少步骤启动

```powershell
uv sync --locked
uv run streamlit run src/geophotoloc/app/main.py
```

浏览器打开终端给出的本地地址（默认 [http://localhost:8501](http://localhost:8501)）。默认「离线案例」可直接查看北京、广州、东方明珠，**无需 API Key、SQLite 或外网**。离线地图使用随项目打包的 Leaflet/jQuery，显示本地几何与标记，不请求网络底图；页面明确标注“离线复现实验结果，非本次实时模型推理”。

在线模式额外步骤：已有 `.env` 时保留原文件，仅补充配置；没有时复制 `.env.example`，在本地填写百炼 API Key。然后初始化已定义的有限 OSM 覆盖：

```powershell
uv run python -m geophotoloc.cli demo-setup
```

该命令复用有效地区，仅顺序导入缺失的上海陆家嘴、北京 CBD、广州珠江新城/广州塔。支持 `--offline`、`--db`；服务失败会明确提示，不覆盖已有有效数据，不要求手动编辑 SQLite。页面也有初始化按钮。地图未准备好时不会先消耗视觉调用。

选择在线模式，上传 JPEG/PNG/WebP 并点击「开始定位」。只在显式点击时运行真实 Pipeline；页面重绘不请求模型，同会话同图像重复运行命中缓存时明确标注。相同图片改变搜索参数可复用视觉识别，只重算地图和几何。会话缓存有数量上限，不使用全局可变密钥。在线底图可使用 OSM 网络瓦片并显示版权；每次上传不重新调用 Overpass。

界面与算法分层：`app/main.py` 负责呈现，`pipeline.py` 注入并串联 VisionAnalyzer → MapMatcher → PoseSolver，`visualization.py` 负责标注与地图，`demo_data.py` 只读历史结果，`setup.py` 初始化有限覆盖。真实机位评估在独立脚本中读取求解结果后执行，不进入定位 Pipeline。

运行测试：`uv run pytest`。最终验收见 [STAGE5_FINAL_EVALUATION.md](docs/STAGE5_FINAL_EVALUATION.md)，导师演示流程见 [DEMO_GUIDE.md](docs/DEMO_GUIDE.md)。项目设置本地 `.cache/uv`，避免本机曾出现的跨盘 uv 缓存问题；历史环境说明保留在下文。

## 环境与执行

使用 Python 3.11、uv；运行依赖为 Pydantic、NumPy、Shapely、PyProj、OpenAI SDK、Pillow、python-dotenv、httpx；SQLite 使用 Python 标准库，测试依赖为 pytest。`uv.lock` 固定依赖版本，`.python-version` 固定 Python 3.11。几何功能、地图命令和离线测试不需要 API Key；真实视觉识别需要百炼 API Key。

通用安装与测试命令（项目根目录）：

```powershell
uv python install 3.11
uv venv --python 3.11
uv sync --locked
uv run pytest
```

本机首次安装时，默认 uv 安装/缓存路径触发 Windows 跨盘移动错误（os error 17）。实际使用以下 PowerShell 命令，将 Python 和缓存存放在项目外的 D 盘目录：

```powershell
$env:UV_PYTHON_INSTALL_DIR = 'D:\HuaweiMoveData\Users\HW\.uv-python'
$env:UV_CACHE_DIR = 'D:\HuaweiMoveData\Users\HW\.uv-cache'
uv python install 3.11
uv venv --python 3.11
uv sync
uv run pytest
```

## 项目结构

```text
GeoPhotoLoc/
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .gitignore
├── README.md
├── src/geophotoloc/
│   ├── __init__.py
│   ├── config.py
│   ├── cli.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── landmark.py
│   │   ├── observation.py
│   │   ├── localization.py
│   │   ├── vision.py
│   │   └── maps.py
│   ├── geometry/
│   │   ├── __init__.py
│   │   ├── coordinates.py
│   │   ├── bearing.py
│   │   └── constraints.py
│   ├── maps/
│   │   ├── __init__.py
│   │   ├── regions.py
│   │   ├── names.py
│   │   ├── overpass.py
│   │   ├── parsing.py
│   │   ├── store.py
│   │   ├── importing.py
│   │   └── matching.py
│   └── vision/
│       ├── __init__.py
│       ├── preprocessing.py
│       ├── client.py
│       └── relations.py
├── scripts/
│   ├── smoke_vision.py
│   ├── evaluate_real_images.py
│   ├── compare_real_images.py
│   ├── evaluate_stage3.py
│   └── compare_stage3.py
└── tests/
    ├── conftest.py
    ├── test_coordinates.py
    ├── test_bearing.py
    ├── test_constraints.py
    ├── test_models.py
    ├── test_preprocessing.py
    ├── test_vision_config.py
    ├── test_vision_models.py
    ├── test_vision_client.py
    └── test_cli.py
```

## 接口约定

- `GeoPoint` 使用 WGS84 十进制度，字段为 `latitude`、`longitude`，校验纬度 [-90,90]、经度 [-180,180]。图像坐标和可选置信度为 [0,1]，相机朝向为 [0,360)，得分必须有限，约束数为非负整数。
- `Landmark`、`ImageLandmark`、`SpatialRelation`、`CandidatePose`、`LocalizationResult` 及关系/状态枚举提供后续模块的数据契约；所有模型均可通过 `geophotoloc.models` 导入。
- `LocalCoordinateSystem(origin).to_local(point)` 返回 `(east, north)`，单位米；`to_geographic((east, north))` 为逆转换。采用以场景附近原点为中心的 AEQD 投影，场景内必须复用同一投影。PyProj 始终使用 `always_xy=True`，内部经度在前；对外使用命名字段避免混淆。
- `horizontal_distance(a, b)` 返回 WGS84 椭球面距离（米），不含高程；局部投影不保证任意两点间的全球距离精度。
- `bearing(observer, landmark)` 返回 [0,360) 度，北 0°、东 90°、顺时针递增；重合点抛出 `ValueError`。
- `signed_angle_difference(from_angle, to_angle)` 返回 [-180,180) 度；正值表示从前者顺时针转向后者，负值为逆时针，精确反向统一返回 -180°。
- `check_left_right(P, A, B, "LEFT_OF" | "RIGHT_OF", config=None)` 判断 A 相对 B 的图像顺序，返回 `ConstraintResult`。坐标均为同一局部平面的米制坐标。结果包含 `satisfied`、原因、两条视线方位角、有符号夹角、虚拟视角朝向和水平投影坐标，供后续评分使用。
- 左右判定使用两条视线短弧的平分方向作为公共局部视角，按直立相机的右/前坐标进行透视投影，单位焦距。朝向未知时地图东西不能直接解释为图像左右；这里只判断共同前向视角下的顺序相容性，无法保证未知真实视场能同时容纳两地标，也无法唯一确定拍摄位置。
- `satisfied=None` 表示退化场景，评分时不能当作满足约束：观察点与地标重合、两地标重合、视线同向或接近反向。`GeometryConfig` 默认距离容差 1e-6 米，角度容差 0.1°。非法坐标和不支持的关系抛出 `ValueError`。

## Stage 1 验证范围

测试包含坐标往返、经纬顺序及米制距离、跨日期变更线、高纬度、四个正方向、角度环绕、公共视角旋转、地标交换、地图东西与图像左右的区别、退化场景、无效输入与 Pydantic 校验。测试均断言具体数值或状态；不调用外部服务。

2026-11-14 实际执行 `uv run pytest`：Python 3.11.18、pytest 9.2.0，**76 passed，0 failed，0 skipped**。当前阶段没有尚未解决的测试问题。视觉识别、地图匹配和完整定位流程不属于本次验证范围。

## Stage 2 配置与 CLI

程序读取当前工作目录的 `.env`，进程环境中的同名变量优先；不改写 `.env` 或进程环境，不对值进行变量插值。已有 `.env` 时只补充缺少的配置，不要用模板覆盖。模板字段：

| 变量 | 默认值/含义 |
| --- | --- |
| `GEOPHOTOLOC_VLM_API_KEY` | 必填，百炼 API Key |
| `GEOPHOTOLOC_VLM_MODEL` | `qwen3.8-flash` |
| `GEOPHOTOLOC_VLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `GEOPHOTOLOC_VLM_TIMEOUT` | `60`，每次请求的超时秒数，范围 (0,600] |
| `GEOPHOTOLOC_VLM_MAX_RETRIES` | `2`，SDK 最大重试次数，范围 [0,5] |

```powershell
uv run python -m geophotoloc.cli analyze photo.jpg
uv run python -m geophotoloc.cli analyze photo.jpg --output result.json
uv run python -m geophotoloc.cli analyze photo.jpg --output -
```

前两种调用输出终端摘要，第二种另写 UTF-8 JSON；`--output -` 只在标准输出写 JSON。输入、配置、API、结构化响应或输出写入失败时向标准错误输出明确错误，退出码为 1；参数错误为 2。JSON 输出采用临时文件原子替换，API 失败保留已有结果，不允许输出覆盖输入图像或 `.env`。空识别是有效结果，返回空列表和警告。

## Stage 2 接口与边界

- `prepare_image(path, config=None)` 校验扩展名和实际格式，仅接受静态 JPEG、PNG、WebP。默认文件上限 20 MiB、像素上限 4000 万、处理后最长边 1600 像素，JPEG 编码数据上限 4 MiB（Base64 之前）。`ImageProcessingConfig` 可显式调整限制。
- 预处理校正 EXIF 方向、白底合成透明图像，必要时缩放、降低 JPEG 质量或进一步缩小图片。上传内容为重新编码的 JPEG Data URL，不保留 EXIF/GPS/其他原始元数据，不使用 GPS 辅助定位。
- `ImageMetadata` 记录文件原始尺寸、方向校正后尺寸、处理后尺寸、格式、字节数及方向是否校正。所有地标坐标均对应方向校正后的最终输入图像，使用 [0,1]、左上角原点、x 向右、y 向下。
- `ImageLandmark` 保持 Stage 1 的构造方式，新增字段都有默认值；视觉专用子类 `VisionLandmark` 严格要求唯一 ID、候选名称列表、边界框、识别依据、身份不确定性及坐标可靠性。中心必须在有效、非零面积的边界框内，禁止填入地图实体 ID。
- `VisionAnalyzer(config).analyze(path)` 使用 OpenAI SDK 调用配置中的唯一模型，不自动切换模型。请求要求可辨识地标和建筑、桥梁、河流、道路等可见要素；不确定身份时使用通用描述，不要求猜测地理位置。模型自报置信度没有经过概率校准。
- 返回 `VisionExtractionResult`：`image`、`landmarks`、`relations`、`scene_features`、`warnings`、`relation_min_gap`。严格校验 JSON、字段类型、重复属性/ID、坐标、边界框与关系引用；截断、拒绝和无效响应均报错，不通过再次调用模型自动修复。
- `extract_relations` 对每对坐标可靠的地标按中心坐标生成互逆的 `LEFT_OF/RIGHT_OF`、`ABOVE/BELOW`，每个轴差异必须大于默认 0.03（归一化单位）。中心差异过小或坐标不可靠时不生成该关系，不根据识别置信度猜测位置。结果校验同时拒绝自引用、未知 ID、重复和与坐标冲突的关系。
- 关系只描述图像空间，不代表地图东西、地理南北或真实距离。物体大小不用于推断距离；本阶段不推断遮挡，不进行 OSM 检索、机位求解或 Web 开发。实际识别及坐标可靠性依赖模型，Mock 和合成图冒烟测试均不能证明旅游照片上的识别准确率。

## Stage 2 验证

`uv run pytest` 的新增测试仅使用生成的图片、Mock OpenAI 接口与内存 HTTP transport；不读取真实 Key、不发真实网络请求。覆盖图片格式/损坏/大小/像素/压缩限制、EXIF 旋转与 GPS 元数据移除、缺失/无效配置、超时/限流及重试上限、JSON/Pydantic 校验、空间关系及 CLI 输出/失败行为，并运行全部 Stage 1 回归测试。

真实冒烟测试单独执行：

```powershell
uv run python scripts/smoke_vision.py
```

该脚本只允许指定的 `qwen3.8-flash` 与百炼地址，SDK 重试设为 0，最多发送两次请求，分别使用本地生成的合成建筑/桥梁场景及纯白图片。只验证接口连通性与结构化契约，不测试真实地标身份准确率。不会修改 `.env`，不会输出密钥或远程错误正文。正常 CLI 使用 `.env` 中的超时与重试设置。

2026-11-14 实际验收：

- `uv sync --locked` 成功；`uv run pytest`：**180 passed，0 failed，0 skipped**，包含 Stage 1 的全部 76 项回归测试。
- 使用已有 `.env` 配置，向指定百炼地址的 `qwen3.8-flash` 发送 **2 次真实请求，2 次成功，0 次失败，0 次重试**。合成场景返回 2 个身份不确定的通用地标及 4 条空间关系；纯白图片返回 0 个地标、0 条关系。
- 调用前后比对确认已有 `.env` 字节内容未改变。未调用其他模型，未上传用户照片，未验证真实旅游照片上的身份识别准确率。没有尚未解决的功能或测试阻塞。

## Stage 2.1 真实照片验证

真实照片的来源、独立参考答案、完整 JSON、标注框、API 请求账本、成功与失败案例见 [STAGE2_REAL_IMAGE_EVALUATION.md](docs/STAGE2_REAL_IMAGE_EVALUATION.md)。本次验证 3 张 CC BY-SA 4.0 真实照片，实际请求 5 次（3 成功、2 超时）；7 个固定目标中明确主名称正确 2 个，另有不确定候选、通用描述和漏检。人工对应后 8 条参考关系有 6 条正确，2 条因漏检不可核验，不作为普遍准确率。最终全部自动化测试为 **185 passed，0 failed，0 skipped**。生产识别和几何算法未修改。

## Stage 3 地图数据与实体匹配

真实 OSM 覆盖、Top-K、正确/错误身份、名称缺口、完整坐标与已知限制见 [STAGE3_EVALUATION.md](docs/STAGE3_EVALUATION.md)。三个区域获取并缓存成功，当前有效 SQLite 覆盖 **21,178** 个要素，包含 **12,154** 个完整面轮廓。本阶段不调用视觉模型，不读取 GPS，不求摄影机位。

```powershell
uv sync --locked
uv run python -m geophotoloc.cli map-import --region shanghai
uv run python -m geophotoloc.cli map-import --region beijing
uv run python -m geophotoloc.cli map-import --region guangzhou

uv run python -m geophotoloc.cli map-match result.json --region shanghai
uv run python -m geophotoloc.cli map-match result.json --output matches.json
uv run python -m geophotoloc.cli map-match result.json --output -
```

`map-import` 支持 `--offline`（只用现有缓存）、`--refresh`（主动刷新）、`--cache-dir`、`--db`、`--output`。默认 SQLite 位于 `.cache/geophotoloc/maps.sqlite3`，缓存位于 `.cache/geophotoloc/overpass`，成功响应默认保留 7 天有效期；服务异常时可回退旧缓存并标记 stale，获取时间不重置。源响应不完整/非法时不缓存。请求按有限 bbox 执行，应用不进行并发批量下载。

`map-match` 支持 `--top-k`（默认 5）、`--db`、`--output`。`--region` 可重复，用于限制已导入覆盖；省略时从所有已加载区域进行通用名称检索并推导区域假设，不需要知道照片城市或当前 GPS。JSON 输出文件和模块 CLI 标准流使用 UTF-8，失败退出非零；地图命令不读取视觉 API Key。

`maps/overpass.py` 管理受限下载与缓存，`parsing.py` 解析 node/way/relation、名称/多语言别名/原始标签/建筑轮廓与内环，`store.py` 管理 SQLite 名称、类别、OSM ID、几何范围索引与区域成员，`matching.py` 管理可解释评分、Top-K 和区域组合。SQLite 写入按 OSM 类型/ID 幂等，事务回滚不破坏已有覆盖；刷新后非当前区域成员不参与检索。

稳定 Python 接口：

```python
from geophotoloc.maps import LandmarkStore, MapMatcher, import_region
from geophotoloc.models import VisionExtractionResult

with LandmarkStore() as store:
    import_region(store, "shanghai", offline=True)
    result = MapMatcher(store).match(vision)  # vision: VisionExtractionResult
```

等价函数接口为 `match_landmarks(vision, store, regions=None, config=None)`。`MapMatchingResult.matches` 中每项对应原图像 ID，候选携带完整 `MapLandmark`、OSM ID、真实坐标、几何、精度、坐标含义、来源时间、评分组件与未校准分数。`region_hypotheses` 给出共同覆盖区域、图像 ID→实体 ID 的组合、两两最大距离及检查依据。核心类型也可从 `geophotoloc.models.maps` 导入。

算法不把通用高楼描述强行映射为建筑，也不把一个对象的多个候选名拆成其他漏检物体。标准名称、名称语言变体、分号别名和 OSM Wikipedia 标题可参与匹配；NFKC/大小写/标点归一化与模糊检索不做额外在线翻译。车站、售票点、酒店和观景点等与塔楼的明显类别冲突会被降权过滤。Wikidata 等价表示保留引用，不重复充当不同对象；同名近邻建筑表示也保守检查重复分配。

空间检查只验证共同区域、实体唯一性与默认 15 km 两两地标距离，以有界 beam 保留组合；低支持地区可保留，输出截断会警告。图像左右/上下不当作地图方位，互逆关系去重后供后续使用，不用于重复加分。评分为 `0.70×名称 + 0.15×类别 + 0.15×身份线索`，明确类别冲突另扣 0.30，默认阈值 0.68；分数不是概率，身份不自动确认。

真实样本有 6 个已检测参考目标：4 个 Top-1 正确、1 个 Top-1 错误但正确实体在 Top-K、1 个未匹配；视觉漏检的西塔不补造。正确 Top-K 身份覆盖 5/6，同时保留了错误候选和东西塔歧义，不宣称普遍准确率。当前全部测试 **245 passed，0 failed，0 skipped**，离线测试不依赖 Overpass 公网。数据署名为 © OpenStreetMap contributors / ODbL，详见 [地图数据来源](docs/evaluation/stage3/ATTRIBUTION.md)。


## Stage 4 候选摄影机位区域

当前完整回归结果：**270 passed，0 failed，0 skipped**。

新增 `localization/{projection,scoring,search,regions,solver}.py` 和 `models/pose.py`。实际使用局部米制投影、有限粗/细网格、Stage 1 方位角/左右工具、全局水平视场、软横向投影残差、完整建筑/水域过滤及连通区域提取。多个地图身份组合分别求解，不只取 Top-1；单地标返回证据不足。原有 CandidatePose/LocalizationResult 保持兼容。

```powershell
uv run python -m geophotoloc.cli localize vision.json
uv run python -m geophotoloc.cli localize vision.json --output localization.json --geojson candidate_regions.geojson
uv run python -m geophotoloc.cli localize vision.json --radius 2200 --coarse-spacing 180 --fine-spacing 60 --max-points 24000 --fov 60 75 90 110 130
uv run python scripts/evaluate_stage4.py
uv run pytest
```

`localize` 从本地数据库自动执行 Stage 3 与 Stage 4，不调用视觉 API；支持 `--db`、`--bounds SOUTH WEST NORTH EAST` 及上述预算参数。文件输出为 UTF-8；GeoJSON 支持 Polygon/MultiPolygon 和实际搜索的代表点，轴顺序为经度、纬度。保留匹配实体、相机假设、分项评分、过滤原始分数、预算及边界限制。

Python API：`PoseSolver(store, PoseSearchConfig(...)).solve(vision_result, map_matching_result)`；可从 `geophotoloc.localization` 或 `geophotoloc.models.pose` 导入模型。结果 `.model_dump_json()` 提供完整证据，`.geojson` 提供可直接展示的 FeatureCollection。

真实验证：北京 2 个区域（AMBIGUOUS）；广州 8 个区域（SEARCH_LIMITED），东西塔组合均可行且未消歧；东方明珠 0 个区域（INSUFFICIENT_EVIDENCE）。区域是粗/细单元集合的近似，不保证所有内部像素均可行；未知 FOV、地图裁剪和只有两地标的连续解会造成宽区域。网格间距、残差和启发式分数不表示米级精度或统计置信度。完整参数、实际耗时、JSON/GeoJSON 及限制见 [STAGE4_EVALUATION.md](docs/STAGE4_EVALUATION.md)。
