# ph-merge-update 中文对照

仅当用户明确点名 ph-merge-update 并要求使用时执行；普通描述和提及不触发。ph-init 可在已请求升级中读取本文作为内部步骤。明确启动后的继续不要求重复点名，不自动调用其他技能。

# 将发行版合并到已安装项目

使用准备好的发行根脚本与迁移文档，即使旧项目没有本技能。ph-init 在已请求升级中也直接读取本流程。不用 init --apply、adopt、目标 git pull 或模板强盖代替升级。

## 来源与预检

官方源 `https://github.com/chenweixuanJokes/project-harness.git`；1.x 历史 `https://github.com/chenweixuanJokes/ph-init.git` 身份保持兼容。仓外准备固定稳定 tag/commit 并读根 SKILL.md，不用 main 或未准备本地树冒充最新。

```text
python3 <ph-init-root>/scripts/ph_release.py prepare --version latest --repo <target>
python3 <release-root>/scripts/ph_merge_update.py inspect --repo <target>
```

同次操作复用已准备根。来源校验失败或缺迁移链阻断写入。旧入口可能因 schema_version 或 Spec Kit 元数据拒绝新包，按 ph-init 指引从正式目标标签在仓外新目录使用新版入口。不修改旧验证器绕过，不假称未发布标签可下载。

读取目标约束与提问规则。盘点清单、真实技能目录、canonical/适配入口、文档、运行时、未提交改动和 worktree。历史 1.1.0 有不同布局，不能只凭版本串判断。新项目走安装，同版 check/sync 离线，拒绝降级。

## 替换前保全

盘点全部受影响原件，记录归属、类型、路径、摘要。在替换、移动、退役前，按迁移声明的归档/备份保全并生成可恢复清单。不跟随链接到仓外，未知第三方内容不动。

保全和迁移分别验收：仍有效的项目规则、事实、参数、附件、需求、问答、测试证据、记忆和技能定制需要活动落点与证据；只留历史须说明原因。有备份不等于有效定制已承接。

语义合并必须读正文，保留事实和有效规则，只改迁移要求，修活动引用与索引，保留历史原话和代码块。不借升级重新全网调查或生成全部项目文档。

## 状态与执行

读取 migrations/index.json 及真实旧状态到目标的全部迁移。后续终态可替代中间安装步骤，但不能漏迁移义务。已发布迁移文档不改写。

用 `.agents/updates/<target-version>/state.json` 和 report.md。保留 from_version/to_version/source repository/tag/commit，链上每项登记。总状态 in_progress/complete；项状态 pending/applied/not_applicable/blocked，evidence 为真实字符串证据。按磁盘恢复，不只看版本或旧报告；不把已变化原件重建成基准，不重复插入迁移正文。

说明实际写入范围，通过宿主问答解决必要冲突。授权后无歧义操作不反复问。项目规则冲突保持阻断，不能为方便降低门禁。

## 自研 SDD 过渡

读取目标包的 1.2.2-to-1.2.3 迁移说明，遵守准确命令顺序与保护。六项分别为：

| 项 | 完成结果 |
| --- | --- |
| sdd-skill-replacement | 安装新技能，安全退役旧受管入口及适配副本，处理同名替换和定制 |
| sdd-runtime-takeover | 自有运行时和治理能力接管，不丢原则与导航 |
| bilingual-skills | 本次新增/修改技能有英文 SKILL.md 和中文 SKILL.zh.md，对照不注册为技能 |
| docs-tests-consolidation | 合并文档、测试、用例沉淀规则，保留项目事实 |
| worktree-session-continuity | 安装新运行时，既有会话、分配、历史保留 |
| artifact-compat | 旧需求/计划/任务/证据可读可追溯，不编造新通过状态 |

新开发技能为 ph-require、ph-clarify、ph-design、ph-design-review、ph-tasks、ph-verify-plan、ph-small-change、ph-implement、ph-verify、ph-archive。ph-clarify、ph-tasks、ph-implement 替换旧同名语义；ph-analyze、ph-checklist、ph-converge、ph-constitution、ph-plan、ph-specify、ph-taskstoissues 不保留为另一套活动流程。

先预检 `ph_merge_update.py migrate-skills --repo <target>`，仅授权且无冲突时 --apply。归属以内容基准与历史证据证明，不凭名称或来源标记。整个目录含资源保全。修改正文、未知附属文件、第三方同名需记录保全/迁移决定，不伪造原版字节绕过阻断。canonical 退役前审查适配副本，避免丢归属证明。确认厂商入口没有旧受管孤儿。

migrate-skills 报告未知附属文件时先审查含义。`--extras-decisions <JSON>` 接收每个技能的 `decision: archive` 及 `note`，只能用于确属历史或有效内容已承接到核验过的活动落点的文件；说明与报告记录处置证据。此参数不是丢弃定制的通用许可。正文已修改仍须解决冲突，不伪造基准。

旧 spec.md、plan.md、任务编号、回答、附件、验收证据、伴读、意图账本保留。运行时 adopt 映射原文件不改正文，初始待核验；旧完成勾选不变成当前用户验收。升级不改删 `.worktrees/.ph/`，既有工作区是执行状态，不是旧技能资产。

活动内容位于 project-harness 的 constraints/documents/specs/memory/archive/runtime。通过新治理脚本物化宪法、刷新逐文件导航并保留用户原则。退出上游生成器不能丢治理覆盖，不需要调用已退役 ph-constitution 补尾。

## 验证与定版

语义合并后核对原件可恢复、有效内容落点、必需技能集合、英中对照、适配、运行命令、文档/用例引用。按 ph_governance.py 帮助和发行根 references/项目化验收.md 做内容/导航检查；安装副本从项目内 ph-init 包读取同一指引，不解析不存在的仓库根引用。

```text
python3 <release-root>/scripts/ph_merge_update.py verify --repo <target>
python3 <release-root>/scripts/ph_merge_update.py finalize --repo <target>
python3 <release-root>/scripts/ph_merge_update.py finalize --repo <target> --apply
```

最终 apply 须适用审批和候选检查通过，保留原适配模式。目标版本已写不替代迁移证据，pending/blocked 保持 in_progress。失败不报完成。finalize 后用已装内核离线 check；check/sync 不补文档、不顺便升级。

报告实际改动、保全原件、承接定制、退役入口、新技能、真实验证和限制。区分脚本结构通过、语义验收和公网发行验证。不为升级提交、推送、部署、发布、写记忆或清理 worktree。不用 rm，退役按可恢复备份和已授权废纸篓策略处理。
