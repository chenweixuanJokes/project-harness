---
name: ph-human
description: "Inspect and refresh explanatory companions for existing PH feature artifacts. Invoke only when the user explicitly names ph-human and requests it; ordinary descriptions, mentions and suggested next steps do not trigger it. Continue an explicitly started stage without repeated naming. Do not automatically invoke other skills. Companions are snapshots, not authoritative requirements or acceptance evidence."
---

# Maintain human-readable companions

Use [the human-writing rules](references/human-writing.md) as the writing authority. Development skills may read those rules directly when publishing their own changed artifacts; that does not invoke this skill.

## Procedure

1. Determine the requested feature or all-feature scope. Prefer an explicit path. When the user requests all or gives no narrower scope, use `--all`; do not silently choose a global active-feature pointer in a parallel workspace.
2. Run the read-only inventory:

   ```text
   python3 .agents/scripts/ph_human.py status --repo <root> (--feature <feature-directory> | --all)
   ```

   Interpret fresh, stale, orphan, user_modified, snapshot, unreadable and missing according to the returned source hashes and metadata. A fresh hash proves source alignment, not the accuracy of the prose.
3. Refresh items within the user's requested scope. An inspection-only request remains read-only. Report user_modified/unreadable targets without overwriting; ask only when a genuine unresolved choice changes the write scope. Legacy analysis/issues snapshots without a current source are historical: do not invent a new report or resurrect a retired skill.
4. Read each source in full, compose the companion in a temporary file outside the repository, then publish:

   ```text
   python3 .agents/scripts/ph_human.py publish --repo <root> --source <source-relative-path> --candidate <temporary-body> --skill ph-human
   ```

   The script owns mapping, source/body hashes, footer and safe writes. Do not put machine metadata in the candidate, bypass a conflict, or use a companion as another companion's source.
5. Run status again and report refreshed items, still-stale sources, protected user edits and missing-source items separately.

## Boundaries

Write only companion artifacts. Do not edit requirements, design, tasks, verification, constitution or acceptance state; do not invoke other skills or perform Git/external operations. A companion explains what a source says and cannot replace user acceptance, test evidence or a current project rule. Missing or stale companions do not invalidate the authoritative source itself.
