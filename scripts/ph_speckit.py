#!/usr/bin/env python3
"""PH ↔ GitHub Spec Kit integration: pinned fetch, official generation, ph-* install.

The ten spec-driven skills (analyze, checklist, clarify, constitution, converge,
implement, plan, specify, tasks, taskstoissues) and the `.specify/` shared
infrastructure are produced by the OFFICIAL Spec Kit generator at a pinned
release (release.json `speckit` section). PH never ships a hand-copied or
re-rendered variant of `templates/commands/*.md`: every install re-runs the
official `specify init` in an isolated staging directory, then renames the
generated `speckit-*` skills to `ph-*` with a consistent textual conversion and
records the upstream provenance for future upgrades.

Upgrades overwrite an existing differing file ONLY on a content-baseline
proof: every install records `speckit.files` in `.agents/ph.json` - the
sha256 of every managed file's bytes as installed - and a differing file is
rewritten only while its current bytes still match that baseline. Generation
markers alone (the manifest's speckit record or skills mapping, a skill's
own `x-ph-upstream` provenance block, the constitution override's PH
marker) never unlock an overwrite: they only say PH once wrote the path, not
that the user has not edited it since. Without a matching baseline the file
is a conflict, never a silent overwrite; identical bytes always skip, so an
unmodified healthy install is unaffected.

The `.specify/` directory keeps its upstream name and layout. Only the skill
directories, the skill `name` frontmatter, and inter-skill invocation
references (`$speckit-<core>`, `/speckit-<core>`, `/skill:speckit-<core>`) are
renamed to `ph-<core>`. Dot-form extension hook ids (`speckit.git.commit`)
and their hyphenated invocation spellings (`$speckit-git-commit`) belong to the
upstream extension ecosystem, not to the ten core skills, and are preserved.

No third-party imports: the official CLI itself is installed into an isolated
venv under a PH-owned cache directory, never into the global environment.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import ph_init
from ph_init import (
    PHError,
    contained,
    is_disallowed_reparse,
    posix_rel,
    read_json,
    sha256_bytes,
    sha256_file,
)


def is_hardlink(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and not path.is_symlink() and path.stat().st_nlink > 1
    except OSError:
        return False


def ensure_safe_write_dest(repo: Path, rel: str) -> Path:
    """Resolve a managed write destination, refusing links and escapes.

    Every component from the repository root down to the destination must be
    a real repository-local directory or file: a symlinked `.agents/skills` or
    `.specify` must never redirect a managed write outside the project, and a
    hardlinked managed file must never be written through. Used by every
    apply-time write path (install, constitution, manifest update).
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
            if cur.exists() and not cur.is_file():
                raise PHError(f"{rel}: destination is not a regular file")
            if is_hardlink(cur):
                raise PHError(f"{rel}: destination is a hardlink; refusing to write through it")
        else:
            if cur.exists() and (not cur.is_dir() or is_disallowed_reparse(cur)):
                raise PHError(f"{rel}: {posix_rel(cur.relative_to(repo_a))} is not a real directory")
        if not contained(repo_a, cur):
            raise PHError(f"{rel}: destination escapes the repository")
    return Path(dest)

SOURCE_ROOT = Path(__file__).resolve().parents[1]
# Single source of truth for the ten upstream core names: release.json's
# speckit.skills section, loaded by ph_init (the same bundled release.json that
# ships with this script). ph_init/ph_speckit/ph_release must never re-spell
# the list; the static pin lives in tests/test_ph_speckit.py.
SPECKIT_CORE_SKILLS = ph_init.SPECKIT_CORE_SKILLS
SPECKIT_INTEGRATION = "zcode"
SPECKIT_SCRIPT_TYPE = "sh"
SPECKIT_GENERATED_SKILLS_DIR = ".zcode/skills"
SPECIFY_DIR = ".specify"
PH_UPSTREAM_KEY = "x-ph-upstream"
CONSTITUTION_OVERRIDE_REL = ".specify/templates/overrides/constitution-template.md"
CONSTITUTION_MEMORY_REL = ".specify/memory/constitution.md"
CONSTITUTION_PROVENANCE_REL = ".specify/memory/.constitution-template.json"
ZCODE_MANIFEST_REL = ".specify/integrations/zcode.manifest.json"
SPECKIT_MANIFEST_REL = ".specify/integrations/speckit.manifest.json"
# Managed by the speckit manifest: scripts, core templates, .specify/.gitignore.
# The workflow-engine assets (.specify/workflows/) are deliberately NOT
# installed: the pinned v1.0.8 engine dispatches workflow steps through
# build_command_invocation, which hard-codes the upstream `speckit-` invocation
# namespace, so a renamed installation cannot execute the bundled workflow and
# shipping it would deliver a broken feature. PH's supported surface is the
# in-session invocation of the ten ph-* skills, none of which reference the
# workflow engine (checked by cmd_verify).
SPECKIT_MANAGED_EXTRA = (
    ".specify/init-options.json",
    ".specify/integration.json",
    CONSTITUTION_PROVENANCE_REL,
)
WORKFLOW_DIR_REL = ".specify/workflows"
PH_OVERRIDE_MARKER = "<!-- PH-managed constitution override: generated by ph_speckit.py; regenerate with `ph_speckit.py constitution --repo <repo> --apply`. -->"
DOCS_GOVERNANCE_ROOT = "docs/约束规范"


def speckit_contract() -> dict:
    section = read_json(SOURCE_ROOT / "speckit.json")
    if not isinstance(section, dict):
        raise PHError("speckit.json is missing the pinned spec-kit contract")
    for key in ("repository", "tag", "commit", "version"):
        if not isinstance(section.get(key), str) or not section[key]:
            raise PHError(f"speckit.json {key} must be a non-empty string")
    skills = section.get("skills")
    if not isinstance(skills, list) or sorted(skills) != sorted(SPECKIT_CORE_SKILLS):
        raise PHError("speckit.json skills must list exactly the ten core skills")
    return section


