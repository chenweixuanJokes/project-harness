---
name: ph-small-change
description: "Prepare a bounded bug fix or small local change with concise requirements, design, tasks and verification. Invoke only when the user explicitly names ph-small-change and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Prepare a small change

Read [the development contract](../ph-require/references/process.md). This is a planning entry, not a shortcut to editing application code. Reduced paperwork never reduces testing or authorization requirements.

## Eligibility

Use this route when the expected result and affected behavior are clear, the scope is local, compatibility is understood and a finite set of checks can validate the change. Judge by consequences and uncertainty, not line count.

Investigate a claimed simple bug before accepting that classification. Public API changes, data migration, authentication/security semantics, core business changes, broad cross-module effects or unresolved product choices require the full route. Preserve what has already been learned and recommend the relevant requirement/design stage; do not start the full workflow automatically or discard the record.

## Procedure

1. Read the current behavior, relevant code/tests and applicable constraints. For a bug, establish reproducible input, observed behavior and expected behavior; distinguish confirmed cause from hypothesis. Investigation may run safe checks within scope, but this preparation stage does not implement the fix.
2. Resolve factual gaps yourself and ask only for material user decisions. Write change.md with goal, existing behavior to preserve, exclusions, affected locations, confirmed cause or remaining uncertainty, minimal solution and user outcome acceptance.
3. For a new eligible change, dry-run then apply `ph_sdd.py create --repo <root> --feature <id> --flow small --title <title>`. Use the shipped change template as guidance. Do not create separate empty requirement/design files. Existing small or legacy records retain their identities and source history.
4. Review the concise requirement/solution for omissions and constraint conflicts within this invocation. Before marking change reviewed, list each remaining uncertainty and decide whether its answer could change the proposed behavior, compatibility or scope. If it could, keep change draft, carry the decision as a blocking prerequisite on the affected implementation task, and stop before recommending implementation. Being outside this repository or awaiting user acceptance does not resolve such a dependency. A missing demonstration of an already agreed result is different: keep it as an explicit verification limit. Record the actual review, not a ceremonial pass.
5. Write tasks.md with stable IDs, concrete owned files, prerequisites, necessary unit tests, verification and completion criteria. Carry any unresolved implementation condition into the affected task's prerequisites; a general review mark does not resolve it. A bug task includes a reproducing regression where applicable. Reuse covering tests and avoid unrelated cleanup.
6. Write verify-plan.md and acceptance.md with the same semantics as the full route: the agent checks the working result and affected regression; the user confirms a prepared representative outcome. Map technical criteria to agent checks even if an existing requirement labels them AC; do not ask the user to verify tests passing or unchanged internal behavior. Read the shipped templates and project testing rules directly, without invoking ph-tasks or ph-verify-plan. Unit tests stay inside tasks, and existing full-suite requirements still apply.
7. Check coverage and source freshness. Publish supported companions and report why the change qualifies for this route, the minimal plan, checks and any blockers. Recommend ph-implement only when preparation is ready.

## Completion

A small change has an honest, compact requirement/solution, executable tasks, agent checks and an outcome-focused user guide. No implementation, branch creation, commit or acceptance result has been inferred from a request to prepare.
