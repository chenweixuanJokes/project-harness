---
name: ph-init
description: "初始化、检查或同步本仓库的项目级 Harness（PH）：从唯一 GitHub 源准备正式发行版，安装 canonical、八个 PH skills 与 project-harness 目录结构，并从 PH 随包资产安装十个基于固定官方 Spec Kit 的适配版 ph-* skills 与运行时。存量项目用旧内容接入：盘点后在仓外生成 sources 快照与合并候选，经 init --adopt-plan 安装，不先装模板盖旧正文；init 会话按代码与实时官方资料逐项补全文档并产出覆盖报告。调用门禁：仅当用户当轮明确点名 ph-init（如「用 ph-init 初始化这个仓库」）并要求使用时才调用；只说“初始化 PH”“检查 PH”“同步 PH”“升级 PH”“bootstrap harness”等普通描述、上下文提及或讨论技能名称都不触发。已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。已装项目的安装、检查、同步、升正式版都由本 Skill 接；用户已请求的升级在本会话按 merge-update 步骤做完，不另开技能。不要把编码客户端内置的初始化向导（如 /init）、厂商脚手架、git init、目标仓 git pull、或 ph-worktree-* 误判为本技能。"
---

# ph-init

把正式发行版的 PH 落到 Git 仓库：空仓库安装脚手架，存量项目用旧内容接入（已有正文优先引用，不复制第二套），并在初始化会话逐项补全文档；也可只检查 / 修复适配层。已接入且版本旧于发行根时，**同一会话**按发行根的 merge-update 步骤做完升级，不要用 `init --apply` 覆盖定制，不要另开技能。

PH 面向多种编码客户端：约束与技能的正式存放位置（canonical）固定在 `.agents/`，仓库根 `AGENTS.md` 是通用入口；Claude Code 通过 `CLAUDE.md` 与 `.claude/skills/` 适配层接入；Codex、OpenCode 原生读取 `.agents/skills`。

## 何时用 / 何时不用

**调用门禁**：仅当用户当轮明确点名本技能（如「用 ph-init 初始化」「用 ph-init 升级 PH」）并要求使用时才执行。用户只说“初始化 PH”“检查 PH”“升级 PH”、上下文提及、或讨论技能名称本身，都不触发；不点名时不下载、不安装、不改目标。

使用：

- 空仓库或尚未接入 PH 的存量仓库：先准备正式版，再盘点、整合、经仓外合并候选安装与补全文档
- 已装且要跟官方包对齐（用户点名 ph-init 并要求安装或升级）
- 检查 portable 副本 / symlink 是否与**项目已装** canonical 一致
- 同步适配层漂移（根 `AGENTS.md`、`CLAUDE.md`、`.claude/skills/`）
- 续做本次初始化未完成的文档：读已装指引、`.agents/init-report.md` 与磁盘实态；不重跑安装、不借机升版本

不用：

- 编码客户端内置的初始化向导（如 `/init`）、厂商脚手架、`git init` 本身
- 在目标仓库 `git pull` 当升级
- `ph-worktree-*`（worktree 创建与交付）、`ph-memory-*`（记忆查询 / 写入 / 学习 / 归档）与上游规格技能（`ph-specify` 等，用户点名才触发；查询技能 `ph-memory-ask` 是唯一例外，用户表达回忆意图时自动触发）；其余技能仅在用户点名该技能并要求使用时触发，本 Skill 不代为调用

## 1.2.1 完成交付要求

本次升级必须把旧项目的有效内容移植到 `.agents/project-harness/` 下的新规范，而不是把旧文件归档后留下空模板。开始写入前盘点全部旧 PH 技能及附属资源、入口、配置、脚本、文档、记忆、规格与升级记录，在统一 archive 保存原件及逐文件校验清单；用户定制和未提交内容也属于保全范围。无关业务文件不接管，个人 HOME 不触碰。

