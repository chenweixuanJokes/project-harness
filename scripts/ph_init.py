#!/usr/bin/env python3
"""PH bootstrapper: install, check, and sync a repository-local Project Harness.

Codex and OpenCode read AGENTS.md and `.agents/skills` natively, so only the
Claude entry points need adapters. This script is the only writer for those
adapters. It is self-contained after install — runtime assets live next to
this file, never at a proposal-repo absolute path.

No third-party deps. No schema upgrade / history migration.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


ACTIONS = ("init", "check", "sync")
MODES = ("portable", "symlink")
# `auto` exists only as a CLI request for a fresh install: it is never
# persisted to the manifest and resolves to a concrete mode at apply time.
CLI_MODES = ("auto", "portable", "symlink")
CLAUDE_STUB = "@.agents/AGENTS.md\n"
PH_GITIGNORE_ENTRY = "/.worktrees/"
PH_GITIGNORE_BLOCK = (
    "# PH-marker: isolated Git worktrees are local execution environments, not source.\n"
    "# Keep this exact ignore entry so `ph-init` / adapters can detect the convention.\n"
    "/.worktrees/\n"
)
RELEASE = json.loads((Path(__file__).resolve().parent.parent / "release.json").read_text(encoding="utf-8"))
RELEASE_VERSION = RELEASE["version"]
REQUIRED_SKILLS = tuple(RELEASE["required_skills"])
# The self-developed spec-driven runtime root (relocated from the pre-1.2.1
# `.specify/` layout). The pinned upstream Spec Kit integration it once hosted
# was retired with 1.2.3; the constitution materialization and navigation
# checks it performed live in ph_governance.py now.
SPECIFY_DIR = ".agents/project-harness/runtime"
RUNTIME_MANAGED_MINIMUM = (
    ".agents/project-harness/constitution.md",
    ".agents/scripts/ph_sdd.py",
)
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REL_PATH = re.compile(
    r"^(?!\/)(?!\~\/)(?![A-Za-z]:)(?![a-zA-Z][a-zA-Z0-9+.-]*:)"
    r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$"
)
SKIP_DIR_NAMES = {"__pycache__", ".git"}
SKIP_FILE_NAMES = {".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
# Sync may rewrite only this structured problem. Every other conflict stays
# blocking, including unknown/missing problem types. Do not infer permission
# from human-readable reason text.
PROBLEM_CONTENT_DRIFT = "content_drift"
PROBLEM_EXISTING_DIFF = "existing_diff"
PROBLEM_OUTSIDE_REPO = "outside_repo"
PROBLEM_DEST_SYMLINK = "destination_symlink"
PROBLEM_DEST_JUNCTION = "destination_junction"
PROBLEM_NOT_REGULAR_FILE = "not_regular_file"
PROBLEM_NOT_DIRECTORY = "not_directory"
PROBLEM_HARDLINK = "hardlink"
PROBLEM_UNMANAGED_EXTRA = "unmanaged_extra"
PROBLEM_GIT_SYMLINK = "git_symlink_degenerated"
PROBLEM_NESTED_LINK = "nested_symlink"
PROBLEM_SYMLINK_TARGET = "symlink_target_mismatch"
PROBLEM_EXISTING_NON_SYMLINK = "existing_non_symlink"
SYNC_REPAIRABLE_PROBLEMS = frozenset({PROBLEM_CONTENT_DRIFT})
FALSE_CORE_SYMLINKS = frozenset({"false", "0", "no", "off"})
# Adopt-plan contract: a session reads the legacy rules of an uninstalled repo,
# merges them with the PH template, and the user reviews the exact write set.
# The plan is the authorization; the script only verifies and materializes it.
ADOPT_PLAN_VERSION = 1
ADOPT_CANONICAL = ".agents/AGENTS.md"
ADOPT_ROOT_ENTRIES = ("AGENTS.md", "CLAUDE.md")
# Active PH content roots an adopt plan may also carry besides docs/**:
# legacy 约束规范 / 项目Wiki trees merge into the project-harness home.
ADOPT_HOME_ROOTS = (
    ".agents/project-harness/constraints",
    ".agents/project-harness/documents",
)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
ADOPT_UNSAFE_HEAD = re.compile(r"^(?:/|~|[A-Za-z]:[\\/]|[A-Za-z][A-Za-z0-9+.-]*:)")
ADOPT_NTFS_RESERVED = frozenset('<>:"|?*')


class PHError(Exception):
    """User-facing failure that should become a non-zero exit, not a traceback."""


@dataclass
class Item:
    kind: str  # write | skip | conflict | block | error | ok
    path: str
    reason: str
    problem: str | None = None


@dataclass
class Report:
    action: str
    mode: str
    apply: bool
    items: list[Item] = field(default_factory=list)

    def add(self, kind: str, path: str, reason: str, problem: str | None = None) -> None:
        self.items.append(Item(kind, posix_rel(path), reason, problem))

    @property
    def blocked(self) -> bool:
        return any(i.kind in {"conflict", "block", "error"} for i in self.items)

    def render(self) -> str:
        status = "error" if self.blocked else "ok"
        lines = [
            f"status={status}",
            f"action={self.action}",
            f"mode={self.mode}",
            f"apply={str(self.apply).lower()}",
        ]
        for item in self.items:
            lines.append(f"item={item.kind}\t{item.path}\t{item.reason}")
        return "\n".join(lines) + "\n"


def skill_root() -> Path:
    """Directory that contains SKILL.md and self-contained assets.

    Resolved from this file so an installed copy can initialize another
    repository without reading the proposal tree.
    """

    return Path(__file__).resolve().parent.parent


def scaffold_root() -> Path:
    path = skill_root() / "assets" / "scaffold"
    if not path.is_dir():
        raise PHError(f"missing self-contained scaffold: {path}")
    return path


def posix_rel(path: str | Path) -> str:
    return str(path).replace(os.sep, "/")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_git_symlink_mode(repo: Path, rel: str) -> bool:
    """Detect Git mode 120000 even when the worktree file is plain text.

    Why: `core.symlinks=false` checkouts materialize a symlink as a regular
    file whose contents are the target path. `Path.is_symlink()` is then false,
    but PH still has to treat it as a broken/degraded symlink, not a portable
    copy.
    """

    proc = run_git(repo, "ls-files", "--stage", "-z", "--", rel, check=False)
    if proc.returncode != 0 or not proc.stdout:
        return False
    for rec in proc.stdout.split("\0"):
        if not rec:
            continue
        # format: <mode> <sha> <stage>\t<path>
        meta, _, _path = rec.partition("\t")
        mode = meta.split(" ", 1)[0]
        if mode == "120000":
            return True
    return False


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise PHError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def find_repo(explicit: str | None) -> Path:
    start = Path(explicit).resolve() if explicit else Path.cwd().resolve()
    if not start.exists():
        raise PHError(f"path does not exist: {start}")
    cwd = start if start.is_dir() else start.parent
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise PHError("not a git repository; PH only installs into a git root")
    return Path(proc.stdout.strip()).resolve()


def contained(repo: Path, path: Path) -> bool:
    repo_r = repo.resolve()
    try:
        path.resolve().relative_to(repo_r)
        return True
    except ValueError:
        return False


def repo_rel(repo: Path, path: Path) -> str:
    """Return the adapter path, not the destination of an existing symlink."""

    return posix_rel(path.absolute().relative_to(repo.absolute()))


def expected_rel_link(link: Path, target: Path) -> str:
    return posix_rel(os.path.relpath(target, start=link.parent))


def is_hardlink_to(path: Path, other: Path) -> bool:
    if not path.exists() or not other.exists():
        return False
    if path.is_symlink() or other.is_symlink():
        return False
    s1 = path.stat()
    s2 = other.stat()
    return s1.st_ino == s2.st_ino and s1.st_dev == s2.st_dev


def is_disallowed_reparse(path: Path) -> bool:
    """Reject Windows junctions / non-symlink reparse points if we can see them.

    PH only creates POSIX symlinks or regular files. Junctions and hardlinks
    are not portable across checkouts.
    """

    if not path.exists() and not path.is_symlink():
        return False
    if os.name == "nt":
        try:
            st = os.lstat(path)
            attrs = getattr(st, "st_file_attributes", 0)
            reparse = bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return reparse and not path.is_symlink()
        except OSError:
            return False
    return False


def is_nested_link(path: Path) -> bool:
    """True for a POSIX symlink or a Windows junction at this exact node."""

    return path.is_symlink() or is_disallowed_reparse(path)


def reject_nested_links(root: Path, *, label: str) -> None:
    """Refuse to walk a tree that contains nested symlink/junction nodes.

    `os.walk` skips symlink directories by default, so a nested directory
    link would otherwise vanish from the inventory and make check look green.
    File links are equally banned: PH skill resources are regular files.
    """

    if is_nested_link(root):
        raise PHError(f"{label} is a nested symlink or junction: {root}")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for name in list(dirnames):
            child = current / name
            if is_nested_link(child):
                raise PHError(f"{label} contains nested symlink or junction: {child}")
        for name in filenames:
            child = current / name
            if is_nested_link(child):
                raise PHError(f"{label} contains nested symlink or junction: {child}")


def iter_files(root: Path) -> Iterable[Path]:
    """Yield regular files only. Nested symlink/junction nodes fail closed."""

    reject_nested_links(root, label="tree")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for name in filenames:
            if name in SKIP_FILE_NAMES or Path(name).suffix in SKIP_SUFFIXES:
                continue
            path = Path(dirpath) / name
            if is_nested_link(path):
                raise PHError(f"tree contains nested symlink or junction: {path}")
            yield path


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PHError(f"missing manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PHError(f"illegal manifest JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PHError(f"illegal manifest: {path}: root must be an object")
    return data


def _need(obj: dict, key: str, ctx: str) -> object:
    if key not in obj:
        raise PHError(f"illegal manifest: missing {ctx}.{key}" if ctx else f"illegal manifest: missing {key}")
    return obj[key]


def _const(value: object, expected: object, ctx: str) -> None:
    if value != expected:
        raise PHError(f"illegal manifest: {ctx} must be {expected!r}, got {value!r}")


def _rel(value: object, ctx: str) -> str:
    if not isinstance(value, str) or not REL_PATH.match(value):
        raise PHError(f"illegal manifest: {ctx} is not a repository-relative POSIX path")
    return value


def validate_manifest(data: dict) -> None:
    """Necessary-field check. Not a full JSON Schema evaluator.

    Why stdlib-only: installed PH must not grow a jsonschema dependency, and
    the approved schema is a closed const-heavy inventory, not an open document.
    """

    for key in (
        "$schema",
        "template_version",
        "adapter_mode",
        "canonical",
        "adapters",
        "worktree",
        "memory",
        "skills",
    ):
        _need(data, key, "")
    _const(data["$schema"], "./ph.schema.json", "$schema")
    if "schema_version" in data:
        raise PHError(
            "illegal manifest: schema_version was removed; the manifest carries only "
            f"template_version (expected {RELEASE_VERSION!r}). Re-run ph-merge-update "
            "to adopt the single-version manifest format."
        )
    value = data["template_version"]
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise PHError("illegal manifest: template_version is not semver")
    _const(value, RELEASE_VERSION, "template_version")
    if data["adapter_mode"] not in MODES:
        raise PHError("illegal manifest: adapter_mode must be portable or symlink")

    canonical = data["canonical"]
    if not isinstance(canonical, dict):
        raise PHError("illegal manifest: canonical must be an object")
    for key, expected in {
        "root": ".agents",
        "agents": ".agents/AGENTS.md",
        "manifest": ".agents/ph.json",
        "schema": ".agents/ph.schema.json",
        "memory": ".agents/project-harness/memory",
        "skills": ".agents/skills",
        "scripts": ".agents/scripts",
    }.items():
        _const(_need(canonical, key, "canonical"), expected, f"canonical.{key}")

    adapters = data["adapters"]
    if not isinstance(adapters, dict):
        raise PHError("illegal manifest: adapters must be an object")
    mode = data["adapter_mode"]
    specs = {
        "root_agents": (
            "managed_copy" if mode == "portable" else "symlink",
            "AGENTS.md",
            ".agents/AGENTS.md",
            None,
        ),
        "claude_entry": (
            "import_stub" if mode == "portable" else "symlink",
            "CLAUDE.md",
            ".agents/AGENTS.md",
            None,
        ),
        "claude_skills": (
            "mirror_tree" if mode == "portable" else "symlink",
            ".claude/skills",
            ".agents/skills",
            "ph-*",
        ),
    }
    if set(adapters) != set(specs):
        raise PHError(
            "illegal manifest: adapters must contain only root_agents, "
            "claude_entry, and claude_skills"
        )
    for name, (expected_mode, path, source, include) in specs.items():
        adapter = _need(adapters, name, "adapters")
        if not isinstance(adapter, dict):
            raise PHError(f"illegal manifest: adapters.{name} must be an object")
        _const(_need(adapter, "mode", f"adapters.{name}"), expected_mode, f"adapters.{name}.mode")
        _const(_rel(_need(adapter, "path", f"adapters.{name}"), f"adapters.{name}.path"), path, f"adapters.{name}.path")
        _const(
            _rel(_need(adapter, "source", f"adapters.{name}"), f"adapters.{name}.source"),
            source,
            f"adapters.{name}.source",
        )
        if include is not None:
            _const(_need(adapter, "include", f"adapters.{name}"), include, f"adapters.{name}.include")

    worktree = data["worktree"]
    if not isinstance(worktree, dict):
        raise PHError("illegal manifest: worktree must be an object")
    _const(_need(worktree, "root", "worktree"), ".worktrees", "worktree.root")
    _const(_need(worktree, "gitignore_entry", "worktree"), "/.worktrees/", "worktree.gitignore_entry")
    _const(_need(worktree, "path_mode", "worktree"), "slug_hash", "worktree.path_mode")
    _const(_need(worktree, "wip_prefix", "worktree"), "wip:", "worktree.wip_prefix")
    commands = _need(worktree, "verify_commands", "worktree")
    if not isinstance(commands, list) or any(
        not isinstance(command, list)
        or not command
        or any(not isinstance(arg, str) or not arg for arg in command)
        for command in commands
    ):
        raise PHError("illegal manifest: worktree.verify_commands must be argv arrays")
    max_bytes = _need(worktree, "max_changed_file_bytes", "worktree")
    if not isinstance(max_bytes, int) or not (1 <= max_bytes <= 1024 * 1024 * 1024):
        raise PHError("illegal manifest: worktree.max_changed_file_bytes is out of range")

    memory = data["memory"]
    if not isinstance(memory, dict):
        raise PHError("illegal manifest: memory must be an object")
    _const(_need(memory, "root", "memory"), ".agents/project-harness/memory", "memory.root")
    directories = _need(memory, "directories", "memory")
    if not isinstance(directories, dict):
        raise PHError("illegal manifest: memory.directories must be an object")
    for key, expected in (("temporary", "temporary"), ("structured", "structured"), ("archive", "../archive/memory")):
        _const(_need(directories, key, "memory.directories"), expected, f"memory.directories.{key}")
    fields = _need(memory, "frontmatter_fields", "memory")
    expected_fields = [
        "kind",
        "status",
        "created",
        "updated",
        "provenance",
        "confidence",
        "review_after",
        "supersedes",
        "sensitivity",
        "topics",
    ]
    if fields != expected_fields:
        raise PHError("illegal manifest: memory.frontmatter_fields mismatch")

    skills = data["skills"]
    if not isinstance(skills, dict):
        raise PHError("illegal manifest: skills must be an object")
    _const(_need(skills, "root", "skills"), ".agents/skills", "skills.root")
    names = _need(skills, "required_names", "skills")
    if names != list(REQUIRED_SKILLS):
        raise PHError("illegal manifest: skills.required_names mismatch")
    if "speckit" in data:
        raise PHError(
            "illegal manifest: the speckit section was removed with the upstream "
            "integration; re-run ph-merge-update to adopt the self-developed runtime"
        )


def ensure_canonical_root(repo: Path) -> None:
    """Canonical PH content must be a real repository-local directory."""

    root = repo / ".agents"
    if not root.exists() and not root.is_symlink():
        return
    if root.is_symlink() or is_disallowed_reparse(root):
        raise PHError("canonical .agents must not be a symlink or junction")
    if not root.is_dir() or not contained(repo, root):
        raise PHError("canonical .agents must be a repository-local directory")


def ensure_canonical_layout(repo: Path) -> None:
    # A completely absent .agents is the "missing manifest" case; let read_json
    # produce that message instead of a partial-layout error.
    if not (repo / ".agents").exists() and not (repo / ".agents").is_symlink():
        return
    ensure_canonical_root(repo)
    agents = repo / ".agents" / "AGENTS.md"
    if agents.is_symlink() or is_disallowed_reparse(agents):
        raise PHError("canonical .agents/AGENTS.md must not be a symlink or junction")
    if not agents.is_file() or not contained(repo, agents):
        raise PHError("canonical .agents/AGENTS.md must be a repository-local regular file")
    skills = repo / ".agents" / "skills"
    if skills.is_symlink() or is_disallowed_reparse(skills):
        raise PHError("canonical .agents/skills must not be a symlink or junction")
    if not skills.is_dir() or not contained(repo, skills):
        raise PHError("canonical .agents/skills must be a repository-local directory")
    for name in REQUIRED_SKILLS:
        root = skills / name
        skill = root / "SKILL.md"
        if root.is_symlink() or is_disallowed_reparse(root) or not contained(repo, root):
            raise PHError(f"canonical skill {name} must be a repository-local real directory")
        if skill.is_symlink() or is_disallowed_reparse(skill) or not skill.is_file():
            raise PHError(f"canonical skill {name}/SKILL.md must be a regular file")
        reject_nested_links(root, label=f"canonical skill {name}")


def load_repo_manifest(repo: Path, *, candidate: dict | None = None) -> dict:
    # Only the merge-update verifier supplies a candidate; normal commands
    # reject old versions before checking for newly required skills.
    path = repo / ".agents" / "ph.json"
    ensure_canonical_root(repo)
    if path.is_symlink() or is_disallowed_reparse(path) or not contained(repo, path):
        raise PHError("canonical .agents/ph.json must be a regular repository-local file")
    if not path.is_file() or path.stat().st_nlink > 1:
        raise PHError("canonical .agents/ph.json must be a regular unshared file")
    actual = read_json(path)
    data = actual if candidate is None else candidate
    if candidate is not None:
        expected = dict(actual)
        expected.pop("schema_version", None)
        expected["template_version"] = RELEASE_VERSION
        expected["skills"] = dict(actual.get("skills", {}), required_names=list(REQUIRED_SKILLS))
        # Upgrades adopt the canonical scripts directory; everything else in
        # the disk manifest stays fixed.
        expected["canonical"] = dict(actual.get("canonical") or {}, scripts=".agents/scripts")
        # The retired speckit section (upstream provenance plus per-file
        # content baselines) leaves the manifest with the 1.2.3 takeover: the
        # baselines are consumed by the skill-replacement migration before
        # finalize, and the target runtime no longer carries upstream state.
        expected.pop("speckit", None)
        # Upgrading a pre-1.1.9 manifest additionally removes the retired
        # codex_skills adapter. The target candidate must use that minimal
        # three-adapter topology; every other difference stays a rejection.
        expected["adapters"] = dict(actual.get("adapters") or {})
        expected["adapters"].pop("codex_skills", None)
        if candidate != expected:
            raise PHError(
                "candidate may change only template_version, the canonical scripts "
                "directory, and the required skills list; it may also delete the "
                "removed schema_version field, the removed adapters.codex_skills "
                "adapter, and the removed speckit section"
            )
    validate_manifest(data)
    ensure_canonical_layout(repo)
    return data


def tracked_worktrees(repo: Path) -> list[str]:
    proc = run_git(repo, "ls-files", "-z", "--", ".worktrees", check=False)
    if proc.returncode != 0 or not proc.stdout:
        return []
    return [p for p in proc.stdout.split("\0") if p]


def infer_mode(repo: Path) -> str | None:
    """Infer the locked repo mode from adapters that already exist.

    Mode is not stored in ph.json (schema forbids extra keys). The presence of
    a symlink vs a regular managed copy is the lock.
    """

    root_agents = repo / "AGENTS.md"
    claude = repo / "CLAUDE.md"
    votes: set[str] = set()
    if root_agents.is_symlink() or is_git_symlink_mode(repo, "AGENTS.md"):
        votes.add("symlink")
    elif root_agents.is_file():
        votes.add("portable")
    if claude.is_symlink() or is_git_symlink_mode(repo, "CLAUDE.md"):
        votes.add("symlink")
    elif claude.is_file():
        votes.add("portable")
    skill_probe = repo / ".claude" / "skills"
    if skill_probe.is_dir():
        for child in skill_probe.iterdir():
            if not child.name.startswith("ph-"):
                continue
            if child.is_symlink() or is_git_symlink_mode(repo, repo_rel(repo, child)):
                votes.add("symlink")
            elif child.exists():
                votes.add("portable")
    if not votes:
        return None
    if votes == {"portable", "symlink"}:
        raise PHError("mixed portable/symlink adapters; repository mode is mixed and cannot be inferred")
    return next(iter(votes))


def resolve_mode(repo: Path, requested: str | None, action: str) -> str:
    """Resolve the requested mode against the repository's locked state.

    A manifest's `adapter_mode` only ever persists a concrete portable or
    symlink choice. `auto` is a CLI-only request: an installed (or otherwise
    locked) repository keeps its declared/inferred mode regardless, and only a
    fresh install defers the choice to apply time.
    """

    ensure_canonical_root(repo)
    manifest_path = repo / ".agents" / "ph.json"
    declared: str | None = None
    if manifest_path.is_symlink() or is_disallowed_reparse(manifest_path):
        raise PHError("canonical .agents/ph.json must not be a symlink or junction")
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        validate_manifest(manifest)
        declared = manifest["adapter_mode"]
    inferred = infer_mode(repo)
    locked = declared or inferred
    if declared and inferred and declared != inferred and action != "sync":
        raise PHError(
            f"manifest declares {declared} but adapters look like {inferred}; run check before repair"
        )
    if requested not in (None, "auto") and locked and requested != locked:
        raise PHError(
            f"repository mode is locked to {locked}; refusing to {action} as {requested}. "
            "PH does not migrate modes."
        )
    if locked:
        return locked
    return requested or "auto"


def gitignore_has_entry(text: str) -> bool:
    for raw in text.splitlines():
        line = raw.strip()
        if line == PH_GITIGNORE_ENTRY or line == ".worktrees/" or line == ".worktrees":
            return True
    return False


def plan_write_file(
    report: Report,
    dest: Path,
    data: bytes,
    reason: str,
    repo: Path,
    *,
    repairable: bool = False,
) -> None:
    try:
        rel = repo_rel(repo, dest)
    except ValueError:
        report.add(
            "conflict",
            dest,
            f"{reason}: destination is outside the repository",
            PROBLEM_OUTSIDE_REPO,
        )
        return
    if not contained(repo, dest):
        report.add(
            "conflict",
            rel,
            f"{reason}: destination resolves outside the repository",
            PROBLEM_OUTSIDE_REPO,
        )
        return
    if dest.is_symlink() or dest.exists():
        if dest.is_symlink():
            report.add("conflict", rel, f"{reason}: destination is a symlink", PROBLEM_DEST_SYMLINK)
            return
        if is_disallowed_reparse(dest):
            report.add(
                "conflict",
                rel,
                f"{reason}: destination is a junction/reparse point",
                PROBLEM_DEST_JUNCTION,
            )
            return
        if not dest.is_file():
            report.add(
                "conflict",
                rel,
                f"{reason}: destination is not a regular file",
                PROBLEM_NOT_REGULAR_FILE,
            )
            return
        current = dest.read_bytes()
        if current == data:
            report.add("skip", rel, f"{reason}: identical")
            return
        problem = PROBLEM_CONTENT_DRIFT if repairable else PROBLEM_EXISTING_DIFF
        report.add("conflict", rel, f"{reason}: existing file differs", problem)
        return
    report.add("write", repo_rel(repo, dest) if contained(repo, dest) else posix_rel(dest.relative_to(repo)), reason)


def plan_skip_or_write_copy(
    report: Report,
    src: Path,
    dest: Path,
    reason: str,
    repo: Path,
    *,
    repairable: bool = False,
) -> None:
    if dest.exists() and not dest.is_symlink() and is_hardlink_to(dest, src):
        report.add("conflict", repo_rel(repo, dest), f"{reason}: hardlink is not allowed", PROBLEM_HARDLINK)
        return
    plan_write_file(report, dest, src.read_bytes(), reason, repo, repairable=repairable)


def plan_authorized_write(report: Report, dest: Path, data: bytes, reason: str, repo: Path) -> None:
    """Plan a root-entry rewrite authorized by a hash-pinned adopt source.

    Only the two root rule entries may reach this helper: their current bytes
    were pinned in the adopt plan's sources, so replacing them with the merged
    candidate (portable copy / CLAUDE stub) is the reviewed transformation.
    Unsafe shapes still conflict; nothing is forced.
    """

    try:
        rel = repo_rel(repo, dest)
    except ValueError:
        report.add(
            "conflict",
            dest,
            f"{reason}: destination is outside the repository",
            PROBLEM_OUTSIDE_REPO,
        )
        return
    if not contained(repo, dest):
        report.add(
            "conflict",
            rel,
            f"{reason}: destination resolves outside the repository",
            PROBLEM_OUTSIDE_REPO,
        )
        return
    if dest.is_symlink():
        report.add("conflict", rel, f"{reason}: destination is a symlink", PROBLEM_DEST_SYMLINK)
        return
    if is_disallowed_reparse(dest):
        report.add("conflict", rel, f"{reason}: destination is a junction/reparse point", PROBLEM_DEST_JUNCTION)
        return
    if dest.exists() and not dest.is_file():
        report.add("conflict", rel, f"{reason}: destination is not a regular file", PROBLEM_NOT_REGULAR_FILE)
        return
    try:
        shared = dest.exists() and dest.stat().st_nlink > 1
    except OSError:
        shared = True
    if shared:
        report.add("conflict", rel, f"{reason}: hardlink is not allowed", PROBLEM_HARDLINK)
        return
    if not dest.exists():
        report.add("write", rel, reason)
        return
    if dest.read_bytes() == data:
        report.add("skip", rel, f"{reason}: identical")
        return
    report.add("write", rel, f"{reason}: 来源已确认，覆盖为合并结果")


def apply_file(dest: Path, data: bytes) -> None:
    if dest.is_symlink() or is_disallowed_reparse(dest):
        raise PHError(f"refusing to write through symlink or junction: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.ph-tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)


def copy_file_bytes(src: Path, dest: Path) -> None:
    apply_file(dest, src.read_bytes())


def plan_file_set_copy(
    report: Report,
    repo: Path,
    src_root: Path,
    source_files: Iterable[Path],
    dest_root: Path,
    rel: str,
    reason: str,
    *,
    repairable: bool = False,
) -> None:
    """Plan a managed directory copy without following or mixing user-owned content."""

    try:
        reject_nested_links(src_root, label=reason)
        files = list(source_files)
    except PHError as exc:
        report.add("conflict", rel, str(exc), PROBLEM_NESTED_LINK)
        return
    if dest_root.is_symlink() or is_git_symlink_mode(repo, rel):
        report.add("conflict", rel, f"{reason}: destination root is a symlink", PROBLEM_DEST_SYMLINK)
        return
    if not contained(repo, dest_root):
        report.add(
            "conflict",
            rel,
            f"{reason}: destination resolves outside the repository",
            PROBLEM_OUTSIDE_REPO,
        )
        return
    if is_disallowed_reparse(dest_root):
        report.add(
            "conflict",
            rel,
            f"{reason}: destination root is a junction/reparse point",
            PROBLEM_DEST_JUNCTION,
        )
        return
    if dest_root.exists() and not dest_root.is_dir():
        report.add("conflict", rel, f"{reason}: destination root is not a directory", PROBLEM_NOT_DIRECTORY)
        return
    expected = {posix_rel(path.relative_to(src_root)) for path in files}
    if dest_root.is_dir():
        try:
            reject_nested_links(dest_root, label=reason)
            extra_files = sorted(
                posix_rel(path.relative_to(dest_root))
                for path in iter_files(dest_root)
                if posix_rel(path.relative_to(dest_root)) not in expected
            )
        except PHError as exc:
            report.add("conflict", rel, str(exc), PROBLEM_NESTED_LINK)
            return
        if extra_files:
            report.add(
                "conflict",
                rel,
                f"{reason} has unmanaged extra files: " + ", ".join(extra_files[:8]),
                PROBLEM_UNMANAGED_EXTRA,
            )
            return
    for src in files:
        dest = dest_root / src.relative_to(src_root)
        plan_skip_or_write_copy(
            report,
            src,
            dest,
            reason,
            repo,
            repairable=repairable,
        )


def plan_tree_copy(report: Report, src_root: Path, dest_root: Path, reason: str, repo: Path) -> None:
    plan_file_set_copy(
        report,
        repo,
        src_root,
        iter_files(src_root),
        dest_root,
        repo_rel(repo, dest_root),
        reason,
    )


def apply_tree_copy(src_root: Path, dest_root: Path, repo: Path | None = None) -> None:
    if is_nested_link(dest_root):
        raise PHError(f"refusing to write through symlink or junction: {dest_root}")
    if repo is not None and not contained(repo, dest_root):
        raise PHError(f"refusing to write destination outside the repository: {dest_root}")
    reject_nested_links(src_root, label="apply source")
    if dest_root.exists():
        reject_nested_links(dest_root, label="apply destination")
    for src in iter_files(src_root):
        dest = dest_root / src.relative_to(src_root)
        if dest.exists() and dest.read_bytes() == src.read_bytes():
            continue
        copy_file_bytes(src, dest)


def ph_init_payload_files() -> list[Path]:
    """Files that must travel with a self-installed ph-init.

    Scaffold is included so the installed skill can initialize another repo.
    Scaffold itself must not contain ph-init, or install would recurse forever.
    Maintainer-only `scripts/build_scaffold.py` is excluded from the payload.
    """

    root = skill_root()
    files: list[Path] = []
    skill_md = root / "SKILL.md"
    script = root / "scripts" / "ph_init.py"
    if not skill_md.is_file() or not script.is_file():
        raise PHError("ph-init installation payload is incomplete")
    files.append(skill_md)
    zh_md = root / "SKILL.zh.md"
    if not zh_md.is_file():
        raise PHError("ph-init installation payload is missing the bilingual companion SKILL.zh.md")
    files.append(zh_md)
    files.append(script)
    for rel in ("release.json", "scripts/ph_release.py", "scripts/ph_merge_update.py", "scripts/ph_governance.py", "scripts/ph_layout.py"):
        resource = root / rel
        if not resource.is_file() or resource.is_symlink():
            raise PHError(f"ph-init payload missing regular file: {rel}")
        files.append(resource)
    migrations = root / "migrations"
    if not migrations.is_dir():
        raise PHError("ph-init migrations missing")
    reject_nested_links(migrations, label="ph-init migrations")
    files.extend(iter_files(migrations))
    references = root / "references"
    if references.is_dir():
        reject_nested_links(references, label="ph-init references")
        files.extend(iter_files(references))
    evals = root / "evals"
    if evals.is_dir():
        reject_nested_links(evals, label="ph-init evals")
        files.extend(iter_files(evals))
    assets = root / "assets" / "scaffold"
    if not assets.is_dir():
        raise PHError("ph-init assets/scaffold missing; installed copy is not self-contained")
    reject_nested_links(assets, label="ph-init assets/scaffold")
    files.extend(iter_files(assets))
    return files


def plan_payload_mirrors(report: Report, repo: Path) -> None:
    """Plan the Claude mirror for ph-init using the self-install payload only."""

    src_root = skill_root()
    files = ph_init_payload_files()
    rel = ".claude/skills/ph-init"
    plan_file_set_copy(
        report,
        repo,
        src_root,
        files,
        repo / rel,
        rel,
        "portable skill mirror",
    )


def assert_scaffold_not_recursive() -> None:
    nested = scaffold_root() / ".agents" / "skills" / "ph-init"
    if nested.exists():
        raise PHError(
            "scaffold contains .agents/skills/ph-init; refusing to copy a recursive installer"
        )


def plan_self_install(report: Report, repo: Path) -> None:
    dest_root = repo / ".agents" / "skills" / "ph-init"
    src_root = skill_root()
    if dest_root.resolve() == src_root.resolve():
        report.add("skip", ".agents/skills/ph-init", "already running from destination")
        return
    plan_file_set_copy(
        report,
        repo,
        src_root,
        ph_init_payload_files(),
        dest_root,
        ".agents/skills/ph-init",
        "self-install ph-init",
    )


def apply_self_install(repo: Path) -> None:
    dest_root = repo / ".agents" / "skills" / "ph-init"
    src_root = skill_root()
    if dest_root.resolve() == src_root.resolve():
        return
    for src in ph_init_payload_files():
        dest = dest_root / src.relative_to(src_root)
        if dest.exists() and dest.read_bytes() == src.read_bytes():
            continue
        copy_file_bytes(src, dest)


def plan_governance(report: Report, repo: Path, adopt: dict | None = None) -> None:
    """Plan the constitution materialization taken over from the retired
    spec-kit integration: the materialized constitution is created only when
    it is missing, and an existing one stays user-owned content."""

    import ph_governance

    if adopt is not None and ph_governance.CONSTITUTION in adopt.get("files", {}):
        report.add("skip", ph_governance.CONSTITUTION, "adopt plan supplies the reviewed constitution")
        return
    try:
        item = ph_governance.materialize_constitution(repo, apply=False)
    except (ph_governance.PHGovernanceError, ValueError, OSError) as exc:
        report.add("conflict", ph_governance.CONSTITUTION, f"constitution materialization blocked: {exc}")
        return
    if item["kind"] == "write":
        report.add("write", item["path"], item["reason"])
    else:
        report.add("skip" if item["kind"] == "skip" else "conflict", item["path"], item.get("reason", ""))


def apply_governance(report: Report, repo: Path) -> None:
    """Apply the constitution materialization after the scaffold deploy."""

    import ph_governance

    try:
        item = ph_governance.materialize_constitution(repo, apply=True)
    except (ph_governance.PHGovernanceError, ValueError, OSError) as exc:
        report.add("error", ph_governance.CONSTITUTION, f"constitution materialization failed: {exc}")
        return
    if item["kind"] == "conflict":
        report.add("conflict", item["path"], item.get("reason", ""))


def extra_skill_sources() -> dict[str, Path]:
    """The canonical scaffold skills installed alongside ph-init."""

    mapping: dict[str, Path] = {}
    for name in REQUIRED_SKILLS:
        if name != "ph-init":
            mapping[name] = scaffold_root() / ".agents" / "skills" / name
    for name, path in mapping.items():
        if not (path / "SKILL.md").is_file():
            raise PHError(f"missing canonical scaffold skill: {name}")
    return mapping


def scaffold_entries() -> list[tuple[Path, str]]:
    """Canonical files to materialize at the target repo root.

    Skills under `.agents/skills/ph-init` are excluded so init can overlay a
    single self-contained installer instead of a nested copy of itself.
    """

    root = scaffold_root()
    reject_nested_links(root, label="scaffold")
    entries: list[tuple[Path, str]] = []
    for src in iter_files(root):
        rel = posix_rel(src.relative_to(root))
        if rel.startswith(".agents/skills/ph-init/") or rel == ".agents/skills/ph-init":
            continue
        entries.append((src, rel))
    return entries


def manifest_bytes_for_mode(mode: str) -> bytes:
    """Render the repository-level adapter choice into the shared manifest."""

    data = read_json(scaffold_root() / ".agents" / "ph.json")
    data["adapter_mode"] = mode
    data["adapters"]["root_agents"]["mode"] = (
        "managed_copy" if mode == "portable" else "symlink"
    )
    data["adapters"]["claude_entry"]["mode"] = (
        "import_stub" if mode == "portable" else "symlink"
    )
    data["adapters"]["claude_skills"]["mode"] = (
        "mirror_tree" if mode == "portable" else "symlink"
    )
    validate_manifest(data)
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def is_docs_rel(rel: str) -> bool:
    """True for repository-relative files under docs/, not docs-prefixed names."""

    rel = posix_rel(rel)
    roots = ("docs", ".agents/project-harness/constraints", ".agents/project-harness/documents")
    return any(rel == root or rel.startswith(root + "/") for root in roots)


def docs_dest_issue(repo: Path, dest: Path) -> tuple[str, str] | None:
    """Reject links, escapes, junctions, hardlinks, and unsafe ancestors.

    Same-name regular files under docs/ are preserved elsewhere; this helper
    only names shapes init must not write through or treat as project docs.
    """

    try:
        rel = repo_rel(repo, dest)
    except ValueError:
        return ("destination is outside the repository", PROBLEM_OUTSIDE_REPO)
    if dest.is_symlink() or is_git_symlink_mode(repo, rel):
        return ("destination is a symlink", PROBLEM_DEST_SYMLINK)
    if is_disallowed_reparse(dest):
        return ("destination is a junction/reparse point", PROBLEM_DEST_JUNCTION)
    if dest.exists() and not dest.is_file():
        return ("destination is not a regular file", PROBLEM_NOT_REGULAR_FILE)
    try:
        if dest.exists() and dest.is_file() and dest.stat().st_nlink > 1:
            return ("hardlink is not allowed", PROBLEM_HARDLINK)
    except OSError:
        return ("destination is not a regular file", PROBLEM_NOT_REGULAR_FILE)
    repo_a = repo.absolute()
    cur = dest.absolute().parent
    while True:
        try:
            cur_rel = posix_rel(cur.relative_to(repo_a))
        except ValueError:
            return ("destination ancestor is outside the repository", PROBLEM_OUTSIDE_REPO)
        if cur == repo_a:
            break
        if cur.is_symlink() or is_disallowed_reparse(cur):
            return (f"ancestor {cur_rel} is a symlink or junction", PROBLEM_NESTED_LINK)
        if cur.exists() and not cur.is_dir():
            return (f"ancestor {cur_rel} is not a directory", PROBLEM_NOT_DIRECTORY)
        nxt = cur.parent
        if nxt == cur:
            return ("destination ancestor is outside the repository", PROBLEM_OUTSIDE_REPO)
        cur = nxt
    if not contained(repo, dest):
        return ("destination resolves outside the repository", PROBLEM_OUTSIDE_REPO)
    return None


def classify_docs_scaffold(repo: Path, dest: Path, data: bytes) -> tuple[str, str, str | None]:
    """Shared init plan/apply decision for one scaffold docs path."""

    issue = docs_dest_issue(repo, dest)
    if issue:
        suffix, problem = issue
        return ("conflict", f"scaffold: {suffix}", problem)
    if dest.exists():
        if dest.read_bytes() == data:
            return ("skip", "scaffold: identical", None)
        return ("skip", "scaffold: 保留待会话审阅", None)
    return ("write", "scaffold", None)


def safe_adopt_rel(value: object, ctx: str) -> str:
    """Repository-relative POSIX path check that allows scaffold-style unicode.

    The manifest REL_PATH intentionally stays ASCII-only for adapter consts;
    adopt plans legitimately carry Chinese docs paths, so only unsafe shapes
    are rejected here: absolute/drive/scheme heads, backslashes, NUL bytes,
    empty, dot, or parent components, and Windows-reserved characters
    (`<>:"|?*` per component; on NTFS `docs/a:b.md` is an alternate data
    stream, not a file).
    """

    if (
        not isinstance(value, str)
        or not value
        or value.startswith(("/", "~"))
        or "\\" in value
        or "\x00" in value
        or ADOPT_UNSAFE_HEAD.match(value)
    ):
        raise PHError(f"{ctx} is not a repository-relative POSIX path: {value!r}")
    for part in value.split("/"):
        if part in ("", ".", ".."):
            raise PHError(f"{ctx} is not a repository-relative POSIX path: {value!r}")
        if ADOPT_NTFS_RESERVED.intersection(part):
            raise PHError(f"{ctx} has a Windows-reserved character in path component {part!r}: {value!r}")
    return value


def adopt_plan_allows_file(rel: str) -> bool:
    """Adopt may write only the merged canonical and explicitly listed docs."""

    return (
        rel == ADOPT_CANONICAL
        or rel == ".agents/project-harness/constitution.md"
        or rel.startswith("docs/")
        or any(rel == root or rel.startswith(root + "/") for root in ADOPT_HOME_ROOTS)
    )


def load_adopt_plan(value: str, repo: Path) -> dict:
    """Read and structurally validate an adopt plan. Disk pins are checked later.

    The plan file must be a regular unshared file outside both the target
    repository and the ph-init distribution root, so an adopted write set can
    never be smuggled through repo content or the release tree.
    """

    path = Path(value)
    if not path.exists():
        raise PHError(f"missing adopt plan: {path}")
    if path.is_symlink() or is_disallowed_reparse(path) or not path.is_file():
        raise PHError(f"adopt plan must be a regular file, not a link or junction: {path}")
    if path.stat().st_nlink > 1:
        raise PHError(f"adopt plan must not be a hardlink: {path}")
    if contained(repo, path):
        raise PHError(f"adopt plan must live outside the target repository: {path}")
    if contained(skill_root(), path):
        raise PHError(f"adopt plan must not live inside the ph-init distribution root: {path}")
    data = read_json(path)
    _const(_need(data, "version", "adopt plan"), ADOPT_PLAN_VERSION, "adopt plan.version")
    declared = _need(data, "repo", "adopt plan")
    if (
        not isinstance(declared, str)
        or not Path(declared).is_absolute()
        or Path(declared).resolve() != repo
    ):
        raise PHError(f"adopt plan.repo must be the absolute target repository path, got {declared!r}")
    _const(_need(data, "release_version", "adopt plan"), RELEASE_VERSION, "adopt plan.release_version")
    sources = _need(data, "sources", "adopt plan")
    files = _need(data, "files", "adopt plan")
    if not isinstance(sources, dict) or not isinstance(files, dict):
        raise PHError("adopt plan sources and files must be objects")
    for rel, expected in sources.items():
        safe_adopt_rel(rel, "adopt plan source path")
        if expected is not None and (not isinstance(expected, str) or not SHA256_HEX.fullmatch(expected)):
            raise PHError(f"adopt plan source {rel} must be a lowercase SHA256 digest or null")
    for rel in (ADOPT_CANONICAL, *ADOPT_ROOT_ENTRIES):
        if rel not in sources:
            raise PHError(f"adopt plan sources must record rule entry {rel}")
    for rel, body in files.items():
        safe_adopt_rel(rel, "adopt plan file path")
        if not adopt_plan_allows_file(rel):
            raise PHError(
                f"adopt plan file is outside the allowed write set ({ADOPT_CANONICAL}, docs/** and the project-harness home roots): {rel}"
            )
        if not isinstance(body, str):
            raise PHError(f"adopt plan file {rel} must be a UTF-8 text body")
        try:
            body.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PHError(f"adopt plan file {rel} is not encodable as UTF-8: {exc}") from exc
        if rel == ".agents/project-harness/constitution.md":
            if ("<!-- PH-managed constitution override:" not in body
                    or "## 约束导航" not in body
                    or "[PROJECT_NAME]" in body or "[PRINCIPLE_" in body):
                raise PHError("adopt constitution must preserve principles and carry a materialized navigation zone")
        if rel not in sources:
            raise PHError(f"adopt plan file {rel} is not pinned in sources")
    canonical = files.get(ADOPT_CANONICAL)
    if not isinstance(canonical, str) or not canonical.strip():
        raise PHError(f"adopt plan files must carry a non-empty {ADOPT_CANONICAL}")
    return data


def check_adopt_sources(report: Report, repo: Path, plan: dict) -> bool:
    """Verify every pinned source against disk; report conflicts on drift.

    Called once after the plan is read (whole-set check) and again before any
    write, so any change between plan review and materialization blocks. Root
    entries may be direct relative symlinks to the canonical body only; every
    other source must be a safe regular file or absent.
    """

    ok = True
    for rel in sorted(plan["sources"]):
        expected = plan["sources"][rel]
        path = repo / rel
        digest: str | None = None
        if rel in ADOPT_ROOT_ENTRIES and path.is_symlink():
            raw = posix_rel(os.readlink(path))
            if raw != ADOPT_CANONICAL:
                report.add(
                    "conflict",
                    rel,
                    f"adopt source: root entry symlink must be exactly {ADOPT_CANONICAL}, got {raw!r}",
                    PROBLEM_SYMLINK_TARGET,
                )
                ok = False
                continue
            body = repo / ADOPT_CANONICAL
            if not body.is_file():
                report.add(
                    "conflict",
                    rel,
                    f"adopt source: symlink target {ADOPT_CANONICAL} is missing",
                    PROBLEM_SYMLINK_TARGET,
                )
                ok = False
                continue
            digest = sha256_file(body)
        else:
            issue = docs_dest_issue(repo, path)
            if issue is not None:
                suffix, problem = issue
                report.add("conflict", rel, f"adopt source: {suffix}", problem)
                ok = False
                continue
            if path.exists():
                digest = sha256_file(path)
        if digest != expected:
            want = "absent" if expected is None else expected
            got = "absent" if digest is None else digest
            report.add("conflict", rel, f"adopt source drift: plan pinned {want}, disk has {got}")
            ok = False
    return ok


def classify_adopt_file(repo: Path, rel: str, data: bytes) -> tuple[str, str, str | None]:
    """Shared adopt plan/apply decision for one plan-listed write."""

    issue = docs_dest_issue(repo, repo / rel)
    if issue is not None:
        suffix, problem = issue
        return ("conflict", f"adopt: {suffix}", problem)
    dest = repo / rel
    if dest.exists():
        if dest.read_bytes() == data:
            return ("skip", "adopt: identical", None)
        return ("write", "adopt: 合并写入（覆盖已确认来源）", None)
    return ("write", "adopt: 合并写入（新文件）", None)


def plan_adopt_files(report: Report, repo: Path, plan: dict) -> None:
    for rel in sorted(plan["files"]):
        data = plan["files"][rel].encode("utf-8")
        kind, reason, problem = classify_adopt_file(repo, rel, data)
        report.add(kind, rel, reason, problem)


def apply_adopt_files(repo: Path, plan: dict) -> None:
    for rel in sorted(plan["files"]):
        data = plan["files"][rel].encode("utf-8")
        kind, reason, _problem = classify_adopt_file(repo, rel, data)
        if kind == "skip":
            continue
        if kind != "write":
            raise PHError(f"refusing to write adopt file {rel}: {reason}")
        apply_file(repo / rel, data)


def semver_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def peek_installed_template_version(repo: Path) -> str | None:
    """Return a regular manifest's template_version, or None if absent/unreadable."""

    manifest = repo / ".agents" / "ph.json"
    if manifest.is_symlink() or is_disallowed_reparse(manifest) or not manifest.is_file():
        return None
    try:
        data = read_json(manifest)
    except PHError:
        return None
    value = data.get("template_version")
    if isinstance(value, str) and SEMVER.fullmatch(value):
        return value
    return None


