#!/usr/bin/env python3
"""Runtime integration tests for the PH worktree lifecycle script.

Every fixture is a real temporary Git repository under the system temp
directory. Nothing is deleted with ``rm``; workspaces are moved into the
existing macOS ``~/.Trash`` during teardown.

Covers the 1.1.14 runtime additions: the unified ``wip`` subcommand, the
dirty-task blocking of ``exit``, ``redeliver`` after abort or verification
failure, pre-merge snapshot verification for ``continue``/``abort-merge``,
the read-only ``doctor`` report, explicit ``recover`` (archive/adopt), the
recoverable ``creating`` record, structured manifest errors, and the
``enter --expect-source-*`` drift guards.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "assets/scaffold/.agents/skills/ph-worktree-enter/scripts/ph_worktree.py"
EXIT_SCRIPT = REPO_ROOT / "assets/scaffold/.agents/skills/ph-worktree-exit/scripts/ph_worktree.py"
TRASH = Path.home() / ".Trash"

DEFAULT_MANIFEST = {"worktree": {"verify_commands": []}}


class RuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.workspaces: list[Path] = []
        self.new_repo()
        self.manifest = json.loads(json.dumps(DEFAULT_MANIFEST))
        (self.repo / ".agents" / "ph.json").write_text(
            json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8"
        )
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")

    # ---------- fixture plumbing ----------

    def tearDown(self):
        for workspace in self.workspaces:
            if workspace.exists():
                workspace.rename(
                    TRASH / f"ph-worktree-runtime-{os.getpid()}-{time.time_ns()}"
                )

    def new_repo(self) -> Path:
        self.workspace = Path(tempfile.mkdtemp(prefix="ph-worktree-runtime-"))
        self.workspaces.append(self.workspace)
        self.repo = self.workspace / "repo"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "PH runtime test")
        self.git("config", "user.email", "ph-runtime@example.com")
        (self.repo / ".gitignore").write_text("/.worktrees/\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# fixture\n", encoding="utf-8")
        (self.repo / "extra.txt").write_text("extra\n", encoding="utf-8")
        (self.repo / ".agents").mkdir()
        return self.repo

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo),
            text=True,
            capture_output=True,
            timeout=60,
        )
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")
        return proc

    def invoke(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            timeout=120,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail(f"non-JSON output (rc={proc.returncode}): {proc.stdout!r} / {proc.stderr!r}")
        return proc, payload

    def assert_blocked(self, proc, payload, fragment: str | None = None) -> None:
        self.assertEqual(proc.returncode, 2, payload)
        self.assertEqual(payload["status"], "blocked")
        if fragment is not None:
            self.assertIn(fragment, payload["error"])

    def assert_ok(self, proc, payload) -> tuple:
        self.assertEqual(proc.returncode, 0, payload)
        self.assertNotEqual(payload.get("status"), "blocked", payload)
        return proc, payload

    def set_manifest(self, worktree: dict, message: str = "manifest") -> None:
        (self.repo / ".agents" / "ph.json").write_text(
            json.dumps({"worktree": worktree}, indent=2) + "\n", encoding="utf-8"
        )
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    @property
    def sessions_dir(self) -> Path:
        return self.repo / ".worktrees" / ".ph" / "sessions"

    def session_paths(self) -> list[Path]:
        return sorted(self.sessions_dir.glob("*.json"))

    def session_data(self, index: int = 0) -> tuple[Path, dict]:
        paths = self.session_paths()
        self.assertEqual(len(paths), 1, paths)
        return paths[index], json.loads(paths[index].read_text(encoding="utf-8"))

    def enter(self, branch: str, *, apply: bool = False, extra: list[str] | None = None):
        args = ["enter", "--repo", str(self.repo), "--branch", branch, *(extra or [])]
        if apply:
            args.append("--apply")
        return self.invoke(*args)

    def run_exit(self, task_path: Path, *, apply: bool = False, extra: list[str] | None = None):
        args = ["exit", "--repo", str(task_path), *(extra or [])]
        if apply:
            args.append("--apply")
        return self.invoke(*args)

    def wip(self, repo_path: Path, message: str, *, apply: bool = False):
        args = ["wip", "--repo", str(repo_path), "--message", message]
        if apply:
            args.append("--apply")
        return self.invoke(*args)

    def make_task(self, branch: str = "fix/timeout") -> Path:
        _, payload = self.assert_ok(*self.enter(branch, apply=True))
        self.task_branch = branch
        return Path(payload["taskPath"])

    def commit_task_change(
        self,
        task_path: Path,
        text: str = "# fixture task\n",
        message: str = "wip: task change",
    ) -> str:
        (task_path / "README.md").write_text(text, encoding="utf-8")
        _, payload = self.assert_ok(*self.wip(task_path, message, apply=True))
        return payload["commit"]

    def source_advance(self, message: str = "source advance") -> str:
        (self.repo / "extra.txt").write_text(
            (self.repo / "extra.txt").read_text(encoding="utf-8") + message + "\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def source_conflict_change(self, text: str = "# fixture source\n") -> None:
        (self.repo / "README.md").write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "source conflict change")

    def staged_set(self, cwd: Path) -> list[str]:
        out = self.git("diff", "--cached", "--name-only", cwd=cwd).stdout
        return sorted(line for line in out.splitlines() if line)

    def status_set(self, cwd: Path) -> list[str]:
        out = self.git("status", "--porcelain", cwd=cwd).stdout
        return sorted(line for line in out.splitlines() if line)


class WipCommandTests(RuntimeFixture):
    def test_wip_dry_run_is_read_only(self):
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        self.git("add", "a.txt")
        (self.repo / "README.md").write_text("# changed\n", encoding="utf-8")
        (self.repo / "b.txt").write_text("b\n", encoding="utf-8")
        before_status = self.status_set(self.repo)
        head_before = self.git("rev-parse", "HEAD").stdout.strip()
        proc, payload = self.assert_ok(*self.wip(self.repo, "wip: dry run"))
        self.assertFalse(payload["apply"])
        self.assertEqual(payload["staged"], ["a.txt"])
        self.assertEqual(payload["unstaged"], ["README.md"])
        self.assertEqual(payload["untracked"], ["b.txt"])
        self.assertEqual(payload["risks"], [])
        self.assertIn("planned", payload["commit"])
        self.assertEqual(self.status_set(self.repo), before_status, "dry-run must not touch state")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), head_before)

    def test_wip_commits_mixed_changes_and_deletion(self):
        task = self.make_task()
        (task / "a.txt").write_text("a\n", encoding="utf-8")
        self.git("add", "a.txt", cwd=task)
        (task / "README.md").write_text("# changed\n", encoding="utf-8")
        (task / "b.txt").write_text("b\n", encoding="utf-8")
        (task / "extra.txt").unlink()
        proc, payload = self.assert_ok(*self.wip(task, "wip: mixed", apply=True))
        self.assertEqual(
            payload["files"], ["README.md", "a.txt", "b.txt", "extra.txt"]
        )
        name_status = self.git("show", "--name-status", "--format=", "HEAD", cwd=task).stdout
        self.assertIn("A\ta.txt", name_status)
        self.assertIn("M\tREADME.md", name_status)
        self.assertIn("A\tb.txt", name_status)
        self.assertIn("D\textra.txt", name_status)
        self.assertEqual(self.status_set(task), [], "wip must leave the tree clean")

    def test_wip_blocks_secret_path_without_touching_the_index(self):
        task = self.make_task()
        (task / "README.md").write_text("# staged edit\n", encoding="utf-8")
        self.git("add", "README.md", cwd=task)
        (task / "server.key").write_text("pretend key\n", encoding="utf-8")
        before_status = self.status_set(task)
        commits_before = self.git("rev-list", "HEAD").stdout.splitlines()
        proc, payload = self.wip(task, "wip: steal key", apply=True)
        self.assert_blocked(proc, payload, "server.key")
        self.assertEqual(self.status_set(task), before_status, "a blocked wip must not stage anything")
        self.assertEqual(self.git("rev-list", "HEAD").stdout.splitlines(), commits_before)

    def test_wip_blocks_secret_content_in_staged_and_unstaged_diffs(self):
        task = self.make_task()
        (task / "config.py").write_text("password = hunter2secretvalue\n", encoding="utf-8")
        self.git("add", "config.py", cwd=task)
        (task / "README.md").write_text("token: abcdef1234567890\n", encoding="utf-8")
        proc, payload = self.wip(task, "wip: secrets", apply=True)
        self.assert_blocked(proc, payload, "staged content")
        self.assertIn("unstaged content", payload["error"])
        self.assertEqual(self.staged_set(task), ["config.py"])

    def test_wip_blocks_secret_content_in_untracked_files(self):
        task = self.make_task()
        (task / "settings").mkdir()
        (task / "settings" / "settings.ini").write_text(
            "password = abcdefgh123456\n", encoding="utf-8"
        )
        proc, payload = self.wip(task, "wip: untracked secret", apply=True)
        self.assert_blocked(proc, payload, "untracked file")
        self.assertTrue((task / "settings" / "settings.ini").exists())

    def test_wip_blocks_oversized_files_per_manifest_limit(self):
        self.set_manifest({"verify_commands": [], "max_changed_file_bytes": 16})
        task = self.make_task()
        (task / "big.bin").write_text("x" * 64, encoding="utf-8")
        proc, payload = self.wip(task, "wip: big", apply=True)
        self.assert_blocked(proc, payload, "large file")
        self.assertTrue((task / "big.bin").exists())

    def test_wip_leaves_ignored_files_alone(self):
        task = self.make_task()
        (task / ".gitignore").write_text("/.worktrees/\ncache.log\n", encoding="utf-8")
        (task / "cache.log").write_text("cache\n", encoding="utf-8")
        proc, payload = self.assert_ok(*self.wip(task, "wip: ignore rules"))
        self.assertNotIn("cache.log", payload["untracked"])
        self.assertIn(".gitignore", payload["unstaged"])


class ExitDeliveryTests(RuntimeFixture):
    def test_exit_fast_forward_merges_the_task_branch(self):
        task = self.make_task()
        commit = self.commit_task_change(task)
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(payload["merge"], "merged")
        self.assertTrue((task).exists(), "cleanup is a separate confirmation")
        self.assertEqual(
            self.git("merge-base", "--is-ancestor", commit, "HEAD").returncode, 0
        )
        _, session = self.session_data()
        self.assertEqual(session["phase"], "merged")
        self.assertEqual(session["mergedHead"], self.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual(session["taskHead"], commit)

    def test_exit_non_fast_forward_creates_a_merge_commit(self):
        task = self.make_task()
        commit = self.commit_task_change(task)
        source_head = self.source_advance()
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(self.git("rev-parse", "HEAD^1").stdout.strip(), source_head)
        self.assertEqual(self.git("rev-parse", "HEAD^2").stdout.strip(), commit)

    def test_exit_dirty_blocked_and_dry_run_reports_lists(self):
        task = self.make_task()
        (task / "README.md").write_text("# dirty\n", encoding="utf-8")
        (task / "note.txt").write_text("note\n", encoding="utf-8")
        before_status = self.status_set(task)
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertTrue(payload["taskTree"]["untracked"])
        self.assertIn("blocked-dirty", payload["commit"])
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "wip subcommand")
        self.assertEqual(self.status_set(task), before_status)

    def test_exit_accepts_deprecated_message_argument(self):
        task = self.make_task()
        proc, payload = self.assert_ok(
            *self.run_exit(task, apply=True, extra=["--message", "legacy"])
        )
        self.assertEqual(payload["status"], "merged")

    def test_ignored_files_block_cleanup_until_removed(self):
        task = self.make_task()
        (task / ".gitignore").write_text("/.worktrees/\ncache.log\n", encoding="utf-8")
        (task / "cache.log").write_text("cache\n", encoding="utf-8")
        self.assert_ok(*self.wip(task, "wip: ignore rules", apply=True))
        self.assert_ok(*self.run_exit(task, apply=True))
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "ignored files")
        self.assertIn("cache.log", payload["error"])
        (task / "cache.log").rename(self.workspace / "cache.log.kept")
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        self.assertFalse(task.exists())
        self.assertEqual(self.session_paths(), [])
        completed = self.repo / ".worktrees" / ".ph" / "completed"
        self.assertEqual(len(list(completed.glob("*.json"))), 1)


class ExitDryRunReadOnlyTests(RuntimeFixture):
    """Every exit dry-run phase must be a pure read-only plan gate.

    Regression guard: a dry-run used to reach perform_merge,
    complete_verification and cleanup_session for non-entered phases. The
    sentinel verification command proves verify commands never execute, and
    the frozen state proves sessions, index, HEAD and directories stay put.
    """

    DRY_RUN_PHASES = {
        "creating": (True, "creation of this worktree was interrupted"),
        "entered": (False, None),
        "committed": (False, None),
        "merge_conflict": (True, "a merge conflict is active"),
        "merging": (True, "interrupted merge is recorded"),
        "merged_unverified": (False, None),
        "merge_verify_failed": (False, None),
        "merged": (False, None),
    }

    def build_phase(self, phase: str) -> Path:
        self.new_repo()
        # The sentinel lives outside the repo, so a legitimate verification
        # run never trips the run_verification digest guard while still
        # proving whether verification commands executed at all.
        self.sentinel = self.workspace / f"sentinel-{time.time_ns()}"
        os.environ["PH_SENTINEL"] = str(self.sentinel)
        self.set_manifest(
            {"verify_commands": [["bash", "-c", 'printf ran > "$PH_SENTINEL"']]}
        )
        task = self.make_task("fix/dry")
        session_path, session = self.session_data()
        if phase in {"creating", "entered"}:
            if phase == "creating":
                session["phase"] = "creating"
                session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
            return task
        task_head = self.commit_task_change(task, message="wip: dry phase")
        session["taskHead"] = task_head
        if phase == "committed":
            session["phase"] = "committed"
            session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
            return task
        pre_merge_head = self.git("rev-parse", "HEAD").stdout.strip()
        if phase in {"merge_conflict", "merging"}:
            self.source_conflict_change()
            self.git("merge", self.task_branch, check=False)
        else:
            self.source_advance()
            self.git("merge", self.task_branch)
        session["mergeSourceBranch"] = "main"
        session["mergeSourceHead"] = pre_merge_head
        session["mergeTaskHead"] = task_head
        session["phase"] = phase
        if phase in {"merged_unverified", "merge_verify_failed", "merged"}:
            session["mergedHead"] = self.git("rev-parse", "HEAD").stdout.strip()
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        return task

    def freeze(self, task: Path) -> dict:
        completed = self.repo / ".worktrees" / ".ph" / "completed"
        return {
            "sessions": {p.name: p.read_bytes() for p in self.session_paths()},
            "completed": sorted(p.name for p in completed.glob("*.json")),
            "task_status": self.status_set(task),
            "main_status": self.status_set(self.repo),
            "task_head": self.git("rev-parse", "HEAD", cwd=task).stdout.strip(),
            "main_head": self.git("rev-parse", "HEAD").stdout.strip(),
            "task_exists": task.exists(),
        }

    def test_dry_run_is_read_only_in_every_phase(self):
        for phase, (blocked, fragment) in self.DRY_RUN_PHASES.items():
            with self.subTest(phase=phase):
                task = self.build_phase(phase)
                before = self.freeze(task)
                proc, payload = self.run_exit(task)
                if blocked:
                    self.assert_blocked(proc, payload, fragment)
                else:
                    self.assert_ok(proc, payload)
                self.assertEqual(
                    self.freeze(task), before, f"dry-run mutated state in phase {phase}"
                )
                self.assertFalse(self.sentinel.exists())

    def test_dry_run_cleanup_plans_without_removing_anything(self):
        task = self.build_phase("merged")
        before = self.freeze(task)
        proc, payload = self.assert_ok(*self.run_exit(task, extra=["--cleanup"]))
        self.assertTrue(payload["cleanupPlanned"])
        self.assertEqual(self.freeze(task), before)
        self.assertTrue(task.exists())
        self.assertFalse(self.sentinel.exists())

    def test_apply_still_executes_verification_sentinel(self):
        # Detection-power control: the same sentinel manifest must fire on the
        # apply path, proving the dry-run assertions above mean something.
        task = self.build_phase("committed")
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertTrue(self.sentinel.exists())


class MergeSnapshotTests(RuntimeFixture):
    def test_continue_and_abort_reject_a_foreign_merge_then_recover(self):
        task = self.make_task()
        commit = self.commit_task_change(task)
        self.source_conflict_change()
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "merge conflict preserved")
        _, session = self.session_data()
        self.assertEqual(session["phase"], "merge_conflict")
        self.assertEqual(session["mergeTaskHead"], commit)
        self.assertTrue((self.repo / ".git" / "MERGE_HEAD").exists())

        # A different merge in the source tree must be refused. The foreign
        # branch diverges from HEAD~1 so the merge cannot fast-forward.
        self.git("merge", "--abort")
        self.git("checkout", "-q", "-b", "foreign", "HEAD~1")
        (self.repo / "README.md").write_text("# foreign\n", encoding="utf-8")
        self.git("commit", "-qam", "foreign change")
        self.git("checkout", "-q", "main")
        self.git("merge", "foreign", check=False)
        # Dry-run already diagnoses the foreign merge; read-only and blocked.
        proc, payload = self.invoke("continue", "--repo", str(task))
        self.assert_blocked(proc, payload, "a different merge is active")
        proc, payload = self.invoke("continue", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "a different merge is active")
        proc, payload = self.invoke("abort-merge", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "a different merge is active")

        # Redoing the PH merge restores a resumable conflict.
        self.git("merge", "--abort")
        self.git("merge", self.task_branch, check=False)
        (self.repo / "README.md").write_text("# resolved\n", encoding="utf-8")
        self.git("add", "README.md")
        proc, payload = self.assert_ok(*self.invoke("continue", "--repo", str(task), "--apply"))
        self.assertEqual(payload["status"], "merged")

    def test_legacy_session_without_snapshot_uses_git_merge_state_evidence(self):
        task = self.make_task()
        self.commit_task_change(task)
        self.source_conflict_change()
        self.run_exit(task, apply=True)  # blocked with a preserved conflict
        session_path, session = self.session_data()
        self.assertEqual(session["phase"], "merge_conflict")
        # Simulate a pre-1.1.14 record: strip the new snapshot fields.
        for field in ("mergeSourceBranch", "mergeSourceHead", "mergeTaskHead"):
            session.pop(field, None)
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")

        # A foreign merge is still refused on the reconstructed evidence.
        # The foreign branch diverges from HEAD~1 so no fast-forward occurs.
        self.git("merge", "--abort")
        self.git("checkout", "-q", "-b", "foreign", "HEAD~1")
        (self.repo / "README.md").write_text("# foreign\n", encoding="utf-8")
        self.git("commit", "-qam", "foreign change")
        self.git("checkout", "-q", "main")
        self.git("merge", "foreign", check=False)
        proc, payload = self.invoke("continue", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "a different merge is active")

        # The genuine PH merge is accepted via ORIG_HEAD evidence.
        self.git("merge", "--abort")
        self.git("merge", self.task_branch, check=False)
        (self.repo / "README.md").write_text("# resolved\n", encoding="utf-8")
        self.git("add", "README.md")
        proc, payload = self.assert_ok(*self.invoke("continue", "--repo", str(task), "--apply"))
        self.assertEqual(payload["status"], "merged")

    def test_interrupted_merging_phase_resolves_from_git_state(self):
        task = self.make_task()
        self.commit_task_change(task)
        self.source_conflict_change()
        self.run_exit(task, apply=True)  # blocked; pre-merge snapshot recorded
        session_path, session = self.session_data()
        self.assertEqual(session["phase"], "merge_conflict")

        # Crash 1: the merging snapshot was written but Git has no merge state.
        self.git("merge", "--abort")
        session["phase"] = "merging"
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.invoke("continue", "--repo", str(task))
        self.assert_ok(proc, payload)
        self.assertEqual(payload["interruptedMergeResolvesTo"], "committed")

        # Crash 2: the snapshot was written and Git holds the real conflict.
        self.git("merge", self.task_branch, check=False)
        proc, payload = self.invoke("continue", "--repo", str(task))
        self.assertEqual(payload["interruptedMergeResolvesTo"], "merge_conflict")
        (self.repo / "README.md").write_text("# resolved\n", encoding="utf-8")
        self.git("add", "README.md")
        proc, payload = self.assert_ok(*self.invoke("continue", "--repo", str(task), "--apply"))
        self.assertEqual(payload["status"], "merged")

        # Crash 3: the merge completed but the phase write was interrupted.
        _, session = self.session_data()
        session["phase"] = "merging"
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.invoke("continue", "--repo", str(task))
        self.assertEqual(payload["interruptedMergeResolvesTo"], "merged_unverified")
        proc, payload = self.invoke("continue", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "(phase: merged_unverified)")
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")


class RedeliverTests(RuntimeFixture):
    def prepare_conflict(self) -> tuple[Path, str]:
        task = self.make_task()
        commit = self.commit_task_change(task)
        self.source_conflict_change()
        self.run_exit(task, apply=True)  # blocked with a preserved conflict
        proc, payload = self.assert_ok(*self.invoke("abort-merge", "--repo", str(task), "--apply"))
        self.assertEqual(payload["phase"], "committed")
        return task, commit

    def test_abort_then_fix_then_redeliver_merges(self):
        task, first_commit = self.prepare_conflict()
        # With no supplementary commit, redeliver defers to the exit retry.
        proc, payload = self.invoke("redeliver", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "no new commits")
        # Fix the branch by merging the source into the task branch.
        self.git("merge", "main", cwd=task, check=False)
        (task / "README.md").write_text("# resolved in task\n", encoding="utf-8")
        self.git("add", "README.md", cwd=task)
        self.git("commit", "-qm", "merge source into task", cwd=task)
        second_commit = self.git("rev-parse", "HEAD", cwd=task).stdout.strip()

        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "task HEAD changed")

        proc, payload = self.assert_ok(*self.invoke("redeliver", "--repo", str(task)))
        self.assertEqual(payload["fromTaskHead"], first_commit)
        self.assertEqual(payload["toTaskHead"], second_commit)

        proc, payload = self.assert_ok(*self.invoke("redeliver", "--repo", str(task), "--apply"))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(
            self.git("merge-base", "--is-ancestor", second_commit, "HEAD").returncode, 0
        )
        _, session = self.session_data()
        self.assertEqual(
            session["redeliveries"],
            [{"from": first_commit, "to": second_commit, "at": session["redeliveries"][0]["at"]}],
        )

        # A merged session is no longer a redelivery candidate.
        proc, payload = self.invoke("redeliver", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "not merged")

    def test_redeliver_blocked_on_rewritten_task_history(self):
        task, first_commit = self.prepare_conflict()
        self.git("reset", "-q", "--hard", "HEAD~1", cwd=task)
        (task / "other.txt").write_text("other\n", encoding="utf-8")
        self.git("add", "-A", cwd=task)
        self.git("commit", "-qm", "different work", cwd=task)
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "task HEAD changed")
        proc, payload = self.invoke("redeliver", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "not a descendant")

    def test_verification_failure_retry_and_redeliver_records(self):
        self.set_manifest(
            {"verify_commands": [["bash", "-c", "git log -1 --format=%s | grep -q task"]]}
        )
        task = self.make_task()
        first_commit = self.commit_task_change(task, message="wip: task change")
        self.source_advance()
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "post-merge verification failed")
        _, session = self.session_data()
        self.assertEqual(session["phase"], "merge_verify_failed")
        self.assertEqual(
            self.git("merge-base", "--is-ancestor", first_commit, "HEAD").returncode, 0
        )

        # Unchanged task head: the original retry path still applies.
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "post-merge verification failed")

        # Supplementary task commit: only redeliver can move the delivery.
        self.commit_task_change(
            task, text="# fixture task two\n", message="wip: task round two"
        )
        second_commit = self.git("rev-parse", "HEAD", cwd=task).stdout.strip()
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "task HEAD changed")
        proc, payload = self.invoke("redeliver", "--repo", str(task), "--apply")
        self.assert_blocked(proc, payload, "post-merge verification failed")
        _, session = self.session_data()
        self.assertEqual(session["phase"], "merge_verify_failed")
        self.assertEqual(
            [entry["from"] for entry in session["redeliveries"]], [first_commit]
        )
        self.assertEqual(
            [entry["to"] for entry in session["redeliveries"]], [second_commit]
        )


class DoctorRecoverTests(RuntimeFixture):
    def test_doctor_reports_inconsistencies_read_only(self):
        task = self.make_task("fix/alpha")
        session_path, session = self.session_data()
        self.git("worktree", "remove", str(task))  # orphan the entered session
        duplicate = self.sessions_dir / "duplicate.json"
        duplicate.write_text(session_path.read_text(encoding="utf-8"), encoding="utf-8")
        (self.sessions_dir / "corrupt.json").write_text("not json", encoding="utf-8")
        self.git("worktree", "add", "-b", "manual-b", str(self.repo / ".worktrees" / "manual-b"))
        (self.repo / ".worktrees" / "probe.txt").write_text("probe\n", encoding="utf-8")

        before = self.status_set(self.repo)
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        self.assertEqual(
            sorted(payload["orphans"]), sorted([session_path.name, "duplicate.json"])
        )
        self.assertEqual(len(payload["duplicates"]), 1)
        self.assertEqual(
            {entry["session"] for entry in payload["duplicates"][0]["sessions"]},
            {session_path.name, "duplicate.json"},
        )
        self.assertTrue(
            any(path.endswith("manual-b") for path in payload["unregisteredWorktrees"])
        )
        self.assertEqual(len(payload["corruptRecords"]), 1)
        self.assertTrue(payload["corruptRecords"][0].startswith("corrupt.json:"))
        self.assertEqual(self.status_set(self.repo), before, "doctor must be read-only")

    def test_recover_archives_only_provably_dead_records(self):
        task = self.make_task("fix/alpha")
        session_path, _ = self.session_data()
        proc, payload = self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "archive", "--apply",
        )
        self.assert_blocked(proc, payload, "still exists")
        self.git("worktree", "remove", str(task))
        proc, payload = self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "archive",
        )
        self.assert_ok(proc, payload)
        self.assertIn("archive", payload["planned"])
        proc, payload = self.assert_ok(*self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "archive", "--apply",
        ))
        self.assertEqual(payload["status"], "archived")
        self.assertFalse(session_path.exists())
        completed = self.repo / ".worktrees" / ".ph" / "completed" / session_path.name
        self.assertTrue(completed.exists())
        # Branches and directories are preserved; the task branch still exists.
        self.assertEqual(
            self.git("show-ref", "--verify", "refs/heads/fix/alpha").returncode, 0
        )

    def test_recover_rejects_ambiguous_or_missing_targets(self):
        self.make_task("fix/alpha")
        session_path, _ = self.session_data()
        for args, fragment in (
            (
                ["--session", session_path.name, "--action", "adopt"],
                "interrupted creating record",
            ),
            (["--session", "missing.json", "--action", "archive"], "does not exist"),
            (["--session", "../outside.json", "--action", "archive"], "file name"),
        ):
            proc, payload = self.invoke("recover", "--repo", str(self.repo), *args)
            self.assert_blocked(proc, payload, fragment)

    def test_recover_adopt_restores_an_interrupted_creation(self):
        task = self.make_task("fix/beta")
        session_path, session = self.session_data()
        session["phase"] = "creating"
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        self.assertEqual(payload["interruptedCreating"], [session_path.name])
        proc, payload = self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "adopt",
        )
        self.assert_ok(proc, payload)
        self.assertIn("entered", payload["planned"])
        proc, payload = self.assert_ok(*self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "adopt", "--apply",
        ))
        self.assertEqual(payload["status"], "adopted")
        _, session = self.session_data()
        self.assertEqual(session["phase"], "entered")
        # A restored session delivers normally, including cleanup.
        self.commit_task_change(task, message="wip: after adopt")
        self.assert_ok(*self.run_exit(task, apply=True))
        self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(self.session_paths(), [])

    def test_recover_adopt_rejects_changed_branch_and_duplicates(self):
        task = self.make_task("fix/gamma")
        session_path, session = self.session_data()
        session["phase"] = "creating"
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        duplicate = self.sessions_dir / "duplicate.json"
        duplicate.write_text(session_path.read_text(encoding="utf-8"), encoding="utf-8")
        proc, payload = self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "adopt", "--apply",
        )
        self.assert_blocked(proc, payload, "duplicate records")
        duplicate.unlink()
        self.git("checkout", "-q", "-b", "rogue", cwd=task)
        proc, payload = self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "adopt", "--apply",
        )
        self.assert_blocked(proc, payload, "branch changed")

    def test_cleanup_archival_is_retried_via_recover(self):
        task = self.make_task("fix/delta")
        self.commit_task_change(task, message="wip: delta")
        self.assert_ok(*self.run_exit(task, apply=True))
        session_path, session = self.session_data()
        # Simulate a crash after the worktree removal and cleaned write but
        # before the record moved to completed/.
        self.git("worktree", "remove", str(task))
        session["phase"] = "cleaned"
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        self.assertEqual(payload["cleanedNotArchived"], [session_path.name])
        proc, payload = self.assert_ok(*self.invoke(
            "recover", "--repo", str(self.repo), "--session", session_path.name,
            "--action", "archive", "--apply",
        ))
        self.assertEqual(payload["status"], "archived")
        self.assertEqual(self.session_paths(), [])


class EnterGuardTests(RuntimeFixture):
    def test_enter_blocked_by_a_live_session(self):
        self.make_task("fix/alpha")
        proc, payload = self.enter("fix/alpha")
        self.assert_blocked(proc, payload, "live PH session")
        proc, payload = self.enter("fix/alpha", apply=True)
        self.assert_blocked(proc, payload, "live PH session")
        self.assertEqual(len(self.session_paths()), 1)

    def test_expect_source_guards_block_before_any_write(self):
        wrong_head = "0" * 40
        proc, payload = self.enter(
            "fix/alpha", extra=["--expect-source-head", wrong_head]
        )
        self.assert_blocked(proc, payload, "source HEAD drifted")
        proc, payload = self.enter(
            "fix/alpha", extra=["--expect-source-branch", "release/other"]
        )
        self.assert_blocked(proc, payload, "source branch drifted")
        self.assertEqual(self.session_paths(), [])
        self.assertFalse((self.repo / ".worktrees").exists())

        head = self.git("rev-parse", "HEAD").stdout.strip()
        proc, payload = self.enter(
            "fix/alpha",
            extra=["--expect-source-head", head, "--expect-source-branch", "main"],
        )
        self.assert_ok(proc, payload)

        # Source drift after the plan was taken is caught before writing.
        self.source_advance()
        proc, payload = self.enter(
            "fix/beta", apply=True, extra=["--expect-source-head", head]
        )
        self.assert_blocked(proc, payload, "source HEAD drifted")
        self.assertEqual(len(self.session_paths()), 0)
        self.assertFalse((self.repo / ".worktrees").exists())

    def test_enter_writes_a_recoverable_creating_record(self):
        head = self.git("rev-parse", "HEAD").stdout.strip()
        task = self.make_task("fix/alpha")
        _, session = self.session_data()
        self.assertEqual(session["phase"], "entered")
        self.assertEqual(session["initialTaskHead"], head)
        self.assertEqual(
            self.git("rev-parse", "HEAD", cwd=task).stdout.strip(), head
        )


class ManifestAndLockTests(RuntimeFixture):
    def test_manifest_errors_are_structured(self):
        cases = [
            ("{not json", "JSON parse error"),
            ("[]", "top level must be a JSON object"),
            (json.dumps({"worktree": "nope"}), "'worktree' must be an object"),
            (
                json.dumps({"worktree": {"verify_commands": "nope"}}),
                "verify_commands must be an array",
            ),
            (
                json.dumps({"worktree": {"verify_commands": [], "max_changed_file_bytes": 0}}),
                "positive integer",
            ),
        ]
        for content, fragment in cases:
            with self.subTest(content=content):
                self.new_repo()
                (self.repo / ".gitignore").write_text("/.worktrees/\n", encoding="utf-8")
                (self.repo / "README.md").write_text("# fixture\n", encoding="utf-8")
                (self.repo / ".agents" / "ph.json").write_text(content, encoding="utf-8")
                self.git("add", "-A")
                self.git("commit", "-qm", "fixture")
                proc, payload = self.enter("fix/alpha")
                self.assert_blocked(proc, payload, fragment)
                self.assertFalse((self.repo / ".worktrees").exists())

    def test_unreadable_manifest_is_blocked(self):
        (self.repo / ".agents" / "ph.json").chmod(0o000)
        try:
            proc, payload = self.enter("fix/alpha")
            self.assert_blocked(proc, payload, "cannot read .agents/ph.json")
        finally:
            (self.repo / ".agents" / "ph.json").chmod(0o644)

    def test_lock_blocks_apply_but_not_doctor(self):
        task = self.make_task()
        (task / "note.txt").write_text("note\n", encoding="utf-8")
        lock = self.repo / ".git" / "ph-delivery.lock"
        lock.write_text('{"pid": 0}\n', encoding="utf-8")
        proc, payload = self.wip(task, "wip: locked", apply=True)
        self.assert_blocked(proc, payload, "ph-delivery.lock")
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "ph-delivery.lock")
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        lock.unlink()
        proc, payload = self.assert_ok(*self.wip(task, "wip: unlocked", apply=True))
        self.assertEqual(payload["commit"], self.git("rev-parse", "HEAD", cwd=task).stdout.strip())


class BranchAndSourceDriftTests(RuntimeFixture):
    def test_task_switch_source_switch_and_rewrite_are_blocked(self):
        task = self.make_task()
        self.commit_task_change(task, message="wip: work")

        self.git("checkout", "-q", "-b", "rogue", cwd=task)
        proc, payload = self.run_exit(task)
        self.assert_blocked(proc, payload, "task branch changed")
        self.git("checkout", "-q", "fix/timeout", cwd=task)

        self.git("checkout", "-q", "-b", "elsewhere")
        proc, payload = self.run_exit(task)
        self.assert_blocked(proc, payload, "source branch changed")
        self.git("checkout", "-q", "main")

        self.git("commit", "-q", "--amend", "-m", "fixture rewritten")
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "source history was rewritten")


class ShippedArtifactsTests(unittest.TestCase):
    def test_both_skill_dirs_ship_the_identical_script(self):
        self.assertEqual(
            SCRIPT.read_bytes(),
            EXIT_SCRIPT.read_bytes(),
            "enter and exit must ship the same runtime script",
        )


if __name__ == "__main__":
    unittest.main()
