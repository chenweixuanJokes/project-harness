#!/usr/bin/env python3
"""Unit tests for the isolated PH release downloader."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ph_release  # noqa: E402


TRASH_ROOT = Path.home() / "trash"
FIXED_SOURCE = ph_release.FIXED_SOURCE
DOWNLOAD_SOURCE = ph_release.DOWNLOAD_SOURCE
SCHEMA_ID = ph_release.SCHEMA_ID
CURRENT_VERSION = "1.1.13"
LEGACY_VERSION = "1.1.7"
DEFAULT_SKILLS = [
    "ph-init",
    "ph-worktree-enter",
    "ph-worktree-exit",
    "ph-memory-capture",
    "ph-memory-archive",
    "ph-memory-ask",
    "ph-intent-new",
    "ph-intent-impl",
    "ph-intent-verify",
    "ph-intent-drop",
    "ph-merge-update",
    "ph-docs-sync",
    "ph-sure",
]
REAL_MIGRATIONS = {
    "format_version": 1,
    "migrations": [
        {
            "from_version": "1.0.0",
            "to_version": "1.1.0",
            "path": "migrations/1.0.0-to-1.1.0.md",
            "items": ["intent-domain"],
        },
        {
            "from_version": "1.1.0",
            "to_version": "1.1.1",
            "path": "migrations/1.1.0-to-1.1.1.md",
            "items": [
                "intent-skill-names",
                "intent-lifecycle",
                "online-source",
                "merge-update",
                "schema-contract",
                "project-content",
            ],
        },
    ],
}


def run(argv, cwd=None, env=None):
    return subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, timeout=60)


class DictTransport(ph_release.GitTransport):
    def __init__(self, tags=None, trees=None, blobs=None, types=None, ls_error=None, fetch_error=None):
        self.tags = tags or {}
        self.trees = trees or {}
        self.blobs = blobs or {}
        self.types = types or {}
        self.ls_error = ls_error
        self.fetch_error = fetch_error
        self.ls_calls = []
        self.fetch_calls = []

    def ls_remote_tags(self, source):
        self.ls_calls.append(source)
        if self.ls_error is not None:
            raise self.ls_error
        lines = []
        for tag, commit in self.tags.items():
            if isinstance(commit, tuple):
                tag_obj, peeled = commit
                lines.append(f"{tag_obj}\trefs/tags/{tag}")
                lines.append(f"{peeled}\trefs/tags/{tag}^{{}}")
            else:
                lines.append(f"{commit}\trefs/tags/{tag}")
        return "\n".join(lines) + "\n"

    def fetch_commit(self, source, commit, dest):
        self.fetch_calls.append((source, commit, dest))
        if self.fetch_error is not None:
            raise self.fetch_error
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "HEAD").write_text(commit + "\n", encoding="utf-8")

    def object_type(self, git_dir, object_id):
        return self.types.get(object_id, "commit")

    def ls_tree(self, git_dir, commit):
        return self.trees[commit]

    def cat_file(self, git_dir, object_id):
        return self.blobs[object_id]


class PhReleaseTests(unittest.TestCase):
    def setUp(self):
        self._temps = []

    def tearDown(self):
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-release-{stamp}-{os.getpid()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=False)
        for i, path in enumerate(self._temps):
            if Path(path).exists():
                Path(path).rename(dest / f"{i:02d}-{Path(path).name}")

    def temp_dir(self, prefix):
        root = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(root)
        return root

    def git_repo(self, prefix):
        root = self.temp_dir(prefix)
        for argv in (
            ["git", "init"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "ph-release-test"],
        ):
            proc = run(argv, cwd=root)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return root

    def blob(self, data: bytes) -> tuple[str, bytes]:
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(), data

    def commit_id(self, seed: str) -> str:
        return hashlib.sha1(seed.encode()).hexdigest()

    def release_files(self, version=CURRENT_VERSION, *, skills=None, extra=None, mutate=None):
        """Current release shape (1.1.8+): no schema_version anywhere."""

        skills = list(skills or DEFAULT_SKILLS)
        release = {
            "format_version": 1,
            "version": version,
            "repository": FIXED_SOURCE,
            "required_skills": skills,
        }
        manifest = {
            "template_version": version,
            "skills": {"required_names": skills},
        }
        schema = {"$id": SCHEMA_ID}
        files = {
            "release.json": json.dumps(release, indent=2) + "\n",
            "SKILL.md": "# ph-init\n",
            "scripts/ph_init.py": "print('init')\n",
            "scripts/ph_release.py": "print('release')\n",
            "scripts/ph_merge_update.py": "print('merge')\n",
            "assets/scaffold/.agents/ph.json": json.dumps(manifest, indent=2) + "\n",
            "assets/scaffold/.agents/ph.schema.json": json.dumps(schema, indent=2) + "\n",
            "assets/scaffold/.agents/AGENTS.md": "# agents\n",
            "migrations/index.json": json.dumps(REAL_MIGRATIONS, indent=2) + "\n",
            "migrations/1.0.0-to-1.1.0.md": "# 1.0.0 to 1.1.0\n",
            "migrations/1.1.0-to-1.1.1.md": "# 1.1.0 to 1.1.1\n",
        }
        for name in skills:
            if name == "ph-init":
                continue
            files[f"assets/scaffold/.agents/skills/{name}/SKILL.md"] = f"# {name}\n"
        if extra:
            files.update(extra)
        if mutate:
            mutate(files)
        return files

    def legacy_release_files(self, version=LEGACY_VERSION, *, schema_version="1.1.1", skills=None, extra=None, mutate=None):
        """Pre-1.1.8 release shape: schema_version must agree in three places."""

        files = self.release_files(version, skills=skills, extra=extra)
        release = json.loads(files["release.json"])
        release["schema_version"] = schema_version
        files["release.json"] = json.dumps(release, indent=2) + "\n"
        manifest = json.loads(files["assets/scaffold/.agents/ph.json"])
        manifest["schema_version"] = schema_version
        files["assets/scaffold/.agents/ph.json"] = json.dumps(manifest, indent=2) + "\n"
        schema = json.loads(files["assets/scaffold/.agents/ph.schema.json"])
        schema["$id"] = f"urn:ph:schema:project-harness:{schema_version}"
        files["assets/scaffold/.agents/ph.schema.json"] = json.dumps(schema, indent=2) + "\n"
        if mutate:
            mutate(files)
        return files

    def tree_from_files(self, files):
        blobs = {}
        records = []
        for path, text in files.items():
            data = text.encode() if isinstance(text, str) else text
            object_id, raw = self.blob(data)
            blobs[object_id] = raw
            records.append(f"100644 blob {object_id}\t{path}")
        return "\0".join(records) + "\0", blobs

    def transport_for(self, files, version=CURRENT_VERSION, extra_tags=None):
        commit = self.commit_id(f"v{version}")
        tree, blobs = self.tree_from_files(files)
        tags = {f"v{version}": commit}
        if extra_tags:
            tags.update(extra_tags)
        return DictTransport(tags=tags, trees={commit: tree}, blobs=blobs), commit

    def prepare(self, transport, version="latest", repo=None, support=None, offer_support=False):
        parent = self.temp_dir("ph-release-work-")
        return ph_release.prepare_release(
            version,
            repo=repo,
            transport=transport,
            parent=parent,
            support=support,
            offer_support=offer_support,
        )

    def test_parse_ls_remote_prefers_peeled_annotated_commit(self):
        tag_obj = self.commit_id("tag-object")
        commit = self.commit_id("peeled-commit")
        lightweight = self.commit_id("light")
        payload = (
            f"{tag_obj}\trefs/tags/v1.1.1\n"
            f"{commit}\trefs/tags/v1.1.1^{{}}\n"
            f"{lightweight}\trefs/tags/v1.0.0\n"
            f"{self.commit_id('rc')}\trefs/tags/v1.2.0-rc.1\n"
            f"{self.commit_id('other')}\trefs/tags/not-a-version\n"
        )
        tags = ph_release.parse_ls_remote_tags(payload)
        self.assertEqual(tags["v1.1.1"], commit)
        self.assertEqual(tags["v1.0.0"], lightweight)
        self.assertNotIn("v1.2.0-rc.1", tags)
        self.assertNotIn("not-a-version", tags)

    def test_latest_selects_numeric_max_stable_tag(self):
        tags = {
            "v1.9.9": self.commit_id("199"),
            "v1.10.0": self.commit_id("1100"),
            "v2.0.0": self.commit_id("200"),
        }
        tag, commit = ph_release.select_tag("latest", tags)
        self.assertEqual((tag, commit), ("v2.0.0", tags["v2.0.0"]))

    def test_explicit_version_and_unsupported_metadata(self):
        tags = {"v1.1.1": self.commit_id("111")}
        self.assertEqual(ph_release.select_tag("1.1.1", tags)[0], "v1.1.1")
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.select_tag("1.1.1-rc.1", tags)
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.select_tag("v1.1.1", tags)
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.select_tag("1.1.1", {})
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.select_tag("latest", {})

    def test_prepare_writes_receipt_and_json_fields(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        prepared = self.prepare(transport, "latest")
        self.assertEqual(prepared.version, CURRENT_VERSION)
        self.assertEqual(prepared.tag, f"v{CURRENT_VERSION}")
        self.assertEqual(prepared.commit, commit)
        self.assertEqual(prepared.source, FIXED_SOURCE)
        self.assertTrue(prepared.root.is_dir())
        meta = json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))
        self.assertNotIn("schema_version", meta)
        receipt = json.loads((prepared.root / ".ph-source.json").read_text(encoding="utf-8"))
        self.assertEqual(
            receipt,
            {
                "version": CURRENT_VERSION,
                "tag": f"v{CURRENT_VERSION}",
                "commit": commit,
                "source": FIXED_SOURCE,
            },
        )
        self.assertNotIn("root", receipt)
        self.assertTrue((prepared.root / "scripts/ph_init.py").is_file())
        self.assertTrue((prepared.root / "SKILL.md").is_file())
        self.assertTrue((prepared.root / "migrations/1.1.0-to-1.1.1.md").is_file())
        self.assertEqual(transport.ls_calls, [DOWNLOAD_SOURCE])
        self.assertEqual(transport.fetch_calls[0][:2], (DOWNLOAD_SOURCE, commit))

    def test_download_uses_new_source_but_keeps_fixed_identity(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        prepared = self.prepare(transport, "latest")
        self.assertNotEqual(DOWNLOAD_SOURCE, FIXED_SOURCE)
        self.assertEqual(transport.ls_calls, [DOWNLOAD_SOURCE])
        self.assertEqual(transport.fetch_calls[0][:2], (DOWNLOAD_SOURCE, commit))
        self.assertEqual(prepared.source, FIXED_SOURCE)
        receipt = json.loads((prepared.root / ".ph-source.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["source"], FIXED_SOURCE)
        meta = json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["repository"], FIXED_SOURCE)

    def test_new_downloader_accepts_pre_rename_tag(self):
        files = self.release_files("1.1.8")
        transport, commit = self.transport_for(files, version="1.1.8")
        prepared = self.prepare(transport, "1.1.8")
        self.assertEqual(prepared.tag, "v1.1.8")
        self.assertEqual(prepared.source, FIXED_SOURCE)
        self.assertEqual(transport.ls_calls, [DOWNLOAD_SOURCE])
        self.assertEqual(transport.fetch_calls[0][:2], (DOWNLOAD_SOURCE, commit))
        meta = json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["repository"], FIXED_SOURCE)

    def test_explicit_version_uses_matching_tag(self):
        files_old = self.legacy_release_files(LEGACY_VERSION)
        files_new = self.release_files(CURRENT_VERSION)
        old_commit = self.commit_id(f"v{LEGACY_VERSION}")
        new_commit = self.commit_id(f"v{CURRENT_VERSION}")
        old_tree, old_blobs = self.tree_from_files(files_old)
        new_tree, new_blobs = self.tree_from_files(files_new)
        blobs = {**old_blobs, **new_blobs}
        transport = DictTransport(
            tags={f"v{LEGACY_VERSION}": old_commit, f"v{CURRENT_VERSION}": new_commit},
            trees={old_commit: old_tree, new_commit: new_tree},
            blobs=blobs,
        )
        prepared = self.prepare(transport, LEGACY_VERSION)
        self.assertEqual(prepared.tag, f"v{LEGACY_VERSION}")
        self.assertEqual(prepared.commit, old_commit)
        self.assertEqual(
            json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))["version"],
            LEGACY_VERSION,
        )
        prepared = self.prepare(transport, CURRENT_VERSION)
        self.assertEqual(prepared.tag, f"v{CURRENT_VERSION}")
        self.assertEqual(prepared.commit, new_commit)

    def test_explicit_legacy_version_downloads_old_format_as_published(self):
        files = self.legacy_release_files(LEGACY_VERSION, schema_version="1.1.1")
        transport, commit = self.transport_for(files, version=LEGACY_VERSION)
        prepared = self.prepare(transport, LEGACY_VERSION)
        self.assertEqual(prepared.version, LEGACY_VERSION)
        meta = json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))
        manifest = json.loads((prepared.root / "assets/scaffold/.agents/ph.json").read_text(encoding="utf-8"))
        schema = json.loads((prepared.root / "assets/scaffold/.agents/ph.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["schema_version"], "1.1.1")
        self.assertEqual(manifest["schema_version"], "1.1.1")
        self.assertEqual(schema["$id"], "urn:ph:schema:project-harness:1.1.1")

    def test_legacy_format_must_be_self_consistent(self):
        def mismatch_manifest(files):
            data = json.loads(files["assets/scaffold/.agents/ph.json"])
            data["schema_version"] = "9.9.9"
            files["assets/scaffold/.agents/ph.json"] = json.dumps(data)

        transport, _ = self.transport_for(
            self.legacy_release_files(LEGACY_VERSION, mutate=mismatch_manifest),
            version=LEGACY_VERSION,
        )
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, LEGACY_VERSION)

        def mismatch_schema_id(files):
            data = json.loads(files["assets/scaffold/.agents/ph.schema.json"])
            data["$id"] = "urn:ph:schema:project-harness:1.1.2"
            files["assets/scaffold/.agents/ph.schema.json"] = json.dumps(data)

        transport, _ = self.transport_for(
            self.legacy_release_files(LEGACY_VERSION, mutate=mismatch_schema_id),
            version=LEGACY_VERSION,
        )
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, LEGACY_VERSION)

        def drop_schema_version(files):
            data = json.loads(files["release.json"])
            del data["schema_version"]
            files["release.json"] = json.dumps(data)

        transport, _ = self.transport_for(
            self.legacy_release_files(LEGACY_VERSION, mutate=drop_schema_version),
            version=LEGACY_VERSION,
        )
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, LEGACY_VERSION)

    def test_new_format_rejects_schema_version_residue(self):
        def meta_residue(files):
            data = json.loads(files["release.json"])
            data["schema_version"] = "1.1.1"
            files["release.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=meta_residue))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, "latest")

        def manifest_residue(files):
            data = json.loads(files["assets/scaffold/.agents/ph.json"])
            data["schema_version"] = "1.1.1"
            files["assets/scaffold/.agents/ph.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=manifest_residue))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, "latest")

        def versioned_schema_id(files):
            data = json.loads(files["assets/scaffold/.agents/ph.schema.json"])
            data["$id"] = "urn:ph:schema:project-harness:1.1.1"
            files["assets/scaffold/.agents/ph.schema.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=versioned_schema_id))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, "latest")

        def schema_still_declares_field(files):
            data = json.loads(files["assets/scaffold/.agents/ph.schema.json"])
            data["required"] = ["$schema", "schema_version"]
            data["properties"] = {"schema_version": {"const": "1.1.1"}}
            files["assets/scaffold/.agents/ph.schema.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=schema_still_declares_field))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, "latest")

    def test_new_format_rejects_wrong_schema_id(self):
        def wrong_id(files):
            data = json.loads(files["assets/scaffold/.agents/ph.schema.json"])
            data["$id"] = "urn:ph:schema:other-harness"
            files["assets/scaffold/.agents/ph.schema.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=wrong_id))
        with self.assertRaises(ph_release.PHReleaseError) as ctx:
            self.prepare(transport, "latest")
        self.assertIn("$id", str(ctx.exception))

    def test_rejects_symlink_and_submodule_and_escaped_path(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        blob_id = next(iter(transport.blobs))
        bad_trees = [
            f"120000 blob {blob_id}\tscripts/ph_init.py\0",
            f"160000 commit {self.commit_id('sub')}\tvendor/lib\0",
            f"100644 blob {blob_id}\t../escape.txt\0",
            f"100644 blob {blob_id}\tfoo/../../escape.txt\0",
        ]
        for tree in bad_trees:
            transport.trees[commit] = tree
            with self.assertRaises(ph_release.PHReleaseError):
                self.prepare(transport, CURRENT_VERSION)

    def test_rejects_mismatched_meta_and_missing_required_files(self):
        def mutate_repo(files):
            data = json.loads(files["release.json"])
            data["repository"] = "https://example.com/other.git"
            files["release.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=mutate_repo))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        def mutate_format(files):
            data = json.loads(files["release.json"])
            data["format_version"] = "1"
            files["release.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=mutate_format))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        def drop_script(files):
            del files["scripts/ph_merge_update.py"]

        transport, _ = self.transport_for(self.release_files(mutate=drop_script))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        def bad_migration(files):
            data = json.loads(files["migrations/index.json"])
            data["migrations"][0]["path"] = "../outside.md"
            files["migrations/index.json"] = json.dumps(data)

        def duplicate_from(files):
            data = json.loads(files["migrations/index.json"])
            data["migrations"].append(data["migrations"][0])
            files["migrations/index.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=duplicate_from))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        def empty_items(files):
            data = json.loads(files["migrations/index.json"])
            data["migrations"][0]["items"] = []
            files["migrations/index.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=empty_items))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        def old_from_to_keys(files):
            data = json.loads(files["migrations/index.json"])
            hop = data["migrations"][0]
            hop["from"] = hop.pop("from_version")
            hop["to"] = hop.pop("to_version")
            files["migrations/index.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=old_from_to_keys))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        transport, _ = self.transport_for(self.release_files(mutate=bad_migration))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        def mismatch_manifest(files):
            data = json.loads(files["assets/scaffold/.agents/ph.json"])
            data["template_version"] = "9.9.9"
            files["assets/scaffold/.agents/ph.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=mismatch_manifest))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

        def extra_meta(files):
            data = json.loads(files["release.json"])
            data["channel"] = "nightly"
            files["release.json"] = json.dumps(data)

        transport, _ = self.transport_for(self.release_files(mutate=extra_meta))
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

    def test_network_failure_does_not_fallback(self):
        transport = DictTransport(
            ls_error=ph_release.PHReleaseError(
                f"network failure talking to {DOWNLOAD_SOURCE}: could not resolve host"
            )
        )
        with self.assertRaises(ph_release.PHReleaseError) as ctx:
            self.prepare(transport, "latest")
        self.assertIn("network failure", str(ctx.exception))
        self.assertEqual(transport.fetch_calls, [])

    def test_fetch_timeout_is_captured(self):
        files = self.release_files()
        transport, _ = self.transport_for(files)
        transport.fetch_error = ph_release.PHReleaseError(
            "git fetch --no-tags --depth=1 --no-recurse-submodules -- "
            f"{DOWNLOAD_SOURCE} abc timed out after 60s"
        )
        with self.assertRaises(ph_release.PHReleaseError) as ctx:
            self.prepare(transport, CURRENT_VERSION)
        self.assertIn("timed out", str(ctx.exception))

    def test_prepare_does_not_mutate_target_repo(self):
        target = self.git_repo("ph-release-target-")
        (target / "keep.txt").write_text("keep\n", encoding="utf-8")
        before = {}
        for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
            dirnames[:] = [n for n in dirnames if n != ".git"]
            for name in filenames:
                path = Path(dirpath) / name
                before[str(path.relative_to(target))] = path.read_bytes()
        transport, _ = self.transport_for(self.release_files())
        prepared = self.prepare(transport, "latest", repo=str(target))
        after = {}
        for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
            dirnames[:] = [n for n in dirnames if n != ".git"]
            for name in filenames:
                path = Path(dirpath) / name
                after[str(path.relative_to(target))] = path.read_bytes()
        self.assertEqual(before, after)
        self.assertFalse(str(prepared.root.resolve()).startswith(str(target.resolve()) + os.sep))

    def test_allocate_temp_root_stays_outside_target(self):
        target = self.git_repo("ph-release-outside-")
        root = ph_release.allocate_temp_root(target)
        self._temps.append(root)
        self.assertFalse(str(root.resolve()).startswith(str(target.resolve()) + os.sep))

    def test_parent_inside_target_is_rejected(self):
        target = self.git_repo("ph-release-inside-")
        transport, _ = self.transport_for(self.release_files())
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.prepare_release(
                "latest",
                repo=str(target),
                transport=transport,
                parent=target / "nested-download",
                offer_support=False,
            )

    def test_safe_rel_path_allows_unicode_and_rejects_escape(self):
        self.assertTrue(ph_release.is_safe_rel_path("docs/意图/README.md"))
        self.assertFalse(ph_release.is_safe_rel_path("../outside"))
        self.assertFalse(ph_release.is_safe_rel_path("foo/../../x"))
        self.assertFalse(ph_release.is_safe_rel_path("/abs"))
        self.assertFalse(ph_release.is_safe_rel_path("C:windows"))
        self.assertFalse(ph_release.is_safe_rel_path("https://evil.example/x"))

    def test_cli_prepare_json_with_monkeypatched_transport(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        parent = self.temp_dir("ph-release-cli-")
        original_ctor = ph_release.GitTransport
        original_alloc = ph_release.allocate_temp_root
        original_support = ph_release.offer_official_support

        class Patched(DictTransport):
            def __init__(self):
                super().__init__(
                    tags=transport.tags,
                    trees=transport.trees,
                    blobs=transport.blobs,
                )

        ph_release.GitTransport = Patched
        ph_release.allocate_temp_root = lambda target: parent
        ph_release.offer_official_support = lambda *a, **k: None
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                code = ph_release.main(["prepare", "--version", "latest"])
        finally:
            ph_release.GitTransport = original_ctor
            ph_release.allocate_temp_root = original_alloc
            ph_release.offer_official_support = original_support
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["version"], CURRENT_VERSION)
        self.assertEqual(data["tag"], f"v{CURRENT_VERSION}")
        self.assertEqual(data["commit"], commit)
        self.assertEqual(data["source"], FIXED_SOURCE)
        self.assertTrue(Path(data["root"]).is_dir())
        receipt = json.loads((Path(data["root"]) / ".ph-source.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["commit"], commit)
        self.assertNotIn("root", receipt)

    def test_cli_rejects_unsupported_version_without_network(self):
        proc = run([sys.executable, str(SCRIPTS / "ph_release.py"), "prepare", "--version", "1.1.1-rc.1"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unsupported version", proc.stderr)

    def test_no_public_source_argument(self):
        parser = ph_release._build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["prepare", "--version", "latest", "--source", "https://evil.example/x.git"])
        self.assertFalse(hasattr(ph_release.prepare_release, "source"))

    def test_real_git_fixture_materializes_commit(self):
        source = self.git_repo("ph-release-src-")
        files = self.release_files()
        for rel, text in files.items():
            path = source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for argv in (
            ["git", "add", "."],
            ["git", "commit", "-m", f"v{CURRENT_VERSION}"],
            ["git", "tag", "-a", f"v{CURRENT_VERSION}", "-m", f"v{CURRENT_VERSION}"],
        ):
            proc = run(argv, cwd=source)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        commit = run(["git", "rev-parse", f"v{CURRENT_VERSION}^{{}}"], cwd=source).stdout.strip()
        self.assertEqual(len(commit), 40)

        class LocalTransport(ph_release.GitTransport):
            def ls_remote_tags(self, source_url):
                if source_url != DOWNLOAD_SOURCE:
                    raise ph_release.PHReleaseError(f"unexpected source {source_url}")
                return run(["git", "ls-remote", "--tags", str(source)], cwd=source).stdout

            def fetch_commit(self, source_url, want, dest):
                if source_url != DOWNLOAD_SOURCE:
                    raise ph_release.PHReleaseError(f"unexpected source {source_url}")
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "FETCH_HEAD").write_text(want + "\n", encoding="utf-8")

            def object_type(self, git_dir, want):
                proc = run(["git", "cat-file", "-t", want], cwd=source)
                if proc.returncode != 0:
                    raise ph_release.PHReleaseError(proc.stderr or proc.stdout)
                return proc.stdout.strip()

            def ls_tree(self, git_dir, want):
                proc = run(["git", "ls-tree", "-r", "-z", "--full-tree", want], cwd=source)
                if proc.returncode != 0:
                    raise ph_release.PHReleaseError(proc.stderr or proc.stdout)
                return proc.stdout

            def cat_file(self, git_dir, object_id):
                proc = subprocess.run(
                    ["git", "cat-file", "blob", object_id],
                    cwd=source,
                    capture_output=True,
                    timeout=60,
                )
                if proc.returncode != 0:
                    raise ph_release.PHReleaseError(proc.stderr.decode("utf-8", errors="replace"))
                return proc.stdout

        prepared = self.prepare(LocalTransport(), "latest")
        self.assertEqual(prepared.commit, commit)
        self.assertEqual(
            json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))["version"],
            CURRENT_VERSION,
        )
        self.assertTrue((prepared.root / "scripts/ph_release.py").is_file())
        self.assertFalse((prepared.root / ".git").exists())

    def test_legacy_schema_version_is_independent_of_release_version(self):
        files = self.legacy_release_files(LEGACY_VERSION, schema_version="1.1.1")
        transport, _ = self.transport_for(files, version=LEGACY_VERSION)
        prepared = self.prepare(transport, LEGACY_VERSION)
        meta = json.loads((prepared.root / "release.json").read_text(encoding="utf-8"))
        manifest = json.loads((prepared.root / "assets/scaffold/.agents/ph.json").read_text(encoding="utf-8"))
        schema = json.loads((prepared.root / "assets/scaffold/.agents/ph.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["version"], LEGACY_VERSION)
        self.assertEqual(meta["schema_version"], "1.1.1")
        self.assertEqual(manifest["schema_version"], "1.1.1")
        self.assertEqual(schema["$id"], "urn:ph:schema:project-harness:1.1.1")

    def test_future_release_can_add_skill_and_prepare(self):
        skills = [*DEFAULT_SKILLS, "ph-future-skill"]
        files = self.release_files("1.1.13", skills=skills)
        transport, _ = self.transport_for(files, version="1.1.13")
        prepared = self.prepare(transport, "1.1.13")
        self.assertEqual(prepared.version, "1.1.13")
        self.assertTrue(
            (prepared.root / "assets/scaffold/.agents/skills/ph-future-skill/SKILL.md").is_file()
        )
        # the current release's own newer skills are part of the default set
        current = self.release_files()
        transport, _ = self.transport_for(current)
        prepared = self.prepare(transport)
        self.assertTrue(
            (prepared.root / "assets/scaffold/.agents/skills/ph-docs-sync/SKILL.md").is_file()
        )
        self.assertTrue(
            (prepared.root / "assets/scaffold/.agents/skills/ph-intent-verify/SKILL.md").is_file()
        )

    def test_real_repo_tree_validates_and_uses_real_migration_schema(self):
        version = json.loads((REPO_ROOT / "release.json").read_text(encoding="utf-8"))["version"]
        ph_release.validate_prepared_tree(REPO_ROOT, version)
        index = json.loads((REPO_ROOT / "migrations/index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["format_version"], 1)
        self.assertEqual(index["migrations"][0]["from_version"], "1.0.0")
        self.assertIn("items", index["migrations"][0])
        self.assertNotIn("from", index["migrations"][0])

    def test_semver_fullmatch_rejects_newline_and_leading_zero(self):
        self.assertIsNone(ph_release.SEMVER.fullmatch("1.1.1\n"))
        self.assertIsNone(ph_release.SEMVER.fullmatch("01.1.1"))
        self.assertIsNone(ph_release.SEMVER.fullmatch("1.01.1"))
        self.assertIsNotNone(ph_release.SEMVER.fullmatch("1.1.1"))
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.select_tag("01.1.1", {"v01.1.1": self.commit_id("bad")})
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.select_tag("1.1.1\n", {"v1.1.1": self.commit_id("nl")})

    def test_pinned_object_must_be_commit(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        transport.types[commit] = "tree"
        with self.assertRaises(ph_release.PHReleaseError) as ctx:
            self.prepare(transport, CURRENT_VERSION)
        self.assertIn("not commit", str(ctx.exception))
        transport.types[commit] = "blob"
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, CURRENT_VERSION)

    def test_run_git_strips_config_overrides_and_redacts_credential(self):
        captured = {}

        def fake_run(cmd, cwd=None, env=None, **kwargs):
            captured["cwd"] = Path(cwd) if cwd is not None else None
            captured["env"] = env
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

        original = subprocess.run
        extra = {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": "Authorization: Bearer secret",
            "GIT_DIR": "/tmp/evil.git",
            "GIT_WORK_TREE": "/tmp/evil-work",
            "GIT_COMMON_DIR": "/tmp/evil-common",
            "GIT_OBJECT_DIRECTORY": "/tmp/evil-objects",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/tmp/evil-alt",
            "https_proxy": "http://127.0.0.1:7897",
        }
        previous = {key: os.environ.get(key) for key in extra}
        os.environ.update(extra)
        subprocess.run = fake_run
        try:
            ph_release._run_git(None, "ls-remote", "--tags", "--", FIXED_SOURCE)
        finally:
            subprocess.run = original
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        env = captured["env"]
        self.assertNotIn("GIT_CONFIG_COUNT", env)
        self.assertNotIn("GIT_CONFIG_KEY_0", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_WORK_TREE", env)
        self.assertNotIn("GIT_COMMON_DIR", env)
        self.assertNotIn("GIT_OBJECT_DIRECTORY", env)
        self.assertNotIn("GIT_ALTERNATE_OBJECT_DIRECTORIES", env)
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["https_proxy"], "http://127.0.0.1:7897")
        self.assertEqual(captured["cwd"], Path(tempfile.gettempdir()))
        self.assertIn("credential.helper=", captured["cmd"])

        failed = subprocess.CompletedProcess(
            ["git"],
            1,
            stdout="",
            stderr="fatal: credential helper leaked token=abc",
        )
        subprocess.run = lambda *a, **k: failed
        try:
            with self.assertRaises(ph_release.PHReleaseError) as ctx:
                ph_release._run_git(Path(tempfile.gettempdir()), "fetch", "origin")
        finally:
            subprocess.run = original
        self.assertNotIn("credential", str(ctx.exception).lower())
        self.assertNotIn("token=", str(ctx.exception))

    def test_support_message_uses_everyday_words(self):
        signed_in = ph_release.SupportResult(
            "alice",
            True,
            True,
            "https://github.com/alice/ph-init",
            True,
            True,
        )
        already = ph_release.SupportResult(
            "alice",
            True,
            False,
            "https://github.com/alice/ph-init",
            False,
            True,
        )
        skipped = ph_release.SupportResult(None, False, False, None, False, False)
        created = signed_in.message(after_download=True)
        reused = already.message(after_download=True)
        unsigned = skipped.message(after_download=True)
        follow_up = skipped.message(after_download=False)
        self.assertIn("已经从官方地址下载好了", created)
        self.assertIn("alice", created)
        self.assertIn("https://github.com/alice/ph-init", created)
        self.assertIn("仍从官方地址进行", created)
        self.assertIn("星已经点过", reused)
        self.assertIn("副本已经在这个地址", reused)
        self.assertIn("没有已登录的 GitHub", unsigned)
        self.assertIn(ph_release.OFFICIAL_PAGE, unsigned)
        self.assertIn("官方地址不用再下一次", follow_up)
        for text in (created, reused, unsigned, follow_up):
            lowered = text.lower()
            self.assertNotIn("fork", lowered)
            self.assertNotIn("token", lowered)
            self.assertNotIn("api", lowered)
            self.assertNotIn("github_token", lowered)
            self.assertNotIn("courtesy", lowered)

    def test_prepare_skips_support_when_not_signed_in(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        session = RecordingSupport()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            prepared = self.prepare(transport, "latest", support=session, offer_support=True)
        self.assertEqual(prepared.commit, commit)
        self.assertEqual(session.calls, ["login"])
        self.assertIn("没有已登录的 GitHub", stderr.getvalue())
        self.assertEqual(
            json.loads((prepared.root / ".ph-source.json").read_text(encoding="utf-8"))["source"],
            FIXED_SOURCE,
        )
        self.assertNotIn("root", json.loads((prepared.root / ".ph-source.json").read_text(encoding="utf-8")))

    def test_prepare_records_existing_star_and_copy(self):
        files = self.release_files()
        transport, _ = self.transport_for(files)
        session = RecordingSupport(login="bob", star_created=False, copy_created=False)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            prepared = self.prepare(transport, "latest", support=session, offer_support=True)
        self.assertEqual(session.calls, ["login", ("star", "bob"), ("copy", "bob")])
        self.assertIn("星已经点过", stderr.getvalue())
        self.assertIn("https://github.com/bob/ph-init", stderr.getvalue())
        self.assertEqual(set(prepared.as_dict()), {"version", "tag", "commit", "source", "root"})

    def test_prepare_survives_support_failure(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        session = RecordingSupport(login="carol", error="star")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            prepared = self.prepare(transport, "latest", support=session, offer_support=True)
        self.assertEqual(prepared.commit, commit)
        self.assertIn("安装不受影响", stderr.getvalue())
        self.assertEqual(prepared.source, FIXED_SOURCE)

    def test_failed_download_does_not_offer_support(self):
        transport = DictTransport(ls_error=ph_release.PHReleaseError("network failure talking to source"))
        session = RecordingSupport(login="dave")
        with self.assertRaises(ph_release.PHReleaseError):
            self.prepare(transport, "latest", support=session, offer_support=True)
        self.assertEqual(session.calls, [])

    def test_cli_support_does_not_download(self):
        original = ph_release.GithubSession
        ph_release.GithubSession = RecordingSupport
        stderr = io.StringIO()
        try:
            with redirect_stderr(stderr):
                code = ph_release.main(["support"])
        finally:
            ph_release.GithubSession = original
        self.assertEqual(code, 0)
        self.assertIn("官方地址不用再下一次", stderr.getvalue())

    def make_entry(self, home, *, version=None, junk_only=False, symlink=False):
        entry = home / ".agents" / "skills" / "ph-init"
        if symlink:
            target = home / "entry-target"
            target.mkdir(parents=True)
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.symlink_to(target, target_is_directory=True)
            return entry
        entry.mkdir(parents=True)
        if junk_only:
            (entry / "SKILL.md").write_text("# not a ph-init tree\n", encoding="utf-8")
            return entry
        receipt = {
            "version": version,
            "tag": f"v{version}",
            "commit": "0" * 40,
            "source": FIXED_SOURCE,
        }
        (entry / ".ph-source.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        (entry / "OLD.txt").write_text("old tree\n", encoding="utf-8")
        return entry

    def test_user_entry_refreshes_older_tree_with_trash_backup(self):
        files = self.release_files()
        transport, commit = self.transport_for(files)
        prepared = self.prepare(transport, "latest")
        home = self.temp_dir("ph-user-home-")
        self.make_entry(home, version="1.1.12")
        entry = home / ".agents" / "skills" / "ph-init"
        result = ph_release.refresh_user_entry(prepared.root, home=home)
        self.assertEqual(result["action"], "refreshed")
        self.assertEqual(result["from_version"], "1.1.12")
        self.assertEqual(result["version"], CURRENT_VERSION)
        self.assertEqual(
            (entry / "SKILL.md").read_text(encoding="utf-8"), "# ph-init\n"
        )
        self.assertFalse((entry / "OLD.txt").exists())
        receipt = json.loads((entry / ".ph-source.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["version"], CURRENT_VERSION)
        backup = Path(result["backup"])
        self.assertTrue(backup.is_dir())
        self.assertEqual(
            (backup / "OLD.txt").read_text(encoding="utf-8"), "old tree\n"
        )
        self.assertEqual(backup.parent, home / "trash")

    def test_user_entry_never_downgrades_or_reasks_same_version(self):
        files = self.release_files()
        transport, _ = self.transport_for(files)
        prepared = self.prepare(transport, "latest")
        for version in (CURRENT_VERSION, "9.9.9"):
            home = self.temp_dir("ph-user-home-")
            entry = self.make_entry(home, version=version)
            before = (entry / "OLD.txt").read_bytes()
            result = ph_release.refresh_user_entry(prepared.root, home=home)
            self.assertEqual(result["action"], "skip", version)
            self.assertIn("no downgrade", result["reason"])
            self.assertEqual((entry / "OLD.txt").read_bytes(), before)
            self.assertFalse((home / "trash").exists())

    def test_user_entry_skips_absent_unknown_and_symlink_entries(self):
        files = self.release_files()
        transport, _ = self.transport_for(files)
        prepared = self.prepare(transport, "latest")
        absent = self.temp_dir("ph-user-home-")
        result = ph_release.refresh_user_entry(prepared.root, home=absent)
        self.assertEqual(result["action"], "skip")
        self.assertIn("not installed", result["reason"])
        self.assertFalse((absent / ".agents" / "skills" / "ph-init").exists())
        unknown = self.temp_dir("ph-user-home-")
        entry = self.make_entry(unknown, junk_only=True)
        result = ph_release.refresh_user_entry(prepared.root, home=unknown)
        self.assertEqual(result["action"], "skip")
        self.assertIn("cannot be determined", result["reason"])
        self.assertEqual(
            (entry / "SKILL.md").read_text(encoding="utf-8"), "# not a ph-init tree\n"
        )
        linked = self.temp_dir("ph-user-home-")
        link = self.make_entry(linked, symlink=True)
        result = ph_release.refresh_user_entry(prepared.root, home=linked)
        self.assertEqual(result["action"], "skip")
        self.assertIn("not a plain directory", result["reason"])
        self.assertTrue(link.is_symlink())

    def test_user_entry_requires_prepared_receipt(self):
        root = self.temp_dir("ph-user-root-")
        (root / "release.json").write_text("{}\n", encoding="utf-8")
        home = self.temp_dir("ph-user-home-")
        self.make_entry(home, version="1.1.12")
        with self.assertRaises(ph_release.PHReleaseError):
            ph_release.refresh_user_entry(root, home=home)
        self.assertTrue((home / ".agents" / "skills" / "ph-init" / "OLD.txt").exists())

    def test_ensure_star_targets_new_official_name(self):
        session = ScriptedApiSupport(
            {
                "GET /user/starred/chenweixuanJokes/project-harness": ph_release.SupportActionError(
                    "missing", status=404
                ),
                "PUT /user/starred/chenweixuanJokes/project-harness": {},
            }
        )
        self.assertTrue(session.ensure_star("alice"))
        self.assertEqual(
            session.calls,
            [
                ("GET", "/user/starred/chenweixuanJokes/project-harness"),
                ("PUT", "/user/starred/chenweixuanJokes/project-harness"),
            ],
        )

    def test_ensure_copy_reuses_fork_under_new_name(self):
        session = ScriptedApiSupport(
            {
                "GET /repos/alice/project-harness": {
                    "fork": True,
                    "parent": {"full_name": "chenweixuanJokes/project-harness"},
                    "html_url": "https://github.com/alice/project-harness",
                },
            }
        )
        url, created = session.ensure_copy("alice")
        self.assertFalse(created)
        self.assertEqual(url, "https://github.com/alice/project-harness")
        self.assertEqual(session.calls, [("GET", "/repos/alice/project-harness")])

    def test_ensure_copy_reuses_fork_under_old_name(self):
        session = ScriptedApiSupport(
            {
                "GET /repos/alice/project-harness": ph_release.SupportActionError(
                    "missing", status=404
                ),
                "GET /repos/alice/ph-init": {
                    "fork": True,
                    "parent": {"full_name": "chenweixuanJokes/project-harness"},
                    "html_url": "https://github.com/alice/ph-init",
                },
            }
        )
        url, created = session.ensure_copy("alice")
        self.assertFalse(created)
        self.assertEqual(url, "https://github.com/alice/ph-init")
        self.assertEqual(
            session.calls,
            [
                ("GET", "/repos/alice/project-harness"),
                ("GET", "/repos/alice/ph-init"),
            ],
        )

    def test_ensure_copy_rejects_unrelated_same_name_repos(self):
        fork_created = {"html_url": "https://github.com/alice/project-harness"}
        not_a_fork = ScriptedApiSupport(
            {
                "GET /repos/alice/project-harness": {
                    "fork": False,
                    "html_url": "https://github.com/alice/project-harness",
                },
                "GET /repos/alice/ph-init": ph_release.SupportActionError("missing", status=404),
                "POST /repos/chenweixuanJokes/project-harness/forks": fork_created,
            }
        )
        url, created = not_a_fork.ensure_copy("alice")
        self.assertTrue(created)
        self.assertEqual(url, "https://github.com/alice/project-harness")
        self.assertEqual(
            not_a_fork.calls,
            [
                ("GET", "/repos/alice/project-harness"),
                ("GET", "/repos/alice/ph-init"),
                ("POST", "/repos/chenweixuanJokes/project-harness/forks"),
            ],
        )

        wrong_parent = ScriptedApiSupport(
            {
                "GET /repos/alice/project-harness": {
                    "fork": True,
                    "parent": {"full_name": "someone-else/unrelated"},
                    "html_url": "https://github.com/alice/project-harness",
                },
                "GET /repos/alice/ph-init": {
                    "fork": True,
                    "parent": {"full_name": "someone-else/unrelated"},
                    "html_url": "https://github.com/alice/ph-init",
                },
                "POST /repos/chenweixuanJokes/project-harness/forks": fork_created,
            }
        )
        url, created = wrong_parent.ensure_copy("alice")
        self.assertTrue(created)
        self.assertEqual(url, "https://github.com/alice/project-harness")
        self.assertEqual(
            wrong_parent.calls,
            [
                ("GET", "/repos/alice/project-harness"),
                ("GET", "/repos/alice/ph-init"),
                ("POST", "/repos/chenweixuanJokes/project-harness/forks"),
            ],
        )

    def test_github_request_redacts_token_from_errors(self):
        def fake_urlopen(request, timeout=None):
            self.assertIn("Bearer secret-token", request.get_header("Authorization"))
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "unauthorized",
                hdrs=None,
                fp=io.BytesIO(b'{"message":"bad token=secret-token"}'),
            )

        original = ph_release.urllib.request.urlopen
        ph_release.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(ph_release.SupportActionError) as ctx:
                ph_release._github_request("GET", "/user", "secret-token")
        finally:
            ph_release.urllib.request.urlopen = original
        self.assertNotIn("secret-token", str(ctx.exception))
        self.assertEqual(ctx.exception.status, 401)


class RecordingSupport(ph_release.GithubSession):
    def __init__(self, login=None, star_created=True, copy_url=None, copy_created=True, error=None):
        self.login = login
        self.star_created = star_created
        self.copy_url = copy_url or (f"https://github.com/{login}/ph-init" if login else None)
        self.copy_created = copy_created
        self.error = error
        self.calls = []

    def current_login(self):
        self.calls.append("login")
        if self.error == "login":
            raise ph_release.SupportActionError("login failed")
        return self.login

    def ensure_star(self, login):
        self.calls.append(("star", login))
        if self.error == "star":
            raise ph_release.SupportActionError("star failed", status=403)
        return self.star_created

    def ensure_copy(self, login):
        self.calls.append(("copy", login))
        if self.error == "copy":
            raise ph_release.SupportActionError("copy failed")
        return self.copy_url, self.copy_created


class ScriptedApiSupport(ph_release.GithubSession):
    # _api is replaced by a scripted response table. Keys are "METHOD path"
    # strings; values are payload dicts or exceptions to raise. Every call is
    # recorded, and a call without a scripted answer fails the test.
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _api(self, method, path, *, empty_body=False):
        self.calls.append((method, path))
        result = self.responses[f"{method} {path}"]
        if isinstance(result, Exception):
            raise result
        return result
