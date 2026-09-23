---
name: ph-verify-plan
description: "Prepare agent self-test scenarios and a user outcome acceptance guide before implementation. Invoke only when the user explicitly names ph-verify-plan and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Prepare verification and acceptance

Read [the development contract](../ph-require/references/process.md). This skill writes plans, not execution results. Require a reviewed design and usable task plan. Read original requirements as well as tasks: omissions in tasks must not disappear from acceptance.

## Agent self-test plan

Write verify-plan.md using `runtime/templates/sdd/verify-plan-template.md`. For each stable check ID, record:

- Requirement/outcome references and the risk being checked.
- Real entry point, environment, data, resource owner and preparation/cleanup.
- Concrete operation or intended command, assertions and expected useful result.
- Evidence to collect and the project gate it satisfies.
- Existing case ID to reuse, or a proposed new/updated case and its durable destination.

Cover the main journey, integration, significant errors, permissions, affected regression and applicable visual/output quality. Choose tools according to the host's capabilities and required delegation policies; a browser or visual check is not automatically a human task.

Unit tests belong inside implementation tasks. Do not duplicate their detailed plan here, but reference their evidence and any project-required full-suite rerun. Missing unit-test work or test infrastructure becomes a documented task-plan gap, not permission to proceed untested.

Reusable smoke cases belong in the applicable frontend/backend PH case library. Unit and interface test code stays in the project's test directories. Planned commands are unexecuted proposals, not persistent command configuration or proof of passing. Do not embed credentials, personal absolute paths or temporary ports as permanent case requirements.

## User outcome guide

Write acceptance.md using `runtime/templates/sdd/acceptance-template.md`. Describe what the agent will have prepared, where the user can access the result, the representative business journey and the useful outcome to judge. Keep the journey short without deleting meaningful acceptance goals.

For example, for filtered order export the agent checks permissions, empty results, file contents and regression. The user exports a prepared representative selection and decides whether the delivered file fits their actual reconciliation work. Do not ask the user to repeat edge-case testing, inspect logs or compare database rows.

Distinguish an outcome goal from an executable test assertion. Users may judge fitness, wording or workflow; agents own technical correctness. For internal changes without a meaningful manual scenario, document why and what evidence will be presented instead. This does not manufacture a user approval.

## Reconcile and hand off

Check that every requirement has an agent check, a user outcome criterion, or a justified alternative. If a requirement is untestable or preparation work is missing, report the specific gap and return to the appropriate design/task stage; do not quietly revise the agreed scope. Do not mark any runtime check passed.

After review, record the plan's reviewed state, publish supported companions, and recommend ph-implement. Worktree entry remains a separate explicit choice. The later ph-verify stage runs these checks and prepares the actual user entry point only after the agent's checks pass.
