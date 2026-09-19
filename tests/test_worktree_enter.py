#!/usr/bin/env python3
"""Integration tests for PH worktree creation defaults."""

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
SCRIPT = REPO_ROOT / "assets/scaffold/.agents/scripts/ph_worktree.py"
TRASH_ROOT = Path.home() / "trash"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, text=True, capture_output=True, timeout=60)


class WorktreeEnterTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="ph-worktree-enter-"))
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        for args in (
            ("git", "init", "-q", "-b", "release/current", str(self.repo)),
            ("git", "-C", str(self.repo), "config", "user.name", "PH test"),
            ("git", "-C", str(self.repo), "config", "user.email", "ph-test@example.com"),
        ):
            proc = run(*args)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        (self.repo / ".gitignore").write_text("/.worktrees/\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# fixture\n", encoding="utf-8")
        proc = run("git", "-C", str(self.repo), "add", ".gitignore", "README.md")
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        proc = run("git", "-C", str(self.repo), "commit", "-qm", "fixture")
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def tearDown(self):
        if not self.workspace.exists():
            return
        TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        destination = TRASH_ROOT / f"ph-worktree-enter-{os.getpid()}-{time.time_ns()}"
        self.workspace.rename(destination)

    def invoke(self, branch: str, *, apply: bool = False) -> tuple[subprocess.CompletedProcess[str], dict]:
        args = [sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", branch]
        if apply:
            # --apply is bound to the reviewed precheck snapshot: run the
            # dry-run first and carry its sourceBranch/sourceHead forward.
            plan_proc = run(*args)
            self.assertEqual(plan_proc.returncode, 0, plan_proc.stderr or plan_proc.stdout)
            plan = json.loads(plan_proc.stdout)
            args += [
                "--expect-source-branch", plan["sourceBranch"],
                "--expect-source-head", plan["sourceHead"],
                "--apply",
            ]
        proc = run(*args)
        payload = json.loads(proc.stdout)
        return proc, payload

    def test_plan_uses_main_worktree_current_branch_as_source(self):
        proc, plan = self.invoke("fix/login-timeout")
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertEqual(plan["sourceBranch"], "release/current")
        self.assertEqual(plan["sourceHead"], run("git", "-C", str(self.repo), "rev-parse", "HEAD").stdout.strip())
        self.assertEqual(plan["taskBranch"], "fix/login-timeout")
        self.assertFalse(plan["existingBranch"])
        self.assertFalse(plan["apply"])
        self.assertFalse((self.repo / ".worktrees").exists(), "dry-run must not create state")

    def test_apply_creates_new_branch_and_linked_worktree_in_one_step(self):
        source_head = run("git", "-C", str(self.repo), "rev-parse", "HEAD").stdout.strip()
        proc, result = self.invoke("fix/login-timeout", apply=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["sourceBranch"], "release/current")
        self.assertEqual(run("git", "-C", str(self.repo), "branch", "--show-current").stdout.strip(), "release/current")
        self.assertEqual(run("git", "-C", str(self.repo), "rev-parse", "HEAD").stdout.strip(), source_head)
        task_path = Path(result["taskPath"])
        self.assertTrue(task_path.is_dir())
        self.assertEqual(run("git", "-C", str(task_path), "branch", "--show-current").stdout.strip(), "fix/login-timeout")
        self.assertEqual(run("git", "-C", str(task_path), "rev-parse", "HEAD").stdout.strip(), source_head)
        self.assertEqual(run("git", "-C", str(self.repo), "show-ref", "--verify", "--quiet", "refs/heads/fix/login-timeout").returncode, 0)
        sessions = list((self.repo / ".worktrees/.ph/sessions").glob("*.json"))
        self.assertEqual(len(sessions), 1)
        session = json.loads(sessions[0].read_text(encoding="utf-8"))
        self.assertEqual(session["sourceBranch"], "release/current")
        self.assertEqual(session["taskBranch"], "fix/login-timeout")
        self.assertEqual(Path(session["taskPath"]), task_path)

    def test_apply_requires_and_enforces_precheck_snapshot_binding(self):
        # --apply without the reviewed snapshot is rejected outright, and a
        # mismatching snapshot (source drifted between review and apply) is
        # blocked instead of silently accepted.
        branch = "fix/binding"
        proc, _ = self.invoke(branch, apply=False)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        head = run("git", "-C", str(self.repo), "rev-parse", "HEAD").stdout.strip()
        for argv in (
            [sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", branch, "--apply"],
            [sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", branch,
             "--expect-source-head", head, "--apply"],
        ):
            proc = run(*argv)
            self.assertEqual(proc.returncode, 2, proc.stdout)
            self.assertIn("requires --expect-source-branch", proc.stdout)
        bad = [sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", branch,
               "--expect-source-branch", "release/current",
               "--expect-source-head", "0" * 40, "--apply"]
        proc = run(*bad)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("source HEAD drifted", proc.stdout)
        self.assertFalse((self.repo / ".worktrees").exists(), "blocked apply must not create state")

    def test_shipped_skill_binds_apply_to_reviewed_snapshot(self):
        skill = (REPO_ROOT / "assets/scaffold/.agents/skills/ph-worktree-enter/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--expect-source-branch <计划的 sourceBranch>", skill)
        self.assertIn("--expect-source-head <计划的 sourceHead>", skill)
        self.assertIn("两者缺一脚本直接拒绝", skill)
        self.assertIn("--expect-staged <计划的 sourceDirty.staged>", skill)

    def test_shipped_skill_reports_merge_state_without_redirect_or_questions(self):
        """A merge state is notified and awaited, never auto-routed.

        The user decides how to finish the merge and re-invokes this skill;
        enter must not hand over to ph-worktree-exit, must not pop the
        conflict-recovery question (that flow belongs to exit's own
        delivery/recovery), and must not ask the WIP question either.
        """
        skill = (REPO_ROOT / "assets/scaffold/.agents/skills/ph-worktree-enter/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("直接告诉用户当前处于合并状态", skill)
        self.assertIn("由用户自行完成合并后重新调用本技能", skill)
        self.assertIn("不代为转交其他技能、不自动弹冲突处理问句", skill)
        self.assertIn("不问 WIP、不创建隔离工作区", skill)
        self.assertNotIn("先按 `ph-worktree-exit`", skill)
        doc = (REPO_ROOT / "assets/scaffold/docs/约束规范/工程规范/Git与并行开发.md").read_text(encoding="utf-8")
        self.assertIn("另起的 `ph-worktree-enter` 调用遇冲突态只提示用户处于合并状态", doc)

    def test_enter_in_merge_conflict_state_errors_before_any_wip_flow(self):
        # Script-level contract: a main worktree mid-merge (MERGE_HEAD plus
        # unmerged entries) is refused before any WIP question, session, or
        # worktree is created - the state is the user's to finish.
        def git(*args: str):
            proc = run("git", "-C", str(self.repo), *args)
            self.assertTrue(proc.returncode in (0, 1), proc.stderr or proc.stdout)
            return proc

        branch = "fix/conflicted"
        git("checkout", "-q", "-b", "side")
        (self.repo / "README.md").write_text("# side\n", encoding="utf-8")
        git("commit", "-qam", "side change")
        git("checkout", "-q", "release/current")
        (self.repo / "README.md").write_text("# main\n", encoding="utf-8")
        git("commit", "-qam", "main change")
        git("merge", "side")
        self.assertTrue((self.repo / ".git" / "MERGE_HEAD").exists())
        proc, _ = self.invoke(branch, apply=False)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("Git operation already in progress", proc.stdout + proc.stderr)
        self.assertFalse((self.repo / ".worktrees").exists(), "refused enter must not create state")


    def test_enter_dirty_source_single_apply_commits_wip_and_creates(self):
        # One apply commits the confirmed WIP and creates the worktree; a
        # bare apply (or one without the path bindings) refuses before
        # staging anything.
        (self.repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# changed\n", encoding="utf-8")
        before = run("git", "-C", str(self.repo), "status", "--porcelain").stdout
        plan = json.loads(run(
            sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", "fix/dirty"
        ).stdout)
        self.assertTrue(plan["sourceDirty"]["untracked"])
        self.assertTrue(plan["wipPlanned"])
        head = plan["sourceHead"]
        branch = plan["sourceBranch"]
        # Bare apply without the confirmed message refuses with no effect.
        proc = run(sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", "fix/dirty",
                   "--expect-source-branch", branch, "--expect-source-head", head, "--apply")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("no confirmed WIP", proc.stdout + proc.stderr)
        self.assertEqual(run("git", "-C", str(self.repo), "status", "--porcelain").stdout, before)
        # With the message but without the path bindings, still nothing is staged.
        proc = run(sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", "fix/dirty",
                   "--expect-source-branch", branch, "--expect-source-head", head,
                   "--wip-message", "wip: confirmed source", "--apply")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("--expect-staged", proc.stdout + proc.stderr)
        self.assertEqual(run("git", "-C", str(self.repo), "status", "--porcelain").stdout, before)
        # The single confirmed apply commits the WIP and creates the worktree.
        proc = run(sys.executable, str(SCRIPT), "enter", "--repo", str(self.repo), "--branch", "fix/dirty",
                   "--expect-source-branch", branch, "--expect-source-head", head,
                   "--wip-message", "wip: confirmed source",
                   "--expect-staged", ",".join(plan["sourceDirty"]["staged"]),
                   "--expect-unstaged", ",".join(plan["sourceDirty"]["unstaged"]),
                   "--expect-untracked", ",".join(plan["sourceDirty"]["untracked"]),
                   "--apply")
        payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertEqual(payload["status"], "created")
        self.assertIn("wipCommit", payload)
        self.assertEqual(run("git", "-C", str(self.repo), "status", "--porcelain").stdout, "")
        task = Path(payload["taskPath"])
        self.assertEqual(run("git", "-C", str(task), "branch", "--show-current").stdout.strip(), "fix/dirty")
        self.assertEqual(run("git", "-C", str(task), "rev-parse", "HEAD").stdout.strip(), payload["wipCommit"])
        subject = run("git", "-C", str(self.repo), "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, "wip: confirmed source")

    def test_shipped_skill_does_not_require_normal_creation_confirmation(self):
        """Behavioral boundary (semantic, not sentence-bank anchored).

        An explicit creation request is itself the authorization: the source
        is the main worktree's current branch, the task branch is derived by
        the agent, and none of the two nor the actual creation is re-asked.
        Abnormal findings stop the flow instead of turning the already-given
        authorization back into a confirmation question. Both the skill and
        the question contract's boundary example must state this.
        """
        skill = (REPO_ROOT / "assets/scaffold/.agents/skills/ph-worktree-enter/SKILL.md").read_text(encoding="utf-8")
        questions = (REPO_ROOT / "assets/scaffold/docs/约束规范/工程规范/对用户提问.md").read_text(encoding="utf-8")
        # authorization premise and source-branch semantics in the skill
        self.assertIn("用户明确要求", skill)
        self.assertIn("当前所在分支", skill)
        # no re-asking of source branch, task branch, or actual creation
        self.assertIn("不为这两个分支或实际创建再次询问", skill)
        self.assertNotIn("确认后我才会真正创建", skill)
        # safety gates still stop abnormal runs instead of re-asking everything
        self.assertIn("仍须停止", skill)
        # the question contract's boundary example states the same behavior
        self.assertIn("用户明确要求创建隔离工作区", questions)
        self.assertIn("主工作区当前分支", questions)
        self.assertIn("任务分支按项目规则确定", questions)
        self.assertIn("安全阻断", questions)


if __name__ == "__main__":
    unittest.main()