def ph_skill_name(core: str) -> str:
    return f"ph-{core}"


def speckit_skill_name(core: str) -> str:
    return f"speckit-{core}"


def cache_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    import os

    env = os.environ.get("PH_SPECKIT_CACHE")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".cache" / "ph" / "speckit").resolve()


def run_checked(argv: list[str], cwd: Path | None = None, label: str = "") -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=1200,
        )
    except FileNotFoundError as exc:
        raise PHError(f"{label or 'command'} not available: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PHError(f"{label or 'command'} timed out") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-5:] if detail else ["no output"]
        raise PHError(f"{label or 'command'} failed (exit {proc.returncode}): " + " | ".join(tail))
    return proc


def ensure_source(contract: dict, root: Path) -> Path:
    """Clone the pinned tag and verify the resolved commit. Offline reuse on match.

    A cached clone is reused only when HEAD still resolves to the pinned
    commit AND the worktree and index are clean: a modified clone (partial
    cherry-pick, injected file) is discarded and re-cloned, because it feeds
    the isolated pip install and the staging baseline.
    """

    clone = root / "clone"
    if (clone / ".git").exists():
        head = run_checked(["git", "rev-parse", "HEAD"], cwd=clone, label="git rev-parse (cached clone)")
        status = run_checked(
            ["git", "status", "--porcelain"], cwd=clone, label="git status (cached clone)"
        )
        if head.stdout.strip() == contract["commit"] and not status.stdout.strip():
            return clone
        shutil.rmtree(clone, ignore_errors=True)
    clone.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", contract["tag"], contract["repository"], str(clone)],
        label=f"git clone {contract['repository']} (tag {contract['tag']})",
    )
    head = run_checked(["git", "rev-parse", "HEAD"], cwd=clone, label="git rev-parse (fresh clone)")
    if head.stdout.strip() != contract["commit"]:
        raise PHError(
            f"spec-kit tag {contract['tag']} resolved to {head.stdout.strip()}, expected {contract['commit']}"
        )
    return clone


def ensure_venv(contract: dict, root: Path, clone: Path) -> Path:
    """Install the official CLI into an isolated venv. Never the global environment.

    A cached venv is only reused when the CLI still reports the pinned
    version; a stale or tampered environment is discarded and rebuilt from
    the verified clone. A failed dependency download raises before the
    marker is written, so the next run rebuilds cleanly and nothing else
    has been touched.
    """

    marker = root / "venv" / ".ph-speckit-installed"
    venv = root / "venv"
    expected_version = f"specify {contract['version']}"
    if marker.is_file() and (venv / "bin" / "specify").exists():
        # A cached venv is reused only when the CLI still runs and reports
        # the pinned version; a stale, tampered, or broken cached environment
        # is rebuilt from the verified clone instead of failing forever.
        try:
            version = run_checked(
                [str(venv / "bin" / "specify"), "--version"],
                label="specify --version (cached venv)",
            )
            version_text = version.stdout.strip()
            marker_text = marker.read_text(encoding="utf-8").strip()
        except (PHError, OSError):
            version_text = marker_text = ""
        if (
            version_text == expected_version
            and marker_text == f"{contract['tag']} {contract['commit']}"
        ):
            return venv
        # stale, tampered, or broken cache: rebuild from the verified clone
        shutil.rmtree(venv, ignore_errors=True)
    if venv.exists():
        shutil.rmtree(venv, ignore_errors=True)
    venv.parent.mkdir(parents=True, exist_ok=True)
    run_checked([sys.executable, "-m", "venv", str(venv)], label="python3 -m venv (isolated spec-kit environment)")
    # The pinned source tree is installed from the verified local clone; the
    # CLI's own declared dependencies are resolved by pip from PyPI. This is
    # an isolated, PH-owned venv — the global environment is never touched.
    run_checked(
        [str(venv / "bin" / "pip"), "install", "--quiet", "--disable-pip-version-check", str(clone)],
        label="pip install spec-kit (isolated venv, dependencies from PyPI)",
    )
    version = run_checked([str(venv / "bin" / "specify"), "--version"], label="specify --version")
    if version.stdout.strip() != f"specify {contract['version']}":
        raise PHError(f"isolated specify CLI reports {version.stdout.strip()!r}, expected {contract['version']!r}")
    marker.write_text(f"{contract['tag']} {contract['commit']}\n", encoding="utf-8")
    return venv


