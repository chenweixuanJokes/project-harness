#!/usr/bin/env python3
"""init --adopt-plan: install PH into a legacy repo from a reviewed merge plan."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
SCAFFOLD = REPO_ROOT / "assets" / "scaffold"
PH_INIT = REPO_ROOT / "scripts" / "ph_init.py"
TRASH_ROOT = Path.home() / "trash"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ph_init  # noqa: E402

OLD_RULES_AGENTS = "# 旧规则\n\n- AGENTS 入口的既有约束正文。\n"
OLD_RULES_CLAUDE = "# CLAUDE 旧规则\n\n- Claude 入口的历史说明。\n"
MERGED_NOTE = "\n## 合并自既有规则\n\n以上旧规则已由会话并入 PH 模板。\n"


def run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=90)


def ph(repo, *args, script=None):
    return run([sys.executable, str(script or PH_INIT), *args, "--repo", str(repo)])


def fields(stdout):
    return dict(
        line.split("=", 1)
        for line in stdout.splitlines()
        if "=" in line and not line.startswith("item=")
    )


def items(stdout):
    parsed = []
    for line in stdout.splitlines():
        if not line.startswith("item="):
            continue
        kind, path, reason = line[5:].split("\t", 2)
        parsed.append((kind, path, reason))
    return parsed


def item_map(stdout):
    return {path: (kind, reason) for kind, path, reason in items(stdout)}


def kinds_for(stdout, path):
    return [kind for kind, item_path, _reason in items(stdout) if item_path == path]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InitAdoptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PH_INIT
        cls._source = Path(tempfile.mkdtemp(prefix="ph-adopt-payload-"))
        for src in ph_init.ph_init_payload_files():
            dest = cls._source / src.relative_to(REPO_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
        PH_INIT = cls._source / "scripts" / "ph_init.py"

    @classmethod
    def tearDownClass(cls):
        TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        if cls._source.exists():
            cls._source.rename(TRASH_ROOT / cls._source.name)

    def setUp(self):
        self._temps = []
        self._workspace = Path(tempfile.mkdtemp(prefix="ph-adopt-ws-"))
        self._temps.append(self._workspace)

    def tearDown(self):
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-adopt-{stamp}-{os.getpid()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=False)
        for i, path in enumerate(self._temps):
            if path.exists():
                path.rename(dest / f"{i:02d}-{path.name}")

    def temp_dir(self, prefix):
        root = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(root)
        return root

    def git_repo(self, prefix):
        root = self.temp_dir(prefix)
        for argv in (
            ["git", "init"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "ph-init-test"],
        ):
            proc = run(argv, cwd=root)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return root

    def assert_ok(self, proc, **expect):
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        got = fields(proc.stdout)
        self.assertEqual(got.get("status"), "ok", proc.stdout)
        for key, value in expect.items():
            self.assertEqual(got.get(key), value, proc.stdout)
        self.assertNotRegex(proc.stdout, r"(?m)^item=(conflict|block|error)\t", proc.stdout)

    def plan_path(self, name="adopt-plan.json") -> Path:
        return self._workspace / name

    def pin(self, repo: Path, rel: str) -> str | None:
        path = repo / rel
        if rel in ph_init.ADOPT_ROOT_ENTRIES and path.is_symlink():
            path = repo / ph_init.ADOPT_CANONICAL
        if not path.exists():
            return None
        return sha(path.read_bytes())

    def rule_pins(self, repo: Path, **extra) -> dict:
        sources = {rel: self.pin(repo, rel) for rel in (*ph_init.ADOPT_ROOT_ENTRIES, ph_init.ADOPT_CANONICAL)}
        sources.update(extra)
        return sources

    def write_plan(self, repo: Path, sources: dict, files: dict, **override) -> Path:
        path = override.pop("path", None) or self.plan_path(override.pop("name", "adopt-plan.json"))
        data = {
            "version": override.pop("version", 1),
            "repo": override.pop("plan_repo", str(repo)),
            "release_version": override.pop("release_version", ph_init.RELEASE_VERSION),
            "sources": sources,
            "files": files,
        }
        data.update(override)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def merged_canonical(self, *legacy_texts: str) -> str:
        return "# 项目约束（PH 合并稿）\n" + "\n".join(legacy_texts) + MERGED_NOTE

    def seed_installed_canonical(self, repo: Path, *, with_codex: bool = True) -> dict:
        """Materialize a canonical layout, optionally using the legacy adapter."""

        scaffold_agents = SCAFFOLD / ".agents"
        agents = repo / ".agents"
        agents.mkdir(parents=True, exist_ok=True)
        shutil.copytree(scaffold_agents / "skills", agents / "skills")
        ph_init_skill = agents / "skills" / "ph-init"
        ph_init_skill.mkdir(parents=True, exist_ok=True)
        (ph_init_skill / "SKILL.md").write_bytes((REPO_ROOT / "SKILL.md").read_bytes())
        (agents / "AGENTS.md").write_bytes((scaffold_agents / "AGENTS.md").read_bytes())
        (agents / "ph.schema.json").write_bytes((scaffold_agents / "ph.schema.json").read_bytes())
        data = json.loads((scaffold_agents / "ph.json").read_text(encoding="utf-8"))
        if with_codex:
            data["adapters"]["codex_skills"] = {
                "mode": "mirror_tree",
                "path": ".codex/skills",
                "source": ".agents/skills",
                "include": "ph-*",
            }
        (agents / "ph.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return data

    # -- positive adopt cases -------------------------------------------------

    def test_adopt_root_only_agents_portable(self):
        repo = self.git_repo("ph-adopt-root-only-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})

        dry = ph(repo, "init", "--adopt-plan", str(plan))
        self.assert_ok(dry, action="init", mode="portable", apply="false")
        self.assertFalse((repo / ".agents").exists(), "dry run must not write")
        mapped = item_map(dry.stdout)
        self.assertEqual(mapped[".agents/AGENTS.md"][0], "write", dry.stdout)
        self.assertIn("合并写入", mapped[".agents/AGENTS.md"][1])
        self.assertIn("覆盖为合并结果", mapped["AGENTS.md"][1], dry.stdout)
        self.assertEqual(mapped["CLAUDE.md"][0], "write", dry.stdout)

        applied = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
        self.assert_ok(applied, action="init", mode="portable", apply="true")
        self.assertEqual(item_map(applied.stdout), mapped, "dry and apply plan the same set")
        self.assertEqual((repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"), merged)
        self.assertEqual((repo / "AGENTS.md").read_text(encoding="utf-8"), merged, "adapter uses candidate, not legacy body")
        self.assertEqual((repo / "CLAUDE.md").read_bytes(), b"@.agents/AGENTS.md\n")
        self.assertIn("旧规则", (repo / "AGENTS.md").read_text(encoding="utf-8"), "legacy rules survive via the merge")
        self.assertTrue((repo / ".agents" / "ph.json").is_file())
        self.assert_ok(ph(repo, "check", "--mode", "portable"), action="check", mode="portable", apply="false")

    def test_adopt_claude_only_and_two_differing_entries(self):
        claude_only = self.git_repo("ph-adopt-claude-only-")
        (claude_only / "CLAUDE.md").write_text(OLD_RULES_CLAUDE, encoding="utf-8")
        merged_c = self.merged_canonical(OLD_RULES_CLAUDE)
        plan_c = self.write_plan(claude_only, self.rule_pins(claude_only), {".agents/AGENTS.md": merged_c})
        self.assert_ok(
            ph(claude_only, "init", "--apply", "--adopt-plan", str(plan_c)),
            action="init",
            mode="portable",
            apply="true",
        )
        self.assertEqual((claude_only / ".agents" / "AGENTS.md").read_text(encoding="utf-8"), merged_c)
        self.assertEqual((claude_only / "CLAUDE.md").read_bytes(), b"@.agents/AGENTS.md\n")
        self.assertTrue((claude_only / ".agents" / "ph.json").is_file())

        both = self.git_repo("ph-adopt-two-differ-")
        (both / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        (both / "CLAUDE.md").write_text(OLD_RULES_CLAUDE, encoding="utf-8")
        merged_b = self.merged_canonical(OLD_RULES_AGENTS, OLD_RULES_CLAUDE)
        plan_b = self.write_plan(both, self.rule_pins(both), {".agents/AGENTS.md": merged_b})
        dry = ph(both, "init", "--adopt-plan", str(plan_b))
        self.assert_ok(dry, mode="portable", apply="false")
        mapped = item_map(dry.stdout)
        self.assertIn("覆盖为合并结果", mapped["AGENTS.md"][1], dry.stdout)
        self.assertIn("覆盖为合并结果", mapped["CLAUDE.md"][1], dry.stdout)
        applied = ph(both, "init", "--apply", "--adopt-plan", str(plan_b))
        self.assert_ok(applied, mode="portable", apply="true")
        self.assertEqual(item_map(applied.stdout), mapped)
        canonical = (both / ".agents" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(canonical, merged_b)
        self.assertIn("AGENTS 入口的既有约束正文", canonical)
        self.assertIn("Claude 入口的历史说明", canonical)
        self.assertEqual((both / "AGENTS.md").read_text(encoding="utf-8"), merged_b)
        self.assertEqual((both / "CLAUDE.md").read_bytes(), b"@.agents/AGENTS.md\n")

    def test_adopt_existing_canonical_with_correct_symlinks_infers_symlink_mode(self):
        repo = self.git_repo("ph-adopt-linkmode-")
        old_canonical = "# 旧 canonical\n\n既有 canonical 正文。\n"
        canonical = repo / ".agents" / "AGENTS.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text(old_canonical, encoding="utf-8")
        (repo / "AGENTS.md").symlink_to(".agents/AGENTS.md")
        (repo / "CLAUDE.md").symlink_to(".agents/AGENTS.md")
        merged = self.merged_canonical(old_canonical)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})

        dry = ph(repo, "init", "--adopt-plan", str(plan))
        self.assert_ok(dry, action="init", mode="symlink", apply="false")
        mapped = item_map(dry.stdout)
        self.assertEqual(mapped[".agents/AGENTS.md"][0], "write", dry.stdout)
        self.assertIn("合并写入", mapped[".agents/AGENTS.md"][1])
        self.assertIn("identical relative symlink", mapped["AGENTS.md"][1], dry.stdout)
        self.assertIn("identical relative symlink", mapped["CLAUDE.md"][1], dry.stdout)

        applied = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
        self.assert_ok(applied, action="init", mode="symlink", apply="true")
        self.assertEqual(item_map(applied.stdout), mapped)
        self.assertEqual(canonical.read_text(encoding="utf-8"), merged)
        for rel in ("AGENTS.md", "CLAUDE.md"):
            link = repo / rel
            self.assertTrue(link.is_symlink(), rel)
            self.assertEqual(os.readlink(link), ".agents/AGENTS.md", rel)
            self.assertEqual(link.read_text(encoding="utf-8"), merged, rel)
        self.assert_ok(ph(repo, "check", "--mode", "symlink"), action="check", mode="symlink", apply="false")

    def test_adopt_docs_merge_only_listed_paths_and_keeps_unrelated(self):
        repo = self.git_repo("ph-adopt-docs-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        custom = {
            "docs/README.md": "# 项目文档\n存量 README 正文。\n",
            "docs/项目Wiki/自定义存量.md": "# 仅项目所有\n",
        }
        for rel, text in custom.items():
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        # since 1.2.1 the scaffold ships no docs/ tree: the "existing file is
        # preserved" surface is the project-harness home roots, while the
        # adopt plan itself may still deliver docs/** pages
        home_custom = ".agents/project-harness/constraints/harness规范/文档治理规范.md"
        (repo / home_custom).parent.mkdir(parents=True, exist_ok=True)
        (repo / home_custom).write_text("# 文档治理\n项目定制规范正文。\n", encoding="utf-8")
        merged_doc = custom["docs/README.md"] + "\n并入 PH 文档结构说明。\n"
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        sources = self.rule_pins(
            repo,
            **{
                "docs/README.md": sha(custom["docs/README.md"].encode("utf-8")),
                "docs/项目Wiki/迁移笔记.md": None,
            },
        )
        plan = self.write_plan(
            repo,
            sources,
            {
                ".agents/AGENTS.md": merged,
                "docs/README.md": merged_doc,
                "docs/项目Wiki/迁移笔记.md": "# 迁移笔记\n由会话整理的存量规则去向。\n",
            },
        )

        dry = ph(repo, "init", "--adopt-plan", str(plan))
        self.assert_ok(dry, mode="portable", apply="false")
        mapped = item_map(dry.stdout)
        self.assertIn("合并写入", mapped["docs/README.md"][1], dry.stdout)
        self.assertEqual(mapped["docs/项目Wiki/迁移笔记.md"][0], "write", dry.stdout)
        self.assertEqual(
            mapped[home_custom],
            ("skip", "scaffold: 保留待会话审阅"),
            dry.stdout,
        )
        self.assertNotIn("docs/项目Wiki/自定义存量.md", mapped, dry.stdout)
        self.assertNotIn("docs/约束规范/工程规范/文档治理.md", mapped, dry.stdout)

        applied = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
        self.assert_ok(applied, mode="portable", apply="true")
        self.assertEqual((repo / "docs" / "README.md").read_text(encoding="utf-8"), merged_doc)
        self.assertEqual(
            (repo / "docs" / "项目Wiki" / "迁移笔记.md").read_text(encoding="utf-8"),
            "# 迁移笔记\n由会话整理的存量规则去向。\n",
        )
        self.assertEqual(
            (repo / home_custom).read_text(encoding="utf-8"),
            "# 文档治理\n项目定制规范正文。\n",
        )
        self.assertEqual(
            (repo / "docs" / "项目Wiki" / "自定义存量.md").read_text(encoding="utf-8"),
            custom["docs/项目Wiki/自定义存量.md"],
        )

    def test_adopt_preserves_non_ph_agents_content(self):
        repo = self.git_repo("ph-adopt-keep-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        skill = repo / ".agents" / "skills" / "my-tool" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# my-tool\n用户自己的非 PH 技能。\n", encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})
        self.assert_ok(
            ph(repo, "init", "--apply", "--adopt-plan", str(plan)),
            action="init",
            mode="portable",
            apply="true",
        )
        self.assertEqual(skill.read_text(encoding="utf-8"), "# my-tool\n用户自己的非 PH 技能。\n")
        self.assertFalse((repo / ".claude" / "skills" / "my-tool").exists())
        self.assertFalse((repo / ".codex" / "skills" / "my-tool").exists())

    # -- regression: plain init still behaves ---------------------------------

    def test_candidate_manifest_may_only_delete_codex_skills_adapter(self):
        # The Codex/OpenCode native-reuse topology retired codex_skills, but
        # merge-update kernels that still emit it must keep verifying, and a
        # candidate may not smuggle any other adapters difference through.
        repo = self.git_repo("ph-adopt-candidate-")
        actual = self.seed_installed_canonical(repo)

        kept = copy.deepcopy(actual)
        with self.assertRaises(ph_init.PHError):
            ph_init.load_repo_manifest(repo, candidate=kept)

        trimmed = copy.deepcopy(actual)
        del trimmed["adapters"]["codex_skills"]
        ph_init.load_repo_manifest(repo, candidate=trimmed)

        wrong_codex_mode = copy.deepcopy(actual)
        wrong_codex_mode["adapters"]["codex_skills"]["mode"] = "symlink"
        missing_claude = copy.deepcopy(actual)
        del missing_claude["adapters"]["claude_skills"]
        renamed_extra = copy.deepcopy(actual)
        renamed_extra["adapters"]["opencode_skills"] = dict(renamed_extra["adapters"]["codex_skills"])
        for candidate in (wrong_codex_mode, missing_claude, renamed_extra):
            with self.subTest(adapters=sorted(candidate["adapters"])):
                with self.assertRaises(ph_init.PHError):
                    ph_init.load_repo_manifest(repo, candidate=candidate)

    def test_plain_init_regression_both_modes_on_empty_repo(self):
        for mode in ("portable", "symlink"):
            with self.subTest(mode=mode):
                repo = self.git_repo(f"ph-adopt-fresh-{mode}-")
                dry = ph(repo, "init", "--mode", mode)
                self.assert_ok(dry, action="init", mode=mode, apply="false")
                self.assertFalse((repo / ".agents").exists())
                self.assert_ok(
                    ph(repo, "init", "--apply", "--mode", mode),
                    action="init",
                    mode=mode,
                    apply="true",
                )
                self.assert_ok(ph(repo, "check", "--mode", mode), action="check", mode=mode, apply="false")

    def test_no_plan_conflict_blocks_without_overwrite_and_hints_adoption(self):
        repo = self.git_repo("ph-adopt-hint-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        before = (repo / "AGENTS.md").read_bytes()
        for extra in ((), ("--apply",)):
            proc = ph(repo, "init", "--mode", "portable", *extra)
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertEqual(fields(proc.stdout).get("status"), "error", proc.stdout)
            mapped = item_map(proc.stdout)
            self.assertEqual(mapped["AGENTS.md"][0], "block", proc.stdout)
            self.assertIn("adopt-plan", mapped["AGENTS.md"][1], proc.stdout)
            self.assertEqual((repo / "AGENTS.md").read_bytes(), before)
            self.assertFalse((repo / ".agents").exists())
            self.assertFalse((repo / "CLAUDE.md").exists())

    def test_repeat_init_keeps_customized_canonical(self):
        repo = self.git_repo("ph-adopt-repeat-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})
        self.assert_ok(ph(repo, "init", "--apply", "--adopt-plan", str(plan)), apply="true")

        customized = merged + "\n## 安装后新增定制\n只有 canonical 编辑者会写这里。\n"
        (repo / ".agents" / "AGENTS.md").write_text(customized, encoding="utf-8")
        self.assert_ok(ph(repo, "sync", "--apply", "--mode", "portable"), action="sync", apply="true")
        again = ph(repo, "init", "--apply", "--mode", "portable")
        self.assert_ok(again, action="init", mode="portable", apply="true")
        mapped = item_map(again.stdout)
        self.assertEqual(mapped[".agents/AGENTS.md"][0], "skip", again.stdout)
        self.assertIn("保留定制 canonical", mapped[".agents/AGENTS.md"][1], again.stdout)
        self.assertEqual((repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"), customized)
        self.assertEqual((repo / "AGENTS.md").read_text(encoding="utf-8"), customized)

    def test_init_on_older_install_hands_off_to_same_session_merge(self):
        repo = self.git_repo("ph-init-oldver-")
        agents = repo / ".agents"
        agents.mkdir()
        custom = "# 定制 canonical\n已装旧版不应被 init 覆盖。\n"
        (agents / "AGENTS.md").write_text(custom, encoding="utf-8")
        (repo / "AGENTS.md").write_text(custom, encoding="utf-8")
        (agents / "ph.json").write_text(
            json.dumps({"template_version": "1.1.4", "adapter_mode": "portable"}, indent=2) + "\n",
            encoding="utf-8",
        )
        before_manifest = (agents / "ph.json").read_bytes()
        for extra in ((), ("--apply",)):
            with self.subTest(extra=extra):
                proc = ph(repo, "init", *extra)
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("ph-merge-update", proc.stderr, proc.stderr)
                self.assertIn("1.1.4", proc.stderr, proc.stderr)
                self.assertIn(ph_init.RELEASE_VERSION, proc.stderr, proc.stderr)
                self.assertIn("inspect", proc.stderr, proc.stderr)
                self.assertIn("same session", proc.stderr, proc.stderr)
                self.assertEqual((agents / "ph.json").read_bytes(), before_manifest)
                self.assertEqual((agents / "AGENTS.md").read_text(encoding="utf-8"), custom)
                self.assertEqual((repo / "AGENTS.md").read_text(encoding="utf-8"), custom)
                self.assertFalse((repo / "CLAUDE.md").exists())

    def test_init_on_newer_install_refuses_downgrade(self):
        repo = self.git_repo("ph-init-newver-")
        agents = repo / ".agents"
        agents.mkdir()
        custom = "# 比本包新的已装版本\n"
        (agents / "AGENTS.md").write_text(custom, encoding="utf-8")
        (agents / "ph.json").write_text(
            json.dumps({"template_version": "9.9.9"}, indent=2) + "\n",
            encoding="utf-8",
        )
        before = (agents / "ph.json").read_bytes()
        proc = ph(repo, "init", "--apply")
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("9.9.9", proc.stderr, proc.stderr)
        self.assertIn(ph_init.RELEASE_VERSION, proc.stderr, proc.stderr)
        self.assertIn("downgrade", proc.stderr, proc.stderr)
        self.assertEqual((agents / "ph.json").read_bytes(), before)
        self.assertEqual((agents / "AGENTS.md").read_text(encoding="utf-8"), custom)

    # -- blocking: drift, shapes, mismatch, already installed ------------------

    def test_source_drift_between_dry_and_apply_blocks_and_writes_nothing(self):
        repo = self.git_repo("ph-adopt-drift-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})
        self.assert_ok(ph(repo, "init", "--adopt-plan", str(plan)), apply="false")

        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS + "dry 之后被外部修改。\n", encoding="utf-8")
        drifted = (repo / "AGENTS.md").read_bytes()
        proc = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(fields(proc.stdout).get("status"), "error", proc.stdout)
        self.assertIn("conflict", kinds_for(proc.stdout, "AGENTS.md"), proc.stdout)
        self.assertTrue(any("drift" in r for _k, p, r in items(proc.stdout) if p == "AGENTS.md"), proc.stdout)
        self.assertEqual((repo / "AGENTS.md").read_bytes(), drifted)
        self.assertFalse((repo / ".agents").exists())
        self.assertFalse((repo / "CLAUDE.md").exists())

        # A destination appearing at a null-pinned source also blocks.
        repo2 = self.git_repo("ph-adopt-newfile-")
        (repo2 / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        plan2 = self.write_plan(repo2, self.rule_pins(repo2), {".agents/AGENTS.md": merged})
        self.assert_ok(ph(repo2, "init", "--adopt-plan", str(plan2)), apply="false")
        (repo2 / "CLAUDE.md").write_text("后出现的文件\n", encoding="utf-8")
        proc2 = ph(repo2, "init", "--apply", "--adopt-plan", str(plan2))
        self.assertNotEqual(proc2.returncode, 0, proc2.stdout)
        self.assertIn("conflict", kinds_for(proc2.stdout, "CLAUDE.md"), proc2.stdout)
        self.assertFalse((repo2 / ".agents").exists())

    def test_wrong_links_and_mixed_mode_still_block(self):
        linked = self.git_repo("ph-adopt-wronglink-")
        (linked / "notes.md").write_text("别处的规则正文\n", encoding="utf-8")
        (linked / "AGENTS.md").symlink_to("notes.md")
        plan = self.write_plan(linked, self.rule_pins(linked), {".agents/AGENTS.md": self.merged_canonical("")})
        proc = ph(linked, "init", "--apply", "--adopt-plan", str(plan))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(item_map(proc.stdout)["AGENTS.md"][0], "conflict", proc.stdout)
        self.assertTrue((linked / "AGENTS.md").is_symlink())
        self.assertFalse((linked / ".agents").exists())

        mixed = self.git_repo("ph-adopt-mixed-")
        (mixed / "elsewhere.md").write_text("target\n", encoding="utf-8")
        (mixed / ".agents" / "AGENTS.md").parent.mkdir(parents=True)
        (mixed / ".agents" / "AGENTS.md").write_text("# canonical\n", encoding="utf-8")
        (mixed / "AGENTS.md").symlink_to(".agents/AGENTS.md")
        (mixed / "CLAUDE.md").write_text("普通正文\n", encoding="utf-8")
        plan_m = self.write_plan(mixed, self.rule_pins(mixed), {".agents/AGENTS.md": self.merged_canonical("")})
        proc_m = ph(mixed, "init", "--adopt-plan", str(plan_m))
        self.assertNotEqual(proc_m.returncode, 0, proc_m.stdout)
        self.assertIn("mixed", proc_m.stderr, proc_m.stderr)
        self.assertFalse((mixed / ".agents" / "ph.json").exists())

        locked = self.git_repo("ph-adopt-modelock-")
        (locked / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        plan_l = self.write_plan(locked, self.rule_pins(locked), {".agents/AGENTS.md": self.merged_canonical("")})
        proc_l = ph(locked, "init", "--adopt-plan", str(plan_l), "--mode", "symlink")
        self.assertNotEqual(proc_l.returncode, 0, proc_l.stdout)
        self.assertIn("locked", proc_l.stderr, proc_l.stderr)

    def test_existing_conflicting_agents_content_blocks_adopt(self):
        repo = self.git_repo("ph-adopt-agentsconflict-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        schema = repo / ".agents" / "ph.schema.json"
        schema.parent.mkdir(parents=True)
        schema.write_text("{}\n", encoding="utf-8")
        before = schema.read_bytes()
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})
        proc = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(item_map(proc.stdout)[".agents/ph.schema.json"][0], "conflict", proc.stdout)
        self.assertEqual(schema.read_bytes(), before)
        self.assertFalse((repo / ".agents" / "ph.json").exists())
        self.assertFalse((repo / "CLAUDE.md").exists())

    def test_hardlink_source_blocks_adopt(self):
        repo = self.git_repo("ph-adopt-hardlink-")
        body = repo / "shared-body.md"
        body.write_text(OLD_RULES_AGENTS, encoding="utf-8")
        root = repo / "AGENTS.md"
        os.link(body, root)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": self.merged_canonical("")})
        proc = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(item_map(proc.stdout)["AGENTS.md"][0], "conflict", proc.stdout)
        self.assertIn("hardlink", item_map(proc.stdout)["AGENTS.md"][1], proc.stdout)
        self.assertFalse((repo / ".agents").exists())

    def test_degenerated_git_symlink_source_blocks_adopt(self):
        # core.symlinks=false checkout shape: the index keeps mode 120000 while
        # the worktree entry is plain path text. The whole-set source check
        # must reject the shape even though Path.is_symlink() is false.
        repo = self.git_repo("ph-adopt-gitsymlink-")
        root = repo / "AGENTS.md"
        root.symlink_to(".agents/AGENTS.md")
        proc = run(["git", "add", "AGENTS.md"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        root.unlink()
        root.write_text(".agents/AGENTS.md\n", encoding="utf-8")
        before = root.read_bytes()
        merged = self.merged_canonical(".agents/AGENTS.md\n")
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})
        proc = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(fields(proc.stdout).get("status"), "error", proc.stdout)
        self.assertIn("conflict", kinds_for(proc.stdout, "AGENTS.md"), proc.stdout)
        self.assertTrue(any("symlink" in r for _k, p, r in items(proc.stdout) if p == "AGENTS.md"), proc.stdout)
        self.assertEqual(root.read_bytes(), before)
        self.assertFalse((repo / ".agents").exists())
        self.assertFalse((repo / "CLAUDE.md").exists())

    def test_plan_ancestor_file_conflicts_block_before_any_write(self):
        # docs/a and docs/a/b.md both absent on disk pass every per-file
        # check; the conflict exists only inside the planned write set and
        # must block in the plan phase, before a single file is written.
        repo = self.git_repo("ph-adopt-ancestor-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        internal = self.write_plan(
            repo,
            self.rule_pins(repo, **{"docs/a": None, "docs/a/b.md": None}),
            {".agents/AGENTS.md": merged, "docs/a": "# a\n", "docs/a/b.md": "# b\n"},
        )
        # Same shape across the plan and the scaffold home tree (the
        # scaffold deploys documents/架构地图/ as a directory).
        scaffold_cross = self.write_plan(
            repo,
            self.rule_pins(repo, **{".agents/project-harness/documents/架构地图": None}),
            {
                ".agents/AGENTS.md": merged,
                ".agents/project-harness/documents/架构地图": "# 旧式单文件\n",
            },
            name="cross.json",
        )
        for plan in (internal, scaffold_cross):
            with self.subTest(plan=plan.name):
                applied = None
                for extra in ((), ("--apply",)):
                    proc = ph(repo, "init", "--adopt-plan", str(plan), *extra)
                    applied = applied or proc
                    self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    self.assertEqual(fields(proc.stdout).get("status"), "error", proc.stdout)
                self.assertTrue(
                    any("as both file and directory" in r for _k, _p, r in items(applied.stdout)),
                    applied.stdout,
                )
                self.assertEqual((repo / "AGENTS.md").read_text(encoding="utf-8"), OLD_RULES_AGENTS)
                self.assertFalse((repo / ".agents").exists())
                self.assertFalse((repo / "docs").exists())
                self.assertFalse((repo / "CLAUDE.md").exists())

    # -- structural rejection of the plan itself --------------------------------

    def test_plan_file_location_and_shape_rejected(self):
        repo = self.git_repo("ph-adopt-planloc-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)

        inside = self.write_plan(
            repo,
            self.rule_pins(repo),
            {".agents/AGENTS.md": merged},
            path=repo / "adopt-plan.json",
        )
        proc = ph(repo, "init", "--adopt-plan", str(inside))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("outside the target repository", proc.stderr, proc.stderr)

        in_dist = self.write_plan(
            repo,
            self.rule_pins(repo),
            {".agents/AGENTS.md": merged},
            path=PH_INIT.parent.parent / "adopt-plan.json",
        )
        proc = ph(repo, "init", "--adopt-plan", str(in_dist))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("distribution root", proc.stderr, proc.stderr)

        real = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged}, name="real.json")
        linked = self._workspace / "linked-plan.json"
        linked.symlink_to(real.name)
        proc = ph(repo, "init", "--adopt-plan", str(linked))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("regular file", proc.stderr, proc.stderr)

        alias = self._workspace / "hardlinked-plan.json"
        os.link(real, alias)
        proc = ph(repo, "init", "--adopt-plan", str(alias))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("hardlink", proc.stderr, proc.stderr)
        self.assertFalse((repo / ".agents").exists())

    def test_plan_files_whitelist_and_required_canonical(self):
        repo = self.git_repo("ph-adopt-whitelist-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        pins = self.rule_pins(repo)
        cases = [
            ({".agents/AGENTS.md": merged, "AGENTS.md": merged}, "allowed write set"),
            ({".agents/AGENTS.md": merged, "CLAUDE.md": "x"}, "allowed write set"),
            ({".agents/AGENTS.md": merged, "docs": "x"}, "allowed write set"),
            ({".agents/AGENTS.md": merged, "../outside.md": "x"}, "repository-relative"),
            ({".agents/AGENTS.md": merged, "/etc/passwd": "x"}, "repository-relative"),
            ({".agents/AGENTS.md": merged, "readme.md": "x"}, "allowed write set"),
            ({}, "non-empty"),
            ({".agents/AGENTS.md": ""}, "non-empty"),
            ({".agents/AGENTS.md": merged, "docs/new.md": "x"}, "not pinned in sources"),
            ({".agents/AGENTS.md": merged, ".agents/project-harness/constitution.md": "# [PROJECT_NAME]"}, "materialized navigation"),
        ]
        for files, needle in cases:
            with self.subTest(files=sorted(files)):
                plan = self.write_plan(repo, pins, files)
                proc = ph(repo, "init", "--adopt-plan", str(plan))
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn(needle, proc.stderr, proc.stderr)
        missing_pin = self.write_plan(
            repo,
            {rel: pins[rel] for rel in ("AGENTS.md", ".agents/AGENTS.md")},
            {".agents/AGENTS.md": merged},
        )
        proc = ph(repo, "init", "--adopt-plan", str(missing_pin))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("CLAUDE.md", proc.stderr, proc.stderr)
        bad_hash = self.write_plan(
            repo,
            self.rule_pins(repo, **{"AGENTS.md": "deadbeef"}),
            {".agents/AGENTS.md": merged},
        )
        proc = ph(repo, "init", "--adopt-plan", str(bad_hash))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("SHA256", proc.stderr, proc.stderr)
        self.assertFalse((repo / ".agents").exists())

    def test_windows_reserved_components_rejected_unicode_paths_fine(self):
        repo = self.git_repo("ph-adopt-ntfs-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        pins = self.rule_pins(repo)
        bad_rels = [
            "docs/a:b.md",  # NTFS alternate data stream, not a file
            "docs/归档:笔记.md",
            "docs/a|b.md",
            "docs/a?.md",
            "docs/a<b.md",
            'docs/a"b.md',
        ]
        for rel in bad_rels:
            with self.subTest(files=rel):
                plan = self.write_plan(repo, pins, {".agents/AGENTS.md": merged, rel: "# x\n"})
                proc = ph(repo, "init", "--apply", "--adopt-plan", str(plan))
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("Windows-reserved", proc.stderr, proc.stderr)
        src_side = self.write_plan(
            repo,
            self.rule_pins(repo, **{"docs/a:b.md": None}),
            {".agents/AGENTS.md": merged},
            name="src-side.json",
        )
        proc = ph(repo, "init", "--adopt-plan", str(src_side))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Windows-reserved", proc.stderr, proc.stderr)
        self.assertFalse((repo / "docs").exists())
        self.assertFalse((repo / ".agents").exists())

        unicode_plan = self.write_plan(
            repo,
            self.rule_pins(repo, **{"docs/中文笔记.md": None}),
            {".agents/AGENTS.md": merged, "docs/中文笔记.md": "# 中文正文\n"},
            name="unicode.json",
        )
        proc = ph(repo, "init", "--adopt-plan", str(unicode_plan))
        self.assert_ok(proc, mode="portable", apply="false")
        self.assertEqual(item_map(proc.stdout)["docs/中文笔记.md"][0], "write", proc.stdout)
        self.assertFalse((repo / ".agents").exists(), "dry run must not write")

    def test_plan_version_and_repo_and_release_mismatch_rejected(self):
        repo = self.git_repo("ph-adopt-mismatch-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        other = self.git_repo("ph-adopt-other-")
        for override, needle in (
            ({"version": 2}, "adopt plan.version"),
            ({"release_version": "0.0.9"}, "adopt plan.release_version"),
            ({"plan_repo": str(other)}, "absolute target repository"),
            ({"plan_repo": "relative/repo"}, "absolute target repository"),
        ):
            with self.subTest(override=override):
                plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged}, **override)
                proc = ph(repo, "init", "--adopt-plan", str(plan))
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn(needle, proc.stderr, proc.stderr)
        self.assertFalse((repo / ".agents").exists())

    def test_installed_repo_rejects_adopt_and_check_sync_reject_flag(self):
        repo = self.git_repo("ph-adopt-installed-")
        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        merged = self.merged_canonical(OLD_RULES_AGENTS)
        plan = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged})
        self.assert_ok(ph(repo, "init", "--apply", "--adopt-plan", str(plan)), apply="true")

        (repo / "AGENTS.md").write_text(OLD_RULES_AGENTS, encoding="utf-8")
        plan2 = self.write_plan(repo, self.rule_pins(repo), {".agents/AGENTS.md": merged}, name="second.json")
        proc = ph(repo, "init", "--apply", "--adopt-plan", str(plan2))
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("already installed", proc.stderr, proc.stderr)
        self.assertEqual((repo / "AGENTS.md").read_text(encoding="utf-8"), OLD_RULES_AGENTS, "adopt must not overwrite an installed repo")
        self.assertEqual((repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"), merged)

        for action in ("check", "sync"):
            proc = ph(repo, action, "--adopt-plan", str(plan2))
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("--adopt-plan only applies to init", proc.stderr, proc.stderr)


if __name__ == "__main__":
    unittest.main()
