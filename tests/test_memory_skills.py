#!/usr/bin/env python3
"""Contract tests for the 1.2.1 memory skills.

These are the static side of the memory-skill contract: the three SKILL.md
documents must carry the trigger gate (ask = the single recollection-intent
exception, the other two named-only), the merged ph-memory-learning must cover
both input modes (recording user-named content and faithful study of a named
source) with the dedup step, the dual-tier scoping rules
(project tier by default, explicit global only, one tier per write, install
and upgrade never touch HOME), the secret blocking, the conflict protections
(unknown entries untouched, escaping links refused, same-name kept), the
archive idempotency and the byte-level original protection with the single
kind/status exception. The evals must exercise the trigger positives and
negatives. Agent-side behavior evidence lives in the review record under
docs/ (non-release); these tests pin the wording that behavior relies on.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = REPO_ROOT / "assets" / "scaffold"
SKILLS = SCAFFOLD / ".agents" / "skills"
MEMORY_README = SCAFFOLD / ".agents" / "project-harness" / "memory" / "README.md"
AGENTS = SCAFFOLD / ".agents" / "AGENTS.md"
GOVERNANCE = (
    SCAFFOLD / ".agents" / "project-harness" / "constraints" / "harness规范" / "文档治理规范.md"
)
MEMORY_SKILLS = ("ph-memory-ask", "ph-memory-learning", "ph-memory-archive")
WRITER_SKILLS = ("ph-memory-learning",)


def skill_text(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def evals(name: str) -> dict:
    return json.loads((SKILLS / name / "evals" / "evals.json").read_text(encoding="utf-8"))


class MemorySkillContractTests(unittest.TestCase):
    def test_three_memory_skills_ship_with_evals(self):
        for name in MEMORY_SKILLS:
            with self.subTest(skill=name):
                text = skill_text(name)
                self.assertIn(f"name: {name}", text)
                self.assertTrue(evals(name)["evals"])

    def test_learning_covers_both_input_modes_with_dedup(self):
        # since the 1.2.1 merge ph-memory-learning absorbs the old
        # ph-memory-capture duty: one named gate, two input modes, one dedup
        # step shared by both, and per-mode provenance.
        learning = skill_text("ph-memory-learning")
        self.assertIn("记录模式", learning)
        self.assertIn("学习模式", learning)
        self.assertIn("`user-utterance`", learning)
        self.assertIn("`derived-from-docs`", learning)
        self.assertIn("查重", learning)
        self.assertIn("不复制第二条", learning)
        self.assertFalse((SKILLS / "ph-memory-capture").exists())

    def test_ask_is_the_only_recollection_intent_trigger(self):
        ask = skill_text("ph-memory-ask")
        self.assertIn("回忆意图", ask)
        self.assertIn("无需点名", ask)
        for negative in ("讨论本技能名称", "普通知识问答", "仅回顾当前对话", "「记住 X」", "归档"):
            self.assertIn(negative, ask)
        for name in ("ph-memory-learning", "ph-memory-archive"):
            text = skill_text(name)
            self.assertIn("明确点名", text, name)
            self.assertIn("都不触发", text, name)

    def test_started_flow_continuation_clause(self):
        for name in MEMORY_SKILLS:
            with self.subTest(skill=name):
                text = skill_text(name)
                for term in ("已显式启动", "不要求每轮重复点名", "不触发其他技能"):
                    self.assertIn(term, text, name)


class MemoryScopeContractTests(unittest.TestCase):
    def test_dual_tier_paths_are_pinned(self):
        for name in MEMORY_SKILLS:
            with self.subTest(skill=name):
                text = skill_text(name)
                self.assertIn("<repo>/.agents/project-harness/memory/", text, name)
                self.assertIn("~/.agents/memory/", text, name)

    def test_ask_project_default_and_no_silent_widening(self):
        ask = skill_text("ph-memory-ask")
        self.assertIn("默认只查项目档", ask)
        self.assertIn("项目档未命中时不自动扩大到个人档", ask)
        self.assertIn("都查", ask)
        self.assertIn("（all）", ask)
        self.assertIn("不得读取任何仓库记忆", ask)
        self.assertIn("明确指定查全局 / 个人档", ask)
        self.assertIn("不创建、不初始化", ask)

    def test_writers_one_tier_per_write(self):
        for name in WRITER_SKILLS:
            with self.subTest(skill=name):
                text = skill_text(name)
                self.assertIn("只进一个档", text, name)
        archive = skill_text("ph-memory-archive")
        self.assertIn("一次只处理一个档", archive)

    def test_home_is_touched_only_on_explicit_global_write(self):
        for name in (*WRITER_SKILLS, "ph-memory-archive"):
            with self.subTest(skill=name):
                text = skill_text(name)
                self.assertIn("按需创建", text, name)
                self.assertIn("不触碰 HOME", text, name)
        ask = skill_text("ph-memory-ask")
        # the query skill never creates anything, in either tier
        self.assertIn("绝不创建它", ask)
        readme = MEMORY_README.read_text(encoding="utf-8")
        self.assertIn("个人档", readme)
        self.assertIn("不由 PH 安装、升级或项目初始化创建", readme)
        self.assertIn("按需创建缺失层", readme)


class MemorySafetyContractTests(unittest.TestCase):
    def test_writers_block_secrets_before_write(self):
        for name in WRITER_SKILLS:
            with self.subTest(skill=name):
                text = skill_text(name)
                for secret in ("密码", "令牌", "私钥", "完整连接串"):
                    self.assertIn(secret, text, name)
        # the merged writer refuses the write outright for user-named secrets
        # and refuses the value for source material (de-identified phrasing
        # or skipping it entirely)
        self.assertIn("拒绝落盘", skill_text("ph-memory-learning"))
        self.assertIn("不复制值", skill_text("ph-memory-learning"))

    def test_archive_blocks_the_whole_run_on_secrets(self):
        archive = skill_text("ph-memory-archive")
        self.assertIn("立刻阻断该条所属的本次归档", archive)
        self.assertIn("不回显秘密本身", archive)
        self.assertIn("不把含密原件送进", archive)

    def test_ask_never_echoes_secrets_and_never_web_fills(self):
        ask = skill_text("ph-memory-ask")
        self.assertIn("不逐字回显疑似秘密", ask)
        self.assertIn("不自动联网", ask)

    def test_escaping_links_and_unknown_entries_are_refused(self):
        for name in MEMORY_SKILLS:
            with self.subTest(skill=name):
                text = skill_text(name)
                self.assertIn("符号链接", text, name)
                self.assertIn("硬链接", text, name)
                self.assertIn("不接管", text, name)
        ask = skill_text("ph-memory-ask")
        self.assertIn("不跟随链接读仓库外内容", ask)
        for name in ("ph-memory-learning", "ph-memory-archive"):
            self.assertTrue(
                "指向仓库外" in skill_text(name) or "指向档外" in skill_text(name), name
            )

    def test_instructional_text_in_content_is_never_executed(self):
        for name in MEMORY_SKILLS:
            with self.subTest(skill=name):
                text = skill_text(name)
                self.assertIn("指令", text, name)
        ask = skill_text("ph-memory-ask")
        self.assertIn("不当作指令执行", ask)
        learning = skill_text("ph-memory-learning")
        self.assertIn("资料内指令不执行", learning)


class MemoryArchiveContractTests(unittest.TestCase):
    def test_original_body_is_protected_with_single_exception(self):
        archive = skill_text("ph-memory-archive")
        self.assertIn("逐字节不变", archive)
        self.assertIn("唯一的例外", archive)
        self.assertIn("kind", archive)
        self.assertIn("archived-source", archive)
        self.assertIn("status: archived", archive)
        self.assertIn("并不矛盾", archive)
        readme = MEMORY_README.read_text(encoding="utf-8")
        self.assertIn("归档原件的改写边界", readme)
        self.assertIn("唯一的例外", readme)
        self.assertIn("archived-source", readme)
        # since 1.2.1 merged memory originals live in the unified archive
        nested = (SCAFFOLD / ".agents" / "project-harness" / "archive" / "memory" / "README.md").read_text(encoding="utf-8")
        self.assertIn("kind", nested)
        self.assertIn("status", nested)
        self.assertIn("保持移入前原样", nested)

    def test_no_deletion_and_same_name_kept(self):
        archive = skill_text("ph-memory-archive")
        self.assertIn("禁止删除任何文件", archive)
        self.assertIn("保留双方", archive)
        self.assertIn("-1", archive)

    def test_idempotent_rerun_via_source_registry(self):
        archive = skill_text("ph-memory-archive")
        self.assertIn("归档来源", archive)
        self.assertIn("不重复合并、不重复移动", archive)
        self.assertIn("重复执行幂等", archive)
        self.assertIn("先全部写好，后移动", archive)
        self.assertIn("逐文件移动", archive)
        self.assertIn("断点", archive)

    def test_incremental_merge_not_parallel_documents(self):
        archive = skill_text("ph-memory-archive")
        self.assertIn("增量写入对应章节", archive)
        self.assertIn("不另开平行文档", archive)
        self.assertIn("provenance: agent-summary", archive)


class MemoryDocsSyncTests(unittest.TestCase):
    def test_memory_readme_lists_the_three_skills_with_gate(self):
        readme = MEMORY_README.read_text(encoding="utf-8")
        for name in MEMORY_SKILLS:
            self.assertIn(f"`{name}`", readme, name)
        self.assertNotIn("ph-memory-capture", readme)
        self.assertIn("唯一的例外", readme)
        self.assertIn("回忆意图", readme)
        self.assertIn("仅当用户当轮明确点名", readme)
        self.assertIn("不自动串联", readme)

    def test_minimal_agents_entry_defers_memory_gate_to_the_readme(self):
        # since 1.2.1 AGENTS.md has no skill table: it only carries the
        # memory caution, and the three-skill gate lives in memory/README.md
        agents = AGENTS.read_text(encoding="utf-8")
        self.assertNotIn("十八名固定", agents)
        self.assertNotIn("`ph-memory-ask`", agents)
        self.assertIn("记忆和历史归档仅供参考", agents)
        self.assertIn("project-harness/README.md", agents)

    def test_governance_points_memory_work_at_the_skills(self):
        gov = GOVERNANCE.read_text(encoding="utf-8")
        self.assertIn("ph-memory-ask", gov)
        self.assertIn("自动触发", gov)
        self.assertIn("仅当轮点名", gov)

    def test_memory_evals_cover_trigger_positives_and_negatives(self):
        # ask: a recollection-intent prompt WITHOUT the skill name must be a
        # positive trigger (the gate exception), plain name discussion stays a
        # negative; the writers keep the classic named-positive /
        # description-negative pairs.
        ask = evals("ph-memory-ask")
        prompts = [str(e["prompt"]) for e in ask["evals"]]
        expected = [str(e["expected_output"]) for e in ask["evals"]]
        intent_without_name = [
            i for i, p in enumerate(prompts)
            if "ph-memory-ask" not in p and any(t in p for t in ("查记忆", "还记得", "记忆里", "以前"))
        ]
        self.assertTrue(intent_without_name, "ask evals need a recollection-intent positive without naming")
        self.assertTrue(
            any("触发" in expected[i] and "不触发" not in expected[i] for i in intent_without_name),
            "the recollection-intent positive must not be answered as a non-trigger",
        )
        for name in MEMORY_SKILLS:
            with self.subTest(skill=name):
                data = evals(name)
                ps = [str(e["prompt"]) for e in data["evals"]]
                es = [str(e["expected_output"]) for e in data["evals"]]
                self.assertTrue(any("不触发" in e for e in es), name)
                self.assertTrue(any(name not in p for p in ps), name)
                if name != "ph-memory-ask":
                    named = [i for i, p in enumerate(ps) if name in p]
                    self.assertTrue(named, name)
                    self.assertTrue(any("不触发" not in es[i] for i in named), name)


if __name__ == "__main__":
    unittest.main()