def validate_staging(staging: Path, contract: dict, clone: Path | None = None) -> dict:
    """Verify the staged generation before anything is installed from it.

    Coverage of every installed file, so a corrupted or tampered cache can
    never reach a project:
    - the two official manifests pin every skill file and the shared scripts,
      templates, and .specify/.gitignore by hash;
    - the constitution skeleton is byte-compared against the commit-verified
      clone when available, and the provenance json must restate the staged
      template hash;
    - init-options.json and integration.json are runtime-generated records
      validated against the pinned contract values.
    """

    if not (staging / ZCODE_MANIFEST_REL).is_file() or not (staging / SPECKIT_MANIFEST_REL).is_file():
        raise PHError("staging has not been generated yet")
    for core in SPECKIT_CORE_SKILLS:
        if not (staging / SPECKIT_GENERATED_SKILLS_DIR / speckit_skill_name(core) / "SKILL.md").is_file():
            raise PHError(f"staging is missing generated skill: {speckit_skill_name(core)}")
    zcode_manifest = read_json(staging / ZCODE_MANIFEST_REL)
    files = zcode_manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PHError("staging zcode manifest has no file hashes")
    for rel, expected in files.items():
        path = staging / rel
        if not path.is_file():
            raise PHError(f"staging file missing: {rel}")
        if sha256_file(path) != expected:
            raise PHError(f"staging file hash mismatch vs official manifest: {rel}")
    speckit_manifest = read_json(staging / SPECKIT_MANIFEST_REL)
    for rel, expected in (speckit_manifest.get("files") or {}).items():
        path = staging / rel
        if not path.is_file() or sha256_file(path) != expected:
            raise PHError(f"staging shared-infra file hash mismatch vs official manifest: {rel}")
    if read_json(staging / ".specify" / "init-options.json").get("speckit_version") != contract["version"]:
        raise PHError("staging init-options.json does not match the pinned spec-kit version")
    integration_state = read_json(staging / ".specify" / "integration.json")
    if (
        integration_state.get("integration") != SPECKIT_INTEGRATION
        or integration_state.get("default_integration") != SPECKIT_INTEGRATION
        or integration_state.get("version") != contract["version"]
        or integration_state.get("installed_integrations") != [SPECKIT_INTEGRATION]
        or (integration_state.get("integration_settings") or {}).get(SPECKIT_INTEGRATION, {}).get("script")
        != SPECKIT_SCRIPT_TYPE
    ):
        raise PHError("staging integration.json does not match the pinned zcode integration settings")
    provenance = read_json(staging / CONSTITUTION_PROVENANCE_REL)
    template_hash = sha256_file(staging / ".specify" / "templates" / "constitution-template.md")
    if provenance.get("sha256") != template_hash:
        raise PHError("staging constitution provenance hash does not match the staged constitution template")
    if clone is not None:
        source_skeleton = clone / "templates" / "constitution-template.md"
        if not source_skeleton.is_file():
            raise PHError("verified clone is missing templates/constitution-template.md")
        staged_skeleton = staging / CONSTITUTION_MEMORY_REL
        if staged_skeleton.read_bytes() != source_skeleton.read_bytes():
            raise PHError(f"staging {CONSTITUTION_MEMORY_REL} does not match the verified pinned template")
    return zcode_manifest


def ensure_staging(contract: dict, root: Path) -> tuple[Path, dict]:
    """Run the official `specify init` in an isolated staging directory."""

    staging = root / "staging"
    try:
        clone = root / "clone"
        manifest = validate_staging(staging, contract, clone if clone.is_dir() else None)
        return staging, manifest
    except PHError:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    clone = ensure_source(contract, root)
    venv = ensure_venv(contract, root, clone)
    staging.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            str(venv / "bin" / "specify"),
            "init",
            "--here",
            f"--integration={SPECKIT_INTEGRATION}",
            "--non-interactive",
            "--ignore-agent-tools",
            f"--script={SPECKIT_SCRIPT_TYPE}",
            "--force",
        ],
        cwd=staging,
        label="specify init (official generator, isolated staging)",
    )
    manifest = validate_staging(staging, contract)
    return staging, manifest


def cmd_prepare(args: argparse.Namespace) -> dict:
    contract = speckit_contract()
    root = cache_root(args.cache)
    tag_dir = root / f"{contract['tag']}-{contract['commit'][:12]}"
    if args.force and tag_dir.exists():
        shutil.rmtree(tag_dir, ignore_errors=True)
    staging, manifest = ensure_staging(contract, tag_dir)
    return {
        "action": "prepare",
        "staging": str(staging),
        "repository": contract["repository"],
        "tag": contract["tag"],
        "commit": contract["commit"],
        "version": contract["version"],
        "integration": SPECKIT_INTEGRATION,
        "skills": {
            ph_skill_name(core): {
                "upstream": speckit_skill_name(core),
                "path": f"{SPECKIT_GENERATED_SKILLS_DIR}/{speckit_skill_name(core)}/SKILL.md",
                "sha256": manifest["files"][f"{SPECKIT_GENERATED_SKILLS_DIR}/{speckit_skill_name(core)}/SKILL.md"],
            }
            for core in SPECKIT_CORE_SKILLS
        },
    }


CORE_NAME_PATTERN = re.compile(
    r"speckit-(%s)\b" % "|".join(re.escape(core) for core in SPECKIT_CORE_SKILLS)
)
# Dot form: the workflow engine's command identifiers (`command: speckit.specify`
# in .specify/workflows/speckit/workflow.yml) are handoff targets that the
# upstream dispatch normalizes to the installed skill name, so they must be
# renamed together with the skills. Only the ten core names match; the optional
# extension hook namespace (`speckit.git.commit`, `$speckit-git-commit`), the
# `speckit_version` CLI contract key, and the workflow id `speckit` are
# upstream-internal identifiers and stay untouched.
CORE_DOT_PATTERN = re.compile(
    r"speckit\.(%s)\b" % "|".join(re.escape(core) for core in SPECKIT_CORE_SKILLS)
)


def convert_core_references(text: str) -> str:
    """Rename every core handoff reference to its ph identity.

    Hyphen form (`$speckit-<core>`, `/speckit-<core>`, `/skill:speckit-<core>`,
    directory names, frontmatter `name`) and dot form (`speckit.<core>` command
    identifiers) both map to the ph-* skill names. Upstream-internal
    identifiers listed on CORE_DOT_PATTERN never match and are preserved.
    """

    text = CORE_NAME_PATTERN.sub(lambda m: f"ph-{m.group(1)}", text)
    return CORE_DOT_PATTERN.sub(lambda m: f"ph.{m.group(1)}", text)


def convert_skill_text(text: str, core: str, contract: dict) -> str:
    """Rename the generated skill to its ph- identity with a consistent conversion.

    Directory names, frontmatter `name`, and inter-skill invocations all match
    the same core tokens, so `convert_core_references` covers them. Upstream
    provenance (metadata.author, metadata.source) and the optional extension
    hook namespace are left untouched.
    """

    converted = convert_core_references(text)
    if f'name: "{speckit_skill_name(core)}"' in converted:
        raise PHError(f"skill conversion left the original name for {core}")
    upstream_block = (
        f"{PH_UPSTREAM_KEY}:\n"
        f"  repository: {contract['repository']}\n"
        f"  tag: {contract['tag']}\n"
        f"  commit: {contract['commit']}\n"
        f"  original_name: {speckit_skill_name(core)}\n"
    )
    fm_end = converted.find("\n---\n")
    if not converted.startswith("---\n") or fm_end < 0:
        raise PHError(f"generated skill {core} has no frontmatter to annotate")
    insert_at = fm_end + 1
    return converted[:insert_at] + upstream_block + converted[insert_at:]


