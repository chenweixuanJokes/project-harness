#!/usr/bin/env python3
"""Behavior tests for the 1.1.14 intent-to-spec migration item.

Covers the verbatim extraction contract (no fabrication, NEEDS CLARIFICATION),
the persistent cross-version mapping ledger, the read-only-history rule
(original bytes untouched), interruption idempotency, source-hash drift,
user-modified specs, same-name foreign specs, duplicate source ids,
history-only registration for 已废弃/访谈纪要, the mandatory verify gate and
the explicit select-intent-spec invocation (never overwriting a live feature
pointer). Since 1.2.3 the retired upstream resolver is also covered
negatively: migrated intent features must stay adoptable by the self-built
ph_sdd.py runtime, and the legacy feature pointer keeps its path and
feature_directory contract.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ph_merge_update as mu  # noqa: E402

# The self-built SDD runtime that took over from the retired upstream scripts.
SDD_SCRIPT = REPO_ROOT / "assets/scaffold/.agents/scripts/ph_sdd.py"
_sdd_spec = importlib.util.spec_from_file_location("ph_sdd_layout_contract", SDD_SCRIPT)
ph_sdd = importlib.util.module_from_spec(_sdd_spec)
_sdd_spec.loader.exec_module(ph_sdd)


FULL_ENTRY = """---
intent_id: "INT-20260901-login"
type: feature
status_dir: {status_dir}
created: "2026-09-01"
updated: "2026-09-01"
---

# 登录改造

背景正文。

## 目标

用户能单点登录。

## 范围与非目标

仅 Web 端；不做移动端。

## 关键约束

必须复用现有会话服务。

## 验收标准

跳转登录后回跳原页。

## 待澄清问题

是否支持第三方登录待定。
"""

SPARSE_ENTRY = """---
intent_id: "INT-20260902-crash"
type: issue
status_dir: {status_dir}
created: "2026-09-02"
---

# 崩溃修复

- 2026-09-02 计划获批，已启动实施。
"""

DROPPED_ENTRY = """---
intent_id: "INT-20260903-old"
status_dir: 已废弃/新特性
---

# 旧想法

放弃。
"""

INTERVIEW_ENTRY = """---
interview_id: "IV-20260901-100000-login"
intent_id: "INT-20260901-login"
status: complete
---

# 登录访谈

## 结论与结束状态

