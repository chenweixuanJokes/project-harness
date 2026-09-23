#!/usr/bin/env python3
"""Read-only inspect, structural verify, and finalize for PH merge-update."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

# Script-entry guard, same regression class as ph_init.py: running this CLI
# in an installed repository must not leave __pycache__ next to the kernel
# scripts. Importing this module as a library keeps no side effect.
if __name__ == "__main__":
    sys.dont_write_bytecode = True

import ph_init
import ph_layout
from ph_init import (
    PHError, SPECIFY_DIR, cmd_check, cmd_sync, contained, ensure_canonical_root,
    expected_rel_link, find_repo, infer_mode, is_disallowed_reparse,
    is_git_symlink_mode, iter_files, load_repo_manifest, posix_rel,
    read_json, reject_nested_links, sha256_bytes, sha256_file,
)

FIXED_SOURCE = "https://github.com/chenweixuanJokes/ph-init.git"
RECEIPT_NAME = ".ph-source.json"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
HEX40, SEMVER = re.compile(r"^[0-9a-f]{40}$"), re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
CODEX_SKILLS_REL = ".codex/skills"
CODEX_ARCHIVE_SUFFIX = "-pre-update"
CODEX_ARCHIVE_CHILD = "codex-skills"
ITEM_DONE = frozenset({"applied", "not_applicable"})
ITEM_STATUSES = ITEM_DONE | {"pending", "blocked"}
BASE_SKILLS = ("ph-init", "ph-worktree-enter", "ph-worktree-exit", "ph-memory-capture", "ph-memory-archive", "ph-memory-ask")
OLD_ALIASES = ("ph-intent-capture", "ph-intent-plan", "ph-intent-abandon")
NEW_INTENT = ("ph-intent-new", "ph-intent-impl", "ph-intent-drop")
# Skills introduced by a named migration item at a known release. No earlier
# release ships them, so a live same-named directory on an older project is
# project content on a PH-reserved name: the upgrade must block that item
# instead of overwriting it. (ph-docs-sync arrived with 1.1.10/docs-sync-skill;
# ph-intent-verify with 1.1.13/intent-verify-skill. ph-sure and its migration
# item were dropped from the unreleased 1.1.14 batch when the legacy skill set
# was retired for the spec-kit integration.)
# The three memory skills arrive with the merged 1.1.15→1.2.1 hop (the 1.1.16
# candidate was never published, so the arrival version is 1.2.1). Two of them
# (ph-memory-ask/ph-memory-archive) REINTRODUCE names that PH shipped as
# scaffold skills before 1.1.14: a live same-named directory below 1.1.14 is
# that official historical copy (retire-legacy-skills archives it), and only a
# live copy at 1.1.14 or later - when no PH release shipped the name - is
# unmanaged project content and blocks the item. ph-memory-learning is a new
# name (nothing shipped it before); ph-memory-capture's recording duty was
# folded into learning, so capture itself is NOT re-shipped and stays retired
# (see RETIRED_SKILLS and the capture-residual guard in
# release_skill_name_conflicts).
RELEASE_ONLY_SKILLS = {
    "ph-docs-sync": ("docs-sync-skill", "1.1.10"),
    "ph-intent-verify": ("intent-verify-skill", "1.1.13"),
    "ph-memory-ask": ("memory-skills", "1.2.1"),
    "ph-memory-learning": ("memory-skills", "1.2.1"),
    "ph-memory-archive": ("memory-skills", "1.2.1"),
    "ph-human": ("human-readable-companion", "1.2.2"),
    # 1.2.3 self-developed spec-driven skills. No earlier release shipped
    # these names, so a live same-named directory on an older project is
    # project content on a PH-reserved name and blocks the item instead of
    # being overwritten.
    "ph-require": ("sdd-skill-replacement", "1.2.3"),
    "ph-design": ("sdd-skill-replacement", "1.2.3"),
    "ph-design-review": ("sdd-skill-replacement", "1.2.3"),
    "ph-verify-plan": ("sdd-skill-replacement", "1.2.3"),
    "ph-small-change": ("sdd-skill-replacement", "1.2.3"),
    "ph-verify": ("sdd-skill-replacement", "1.2.3"),
    "ph-archive": ("sdd-skill-replacement", "1.2.3"),
}
# First release at or above which a same-named memory-skill directory is
# unmanaged project content rather than the official pre-1.1.14 copy.
MEMORY_REINTRODUCED_FLOOR = "1.1.14"
MEMORY_SKILL_ITEM = "memory-skills"
# Memory names retired with 1.1.14 whose duty 1.2.1 folded elsewhere instead of
# re-shipping them. Below MEMORY_REINTRODUCED_FLOOR a live copy is the official
# historical scaffold skill and retire-legacy-skills archives it; at that floor
# or later no release ever shipped the name, so a live directory is user
# content on a PH-reserved retired name: block the memory-skills item and ask,
# never delete silently.
MEMORY_RETIRED_NOT_RESHIPPED = ("ph-memory-capture",)
# The ten spec-kit skills were generated from the pinned upstream release
# between 1.1.14 and 1.2.2. 1.2.3 replaces them with self-developed skills:
# seven names retire outright, and ph-clarify / ph-tasks / ph-implement are
# replaced in place with new contracts. The historical names stay pinned here
# so old layouts keep being recognized (never re-spelled from ph_init - the
# current release has no speckit contract anymore) and so the skill-replacement
# migration can classify and archive the managed copies.
SPECKIT_INTRODUCED = "1.1.14"
SPECKIT_RELEASE_ITEM = "speckit-core-integration"
SPECKIT_MANAGED_SKILLS = (
    "ph-analyze",
    "ph-checklist",
    "ph-clarify",
    "ph-constitution",
    "ph-converge",
    "ph-implement",
    "ph-plan",
    "ph-specify",
    "ph-tasks",
    "ph-taskstoissues",
)
# The 1.2.3 skill-replacement migration item: identity recognition for the
# same-name replacements, whole-directory archival for the rest.
SDD_SKILL_ITEM = "sdd-skill-replacement"
SDD_INTRODUCED = "1.2.3"
# The 1.2.3 migration hop, in its index.json order. Single source for the
# upgrade chains the tests and the matrix pin.
SDD_CHAIN_ITEMS = (
    "sdd-skill-replacement",
    "sdd-runtime-takeover",
    "bilingual-skills",
    "docs-tests-consolidation",
    "worktree-session-continuity",
    "artifact-compat",
)
SDD_RETIRED_SKILLS = (
    "ph-analyze",
    "ph-checklist",
    "ph-converge",
    "ph-constitution",
    "ph-plan",
    "ph-specify",
    "ph-taskstoissues",
)
SDD_REPLACED_SKILLS = ("ph-clarify", "ph-implement", "ph-tasks")
# The seven PH skills a 1.1.14..1.2.2 install already carries under their own
# migration items, with 1.2.2-generation text. The skill-replacement item
# installs one of them only when it is missing from the managed install; a
# live copy with old-generation text is neither this item's business nor
# unknown content, so it is never touched and never blocked here. The names
# no earlier release shipped are what this item actually manages.
RETAINED_122_SKILLS = (
    "ph-merge-update",
    "ph-worktree-enter",
    "ph-worktree-exit",
    "ph-memory-ask",
    "ph-memory-learning",
    "ph-memory-archive",
    "ph-human",
)
# The per-file content baselines a 1.1.14..1.2.2 project carries under
# `.agents/ph.json` `speckit.files` (sha256 of every managed file as
# installed). They are the identity proof for the same-name replacements and
# the retirement of the managed copies; without them a live same-name
# directory is unattributable content and blocks the item.
SDD_SKILL_BASELINE_PREFIX = ".agents/skills/"
# Skills retired with 1.1.14: they were scaffold skills in earlier releases, so
# an upgrade must archive them out of the managed install (with a backup) while
# preserving user-customized content that never belonged to PH. ph-memory-ask
# and ph-memory-archive were reintroduced with a new contract by the 1.2.1
# memory skills; they stay listed here so the retirement item still archives
# the old pre-1.1.14 copies, while assert_release_skill_installs drops them
# from the retired set (see there) because the target ships them again.
# ph-memory-capture is NOT reintroduced (its recording duty moved into
# ph-memory-learning), so it stays retired for every upgrade path.
RETIRED_SKILLS = (
    "ph-memory-capture",
    "ph-memory-archive",
    "ph-memory-ask",
    "ph-intent-new",
    "ph-intent-impl",
    "ph-intent-verify",
    "ph-intent-drop",
    "ph-docs-sync",
)
INTENT_ROOTS = ("docs/意图/待办", "docs/意图/实施")
INTENT_KINDS = ("新特性", "问题记录")
# 1.2.1: TARGET_FILES retired with the intent tree - target_paths() now pins
# the project-harness home skeleton instead (see its docstring).
TARGET_FILES = ("docs/意图/README.md", "docs/意图/_模板.md", "docs/意图/访谈纪要/_模板.md", "docs/约束规范/工程规范/意图与访谈.md", ".agents/AGENTS.md")
CORE_PREFIXES = (
    "release.json",
    "SKILL.md",
    "SKILL.zh.md",
    "scripts/ph_init.py",
    "scripts/ph_release.py",
    "scripts/ph_merge_update.py",
    "scripts/ph_governance.py",
    "migrations/",
    "assets/scaffold/",
)
PH_INIT_RUNTIME = (
    "SKILL.md",
    "SKILL.zh.md",
    "release.json",
    "scripts/ph_init.py",
    "scripts/ph_release.py",
    "scripts/ph_merge_update.py",
    "scripts/ph_governance.py",
    "scripts/ph_layout.py",
    "migrations/index.json",
    "assets/scaffold/.agents/ph.json",
    "assets/scaffold/.agents/ph.schema.json",
)


def semver_tuple(version: str) -> tuple[int, int, int]:
    if not isinstance(version, str) or not SEMVER.match(version):
        raise PHError(f"illegal version: {version!r}")
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def is_safe_rel(rel: str) -> bool:
    if not rel or rel.startswith("/") or rel.startswith("~/") or "\\" in rel or "\0" in rel:
        return False
    return all(part not in {"", ".", ".."} for part in rel.split("/"))


def is_protected_rel(rel: str) -> bool:
    for prefix in CORE_PREFIXES:
        if prefix.endswith("/"):
            if rel == prefix[:-1] or rel.startswith(prefix):
                return True
        elif rel == prefix:
            return True
    return False


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def release_contract() -> tuple[str, tuple[str, ...]]:
    data = read_json(SOURCE_ROOT / "release.json")
    version, skills = ph_init.RELEASE_VERSION, tuple(ph_init.REQUIRED_SKILLS)
    if data.get("version") != version:
        raise PHError("release.json does not match ph_init contract")
    if list(data.get("required_skills") or []) != list(skills):
        raise PHError("release.json required_skills do not match ph_init contract")
    if not SEMVER.match(version):
        raise PHError("illegal release contract version")
    return version, skills


def is_hardlink(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and not path.is_symlink() and path.stat().st_nlink > 1
    except OSError:
        return False


def ancestor_issue(repo: Path, path: Path) -> str | None:
    repo_a = repo.absolute()
    cur = path.absolute()
    while True:
        try:
            rel = posix_rel(cur.relative_to(repo_a))
        except ValueError:
            return f"{cur} escapes repository"
        if cur.is_symlink() or is_disallowed_reparse(cur):
            return f"{rel} is a symlink or junction"
        if is_hardlink(cur):
            return f"{rel} is a hardlink"
        if cur == repo_a:
            return None
        nxt = cur.parent
        if nxt == cur:
            return f"{cur} escapes repository"
        cur = nxt


def assert_real_file(repo: Path, path: Path, label: str) -> None:
    issue = ancestor_issue(repo, path)
    if issue or path.is_symlink() or is_disallowed_reparse(path) or is_hardlink(path) or not path.is_file() or not contained(repo, path):
        raise PHError(f"{label} must be a repository-local regular file" + (f": {issue}" if issue else ""))


def assert_real_dir(repo: Path, path: Path, label: str) -> None:
    issue = ancestor_issue(repo, path)
    if issue or path.is_symlink() or is_disallowed_reparse(path) or not path.is_dir() or not contained(repo, path):
        raise PHError(f"{label} must be a repository-local directory" + (f": {issue}" if issue else ""))
    reject_nested_links(path, label=label)


def updates_dir(repo: Path, to_version: str) -> Path:
    if not SEMVER.match(to_version):
        raise PHError(f"illegal to_version: {to_version!r}")
    ensure_canonical_root(repo)
    dest = repo / ".agents" / "updates" / to_version
    assert_real_dir(repo, repo / ".agents", "canonical .agents")
    for node, label in ((dest.parent, ".agents/updates"), (dest, f".agents/updates/{to_version}")):
        if node.exists() or node.is_symlink():
            assert_real_dir(repo, node, label)
        else:
            issue = ancestor_issue(repo, node.parent)
            if issue:
                raise PHError(f"{label} is unsafe: {issue}")
    try:
        dest.resolve().relative_to((repo / ".agents" / "updates").resolve())
    except (ValueError, OSError) as exc:
        raise PHError("state directory escapes .agents/updates") from exc
    return dest


def live_skills(repo: Path) -> set[str]:
    root = repo / ".agents" / "skills"
    if not root.exists() and not root.is_symlink():
        return set()
    assert_real_dir(repo, root, ".agents/skills")
    names: set[str] = set()
    for child in root.iterdir():
        if not child.name.startswith("ph-"):
            continue
        skill = child / "SKILL.md"
        assert_real_dir(repo, child, f"canonical skill {child.name}")
        assert_real_file(repo, skill, f"canonical skill {child.name}/SKILL.md")
        names.add(child.name)
    return names


def detect_profile(names: set[str]) -> tuple[str, list[str]]:
    base, old, new = set(BASE_SKILLS), set(OLD_ALIASES), set(NEW_INTENT)
    speckit = set(SPECKIT_MANAGED_SKILLS)
    # The 1.1.14..1.2.2 layouts carry the ten spec-kit skills next to the PH
    # skills (1.2.1 adds the three memory skills back); 1.2.3 replaces them
    # with the self-developed set, so this recognition stays historical.
    if speckit <= names:
        core = names - speckit
        # A half-applied upgrade may still carry retired leftovers; only a
        # mixed old/new intent layout is unsalvageable guessing.
        if old & core and new & core:
            both = ", ".join(sorted((old | new) & core))
            return "mixed-intent-names", [f"old and new intent skill names both live: {both}"]
        return "speckit-current", []
    # 1.2.3 target layout: the self-developed set replaced the spec-kit
    # generation, so the required skills alone identify the current profile
    # (a half-applied state keeps retired leftovers; only the full set
    # matches).
    if set(ph_init.REQUIRED_SKILLS) <= names:
        core = names - set(ph_init.REQUIRED_SKILLS)
        if old & core and new & core:
            both = ", ".join(sorted((old | new) & core))
            return "mixed-intent-names", [f"old and new intent skill names both live: {both}"]
        return "sdd-current", []
    if not base <= names:
        raise PHError("unknown PH skill layout; refuse to guess")
    # Release-only skills (ph-docs-sync from 1.1.10, ph-intent-verify from
    # 1.1.13) are tolerated here so an older project carrying a same-named
    # directory still resolves to its historical profile and gets the named
    # conflict below, instead of a generic unknown-layout error; from each
    # introducing release on the skill is the release's own.
    core = names - set(RELEASE_ONLY_SKILLS)
    if old & core and new & core:
        both = ", ".join(sorted((old | new) & core))
        return "mixed-intent-names", [f"old and new intent skill names both live: {both}"]
    if old <= core:
        return "1.1.0-legacy-names", []
    if new <= core:
        return "1.1.0-current-names", []
    if core <= (base | {"ph-merge-update"}):
        return "1.0.0", []
    raise PHError("unknown PH skill layout; refuse to guess")


def release_skill_name_conflicts(names: set[str], disk_version: str, existing: dict | None) -> list[str]:
    """Live release-only skills below their introducing release block the item.

    No PH release before the introducing version ships the skill, so an older
    project with a live same-named ``.agents/skills/<name>`` directory carries
    project content on a PH-reserved name: the semantic merge must keep it in
    place, mark that migration item blocked, and ask the user instead of
    overwriting. Reported only before the merge starts (no target state on
    disk yet); once the state exists its recorded item status governs, and
    from the introducing release on the skill is the release's own and never
    conflicts.
    """
    out: list[str] = []
    for skill in sorted(RELEASE_ONLY_SKILLS):
        item, introduced = RELEASE_ONLY_SKILLS[skill]
        if skill not in names or existing is not None:
            continue
        if semver_tuple(disk_version) >= semver_tuple(introduced):
            continue
        if item == MEMORY_SKILL_ITEM and semver_tuple(disk_version) < semver_tuple(
            MEMORY_REINTRODUCED_FLOOR
        ):
            # Below 1.1.14 PH shipped the old same-named memory skill as
            # scaffold content: this is the official historical copy, the
            # retire-legacy-skills item archives it, and the memory-skills
            # item then installs the new contract. Not a customization.
            continue
        out.append(
            f".agents/skills/{skill}: same-name directory exists below "
            f"{introduced} and no PH release ships it; treat it as project "
            f"content, keep it in place, block the {item} item, and ask "
            "the user before any replacement"
        )
    for skill in MEMORY_RETIRED_NOT_RESHIPPED:
        if skill not in names or existing is not None:
            continue
        if semver_tuple(disk_version) < semver_tuple(MEMORY_REINTRODUCED_FLOOR):
            continue  # official pre-1.1.14 copy; retire-legacy-skills archives it
        out.append(
            f".agents/skills/{skill}: retired name exists at {disk_version} and "
            "no PH release ships it anymore (its recording duty moved into "
            "ph-memory-learning); treat it as user content, keep it in place, "
            f"block the {MEMORY_SKILL_ITEM} item, and ask the user to remove "
            "or rename it before retrying"
        )
    for skill in sorted(SPECKIT_MANAGED_SKILLS):
        if skill not in names or existing is not None:
            continue
        if semver_tuple(disk_version) >= semver_tuple(SPECKIT_INTRODUCED):
            continue
        out.append(
            f".agents/skills/{skill}: same-name directory exists below "
            f"{SPECKIT_INTRODUCED} and no PH release ships it; treat it as project "
            f"content, keep it in place, block the {SPECKIT_RELEASE_ITEM} item, "
            "and ask the user before any replacement"
        )
    return out


def load_index() -> list[dict]:
    data = read_json(SOURCE_ROOT / "migrations" / "index.json")
    if data.get("format_version") != 1:
        raise PHError("illegal migrations/index.json format_version")
    hops = data.get("migrations")
    if not isinstance(hops, list) or not hops:
        raise PHError("illegal migrations/index.json")
    out, seen_from, seen_to = [], set(), set()
    for hop in hops:
        if not isinstance(hop, dict):
            raise PHError("illegal migrations/index.json hop")
        src, dest = hop.get("from_version"), hop.get("to_version")
        path, items = hop.get("path"), hop.get("items")
        ok = isinstance(src, str) and isinstance(dest, str) and SEMVER.match(src) and SEMVER.match(dest)
        ok = ok and isinstance(path, str) and isinstance(items, list) and items
        ok = ok and all(isinstance(i, str) and i for i in items or [])
        if not ok:
            raise PHError("illegal migration hop")
        if not is_safe_rel(path) or not path.startswith("migrations/"):
            raise PHError(f"illegal migration hop path: {path}")
        if src in seen_from or dest in seen_to:
            raise PHError("illegal migrations/index.json: versions must be unique")
        if semver_tuple(src) >= semver_tuple(dest):
            raise PHError("illegal migrations/index.json: versions must increase")
        seen_from.add(src)
        seen_to.add(dest)
        doc = SOURCE_ROOT / path
        if doc.is_symlink() or is_hardlink(doc) or not doc.is_file():
            raise PHError(f"missing migration document: {path}")
        out.append({"from": src, "to": dest, "path": path, "items": list(items)})
    return out


def chain_between(from_version: str, to_version: str) -> list[dict]:
    if from_version == to_version:
        return []
    if semver_tuple(from_version) > semver_tuple(to_version):
        raise PHError(f"refusing downgrade {from_version} -> {to_version}")
    by_from, chain, cur, seen = {h["from"]: h for h in load_index()}, [], from_version, set()
    while cur != to_version:
        if cur in seen or cur not in by_from:
            raise PHError(f"missing migration chain {from_version} -> {to_version}")
        seen.add(cur)
        hop = by_from[cur]
        chain.append(hop)
        cur = hop["to"]
    return chain


def chain_items(chain: list[dict]) -> list[str]:
    ids, seen = [], set()
    for hop in chain:
        for item in hop["items"]:
            if item not in seen:
                ids.append(item)
                seen.add(item)
    return ids


def read_disk_manifest(repo: Path) -> dict:
    ensure_canonical_root(repo)
    assert_real_file(repo, repo / ".agents" / "ph.json", "canonical .agents/ph.json")
    assert_real_file(repo, repo / ".agents" / "AGENTS.md", "canonical .agents/AGENTS.md")
    return read_json(repo / ".agents" / "ph.json")


def manifest_version(data: dict) -> str:
    value = data.get("template_version")
    if not isinstance(value, str) or not SEMVER.match(value):
        raise PHError("illegal manifest template_version")
    return value


def repo_mode(repo: Path, data: dict) -> str:
    declared = data.get("adapter_mode") if data.get("adapter_mode") in {"portable", "symlink"} else None
    inferred = infer_mode(repo)
    if declared and inferred and declared != inferred:
        raise PHError(f"manifest declares {declared} but adapters look like {inferred}")
    mode = declared or inferred
    if mode not in {"portable", "symlink"}:
        raise PHError("cannot resolve adapter mode")
    return mode


def read_receipt() -> dict | None:
    path = SOURCE_ROOT / RECEIPT_NAME
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or is_disallowed_reparse(path) or is_hardlink(path) or not path.is_file():
        raise PHError("source receipt must be a regular file")
    data = read_json(path)
    need = {k: data.get(k) for k in ("version", "tag", "commit", "source")}
    if any(not isinstance(v, str) or not v for v in need.values()):
        raise PHError(f"illegal {RECEIPT_NAME}")
    if need["source"] != FIXED_SOURCE or not SEMVER.match(need["version"]) or need["tag"] != f"v{need['version']}" or not HEX40.match(need["commit"]):
        raise PHError(f"illegal {RECEIPT_NAME} identity")
    return need


def run_git(*args: str, cwd: Path | None = None, git_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["git"]
    if git_dir is not None:
        cmd += ["--git-dir", str(git_dir)]
    cmd += list(args)
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def prepared_bare() -> Path | None:
    bare = SOURCE_ROOT.parent / "git"
    if (bare / "HEAD").is_file() and (bare / "objects").is_dir() and not bare.is_symlink():
        return bare
    return None


def verify_tree_blobs(payload: str, root: Path) -> None:
    entries: dict[str, str] = {}
    for line in payload.split("\0"):
        if not line:
            continue
        meta, sep, path = line.partition("\t")
        if not sep:
            raise PHError("illegal source ls-tree record")
        parts = meta.split()
        if len(parts) != 3:
            raise PHError("illegal source ls-tree metadata")
        _mode, obj_type, oid = parts
        if not is_protected_rel(path):
            continue
        if obj_type != "blob" or not HEX40.match(oid):
            raise PHError(f"source tree {path} is not a blob")
        entries[path] = oid
    if not entries:
        raise PHError("source commit is missing protected materials")
    for rel, oid in entries.items():
        dest = root / rel
        if dest.is_symlink() or is_hardlink(dest) or not dest.is_file():
            raise PHError(f"source material is not a regular file: {rel}")
        if git_blob_id(dest.read_bytes()) != oid:
            raise PHError(f"source material does not match commit: {rel}")


def verify_source_materials(receipt: dict) -> None:
    commit = receipt["commit"]
    bare = prepared_bare()
    if bare is not None:
        parsed = run_git("rev-parse", "--verify", f"{commit}^{{commit}}", git_dir=bare)
        typ = run_git("cat-file", "-t", commit, git_dir=bare)
        tree = run_git("ls-tree", "-r", "-z", "--full-tree", commit, git_dir=bare)
        if parsed.returncode != 0 or parsed.stdout.strip() != commit:
            raise PHError("prepared git bare does not contain receipt commit")
        if typ.returncode != 0 or typ.stdout.strip() != "commit":
            raise PHError("receipt commit is not a commit object")
        if tree.returncode != 0:
            raise PHError("cannot list prepared commit tree")
        verify_tree_blobs(tree.stdout, SOURCE_ROOT)
        return
    if not (SOURCE_ROOT / ".git").exists():
        raise PHError("source receipt is not bound to prepared git objects or a tagged development root")
    tag = receipt["tag"]
    head = run_git("rev-parse", "HEAD", cwd=SOURCE_ROOT)
    peeled = run_git("rev-parse", f"{tag}^{{commit}}", cwd=SOURCE_ROOT)
    typ = run_git("cat-file", "-t", commit, cwd=SOURCE_ROOT)
    tree = run_git("ls-tree", "-r", "-z", "--full-tree", commit, cwd=SOURCE_ROOT)
    if head.returncode != 0 or peeled.returncode != 0:
        raise PHError("development root has no matching official tag")
    if not (head.stdout.strip() == commit == peeled.stdout.strip()):
        raise PHError("development HEAD/tag does not match source receipt")
    if typ.returncode != 0 or typ.stdout.strip() != "commit":
        raise PHError("receipt commit is not a commit object")
    if tree.returncode != 0:
        raise PHError("cannot list development commit tree")
    verify_tree_blobs(tree.stdout, SOURCE_ROOT)


def source_status(to_version: str) -> dict:
    receipt = read_receipt()
    if receipt is None:
        return {
            "verified": False,
            "can_finalize": False,
            "reason": f"missing {RECEIPT_NAME}; development tree can inspect but cannot finalize",
            "receipt": None,
        }
    if receipt["version"] != to_version:
        return {
            "verified": False,
            "can_finalize": False,
            "reason": f"receipt version {receipt['version']} != {to_version}",
            "receipt": receipt,
        }
    try:
        verify_source_materials(receipt)
    except PHError as exc:
        return {"verified": False, "can_finalize": False, "reason": str(exc), "receipt": receipt}
    return {"verified": True, "can_finalize": True, "reason": "ok", "receipt": receipt}


def suggested_state(from_version: str, to_version: str, src: dict) -> dict | None:
    if from_version == to_version:
        return None
    receipt = src.get("receipt")
    return {
        "from_version": from_version,
        "to_version": to_version,
        "source": {"repository": FIXED_SOURCE, "tag": receipt["tag"] if receipt else "", "commit": receipt["commit"] if receipt else ""},
        "status": "in_progress",
        "items": [{"id": i, "status": "pending", "evidence": ""} for i in chain_items(chain_between(from_version, to_version))],
    }


def load_state(repo: Path, to_version: str) -> dict:
    path = updates_dir(repo, to_version) / "state.json"
    assert_real_file(repo, path, "update state.json")
    data = read_json(path)
    if not isinstance(data, dict):
        raise PHError("illegal state.json")
    return data


def validate_state(data: dict, from_version: str, to_version: str, required: list[str], src: dict) -> None:
    if data.get("from_version") != from_version or data.get("to_version") != to_version:
        raise PHError("state versions do not match inspect chain")
    if data.get("status") not in {"in_progress", "complete"}:
        raise PHError("state.status must be in_progress or complete")
    source = data.get("source")
    if not isinstance(source, dict) or source.get("repository") != FIXED_SOURCE:
        raise PHError("state.source.repository is not the fixed GitHub source")
    receipt = src.get("receipt")
    if receipt and (source.get("tag") != receipt["tag"] or source.get("commit") != receipt["commit"]):
        raise PHError(
            "state.source does not match source receipt: expected "
            f"tag={receipt['tag']} commit={receipt['commit']}, got "
            f"tag={source.get('tag')!r} commit={source.get('commit')!r}"
        )
    items = data.get("items")
    if not isinstance(items, list) or [i.get("id") for i in items if isinstance(i, dict)] != required:
        raise PHError("state.items must list the full migration chain")
    for item in items:
        if not isinstance(item, dict) or item.get("status") not in ITEM_STATUSES or not isinstance(item.get("evidence"), str):
            raise PHError("illegal state item")


def move_to_trash(path: Path) -> None:
    dest_dir = Path.home() / "trash"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"ph-merge-update-{os.getpid()}-{time.time_ns()}-{path.name}"
    path.rename(dest)


def dump_json(path: Path, data: dict) -> None:
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.is_symlink() or is_disallowed_reparse(path):
        raise PHError(f"refusing to write through symlink or junction: {path}")
    if path.exists() and is_hardlink(path):
        raise PHError(f"refusing to write through hardlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(raw)
        os.replace(tmp, path)
    except Exception:
        if fd >= 0:
            os.close(fd)
        if tmp.exists() or tmp.is_symlink():
            move_to_trash(tmp)
        raise


def write_state(repo: Path, to_version: str, data: dict) -> None:
    dest = updates_dir(repo, to_version)
    dest.mkdir(parents=True, exist_ok=True)
    assert_real_dir(repo, dest, f".agents/updates/{to_version}")
    path = dest / "state.json"
    if path.exists() or path.is_symlink():
        assert_real_file(repo, path, "update state.json")
    dump_json(path, data)


def resolve_from_version(disk_version: str, to_version: str, existing: dict | None) -> str:
    if existing is not None:
        from_version = existing.get("from_version")
        if not isinstance(from_version, str) or not SEMVER.match(from_version):
            raise PHError("illegal state.from_version")
        if existing.get("to_version") != to_version:
            raise PHError("state.to_version does not match target")
        if disk_version not in {from_version, to_version}:
            raise PHError(
                f"interrupted update disk version {disk_version} is neither from {from_version} nor to {to_version}"
            )
        return from_version
    return disk_version


def inspect_payload(repo: Path) -> dict:
    to_version, _skills = release_contract()
    data = read_disk_manifest(repo)
    names = live_skills(repo)
    profile, conflicts = detect_profile(names)
    codex = codex_retirement_status(repo)
    conflicts = list(conflicts) + [
        f"{CODEX_SKILLS_REL}/{i['name']}: {i['reason']}" for i in codex["blocked"]
    ]
    disk_version = manifest_version(data)
    src = source_status(to_version)
    updates = repo / ".agents" / "updates"
    if updates.exists() or updates.is_symlink():
        updates_dir(repo, to_version)
    state_path = updates / to_version / "state.json"
    existing = load_state(repo, to_version) if state_path.exists() or state_path.is_symlink() else None
    from_version = resolve_from_version(disk_version, to_version, existing)
    conflicts += release_skill_name_conflicts(names, disk_version, existing)
    if semver_tuple(from_version) > semver_tuple(to_version):
        raise PHError(f"refusing downgrade {from_version} -> {to_version}")
    chain = chain_between(from_version, to_version)
    mode = repo_mode(repo, data)
    up_to_date = disk_version == to_version and (existing is None or existing.get("status") == "complete")
    if up_to_date:
        if existing is not None:
            verify_payload(repo)
        else:
            codex_verify_check(repo, disk_version, to_version)
        raise_if_blocked(cmd_check(repo, mode), "ordinary check")
        content = ph_layout.verify_constraints(repo, Path(__file__).resolve().parents[1])
        if not content["ok"]:
            conflicts.extend(content["problems"])
            up_to_date = False
    return {
        "action": "inspect", "from": from_version, "to": to_version, "profile": profile,
        "up_to_date": up_to_date, "conflicts": conflicts, "chain": chain, "mode": mode,
        "source": src, "can_finalize": src["can_finalize"] and not up_to_date and not conflicts,
        "existing_state": existing, "suggested_state": None if up_to_date else suggested_state(from_version, to_version, src),
        "skills": sorted(names), "codex_retirement": codex,
    }


def target_paths() -> tuple[list[str], list[str]]:
    """1.2.1 terminal layout: the intent tree is retired, so the mandatory
    targets are the project-harness home skeleton instead."""
    home = ".agents/project-harness"
    dirs = (
        f"{home}/constraints",
        f"{home}/documents",
        f"{home}/memory/temporary",
        f"{home}/memory/structured",
        f"{home}/runtime",
        f"{home}/specs",
        f"{home}/archive",
    )
    files = (f"{home}/README.md", f"{home}/memory/README.md", f"{home}/memory/temporary/README.md", f"{home}/memory/structured/README.md")
    return list(dirs), list(files)


def leftover_aliases(repo: Path) -> list[str]:
    leftover = [n for n in OLD_ALIASES if n in live_skills(repo)]
    leftover += [posix_rel(f"{v}/skills/{n}") for v in (".claude", ".codex") for n in OLD_ALIASES if (p := repo / v / "skills" / n).exists() or p.is_symlink()]
    return leftover


def check_target_layout(repo: Path, skills: tuple[str, ...]) -> None:
    for name in skills:
        root = repo / ".agents" / "skills" / name
        assert_real_dir(repo, root, f"canonical skill {name}")
        assert_real_file(repo, root / "SKILL.md", f"canonical skill {name}/SKILL.md")
    script = repo / ".agents" / "scripts" / "ph_worktree.py"
    assert_real_file(repo, script, ".agents/scripts/ph_worktree.py")
    human = repo / ".agents" / "scripts" / "ph_human.py"
    assert_real_file(repo, human, ".agents/scripts/ph_human.py")
    protocol = repo / ".agents" / "scripts" / "ph_sdd.py"
    if protocol.is_symlink() or not protocol.is_file():
        raise PHError(".agents/scripts/ph_sdd.py (self-developed runtime protocol script) is missing")
    # The retired spec-kit integration must be fully gone from the release
    # root; the governance module owns the materialized-constitution and
    # navigation checks now.
    if (SOURCE_ROOT / "scripts" / "ph_speckit.py").is_file():
        raise PHError("scripts/ph_speckit.py is retired; the release root must not ship it anymore")
    verify_governance_layout(repo)
    dirs, files = target_paths()
    for rel in dirs:
        assert_real_dir(repo, repo / rel, rel)
    for rel in files:
        dest = repo / rel
        assert_real_file(repo, dest, rel)
        text = dest.read_text(encoding="utf-8")
        if not text.strip():
            raise PHError(f"{rel} is empty")

    leftover = leftover_aliases(repo)
    if leftover:
        raise PHError("old intent aliases still live: " + ", ".join(leftover))

    # The active-feature pointer is the runtime scripts' entry into the specs
    # tree: a value left at a pre-1.2.1 location (root specs/) makes every
    # spec command silently resolve to a retired directory, so an unresolvable
    # pointer blocks verify instead of passing as a finished upgrade.
    feature_json = repo / ph_layout.RUNTIME / "feature.json"
    if feature_json.is_file() and not feature_json.is_symlink():
        try:
            pointer = str((read_json(feature_json) or {}).get("feature_directory") or "")
        except (ValueError, OSError):
            raise PHError(f"{ph_layout.RUNTIME}/feature.json is not readable JSON")
        if pointer and not pointer.startswith("/"):
            if not (repo / pointer).is_dir():
                raise PHError(
                    f"{ph_layout.RUNTIME}/feature.json points at {pointer!r}, which is not a directory; "
                    "adapt the active-feature pointer to the project-harness specs root"
                )


def assert_target_schema(repo: Path) -> None:
    disk = repo / ".agents" / "ph.schema.json"
    target = SOURCE_ROOT / "assets" / "scaffold" / ".agents" / "ph.schema.json"
    assert_real_file(repo, disk, "canonical .agents/ph.schema.json")
    if target.is_symlink() or is_hardlink(target) or not target.is_file():
        raise PHError("target ph.schema.json is missing from the source root")
    if read_json(disk) != read_json(target):
        raise PHError("disk ph.schema.json does not match target schema")


def assert_local_ph_init(repo: Path, version: str, skills: tuple[str, ...]) -> None:
    root = repo / ".agents" / "skills" / "ph-init"
    assert_real_dir(repo, root, "canonical skill ph-init")
    release_path = root / "release.json"
    assert_real_file(repo, release_path, "installed ph-init release.json")
    data = read_json(release_path)
    if data.get("version") != version:
        raise PHError("installed ph-init release metadata does not match target")
    if list(data.get("required_skills") or []) != list(skills):
        raise PHError("installed ph-init required_skills do not match target")
    target_release = SOURCE_ROOT / "release.json"
    if not target_release.is_file() or release_path.read_bytes() != target_release.read_bytes():
        raise PHError("installed ph-init release.json does not match source release.json")
    for rel in PH_INIT_RUNTIME:
        assert_real_file(repo, root / rel, f"installed ph-init {rel}")


# ---------------------------------------------------------------------------
# Tool-neutral adapter retirement (1.1.9, item tool-neutral-adapters).
#
# Codex and OpenCode read AGENTS.md and `.agents/skills` natively, so the
# `.codex/skills/ph-*` mirrors are retired: verify classifies each leftover
# against verifiable evidence, finalize --apply moves the provably managed
# ones into the project-harness archive legacy-backup (<date>-pre-update/codex-skills/), and anything
# unprovable stays in place and blocks. Non ph-* entries are never touched.
# ---------------------------------------------------------------------------


def codex_skills_root_issue(repo: Path) -> str | None:
    """Shape problems of the .codex / .codex/skills adapter roots themselves."""
    for label in (".codex", CODEX_SKILLS_REL):
        node = repo / label
        if node.is_symlink() or is_disallowed_reparse(node):
            return f"{label} is a symlink or junction"
        if node.exists() and not node.is_dir():
            return f"{label} is not a directory"
    return None


def codex_leftover_names(repo: Path) -> list[str]:
    """Live .codex/skills/ph-* entry names; non ph-* entries are never listed."""
    root = repo / ".codex" / "skills"
    if not root.exists() and not root.is_symlink():
        return []
    return sorted(
        child.name
        for child in root.iterdir()
        if child.name.startswith("ph-") and (child.exists() or child.is_symlink())
    )


def _head_blob_map(repo: Path, *pathspecs: str) -> dict[str, str] | None:
    """Full-path -> blob id at git HEAD, or None when HEAD is unreadable."""
    proc = run_git("ls-tree", "-r", "-z", "--full-tree", "HEAD", "--", *pathspecs, cwd=repo)
    if proc.returncode != 0:
        return None
    blobs: dict[str, str] = {}
    for line in proc.stdout.split("\0"):
        if not line:
            continue
        meta, sep, path = line.partition("\t")
        parts = meta.split()
        if not sep or len(parts) != 3 or parts[1] != "blob" or not HEX40.match(parts[2]):
            return None
        blobs[path] = parts[2]
    return blobs


def _noise_free_tree(blobs: dict[str, str], prefix: str) -> dict[str, str]:
    """Strip one path prefix and the VCS/OS noise names ph_init skips."""
    out: dict[str, str] = {}
    for path, oid in blobs.items():
        if not path.startswith(prefix):
            continue
        rel = path[len(prefix):]
        if not rel or any(part in ph_init.SKIP_DIR_NAMES for part in rel.split("/")):
            continue
        base = rel.rsplit("/", 1)[-1]
        if base in ph_init.SKIP_FILE_NAMES or Path(base).suffix in ph_init.SKIP_SUFFIXES:
            continue
        out[rel] = oid
    return out


def codex_snapshot_proof(repo: Path, name: str, entry: Path, mirror: dict[str, str]) -> bool:
    """Prove a portable mirror was a managed copy via the pre-upgrade git snapshot.

    Evidence contract: at git HEAD — the last committed pre-upgrade state —
    the mirror's tracked blobs are exactly the canonical skill's blobs, and
    the on-disk mirror still matches those blobs byte for byte, so no project
    content is unique to the mirror. Uncommitted, untracked, or drifted
    mirrors produce no proof and stay blocked.
    """
    head = _head_blob_map(repo, f"{CODEX_SKILLS_REL}/{name}", f".agents/skills/{name}")
    if head is None:
        return False
    mirror_head = _noise_free_tree(head, f"{CODEX_SKILLS_REL}/{name}/")
    canon_head = _noise_free_tree(head, f".agents/skills/{name}/")
    if not mirror_head or mirror_head != canon_head:
        return False
    if set(mirror) != set(mirror_head):
        return False
    for rel in mirror:
        try:
            if git_blob_id((entry / rel).read_bytes()) != mirror_head[rel]:
                return False
        except OSError:
            return False
    return True


def classify_codex_leftover(repo: Path, name: str) -> tuple[str, str]:
    """Classify one live .codex/skills/ph-* entry for the tool-neutral retirement.

    ("retire", evidence) only when the entry is provably a PH-managed adapter:
    a relative symlink with exactly the managed target, or a portable mirror
    whose bytes are identical to the canonical skill (lossless) or to the
    pre-upgrade canonical snapshot recorded at git HEAD. Every other shape —
    wrong link target, junction, plain file, content drift, missing evidence —
    is ("block", reason) and must stay in place for a human decision.
    """
    entry = repo / ".codex" / "skills" / name
    canonical = repo / ".agents" / "skills" / name
    rel = f"{CODEX_SKILLS_REL}/{name}"
    expected = expected_rel_link(entry, canonical)
    if entry.is_symlink():
        raw = posix_rel(os.readlink(entry))
        if os.path.isabs(raw) or raw != expected:
            return "block", f"symlink target {raw!r} is not the managed relative link {expected!r}"
        resolved = (entry.parent / raw).resolve()
        if not canonical.is_dir() or not contained(repo, resolved) or resolved != canonical.resolve():
            return "block", "symlink does not resolve to the canonical skill directory"
        return "retire", f"managed relative symlink -> {expected}"
    if entry.exists() and not entry.is_dir():
        if is_git_symlink_mode(repo, rel) and entry.read_text(encoding="utf-8", errors="replace") == expected:
            return "retire", f"git mode 120000 degenerated symlink -> {expected}"
        return "block", "entry is a regular file, not a skill mirror directory or symlink"
    if not entry.exists():
        return "block", "entry vanished while classifying"
    if is_disallowed_reparse(entry):
        return "block", "entry is a junction or reparse point"
    try:
        mirror: dict[str, str] = {}
        for path in iter_files(entry):
            if path.stat().st_nlink > 1:
                return "block", f"mirror file is a hardlink: {posix_rel(path.relative_to(entry))}"
            mirror[posix_rel(path.relative_to(entry))] = sha256_file(path)
    except PHError as exc:
        return "block", f"mirror tree is not safe to classify: {exc}"
    if canonical.is_dir():
        try:
            canon = {
                posix_rel(p.relative_to(canonical)): sha256_file(p)
                for p in iter_files(canonical)
            }
        except PHError:
            canon = None
        if canon is not None and mirror == canon:
            return "retire", "mirror bytes are identical to the canonical skill; archiving is lossless"
    if codex_snapshot_proof(repo, name, entry, mirror):
        return "retire", "mirror matches the pre-upgrade canonical snapshot at git HEAD"
    return "block", (
        "cannot prove the mirror is PH-managed content: it differs from the canonical skill and "
        "git HEAD holds no pre-upgrade snapshot proving it was a managed copy; archive it during "
        "the semantic merge phase or commit the pre-upgrade state, then re-verify"
    )


def codex_retirement_status(repo: Path) -> dict:
    """Read-only classification of live .codex/skills/ph-* adapters."""
    issue = codex_skills_root_issue(repo)
    if issue is not None:
        return {
            "root_issue": issue,
            "retirable": [],
            "blocked": [{"name": CODEX_SKILLS_REL, "reason": issue}],
        }
    retirable: list[dict] = []
    blocked: list[dict] = []
    for name in codex_leftover_names(repo):
        verdict, reason = classify_codex_leftover(repo, name)
        (retirable if verdict == "retire" else blocked).append({"name": name, "reason": reason})
    return {"root_issue": None, "retirable": retirable, "blocked": blocked}


def codex_blocked_error(status: dict) -> PHError:
    detail = "; ".join(f"{CODEX_SKILLS_REL}/{i['name']}: {i['reason']}" for i in status["blocked"])
    return PHError(
        "blocked codex skill adapters stay in place; archive them during the semantic merge "
        "phase or restore the verifiable evidence, then re-verify: " + detail
    )


def codex_verify_check(repo: Path, disk_version: str, to_version: str) -> list[str]:
    """Enforce the tool-neutral codex contract for verify and completed inspect.

    Blocked entries always fail. Once the target version is written, any live
    leftover fails: the upgrade retires .codex/skills/ph-* before it may
    complete. Returns the retirable names for reporting.
    """
    status = codex_retirement_status(repo)
    if status["blocked"]:
        raise codex_blocked_error(status)
    live = [i["name"] for i in status["retirable"]]
    if disk_version == to_version and live:
        raise PHError(
            f"project is already at {to_version} but codex skill adapters are still live: "
            + ", ".join(f"{CODEX_SKILLS_REL}/{n}" for n in live)
            + "; archive them under .agents/project-harness/archive/legacy-backup/<date>-pre-update/codex-skills/ "
            "or remove them, then re-verify"
        )
    return live


def codex_archive_base(repo: Path) -> Path:
    """Archive root for retired codex adapters, stable across interrupted runs.

    Reuses an existing <date>-pre-update/codex-skills directory an earlier
    interrupted finalize already created; otherwise today's UTC date starts a
    fresh one. Other archived content is never considered or touched.
    """
    # 1.2.1 unified archive: retired adapters land under the project-harness
    # archive, never a top-level .agents/archived directory.
    archived = repo / ".agents" / "project-harness" / "archive" / "legacy-backup"
    if archived.is_dir() and not archived.is_symlink():
        for child in sorted(archived.iterdir()):
            if (
                child.name.endswith(CODEX_ARCHIVE_SUFFIX)
                and child.is_dir()
                and not child.is_symlink()
                and (child / CODEX_ARCHIVE_CHILD).is_dir()
            ):
                return child / CODEX_ARCHIVE_CHILD
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return archived / f"{day}{CODEX_ARCHIVE_SUFFIX}" / CODEX_ARCHIVE_CHILD


def ensure_real_archive_dir(repo: Path, dest: Path) -> None:
    """Create the archive dir without ever crossing a link or escaping the repo."""
    issue = ancestor_issue(repo, dest)
    if issue:
        raise PHError(f"codex archive destination is unsafe: {issue}")
    dest.mkdir(parents=True, exist_ok=True)
    issue = ancestor_issue(repo, dest)
    if issue or dest.is_symlink() or is_disallowed_reparse(dest) or not dest.is_dir() or not contained(repo, dest):
        raise PHError("codex archive destination is not a repository-local real directory")


def is_reusable_symlink_record(dest: Path, record: str) -> bool:
    """True only when dest is exactly the deterministic record for the live link.

    An interrupted run persists the record before unlinking the live symlink,
    so a resume may reuse the leftover only when it is a plain regular file —
    not a symlink, not a hardlink — whose bytes equal the deterministic record
    this run is about to write; only that proves it is this upgrade's own
    leftover rather than independent content. Anything else stays a collision.
    """
    if dest.is_symlink() or is_disallowed_reparse(dest) or is_hardlink(dest) or not dest.is_file():
        return False
    try:
        return dest.read_bytes() == record.encode("utf-8")
    except OSError:
        return False


def retire_codex_adapters(repo: Path) -> list[dict]:
    """Archive provably managed .codex/skills/ph-* adapters inside the project.

    Only finalize --apply calls this: verify classifies first, every entry is
    re-classified at move time (fresh evidence against races), and each entry
    lands under the project-harness archive legacy-backup (<date>-pre-update/codex-skills/<name>) so the
    pre-upgrade adapter stays recoverable. Portable mirrors and degenerated
    link files are moved as-is; a live symlink cannot be moved into .agents
    (the canonical tree must stay link-free), so it is unlinked and a regular
    record file with the original link target is written instead — the record
    is always persisted before the link is removed, and a run interrupted in
    between resumes by reusing that exact record. Non ph-* entries are never
    touched, and an interrupted run resumes idempotently: entries archived by
    a previous run no longer exist live, and the archive directory is reused.
    """
    issue = codex_skills_root_issue(repo)
    if issue is not None:
        raise PHError(f"cannot retire codex adapters: {issue}")
    base = codex_archive_base(repo)
    results: list[dict] = []
    for name in codex_leftover_names(repo):
        if "/" in name or name in {"", ".", ".."}:
            raise PHError(f"illegal codex skill entry name: {name!r}")
        entry = repo / ".codex" / "skills" / name
        if not entry.exists() and not entry.is_symlink():
            results.append({"name": name, "result": "already_retired"})
            continue
        verdict, reason = classify_codex_leftover(repo, name)
        if verdict != "retire":
            raise PHError(f"refusing to archive {CODEX_SKILLS_REL}/{name}: {reason}")
        ensure_real_archive_dir(repo, base)
        dest = base / name
        record: str | None = None
        if entry.is_symlink():
            target_text = os.readlink(entry)
            record = f"retired codex symlink: {CODEX_SKILLS_REL}/{name} -> {posix_rel(target_text)}\n"
        if (dest.exists() or dest.is_symlink()) and not (
            record is not None and is_reusable_symlink_record(dest, record)
        ):
            raise PHError(
                f"codex archive collision: {posix_rel(dest.relative_to(repo))} already exists while "
                f"{CODEX_SKILLS_REL}/{name} is still live; keep both and decide manually"
            )
        if record is not None:
            # The record must be on disk before the link disappears: the link
            # target is the only evidence, and the unlink may be interrupted.
            if not (dest.exists() or dest.is_symlink()):
                dest.write_text(record, encoding="utf-8")
            try:
                entry.unlink()
            except OSError as exc:
                raise PHError(
                    f"cannot unlink {CODEX_SKILLS_REL}/{name} after writing its archive record: {exc}"
                ) from exc
            kind = "symlink-record"
        else:
            try:
                entry.rename(dest)
            except OSError as exc:
                raise PHError(f"cannot move {CODEX_SKILLS_REL}/{name} into the archive: {exc}") from exc
            kind = "moved-tree"
        if entry.exists() or entry.is_symlink() or not (dest.exists() or dest.is_symlink()):
            raise PHError(f"archiving {CODEX_SKILLS_REL}/{name} did not land in the archive")
        results.append({
            "name": name,
            "result": "archived",
            "kind": kind,
            "dest": posix_rel(dest.relative_to(repo)),
            "reason": reason,
        })
    remaining = codex_leftover_names(repo)
    if remaining:
        raise PHError("codex skill adapters still live after retirement: " + ", ".join(remaining))
    return results


def merge_codex_retired(state: dict, results: list[dict]) -> bool:
    """Fold this run's codex archive results into state.retired_codex.

    Every archived adapter is recorded with its name, dest, kind, and the
    classification reason that justified retiring it, so resumed and repeated
    runs stay auditable. Records from earlier runs are kept and only names
    archived again are replaced, so a repeated finalize leaves already
    recorded state byte-identical. Returns True when the state changed.
    """
    previous = state.get("retired_codex")
    known = {
        item["name"]: item
        for item in (previous if isinstance(previous, list) else [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    changed = False
    for item in results:
        if item.get("result") != "archived":
            continue
        entry = {
            "name": item["name"],
            "kind": item.get("kind"),
            "dest": item.get("dest"),
            "reason": item.get("reason"),
        }
        if known.get(item["name"]) != entry:
            known[item["name"]] = entry
            changed = True
    if not changed:
        return False
    state["retired_codex"] = [known[name] for name in sorted(known)]
    return True


def raise_if_blocked(report, label: str) -> None:
    if not report.blocked:
        return
    details = [f"{item.kind} {item.path}: {item.reason}" for item in report.items if item.kind in {"conflict", "block", "error"}]
    raise PHError(f"{label}: " + ("; ".join(details) or "blocked"))


# ---------------------------------------------------------------------------
# 1.2.3 self-developed runtime takeover (item sdd-runtime-takeover): the
# constitution materialization, navigation refresh and content evidence checks
# moved from the retired spec-kit integration script into ph_governance.py.
# ---------------------------------------------------------------------------


def verify_governance_layout(repo: Path) -> None:
    """Verify the materialized constitution and the self-developed runtime
    anchors through the governance module."""

    import ph_governance

    result = ph_governance.check_governance(repo)
    if not result["ok"]:
        raise PHError("governance verification failed: " + "; ".join(result["problems"]))


# ---------------------------------------------------------------------------
# 1.2.3 skill replacement (item sdd-skill-replacement): deterministic
# classification and archival for the retired spec-kit skill generation, plus
# the install of the self-developed skills from the release scaffold.
#
# Identity recognition is per skill directory and keyed on the SKILL.md
# content baseline the spec-kit installs recorded in `.agents/ph.json`
# `speckit.files`:
#   - disk SKILL.md == release scaffold bytes       -> already at target;
#     remaining release-set files are healed in place (idempotent completion).
#   - disk SKILL.md sha256 == recorded baseline     -> managed previous
#     generation: the whole directory (including extra files such as evals,
#     references or user additions) is first archived byte-preserving, then a
#     replaced name is installed fresh from the release scaffold; a retired
#     name is simply gone.
#   - anything else                                 -> unattributable
#     (user-customized or third-party) content: the item is blocked, nothing
#     is touched.
# `.claude/skills/<name>` mirrors are retired before their canonical tree
# (portable: byte-identical mirrors move, differing mirrors block; symlink:
# a deterministic record is persisted before the link is removed) so an
# interrupted run always resumes with evidence. Re-runs skip already retired
# entries and complete partially healed directories.
# ---------------------------------------------------------------------------


def _sdd_release_skill_dir(name: str) -> Path:
    return SOURCE_ROOT / "assets" / "scaffold" / ".agents" / "skills" / name


def _sdd_archive_base(repo: Path) -> Path:
    """Archive root for retired skill trees, stable across interrupted runs.

    Reuses an existing <date>-pre-update/retired-skills directory an earlier
    interrupted run already created; otherwise today's UTC date starts a fresh
    one. Other archived content is never considered or touched.
    """

    archived = repo / ".agents" / "project-harness" / "archive" / "legacy-backup"
    if archived.is_dir() and not archived.is_symlink():
        for child in sorted(archived.iterdir()):
            if (
                child.name.endswith(CODEX_ARCHIVE_SUFFIX)
                and child.is_dir()
                and not child.is_symlink()
                and (child / "retired-skills").is_dir()
            ):
                return child / "retired-skills"
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return archived / f"{day}{CODEX_ARCHIVE_SUFFIX}" / "retired-skills"


def _sdd_dir_files(root: Path) -> dict[str, bytes]:
    reject_nested_links(root, label=f"skill tree {root.name}")
    return {
        posix_rel(path.relative_to(root)): path.read_bytes()
        for path in iter_files(root)
    }


def _sdd_baselines(data: dict) -> dict[str, str]:
    """The well-formed `speckit.files` baseline entries of a disk manifest."""

    section = data.get("speckit") if isinstance(data.get("speckit"), dict) else {}
    files = section.get("files")
    hex64 = re.compile(r"^[0-9a-f]{64}$")
    if not isinstance(files, dict):
        return {}
    return {
        key: value
        for key, value in files.items()
        if isinstance(key, str) and isinstance(value, str) and hex64.fullmatch(value)
    }


def _sdd_ensure_safe_write_dest(repo: Path, rel: str) -> Path:
    """Resolve a managed write destination, refusing links and escapes.

    Every component from the repository root down to the destination must be
    a real repository-local directory, and an existing destination a regular
    non-hardlinked file. Used by every migrate-skills write path.
    """

    dest = (repo / rel).absolute()
    repo_a = repo.absolute()
    if not repo_a.is_dir() or repo_a.is_symlink() or is_disallowed_reparse(repo_a):
        raise PHError(f"{rel}: repository root is not a real directory")
    cur = repo_a
    parts = PurePosixPath(posix_rel(dest.relative_to(repo_a))).parts
    for index, part in enumerate(parts):
        cur = cur / part
        if cur.is_symlink() or is_disallowed_reparse(cur):
            raise PHError(f"{rel}: {posix_rel(cur.relative_to(repo_a))} is a symlink or junction; refusing to write")
        last = index == len(parts) - 1
        if last:
            if cur.exists() and (not cur.is_file() or is_hardlink(cur)):
                raise PHError(f"{rel}: destination is not a regular unshared file")
        else:
            if cur.exists() and (not cur.is_dir() or is_disallowed_reparse(cur)):
                raise PHError(f"{rel}: {posix_rel(cur.relative_to(repo_a))} is not a real directory")
        if not contained(repo_a, cur):
            raise PHError(f"{rel}: destination escapes the repository")
    return Path(dest)


def _sdd_classify(repo: Path, name: str, baselines: dict[str, str]) -> str:
    """current | managed-old | absent | blocked for one managed skill name.

    current      the SKILL.md already carries the release generation bytes;
    managed-old  the SKILL.md still matches the recorded install baseline;
    absent       no live directory;
    blocked      anything else (symlink shapes, missing SKILL.md, or bytes
                 matching neither the release nor the baseline): user or
                 third-party content that must never be touched.
    """

    skill = repo / ".agents" / "skills" / name
    if not skill.exists() and not skill.is_symlink():
        return "absent"
    try:
        assert_real_dir(repo, skill.parent, ".agents/skills")
        if skill.is_symlink() or is_disallowed_reparse(skill) or is_hardlink(skill) or not skill.is_dir():
            return "blocked"
        reject_nested_links(skill, label=f"canonical skill {name}")
    except PHError:
        return "blocked"
    skill_md = skill / "SKILL.md"
    if skill_md.is_symlink() or is_hardlink(skill_md) or not skill_md.is_file():
        return "blocked"
    release_skill_md = _sdd_release_skill_dir(name) / "SKILL.md"
    disk_bytes = skill_md.read_bytes()
    if release_skill_md.is_file() and disk_bytes == release_skill_md.read_bytes():
        return "current"
    baseline_rel = f"{SDD_SKILL_BASELINE_PREFIX}{name}/SKILL.md"
    expected = baselines.get(baseline_rel)
    if expected is not None and sha256_file(skill_md) == expected:
        return "managed-old"
    return "blocked"


def _sdd_retire_tree(repo: Path, source: Path, dest: Path, label: str) -> dict:
    """Move one directory tree into the archive, byte-preserving."""

    ensure_real_archive_dir(repo, dest.parent)
    if dest.exists() or dest.is_symlink():
        raise PHError(
            f"retired-skill archive collision: {posix_rel(dest.relative_to(repo))} already exists while "
            f"{label} is still live; keep both and decide manually"
        )
    try:
        source.rename(dest)
    except OSError as exc:
        raise PHError(f"cannot move {label} into the archive: {exc}") from exc
    if source.exists() or source.is_symlink() or not dest.is_dir():
        raise PHError(f"archiving {label} did not land in the archive")
    return {"kind": "moved-tree", "dest": posix_rel(dest.relative_to(repo))}


# Vendor mirror roots that may hold per-skill mirrors of the managed
# canonical tree. `.claude` is the live adapter; `.codex` is the retired
# 1.1.9 topology whose leftovers may still pend finalize - retiring the
# canonical skill destroys their classification proof, so they retire with it.
SDD_MIRROR_ROOTS = (".claude", ".codex")


def _sdd_retire_mirror(repo: Path, name: str, mirror_rel: str, proof: dict | None, apply: bool) -> dict | None:
    """Retire one `.claude|.codex /skills/<name>` mirror before the canonical tree.

    Returns None when no mirror lives there. Portable mirrors are archived
    only when proven managed: every mirror file's sha256 must equal the
    recorded `speckit.files` baseline of that file where one exists (the
    historical install pinned a subset of the managed files), and every
    unpinned mirror file must be byte-identical to the canonical managed
    tree being retired; mirror files outside that tree are user content.
    Symlink mirrors persist a deterministic record before the link is
    removed (the record is always on disk before the link disappears, so an
    interrupted run resumes by reusing it). Anything else is user content and
    raises instead of being touched. Without apply the mirror is only
    classified and reported - plan mode never writes.
    """

    mirror = repo / mirror_rel / "skills" / name
    if not mirror.exists() and not mirror.is_symlink():
        return None
    base = _sdd_archive_base(repo)
    dest = base / f"{name}.{mirror_rel.lstrip('.')}-mirror"
    if mirror.is_symlink():
        target_text = os.readlink(mirror)
        record = f"retired skill symlink mirror: {mirror_rel}/skills/{name} -> {posix_rel(target_text)}\n"
        if (dest.exists() or dest.is_symlink()) and not is_reusable_symlink_record(dest, record):
            raise PHError(
                f"retired-skill archive collision: {posix_rel(dest.relative_to(repo))} already exists while "
                f".claude/skills/{name} is still live; keep both and decide manually"
            )
        if not apply:
            return {"kind": "symlink-record", "planned": True, "dest": posix_rel(dest.relative_to(repo))}
        ensure_real_archive_dir(repo, dest.parent)
        if not (dest.exists() or dest.is_symlink()):
            dest.write_text(record, encoding="utf-8")
        try:
            mirror.unlink()
        except OSError as exc:
            raise PHError(f"cannot unlink {mirror_rel}/skills/{name} after writing its archive record: {exc}") from exc
        return {"kind": "symlink-record", "dest": posix_rel(dest.relative_to(repo))}
    if mirror.is_symlink() or is_disallowed_reparse(mirror) or not mirror.is_dir():
        raise PHError(f"{mirror_rel}/skills/{name} is not a recognizable mirror; preserve it for review")
    if proof is None:
        raise PHError(
            f"{mirror_rel}/skills/{name} cannot be proven a managed mirror (the canonical tree is already "
            "retired); preserve it for review"
        )
    try:
        mirror_files = _sdd_dir_files(mirror)
    except PHError as exc:
        raise PHError(f"{mirror_rel}/skills/{name} cannot be inspected: {exc}") from exc
    canonical, pinned = proof["canonical"], proof["pinned"]
    if set(mirror_files) - set(canonical):
        raise PHError(
            f"{mirror_rel}/skills/{name} carries files the managed canonical skill does not have; "
            "treat it as user content, keep it in place, block the item, and ask the user"
        )
    missing = sorted(set(pinned) - set(mirror_files))
    if missing:
        raise PHError(
            f"{mirror_rel}/skills/{name} is missing pinned managed files ({', '.join(missing)}); "
            "treat it as user content, keep it in place, block the item, and ask the user"
        )
    unpinned = sorted(rel for rel in mirror_files if rel not in pinned and canonical.get(rel) != mirror_files[rel])
    if unpinned:
        raise PHError(
            f"{mirror_rel}/skills/{name} differs from the managed canonical skill ({', '.join(unpinned)}); "
            "treat it as user content, keep it in place, block the item, and ask the user"
        )
    mismatched = sorted(
        rel for rel, data in mirror_files.items()
        if rel in pinned and sha256_bytes(data) != pinned[rel]
    )
    if mismatched:
        raise PHError(
            f"{mirror_rel}/skills/{name} differs from the managed generation recorded in .agents/ph.json "
            f"({', '.join(mismatched)}); treat it as user content, keep it in place, block the item, and "
            "ask the user"
        )
    if dest.exists() or dest.is_symlink():
        raise PHError(
            f"retired-skill archive collision: {posix_rel(dest.relative_to(repo))} already exists while "
            f"{mirror_rel}/skills/{name} is still live; keep both and decide manually"
        )
    if not apply:
        return {"kind": "moved-tree", "planned": True, "dest": posix_rel(dest.relative_to(repo))}
    ensure_real_archive_dir(repo, dest.parent)
    try:
        mirror.rename(dest)
    except OSError as exc:
        raise PHError(f"cannot move {mirror_rel}/skills/{name} into the archive: {exc}") from exc
    if mirror.exists() or mirror.is_symlink() or not dest.is_dir():
        raise PHError(f"archiving .claude/skills/{name} did not land in the archive")
    return {"kind": "moved-tree", "dest": posix_rel(dest.relative_to(repo))}


def _sdd_staging_base(repo: Path) -> tuple[Path, str]:
    """The managed staging area for fresh skill installs, plus its version.

    Staging lives inside the update flow's own state directory
    (``.agents/updates/<to_version>/sdd-skill-staging``): no check, sync or
    verify enumerates that directory exhaustively, and the atomic
    ``os.rename`` from there into ``.agents/skills/<name>`` stays within the
    repository's single filesystem.
    """

    to_version, _skills = release_contract()
    base = updates_dir(repo, to_version) / "sdd-skill-staging"
    return base, to_version


def _sdd_dest_chain_conflicts(repo: Path, dest: Path, label: str) -> list[str]:
    """Pure-read shape check of the whole ``dest`` chain before any mkdir.

    Every node from the repository root down to ``dest`` - existing or not -
    must be (or become) a real repository-local directory: a symlinked or
    non-directory ancestor is reported as a conflict so the write path never
    discovers it after other steps already moved, and never writes through
    it while creating the missing levels.
    """

    out: list[str] = []
    cur = repo
    for part in dest.relative_to(repo).parts:
        cur = cur / part
        issue = ancestor_issue(repo, cur)
        if issue:
            out.append(f"{label} is unsafe: {issue}")
            return out
        if cur.exists() or cur.is_symlink():
            if cur.is_symlink() or is_disallowed_reparse(cur) or not cur.is_dir():
                out.append(
                    f"{label} is unsafe: {posix_rel(cur.relative_to(repo))} is not a real directory"
                )
                return out
    return out


def _sdd_staging_chain_conflicts(repo: Path) -> list[str]:
    """The pure-read conflicts of the skill install staging path."""

    try:
        base, _to_version = _sdd_staging_base(repo)
    except PHError as exc:
        return [str(exc)]
    return _sdd_dest_chain_conflicts(repo, base, "skill install staging")


def _sdd_prepare_staging(repo: Path, name: str) -> Path:
    """A fresh uniquely named staging directory for one skill install.

    Every install creates its own directory via ``tempfile.mkdtemp`` inside
    the managed staging base and only ever writes into the path it just
    created, so the staging base never becomes an ownership proof: existing
    entries below it - an earlier interrupted run's leftover staging or
    anything else - are never read, moved or taken over, and their presence
    neither blocks a new install nor contributes evidence (an interrupted
    install simply restages and succeeds, leaving the old scratch in place
    as evidence). The whole chain is re-validated with pure reads BEFORE any
    directory is created, so a link can never be written through.
    """

    base, _to_version = _sdd_staging_base(repo)
    chain_conflicts = _sdd_staging_chain_conflicts(repo)
    if chain_conflicts:
        raise PHError(chain_conflicts[0])
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{name}.", dir=base))


def _sdd_install_release_skill(repo: Path, name: str) -> dict:
    """Install one skill directory from the release scaffold, or heal an
    already-current one: only release-set files are written, extra files stay
    user-owned content in place and are reported.

    A fresh install never writes into ``.agents/skills/<name>`` directly: the
    skill is staged in a fresh uniquely named directory inside the managed
    update state directory and moved into place with one atomic rename after
    every staged byte is verified against the scaffold. An interruption
    therefore leaves either no destination or a complete one - the
    half-installed state (mkdir done, SKILL.md missing) that a retry could
    only misread as third-party content and block forever can no longer be
    produced, and a retry simply restages while earlier staging leftovers
    stay in place untouched. An existing canonical directory is never taken
    over: it keeps its third-party protection.
    """

    release = _sdd_release_skill_dir(name)
    if release.is_symlink() or not release.is_dir():
        raise PHError(f"release scaffold is missing the {name} skill")
    dest = repo / ".agents" / "skills" / name
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or is_disallowed_reparse(dest) or not dest.is_dir():
            raise PHError(f".agents/skills/{name} exists and is not a real directory")
        try:
            current = _sdd_dir_files(dest)
        except PHError as exc:
            raise PHError(f".agents/skills/{name} cannot be inspected: {exc}") from exc
    else:
        current = {}
    try:
        target = _sdd_dir_files(release)
    except PHError as exc:
        raise PHError(f"release scaffold skill {name} cannot be read: {exc}") from exc
    extra = sorted(set(current) - set(target))
    if current:
        # Healing a directory whose SKILL.md is proven current: missing
        # release-set files are added; a present file that differs from the
        # release generation has no baseline proof and is never overwritten
        # (the caller pre-checked this as a conflict); extras stay in place.
        for rel, data in sorted(target.items()):
            if current.get(rel) == data:
                continue
            if rel in current:
                raise PHError(
                    f".agents/skills/{name}/{rel} differs from the release generation and no baseline "
                    "proves it managed; keep it in place and ask the user before overwriting"
                )
            _sdd_ensure_safe_write_dest(repo, f".agents/skills/{name}/{rel}")
            child = dest / rel
            child.parent.mkdir(parents=True, exist_ok=True)
            child.write_bytes(data)
    else:
        for rel in sorted(target):
            _sdd_ensure_safe_write_dest(repo, f".agents/skills/{name}/{rel}")
        stage = _sdd_prepare_staging(repo, name)
        for rel in sorted(target):
            child = stage / rel
            child.parent.mkdir(parents=True, exist_ok=True)
            child.write_bytes(target[rel])
        staged = _sdd_dir_files(stage)
        if staged != target:
            raise PHError(f"the staged install of {name} does not match the release scaffold")
        if dest.exists() or dest.is_symlink():
            raise PHError(
                f".agents/skills/{name} appeared while the install was staged; "
                "keep both and decide manually"
            )
        try:
            os.rename(stage, dest)
        except OSError as exc:
            raise PHError(f"cannot move the staged install of {name} into place: {exc}") from exc
        try:
            stage.parent.rmdir()  # best effort: retire the empty staging base
        except OSError:
            pass
    return {"kind": "installed", "files": len(target), "extras_kept": extra}


# Managed files of a spec-kit-era skill directory. Everything else found in a
# managed-old directory is a potential user attachment whose effectiveness the
# migration cannot judge, so it needs an explicit reviewed decision before the
# directory is archived.
SDD_KNOWN_MANAGED_FILES = frozenset({"SKILL.md", "evals/evals.json"})
SDD_EXTRAS_DECISION = "archive"
SDD_EXTRAS_RECORD_FORMAT = "ph.retired-skill-extras/1"


def _sdd_extra_files(repo: Path, name: str) -> list[str]:
    return sorted(set(_sdd_dir_files(repo / ".agents" / "skills" / name)) - SDD_KNOWN_MANAGED_FILES)


def _sdd_load_extras_decisions(path: str | None, names_with_extras: dict[str, list[str]]) -> dict[str, dict]:
    """Load and validate the reviewed extra-file decisions.

    The decisions file maps each skill name that carries extra files to an
    explicit reviewed disposition ({"decision": "archive", "note": "..."}).
    Every name with extras must be covered and nothing beyond them may appear,
    so a stale decisions file cannot silently authorize the wrong directory.
    """

    if not names_with_extras:
        return {}
    if path is None:
        raise PHError(
            "retired skill directories carry files the migration cannot attribute: "
            + "; ".join(f"{name}: {', '.join(files)}" for name, files in sorted(names_with_extras.items()))
            + " — record a reviewed decision for each (JSON: {\"<skill>\": {\"decision\": \"archive\", "
            "\"note\": \"...\"}}) and pass it via --extras-decisions, or keep the directories"
        )
    decisions_path = Path(path)
    if decisions_path.is_symlink() or is_hardlink(decisions_path) or not decisions_path.is_file():
        raise PHError(f"--extras-decisions must be a regular file: {path}")
    try:
        raw = json.loads(decisions_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PHError(f"--extras-decisions is not readable JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PHError("--extras-decisions must be a JSON object keyed by skill name")
    unknown = sorted(set(raw) - set(names_with_extras))
    if unknown:
        raise PHError(f"--extras-decisions covers directories without extra files: {', '.join(unknown)}")
    out: dict[str, dict] = {}
    for name in sorted(names_with_extras):
        entry = raw.get(name)
        if not isinstance(entry, dict):
            raise PHError(f"--extras-decisions[{name}] must be an object")
        if entry.get("decision") != SDD_EXTRAS_DECISION:
            raise PHError(
                f"--extras-decisions[{name}].decision must be {SDD_EXTRAS_DECISION!r}; any other "
                "outcome means the directory stays in place for manual review"
            )
        note = entry.get("note")
        if not isinstance(note, str) or not note.strip():
            raise PHError(f"--extras-decisions[{name}].note must record the review conclusion")
        out[name] = {"decision": entry["decision"], "note": note.strip()}
    return out


def _sdd_extras_record_bytes(name: str, files: list[str], decision: dict) -> bytes:
    """The deterministic bytes of one reviewed extra-file decision record."""

    payload = {
        "format": SDD_EXTRAS_RECORD_FORMAT,
        "skill": name,
        "decision": decision["decision"],
        "note": decision["note"],
        "files": list(files),
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sdd_record_extras(repo: Path, name: str, files: list[str], decision: dict, dest: Path) -> None:
    """Persist the reviewed decision next to the archived tree, idempotently.

    The record lives inside the archive as <name>.extras.json and carries the
    exact file list, the disposition and the review note, so the migration
    decision stays auditable where the files it disposes of are recoverable.
    """

    encoded = _sdd_extras_record_bytes(name, files, decision)
    record = dest.parent / f"{name}.extras.json"
    if record.is_symlink() or is_hardlink(record) or (record.exists() and not record.is_file()):
        raise PHError(f"retired-skill extras record is not a regular file: {posix_rel(record.relative_to(repo))}")
    if record.exists():
        if record.read_bytes() != encoded:
            raise PHError(
                f"retired-skill extras record changed: {posix_rel(record.relative_to(repo))}; "
                "keep both and decide manually"
            )
        return
    record.write_bytes(encoded)


def _sdd_install_conflicts(repo: Path, name: str) -> list[str]:
    """Read-only conflicts an install or heal into ``.agents/skills/<name>``
    would hit, collected before any write.

    A live directory on a PH-reserved name is only healable when its
    SKILL.md is the release generation (the proof that the directory is
    managed): missing release-set files may then be added, extras stay in
    place, and a present file that differs from the release is a conflict.
    Anything else - a missing SKILL.md (an unknown half-install), differing
    bytes, a non-directory shape - is unknown same-name content that stays
    in place and blocks.
    """

    dest = repo / ".agents" / "skills" / name
    if dest.is_symlink() or is_disallowed_reparse(dest) or is_hardlink(dest):
        return [
            f".agents/skills/{name} is a symlink, junction or hardlink; treat it as unattributable "
            "content on a PH-reserved name, keep it in place, and ask the user"
        ]
    if not dest.exists():
        try:
            target = _sdd_dir_files(_sdd_release_skill_dir(name))
            for rel in sorted(target):
                _sdd_ensure_safe_write_dest(repo, f".agents/skills/{name}/{rel}")
        except PHError as exc:
            return [str(exc)]
        return []
    if not dest.is_dir():
        return [
            f".agents/skills/{name} exists and is not a real directory; treat it as unattributable "
            "content on a PH-reserved name, keep it in place, and ask the user"
        ]
    try:
        current = _sdd_dir_files(dest)
        target = _sdd_dir_files(_sdd_release_skill_dir(name))
    except PHError as exc:
        return [f".agents/skills/{name} cannot be inspected: {exc}"]
    if current.get("SKILL.md") != target.get("SKILL.md"):
        return [
            f".agents/skills/{name}: SKILL.md is missing or is not the release generation and no baseline "
            "proves this directory managed; treat it as unknown same-name content on a PH-reserved name, "
            "keep it in place, and ask the user"
        ]
    differing = sorted(
        rel for rel, data in target.items() if rel != "SKILL.md" and rel in current and current[rel] != data
    )
    if differing:
        return [
            f".agents/skills/{name}: existing {', '.join(differing)} differ from the release generation "
            "and no baseline proves them managed; keep them in place and ask the user before overwriting"
        ]
    return []


def _sdd_dest_complete_current(dest: Path, name: str) -> bool:
    """True when every release-set file of skill ``name`` is present in
    ``dest`` with the release bytes (extras are allowed and stay)."""

    target = _sdd_dir_files(_sdd_release_skill_dir(name))
    current = _sdd_dir_files(dest)
    return all(rel in current and current[rel] == data for rel, data in target.items())


def migrate_skills_payload(repo: Path, apply: bool, decisions_path: str | None = None) -> dict:
    """Plan (or apply) the 1.2.3 skill replacement for one repository.

    Read-only without --apply. An apply runs a complete read-only pre-check
    first: identity classification of every managed name, mirror retirement
    evidence, extra-file decisions, archive-destination collisions and
    install-target conflicts are ALL collected before the first write, so a
    blocked run - plan or apply - writes nothing at all. Only a conflict-free
    plan is executed, every step is idempotent, and an interrupted run can be
    retried as-is (fresh installs stage and rename atomically). The seven
    truly-new required names (no earlier release shipped them) missing on
    disk are installed from the release scaffold; the seven 1.2.2 retained
    basic skills (RETAINED_122_SKILLS) are installed only when missing - a
    live copy with old-generation text belongs to its own migration item and
    is neither touched nor blocked here.

    A managed-old directory that carries files beyond the known managed set
    (SKILL.md, evals/evals.json) is never archived on the baseline proof
    alone: the migration cannot judge whether those attachments are still
    effective customizations. It blocks until the caller passes
    --extras-decisions with a reviewed per-directory decision, which is then
    recorded next to the archived tree.

    A live directory on a required new name (never shipped by any earlier
    release) is healable only when its SKILL.md is the release generation:
    missing release-set files are added, extras stay in place, and a present
    file that differs from the release is never overwritten. Anything else -
    an unknown half-install, differing bytes, a foreign mirror without a
    canonical tree - is unknown same-name content that stays in place and
    blocks.
    """

    to_version, skills = release_contract()
    if semver_tuple(to_version) < (1, 2, 3):
        raise PHError("migrate-skills requires the 1.2.3 skill contract")
    data = read_disk_manifest(repo)
    ensure_canonical_root(repo)
    baselines = _sdd_baselines(data)
    if not baselines and (semver_tuple(manifest_version(data)) < semver_tuple(to_version)):
        # A pre-1.2.3 project without any baselines cannot prove ownership of
        # a single managed file: every live same-name directory would be
        # unattributable. Fail closed before touching anything.
        live_managed = [
            n for n in (*SDD_RETIRED_SKILLS, *SDD_REPLACED_SKILLS)
            if _sdd_classify(repo, n, baselines) == "blocked"
        ]
        if live_managed:
            return {
                "action": "migrate-skills", "apply": False, "blocked": True,
                "conflicts": [
                    f".agents/ph.json records no speckit.files content baselines, so the managed "
                    f"copies {', '.join(live_managed)} cannot be proven unmodified; resolve with the user "
                    "before replacing them"
                ],
                "items": [],
            }
    results: list[dict] = []
    conflicts: list[str] = []

    def mirror_proof(name: str, verdict: str) -> dict | None:
        """The managed-generation proof a live mirror must satisfy, per file.

        The historical install recorded baselines for a subset of the managed
        files (SKILL.md only in the 1.1.14-1.2.2 releases), so a mirror file
        counts as managed when its sha256 equals the recorded baseline, or —
        for files the manifest never pinned — when it is byte-identical to
        the canonical managed tree being retired. Mirror files outside the
        canonical managed set are user content."""
        if verdict == "managed-old":
            canonical = _sdd_dir_files(repo / ".agents" / "skills" / name)
        elif verdict == "current":
            canonical = _sdd_dir_files(_sdd_release_skill_dir(name))
        else:
            return None
        prefix = f"{SDD_SKILL_BASELINE_PREFIX}{name}/"
        pinned = {key[len(prefix):]: sha for key, sha in baselines.items() if key.startswith(prefix)}
        return {"canonical": canonical, "pinned": pinned}

    # Phase 1 - read-only detection of every managed disposition: identity,
    # mirrors, extras decisions, archive destinations and install targets.
    # Every conflict is collected here, so a blocked run - plan or apply -
    # writes nothing at all; only a conflict-free plan is ever executed.
    verdicts: dict[str, str] = {}
    for name in (*SDD_RETIRED_SKILLS, *SDD_REPLACED_SKILLS):
        verdict = _sdd_classify(repo, name, baselines)
        verdicts[name] = verdict
        if verdict == "blocked":
            conflicts.append(
                f".agents/skills/{name}: the bytes match neither the release generation nor the recorded "
                "install baseline; treat it as user or third-party content, keep it in place, and ask "
                "the user before any replacement"
            )

    # Mirror retirement is planned only for names whose canonical tree this
    # migration will retire (managed-old): a current-generation canonical is
    # never retired, so its live mirror keeps its adapter role (finalize's
    # portable/symlink sync re-creates .claude/skills for every required
    # skill at the target state) or is user content on the adapter path, and
    # an absent canonical leaves a mirror without proof, which stays a
    # review conflict.
    mirror_plans: list[tuple[str, str, dict]] = []
    for name in (*SDD_RETIRED_SKILLS, *SDD_REPLACED_SKILLS):
        verdict = verdicts[name]
        if verdict == "managed-old":
            proof = mirror_proof(name, verdict)
            for mirror_root in SDD_MIRROR_ROOTS:
                mirror = repo / mirror_root / "skills" / name
                if mirror.exists() or mirror.is_symlink():
                    try:
                        outcome = _sdd_retire_mirror(repo, name, mirror_root, proof, False)
                    except PHError as exc:
                        conflicts.append(str(exc))
                        continue
                    if outcome is not None:
                        mirror_plans.append((name, mirror_root, outcome))
        elif verdict == "absent":
            for mirror_root in SDD_MIRROR_ROOTS:
                mirror = repo / mirror_root / "skills" / name
                if mirror.exists() or mirror.is_symlink():
                    conflicts.append(
                        f"{mirror_root}/skills/{name} cannot be proven a managed mirror (the canonical "
                        "tree is already retired); preserve it for review"
                    )

    # Extra-file attribution needs a reviewed decision before any write, so
    # it is part of the same pre-check as everything else.
    names_with_extras: dict[str, list[str]] = {}
    for name, verdict in verdicts.items():
        if verdict != "managed-old":
            continue
        try:
            extras = _sdd_extra_files(repo, name)
        except PHError as exc:
            conflicts.append(str(exc))
            continue
        if extras:
            names_with_extras[name] = extras
    try:
        decisions = _sdd_load_extras_decisions(decisions_path, names_with_extras)
    except PHError as exc:
        conflicts.append(str(exc))
        decisions = {}

    # Install destinations: a live directory on a truly-new required name is
    # healable only from a proven-current SKILL.md; unknown same-name content
    # blocks. The retained 1.2.2 basic skills are pre-checked only when they
    # are missing from the managed install (then the original-rule install
    # applies); a live copy with old-generation text belongs to its own
    # migration item and is neither touched nor blocked here.
    for name in SDD_REPLACED_SKILLS:
        if verdicts[name] in {"current", "absent"}:
            conflicts.extend(_sdd_install_conflicts(repo, name))
    new_names = sorted(set(skills) - set(SPECKIT_MANAGED_SKILLS) - {"ph-init"} - set(RETAINED_122_SKILLS))
    retained_names = sorted(set(skills) & set(RETAINED_122_SKILLS))
    for name in new_names:
        conflicts.extend(_sdd_install_conflicts(repo, name))
        dest = repo / ".agents" / "skills" / name
        if not (dest.exists() or dest.is_symlink()):
            mirror = repo / ".claude" / "skills" / name
            if mirror.exists() or mirror.is_symlink():
                conflicts.append(
                    f".claude/skills/{name} exists without the canonical skill; no PH release ships this "
                    "name, so treat it as unattributable content on a PH-reserved name, keep it in place, "
                    "and ask the user"
                )
    retained_absent: list[str] = []
    for name in retained_names:
        dest = repo / ".agents" / "skills" / name
        if not (dest.exists() or dest.is_symlink()):
            retained_absent.append(name)
            conflicts.extend(_sdd_install_conflicts(repo, name))

    # The write paths create the staging base and the archive directories;
    # their whole ancestor chains and the existing extras records are
    # pre-checked with pure reads, so nothing is discovered - or written
    # through a link - after other steps already moved.
    if new_names or retained_absent or any(v == "managed-old" for v in verdicts.values()):
        conflicts.extend(_sdd_staging_chain_conflicts(repo))
    archive_base = _sdd_archive_base(repo)
    retire_names = [n for n, v in verdicts.items() if v == "managed-old"]
    if retire_names:
        conflicts.extend(_sdd_dest_chain_conflicts(repo, archive_base, "retired-skill archive destination"))
        for name in retire_names:
            dest = archive_base / name
            if dest.exists() or dest.is_symlink():
                conflicts.append(
                    f"retired-skill archive collision: {posix_rel(dest.relative_to(repo))} already exists while "
                    f".agents/skills/{name} is still live; keep both and decide manually"
                )
        for name, extras in names_with_extras.items():
            if not extras:
                continue
            record = archive_base / f"{name}.extras.json"
            if record.is_symlink() or is_hardlink(record) or (record.exists() and not record.is_file()):
                conflicts.append(
                    f"retired-skill extras record is not a regular file: {posix_rel(record.relative_to(repo))}"
                )
                continue
            if record.exists() and name in decisions:
                if record.read_bytes() != _sdd_extras_record_bytes(name, extras, decisions[name]):
                    conflicts.append(
                        f"retired-skill extras record changed: {posix_rel(record.relative_to(repo))}; "
                        "keep both and decide manually"
                    )
    if conflicts:
        return {"action": "migrate-skills", "apply": False, "blocked": True, "conflicts": conflicts, "items": results}

    # Phase 2 - report the approved plan (plan mode) or execute it (apply).
    if not apply:
        for name, mirror_root, outcome in mirror_plans:
            results.append({"target": f"{mirror_root}/skills/{name}", "action": "retire-mirror", **outcome})
        for name in SDD_RETIRED_SKILLS:
            verdict = verdicts[name]
            if verdict == "absent":
                results.append({"target": f".agents/skills/{name}", "action": "already-retired"})
                continue
            dest = _sdd_archive_base(repo) / name
            results.append({"target": f".agents/skills/{name}", "action": "retire", "dest": posix_rel(dest.relative_to(repo))})
        for name in SDD_REPLACED_SKILLS:
            if verdicts[name] == "current":
                results.append({"target": f".agents/skills/{name}", "action": "already-current"})
            else:
                results.append({"target": f".agents/skills/{name}", "action": "replace", "mode": verdicts[name]})
        for name in new_names:
            dest = repo / ".agents" / "skills" / name
            if (dest.exists() or dest.is_symlink()) and _sdd_dest_complete_current(dest, name):
                results.append({"target": f".agents/skills/{name}", "action": "already-current"})
            else:
                results.append({"target": f".agents/skills/{name}", "action": "install"})
        for name in retained_names:
            dest = repo / ".agents" / "skills" / name
            if not (dest.exists() or dest.is_symlink()):
                results.append({"target": f".agents/skills/{name}", "action": "install"})
        return {"action": "migrate-skills", "apply": False, "blocked": False, "conflicts": [], "items": results}

    for name, mirror_root, _outcome in mirror_plans:
        proof = mirror_proof(name, "managed-old")
        outcome = _sdd_retire_mirror(repo, name, mirror_root, proof, True)
        if outcome is not None:
            results.append({"target": f"{mirror_root}/skills/{name}", "action": "mirror-retired", **outcome})
    for name in SDD_RETIRED_SKILLS:
        if verdicts[name] == "absent":
            results.append({"target": f".agents/skills/{name}", "action": "already-retired"})
            continue
        dest = _sdd_archive_base(repo) / name
        extras = names_with_extras.get(name, [])
        if extras:
            _sdd_record_extras(repo, name, extras, decisions[name], dest)
        outcome = _sdd_retire_tree(repo, repo / ".agents" / "skills" / name, dest, f".agents/skills/{name}")
        results.append({
            "target": f".agents/skills/{name}", "action": "retired",
            "extras": extras, "extras_disposition": decisions[name] if extras else None, **outcome,
        })
    for name in SDD_REPLACED_SKILLS:
        if verdicts[name] == "current":
            results.append({"target": f".agents/skills/{name}", "action": "installed", **_sdd_install_release_skill(repo, name)})
            continue
        if verdicts[name] == "managed-old":
            dest = _sdd_archive_base(repo) / name
            extras = names_with_extras.get(name, [])
            if extras:
                _sdd_record_extras(repo, name, extras, decisions[name], dest)
            outcome = _sdd_retire_tree(repo, repo / ".agents" / "skills" / name, dest, f".agents/skills/{name}")
            results.append({
                "target": f".agents/skills/{name}", "action": "replaced",
                "extras": extras, "extras_disposition": decisions[name] if extras else None, **outcome,
            })
        results.append({"target": f".agents/skills/{name}", "action": "installed", **_sdd_install_release_skill(repo, name)})
    for name in new_names:
        dest = repo / ".agents" / "skills" / name
        if (dest.exists() or dest.is_symlink()) and _sdd_dest_complete_current(dest, name):
            results.append({"target": f".agents/skills/{name}", "action": "already-current"})
            continue
        results.append({"target": f".agents/skills/{name}", "action": "installed", **_sdd_install_release_skill(repo, name)})
    for name in retained_names:
        dest = repo / ".agents" / "skills" / name
        if not (dest.exists() or dest.is_symlink()):
            results.append({"target": f".agents/skills/{name}", "action": "installed", **_sdd_install_release_skill(repo, name)})
    return {"action": "migrate-skills", "apply": True, "blocked": False, "conflicts": [], "items": results}


# ---------------------------------------------------------------------------
# 1.1.14 intent-to-spec: verbatim extraction from the legacy intent tree into
# the spec-kit specs/ root. The originals stay byte-identical read-only
# history; the mapping ledger and the human history index persist in the repo
# across versions. Nothing is fabricated: only the four legacy template
# sections (目标/范围/约束/验收) are carried over verbatim, missing ones become
# NEEDS CLARIFICATION, and no plan/tasks files, priorities or success metrics
# are invented. 已废弃/访谈纪要 entries are registered as history only.
# ---------------------------------------------------------------------------

INTENT_HISTORY_SCHEMA = "ph.intent-ledger/1"
INTENT_SPEC_ROOT = ".agents/project-harness/specs"
# 1.2.1 archives the retired intent tree under the unified archive while
# legacy-backup keeps the pre-upgrade relative path, so an entry source like
# docs/意图/... resolves one-to-one under this root.
INTENT_ARCHIVE_ROOT = ".agents/project-harness/archive/legacy-backup"
INTENT_LEDGER_REL = ".agents/project-harness/specs/.ph-intent-ledger.json"
INTENT_HISTORY_REL = "docs/意图/历史索引.md"
# Spec-eligible roots: the two canonical ones plus the two early-layout roots
# (进行中/已完成), so a tree that still carries a pre-1.1.2 directory is
# migrated instead of silently skipped. 已废弃 and 访谈纪要 are history-only.
INTENT_SPEC_ELIGIBLE_ROOTS = ("docs/意图/待办", "docs/意图/实施", "docs/意图/进行中", "docs/意图/已完成")
INTENT_HISTORY_ONLY_ROOTS = ("docs/意图/已废弃", "docs/意图/访谈纪要")
# The four spec-structured sections. The second tuple lists every heading the
# legacy templates ever used for that section (the 1.0.0 template c805d8f had
# 背景/目标/非目标/记录; 非目标 is a 范围与非目标 alias), so an old entry is
# never mislabeled NEEDS CLARIFICATION when its information exists under a
# historical alias.
INTENT_SPEC_SECTIONS = (
    ("目标", ("目标",)),
    ("范围与非目标", ("范围与非目标", "非目标")),
    ("关键约束", ("关键约束",)),
    ("验收标准", ("验收标准",)),
)
INTENT_CANONICAL_HEADINGS = frozenset(h for _, names in INTENT_SPEC_SECTIONS for h in names)
INTENT_CLARIFY_HEADING = "待澄清问题"
# Status is recorded, never uniformed: a completed legacy entry must not be
# reopened as a Draft and an in-progress entry must not read as done.
_INTENT_UNSAFE_ID = re.compile(r"[^0-9A-Za-z._-]+")
_INTENT_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n?", re.DOTALL)


def _intent_spec_status(status_dir: str) -> tuple[str, str]:
    """Map the migration-time status_dir to a spec Status plus an explicit
    note. The note is part of the deterministic spec body."""
    root = status_dir.split("/", 1)[0] if status_dir else ""
    if root == "待办":
        return "Draft", "迁移时状态为待办；本次迁移不生成 plan / tasks，开始实施仍须按流程澄清与规划。"
    if root in ("实施", "进行中"):
        return (
            "In Progress",
            "迁移时状态为实施（或早期进行中），照录历史状态；实施不等于完成，"
            "本次迁移不重新验收或判通过，既有记录逐字保留在原文「记录」节。",
        )
    if root == "已完成":
        return (
            "Complete",
            "迁移时状态目录为已完成，历史完成记录照录；本次迁移不自动重新验收或判通过，"
            "验收结论以原文「记录」节为准。",
        )
    if root == "已废弃":
        return (
            "Rejected",
            "迁移时状态目录为已废弃；已废弃条目仅登记历史，不重开。",
        )
    return (
        "Unknown",
        f"迁移时状态目录（{status_dir or '未记录'}）无法识别；不推定任何实施或完成状态。",
    )


def _parse_intent_document(text: str) -> dict:
    """Split a legacy intent/interview markdown file into frontmatter, first
    title and verbatim ``## `` section bodies. No content is rewritten.

    Faithful to the source: a fenced code block (``` or ~~~) never opens a
    section or the title, and repeated headings keep every occurrence in
    document order (``sections`` maps a heading to the list of its bodies)
    instead of a mapping overwrite losing the first body and duplicating
    the last one.
    """
    meta: dict[str, str] = {}
    body = text
    match = _INTENT_FRONTMATTER.match(text)
    if match:
        for line in match.group(1).splitlines():
            pair = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$", line)
            if pair:
                meta[pair.group(1)] = pair.group(2).strip().strip('"').strip("'")
        body = text[match.end():]
    title = ""
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: str | None = None
    buffer: list[str] = []
    fence: tuple[str, int] | None = None  # (marker char, opener length)
    for line in body.splitlines():
        if fence is not None:
            buffer.append(line)
            close = re.match(r"^ {0,3}([" + re.escape(fence[0]) + r"]{3,})[ \t]*$", line)
            if close and len(close.group(1)) >= fence[1]:
                fence = None
            continue
        opened = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if opened is not None:
            marker, info = opened.group(1), opened.group(2)
            # CommonMark: a backtick opener's info string may not contain
            # backticks; a tilde opener has no such restriction. Anything
            # failing that is ordinary text, not a fence.
            if not (marker[0] == "`" and "`" in info):
                fence = (marker[0], len(marker))
                buffer.append(line)
                continue
        if current is None and not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            if current is not None:
                sections.setdefault(current, []).append("\n".join(buffer).strip("\n"))
            else:
                preamble = list(buffer)
            current, buffer = line[3:].strip(), []
            order.append(current)
        elif current is not None:
            buffer.append(line)
        else:
            buffer.append(line)
    if current is not None:
        sections.setdefault(current, []).append("\n".join(buffer).strip("\n"))
    elif buffer:
        preamble = list(buffer)
    return {"meta": meta, "title": title, "sections": sections, "order": order, "preamble": "\n".join(preamble).strip("\n")}


def _intent_spec_dir(intent_id: str) -> str:
    slug = _INTENT_UNSAFE_ID.sub("-", intent_id).strip("-.") or "unnamed"
    return f"intent-{slug}"


def _render_intent_spec(source: str, sha: str, parsed: dict, spec_dir: str) -> str:
    """Deterministic spec body: a pure function of the source bytes, so an
    interrupted run can recognize its own partial output byte-for-byte.

    Nothing is lost or fabricated: the four spec-structured sections are
    filled from every legacy heading alias (1.0.0 used 非目标), every other
    original section (背景/记录/访谈依据/计划交接/待澄清问题/...) is carried
    verbatim with its original heading, and the pre-section preamble is kept.
    """
    meta = parsed["meta"]
    intent_id = meta.get("intent_id", "")
    title = parsed["title"] or intent_id or "未命名迁移意图"
    created = meta.get("created", "")
    status_dir = meta.get("status_dir", "")
    status, status_note = _intent_spec_status(status_dir)
    lines = [
        f"# Feature Specification: {title}",
        "",
        f"**Feature Branch**: `{spec_dir}`（迁移占位名，不是 Git 分支）",
        "",
        f"**Created**: {created or '未记录'}（原意图 frontmatter created；本文件由 PH intent-to-spec 迁移生成）",
        "",
        f"**Status**: {status}",
        "",
        f"> {status_note}",
        "",
        f"**Input**: 迁移自旧意图 `{source}`（intent_id: `{intent_id or '未记录'}`，源内容 sha256: `{sha}`"
        + (f"，迁移时 status_dir: `{status_dir}`" if status_dir else "") + "）。",
        "",
        "> 本文件由 PH 1.1.14 intent-to-spec 迁移生成：只逐字摘录原意图内容，缺失的规范节标注"
        " NEEDS CLARIFICATION，不编造优先级、技术方案或成功指标，也不生成 plan / tasks 文件。"
        "原意图文件转为只读历史，字节不变；后续只在本 Spec 继续维护（澄清、规划、验收都在这里进行）。"
        "原文全部小节（含背景、记录、访谈依据、计划交接与历史节别名）都在本文件逐字保留，原文仍是必读出处。"
        "迁移不改变实现状态：本 Spec 不代表任何验收通过，不得据本文件自动重新验收或判通过。",
        "",
    ]
    occurrences: list[tuple[str, str]] = []
    positions: dict[str, int] = {}
    for heading in parsed["order"]:
        index = positions.get(heading, 0)
        occurrences.append((heading, parsed["sections"][heading][index]))
        positions[heading] = index + 1
    consumed: set[str] = set()
    for spec_name, aliases in INTENT_SPEC_SECTIONS:
        # Every occurrence of every alias, in document order, verbatim; an
        # empty (or missing) section carries no content and is reported as
        # NEEDS CLARIFICATION instead of rendered as an empty body.
        found = [
            (heading, body.strip())
            for heading, body in occurrences
            if heading in aliases
        ]
        found = [(heading, body) for heading, body in found if body]
        consumed.update(heading for heading, _ in found)
        lines += [f"## {spec_name}（逐字摘录）", ""]
        if found:
            for heading, body in found:
                if len(found) > 1 or heading != spec_name:
                    lines += [f"### 原节「{heading}」", "", body, ""]
                else:
                    lines += [body, ""]
        else:
            lines += [
                f"NEEDS CLARIFICATION: 原意图没有「{' / '.join(aliases)}」节（或该节为空），"
                "未经用户澄清不得开始实现。",
                "",
            ]
    clarify_bodies = [
        body.strip()
        for heading, body in occurrences
        if heading == INTENT_CLARIFY_HEADING
    ]
    clarify_bodies = [body for body in clarify_bodies if body]
    if clarify_bodies:
        consumed.add(INTENT_CLARIFY_HEADING)
        lines += [f"## {INTENT_CLARIFY_HEADING}（逐字摘录）", ""]
        lines += ["\n\n".join(clarify_bodies), ""]
    else:
        lines += [f"## {INTENT_CLARIFY_HEADING}（逐字摘录）", ""]
        lines += ["原意图未记录待澄清问题；以上 NEEDS CLARIFICATION 项即为当前缺口。", ""]
    others = [(h, body) for h, body in occurrences if h not in consumed and h not in INTENT_CANONICAL_HEADINGS]
    if others:
        lines += ["## 原文其余小节（逐字摘录，必读出处）", ""]
        for heading, body in others:
            lines += [f"### {heading}", "", body.strip(), ""]
    if parsed["preamble"]:
        lines += ["## 原文引言（逐字摘录）", "", parsed["preamble"], ""]
    lines += [
        "## 原文与必读引用",
        "",
        f"- 原意图 `{source}` 是只读历史与必读出处：其「记录」节包含全部时间线、交付与验收结论，"
        "本迁移不重新验收、不改写、不覆盖这些结论。",
        f"- 映射与哈希以 `{INTENT_LEDGER_REL}` 为准；迁移规则与选择方式见 `{INTENT_HISTORY_REL}`。",
        "",
        "## 后续流程",
        "",
        "- 按 `ph-clarify` / `ph-plan` 继续澄清与规划；本迁移不生成 plan / tasks，也不代表验收通过。",
        f"- 选择本 Spec 为当前 feature：见 `{INTENT_HISTORY_REL}` 的调用说明（select-intent-spec 或"
        " SPECIFY_FEATURE_DIRECTORY）；迁移与验证从不改写已有活动 feature 指针。",
        "",
    ]
    return "\n".join(lines)


def _render_intent_history_index(rows: list[dict], ledger_rel: str) -> str:
    """Deterministic human-facing history index plus the single-maintenance-
    location rule declaration; a pure function of the scanned entries."""
    specs = [r for r in rows if r["spec"]]
    history = [r for r in rows if not r["spec"]]
    lines = [
        "# 旧意图迁移历史索引",
        "",
        "自 1.1.14 `intent-to-spec` 迁移起，业务意图只在 `specs/` 下对应的 Spec 中继续维护；"
        "`docs/意图/` 与各条目原文件转为只读历史，字节不再变动。已废弃条目仅在此登记历史，不重开；"
        "访谈纪要仅登记历史。",
        "",
        "## 规则（唯一后续维护位置）",
        "",
        "- 后续只维护 Spec：澄清、规划、验收都在对应 `specs/<feature>/spec.md` 进行。",
        f"- 把某个已迁移 Spec 选为当前 feature：运行"
        f" `python3 .agents/skills/ph-init/scripts/ph_merge_update.py select-intent-spec"
        f" --repo <仓库根> --intent <intent_id>`（默认 dry-run，加 `--apply` 生效；仅当"
        " `runtime/feature.json`（即 `.agents/project-harness/runtime/feature.json`）缺失或未指向其他 feature 时写入），或在 shell 中"
        " `export SPECIFY_FEATURE_DIRECTORY=.agents/project-harness/specs/<feature>`。迁移与验证从不改写已有活动 feature 指针。",
        f"- 原文件与本索引为只读历史；映射与哈希以 `{ledger_rel}` 为准。",
        "",
        "## 已迁移为 Spec（待办 / 实施 / 早期进行中 / 已完成）",
        "",
        "| intent_id | 原文件（只读历史） | Spec |",
        "| --- | --- | --- |",
    ]
    for row in specs:
        lines.append(f"| {row['intent_id']} | {row['source']} | {row['spec']} |")
    if not specs:
        lines.append("| （无） | （无） | （无） |")
    lines += [
        "",
        "## 仅登记历史（已废弃 / 访谈纪要）",
        "",
        "| intent_id | 原文件（只读历史） | 迁移时 status_dir |",
        "| --- | --- | --- |",
    ]
    for row in history:
        lines.append(f"| {row['intent_id']} | {row['source']} | {row['status_dir']} |")
    if not history:
        lines.append("| （无） | （无） | （无） |")
    lines.append("")
    return "\n".join(lines)