def skill_upstream_commit(text: str) -> str | None:
    match = re.search(r"^x-ph-upstream:\n(?:  .+\n)*?  commit: ([0-9a-f]{40})\n", text, re.MULTILINE)
    return match.group(1) if match else None


def read_installed_speckit_section(repo: Path) -> dict | None:
    manifest_path = repo / ".agents" / "ph.json"
    if not manifest_path.is_file():
        return None
    try:
        data = read_json(manifest_path)
    except PHError:
        return None
    section = data.get("speckit")
    return section if isinstance(section, dict) else None


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# The manifest path that records one managed file's baseline. Kept next to the
# classifiers so the recorded set and the classified set cannot drift apart.
SKILL_BASELINE_RELS = {core: f".agents/skills/{ph_skill_name(core)}/SKILL.md" for core in SPECKIT_CORE_SKILLS}


def recorded_file_hash(repo: Path, rel: str) -> str | None:
    """The per-file content baseline recorded by the last PH speckit install.

    This is the only accepted proof that an existing differing file was not
    edited since PH last wrote it. Generation markers - the manifest's
    speckit record, its skills mapping, or a file's own x-ph-upstream
    provenance block - only ever say that PH *once* wrote here; they say
    nothing about the current bytes, so a user edit that kept every marker
    must still surface as a conflict instead of a silent overwrite. A
    malformed `files` entry is treated as absent: an untrustworthy baseline
    must never unlock an overwrite.
    """

    section = read_installed_speckit_section(repo)
    if section is None:
        return None
    files = section.get("files")
    if not isinstance(files, dict):
        return None
    recorded = files.get(rel)
    if isinstance(recorded, str) and _HEX64.fullmatch(recorded):
        return recorded
    return None


def baseline_matches(repo: Path, rel: str) -> bool:
    recorded = recorded_file_hash(repo, rel)
    return recorded is not None and sha256_file(repo / rel) == recorded


def classify_skill(repo: Path, core: str, data: bytes) -> tuple[str, str]:
    """Decide write/skip/overwrite/conflict for one converted skill.

    A differing installed skill is only rewritten when the per-file content
    baseline recorded by the last PH speckit install still matches the
    on-disk bytes. The manifest skills mapping and the file's own
    x-ph-upstream provenance block are generation markers, never proof that
    the current bytes are still the ones PH wrote.
    """

    rel = SKILL_BASELINE_RELS[core]
    dest = repo / rel
    if not dest.exists():
        return ("write", "speckit: new ph skill from pinned official generator")
    if dest.is_symlink() or is_disallowed_reparse(dest):
        return ("conflict", "destination is a symlink or junction")
    if dest.read_bytes() == data:
        return ("skip", "speckit: identical")
    existing = dest.read_text(encoding="utf-8", errors="replace")
    if ph_skill_name(core) not in existing[:512]:
        return ("conflict", "existing same-name skill is user content (no PH provenance); not overwriting")
    if baseline_matches(repo, rel):
        return (
            "write",
            "speckit: PH-managed skill upgrade; on-disk bytes still match the recorded per-file "
            "baseline (unmodified since the last PH install)",
        )
    section = read_installed_speckit_section(repo)
    files = section.get("files") if isinstance(section, dict) else None
    if isinstance(files, dict) and rel in files:
        return (
            "conflict",
            "existing same-name skill carries PH provenance but its bytes no longer match the "
            "recorded baseline (user edits?); not overwriting",
        )
    return (
        "conflict",
        "existing same-name skill cannot be proven unmodified: no per-file content baseline is "
        "recorded for it (user content or a pre-baseline PH generation?); not overwriting",
    )


def classify_specify_file(
    repo: Path, rel: str, data: bytes, contract: dict, raw: bytes | None = None
) -> tuple[str, str]:
    """Decide write/skip/overwrite/conflict for one managed .specify file.

    Ownership is proven, never assumed: a differing file is only rewritten
    when a per-file content baseline recorded by the last PH speckit install
    (`speckit.files` in .agents/ph.json) still matches the on-disk bytes -
    the only proof the file was not edited since - or when the disk bytes
    are a byte-identical stock upstream file of the pinned release.
    Everything else - a missing baseline (an older manifest that predates
    the baselines), a drifted baseline (user edits), a missing speckit
    record - is user content and becomes a conflict, never a silent
    overwrite. Identical bytes still skip, so a healthy install is
    unaffected.
    """

    dest = repo / rel
    if not dest.exists():
        return ("write", "speckit: new .specify shared infrastructure")
    if dest.read_bytes() == data:
        return ("skip", "speckit: identical")
    if baseline_matches(repo, rel):
        return (
            "write",
            "speckit: PH-managed .specify upgrade; on-disk bytes still match the recorded per-file "
            "baseline (unmodified since the last PH install)",
        )
    if raw is not None and dest.read_bytes() == raw:
        return ("write", "speckit: adopting a stock upstream spec-kit file (byte-identical to the pinned official generation)")
    section = read_installed_speckit_section(repo)
    files = section.get("files") if isinstance(section, dict) else None
    if isinstance(files, dict) and rel in files:
        return (
            "conflict",
            ".specify managed file differs from the installed generation and no longer matches its "
            "recorded baseline (user edits?); not overwriting",
        )
    if isinstance(section, dict) and section.get("commit") == contract["commit"]:
        return (
            "conflict",
            ".specify managed file differs from the installed spec-kit generation and this install "
            "recorded no per-file baseline for it (user edits?); not overwriting",
        )
    return (
        "conflict",
        ".specify file has no PH per-file content baseline and is neither the pinned generation nor "
        "stock upstream (user content?); not overwriting (recovery: move the file aside to install "
        "the PH-managed generation, or restore .agents/ph.json if this was a PH-managed project)",
    )


