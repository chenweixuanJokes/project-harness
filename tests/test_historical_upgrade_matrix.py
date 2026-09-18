#!/usr/bin/env python3
"""Real-history upgrade matrix: every released PH layout upgrades to the current release.

Each case restores a genuine historical release tree from this repository's git
objects, installs it into an isolated git repo with that version's own
``ph_init.py``, adds explicit project customizations, then drives the CURRENT
``ph_merge_update.py`` flow (inspect -> semantic merge -> verify -> finalize
dry-run -> finalize --apply -> installed check -> repeated idempotent runs)
from an offline but genuinely verified prepared release, and asserts that every
piece of project content survives byte-for-byte. The one exception is the
1.1.12 question-spec overwrite: ``docs/约束规范/工程规范/对用户提问.md`` is
replaced wholesale with the release-root bytes (the pre-overwrite original is
first moved to the same recovery trash used for retired files) under the
``question-execution-contract`` item's explicit overwrite authorization, so
file-internal project question rules do not survive as effective rules; the
fixture asserts exactly that byte-identity and the recoverable backup. The
1.1.13 hop has two handlers: ``explicit-invocation-rules`` merges the
invoke-only-when-named gate into the eleven pre-1.1.13 skills (and clears the
auto-chaining wording), and ``intent-verify-skill`` installs the new
``ph-intent-verify`` skill from the release scaffold. The 1.1.14 hop has three
handlers: ``worktree-wip-confirm`` merges the unified WIP confirmation (fixed
two-option question asking whether to adopt a wip commit as the way out of the
current blocker - not a per-file content approval - actual question-tool call,
ordinary drift under the same blocker never re-asked while the authorization
is not long-term, refusal/cancel/no-answer stops) plus the conflict-recovery
contract (shared fixed conflict question with "保留现场，我解决后继续" /
"撤销这次合并" only, no stash/discard/ours/theirs/agent presets, keep stops
and waits, abort single-use, continue only on an explicit resolved-and-staged
continue request verified read-only, conflict state outranking the WIP flow)
into the two worktree skills
and the parallel-development spec, replaces the two worktree runtime scripts
byte-identically with the release root (unified ``wip`` subcommand with a
read-only dry-run, read-only ``doctor``, explicit ``recover``, ``redeliver``
and the enter expectation flags, while existing sessions stay untouched and
old sessions lacking new evidence block conservatively), and existing
confirmed WIP decisions are never re-asked;
``intent-verify-acceptance-contract`` merges the acceptance-contract semantics
(formal entry first per target user, remote-localhost honesty, no-entry/no
page plus separately-authorized auxiliary tools, per-client/per-role coverage,
async accept-vs-complete and file standards, deep links never proving
navigation-permission standards, user feedback separated from pre-check
evidence with contradiction clarification, read-only prepares no writes,
recovery re-verifies only affected points) into ``ph-intent-verify``; and
``sure-skill`` installs the new thirteenth skill ``ph-sure`` (wrap-up
verification of implemented / tested / merged / leftovers from current
evidence, no reliance on verbal claims, clean-tree-is-not-merged, no
target-branch guessing, no new commit/merge/publish/delete authorization)
from the release scaffold.

The semantic merge is performed by explicit per-migration-item handlers. A
migration item that is not in the handler registry fails the test instead of
being skipped, so a new migration hop cannot enter ``migrations/index.json``
silently. Sources for historical versions resolve dynamically from published
tags; only the three tag-less histories use their fixed commits.

Historical ``.codex/skills/ph-*`` adapters follow the 1.1.9 tool-neutral
contract: entries the official finalize engine can prove (managed relative
symlinks, byte-identical mirrors) stay in place for ``finalize --apply`` to
archive, while stale portable mirrors - unprovable here because the fixture
repos carry no pre-upgrade git commit - are archived by the semantic merge
itself, but only after each is proven an untouched historical-installer copy
of the pre-merge canonical skill. Non ``ph-*`` content is never touched.

The 1.1.9 repository rename is part of the contract under test. Downloads
use the renamed repository (``DOWNLOAD_SOURCE``), while receipts, release
metadata and ``SourceInfo.source`` keep the historical URL (``FIXED_SOURCE``)
as their permanent identity, so packages prepared by pre-rename downloaders
and update state written before the rename keep verifying. Skill names and
install paths (``.agents/skills/ph-*``, ``~/.agents/skills/ph-init``) are
not renamed. One regression drives the full two-mode upgrade from a package
prepared by the historical 1.1.8 downloader, which still addresses the old
URL.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
CURRENT = json.loads((REPO_ROOT / "release.json").read_text(encoding="utf-8"))["version"]
FIXED_SOURCE = "https://github.com/chenweixuanJokes/ph-init.git"
# The 1.1.9 repository rename: actual downloads (ls-remote / fetch) moved to
# the renamed project-harness repository, while FIXED_SOURCE stays the
# permanent identity recorded by release.json, receipts and SourceInfo.source,
# so pre-rename receipts and update state keep verifying unchanged.
RENAME_DOWNLOAD_SOURCE = "https://github.com/chenweixuanJokes/project-harness.git"
RENAME_OFFICIAL_NAME = "project-harness"
RENAME_LEGACY_OFFICIAL_NAME = "ph-init"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ph_release  # noqa: E402  (dev-tree module, used only to prepare the target offline)

TRASH_ROOT = Path.home() / "trash"
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_FILES = {".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# Historical versions without a published tag. These commits are the only
# recoverable source for those states; every other historical version must
# resolve to its v<version> tag or the matrix fails instead of skipping.
TAGLESS_SOURCES = {
    "1.0.0": (("six-skills", "c805d8fb34eb694443ce7c94eb2c1ecbc2f10a4d"),),
    "1.1.0": (
        ("legacy-names", "bd9bcdcf8cb8768d5b53c42a8b063531a188349e"),
        ("current-names", "e99911e4d53aefc657b4465747c51d09fad3dba6"),
    ),
    "1.1.2": (("ten-skills", "5fe2b2a5455964159daec32fbddd64082d8e83d9"),),
}
CORE_NON_INIT = (
    "ph-worktree-enter", "ph-worktree-exit",
    "ph-memory-capture", "ph-memory-archive", "ph-memory-ask",
)
BASE_SKILLS = ("ph-init",) + CORE_NON_INIT
OLD_ALIASES = ("ph-intent-capture", "ph-intent-plan", "ph-intent-abandon")
NEW_INTENT = ("ph-intent-new", "ph-intent-impl", "ph-intent-drop")
# Historical 1.1.10-1.1.12 releases ship exactly these eleven; 1.1.13 added
# ph-intent-verify, so the tagged 1.1.13 release ships the twelve. The
# unreleased 1.1.14 target adds ph-sure as the thirteenth; the historical
# twelve stay pinned to their actual values so new target skills never leak
# into historical fixture verification.
HISTORICAL_ELEVEN_SKILLS = BASE_SKILLS + NEW_INTENT + ("ph-merge-update", "ph-docs-sync")
HISTORICAL_TWELVE_SKILLS = HISTORICAL_ELEVEN_SKILLS + ("ph-intent-verify",)
TARGET_SKILLS = HISTORICAL_TWELVE_SKILLS + ("ph-sure",)
LAYOUT_SKILLS = {
    "twelve-skills": HISTORICAL_TWELVE_SKILLS,
    "eleven-skills": HISTORICAL_ELEVEN_SKILLS,
    "six-skills": BASE_SKILLS,
    "legacy-names": ("ph-init",) + CORE_NON_INIT + OLD_ALIASES,
    "current-names": ("ph-init",) + CORE_NON_INIT + NEW_INTENT,
    "ten-skills": ("ph-init",) + CORE_NON_INIT + NEW_INTENT + ("ph-merge-update",),
}
LAYOUT_PROFILE = {
    "twelve-skills": "1.1.0-current-names",
    "eleven-skills": "1.1.0-current-names",
    "six-skills": "1.0.0",
    "legacy-names": "1.1.0-legacy-names",
    "current-names": "1.1.0-current-names",
    "ten-skills": "1.1.0-current-names",
}
# In-project archive layout for retired codex adapters; mirrors the constants
# of the same name in scripts/ph_merge_update.py.
CODEX_ARCHIVE_SUFFIX = "-pre-update"
CODEX_ARCHIVE_CHILD = "codex-skills"

W = "docs/约束规范/工程规范"
PENDING_ROOTS = ("待办", "实施")
INTENT_KINDS = ("新特性", "问题记录")
LEGACY_COMPLETED = "已完成"
LEGACY_INPROGRESS = "进行中"
FEATURE_NAME = "INT-20260909-upgrade-matrix-feature.md"
STARTED_NAME = "INT-20260909-upgrade-matrix-started.md"
DELIVERED_NAME = "INT-20260909-upgrade-matrix-delivered.md"
DROPPED_NAME = "INT-20260909-upgrade-matrix-dropped.md"

AGENTS_TAIL = (
    "\n## 项目事实（升级矩阵样例）\n\n"
    "- 升级矩阵注入的项目事实：构建命令为 `make verify-matrix`。\n"
    "- 该段落必须在合并升级后逐字节保留。\n"
)
WIKI_APPEND = "\n升级矩阵注入的 Wiki 事实：本段必须在升级后逐字节保留。\n"
BACKEND_APPEND = "\n升级矩阵注入的后端约束：仅允许 PostgreSQL 16，禁用其它数据库。\n"
GOVERNANCE_APPEND = (
    "\n## 项目文档治理定制（升级矩阵）\n\n"
    "本节是项目自定义治理规则：文档同步修复前须抄送负责人。docs-sync-skill 合并规则索引时必须保留本节。\n"
)
INDEX_CUSTOM_BLOCK = (
    "\n## 项目索引定制（升级矩阵）\n\n"
    "本节是项目自定义索引说明：列出待办新特性时须同时标注访谈纪要链接。\n"
)
# A file-internal project question rule that conflicts with the 1.1.12
# contract: the question-execution-contract overwrite must replace it (with a
# recoverable backup) instead of preserving it as an effective rule.
QUESTION_APPEND = (
    "\n## 项目提问定制（升级矩阵）\n\n"
    "本节是项目自定义提问规则：向用户确认前必须逐字使用固定话术模板，禁止调用宿主结构化问答工具。"
    "1.1.12 覆盖策略授权本文件整文件替换：本节不得保留为仍生效的规则，覆盖前旧原文须备份可恢复。\n"
)
MIGRATION_DAY = "2026-09-09"
REASON_PENDING = "记录显示尚未启动实施"
REASON_STARTED = "记录显示计划获批、已启动实施"
REASON_DELIVERED = "1.1.2 起取消已完成目录，交付意图留在实施并在记录注明结果"


def semver_tuple(version: str) -> tuple:
    parts = version.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def command(*args, cwd=None, timeout=240):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout)


def must_run(*args, cwd=None, timeout=240):
    proc = command(*args, cwd=cwd, timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError(
            f"command failed ({proc.returncode}): {' '.join(map(str, args))}\n{proc.stderr or proc.stdout}"
        )
    return proc


def iter_regular_files(root: Path, *, strict: bool = False):
    """Yield regular files, skipping VCS/OS noise.

    ``strict`` refuses symlink nodes (managed PH trees must be link-free);
    non-strict walks simply skip links so digests stay usable in symlink mode.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name in SKIP_FILES or Path(name).suffix in SKIP_SUFFIXES:
                continue
            path = Path(dirpath) / name
            if path.is_symlink():
                if strict:
                    raise AssertionError(f"unexpected symlink in walked tree: {path}")
                continue
            yield path


