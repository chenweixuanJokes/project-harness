---
name: ph-worktree-enter
description: 为当前 Git 项目创建 PH 管理的隔离 worktree；默认以主工作区当前分支为源，代理自行确定任务分支并记录退出上下文，不为这两个分支或实际创建再次询问。只要用户明确要求“进入 worktree”“开隔离工作区”“并行开发这个任务”或调用 ph-worktree-enter，都必须使用本技能。普通切换分支、只询问 Git 用法、仅录入或规划意图、未授权创建 worktree 时不要使用；源工作区不干净时不要擅自提交、stash 或丢弃改动。
---

# ph-worktree-enter

为一个已经获用户明确授权的并行任务创建 linked worktree。它只负责隔离和登记上下文，不启动服务、不安装依赖，也不修改业务代码。

## 执行前约束

1. 先读项目根 `.agents/AGENTS.md` 与 [`docs/约束规范/工程规范/Git与并行开发.md`](../../../docs/约束规范/工程规范/Git与并行开发.md)。
2. 创建 Git worktree 是有副作用的操作；用户没有明确要求时只说明方案，不执行。
3. 禁止 `git stash`、`--force`、`reset --hard`。源工作区有 staged、unstaged 或 untracked 内容时停止，把清单交给用户处理，并说明“主目录还有未提交改动，现在不能开隔离工作区”。
4. 首版只支持从仓库的 main worktree、attached branch 创建一级 linked worktree；裸仓库、子模块 superproject 和 linked worktree 再嵌套均阻断。

## 执行步骤

1. 源分支默认取主工作区当前所在分支（attached branch），新任务分支从该分支当前 HEAD 检出；这里的 main worktree 指主工作区，不代表 main 分支。不要自动改用 main、master、develop、远端默认分支或其他基线，也不向用户再次确认或切换源分支。代理结合当前任务语义与仓库已有命名规则自行生成简短任务分支名；未声明规则时使用 `feature/<topic>`、`fix/<topic>`、`docs/<topic>`、`refactor/<topic>` 或 `chore/<topic>`。分支名只能使用 ASCII 字母、数字、`.`、`_`、`-`、`/`，并先用 Git 检查格式、是否已存在及是否被其它 worktree 占用。默认创建新分支；若名称冲突则由代理换一个清晰且未占用的名字，不向用户二次问询。只有用户明确要求复用某个已有分支时才增加 `--existing`；该分支不存在或已被占用时停止并说明原因，不擅自改成另一条已有分支。
2. 先运行只读计划：

   ```bash
   python3 .agents/skills/ph-worktree-enter/scripts/ph_worktree.py \
     enter --repo <main-worktree> --branch <task-branch>
   ```

3. 审查计划中的来源分支、来源提交、任务分支、隔离工作区路径及验收命令。验收命令会作为仓库代码执行，必须确认它们与项目规范和用户任务一致。用户已经明确要求创建 worktree 时，该请求同时授权按无异常计划实际创建；审查通过后直接加 `--apply`，不再询问来源分支、任务分支或是否真正创建。发现工作区不干净、路径不安全、分支占用、验收命令可疑或计划与用户意图不一致时仍须停止，并如实说明阻断原因。
4. 进入脚本输出的 `taskPath` 开发。不要手工移动该目录或修改 `.worktrees/.ph/sessions/`。
5. 完成时调用 `ph-worktree-exit`，不要自行把任务分支合并到另一个临时目标。

## 路径与状态

- worktree 路径由“可读分支 slug + SHA-256 前八位”生成，不直接把分支名当文件路径。
- session 存在 `.worktrees/.ph/sessions/<session-id>.json`，不会入 Git；记录 enter 时的 main worktree、source branch/head 与 task worktree/branch。
- `.worktrees/` 未被忽略、分支已被其他 worktree 占用或目标路径已存在时必须停止。
- `.worktrees/`、`.worktrees/.ph/` 及 session 路径必须是真实仓库内目录，禁止经软链或 junction 重定向；不能把移动到其它路径的 worktree 冒充原 session。
- PH 写操作按 main worktree 加独占交付锁；dry-run 不创建锁，也不刷新 Git index。锁冲突直接停止，崩溃残锁不得自动抢占。

## 完成标准

- Git 登记中只有一个新的目标 linked worktree；
- session 与 worktree 路径、分支一一对应；
- main worktree 的分支、HEAD 和工作区内容没有被修改；
- 输出后续 `ph-worktree-exit` 的执行位置。
