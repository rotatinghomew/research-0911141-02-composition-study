# 数据口径

samples 是独立配制样本，group 为配方，batch 为检测批次，dilution 是检测前稀释倍数。readings 的 value 是稀释后读数，乘 dilution 才是原液浓度；state=measured、below_limit、not_added、not_measured 分别表示定量、低于检出限、确定未加入、未检测。total 可为 null，代表没有独立总浓度证据。成分清单之外的余量不能视为零。component_groups 仅为业务可比较的成分集合，不指定统计坐标或算法。

## 数据版本

`fixtures/data.json` 是可直接导入的一份完整材料，`product.json` 保存页面默认范围。导入必须提交完整对象，不把省略字段解释为删除补丁；以规范化 JSON 的 SHA-256 标识内容，同内容多次导入复用版本。原始记录只追加版本，保存的分析材料始终指向原来版本。

页面中的范围影响当前描述，不回写源数据。`null`、缺记录与实际零不能合并；数据格式问题应在导入时明确报错，而不是生成看似成功的空结果。涉及单位、时间或关系的解释以本文件为准，统计方法和业务决策没有预设结果。

## 目录

`composition_study/domain.py` 提供现行领域校验和描述，`validation.py` 处理基础引用与数值校验，`service.py` 连接领域操作和材料存档，`storage.py` 负责内容寻址数据与历史记录，`server.py` 提供本地接口。`web/app.js` 使用接口构建交互页面，不自行推导独立口径。