def installed_same_version(repo: Path) -> bool:
    """True when a valid manifest declares this exact release version."""

    return peek_installed_template_version(repo) == RELEASE_VERSION


def refuse_init_on_version_mismatch(repo: Path) -> None:
    """Init is not an upgrader. A version-mismatched install stays on disk.

    The session that invoked init should continue from this package's
    merge-update steps. This function does not import or run that kernel.
    """

    installed = peek_installed_template_version(repo)
    if installed is None or installed == RELEASE_VERSION:
        return
    if semver_tuple(installed) > semver_tuple(RELEASE_VERSION):
        raise PHError(
            f"PH is already installed at template_version {installed!r}; "
            f"this package is {RELEASE_VERSION!r}. "
            "init --apply and --adopt-plan cannot overwrite or downgrade an installed repository. "
            "Use a matching or newer official package; do not downgrade."
        )
    inspect = f"python3 {skill_root()}/scripts/ph_merge_update.py inspect --repo {repo}"
    raise PHError(
        f"PH is already installed at template_version {installed!r}; "
        f"this package is {RELEASE_VERSION!r}. "
        "init --apply and --adopt-plan cannot overwrite or upgrade an installed repository. "
        "In this same session, prepare this release root, then run: "
        f"{inspect} "
        "and continue the ph-merge-update steps from that release root "
        "(semantic merge, verify, finalize). Do not open another skill."
    )


