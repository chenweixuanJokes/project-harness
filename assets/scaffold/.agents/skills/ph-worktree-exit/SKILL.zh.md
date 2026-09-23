# ph-worktree-exit 中文对照

仅当用户明确点名 ph-worktree-exit 并要求使用时执行；普通描述和名称提及不触发。明确启动后的继续不要求重复点名，不自动调用其他技能。调用授权本次合并，不代表确认提交、推送、删分支或清理工作区。

# 退出隔离任务工作区

读取 `.agents/AGENTS.md`、[Git规范](../../project-harness/constraints/工程规范/Git规范.md)和[提问规范](../../project-harness/constraints/harness规范/对用户提问规范.md)，在已登记 linked worktree 使用 `.agents/scripts/ph_worktree.py`。不凭目录名猜会话，不清理全部工作区。

## 交付边界

目标固定为进入时记录的源工作区/分支。源分支切换、历史重写、任务分支切换或身份不明都阻断。不自动 push、stash、reset --hard、--no-verify、强制删除或 branch -D。清理后默认保留任务分支。

多个独立任务树可并行开发；PH Git 写入及同源合并通过交付锁串行。锁只协调 PH，不阻止外部 Git；未确认原进程停止不抢锁。

SDD 分配要检查功能/任务/资源及未完成兄弟任务。子任务合入不是整需求验收或归档。代码、文档、用例及受跟踪功能材料一起交付；清理前证据进入持久交付路径。合并前快照保留其历史含义。不调用 ph-archive，不暗标需求已验收。

## 预检与提交

只读预检：

```text
python3 .agents/scripts/ph_worktree.py exit --repo <linked-worktree>
```

所有状态的预检都只读，不执行验证命令、合并、写会话或刷新索引。审查 taskTree、sourceDirty、wipRisks、目标和功能分配。

已有合并/冲突优先于 WIP，按下节恢复，不把冲突条目提交进 WIP。否则源树脏时，在源树按 Git 规范统一问句取得同意后，通过独立 wip 子命令解决；这是源树独立阻断，不属于任务树 WIP，然后重新 exit 预检。

任务树脏时展示分支、HEAD、全部 staged/unstaged/untracked 和拟用 `wip: <说明>`，实际用宿主工具问 Git 规范固定 WIP 问句，保留是/否及自由输入。同意只覆盖一次 WIP，不是任意提交。点名退出本身不确认提交。用户另行明确指定正式提交可按其执行，但不能用正式提交替代被拒绝的 WIP。

同意后单次 exit apply 带 `--wip-message`、`--expect-branch`、`--expect-head`、`--expect-staged`、`--expect-unstaged`、`--expect-untracked`，来自已审快照。不拆 WIP 与退出、不手工 add/commit。分支/HEAD/路径状态变化须重查重问；同路径普通内容变化不逐字节重问。授权由该次提交消费。

秘密、超大变动、冲突、不可交付源在提交前整单阻断，不部分提交、不盲目 git add -A。ignored 排除。拒绝、取消、未回答保留全部并停止，不改问法。脚本不能证明真实授权。

两侧干净时：

```text
python3 .agents/scripts/ph_worktree.py exit --repo <linked-worktree> --apply
```

脚本在任务树执行进入时冻结的验证命令，关闭 autostash，以正常快进/合并策略集成，再验证源树。任务分支后改配置不能暗换冻结命令。验证改变 Git 可见状态应停下审查。任务树通过不等于合并后通过。

## 冲突与中断恢复

1. 核实 MERGE_HEAD、未合并路径和 mergeSourceBranch/mergeSourceHead/mergeTaskHead，身份缺失或不符阻断，不接管陌生合并。
2. 用宿主工具提出项目固定冲突问句：保留现场由用户解决后继续，或撤销本次合并。不自动选 ours/theirs、force 或代理代解决。代理解决冲突须另有明确授权，业务取舍仍交用户。
3. 保留现场就停止等待，不轮询。用户明确要求解决并暂存后继续，才核实无冲突且身份一致，执行 `continue --repo <linked-worktree> --apply`。这是合并提交，不是 WIP。
4. 明确撤销只授权本次 `abort-merge --repo <linked-worktree> --apply`；说明冲突处理编辑会撤销，但任务分支与目录保留，先核身份。不自动再次合并。
5. 未答/取消不 abort、不 WIP、不换提问渠道。

只读诊断用 `doctor --repo <primary-worktree>`。committed/merge_verify_failed 后任务分支修正，先看 redeliver 预检再 `redeliver --repo <linked-worktree> --apply`，不复用失败证据。登记恢复仅在工具能证明状态且明确授权范围内使用 `recover --repo <primary-worktree> --session <path> --action archive|adopt --apply`。旧会话缺合并证据保持阻断，不编字段。

## 清理与完成

合并和合并后验证成功后，按项目清理问句另问是否移除本次目录。拒绝则保留会话和目录，后续可继续清理。删除前再核源身份、包含关系、任务树干净、功能/证据材料已完整交付及 ignored 文件。检查 `featureEvidenceIssues`：证据缺失、变化或尚未保全会阻断清理，不阻断已经独立授权的合并。源树中已跟踪且内容匹配的功能内证据，或已跟踪并核对校验和的归档副本，可证明保全；外部路径暂时存在不够。不强制先归档再退出。ignored 数据先由用户保全或处置，无通用强制忽略开关。

仅明确同意且保护条件满足时：

```text
python3 .agents/scripts/ph_worktree.py exit --repo <linked-worktree> --cleanup --apply
```

分别报告源分支、真实合并后验证、未完成兄弟任务、归档与清理状态。会话记录归档不等于需求归档。Git 成功不能推定用户验收或功能收敛。
