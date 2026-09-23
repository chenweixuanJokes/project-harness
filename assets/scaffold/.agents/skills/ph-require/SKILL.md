---
name: ph-require
description: "Capture a clear requirement, scope and user outcome acceptance. Invoke only when the user explicitly names ph-require and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Capture a requirement

Read [the development contract](references/process.md). This stage captures intent; it does not design a solution or implement code.

## Procedure

1. Identify whether the user is starting a requirement or changing an existing one. Read relevant project facts and existing features to avoid duplicate work. Keep investigation proportional; do not turn a clear request into a full PRD interview.
2. Extract the problem, intended users, useful outcome, included scope, excluded scope, non-negotiable constraints and user acceptance goal. Separate supplied facts, verified facts, assumptions and unresolved decisions.
3. Ask only for missing decisions that change scope or acceptance. Use concrete questions grounded in the request. Do not ask the user to select technical details that belong in design. Never fill an unknown with a plausible business assumption just to finish a template.
4. Select an unambiguous feature ID without changing Git branches. For a new full feature, inspect `python3 .agents/scripts/ph_sdd.py create --help`, dry-run `create --repo <root> --feature <id> --flow full --title <title>`, then apply within the requested writing scope. Use `runtime/templates/sdd/requirement-template.md` under the PH home as a structure, not mandatory filler.
5. Write `requirement.md` in the feature directory. Assign stable FR/NFR identifiers and user outcome acceptance identifiers. For each main outcome, state the actor, starting situation, representative action and observable useful result. These are commitments, not a technical test procedure. Keep unknowns explicit and preserve prior wording in a change/clarification history rather than silently replacing decisions.
6. Record the requirement as draft until its clarity has actually been checked. Existing historical `spec.md` remains a valid mapped source; use the runtime's explicit adoption path when needed, preserving source bytes and leaving unverified statuses unclaimed.
7. Publish the supported companion according to the development contract. Report the goal, scope, acceptance outcomes and any blockers; recommend `ph-clarify` without invoking it.

## Completion

A reader can explain what is requested and how the user will recognize a satisfactory outcome. Remaining uncertainties are visible. No design, code, Git mutation or user acceptance result has been invented.