目标已明确。
"""


class IntentToSpecTestCase(unittest.TestCase):
    def test_repeated_section_occurrences_render_once_in_original_order(self):
        text = "# 标题\n"
        for heading in ("目标", "待澄清问题", "记录"):
            text += f"\n## {heading}\n{heading}甲唯一正文\n## {heading}\n{heading}乙唯一正文\n"
        parsed = mu._parse_intent_document(text)
        rendered = mu._render_intent_spec("docs/意图/a.md", "0" * 64, parsed, "intent-a")
        for heading in ("目标", "待澄清问题", "记录"):
            first, second = f"{heading}甲唯一正文", f"{heading}乙唯一正文"
            self.assertEqual(rendered.count(first), 1)
            self.assertEqual(rendered.count(second), 1)
            self.assertLess(rendered.index(first), rendered.index(second))

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for dirpath in (
            "docs/意图/待办/新特性",
            "docs/意图/实施/问题记录",
            "docs/意图/已废弃/新特性",
            "docs/意图/访谈纪要",
        ):
            (self.repo / dirpath).mkdir(parents=True)
        self.write("docs/意图/待办/新特性/INT-20260901-login.md", FULL_ENTRY.format(status_dir="待办/新特性"))
        self.write("docs/意图/实施/问题记录/INT-20260902-crash.md", SPARSE_ENTRY.format(status_dir="实施/问题记录"))
        self.write("docs/意图/已废弃/新特性/INT-20260903-old.md", DROPPED_ENTRY)
        self.write("docs/意图/访谈纪要/IV-20260901-100000-login.md", INTERVIEW_ENTRY)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        dest = self.repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return dest

    def migrate(self, apply: bool = False):
        return mu.migrate_intents_payload(self.repo, apply)

    def ledger(self) -> dict:
        return json.loads((self.repo / mu.INTENT_LEDGER_REL).read_text(encoding="utf-8"))

    def spec_bytes(self, spec: str) -> bytes:
        return (self.repo / spec).read_bytes()

    def snapshot(self) -> dict[str, str]:
        snaps: dict[str, str] = {}
        for base in ("docs/意图", mu.INTENT_SPEC_ROOT, mu.SPECIFY_DIR):
            root = self.repo / base
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    snaps[path.relative_to(self.repo).as_posix()] = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
        return snaps

    # -- extraction contract ------------------------------------------------

    def test_apply_generates_specs_with_verbatim_sections_and_metadata(self):
        result = self.migrate(apply=True)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(
            sorted(result["generated"]),
            [".agents/project-harness/specs/intent-INT-20260901-login/spec.md", ".agents/project-harness/specs/intent-INT-20260902-crash/spec.md"],
        )
        spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260901-login/spec.md").decode("utf-8")
        self.assertIn("# Feature Specification: 登录改造", spec)
        for fragment in ("用户能单点登录。", "仅 Web 端；不做移动端。", "必须复用现有会话服务。", "跳转登录后回跳原页。"):
            self.assertIn(fragment, spec)
        self.assertIn("intent_id: `INT-20260901-login`", spec)
        ledger_entries = {e["intent_id"]: e for e in self.ledger()["entries"]}
        self.assertIn(ledger_entries["INT-20260901-login"]["source_sha256"], spec)
        self.assertIn("status_dir: `待办/新特性`", spec)
        # The plan/tasks prohibition and the not-complete statement are present.
        self.assertIn("不生成 plan / tasks", spec)
        self.assertIn("不得据本文件自动重新验收或判通过", spec)

    def test_missing_sections_become_needs_clarification_without_fabrication(self):
        self.migrate(apply=True)
        spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260902-crash/spec.md").decode("utf-8")
        self.assertEqual(spec.count("NEEDS CLARIFICATION: 原意图没有「"), 4)
        for section in ("目标", "范围与非目标", "关键约束", "验收标准"):
            self.assertIn(f"## {section}（逐字摘录）", spec)
        self.assertNotIn("FR-001", spec)
        self.assertNotIn("SC-001", spec)
        self.assertNotIn("P1", spec)
        self.assertNotIn("User Story", spec)
        # No plan/tasks files are generated anywhere under specs/.
        for path in (self.repo / "specs").rglob("*"):
            if path.is_file():
                self.assertIn(path.name, {"spec.md", ".ph-intent-ledger.json"})

    def test_dropped_and_interview_entries_are_history_only(self):
        result = self.migrate(apply=True)
        self.assertIn("docs/意图/已废弃/新特性/INT-20260903-old.md", result["history_only"])
        self.assertIn("docs/意图/访谈纪要/IV-20260901-100000-login.md", result["history_only"])
        self.assertFalse((self.repo / ".agents/project-harness/specs/intent-INT-20260903-old").exists())
        ledger = self.ledger()
        self.assertEqual(len(ledger["entries"]), 2)
        self.assertEqual(len(ledger["history_only"]), 2)
        index = (self.repo / mu.INTENT_HISTORY_REL).read_text(encoding="utf-8")
        self.assertIn("唯一后续维护位置", index)
        for rel in (
            "docs/意图/已废弃/新特性/INT-20260903-old.md",
            "docs/意图/访谈纪要/IV-20260901-100000-login.md",
        ):
            self.assertIn(rel, index)
        self.assertIn("select-intent-spec", index)
        self.assertIn("SPECIFY_FEATURE_DIRECTORY", index)

    def test_originals_stay_byte_identical(self):
        before = self.snapshot()
        self.migrate(apply=True)
        after = self.snapshot()
        for rel, digest in before.items():
            if rel.startswith("docs/意图"):
                self.assertEqual(after[rel], digest, f"original drifted: {rel}")
        # Only additive artifacts appear.
        new_rels = set(after) - set(before)
        self.assertTrue(new_rels)
        self.assertTrue(all(rel.startswith(".agents/project-harness/specs/") or rel == mu.INTENT_HISTORY_REL for rel in new_rels))

    # -- ledger persistence and conflicts -----------------------------------

    def test_rerun_is_idempotent_and_ledger_is_persistent(self):
        first = self.migrate(apply=True)
        snapshot = self.snapshot()
        second = self.migrate(apply=True)
        self.assertEqual(sorted(second["skipped"]), sorted(first["generated"]))
        self.assertEqual(second["generated"], [])
        self.assertEqual(second["conflicts"], [])
        self.assertEqual(self.snapshot(), snapshot, "a repeated migration must not change the repo")

    def test_interrupted_run_resumes_from_half_written_specs(self):
        # Simulate an interruption after spec writes but before the ledger:
        # a rerun recognizes its own deterministic output and completes.
        plan = mu.plan_intent_to_spec(self.repo)
        for row in plan["rows"]:
            if row.get("spec") and row["action"] == "generated":
                mu._write_repo_bytes(self.repo, row["spec"], b"placeholder-wrong-bytes")
        with self.assertRaises(mu.PHError):
            self.migrate(apply=True)  # foreign bytes at the target block the apply
        for row in plan["rows"]:
            if row.get("spec") and row["action"] == "generated":
                expected = mu._render_intent_spec(
                    row["source"], row["source_sha256"],
                    mu._parse_intent_document((self.repo / row["source"]).read_text(encoding="utf-8")),
                    row["spec_dir"],
                ).encode("utf-8")
                mu._write_repo_bytes(self.repo, row["spec"], expected)
        result = self.migrate(apply=True)
        self.assertEqual(sorted(result["restored"]), sorted(r["spec"] for r in plan["rows"] if r.get("spec")))
        self.assertEqual(self.ledger()["schema"], mu.INTENT_HISTORY_SCHEMA)

    def test_source_updated_blocks_apply_and_verify(self):
        # Read-only-history originals that drift after the migration are an
        # unreviewed change: the apply must surface them as a blocker (never
        # silently skip), and the verify gate must keep refusing until the
        # original bytes are restored.
        self.migrate(apply=True)
        entry = self.repo / "docs/意图/待办/新特性/INT-20260901-login.md"
        entry.write_text(entry.read_text(encoding="utf-8") + "\n新增记录行。\n", encoding="utf-8")
        spec_before = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260901-login/spec.md")
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("read-only-history originals drifted", str(caught.exception))
        self.assertIn("docs/意图/待办/新特性/INT-20260901-login.md", str(caught.exception))
        self.assertEqual(self.spec_bytes(".agents/project-harness/specs/intent-INT-20260901-login/spec.md"), spec_before)
        with self.assertRaises(mu.PHError) as caught:
            mu.verify_intent_spec_layout(self.repo)
        self.assertIn("originals drifted", str(caught.exception))
        # Dry-run still reports the drift without raising.
        plan = self.migrate()
        self.assertEqual(plan["source_updated"], ["docs/意图/待办/新特性/INT-20260901-login.md"])
        # Restoring the original bytes unblocks both the apply and verify.
        self.write("docs/意图/待办/新特性/INT-20260901-login.md", FULL_ENTRY.format(status_dir="待办/新特性"))
        self.migrate(apply=True)
        mu.verify_intent_spec_layout(self.repo)

    def test_user_modified_spec_is_never_overwritten(self):
        self.migrate(apply=True)
        spec_path = self.repo / ".agents/project-harness/specs/intent-INT-20260901-login/spec.md"
        spec_path.write_bytes(spec_path.read_bytes() + "\n用户补充：移动端范围待议。\n".encode("utf-8"))
        result = self.migrate(apply=True)
        self.assertEqual(result["spec_user_modified"], ["docs/意图/待办/新特性/INT-20260901-login.md"])
        self.assertIn("用户补充", spec_path.read_text(encoding="utf-8"))

    def test_same_name_foreign_spec_blocks_apply_without_writing(self):
        (self.repo / ".agents/project-harness/specs/intent-INT-20260901-login").mkdir(parents=True)
        (self.repo / ".agents/project-harness/specs/intent-INT-20260901-login/spec.md").write_text("mine", encoding="utf-8")
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("already exists and is not a migration artifact", str(caught.exception))
        self.assertEqual((self.repo / ".agents/project-harness/specs/intent-INT-20260901-login/spec.md").read_text(encoding="utf-8"), "mine")
        self.assertFalse((self.repo / mu.INTENT_LEDGER_REL).exists())
        plan = self.migrate()
        self.assertTrue(any("already exists" in c for c in plan["conflicts"]))

    def test_duplicate_source_intent_id_blocks_apply(self):
        self.write("docs/意图/待办/问题记录/dup.md", FULL_ENTRY.replace("待办/新特性", "待办/问题记录"))
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("duplicate source id", str(caught.exception))
        self.assertFalse((self.repo / mu.INTENT_LEDGER_REL).exists())

    def test_early_layout_roots_are_migrated_too(self):
        # A tree that still carries the pre-1.1.2 进行中/已完成 directories.
        for dirpath in ("docs/意图/进行中/新特性", "docs/意图/已完成/问题记录"):
            (self.repo / dirpath).mkdir(parents=True, exist_ok=True)
        self.write(
            "docs/意图/进行中/新特性/INT-20260801-early.md",
            FULL_ENTRY.format(status_dir="进行中/新特性").replace("INT-20260901-login", "INT-20260801-early"),
        )
        self.write(
            "docs/意图/已完成/问题记录/INT-20260802-done.md",
            SPARSE_ENTRY.format(status_dir="已完成/问题记录").replace("INT-20260902-crash", "INT-20260802-done"),
        )
        result = self.migrate(apply=True)
        self.assertIn(".agents/project-harness/specs/intent-INT-20260801-early/spec.md", result["generated"])
        self.assertIn(".agents/project-harness/specs/intent-INT-20260802-done/spec.md", result["generated"])
        # An early-layout completed legacy entry keeps its completed status.
        done = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260802-done/spec.md").decode("utf-8")
        self.assertIn("**Status**: Complete", done)
        self.assertIn("不自动重新验收或判通过", done)
        early = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260801-early/spec.md").decode("utf-8")
        self.assertIn("**Status**: In Progress", early)
        self.assertIn("实施不等于完成", early)

    # -- mandatory verify gate ----------------------------------------------

    def test_verify_gate_accepts_the_applied_state(self):
        self.migrate(apply=True)
        mu.verify_intent_spec_layout(self.repo)  # must not raise

    def test_verify_gate_rejects_missing_or_inconsistent_artifacts(self):
        with self.assertRaises(mu.PHError):
            mu.verify_intent_spec_layout(self.repo)
        self.migrate(apply=True)
        (self.repo / ".agents/project-harness/specs/intent-INT-20260902-crash/spec.md").unlink()
        with self.assertRaises(mu.PHError):
            mu.verify_intent_spec_layout(self.repo)
        self.migrate(apply=True)
        (self.repo / "docs/意图/历史索引.md").unlink()
        with self.assertRaises(mu.PHError):
            mu.verify_intent_spec_layout(self.repo)

    def test_foreign_ledger_schema_is_refused(self):
        (self.repo / "specs").mkdir()
        ledger_path = self.repo / mu.INTENT_LEDGER_REL
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps({"schema": "someone-else/9", "entries": []}), encoding="utf-8"
        )
        with self.assertRaises(mu.PHError):
            self.migrate()

    # -- select-intent-spec -------------------------------------------------

    def test_select_writes_pointer_only_when_absent_and_never_overwrites(self):
        self.migrate(apply=True)
        plan = mu.select_intent_spec(self.repo, "INT-20260901-login", None, apply=False)
        self.assertEqual(plan["planned"]["feature_directory"], ".agents/project-harness/specs/intent-INT-20260901-login")
        self.assertFalse((self.repo / ".agents/project-harness/runtime/feature.json").exists())
        mu.select_intent_spec(self.repo, "INT-20260901-login", None, apply=True)
        pointer = json.loads((self.repo / ".agents/project-harness/runtime/feature.json").read_text(encoding="utf-8"))
        # The upstream resolver derives FEATURE_SPEC as <dir>/spec.md itself, so
        # the pointer must hold the directory, never the spec.md file path.
        self.assertEqual(pointer, {"feature_directory": ".agents/project-harness/specs/intent-INT-20260901-login"})
        # A live pointer pointing elsewhere is never overwritten.
        with self.assertRaises(mu.PHError) as caught:
            mu.select_intent_spec(self.repo, "INT-20260902-crash", None, apply=True)
        self.assertIn("refusing to overwrite the active feature pointer", str(caught.exception))
        self.assertEqual(
            json.loads((self.repo / ".agents/project-harness/runtime/feature.json").read_text(encoding="utf-8")), pointer
        )
        # Selecting the already-selected spec is a no-op.
        again = mu.select_intent_spec(self.repo, "INT-20260901-login", None, apply=True)
        self.assertFalse(again["wrote"])
        # Selecting by spec path or by directory both work; unknown ids fail.
        by_spec = mu.select_intent_spec(self.repo, None, ".agents/project-harness/specs/intent-INT-20260902-crash/spec.md", apply=False)
        self.assertEqual(by_spec["intent_id"], "INT-20260902-crash")
        by_dir = mu.select_intent_spec(self.repo, None, ".agents/project-harness/specs/intent-INT-20260902-crash", apply=False)
        self.assertEqual(by_dir["intent_id"], "INT-20260902-crash")
        with self.assertRaises(mu.PHError):
            mu.select_intent_spec(self.repo, "INT-404", None, apply=False)

    def test_migration_never_creates_the_feature_pointer(self):
        self.migrate(apply=True)
        self.assertFalse((self.repo / ".agents/project-harness/runtime/feature.json").exists())

    def test_migrated_intent_feature_is_adoptable_by_the_self_runtime(self):
        # The upstream bash resolver is retired; the self-built runtime takes
        # over. A migrated intent feature directory (spec.md at its root) must
        # stay adoptable via ph_sdd.py adopt: the original bytes are never
        # edited, the metadata records the legacy mapping, and adopt itself
        # never creates the legacy runtime pointer.
        self.migrate(apply=True)
        spec_rel = ".agents/project-harness/specs/intent-INT-20260901-login/spec.md"
        before = self.spec_bytes(spec_rel)
        result = subprocess.run(
            [sys.executable, str(SDD_SCRIPT), "adopt",
             "--feature", "intent-INT-20260901-login",
             "--repo", str(self.repo), "--apply"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        meta = json.loads(
            (self.repo / ".agents/project-harness/specs/intent-INT-20260901-login/ph-feature.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(meta["schema"], ph_sdd.METADATA_SCHEMA)
        self.assertEqual(meta["flow"], "full")
        self.assertEqual(meta["adopted_from"], {"requirement": "spec.md"})
        self.assertEqual(self.spec_bytes(spec_rel), before)
        self.assertFalse((self.repo / ph_sdd.LEGACY_POINTER).exists())

    def test_select_pointer_keeps_the_legacy_runtime_contract(self):
        # The legacy pointer path and its feature_directory contract are
        # unchanged, so the runtime's read-only compatibility and the explicit
        # select command agree on the same file.
        self.migrate(apply=True)
        self.assertEqual(ph_sdd.LEGACY_POINTER,
                         ".agents/project-harness/runtime/feature.json")
        mu.select_intent_spec(self.repo, "INT-20260901-login", None, apply=True)
        pointer = json.loads((self.repo / ph_sdd.LEGACY_POINTER).read_text(encoding="utf-8"))
        self.assertEqual(
            pointer,
            {"feature_directory": ".agents/project-harness/specs/intent-INT-20260901-login"},
        )

    # -- review fixes: aliases, status mapping, casefold, containment -------

    def test_old_template_aliases_and_every_section_survive(self):
        # The 1.0.0 template (c805d8f) had 背景/目标/非目标/记录 only: 非目标 is a
        # 范围与非目标 alias, and nothing (records, acceptance conclusions,
        # preamble) may be dropped or mislabeled as missing.
        old_layout = """---