随后逐项承接有效内容：规则进入 constraints 并由顶层 constitution 逐文件引用、注明使用时机；项目事实进入 documents；活动记忆进入 memory；当前需求、任务状态及必要原话和附件进入 specs；运行文件进入 runtime。归档不等于迁移完成。每项仍有效的旧内容都须记录新位置及验证证据，只有明确被替代或废弃的材料才只留历史原件。

在本次已授权的安装/升级中完成 constitution 物化及约束索引，不要求用户另行调用 ph-constitution 补尾。已有原则必须保留；缺少使用条件时阅读正文归纳，真实冲突未解决时阻断，不以占位符或待确认内容交付。

精简 AGENTS.md 只移除已经在新版约束中承接的详细规则及冗余技能列表，保留读取 constitution 的执行要求。技能调用条件由各自元数据声明。新路径实际运行、原件完整性与有效内容承接均通过后，才清理旧活动入口并推进版本。完整步骤按准备好的发行根 ph-merge-update 正文执行。

## 唯一源与准备

正式源只有 `https://github.com/chenweixuanJokes/project-harness.git`。官方仓库由 `ph-init` 更名而来，产品名 Project Harness；技能名与安装路径不随仓库名变化，仍是 `ph-init` 与 `ph-*`。旧地址 `https://github.com/chenweixuanJokes/ph-init.git` 经 GitHub 重定向指向同一仓库：1.1.8 及以后入口按旧地址 prepare 也能取到新包，不是错误；`FIXED_SOURCE` 等固定标识与 `release.json.repository`、`receipt.source`、`state.source.repository` 在 1.x 保留旧地址的兼容含义，存量值不改写、不当作错误。`latest` 取数值最大的稳定 tag（排除预发布与非版本标签），并固定到该 tag 的 commit。本批版本为 `1.2.2`（八个 PH 必需 Skill 加十个上游规格技能）。PH 只有这一个版本号：不再有独立的 Schema 版本，发行包与项目清单都不携带 `schema_version` 字段，schema 标识固定为无版本的 `urn:ph:schema:project-harness`；`template_version` 仍表示项目已完成升级的 PH 版本。

### Spec Kit 集成（固定正式版）

十个技能为 `ph-analyze`、`ph-checklist`、`ph-clarify`、`ph-constitution`、`ph-converge`、`ph-implement`、`ph-plan`、`ph-specify`、`ph-tasks`、`ph-taskstoissues`。

十个规格驱动 ph-* 技能及运行时直接由 PH 发行包提供，正文位于 assets/scaffold，来源由 speckit.json 和 assets/speckit-bundle.json 记录。安装前校验完整清单与哈希；用户安装和升级不访问官方 Spec Kit、不调用 pip、不创建官方 CLI 环境。官方固定 tag+commit 仅用于维护者按需引入上游，实际分发内容是 PH 适配版。

安装使用 scripts/ph_speckit.py，先 dry-run 再 --apply。逐文件内容基准仍记录在 .agents/ph.json.speckit.files；来源标记不构成未修改证明。受管文件磁盘字节与旧基准一致才可更新，用户定制冲突不得覆盖。普通 scaffold 部署不重复写这些文件，最后重新记录基准。包损坏或冲突阻止安装，不推进版本。

运行时位于 .agents/project-harness/runtime，项目宪法位于 project-harness/constitution.md；宪法保留项目原则并导航现行约束。十技能按阶段默认落实项目测试规范，不新增验收入口、不自动串联技能。十技能在产出机器产物时附带生成同功能目录的人读伴读（快照解释，非权威规则或验收源）：映射、来源哈希与受管写入由 `.agents/scripts/ph_human.py` 完成，写作规范与按需盘点刷新由 ph-human 技能提供（ph-human 仅用户点名时触发；十技能直接读取其规范文件，不调用它、不自动串联技能）。ph-implement 默认完成必要测试与证据记录，不能以任务打勾代替验收；没有合并授权不得为交付自动合入。十技能在完成报告与 extension hook 处理结束后，固定输出「下一步建议执行」收尾文案：先建议压缩会话，再按场景列出后续可点名执行的技能；只建议，不自动调用。


