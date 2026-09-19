# Changelog

本仓库用户可见的正式版本摘要。相邻版本的适配步骤见 [migrations/README.md](./migrations/README.md)。

从 `1.1.8` 起只有一个 PH 版本号，不再单独维护 Schema 版本（`1.1.7` 及更早的历史批曾以独立 Schema `1.1.1` 维护，见各版段落，最终态以本版为准）。

尚未打过历史 tag。`1.0.0` 与两套 `1.1.0` 命名是可追溯提交，不是已发布 tag。首个正式 tag 是 `v1.1.1`，不追认 `v1.1.0`。

## 1.1.14

- 技能集整体收缩与上游集成：PH 自身只保留四个必需 Skill——`ph-init`、`ph-merge-update`、`ph-worktree-enter`、`ph-worktree-exit`；九个旧受管技能（`ph-memory-capture`、`ph-memory-archive`、`ph-memory-ask`、`ph-intent-new`、`ph-intent-impl`、`ph-intent-verify`、`ph-intent-drop`、`ph-docs-sync`，含未发布草稿的 `ph-sure`）从 scaffold 与旧项目升级的受管安装移除，退役文件先备份到 `.agents/updates/<ver>/backup/`；意图（`docs/意图/`）、记忆（`.agents/memory/`）与业务 docs 结构及内容保留，规则文档改为"由代理在普通会话按本文执行"。
- 十个规格驱动技能 `ph-analyze`、`ph-checklist`、`ph-clarify`、`ph-constitution`、`ph-converge`、`ph-implement`、`ph-plan`、`ph-specify`、`ph-tasks`、`ph-taskstoissues` 与 `.specify/` 共享基础设施（scripts、templates、manifests、初始 constitution；不安装仍绑定上游技能命名的工作流引擎资产）由 `scripts/ph_speckit.py` 从 GitHub Spec Kit 固定正式 tag+commit（`speckit.json`，当前 v1.0.8 / 0cc9a6a1）用官方生成器安装：克隆固定 tag 校验 commit → 隔离 venv 安装官方 `specify` CLI（不装全局）→ 隔离暂存目录官方生成 → 统一改 `ph-` 前缀（目录、frontmatter `name`、技能间 `$` / `/` 调用一致转换，`.specify` 目录不改名，`speckit.` 点形式扩展 hook 标识保留）→ 安全合并进目标项目。来源映射记录在 frontmatter `x-ph-upstream` 与 `.agents/ph.json` 的 `speckit` 节供后续升级比对。项目同名自定义技能冲突时阻断不覆盖；获取 / 生成 / 安装失败整次安装或升级停止、不推进版本，已装部分幂等、重试续装。
- 宪法治理：`.specify/templates/overrides/constitution-template.md` 是 PH 生成的项目级覆盖模板（上游解析优先级最高、replace 策略），`ph-constitution` 技能后续更新宪法时保留 PH 约定——管理区逐篇引用 `docs/约束规范` 实际文档（每篇相对链接、适用范围与何时打开，从目录索引或正文提取，识别不了的明确标"待确认"），不复制规范正文、排除 Wiki 空模板与维护者规则；init / 升级流程在文档增删移动后刷新该区；`.specify/memory/constitution.md` 的用户原则正文保留不改写。
- 两个 worktree 技能共享单一脚本 `.agents/scripts/ph_worktree.py`（原两份内嵌副本退役，技能正文统一引用共享路径；`canonical.scripts` 入 ph.json）。
- worktree 未提交改动的处理统一为"WIP 统一确认"，同一套规则覆盖三个位置：`ph-worktree-enter` 的源工作区（创建被脏状态阻断时）、`ph-worktree-exit` 的任务树（交付前有 staged、unstaged 或 untracked 内容时）与 `ph-worktree-exit` 的合并目标源工作区（合并被脏状态阻断时，`wip:` 提交做在源工作区）。先只读检查并列明所在目录、当前分支、staged / unstaged / untracked 完整清单与拟用的 `wip: <说明>` 提交信息，再按 `Git与并行开发.md` 第 2 节的固定问句模板实际调用问答工具提问；两个选项文案固定为字面"是""否"；没有可用问答工具或工具故障时按《对用户提问》的降级规则用可见文字提出同一模板并等待回答。确认问的是"是否采用 `wip:` 提交解决当前这次阻断"，不是对文件内容的逐项审批。拒绝、取消或未回答时保留全部改动并停止，不 stash、不丢弃；同一阻断场景内普通内容变化不重问，授权不是长期授权；WIP 确认只覆盖这次 `wip:` 提交。
- `ph-worktree-exit` 取消按 staged / unstaged 分级默认普通提交：任务树有内容时先统一 WIP 确认，再由统一脚本执行受确认的 `wip:` 提交。运行时脚本扩展：`wip` 子命令（dry-run 只读、确认后显式 `--apply`）、只读诊断 `doctor`、显式恢复 `recover`、重新交付 `redeliver` 与 `enter` 的 `--expect-source-head` / `--expect-source-branch` 校验；`exit --apply` 使用 `--wip-message` 接收已确认的 WIP 提交信息。安全筛查保持：疑似密钥、异常大文件与未解决冲突不得收进，整单拒绝、不部分提交。
- 合并冲突恢复统一为固定冲突问句：保留 Git 标准 merge 状态，先只读确认 `MERGE_HEAD` 与未合并条目并列明冲突清单、依据 session 合并快照核对 merge 身份，再按固定冲突问句实际调用问答工具提问（"保留现场，我解决后继续""撤销这次合并"）；保留现场即停止等待，用户明确"已解决并暂存，请继续"且只读核验通过才 `continue`；撤销是仅本次 `abort-merge` 的单独授权；冲突态优先于 WIP 流程；陌生 merge 与旧 session 缺证据保守阻断，用 `doctor` 诊断、`recover` 显式恢复。
- 旧意图机制升级为 Spec Kit 规格驱动（迁移项 `intent-to-spec`，必过项）：`docs/意图/待办/`、`实施/`（兼容早期 `进行中/`、`已完成/`）每个条目由发行根 `ph_merge_update.py migrate-intents` 逐字摘录生成 `specs/intent-<intent_id>/spec.md`（目标 / 范围与非目标 / 关键约束 / 验收标准按模板节别名映射，缺失节标注 NEEDS CLARIFICATION，不编造优先级、技术方案、成功指标，不生成 plan / tasks），原件字节不动转为只读历史；映射持久记录在 `specs/.ph-intent-ledger.json`（跨版本有效），已废弃与访谈条目仅在 `docs/意图/历史索引.md` 登记历史不重开；Status 照录历史状态（Draft / In Progress / Complete / Unknown），不把已完成重开为 Draft、不自动重新验收；重复源 intent_id、目标路径被非迁移产物占用、大小写归一同名 Spec 目录、frontmatter `status_dir` 与物理状态目录不一致均在规划期阻断；源文件漂移阻断 apply 与 verify 并给恢复指引，Spec / 历史索引被用户修改只报告不覆盖；`select-intent-spec` 显式把某个已迁移 Spec 选为当前 feature，只在 `.specify/feature.json` 缺失时写入且值是 feature 目录，从不改写已有活动指针；重复执行 migrate-intents 幂等。
- 迁移项：`worktree-wip-confirm`、`retire-legacy-skills`、`speckit-core-integration`、`constitution-governance-zone`（未发布的 `intent-verify-acceptance-contract` 与 `sure-skill` 迁移项随技能集收缩撤销）。项目定制、业务文档、既有授权结论保留，不因升级重问。
- 写前校验收紧（本批审查修复）：`ph_speckit.py install` 对已有受管文件（`.specify` 文件、`ph-*` 技能、宪法模板覆盖）按**内容基准**归属判定——每次安装把每个受管文件安装后磁盘字节的 sha256 记入 `.agents/ph.json` 的 `speckit.files`；与当前代不同的文件仅在磁盘字节仍与该基准一致（证明上次安装后未被用户改动）或逐字节等于固定上游原版时才写入。manifest 的来源记录、skills 映射与文件自带的 `x-ph-upstream` / PH 生成标记只是来源标记，不构成未修改证明：无内容基准或字节与基准不一致（含用户在已转换模板里附加自定义文字）一律报冲突不覆盖，正常未改动的安装逐字节相同照常跳过。`.agents/ph.json` 的写入安全与可解析性在落盘前校验，软链 / 硬链 / 不可解析提前整单阻断，不再出现"技能已写、manifest 更新失败"的半安装。受确认 WIP 提交把 `--wip-message` 纳入前置绑定校验，缺失或为空在暂存前整单拒绝（此前会先 `git add` 再失败）；`exit --apply` 在任务树 WIP 提交前先校验合并目标可交付，源区处于合并中等不可交付状态时先行阻断、任务树无任何副作用。
- intent-to-spec 解析与映射保真（本批审查修复）：原文重复同名小节全部逐字保留（此前字典覆盖丢第一节、复制末节），代码围栏内 `##` 不再误判为小节，空节照常标 NEEDS CLARIFICATION；不同 intent_id 坍缩到同一目录名时后者加确定性消歧后缀，账本已记录的 Spec 路径永不重算，真实重复 intent_id 仍报 duplicate source id；`specs/` 根或 feature 目录被普通文件占用时 dry-run 报冲突而非 apply 裸崩溃；`docs/意图/` 管理根下出现符号链接目录一律 fail-closed（此前 rglob 静默跳过）；历史索引中的 select 命令指向项目内真实脚本路径 `.agents/skills/ph-init/scripts/ph_merge_update.py`；历史索引被用户修改而账本丢失时保留并报告、重建账本幂等；verify 核对历史索引关键声明（账本路径与 select 命令仍在）并为 history-only 原件补祖先 containment 校验。

