---
name: ph-archive
description: "Archive a verified requirement and consolidate actual project documentation and reusable smoke cases. Invoke only when the user explicitly names ph-archive and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills. Archiving does not authorize Git commits, merges, worktree exit or cleanup."
---

# Archive and consolidate a requirement

Read [the development contract](../ph-require/references/process.md), the project's document governance rules and applicable test case/gate rules. This is feature archiving, not ph-memory-archive and not worktree exit.

## 1. Establish completion and location

Read current requirements/change, design/review, tasks, verification plans, actual evidence and the user's recorded outcome decision. Inspect repository and worktree assignment. Confirm required work is done, agent checks are current, user acceptance is recorded or an explicit justified applicability decision exists, and no blocking findings remain.

A worker branch cannot archive an entire feature while sibling work remains unintegrated. Use the worktree runtime's read-only doctor/group information where relevant. Distinguish a verified complete feature on a task branch from a merged delivery: the former can preserve a snapshot with an explicit not-merged status, but cannot claim source-branch verification.

If evidence is stale, the user has not answered, or required work remains, report the exact blocker and appropriate stage. Do not mark completed merely to save history. Preserve incomplete material without mislabeling it as a completed requirement.

## 2. Consolidate current project facts

Compare the implemented result with existing project documents. Update only affected facts: feature map, product behavior, architecture, data contracts, interfaces, usage/build guidance and operational instructions. Prefer updating the existing authoritative location over creating duplicates. Business docs outside PH remain project-owned; modify only documents directly affected by this authorized requirement.

Within PH documents, maintain directory README indexes and honest owner/status/last_verified/verified_against/refresh_trigger fields. Unknown owners remain unknown. A partial review does not establish whole-page verification. Preserve unrelated customization, links and still-valid text.

Rules are separate from facts. Do not promote implementation choices or remembered advice into constraints. Only already authorized, explicitly adopted rule changes may enter constraints, with an updated constitution navigation and major architecture decisions recorded under the project's ADR policy. Unresolved normative changes block that item, not justify weakening a gate. Do not call memory skills or write memories as an automatic archival side effect.

## 3. Consolidate reusable test cases

Read verify-plan's proposed case destinations and the actual tested implementations. Reuse stable case IDs, deduplicate overlapping cases and link requirements, scripts and evidence.

- Keep unit/interface automated tests in the project's actual test directories; archive does not postpone or replace their implementation.
- Register or update verified reusable smoke scenarios in the corresponding frontend/backend PH case library, one case per file according to the existing template.
- Preserve preconditions, safe data setup, operations, assertions, cleanup, actual script location and evidence. Do not turn temporary commands, personal paths, temporary ports or secrets into long-lived configuration.
- Record failed/unexecuted candidates truthfully; they cannot appear in a passing consolidation report. If a required case remains unimplemented or fails, return a traceable task rather than declaring archival completion.
- The user's representative outcome journey is not a second technical test suite and should not be copied verbatim into a mandatory test library.

Run applicable checks after documentation/case changes. New or changed runnable cases require actual validation under project gates. Reassess evidence affected by these changes before the snapshot is finalized.

## 4. Preserve the history

Write an archival summary in the active feature record: scope delivered, source/evidence state, user conclusion, document/case destinations, known limitations and actual merge/release state. Record what did not need updating and why; do not create filler documents.

Use the shipped ph_sdd.py archive command, dry-run before apply, to preserve a checksummed feature snapshot and index. Keep the stable active feature path and references; do not move it away or replace source history with a summary. Repeated archival of the same state should be idempotent. Verify the snapshot inventory and live links, and report any mechanical or semantic failure separately.

## 5. Worktree handoff

Do not invoke ph-worktree-exit or its apply commands. When archiving inside a worktree, clearly report that code, documents, cases and snapshot are still on that branch and must accompany its later authorized delivery. When archiving after a merge, use the actual integrated state and post-merge verification.

The independent exit skill handles submission/merge, post-merge checks and separately confirmed cleanup. Archiving is not authorization for any of those actions. Preserve evidence outside a soon-to-be-cleaned environment or in tracked delivered artifacts before cleanup; a link to a disappearing task directory is not durable evidence.

## Completion

The requirement history is recoverable, affected project facts and reusable smoke cases reflect verified reality, references are valid, and verification/archive/integration/release statuses are reported independently. No unrequested Git, memory or external action occurred.