当前这份 Skill 可能是旧用户入口或 shadow 副本。**初始化必须先准备发行根，再读该根的 `SKILL.md` 并只执行该根脚本**。不要用眼前这份本地 `assets/scaffold` 冒充最新版。离线内核可以安装它携带的确定版本，但不代表最新正式版。

```text
python3 <ph-init-root>/scripts/ph_release.py prepare --version latest|1.1.14 --repo <target>
```

stdout JSON：`root` `version` `tag` `commit` `source`（`source` 是固定仓库 URL 字符串）。材料下在目标仓库外的隔离目录，不读不传目标内容。同一 commit 已在本地时检查可不访问网络。无 tag、网络失败、tag/commit/`release.json` 不一致：停止，不回退到未准备的本地包。

准备成功后，把脚本写在标准错误里的那段话原样转告用户：已登录会加星并在当前账号下建副本（已有则复用）；没登录或做不到只说明安装不受影响。不要再弹选择题，不要请用户当场登录，不要把账号副本当成以后的下载地址。用旧脚本第一次拉到本版时，读到本 Skill 后补跑：

```text
python3 <release-root>/scripts/ph_release.py support
```

记下 JSON 里的 `root`。后续 dry-run 与 apply 固定同一 `version`/`commit`。预检可以下载，不得改目标。

prepare 成功后，顺带执行一次用户级入口刷新：

```text
python3 <release-root>/scripts/ph_release.py user-entry
```

它把 `~/.agents/skills/ph-init` 整树刷新为该发行根（旧树先移入 `~/trash` 备份，来源回执随树写入；刷新失败自动还原，不会留下半份入口）。入口不存在、不是普通目录、版本无法判定或不旧于本包时返回 `action: skip` 与原因，这不是错误：不新建入口、不降级、不当作安装失败。只从准备好的发行根运行，不在开发树或项目内执行。

旧版（1.1.7 及更早）用户级入口的 prepare 会**必然拒绝 1.1.8 及以后发行包**：旧脚本必查发行元数据里的 `schema_version`，新版包已删除该键。这是预期现象，不重试、不回退、不假称自动恢复。一次性入口切换使用首个无独立 Schema 版本的已发布标签 v1.1.8：把 v1.1.8 clone 到一个**新的仓外安全目录**（如 `mktemp -d` 创建），不覆盖用户级入口与目标项目，不用 `main` 或本地开发树冒充发行；先在该目录运行 `python3 <新目录>/scripts/ph_release.py prepare --version 1.1.8` 并读取返回根的 Skill，再用这份新工具准备并固定后续发行根。**1.1.8-1.1.13 入口无法直接准备 1.1.14**（1.1.14 起必需技能名单拆为 4 个 scaffold 技能加 10 个安装期生成的规格驱动技能，旧校验器按 manifest 与 `required_skills` 全等校验会以 skills.required_names mismatch 拒绝；这是设计使然，不要绕过）：把 v1.1.14 标签本身 clone 到新的仓外安全目录，运行该目录的 `python3 <clone>/scripts/ph_release.py prepare --version 1.1.14 --repo <target>`（其自带校验器验证本版发行并写入 receipt），再用返回根执行升级。之后只用 1.1.14 根按 merge-update 步骤合并、verify、finalize；旧 `schema_version` 字段仅在 finalize 验收通过后随版本写入一起移除。已经持有本次 prepare 的固定 1.1.14 root 时，读取其中 Skill 后直接进入分流，不再次 prepare。

`build_scaffold.py` / `build_project_template.py` 是旧 monorepo 作者工具，不是发布源，安装与升级不要跑它们。

## 命令

准备完成后，安装内核在发行根，默认 dry-run：