def digest_tree(root: Path):
    """Map repo-relative path -> content digest, symlink nodes included.

    Symlinks record ``link:<target>`` so the read-only and idempotency checks
    stay sensitive to a link being added, removed, or repointed. VCS/OS noise
    (.git, __pycache__, *.pyc, .DS_Store) remains ignored.
    """
    entries: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for name in list(dirnames):
            child = current / name
            if name in SKIP_DIRS:
                dirnames.remove(name)
                continue
            if child.is_symlink():
                entries[child.relative_to(root).as_posix()] = f"link:{os.readlink(child)}"
                dirnames.remove(name)  # record the link node itself, never descend
        for name in sorted(filenames):
            if name in SKIP_FILES or Path(name).suffix in SKIP_SUFFIXES:
                continue
            path = current / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries[rel] = f"link:{os.readlink(path)}"
            else:
                entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def load_index(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format_version") != 1:
        raise AssertionError(f"illegal migrations index: {path}")
    return data["migrations"]


def independent_chain(index_path: Path, from_version: str, to_version: str):
    """Compute the migration chain without using any runtime helper."""
    by_from = {hop["from_version"]: hop for hop in load_index(index_path)}
    chain, cur, seen = [], from_version, set()
    while cur != to_version:
        if cur in seen or cur not in by_from:
            raise AssertionError(f"missing migration chain {from_version} -> {to_version} at {cur}")
        seen.add(cur)
        hop = by_from[cur]
        chain.append({
            "from": hop["from_version"], "to": hop["to_version"],
            "path": hop["path"], "items": list(hop["items"]),
        })
        cur = hop["to_version"]
    return chain


def historical_versions():
    versions = set()
    for hop in load_index(REPO_ROOT / "migrations" / "index.json"):
        versions.add(hop["from_version"])
        versions.add(hop["to_version"])
    return sorted((v for v in versions if semver_tuple(v) < semver_tuple(CURRENT)), key=semver_tuple)


def sources_for_version(version: str):
    if version in TAGLESS_SOURCES:
        return TAGLESS_SOURCES[version]
    tag = f"v{version}"
    proc = command("git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise AssertionError(
            f"historical version {version} has no published tag v{version} and no fixed commit source; "
            "the upgrade matrix refuses to fabricate history - publish the tag or register a fixed source"
        )
    layout = (
        "twelve-skills" if semver_tuple(version) >= (1, 1, 13)
        else "eleven-skills" if semver_tuple(version) >= (1, 1, 10)
        else "ten-skills"
    )
    return ((layout, tag),)


def build_cases():
    cases = []
    for version in historical_versions():
        for layout, ref in sources_for_version(version):
            for mode in ("portable", "symlink"):
                cases.append({"version": version, "layout": layout, "ref": ref, "mode": mode})
    return cases


def expected_schema_version(version: str):
    """The historical schema_version contract: absent from 1.1.8 onwards."""
    if semver_tuple(version) < (1, 1, 2):
        return version
    if semver_tuple(version) < (1, 1, 8):
        return "1.1.1"
    return None


def index_row(name: str, src_dir: str, dst_dir: str) -> str:
    return f"| [{name}]({name}) | 升级矩阵样例：自 {src_dir} 迁入 {dst_dir} |"


def migration_record(src_dir: str, dst_dir: str, reason: str) -> str:
    return (
        f"- {MIGRATION_DAY} 升级迁移：自 {src_dir} 迁入 {dst_dir}；"
        f"依据：{reason}。编号与历史正文保持不变。\n"
    )


def extract_git_tree(ref: str, dest: Path):
    """Restore a full tree from this repository's real git objects."""
    payload = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", ref],
        capture_output=True, timeout=240,
    )
    if payload.returncode != 0:
        raise AssertionError(f"git archive {ref} failed: {payload.stderr.decode('utf-8', 'replace')}")
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(payload.stdout), mode="r:") as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:  # Python < 3.12 has no filter argument
            tar.extractall(dest)


_PREPARED_MODULE_SEQ = 0
_PREPARED_PH_RELEASE: dict[Path, object] = {}


def _load_prepared_module(path: Path, prefix: str):
    """Load a module from a prepared release tree under a unique name."""
    global _PREPARED_MODULE_SEQ
    _PREPARED_MODULE_SEQ += 1
    name = f"{prefix}_{_PREPARED_MODULE_SEQ}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prepared_ph_release(root: Path):
    """The prepared release's own ph_release module (cached per root)."""
    key = root.resolve()
    module = _PREPARED_PH_RELEASE.get(key)
    if module is None:
        module = _load_prepared_module(key / "scripts" / "ph_release.py", "matrix_prepared_ph_release")
        _PREPARED_PH_RELEASE[key] = module
    return module


class LocalTransport(ph_release.GitTransport):
    """Offline transport: the fixed GitHub source is replaced by a local repo.

    ``expected`` pins the exact remote URL the caller must use. The current
    release downloads from ``DOWNLOAD_SOURCE`` (the repository was renamed to
    project-harness); a historical tool still addresses the old
    ``FIXED_SOURCE`` URL. Each transport instance accepts exactly one URL on
    purpose: tolerating both would mask a tool calling the wrong source.
    """

    def __init__(self, source: Path, expected: str | None = None):
        self.source = source
        self.expected = ph_release.DOWNLOAD_SOURCE if expected is None else expected

    def ls_remote_tags(self, source: str) -> str:
        assert source == self.expected, f"unexpected remote {source!r}, expected {self.expected!r}"
        return must_run("git", "ls-remote", "--tags", str(self.source)).stdout

    def fetch_commit(self, source: str, commit: str, dest: Path) -> None:
        assert source == self.expected, f"unexpected remote {source!r}, expected {self.expected!r}"
        must_run("git", "init", "--bare", "--template=", str(dest))
        must_run("git", "-C", str(dest), "fetch", "--no-tags", str(self.source), commit)


class PreparedTarget:
    """Current release prepared offline from a synthetic local tagged repo.

    The upgrade target is the *published* release: when tag v<CURRENT> exists
    the source tree is restored from that tag's git objects, so in-progress
    working-tree edits never masquerade as a released upgrade target. Only an
    unpublished version (release preparation before tagging) falls back to the
    working tree as the candidate release.

    ``from_prepared`` wraps a release tree another tool already prepared (the
    historical 1.1.8 downloader in the pre-rename regression): the new tool
    shipped inside that tree then drives the upgrade against its own receipt.
    """

    def __init__(self, workspace: Path):
        tag = f"v{CURRENT}"
        proc = command("git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}")
        source = workspace / "source"
        self.source = source
        if proc.returncode == 0 and proc.stdout.strip():
            extract_git_tree(tag, source)
            self.origin = f"published tag {tag}"
        else:
            self._copy_source(source)
            self.origin = "working tree (current version has no published tag yet)"
        must_run("git", "init", "-q", str(source))
        must_run("git", "-C", str(source), "add", ".")
        must_run("git", "-C", str(source), "-c", "user.name=PH fixture",
                 "-c", "user.email=fixture@example.com", "commit", "-qm", "fixture release")
        must_run("git", "-C", str(source), "tag", tag)
        prepared = ph_release.prepare_release(
            "latest", transport=LocalTransport(source),
            parent=workspace / "prepared", offer_support=False,
        )
        self._load(prepared)

    @classmethod
    def from_prepared(cls, prepared, origin: str) -> "PreparedTarget":
        self = cls.__new__(cls)
        self.origin = origin
        self._load(prepared)
        return self

    def _load(self, prepared):
        # Resolve once: ph_init resolves __file__, so an unresolved macOS
        # /var/... prefix would break relative_to against skill_root().
        self.root: Path = prepared.root.resolve()
        self.commit: str = prepared.commit
        self.version: str = prepared.version
        self.tag: str = prepared.tag
        self.index_path = self.root / "migrations" / "index.json"
        if self.version != CURRENT:
            raise AssertionError(f"prepared version {self.version} != release.json {CURRENT}")
        if not (self.root / ".ph-source.json").is_file():
            raise AssertionError("prepared release is missing .ph-source.json")
        # Load the prepared root's own installer module so target material comes
        # from the prepared release, never from the dev tree.
        module = _load_prepared_module(self.root / "scripts" / "ph_init.py", "matrix_prepared_ph_init")
        self.ph_init = module
        self.required_skills = tuple(module.REQUIRED_SKILLS)
        self.scaffold_dir = self.root / "assets" / "scaffold"
        self.payload_files = {p.relative_to(self.root).as_posix(): p for p in module.ph_init_payload_files()}
        self.scaffold_files = {
            p.relative_to(self.scaffold_dir).as_posix(): p for p in iter_regular_files(self.scaffold_dir, strict=True)
        }

    @staticmethod
    def _copy_source(source: Path):
        def ignore(directory, names):
            blocked = {"__pycache__", ".git", ".zcode", ".DS_Store"}
            if Path(directory) == REPO_ROOT:
                blocked |= {"AGENTS.md", "CLAUDE.md"}  # local maintainer symlinks, not release content
            return blocked

        shutil.copytree(REPO_ROOT, source, ignore=ignore)


class HistoricalTree:
    """A release tree restored from this repository's real git objects."""

    def __init__(self, workspace: Path, version: str, layout: str, ref: str):
        self.version, self.layout, self.ref = version, layout, ref
        self.root = workspace / "hist" / f"{version}-{layout}"
        if self.root.exists():
            raise AssertionError(f"historical tree already extracted: {self.root}")
        extract_git_tree(ref, self.root)
        self.scaffold_dir = self.root / "assets" / "scaffold"
        self._verify_genuine_history()

    def _verify_genuine_history(self):
        manifest = json.loads((self.scaffold_dir / ".agents" / "ph.json").read_text(encoding="utf-8"))
        if manifest["template_version"] != self.version:
            raise AssertionError(
                f"{self.ref} scaffold manifest is {manifest['template_version']}, expected {self.version}"
            )
        if manifest.get("schema_version") != expected_schema_version(self.version):
            raise AssertionError(f"{self.ref} schema_version {manifest.get('schema_version')!r} is not the historical value")
        # The scaffold never contains ph-init itself (init overlays the
        # self-contained installer), so compare against the layout minus it.
        expected = sorted(set(LAYOUT_SKILLS[self.layout]) - {"ph-init"})
        installed = sorted(
            p.name for p in (self.scaffold_dir / ".agents" / "skills").iterdir()
            if (p / "SKILL.md").is_file()
        )
        if installed != expected:
            raise AssertionError(f"{self.ref} scaffold skills {installed} != layout {expected}")
        if sorted(manifest["skills"]["required_names"]) != sorted(set(LAYOUT_SKILLS[self.layout])):
            raise AssertionError(f"{self.ref} manifest required_names does not match layout")
        release = self.root / "release.json"
        if semver_tuple(self.version) >= (1, 1, 1):
            data = json.loads(release.read_text(encoding="utf-8"))
            if data["version"] != self.version or data.get("schema_version") != expected_schema_version(self.version):
                raise AssertionError(f"{self.ref} release.json does not match the historical version")
        elif release.exists():
            raise AssertionError(f"{self.ref} unexpectedly carries release.json")
        roots = {p.name for p in (self.scaffold_dir / "docs" / "意图").iterdir() if p.is_dir()}
        if self.version == "1.0.0" or self.layout in ("legacy-names", "current-names"):
            expected_roots = {LEGACY_INPROGRESS, LEGACY_COMPLETED, "已废弃", "访谈纪要"}
        elif self.version == "1.1.1":
            expected_roots = {"待办", "实施", LEGACY_COMPLETED, "已废弃", "访谈纪要"}
        else:
            expected_roots = {"待办", "实施", "已废弃", "访谈纪要"}
        if roots != expected_roots:
            raise AssertionError(f"{self.ref} intent roots {sorted(roots)} != {sorted(expected_roots)}")


# ---------------------------------------------------------------------------
# Semantic merge engine: explicit handlers per migration item id.
#
# Handler scopes follow what each hop's migration document owns, evaluated as
# the final state (the migration README explicitly allows merging intermediate
# states that later hops supersede). A managed file is replaced with target
# content when the disk copy still matches the historical template, preserved
# untouched when it carries project customizations, and created when missing.
#
# The 1.1.9 tool-neutral item additionally retires the historical
# .codex/skills/ph-* vendor adapters: provably-managed entries stay in place
# for finalize --apply to archive, and only entries the official engine
# cannot prove are archived here (MergeEngine.retire_codex_mirrors).
# ---------------------------------------------------------------------------

