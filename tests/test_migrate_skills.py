#!/usr/bin/env python3
"""Dedicated tests for the 1.2.3 skill-replacement migration (migrate-skills).

Covers the semantics the retired spec-kit test file used to own, now for the
self-developed skill contract: baseline identity recognition (current /
managed-old / blocked), whole-directory archival of the seven retired skills,
in-place replacement of the three same-name skills, third-party protection,
extra-file decision records, vendor mirror retirement and idempotent resume."""

from __future__ import annotations

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
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
SCAFFOLD = REPO_ROOT / "assets" / "scaffold"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

import ph_init  # noqa: E402
import ph_merge_update  # noqa: E402

# macOS has a system trash directory; never mkdir the root itself - test
# artifacts live in per-run subdirectories created on demand.
TRASH_ROOT = Path.home() / ".Trash" if sys.platform == "darwin" else Path.home() / "trash"
MANAGED = list(ph_merge_update.SPECKIT_MANAGED_SKILLS)
RETIRED = list(ph_merge_update.SDD_RETIRED_SKILLS)
REPLACED = list(ph_merge_update.SDD_REPLACED_SKILLS)
# The non-speckit skills a real 1.2.2 install already carries; migrate-skills
# never touches them (their replacement belongs to other migration items).
SHIPPED_122 = [
    "ph-merge-update", "ph-worktree-enter", "ph-worktree-exit",
    "ph-memory-ask", "ph-memory-learning", "ph-memory-archive", "ph-human",
]
# The 1.2.3-only names migrate-skills installs when absent.
NEW_NAMES = sorted(
    set(ph_init.REQUIRED_SKILLS) - set(MANAGED) - {"ph-init"} - set(SHIPPED_122)
)
ARCHIVE_REL = ".agents/project-harness/archive/legacy-backup"


def run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=60)


def copy_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src, dest, symlinks=False, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"),
    )


def old_skill_bytes(name: str) -> bytes:
    return (
        f"---\nname: {name}\ndescription: spec-kit generation skill\n---\n"
        f"# {name}\n\n1.1.14 至 1.2.2 的上游代技能正文。\n"
    ).encode("utf-8")


