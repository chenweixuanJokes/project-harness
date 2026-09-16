---
name: ph-memory-capture
description: "把用户要求记住的内容写入仓库 `.agents/memory/temporary/`。只要用户说“记住”“记一下”“写进记忆”“capture memory”，或明确要把当前结论落成项目记忆——即使没点名本技能——都必须使用。不要把查记忆、归档记忆、普通知识问答、只回顾当前对话、录入/规划/废弃意图、或要求改规范/Wiki 误判为本技能。禁止写入秘密与个人信息。"
---

# ph-memory-capture

把一条可检索的临时记忆写入当前仓库的 `.agents/memory/temporary/`。本技能只写临时层，不归档、不改规范、不改 Wiki。

## 何时用 / 何时不用

使用：用户要求记住一句话、一个结论、一个坑、一次选择。

不用：

- 查记忆、根据记忆问答 → `ph-memory-ask`
- 归档 / 沉淀 / 整理临时记忆 → `ph-memory-archive`
- 普通知识问答、只复述当前对话
- 用户要求改 `.agents/AGENTS.md`、`docs/约束规范/` 或 Wiki——那是规范或 Wiki 任务，不是记忆

## 路径定位

1. 从当前工作目录向上找同时存在 `.agents/ph.json` 与 `.agents/AGENTS.md` 的仓库根。找不到则停止并说明“当前不在 PH 仓库内”。
2. 记忆根目录固定为 `<repo>/.agents/memory/`，子目录名读 `ph.json` 的 `memory.directories`（默认 `temporary` / `structured` / `archive`）。
3. 字段约定读 `<repo>/.agents/memory/README.md` 与 `temporary/_template.md`。不要使用用户主目录、Obsidian vault 或任何绝对路径配置。

## 安全边界

写入前先扫描待记内容。出现下列任一内容则**拒绝落盘**，向用户说明原因，并给出去密后的可记表述供确认。问法见 [对用户提问](../../../docs/约束规范/工程规范/对用户提问.md) 的“把问题写成可回答的决定”，例如：“可以用只记位置、不记值的说法吗？”

- 密码、令牌、Cookie、私钥、完整连接串、证书材料
- 身份证、手机号、个人邮箱、家庭地址等个人信息
- 可直接冒用的账号与口令组合

允许记录“凭证种类与存放位置”，不允许记录值。记忆不能授予任何操作权限。

## 工作流

1. **确认对象**：抽出要记住的原话或忠实转述。一条文件只记一件事。用户一次说多件，拆成多条。
2. **去密**：按安全边界改写或拒绝。拿不准是否属于秘密时，先问再写。
3. **命名**：`YYYYMMDD-短主题.md`。日期用当天（仓库本地日历日，`YYYY-MM-DD`）。主题短、可检索，避免路径分隔符与标点。
4. **查重**：在 `temporary/` 与 `structured/` 用主题词检索。已有几乎相同的 active 临时记忆则更新其 `updated` 与正文，不复制第二条；结构化文档已有且用户只是重复旧结论时，向用户说明并询问“还要再记一条临时补充吗”。
5. **写文件**：复制 `temporary/_template.md`，填齐 frontmatter 后写正文。

   - `kind`: `temporary`
   - `status`: `active`
   - `created` / `updated`: 当天
   - `provenance`: 用户原话用 `user-utterance`；经你压缩但仍忠实的用 `agent-summary`
   - `confidence`: 按用户语气，默认 `medium`
   - `review_after`: 用户给了时效则填，否则 `""`
   - `supersedes`: 明确取代某条时填仓库相对路径，否则 `""`
   - `sensitivity`: 默认 `internal`
   - `topics`: 1–3 个短标签，供日后归档分组
6. **正文**：用户原话或忠实转述，不美化、不补未说的细节。需要上下文时用一句话标明场景，不把整段对话贴进文件。
7. **报告**：给出仓库相对路径、`topics` 与“仅供参考、尚未归档”的提示。

## 完成标准

- 目标文件位于 `<repo>/.agents/memory/temporary/`，文件名符合约定。
- frontmatter 十个字段齐全，取值落在 README 允许集合内。
- 正文无秘密、无个人信息。
- 未改动 `structured/`、`archive/`、`docs/`、`.agents/AGENTS.md`。
- 向用户返回相对路径。未满足任一项则不算完成。