- 基准记录与验证门禁：`record-baselines` 遇到任一文件冲突时不刷新宪法模板、不重写 manifest，并向初始化调用方报告失败；`verify` 缺少 Spec Kit 安装记录时拒绝通过。

## 1.1.13

- 全部十二个 PH 技能改为显式调用门禁：仅当用户当轮明确点名该技能（如「用 ph-memory-capture 记住…」）并要求使用时才调用；普通描述任务（如“记住 X”“同步文档”“初始化 PH”“开个 worktree”）、上下文提及或讨论技能名称都不触发。清除“只要用户说…——即使没点名——都必须使用”式描述即触发语句与技能间自动串联：进入 worktree 后的交付由用户点名 `ph-worktree-exit`，录入 / 启动推进 / 验收 / 废弃互不推导调用。门禁只管入口：已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。唯一保留的内部步骤：用户点名 `ph-init` 并请求升级已装项目时，该会话读发行根 `ph-merge-update` 作为该次升级的步骤与参考文档。
- 新增第十二个必需技能 `ph-intent-verify`：实现完成后对唯一意图做产品经理式逐步用户验收。定位意图、验收标准与真实实现（启动推进只表示进入实施与规划，不代表实现完成）；复用已有环境，只按项目说明准备本地服务，不擅自重启 / 安装 / 改配置；按宿主工具能力给用户可见入口，区分隔离浏览器与用户可见页面，可访问的地址不等于已打开，有打开能力且在授权范围内就实际打开要验收的功能、不只给链接，宣称“已打开”必须有实际打开成功的证据；一轮一个验收点（验证什么 / 在哪操作 / 输入什么 / 预期结果），有问答工具就实际调用等用户反馈，确实无工具或开放问题无法用工具表达时按《对用户提问》以文字等效提交，取消、沉默、跳过与代理自测都不通过；失败记录可复现证据，不自动修代码、不调用其他技能、可恢复；记录写入该意图现有「记录」节，不新增状态、目录或纪要 purpose；整体状态只有通过 / 不通过 / 阻断 / 未验收，整体结论由逐项状态汇总而成，全部验收点被用户真实确认才整体通过。
- 各技能 evals 补触发正反例（点名即触发；仅描述、上下文提及或讨论名称不触发）；`ph-intent-verify` evals 覆盖逐步验收、失败、暂停恢复、只读、环境受阻、入口打开证据、无工具降级与整体汇总。
- 迁移项：`explicit-invocation-rules`（十一个既有 Skill 的描述与正文合并门禁、清除自动串联，规则索引与引用文档同步，各 evals 补正反例）与 `intent-verify-skill`（安装新技能并登记规则索引第十二行；升级前已存在的同名自定义 `.agents/skills/ph-intent-verify/` 或禁止新增 ph-* 技能的定制规则阻断该项，由用户决定，与 1.1.10 `ph-docs-sync` 同名保护同机制）。项目定制、业务文档、既有授权结论保留；两项均不新增意图状态、目录或纪要 purpose。

