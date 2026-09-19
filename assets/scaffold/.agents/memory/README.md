# 项目记忆

本目录是仓库内的便携记忆库，路径一律相对仓库根：`.agents/memory/{temporary,structured,archive}`。不绑定 Obsidian、个人 vault 或任何用户绝对路径。

记忆只表示“当时曾这样写过”。它不是规范、不是当前事实、也不是执行授权。与 `.agents/AGENTS.md`、`docs/约束规范/`、当前代码或用户当轮指令冲突时，以后者为准。

## 目录

| 路径 | 定位 |
| --- | --- |
| [temporary/](./temporary/README.md) | 一条一事的临时记忆，尚未合并 |
| [structured/](./structured/README.md) | 按主题沉淀后的结构化记忆 |
| [archive/](./archive/README.md) | 已合并的临时记忆原件，禁止改写、禁止删除 |

空目录用本层 README 占位，与 `docs/` 的“每目录一个 README”一致，不另用 `.gitkeep`。

## Frontmatter

每条记忆（含结构化文档与归档原件）必须带齐以下字段，顺序与 [ph.json](../ph.json) 的 `memory.frontmatter_fields` 一致：

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

- 问“以前记过什么”：按记忆回答，并标注路径、日期与参考性质。
- 要据此改代码、改规范、部署、删除或对外发送：先核验当前 `AGENTS.md`、`docs/约束规范/` 与代码；核验失败则停止询问，不得用记忆补齐。对用户开口前先读 `docs/约束规范/工程规范/对用户提问.md`，问句用日常用语。
- 记忆过期或冲突时并列列出，不擅自裁定当前真相。