```text
python3 <release-root>/scripts/ph_init.py init [--apply] [--adopt-plan <plan.json>] [--mode auto|portable|symlink] [--repo <git-root>]
```

已装且仓内 `template_version` 与本包不同时，`init`（含 `--apply` / `--adopt-plan`）退出 1，并写出本会话接着要跑的 inspect 命令。不要把这次失败当成可以改用 `init --apply` 盖过去。

`check` / `sync` 使用**目标项目已安装**的内核，保持离线，不重新 prepare，不 `git pull`，不触发文档补全，不升版本：

```text
python3 <project-or-installed-ph-init>/scripts/ph_init.py check [--mode portable|symlink] [--repo <git-root>]
python3 <project-or-installed-ph-init>/scripts/ph_init.py sync [--apply] [--mode portable|symlink] [--repo <git-root>]
```

- `--mode` 缺省（新装 auto）：项目尚无 `.agents/ph.json`、也推断不出既有适配层时，新装在 apply 阶段优先使用相对 symlink：先检查 Git 配置并探测文件与目录软链接，可用即使用，探测失败自动改用 portable，不当作错误。dry-run 不探测、不写入，分别展示两种模式的条件计划；两种计划都存在冲突时不执行能力探测。显式 `--mode symlink` 严格失败：探测不通过即阻断，不回退。
- 已装项目保留模式：先读 `.agents/ph.json` 声明，再从已有适配层推断；check / sync / 升级沿用该模式，不自动转换。仓库级固定，工具内不做 mode 迁移。
- `portable`：受管副本 / 镜像，不是功能降级。根 `AGENTS.md` 与 canonical 字节一致；`CLAUDE.md` 为 `@.agents/AGENTS.md` stub；`.claude/skills/ph-*` 为完整受管镜像。Windows `core.symlinks=false`、不支持符号链接的文件系统、打包或同步会展开链接的场景，使用 portable。
- `symlink`：上述入口是指向 canonical 的直接相对软链。禁止 hardlink / junction。`core.symlinks` 显式 false 时阻断。写入前探测软链能力。
- 未带 `--adopt-plan` 的 `init` 对 `docs/**` 已有安全普通文件只保留并报告待会话审阅，这不是已合并；**不得用这种安装先落模板再盖旧正文**，存量内容一律走 `--adopt-plan` 合并候选。其余冲突 fail-closed。`sync --apply` 只覆盖结构化 `content_drift`，不改 canonical 或 docs。

`--adopt-plan` 契约（仅当目标尚无 `.agents/ph.json`；已装旧版由本会话按 merge-update 步骤升级，不走 adopt）：

- `version` 固定 `1`；`repo` 是目标仓绝对路径；`release_version` 是本发行包版本。
- `sources`：合并基准快照，`{仓内相对路径: 正文 SHA256，文件缺失为 null}`；必含 `.agents/AGENTS.md`、`AGENTS.md`、`CLAUDE.md` 三个入口，以及 `files` 的全部目标路径。
- `files`：候选 UTF-8 正文，只允许 canonical `.agents/AGENTS.md`（必需）、`docs/**` 与 `.agents/project-harness/{constraints,documents}/**`。候选由已有正文与脚手架整合：已有正文优先原样保留或引用登记，不复制第二套。
- plan 文件由会话在目标仓外生成：不进项目、不改发行树、不写秘密 / 令牌 / 完整连接串。脚本核对 `sources` 哈希与目标实态一致才落盘；哈希护栏只防错仓、错时点与中途变更，**不证明候选内容完整正确**，语义由会话 Agent 负责。

- 嵌套 symlink/junction、仓外解析、hardlink、受管镜像中的未托管多余文件保持阻断。`sync` 不升级 canonical、不补缺失 Skill。

## 工作流

