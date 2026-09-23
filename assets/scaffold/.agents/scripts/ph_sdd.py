#!/usr/bin/env python3
"""Self-built SDD runtime plumbing for Project Harness (no SpecKit binding).

A minimal, stdlib-only CLI that keeps the mechanical state of spec-driven
work in stable feature directories. It never writes prose, never runs git,
never merges, never leaves a worktree, never touches memory archives, and
never claims semantic or real-acceptance guarantees: every status in the
metadata was set by an explicit call that had to carry the user's decision
(note) or real evidence (a file whose hash is recorded). The calling skill
owns the semantics; this script owns consistency.

Paths (all repo-relative):

* specs root      .agents/project-harness/specs/<id>/
* metadata        <feature>/ph-feature.json        (schema ph-feature/1)
* archive root    .agents/project-harness/archive/features/
* archive index   .agents/project-harness/archive/features/index.json
* legacy pointer  .agents/project-harness/runtime/feature.json  (read-only)
* templates       .agents/project-harness/runtime/templates/sdd/  (reference)

Artifact mapping per flow (files live at the feature root):

* full:  requirement.md design.md review.md tasks.md verify-plan.md
         acceptance.md verification.md
* small: change.md replaces requirement/design (and the design review);
         tasks / verify-plan / acceptance / verification are shared.
* legacy: old SpecKit feature dirs (spec.md / plan.md, no metadata) are
         read-only compatible. ``adopt`` maps spec.md->requirement,
         plan.md->design without editing originals, without copying numbers
         or evidence, and with every status pending explicit verification -
         checkbox state is never interpreted.

Statuses (only via explicit ``mark``; non-draft and every change needs
--note or --evidence):

* requirement/change/design/review/verify-plan: draft, reviewed
* tasks:            draft, done, not_applicable
* acceptance/verification: draft, passed, not_applicable

Gates (consistency only, not truth):

* review-before-tasks: tasks exist or are marked only when the definer
  (requirement for full, change for small) AND design (full) are reviewed.
* design reviewed binds the review artifact: review.md must exist, its hash
  and the requirement fingerprint at review time are recorded, so a later
  requirement change stalls the design review (basis drift).
* drift: a file no longer matching its recorded fingerprint, or a missing /
  changed evidence file, is reported as 待复核 (needs re-review). Statuses
  are never auto-revoked and never fake a pass; downstream marks and archive
  are blocked until the drifted record is re-confirmed by an explicit mark.
* archive-readiness: tasks done, acceptance passed, verification passed -
  or an explicit not_applicable WITH a recorded reason. Silence or missing
  user feedback is not a reason the tool can record on its own.

Archive is transactional and append-only: a full read-only snapshot under
archive/features/<id>/<UTC-timestamp>/ (external evidence files are copied
into the snapshot's ``_evidence/`` with an original-path/hash mapping) plus
an entry in the stable index. A journal makes the copy -> index -> metadata
sequence recoverable: an interrupted archive is completed on the next run
without duplicating entries, and no failure ever touches the original
feature files. Identical content AND an identical decision (note + evidence)
archive as ``unchanged``; the consistency gates always run first, so a
drifted feature never archives and never reports unchanged. Every mutating
apply (create/adopt/mark/archive) holds a repo-managed mutex lock
(``.agents/project-harness/.sdd.lock``); dry-runs never lock or write, and
a live lock is refused, never seized.

Dry-run is the default for every mutating command; ``--apply`` executes.
Governance concerns (constitution, navigation, content verification) are out
of scope here and belong to the distribution-side governance tooling.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FLOWS = {
    "full": ("requirement", "design", "review", "tasks", "verify-plan", "acceptance", "verification"),
    "small": ("change", "tasks", "verify-plan", "acceptance", "verification"),
}
STATUSES = {
    "requirement": ("draft", "reviewed"),
    "change": ("draft", "reviewed"),
    "design": ("draft", "reviewed"),
    "review": ("draft", "reviewed"),
    "verify-plan": ("draft", "reviewed"),
    "tasks": ("draft", "done", "not_applicable"),
    "acceptance": ("draft", "passed", "not_applicable"),
    "verification": ("draft", "passed", "not_applicable"),
}
SPECS_ROOT = ".agents/project-harness/specs"
ARCHIVE_ROOT = ".agents/project-harness/archive/features"
METADATA_NAME = "ph-feature.json"
METADATA_SCHEMA = "ph-feature/1"
ARCHIVE_INDEX_NAME = "index.json"
ARCHIVE_INDEX_SCHEMA = "ph-archive-index/1"
ARCHIVE_JOURNAL_SCHEMA = "ph-archive-journal/1"
ARCHIVE_EVIDENCE_SCHEMA = "ph-evidence-manifest/1"
EVIDENCE_DIR = "_evidence"
SDD_LOCK_NAME = ".sdd.lock"
LEGACY_POINTER = ".agents/project-harness/runtime/feature.json"
DEFINER = {"full": "requirement", "small": "change"}
LEGACY_DISPLAY = ("spec", "plan", "research", "data-model", "quickstart", "tasks", "verification")
CREATE_ID_PATTERN = re.compile(r"^[0-9]{3,}(-[a-z0-9]+)*$")
REF_TOKEN_RE = re.compile(r"\b(?:FR|NFR|AC)-[0-9]+\b")
HEX64 = set("0123456789abcdef")


class PHsddError(Exception):
    """User-facing failure that must become a non-zero exit, not a traceback."""


# ---------------------------------------------------------------------------
# Path safety (same model as ph_human.py)
# ---------------------------------------------------------------------------


def is_safe_rel(rel: str) -> bool:
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "~")) or "\\" in rel or "\0" in rel:
        return False
    if len(rel) > 1 and rel[1] == ":":
        return False
    return all(part not in {"", ".", ".."} for part in rel.split("/"))


def is_safe_name(name: str) -> bool:
    """A single repository path segment usable as a feature directory name."""
    return bool(is_safe_rel(name)) and "/" not in name and not name.startswith(".") and len(name) <= 80


def is_hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in HEX64 for c in value)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_file_bytes(path: Path) -> bytes:
    """Bytes with an honest error: an unreadable file is a user-facing
    failure, never a raw traceback."""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PHsddError(f"无法读取文件 {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    return sha256_bytes(read_file_bytes(path))


def is_hardlink(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and not path.is_symlink() and path.stat().st_nlink > 1
    except OSError:
        return False


def is_disallowed_reparse(path: Path) -> bool:
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
        raise PHsddError(f"{label} is not a safe repository-relative path: {rel!r}")
    path = repo / rel
    issue = path_issue(repo, path)
    if issue:
        raise PHsddError(f"{label} 路径不安全: {rel}（{issue}）")
    if not path.is_file():
        raise PHsddError(f"{label} 不存在或不是常规文件: {rel}")
    return path


def require_real_dir(repo: Path, rel: str, label: str) -> Path:
    if not is_safe_rel(rel):
        raise PHsddError(f"{label} is not a safe repository-relative path: {rel!r}")
    path = repo / rel
    issue = path_issue(repo, path)
    if issue or not path.is_dir():
        raise PHsddError(f"{label} 必须是仓库内真实目录: {rel}" + (f"（{issue}）" if issue else ""))
    return path


def atomic_write(path: Path, data: bytes) -> None:
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
            tmp.unlink()
        raise


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_repo(explicit: str) -> Path:
    repo = Path(explicit).expanduser().resolve()
    if not repo.is_dir():
        raise PHsddError(f"repository root is not a directory: {repo}")
    return repo


def is_safe_unicode_name(name: str) -> bool:
    """A single safe path segment for historical feature directory names.

    Unlike create ids, adopt must accept the names older flows actually
    created on disk (e.g. ``001-登录功能`` or ``20260101-legacy-auth``):
    any non-control Unicode is allowed as long as the segment cannot escape
    the specs root or confuse path handling. The original directory is never
    renamed.
    """
    if not isinstance(name, str) or not name or len(name) > 80:
        return False
    if name != name.strip() or name.startswith("."):
        return False
    if any(ch in name for ch in "/\\<>:\"|?*"):
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return False
    return is_safe_rel(name)


def visible_children(directory: Path) -> list[str]:
    """Entries a user would see: dotfiles such as .DS_Store never count as
    feature content, for create preflight and status classification alike."""
    return sorted(p.name for p in directory.iterdir() if not p.name.startswith("."))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


@contextlib.contextmanager
def sdd_lock(repo: Path, command: str):
    """Repo-managed mutex for mutating apply runs. A live holder is refused,
    never seized; a provably dead holder (pid gone) is cleaned up so a crash
    cannot block the project forever. Dry-runs never call this."""
    path = repo / ".agents/project-harness" / SDD_LOCK_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = None
            try:
                holder = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                holder = None
            if isinstance(holder, dict) and isinstance(holder.get("pid"), int):
                if _pid_alive(holder["pid"]):
                    raise PHsddError(
                        f"另一个 ph_sdd 写操作正在进行（PID {holder['pid']}，"
                        f"{holder.get('command', '?')}，始于 {holder.get('at', '?')}）；"
                        "已拒绝并发写入（不抢锁），请等待其结束后重试"
                    )
                os.unlink(path)  # holder pid no longer exists: provably stale
                continue
            raise PHsddError(
                f"存在无法识别的锁文件 {path}（内容不是本工具的锁记录）；"
                "请人工确认没有 ph_sdd 进程在运行后移除该文件再重试"
            )
    try:
        os.write(fd, (json.dumps({"pid": os.getpid(), "command": command, "at": now_utc()},
                                 ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _force_remove_tree(path: Path) -> None:
    """Remove a tool-created tree even when parts were chmod'd read-only."""
    if not path.exists() and not path.is_symlink():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        try:
            os.chmod(child, 0o755 if child.is_dir() else 0o644)
        except OSError:
            pass
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Feature resolution and metadata
# ---------------------------------------------------------------------------


