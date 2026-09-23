# ph-worktree-enter 中文对照

仅当用户明确点名 ph-worktree-enter 并要求使用时执行；普通描述和名称提及不触发。明确启动后的继续不要求重复点名，不自动调用其他技能。创建不授权提交、实现、合并、退出或清理。

# 进入隔离任务工作区

读取 `.agents/AGENTS.md`、[Git规范](../../project-harness/constraints/工程规范/Git规范.md)和[提问规范](../../project-harness/constraints/harness规范/对用户提问规范.md)。使用共享 `.agents/scripts/ph_worktree.py`，不手写 Git 编排替代。

## 范围与分配

只创建登记明确要求的环境，不装依赖、不启服务、不改代码。源是主工作区当前 attached 分支，不必是 main，不切到 main/master/develop 或其他基线。运行时只支持从主工作区创建一级 linked worktree，不支持的裸仓/子模块/嵌套状态停止。

按项目规则生成简短未占用分支名，只用 ASCII 字母、数字、连字符、下划线和斜杠。正常命名和已请求创建不重复确认。仅用户指定复用现有分支时用 `--existing`；不存在或被占用则停止，不替换成其他已有分支。

SDD 工作明确功能仓内相对路径、功能 ID、任务 ID，识别独占端口、数据库和其他资源。查看 `enter --help` 中 `--feature-path`、`--feature-id`、可重复的 `--task-id`、`--resource key=value`。多个独立树可并存，但共享文件和外部资源要分配归属或串行；worktree 不隔离服务。

## 预检与源保护

运行：

```text
python3 .agents/scripts/ph_worktree.py enter --repo <primary-worktree> --branch <task-branch>
```

预检和 apply 携带同一 SDD 分配。审查 sourceBranch/sourceHead、taskPath、验证命令、sourceDirty、wipRisks、任务/资源冲突。命令将执行仓库代码，需检查范围与安全性。

合并进行中或未合并条目在 WIP 提问前阻断创建，不借机解决冲突、调用退出或重试。不 stash、force、reset --hard 或搬开冲突内容强行创建。

源干净时，明确创建请求授权执行无异常计划，携带两项源绑定：

```text
python3 .agents/scripts/ph_worktree.py enter --repo <primary-worktree> --branch <task-branch> --expect-source-branch <sourceBranch> --expect-source-head <sourceHead> --apply
```

存在 staged/unstaged/untracked 时，先通过宿主问答工具使用 Git 规范的统一 WIP 固定问句，展示目录、分支、三组完整清单及拟用 `wip: <说明>`。选项按规范固定是/否，保留宿主自由输入。拒绝、取消、未回答则保留改动停止，不换问法获取同意。

明确同意后单次 enter apply 完成 WIP 与创建，带上预检的 `--wip-message`、`--expect-source-branch`、`--expect-source-head`、`--expect-staged`、`--expect-unstaged`、`--expect-untracked`。不拆成独立 add/commit/enter，独立 wip 命令不替代本流程。

分支、HEAD、路径/状态集合变化使授权快照失效，须重查重问；同一已展示路径集合内普通内容变化不逐字节重问。授权由一次提交消费，后续脏树阻断另行确认。疑似秘密、超大文件或未解决冲突整单阻断，不部分提交。ignored 排除，不盲目 git add -A。脚本只能绑定现场，不能证明真实同意。

## 登记与交接

运行时检查 `.worktrees/` 已忽略、路径安全、分支占用及 Git 登记，生成可读 slug/hash 路径，在 `.worktrees/.ph/sessions/` 记录来源和分配。不手改目录名或 session JSON。真实目录及包含检查拒绝软链/junction 重定向。

PH 写操作按主工作区共享锁；预检不建锁、不刷新索引。锁冲突停止，不确认原进程退出就不抢残锁。

核对新登记目录、分支、分配与计划一致，源分支未切换。报告 taskPath、范围和资源限制，准备好的任务建议 ph-implement，并说明之后独立调用 ph-worktree-exit，不自动调用。旧会话升级时保留，不能编造缺失恢复证据。