def classify_canonical_scaffold(repo: Path, dest: Path, data: bytes) -> tuple[str, str, str | None]:
    """Shared init decision for the scaffold canonical rule body.

    After a same-version install the canonical is user-owned prose: repeated
    init skips a customized body instead of conflicting, so customization
    survives idempotent re-runs. An uninstalled repo with a differing body
    still conflicts, with a pointer to the adopt flow.
    """

    if dest.is_symlink():
        return ("conflict", "scaffold: destination is a symlink", PROBLEM_DEST_SYMLINK)
    if is_disallowed_reparse(dest):
        return ("conflict", "scaffold: destination is a junction/reparse point", PROBLEM_DEST_JUNCTION)
    if dest.exists() and not dest.is_file():
        return ("conflict", "scaffold: destination is not a regular file", PROBLEM_NOT_REGULAR_FILE)
    if not dest.exists():
        return ("write", "scaffold", None)
    current = dest.read_bytes()
    if current == data:
        return ("skip", "scaffold: identical", None)
    if installed_same_version(repo):
        return ("skip", "scaffold: 已安装同版，保留定制 canonical", None)
    reason = "scaffold: existing file differs"
    if not (repo / ".agents" / "ph.json").exists():
        reason += "；未安装 PH：请由会话生成 adopt 计划（init --adopt-plan）整合既有规则"
    return ("conflict", reason, PROBLEM_EXISTING_DIFF)


