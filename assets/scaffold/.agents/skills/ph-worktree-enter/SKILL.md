---
name: ph-worktree-enter
description: 为当前 Git 项目创建 PH 管理的隔离 worktree；默认以主工作区当前分支为源，代理自行确定任务分支并记录退出上下文，不为这两个分支或实际创建再次询问。调用门禁：仅当用户当轮明确点名 ph-worktree-enter（如「用 ph-worktree-enter 开隔离工作区」）并要求使用时才调用；只说“开个 worktree”“并行开发这个任务”等普通描述、上下文提及或讨论技能名称都不触发。已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。普通切换分支、只询问 Git 用法、仅录入或规划意图、未授权创建 worktree 时不要使用；源工作区不干净时不要擅自提交、stash 或丢弃改动。
---

# ph-worktree-enter

为一个已经获用户明确授权的并行任务创建 linked worktree。它只负责隔离和登记上下文，不启动服务、不安装依赖，也不修改业务代码。

## 执行前约束

1. 先读项目根 `.agents/AGENTS.md` 与 [`project-harness/constraints/工程规范/Git规范.md`](../../project-harness/constraints/工程规范/Git规范.md)。
2. 创建 Git worktree 是有副作用的操作；用户没有明确要求时只说明方案，不执行。
3. 禁止 `git stash`、`--force`、`reset --hard`。合并状态先检查：主工作区存在 `MERGE_HEAD` 或未合并条目（合并进行中或冲突未决）时不问 WIP、不创建隔离工作区，直接告诉用户当前处于合并状态，等合并完成之后才能做 WIP 与创建；由用户自行完成合并后重新调用本技能，不代为转交其他技能、不自动弹冲突处理问句。脚本对这类状态直接报错时同样按此处理，不把报错当作重试入口。源工作区有 staged、unstaged 或 untracked 内容时停止创建，执行统一 WIP 确认：dry-run 会只读报告 `sourceDirty` 清单与安全筛查结果；随后按 [`Git与并行开发`](../../project-harness/constraints/工程规范/Git规范.md) 第 3 节的固定问句模板实际调用问答工具提问，只替换目录、分支、清单、wip 说明与后续动作（提交后创建本隔离工作区）五个变量，两个选项字面为“是”“否”。WIP 确认问的是是否采用 `wip:` 提交解决当前这次阻断，不是对文件内容的逐项审批；没有可用问答工具或工具故障时按 [对用户提问](../../project-harness/constraints/harness规范/对用户提问规范.md) 的降级规则用可见文字提出同一模板并等待回答，不开放式问“怎么办”。用户答“是”后才执行：单次 `enter --apply --wip-message "wip: <说明>"` 连同 `--expect-source-branch`、`--expect-source-head`、`--expect-staged`、`--expect-unstaged`、`--expect-untracked`（取自 dry-run 快照）一次完成受确认的 WIP 提交与隔离工作区创建，不拆成两次脚本调用，也不由 Agent 手写 `git add` / `git commit`；提交把 staged、unstaged、untracked 一起收进，ignored 排除，不盲目 `git add -A`，疑似密钥、异常大文件与未解决的冲突整单拒绝、不部分提交；只要安全筛查发现无法纳入的非 ignored 变动，创建在其被用户处置之前保持阻断，即使其中部分路径已另行经授权提交，也不得把该工作区当作干净继续操作。独立 `wip` 子命令仅供用户直接使用。答“否”、取消或未回答时保留全部改动并停止创建，不 stash、不丢弃、不自动授权、不换问法重问。确认后到提交实际执行前：分支、HEAD 或拟提交路径/状态集合发生变化（新增、删除或状态转移）时脚本阻断并重新预检、重新确认，不沿用已消费的确认覆盖新变更；同一已展示路径的普通内容修改不需要重新确认（不逐字节比对文件内容）。授权不是长期授权：该提交一经执行授权即消费，该阻断场景结束后再次被未提交改动阻断（包括后续步骤、下一次交付或该工作区再次变脏），按当时的现场重新确认。WIP 确认只覆盖这次 `wip:` 提交，不授权普通提交、清理或任何安全检查豁免。确认提交后源工作区已干净，直接继续创建。
4. 首版只支持从仓库的 main worktree、attached branch 创建一级 linked worktree；裸仓库、子模块 superproject 和 linked worktree 再嵌套均阻断。

## 执行步骤

