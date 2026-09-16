---
name: ph-worktree-exit
description: 将 PH 管理的任务 worktree 按“验证、受控提交、合并回进入时记录的源工作区、再次验证”交付，并在另行取得用户确认后清理本次 worktree。调用门禁：仅当用户当轮明确点名 ph-worktree-exit（如「用 ph-worktree-exit 收口」）并要求使用时才调用；只说“退出 worktree”“收口合回主目录”“完成这个并行任务”等普通描述、上下文提及或讨论技能名称都不触发。已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。普通提交、普通合并、仅废弃或变更意图状态、非 PH 登记的 worktree、仅询问 Git 用法时不要使用；不得自动 push、删分支、stash、force 或清理其它会话。
---

# ph-worktree-exit

把 `ph-worktree-enter` 创建的任务 worktree 安全交付回当时记录的 source worktree/source branch。调用本技能表示用户授权完成必要的验证、任务提交和合并；**清理 linked worktree 必须在合并完成后另行确认**。

## 执行前约束

1. 先读项目根 `.agents/AGENTS.md` 与 [`docs/约束规范/工程规范/Git与并行开发.md`](../../../docs/约束规范/工程规范/Git与并行开发.md)。
2. 必须在 PH session 登记的 linked worktree 内执行；不接受凭目录名猜 session，也不扫描清理所有 `.worktrees/*`。
3. 禁止 `git stash`、`reset --hard`、`--no-verify`、`worktree remove --force`、`branch -D` 和自动 push。
4. merge 目标固定为 enter 时记录的 source worktree/source branch。源分支被切换、源工作区不干净、源历史被重写或任务分支被切换时停止。
5. 所有 phase 的 dry-run 均只读，不执行验证命令、merge 或写 session；恢复到 `committed`、`merged_unverified`、`merge_verify_failed` 后同样需要 `--apply`。
6. 同一 main worktree 的 PH 写操作使用 Git 管理目录中的 `ph-delivery.lock` 串行化；锁存在时停止。它只协调 PH 进程，不阻止人或其他工具直接操作 Git；崩溃残锁必须先确认原进程已停止，再人工归档，不自动抢占。

## 提交范围

- clean：跳过提交；
- 只有 staged：只提交 index；
- 只有 tracked unstaged：执行 `git add -u` 后提交；
- staged 与 unstaged 并存，或存在任何 untracked 文件：停止，由用户决定范围；对用户问“这次提交要包括哪些”，问法见 [对用户提问](../../../docs/约束规范/工程规范/对用户提问.md) 的“把问题写成可回答的决定”。
- ignored 文件永不加入；疑似密钥文件名或异常大文件阻断；
- 需要提交时必须提供符合项目规范的消息，保留项目 hooks、签名和 Git author 配置。

## 正常流程

1. 先运行 dry-run 查看提交范围与 merge 目标：

   ```bash
   python3 .agents/skills/ph-worktree-exit/scripts/ph_worktree.py \
     exit --repo <linked-worktree> --message "<commit-message>"
   ```

2. 检查计划后加 `--apply`。脚本依次：
   - 在任务树运行 `ph-worktree-enter` 写入 session 的验证命令；这些命令冻结自进入时已审核的 source 配置，任务分支后续修改 `.agents/ph.json` 不影响本次交付；验证命令若改变 staged、tracked 或 untracked 状态则停止，由用户审查变化；
   - 按上述安全分级提交；
   - 在 source worktree 以 Git 默认 fast-forward/merge 策略合并，显式关闭 autostash；
   - 在合并结果上再次运行验证；
   - 保留任务分支和 linked worktree，提示清理仍待确认。
3. 合并后明确询问用户是否清理**本 session** 的 worktree。对用户说：“改动已经合回原来的分支。这次的隔离目录还在。要不要删掉这个目录？” 不要问内部会话名。清理前重新核对 source 分支及交付包含关系；若存在任何 ignored 文件（包括本地配置和缓存），停止并列出路径，先由用户保全不可再生成的数据、处置可再生成产物。没有通用“忽略这些文件强制删除”开关。只有用户同意且上述条件满足，才执行：

   ```bash
   python3 .agents/skills/ph-worktree-exit/scripts/ph_worktree.py \
     exit --repo <linked-worktree> --cleanup --apply
   ```

## 冲突恢复

合并冲突时保留 Git 的标准 merge 状态，不自动解决：

- 用户解决并暂存全部冲突后：

  ```bash
  python3 .agents/skills/ph-worktree-exit/scripts/ph_worktree.py \
    continue --repo <linked-worktree> --apply
  ```

- 用户决定放弃本次 merge（对用户问“你是自己改完后继续合回，还是放弃这次合回”）：

  ```bash
  python3 .agents/skills/ph-worktree-exit/scripts/ph_worktree.py \
    abort-merge --repo <linked-worktree> --apply
  ```

`abort-merge` 只撤销 source worktree 中尚未完成的 merge，任务分支提交仍保留。之后可以修复分支并重新执行 exit。

## 完成标准

- 任务变更已经通过门禁并提交；
- source branch 包含任务分支，合并结果再次通过门禁；
- 若用户拒绝清理，worktree 与 session 保留，可稍后幂等清理；
- 若用户同意清理，只移除该 session 登记的 clean linked worktree；任务分支保留，不 push、不 prune 其它 worktree。