def plan_scaffold(report: Report, repo: Path, mode: str, *, skip_rels: frozenset[str] = frozenset()) -> None:
    for src, rel in scaffold_entries():
        if rel == ".gitignore":
            continue  # gitignore is marker-idempotent, not a whole-file replace
        if rel in skip_rels:
            continue  # the adopt plan supplies the reviewed content for this path
        if rel == ".agents/ph.json" and mode == "auto":
            # The manifest persists only a concrete portable/symlink choice;
            # an unresolved auto dry run cannot render it without probing the
            # destination filesystem, so it is planned and written at apply.
            continue
        data = manifest_bytes_for_mode(mode) if rel == ".agents/ph.json" else src.read_bytes()
        dest = repo / rel
        if rel == ADOPT_CANONICAL:
            kind, reason, problem = classify_canonical_scaffold(repo, dest, data)
            report.add(kind, rel, reason, problem)
            continue
        if is_docs_rel(rel):
            kind, reason, problem = classify_docs_scaffold(repo, dest, data)
            report.add(kind, rel, reason, problem)
            continue
        plan_write_file(report, dest, data, "scaffold", repo)


def apply_scaffold(repo: Path, mode: str, *, skip_rels: frozenset[str] = frozenset()) -> None:
    for src, rel in scaffold_entries():
        if rel == ".gitignore":
            continue
        if rel in skip_rels:
            continue
        dest = repo / rel
        data = manifest_bytes_for_mode(mode) if rel == ".agents/ph.json" else src.read_bytes()
        if rel == ADOPT_CANONICAL:
            kind, reason, _problem = classify_canonical_scaffold(repo, dest, data)
            if kind == "skip":
                continue
            if kind != "write":
                raise PHError(f"refusing to write canonical {rel}: {reason}")
            apply_file(dest, data)
            continue
        if is_docs_rel(rel):
            kind, reason, _problem = classify_docs_scaffold(repo, dest, data)
            if kind == "skip":
                continue
            if kind != "write":
                raise PHError(f"refusing to write docs path {rel}: {reason}")
            apply_file(dest, data)
            continue
        if dest.exists() and dest.read_bytes() == data:
            continue
        apply_file(dest, data)


