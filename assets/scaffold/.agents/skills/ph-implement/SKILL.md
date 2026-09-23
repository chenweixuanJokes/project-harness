---
name: ph-implement
description: "Execute prepared implementation or repair tasks and their unit tests. Invoke only when the user explicitly names ph-implement and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Implement prepared tasks

Read [the development contract](../ph-require/references/process.md). This stage executes tasks; it does not substitute for whole-result verification or user acceptance.

## Before editing

1. Identify the current repository, feature and optional registered worktree/task assignment. Read requirement/change, design where applicable, review, tasks, verify-plan and acceptance. Run the runtime's read-only status/check operations and investigate stale source records. An empty/missing plan or unresolved design blocker stops dependent implementation.
2. Read applicable build, self-test, unit, smoke, regression and stability rules. Inspect current changes so user edits are preserved. Pending runtime checks in verify-plan are expected before implementation; do not treat them as failed requirement-quality reviews.
3. Confirm work is within the requested task scope. Use the current branch unless separately authorized otherwise. Do not invoke ph-worktree-enter, ph-worktree-exit, ph-verify or ph-archive. No automatic commits, merges, pushes, deployment or paid/external operations.

## Execute

4. Work in dependency order. For each task inspect the actual source, implement the smallest appropriate change and create/update its required unit tests. For a bug, obtain reproducing evidence before claiming the fix. Run task checks and project-required unit gates; unrelated failures are reported, not silently fixed or excluded.
5. When the host supports workers, delegate only independently verifiable tasks with explicit file ownership, dependency inputs, task IDs and test responsibilities. Use already authorized registered worktrees when assigned. Shared files, lockfiles, generated outputs and external resources have one writer or serialized access. Do not create new worktrees simply because parallel execution would be convenient.
6. Workers return bounded results, changed files, actual checks, evidence and unresolved items. They do not all rewrite the shared task list or project indexes. The coordinator inspects and integrates results; worker self-reports alone do not establish feature completion. A task branch is not the integrated final product.
7. If reality invalidates the design, stop affected work and describe the discrepancy. Do not silently change acceptance, invent a product decision or continue on a guessed interface. For local defects in the authorized implementation, repair and rerun the relevant task checks.
8. Update task progress only after its actual completion criteria hold. Preserve IDs and prior evidence. Record actual commands, code/environment state, results and evidence in verification.md or assigned worker evidence files. Mark incomplete/blocked work honestly; checkmarks do not replace running evidence.
9. Maintain implementation-linked documentation and test code as tasks require. Do not defer writing automated tests until archive. Keep reusable smoke-case candidates linked for later validated consolidation; do not claim unexecuted cases passed.

## Handoff

Reconcile assigned tasks and evidence, refresh supported companions and report implementation/unit-test results separately from whole-result verification, user acceptance and merge status. If all assigned work is ready, recommend ph-verify. If parallel pieces still require integration, describe the pending independently authorized worktree-exit operations and integrated verification. Do not declare the requirement delivered merely because task checkboxes are checked.
