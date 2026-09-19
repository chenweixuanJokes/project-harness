---
name: ph-merge-update
description: "已装 PH 项目升到正式发行版的步骤：从唯一 GitHub 源准备固定 tag/commit，按迁移链审阅合并，验收后再推进项目版本。本文件不按普通描述触发：用户点名 ph-init 并请求升级已装项目时，由 ph-init 会话读本文件作为该次升级的内部步骤执行；用户当轮明确点名 ph-merge-update 并要求使用时，也由同一会话按本文件执行。只说“升级 PH”“安装 harness”、上下文提及或讨论名称不触发。已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。不要把未初始化仓库的安装、普通 check/sync、git pull、或 worktree 误判为本文件的步骤。"
---

# ph-merge-update

已接入 PH 的仓库跟官方发行版对齐。这是 **`ph-init` 会话**在已装旧版上要执行的步骤：用户点名 `ph-init` 并请求升级时，本会话读本文件作为该次升级的内部步骤执行；用户当轮点名本文件并要求使用时同样执行。Agent 按迁移说明做语义合并；脚本只读状态、验收结构和收尾。不要用 `init --apply` 覆盖定制，不要在目标仓库 `git pull`。

旧项目可以没有本目录。从准备好的发行根读取：

`assets/scaffold/.agents/skills/ph-merge-update/SKILL.md`

然后由当前 `ph-init` 会话按该副本执行。

## 何时用 / 何时不用

使用：项目已有 `.agents/ph.json` 与 `.agents/AGENTS.md`，用户要升到正式版或恢复未完成升级。用户即使说的是「初始化 / 安装」，已装旧版也走本文件步骤。

不用：

- 空仓库或尚未接入 PH：仍由 `ph-init` 走安装 / adopt，本文件只描述已装升级步骤
- 只检查 / 同步适配层：项目已装的 `ph-init` `check` / `sync`
- 目标仓库拉远端、提交、推送、改可见性
- 记忆、worktree、录入 / 实施 / 废弃意图

## 来源与命令

唯一源：`https://github.com/chenweixuanJokes/project-harness.git`。官方仓库由 `ph-init` 更名而来：旧地址 `https://github.com/chenweixuanJokes/ph-init.git` 经 GitHub 重定向指向同一仓库，1.1.8 及以后入口按旧地址 prepare 取到新包不是错误；`FIXED_SOURCE` 等固定标识与 `release.json.repository`、`receipt.source`、`state.source.repository` 在 1.x 保留旧地址的兼容含义，存量值不改写、不当作错误。`latest` = 数值最大的稳定 tag（排除预发布与非版本标签），并固定到该 tag 的 commit。无 tag、网络失败、tag/commit/元数据不一致则停止；不拿本地 `assets/scaffold` 或 `main` 冒充最新。本版起 PH 只有单一版本号：发行包与项目清单都不再携带 `schema_version`，schema 标识固定为无版本的 `urn:ph:schema:project-harness`。

准备（下载在目标仓库外）：

```text
python3 <ph-init-root>/scripts/ph_release.py prepare --version latest|1.1.14 --repo <target>
```

stdout JSON 字段：`root` `version` `tag` `commit` `source`。`source` 是固定仓库 URL 字符串（1.x 仍为旧地址，保留兼容含义，不改写、不当错误）。本地已有该 commit 的检查不访问网络。准备成功后把脚本提示转告用户；没登录不拦升级。本会话刚用旧脚本 prepare 时，用发行根补跑 `python3 <release-root>/scripts/ph_release.py support`，不必为了加星再下一遍包。检查 / 同步仍然离线，不重新 prepare，也不为了加星上网。安装和以后升级仍从官方地址进行。

**一次性入口切换**：旧版（1.1.7 及更早）用户级入口的 prepare 必查发行元数据里的 `schema_version`，会必然拒绝 1.1.8 及以后发行包；这是预期现象，不重试、不回退、不假称自动恢复。把首个无独立 Schema 版本的已发布标签 v1.1.8 clone 到一个**新的仓外安全目录**（如 `mktemp -d` 创建），不覆盖用户级入口与目标项目，不用 `main` 或本地开发树冒充发行；先在该目录运行 `python3 <新目录>/scripts/ph_release.py prepare --version 1.1.8` 并读取返回根的 Skill，再用这份新工具准备并固定后续发行根。**1.1.8-1.1.13 入口无法直接准备 1.1.14**（1.1.14 起必需技能名单拆为 4 个 scaffold 技能加 10 个安装期生成的规格驱动技能，旧校验器按 manifest 与 `required_skills` 全等校验会以 skills.required_names mismatch 拒绝；这是设计使然，不要绕过）：把 v1.1.14 标签本身 clone 到新的仓外安全目录，运行该目录的 `python3 <clone>/scripts/ph_release.py prepare --version 1.1.14 --repo <target>`（其自带校验器验证本版发行并写入 receipt），再用返回根执行升级。之后本文件全部升级命令都使用 1.1.14 prepare 返回的根，不再用旧目录或中间发行根冒充最终目标。