def metadata_rel(feature: str) -> str:
    return f"{SPECS_ROOT}/{feature}/{METADATA_NAME}"


def artifact_file(meta: dict, artifact: str) -> str:
    return meta.get("files", {}).get(artifact, f"{artifact}.md")


def validate_meta(meta: object, feature: str) -> dict:
    """Structural validation; anything else is user content and refused."""
    invalid = f"{metadata_rel(feature)} 不是本工具管理的有效元数据（视为用户内容，已拒绝写入）"
    if not isinstance(meta, dict) or meta.get("schema") != METADATA_SCHEMA:
        raise PHsddError(invalid)
    if meta.get("id") != feature or meta.get("flow") not in FLOWS:
        raise PHsddError(invalid)
    flow = meta["flow"]
    artifacts = meta.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PHsddError(invalid)
    for name, record in artifacts.items():
        if name not in FLOWS[flow] or not isinstance(record, dict):
            raise PHsddError(invalid)
        if record.get("status") not in STATUSES[name] or not is_hex64(record.get("fingerprint", "")):
            raise PHsddError(invalid)
        if not isinstance(record.get("history", []), list):
            raise PHsddError(invalid)
    files = meta.get("files", {})
    if not isinstance(files, dict) or any(
        key not in FLOWS[flow] or not is_safe_name(value) or not value.endswith(".md")
        for key, value in files.items()
    ):
        raise PHsddError(invalid)
    if not isinstance(meta.get("archive", []), list):
        raise PHsddError(invalid)
    return meta


def load_meta(repo: Path, feature: str) -> dict | None:
    path = repo / metadata_rel(feature)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PHsddError(
            f"{metadata_rel(feature)} 无法解析（{exc}）；它不是本工具管理的有效元数据，视为用户内容，已拒绝写入"
        ) from exc
    return validate_meta(raw, feature)


def resolve_feature(repo: Path, feature: str, label: str = "feature") -> tuple[str, Path]:
    if not is_safe_name(feature):
        raise PHsddError(f"{label} 不是安全的单段目录名: {feature!r}")
    rel = f"{SPECS_ROOT}/{feature}"
    path = require_real_dir(repo, rel, label)
    return rel, path


def new_metadata(feature: str, flow: str, title: str, files: dict | None = None) -> dict:
    stamp = now_utc()
    meta = {
        "schema": METADATA_SCHEMA,
        "id": feature,
        "flow": flow,
        "title": title,
        "created": stamp,
        "updated": stamp,
        "artifacts": {},
        "archive": [],
    }
    if files:
        meta["files"] = dict(files)
        meta["adopted_from"] = dict(files)
    return meta


