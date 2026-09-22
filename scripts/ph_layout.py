#!/usr/bin/env python3
"""Canonical PH layout and lossless pre-migration inventory."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

HOME = ".agents/project-harness"
ARCHIVE = f"{HOME}/archive"
CONSTITUTION = f"{HOME}/constitution.md"
CONSTRAINTS = f"{HOME}/constraints"
MEMORY = f"{HOME}/memory"
RUNTIME = f"{HOME}/runtime"
SPECS = f"{HOME}/specs"


RECORD_DIRECTORIES = {
    "架构决策": "重大架构或技术调整时读取既有决策，避免推翻已采纳方案。",
    "测试规范/前端测试规范/前端测试用例": "前端冒烟与回归时读取全部适用冒烟用例。",
    "测试规范/后端测试规范/后端测试用例": "后端冒烟与回归时读取全部适用冒烟用例。",
}


def constraint_entries(repo: Path) -> list[Path]:
    root = real_directory(repo, CONSTRAINTS)
    entries = []
    if not root.is_dir():
        return entries
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        real_directory(repo, path.parent.relative_to(repo).as_posix())
        if path.is_symlink():
            raise ValueError(f"constraint must not be a link: {relative}")
        if relative in RECORD_DIRECTORIES:
            entries.append(path)
        elif path.is_file() and not path.name.startswith("_") and not any(
            relative.startswith(directory + "/") for directory in RECORD_DIRECTORIES
        ):
            entries.append(path)
    return entries


def verify_constraints(repo: Path, release: Path) -> dict:
    """Check evidence coverage; semantic correctness remains an agent review."""
    problems = []
    template = release / "assets/scaffold" / CONSTRAINTS
    required = {p.relative_to(template).as_posix() for p in template.rglob("*.md")}
    if not template.is_dir() or not required:
        problems.append(f"missing constraint template tree: {template}")
    try:
        required.update(p.relative_to(repo / CONSTRAINTS).as_posix()
                        for p in constraint_entries(repo) if p.is_file())
    except ValueError as exc:
        problems.append(str(exc))
    report_path = repo / HOME / "init-report.json"
    report = {}
    try:
        real_directory(repo, HOME)
        if report_path.is_symlink():
            raise ValueError("content report must not be a link")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("content report must be an object")
        if report.get("format") != "ph.content/1" or report.get("project_kind") not in {"existing", "new", "upgrade"}:
            raise ValueError("invalid content report format or project_kind")
        rows = report.get("documents")
        if not isinstance(rows, dict):
            raise ValueError("content report documents must be an object")
    except (OSError, ValueError, TypeError) as exc:
        problems.append(f"content report: {exc}")
        rows = {}
    for relative in sorted(required):
        path = repo / CONSTRAINTS / relative
        try:
            real_directory(repo, path.parent.relative_to(repo).as_posix())
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"missing regular constraint: {relative}")
            text = path.read_text(encoding="utf-8")
            if path.name.startswith("_"):
                continue
            row = rows.get(relative)
            if not isinstance(row, dict):
                raise ValueError(f"missing content evidence: {relative}")
            if row.get("status") not in {"verified", "adopted", "not_applicable"}:
                raise ValueError(f"unresolved content status: {relative}")
            if row.get("sha256") != digest(path.read_bytes()):
                raise ValueError(f"content evidence is stale: {relative}")
            for key in ("evidence", "reason"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise ValueError(f"missing {key}: {relative}")
            if row.get("semantic_review") is not True:
                raise ValueError(f"semantic review not recorded: {relative}")
            if row["status"] == "not_applicable" and "不适用" not in text:
                raise ValueError(f"not-applicable decision missing from body: {relative}")
            # A small explicit marker distinguishes syntax examples from live slots.
            for line in text.splitlines():
                if "<!-- ph:placeholder-example -->" in line:
                    continue
                if re.search(r"<填写[^>]*>|\[待填写\]", line):
                    raise ValueError(f"unfilled constraint: {relative}")
            for target in re.findall(r"\]\(([^)]+)\)", text):
                local = target.split("#", 1)[0]
                if not local or "://" in local or local.startswith("mailto:"):
                    continue
                resolved = (path.parent / local).resolve()
                if not resolved.is_relative_to(repo.resolve()) or not resolved.exists():
                    raise ValueError(f"broken or external local link: {relative}: {target}")
            usage = re.search(r"^使用时机[：:]\s*(.+)$", text, re.MULTILINE)
            if not usage or "待确认" in usage.group(1):
                raise ValueError(f"missing verified usage: {relative}")
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
    if isinstance(report, dict) and report.get("migration") is not None:
        migration = report["migration"]
        try:
            if not isinstance(migration, dict):
                raise ValueError("migration evidence must be an object")
            verify_transplants(repo, migration["batch"], migration["decisions"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"migration decision stale or invalid ({exc})")
    return {"action": "verify-content", "ok": not problems, "problems": problems,
            "semantic_review_required": True}


def installed_path(source: str) -> str:
    if source == ".specify/memory/constitution.md":
        return CONSTITUTION
    if source == ".specify/memory/.constitution-template.json":
        return f"{RUNTIME}/.constitution-template.json"
    if source == ".specify" or source.startswith(".specify/"):
        return RUNTIME + source[len(".specify"):]
    return source


def source_path(installed: str) -> str:
    """The upstream staging source path for an installed runtime path."""
    if installed == CONSTITUTION:
        return ".specify/memory/constitution.md"
    if installed == f"{RUNTIME}/.constitution-template.json":
        return ".specify/memory/.constitution-template.json"
    if installed == RUNTIME or installed.startswith(RUNTIME + "/"):
        return ".specify" + installed[len(RUNTIME):]
    return installed


def convert_runtime_text(text: str, source: str) -> str:
    """Adapt pinned upstream paths, keeping source validation outside this pass."""
    text = text.replace(".specify/memory/constitution.md", CONSTITUTION)
    text = text.replace(".specify/memory/.constitution-template.json", f"{RUNTIME}/.constitution-template.json")
    text = re.sub(r"(?<![\w/.-])\.specify(?=/|[\s\"'`)]|$)", RUNTIME, text)
    text = text.replace("/.specify", "/" + RUNTIME)
    text = re.sub(r"(?<![\w.-])specs/", SPECS + "/", text)
    text = text.replace('"$REPO_ROOT/specs"', '"$REPO_ROOT/' + SPECS + '"')
    text = text.replace('"$repo_root/specs"', '"$repo_root/' + SPECS + '"')
    if source == ".specify/scripts/bash/common.sh":
        old = '(cd "$script_dir/../../.." && pwd)'
        if text.count(old) != 1:
            raise ValueError("pinned common.sh root fallback changed; review required")
        text = text.replace(old, '(cd "$script_dir/../../../../.." && pwd)')
    return text


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in (".", "..") for p in value.split("/")):
        raise ValueError(f"unsafe relative path: {value}")
    return path


def real_directory(root: Path, relative: str) -> Path:
    path = root
    if relative == ".":
        return root
    for part in safe_relative(relative).parts:
        path = path / part
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"not a real directory: {path}")
    return path


def inventory(repo: Path, roots: dict[str, str]) -> list[dict]:
    """Inventory explicitly owned roots; links are recorded without traversal."""
    if repo.is_symlink() or not repo.is_dir():
        raise ValueError("repository must be a real directory")
    entries: dict[str, dict] = {}

    def visit(path: Path, reason: str) -> None:
        rel = path.relative_to(repo).as_posix()
        if rel == ARCHIVE or rel.startswith(ARCHIVE + "/"):
            return
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            entry = {"path": rel, "kind": "link", "target": os.readlink(path)}
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise ValueError(f"hardlinked source requires review: {rel}")
            entry = {"path": rel, "kind": "file", "sha256": digest(path.read_bytes()), "mode": stat.S_IMODE(info.st_mode)}
        elif stat.S_ISDIR(info.st_mode):
            entries.setdefault(rel, {"path": rel, "kind": "directory", "reason": reason})
            for child in sorted(path.iterdir()):
                visit(child, reason)
            return
        else:
            raise ValueError(f"unsupported source type: {rel}")
        entry["reason"] = reason
        entries.setdefault(rel, entry)

    for relative, reason in sorted(roots.items()):
        if not reason.strip():
            raise ValueError(f"ownership evidence missing: {relative}")
        rel = safe_relative(relative)
        if rel.parent != PurePosixPath("."):
            real_directory(repo, rel.parent.as_posix())
        path = repo / relative
        if path.exists() or path.is_symlink():
            visit(path, reason)
    return [entries[key] for key in sorted(entries)]


def transfer_files(repo: Path, batch: str, moves: dict[str, str]) -> dict:
    """Move inventoried originals to active destinations only after full preflight."""
    base = real_directory(repo, f"{ARCHIVE}/upgrades/{batch}")
    manifest = base / "inventory.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("verified original inventory required before migration")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in payload["entries"]}
    targets: set[str] = set()
    pending: list[tuple[Path, Path, dict]] = []
    for source, target in moves.items():
        safe_relative(source)
        safe_relative(target)
        if target == ARCHIVE or target.startswith(ARCHIVE + "/"):
            raise ValueError("active migration destination must not be an archive")
        if source == target or target in targets or target in moves:
            raise ValueError("overlapping migration destinations")
        targets.add(target)
        entry = entries.get(source)
        if not entry or entry["kind"] != "file":
            raise ValueError(f"source not inventoried as a regular file: {source}")
        real_directory(repo, str(PurePosixPath(source).parent))
        real_directory(repo, str(PurePosixPath(target).parent))
        src, dest = repo / source, repo / target
        original = base / "objects" / (entry["sha256"] + ".blob")
        if original.is_symlink() or not original.is_file() or digest(original.read_bytes()) != entry["sha256"]:
            raise ValueError(f"original archive is incomplete: {source}")
        for path in (src, dest):
            if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
                raise ValueError(f"unsafe migration path: {path}")
            if path.exists() and digest(path.read_bytes()) != entry["sha256"]:
                raise ValueError(f"migration content conflict: {path}")
        if not src.exists() and not dest.exists():
            raise ValueError(f"missing source and destination: {source}")
        pending.append((src, dest, entry))
    completed = []
    for src, dest, entry in pending:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.exists() and not dest.exists():
            src.rename(dest)
        elif src.exists():
            # Keep duplicate names inert so archive never exposes an old SKILL.md.
            retained = base / "relocated" / (digest(entry["path"].encode()) + ".blob")
            if retained.exists() or retained.is_symlink():
                raise ValueError(f"retained source already exists: {entry['path']}")
            retained.parent.mkdir(parents=True, exist_ok=True)
            src.rename(retained)
        if digest(dest.read_bytes()) != entry["sha256"]:
            raise ValueError(f"destination verification failed: {dest}")
        completed.append({"source": entry["path"], "destination": dest.relative_to(repo).as_posix(), "method": "byte-preserving move"})
    return {"transferred": completed, "migration_complete": False}


def verify_transplants(repo: Path, batch: str, decisions: list[dict]) -> dict:
    """Require an explicit disposition for each preserved file, not just a backup."""
    base = real_directory(repo, f"{ARCHIVE}/upgrades/{batch}")
    manifest = base / "inventory.json"
    if manifest.is_symlink():
        raise ValueError("archive inventory must not be a link")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    originals = {entry["path"]: entry for entry in payload["entries"] if entry["kind"] != "directory"}
    mapped = {}
    for decision in decisions:
        source = decision.get("source")
        if source not in originals or source in mapped:
            raise ValueError(f"unknown or duplicate disposition: {source}")
        if not str(decision.get("evidence", "")).strip():
            raise ValueError(f"missing migration evidence: {source}")
        kind = decision.get("kind")
        if kind == "historical":
            if not str(decision.get("reason", "")).strip():
                raise ValueError(f"archive-only disposition requires a reason: {source}")
        elif kind in {"moved", "merged", "replaced", "adapter"}:
            destinations = decision.get("destinations")
            if not isinstance(destinations, list) or not destinations:
                raise ValueError(f"missing active destinations: {source}")
            for destination in destinations:
                rel = destination.get("path", "")
                safe_relative(rel)
                if rel == ARCHIVE or rel.startswith(ARCHIVE + "/"):
                    raise ValueError(f"archive is not an active destination: {rel}")
                real_directory(repo, str(PurePosixPath(rel).parent))
                path = repo / rel
                if kind == "adapter" and path.is_symlink():
                    if os.readlink(path) != destination.get("target") or not path.resolve().is_relative_to(repo.resolve()):
                        raise ValueError(f"adapter target mismatch: {rel}")
                elif path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != destination.get("sha256"):
                    raise ValueError(f"active destination not verified: {rel}")
        else:
            raise ValueError(f"unresolved migration disposition: {source}")
        mapped[source] = decision
    missing = sorted(set(originals) - set(mapped))
    if missing:
        raise ValueError("preserved but not migrated: " + ", ".join(missing))
    for entry in originals.values():
        if entry["kind"] == "file":
            path = base / "objects" / (entry["sha256"] + ".blob")
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != entry["sha256"]:
                raise ValueError(f"original archive is incomplete: {entry['path']}")
    return {"ok": True, "covered": len(mapped), "semantic_review_required": True}


def preserve(repo: Path, batch: str, roots: dict[str, str]) -> dict:
    """Preserve originals before migration; never certify migration completion."""
    if len(safe_relative(batch).parts) != 1:
        raise ValueError("batch must be a single directory name")
    base = real_directory(repo, f"{ARCHIVE}/upgrades/{batch}")
    manifest = base / "inventory.json"
    if manifest.is_symlink():
        raise ValueError("archive inventory must not be a link")
    entries = inventory(repo, roots)
    payload = {"format": "ph.originals/1", "roots": roots, "entries": entries}
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    if manifest.exists() and manifest.read_bytes() != encoded:
        raise ValueError("source inventory changed; refusing to redefine an existing archive batch")
    # The original path is only metadata. A digest names each inert archive object,
    # so archived SKILL.md/AGENTS.md files cannot become discoverable instructions.
    objects = real_directory(repo, f"{ARCHIVE}/upgrades/{batch}/objects")
    pending: list[tuple[Path, bytes, dict]] = []
    for entry in entries:
        if entry["kind"] != "file":
            continue
        data = (repo / entry["path"]).read_bytes()
        if digest(data) != entry["sha256"]:
            raise ValueError(f"source changed during inventory: {entry['path']}")
        target = objects / (entry["sha256"] + ".blob")
        if target.is_symlink() or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1 or target.read_bytes() != data)):
            raise ValueError(f"archive object conflict: {target}")
        pending.append((target, data, entry))
    objects.mkdir(parents=True, exist_ok=True)
    for target, data, entry in pending:
        if not target.exists():
            with target.open("xb") as out:
                out.write(data)
        if digest(target.read_bytes()) != entry["sha256"]:
            raise ValueError(f"archive verification failed: {entry['path']}")
    if not manifest.exists():
        with manifest.open("xb") as out:
            out.write(encoded)
    elif manifest.read_bytes() != encoded:
        raise ValueError("archive inventory changed during preservation")
    return {"archive": base.relative_to(repo).as_posix(), "preserved": len(entries), "migration_complete": False}


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Preserve and verify explicitly inventoried PH content")
    parser.add_argument("action", choices=("preserve", "verify-transplants"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--plan", required=True, help="JSON containing roots or decisions; no secrets")
    args = parser.parse_args()
    try:
        repo = Path(args.repo).resolve(strict=True)
        payload = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        if args.action == "preserve":
            result = preserve(repo, args.batch, payload["roots"])
        else:
            result = verify_transplants(repo, args.batch, payload["decisions"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
