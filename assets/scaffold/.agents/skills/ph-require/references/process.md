# PH development contract

Read this contract at the beginning of each PH development stage. It defines shared boundaries, not an automatic workflow. User-facing artifacts default to Simplified Chinese unless the project or user specifies another language.

## Authority and scope

Read the project's `.agents/AGENTS.md`, `.agents/project-harness/constitution.md`, and the constraint documents whose reading conditions apply. For planning, implementation, verification and archiving, read the test gate, case and stability rules under `.agents/project-harness/constraints/测试规范/`; then the applicable frontend/backend build and self-test rules. Existing project gates are not optional. Missing or unfilled rules are gaps to report, not permission to waive testing.

Only run the explicitly requested skill. A mention, an ordinary task description, or a suggested next step is not an invocation. Feedback and continuation within an explicitly started stage do not require repeated invocation. Do not automatically invoke another skill. An approved design is not permission to implement, create a worktree, commit, merge, publish or clean up. Use the host's actual question tool for necessary decisions and its dedicated approval mechanism where required. Never request secrets through chat or ordinary questions.

Resolve facts from code and current documents before asking. Ask only for decisions that affect intent, scope, acceptance, compatibility or authorization. Preserve confirmed answers and history. Stop dependent work on unresolved decisions; independent authorized investigation may continue.

## Feature identity and artifacts

Keep active records under `.agents/project-harness/specs/<feature>/`. Prefer an explicit feature path. Otherwise inspect current worktree assignment and available feature records; ask when several candidates remain. Do not silently select the most recently edited feature or use a shared global pointer as a parallel-work coordination mechanism.

| Artifact | Responsibility |
| --- | --- |
| requirement.md | Goal, users, scope, exclusions, constraints and user outcome acceptance |
| design.md | Product behavior, interaction and technical solution |
| review.md | Design findings, decisions and reviewed source state |
| tasks.md | Ordered implementation and repair work, including necessary unit tests |
| verify-plan.md | Agent-owned whole-result checks, expected outcomes and case-library destinations |
| acceptance.md | Prepared user experience and outcome confirmation guide |
| verification.md | Actual execution evidence, failures, user feedback and current conclusions |
| change.md | Small-change requirement and minimal design instead of separate requirement/design documents |

The executable helpers are `.agents/scripts/ph_sdd.py` and `.agents/scripts/ph_human.py`, relative to the project root; `project-harness/runtime/` contains templates, not those scripts. Use `python3 .agents/scripts/ph_sdd.py --help` and subcommand help for the exact mechanical interface. Inspect the declared path before reporting a missing tool. These helpers assist with paths, structure and state; they cannot certify semantic correctness or real user approval. Do not hand-edit machine metadata to bypass a failed check.

For an existing feature, respect its recorded artifact mapping. Legacy `spec.md` and `plan.md` remain readable sources for requirement and design; preserve original IDs, Q&A, attachments and evidence. Do not rewrite a historical feature merely to rename its files. Missing modern gates must be evaluated, not inferred from old checkmarks. Small changes may use concise sections, but share the same task, verification and authorization semantics. Do not create empty optional documents.

Use stable requirement, acceptance, task and finding IDs. Preserve existing IDs. Link a task to its requirement/design basis and a check to the intended outcome. A checkbox is progress, not proof of execution. Record source changes so a previous review or verification can be identified as requiring reassessment.

## Evidence and ownership

Record the actual command or operation, time, code state including uncommitted changes, relevant configuration/environment, result and evidence location. Distinguish passed, failed, not run and justified not applicable. Missing tests are not not-applicable; reading code is not running tests. Keep prior results when new results supersede them.

Relevant code, dependency, configuration, environment, requirement or design changes require reassessing prior evidence. Reuse only evidence still applicable to the current state. A recorded fingerprint is a drift signal, not a proof of environment equivalence. Do not count a failed first run as passing merely because an unexplained retry succeeds; follow project stability rules.

The agent owns unit testing, integration checks, regression, environment preparation and technical diagnosis. The user accepts a usable outcome, not a second technical test suite. Invite user acceptance only after required agent checks pass. Supply a ready entry point, prepared data, a representative business path and the expected useful result. Do not ask the user to inspect logs, SQL, response codes or edge cases that the agent should have checked.

Silence, cancellation and inability to reach an environment are not approval. Record waiting or blocked. For an internal change without a meaningful user-operated scenario, explain that boundary and present appropriate delivery evidence; do not invent a manual exercise or claim the user approved it.

## Parallel work

Worktrees are optional execution environments. `ph-worktree-enter` and `ph-worktree-exit` are independent, explicitly invoked skills. Implementing or archiving a feature does not invoke them or authorize their effects.

Before delegating, assign task IDs, file ownership, dependencies, expected outputs and verification responsibilities. Independent workers may run in registered worktrees; shared files, lockfiles, generated assets, ports, databases and external services need a single owner or serialized access. Worktrees isolate files, not external resources.

Workers write their own task results and evidence. The coordinator updates the shared task list, indexes and integrated conclusion. A completed task branch is not a completed feature. Integrate through separately authorized exit operations, then verify the combined result. Do not claim pre-merge evidence proves the post-merge state.

## Companions and handoff

When writing or materially updating a supported authoritative artifact, read [human writing](../../ph-human/references/human-writing.md), compose its explanatory companion and publish it with `ph_human.py`; do not invoke ph-human. Only explain real source content. Report publication conflicts without overwriting user edits. A companion is neither an acceptance source nor a substitute for evidence. Do not regenerate unrelated companions or invent source-less snapshots.

Finish with the artifacts changed, checks actually performed, unresolved items and one or more appropriate next skill names. Suggest, do not invoke. A fresh conversation must be able to continue from the files and current repository state; clearing or compacting chat is optional, not a correctness gate.