def plan_gitignore(report: Report, repo: Path) -> None:
    path = repo / ".gitignore"
    if path.is_symlink():
        report.add("conflict", ".gitignore", "gitignore is a symlink", PROBLEM_DEST_SYMLINK)
        return
    if not path.exists():
        report.add("write", ".gitignore", "create PH worktree marker")
        return
    text = path.read_text(encoding="utf-8")
    if gitignore_has_entry(text):
        report.add("skip", ".gitignore", "PH worktree marker present")
        return
    report.add("write", ".gitignore", "append PH worktree marker")


def apply_gitignore(repo: Path) -> None:
    path = repo / ".gitignore"
    if not path.exists():
        apply_file(path, PH_GITIGNORE_BLOCK.encode("utf-8"))
        return
    text = path.read_text(encoding="utf-8")
    if gitignore_has_entry(text):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    apply_file(path, (text + PH_GITIGNORE_BLOCK).encode("utf-8"))


def skill_names(repo: Path) -> list[str]:
    skills = repo / ".agents" / "skills"
    if not skills.is_dir():
        return []
    names = []
    for child in sorted(skills.iterdir()):
        if child.name.startswith("ph-") and (child / "SKILL.md").exists():
            names.append(child.name)
    return names


def adapter_skill_pairs(repo: Path) -> list[tuple[Path, Path, str]]:
    pairs = []
    for name in skill_names(repo):
        src = repo / ".agents" / "skills" / name
        dest = repo / ".claude" / "skills" / name
        pairs.append((src, dest, f".claude/skills/{name}"))
    return pairs