## 1.1.12

- 全面重写《对用户提问》：从按场景罗列编号章节与白话问句模板，改为按执行契约组织——何时需要用户决定、通过正确通道实际提问、把问题写成可回答的决定、根据真实回答推进、纠正失误与恢复中断、边界示例、完成检查；去除编号章节。
- 新口径要点：能查清的事实先查不问，授权内的普通选择自主处理；当前宿主有能合理表达当前问题的结构化问答工具时必须实际调用，正文列选项、预告或承诺不代替调用，调用失败、提交成功、收到回答是不同结果；降级为可见文字提问必须有实际原因（无工具、故障无法恢复，或工具格式无法合理表达开放问题），按具体原因区分权限拒绝、用户取消与无法确认原因的无有效回答，不凭 error 状态默认故障重问；正式计划审批走专用通道，无专用能力时只按宿主明确允许的替代办理否则停；已提交问题、收到回答、取得操作授权是三个状态，不用推荐项或沉默补齐；被指出没用工具且决定未解决时实际重新提交。
- 迁移项：`question-execution-contract`。唯一整文件覆盖授权：《对用户提问》由发行根副本整文件替换（逐字节一致），文件内旧话术与项目定制不并入、不留为仍生效的规则，覆盖前旧原文按现行退役备份机制（`~/trash/` 或 `.agents/updates/<版本>/backup/`）移存、可恢复，重试不重复备份，且不绕过写入确认与文件安全检查。其余按段落语义合并该文引用的工程规范文档、memory README、canonical AGENTS 提问摘要节及七个 Skill 的门禁问句引用，引用改为不锚定章节号的语义落点；报告字段、脚本命令、已填项目正文与既有授权结论保留。

