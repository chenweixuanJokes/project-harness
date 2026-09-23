---
name: ph-worktree-exit
description: "Deliver a registered PH task worktree to its recorded source, verify the merged result and optionally clean up after separate consent. Invoke only when the user explicitly names ph-worktree-exit and requests it; ordinary descriptions or mentions do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills. Invocation authorizes the scoped merge, not a commit, push, branch deletion or worktree cleanup."
---

# Exit an isolated task worktree

Read `.agents/AGENTS.md`, [Git rules](../../project-harness/constraints/工程规范/Git规范.md) and [question rules](../../project-harness/constraints/harness规范/对用户提问规范.md). Use `.agents/scripts/ph_worktree.py` in the registered linked worktree. Never guess a session from its directory name or clean all trees.

## Delivery boundaries

The target is the source worktree/branch recorded at entry. Changed source branch, rewritten source history, changed task branch or unverified session identity blocks delivery. No automatic push, stash, reset --hard, --no-verify, force removal or branch -D. Default task branches remain after cleanup.

Multiple independent task trees may develop concurrently; PH Git writes and merges into a common source serialize through the delivery lock. A lock only coordinates PH processes, not arbitrary external Git commands. Do not seize a lock without confirming the original process stopped.

For SDD assignments, inspect feature/task/resource and pending sibling information. A merged child task is not whole-feature acceptance or archiving. Code, documentation, cases and tracked feature records must travel together; preserve evidence in durable delivered paths before cleanup. A snapshot archived before merge retains its historical pre-merge meaning. Do not invoke ph-archive or silently mark the requirement accepted.

## Preflight and commits

Run the read-only dry-run:

```text
python3 .agents/scripts/ph_worktree.py exit --repo <linked-worktree>
```

All dry-runs are read-only, including resumed phases: no verification command, merge, session mutation or index refresh. Review taskTree, sourceDirty, wipRisks, target and feature assignment.

An existing merge/conflict takes precedence over WIP: follow conflict recovery below, never stage unresolved entries into a WIP. Otherwise handle a dirty source in that source worktree using the Git rules' unified WIP question and the script's standalone wip command after consent. It is a separate blocker, not part of the task-tree WIP. Then repeat exit dry-run.

For a dirty task tree, show branch, HEAD, all staged/unstaged/untracked paths and the proposed `wip: <description>`, then actually ask the exact unified WIP question in the Git rules using the host tool. Preserve its yes/no labels and host free input. Consent covers one WIP, not arbitrary submission. Invocation of this skill alone never confirms a commit. A separately and explicitly specified formal commit may be performed as authorized; do not silently substitute one for refused WIP.

After WIP consent, use a single exit apply with `--wip-message`, `--expect-branch`, `--expect-head`, `--expect-staged`, `--expect-unstaged`, `--expect-untracked` taken from the reviewed snapshot. Do not split task WIP and exit into two invocations or manually git add/commit. Branch/HEAD/path-status changes require new preflight and consent; same-path ordinary content edits do not trigger byte-by-byte reconfirmation under the existing contract. Consent is consumed by that commit.

Secrets, oversized changes, conflicts or an undeliverable source block before committing; no partial submission or blind git add -A. Ignored files stay excluded. Rejection/cancellation/no answer preserves all content and stops without rewording the question. The script does not itself prove human authorization.

For clean trees:

```text
python3 .agents/scripts/ph_worktree.py exit --repo <linked-worktree> --apply
```

The script runs the entry-frozen verification commands on the task tree, merges with Git's normal fast-forward/merge behavior and autostash disabled, then verifies the merged source. Later task-branch edits to command configuration cannot silently change the frozen delivery checks. Verification that changes Git-visible state stops for review. Passing task-tree checks alone is not passing merged-source checks.

## Conflicts and interrupted delivery

1. Confirm MERGE_HEAD, unmerged paths and the recorded mergeSourceBranch/mergeSourceHead/mergeTaskHead identity. Mismatch or missing identity blocks; do not adopt a foreign merge.
2. Ask the exact project conflict question through the host tool, with choices equivalent to “keep the scene; I will resolve and continue” and “abort this merge.” No automatic ours/theirs, force or agent resolution option. Agent conflict resolution needs separate explicit authorization; business trade-offs still require the user.
3. Keeping the scene means stop and wait, not poll. Only after the user explicitly asks to continue following resolution/staging, verify no unmerged paths and the same merge identity, then run `continue --repo <linked-worktree> --apply`. This creates a merge commit, not a WIP.
4. An explicit abort choice authorizes only that merge's `abort-merge --repo <linked-worktree> --apply`; explain that conflict-resolution edits are discarded while the task branch and worktree remain. Verify identity first. Do not retry the merge automatically.
5. No answer/cancellation means no abort, WIP or new question channel.

Use `doctor --repo <primary-worktree>` for read-only diagnosis. For a corrected branch after committed/merge_verify_failed delivery, inspect redeliver dry-run before `redeliver --repo <linked-worktree> --apply`. Do not reuse failed verification as current proof. Registration recovery uses explicit `recover --repo <primary-worktree> --session <path> --action archive|adopt --apply` only for states the tool can prove recoverable and with the requested scope. Old sessions lacking needed merge evidence remain blocked; never invent fields.

## Cleanup and completion

After successful merge and post-merge checks, separately ask whether to remove this session's isolated directory using the project's cleanup wording. Refusal leaves the tree and session available for later cleanup. Before removal, recheck source identity, inclusion, clean task state, complete delivery of feature/evidence material and any ignored files. Review `featureEvidenceIssues`: missing, changed or unpreserved evidence blocks cleanup, not the independently authorized merge. A matching tracked feature file in the source or a tracked checksummed archive copy can preserve evidence; an external path merely existing is not enough. No mandatory archive-before-exit order is introduced. Ignored data blocks cleanup until the user preserves or disposes of it; no generic force-ignore bypass.

Only with explicit cleanup consent and all protections satisfied:

```text
python3 .agents/scripts/ph_worktree.py exit --repo <linked-worktree> --cleanup --apply
```

Report source branch, actual merged verification, pending sibling work, archive state and cleanup separately. Session-record archiving is not requirement archiving. Do not claim user acceptance or feature convergence from a successful Git operation.
