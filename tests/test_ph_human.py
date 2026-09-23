#!/usr/bin/env python3
"""Unit tests for the shared human-companion script ph_human.py.

Every fixture is a real temporary directory (no Git needed: the script only
needs a repository root directory). Workspaces are moved into ``~/.Trash``
during teardown; nothing is deleted with ``rm``.

Covers the release-critical contract of ``assets/scaffold/.agents/scripts/
ph_human.py``: source/companion mapping (root, nested-flattened, constitution),
machine footer provenance, atomic managed writes that never touch the machine
source, overwrite protection for user-modified or footer-less companions,
staleness/orphan detection, snapshot companions for ph-analyze /
ph-taskstoissues, refusal for missing sources, companion-as-input recursion,
nested naming conflicts, symlink escape safety, and the feature-root-only
status scan that never descends into checklists/ or contracts/.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "assets/scaffold/.agents/scripts/ph_human.py"
TRASH = Path.home() / ".Trash"
FEATURE = ".agents/project-harness/specs/001-demo"


def load_module():
    spec = importlib.util.spec_from_file_location("ph_human_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ph_human = load_module()


class HumanCompanionFixture(unittest.TestCase):
    def setUp(self):
        self.workspaces: list[Path] = []
        self.repo = self.new_dir()
        self.feature_dir = self.repo / FEATURE
        self.feature_dir.mkdir(parents=True)

    def new_dir(self) -> Path:
        workspace = Path(tempfile.mkdtemp(prefix="ph-human-tests-"))
        self.workspaces.append(workspace)
        return workspace

    def tearDown(self):
        for workspace in self.workspaces:
            dest = TRASH / f"ph-human-tests-{os.getpid()}-{workspace.name}"
            if workspace.exists():
                shutil.move(str(workspace), str(dest))

    # -- helpers ------------------------------------------------------------

    def write_machine(self, name: str, text: str) -> Path:
        path = self.feature_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def candidate(self, text: str) -> Path:
        path = self.new_dir() / "candidate.md"
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--repo", str(self.repo)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def publish(self, source: str, text: str, skill: str = "ph-specify") -> subprocess.CompletedProcess:
        return self.run_cli("publish", "--source", source, "--candidate", str(self.candidate(text)), "--skill", skill)

    def publish_snapshot(self, kind: str, text: str, skill: str) -> subprocess.CompletedProcess:
        return self.run_cli(
            "publish-snapshot", "--feature", FEATURE, "--kind", kind,
            "--candidate", str(self.candidate(text)), "--skill", skill,
        )

    def status(self, *extra: str) -> dict:
        proc = self.run_cli("status", *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)


class MappingTests(HumanCompanionFixture):
    NAMES = ("spec.md", "plan.md", "research.md", "data-model.md", "quickstart.md",
             "tasks.md", "verification.md", "requirement.md", "design.md", "review.md",
             "verify-plan.md", "acceptance.md", "change.md")

    def test_root_and_nested_and_constitution_mapping(self):
        for name in self.NAMES:
            self.write_machine(name, f"# {name}\n")
            proc = self.publish(f"{FEATURE}/{name}", f"{name} 伴读正文。\n")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["companion"], f"{FEATURE}/{name[:-3]}-human.md")
            self.assertTrue((self.repo / payload["companion"]).is_file())

        self.write_machine("checklists/requirements.md", "# 清单\n")
        proc = self.publish(f"{FEATURE}/checklists/requirements.md", "清单伴读。\n", skill="ph-checklist")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["companion"], f"{FEATURE}/checklists-requirements-human.md")
        self.assertFalse((self.feature_dir / "checklists").joinpath("requirements-human.md").exists())

        self.write_machine("contracts/carrier.md", "# 契约\n")
        proc = self.publish(f"{FEATURE}/contracts/carrier.md", "契约伴读。\n", skill="ph-plan")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["companion"], f"{FEATURE}/contracts-carrier-human.md")

        constitution = self.repo / ".agents/project-harness/constitution.md"
        constitution.parent.mkdir(parents=True, exist_ok=True)
        constitution.write_text("# 宪法\n", encoding="utf-8")
        proc = self.run_cli("publish", "--source", ".agents/project-harness/constitution.md",
                            "--candidate", str(self.candidate("宪法伴读。\n")), "--skill", "ph-constitution")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["companion"], ".agents/project-harness/constitution-human.md")

    def test_unmapped_and_empty_feature_sources_refused(self):
        self.write_machine("other.md", "# 其他\n")
        proc = self.publish(f"{FEATURE}/other.md", "正文\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unmapped machine source", proc.stderr)

        proc = self.publish(f"{FEATURE}/plan.md", "正文\n", skill="ph-plan")  # mapped but absent
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must be a repository-local regular file", proc.stderr)
        self.assertFalse((self.feature_dir / "plan-human.md").exists())

    def test_companion_is_never_an_input(self):
        self.write_machine("spec.md", "# spec\n")
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "正文\n").returncode, 0)
        proc = self.publish(f"{FEATURE}/spec-human.md", "伴读的伴读\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("refusing to map a companion as a machine source", proc.stderr)
        self.assertFalse((self.feature_dir / "spec-human-human.md").exists())

    def test_nested_naming_conflict_blocks_publish(self):
        # Sibling sources that differ only by case flatten to the same
        # companion name (contracts-api-human.md); on a case-insensitive
        # volume the two sources cannot even coexist, so the scenario is
        # impossible there and the test skips after proving that.
        self.write_machine("contracts/api.md", "# api\n")
        api_file = self.feature_dir / "contracts" / "api.md"
        api_bytes = api_file.read_bytes()
        upper = self.feature_dir / "contracts" / "API.md"
        upper.write_text("# api upper\n", encoding="utf-8")
        if api_file.read_bytes() != api_bytes:
            # case-insensitive volume: writing API.md replaced api.md, so two
            # distinct sources cannot exist and no conflict is possible.
            self.skipTest("case-insensitive filesystem: case-variant siblings cannot coexist")
        proc = self.publish(f"{FEATURE}/contracts/api.md", "正文\n", skill="ph-plan")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("nested naming conflict", proc.stderr)
        self.assertFalse((self.feature_dir / "contracts-api-human.md").exists())

    def test_case_fold_collision_between_checklists_blocks(self):
        self.write_machine("checklists/UX.md", "# ux\n")
        ux_file = self.feature_dir / "checklists" / "UX.md"
        ux_bytes = ux_file.read_bytes()
        lower = self.feature_dir / "checklists" / "ux.md"
        lower.write_text("# ux lower\n", encoding="utf-8")
        if ux_file.read_bytes() != ux_bytes:
            self.skipTest("case-insensitive filesystem: case-variant siblings cannot coexist")
        proc = self.publish(f"{FEATURE}/checklists/ux.md", "正文\n", skill="ph-checklist")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("nested naming conflict", proc.stderr)

    def test_symlinked_source_and_escaping_paths_refused(self):
        self.write_machine("spec.md", "# spec\n")
        outside = self.new_dir() / "outside.md"
        outside.write_text("# outside\n", encoding="utf-8")
        link = self.feature_dir / "plan.md"
        link.symlink_to(outside)
        proc = self.publish(f"{FEATURE}/plan.md", "正文\n", skill="ph-plan")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("symlink", proc.stderr)

        for bad in ("../escape.md", "/abs.md", "~/home.md"):
            proc = self.run_cli("publish", "--source", bad, "--candidate", str(self.candidate("x\n")))
            self.assertEqual(proc.returncode, 2, bad)


class PublishProtectionTests(HumanCompanionFixture):
    def test_publish_never_modifies_the_machine_source(self):
        self.write_machine("spec.md", "# 规格原文\nFR-1 内容。\n")
        before = (self.feature_dir / "spec.md").read_bytes()
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "伴读正文。\n").returncode, 0)
        self.assertEqual((self.feature_dir / "spec.md").read_bytes(), before)

    def test_footer_records_provenance_and_source_hash(self):
        self.write_machine("spec.md", "# 规格原文\n")
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "伴读正文。\n").returncode, 0)
        companion = self.feature_dir / "spec-human.md"
        parsed = ph_human.parse_companion(companion.read_bytes())
        self.assertIsNotNone(parsed)
        body, meta = parsed
        self.assertEqual(meta["kind"], "artifact")
        self.assertEqual(meta["skill"], "ph-specify")
        self.assertEqual(meta["source"], f"{FEATURE}/spec.md")
        self.assertEqual(meta["source_sha256"],
                         hashlib.sha256((self.feature_dir / "spec.md").read_bytes()).hexdigest())
        self.assertTrue(ph_human.is_hex64(meta["body_sha256"]))
        self.assertTrue(body.startswith("伴读正文。\n"))

    def test_duplicate_generation_replaces_managed_output(self):
        self.write_machine("spec.md", "# 规格原文\n")
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "第一版伴读。\n").returncode, 0)
        proc = self.publish(f"{FEATURE}/spec.md", "第二版伴读。\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (self.feature_dir / "spec-human.md").read_text(encoding="utf-8")
        self.assertIn("第二版伴读。", text)
        self.assertNotIn("第一版伴读。", text)

    def test_user_modified_companion_blocks_republish(self):
        self.write_machine("spec.md", "# 规格原文\n")
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "伴读正文。\n").returncode, 0)
        companion = self.feature_dir / "spec-human.md"
        companion.write_text("用户重写的伴读\n", encoding="utf-8")  # footer gone = user content
        proc = self.publish(f"{FEATURE}/spec.md", "新版伴读。\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("user content", proc.stderr)
        self.assertEqual(companion.read_text(encoding="utf-8"), "用户重写的伴读\n")

        # body edited but footer kept intact: still a user modification
        shutil.move(str(companion), str(TRASH / f"ph-human-user-companion-{os.getpid()}"))
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "伴读正文。\n").returncode, 0)
        text = companion.read_text(encoding="utf-8")
        companion.write_text(text.replace("伴读正文", "用户改过的正文"), encoding="utf-8")
        proc = self.publish(f"{FEATURE}/spec.md", "再新版。\n")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no longer matches the recorded body hash", proc.stderr)

    def test_candidate_must_be_plain_prose(self):
        self.write_machine("spec.md", "# 规格原文\n")
        for bad_text in ("", "   \n", f"正文\n{ph_human.FOOTER_BEGIN}\nsource: x\n"):
            path = self.candidate(bad_text)
            proc = self.run_cli("publish", "--source", f"{FEATURE}/spec.md",
                                 "--candidate", str(path), "--skill", "ph-specify")
            self.assertEqual(proc.returncode, 2, bad_text[:20])
        dir_candidate = self.new_dir()
        proc = self.run_cli("publish", "--source", f"{FEATURE}/spec.md",
                            "--candidate", str(dir_candidate), "--skill", "ph-specify")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.feature_dir / "spec-human.md").exists())


class StatusTests(HumanCompanionFixture):
    def test_fresh_stale_orphan_user_modified_snapshot_states(self):
        self.write_machine("spec.md", "# 规格原文\n")
        self.write_machine("tasks.md", "# 任务\n")
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "spec 伴读\n").returncode, 0)
        self.assertEqual(self.publish(f"{FEATURE}/tasks.md", "tasks 伴读\n", skill="ph-tasks").returncode, 0)
        self.assertEqual(self.publish_snapshot("analysis", "## 本次真实报告\n", "ph-analyze").returncode, 0)

        report = self.status("--feature", FEATURE)
        states = {c["companion"].rsplit("/", 1)[-1]: c["state"] for c in report["features"][0]["companions"]}
        self.assertEqual(states["spec-human.md"], "fresh")
        self.assertEqual(states["tasks-human.md"], "fresh")
        self.assertEqual(states["analysis-human.md"], "snapshot")
        # root machine files without companions are reported missing only
        self.assertNotIn("analysis.md", str(report["features"][0]["missing"]))

        self.write_machine("spec.md", "# 规格原文\n\nFR-2 新增。\n")
        report = self.status("--feature", FEATURE)
        states = {c["companion"].rsplit("/", 1)[-1]: c["state"] for c in report["features"][0]["companions"]}
        self.assertEqual(states["spec-human.md"], "stale")

        (self.feature_dir / "tasks.md").unlink()
        report = self.status("--feature", FEATURE)
        states = {c["companion"].rsplit("/", 1)[-1]: c["state"] for c in report["features"][0]["companions"]}
        self.assertEqual(states["tasks-human.md"], "orphan")

        companion = self.feature_dir / "spec-human.md"
        companion.write_text(companion.read_text(encoding="utf-8").replace("spec 伴读", "用户改的"), encoding="utf-8")
        report = self.status("--feature", FEATURE)
        states = {c["companion"].rsplit("/", 1)[-1]: c["state"] for c in report["features"][0]["companions"]}
        self.assertEqual(states["spec-human.md"], "user_modified")

    def test_scan_isolation_never_descends_into_nested_dirs(self):
        # A stray "-human" file inside checklists/ and contracts/ is project
        # content the status scan must not read, and companions placed inside
        # the nested dirs are not part of the managed set.
        self.write_machine("checklists/requirements.md", "# 清单\n")
        self.write_machine("checklists/stray-human.md", "# 用户文件\n")
        self.assertEqual(
            self.publish(f"{FEATURE}/checklists/requirements.md", "清单伴读\n", skill="ph-checklist").returncode, 0
        )
        report = self.status("--feature", FEATURE)
        names = [c["companion"] for c in report["features"][0]["companions"]]
        self.assertEqual(names, [f"{FEATURE}/checklists-requirements-human.md"])
        # nested files were never listed, hashed, or rewritten
        self.assertEqual((self.feature_dir / "checklists/stray-human.md").read_text(encoding="utf-8"), "# 用户文件\n")
        self.assertEqual((self.feature_dir / "checklists/requirements.md").read_text(encoding="utf-8"), "# 清单\n")

    def test_status_all_covers_features_and_constitution(self):
        self.write_machine("spec.md", "# spec\n")
        self.assertEqual(self.publish(f"{FEATURE}/spec.md", "spec 伴读\n").returncode, 0)
        other = self.repo / ".agents/project-harness/specs/002-other"
        other.mkdir(parents=True)
        (other / "spec.md").write_text("# spec2\n", encoding="utf-8")
        constitution = self.repo / ".agents/project-harness/constitution.md"
        constitution.write_text("# 宪法\n", encoding="utf-8")
        self.assertEqual(
            self.run_cli("publish", "--source", ".agents/project-harness/constitution.md",
                         "--candidate", str(self.candidate("宪法伴读\n")), "--skill", "ph-constitution").returncode, 0
        )
        report = self.status("--all")
        features = {f["feature"]: f for f in report["features"]}
        self.assertEqual(set(features), {FEATURE, ".agents/project-harness/specs/002-other", ".agents/project-harness"})
        self.assertEqual(features[FEATURE]["missing"], [])
        self.assertEqual(features[".agents/project-harness/specs/002-other"]["missing"],
                         [".agents/project-harness/specs/002-other/spec.md"])
        self.assertEqual([c["state"] for c in features[".agents/project-harness"]["companions"]], ["fresh"])

    def test_status_requires_exactly_one_scope(self):
        proc = self.run_cli("status")
        self.assertEqual(proc.returncode, 2)
        proc = self.run_cli("status", "--feature", FEATURE, "--all")
        self.assertEqual(proc.returncode, 2)
        proc = self.run_cli("status", "--feature", ".agents/project-harness/specs/missing-dir")
        self.assertEqual(proc.returncode, 2)

    def test_status_reports_footerless_files_as_unreadable(self):
        (self.feature_dir / "plan-human.md").write_text("用户自建文件\n", encoding="utf-8")
        report = self.status("--feature", FEATURE)
        entry = report["features"][0]["companions"][0]
        self.assertEqual(entry["state"], "unreadable")
        self.assertIn("user content", entry["reason"])


class SnapshotTests(HumanCompanionFixture):
    def test_analysis_and_issues_snapshots(self):
        proc = self.publish_snapshot("analysis", "## 分析报告\n本次真实结论。\n", "ph-analyze")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["companion"], f"{FEATURE}/analysis-human.md")
        parsed = ph_human.parse_companion((self.feature_dir / "analysis-human.md").read_bytes())
        body, meta = parsed
        self.assertEqual(meta["kind"], "analysis")
        self.assertEqual(meta["source"], "@invocation")
        self.assertEqual(meta["source_sha256"], "-")
        self.assertEqual(meta["skill"], "ph-analyze")

        proc = self.publish_snapshot("issues", "## Issue 结果\n- #12 任务\n", "ph-taskstoissues")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["companion"], f"{FEATURE}/issues-human.md")

        # snapshots are replaceable managed output while unmodified
        self.assertEqual(self.publish_snapshot("analysis", "## 新一次报告\n", "ph-analyze").returncode, 0)

    def test_snapshot_feature_must_be_real_dir(self):
        proc = self.run_cli("publish-snapshot", "--feature", ".agents/project-harness/specs/nope",
                            "--kind", "analysis", "--candidate", str(self.candidate("x\n")), "--skill", "ph-analyze")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("repository-local real directory", proc.stderr)


class ModuleContractTests(unittest.TestCase):
    def test_footer_schema_fields_are_pinned(self):
        self.assertEqual(ph_human.FOOTER_SCHEMA, "ph-human-companion/1")
        self.assertEqual(
            ph_human.ROOT_MACHINE_NAMES,
            ("spec", "plan", "research", "data-model", "quickstart", "tasks", "verification",
             "requirement", "design", "review", "verify-plan", "acceptance", "change"),
        )
        self.assertEqual(ph_human.NESTED_SOURCE_DIRS, ("checklists", "contracts"))
        self.assertEqual(ph_human.SNAPSHOT_KINDS, {"analysis": "analysis-human.md", "issues": "issues-human.md"})

    def test_script_travels_in_scaffold(self):
        # Skill bodies (SKILL.md / references / evals) are owned by the skill
        # authoring effort and are deliberately not asserted here.
        self.assertTrue((REPO_ROOT / "assets/scaffold/.agents/scripts/ph_human.py").is_file())


if __name__ == "__main__":
    unittest.main()
