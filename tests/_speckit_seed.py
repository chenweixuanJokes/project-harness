"""Shared real spec-kit install seed for upgrade fixtures.

Both the merge-update fixtures and the historical upgrade matrix simulate the
Agent-executed 1.1.14 speckit-core-integration item by copying a real pinned
generation install. The seed is built once per machine (cache or network) by
running the actual ``ph_speckit.py install --apply`` into a temporary git repo,
then reused read-only. A stale seed from an older install contract (shared
files without the ph- rename, or one that still ships the workflow-engine
assets) is discarded and rebuilt.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The seed must match the current install contract: shared files carry the
# ph- rename ($ph-plan), the workflow-engine assets are absent (engine
# dispatch is upstream-namespace bound at the pinned release), and the ten
# skills carry upstream provenance.
_SEED_PREFIX = "ph-speckit-seed-"


def seed_path() -> Path:
    return Path(tempfile.gettempdir()) / f"{_SEED_PREFIX}{os.getuid()}"


def _seed_is_current(seed: Path) -> bool:
    if not (seed / ".specify" / "memory" / "constitution.md").is_file():
        return False
    if (seed / ".specify" / "workflows").exists():
        return False
    template = seed / ".specify" / "templates" / "plan-template.md"
    if not template.is_file() or "$ph-plan" not in template.read_text(encoding="utf-8"):
        return False
    provenance = seed / ".agents" / "skills" / "ph-specify" / "SKILL.md"
    if not provenance.is_file() or "x-ph-upstream" not in provenance.read_text(encoding="utf-8"):
        return False
    return True


def ensure_seed() -> Path:
    """Return the shared seed directory, building it once if needed."""
    seed = seed_path()
    if _seed_is_current(seed):
        return seed
    if seed.exists():
        shutil.rmtree(seed, ignore_errors=True)
    seed.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(seed)], check=True)
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "ph_speckit.py"),
         "install", "--repo", str(seed), "--apply"],
        capture_output=True, text=True, timeout=1800,
    )
    if proc.returncode != 0:
        raise AssertionError(f"speckit seed install failed: {proc.stderr[-1000:]}")
    if not _seed_is_current(seed):
        raise AssertionError("speckit seed install produced an out-of-contract tree")
    return seed


def contract() -> dict:
    return json.loads((REPO_ROOT / "speckit.json").read_text(encoding="utf-8"))
