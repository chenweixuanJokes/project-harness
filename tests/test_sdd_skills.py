#!/usr/bin/env python3
"""Contract tests for the bilingual skills rewritten for the SDD suite.

1.2.3 rewrote the development-suite skills in English and shipped a Chinese
companion file (SKILL.zh.md, 中文对照) next to each. Fifteen skills carry
both languages: the root ph-init entry, the seven changed and the seven new
scaffold skills. These tests pin the semantics that must survive any
rewording — never a total character count, never a full-sentence pin:

- the English description states the skill's responsibility (a few
  responsibility stems per skill) and the whole invocation gate, including
  the skill's own name;
- the Chinese companion exists, is a companion (no frontmatter of its own,
  so it never becomes an extra skill entry), carries the `<skill> 中文对照`
  heading and restates the same gate in Chinese;
- English skill texts reference no retired upstream Spec Kit engine
  artifact (directory, CLI, scripts, license);
- every relative markdown link resolves to a real file;
- artifact IDs (requirement.md, design.md, …) appear in both languages
  together: neither translation introduces or drops one.

The trigger positive/negative eval coverage lives in
test_invocation_gate.py; this file covers the language and reference
contract of the skill texts themselves.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = REPO_ROOT / "assets" / "scaffold"
SKILLS = SCAFFOLD / ".agents" / "skills"
PROCESS_EN = SKILLS / "ph-require" / "references" / "process.md"
PROCESS_ZH = SKILLS / "ph-require" / "references" / "process.zh.md"

# The explicit expected bilingual set: root ph-init plus every scaffold
# skill that ships SKILL.md + SKILL.zh.md. A skill losing a language file,
# or a translation accidentally becoming a new skill entry, fails here.
EXPECTED_BILINGUAL = [
    "ph-init",
    "ph-archive",
    "ph-clarify",
    "ph-design",
    "ph-design-review",
    "ph-human",
    "ph-implement",
    "ph-merge-update",
    "ph-require",
    "ph-small-change",
    "ph-tasks",
    "ph-verify",
    "ph-verify-plan",
    "ph-worktree-enter",
    "ph-worktree-exit",
]

# Responsibility stems each English description must state (checked
# case-insensitively as substrings; deliberately coarse so rewording
# survives as long as the responsibility is actually described).
DESCRIPTION_STEMS = {
    "ph-init": ["install", "upgrade", "synchronize"],
    "ph-merge-update": ["upgrade", "migration"],
    "ph-worktree-enter": ["isolated", "worktree", "register"],
    "ph-worktree-exit": ["deliver", "worktree", "verify"],
    "ph-human": ["companion"],
    "ph-require": ["requirement", "scope", "acceptance"],
    "ph-clarify": ["clarify", "requirement"],
    "ph-design": ["design", "behavior"],
    "ph-design-review": ["review", "design", "requirement"],
    "ph-tasks": ["tasks", "unit tests"],
    "ph-verify-plan": ["self-test", "acceptance"],
    "ph-small-change": ["bug fix", "concise"],
    "ph-implement": ["tasks", "unit tests"],
    "ph-verify": ["verification", "user outcome acceptance", "repair tasks"],
    "ph-archive": ["archive", "documentation", "smoke cases"],
}

# The four gate clauses in their English and Chinese wordings. The English
# description must contain the skill's own name right after "explicitly
# names"; the Chinese companion carries the same clauses.
EN_GATE_NAMED = "explicitly names {name}"
EN_GATE_TRIGGERS = "not trigger"
EN_GATE_CONTINUATION = "without repeated naming"
EN_GATE_NO_CHAIN = "automatically invoke"
ZH_GATE_CLAUSES = ("明确点名", "不触发", "不要求重复点名", "不自动调用其他技能")

# Retired upstream Spec Kit engine artifacts must not return in English
# skill texts; a prose mention of independence (e.g. "does not depend on
# upstream Spec Kit") does not contain these tokens.
BANNED_UPSTREAM_TOKENS = [
    ".specify",
    "speckit",
    "spec-kit",
    "specify init",
    "scripts/bash",
    "setup-plan",
    "setup-tasks",
    "check-prerequisites",
    "create-new-feature",
    "resolve-template",
]

# The artifact ID set from the development contract's responsibility table
# (including the legacy mapped sources). Presence must match across the
# English text and its Chinese companion.
ARTIFACT_IDS = [
    "requirement.md",
    "design.md",
    "review.md",
    "tasks.md",
    "verify-plan.md",
    "acceptance.md",
    "verification.md",
    "change.md",
    "spec.md",
    "plan.md",
]

LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def skill_pair(name: str) -> tuple[Path, Path]:
    en = REPO_ROOT / "SKILL.md" if name == "ph-init" else SKILLS / name / "SKILL.md"
    zh = REPO_ROOT / "SKILL.zh.md" if name == "ph-init" else SKILLS / name / "SKILL.zh.md"
    return en, zh


def frontmatter_field(text: str, field: str) -> str:
    body = text.split("---", 2)[1]
    for line in body.splitlines():
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def description_value(path: Path) -> str:
    return frontmatter_field(path.read_text(encoding="utf-8"), "description")


def mentions_artifact(text: str, artifact: str) -> bool:
    pattern = r"(?<![A-Za-z0-9-])" + re.escape(artifact) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text) is not None


class BilingualSddSkillTests(unittest.TestCase):
    def test_bilingual_set_matches_release(self):
        derived = [
            d.name
            for d in sorted(SKILLS.iterdir())
            if (d / "SKILL.md").is_file() and (d / "SKILL.zh.md").is_file()
        ]
        if (REPO_ROOT / "SKILL.md").is_file() and (REPO_ROOT / "SKILL.zh.md").is_file():
            derived.append("ph-init")
        self.assertEqual(sorted(derived), sorted(EXPECTED_BILINGUAL))
        for name in EXPECTED_BILINGUAL:
            with self.subTest(skill=name):
                en, zh = skill_pair(name)
                self.assertTrue(en.is_file(), name)
                self.assertTrue(zh.is_file(), name)

    def test_english_description_states_responsibility_and_gate(self):
        for name in EXPECTED_BILINGUAL:
            with self.subTest(skill=name):
                en, _ = skill_pair(name)
                text = en.read_text(encoding="utf-8")
                self.assertEqual(frontmatter_field(text, "name"), name)
                desc = description_value(en)
                self.assertTrue(desc, f"{name}: empty description")
                for stem in DESCRIPTION_STEMS[name]:
                    self.assertIn(stem, desc.lower(), f"{name}: missing responsibility stem {stem!r}")
                self.assertIn(EN_GATE_NAMED.format(name=name), desc, name)
                self.assertIn(EN_GATE_TRIGGERS, desc, name)
                self.assertIn(EN_GATE_CONTINUATION, desc, name)
                self.assertIn(EN_GATE_NO_CHAIN, desc, name)

    def test_chinese_companion_carries_gate_and_is_not_an_entry(self):
        for name in EXPECTED_BILINGUAL:
            with self.subTest(skill=name):
                _, zh = skill_pair(name)
                text = zh.read_text(encoding="utf-8")
                # a companion, not an extra skill entry: no frontmatter
                self.assertFalse(text.startswith("---"), name)
                self.assertTrue(
                    text.splitlines() and text.splitlines()[0].strip() == f"# {name} 中文对照",
                    f"{name}: missing 中文对照 heading",
                )
                for clause in ZH_GATE_CLAUSES:
                    self.assertIn(clause, text, f"{name}: missing zh gate clause {clause}")

    def test_english_texts_have_no_retired_upstream_engine(self):
        targets = {name: skill_pair(name)[0] for name in EXPECTED_BILINGUAL}
        targets["ph-require/references/process.md"] = PROCESS_EN
        for label, path in targets.items():
            with self.subTest(text=label):
                lowered = path.read_text(encoding="utf-8").lower()
                for token in BANNED_UPSTREAM_TOKENS:
                    self.assertNotIn(token, lowered, f"{label}: upstream token {token!r}")

    def test_markdown_links_resolve_to_real_files(self):
        targets: list[Path] = []
        for name in EXPECTED_BILINGUAL:
            en, zh = skill_pair(name)
            targets += [en, zh]
        targets += [PROCESS_EN, PROCESS_ZH]
        for path in targets:
            text = path.read_text(encoding="utf-8")
            for match in LINK_RE.finditer(text):
                target = match.group(1)
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                with self.subTest(file=str(path), link=target):
                    path_part = unquote(target.split("#")[0])
                    if not path_part:
                        continue
                    resolved = (path.parent / path_part).resolve()
                    self.assertTrue(resolved.is_file(), f"{path} -> {target}")

    def test_artifact_ids_consistent_across_languages(self):
        for name in EXPECTED_BILINGUAL:
            en_text = skill_pair(name)[0].read_text(encoding="utf-8")
            zh_text = skill_pair(name)[1].read_text(encoding="utf-8")
            with self.subTest(skill=name):
                for artifact in ARTIFACT_IDS:
                    self.assertEqual(
                        mentions_artifact(en_text, artifact),
                        mentions_artifact(zh_text, artifact),
                        f"{name}: artifact {artifact} language mismatch",
                    )


if __name__ == "__main__":
    unittest.main()
