# Human-readable companion writing

This is the shared writing rule for ph-human and development stages publishing companions directly. Reading it does not invoke another skill. Write user-facing companions in Simplified Chinese unless requested otherwise.

## Meaning

A companion explains what an authoritative artifact currently says, why the choices matter and what remains uncertain. It is an explanatory snapshot, not a rule, acceptance source, operating manual or replacement for the original. Missing companions do not invalidate originals; stale companions must not be presented as current.

Open with the source-relative path, generation date and an explicit snapshot statement saying the original governs and subsequent changes can make the explanation stale.

## Mapping and publishing

Use `python3 .agents/scripts/ph_human.py` to determine supported mappings and publish. New feature sources include requirement.md, change.md, design.md, review.md, tasks.md, verify-plan.md, acceptance.md and verification.md. Legacy spec.md, plan.md, research.md, data-model.md, quickstart.md, checklists and contracts remain supported according to the script. Constitution companions remain separate from feature artifacts.

Companions reside at the feature root and use `-human.md` names. Nested checklist/contract mappings are flattened by the script to avoid being mistaken for authoritative checklist entries. Name collisions are blocked, not silently overwritten. Any `-human.md` file is never an input source.

Write only the body to a temporary file outside the repository. The publisher adds source identity, sha256, producing skill, date and body hash. Do not forge the footer. User-modified bodies, malformed footer metadata, unsafe paths and missing sources are protected; report them rather than bypassing publication checks.

Historical analysis/issues snapshots have no current authoritative file to regenerate from. Preserve them as historical explanations; do not invent new analysis or external issue creation results.

## What to explain

- Requirement/change: problem, intended users, scope choices, preserved behavior and important outcome acceptance. Do not add new requirements.
- Design and legacy plan/research: why this approach was chosen, evidence, alternatives, dependencies and material risks. Keep technical boundaries visible.
- Review: material findings, coverage and what blocks implementation; do not turn an agent review into user approval.
- Tasks: order, dependencies, parallel ownership and what completion means. Preserve IDs.
- Verify-plan: what the agent will check, why those checks matter and reusable case destinations. Planned tests have not passed yet.
- Acceptance: what useful result the user will judge. An explanation is not the actual acceptance guide or the user's answer.
- Verification: what actually ran, actual results, evidence, missing checks and user feedback. Never upgrade failed, waiting or unexecuted states to passed.
- Models/contracts/quickstart: entities, relationships, consumers, compatibility and prerequisites.
- Constitution: project principles and when constraints apply; do not duplicate the entire rule set.

## Style

Organize around real reader questions. State a decision, its reason and cost rather than calling it superior without evidence. Preserve API paths, fields, versions, quantitative thresholds, task/requirement/acceptance IDs and other traceable identifiers exactly. Readability is not permission to delete technical boundaries.

Carry unknowns forward faithfully. Do not resolve NEEDS CLARIFICATION or pending decisions through prose. Do not add boilerplate, self-evaluation or narration about how the explanation was generated.

Aim for a short, coherent read, often 200–500 Chinese characters for a small source and more for a dense one. Length is not a quota. Use a source/snapshot opening, one-sentence orientation and short substantive sections. Tables help genuine comparisons, not every paragraph. Use content-specific headings.
