---
name: ph-worktree-enter
description: "Create and register an isolated PH task worktree, optionally bound to a feature and parallel task group. Invoke only when the user explicitly names ph-worktree-enter and requests it; ordinary descriptions or mentions do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills. Creation does not authorize commits, implementation, merge, exit or cleanup."
---

# Enter an isolated task worktree

Read `.agents/AGENTS.md`, [Git rules](../../project-harness/constraints/工程规范/Git规范.md) and [question rules](../../project-harness/constraints/harness规范/对用户提问规范.md). Use the shared `.agents/scripts/ph_worktree.py`, not hand-written Git orchestration.

## Scope and assignment

This skill creates and registers an explicitly requested environment. It does not install dependencies, start services or edit application code. Source means the primary worktree's current attached branch, not necessarily main. Do not switch to main/master/develop or another baseline. The runtime supports one-level linked worktrees from a primary tree; unsupported bare/submodule/nested configurations stop.

Choose a short unoccupied task branch following project naming rules; use only ASCII letters, digits, hyphen, underscore and slash. Do not ask again for a normal generated name or creation already requested. Use `--existing` only for an explicitly requested existing branch; if unavailable/occupied, stop instead of substituting another existing branch.

For SDD work, establish the feature's repository-relative path, feature ID and assigned task IDs. Identify exclusive ports, databases and other resources. Inspect `enter --help` for `--feature-path`, `--feature-id`, repeatable `--task-id` and `--resource key=value`. Multiple independent trees may coexist, but shared files and external resources need ownership or serialization; worktrees do not isolate services.

## Dry-run and source protection

Run:

```text
python3 .agents/scripts/ph_worktree.py enter --repo <primary-worktree> --branch <task-branch>
```

Include the intended SDD assignment in dry-run and apply. Review sourceBranch/sourceHead, taskPath, verification commands, sourceDirty, wipRisks and feature/resource conflicts. Commands execute repository code: check their scope and safety before approving them.

A merge in progress or unmerged entries stops creation before any WIP question. Do not treat this as an invitation to resolve conflicts, invoke exit or retry creation. Never stash, force, reset --hard or move conflicting content out of the way.

For a clean source, the user's explicit creation request authorizes the reviewed normal plan. Apply with both source snapshot bindings:

```text
python3 .agents/scripts/ph_worktree.py enter --repo <primary-worktree> --branch <task-branch> --expect-source-branch <sourceBranch> --expect-source-head <sourceHead> --apply
```

For staged, unstaged or untracked changes, first use the exact unified WIP question in the Git rules through the host's question tool. Show directory, branch, all three path sets and proposed `wip: <description>`. The fixed choices are the project's yes/no labels, with the host's free-input option retained. Rejection, cancellation or no answer preserves changes and stops; do not reword the question to obtain agreement.

After explicit WIP consent, a single enter apply combines the approved WIP and creation. Add `--wip-message`, `--expect-source-branch`, `--expect-source-head`, `--expect-staged`, `--expect-unstaged`, `--expect-untracked` from that dry-run. Do not split into independent add/commit/enter operations. The standalone wip command is not this workflow's substitute.

Changed branch, HEAD or path/status sets invalidate the snapshot and require fresh preflight and consent. Ordinary edits within the same displayed path set do not require byte-by-byte reapproval under the existing WIP contract. Consent is consumed by that one commit; later dirty-state blockers need their own consent. Suspected secrets, oversized files or unresolved conflicts block the whole operation, not a partial commit. Ignored files are excluded; do not blindly git add -A. The runtime binds state but cannot prove human consent.

## Registration and handoff

The runtime checks ignored `.worktrees/`, safe paths, branch occupancy and Git registration, creates a readable slug/hash path, and records the source and assignment under `.worktrees/.ph/sessions/`. Do not rename directories or edit session JSON manually. Real directory and containment checks reject unsafe symlink/junction redirection.

PH write operations share a per-primary-worktree lock. Dry-run does not create a lock or refresh the index. A lock conflict stops; do not seize a stale-looking lock without confirming the original process stopped.

Verify the new registered tree, branch and assignment match the plan and the source branch has not switched. Report taskPath, assigned scope and resource limitations. Suggest ph-implement for prepared tasks and explain that ph-worktree-exit is independently invoked later. Do not invoke either skill. Existing sessions survive upgrades unchanged; missing recovery evidence must not be invented.
