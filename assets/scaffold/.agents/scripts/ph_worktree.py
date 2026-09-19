#!/usr/bin/env python3
"""Create and deliver PH-managed Git worktrees without stash or force operations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION_FIELDS = {
    "schemaVersion",
    "sessionId",
    "createdAt",
    "mainPath",
    "sourceBranch",
    "sourceHead",
    "taskBranch",
    "taskPath",
    "phase",
    "verifyCommands",
    "maxChangedFileBytes",
}
LIVE_PHASES = {
    "creating",
    "entered",
    "committed",
    "merge_conflict",
    "merging",
    "merged_unverified",
    "merge_verify_failed",
    "merged",
}
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._/-]+$")
SECRET_NAME = re.compile(
    r"(^|/)(\.env(?:\..*)?|id_(?:rsa|dsa|ecdsa|ed25519)|credentials?|secrets?)(?:$|/)|"
    r"\.(?:pem|key|p12|pfx|keystore|jks)$",
    re.IGNORECASE,
)
SECRET_CONTENT = re.compile(
    r"AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"(?i:(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{12,})"
)
DEFAULT_MAX_CHANGED_FILE_BYTES = 10 * 1024 * 1024


class PHError(Exception):
    """A safe, user-actionable refusal."""


def run(
    cwd: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    # Read-only Git queries must not refresh the index during dry-run.
    merged_env["GIT_OPTIONAL_LOCKS"] = "0"
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        env=merged_env,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PHError(f"command failed ({' '.join(args)}): {detail}")
    return proc


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(cwd, "git", *args, check=check)


def git_root(path: Path) -> Path:
    proc = git(path, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        raise PHError(f"not a Git worktree: {path}")
    return Path(proc.stdout.strip()).resolve()


def worktrees(repo: Path) -> list[dict[str, str]]:
    proc = git(repo, "worktree", "list", "--porcelain")
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in proc.stdout.splitlines() + [""]:
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return rows


def main_worktree(repo: Path) -> Path:
    rows = worktrees(repo)
    if not rows:
        raise PHError("Git reported no worktrees")
    return Path(rows[0]["worktree"]).resolve()


def current_branch(repo: Path) -> str:
    proc = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise PHError("detached HEAD is not supported")
    return proc.stdout.strip()


def current_head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def git_path(repo: Path, name: str) -> Path:
    raw = git(repo, "rev-parse", "--git-path", name).stdout.strip()
    path = Path(raw)
    return path if path.is_absolute() else (repo / path).resolve()


def ensure_no_operation(repo: Path) -> None:
    markers = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
    )
    active = [name for name in markers if git_path(repo, name).exists()]
    if active:
        raise PHError(f"Git operation already in progress: {', '.join(active)}")
    if git(repo, "ls-files", "-u", check=False).stdout:
        raise PHError("unmerged index entries exist")


def change_sets(repo: Path) -> tuple[list[str], list[str], list[str]]:
    def names(*args: str) -> list[str]:
        out = git(repo, *args).stdout
        return sorted({part for part in out.split("\0") if part})

    staged = names("diff", "--cached", "--name-only", "-z")
    unstaged = names("diff", "--name-only", "-z")
    untracked = names("ls-files", "--others", "--exclude-standard", "-z")
    return staged, unstaged, untracked


def ensure_clean(repo: Path, label: str) -> None:
    staged, unstaged, untracked = change_sets(repo)
    if staged or unstaged or untracked:
        raise PHError(
            f"{label} is not clean; staged={staged}, unstaged={unstaged}, "
            f"untracked={untracked}. PH never stashes or discards them."
        )


def ensure_main_repo(repo: Path) -> Path:
    root = git_root(repo)
    main = main_worktree(root)
    if root != main:
        raise PHError(f"enter must run from the main worktree: {main}")
    if git(root, "rev-parse", "--is-bare-repository").stdout.strip() == "true":
        raise PHError("bare repositories are not supported")
    if (root / ".gitmodules").exists():
        raise PHError("superprojects with submodules are not supported by PH worktree automation")
    return root


def validate_branch(repo: Path, branch: str) -> None:
    if not SAFE_BRANCH.fullmatch(branch) or not branch.isascii():
        raise PHError("branch must use ASCII letters, numbers, '.', '_', '-', and '/' only")
    proc = git(repo, "check-ref-format", "--branch", branch, check=False)
    if proc.returncode != 0:
        raise PHError(f"invalid branch name: {branch}")


def branch_exists(repo: Path, branch: str) -> bool:
    return git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def occupied_branches(repo: Path) -> dict[str, str]:
    occupied: dict[str, str] = {}
    for row in worktrees(repo):
        ref = row.get("branch", "")
        if ref.startswith("refs/heads/"):
            occupied[ref.removeprefix("refs/heads/")] = row["worktree"]
    return occupied


def require_local_path(main: Path, path: Path) -> Path:
    """Reject redirected path components before resolving a PH-managed path."""

    main = main.resolve()
    try:
        parts = path.absolute().relative_to(main).parts
    except ValueError as exc:
        raise PHError(f"PH path is outside the main worktree: {path}") from exc
    current = main
    for part in parts:
        if part in {"..", "."}:
            raise PHError(f"unsafe PH path component: {path}")
        current = current / part
        junction = getattr(current, "is_junction", lambda: False)()
        if current.is_symlink() or junction:
            raise PHError(f"PH path must not contain a symlink or junction: {current}")
    try:
        current.resolve().relative_to(main)
    except ValueError as exc:
        raise PHError(f"PH path resolves outside the main worktree: {path}") from exc
    return current


def managed_root(main: Path) -> Path:
    root = require_local_path(main, main / ".worktrees")
    if root.exists() and not root.is_dir():
        raise PHError(".worktrees must be a real directory")
    return root


@contextmanager
def delivery_lock(main: Path):
    """Serialize PH mutations sharing a main worktree, without a stale-lock takeover."""

    path = git_path(main, "ph-delivery.lock")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PHError(
            f"another PH delivery owns {path}; if it crashed, verify the owner has stopped "
            "before manually archiving this lock"
        ) from exc
    try:
        owner = {"pid": os.getpid(), "createdAt": datetime.now(timezone.utc).isoformat()}
        os.write(descriptor, json.dumps(owner).encode("utf-8"))
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def safe_task_path(main: Path, branch: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "--", branch).strip("-.").lower() or "task"
    slug = slug[:80].rstrip("-.")
    suffix = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:8]
    root = managed_root(main)
    target = require_local_path(main, root / f"{slug}--{suffix}")
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PHError("computed worktree path escapes .worktrees") from exc
    return target


def ensure_ignored(main: Path) -> None:
    probe = ".worktrees/.ph-ignore-probe"
    if git(main, "check-ignore", "--quiet", probe, check=False).returncode != 0:
        raise PHError(".worktrees/ is not ignored; run ph-init before creating a worktree")


def session_dirs(main: Path) -> tuple[Path, Path]:
    root = managed_root(main) / ".ph"
    sessions = require_local_path(main, root / "sessions")
    completed = require_local_path(main, root / "completed")
    for path in (root, sessions, completed):
        if path.exists() and not path.is_dir():
            raise PHError(f"PH state path must be a directory: {path}")
    return sessions, completed


def save_session(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_session(linked: Path) -> tuple[Path, dict[str, Any]]:
    main = main_worktree(linked)
    sessions, _ = session_dirs(main)
    matches: list[tuple[Path, dict[str, Any]]] = []
    if sessions.is_dir():
        for path in sessions.glob("*.json"):
            require_local_path(main, path)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PHError(f"cannot recover corrupt PH session {path}: {exc}") from exc
            if not isinstance(data, dict):
                raise PHError(f"PH session must be a JSON object: {path}")
            if Path(str(data.get("taskPath", ""))).resolve() == linked.resolve():
                matches.append((path, data))
    if len(matches) != 1:
        raise PHError(f"expected one PH session for {linked}, found {len(matches)}")
    path, data = matches[0]
    missing = sorted(SESSION_FIELDS - data.keys())
    if missing:
        raise PHError(f"session is missing fields: {', '.join(missing)}")
    return path, data


def read_session_record(main: Path, path: Path) -> dict[str, Any]:
    require_local_path(main, path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PHError(f"unreadable session record {path.name}; run doctor to inspect: {exc}") from exc
    if not isinstance(data, dict):
        raise PHError(f"session record must be a JSON object: {path.name}")
    return data


def reject_live_session_conflicts(main: Path, sessions: Path, branch: str, target: Path) -> None:
    if not sessions.is_dir():
        return
    for path in sessions.glob("*.json"):
        data = read_session_record(main, path)
        if data.get("phase") not in LIVE_PHASES:
            continue
        same_branch = data.get("taskBranch") == branch
        same_path = bool(data.get("taskPath")) and Path(str(data["taskPath"])).resolve() == target.resolve()
        if same_branch or same_path:
            raise PHError(
                f"a live PH session for this task already exists ({path.name}, "
                f"phase {data.get('phase')}); inspect it with doctor and deliver or "
                "recover it instead of creating a duplicate"
            )


def load_worktree_policy(main: Path) -> tuple[list[list[str]], int]:
    path = main / ".agents" / "ph.json"
    if not path.is_file():
        return [], DEFAULT_MAX_CHANGED_FILE_BYTES
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PHError(f"cannot read .agents/ph.json: {exc}") from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PHError(f"invalid .agents/ph.json: JSON parse error at line {exc.lineno}: {exc.msg}") from exc
    if not isinstance(manifest, dict):
        raise PHError(
            f"invalid .agents/ph.json: top level must be a JSON object, got {type(manifest).__name__}"
        )
    worktree = manifest.get("worktree", {})
    if not isinstance(worktree, dict):
        raise PHError(
            f"invalid .agents/ph.json: 'worktree' must be an object, got {type(worktree).__name__}"
        )
    commands = worktree.get("verify_commands", [])
    if not isinstance(commands, list) or any(
        not isinstance(command, list)
        or not command
        or any(not isinstance(arg, str) or not arg for arg in command)
        for command in commands
    ):
        raise PHError("worktree.verify_commands must be an array of non-empty argv arrays")
    limit = worktree.get("max_changed_file_bytes", DEFAULT_MAX_CHANGED_FILE_BYTES)
    if not isinstance(limit, int) or limit < 1:
        raise PHError("worktree.max_changed_file_bytes must be a positive integer")
    return commands, limit


def session_policy(data: dict[str, Any]) -> tuple[list[list[str]], int]:
    commands = data.get("verifyCommands")
    limit = data.get("maxChangedFileBytes")
    if not isinstance(commands, list) or any(
        not isinstance(command, list)
        or not command
        or any(not isinstance(arg, str) or not arg for arg in command)
        for command in commands
    ):
        raise PHError("session verifyCommands are invalid")
    if not isinstance(limit, int) or limit < 1:
        raise PHError("session maxChangedFileBytes is invalid")
    return commands, limit


def worktree_state_digest(repo: Path) -> str:
    """Fingerprint all non-ignored Git-visible state around a verification run."""

    digest = hashlib.sha256()
    commands = (
        ("rev-parse", "HEAD"),
        ("symbolic-ref", "--quiet", "HEAD"),
        ("ls-files", "--stage", "-z"),
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
        ("diff", "--binary", "--no-ext-diff", "--no-textconv"),
        ("diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"),
    )
    for args in commands:
        proc = git(repo, *args, check=False)
        if proc.returncode and args[0] != "symbolic-ref":
            raise PHError("cannot snapshot Git-visible state: " + proc.stderr.strip())
        digest.update(str(proc.returncode).encode("ascii") + b"\0")
        digest.update(proc.stdout.encode("utf-8") + b"\0")
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
    for rel in sorted(part for part in untracked.split("\0") if part):
        path = repo / rel
        digest.update(rel.encode("utf-8") + b"\0")
        if path.is_symlink():
            digest.update(b"link:" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise PHError(f"cannot fingerprint untracked path: {rel}")
        digest.update(b"\0")
    return digest.hexdigest()


def run_verification(repo: Path, commands: list[list[str]], phase: str) -> None:
    before = worktree_state_digest(repo)
    for command in commands:
        proc = run(repo, *command, check=False)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise PHError(f"{phase} verification failed ({' '.join(command)}): {detail}")
    if worktree_state_digest(repo) != before:
        raise PHError(
            f"{phase} verification changed Git-visible files; inspect those changes before delivery"
        )


def added_lines(diff_text: str) -> str:
    return "\n".join(
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def screen_wip_changes(
    repo: Path,
    staged: list[str],
    unstaged: list[str],
    untracked: list[str],
    size_limit: int,
) -> list[str]:
    """Screen every current non-ignored change before anything is staged."""

    risks: list[str] = []
    for rel in sorted(set(staged) | set(unstaged) | set(untracked)):
        normalized = rel.replace("\\", "/")
        if SECRET_NAME.search(normalized):
            risks.append(f"secret-like path: {rel}")
        path = repo / rel
        if path.is_file() and path.stat().st_size > size_limit:
            risks.append(f"large file ({path.stat().st_size} bytes): {rel}")
    for label, args in (
        ("staged", ("diff", "--cached", "--no-ext-diff", "--unified=0")),
        ("unstaged", ("diff", "--no-ext-diff", "--unified=0")),
    ):
        if SECRET_CONTENT.search(added_lines(git(repo, *args, check=False).stdout)):
            risks.append(f"secret-like value in {label} content")
    for rel in sorted(untracked):
        path = repo / rel
        if path.is_symlink():
            if SECRET_CONTENT.search(os.readlink(path)):
                risks.append(f"secret-like value in symlink target: {rel}")
        elif path.is_file():
            with path.open("rb") as stream:
                text = stream.read(size_limit).decode("utf-8", errors="ignore")
            if SECRET_CONTENT.search(text):
                risks.append(f"secret-like value in untracked file: {rel}")
    return risks


def command_wip(args: argparse.Namespace) -> dict[str, Any]:
    linked = git_root(Path(args.repo).resolve())
    main = main_worktree(linked)
    _, size_limit = load_worktree_policy(main)
    ensure_no_operation(linked)
    staged, unstaged, untracked = change_sets(linked)
    branch = current_branch(linked)
    head = current_head(linked)
    result: dict[str, Any] = {
        "action": "wip",
        "apply": args.apply,
        "repo": str(linked),
        "branch": branch,
        "head": head,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "message": args.message,
    }
    if not args.apply:
        if not (staged or unstaged or untracked):
            result["commit"] = "clean"
            return result
        risks = screen_wip_changes(linked, staged, unstaged, untracked, size_limit)
        result["risks"] = risks
        if risks:
            raise PHError("unsafe WIP candidate; nothing was staged or committed: " + "; ".join(risks))
        result["commit"] = (
            "planned: stage every listed non-ignored change and create one WIP commit "
            "with hooks and signing intact"
        )
        return result
    # The apply run carries the reviewed dry-run snapshot forward: branch,
    # HEAD, and the to-be-committed path/status sets - checked before anything
    # else, so a drifted scene is never screened or committed under a stale
    # authorization. A set change (a path added, removed, or moved between
    # staged/unstaged/untracked) or a HEAD/branch change blocks and forces a
    # fresh precheck plus a fresh confirmation. Ordinary content modification
    # of an already-listed path stays allowed (no per-file hashing). The
    # message is validated in the same pre-staging block: an empty one never
    # stages anything.
    if not args.message.strip():
        raise PHError("wip --apply requires a non-empty --message; nothing was staged or committed")
    missing = [
        flag
        for flag, value in (
            ("--expect-branch", args.expect_branch),
            ("--expect-head", args.expect_head),
            ("--expect-staged", args.expect_staged),
            ("--expect-unstaged", args.expect_unstaged),
            ("--expect-untracked", args.expect_untracked),
        )
        if value is None
    ]
    if missing:
        raise PHError(
            "wip --apply requires the reviewed dry-run snapshot bindings: "
            + ", ".join(missing)
            + "; re-run the dry-run and carry its values forward"
        )
    if branch != args.expect_branch:
        raise PHError(f"branch drifted: expected {args.expect_branch}, found {branch}")
    if head != args.expect_head:
        raise PHError(f"HEAD drifted: expected {args.expect_head}, found {head}")
    expected = {
        "staged": sorted(p for p in args.expect_staged.split(",") if p),
        "unstaged": sorted(p for p in args.expect_unstaged.split(",") if p),
        "untracked": sorted(p for p in args.expect_untracked.split(",") if p),
    }
    current = {"staged": sorted(staged), "unstaged": sorted(unstaged), "untracked": sorted(untracked)}
    for kind in ("staged", "unstaged", "untracked"):
        if expected[kind] != current[kind]:
            added = sorted(set(current[kind]) - set(expected[kind]))
            removed = sorted(set(expected[kind]) - set(current[kind]))
            raise PHError(
                f"change-set drifted since the reviewed dry-run ({kind}: "
                f"added {added or 'none'}, removed {removed or 'none'}); re-run the dry-run "
                "and reconfirm with the user - a stale authorization cannot cover new changes"
            )
    if not (staged or unstaged or untracked):
        result["commit"] = "clean"
        return result
    risks = screen_wip_changes(linked, staged, unstaged, untracked, size_limit)
    result["risks"] = risks
    if risks:
        raise PHError("unsafe WIP candidate; nothing was staged or committed: " + "; ".join(risks))
    to_add = sorted(set(unstaged) | set(untracked))
    if to_add:
        git(linked, "add", "--", *to_add)
    proc = git(linked, "commit", "-m", args.message, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PHError(f"commit failed; hooks and signing were not bypassed: {detail}")
    result["commit"] = current_head(linked)
    result["files"] = sorted(set(staged) | set(unstaged) | set(untracked))
    return result


def validate_session_identity(
    linked: Path,
    data: dict[str, Any],
    require_matching_head: bool = True,
) -> tuple[Path, str]:
    if data.get("phase") == "creating":
        raise PHError(
            "creation of this worktree was interrupted; inspect it with doctor and "
            "adopt or archive it via recover instead of delivering"
        )
    task_path = Path(data["taskPath"]).resolve()
    if linked.resolve() != task_path:
        raise PHError("current worktree does not match session taskPath")
    task_branch = current_branch(linked)
    if task_branch != data["taskBranch"]:
        raise PHError(f"task branch changed: expected {data['taskBranch']}, got {task_branch}")
    main = Path(data["mainPath"]).resolve()
    if main_worktree(linked) != main or not main.is_dir():
        raise PHError("session mainPath no longer matches Git's main worktree")
    validate_branch(main, task_branch)
    if require_local_path(main, Path(data["taskPath"])) != safe_task_path(main, task_branch):
        raise PHError("session task path is not the canonical PH worktree path")
    if data.get("phase") != "entered":
        ensure_clean(linked, "task worktree after session commit")
        if require_matching_head:
            task_head = data.get("taskHead")
            if not task_head or current_head(linked) != task_head:
                raise PHError(
                    "task HEAD changed after the session commit; deliver the new state "
                    "with the redeliver subcommand instead of retrying exit"
                )
    return main, task_branch


def validate_merge_target_identity(main: Path, data: dict[str, Any]) -> None:
    """Check the merge target's identity without demanding a clean tree.

    Dry-runs use this so a dirty merge target shows up as read-only plan
    data (``sourceDirty``) instead of an error; the apply path still goes
    through ``validate_merge_target``, which enforces the clean tree.
    """
    if current_branch(main) != data["sourceBranch"]:
        raise PHError(
            f"source branch changed: expected {data['sourceBranch']}, got {current_branch(main)}"
        )
    ensure_no_operation(main)
    if git(main, "merge-base", "--is-ancestor", data["sourceHead"], "HEAD", check=False).returncode != 0:
        raise PHError("source history was rewritten; enter-time sourceHead is no longer an ancestor")


def validate_merge_target(main: Path, data: dict[str, Any]) -> None:
    validate_merge_target_identity(main, data)
    ensure_clean(main, "source worktree")


def perform_merge(main: Path, data: dict[str, Any], session_path: Path) -> str:
    task_branch = data["taskBranch"]
    if git(main, "merge-base", "--is-ancestor", task_branch, "HEAD", check=False).returncode == 0:
        data["phase"] = "merged_unverified"
        save_session(session_path, data)
        return "already-contained"
    # Record the pre-merge snapshot BEFORE the merge starts so an interruption
    # is always recoverable from the session record plus Git state.
    data["mergeSourceBranch"] = current_branch(main)
    data["mergeSourceHead"] = current_head(main)
    data["mergeTaskHead"] = git(main, "rev-parse", task_branch).stdout.strip()
    data["phase"] = "merging"
    save_session(session_path, data)
    proc = git(
        main,
        "-c",
        "merge.autoStash=false",
        "merge",
        task_branch,
        check=False,
    )
    if proc.returncode != 0:
        if git_path(main, "MERGE_HEAD").exists():
            data["phase"] = "merge_conflict"
            save_session(session_path, data)
            raise PHError("merge conflict preserved; resolve and run continue, or run abort-merge")
        data["phase"] = "committed"
        save_session(session_path, data)
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PHError(f"merge failed without a resumable conflict: {detail}")
    data["phase"] = "merged_unverified"
    save_session(session_path, data)
    return "merged"


def verify_merge_snapshot(main: Path, data: dict[str, Any]) -> None:
    """Refuse to touch a merge that is not the one this session started."""

    merge_task_head = data.get("mergeTaskHead") or data.get("taskHead")
    merge_source_branch = data.get("mergeSourceBranch") or data.get("sourceBranch")
    merge_source_head = data.get("mergeSourceHead")
    if not merge_task_head:
        raise PHError("session lacks the pre-merge task HEAD; evidence insufficient, refusing to guess")
    if not merge_source_branch:
        raise PHError("session lacks the pre-merge source branch; evidence insufficient, refusing to guess")
    active_branch = current_branch(main)
    if active_branch != merge_source_branch:
        raise PHError(
            f"a different merge is active: source branch is {active_branch}, "
            f"the PH merge targeted {merge_source_branch}"
        )
    if not git_path(main, "MERGE_HEAD").exists():
        raise PHError("MERGE_HEAD is gone; no PH merge conflict is active")
    merge_head = git(main, "rev-parse", "MERGE_HEAD").stdout.strip()
    if merge_head != merge_task_head:
        raise PHError(
            f"a different merge is active: MERGE_HEAD is {merge_head}, "
            f"the PH merge was merging {merge_task_head}"
        )
    if merge_source_head:
        if current_head(main) != merge_source_head:
            raise PHError("source HEAD changed since the PH merge started; refusing to touch a different merge")
        return
    # Legacy record without a pre-merge source HEAD snapshot: reconstruct the
    # evidence from Git's own merge state instead of claiming the merge by
    # branch and task HEAD alone. Git records ORIG_HEAD when a merge starts,
    # and HEAD stays on it until the merge commit is created.
    orig_head_path = git_path(main, "ORIG_HEAD")
    if not orig_head_path.exists():
        raise PHError(
            "session predates merge snapshots and Git has no ORIG_HEAD; "
            "evidence insufficient, refusing to guess"
        )
    orig_head = git(main, "rev-parse", "ORIG_HEAD").stdout.strip()
    if orig_head != current_head(main):
        raise PHError(
            "HEAD moved since the merge started; refusing to touch a different merge"
        )
    entered_source_head = data.get("sourceHead")
    if entered_source_head and git(
        main, "merge-base", "--is-ancestor", entered_source_head, orig_head, check=False
    ).returncode != 0:
        raise PHError(
            "ORIG_HEAD is not on the recorded source history; "
            "evidence insufficient, refusing to guess"
        )


def resolve_merging_phase(main: Path, data: dict[str, Any]) -> str:
    """Classify an interrupted 'merging' phase from provable Git state (read-only)."""

    merge_task_head = data.get("mergeTaskHead")
    merge_source_head = data.get("mergeSourceHead")
    if not merge_task_head or not merge_source_head:
        raise PHError(
            "interrupted merge record lacks its pre-merge snapshot; "
            "inspect it with doctor instead of guessing"
        )
    if git_path(main, "MERGE_HEAD").exists():
        if git(main, "rev-parse", "MERGE_HEAD").stdout.strip() != merge_task_head:
            raise PHError("a different merge is active: MERGE_HEAD does not match the recorded snapshot")
        return "merge_conflict"
    head = current_head(main)
    parents = git(main, "rev-parse", f"{head}^1", f"{head}^2", check=False)
    if parents.returncode == 0 and parents.stdout.split() == [merge_source_head, merge_task_head]:
        return "merged_unverified"
    return "committed"


def validate_merged_target(main: Path, data: dict[str, Any]) -> None:
    if current_branch(main) != data["sourceBranch"]:
        raise PHError("source branch changed after merge; refusing to verify a different branch")
    ensure_no_operation(main)
    ensure_clean(main, "source worktree before post-merge verification")
    if git(
        main,
        "merge-base",
        "--is-ancestor",
        data["taskBranch"],
        "HEAD",
        check=False,
    ).returncode != 0:
        raise PHError("source branch no longer contains the delivered task branch")


def complete_verification(
    main: Path,
    data: dict[str, Any],
    session_path: Path,
    commands: list[list[str]],
) -> None:
    validate_merged_target(main, data)
    merged_head = current_head(main)
    run_verification(main, commands, "post-merge")
    validate_merged_target(main, data)
    if current_head(main) != merged_head:
        raise PHError("post-merge verification changed the source HEAD")
    data["phase"] = "merged"
    data["mergedHead"] = merged_head
    save_session(session_path, data)


def cleanup_session(main: Path, linked: Path, data: dict[str, Any], session_path: Path) -> None:
    if data.get("phase") != "merged":
        raise PHError("cleanup requires a successfully merged and verified session")
    validate_session_identity(linked, data)
    validate_merged_target(main, data)
    verified_head = data.get("mergedHead")
    if not verified_head or git(main, "merge-base", "--is-ancestor", verified_head, "HEAD", check=False).returncode:
        raise PHError("source history no longer contains the verified merge")
    ensure_no_operation(linked)
    ensure_clean(linked, "task worktree")
    ignored = git(linked, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").stdout
    ignored_paths = [part for part in ignored.split("\0") if part]
    if ignored_paths:
        raise PHError(
            f"cleanup blocked by ignored files: {ignored_paths}. Preserve local data outside "
            "the worktree and review disposable artifacts before requesting cleanup again."
        )
    registered = {Path(row["worktree"]).resolve() for row in worktrees(main)}
    if linked.resolve() not in registered or linked.resolve() == main.resolve():
        raise PHError("cleanup target is not the registered linked worktree from this session")
    proc = git(main, "worktree", "remove", str(linked), check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PHError(f"safe worktree removal failed; PH will not force it: {detail}")
    data["phase"] = "cleaned"
    save_session(session_path, data)
    archive_session(main, session_path)


def archive_session(main: Path, session_path: Path) -> None:
    _, completed = session_dirs(main)
    completed.mkdir(parents=True, exist_ok=True)
    session_path.replace(completed / session_path.name)


def confirm_wip_commit(
    repo: Path,
    message: str,
    *,
    expect_branch: str,
    expect_head: str,
    expect_staged: str | None,
    expect_unstaged: str | None,
    expect_untracked: str | None,
    size_limit: int,
) -> tuple[str, list[str], list[str], list[str]]:
    """Stage and create the one confirmed `wip:` commit inside a single apply.

    The bindings are the reviewed precheck snapshot (branch, HEAD, and the
    path/status sets): a set change (path added, removed, or moved between
    staged/unstaged/untracked) or a HEAD/branch change blocks and forces a
    fresh precheck plus a fresh confirmation - a stale authorization must
    never cover new changes. Ordinary content modification of an
    already-listed path stays allowed (no per-file hashing). Returns the new
    HEAD plus the committed sets.
    """

    # Every parameter is validated before anything is staged: the message
    # joins the binding list, so a missing or empty message refuses the
    # whole order up front, never `git add` first and then fail at commit.
    staged, unstaged, untracked = change_sets(repo)
    branch = current_branch(repo)
    head = current_head(repo)
    missing = [
        flag
        for flag, value in (
            ("--wip-message", message if isinstance(message, str) and message.strip() else None),
            ("--expect-branch", expect_branch),
            ("--expect-head", expect_head),
            ("--expect-staged", expect_staged),
            ("--expect-unstaged", expect_unstaged),
            ("--expect-untracked", expect_untracked),
        )
        if value is None
    ]
    if missing:
        raise PHError(
            "the in-apply WIP commit requires the reviewed precheck snapshot bindings: "
            + ", ".join(missing)
            + "; re-run the dry-run and carry its values forward"
        )
    if branch != expect_branch:
        raise PHError(f"branch drifted: expected {expect_branch}, found {branch}")
    if head != expect_head:
        raise PHError(f"HEAD drifted: expected {expect_head}, found {head}")
    expected = {
        "staged": sorted(p for p in expect_staged.split(",") if p),
        "unstaged": sorted(p for p in expect_unstaged.split(",") if p),
        "untracked": sorted(p for p in expect_untracked.split(",") if p),
    }
    current = {"staged": sorted(staged), "unstaged": sorted(unstaged), "untracked": sorted(untracked)}
    for kind in ("staged", "unstaged", "untracked"):
        if expected[kind] != current[kind]:
            added = sorted(set(current[kind]) - set(expected[kind]))
            removed = sorted(set(expected[kind]) - set(current[kind]))
            raise PHError(
                f"change-set drifted since the reviewed precheck ({kind}: "
                f"added {added or 'none'}, removed {removed or 'none'}); re-run the dry-run "
                "and reconfirm with the user - a stale authorization cannot cover new changes"
            )
    if not (staged or unstaged or untracked):
        raise PHError("the tree is clean; the confirmed WIP commit has nothing to commit")
    risks = screen_wip_changes(repo, staged, unstaged, untracked, size_limit)
    if risks:
        raise PHError("unsafe WIP candidate; nothing was staged or committed: " + "; ".join(risks))
    to_add = sorted(set(unstaged) | set(untracked))
    if to_add:
        git(repo, "add", "--", *to_add)
    proc = git(repo, "commit", "-m", message, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PHError(f"commit failed; hooks and signing were not bypassed: {detail}")
    return current_head(repo), staged, unstaged, untracked


def command_enter(args: argparse.Namespace) -> dict[str, Any]:
    main = ensure_main_repo(Path(args.repo).resolve())
    managed_root(main)
    sessions, _ = session_dirs(main)
    # Policy errors are reported before cleanliness, so a broken manifest is
    # diagnosed as a configuration problem rather than a dirty tree.
    verify_commands, max_changed_file_bytes = load_worktree_policy(main)
    ensure_no_operation(main)
    ensure_ignored(main)
    validate_branch(main, args.branch)
    source_branch = current_branch(main)
    source_head = current_head(main)
    source_dirty = change_sets(main)
    dirty = any(source_dirty)
    if args.apply and (args.expect_source_branch is None or args.expect_source_head is None):
        raise PHError(
            "enter --apply requires --expect-source-branch and --expect-source-head bound to "
            "the reviewed precheck snapshot; re-run the dry-run and carry its sourceBranch/"
            "sourceHead forward so drift is blocked instead of silently accepted"
        )
    if args.expect_source_branch is not None and args.expect_source_branch != source_branch:
        raise PHError(
            f"source branch drifted: expected {args.expect_source_branch}, found {source_branch}"
        )
    if args.expect_source_head is not None and args.expect_source_head != source_head:
        raise PHError(f"source HEAD drifted: expected {args.expect_source_head}, found {source_head}")
    if not dirty:
        if args.wip_message is not None:
            raise PHError("--wip-message was passed but the source worktree is clean")
    elif args.apply and args.wip_message is None:
        raise PHError(
            "source worktree is not clean and no confirmed WIP was bound; ask the unified "
            "WIP question (是/否), and on 是 re-run enter --apply with --wip-message and the "
            "precheck bindings so one invocation commits the WIP and creates the worktree"
        )
    target = safe_task_path(main, args.branch)
    # Duplicate diagnosis comes before branch-occupancy errors so an
    # interrupted run is reported as a recoverable live session.
    reject_live_session_conflicts(main, sessions, args.branch, target)
    exists = branch_exists(main, args.branch)
    if exists != args.existing:
        if exists:
            raise PHError("branch already exists; pass --existing to reuse it")
        raise PHError("--existing was passed but the branch does not exist")
    occupied = occupied_branches(main)
    if args.branch in occupied:
        raise PHError(f"branch is already checked out at {occupied[args.branch]}")
    if target.exists():
        raise PHError(f"target path already exists: {target}")
    initial_task_head = git(main, "rev-parse", args.branch).stdout.strip() if exists else source_head
    plan = {
        "action": "enter",
        "apply": args.apply,
        "mainPath": str(main),
        "sourceBranch": source_branch,
        "sourceHead": source_head,
        "taskBranch": args.branch,
        "taskPath": str(target),
        "existingBranch": exists,
        "initialTaskHead": initial_task_head,
        "verifyCommands": verify_commands,
        "maxChangedFileBytes": max_changed_file_bytes,
    }
    if dirty:
        plan["sourceDirty"] = {
            "staged": source_dirty[0],
            "unstaged": source_dirty[1],
            "untracked": source_dirty[2],
        }
        plan["wipPlanned"] = True
        plan["wipRisks"] = screen_wip_changes(main, *source_dirty, max_changed_file_bytes)
    if not args.apply:
        return plan
    wip_commit = None
    if dirty:
        # One apply does the confirmed WIP commit and the creation: the user
        # answered 是 to the unified question and the precheck snapshot is
        # bound, so no separate wip invocation exists in this flow.
        wip_commit, _, _, _ = confirm_wip_commit(
            main,
            args.wip_message,
            expect_branch=args.expect_source_branch,
            expect_head=args.expect_source_head,
            expect_staged=args.expect_staged,
            expect_unstaged=args.expect_unstaged,
            expect_untracked=args.expect_untracked,
            size_limit=max_changed_file_bytes,
        )
        source_head = wip_commit
        initial_task_head = wip_commit if not exists else initial_task_head
        plan["sourceHead"] = source_head
        plan["initialTaskHead"] = initial_task_head
        plan["wipCommit"] = wip_commit
    session_id = str(uuid.uuid4())
    session = {
        "schemaVersion": 1,
        "sessionId": session_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "mainPath": str(main),
        "sourceBranch": source_branch,
        "sourceHead": source_head,
        "taskBranch": args.branch,
        "taskPath": str(target),
        # Recoverable state: if creation is interrupted, doctor lists this
        # record and recover adopts or archives it.
        "phase": "creating",
        "initialTaskHead": initial_task_head,
        "verifyCommands": verify_commands,
        "maxChangedFileBytes": max_changed_file_bytes,
    }
    if wip_commit is not None:
        session["sourceWipCommit"] = wip_commit
    session_path = sessions / f"{session_id}.json"
    save_session(session_path, session)
    target.parent.mkdir(parents=True, exist_ok=True)
    if exists:
        git(main, "worktree", "add", str(target), args.branch)
    else:
        git(main, "worktree", "add", "-b", args.branch, str(target), source_head)
    session["phase"] = "entered"
    save_session(session_path, session)
    plan["sessionId"] = session_id
    plan["status"] = "created"
    return plan


def command_exit(args: argparse.Namespace) -> dict[str, Any]:
    linked = git_root(Path(args.repo).resolve())
    session_path, data = load_session(linked)
    main, _ = validate_session_identity(linked, data)
    commands, size_limit = session_policy(data)
    phase = data["phase"]
    result: dict[str, Any] = {"action": "exit", "apply": args.apply, "phase": phase}

    if args.cleanup and phase != "merged":
        raise PHError(
            "cleanup must be a separate exit call after the session is merged and verified; "
            "an interrupted archival is retried with the recover subcommand"
        )
    if phase == "merge_conflict":
        raise PHError("a merge conflict is active; use continue or abort-merge")
    if phase == "merging":
        raise PHError("an interrupted merge is recorded; resolve it with continue or abort-merge first")

    if not args.apply:
        # Read-only plan gate: in every phase, dry-run never runs verification
        # commands, never merges, never writes the session and never cleans.
        if phase == "entered":
            ensure_no_operation(linked)
            staged, unstaged, untracked = change_sets(linked)
            dirty = bool(staged or unstaged or untracked)
            result["taskTree"] = {"staged": staged, "unstaged": unstaged, "untracked": untracked}
            if dirty:
                result["wipPlanned"] = True
                result["wipRisks"] = screen_wip_changes(linked, staged, unstaged, untracked, size_limit)
                result["commit"] = (
                    "planned: one confirmed exit --apply with --wip-message commits the WIP "
                    "and delivers in the same invocation"
                )
            else:
                result["commit"] = "clean"
            result["taskBranch"] = current_branch(linked)
            result["taskHead"] = current_head(linked)
            validate_merge_target_identity(main, data)
            staged_s, unstaged_s, untracked_s = change_sets(main)
            if staged_s or unstaged_s or untracked_s:
                result["sourceDirty"] = {
                    "staged": staged_s, "unstaged": unstaged_s, "untracked": untracked_s
                }
        elif phase == "committed":
            validate_merge_target_identity(main, data)
            staged_s, unstaged_s, untracked_s = change_sets(main)
            if staged_s or unstaged_s or untracked_s:
                result["sourceDirty"] = {
                    "staged": staged_s, "unstaged": unstaged_s, "untracked": untracked_s
                }
        elif phase in {"merged_unverified", "merge_verify_failed", "merged"}:
            validate_merged_target(main, data)
        else:
            raise PHError(f"cannot plan exit from {phase}")
        result["mergeTarget"] = f"{data['mainPath']}:{data['sourceBranch']}"
        result["verifyCommands"] = commands
        result["cleanupPlanned"] = bool(args.cleanup)
        return result

    if phase == "entered":
        ensure_no_operation(linked)
        # The merge target is validated BEFORE the confirmed WIP commit: an
        # undeliverable target (a main worktree mid-merge, dirty, or moved to
        # another branch) must block the whole apply with nothing staged or
        # committed in the task tree first.
        validate_merge_target(main, data)
        staged, unstaged, untracked = change_sets(linked)
        if staged or unstaged or untracked:
            # One apply does the confirmed WIP commit and the delivery: the
            # user answered 是 to the unified question and the task-tree
            # snapshot is bound, so no separate wip invocation exists here.
            # The merge-conflict phases above never reach this: a conflict is
            # reported first and never answered with a WIP question.
            wip_commit, _, _, _ = confirm_wip_commit(
                linked,
                args.wip_message,
                expect_branch=args.expect_branch,
                expect_head=args.expect_head,
                expect_staged=args.expect_staged,
                expect_unstaged=args.expect_unstaged,
                expect_untracked=args.expect_untracked,
                size_limit=size_limit,
            )
            result["taskWipCommit"] = wip_commit
            data["taskWipCommit"] = wip_commit
            save_session(session_path, data)
        run_verification(linked, commands, "pre-merge")
        data["phase"] = "committed"
        data["taskHead"] = current_head(linked)
        save_session(session_path, data)
        phase = "committed"

    if phase == "committed":
        validate_merge_target(main, data)
        result["merge"] = perform_merge(main, data, session_path)
        phase = data["phase"]

    if phase in {"merged_unverified", "merge_verify_failed"}:
        try:
            complete_verification(main, data, session_path, commands)
        except PHError:
            data["phase"] = "merge_verify_failed"
            save_session(session_path, data)
            raise
        phase = "merged"

    if phase == "merged":
        result["status"] = "merged"
        if args.cleanup:
            cleanup_session(main, linked, data, session_path)
            result["status"] = "cleaned"
        else:
            result["cleanupRequiredConfirmation"] = True
        return result
    raise PHError(f"unsupported session phase for exit: {phase}")


def command_redeliver(args: argparse.Namespace) -> dict[str, Any]:
    linked = git_root(Path(args.repo).resolve())
    session_path, data = load_session(linked)
    main, _ = validate_session_identity(linked, data, require_matching_head=False)
    phase = data["phase"]
    if phase not in {"committed", "merge_verify_failed"}:
        raise PHError(
            f"redeliver applies to committed or merge_verify_failed sessions, not {phase}"
        )
    old_head = data.get("taskHead")
    if not old_head:
        raise PHError("session has no recorded taskHead; evidence insufficient to redeliver")
    new_head = current_head(linked)
    result: dict[str, Any] = {
        "action": "redeliver",
        "apply": args.apply,
        "phase": phase,
        "fromTaskHead": old_head,
        "toTaskHead": new_head,
    }
    if new_head == old_head:
        raise PHError(
            "no new commits since the delivered taskHead; retry the delivery with exit instead"
        )
    if git(linked, "merge-base", "--is-ancestor", old_head, new_head, check=False).returncode != 0:
        raise PHError(
            "new task HEAD is not a descendant of the delivered taskHead; "
            "the task history was rewritten and cannot be redelivered"
        )
    validate_merge_target(main, data)
    commands, _ = session_policy(data)
    if not args.apply:
        result["verifyCommands"] = commands
        result["planned"] = (
            "verify the task tree, record the old and new delivered versions, "
            "then merge and verify as usual"
        )
        return result
    ensure_no_operation(linked)
    run_verification(linked, commands, "pre-merge")
    ensure_clean(linked, "task worktree before recording the redelivery")
    data["taskHead"] = new_head
    data.setdefault("redeliveries", []).append(
        {"from": old_head, "to": new_head, "at": datetime.now(timezone.utc).isoformat()}
    )
    data["phase"] = "committed"
    save_session(session_path, data)
    result["merge"] = perform_merge(main, data, session_path)
    try:
        complete_verification(main, data, session_path, commands)
    except PHError:
        data["phase"] = "merge_verify_failed"
        save_session(session_path, data)
        raise
    result["status"] = "merged"
    result["cleanupRequiredConfirmation"] = True
    return result


def command_continue(args: argparse.Namespace) -> dict[str, Any]:
    linked = git_root(Path(args.repo).resolve())
    session_path, data = load_session(linked)
    main, _ = validate_session_identity(linked, data)
    phase = data["phase"]
    if phase == "merging":
        resolved = resolve_merging_phase(main, data)
        if not args.apply:
            return {
                "action": "continue",
                "apply": False,
                "mainPath": str(main),
                "interruptedMergeResolvesTo": resolved,
            }
        data["phase"] = resolved
        save_session(session_path, data)
        phase = resolved
    if phase != "merge_conflict":
        raise PHError(f"no PH merge conflict is ready to continue (phase: {phase})")
    verify_merge_snapshot(main, data)
    if git(main, "ls-files", "-u", check=False).stdout:
        raise PHError("unresolved merge entries remain")
    if not args.apply:
        return {"action": "continue", "apply": False, "mainPath": str(main)}
    proc = run(
        main,
        "git",
        "-c",
        "merge.autoStash=false",
        "merge",
        "--continue",
        check=False,
        env={"GIT_EDITOR": "true"},
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PHError(f"merge --continue failed: {detail}")
    data["phase"] = "merged_unverified"
    save_session(session_path, data)
    commands, _ = session_policy(data)
    try:
        complete_verification(main, data, session_path, commands)
    except PHError:
        data["phase"] = "merge_verify_failed"
        save_session(session_path, data)
        raise
    result = {"action": "continue", "apply": True, "status": "merged"}
    result["cleanupRequiredConfirmation"] = True
    return result


def command_abort(args: argparse.Namespace) -> dict[str, Any]:
    linked = git_root(Path(args.repo).resolve())
    session_path, data = load_session(linked)
    main, _ = validate_session_identity(linked, data)
    phase = data["phase"]
    if phase == "merging":
        resolved = resolve_merging_phase(main, data)
        if not args.apply:
            return {
                "action": "abort-merge",
                "apply": False,
                "mainPath": str(main),
                "interruptedMergeResolvesTo": resolved,
            }
        data["phase"] = resolved
        save_session(session_path, data)
        phase = resolved
    if phase != "merge_conflict":
        raise PHError(f"no PH merge conflict is active (phase: {phase})")
    verify_merge_snapshot(main, data)
    if not args.apply:
        return {"action": "abort-merge", "apply": False, "mainPath": str(main)}
    git(main, "merge", "--abort")
    data["phase"] = "committed"
    save_session(session_path, data)
    return {"action": "abort-merge", "apply": True, "status": "aborted", "phase": "committed"}


def command_doctor(args: argparse.Namespace) -> dict[str, Any]:
    main = main_worktree(git_root(Path(args.repo).resolve()))
    root = managed_root(main)
    sessions, _ = session_dirs(main)
    records: list[tuple[str, dict[str, Any]]] = []
    corrupt: list[str] = []
    if sessions.is_dir():
        for path in sorted(sessions.glob("*.json")):
            try:
                data = read_session_record(main, path)
                if not str(data.get("taskPath", "")):
                    raise ValueError("record has no taskPath")
                missing = sorted(SESSION_FIELDS - data.keys())
                if missing:
                    raise ValueError(f"missing fields: {', '.join(missing)}")
            except PHError as exc:
                corrupt.append(f"{path.name}: {exc}")
                continue
            records.append((path.name, data))
    registered = {Path(row["worktree"]).resolve() for row in worktrees(main)}
    by_task: dict[str, list[str]] = {}
    orphans: list[str] = []
    cleaned_not_archived: list[str] = []
    interrupted_creating: list[str] = []
    interrupted_merging: list[str] = []
    session_tasks: set[Path] = set()
    for name, data in records:
        task_path = Path(str(data["taskPath"])).resolve()
        session_tasks.add(task_path)
        by_task.setdefault(str(task_path), []).append(name)
        phase = data.get("phase")
        if phase == "cleaned":
            cleaned_not_archived.append(name)
            continue
        if phase == "creating":
            interrupted_creating.append(name)
        if phase == "merging":
            interrupted_merging.append(name)
        if task_path not in registered and not task_path.is_dir():
            orphans.append(name)
    phases_by_name = {name: data.get("phase") for name, data in records}
    duplicates = [
        {
            "taskPath": task,
            "sessions": [
                {"session": name, "phase": phases_by_name[name]} for name in names
            ],
        }
        for task, names in sorted(by_task.items())
        if len(names) > 1
    ]
    unregistered: list[str] = []
    for row in worktrees(main):
        worktree_path = Path(row["worktree"]).resolve()
        if worktree_path == main.resolve():
            continue
        try:
            worktree_path.relative_to(root.resolve())
        except ValueError:
            continue
        if worktree_path not in session_tasks:
            unregistered.append(str(worktree_path))
    return {
        "action": "doctor",
        "mainPath": str(main),
        "orphans": orphans,
        "duplicates": duplicates,
        "unregisteredWorktrees": unregistered,
        "cleanedNotArchived": cleaned_not_archived,
        "interruptedCreating": interrupted_creating,
        "interruptedMerging": interrupted_merging,
        "corruptRecords": corrupt,
    }


def command_recover(args: argparse.Namespace) -> dict[str, Any]:
    main = main_worktree(git_root(Path(args.repo).resolve()))
    sessions, _ = session_dirs(main)
    if args.session != Path(args.session).name or args.session in {".", ".."} or not args.session.endswith(".json"):
        raise PHError("--session must be a session record file name like <sessionId>.json")
    session_path = require_local_path(main, sessions / args.session)
    if not session_path.is_file():
        raise PHError(f"recovery target does not exist: {args.session}")
    data = read_session_record(main, session_path)
    missing = sorted(SESSION_FIELDS - data.keys())
    if missing:
        raise PHError(f"recovery target is missing fields: {', '.join(missing)}")
    phase = data["phase"]
    result: dict[str, Any] = {
        "action": "recover",
        "recoverAction": args.action,
        "session": args.session,
        "phase": phase,
        "apply": args.apply,
    }
    task_path_raw = str(data.get("taskPath", ""))
    if not task_path_raw:
        raise PHError("recovery target has no taskPath; evidence insufficient")
    task_path = Path(task_path_raw)
    registered = {Path(row["worktree"]).resolve() for row in worktrees(main)}
    on_disk = task_path.is_dir()
    is_registered = task_path.resolve() in registered

    if args.action == "archive":
        if on_disk or is_registered:
            raise PHError(
                "the recorded worktree still exists or is still registered, so this "
                "session is not provably dead; deliver, abort or clean it instead of "
                "archiving"
            )
        if not args.apply:
            result["planned"] = (
                "archive the dead session record into .ph/completed/; "
                "branches and directories are preserved"
            )
            return result
        archive_session(main, session_path)
        result["status"] = "archived"
        return result

    if phase != "creating":
        raise PHError(f"adopt applies only to an interrupted creating record, not {phase}")
    if not on_disk or not is_registered:
        raise PHError(
            "the recorded worktree does not exist; there is nothing to adopt "
            "(archive the record instead)"
        )
    for other_path in sessions.glob("*.json"):
        if other_path == session_path:
            continue
        other = read_session_record(main, other_path)
        if str(other.get("taskPath", "")) and Path(str(other["taskPath"])).resolve() == task_path.resolve():
            raise PHError(
                f"duplicate records for this taskPath ({other_path.name}); archive the "
                "stale one explicitly before adopting, otherwise delivery would find "
                "two sessions"
            )
    expected = data.get("initialTaskHead")
    if not expected:
        raise PHError("creating record lacks initialTaskHead; evidence insufficient to adopt")
    if require_local_path(main, task_path) != safe_task_path(main, str(data["taskBranch"])):
        raise PHError("recovery target is not the canonical PH worktree path for its task branch")
    branch = current_branch(task_path)
    if branch != data["taskBranch"]:
        raise PHError(f"worktree branch changed: expected {data['taskBranch']}, got {branch}")
    head = current_head(task_path)
    if head != expected:
        raise PHError(
            f"worktree HEAD {head} does not match the recorded initialTaskHead {expected}; "
            "evidence is ambiguous, refusing to adopt"
        )
    if not args.apply:
        result["planned"] = "mark the interrupted creation as entered so delivery can proceed"
        return result
    data["phase"] = "entered"
    save_session(session_path, data)
    result["status"] = "adopted"
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="PH worktree lifecycle")
    sub = root.add_subparsers(dest="command", required=True)

    enter = sub.add_parser("enter", help="Plan or create a PH linked worktree")
    enter.add_argument("--repo", required=True)
    enter.add_argument("--branch", required=True)
    enter.add_argument("--existing", action="store_true")
    enter.add_argument("--expect-source-branch", dest="expect_source_branch")
    enter.add_argument("--expect-source-head", dest="expect_source_head")
    enter.add_argument(
        "--wip-message",
        dest="wip_message",
        help="confirmed `wip:` message; on a dirty source tree one apply commits the "
        "WIP and creates the worktree",
    )
    enter.add_argument(
        "--expect-staged",
        dest="expect_staged",
        help="comma-joined staged paths of the reviewed dry-run; required with --wip-message",
    )
    enter.add_argument(
        "--expect-unstaged",
        dest="expect_unstaged",
        help="comma-joined unstaged paths of the reviewed dry-run; required with --wip-message",
    )
    enter.add_argument(
        "--expect-untracked",
        dest="expect_untracked",
        help="comma-joined untracked paths of the reviewed dry-run; required with --wip-message",
    )
    enter.add_argument("--apply", action="store_true")

    exit_cmd = sub.add_parser("exit", help="Verify, merge, and optionally clean a PH worktree")
    exit_cmd.add_argument("--repo", required=True)
    # Deprecated and ignored: exit never commits. Dirty trees are blocked with
    # guidance toward the wip subcommand or an explicitly authorized commit.
    exit_cmd.add_argument("--message")
    exit_cmd.add_argument("--cleanup", action="store_true")
    exit_cmd.add_argument(
        "--wip-message",
        dest="wip_message",
        help="confirmed `wip:` message; on a dirty task tree one apply commits the WIP "
        "and delivers",
    )
    exit_cmd.add_argument("--expect-branch", dest="expect_branch", help="task branch of the reviewed dry-run; required with --wip-message")
    exit_cmd.add_argument("--expect-head", dest="expect_head", help="task HEAD of the reviewed dry-run; required with --wip-message")
    exit_cmd.add_argument("--expect-staged", dest="expect_staged", help="comma-joined staged paths of the reviewed dry-run; required with --wip-message")
    exit_cmd.add_argument("--expect-unstaged", dest="expect_unstaged", help="comma-joined unstaged paths of the reviewed dry-run; required with --wip-message")
    exit_cmd.add_argument("--expect-untracked", dest="expect_untracked", help="comma-joined untracked paths of the reviewed dry-run; required with --wip-message")
    exit_cmd.add_argument("--apply", action="store_true")

    wip = sub.add_parser("wip", help="Commit all current non-ignored changes as one WIP commit")
    wip.add_argument("--repo", required=True)
    wip.add_argument("--message", required=True)
    wip.add_argument(
        "--expect-branch",
        dest="expect_branch",
        help="branch of the reviewed dry-run; required for --apply",
    )
    wip.add_argument(
        "--expect-head",
        dest="expect_head",
        help="HEAD of the reviewed dry-run; required for --apply",
    )
    wip.add_argument(
        "--expect-staged",
        dest="expect_staged",
        help="comma-joined staged paths of the reviewed dry-run; required for --apply",
    )
    wip.add_argument(
        "--expect-unstaged",
        dest="expect_unstaged",
        help="comma-joined unstaged paths of the reviewed dry-run; required for --apply",
    )
    wip.add_argument(
        "--expect-untracked",
        dest="expect_untracked",
        help="comma-joined untracked paths of the reviewed dry-run; required for --apply",
    )
    wip.add_argument("--apply", action="store_true")

    redeliver = sub.add_parser(
        "redeliver",
        help="Deliver supplementary task commits after an aborted or failed delivery",
    )
    redeliver.add_argument("--repo", required=True)
    redeliver.add_argument("--apply", action="store_true")

    cont = sub.add_parser("continue", help="Continue a resolved PH merge conflict")
    cont.add_argument("--repo", required=True)
    cont.add_argument("--apply", action="store_true")

    abort = sub.add_parser("abort-merge", help="Abort the PH merge while preserving task commits")
    abort.add_argument("--repo", required=True)
    abort.add_argument("--apply", action="store_true")

    doctor = sub.add_parser("doctor", help="Read-only report of PH session and worktree inconsistencies")
    doctor.add_argument("--repo", required=True)

    recover = sub.add_parser(
        "recover",
        help="Archive a provably dead session record or adopt an interrupted creation",
    )
    recover.add_argument("--repo", required=True)
    recover.add_argument("--session", required=True)
    recover.add_argument("--action", required=True, choices=("archive", "adopt"))
    recover.add_argument("--apply", action="store_true")
    return root


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "enter": command_enter,
        "exit": command_exit,
        "wip": command_wip,
        "redeliver": command_redeliver,
        "continue": command_continue,
        "abort-merge": command_abort,
        "doctor": command_doctor,
        "recover": command_recover,
    }[args.command](args)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if getattr(args, "apply", False):
            main_repo = main_worktree(git_root(Path(args.repo).resolve()))
            with delivery_lock(main_repo):
                result = dispatch(args)
        else:
            result = dispatch(args)
    except PHError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
