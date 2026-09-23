---
name: ph-design
description: "Design product behavior, interaction and technical implementation for a clarified requirement. Invoke only when the user explicitly names ph-design and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills."
---

# Design the solution

Read [the development contract](../ph-require/references/process.md). Require a sufficiently clarified requirement; investigate missing facts but do not silently decide unresolved business questions.

## Procedure

1. Read the requirement, applicable constraints, current architecture, affected source files, interfaces and tests. Trace relevant callers and side effects using semantic tools where available. Check versions and authoritative external references only where needed; never send private project content to external search.
2. Describe the product experience: entry point, actors, main journey, observable output, loading/empty/error/permission states and accessibility where applicable. For a CLI, service or internal change, describe its actual consumer contract rather than inventing screens.
3. Describe implementation boundaries: reused components, modules to change, data flow, interface/data contracts, error handling, compatibility, migration, security and operational effects. Give file and symbol references where verified. Resolve code facts now instead of leaving “reuse X if it exists” to the implementer.
4. Compare alternatives only for consequential choices. State the selected option, evidence, trade-offs and unresolved dependencies. Do not demand alternatives for obvious local choices or claim unknown external behavior as confirmed.
5. Write design.md using `runtime/templates/sdd/design-template.md` as guidance. Map requirements and acceptance outcomes to concrete design sections. Identify test seams and resource needs, not the full task-level test script. Record expected documentation and reusable case-library changes.
6. Identify parallelizable boundaries and shared interfaces. Shared schemas, generated files, dependency lockfiles, database migrations and global indexes need an owner or serialization. A worktree is optional; this stage creates none.
7. Reconcile the design with the original requirement. If the solution cannot meet it, expose the conflict instead of lowering acceptance. Keep the design draft until ph-design-review actually reviews the current sources. Updating a previously reviewed design requires reassessment of dependent tasks and checks.
8. Refresh supported companions and present the user-visible behavior, key implementation decisions, risks and unresolved items. Recommend ph-design-review; do not implement.

## Completion

The design explains both what the consumer experiences and how the project can build it. Each requirement has a design location or an explicit unresolved gap. No code, branch, external configuration or acceptance threshold was changed.