1. 源分支默认取主工作区当前所在分支（attached branch），新任务分支从该分支当前 HEAD 检出；这里的 main worktree 指主工作区，不代表 main 分支。不要自动改用 main、master、develop、远端默认分支或其他基线，也不向用户再次确认或切换源分支。代理结合当前任务语义与仓库已有命名规则自行生成简短任务分支名；未声明规则时使用 `feature/<topic>`、`fix/<topic>`、`docs/<topic>`、`refactor/<topic>` 或 `chore/<topic>`。分支名只能使用 ASCII 字母、数字、`.`、`_`、`-`、`/`，并先用 Git 检查格式、是否已存在及是否被其它 worktree 占用。默认创建新分支；若名称冲突则由代理换一个清晰且未占用的名字，不向用户二次问询。只有用户明确要求复用某个已有分支时才增加 `--existing`；该分支不存在或已被占用时停止并说明原因，不擅自改成另一条已有分支。
2. 先运行只读计划（脏工作区不报错，计划只读列出 `sourceDirty` 与筛查结果）：

   ```bash
   python3 .agents/scripts/ph_worktree.py \
     enter --repo <main-worktree> --branch <task-branch>
   ```

3. 审查计划中的来源分支（`sourceBranch`）、来源提交（`sourceHead`）、任务分支、隔离工作区路径及验收命令。验收命令会作为仓库代码执行，必须确认它们与项目规范和用户任务一致。用户已经明确要求创建 worktree 时，该请求同时授权按无异常计划实际创建：工作区干净时，`--apply` 必须带上 `--expect-source-branch <计划的 sourceBranch>` 与 `--expect-source-head <计划的 sourceHead>`（两者缺一脚本直接拒绝；漂移阻断并重新 dry-run）；工作区脏时，先完成执行前约束 3 的统一 WIP 确认，答“是”后单次调用一次完成 WIP 提交与创建：

   ```bash
   # 干净源工作区：一次 apply 直接创建
   python3 .agents/scripts/ph_worktree.py \
     enter --repo <main-worktree> --branch <task-branch> \
     --expect-source-branch <计划的 sourceBranch> \
     --expect-source-head <计划的 sourceHead> --apply

   # 脏源工作区、用户已答“是”：一次 apply 内完成 WIP 提交 + 创建
   python3 .agents/scripts/ph_worktree.py \
     enter --repo <main-worktree> --branch <task-branch> \
     --expect-source-branch <计划的 sourceBranch> \
     --expect-source-head <计划的 sourceHead> \
     --wip-message "wip: <说明>" \
     --expect-staged <计划的 sourceDirty.staged> \
     --expect-unstaged <计划的 sourceDirty.unstaged> \
     --expect-untracked <计划的 sourceDirty.untracked> --apply
   ```

   发现路径不安全、分支占用、验收命令可疑或计划与用户意图不一致时仍须停止，并如实说明阻断原因。
4. 进入脚本输出的 `taskPath` 开发。不要手工移动该目录或修改 `.worktrees/.ph/sessions/`。
5. 任务完成后的交付由用户当轮明确点名 `ph-worktree-exit` 并要求退出时执行；在那之前不要自行把任务分支合并到另一个临时目标。

## 路径与状态

- worktree 路径由“可读分支 slug + SHA-256 前八位”生成，不直接把分支名当文件路径。
- session 存在 `.worktrees/.ph/sessions/<session-id>.json`，不会入 Git；记录 enter 时的 main worktree、source branch/head 与 task worktree/branch。session 结构向后兼容：1.1.14 起新增字段非必填，旧 session 只读兼容，不被迁移覆写；退出阶段的合并快照（`mergeSourceBranch` / `mergeSourceHead` / `mergeTaskHead`）由 `ph-worktree-exit` 写入并用于核对 merge 身份。
- `.worktrees/` 未被忽略、分支已被其他 worktree 占用或目标路径已存在时必须停止。
- `.worktrees/`、`.worktrees/.ph/` 及 session 路径必须是真实仓库内目录，禁止经软链或 junction 重定向；不能把移动到其它路径的 worktree 冒充原 session。
- PH 写操作按 main worktree 加独占交付锁；dry-run 不创建锁，也不刷新 Git index。锁冲突直接停止，崩溃残锁不得自动抢占。

## 完成标准

- Git 登记中只有一个新的目标 linked worktree；
- session 与 worktree 路径、分支一一对应；
- main worktree 的分支没有被切换；除用户已确认的 `wip:` 提交外，HEAD 和工作区内容没有被其他操作修改；
- 输出后续 `ph-worktree-exit` 的执行位置。