## 1.1.11

- `ph-intent-impl` 默认保留当前分支与工作区；启动意图或批准计划不授权新建、切换分支或创建 worktree，仅用户明确要求时执行。
- `ph-worktree-enter` 默认从主工作区当前所在分支的 HEAD 检出任务分支；主工作区不等于 main 分支，不自动改用 main/master/develop 或远端默认分支。
- 迁移项：`current-branch-defaults`，仅合并两个 Skill 的规则与行为样例，不改变现有分支和 worktree。
- 修正 `初始化与文档补全.md` 中 adopt 安装命令示例的 `--mode` 选项：补上 1.1.9 起实现的新装缺省 `auto`，与入口 Skill 的命令说明一致。迁移项：`adopt-mode-docs`。

## 1.1.10

- 新增第十一个必需 Skill `ph-docs-sync`：对照当前代码、配置、锁文件、CI 与近 7 天提交线索（用户指定提交区间时以指定区间为准；搜索覆盖不足不作否定证据），核验 README、docs 配置说明、使用示例与 Wiki 现行叙述；检查请求默认只读，用户明确要求同步修复才可写，未指定范围时按核验对象默认范围执行，仅授权含糊 / 越界 / 冲突时先问；只修可直接证实的不一致，逐项报告文件与依据，无修改时报告实际核对范围与证据。
- 核验口径：命令示例核对完整前置条件（构建产物来源、工作目录、步骤依赖），不只替换命令名；未运行的命令写明静态依据，不标已验证通过。配置项分别核验名称、可配置性与默认值，常量硬编码或输出等价不构成支持配置的证据；框架默认行为须有仓内依赖版本与可验证实现证据，不凭框架印象推断，证据不足报告未知。修复后重读 diff 并复核受影响文档的链接与索引。
- 行为边界：当前工作区（含未提交改动）是事实；提交标题不能证明实现，找不到提交不能证明不存在。规范冲突不降级规范；历史意图、纪要、Changelog、迁移与归档不改写；可执行示例、真实配置和业务代码只作证据默认不改，文档代码片段可修但不伪称运行成功；Wiki 五字段仅如实维护，局部核对不谎称整页核实；不自动落盘报告 / 造记忆 / 意图、不 git 操作、不部署、不改升级字段。
- 升级行为：`docs-sync-skill` 迁移项只安装该 Skill 并合并规则索引（`.agents/AGENTS.md` 技能表、文档治理 §6、初始化与文档补全），**不自动同步任何业务文档**；项目定制与 adapter mode 保留；升级前已存在的同名自定义 `.agents/skills/ph-docs-sync/`（形态规整进冲突清单，异常形态先被结构校验拒绝，均 fail-closed）或禁止该行为的定制规则必须阻断，由用户决定。迁移项：`docs-sync-skill`。

