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
description carries that clarification (since 1.2.1 the minimal AGENTS.md
has no skill table, and the memory README restates the memory-skill gate).

The retired ph-intent-verify contract half was removed with the 1.1.14
skill-set reduction; intent acceptance rules now live in 意图与访谈.md.
Since 1.1.16 there is exactly one second exception: ph-memory-ask triggers
on the user's recollection intent in the current turn without being named
("查记忆", "你还记得吗", ...); naming it still works, but plain "记住 /
学习 / 归档" requests, name discussions, and skill chaining never trigger
any memory skill.

Since 1.2.3 the ten SDD development skills (ph-require ... ph-archive)
ship inside the scaffold with English descriptions; the same gate is
asserted semantically in whichever language a description carries. The
required skill list has a single source: release.json's required_skills
(the retired speckit.json is gone and no second hand-maintained count is
allowed).
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
# release.json is the single source for the required skill list; the eight
# PH scaffold skills (1.2.2 adds ph-human) plus the ten SDD skills ship in
# the scaffold. No second hand-maintained count is allowed.
REQUIRED = json.loads((REPO_ROOT / "release.json").read_text(encoding="utf-8"))["required_skills"]
assert REQUIRED[0] == "ph-init"

# English-language gate anchors (semantic contract, not style): the
# Chinese equivalents are 明确点名 / 不触发 / 已显式启动…不要求每轮重复点名 /
# 不自动调用其他技能.
EN_GATE_ANCHORS = ("explicitly names", "not trigger")
EN_CONTINUATION_ANCHORS = ("explicitly started", "without repeated naming")
EN_NO_CHAIN_ANCHOR = "automatically invoke"


def frontmatter(text: str) -> str:
    assert text.startswith("---\n"), text[:40]
    return text.split("---", 2)[1]


def description(path: Path) -> str:
    for line in frontmatter(path.read_text(encoding="utf-8")).splitlines():
        if line.startswith("description:"):
            return line
    return ""


def is_english_description(desc_line: str) -> bool:
    return "explicitly names" in desc_line


def frontmatter(text: str) -> str:
    assert text.startswith("---\n"), text[:40]
    return text.split("---", 2)[1]


class ExplicitInvocationGateTests(unittest.TestCase):
    def test_scaffold_skills_present(self):
        self.assertEqual(sorted(ALL_SKILL_PATHS), sorted(REQUIRED))

    def test_every_description_carries_the_gate(self):
        for name, path in ALL_SKILL_PATHS.items():
            with self.subTest(skill=name):
                desc_line = description(path)
                self.assertTrue(desc_line, f"{name}: no description line")
                if name == "ph-memory-ask":
                    # The one recollection-intent exception: the query skill
                    # triggers on intent without being named.
                    self.assertIn("回忆意图", desc_line, name)
                    self.assertIn("无需点名", desc_line, name)
                elif is_english_description(desc_line):
                    for anchor in EN_GATE_ANCHORS:
                        self.assertIn(anchor, desc_line, name)
                else:
                    self.assertIn("明确点名", desc_line, name)
                self.assertIn("不触发" if not is_english_description(desc_line) else "not trigger", desc_line, name)

    def test_memory_ask_query_intent_is_the_only_memory_exception(self):
        # The 1.1.16 memory skills keep the name-it gate except for the ask
        # query: recollection intent triggers it, plain 记住/学习/归档 and
        # name discussions never trigger any memory skill, and the scaffold
        # constraints state the exception centrally.
        ask = (SKILLS / "ph-memory-ask" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("回忆意图", ask)
        self.assertIn("无需点名", ask)
        for term in ("「记住 X」", "学习", "归档"):
            self.assertIn(term, ask)
        for name in ("ph-memory-learning", "ph-memory-archive"):
            text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("明确点名", text, name)
            self.assertIn("都不触发", text, name)
        # since 1.2.1 the central statement lives in the memory README (the
        # minimal AGENTS.md no longer carries a skill table)
        memory = (SCAFFOLD / ".agents/project-harness/memory/README.md").read_text(encoding="utf-8")
        self.assertIn("ph-memory-ask", memory)
        self.assertIn("无需点名", memory)
        self.assertIn("任何记忆技能", memory)
        self.assertIn("不自动串联", memory)

    def test_started_flow_continuation_does_not_require_renaming(self):
        # The entry gate governs entry only: once a flow was explicitly
        # started, user answers and "continue" belong to that same flow.
        clause_terms = ("已显式启动", "不要求每轮重复点名", "不触发其他技能")
        for name, path in ALL_SKILL_PATHS.items():
            with self.subTest(skill=name):
                desc_line = description(path)
                if is_english_description(desc_line):
                    for anchor in EN_CONTINUATION_ANCHORS + (EN_NO_CHAIN_ANCHOR,):
                        self.assertIn(anchor, desc_line, name)
                    continue
                for term in clause_terms:
                    self.assertIn(term, desc_line, name)
        # the same rule is stated centrally in the memory README for the
        # memory skills, and every skill description repeats it
        memory = (SCAFFOLD / ".agents/project-harness/memory/README.md").read_text(encoding="utf-8")
        self.assertIn("已显式启动", memory)
        self.assertIn("不要求每轮重复点名", memory)
        wexit = (SKILLS / "ph-worktree-exit" / "SKILL.md").read_text(encoding="utf-8")
        for anchor in EN_CONTINUATION_ANCHORS + (EN_NO_CHAIN_ANCHOR,):
            self.assertIn(anchor, wexit)

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
        # Either language carries the contract; 1.2.3 rewrote both files in
        # English ("internal steps"), older texts said 内部步骤.
        root = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("merge-update", root)
        merge = (SKILLS / "ph-merge-update" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-init", merge)
        self.assertTrue(
            "内部步骤" in merge + root or "internal steps" in merge + root,
            "the init-internal merge-update reading exception is not stated",
        )

    def test_boundary_pointers_name_skills_without_deriving_calls(self):
        # Boundaries may point at the right skill, but the release must not
        # instruct one skill to invoke another.
        merge = (SKILLS / "ph-merge-update" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-init", merge)
        self.assertTrue("明确点名" in merge or "explicitly names" in merge, "merge-update gate wording missing")
        enter = (SKILLS / "ph-worktree-enter" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-worktree-exit", enter)
        self.assertTrue("明确点名" in enter or "explicitly names" in enter, "worktree-enter gate wording missing")

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