class MigrateSkillsTests(unittest.TestCase):
    def setUp(self):
        self._temps = []

    def tearDown(self):
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-migrate-skills-{stamp}-{os.getpid()}"
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
        for argv in (["git", "init"], ["git", "config", "user.email", "t@example.com"], ["git", "config", "user.name", "t"]):
            proc = run(argv, cwd=root)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return root

    def fixture_122(self, mode="portable"):
        """A 1.2.2-style install: ten speckit-era skills with recorded content
        baselines, the seven unchanged PH skills, and live .claude mirrors."""
        repo = self.git_repo("ph-mig-")
        agents = repo / ".agents" / "AGENTS.md"
        agents.parent.mkdir(parents=True, exist_ok=True)
        agents.write_text("# agents\nproject_fact: keep-me\n", encoding="utf-8")
        for name in MANAGED:
            skill = repo / ".agents" / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_bytes(old_skill_bytes(name))
            if name == "ph-plan":
                (skill / "evals").mkdir()
                (skill / "evals" / "evals.json").write_text('{"cases": []}\n', encoding="utf-8")
        for name in SHIPPED_122:
            copy_tree(SCAFFOLD / ".agents" / "skills" / name, repo / ".agents" / "skills" / name)
        baselines = {}
        for name in MANAGED:
            for path in sorted((repo / ".agents" / "skills" / name).rglob("*")):
                if path.is_file():
                    baselines[path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "template_version": "1.2.2",
            "adapter_mode": mode,
            "skills": {"required_names": MANAGED},
            "speckit": {"files": baselines},
        }
        (repo / ".agents" / "ph.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if mode == "portable":
            for name in MANAGED:
                copy_tree(repo / ".agents" / "skills" / name, repo / ".claude" / "skills" / name)
        else:
            for name in MANAGED:
                dest = repo / ".claude" / "skills" / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(f"../../.agents/skills/{name}")
        return repo

    def tree_snapshot(self, repo: Path) -> dict:
        out: dict[str, str] = {}
        for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".git"}]
            for name in list(dirnames):
                child = Path(dirpath) / name
                if child.is_symlink():
                    out[child.relative_to(repo).as_posix()] = f"link:{os.readlink(child)}"
                    dirnames.remove(name)
            for name in sorted(filenames):
                if name == ".DS_Store":
                    continue
                path = Path(dirpath) / name
                rel = path.relative_to(repo).as_posix()
                out[rel] = f"link:{os.readlink(path)}" if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()
        return out

    def retired_skills_dir(self, repo: Path) -> Path:
        root = repo / ARCHIVE_REL
        self.assertTrue(root.is_dir())
        matches = [c for c in root.iterdir() if c.name.endswith("-pre-update") and (c / "retired-skills").is_dir()]
        self.assertEqual(len(matches), 1, "exactly one migration archive directory expected")
        return matches[0] / "retired-skills"

    def items_by_target(self, payload: dict) -> dict:
        return {i["target"]: i for i in payload["items"]}

    def test_plan_is_read_only_and_reports_full_replacement(self):
        for mode in ("portable", "symlink"):
            with self.subTest(mode=mode):
                repo = self.fixture_122(mode)
                before = self.tree_snapshot(repo)
                manifest_bytes = (repo / ".agents" / "ph.json").read_bytes()
                plan = ph_merge_update.migrate_skills_payload(repo, False)
                self.assertFalse(plan["blocked"])
                self.assertEqual(plan["conflicts"], [])
                items = self.items_by_target(plan)
                for name in RETIRED:
                    self.assertEqual(items[f".agents/skills/{name}"]["action"], "retire")
                for name in REPLACED:
                    self.assertEqual(items[f".agents/skills/{name}"]["action"], "replace")
                    self.assertEqual(items[f".agents/skills/{name}"]["mode"], "managed-old")
                for name in NEW_NAMES:
                    self.assertEqual(items[f".agents/skills/{name}"]["action"], "install")
                self.assertIn(f".claude/skills/{RETIRED[0]}", items)
                self.assertEqual(items[f".claude/skills/{RETIRED[0]}"]["action"], "retire-mirror")
                self.assertTrue(items[f".claude/skills/{RETIRED[0]}"]["planned"])
                # plan mode must not write anything at all
                self.assertEqual(self.tree_snapshot(repo), before)
                self.assertEqual((repo / ".agents" / "ph.json").read_bytes(), manifest_bytes)
                self.assertFalse((repo / ARCHIVE_REL).exists())

    def test_apply_replaces_retires_and_is_idempotent(self):
        for mode in ("portable", "symlink"):
            with self.subTest(mode=mode):
                repo = self.fixture_122(mode)
                result = ph_merge_update.migrate_skills_payload(repo, True)
                self.assertFalse(result["blocked"])
                retired_dir = self.retired_skills_dir(repo)
                for name in RETIRED:
                    self.assertFalse((repo / ".agents" / "skills" / name).exists(), name)
                    kept = retired_dir / name / "SKILL.md"
                    self.assertEqual(kept.read_bytes(), old_skill_bytes(name), name)
                if mode == "portable":
                    for name in MANAGED:
                        self.assertFalse((repo / ".claude" / "skills" / name).exists(), name)
                        mirror = retired_dir / f"{name}.claude-mirror"
                        self.assertEqual(
                            (mirror / "SKILL.md").read_bytes(), old_skill_bytes(name), name
                        )
                else:
                    for name in MANAGED:
                        self.assertFalse((repo / ".claude" / "skills" / name).exists(), name)
                        record = retired_dir / f"{name}.claude-mirror"
                        self.assertEqual(
                            record.read_text(encoding="utf-8"),
                            f"retired skill symlink mirror: .claude/skills/{name} -> ../../.agents/skills/{name}\n",
                            name,
                        )
                for name in REPLACED:
                    live = repo / ".agents" / "skills" / name / "SKILL.md"
                    self.assertEqual(
                        live.read_bytes(),
                        (SCAFFOLD / ".agents" / "skills" / name / "SKILL.md").read_bytes(),
                        name,
                    )
                for name in NEW_NAMES:
                    for path in (SCAFFOLD / ".agents" / "skills" / name).rglob("*"):
                        if not path.is_file():
                            continue
                        live = repo / ".agents" / "skills" / name / path.relative_to(SCAFFOLD / ".agents" / "skills" / name)
                        self.assertEqual(live.read_bytes(), path.read_bytes(), str(live))
                for name in SHIPPED_122:
                    self.assertTrue((repo / ".agents" / "skills" / name / "SKILL.md").is_file(), name)
                self.assertTrue((repo / ".claude" / "skills" / "ph-require").exists() is False)
                # Idempotent resume: a second apply changes nothing on disk.
                after = self.tree_snapshot(repo)
                again = ph_merge_update.migrate_skills_payload(repo, True)
                self.assertFalse(again["blocked"])
                self.assertEqual(self.tree_snapshot(repo), after)
                items = self.items_by_target(again)
                for name in RETIRED:
                    self.assertEqual(items[f".agents/skills/{name}"]["action"], "already-retired")
                self.assertEqual(
                    items[f".agents/skills/{REPLACED[0]}"]["action"], "installed"
                )
                self.assertEqual(self.retired_skills_dir(repo), retired_dir)

    def test_user_modified_skill_blocks_and_stays_in_place(self):
        repo = self.fixture_122()
        (repo / ".agents" / "skills" / "ph-plan" / "SKILL.md").write_text(
            "---\nname: ph-plan\ndescription: user rewrite\n---\n# 用户改写\n", encoding="utf-8"
        )
        before = self.tree_snapshot(repo)
        plan = ph_merge_update.migrate_skills_payload(repo, False)
        self.assertTrue(plan["blocked"])
        self.assertTrue(any(".agents/skills/ph-plan" in c for c in plan["conflicts"]))
        # apply refuses before any write: no mirror, no tree change
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertTrue(any(".agents/skills/ph-plan" in c for c in result["conflicts"]))
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertFalse((repo / ARCHIVE_REL).exists())

    def test_missing_baselines_fail_closed(self):
        repo = self.fixture_122()
        data = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        data.pop("speckit")
        (repo / ".agents" / "ph.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        before = self.tree_snapshot(repo)
        plan = ph_merge_update.migrate_skills_payload(repo, False)
        self.assertTrue(plan["blocked"])
        self.assertTrue(any("no speckit.files content baselines" in c for c in plan["conflicts"]))
        self.assertEqual(self.tree_snapshot(repo), before)

    def test_third_party_new_name_is_never_touched(self):
        """Project content on a PH-reserved new name is unknown same-name
        content: the payload blocks (keeping the reserved-name conflict
        visible), and the directory is never installed over or archived."""

        repo = self.fixture_122()
        custom = repo / ".agents" / "skills" / "ph-require"
        custom.mkdir(parents=True)
        custom_bytes = "---\nname: ph-require\ndescription: project-local tool\n---\n# 项目自有\n".encode("utf-8")
        (custom / "SKILL.md").write_bytes(custom_bytes)
        before = self.tree_snapshot(repo)
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertTrue(any(".agents/skills/ph-require" in c for c in result["conflicts"]), result["conflicts"])
        self.assertEqual((custom / "SKILL.md").read_bytes(), custom_bytes)
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertFalse((repo / ARCHIVE_REL).exists())
        # The upgrade gate independently flags the reserved-name occupation.
        conflicts = ph_merge_update.release_skill_name_conflicts({"ph-require"}, "1.2.2", None)
        self.assertTrue(any("ph-require" in c and "1.2.3" in c for c in conflicts), conflicts)

    def test_extras_require_reviewed_decisions_and_get_recorded(self):
        repo = self.fixture_122()
        extra = repo / ".agents" / "skills" / "ph-plan" / "references"
        extra.mkdir()
        (extra / "custom-checklist.md").write_text("# 项目自定义检查清单\n", encoding="utf-8")
        plan = ph_merge_update.migrate_skills_payload(repo, False)
        self.assertTrue(plan["blocked"])
        self.assertIn("--extras-decisions", plan["conflicts"][0])
        self.assertIn("ph-plan", plan["conflicts"][0])
        self.assertIn("custom-checklist.md", plan["conflicts"][0])
        # a stale decisions file that covers an unrelated directory is rejected
        stale = self.temp_dir("ph-mig-decisions-") / "decisions.json"
        stale.write_text(json.dumps({"ph-converge": {"decision": "archive", "note": "x"}}), encoding="utf-8")
        plan = ph_merge_update.migrate_skills_payload(repo, False, str(stale))
        self.assertTrue(plan["blocked"])
        self.assertIn("covers directories without extra files", plan["conflicts"][0])
        # a decision without a review note is rejected
        noted = self.temp_dir("ph-mig-decisions-") / "decisions.json"
        noted.write_text(json.dumps({"ph-plan": {"decision": "archive"}}), encoding="utf-8")
        plan = ph_merge_update.migrate_skills_payload(repo, False, str(noted))
        self.assertTrue(plan["blocked"])
        self.assertIn("note", plan["conflicts"][0])
        # the reviewed decision archives the attachment together with the tree
        reviewed = self.temp_dir("ph-mig-decisions-") / "decisions.json"
        reviewed.write_text(json.dumps({
            "ph-plan": {"decision": "archive", "note": "审阅确认：项目自定义检查清单随目录归档保留"},
        }, ensure_ascii=False), encoding="utf-8")
        result = ph_merge_update.migrate_skills_payload(repo, True, str(reviewed))
        self.assertFalse(result["blocked"])
        retired_dir = self.retired_skills_dir(repo)
        self.assertEqual(
            (retired_dir / "ph-plan" / "references" / "custom-checklist.md").read_text(encoding="utf-8"),
            "# 项目自定义检查清单\n",
        )
        record = json.loads((retired_dir / "ph-plan.extras.json").read_text(encoding="utf-8"))
        self.assertEqual(record["format"], "ph.retired-skill-extras/1")
        self.assertEqual(record["skill"], "ph-plan")
        self.assertEqual(record["decision"], "archive")
        self.assertEqual(record["files"], ["references/custom-checklist.md"])
        self.assertTrue(record["note"].strip())

    def test_drifted_portable_mirror_blocks_and_stays(self):
        repo = self.fixture_122()
        drifted = repo / ".claude" / "skills" / "ph-analyze" / "SKILL.md"
        drifted.write_bytes(drifted.read_bytes() + "\n用户改动\n".encode("utf-8"))
        before = self.tree_snapshot(repo)
        plan = ph_merge_update.migrate_skills_payload(repo, False)
        self.assertTrue(plan["blocked"])
        self.assertTrue(any(".claude/skills/ph-analyze" in c for c in plan["conflicts"]))
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertTrue(any(".claude/skills/ph-analyze" in c for c in result["conflicts"]))
        self.assertEqual(self.tree_snapshot(repo), before)

    def test_archive_collision_blocks_the_colliding_name(self):
        """Simulate an interrupted earlier run that archived ph-analyze while
        the live tree was restored: the full pre-check detects the collision
        before any write, so the apply blocks with zero writes instead of
        retiring other skills first and failing mid-way."""

        repo = self.fixture_122()
        collision = repo / ARCHIVE_REL / "2099-01-01-pre-update" / "retired-skills" / "ph-analyze"
        collision.mkdir(parents=True)
        (collision / "SKILL.md").write_bytes(b"earlier archive\n")
        before = self.tree_snapshot(repo)
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertTrue(any("already exists" in c for c in result["conflicts"]), result["conflicts"])
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertTrue((repo / ".agents" / "skills" / "ph-analyze" / "SKILL.md").is_file())
        # No mirror, tree or archive entry beyond the pre-existing collision moved.
        self.assertTrue((repo / ".claude" / "skills" / "ph-analyze" / "SKILL.md").is_file())
        self.assertEqual((collision / "SKILL.md").read_bytes(), b"earlier archive\n")

    def test_extras_block_before_any_mirror_write(self):
        """Counter-example regression: a managed-old skill carrying
        unattributed extra files without a reviewed decision blocks the apply
        during the read-only pre-check, so not even the mirrors a conflict-free
        plan would archive are retired."""

        repo = self.fixture_122()
        extra = repo / ".agents" / "skills" / "ph-plan" / "references"
        extra.mkdir()
        (extra / "custom-checklist.md").write_text("# 项目自定义检查清单\n", encoding="utf-8")
        before = self.tree_snapshot(repo)
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertIn("--extras-decisions", result["conflicts"][0])
        self.assertIn("ph-plan", result["conflicts"][0])
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertTrue((repo / ".claude" / "skills" / "ph-analyze" / "SKILL.md").is_file())
        self.assertFalse((repo / ARCHIVE_REL).exists())
        self.assertFalse(self.staging_base(repo).exists())

    def test_current_skill_customized_release_file_blocks_instead_of_overwrite(self):
        """Counter-example regression: inside a proven-current skill, a
        present release-set file that differs from the release generation has
        no baseline proof - the apply must block and keep the user's bytes
        instead of silently overwriting them (missing files are still added,
        extras stay)."""

        repo = self.fixture_122()
        first = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(first["blocked"])
        target_file = repo / ".agents" / "skills" / "ph-clarify" / "SKILL.zh.md"
        self.assertTrue(target_file.is_file())
        user_bytes = target_file.read_bytes() + "\n项目定制补充\n".encode("utf-8")
        target_file.write_bytes(user_bytes)
        before = self.tree_snapshot(repo)
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertTrue(
            any("ph-clarify" in c and "SKILL.zh.md" in c for c in result["conflicts"]),
            result["conflicts"],
        )
        self.assertEqual(target_file.read_bytes(), user_bytes)
        self.assertEqual(self.tree_snapshot(repo), before)

    def test_retained_122_skills_with_old_text_pass_and_stay(self):
        """A real 1.2.2 project carries the seven retained basic skills with
        1.2.2 text, not the current release bytes: the skill-replacement item
        must neither block on them nor touch them (their refresh belongs to
        their own migration items), while the migration still completes for
        the truly-new names. A retained skill missing from the managed install
        is installed under the original rule."""

        self.assertEqual(sorted(SHIPPED_122), sorted(ph_merge_update.RETAINED_122_SKILLS))
        repo = self.fixture_122()
        old_retained = {}
        for name in SHIPPED_122:
            skill_md = repo / ".agents" / "skills" / name / "SKILL.md"
            old_retained[name] = (
                f"---\nname: {name}\ndescription: 1.2.2 retained basic skill\n---\n"
                f"# {name}\n\n1.2.2 保留基础技能旧正文。\n"
            ).encode("utf-8")
            skill_md.write_bytes(old_retained[name])
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(result["blocked"])
        items = self.items_by_target(result)
        for name in SHIPPED_122:
            self.assertNotIn(f".agents/skills/{name}", items)
            self.assertEqual((repo / ".agents" / "skills" / name / "SKILL.md").read_bytes(), old_retained[name])
        for name in NEW_NAMES:
            self.assertEqual(items[f".agents/skills/{name}"]["action"], "installed")
        # A retained basic skill missing from the managed install is installed
        # under the original rule, with the same destination pre-check.
        missing = repo / ".agents" / "skills" / "ph-merge-update"
        shutil.rmtree(missing)
        plan = ph_merge_update.migrate_skills_payload(repo, False)
        self.assertFalse(plan["blocked"])
        self.assertEqual(
            self.items_by_target(plan)[f".agents/skills/ph-merge-update"]["action"], "install"
        )
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(result["blocked"])
        self.assertEqual(
            (missing / "SKILL.md").read_bytes(),
            (SCAFFOLD / ".agents" / "skills" / "ph-merge-update" / "SKILL.md").read_bytes(),
        )

    def test_updates_symlink_blocks_apply_with_zero_writes(self):
        """Counter-example regression: a symlinked .agents/updates ancestor is
        refused during the read-only pre-check, so the apply writes nothing -
        the staging chain can never be written through."""

        repo = self.fixture_122()
        updates = repo / ".agents" / "updates"
        outside = self.temp_dir("ph-mig-outside-") / "updates-out"
        outside.mkdir()
        updates.symlink_to(outside)
        self.assertFalse((outside / ph_init.RELEASE_VERSION).exists())
        before = self.tree_snapshot(repo)
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertTrue(any("updates" in c and "symlink" in c for c in result["conflicts"]), result["conflicts"])
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertFalse((outside / ph_init.RELEASE_VERSION).exists(), "nothing may be created behind the link")
        self.assertFalse((repo / ".agents" / "skills" / "ph-require").exists())
        self.assertTrue((repo / ".claude" / "skills" / "ph-analyze" / "SKILL.md").is_file())

    def test_extras_record_conflict_blocks_with_zero_writes(self):
        """Counter-example regression: an existing extras record whose bytes
        differ from the reviewed decision is detected during the pre-check,
        so the apply blocks with zero writes instead of failing after other
        mirrors already moved."""

        repo = self.fixture_122()
        extra = repo / ".agents" / "skills" / "ph-plan" / "references"
        extra.mkdir()
        (extra / "custom-checklist.md").write_text("# 项目自定义检查清单\n", encoding="utf-8")
        reviewed = self.temp_dir("ph-mig-decisions-") / "decisions.json"
        reviewed.write_text(json.dumps({
            "ph-plan": {"decision": "archive", "note": "本次审阅结论"},
        }, ensure_ascii=False), encoding="utf-8")
        stale_record = repo / ARCHIVE_REL / "2099-01-01-pre-update" / "retired-skills" / "ph-plan.extras.json"
        stale_record.parent.mkdir(parents=True)
        stale_record.write_text(
            json.dumps({
                "format": "ph.retired-skill-extras/1", "skill": "ph-plan",
                "decision": "archive", "note": "历史审阅结论",
                "files": ["references/custom-checklist.md"],
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        before = self.tree_snapshot(repo)
        result = ph_merge_update.migrate_skills_payload(repo, True, str(reviewed))
        self.assertTrue(result["blocked"])
        self.assertTrue(any("extras record changed" in c for c in result["conflicts"]), result["conflicts"])
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertTrue((repo / ".claude" / "skills" / "ph-analyze" / "SKILL.md").is_file())
        self.assertEqual(stale_record.read_text(encoding="utf-8"), stale_record.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Fresh-install interruption recovery: installs stage into the managed
    # update state directory and move into place with one atomic rename, so
    # the half-installed state (mkdir done, SKILL.md missing) that a retry
    # could only misread as third-party content is never produced.
    # ------------------------------------------------------------------

    def staging_base(self, repo: Path) -> Path:
        return repo / ".agents" / "updates" / ph_init.RELEASE_VERSION / "sdd-skill-staging"

    def test_interrupted_install_recovers_from_staging_leftover(self):
        repo = self.fixture_122()
        target = "ph-require"
        self.assertIn(target, NEW_NAMES)
        staging = self.staging_base(repo)
        real_write = Path.write_bytes

        def crash_mid_staging(path, data):
            if (
                path.parent.parent == staging
                and path.parent.name.startswith(f"{target}.")
                and path.name == "SKILL.md"
            ):
                raise OSError("simulated crash between mkdir and SKILL.md")
            return real_write(path, data)

        with mock.patch.object(Path, "write_bytes", crash_mid_staging):
            with self.assertRaises(OSError):
                ph_merge_update.migrate_skills_payload(repo, True)
        # Atomicity: no half-installed canonical directory exists, only the
        # interrupted run's own uniquely named staging scratch.
        self.assertFalse((repo / ".agents" / "skills" / target).exists())
        leftovers = sorted(p.name for p in staging.iterdir() if p.name.startswith(f"{target}."))
        self.assertEqual(len(leftovers), 1)
        # The retry restages into a fresh unique directory from the release
        # scaffold and completes; the leftover stays in place as evidence.
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(result["blocked"])
        self.assertEqual(self.items_by_target(result)[f".agents/skills/{target}"]["action"], "installed")
        for path in (SCAFFOLD / ".agents" / "skills" / target).rglob("*"):
            if not path.is_file():
                continue
            live = repo / ".agents" / "skills" / target / path.relative_to(SCAFFOLD / ".agents" / "skills" / target)
            self.assertEqual(live.read_bytes(), path.read_bytes(), str(live))
        self.assertTrue((staging / leftovers[0]).is_dir())
        self.assertFalse((staging / leftovers[0] / "SKILL.md").exists())

    def test_interrupted_install_before_rename_recovers(self):
        repo = self.fixture_122()
        target = "ph-require"
        staging = self.staging_base(repo)
        real_rename = os.rename
        crashed = {"used": False}

        def crash_before_rename(src, dst, *args, **kwargs):
            if (
                not crashed["used"]
                and str(src).startswith(str(staging))
                and Path(dst).name == target
            ):
                crashed["used"] = True
                raise OSError("simulated crash right before the atomic rename")
            return real_rename(src, dst, *args, **kwargs)

        with mock.patch.object(ph_merge_update.os, "rename", crash_before_rename):
            with self.assertRaises(ph_init.PHError):
                ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse((repo / ".agents" / "skills" / target).exists())
        leftovers = sorted(p.name for p in staging.iterdir() if p.name.startswith(f"{target}."))
        self.assertEqual(len(leftovers), 1)
        self.assertEqual(
            (staging / leftovers[0] / "SKILL.md").read_bytes(),
            (SCAFFOLD / ".agents" / "skills" / target / "SKILL.md").read_bytes(),
        )
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(result["blocked"])
        self.assertEqual(self.items_by_target(result)[f".agents/skills/{target}"]["action"], "installed")
        # The complete leftover is never taken over or moved; the install used
        # a fresh staging directory.
        self.assertEqual(
            (staging / leftovers[0] / "SKILL.md").read_bytes(),
            (SCAFFOLD / ".agents" / "skills" / target / "SKILL.md").read_bytes(),
        )
        self.assertEqual(
            (repo / ".agents" / "skills" / target / "SKILL.md").read_bytes(),
            (SCAFFOLD / ".agents" / "skills" / target / "SKILL.md").read_bytes(),
        )

    def test_unknown_staging_content_is_preserved(self):
        """A staging base entry this tool did not create (a foreign file or
        directory under the managed staging root) is neither read, moved nor
        taken over: its presence must not block the install and its bytes
        must survive the whole migration untouched."""

        repo = self.fixture_122()
        staging = self.staging_base(repo)
        staging.mkdir(parents=True)
        foreign_dir = staging / "ph-require.someone-elses-scratch"
        foreign_dir.mkdir()
        foreign_note = foreign_dir / "note.txt"
        note_bytes = "他人暂存内容\n".encode("utf-8")
        foreign_note.write_bytes(note_bytes)
        stray = staging / "stray.txt"
        stray.write_bytes(b"stray\n")
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(result["blocked"])
        self.assertEqual(self.items_by_target(result)[".agents/skills/ph-require"]["action"], "installed")
        self.assertEqual(foreign_note.read_bytes(), note_bytes)
        self.assertTrue(foreign_dir.is_dir())
        self.assertEqual(stray.read_bytes(), b"stray\n")
        self.assertEqual(
            (repo / ".agents" / "skills" / "ph-require" / "SKILL.md").read_bytes(),
            (SCAFFOLD / ".agents" / "skills" / "ph-require" / "SKILL.md").read_bytes(),
        )

    def test_unproven_half_install_is_never_taken_over(self):
        """A half-installed directory this tool cannot prove it created (e.g.
        left by an older implementation or a foreign source) is unknown
        same-name content on a PH-reserved name: the payload blocks, and the
        directory is neither healed, archived, taken over, nor staged for."""

        repo = self.fixture_122()
        half = repo / ".agents" / "skills" / "ph-require"
        (half / "refs").mkdir(parents=True)
        fragment = "# 半成品片段\n".encode("utf-8")
        (half / "refs" / "notes.md").write_bytes(fragment)
        before = self.tree_snapshot(repo)
        result = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertTrue(result["blocked"])
        self.assertTrue(any(".agents/skills/ph-require" in c for c in result["conflicts"]), result["conflicts"])
        self.assertEqual((half / "refs" / "notes.md").read_bytes(), fragment)
        self.assertFalse((half / "SKILL.md").exists(), "the unknown half-install must not be healed")
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertFalse((repo / ARCHIVE_REL).exists())
        self.assertFalse(self.staging_base(repo).exists())

    def test_post_final_rerun_keeps_current_mirrors_and_writes_nothing(self):
        """After the target state is reached, finalize's adapter sync
        re-creates the .claude mirrors of every installed skill. A repeated
        migrate-skills must treat those current-generation mirrors as live
        adapters (not as retirement leftovers) and write nothing at all."""

        repo = self.fixture_122()
        first = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(first["blocked"])
        # Simulate finalize: the target manifest leaves the baselines behind
        # and the portable sync re-creates every canonical skill's mirror.
        data = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        candidate = ph_merge_update.build_candidate(data, ph_init.RELEASE_VERSION, ph_init.REQUIRED_SKILLS)
        (repo / ".agents" / "ph.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for child in sorted((repo / ".agents" / "skills").iterdir()):
            copy_tree(child, repo / ".claude" / "skills" / child.name)
        before = self.tree_snapshot(repo)
        plan = ph_merge_update.migrate_skills_payload(repo, False)
        self.assertFalse(plan["blocked"])
        self.assertEqual([i for i in plan["items"] if "mirror" in i["action"]], [])
        self.assertEqual(self.tree_snapshot(repo), before)
        again = ph_merge_update.migrate_skills_payload(repo, True)
        self.assertFalse(again["blocked"])
        self.assertEqual([i for i in again["items"] if "mirror" in i["action"]], [])
        self.assertEqual(self.tree_snapshot(repo), before)
        replaced_mirrors = [f".claude/skills/{name}" for name in REPLACED]
        self.assertTrue(all(repo / rel for rel in replaced_mirrors), "current mirrors must stay live")

    def test_cli_apply_gating_and_post_final_zero_write(self):
        """The CLI refuses --apply for read-only actions and accepts it for
        migrate-skills, whose apply stays zero-write at the target state."""

        repo = self.fixture_122()
        self.assertFalse(ph_merge_update.migrate_skills_payload(repo, True)["blocked"])
        data = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        candidate = ph_merge_update.build_candidate(data, ph_init.RELEASE_VERSION, ph_init.REQUIRED_SKILLS)
        (repo / ".agents" / "ph.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for child in sorted((repo / ".agents" / "skills").iterdir()):
            copy_tree(child, repo / ".claude" / "skills" / child.name)
        before = self.tree_snapshot(repo)
        cli = [sys.executable, str(SCRIPTS / "ph_merge_update.py")]
        refused = run([*cli, "verify", "--repo", str(repo), "--apply"])
        self.assertEqual(refused.returncode, 2)
        self.assertIn("do not pass --apply", refused.stderr)
        accepted = run([*cli, "migrate-skills", "--repo", str(repo), "--apply"])
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        payload = json.loads(accepted.stdout)
        self.assertTrue(payload["apply"])
        self.assertFalse(payload["blocked"])
        self.assertEqual(self.tree_snapshot(repo), before)


if __name__ == "__main__":
    unittest.main()
