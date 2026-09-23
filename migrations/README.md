# 迁移说明

相邻正式版本之间的变化与适配步骤。`index.json` 是顺序源；升级必须读完起点到目标的完整链。后来覆盖的中间变化可以合并成最终操作，但不能跳过未知版本或缺失记录。

`1.0.0` 与两套 `1.1.0` 命名是仓库可追溯的历史布局，不是已发布 tag。首个正式 tag 是 `v1.1.1`，不追认旧 `1.1.0` tag。

## 维护

- 每个对外批次写一份 `migrations/<from>-to-<to>.md`，并在 `index.json` 追加一条相邻记录。
- `items` 使用稳定 id，与项目 `.agents/updates/<to_version>/state.json` 的 `items[].id` 一致。
- 无需存量迁移的批次也要有说明，写明“无存量项”。
- 链接用有效相对路径。不要把 `main` 或本地 `assets/scaffold` 写成已发布最新版。

## 说明模板

每份迁移说明使用下列标题，缺一不可：

```md
# <from_version> → <to_version>

## why
为什么有这次变化。历史补录须标明不是新发布。

## from
起点的真实行为、Skill 名、目录和版本锁。按文件实态识别，不靠口口相传。

## to
目标行为。可把后续覆盖的中间态写成最终操作。

## affected
会被动到的路径、Skill、厂商入口、索引。只列迁移要求改的范围。

## preserve
默认保留：项目事实、访谈原话、业务编号、旧进行中条目、无关 Wiki/记忆、adapter mode。

## conflict
与项目显式规则或本地定制冲突时停止受影响项，备份后请用户决定。禁止 `rm`。

## verify
可检查的完成标准。未完成不得推进 `template_version`。
```

当前链：

