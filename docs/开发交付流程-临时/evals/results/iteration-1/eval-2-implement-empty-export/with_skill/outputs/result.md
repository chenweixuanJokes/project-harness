# implement-empty-export

执行类型：真实隔离命令演练。执行者：当前主 Agent（作者自评，非独立模型）。

既有2项测试通过；空输入先复现 IndexError；最小修复后3项测试通过。未加依赖或公开参数，没有PH或worktree，用户原有文件哈希不变。
