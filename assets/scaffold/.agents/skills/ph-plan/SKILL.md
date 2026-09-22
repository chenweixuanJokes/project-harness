---
name: "ph-plan"
description: "根据功能规格和项目约束制定实现计划，形成研究、数据模型与接口等设计材料。仅在用户主动明确点名调用本技能时执行；普通任务描述、名称提及或上下文关联不触发，执行结束后不自动串联其他技能。已显式启动后不要求每轮重复点名，不触发其他技能。"
compatibility: "Requires spec-kit project structure with .agents/project-harness/runtime/ directory"
metadata:
  author: "github-spec-kit"
  source: "templates/commands/plan.md"
x-ph-upstream:
  repository: https://github.com/github/spec-kit.git
  tag: v1.0.8
  commit: 0cc9a6a1159471a3108b9bad718ba17006dd6039
  original_name: speckit-plan
---

## PH 项目测试规范联动

本技能是基于固定上游的 PH 适配版。项目宪法及其引用的现行约束决定验收要求，不使用上游的可选测试提示降低项目门禁。按当前阶段读取 `.agents/project-harness/constraints/测试规范/门禁规范.md`、`用例规范.md`、`稳定性规范.md`；涉及实现方案、任务或运行验证时，继续读取相关端的自测规范、单元/冒烟/回归规范及相关冒烟案例。启动方式只从相关端构建规范获取。缺文件或存在占位时报告缺口，不跳过必需约束。

不要求用户重复选择是否遵守项目已经采用的测试要求。仅澄清无法查证的业务歧义或必要权限。本次调用不自动调用其它技能，扩展 hook 也不能绕过点名调用和外部操作授权。

在 plan.md 中建立验收场景与验证方法的对应关系，说明已有用例、必要新增测试、影响范围与环境缺口。规则和长期命令仅引用其规范源，不抄写成第二套。测试尚未建立时计划补齐，不将其判为不适用。

附带人读版：本次写出 plan.md、research.md、data-model.md、quickstart.md 或 contracts/ 下契约后，对本次实际生成的每份产物，按 `.agents/skills/ph-human/references/human-writing.md` 的规范把它的当前内容写成同功能目录的人读伴读：正文先写仓外临时文件，再经 `python3 .agents/scripts/ph_human.py publish` 发布，文件映射与文末机器元数据由脚本处理，正文不自带元数据。伴读是快照解释，不是权威规则或验收源；缺产物不编伴读，本次未写机器产物时不生成。直接读取该写作规范执行，不调用 ph-human，也不触发任何其他技能。



## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Pre-Execution Checks

**Check for extension hooks (before planning)**:
- Check if `.agents/project-harness/runtime/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_plan` key
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

1. **Setup**: Run `.agents/project-harness/runtime/scripts/bash/setup-plan.sh --json` from repo root and parse JSON for FEATURE_SPEC, IMPL_PLAN, FEATURE_DIR, BRANCH. For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

2. **Load context**: Read FEATURE_SPEC and `.agents/project-harness/constitution.md`. Load IMPL_PLAN template (already copied).

3. **Execute plan workflow**: Follow the structure in IMPL_PLAN template to:
   - Fill Technical Context (mark unknowns as "NEEDS CLARIFICATION")
   - Fill Constitution Check section from constitution
   - Evaluate gates (ERROR if violations unjustified)
   - Phase 0: Generate research.md (resolve all NEEDS CLARIFICATION)
   - Phase 1: Generate data-model.md, contracts/, quickstart.md
   - Re-evaluate Constitution Check post-design

## Mandatory Post-Execution Hooks

**You MUST complete this section before reporting completion to the user.**