同一次预检与写入复用这个 `root`。读该 root 的本 Skill 与 `migrations/`。升级工具在发行根，不在目标旧包：

```text
python3 <release-root>/scripts/ph_merge_update.py inspect --repo <target>
python3 <release-root>/scripts/ph_merge_update.py verify --repo <target>
python3 <release-root>/scripts/ph_merge_update.py finalize [--apply] --repo <target>
```

`inspect` 只读，不走会提前拒绝旧版本的 `load_repo_manifest()`。`finalize` 才按原 adapter mode 同步候选适配层并在验收通过后写版本。默认 dry-run；用户明确要求写入才 `--apply`。

禁止：目标仓库 `git pull`、自动 `git commit` / `push`、`rm`（退役文件移 `~/trash/` 或 `.agents/updates/<ver>/backup/`）。

## 进度文件

`.agents/updates/<to_version>/state.json` 与同目录 `report.md`。`state.json`：

```json
{
  "from_version": "1.1.2",
  "to_version": "1.1.3",
  "source": {
    "repository": "https://github.com/chenweixuanJokes/ph-init.git",
    "tag": "v1.1.3",
    "commit": "<40-hex>"
  },
  "status": "in_progress",
  "items": [
    {
      "id": "init-docs-workflow",
      "status": "pending",
      "evidence": ""
    },
    {
      "id": "docs-guidance",
      "status": "pending",
      "evidence": ""
    },
    {
      "id": "docs-project-preserve",
      "status": "pending",
      "evidence": ""
    }
  ]
}
```

`status` 仅 `in_progress` | `complete`。每项 `id` 与迁移 `items` 一致；项状态仅 `pending` | `applied` | `not_applicable` | `blocked`；`evidence` 为字符串。链上每一跳的项都要出现（从 1.0.0 出发须含 `intent-domain`）。

`report.md` 写实际差异、保留内容、验证证据、未解决项；不含凭证或个人敏感信息。脚本成功 ≠ 语义合并正确。

## 工作流