| 段 | 说明 | 项 |
| --- | --- | --- |
| [1.0.0 → 1.1.0](./1.0.0-to-1.1.0.md) | 历史补录：意图域与三 Skill | `intent-domain` |
| [1.1.0 → 1.1.1](./1.1.0-to-1.1.1.md) | 首个正式发布批次 | `intent-skill-names` `intent-lifecycle` `online-source` `merge-update` `schema-contract` `project-content` |
| [1.1.1 → 1.1.2](./1.1.1-to-1.1.2.md) | 意图交付留实施，取消旧状态目录 | `intent-no-completed` `intent-legacy-inprogress` |
| [1.1.2 → 1.1.3](./1.1.2-to-1.1.3.md) | init 会话补全文档与项目内容保护 | `init-docs-workflow` `docs-guidance` `docs-project-preserve` |
| [1.1.3 → 1.1.4](./1.1.3-to-1.1.4.md) | 存量约束合并接入与全量文档取证 | `adopt-plan-init` `adopt-existing-content` `init-report-coverage` |
| [1.1.4 → 1.1.5](./1.1.4-to-1.1.5.md) | 已装旧版由 ph-init 会话做完升级 | `init-unified-entry` |
| [1.1.5 → 1.1.6](./1.1.5-to-1.1.6.md) | 对用户提问改成日常用语，内部字段名仍留在代理侧 | `plain-user-questions` |
| [1.1.6 → 1.1.7](./1.1.6-to-1.1.7.md) | 准备成功后已登录则加星并建账号副本，不改下载源 | `prepare-star-fork` |
| [1.1.7 → 1.1.8](./1.1.7-to-1.1.8.md) | 彻底取消独立 Schema 版本，单一 PH 版本与一次性入口切换 | `single-ph-version` |
| [1.1.8 → 1.1.9](./1.1.8-to-1.1.9.md) | worktree 默认使用当前源分支，任务分支由代理确定；适配层改工具中立三工具拓扑，安全退役 `.codex/skills/ph-*`；官方仓库更名 `project-harness`，产品名 Project Harness，技能名不变 | `worktree-auto-branch` `tool-neutral-adapters` `repository-rename` |
| [1.1.9 → 1.1.10](./1.1.9-to-1.1.10.md) | 新增第十一个必需 Skill `ph-docs-sync`：对照代码 / 配置 / 锁文件 / CI 核验并按授权修复 README、docs 配置说明、使用示例与 Wiki；升级只装 Skill 与规则索引，不自动同步业务文档 | `docs-sync-skill` |
| [1.1.10 → 1.1.11](./1.1.10-to-1.1.11.md) | 实现默认留当前分支，worktree 默认从当前分支检出；初始化指引 adopt 命令示例补 `--mode auto` | `current-branch-defaults` `adopt-mode-docs` |
| [1.1.11 → 1.1.12](./1.1.11-to-1.1.12.md) | 对用户提问重写为执行契约：是否问、通道与工具实际调用、问题质量、答案三态处理、失误纠正与中断恢复、边界示例；引用改语义落点，不再锚定章节号；该文件整文件覆盖（旧原文备份后替换），不保留文件内项目定制 | `question-execution-contract` |
| [1.1.12 → 1.1.13](./1.1.12-to-1.1.13.md) | 十二个技能统一显式调用门禁：仅当用户当轮点名技能并要求使用才调用，普通描述 / 上下文 / 讨论名称不触发；清除技能间自动串联（升级会话内部步骤除外）；新增第十二个必需技能 `ph-intent-verify`：实现完成后由用户逐点验收，结论写入意图「记录」节，不新增状态 / 目录 / purpose | `explicit-invocation-rules` `intent-verify-skill` |
| [1.1.13 → 1.1.14](./1.1.13-to-1.1.14.md) | worktree 进入源树、退出任务树与合并目标源树因未提交改动实际阻断时，统一先展示目录 / 分支 / 完整清单与拟用 wip 信息（说明现场与安全筛查结果），再实际调用问答工具提出固定问句（只给"确认 WIP 并继续""停止，保留现场"两个选择，问的是是否采用 wip: 提交解决当前阻断、不是内容审批）；未确认停止；同一已展示路径的普通内容修改不重问，分支 / HEAD / 拟提交路径或状态集合变化阻断重新预检重新确认，授权非长期、新阻断重新确认；退出不再按 staged / unstaged 分级默认普通提交，受确认提交经统一脚本 `wip` 子命令执行（dry-run 只读、确认后显式 `--apply`），运行时新增 doctor / recover / redeliver 与 enter 期望源校验，session 新增字段非必填、不覆盖现有 session；两技能内嵌脚本退役、共享 `.agents/scripts/ph_worktree.py`。九个旧受管技能（ph-memory-*、ph-intent-*、ph-docs-sync，含未发布的 ph-sure 残留）先备份再退役，意图 / 记忆 / 业务 docs 保留，规则改为代理按文档执行。十个规格驱动技能与 `.specify/` 共享基础设施由 `ph_speckit.py` 从 GitHub Spec Kit 固定正式 tag+commit 用官方生成器安装，统一改 `ph-` 前缀并记录来源映射（frontmatter `x-ph-upstream` 与 ph.json `speckit` 节），同名自定义技能冲突阻断不覆盖。宪法经上游项目模板覆盖机制（`.specify/templates/overrides/constitution-template.md`）落地 PH 约定：管理区逐篇引用 `docs/约束规范` 实际文档（链接、适用范围、何时打开），识别不了的标待确认，init / 升级刷新 | `worktree-wip-confirm` `retire-legacy-skills` `speckit-core-integration` `constitution-governance-zone` |
| [1.1.14 → 1.1.15](./1.1.14-to-1.1.15.md) | 补齐 Spec Kit 安装完整性、受管路径安全与失败状态门禁：完整受管运行文件与内容基准缺一即阻断，相同内容的软链接 / 硬链接 / 目录占用照常拒绝，基准重建只接受已安装的当前代字节，独立宪法刷新先校验后写入，CLI 的 blocked 与验证失败返回非零退出码 | `speckit-integrity-gates` |
| [1.1.15 → 1.2.1](./1.1.15-to-1.2.1.md) | 新增三个记忆技能 `ph-memory-ask` / `ph-memory-learning` / `ph-memory-archive`（必需 Skill 4→7；ask / archive 以新契约重新引入 1.1.14 退役的名字，learning 为新技能并承接原 capture 的记录职责，capture 名不再发行、旧副本照常退役）：查询按回忆意图自动触发（显式调用门禁唯一新例外），记录 / 学习 / 归档仅当轮点名；双档 project=`<repo>/.agents/project-harness/memory` 与 global=`~/.agents/memory`，查询支持 all、项目内默认项目档未命中不扩大、写入每次一档、个人档仅明确全局时按需创建；秘密阻断、逃逸链接不跟随、未知条目不接管、同名冲突保留、归档幂等可续做、原件正文逐字节保护（仅 kind/status 随移入切换）；记忆内容升级前后逐字节不动；PH 目录归家 `project-harness/`、宪法升级内物化并逐文件引用 constraints（含使用时机）、意图目录退役、AGENTS 精简、规格技能 description 中文化+调用门禁、旧文件全量原件归档 `archive/upgrades/` | `memory-skills`、`ph-home-restructure`、`constitution-materialization`、`intent-retirement`、`bundled-speckit-acceptance` |
| [1.2.1 → 1.2.2](./1.2.1-to-1.2.2.md) | 升级顺带刷新用户级 ph-init 引导入口（user-entry 子命令：不新建、不降级、旧树备份 ~/trash 失败自动还原）；新增第八必需技能 ph-human 与共享脚本 ph_human.py（十个规格技能附带人读伴读：映射+来源哈希+受管写入保护）；十技能新增固定收尾「下一步建议执行」（只建议不调用） | `user-entry-refresh` `human-readable-companion` `speckit-next-step-hints` |
| [1.2.2 → 1.2.3](./1.2.2-to-1.2.3.md) | 彻底取消当前运行发行对上游 Spec Kit 依赖：必需 Skill 唯一来源固定 18 个自研技能，7 个旧规格技能整目录归档退役、3 个同名技能基准识别原位替换、7 个新技能安装（migrate-skills 确定性执行、厂商镜像先归档、中断幂等）；自研运行时接管（speckit.json/bundle/ph_speckit 退役、宪法物化/导航/verify-content 提取为 ph_governance.py、协议脚本 ph_sdd.py 落地）；15 个修改技能英文入口+SKILL.zh.md；文档测试语义合并沉淀；worktree 会话逐字节不动；新产物 requirement/design/tasks/verify-plan/acceptance/verification（small 用 change.md），旧 spec/plan 兼容读取；1.2.2 旧入口 prepare 新包硬失败，一次性从 v1.2.3 仓外新目录过渡 | `sdd-skill-replacement` `sdd-runtime-takeover` `bilingual-skills` `docs-tests-consolidation` `worktree-session-continuity` `artifact-compat` |
