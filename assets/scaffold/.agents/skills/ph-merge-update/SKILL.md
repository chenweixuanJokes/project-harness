---
name: ph-merge-update
description: "Upgrade an installed PH project through the fixed release migration chain while preserving project content. Invoke only when the user explicitly names ph-merge-update and requests it; ordinary descriptions and mentions do not trigger it. The ph-init session may read this file as internal steps of an explicitly requested upgrade. Continue an explicitly started operation without repeated naming. Do not automatically invoke other skills."
---

# Merge a PH release into an installed project

Use the prepared release's scripts and migration documents, even when the old project has no copy of this skill. This procedure is also read directly by ph-init for an already requested upgrade. Do not use init --apply, an adoption plan, target git pull or template replacement as an upgrade shortcut.

## Source and preflight

The official source is `https://github.com/chenweixuanJokes/project-harness.git`; historical 1.x source identities using `https://github.com/chenweixuanJokes/ph-init.git` remain compatible. Prepare one stable tag/commit outside the target and read its root SKILL.md. Never use main or an unprepared local tree as the latest release.

```text
python3 <ph-init-root>/scripts/ph_release.py prepare --version latest --repo <target>
python3 <release-root>/scripts/ph_merge_update.py inspect --repo <target>
```

Reuse an already prepared root for the same operation. Failed source verification or a missing migration chain blocks writes. Old entry validators can reject the new self-developed package because they require schema_version or Spec Kit metadata. Use the fixed published target tag's own entry in a new external directory as described in ph-init; do not edit the old validator or pretend a not-yet-published tag can be downloaded.

Read applicable target constraints and the project's question rules. Inspect manifest, actual skill directories, canonical/adapter entries, documents, runtime, uncommitted changes and ongoing worktrees. Historical 1.1.0 layouts differ; do not infer their identities from the version string alone. New projects belong to installation, same-version check/sync stays offline, and downgrade is refused.

## Preserve before replacing

Inventory every affected original and record ownership, type, path and digest. Preserve originals in the migration's declared archive/backup with a restorable inventory before replacement, relocation or retirement. Do not follow archived links outside the repository. Unknown third-party content remains untouched.

Preservation and migration are separate acceptance criteria: still-valid project rules, facts, parameters, attachments, requirements, question history, test evidence, memory and skill customization need an active destination and evidence. A historical-only disposition requires a reason. An archived copy alone does not prove useful customization survived.

Read prose for semantic merging. Retain current project facts and valid rules, merge only changes required by the migration, repair active references and indexes, and preserve historical wording/code blocks. Do not perform broad fresh research or regenerate all project documents as an incidental upgrade.

## State and execution

Read migrations/index.json and every hop from the actual source state to the target. Later target-state operations can supersede intermediate installation steps, but no migration obligation may be dropped. Already published migration documents remain unchanged.

Use `.agents/updates/<target-version>/state.json` and report.md. Preserve from_version/to_version/source repository/tag/commit and a record for every chain item. Overall status is in_progress or complete; item status is pending/applied/not_applicable/blocked with honest string evidence. Resume by checking real disk state, not just the version field or past report. Do not rebaseline changed originals or duplicate migrated prose on retry.

Explain the actual write scope and resolve necessary conflicts using the host question tool. Once authorized, execute unambiguous operations without repeated permission prompts. A project rule conflicting with the proposed target remains blocked until decided; do not choose a lower gate for convenience.

## Self-developed SDD transition

Read the target release's 1.2.2-to-1.2.3 migration document and follow its exact command order and safety checks. The six transition items are:

| Item | Required result |
| --- | --- |
| sdd-skill-replacement | New development suite installed; old managed entries and obsolete adapters safely retired; same-name replacements and customization handled |
| sdd-runtime-takeover | PH-owned runtime and governance functions replace upstream dependencies without losing principles or navigation |
| bilingual-skills | Changed/new skills carry English SKILL.md and Chinese SKILL.zh.md; translations are not extra skill entries |
| docs-tests-consolidation | Current document, testing and case-library rules merged without erasing project facts |
| worktree-session-continuity | New runtime installed while existing session/assignment/history data remains intact |
| artifact-compat | Old spec/plan/task/evidence records remain readable and traceable, with no invented new pass states |

The target development suite is ph-require, ph-clarify, ph-design, ph-design-review, ph-tasks, ph-verify-plan, ph-small-change, ph-implement, ph-verify and ph-archive. ph-clarify/ph-tasks/ph-implement replace older same-name implementations; old ph-analyze/ph-checklist/ph-converge/ph-constitution/ph-plan/ph-specify/ph-taskstoissues are not retained as active alternative workflows.

Use `ph_merge_update.py migrate-skills --repo <target>` in dry-run, then --apply only for an authorized non-conflicting plan. Prove ownership using recorded content baselines and historical evidence, not names or provenance markers alone. Preserve whole directories including resources. Modified bodies, unknown auxiliary files or third-party same-name content require a documented preservation/migration decision; do not relabel them as stock bytes to bypass a block. Review adapter copies before retiring their canonical source so ownership proof is not lost. Verify no obsolete managed orphan remains in a declared vendor entry.

If migrate-skills reports unrecognized auxiliary files, first review their meaning. Its `--extras-decisions <JSON>` accepts a per-skill `decision: archive` plus a `note`; use it only when those files are truly historical or their still-valid content has already been preserved at a verified active destination. Include the disposition evidence in the note/report. The switch is not blanket permission to discard customization. Modified main skill bodies still require conflict resolution rather than a forged baseline.

Preserve old spec.md, plan.md, task IDs, answers, attachments, acceptance evidence, companions and intent ledgers. Runtime adoption maps existing files rather than rewriting them and starts unverified; an old completed checkbox never becomes current user acceptance. Do not change or delete `.worktrees/.ph/` sessions during package migration. Existing worktrees are execution state, not obsolete skill assets.

Current content lives under project-harness: constraints, documents, specs, memory, archive and runtime. Materialize constitution and refresh its per-file navigation with the new governance script, preserving user principles. The removal of an upstream generator must not remove governance coverage. No automatic ph-constitution or other retired command is required to finish the upgrade.

## Verify and finalize

After semantic merging, verify restored originals, active content destinations, required skill set, English/Chinese files, adapter state, runtime commands and document/case references. Run the release's ph_governance.py content/navigation checks according to its help and the release root's `references/项目化验收.md` when executing from the release root. In an installed copy, read the same guidance from the project-local ph-init package instead of resolving a nonexistent repository-root reference.

```text
python3 <release-root>/scripts/ph_merge_update.py verify --repo <target>
python3 <release-root>/scripts/ph_merge_update.py finalize --repo <target>
python3 <release-root>/scripts/ph_merge_update.py finalize --repo <target> --apply
```

Final apply requires the appropriate approval and successful candidate checks. Keep the original adapter mode. An already written target version never substitutes for complete migration evidence; pending/blocked items remain in_progress. Failure cannot be reported as completed. After finalize, use the installed kernel's ordinary check offline. Check/sync does not fill documentation or opportunistically upgrade.

Report actual changes, preserved originals, migrated customization, removed old entries, new skills, verified commands and remaining limitations. Distinguish structural script success, semantic content acceptance and public release verification. Do not commit, push, deploy, publish, write memories or clean worktrees to finish this operation. Do not use rm; use the migration's restorable backups and approved trash policy for retirement.
