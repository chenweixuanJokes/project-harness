#!/usr/bin/env python3
"""Governance takeover tests: constitution materialization, navigation refresh,
content evidence verification - the capabilities extracted from the retired
spec-kit integration script into scripts/ph_governance.py (1.2.3)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

import ph_governance  # noqa: E402
from content_fixture import complete_documentation_project  # noqa: E402

TRASH_ROOT = Path.home() / "trash"


def run_cli(*argv):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "ph_governance.py"), *argv],
        capture_output=True, text=True, timeout=120,
    )


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self._temps = []

    def tearDown(self):
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-governance-{stamp}-{os.getpid()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=False)
        for i, path in enumerate(self._temps):
            if Path(path).exists():
                Path(path).rename(dest / f"{i:02d}-{Path(path).name}")

    def temp_dir(self, prefix):
        root = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(root)
        return root

    def git_repo(self, prefix):
        root = self.temp_dir(prefix)
        for argv in (["git", "init"], ["git", "config", "user.email", "t@example.com"], ["git", "config", "user.name", "t"]):
            proc = subprocess.run(argv, cwd=root, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return root

    def seeded_repo(self):
        repo = self.git_repo("ph-gov-")
        manifest = repo / ".agents" / "ph.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"template_version": "1.2.3"}), encoding="utf-8")
        complete_documentation_project(repo, REPO_ROOT)
        return repo

    def test_materialize_creates_missing_constitution_and_cli_matches(self):
        repo = self.seeded_repo()
        proc = run_cli("materialize-constitution", "--repo", str(repo))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads(proc.stdout)
        self.assertEqual(plan["kind"], "write")
        self.assertFalse((repo / ph_governance.CONSTITUTION).exists(), "plan must not write")
        proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        written = (repo / ph_governance.CONSTITUTION).read_bytes()
        self.assertTrue(written.split(b"\n")[0].startswith(b"# "))
        self.assertIn(ph_governance.GOVERNANCE_MARKER.encode(), written)
        # repeated runs skip: the constitution is user-owned content
        proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
        self.assertEqual(json.loads(proc.stdout)["kind"], "skip")
        self.assertEqual((repo / ph_governance.CONSTITUTION).read_bytes(), written)

    def test_materialize_never_overwrites_existing_constitution(self):
        repo = self.seeded_repo()
        dest = repo / ph_governance.CONSTITUTION
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"# my own principles\nkeep me\n")
        proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
        self.assertEqual(json.loads(proc.stdout)["kind"], "skip")
        self.assertEqual(dest.read_bytes(), b"# my own principles\nkeep me\n")

    def test_refresh_refuses_hardlinked_constitution_without_writing_through(self):
        """Regression: an in-place write goes through the shared inode, so a
        constitution hardlinked to a file outside the repository used to carry
        the navigation replacement out of the repo. The destination must be
        refused before any byte is written."""

        repo = self.seeded_repo()
        proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        dest = repo / ph_governance.CONSTITUTION
        outside = self.temp_dir("ph-gov-outside-") / "outside-constitution.md"
        os.link(dest, outside)
        original = outside.read_bytes()
        custom = repo / ".agents/project-harness/constraints/custom-rule.md"
        custom.write_text("# 自定义规则\n\n使用时机：触及本规则的工作前阅读。\n", encoding="utf-8")
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        proc = run_cli("refresh-navigation", "--repo", str(repo), "--expected-sha", sha, "--apply")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("hardlink", proc.stderr)
        self.assertEqual(outside.read_bytes(), original, "the write escaped through the hardlink")
        self.assertEqual(dest.read_bytes(), original)
        # The plain materialize path reports the same shape as a conflict
        # instead of raising, so the caller keeps an actionable payload.
        item = ph_governance.materialize_constitution(repo, apply=True)
        self.assertEqual(item["kind"], "conflict")
        self.assertIn("hardlink", item["reason"])

    def test_safe_dest_refuses_hardlinked_constraints_document(self):
        """A hardlinked constraints document is refused like a symlinked one:
        the same shared-inode write-through applies to every _safe_dest caller."""

        repo = self.seeded_repo()
        doc = repo / ".agents/project-harness/constraints/custom-rule.md"
        doc.write_text("# 自定义规则\n\n使用时机：触及本规则的工作前阅读。\n", encoding="utf-8")
        outside = self.temp_dir("ph-gov-outside-") / "outside-rule.md"
        os.link(doc, outside)
        with self.assertRaises(ph_governance.PHGovernanceError) as ctx:
            ph_governance._safe_dest(repo, ".agents/project-harness/constraints/custom-rule.md")
        self.assertIn("hardlink", str(ctx.exception))
        self.assertEqual(outside.read_bytes(), doc.read_bytes())

    def test_navigation_links_resolve_from_the_materialized_depth(self):
        """Every navigation entry is a repo-home-relative link, so it must
        resolve to a live document when read from the materialized
        constitution's own directory (the retired spec-kit test resolved each
        link; this keeps that responsibility after its retirement)."""

        repo = self.seeded_repo()
        subdir = repo / ".agents/project-harness/constraints/工程规范"
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / "Git与并行开发.md").write_text(
            "# Git与并行开发\n\n使用时机：触碰分支与并行开发约定前阅读。\n", encoding="utf-8"
        )
        proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (repo / ph_governance.CONSTITUTION).read_text(encoding="utf-8")
        entries = list(re.finditer(r"^- \[([^\]]+)\]\(([^)]+)\)\n  使用时机：(.+)$", text, re.MULTILINE))
        self.assertTrue(entries, "navigation zone rendered no entries")
        home = repo / ph_governance.HOME
        for entry in entries:
            target = home / entry.group(2)
            self.assertTrue(target.is_file() or target.is_dir(), f"broken link: {entry.group(2)}")
            self.assertTrue(entry.group(3).strip(), f"empty usage line: {entry.group(2)}")

    def test_readme_description_fallback_feeds_the_usage_line(self):
        """A constraints document without a body usage line takes its
        使用时机 from the directory README index: the indexed-heading form and
        the plain list-line form (extract_readme_description)."""

        for shape in ("heading", "list"):
            with self.subTest(shape=shape):
                repo = self.seeded_repo()
                subdir = repo / ".agents/project-harness/constraints/工程规范"
                subdir.mkdir(parents=True, exist_ok=True)
                doc = subdir / "Git与并行开发.md"
                doc.write_text("# Git与并行开发\n\n正文没有使用时机。\n", encoding="utf-8")
                if shape == "heading":
                    (subdir / "README.md").write_text(
                        "## 目录\n\n**Git与并行开发.md**\n分支与并行开发的约束，动手前阅读。\n",
                        encoding="utf-8",
                    )
                else:
                    (subdir / "README.md").write_text(
                        "- [Git与并行开发.md](./Git与并行开发.md)：分支与并行开发的约束\n",
                        encoding="utf-8",
                    )
                proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                text = (repo / ph_governance.CONSTITUTION).read_text(encoding="utf-8")
                row = next(line for line in text.splitlines() if "Git与并行开发.md" in line)
                usage = text.splitlines()[text.splitlines().index(row) + 1]
                self.assertIn("使用时机：分支与并行开发的约束", usage)
                self.assertNotIn("待确认", usage)

    def test_refresh_preserves_principles_and_pending_usage_blocks_verify(self):
        repo = self.seeded_repo()
        dest = repo / ph_governance.CONSTITUTION
        proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        original_text = dest.read_text(encoding="utf-8")
        prefix = original_text.split(ph_governance.NAV_HEADING)[0]
        ok = run_cli("verify", "--repo", str(repo))
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["ok"])

        custom = repo / ".agents/project-harness/constraints/custom-rule.md"
        # strict refresh refuses a constraints file without a verified usage line
        custom.write_text("# 无时机规则\n\n正文没有阅读时机。\n", encoding="utf-8")
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        refused = run_cli("refresh-navigation", "--repo", str(repo), "--expected-sha", sha, "--apply")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("missing usage", refused.stderr)

        # A 待确认 usage refreshes (the gap stays visible) but fails verify.
        custom.write_text("# 自定义规则\n\n使用时机：待确认。\n", encoding="utf-8")
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        proc = run_cli("refresh-navigation", "--repo", str(repo), "--expected-sha", sha, "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(json.loads(proc.stdout)["entries"], 1)
        self.assertIn("自定义规则", dest.read_text(encoding="utf-8"))
        # Principles and the marker-zone header stay byte-identical.
        self.assertTrue(dest.read_text(encoding="utf-8").startswith(prefix))
        pending = run_cli("verify", "--repo", str(repo))
        self.assertEqual(pending.returncode, 2)
        self.assertIn("empty usage line", pending.stdout)

        # Recording the real reading moment clears the problem; the dry run
        # reports the plan without writing.
        custom.write_text("# 自定义规则\n\n使用时机：触及本规则的工作前阅读。\n", encoding="utf-8")
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        before = dest.read_bytes()
        dry = run_cli("refresh-navigation", "--repo", str(repo), "--expected-sha", sha)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(json.loads(dry.stdout)["apply"], False)
        self.assertEqual(dest.read_bytes(), before)
        proc = run_cli("refresh-navigation", "--repo", str(repo), "--expected-sha", sha, "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(run_cli("verify", "--repo", str(repo)).returncode, 0)

    def test_verify_flags_uncovered_constraints_and_drifted_sha(self):
        repo = self.seeded_repo()
        dest = repo / ph_governance.CONSTITUTION
        proc = run_cli("materialize-constitution", "--repo", str(repo), "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        custom = repo / ".agents/project-harness/constraints/custom-rule.md"
        # An uncovered constraints file breaks the exact-coverage contract.
        custom.write_text("# 自定义规则\n\n使用时机：触及本规则的工作前阅读。\n", encoding="utf-8")
        bad = run_cli("verify", "--repo", str(repo))
        self.assertEqual(bad.returncode, 2)
        self.assertIn("does not cover constraints exactly", bad.stdout)
        # A drifted or wrong reviewed sha is refused before anything is written.
        reviewed = hashlib.sha256(dest.read_bytes()).hexdigest()
        drifted = run_cli("refresh-navigation", "--repo", str(repo), "--expected-sha", "0" * 64)
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("changed since review", drifted.stderr)
        wrong = run_cli(
            "refresh-navigation", "--repo", str(repo),
            "--expected-sha", hashlib.sha256(b"not the reviewed bytes").hexdigest(),
        )
        self.assertEqual(wrong.returncode, 2)
        self.assertEqual(hashlib.sha256(dest.read_bytes()).hexdigest(), reviewed)

    def test_refresh_accepts_the_legacy_spec_kit_marker(self):
        repo = self.seeded_repo()
        dest = repo / ph_governance.CONSTITUTION
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = (
            "# 历史宪法\n\n原则正文不可丢失。\n\n"
            f"{ph_governance.LEGACY_MARKER}\n{ph_governance.NAV_HEADING}\n\n"
            f"{ph_governance.EMPTY_NAVIGATION}\n"
        )
        dest.write_text(body, encoding="utf-8")
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        proc = run_cli("refresh-navigation", "--repo", str(repo), "--expected-sha", sha, "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        updated = dest.read_text(encoding="utf-8")
        self.assertIn("原则正文不可丢失。", updated)
        self.assertNotIn(ph_governance.EMPTY_NAVIGATION, updated)
        self.assertEqual(run_cli("verify", "--repo", str(repo)).returncode, 0)

    def test_verify_flags_upstream_placeholders_and_legacy_roots(self):
        repo = self.seeded_repo()
        dest = repo / ph_governance.CONSTITUTION
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            "# [PROJECT_NAME] Constitution\n\n"
            f"{ph_governance.GOVERNANCE_MARKER}\n{ph_governance.NAV_HEADING}\n\n"
            f"{ph_governance.EMPTY_NAVIGATION}\n",
            encoding="utf-8",
        )
        (repo / ".specify").mkdir()
        proc = run_cli("verify", "--repo", str(repo))
        self.assertEqual(proc.returncode, 2)
        problems = json.loads(proc.stdout)["problems"]
        self.assertTrue(any("[PROJECT_NAME]" in p for p in problems), problems)
        self.assertTrue(any(".specify" in p for p in problems), problems)

    def test_verify_content_reports_complete_fixture(self):
        repo = self.seeded_repo()
        proc = run_cli("verify-content", "--repo", str(repo))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