def plan_portable_skill_mirror(
    report: Report,
    repo: Path,
    src: Path,
    dest: Path,
    rel: str,
) -> None:
    """Plan one vendor mirror without traversing or replacing user-owned paths."""

    plan_file_set_copy(
        report,
        repo,
        src,
        iter_files(src),
        dest,
        rel,
        "portable skill mirror",
        repairable=True,
    )


def plan_portable_adapters(report: Report, repo: Path) -> None:
    canonical = repo / ".agents" / "AGENTS.md"
    if canonical.is_file():
        root_agents = repo / "AGENTS.md"
        if root_agents.exists() and not root_agents.is_symlink() and is_hardlink_to(root_agents, canonical):
            report.add(
                "conflict",
                "AGENTS.md",
                "portable root AGENTS copy: hardlink is not allowed",
                PROBLEM_HARDLINK,
            )
        else:
            plan_write_file(
                report,
                root_agents,
                canonical.read_bytes(),
                "portable root AGENTS copy",
                repo,
                repairable=True,
            )
        plan_write_file(
            report,
            repo / "CLAUDE.md",
            CLAUDE_STUB.encode("utf-8"),
            "portable CLAUDE stub",
            repo,
            repairable=True,
        )
    for src, dest, rel in adapter_skill_pairs(repo):
        plan_portable_skill_mirror(report, repo, src, dest, rel)


def apply_portable_adapters(repo: Path) -> None:
    canonical = repo / ".agents" / "AGENTS.md"
    if canonical.is_file():
        apply_file(repo / "AGENTS.md", canonical.read_bytes())
        apply_file(repo / "CLAUDE.md", CLAUDE_STUB.encode("utf-8"))
    for src, dest, _rel in adapter_skill_pairs(repo):
        apply_tree_copy(src, dest, repo)


def plan_one_symlink(report: Report, repo: Path, dest: Path, target: Path, reason: str) -> None:
    try:
        rel = repo_rel(repo, dest)
    except ValueError:
        report.add(
            "conflict",
            dest,
            f"{reason}: destination is outside the repository",
            PROBLEM_OUTSIDE_REPO,
        )
        return
    if not contained(repo, dest):
        report.add(
            "conflict",
            rel,
            f"{reason}: destination resolves outside the repository",
            PROBLEM_OUTSIDE_REPO,
        )
        return
    expected = expected_rel_link(dest, target)
    if dest.is_symlink():
        current = posix_rel(os.readlink(dest))
        if current == expected:
            report.add("skip", rel, f"{reason}: identical relative symlink")
        else:
            report.add(
                "conflict",
                rel,
                f"{reason}: symlink target {current!r} != {expected!r}",
                PROBLEM_SYMLINK_TARGET,
            )
        return
    if dest.exists():
        if is_git_symlink_mode(repo, rel):
            report.add(
                "conflict",
                rel,
                f"{reason}: git mode 120000 degenerated to path text",
                PROBLEM_GIT_SYMLINK,
            )
            return
        if is_hardlink_to(dest, target):
            report.add("conflict", rel, f"{reason}: hardlink is not allowed", PROBLEM_HARDLINK)
            return
        if is_disallowed_reparse(dest):
            report.add("conflict", rel, f"{reason}: junction is not allowed", PROBLEM_DEST_JUNCTION)
            return
        report.add("conflict", rel, f"{reason}: existing non-symlink path", PROBLEM_EXISTING_NON_SYMLINK)
        return
    report.add("write", rel, f"{reason}: relative symlink -> {expected}")


def git_core_symlinks(repo: Path) -> str | None:
    """Read the effective Git `core.symlinks` value. None means Git did not set it."""

    proc = run_git(repo, "config", "--get", "core.symlinks", check=False)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def symlink_blocker(repo: Path, dests: Iterable[Path] | None = None) -> str | None:
    """Return why real symlinks cannot be kept here, or None when they can.

    Why not auto-enable `core.symlinks`: PH must not raise repository or OS
    privileges. An explicit `false` is a human/policy choice and blocks the
    symlink mode. Capability is probed on the destination filesystem(s), not
    only the repo root, because adapters may sit on another mount. The probe
    never pre-creates a managed adapter path: a destination that does not
    exist yet is probed on the repository root instead, and every temporary
    probe directory is removed before returning.
    """

    configured = git_core_symlinks(repo)
    if configured is not None and configured.lower() in FALSE_CORE_SYMLINKS:
        return f"git core.symlinks is explicitly {configured}"
    probe_roots = [repo]
    if dests:
        for dest in dests:
            parent = dest if dest.is_dir() else dest.parent
            while not parent.exists() and parent != repo:
                parent = parent.parent
            probe_roots.append(parent)
    seen: set[Path] = set()
    for root in probe_roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        parent = resolved if resolved.is_dir() else resolved.parent
        try:
            with tempfile.TemporaryDirectory(prefix=".ph-link-probe-", dir=parent) as raw:
                base = Path(raw)
                for is_directory in (False, True):
                    target = base / ("directory" if is_directory else "file")
                    if is_directory:
                        target.mkdir()
                    else:
                        target.write_text("probe", encoding="utf-8")
                    link = base / f"{target.name}-link"
                    try:
                        link.symlink_to(target.name, target_is_directory=is_directory)
                    except (OSError, NotImplementedError) as exc:
                        return f"os.symlink failed on {parent}: {exc}"
                    if not link.is_symlink() or link.resolve() != target.resolve():
                        return "symlink probe did not produce a real filesystem symlink"
        except OSError as exc:
            return f"symlink probe failed on {parent}: {exc}"
    return None


def ensure_symlink_supported(repo: Path, dests: Iterable[Path] | None = None) -> None:
    """Fail closed when Git or the destination filesystem cannot keep real links."""

    reason = symlink_blocker(repo, dests)
    if reason is not None:
        raise PHError(
            f"symlink mode is unavailable here: {reason}; "
            "use portable mode or enable the OS/Git symlink capability "
            "without this tool changing it"
        )


def resolve_auto_mode(report: Report, repo: Path) -> str:
    """Pick the adapter mode for a fresh install: symlink first, portable fallback.

    Auto prefers symlink because it keeps a single source of truth. When the
    destination filesystems or an explicit `core.symlinks=false` cannot keep
    real links, the run downgrades to portable and the report item names the
    concrete blocker, so the choice is never a silent one.
    """

    reason = symlink_blocker(
        repo,
        [
            repo / "AGENTS.md",
            repo / "CLAUDE.md",
            repo / ".claude" / "skills",
        ],
    )
    if reason is None:
        return "symlink"
    report.add("ok", ".", f"auto mode: symlink unavailable ({reason}); installing portable")
    return "portable"


