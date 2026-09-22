#!/usr/bin/env python3
"""Unit tests for scripts/check_release.py."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_release  # noqa: E402


TRASH_ROOT = Path.home() / "trash"
REQUIRED_SKILLS = [
    "ph-init",
    "ph-merge-update",
    "ph-worktree-enter",
    "ph-worktree-exit",
    "ph-memory-ask",
    "ph-memory-learning",
    "ph-memory-archive",
]
# The pre-1.1.8 era shipped exactly these ten skills (ph-docs-sync arrived in
# 1.1.10, ph-intent-verify in 1.1.13, ph-sure in 1.1.14); the synthetic legacy
# fixture keeps the historical list explicitly instead of slicing the current
# one, so a new release skill can never silently grow the legacy fixture.
LEGACY_TEN_SKILLS = [
    "ph-init",
    "ph-worktree-enter",
    "ph-worktree-exit",
    "ph-memory-capture",
    "ph-memory-archive",
    "ph-memory-ask",
    "ph-intent-new",
    "ph-intent-impl",
    "ph-intent-drop",
    "ph-merge-update",
]


def _read_release_version() -> str:
    data = json.loads((REPO_ROOT / "release.json").read_text(encoding="utf-8"))
    return str(data["version"])


def _bump_patch(version: str, delta: int) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    next_patch = patch + delta
    if next_patch < 0:
        raise ValueError(f"cannot bump {version} by {delta}")
    return f"{major}.{minor}.{next_patch}"


CURRENT = _read_release_version()
NEXT = _bump_patch(CURRENT, 1)
LEGACY_VERSION = "1.1.7"


def _published_predecessor() -> str:
    """The from_version of the migration hop that lands on CURRENT.

    Since 1.2.1 the release chain may use merged hops (1.1.15 -> 1.2.1),
    so the published predecessor is read from migrations/index.json
    instead of being derived arithmetically.
    """

    data = json.loads((REPO_ROOT / "migrations/index.json").read_text(encoding="utf-8"))
    starts = [h["from_version"] for h in data["migrations"] if h["to_version"] == CURRENT]
    assert len(starts) == 1, starts
    return starts[0]


def run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=60)


def copy_repo(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src,
        dest,
        symlinks=False,
        ignore=lambda directory, names: set(shutil.ignore_patterns(
            ".git", "__pycache__", ".zcode", ".DS_Store", "*.pyc"
        )(directory, names)) | ({"AGENTS.md", "CLAUDE.md"} if Path(directory) == src else set()),
    )


class CheckReleaseTests(unittest.TestCase):
    def setUp(self):
        self._temps = []

    def tearDown(self):
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-check-release-{stamp}-{os.getpid()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=False)
        for i, path in enumerate(self._temps):
            if Path(path).exists():
                Path(path).rename(dest / f"{i:02d}-{Path(path).name}")

    def test_prepared_tree_errors_are_not_swallowed(self):
        with mock.patch.object(check_release.ph_release, "validate_prepared_tree", side_effect=check_release.ph_release.PHReleaseError("illegal manifest: skills.required_names mismatch")):
            with self.assertRaisesRegex(check_release.CheckError, "skills.required_names mismatch"):
                check_release._call_prepared_tree(REPO_ROOT, CURRENT, REQUIRED_SKILLS)

    def temp_dir(self, prefix):
        root = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(root)
        return root

    def git_repo(self, prefix, *, with_files=True):
        parent = self.temp_dir(prefix)
        root = parent / "repo"
        if with_files:
            copy_repo(REPO_ROOT, root)
        else:
            root.mkdir()
        for argv in (
            ["git", "init"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "ph-check-test"],
        ):
            proc = run(argv, cwd=root)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return root

    def commit_all(self, repo: Path, message: str) -> str:
        proc = run(["git", "add", "-A"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        proc = run(["git", "commit", "-m", message], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()

    def write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def mutate_release(self, repo: Path, **fields) -> None:
        path = repo / "release.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(fields)
        self.write_json(path, data)

    def mutate_manifest(self, repo: Path, **fields) -> None:
        path = repo / "assets/scaffold/.agents/ph.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(fields)
        self.write_json(path, data)

    def mutate_schema(self, repo: Path, **fields) -> None:
        path = repo / "assets/scaffold/.agents/ph.schema.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(fields)
        self.write_json(path, data)

    def set_index(self, repo: Path, hops: list[dict]) -> None:
        self.write_json(repo / "migrations/index.json", {"format_version": 1, "migrations": hops})

    def assert_fails(self, root: Path, needle: str, tag=None):
        with self.assertRaises(check_release.CheckError) as ctx:
            check_release.validate_tree(root, repo=root, tag=tag)
        self.assertIn(needle, str(ctx.exception))

    def test_current_tree_passes_without_tags(self):
        result = check_release.validate_tree(REPO_ROOT, repo=REPO_ROOT, tag=None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["version"], CURRENT)
        self.assertEqual(result["required_skills"], REQUIRED_SKILLS)
        self.assertNotIn("schema_version", result)

    def test_skill_list_contract(self):
        # 1.2.1 ships seventeen skills; the synthetic pre-1.1.8 legacy fixture
        # must keep exactly the historical ten (ph-docs-sync arrived in
        # 1.1.10, ph-intent-verify in 1.1.13, ph-sure in 1.1.14) instead of
        # slicing the current list, so new release skills never leak into
        # legacy fixtures.
        self.assertEqual(len(REQUIRED_SKILLS), 7)
        self.assertEqual(len(LEGACY_TEN_SKILLS), 10)
        self.assertNotIn("ph-docs-sync", LEGACY_TEN_SKILLS)
        self.assertNotIn("ph-intent-verify", LEGACY_TEN_SKILLS)
        self.assertNotIn("ph-sure", LEGACY_TEN_SKILLS)
        self.assertIn("ph-merge-update", REQUIRED_SKILLS)
        self.assertIn("ph-worktree-exit", REQUIRED_SKILLS)

    def test_cli_current_tree(self):
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = check_release.main(["--root", str(REPO_ROOT)])
        self.assertEqual(code, 0, err.getvalue())
        data = json.loads(buf.getvalue())
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["version"], CURRENT)

    def test_root_skill_codeblock_placeholder_is_not_a_broken_link(self):
        repo = self.git_repo("ph-check-fence-")
        skill = repo / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        text += (
            "\n```text\n"
            "see [missing](./definitely-not-there.md)\n"
            "python3 <ph-init-root>/scripts/ph_release.py prepare --version latest\n"
            "```\n"
        )
        skill.write_text(text, encoding="utf-8")
        check_release.validate_tree(repo, repo=repo, tag=None)

    def test_rejects_mismatched_metadata(self):
        repo = self.git_repo("ph-check-meta-")
        self.mutate_release(repo, schema_version="1.1.1")
        self.assert_fails(repo, "unsupported keys")

        repo = self.git_repo("ph-check-schema-id-")
        self.mutate_schema(repo, **{"$id": "urn:ph:schema:project-harness:1.1.1"})
        self.assert_fails(repo, "$id")

        repo = self.git_repo("ph-check-schema-id-2-")
        self.mutate_schema(repo, **{"$id": "urn:ph:schema:other"})
        self.assert_fails(repo, "$id")

        repo = self.git_repo("ph-check-schema-field-")
        self.mutate_schema(
            repo,
            required=["$schema", "schema_version"],
            properties={"schema_version": {"const": "1.1.1"}},
        )
        self.assert_fails(repo, "schema_version")

        repo = self.git_repo("ph-check-manifest-")
        self.mutate_manifest(repo, schema_version="1.1.1")
        self.assert_fails(repo, "schema_version")

        repo = self.git_repo("ph-check-manifest-2-")
        self.mutate_manifest(repo, template_version="0.0.1")
        self.assert_fails(repo, "template_version")

        repo = self.git_repo("ph-check-skills-")
        data = json.loads((repo / "release.json").read_text(encoding="utf-8"))
        data["required_skills"] = REQUIRED_SKILLS[:-1]
        self.write_json(repo / "release.json", data)
        self.assert_fails(repo, "required_skills")

    def test_rejects_source_identity_and_download_address_drift(self):
        mutations = {
            "FIXED_SOURCE": "https://github.com/chenweixuanJokes/project-harness.git",
            "DOWNLOAD_SOURCE": "https://github.com/chenweixuanJokes/ph-init.git",
            "OFFICIAL_FULL_NAME": "someone/project-harness",
            "OFFICIAL_PAGE": "https://github.com/chenweixuanJokes/ph-init",
        }
        for name, value in mutations.items():
            with self.subTest(constant=name), mock.patch.object(check_release.ph_release, name, value):
                with self.assertRaisesRegex(check_release.CheckError, name):
                    check_release.load_release(REPO_ROOT)

    def test_download_address_cannot_replace_release_identity(self):
        repo = self.git_repo("ph-check-source-identity-")
        self.mutate_release(repo, repository=check_release.ph_release.DOWNLOAD_SOURCE)
        self.assert_fails(repo, "repository mismatch")

    def test_rejects_broken_markdown_link_outside_codeblock(self):
        repo = self.git_repo("ph-check-link-")
        readme = repo / "migrations/README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\n[gone](./no-such-file.md)\n", encoding="utf-8")
        self.assert_fails(repo, "broken markdown link")

    def test_rejects_empty_skill_description(self):
        repo = self.git_repo("ph-check-front-")
        path = repo / "assets/scaffold/.agents/skills/ph-merge-update/SKILL.md"
        path.write_text("---\nname: ph-merge-update\ndescription: \"\"\n---\n# x\n", encoding="utf-8")
        self.assert_fails(repo, "description")

    def test_rejects_invalid_evals_json(self):
        repo = self.git_repo("ph-check-evals-")
        (repo / "evals/evals.json").write_text("{not-json", encoding="utf-8")
        self.assert_fails(repo, "illegal")

    def test_temp_git_same_version_non_payload_change_passes(self):
        repo = self.git_repo("ph-check-nonpayload-")
        self.commit_all(repo, f"v{CURRENT}")
        proc = run(["git", "tag", "-a", f"v{CURRENT}", "-m", f"v{CURRENT}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        (repo / "README.md").write_text("# docs only\n", encoding="utf-8")
        (repo / ".github").mkdir(exist_ok=True)
        (repo / ".github/workflows").mkdir(exist_ok=True)
        (repo / ".github/workflows/check.yml").write_text("name: check\n", encoding="utf-8")
        (repo / ".agents").mkdir(exist_ok=True)
        (repo / ".agents/AGENTS.md").write_text("# Maintainer rules\n", encoding="utf-8")
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs/release-rules.md").write_text("# Version discipline\n", encoding="utf-8")
        result = check_release.validate_tree(repo, repo=repo, tag=None)
        self.assertEqual(result["status"], "ok")

    def test_temp_git_same_version_payload_change_rejected(self):
        repo = self.git_repo("ph-check-payload-")
        self.commit_all(repo, f"v{CURRENT}")
        proc = run(["git", "tag", "-a", f"v{CURRENT}", "-m", f"v{CURRENT}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        skill = repo / "assets/scaffold/.agents/skills/ph-merge-update/SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nextra payload line\n", encoding="utf-8")
        self.assert_fails(repo, "already tagged")

    def test_new_patch_without_migration_record_rejected(self):
        repo = self.git_repo("ph-check-missing-hop-")
        self.commit_all(repo, f"v{CURRENT}")
        proc = run(["git", "tag", "-a", f"v{CURRENT}", "-m", f"v{CURRENT}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.mutate_release(repo, version=NEXT)
        self.mutate_manifest(repo, template_version=NEXT)
        self.assert_fails(repo, f"missing migration record {CURRENT} -> {NEXT}")

    def test_new_patch_with_complete_record_passes(self):
        repo = self.git_repo("ph-check-next-")
        self.commit_all(repo, f"v{CURRENT}")
        proc = run(["git", "tag", "-a", f"v{CURRENT}", "-m", f"v{CURRENT}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.mutate_release(repo, version=NEXT)
        self.mutate_manifest(repo, template_version=NEXT)
        hops = json.loads((repo / "migrations/index.json").read_text(encoding="utf-8"))["migrations"]
        hops.append(
            {
                "from_version": CURRENT,
                "to_version": NEXT,
                "path": f"migrations/{CURRENT}-to-{NEXT}.md",
                "items": ["docs-only"],
            }
        )
        self.set_index(repo, hops)
        (repo / f"migrations/{CURRENT}-to-{NEXT}.md").write_text(
            f"# {CURRENT} → {NEXT}\n\n"
            f"## why\npatch\n\n## from\n{CURRENT}\n\n## to\n{NEXT}\n\n"
            "## affected\ndocs-only\n\n## preserve\nnone\n\n"
            "## conflict\nnone\n\n## verify\nok\n",
            encoding="utf-8",
        )
        result = check_release.validate_tree(repo, repo=repo, tag=None)
        self.assertEqual(result["version"], NEXT)

    def test_tag_validation_requires_matching_commit_and_meta(self):
        repo = self.git_repo("ph-check-tag-")
        commit = self.commit_all(repo, f"v{CURRENT}")
        proc = run(["git", "tag", "-a", f"v{CURRENT}", "-m", f"v{CURRENT}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        result = check_release.validate_tree(repo, repo=repo, tag=f"v{CURRENT}")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(run(["git", "rev-parse", f"v{CURRENT}^{{}}"], cwd=repo).stdout.strip(), commit)

        self.mutate_release(repo, version=NEXT)
        self.mutate_manifest(repo, template_version=NEXT)
        hops = json.loads((repo / "migrations/index.json").read_text(encoding="utf-8"))["migrations"]
        hops.append(
            {
                "from_version": CURRENT,
                "to_version": NEXT,
                "path": f"migrations/{CURRENT}-to-{NEXT}.md",
                "items": ["docs-only"],
            }
        )
        self.set_index(repo, hops)
        (repo / f"migrations/{CURRENT}-to-{NEXT}.md").write_text(
            f"# {CURRENT} → {NEXT}\n\n## why\n\n## from\n\n## to\n\n## affected\ndocs-only\n\n## preserve\n\n## conflict\n\n## verify\n",
            encoding="utf-8",
        )
        self.assert_fails(repo, "does not match release.json version", tag=f"v{CURRENT}")

        repo = self.git_repo("ph-check-tag-head-")
        self.commit_all(repo, f"v{CURRENT}")
        proc = run(["git", "tag", "-a", f"v{CURRENT}", "-m", f"v{CURRENT}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        (repo / "README.md").write_text("# later\n", encoding="utf-8")
        later = self.commit_all(repo, "later")
        self.assertNotEqual(later, run(["git", "rev-parse", f"v{CURRENT}^{{}}"], cwd=repo).stdout.strip())
        self.assert_fails(repo, "does not match HEAD", tag=f"v{CURRENT}")

    def test_complete_chain_across_untagged_intermediate_passes(self):
        published = _published_predecessor()
        repo = self.git_repo("ph-check-chain-ok-")
        self.commit_all(repo, f"v{published}")
        proc = run(["git", "tag", "-a", f"v{published}", "-m", f"v{published}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        result = check_release.validate_tree(repo, repo=repo, tag=None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["version"], CURRENT)

    def test_broken_chain_across_untagged_intermediate_rejected(self):
        # 1.2.1 landed as a merged hop, so the synthetic break removes the
        # hop into CURRENT itself; the validator must still refuse a chain
        # whose latest published tag no longer reaches the working version.
        published = _published_predecessor()
        repo = self.git_repo("ph-check-chain-gap-")
        hops = json.loads((repo / "migrations/index.json").read_text(encoding="utf-8"))["migrations"]
        hops = [
            hop
            for hop in hops
            if not (hop["from_version"] == published and hop["to_version"] == CURRENT)
        ]
        self.set_index(repo, hops)
        self.commit_all(repo, f"v{published}")
        proc = run(["git", "tag", "-a", f"v{published}", "-m", f"v{published}"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assert_fails(repo, f"missing migration record {published} -> {CURRENT}")

    def write_legacy_tree(self, root: Path, version: str, schema_version: str, *, manifest_schema: str | None = None) -> None:
        """Minimal pre-1.1.8 tree for the ph_release compat branch."""

        manifest_schema = manifest_schema or schema_version
        release = {
            "format_version": 1,
            "version": version,
            "schema_version": schema_version,
            "repository": check_release.ph_release.FIXED_SOURCE,
            "required_skills": LEGACY_TEN_SKILLS,
        }
        manifest = {
            "schema_version": manifest_schema,
            "template_version": version,
            "skills": {"required_names": LEGACY_TEN_SKILLS},
        }
        schema = {"$id": f"urn:ph:schema:project-harness:{schema_version}"}
        hop = {
            "from_version": "1.0.0",
            "to_version": version,
            "path": f"migrations/1.0.0-to-{version}.md",
            "items": ["legacy-fixture"],
        }
        files = {
            "release.json": release,
            "SKILL.md": "# ph-init\n",
            "scripts/ph_init.py": "print('init')\n",
            "scripts/ph_release.py": "print('release')\n",
            "scripts/ph_merge_update.py": "print('merge')\n",
            "assets/scaffold/.agents/ph.json": manifest,
            "assets/scaffold/.agents/ph.schema.json": schema,
            "assets/scaffold/.agents/AGENTS.md": "# agents\n",
            "migrations/index.json": {"format_version": 1, "migrations": [hop]},
            f"migrations/1.0.0-to-{version}.md": f"# 1.0.0 to {version}\n",
        }
        for name in LEGACY_TEN_SKILLS:
            if name != "ph-init":
                files[f"assets/scaffold/.agents/skills/{name}/SKILL.md"] = f"# {name}\n"
        for rel, data in files.items():
            if isinstance(data, str):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(data, encoding="utf-8")
            else:
                self.write_json(root / rel, data)

    def test_prepared_compat_branches_for_legacy_trees(self):
        legacy = self.temp_dir("ph-check-legacy-ok-")
        self.write_legacy_tree(legacy, LEGACY_VERSION, "1.1.1")
        check_release._call_prepared_tree(legacy, LEGACY_VERSION, REQUIRED_SKILLS)

        inconsistent = self.temp_dir("ph-check-legacy-bad-")
        self.write_legacy_tree(inconsistent, LEGACY_VERSION, "1.1.1", manifest_schema="9.9.9")
        with self.assertRaises(check_release.CheckError) as ctx:
            check_release._call_prepared_tree(inconsistent, LEGACY_VERSION, REQUIRED_SKILLS)
        self.assertIn("schema_version", str(ctx.exception))

        # A >= 1.1.8 tree must not sneak the legacy shape through compat.
        residue = self.temp_dir("ph-check-residue-")
        self.write_legacy_tree(residue, "1.1.8", "1.1.1")
        with self.assertRaises(check_release.CheckError) as ctx:
            check_release._call_prepared_tree(residue, "1.1.8", REQUIRED_SKILLS)
        self.assertIn("schema_version", str(ctx.exception))

    def test_mocked_git_tags_reject_payload_rewrite_of_published_version(self):
        repo = self.temp_dir("ph-check-mock-")
        published = {"release.json": b'{"version":"1.1.1"}\n', "SKILL.md": b"old\n"}
        current = dict(published)
        current["SKILL.md"] = b"changed\n"
        hops = [
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
                "items": ["merge-update"],
            },
        ]
        release = {
            "version": "1.1.1",
            "required_skills": REQUIRED_SKILLS,
        }
        with mock.patch.object(check_release, "list_published_tags", return_value={"v1.1.1": "a" * 40}), \
             mock.patch.object(check_release, "payload_map_from_tree", return_value=current), \
             mock.patch.object(check_release, "payload_map_from_git", return_value=published):
            with self.assertRaises(check_release.CheckError) as ctx:
                check_release.validate_version_discipline(
                    repo, repo, release, hops, {"v1.1.1": "a" * 40}, None
                )
        self.assertIn("already tagged", str(ctx.exception))

    def test_cli_rejects_bad_tag_flag(self):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            try:
                check_release.main(["--root", str(REPO_ROOT), "--tag", "1.1.1"])
            except check_release.CheckError as exc:
                sys.stderr.write(f"error: {exc}\n")
                raise SystemExit(1)
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("unsupported --tag", err.getvalue())


if __name__ == "__main__":
    unittest.main()