## 1.1.9

- 创建 worktree 时，来源默认使用主工作区当前分支和当前提交，不再询问或切换来源分支。
- 任务分支由代理根据当前任务和项目命名规则自行确定；用户没有指定时默认创建新的、未占用分支，名称冲突由代理自行调整。只有用户明确要求时才复用已有分支。
- 用户明确要求创建 worktree 已构成本次正常创建授权。代理仍审查只读计划和验收命令，计划无异常时直接创建，不再二次询问分支或是否实际创建；工作区不干净、路径或分支异常等安全门禁保持不变。迁移项：`worktree-auto-branch`。
- 适配层改为工具中立：canonical 固定 `.agents/`，根 `AGENTS.md` 为通用入口；Claude Code 经 `CLAUDE.md` 与 `.claude/skills/` 接入；Codex、OpenCode 原生读取 `AGENTS.md` 与 `.agents/skills`，不再维护 `.codex/skills` 镜像。新装不再创建 `.codex/skills/ph-*`；adapter mode 保留不变，`auto`（优先 symlink、探测失败回落 portable）只是新装的缺省请求，不适用于已装项目。
- 已装项目升级时按证据退役 `.codex/skills/ph-*`：可证明受管的条目在 `finalize --apply` 时归档到 `.agents/archived/<日期>-pre-update/codex-skills/`（portable 镜像整目录移动；活软链改为解除链接并留含原链接目标的记录文件，`.agents/` 内不落任何链接），项目清单移除 `adapters.codex_skills`；形态异常、目标异常、内容漂移或无法证明的一律阻断并原地保留，非 `ph-*` 条目（如 `.codex/skills/my-tool`）永不触碰。迁移项：`tool-neutral-adapters`。
- 官方 GitHub 仓库由 `ph-init` 更名为 `project-harness`，产品名统一为 Project Harness。安装入口与技能名不随仓库名变化：入口仍是 `ph-init`，技能仍是 `ph-*`，用户级安装路径仍是 `~/.agents/skills/ph-init`。新版运行时从新地址下载发行包；旧地址经 GitHub 重定向仍指向同一仓库，`FIXED_SOURCE`、`release.json.repository`、`receipt.source`、`state.source.repository` 在 1.x 保留旧地址的兼容含义，存量值不改写，1.1.8 及以后入口经旧地址仍可取得新包。迁移项：`repository-rename`。

## 1.1.8