1. **确认动作与范围并分流**。读目标 `.agents/ph.json`（没有就当未安装）。对目标跑 `prepare`，记下发行根，随后执行一次 `python3 <发行根>/scripts/ph_release.py user-entry`，把用户级 ph-init 入口顺带刷新到本包（跳过即向用户报告原因，不新建、不降级、不重试）。只要是 check/sync 就不生成文档、不升版本。然后：
   1. 已装且仓内版本**小于**发行根：读该根 `assets/scaffold/.agents/skills/ph-merge-update/SKILL.md`，**本会话按那份执行**（inspect → 按迁移说明语义合并 → verify → finalize）。旧项目没装这个 Skill 也以发行根这份为准。禁止 `init --apply` / `--adopt-plan`，不另开技能，不自动 finalize。
   2. 已装且版本相同：报告已接入；要 check / sync / 续做文档就走对应分支，不重跑安装、不升版本。
   3. 已装且仓内版本**大于**本包：停止，说明不要降级；换匹配或更新的正式包。
   4. 没装：继续下列安装 / adopt。
2. **初始化：准备发行根**。读该 `root` 的 `SKILL.md`，用该 root 的 `ph_init.py`。同时读该 root 的[初始化与文档补全](references/接入规范.md)，不能先改准备好的发行树。
3. **只读盘点**：核对 Git 状态与已有内容，汇总七类证据：模块、代码、配置、真实依赖（锁文件）、测试、CI、旧约束（含 `docs/` 下非 PH 命名的旧文档目录）。已有正文优先引用登记，不复制第二套；待核实项与已定性为规则 / 事实 / 建议的条目分开，不臆造 ADR、意图、访谈、记忆或测试通过。
4. **dry-run 与报告整合**：同一 `root` 不加 `--apply` 跑 dry-run；`plan` / `skip` / `conflict` / `block` 是待整合材料，不是施工单。向用户交整合结果：直接落地、复用引用、冲突待裁决、不适用与保留范围。对用户说明和提问前先读已装或发行根的 [对用户提问](assets/scaffold/.agents/project-harness/constraints/harness规范/对用户提问规范.md)，不要把内部字段或脚本名当问句。仅预检时不写 docs。根 `AGENTS.md` 在而 `.agents/AGENTS.md` 不在、受跟踪 `.worktrees/`、不安全链接或路径仍阻断，不能移走文件后偷偷强装。
5. **仓外合并候选**：获得本轮授权后（对用户问“现在可以按这个范围写入吗”），会话在目标仓外生成 `sources` 快照与合并候选 plan JSON（契约见命令节）。内核 adopt 只写白名单内的 canonical、项目约束和资料候选，不自动搬移或删除。已有正文优先复用 / 引用登记，不复制第二套、不重写已有证据的正确内容。
6. **adopt 安装**：用户确认候选后，同一 `root` 执行 `init --adopt-plan <plan>`，先 dry-run 再 `--apply`。`--apply` 的顺序是：先 spec-kit 安装（失败即整体中止、无 adopt 哈希污染、可重试），再 adopt 候选、scaffold、ph-init 自装（含 scaffold、release 元数据、在线脚本、spec-kit 集成脚本、迁移资料；scaffold 内不嵌套 `ph-init`）、适配层镜像（Claude 镜像按 `include: ph-*` 自动覆盖十技能）。安装成功立即跑已装内核的 `check`。
7. **逐项补全与覆盖报告**：按已装指引分阶段派发 subagent。旧目录与顶层正文按指引 1.1 归并进 `project-harness/` 新落点：同主题合成单一正文，附件随所属正文走，旧计划不推定评审或通过；写前把原文备份到 `.agents/project-harness/archive/legacy-backup/<日期>-pre-init/`，修活动引用与索引后再移出活树旧文件，仓内快照即是可恢复原件，未授权或冲突记未完成。先取真实栈与代码证据，再按独立文件归属补 Wiki、前端、后端、工程与测试规范；官方资料按目标实际版本实时查阅并记录 URL、版本、访问日期与采用理由，搜索只用通用技术名，不上传项目内容。主会话维护 `.agents/init-report.md` 覆盖报告：矩阵每个独立 id 一行（落点、仓内证据、结果、说明），结果只用已核验 / 复用 / 不适用 / 待核实 / 冲突；PH 通用流程条目写采用声明，不编造项目记录。改 canonical 后按原 mode 先 dry-run 再在授权范围内 `sync --apply`，重新 `check`。没有 subagent 能力则如实报告限制并串行取证。
8. **交付或续做**：分别报告“PH 安装检查”“文档补全”结果，列已核验、复用、待采纳、待核实、不适用和冲突项。网络/子任务失败不抹掉已核验成果，也不宣称文档完成；续做读磁盘、`init-report` 与上次记录，不再 `init --apply`。需要时用刚装好的包初始化临时另一仓，确认自包含。

