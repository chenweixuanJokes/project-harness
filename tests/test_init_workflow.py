"""Static contract tests for the documented init workflow (skill + scaffold docs).

These checks keep the workflow requirements explicit in the shipped text:
adopt-plan contract, legacy-content onboarding, evidence-based completion and
the init-report coverage convention. They assert concepts and structure, not
exact prose, and never execute the installer.
"""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "assets/scaffold"
GUIDE = ROOT / "references/接入规范.md"
GOVERNANCE = SCAFFOLD / ".agents/project-harness/constraints/harness规范/文档治理规范.md"
AGENTS = SCAFFOLD / ".agents/AGENTS.md"
EVALS = ROOT / "evals/evals.json"

RESULT_STATES = ("已核验", "复用", "不适用", "待核实", "冲突")
# The root skill reports completion states in English prose; the scaffold
# guide keeps the published Chinese report vocabulary.
SKILL_RESULT_STATES = ("verified", "reused", "not-applicable", "pending", "conflicting")
EVIDENCE_KINDS = ("模块", "代码", "配置", "真实依赖", "测试", "CI", "旧约束")
ADOPT_SOURCES_ENTRIES = (".agents/AGENTS.md", "AGENTS.md", "CLAUDE.md")
# Common strict subset every distributed skill must satisfy: strict kebab-case
# name (slot directory equals frontmatter name) and a non-empty description
# of at most 1024 characters.
STRICT_SKILL_NAME = re.compile(r"^ph-[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_BLOCK = re.compile(r"\A---\n(.*?)\n---\n", re.S)
FRONTMATTER_SCALAR = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


def frontmatter_scalars(text: str) -> dict:
    """Precise, limited frontmatter parse: flat ``key: value`` scalars only.

    Single-line scalars cover every distributed skill; indented continuation
    lines of a nested mapping/list block (should one ever reappear) are
    skipped rather than parsed, since only top-level scalar slots are
    asserted. No third-party YAML dependency; malformed top-level lines fail
    loudly instead of guessing.
    """
    block = FRONTMATTER_BLOCK.match(text)
    if block is None:
        raise AssertionError("missing YAML frontmatter")
    fields = {}
    for raw in block.group(1).splitlines():
        if raw.startswith((" ", "\t")):
            continue  # nested continuation of a mapping/list block, not a scalar slot
        parsed = FRONTMATTER_SCALAR.match(raw)
        if parsed is None:
            raise AssertionError(f"cannot parse frontmatter line: {raw!r}")
        fields[parsed.group(1)] = parsed.group(2).strip().strip("\"'")
    return fields


def scaffold_docs_texts():
    for path in sorted((SCAFFOLD / "docs").rglob("*.md")):
        yield path, path.read_text(encoding="utf-8")


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    def test_batch_version_single_ph_version_contract(self):
        release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        # the skill states the current package version and takes it from the
        # single release source, not a second hand-maintained count
        self.assertIn(release["version"], self.skill)
        self.assertIn("release.json", self.skill)
        self.assertIn("ph_governance.py", self.skill)
        # separate schema version is gone; older release numbers must not
        # reappear as the current batch
        self.assertNotRegex(self.skill, r"1\.1\.1(?![0-9])")

    def test_one_time_entry_switch_documented(self):
        release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        # old entry validators reject the new package contract; the documented
        # bootstrap is the published release tag prepared out-of-repo by its
        # own entry, never a patched validator, a retry or a local tree posing
        # as a release
        self.assertIn("reject new package contracts", self.skill)
        self.assertIn(f"v{release['version']}", self.skill)
        self.assertIn("outside the project", self.skill)
        self.assertIn("Do not patch the old validator", self.skill)
        self.assertIn("report publication as unavailable", self.skill)
        self.assertIn("not public release installation", self.skill)
        # historical transitions stay in their unchanged migration files
        self.assertIn("Earlier historical transitions", self.skill)
        # the shipped user-entry refresh runs once per maintenance operation
        self.assertIn("user-entry", self.skill)

    def test_skill_keeps_upgrade_in_same_session(self):
        self.assertIn("same operation", self.skill)
        self.assertIn("ph-merge-update", self.skill)
        self.assertIn("internal steps", self.skill)
        self.assertIn("not a new automatically triggered skill", self.skill)
        self.assertIn("Never run init --apply", self.skill)

    def test_retired_skills_routed_away_from_init(self):
        # 1.1.14 retired the old helper skills and 1.2.3 retired the bundled
        # Spec Kit pieces entirely: init references neither, and the spec
        # workflow is the PH-owned SDD suite.
        for retired in ("ph-docs-sync", "ph-sure", "ph-intent-verify",
                        "ph-memory-capture", "ph-intent-impl",
                        "ph_speckit.py", "speckit.json", "speckit-bundle",
                        "ph-specify", "ph-plan", "ph-taskstoissues",
                        "ph-analyze", "ph-checklist", "ph-converge", "ph-constitution"):
            self.assertNotIn(retired, self.skill)
        self.assertIn("not depend on upstream Spec Kit", self.skill)
        self.assertIn("PH-owned", self.skill)
        for current in ("ph-require", "ph-design", "ph-verify-plan",
                        "ph-small-change", "ph-archive"):
            self.assertIn(current, self.skill)

    def test_mode_default_auto_for_new_installs(self):
        mode_lines = [line for line in self.skill.splitlines() if "--mode" in line]
        self.assertTrue(mode_lines, "skill must document the --mode default")
        self.assertIn("auto|portable|symlink", mode_lines[0])
        # new installs probe symlink capability at apply; probe failure -> portable
        self.assertIn("probes symlink capability", self.skill)
        self.assertIn("falls back to portable", self.skill)
        # dry-run neither probes nor writes; explicit symlink fails strictly
        self.assertIn("Default commands are dry-run", self.skill)
        self.assertIn("fails rather than silently changes mode", self.skill)
        # portable is supported, not degraded
        self.assertIn("Portable is supported, not degraded", self.skill)
        self.assertIn("hardlinks", self.skill)
        # installed projects keep their mode; no automatic conversion
        self.assertIn("does not migrate that choice", self.skill)

    def test_skill_is_tool_neutral(self):
        # the shipped text carries no vendor-specific declarations
        self.assertNotIn("ZCode", self.skill)
        self.assertNotIn(".zcode", self.skill)
        self.assertNotIn(".codex", self.skill)
        self.assertNotIn(".opencode", self.skill)
        self.assertIn("host /init command", self.skill)

    def test_multi_client_adapters_documented(self):
        # Claude is the only declared adapter; every other client reads the
        # canonical location directly and needs no vendor mirror.
        self.assertIn("AGENTS.md", self.skill)
        self.assertIn("CLAUDE.md", self.skill)
        self.assertIn(".claude/skills/", self.skill)
        self.assertIn("no duplicate copies", self.skill)
        self.assertIn("vendor mirrors", self.skill)
        for vendor in ("Claude Code", "Codex", "OpenCode"):
            self.assertNotIn(vendor, self.skill)

    def test_distributed_skills_share_strict_frontmatter_subset(self):
        release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        required = release["required_skills"]
        # 1.2.3 ships one self-contained set of 18 PH-owned skills; the
        # bundled Spec Kit contract and its second skill list are retired.
        self.assertEqual(len(required), 18)
        self.assertEqual(sorted(required), [
            "ph-archive", "ph-clarify", "ph-design", "ph-design-review",
            "ph-human", "ph-implement", "ph-init", "ph-memory-archive",
            "ph-memory-ask", "ph-memory-learning", "ph-merge-update",
            "ph-require", "ph-small-change", "ph-tasks", "ph-verify",
            "ph-verify-plan", "ph-worktree-enter", "ph-worktree-exit",
        ])
        self.assertNotIn("speckit", release)
        self.assertFalse((ROOT / "speckit.json").exists())
        self.assertFalse((ROOT / "assets/speckit-bundle.json").exists())
        # the root SKILL.md is the ph-init slot; the other seventeen live in scaffold
        slots = {
            "ph-init": ROOT / "SKILL.md",
            **{
                name: SCAFFOLD / ".agents" / "skills" / name / "SKILL.md"
                for name in required
                if name != "ph-init"
            },
        }
        scaffold_dirs = sorted(
            child.name
            for child in (SCAFFOLD / ".agents" / "skills").iterdir()
            if child.is_dir()
        )
        self.assertEqual(scaffold_dirs, sorted(name for name in required if name != "ph-init"))
        for name, path in sorted(slots.items()):
            with self.subTest(skill=name):
                self.assertTrue(path.is_file(), f"missing skill file for {name}")
                self.assertTrue(STRICT_SKILL_NAME.match(name),
                                f"skill name is not strict kebab-case: {name}")
                fields = frontmatter_scalars(path.read_text(encoding="utf-8"))
                self.assertEqual(fields.get("name"), name,
                                 "slot name and frontmatter name must match")
                description = fields.get("description")
                self.assertTrue(description and description.strip(),
                                "description must be non-empty")
                self.assertLessEqual(len(description), 1024)

    def test_adopt_plan_cli_contract_is_explicit(self):
        self.assertIn("--adopt-plan", self.skill)
        for term in ("version=1", "repo", "release_version", "sources", "files", "SHA256"):
            self.assertIn(term, self.skill)
        for entry in ADOPT_SOURCES_ENTRIES:
            self.assertIn(entry, self.skill)
        self.assertIn("outside the repository", self.skill)  # candidate prepared out-of-repo
        self.assertIn("No installed manifest", self.skill)  # adopt only for fresh targets
        self.assertIn("Allowed destinations", self.skill)  # canonical/docs/constraints only
        self.assertIn("overwrite old prose", self.skill)  # template never over legacy content
        self.assertIn("not semantic completeness", self.skill)  # hash guard != semantic proof

    def test_skill_forbids_template_over_legacy_content(self):
        self.assertIn("overwrite old prose", self.skill)
        self.assertIn(".agents/init-report.md", self.skill)
        for state in SKILL_RESULT_STATES:
            self.assertIn(state, self.skill)

    def test_skill_merges_legacy_dirs_instead_of_keeping_them(self):
        self.assertIn("migrate still-valid", self.skill)
        self.assertIn("appropriate PH zones", self.skill)
        self.assertIn("Archiving alone is not migrating useful content", self.skill)
        self.assertIn("Preserve old originals", self.skill)
        self.assertIn("explicitly labeled", self.skill)


class GuideContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = GUIDE.read_text(encoding="utf-8") + (ROOT / "references/补全规范.md").read_text(encoding="utf-8")

    def test_legacy_content_onboarding_rules(self):
        self.assertIn("用旧内容接入", self.guide)
        self.assertIn("复用", self.guide)
        self.assertIn("不复制第二套", self.guide)
        for legacy in ("specs", "domains", "plans"):
            self.assertIn(legacy, self.guide)
        self.assertIn("归并", self.guide)
        self.assertIn("深链", self.guide)
        self.assertIn("效力", self.guide)
        self.assertNotIn("保留原位", self.guide)

    def test_docs_finish_in_three_domains(self):
        for term in ("README.md", "约束规范", "意图", "项目Wiki", "旧路径 → 新落点",
                     "附件", "活动引用", "空壳", "软链"):
            self.assertIn(term, self.guide)
        self.assertIn("只允许", self.guide)

    def test_migration_requires_authorization_and_preserves_sources(self):
        for term in ("本轮授权", "archive/legacy-backup", "哈希", "未完成", "不自动搬移或删除"):
            self.assertIn(term, self.guide)
        self.assertIn("旧正文", self.guide)
        self.assertIn("历史记录", self.guide)
        self.assertIn("归并", self.guide)
        self.assertIn("深链", self.guide)
        self.assertNotIn("仓外备份", self.guide)

    def test_legacy_plans_are_not_fabricated_intents(self):
        self.assertIn("已有需求与计划", self.guide)
        self.assertIn("不推定评审", self.guide)
        self.assertIn("交付", self.guide)
        self.assertIn("实施", self.guide)
        self.assertIn("不造纪要", self.guide)

    def test_same_topic_merges_into_one_body(self):
        self.assertIn("同主题", self.guide)
        self.assertIn("一个正文", self.guide)
        self.assertIn("不是把两个版本全文拼在一起", self.guide)
        self.assertIn("不以“代码为准”擅自废止规则", self.guide)

    def test_attachments_follow_body_and_are_not_executed(self):
        self.assertIn("附件", self.guide)
        self.assertIn("不因整理而执行", self.guide)
        self.assertIn("archive/legacy-backup", self.guide)
        self.assertIn("可恢复原件", self.guide)

    def test_archived_snapshot_convention_is_in_repo(self):
        archived = SCAFFOLD / ".agents/project-harness/archive/legacy-backup/README.md"
        self.assertTrue(archived.is_file(), "scaffold must ship archive/legacy-backup/README.md")
        text = archived.read_text(encoding="utf-8")
        for term in ("archive/legacy-backup", "pre-init", "原样", "可恢复", "archive/memory", "不自动"):
            self.assertIn(term, text)
        self.assertIn("archive/legacy-backup", self.guide)
        self.assertIn("可恢复原件", self.guide)
        self.assertIn("plan JSON", self.guide)
        # adopt plan stays outside the repo; source-file backup does not
        self.assertIn("目标仓外", self.guide)

    def test_inventory_requires_all_evidence_kinds(self):
        self.assertTrue(all(kind in self.guide for kind in EVIDENCE_KINDS),
                        "guide must enumerate every evidence kind")

    def test_snapshot_inventory_accounts_for_ignored_build_inputs(self):
        for term in ("git ls-files", ".gitignore", ".java-version", "哈希", "非凭据"):
            self.assertIn(term, self.guide)
        self.assertIn("副本缺失不代表原项目不存在", self.guide)

    def test_report_does_not_hide_unresolved_items(self):
        self.assertIn("不能只在页脚", self.guide)
        self.assertIn("不表示问题全部解决", self.guide)
        self.assertIn("不以“代码为准”擅自废止规则", self.guide)

    def test_dry_run_output_requires_integration(self):
        self.assertIn("施工单", self.guide)
        self.assertIn("待整合", self.guide)
        for category in ("直接落地", "复用引用", "冲突待裁决", "不适用与保留"):
            self.assertIn(category, self.guide)

    def test_adopt_plan_flow_documented_with_snapshot(self):
        self.assertIn("init --adopt-plan", self.guide)
        for key in ('"version": 1', '"repo"', '"release_version"', '"sources"', '"files"'):
            self.assertIn(key, self.guide)  # the shipped JSON example
        self.assertIn("SHA256", self.guide)
        self.assertIn("仓外", self.guide)
        self.assertIn("ph.json", self.guide)
        self.assertIn("不证明候选内容正确", self.guide)

    def test_init_report_convention(self):
        self.assertIn("`.agents/init-report.md`", self.guide)
        self.assertIn("实现记录", self.guide)
        for column in ("`id`", "`落点`", "`仓内证据`", "`结果`", "`说明`"):
            self.assertIn(column, self.guide)
        for state in RESULT_STATES:
            self.assertIn(state, self.guide)
        self.assertIn("每个独立 id", self.guide)
        self.assertIn("采用声明", self.guide)
        # the matrix itself still enumerates the boundary ids of each group
        for ident in ("E1", "E2", "C61", "C65", "F3", "F34", "D35", "D39",
                      "D40", "D44", "C45", "C50", "D51", "D60"):
            self.assertIn(ident, self.guide)

    def test_section_references_into_guide_resolve(self):
        headings = {int(m.group(1)) for m in re.finditer(r"(?m)^## (\d+)\. ", self.guide)}
        self.assertTrue(headings)
        for path, text in scaffold_docs_texts():
            for m in re.finditer(r"初始化与文档补全\.md\)\s*§(\d+)", text):
                self.assertIn(int(m.group(1)), headings,
                              f"{path.name} references a missing guide section")
            for m in re.finditer(r"初始化与文档补全\.md#(\d+)-", text):
                self.assertIn(int(m.group(1)), headings,
                              f"{path.name} references a missing guide anchor")


class EntryPointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.governance = GOVERNANCE.read_text(encoding="utf-8")
        cls.agents = AGENTS.read_text(encoding="utf-8")

    def test_governance_declares_init_report_and_archive_split(self):
        self.assertIn("init-report", self.governance)
        self.assertIn("archive/legacy-backup", self.governance)
        self.assertIn("只读追溯", self.governance)
        self.assertNotIn("保留原位", self.governance)
        # business docs stay outside PH governance
        self.assertIn("PH 不占用、不索引", self.governance)

    def test_canonical_agents_entry_is_minimal_and_points_at_the_constitution(self):
        # Since 1.2.1 the entry file only routes to the materialized
        # constitution and the home README; the old skill table, centralized
        # invocation gate and detailed rules are gone.
        self.assertIn("constitution.md", self.agents)
        self.assertIn("project-harness/README.md", self.agents)
        self.assertIn("基本要求", self.agents)
        self.assertNotIn("init-report", self.agents)
        self.assertNotIn(".agents/archived", self.agents)
        self.assertNotIn("ph-specify", self.agents)
        self.assertNotIn("十八名固定", self.agents)

    def test_invocation_gate_lives_in_each_skill_metadata(self):
        # The gate lives in every skill's own metadata, keeping its two
        # standing exceptions: the ph-init in-session merge-update steps and
        # the ph-memory-ask recollection intent. 1.2.3 rewrote the SDD suite
        # in English while the three memory skills keep their published
        # Chinese body.
        skills = sorted((SCAFFOLD / ".agents/skills").glob("ph-*/SKILL.md"))
        # the seventeen scaffold skills plus the root ph-init entry make the
        # eighteen required skills
        self.assertEqual(len(skills), 17)
        for skill in skills:
            text = skill.read_text(encoding="utf-8")
            desc = next(
                (line for line in text.splitlines() if line.startswith("description:")), "", )
            self.assertRegex(desc, r"explicitly names|do not trigger|点名",
                             f"{skill.name}: {desc}")
        ask = (SCAFFOLD / ".agents/skills/ph-memory-ask/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("回忆意图", ask)
        init_skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ph-merge-update", init_skill)


class EvalsCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(EVALS.read_text(encoding="utf-8"))
        cls.items = data["evals"]

    def test_ids_unique_and_scenarios_present(self):
        ids = [item["id"] for item in self.items]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 18)
        blob = "\n".join(item["prompt"] + item["expected_output"] for item in self.items)
        # legacy docs, merge-not-copy, attachments, same-topic, unapproved
        # plan, pure-code, stale-conflict, SDD takeover, same-session upgrade
        self.assertIn("specs", blob)
        self.assertIn("附件", blob)
        self.assertIn("不复制第二套", blob)
        self.assertIn("归档不等于", blob)
        self.assertIn("两份大体相同", blob)
        self.assertIn("不双全文追加", blob)
        self.assertIn("不推定设计审查", blob)
        self.assertIn("依据代码反推事实", blob)
        self.assertIn("Gradle", blob)
        self.assertIn("不悄悄废止旧规则", blob)
        self.assertIn("自研SDD版", blob)
        self.assertIn("missing schema_version", blob)
        self.assertIn("SpecKit时代入口", blob)
        self.assertIn("1.2.3", blob)
        self.assertIn("正式受管副本", blob)
        self.assertIn("canonical", blob)
        self.assertIn("不先装模板盖正文", blob)
        self.assertIn("user-entry", blob)
        # the upgrade runs merge-update as in-session internal steps
        self.assertIn("内部步骤", blob)
        self.assertNotIn("转交 ph-merge-update", blob)
        # historical zones and claims that must not come back
        self.assertNotIn(".agents/archived", blob)
        self.assertNotIn("仓外备份", blob)
        self.assertNotIn("保留原位", blob)

    def test_trigger_negatives_stay_covered(self):
        # Ordinary descriptions, adjacent task wordings and bare discussions
        # must not start the installer or chain into other skills.
        blob = "\n".join(item["prompt"] + item["expected_output"] for item in self.items)
        self.assertIn("不触发ph-init", blob)
        self.assertIn("普通描述不触发", blob)
        self.assertIn("ph-require", blob)

    def test_every_eval_is_a_complete_behavior_definition(self):
        for item in self.items:
            with self.subTest(id=item["id"]):
                self.assertTrue(item["prompt"].strip())
                self.assertTrue(item["expected_output"].strip())


if __name__ == "__main__":
    unittest.main()