def _intent_scan_entries(repo: Path) -> list[dict]:
    """Collect every legacy entry file below the managed roots (skipping the
    README indexes and _模板 templates). Directories outside the known roots
    are project content and are never touched.

    The walk is fail-closed: a plain rglob silently skips symlinked
    subdirectories, so entries hidden behind a link would vanish from the
    migration instead of being reported; any symlink below the managed roots
    (including a linked root itself) is refused, as is any non-regular entry.
    """
    docs = repo / "docs" / "意图"
    if not docs.is_dir():
        return []
    if docs.is_symlink():
        raise PHError("refusing to migrate through a symlinked intent root: docs/意图")
    entries: list[dict] = []
    for root in INTENT_SPEC_ELIGIBLE_ROOTS + INTENT_HISTORY_ONLY_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        if base.is_symlink():
            raise PHError(f"refusing to migrate a symlinked intent root: {root}")

        def walk(dir_path: Path, batch: list[dict]) -> None:
            for path in sorted(dir_path.iterdir()):
                if path.is_symlink():
                    raise PHError(
                        f"refusing to migrate a symlinked intent path: {posix_rel(path.relative_to(repo))}"
                    )
                if path.is_dir():
                    walk(path, batch)
                elif path.is_file():
                    if path.name == "README.md" or path.name.startswith("_"):
                        continue
                    if not path.name.endswith(".md"):
                        continue
                    batch.append({"source": posix_rel(path.relative_to(repo)), "root": root})
                else:
                    raise PHError(
                        f"refusing to migrate a non-regular intent entry: {posix_rel(path.relative_to(repo))}"
                    )

        batch: list[dict] = []
        walk(base, batch)
        batch.sort(key=lambda item: item["source"])
        entries.extend(batch)
    return entries


