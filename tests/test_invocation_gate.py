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

The retired ph-intent-verify contract half was removed with the 1.1.14
skill-set reduction; intent acceptance rules now live in 意图与访谈.md.
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
# The four PH scaffold skills; the ten spec-kit skills live in .agents/skills
# only after an install runs the pinned upstream generator (no scaffold copy).
REQUIRED = [
    "ph-init", "ph-merge-update", "ph-worktree-enter", "ph-worktree-exit",
]


def frontmatter(text: str) -> str:
    assert text.startswith("---\n"), text[:40]
    return text.split("---", 2)[1]


class ExplicitInvocationGateTests(unittest.TestCase):
    def test_scaffold_skills_present(self):
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
        wexit = (SKILLS / "ph-worktree-exit" / "SKILL.md").read_text(encoding="utf-8")
        for term in clause_terms:
            self.assertIn(term, wexit)

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
        merge = (SKILLS / "ph-merge-update" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-init", merge)
        self.assertIn("明确点名", merge)
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
