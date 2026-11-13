# GeoPhotoLoc — Stage 2

旅游照片拍摄机位粗定位 Demo。已完成基础工程与几何工具（Stage 1）、图像语义识别与图像空间关系提取（Stage 2）。尚未开发地图检索、实体匹配和候选机位求解，Stage 1 几何算法保持不变。

## 环境与执行

使用 Python 3.11、uv；运行依赖为 Pydantic、NumPy、Shapely、PyProj、OpenAI SDK、Pillow、python-dotenv，测试依赖为 pytest。`uv.lock` 固定依赖版本，`.python-version` 固定 Python 3.11。几何功能与 Mock 测试不需要 API Key；真实视觉识别需要配置百炼 API Key。

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
│   │   └── vision.py
│   ├── geometry/
│   │   ├── __init__.py
│   │   ├── coordinates.py
│   │   ├── bearing.py
│   │   └── constraints.py
│   └── vision/
│       ├── __init__.py
│       ├── preprocessing.py
│       ├── client.py
│       └── relations.py
├── scripts/
│   └── smoke_vision.py
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
