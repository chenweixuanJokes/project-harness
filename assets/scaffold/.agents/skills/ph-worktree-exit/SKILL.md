---
name: ph-worktree-exit
description: 将 PH 管理的任务 worktree 按“验证、受控提交、合并回进入时记录的源工作区、再次验证”交付，并在另行取得用户确认后清理本次 worktree。调用门禁：仅当用户当轮明确点名 ph-worktree-exit（如「用 ph-worktree-exit 收口」）并要求使用时才调用；只说“退出 worktree”“收口合回主目录”“完成这个并行任务”等普通描述、上下文提及或讨论技能名称都不触发。已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。普通提交、普通合并、非 PH 登记的 worktree、仅询问 Git 用法时不要使用；不得自动 push、删分支、stash、force 或清理其它会话。
---

# ph-worktree-exit

把 `ph-worktree-enter` 创建的任务 worktree 安全交付回当时记录的 source worktree/source branch。调用本技能表示用户授权完成必要的验证与合并；任务树与源工作区的 `wip:` 提交各自按“提交范围”取得确认，其中任务树 WIP 与交付在单次 `exit --apply` 内一次完成，不拆成两次脚本调用，调用本技能本身不构成任何提交确认；**清理 linked worktree 必须在合并完成后另行确认**。

## 执行前约束

1. 先读项目根 `.agents/AGENTS.md` 与 [`project-harness/constraints/工程规范/Git规范.md`](../../project-harness/constraints/工程规范/Git规范.md)。
2. 必须在 PH session 登记的 linked worktree 内执行；不接受凭目录名猜 session，也不扫描清理所有 `.worktrees/*`。
3. 禁止 `git stash`、`reset --hard`、`--no-verify`、`worktree remove --force`、`branch -D` 和自动 push。
4. merge 目标固定为 enter 时记录的 source worktree/source branch。源分支被切换、源历史被重写或任务分支被切换时停止。合并状态先检查：session 处于 `merge_conflict` 或 `merging` 时按“冲突恢复”处理，冲突态优先于一切 WIP 流程，不问 WIP。源工作区不干净时，先在源工作区按“提交范围”完成统一 WIP 确认并用统一脚本 `wip` 子命令执行受确认的 `wip:` 提交（源工作区的这次 WIP 是合并目标自己的阻断，脚本 `exit` 不代收），再继续交付；拒绝、取消或未回答时保留改动并暂停交付；未解决的冲突条目不得为 WIP 收进提交。
5. 所有 phase 的 dry-run 均只读，不执行验证命令、merge 或写 session；恢复到 `committed`、`merged_unverified`、`merge_verify_failed` 后同样需要 `--apply`。
6. 同一 main worktree 的 PH 写操作使用 Git 管理目录中的 `ph-delivery.lock` 串行化；锁存在时停止。它只协调 PH 进程，不阻止人或其他工具直接操作 Git；崩溃残锁必须先确认原进程已停止，再人工归档，不自动抢占。

## 提交范围

统一 WIP 确认（enter 源树、本任务树、合并目标源树同一套）：先只读 dry-run，列明所在目录、当前分支、staged / unstaged / untracked 完整清单与拟用的 `wip: <说明>` 提交信息，用于说明现场与安全筛查结果；随后按 [Git与并行开发](../../project-harness/constraints/工程规范/Git规范.md) 第 3 节的固定问句模板实际调用问答工具提问，只替换目录、分支、清单、wip 说明与后续动作五个变量，两个选项字面为“是”“否”，不添加其他预设选项，也不禁用宿主自带的自由输入（如 Other）。WIP 确认问的是是否采用 `wip:` 提交解决当前这次阻断，不是对文件内容的逐项审批；没有可用问答工具或工具故障时按 [对用户提问](../../project-harness/constraints/harness规范/对用户提问规范.md) 的降级规则用可见文字提出同一模板并等待回答，不开放式问“怎么办”。

