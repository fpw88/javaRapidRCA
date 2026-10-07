"""各规则的用户自定义内容（稀疏、可选，唯一来源，改这里即全局生效）。

key 为规则名（与 dimension_provenance.rules 里的名字一致，如「规则N」）。
- root_cause：该规则命中的根因描述（str）。命中且写了才带；带了则汇聚层直接采用原文。
- suggestion：该规则对应的首部处理建议（list[str]，按顺序作为「处理建议」最前面的若干条）。
- grade：可选，覆盖该规则命中的定级（"P0"|"P1"|"P2"）。写了才覆盖；默认用规则引擎确定性定级。
- score：可选，覆盖该规则命中的得分（0-100 整数）。写了才覆盖。
未写 root_cause / suggestion 的规则走大模型兜底（结合 rule_text 因果链发挥）。

当前为空：暂无规则产出 dimension_provenance.rules；
本文件与汇聚层「用户指定优先、大模型兜底」的机制一并保留，供后续新规则使用。
"""
RULE_CONTENT = {}
