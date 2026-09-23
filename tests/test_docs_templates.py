"""Static coverage of the distributable initialization guide and wiki templates."""
from pathlib import Path
import json
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "assets/scaffold"
DOCS = SCAFFOLD / ".agents/project-harness/documents"
ENGINEERING = SCAFFOLD / ".agents/project-harness/constraints/工程规范"


class DocsTemplateTests(unittest.TestCase):
    def test_engineering_guides_are_indexed_and_skill_reachable(self):
        constraints = ENGINEERING.parent
        self.assertFalse(list(constraints.rglob("README.md")))
        for name in ("Git规范.md", "安全规范.md"):
            self.assertTrue((ENGINEERING / name).is_file())
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for name in ("接入规范.md", "补全规范.md", "项目化验收.md"):
            self.assertTrue((ROOT / "references" / name).is_file())
            self.assertIn("references/" + name, skill)

    def test_workbook_test_cases_and_conditional_components_are_mapped(self):
        guide = (ROOT / "references/补全规范.md").read_text(encoding="utf-8")
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
        self.assertEqual(release["version"], "1.2.3")
        self.assertNotIn("schema_version", release)  # single PH version since 1.1.8
        self.assertEqual(len(release["required_skills"]), 18)
        self.assertIn("ph-merge-update", release["required_skills"])
        self.assertIn("ph-worktree-exit", release["required_skills"])
        # the bundled upstream Spec Kit contract is retired since 1.2.3
        self.assertFalse((REPO_ROOT / "speckit.json").exists())
        self.assertFalse((REPO_ROOT / "assets/speckit-bundle.json").exists())
        self.assertNotIn("speckit", release)
        manifest = json.loads((SCAFFOLD / ".agents/ph.json").read_text())
        self.assertNotIn("schema_version", manifest)
        self.assertEqual(manifest["template_version"], release["version"])
        self.assertEqual(manifest["skills"]["required_names"], release["required_skills"])
        self.assertNotIn("speckit", manifest)
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
        hop_1114 = next(h for h in hops if h["from_version"] == "1.1.13")
        self.assertEqual(hop_1114["to_version"], "1.1.14")
        self.assertEqual(hop_1114["path"], "migrations/1.1.13-to-1.1.14.md")
        self.assertEqual(hop_1114["items"],
                         ["worktree-wip-confirm", "retire-legacy-skills",
                          "speckit-core-integration", "constitution-governance-zone",
                          "intent-to-spec"])
        hop_123 = next(h for h in hops if h["from_version"] == "1.2.2")
        self.assertEqual(hop_123["to_version"], "1.2.3")
        self.assertEqual(hop_123["items"],
                         ["sdd-skill-replacement", "sdd-runtime-takeover",
                          "bilingual-skills", "docs-tests-consolidation",
                          "worktree-session-continuity", "artifact-compat"])

    def test_sdd_takeover_migration_documented(self):
        doc = (ROOT / "migrations/1.2.2-to-1.2.3.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("sdd-skill-replacement", "sdd-runtime-takeover", "bilingual-skills",
                     "docs-tests-consolidation", "worktree-session-continuity",
                     "artifact-compat",
                     # the retired bundled Spec Kit contract
                     "ph_speckit.py", "speckit.json", "18 个自研技能",
                     # the one-time old-entry transition
                     "硬校验失败", "仓外安全目录", "v1.2.3",
                     # the deterministic skill migration and governance split
                     "migrate-skills", "ph_governance.py",
                     # the minimal self-built runtime and bilingual skills
                     "templates/sdd/", "SKILL.zh.md",
                     # artifact compatibility: new names, legacy bytes untouched
                     "requirement.md", "change.md", "spec.md", "plan.md",
                     "feature.json", ".ph-intent-ledger.json",
                     "template_version", "1.2.3"):
            self.assertIn(term, doc)

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

    def test_worktree_wip_confirm_migration_documented(self):
        doc = (ROOT / "migrations/1.1.13-to-1.1.14.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("worktree-wip-confirm", "1.1.13", "1.1.14",
                     "统一 WIP 确认", '两个选项文案固定为字面"是""否"', "单次 `enter --apply`",
                     "exit --apply", '不拆成"先 wip 再进入 / 退出"两次脚本调用',
                     "实际调用问答工具", "wip: <说明>", "ph-worktree-enter", "ph-worktree-exit",
                     "Git与并行开发.md", "不再按分级默认普通提交", "源工作区",
                     "不盲目 `git add -A`", "ignored", "未解决的冲突", "不换问法重问",
                     '答"否"、取消或未回答', "调用本技能本身不构成任何提交确认",
                     "是否采用 `wip:` 提交解决当前这次阻断", "不是对文件内容的逐项审批",
                     "同一已展示路径的普通内容修改不需要重新确认", "不逐字节比对文件内容",
                     "授权不是长期授权", "不部分提交",
                     "--wip-message", "只读 dry-run", "整单拒绝",
                     "脚本无能力证明真实用户确认", "绝不据此提交",
                     "doctor", "recover", "redeliver", "--expect-source-head",
                     "mergeSourceBranch", "recover 不能恢复所有旧 merge",
                     "核对 merge 身份", "保守阻断", "新增字段非必填", "不覆盖现有 session",
                     "冲突恢复", "MERGE_HEAD", "冲突清单", "未合并条目",
                     "保留现场，我解决后继续", "撤销这次合并", "已解决并暂存，请继续",
                     "冲突态优先", "不是 WIP",
                     "运行时脚本", "blocked", "adapter mode", "逐字节一致", "template_version",
                     ".agents/scripts/ph_worktree.py", "sourceDirty"):
            self.assertIn(term, doc)

    def test_retire_and_speckit_migration_documented(self):
        doc = (ROOT / "migrations/1.1.13-to-1.1.14.md").read_text(encoding="utf-8")
        for heading in ("## why", "## from", "## to", "## affected",
                        "## preserve", "## conflict", "## verify"):
            self.assertIn(heading, doc)
        for term in ("retire-legacy-skills", "speckit-core-integration",
                     "constitution-governance-zone", "intent-to-spec",
                     "ph-memory-capture", "ph-intent-new", "ph-docs-sync",
                     "备份", "docs/意图/", ".agents/memory/", "业务 docs",
                     "由代理按本文执行",
                     "github/spec-kit", "正式 tag+commit", "官方生成器", "隔离 venv",
                     "x-ph-upstream", "speckit.json", "自定义技能", "不得覆盖",
                     "specify init", "zcode", "ph-",
                     "constitution-template.md", "覆盖机制", "待确认",
                     "docs/约束规范", "相对链接", "不复制规范正文",
                     "重试续装", "不推进版本", "template_version",
                     # intent-to-spec contract terms
                     "必过", "不接受 `not_applicable`", "specs/.ph-intent-ledger.json",
                     "NEEDS CLARIFICATION", "不编造优先级", "不生成 plan / tasks",
                     "历史索引", "只读历史", "select-intent-spec",
                     "SPECIFY_FEATURE_DIRECTORY", "重复源 intent_id", "幂等"):
            self.assertIn(term, doc)

    def test_explicit_invocation_gate_registered_everywhere(self):
        # Since 1.2.1 the entry file is minimal and delegates to the
        # constitution; each skill's own metadata carries the invocation
        # gate, and the retired interview doc survives only as history.
        agents = (SCAFFOLD / ".agents/AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("constitution.md", agents)
        interview = (
            SCAFFOLD / ".agents/project-harness/archive/constraints-history/意图与访谈.md"
        ).read_text(encoding="utf-8")
        self.assertIn("不自动触发", interview)
        banned = ("即使没点名本技能——都必须使用", "即使没说出归档二字——都必须使用",
                  "或调用 ph-worktree-exit，都必须使用本技能", "完成时调用 `ph-worktree-exit`",
                  "启动推进属于 `ph-intent-impl`", "才按要求处理分支或调用 `ph-worktree-enter`")
        root = SCAFFOLD / ".agents/skills"
        for skill in (*root.glob("*/SKILL.md"), ROOT / "SKILL.md"):
            text = skill.read_text(encoding="utf-8")
            for phrase in banned:
                self.assertNotIn(phrase, text, f"{skill}: {phrase}")
            self.assertIn("ph-", text)

    def test_maintainer_docs_link_overall_release_spec_without_withdrawn_docs(self):
        for name in (
            "README.md",
            "docs/README.md",
            "docs/约束规范/工程规范/README.md",
            "docs/约束规范/工程规范/版本与合并升级.md",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("插件安装.md", text, name)
            self.assertNotIn("插件发行与安装.md", text, name)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/约束规范/工程规范/版本与合并升级.md", readme)
        engineering_index = (
            ROOT / "docs/约束规范/工程规范/README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("](./版本与合并升级.md)", engineering_index)


if __name__ == "__main__":
    unittest.main()
