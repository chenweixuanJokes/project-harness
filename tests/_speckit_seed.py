"""Shared real spec-kit install seed for upgrade fixtures.

The merge-update fixtures and the historical upgrade matrix simulate the
Agent-executed 1.1.14 speckit-core-integration item (and the 1.2.1/1.2.2
baseline refreshes) by copying a real pinned-generation install. Since 1.2.3
the release itself no longer ships the spec-kit integration, so the seed is
built from this repository's published history: the exact ``v1.2.2`` tree is
extracted from the local git objects (``git archive <tag-commit>``) and the
extracted historical ``scripts/ph_speckit.py`` performs a genuine bundled
offline install into a temporary git repo. The seed is built once per machine
and reused read-only; a stale seed from an older install contract is discarded
and rebuilt. This keeps the historical construction real (the historical
installer with its historical scaffold and bundle) instead of weakening it to
a manifest version bump.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from time import time_ns

REPO_ROOT = Path(__file__).resolve().parents[1]

# The published tag whose tree carries the last speckit-capable installer.
# Pinned explicitly: the seed must be a deterministic, reproducible historical
# construction, never "whatever HEAD happens to carry".
HISTORY_TAG = "v1.2.2"

_SEED_PREFIX = "ph-speckit-seed-"
_SRC_PREFIX = "ph-speckit-hist-src-"


def seed_path() -> Path:
    return Path(tempfile.gettempdir()) / f"{_SEED_PREFIX}{os.getuid()}"


def source_path() -> Path:
    return Path(tempfile.gettempdir()) / f"{_SRC_PREFIX}{os.getuid()}"


# Stamp of the conversion contract the seed was built with. Bump it whenever
# the conversion output changes shape (paths, wording, rewrites), so a cached
# seed from an older conversion rebuilds instead of drifting from the bytes
# the historical pipeline produces.
SEED_CONTRACT_STAMP = "1.2.3-history-extraction-r1"


def _run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=600, **kwargs)


def _retire_temporary(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    trash = Path.home() / (".Trash" if sys.platform == "darwin" else "trash")
    if sys.platform != "darwin":
        trash.mkdir(parents=True, exist_ok=True)
    if not trash.is_dir():
        raise AssertionError(f"system trash is unavailable: {trash}")
    shutil.move(str(path), str(trash / f"ph-history-fixture-{time_ns()}-{path.name}"))


def _extract_source(src: Path) -> None:
    """Extract the pinned historical tag into a plain tree (no .git)."""

    if src.exists():
        _retire_temporary(src)
    src.mkdir(parents=True, exist_ok=True)
    proc = _run(["git", "-C", str(REPO_ROOT), "rev-parse", f"{HISTORY_TAG}^{{commit}}"])
    if proc.returncode != 0:
        raise AssertionError(f"history tag {HISTORY_TAG} is missing from the local git objects: {proc.stderr}")
    commit = proc.stdout.strip()
    (src / ".ph-history-commit").write_text(commit + "\n", encoding="utf-8")
    archive_file = src / ".archive.tar"
    with open(archive_file, "wb") as out:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "archive", commit],
            stdout=out, stderr=subprocess.PIPE, timeout=600,
        )
    if proc.returncode != 0:
        raise AssertionError(f"git archive {HISTORY_TAG} failed: {proc.stderr.decode(errors='replace')}")
    tar = subprocess.run(["tar", "-xf", str(archive_file), "-C", str(src)], capture_output=True, text=True, timeout=600)
    _retire_temporary(archive_file)
    if tar.returncode != 0:
        raise AssertionError(f"cannot extract the historical tree: {tar.stderr}")


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("ph_speckit_history", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_root() -> Path:
    """The extracted historical release tree, refreshed when its stamp changes."""

    src = source_path()
    stamp = src / ".ph-seed-contract"
    if not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != SEED_CONTRACT_STAMP:
        _extract_source(src)
        stamp.write_text(SEED_CONTRACT_STAMP + "\n", encoding="utf-8")
    return src


def module():
    """Run a snippet inside the historical tree's module context.

    The historical ``ph_speckit`` imports its own ``ph_init``/``ph_layout``
    siblings; loading it in-process would pollute or shadow the dev-tree
    modules, so snippets execute in a short-lived subprocess that prints one
    JSON line. ``ns`` holds JSON-serializable inputs only.
    """

    def run(snippet: str, ns: dict | None = None) -> dict:
        src = source_root()
        script = src / ".fixture-driver.py"
        payload = json.dumps({"src": str(src), "ns": ns or {}})
        script.write_text(
            "import json, sys\n"
            "args = json.loads(sys.stdin.read())\n"
            "sys.path.insert(0, args['src'] + '/scripts')\n"
            "import ph_init, ph_speckit, ph_layout\n"
            "from pathlib import Path\n"
            + snippet
            + "\n",
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                input=payload, capture_output=True, text=True, timeout=600,
            )
        finally:
            _retire_temporary(script)
        if proc.returncode != 0:
            raise AssertionError(f"historical speckit driver failed: {proc.stderr[-1500:]}")
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        return json.loads(lines[-1])

    return run


def finalize_fixture(repo) -> dict:
    """Render the fixture-specific constitution pair and record baselines.

    Mirrors exactly what the 1.2.2-era ``ph_speckit install --apply`` plus
    ``record-baselines`` wrote for a real project: an override template and a
    live constitution whose navigation zones reference the fixture's own
    constraints tree, plus the per-file content baselines in the fixture
    manifest (the identity proof the skill replacement later compares).
    """

    repo_str = str(Path(repo).resolve())
    run = module()
    return run(
        "ns = args['ns']\n"
        "repo = Path(ns['repo'])\n"
        "contract = ph_speckit.speckit_contract()\n"
        "staging = ph_speckit.resolve_staging(None, contract)\n"
        "override = repo / ph_speckit.CONSTITUTION_OVERRIDE_REL\n"
        "override.parent.mkdir(parents=True, exist_ok=True)\n"
        "override.write_bytes(ph_speckit.render_constitution_override(repo, staging, contract))\n"
        "live = repo / ph_speckit.CONSTITUTION_MEMORY_REL\n"
        "live.write_bytes(ph_speckit.render_live_constitution(repo, staging, contract))\n"
        "ph_speckit.cmd_record_baselines(repo, None, refresh_override_sha=ph_init.sha256_file(override), refresh_constitution_sha=ph_init.sha256_file(live))\n"
        "import hashlib\n"
        "print(json.dumps({'override_sha': hashlib.sha256(override.read_bytes()).hexdigest(), 'live_sha': hashlib.sha256(live.read_bytes()).hexdigest()}))\n",
        {"repo": repo_str},
    )


def contract() -> dict:
    return json.loads((source_root() / "speckit.json").read_text(encoding="utf-8"))


def _seed_is_current(seed: Path, src: Path) -> bool:
    stamp = seed / ".ph-seed-contract"
    if not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != SEED_CONTRACT_STAMP:
        return False
    if not (seed / ".agents" / "skills" / "ph-specify" / "SKILL.md").is_file():
        return False
    specify = seed / ".agents" / "skills" / "ph-specify" / "SKILL.md"
    if "x-ph-upstream" not in specify.read_text(encoding="utf-8"):
        return False
    # The conversion contract fingerprint: the 1.2.1 layout relocation and the
    # Chinese gated description. A seed from an older conversion (pre-rename
    # .specify tree, English description) must rebuild even though its
    # structure still looks valid.
    if (seed / ".specify").exists():
        return False
    if "不自动串联" not in specify.read_text(encoding="utf-8"):
        return False
    if not (seed / ".agents" / "project-harness" / "constitution.md").is_file():
        return False
    if (seed / ".agents" / "project-harness" / "runtime" / "workflows").exists():
        return False
    template = seed / ".agents" / "project-harness" / "runtime" / "templates" / "plan-template.md"
    if not template.is_file() or "$ph-plan" not in template.read_text(encoding="utf-8"):
        return False
    import hashlib
    bundle = json.loads((src / "assets" / "speckit-bundle.json").read_text(encoding="utf-8"))
    for rel, digest in bundle["files"].items():
        path = seed / rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return True


def ensure_seed() -> Path:
    """Return the shared seed directory, building it once if needed."""

    src = source_root()
    seed = seed_path()
    if _seed_is_current(seed, src):
        return seed
    if seed.exists():
        _retire_temporary(seed)
    seed.mkdir(parents=True, exist_ok=True)
    (seed / ".ph-seed-contract").write_text(SEED_CONTRACT_STAMP + "\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(seed)], check=True)
    proc = subprocess.run(
        [sys.executable, str(src / "scripts" / "ph_speckit.py"),
         "install", "--repo", str(seed), "--apply"],
        capture_output=True, text=True, timeout=1800,
    )
    if proc.returncode != 0:
        raise AssertionError(f"speckit seed install failed: {proc.stderr[-1000:]}")
    if not _seed_is_current(seed, src):
        raise AssertionError("speckit seed install produced an out-of-contract tree")
    return seed