1. **确认**。已初始化才继续。未初始化回到 `ph-init` 的安装 / adopt，不要在本步骤里装新仓。核实目标版本（默认 `latest`）与已有授权，不重复询问已经明确的选择。用户尚未决定是否启动升级时，实际询问“现在开始检查升级差异吗？”，选项为“检查差异，写入前确认范围（推荐）”与“暂不启动升级”；用户已要求升级时直接准备和检查，写入仍按后续流程确认具体范围。提问方式见 [对用户提问](../../../docs/约束规范/工程规范/对用户提问.md#把问题写成可回答的决定)，不提供绕过合并检查或必要审批的“直接写入”选项。
2. **准备发行根**。对目标跑 `prepare`（`ph-init` 会话通常已经做过，复用同一 `root`）。失败则停。记下 `root/version/tag/commit`。
3. **只读 inspect**。结合 manifest、真实 Skill 目录名、意图目录判定布局。可核实历史：
   - `1.0.0` 六 Skill，意图在 `进行中/`
   - `1.1.0` 旧名：`ph-intent-capture` / `plan` / `abandon`
   - `1.1.0` 新名：`ph-intent-new` / `impl` / `drop`，目录可能仍是 `进行中/`
   - 工作区已有 `待办/` `实施/`，版本锁仍可能是 `1.1.0`
   不能因 `template_version=1.1.0` 猜是哪一套。未知布局或缺迁移记录则阻断。
4. **建或恢复清单**。读 `<release-root>/migrations/index.json` 与从 `from_version` 到目标的说明。已有 `state.json` 时对照文件实态：已落地不重做、不重复插入章节。版本已写成目标但 `report` / 项未完成 → 继续验收，不跳过。
5. **按项合并**（用户确认后才写盘）。框架资产更新到目标态。涉及 spec-kit 的迁移项（安装十技能、刷新宪法管理区）由发行根 `scripts/ph_speckit.py` 执行（`install` / `constitution`，先 dry-run 再 `--apply`；获取失败即停止整次升级、记录状态可重试，不推进版本）。AGENTS、规范、README 按段落合并，保留已填项目事实。唯一例外：迁移说明授权整文件覆盖的文件（当前为 1.1.12 `question-execution-contract` 的《对用户提问》）按该授权先备份旧原文再整文件替换，不走段落合并。业务文档只做迁移要求的调整，不改访谈原话、历史代码块、业务编号、无关 Wiki/记忆。init 会话中 subagent 生成的文档同样属于项目定制；不因升级重新生成 Wiki、全网调研或替换技术栈。新指引补缺与项目正文分开审阅，只有另行授权补全时才执行扩展调研。旧意图目录按完整链的最终迁移要求处理，不能仅按旧模板猜业务状态。
6. **冲突**。与项目显式规则或本地定制相反 → 该项 `blocked`，停受影响写入，请用户决定。对用户说明“升级在这一项停住了”以及双方约定，问怎么处理；不要把项编号或内部状态名念给用户。旧 Skill 重命名退役须审阅备份；有定制不静默删。根 AGENTS 在而 canonical 不在、仓外软链、嵌套 symlink/junction、受跟踪 `.worktrees/`：fail-closed。
7. **verify**。项无 `pending`/`blocked`，必需 Skill 清单与目录实态符合目标，`report.md` 完整。不通过不 finalize。
8. **finalize**。先 dry-run。用户确认后 `--apply`：对用户问“差异已经看过了，现在可以按这些改动写入吗”，不要问内部收尾命令。同步候选适配层（不改 mode），candidate check 通过前不改磁盘 `ph.json` 版本；通过后再写 `template_version` 并移除旧的 `schema_version` 字段（本版起不再有该键），再跑常规 `check`。新 schema 与自包含运行脚本须在第 5 步合并完成，verify 前已在磁盘上；finalize 不替换这些文件。失败保持 `in_progress`，不宣称完成。

更新项目内 `ph-init` payload 用本次 `release-root`，保留该副本上的项目定制。`check` / `sync` 用项目已装内核，离线，不重新 `prepare`。

## 1.1.1 项（按实态勾）

完整条文读 `<release-root>/migrations/1.1.0-to-1.1.1.md`；从 1.0.0 出发先读 `<release-root>/migrations/1.0.0-to-1.1.0.md`。索引是 `<release-root>/migrations/index.json`。

| id | 做完的样子 |
| --- | --- |
| `intent-domain` | 已有意图三 Skill（旧名或新名）及意图与访谈规范；否则从六 Skill 补齐。已有则 `not_applicable` |
| `intent-skill-names` | 目录与入口为 `new/impl/drop`；旧名已备份退役 |
| `intent-lifecycle` | 存在 `待办/` `实施/` 及 README；导航已改。不搬业务 `进行中/` |
| `online-source` | 项目内 ph-init 入口改为 prepare → 该 root 的 init；失败阻断写清楚 |
| `merge-update` | 本 Skill 已安装；`.agents/updates/<ver>/` 有 state/report |
| `schema-contract` | 目标契约十 Skill / Schema 1.1.1；版本字段只在 finalize 后写 |
| `project-content` | 混合文件已合并 PH 入口；项目事实仍在 |

## 1.1.2 意图状态项

读 `<release-root>/migrations/1.1.1-to-1.1.2.md`。`intent-no-completed` 将存量已完成条目保留结果记录后迁入对应实施分类；`intent-legacy-inprogress` 按真实启动情况处理旧进行中条目，不凭目录猜业务状态。信息不足则 blocked，不能跳过这两项而只勾前后版本表。

## 1.1.3 文档补全项

完整条文读 `<release-root>/migrations/1.1.2-to-1.1.3.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `init-docs-workflow` | 项目已装 ph-init 包携带新工作流、保留同名 docs 的内核与完整指导材料；check/sync 不生成文档 |
| `docs-guidance` | 新增工程指导、各端／测试细节及索引按段落补缺；已拆专文的等价落点有证据，不复制规则 |
| `docs-project-preserve` | 已审阅并记录项目正文、用例、核验历史与定制保留证据；未授权的全文补全只记录缺口，不执行 |

项目资料仍有占位不阻止这次指导升级，但不能把“升级完成”说成“文档补全完成”。发生规则冲突则对应项 blocked，不 finalize。重复执行先读磁盘与进度，已有章节不重复追加。

## 1.1.6 提问口径项

读 `<release-root>/migrations/1.1.5-to-1.1.6.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `plain-user-questions` | 已合并对用户提问口径与各门禁白话问句；报告字段、脚本命令和项目已填正文仍保留。未因本项重跑文档补全 |

向用户确认升级或冲突时按 [对用户提问](../../../docs/约束规范/工程规范/对用户提问.md) 的“把问题写成可回答的决定”发问，不要把项编号念给用户。

## 1.1.7 准备附加项

读 `<release-root>/migrations/1.1.6-to-1.1.7.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `prepare-star-fork` | 已合并准备成功后的加星 / 建副本说明；下载源仍是官方地址；检查 / 同步不为此上网。旧脚本第一次拉到本版时已用发行根补跑 `support`，或已记录本机未登录 |

向用户只转告脚本里的白话提示，不要把内部命令名当问句。

## 1.1.8 单一版本项

读 `<release-root>/migrations/1.1.7-to-1.1.8.md`，从更早版本出发仍须读完整链。旧 `schema-contract` 项中的中间格式以本项最终格式为准，不再写回 `schema_version` 或带版本的 `$id`。

| id | 做完的样子 |
| --- | --- |
| `single-ph-version` | 已合并单一版本口径与一次性入口切换说明；升级使用经过固定来源校验的无独立 Schema 版本发行根，旧入口未被覆盖；finalize 通过后项目清单不再含 `schema_version`，`template_version` 写当前目标版本，schema `$id` 为无版本的 `urn:ph:schema:project-harness`；业务正文与未完成记录仍保留 |

旧入口拒绝新包时，如实说明下载未完成、尚未升级项目；说明需要取得新版工具，再按授权范围处理。不得把旧工具的失败说成已经完成入口切换。

## 1.1.9 worktree 默认决策项

读 `<release-root>/migrations/1.1.8-to-1.1.9.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `worktree-auto-branch` | `ph-worktree-enter` 和项目并行开发规则已明确：来源取主工作区当前分支，任务分支由代理依据任务语义和项目规则自行确定；用户明确要求创建后，正常计划不再二次询问，异常安全门禁仍保留。项目自己的分支命名、验证命令与本地定制未被整文件覆盖 |

## 1.1.9 工具中立适配项

同样读取 `<release-root>/migrations/1.1.8-to-1.1.9.md` 的 `tool-neutral-adapters`。Codex 与 OpenCode 直接读取根 `AGENTS.md` 和 `.agents/skills`；Claude Code 保留 `CLAUDE.md` 与 `.claude/skills` 入口，不新建其他镜像。

合并前核对旧 `.codex/skills/ph-*` 是否为受管链接或镜像，并保存内容摘要。`inspect` / `verify` 只读分类；可证明受管的条目由 `finalize --apply` 归档到 `.agents/archived/<日期>-pre-update/codex-skills/`，软链接保存原目标记录，普通镜像完整移动。内容漂移或证据不足时停止，不凭名称归档；语义合并阶段需要处置的项目定制须先审阅并保留原文。非 `ph-*` 技能及其他配置不动。

finalize 成功后清单删除 `adapters.codex_skills`，普通 check 不得再发现活动的旧 PH 入口。自动归档结果保存在升级 state 的 `retired_codex` 中；中断后复用原记录，不能覆盖不同内容的归档。项目原来的 portable / symlink 模式不变，`auto` 只用于未锁定模式的新安装。

## 1.1.9 仓库更名项

同样读取 `<release-root>/migrations/1.1.8-to-1.1.9.md` 的 `repository-rename`。官方仓库由 `ph-init` 更名为 `project-harness`，产品名 Project Harness；技能名与安装路径不随仓库名变化，仍是 `ph-init` 与 `ph-*`，不迁移用户级入口、不重建技能目录。

合并新 Skill 中的官方源说明，正式链接指向新仓库；项目文档如有引用官方源地址，一并更新为新地址。`receipt.source`、state 的 `source.repository`、`release.json.repository` 在 1.x 保留旧地址的兼容含义，存量值不改写、不当作错误；已发布迁移说明与历史升级记录中的旧地址保持原样。1.1.8 及以后入口按旧地址 prepare 也能取到新包，不是错误。

## 1.1.10 文档同步 Skill 项

读 `<release-root>/migrations/1.1.9-to-1.1.10.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `docs-sync-skill` | 新必需 Skill `ph-docs-sync` 已从发行根安装到 `.agents/skills/ph-docs-sync/`；`.agents/AGENTS.md` 技能表与 `docs/约束规范/工程规范/文档治理.md` §6、`初始化与文档补全.md` 的规则索引已合并指向该 Skill；**本项不自动同步任何业务文档**（README / docs / Wiki 的核验修复由用户另行发起 `ph-docs-sync`）；项目定制与 adapter mode 保留 |

合并前核对 `.agents/skills/ph-docs-sync/`：旧版（1.1.9 及更早）不携带该 Skill，若项目已有**同名自定义 Skill**，本项 `blocked`，保留原件并请用户决定（改名保留或替换为官方版），不得覆盖；项目规则明确禁止自动修正文档或禁止新增 ph-* Skill 时同样 `blocked`。形态规整的同名目录由 `inspect` 列入冲突清单；无 `SKILL.md` 或含软链等异常形态会先被结构校验直接拒绝，两种路径都 fail-closed。

## 1.1.11 分支默认项

读 `<release-root>/migrations/1.1.10-to-1.1.11.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `current-branch-defaults` | `ph-intent-impl` 与 `ph-worktree-enter` 已合并分支与工作区默认规则：启动意图或批准计划不授权新建、切换分支或创建 worktree；worktree 从主工作区当前所在分支的 HEAD 检出，不自动改用 main/master/develop 或远端默认分支。已有分支和 worktree 未被改动 |

## 1.1.11 指引命令示例项

同样读取 `<release-root>/migrations/1.1.10-to-1.1.11.md` 的 `adopt-mode-docs`。`docs/约束规范/工程规范/初始化与文档补全.md` §3.4 adopt 安装命令示例的 `--mode` 选项已包含 `auto`，与 1.1.9 起的新装缺省一致；该文档已有项目定制按段落合并，只改这一行示例。

## 1.1.12 提问执行契约项

读 `<release-root>/migrations/1.1.11-to-1.1.12.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `question-execution-contract` | `docs/约束规范/工程规范/对用户提问.md` 已按执行契约组织（何时需要用户决定、通过正确通道实际提问、把问题写成可回答的决定、根据真实回答推进、纠正失误与恢复中断、边界示例、完成检查），旧编号章节与固定句库不再保留；该文件本身由发行根副本整文件覆盖，与发行根逐字节一致，文件内旧定制不留为生效规则，旧原文已备份；引用该文的规范文档、`.agents/memory/README.md`、`.agents/AGENTS.md` 提问摘要节与各 Skill 门禁句已改为不锚定章节号的语义引用。报告字段、脚本命令、已填项目正文与既有授权结论仍保留，未因本项重问已决定的事 |

该文件适用本版覆盖策略：不按段落语义合并、不保留文件内旧话术或项目定制，直接用发行根副本整文件替换（逐字节一致）；替换前旧原文移入 `~/trash/` 或 `.agents/updates/<ver>/backup/` 备份（现行退役备份机制，禁止 `rm`），重试时文件已是目标内容则不再重复备份、不改动备份原件。软链与非普通文件照常拒绝，写入仍在本 Skill 的用户确认范围内。该文件内的旧提问定制因此不作为仍生效的冲突规则；其他文件中与契约相反的显式规则（如禁止宿主问答工具）仍按冲突规则 `blocked` 并请用户决定。引用该文的语义更新照常进行。向用户确认升级或冲突时按该契约选择通道与问法，不要把项编号念给用户。

## 1.1.13 调用门禁与新技能项

读 `<release-root>/migrations/1.1.12-to-1.1.13.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `explicit-invocation-rules` | 十一个既有 Skill（根 `ph-init` 与 scaffold 十个）的 `description` 与正文已合并调用门禁：仅当用户当轮明确点名该技能并要求使用时才调用，普通描述、上下文提及与讨论名称不触发；“只要用户说…就必须使用”“即使没点名”一类描述即触发语句已清除；跨技能自动串联（如进入 worktree 自动调用退出技能）已改为由用户点名，`ph-init` 会话执行已请求升级所需内部步骤与参考文档的说明保留。`.agents/AGENTS.md` 技能表上方与 `docs/约束规范/工程规范/意图与访谈.md`、`docs/意图/_模板.md`、`Git与并行开发.md` 的技能入口表述同步。各 Skill 行为样例补触发正反例。项目对 Skill 正文的已有定制按段落合并保留 |
| `intent-verify-skill` | 新必需 Skill `ph-intent-verify` 已从发行根安装到 `.agents/skills/ph-intent-verify/`（SKILL.md 与 evals）；`.agents/AGENTS.md` 技能表与 `docs/约束规范/工程规范/意图与访谈.md` 已登记第十二行；本项自身不迁移业务意图、不新增意图状态、目录或纪要 purpose（存量业务意图的 Spec 迁移由 1.1.14 `intent-to-spec` 负责）。安装证据记录在 state 项 |

合并前核对 `.agents/skills/ph-intent-verify/`：旧版（1.1.12 及更早）不携带该 Skill，若项目已有**同名自定义 Skill**，本项 `blocked`，保留原件并请用户决定（改名保留或替换为官方版），不得覆盖；项目规则明确禁止新增 ph-* Skill 时同样 `blocked`。形态规整的同名目录由 `inspect` 列入冲突清单；无 `SKILL.md` 或含软链等异常形态会先被结构校验直接拒绝，两种路径都 fail-closed。`explicit-invocation-rules` 与项目显式规则相反（如项目要求按普通描述自动触发某 Skill）时该项 `blocked`，交用户裁决。

## 1.1.14 worktree WIP 统一确认项

读 `<release-root>/migrations/1.1.13-to-1.1.14.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `worktree-wip-confirm` | `ph-worktree-enter` 与 `ph-worktree-exit` 已合并统一 WIP 确认：进入源树、退出任务树、合并目标源树因未提交改动实际阻断时，先只读 dry-run 列明目录、当前分支、staged / unstaged / untracked 完整清单与拟用 `wip: <说明>` 提交信息（用于说明现场与安全筛查结果），再实际调用问答工具提出固定问句，两个选项字面为"是""否"；确认问的是是否采用 `wip:` 提交解决当前这次阻断，不是对文件内容的逐项审批；答"是"授权本次组合调用：受确认的 WIP 提交与后续动作（创建隔离工作区 / 继续交付）在单次 `enter --apply` / `exit --apply` 内由运行时脚本一次完成，`--wip-message` 连同绑定 dry-run 快照的各 `--expect-*`（enter：`--expect-source-branch`、`--expect-source-head`、`--expect-staged`、`--expect-unstaged`、`--expect-untracked`；exit：`--expect-branch`、`--expect-head` 与同三组路径集合）一起传入，缺任一绑定或分支、HEAD、改动路径/状态集合与 dry-run 不一致时整单拒绝并重新预检，技能流程不拆成"先 wip 再进入 / 退出"两次调用，独立 `wip` 子命令保留给用户直接使用；拒绝、取消或未回答保留改动并停止，同一已展示路径的普通内容修改不重问（不逐字节比对文件内容）；分支、HEAD 或拟提交路径/状态集合变化（新增、删除或状态转移）时阻断并重新预检、重新确认，不沿用已消费的确认覆盖新变更，授权不是长期授权（提交一经执行授权即消费，新阻断按当时现场重新确认）；WIP 确认只覆盖这次 `wip:` 提交，仅调用退出技能不构成提交确认，用户单独指定的正式提交仍按指定执行。`ph-worktree-exit` 不再按 staged / unstaged 分级默认普通提交；staged / unstaged / untracked 一起收进，ignored 排除，疑似密钥、异常大文件与未解决冲突整单拒绝、不部分提交，不盲目 `git add -A`；脚本无能力证明真实用户确认，人类确认由 Skill 流程在调用 `--apply` 前完成。运行时同步扩展：`exit` 不再接收提交信息（兼容接受旧 `--message` 但绝不据此提交），`exit` dry-run 只读报告合并目标源工作区脏状态（`sourceDirty`），`enter` dry-run 报告 `sourceDirty` / `wipPlanned` / `wipRisks`，新增只读 `doctor`、显式 `recover`（archive / adopt，目标与操作由用户显式指定）与 `redeliver`（仅 `committed` / `merge_verify_failed` 且任务分支出现新提交，先核验再交付）。合并冲突恢复并入同一套机制：冲突态优先于 WIP 流程，先只读确认 `MERGE_HEAD` 与未合并条目并列明冲突清单、依据合并快照（`mergeSourceBranch` / `mergeSourceHead` / `mergeTaskHead`）核对 merge 身份，再实际调用问答工具按固定冲突问句（`Git与并行开发.md` 第 4 节，只替换目录、任务分支、源分支、清单四个变量）问"保留现场，我解决后继续""撤销这次合并"，不添加 stash、丢弃、一键选 ours/theirs、Agent 代解决等其他预设选项；保留现场即停止等待不轮询，用户明确"已解决并暂存，请继续"且只读核验无未合并条目、merge 身份与 session 吻合才 `continue`，撤销是仅本次 `abort-merge` 的单独授权，取消或未回答不 abort、不做 WIP、不换问法重问；冲突解决后 `continue` 生成的是合并提交不是 WIP，清理另行确认；陌生 merge 与旧 session 缺少新增证据时保守阻断，不猜测补齐，用只读 doctor 诊断、显式 recover 恢复，recover 不能恢复所有旧 merge。`docs/约束规范/工程规范/Git与并行开发.md` 的 WIP 两段与冲突固定问句段同步；两个 Skill 的 evals 补统一确认、运行时恢复与冲突恢复正反例。worktree 运行时脚本已被本项替换 |

合并前核对 worktree 运行时脚本：本项把 `.agents/skills/ph-worktree-enter/scripts/ph_worktree.py` 与 `.agents/skills/ph-worktree-exit/scripts/ph_worktree.py` 退役（先备份），改为共享脚本 `.agents/scripts/ph_worktree.py`（与发行根逐字节一致），两个 worktree 技能正文改为引用共享脚本路径；脚本新增 `wip`（五绑定）/ `doctor` / `recover` / `redeliver` 子命令，`enter` / `exit` 的 `--apply` 单次调用内完成受确认 WIP 提交与创建 / 交付并强制绑定预检快照；`.worktrees/.ph/sessions/` 现有 session 文件不被迁移读取改写或删除，session 新增字段非必填，旧 session 由新脚本只读兼容读取、缺少新增证据时保守阻断。项目显式规则与本项相反（如要求脏工作区静默提交、不问即 `git add -A`、把调用脚本当作真实用户确认、要求合并冲突自动选 ours/theirs、或把"冲突已解决"口头结论当作 continue 授权）时该项 `blocked`，交用户裁决。已获用户明确确认的既有 WIP 授权与清理决定不因本项重问。

## 1.1.14 退役技能项

读 `<release-root>/migrations/1.1.13-to-1.1.14.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `retire-legacy-skills` | 旧受管技能 `ph-memory-capture`、`ph-memory-archive`、`ph-memory-ask`、`ph-intent-new`、`ph-intent-impl`、`ph-intent-verify`、`ph-intent-drop`、`ph-docs-sync`（及未正式发布的 `ph-sure` 残留）已从 `.agents/skills/` 与 `.claude/skills/` 镜像移除并先备份到 `.agents/updates/<ver>/backup/`（退役原文快照）；`.codex/skills/` 下可证明为受管副本的同名镜像在同一退役步骤内一并归档（退役后 canonical 消失会使 1.1.9 机制的镜像证明失效；证明不成立的镜像保持原样交用户裁决）；项目自定义内容、与 PH 发行版字节不一致的定制正文、`docs/意图/`、`.agents/memory/` 与业务 docs 全部原样保留；`.agents/AGENTS.md` 技能表已按目标态重写（四个 PH 技能 + 十个上游技能）。未审阅的内容先备份后移除，报告列明，不静默丢弃 |

合并前核对每个退役技能目录：内容与旧发行版一致的按受管退役处理；与发行版不一致（用户改过）的同样先备份再退役，但差异摘要要写进 `report.md`；同目录出现发行版不认识的自定义文件时备份整个目录并报告。用户显式要求保留某个退役技能目录为自定义技能时，该项按冲突处理（`blocked` 或用户明确豁免后 `not_applicable` 记录豁免证据），不得覆盖。

## 1.1.14 spec-kit 集成项

读 `<release-root>/migrations/1.1.13-to-1.1.14.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `speckit-core-integration` | 十个规格驱动技能 `ph-analyze`、`ph-checklist`、`ph-clarify`、`ph-constitution`、`ph-converge`、`ph-implement`、`ph-plan`、`ph-specify`、`ph-tasks`、`ph-taskstoissues` 已由发行根 `scripts/ph_speckit.py install --apply` 从发行根 `speckit.json` 契约（顶层独立文件，不进 `release.json`，保证 1.1.8-1.1.13 历史入口仍能准备本版）固定的 GitHub Spec Kit 正式 tag+commit 用官方生成器安装（隔离暂存生成，统一改 `ph-` 前缀，`.specify` 目录保持上游名，frontmatter `x-ph-upstream` 与 `.agents/ph.json` 的 `speckit` 节记录来源映射）；`.claude/skills` 镜像同步；`.specify/memory/constitution.md` 已有内容原样保留。同目录已存在的**同名自定义技能**使本项 `blocked`（保留原件、请用户决定），不覆盖。安装或获取失败时整次升级停止、不推进版本，状态可重试。项目显式规则明确禁止安装上游技能时 `blocked`，交用户裁决 |
| `constitution-governance-zone` | `.specify/templates/overrides/constitution-template.md` 已由 `ph_speckit.py constitution --apply` 生成或刷新：上游项目覆盖机制（优先级最高、replace 策略）使 `ph-constitution` 技能后续更新宪法时保留 PH 约定；管理区逐篇引用 `docs/约束规范` 实际文档（相对链接 `../../docs/...` 按物化深度有效），每篇带适用范围与阅读时机（从目录索引或正文提取），识别不了的明确标“待确认”，不复制规范正文、不含 Wiki 空模板与维护者规则；该文件已存在的用户自定义覆盖使本项 `blocked`，不覆盖。`.specify/memory/constitution.md` 的用户原则正文不动 |

## 1.1.14 旧意图迁移 Spec 项

读 `<release-root>/migrations/1.1.13-to-1.1.14.md`，从更早版本出发仍须读完整链。

| id | 做完的样子 |
| --- | --- |
| `intent-to-spec` | 旧意图机制升级为 Spec：`specs/.ph-intent-ledger.json` 已由发行根 `ph_merge_update.py migrate-intents --repo <仓库> --apply` 生成（schema `ph.intent-ledger/1`），`docs/意图/待办/`、`实施/`（兼容早期 `进行中/`、`已完成/`）每个条目有 `specs/intent-<intent_id>/spec.md`——只逐字摘录旧模板目标 / 范围 / 约束 / 验收四节，缺失或空节标 NEEDS CLARIFICATION，不编造优先级 / 技术方案 / 成功指标，不生成 plan / tasks；解析保真（重复同名小节全部保留、代码围栏内 `##` 不算小节），头部记录来源路径、原 intent_id、源内容 sha256 与 status_dir；已废弃与访谈纪要条目只在 `docs/意图/历史索引.md` 登记历史、不重开；`docs/意图/` 全部原有文件字节不动，转为只读历史，历史索引声明 Spec 是唯一后续维护位置并写明 select-intent-spec / SPECIFY_FEATURE_DIRECTORY 的选择方式（select 命令指向项目内真实路径 `.agents/skills/ph-init/scripts/ph_merge_update.py`）；重复源 intent_id、同名已有 spec（报错附恢复路径）、大小写归一后同名 Spec 目录、`specs/` 根或 feature 目录被文件占用、frontmatter `status_dir` 与物理状态目录不一致均在规划期阻断 apply，管理根下符号链接 fail-closed 拒绝，新 Spec 独占创建；账本已记录的 Spec 路径永不重算，不同 intent_id 目录名坍缩时确定性消歧；源更新（只读历史原文件被改动）阻断 apply 与 verify 并给出恢复指引，Spec / 历史索引被用户修改的只报告不覆盖（历史索引保留判定不依赖账本，账本丢失重跑仍幂等保留）；账本、索引、Spec、feature.json 写入与 verify 全部带祖先 containment 校验（含 history-only 原件），verify 另核对历史索引关键声明（账本路径与 select 命令仍在）；Status 照录历史状态（Draft / In Progress / Complete / Unknown，不把已完成重开为 Draft）；最旧模板「非目标」等节别名正确映射，背景 / 记录 / 计划交接 / 引言逐字保留并标注原文必读；`.specify/feature.json` 不被迁移创建或改写，select 写入的指针值是 feature 目录（上游 common.sh 解析已实测）；重复执行 migrate-intents 幂等。本项必过（不接受 `not_applicable`），与技能退役解耦 |

合并前核对：本项在 `retire-legacy-skills` 之后执行，业务意图条目在退役流程中字节不动，本项只读它们并新增 `specs/` 产物与历史索引。项目显式要求保留旧意图机制不迁移时该项 `blocked`（保留原树交用户决定）；`specs/.ph-intent-ledger.json` 已存在但 schema 不符时阻断，不猜测改写。

## 完成标准

- 未对目标 `git pull`，未当最新源用 `main` 或未准备的本地 scaffold。
- dry-run / `inspect` 不写目标；冲突项保持原文件。
- `state.status=complete` 仅当 verify + finalize 成功且常规 `check` 通过。
- adapter mode 未变；`进行中/` 业务条目未被批量改派。
- 未自动 commit / push / 公开仓库。
