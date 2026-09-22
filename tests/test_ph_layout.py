from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ph_layout


class RuntimePathTests(unittest.TestCase):
    def test_source_paths_and_shell_root(self):
        text = ('"$dir/.specify" "$REPO_ROOT/specs" .specify/memory/constitution.md '
                '`specs/001-example/spec.md`\n(cd "$script_dir/../../.." && pwd)')
        result = ph_layout.convert_runtime_text(text, ".specify/scripts/bash/common.sh")
        self.assertNotIn("/.specify", result)
        self.assertIn(ph_layout.CONSTITUTION, result)
        self.assertIn(ph_layout.SPECS + "/001-example/spec.md", result)
        self.assertIn('$script_dir/../../../../..', result)

    def test_real_pinned_scripts_work_without_old_directories(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _speckit_seed
        import ph_speckit
        _speckit_seed.ensure_seed()
        staging = ph_speckit.resolve_staging(None, ph_speckit.speckit_contract())
        repo = Path(tempfile.mkdtemp(prefix="ph-layout-runtime-"))
        result = ph_speckit.cmd_install(repo, True, None)
        self.assertFalse(result["blocked"], result)
        scripts = repo / ph_layout.RUNTIME / "scripts/bash"
        for script in scripts.glob("*.sh"):
            subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True)
        proc = subprocess.run(["bash", str(scripts / "create-new-feature.sh"), "--json", "--short-name", "sample", "Example feature"], cwd=repo, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((repo / ".specify").exists())
        self.assertFalse((repo / "specs").exists())
        self.assertTrue(list((repo / ph_layout.SPECS).glob("*/spec.md")))
        for script in ("setup-plan.sh", "setup-tasks.sh"):
            proc = subprocess.run(["bash", str(scripts / script), "--json"], cwd=repo, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_unexpected_upstream_root_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "review required"):
            ph_layout.convert_runtime_text("unknown", ".specify/scripts/bash/common.sh")


class ArchiveTests(unittest.TestCase):
    def repo(self):
        return Path(tempfile.mkdtemp(prefix="ph-layout-test-"))

    def test_complete_skill_resources_preserved_without_live_skill_names(self):
        repo = self.repo()
        skill = repo / ".agents/skills/ph-custom"
        (skill / "assets").mkdir(parents=True)
        (skill / "SKILL.md").write_text("用户修改的技能", encoding="utf-8")
        (skill / "assets/input.bin").write_bytes(b"\x00\xff")
        roots = {".agents/skills/ph-custom": "installed manifest plus user customization"}
        result = ph_layout.preserve(repo, "to-1.2.1", roots)
        self.assertFalse(result["migration_complete"])
        archive = repo / result["archive"]
        entries = json.loads((archive / "inventory.json").read_text())["entries"]
        for entry in entries:
            if entry["kind"] == "file":
                self.assertEqual((repo / entry["path"]).read_bytes(), (archive / "objects" / (entry["sha256"] + ".blob")).read_bytes())
        self.assertEqual(list(archive.rglob("SKILL.md")), [])
        self.assertEqual(result, ph_layout.preserve(repo, "to-1.2.1", roots))

    def test_active_content_is_transferred_not_only_archived(self):
        repo = self.repo()
        (repo / "old.md").write_text("current project rule")
        ph_layout.preserve(repo, "test", {"old.md": "project constraint"})
        moves = {"old.md": ph_layout.CONSTRAINTS + "/rule.md"}
        result = ph_layout.transfer_files(repo, "test", moves)
        self.assertFalse((repo / "old.md").exists())
        self.assertEqual((repo / moves["old.md"]).read_text(), "current project rule")
        self.assertEqual(result, ph_layout.transfer_files(repo, "test", moves))

    def test_backup_alone_cannot_pass_migration_verification(self):
        repo = self.repo()
        (repo / "old.md").write_text("current rule")
        ph_layout.preserve(repo, "test", {"old.md": "PH constraint"})
        with self.assertRaisesRegex(ValueError, "preserved but not migrated"):
            ph_layout.verify_transplants(repo, "test", [])
        destination = ph_layout.CONSTRAINTS + "/rule.md"
        ph_layout.transfer_files(repo, "test", {"old.md": destination})
        decisions = [{"source": "old.md", "kind": "moved", "evidence": "original bytes preserved", "destinations": [{"path": destination, "sha256": ph_layout.digest(b"current rule")}]}]
        self.assertTrue(ph_layout.verify_transplants(repo, "test", decisions)["ok"])
        (repo / destination).write_text("drift")
        with self.assertRaisesRegex(ValueError, "not verified"):
            ph_layout.verify_transplants(repo, "test", decisions)

    def test_destination_conflict_keeps_all_sources(self):
        repo = self.repo()
        (repo / "a.md").write_text("a")
        (repo / "b.md").write_text("b")
        ph_layout.preserve(repo, "test", {"a.md": "PH", "b.md": "PH"})
        (repo / ph_layout.CONSTRAINTS).mkdir(parents=True)
        (repo / ph_layout.CONSTRAINTS / "b.md").write_text("custom")
        with self.assertRaisesRegex(ValueError, "content conflict"):
            ph_layout.transfer_files(repo, "test", {"a.md": ph_layout.CONSTRAINTS + "/a.md", "b.md": ph_layout.CONSTRAINTS + "/b.md"})
        self.assertTrue((repo / "a.md").exists())
        self.assertTrue((repo / "b.md").exists())

    def test_links_recorded_without_following(self):
        repo = self.repo()
        (repo / "AGENTS.md").symlink_to("/unowned/AGENTS.md")
        ph_layout.preserve(repo, "test", {"AGENTS.md": "PH adapter"})
        data = json.loads((repo / ph_layout.ARCHIVE / "upgrades/test/inventory.json").read_text())
        self.assertEqual(data["entries"][0]["target"], "/unowned/AGENTS.md")

    def test_changed_source_does_not_overwrite_original(self):
        repo = self.repo()
        (repo / "old.md").write_text("original")
        roots = {"old.md": "historical PH document"}
        ph_layout.preserve(repo, "test", roots)
        (repo / "old.md").write_text("edited")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            ph_layout.preserve(repo, "test", roots)

    def test_archive_is_not_recursively_archived(self):
        repo = self.repo()
        (repo / ph_layout.HOME).mkdir(parents=True)
        (repo / ph_layout.HOME / "constitution.md").write_text("rules")
        roots = {ph_layout.HOME: "canonical PH home"}
        ph_layout.preserve(repo, "first", roots)
        ph_layout.preserve(repo, "second", roots)
        data = json.loads((repo / ph_layout.ARCHIVE / "upgrades/second/inventory.json").read_text())
        self.assertFalse(any(entry["path"].startswith(ph_layout.ARCHIVE) for entry in data["entries"]))

    def test_archive_parent_link_blocks_before_write(self):
        repo = self.repo()
        (repo / ".agents").mkdir()
        (repo / ph_layout.HOME).symlink_to(self.repo(), target_is_directory=True)
        (repo / "old.md").write_text("original")
        with self.assertRaisesRegex(ValueError, "not a real directory"):
            ph_layout.preserve(repo, "test", {"old.md": "PH document"})


if __name__ == "__main__":
    unittest.main()