intent_id: "INT-20260801-legacy"
type: feature
status_dir: 进行中/新特性
created: "2026-08-01"
---

# 旧版模板条目

引言：这条正文必须原样保留。

## 背景

老模板的背景说明。

## 目标

可验证的完成标准甲。

## 非目标

明确不做的范围乙。

## 记录

- 2026-08-02 交付完成，验收通过：结论必须保留。
"""
        (self.repo / "docs/意图/进行中/新特性").mkdir(parents=True, exist_ok=True)
        self.write("docs/意图/进行中/新特性/INT-20260801-legacy.md", old_layout)
        self.migrate(apply=True)
        spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260801-legacy/spec.md").decode("utf-8")
        # Alias mapped: 非目标 content fills 范围与非目标, no false NEEDS
        # CLARIFICATION for it.
        self.assertIn("明确不做的范围乙。", spec)
        self.assertIn("原节「非目标」", spec)
        self.assertNotIn("原意图没有「范围与非目标 / 非目标」节", spec)
        # The other template sections are carried verbatim.
        self.assertIn("### 背景", spec)
        self.assertIn("老模板的背景说明。", spec)
        self.assertIn("### 记录", spec)
        self.assertIn("交付完成，验收通过：结论必须保留。", spec)
        # The preamble survives too.
        self.assertIn("引言：这条正文必须原样保留。", spec)
        # 关键约束 and 验收标准 genuinely do not exist in the old template.
        self.assertEqual(spec.count("NEEDS CLARIFICATION: 原意图没有「"), 2)
        # Status records the historical in-progress state, not Draft.
        self.assertIn("**Status**: In Progress", spec)
        self.assertIn("照录历史状态", spec)

    def test_status_reflects_the_historical_state_and_never_reopens_done(self):
        (self.repo / "docs/意图/已完成/新特性").mkdir(parents=True, exist_ok=True)
        done = SPARSE_ENTRY.format(status_dir="已完成/新特性").replace(
            "INT-20260902-crash", "INT-20260808-done"
        )
        self.write("docs/意图/已完成/新特性/INT-20260808-done.md", done)
        self.migrate(apply=True)
        pending = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260901-login/spec.md").decode("utf-8")
        self.assertIn("**Status**: Draft", pending)
        started = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260902-crash/spec.md").decode("utf-8")
        self.assertIn("**Status**: In Progress", started)
        done_spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260808-done/spec.md").decode("utf-8")
        self.assertIn("**Status**: Complete", done_spec)
        self.assertIn("不自动重新验收或判通过", done_spec)
        # An unrecognized status_dir is recorded as unknown, never guessed.
        self.write(
            "docs/意图/待办/新特性/INT-20260904-odd.md",
            FULL_ENTRY.replace("INT-20260901-login", "INT-20260904-odd").replace(
                "status_dir: 待办/新特性", "status_dir: 待审核/新特性"
            ),
        )
        self.migrate(apply=True)
        odd = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260904-odd/spec.md").decode("utf-8")
        self.assertIn("**Status**: Unknown", odd)
        self.assertIn("不推定任何实施或完成状态", odd)

    def test_casefold_collision_between_ids_blocks_the_apply(self):
        # On a case-insensitive filesystem specs/intent-Abc and specs/intent-abc
        # are the same directory; the plan must block instead of letting the
        # second write overwrite the first.
        # The source FILE names stay distinct (a case-only difference would
        # collapse to one file on a case-insensitive filesystem); the
        # intent_ids they declare differ only by case.
        base = FULL_ENTRY.format(status_dir="待办/新特性").replace("INT-20260901-login", "INT-20260905-CaseA")
        other = FULL_ENTRY.format(status_dir="待办/新特性").replace("INT-20260901-login", "INT-20260905-casea")
        self.write("docs/意图/待办/新特性/case-a-entry.md", base)
        self.write("docs/意图/待办/新特性/case-b-entry.md", other)
        plan = self.migrate()
        self.assertTrue(any("differ only by case" in c for c in plan["conflicts"]))
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("differ only by case", str(caught.exception))
        # Nothing was written: the specs root has no spec directory at all.
        specs_root = self.repo / mu.INTENT_SPEC_ROOT
        if specs_root.is_dir():
            live = [p.name for p in specs_root.iterdir()]
            self.assertEqual(live, [], "no spec directory may be created for colliding ids")

    def test_casefold_collision_in_the_ledger_fails_verify(self):
        self.migrate(apply=True)
        ledger_path = self.repo / mu.INTENT_LEDGER_REL
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        variant = mu.INTENT_SPEC_ROOT + "/INTENT-INT-20260901-LOGIN/spec.md"
        variant_path = self.repo / variant
        if not variant_path.exists():
            variant_path.parent.mkdir(parents=True)
            variant_path.write_bytes((self.repo / ledger["entries"][0]["spec"]).read_bytes())
        ledger["entries"].append(dict(ledger["entries"][0], spec=variant))
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(mu.PHError) as caught:
            mu.verify_intent_spec_layout(self.repo)
        self.assertIn("differ only by case", str(caught.exception))

    def test_symlinked_specs_ancestor_is_refused(self):
        # The ledger write (the one write that happens even when no spec is
        # generated) must refuse to travel through a symlinked ancestor.
        (self.repo / "docs/意图/待办/新特性/INT-20260901-login.md").unlink()
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (self.repo / mu.INTENT_SPEC_ROOT).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / mu.INTENT_SPEC_ROOT).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("specs", str(caught.exception))
        self.assertIn("symlink", str(caught.exception))
        # verify also refuses the symlinked artifact tree.
        ledger_dest = outside / ".ph-intent-ledger.json"
        ledger_dest.write_text(
            json.dumps({"schema": mu.INTENT_HISTORY_SCHEMA, "entries": [], "history_only": []}),
            encoding="utf-8",
        )
        (self.repo / "docs/意图/历史索引.md").write_text("# 索引\n", encoding="utf-8")
        with self.assertRaises(mu.PHError) as caught:
            mu.verify_intent_spec_layout(self.repo)
        self.assertIn("specs", str(caught.exception))
        self.assertIn("symlink", str(caught.exception))

    def test_ledger_loss_with_user_edited_spec_has_a_recovery_path(self):
        # A deleted ledger plus a user-edited spec blocks safely and tells the
        # user the recovery: move the edited spec aside, regenerate the
        # baseline, then re-apply the edits.
        self.migrate(apply=True)
        spec_path = self.repo / ".agents/project-harness/specs/intent-INT-20260901-login/spec.md"
        edited = spec_path.read_bytes() + "\n用户补充：范围待议。\n".encode("utf-8")
        spec_path.write_bytes(edited)
        (self.repo / mu.INTENT_LEDGER_REL).unlink()
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("already exists and is not a migration artifact", str(caught.exception))
        self.assertIn("recovery:", str(caught.exception))
        # Follow the documented recovery: move it aside, regenerate, re-apply.
        aside = Path(self._tmp.name) / "aside"
        aside.mkdir()
        (aside / "intent-INT-20260901-login.md").write_bytes(edited)
        import shutil as _shutil
        _shutil.rmtree(spec_path.parent)
        self.migrate(apply=True)
        self.assertEqual(
            self.spec_bytes(".agents/project-harness/specs/intent-INT-20260901-login/spec.md"),
            self.spec_bytes(".agents/project-harness/specs/intent-INT-20260901-login/spec.md"),
        )
        mu.verify_intent_spec_layout(self.repo)
        spec_path.write_bytes(edited)  # the user re-applies their edits
        # A user-modified spec is never overwritten by a rerun.
        result = self.migrate(apply=True)
        self.assertEqual(result["spec_user_modified"], ["docs/意图/待办/新特性/INT-20260901-login.md"])

    def test_history_index_user_edits_are_preserved(self):
        self.migrate(apply=True)
        index = self.repo / mu.INTENT_HISTORY_REL
        index.write_bytes(index.read_bytes() + "\n用户备注行。\n".encode("utf-8"))
        result = self.migrate(apply=True)
        self.assertTrue(result["history_index_user_modified"])
        self.assertIn("用户备注行。", index.read_text(encoding="utf-8"))

    # -- review fixes: parse fidelity, provenance, recovery ------------------

    def test_repeated_headings_keep_every_occurrence_verbatim(self):
        # Two `## 目标` sections used to collapse in a dict: the first body
        # was lost and the last body was rendered twice. Every occurrence
        # must survive, in document order.
        doc = FULL_ENTRY.format(status_dir="待办/新特性").replace(
            "## 目标\n\n用户能单点登录。\n",
            "## 目标\n\n用户能单点登录。\n\n## 背景\n\n第一段背景。\n\n## 目标\n\n修正后的目标。\n",
        )
        parsed = mu._parse_intent_document(doc)
        self.assertEqual(len(parsed["sections"]["目标"]), 2)
        self.assertEqual(len(parsed["sections"]["背景"]), 1)
        self.write("docs/意图/待办/新特性/INT-20260910-dup.md", doc.replace("INT-20260901-login", "INT-20260910-dup"))
        self.migrate(apply=True)
        spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260910-dup/spec.md").decode("utf-8")
        self.assertIn("用户能单点登录。", spec)
        self.assertIn("修正后的目标。", spec)
        self.assertIn("### 背景", spec)
        self.assertIn("第一段背景。", spec)

    def test_hash_headings_inside_code_fences_are_not_sections(self):
        # A `## ` line inside a fenced code block used to open a phantom
        # section, splitting the real section body.
        doc = FULL_ENTRY.format(status_dir="待办/新特性").replace(
            "## 验收标准\n\n跳转登录后回跳原页。\n",
            "## 验收标准\n\n跳转登录后回跳原页。\n\n```markdown\n## 目标\n\n这不是真实小节，是示例文档。\n```\n",
        )
        parsed = mu._parse_intent_document(doc)
        self.assertEqual(parsed["sections"]["目标"], ["用户能单点登录。"])
        self.assertIn("```markdown\n## 目标", "\n".join(parsed["sections"]["验收标准"]))
        self.write("docs/意图/待办/新特性/INT-20260911-fence.md", doc.replace("INT-20260901-login", "INT-20260911-fence"))
        self.migrate(apply=True)
        spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260911-fence/spec.md").decode("utf-8")
        self.assertIn("```markdown\n## 目标", spec)
        self.assertIn("这不是真实小节，是示例文档。", spec)
        # The fenced example did not split the 验收标准 body.
        self.assertLess(spec.index("跳转登录后回跳原页。"), spec.index("```markdown"))

    def test_empty_spec_section_becomes_needs_clarification(self):
        doc = FULL_ENTRY.format(status_dir="待办/新特性").replace(
            "## 关键约束\n\n必须复用现有会话服务。\n",
            "## 关键约束\n",
        )
        self.write("docs/意图/待办/新特性/INT-20260912-empty.md", doc.replace("INT-20260901-login", "INT-20260912-empty"))
        self.migrate(apply=True)
        spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260912-empty/spec.md").decode("utf-8")
        self.assertIn("NEEDS CLARIFICATION: 原意图没有「关键约束」节（或该节为空）", spec)

    def test_history_index_command_points_at_the_installed_script(self):
        # The index names the script path that actually ships in the project
        # (.agents/skills/ph-init carries the self-installed runtime payload);
        # the ph-merge-update skill directory has no scripts.
        self.migrate(apply=True)
        index = (self.repo / mu.INTENT_HISTORY_REL).read_text(encoding="utf-8")
        self.assertIn(".agents/skills/ph-init/scripts/ph_merge_update.py select-intent-spec", index)
        self.assertNotIn("ph-merge-update/scripts", index)

    def test_status_dir_disagreeing_with_physical_dir_blocks(self):
        # A file sitting in 已完成 while its frontmatter still says 待办 must
        # not be silently reopened as a Draft: the plan reports the conflict
        # and the apply writes nothing.
        (self.repo / "docs/意图/已完成/新特性").mkdir(parents=True, exist_ok=True)
        moved = FULL_ENTRY.format(status_dir="待办/新特性").replace("INT-20260901-login", "INT-20260913-moved")
        self.write("docs/意图/已完成/新特性/INT-20260913-moved.md", moved)
        plan = self.migrate()
        self.assertTrue(any("status_dir" in c and "已完成" in c for c in plan["conflicts"]), plan["conflicts"])
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("status_dir", str(caught.exception))
        self.assertFalse((self.repo / mu.INTENT_LEDGER_REL).exists())
        self.assertFalse((self.repo / ".agents/project-harness/specs/intent-INT-20260913-moved").exists())

    def test_missing_or_unrecognized_status_dir_stays_compatible(self):
        # Regular history stays compatible: an entry without status_dir, or
        # with an unrecognized one, keeps today's behavior (no conflict).
        (self.repo / "docs/意图/已完成/新特性").mkdir(parents=True, exist_ok=True)
        missing = FULL_ENTRY.format(status_dir="待办/新特性").replace("INT-20260901-login", "INT-20260914-nostatus")
        missing = missing.replace("status_dir: 待办/新特性\n", "")
        self.write("docs/意图/已完成/新特性/INT-20260914-nostatus.md", missing)
        result = self.migrate(apply=True)
        self.assertEqual(result["conflicts"], [])
        spec = self.spec_bytes(".agents/project-harness/specs/intent-INT-20260914-nostatus/spec.md").decode("utf-8")
        self.assertIn("**Status**: Unknown", spec)

    def test_history_index_survives_a_lost_ledger(self):
        # The index used to be overwritten whenever the ledger was gone: the
        # user-modified index must be kept and reported, the ledger rebuilt,
        # and the recovery stays idempotent.
        self.migrate(apply=True)
        index = self.repo / mu.INTENT_HISTORY_REL
        index.write_bytes(index.read_bytes() + "\n用户备注行。\n".encode("utf-8"))
        (self.repo / mu.INTENT_LEDGER_REL).unlink()
        result = self.migrate(apply=True)
        self.assertTrue(result["history_index_user_modified"])
        self.assertIn("用户备注行。", index.read_text(encoding="utf-8"))
        self.assertEqual(self.ledger()["schema"], mu.INTENT_HISTORY_SCHEMA)
        # Idempotent: a further run keeps preserving the same index.
        before = index.read_bytes()
        again = self.migrate(apply=True)
        self.assertTrue(again["history_index_user_modified"])
        self.assertEqual(index.read_bytes(), before)
        mu.verify_intent_spec_layout(self.repo)

    def test_history_index_regenerates_when_byte_identical_after_ledger_loss(self):
        # An interrupted run that wrote the index but not the ledger must
        # still recover: the generated index is byte-identical to the fresh
        # render, so rewriting it is a no-op.
        self.migrate(apply=True)
        index = self.repo / mu.INTENT_HISTORY_REL
        generated = index.read_bytes()
        (self.repo / mu.INTENT_LEDGER_REL).unlink()
        result = self.migrate(apply=True)
        self.assertFalse(result["history_index_user_modified"])
        self.assertEqual(index.read_bytes(), generated)

    def test_verify_rejects_a_history_index_missing_key_claims(self):
        # verify must check the key claims of the index (the specs/ tree as
        # the single follow-up maintenance location, the ledger as the
        # mapping authority, and the select command) - a normal user note
        # does not break it, but a rules section stripped of any claim fails.
        self.migrate(apply=True)
        index = self.repo / mu.INTENT_HISTORY_REL
        pristine = index.read_bytes()
        index.write_bytes(pristine + "\n用户备注行。\n".encode("utf-8"))
        mu.verify_intent_spec_layout(self.repo)  # notes never break verify
        stripped = [
            line
            for line in index.read_text(encoding="utf-8").splitlines(keepends=True)
            if "select-intent-spec" not in line
        ]
        index.write_text("".join(stripped), encoding="utf-8")
        with self.assertRaises(mu.PHError) as caught:
            mu.verify_intent_spec_layout(self.repo)
        self.assertIn("select-intent-spec", str(caught.exception))
        # A rules section that keeps the command but strips the
        # unique-maintenance declaration fails verify too.
        index.write_bytes(pristine)
        stripped = [
            line
            for line in index.read_text(encoding="utf-8").splitlines(keepends=True)
            if "唯一后续维护位置" not in line
        ]
        index.write_text("".join(stripped), encoding="utf-8")
        with self.assertRaises(mu.PHError) as caught:
            mu.verify_intent_spec_layout(self.repo)
        self.assertIn("唯一后续维护位置", str(caught.exception))

    def test_symlinked_intent_subdirectory_is_refused(self):
        # A symlinked subdirectory under a managed root must fail closed: a
        # plain rglob silently skips it, so entries behind the link would
        # vanish from the migration instead of being reported.
        outside = Path(self._tmp.name) / "linked-intent"
        outside.mkdir()
        (outside / "INT-20260920-linked.md").write_text(
            FULL_ENTRY.format(status_dir="待办/新特性").replace("INT-20260901-login", "INT-20260920-linked"),
            encoding="utf-8",
        )
        (self.repo / "docs/意图/待办/新特性/linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(mu.PHError) as caught:
            self.migrate()  # already refused in the read-only dry-run
        self.assertIn("symlink", str(caught.exception))
        self.assertIn("linked", str(caught.exception))
        with self.assertRaises(mu.PHError):
            self.migrate(apply=True)
        self.assertFalse((self.repo / mu.INTENT_LEDGER_REL).exists())

    def test_symlinked_intent_file_is_refused(self):
        outside = Path(self._tmp.name) / "linked-entry.md"
        outside.write_text("nope\n", encoding="utf-8")
        (self.repo / "docs/意图/待办/新特性/INT-20260921-link.md").symlink_to(outside)
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("symlink", str(caught.exception))

    def test_verify_checks_history_only_containment(self):
        # history_only originals get the same ancestor containment proof as
        # migrated entries: a symlinked docs tree must not read as in-repo.
        self.migrate(apply=True)
        ledger_path = self.repo / mu.INTENT_LEDGER_REL
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        entry = dict(ledger["history_only"][0])
        escape = Path(self._tmp.name) / "escape-意图"
        escape.mkdir()
        link_root = self.repo / "docs" / "链接意图"
        link_root.symlink_to(escape, target_is_directory=True)
        (escape / "INT-20260903-old.md").write_text(DROPPED_ENTRY, encoding="utf-8")
        entry["source"] = "docs/链接意图/INT-20260903-old.md"
        ledger["history_only"].append(entry)
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(mu.PHError) as caught:
            mu.verify_intent_spec_layout(self.repo)
        self.assertIn("escapes the repository", str(caught.exception))

    def test_specs_path_as_a_file_is_a_plan_conflict(self):
        # `specs` being a regular file used to crash the apply with a bare
        # NotADirectoryError; the dry-run must report it as a conflict.
        spec_root = self.repo / mu.INTENT_SPEC_ROOT
        spec_root.parent.mkdir(parents=True, exist_ok=True)
        spec_root.write_text("not a directory\n", encoding="utf-8")
        plan = self.migrate()
        self.assertTrue(any("real directory" in c for c in plan["conflicts"]), plan["conflicts"])
        with self.assertRaises(mu.PHError) as caught:
            self.migrate(apply=True)
        self.assertIn("specs", str(caught.exception))

    def test_feature_dir_path_as_a_file_is_a_plan_conflict(self):
        # A non-directory at the planned feature directory (e.g.
        # specs/intent-x as a file) must also be reported, not crash.
        (self.repo / mu.INTENT_SPEC_ROOT).mkdir(parents=True, exist_ok=True)
        (self.repo / mu.INTENT_SPEC_ROOT / "intent-INT-20260901-login").write_text("blocker\n", encoding="utf-8")
        plan = self.migrate()
        self.assertTrue(any("intent-INT-20260901-login" in c and "real directory" in c for c in plan["conflicts"]), plan["conflicts"])
        with self.assertRaises(mu.PHError):
            self.migrate(apply=True)

    def test_single_non_ascii_id_keeps_the_plain_slug(self):
        # A lone non-ASCII id keeps today's deterministic slug (any already
        # persisted mapping stays stable); only an actual collision between
        # different ids adds the deterministic disambiguator.
        self.write(
            "docs/意图/待办/新特性/中文.md",
            FULL_ENTRY.format(status_dir="待办/新特性").replace("INT-20260901-login", "登录改造甲"),
        )
        result = self.migrate(apply=True)
        self.assertIn(".agents/project-harness/specs/intent-unnamed/spec.md", result["generated"])

    def test_non_ascii_intent_ids_get_distinct_target_dirs(self):
        # Non-ASCII ids used to collapse to one slug and surface as a
        # misleading "duplicate source id"; when two DIFFERENT ids collide,
        # the later one gets a deterministic disambiguator while the first
        # keeps the plain (possibly already persisted) slug.
        self.write(
            "docs/意图/待办/新特性/中文甲.md",
            FULL_ENTRY.format(status_dir="待办/新特性").replace("INT-20260901-login", "登录改造甲"),
        )
        self.write(
            "docs/意图/待办/问题记录/中文乙.md",
            SPARSE_ENTRY.format(status_dir="待办/问题记录").replace("INT-20260902-crash", "崩溃修复乙"),
        )
        result = self.migrate(apply=True)
        self.assertEqual(result["conflicts"], [])
        self.assertIn(".agents/project-harness/specs/intent-unnamed/spec.md", result["generated"])
        suffix_b = hashlib.sha256("崩溃修复乙".encode("utf-8")).hexdigest()[:8]
        self.assertIn(f".agents/project-harness/specs/intent-unnamed-{suffix_b}/spec.md", result["generated"])
        mu.verify_intent_spec_layout(self.repo)
        # Idempotent: the rerun recognizes the same deterministic paths.
        again = self.migrate(apply=True)
        self.assertEqual(again["generated"], [])
        self.assertEqual(
            sorted(again["skipped"]),
            sorted(result["generated"]),
        )

    def test_ledger_recorded_spec_paths_stay_stable(self):
        # A recorded mapping is never recomputed: after a rename recorded in
        # the ledger, the rerun keeps the persisted path instead of
        # regenerating the spec at the recomputed location.
        self.migrate(apply=True)
        old_dir = self.repo / ".agents/project-harness/specs/intent-INT-20260902-crash"
        new_dir = self.repo / ".agents/project-harness/specs/intent-INT-20260902-renamed"
        old_dir.rename(new_dir)
        ledger_path = self.repo / mu.INTENT_LEDGER_REL
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        for entry in ledger["entries"]:
            if entry["spec"] == ".agents/project-harness/specs/intent-INT-20260902-crash/spec.md":
                entry["spec"] = ".agents/project-harness/specs/intent-INT-20260902-renamed/spec.md"
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = self.migrate(apply=True)
        self.assertEqual(result["conflicts"], [])
        self.assertIn(".agents/project-harness/specs/intent-INT-20260902-renamed/spec.md", result["skipped"])
        self.assertFalse(old_dir.exists())
        self.assertTrue((new_dir / "spec.md").is_file())
        mu.verify_intent_spec_layout(self.repo)


if __name__ == "__main__":
    unittest.main()
