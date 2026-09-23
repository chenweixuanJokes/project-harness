---
name: ph-tasks
description: "Plan concrete implementation tasks and their unit tests from reviewed requirements and design. Invoke only when the user explicitly names ph-tasks and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Plan implementation tasks

Read [the development contract](../ph-require/references/process.md). Require the current requirement and design review to be ready; a stale review or unresolved blocker is not approval. Small-change preparation follows the equivalent checks within ph-small-change.

## Procedure

1. Read requirement, design, review and applicable testing/build rules. Inspect the files, symbols, callers, existing tests and commands that the plan will rely on. Reuse existing implementations and tests before proposing new abstractions.
2. Decompose by independently verifiable outcomes and actual dependencies. Use stable T identifiers; retain existing IDs and completed-task history when revising. Each task states requirement/design references, purpose, prerequisites, owned files/symbols, concrete changes, necessary unit tests, verification and completion criteria.
3. Make code facts definite, not conditional guesses such as “if a helper exists, reuse it.” Real runtime branches and unresolved external constraints are different: describe required behavior and mark genuine blockers. Do not prescribe brittle line numbers without identifying the symbol or surrounding structure.
4. Include unit-test creation or updates within each applicable implementation task, including a reproducing regression for a bug fix. Tests are required by project rules, not by whether the user asked for them. Reuse covering tests; pure documentation/configuration tasks use an honest appropriate check rather than invented unit tests.
5. Add necessary test infrastructure, test data, documentation, reusable smoke-case implementation and evidence tasks. The later ph-verify-plan stage plans whole-result checks; it must not become a place to discover all unit tests were omitted.
6. Mark safe parallel groups with file ownership, interface dependencies and external resource constraints. Shared files and indexes have one coordinator. Worktree allocation is only a proposed mapping until ph-worktree-enter is explicitly used; do not create branches or isolated trees here.
7. Write tasks.md using `runtime/templates/sdd/tasks-template.md`. Review coverage, duplicate work, dependency gaps, conflicting edits and measurable completion. For a large plan, bounded task expansion and independent review may use subagents; reconcile the full plan before handing it off.
8. Record the plan as draft/pending execution, refresh its companion, and report task groups, test obligations and remaining blockers. Recommend ph-verify-plan, not immediate implementation.

## Completion

An implementer can carry out each task without redesigning the feature. Required unit tests are part of the tasks, all requirements are covered or explicitly blocked, and no tasks have been marked complete without execution.
