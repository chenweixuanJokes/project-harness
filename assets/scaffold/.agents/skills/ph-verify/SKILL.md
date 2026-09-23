---
name: ph-verify
description: "Run agent-owned result verification, then obtain user outcome acceptance; append traceable repair tasks for failures. Invoke only when the user explicitly names ph-verify and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Verify the delivered result

Read [the development contract](../ph-require/references/process.md). This stage writes verification records and repair tasks, not application code. It does not commit, merge, exit a worktree or archive a requirement.

## 1. Establish the state being checked

Select the feature explicitly. Read original requirements/change, design/review, tasks, verify-plan, acceptance and prior evidence. Run read-only runtime status/check. Confirm whether the current tree is the integrated feature or only a worker's task branch. For the latter, report scoped checks without claiming whole-feature acceptance.

Record the actual code state including uncommitted changes, environment, configuration and verification scope. Reassess prior evidence affected by changes. Inspect project test gates rather than assuming the plan contains all mandatory checks.

## 2. Agent self-test and intent review

Execute the planned whole-result checks through real entry points: main journey, integration, critical errors, permissions, affected regression and applicable UI/visual/output checks. Use the host's mandated browser/visual tool or delegated capability. Lack of a required tool is a blocked check, not permission to replace execution with reading source.

Unit tests were written and run inside tasks; inspect their evidence and rerun when changed code or project gates require it. Do not create a duplicate unit-test planning stage or waive the full suite required by the project. Keep failed, not-run and justified not-applicable outcomes separate. Follow the stability rules for flaky behavior rather than retrying until green.

Compare the implementation against each original requirement and relevant design decision, looking for missing, partial, contradictory and unrequested behavior. Trace each required outcome through an actual entry point. A helper's return value, a proposed interface or an approved design is not proof that the promised behavior exists. If the design omits or weakens an original requirement without an explicit scope decision, report a design gap rather than accepting the reduced implementation. Passing the tests that happen to exist is not proof that omitted requirements were implemented.

Record actual operations, results and evidence in verification.md. Do not check off a scenario without evidence. Agent checks must pass before asking the user to experience the result.

## 3. Route failures into work

For each actionable failure, record a stable finding ID, requirement/check reference, observed/expected behavior, evidence and the smallest verifiable repair. Search existing unresolved tasks by finding/reference before appending. Repeated failure updates its attempt history rather than producing duplicate tasks.

Append repair tasks without renumbering, rewriting completed history or silently expanding scope. Require suitable regression coverage. Stop here when agent checks fail and recommend ph-implement; do not repair application code in this skill or invoke the next skill automatically.

A design flaw returns to ph-design; an unresolved intent question returns to ph-clarify; new desired functionality requires explicit scope handling. Unrelated existing failures remain visible and subject to project gates, not silently removed from the result.

## 4. User outcome acceptance

After agent checks pass, prepare the actual environment, safe representative data and usable entry point described in acceptance.md. Confirm readiness before handing it to the user. Present a short business journey and the useful result to judge, not logs, SQL assertions or technical edge-case tests.

Use the host's question capability to collect the user's actual conclusion. Record the answer and affected outcome IDs. If unavailable, cancelled or unanswered, stop at waiting-for-user; never infer approval. For an internal change with no meaningful manual operation, explain the evidence-based alternative and record an explicit applicability decision, not a fictitious user pass.

If feedback shows the agreed outcome is unmet, append/update repair work and recommend ph-implement. If it introduces a new preference or scope, make that distinction before changing the requirement. After fixes, rerun affected agent checks and required regression first; ask the user to reconfirm only affected outcomes unless the broader experience changed.

## 5. Conclude

Record the two decisions separately with the runtime. Set `verification` to `passed` when all required agent checks and intent review pass on the recorded state; this does not require a user answer. Keep it `draft` if a required check failed or remains unperformed. Set `acceptance` to `passed` only for an actual user conclusion, or to `not_applicable` only for a justified applicability decision. Waiting for the user or preparing their environment does not erase valid agent results, and neither permits marking acceptance complete.

Refresh supported companions. Report agent verification, acceptance readiness, user acceptance, unresolved findings, integration and archive status separately. Recommend ph-archive only when the complete feature is ready; a task branch or pending user response is not convergence.
