#!/usr/bin/env python3
"""Init preserves existing safe docs/** files; missing docs still install."""

from __future__ import annotations

import os
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

# Since 1.2.1 the scaffold ships no docs/ tree: the docs-like PH content
# lives under the project-harness home roots (constraints/ documents/), and
# init must never overwrite a differing existing file there. Legacy docs/**
# files are business content PH does not manage; a fresh init neither maps
# nor touches them.
HOME = ".agents/project-harness"
CUSTOM_DOCS = {
    f"{HOME}/constraints/harness规范/文档治理规范.md": "# 文档治理\n使用时机：维护项目文档时。\n项目定制规范正文。\n",
    f"{HOME}/documents/项目概述.md": "# 项目概述\n项目 Wiki 正文。\n",
}
MISSING_DOCS = (
    f"{HOME}/documents/功能地图.md",
    f"{HOME}/constraints/测试规范/门禁规范.md",
)
EXTRA_DOC = "docs/项目Wiki/自定义存量.md"
PAYLOAD_NEW_DOC = "docs/约束规范/工程规范/传递验收.md"


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


class ExistingDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PH_INIT
        cls._source = Path(tempfile.mkdtemp(prefix="ph-existing-docs-payload-"))
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

    def tearDown(self):
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-existing-docs-{stamp}-{os.getpid()}"
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

    def write_custom_docs(self, repo: Path) -> dict[str, bytes]:
        kept = {}
        for rel, text in CUSTOM_DOCS.items():
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = text.encode("utf-8")
            dest.write_bytes(data)
            kept[rel] = data
        extra = repo / EXTRA_DOC
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("# 仅项目所有\n", encoding="utf-8")
        kept[EXTRA_DOC] = extra.read_bytes()
        return kept

    def assert_ok(self, proc, **expect):
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        got = fields(proc.stdout)
        self.assertEqual(got.get("status"), "ok", proc.stdout)
        for key, value in expect.items():
            self.assertEqual(got.get(key), value, proc.stdout)
        self.assertNotRegex(proc.stdout, r"(?m)^item=(conflict|block|error)\t", proc.stdout)

    def test_is_docs_rel_only_docs_tree(self):
        self.assertTrue(ph_init.is_docs_rel("docs"))
        self.assertTrue(ph_init.is_docs_rel("docs/README.md"))
        self.assertTrue(ph_init.is_docs_rel("docs/约束规范/工程规范/文档治理.md"))
        self.assertFalse(ph_init.is_docs_rel("docsfile.md"))
        self.assertFalse(ph_init.is_docs_rel(".agents/docs/README.md"))
        self.assertFalse(ph_init.is_docs_rel("AGENTS.md"))

    def test_classify_docs_scaffold_shared_plan_apply(self):
        workspace = self.temp_dir("ph-docs-classify-ws-")
        repo = workspace / "repo"
        repo.mkdir()
        for argv in (
            ["git", "init"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "ph-init-test"],
        ):
            proc = run(argv, cwd=repo)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        dest = repo / "docs" / "README.md"
        dest.parent.mkdir(parents=True)
        data = b"# template\n"
        self.assertEqual(ph_init.classify_docs_scaffold(repo, dest, data), ("write", "scaffold", None))
        dest.write_bytes(data)
        self.assertEqual(
            ph_init.classify_docs_scaffold(repo, dest, data),
            ("skip", "scaffold: identical", None),
        )
        dest.write_bytes(b"# custom\n")
        self.assertEqual(
            ph_init.classify_docs_scaffold(repo, dest, data),
            ("skip", "scaffold: 保留待会话审阅", None),
        )
        outside = workspace / "outside.md"
        outside.write_bytes(b"x")
        kind, reason, problem = ph_init.classify_docs_scaffold(repo, outside, data)
        self.assertEqual(kind, "conflict")
        self.assertEqual(problem, ph_init.PROBLEM_OUTSIDE_REPO)

        linked = repo / "docs" / "linked.md"
        linked.symlink_to("README.md")
        kind, reason, problem = ph_init.classify_docs_scaffold(repo, linked, data)
        self.assertEqual((kind, problem), ("conflict", ph_init.PROBLEM_DEST_SYMLINK))

        as_dir = repo / "docs" / "dir.md"
        as_dir.mkdir(parents=True)
        kind, reason, problem = ph_init.classify_docs_scaffold(repo, as_dir, data)
        self.assertEqual((kind, problem), ("conflict", ph_init.PROBLEM_NOT_REGULAR_FILE))

        hard = repo / "docs" / "hard.md"
        hard.write_bytes(b"custom-hard")
        alias = repo / "hard-alias.md"
        os.link(hard, alias)
        kind, reason, problem = ph_init.classify_docs_scaffold(repo, hard, data)
        self.assertEqual((kind, problem), ("conflict", ph_init.PROBLEM_HARDLINK))

        (repo / "elsewhere").mkdir()
        (repo / "docs-link-root").symlink_to("elsewhere")
        through = repo / "docs-link-root" / "README.md"
        kind, reason, problem = ph_init.classify_docs_scaffold(repo, through, data)
        self.assertEqual((kind, problem), ("conflict", ph_init.PROBLEM_NESTED_LINK))

        file_ancestor = repo / "docs" / "约束规范"
        file_ancestor.write_text("not-a-directory", encoding="utf-8")
        nested = repo / "docs" / "约束规范" / "工程规范" / "文档治理.md"
        kind, reason, problem = ph_init.classify_docs_scaffold(repo, nested, data)
        self.assertEqual((kind, problem), ("conflict", ph_init.PROBLEM_NOT_DIRECTORY))

    def test_portable_and_symlink_preserve_existing_docs(self):
        for mode in ("portable", "symlink"):
            with self.subTest(mode=mode):
                repo = self.git_repo(f"ph-docs-{mode}-")
                kept = self.write_custom_docs(repo)
                before = {rel: (repo / rel).read_bytes() for rel in kept}
                dry = ph(repo, "init", "--mode", mode)
                self.assert_ok(dry, action="init", mode=mode, apply="false")
                mapped = item_map(dry.stdout)
                for rel in CUSTOM_DOCS:
                    self.assertEqual(mapped[rel], ("skip", "scaffold: 保留待会话审阅"), dry.stdout)
                for rel in MISSING_DOCS:
                    self.assertEqual(mapped[rel], ("write", "scaffold"), dry.stdout)
                    self.assertFalse((repo / rel).exists(), rel)
                # legacy docs/ files are not PH-managed: no plan item at all
                self.assertNotIn(EXTRA_DOC, mapped, dry.stdout)
                self.assertEqual({rel: (repo / rel).read_bytes() for rel in kept}, before)

                applied = ph(repo, "init", "--apply", "--mode", mode)
                self.assert_ok(applied, action="init", mode=mode, apply="true")
                self.assertEqual(item_map(applied.stdout), mapped)
                for rel, data in before.items():
                    self.assertEqual((repo / rel).read_bytes(), data, rel)
                for rel in MISSING_DOCS:
                    self.assertEqual((repo / rel).read_bytes(), (SCAFFOLD / rel).read_bytes(), rel)

    def test_non_docs_root_and_agents_conflicts_fail_closed(self):
        repo = self.git_repo("ph-docs-nondocs-")
        kept = self.write_custom_docs(repo)
        agents = repo / ".agents" / "AGENTS.md"
        agents.parent.mkdir(parents=True, exist_ok=True)
        agents.write_text("# custom agents\nnot scaffold\n", encoding="utf-8")
        root_agents = repo / "AGENTS.md"
        root_agents.write_text("# stray root agents\n", encoding="utf-8")
        before_docs = {rel: (repo / rel).read_bytes() for rel in kept}
        before_agents = agents.read_bytes()
        before_root = root_agents.read_bytes()

        dry = ph(repo, "init", "--mode", "portable")
        self.assertNotEqual(dry.returncode, 0, dry.stdout)
        self.assertEqual(fields(dry.stdout).get("status"), "error", dry.stdout)
        mapped = item_map(dry.stdout)
        self.assertEqual(mapped[".agents/AGENTS.md"][0], "conflict", dry.stdout)
        self.assertIn("existing file differs", mapped[".agents/AGENTS.md"][1])
        for rel in CUSTOM_DOCS:
            self.assertEqual(mapped[rel], ("skip", "scaffold: 保留待会话审阅"), dry.stdout)
        self.assertNotIn(EXTRA_DOC, mapped, dry.stdout)

        applied = ph(repo, "init", "--apply", "--mode", "portable")
        self.assertNotEqual(applied.returncode, 0, applied.stdout)
        self.assertEqual({rel: (repo / rel).read_bytes() for rel in kept}, before_docs)
        self.assertEqual(agents.read_bytes(), before_agents)
        self.assertEqual(root_agents.read_bytes(), before_root)
        for rel in MISSING_DOCS:
            self.assertFalse((repo / rel).exists(), rel)

    def test_unsafe_docs_shapes_conflict_and_do_not_write(self):
        # the same fail-closed protection now guards the home roots the
        # scaffold actually deploys (constraints/ documents/)
        repo = self.git_repo("ph-docs-unsafe-")
        (repo / HOME / "constraints" / "工程规范").mkdir(parents=True, exist_ok=True)
        outside_target = repo / "outside-readme.md"
        outside_target.write_text("escape", encoding="utf-8")
        (repo / HOME / "constraints" / "工程规范" / "Git规范.md").symlink_to("../outside-readme.md")
        (repo / HOME / "constraints" / "工程规范").mkdir(parents=True, exist_ok=True)
        as_dir = repo / HOME / "constraints" / "harness规范" / "文档治理规范.md"
        as_dir.mkdir(parents=True)
        (repo / "wiki-elsewhere").mkdir()
        (repo / HOME / "documents").mkdir(parents=True)
        (repo / HOME / "documents" / "架构地图").symlink_to("../wiki-elsewhere")
        (repo / HOME / "documents" / "领域").write_text("not-a-directory", encoding="utf-8")

        dry = ph(repo, "init", "--mode", "portable")
        self.assertNotEqual(dry.returncode, 0, dry.stdout)
        mapped = item_map(dry.stdout)
        self.assertEqual(mapped[f"{HOME}/constraints/工程规范/Git规范.md"][0], "conflict", dry.stdout)
        self.assertIn("symlink", mapped[f"{HOME}/constraints/工程规范/Git规范.md"][1])
        self.assertEqual(mapped[f"{HOME}/constraints/harness规范/文档治理规范.md"][0], "conflict", dry.stdout)
        self.assertIn("not a regular file", mapped[f"{HOME}/constraints/harness规范/文档治理规范.md"][1])
        wiki = mapped[f"{HOME}/documents/架构地图/README.md"]
        self.assertEqual(wiki[0], "conflict", dry.stdout)
        self.assertTrue("symlink" in wiki[1] or "outside" in wiki[1], wiki)
        domain = mapped[f"{HOME}/documents/领域/README.md"]
        self.assertEqual(domain[0], "conflict", dry.stdout)
        self.assertIn("not a directory", domain[1])

        applied = ph(repo, "init", "--apply", "--mode", "portable")
        self.assertNotEqual(applied.returncode, 0, applied.stdout)
        self.assertTrue((repo / HOME / "constraints" / "工程规范" / "Git规范.md").is_symlink())
        self.assertTrue(as_dir.is_dir())
        self.assertTrue((repo / HOME / "documents" / "架构地图").is_symlink())
        self.assertTrue((repo / HOME / "documents" / "领域").is_file())
        self.assertFalse((repo / HOME / "documents" / "功能地图.md").exists())

    def test_sync_does_not_rewrite_project_docs(self):
        repo = self.git_repo("ph-docs-sync-")
        kept = self.write_custom_docs(repo)
        self.assert_ok(ph(repo, "init", "--apply", "--mode", "portable"), action="init", apply="true")
        for rel, text in CUSTOM_DOCS.items():
            (repo / rel).write_text(text + "安装后再改。\n", encoding="utf-8")
        after_init = {rel: (repo / rel).read_bytes() for rel in (*CUSTOM_DOCS, EXTRA_DOC, *MISSING_DOCS)}
        dry = ph(repo, "sync", "--mode", "portable")
        self.assert_ok(dry, action="sync", mode="portable", apply="false")
        self.assertEqual({rel: (repo / rel).read_bytes() for rel in after_init}, after_init)
        applied = ph(repo, "sync", "--apply", "--mode", "portable")
        self.assert_ok(applied, action="sync", mode="portable", apply="true")
        self.assertEqual({rel: (repo / rel).read_bytes() for rel in after_init}, after_init)
        for rel in CUSTOM_DOCS:
            self.assertIn("安装后再改", (repo / rel).read_text(encoding="utf-8"))

    def test_self_install_payload_can_deliver_new_docs(self):
        first = self.git_repo("ph-docs-payload-src-")
        self.assert_ok(ph(first, "init", "--apply", "--mode", "portable"), action="init", apply="true")
        installed = first / ".agents" / "skills" / "ph-init" / "scripts" / "ph_init.py"
        new_doc = first / ".agents" / "skills" / "ph-init" / "assets" / "scaffold" / PAYLOAD_NEW_DOC
        new_doc.parent.mkdir(parents=True, exist_ok=True)
        payload = "# 新文档\n使用时机：查看新增规范时。\n应由已安装 payload 传到下一仓。\n".encode("utf-8")
        new_doc.write_bytes(payload)

        second = self.git_repo("ph-docs-payload-dst-")
        kept = self.write_custom_docs(second)
        applied = ph(second, "init", "--apply", "--mode", "portable", script=installed)
        self.assert_ok(applied, action="init", mode="portable", apply="true")
        mapped = item_map(applied.stdout)
        self.assertEqual(mapped[PAYLOAD_NEW_DOC], ("write", "scaffold"), applied.stdout)
        self.assertEqual((second / PAYLOAD_NEW_DOC).read_bytes(), payload)
        for rel, data in kept.items():
            self.assertEqual((second / rel).read_bytes(), data, rel)
        for rel in CUSTOM_DOCS:
            self.assertEqual(mapped[rel], ("skip", "scaffold: 保留待会话审阅"), applied.stdout)


if __name__ == "__main__":
    unittest.main()
