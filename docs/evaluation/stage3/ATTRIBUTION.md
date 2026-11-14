# Stage 3 地图证据来源

本目录 OSM 实体名称、标签、坐标、轮廓及数据库摘录来自 **© OpenStreetMap contributors**，使用 [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/)。来源与许可：[OpenStreetMap copyright](https://www.openstreetmap.org/copyright)。数据库内容及摘录受其许可约束，不改变本项目代码的许可。

数据由 `https://overpass-api.de/api/interpreter` 于 2026-11-14（Asia/Shanghai）按有限 bbox 查询获取。精确查询、UTC 获取时间和 OSM 基准时间见 [imports.json](imports.json)。大规模原始响应和本地 SQLite 数据库仅保存在被 Git 忽略的 `.cache/geophotoloc/`，本目录只保留少量结果和身份核验摘录。

结果中的坐标是实际 OSM node 坐标或从真实 way/relation 几何计算的代表点；坐标含义见各实体 `coordinate_meaning`，不表示入口或拍摄点。OSM 网页可按 `https://www.openstreetmap.org/{node|way|relation}/{id}` 查看原始实体。

`reference_entities.json` 是单独离线核验用的 7 个真实 OSM 实体摘录，不用于向匹配器提供预设答案；生产代码不读取本目录。照片及视觉识别结果沿用 Stage 2.1 的独立来源与许可。
