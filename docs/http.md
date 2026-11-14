# 本地接口

服务只用于本地教研复核，不连接真实人员目录或外部数据源。数据以 UTF-8 JSON 传输；未找到对象返回 404，无效业务输入返回 400，正文超出 8MB 返回 413。

- `GET /health` 返回就绪状态。
- `GET /api/context` 返回产品配置、默认版本、已导入版本与保存记录目录（含比较记录目录）。
- `GET /api/data?revision=版本` 返回该版本完整原始数据；省略版本使用演示材料。
- `POST /api/datasets` 接收 `label` 和完整 `data`，返回新建或复用的 `revision`。
- `POST /api/explore` 接收可选 `revision` 和 `selection`，返回数据指纹、实际选择和领域描述。
- `POST /api/notebooks` 使用相同选择参数和 `title`，服务端重新计算后保存，不能由客户端伪造结果。
- `GET /api/notebooks` 返回材料目录，`GET /api/notebooks/编号` 返回冻结描述、选择条件和所用数据。
- `GET /api/compare/options?revision=版本` 返回该版本可用于比较的配方、成分、成分组与未检出处理假设。
- `POST /api/compare` 接收可选 `revision` 和 `scheme`（`group_a`、`group_b`、`components`、`below_limit`），返回规范化方案、数据指纹和比较视图，不保存。
- `POST /api/comparisons` 使用相同参数和 `title`，服务端重新计算后把方案与结果一起冻结保存。
- `GET /api/comparisons` 返回比较记录目录，`GET /api/comparisons/编号` 返回冻结的方案与结果；用保存的 `scheme` 重新 `POST /api/compare` 可在新数据版本上重做，不回写旧记录。

领域描述包含 `summary`、`rows`、`series` 和 `notes`，学习进展另含作答历史。比较视图包含 `level`（整体浓度）、`contrasts`（相对构成对数比对比）、`balances`（成分组平衡）、`structural`（结构差异）、`sensitivity`（处理假设敏感性）、`limitations`（可比性限制）和 `notes`。这里记录的是已有浏览交互，不限制新分析功能的内部结构。增添业务能力时需保持现有原始记录和保存材料可读取。