Check if `.agents/project-harness/runtime/extensions.yml` exists in the project root.
- If it does not exist, or no hooks are registered under `hooks.after_plan`, skip to the Completion Report.
- If it exists, read it and look for entries under the `hooks.after_plan` key.
- If the YAML cannot be parsed or is invalid, do not skip silently: tell the user that `.agents/project-harness/runtime/extensions.yml` could not be read (include the parser error) and that no hooks were checked, including any mandatory (`optional: false`) hooks registered there, then continue to the Completion Report.
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- When constructing command invocations from hook command names, replace dots (`.`) with hyphens (`-`). For example, `speckit.git.commit` → `$speckit-git-commit`.
- For each executable hook, output the following based on its `optional` flag:
  - **Mandatory hook** (`optional: false`) — **You MUST emit `EXECUTE_COMMAND:` for each mandatory hook**:
    ```
    ## Extension Hooks

    **Automatic Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}
    ```
    After emitting the block above you MUST actually invoke the hook and wait for it to finish before continuing. Run it the same way you would run the command yourself in this agent/session (the invocation may differ from the literal `{command}` id shown above, e.g. a skills-mode agent runs it as `/skill:speckit-...` or `$speckit-...`). Emitting the block alone does not run the hook.
  - **Optional hook** (`optional: true`):
    ```
    ## Extension Hooks

    **Optional Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```

## Completion Report

Command ends after Phase 1 design. Report branch, IMPL_PLAN path, and generated artifacts.

## Phases

### Phase 0: Outline & Research

1. **Extract unknowns from Technical Context** above:
   - For each NEEDS CLARIFICATION → research task
   - For each dependency → best practices task
   - For each integration → patterns task

2. **Generate and dispatch research agents**:

   ```text
   For each unknown in Technical Context:
     Task: "Research {unknown} for {feature context}"
   For each technology choice:
     Task: "Find best practices for {tech} in {domain}"
   ```

3. **Consolidate findings** in `research.md` using format:
   - Decision: [what was chosen]
   - Rationale: [why chosen]
   - Alternatives considered: [what else evaluated]

**Output**: research.md with all NEEDS CLARIFICATION resolved

### Phase 1: Design & Contracts

**Prerequisites:** `research.md` complete

1. **Extract entities from feature spec** → `data-model.md`:
   - Entity name, fields, relationships
   - Validation rules from requirements
   - State transitions if applicable

2. **Define interface contracts** (if project has external interfaces) → `/contracts/`:
   - Identify what interfaces the project exposes to users or other systems
   - Document the contract format appropriate for the project type
   - Examples: public APIs for libraries, command schemas for CLI tools, endpoints for web services, grammars for parsers, UI contracts for applications
   - Skip if project is purely internal (build scripts, one-off tools, etc.)

3. **Create quickstart validation guide** → `quickstart.md`:
   - Document runnable validation scenarios that prove the feature works end-to-end
   - Include prerequisites, setup commands, test/run commands, and expected outcomes
   - Use links or references to contracts and data model details instead of duplicating them
   - Do not include full implementation code, model/service/controller bodies, migrations, or complete test suites
   - Keep this artifact as a validation/run guide; implementation details belong in `tasks.md` and the implementation phase

**Output**: data-model.md, /contracts/*, quickstart.md

## Key rules

- Use absolute paths for filesystem operations; use project-relative paths for references in documentation
- ERROR on gate failures or unresolved clarifications

## Done When

- [ ] Plan workflow executed and design artifacts generated
- [ ] Extension hooks dispatched or skipped according to the rules in Mandatory Post-Execution Hooks above
- [ ] Completion reported to user with branch, plan path, and generated artifacts

## PH 下一步建议（固定输出）

完成报告与 extension hook 处理结束后、结束本次回复前，向用户原样输出下面代码块内的固定文案作为收尾。这只是建议：本技能不自动调用任何技能，等用户明确点名后再执行。

```text
下一步建议执行:
- 压缩会话（/compact）后再继续
- 后续可执行的 skills（按场景选择）:
  - $ph-checklist - 为需求质量单独生成检查清单
  - $ph-tasks - 把计划拆解为可执行任务清单
```