ENGINE_ENSURE = {
    "current-branch-defaults": {
        # 1.1.11 release deltas this item owns: the branch-default rules in
        # ph-intent-impl and ph-worktree-enter (SKILL.md + evals samples),
        # plus the runtime-material version refs that follow the release
        # bump (scaffold ph-merge-update skill, root SKILL.md, release.json,
        # migrations register this item). Existing branches and worktrees
        # are never touched by this item.
        "skills": ("ph-intent-impl", "ph-worktree-enter", "ph-merge-update"),
        "payload": True,
    },
    "adopt-mode-docs": {
        # 1.1.11 doc-line delta this item owns: the adopt install command's
        # --mode example in the initialization guide gains the auto option
        # the CLI has accepted since 1.1.9. The line had stayed at the
        # 1.1.4-era two-option list; customized guides are preserved by
        # ensure_file instead of being overwritten.
        "docs": [f"{W}/初始化与文档补全.md"],
    },
    "intent-domain": {
        "docs": [
            "docs/意图/README.md", "docs/意图/_模板.md",
            "docs/意图/访谈纪要/README.md", "docs/意图/访谈纪要/_模板.md",
            "docs/意图/已废弃/README.md",
            f"{W}/README.md", f"{W}/文档治理.md", f"{W}/意图与访谈.md",
        ],
        "skills": CORE_NON_INIT + NEW_INTENT,
        "agents": True,
    },
    "intent-skill-names": {
        "docs": [f"{W}/意图与访谈.md"],
        "skills": NEW_INTENT,
        "retire": OLD_ALIASES,
        "agents": True,
    },
    "intent-lifecycle": {
        "docs": [
            "docs/意图/README.md", "docs/意图/已废弃/README.md", "docs/意图/访谈纪要/README.md",
            *[f"docs/意图/{root}/{kind}/README.md" for root in PENDING_ROOTS for kind in INTENT_KINDS],
            *[f"docs/意图/{root}/README.md" for root in PENDING_ROOTS],
        ],
        "agents": True,
    },
    "online-source": {"payload": True},
    "merge-update": {"docs": ["docs/README.md"], "skills": ("ph-merge-update",)},
    "schema-contract": {"schema_check": True},
    "project-content": {"payload": True, "agents": True},
    "intent-no-completed": {
        "docs": [
            "docs/意图/README.md", "docs/意图/_模板.md",
            "docs/意图/实施/新特性/README.md", "docs/意图/实施/问题记录/README.md",
            f"{W}/README.md", f"{W}/文档治理.md", f"{W}/意图与访谈.md",
        ],
        "skills": NEW_INTENT,
        "agents": True,
        "entries": LEGACY_COMPLETED,
    },
    "intent-legacy-inprogress": {
        "docs": ["docs/意图/README.md", f"{W}/README.md", f"{W}/文档治理.md", f"{W}/意图与访谈.md"],
        "skills": NEW_INTENT,
        "agents": True,
        "entries": LEGACY_INPROGRESS,
    },
    "init-docs-workflow": {"payload": True, "skills": ("ph-merge-update",)},
    "docs-guidance": {
        "docs": [
            "docs/README.md", "docs/约束规范/README.md",
            "docs/约束规范/前端规范/README.md", "docs/约束规范/前端规范/前端规范.md",
            "docs/约束规范/后端规范/README.md", "docs/约束规范/后端规范/后端规范.md",
            "docs/约束规范/测试规范/README.md", "docs/约束规范/测试规范/测试规范.md",
            "docs/约束规范/架构决策/README.md", "docs/约束规范/架构决策/_模板.md",
            f"{W}/README.md", f"{W}/Git与并行开发.md", f"{W}/初始化与文档补全.md",
            f"{W}/安全与配置.md", f"{W}/构建发布与运维.md", f"{W}/文档治理.md",
            "docs/项目Wiki/README.md", "docs/项目Wiki/功能地图.md", "docs/项目Wiki/开发指南.md",
            "docs/项目Wiki/架构地图/README.md", "docs/项目Wiki/架构地图/前端架构.md",
            "docs/项目Wiki/架构地图/后端架构.md", "docs/项目Wiki/架构地图/架构地图.md",
            "docs/项目Wiki/项目概述.md", "docs/项目Wiki/领域/README.md", "docs/项目Wiki/领域/_模板.md",
        ],
        "agents": True,
    },
    "docs-project-preserve": {"audit": True},
    "adopt-plan-init": {"payload": True},
    "adopt-existing-content": {
        "docs": [f"{W}/README.md", f"{W}/初始化与文档补全.md", f"{W}/文档治理.md", ".agents/archived/README.md"],
        "agents": True,
    },
    "init-report-coverage": {"docs": [f"{W}/初始化与文档补全.md"]},
    "init-unified-entry": {
        "payload": True, "skills": ("ph-merge-update",),
        "docs": ["docs/README.md", f"{W}/初始化与文档补全.md"], "agents": True,
    },
    "plain-user-questions": {
        "payload": True,
        "docs": [
            f"{W}/Git与并行开发.md", f"{W}/README.md", f"{W}/初始化与文档补全.md",
            f"{W}/对用户提问.md", f"{W}/意图与访谈.md", ".agents/memory/README.md",
        ],
        "skills": NEW_INTENT + ("ph-memory-capture", "ph-memory-ask",
                                "ph-worktree-enter", "ph-worktree-exit", "ph-merge-update"),
        "agents": True,
    },
    "prepare-star-fork": {"payload": True, "skills": ("ph-merge-update",)},
    "single-ph-version": {"schema": True, "payload": True, "skills": ("ph-merge-update",)},
    "worktree-auto-branch": {
        "payload": True, "skills": ("ph-worktree-enter", "ph-merge-update"),
        "docs": [f"{W}/Git与并行开发.md", f"{W}/对用户提问.md", "docs/项目Wiki/开发指南.md"],
        "agents": True,
    },
    "tool-neutral-adapters": {
        # 1.1.9 release deltas this item owns: the ph-init runtime materials
        # (SKILL.md/README/scripts/migrations/release.json move to 1.1.9),
        # ph.schema.json (adapters no longer require codex_skills), the
        # canonical AGENTS.md topology wording, and the ph-merge-update skill
        # docs that register the 1.1.9 hop and the three-tool topology. The
        # manifest's codex_skills adapter itself is removed only by finalize,
        # per the migration contract. "codex" drives the semantic retirement
        # of the historical .codex/skills/ph-* adapters.
        "payload": True, "skills": ("ph-merge-update",),
        "agents": True, "schema": True, "codex": True,
    },
    "repository-rename": {
        # 1.1.9 rename deltas this item owns: the ph-init runtime materials
        # (ph_release.py gains DOWNLOAD_SOURCE and the project-harness brand
        # constants, the root SKILL.md source wording, migrations register
        # this item) and the scaffold ph-merge-update skill's official-source
        # and brand guidance. Receipts, release.json.repository and
        # SourceInfo.source keep the historical FIXED_SOURCE URL; skill names
        # and install paths are not renamed. "rename" asserts exactly that
        # contract on the prepared target and the merged project.
        "payload": True, "skills": ("ph-merge-update",), "rename": True,
    },
    "docs-sync-skill": {
        # 1.1.10 release deltas this item owns: the new ph-docs-sync skill
        # (SKILL.md + evals), the canonical AGENTS.md skill table (eleven
        # names plus the ph-docs-sync row), the governance §6 rule index that
        # now registers the skill instead of denying one exists, the
        # completion guide's fixed-skill count and D58 conventions, the
        # scaffold ph-merge-update skill (version refs and the 1.1.10 item
        # section it registers), and the ph-init runtime materials (root
        # SKILL.md, release.json, migrations register this item). The upgrade
        # installs the skill and merges the rule indexes only; business
        # documents are never synced by this item - the matrix asserts the
        # fixture's wiki/backend bodies survive byte-for-byte.
        "payload": True, "skills": ("ph-docs-sync", "ph-merge-update"),
        "agents": True,
        "docs": [f"{W}/文档治理.md", f"{W}/初始化与文档补全.md"],
    },
    "question-execution-contract": {
        # 1.1.12 release deltas this item owns: the question spec rewritten as
        # an execution contract (whether to ask / channel and real tool calls /
        # question quality / answer states / recovery / boundary examples, no
        # numbered sections), the semantic reference updates in the specs,
        # memory README and canonical AGENTS that used to pin its numbered
        # sections, the gate-question wording in the skills citing it, and the
        # runtime-material version refs that follow the release bump. Answers
        # and authorizations already given to the project are never re-asked.
        # The question spec file itself carries this item's whole-file
        # overwrite authorization ("overwrite"): it is replaced with the
        # release-root bytes after a recoverable trash backup, never
        # semantically merged, so file-internal project question rules do not
        # survive as effective rules; conflicting rules in other files still
        # block, and the flow's write confirmation and file safety checks
        # still apply.
        "payload": True,
        "docs": [
            f"{W}/对用户提问.md", f"{W}/意图与访谈.md", f"{W}/初始化与文档补全.md",
            f"{W}/Git与并行开发.md", f"{W}/README.md", ".agents/memory/README.md",
        ],
        "overwrite": (f"{W}/对用户提问.md",),
        "skills": ("ph-intent-new", "ph-intent-impl", "ph-intent-drop",
                   "ph-memory-capture", "ph-memory-ask", "ph-worktree-exit",
                   "ph-merge-update"),
        "agents": True,
    },
    "explicit-invocation-rules": {
        # 1.1.13 release deltas this item owns: the invocation gate across the
        # eleven pre-1.1.13 skills (invoke only when the user explicitly names
        # the skill and asks for it; plain need descriptions, context mentions
        # and name discussions never trigger), the removal of auto-chaining
        # (enter no longer derives the exit-skill call, intent skills no
        # longer derive each other), the gate sentences in the canonical
        # AGENTS skill table and the intent/template/parallel-dev/init-guide
        # wording, the trigger positive/negative eval samples, and the
        # runtime-material version refs that follow the release bump. The
        # ph-init internal-step wording (an upgrade requested to ph-init is
        # executed by that session from the release-root merge-update steps)
        # is kept. Project-customized skill prose is preserved by ensure_file.
        "payload": True,
        "docs": [
            f"{W}/意图与访谈.md", f"{W}/Git与并行开发.md",
            f"{W}/初始化与文档补全.md", f"{W}/文档治理.md",
            f"{W}/README.md", "docs/意图/_模板.md",
        ],
        "skills": CORE_NON_INIT + NEW_INTENT + ("ph-merge-update", "ph-docs-sync"),
        "agents": True,
    },
    "intent-verify-skill": {
        # 1.1.13 release deltas this item owns: the new twelfth skill
        # ph-intent-verify (SKILL.md + evals) installed from the release
        # scaffold, its twelfth row in the canonical AGENTS skill table and
        # the intent spec's duty table, and the payload refresh. No business
        # intent, lifecycle status, directory or interview purpose is added;
        # a live same-name custom skill on an older project blocks the item
        # upstream (release_skill_name_conflicts) instead of being replaced.
        "payload": True,
        "docs": [f"{W}/意图与访谈.md"],
        "skills": ("ph-intent-verify",),
        "agents": True,
    },
    "worktree-wip-confirm": {
        # 1.1.14 release deltas this item owns: the unified WIP confirmation
        # across the three blocked sites (ph-worktree-enter's source tree,
        # ph-worktree-exit's task tree and the merge-target source tree): a
        # read-only listing of directory, branch, staged/unstaged/untracked
        # and the proposed wip message (explaining the situation and the
        # safety screening), then an actual question-tool call asking whether
        # to adopt the wip commit as the way out of this blocker - not a
        # per-file content approval - offering exactly "确认 WIP 并继续" /
        # "停止，保留现场"; refusal, cancel or no answer keeps the changes
        # and stops; ordinary content drift under the same blocker before the
        # commit runs is not re-asked, and the authorization is not long-term
        # (running the commit consumes it; every new blocking instance is
        # reconfirmed against the situation at hand). Exit no longer defaults
        # normal commits by the staged/unstaged classification. Also owned:
        # the conflict-recovery contract (real MERGE_HEAD/unmerged conflict
        # verified read-only first, the merge identity checked against the
        # session snapshot before continue and abort, the shared fixed
        # conflict question offering exactly "保留现场，我解决后继续" /
        # "撤销这次合并" with no stash/discard/ours/theirs/agent presets,
        # keep stops and waits, abort granted only by that option for that
        # one merge, continue only after an explicit resolved-and-staged
        # continue request verified read-only, conflict state outranking the
        # WIP flow). Also owned: the parallel-development spec's two WIP
        # paragraphs and the conflict question section, both skills' trigger
        # evals, the two worktree runtime scripts replaced byte-identically
        # with the release root (unified wip/doctor/recover/redeliver
        # subcommands and the enter expectation flags; existing sessions are
        # never rewritten and old sessions lacking new evidence block
        # conservatively), and the runtime-material version refs that follow
        # the release bump (scaffold ph-merge-update skill, root SKILL.md,
        # release.json, migrations register this item). Existing confirmed
        # WIP or cleanup decisions are never re-asked.
        "payload": True,
        "skills": ("ph-worktree-enter", "ph-worktree-exit", "ph-merge-update"),
        "docs": [f"{W}/Git与并行开发.md"],
        "agents": True,
    },
    "intent-verify-acceptance-contract": {
        # 1.1.14 release deltas this item owns: the ph-intent-verify skill's
        # acceptance-contract semantics - entry chosen per the intent's actual
        # target users with the formal entry first (web page, user-terminal
        # command, minimal API call; business users never handed only a curl
        # command), remote localhost/127.0.0.1 never claimed as user-side
        # address, opening distinguished as provided vs request-accepted vs
        # user-side-loaded, missing entries reported honestly as delivery
        # defects (no default demo pages; auxiliary tools only after separate
        # authorization as a separate task, never mocking business results,
        # real calls only), one independent result per round possibly spanning
        # steps without expanding the standard and written into the
        # user-visible message, per-client and per-role coverage, async
        # observed as accepted-or-completed per the standard with no invented
        # timeout failure, file standards actually obtaining the file, deep
        # links never proving navigation/permission standards, user feedback
        # (four states) separated from pre-check evidence with contradiction
        # clarification over object/environment/input/role and no fabricated
        # failures, docs verified against scripts/configs within
        # authorization, cache/log byproducts scoped to authorized operations
        # (read-only sessions start no writing preparations), records carrying
        # entry / role / known build (never fabricated) / pre-check evidence
        # and excluding secrets, sensitive inputs and credentialed URLs,
        # non-read-only writes limited to appending the target intent's 记录
        # section (read-only also prepares no writes), and recovery
        # re-verifying only affected points. The invocation gate is unchanged
        # by this item.
        "skills": ("ph-intent-verify",),
    },
    "sure-skill": {
        # 1.1.14 release deltas this item owns: the new thirteenth skill
        # ph-sure (SKILL.md + evals) installed from the release scaffold, its
        # thirteenth row in the canonical AGENTS.md skill table, the fixed
        # skill-count wording in the completion guide, and the runtime
        # material version refs that follow the release bump (release.json,
        # migrations register this item; the canonical AGENTS merge itself is
        # owned by worktree-wip-confirm's payload/agents refresh in the same
        # hop). The skill verifies the four wrap-up questions (implemented,
        # tested, merged, leftovers) from current evidence only: verbal
        # claims are re-verified, untested/failed/not-applicable are kept
        # apart, a clean worktree is not a merge, and the target branch is
        # never guessed; the check itself grants no commit/merge/publish/
        # delete authorization and never crosses the user acceptance gate.
        # No business intent, lifecycle status, directory or interview
        # purpose is added; a live same-name custom skill on an older project
        # blocks the item upstream (release_skill_name_conflicts) instead of
        # being replaced.
        "payload": True,
        "docs": [f"{W}/初始化与文档补全.md"],
        "skills": ("ph-sure",),
    },
}
SPECIAL_SCAFFOLD_RELS = {".gitignore", ".agents/ph.json", ".agents/ph.schema.json", ".agents/AGENTS.md"}