## 项目化内容交付

初始化、升级和同版本续做均读取 [项目化验收](references/项目化验收.md) 与 [补全规范](references/补全规范.md)。按基础树逐篇填入当前项目事实、有效旧规则或新项目基础需求，不用空模板充数。新项目拟采用约定与已有实现分开写，未执行命令不得标通过。存量有效发布运维等专题继续保留。

主代理逐篇核验后记录文件证据，刷新宪法导航并运行 `ph_speckit.py verify-content`；失败时只能报告骨架可用，不能宣布初始化或升级完成。已授权范围内无冲突步骤直接继续，不重复确认。

## 完成标准

- 未调用编码客户端内置的初始化向导（如 `/init`），未对目标 `git pull`。
- 初始化的 dry 与 apply 来自同一 prepare `commit`；dry-run 未改目标，准备失败未用本地旧模板装“最新”。
- 本会话 prepare 成功后已执行 `user-entry` 并按结果处理：已刷新（旧入口备份在 `~/trash`）或明确跳过（不存在 / 非普通目录 / 版本无法判定 / 不旧于本包）；未新建入口、未降级、未把跳过当失败。
- 未先安装模板再盖旧正文：存量内容经仓外合并候选接入，`sources` 快照与 plan 均在仓外生成，发行树未被改动；已有正文以复用 / 引用登记，未复制第二套，冲突未擅自裁决。
- `--adopt-plan` 仅用于尚无 `.agents/ph.json` 的目标；`--apply` 后已装内核 `check` 通过；未为原生读取 `.agents/skills` 的客户端另建重复技能目录。
- spec-kit 集成来自 PH 随包适配版，来源与文件哈希符合发行清单，安装不依赖官方生成缓存；十技能目录与 frontmatter 已统一改 `ph-` 前缀、上游来源映射在 `x-ph-upstream` 与 `.agents/ph.json.speckit` 中可查；仓库根无 `.specify/` 与 `specs/`，运行时落在 `project-harness/runtime/` 且脚本可真实执行；constitution 已物化在 `project-harness/constitution.md`，逐文件引用当前 `project-harness/constraints/` 文档并写明使用时机（无占位、无待确认遗留）；与用户自定义同名技能冲突时未覆盖而是阻断上报。
- `.agents/init-report.md` 覆盖指引第 5 节全部独立 id；未核实内容未伪装成规范或事实，未执行命令未标通过，未臆造 ADR / 意图 / 访谈 / 记忆 / 测试通过。安装检查通过不代表文档补全完成。最终 PH 活动内容只在 `.agents/`（含 `project-harness/`），`docs/` 归业务文档；未获迁移授权或存在冲突的旧目录记未完成，不把长期并存当完成。
- 已装旧版未走 `init --apply`；升级在本会话用发行根 `ph_merge_update.py` 做完，未另开技能、未自动 finalize。1.1.7 及更早入口拒绝新包时已用已发布 v1.1.8 完成一次性入口切换，并由该工具取得固定的 1.1.14 发行根；旧 `schema_version` 字段仅在 finalize 通过后移除。文档补全和普通 check/sync 未擅自升版本。
- 未自动 commit / push / 公开仓库、部署或发送通知。