def _write_repo_bytes(repo: Path, rel: str, data: bytes) -> None:
    path = repo / rel
    issue = ancestor_issue(repo, path)
    if issue:
        raise PHError(issue)
    if path.is_symlink() or is_disallowed_reparse(path):
        raise PHError(f"refusing to write through symlink or junction: {rel}")
    if path.exists() and is_hardlink(path):
        raise PHError(f"refusing to write through hardlink: {rel}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
        os.replace(tmp, path)
    except Exception:
        if fd >= 0:
            os.close(fd)
        if tmp.exists() or tmp.is_symlink():
            move_to_trash(tmp)
        raise


def _create_repo_file_exclusive(repo: Path, rel: str, data: bytes) -> None:
    """Atomically create a repo file that must not already exist.

    ``os.link`` fails with FileExistsError when any file (including one that
    differs only in case on a case-insensitive filesystem) already occupies the
    name, so two planned specs can never silently overwrite each other the way
    an ``os.replace`` write would.
    """
    dest = repo / rel
    issue = ancestor_issue(repo, dest)
    if issue:
        raise PHError(issue)
    if dest.exists() or dest.is_symlink():
        raise PHError(f"refusing to overwrite an existing file: {rel}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        try:
            os.link(tmp, dest)
        except FileExistsError as exc:
            raise PHError(f"refusing to overwrite an existing file: {rel}") from exc
        except OSError:
            # Filesystems without hardlink support fall back to the replace
            # write after re-checking the target.
            if dest.exists() or dest.is_symlink():
                raise PHError(f"refusing to overwrite an existing file: {rel}")
            os.replace(tmp, dest)
            return
    finally:
        # Unlink, never trash-rename: the tmp file shares the inode with the
        # freshly linked dest, and keeping any name for it would leave the
        # destination looking like a hardlink (nlink > 1) to every later
        # managed-write check.
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def plan_intent_to_spec(repo: Path) -> dict:
    """Compute the full intent-to-spec plan without writing anything.

    The plan is the apply contract: `generated` entries are new, `restored`
    entries were interrupted mid-write (their spec bytes equal the deterministic
    render), `skipped` entries are already migrated, `source_updated` /
    `spec_user_modified` entries are never overwritten, and `conflicts`
    (a target spec path occupied by a foreign file, duplicate source ids,
    a frontmatter status_dir disagreeing with the physical directory, or a
    non-directory in the way of the specs artifacts) block the apply
    entirely.
    """
    raw_entries = _intent_scan_entries(repo)
    scanned: list[dict] = []
    for raw in raw_entries:
        path = repo / raw["source"]
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise PHError(f"unreadable intent entry {raw['source']}: {exc}") from exc
        parsed = _parse_intent_document(text)
        scanned.append({
            **raw,
            "sha256": sha256_file(path),
            "parsed": parsed,
            "intent_id": parsed["meta"].get("intent_id") or path.stem,
        })
    ledger_path = repo / INTENT_LEDGER_REL
    ledger = read_json(ledger_path) if ledger_path.is_file() else None
    if ledger is not None and ledger.get("schema") != INTENT_HISTORY_SCHEMA:
        raise PHError(f"{INTENT_LEDGER_REL} has an unknown schema: {ledger.get('schema')!r}")
    known = {}
    for item in (ledger or {}).get("entries") or []:
        if isinstance(item, dict) and isinstance(item.get("source"), str):
            known[item["source"]] = item
    conflicts: list[str] = []
    # Status provenance: the physical location and the frontmatter
    # status_dir must agree whenever both name a recognized status root - a
    # file sitting in 已完成 while its frontmatter still says 待办 must not
    # be silently reopened as a Draft. A missing or unrecognized value keeps
    # the historical-compatibility behavior (recorded as-is, no conflict).
    recognized_status_roots = {"待办", "实施", "进行中", "已完成", "已废弃"}
    for entry in scanned:
        parts = entry["source"].split("/")
        physical = parts[2] if len(parts) > 3 else ""
        status_dir = entry["parsed"]["meta"].get("status_dir", "")
        front = status_dir.split("/", 1)[0] if status_dir else ""
        if physical in recognized_status_roots and front in recognized_status_roots and physical != front:
            conflicts.append(
                f"`{entry['source']}` frontmatter status_dir `{status_dir}` disagrees with its "
                f"physical directory `{physical}/`; the migration records the historical state "
                "verbatim and refuses to guess (fix the frontmatter or move the file, then re-run)"
            )

    # Target directory assignment. An entry already recorded in the ledger
    # keeps its persisted spec path - the mapping is historical fact and is
    # never recomputed, so nothing already on disk moves. New entries
    # derive the directory from the intent id; when two DIFFERENT ids
    # collapse onto the same slug (every non-ASCII id collapses to the
    # shared `unnamed` slug), each colliding entry gets a deterministic
    # disambiguator instead of a misleading duplicate-source-id conflict.
    eligible = [e for e in scanned if e["root"] in INTENT_SPEC_ELIGIBLE_ROOTS]
    assigned: dict[str, str] = {}
    owner_of: dict[str, tuple[str, str]] = {}
    for entry in eligible:
        prior = known.get(entry["source"])
        prior_spec = prior.get("spec") if isinstance(prior, dict) else None
        if (
            isinstance(prior_spec, str)
            and is_safe_rel(prior_spec)
            and prior_spec.startswith(f"{INTENT_SPEC_ROOT}/")
            and prior_spec.endswith("/spec.md")
        ):
            spec_dir = posix_rel(prior_spec)[len(f"{INTENT_SPEC_ROOT}/"): -len("/spec.md")]
            assigned[entry["source"]] = spec_dir
            owner_of.setdefault(spec_dir, (entry["intent_id"], entry["source"]))
    for entry in sorted(
        (e for e in eligible if e["source"] not in assigned),
        key=lambda item: item["source"],
    ):
        spec_dir = _intent_spec_dir(entry["intent_id"])
        owner = owner_of.get(spec_dir)
        if owner is not None and owner[0] != entry["intent_id"]:
            suffix = hashlib.sha256(entry["intent_id"].encode("utf-8")).hexdigest()[:8]
            spec_dir = f"{spec_dir}-{suffix}"
        assigned[entry["source"]] = spec_dir
        owner_of.setdefault(spec_dir, (entry["intent_id"], entry["source"]))
    by_dir: dict[str, str] = {}
    by_casefold: dict[str, str] = {}
    for entry in eligible:
        spec_dir = assigned[entry["source"]]
        owner = by_dir.setdefault(spec_dir, entry["source"])
        if owner != entry["source"]:
            conflicts.append(
                f"duplicate source id `{entry['intent_id']}`: {entry['source']} collides with {owner} on {INTENT_SPEC_ROOT}/{spec_dir}"
            )
            continue
        # Case-insensitive filesystems (macOS default) resolve specs/intent-A
        # and specs/intent-a to the same directory, so a case-only collision
        # must block at plan time - not silently overwrite the first spec.
        folded = spec_dir.casefold()
        case_owner = by_casefold.setdefault(folded, spec_dir)
        if case_owner != spec_dir:
            conflicts.append(
                f"spec directory names differ only by case (`{spec_dir}` for {entry['source']} "
                f"collides with `{case_owner}`); a case-insensitive filesystem would overwrite one of them"
            )
    # The specs root and each planned feature directory must be real
    # directories: a regular file (or link) in the way used to crash the
    # apply with a bare NotADirectoryError instead of a reported conflict.
    # 1.2.1: the legacy root-level specs/ tree must not shadow the migrated
    # home root. Its relocation is owned by ph-home-restructure, but a
    # directory (or link) sitting at the old root is recorded here as a
    # relocation input so verify can prove nothing was silently dropped.
    legacy_specs = repo / "specs"
    if legacy_specs.is_symlink() or (legacy_specs.exists() and not legacy_specs.is_dir()):
        conflicts.append(
            '`specs` at the repository root is a symlink or non-directory; move it aside and re-run migrate-intents'
        )
    specs_root = repo / INTENT_SPEC_ROOT
    if specs_root.is_symlink() or (specs_root.exists() and not specs_root.is_dir()):
        conflicts.append(
            f"`{INTENT_SPEC_ROOT}` must be a real directory to hold the migration artifacts "
            "(found a symlink or non-directory in the way); move it aside and re-run migrate-intents"
        )
    plan_rows: list[dict] = []
    for entry in scanned:
        row = {
            "source": entry["source"],
            "source_sha256": entry["sha256"],
            "intent_id": entry["intent_id"],
            "status_dir": entry["parsed"]["meta"].get("status_dir", ""),
        }
        if entry["root"] not in INTENT_SPEC_ELIGIBLE_ROOTS:
            plan_rows.append({**row, "spec": None, "action": "history_only"})
            continue
        spec_dir = assigned[entry["source"]]
        spec_rel = f"{INTENT_SPEC_ROOT}/{spec_dir}/spec.md"
        parent_rel = spec_rel.rsplit("/", 1)[0]
        parent = repo / parent_rel
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            conflicts.append(
                f"`{parent_rel}` is not a real directory for the planned spec `{spec_rel}` "
                "(found a symlink or non-directory in the way); move it aside and re-run migrate-intents"
            )
            plan_rows.append({**row, "spec": spec_rel, "action": "conflict"})
            continue
        expected = _render_intent_spec(entry["source"], entry["sha256"], entry["parsed"], spec_dir).encode("utf-8")
        expected_sha = hashlib.sha256(expected).hexdigest()
        row.update({"spec": spec_rel, "spec_sha256": expected_sha, "spec_dir": spec_dir})
        prior = known.get(entry["source"])
        target = repo / spec_rel
        if prior is None:
            if target.exists() or target.is_symlink():
                if target.is_file() and not target.is_symlink() and target.read_bytes() == expected:
                    row["action"] = "restored"  # interrupted before the ledger was written
                else:
                    conflicts.append(
                        f"{spec_rel} already exists and is not a migration artifact of {entry['source']} "
                        "(recovery: if it is a spec you edited, move or rename its directory aside, re-run "
                        "migrate-intents to rebuild the baseline spec and the ledger, then re-apply your edits; "
                        "if it is an unrelated same-name file, rename it to keep both)"
                    )
                    plan_rows.append({**row, "action": "conflict"})
                    continue
            else:
                row["action"] = "generated"
        elif prior.get("source_sha256") != entry["sha256"]:
            row["action"] = "source_updated"  # never regenerate over a migrated spec
        else:
            if target.is_file() and not target.is_symlink():
                current_sha = hashlib.sha256(target.read_bytes()).hexdigest()
                if current_sha == prior.get("spec_sha256") or current_sha == expected_sha:
                    row["action"] = "skipped"
                else:
                    row["action"] = "spec_user_modified"  # keep the user's spec
            else:
                row["action"] = "restored"
        plan_rows.append(row)
    history_rows = [
        {"intent_id": r["intent_id"], "source": r["source"], "status_dir": r["status_dir"], "spec": r.get("spec")}
        for r in plan_rows
    ]
    history = _render_intent_history_index(history_rows, INTENT_LEDGER_REL).encode("utf-8")
    history_sha = hashlib.sha256(history).hexdigest()
    index_path = repo / INTENT_HISTORY_REL
    recorded_index_sha = (ledger or {}).get("history_index_sha256")
    disk_index_sha = (
        hashlib.sha256(index_path.read_bytes()).hexdigest() if index_path.is_file() else None
    )
    result = {
        "action": "migrate-intents",
        "apply": False,
        "repo": str(repo),
        "ledger": INTENT_LEDGER_REL,
        "history_index": INTENT_HISTORY_REL,
        "generated": sorted(r["spec"] for r in plan_rows if r.get("action") == "generated"),
        "restored": sorted(r["spec"] for r in plan_rows if r.get("action") == "restored"),
        "skipped": sorted(r["spec"] for r in plan_rows if r.get("action") == "skipped"),
        "source_updated": sorted(r["source"] for r in plan_rows if r.get("action") == "source_updated"),
        "spec_user_modified": sorted(r["source"] for r in plan_rows if r.get("action") == "spec_user_modified"),
        # The user's index is kept without needing the ledger's recorded
        # hash: any existing index that is neither the current render nor
        # the ledger-recorded generation is user content. An index the
        # current scan can regenerate byte-for-byte (an interrupted first
        # run, a lost ledger) is still rewritten - the recovery stays
        # idempotent.
        "history_index_user_modified": bool(
            disk_index_sha is not None
            and disk_index_sha != history_sha
            and (not isinstance(recorded_index_sha, str) or disk_index_sha != recorded_index_sha)
        ),
        "history_only": sorted(r["source"] for r in plan_rows if r.get("action") == "history_only"),
        "conflicts": sorted(set(conflicts)),
        "history_index_sha256": history_sha,
    }
    return {
        "result": result, "rows": plan_rows, "ledger": ledger or {}, "known": known,
        "history": history, "conflicts": sorted(set(conflicts)),
    }


def migrate_intents_payload(repo: Path, apply: bool) -> dict:
    plan = plan_intent_to_spec(repo)
    result = dict(plan["result"])
    if not apply:
        result["apply"] = False
        return result
    if plan["conflicts"]:
        raise PHError("intent-to-spec conflicts; nothing was written: " + "; ".join(plan["conflicts"]))
    # A drifted source is an unreviewed change to a read-only-history original;
    # the apply must surface it as a blocker, not silently skip it.
    if plan["result"]["source_updated"]:
        raise PHError(
            "intent-to-spec: the read-only-history originals drifted after migration; nothing was written: "
            + "; ".join(plan["result"]["source_updated"])
            + " (recovery: restore the original bytes with git, or if the change belongs in the new world, "
            "apply it to the corresponding specs/<feature>/spec.md yourself - the original must stay byte-identical)"
        )
    entries: list[dict] = []
    for row in plan["rows"]:
        if not row.get("spec"):
            entries.append({
                "intent_id": row["intent_id"], "source": row["source"],
                "source_sha256": row["source_sha256"], "status_dir": row["status_dir"],
            })
            continue
        prior = plan["known"].get(row["source"]) or {}
        if row["action"] in {"generated", "restored"}:
            # Only generated/restored rows write: skipped and spec_user_modified
            # rows must never touch the spec on disk. New files are created
            # exclusively so a case-only collision can never overwrite one.
            spec_path = repo / row["spec"]
            expected_bytes = _render_intent_spec(
                row["source"], row["source_sha256"],
                _parse_intent_document((repo / row["source"]).read_text(encoding="utf-8")),
                row["spec_dir"],
            ).encode("utf-8")
            if not spec_path.exists() and not spec_path.is_symlink():
                _create_repo_file_exclusive(repo, row["spec"], expected_bytes)
            elif spec_path.is_file() and spec_path.read_bytes() != expected_bytes:
                raise PHError(
                    f"{row['spec']} changed between plan and apply; re-run migrate-intents"
                )
            recorded_sha = row["spec_sha256"]
        else:
            recorded_sha = prior.get("spec_sha256", row["spec_sha256"])
        entries.append({
            "intent_id": row["intent_id"], "source": row["source"], "source_sha256": row["source_sha256"],
            "spec": row["spec"], "spec_sha256": recorded_sha, "status_dir": row["status_dir"],
        })
    entries.sort(key=lambda item: item["source"])
    ledger = {
        "schema": INTENT_HISTORY_SCHEMA,
        "specs_root": INTENT_SPEC_ROOT,
        "entries": [e for e in entries if e.get("spec")],
        "history_only": [e for e in entries if not e.get("spec")],
        "history_index_sha256": plan["result"]["history_index_sha256"],
    }
    # Only rewrite the generated history index when it is ours. A
    # user-modified index is kept and reported even when the ledger itself
    # was lost: the plan flags it without needing the recorded hash, so the
    # recovery stays idempotent (a regenerated index stays byte-identical,
    # a user index stays preserved on every rerun).
    if not plan["result"]["history_index_user_modified"]:
        _write_repo_bytes(repo, INTENT_HISTORY_REL, plan["history"])
    _write_repo_bytes(
        repo, INTENT_LEDGER_REL,
        (json.dumps(ledger, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    result["apply"] = True
    return result


def verify_intent_spec_layout(repo: Path) -> None:
    """The mandatory intent-to-spec item must have produced its persistent
    artifacts: a schema-current ledger, a live spec per entry, the untouched
    originals, and the history index."""
    ledger_path = repo / INTENT_LEDGER_REL
    if not ledger_path.is_file():
        raise PHError(f"{INTENT_LEDGER_REL} is missing: the mandatory intent-to-spec item has not been applied")
    issue = ancestor_issue(repo, ledger_path)
    if issue:
        raise PHError(f"intent-to-spec artifact escapes the repository: {issue}")
    ledger = read_json(ledger_path)
    if ledger.get("schema") != INTENT_HISTORY_SCHEMA:
        raise PHError(f"{INTENT_LEDGER_REL} schema is not {INTENT_HISTORY_SCHEMA}")
    for key in ("entries", "history_only"):
        if not isinstance(ledger.get(key), list):
            raise PHError(f"{INTENT_LEDGER_REL} {key} must be a list")
    seen_spec_dirs: dict[str, str] = {}
    drifted: list[str] = []
    for entry in ledger["entries"]:
        source, spec = str(entry.get("source", "")), str(entry.get("spec", ""))
        if not is_safe_rel(source) or not is_safe_rel(spec):
            raise PHError(f"{INTENT_LEDGER_REL} carries an unsafe path: {source!r} / {spec!r}")
        original = intent_original_path(repo, source)
        if original is None:
            raise PHError(f"migrated intent original must stay as read-only history: {source}")
        # Containment: a symlinked ancestor (specs/ -> anywhere) must never
        # let the migration artifacts resolve outside the repo.
        for rel in (INTENT_LEDGER_REL, source, spec):
            issue = ancestor_issue(repo, repo / rel)
            if issue:
                raise PHError(f"intent-to-spec artifact escapes the repository: {issue}")
        issue = ancestor_issue(repo, original)
        if issue:
            raise PHError(f"intent-to-spec artifact escapes the repository: {issue}")
        if not (repo / spec).is_file():
            raise PHError(f"ledger spec is missing: {spec}")
        spec_dir = spec.rsplit("/", 1)[0]
        folded = spec_dir.casefold()
        owner = seen_spec_dirs.setdefault(folded, spec_dir)
        if owner != spec_dir:
            raise PHError(
                f"ledger spec directories differ only by case ({owner!r} vs {spec_dir!r}); "
                "on a case-insensitive filesystem they are the same directory"
            )
        if sha256_file(original) != entry.get("source_sha256"):
            # The originals are read-only history: a drifted original is an
            # unreviewed change the migration never carried into the spec, and
            # it must block verify instead of being swallowed.
            drifted.append(f"{source} (recorded {str(entry.get('source_sha256'))[:12]}...)")
    for entry in ledger["history_only"]:
        source = str(entry.get("source", ""))
        original = intent_original_path(repo, source) if is_safe_rel(source) else None
        if original is None:
            raise PHError(f"history-only intent original must stay as read-only history: {source!r}")
        # Same containment proof as migrated entries: a symlinked ancestor
        # must never let a history-only original resolve outside the repo.
        issue = ancestor_issue(repo, original)
        if issue:
            raise PHError(f"intent-to-spec artifact escapes the repository: {issue}")
        if sha256_file(original) != entry.get("source_sha256"):
            drifted.append(f"{source} (recorded {str(entry.get('source_sha256'))[:12]}...)")
    if drifted:
        raise PHError(
            "read-only-history originals drifted after migration; restore their bytes or re-run "
            "migrate-intents to review the drift: " + "; ".join(drifted)
        )
    history = intent_original_path(repo, INTENT_HISTORY_REL)
    if history is None or not history.read_text(encoding="utf-8").strip():
        raise PHError(f"{INTENT_HISTORY_REL} is missing or empty")
    issue = ancestor_issue(repo, history)
    if issue:
        raise PHError(f"intent-to-spec artifact escapes the repository: {issue}")
    # Key claims survive: the index declares the specs/ tree as the single
    # follow-up maintenance location, names the ledger as the mapping
    # authority, and names the select command. Ordinary user notes never
    # break this; a rules section stripped of the claims fails the verify.
    index_text = history.read_text(encoding="utf-8")
    for claim in (INTENT_LEDGER_REL, "select-intent-spec", "唯一后续维护位置"):
        if claim not in index_text:
            raise PHError(
                f"{INTENT_HISTORY_REL} must keep the migration rules: it no longer mentions {claim}"
            )


def intent_original_path(repo: Path, source: str) -> Path | None:
    """Resolve the read-only original of a migrated intent entry.

    1.2.1 archives the retired intent tree under the unified archive while
    legacy-backup keeps the pre-upgrade relative path, so the original
    resolves at its live path while the tree is still in place and at the
    archived path afterwards; neither means the read-only-history contract
    is broken.
    """

    live = repo / source
    if live.is_file():
        return live
    archived = repo / INTENT_ARCHIVE_ROOT / source
    return archived if archived.is_file() else None


def select_intent_spec(repo: Path, intent: str | None, spec: str | None, apply: bool) -> dict:
    """Explicitly choose one migrated spec as the current feature.

    The migration and verification never touch the feature pointer; this
    user-invoked action writes `.specify/feature.json` only when the file is
    absent (a live pointer pointing elsewhere is never overwritten - use the
    SPECIFY_FEATURE_DIRECTORY environment or edit it by hand instead).
    """
    if bool(intent) == bool(spec):
        raise PHError("select-intent-spec needs exactly one of --intent or --spec")
    ledger_path = repo / INTENT_LEDGER_REL
    if not ledger_path.is_file():
        raise PHError(f"{INTENT_LEDGER_REL} is missing: run migrate-intents first")
    ledger = read_json(ledger_path)
    target = None
    if intent:
        for entry in ledger.get("entries") or []:
            if entry.get("intent_id") == intent:
                target = entry
                break
        if target is None:
            raise PHError(f"no migrated spec for intent {intent!r}; run migrate-intents or check the ledger")
    else:
        want = posix_rel(str(spec))
        # Accept both the feature directory and the spec.md file path.
        candidates = {want, f"{want.rstrip('/')}/spec.md".replace("//spec.md", "/spec.md")}
        for entry in ledger.get("entries") or []:
            if entry.get("spec") in candidates:
                target = entry
                break
        if target is None:
            raise PHError(f"{want} is not a ledger-recorded migrated spec; run migrate-intents first")
    spec_rel = target["spec"]
    if not (repo / spec_rel).is_file():
        raise PHError(f"migrated spec is missing on disk: {spec_rel}")
    # The upstream spec-kit resolver reads feature_directory as the FEATURE
    # DIRECTORY and derives FEATURE_SPEC as "<dir>/spec.md" itself, so the
    # pointer must hold the directory - writing the spec.md file path would
    # make upstream resolve specs/<dir>/spec.md/spec.md.
    feature_dir = posix_rel(spec_rel)[: -len("/spec.md")] if spec_rel.endswith("/spec.md") else posix_rel(spec_rel)
    if not (repo / feature_dir).is_dir():
        raise PHError(f"migrated feature directory is missing on disk: {feature_dir}")
    feature_json = repo / SPECIFY_DIR / "feature.json"
    result: dict = {
        "action": "select-intent-spec", "apply": apply, "intent_id": target.get("intent_id"),
        "spec": spec_rel, "feature_directory": feature_dir, "feature_json": f"{SPECIFY_DIR}/feature.json",
    }
    if feature_json.is_file():
        current = read_json(feature_json).get("feature_directory")
        if current == feature_dir:
            result["wrote"] = False
            result["reason"] = "feature pointer already selects this spec"
            return result
        if apply:
            raise PHError(
                f"refusing to overwrite the active feature pointer ({current!r}); use "
                "SPECIFY_FEATURE_DIRECTORY or adjust runtime/feature.json (.agents/project-harness/runtime/feature.json) by hand"
            )
        result["wrote"] = False
        result["refused"] = (
            f"the active feature pointer selects {current!r}; select-intent-spec never overwrites it "
            "(use SPECIFY_FEATURE_DIRECTORY or adjust runtime/feature.json (.agents/project-harness/runtime/feature.json) by hand)"
        )
        return result
    if apply:
        _write_repo_bytes(
            repo, f"{SPECIFY_DIR}/feature.json",
            (json.dumps({"feature_directory": feature_dir}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        result["wrote"] = True
    else:
        result["wrote"] = False
        result["planned"] = {"feature_directory": feature_dir}
    return result


def build_candidate(data: dict, version: str, skills: tuple[str, ...]) -> dict:
    cand = copy.deepcopy(data)
    cand.pop("schema_version", None)
    cand["template_version"] = version
    # Tool-neutral adapters: Codex and OpenCode read AGENTS.md and
    # .agents/skills natively, so the retired codex_skills adapter leaves the
    # manifest with the upgrade. Live .codex/skills/ph-* trees are retired by
    # finalize with per-entry evidence; ph_init's candidate whitelist accepts
    # exactly this additional deletion.
    adapters = cand.get("adapters")
    if isinstance(adapters, dict):
        adapters.pop("codex_skills", None)
    canonical = cand.get("canonical")
    if isinstance(canonical, dict):
        canonical["scripts"] = ".agents/scripts"
    skills_obj = cand.get("skills")
    if not isinstance(skills_obj, dict):
        raise PHError("illegal manifest: skills must be an object")
    skills_obj["required_names"] = list(skills)
    # The retired speckit section (upstream provenance and the per-file content
    # baselines) leaves the manifest with the 1.2.3 takeover; the baselines are
    # consumed by the sdd-skill-replacement migration before finalize.
    cand.pop("speckit", None)
    return cand


def assert_release_skill_installs(repo: Path, disk_version: str, state: dict) -> dict:
    """Pin each freshly installed release-only skill to the release bytes.

    While the disk is still below a skill's introducing release, an applied
    or not_applicable migration item means the semantic merge installed the
    release skill, so the canonical tree must match the release scaffold byte
    for byte: a same-name custom skill left in place must not pass as the
    installed one. After finalize writes the introducing version the pin no
    longer applies and later project customization of the skill is free.
    Skills that 1.1.14 retired (and their unshipped draft sibling ph-sure)
    are not pinned to a scaffold copy anymore; when the retirement item is
    applied they must be gone from the managed install instead. The memory
    skills reintroduced by the 1.2.1 target are removed from that retired
    set (they are release-only skills again and get pinned), so a freshly
    installed ph-memory-* directory never fails the retirement gate as a
    leftover. ph-memory-capture is not re-shipped and stays retired, so an
    applied retirement plus a live capture directory fails as a leftover.
    """
    statuses = {
        item.get("id"): item.get("status")
        for item in state.get("items", [])
        if isinstance(item, dict)
    }
    # Retired means "must be gone when retire-legacy-skills is applied".
    # Release-only skills the CURRENT target re-ships (the 1.2.1 memory
    # skills) leave the retired set and rejoin the byte pin below, decided by
    # the scaffold actually shipping the directory; skills the target no
    # longer ships (ph-docs-sync, ph-intent-verify, ph-memory-capture) stay
    # retired instead.
    scaffold_skills = SOURCE_ROOT / "assets" / "scaffold" / ".agents" / "skills"
    shipped_release_only = frozenset(
        skill for skill in RELEASE_ONLY_SKILLS if (scaffold_skills / skill).is_dir()
    )
    retired = (set(RETIRED_SKILLS) | {"ph-sure"}) - shipped_release_only
    if statuses.get("retire-legacy-skills") == "applied" and semver_tuple(disk_version) < semver_tuple(
        SPECKIT_INTRODUCED
    ):
        leftovers = sorted(
            skill
            for skill in retired
            if (repo / ".agents" / "skills" / skill / "SKILL.md").is_file()
            or (repo / ".claude" / "skills" / skill).exists()
        )  # .codex leftovers stay owned by the 1.1.9 tool-neutral retirement
        if leftovers:
            raise PHError(
                "retire-legacy-skills is applied but retired skills still live: "
                + ", ".join(leftovers)
            )
    # 1.2.3: once the skill-replacement item is applied, the seven retired
    # spec-kit names (and their .claude mirrors) must be gone from the managed
    # install; the three replaced names are covered by the release pin below
    # only while the disk is below 1.2.3, so a live old-generation copy fails
    # there instead.
    if statuses.get(SDD_SKILL_ITEM) in ITEM_DONE and semver_tuple(disk_version) < semver_tuple(
        SDD_INTRODUCED
    ):
        leftovers = sorted(
            skill
            for skill in SDD_RETIRED_SKILLS
            if (repo / ".agents" / "skills" / skill / "SKILL.md").is_file()
            or (repo / ".claude" / "skills" / skill).exists()
        )
        if leftovers:
            raise PHError(
                f"{SDD_SKILL_ITEM} is applied but retired spec-kit skills still live: "
                + ", ".join(leftovers)
            )
    for skill in sorted(shipped_release_only):
        item, introduced = RELEASE_ONLY_SKILLS[skill]
        if statuses.get(item) not in ITEM_DONE:
            continue  # pending/blocked items already fail the evidence gate
        if semver_tuple(disk_version) >= semver_tuple(introduced):
            continue
        target = SOURCE_ROOT / "assets" / "scaffold" / ".agents" / "skills" / skill
        installed = repo / ".agents" / "skills" / skill
        if not installed.is_dir() or installed.is_symlink():
            raise PHError(f"canonical skill {skill} must be a real directory")
        assert_real_dir(repo, installed, f"canonical skill {skill}")
        if not target.is_dir() or target.is_symlink():
            raise PHError(f"release scaffold is missing the {skill} skill")
        try:
            target_files = {
                posix_rel(path.relative_to(target)): path.read_bytes() for path in iter_files(target)
            }
            installed_files = {
                posix_rel(path.relative_to(installed)): path.read_bytes() for path in iter_files(installed)
            }
        except PHError as exc:
            raise PHError(f"cannot verify the installed {skill}: {exc}") from exc
        if installed_files != target_files:
            raise PHError(
                f"installed {skill} does not match the release skill; a same-name "
                "custom skill must block the migration item instead of passing as installed"
            )


def verify_payload(repo: Path) -> dict:
    to_version, skills = release_contract()
    src = source_status(to_version)
    data = read_disk_manifest(repo)
    profile, conflicts = detect_profile(live_skills(repo))
    if conflicts:
        raise PHError("retire old intent aliases before verify: " + "; ".join(conflicts))
    state = load_state(repo, to_version)
    disk_version = manifest_version(data)
    from_version = resolve_from_version(disk_version, to_version, state)
    if semver_tuple(from_version) > semver_tuple(to_version):
        raise PHError(f"refusing downgrade {from_version} -> {to_version}")
    chain = chain_between(from_version, to_version)
    validate_state(state, from_version, to_version, chain_items(chain), src)
    report = updates_dir(repo, to_version) / "report.md"
    assert_real_file(repo, report, "update report.md")
    if not report.read_text(encoding="utf-8").strip():
        raise PHError("report.md is empty")
    pending = [i["id"] for i in state["items"] if i.get("status") not in ITEM_DONE or not str(i.get("evidence", "")).strip()]
    if pending:
        raise PHError("items are not applied/not_applicable with evidence: " + ", ".join(pending))
    # intent-to-spec is a mandatory item: it always has legacy content to
    # register (the scaffold ships the intent tree), so it can never be
    # legitimately skipped as not_applicable.
    for item in state["items"]:
        if item.get("id") == "intent-to-spec" and item.get("status") != "applied":
            raise PHError("intent-to-spec is a mandatory migration item: it must be applied, not skipped")
    if any(i.get("id") == "intent-to-spec" for i in state["items"]):
        verify_intent_spec_layout(repo)
    assert_release_skill_installs(repo, disk_version, state)
    check_target_layout(repo, skills)
    content = ph_layout.verify_constraints(repo, Path(__file__).resolve().parents[1])
    if not content["ok"]:
        raise PHError("project constraints are incomplete: " + "; ".join(content["problems"]))
    assert_target_schema(repo)
    assert_local_ph_init(repo, to_version, skills)
    live_codex = codex_verify_check(repo, disk_version, to_version)
    mode = repo_mode(repo, data)
    candidate = build_candidate(data, to_version, skills)
    load_repo_manifest(repo, candidate=candidate)
    raise_if_blocked(cmd_sync(repo, mode, False, candidate=candidate), "candidate sync plan")
    if not src["verified"]:
        raise PHError(src["reason"])
    return {
        "action": "verify", "ok": True, "from": from_version, "to": to_version, "profile": profile,
        "status": state["status"], "mode": mode, "source": src,
        "codex_retirement": {"retirable": live_codex},
    }


def write_versions(repo: Path, data: dict, version: str, skills: tuple[str, ...]) -> None:
    path = repo / ".agents" / "ph.json"
    assert_real_file(repo, path, "canonical .agents/ph.json")
    dump_json(path, build_candidate(data, version, skills))


def mark_in_progress(repo: Path, to_version: str) -> None:
    state = load_state(repo, to_version)
    if state.get("status") == "complete":
        state["status"] = "in_progress"
        write_state(repo, to_version, state)


def finalize_payload(repo: Path, apply: bool) -> dict:
    to_version, skills = release_contract()
    src = source_status(to_version)
    if not src["can_finalize"]:
        raise PHError(src["reason"])
    verified = verify_payload(repo)
    data = read_disk_manifest(repo)
    mode = repo_mode(repo, data)
    candidate = build_candidate(data, to_version, skills)
    if not apply:
        return {
            "action": "finalize", "ok": True, "apply": False, "complete": False, "mode": mode,
            "from": verified["from"], "to": to_version,
            "codex_retirement": verified["codex_retirement"],
        }
    retired_codex = retire_codex_adapters(repo)
    # Persist the per-entry archive evidence (dest/kind/reason) into state
    # right after the retirement pass, so an interrupted finalize still leaves
    # an auditable trail; merging by name keeps a repeated finalize from
    # changing state, and a completed one stays byte-identical.
    state = load_state(repo, to_version)
    if merge_codex_retired(state, retired_codex):
        write_state(repo, to_version, state)
    raise_if_blocked(cmd_sync(repo, mode, True, candidate=candidate), "candidate sync apply")
    raise_if_blocked(cmd_check(repo, mode, candidate=candidate), "candidate check")
    write_versions(repo, read_disk_manifest(repo), to_version, skills)
    regular = cmd_check(repo, mode)
    if regular.blocked:
        mark_in_progress(repo, to_version)
        raise_if_blocked(regular, "regular check")
    state = load_state(repo, to_version)
    state["status"] = "complete"
    write_state(repo, to_version, state)
    return {
        "action": "finalize", "ok": True, "apply": True, "complete": True, "mode": mode,
        "from": verified["from"], "to": to_version, "retired_codex": retired_codex,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ph_merge_update.py")
    parser.add_argument(
        "action",
        choices=("inspect", "verify", "finalize", "migrate-intents", "select-intent-spec", "migrate-skills"),
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--intent", help="select-intent-spec: migrated intent_id to select")
    parser.add_argument("--spec", help="select-intent-spec: ledger-recorded spec path to select")
    parser.add_argument(
        "--extras-decisions",
        help="migrate-skills: reviewed per-directory decision file for unattributed extra files "
        "(JSON: {\"<skill>\": {\"decision\": \"archive\", \"note\": \"...\"}})",
    )
    args = parser.parse_args(argv)
    writable = {"finalize", "migrate-intents", "select-intent-spec", "migrate-skills"}
    if args.action != "finalize" and args.action not in writable and args.apply:
        parser.error(f"{args.action} is read-only; do not pass --apply")
    dispatch = {
        "inspect": inspect_payload,
        "verify": verify_payload,
        "finalize": lambda r: finalize_payload(r, args.apply),
        "migrate-intents": lambda r: migrate_intents_payload(r, args.apply),
        "select-intent-spec": lambda r: select_intent_spec(r, args.intent, args.spec, args.apply),
        "migrate-skills": lambda r: migrate_skills_payload(r, args.apply, args.extras_decisions),
    }
    try:
        repo = find_repo(args.repo)
        payload = dispatch[args.action](repo)
    except PHError as exc:
        sys.stderr.write(f"error={exc}\n")
        return 2
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
