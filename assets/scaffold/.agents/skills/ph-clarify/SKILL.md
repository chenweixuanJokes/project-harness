---
name: ph-clarify
description: "Inspect and clarify a recorded requirement before design. Invoke only when the user explicitly names ph-clarify and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Clarify a requirement

Read [the development contract](../ph-require/references/process.md). Select the feature explicitly and read its requirement or mapped legacy spec in full. For a small change, read change.md.

## Procedure

1. Inspect goals, roles, main outcomes, exclusions, data ownership, permissions, meaningful failure boundaries, compatibility and acceptance measurability. Compare current implementation and project rules. Do not manufacture questions merely to complete a checklist.
2. Classify each gap as a verifiable fact, a user decision or a nonblocking detail. Investigate facts yourself. Defer implementation choices to design unless they alter the user's contract.
3. Present one blocking decision at a time through the host's question capability. Explain the observed ambiguity and its consequences, offer distinct grounded choices when suitable, and preserve the actual answer. Do not ask whether existing mandatory project tests should apply.
4. Update only the affected requirement passages and append a concise clarification record containing the question, answer, date and affected IDs. Preserve previous decisions and supplied language that remains valid. Do not silently convert a new request into an old acceptance criterion.
5. Recheck the whole requirement for contradictions introduced by the answers. If blocking issues remain or the user cannot answer, leave the stage blocked/draft with a precise explanation. Otherwise record a reviewed requirement using the shipped runtime and an honest review note; this records clarity, not implementation or user acceptance.
6. If the requirement changed after design/tasks/checks existed, report which downstream artifacts require reassessment. Do not regenerate those stages or leave their earlier approvals presented as current.
7. Refresh only the changed source's supported companion. Summarize confirmed decisions and unresolved issues; recommend ph-design when ready.

## Completion

Every material uncertainty is resolved or explicitly blocking. Requirement review never marks tests, implementation or user acceptance as passed. No application code or unrelated document is changed.