def save_meta(repo: Path, feature: str, meta: dict) -> None:
    meta["updated"] = now_utc()
    path = repo / metadata_rel(feature)
    issue = path_issue(repo, path)
    if issue:
        raise PHsddError(f"拒绝写入元数据：{issue}")
    atomic_write(path, (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# Evidence and drift detection
# ---------------------------------------------------------------------------


def resolve_evidence(repo: Path, raw: str) -> Path:
    """Evidence may live outside the repository; it must be a real regular file."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = repo / candidate
    if candidate.is_symlink() or not candidate.is_file():
        raise PHsddError(f"取证文件必须是真实常规文件（不接受符号链接或缺失路径）: {raw}")
    try:
        candidate.relative_to(repo.absolute())
        issue = path_issue(repo, candidate)
        if issue:
            raise PHsddError(f"取证文件路径不安全: {issue}")
    except ValueError:
        pass  # outside the repository on purpose; the regular-file check above holds
    return candidate


def evidence_record(repo: Path, raw: str) -> dict:
    path = resolve_evidence(repo, raw)
    data = read_file_bytes(path)
    return {"path": raw, "sha256": sha256_bytes(data), "bytes": len(data)}


def evidence_issue(repo: Path, record: dict) -> str | None:
    """None when the recorded evidence file still exists with the same bytes."""
    try:
        path = resolve_evidence(repo, record["path"])
    except PHsddError:
        return f"的取证文件 {record['path']} 缺失"
    if sha256_file(path) != record.get("sha256"):
        return f"的取证文件 {record['path']} 内容已变化"
    return None


# Downstream completion order used by basis handling: an upstream re-mark
# must never be blocked by its own stale downstream records, so drift
# blocking compares these ranks.
ARTIFACT_RANK = {
    "full": {"requirement": 0, "design": 1, "review": 1, "tasks": 2,
             "verify-plan": 3, "verification": 4, "acceptance": 5},
    "small": {"change": 0, "tasks": 1, "verify-plan": 2, "verification": 3, "acceptance": 4},
}


def basis_upstreams(flow: str, artifact: str) -> tuple[str, ...]:
    """The upstream set a completion record binds itself to. verification
    never binds acceptance (that would loop); acceptance binds verification
    (its evidence identity is bound separately)."""
    definer = DEFINER[flow]
    design = ("design",) if flow == "full" else ()
    if artifact == "design":
        return ("requirement", "review")
    if artifact == "tasks":
        return (definer,) + design
    if artifact == "verify-plan":
        return (definer,) + design + ("tasks",)
    if artifact == "verification":
        return (definer,) + design + ("tasks", "verify-plan")
    if artifact == "acceptance":
        return (definer, "verification")
    return ()


def effective_fingerprint(meta: dict, feature_dir: Path, artifact: str) -> str | None:
    """The fingerprint an upstream contributes right now: its recorded
    fingerprint when marked, otherwise the hash of its on-disk file."""
    record = meta["artifacts"].get(artifact)
    if record:
        return record["fingerprint"]
    path = feature_dir / artifact_file(meta, artifact)
    return sha256_file(path) if path.is_file() else None


def collect_drifts(repo: Path, meta: dict, feature_dir: Path) -> list[dict]:
    """Every recorded fact that no longer matches reality (待复核 items)."""
    drifts: list[dict] = []
    for artifact in FLOWS[meta["flow"]]:
        record = meta["artifacts"].get(artifact)
        if not record:
            continue
        path = feature_dir / artifact_file(meta, artifact)
        issue = path_issue(repo, path)
        if issue or not path.is_file():
            drifts.append({
                "artifact": artifact,
                "kind": "missing",
                "message": f"「{artifact}」的产物文件 {artifact_file(meta, artifact)} 缺失或不可读，处于待复核状态",
            })
        elif sha256_file(path) != record["fingerprint"]:
            drifts.append({
                "artifact": artifact,
                "kind": "content",
                "message": f"「{artifact}」内容与记录的指纹不一致，处于待复核状态；"
                           "请人工复审后重新 mark（状态不会被自动撤销，也不会被冒充为通过）",
            })
        if record.get("evidence"):
            problem = evidence_issue(repo, record["evidence"])
            if problem:
                drifts.append({
                    "artifact": artifact,
                    "kind": "evidence",
                    "message": f"「{artifact}」{problem}，处于待复核状态；请重新取证后 mark",
                })
    # Downstream completion records bind the fingerprints of the artifacts
    # they were based on: an upstream re-mark stales every downstream record
    # (basis drift) until that record is re-marked itself. verification never
    # binds acceptance (no loop); acceptance binds verification's evidence
    # identity, so re-marking verification invalidates a passed acceptance.
    for artifact in FLOWS[meta["flow"]]:
        record = meta["artifacts"].get(artifact)
        if not record:
            continue
        basis = record.get("basis")
        if isinstance(basis, dict):
            for upstream, expected in basis.items():
                if effective_fingerprint(meta, feature_dir, upstream) != expected:
                    drifts.append({
                        "artifact": artifact,
                        "kind": "basis",
                        "message": f"「{artifact}」记录所依据的 {upstream} 内容已变化（basis 漂移），"
                                   "处于待复核状态；请复审后重新 mark",
                    })
        if artifact == "acceptance" and isinstance(record.get("verification_evidence"), dict):
            bound = record["verification_evidence"]
            verification = meta["artifacts"].get("verification")
            current_sha = ((verification or {}).get("evidence") or {}).get("sha256")
            if current_sha != bound.get("sha256"):
                drifts.append({
                    "artifact": "acceptance",
                    "kind": "basis",
                    "message": "「acceptance」绑定的 verification 证据身份已变化（验证成果被重新标记），"
                               "处于待复核状态；请复审后重新 mark",
                })
    return drifts


# ---------------------------------------------------------------------------
# Gate evaluation shared by check / archive
# ---------------------------------------------------------------------------


def review_gate_errors(meta: dict, feature_dir: Path, drifts: list[dict]) -> list[dict]:
    """review-before-tasks: tasks may exist or be marked only after review."""
    tasks_on_disk = (feature_dir / artifact_file(meta, "tasks")).is_file()
    tasks_record = meta["artifacts"].get("tasks")
    if not tasks_on_disk and not tasks_record:
        return []
    drifted = {d["artifact"] for d in drifts}
    errors: list[dict] = []
    definer = DEFINER[meta["flow"]]
    required = [definer] + (["design"] if meta["flow"] == "full" else [])
    for name in required:
        record = meta["artifacts"].get(name)
        if not record:
            errors.append({
                "gate": "review-before-tasks",
                "message": f"任务（tasks）推进前必须完成评审：{meta['flow']} 流程要求 {name} 已 reviewed，当前未评审",
            })
        elif record["status"] != "reviewed":
            errors.append({
                "gate": "review-before-tasks",
                "message": f"任务（tasks）推进前必须完成评审：{meta['flow']} 流程要求 {name} 已 reviewed，"
                           f"当前为 {record['status']}",
            })
        elif name in drifted:
            errors.append({
                "gate": "review-before-tasks",
                "message": f"任务（tasks）推进被阻断：{name} 处于待复核状态，请先复审并重新 mark",
            })
    return errors


def archive_gate_errors(meta: dict, drifts: list[dict]) -> list[dict]:
    """archive-readiness: tasks done + acceptance/verification passed (or an
    explicit not_applicable with a recorded reason); no drift may remain."""
    errors: list[dict] = []
    for artifact, passing in (("tasks", "done"), ("acceptance", "passed"), ("verification", "passed")):
        record = meta["artifacts"].get(artifact)
        if record and record["status"] in (passing, "not_applicable"):
            continue
        current = record["status"] if record else "未标记"
        errors.append({
            "gate": "archive-readiness",
            "message": (
                f"归档前要求 {artifact} 已 {passing}，或显式 not_applicable 并注明理由；"
                f"当前为 {current}（用户未反馈不构成 not_applicable 的理由）"
            ),
        })
    for drift in drifts:
        errors.append({"gate": "archive-readiness", "message": drift["message"]})
    return errors


def _read_utf8(path: Path) -> tuple[str, bool]:
    """Decode UTF-8 honestly: an undecodable artifact is reported, never
    silently treated as empty text."""
    try:
        return path.read_text(encoding="utf-8"), True
    except (UnicodeDecodeError, OSError):
        return "", False


def reference_warnings(meta: dict, feature_dir: Path) -> list[dict]:
    """Syntactic numbered-reference check (FR-N / NFR-N / AC-N). No semantic claim."""
    warnings: list[dict] = []

    def content(path: Path) -> str | None:
        if not path.is_file():
            return None
        text, ok = _read_utf8(path)
        if not ok:
            warnings.append({
                "gate": "encoding",
                "message": f"{path.name} 不是有效 UTF-8 文本，已跳过其编号引用解析"
                           "（这不会使任何状态被判定为通过）",
            })
            return None
        return text

    defined: set[str] = set()
    definer = DEFINER[meta["flow"]]
    definer_file = feature_dir / artifact_file(meta, definer)
    acceptance_file = feature_dir / artifact_file(meta, "acceptance")
    # AC-n may be defined at requirement time (the user's acceptance ask) in
    # the definer, or later in acceptance.md; both count as definitions.
    for path, families in ((definer_file, ("FR", "NFR", "AC")), (acceptance_file, ("AC",))):
        text = content(path)
        if text is None:
            continue
        for family in families:
            defined.update(token for token in REF_TOKEN_RE.findall(text) if token.startswith(f"{family}-"))
    seen: set[tuple[str, str]] = set()
    for artifact in ("design", "tasks", "verify-plan", "verification"):
        path = feature_dir / artifact_file(meta, artifact)
        text = content(path)
        if text is None:
            continue
        for token in sorted(set(REF_TOKEN_RE.findall(text))):
            if token in defined or (artifact, token) in seen:
                continue
            seen.add((artifact, token))
            warnings.append({
                "gate": "references",
                "message": f"{artifact_file(meta, artifact)} 引用了未定义的 {token}"
                           f"（编号定义应位于 {definer_file.name} 或 {acceptance_file.name}）",
            })
    return warnings


def stray_warnings(meta: dict, feature_dir: Path) -> list[dict]:
    warnings: list[dict] = []
    if meta["flow"] == "full" and (feature_dir / "change.md").is_file():
        warnings.append({
            "gate": "stray",
            "message": "full 流程不使用 change.md（small 流程才以 change.md 替代 requirement 与 design）",
        })
    elif meta["flow"] == "small":
        for name in ("requirement", "design", "review"):
            if (feature_dir / f"{name}.md").is_file():
                warnings.append({
                    "gate": "stray",
                    "message": f"small 流程以 change.md 替代 requirement 与 design，检测到未使用的 {name}.md",
                })
    return warnings


def artifact_entries(meta: dict, feature_dir: Path, drifts: list[dict]) -> list[dict]:
    by_artifact: dict[str, list[dict]] = {}
    for drift in drifts:
        by_artifact.setdefault(drift["artifact"], []).append(drift)
    entries = []
    for artifact in FLOWS[meta["flow"]]:
        record = meta["artifacts"].get(artifact)
        name = artifact_file(meta, artifact)
        on_disk = (feature_dir / name).is_file()
        if record:
            status = record["status"]
        elif on_disk:
            status = "unmarked"
        else:
            status = "absent"
        issues = by_artifact.get(artifact, [])
        entries.append({
            "name": artifact,
            "file": name,
            "on_disk": on_disk,
            "status": status,
            "recorded": bool(record),
            "drift": any(i["kind"] in ("content", "missing", "basis", "review") for i in issues),
            "drift_message": next((i["message"] for i in issues
                                   if i["kind"] in ("content", "missing", "basis", "review")), ""),
            "evidence_ok": (not any(i["kind"] == "evidence" for i in issues)) if record else None,
        })
    return entries


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_create(repo: Path, feature: str, flow: str, title: str, apply: bool) -> tuple[dict, int]:
    if flow not in FLOWS:
        raise PHsddError(f"flow 必须是 {' 或 '.join(FLOWS)}")
    if not title or not title.strip():
        raise PHsddError("title 不能为空：请写出这项功能是什么")
    if not CREATE_ID_PATTERN.match(feature) or not is_safe_name(feature):
        raise PHsddError(f"feature 编号无效（应为 001 或 001-短横线小写名）: {feature!r}")
    feature_dir = repo / SPECS_ROOT / feature
    exists = feature_dir.exists() or feature_dir.is_symlink()
    legacy_hint = ""
    plan: list[str] = []
    if exists:
        issue = path_issue(repo, feature_dir)
        if issue or not feature_dir.is_dir():
            raise PHsddError(f"feature 路径不可用: {issue or '不是目录'}")
        children = visible_children(feature_dir)  # dotfiles (.DS_Store ...) are not content
        if children:
            if "spec.md" in children or "plan.md" in children:
                legacy_hint = "；检测到旧 SpecKit 产物（spec.md/plan.md），如需接续请使用 adopt"
            plan.append(f"目录已存在且非空，--apply 将被拒绝: {SPECS_ROOT}/{feature}")
    plan.append(f"创建目录 {SPECS_ROOT}/{feature}/（已存在则复用）")
    plan.append(f"写入元数据 {metadata_rel(feature)}（flow={flow}，不创建任何产物文件）")
    payload = {
        "action": "create",
        "dry_run": not apply,
        "feature": feature,
        "feature_rel": f"{SPECS_ROOT}/{feature}",
        "flow": flow,
        "title": title,
        "exists": exists,
        "plan": plan,
    }
    if legacy_hint:
        payload["note"] = legacy_hint.lstrip("；")
    if not apply:
        return payload, 0
    if exists and visible_children(feature_dir):
        raise PHsddError(
            f"feature 目录已存在且非空: {SPECS_ROOT}/{feature}{legacy_hint or '（拒绝覆盖任何既有内容）'}"
        )
    issue = path_issue(repo, feature_dir)
    if issue:
        raise PHsddError(f"拒绝创建：{issue}")
    if (repo / metadata_rel(feature)).exists():
        raise PHsddError(f"元数据已存在: {metadata_rel(feature)}（拒绝覆盖）")
    with sdd_lock(repo, f"create {feature}"):
        if (repo / metadata_rel(feature)).exists():
            raise PHsddError(f"元数据已存在: {metadata_rel(feature)}（拒绝覆盖）")
        feature_dir.mkdir(parents=True, exist_ok=True)
        save_meta(repo, feature, new_metadata(feature, flow, title.strip()))
    payload["created"] = True
    return payload, 0


def cmd_adopt(repo: Path, feature: str, title: str | None, apply: bool) -> tuple[dict, int]:
    # adopt accepts the safe historical directory names older flows actually
    # created (including non-ASCII like 001-登录功能); the directory is never renamed
    if not is_safe_unicode_name(feature):
        raise PHsddError(f"feature 名不是安全的历史目录名: {feature!r}")
    rel, _ = resolve_feature(repo, feature, "feature")
    if (repo / metadata_rel(feature)).exists():
        raise PHsddError(f"{metadata_rel(feature)} 已存在；已有元数据的功能不需要 adopt")
    files: dict[str, str] = {}
    if (repo / SPECS_ROOT / feature / "spec.md").is_file() and not (repo / SPECS_ROOT / feature / "requirement.md").is_file():
        files["requirement"] = "spec.md"
    if (repo / SPECS_ROOT / feature / "plan.md").is_file() and not (repo / SPECS_ROOT / feature / "design.md").is_file():
        files["design"] = "plan.md"
    if not files:
        raise PHsddError(
            f"{rel} 中未发现可接续的旧产物（需要 spec.md 或 plan.md）；普通目录请改用 create"
        )
    payload = {
        "action": "adopt",
        "dry_run": not apply,
        "feature": feature,
        "feature_rel": rel,
        "flow": "full",
        "files": files,
        "plan": [
            f"写入元数据 {metadata_rel(feature)}（flow=full，状态全部待核验）",
            "原 spec.md/plan.md 等文件保持原样，不迁移、不改编号、不读取勾选状态",
        ],
        "note": "接续后所有产物状态为待核验（unmarked）；继续推进需按 full 流程补齐真实评审与验收",
    }
    if not apply:
        return payload, 0
    with sdd_lock(repo, f"adopt {feature}"):
        if (repo / metadata_rel(feature)).exists():
            raise PHsddError(f"{metadata_rel(feature)} 已存在；已有元数据的功能不需要 adopt")
        save_meta(repo, feature, new_metadata(feature, "full", (title or feature).strip(), files))
    payload["adopted"] = True
    return payload, 0


def cmd_mark(repo: Path, feature: str, artifact: str, status: str, note: str | None,
             evidence: str | None, apply: bool) -> tuple[dict, int]:
    _, feature_dir = resolve_feature(repo, feature)
    meta = load_meta(repo, feature)
    if meta is None:
        raise PHsddError(
            f"{metadata_rel(feature)} 不存在：legacy 目录只兼容读取，如需接续旧需求请使用 adopt 建立元数据"
        )
    if artifact not in FLOWS[meta["flow"]]:
        raise PHsddError(
            f"{meta['flow']} 流程不使用产物 {artifact}（可用: {', '.join(FLOWS[meta['flow']])}）"
        )
    if status not in STATUSES[artifact]:
        raise PHsddError(f"{artifact} 的状态只能是 {' / '.join(STATUSES[artifact])}，收到 {status!r}")
    file_name = artifact_file(meta, artifact)
    require_real_file(repo, f"{SPECS_ROOT}/{feature}/{file_name}", f"产物 {artifact}（{file_name}）")
    record = meta["artifacts"].get(artifact)
    current = record["status"] if record else None
    needs_input = status != "draft" or (record is not None and current != "draft")
    if needs_input and not note and not evidence:
        raise PHsddError(
            f"标记 {artifact} 为 {status} 需要显式输入：--note（用户决定原文）或 --evidence（真实证据文件）；"
            "工具只记录，不代替用户决定"
        )
    drifts = collect_drifts(repo, meta, feature_dir)
    # Drift blocking is rank-aware: an upstream re-mark must never be blocked
    # by its own stale downstream records - fixing the upstream IS the remedy.
    rank = ARTIFACT_RANK[meta["flow"]]
    for drift in drifts:
        other = drift["artifact"]
        if other == artifact or rank.get(other, 99) > rank.get(artifact, 99):
            continue
        raise PHsddError(f"存在待复核项，先处理 {other} 再继续：{drift['message']}")
    if artifact == "tasks":
        definer = DEFINER[meta["flow"]]
        required = [definer] + (["design"] if meta["flow"] == "full" else [])
        for name in required:
            gate_record = meta["artifacts"].get(name)
            if not gate_record or gate_record["status"] != "reviewed":
                raise PHsddError(
                    f"任务（tasks）推进前必须完成评审：{meta['flow']} 流程要求 {name} 已 reviewed，"
                    f"当前为{'未评审' if not gate_record else gate_record['status']}"
                )
    fingerprint = sha256_file(feature_dir / file_name)
    evidence_rec = evidence_record(repo, evidence) if evidence else None
    # Bind this record to the current content of its upstream set; a missing
    # upstream (no file, no record) is a hard error, never an empty binding.
    basis: dict[str, str] = {}
    for upstream in basis_upstreams(meta["flow"], artifact):
        upstream_fp = effective_fingerprint(meta, feature_dir, upstream)
        if upstream_fp is None:
            raise PHsddError(
                f"标记 {artifact} 需要前置产物 {artifact_file(meta, upstream)}（{upstream}）已存在"
                "（文件或已标记记录），当前缺失"
            )
        basis[upstream] = upstream_fp
    verification_evidence = None
    if artifact == "acceptance":
        verification = meta["artifacts"].get("verification")
        verification_evidence = (verification or {}).get("evidence")
    self_drift = any(d["artifact"] == artifact for d in drifts)
    if (not self_drift and record and record["status"] == status
            and record["fingerprint"] == fingerprint
            and (record.get("note") or None) == note
            and (record.get("evidence") or None) == evidence_rec):
        return {
            "action": "mark",
            "dry_run": False,
            "feature": feature,
            "artifact": artifact,
            "status": status,
            "unchanged": True,
        }, 0
    payload = {
        "action": "mark",
        "dry_run": not apply,
        "feature": feature,
        "artifact": artifact,
        "file": file_name,
        "status": status,
        "previous": current,
        "fingerprint": fingerprint,
        "note": note,
        "evidence": evidence_rec,
    }
    if basis:
        payload["basis"] = basis
    if artifact == "acceptance":
        payload["verification_evidence"] = verification_evidence
    if not apply:
        return payload, 0
    with sdd_lock(repo, f"mark {feature}/{artifact}"):
        meta = load_meta(repo, feature)
        if meta is None:
            raise PHsddError(f"{metadata_rel(feature)} 不存在")
        prior = meta["artifacts"].get(artifact)
        if (prior and prior["status"] == status and prior["fingerprint"] == fingerprint
                and (prior.get("note") or None) == note
                and (prior.get("evidence") or None) == evidence_rec):
            return {
                "action": "mark", "dry_run": False, "feature": feature,
                "artifact": artifact, "status": status, "unchanged": True,
            }, 0
        prior_history = prior.get("history", []) if prior else []
        event = {"status": status, "at": now_utc(), "note": note, "evidence": evidence_rec}
        entry = {
            "status": status,
            "status_at": event["at"],
            "note": note,
            "evidence": evidence_rec,
            "fingerprint": fingerprint,
            "fingerprint_at": now_utc(),
            "history": [*prior_history, event],
        }
        if basis:
            entry["basis"] = basis
        if artifact == "acceptance":
            entry["verification_evidence"] = verification_evidence
        meta["artifacts"][artifact] = entry
        save_meta(repo, feature, meta)
    payload["applied"] = True
    return payload, 0


def classify_feature(repo: Path, name: str) -> dict:
    rel = f"{SPECS_ROOT}/{name}"
    feature_dir = repo / rel
    has_files = any(not child.name.startswith(".") for child in feature_dir.iterdir())
    if not has_files:
        entry = {
            "id": name, "feature_rel": rel, "flow": "empty", "title": None,
            "artifacts": [], "archive_count": 0, "readonly": True, "metadata_state": "absent",
            "note": "空目录；可用 create 建立新功能",
        }
        return entry
    try:
        meta = load_meta(repo, name)
    except PHsddError:
        return {
            "id": name, "feature_rel": rel, "flow": "invalid", "title": None,
            "artifacts": [], "archive_count": 0, "readonly": True, "metadata_state": "invalid",
            "note": "元数据无法解析或结构无效（视为用户内容）；本工具不做门禁判断",
        }
    if meta is not None:
        return build_managed_entry(repo, meta, feature_dir)
    if (feature_dir / "spec.md").is_file() or (feature_dir / "plan.md").is_file():
        artifacts = [
            {"name": stem, "file": f"{stem}.md", "on_disk": True, "status": "unrecorded"}
            for stem in LEGACY_DISPLAY if (feature_dir / f"{stem}.md").is_file()
        ]
        return {
            "id": name, "feature_rel": rel, "flow": "legacy", "title": None,
            "artifacts": artifacts, "archive_count": 0, "readonly": True,
            "metadata_state": "absent",
            "note": "旧 SpecKit 功能目录只兼容读取，状态不虚构；如需接续请使用 adopt 建立元数据",
        }
    return {
        "id": name, "feature_rel": rel, "flow": "unmanaged", "title": None,
        "artifacts": [], "archive_count": 0, "readonly": True, "metadata_state": "absent",
        "note": "目录无元数据且无可识别旧产物；本工具不管理该目录",
    }


def build_managed_entry(repo: Path, meta: dict, feature_dir: Path) -> dict:
    drifts = collect_drifts(repo, meta, feature_dir)
    return {
        "id": meta["id"],
        "feature_rel": f"{SPECS_ROOT}/{meta['id']}",
        "flow": meta["flow"],
        "title": meta.get("title"),
        "created": meta.get("created"),
        "artifacts": artifact_entries(meta, feature_dir, drifts),
        "archive_count": len(meta.get("archive", [])),
        "readonly": False,
        "metadata_state": "ok",
        "drift_count": len(drifts),
    }


def read_legacy_pointer(repo: Path) -> str | None:
    path = repo / LEGACY_POINTER
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("feature_directory")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def cmd_status(repo: Path, feature: str | None, scan_all: bool) -> tuple[dict, int]:
    if bool(feature) == bool(scan_all):
        raise PHsddError("status 需要且只需要 --feature 或 --all 之一")
    features: list[dict] = []
    if scan_all:
        specs = repo / SPECS_ROOT
        if specs.exists():
            issue = path_issue(repo, specs)
            if issue or not specs.is_dir():
                raise PHsddError(f"无法扫描 {SPECS_ROOT}: {issue or '不是目录'}")
            for child in sorted(specs.iterdir()):
                if child.name.startswith(".") or not child.is_dir():
                    continue
                # one broken directory must not blank out the whole report
                try:
                    issue = path_issue(repo, child)
                    if issue:
                        raise PHsddError(issue)
                    features.append(classify_feature(repo, child.name))
                except PHsddError as exc:
                    features.append({
                        "id": child.name,
                        "feature_rel": f"{SPECS_ROOT}/{child.name}",
                        "flow": "error",
                        "title": None,
                        "artifacts": [],
                        "archive_count": 0,
                        "readonly": True,
                        "metadata_state": "unknown",
                        "error": str(exc),
                    })
    else:
        rel, _ = resolve_feature(repo, feature or "", "feature")
        features.append(classify_feature(repo, rel.split("/")[-1]))
    summary: dict[str, int] = {}
    for entry in features:
        summary[f"flow:{entry['flow']}"] = summary.get(f"flow:{entry['flow']}", 0) + 1
        for artifact in entry["artifacts"]:
            key = f"status:{artifact['status']}"
            summary[key] = summary.get(key, 0) + 1
    payload = {
        "action": "status",
        "features": features,
        "legacy_pointer": read_legacy_pointer(repo),
        "summary": dict(sorted(summary.items())),
        "note": "旧指针与 legacy 目录只兼容读取；本命令从不写入",
    }
    return payload, 0


def cmd_check(repo: Path, feature: str) -> tuple[dict, int]:
    rel, feature_dir = resolve_feature(repo, feature, "feature")
    meta = load_meta(repo, feature)  # raises on corrupted metadata (user content)
    if meta is None:
        classified = classify_feature(repo, feature)
        return {
            "action": "check",
            "feature": feature,
            "feature_rel": rel,
            "result": classified["flow"] if classified["flow"] in ("legacy", "unmanaged", "empty") else "blocked",
            "flow": classified["flow"],
            "artifacts": classified["artifacts"],
            "errors": [],
            "warnings": [],
            "note": classified.get("note", "目录无元数据；本工具不做门禁判断"),
        }, 0
    drifts = collect_drifts(repo, meta, feature_dir)
    errors = [{"gate": "evidence" if d["kind"] == "evidence" else "drift", "message": d["message"]}
              for d in drifts]
    errors += review_gate_errors(meta, feature_dir, drifts)
    warnings = stray_warnings(meta, feature_dir) + reference_warnings(meta, feature_dir)
    result = "blocked" if errors else ("needs-review" if warnings else "ok")
    return {
        "action": "check",
        "feature": feature,
        "feature_rel": rel,
        "flow": meta["flow"],
        "title": meta.get("title"),
        "result": result,
        "artifacts": artifact_entries(meta, feature_dir, drifts),
        "errors": errors,
        "warnings": warnings,
        "note": "本检查只保证记录一致性（语法级编号引用、指纹、门禁顺序），不保证语义正确或验收真实",
    }, {"ok": 0, "needs-review": 1, "blocked": 2}[result]


def feature_fingerprint(meta: dict, feature_dir: Path) -> str:
    """Fingerprint of everything semantically meaningful in the feature:
    the artifact files AND the recorded decisions (statuses, notes, evidence
    bindings, review bindings, history). The archive history and the
    updated/created stamps are excluded: history would make the fingerprint
    self-referential (the entry stores the fingerprint), stamps change on
    every save without a semantic difference."""
    semantic = {key: meta.get(key) for key in ("schema", "id", "flow", "title", "files", "adopted_from", "artifacts")}
    digest = hashlib.sha256()
    digest.update(b"ph-feature-fingerprint/1\n")
    digest.update(json.dumps(semantic, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    digest.update(b"\nfiles\n")
    for path in sorted(feature_dir.rglob("*")):
        if path.is_symlink() or is_disallowed_reparse(path):
            raise PHsddError(f"归档中止，feature 目录内含符号链接或联接点: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PHsddError(f"归档中止，遇到非常规文件: {path}")
        if path.name == METADATA_NAME:
            continue
        rel = path.relative_to(feature_dir).as_posix()
        digest.update(f"{rel}\n{sha256_file(path)}\n".encode("utf-8"))
    return digest.hexdigest()


def load_archive_index(repo: Path) -> dict:
    path = repo / ARCHIVE_ROOT / ARCHIVE_INDEX_NAME
    if not path.exists():
        return {"schema": ARCHIVE_INDEX_SCHEMA, "entries": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PHsddError(f"{ARCHIVE_ROOT}/{ARCHIVE_INDEX_NAME} 无法解析（视为用户内容，已拒绝写入）: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != ARCHIVE_INDEX_SCHEMA \
            or not isinstance(raw.get("entries"), list):
        raise PHsddError(f"{ARCHIVE_ROOT}/{ARCHIVE_INDEX_NAME} 不是本工具管理的索引（视为用户内容，已拒绝写入）")
    return raw


def journal_path(repo: Path, feature: str) -> Path:
    return repo / ARCHIVE_ROOT / f".journal-{feature}.json"


def load_journal(repo: Path, feature: str) -> dict | None:
    path = journal_path(repo, feature)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PHsddError(
            f"{path} 无法解析：存在无法识别的归档事务日志（视为用户内容，不自动处理）；"
            f"请人工确认上次归档状态后移除该文件再重试: {exc}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("schema") != ARCHIVE_JOURNAL_SCHEMA \
            or raw.get("feature") != feature or raw.get("phase") not in ("copying", "copied"):
        raise PHsddError(
            f"{path} 不是本工具的归档事务日志（视为用户内容，不自动处理）；请人工确认后移除再重试"
        )
    return raw


def write_journal(repo: Path, feature: str, journal: dict) -> None:
    path = journal_path(repo, feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, (json.dumps(journal, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _gather_evidence(meta: dict, extra: dict | None) -> list[dict]:
    """Distinct evidence records bound by marks plus this archive's own."""
    seen: dict[tuple[str, str], dict] = {}
    for record in meta["artifacts"].values():
        ev = record.get("evidence")
        if isinstance(ev, dict) and ev.get("path") and ev.get("sha256"):
            seen[(ev["path"], ev["sha256"])] = ev
    if extra and extra.get("path") and extra.get("sha256"):
        seen[(extra["path"], extra["sha256"])] = extra
    return list(seen.values())


def _snapshot_evidence(repo: Path, meta: dict, extra: dict | None,
                       feature_dir: Path, snapshot: Path) -> list[dict]:
    """Copy every bound evidence file into the snapshot so cleanup of the
    original cannot destroy archived proof. Files already inside the feature
    directory are preserved by the snapshot itself and only mapped."""
    copies: list[dict] = []
    counter = 1
    entries = _gather_evidence(meta, extra)
    if not entries:
        return copies
    evidence_dir = snapshot / EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for ev in entries:
        source = resolve_evidence(repo, ev["path"])
        try:
            inside = source.resolve().relative_to(feature_dir.resolve()).as_posix()
        except ValueError:
            inside = None
        if inside is not None:
            copies.append({"path": ev["path"], "sha256": ev["sha256"],
                           "bytes": source.stat().st_size, "snapshot_path": inside})
            continue
        data = read_file_bytes(source)
        if sha256_bytes(data) != ev["sha256"]:
            raise PHsddError(f"取证文件在归档时已变化，中止归档: {ev['path']}")
        safe_base = re.sub(r"[^A-Za-z0-9._-]", "_", Path(ev["path"]).name) or "evidence"
        dest_rel = f"{EVIDENCE_DIR}/{counter:04d}-{safe_base}"
        counter += 1
        atomic_write(snapshot / dest_rel, data)
        copies.append({"path": ev["path"], "sha256": ev["sha256"],
                       "bytes": len(data), "snapshot_path": dest_rel})
    manifest = {"schema": ARCHIVE_EVIDENCE_SCHEMA, "copies": copies}
    atomic_write(snapshot / EVIDENCE_DIR / "manifest.json",
                 (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return copies


def _chmod_snapshot(snapshot: Path) -> list[str]:
    warnings: list[str] = []
    for path in sorted(snapshot.rglob("*"), reverse=True):
        try:
            os.chmod(path, 0o444 if path.is_file() else 0o555)
        except OSError as exc:
            warnings.append(f"只读设置失败（内容已保全）: {path.name}: {exc}")
    try:
        os.chmod(snapshot, 0o555)
    except OSError as exc:
        warnings.append(f"只读设置失败（内容已保全）: {snapshot.name}: {exc}")
    return warnings


def _append_index_entry(repo: Path, entry: dict) -> None:
    index = load_archive_index(repo)  # validated again right before the write
    if any(e.get("snapshot") == entry["snapshot"] for e in index["entries"]):
        return  # recovery: this transaction's index entry is already durable
    index["entries"].append(entry)
    index_path = repo / ARCHIVE_ROOT / ARCHIVE_INDEX_NAME
    issue = path_issue(repo, index_path)
    if issue:
        raise PHsddError(f"拒绝写入归档索引：{issue}")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(index_path, (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _append_meta_archive(repo: Path, feature: str, meta: dict, entry: dict) -> None:
    if any(e.get("snapshot") == entry["snapshot"] for e in meta.get("archive", [])):
        return  # recovery: already recorded in the active metadata
    meta["archive"] = [*meta.get("archive", []), entry]
    save_meta(repo, feature, meta)


def _copy_snapshot(feature_dir: Path, snapshot: Path, manifest: list) -> None:
    """Copy the feature files listed in the manifest, verifying each hash."""
    for rel, expected in manifest:
        data = read_file_bytes(feature_dir / rel)
        if sha256_bytes(data) != expected:
            raise PHsddError(f"归档中止：{rel} 在复制时发生变化")
        dest = snapshot / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(dest, data)


def _finish_copy_phase(repo: Path, feature: str, meta: dict, journal: dict,
                       evidence_rec: dict | None, feature_dir: Path) -> list[str]:
    """Copy + evidence + chmod + index + metadata, then drop the journal.
    Index and metadata appends are idempotent by snapshot id, so a crash
    between the two writes is completed (never duplicated) on recovery."""
    snapshot = repo / journal["snapshot"]
    _force_remove_tree(snapshot)  # remove a partial copy; originals untouched
    _copy_snapshot(feature_dir, snapshot, journal["files"])
    copies = _snapshot_evidence(repo, meta, evidence_rec, feature_dir, snapshot)
    journal["entry"]["evidence_copies"] = copies
    journal["meta_entry"]["evidence_copies"] = copies
    journal["phase"] = "copied"
    write_journal(repo, feature, journal)
    warnings = _chmod_snapshot(snapshot)
    _append_index_entry(repo, journal["entry"])
    _append_meta_archive(repo, feature, meta, journal["meta_entry"])
    journal_path(repo, feature).unlink()
    return warnings


def _recover_journal(repo: Path, feature: str, meta: dict, journal: dict,
                     evidence_rec: dict | None, apply: bool) -> tuple[dict, int]:
    """Finish or roll back an interrupted archive; originals are never lost."""
    payload = {
        "action": "archive",
        "dry_run": not apply,
        "feature": feature,
        "result": "recovering",
        "recovery_phase": journal["phase"],
        "snapshot": journal["snapshot"],
        "note": journal["entry"].get("note"),
    }
    if journal["phase"] == "copied":
        # The snapshot is complete and read-only: finish the transaction as
        # it was recorded, even if the feature has since drifted - the
        # snapshot preserves the validated decision.
        if not apply:
            return payload, 0
        warnings = []
        _append_index_entry(repo, journal["entry"])
        _append_meta_archive(repo, feature, meta, journal["meta_entry"])
        journal_path(repo, feature).unlink()
        payload["result"] = "recovered"
        payload["recovered"] = True
        if warnings:
            payload["warnings"] = warnings
        return payload, 0
    # phase == "copying": nothing is durable yet; redo only if the recorded
    # decision still holds.
    feature_dir = repo / f"{SPECS_ROOT}/{feature}"
    drifts = collect_drifts(repo, meta, feature_dir)
    errors = archive_gate_errors(meta, drifts)
    if errors or feature_fingerprint(meta, feature_dir) != journal.get("feature_fingerprint"):
        if apply:
            _force_remove_tree(repo / journal["snapshot"])
            journal_path(repo, feature).unlink()
        payload["result"] = "rolled-back"
        payload["errors"] = errors or [{
            "gate": "archive-readiness",
            "message": "feature 自上次中断的归档后已变化，该事务已回滚；请重新检查后归档",
        }]
        return payload, (2 if apply else 0)
    if not apply:
        return payload, 0
    warnings = _finish_copy_phase(repo, feature, meta, journal, evidence_rec, feature_dir)
    payload["result"] = "recovered"
    payload["recovered"] = True
    if warnings:
        payload["warnings"] = warnings
    return payload, 0


def cmd_archive(repo: Path, feature: str, note: str | None, evidence: str | None,
                apply: bool) -> tuple[dict, int]:
    rel, feature_dir = resolve_feature(repo, feature, "feature")
    meta = load_meta(repo, feature)
    if meta is None:
        raise PHsddError(
            f"{metadata_rel(feature)} 不存在：legacy 目录只兼容读取，归档接续请先使用 adopt 建立元数据"
        )
    if not note or not note.strip():
        raise PHsddError("archive 需要显式 --note（用户归档决定的原文）；仅凭工具判断不归档")
    note = note.strip()
    evidence_rec = evidence_record(repo, evidence) if evidence else None

    journal = load_journal(repo, feature)
    if journal is not None:
        return _recover_journal(repo, feature, meta, journal, evidence_rec, apply)

    # Gates always run BEFORE any idempotency decision: a drifted or
    # incomplete feature is blocked - never "unchanged", never archived.
    drifts = collect_drifts(repo, meta, feature_dir)
    errors = archive_gate_errors(meta, drifts)
    fingerprint = feature_fingerprint(meta, feature_dir)
    payload = {
        "action": "archive",
        "dry_run": not apply,
        "feature": feature,
        "feature_rel": rel,
        "note": note,
        "evidence": evidence_rec,
        "feature_fingerprint": fingerprint,
        "artifact_states": {name: rec["status"] for name, rec in meta["artifacts"].items()},
        "errors": errors,
        "result": "blocked" if errors else "ready",
    }
    if errors:
        return payload, (2 if apply else 0)
    previous = meta.get("archive", [])[-1] if meta.get("archive") else None
    if (previous and previous.get("feature_fingerprint") == fingerprint
            and previous.get("note") == note
            and (previous.get("evidence") or None) == evidence_rec):
        # same content AND the same recorded decision; a new note or new
        # evidence is a new decision and gets a new snapshot entry
        payload["unchanged"] = True
        payload["snapshot"] = previous["snapshot"]
        payload["result"] = "unchanged"
        return payload, 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot_rel = f"{ARCHIVE_ROOT}/{feature}/{stamp}"
    payload["snapshot"] = snapshot_rel
    payload["plan"] = [
        f"复制整个 feature 目录到 {snapshot_rel}/ 并设为只读（含 _evidence/ 取证副本与映射）",
        f"向 {ARCHIVE_ROOT}/{ARCHIVE_INDEX_NAME} 追加一条归档记录（只追加，不改历史）",
        f"在 {metadata_rel(feature)} 记录本次归档历史",
        "不执行 git 操作、不合并、不退出 worktree、不改记忆库",
    ]
    if not apply:
        return payload, 0

    with sdd_lock(repo, f"archive {feature}"):
        load_archive_index(repo)  # full index precheck before anything is written
        if (repo / snapshot_rel).exists():
            raise PHsddError(f"快照目录已存在，拒绝覆盖历史: {snapshot_rel}")
        meta = load_meta(repo, feature)  # re-read under the lock
        if feature_fingerprint(meta, feature_dir) != fingerprint:
            raise PHsddError("feature 在归档准备期间发生变化，请重新执行 archive（本次未写入任何内容）")
        errors = archive_gate_errors(meta, collect_drifts(repo, meta, feature_dir))
        if errors:
            raise PHsddError(f"归档门禁在写入前未通过：{errors[0]['message']}")
        manifest: list[list[str]] = []
        for path in sorted(feature_dir.rglob("*")):
            issue = path_issue(repo, path)
            if issue:
                raise PHsddError(f"归档中止，路径不安全: {issue}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise PHsddError(f"归档中止，遇到非常规文件: {path}")
            manifest.append([path.relative_to(feature_dir).as_posix(), sha256_file(path)])
        journal = {
            "schema": ARCHIVE_JOURNAL_SCHEMA,
            "feature": feature,
            "phase": "copying",
            "snapshot": snapshot_rel,
            "feature_fingerprint": fingerprint,
            "files": manifest,
            "entry": {
                "feature": feature,
                "flow": meta["flow"],
                "snapshot": snapshot_rel,
                "archived_at": now_utc(),
                "note": note,
                "evidence": evidence_rec,
                "artifact_states": payload["artifact_states"],
                "feature_fingerprint": fingerprint,
            },
            "meta_entry": {
                "snapshot": snapshot_rel,
                "archived_at": now_utc(),
                "note": note,
                "evidence": evidence_rec,
                "feature_fingerprint": fingerprint,
            },
        }
        write_journal(repo, feature, journal)
        try:
            warnings = _finish_copy_phase(repo, feature, meta, journal, evidence_rec, feature_dir)
        except Exception:
            # the transaction never became durable: roll back tool output
            # (partial snapshot + journal). Original files were only read.
            _force_remove_tree(repo / snapshot_rel)
            with contextlib.suppress(OSError):
                journal_path(repo, feature).unlink()
            raise
    payload["evidence_copies"] = journal["entry"].get("evidence_copies", [])
    if warnings:
        payload["warnings"] = warnings
    payload["archived"] = True
    return payload, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ph_sdd.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="创建稳定功能目录与元数据（默认 dry-run）")
    p_create.add_argument("--repo", required=True)
    p_create.add_argument("--feature", required=True, help="功能编号，如 001 或 001-login")
    p_create.add_argument("--flow", required=True, choices=sorted(FLOWS))
    p_create.add_argument("--title", required=True, help="一句话说明这项功能是什么")
    p_create.add_argument("--apply", action="store_true")

    p_adopt = sub.add_parser("adopt", help="为旧 SpecKit 功能目录建立元数据接续（默认 dry-run）")
    p_adopt.add_argument("--repo", required=True)
    p_adopt.add_argument("--feature", required=True, help="已存在的安全历史目录名")
    p_adopt.add_argument("--title", default=None)
    p_adopt.add_argument("--apply", action="store_true")

    p_mark = sub.add_parser("mark", help="显式记录产物状态（默认 dry-run）")
    p_mark.add_argument("--repo", required=True)
    p_mark.add_argument("--feature", required=True)
    p_mark.add_argument("--artifact", required=True)
    p_mark.add_argument("--status", required=True)
    p_mark.add_argument("--note", default=None, help="用户决定的原文（状态记录的责任来源）")
    p_mark.add_argument("--evidence", default=None, help="真实证据文件路径（记录哈希）")
    p_mark.add_argument("--apply", action="store_true")

    p_check = sub.add_parser("check", help="只读门禁检查：0=ok 1=needs-review 2=blocked")
    p_check.add_argument("--repo", required=True)
    p_check.add_argument("--feature", required=True)

    p_status = sub.add_parser("status", help="只读状态总览")
    p_status.add_argument("--repo", required=True)
    p_status.add_argument("--feature", default=None)
    p_status.add_argument("--all", action="store_true")

    p_archive = sub.add_parser("archive", help="归档为只读快照并追加索引（默认 dry-run）")
    p_archive.add_argument("--repo", required=True)
    p_archive.add_argument("--feature", required=True)
    p_archive.add_argument("--note", required=True, help="用户归档决定的原文")
    p_archive.add_argument("--evidence", default=None)
    p_archive.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)
    try:
        repo = find_repo(args.repo)
        if args.command == "create":
            payload, code = cmd_create(repo, args.feature, args.flow, args.title, args.apply)
        elif args.command == "adopt":
            payload, code = cmd_adopt(repo, args.feature, args.title, args.apply)
        elif args.command == "mark":
            payload, code = cmd_mark(repo, args.feature, args.artifact, args.status,
                                     args.note, args.evidence, args.apply)
        elif args.command == "check":
            payload, code = cmd_check(repo, args.feature)
        elif args.command == "status":
            payload, code = cmd_status(repo, args.feature, args.all)
        else:
            payload, code = cmd_archive(repo, args.feature, args.note, args.evidence, args.apply)
    except PHsddError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
