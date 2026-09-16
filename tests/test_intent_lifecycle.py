#!/usr/bin/env python3
"""Intent scaffold and installer regression tests.

Markdown checks cover this repo's ordinary ``[text](rel)`` links,
not full CommonMark.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
PH_INIT = REPO_ROOT / "scripts" / "ph_init.py"
SCAFFOLD = REPO_ROOT / "assets" / "scaffold"
TRASH_ROOT = Path.home() / "trash"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ph_init  # noqa: E402
MD_LINK = re.compile(r"(?<!!)\[.*?\]\(([^)]+)\)")
REQUIRED_SKILLS = (
    "ph-init", "ph-worktree-enter", "ph-worktree-exit",
    "ph-memory-capture", "ph-memory-archive", "ph-memory-ask",
    "ph-intent-new", "ph-intent-impl", "ph-intent-verify", "ph-intent-drop",
    "ph-merge-update", "ph-docs-sync",
)
STATUS_DIRS = (
    "docs/意图/待办/新特性", "docs/意图/待办/问题记录",
    "docs/意图/实施/新特性", "docs/意图/实施/问题记录",
)


def run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=60)


def ph(repo, *args, script=None):
    return run([sys.executable, str(script or PH_INIT), *args, "--repo", str(repo)])


def fields(stdout):
    return dict(line.split("=", 1) for line in stdout.splitlines()
                if "=" in line and not line.startswith("item="))


def tree(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [n for n in dirnames if n not in {".git", "__pycache__"}]
        for name in dirnames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            out[rel + "/"] = f"link:{os.readlink(path)}" if path.is_symlink() else "dir"
        for name in filenames:
            path = Path(dirpath) / name
            if name == ".DS_Store" or path.suffix in {".pyc", ".pyo"}:
                continue
            rel = path.relative_to(root).as_posix()
            out[rel] = f"link:{os.readlink(path)}" if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def resolved_links(path):
    found = set()
    for target in MD_LINK.findall(path.read_text(encoding="utf-8")):
        href = target.strip().split("#", 1)[0]
        if href and not href.startswith(("http://", "https://", "mailto:")):
            found.add((path.parent / href).resolve())
    return found


def line_field(text, key):
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip("\"'")
    raise AssertionError(f"missing {key}: field")


class IntentLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PH_INIT
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import ph_init
        cls._source = Path(tempfile.mkdtemp(prefix="ph-intent-payload-"))
        for src in ph_init.ph_init_payload_files():
            dest = cls._source / src.relative_to(REPO_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
        PH_INIT = cls._source / "scripts/ph_init.py"

    @classmethod
    def tearDownClass(cls):
        TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        cls._source.rename(TRASH_ROOT / cls._source.name)

    def setUp(self):
        self._temps = []

    def tearDown(self):
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-intent-lifecycle-{stamp}-{os.getpid()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=False)
        for i, path in enumerate(self._temps):
            if path.exists():
                path.rename(dest / f"{i:02d}-{path.name}")

    def git_repo(self, prefix):
        root = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(root)
        for argv in (["git", "init"], ["git", "config", "user.email", "t@example.com"],
                     ["git", "config", "user.name", "ph-init-test"]):
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

    def init_apply(self, prefix, mode="portable", script=None):
        repo = self.git_repo(prefix)
        args = ("init", "--apply") if mode is None else ("init", "--apply", "--mode", mode)
        expect = {"action": "init", "apply": "true"}
        if mode is not None:
            # An explicit mode is echoed back verbatim; mode=None leaves the
            # auto default, and the caller asserts the resolved value.
            expect["mode"] = mode
        self.assert_ok(ph(repo, *args, script=script), **expect)
        return repo

    def assert_layout(self, repo):
        for name in REQUIRED_SKILLS:
            self.assertTrue((repo / ".agents/skills" / name / "SKILL.md").is_file(), name)
            self.assertTrue((repo / ".claude/skills" / name / "SKILL.md").exists(), name)
        # Codex and OpenCode read AGENTS.md and .agents/skills natively:
        # the minimal adapter topology creates no vendor directory for them.
        self.assertFalse((repo / ".codex").exists())
        self.assertFalse((repo / ".opencode").exists())
        for rel in STATUS_DIRS:
            self.assertTrue((repo / rel / "README.md").is_file(), rel)
        self.assertFalse((repo / "docs/意图/进行中").exists())
        self.assertEqual(line_field((repo / "docs/意图/_模板.md").read_text(encoding="utf-8"), "status_dir"),
                         "待办/新特性")
        for rel in (".agents/AGENTS.md", ".agents/ph.json", "AGENTS.md", "CLAUDE.md", ".gitignore"):
            self.assertTrue((repo / rel).exists(), rel)

    def test_scaffold_default_status_dirs(self):
        for rel in STATUS_DIRS:
            self.assertTrue((SCAFFOLD / rel / "README.md").is_file(), rel)
        intent = SCAFFOLD / "docs/意图"
        self.assertFalse((intent / "进行中").exists())
        self.assertEqual(line_field((intent / "_模板.md").read_text(encoding="utf-8"), "status_dir"),
                         "待办/新特性")

    def test_intent_and_agents_markdown_links_and_readme_indexes(self):
        docs, agents = SCAFFOLD / "docs", SCAFFOLD / ".agents/AGENTS.md"
        checked = 0
        for path in (*docs.rglob("*.md"), agents):
            for dest in resolved_links(path):
                checked += 1
                self.assertTrue(dest.exists(), f"broken link in {path} -> {dest}")
        self.assertGreater(checked, 0)
        for directory in (docs, *sorted(p for p in docs.rglob("*") if p.is_dir())):
            readme = directory / "README.md"
            self.assertTrue(readme.is_file(), f"missing README: {directory}")
            linked = resolved_links(readme)
            missing = [c.name for c in directory.iterdir()
                       if c.name not in {"README.md", ".DS_Store"}
                       and c.resolve() not in linked
                       and (c / "README.md").resolve() not in linked]
            self.assertEqual(missing, [], f"{readme} missing {missing}")

    def test_eval_json_and_skill_frontmatter(self):
        skills = [REPO_ROOT / "SKILL.md", *sorted((SCAFFOLD / ".agents/skills").glob("*/SKILL.md"))]
        names = []
        for skill in skills:
            text = skill.read_text(encoding="utf-8")
            name, description = line_field(text, "name"), line_field(text, "description")
            self.assertEqual(name, "ph-init" if skill.parent == REPO_ROOT else skill.parent.name)
            self.assertTrue(description)
            self.assertLessEqual(len(description), 1024, name)
            names.append(name)
        self.assertEqual(sorted(names), sorted(REQUIRED_SKILLS))
        seen = []
        for path in [REPO_ROOT / "evals/evals.json",
                     *sorted((SCAFFOLD / ".agents/skills").glob("*/evals/evals.json"))]:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["evals"], path)
            seen.append(data["skill_name"])
            for item in data["evals"]:
                self.assertTrue(str(item["prompt"]).strip() and str(item["expected_output"]).strip())
        self.assertEqual(len(seen), len(set(seen)))
        self.assertTrue(set(seen).issubset(REQUIRED_SKILLS))

    def test_real_ph_init_dry_run_apply_check_both_modes(self):
        empty = self.git_repo("ph-intent-dry-")
        before = tree(empty)
        dry = ph(empty, "init", "--mode", "portable")
        self.assert_ok(dry, action="init", mode="portable", apply="false")
        self.assertEqual(tree(empty), before)
        self.assertIn("item=write", dry.stdout)
        portable = self.init_apply("ph-intent-portable-")
        self.assert_ok(ph(portable, "check", "--mode", "portable"), action="check", mode="portable", apply="false")
        self.assert_layout(portable)
        symlink = self.init_apply("ph-intent-symlink-", "symlink")
        self.assert_ok(ph(symlink, "check", "--mode", "symlink"), action="check", mode="symlink", apply="false")
        self.assert_layout(symlink)

    def test_portable_bytes_and_symlink_relative_adapters(self):
        portable = self.init_apply("ph-intent-bytes-")
        canonical = portable / ".agents/AGENTS.md"
        self.assertFalse((portable / "AGENTS.md").is_symlink())
        self.assertEqual((portable / "AGENTS.md").read_bytes(), canonical.read_bytes())
        self.assertEqual((portable / "CLAUDE.md").read_bytes(), b"@.agents/AGENTS.md\n")
        for name in REQUIRED_SKILLS:
            src = portable / ".agents/skills" / name
            dest = portable / ".claude/skills" / name
            self.assertFalse(dest.is_symlink(), dest)
            self.assertEqual(tree(src), tree(dest), dest)
        symlink = self.init_apply("ph-intent-rel-", "symlink")
        pairs = [(symlink / "AGENTS.md", symlink / ".agents/AGENTS.md"),
                 (symlink / "CLAUDE.md", symlink / ".agents/AGENTS.md")]
        for name in REQUIRED_SKILLS:
            src = symlink / ".agents/skills" / name
            pairs.append((symlink / ".claude/skills" / name, src))
        for dest, target in pairs:
            self.assertTrue(dest.is_symlink(), dest)
            raw = os.readlink(dest)
            self.assertFalse(os.path.isabs(raw), raw)
            self.assertEqual(Path(raw).as_posix(), Path(os.path.relpath(target, dest.parent)).as_posix())
            self.assertEqual((dest.parent / raw).resolve(), target.resolve())

    def test_sync_leaves_legacy_in_progress_user_docs(self):
        repo = self.init_apply("ph-intent-sync-")
        intent_id = "INT-20260101-legacy-export"
        legacy = repo / "docs/意图/进行中/新特性"
        legacy.mkdir(parents=True)
        intent = legacy / f"{intent_id}.md"
        intent.write_text(
            f"---\nintent_id: \"{intent_id}\"\ntype: feature\nstatus_dir: 进行中/新特性\n---\n"
            f"# {intent_id}\n\n用户遗留的旧进行中意图，sync 不得自动迁移。\n",
            encoding="utf-8",
        )
        readme = legacy / "README.md"
        readme.write_text(f"# 新特性\n\n[{intent_id}.md](./{intent_id}.md)\n", encoding="utf-8")
        before, intent_b, readme_b = tree(repo / "docs"), intent.read_bytes(), readme.read_bytes()
        self.assert_ok(ph(repo, "sync", "--mode", "portable"), action="sync", mode="portable", apply="false")
        self.assertEqual(tree(repo / "docs"), before)
        self.assert_ok(ph(repo, "sync", "--apply", "--mode", "portable"), action="sync", mode="portable", apply="true")
        self.assertEqual(tree(repo / "docs"), before)
        self.assertEqual((intent.read_bytes(), readme.read_bytes()), (intent_b, readme_b))
        self.assertFalse((repo / f"docs/意图/实施/新特性/{intent_id}.md").exists())
        self.assertFalse((repo / f"docs/意图/待办/新特性/{intent_id}.md").exists())
        self.assertEqual(line_field(intent.read_text(encoding="utf-8"), "status_dir"), "进行中/新特性")

    def test_installed_copy_can_init_second_repo(self):
        first = self.init_apply("ph-intent-first-")
        installed = first / ".agents/skills/ph-init/scripts/ph_init.py"
        self.assertTrue(installed.is_file())
        self.assertTrue((first / ".agents/skills/ph-init/assets/scaffold").is_dir())
        # Default (auto) install through the installed copy: apply resolves a
        # concrete mode, so the report never claims mode=auto after writing.
        second = self.init_apply("ph-intent-second-", mode=None, script=installed)
        self.assert_layout(second)
        self.assertTrue((second / ".agents/skills/ph-init/scripts/ph_init.py").is_file())
        manifest = json.loads((second / ".agents" / "ph.json").read_text(encoding="utf-8"))
        self.assertIn(manifest["adapter_mode"], ("portable", "symlink"))
        self.assertEqual(sorted(manifest["adapters"]), ["claude_entry", "claude_skills", "root_agents"])
        self.assert_ok(
            ph(second, "check", script=installed),
            action="check",
            mode=manifest["adapter_mode"],
            apply="false",
        )

    # -- auto mode and the minimal three-tool adapter topology ----------------

    def test_auto_dry_run_writes_nothing_and_defers_resolution(self):
        repo = self.git_repo("ph-intent-autodry-")
        before = tree(repo)
        dry = ph(repo, "init")
        self.assert_ok(dry, action="init", mode="auto", apply="false")
        self.assertIn("auto mode: symlink vs portable is resolved at apply time", dry.stdout)
        self.assertIn("if portable:", dry.stdout)
        self.assertIn("if symlink:", dry.stdout)
        self.assertIn("\t.agents/ph.json\t", dry.stdout)
        self.assertIn("\t.claude/skills", dry.stdout)
        # Read-only also means no destination-filesystem probe and no writes.
        self.assertEqual(tree(repo), before)
        self.assertFalse((repo / ".claude").exists())
        self.assertFalse(any(p.name.startswith(".ph-link-probe-") for p in repo.iterdir()))

    def test_auto_mode_prefers_symlink_when_supported(self):
        repo = self.git_repo("ph-intent-autolink-")
        if ph_init.symlink_blocker(repo):
            self.skipTest("this filesystem or git cannot keep real symlinks")
        applied = ph(repo, "init", "--apply")
        self.assert_ok(applied, action="init", mode="symlink", apply="true")
        self.assertTrue((repo / "AGENTS.md").is_symlink())
        manifest = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["adapter_mode"], "symlink")
        self.assertEqual(sorted(manifest["adapters"]), ["claude_entry", "claude_skills", "root_agents"])
        self.assert_layout(repo)
        self.assert_ok(ph(repo, "check"), action="check", mode="symlink", apply="false")

    def test_auto_mode_downgrades_to_portable_when_core_symlinks_false(self):
        repo = self.git_repo("ph-intent-autofalse-")
        proc = run(["git", "config", "core.symlinks", "false"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        applied = ph(repo, "init", "--apply")
        self.assert_ok(applied, action="init", mode="portable", apply="true")
        # The downgrade reason is an explicit report item, not a silent pick.
        self.assertIn(
            "auto mode: symlink unavailable (git core.symlinks is explicitly false); installing portable",
            applied.stdout,
        )
        self.assertFalse((repo / "AGENTS.md").is_symlink())
        self.assertEqual((repo / "CLAUDE.md").read_bytes(), b"@.agents/AGENTS.md\n")
        self.assert_ok(ph(repo, "check"), action="check", mode="portable", apply="false")

    def test_auto_mode_downgrades_when_os_symlink_probe_fails(self):
        repo = self.git_repo("ph-intent-osfail-")
        report = ph_init.Report("init", "auto", True)
        with mock.patch.object(ph_init.os, "symlink", side_effect=OSError("no links here")):
            mode = ph_init.resolve_auto_mode(report, repo)
        self.assertEqual(mode, "portable")
        reasons = [item.reason for item in report.items]
        self.assertTrue(any("os.symlink failed" in reason for reason in reasons), reasons)

    def test_explicit_symlink_mode_fails_hard_when_core_symlinks_false(self):
        repo = self.git_repo("ph-intent-strict-")
        proc = run(["git", "config", "core.symlinks", "false"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        # A dry run never probes, so explicit symlink stays ok until apply.
        before = tree(repo)
        self.assert_ok(ph(repo, "init", "--mode", "symlink"), action="init", mode="symlink", apply="false")
        self.assertEqual(tree(repo), before)
        applied = ph(repo, "init", "--apply", "--mode", "symlink")
        self.assertNotEqual(applied.returncode, 0, applied.stdout)
        self.assertEqual(fields(applied.stdout).get("status"), "error", applied.stdout)
        self.assertIn("item=block\t.", applied.stdout)
        self.assertIn("core.symlinks", applied.stdout)
        self.assertEqual(tree(repo), before, "blocked symlink apply must write nothing")

    def test_installed_portable_repo_locks_mode_against_auto_default(self):
        repo = self.init_apply("ph-intent-locked-")
        # The auto default must follow the repository's locked portable mode,
        # never convert it, and an explicit symlink keeps being refused.
        again = ph(repo, "init", "--apply")
        self.assert_ok(again, action="init", mode="portable", apply="true")
        self.assertFalse((repo / "AGENTS.md").is_symlink())
        self.assertFalse((repo / "CLAUDE.md").is_symlink())
        refused = ph(repo, "init", "--apply", "--mode", "symlink")
        self.assertNotEqual(refused.returncode, 0, refused.stdout + refused.stderr)
        self.assertIn("locked", refused.stderr, refused.stderr)
        self.assert_ok(ph(repo, "check"), action="check", mode="portable", apply="false")

    def test_auto_conflicting_adapter_parent_blocks_before_probe(self):
        repo = self.git_repo("ph-auto-parent-")
        (repo / ".claude").mkdir()
        (repo / ".claude/skills").write_text("user content\n")
        before = tree(repo)
        with mock.patch.object(ph_init, "symlink_blocker", side_effect=AssertionError("must not probe")):
            for apply in (False, True):
                result = ph_init.cmd_init(repo, "auto", apply)
                self.assertTrue(result.blocked)
                self.assertIn("skill adapter parent", result.render())
        self.assertEqual(tree(repo), before)

    def test_directory_link_probe_failure_falls_back_before_install(self):
        repo = self.git_repo("ph-auto-directory-")
        real_symlink = os.symlink

        def files_only(src, dst, target_is_directory=False, **kwargs):
            if target_is_directory:
                raise OSError("directory links disabled")
            return real_symlink(src, dst, target_is_directory=target_is_directory, **kwargs)

        with mock.patch.object(ph_init, "skill_root", return_value=self._source), \
                mock.patch.object(ph_init.os, "symlink", side_effect=files_only):
            result = ph_init.cmd_init(repo, "auto", True)
        self.assertFalse(result.blocked, result.render())
        self.assertEqual(result.mode, "portable")
        self.assertIn("directory links disabled", result.render())
        self.assertFalse((repo / "AGENTS.md").is_symlink())
        self.assertFalse(any(p.name.startswith(".ph-link-probe-") for p in repo.iterdir()))

    def test_apply_directory_symlink_passes_windows_flag(self):
        repo = self.git_repo("ph-directory-flag-")
        target = repo / "skill"
        target.mkdir()
        with mock.patch.object(Path, "symlink_to") as create:
            ph_init.apply_one_symlink(repo / "adapter", target, repo)
        create.assert_called_once_with("skill", target_is_directory=True)

    def test_check_reports_retired_codex_but_preserves_user_skills(self):
        repo = self.init_apply("ph-check-codex-")
        root = repo / ".codex/skills"
        root.mkdir(parents=True)
        (root / "my-tool").mkdir()
        self.assert_ok(ph(repo, "check"))
        legacy = root / "ph-init"
        legacy.symlink_to("../../.agents/skills/ph-init", target_is_directory=True)
        before = tree(repo)
        checked = ph(repo, "check")
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("retired Codex PH adapter", checked.stdout)
        self.assertEqual(tree(repo), before)

    def test_zcode_skills_directory_no_longer_blocks_check(self):
        repo = self.init_apply("ph-intent-zcode-")
        (repo / ".zcode" / "skills").mkdir(parents=True)
        checked = ph(repo, "check", "--mode", "portable")
        self.assert_ok(checked, action="check", mode="portable", apply="false")
        self.assertNotIn(".zcode/skills", checked.stdout)


if __name__ == "__main__":
    unittest.main()