def apply_one_symlink(dest: Path, target: Path, repo: Path | None = None) -> None:
    if repo is not None and not contained(repo, dest):
        raise PHError(f"refusing to write destination outside the repository: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = expected_rel_link(dest, target)
    if dest.exists() and not dest.is_symlink() and dest.is_dir():
        raise PHError(f"refusing to replace directory with symlink: {dest}")
    if dest.is_symlink() or dest.exists():
        dest.unlink()
    dest.symlink_to(expected, target_is_directory=target.is_dir())


def plan_symlink_adapters(report: Report, repo: Path) -> None:
    canonical = repo / ".agents" / "AGENTS.md"
    plan_one_symlink(report, repo, repo / "AGENTS.md", canonical, "symlink root AGENTS")
    plan_one_symlink(report, repo, repo / "CLAUDE.md", canonical, "symlink CLAUDE")
    for src, dest, _rel in adapter_skill_pairs(repo):
        plan_one_symlink(report, repo, dest, src, "symlink skill mirror")


def apply_symlink_adapters(repo: Path) -> None:
    canonical = repo / ".agents" / "AGENTS.md"
    apply_one_symlink(repo / "AGENTS.md", canonical, repo)
    apply_one_symlink(repo / "CLAUDE.md", canonical, repo)
    for src, dest, _rel in adapter_skill_pairs(repo):
        apply_one_symlink(dest, src, repo)


def preflight_blocks(report: Report, repo: Path, action: str, *, adopt: bool = False) -> None:
    tracked = tracked_worktrees(repo)
    if tracked:
        report.add("block", ".worktrees", f"tracked worktree paths exist: {', '.join(tracked[:8])}")
    root_agents = repo / "AGENTS.md"
    canonical = repo / ".agents" / "AGENTS.md"
    if (
        action == "init"
        and not adopt
        and (root_agents.exists() or root_agents.is_symlink())
        and not canonical.exists()
    ):
        report.add(
            "block",
            "AGENTS.md",
            "migration blocked: root AGENTS.md exists but .agents/AGENTS.md does not; will not merge; "
            "由会话读取既有规则生成 adopt 计划后，用 init --adopt-plan 整合",
        )


def check_write_ancestor_conflicts(report: Report) -> None:
    """Conflict before apply when one planned write is an ancestor of another.

    docs/a and docs/a/b.md in the same write set cannot both materialize;
    without this gate apply would write half the set and then fail.
    """

    writes = {item.path for item in report.items if item.kind == "write"}
    for rel in sorted(writes):
        parts = rel.split("/")
        for i in range(1, len(parts)):
            ancestor = "/".join(parts[:i])
            if ancestor in writes:
                report.add(
                    "conflict",
                    rel,
                    f"planned write set uses {ancestor} as both file and directory",
                    PROBLEM_NOT_DIRECTORY,
                )
                break


def check_portable(report: Report, repo: Path) -> None:
    canonical = repo / ".agents" / "AGENTS.md"
    root = repo / "AGENTS.md"
    if not canonical.is_file():
        report.add("error", ".agents/AGENTS.md", "canonical missing")
        return
    digest = sha256_file(canonical)
    if root.is_symlink() or is_git_symlink_mode(repo, "AGENTS.md"):
        report.add("error", "AGENTS.md", "expected portable copy, found symlink")
    elif not root.is_file():
        report.add("error", "AGENTS.md", "missing portable root copy")
    elif is_hardlink_to(root, canonical):
        report.add("error", "AGENTS.md", "hardlink is not a portable managed copy")
    elif sha256_file(root) != digest:
        report.add("error", "AGENTS.md", f"SHA256 drift vs canonical {digest}")
    else:
        report.add("ok", "AGENTS.md", f"SHA256 {digest}")

    claude = repo / "CLAUDE.md"
    if claude.is_symlink() or is_git_symlink_mode(repo, "CLAUDE.md"):
        report.add("error", "CLAUDE.md", "expected portable stub, found symlink")
    elif not claude.is_file():
        report.add("error", "CLAUDE.md", "missing CLAUDE stub")
    elif claude.read_bytes() != CLAUDE_STUB.encode("utf-8"):
        report.add("error", "CLAUDE.md", "CLAUDE stub drift")
    else:
        report.add("ok", "CLAUDE.md", "stub @.agents/AGENTS.md")

    for src, dest, rel in adapter_skill_pairs(repo):
        if dest.is_symlink() or is_git_symlink_mode(repo, rel):
            report.add("error", rel, "expected portable mirror, found symlink")
            continue
        if not dest.exists():
            report.add("error", rel, "missing portable skill mirror")
            continue
        if is_hardlink_to(dest, src):
            report.add("error", rel, "hardlink is not a portable mirror")
            continue
        try:
            reject_nested_links(src, label=f"canonical skill {src.name}")
            reject_nested_links(dest, label=rel)
            src_files = {posix_rel(p.relative_to(src)): sha256_file(p) for p in iter_files(src)}
            dest_files = {posix_rel(p.relative_to(dest)): sha256_file(p) for p in iter_files(dest)}
        except PHError as exc:
            report.add("error", rel, str(exc), PROBLEM_NESTED_LINK)
            continue
        if src_files != dest_files:
            report.add("error", rel, "SHA256 drift vs canonical skill")
        else:
            report.add("ok", rel, "SHA256 match")


def check_one_symlink(report: Report, repo: Path, dest: Path, target: Path, rel: str) -> None:
    if is_disallowed_reparse(dest):
        report.add("error", rel, "junction/reparse point is not allowed")
        return
    if dest.exists() and not dest.is_symlink() and is_hardlink_to(dest, target):
        report.add("error", rel, "hardlink is not allowed")
        return
    if dest.exists() and not dest.is_symlink() and is_git_symlink_mode(repo, rel):
        report.add("error", rel, "git mode 120000 degenerated to path text in the worktree")
        return
    if not dest.is_symlink():
        report.add("error", rel, "missing relative symlink")
        return
    raw = os.readlink(dest)
    if os.path.isabs(raw):
        report.add("error", rel, f"symlink is absolute: {raw}")
        return
    expected = expected_rel_link(dest, target)
    if posix_rel(raw) != expected:
        report.add("error", rel, f"symlink {raw!r} != {expected!r}")
        return
    resolved = (dest.parent / raw).resolve()
    if not contained(repo, resolved):
        report.add("error", rel, f"symlink escapes repository: {resolved}")
        return
    if resolved != target.resolve():
        report.add("error", rel, f"symlink resolves to {resolved}, expected {target}")
        return
    report.add("ok", rel, f"relative symlink -> {expected}")


def check_symlink(report: Report, repo: Path) -> None:
    canonical = repo / ".agents" / "AGENTS.md"
    check_one_symlink(report, repo, repo / "AGENTS.md", canonical, "AGENTS.md")
    check_one_symlink(report, repo, repo / "CLAUDE.md", canonical, "CLAUDE.md")
    for src, dest, rel in adapter_skill_pairs(repo):
        check_one_symlink(report, repo, dest, src, rel)


def check_retired_codex_adapters(report: Report, repo: Path) -> None:
    for rel in (".codex", ".codex/skills"):
        root = repo / rel
        if not root.exists() and not root.is_symlink():
            return
        if root.is_symlink() or is_disallowed_reparse(root) or not root.is_dir():
            report.add("error", rel, "cannot safely inspect retired PH adapters; preserve this path for review")
            return
    for child in sorted(root.iterdir()):
        if child.name.startswith("ph-"):
            report.add(
                "error", repo_rel(repo, child),
                "retired Codex PH adapter is still live; review and archive it using the "
                "tool-neutral-adapters migration before checking again",
            )


def check_common(report: Report, repo: Path, *, candidate: dict | None = None) -> dict:
    data = load_repo_manifest(repo, candidate=candidate)
    check_retired_codex_adapters(report, repo)
    for name in REQUIRED_SKILLS:
        skill = repo / ".agents" / "skills" / name / "SKILL.md"
        if not skill.is_file():
            report.add("error", f".agents/skills/{name}/SKILL.md", "required skill missing")
        else:
            report.add("ok", f".agents/skills/{name}/SKILL.md", "present")
    # The self-developed runtime replaced the pinned spec-kit integration with
    # 1.2.3; its absence is a broken/unfinished install, not a scaffold drift.
    for rel in RUNTIME_MANAGED_MINIMUM:
        if not (repo / rel).is_file():
            report.add("error", rel, "self-developed runtime file missing")
        else:
            report.add("ok", rel, "present")
    import ph_governance

    try:
        governance = ph_governance.check_governance(repo)
        if not governance["ok"]:
            for problem in governance["problems"]:
                report.add("error", ph_governance.CONSTITUTION, problem)
    except (ph_governance.PHGovernanceError, ValueError, OSError) as exc:
        report.add("error", ph_governance.CONSTITUTION, str(exc))
    script = repo / ".agents" / "scripts" / "ph_worktree.py"
    if not script.is_file():
        report.add("error", ".agents/scripts/ph_worktree.py", "shared worktree script missing")
    else:
        report.add("ok", ".agents/scripts/ph_worktree.py", "present")
    human_script = repo / ".agents" / "scripts" / "ph_human.py"
    if not human_script.is_file():
        report.add("error", ".agents/scripts/ph_human.py", "shared human-companion script missing")
    else:
        report.add("ok", ".agents/scripts/ph_human.py", "present")
    gitignore = repo / ".gitignore"
    if not gitignore.is_file() or not gitignore_has_entry(gitignore.read_text(encoding="utf-8")):
        report.add("error", ".gitignore", "missing PH worktree marker")
    else:
        report.add("ok", ".gitignore", "PH worktree marker present")
    return data


def cmd_init(repo: Path, mode: str, apply: bool, adopt: dict | None = None) -> Report:
    assert_scaffold_not_recursive()
    report = Report("init", mode, apply)
    preflight_blocks(report, repo, "init", adopt=adopt is not None)
    if report.blocked:
        return report
    skip_rels = frozenset(adopt["files"]) if adopt is not None else frozenset()
    if adopt is not None:
        # Whole-set source pin check; drift blocks before any capability probe
        # or write planning, so an obsolete approved plan has no side effects.
        check_adopt_sources(report, repo, adopt)
        plan_adopt_files(report, repo, adopt)
        if report.blocked:
            return report
    if mode == "auto":
        plans = {choice: cmd_init(repo, choice, False, adopt=adopt) for choice in MODES}
        both_blocked = all(plan.blocked for plan in plans.values())
        if not apply or both_blocked:
            report.add(
                "ok", ".",
                "auto mode: symlink vs portable is resolved at apply time; dry run stays read-only",
            )
            for choice, plan in plans.items():
                for item in plan.items:
                    kind = item.kind
                    if not both_blocked and kind in {"error", "block", "conflict"}:
                        kind = "skip"
                    report.add(kind, item.path, f"if {choice}: {item.kind}: {item.reason}", item.problem)
            return report
        mode = resolve_auto_mode(report, repo)
        if plans[mode].blocked:
            report.mode = mode
            report.items.extend(plans[mode].items)
            return report
        applied = cmd_init(repo, mode, True, adopt=adopt)
        applied.items[:0] = report.items
        return applied
    plan_governance(report, repo, adopt=adopt)
    plan_scaffold(report, repo, mode, skip_rels=skip_rels)
    plan_self_install(report, repo)
    plan_gitignore(report, repo)
    if mode != "auto":
        plan_init_adapters(report, repo, mode, adopt=adopt)
    check_write_ancestor_conflicts(report)
    if apply and not report.blocked:
        if adopt is not None and not check_adopt_sources(report, repo, adopt):
            return report
        # Probe only after preflight passed and the complete plan has no
        # conflicts, so a doomed run never writes probe litter first.
        if mode == "symlink":
            try:
                ensure_symlink_supported(
                    repo,
                    [
                        repo / "AGENTS.md",
                        repo / "CLAUDE.md",
                        repo / ".claude" / "skills",
                    ],
                )
            except PHError as exc:
                report.add("block", ".", str(exc))
                return report
        # Governance last: the adopt plan and the scaffold deploy may bring a
        # reviewed constitution; only a still-missing one is materialized, and
        # an existing one stays user-owned content.
        if adopt is not None:
            apply_adopt_files(repo, adopt)
        apply_scaffold(repo, mode, skip_rels=skip_rels)
        apply_self_install(repo)
        apply_gitignore(repo)
        if mode == "portable":
            apply_portable_adapters(repo)
        else:
            apply_symlink_adapters(repo)
        apply_governance(report, repo)
    return report


def plan_init_adapters(report: Report, repo: Path, mode: str, adopt: dict | None = None) -> None:
    """Describe adapters using the layout init would produce, including new skills."""

    for rel in (".claude", ".claude/skills"):
        root = repo / rel
        if root.is_symlink() or is_disallowed_reparse(root) or (root.exists() and not root.is_dir()):
            report.add("conflict", rel, "skill adapter parent must be a real directory", PROBLEM_NOT_DIRECTORY)
            return
    virtual_skills = set(skill_names(repo)) | set(REQUIRED_SKILLS)
    if mode == "portable":
        if adopt is not None:
            # Adapters derive from the reviewed candidate canonical, not the
            # legacy bodies; pinned root entries may convert to copy/stub.
            plan_authorized_write(
                report,
                repo / "AGENTS.md",
                adopt["files"][ADOPT_CANONICAL].encode("utf-8"),
                "adopt portable root AGENTS copy",
                repo,
            )
            plan_authorized_write(
                report,
                repo / "CLAUDE.md",
                CLAUDE_STUB.encode("utf-8"),
                "adopt portable CLAUDE stub",
                repo,
            )
        else:
            canonical_src = scaffold_root() / ".agents" / "AGENTS.md"
            if (repo / ".agents" / "AGENTS.md").is_file():
                canonical_src = repo / ".agents" / "AGENTS.md"
            root_agents = repo / "AGENTS.md"
            canonical_in_repo = repo / ".agents" / "AGENTS.md"
            if (
                canonical_in_repo.is_file()
                and root_agents.exists()
                and not root_agents.is_symlink()
                and is_hardlink_to(root_agents, canonical_in_repo)
            ):
                report.add(
                    "conflict",
                    "AGENTS.md",
                    "portable root AGENTS copy: hardlink is not allowed",
                    PROBLEM_HARDLINK,
                )
            else:
                plan_write_file(report, root_agents, canonical_src.read_bytes(), "portable root AGENTS copy", repo)
            plan_write_file(report, repo / "CLAUDE.md", CLAUDE_STUB.encode("utf-8"), "portable CLAUDE stub", repo)
        extras = extra_skill_sources()
        for name in sorted(virtual_skills):
            if name == "ph-init":
                plan_payload_mirrors(report, repo)
                continue
            src = repo / ".agents" / "skills" / name
            if not src.exists():
                src = extras.get(name)
                if src is None:
                    continue
            rel = f".claude/skills/{name}"
            plan_portable_skill_mirror(report, repo, src, repo / rel, rel)
        return
    plan_one_symlink(report, repo, repo / "AGENTS.md", repo / ".agents" / "AGENTS.md", "symlink root AGENTS")
    plan_one_symlink(report, repo, repo / "CLAUDE.md", repo / ".agents" / "AGENTS.md", "symlink CLAUDE")
    for name in sorted(virtual_skills):
        src = repo / ".agents" / "skills" / name
        plan_one_symlink(report, repo, repo / ".claude" / "skills" / name, src, "symlink skill mirror")


def cmd_check(repo: Path, mode: str, *, candidate: dict | None = None) -> Report:
    report = Report("check", mode, False)
    preflight_blocks(report, repo, "check")
    try:
        check_common(report, repo, candidate=candidate)
    except PHError as exc:
        report.add("error", ".agents/ph.json", str(exc))
        return report
    if mode == "portable":
        check_portable(report, repo)
    else:
        check_symlink(report, repo)
    return report


def cmd_sync(repo: Path, mode: str, apply: bool, *, candidate: dict | None = None) -> Report:
    """Rewrite managed adapters from canonical. Does not merge or upgrade.

    Sync exists to repair drift of files PH owns. It still refuses to clobber
    unexpected symlink/hardlink/junction shapes — those stay conflicts so a
    human can decide. Canonical `.agents/**` and `docs/**` are not rewritten
    from the installer payload here.
    """

    report = Report("sync", mode, apply)
    preflight_blocks(report, repo, "sync")
    try:
        load_repo_manifest(repo, candidate=candidate)
    except PHError as exc:
        report.add("error", ".agents/ph.json", str(exc))
        return report
    if mode == "portable":
        # Sync repairs managed copies in place, so a drifted file is a write
        # rather than an init-time conflict.
        _plan_sync_portable(report, repo)
        if apply and not report.blocked:
            apply_portable_adapters(repo)
            apply_gitignore(repo)
    else:
        if apply:
            try:
                ensure_symlink_supported(
                    repo,
                    [
                        repo / "AGENTS.md",
                        repo / "CLAUDE.md",
                        repo / ".claude" / "skills",
                    ],
                )
            except PHError as exc:
                report.add("block", ".", str(exc))
                return report
        _plan_sync_symlink(report, repo)
        if apply and not report.blocked:
            apply_symlink_adapters(repo)
            apply_gitignore(repo)
    return report


def _replace_kind_conflict_with_write(report: Report) -> None:
    """Reclassify only existing-bytes content_drift as a sync write.

    Init treats any existing-file difference as conflict=do-not-touch. Sync
    is allowed to repair that one structured problem. Every other conflict
    — outside-repo, nested links, junctions, extras, unknown/missing
    problem types — stays blocking. Permission is never inferred from
    reason text.
    """

    kept: list[Item] = []
    for item in report.items:
        if item.kind == "conflict" and item.problem in SYNC_REPAIRABLE_PROBLEMS:
            kept.append(Item("write", item.path, f"sync repair: {item.reason}", item.problem))
        else:
            kept.append(item)
    report.items = kept


def _plan_sync_portable(report: Report, repo: Path) -> None:
    plan_portable_adapters(report, repo)
    _replace_kind_conflict_with_write(report)
    plan_gitignore(report, repo)


def _plan_sync_symlink(report: Report, repo: Path) -> None:
    # Missing links may be created, but unknown files/directories and wrong links
    # remain conflicts: replacing them could discard user-owned adapter content.
    plan_symlink_adapters(report, repo)
    plan_gitignore(report, repo)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ph_init.py",
        description="Initialize, check, or sync a Project Harness repository.",
    )
    parser.add_argument("action", choices=ACTIONS, help="init (default dry-run), check (read-only), sync (needs --apply to write)")
    parser.add_argument("--apply", action="store_true", help="Write planned changes. Required for sync writes; init is dry-run without it.")
    parser.add_argument(
        "--mode",
        choices=CLI_MODES,
        default=None,
        help=(
            "auto (default for a fresh init: symlink when the destination filesystem supports real links, else portable; "
            "resolved only at apply), portable, or symlink. Locked per repository."
        ),
    )
    parser.add_argument("--repo", default=None, help="Git repository root or a path inside it.")
    parser.add_argument(
        "--adopt-plan",
        default=None,
        metavar="PATH",
        help="Adopt an existing uninstalled repo from a session-generated merge plan (init only).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action == "check" and args.apply:
        parser.error("check is read-only; do not pass --apply")
    if args.adopt_plan and args.action != "init":
        parser.error("--adopt-plan only applies to init")
    try:
        repo = find_repo(args.repo)
        if args.action == "init":
            refuse_init_on_version_mismatch(repo)
        adopt = None
        if args.adopt_plan:
            adopt = load_adopt_plan(args.adopt_plan, repo)
            manifest = repo / ".agents" / "ph.json"
            if manifest.exists() or manifest.is_symlink():
                installed = peek_installed_template_version(repo) or "unknown"
                raise PHError(
                    "PH is already installed in this repository "
                    f"(template_version {installed!r} -> {RELEASE_VERSION!r}); "
                    "adopt cannot overwrite or upgrade it; use ph-merge-update"
                )
        mode = resolve_mode(repo, args.mode, args.action)
        if args.action == "init":
            report = cmd_init(repo, mode, args.apply, adopt=adopt)
        elif args.action == "check":
            report = cmd_check(repo, mode)
        else:
            report = cmd_sync(repo, mode, args.apply)
    except PHError as exc:
        sys.stderr.write(f"error={exc}\n")
        return 1
    sys.stdout.write(report.render())
    return 2 if report.blocked else 0


if __name__ == "__main__":
    # The kernel imports below (ph_governance, and through it ph_init and
    # ph_layout) would leave __pycache__ next to this script. In an installed
    # portable skill that pollutes the checked repository during a read-only
    # check. Only the script entry sets this; importing this module as a
    # library keeps no side effects.
    sys.dont_write_bytecode = True
    sys.exit(main())