- 用户答“是”后，任务树的受确认 WIP 提交与交付由单次 `exit --apply` 内的运行时脚本一次完成，受确认提交完成后脚本只见 clean 工作区：`--wip-message "wip: <说明>"` 携带 `--expect-branch`、`--expect-head`、`--expect-staged`、`--expect-unstaged`、`--expect-untracked` 绑定 dry-run 快照（缺任一绑定——含缺失或空的 `--wip-message`——或分支、HEAD、拟提交路径/状态集合与 dry-run 不一致时，脚本在任何 `git add` 之前整单拒绝并要求重新预检，防止把提交落到别的分支或沿用旧确认提交新的改动范围；合并目标不可交付（源区处于合并中等）同样在任务树 WIP 提交之前先行阻断，任务树无任何暂存或提交副作用），不由 Agent 手写 `git add` / `git commit` 拼装；确认后到提交实际执行前，同一已展示路径的普通内容修改不需要重新确认（不逐字节比对文件内容），授权不是长期授权，该提交一经执行授权即消费。
- 独立 `wip` 子命令保留给用户直接使用，技能流程不拆成“先 wip 再 exit”两次调用；源工作区的 WIP 是合并目标自己的阻断，按执行前约束 4 单独确认并在源工作区执行一次。
- 用户答“否”、取消或未回答时保留全部改动并停止推进，不 stash、不丢弃、不改用其他提交方式、不换问法重问。
- clean：跳过提交，直接进入合并；任务树有 staged、unstaged 或 untracked 内容（包括只有 staged、只有 tracked unstaged、两者并存、含 untracked）时不再按分级默认普通提交，一律走统一 WIP 确认 + 单次 `exit --apply`；用户已在本次会话单独明确指定任务树改动的正式提交（范围与消息齐备）时可按指定执行，仅调用本技能不构成 WIP 或任何提交确认。
- 提交把 staged、unstaged、untracked 一起收进，ignored 排除，不盲目 `git add -A`；疑似密钥、异常大文件与未解决的冲突整单拒绝、不部分提交，也不得绕过安全门禁。只要安全筛查发现无法纳入的非 ignored 变动，交付在其被用户处置之前保持阻断，即使其中部分路径已另行经授权提交，也不得把任务树或源工作区当作干净继续调用 `--apply`。
- 脚本自身不向用户征求授权，脚本无能力证明真实用户确认；它的安全分级只在 `--apply` 时兜底拦截其不接受的状态，人类确认由本流程在调用 `--apply` 前完成；需要提交时必须提供符合项目规范的消息，保留项目 hooks、签名和 Git author 配置。WIP 确认只覆盖这次 `wip:` 提交，不授权普通提交、清理或任何安全检查豁免。

## 正常流程

1. 先运行只读 dry-run 查看合并目标、两侧工作区状态与任务树快照（`exit` 不再接收提交信息参数；兼容接受旧 `--message` 参数但绝不据此提交）：

   ```bash
   python3 .agents/scripts/ph_worktree.py \
     exit --repo <linked-worktree>
   ```

   dry-run 会同时报告任务树（`taskTree` / `wipPlanned` / `wipRisks`）与合并目标源工作区（`sourceDirty`，若有）。

2. 两侧都干净时直接进入第 3 步。源工作区不干净时，先按执行前约束 4 在源工作区完成统一 WIP 确认并执行源工作区的受确认 `wip:` 提交，然后重新 dry-run；任务树有改动时，按“提交范围”完成统一 WIP 确认，答“是”后单次调用一次完成任务树 WIP 提交与交付：

   ```bash
   # 任务树干净：一次 apply 直接交付
   python3 .agents/scripts/ph_worktree.py \
     exit --repo <linked-worktree> --apply

   # 任务树有改动、用户已答“是”：一次 apply 内完成 WIP 提交 + 交付
   python3 .agents/scripts/ph_worktree.py \
     exit --repo <linked-worktree> \
     --wip-message "wip: <说明>" \
     --expect-branch <dry-run 的 taskBranch> \
     --expect-head <dry-run 的 taskHead> \
     --expect-staged <dry-run 的 taskTree.staged> \
     --expect-unstaged <dry-run 的 taskTree.unstaged> \
     --expect-untracked <dry-run 的 taskTree.untracked> --apply
   ```

   脚本依次：在任务树运行 `ph-worktree-enter` 写入 session 的验证命令（这些命令冻结自进入时已审核的 source 配置，任务分支后续修改 `.agents/ph.json` 不影响本次交付；验证命令若改变 staged、tracked 或 untracked 状态则停止，由用户审查变化）→ 在 source worktree 以 Git 默认 fast-forward/merge 策略合并（显式关闭 autostash）→ 在合并结果上再次运行验证 → 保留任务分支和 linked worktree，提示清理仍待确认。
3. 合并后明确询问用户是否清理**本 session** 的 worktree。对用户说：“改动已经合回原来的分支。这次的隔离目录还在。要不要删掉这个目录？” 不要问内部会话名。清理前重新核对 source 分支及交付包含关系；若存在任何 ignored 文件（包括本地配置和缓存），停止并列出路径，先由用户保全不可再生成的数据、处置可再生成产物。没有通用“忽略这些文件强制删除”开关。只有用户同意且上述条件满足，才执行：

   ```bash
   python3 .agents/scripts/ph_worktree.py \
     exit --repo <linked-worktree> --cleanup --apply
   ```

## 冲突恢复

合并冲突时保留 Git 的标准 merge 状态，不自动解决。冲突态优先于“提交范围”的脏工作区 WIP 流程：merge 已发生冲突后，未合并条目不得转成 WIP 或任何提交收进，冲突全部解决并暂存后由 `continue` 生成的合并提交也不是 WIP 提交；清理隔离目录仍另行确认。