- 彻底取消独立 Schema 版本：发行包与项目清单不再携带 `schema_version` 字段，schema 标识固定为不带版本的 `urn:ph:schema:project-harness`，不另升编号。`template_version` 仍表示项目已完成升级的 PH 版本；`format_version` 等内部格式标识不变。
- 旧版（1.1.7 及更早）安装入口在准备发行包时必查 `schema_version`，因此**必然拒绝 1.1.8 包**，也不会自动恢复。首次升级到本版需要一次性入口切换：把官方稳定标签 v1.1.8 克隆到一个新的仓外安全目录（不覆盖用户级入口与目标项目，不用开发分支冒充发行），用新目录运行 `ph_release.py prepare --version 1.1.8`，读取返回发行根的 SKILL 继续升级；v1.1.8 标签发布后适用。
- 存量项目升级仍由 ph-init 会话按发行根 merge-update 步骤完成（inspect → 语义合并 → verify → finalize），不对已装项目 `init --apply`；旧 `schema_version` 字段仅在 finalize 验收通过后随 `template_version=1.1.8` 一起移除。业务正文、既有模式与未完成记录保留。迁移项：`single-ph-version`。

## 1.1.7

- 准备发行包仍只从官方地址匿名下载。下载成功后，本机已登录 GitHub 时顺手给官方仓库加星，并在当前账号下建一份副本（已有则复用）；没登录或做不到只提示，不挡安装和升级。
- 另提供只做加星和建副本、不再下载的 `support` 命令。用旧脚本第一次拉到本版时，读到新 Skill 后用发行根补跑即可。
- 安装和以后升级仍从官方地址进行，不从账号副本拉。Schema 保持 `1.1.1`。存量升级只合并这些说明和 Skill 正文。迁移项：`prepare-star-fork`。

## 1.1.6

- 新增对用户提问口径：用户听得见的问句、选项和一句解释用日常用语，先说要决定什么。脚本字段、覆盖报告枚举、四类整合内部标题保持原名。
- 接入预检、写入范围、升级确认、意图歧义、隔离工作区和记忆核验等门禁补了白话问句模板。问句里不再把内部工序词当主语。
- Schema 保持 `1.1.1`。存量升级只合并这些说明和 Skill 正文，不改业务文档、不重跑文档补全。迁移项：`plain-user-questions`。

## 1.1.5

- 用户入口只有 `ph-init`：说「初始化 PH」「安装 harness」「升级 PH」都先 prepare，再由本会话分流。已装且版本旧于发行根时，停 `init --apply` / `--adopt-plan`，同一会话按发行根 merge-update 步骤做完（inspect → 语义合并 → verify → finalize），不另开技能，不自动 finalize。
- 已装且已是发行根版本：不升级；检查 / 同步 / 续做文档走现有分支，同版重跑仍保留定制 canonical。仓内版本新于本包则 fail-closed，不降级。
- 内核仍是两套：`ph_init.py` 不调用 inspect / finalize，也不自动改版本；`ph-merge-update` Skill 与十个必需 Skill 清单保留，给会话当升级步骤用。
- Schema 保持 `1.1.1`。迁移项：`init-unified-entry`。

## 1.1.4

- 存量接入改为“已有内容优先”：会话盘点七类证据（模块、代码、配置、真实依赖、测试、CI、旧约束）后在目标仓外生成 `sources` 哈希快照与合并候选 plan，`init --adopt-plan` 核对哈希一致才落盘；候选只允许 canonical `.agents/AGENTS.md`（必需）与 `docs/**`，已有正文优先复用 / 引用登记，不复制第二套。
- adopt 仅用于尚无 `.agents/ph.json` 的目标；已安装仓库拒绝 adopt 并指向 `ph-merge-update`。已安装同版重跑 init 保留定制 canonical，不再冲突；未安装仓库 canonical 不一致仍阻断并提示 adopt 流程。`--mode` 缺省先读 manifest 声明再从适配层推断。
- 指引与导航：dry-run 输出按四类整合（直接落地 / 复用引用 / 冲突待裁决 / 不适用与保留）；旧文档目录（如 `docs/specs/`、`docs/domains/`、`docs/plans/`）按内容归并进三域，不留旧目录、空壳或软链，PH 固定入口摘要 + 深链指向归并后的正文，被引用旧规范保持效力。写入或移走旧文件前，原文先原样备份到 `.agents/archived/<日期>-pre-init/`，仓内快照即是可恢复原件，不再要求仓外原文备份；adopt 的 plan JSON 仍在目标仓外。
- 新增 `.agents/init-report.md` 覆盖报告：矩阵每个独立 id 一行（落点、仓内证据、结果、说明），结果枚举已核验 / 复用 / 不适用 / 待核实 / 冲突；PH 通用流程条目写采用声明。
- Schema 保持 `1.1.1`、十个必需 Skill；本批仅 Skill、内核与文档行为变化，无契约改动。迁移项：`adopt-plan-init` `adopt-existing-content` `init-report-coverage`。

