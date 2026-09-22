"""Exercise a real prepared Git snapshot and post-merge finalization offline."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
CURRENT = json.loads((ROOT / "release.json").read_text())["version"]
sys.path.insert(0, str(ROOT / "scripts"))
import ph_release


def command(*args, cwd=None):
    result = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


def digest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
            and "__pycache__" not in p.parts}


class LocalTransport(ph_release.GitTransport):
    """Offline transport; pins the exact remote URL each caller must use.

    The current tool downloads from DOWNLOAD_SOURCE (the repository was
    renamed to project-harness); a historical downloader still addresses the
    old FIXED_SOURCE URL. Each instance accepts exactly one URL on purpose:
    tolerating both would mask a tool calling the wrong source.
    """

    def __init__(self, source, expected=None):
        self.source = source
        self.expected = ph_release.DOWNLOAD_SOURCE if expected is None else expected

    def ls_remote_tags(self, source):
        assert source == self.expected, f"unexpected remote {source!r}, expected {self.expected!r}"
        return command("git", "ls-remote", "--tags", str(self.source))

    def fetch_commit(self, source, commit, dest):
        assert source == self.expected, f"unexpected remote {source!r}, expected {self.expected!r}"
        command("git", "init", "--bare", "--template=", str(dest))
        command("git", "-C", str(dest), "fetch", "--no-tags", str(self.source), commit)


class ReleaseIntegrationTests(unittest.TestCase):
    def test_current_downloader_prepares_published_legacy_tags(self):
        workspace = Path(tempfile.mkdtemp(prefix="ph-legacy-download-"))
        try:
            for version in ("1.1.1", "1.1.7"):
                with self.subTest(version=version):
                    prepared = ph_release.prepare_release(
                        version,
                        transport=LocalTransport(ROOT),
                        parent=workspace / version,
                        offer_support=False,
                    )
                    expected = command("git", "rev-parse", f"v{version}^{{}}", cwd=ROOT).strip()
                    self.assertEqual(prepared.commit, expected)
                    release = json.loads((prepared.root / "release.json").read_text())
                    manifest = json.loads((prepared.root / "assets/scaffold/.agents/ph.json").read_text())
                    self.assertEqual(release["version"], version)
                    self.assertEqual(manifest["template_version"], version)
                    self.assertEqual(release["schema_version"], manifest["schema_version"])
                    for rel in ("release.json", "assets/scaffold/.agents/ph.json",
                                "assets/scaffold/.agents/ph.schema.json"):
                        original = subprocess.run(
                            ["git", "show", f"v{version}:{rel}"], cwd=ROOT,
                            capture_output=True, check=True, timeout=90,
                        ).stdout
                        self.assertEqual((prepared.root / rel).read_bytes(), original)
        finally:
            trash = Path.home() / "trash"
            trash.mkdir(parents=True, exist_ok=True)
            workspace.rename(trash / f"ph-legacy-download-{os.getpid()}-{time.time_ns()}")

    def test_prepared_snapshot_init_and_post_merge_finalize(self):
        workspace = Path(tempfile.mkdtemp(prefix="ph-release-integration-"))
        try:
            source = workspace / "source"
            shutil.copytree(ROOT, source, ignore=lambda directory, names: set(shutil.ignore_patterns(
                ".git", ".zcode", "__pycache__", "*.pyc", ".DS_Store"
            )(directory, names)) | ({"AGENTS.md", "CLAUDE.md"} if Path(directory) == ROOT else set()))
            command("git", "init", "-q", str(source))
            command("git", "-C", str(source), "add", ".")
            command("git", "-C", str(source), "-c", "user.name=PH fixture",
                    "-c", "user.email=fixture@example.com", "commit", "-qm", "fixture release")
            command("git", "-C", str(source), "tag", f"v{CURRENT}")
            for version in ("1.1.1", "1.1.7"):
                with self.subTest(old_downloader=version):
                    name = f"legacy_ph_release_{version.replace('.', '_')}"
                    path = workspace / f"{name}.py"
                    path.write_text(command("git", "show", f"v{version}:scripts/ph_release.py", cwd=ROOT))
                    spec = importlib.util.spec_from_file_location(name, path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[name] = module
                    try:
                        spec.loader.exec_module(module)
                        support = Mock(side_effect=AssertionError("unexpected GitHub support action"))
                        module.offer_official_support = support
                        with self.assertRaisesRegex(module.PHReleaseError, "missing schema_version"):
                            module.prepare_release(
                                CURRENT,
                                # Historical downloaders still address the
                                # old FIXED_SOURCE URL; only the renamed
                                # current tool uses DOWNLOAD_SOURCE.
                                transport=LocalTransport(source, expected=module.FIXED_SOURCE),
                                parent=workspace / f"old-download-{version}",
                            )
                        support.assert_not_called()
                    finally:
                        sys.modules.pop(name, None)
            prepared = ph_release.prepare_release(
                "latest",
                transport=LocalTransport(source),
                parent=workspace / "prepared",
                offer_support=False,
            )
            root = prepared.root
            self.assertEqual(set(prepared.as_dict()), {"version", "tag", "commit", "source", "root"})
            # The rename keeps the historical URL as the identity of the
            # result and the receipt, while the download itself used the
            # renamed project-harness repository.
            self.assertEqual(prepared.source, ph_release.FIXED_SOURCE)
            receipt = json.loads((root / ".ph-source.json").read_text())
            self.assertEqual(receipt["source"], ph_release.FIXED_SOURCE)
            self.assertNotIn("schema_version", json.loads((root / "release.json").read_text()))
            for mode in ("portable", "symlink"):
                with self.subTest(mode=mode):
                    repo = workspace / mode
                    command("git", "init", "-q", str(repo))
                    init = root / "scripts/ph_init.py"
                    merge = root / "scripts/ph_merge_update.py"
                    before = digest(repo)
                    command(sys.executable, str(init), "init", "--mode", mode, "--repo", str(repo))
                    self.assertEqual(before, digest(repo))
                    command(sys.executable, str(init), "init", "--apply", "--mode", mode, "--repo", str(repo))
                    installed = repo / ".agents/skills/ph-init/scripts/ph_init.py"
                    command(sys.executable, str(installed), "check", "--repo", str(repo))
                    # Model the post-semantic-merge stage; this is not a test of
                    # an Agent reconstructing old project rules from scratch.
                    manifest = repo / ".agents/ph.json"
                    data = json.loads(manifest.read_text())
                    self.assertNotIn("schema_version", data)
                    self.assertNotIn("schema_version", json.loads(
                        (repo / ".agents/skills/ph-init/release.json").read_text()))
                    self.assertEqual(json.loads((repo / ".agents/ph.schema.json").read_text())["$id"],
                                     "urn:ph:schema:project-harness")
                    data["schema_version"] = data["template_version"] = "1.0.0"
                    data["skills"]["required_names"] = data["skills"]["required_names"][:6]
                    manifest.write_text(json.dumps(data) + "\n")
                    agents = repo / ".agents/AGENTS.md"
                    agents.write_text(agents.read_text() + "\nProject-specific command: make verify\n")
                    legacy = repo / "docs/意图/进行中/新特性/INT-keep.md"
                    legacy.parent.mkdir(parents=True)
                    legacy.write_text("# Original intent\nDo not reclassify.\n")
                    # the intent tree is retired; a legacy project may still
                    # carry such files and they must survive untouched
                    pending = repo / "docs/意图/待办/新特性/README.md"
                    pending.parent.mkdir(parents=True, exist_ok=True)
                    pending.write_text("# 待办\nCustom project index entry\n")
                    wiki = repo / "docs/项目Wiki/项目概述.md"
                    wiki.parent.mkdir(parents=True, exist_ok=True)
                    wiki.write_text("# 项目概述\nReviewed subagent project facts\n")
                    rules = repo / "docs/约束规范/后端规范/后端规范.md"
                    rules.parent.mkdir(parents=True, exist_ok=True)
                    rules.write_text("# 后端规范\nProject-specific approved exception\n")
                    retained_paths = (agents, legacy, pending, wiki, rules)
                    retained = tuple(path.read_bytes() for path in retained_paths)
                    inspected = json.loads(command(sys.executable, str(merge), "inspect", "--repo", str(repo)))
                    self.assertTrue(inspected["source"]["verified"], inspected["source"])
                    state = inspected["suggested_state"]
                    self.assertEqual(state["from_version"], "1.0.0")
                    self.assertEqual(state["source"]["commit"], prepared.commit)
                    for item in state["items"]:
                        item.update(status="applied", evidence="Post-merge fixture contains target assets; protected project bytes checked")
                    record = repo / ".agents/updates" / CURRENT
                    record.mkdir(parents=True)
                    (record / "state.json").write_text(json.dumps(state) + "\n")
                    (record / "report.md").write_text("# Local fixture\nPost-merge structural test, not public GitHub verification.\n")
                    # the mandatory intent-to-spec item's artifacts are part of
                    # the applied state verify checks; run the real item
                    command(sys.executable, str(merge), "migrate-intents", "--repo", str(repo), "--apply")
                    from content_fixture import complete_documentation_project
                    complete_documentation_project(repo, root)
                    command(sys.executable, str(merge), "verify", "--repo", str(repo))
                    before = digest(repo)
                    command(sys.executable, str(merge), "finalize", "--repo", str(repo))
                    self.assertEqual(before, digest(repo))
                    command(sys.executable, str(merge), "finalize", "--apply", "--repo", str(repo))
                    self.assertEqual(retained, tuple(path.read_bytes() for path in retained_paths))
                    finalized = json.loads(manifest.read_text())
                    self.assertNotIn("schema_version", finalized)
                    self.assertEqual(finalized["template_version"], CURRENT)
                    command(sys.executable, str(installed), "check", "--repo", str(repo))
                    result = json.loads(command(sys.executable, str(merge), "inspect", "--repo", str(repo)))
                    self.assertTrue(result["up_to_date"])
                    self.assertIsNone(result["suggested_state"])
                    state = json.loads((record / "state.json").read_text())
                    state["status"] = "in_progress"
                    (record / "state.json").write_text(json.dumps(state) + "\n")
                    command(sys.executable, str(merge), "finalize", "--apply", "--repo", str(repo))
                    self.assertEqual(json.loads((record / "state.json").read_text())["status"], "complete")
        finally:
            trash = Path.home() / "trash"
            trash.mkdir(parents=True, exist_ok=True)
            workspace.rename(trash / f"ph-release-integration-{os.getpid()}-{time.time_ns()}")


if __name__ == "__main__":
    unittest.main()
