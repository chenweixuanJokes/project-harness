#!/usr/bin/env python3
"""Human-readable companion plumbing for PH spec-driven skills.

The ten spec-driven skills (ph-specify, ph-clarify, ph-plan, ph-tasks,
ph-converge, ph-implement, ph-constitution, ph-checklist, ph-analyze,
ph-taskstoissues) attach a human-readable companion document next to the
machine artifact they produce. A companion is a snapshot explanation written
by the calling skill following .agents/skills/ph-human/references/
human-writing.md; it is never an authoritative rule or acceptance source.

This script does the mechanical half only - it never generates prose:

* ``publish``        map one on-disk machine artifact to its companion path,
                     verify write safety, append the machine footer (source
                     path, source sha256, producing skill, timestamp, body
                     hash) and atomically publish a candidate prose file.
* ``publish-snapshot`` publish a companion with no on-disk machine source
                     (the ph-analyze report / the authorized ph-taskstoissues
                     results of THIS invocation).
* ``status``         read-only staleness report: fresh / stale / orphan /
                     user-modified / snapshot companions, plus root-level
                     machine artifacts that have no companion yet.

Naming contract (the single authority; human-writing.md documents it):

* <feature>/spec.md|plan.md|research.md|data-model.md|quickstart.md|
  tasks.md|verification.md  ->  <feature>/<name>-human.md
* <feature>/checklists/<n>.md  ->  <feature>/checklists-<n>-human.md
* <feature>/contracts/<n>.md   ->  <feature>/contracts-<n>-human.md
* .agents/project-harness/constitution.md
                               ->  .agents/project-harness/constitution-human.md

Every companion lives at the feature directory root (never inside
checklists/ or contracts/), so scans never descend into those directories.
Sources whose name already ends in ``-human.md`` are refused: a companion is
never an input, and no companion of a companion exists. A missing source
never yields a fabricated companion.

Write protection: a companion destination that exists must carry a valid
machine footer whose recorded body hash still matches the on-disk prose -
that is the proof the file is this tool's own unmodified output. Anything
else (no footer, unreadable footer, drifted body) is user content and blocks
the write instead of being overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

FOOTER_SCHEMA = "ph-human-companion/1"
FOOTER_BEGIN = f"<!-- {FOOTER_SCHEMA}"
FOOTER_END = "-->"
FOOTER_KEYS = ("source", "source_sha256", "kind", "skill", "generated", "body_sha256")
HEX64 = set("0123456789abcdef")
CONSTITUTION_SOURCE = ".agents/project-harness/constitution.md"
ROOT_MACHINE_NAMES = (
    "spec",
    "plan",
    "research",
    "data-model",
    "quickstart",
    "tasks",
    "verification",
)
NESTED_SOURCE_DIRS = ("checklists", "contracts")
COMPANION_SUFFIX = "-human.md"
SNAPSHOT_KINDS = {"analysis": "analysis-human.md", "issues": "issues-human.md"}
SPECS_ROOT = ".agents/project-harness/specs"


class PHHumanError(Exception):
    """User-facing failure that must become a non-zero exit, not a traceback."""


def is_safe_rel(rel: str) -> bool:
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "~")) or "\\" in rel or "\0" in rel:
        return False
    if len(rel) > 1 and rel[1] == ":":
        return False
    return all(part not in {"", ".", ".."} for part in rel.split("/"))


def is_hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in HEX64 for c in value)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_hardlink(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and not path.is_symlink() and path.stat().st_nlink > 1
    except OSError:
        return False


def is_disallowed_reparse(path: Path) -> bool:
    # Windows junctions/reparse points are directories that both is_dir() and
    # lstat() treat as ordinary on POSIX; the flag check below is a no-op
    # there and catches the reparse case on Windows.
    try:
        return int(os.lstat(path).st_file_attributes) & 0x400 != 0  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def path_issue(repo: Path, path: Path) -> str | None:
    """Unsafe-ancestor report for a repo-local path (symlink/junction/escape)."""
    repo_a = repo.absolute()
    cur = path.absolute()
    while True:
        try:
            cur.relative_to(repo_a)
        except ValueError:
            return f"{path} escapes the repository root"
        if cur.is_symlink() or is_disallowed_reparse(cur):
            return f"{cur} is a symlink or junction"
        if is_hardlink(cur):
            return f"{cur} is a hardlink"
        if cur == repo_a:
            return None
        nxt = cur.parent
        if nxt == cur:
            return f"{path} escapes the repository root"
        cur = nxt


def require_real_file(repo: Path, rel: str, label: str) -> Path:
    if not is_safe_rel(rel):
        raise PHHumanError(f"{label} is not a safe repository-relative path: {rel!r}")
    path = repo / rel
    issue = path_issue(repo, path)
    if issue or not path.is_file():
        raise PHHumanError(f"{label} must be a repository-local regular file: {rel}" + (f" ({issue})" if issue else ""))
    return path


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def map_source(repo: Path, rel: str) -> dict:
    """Map one machine artifact to its companion path (no filesystem reads
    beyond the source's own existence/safety checks)."""
    if not is_safe_rel(rel):
        raise PHHumanError(f"source is not a safe repository-relative path: {rel!r}")
    parts = PurePosixPath(rel).parts
    name = parts[-1] if parts else ""
    if not name.endswith(".md") or name == ".md":
        raise PHHumanError(f"machine source must be a markdown file: {rel}")
    if name.endswith(COMPANION_SUFFIX):
        raise PHHumanError(
            f"refusing to map a companion as a machine source: {rel} "
            "(companions are never inputs; no companion of a companion exists)"
        )
    if rel == CONSTITUTION_SOURCE:
        companion = ".agents/project-harness/constitution-human.md"
    elif len(parts) >= 3 and parts[-2] in NESTED_SOURCE_DIRS:
        subdir, stem = parts[-2], name[:-3]
        if not stem:
            raise PHHumanError(f"machine source has an empty name: {rel}")
        companion = "/".join([*parts[:-2], f"{subdir}-{stem}{COMPANION_SUFFIX}"])
    elif len(parts) >= 2 and name[:-3] in ROOT_MACHINE_NAMES:
        companion = "/".join([*parts[:-1], f"{name[:-3]}{COMPANION_SUFFIX}"])
    else:
        raise PHHumanError(
            f"unmapped machine source: {rel} (mappable: {', '.join(ROOT_MACHINE_NAMES)} "
            f"and {CONSTITUTION_SOURCE} at the feature root; nested: "
            + ", ".join(f"<feature>/{d}/<name>.md" for d in NESTED_SOURCE_DIRS)
            + ")"
        )
    require_real_file(repo, rel, "machine source")
    check_nested_collision(repo, rel, companion)
    return {"source": rel, "companion": companion, "kind": "artifact"}


def check_nested_collision(repo: Path, rel: str, companion: str) -> None:
    """Block two nested machine sources flattening to one companion name."""
    parts = PurePosixPath(rel).parts
    if len(parts) < 3 or parts[-2] not in NESTED_SOURCE_DIRS:
        return
    subdir, stem = parts[-2], parts[-1][:-3]
    flat = f"{subdir}-{stem}{COMPANION_SUFFIX}".casefold()
    base = repo / "/".join(parts[:-2]) / subdir
    issue = path_issue(repo, base)
    if issue or not base.is_dir():
        raise PHHumanError(f"cannot inspect the {subdir}/ directory for naming conflicts: {issue or 'missing'}")
    for child in sorted(base.iterdir()):
        if not child.name.endswith(".md") or child.name.endswith(COMPANION_SUFFIX):
            continue
        other = f"{subdir}-{child.name[:-3]}{COMPANION_SUFFIX}".casefold()
        if other == flat and child.name != parts[-1]:
            raise PHHumanError(
                f"nested naming conflict: {rel} and {child.name} both flatten to "
                f"{companion}; rename one source or publish manually resolved content"
            )


# ---------------------------------------------------------------------------
# Companion footer
# ---------------------------------------------------------------------------


def build_footer(meta: dict) -> str:
    lines = [FOOTER_BEGIN]
    for key in FOOTER_KEYS:
        lines.append(f"{key}: {meta[key]}")
    lines.append(FOOTER_END)
    return "\n".join(lines) + "\n"


def parse_companion(data: bytes) -> tuple[str, dict] | None:
    """Split a companion file into (body, footer meta); None when the bytes
    are not a recognizable PH companion (missing/trailing-footer invalid)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    marker = f"\n{FOOTER_BEGIN}\n"
    index = text.find(marker)
    if index < 0:
        return None
    body = text[: index + 1]
    tail = text[index + len(marker):]
    if not tail.endswith(f"\n{FOOTER_END}\n") and tail != f"{FOOTER_END}\n":
        return None
    block = tail[: -len(FOOTER_END) - 1] if tail.endswith(f"\n{FOOTER_END}\n") else tail
    meta: dict[str, str] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if not sep or key.strip() != key or not key:
            return None
        meta[key] = value.strip()
    if tuple(meta) != FOOTER_KEYS:
        return None
    if meta["kind"] not in {"artifact", *SNAPSHOT_KINDS}:
        return None
    if not is_hex64(meta["body_sha256"]):
        return None
    if meta["kind"] == "artifact":
        if meta["source"] == "@invocation" or not is_hex64(meta["source_sha256"]):
            return None
        if not is_safe_rel(meta["source"]):
            return None
    else:
        if meta["source"] != "@invocation" or meta["source_sha256"] != "-":
            return None
    if not meta["skill"] or not meta["generated"]:
        return None
    return body, meta


def companion_state(repo: Path, data: bytes) -> dict:
    """Classify one companion's bytes for status (never writes)."""
    parsed = parse_companion(data)
    if parsed is None:
        return {"state": "unreadable", "reason": "no valid PH companion footer; treat as user content"}
    body, meta = parsed
    out = {
        "state": None,
        "kind": meta["kind"],
        "skill": meta["skill"],
        "generated": meta["generated"],
        "source": meta["source"],
    }
    if sha256_bytes(body.encode("utf-8")) != meta["body_sha256"]:
        out["state"] = "user_modified"
        out["reason"] = "prose no longer matches the recorded body hash (user edits?); refresh is blocked"
        return out
    if meta["kind"] != "artifact":
        out["state"] = "snapshot"
        out["reason"] = "invocation snapshot (analysis report / authorized results); no on-disk machine source to compare"
        return out
    source = repo / meta["source"]
    issue = path_issue(repo, source)
    if issue or not source.is_file():
        out["state"] = "orphan"
        out["reason"] = f"machine source {meta['source']} is missing or unsafe"
        return out
    if sha256_file(source) == meta["source_sha256"]:
        out["state"] = "fresh"
    else:
        out["state"] = "stale"
        out["reason"] = f"machine source {meta['source']} changed after this companion was written"
    return out


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def read_candidate(path_str: str, dest: Path) -> bytes:
    candidate = Path(path_str).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise PHHumanError(f"candidate must be a regular file (no symlinks): {candidate}")
    data = candidate.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PHHumanError(f"candidate must be UTF-8 prose: {candidate}") from exc
    if not text.strip():
        raise PHHumanError(f"candidate prose is empty: {candidate}")
    if FOOTER_BEGIN in text:
        raise PHHumanError(
            "candidate already carries a PH companion footer; provide prose only - "
            "the footer is written by this script"
        )
    if candidate.absolute().resolve() == dest.absolute().resolve():
        raise PHHumanError("candidate must not be the companion destination itself")
    # Exactly one trailing newline separates the prose from the machine
    # footer, so parsing the published file recovers the exact published
    # prose bytes and the recorded body hash stays verifiable.
    if not data.endswith(b"\n"):
        data += b"\n"
    return data


def write_companion(repo: Path, companion_rel: str, body: bytes, meta: dict) -> None:
    dest = repo / companion_rel
    issue = path_issue(repo, dest)
    if issue:
        raise PHHumanError(f"refusing to publish through an unsafe path: {issue}")
    if dest.exists():
        if not dest.is_file():
            raise PHHumanError(f"companion destination is not a regular file: {companion_rel}")
        parsed = parse_companion(dest.read_bytes())
        if parsed is None:
            raise PHHumanError(
                f"refusing to overwrite {companion_rel}: it carries no valid PH companion "
                "footer, so it is user content; move it aside or review it first"
            )
        body_on_disk, meta_on_disk = parsed
        if sha256_bytes(body_on_disk.encode("utf-8")) != meta_on_disk["body_sha256"]:
            raise PHHumanError(
                f"refusing to overwrite {companion_rel}: its prose no longer matches the "
                "recorded body hash (user edits?); the user must decide - move the file "
                "aside to publish a fresh companion"
            )
    content = body + build_footer(meta).encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
        os.replace(tmp, dest)
    except Exception:
        if fd >= 0:
            os.close(fd)
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        raise


def publish(repo: Path, source_rel: str, candidate: str, skill: str) -> dict:
    mapping = map_source(repo, source_rel)
    body = read_candidate(candidate, repo / mapping["companion"])
    meta = {
        "source": mapping["source"],
        "source_sha256": sha256_file(repo / mapping["source"]),
        "kind": "artifact",
        "skill": skill,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body_sha256": sha256_bytes(body),
    }
    write_companion(repo, mapping["companion"], body, meta)
    state = companion_state(repo, (repo / mapping["companion"]).read_bytes())
    return {
        "action": "publish",
        "source": mapping["source"],
        "companion": mapping["companion"],
        "kind": "artifact",
        "skill": skill,
        "state": state["state"],
    }


def publish_snapshot(repo: Path, feature_rel: str, kind: str, candidate: str, skill: str) -> dict:
    if kind not in SNAPSHOT_KINDS:
        raise PHHumanError(f"snapshot kind must be one of {sorted(SNAPSHOT_KINDS)}")
    if not is_safe_rel(feature_rel):
        raise PHHumanError(f"feature is not a safe repository-relative path: {feature_rel!r}")
    feature = repo / feature_rel
    issue = path_issue(repo, feature)
    if issue or not feature.is_dir():
        raise PHHumanError(f"feature must be a repository-local real directory: {feature_rel}")
    companion_rel = f"{feature_rel.rstrip('/')}/{SNAPSHOT_KINDS[kind]}"
    body = read_candidate(candidate, repo / companion_rel)
    meta = {
        "source": "@invocation",
        "source_sha256": "-",
        "kind": kind,
        "skill": skill,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body_sha256": sha256_bytes(body),
    }
    write_companion(repo, companion_rel, body, meta)
    return {
        "action": "publish-snapshot",
        "feature": feature_rel,
        "companion": companion_rel,
        "kind": kind,
        "skill": skill,
        "note": "snapshot of this invocation's real output; refresh only by running the skill again",
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def feature_companions(repo: Path, feature_rel: str) -> dict:
    """Companion states for one feature directory (root-level scan only:
    never descends into checklists/ or contracts/)."""
    feature = repo / feature_rel
    companions: list[dict] = []
    seen: set[str] = set()
    for child in sorted(feature.iterdir()):
        if not child.name.endswith(COMPANION_SUFFIX) or not child.is_file():
            continue
        rel = f"{feature_rel}/{child.name}"
        issue = path_issue(repo, child)
        entry = {"companion": rel}
        if issue:
            entry.update({"state": "unreadable", "reason": issue})
        else:
            entry.update(companion_state(repo, child.read_bytes()))
        companions.append(entry)
        seen.add(child.name)
    missing = [
        f"{feature_rel}/{name}.md"
        for name in ROOT_MACHINE_NAMES
        if (feature / f"{name}.md").is_file() and f"{name}{COMPANION_SUFFIX}" not in seen
    ]
    return {"feature": feature_rel, "companions": companions, "missing": missing}


def status(repo: Path, feature_rel: str | None, scan_all: bool) -> dict:
    if bool(feature_rel) == bool(scan_all):
        raise PHHumanError("status needs exactly one of --feature or --all")
    features: list[dict] = []
    if scan_all:
        specs = repo / SPECS_ROOT
        if specs.exists():
            issue = path_issue(repo, specs)
            if issue or not specs.is_dir():
                raise PHHumanError(f"cannot scan {SPECS_ROOT}: {issue or 'not a directory'}")
            for child in sorted(specs.iterdir()):
                if child.name.startswith(".") or not child.is_dir():
                    continue
                child_issue = path_issue(repo, child)
                if child_issue:
                    raise PHHumanError(f"cannot scan feature directory {child}: {child_issue}")
                features.append(feature_companions(repo, f"{SPECS_ROOT}/{child.name}"))
        if (repo / CONSTITUTION_SOURCE).is_file():
            rel = ".agents/project-harness/constitution-human.md"
            companions: list[dict] = []
            if (repo / rel).is_file():
                companions.append({"companion": rel, **companion_state(repo, (repo / rel).read_bytes())})
            features.append({
                "feature": ".agents/project-harness",
                "companions": companions,
                "missing": [] if companions else [CONSTITUTION_SOURCE],
            })
    else:
        if not is_safe_rel(feature_rel or ""):
            raise PHHumanError(f"feature is not a safe repository-relative path: {feature_rel!r}")
        feature = repo / feature_rel  # type: ignore[arg-type]
        issue = path_issue(repo, feature)
        if issue or not feature.is_dir():
            raise PHHumanError(f"feature must be a repository-local real directory: {feature_rel}")
        features.append(feature_companions(repo, feature_rel))  # type: ignore[arg-type]
    counts: dict[str, int] = {}
    for feature in features:
        for entry in feature["companions"]:
            counts[entry["state"]] = counts.get(entry["state"], 0) + 1
        counts["missing"] = counts.get("missing", 0) + len(feature["missing"])
    return {
        "action": "status",
        "features": features,
        "summary": dict(sorted(counts.items())),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def find_repo(explicit: str) -> Path:
    repo = Path(explicit).expanduser().resolve()
    if not repo.is_dir():
        raise PHHumanError(f"repository root is not a directory: {repo}")
    return repo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ph_human.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_publish = sub.add_parser("publish", help="map a machine artifact and publish its companion")
    p_publish.add_argument("--repo", required=True)
    p_publish.add_argument("--source", required=True, help="repo-relative machine artifact path")
    p_publish.add_argument("--candidate", required=True, help="prose candidate file (agent-written, outside the repo)")
    p_publish.add_argument("--skill", required=True, help="name of the skill producing this companion")

    p_snapshot = sub.add_parser("publish-snapshot", help="publish an invocation-snapshot companion")
    p_snapshot.add_argument("--repo", required=True)
    p_snapshot.add_argument("--feature", required=True, help="repo-relative feature directory")
    p_snapshot.add_argument("--kind", required=True, choices=sorted(SNAPSHOT_KINDS))
    p_snapshot.add_argument("--candidate", required=True)
    p_snapshot.add_argument("--skill", required=True)

    p_status = sub.add_parser("status", help="read-only staleness report")
    p_status.add_argument("--repo", required=True)
    p_status.add_argument("--feature", default=None, help="repo-relative feature directory")
    p_status.add_argument("--all", action="store_true", help="scan every feature under the specs root plus the constitution companion")

    args = parser.parse_args(argv)
    try:
        repo = find_repo(args.repo)
        if args.command == "publish":
            payload = publish(repo, args.source, args.candidate, args.skill)
        elif args.command == "publish-snapshot":
            payload = publish_snapshot(repo, args.feature, args.kind, args.candidate, args.skill)
        else:
            payload = status(repo, args.feature, args.all)
    except PHHumanError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
