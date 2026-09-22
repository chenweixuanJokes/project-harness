---
name: "ph-taskstoissues"
description: "将已有任务转为可跟踪的 GitHub Issues，保留任务内容与依赖关系。仅在用户主动明确点名调用本技能时执行；普通任务描述、名称提及或上下文关联不触发，执行结束后不自动串联其他技能。已显式启动后不要求每轮重复点名，不触发其他技能。"
compatibility: "Requires spec-kit project structure with .agents/project-harness/runtime/ directory"
metadata:
  author: "github-spec-kit"
  source: "templates/commands/taskstoissues.md"
x-ph-upstream:
  repository: https://github.com/github/spec-kit.git
  tag: v1.0.8
  commit: 0cc9a6a1159471a3108b9bad718ba17006dd6039
  original_name: speckit-taskstoissues
---

## PH 项目测试规范联动

本技能是基于固定上游的 PH 适配版。项目宪法及其引用的现行约束决定验收要求，不使用上游的可选测试提示降低项目门禁。按当前阶段读取 `.agents/project-harness/constraints/测试规范/门禁规范.md`、`用例规范.md`、`稳定性规范.md`；涉及实现方案、任务或运行验证时，继续读取相关端的自测规范、单元/冒烟/回归规范及相关冒烟案例。启动方式只从相关端构建规范获取。缺文件或存在占位时报告缺口，不跳过必需约束。

不要求用户重复选择是否遵守项目已经采用的测试要求。仅澄清无法查证的业务歧义或必要权限。本次调用不自动调用其它技能，扩展 hook 也不能绕过点名调用和外部操作授权。

保留任务的验收目标、测试工作、依赖和证据要求，不只转换开发任务。创建 GitHub Issues 属于对外写入，必须在已有明确授权范围内执行；测试联动不扩大该授权。

附带人读版：仅当本次在已有授权范围内真实创建了 GitHub Issues，才按 `.agents/skills/ph-human/references/human-writing.md` 把实际创建结果写成当前功能目录下的 issues-human.md 快照伴读，正文先写仓外临时文件，再经 `python3 .agents/scripts/ph_human.py publish-snapshot --kind issues` 发布，文末机器元数据由脚本处理，正文不自带元数据。仅计划、被拒绝或失败时不生成；生成伴读不构成额外对外写入。伴读是快照解释，不是权威规则或验收源。直接读取该写作规范执行，不调用 ph-human，也不触发任何其他技能。



## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before tasks-to-issues conversion)**:
- Check if `.agents/project-harness/runtime/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_taskstoissues` key
- If the YAML cannot be parsed or is invalid, do not skip silently: tell the user that `.agents/project-harness/runtime/extensions.yml` could not be read (include the parser error) and that no hooks were checked, including any mandatory (`optional: false`) hooks registered there, then continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- When constructing command invocations from hook command names, replace dots (`.`) with hyphens (`-`). For example, `speckit.git.commit` → `$speckit-git-commit`.
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):
    ```
    ## Extension Hooks

    **Optional Pre-Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```
  - **Mandatory hook** (`optional: false`):
    ```
    ## Extension Hooks

    **Automatic Pre-Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}

    Wait for the result of the hook command before proceeding to the Outline.
    ```
    After emitting the block above you MUST actually invoke the hook and wait for it to finish before continuing. Run it the same way you would run the command yourself in this agent/session (the invocation may differ from the literal `{command}` id shown above, e.g. a skills-mode agent runs it as `/skill:speckit-...` or `$speckit-...`). Emitting the block alone does not run the hook.
- If no hooks are registered or `.agents/project-harness/runtime/extensions.yml` does not exist, skip silently

## Outline

1. Run `.agents/project-harness/runtime/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks` from repo root and parse FEATURE_DIR and AVAILABLE_DOCS list. All paths must be absolute. For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").
1. **IF EXISTS**: Load `.agents/project-harness/constitution.md` for project principles and governance constraints.
1. From the executed script, extract the path to **tasks**.
1. Get the Git remote by running:

```bash
git config --get remote.origin.url
```