def rename_contract_facts(repo: Path, prepared) -> list[str]:
    """Assert the repository-rename contract; return per-case evidence lines.

    Source: the prepared release downloads from the renamed project-harness
    repository (DOWNLOAD_SOURCE) while its receipt, release.json.repository
    and SourceInfo.source keep the historical ph-init URL (FIXED_SOURCE), and
    the merged project carries the renamed runtime byte-for-byte. Brand: the
    vendor constants follow the new repository name. Old skill paths: the
    canonical skill directories keep their historical names - the repository
    rename must not rename installed skills. Every fact below is asserted,
    never assumed.
    """
    release_mod = prepared_ph_release(prepared.root)
    assert release_mod.FIXED_SOURCE == FIXED_SOURCE, (
        "receipt/metadata identity must keep the historical ph-init URL across the rename"
    )
    assert release_mod.DOWNLOAD_SOURCE == RENAME_DOWNLOAD_SOURCE, (
        "actual downloads must use the renamed project-harness repository"
    )
    assert release_mod.OFFICIAL_NAME == RENAME_OFFICIAL_NAME, (
        "brand constants must follow the renamed repository"
    )
    assert release_mod.LEGACY_OFFICIAL_NAME == RENAME_LEGACY_OFFICIAL_NAME, (
        "the pre-rename repository name must stay documented as the legacy brand"
    )
    receipt = json.loads((prepared.root / ".ph-source.json").read_text(encoding="utf-8"))
    assert receipt["source"] == FIXED_SOURCE, "prepared receipt lost the historical source URL"
    release_meta = json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))
    assert release_meta["repository"] == FIXED_SOURCE, "release metadata lost the historical source URL"
    project_release = repo / ".agents" / "skills" / "ph-init" / "scripts" / "ph_release.py"
    assert project_release.read_bytes() == (prepared.root / "scripts" / "ph_release.py").read_bytes(), (
        "the merged project's ph_release.py drifted from the prepared release"
    )
    skill = repo / ".agents" / "skills" / "ph-merge-update" / "SKILL.md"
    target_skill = prepared.scaffold_dir / ".agents" / "skills" / "ph-merge-update" / "SKILL.md"
    assert skill.read_bytes() == target_skill.read_bytes(), (
        "the merged ph-merge-update skill drifted from the prepared release"
    )
    assert RENAME_DOWNLOAD_SOURCE in skill.read_text(encoding="utf-8"), (
        "the ph-merge-update skill does not teach the renamed download source"
    )
    for name in ("ph-init", "ph-merge-update"):
        assert (repo / ".agents" / "skills" / name / "SKILL.md").is_file(), (
            f"the repository rename must not rename skill directories: {name}"
        )
    return [
        f"下载源已切换 {RENAME_DOWNLOAD_SOURCE}，receipt 与元数据保留 {FIXED_SOURCE}",
        f"品牌常量 OFFICIAL_NAME={RENAME_OFFICIAL_NAME}（旧名 {RENAME_LEGACY_OFFICIAL_NAME}），"
        "项目内 ph_release.py 与发行根逐字节一致",
        "旧 Skill 路径 .agents/skills/ph-init、.agents/skills/ph-merge-update 保持不变（已核对）",
    ]


