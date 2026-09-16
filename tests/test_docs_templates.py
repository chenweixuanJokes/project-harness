"""Static coverage of the distributable initialization guide and wiki templates."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "assets/scaffold"
DOCS = SCAFFOLD / "docs"
ENGINEERING = DOCS / "约束规范/工程规范"


class DocsTemplateTests(unittest.TestCase):
    def test_engineering_guides_are_indexed_and_skill_reachable(self):
        index = (ENGINEERING / "README.md").read_text(encoding="utf-8")
        for name in ("初始化与文档补全.md", "安全与配置.md", "构建发布与运维.md"):
            self.assertTrue((ENGINEERING / name).is_file())
            self.assertIn(f"./{name}", index)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("assets/scaffold/docs/约束规范/工程规范/初始化与文档补全.md", skill)

    def test_workbook_test_cases_and_conditional_components_are_mapped(self):
        guide = (ENGINEERING / "初始化与文档补全.md").read_text(encoding="utf-8")
        self.assertIn("F29 / F31 / F33", guide)
        self.assertIn("F30 / F32 / F34", guide)
        for component in ("Kong", "Eureka", "Apollo"):
            self.assertIn(component, guide)
        self.assertIn("仅实际使用", guide)
        for topic in ("D39 完成", "D58 同步", "D59 纠正", "D60 问答", "D54 记忆纠正"):
            self.assertIn(topic, guide)

    def test_all_wiki_templates_keep_honest_governance_fields(self):
        for path in (DOCS / "项目Wiki").rglob("*.md"):
            if path.name == "README.md":
                continue
            with self.subTest(path=path.relative_to(DOCS)):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                frontmatter = text.split("---", 2)[1]
                for key in ("owner", "status", "last_verified", "verified_against", "refresh_trigger"):
                    self.assertRegex(frontmatter, rf"(?m)^{key}:")
                self.assertIn("status: draft", frontmatter)
                self.assertIn('last_verified: ""', frontmatter)
                self.assertIn('verified_against: ""', frontmatter)

    def test_each_docs_directory_indexes_direct_children(self):
        for directory in (DOCS, *(p for p in DOCS.rglob("*") if p.is_dir())):
            with self.subTest(directory=directory.relative_to(SCAFFOLD)):
                index = directory / "README.md"
                self.assertTrue(index.is_file())
                text = index.read_text(encoding="utf-8")
                links = re.findall(r"\]\(([^)]+)\)", text)
                targets = {(directory / link.split("#", 1)[0]).resolve()
                           for link in links if "://" not in link}
                for child in directory.iterdir():
                    if child.is_dir():
                        self.assertIn((child / "README.md").resolve(), targets)
                    elif child.suffix == ".md" and child != index:
                        self.assertIn(child.resolve(), targets)

    def test_docs_migration_keeps_single_version_contract(self):
        release = json.loads((ROOT / "release.json").read_text())
        self.assertEqual(release["version"], "1.1.13")
        self.assertNotIn("schema_version", release)  # single PH version since 1.1.8
        self.assertEqual(len(release["required_skills"]), 12)
        self.assertIn("ph-docs-sync", release["required_skills"])
        self.assertIn("ph-intent-verify", release["required_skills"])
        manifest = json.loads((SCAFFOLD / ".agents/ph.json").read_text())
        self.assertNotIn("schema_version", manifest)
        self.assertEqual(manifest["template_version"], "1.1.13")
        self.assertEqual(manifest["skills"]["required_names"], release["required_skills"])
        schema = json.loads((SCAFFOLD / ".agents/ph.schema.json").read_text())
        self.assertEqual(schema["$id"], "urn:ph:schema:project-harness")  # fixed, versionless
        self.assertNotIn("schema_version", schema.get("required", []))
        self.assertNotIn("schema_version", schema.get("properties", {}))
        hops = json.loads((ROOT / "migrations/index.json").read_text())["migrations"]
        hop = next(h for h in hops if h["from_version"] == "1.1.2")
        self.assertEqual(hop["items"], ["init-docs-workflow", "docs-guidance", "docs-project-preserve"])
        hop_118 = next(h for h in hops if h["from_version"] == "1.1.7")
        self.assertEqual(hop_118["to_version"], "1.1.8")
        self.assertEqual(hop_118["items"], ["single-ph-version"])
        hop_119 = next(h for h in hops if h["from_version"] == "1.1.8")
        self.assertEqual(hop_119["to_version"], "1.1.9")
        self.assertEqual(sorted(hop_119["items"]),
                         ["repository-rename", "tool-neutral-adapters", "worktree-auto-branch"])
        hop_1110 = next(h for h in hops if h["from_version"] == "1.1.9")
        self.assertEqual(hop_1110["to_version"], "1.1.10")
        self.assertEqual(hop_1110["items"], ["docs-sync-skill"])
        hop_1111 = next(h for h in hops if h["from_version"] == "1.1.10")
        self.assertEqual(hop_1111["to_version"], "1.1.11")
        self.assertEqual(hop_1111["items"], ["current-branch-defaults", "adopt-mode-docs"])
        hop_1112 = next(h for h in hops if h["from_version"] == "1.1.11")
        self.assertEqual(hop_1112["to_version"], "1.1.12")
        self.assertEqual(hop_1112["items"], ["question-execution-contract"])
        hop_1113 = next(h for h in hops if h["from_version"] == "1.1.12")
        self.assertEqual(hop_1113["to_version"], "1.1.13")
        self.assertEqual(hop_1113["items"], ["explicit-invocation-rules", "intent-verify-skill"])

    def test_single_ph_version_migration_documented(self):
        doc = (ROOT / "migrations/1.1.7-to-1.1.8.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("single-ph-version", "schema_version", "v1.1.8",
                     "新的仓外", "不覆盖", "finalize"):
            self.assertIn(term, doc)

    def test_worktree_auto_branch_migration_documented(self):
        doc = (ROOT / "migrations/1.1.8-to-1.1.9.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("worktree-auto-branch", "当前分支", "任务分支", "不再询问",
                     "--existing", "v1.1.8", "1.1.9"):
            self.assertIn(term, doc)

    def test_docs_sync_skill_migration_documented(self):
        doc = (ROOT / "migrations/1.1.9-to-1.1.10.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("docs-sync-skill", "ph-docs-sync", "1.1.9", "1.1.10",
                     "十一个必需 Skill", "不自动同步任何业务文档", "同名自定义 Skill",
                     "blocked", "adapter mode"):
            self.assertIn(term, doc)

    def test_question_execution_contract_migration_documented(self):
        doc = (ROOT / "migrations/1.1.11-to-1.1.12.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("question-execution-contract", "对用户提问", "执行契约", "1.1.11",
                     "1.1.12", "实际调用", "降级", "三个不同状态", "整文件覆盖",
                     "逐字节一致", "备份", "语义引用", "blocked", "adapter mode"):
            self.assertIn(term, doc)

    def test_invocation_and_verify_migration_documented(self):
        doc = (ROOT / "migrations/1.1.12-to-1.1.13.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("explicit-invocation-rules", "intent-verify-skill", "1.1.12",
                     "1.1.13", "ph-intent-verify", "明确点名", "普通描述", "讨论技能名称",
                     "自动串联", "ph-merge-update", "内部步骤", "记录", "不通过",
                     "阻断", "未验收", "隔离浏览器", "问答工具", "同名自定义",
                     "blocked", "adapter mode"):
            self.assertIn(term, doc)

    def test_docs_sync_skill_shipped_and_indexed(self):
        skill = SCAFFOLD / ".agents/skills/ph-docs-sync/SKILL.md"
        self.assertTrue(skill.is_file())
        text = skill.read_text(encoding="utf-8")
        for term in ("name: ph-docs-sync", "只读", "可直接证实", "近 7 天提交只",
                     "规范冲突不降级规范", "五字段", "不自动",
                     # command examples: full preconditions, static basis
                     "前置条件", "构建产物", "工作目录", "步骤依赖", "静态依据",
                     # config claims: name / configurability / default, no guessing
                     "可配置性", "默认值", "框架印象",
                     # evidence handling: search coverage, commit range, default scope
                     "搜索覆盖不足", "指定区间", "默认范围",
                     # post-repair diff and link re-check step
                     "diff 与链接复核"):
            self.assertIn(term, text)
        evals = json.loads(
            (SCAFFOLD / ".agents/skills/ph-docs-sync/evals/evals.json").read_text(encoding="utf-8")
        )
        self.assertEqual(evals["skill_name"], "ph-docs-sync")
        self.assertTrue(evals["evals"])
        # Governance and the completion guide register the skill instead of
        # denying its existence.
        governance = (ENGINEERING / "文档治理.md").read_text(encoding="utf-8")
        self.assertIn("ph-docs-sync", governance)
        self.assertIn("规则源", governance)
        self.assertNotIn("不是 Skill", governance)
        guide = (ENGINEERING / "初始化与文档补全.md").read_text(encoding="utf-8")
        self.assertIn("ph-docs-sync", guide)
        self.assertNotIn("无独立 Skill", guide)
        agents = (SCAFFOLD / ".agents/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("十二名固定", agents)
        self.assertIn("ph-docs-sync", agents)

    def test_intent_verify_skill_shipped_and_indexed(self):
        skill = SCAFFOLD / ".agents/skills/ph-intent-verify/SKILL.md"
        self.assertTrue(skill.is_file())
        text = skill.read_text(encoding="utf-8")
        for term in ("name: ph-intent-verify", "明确点名", "一轮", "验收点",
                     "通过 / 不通过 / 阻断 / 未验收", "记录", "只读", "隔离浏览器",
                     "问答工具", "环境", "证据", "不调用其他技能", "意图"):
            self.assertIn(term, text)
        self.assertNotIn("完成时调用", text)  # no auto-chaining wording
        evals = json.loads(
            (SCAFFOLD / ".agents/skills/ph-intent-verify/evals/evals.json").read_text(encoding="utf-8")
        )
        self.assertEqual(evals["skill_name"], "ph-intent-verify")
        prompts = [e["prompt"] for e in evals["evals"]]
        # trigger coverage: named-skill positives and non-naming negatives
        self.assertTrue(any("ph-intent-verify" in p for p in prompts))
        self.assertTrue(any("ph-intent-verify" not in p for p in prompts))
        agents = (SCAFFOLD / ".agents/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("ph-intent-verify", agents)
        interview = (ENGINEERING / "意图与访谈.md").read_text(encoding="utf-8")
        self.assertIn("ph-intent-verify", interview)

    def test_explicit_invocation_gate_registered_everywhere(self):
        # The gate sentence lives in the rule index and the intent spec; the
        # auto-trigger phrasings are gone from all twelve skills.
        for rel in (".agents/AGENTS.md", "docs/约束规范/工程规范/意图与访谈.md"):
            text = (SCAFFOLD / rel).read_text(encoding="utf-8")
            self.assertIn("点名", text, rel)
        banned = ("即使没点名本技能——都必须使用", "即使没说出归档二字——都必须使用",
                  "或调用 ph-worktree-exit，都必须使用本技能", "完成时调用 `ph-worktree-exit`",
                  "启动推进属于 `ph-intent-impl`", "才按要求处理分支或调用 `ph-worktree-enter`")
        root = SCAFFOLD / ".agents/skills"
        for skill in (*root.glob("*/SKILL.md"), ROOT / "SKILL.md"):
            text = skill.read_text(encoding="utf-8")
            for phrase in banned:
                self.assertNotIn(phrase, text, f"{skill}: {phrase}")
            self.assertIn("ph-", text)


if __name__ == "__main__":
    unittest.main()
