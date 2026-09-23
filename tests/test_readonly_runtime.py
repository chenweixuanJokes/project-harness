#!/usr/bin/env python3
"""Read-only runtime regression: the real CLI must check without writing.

Reproduces the bytecode-cache pollution regression: after a portable install,
a plain `check` run (no PYTHONDONTWRITEBYTECODE) used to leave
``__pycache__/*.pyc`` next to the installed kernel scripts, so a checked
repository drifted from its payload. The tests below drive the real CLI in
subprocesses and compare full file trees before and after, for both install
modes.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# This flag only covers the harness's own `import ph_init` below (payload
# enumeration). The product under test always runs in a separate subprocess
# with a normal environment, so it can never be masked by this line.
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
TRASH_ROOT = Path.home() / (".Trash" if sys.platform == "darwin" else "trash")

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ph_init  # noqa: E402


def run(argv: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=120, env=env)


def cli_env() -> dict:
    """Normal environment for the CLI under test.

    Bytecode-writing knobs are removed so the subprocess would write caches
    next to the kernel scripts if the product still did that.
    """

    env = dict(os.environ)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.pop("PYTHONPYCACHEPREFIX", None)
    return env


def run_cli(script: Path, *args: str, repo: Path) -> subprocess.CompletedProcess:
    return run([sys.executable, str(script), *args, "--repo", str(repo)], env=cli_env())


def fields(stdout: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in stdout.splitlines()
        if "=" in line and not line.startswith("item=")
    )


def items(stdout: str) -> list[tuple[str, str, str]]:
    parsed = []
    for line in stdout.splitlines():
        if not line.startswith("item="):
            continue
        kind, path, reason = line[5:].split("\t", 2)
        parsed.append((kind, path, reason))
    return parsed


def tree_state(root: Path) -> dict[str, str]:
    """Relative path -> kind plus content evidence, ignoring Git internals.

    Covers directories, regular files (sha256) and symlinks (target text), so
    any file, cache directory or link the CLI adds shows up in the diff.
    """

    state: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if path.is_symlink():
            state[rel] = "link:" + os.readlink(path)
        elif path.is_dir():
            state[rel] = "dir"
        else:
            state[rel] = "file:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return state


def assert_no_bytecode_cache(test: unittest.TestCase, root: Path, label: str) -> None:
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        test.assertNotIn(
            "__pycache__", path.parts, f"{label} gained a bytecode cache dir: {rel}"
        )
        if path.is_file():
            test.assertFalse(
                path.suffix in {".pyc", ".pyo"}, f"{label} gained a bytecode file: {rel}"
            )


class ReadonlyRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A clean payload copy: the assertions compare the installer source
        # too, so the development checkout must not be touched by the runs.
        cls._source = Path(tempfile.mkdtemp(prefix="ph-readonly-payload-"))
        for src in ph_init.ph_init_payload_files():
            dest = cls._source / src.relative_to(REPO_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    @classmethod
    def tearDownClass(cls):
        if sys.platform != "darwin":
            TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        if not TRASH_ROOT.is_dir():
            return
        if cls._source.exists():
            cls._source.rename(TRASH_ROOT / cls._source.name)

    def setUp(self):
        self._temps: list[Path] = []
        self._workspace = Path(tempfile.mkdtemp(prefix="ph-readonly-ws-"))
        self._temps.append(self._workspace)

    def tearDown(self):
        if not self._temps or (sys.platform == "darwin" and not TRASH_ROOT.is_dir()):
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-readonly-{stamp}-{os.getpid()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=False)
        for i, path in enumerate(self._temps):
            if path.exists():
                path.rename(dest / f"{i:02d}-{path.name}")

    def git_repo(self) -> Path:
        root = self._workspace / f"repo-{len(self._temps)}"
        root.mkdir()
        self._temps.append(root)
        for argv in (
            ["git", "init"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "ph-init-test"],
        ):
            proc = run(argv, cwd=root)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return root

    def install(self, mode: str) -> tuple[Path, Path]:
        repo = self.git_repo()
        proc = run_cli(self._source / "scripts" / "ph_init.py", "init", "--mode", mode, "--apply", repo=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertEqual(fields(proc.stdout).get("status"), "ok", proc.stdout)
        # The init entry point imports the kernel modules too; the payload
        # must come out of it as clean as it went in.
        assert_no_bytecode_cache(self, self._source, "installer payload after init")
        return repo, repo / ".agents" / "skills" / "ph-init" / "scripts" / "ph_init.py"

    def assert_check_is_read_only(self, script: Path, repo: Path) -> subprocess.CompletedProcess:
        before_target = tree_state(repo)
        before_payload = tree_state(self._source)
        proc = run_cli(script, "check", repo=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertEqual(fields(proc.stdout).get("status"), "ok", proc.stdout)
        blocking = [item for item in items(proc.stdout) if item[0] in {"error", "conflict", "block"}]
        self.assertEqual(blocking, [], proc.stdout)
        self.assertEqual(tree_state(repo), before_target, "check modified the checked repository")
        self.assertEqual(tree_state(self._source), before_payload, "check modified the installer payload")
        assert_no_bytecode_cache(self, repo, "checked repository")
        assert_no_bytecode_cache(self, self._source, "installer payload")
        return proc

    def test_portable_check_writes_nothing(self):
        repo, installed_script = self.install("portable")
        self.assertTrue(installed_script.is_file(), "portable install misses the kernel script")
        self.assert_check_is_read_only(installed_script, repo)

    def test_symlink_mode_check_writes_nothing(self):
        repo, _ = self.install("symlink")
        # Symlink mode has no kernel copy inside the repo; the check runs from
        # the payload the adapters link back to.
        self.assert_check_is_read_only(self._source / "scripts" / "ph_init.py", repo)

    def test_kernel_cli_entries_write_no_bytecode_cache(self):
        # `--help` already executes each kernel CLI's module top level: the
        # governance and merge-update entries import the other kernel modules
        # before any argument parsing, so an unguarded entry litters the
        # scripts directory even for a pure usage query.
        for name in ("ph_init.py", "ph_governance.py", "ph_merge_update.py"):
            with self.subTest(script=name):
                script = self._source / "scripts" / name
                self.assertTrue(script.is_file(), f"payload misses {name}")
                proc = run([sys.executable, str(script), "--help"], env=cli_env())
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                assert_no_bytecode_cache(self, self._source, f"{name} --help entry")

    def assert_governance_verify_is_read_only(self, script: Path, repo: Path) -> None:
        before_target = tree_state(repo)
        before_payload = tree_state(self._source)
        proc = run_cli(script, "verify", repo=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn('"ok": true', proc.stdout, proc.stdout)
        self.assertEqual(tree_state(repo), before_target, "governance verify modified the repository")
        self.assertEqual(tree_state(self._source), before_payload, "governance verify modified the payload")
        assert_no_bytecode_cache(self, repo, "governance-verified repository")
        assert_no_bytecode_cache(self, self._source, "governance payload")

    def test_portable_governance_verify_writes_nothing(self):
        repo, _ = self.install("portable")
        script = repo / ".agents" / "skills" / "ph-init" / "scripts" / "ph_governance.py"
        self.assertTrue(script.is_file(), "portable install misses the governance script")
        self.assert_governance_verify_is_read_only(script, repo)

    def test_symlink_mode_governance_verify_writes_nothing(self):
        repo, _ = self.install("symlink")
        # Same shape as the check tests: the adapters link back to the
        # payload, so the governance CLI runs from the payload scripts.
        self.assert_governance_verify_is_read_only(self._source / "scripts" / "ph_governance.py", repo)


if __name__ == "__main__":
    unittest.main()
