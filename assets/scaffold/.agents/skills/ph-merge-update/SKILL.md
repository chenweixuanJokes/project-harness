---
name: ph-merge-update
description: "已装 PH 项目升到正式发行版的步骤：从唯一 GitHub 源准备固定 tag/commit，按迁移链审阅合并，验收后再推进项目版本。本文件不按普通描述触发：用户点名 ph-init 并请求升级已装项目时，由 ph-init 会话读本文件作为该次升级的内部步骤执行；用户当轮明确点名 ph-merge-update 并要求使用时，也由同一会话按本文件执行。只说“升级 PH”“安装 harness”、上下文提及或讨论名称不触发。已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。不要把未初始化仓库的安装、普通 check/sync、git pull、录入/实施/验收/废弃意图、记忆或 worktree 误判为本文件的步骤。"
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
python3 <ph-init-root>/scripts/ph_release.py prepare --version latest|1.1.13 --repo <target>
```

stdout JSON 字段：`root` `version` `tag` `commit` `source`。`source` 是固定仓库 URL 字符串（1.x 仍为旧地址，保留兼容含义，不改写、不当错误）。本地已有该 commit 的检查不访问网络。准备成功后把脚本提示转告用户；没登录不拦升级。本会话刚用旧脚本 prepare 时，用发行根补跑 `python3 <release-root>/scripts/ph_release.py support`，不必为了加星再下一遍包。检查 / 同步仍然离线，不重新 prepare，也不为了加星上网。安装和以后升级仍从官方地址进行。

**一次性入口切换**：旧版（1.1.7 及更早）用户级入口的 prepare 必查发行元数据里的 `schema_version`，会必然拒绝 1.1.8 及以后发行包；这是预期现象，不重试、不回退、不假称自动恢复。把首个无独立 Schema 版本的已发布标签 v1.1.8 clone 到一个**新的仓外安全目录**（如 `mktemp -d` 创建），不覆盖用户级入口与目标项目，不用 `main` 或本地开发树冒充发行；先在该目录运行 `python3 <新目录>/scripts/ph_release.py prepare --version 1.1.8` 并读取返回根的 Skill，再用这份新工具准备并固定目标 1.1.13 发行根。之后本文件全部升级命令都使用 1.1.13 prepare 返回的根，不再用旧目录或 v1.1.8 发行根冒充最终目标。1.1.8 及以后入口可直接准备 1.1.13。

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
5. **按项合并**（用户确认后才写盘）。框架资产更新到目标态。AGENTS、规范、README 按段落合并，保留已填项目事实。唯一例外：迁移说明授权整文件覆盖的文件（当前为 1.1.12 `question-execution-contract` 的《对用户提问》）按该授权先备份旧原文再整文件替换，不走段落合并。业务文档只做迁移要求的调整，不改访谈原话、历史代码块、业务编号、无关 Wiki/记忆。init 会话中 subagent 生成的文档同样属于项目定制；不因升级重新生成 Wiki、全网调研或替换技术栈。新指引补缺与项目正文分开审阅，只有另行授权补全时才执行扩展调研。旧意图目录按完整链的最终迁移要求处理，不能仅按旧模板猜业务状态。
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
| `intent-verify-skill` | 新必需 Skill `ph-intent-verify` 已从发行根安装到 `.agents/skills/ph-intent-verify/`（SKILL.md 与 evals）；`.agents/AGENTS.md` 技能表与 `docs/约束规范/工程规范/意图与访谈.md` 已登记第十二行；本项不迁移任何业务意图，不新增意图状态、目录或纪要 purpose。安装证据记录在 state 项 |

合并前核对 `.agents/skills/ph-intent-verify/`：旧版（1.1.12 及更早）不携带该 Skill，若项目已有**同名自定义 Skill**，本项 `blocked`，保留原件并请用户决定（改名保留或替换为官方版），不得覆盖；项目规则明确禁止新增 ph-* Skill 时同样 `blocked`。形态规整的同名目录由 `inspect` 列入冲突清单；无 `SKILL.md` 或含软链等异常形态会先被结构校验直接拒绝，两种路径都 fail-closed。`explicit-invocation-rules` 与项目显式规则相反（如项目要求按普通描述自动触发某 Skill）时该项 `blocked`，交用户裁决。

## 完成标准

- 未对目标 `git pull`，未当最新源用 `main` 或未准备的本地 scaffold。
- dry-run / `inspect` 不写目标；冲突项保持原文件。
- `state.status=complete` 仅当 verify + finalize 成功且常规 `check` 通过。
- adapter mode 未变；`进行中/` 业务条目未被批量改派。
- 未自动 commit / push / 公开仓库。
