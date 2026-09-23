---
name: ph-init
description: "Install, inspect, synchronize or upgrade Project Harness from its fixed official release source. Invoke only when the user explicitly names ph-init and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started operation without repeated naming. Do not automatically invoke other skills: reading ph-merge-update as internal steps of the requested upgrade is the explicit exception. Do not confuse this with a host /init command, git init, git pull, worktree operations or feature implementation."
---

# Install and maintain Project Harness

PH installs project-owned instructions and skills under `.agents/`. Root AGENTS.md is the general entry; declared Claude adapters expose CLAUDE.md and `.claude/skills/`. Other clients that read the canonical location need no duplicate copies. Use the project's locked portable/symlink mode; this operation does not migrate that choice.

The development suite is PH-owned: ph-require, ph-clarify, ph-design, ph-design-review, ph-tasks, ph-verify-plan, ph-small-change, ph-implement, ph-verify and ph-archive. It does not depend on upstream Spec Kit at installation or execution. The release also includes installation/update, independent worktree entry/exit, memory and human-companion tools. The required skill list comes from release.json, not a second hand-maintained count.

## Source and preparation

The sole official source is `https://github.com/chenweixuanJokes/project-harness.git`. The historical `https://github.com/chenweixuanJokes/ph-init.git` redirects to it and remains a compatible identity in 1.x receipts; do not rewrite valid historical source fields. Stable releases use vMAJOR.MINOR.PATCH tags; latest means the numerically greatest stable tag, pinned to its commit. The current package version is 1.2.3. Never present a local development tree or main as the latest release.

For install or upgrade, prepare outside the target repository:

```text
python3 <ph-init-root>/scripts/ph_release.py prepare --version latest --repo <target>
```

Read returned root/version/tag/commit/source and then read that root's SKILL.md. All subsequent actions use the same prepared version/commit and its scripts. Network failure, missing tag or inconsistent metadata stops preparation; no fallback to stale local assets. An offline package can install its identified version, not claim latest.

Old entry validators may reject new package contracts: through 1.1.7 they require schema_version, and Spec Kit-era validators require the now-retired upstream contract. Do not patch the old validator, retry unchanged or claim the target upgraded. For this transition, obtain the officially published v1.2.3 tag in a new safe directory outside the project, run its own ph_release.py prepare for that fixed version and read the returned root. Before that tag exists, report publication as unavailable; local candidate testing is not public release installation. Earlier historical transitions remain documented in their unchanged migration files.

Preparation only obtains and verifies the release; it does not star a repository or create an account fork. The separate support command may perform those account changes only when the user explicitly authorizes them. Do not run it to finish installation or reproduce a historical default. When testing a historical downloader, isolate its support hook so no real account is changed. Lack of login never blocks installation. Do not request login or treat an account fork as the official source.

Run the prepared root's user-entry refresh once within the requested maintenance operation:

```text
python3 <release-root>/scripts/ph_release.py user-entry
```

It updates an existing recognized older user entry with backup/rollback protection. Missing, non-directory, unknown-version or not-older entries may be skipped; report the actual result, do not create a new global entry or force a downgrade. A refreshed user entry does not mean the project has upgraded.

## Route by target state

- No installed manifest: inspect existing content, then install/adopt.
- Installed older version: read `assets/scaffold/.agents/skills/ph-merge-update/SKILL.md` in the prepared root and perform its steps in this same operation. This is internal execution of the requested upgrade, not a new automatically triggered skill. Never run init --apply or adopt over an installed old project.
- Same version: check, synchronize adapters or continue document completion as requested; do not reinstall or opportunistically upgrade.
- Newer project than package: stop rather than downgrade.
- Check/sync alone: use the project's installed kernel offline; do not prepare, fetch, write project facts or upgrade.

```text
python3 <release-root>/scripts/ph_init.py init --repo <target> [--mode auto|portable|symlink] [--adopt-plan <plan.json>] [--apply]
python3 <installed-ph-init>/scripts/ph_init.py check --repo <target> [--mode portable|symlink]
python3 <installed-ph-init>/scripts/ph_init.py sync --repo <target> [--mode portable|symlink] [--apply]
```

Default commands are dry-run. Sync repairs only declared adapter drift, not canonical content or missing/upgraded skills. New auto installation probes symlink capability at apply and falls back to portable where appropriate; an explicit symlink request fails rather than silently changes mode. Portable is supported, not degraded. Reject hardlinks, junctions, unsafe nested links, out-of-repository paths and unmanaged mirror extras.

## Install or adopt existing content

Read [adoption guidance](references/接入规范.md), [completion guidance](references/补全规范.md) and [content acceptance](references/项目化验收.md) from the same release. Do not modify the prepared distribution.

1. Inventory current Git state, entry files, modules, source, configuration, lockfiles, tests, CI and existing project rules/documents. Preserve user changes. Reuse existing authoritative prose or references rather than duplicating facts into a second document set.
2. Run dry-run and classify planned, skipped, conflicting and blocked items. Read the project's question rules before asking for a necessary decision. An existing root AGENTS.md without a canonical source, tracked worktrees or unsafe paths remains blocked; do not move the obstacle away to force installation.
3. For an existing uninitialized project, prepare an adoption candidate and source hashes outside the repository. Do not install template text first and then overwrite old prose. Obtain any missing authorization for the actual write scope through the proper host channel.
4. The adoption JSON has version=1, absolute repo, release_version, sources mapping repository-relative paths to SHA256 or null, and files containing candidate UTF-8 prose. Sources include `.agents/AGENTS.md`, AGENTS.md, CLAUDE.md and all candidate targets. Allowed destinations are canonical instructions, docs and PH constraints/documents. Do not include secrets. Hashes protect identity and drift, not semantic completeness; the agent reviews that separately.
5. Execute the same candidate and release root in dry-run then apply. Install the self-contained PH skill/runtime set and project-local ph-init payload, then declared adapters. Do not add other vendor mirrors. Installation errors remain failures; run the installed check after successful apply.
6. Complete project documentation from actual code and the project's real technology versions. Delegate independent factual research where supported, but keep canonical ownership and final semantic review in the main session. External research uses generic technical queries, not private project content. Without agents, report the limitation and work serially.
7. Preserve old originals before authorized relocation, migrate still-valid rules/facts/requirements/memory into the appropriate PH zones, repair links and indexes, then retire obsolete active entries. Archiving alone is not migrating useful content. Unknown project facts, unexecuted commands and unadopted recommendations remain explicitly labeled.
8. Maintain `.agents/init-report.md` plus the required content evidence report with one entry per governed document. Materialize constitution and refresh its per-file constraint navigation using the shipped ph_governance.py commands; preserve existing principles. Run verify-content and ordinary installed check. Script success does not replace semantic review.

## Project content and completion

Current rules live in constraints, project facts in documents, working requirements in specs, reference memory in memory, historical originals in archive and PH runtime in runtime. Long rules do not belong in AGENTS.md. Read and preserve existing valid project decisions; do not fabricate ADRs, interviews, memories or test results to fill templates.

Companions are optional explanations of real artifacts. The ph_human.py publisher owns hashes/mappings; its human-writing reference defines prose. Companions never establish user acceptance. Worktree enter/exit remain independent explicit operations; feature archiving does not merge or delete worktrees.

Report installation checks and document completion separately, including verified/reused/not-applicable/pending/conflicting items. Empty templates, missing content migration or unresolved conflicts cannot be reported as complete. On interruption resume from disk and reports, not by reinstalling. Never commit, push, publish, deploy or send notifications solely to finish installation.