class MergeEngine:
    """Agent-side semantic merge with an explicit template-drift policy.

    Customized scaffold files are preserved by default (``ensure_file``);
    the only exception is a migration item's explicit overwrite
    authorization (``overwrite_scaffold``), currently the 1.1.12 question
    spec, which backs the original up to the recovery trash before replacing
    it wholesale.
    """

    def __init__(self, repo: Path, case: dict, prepared: PreparedTarget, hist: HistoricalTree,
                 trash: Path, before_digests: dict[str, str]):
        self.repo, self.case, self.prepared, self.hist, self.trash = repo, case, prepared, hist, trash
        # Tree digest captured before the semantic merge started (repo-rel
        # path -> sha256, "link:<target>" for symlinks): the evidence source
        # for proving .codex mirrors untouched historical copies.
        self.before_digests = before_digests
        self.mutations: list[str] = []
        self.preserved: set[str] = set()   # customized files the engine chose not to touch
        self.rewritten: set[str] = set()   # index files the entry migration rewrote
        # Item-level overwrite policy outcome (1.1.12 question spec):
        # repo-rel path -> recoverable backup file in the engine trash.
        self.overwrite_backups: dict[str, Path] = {}
        # tool-neutral-adapters outcome: live .codex/skills/ph-* names at
        # handler time, which of them this engine archived itself, and which
        # provably-managed ones stayed in place for finalize --apply.
        self.codex_seen: list[str] | None = None
        self.codex_archived: list[str] = []
        self.codex_left_for_finalize: list[str] = []

    # -- primitives ---------------------------------------------------------

    def trash_move(self, path: Path) -> Path | None:
        if not path.exists() and not path.is_symlink():
            return None
        self.trash.mkdir(parents=True, exist_ok=True)
        dest = self.trash / f"{time.time_ns()}-{path.name}"
        path.rename(dest)
        return dest

    def ensure_file(self, repo_rel: str, target: Path, hist_path: Path | None) -> str:
        dest = self.repo / repo_rel
        if dest.is_symlink():
            raise AssertionError(f"refusing to write through symlink: {repo_rel}")
        target_bytes = target.read_bytes()
        if dest.exists():
            if not dest.is_file():
                raise AssertionError(f"managed path is not a regular file: {repo_rel}")
            disk = dest.read_bytes()
            if disk == target_bytes:
                return "ok"
            if hist_path is not None and hist_path.is_file() and hist_path.read_bytes() == disk:
                dest.write_bytes(target_bytes)
                self.mutations.append(f"replace {repo_rel} (template drift)")
                return "replace"
            self.preserved.add(repo_rel)
            return "preserved-custom"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(target_bytes)
        self.mutations.append(f"create {repo_rel}")
        return "create"

    def ensure_scaffold(self, rel: str) -> str:
        hist = self.hist.scaffold_dir / rel
        return self.ensure_file(rel, self.prepared.scaffold_dir / rel, hist if hist.exists() else None)

    def overwrite_scaffold(self, rel: str) -> str:
        """Replace one scaffold file wholesale under an item-level overwrite
        authorization (1.1.12 question spec).

        The pre-overwrite original first moves to the same recovery trash the
        engine already uses for retired files, so it stays recoverable; a
        file already at target bytes is left untouched, so a retry neither
        re-copies the file nor creates a duplicate backup nor clobbers the
        recorded original. Symlink and non-regular-file refusals match
        ``ensure_file``; a file replaced here is no longer reported as
        preserved.
        """
        dest = self.repo / rel
        if dest.is_symlink():
            raise AssertionError(f"refusing to write through symlink: {rel}")
        target_bytes = (self.prepared.scaffold_dir / rel).read_bytes()
        if dest.is_file() and dest.read_bytes() == target_bytes:
            return "ok"
        if dest.exists():
            if not dest.is_file():
                raise AssertionError(f"overwrite path is not a regular file: {rel}")
            backup = self.trash_move(dest)
            assert backup is not None, f"trash move failed for {rel}"
            self.overwrite_backups[rel] = backup
            self.mutations.append(f"backup+overwrite {rel} (item-level overwrite policy)")
        else:
            self.mutations.append(f"create {rel} (item-level overwrite policy)")
        self.preserved.discard(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(target_bytes)
        return "overwrite"

    def merge_agents(self):
        rel = ".agents/AGENTS.md"
        dest = self.repo / rel
        hist_bytes = (self.hist.scaffold_dir / rel).read_bytes()
        target_bytes = (self.prepared.scaffold_dir / rel).read_bytes()
        disk = dest.read_bytes()
        if disk == target_bytes or disk.startswith(target_bytes):
            return  # already at target, optionally with the preserved project tail
        if disk == hist_bytes:
            dest.write_bytes(target_bytes)
            self.mutations.append(f"replace {rel} (template drift)")
            return
        if not disk.startswith(hist_bytes):
            raise AssertionError(f"{rel} is neither the historical template nor template+custom tail")
        dest.write_bytes(target_bytes + disk[len(hist_bytes):])
        self.mutations.append(f"merge {rel} (PH body -> target, project tail preserved)")

    def _sync_tree(self, repo_dir: Path, target_dir: Path, hist_dir: Path | None) -> bool:
        """Bring one managed directory to target bytes, preserving customized files."""
        target_rels = {p.relative_to(target_dir).as_posix(): p for p in iter_regular_files(target_dir, strict=True)}
        changed = False
        for sub, target_path in sorted(target_rels.items()):
            rel = f"{repo_dir.relative_to(self.repo).as_posix()}/{sub}"
            hist_path = (hist_dir / sub) if (hist_dir is not None and (hist_dir / sub).exists()) else None
            outcome = self.ensure_file(rel, target_path, hist_path)
            changed = changed or outcome in ("create", "replace")
        if repo_dir.is_dir():
            for path in iter_regular_files(repo_dir, strict=True):
                sub = path.relative_to(repo_dir).as_posix()
                if sub in target_rels:
                    continue
                rel = f"{repo_dir.relative_to(self.repo).as_posix()}/{sub}"
                hist_path = (hist_dir / sub) if hist_dir is not None else None
                if hist_path is not None and hist_path.is_file() and hist_path.read_bytes() == path.read_bytes():
                    self.trash_move(path)
                    self.mutations.append(f"retire stale template file {rel}")
                    changed = True
                else:
                    self.preserved.add(rel)
        return changed

    def ensure_skill(self, name: str):
        if name == "ph-init":
            return self.ensure_payload()
        hist_dir = self.hist.scaffold_dir / ".agents" / "skills" / name
        changed = self._sync_tree(
            self.repo / ".agents" / "skills" / name,
            self.prepared.scaffold_dir / ".agents" / "skills" / name,
            hist_dir if hist_dir.exists() else None,
        )
        if changed:
            self.rebuild_mirrors(name)

    def ensure_payload(self):
        repo_skill = self.repo / ".agents" / "skills" / "ph-init"
        changed = False
        for rel, target_path in sorted(self.prepared.payload_files.items()):
            outcome = self.ensure_file(
                f".agents/skills/ph-init/{rel}", target_path,
                self.hist.root / rel if (self.hist.root / rel).exists() else None,
            )
            changed = changed or outcome in ("create", "replace")
        payload_rels = set(self.prepared.payload_files)
        if repo_skill.is_dir():
            for path in iter_regular_files(repo_skill, strict=True):
                rel = path.relative_to(repo_skill).as_posix()
                if rel in payload_rels:
                    continue
                hist_path = self.hist.root / rel
                if hist_path.is_file() and hist_path.read_bytes() == path.read_bytes():
                    self.trash_move(path)
                    self.mutations.append(f"retire stale template file .agents/skills/ph-init/{rel}")
                    changed = True
                else:
                    self.preserved.add(f".agents/skills/ph-init/{rel}")
        if changed:
            self.rebuild_mirrors("ph-init")

    def rebuild_mirrors(self, name: str):
        # The Claude mirror is a still-managed PH adapter: finalize's sync
        # rebuilds it from the canonical tree, so a stale copy is retired
        # here. The codex mirror stopped being a managed adapter in 1.1.9
        # (Codex/OpenCode read .agents natively): historical .codex/skills
        # entries are retired by the tool-neutral-adapters handler plus
        # finalize's codex retirement, never dropped here, so the pre-upgrade
        # copies stay recoverable inside the project archive.
        self.trash_move(self.repo / ".claude" / "skills" / name)

    def run_merge_tool(self, *args):
        """Run the prepared release's merge tool against this repo."""
        proc = must_run(sys.executable, str(self.prepared.root / "scripts" / "ph_merge_update.py"),
                        *args, "--repo", str(self.repo))
        return json.loads(proc.stdout)

    def codex_archive_base(self) -> Path:
        """The in-project codex archive base, by the official engine's rule.

        Mirrors ph_merge_update.codex_archive_base: an existing
        <date>-pre-update/codex-skills directory is reused - so finalize
        --apply archives into the same date dir this engine already used -
        and a fresh semantic archive starts today's UTC date.
        """
        archived = self.repo / ".agents" / "archived"
        if archived.is_dir() and not archived.is_symlink():
            for child in sorted(archived.iterdir()):
                if (child.name.endswith(CODEX_ARCHIVE_SUFFIX) and child.is_dir()
                        and not child.is_symlink()
                        and (child / CODEX_ARCHIVE_CHILD).is_dir()):
                    return child / CODEX_ARCHIVE_CHILD
        day = time.strftime("%Y-%m-%d", time.gmtime())
        return archived / f"{day}{CODEX_ARCHIVE_SUFFIX}" / CODEX_ARCHIVE_CHILD

    def retire_codex_mirrors(self):
        """Semantic-phase retirement of historical .codex/skills/ph-* adapters.

        The 1.1.9 contract splits the work: entries the official finalize
        engine can prove (managed relative symlinks, byte-identical mirrors)
        stay in place for finalize --apply to archive, and only entries it
        cannot prove are archived during the semantic merge. Here that
        unprovable set is exactly the stale portable mirrors - earlier items
        refreshed the canonical skills while these repos carry no pre-upgrade
        git commit - so each blocked mirror is first proven to be an
        untouched copy of the pre-merge canonical skill (the historical
        installer produced it that way and the fixture never customizes it)
        and only then moved into the project-local archive. Non ph-* entries
        are never touched.
        """
        inspected = self.run_merge_tool("inspect")
        blocked = inspected["codex_retirement"]["blocked"]
        retirable = sorted(item["name"] for item in inspected["codex_retirement"]["retirable"])
        base = None
        for item in blocked:
            name = item["name"]
            entry = self.repo / ".codex" / "skills" / name
            if entry.is_symlink() or not entry.is_dir():
                raise AssertionError(
                    f"blocked .codex/skills/{name} is not a portable mirror directory: {item['reason']}"
                )
            prefix = f".agents/skills/{name}/"
            pre_merge = {
                rel[len(prefix):]: digest
                for rel, digest in self.before_digests.items() if rel.startswith(prefix)
            }
            if not pre_merge:
                raise AssertionError(f"no pre-merge canonical snapshot for .codex/skills/{name}")
            mirror = {
                path.relative_to(entry).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in iter_regular_files(entry, strict=True)
            }
            if mirror != pre_merge:
                raise AssertionError(
                    f".codex/skills/{name} drifted from the pre-merge canonical skill "
                    f"(official classification: {item['reason']}); refusing to archive it as managed"
                )
            if base is None:
                base = self.codex_archive_base()
                base.mkdir(parents=True, exist_ok=True)
            dest = base / name
            if dest.exists() or dest.is_symlink():
                raise AssertionError(f"codex archive destination already exists: {dest}")
            entry.rename(dest)
            self.mutations.append(
                f"archive stale codex mirror .codex/skills/{name}"
                f" -> {dest.relative_to(self.repo).as_posix()}"
            )
        self.codex_seen = sorted({*retirable, *(item["name"] for item in blocked)})
        self.codex_archived = sorted(item["name"] for item in blocked)
        self.codex_left_for_finalize = retirable
        return self.codex_archived, retirable

    def retire_skill(self, name: str) -> list[str]:
        retired = []
        self.trash_move(self.repo / ".agents" / "skills" / name)
        retired.append(f".agents/skills/{name}")
        for vendor in (".claude", ".codex"):
            entry = self.repo / vendor / "skills" / name
            if entry.exists() or entry.is_symlink():
                self.trash_move(entry)
                retired.append(f"{vendor}/skills/{name}")
        if len(retired) > 1:
            self.mutations.append("retire legacy skill entries: " + ", ".join(retired))
        return retired

    def ensure_schema(self):
        self.ensure_scaffold(".agents/ph.schema.json")

    # -- intent entry migration --------------------------------------------

    @staticmethod
    def _drop_empty_row(text: str) -> str:
        return "".join(
            line for line in text.splitlines(keepends=True)
            if not line.strip().startswith("| （空）")
        )

    def _append_to_index(self, rel: str, addition: str):
        # Bring a missing or still-templated index to target bytes first, but
        # never re-classify an index this engine has already rewritten (the
        # row append and the carried custom tail land in the same file).
        if rel not in self.rewritten:
            self.ensure_scaffold(rel)
        self.rewritten.add(rel)
        readme = self.repo / rel
        text = self._drop_empty_row(readme.read_text(encoding="utf-8"))
        if not text.endswith("\n"):
            text += "\n"
        readme.write_text(text + addition, encoding="utf-8")

    def migrate_legacy_entries(self, legacy_root: str, decide):
        """Move business entries out of a legacy status dir, then retire the dir.

        ``decide(entry_text, kind)`` returns ``(target_root, reason)`` and must
        justify the classification from the entry's own recorded evidence.
        Returns None when the legacy dir is absent (item not applicable here).
        """
        legacy_dir = self.repo / "docs" / "意图" / legacy_root
        if not legacy_dir.is_dir():
            return None
        moved = []
        for kind in INTENT_KINDS:
            kind_dir = legacy_dir / kind
            if not kind_dir.is_dir():
                continue
            for path in sorted(kind_dir.iterdir()):
                if path.name == "README.md":
                    continue
                if not path.is_file():
                    raise AssertionError(f"unexpected non-file entry under legacy intent dir: {path}")
                text = path.read_text(encoding="utf-8")
                target_root, reason = decide(text, kind)
                old_dir, new_dir = f"{legacy_root}/{kind}", f"{target_root}/{kind}"
                old_line = f"status_dir: {old_dir}"
                if text.count(old_line) != 1:
                    raise AssertionError(f"cannot rewrite status_dir in {path}")
                dest = self.repo / "docs" / "意图" / new_dir / path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(
                    text.replace(old_line, f"status_dir: {new_dir}", 1)
                    + migration_record(old_dir, new_dir, reason),
                    encoding="utf-8",
                )
                self.trash_move(path)
                self._append_to_index(
                    f"docs/意图/{new_dir}/README.md",
                    index_row(path.name, old_dir, new_dir) + "\n",
                )
                moved.append((path.name, old_dir, new_dir))
                self.mutations.append(f"move intent entry {path.name}: {old_dir} -> {new_dir}")
            readme = kind_dir / "README.md"
            hist_readme = self.hist.scaffold_dir / "docs" / "意图" / legacy_root / kind / "README.md"
            if readme.is_file() and hist_readme.is_file():
                disk, hist_bytes = readme.read_bytes(), hist_readme.read_bytes()
                if disk != hist_bytes and disk.startswith(hist_bytes):
                    # A customized legacy index is carried into the pending
                    # index of the same kind, keeping the user's section bytes.
                    self._append_to_index(
                        f"docs/意图/待办/{kind}/README.md",
                        disk[len(hist_bytes):].decode("utf-8"),
                    )
                    self.mutations.append(f"carry custom index tail into 待办/{kind}/README.md")
        self.trash_move(legacy_dir)
        self.mutations.append(f"retire legacy intent dir {legacy_root}/")
        return moved


def _summarize(mutations):
    head = "; ".join(mutations[:6])
    more = f" (+{len(mutations) - 6} more)" if len(mutations) > 6 else ""
    return head + more


def _make_handler(item_id):
    spec = ENGINE_ENSURE[item_id]

    def handler(engine: MergeEngine):
        mark = len(engine.mutations)
        extra = []
        overwritten_rels = set(spec.get("overwrite", ()))
        for rel in spec.get("overwrite", ()):
            if rel not in engine.prepared.scaffold_files:
                raise AssertionError(f"overwrite scope references a scaffold file missing from the target: {rel}")
            engine.overwrite_scaffold(rel)
        for rel in spec.get("docs", []):
            if rel in overwritten_rels:
                continue
            if rel not in engine.prepared.scaffold_files:
                raise AssertionError(f"scope references a scaffold file missing from the target: {rel}")
            engine.ensure_scaffold(rel)
        for name in spec.get("skills", ()):
            engine.ensure_skill(name)
        for name in spec.get("retire", ()):
            extra.extend(engine.retire_skill(name))
        if spec.get("payload"):
            engine.ensure_payload()
        if spec.get("agents"):
            engine.merge_agents()
        if spec.get("schema"):
            engine.ensure_schema()
        codex_archived, codex_left = [], []
        if spec.get("codex"):
            # Later hops can change canonical skills after mirror
            # classification. Only skills a historical install could have
            # carried (and therefore could have mirrored into .codex) are
            # synced here: release-only skills introduced by the target hop
            # (ph-sure in 1.1.14) are installed by their own migration item
            # and have no historical mirror to classify.
            for name in HISTORICAL_TWELVE_SKILLS:
                if name != "ph-init":
                    engine.ensure_skill(name)
            engine.ensure_payload()
            codex_archived, codex_left = engine.retire_codex_mirrors()
        moved = None
        if spec.get("entries") == LEGACY_COMPLETED:
            moved = engine.migrate_legacy_entries(
                LEGACY_COMPLETED, lambda text, kind: ("实施", REASON_DELIVERED)
            )
        elif spec.get("entries") == LEGACY_INPROGRESS:
            def classify(text, kind):
                if "已启动实施" in text or "计划获批" in text:
                    return "实施", REASON_STARTED
                if "尚未启动实施" in text:
                    return "待办", REASON_PENDING
                raise AssertionError("insufficient evidence to classify a legacy in-progress entry")

            moved = engine.migrate_legacy_entries(LEGACY_INPROGRESS, classify)
        rename_facts: list[str] = []
        if spec.get("rename"):
            # Runs after this item's ensures: the assertions read the merged
            # project state the ensures (and earlier items) produced.
            rename_facts = rename_contract_facts(engine.repo, engine.prepared)
        mine = engine.mutations[mark:] + extra
        if spec.get("audit"):
            facts = engine.case["preserved_digests"]
            listing = ", ".join(f"{rel}:{digest[:10]}" for rel, digest in sorted(facts.items()))
            return "applied", (
                f"保留审阅已完成：升级前快照 {len(facts)} 份项目定制文件（{listing}）；"
                "矩阵在 finalize 后对全部原文逐字节核对。"
            )
        if spec.get("schema_check"):
            manifest = json.loads((engine.repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
            old_schema = manifest.get("schema_version")
            if old_schema is None:
                raise AssertionError("pre-1.1.8 manifest unexpectedly lacks schema_version before finalize")
            return "not_applicable", (
                f"带版本 Schema 中间态已被 {CURRENT} 单一版本最终态取代，无需单独落地；"
                f"已核对磁盘 ph.json 仍含 schema_version={old_schema}（保持原值，待 finalize 删除），"
                "ph.schema.json 的无版本 $id 由 single-ph-version 写入。"
            )
        if mine:
            detail = f"实际改动：{_summarize(mine)}"
            if spec.get("codex"):
                detail += (
                    f"；.codex 退役：语义归档 {len(codex_archived)} 项、"
                    f"{len(codex_left)} 项已证明受管留给 finalize --apply 归档"
                )
            if rename_facts:
                detail += "；仓库改名：" + "；".join(rename_facts)
            return "applied", detail
        # No mutation in this case: report concrete verified facts, never a blanket "applied".
        facts = []
        if "retire" in spec:
            live = [
                n for n in spec["retire"]
                if (engine.repo / ".agents" / "skills" / n).exists()
                or any((engine.repo / v / "skills" / n).exists() for v in (".claude", ".codex"))
            ]
            assert not live, f"legacy aliases still live but nothing retired them: {live}"
            facts.append(f"旧名 Skill 无残留（.agents/.claude/.codex 均无 {', '.join(spec['retire'])}，已核对）")
        if spec.get("entries"):
            legacy_dir = engine.repo / "docs" / "意图" / spec["entries"]
            assert not legacy_dir.exists(), f"{legacy_dir} still exists but the item reported no work"
            facts.append(f"docs/意图/{spec['entries']}/ 不存在，无存量条目需要迁移（已核对）")
        if spec.get("skills"):
            missing = [n for n in spec["skills"]
                       if not (engine.repo / ".agents" / "skills" / n / "SKILL.md").is_file()]
            assert not missing, f"scoped skills missing after merge: {missing}"
            facts.append(f"范围内 {len(spec['skills'])} 个 Skill 已在位且与发行根一致（已核对）")
        synced_docs = [rel for rel in spec.get("docs", []) if rel not in engine.preserved]
        preserved_docs = [rel for rel in spec.get("docs", []) if rel in engine.preserved]
        for rel in synced_docs:
            disk = engine.repo / rel
            target = engine.prepared.scaffold_dir / rel
            if not disk.read_bytes() == target.read_bytes():
                raise AssertionError(f"no mutation reported but scoped file drifted: {rel}")
        facts.append(f"范围内 {len(synced_docs)} 个文档已与发行根一致（已核对）")
        if preserved_docs:
            facts.append(
                f"范围内 {len(preserved_docs)} 个项目定制文档按策略保留原文"
                f"（{'、'.join(preserved_docs)}，已核对）"
            )
        if spec.get("payload"):
            facts.append("项目内 ph-init payload 已与发行根一致（先前项已刷新，已核对）")
        if spec.get("agents"):
            facts.append("canonical 已是目标模板+项目尾部（先前项已合并，已核对）")
        if spec.get("schema"):
            facts.append("ph.schema.json 已是无版本 $id 最终态（先前项已写入，已核对）")
        if spec.get("codex"):
            assert not codex_archived, "codex archives must show up as engine mutations"
            facts.append(
                f".codex/skills/ph-* 共 {len(codex_left)} 项经正式 inspect 分类均可证明受管，"
                "已原地保留交给 finalize --apply 归档（已核对）"
            )
        if rename_facts:
            facts.extend(rename_facts)
        return "not_applicable", f"本例无需改动：{'；'.join(facts)}"

    return handler


HANDLERS = {item: _make_handler(item) for item in ENGINE_ENSURE}


def check_scope_coverage(case, prepared: PreparedTarget, hist: HistoricalTree, item_ids):
    """Fail loudly when a scaffold delta is owned by no item of this chain."""
    ensure_rels, ensure_skills = set(), set()
    payload, agents, schema = False, False, False
    for item in item_ids:
        spec = ENGINE_ENSURE[item]
        ensure_rels.update(spec.get("docs", []))
        ensure_skills.update(spec.get("skills", ()))
        payload = payload or bool(spec.get("payload"))
        agents = agents or bool(spec.get("agents"))
        schema = schema or bool(spec.get("schema"))
    for rel, target_path in prepared.scaffold_files.items():
        if rel in SPECIAL_SCAFFOLD_RELS or rel.startswith(".agents/skills/"):
            continue
        hist_path = hist.scaffold_dir / rel
        if hist_path.is_file() and hist_path.read_bytes() == target_path.read_bytes():
            continue
        assert rel in ensure_rels, (
            f"scaffold delta {rel} (hist {hist.ref} -> target) is owned by no migration item "
            f"in the chain {case['version']} -> {CURRENT}"
        )
    hist_agents = (hist.scaffold_dir / ".agents" / "AGENTS.md").read_bytes()
    if hist_agents != (prepared.scaffold_dir / ".agents" / "AGENTS.md").read_bytes():
        assert agents, f"canonical AGENTS.md differs for {hist.ref} but no chain item owns the merge"
    hist_schema = (hist.scaffold_dir / ".agents" / "ph.schema.json").read_bytes()
    if hist_schema != (prepared.scaffold_dir / ".agents" / "ph.schema.json").read_bytes():
        assert schema, f"ph.schema.json differs for {hist.ref} but no chain item owns the update"
    payload_delta = False
    for rel, target_path in prepared.payload_files.items():
        hist_path = hist.root / rel
        if not hist_path.is_file() or hist_path.read_bytes() != target_path.read_bytes():
            payload_delta = True
            break
    if payload_delta:
        assert payload, f"ph-init payload differs for {hist.ref} but no chain item owns the refresh"
    for name in set(TARGET_SKILLS) - {"ph-init"}:
        target_dir = prepared.scaffold_dir / ".agents" / "skills" / name
        hist_dir = hist.scaffold_dir / ".agents" / "skills" / name
        target_files = {p.relative_to(target_dir).as_posix(): p.read_bytes()
                        for p in iter_regular_files(target_dir, strict=True)}
        hist_files = ({p.relative_to(hist_dir).as_posix(): p.read_bytes()
                       for p in iter_regular_files(hist_dir, strict=True)}
                      if hist_dir.is_dir() else {})
        if target_files != hist_files:
            assert name in ensure_skills, (
                f"skill {name} differs between {hist.ref} and the target but no chain item owns it"
            )


# ---------------------------------------------------------------------------
# Project customization fixture
# ---------------------------------------------------------------------------

FEATURE_ENTRY = """---
intent_id: "INT-20260909-upgrade-matrix-feature"
type: feature
status_dir: {status_dir}
created: "2026-09-09"
updated: "2026-09-09"
related: []
---

# 升级矩阵样例：未启动的新特性

业务正文保持原文：这条意图用于验证历史升级逐字节保留用户内容。

访谈纪要索引见 [访谈纪要 README](../../访谈纪要/README.md)。

## 记录

- {MIGRATION_DAY} 录入需求，尚未启动实施。
"""

STARTED_ENTRY = """---
intent_id: "INT-20260909-upgrade-matrix-started"
type: issue
status_dir: {status_dir}
created: "2026-09-09"
updated: "2026-09-09"
related: []
---

# 升级矩阵样例：已启动的问题修复

业务正文保持原文：这条意图带有明确的启动证据。

访谈纪要索引见 [访谈纪要 README](../../访谈纪要/README.md)。

## 记录

- {MIGRATION_DAY} 录入问题。
- {MIGRATION_DAY} 计划获批，已启动实施。
"""

DELIVERED_ENTRY = """---
intent_id: "INT-20260909-upgrade-matrix-delivered"
type: feature
status_dir: {status_dir}
created: "2026-09-08"
updated: "2026-09-08"
related: []
---

# 升级矩阵样例：已交付的新特性

业务正文保持原文：这条意图用于验证交付意图留在实施并记录结果。

## 记录

- 2026-09-08 交付完成，验收通过。
"""

DROPPED_ENTRY = """---
intent_id: "INT-20260909-upgrade-matrix-dropped"
type: feature
status_dir: 已废弃/新特性
created: "2026-09-08"
updated: "2026-09-08"
related: []
---

# 升级矩阵样例：已废弃的新特性

业务正文保持原文：已废弃条目在升级中一律不动。

## 记录

- 2026-09-08 明确放弃，保留原因与历史。
"""


def insert_project_customizations(repo: Path, case: dict) -> dict:
    """Add explicit project content to a freshly installed historical repo."""
    version, layout = case["version"], case["layout"]
    old_layout = version == "1.0.0" or layout in ("legacy-names", "current-names")
    active_feature = f"{LEGACY_INPROGRESS}/新特性" if old_layout else "待办/新特性"
    started_dir = f"{LEGACY_INPROGRESS}/问题记录" if old_layout else "实施/问题记录"
    delivered_dir = f"{LEGACY_COMPLETED}/新特性" if semver_tuple(version) <= (1, 1, 1) else "实施/新特性"
    case["old_layout"] = old_layout

    agents = repo / ".agents" / "AGENTS.md"
    agents.write_bytes(agents.read_bytes() + AGENTS_TAIL.encode("utf-8"))

    manifest_path = repo / ".agents" / "ph.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["project_note"] = "升级矩阵注入的项目备注：必须在 finalize 后逐字节保留。"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    wiki = repo / "docs" / "项目Wiki" / "项目概述.md"
    wiki.write_bytes(wiki.read_bytes() + WIKI_APPEND.encode("utf-8"))
    backend = repo / "docs" / "约束规范" / "后端规范" / "后端规范.md"
    backend.write_bytes(backend.read_bytes() + BACKEND_APPEND.encode("utf-8"))
    governance = repo / W / "文档治理.md"
    governance.write_bytes(governance.read_bytes() + GOVERNANCE_APPEND.encode("utf-8"))

    # File-internal project question rule for the 1.1.12 overwrite policy:
    # question-execution-contract must replace the file wholesale (with a
    # recoverable backup) instead of preserving this customization.
    # Historical installs before 1.1.6 carry no question spec at all; there
    # the chain creates the official file and there is nothing to overwrite.
    # From 1.1.12 the contract is already installed, the overwrite
    # authorization is not part of any later chain, and a 1.1.13-upgrade
    # project question rule is ordinary customization to preserve - so the
    # fixture only injects it while the overwrite hop is actually in the chain.
    question_rel = f"{W}/对用户提问.md"
    overwritten_bytes: dict[str, bytes] = {}
    question_spec = repo / question_rel
    if question_spec.is_file() and semver_tuple(version) < (1, 1, 12):
        question_spec.write_bytes(question_spec.read_bytes() + QUESTION_APPEND.encode("utf-8"))
        overwritten_bytes[question_rel] = question_spec.read_bytes()

    # User-owned content inside the retired .codex adapter area: non ph-*
    # entries must survive the 1.1.9 tool-neutral retirement byte-for-byte.
    codex_tool = repo / ".codex" / "skills" / "my-tool"
    codex_tool.mkdir(parents=True, exist_ok=True)
    codex_tool_skill = codex_tool / "SKILL.md"
    codex_tool_skill.write_text(
        "# my-tool\n\n升级矩阵注入的用户自有 Codex Skill：非 ph-* 条目必须在升级后逐字节保留。\n",
        encoding="utf-8",
    )

    index = repo / "docs" / "意图" / active_feature / "README.md"
    index.write_bytes(index.read_bytes() + INDEX_CUSTOM_BLOCK.encode("utf-8"))

    def write_entry(template, name, target_dir):
        path = repo / "docs" / "意图" / target_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.format(status_dir=target_dir, MIGRATION_DAY=MIGRATION_DAY), encoding="utf-8")
        return path

    feature = write_entry(FEATURE_ENTRY, FEATURE_NAME, active_feature)
    started = write_entry(STARTED_ENTRY, STARTED_NAME, started_dir)
    delivered = write_entry(DELIVERED_ENTRY, DELIVERED_NAME, delivered_dir)
    dropped = write_entry(DROPPED_ENTRY, DROPPED_NAME, "已废弃/新特性")

    preserved = {
        "docs/项目Wiki/项目概述.md": wiki.read_bytes(),
        "docs/约束规范/后端规范/后端规范.md": backend.read_bytes(),
        f"{W}/文档治理.md": governance.read_bytes(),
        ".codex/skills/my-tool/SKILL.md": codex_tool_skill.read_bytes(),
        f"docs/意图/已废弃/新特性/{DROPPED_NAME}": dropped.read_bytes(),
    }
    # An entry that the migration chain must relocate, with the classification
    # evidence the fixture wrote into its 记录 section.
    moved = []  # (name, src_dir, dst_dir, original_text, reason)
    if not old_layout:
        preserved[f"docs/意图/{active_feature}/{FEATURE_NAME}"] = feature.read_bytes()
        preserved[f"docs/意图/{started_dir}/{STARTED_NAME}"] = started.read_bytes()
        preserved[f"docs/意图/{active_feature}/README.md"] = index.read_bytes()
        if semver_tuple(version) > (1, 1, 1):
            preserved[f"docs/意图/{delivered_dir}/{DELIVERED_NAME}"] = delivered.read_bytes()
    if version == "1.1.1":
        moved.append((DELIVERED_NAME, delivered_dir, "实施/新特性", delivered.read_text(encoding="utf-8"), REASON_DELIVERED))
    if old_layout:
        moved.append((FEATURE_NAME, active_feature, "待办/新特性", feature.read_text(encoding="utf-8"), REASON_PENDING))
        moved.append((STARTED_NAME, started_dir, "实施/问题记录", started.read_text(encoding="utf-8"), REASON_STARTED))
        moved.append((DELIVERED_NAME, delivered_dir, "实施/新特性", delivered.read_text(encoding="utf-8"), REASON_DELIVERED))
    case["preserved_digests"] = {
        rel: hashlib.sha256(data).hexdigest() for rel, data in sorted(preserved.items())
    }
    # Scaffold paths this fixture actually customized. Legacy layouts carry
    # the pending index block via the entry migration instead of keeping the
    # file untouched, so their customized pending index is the rewritten one.
    customized_scaffold = {
        "docs/项目Wiki/项目概述.md",
        "docs/约束规范/后端规范/后端规范.md",
        f"{W}/文档治理.md",
    }
    if not old_layout:
        customized_scaffold.add("docs/意图/待办/新特性/README.md")
    if overwritten_bytes:
        customized_scaffold.add(question_rel)
    return {
        "preserved_bytes": preserved,
        "moved_entries": moved,
        "agents_tail": AGENTS_TAIL.encode("utf-8"),
        "customized_scaffold_paths": customized_scaffold,
        "overwritten_bytes": overwritten_bytes,
    }


# ---------------------------------------------------------------------------
# The matrix test
# ---------------------------------------------------------------------------

class HistoricalUpgradeMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trash_run = TRASH_ROOT / f"ph-upgrade-matrix-{os.getpid()}-{time.time_ns()}"
        cls.workspace = Path(tempfile.mkdtemp(prefix="ph-upgrade-matrix-"))
        cls.status_log: list[tuple[str, str, str, list[tuple[str, str]]]] = []
        try:
            cls.cases = build_cases()
            cls.hists: dict[str, HistoricalTree] = {}
            cls.prepared = PreparedTarget(cls.workspace)
            for case in cls.cases:
                key = f"{case['version']}-{case['layout']}"
                if key not in cls.hists:
                    cls.hists[key] = HistoricalTree(cls.workspace, case["version"], case["layout"], case["ref"])
            all_items = {
                item
                for case in cls.cases
                for hop in independent_chain(cls.prepared.index_path, case["version"], CURRENT)
                for item in hop["items"]
            }
            assert all_items, "matrix without any migration item would not test the merge"
            unknown = all_items - set(HANDLERS)
            if unknown:
                raise AssertionError(f"migration items without a semantic-merge handler: {sorted(unknown)}")
        except Exception:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        workspace = getattr(cls, "workspace", None)
        if workspace is None or not workspace.exists():
            return
        trash_run = getattr(cls, "trash_run", TRASH_ROOT / f"ph-upgrade-matrix-{os.getpid()}-{time.time_ns()}")
        trash_run.mkdir(parents=True, exist_ok=True)
        workspace.rename(trash_run / f"workspace-{time.time_ns()}")

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    # -- helpers ------------------------------------------------------------

    def merge_tool(self, prepared=None):
        return (prepared or self.prepared).root / "scripts" / "ph_merge_update.py"

    def run_tool(self, *args, repo: Path, prepared=None):
        proc = must_run(sys.executable, str(self.merge_tool(prepared)), *args, "--repo", str(repo))
        return json.loads(proc.stdout)

    def run_case(self, case, prepared=None, repo_suffix=""):
        """Drive one full historical upgrade against ``prepared`` (default: the
        current-tool target). ``repo_suffix`` keeps regression-driven repos
        apart from the main matrix repos at the same version."""
        version, layout, mode, ref = case["version"], case["layout"], case["mode"], case["ref"]
        prepared = prepared or self.prepared
        hist = self.hists[f"{version}-{layout}"]
        repo = self.workspace / "repos" / f"{version}-{layout}-{mode}{repo_suffix}"
        must_run("git", "init", "-q", str(repo))

        # 1) Real historical install with that version's own installer.
        proc = must_run(sys.executable, str(hist.root / "scripts" / "ph_init.py"),
                        "init", "--apply", "--mode", mode, "--repo", str(repo))
        self.assertIn("status=ok", proc.stdout, proc.stdout)
        check = must_run(sys.executable, str(hist.root / "scripts" / "ph_init.py"), "check", "--repo", str(repo))
        self.assertIn("status=ok", check.stdout, check.stdout)
        disk_manifest = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        self.assertEqual(disk_manifest["template_version"], version)
        self.assertEqual(disk_manifest.get("schema_version"), expected_schema_version(version))
        self.assertEqual(disk_manifest["adapter_mode"], mode)
        self.assertEqual(sorted(disk_manifest["skills"]["required_names"]), sorted(set(LAYOUT_SKILLS[layout])))
        live = sorted(p.name for p in (repo / ".agents" / "skills").iterdir() if p.is_dir())
        self.assertEqual(live, sorted(set(LAYOUT_SKILLS[layout])))

        # 2) Project customizations.
        custom = insert_project_customizations(repo, case)

        # 3) Current inspect: read-only, genuinely verified source, full chain.
        chain = independent_chain(prepared.index_path, version, CURRENT)
        item_ids = [i for hop in chain for i in hop["items"]]
        check_scope_coverage(case, prepared, hist, item_ids)
        before = digest_tree(repo)
        inspected = self.run_tool("inspect", repo=repo, prepared=prepared)
        self.assertEqual(digest_tree(repo), before, "inspect must not modify the repository")
        self.assertEqual(inspected["from"], version)
        self.assertEqual(inspected["to"], CURRENT)
        self.assertEqual(inspected["profile"], LAYOUT_PROFILE[layout])
        self.assertFalse(inspected["up_to_date"])
        self.assertEqual(inspected["mode"], mode)
        self.assertTrue(inspected["source"]["verified"], inspected["source"])
        self.assertTrue(inspected["can_finalize"])
        self.assertEqual(inspected["source"]["receipt"]["commit"], prepared.commit)
        self.assertEqual(inspected["source"]["receipt"]["tag"], f"v{CURRENT}")
        self.assertEqual(inspected["chain"], chain)
        self.assertEqual([i["id"] for i in inspected["suggested_state"]["items"]], item_ids)

        # 4) Semantic merge driven by explicit per-item handlers.
        engine = MergeEngine(repo, case, prepared, hist, self.trash_run, before)
        state = inspected["suggested_state"]
        for item in state["items"]:
            handler = HANDLERS.get(item["id"])
            if handler is None:
                self.fail(f"migration item {item['id']!r} has no semantic-merge handler")
            status, evidence = handler(engine)
            self.assertIn(status, ("applied", "not_applicable"), item["id"])
            self.assertTrue(evidence and evidence.strip(), f"empty evidence for {item['id']}")
            item["status"] = status
            item["evidence"] = evidence
        if "tool-neutral-adapters" in item_ids:
            self.assertIsNotNone(
                engine.codex_seen,
                "tool-neutral-adapters never classified the .codex/skills adapters",
            )
        else:
            # Tool-neutral 1.1.9+ installs carry no .codex adapters and the
            # item is not in their chain: nothing to classify.
            self.assertIsNone(engine.codex_seen)
        updates = repo / ".agents" / "updates" / CURRENT
        updates.mkdir(parents=True, exist_ok=True)
        (updates / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        applied = sum(1 for i in state["items"] if i["status"] == "applied")
        (updates / "report.md").write_text(
            f"# 升级矩阵：{version}/{layout}/{mode} -> {CURRENT}\n\n"
            f"- 离线验证源：{RENAME_DOWNLOAD_SOURCE} 下载、receipt 标识保留 {FIXED_SOURCE}，"
            f"tag v{CURRENT} commit {prepared.commit}\n"
            f"- 迁移链 {len(chain)} 跳，{len(item_ids)} 项；语义合并实际改动 {len(engine.mutations)} 处，"
            f"{applied} 项 applied、{len(item_ids) - applied} 项 not_applicable。\n"
            f"- 保留核对：AGENTS 项目事实段、ph.json project_note、Wiki/后端约束、意图正文与索引、已废弃条目。\n"
            f"- 验证：inspect 只读核对、verify、finalize dry-run、finalize --apply、已装 check、重复幂等。\n",
            encoding="utf-8",
        )

        # 5) verify, finalize dry-run (no writes), finalize --apply.
        type(self).status_log.append(
            (version, layout, mode, [(i["id"], i["status"]) for i in state["items"]])
        )
        self.run_tool("verify", repo=repo, prepared=prepared)
        before_finalize = digest_tree(repo)
        dry = self.run_tool("finalize", repo=repo, prepared=prepared)
        self.assertFalse(dry["apply"])
        self.assertFalse(dry["complete"])
        self.assertEqual(
            sorted(dry["codex_retirement"]["retirable"]), engine.codex_left_for_finalize,
            "finalize dry-run must report exactly the entries left for it to archive",
        )
        self.assertEqual(digest_tree(repo), before_finalize, "finalize dry-run must not write")
        applied_result = self.run_tool("finalize", "--apply", repo=repo, prepared=prepared)
        self.assertTrue(applied_result["complete"])
        self.assertEqual(applied_result["mode"], mode)
        self.assertEqual(applied_result["from"], version)
        retired_by_finalize = applied_result["retired_codex"]
        self.assertEqual(
            sorted(i["name"] for i in retired_by_finalize), engine.codex_left_for_finalize,
            "finalize must archive exactly the provably-managed entries the merge left live",
        )
        self.assertTrue(all(i["result"] == "archived" for i in retired_by_finalize))

        # 6) The upgraded repo's own installer must pass its check.
        installed = repo / ".agents" / "skills" / "ph-init" / "scripts" / "ph_init.py"
        proc = must_run(sys.executable, str(installed), "check", "--repo", str(repo))
        self.assertIn("status=ok", proc.stdout, proc.stdout)

        # 7) Byte-level preservation of every piece of project content.
        for rel, expected in custom["preserved_bytes"].items():
            path = repo / rel
            self.assertTrue(path.is_file(), f"preserved file missing after upgrade: {rel}")
            self.assertEqual(path.read_bytes(), expected, f"preserved content drifted: {rel}")
        # 7b) 1.1.12 question-spec overwrite: the file must be byte-identical
        # to the release root (no merged-in old wording or project rule), and
        # when the historical install carried the spec, its pre-overwrite
        # original must stay recoverable in the engine trash.
        question_rel = f"{W}/对用户提问.md"
        target_question = (prepared.scaffold_dir / question_rel).read_bytes()
        self.assertFalse((repo / question_rel).is_symlink())
        self.assertEqual(
            (repo / question_rel).read_bytes(), target_question,
            "the question spec must be byte-identical to the release root after the upgrade",
        )
        if custom["overwritten_bytes"]:
            original_question = custom["overwritten_bytes"][question_rel]
            self.assertNotEqual(original_question, target_question,
                                "fixture customization must differ from the target spec")
            self.assertNotIn(question_rel, engine.preserved,
                             "the overwritten question spec must not be reported as preserved")
            backup = engine.overwrite_backups.get(question_rel)
            self.assertIsNotNone(backup, "the overwritten question spec lost its pre-overwrite backup")
            self.assertTrue(backup.is_file(), f"backup missing after upgrade: {backup}")
            self.assertEqual(backup.read_bytes(), original_question,
                             "the backup must hold the pre-overwrite original bytes")
        else:
            self.assertNotIn(question_rel, engine.overwrite_backups,
                             "a never-customized question spec must not be backed up")
        for name, src_dir, dst_dir, original, reason in custom["moved_entries"]:
            path = repo / "docs" / "意图" / dst_dir / name
            self.assertTrue(path.is_file(), f"moved intent entry missing: {dst_dir}/{name}")
            expected = original.replace(
                f"status_dir: {src_dir}", f"status_dir: {dst_dir}", 1
            ) + migration_record(src_dir, dst_dir, reason)
            self.assertEqual(path.read_text(encoding="utf-8"), expected, f"moved entry drifted: {dst_dir}/{name}")
            self.assertFalse(
                (repo / "docs" / "意图" / src_dir / name).exists(),
                f"source entry not retired: {src_dir}/{name}",
            )
            row = index_row(name, src_dir, dst_dir)
            index = (repo / "docs" / "意图" / dst_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn(row, index, f"index row for moved entry missing: {dst_dir}/README.md")
            self.assertEqual(index.count(row), 1, f"index row not inserted exactly once: {dst_dir}/README.md")
        agents = repo / ".agents" / "AGENTS.md"
        target_agents = (prepared.scaffold_dir / ".agents" / "AGENTS.md").read_bytes()
        self.assertEqual(agents.read_bytes(), target_agents + custom["agents_tail"])

        # 8) Final structural state.
        manifest = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["template_version"], CURRENT)
        self.assertNotIn("schema_version", manifest)
        self.assertEqual(manifest["adapter_mode"], mode)
        self.assertEqual(manifest["skills"]["required_names"], list(prepared.required_skills))
        self.assertEqual(manifest["project_note"], "升级矩阵注入的项目备注：必须在 finalize 后逐字节保留。")
        schema = json.loads((repo / ".agents" / "ph.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            schema, json.loads((prepared.scaffold_dir / ".agents" / "ph.schema.json").read_text(encoding="utf-8"))
        )
        self.assertEqual(schema["$id"], "urn:ph:schema:project-harness")
        skills = sorted(p.name for p in (repo / ".agents" / "skills").iterdir() if p.is_dir())
        self.assertEqual(skills, sorted(set(prepared.required_skills)))
        for name in OLD_ALIASES:
            for base in (".agents", ".claude", ".codex"):
                self.assertFalse((repo / base / "skills" / name).exists(), f"legacy alias still live: {base}/skills/{name}")
        intent_roots = {p.name for p in (repo / "docs" / "意图").iterdir() if p.is_dir()}
        self.assertEqual(intent_roots, {"待办", "实施", "已废弃", "访谈纪要"})
        # Tool-neutral adapter topology (1.1.9): the canonical .agents tree,
        # the root entry, and the Claude adapters are all that remains. The
        # historical .codex/skills/ph-* mirrors are gone (archived in-project
        # below) and no .opencode vendor directory may appear either; the
        # adapter mode itself is preserved by the upgrade.
        self.assertNotIn("codex_skills", manifest["adapters"])
        root_entry, claude_entry = repo / "AGENTS.md", repo / "CLAUDE.md"
        if mode == "portable":
            self.assertEqual(root_entry.read_bytes(), agents.read_bytes(),
                             "root AGENTS.md must be the canonical managed copy")
            self.assertEqual(claude_entry.read_bytes(),
                             prepared.ph_init.CLAUDE_STUB.encode("utf-8"))
        else:
            self.assertEqual(os.readlink(root_entry), ".agents/AGENTS.md")
            self.assertEqual(os.readlink(claude_entry), ".agents/AGENTS.md")
        for name in prepared.required_skills:
            adapter = repo / ".claude" / "skills" / name
            if mode == "portable":
                self.assertTrue(adapter.is_dir() and not adapter.is_symlink(),
                                f"missing Claude skill mirror: {name}")
            else:
                self.assertTrue(adapter.is_symlink(), f"missing Claude skill symlink: {name}")
                self.assertEqual(os.readlink(adapter), f"../../.agents/skills/{name}")
        for vendor in (".codex", ".opencode"):
            vendor_skills = repo / vendor / "skills"
            live_vendor = (
                sorted(p.name for p in vendor_skills.iterdir() if p.name.startswith("ph-"))
                if vendor_skills.is_dir() else []
            )
            self.assertEqual(live_vendor, [], f"retired {vendor}/skills/ph-* adapters still live")
        # Every historical codex adapter the installer produced (minus the
        # alias retirements owned by the earlier intent-skill-names hop) ended
        # up archived exactly once, in a single <date>-pre-update/codex-skills
        # directory shared by the semantic merge and finalize --apply, with
        # the pre-upgrade bytes intact. The tool-neutral 1.1.9 installer
        # creates no .codex adapters at all, so those cases expect empty
        # retirement sets and no archive directory.
        expected_codex = set(LAYOUT_SKILLS[layout]) - set(OLD_ALIASES)
        if semver_tuple(version) >= (1, 1, 9):
            expected_codex = set()
        self.assertEqual(
            set(engine.codex_seen or ()), expected_codex,
            "unexpected set of live codex adapters at semantic-merge time",
        )
        archive_days = sorted(
            child for child in (repo / ".agents/archived").iterdir()
            if child.name.endswith(CODEX_ARCHIVE_SUFFIX) and (child / CODEX_ARCHIVE_CHILD).is_dir()
        )
        if expected_codex:
            self.assertEqual(len(archive_days), 1,
                             "semantic merge and finalize must share one archive date directory")
            codex_archive = archive_days[0] / CODEX_ARCHIVE_CHILD
            self.assertEqual({p.name for p in codex_archive.iterdir()}, set(engine.codex_seen))
            for name in engine.codex_seen:
                dest = codex_archive / name
                if mode == "portable":
                    prefix = f".agents/skills/{name}/"
                    expected_files = {
                        rel[len(prefix):]: digest
                        for rel, digest in before.items() if rel.startswith(prefix)
                    }
                    archived_files = {
                        path.relative_to(dest).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in iter_regular_files(dest, strict=True)
                    }
                    self.assertEqual(archived_files, expected_files,
                                     f"archived codex mirror drifted: {name}")
                else:
                    self.assertTrue(dest.is_file(), f"missing codex symlink record: {name}")
                    self.assertEqual(
                        dest.read_text(encoding="utf-8"),
                        f"retired codex symlink: .codex/skills/{name} -> ../../.agents/skills/{name}\n",
                    )
        else:
            self.assertEqual(archive_days, [],
                             "a tool-neutral 1.1.9+ history must not produce codex archives")
        # Scaffold drift is allowed on exactly two classes of files: the ones
        # this fixture customized, and the index READMEs the entry migration
        # rewrote. The engine's own preserved set must equal the customized
        # files it was actually asked to ensure - minus the question spec the
        # 1.1.12 overwrite policy replaced (it ends at target bytes, so it
        # shows no drift and must never appear as preserved) - anything more
        # or less fails.
        ensured_rels = set()
        for item_id in item_ids:
            ensured_rels.update(ENGINE_ENSURE[item_id].get("docs", []))
        expected_preserved = {
            rel for rel in custom["customized_scaffold_paths"] if rel in ensured_rels
        } - set(custom["overwritten_bytes"])
        self.assertEqual(
            {rel for rel in engine.preserved if not rel.startswith(".agents/skills/")},
            expected_preserved,
            "engine preserved an unexpected set of scaffold files",
        )
        self.assertEqual(
            {rel for rel in engine.preserved if rel.startswith(".agents/skills/")},
            set(),
            "the fixture customizes no skill or payload file",
        )
        allowed_drift = custom["customized_scaffold_paths"] | engine.rewritten
        for rel, target_path in prepared.scaffold_files.items():
            if rel in SPECIAL_SCAFFOLD_RELS or rel.startswith(".agents/skills/"):
                continue
            disk = repo / rel
            self.assertTrue(disk.is_file(), f"scaffold file missing after upgrade: {rel}")
            if disk.read_bytes() != target_path.read_bytes():
                self.assertIn(rel, allowed_drift, f"unexplained scaffold drift: {rel}")
        # The intent tree must be exactly target scaffold plus the sample entries.
        expected_extras = {
            f"待办/新特性/{FEATURE_NAME}",
            f"实施/问题记录/{STARTED_NAME}",
            f"实施/新特性/{DELIVERED_NAME}",
            f"已废弃/新特性/{DROPPED_NAME}",
        }
        intent_files = {
            p.relative_to(repo / "docs" / "意图").as_posix()
            for p in iter_regular_files(repo / "docs" / "意图")
        }
        scaffold_intent = {
            rel[len("docs/意图/"):] for rel in prepared.scaffold_files if rel.startswith("docs/意图/")
        }
        self.assertEqual(intent_files, scaffold_intent | expected_extras)
        pending_index_path = repo / "docs" / "意图" / "待办" / "新特性" / "README.md"
        block = INDEX_CUSTOM_BLOCK.encode("utf-8")
        final_index = pending_index_path.read_bytes()
        self.assertEqual(
            final_index.count(block), 1,
            "the custom index block must survive the upgrade exactly once",
        )
        if case["old_layout"]:
            # The entry migration appends the moved entry's row first and
            # carries the user's custom section last, so the final file must
            # end with the complete custom block bytes.
            self.assertTrue(
                final_index.endswith(block),
                "migrated pending index must end with the carried custom index block",
            )
        else:
            # Nothing moved into the pending index; the customized file must
            # stay byte-identical to what the fixture wrote.
            self.assertEqual(
                final_index,
                custom["preserved_bytes"]["docs/意图/待办/新特性/README.md"],
            )

        # 9) Idempotency: repeat inspect / verify / finalize --apply.
        after_upgrade = digest_tree(repo)
        reloaded = self.run_tool("inspect", repo=repo, prepared=prepared)
        self.assertTrue(reloaded["up_to_date"])
        self.assertIsNone(reloaded["suggested_state"])
        self.assertFalse(reloaded["can_finalize"])
        self.run_tool("verify", repo=repo, prepared=prepared)
        again = self.run_tool("finalize", "--apply", repo=repo, prepared=prepared)
        self.assertTrue(again["complete"])
        self.assertEqual(digest_tree(repo), after_upgrade, "repeated finalize must not change the repository")

        # 10) 1.1.12 overwrite retry: re-running the item handler on the
        # upgraded repo is a no-op - the file stays at target bytes, no new
        # backup copy appears, and the recoverable pre-overwrite original
        # keeps its bytes (a retry must not clobber the backup with newer
        # content).
        question_rel = f"{W}/对用户提问.md"
        backup_before = engine.overwrite_backups.get(question_rel)
        mutations_before = list(engine.mutations)
        trash_names = sorted(p.name for p in self.trash_run.glob(f"*-{Path(question_rel).name}"))
        HANDLERS["question-execution-contract"](engine)
        self.assertEqual(engine.mutations, mutations_before, "retry re-ran the overwrite")
        self.assertEqual(engine.overwrite_backups.get(question_rel), backup_before)
        self.assertEqual(
            sorted(p.name for p in self.trash_run.glob(f"*-{Path(question_rel).name}")),
            trash_names, "retry created a duplicate question-spec backup",
        )
        self.assertEqual((repo / question_rel).read_bytes(),
                         (prepared.scaffold_dir / question_rel).read_bytes())
        if backup_before is not None:
            self.assertTrue(backup_before.is_file(), "retry lost the recoverable original")
            self.assertEqual(backup_before.read_bytes(), custom["overwritten_bytes"][question_rel])

    # -- tests ---------------------------------------------------------------

    def test_historical_download_entries_handoff_to_current_tooling(self):
        receipt = json.loads((self.prepared.root / ".ph-source.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["version"], CURRENT)
        self.assertEqual(receipt["tag"], f"v{CURRENT}")
        self.assertEqual(receipt["commit"], self.prepared.commit)
        # The 1.1.9 rename keeps the historical URL as the receipt identity,
        # so receipts written before or after the rename stay interchangeable.
        self.assertEqual(receipt["source"], FIXED_SOURCE)

        seen = set()
        for case in self.cases:
            key = case["version"], case["layout"]
            if key in seen:
                continue
            seen.add(key)
            version, layout = key
            hist = self.hists[f"{version}-{layout}"]
            downloader = hist.root / "scripts" / "ph_release.py"
            with self.subTest(version=version, layout=layout):
                if semver_tuple(version) < (1, 1, 1):
                    self.assertFalse(
                        downloader.exists(),
                        "pre-1.1.1 histories must hand off because they have no online downloader",
                    )
                    continue

                self.assertTrue(downloader.is_file(), "historical online downloader is missing")
                name = f"matrix_ph_release_{version.replace('.', '_')}_{layout.replace('-', '_')}"
                spec = importlib.util.spec_from_file_location(name, downloader)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                try:
                    spec.loader.exec_module(module)
                    support = Mock(side_effect=AssertionError("unexpected GitHub support action"))
                    if hasattr(module, "offer_official_support"):
                        module.offer_official_support = support
                    kwargs = {
                        # Historical downloaders before the rename address
                        # the old FIXED_SOURCE URL; the renamed 1.1.9+ tools
                        # download from DOWNLOAD_SOURCE while receipts keep
                        # the FIXED_SOURCE identity.
                        "transport": LocalTransport(
                            self.prepared.source,
                            expected=(
                                module.FIXED_SOURCE
                                if semver_tuple(version) < (1, 1, 9)
                                else getattr(module, "DOWNLOAD_SOURCE", module.FIXED_SOURCE)
                            ),
                        ),
                        "parent": self.workspace / "historical-downloads" / f"{version}-{layout}",
                    }
                    if semver_tuple(version) >= (1, 1, 7):
                        kwargs["offer_support"] = False
                    if semver_tuple(version) < (1, 1, 8):
                        with self.assertRaisesRegex(module.PHReleaseError, "missing schema_version"):
                            module.prepare_release(CURRENT, **kwargs)
                    else:
                        downloaded = module.prepare_release(CURRENT, **kwargs)
                        self.assertEqual(downloaded.version, CURRENT)
                        self.assertEqual(downloaded.tag, f"v{CURRENT}")
                        self.assertEqual(downloaded.commit, self.prepared.commit)
                        # The pre-rename downloader records the historical URL
                        # in SourceInfo.source and the receipt; the new tool
                        # verifies that identity unchanged.
                        self.assertEqual(downloaded.source, module.FIXED_SOURCE)
                        downloaded_receipt = json.loads(
                            (downloaded.root / ".ph-source.json").read_text(encoding="utf-8")
                        )
                        self.assertEqual(downloaded_receipt["source"], module.FIXED_SOURCE)
                    support.assert_not_called()
                finally:
                    sys.modules.pop(name, None)

    def test_pre_rename_118_downloader_package_upgrades_both_modes(self):
        """The pre-rename 1.1.8 entry prepares the 1.1.9 package; the new tool upgrades.

        A 1.1.8 project's installed downloader still addresses the historical
        FIXED_SOURCE URL. The package it prepares must be complete (same
        commit, receipt keeping the historical source URL, the renamed new
        tool inside), and the new ph_merge_update shipped in that package must
        verify that receipt and drive the full upgrade in both adapter modes.
        This reuses the standard run_case chain end to end: install,
        customizations, semantic merge, verify, finalize, installed check and
        idempotency.
        """
        cases = [c for c in self.cases if c["version"] == "1.1.8"]
        self.assertTrue(cases, "the pre-rename 1.1.8 release must be part of the matrix")
        hist = self.hists["1.1.8-ten-skills"]
        name = "matrix_pre_rename_118_ph_release"
        spec = importlib.util.spec_from_file_location(name, hist.root / "scripts" / "ph_release.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            support = Mock(side_effect=AssertionError("unexpected GitHub support action"))
            if hasattr(module, "offer_official_support"):
                module.offer_official_support = support
            downloaded = module.prepare_release(
                CURRENT,
                transport=LocalTransport(self.prepared.source, expected=module.FIXED_SOURCE),
                parent=self.workspace / "pre-rename-118-handoff",
                offer_support=False,
            )
            support.assert_not_called()
        finally:
            sys.modules.pop(name, None)
        self.assertEqual(downloaded.version, CURRENT)
        self.assertEqual(downloaded.tag, f"v{CURRENT}")
        self.assertEqual(downloaded.commit, self.prepared.commit)
        self.assertEqual(downloaded.source, module.FIXED_SOURCE)
        old_target = PreparedTarget.from_prepared(
            downloaded, origin="prepared by the historical 1.1.8 downloader (old source URL)"
        )
        for case in cases:
            with self.subTest(mode=case["mode"]):
                self.run_case(case, prepared=old_target, repo_suffix="-pre-rename-handoff")

    def test_matrix_inventory_and_source_resolution(self):
        versions = historical_versions()
        self.assertTrue(versions, "migrations index lists no historical versions")
        self.assertIn(CURRENT, {hop["to_version"] for hop in load_index(REPO_ROOT / "migrations" / "index.json")})
        by_version = {}
        for case in self.cases:
            by_version.setdefault(case["version"], []).append(case)
        self.assertEqual(set(by_version), set(versions), "every pre-current index version needs at least one case")
        self.assertEqual(
            {c["layout"] for c in by_version.get("1.1.0", [])}, {"legacy-names", "current-names"},
            "1.1.0 must be covered in both historical layouts",
        )
        expected_count = 2 * sum(len(sources_for_version(v)) for v in versions)
        self.assertEqual(len(self.cases), expected_count)
        lines = [f"historical upgrade matrix -> {CURRENT} (target source: {self.prepared.origin})",
                 "version\tlayout\tmode\tsource\tchain items"]
        for case in self.cases:
            chain = independent_chain(self.prepared.index_path, case["version"], CURRENT)
            lines.append(f"{case['version']}\t{case['layout']}\t{case['mode']}\t{case['ref']}\t{len(chain)}")
        print("\n" + "\n".join(lines) + "\n")

    def test_every_historical_layout_upgrades_to_current(self):
        for case in self.cases:
            with self.subTest(version=case["version"], layout=case["layout"], mode=case["mode"]):
                self.run_case(case)
        # Per-case migration item outcomes: statuses must reflect the real
        # starting state, so both applied and not_applicable occur instead of
        # a blanket "everything applied". Unknown item ids already failed in
        # setUpClass; this only checks what the runs actually produced.
        self.assertTrue(self.status_log, "no case completed the semantic merge; see the case failures above")
        statuses = [status for _v, _l, _m, items in self.status_log for _i, status in items]
        self.assertIn("applied", statuses)
        self.assertIn("not_applicable", statuses)
        report = ["migration item outcomes per case:"]
        for version, layout, mode, items in self.status_log:
            report.append(f"{version}/{layout}/{mode}: " + ", ".join(f"{i}={s}" for i, s in items))
        print("\n" + "\n".join(report) + "\n")


if __name__ == "__main__":
    unittest.main()