def convert_shared_bytes(data: bytes) -> bytes:
    """Apply the same core-reference conversion to shared infrastructure files.

    Templates tell the agent which skill fills them in, prerequisite scripts
    name the skill that must run first, and the bundled workflow's command
    identifiers are handoff targets — all must name the ph-* skills after the
    rename. Files that do not decode as UTF-8 pass through untouched; the
    metadata JSON files contain no core references, so this is a no-op for them.
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return convert_core_references(text).encode("utf-8")


def build_install_plan(repo: Path, staging: Path, contract: dict) -> list[dict]:
    items: list[dict] = []
    for core in SPECKIT_CORE_SKILLS:
        src = staging / SPECKIT_GENERATED_SKILLS_DIR / speckit_skill_name(core) / "SKILL.md"
        data = convert_skill_text(src.read_text(encoding="utf-8"), core, contract).encode("utf-8")
        kind, reason = classify_skill(repo, core, data)
        items.append({"kind": kind, "path": f".agents/skills/{ph_skill_name(core)}/SKILL.md", "reason": reason, "data": data})
    specify_dir = staging / SPECIFY_DIR
    managed = set()
    for rel, _ in (read_json(staging / SPECKIT_MANIFEST_REL).get("files") or {}).items():
        managed.add(rel)
    managed.update(SPECKIT_MANAGED_EXTRA)
    for path in sorted(specify_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = posix_rel(path.relative_to(staging))
        if rel == ZCODE_MANIFEST_REL:
            continue  # zcode-layout install record; PH installs to .agents/skills instead
        if rel == CONSTITUTION_MEMORY_REL:
            dest = repo / rel
            if dest.exists():
                items.append({"kind": "skip", "path": rel, "reason": "speckit: existing constitution preserved (user principles)", "data": None})
            else:
                items.append({"kind": "write", "path": rel, "reason": "speckit: initial constitution from upstream template", "data": path.read_bytes()})
            continue
        if rel not in managed:
            continue
        data = convert_shared_bytes(path.read_bytes())
        kind, reason = classify_specify_file(repo, rel, data, contract, raw=path.read_bytes())
        items.append({"kind": kind, "path": rel, "reason": reason, "data": data})
    return items


def plan_constitution_override(repo: Path, staging: Path, contract: dict) -> dict:
    dest = repo / CONSTITUTION_OVERRIDE_REL
    try:
        ensure_safe_write_dest(repo, CONSTITUTION_OVERRIDE_REL)
    except PHError as exc:
        return {"kind": "conflict", "path": CONSTITUTION_OVERRIDE_REL, "reason": str(exc), "data": None}
    data = render_constitution_override(repo, staging, contract)
    if dest.exists():
        if dest.is_symlink() or is_disallowed_reparse(dest):
            return {"kind": "conflict", "path": CONSTITUTION_OVERRIDE_REL, "reason": "constitution override destination is a symlink or junction", "data": None}
        existing = dest.read_text(encoding="utf-8", errors="replace")
        if PH_OVERRIDE_MARKER not in existing:
            return {"kind": "conflict", "path": CONSTITUTION_OVERRIDE_REL, "reason": "an existing constitution-template override is user content; not overwriting", "data": None}
        if dest.read_bytes() == data:
            return {"kind": "skip", "path": CONSTITUTION_OVERRIDE_REL, "reason": "speckit: constitution override up to date", "data": None}
        # The PH marker alone is a generation marker, not a no-edit proof: the
        # refresh (a changed docs/约束规范 navigation zone) is only allowed to
        # replace a file whose bytes still match the recorded baseline.
        if baseline_matches(repo, CONSTITUTION_OVERRIDE_REL):
            return {
                "kind": "write",
                "path": CONSTITUTION_OVERRIDE_REL,
                "reason": "speckit: constitution governance refresh (on-disk bytes match the recorded baseline)",
                "data": data,
            }
        return {
            "kind": "conflict",
            "path": CONSTITUTION_OVERRIDE_REL,
            "reason": "the existing constitution-template override carries the PH marker but its bytes "
            "no longer match the recorded baseline (user edits?); not overwriting (recovery: move the "
            "override aside and re-run, or re-record after reviewing the edit)",
            "data": None,
        }
    return {"kind": "write", "path": CONSTITUTION_OVERRIDE_REL, "reason": "speckit: PH constitution governance override (project template layer)", "data": data}


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def extract_readme_description(readme: Path, doc_rel: str) -> str | None:
    """One-line positioning from a directory README index, if declared.

    Supports the PH index shapes: markdown table rows
    (`| [doc.md](./doc.md) | positioning |`) and list rows
    (`- [doc.md](doc.md): positioning`).
    """

    if not readme.is_file():
        return None
    name = doc_rel.rsplit("/", 1)[-1]
    dir_name = doc_rel.rsplit("/", 1)[-2] if "/" in doc_rel else None
    for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        desc: str | None = None
        link: str | None = None
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 2:
                m = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", cells[0])
                if m:
                    link, desc = m.group(2), cells[1].strip()
        else:
            m = re.match(r"^[-*]\s+\[([^\]]+)\]\(([^)]+)\)\s*[:：]?\s*(.*)$", stripped)
            if m:
                link, desc = m.group(2), (m.group(3) or "").strip()
        if link is None:
            continue
        target = link.rstrip("/")
        if target.endswith("/" + name) or target == name:
            if desc:
                return desc
        if dir_name and (target.endswith("/" + dir_name + "/README.md") or target.endswith("/" + dir_name)):
            if desc:
                return desc
    return None


def render_constitution_override(repo: Path, staging: Path, contract: dict) -> bytes:
    """Render the PH constitution project-override template.

    The upstream skeleton is taken verbatim from the official generation
    (priority-1 project overrides always use the `replace` strategy upstream,
    so this file becomes the template `ph-constitution` reads). PH only appends
    a governance navigation zone that references — never copies — the live
    docs/约束规范 documents, so later constitution updates keep the convention.
    """

    skeleton = (staging / ".specify" / "templates" / "constitution-template.md").read_text(encoding="utf-8")
    governance_root = repo / DOCS_GOVERNANCE_ROOT
    rows: list[str] = []
    if governance_root.is_dir():
        for path in sorted(governance_root.rglob("*.md")):
            rel = posix_rel(path.relative_to(repo))
            base = rel.rsplit("/", 1)[-1]
            if base.startswith("_"):
                continue  # document skeletons/templates are not live constraints
            text = path.read_text(encoding="utf-8", errors="replace")
            title = extract_title(text, base)
            desc = None
            for candidate in (path.parent / "README.md", path.parent.parent / "README.md"):
                desc = extract_readme_description(candidate, rel)
                if desc:
                    break
            state = ""
            if "<填写：" in text or "<填写:" in text:
                state = "（骨架：占位符未填写，初始化补全后生效）"
            if desc is None:
                desc = "待确认：本篇的适用范围与阅读时机未能从目录索引或正文识别，请补充后再依赖。"
            # Links are written for the materialized constitution at
            # .specify/memory/constitution.md (two levels below the repo
            # root), not for the override template's own deeper location —
            # the template's purpose is to become that document.
            rows.append(f"- [{title}](../../{rel})：{desc}{state}")
    navigation = "\n".join(rows) if rows else "（docs/约束规范 目前没有可引用的正文文档。）"
    zone = (
        "\n<!-- PH-managed constitution override: generated by ph_speckit.py; regenerate with `ph_speckit.py constitution --repo <repo> --apply`. -->\n"
        "## PH 管理区：本仓库约束规范导航\n\n"
        "以下文档是本仓库现行约束规范的唯一正文，本模板只做逐篇引用、不复制正文；"
        "阅读时机与适用范围以各篇正文及其目录索引为准，冲突时以正文为准。维护规则：新增、移动或删除"
        f" {DOCS_GOVERNANCE_ROOT} 下的文档后，由 PH init / 升级流程刷新本区。\n\n"
        f"{navigation}\n"
    )
    return (skeleton.rstrip("\n") + "\n" + zone).encode("utf-8")


def resolve_staging(cache: str | None, contract: dict) -> Path:
    """Prepare (and fully validate) the staging directory in the PH cache root.

    There is deliberately no --staging override: a self-declared staging
    directory carries its own manifest, so trusting it would bypass the
    verified-source baseline. Tests redirect the cache root via
    PH_SPECKIT_CACHE instead, which keeps the verified clone, venv, and
    staging together under one root.
    """

    root = cache_root(cache) / f"{contract['tag']}-{contract['commit'][:12]}"
    staging, _ = ensure_staging(contract, root)
    return staging


def cmd_install(repo: Path, apply: bool, cache: str | None) -> dict:
    contract = speckit_contract()
    staging = resolve_staging(cache, contract)
    items = build_install_plan(repo, staging, contract)
    items.append(plan_constitution_override(repo, staging, contract))
    # The manifest update happens after the item writes, so the manifest's
    # own write safety is validated up front too: an unsafe or unreadable
    # .agents/ph.json must block the whole install instead of failing after
    # the tree has already been written.
    manifest_rel = ".agents/ph.json"
    manifest_path = repo / manifest_rel
    if manifest_path.is_symlink() or manifest_path.exists():
        try:
            manifest_dest = ensure_safe_write_dest(repo, manifest_rel)
            if not isinstance(read_json(manifest_dest), dict):
                raise PHError(".agents/ph.json must be a JSON object")
        except PHError as exc:
            items.append({
                "kind": "conflict",
                "path": manifest_rel,
                "reason": f"the repository manifest cannot be updated by this install: {exc}",
                "data": None,
            })
    # Validate every write destination BEFORE any write: an unsafe ancestor
    # (symlinked .agents/skills, escaping path) is a conflict that blocks the
    # whole install, never a mid-apply crash with half the tree written.
    for item in items:
        if item["kind"] != "write" or item["data"] is None:
            continue
        try:
            ensure_safe_write_dest(repo, item["path"])
        except PHError as exc:
            item["kind"] = "conflict"
            item["reason"] = str(exc)
    blocked = any(i["kind"] == "conflict" for i in items)
    applied = False
    if apply and not blocked:
        for item in items:
            if item["kind"] != "write" or item["data"] is None:
                continue
            dest = ensure_safe_write_dest(repo, item["path"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(item["data"])
        applied = True
        # The install plan is the complete managed set: the baselines are
        # rebuilt from what is now on disk (retired upstream paths drop out).
        update_installed_speckit_section(repo, contract, items)
    return {
        "action": "install",
        "apply": applied,
        "staging": str(staging),
        "repository": contract["repository"],
        "tag": contract["tag"],
        "commit": contract["commit"],
        "version": contract["version"],
        "blocked": blocked,
        "items": [
            {
                "kind": i["kind"],
                "path": i["path"],
                "reason": i["reason"],
                # The content proof of what this run wrote (or would write):
                # a later step may use it to prove an on-disk file is exactly
                # this run's own output before refreshing it.
                "sha256": sha256_bytes(i["data"]) if i["data"] is not None else None,
            }
            for i in items
        ],
    }


def _validated_file_hashes(raw: object) -> dict[str, str]:
    """Keep only well-formed baseline entries: {path: 64-hex sha256}.

    An untrustworthy baseline (wrong types, wrong hash shape) must never
    unlock an overwrite, so it is dropped instead of trusted.
    """

    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str) and _HEX64.fullmatch(value)
    }


def update_installed_speckit_section(
    repo: Path, contract: dict, items: list[dict] | None = None, rebuild: bool = True
) -> None:
    """Record the upstream provenance AND the per-file content baselines.

    `speckit.files` maps every managed path to the sha256 of the bytes on
    disk after this install. That baseline is the ownership proof a future
    upgrade must match before it may overwrite a differing file; without it
    the upgrade stays a conflict. A fresh `init` deploys the scaffold
    manifest template (which carries no baselines) after the install, so
    `record-baselines` re-records them once the scaffold deploy is done.
    With `rebuild` the recorded set is replaced by this plan's files (the
    install plan is the complete managed set, so retired paths drop out);
    otherwise the previous baselines are kept and only this plan's paths
    are refreshed (the standalone constitution refresh).
    """

    manifest_path = ensure_safe_write_dest(repo, ".agents/ph.json")
    if not manifest_path.is_file():
        return
    data = read_json(manifest_path)
    previous = data.get("speckit") if isinstance(data.get("speckit"), dict) else {}
    files: dict[str, str] = {} if rebuild else _validated_file_hashes(previous.get("files"))
    for item in items or []:
        # The memory constitution is user-owned content (every install after
        # the first preserves it), so it never carries a PH baseline.
        if item["kind"] not in ("write", "skip") or item["path"] == CONSTITUTION_MEMORY_REL:
            continue
        path = repo / item["path"]
        if path.is_file():
            files[item["path"]] = sha256_file(path)
    data["speckit"] = {
        "repository": contract["repository"],
        "tag": contract["tag"],
        "commit": contract["commit"],
        "version": contract["version"],
        "skills": {ph_skill_name(core): speckit_skill_name(core) for core in SPECKIT_CORE_SKILLS},
        "files": dict(sorted(files.items())),
    }
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_record_baselines(repo: Path, cache: str | None, refresh_override_sha: str | None = None) -> dict:
    """Re-record the per-file baselines after a fresh init replaced the manifest.

    A fresh `init` runs the speckit install first (recording the baselines
    into .agents/ph.json) and then deploys the scaffold, whose manifest
    template carries no `files` section - the deploy would erase them. This
    cache-only command re-derives the managed file set from the verified
    staging and re-records the on-disk hashes; it never reaches the network.

    The scaffold deploy also legitimately changes the docs/约束规范 tree the
    constitution override's navigation zone references, so the override that
    the install step wrote moments earlier no longer matches a fresh render.
    `refresh_override_sha` carries the content proof of exactly what the
    install step wrote: when the on-disk override still matches it, the
    caller has proven the file is this run's own output (not a user edit),
    and it is refreshed to the new render before its baseline is recorded.
    Without the proof a mismatching override stays a conflict.
    """

    contract = speckit_contract()
    root = cache_root(cache) / f"{contract['tag']}-{contract['commit'][:12]}"
    staging = root / "staging"
    if not staging.is_dir():
        raise PHError("verified speckit staging cache is missing; run the install step first")
    validate_staging(staging, contract)
    items = build_install_plan(repo, staging, contract)
    override_item = plan_constitution_override(repo, staging, contract)
    if (
        override_item["kind"] == "conflict"
        and refresh_override_sha is not None
        and _HEX64.fullmatch(refresh_override_sha)
    ):
        dest = repo / CONSTITUTION_OVERRIDE_REL
        if dest.is_file() and sha256_file(dest) == refresh_override_sha:
            data = render_constitution_override(repo, staging, contract)
            override_item = {
                "kind": "write",
                "path": CONSTITUTION_OVERRIDE_REL,
                "reason": "speckit: constitution governance refresh (on-disk bytes proven to be this run's install output)",
                "data": data,
            }
    items.append(override_item)
    blocked = any(item["kind"] == "conflict" for item in items)
    if not blocked:
        manifest = ensure_safe_write_dest(repo, ".agents/ph.json")
        if not manifest.is_file() or not isinstance(read_json(manifest), dict):
            raise PHError(".agents/ph.json must be a JSON object before recording baselines")
        if override_item["kind"] == "write":
            dest = ensure_safe_write_dest(repo, CONSTITUTION_OVERRIDE_REL)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(override_item["data"])
        update_installed_speckit_section(repo, contract, items)
    section = read_installed_speckit_section(repo)
    return {
        "action": "record-baselines",
        "blocked": blocked,
        "conflicts": [item["path"] for item in items if item["kind"] == "conflict"],
        "repository": contract["repository"],
        "tag": contract["tag"],
        "commit": contract["commit"],
        "version": contract["version"],
        "override": override_item["kind"],
        "files": (section or {}).get("files") or {},
    }


def cmd_constitution(repo: Path, apply: bool, cache: str | None) -> dict:
    contract = speckit_contract()
    staging = resolve_staging(cache, contract)
    item = plan_constitution_override(repo, staging, contract)
    applied = False
    if apply and item["kind"] == "write" and item["data"] is not None:
        dest = ensure_safe_write_dest(repo, item["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(item["data"])
        applied = True
        # A standalone refresh must re-record the baseline it just replaced,
        # otherwise the next install would see a drifted override.
        update_installed_speckit_section(repo, contract, [item], rebuild=False)
    return {
        "action": "constitution",
        "apply": applied,
        "blocked": item["kind"] == "conflict",
        "items": [{"kind": item["kind"], "path": item["path"], "reason": item["reason"]}],
    }


def cmd_verify(repo: Path) -> dict:
    contract = speckit_contract()
    problems: list[str] = []
    for core in SPECKIT_CORE_SKILLS:
        skill = repo / ".agents" / "skills" / ph_skill_name(core) / "SKILL.md"
        if not skill.is_file():
            problems.append(f"missing skill .agents/skills/{ph_skill_name(core)}/SKILL.md")
            continue
        text = skill.read_text(encoding="utf-8", errors="replace")
        # The x-ph-upstream block intentionally carries the original name;
        # only references outside that provenance block must be converted.
        body = re.sub(r"^x-ph-upstream:\n(?:  .*\n?)*", "", text, flags=re.MULTILINE)
        if f'name: "{ph_skill_name(core)}"' not in text[:512]:
            problems.append(f"skill {ph_skill_name(core)} frontmatter name mismatch")
        if f"speckit-{core}" in body or f"speckit.{core}" in body:
            problems.append(f"skill {ph_skill_name(core)} still references its upstream name")
        if skill_upstream_commit(text) != contract["commit"]:
            problems.append(f"skill {ph_skill_name(core)} upstream provenance does not match the pinned commit")
    for rel in SPECKIT_MANAGED_EXTRA + (
        ".specify/scripts/bash/check-prerequisites.sh",
        ".specify/scripts/bash/resolve-template.sh",
        ".specify/templates/spec-template.md",
        CONSTITUTION_MEMORY_REL,
    ):
        if not (repo / rel).is_file():
            problems.append(f"missing {rel}")
    # Shared infrastructure must carry the rename too: no hyphen- or dot-form
    # core reference may survive in any managed .specify file (the memory
    # constitution is user-owned content and stays exempt).
    shared_files = {
        *SPECKIT_MANAGED_EXTRA,
        ".specify/scripts/bash/check-prerequisites.sh",
        ".specify/scripts/bash/common.sh",
        ".specify/scripts/bash/create-new-feature.sh",
        ".specify/scripts/bash/resolve-template.sh",
        ".specify/scripts/bash/setup-plan.sh",
        ".specify/scripts/bash/setup-tasks.sh",
        ".specify/templates/checklist-template.md",
        ".specify/templates/plan-template.md",
        ".specify/templates/spec-template.md",
        ".specify/templates/tasks-template.md",
        CONSTITUTION_OVERRIDE_REL,
    }
    for rel in sorted(shared_files):
        path = repo / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if CORE_NAME_PATTERN.search(text) or CORE_DOT_PATTERN.search(text):
            problems.append(f"{rel} still references an upstream speckit-* skill name")
    # The workflow-engine assets are deliberately not installed: the pinned
    # v1.0.8 engine hard-codes the upstream invocation namespace, so the
    # bundled workflow cannot dispatch to renamed skills. Their absence is
    # part of the contract; nothing else depends on them.
    if (repo / WORKFLOW_DIR_REL).exists():
        problems.append(f"{WORKFLOW_DIR_REL} must not be installed (engine dispatch is upstream-namespace bound)")
    override = repo / CONSTITUTION_OVERRIDE_REL
    if not override.is_file():
        problems.append(f"missing {CONSTITUTION_OVERRIDE_REL}")
    elif PH_OVERRIDE_MARKER not in override.read_text(encoding="utf-8", errors="replace"):
        problems.append(f"{CONSTITUTION_OVERRIDE_REL} is not PH-managed")
    section = read_installed_speckit_section(repo)
    if section is None:
        problems.append(".agents/ph.json has no valid speckit installation record")
    else:
        if section.get("commit") != contract["commit"] or section.get("tag") != contract["tag"]:
            problems.append(".agents/ph.json speckit section does not match the release contract")
        elif {ph_skill_name(c): speckit_skill_name(c) for c in SPECKIT_CORE_SKILLS} != (section.get("skills") or {}):
            problems.append(".agents/ph.json speckit skills mapping is incomplete")
        else:
            # Every install must record the per-file content baselines the
            # next upgrade compares against before it may overwrite a
            # differing file.
            files = _validated_file_hashes(section.get("files"))
            if not files:
                problems.append(".agents/ph.json speckit section records no per-file content baselines")
            else:
                for core in SPECKIT_CORE_SKILLS:
                    if SKILL_BASELINE_RELS[core] not in files:
                        problems.append(f".agents/ph.json speckit.files has no baseline for {ph_skill_name(core)}")
                if CONSTITUTION_OVERRIDE_REL not in files:
                    problems.append(".agents/ph.json speckit.files has no baseline for the constitution override")
    return {"action": "verify", "ok": not problems, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ph_speckit.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p_prepare = sub.add_parser("prepare", help="fetch the pinned official release and generate in isolation")
    p_prepare.add_argument("--cache", help="cache root (default ~/.cache/ph/speckit)")
    p_prepare.add_argument("--force", action="store_true", help="discard cached generation and regenerate")
    p_install = sub.add_parser("install", help="install/upgrade the ten ph-* skills and .specify into a repository")
    p_install.add_argument("--repo", required=True)
    p_install.add_argument("--apply", action="store_true")
    p_install.add_argument("--cache", help="cache root (default ~/.cache/ph/speckit)")
    p_const = sub.add_parser("constitution", help="refresh the PH constitution governance override template")
    p_const.add_argument("--repo", required=True)
    p_const.add_argument("--apply", action="store_true")
    p_const.add_argument("--cache", help="cache root (default ~/.cache/ph/speckit)")
    p_record = sub.add_parser(
        "record-baselines",
        help="re-record the per-file content baselines after a fresh init deployed the scaffold manifest",
    )
    p_record.add_argument("--repo", required=True)
    p_record.add_argument("--cache", help="cache root (default ~/.cache/ph/speckit)")
    p_record.add_argument(
        "--refresh-override-sha",
        help="sha256 of the constitution override exactly as this run's install wrote it; proves the "
        "file is this run's own output so it may be refreshed for the scaffold-deployed docs tree",
    )
    p_verify = sub.add_parser("verify", help="verify the installed spec-kit integration")
    p_verify.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            payload = cmd_prepare(args)
        elif args.command == "install":
            repo = ph_init.find_repo(args.repo)
            payload = cmd_install(repo, args.apply, args.cache)
        elif args.command == "constitution":
            repo = ph_init.find_repo(args.repo)
            payload = cmd_constitution(repo, args.apply, args.cache)
        elif args.command == "record-baselines":
            repo = ph_init.find_repo(args.repo)
            payload = cmd_record_baselines(repo, args.cache, args.refresh_override_sha)
        else:
            repo = ph_init.find_repo(args.repo)
            payload = cmd_verify(repo)
    except PHError as exc:
        sys.stderr.write(f"error={exc}\n")
        return 2
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
