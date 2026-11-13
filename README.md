# GeoPhotoLoc — Stage 1

旅游照片拍摄机位粗定位 Demo 的基础工程。当前提供数据模型、地理坐标转换、方位角及二维左右约束接口；尚未接入视觉 API、地图检索或候选机位搜索。

## 环境与执行

使用 Python 3.11、uv；运行依赖为 Pydantic、NumPy、Shapely、PyProj，测试依赖为 pytest。`uv.lock` 固定依赖版本，`.python-version` 固定 Python 3.11。Stage 1 不需要环境变量或密钥，`.env.example` 仅为占位文件。

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
│   ├── models/
│   │   ├── __init__.py
│   │   ├── landmark.py
│   │   ├── observation.py
│   │   └── localization.py
│   └── geometry/
│       ├── __init__.py
│       ├── coordinates.py
│       ├── bearing.py
│       └── constraints.py
└── tests/
    ├── test_coordinates.py
    ├── test_bearing.py
    ├── test_constraints.py
    └── test_models.py
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

## 验证范围

测试包含坐标往返、经纬顺序及米制距离、跨日期变更线、高纬度、四个正方向、角度环绕、公共视角旋转、地标交换、地图东西与图像左右的区别、退化场景、无效输入与 Pydantic 校验。测试均断言具体数值或状态；不调用外部服务。

2026-11-14 实际执行 `uv run pytest`：Python 3.11.18、pytest 9.2.0，**76 passed，0 failed，0 skipped**。当前阶段没有尚未解决的测试问题。视觉识别、地图匹配和完整定位流程不属于本次验证范围。
