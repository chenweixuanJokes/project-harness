#!/usr/bin/env python3
"""Prepare a PH release snapshot from the fixed public Git source.

Git downloads use DOWNLOAD_SOURCE; release metadata, receipts and returned
source fields retain FIXED_SOURCE as the 1.x compatibility identity.
Callers cannot supply an arbitrary remote. After a successful download,
an existing GitHub login may be used to star and fork the official repo.
Those optional actions never change the source or fail the prepare.
This script does not initialize projects, merge updates or invoke ph_init.

No third-party deps. Temporary trees are never auto-deleted; callers
must move leftovers into ``~/trash``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


# 旧下载器严格校验此值，因此 1.x 元数据与回执保留它，不用它作为新版下载地址。
FIXED_SOURCE = "https://github.com/chenweixuanJokes/ph-init.git"
DOWNLOAD_SOURCE = "https://github.com/chenweixuanJokes/project-harness.git"
OFFICIAL_OWNER = "chenweixuanJokes"
OFFICIAL_NAME = "project-harness"
# 上游改名不会要求用户的已有副本跟着改名。
LEGACY_OFFICIAL_NAME = "ph-init"
OFFICIAL_PAGE = "https://github.com/chenweixuanJokes/project-harness"
OFFICIAL_FULL_NAME = f"{OFFICIAL_OWNER}/{OFFICIAL_NAME}"
GITHUB_API = "https://api.github.com"
FORMAT_VERSION = 1
# Core Spec Kit skills installed from the pinned upstream release; they are
# generated at install time, never scaffold content. Derived from the bundled
# speckit.json — the single maintenance source for the pinned spec-kit
# contract (release.json keeps required_skills for the four PH scaffold
# skills; speckit.json travels as its own top-level release file because the
# published pre-1.1.14 validators whitelist their release.json keys and must
# keep being able to prepare this release). No script may re-spell the list;
# the static pin guarding accidental edits lives in tests/test_ph_speckit.py.
_BUNDLED_SPECKIT_JSON = json.loads(
    (Path(__file__).resolve().parents[1] / "speckit.json").read_text(encoding="utf-8")
)
SPECKIT_CORE_SKILLS = tuple(
    _BUNDLED_SPECKIT_JSON.get("skills") or ()
    if isinstance(_BUNDLED_SPECKIT_JSON, dict)
    else ()
)
if not SPECKIT_CORE_SKILLS or len(set(SPECKIT_CORE_SKILLS)) != len(SPECKIT_CORE_SKILLS):
    raise SystemExit("speckit.json skills must be a non-empty list of unique names")
# Releases at or after this version publish no independent schema_version:
# release.json and the manifest must not carry the field, and the schema $id
# is fixed without a version suffix. Older tags keep the legacy shape.
NO_SCHEMA_VERSION_AT = (1, 1, 8)
# Releases at or after this version require the pinned spec-kit contract file
# speckit.json at the release root (and the speckit provenance in the
# manifest). Earlier tags predate the GitHub Spec Kit integration and stay
# valid as published.
SPECKIT_REQUIRED_AT = (1, 1, 14)
SCHEMA_ID = "urn:ph:schema:project-harness"
SCHEMA_ID_PREFIX = f"{SCHEMA_ID}:"
GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
STABLE_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SKILL_NAME = re.compile(r"^ph-[a-z0-9-]+$")
DRIVE_OR_SCHEME = re.compile(r"^(?:[A-Za-z]:|[a-zA-Z][a-zA-Z0-9+.-]*:)")
GIT_TIMEOUT_SEC = 60
SUPPORT_TIMEOUT_SEC = 15
SAFE_GIT_CONFIG = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.askPass=",
    "-c",
    "credential.helper=",
    "-c",
    "http.cookieFile=",
    "-c",
    "http.extraHeader=",
    "-c",
    "protocol.file.allow=never",
    "-c",
    "transfer.fsckObjects=true",
    "-c",
    "fetch.fsckObjects=true",
    "-c",
    "fetch.recurseSubmodules=false",
    "-c",
    "submodule.recurse=false",
)
SOURCE_RECEIPT_NAME = ".ph-source.json"
BASE_SKILLS = ("ph-init", "ph-merge-update")
REQUIRED_SCRIPTS = (
    "scripts/ph_init.py",
    "scripts/ph_release.py",
    "scripts/ph_merge_update.py",
)
REQUIRED_SCAFFOLD = (
    "assets/scaffold/.agents/ph.json",
    "assets/scaffold/.agents/ph.schema.json",
    "assets/scaffold/.agents/AGENTS.md",
)
MIGRATIONS_INDEX = "migrations/index.json"
_GIT_DIR_KEYS = {
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_INDEX_FILE",
    "GIT_COOKIE_FILE",
}


class PHReleaseError(Exception):
    """User-facing failure that should become a non-zero exit, not a traceback."""


@dataclass(frozen=True)
class SourceInfo:
    version: str
    tag: str
    commit: str
    source: str


@dataclass(frozen=True)
class PreparedRelease:
    version: str
    tag: str
    commit: str
    source: str
    root: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "tag": self.tag,
            "commit": self.commit,
            "source": self.source,
            "root": str(self.root),
        }


@dataclass(frozen=True)
class GitTreeEntry:
    mode: str
    obj_type: str
    object_id: str
    path: str


class GitTransport:
    """Minimal git remote operations. Tests may replace this class."""

    def ls_remote_tags(self, source: str) -> str:
        return _run_git(
            Path(tempfile.gettempdir()),
            "ls-remote",
            "--tags",
            "--",
            source,
            timeout=GIT_TIMEOUT_SEC,
        ).stdout

    def fetch_commit(self, source: str, commit: str, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        _run_git(dest, "init", "--bare", "--template=", timeout=GIT_TIMEOUT_SEC)
        _run_git(
            dest,
            "fetch",
            "--no-tags",
            "--depth=1",
            "--no-recurse-submodules",
            "--",
            source,
            commit,
            timeout=GIT_TIMEOUT_SEC,
        )

    def object_type(self, git_dir: Path, object_id: str) -> str:
        return _run_git(
            git_dir,
            "cat-file",
            "-t",
            object_id,
            timeout=GIT_TIMEOUT_SEC,
        ).stdout.strip()

    def ls_tree(self, git_dir: Path, commit: str) -> str:
        return _run_git(
            git_dir,
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            commit,
            timeout=GIT_TIMEOUT_SEC,
        ).stdout

    def cat_file(self, git_dir: Path, object_id: str) -> bytes:
        return _run_git(
            git_dir,
            "cat-file",
            "blob",
            object_id,
            timeout=GIT_TIMEOUT_SEC,
            text=False,
        ).stdout


@dataclass(frozen=True)
class SupportResult:
    login: str | None
    starred: bool
    star_created: bool
    copy_url: str | None
    copy_created: bool
    signed_in: bool

    def message(self, *, after_download: bool) -> str:
        prefix = "已经从官方地址下载好了。" if after_download else "官方地址不用再下一次。"
        if self.signed_in and self.login and self.starred and self.copy_url:
            star_part = "给官方仓库加了星" if self.star_created else "星已经点过"
            copy_part = (
                f"并在你的账号下建了副本：{self.copy_url}"
                if self.copy_created
                else f"副本已经在这个地址：{self.copy_url}"
            )
            return (
                f"{prefix}我用你本机已登录的 GitHub 账号 {self.login} {star_part}，"
                f"{copy_part}。这次安装和以后升级仍从官方地址进行，不从这份副本拉。"
            )
        return (
            f"{prefix}本机现在没有已登录的 GitHub，所以没有加星，也没有在你的账号下建副本。"
            f"安装不受影响。若你愿意支持，可打开 {OFFICIAL_PAGE} 加星，并在自己账号下建一份副本。"
        )


class GithubSession:
    """Optional signed-in GitHub actions. Tests may replace this class."""

    def current_login(self) -> str | None:
        login = _gh_login()
        if login:
            return login
        token = _env_github_token()
        if not token:
            return None
        try:
            payload = _github_request("GET", "/user", token)
        except SupportActionError:
            return None
        name = payload.get("login")
        return name if isinstance(name, str) and name else None

    def ensure_star(self, login: str) -> bool:
        del login
        path = f"/user/starred/{OFFICIAL_FULL_NAME}"
        try:
            self._api("GET", path)
            return False
        except SupportActionError as exc:
            if exc.status != 404:
                raise
        self._api("PUT", path, empty_body=True)
        return True

    def ensure_copy(self, login: str) -> tuple[str, bool]:
        existing = self._existing_copy_url(login)
        if existing:
            return existing, False
        payload = self._api("POST", f"/repos/{OFFICIAL_FULL_NAME}/forks")
        html = payload.get("html_url")
        if isinstance(html, str) and html.startswith("https://github.com/"):
            return html, True
        full_name = payload.get("full_name")
        if isinstance(full_name, str) and "/" in full_name:
            return f"https://github.com/{full_name}", True
        refreshed = self._existing_copy_url(login)
        if refreshed:
            return refreshed, True
        raise SupportActionError("copy address missing")

    def _api(self, method: str, path: str, *, empty_body: bool = False) -> dict[str, object]:
        if _gh_login():
            return _gh_api(method, path, empty_body=empty_body)
        token = _env_github_token()
        if not token:
            raise SupportActionError("not signed in")
        return _github_request(method, path, token, empty_body=empty_body)

    def _existing_copy_url(self, login: str) -> str | None:
        for name in (OFFICIAL_NAME, LEGACY_OFFICIAL_NAME):
            url = self._existing_copy_url_for(login, name)
            if url:
                return url
        return None

    def _existing_copy_url_for(self, login: str, name: str) -> str | None:
        try:
            payload = self._api("GET", f"/repos/{login}/{name}")
        except SupportActionError as exc:
            if exc.status == 404:
                return None
            raise
        if payload.get("fork") is not True:
            return None
        parent = payload.get("parent")
        if not isinstance(parent, dict) or parent.get("full_name") != OFFICIAL_FULL_NAME:
            return None
        html = payload.get("html_url")
        if isinstance(html, str) and html.startswith("https://github.com/"):
            return html
        return f"https://github.com/{login}/{name}"


class SupportActionError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _gh_login() -> str | None:
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=SUPPORT_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    login = (proc.stdout or "").strip()
    return login or None


def _env_github_token() -> str | None:
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def _gh_api(method: str, path: str, *, empty_body: bool = False) -> dict[str, object]:
    cmd = ["gh", "api", "-X", method, path]
    if empty_body:
        cmd.extend(["-H", "Content-Length: 0"])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=SUPPORT_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise SupportActionError(f"github {method} {path} timed out") from exc
    except OSError as exc:
        raise SupportActionError(f"github {method} {path} failed to start") from exc
    if proc.returncode != 0:
        status = _gh_status(proc.stderr or proc.stdout)
        raise SupportActionError(f"github {method} {path} failed", status=status)
    raw = (proc.stdout or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SupportActionError(f"github {method} {path} failed") from exc
    return payload if isinstance(payload, dict) else {}


def _gh_status(text: str) -> int | None:
    match = re.search(r"\bHTTP\s+(\d{3})\b", text or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _github_request(
    method: str,
    path: str,
    token: str,
    *,
    empty_body: bool = False,
) -> dict[str, object]:
    request = urllib.request.Request(
        f"{GITHUB_API}{path}",
        method=method,
        data=b"" if empty_body else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ph-init",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=SUPPORT_TIMEOUT_SEC) as response:
            raw = response.read()
            if not raw:
                return {}
            payload = json.loads(raw.decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise SupportActionError(f"github {method} {path} failed", status=status)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise SupportActionError(f"github {method} {path} failed") from exc


def offer_official_support(
    session: GithubSession | None = None,
    *,
    after_download: bool = True,
) -> SupportResult:
    """Star and copy the official repo when already signed in.

    Failures are swallowed: download and install continue either way.
    """

    session = session or GithubSession()
    try:
        login = session.current_login()
        if not login:
            result = SupportResult(None, False, False, None, False, False)
        else:
            star_created = session.ensure_star(login)
            copy_url, copy_created = session.ensure_copy(login)
            result = SupportResult(login, True, star_created, copy_url, copy_created, True)
    except Exception:
        result = SupportResult(None, False, False, None, False, False)
    sys.stderr.write(result.message(after_download=after_download) + "\n")
    return result


def _scrub_git_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("authorization", "bearer", "password", "credential", "token=")):
        return "git failed; details redacted"
    return text


def _run_git(
    cwd: Path | None,
    *args: str,
    timeout: int = GIT_TIMEOUT_SEC,
    text: bool = True,
) -> subprocess.CompletedProcess:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _GIT_DIR_KEYS
        and not key.startswith("GIT_CONFIG")
        and not key.startswith("GIT_ALTERNATE")
        and key not in {"GIT_ASKPASS", "SSH_ASKPASS"}
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    env["SSH_ASKPASS"] = ""
    env["GCM_INTERACTIVE"] = "Never"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_PROTOCOL_FROM_USER"] = "0"
    workdir = cwd if cwd is not None else Path(tempfile.gettempdir())
    cmd = ["git", *SAFE_GIT_CONFIG, *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            env=env,
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise PHReleaseError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    except OSError as exc:
        raise PHReleaseError(f"git {' '.join(args)} failed to start: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        out = proc.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        detail = _scrub_git_text((err or out or "").strip() or f"exit {proc.returncode}")
        if _looks_like_network_failure(detail):
            raise PHReleaseError(f"network failure talking to {DOWNLOAD_SOURCE}: {detail}")
        raise PHReleaseError(f"git {' '.join(args)} failed: {detail}")
    return proc


def _looks_like_network_failure(detail: str) -> bool:
    lowered = detail.lower()
    markers = (
        "could not resolve host",
        "unable to access",
        "failed to connect",
        "connection refused",
        "connection timed out",
        "network is unreachable",
        "ssl",
        "tls",
        "timed out",
        "temporary failure in name resolution",
        "no route to host",
        "operation timed out",
        "http request failed",
        "the requested url returned error",
    )
    return any(marker in lowered for marker in markers)


def parse_ls_remote_tags(payload: str) -> dict[str, str]:
    """Map stable ``vMAJOR.MINOR.PATCH`` tags to peeled commit ids.

    Annotated tags contribute both ``refs/tags/vX`` and
    ``refs/tags/vX^{}``. The peeled line is preferred so the resolved
    object is always a commit, not the tag object.
    """

    commits: dict[str, str] = {}
    peeled: set[str] = set()
    for raw in payload.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise PHReleaseError(f"illegal ls-remote line: {raw!r}")
        object_id, ref = parts
        if not GIT_OBJECT_ID.fullmatch(object_id):
            raise PHReleaseError(f"illegal ls-remote object id: {object_id!r}")
        if not ref.startswith("refs/tags/"):
            continue
        is_peeled = ref.endswith("^{}")
        tag = ref[len("refs/tags/") :]
        if is_peeled:
            tag = tag[:-3]
        match = STABLE_TAG.fullmatch(tag)
        if not match:
            continue
        if is_peeled or tag not in peeled:
            commits[tag] = object_id
        if is_peeled:
            peeled.add(tag)
    return commits


def _parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise PHReleaseError(f"not a semver value: {value!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _semver_tuple(tag: str) -> tuple[int, int, int]:
    match = STABLE_TAG.fullmatch(tag)
    if not match:
        raise PHReleaseError(f"not a stable version tag: {tag}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def select_tag(version: str, tags: Mapping[str, str]) -> tuple[str, str]:
    if version == "latest":
        if not tags:
            raise PHReleaseError("no stable vMAJOR.MINOR.PATCH tags at the fixed source")
        tag = max(tags, key=_semver_tuple)
        return tag, tags[tag]
    if not SEMVER.fullmatch(version):
        raise PHReleaseError(
            f"unsupported version {version!r}; use latest or MAJOR.MINOR.PATCH"
        )
    tag = f"v{version}"
    if tag not in tags:
        raise PHReleaseError(f"version tag {tag} is not a published stable release")
    return tag, tags[tag]


def is_safe_rel_path(rel: str) -> bool:
    """True when *rel* stays a repository-relative POSIX path.

    Unicode path components are allowed so scaffold docs can keep Chinese
    names. Absolute paths, schemes, blank/``.`` / ``..`` parts, and
    backslashes are not.
    """

    if not rel or rel.startswith("/") or rel.startswith("~/"):
        return False
    if "\\" in rel or "\0" in rel or "\n" in rel or "\r" in rel:
        return False
    if DRIVE_OR_SCHEME.match(rel):
        return False
    parts = rel.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def parse_ls_tree(payload: str) -> list[GitTreeEntry]:
    entries: list[GitTreeEntry] = []
    for rec in payload.split("\0"):
        if not rec:
            continue
        meta, sep, path = rec.partition("\t")
        if not sep:
            raise PHReleaseError(f"illegal ls-tree record: {rec!r}")
        parts = meta.split()
        if len(parts) != 3:
            raise PHReleaseError(f"illegal ls-tree metadata: {meta!r}")
        mode, obj_type, object_id = parts
        if not is_safe_rel_path(path):
            raise PHReleaseError(f"refusing escaped tree path: {path!r}")
        entries.append(GitTreeEntry(mode, obj_type, object_id, path))
    return entries


def validate_tree_entries(entries: list[GitTreeEntry]) -> None:
    if not entries:
        raise PHReleaseError("release commit has an empty tree")
    seen: set[str] = set()
    for entry in entries:
        if entry.path in seen:
            raise PHReleaseError(f"duplicate tree path: {entry.path}")
        seen.add(entry.path)
        if entry.mode == "120000":
            raise PHReleaseError(f"refusing git symlink in release tree: {entry.path}")
        if entry.mode == "160000":
            raise PHReleaseError(f"refusing git submodule in release tree: {entry.path}")
        if entry.obj_type != "blob" or entry.mode not in {"100644", "100755"}:
            raise PHReleaseError(
                f"unsupported tree entry {entry.mode} {entry.obj_type} {entry.path}"
            )
        if not GIT_OBJECT_ID.fullmatch(entry.object_id):
            raise PHReleaseError(f"illegal tree object id for {entry.path}")
        if not is_safe_rel_path(entry.path):
            raise PHReleaseError(f"refusing escaped or illegal tree path: {entry.path}")


def _safe_dest(root: Path, rel: str) -> Path:
    if not is_safe_rel_path(rel):
        raise PHReleaseError(f"refusing escaped path: {rel}")
    dest = (root / rel).resolve()
    try:
        dest.relative_to(root.resolve())
    except ValueError as exc:
        raise PHReleaseError(f"refusing escaped path: {rel}") from exc
    return dest


def materialize_blobs(
    transport: GitTransport,
    git_dir: Path,
    root: Path,
    entries: list[GitTreeEntry],
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        dest = _safe_dest(root, entry.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = transport.cat_file(git_dir, entry.object_id)
        dest.write_bytes(data)
        if entry.mode == "100755":
            dest.chmod(dest.stat().st_mode | 0o111)


def _need(obj: dict, key: str, ctx: str) -> object:
    if key not in obj:
        raise PHReleaseError(f"illegal release.json: missing {ctx}.{key}" if ctx else f"illegal release.json: missing {key}")
    return obj[key]


def _const(value: object, expected: object, ctx: str) -> None:
    if value != expected:
        raise PHReleaseError(f"illegal release.json: {ctx} must be {expected!r}, got {value!r}")


def read_json_object(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PHReleaseError(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PHReleaseError(f"illegal {label} JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PHReleaseError(f"illegal {label}: root must be an object")
    return data


def _skill_names(skills: object, label: str) -> list[str]:
    if not isinstance(skills, list) or not skills:
        raise PHReleaseError(f"illegal {label}: required skills must be a non-empty list")
    names: list[str] = []
    seen: set[str] = set()
    for item in skills:
        if not isinstance(item, str) or not SKILL_NAME.fullmatch(item):
            raise PHReleaseError(f"illegal {label}: unsafe skill name {item!r}")
        if item in seen:
            raise PHReleaseError(f"illegal {label}: duplicate skill {item}")
        seen.add(item)
        names.append(item)
    for required in BASE_SKILLS:
        if required not in seen:
            raise PHReleaseError(f"illegal {label}: missing required skill {required}")
    return names


def _require_file(root: Path, rel: str, label: str) -> Path:
    path = _safe_dest(root, rel)
    if not path.is_file() or path.is_symlink():
        raise PHReleaseError(f"missing {label}: {rel}")
    return path


def _validate_speckit_section(section: object) -> None:
    if not isinstance(section, dict):
        raise PHReleaseError("illegal speckit.json: the pinned spec-kit contract is required")
    speckit_extra = set(section) - {"schema", "repository", "tag", "commit", "version", "skills", "integration", "script"}
    if speckit_extra:
        raise PHReleaseError(
            f"illegal speckit.json: unsupported keys {sorted(speckit_extra)}"
        )
    for key in ("repository", "tag", "commit", "version"):
        value = section.get(key)
        if not isinstance(value, str) or not value:
            raise PHReleaseError(f"illegal speckit.json: {key} must be a non-empty string")
    if section.get("tag") != f"v{section.get('version')}":
        raise PHReleaseError("illegal speckit.json: tag must match version")
    if not re.fullmatch(r"[0-9a-f]{40}", str(section.get("commit"))):
        raise PHReleaseError("illegal speckit.json: commit must be a 40-hex commit id")
    core = section.get("skills")
    if not isinstance(core, list) or sorted(str(c) for c in core) != sorted(SPECKIT_CORE_SKILLS):
        raise PHReleaseError("illegal speckit.json: skills must list the pinned core skills")
    if section.get("integration") != "zcode" or section.get("script") != "sh":
        raise PHReleaseError("illegal speckit.json: the zcode integration with sh scripts must be pinned")


def validate_speckit_contract(root: Path) -> None:
    """Validate the top-level speckit.json contract file of a prepared tree.

    The contract travels as its own release file (not inside release.json) so
    the published pre-1.1.14 validators - whose release.json key whitelist is
    frozen - keep being able to prepare this release.
    """
    path = root / "speckit.json"
    if path.is_symlink() or not path.is_file():
        raise PHReleaseError("the prepared release is missing the speckit.json contract")
    data = read_json_object(path, "speckit.json")
    if data.get("schema") != "ph.speckit-contract/1":
        raise PHReleaseError("illegal speckit.json: schema must be ph.speckit-contract/1")
    _validate_speckit_section(data)


def validate_release_meta(data: dict, expected_version: str) -> list[str]:
    """Validate current release metadata and return the required skills."""

    format_version = _need(data, "format_version", "")
    if not isinstance(format_version, int) or isinstance(format_version, bool):
        raise PHReleaseError("illegal release.json: format_version must be an integer")
    _const(format_version, FORMAT_VERSION, "format_version")

    version = _need(data, "version", "")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise PHReleaseError("illegal release.json: version is not semver")
    _const(version, expected_version, "version")

    repository = _need(data, "repository", "")
    if not isinstance(repository, str):
        raise PHReleaseError("illegal release.json: repository must be a string")
    _const(repository, FIXED_SOURCE, "repository")

    extra = set(data) - {"format_version", "version", "repository", "required_skills"}
    if extra:
        raise PHReleaseError(
            f"illegal release.json: unsupported metadata keys {sorted(extra)}"
        )

    return _skill_names(_need(data, "required_skills", ""), "release.json")


def _validate_legacy_release_meta(
    data: dict,
    expected_version: str,
) -> tuple[list[str], str]:
    schema_version = _need(data, "schema_version", "")
    if not isinstance(schema_version, str) or not SEMVER.fullmatch(schema_version):
        raise PHReleaseError("illegal release.json: schema_version is not semver")
    metadata = dict(data)
    del metadata["schema_version"]
    return validate_release_meta(metadata, expected_version), schema_version


def _validate_manifest_versions(
    data: dict,
    expected_version: str,
    skills: list[str],
) -> None:
    template_version = data.get("template_version")
    if not isinstance(template_version, str) or not SEMVER.fullmatch(template_version):
        raise PHReleaseError("illegal manifest: template_version is not semver")
    if template_version != expected_version:
        raise PHReleaseError(
            f"illegal manifest: template_version must be {expected_version!r}, got {template_version!r}"
        )
    skill_block = data.get("skills")
    if not isinstance(skill_block, dict):
        raise PHReleaseError("illegal manifest: skills must be an object")
    names = skill_block.get("required_names")
    if _parse_semver(expected_version) >= SPECKIT_REQUIRED_AT:
        if names != list(skills) + [f"ph-{core}" for core in SPECKIT_CORE_SKILLS]:
            raise PHReleaseError("illegal manifest: skills.required_names mismatch")
        section = data.get("speckit")
        if not isinstance(section, dict):
            raise PHReleaseError("illegal manifest: speckit section is required")
        contract = read_json_object(
            Path(__file__).resolve().parents[1] / "speckit.json", "speckit.json"
        )
        expected_section = {
            "repository": contract.get("repository"),
            "tag": contract.get("tag"),
            "commit": contract.get("commit"),
            "version": contract.get("version"),
            "skills": {f"ph-{core}": f"speckit-{core}" for core in SPECKIT_CORE_SKILLS},
        }
        if section != expected_section:
            raise PHReleaseError("illegal manifest: speckit section must match the release contract")
    else:
        if names != list(skills):
            raise PHReleaseError("illegal manifest: skills.required_names mismatch")
        if "speckit" in data:
            raise PHReleaseError(
                "illegal manifest: speckit section predates the spec-kit integration"
            )


def validate_manifest(
    data: dict,
    expected_version: str,
    skills: list[str],
) -> None:
    if "schema_version" in data:
        raise PHReleaseError(
            "illegal manifest: schema_version was removed; delete the field"
        )
    _validate_manifest_versions(data, expected_version, skills)


def _validate_legacy_manifest(
    data: dict,
    expected_version: str,
    skills: list[str],
    schema_version: str,
) -> None:
    found_schema = data.get("schema_version")
    if not isinstance(found_schema, str) or not SEMVER.fullmatch(found_schema):
        raise PHReleaseError("illegal manifest: schema_version is not semver")
    if found_schema != schema_version:
        raise PHReleaseError(
            f"illegal manifest: schema_version must be {schema_version!r}, got {found_schema!r}"
        )
    _validate_manifest_versions(data, expected_version, skills)


def validate_schema(data: dict) -> None:
    schema_id = data.get("$id")
    if schema_id != SCHEMA_ID:
        raise PHReleaseError(f"illegal schema: $id must be {SCHEMA_ID!r}, got {schema_id!r}")
    required = data.get("required")
    if isinstance(required, list) and "schema_version" in required:
        raise PHReleaseError("illegal schema: required must not list schema_version")
    properties = data.get("properties")
    if isinstance(properties, dict) and "schema_version" in properties:
        raise PHReleaseError("illegal schema: properties must not define schema_version")


def _validate_legacy_schema(data: dict, schema_version: str) -> None:
    schema_id = data.get("$id")
    expected = f"{SCHEMA_ID_PREFIX}{schema_version}"
    if schema_id != expected:
        raise PHReleaseError(f"illegal schema: $id must be {expected!r}, got {schema_id!r}")


def validate_migrations_index(data: dict, root: Path) -> None:
    extra = set(data) - {"format_version", "migrations"}
    if extra:
        raise PHReleaseError(
            f"illegal migrations/index.json: unsupported keys {sorted(extra)}"
        )
    format_version = data.get("format_version")
    if not isinstance(format_version, int) or isinstance(format_version, bool):
        raise PHReleaseError("illegal migrations/index.json: format_version must be 1")
    if format_version != FORMAT_VERSION:
        raise PHReleaseError("illegal migrations/index.json: format_version must be 1")
    migrations = data.get("migrations")
    if not isinstance(migrations, list):
        raise PHReleaseError("illegal migrations/index.json: migrations must be a list")
    seen_from: set[str] = set()
    prev_from: tuple[int, int, int] | None = None
    for index, item in enumerate(migrations):
        ctx = f"migrations[{index}]"
        if not isinstance(item, dict):
            raise PHReleaseError(f"illegal migrations/index.json: {ctx} must be an object")
        unknown = set(item) - {"from_version", "to_version", "path", "items"}
        if unknown:
            raise PHReleaseError(
                f"illegal migrations/index.json: {ctx} unsupported keys {sorted(unknown)}"
            )
        src = item.get("from_version")
        dest_ver = item.get("to_version")
        rel = item.get("path")
        items = item.get("items")
        if not isinstance(src, str) or not SEMVER.fullmatch(src):
            raise PHReleaseError(f"illegal migrations/index.json: {ctx}.from_version must be semver")
        if not isinstance(dest_ver, str) or not SEMVER.fullmatch(dest_ver):
            raise PHReleaseError(f"illegal migrations/index.json: {ctx}.to_version must be semver")
        from_parts = _parse_semver(src)
        to_parts = _parse_semver(dest_ver)
        if from_parts >= to_parts:
            raise PHReleaseError(
                f"illegal migrations/index.json: {ctx} to_version must be greater than from_version"
            )
        if src in seen_from:
            raise PHReleaseError(f"illegal migrations/index.json: duplicate from_version {src}")
        seen_from.add(src)
        if prev_from is not None and from_parts <= prev_from:
            raise PHReleaseError(
                f"illegal migrations/index.json: {ctx} from_version must increase"
            )
        prev_from = from_parts
        if not isinstance(rel, str) or not rel:
            raise PHReleaseError(f"illegal migrations/index.json: {ctx}.path must be a string")
        if not is_safe_rel_path(rel):
            raise PHReleaseError(f"illegal migrations/index.json: {ctx}.path escapes the tree")
        dest = _safe_dest(root, rel)
        if not dest.is_file() or dest.is_symlink():
            raise PHReleaseError(f"missing migration document: {rel}")
        if not isinstance(items, list) or not items:
            raise PHReleaseError(f"illegal migrations/index.json: {ctx}.items must be a non-empty list")
        seen_items: set[str] = set()
        for entry in items:
            if not isinstance(entry, str) or not entry:
                raise PHReleaseError(f"illegal migrations/index.json: {ctx}.items must be unique strings")
            if entry in seen_items:
                raise PHReleaseError(f"illegal migrations/index.json: {ctx}.items must be unique")
            seen_items.add(entry)


def _require_tree_files(root: Path, skills: list[str]) -> None:
    _require_file(root, "SKILL.md", "required skill file")
    for rel in REQUIRED_SCRIPTS:
        _require_file(root, rel, "required script")
    for rel in REQUIRED_SCAFFOLD:
        _require_file(root, rel, "required scaffold file")
    for name in skills:
        if name == "ph-init":
            continue
        _require_file(root, f"assets/scaffold/.agents/skills/{name}/SKILL.md", "required skill file")


def validate_prepared_tree(root: Path, expected_version: str) -> None:
    legacy = _parse_semver(expected_version) < NO_SCHEMA_VERSION_AT
    release = read_json_object(root / "release.json", "release.json")
    if legacy:
        skills, schema_version = _validate_legacy_release_meta(release, expected_version)
    else:
        skills = validate_release_meta(release, expected_version)
    _require_tree_files(root, skills)
    manifest = read_json_object(root / "assets/scaffold/.agents/ph.json", "manifest")
    schema = read_json_object(root / "assets/scaffold/.agents/ph.schema.json", "schema")
    if legacy:
        _validate_legacy_manifest(manifest, expected_version, skills, schema_version)
        _validate_legacy_schema(schema, schema_version)
    else:
        validate_manifest(manifest, expected_version, skills)
        validate_schema(schema)
    if _parse_semver(expected_version) >= SPECKIT_REQUIRED_AT:
        validate_speckit_contract(root)
    migrations = read_json_object(root / MIGRATIONS_INDEX, "migrations/index.json")
    validate_migrations_index(migrations, root)


def source_receipt(info: SourceInfo) -> dict[str, str]:
    return {
        "version": info.version,
        "tag": info.tag,
        "commit": info.commit,
        "source": info.source,
    }


def write_source_receipt(root: Path, info: SourceInfo) -> None:
    path = root / SOURCE_RECEIPT_NAME
    path.write_text(json.dumps(source_receipt(info), indent=2) + "\n", encoding="utf-8")


def resolve_target_repo(explicit: str | None) -> Path | None:
    if explicit:
        start = Path(explicit).expanduser()
        if not start.exists():
            raise PHReleaseError(f"path does not exist: {start}")
        cwd = start if start.is_dir() else start.parent
    else:
        cwd = Path.cwd()
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        if explicit:
            raise PHReleaseError("not a git repository; --repo must be a git root")
        return None
    return Path(proc.stdout.strip()).resolve()


def _outside_target(path: Path, target: Path | None) -> bool:
    if target is None:
        return True
    try:
        path.resolve().relative_to(target.resolve())
    except ValueError:
        return True
    return False


def allocate_temp_root(target_repo: Path | None) -> Path:
    tmp = Path(tempfile.gettempdir()).resolve()
    if not _outside_target(tmp, target_repo):
        raise PHReleaseError(
            "system temp directory is inside the target repository; refuse to download there"
        )
    root = Path(tempfile.mkdtemp(prefix="ph-release-", dir=tmp))
    if not _outside_target(root, target_repo):
        raise PHReleaseError("prepared root resolved inside the target repository")
    return root


def resolve_source_info(
    version: str,
    transport: GitTransport,
) -> SourceInfo:
    if version != "latest" and not SEMVER.fullmatch(version):
        raise PHReleaseError(
            f"unsupported version {version!r}; use latest or MAJOR.MINOR.PATCH"
        )
    payload = transport.ls_remote_tags(DOWNLOAD_SOURCE)
    tags = parse_ls_remote_tags(payload)
    tag, commit = select_tag(version, tags)
    if not GIT_OBJECT_ID.fullmatch(commit):
        raise PHReleaseError(f"resolved commit is not a SHA-1 object id: {commit!r}")
    return SourceInfo(version=tag[1:], tag=tag, commit=commit, source=FIXED_SOURCE)


def prepare_release(
    version: str,
    *,
    repo: str | None = None,
    transport: GitTransport | None = None,
    parent: Path | None = None,
    support: GithubSession | None = None,
    offer_support: bool = True,
) -> PreparedRelease:
    """Download and validate a tagged PH release.

    ``transport`` and ``support`` are the test seams. There is no public
    source URL argument: ls-remote and fetch always use
    ``DOWNLOAD_SOURCE``, while the ``source`` field of the result and
    the receipt record the constant identity ``FIXED_SOURCE``.
    """

    transport = transport or GitTransport()
    target = resolve_target_repo(repo)
    workspace = parent if parent is not None else allocate_temp_root(target)
    if parent is not None:
        if not _outside_target(workspace, target):
            raise PHReleaseError("prepared root resolved inside the target repository")
        workspace.mkdir(parents=True, exist_ok=True)
    info = resolve_source_info(version, transport)
    git_dir = workspace / "git"
    root = workspace / "root"
    git_dir.mkdir(parents=True, exist_ok=True)
    transport.fetch_commit(DOWNLOAD_SOURCE, info.commit, git_dir)
    obj_type = transport.object_type(git_dir, info.commit)
    if obj_type != "commit":
        raise PHReleaseError(f"pinned object {info.commit} is {obj_type}, not commit")
    tree_payload = transport.ls_tree(git_dir, info.commit)
    entries = parse_ls_tree(tree_payload)
    validate_tree_entries(entries)
    materialize_blobs(transport, git_dir, root, entries)
    validate_prepared_tree(root, info.version)
    write_source_receipt(root, info)
    if offer_support:
        offer_official_support(support, after_download=True)
    return PreparedRelease(
        version=info.version,
        tag=info.tag,
        commit=info.commit,
        source=info.source,
        root=root,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a PH release from the fixed GitHub source")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="download and validate a tagged release")
    prepare.add_argument(
        "--version",
        required=True,
        help="latest or an explicit MAJOR.MINOR.PATCH version",
    )
    prepare.add_argument(
        "--repo",
        default=None,
        help="target git root used only to keep the download outside that repo",
    )
    sub.add_parser(
        "support",
        help="add a star and create an account-level copy when already signed in",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepared = prepare_release(args.version, repo=args.repo)
        sys.stdout.write(json.dumps(prepared.as_dict(), indent=2) + "\n")
        return 0
    if args.command == "support":
        offer_official_support(after_download=False)
        return 0
    raise PHReleaseError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PHReleaseError as exc:
        sys.stderr.write(f"error: {exc}\n")
        raise SystemExit(1)
