#!/usr/bin/env python3
"""Explicit-invocation gate and user-acceptance skill contract tests.

The gate is a distribution-wide wording contract: every PH skill is invoked
only when the user explicitly names it in the current turn and asks for it;
plain need descriptions, context mentions, and skill-name discussions never
trigger, and skills never derive each other's invocation. The one documented
internal step (the ph-init session reading the release-root merge-update
steps for an upgrade the user already requested) stays allowed. The gate
covers entry only: inside an already explicitly started flow, user answers
and "continue" are received and resumed by that same flow without repeating
the skill name each turn and without triggering other skills; every skill
description and the scaffold project constraints carry that clarification.

The second half pins the ph-intent-verify acceptance contract: one
acceptance point per round, user feedback via real question tools with the
shared-norm degradation when no tool exists or an open question cannot be
expressed in the tool format, agent self-tests never count as acceptance,
a user-visible entry counts as "opened" only with real successful-open
evidence (actually opening the feature when the host can and it is
authorized, never a bare link), the overall conclusion summarizes per-point
states (pass only when every point passes), failure evidence with
reproduction, pause/resume, read-only behavior, environment blockers, and
the four-state conclusion written into the intent's existing 记录 section.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = REPO_ROOT / "assets" / "scaffold"
SKILLS = SCAFFOLD / ".agents" / "skills"
ALL_SKILL_PATHS = {
    "ph-init": REPO_ROOT / "SKILL.md",
    **{p.parent.name: p for p in sorted(SKILLS.glob("*/SKILL.md"))},
}
REQUIRED = [
    "ph-init", "ph-worktree-enter", "ph-worktree-exit",
    "ph-memory-capture", "ph-memory-archive", "ph-memory-ask",
    "ph-intent-new", "ph-intent-impl", "ph-intent-verify", "ph-intent-drop",
    "ph-merge-update", "ph-docs-sync", "ph-sure",
]


def frontmatter(text: str) -> str:
    assert text.startswith("---\n"), text[:40]
    return text.split("---", 2)[1]


class ExplicitInvocationGateTests(unittest.TestCase):
    def test_thirteen_skills_present(self):
        self.assertEqual(sorted(ALL_SKILL_PATHS), sorted(REQUIRED))

    def test_every_description_carries_the_gate(self):
        for name, path in ALL_SKILL_PATHS.items():
            with self.subTest(skill=name):
                text = path.read_text(encoding="utf-8")
                description = ""
                for line in frontmatter(text).splitlines():
                    if line.startswith("description:"):
                        description = line
                        break
                self.assertIn("明确点名", description, name)
                self.assertIn("不触发", description, name)

    def test_started_flow_continuation_does_not_require_renaming(self):
        # The entry gate governs entry only: once a flow was explicitly
        # started, user answers and "continue" belong to that same flow.
        clause_terms = ("已显式启动", "不要求每轮重复点名", "不触发其他技能")
        for name, path in ALL_SKILL_PATHS.items():
            with self.subTest(skill=name):
                text = path.read_text(encoding="utf-8")
                description = ""
                for line in frontmatter(text).splitlines():
                    if line.startswith("description:"):
                        description = line
                        break
                for term in clause_terms:
                    self.assertIn(term, description, name)
        # the same rule is stated centrally in the scaffold project constraints,
        # and the verify body gate (the multi-round acceptance flow) repeats it
        agents = (SCAFFOLD / ".agents" / "AGENTS.md").read_text(encoding="utf-8")
        for term in clause_terms:
            self.assertIn(term, agents)
        verify = (SKILLS / "ph-intent-verify" / "SKILL.md").read_text(encoding="utf-8")
        gate = verify.split("## 调用门禁", 1)[1].split("\n## ", 1)[0]
        for term in clause_terms:
            self.assertIn(term, gate)

    def test_auto_trigger_and_auto_chain_wording_removed(self):
        banned = [
            # description-level "describe-the-need triggers" phrasing
            "——即使没点名本技能——都必须使用",
            "——即使没说出归档二字——都必须使用",
            "或调用 ph-worktree-exit，都必须使用本技能",
            "“ph-init”“bootstrap harness”时必须使用",
            # body-level auto chaining
            "完成时调用 `ph-worktree-exit`",
            "启动推进属于 `ph-intent-impl`",
            "或调用 `ph-worktree-enter`",
        ]
        for name, path in ALL_SKILL_PATHS.items():
            with self.subTest(skill=name):
                text = path.read_text(encoding="utf-8")
                for phrase in banned:
                    self.assertNotIn(phrase, text, f"{name}: {phrase}")

    def test_internal_upgrade_step_wording_is_kept(self):
        # The one allowed derivation: the ph-init session executing an
        # already-requested upgrade reads the release-root merge-update steps.
        root = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("merge-update", root)
        merge = (SKILLS / "ph-merge-update" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-init", merge)
        self.assertIn("内部步骤", merge + root)

    def test_boundary_pointers_name_skills_without_deriving_calls(self):
        # Boundaries may point at the right skill, but the release must not
        # instruct one skill to invoke another.
        impl = (SKILLS / "ph-intent-impl" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-worktree-enter", impl)
        self.assertIn("明确点名", impl)
        enter = (SKILLS / "ph-worktree-enter" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-worktree-exit", enter)
        self.assertIn("明确点名", enter)

    def test_evals_cover_trigger_positive_and_negative(self):
        for name, path in ALL_SKILL_PATHS.items():
            eval_path = (
                path.parent / "evals" / "evals.json"
                if name != "ph-init"
                else REPO_ROOT / "evals" / "evals.json"
            )
            with self.subTest(skill=name):
                data = json.loads(eval_path.read_text(encoding="utf-8"))
                self.assertEqual(data["skill_name"], name)
                prompts = [str(e["prompt"]) for e in data["evals"]]
                expected = [str(e["expected_output"]) for e in data["evals"]]
                # positive: an explicitly named request is answered as a trigger
                named = [i for i, p in enumerate(prompts) if name in p]
                self.assertTrue(named, f"{name}: no eval names the skill")
                self.assertTrue(
                    any("不触发" not in expected[i] for i in named),
                    f"{name}: no named-skill positive trigger",
                )
                # negative: a plain description or name discussion does not trigger
                self.assertTrue(
                    any("不触发" in e for e in expected),
                    f"{name}: no non-trigger negative",
                )
                self.assertTrue(
                    any(name not in p for p in prompts),
                    f"{name}: every eval names the skill; no description-only negative",
                )


class IntentVerifyAcceptanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (SKILLS / "ph-intent-verify" / "SKILL.md").read_text(encoding="utf-8")
        cls.evals = json.loads(
            (SKILLS / "ph-intent-verify" / "evals" / "evals.json").read_text(encoding="utf-8")
        )

    def section(self, title: str) -> str:
        self.assertIn(f"## {title}", self.text, title)
        after = self.text.split(f"## {title}", 1)[1]
        return after.split("\n## ", 1)[0]

    def test_step_by_step_rounds_and_real_question_tools(self):
        step = self.section("逐步验收")
        for term in ("一轮只验收一个点", "验证什么", "在哪操作", "输入什么", "预期",
                     "问答工具", "等待回答"):
            self.assertIn(term, step)
        gate = self.section("调用门禁")
        self.assertIn("自测", gate)
        self.assertIn("预检", gate)
        self.assertIn("取消", gate)
        self.assertIn("沉默", gate)

    def test_question_tool_degradation_follows_shared_norm(self):
        # No claim that every host must ship a question tool: when the host
        # truly has none, fails irrecoverably, or the format cannot express
        # an open question, the shared norm's text fallback applies.
        step = self.section("逐步验收")
        for term in ("没有问答工具", "开放", "可见文字", "等待回答", "不声称已通过工具提问"):
            self.assertIn(term, step)
        self.assertNotIn("必须有问答工具", self.text)
        self.assertNotIn("必有问答工具", self.text)

    def test_four_state_conclusion_requires_user_confirmation(self):
        text = self.text
        self.assertIn("通过 / 不通过 / 阻断 / 未验收", text)
        self.assertIn("整体", text)
        self.assertIn("真实确认", text)
        # the overall conclusion summarizes per-point states; no severity ranking
        step = self.section("逐步验收")
        self.assertIn("整体结论由逐项状态汇总", step)
        self.assertIn("整体通过", step)
        self.assertIn("整体不通过", step)
        self.assertNotIn("最严重", text)

    def test_failure_evidence_without_auto_fixing(self):
        fail = self.section("失败与恢复")
        for term in ("复现", "证据", "不自动修代码", "不调用其他技能", "恢复"):
            self.assertIn(term, fail)

    def test_read_only_and_pause_resume(self):
        record = self.section("记录")
        self.assertIn("只读", record)
        self.assertIn("待归档、未写入项目", record)
        self.assertIn("中断恢复", self.text)

    def test_record_goes_to_existing_intent_section_without_new_states(self):
        record = self.section("记录")
        for term in ("「记录」", "不新建状态、目录或纪要 purpose", "frontmatter"):
            self.assertIn(term, record)
        # the intent stays in 实施: verify never moves or re-classifies
        locate = self.section("定位与核对")
        self.assertIn("实施", locate)
        self.assertNotIn("status_dir: ", record)

    def test_environment_reuse_and_blockers(self):
        env = self.section("环境准备")
        for term in ("复用", "不擅自重启", "安装", "改配置", "阻断"):
            self.assertIn(term, env)
        self.assertIn("生产", env)

    def test_real_user_visible_entry_no_faked_opening(self):
        show = self.section("展示真实入口")
        for term in ("隔离浏览器", "可访问的地址不等于已打开", "打开操作返回成功",
                     "实际打开", "不只给一个链接", "假称打开", "非网页"):
            self.assertIn(term, show)

    def test_boundaries_no_commit_push_branch_worktree_or_other_skills(self):
        edge = self.section("边界")
        for term in ("commit", "push", "worktree", "发布", "template_version", "不自动调用"):
            self.assertIn(term, edge)

    def test_evals_cover_acceptance_behaviors(self):
        blob = json.dumps(self.evals, ensure_ascii=False)
        for topic in ("验收点", "不通过", "恢复", "只读", "阻断", "环境", "隔离浏览器", "记录",
                      # fixed-review behaviors: open evidence, no-tool degradation,
                      # overall summary, continuation without re-naming
                      "已打开", "不只给一个链接", "不声称已通过工具提问",
                      "汇总", "不要求重复点名"):
            self.assertIn(topic, blob, topic)
        prompts = [str(e["prompt"]) for e in self.evals["evals"]]
        expected = [str(e["expected_output"]) for e in self.evals["evals"]]
        self.assertTrue(any("ph-intent-verify" not in p and "不触发" in e for p, e in zip(prompts, expected)))
        self.assertTrue(any("不通过" in e for e in expected))
        self.assertTrue(any("阻断" in e for e in expected))
        self.assertTrue(any("未验收" in e or "跳过" in e for e in expected))
        self.assertTrue(any("隔离浏览器" in e for e in expected))
        # continuation sample: an unnamed follow-up handled by the started flow
        self.assertTrue(any("ph-intent-verify" not in p and "不要求重复点名" in e
                            for p, e in zip(prompts, expected)))


if __name__ == "__main__":
    unittest.main()