1. 先只读确认 merge 已真实处于冲突态：存在 `MERGE_HEAD` 与未合并条目，列明冲突清单、当前任务分支与合并目标源分支，依据 session 合并快照（`mergeSourceBranch` / `mergeSourceHead` / `mergeTaskHead`）核对 merge 身份，与现场一致才继续本节流程；快照缺失或对不上时按“中断、诊断与恢复”处理，不猜测。
2. 随后按 [Git与并行开发](../../project-harness/constraints/工程规范/Git规范.md) 第 5 节的固定冲突问句模板实际调用问答工具提问，模板只替换目录、任务分支、源分支、清单四个变量：“<目录>中，任务分支<任务分支>合入源分支<源分支>时发生冲突：<清单>。保留现场由你解决后继续，还是撤销这次合并？撤销会取消本次合并中的冲突处理，任务分支提交和隔离目录仍保留。”两个选项固定为“保留现场，我解决后继续”“撤销这次合并”，不添加 stash、丢弃、一键选 ours/theirs、Agent 代解决等其他预设选项，也不禁用宿主自带的自由输入（如 Other）。没有可用问答工具或工具故障时，按 [对用户提问](../../project-harness/constraints/harness规范/对用户提问规范.md) 的降级规则用可见文字提出同一模板并等待回答。
3. 用户选择“保留现场，我解决后继续”：停止等待用户解决冲突，不立即 continue、不轮询。用户明确说“已解决并暂存，请继续”时，先只读核验无未合并条目、核对 merge 身份（session 与任务分支未变、merge 状态吻合），再执行（既有具体授权不重问）：

   ```bash
   python3 .agents/scripts/ph_worktree.py \
     continue --repo <linked-worktree> --apply
   ```

   仅文件里没有冲突标记、或用户口头说“已解决”而没有明确要求继续，都不是继续授权，保持停止。用户明确委托 Agent 解决冲突属单独授权，不能从退出技能、WIP 或保留现场选项推导；冲突条目涉及业务取舍时仍停止交用户。
4. 用户选择“撤销这次合并”：先向用户说明冲突解决的编辑会被撤销，只读核对 merge 身份确认撤销的正是本 session 发起的这次合并，再执行（该选择本身是仅本次 abort 的明确授权）：

   ```bash
   python3 .agents/scripts/ph_worktree.py \
     abort-merge --repo <linked-worktree> --apply
   ```

   `abort-merge` 只撤销 source worktree 中尚未完成的 merge，任务分支提交仍保留；不自动重试 exit，不删除任务分支或隔离目录，之后可以修复分支并重新执行 exit。
5. 用户取消、跳过或未回答固定问句：同样停止等待，不 abort、不做 WIP、不换问法重问。新一次 merge 冲突重新走第 1-2 步提问，不复用旧授权。

## 中断、诊断与恢复

- 交付中断、验证失败或冲突撤销后修复任务分支再次交付时，先核验再交付：确认 session 处于 `committed` 或 `merge_verify_failed` 且任务分支在其后出现新提交，审查 `redeliver` 的只读 dry-run（session、任务分支与验证命令核验通过才交付），再显式加 `--apply`；不复用上次失败的证据，也不跳过核验：

  ```bash
  python3 .agents/scripts/ph_worktree.py \
    redeliver --repo <linked-worktree> --apply
  ```

- 对 session、锁与 merge 状态存疑时，先用 `doctor` 只读诊断；无 `--apply`，不做任何修复：

  ```bash
  python3 .agents/scripts/ph_worktree.py \
    doctor --repo <main-worktree>
  ```

- 确需恢复登记时由 `recover` 显式执行，恢复目标与操作由用户显式指定，不猜测、不自动覆盖现有 session：

  ```bash
  python3 .agents/scripts/ph_worktree.py \
    recover --repo <main-worktree> --session <session JSON 路径> --action archive --apply
  ```

  `archive` 仅适用于隔离目录已清理（cleaned）或目录不存在且未登记的残留记录；`adopt` 仅适用于 creating 记录且现存登记 worktree、分支与 initialTaskHead 吻合。两个动作之外的状态不被 recover 覆盖，如实交用户处置。
- 现场与 session 登记不符（如 merge 身份对不上的陌生 merge）或旧版本创建的 session 缺少新增证据字段时，脚本保守阻断：不猜测补齐、不把陌生 merge 当作本 session 的交付继续；recover 不能恢复所有旧 merge，先 `doctor` 只读诊断，按其结果以显式 `recover` 恢复或交用户决定。session 结构向后兼容，1.1.14 新增字段非必填，现有 session 不被迁移覆写。

## 完成标准

- 任务变更已经通过门禁并提交（受确认的任务树 WIP 在单次 `exit --apply` 内完成，或用户单独指定的正式提交）；
- source branch 包含任务分支，合并结果再次通过门禁；
- 若用户拒绝清理，worktree 与 session 保留，可稍后幂等清理；
- 若用户同意清理，只移除该 session 登记的 clean linked worktree；任务分支保留，不 push、不 prune 其它 worktree。
