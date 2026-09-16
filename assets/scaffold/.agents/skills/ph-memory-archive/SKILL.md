---
name: ph-memory-archive
description: "将 `.agents/memory/temporary/` 下的零散临时记忆合并进 `.agents/memory/structured/`，原件移入 `archive/`。调用门禁：仅当用户当轮明确点名 ph-memory-archive（如「用 ph-memory-archive 归档记忆」）并要求使用时才调用；只说“归档记忆”“沉淀记忆”“整理临时记忆”等普通描述、上下文提及或讨论技能名称都不触发。已显式启动的同一流程内，用户回答提问或说“继续”仍按原流程接收反馈与恢复，不要求每轮重复点名，也不触发其他技能。不要把查记忆、记住 X、只回顾当前对话、意图的录入/规划/验收/废弃、或改规范/Wiki 误判为本技能。"
---

# ph-memory-archive

把临时记忆按主题合并进结构化文档，并把原件移入归档层。归档 = 内容沉淀 + 原件存档。全程不删除文件，不把记忆提升为规范。

**调用门禁**：仅当用户当轮明确点名本技能（如「用 ph-memory-archive 归档记忆」）并要求使用时才执行。用户只说“归档一下记忆”“整理整理临时记忆”、上下文提及、或讨论技能名称本身，都不触发。

## 何时用 / 何时不用

使用：用户要求归档、沉淀、整理临时记忆；或临时层同主题已堆积到需要合并。

不用：

- “记住 X” → `ph-memory-capture`
- 查记忆 / 以前是怎么做的 → `ph-memory-ask`
- 改 AGENTS、约束或 Wiki

用户限定范围（例如“只归档测试相关”）时，只处理该范围。

## 路径定位

1. 从当前工作目录向上找同时存在 `.agents/ph.json` 与 `.agents/AGENTS.md` 的仓库根。找不到则停止。
2. 三个子目录来自 `ph.json` 的 `memory.directories`，默认：

   - `<repo>/.agents/memory/temporary/`
   - `<repo>/.agents/memory/structured/`
   - `<repo>/.agents/memory/archive/`
3. 先读 `<repo>/.agents/memory/README.md` 与 `structured/_template.md`。本技能与 README 冲突时以 README 为准。不要使用 Obsidian 或用户绝对路径。

## 安全边界

- 合并前与合并中再次扫描：密码、令牌、Cookie、私钥、完整连接串、证书材料、身份证、手机号、个人邮箱、家庭地址等秘密与个人信息。发现任一待归档原件含此类内容，**立刻阻断该条所属的本次归档**（用户限定了范围则只阻断该范围；未限定则阻断整个本次归档）：不新建或改写 `structured/`，不把原件移入 `archive/`，源文件保持原处原样。
- 阻断后只报告处理要求：指出含敏感内容的仓库相对路径（不复制、不摘录、不回显秘密本身），要求用户先脱敏、撤销或轮换已暴露凭据，并自行改写该临时记忆后再重新归档。本技能不擅自改写、不复制秘密、不把含密原件送进受 Git 管理的 `archive/`。
- 无敏感内容的正常原件仍用“移动”保留到 `archive/`，不用 `rm`。禁止删除任何文件。
- 不把归档结果写成 `docs/约束规范/` 或 Wiki。记忆仍只供参考。

## 工作流

1. **盘点**：列出 `temporary/` 下除 `README.md`、`_template.md` 外的 `YYYYMMDD-*.md`。若没有待归档文件，报告“没有待归档的临时记忆”并结束。
2. **通读并扫描敏感内容**：逐篇读完全文。临时记忆是唯一事实来源，不凭印象补充。任一篇含安全边界所列秘密或个人信息时，立刻按安全边界阻断本次归档（或用户限定的范围），跳过后续合并与移动。
3. **分组**：优先用 frontmatter `topics[0]`，其次用标题与正文判断主题域。一个主题域对应 `structured/` 下一份文档。归属不明的归入最接近的已有主题；全新主题按 `_template.md` 新建，文件名用短中文或英文 kebab-case。
4. **合并**：对每个主题域：

   - 已有结构化文档：增量写入对应章节，去重，不另开平行文档。更新 `updated` 为当天，视情况调整 `confidence` / `review_after` / `topics`。在文末“归档来源”追加本次原件的仓库相对路径。
   - 不存在：复制 `_template.md`，`kind: structured`，`status: active`，`created` 与 `updated` 为当天，`provenance: agent-summary`。
   - 忠实原文、保留有信息量的细节；用户原话加“用户原话”标注。不美化、不把过期猜测写成现行事实。
   - 若新结论明确取代旧结构化段落：旧文档或旧段标 `status: superseded`，新文档填 `supersedes` 为旧路径。
5. **移入原件**：仅当本次范围内全部待归档文件均无敏感内容、且对应结构化文档已写好时，将已合并的临时文件移到 `archive/`。移动时只改 frontmatter：`kind: archived-source`，`status: archived`；`created` / `updated` / 正文保持原样。同名冲突时保留双方，新文件加 `-1` 后缀。禁止 `rm`，禁止删除原件。发现敏感内容时本步不得执行。
6. **报告**：成功时列出新建或更新的结构化文档、各合并几条、原件的新路径，并提醒“结构化记忆仍不是规范”。阻断时只报含敏感内容的相对路径与“先脱敏 / 撤销凭据后再归档”，不附秘密原文。

## 完成标准

- 无敏感内容时：`temporary/` 中本次范围内的待归档文件已不在原处；对应 `structured/` 文档 frontmatter 十个字段齐全，正文能回溯到归档来源路径；原件在 `archive/`，正文未被改写，`kind` / `status` 已切换。
- 发现敏感内容时：不新建或改写 `structured/`，不移动源文件，`temporary/` 原件仍在原处；报告已给出脱敏 / 撤销凭据要求且未复制秘密。
- 无文件被删除，无秘密进入结构化层或 archive 层。
- 未改动 `docs/` 与 `.agents/AGENTS.md`。
