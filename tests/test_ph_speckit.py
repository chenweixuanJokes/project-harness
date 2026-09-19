#!/usr/bin/env python3
"""ph_speckit integration tests: conversion, safety, provenance, constitution.

The pinned official spec-kit release is converted to the ph-* identity and
installed through ph_speckit.py. These tests pin the conversion contract
(the single-source skill lists, hyphen and dot form, upstream-internal
identifiers left untouched, workflow-engine assets excluded), the write-path
safety (ancestor symlinks and containment), the cache protections (venv
revalidation, staging baselines), and the constitution governance override
with links rendered for the materialized document depth.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

import ph_init  # noqa: E402
import ph_merge_update  # noqa: E402
import ph_speckit  # noqa: E402
import _speckit_seed  # noqa: E402

TRASH_ROOT = Path.home() / "trash"
# The static pin: the ten upstream names and the ph identities they install
# as. This is the independent guard against accidental edits of speckit.json;
# the runtime code must never re-spell the list.
STATIC_CORE_SKILLS = (
    "analyze", "checklist", "clarify", "constitution", "converge",
    "implement", "plan", "specify", "tasks", "taskstoissues",
)
STATIC_REQUIRED_SKILLS = (
    "ph-init", "ph-merge-update", "ph-worktree-enter", "ph-worktree-exit",
)


class SingleSourceContractTests(unittest.TestCase):
    def test_static_pin_matches_the_speckit_contract_file(self):
        contract = ph_speckit.speckit_contract()
        self.assertEqual(tuple(sorted(contract["skills"])), tuple(sorted(STATIC_CORE_SKILLS)))
        self.assertEqual(
            tuple(sorted(ph_init.RELEASE["required_skills"])),
            tuple(sorted(STATIC_REQUIRED_SKILLS)),
        )

    def test_every_module_derives_the_same_list(self):
        # The list is the single sorted canonical order (this used to be a
        # tautological self-comparison that could never fail).
        self.assertEqual(ph_init.SPECKIT_CORE_SKILLS, tuple(sorted(ph_init.SPECKIT_CORE_SKILLS)))
        self.assertEqual(ph_speckit.SPECKIT_CORE_SKILLS, ph_init.SPECKIT_CORE_SKILLS)
        self.assertEqual(
            ph_init.ALL_REQUIRED_SKILL_NAMES,
            ph_init.REQUIRED_SKILLS + tuple(f"ph-{c}" for c in STATIC_CORE_SKILLS),
        )
        self.assertEqual(
            tuple(ph_merge_update.ph_init.SPECKIT_SKILL_NAMES),
            tuple(f"ph-{c}" for c in STATIC_CORE_SKILLS),
        )


class ConversionContractTests(unittest.TestCase):
    def test_hyphen_and_dot_forms_convert(self):
        text = (
            "Run $speckit-plan then /speckit-specify or /skill:speckit-implement. "
            "The speckit-plan skill follows speckit.tasks in workflow.yml "
            "(command: speckit.tasks), then speckit-implement runs."
        )
        converted = ph_speckit.convert_core_references(text)
        self.assertIn("$ph-plan", converted)
        self.assertIn("/ph-specify", converted)
        self.assertIn("/skill:ph-implement", converted)
        self.assertIn("(command: ph.tasks)", converted)
        self.assertNotIn("speckit-", converted)
        self.assertNotIn("speckit.plan", converted)
        # idempotent
        self.assertEqual(converted, ph_speckit.convert_core_references(converted))

    def test_upstream_internal_identifiers_are_preserved(self):
        text = (
            "The extension hook speckit.git.commit runs as $speckit-git-commit; "
            "the CLI contract key speckit_version and format_speckit_command stay "
            "upstream-internal, like speckit_version >=0.8.5."
        )
        converted = ph_speckit.convert_core_references(text)
        self.assertEqual(converted, text)

    def test_convert_skill_text_adds_provenance_and_renames(self):
        contract = ph_speckit.speckit_contract()
        core = "specify"
        original = (
            "---\n"
            'name: "speckit-specify"\n'
            "description: upstream skill\n"
            "---\n"
            "# speckit-specify\n"
            "Calls $speckit-plan; the hook $speckit-git-commit stays.\n"
        )
        converted = ph_speckit.convert_skill_text(original, core, contract)
        self.assertIn('name: "ph-specify"', converted)
        self.assertIn("Calls $ph-plan", converted)
        self.assertIn("$speckit-git-commit stays", converted)
        self.assertIn("x-ph-upstream:", converted)
        self.assertIn(f"  original_name: speckit-{core}", converted)
        self.assertEqual(ph_speckit.skill_upstream_commit(converted), contract["commit"])


class RealGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = _speckit_seed.ensure_seed()

    def setUp(self):
        self._temps = []

    def temp_dir(self, prefix):
        path = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(path)
        return path

    def tearDown(self):
        if not self._temps:
            return
        TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        dest = TRASH_ROOT / f"ph-speckit-tests-{os.getpid()}-{self._temps[0].name}"
        dest.mkdir(parents=True, exist_ok=True)
        for i, temp in enumerate(self._temps):
            target = dest / f"{i:02d}"
            if temp.exists() and not target.exists():
                temp.rename(target)

    def repo(self, prefix):
        path = self.temp_dir(prefix)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        return path

    def test_seed_matches_the_install_contract(self):
        for core in STATIC_CORE_SKILLS:
            skill = self.seed / ".agents" / "skills" / f"ph-{core}" / "SKILL.md"
            self.assertTrue(skill.is_file(), f"missing converted skill: ph-{core}")
            text = skill.read_text(encoding="utf-8")
            self.assertIn(f'name: "ph-{core}"', text[:512])
            self.assertIn("x-ph-upstream:", text)
        # upstream-internal identifiers survive the real conversion
        specify = (self.seed / ".agents" / "skills" / "ph-specify" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("$speckit-git-commit", specify)
        self.assertIn("speckit.git.commit", specify)
        # shared infra carries the rename
        template = (self.seed / ".specify" / "templates" / "plan-template.md").read_text(encoding="utf-8")
        self.assertIn("$ph-plan", template)
        prereq = (self.seed / ".specify" / "scripts" / "bash" / "check-prerequisites.sh").read_text(encoding="utf-8")
        self.assertIn("$ph-specify", prereq)
        # workflow-engine assets are excluded by contract
        self.assertFalse((self.seed / ".specify" / "workflows").exists())

    def test_cmd_verify_accepts_a_complete_install(self):
        repo = self.repo("ph-speckit-verify-install-")
        manifest = repo / ".agents/ph.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="utf-8")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"])
        result = ph_speckit.cmd_verify(repo)
        self.assertEqual(result["problems"], [], result)

    def test_install_conflict_and_write_protection(self):
        repo = self.repo("ph-speckit-conflict-")
        # A user-owned same-name skill blocks the install without any write.
        custom = repo / ".agents" / "skills" / "ph-specify" / "SKILL.md"
        custom.parent.mkdir(parents=True)
        custom.write_text(
            "---\nname: ph-specify\ndescription: user content\n---\n# ours\n", encoding="utf-8"
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"])
        by_path = {item["path"]: item for item in payload["items"]}
        self.assertEqual(by_path[".agents/skills/ph-specify/SKILL.md"]["kind"], "conflict")
        self.assertFalse((repo / ".specify").exists(), "a blocked install must write nothing")
        self.assertIn("user content", custom.read_text(encoding="utf-8"))

    def test_apply_refuses_symlinked_destination_ancestors(self):
        repo = self.repo("ph-speckit-symlink-")
        outside = self.temp_dir("ph-speckit-outside-")
        (repo / ".agents").mkdir()
        (repo / ".agents" / "skills").symlink_to(outside)
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        # The unsafe destination is a conflict: the install stays blocked and
        # nothing is written through the link (no mid-apply crash either).
        self.assertTrue(payload["blocked"], "a symlinked skills root must block the install")
        self.assertFalse(payload["apply"])
        conflicts = [i for i in payload["items"] if i["kind"] == "conflict"]
        self.assertTrue(conflicts)
        self.assertTrue(all("symlink" in i["reason"] for i in conflicts), conflicts)
        self.assertFalse((outside / "ph-specify").exists(), "no write may escape through the link")

    def test_apply_refuses_symlinked_specify_ancestor(self):
        repo = self.repo("ph-speckit-specify-link-")
        outside = self.temp_dir("ph-speckit-outside2-")
        (repo / ".specify").symlink_to(outside)
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], "a symlinked .specify must block the install")
        self.assertFalse((outside / "templates").exists())

    def test_ensure_safe_write_dest_rejects_hardlinks_and_escapes(self):
        repo = self.repo("ph-speckit-safe-dest-")
        target = repo / ".agents" / "skills" / "ph-specify" / "SKILL.md"
        target.parent.mkdir(parents=True)
        hard_source = self.temp_dir("ph-speckit-hardlink-") / "source.md"
        hard_source.write_text("shared\n", encoding="utf-8")
        os.link(hard_source, target)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_speckit.ensure_safe_write_dest(repo, ".agents/skills/ph-specify/SKILL.md")
        self.assertIn("hardlink", str(ctx.exception))

    def test_validate_staging_detects_tampering(self):
        staging = self.temp_dir("ph-speckit-tamper-")
        shutil.copytree(self.seed / ".specify", staging / ".specify")
        contract = ph_speckit.speckit_contract()
        # A staging without the official manifests is rejected outright.
        with self.assertRaises(ph_init.PHError):
            ph_speckit.validate_staging(staging, contract, clone=None)

    def test_validate_staging_rejects_drifted_skeleton(self):
        # A full pristine staging (from the verified cache) passes with the
        # clone baseline; tampering with the constitution skeleton - which the
        # official manifests do not cover - is caught by the clone comparison.
        cache_root = ph_speckit.cache_root(None)
        contract = ph_speckit.speckit_contract()
        tag_dir = cache_root / f"{contract['tag']}-{contract['commit'][:12]}"
        clone = tag_dir / "clone"
        source_staging = tag_dir / "staging"
        if not clone.is_dir() or not source_staging.is_dir():
            self.skipTest("verified clone/staging not cached on this machine")
        staging = self.temp_dir("ph-speckit-staging-")
        shutil.copytree(source_staging, staging, ignore=shutil.ignore_patterns(".git"), dirs_exist_ok=True)
        ph_speckit.validate_staging(staging, contract, clone=clone)
        # Tamper with the constitution skeleton (not manifest-covered).
        (staging / ".specify" / "memory" / "constitution.md").write_text(
            "tampered\n", encoding="utf-8"
        )
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_speckit.validate_staging(staging, contract, clone=clone)
        self.assertIn("verified pinned template", str(ctx.exception))

    def test_ensure_venv_rebuilds_a_broken_cached_environment(self):
        contract = ph_speckit.speckit_contract()
        root = self.temp_dir("ph-speckit-venv-")
        venv = root / "venv"
        venv.mkdir(parents=True)
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        # A marker and a specify binary that always fails: the cached venv is
        # unusable, so the reuse path must rebuild rather than raise.
        (bin_dir / "specify").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        (bin_dir / "specify").chmod(0o755)
        (venv / ".ph-speckit-installed").write_text(
            f"{contract['tag']} {contract['commit']}\n", encoding="utf-8"
        )
        with mock.patch.object(
            ph_speckit, "run_checked", side_effect=ph_init.PHError("command failed")
        ):
            with self.assertRaises(ph_init.PHError):
                ph_speckit.ensure_venv(contract, root, Path("/nonexistent-clone"))
        # The broken cached venv was discarded ahead of the rebuild attempt
        # instead of failing forever on the unusable cache.
        self.assertFalse((venv / ".ph-speckit-installed").exists())


class SpecifyOwnershipTests(unittest.TestCase):
    """Ownership of an existing managed file must be proven, never assumed.

    A differing managed file (skill, .specify file, constitution override) is
    only rewritten when the per-file content baseline recorded by the last PH
    install (`speckit.files` in .agents/ph.json) still matches the on-disk
    bytes. Generation markers - the manifest's speckit record, its skills
    mapping, a skill's x-ph-upstream block, the override's PH marker - say
    only that PH once wrote the path, never that the user has not edited it,
    so a user's added text (even arbitrary Chinese prose in a converted
    template) must surface as a conflict, never a silent overwrite. Identical
    bytes still skip, so a healthy install is unaffected.
    """

    @classmethod
    def setUpClass(cls):
        cls.seed = _speckit_seed.ensure_seed()
        cls.contract = ph_speckit.speckit_contract()

    def setUp(self):
        self._temps = []

    def temp_dir(self, prefix):
        path = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(path)
        return path

    def tearDown(self):
        if not self._temps:
            return
        TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        dest = TRASH_ROOT / f"ph-speckit-own-{os.getpid()}-{self._temps[0].name}"
        dest.mkdir(parents=True, exist_ok=True)
        for i, temp in enumerate(self._temps):
            target = dest / f"{i:02d}"
            if temp.exists() and not target.exists():
                temp.rename(target)

    def repo(self, prefix):
        path = self.temp_dir(prefix)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        return path

    def staging_template(self, rel: str) -> tuple[bytes, bytes]:
        staging = ph_speckit.resolve_staging(None, self.contract)
        raw = (staging / rel).read_bytes()
        return raw, ph_speckit.convert_shared_bytes(raw)

    def staging_skill(self, core: str) -> bytes:
        staging = ph_speckit.resolve_staging(None, self.contract)
        src = staging / ph_speckit.SPECKIT_GENERATED_SKILLS_DIR / ph_speckit.speckit_skill_name(core) / "SKILL.md"
        return ph_speckit.convert_skill_text(src.read_text(encoding="utf-8"), core, self.contract).encode("utf-8")

    def write_manifest(
        self,
        repo: Path,
        *,
        commit: str,
        tag: str,
        version: str,
        files: dict[str, str] | None = None,
    ) -> None:
        manifest = repo / ".agents" / "ph.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        section = {
            "repository": self.contract["repository"],
            "tag": tag,
            "commit": commit,
            "version": version,
            "skills": {"ph-plan": "speckit-plan"},
        }
        if files is not None:
            section["files"] = files
        manifest.write_text(json.dumps({"speckit": section}), encoding="utf-8")

    def item(self, payload: dict, rel: str) -> dict:
        return next(i for i in payload["items"] if i["path"] == rel)

    def test_user_specify_file_without_provenance_is_never_overwritten(self):
        repo = self.repo("ph-speckit-user-specify-")
        custom = repo / ".specify" / "templates" / "plan-template.md"
        custom.parent.mkdir(parents=True)
        custom.write_text("# 我的项目自有计划模板\n", encoding="utf-8")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        by_path = {item["path"]: item for item in payload["items"]}
        self.assertEqual(by_path[".specify/templates/plan-template.md"]["kind"], "conflict")
        self.assertEqual(custom.read_text(encoding="utf-8"), "# 我的项目自有计划模板\n")
        # A blocked install writes nothing at all.
        self.assertFalse((repo / ".agents" / "skills" / "ph-plan").exists())

    def test_baseline_backed_upgrade_writes_and_re_records_baselines(self):
        # The safe upgrade path: the manifest records the per-file baseline of
        # the previous generation and the on-disk bytes still match it, so the
        # file is provably unmodified and may be replaced by the new one.
        repo = self.repo("ph-speckit-upgrade-")
        _raw, converted = self.staging_template(".specify/templates/plan-template.md")
        older = converted + "\nolder generation line\n".encode("utf-8")
        dest = repo / ".specify" / "templates" / "plan-template.md"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(older)
        self.write_manifest(
            repo,
            commit="0" * 40,
            tag="v0.0.1",
            version="0.0.1",
            files={".specify/templates/plan-template.md": hashlib.sha256(older).hexdigest()},
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ".specify/templates/plan-template.md")["kind"], "write")
        self.assertEqual(dest.read_bytes(), converted)
        # The manifest provenance advanced to the pinned contract and the
        # baseline now records the freshly installed bytes.
        section = ph_speckit.read_installed_speckit_section(repo)
        self.assertEqual(section["commit"], self.contract["commit"])
        self.assertEqual(
            section["files"][".specify/templates/plan-template.md"],
            hashlib.sha256(converted).hexdigest(),
        )

    def test_old_generation_with_user_added_text_without_baseline_conflicts(self):
        # The regression this file exists for: a previous-generation install
        # (old commit recorded in the manifest) whose converted template the
        # user extended with their own Chinese notes. The old contract treated
        # the manifest's generation record as ownership and silently overwrote
        # the notes; without a per-file content baseline the differing file is
        # user content and must conflict.
        repo = self.repo("ph-speckit-user-append-")
        _raw, converted = self.staging_template(".specify/templates/plan-template.md")
        user_text = "\n\n## 我们项目自己的补充\n\n交付前必须通过内部验收，本节为项目自有约定。\n"
        disk = converted + user_text.encode("utf-8")
        dest = repo / ".specify" / "templates" / "plan-template.md"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(disk)
        # A pre-baseline manifest: it records the generation, never the bytes.
        self.write_manifest(repo, commit="0" * 40, tag="v0.0.1", version="0.0.1")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ".specify/templates/plan-template.md")["kind"], "conflict")
        self.assertIn("项目自有约定", dest.read_text(encoding="utf-8"))

    def test_recorded_generation_with_upstream_named_file_conflicts(self):
        repo = self.repo("ph-speckit-reverted-")
        raw, _converted = self.staging_template(".specify/templates/plan-template.md")
        dest = repo / ".specify" / "templates" / "plan-template.md"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(raw + "\nuser note\n".encode("utf-8"))
        self.write_manifest(repo, commit="0" * 40, tag="v0.0.1", version="0.0.1")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ".specify/templates/plan-template.md")["kind"], "conflict")

    def test_specify_file_edited_within_this_generation_conflicts(self):
        repo = self.repo("ph-speckit-same-commit-")
        _raw, converted = self.staging_template(".specify/templates/plan-template.md")
        dest = repo / ".specify" / "templates" / "plan-template.md"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(converted + "\n用户改动。\n".encode("utf-8"))
        self.write_manifest(
            repo,
            commit=self.contract["commit"],
            tag=self.contract["tag"],
            version=self.contract["version"],
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ".specify/templates/plan-template.md")["kind"], "conflict")
        self.assertIn("用户改动。", dest.read_text(encoding="utf-8"))

    def test_drifted_baseline_conflicts_even_from_a_recorded_generation(self):
        # A baseline exists, but the on-disk bytes no longer match it: the
        # user edited the file after the install, so no upgrade may overwrite.
        repo = self.repo("ph-speckit-drift-")
        _raw, converted = self.staging_template(".specify/templates/plan-template.md")
        disk = converted + "\n用户改动。\n".encode("utf-8")
        dest = repo / ".specify" / "templates" / "plan-template.md"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(disk)
        self.write_manifest(
            repo,
            commit="0" * 40,
            tag="v0.0.1",
            version="0.0.1",
            files={".specify/templates/plan-template.md": hashlib.sha256(converted).hexdigest()},
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ".specify/templates/plan-template.md")["kind"], "conflict")
        self.assertIn("用户改动。", dest.read_text(encoding="utf-8"))

    def test_malformed_baseline_entries_are_dropped_not_trusted(self):
        # A corrupted `files` record (wrong hash shape) must never unlock an
        # overwrite: it is treated as absent and the file conflicts.
        repo = self.repo("ph-speckit-bad-baseline-")
        _raw, converted = self.staging_template(".specify/templates/plan-template.md")
        disk = converted + "\nolder generation line\n".encode("utf-8")
        dest = repo / ".specify" / "templates" / "plan-template.md"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(disk)
        self.write_manifest(
            repo,
            commit="0" * 40,
            tag="v0.0.1",
            version="0.0.1",
            files={".specify/templates/plan-template.md": "not-a-hash"},
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ".specify/templates/plan-template.md")["kind"], "conflict")

    def test_stock_upstream_specify_file_is_adopted(self):
        repo = self.repo("ph-speckit-stock-")
        raw, converted = self.staging_template(".specify/templates/plan-template.md")
        dest = repo / ".specify" / "templates" / "plan-template.md"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(raw)  # a stock, unmodified upstream file
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ".specify/templates/plan-template.md")["kind"], "write")
        self.assertEqual(dest.read_bytes(), converted)

    def test_install_records_per_file_baselines(self):
        # Every install re-records the baselines: skills, managed .specify
        # files, and the constitution override - but never the user-owned
        # memory constitution.
        repo = self.repo("ph-speckit-baselines-")
        manifest = repo / ".agents" / "ph.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"speckit": {"skills": {}}}), encoding="utf-8")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"], payload["items"])
        section = ph_speckit.read_installed_speckit_section(repo)
        files = section.get("files")
        self.assertIsInstance(files, dict)
        for core in ph_speckit.SPECKIT_CORE_SKILLS:
            rel = f".agents/skills/ph-{core}/SKILL.md"
            self.assertEqual(
                files.get(rel), ph_init.sha256_file(repo / rel), f"baseline missing or wrong for {rel}"
            )
        self.assertEqual(files[".specify/templates/plan-template.md"], ph_init.sha256_file(repo / ".specify/templates/plan-template.md"))
        self.assertEqual(
            files[ph_speckit.CONSTITUTION_OVERRIDE_REL],
            ph_init.sha256_file(repo / ph_speckit.CONSTITUTION_OVERRIDE_REL),
        )
        self.assertNotIn(ph_speckit.CONSTITUTION_MEMORY_REL, files)

    def _fresh_init_window(self, prefix: str) -> tuple[Path, str, Path]:
        """The fresh-init window: install wrote the override (its sha256 is
        this run's content proof), then the scaffold deploy replaced the
        manifest with its template (no speckit.files) and grew the docs/
        约束规范 tree the override references."""
        repo = self.repo(prefix)
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"], payload["items"])
        self.write_manifest(
            repo,
            commit=self.contract["commit"],
            tag=self.contract["tag"],
            version=self.contract["version"],
            files=None,
        )
        override_rel = ph_speckit.CONSTITUTION_OVERRIDE_REL
        install_sha = self.item(payload, override_rel)["sha256"]
        docs = repo / "docs" / "约束规范" / "工程规范"
        docs.mkdir(parents=True)
        (docs / "对用户提问.md").write_text("# 对用户提问\n", encoding="utf-8")
        return repo, install_sha, repo / override_rel

    def test_record_baselines_refresh_refuses_a_user_edited_override(self):
        # Between the install and record-baselines the user appended their own
        # note to the freshly installed override. The install sha no longer
        # matches the disk bytes, so the refresh is refused, the user text
        # stays, and the edited file is never registered as an official
        # baseline.
        repo, install_sha, dest = self._fresh_init_window("ph-speckit-record-user-edit-")
        dest.write_bytes(dest.read_bytes() + "\n<!-- 用户补充的项目宪法说明 -->\n".encode("utf-8"))
        result = ph_speckit.cmd_record_baselines(repo, None, refresh_override_sha=install_sha)
        self.assertEqual(result["override"], "conflict")
        self.assertTrue(result["blocked"])
        self.assertIn("用户补充的项目宪法说明", dest.read_text(encoding="utf-8"))
        section = ph_speckit.read_installed_speckit_section(repo)
        self.assertNotIn(ph_speckit.CONSTITUTION_OVERRIDE_REL, section.get("files") or {})

    def test_record_baselines_refresh_rebinds_this_runs_own_output(self):
        # The override still carries exactly the bytes this run's install
        # wrote (the recorded sha matches), so the scaffold-deployed docs tree
        # justifies refreshing the navigation zone and re-recording the
        # baseline.
        repo, install_sha, dest = self._fresh_init_window("ph-speckit-record-refresh-")
        result = ph_speckit.cmd_record_baselines(repo, None, refresh_override_sha=install_sha)
        self.assertEqual(result["override"], "write")
        self.assertIn("对用户提问", dest.read_text(encoding="utf-8"))
        section = ph_speckit.read_installed_speckit_section(repo)
        self.assertEqual(
            section["files"][ph_speckit.CONSTITUTION_OVERRIDE_REL],
            ph_init.sha256_file(dest),
        )

    def test_record_baselines_never_registers_user_edited_files(self):
        # After the scaffold deploy replaced the manifest (no speckit.files),
        # record-baselines re-derives the managed set: a managed file the user
        # edited in the window stays a conflict and is never registered as an
        # official baseline; its bytes are never rewritten either.
        repo = self.repo("ph-speckit-record-user-file-")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"], payload["items"])
        self.write_manifest(
            repo,
            commit=self.contract["commit"],
            tag=self.contract["tag"],
            version=self.contract["version"],
            files=None,
        )
        rel = ".specify/templates/plan-template.md"
        dest = repo / rel
        dest.write_bytes(dest.read_bytes() + "\n<!-- 用户自定义 -->\n".encode("utf-8"))
        result = ph_speckit.cmd_record_baselines(repo, None)
        self.assertNotIn(rel, result["files"])
        self.assertIn("用户自定义", dest.read_text(encoding="utf-8"))

    def test_record_conflict_preserves_manifest_and_override(self):
        repo, install_sha, override = self._fresh_init_window("ph-record-atomic-")
        manifest = repo / ".agents/ph.json"
        before_manifest = manifest.read_bytes()
        before_override = override.read_bytes()
        target = repo / ".specify/templates/plan-template.md"
        target.write_bytes(target.read_bytes() + b"\nuser customization\n")
        result = ph_speckit.cmd_record_baselines(repo, None, install_sha)
        self.assertTrue(result["blocked"])
        self.assertEqual(manifest.read_bytes(), before_manifest)
        self.assertEqual(override.read_bytes(), before_override)

    def test_init_reports_baseline_conflict(self):
        with mock.patch.object(ph_init, "run_speckit", return_value={"blocked": True, "conflicts": ["customized file"]}):
            report = mock.Mock()
            ph_init.record_speckit_baselines(report, self.repo("ph-record-report-"), None)
        self.assertEqual(report.add.call_args.args[0], "error")

    def test_verify_requires_installation_record(self):
        repo = self.repo("ph-verify-record-")
        ph_speckit.cmd_install(repo, apply=True, cache=None)
        manifest = repo / ".agents/ph.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}\n", encoding="utf-8")
        result = ph_speckit.cmd_verify(repo)
        self.assertFalse(result["ok"])
        self.assertTrue(any("installation record" in p for p in result["problems"]))

    def test_user_edited_skill_with_drifted_baseline_conflicts(self):
        # The manifest's skills mapping and the file's own x-ph-upstream block
        # are generation markers; the user edit keeps them and must still win.
        repo = self.repo("ph-speckit-skill-edit-")
        rel = ".agents/skills/ph-plan/SKILL.md"
        data = self.staging_skill("plan")
        edited = data + "\n<!-- 项目自定义：交付前先跑 make check。 -->\n".encode("utf-8")
        dest = repo / rel
        dest.parent.mkdir(parents=True)
        dest.write_bytes(edited)
        self.write_manifest(
            repo,
            commit=self.contract["commit"],
            tag=self.contract["tag"],
            version=self.contract["version"],
            files={rel: hashlib.sha256(data).hexdigest()},
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, rel)["kind"], "conflict")
        self.assertIn("项目自定义", dest.read_text(encoding="utf-8"))

    def test_unmodified_skill_with_matching_baseline_upgrades(self):
        # The safe skill-upgrade path: the on-disk bytes are exactly the
        # previous install's baseline, so a newer pinned generation may
        # replace them.
        repo = self.repo("ph-speckit-skill-upgrade-")
        rel = ".agents/skills/ph-plan/SKILL.md"
        data = self.staging_skill("plan")
        older = data + "\n<!-- older generation -->\n".encode("utf-8")
        dest = repo / rel
        dest.parent.mkdir(parents=True)
        dest.write_bytes(older)
        self.write_manifest(
            repo,
            commit="0" * 40,
            tag="v0.0.1",
            version="0.0.1",
            files={rel: hashlib.sha256(older).hexdigest()},
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, rel)["kind"], "write")
        self.assertEqual(dest.read_bytes(), data)

    def test_skill_with_provenance_but_no_baseline_conflicts(self):
        # Regression for the removed provenance path: an x-ph-upstream block
        # alone used to authorize an overwrite. The user edit below keeps the
        # whole provenance block and must still block the install.
        repo = self.repo("ph-speckit-skill-prov-")
        rel = ".agents/skills/ph-plan/SKILL.md"
        data = self.staging_skill("plan")
        edited = data + "\n用户补充的一行。\n".encode("utf-8")
        dest = repo / rel
        dest.parent.mkdir(parents=True)
        dest.write_bytes(edited)
        self.write_manifest(
            repo,
            commit="0" * 40,
            tag="v0.0.1",
            version="0.0.1",
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, rel)["kind"], "conflict")
        self.assertIn("用户补充的一行。", dest.read_text(encoding="utf-8"))

    def test_user_edited_override_with_drifted_baseline_conflicts(self):
        # The PH marker in the override is a generation marker too: a refresh
        # must not replace an override whose bytes drifted from the baseline.
        repo = self.repo("ph-speckit-override-edit-")
        pristine = ph_speckit.render_constitution_override(repo, self.seed, self.contract)
        edited = pristine + "\n项目自有补充段落。\n".encode("utf-8")
        dest = repo / ph_speckit.CONSTITUTION_OVERRIDE_REL
        dest.parent.mkdir(parents=True)
        dest.write_bytes(edited)
        self.write_manifest(
            repo,
            commit=self.contract["commit"],
            tag=self.contract["tag"],
            version=self.contract["version"],
            files={ph_speckit.CONSTITUTION_OVERRIDE_REL: hashlib.sha256(pristine).hexdigest()},
        )
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ph_speckit.CONSTITUTION_OVERRIDE_REL)["kind"], "conflict")
        self.assertIn("项目自有补充段落", dest.read_text(encoding="utf-8"))

    def test_override_refresh_on_a_matching_baseline_and_re_record(self):
        # docs/约束规范 gained a document: the PH-managed navigation zone
        # refreshes because the override bytes still match the baseline, and
        # the new baseline is recorded afterwards.
        repo = self.repo("ph-speckit-override-refresh-")
        pristine = ph_speckit.render_constitution_override(repo, self.seed, self.contract)
        dest = repo / ph_speckit.CONSTITUTION_OVERRIDE_REL
        dest.parent.mkdir(parents=True)
        dest.write_bytes(pristine)
        self.write_manifest(
            repo,
            commit=self.contract["commit"],
            tag=self.contract["tag"],
            version=self.contract["version"],
            files={ph_speckit.CONSTITUTION_OVERRIDE_REL: hashlib.sha256(pristine).hexdigest()},
        )
        governance = repo / "docs" / "约束规范" / "工程规范"
        governance.mkdir(parents=True)
        (governance / "Git与并行开发.md").write_text("# Git与并行开发\n正文。\n", encoding="utf-8")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"], payload["items"])
        self.assertEqual(self.item(payload, ph_speckit.CONSTITUTION_OVERRIDE_REL)["kind"], "write")
        refreshed = dest.read_bytes()
        self.assertIn("Git与并行开发", refreshed.decode("utf-8"))
        section = ph_speckit.read_installed_speckit_section(repo)
        self.assertEqual(
            section["files"][ph_speckit.CONSTITUTION_OVERRIDE_REL], ph_init.sha256_file(dest)
        )
        # A rerun without further changes skips, and a standalone constitution
        # refresh keeps the baseline in sync.
        again = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertFalse(again["blocked"], again["items"])
        self.assertEqual(self.item(again, ph_speckit.CONSTITUTION_OVERRIDE_REL)["kind"], "skip")
        payload = ph_speckit.cmd_constitution(repo, apply=True, cache=None)
        self.assertFalse(payload["blocked"])
        section = ph_speckit.read_installed_speckit_section(repo)
        self.assertEqual(
            section["files"][ph_speckit.CONSTITUTION_OVERRIDE_REL], ph_init.sha256_file(dest)
        )

    def test_manifest_candidate_keeps_the_recorded_baselines(self):
        # build_candidate and the load_repo_manifest candidate check must keep
        # the disk manifest's per-file baselines (dropping them would turn
        # every future upgrade into a conflict), while a manifest without
        # baselines stays without them.
        data = {
            "template_version": "1.1.13",
            "skills": {},
            "speckit": {"files": {".specify/templates/plan-template.md": "a" * 64}},
        }
        cand = ph_merge_update.build_candidate(data, "1.1.14", ("ph-init",))
        self.assertEqual(cand["speckit"]["files"], {".specify/templates/plan-template.md": "a" * 64})
        self.assertEqual(cand["speckit"]["commit"], self.contract["commit"])
        plain = ph_merge_update.build_candidate(
            {"template_version": "1.1.13", "skills": {}, "speckit": {}}, "1.1.14", ("ph-init",)
        )
        self.assertNotIn("files", plain["speckit"])
        self.assertEqual(
            ph_init.speckit_section_with_baselines(data)["files"],
            {".specify/templates/plan-template.md": "a" * 64},
        )
        self.assertNotIn("files", ph_init.speckit_section_with_baselines({"speckit": {}}))

    def test_install_prevalidates_the_manifest_write_target(self):
        # The speckit section is written into .agents/ph.json AFTER the item
        # writes, so an unsafe manifest must block the whole install up front
        # instead of failing with the tree half written.
        repo = self.repo("ph-speckit-manifest-link-")
        outside = self.temp_dir("ph-speckit-manifest-out-")
        (repo / ".agents").mkdir()
        (outside / "ph.json").write_text('{"speckit": {}}\n', encoding="utf-8")
        (repo / ".agents" / "ph.json").symlink_to(outside / "ph.json")
        payload = ph_speckit.cmd_install(repo, apply=True, cache=None)
        self.assertTrue(payload["blocked"], payload["items"])
        self.assertFalse(payload["apply"])
        by_path = {item["path"]: item for item in payload["items"]}
        self.assertEqual(by_path[".agents/ph.json"]["kind"], "conflict")
        # Nothing was written: no skills, no .specify tree.
        self.assertFalse((repo / ".agents" / "skills" / "ph-plan").exists())
        self.assertFalse((repo / ".specify").exists())


class ConstitutionOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = _speckit_seed.ensure_seed()
        cls.contract = ph_speckit.speckit_contract()

    def setUp(self):
        self._temps = []

    def temp_dir(self, prefix):
        path = Path(tempfile.mkdtemp(prefix=prefix))
        self._temps.append(path)
        return path

    def tearDown(self):
        if not self._temps:
            return
        TRASH_ROOT.mkdir(parents=True, exist_ok=True)
        dest = TRASH_ROOT / f"ph-speckit-const-{os.getpid()}-{self._temps[0].name}"
        dest.mkdir(parents=True, exist_ok=True)
        for i, temp in enumerate(self._temps):
            target = dest / f"{i:02d}"
            if temp.exists() and not target.exists():
                temp.rename(target)

    def test_override_links_resolve_at_the_materialized_depth(self):
        repo = self.temp_dir("ph-speckit-const-")
        # Material docs referenced by the governance zone.
        governance = repo / "docs" / "约束规范" / "工程规范"
        governance.mkdir(parents=True)
        (governance / "README.md").write_text(
            "| [Git与并行开发.md](./Git与并行开发.md) | 分支与并行开发约束 |\n", encoding="utf-8"
        )
        (governance / "Git与并行开发.md").write_text(
            "# Git与并行开发\n正文：分支规则。\n", encoding="utf-8"
        )
        data = ph_speckit.render_constitution_override(repo, self.seed, self.contract)
        dest = repo / ph_speckit.CONSTITUTION_OVERRIDE_REL
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        # The override renders for the materialized constitution at
        # .specify/memory/constitution.md (two levels below the root), so the
        # links must resolve from that depth - verified against the exact
        # materialized path, not the template's own location.
        materialized = repo / ".specify" / "memory" / "constitution.md"
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_bytes(data)
        text = materialized.read_text(encoding="utf-8")
        self.assertIn("## PH 管理区：本仓库约束规范导航", text)
        link_line = next(
            line for line in text.splitlines() if "Git与并行开发.md" in line and "](../../docs/" in line
        )
        target = (materialized.parent / link_line.split("](", 1)[1].split(")", 1)[0]).resolve()
        self.assertTrue(target.is_file(), f"broken link from the materialized depth: {link_line}")
        self.assertEqual(
            target, (repo / "docs" / "约束规范" / "工程规范" / "Git与并行开发.md").resolve()
        )
        # Positioning comes from the directory README index.
        self.assertIn("分支与并行开发约束", link_line)
        # The upstream skeleton survives verbatim ahead of the PH zone.
        skeleton = (self.seed / ".specify" / "templates" / "constitution-template.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(skeleton.rstrip("\n")))

    def test_unindexable_document_is_marked_pending_confirmation(self):
        repo = self.temp_dir("ph-speckit-const-unknown-")
        governance = repo / "docs" / "约束规范" / "后端规范"
        governance.mkdir(parents=True)
        (governance / "无名约束.md").write_text("# 无名约束\n没有任何索引描述。\n", encoding="utf-8")
        data = ph_speckit.render_constitution_override(repo, self.seed, self.contract)
        text = data.decode("utf-8")
        self.assertIn("无名约束", text)
        self.assertIn("待确认", text)
        self.assertIn("未能从目录索引或正文识别", text)

    def test_template_underscore_files_are_excluded(self):
        repo = self.temp_dir("ph-speckit-const-tpl-")
        governance = repo / "docs" / "约束规范" / "工程规范"
        governance.mkdir(parents=True)
        (governance / "_模板.md").write_text("# 模板\n", encoding="utf-8")
        data = ph_speckit.render_constitution_override(repo, self.seed, self.contract)
        self.assertNotIn("_模板.md", data.decode("utf-8"))


class WorkflowExclusionTests(unittest.TestCase):
    def test_workflow_engine_assets_are_not_installed(self):
        seed = _speckit_seed.ensure_seed()
        self.assertFalse((seed / ".specify" / "workflows").exists())
        # The skill files must not reference the workflow engine.
        for skill in (seed / ".agents" / "skills").glob("ph-*/SKILL.md"):
            text = skill.read_text(encoding="utf-8")
            self.assertNotIn(".specify/workflows", text, skill)

    def test_verify_flags_installed_workflow_assets(self):
        with tempfile.TemporaryDirectory(prefix="ph-speckit-wf-") as tmp:
            repo = Path(tmp)
            (repo / ".specify" / "workflows").mkdir(parents=True)
            (repo / ".specify" / "workflows" / "speckit").mkdir()
            (repo / ".specify" / "workflows" / "speckit" / "workflow.yml").write_text(
                "schema_version: '1.0'\n", encoding="utf-8"
            )
            result = ph_speckit.cmd_verify(repo)
            self.assertFalse(result["ok"])
            self.assertTrue(
                any("must not be installed" in p for p in result["problems"]), result["problems"]
            )


if __name__ == "__main__":
    unittest.main()