> [!CAUTION]
> ONLY PROCEED TO NEXT STEPS IF THE REMOTE IS A GITHUB URL

1. **Fetch existing issues for deduplication**: Before creating anything, build the set of task IDs you are about to process from `tasks.md` (each is a `T` followed by **at least** three digits, e.g. `T001` — `$ph-converge` assigns new IDs with `T{M+1:03d}`, which is a floor rather than a cap, so once a file has more than 999 tasks the IDs are four digits or longer). Then use the GitHub MCP server's `list_issues` tool to look for issues that already cover those IDs. Do not pass a `state` value, since omitting it makes the tool return both open and closed issues. Request `perPage: 100` to keep the number of calls down, and since the tool uses cursor-based pagination, request pages with the `after` parameter (using the `endCursor` from the previous response). For each issue title, match it against the task ID pattern `\bT\d{3,}\b` (the `{3,}` accepts four-digit and longer IDs — with `\d{3}` a title containing `T1000` would not match at all, because the trailing `\b` cannot fall between two digits, so that task would be silently neither deduplicated nor created; word boundaries still stop a token like `ST001` from matching, and force the whole digit run to be consumed so `T100` can never match inside `T1000`; this also recognises titles written as `T001 ...`, `T001: ...` or `[T001] ...`) and, when it matches one of your task IDs, mark that ID as already having an issue. Stop paginating as soon as every task ID has been matched, or when there are no more pages, so you do not keep fetching the whole repository's issue history once all task IDs are accounted for. This bounds the number of calls on repos with large issue histories and still prevents duplicates when the command is re-run after `tasks.md` is regenerated or the skill is re-invoked.
1. For each task in the list, use the GitHub MCP server to create a new issue in the repository that is representative of the Git remote. Task lines in `tasks.md` start with a markdown checkbox, so first strip the leading `- [ ]` (and any `[P]` / `[US#]` markers) to recover the task ID and its description. Create the issue with a single canonical title of the form `T001: <description>`, with the ID written once followed by the task description (for example, the line `- [ ] T001 Create project structure` becomes the title `T001: Create project structure`).
   - **Skip** any task whose ID is already present in the set of existing issues from the previous step, and report it (for example, `T001 already has an issue, skipping`).
   - Only create issues for tasks that do not yet have a matching issue.

> [!CAUTION]
> UNDER NO CIRCUMSTANCES EVER CREATE ISSUES IN REPOSITORIES THAT DO NOT MATCH THE REMOTE URL

## Post-Execution Checks

**Check for extension hooks (after tasks-to-issues conversion)**:
Check if `.agents/project-harness/runtime/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.after_taskstoissues` key
- If the YAML cannot be parsed or is invalid, do not skip silently: tell the user that `.agents/project-harness/runtime/extensions.yml` could not be read (include the parser error) and that no hooks were checked, including any mandatory (`optional: false`) hooks registered there, then continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- When constructing command invocations from hook command names, replace dots (`.`) with hyphens (`-`). For example, `speckit.git.commit` → `$speckit-git-commit`.
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):
    ```
    ## Extension Hooks

    **Optional Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```
  - **Mandatory hook** (`optional: false`):
    ```
    ## Extension Hooks

    **Automatic Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}
    ```
    After emitting the block above you MUST actually invoke the hook and wait for it to finish before continuing. Run it the same way you would run the command yourself in this agent/session (the invocation may differ from the literal `{command}` id shown above, e.g. a skills-mode agent runs it as `/skill:speckit-...` or `$speckit-...`). Emitting the block alone does not run the hook.
- If no hooks are registered or `.agents/project-harness/runtime/extensions.yml` does not exist, skip silently

## PH 下一步建议（固定输出）

完成报告与 extension hook 处理结束后、结束本次回复前，向用户原样输出下面代码块内的固定文案作为收尾。这只是建议：本技能不自动调用任何技能，等用户明确点名后再执行。

```text
下一步建议执行:
- 压缩会话（/compact）后再继续
- 后续可执行的 skills（按场景选择）:
  - 无 - 本技能是流程终点，后续在 GitHub Issues 跟踪任务
```