## 1.1.3

- init 会话按真实代码和技术栈派发 subagent，结合实时官方资料补齐 Wiki、工程／前端／后端／测试规范，区分既有规则、事实、建议与待核实项。
- 安装内核保留已有安全普通 `docs/**` 文件，缺失才安装；非 docs 冲突与不安全路径仍阻断。check/sync 保持离线，不生成或覆盖文档。
- 按项目级 harness 内容清单扩充规范与 Wiki 模板，新增初始化补全、安全配置、构建发布运维三篇工程指引；不预装特定中间件，不造需求、决策或测试通过记录。
- merge-update 按段落补缺，保护既有项目文档及 subagent 产物，不因升版自动重建 Wiki。迁移项：`init-docs-workflow` `docs-guidance` `docs-project-preserve`。
- Schema 保持 `1.1.1`、十个必需 Skill；Wiki 同步／纠正／问答和记忆纠正只补文档流程，不新增 Skill 或定时任务。

## 1.1.2

- 意图生命周期取消 `已完成/` 状态：交付的意图留在 `实施/` 并在「记录」注明日期与结果；空模板的 `已完成/` 目录移除，存量 `已完成/` 条目迁入对应实施分类。
- 取消旧 `进行中/` 兼容状态：存量条目按是否已启动迁入待办或实施，空模板目录移除，Skill 与规范不再保留兼容分支。迁移项：`intent-no-completed` `intent-legacy-inprogress`。
- Schema 不变（仍为 `1.1.1`）：仅 Skill 与文档内容变化，无契约改动。

## 1.1.1

正式源：`https://github.com/chenweixuanJokes/ph-init.git`。`latest` 按稳定 tag 数值排序并固定 commit。

- Init：先 `scripts/ph_release.py prepare`，再执行该发行根的 `ph_init.py`。无 tag、网络失败或元数据不一致则阻断；不把本地 `assets/scaffold` 或 `main` 当成最新版。
- 新增第十个 Skill `ph-merge-update`：inspect 只读、Agent 按迁移链合并、verify / finalize 验收后才写项目版本。不在目标仓库 `git pull`。
- 意图 Skill 名：`capture/plan/abandon` → `new/impl/drop`（若项目仍是旧名）。
- 意图目录：新增 `待办/` 与 `实施/`；旧 `进行中/` 业务条目按需兼容，不批量改派。
- 发布元数据 `release.json`；迁移链见 [migrations/index.json](./migrations/index.json)。
- `build_scaffold.py` / `build_project_template.py` 仍是旧 monorepo 作者工具，不是本独立仓的发布源。

升级项：`intent-skill-names` `intent-lifecycle` `online-source` `merge-update` `schema-contract` `project-content`。从 1.0.0 出发还要做历史项 `intent-domain`。

## 1.1.0（历史，无 tag）

补录。同一版本锁下先后存在：

1. 九 Skill 旧名 `ph-intent-capture` / `ph-intent-plan` / `ph-intent-abandon`，意图目录仍为 `进行中/`。
2. 改名为 `ph-intent-new` / `ph-intent-impl` / `ph-intent-drop`。
3. 工作区已有待办/实施目录调整，版本锁仍可能是 `1.1.0`。

详见 [migrations/1.0.0-to-1.1.0.md](./migrations/1.0.0-to-1.1.0.md) 与 [migrations/1.1.0-to-1.1.1.md](./migrations/1.1.0-to-1.1.1.md)。

## 1.0.0（历史，无 tag）

六 Skill：`ph-init`、worktree 一对、memory 三个。意图只有 `进行中/`。`init` / `check` / `sync` 不是升级器。
