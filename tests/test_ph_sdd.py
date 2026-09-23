#!/usr/bin/env python3
"""Unit tests for the self-built SDD runtime script ph_sdd.py.

Every fixture is a real temporary directory (no Git needed: the script never
runs git). Workspaces are moved into ``~/.Trash`` during teardown; nothing is
deleted with ``rm``.

Covers the release-critical contract of ``assets/scaffold/.agents/scripts/
ph_sdd.py``: stable feature directories under specs/, the full/small/legacy
artifact mapping, explicit --repo/--feature addressing, dry-run default with
--apply, idempotent marks, path-escape and symlink refusal, write protection
for managed metadata, the review-before-tasks gate (requirement AND design
reviewed, design review bound to review.md and the requirement fingerprint),
drift blocking instead of fake-pass, the archive-readiness gate (tasks done,
acceptance/verification passed or explicitly not_applicable with a reason),
legacy adoption via ``adopt`` that never edits original files nor guesses
states from checkboxes, and the append-only archive (read-only snapshots +
stable index, no git/merge/worktree actions).
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
SCRIPT = REPO_ROOT / "assets/scaffold/.agents/scripts/ph_sdd.py"
TRASH = Path.home() / ".Trash"
FEATURE = "001-demo"
FEATURE_REL = f".agents/project-harness/specs/{FEATURE}"
ARCHIVE_ROOT = ".agents/project-harness/archive/features"


def load_module():
    spec = importlib.util.spec_from_file_location("ph_sdd_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ph_sdd = load_module()


class SddFixture(unittest.TestCase):
    def setUp(self):
        self.workspaces: list[Path] = []
        self.repo = self.new_dir()
        self.specs = self.repo / ".agents/project-harness/specs"
        self.specs.mkdir(parents=True)
        self.feature_dir = self.specs / FEATURE

    def new_dir(self) -> Path:
        workspace = Path(tempfile.mkdtemp(prefix="ph-sdd-tests-"))
        self.workspaces.append(workspace)
        return workspace

    def tearDown(self):
        for workspace in self.workspaces:
            dest = TRASH / f"ph-sdd-tests-{os.getpid()}-{workspace.name}"
            if workspace.exists():
                shutil.move(str(workspace), str(dest))

    # -- helpers ------------------------------------------------------------

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--repo", str(self.repo)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def create(self, flow: str = "full", title: str = "演示功能", apply: bool = True, feature: str = FEATURE):
        args = ["create", "--feature", feature, "--flow", flow, "--title", title]
        if apply:
            args.append("--apply")
        return self.run_cli(*args)

    def mark(self, artifact: str, status: str, note: str | None = None, evidence: str | None = None,
             apply: bool = True, feature: str = FEATURE):
        args = ["mark", "--feature", feature, "--artifact", artifact, "--status", status]
        if note is not None:
            args += ["--note", note]
        if evidence is not None:
            args += ["--evidence", evidence]
        if apply:
            args.append("--apply")
        return self.run_cli(*args)

    def check(self, feature: str = FEATURE):
        return self.run_cli("check", "--feature", feature)

    def status(self, *extra: str):
        return self.run_cli("status", *extra)

    def adopt(self, feature: str, apply: bool = True):
        args = ["adopt", "--feature", feature]
        if apply:
            args.append("--apply")
        return self.run_cli(*args)

    def archive(self, note: str = "验收通过，用户决定归档", evidence: str | None = None, apply: bool = True,
                feature: str = FEATURE):
        args = ["archive", "--feature", feature, "--note", note]
        if evidence is not None:
            args += ["--evidence", evidence]
        if apply:
            args.append("--apply")
        return self.run_cli(*args)

    def write_artifact(self, name: str, text: str, feature: str = FEATURE) -> Path:
        base = self.specs / feature
        path = base / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def metadata(self, feature: str = FEATURE) -> dict:
        return json.loads((self.specs / feature / "ph-feature.json").read_text(encoding="utf-8"))

    def write_evidence(self, text: str = "测试通过的真实输出\n") -> Path:
        path = self.repo / "evidence" / "run.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def payload(self, proc: subprocess.CompletedProcess) -> dict:
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def review_chain(self, feature: str = FEATURE, drift: bool = False):
        """Bring a full-flow feature through the review chain up to tasks."""
        if not (self.specs / feature / "ph-feature.json").exists():
            self.assertEqual(self.create(feature=feature).returncode, 0)
        self.write_artifact("requirement", "# 需求\nFR-1 登录。\n", feature)
        self.assertEqual(self.mark("requirement", "reviewed", note="用户确认需求", feature=feature).returncode, 0)
        if drift:
            self.write_artifact("requirement", "# 需求\nFR-1 登录。\nFR-2 追加。\n", feature)
        self.write_artifact("design", "# 设计\n采用会话令牌。\n", feature)
        self.write_artifact("review", "# 设计评审\n结论：通过。\n", feature)
        proc = self.mark("design", "reviewed", note="评审通过", feature=feature)
        if drift:
            self.assertEqual(proc.returncode, 2, "需求漂移后设计评审必须被阻断")
            return False
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return True


class ModuleContractTests(unittest.TestCase):
    def test_flows_and_statuses_are_pinned(self):
        self.assertEqual(ph_sdd.FLOWS, {
            "full": ("requirement", "design", "review", "tasks", "verify-plan", "acceptance", "verification"),
            "small": ("change", "tasks", "verify-plan", "acceptance", "verification"),
        })
        self.assertEqual(ph_sdd.STATUSES, {
            "requirement": ("draft", "reviewed"),
            "change": ("draft", "reviewed"),
            "design": ("draft", "reviewed"),
            "review": ("draft", "reviewed"),
            "verify-plan": ("draft", "reviewed"),
            "tasks": ("draft", "done", "not_applicable"),
            "acceptance": ("draft", "passed", "not_applicable"),
            "verification": ("draft", "passed", "not_applicable"),
        })

    def test_roots_and_schemas_are_pinned(self):
        self.assertEqual(ph_sdd.SPECS_ROOT, ".agents/project-harness/specs")
        self.assertEqual(ph_sdd.ARCHIVE_ROOT, ".agents/project-harness/archive/features")
        self.assertEqual(ph_sdd.METADATA_NAME, "ph-feature.json")
        self.assertEqual(ph_sdd.METADATA_SCHEMA, "ph-feature/1")
        self.assertEqual(ph_sdd.ARCHIVE_INDEX_SCHEMA, "ph-archive-index/1")
        self.assertEqual(ph_sdd.ARCHIVE_JOURNAL_SCHEMA, "ph-archive-journal/1")
        self.assertEqual(ph_sdd.ARCHIVE_EVIDENCE_SCHEMA, "ph-evidence-manifest/1")
        self.assertEqual(ph_sdd.EVIDENCE_DIR, "_evidence")
        self.assertEqual(ph_sdd.SDD_LOCK_NAME, ".sdd.lock")
        self.assertEqual(ph_sdd.LEGACY_POINTER, ".agents/project-harness/runtime/feature.json")

    def test_basis_upstreams_and_ranks_are_pinned(self):
        self.assertEqual(ph_sdd.basis_upstreams("full", "design"), ("requirement", "review"))
        self.assertEqual(ph_sdd.basis_upstreams("full", "tasks"), ("requirement", "design"))
        self.assertEqual(ph_sdd.basis_upstreams("small", "tasks"), ("change",))
        self.assertEqual(ph_sdd.basis_upstreams("full", "verification"),
                         ("requirement", "design", "tasks", "verify-plan"))
        self.assertEqual(ph_sdd.basis_upstreams("full", "acceptance"), ("requirement", "verification"))
        self.assertEqual(ph_sdd.basis_upstreams("small", "acceptance"), ("change", "verification"))
        # no downstream record binds acceptance: no loop
        for flow in ph_sdd.FLOWS:
            for artifact in ph_sdd.FLOWS[flow]:
                self.assertNotIn("acceptance", ph_sdd.basis_upstreams(flow, artifact))
        ranks = ph_sdd.ARTIFACT_RANK
        self.assertLess(ranks["full"]["requirement"], ranks["full"]["design"])
        self.assertLess(ranks["full"]["verification"], ranks["full"]["acceptance"])

    def test_script_and_templates_travel_in_scaffold(self):
        self.assertTrue(SCRIPT.is_file())
        expected = ph_sdd.FLOWS["full"] + ("change",)
        self.assertEqual(sorted(expected),
                         sorted({"requirement", "change", "design", "review", "tasks",
                                 "verify-plan", "acceptance", "verification"}))
        for name in expected:
            path = REPO_ROOT / f"assets/scaffold/.agents/project-harness/runtime/templates/sdd/{name}-template.md"
            self.assertTrue(path.is_file(), path.name)
            self.assertTrue(path.read_text(encoding="utf-8").strip(), path.name)
        self.assertTrue((REPO_ROOT / "assets/scaffold/.agents/project-harness/runtime/README.md").is_file())


class CreateTests(SddFixture):
    def test_dry_run_is_the_default_and_writes_nothing(self):
        proc = self.create(apply=False)
        payload = self.payload(proc)
        self.assertTrue(payload["dry_run"])
        self.assertFalse(self.feature_dir.exists())

    def test_apply_creates_metadata_only(self):
        payload = self.payload(self.create())
        self.assertEqual(payload["feature_rel"], FEATURE_REL)
        meta = self.metadata()
        self.assertEqual(meta["schema"], "ph-feature/1")
        self.assertEqual(meta["id"], FEATURE)
        self.assertEqual(meta["flow"], "full")
        self.assertEqual(meta["title"], "演示功能")
        self.assertEqual(meta["artifacts"], {})
        self.assertEqual(meta["archive"], [])
        self.assertEqual(sorted(p.name for p in self.feature_dir.iterdir()), ["ph-feature.json"])

    def test_existing_feature_refused(self):
        self.assertEqual(self.create().returncode, 0)
        proc = self.create()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("已存在", proc.stderr)
        # a dry-run over an existing feature stays informative, not fatal
        proc = self.create(apply=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_feature_id_validation(self):
        for bad in ("demo", "001-", "001-UPPER", "../escape", "/abs", "a/b", "001--x"):
            proc = self.create(feature=bad)
            self.assertEqual(proc.returncode, 2, bad)
        self.assertFalse((self.specs / "demo").exists())

    def test_flow_choice_is_validated(self):
        proc = self.run_cli("create", "--feature", FEATURE, "--flow", "legacy", "--title", "x", "--apply")
        self.assertEqual(proc.returncode, 2)

    def test_legacy_directory_refused_with_adopt_hint(self):
        self.feature_dir.mkdir()
        (self.feature_dir / "spec.md").write_text("# 旧规格\n", encoding="utf-8")
        proc = self.create()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("adopt", proc.stderr)
        self.assertFalse((self.feature_dir / "ph-feature.json").exists())

    def test_nonempty_directory_refused(self):
        self.feature_dir.mkdir()
        (self.feature_dir / "notes.txt").write_text("用户文件\n", encoding="utf-8")
        proc = self.create()
        self.assertEqual(proc.returncode, 2)


class MarkTests(SddFixture):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.create().returncode, 0)

    def test_dry_run_is_the_default(self):
        self.write_artifact("requirement", "# 需求\nFR-1 登录。\n")
        proc = self.mark("requirement", "reviewed", note="用户已确认", apply=False)
        payload = self.payload(proc)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(self.metadata()["artifacts"], {})

    def test_non_draft_requires_explicit_note_or_evidence(self):
        self.write_artifact("requirement", "# 需求\n")
        proc = self.mark("requirement", "reviewed")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("note", proc.stderr)
        self.assertEqual(self.metadata()["artifacts"], {})

    def test_apply_records_status_fingerprint_note_and_evidence(self):
        req = self.write_artifact("requirement", "# 需求\nFR-1 登录。\n")
        ev = self.write_evidence()
        proc = self.mark("requirement", "reviewed", note="用户已确认", evidence=str(ev))
        payload = self.payload(proc)
        self.assertFalse(payload["dry_run"])
        record = self.metadata()["artifacts"]["requirement"]
        self.assertEqual(record["status"], "reviewed")
        self.assertEqual(record["note"], "用户已确认")
        self.assertEqual(record["evidence"]["sha256"], hashlib.sha256(ev.read_bytes()).hexdigest())
        self.assertEqual(record["evidence"]["bytes"], ev.stat().st_size)
        self.assertEqual(record["fingerprint"], hashlib.sha256(req.read_bytes()).hexdigest())
        self.assertEqual(record["history"][-1]["status"], "reviewed")

    def test_same_mark_is_idempotent(self):
        self.write_artifact("requirement", "# 需求\n")
        self.assertEqual(self.mark("requirement", "reviewed", note="确认").returncode, 0)
        before = self.metadata()["updated"]
        proc = self.mark("requirement", "reviewed", note="确认")
        payload = self.payload(proc)
        self.assertTrue(payload["unchanged"])
        self.assertEqual(self.metadata()["updated"], before)

    def test_reconfirm_after_drift_updates_fingerprint_with_explicit_input(self):
        self.write_artifact("requirement", "# 需求\nFR-1\n")
        self.assertEqual(self.mark("requirement", "reviewed", note="确认").returncode, 0)
        self.write_artifact("requirement", "# 需求\nFR-1\nFR-2\n")
        proc = self.mark("requirement", "reviewed")  # same status but drifted content
        self.assertEqual(proc.returncode, 2)
        proc = self.mark("requirement", "reviewed", note="复审通过")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        record = self.metadata()["artifacts"]["requirement"]
        self.assertEqual(record["note"], "复审通过")
        self.assertEqual(record["fingerprint"],
                         hashlib.sha256((self.feature_dir / "requirement.md").read_bytes()).hexdigest())

    def test_full_review_chain_gates_tasks(self):
        # tasks cannot be marked until requirement AND design are reviewed
        self.write_artifact("tasks", "# 任务\n- [ ] T1 实现 FR-1\n")
        proc = self.mark("tasks", "done", note="完成")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("review", proc.stderr)

        self.write_artifact("requirement", "# 需求\nFR-1\n")
        self.assertEqual(self.mark("requirement", "reviewed", note="确认").returncode, 0)
        self.write_artifact("design", "# 设计\n方案。\n")
        proc = self.mark("design", "reviewed", note="确认")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("review.md", proc.stderr)  # design review needs the review artifact

        self.write_artifact("review", "# 设计评审\n结论：通过。\n")
        self.assertEqual(self.mark("design", "reviewed", note="确认").returncode, 0)
        record = self.metadata()["artifacts"]["design"]
        self.assertEqual(record["basis"], {
            "requirement": self.metadata()["artifacts"]["requirement"]["fingerprint"],
            "review": hashlib.sha256((self.feature_dir / "review.md").read_bytes()).hexdigest(),
        })
        proc = self.mark("tasks", "done", note="完成", evidence=str(self.write_evidence()))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tasks_record = self.metadata()["artifacts"]["tasks"]
        self.assertEqual(tasks_record["basis"]["requirement"],
                         self.metadata()["artifacts"]["requirement"]["fingerprint"])
        self.assertEqual(tasks_record["basis"]["design"],
                         self.metadata()["artifacts"]["design"]["fingerprint"])

    def test_downstream_basis_stales_after_upstream_remark_and_recovers(self):
        # A requirement re-review must not leave the old downstream
        # done/passed records valid: they go 待复核, archive is refused, and
        # re-marking the chain in dependency order restores everything.
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verify-plan", "# 验证计划\nVP-1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.write_artifact("acceptance", "# 验收\nAC-1\n")
        self.assertEqual(self.mark("tasks", "done", note="完成").returncode, 0)
        self.assertEqual(self.mark("verification", "passed", note="验证完成").returncode, 0)
        self.assertEqual(self.mark("acceptance", "passed", note="用户验收").returncode, 0)

        # the requirement changes and is re-confirmed
        self.write_artifact("requirement", "# 需求\nFR-1\nFR-2 追加。\n")
        self.assertEqual(self.mark("requirement", "reviewed", note="复审通过").returncode, 0)
        proc = self.check()
        self.assertEqual(proc.returncode, 2)
        text = json.dumps(json.loads(proc.stdout), ensure_ascii=False)
        self.assertIn("待复核", text)
        proc = self.archive()
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.repo / ARCHIVE_ROOT / FEATURE).exists())

        # re-mark the chain in dependency order; each upstream re-mark stales
        # its downstream, and marking an upstream is never blocked by them
        for artifact, status, note in (("design", "reviewed", "复审设计"),
                                       ("tasks", "done", "复核任务"),
                                       ("verify-plan", "reviewed", "复核计划"),
                                       ("verification", "passed", "复验完成"),
                                       ("acceptance", "passed", "重新验收")):
            proc = self.mark(artifact, status, note=note)
            self.assertEqual(proc.returncode, 0, f"{artifact}: {proc.stderr}")
        proc = self.archive()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("snapshot", json.loads(proc.stdout))

    def test_acceptance_binds_verification_evidence_identity(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verify-plan", "# 计划\nVP-1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.write_artifact("acceptance", "# 验收\nAC-1\n")
        ev = self.write_evidence()
        self.assertEqual(self.mark("tasks", "done", note="完成").returncode, 0)
        self.assertEqual(self.mark("verification", "passed", note="验证", evidence=str(ev)).returncode, 0)
        self.assertEqual(self.mark("acceptance", "passed", note="用户验收").returncode, 0)
        bound = self.metadata()["artifacts"]["acceptance"]["verification_evidence"]
        self.assertEqual(bound["sha256"], hashlib.sha256(ev.read_bytes()).hexdigest())

        # verification is re-marked against NEW evidence: the acceptance
        # record no longer refers to the verified result and must go stale
        ev2 = self.write_evidence("第二次验证输出\n")
        proc = self.mark("verification", "passed", note="重新验证", evidence=str(ev2))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.archive()
        self.assertEqual(proc.returncode, 2)
        proc = self.mark("acceptance", "passed", note="重新验收")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.archive().returncode, 0)

    def test_requirement_drift_blocks_downstream_completion_marks(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.assertEqual(self.mark("tasks", "done", note="完成").returncode, 0)
        # now the requirement drifts: downstream completion marks are blocked
        self.write_artifact("requirement", "# 需求\nFR-1\nFR-2\n")
        self.write_artifact("verify-plan", "# 计划\nVP-1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        proc = self.mark("verification", "passed", note="验证完成")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("待复核", proc.stderr)

    def test_small_flow_replaces_requirement_and_design_with_change(self):
        self.assertEqual(self.create(flow="small", title="小改动", feature="002-small").returncode, 0)
        for artifact in ("requirement", "design", "review"):
            proc = self.mark(artifact, "reviewed", note="确认", feature="002-small")
            self.assertEqual(proc.returncode, 2, artifact)
            self.assertIn("small", proc.stderr)
        self.write_artifact("change", "# 变更\nFR-1\n", feature="002-small")
        self.assertEqual(self.mark("change", "reviewed", note="确认", feature="002-small").returncode, 0)
        self.write_artifact("tasks", "# 任务\nT1\n", feature="002-small")
        self.assertEqual(self.mark("tasks", "done", note="完成", feature="002-small").returncode, 0)

    def test_not_applicable_requires_reason_note(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.write_artifact("acceptance", "# 验收\nAC-1\n")
        proc = self.mark("acceptance", "not_applicable")
        self.assertEqual(proc.returncode, 2)
        proc = self.mark("acceptance", "not_applicable", note="内部任务无外部用户，验收不适用")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        record = self.metadata()["artifacts"]["acceptance"]
        self.assertEqual(record["status"], "not_applicable")
        self.assertIn("无外部用户", record["note"])

    def test_artifact_file_must_exist_to_be_marked(self):
        proc = self.mark("design", "reviewed", note="确认")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("不存在", proc.stderr)

    def test_unknown_artifact_and_status_refused(self):
        self.write_artifact("tasks", "# 任务\n")
        for args in (("spec", "reviewed"), ("tasks", "passed"), ("tasks", "bogus")):
            proc = self.mark(*args, note="x")
            self.assertEqual(proc.returncode, 2, str(args))

    def test_evidence_must_be_a_real_file(self):
        self.write_artifact("requirement", "# 需求\n")
        outside = self.new_dir() / "outside.txt"
        outside.write_text("证据\n", encoding="utf-8")
        link = self.repo / "link.txt"
        link.symlink_to(outside)
        for bad in (str(self.repo / "missing.txt"), str(link)):
            proc = self.mark("requirement", "reviewed", note="确认", evidence=bad)
            self.assertEqual(proc.returncode, 2, bad)

    def test_corrupted_metadata_treated_as_user_content(self):
        (self.feature_dir / "ph-feature.json").write_text("不是 json", encoding="utf-8")
        self.write_artifact("requirement", "# 需求\n")
        proc = self.mark("requirement", "reviewed", note="确认")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("用户内容", proc.stderr)


class CheckTests(SddFixture):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.create().returncode, 0)

    def test_fully_gated_feature_passes(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\n- [ ] T1 实现 FR-1\n")
        self.assertEqual(self.mark("tasks", "done", note="完成").returncode, 0)
        self.write_artifact("verify-plan", "# 验证计划\nVP-1\n")
        self.write_artifact("acceptance", "# 验收\nAC-1 登录成功。\n")
        self.write_artifact("verification", "# 验证\nVP-1 已执行，AC-1 通过。\n")
        self.assertEqual(self.mark("verification", "passed", note="验证记录完成").returncode, 0)
        self.assertEqual(self.mark("acceptance", "passed", note="用户验收通过").returncode, 0)
        proc = self.check()
        payload = self.payload(proc)
        self.assertEqual(payload["result"], "ok")
        self.assertEqual(proc.returncode, 0)

    def test_ac_defined_at_requirement_time_resolves(self):
        # the user's acceptance criteria are defined in requirement.md before
        # acceptance.md exists: referencing them must not warn
        self.write_artifact("requirement", "# 需求\nFR-1 登录。\nAC-1 登录成功。\n")
        self.assertEqual(self.mark("requirement", "reviewed", note="确认").returncode, 0)
        self.write_artifact("design", "# 设计\n覆盖 FR-1。\n")
        self.write_artifact("review", "# 评审\n通过。\n")
        self.assertEqual(self.mark("design", "reviewed", note="确认").returncode, 0)
        self.write_artifact("tasks", "# 任务\nT1 覆盖 AC-1\n")
        self.assertEqual(self.mark("tasks", "done", note="完成").returncode, 0)
        proc = self.check()
        payload = self.payload(proc)
        self.assertEqual(payload["result"], "ok")
        self.assertEqual(proc.returncode, 0)

    def test_review_before_tasks_gate_blocks(self):
        self.write_artifact("tasks", "# 任务\n- [ ] T1\n")
        proc = self.check()
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["result"], "blocked")
        gates = [e["gate"] for e in payload["errors"]]
        self.assertIn("review-before-tasks", gates)

    def test_drift_blocks_with_needs_review_message(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("requirement", "# 需求\nFR-1\nFR-2 追加。\n")
        proc = self.check()
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["result"], "blocked")
        entry = next(a for a in payload["artifacts"] if a["name"] == "requirement")
        self.assertTrue(entry["drift"])
        self.assertEqual(entry["status"], "reviewed")  # status kept, never auto-revoked
        self.assertIn("待复核", entry["drift_message"])

    def test_undefined_numbered_references_need_review(self):
        self.write_artifact("requirement", "# 需求\nFR-1 登录。\n")
        self.write_artifact("design", "# 设计\n覆盖 FR-1，另及 FR-2。\n")
        proc = self.check()
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["result"], "needs-review")
        text = json.dumps(payload["warnings"], ensure_ascii=False)
        self.assertIn("FR-2", text)

    def test_ac_references_resolve_against_acceptance(self):
        self.write_artifact("verification", "# 验证\nAC-1 已通过。\n")
        proc = self.check()
        self.assertEqual(proc.returncode, 1)  # AC-1 not defined yet
        self.write_artifact("acceptance", "# 验收\nAC-1 登录成功。\n")
        proc = self.check()
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_evidence_drift_blocks(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        ev = self.write_evidence()
        self.assertEqual(self.mark("tasks", "done", note="完成", evidence=str(ev)).returncode, 0)
        ev.write_text("证据被改写\n", encoding="utf-8")
        proc = self.check()
        self.assertEqual(proc.returncode, 2)
        text = json.dumps(json.loads(proc.stdout), ensure_ascii=False)
        self.assertIn("evidence", text)

    def test_review_basis_drift_blocks_tasks_gate(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.assertEqual(self.mark("tasks", "done", note="完成").returncode, 0)
        # requirement is re-confirmed with a new fingerprint: the design review
        # basis is now stale and downstream completion marks are blocked
        self.write_artifact("requirement", "# 需求\nFR-1\nFR-2\n")
        self.assertEqual(self.mark("requirement", "reviewed", note="复审").returncode, 0)
        proc = self.mark("verification", "passed", note="验证")
        self.assertEqual(proc.returncode, 2)
        text = proc.stderr
        self.assertTrue("basis" in text or "待复核" in text, text)

    def test_stray_artifact_from_other_flow_warns(self):
        self.assertEqual(self.create(flow="small", title="小改动", feature="002-small").returncode, 0)
        (self.specs / "002-small" / "requirement.md").write_text("越界产物\n", encoding="utf-8")
        proc = self.check(feature="002-small")
        self.assertEqual(proc.returncode, 1)
        text = json.dumps(json.loads(proc.stdout), ensure_ascii=False)
        self.assertIn("change.md", text)

    def test_missing_feature_and_corrupted_metadata(self):
        proc = self.check(feature="999-none")
        self.assertEqual(proc.returncode, 2)
        (self.feature_dir / "ph-feature.json").write_text("{bad", encoding="utf-8")
        proc = self.check()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("用户内容", proc.stderr)

    def test_empty_new_feature_is_ok(self):
        payload = self.payload(self.check())
        self.assertEqual(payload["result"], "ok")
        self.assertEqual(payload["flow"], "full")


class AdoptTests(SddFixture):
    LEGACY_FILES = {
        "spec.md": "# 旧规格\nFR-1 已有行为。\n",
        "plan.md": "# 旧计划\n沿用现有架构。\n",
        "tasks.md": "# 旧任务\n- [x] T1 旧任务已完成\n",
        "verification.md": "# 旧验证\n历史记录。\n",
        "research.md": "# 旧调研\n仅供参考。\n",
    }

    def make_legacy(self, feature: str = "001-legacy") -> Path:
        d = self.specs / feature
        d.mkdir(parents=True)
        for name, text in self.LEGACY_FILES.items():
            (d / name).write_text(text, encoding="utf-8")
        return d

    def test_dry_run_is_the_default_and_writes_nothing(self):
        self.make_legacy()
        proc = self.adopt("001-legacy", apply=False)
        payload = self.payload(proc)
        self.assertTrue(payload["dry_run"])
        self.assertFalse((self.specs / "001-legacy" / "ph-feature.json").exists())

    def test_apply_maps_legacy_files_without_touching_them(self):
        d = self.make_legacy()
        before = {name: (d / name).read_bytes() for name in self.LEGACY_FILES}
        payload = self.payload(self.adopt("001-legacy"))
        meta = json.loads((d / "ph-feature.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["flow"], "full")
        self.assertEqual(meta["files"], {"requirement": "spec.md", "design": "plan.md"})
        self.assertEqual(meta["artifacts"], {})  # nothing guessed, all pending verification
        self.assertEqual(meta["adopted_from"], {"requirement": "spec.md", "design": "plan.md"})
        self.assertEqual({name: (d / name).read_bytes() for name in self.LEGACY_FILES}, before)
        self.assertFalse((d / "review.md").exists())

    def test_adopted_feature_is_pending_review_and_gated(self):
        self.make_legacy()
        self.assertEqual(self.adopt("001-legacy").returncode, 0)
        report = self.payload(self.run_cli("status", "--feature", "001-legacy"))
        feature = report["features"][0]
        self.assertEqual(feature["flow"], "full")
        states = {a["name"]: a["status"] for a in feature["artifacts"]}
        self.assertEqual(states["requirement"], "unmarked")  # 待核验, never guessed from checkboxes
        self.assertEqual(states["design"], "unmarked")
        self.assertEqual(states["tasks"], "unmarked")
        # the legacy tasks.md on disk triggers the review gate: nothing continues
        proc = self.check(feature="001-legacy")
        self.assertEqual(proc.returncode, 2)
        gates = [e["gate"] for e in json.loads(proc.stdout)["errors"]]
        self.assertIn("review-before-tasks", gates)

    def test_marking_adopted_feature_uses_mapped_file(self):
        self.make_legacy()
        self.assertEqual(self.adopt("001-legacy").returncode, 0)
        d = self.specs / "001-legacy"
        self.assertEqual(self.mark("requirement", "reviewed", note="核验旧规格", feature="001-legacy").returncode, 0)
        record = json.loads((d / "ph-feature.json").read_text(encoding="utf-8"))["artifacts"]["requirement"]
        self.assertEqual(record["fingerprint"], hashlib.sha256((d / "spec.md").read_bytes()).hexdigest())
        # requirement re-check passes, but tasks still need the design review
        self.write_artifact("review", "# 评审\n通过。\n", feature="001-legacy")
        (d / "design.md").write_text("# 新设计\n", encoding="utf-8")  # canonical file now exists
        proc = self.run_cli("mark", "--feature", "001-legacy", "--artifact", "design",
                            "--status", "reviewed", "--note", "确认", "--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_adopt_requires_recognizable_legacy_content(self):
        empty = self.specs / "002-empty"
        empty.mkdir()
        proc = self.adopt("002-empty")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("spec.md", proc.stderr)
        stray = self.specs / "003-stray"
        stray.mkdir()
        (stray / "notes.md").write_text("普通文件\n", encoding="utf-8")
        proc = self.adopt("003-stray")
        self.assertEqual(proc.returncode, 2)

    def test_adopt_refuses_existing_metadata_and_unsafe_names(self):
        self.make_legacy()
        self.assertEqual(self.adopt("001-legacy").returncode, 0)
        proc = self.adopt("001-legacy")
        self.assertEqual(proc.returncode, 2)
        for bad in ("../escape", "a/b", ".hidden"):
            proc = self.adopt(bad)
            self.assertEqual(proc.returncode, 2, bad)

    def test_historical_feature_names_are_allowed(self):
        d = self.specs / "20260101-legacy-auth"
        d.mkdir()
        (d / "spec.md").write_text("# 旧规格\n", encoding="utf-8")
        (d / "plan.md").write_text("# 旧计划\n", encoding="utf-8")
        proc = self.adopt("20260101-legacy-auth")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.metadata("20260101-legacy-auth")["id"], "20260101-legacy-auth")


class StatusTests(SddFixture):
    def test_single_feature_report(self):
        self.assertEqual(self.create().returncode, 0)
        self.write_artifact("requirement", "# 需求\nFR-1\n")
        self.assertEqual(self.mark("requirement", "reviewed", note="确认").returncode, 0)
        self.write_artifact("tasks", "# 任务\n")
        report = self.payload(self.status("--feature", FEATURE))
        feature = report["features"][0]
        self.assertEqual(feature["id"], FEATURE)
        self.assertEqual(feature["flow"], "full")
        states = {a["name"]: a["status"] for a in feature["artifacts"]}
        self.assertEqual(states["requirement"], "reviewed")
        self.assertEqual(states["tasks"], "unmarked")
        self.assertEqual(states["design"], "absent")

    def test_all_lists_features_and_legacy_readonly(self):
        self.assertEqual(self.create().returncode, 0)
        legacy = self.specs / "002-old"
        legacy.mkdir()
        (legacy / "spec.md").write_text("# 旧规格\n", encoding="utf-8")
        (legacy / "plan.md").write_text("# 旧计划\n", encoding="utf-8")
        pointer = self.repo / ".agents/project-harness/runtime/feature.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text('{"feature_directory": ".agents/project-harness/specs/002-old"}\n', encoding="utf-8")
        report = self.payload(self.status("--all"))
        features = {f["id"]: f for f in report["features"]}
        self.assertEqual(features[FEATURE]["flow"], "full")
        self.assertEqual(features["002-old"]["flow"], "legacy")
        self.assertTrue(features["002-old"]["readonly"])
        self.assertIn("spec.md", [a["file"] for a in features["002-old"]["artifacts"]])
        self.assertEqual(report["legacy_pointer"], ".agents/project-harness/specs/002-old")
        # compat read only: nothing was written, not even metadata
        self.assertFalse((legacy / "ph-feature.json").exists())
        self.assertEqual(pointer.read_text(encoding="utf-8"),
                         '{"feature_directory": ".agents/project-harness/specs/002-old"}\n')

    def test_archive_history_visible_in_status(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verify-plan", "# 计划\nVP-1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.write_artifact("acceptance", "# 验收\nAC-1\n")
        for artifact, status, note in (("tasks", "done", "完成"),
                                       ("verification", "passed", "验证"),
                                       ("acceptance", "passed", "验收")):
            self.assertEqual(self.mark(artifact, status, note=note).returncode, 0)
        self.assertEqual(self.archive().returncode, 0)
        report = self.payload(self.status("--feature", FEATURE))
        self.assertEqual(report["features"][0]["archive_count"], 1)

    def test_invalid_metadata_reported_not_crashing(self):
        self.assertEqual(self.create().returncode, 0)
        (self.feature_dir / "ph-feature.json").write_text("{bad", encoding="utf-8")
        report = self.payload(self.status("--feature", FEATURE))
        self.assertEqual(report["features"][0]["metadata_state"], "invalid")


class ArchiveTests(SddFixture):
    def complete_feature(self, feature: str = FEATURE):
        self.assertTrue(self.review_chain(feature=feature))
        self.write_artifact("tasks", "# 任务\nT1\n", feature)
        self.write_artifact("verify-plan", "# 验证计划\nVP-1\n", feature)
        self.write_artifact("acceptance", "# 验收\nAC-1\n", feature)
        self.write_artifact("verification", "# 验证\n完成。\n", feature)
        for artifact, status, note in (("tasks", "done", "完成"),
                                       ("verification", "passed", "验证完成"),
                                       ("acceptance", "passed", "用户验收")):
            self.assertEqual(self.mark(artifact, status, note=note, feature=feature).returncode, 0)

    def test_dry_run_is_the_default(self):
        self.assertEqual(self.create().returncode, 0)
        proc = self.archive(apply=False)
        payload = self.payload(proc)
        self.assertTrue(payload["dry_run"])
        self.assertFalse((self.repo / ARCHIVE_ROOT).exists())

    def test_archive_readiness_gate_blocks_incomplete_feature(self):
        self.assertEqual(self.create().returncode, 0)
        proc = self.archive()
        self.assertEqual(proc.returncode, 2)
        gates = [e["gate"] for e in json.loads(proc.stdout)["errors"]]
        self.assertIn("archive-readiness", gates)

    def test_archive_readiness_accepts_explicit_not_applicable(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verify-plan", "# 计划\nVP-1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.write_artifact("acceptance", "# 验收\nAC-1\n")
        self.assertEqual(self.mark("verification", "passed", note="完成").returncode, 0)
        self.assertEqual(self.mark("acceptance", "not_applicable", note="内部任务无外部用户").returncode, 0)
        self.assertEqual(self.mark("tasks", "done", note="完成").returncode, 0)
        payload = self.payload(self.archive())
        self.assertIn("snapshot", payload)

    def test_apply_snapshots_readonly_with_index(self):
        self.complete_feature()
        ev = self.write_evidence()
        proc = self.archive(note="验收通过，用户决定归档", evidence=str(ev))
        payload = self.payload(proc)
        snapshot_rel = payload["snapshot"]
        snapshot = self.repo / snapshot_rel
        self.assertTrue(snapshot.is_dir())
        self.assertTrue(snapshot_rel.startswith(f"{ARCHIVE_ROOT}/{FEATURE}/"))
        # the whole feature was preserved and is now read-only
        for path in snapshot.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o222, 0, path)
        # external evidence is preserved inside the snapshot with a mapping
        copies = payload["evidence_copies"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["path"], str(ev))
        copied = snapshot / copies[0]["snapshot_path"]
        self.assertTrue(copied.is_file())
        self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(),
                         hashlib.sha256(ev.read_bytes()).hexdigest())
        manifest = json.loads((snapshot / "_evidence" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["copies"], copies)
        # every preserved feature file matches its live twin (except the
        # metadata, which gains the archive history after the copy)
        for path in snapshot.rglob("*"):
            rel = path.relative_to(snapshot)
            if not path.is_file() or rel.parts[0] == "_evidence" or path.name == "ph-feature.json":
                continue
            self.assertEqual(path.read_bytes(), (self.feature_dir / rel).read_bytes(), rel)
        # active feature stays writable and in place
        self.assertTrue((self.feature_dir / "requirement.md").stat().st_mode & 0o222)
        # index entry is append-only and records the explicit decision
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["schema"], "ph-archive-index/1")
        self.assertEqual(len(index["entries"]), 1)
        entry = index["entries"][0]
        self.assertEqual(entry["feature"], FEATURE)
        self.assertEqual(entry["note"], "验收通过，用户决定归档")
        self.assertEqual(entry["evidence"]["sha256"], hashlib.sha256(ev.read_bytes()).hexdigest())
        self.assertEqual(entry["artifact_states"]["tasks"], "done")
        self.assertEqual(entry["artifact_states"]["acceptance"], "passed")
        # active metadata records the archive history
        self.assertEqual(len(self.metadata()["archive"]), 1)

    def test_same_content_is_idempotent(self):
        self.complete_feature()
        self.assertEqual(self.archive().returncode, 0)
        first = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        proc = self.archive()
        payload = self.payload(proc)
        self.assertTrue(payload["unchanged"])
        second = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(first, second)
        self.assertEqual(len(list((self.repo / ARCHIVE_ROOT / FEATURE).iterdir())), 1)

    def test_drift_blocks_archive(self):
        self.complete_feature()
        self.write_artifact("requirement", "# 需求\nFR-1\nFR-2 追加。\n")
        proc = self.archive()
        self.assertEqual(proc.returncode, 2)
        text = json.dumps(json.loads(proc.stdout), ensure_ascii=False)
        self.assertIn("待复核", text)
        self.assertFalse((self.repo / ARCHIVE_ROOT / FEATURE).exists())

    def test_changed_content_creates_a_second_snapshot(self):
        self.complete_feature()
        self.assertEqual(self.archive().returncode, 0)
        # any content edit invalidates the records bound to it; the chain is
        # re-marked in dependency order, then the new content archives again
        self.write_artifact("verify-plan", "# 验证计划\nVP-1\nVP-2 补充。\n")
        for artifact, status, note in (("verify-plan", "reviewed", "复核计划"),
                                       ("verification", "passed", "复验完成")):
            self.assertEqual(self.mark(artifact, status, note=note).returncode, 0)
        self.assertEqual(self.archive().returncode, 0)
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 2)
        self.assertEqual(len(self.metadata()["archive"]), 2)

    def test_legacy_and_unmanaged_features_refused(self):
        legacy = self.specs / "002-old"
        legacy.mkdir()
        (legacy / "spec.md").write_text("# 旧规格\n", encoding="utf-8")
        proc = self.archive(feature="002-old")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("adopt", proc.stderr)

    def test_note_is_required_and_no_git_or_memory_actions(self):
        self.complete_feature()
        proc = self.run_cli("archive", "--feature", FEATURE, "--apply")
        self.assertEqual(proc.returncode, 2)
        git_dir = self.repo / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        memory = self.repo / ".agents/project-harness/memory/temporary"
        memory.mkdir(parents=True)
        (memory / "note.md").write_text("记忆\n", encoding="utf-8")
        before = (git_dir / "HEAD").read_bytes()
        self.assertEqual(self.archive().returncode, 0)
        self.assertEqual((git_dir / "HEAD").read_bytes(), before)
        self.assertEqual((memory / "note.md").read_text(encoding="utf-8"), "记忆\n")


class ArchiveConsistencyTests(SddFixture):
    """Audit regressions D1/D2/D4: gate-before-idempotency ordering, the
    semantic fingerprint, evidence snapshots, and journal recovery."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.create().returncode, 0)

    def complete(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verify-plan", "# 计划\nVP-1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.write_artifact("acceptance", "# 验收\nAC-1\n")
        for artifact, status, note in (("tasks", "done", "完成"),
                                       ("verification", "passed", "验证完成"),
                                       ("acceptance", "passed", "用户验收")):
            self.assertEqual(self.mark(artifact, status, note=note).returncode, 0)

    # D1: a drifted feature is blocked, never "unchanged"
    def test_evidence_drift_blocks_archive_instead_of_unchanged(self):
        self.complete()
        ev = self.write_evidence()
        self.assertEqual(self.mark("verification", "passed", note="复验", evidence=str(ev)).returncode, 0)
        self.assertEqual(self.archive().returncode, 0)
        ev.write_text("证据被改写\n", encoding="utf-8")
        proc = self.archive()  # same note: the old code returned 0/unchanged here
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["result"], "blocked")
        snapshots = list((self.repo / ARCHIVE_ROOT / FEATURE).iterdir()) if (self.repo / ARCHIVE_ROOT / FEATURE).exists() else []
        self.assertEqual(len(snapshots), 1)  # no second snapshot was created

    # D1: semantic metadata changes are a new decision, never silently dropped
    def test_metadata_decision_change_creates_new_snapshot(self):
        self.complete()
        self.assertEqual(self.archive(note="归档").returncode, 0)
        # a note update on a done record changes the semantic fingerprint
        self.assertEqual(self.mark("tasks", "done", note="更新完成说明").returncode, 0)
        proc = self.archive(note="归档")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("unchanged", json.loads(proc.stdout))
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 2)
        self.assertNotEqual(index["entries"][0]["feature_fingerprint"],
                            index["entries"][1]["feature_fingerprint"])

    # D1: idempotency requires the same recorded decision, not just content
    def test_same_content_different_note_is_a_new_decision(self):
        self.complete()
        self.assertEqual(self.archive(note="第一次归档决定").returncode, 0)
        proc = self.archive(note="用户更改归档说明")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("unchanged", json.loads(proc.stdout))
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual([e["note"] for e in index["entries"]], ["第一次归档决定", "用户更改归档说明"])

    # D2: archived proof survives cleanup of the original evidence file
    def test_evidence_snapshot_survives_original_cleanup(self):
        self.complete()
        ev = self.write_evidence()
        self.assertEqual(self.mark("verification", "passed", note="复验", evidence=str(ev)).returncode, 0)
        payload = self.payload(self.archive())
        copies = payload["evidence_copies"]
        self.assertEqual(len(copies), 1)
        snapshot_copy = self.repo / payload["snapshot"] / copies[0]["snapshot_path"]
        # cleanup of the original (moved to the trash, never rm'd)
        shutil.move(str(ev), str(TRASH / f"ph-sdd-ev-{os.getpid()}-{ev.name}"))
        self.assertFalse(ev.exists())
        self.assertEqual(hashlib.sha256(snapshot_copy.read_bytes()).hexdigest(), copies[0]["sha256"])
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["entries"][0]["evidence_copies"], copies)
        # the active feature honestly reports the missing evidence path
        proc = self.check()
        self.assertEqual(proc.returncode, 2)

    # D2: evidence inside the feature is mapped, not duplicated
    def test_feature_internal_evidence_is_mapped_not_duplicated(self):
        self.complete()
        internal = self.feature_dir / "logs" / "run.txt"
        internal.parent.mkdir(parents=True)
        internal.write_text("feature 内证据\n", encoding="utf-8")
        self.assertEqual(self.mark("verification", "passed", note="复验", evidence=str(internal)).returncode, 0)
        payload = self.payload(self.archive())
        copies = payload["evidence_copies"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["snapshot_path"], "logs/run.txt")
        self.assertFalse((self.repo / payload["snapshot"] / "_evidence" / "0001-run.txt").exists())

    # D4: a broken index is a precheck failure - nothing is copied
    def test_broken_index_blocks_before_any_copy(self):
        self.complete()
        archive_root = self.repo / ARCHIVE_ROOT
        archive_root.mkdir(parents=True)
        (archive_root / "index.json").write_text("{bad json", encoding="utf-8")
        proc = self.archive()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("用户内容", proc.stderr)
        self.assertFalse((archive_root / FEATURE).exists())
        self.assertFalse((archive_root / f".journal-{FEATURE}.json").exists())

    # D4 helpers used by the recovery tests
    def build_journal(self, phase: str):
        meta = ph_sdd.load_meta(self.repo, FEATURE)
        feature_dir = self.repo / FEATURE_REL
        fingerprint = ph_sdd.feature_fingerprint(meta, feature_dir)
        stamp = "20991231T000000000000Z"
        snapshot_rel = f"{ARCHIVE_ROOT}/{FEATURE}/{stamp}"
        manifest = [[p.relative_to(feature_dir).as_posix(), ph_sdd.sha256_file(p)]
                    for p in sorted(feature_dir.rglob("*"))
                    if p.is_file() and p.name != "ph-feature.json"]
        entry = {
            "feature": FEATURE, "flow": "full", "snapshot": snapshot_rel,
            "archived_at": ph_sdd.now_utc(), "note": "恢复测试归档决定", "evidence": None,
            "artifact_states": {n: r["status"] for n, r in meta["artifacts"].items()},
            "feature_fingerprint": fingerprint,
        }
        meta_entry = {k: entry[k] for k in ("snapshot", "archived_at", "note", "evidence",
                                            "feature_fingerprint")}
        journal = {
            "schema": ph_sdd.ARCHIVE_JOURNAL_SCHEMA, "feature": FEATURE, "phase": phase,
            "snapshot": snapshot_rel, "feature_fingerprint": fingerprint,
            "files": manifest, "entry": entry, "meta_entry": meta_entry,
        }
        ph_sdd.write_journal(self.repo, FEATURE, journal)
        return journal

    def test_recovery_completes_copied_transaction(self):
        self.complete()
        journal = self.build_journal("copying")
        # simulate a crash right after the copy: snapshot exists, index/metadata do not
        ph_sdd._copy_snapshot(self.repo / FEATURE_REL, self.repo / journal["snapshot"], journal["files"])
        journal["phase"] = "copied"
        ph_sdd.write_journal(self.repo, FEATURE, journal)
        proc = self.archive(note="恢复测试归档决定")
        payload = self.payload(proc)
        self.assertEqual(payload["result"], "recovered")
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 1)
        self.assertEqual(len(self.metadata()["archive"]), 1)
        self.assertFalse(ph_sdd.journal_path(self.repo, FEATURE).exists())
        # re-running archives as unchanged: no duplicates
        proc = self.archive(note="恢复测试归档决定")
        self.assertTrue(self.payload(proc)["unchanged"])
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 1)

    def test_recovery_redoes_partial_copy(self):
        self.complete()
        journal = self.build_journal("copying")
        partial = self.repo / journal["snapshot"]
        partial.mkdir(parents=True)
        (partial / "requirement.md").write_text("半个损坏副本", encoding="utf-8")
        proc = self.archive(note="恢复测试归档决定")
        payload = self.payload(proc)
        self.assertEqual(payload["result"], "recovered")
        snapshot = self.repo / journal["snapshot"]
        self.assertEqual((snapshot / "requirement.md").read_bytes(),
                         (self.feature_dir / "requirement.md").read_bytes())
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 1)
        self.assertFalse(ph_sdd.journal_path(self.repo, FEATURE).exists())

    def test_recovery_completes_when_index_written_but_metadata_not(self):
        self.complete()
        journal = self.build_journal("copying")
        ph_sdd._copy_snapshot(self.repo / FEATURE_REL, self.repo / journal["snapshot"], journal["files"])
        journal["phase"] = "copied"
        ph_sdd.write_journal(self.repo, FEATURE, journal)
        ph_sdd._append_index_entry(self.repo, journal["entry"])  # crash before metadata write
        proc = self.archive(note="恢复测试归档决定")
        self.payload(proc)
        index = json.loads((self.repo / ARCHIVE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 1)  # not duplicated
        self.assertEqual(len(self.metadata()["archive"]), 1)  # completed

    def test_copy_failure_rolls_back_and_keeps_originals(self):
        self.complete()
        target = self.feature_dir / "verification.md"
        original = target.read_bytes()
        target.chmod(0o000)
        try:
            proc = self.archive()
            self.assertEqual(proc.returncode, 2)
            self.assertIn("无法读取", proc.stderr)
        finally:
            target.chmod(0o644)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((self.repo / ARCHIVE_ROOT / FEATURE).exists())
        self.assertFalse(ph_sdd.journal_path(self.repo, FEATURE).exists())


class LockTests(SddFixture):
    """Audit regression D3: mutating applies hold a repo-managed mutex;
    dry-runs never lock; a live lock is refused, a dead lock is cleaned."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.create().returncode, 0)
        self.write_artifact("requirement", "# 需求\nFR-1\n")
        self.lock_path = self.repo / ".agents/project-harness" / ph_sdd.SDD_LOCK_NAME

    def write_lock(self, pid: int):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(json.dumps({"pid": pid, "command": "other", "at": "x"}), encoding="utf-8")

    def test_live_lock_blocks_apply_but_not_dry_run(self):
        holder = subprocess.Popen(["sleep", "30"])
        try:
            self.write_lock(holder.pid)
            proc = self.mark("requirement", "reviewed", note="确认")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("不抢锁", proc.stderr)
            proc = self.mark("requirement", "reviewed", note="确认", apply=False)  # dry-run: no lock
            self.assertEqual(proc.returncode, 0, proc.stderr)
        finally:
            holder.terminate()
            holder.wait()
        self.assertTrue(self.lock_path.exists())

    def test_dead_lock_is_cleaned_and_apply_proceeds(self):
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.write_lock(gone.pid)
        proc = self.mark("requirement", "reviewed", note="确认")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.lock_path.exists())  # released after the run

    def test_unrecognized_lock_is_refused_and_preserved(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text("这不是锁记录", encoding="utf-8")
        proc = self.mark("requirement", "reviewed", note="确认")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("人工确认", proc.stderr)
        self.assertEqual(self.lock_path.read_text(encoding="utf-8"), "这不是锁记录")

    def test_lock_released_after_normal_archive(self):
        self.assertTrue(self.review_chain())
        self.write_artifact("tasks", "# 任务\nT1\n")
        self.write_artifact("verify-plan", "# 计划\nVP-1\n")
        self.write_artifact("verification", "# 验证\n完成。\n")
        self.write_artifact("acceptance", "# 验收\nAC-1\n")
        for artifact, status in (("tasks", "done"), ("verification", "passed"), ("acceptance", "passed")):
            self.assertEqual(self.mark(artifact, status, note="完成").returncode, 0)
        self.assertEqual(self.archive().returncode, 0)
        self.assertFalse(self.lock_path.exists())


class DotfileTests(SddFixture):
    """Audit regression D5: dotfile-only directories are consistent between
    status classification and create preflight."""

    def test_dotfile_only_dir_is_empty_for_status_and_creatable(self):
        self.feature_dir.mkdir()
        (self.feature_dir / ".DS_Store").write_bytes(b"\x00")
        report = self.payload(self.status("--feature", FEATURE))
        self.assertEqual(report["features"][0]["flow"], "empty")
        proc = self.create(apply=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.payload(self.create())
        self.assertEqual(payload["created"], True)
        self.assertTrue((self.feature_dir / "ph-feature.json").is_file())
        self.assertTrue((self.feature_dir / ".DS_Store").exists())  # untouched


class AdoptUnicodeTests(SddFixture):
    """Audit regression D6: historical feature names may be non-ASCII."""

    def make_legacy(self, feature: str) -> Path:
        d = self.specs / feature
        d.mkdir(parents=True)
        (d / "spec.md").write_text("# 旧规格\n", encoding="utf-8")
        (d / "plan.md").write_text("# 旧计划\n", encoding="utf-8")
        return d

    def test_adopt_allows_chinese_historical_name_without_rename(self):
        d = self.make_legacy("001-登录功能")
        before = (d / "spec.md").read_bytes()
        payload = self.payload(self.adopt("001-登录功能"))
        self.assertEqual(payload["files"], {"requirement": "spec.md", "design": "plan.md"})
        meta = json.loads((d / "ph-feature.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "001-登录功能")
        self.assertEqual((d / "spec.md").read_bytes(), before)  # originals untouched
        report = self.payload(self.status("--all"))
        features = {f["id"]: f for f in report["features"]}
        self.assertEqual(features["001-登录功能"]["flow"], "full")

    def test_adopt_rejects_unsafe_names(self):
        for bad in ("带空格 ", " a/b", "a/b", "..", "x" * 81, "tab\tname"):
            proc = self.adopt(bad)
            self.assertEqual(proc.returncode, 2, bad)


class StatusIsolationTests(SddFixture):
    """Audit regression D7: one broken directory cannot blank out status --all."""

    def test_status_all_continues_past_broken_directory(self):
        self.assertEqual(self.create().returncode, 0)
        outside = self.new_dir()
        link = self.specs / "003-bad"
        link.symlink_to(outside)
        proc = self.status("--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        flows = {f["id"]: f["flow"] for f in report["features"]}
        self.assertEqual(flows[FEATURE], "full")
        self.assertEqual(flows["003-bad"], "error")
        self.assertIn("symlink", json.dumps(report, ensure_ascii=False))


class PathSafetyTests(SddFixture):
    def test_symlinked_feature_and_artifact_refused(self):
        outside = self.new_dir() / "outside"
        outside.mkdir()
        (outside / "requirement.md").write_text("外部\n", encoding="utf-8")
        link = self.specs / FEATURE
        link.symlink_to(outside)
        proc = self.create()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("symlink", proc.stderr)

        self.assertEqual(self.create(feature="002-real").returncode, 0)
        link2 = self.specs / "002-real" / "design.md"
        link2.symlink_to(outside / "requirement.md")
        proc = self.mark("design", "reviewed", note="确认", feature="002-real")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("symlink", proc.stderr)

    def test_hardlinked_metadata_refused_without_writing_external_inode(self):
        self.assertEqual(self.create().returncode, 0)
        self.write_artifact("requirement", "# 需求\nFR-1 登录。\n")
        metadata = self.feature_dir / "ph-feature.json"
        outside = self.new_dir() / "shared-metadata.json"
        metadata.rename(outside)
        os.link(outside, metadata)
        before = outside.read_bytes()

        proc = self.mark("requirement", "reviewed", note="已审查")

        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("hardlink", proc.stderr)
        self.assertEqual(outside.read_bytes(), before)
        self.assertEqual(metadata.read_bytes(), before)

    def test_hardlinked_artifact_refused_without_changing_metadata(self):
        self.assertEqual(self.create().returncode, 0)
        outside = self.new_dir() / "requirement.md"
        outside.write_text("# 需求\nFR-1 登录。\n", encoding="utf-8")
        os.link(outside, self.feature_dir / "requirement.md")
        before = (self.feature_dir / "ph-feature.json").read_bytes()
        original = outside.read_bytes()

        proc = self.mark("requirement", "reviewed", note="已审查")

        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("hardlink", proc.stderr)
        self.assertEqual((self.feature_dir / "ph-feature.json").read_bytes(), before)
        self.assertEqual(outside.read_bytes(), original)

    def test_escaping_paths_refused(self):
        for bad in ("../escape", "/abs", "~/home", "a/b"):
            proc = self.run_cli("status", "--feature", bad)
            self.assertEqual(proc.returncode, 2, bad)


if __name__ == "__main__":
    unittest.main()
