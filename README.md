# Project Harness

Project Harness（PH）为 Git 项目安装一套供 AI 编码助手使用的开发规范、技能和文档目录。初始化时，助手会读取项目代码和已有资料，整理 Wiki、开发规范和测试要求。配套技能还可以记录需求、归档项目经验、管理隔离工作区。安装入口与技能名固定为 `ph-init`，不随仓库名变化。

如果你已经在用 `AGENTS.md` 交代编码规则，PH 可以在这份规则之外，补上架构说明、需求记录和经验归档。资料保存在仓库里，团队可以一起维护，后续会话也有据可查。已有文档可以合并整理，不必从模板重写。

> 从旧地址来？本仓库已由 `ph-init` 更名为 `project-harness`，旧链接自动跳转。已安装用户无需重装或搬目录，升级步骤见[从旧版本升级](./docs/从旧版本升级.md)。

[开始使用](#开始使用) · [更新记录](./CHANGELOG.md) · [正式版本](https://github.com/chenweixuanJokes/project-harness/releases)

## 项目中会增加什么

项目规则保存在 `.agents/AGENTS.md`，根目录的 `AGENTS.md`、`CLAUDE.md` 是供编码工具读取的入口，由 PH 生成和同步。文档按用途分开：

```text
docs/
├── 约束规范/       # 编码规则、测试要求、架构决策
├── 意图/           # 功能需求、问题及实施记录
└── 项目Wiki/       # 项目结构、领域知识、使用说明

.agents/
├── AGENTS.md       # 项目约束正文
├── skills/         # PH 技能
├── memory/         # 项目经验与历史参考
└── archived/       # 整理文档前保存的原文
```

这里的「意图」指准备在项目中做的改动。功能和问题可以先记为待办，开始开发后进入实施，完成时留下验收结果；放弃的事项也保留原因。

PH 附带十二个技能，覆盖安装与维护、需求记录与实施、实现后的用户验收、记忆的记录与查询、隔离工作区的进入和退出，以及文档与代码一致性的核验同步。项目记忆用于参考，不能替代当前规则和代码。所有技能都需要你在对话中点名才会使用：只描述任务（比如“记住 X”“检查文档”）不会自动触发对应技能，技能之间也不会互相联动调用。

## 支持的编码工具

PH 面向 Claude Code、Codex、OpenCode，不绑定某个客户端。约束与技能的规范源固定在 `.agents/`，仓库根 `AGENTS.md` 是通用入口。Claude Code 通过 `CLAUDE.md` 与 `.claude/skills/` 接入；Codex、OpenCode 原生读取 `.agents/skills`。其他客户端需核对各自的规则文件和技能发现路径，不能仅凭“支持 Skills”就视为兼容。

入口依据：[Claude Code 技能文档](https://code.claude.com/docs/en/skills)、[Codex 技能文档](https://developers.openai.com/codex/skills)、[OpenCode 技能文档](https://opencode.ai/docs/skills/)。

## 已有项目怎么处理

初始化会先检查代码、依赖、配置、测试和现有文档，再给出整理方案。比如项目使用什么框架、测试从哪里运行，要从仓库中核实；没有前端的项目，不会被要求填写一套前端技术栈。

已有正文优先保留或引用。需要合并、移动的文档会先备份原文，再调整目录和链接。内容有冲突时由你确认，不会直接套用模板。

文件写入后，助手会继续补文档，并说明哪些内容已经核实、哪些仍缺资料。安装检查只检查 PH 文件和入口，文档是否完整要单独看；未完成的部分可以继续整理，无需重装。

## 开始使用

需要 Git、Python 3 和支持 Skills 的 AI 编码工具。下面将入口安装到用户级技能目录，请先确认你的工具会读取该目录：

```bash
git clone https://github.com/chenweixuanJokes/project-harness.git ~/.agents/skills/ph-init
```

目录已存在时不要覆盖，使用已有入口即可。Codex 和 OpenCode 可直接发现这份用户级技能。Claude Code 还需要在 `~/.claude/skills/ph-init` 建立直接指向 `../../.agents/skills/ph-init` 的相对软链接；先检查该路径，已有内容时不要覆盖。Windows 无法创建目录软链接时，可将这份入口作为受管副本放入 Claude Code 的技能目录，更新时保持与规范源一致。

打开自己的项目，在 AI 对话中输入：

> 用 ph-init 初始化 PH，先检查现有代码和文档，列出要改哪些文件，确认后再安装。

助手会下载最新正式版，检查项目，并等待你确认写入范围。目标项目需要是 Git 仓库，空目录可以先执行 `git init`。不要在 Project Harness 分发仓库本身执行初始化。

新装默认自动选择适配模式：写入前检查 Git 配置，并实际探测文件和目录软链接；可用就优先使用，`core.symlinks=false` 或探测失败则自动改用 portable 受管副本，并说明原因。打包、同步工具以后是否会展开链接无法自动检测；有这类分发需求，或团队包含不支持软链接的环境时，应在首次安装显式选择 `--mode portable`。portable 保持内容一致，不是功能降级；显式 `--mode symlink` 时不回退，探测失败直接停止。已安装的项目升级时保留原模式，本版不提供模式转换。

不同客户端的技能发现方式有差异，未识别时请检查客户端配置。Windows、网络盘和各客户端的兼容情况尚未全部验证。

## 日常使用

安装以后，在对话中点名技能，让助手按对应技能的流程处理，例如：

> 用 ph-intent-new 把导出报表的需求登记成意图，先不写代码。

> 用 ph-intent-impl 启动这个意图，制定实施计划。

> 用 ph-memory-capture 把这次排查的结论记到项目记忆里。

> 用 ph-worktree-enter 给这个任务开一个隔离工作区。

> 完成后用 ph-worktree-exit 收口，把改动合回主目录。

> 用 ph-intent-verify 逐项验收这个做完的意图。

> 用 ph-docs-sync 对照当前代码检查 README 和文档里的配置说明、使用示例是否过期，先不要改文件。

检查、同步和升级使用 `ph-init` 入口：

> 用 ph-init 检查 PH，先不要改文件。

> 用 ph-init 升级 PH，保留项目自己的规则和文档，先给我看差异。

所有 PH 技能只在被点名并要求使用时才执行；不点名、直接描述任务时不会触发对应技能。流程开始后，直接回答提问或说“继续”即可推进，不需要每轮重复技能名。普通检查和同步使用项目已安装的版本，不下载更新。升级会比较新旧内容，保留项目定制；与现有规则冲突的部分需要确认。旧版本的首次升级与仓库更名说明见[从旧版本升级](./docs/从旧版本升级.md)。

## 下载

安装和升级从 [官方仓库](https://github.com/chenweixuanJokes/project-harness) 下载正式版本。开发分支不作为最新版；下载或校验失败时会停止。官方仓库已由 `ph-init` 更名，旧地址自动跳转，详见[从旧版本升级](./docs/从旧版本升级.md)。

可下载的版本以 [Releases](https://github.com/chenweixuanJokes/project-harness/releases) 为准。

## 文档

- [初始化与文档整理](./assets/scaffold/docs/约束规范/工程规范/初始化与文档补全.md)
- [版本升级说明](./migrations/README.md)
- [技能与命令参考](./SKILL.md)
- [贡献者：维护与发布要求](./docs/约束规范/工程规范/版本与合并升级.md)
