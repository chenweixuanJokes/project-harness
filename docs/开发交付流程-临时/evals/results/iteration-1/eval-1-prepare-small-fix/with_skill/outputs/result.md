# prepare-small-fix

执行类型：主 Agent 准备走读，无产品写入。执行者：当前主 Agent（作者自评，非独立模型）。

A1 空输入仅输出列头；A2 非空中文格式不变；A3 can_export=False 拒绝。T1 删除无用途首项读取并新增空输入测试。实现入口 exporter.py:10，验证 python3 -m unittest -v。只准备时不实施；后续真实修复在另行授权的隔离演练内完成。
