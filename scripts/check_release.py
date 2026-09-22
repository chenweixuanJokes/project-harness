#!/usr/bin/env python3
"""Validate the PH release tree and version discipline.

Reads ``release.json`` as the single source for the version and the
required skill list. Since 1.1.8 there is no independent schema_version:
release.json and the manifest must not carry the field and the schema $id
is fixed. Does not talk to the public GitHub API. Temporary trees are
never auto-deleted; callers must move leftovers into ``~/trash``.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ph_release  # noqa: E402
import ph_init  # noqa: E402


FORMAT_VERSION = 1
STABLE_TAG = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
# Strict kebab-case for the distributed skills: lowercase alphanumeric
# segments joined by single hyphens, no leading/trailing/double hyphen.
SKILL_NAME = re.compile(r"^ph-[a-z0-9]+(?:-[a-z0-9]+)*$")
ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
MD_LINK = re.compile(r"(?<!!)\[(?:[^\]\\]|\\.)+\]\(([^)]+)\)")
FENCE = re.compile(r"```[\s\S]*?```")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
YAML_SCALAR = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(?P<value>.*)$"
)
SKIP_DIR_NAMES = {".git", "__pycache__", ".zcode", ".idea"}
SKIP_FILE_NAMES = {".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
NON_PAYLOAD_TOP = frozenset(
    {
        "README.md",
        "CHANGELOG.md",
        ".github",
        "tests",
        ".gitignore",
        ".zcode",
        "docs",
        "AGENTS.md",
        "CLAUDE.md",
    }
)
REQUIRED_ROOT_FILES = (
    "release.json",
    "SKILL.md",
    "evals/evals.json",
    "migrations/index.json",
    "assets/scaffold/.agents/ph.json",
    "assets/scaffold/.agents/ph.schema.json",
    "assets/scaffold/.agents/AGENTS.md",
    "scripts/ph_init.py",
    "scripts/ph_release.py",
    "scripts/ph_merge_update.py",
)
MIGRATION_HEADINGS = ("why", "from", "to", "affected", "preserve", "conflict", "verify")
SCHEMA_ID = "urn:ph:schema:project-harness"


class CheckError(Exception):
    """User-facing validation failure."""


def _need(obj: Mapping, key: str, ctx: str) -> object:
    if key not in obj:
        raise CheckError(f"illegal {ctx}: missing {key}")
    return obj[key]


def _const(value: object, expected: object, ctx: str) -> None:
    if value != expected:
        raise CheckError(f"illegal {ctx}: expected {expected!r}, got {value!r}")


def _semver(value: object, ctx: str) -> str:
    if not isinstance(value, str) or not SEMVER.match(value):
        raise CheckError(f"illegal {ctx}: not semver")
    return value


def semver_tuple(version: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(version) or STABLE_TAG.fullmatch(version)
    if not match:
        raise CheckError(f"not a stable version: {version}")
    if version.startswith("v"):
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    parts = version.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def tag_version(tag: str) -> str:
    match = STABLE_TAG.fullmatch(tag)
    if not match:
        raise CheckError(f"not a stable version tag: {tag}")
    return f"{int(match.group(1))}.{int(match.group(2))}.{int(match.group(3))}"


def read_json_object(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckError(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CheckError(f"illegal {label} JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckError(f"illegal {label}: root must be an object")
    return data


def read_json_any(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckError(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CheckError(f"illegal {label} JSON: {path}: {exc}") from exc


def is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def require_regular_file(root: Path, rel: str, label: str | None = None) -> Path:
    if not ph_release.is_safe_rel_path(rel):
        raise CheckError(f"refusing escaped path: {rel}")
    dest = (root / rel).resolve()
    try:
        dest.relative_to(root.resolve())
    except ValueError as exc:
        raise CheckError(f"refusing escaped path: {rel}") from exc
    if not is_regular_file(dest):
        raise CheckError(f"missing {label or rel}: {rel}")
    return dest


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in SKIP_DIR_NAMES and not (Path(dirpath) / name).is_symlink()
        )
        for name in sorted(filenames):
            if name in SKIP_FILE_NAMES or Path(name).suffix in SKIP_SUFFIXES:
                continue
            path = Path(dirpath) / name
            if path.is_symlink():
                if path.parent == root and path.name in {"AGENTS.md", "CLAUDE.md"}:
                    if os.readlink(path) != ".agents/AGENTS.md" or not is_regular_file(root / ".agents/AGENTS.md"):
                        raise CheckError(f"invalid local constraint entry: {path}")
                    if git_file_bytes(root, "HEAD", path.name) is not None:
                        raise CheckError(f"maintainer symlink must not be published: {path}")
                    continue
                raise CheckError(f"refusing symlink in tree: {path}")
            if path.is_file():
                yield path


def load_release(root: Path) -> dict:
    _const(ph_release.FIXED_SOURCE, "https://github.com/chenweixuanJokes/ph-init.git", "ph_release.FIXED_SOURCE")
    _const(ph_release.DOWNLOAD_SOURCE, "https://github.com/chenweixuanJokes/project-harness.git", "ph_release.DOWNLOAD_SOURCE")
    _const(ph_release.OFFICIAL_FULL_NAME, "chenweixuanJokes/project-harness", "ph_release.OFFICIAL_FULL_NAME")
    _const(ph_release.OFFICIAL_PAGE, "https://github.com/chenweixuanJokes/project-harness", "ph_release.OFFICIAL_PAGE")
    data = read_json_object(root / "release.json", "release.json")
    format_version = _need(data, "format_version", "release.json")
    if not isinstance(format_version, int) or isinstance(format_version, bool):
        raise CheckError("illegal release.json: format_version must be an integer")
    _const(format_version, FORMAT_VERSION, "release.json.format_version")
    version = _semver(_need(data, "version", "release.json"), "release.json.version")
    repository = _need(data, "repository", "release.json")
    if not isinstance(repository, str) or repository != ph_release.FIXED_SOURCE:
        raise CheckError("illegal release.json: repository mismatch")
    extra = set(data) - {
        "format_version",
        "version",
        "repository",
        "required_skills",
    }
    if extra:
        raise CheckError(f"illegal release.json: unsupported keys {sorted(extra)}")
    skills = _need(data, "required_skills", "release.json")
    if not isinstance(skills, list) or any(
        not isinstance(item, str) or not SKILL_NAME.match(item) for item in skills
    ):
        raise CheckError("illegal release.json: required_skills must be ph-* names")
    if len(skills) != 8 or len(set(skills)) != 8:
        raise CheckError("illegal release.json: required_skills must list 8 unique names")
    if skills[0] != "ph-init":
        raise CheckError("illegal release.json: required_skills[0] must be ph-init")
    # The pinned spec-kit contract travels as its own top-level release file:
    # the published pre-1.1.14 validators whitelist their release.json keys
    # and must keep being able to prepare this release.
    contract_path = root / "speckit.json"
    if contract_path.is_symlink() or not contract_path.is_file():
        raise CheckError("the release root is missing the speckit.json contract")
    section = read_json_object(contract_path, "speckit.json")
    if section.get("schema") != "ph.speckit-contract/1":
        raise CheckError("illegal speckit.json: schema must be ph.speckit-contract/1")
    extra = set(section) - {"schema", "repository", "tag", "commit", "version", "skills", "integration", "script"}
    if extra:
        raise CheckError(f"illegal speckit.json: unsupported keys {sorted(extra)}")
    for key in ("repository", "tag", "commit", "version"):
        value = section.get(key)
        if not isinstance(value, str) or not value:
            raise CheckError(f"illegal speckit.json: {key} must be a non-empty string")
    if section.get("tag") != f"v{section.get('version')}" or not STABLE_TAG.match(str(section.get("tag"))):
        raise CheckError("illegal speckit.json: tag must be v<version>")
    if not re.fullmatch(r"[0-9a-f]{40}", str(section.get("commit"))):
        raise CheckError("illegal speckit.json: commit must be a 40-hex commit id")
    core = section.get("skills")
    if (
        not isinstance(core, list)
        or sorted(str(c) for c in core) != sorted(ph_init.SPECKIT_CORE_SKILLS)
    ):
        raise CheckError("illegal speckit.json: skills must list exactly the ten core skills")
    if section.get("integration") != "zcode" or section.get("script") != "sh":
        raise CheckError("illegal speckit.json: the zcode integration with sh scripts must be pinned")
    return {
        "version": version,
        "required_skills": list(skills),
        "speckit": dict(section),
        "repository": repository,
    }


def load_migrations(root: Path) -> list[dict]:
    data = read_json_object(root / "migrations" / "index.json", "migrations/index.json")
    format_version = data.get("format_version", FORMAT_VERSION)
    if format_version != FORMAT_VERSION:
        raise CheckError("illegal migrations/index.json: format_version")
    hops = _need(data, "migrations", "migrations/index.json")
    if not isinstance(hops, list) or not hops:
        raise CheckError("illegal migrations/index.json: migrations must be a non-empty list")
    out: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(hops):
        ctx = f"migrations[{index}]"
        if not isinstance(item, dict):
            raise CheckError(f"illegal migrations/index.json: {ctx} must be an object")
        src = item.get("from_version")
        dest = item.get("to_version")
        if not isinstance(src, str) or not isinstance(dest, str):
            raise CheckError(
                f"illegal migrations/index.json: {ctx} must use from_version/to_version"
            )
        src = _semver(src, f"{ctx}.from_version")
        dest = _semver(dest, f"{ctx}.to_version")
        if semver_tuple(src) >= semver_tuple(dest):
            raise CheckError(f"illegal migrations/index.json: {ctx} is not an upgrade")
        pair = (src, dest)
        if pair in seen_pairs:
            raise CheckError(f"illegal migrations/index.json: duplicate hop {src}->{dest}")
        seen_pairs.add(pair)
        rel = item.get("path")
        if not isinstance(rel, str) or not rel:
            raise CheckError(f"illegal migrations/index.json: {ctx}.path must be a string")
        if not ph_release.is_safe_rel_path(rel) or not rel.startswith("migrations/"):
            raise CheckError(f"illegal migrations/index.json: {ctx}.path escapes the tree")
        path = require_regular_file(root, rel, f"{ctx}.path")
        items = item.get("items")
        if not isinstance(items, list) or not items:
            raise CheckError(f"illegal migrations/index.json: {ctx}.items must be a non-empty list")
        if any(not isinstance(entry, str) or not ITEM_ID.match(entry) for entry in items):
            raise CheckError(f"illegal migrations/index.json: {ctx}.items must be stable ids")
        if len(items) != len(set(items)):
            raise CheckError(f"illegal migrations/index.json: {ctx}.items has duplicates")
        extra = set(item) - {"from_version", "to_version", "path", "items"}
        if extra:
            raise CheckError(f"illegal migrations/index.json: {ctx} extra keys {sorted(extra)}")
        out.append(
            {
                "from_version": src,
                "to_version": dest,
                "path": rel,
                "items": list(items),
                "doc": path,
            }
        )
    return out


def chain_to(hops: list[dict], target: str) -> list[dict]:
    by_to = {hop["to_version"]: hop for hop in hops}
    if len(by_to) != len(hops):
        raise CheckError("illegal migrations/index.json: to_version values must be unique")
    if target not in by_to:
        starts = {hop["from_version"] for hop in hops} | {hop["to_version"] for hop in hops}
        previous = sorted((ver for ver in starts if semver_tuple(ver) < semver_tuple(target)), key=semver_tuple)
        if previous:
            raise CheckError(f"missing migration record {previous[-1]} -> {target}")
        raise CheckError(f"missing migration record to {target}")
    chain: list[dict] = []
    seen: set[str] = set()
    current = target
    while current in by_to:
        if current in seen:
            raise CheckError(f"cyclic migration chain at {current}")
        seen.add(current)
        hop = by_to[current]
        chain.append(hop)
        current = hop["from_version"]
    chain.reverse()
    if not chain or chain[-1]["to_version"] != target:
        raise CheckError(f"missing migration chain ending at {target}")
    cursor = chain[0]["from_version"]
    for hop in chain:
        if hop["from_version"] != cursor:
            raise CheckError(
                f"broken migration chain: expected from {cursor}, got {hop['from_version']}"
            )
        cursor = hop["to_version"]
    if cursor != target:
        raise CheckError(f"migration chain does not reach {target}")
    return chain


def assert_all_old_entries_reach(hops: list[dict], target: str) -> None:
    by_from = {hop["from_version"]: hop for hop in hops}
    if len(by_from) != len(hops):
        raise CheckError("illegal migrations/index.json: from_version values must be unique")
    starts = {hop["from_version"] for hop in hops} - {hop["to_version"] for hop in hops}
    if not starts:
        raise CheckError("illegal migrations/index.json: no historical start version")
    for start in sorted(starts, key=semver_tuple):
        cursor = start
        seen: set[str] = set()
        while cursor != target:
            if cursor in seen:
                raise CheckError(f"cyclic migration chain from {start}")
            seen.add(cursor)
            if cursor not in by_from:
                raise CheckError(f"old version {start} does not reach current {target}")
            cursor = by_from[cursor]["to_version"]


def parse_frontmatter(text: str, label: str) -> dict[str, str]:
    match = FRONTMATTER.match(text)
    if not match:
        raise CheckError(f"illegal {label}: missing YAML frontmatter")
    data: dict[str, str] = {}
    pending_key: str | None = None
    pending_lines: list[str] = []

    def flush() -> None:
        nonlocal pending_key, pending_lines
        if pending_key is None:
            return
        value = "\n".join(pending_lines).strip()
        if value.startswith("|"):
            value = value[1:].lstrip("\n")
        data[pending_key] = value.strip().strip("\"'")
        pending_key = None
        pending_lines = []

    for raw in match.group(1).splitlines():
        if pending_key is not None and (raw.startswith("  ") or raw.startswith("\t") or raw == ""):
            pending_lines.append(raw)
            continue
        flush()
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = YAML_SCALAR.match(line)
        if not parsed:
            raise CheckError(f"illegal {label}: cannot parse frontmatter line {raw!r}")
        pending_key = parsed.group("key")
        pending_lines = [parsed.group("value")]
    flush()
    return data


def validate_skill(path: Path, expected_name: str) -> None:
    """Common strict subset shared by all distributed skills.

    The skill slot (root ``SKILL.md`` for ``ph-init``, the scaffold directory
    otherwise) and the frontmatter ``name`` must be the same strict kebab-case
    identifier, and ``description`` must be a non-empty string of at most 1024
    characters. Frontmatter parsing stays limited to flat scalars; there is
    deliberately no third-party YAML dependency.
    """
    text = path.read_text(encoding="utf-8")
    fields = parse_frontmatter(text, str(path))
    name = fields.get("name")
    description = fields.get("description")
    if name != expected_name:
        raise CheckError(f"illegal skill frontmatter: {path} name must be {expected_name!r}")
    if not SKILL_NAME.match(name):
        raise CheckError(f"illegal skill frontmatter: {path} name is not strict kebab-case: {name!r}")
    if not isinstance(description, str) or not description.strip():
        raise CheckError(f"illegal skill frontmatter: {path} description is empty")
    if len(description) > 1024:
        raise CheckError(f"illegal skill frontmatter: {path} description exceeds 1024 chars")


def validate_evals(path: Path, expected_name: str) -> None:
    data = read_json_object(path, str(path))
    if data.get("skill_name") != expected_name:
        raise CheckError(f"illegal evals: {path} skill_name must be {expected_name!r}")
    evals = data.get("evals")
    if not isinstance(evals, list) or not evals:
        raise CheckError(f"illegal evals: {path} evals must be a non-empty list")
    seen_ids: set[object] = set()
    for index, item in enumerate(evals):
        ctx = f"{path} evals[{index}]"
        if not isinstance(item, dict):
            raise CheckError(f"illegal evals: {ctx} must be an object")
        ident = item.get("id")
        if ident in seen_ids:
            raise CheckError(f"illegal evals: {ctx} duplicate id")
        seen_ids.add(ident)
        prompt = item.get("prompt")
        expected = item.get("expected_output")
        if not isinstance(prompt, str) or not prompt.strip():
            raise CheckError(f"illegal evals: {ctx} prompt is empty")
        if not isinstance(expected, str) or not expected.strip():
            raise CheckError(f"illegal evals: {ctx} expected_output is empty")
        files = item.get("files", [])
        if files is None:
            files = []
        if not isinstance(files, list):
            raise CheckError(f"illegal evals: {ctx} files must be a list")


def validate_json_file(path: Path, label: str) -> object:
    return read_json_any(path, label)


def strip_markdown_noise(text: str) -> str:
    return FENCE.sub("", text)


def markdown_rel_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in MD_LINK.findall(strip_markdown_noise(text)):
        href = raw.strip().split()[0].strip("<>")
        href = href.split("#", 1)[0]
        if not href or href.startswith(("http://", "https://", "mailto:", "urn:")):
            continue
        targets.append(href)
    return targets


def validate_markdown_links(path: Path, root: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for href in markdown_rel_targets(text):
        if not ph_release.is_safe_rel_path(href.lstrip("./")) and href.startswith(("/", "~/", "\\")):
            raise CheckError(f"broken markdown link in {path}: {href}")
        dest = (path.parent / href).resolve()
        try:
            dest.relative_to(root.resolve())
        except ValueError as exc:
            raise CheckError(f"broken markdown link in {path}: {href}") from exc
        if not dest.exists():
            raise CheckError(f"broken markdown link in {path}: {href}")


def validate_schema(root: Path) -> dict:
    path = require_regular_file(
        root, "assets/scaffold/.agents/ph.schema.json", "schema"
    )
    schema = read_json_object(path, "schema")
    schema_id = schema.get("$id")
    if schema_id != SCHEMA_ID:
        raise CheckError(f"illegal schema $id: expected {SCHEMA_ID!r}, got {schema_id!r}")
    required = schema.get("required")
    if isinstance(required, list) and "schema_version" in required:
        raise CheckError("illegal schema: required must not list schema_version")
    properties = schema.get("properties")
    if isinstance(properties, dict) and "schema_version" in properties:
        raise CheckError("illegal schema: properties must not define schema_version")
    adapters = properties.get("adapters") if isinstance(properties, dict) else None
    adapter_properties = adapters.get("properties") if isinstance(adapters, dict) else None
    adapter_required = adapters.get("required") if isinstance(adapters, dict) else None
    expected = {"root_agents", "claude_entry", "claude_skills"}
    if not isinstance(adapter_properties, dict) or set(adapter_properties) != expected:
        raise CheckError("illegal schema: adapters must define only the three supported entries")
    if not isinstance(adapter_required, list) or set(adapter_required) != expected:
        raise CheckError("illegal schema: adapters must require the three supported entries")
    return schema


def validate_manifest(root: Path, release: Mapping[str, object]) -> None:
    path = require_regular_file(root, "assets/scaffold/.agents/ph.json", "manifest")
    data = read_json_object(path, "manifest")
    extra_schema = data.get("$schema")
    if extra_schema not in {None, "./ph.schema.json"}:
        raise CheckError("illegal manifest: $schema must be ./ph.schema.json")
    if "schema_version" in data:
        raise CheckError("illegal manifest: schema_version was removed; delete the field")
    template_version = _semver(data.get("template_version"), "manifest.template_version")
    if template_version != release["version"]:
        raise CheckError(
            f"illegal manifest: template_version must be {release['version']!r}"
        )
    adapters = data.get("adapters")
    expected_adapters = {"root_agents", "claude_entry", "claude_skills"}
    if not isinstance(adapters, dict) or set(adapters) != expected_adapters:
        raise CheckError("illegal manifest: adapters must contain only the three supported entries")
    skills = data.get("skills")
    if not isinstance(skills, dict):
        raise CheckError("illegal manifest: skills must be an object")
    names = skills.get("required_names")
    expected_names = list(release["required_skills"]) + [
        f"ph-{core}" for core in release["speckit"]["skills"]
    ]
    if names != expected_names:
        raise CheckError("illegal manifest: skills.required_names mismatch")
    canonical = data.get("canonical")
    if not isinstance(canonical, dict) or canonical.get("scripts") != ".agents/scripts":
        raise CheckError("illegal manifest: canonical.scripts must be .agents/scripts")
    speckit = data.get("speckit")
    if not isinstance(speckit, dict):
        raise CheckError("illegal manifest: speckit section is required")
    expected_section = {
        "repository": release["speckit"]["repository"],
        "tag": release["speckit"]["tag"],
        "commit": release["speckit"]["commit"],
        "version": release["speckit"]["version"],
        "skills": {
            f"ph-{core}": f"speckit-{core}" for core in release["speckit"]["skills"]
        },
    }
    if speckit != expected_section:
        raise CheckError("illegal manifest: speckit section must match the release contract")


def validate_skills_and_docs(root: Path, skills: list[str]) -> None:
    validate_skill(require_regular_file(root, "SKILL.md", "root SKILL.md"), "ph-init")
    validate_evals(require_regular_file(root, "evals/evals.json", "root evals"), "ph-init")
    skill_root = root / "assets" / "scaffold" / ".agents" / "skills"
    if not skill_root.is_dir() or skill_root.is_symlink():
        raise CheckError("missing assets/scaffold/.agents/skills")
    skills = tuple(skills) + tuple(ph_init.SPECKIT_SKILL_NAMES)
    found: list[str] = []
    for name in skills:
        if name == "ph-init":
            continue
        dest = skill_root / name
        if dest.is_symlink() or not dest.is_dir():
            raise CheckError(f"missing required skill directory: {name}")
        validate_skill(require_regular_file(dest, "SKILL.md", f"{name}/SKILL.md"), name)
        evals = dest / "evals" / "evals.json"
        if evals.exists():
            validate_evals(require_regular_file(dest, "evals/evals.json", f"{name} evals"), name)
        found.append(name)
    extras = sorted(
        child.name
        for child in skill_root.iterdir()
        if child.is_dir() and child.name not in set(skills)
    )
    if extras:
        raise CheckError(f"unexpected scaffold skills: {extras}")
    missing = [name for name in skills if name != "ph-init" and name not in found]
    if missing:
        raise CheckError(f"missing required scaffold skills: {missing}")
    if (skill_root / "ph-init").exists():
        raise CheckError("scaffold must not nest ph-init")
    script = root / "assets" / "scaffold" / ".agents" / "scripts" / "ph_worktree.py"
    if script.is_symlink() or not script.is_file():
        raise CheckError("scaffold must ship the shared .agents/scripts/ph_worktree.py")
    import ph_speckit
    try:
        ph_speckit.bundled_source(root)
    except ph_init.PHError as exc:
        raise CheckError(str(exc)) from exc

    for path in iter_files(root):
        if path.suffix == ".json":
            validate_json_file(path, str(path.relative_to(root)))
        if path.suffix == ".md":
            validate_markdown_links(path, root)


def validate_migration_docs(hops: list[dict], current: str) -> None:
    for hop in hops:
        text = hop["doc"].read_text(encoding="utf-8")
        heading = text.lstrip().splitlines()[0] if text.strip() else ""
        if hop["from_version"] not in heading or hop["to_version"] not in heading:
            raise CheckError(
                f"illegal migration doc {hop['path']}: title must name "
                f"{hop['from_version']} -> {hop['to_version']}"
            )
        lowered = {line.strip("# ").strip().lower() for line in text.splitlines() if line.startswith("## ")}
        missing = [name for name in MIGRATION_HEADINGS if name not in lowered]
        if missing:
            raise CheckError(f"illegal migration doc {hop['path']}: missing sections {missing}")
        for item in hop["items"]:
            if item not in text:
                raise CheckError(f"illegal migration doc {hop['path']}: missing item {item}")
    chain_to(hops, current)
    assert_all_old_entries_reach(hops, current)


def _call_prepared_tree(root: Path, version: str, skills: list[str]) -> None:
    try:
        ph_release.validate_prepared_tree(root, version)
    except ph_release.PHReleaseError as exc:
        raise CheckError(str(exc)) from exc


def validate_prepared_compat(root: Path, release: Mapping[str, object]) -> None:
    for rel in REQUIRED_ROOT_FILES:
        require_regular_file(root, rel)
    _call_prepared_tree(root, str(release["version"]), list(release["required_skills"]))


def parse_local_tags(payload: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    peeled: set[str] = set()
    for raw in payload.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise CheckError(f"illegal git tag list line: {raw!r}")
        object_id, ref = parts
        if not GIT_OBJECT_ID.match(object_id):
            raise CheckError(f"illegal git object id: {object_id!r}")
        if not ref.startswith("refs/tags/"):
            continue
        is_peeled = ref.endswith("^{}")
        tag = ref[len("refs/tags/") :]
        if is_peeled:
            tag = tag[:-3]
        if not STABLE_TAG.match(tag):
            continue
        if is_peeled or tag not in peeled:
            tags[tag] = object_id
        if is_peeled:
            peeled.add(tag)
    return tags


def run_git(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    cmd = ["git", "-C", str(repo), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CheckError(f"git {' '.join(args)} failed: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        out = proc.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        raise CheckError(f"git {' '.join(args)} failed: {(err or out or '').strip()}")
    return proc


def list_published_tags(repo: Path) -> dict[str, str]:
    try:
        payload = run_git(repo, "show-ref", "--tags", "-d").stdout
    except CheckError as exc:
        if "failed:" in str(exc) and "show-ref" in str(exc):
            return {}
        raise
    return parse_local_tags(payload)


def git_file_bytes(repo: Path, spec: str, rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{spec}:{rel}"],
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def unquote_c_style(path: str) -> str:
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        return ast.literal_eval(path)
    return path


def git_ls_files(repo: Path, spec: str) -> list[str]:
    proc = run_git(repo, "ls-tree", "-r", "-z", "--name-only", spec)
    return [unquote_c_style(name) for name in proc.stdout.split("\0") if name]


def is_payload_path(rel: str) -> bool:
    if rel == ".agents/AGENTS.md":
        return False
    top = rel.split("/", 1)[0]
    # IDE-private state is never release payload, whether tracked or not.
    if top in (".idea", ".zcodeignore"):
        return False
    if top in NON_PAYLOAD_TOP:
        return False
    if rel == "scripts/check_release.py" or rel.startswith("scripts/check_release.py/"):
        return False
    if rel.startswith("scripts/build_"):
        return False
    return True


def payload_map_from_git(repo: Path, spec: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for rel in git_ls_files(repo, spec):
        if not is_payload_path(rel):
            continue
        data = git_file_bytes(repo, spec, rel)
        if data is None:
            raise CheckError(f"unable to read {rel} from {spec}")
        files[rel] = data
    return files


def payload_map_from_tree(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        if not is_payload_path(rel):
            continue
        files[rel] = path.read_bytes()
    return files


def payload_changed(current: Mapping[str, bytes], published: Mapping[str, bytes]) -> bool:
    return dict(current) != dict(published)


def latest_tag(tags: Mapping[str, str], exclude: str | None = None) -> str | None:
    names = [tag for tag in tags if tag != exclude]
    if not names:
        return None
    return max(names, key=lambda tag: semver_tuple(tag_version(tag)))


def read_published_release(repo: Path, tag: str) -> dict:
    data = git_file_bytes(repo, tag, "release.json")
    if data is None:
        raise CheckError(f"published tag {tag} is missing release.json")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckError(f"published tag {tag} has illegal release.json") from exc
    if not isinstance(parsed, dict):
        raise CheckError(f"published tag {tag} has illegal release.json")
    version = parsed.get("version")
    if not isinstance(version, str) or not SEMVER.match(version):
        raise CheckError(f"published tag {tag} has illegal version")
    if f"v{version}" != tag:
        raise CheckError(f"published tag {tag} does not match release.json version {version}")
    return parsed


def assert_index_has_hop(hops: list[dict], src: str, dest: str) -> None:
    chain = chain_to(hops, dest)
    for hop in chain:
        if hop["from_version"] == src:
            return
    raise CheckError(f"missing migration record {src} -> {dest}")


def validate_version_discipline(
    root: Path,
    repo: Path,
    release: Mapping[str, object],
    hops: list[dict],
    tags: Mapping[str, str],
    current_tag: str | None,
) -> None:
    version = str(release["version"])
    current_payload = payload_map_from_tree(root)
    if current_tag is not None:
        expected = f"v{version}"
        if current_tag != expected:
            raise CheckError(
                f"tag {current_tag} does not match release.json version {version}"
            )
        commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
        tagged = tags.get(current_tag)
        if tagged is None:
            raise CheckError(f"current tag {current_tag} is not a published stable tag")
        if commit != tagged:
            raise CheckError(
                f"tag {current_tag} commit {tagged} does not match HEAD {commit}"
            )
        others = {name: sha for name, sha in tags.items() if name != current_tag}
        previous = latest_tag(others)
        if previous is not None:
            prev_version = tag_version(previous)
            if semver_tuple(version) <= semver_tuple(prev_version):
                raise CheckError(
                    f"tag {current_tag} is not greater than previous published {previous}"
                )
            assert_index_has_hop(hops, prev_version, version)
        return

    if not tags:
        if semver_tuple(version) < (1, 1, 1):
            raise CheckError("tree without visible tags must use version >= 1.1.1")
        chain_to(hops, version)
        assert_all_old_entries_reach(hops, version)
        return

    latest = latest_tag(tags)
    if latest is None:
        raise CheckError("no stable published tags")
    latest_version = tag_version(latest)
    cmp = (semver_tuple(version) > semver_tuple(latest_version)) - (
        semver_tuple(version) < semver_tuple(latest_version)
    )
    if cmp < 0:
        raise CheckError(
            f"working version {version} is older than published {latest_version}"
        )
    if cmp == 0:
        published_payload = payload_map_from_git(repo, latest)
        if payload_changed(current_payload, published_payload):
            raise CheckError(
                f"version {version} is already tagged; payload bytes changed so bump the version"
            )
        return
    assert_index_has_hop(hops, latest_version, version)


def validate_tree(root: Path, repo: Path | None = None, tag: str | None = None) -> dict:
    release = load_release(root)
    hops = load_migrations(root)
    validate_schema(root)
    validate_manifest(root, release)
    validate_prepared_compat(root, release)
    validate_skills_and_docs(root, list(release["required_skills"]))
    git_root = repo or root
    tags = list_published_tags(git_root)
    validate_version_discipline(root, git_root, release, hops, tags, tag)
    validate_migration_docs(hops, str(release["version"]))
    return {
        "status": "ok",
        "version": release["version"],
        "required_skills": release["required_skills"],
        "tag": tag,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the PH release tree")
    parser.add_argument(
        "--tag",
        default=None,
        help="validate the current commit as this published tag, e.g. v1.1.1",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="repository root to check (defaults to this script's repository)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve() if args.root else SCRIPTS_DIR.parent
    tag = args.tag
    if tag == "":
        tag = None
    if tag is not None and not STABLE_TAG.match(tag):
        raise CheckError(f"unsupported --tag {tag!r}; use vMAJOR.MINOR.PATCH")
    result = validate_tree(root, repo=root, tag=tag)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckError as exc:
        sys.stderr.write(f"error: {exc}\n")
        raise SystemExit(1)
