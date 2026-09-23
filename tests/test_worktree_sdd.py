#!/usr/bin/env python3
"""SDD integration tests for the PH worktree lifecycle script.

Every fixture is a real temporary Git repository under the system temp
directory. Nothing is deleted with ``rm``; workspaces are moved into the
existing macOS ``~/.Trash`` during teardown.

Covers the new-SDD worktree runtime integration: optional task-session
bindings (feature path/id, task IDs, resources), task-group anti-conflict
at enter, feature-group reporting at exit, read-time binding validation,
the doctor feature report, dual-worktree parallel work with serial
delivery, cross-worktree conflict recovery, dirty-tree and cleanup
isolation, feature-evidence preservation before cleanup (missing,
drifted, external-only, archived, tracked-in-feature), and old sessions
without the new fields staying compatible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "assets/scaffold/.agents/scripts/ph_worktree.py"
TRASH = Path.home() / ".Trash"

FEATURE = ".agents/project-harness/specs/001-auth"


class SddFixture(unittest.TestCase):
    def setUp(self):
        self.workspaces: list[Path] = []
        self.new_repo()

    def tearDown(self):
        if not TRASH.is_dir():
            return  # Hosts without a system trash retain fixtures in the temp directory.
        for workspace in self.workspaces:
            if workspace.exists():
                workspace.rename(TRASH / f"ph-worktree-sdd-{os.getpid()}-{time.time_ns()}")

    # ---------- fixture plumbing ----------

    def new_repo(self) -> Path:
        self.workspace = Path(tempfile.mkdtemp(prefix="ph-worktree-sdd-"))
        self.workspaces.append(self.workspace)
        self.repo = self.workspace / "repo"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "PH sdd test")
        self.git("config", "user.email", "ph-sdd@example.com")
        (self.repo / ".gitignore").write_text("/.worktrees/\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# fixture\n", encoding="utf-8")
        (self.repo / "extra.txt").write_text("extra\n", encoding="utf-8")
        (self.repo / ".agents").mkdir()
        self.feature_dir = self.repo / FEATURE
        self.feature_dir.mkdir(parents=True)
        (self.feature_dir / "spec.md").write_text("# spec\n", encoding="utf-8")
        (self.feature_dir / "tasks.md").write_text("- [ ] T001 do a\n- [ ] T002 do b\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
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

    def invoke_raw(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            timeout=120,
        )

    def invoke(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        proc = self.invoke_raw(*args)
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

    def set_manifest(self, verify_commands: list, message: str = "manifest") -> None:
        (self.repo / ".agents" / "ph.json").write_text(
            json.dumps({"worktree": {"verify_commands": verify_commands}}, indent=2) + "\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    @property
    def sessions_dir(self) -> Path:
        return self.repo / ".worktrees" / ".ph" / "sessions"

    def session_records(self) -> dict[str, dict]:
        return {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.sessions_dir.glob("*.json"))
        }

    def completed_records(self) -> dict[str, dict]:
        completed = self.repo / ".worktrees" / ".ph" / "completed"
        return {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(completed.glob("*.json"))
        }

    def enter_sdd(
        self,
        branch: str,
        *,
        feature: str | None = None,
        feature_id: str | None = None,
        task_ids: tuple[str, ...] = (),
        resources: tuple[str, ...] = (),
        apply: bool = False,
    ):
        args = ["enter", "--repo", str(self.repo), "--branch", branch]
        if feature is not None:
            args += ["--feature-path", feature]
        if feature_id is not None:
            args += ["--feature-id", feature_id]
        for task_id in task_ids:
            args += ["--task-id", task_id]
        for resource in resources:
            args += ["--resource", resource]
        if apply:
            # --apply is bound to the reviewed precheck snapshot: carry the
            # dry-run sourceBranch/sourceHead forward so the intended block
            # (a conflict, not drift) still surfaces.
            proc = self.invoke_raw(*args)
            if proc.returncode == 0:
                plan = json.loads(proc.stdout)
                source_branch, source_head = plan["sourceBranch"], plan["sourceHead"]
            else:
                source_branch = self.git("branch", "--show-current").stdout.strip()
                source_head = self.git("rev-parse", "HEAD").stdout.strip()
            args += [
                "--expect-source-branch", source_branch,
                "--expect-source-head", source_head,
                "--apply",
            ]
        return self.invoke(*args)

    def wip(self, repo_path: Path, message: str, *, apply: bool = False):
        args = ["wip", "--repo", str(repo_path), "--message", message]
        if apply:
            proc = self.invoke_raw(*args)
            if proc.returncode == 0:
                plan = json.loads(proc.stdout)
                binding = (plan["branch"], plan["head"], plan["staged"], plan["unstaged"], plan["untracked"])
            else:
                binding = (
                    self.git("branch", "--show-current", cwd=repo_path, check=False).stdout.strip(),
                    self.git("rev-parse", "HEAD", cwd=repo_path, check=False).stdout.strip(),
                    self.git("diff", "--name-only", "--cached", cwd=repo_path, check=False).stdout.split(),
                    self.git("diff", "--name-only", cwd=repo_path, check=False).stdout.split(),
                    self.git("ls-files", "--others", "--exclude-standard", cwd=repo_path, check=False).stdout.split(),
                )
            branch, head, staged, unstaged, untracked = binding
            args += [
                "--expect-branch", branch,
                "--expect-head", head,
                "--expect-staged", ",".join(sorted(staged)),
                "--expect-unstaged", ",".join(sorted(unstaged)),
                "--expect-untracked", ",".join(sorted(untracked)),
                "--apply",
            ]
        return self.invoke(*args)

    def run_exit(self, task_path: Path, *, apply: bool = False, extra: list[str] | None = None):
        args = ["exit", "--repo", str(task_path), *(extra or [])]
        if apply:
            args.append("--apply")
        return self.invoke(*args)

    def make_task(self, branch: str, **binding) -> Path:
        _, payload = self.assert_ok(*self.enter_sdd(branch, apply=True, **binding))
        return Path(payload["taskPath"])

    def commit_task_change(self, task_path: Path, rel: str, text: str, message: str) -> str:
        target = task_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        _, payload = self.assert_ok(*self.wip(task_path, message, apply=True))
        return payload["commit"]

    def status_set(self, cwd: Path) -> list[str]:
        out = self.git("status", "--porcelain", cwd=cwd).stdout
        return sorted(line for line in out.splitlines() if line)


class FeatureBindingTests(SddFixture):
    def test_enter_records_optional_feature_binding(self):
        # A non-canonical spelling must be recorded in canonical form so the
        # same directory always binds to one group identity.
        messy = "./" + FEATURE + "/."
        proc, plan = self.assert_ok(
            *self.enter_sdd(
                "feat/task-a",
                feature=messy,
                feature_id="001-auth",
                task_ids=("T001",),
                resources=("port=8081",),
            )
        )
        self.assertEqual(plan["feature"], {
            "path": FEATURE,
            "id": "001-auth",
            "exists": True,
            "taskIds": ["T001"],
            "resources": {"port": "8081"},
        })
        _, payload = self.assert_ok(*self.enter_sdd(
            "feat/task-a",
            feature=messy,
            feature_id="001-auth",
            task_ids=("T001",),
            resources=("port=8081",),
            apply=True,
        ))
        task_a = Path(payload["taskPath"])
        session = list(self.session_records().values())[0]
        self.assertEqual(session["featurePath"], FEATURE)
        self.assertEqual(session["featureId"], "001-auth")
        self.assertEqual(session["taskIds"], ["T001"])
        self.assertEqual(session["resources"], {"port": "8081"})

        # A binding without a feature path stores pure metadata.
        self.assert_ok(*self.enter_sdd(
            "feat/task-b", feature_id="loose", task_ids=("T009",), resources=("gpu=0",), apply=True,
        ))
        records = self.session_records()
        self.assertEqual(len(records), 2)
        loose = [data for data in records.values() if data.get("featureId") == "loose"][0]
        self.assertNotIn("featurePath", loose)
        self.assertEqual(loose["taskIds"], ["T009"])
        self.assertEqual(loose["resources"], {"gpu": "0"})
        self.assertTrue(task_a.exists())

    def test_feature_id_defaults_to_feature_path_basename(self):
        self.assert_ok(*self.enter_sdd("feat/task-a", feature=FEATURE, apply=True))
        session = list(self.session_records().values())[0]
        self.assertEqual(session["featurePath"], FEATURE)
        self.assertEqual(session["featureId"], "001-auth")

    def test_malformed_bindings_are_rejected_read_only(self):
        cases = [
            {"feature": "  "},
            {"feature": "/etc"},
            {"feature": "../outside"},
            {"feature": FEATURE + "/../../outside"},
            {"feature": ".worktrees/escape"},
            {"feature": "src/business"},
            {"feature": ".agents/project-harness/documents"},
            {"feature": ".agents/project-harness/specs"},
            {"feature": FEATURE + "/nested"},
            {"feature_id": "  "},
            {"task_ids": ("  ",)},
            {"task_ids": ("T1", " T1 ")},
            {"resources": ("port",)},
            {"resources": ("=8080",)},
            {"resources": ("port= ",)},
        ]
        for kwargs in cases:
            with self.subTest(**kwargs):
                proc, payload = self.enter_sdd("feat/bad", **kwargs)
                self.assert_blocked(proc, payload)
                self.assertEqual(self.session_records(), {})
                self.assertFalse((self.repo / ".worktrees").exists())

    def test_symlinked_feature_path_is_blocked(self):
        outside = self.workspace / "outside-dir"
        outside.mkdir()
        link = self.repo / ".agents" / "project-harness" / "specs" / "linked"
        link.symlink_to(outside, target_is_directory=True)
        try:
            proc, payload = self.enter_sdd("feat/escape", feature=".agents/project-harness/specs/linked")
            self.assert_blocked(proc, payload, "symlink")
            self.assertEqual(self.session_records(), {})
        finally:
            link.unlink()

    def test_feature_path_must_match_specs_metadata(self):
        # A PH feature directory under the specs root with consistent metadata
        # binds, and the id defaults to the directory name.
        self.write_feature_metadata("002-other", {"schema": "ph-feature/1", "id": "002-other"})
        _, payload = self.assert_ok(*self.enter_sdd(
            "feat/task-a", feature=".agents/project-harness/specs/002-other", apply=True,
        ))
        task_a = Path(payload["taskPath"])
        session = list(self.session_records().values())[0]
        self.assertEqual(session["featurePath"], ".agents/project-harness/specs/002-other")
        self.assertEqual(session["featureId"], "002-other")

        # An explicit id must agree with the metadata id.
        proc, payload = self.enter_sdd(
            "feat/task-b", feature=".agents/project-harness/specs/002-other",
            feature_id="custom-name", apply=True,
        )
        self.assert_blocked(proc, payload, "does not match the feature metadata id")

        # The metadata id must agree with the directory name.
        self.write_feature_metadata("003-third", {"schema": "ph-feature/1", "id": "003-renamed"})
        proc, payload = self.enter_sdd("feat/task-c", feature=".agents/project-harness/specs/003-third", apply=True)
        self.assert_blocked(proc, payload, "does not match the feature directory")

        # Unreadable metadata is refused, never guessed around.
        self.write_feature_metadata("004-bad", "not json")
        proc, payload = self.enter_sdd("feat/task-d", feature=".agents/project-harness/specs/004-bad", apply=True)
        self.assert_blocked(proc, payload, "cannot read feature metadata")

        # Read-time: metadata edited after the binding blocks the delivery.
        metadata_file = self.repo / ".agents" / "project-harness" / "specs" / "002-other" / "ph-feature.json"
        metadata_file.write_text(
            json.dumps({"schema": "ph-feature/1", "id": "renamed"}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.commit_all("rename metadata id")
        proc, payload = self.run_exit(task_a)
        self.assert_blocked(proc, payload, "does not match the feature directory")
        metadata_file.write_text(
            json.dumps({"schema": "ph-feature/1", "id": "002-other"}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.commit_all("restore metadata id")
        proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True))
        self.assertEqual(payload["status"], "merged")

    def commit_all(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def write_feature_metadata(self, feature: str, metadata, message: str = "feature metadata") -> None:
        directory = self.repo / ".agents" / "project-harness" / "specs" / feature
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "ph-feature.json"
        target.write_text(
            metadata if isinstance(metadata, str) else json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.commit_all(message)

    def test_feature_task_and_resource_conflicts_block_enter_apply(self):
        self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",), resources=("port=8001",))

        # Same feature group, same task ID: dry-run reports it read-only,
        # the apply is refused.
        proc, plan = self.enter_sdd("feat/task-b", feature=FEATURE, task_ids=("T001",))
        self.assert_ok(proc, plan)
        self.assertEqual(len(plan["featureConflicts"]), 1)
        conflict = plan["featureConflicts"][0]
        self.assertEqual(conflict["taskIds"], ["T001"])
        self.assertIn("phase", conflict)
        proc, payload = self.enter_sdd("feat/task-b", feature=FEATURE, task_ids=("T001",), apply=True)
        self.assert_blocked(proc, payload, "T001")

        # Task IDs stay unique per feature group: a different feature may
        # reuse the same task ID.
        self.assert_ok(*self.enter_sdd("feat/task-x", feature=".agents/project-harness/specs/002-other", task_ids=("T001",), apply=True))

        # Resources are (key, value) identities across ALL live sessions:
        # port=8001 is taken cross-feature, port=8002 is a different resource.
        proc, payload = self.enter_sdd(
            "feat/task-c", feature=".agents/project-harness/specs/002-other", task_ids=("T003",), resources=("port=8001",), apply=True,
        )
        self.assert_blocked(proc, payload, "port=8001")
        self.assert_ok(*self.enter_sdd(
            "feat/task-d", feature=".agents/project-harness/specs/002-other", task_ids=("T003",), resources=("port=8003",), apply=True,
        ))

        # A shared database with the same identity conflicts cross-feature.
        self.assert_ok(*self.enter_sdd(
            "feat/task-e", feature=".agents/project-harness/specs/002-other",
            task_ids=("T004",), resources=("db=pg-9", "port=8004",), apply=True,
        ))
        proc, payload = self.enter_sdd("feat/task-f", feature=FEATURE, task_ids=("T005",), resources=("db=pg-9",), apply=True)
        self.assert_blocked(proc, payload, "db=pg-9")

        # The same (key, value) pair conflicts inside one feature group too.
        proc, payload = self.enter_sdd("feat/task-g", feature=FEATURE, task_ids=("T006",), resources=("port=8001",), apply=True)
        self.assert_blocked(proc, payload, "port=8001")

        # Only the genuinely unconflicting enters created worktrees.
        self.assertEqual(len(self.session_records()), 4)

    def test_conflict_block_happens_before_the_confirmed_wip_commit(self):
        # A dirty source worktree with a conflicting feature binding must be
        # refused before the confirmed WIP commit runs; otherwise the commit
        # would land with no session to deliver.
        self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        (self.repo / "note.txt").write_text("dirty\n", encoding="utf-8")
        proc, plan = self.invoke(
            "enter", "--repo", str(self.repo), "--branch", "feat/task-b", "--feature-path", FEATURE, "--task-id", "T001",
        )
        self.assert_ok(proc, plan)
        before = self.status_set(self.repo)
        proc, payload = self.invoke(
            "enter", "--repo", str(self.repo), "--branch", "feat/task-b", "--feature-path", FEATURE,
            "--task-id", "T001",
            "--expect-source-branch", plan["sourceBranch"],
            "--expect-source-head", plan["sourceHead"],
            "--wip-message", "wip: must not happen",
            "--expect-staged", "", "--expect-unstaged", "", "--expect-untracked", "note.txt",
            "--apply",
        )
        self.assert_blocked(proc, payload, "feature")
        self.assertEqual(self.status_set(self.repo), before, "a conflicted enter must not commit the WIP")
        self.assertEqual(len(self.session_records()), 1)


class ExitGroupTests(SddFixture):
    def test_exit_reports_feature_group_and_pending_siblings(self):
        task_a = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        task_b = self.make_task("feat/task-b", feature=FEATURE, task_ids=("T002",))

        self.commit_task_change(task_a, "a.txt", "a\n", "wip: a")
        proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(payload["feature"]["path"], FEATURE)
        self.assertEqual(payload["feature"]["taskIds"], ["T001"])
        siblings = payload["feature"]["pendingSiblings"]
        self.assertEqual(len(siblings), 1)
        self.assertEqual(siblings[0]["taskIds"], ["T002"])
        self.assertEqual(siblings[0]["phase"], "entered")

        # One subtask merging is visible as a group event, not whole-feature
        # acceptance: the sibling is still pending when B delivers.
        self.commit_task_change(task_b, "b.txt", "b\n", "wip: b")
        proc, payload = self.assert_ok(*self.run_exit(task_b, apply=True))
        siblings = payload["feature"]["pendingSiblings"]
        self.assertEqual([entry["taskIds"] for entry in siblings], [["T001"]])
        self.assertEqual([entry["phase"] for entry in siblings], ["merged"])

        # Cleanup keeps the evidence: the archived session record preserves
        # the feature binding and delivered task IDs.
        proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        completed = self.completed_records()
        self.assertEqual(len(completed), 1)
        record = list(completed.values())[0]
        self.assertEqual(record["featurePath"], FEATURE)
        self.assertEqual(record["taskIds"], ["T001"])

    def test_exit_refuses_tampered_or_redirected_feature_binding(self):
        task_a = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        self.commit_task_change(task_a, "a.txt", "a\n", "wip: a")
        session_path, session = list(self.session_records().items())[0]
        record_file = self.sessions_dir / session_path

        # Case 1: a hand-edited escaping path is refused before anything runs.
        session["featurePath"] = "../../outside"
        record_file.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.run_exit(task_a)
        self.assert_blocked(proc, payload, "featurePath")

        # Case 2: the feature directory is replaced by a symlink redirect.
        session["featurePath"] = FEATURE
        record_file.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        side = self.workspace / "redirect-target"
        side.mkdir()
        self.feature_dir.rename(side / "001-auth")
        try:
            (self.feature_dir).symlink_to(side / "001-auth", target_is_directory=True)
            proc, payload = self.run_exit(task_a)
            self.assert_blocked(proc, payload, "symlink")
        finally:
            (self.feature_dir).unlink()
            (side / "001-auth").rename(self.feature_dir)

        # With the genuine binding restored the delivery proceeds.
        proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True))
        self.assertEqual(payload["status"], "merged")

    def test_doctor_reports_feature_groups_conflicts_and_corruption(self):
        task_a = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        task_b = self.make_task("feat/task-b", feature=FEATURE, task_ids=("T002",))
        records = self.session_records()
        name_a = [name for name, data in records.items() if data["taskIds"] == ["T001"]][0]
        name_b = [name for name, data in records.items() if data["taskIds"] == ["T002"]][0]

        before = self.status_set(self.repo)
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        self.assertEqual(len(payload["featureGroups"]), 1)
        group = payload["featureGroups"][0]
        self.assertEqual(group["featurePath"], FEATURE)
        self.assertEqual(group["featureId"], "001-auth")
        self.assertEqual(
            sorted(entry["session"] for entry in group["sessions"]), sorted([name_a, name_b])
        )
        self.assertEqual(payload["featureConflicts"], [])
        self.assertEqual(self.status_set(self.repo), before, "doctor must be read-only")

        # Tampered overlap surfaces as a conflict; a corrupt binding lands in
        # corruptRecords and leaves the group.
        file_b = self.sessions_dir / name_b
        data_b = json.loads(file_b.read_text(encoding="utf-8"))
        data_b["taskIds"] = ["T001"]
        file_b.write_text(json.dumps(data_b, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        conflicts = payload["featureConflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(sorted(conflicts[0]["sessions"]), sorted([name_a, name_b]))
        self.assertEqual(conflicts[0]["featurePaths"], [FEATURE])
        self.assertEqual(conflicts[0]["taskIds"], ["T001"])

        data_b["featurePath"] = "no/such/../path"
        file_b.write_text(json.dumps(data_b, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        self.assertTrue(any(name_b in entry for entry in payload["corruptRecords"]))
        self.assertEqual(payload["featureConflicts"], [])
        self.assertEqual(len(payload["featureGroups"]), 1)
        self.assertEqual([entry["session"] for entry in payload["featureGroups"][0]["sessions"]], [name_a])

        self.assertTrue(task_a.exists() and task_b.exists())

    def test_doctor_reports_cross_feature_resource_conflicts(self):
        task_a = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",), resources=("db=pg-9",))
        task_b = self.make_task(
            "feat/task-b", feature=".agents/project-harness/specs/002-other",
            task_ids=("T002",), resources=("db=pg-10",),
        )
        records = self.session_records()
        name_a = [name for name, data in records.items() if data["taskIds"] == ["T001"]][0]
        name_b = [name for name, data in records.items() if data["taskIds"] == ["T002"]][0]

        # Different values are different resources: no conflict.
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        self.assertEqual(payload["featureConflicts"], [])

        # The same (key, value) identity across two features is a conflict,
        # which enter would have prevented, so tamper one record to surface
        # the doctor diagnosis.
        file_b = self.sessions_dir / name_b
        data_b = json.loads(file_b.read_text(encoding="utf-8"))
        data_b["resources"] = {"db": "pg-9"}
        file_b.write_text(json.dumps(data_b, indent=2) + "\n", encoding="utf-8")
        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        conflicts = payload["featureConflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(sorted(conflicts[0]["sessions"]), sorted([name_a, name_b]))
        self.assertEqual(
            sorted(conflicts[0]["featurePaths"]),
            sorted([FEATURE, ".agents/project-harness/specs/002-other"]),
        )
        self.assertEqual(conflicts[0]["resources"], ["db=pg-9"])
        self.assertEqual(conflicts[0]["taskIds"], [])
        self.assertTrue(task_a.exists() and task_b.exists())


class EvidencePreservationTests(SddFixture):
    """Cleanup must never destroy the last traceable copy of evidence that a
    bound feature's metadata still references.

    Preservation is proven two ways, mirroring the SDD archive layout: a
    committed archive snapshot whose _evidence manifest maps the recorded
    hash to a tracked, content-identical copy, or the evidence file itself
    tracked inside the feature workspace with unchanged content. Everything
    else - missing, drifted, external-only, untracked, ignored - blocks
    cleanup while exit (merge) keeps reporting without blocking.
    """

    def commit_all(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-qm", message)

    def evidence_record(self, raw_path: str, content: bytes) -> dict:
        return {
            "path": raw_path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }

    def write_evidence_metadata(self, evidence: dict, *, feature: str = FEATURE) -> None:
        metadata = {
            "schema": "ph-feature/1",
            "id": Path(feature).name,
            "flow": "small",
            "title": "evidence preservation fixture",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "artifacts": {
                "verification": {
                    "status": "passed",
                    "fingerprint": hashlib.sha256(b"fixture").hexdigest(),
                    "history": [],
                    "evidence": evidence,
                }
            },
            "archive": [],
        }
        directory = self.repo / feature
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "ph-feature.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.commit_all("feature evidence metadata")

    def archive_copy(
        self, raw_path: str, content: bytes, *, sha: str | None = None, index: int = 1
    ) -> tuple[dict, bytes]:
        safe_base = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_path).name) or "evidence"
        copy = {
            "path": raw_path,
            "sha256": sha or hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "snapshot_path": f"_evidence/{index:04d}-{safe_base}",
        }
        return copy, content

    def write_archive_snapshot(
        self,
        copies: list[dict],
        contents: list[bytes],
        *,
        feature: str = "001-auth",
        commit: bool = True,
    ) -> Path:
        snapshot = self.repo / ".agents/project-harness/archive/features" / feature / "20260101T000000Z"
        evidence_dir = snapshot / "_evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "manifest.json").write_text(
            json.dumps({"schema": "ph-evidence-manifest/1", "copies": copies}, indent=2) + "\n",
            encoding="utf-8",
        )
        for copy, content in zip(copies, contents):
            target = snapshot / copy["snapshot_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if commit:
            self.commit_all("archive snapshot")
        return snapshot

    def issue_kinds(self, payload: dict) -> list[str]:
        return [issue["kind"] for issue in payload.get("featureEvidenceIssues", [])]

    def external_evidence(self, name: str, content: bytes) -> Path:
        path = self.workspace / name
        path.write_bytes(content)
        return path

    def merged_task(self, evidence: dict) -> Path:
        self.write_evidence_metadata(evidence)
        task = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        self.commit_task_change(task, "a.txt", "a\n", "wip: a")
        return task

    def write_metadata_raw(self, text: str, *, feature: str = FEATURE) -> None:
        directory = self.repo / feature
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "ph-feature.json").write_text(text, encoding="utf-8")
        self.commit_all("feature metadata")

    def task_with_metadata_raw(self, text: str) -> Path:
        self.write_metadata_raw(text)
        task = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        self.commit_task_change(task, "a.txt", "a\n", "wip: a")
        return task

    def test_unreadable_feature_metadata_blocks_exit_entirely(self):
        # Corrupt JSON is caught by the binding validation before any evidence
        # reporting: exit is blocked outright, so a damaged metadata can never
        # release anything, let alone cleanup.
        task = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        (self.feature_dir / "ph-feature.json").write_text("{ not json", encoding="utf-8")
        self.commit_all("corrupt metadata")
        self.commit_task_change(task, "a.txt", "a\n", "wip: a")
        proc, payload = self.run_exit(task)
        self.assert_blocked(proc, payload, "cannot read feature metadata")
        self.assertTrue(task.exists())

    def test_heterogeneous_metadata_blocks_cleanup_as_metadata_invalid(self):
        # A parseable metadata with a malformed structure passes binding
        # validation but must fail cleanup closed instead of silently
        # checking nothing.
        metadata = {
            "schema": "ph-feature/1",
            "id": "001-auth",
            "flow": "small",
            "title": "heterogeneous",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "artifacts": ["not", "an", "object"],
            "archive": [],
        }
        task = self.task_with_metadata_raw(json.dumps(metadata, indent=2) + "\n")
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["metadata-invalid"])
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(self.issue_kinds(payload), ["metadata-invalid"])
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("metadata-invalid", payload["error"])
        self.assertTrue(task.exists())

    def test_invalid_evidence_bindings_block_cleanup_as_evidence_invalid(self):
        hex64 = hashlib.sha256(b"fixture").hexdigest()
        metadata = {
            "schema": "ph-feature/1",
            "id": "001-auth",
            "flow": "small",
            "title": "invalid bindings",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "artifacts": {
                "tasks": {
                    "status": "done", "fingerprint": hex64, "history": [],
                    "evidence": "not-an-object",
                },
                "acceptance": {
                    "status": "passed", "fingerprint": hex64, "history": [],
                    "evidence": {"path": FEATURE + "/a.txt"},
                },
                "verification": {
                    "status": "passed", "fingerprint": hex64, "history": [],
                    "evidence": {"path": FEATURE + "/v.txt", "sha256": "deadbeef"},
                },
            },
            "archive": [],
        }
        task = self.task_with_metadata_raw(json.dumps(metadata, indent=2) + "\n")
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["evidence-invalid"] * 3)
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("evidence-invalid", payload["error"])
        self.assertTrue(task.exists())

    def test_history_evidence_bindings_are_preservation_subjects(self):
        # The current evidence is committed inside the feature workspace, but
        # an earlier mark's evidence lives only outside the repository: the
        # historical declaration blocks cleanup until it is preserved too.
        content = b"tracked report\n"
        (self.feature_dir / "report.txt").write_bytes(content)
        external = self.external_evidence("outside-evidence.txt", b"older run\n")
        metadata = {
            "schema": "ph-feature/1",
            "id": "001-auth",
            "flow": "small",
            "title": "history bindings",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "artifacts": {
                "verification": {
                    "status": "passed",
                    "fingerprint": hashlib.sha256(b"fixture").hexdigest(),
                    "evidence": self.evidence_record(FEATURE + "/report.txt", content),
                    "history": [
                        {
                            "status": "passed",
                            "at": "2026-01-01T00:00:00Z",
                            "note": "earlier run",
                            "evidence": self.evidence_record(str(external), b"older run\n"),
                        }
                    ],
                }
            },
            "archive": [],
        }
        task = self.task_with_metadata_raw(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])
        self.assertIn("history[0]", payload["featureEvidenceIssues"][0]["binding"])
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("history[0]", payload["error"])

        # Archiving the historical evidence (committed snapshot copy) removes
        # the last issue and cleanup succeeds.
        copy, blob = self.archive_copy(str(external), b"older run\n")
        self.write_archive_snapshot([copy], [blob])
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        self.assertFalse(task.exists())

    def test_archive_entry_evidence_bindings_are_preservation_subjects(self):
        external = self.external_evidence("outside-evidence.txt", b"archive evidence\n")
        metadata = {
            "schema": "ph-feature/1",
            "id": "001-auth",
            "flow": "small",
            "title": "archive bindings",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "artifacts": {},
            "archive": [
                {
                    "snapshot": "manual",
                    "evidence": self.evidence_record(str(external), b"archive evidence\n"),
                }
            ],
        }
        task = self.task_with_metadata_raw(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])
        self.assertIn("archive[0]", payload["featureEvidenceIssues"][0]["binding"])
        self.assert_ok(*self.run_exit(task, apply=True))
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("archive[0]", payload["error"])
        self.assertTrue(task.exists())

    def test_staged_but_uncommitted_evidence_is_not_claimed_persisted(self):
        # Persistence verdicts consult the committed tree only: a staged
        # working-tree copy matches the recorded hash yet must still be
        # reported as unpreserved, never as safe.
        content = b"staged evidence\n"
        # The metadata is committed while the evidence file does not exist
        # yet, so the staging below cannot be swept into that commit.
        self.write_evidence_metadata(self.evidence_record(FEATURE + "/report.txt", content))
        task = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        (self.feature_dir / "report.txt").write_bytes(content)
        self.git("add", f"{FEATURE}/report.txt")
        self.commit_task_change(task, "a.txt", "a\n", "wip: a")

        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])
        # The existing clean-source gate still blocks the merge itself.
        proc, payload = self.run_exit(task, apply=True)
        self.assert_blocked(proc, payload, "source worktree is not clean")
        self.assertTrue(task.exists())

    def test_non_regular_feature_metadata_is_metadata_invalid(self):
        # A feature metadata path that exists but is not a plain regular file
        # (here: a directory) is a damaged binding, not an absent one, and
        # blocks cleanup; a truly absent metadata stays compatible.
        metadata = {
            "schema": "ph-feature/1",
            "id": "001-auth",
            "flow": "small",
            "title": "absent marker",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "artifacts": {},
            "archive": [],
        }
        task = self.task_with_metadata_raw(json.dumps(metadata, indent=2) + "\n")
        (self.feature_dir / "ph-feature.json").rename(self.workspace / "parked-metadata.json")
        (self.feature_dir / "ph-feature.json").mkdir()
        self.commit_all("metadata replaced by directory")

        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["metadata-invalid"])
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("metadata-invalid", payload["error"])
        self.assertTrue(task.exists())

    def test_committed_evidence_removal_loses_preservation(self):
        # Once the committed copy is removed from the merged source, the
        # evidence is no longer preserved even though it once was.
        content = b"tracked report\n"
        (self.feature_dir / "report.txt").write_bytes(content)
        task = self.merged_task(self.evidence_record(FEATURE + "/report.txt", content))
        self.assert_ok(*self.run_exit(task, apply=True))

        self.git("rm", "-q", f"{FEATURE}/report.txt")
        self.commit_all("remove evidence")
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("missing", payload["error"])
        self.assertTrue(task.exists())

    def test_missing_evidence_blocks_cleanup_but_reports_without_blocking_exit(self):
        # The referenced file was never created; the recorded hash is
        # unverifiable, so cleanup is refused and the worktree stays.
        task = self.merged_task(self.evidence_record(FEATURE + "/report.txt", b"never written\n"))
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["missing"])
        self.assertIn("report.txt", payload["featureEvidenceIssues"][0]["path"])

        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(self.issue_kinds(payload), ["missing"])

        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("missing", payload["error"])
        self.assertTrue(task.exists(), "a blocked cleanup keeps the worktree")

    def test_drifted_evidence_blocks_cleanup_but_reports_without_blocking_exit(self):
        content = b"v1 content\n"
        (self.feature_dir / "report.txt").write_bytes(content)
        drifted = b"v2 content\n"
        (self.feature_dir / "report.txt").write_bytes(drifted)
        task = self.merged_task(self.evidence_record(FEATURE + "/report.txt", content))
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["changed"])

        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(self.issue_kinds(payload), ["changed"])

        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("changed", payload["error"])
        self.assertTrue(task.exists())

    def test_external_only_evidence_blocks_cleanup_while_exit_can_precede_archiving(self):
        # An external file existing today is not long-term delivery: without a
        # tracked archive copy cleanup stays blocked even though the file
        # matches its recorded hash. Exiting (merging) first is still allowed;
        # archiving may legitimately happen after delivery.
        content = b"external evidence\n"
        external = self.external_evidence("outside-evidence.txt", content)
        task = self.merged_task(self.evidence_record(str(external), content))

        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])

        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])

        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertIn("unpreserved", payload["error"])
        self.assertTrue(task.exists())

    def test_archived_evidence_allows_cleanup_even_when_the_original_is_gone(self):
        # Once a committed archive snapshot maps the hash to a tracked,
        # content-identical copy, the original external file disappearing does
        # not matter: the snapshot is the preservation proof.
        content = b"external evidence\n"
        external = self.external_evidence("outside-evidence.txt", content)
        copy, blob = self.archive_copy(str(external), content)
        self.write_evidence_metadata(self.evidence_record(str(external), content))
        self.write_archive_snapshot([copy], [blob])
        # The original leaves its recorded path without being destroyed: it is
        # renamed to a kept location in the workspace, and cleanup must still
        # succeed purely on the committed snapshot copy.
        external.rename(self.workspace / "parked-original-evidence")

        task = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        self.commit_task_change(task, "a.txt", "a\n", "wip: a")
        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertNotIn("featureEvidenceIssues", payload)
        self.assert_ok(*self.run_exit(task, apply=True))

        proc, payload = self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        self.assertFalse(task.exists())
        self.assertEqual(len(self.completed_records()), 1)

    def test_tracked_feature_internal_evidence_allows_cleanup_without_archive(self):
        # Evidence committed inside the feature workspace is already in the
        # merged source once the delivery merges: no archive is required
        # before cleanup, so exit-then-archive stays a valid order.
        content = b"tracked report\n"
        (self.feature_dir / "report.txt").write_bytes(content)
        task = self.merged_task(self.evidence_record(FEATURE + "/report.txt", content))

        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertNotIn("featureEvidenceIssues", payload)
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")

        proc, payload = self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        self.assertFalse(task.exists())

    def test_ignored_feature_internal_evidence_does_not_count_as_preserved(self):
        # An ignored file inside the feature workspace is not tracked, so it
        # fails the preservation bar even though its content still matches.
        content = b"ignored evidence\n"
        (self.feature_dir / "report.log").write_bytes(content)
        gitignore = self.repo / ".gitignore"
        gitignore.write_text(
            gitignore.read_text(encoding="utf-8")
            + f"/{FEATURE}/report.log\n",
            encoding="utf-8",
        )
        task = self.merged_task(self.evidence_record(FEATURE + "/report.log", content))

        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])

        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertTrue(task.exists())

    def test_archive_copy_counts_only_when_tracked_and_manifest_matches(self):
        # An uncommitted snapshot is not yet preservation (and the evidence
        # gate fires before the generic clean-tree gate); committing it makes
        # the archive route valid and cleanup succeeds.
        content = b"external evidence\n"
        external = self.external_evidence("outside-evidence.txt", content)
        task = self.merged_task(self.evidence_record(str(external), content))
        self.assert_ok(*self.run_exit(task, apply=True))

        copy, blob = self.archive_copy(str(external), content)
        self.write_archive_snapshot([copy], [blob], commit=False)
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertTrue(task.exists())

        self.commit_all("commit archive snapshot")
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        self.assertFalse(task.exists())

    def test_manifest_sha_mismatch_does_not_count_as_preserved(self):
        content = b"external evidence\n"
        external = self.external_evidence("outside-evidence.txt", content)
        task = self.merged_task(self.evidence_record(str(external), content))
        self.assert_ok(*self.run_exit(task, apply=True))

        copy, blob = self.archive_copy(str(external), content, sha="0" * 64)
        self.write_archive_snapshot([copy], [blob])
        proc, payload = self.run_exit(task, apply=True, extra=["--cleanup"])
        self.assert_blocked(proc, payload, "cleanup blocked by unpreserved feature evidence")
        self.assertTrue(task.exists())

    def test_dry_run_reports_evidence_issues_without_writing_anything(self):
        content = b"external evidence\n"
        external = self.external_evidence("outside-evidence.txt", content)
        task = self.merged_task(self.evidence_record(str(external), content))
        # Deliver first so a cleanup-planned dry-run is legal; the zero-write
        # assertion then covers both the plain and the cleanup dry-run.
        self.assert_ok(*self.run_exit(task, apply=True))

        before_repo = self.status_set(self.repo)
        before_sessions = self.session_records()
        before_completed = self.completed_records()
        before_tree = self.status_set(task)

        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])
        self.assertFalse(payload["cleanupPlanned"])
        proc, payload = self.assert_ok(*self.run_exit(task, extra=["--cleanup"]))
        self.assertEqual(self.issue_kinds(payload), ["unpreserved"])
        self.assertTrue(payload["cleanupPlanned"])

        self.assertEqual(self.status_set(self.repo), before_repo, "a dry-run must not touch the repo")
        self.assertEqual(self.session_records(), before_sessions)
        self.assertEqual(self.completed_records(), before_completed)
        self.assertEqual(self.status_set(task), before_tree)
        self.assertTrue(task.exists())

    def test_feature_id_only_bindings_keep_the_previous_behavior(self):
        # Without a bound feature workspace there is no evidence anchor: the
        # minimal enhancement scopes preservation to path-bound sessions, so
        # an id-only binding behaves exactly as before - even when a same-named
        # feature directory carries evidence metadata.
        loose = ".agents/project-harness/specs/loose-feature"
        (self.repo / loose).mkdir(parents=True)
        missing = self.repo / loose / "report.txt"
        self.write_evidence_metadata(
            self.evidence_record(str(missing), b"loose evidence\n"), feature=loose
        )
        task = self.make_task("feat/loose", feature_id="loose-feature")
        self.commit_task_change(task, "l.txt", "l\n", "wip: loose")

        proc, payload = self.assert_ok(*self.run_exit(task))
        self.assertNotIn("featureEvidenceIssues", payload)
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertNotIn("featureEvidenceIssues", payload)
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")


class DualWorktreeDeliveryTests(SddFixture):
    def test_parallel_changes_deliver_serially_with_fresh_post_merge_verification(self):
        # Each delivery re-runs its own verification twice (pre-merge in the
        # task worktree, post-merge on the merged source): the appended
        # sentinel proves B's merge is re-verified with B's commands, not
        # rubber-stamped with A's branch-time results.
        sentinel = self.workspace / "sentinel.log"
        os.environ["SDD_SENTINEL"] = str(sentinel)
        try:
            self.set_manifest([["bash", "-c", 'echo a >> "$SDD_SENTINEL"']], "manifest a")
            task_a = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
            self.commit_task_change(task_a, "a.txt", "a\n", "wip: a")
            proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True))
            self.assertEqual(payload["status"], "merged")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "a\na\n")

            self.set_manifest([["bash", "-c", 'echo b >> "$SDD_SENTINEL"']], "manifest b")
            task_b = self.make_task("feat/task-b", feature=FEATURE, task_ids=("T002",))
            self.commit_task_change(task_b, "b.txt", "b\n", "wip: b")
            proc, payload = self.assert_ok(*self.run_exit(task_b, apply=True))
            self.assertEqual(payload["status"], "merged")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "a\na\nb\nb\n")
        finally:
            os.environ.pop("SDD_SENTINEL", None)

        # Both parallel task changes landed in the source branch.
        self.assertTrue((self.repo / "a.txt").exists())
        self.assertTrue((self.repo / "b.txt").exists())
        records = self.session_records()
        self.assertEqual(sorted(data["phase"] for data in records.values()), ["merged", "merged"])
        self.assertEqual(
            sorted(data["taskIds"] for data in records.values()), [["T001"], ["T002"]]
        )
        self.assertTrue(task_a.exists() and task_b.exists(), "cleanup stays a separate confirmation")

    def test_same_target_conflict_serializes_and_recovers_across_worktrees(self):
        task_a = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        task_b = self.make_task("feat/task-b", feature=FEATURE, task_ids=("T002",))
        self.commit_task_change(task_a, "README.md", "# from a\n", "wip: a readme")
        self.commit_task_change(task_b, "README.md", "# from b\n", "wip: b readme")
        a_status = self.status_set(task_a)

        # Serialized same-target delivery: A merges first.
        proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True))
        self.assertEqual(payload["status"], "merged")

        # B's delivery against the same target hits a resumable conflict.
        proc, payload = self.run_exit(task_b, apply=True)
        self.assert_blocked(proc, payload, "merge conflict preserved")
        records = self.session_records()
        phase_b = [data["phase"] for data in records.values() if data["taskIds"] == ["T002"]][0]
        self.assertEqual(phase_b, "merge_conflict")
        self.assertTrue((self.repo / ".git" / "MERGE_HEAD").exists())
        self.assertEqual(self.status_set(task_a), a_status, "a sibling conflict must not touch task A")

        # The conflict state stays read-only for dry-runs.
        proc, payload = self.run_exit(task_b)
        self.assert_blocked(proc, payload, "a merge conflict is active")

        # Resolving in the main worktree and continuing delivers B.
        (self.repo / "README.md").write_text("# combined\n", encoding="utf-8")
        self.git("add", "README.md")
        proc, payload = self.assert_ok(*self.invoke("continue", "--repo", str(task_b), "--apply"))
        self.assertEqual(payload["status"], "merged")
        self.assertEqual(
            self.git("merge-base", "--is-ancestor", "feat/task-b", "HEAD").returncode, 0
        )

        # Cleanup is per-session and isolated.
        proc, payload = self.assert_ok(*self.run_exit(task_b, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        self.assertFalse(task_b.exists())
        self.assertTrue(task_a.exists())

    def test_dirty_sibling_and_the_delivery_lock_stay_per_worktree_safe(self):
        task_a = self.make_task("feat/task-a", feature=FEATURE, task_ids=("T001",))
        task_b = self.make_task("feat/task-b", feature=FEATURE, task_ids=("T002",))
        (task_b / "scratch.txt").write_text("dirty\n", encoding="utf-8")
        b_status = self.status_set(task_b)

        # B's dirty tree does not block A's delivery; the lock is shared, so
        # both applies target the same per-main lock and serialize.
        self.commit_task_change(task_a, "a.txt", "a\n", "wip: a")
        lock = self.repo / ".git" / "ph-delivery.lock"
        lock.write_text('{"pid": 0}\n', encoding="utf-8")
        proc, payload = self.run_exit(task_a, apply=True)
        self.assert_blocked(proc, payload, "ph-delivery.lock")
        proc, payload = self.run_exit(task_b, apply=True)
        self.assert_blocked(proc, payload, "ph-delivery.lock")
        lock.unlink()

        proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True))
        self.assertEqual(payload["status"], "merged")
        proc, payload = self.assert_ok(*self.run_exit(task_a, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        self.assertFalse(task_a.exists())

        # B is untouched: still present, still dirty, still bound.
        self.assertEqual(self.status_set(task_b), b_status)
        self.assertTrue(task_b.exists())
        records = self.session_records()
        self.assertEqual(
            [data["taskIds"] for data in records.values()], [["T002"]]
        )
        self.assertEqual(records[list(records)[0]]["featurePath"], FEATURE)


class OldSessionCompatTests(SddFixture):
    def test_old_sessions_without_feature_fields_keep_working(self):
        task = self.make_task("fix/plain")
        self.commit_task_change(task, "fix.txt", "fix\n", "wip: plain")
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True))
        self.assertEqual(payload["status"], "merged")
        self.assertNotIn("feature", payload)
        # No feature binding means no evidence anchor: the preservation report
        # never appears for old plain sessions.
        self.assertNotIn("featureEvidenceIssues", payload)
        records = self.session_records()
        self.assertEqual(len(records), 1)
        record = list(records.values())[0]
        for field in ("featurePath", "featureId", "taskIds", "resources"):
            self.assertNotIn(field, record)
        proc, payload = self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(payload["status"], "cleaned")
        completed = self.completed_records()
        self.assertEqual(len(completed), 1)
        for field in ("featurePath", "featureId", "taskIds", "resources"):
            self.assertNotIn(field, list(completed.values())[0])

        proc, payload = self.assert_ok(*self.invoke("doctor", "--repo", str(self.repo)))
        self.assertEqual(payload["featureGroups"], [])
        self.assertEqual(payload["featureConflicts"], [])

    def test_shipped_skills_document_the_sdd_integration(self):
        # The rewritten skill texts carry the SDD surface: enter documents the
        # four binding flags; exit pins the subtask-vs-feature boundary, the
        # pending-sibling visibility and the archive separation.
        enter_skill = (REPO_ROOT / "assets/scaffold/.agents/skills/ph-worktree-enter/SKILL.md").read_text(encoding="utf-8")
        exit_skill = (REPO_ROOT / "assets/scaffold/.agents/skills/ph-worktree-exit/SKILL.md").read_text(encoding="utf-8")
        for flag in ("--feature-path", "--feature-id", "--task-id", "--resource key=value"):
            self.assertIn(flag, enter_skill)
        self.assertIn("A merged child task is not whole-feature acceptance or archiving", exit_skill)
        self.assertIn("pending sibling", exit_skill)
        self.assertIn("Do not invoke ph-archive", exit_skill)

    def test_exit_and_sdd_archive_cli_stay_decoupled(self):
        # exit never calls the separate SDD archive CLI and vice versa: the
        # runtime script must not reference it, and cleanup keeps archiving
        # only the session record under .worktrees/.ph/completed/.
        self.assertNotIn("ph_sdd", SCRIPT.read_text(encoding="utf-8"))
        task = self.make_task("fix/plain", feature=FEATURE, task_ids=("T001",))
        self.commit_task_change(task, "fix.txt", "fix\n", "wip: plain")
        self.assert_ok(*self.run_exit(task, apply=True))
        self.assert_ok(*self.run_exit(task, apply=True, extra=["--cleanup"]))
        self.assertEqual(len(self.completed_records()), 1)
        self.assertFalse(list((self.repo / ".agents" / "scripts").glob("ph_sdd*")))


if __name__ == "__main__":
    unittest.main()
