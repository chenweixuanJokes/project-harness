---
name: ph-design-review
description: "Review implementation design against the original requirement and project constraints before task planning. Invoke only when the user explicitly names ph-design-review and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Review the design

Read [the development contract](../ph-require/references/process.md). This is a pre-task review: tasks.md is not a prerequisite. The review may write review.md and review state, not requirement, design or application code.

## Procedure

1. Read the full requirement and design with their current source state. Read applicable project constraints and enough implementation evidence to validate consequential claims. An earlier review is not valid merely because its file exists.
2. Build a coverage map from each requirement and user outcome to its design location. Inspect omissions, contradictions, unjustified additions, ambiguous interactions, failure states, data/permission boundaries, compatibility and testability. Treat the original confirmed intent as the acceptance authority; a design cannot silently narrow it.
3. Assess implementation feasibility, dependency ordering and parallel boundaries. Report assumptions unsupported by code or authoritative references. Do not require a detailed task list before checking the design.
4. When the scope justifies another perspective and the host supports agents, request an independent read-only review with bounded files and explicit questions. Integrate evidence rather than counting reviewers. Without subagents, perform the same checks locally and state the limitation; do not pretend independent review occurred.
5. Write review.md with reviewed source identities, coverage, stable finding IDs, severity, evidence, affected requirement/design references and recommended remediation. Findings must describe an actual consequence, not personal style preferences. Distinguish blocking findings from optional improvements.
6. If a blocking finding exists, keep design unapproved and recommend ph-design or ph-clarify as appropriate. Do not fix the design during the review or weaken the requirement to make it pass. If none exists, record design reviewed with the report as evidence using the runtime; preserve any required host/user approval separately. Agent review is not user approval.
7. Report the outcome and next step. Recommend ph-tasks only when design review and applicable approval gates are satisfied. Do not invoke it.

## Completion

The user can see whether the design covers the agreed requirement, the evidence supporting the conclusion, and what blocks task planning. A clean report is supported by actual checks, not an empty findings list copied from a template.
