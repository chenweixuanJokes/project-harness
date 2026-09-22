# 本地 E2E 测试

> 触发：用户说「本地 e2e 测试」「按上次那套 e2e 跑一遍」或要求发布前做真实项目实测时，按本文执行。本文是**本仓维护者程序**，不进入下游 scaffold，也不装进用户项目。
>
> 定位：历史升级矩阵（`tests/test_historical_upgrade_matrix.py`，fixture 脚本链路）之外的真实项目实测——真实业务仓的临时副本、Agent 语义合并、产品自带网关与终态断言。矩阵证明脚本链路，本文证明「init / update 在真实存量项目上能生成预期终态」。

## 1. 原则与纪律

- **只在临时副本操作**：真实业务仓复制到 `/tmp` 工作区并 `git init` + 基线提交后再动手；真实仓绝不修改。真实仓的未提交改动随副本基线提交一起保全。
- **证据导向**：每步用产品自带命令验收（`inspect`、`verify-content`、`verify`、`finalize`、已装内核 `check`）；驱动脚本自写的断言只作补充。脚本通过不代替语义复核。
- **诚实门禁**：内容未补全时必须先演示 `verify-content` 拦截（保存失败输出），补全后再复跑通过；不编造测试实现、不把未执行命令标成通过、无该端如实写「不适用」。
- 禁用 `rm`：退役与清理一律 `mv` 到 `~/.Trash/` 或 `.agents/updates/<ver>/backup/`；禁用 `git stash`。提交遵循当次授权。
- **随包安装**：spec-kit 十技能与运行时由 PH 发行包自带（`assets/scaffold` + `assets/speckit-bundle.json` 哈希清单），安装与升级不访问官方 GitHub、不读 `~/.cache/ph/speckit/`、不运行 pip 或官方生成器。维护者按需引入上游的流程见 `references/Spec-Kit维护.md`。
- 失败必须修复后复跑到绿才算收敛；如实记录驱动侧修复与产品侧观察，不混淆两者。

## 2. 环境准备

1. **发行根**：测未发布的工作树时，在仓外目录 rsync 复制本仓（排除 `.git`、`.zcode`、`__pycache__`、`.DS_Store` 与根维护软链 `AGENTS.md`/`CLAUDE.md`），`git init` + commit + `tag v<版本>`，再对该副本运行 `python3 scripts/ph_release.py prepare --version latest --repo <目标仓>`；测已发布版本则直接对正式 tag prepare。记下返回的 `root/version/tag/commit`，全流程复用同一 root。
2. **发行包完整性**：`python3 scripts/check_release.py` 通过即覆盖随包清单与哈希校验；无需再核对 speckit 缓存目录。
3. **工作区**：`/tmp/ph-e2e-<日期>/` 下放发行根、各案例项目副本、驱动脚本与内容模块；用完即弃，方法以本文为准，不依赖那些脚本存续。

## 3. 案例矩阵

按本机 `~/projects` 实况选案，固定三类，B/C 必须覆盖 portable 与 symlink 两种适配模式：

| 案例 | 选取标准 | 首轮已验证实例 |
| --- | --- | --- |
| A 空白 init | 新建空 git 仓 | `blank-demo` |
| B 已完成初始化升级 | 距目标最近的旧版（首轮 1.1.15）；有真实定制文档、自定义技能、spec；任一适配模式 | `01-infra-service/annto-paas-cloud`（symlink） |
| C 未完成初始化升级 | 支持链内较早版本（首轮 1.1.9）；模板未填全、长迁移链、另一种适配模式 | `05-small-tools/metrology`（portable，13 篇 ADR、49 个意图文件） |

找案：`find ~/projects -maxdepth 4 -name ph.json -path '*/.agents/*'` 逐个读 `template_version`。版本演进后更新选案，保持「最近旧版 + 最早支持版 + 两种模式」的覆盖结构。

## 4. 案例流程

### 案例 A：空白项目 init

dry-run（断言零写入）→ `init --apply` → `ph_speckit.py install --apply` → `check` → `verify` → `verify-content`（断言**失败**：骨架态被拦，问题为占位符 + 无证据报告）→ 终态断言（24 篇基础树与发行模板逐字节一致、constraints 零 README、导航 24 条、骨架状态标记如实保留）。

### 案例 B/C：存量升级（两阶段驱动）

**prep（复制与合并）**：

1. rsync 复制目标仓（排除 `.git`、`node_modules`、`dist`、`.worktrees`、`.zcode`、`.DS_Store`、`__pycache__` 等）→ `git init` + 基线提交。
2. `ph_merge_update.py inspect --repo <副本>`：断言 `from`/`to`、适配模式、迁移链项数。
3. `ph_layout.preserve(repo, '<from>-to-<to>', roots)`：旧活动内容（docs 三域、`.agents/memory`、`.agents/archived`、`.agents/AGENTS.md`、`.agents/ph.json` 等）按哈希入 `archive/upgrades/<批次>/`，含 `inventory.json`。技能目录不入 preserve（旧字节由副本 git 历史与发行基线可恢复；自定义技能不动）。
4. 语义合并与家目录重组（要点见第 5 节）。
5. 旧活动入口退役：`docs/*`、`.specify`、根 `specs/`、`.agents/memory`、`.agents/archived` 等 `mv` 进 `.agents/updates/<to>/backup/retired/`；`docs/` 清空后整目录退役。

