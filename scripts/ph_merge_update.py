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
from pathlib import Path

import ph_init
from ph_init import (
    PHError, cmd_check, cmd_sync, contained, ensure_canonical_root,
    expected_rel_link, find_repo, infer_mode, is_disallowed_reparse,
    is_git_symlink_mode, iter_files, load_repo_manifest, posix_rel,
    read_json, reject_nested_links, sha256_file,
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
# ph-intent-verify arrives with 1.1.13/intent-verify-skill.)
RELEASE_ONLY_SKILLS = {
    "ph-docs-sync": ("docs-sync-skill", "1.1.10"),
    "ph-intent-verify": ("intent-verify-skill", "1.1.13"),
}
INTENT_ROOTS = ("docs/意图/待办", "docs/意图/实施")
INTENT_KINDS = ("新特性", "问题记录")
TARGET_FILES = ("docs/意图/README.md", "docs/意图/_模板.md", "docs/意图/访谈纪要/_模板.md", "docs/约束规范/工程规范/意图与访谈.md", ".agents/AGENTS.md")
CORE_PREFIXES = (
    "release.json",
    "SKILL.md",
    "scripts/ph_init.py",
    "scripts/ph_release.py",
    "scripts/ph_merge_update.py",
    "migrations/",
    "assets/scaffold/",
)
PH_INIT_RUNTIME = (
    "SKILL.md",
    "release.json",
    "scripts/ph_init.py",
    "scripts/ph_release.py",
    "scripts/ph_merge_update.py",
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
        out.append(
            f".agents/skills/{skill}: same-name directory exists below "
            f"{introduced} and no PH release ships it; treat it as project "
            f"content, keep it in place, block the {item} item, and ask "
            "the user before any replacement"
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
        raise PHError("state.source does not match source receipt")
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
    return {
        "action": "inspect", "from": from_version, "to": to_version, "profile": profile,
        "up_to_date": up_to_date, "conflicts": conflicts, "chain": chain, "mode": mode,
        "source": src, "can_finalize": src["can_finalize"] and not up_to_date and not conflicts,
        "existing_state": existing, "suggested_state": None if up_to_date else suggested_state(from_version, to_version, src),
        "skills": sorted(names), "codex_retirement": codex,
    }


def target_paths() -> tuple[list[str], list[str]]:
    dirs = [r for r in INTENT_ROOTS] + [f"{r}/{k}" for r in INTENT_ROOTS for k in INTENT_KINDS]
    files = list(TARGET_FILES) + [f"{d}/README.md" for d in dirs]
    return dirs, files


def leftover_aliases(repo: Path) -> list[str]:
    leftover = [n for n in OLD_ALIASES if n in live_skills(repo)]
    leftover += [posix_rel(f"{v}/skills/{n}") for v in (".claude", ".codex") for n in OLD_ALIASES if (p := repo / v / "skills" / n).exists() or p.is_symlink()]
    return leftover


def check_target_layout(repo: Path, skills: tuple[str, ...]) -> None:
    for name in skills:
        root = repo / ".agents" / "skills" / name
        assert_real_dir(repo, root, f"canonical skill {name}")
        assert_real_file(repo, root / "SKILL.md", f"canonical skill {name}/SKILL.md")
    dirs, files = target_paths()
    for rel in dirs:
        assert_real_dir(repo, repo / rel, rel)
    for rel in files:
        dest = repo / rel
        assert_real_file(repo, dest, rel)
        text = dest.read_text(encoding="utf-8")
        if not text.strip():
            raise PHError(f"{rel} is empty")
        if rel == "docs/意图/_模板.md" and not re.search(
            r'^status_dir:\s*[\"\']?待办/新特性[\"\']?\s*$', text, re.MULTILINE
        ):
            raise PHError(f"{rel} must default status_dir to 待办/新特性")
    leftover = leftover_aliases(repo)
    if leftover:
        raise PHError("old intent aliases still live: " + ", ".join(leftover))


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
# ones into `.agents/archived/<date>-pre-update/codex-skills/`, and anything
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
            + "; archive them under .agents/archived/<date>-pre-update/codex-skills/ or remove "
            "them, then re-verify"
        )
    return live


def codex_archive_base(repo: Path) -> Path:
    """Archive root for retired codex adapters, stable across interrupted runs.

    Reuses an existing <date>-pre-update/codex-skills directory an earlier
    interrupted finalize already created; otherwise today's UTC date starts a
    fresh one. Other archived content is never considered or touched.
    """
    archived = repo / ".agents" / "archived"
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
    lands under .agents/archived/<date>-pre-update/codex-skills/<name> so the
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
    skills_obj = cand.get("skills")
    if not isinstance(skills_obj, dict):
        raise PHError("illegal manifest: skills must be an object")
    skills_obj["required_names"] = list(skills)
    return cand


def assert_release_skill_installs(repo: Path, disk_version: str, state: dict) -> None:
    """Pin each freshly installed release-only skill to the release bytes.

    While the disk is still below a skill's introducing release, an applied
    or not_applicable migration item means the semantic merge installed the
    release skill, so the canonical tree must match the release scaffold byte
    for byte: a same-name custom skill left in place must not pass as the
    installed one (ph-docs-sync with 1.1.10, ph-intent-verify with 1.1.13).
    After finalize writes the introducing version the pin no longer applies
    and later project customization of the skill is free.
    """
    statuses = {
        item.get("id"): item.get("status")
        for item in state.get("items", [])
        if isinstance(item, dict)
    }
    for skill in sorted(RELEASE_ONLY_SKILLS):
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
    assert_release_skill_installs(repo, disk_version, state)
    check_target_layout(repo, skills)
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
    parser.add_argument("action", choices=("inspect", "verify", "finalize"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.action != "finalize" and args.apply:
        parser.error(f"{args.action} is read-only; do not pass --apply")
    try:
        repo = find_repo(args.repo)
        payload = {"inspect": inspect_payload, "verify": verify_payload, "finalize": lambda r: finalize_payload(r, args.apply)}[args.action](repo)
    except PHError as exc:
        sys.stderr.write(f"error={exc}\n")
        return 2
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
