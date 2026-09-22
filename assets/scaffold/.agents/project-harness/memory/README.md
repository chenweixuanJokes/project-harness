# 项目记忆

本目录是仓库内的便携记忆库（**项目档**），路径一律相对仓库根：`.agents/project-harness/memory/（temporary、structured），归档层在 ../archive/memory/`。不绑定 Obsidian、个人 vault 或任何用户绝对路径。

记忆只表示“当时曾这样写过”。它不是规范、不是当前事实、也不是执行授权。与 `.agents/AGENTS.md`、`project-harness/constraints/`、当前代码或用户当轮指令冲突时，以后者为准。

## 技能

记忆操作由三个 PH 技能执行，安装与升级由 PH 发行版管理：

| Skill | 何时用 | 调用门禁 |
| --- | --- | --- |
| `ph-memory-ask` | 回忆、盘点、追溯记忆并按记忆回答 | **唯一例外**：用户当轮明确表达回忆意图（如“查记忆”“你还记得吗”）即自动触发，无需点名 |
| `ph-memory-learning` | 记住用户点名要求记录的内容，或忠实阅读用户点名指定的资料并按主题写心得 | 仅当用户当轮明确点名该技能并指定内容或资料时触发 |
| `ph-memory-archive` | 把临时记忆按主题增量合并进结构化层，原件移入归档层 | 仅当用户当轮明确点名该技能并要求使用时触发 |

普通描述（“记住 X”“学习一下”“归档一下”）、上下文提及或讨论技能名称都不触发除 ask 意图查询之外的任何记忆技能；技能之间不自动串联；已显式启动的同一流程内用户回答与“继续”仍按原流程接收，不要求每轮重复点名。

## 个人档

跨项目参考可使用个人档 `~/.agents/memory/`，`temporary` / `structured` / `archive` 三层目录与 frontmatter 字段约定沿用项目档（个人档归档层就地在 `~/.agents/memory/archive/`，不套用项目档的统一归档目录）。个人档不由 PH 安装、升级或项目初始化创建：查询在用户明确指定“全局 / 个人档 / 都查（all）”时只读检索（不存在则如实报告），写入与归档仅在用户明确要求全局时按需创建缺失层；除 `~/.agents/memory/` 自身外不触碰 HOME 下其他路径。项目内查询默认只查项目档，项目档未命中不自动扩大到个人档。

## 目录

| 路径 | 定位 |
| --- | --- |
| [temporary/](./temporary/README.md) | 一条一事的临时记忆，尚未合并 |
| [structured/](./structured/README.md) | 按主题沉淀后的结构化记忆 |
| [../archive/memory/](../archive/memory/README.md) | 已合并的临时记忆原件（统一归档目录），禁止改写、禁止删除；唯一例外见下 |

空目录用本层 README 占位，与约束目录的“每目录一个 README”一致，不另用 `.gitkeep`。

## 归档原件的改写边界

archive 层原件“禁止改写”与归档时切换 `kind` / `status` 并不矛盾，边界是：原件**正文与其余全部 frontmatter 字段**（`created`、`updated`、`provenance`、`confidence`、`review_after`、`supersedes`、`sensitivity`、`topics`）逐字节保持移入前原样，禁止删除、禁止润色；**唯一的例外**是移入时允许且仅允许把 frontmatter 的 `kind` 改为 `archived-source`、`status` 改为 `archived`，表示该文件已并入结构化层、不再是现行临时记忆。除此之外对原件的任何修改都不允许。

## Frontmatter

每条记忆（含结构化文档与归档原件）必须带齐以下字段，顺序与 [ph.json](../../ph.json) 的 `memory.frontmatter_fields` 一致：

```yaml
---
kind: temporary
status: active
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
provenance: user-utterance
confidence: medium
review_after: "YYYY-MM-DD"
supersedes: ""
sensitivity: internal
topics:
  - example-topic
---
```

| 字段 | 取值 | 作用 |
| --- | --- | --- |
| `kind` | `temporary` / `structured` / `archived-source` | 当前所在层。原件移入 archive 后改为 `archived-source`，正文不改。 |
| `status` | `active` / `superseded` / `archived` | 是否仍作现行参考。被取代的结构化文档标 `superseded`，并填 `supersedes` 的反向关系。 |
| `created` | `YYYY-MM-DD` | 首次写入日 |
| `updated` | `YYYY-MM-DD` | 最近改写日；归档原件保持移入前的值 |
| `provenance` | `user-utterance` / `agent-summary` / `derived-from-docs` / `derived-from-code` | 来源类型，便于 ask 时判断可信度 |
| `confidence` | `high` / `medium` / `low` | 记录当时的确信程度，不是当前有效性 |
| `review_after` | `YYYY-MM-DD` 或 `""` | 建议重验日期；空表示无固定复审点 |
| `supersedes` | 仓库相对路径或 `""` | 本篇取代的旧记忆；没有则空 |
| `sensitivity` | `internal` / `public-in-repo` | 仅描述可见范围。秘密不得入库，因此没有 `secret` 档。 |
| `topics` | 字符串列表 | 主题标签，归档分组与检索用 |

字段模板见 [structured/_template.md](./structured/_template.md) 与 [temporary/_template.md](./temporary/_template.md)。

## 安全边界

下列内容不得写入任何记忆文件：

- 密码、令牌、Cookie、私钥、完整连接串、证书材料
- 身份证、手机号、个人邮箱、家庭地址等个人信息
- 可直接冒用的账号口令组合

发现此类内容立即停止写入或归档该条：不落盘、不移入受 Git 管理的 `archive/`，源文件保持原处；只报告脱敏 / 撤销凭据等处理要求，不擅自改写、不复制秘密。需要记住“用了哪类凭证、存在哪里”时，只写位置与种类，不写值。

## 效力与核验

- 问“以前记过什么”：由 `ph-memory-ask` 只读检索并回答，标注档位、路径、日期与参考性质。
- 要据此改代码、改规范、部署、删除或对外发送：先核验当前 `AGENTS.md`、`project-harness/constraints/` 与代码；核验失败则停止询问，不得用记忆补齐。对用户开口前先读 `project-harness/constraints/harness规范/对用户提问规范.md`，问句用日常用语。
- 记忆过期或冲突时并列列出，不擅自裁定当前真相。