**finish（安装与网关）**：

6. `ph_speckit.py install --apply`（随包安装：十技能 + `runtime/` + 宪法 override + `ph.json` speckit 基准重建；不联网、不用官方缓存）。
7. `ph.json` re-key（canonical/memory 按 scaffold；保留 adapter_mode、适配层与 worktree 验证命令）。
8. 宪法物化（真实项目名、零占位符、PH 管理区 + 空导航占位）→ `refresh-navigation` 先 dry 后 `--apply`，断言条目数 = 基础树 + 项目新增 + 记录目录。
9. 迁移决定与证据报告：`verify_transplants` 通过后写 `project-harness/init-report.json`（`ph.content/1`，`project_kind=upgrade`，逐文件 sha256 + migration 决定）与 `.agents/init-report.md`。
10. `updates/<to>/{state.json,report.md}`：链上每项 applied/not_applicable + 证据；瞬态中间项（如已被后续版本退役的技能项）写明「由终态直接承接」。
11. 网关顺序：`verify-content` → `ph_merge_update.py verify` → `finalize`（dry）→ `finalize --apply` → 副本内已装内核 `ph_init.py check`。
12. 终态断言（见第 7 节）+ finalize 后复验（`verify-content` 零问题、state complete、版本与模式）。

**案例 C 追加**：骨架态先跑 `verify-content` 存档拦截输出；`retire-legacy-skills`（canonical 与 `.claude` 镜像先备份再退役）；`migrate-intents` dry + `--apply`；≤1.1.13 长链注意账本存续口径（见第 6 节）。

## 5. 语义合并要点

- 逐篇读旧正文，不能只比文件名或复制新模板。旧单篇规范按 1.2.1 终态拆分承接（如旧《前端规范》→ 技术/样式/自测/构建四篇）；模板占位按仓库真实事实（构建文件、CI 工作流、测试目录、ADR）补齐；某端不存在时如实写「不适用」并说明启用条件。
- 链接重写程序化：建「旧仓库相对路径 → 新路径」映射表（exact + 前缀），按文件新位置重算相对链接；映射不到且目标已退役的，登记真实承接位置或删除。`verify-content` 兜底全部链接可解析。
- constraints 内最终零 README（目录索引解散进正文或由宪法导航承担）、零占位符、每篇 `使用时机：`；测试工具与脚本类资源（安装说明、模拟登录工具、样板）进 `documents/`；记录目录（`架构决策/`、两端测试用例/）内容逐字节保留且不进证据表。
- 迁移决定覆盖 preserve 清单**每个文件**：`moved`（字节相同）/ `merged`（改写承接）/ `replaced`（基础树承接）/ `historical`（退役，必写理由）；archive/ 路径不可作活动落点；`ph.json` 因 finalize 会再次改写，只作 historical。
- `.agents/AGENTS.md` 换 scaffold 精简入口；ph-init 载荷整目录换发行字节（旧载荷 `mv` 入备份）；A13 篇 ADR 类记录进 `constraints/架构决策/`。
- 旧 AGENTS.md 的有效规则（环境模型、启动参数、门禁摘要等）逐节并入对应约束正文，不得以「原件已归档」代替移植。

## 6. 已知坑（首轮实测沉淀，复跑时先对照）

- **便携模式镜像**：更新 canonical 技能后，必须先备份退役 `.claude/skills` 下的旧实体镜像，finalize 的 sync 才能重建；否则以「portable skill mirror has unmanaged extra files」fail-closed。
- **≤1.1.13 长链意图**：`migrate-intents` 账本必须存留 `project-harness/specs/.ph-intent-ledger.json`（verify 要求）；`docs/意图` 原件按**原相对路径**进 `legacy-backup`（校验靠它解析）；重跑 `migrate-intents` 会在原路径再生 `docs/意图/历史索引.md`，需先归并进归档再退役。≥1.1.14 链的历史账本则退役。
- **旧文档失效链接**：承接时可能遇到旧文自身指错层级的链接，映射表要为其登记真实承接位置，不能机械重算。
- **驱动幂等**：复跑驱动脚本时，旧路径读取统一走「活树优先、退役后读 `backup/retired`」封装；会再生的产物（历史索引）与会被占用的备份目标都要有守卫；占位符扫描必须在覆盖模板的承接步骤**之后**执行。
- **schema/清单**：`.agents/ph.schema.json` 换 scaffold 字节；re-key 只动 canonical/memory，保留 adapter 与 worktree 配置。

## 7. 产出与验收

- 每案例收敛标准：产品网关全绿 + 独立终态断言通过（版本 = 目标、无 `schema_version`、适配模式保留、24 篇基础树齐、导航与磁盘集合精确一致、旧布局彻底退役、迁移字节保全、自定义技能与用户内容未动）+ finalize 后复验全绿。
- 汇总报告写本仓 `.zcode/E2E报告-<日期>.md`（或并入当轮验收报告），含：三案例结论、驱动侧修复记录、产品侧观察（区分「非阻断改进建议」与「缺陷」）。
- 发现产品缺陷按 [版本与合并升级](./版本与合并升级.md) 处置（修复、递增版本、补迁移说明与矩阵）；文档改进建议记录待用户裁决。测试失败不得当作已验收。
