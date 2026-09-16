#!/usr/bin/env python3
"""Fixture tests for ph_merge_update inspect/verify/finalize."""

from __future__ import annotations

import hashlib
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
SCAFFOLD = REPO_ROOT / "assets" / "scaffold"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ph_init  # noqa: E402
import ph_merge_update  # noqa: E402
import ph_release  # noqa: E402

TRASH_ROOT = Path.home() / "trash"
FIXED_SOURCE = ph_merge_update.FIXED_SOURCE
COMMIT = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CURRENT, TARGET_SKILLS_TUPLE = ph_merge_update.release_contract()
TARGET_SKILLS = list(TARGET_SKILLS_TUPLE)
BASE_SKILLS = list(ph_merge_update.BASE_SKILLS)
OLD_ALIASES = list(ph_merge_update.OLD_ALIASES)
NEW_INTENT = list(ph_merge_update.NEW_INTENT)
CHAIN_110 = [
    "intent-skill-names",
    "intent-lifecycle",
    "online-source",
    "merge-update",
    "schema-contract",
    "project-content",
    "intent-no-completed",
    "intent-legacy-inprogress",
    "init-docs-workflow",
    "docs-guidance",
    "docs-project-preserve",
    "adopt-plan-init",
    "adopt-existing-content",
    "init-report-coverage",
    "init-unified-entry",
    "plain-user-questions",
    "prepare-star-fork",
    "single-ph-version",
    "worktree-auto-branch",
    "tool-neutral-adapters",
    "repository-rename",
    "docs-sync-skill",
    "current-branch-defaults",
    "adopt-mode-docs",
    "question-execution-contract",
    "explicit-invocation-rules",
    "intent-verify-skill",
]
CHAIN_100 = ["intent-domain", *CHAIN_110]
CHAIN_111 = CHAIN_110[6:]  # everything after the 1.1.0 -> 1.1.1 hop
CHAIN_117 = ["single-ph-version", "worktree-auto-branch", "tool-neutral-adapters", "repository-rename", "docs-sync-skill", "current-branch-defaults", "adopt-mode-docs", "question-execution-contract", "explicit-invocation-rules", "intent-verify-skill"]
CHAIN_118 = ["worktree-auto-branch", "tool-neutral-adapters", "repository-rename", "docs-sync-skill", "current-branch-defaults", "adopt-mode-docs", "question-execution-contract", "explicit-invocation-rules", "intent-verify-skill"]
CHAIN_119 = ["docs-sync-skill", "current-branch-defaults", "adopt-mode-docs", "question-execution-contract", "explicit-invocation-rules", "intent-verify-skill"]
CHAIN_112 = [
    "init-docs-workflow",
    "docs-guidance",
    "docs-project-preserve",
]


def run(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=60)


def copy_tree(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src,
        dest,
        symlinks=False,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"),
    )


class MergeUpdateTests(unittest.TestCase):
    def setUp(self):
        self._temps = []
        self.receipt_patch = None

    def tearDown(self):
        if self.receipt_patch is not None:
            self.receipt_patch.stop()
        if not self._temps:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = TRASH_ROOT / f"ph-merge-update-{stamp}-{os.getpid()}"
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
            ["git", "config", "user.name", "ph-merge-test"],
        ):
            proc = run(argv, cwd=root)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return root

    def write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_skill(self, repo: Path, name: str) -> None:
        dest = repo / ".agents" / "skills" / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n# {name}\n", encoding="utf-8")

    def write_manifest(self, repo: Path, *, version="1.1.0", mode="portable", names=None, extra=None) -> dict:
        data = json.loads((SCAFFOLD / ".agents" / "ph.json").read_text(encoding="utf-8"))
        data.pop("schema_version", None)  # the scaffold template is the single-version format
        if ph_merge_update.semver_tuple(version) < (1, 1, 8):
            # Pre-1.1.8 manifests carried the legacy field: it equaled
            # template_version up to 1.1.1, then stayed pinned at 1.1.1.
            data["schema_version"] = (
                version if ph_merge_update.semver_tuple(version) < (1, 1, 2) else "1.1.1"
            )
        if ph_merge_update.semver_tuple(version) < (1, 1, 9):
            # Pre-1.1.9 manifests still declared the codex adapter that this
            # release retires (Codex/OpenCode read AGENTS.md and .agents/skills
            # natively now); the scaffold no longer carries it.
            data["adapters"]["codex_skills"] = {
                "mode": "mirror_tree" if mode == "portable" else "symlink",
                "path": ".codex/skills",
                "source": ".agents/skills",
                "include": "ph-*",
            }
        data["template_version"] = version
        data["adapter_mode"] = mode
        if mode == "symlink":
            data["adapters"]["root_agents"]["mode"] = "symlink"
            data["adapters"]["claude_entry"]["mode"] = "symlink"
            data["adapters"]["claude_skills"]["mode"] = "symlink"
        data["skills"]["required_names"] = list(names or NEW_INTENT and (BASE_SKILLS + NEW_INTENT))
        if extra:
            data.update(extra)
        self.write_json(repo / ".agents" / "ph.json", data)
        schema_src = SCAFFOLD / ".agents" / "ph.schema.json"
        (repo / ".agents" / "ph.schema.json").write_bytes(schema_src.read_bytes())
        return data

    def write_agents(self, repo: Path, text="# agents\nproject_fact: keep-me\n") -> None:
        path = repo / ".agents" / "AGENTS.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_intent_layout(self, repo: Path, *, pending=True, in_progress=False) -> None:
        _dirs, files = ph_merge_update.target_paths()
        for rel in files:
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = SCAFFOLD / rel
            if rel.startswith("docs/意图/待办/") and src.is_file():
                dest.write_bytes(src.read_bytes())
            elif not dest.exists():
                dest.write_bytes(src.read_bytes() if src.is_file() else f"# {rel}\n".encode("utf-8"))
        if in_progress:
            legacy = repo / "docs/意图/进行中/新特性"
            legacy.mkdir(parents=True, exist_ok=True)
            (legacy / "INT-keep.md").write_text("# INT-keep\nuser body\n", encoding="utf-8")
        if not pending:
            return

    def seed_target_skills(self, repo: Path) -> None:
        for name in TARGET_SKILLS:
            if name == "ph-init":
                copy_tree(REPO_ROOT, repo / ".agents" / "skills" / "ph-init")
            else:
                src = SCAFFOLD / ".agents" / "skills" / name
                if src.is_dir():
                    copy_tree(src, repo / ".agents" / "skills" / name)
                else:
                    self.write_skill(repo, name)

    def seed_legacy_names(self, repo: Path) -> None:
        for name in BASE_SKILLS + OLD_ALIASES:
            self.write_skill(repo, name)

    def seed_v100(self, repo: Path) -> None:
        for name in BASE_SKILLS:
            self.write_skill(repo, name)

    def seed_adapters(self, repo: Path, mode: str, names, codex: bool = True) -> None:
        """Materialize adapters; codex=True reproduces a pre-1.1.9 install."""
        canonical = repo / ".agents" / "AGENTS.md"
        if mode == "portable":
            (repo / "AGENTS.md").write_bytes(canonical.read_bytes())
            (repo / "CLAUDE.md").write_text("@.agents/AGENTS.md\n", encoding="utf-8")
            for name in names:
                src = repo / ".agents" / "skills" / name
                if src.is_dir():
                    copy_tree(src, repo / ".claude" / "skills" / name)
                    if codex:
                        copy_tree(src, repo / ".codex" / "skills" / name)
            return
        (repo / "AGENTS.md").symlink_to(".agents/AGENTS.md")
        (repo / "CLAUDE.md").symlink_to(".agents/AGENTS.md")
        for name in names:
            src = Path("../../.agents/skills") / name
            for vendor in (".claude", *((".codex",) if codex else ())):
                dest = repo / vendor / "skills" / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(src)

    def tree_snapshot(self, repo: Path) -> dict:
        """Repo-relative path -> content digest or link target, VCS noise aside."""
        out: dict[str, str] = {}
        for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".git"}]
            for name in list(dirnames):
                child = Path(dirpath) / name
                if child.is_symlink():
                    out[child.relative_to(repo).as_posix()] = f"link:{os.readlink(child)}"
                    dirnames.remove(name)  # record the link node, never descend
            for name in sorted(filenames):
                if name == ".DS_Store":
                    continue
                path = Path(dirpath) / name
                rel = path.relative_to(repo).as_posix()
                out[rel] = f"link:{os.readlink(path)}" if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()
        return out

    def archived_codex_dir(self, repo: Path) -> Path | None:
        root = repo / ".agents" / "archived"
        if not root.is_dir():
            return None
        for child in sorted(root.iterdir()):
            if child.name.endswith("-pre-update") and (child / "codex-skills").is_dir():
                return child / "codex-skills"
        return None

    def seed_gitignore(self, repo: Path) -> None:
        (repo / ".gitignore").write_text("/.worktrees/\n", encoding="utf-8")

    def update_dir(self, repo: Path, version=None) -> Path:
        return repo / ".agents" / "updates" / (version or CURRENT)

    def receipt(self, version=None):
        version = version or CURRENT
        return {"version": version, "tag": f"v{version}", "commit": COMMIT, "source": FIXED_SOURCE}

    def install_receipt(self, verified=True, can_finalize=True, receipt=None, reason="ok"):
        payload = {
            "verified": verified,
            "can_finalize": can_finalize,
            "reason": reason,
            "receipt": receipt if receipt is not None else (self.receipt() if verified else None),
        }
        self.receipt_patch = mock.patch.object(ph_merge_update, "source_status", return_value=payload)
        self.receipt_patch.start()
        return payload

    def write_state(self, repo: Path, *, from_version="1.1.0", to_version=None, items=None, status="in_progress", receipt=None):
        to_version = to_version or CURRENT
        receipt = receipt or self.receipt()
        ids = items or CHAIN_110
        data = {
            "from_version": from_version,
            "to_version": to_version,
            "source": {"repository": FIXED_SOURCE, "tag": receipt["tag"], "commit": receipt["commit"]},
            "status": status,
            "items": [{"id": i, "status": "applied", "evidence": f"ok:{i}"} for i in ids],
        }
        dest = self.update_dir(repo, to_version)
        dest.mkdir(parents=True, exist_ok=True)
        self.write_json(dest / "state.json", data)
        (dest / "report.md").write_text("# report\nkept project_fact\n", encoding="utf-8")
        return data

    def invoke(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ph_merge_update.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def load(self, stdout):
        return json.loads(stdout)

    def test_custom_pending_index_survives_finalize_and_completed_inspect(self):
        self.install_receipt()
        repo = self.fixture_110_current()
        self.write_state(repo)
        index = repo / "docs/意图/待办/新特性/README.md"
        custom = index.read_text(encoding="utf-8") + "\n[用户需求](INT-custom.md)\n"
        index.write_text(custom, encoding="utf-8")
        intent = index.parent / "INT-custom.md"
        intent.write_text("# 用户需求\n保留原文\n", encoding="utf-8")
        ph_merge_update.finalize_payload(repo, True)
        result = ph_merge_update.inspect_payload(repo)
        self.assertTrue(result["up_to_date"])
        self.assertFalse(result["can_finalize"])
        self.assertIsNone(result["suggested_state"])
        self.assertEqual(index.read_text(encoding="utf-8"), custom)
        self.assertEqual(intent.read_text(encoding="utf-8"), "# 用户需求\n保留原文\n")

    def test_docs_migration_from_112_preserves_project_content(self):
        self.install_receipt()
        repo = self.fixture_110_current()
        manifest_path = repo / ".agents/ph.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.update(template_version="1.1.2", schema_version="1.1.1")
        self.write_json(manifest_path, manifest)
        retained = {}
        for rel, text in (
            ("docs/项目Wiki/项目概述.md", "# 已核验 Wiki\nsubagent 产物与人工定制\n"),
            ("docs/约束规范/后端规范/后端规范.md", "# 后端规范\n已批准项目例外\n"),
        ):
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            retained[path] = path.read_bytes()
        inspected = ph_merge_update.inspect_payload(repo)
        ids = [item["id"] for item in inspected["suggested_state"]["items"]]
        self.assertEqual(ids, ["init-docs-workflow", "docs-guidance", "docs-project-preserve",
                               "adopt-plan-init", "adopt-existing-content", "init-report-coverage",
                               "init-unified-entry", "plain-user-questions",
                               "prepare-star-fork", "single-ph-version", "worktree-auto-branch",
                               "tool-neutral-adapters", "repository-rename", "docs-sync-skill",
                               "current-branch-defaults", "adopt-mode-docs",
                               "question-execution-contract", "explicit-invocation-rules",
                               "intent-verify-skill"])
        state = self.write_state(repo, from_version="1.1.2", items=ids)
        before_manifest = manifest_path.read_bytes()
        for status in ("pending", "blocked"):
            state["items"][1]["status"] = status
            self.write_json(self.update_dir(repo) / "state.json", state)
            with self.assertRaises(ph_init.PHError):
                ph_merge_update.finalize_payload(repo, True)
            self.assertEqual(manifest_path.read_bytes(), before_manifest)
            self.assertEqual({p: p.read_bytes() for p in retained}, retained)
        state["items"][1]["status"] = "applied"
        self.write_json(self.update_dir(repo) / "state.json", state)
        ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(ph_merge_update.inspect_payload(repo)["up_to_date"])
        ph_merge_update.finalize_payload(repo, True)
        self.assertEqual({p: p.read_bytes() for p in retained}, retained)

    def test_completed_inspect_rechecks_content(self):
        self.install_receipt()
        repo = self.fixture_110_current()
        self.write_state(repo)
        ph_merge_update.finalize_payload(repo, True)
        template = repo / "docs/意图/_模板.md"
        template.write_text("status_dir: 进行中/新特性\n", encoding="utf-8")
        with self.assertRaisesRegex(ph_init.PHError, "must default status_dir"):
            ph_merge_update.inspect_payload(repo)

    def fixture_110_current(self, mode="portable"):
        repo = self.git_repo(f"ph-merge-{mode}-")
        names = BASE_SKILLS + NEW_INTENT + ["ph-merge-update"]
        self.write_manifest(repo, mode=mode, names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.write_intent_layout(repo, in_progress=True)
        # Adapters mirror every live canonical skill: these fixtures model the
        # post-merge state where all target skills (ph-docs-sync included)
        # are installed with byte-identical copies.
        self.seed_adapters(repo, mode, TARGET_SKILLS)
        self.seed_gitignore(repo)
        return repo

    def fixture_at_version(self, from_version: str, mode="portable"):
        """A pre-1.1.8 install whose manifest still carries schema_version."""
        repo = self.git_repo(f"ph-merge-v{from_version}-{mode}-")
        names = BASE_SKILLS + NEW_INTENT + ["ph-merge-update"]
        self.write_manifest(
            repo,
            mode=mode,
            version=from_version,
            names=names,
            extra={"project_note": "keep-user-field"},
        )
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.write_intent_layout(repo, in_progress=True)
        self.seed_adapters(repo, mode, TARGET_SKILLS)
        self.seed_gitignore(repo)
        return repo

    def fixture_at_119(self, mode="portable"):
        """A 1.1.9 install: single version, three-adapter topology, ten skills."""
        repo = self.git_repo(f"ph-merge-v119-{mode}-")
        names = BASE_SKILLS + NEW_INTENT + ["ph-merge-update"]
        self.write_manifest(repo, mode=mode, version="1.1.9", names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.write_intent_layout(repo, in_progress=True)
        # 1.1.9 installs carry no codex adapters (tool-neutral topology).
        self.seed_adapters(repo, mode, TARGET_SKILLS, codex=False)
        self.seed_gitignore(repo)
        return repo

    def test_upgrade_from_111_and_117_drops_schema_version(self):
        self.install_receipt()
        for from_version, chain_ids in (("1.1.1", CHAIN_111), ("1.1.7", CHAIN_117)):
            with self.subTest(from_version=from_version):
                repo = self.fixture_at_version(from_version)
                manifest_path = repo / ".agents" / "ph.json"
                old_bytes = manifest_path.read_bytes()
                agents_bytes = (repo / ".agents" / "AGENTS.md").read_bytes()

                inspected = ph_merge_update.inspect_payload(repo)
                self.assertEqual(inspected["from"], from_version)
                self.assertEqual(inspected["to"], CURRENT)
                self.assertFalse(inspected["up_to_date"])
                self.assertEqual(
                    [i["id"] for i in inspected["suggested_state"]["items"]], chain_ids
                )
                self.assertEqual(manifest_path.read_bytes(), old_bytes, "inspect must stay read-only")

                state = self.write_state(repo, from_version=from_version, items=chain_ids)
                verified = ph_merge_update.verify_payload(repo)
                self.assertTrue(verified["ok"])
                self.assertEqual(verified["from"], from_version)
                self.assertEqual(manifest_path.read_bytes(), old_bytes, "verify must stay read-only")
                self.assertEqual((repo / ".agents" / "AGENTS.md").read_bytes(), agents_bytes)

                old = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(old["schema_version"], "1.1.1")
                self.assertIn("codex_skills", old["adapters"])
                cand = ph_merge_update.build_candidate(old, CURRENT, tuple(TARGET_SKILLS))
                self.assertNotIn("schema_version", cand)
                self.assertNotIn("codex_skills", cand["adapters"])
                self.assertEqual(cand["template_version"], CURRENT)
                self.assertEqual(cand["skills"]["required_names"], TARGET_SKILLS)
                self.assertEqual(cand["project_note"], "keep-user-field")
                self.assertEqual(cand["worktree"], old["worktree"])
                self.assertEqual(cand["memory"], old["memory"])
                ph_init.load_repo_manifest(repo, candidate=cand)

                # dry-run finalize writes nothing
                result = ph_merge_update.finalize_payload(repo, False)
                self.assertFalse(result["apply"])
                self.assertFalse(result["complete"])
                self.assertEqual(manifest_path.read_bytes(), old_bytes)

                # a pending migration item blocks apply and never falsely completes
                state["items"][-1]["status"] = "pending"
                self.write_json(self.update_dir(repo) / "state.json", state)
                with self.assertRaises(ph_init.PHError):
                    ph_merge_update.finalize_payload(repo, True)
                self.assertEqual(manifest_path.read_bytes(), old_bytes)
                self.assertEqual(
                    json.loads((self.update_dir(repo) / "state.json").read_text())["status"],
                    "in_progress",
                )

                state["items"][-1]["status"] = "applied"
                self.write_json(self.update_dir(repo) / "state.json", state)
                result = ph_merge_update.finalize_payload(repo, True)
                self.assertTrue(result["complete"])
                written = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertNotIn("schema_version", written)
                self.assertNotIn("codex_skills", written["adapters"])
                self.assertEqual(written["template_version"], CURRENT)
                self.assertEqual(written["project_note"], "keep-user-field")
                self.assertEqual(written["skills"]["required_names"], TARGET_SKILLS)
                self.assertEqual(written["worktree"], old["worktree"])
                self.assertEqual(written["memory"], old["memory"])
                self.assertIn("keep-me", (repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"))
                self.assertEqual(
                    json.loads((self.update_dir(repo) / "state.json").read_text())["status"],
                    "complete",
                )
                self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])

                # repeated finalize stays complete; the new manifest loads without a candidate
                self.assertTrue(ph_merge_update.finalize_payload(repo, True)["complete"])
                ph_init.load_repo_manifest(repo)
                self.assertTrue(ph_merge_update.inspect_payload(repo)["up_to_date"])

    def test_docs_sync_same_name_custom_skill_blocks_inspect(self):
        self.install_receipt()
        repo = self.fixture_at_119()
        custom = repo / ".agents/skills/ph-docs-sync/SKILL.md"
        custom_body = (
            "---\nname: ph-docs-sync\ndescription: team custom sync flow\n---\n"
            "# our own sync skill\n项目自建同步流程，升级不得覆盖。\n"
        )
        custom.write_text(custom_body, encoding="utf-8")
        before = self.tree_snapshot(repo)

        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.9")
        self.assertEqual(inspected["to"], CURRENT)
        self.assertEqual(inspected["profile"], "1.1.0-current-names")
        self.assertTrue(
            any("ph-docs-sync" in conflict for conflict in inspected["conflicts"]),
            inspected["conflicts"],
        )
        self.assertFalse(inspected["can_finalize"])
        # inspect stays read-only and the custom body survives byte-for-byte
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

    def test_docs_sync_blocked_item_keeps_custom_skill_and_version(self):
        self.install_receipt()
        repo = self.fixture_at_119()
        custom = repo / ".agents/skills/ph-docs-sync/SKILL.md"
        custom_body = (
            "---\nname: ph-docs-sync\ndescription: team custom sync flow\n---\n"
            "# our own sync skill\n项目自建同步流程，升级不得覆盖。\n"
        )
        custom.write_text(custom_body, encoding="utf-8")
        manifest_path = repo / ".agents/ph.json"
        before = manifest_path.read_bytes()

        inspected = ph_merge_update.inspect_payload(repo)
        state = inspected["suggested_state"]
        self.assertEqual([i["id"] for i in state["items"]], CHAIN_119)
        docs_sync = next(i for i in state["items"] if i["id"] == "docs-sync-skill")
        docs_sync["status"] = "blocked"
        docs_sync["evidence"] = "同名自定义 Skill，保留原件待用户决定"
        dest = self.update_dir(repo)
        dest.mkdir(parents=True, exist_ok=True)
        self.write_json(dest / "state.json", state)
        (dest / "report.md").write_text("# report\ndocs-sync-skill blocked\n", encoding="utf-8")

        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("docs-sync-skill", str(ctx.exception))
        with self.assertRaises(ph_init.PHError):
            ph_merge_update.finalize_payload(repo, False)
        with self.assertRaises(ph_init.PHError):
            ph_merge_update.finalize_payload(repo, True)
        # a blocked item never advances the version or rewrites the state
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(
            json.loads(manifest_path.read_text(encoding="utf-8"))["template_version"], "1.1.9"
        )
        self.assertEqual(json.loads((dest / "state.json").read_text())["status"], "in_progress")
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

        # Marking the blocked item applied while the custom skill stays in
        # place must not pass verify: the installed skill has to match the
        # release bytes during the 1.1.10 upgrade.
        for item in state["items"]:
            item["status"] = "applied"
            item["evidence"] = "fixture already contains the target skill defaults"
        docs_sync["status"] = "applied"
        docs_sync["evidence"] = "falsely claims the release skill was installed"
        self.write_json(dest / "state.json", state)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("does not match the release skill", str(ctx.exception))
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

    def test_upgrade_from_119_installs_docs_sync_and_preserves_docs(self):
        self.install_receipt()
        repo = self.fixture_at_119()
        wiki = repo / "docs/项目Wiki/项目概述.md"
        wiki.parent.mkdir(parents=True, exist_ok=True)
        wiki.write_text("# 项目概述\n项目事实：升级不得自动同步业务文档。\n", encoding="utf-8")
        wiki_bytes = wiki.read_bytes()
        governance = repo / "docs/约束规范/工程规范/文档治理.md"
        governance.parent.mkdir(parents=True, exist_ok=True)
        governance.write_text(
            "# 文档治理\n项目定制：同步修复前须抄送负责人。\n", encoding="utf-8"
        )
        governance_bytes = governance.read_bytes()

        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.9")
        self.assertEqual([i["id"] for i in inspected["suggested_state"]["items"]], CHAIN_119)
        self.write_state(repo, from_version="1.1.9", items=CHAIN_119)
        verified = ph_merge_update.verify_payload(repo)
        self.assertTrue(verified["ok"])

        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        self.assertEqual(result["from"], "1.1.9")
        written = json.loads((repo / ".agents/ph.json").read_text(encoding="utf-8"))
        self.assertEqual(written["template_version"], CURRENT)
        self.assertIn("ph-docs-sync", written["skills"]["required_names"])
        self.assertEqual(written["adapter_mode"], "portable")
        # the upgrade installs the skill and never syncs business documents
        skill = repo / ".agents/skills/ph-docs-sync"
        self.assertTrue((skill / "SKILL.md").is_file())
        self.assertEqual(
            (skill / "SKILL.md").read_bytes(),
            (SCAFFOLD / ".agents/skills/ph-docs-sync/SKILL.md").read_bytes(),
        )
        self.assertTrue((repo / ".claude/skills/ph-docs-sync/SKILL.md").is_file())
        self.assertEqual(wiki.read_bytes(), wiki_bytes)
        self.assertEqual(governance.read_bytes(), governance_bytes)
        # the upgraded repo's own installer discovers the new required skill
        installed = repo / ".agents/skills/ph-init/scripts/ph_init.py"
        proc = run([sys.executable, str(installed), "check", "--repo", str(repo)])
        self.assertIn("status=ok", proc.stdout, proc.stdout)
        self.assertIn(".agents/skills/ph-docs-sync/SKILL.md", proc.stdout)
        # repeated runs stay idempotent
        self.assertTrue(ph_merge_update.inspect_payload(repo)["up_to_date"])
        again = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(again["complete"])
        self.assertEqual(wiki.read_bytes(), wiki_bytes)

    def test_intent_verify_same_name_custom_skill_blocks_inspect(self):
        # ph-intent-verify arrives with 1.1.13: a live same-named directory on
        # a 1.1.9 project is project content and must block instead of being
        # overwritten (same contract as the 1.1.10 ph-docs-sync protection).
        self.install_receipt()
        repo = self.fixture_at_119()
        custom = repo / ".agents/skills/ph-intent-verify/SKILL.md"
        custom_body = (
            "---\nname: ph-intent-verify\ndescription: team custom acceptance flow\n---\n"
            "# our own verify skill\n项目自建验收流程，升级不得覆盖。\n"
        )
        custom.write_text(custom_body, encoding="utf-8")
        before = self.tree_snapshot(repo)

        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.9")
        self.assertEqual(inspected["to"], CURRENT)
        self.assertEqual(inspected["profile"], "1.1.0-current-names")
        self.assertTrue(
            any("ph-intent-verify" in conflict for conflict in inspected["conflicts"]),
            inspected["conflicts"],
        )
        self.assertFalse(inspected["can_finalize"])
        # inspect stays read-only and the custom body survives byte-for-byte
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

    def test_intent_verify_install_pinned_to_release_bytes(self):
        # Marking intent-verify-skill applied while a drifted same-name skill
        # stays in place must not pass verify: the installed skill has to
        # match the release bytes during the 1.1.13 upgrade.
        self.install_receipt()
        repo = self.fixture_at_119()
        custom = repo / ".agents/skills/ph-intent-verify/SKILL.md"
        custom_body = "---\nname: ph-intent-verify\ndescription: drift\n---\n# drifted verify skill\n"
        custom.write_text(custom_body, encoding="utf-8")
        manifest_path = repo / ".agents/ph.json"
        before = manifest_path.read_bytes()

        inspected = ph_merge_update.inspect_payload(repo)
        state = inspected["suggested_state"]
        self.assertEqual([i["id"] for i in state["items"]], CHAIN_119)
        for item in state["items"]:
            item["status"] = "applied"
            item["evidence"] = "fixture already contains the target skill defaults"
        dest = self.update_dir(repo)
        dest.mkdir(parents=True, exist_ok=True)
        self.write_json(dest / "state.json", state)
        (dest / "report.md").write_text("# report\nintent-verify-skill applied\n", encoding="utf-8")

        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("installed ph-intent-verify does not match the release skill", str(ctx.exception))
        # a failing verify never advances the version or rewrites the state
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(
            json.loads((dest / "state.json").read_text())["status"], "in_progress"
        )
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

        # Installing the genuine release skill unblocks verify and finalize;
        # afterwards project customization of the skill is free.
        custom.write_text(
            (SCAFFOLD / ".agents/skills/ph-intent-verify/SKILL.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        verified = ph_merge_update.verify_payload(repo)
        self.assertTrue(verified["ok"])
        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("ph-intent-verify", written["skills"]["required_names"])
        self.assertEqual(
            (repo / ".agents/skills/ph-intent-verify/SKILL.md").read_bytes(),
            (SCAFFOLD / ".agents/skills/ph-intent-verify/SKILL.md").read_bytes(),
        )
        installed_check = run([sys.executable,
                               str(repo / ".agents/skills/ph-init/scripts/ph_init.py"),
                               "check", "--repo", str(repo)])
        self.assertIn("status=ok", installed_check.stdout, installed_check.stdout)
        self.assertIn(".agents/skills/ph-intent-verify/SKILL.md", installed_check.stdout)

    def test_upgrade_from_118_worktree_and_tool_neutral(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8")
        manifest_path = repo / ".agents/ph.json"
        before = manifest_path.read_bytes()
        my_tool = repo / ".codex" / "skills" / "my-tool"
        my_tool.mkdir(parents=True, exist_ok=True)
        (my_tool / "SKILL.md").write_text("# my-tool\nuser-owned\n", encoding="utf-8")

        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.8")
        self.assertEqual(inspected["to"], CURRENT)
        self.assertEqual(
            [item["id"] for item in inspected["suggested_state"]["items"]],
            CHAIN_118,
        )
        self.assertEqual(manifest_path.read_bytes(), before)
        # Portable mirrors are byte-identical to the canonical skills here, so
        # inspect classifies every live codex adapter as retirable.
        self.assertEqual(
            sorted(i["name"] for i in inspected["codex_retirement"]["retirable"]),
            sorted(TARGET_SKILLS),
        )
        self.assertEqual(inspected["codex_retirement"]["blocked"], [])

        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        verified = ph_merge_update.verify_payload(repo)
        self.assertTrue(verified["ok"])
        self.assertEqual(
            sorted(verified["codex_retirement"]["retirable"]),
            sorted(TARGET_SKILLS),
        )
        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        archived = {i["name"] for i in result["retired_codex"]}
        self.assertEqual(archived, set(TARGET_SKILLS))
        self.assertTrue(all(i["result"] == "archived" for i in result["retired_codex"]))
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(written["template_version"], CURRENT)
        self.assertNotIn("schema_version", written)
        self.assertNotIn("codex_skills", written["adapters"])
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        # pre-upgrade mirrors stay recoverable inside the project archive
        archived_dir = self.archived_codex_dir(repo)
        self.assertIsNotNone(archived_dir)
        for name in TARGET_SKILLS:
            self.assertTrue((archived_dir / name / "SKILL.md").is_file(), name)
        self.assertFalse((archived_dir / "my-tool").exists())
        # non-ph content under .codex/skills is never touched
        self.assertEqual((my_tool / "SKILL.md").read_text(encoding="utf-8"), "# my-tool\nuser-owned\n")

    def test_codex_symlink_leftovers_archive_and_finalize_is_idempotent(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8", mode="symlink")
        my_tool = repo / ".codex" / "skills" / "my-tool"
        my_tool.mkdir(parents=True, exist_ok=True)
        (my_tool / "SKILL.md").write_text("# my-tool\n", encoding="utf-8")
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)

        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        self.assertTrue((repo / "AGENTS.md").is_symlink())
        written = json.loads((repo / ".agents/ph.json").read_text(encoding="utf-8"))
        self.assertNotIn("codex_skills", written["adapters"])
        # Live symlinks cannot be moved into .agents (it must stay link-free):
        # each one is unlinked and a regular record file keeps the link target.
        archived_dir = self.archived_codex_dir(repo)
        self.assertIsNotNone(archived_dir)
        for name in TARGET_SKILLS:
            record = archived_dir / name
            self.assertTrue(record.is_file(), name)
            self.assertEqual(
                record.read_text(encoding="utf-8"),
                f"retired codex symlink: .codex/skills/{name} -> ../../.agents/skills/{name}\n",
            )
            self.assertFalse((repo / ".codex" / "skills" / name).exists())
        self.assertTrue((my_tool / "SKILL.md").is_file())

        # Repeated inspect/verify/finalize keep the state complete and the tree stable.
        after_upgrade = self.tree_snapshot(repo)
        self.assertTrue(ph_merge_update.inspect_payload(repo)["up_to_date"])
        self.assertTrue(ph_merge_update.verify_payload(repo)["ok"])
        again = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(again["complete"])
        self.assertEqual(again["retired_codex"], [])
        self.assertEqual(self.tree_snapshot(repo), after_upgrade)
        self.assertEqual(
            sorted(p.name for p in (repo / ".agents" / "archived").iterdir()),
            [archived_dir.parent.name],
            "a repeated finalize must not create a second archive directory",
        )

    def test_codex_portable_drift_blocks_and_stays_in_place(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8")  # no commit: no pre-upgrade git snapshot exists
        drifted = repo / ".codex" / "skills" / "ph-intent-new" / "SKILL.md"
        drifted.write_bytes(drifted.read_bytes() + b"\nuser customization\n")
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        before = self.tree_snapshot(repo)

        inspected = ph_merge_update.inspect_payload(repo)
        blocked = {i["name"] for i in inspected["codex_retirement"]["blocked"]}
        self.assertIn("ph-intent-new", blocked)
        self.assertFalse(inspected["can_finalize"])
        self.assertTrue(any(".codex/skills/ph-intent-new" in c for c in inspected["conflicts"]))

        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("blocked codex skill adapters", str(ctx.exception))
        self.assertIn("ph-intent-new", str(ctx.exception))
        # dry-run and apply both stop before anything is moved
        with self.assertRaises(ph_init.PHError):
            ph_merge_update.finalize_payload(repo, False)
        with self.assertRaises(ph_init.PHError):
            ph_merge_update.finalize_payload(repo, True)
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertIsNone(self.archived_codex_dir(repo))
        self.assertEqual(
            json.loads((self.update_dir(repo) / "state.json").read_text())["status"],
            "in_progress",
        )

    def test_codex_portable_git_snapshot_retires_stale_mirror(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8")
        # Commit the pre-upgrade state: the only acceptable portable-mirror
        # evidence when the semantic merge has already changed the canonical.
        for argv in (["git", "add", "-A"], ["git", "commit", "-m", "pre-upgrade 1.1.8"]):
            proc = run(argv, cwd=repo)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        stale_bytes = (repo / ".codex" / "skills" / "ph-intent-new" / "SKILL.md").read_bytes()
        # Semantic merge updates the canonical skill; the codex mirror goes stale.
        (repo / ".agents" / "skills" / "ph-intent-new" / "SKILL.md").write_text(
            "---\nname: ph-intent-new\ndescription: merged 1.1.9 body\n---\n# merged\n",
            encoding="utf-8",
        )
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)

        verdict, reason = ph_merge_update.classify_codex_leftover(repo, "ph-intent-new")
        self.assertEqual(verdict, "retire")
        self.assertIn("git HEAD", reason)
        verified = ph_merge_update.verify_payload(repo)
        self.assertIn("ph-intent-new", verified["codex_retirement"]["retirable"])
        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        archived = self.archived_codex_dir(repo) / "ph-intent-new" / "SKILL.md"
        self.assertEqual(archived.read_bytes(), stale_bytes)
        # the merged canonical is untouched by the archiving
        self.assertIn(
            "merged 1.1.9 body",
            (repo / ".agents" / "skills" / "ph-intent-new" / "SKILL.md").read_text(encoding="utf-8"),
        )

    def test_codex_abnormal_shapes_block(self):
        self.install_receipt()
        cases = {}
        symlink_repo = self.fixture_at_version("1.1.8", mode="symlink")
        wrong = symlink_repo / ".codex" / "skills" / "ph-intent-new"
        wrong.unlink()
        wrong.symlink_to("../../.claude/skills/ph-intent-new")
        cases["wrong symlink target"] = symlink_repo

        file_repo = self.fixture_at_version("1.1.8")
        entry = file_repo / ".codex" / "skills" / "ph-intent-new"
        shutil.rmtree(entry)
        entry.write_text("# not a mirror\n", encoding="utf-8")
        cases["regular file entry"] = file_repo

        root_repo = self.fixture_at_version("1.1.8")
        shutil.rmtree(root_repo / ".codex" / "skills")
        (root_repo / ".codex" / "skills").symlink_to(root_repo / ".claude" / "skills")
        cases["symlinked skills root"] = root_repo

        for label, repo in cases.items():
            with self.subTest(case=label):
                self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
                before = self.tree_snapshot(repo)
                with self.assertRaises(ph_init.PHError) as ctx:
                    ph_merge_update.verify_payload(repo)
                self.assertIn(".codex", str(ctx.exception))
                inspected = ph_merge_update.inspect_payload(repo)
                self.assertFalse(inspected["can_finalize"])
                self.assertTrue(inspected["conflicts"])
                self.assertEqual(self.tree_snapshot(repo), before)
                self.assertIsNone(self.archived_codex_dir(repo))

    def test_codex_archive_collision_blocks_and_keeps_both(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8")
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        # A previous interrupted run archived everything, then the entry reappeared.
        ph_merge_update.retire_codex_adapters(repo)
        archived = self.archived_codex_dir(repo) / "ph-intent-new"
        resurrected = repo / ".codex" / "skills" / "ph-intent-new"
        shutil.copytree(archived, resurrected)
        before = self.tree_snapshot(repo)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.retire_codex_adapters(repo)
        self.assertIn("collision", str(ctx.exception))
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertTrue(archived.is_dir())
        self.assertTrue(resurrected.is_dir())

    def test_codex_resume_after_interrupted_retirement(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8")
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        # Simulate a crash after the retirement pass but before sync/write.
        first_pass = ph_merge_update.retire_codex_adapters(repo)
        self.assertEqual({i["name"] for i in first_pass}, set(TARGET_SKILLS))
        archived_dir = self.archived_codex_dir(repo)

        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        self.assertEqual(result["retired_codex"], [])
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        # the resumed run reuses the existing archive directory
        self.assertEqual(self.archived_codex_dir(repo), archived_dir)
        written = json.loads((repo / ".agents/ph.json").read_text(encoding="utf-8"))
        self.assertNotIn("codex_skills", written["adapters"])

    def test_codex_symlink_unlink_interruption_resumes_and_audits(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8", mode="symlink")
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        skills_dir = repo / ".codex" / "skills"

        # Interruption right between persisting the archive record and
        # unlinking the live symlink: the OSError must surface as PHError and
        # leave both the live link and the deterministic record in place.
        real_unlink = Path.unlink

        def interrupted_unlink(self, *args, **kwargs):
            if self.parent == skills_dir and self.name.startswith("ph-"):
                raise OSError("simulated interruption after writing the record")
            return real_unlink(self, *args, **kwargs)

        with mock.patch.object(Path, "unlink", interrupted_unlink):
            with self.assertRaises(ph_init.PHError) as ctx:
                ph_merge_update.finalize_payload(repo, True)
        self.assertIn("cannot unlink", str(ctx.exception))
        archived_dir = self.archived_codex_dir(repo)
        self.assertIsNotNone(archived_dir)
        stuck = next(p.name for p in archived_dir.iterdir())
        live = repo / ".codex" / "skills" / stuck
        record = archived_dir / stuck
        self.assertTrue(live.is_symlink())
        self.assertEqual(
            record.read_text(encoding="utf-8"),
            f"retired codex symlink: .codex/skills/{stuck} -> ../../.agents/skills/{stuck}\n",
        )
        state = json.loads((self.update_dir(repo) / "state.json").read_text())
        self.assertEqual(state["status"], "in_progress")
        self.assertNotIn("retired_codex", state)

        # Only the byte-identical record may be reused; anything else collides.
        record.write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.retire_codex_adapters(repo)
        self.assertIn("collision", str(ctx.exception))
        self.assertTrue(live.is_symlink())
        record.write_text(
            f"retired codex symlink: .codex/skills/{stuck} -> ../../.agents/skills/{stuck}\n",
            encoding="utf-8",
        )

        # The resumed finalize reuses the exact record, unlinks the live
        # entry, and records every archived adapter in state for audits.
        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        self.assertFalse(live.exists() or live.is_symlink())
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        by_name = {i["name"]: i for i in result["retired_codex"]}
        self.assertEqual(by_name[stuck]["result"], "archived")
        self.assertEqual(by_name[stuck]["kind"], "symlink-record")
        state = json.loads((self.update_dir(repo) / "state.json").read_text())
        self.assertEqual(state["status"], "complete")
        audited = {i["name"]: i for i in state["retired_codex"]}
        self.assertEqual(set(audited), set(TARGET_SKILLS))
        for name, item in audited.items():
            self.assertEqual(
                item["dest"],
                f".agents/archived/{archived_dir.parent.name}/codex-skills/{name}",
            )
            self.assertEqual(item["kind"], "symlink-record")
            self.assertIn("managed relative symlink", item["reason"])

        # A repeated finalize stays idempotent: nothing new is retired and the
        # completed state, including the audit records, is unchanged.
        state_path = self.update_dir(repo) / "state.json"
        before = state_path.read_bytes()
        again = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(again["complete"])
        self.assertEqual(again["retired_codex"], [])
        self.assertEqual(state_path.read_bytes(), before)

    def test_completed_repo_with_live_codex_leftovers_is_blocked(self):
        repo = self.git_repo("ph-merge-stale-codex-")
        names = TARGET_SKILLS
        self.write_manifest(repo, version=CURRENT, names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.write_intent_layout(repo)
        # A repo already at CURRENT must not keep live codex adapters around.
        self.seed_adapters(repo, "portable", names, codex=True)
        self.seed_gitignore(repo)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.inspect_payload(repo)
        self.assertIn("still live", str(ctx.exception))
        with self.assertRaises(ph_init.PHError):
            ph_merge_update.finalize_payload(repo, True)
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), sorted(TARGET_SKILLS))
        self.assertIsNone(self.archived_codex_dir(repo))

    def test_candidate_whitelist_only_allows_schema_and_codex_removal(self):
        repo = self.fixture_at_version("1.1.7")
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_init.load_repo_manifest(repo)
        self.assertIn("schema_version", str(ctx.exception))

        data = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        base = ph_merge_update.build_candidate(data, CURRENT, tuple(TARGET_SKILLS))
        ph_init.load_repo_manifest(repo, candidate=base)  # these deletions are allowed
        self.assertNotIn("codex_skills", base["adapters"])

        def rejected(mutate, label):
            bad = ph_merge_update.build_candidate(data, CURRENT, tuple(TARGET_SKILLS))
            mutate(bad)
            with self.assertRaises(ph_init.PHError, msg=label):
                ph_init.load_repo_manifest(repo, candidate=bad)

        rejected(lambda c: c.update(schema_version="1.1.1"), "candidate kept the removed field")
        rejected(lambda c: c.update(adapter_mode="symlink"), "candidate edited adapter_mode")
        rejected(lambda c: c.pop("worktree"), "candidate deleted another field")
        rejected(lambda c: c.update(memory=dict(c["memory"], root=".elsewhere")), "candidate edited memory")
        rejected(lambda c: c.update(extra_note="new-field"), "candidate added a field")
        rejected(
            lambda c: c["adapters"].update(codex_skills=dict(c["adapters"]["claude_skills"])),
            "candidate kept codex_skills with edited contents",
        )
        rejected(
            lambda c: c["adapters"].update(opencode_skills=dict(c["adapters"]["claude_skills"])),
            "candidate added an unknown adapter",
        )


    def test_inspect_dev_tree_unverified_source(self):
        repo = self.git_repo("ph-merge-inspect-")
        self.write_manifest(repo, names=BASE_SKILLS + NEW_INTENT)
        self.write_agents(repo)
        for name in BASE_SKILLS + NEW_INTENT:
            self.write_skill(repo, name)
        code, out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["from"], "1.1.0")
        self.assertEqual(data["to"], CURRENT)
        self.assertEqual(data["profile"], "1.1.0-current-names")
        self.assertEqual([h["from"] for h in data["chain"]], [h["from"] for h in ph_merge_update.chain_between("1.1.0", CURRENT)])
        self.assertFalse(data["source"]["verified"])
        self.assertFalse(data["can_finalize"])
        self.assertIn("cannot finalize", data["source"]["reason"])
        self.assertEqual([i["id"] for i in data["suggested_state"]["items"]], CHAIN_110)
        self.assertEqual(data["suggested_state"]["status"], "in_progress")

    def test_inspect_identifies_legacy_and_v100(self):
        legacy = self.git_repo("ph-merge-legacy-")
        self.write_manifest(legacy, names=BASE_SKILLS + OLD_ALIASES)
        self.write_agents(legacy)
        self.seed_legacy_names(legacy)
        code, out, err = self.invoke("inspect", "--repo", str(legacy))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["profile"], "1.1.0-legacy-names")
        self.assertEqual(data["from"], "1.1.0")
        self.assertEqual([i["id"] for i in data["suggested_state"]["items"]], CHAIN_110)

        v100 = self.git_repo("ph-merge-v100-")
        self.write_manifest(v100, version="1.0.0", names=BASE_SKILLS)
        self.write_agents(v100)
        self.seed_v100(v100)
        code, out, err = self.invoke("inspect", "--repo", str(v100))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["profile"], "1.0.0")
        self.assertEqual(data["from"], "1.0.0")
        self.assertEqual([i["id"] for i in data["suggested_state"]["items"]], CHAIN_100)

    def test_inspect_lists_mixed_intent_names(self):
        repo = self.git_repo("ph-merge-mixed-")
        self.write_manifest(repo, names=BASE_SKILLS)
        self.write_agents(repo)
        for name in BASE_SKILLS + ["ph-intent-capture", "ph-intent-new"]:
            self.write_skill(repo, name)
        code, out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["from"], "1.1.0")
        self.assertEqual(data["profile"], "mixed-intent-names")
        self.assertTrue(data["conflicts"])
        self.assertFalse(data["can_finalize"])

    def test_inspect_unknown_layout_blocks(self):
        repo = self.git_repo("ph-merge-unknown-")
        self.write_manifest(repo, names=BASE_SKILLS)
        self.write_agents(repo)
        for name in BASE_SKILLS + ["ph-custom-extra"]:
            self.write_skill(repo, name)
        code, _out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("unknown PH skill layout", err)

    def test_inspect_rejects_skill_symlink(self):
        repo = self.git_repo("ph-merge-symlink-skill-")
        self.write_manifest(repo, names=BASE_SKILLS + NEW_INTENT)
        self.write_agents(repo)
        for name in BASE_SKILLS + NEW_INTENT:
            self.write_skill(repo, name)
        skill = repo / ".agents" / "skills" / "ph-intent-new" / "SKILL.md"
        outside = self.temp_dir("ph-merge-outside-") / "SKILL.md"
        outside.write_text("escaped\n", encoding="utf-8")
        skill.unlink()
        skill.symlink_to(outside)
        code, _out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertTrue("regular file" in err or "nested symlink" in err, err)

    def test_verify_blocks_pending_and_empty_evidence(self):
        repo = self.fixture_110_current()
        self.install_receipt()
        state = self.write_state(repo)
        state["items"][0]["status"] = "pending"
        self.write_json(self.update_dir(repo) / "state.json", state)
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("intent-skill-names", err)

        state["items"][0]["status"] = "applied"
        state["items"][0]["evidence"] = "   "
        self.write_json(self.update_dir(repo) / "state.json", state)
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("evidence", err)

    def test_verify_blocks_live_old_alias(self):
        repo = self.fixture_110_current()
        self.install_receipt()
        self.write_state(repo)
        dest = repo / ".claude" / "skills" / "ph-intent-capture"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text("# leftover alias\n", encoding="utf-8")
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("old intent aliases still live", err)

    def test_finalize_dry_run_keeps_disk(self):
        repo = self.fixture_110_current("portable")
        self.install_receipt()
        self.write_state(repo)
        before = (repo / ".agents" / "ph.json").read_bytes()
        fact = (repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8")
        legacy = (repo / "docs/意图/进行中/新特性/INT-keep.md").read_bytes()
        snapshot = self.tree_snapshot(repo)
        code, out, err = self.invoke("finalize", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertFalse(data["apply"])
        self.assertFalse(data["complete"])
        self.assertEqual(
            sorted(data["codex_retirement"]["retirable"]), sorted(TARGET_SKILLS)
        )
        self.assertEqual((repo / ".agents" / "ph.json").read_bytes(), before)
        self.assertIn("keep-me", (repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual((repo / "docs/意图/进行中/新特性/INT-keep.md").read_bytes(), legacy)
        self.assertEqual(json.loads((self.update_dir(repo) / "state.json").read_text())["status"], "in_progress")
        self.assertEqual(fact, (repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"))
        # dry-run retires nothing: codex adapters stay live and no archive appears
        self.assertEqual(self.tree_snapshot(repo), snapshot)
        self.assertIsNone(self.archived_codex_dir(repo))

    def test_finalize_apply_portable_and_recovery(self):
        repo = self.fixture_110_current("portable")
        self.install_receipt()
        self.write_state(repo)
        manifest = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        manifest["project_note"] = "keep-user-field"
        self.write_json(repo / ".agents" / "ph.json", manifest)
        code, out, err = self.invoke("finalize", "--apply", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertTrue(data["complete"])
        written = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        self.assertEqual(written["template_version"], CURRENT)
        self.assertNotIn("schema_version", written)
        self.assertNotIn("codex_skills", written["adapters"])
        self.assertEqual(written["adapter_mode"], "portable")
        self.assertEqual(written["project_note"], "keep-user-field")
        self.assertEqual(written["skills"]["required_names"], TARGET_SKILLS)
        self.assertEqual(json.loads((self.update_dir(repo) / "state.json").read_text())["status"], "complete")
        self.assertIn("keep-me", (repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        self.assertIsNotNone(self.archived_codex_dir(repo))

        # complete rerun must re-verify live files
        (repo / "docs/意图/待办/README.md").unlink()
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("docs/意图/待办/README.md", err)

        # versions written, state not complete -> recover
        (repo / "docs/意图/待办/README.md").write_bytes((SCAFFOLD / "docs/意图/待办/README.md").read_bytes())
        state = json.loads((self.update_dir(repo) / "state.json").read_text())
        state["status"] = "in_progress"
        self.write_json(self.update_dir(repo) / "state.json", state)
        code, out, err = self.invoke("finalize", "--apply", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        self.assertTrue(self.load(out)["complete"])

    def test_finalize_apply_symlink_mode(self):
        repo = self.fixture_110_current("symlink")
        self.install_receipt()
        self.write_state(repo)
        code, out, err = self.invoke("finalize", "--apply", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["mode"], "symlink")
        written = json.loads((repo / ".agents" / "ph.json").read_text(encoding="utf-8"))
        self.assertEqual(written["adapter_mode"], "symlink")
        self.assertEqual(written["template_version"], CURRENT)
        self.assertNotIn("codex_skills", written["adapters"])
        self.assertTrue((repo / "AGENTS.md").is_symlink())
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        self.assertIsNotNone(self.archived_codex_dir(repo))

    def test_finalize_blocked_does_not_mark_complete(self):
        repo = self.fixture_110_current("portable")
        self.install_receipt()
        self.write_state(repo)
        original = (repo / ".agents" / "ph.json").read_bytes()

        def boom(*_a, **_k):
            raise ph_init.PHError("candidate check failed")

        with mock.patch.object(ph_merge_update, "cmd_check", side_effect=boom):
            with mock.patch.object(ph_merge_update, "cmd_sync", return_value=ph_init.Report("sync", "portable", False)):
                with mock.patch.object(ph_merge_update, "load_repo_manifest", return_value={}):
                    code, _out, err = self.invoke("finalize", "--apply", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("candidate check failed", err)
        self.assertEqual((repo / ".agents" / "ph.json").read_bytes(), original)
        self.assertEqual(json.loads((self.update_dir(repo) / "state.json").read_text())["status"], "in_progress")

    def test_finalize_without_receipt_is_blocked(self):
        repo = self.fixture_110_current()
        self.write_state(repo)
        code, _out, err = self.invoke("finalize", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("cannot finalize", err)
        self.assertEqual(json.loads((repo / ".agents" / "ph.json").read_text())["template_version"], "1.1.0")

    def test_inspect_does_not_call_locked_loader(self):
        repo = self.git_repo("ph-merge-noload-")
        self.write_manifest(repo, version="1.0.0", names=BASE_SKILLS)
        self.write_agents(repo)
        self.seed_v100(repo)

        def locked(*_a, **_k):
            raise AssertionError("inspect must not call load_repo_manifest")

        with mock.patch.object(ph_merge_update, "load_repo_manifest", side_effect=locked):
            code, out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.load(out)["from"], "1.0.0")

    def test_candidate_preserves_user_fields(self):
        data = {
            "schema_version": "1.1.0",
            "template_version": "1.1.0",
            "adapter_mode": "portable",
            "project_note": "keep",
            "adapters": {
                "claude_skills": {"mode": "mirror_tree"},
                "codex_skills": {"mode": "mirror_tree", "path": ".codex/skills"},
            },
            "skills": {"root": ".agents/skills", "required_names": BASE_SKILLS + NEW_INTENT},
        }
        cand = ph_merge_update.build_candidate(data, CURRENT, tuple(TARGET_SKILLS))
        self.assertEqual(cand["project_note"], "keep")
        self.assertEqual(cand["adapter_mode"], "portable")
        self.assertIn("claude_skills", cand["adapters"])
        self.assertNotIn("codex_skills", cand["adapters"])  # tool-neutral candidate
        self.assertEqual(cand["skills"]["required_names"], TARGET_SKILLS)
        self.assertEqual(cand["template_version"], CURRENT)
        self.assertNotIn("schema_version", cand)
        self.assertEqual(data["template_version"], "1.1.0")
        self.assertEqual(data["skills"]["required_names"], BASE_SKILLS + NEW_INTENT)
        self.assertIn("schema_version", data)
        self.assertIn("codex_skills", data["adapters"])

    def test_inspect_uses_manifest_version_not_skill_guess(self):
        repo = self.git_repo("ph-merge-partial-")
        names = BASE_SKILLS + NEW_INTENT + ["ph-merge-update"]
        self.write_manifest(repo, version="1.0.0", names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.write_intent_layout(repo)
        code, out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["from"], "1.0.0")
        self.assertEqual(data["profile"], "1.1.0-current-names")
        self.assertEqual([i["id"] for i in data["suggested_state"]["items"]], CHAIN_100)
        self.assertFalse(data["up_to_date"])

    def test_inspect_complete_target_is_up_to_date(self):
        repo = self.git_repo("ph-merge-current-")
        names = TARGET_SKILLS
        self.write_manifest(repo, version=CURRENT, names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.write_intent_layout(repo)
        # A fresh CURRENT install carries no codex adapters at all.
        self.seed_adapters(repo, "portable", names, codex=False)
        self.seed_gitignore(repo)
        code, out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["from"], CURRENT)
        self.assertEqual(data["to"], CURRENT)
        self.assertTrue(data["up_to_date"])
        self.assertIsNone(data["suggested_state"])
        self.assertFalse(data["can_finalize"])
        self.assertEqual(data["codex_retirement"]["retirable"], [])
        self.assertEqual(data["codex_retirement"]["blocked"], [])
        self.assertFalse((self.update_dir(repo) / "state.json").exists())

    def test_inspect_keeps_state_from_and_rejects_unrelated_disk_version(self):
        repo = self.git_repo("ph-merge-interrupt-")
        names = BASE_SKILLS + NEW_INTENT
        self.write_manifest(repo, version="1.0.0", names=names)
        self.write_agents(repo)
        for name in names:
            self.write_skill(repo, name)
        self.write_state(repo, from_version="1.1.0")
        code, out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("neither from", err)

        self.write_manifest(repo, version=CURRENT, names=names)
        code, out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = self.load(out)
        self.assertEqual(data["from"], "1.1.0")
        self.assertFalse(data["up_to_date"])
        self.assertEqual(data["existing_state"]["from_version"], "1.1.0")

    def test_inspect_unknown_version_must_be_on_chain(self):
        repo = self.git_repo("ph-merge-unknown-ver-")
        self.write_manifest(repo, version="1.2.0", names=BASE_SKILLS + NEW_INTENT)
        self.write_agents(repo)
        for name in BASE_SKILLS + NEW_INTENT:
            self.write_skill(repo, name)
        code, _out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertTrue("downgrade" in err or "missing migration chain" in err, err)

    def test_verify_blocks_mixed_names_before_retire(self):
        repo = self.fixture_110_current()
        self.install_receipt()
        self.write_state(repo)
        self.write_skill(repo, "ph-intent-capture")
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("retire old intent aliases", err)

    def test_verify_requires_target_schema_and_runtime(self):
        repo = self.fixture_110_current()
        self.install_receipt()
        self.write_state(repo)
        (repo / ".agents" / "ph.schema.json").write_text("{}\n", encoding="utf-8")
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("ph.schema.json", err)

        (repo / ".agents" / "ph.schema.json").write_bytes((SCAFFOLD / ".agents" / "ph.schema.json").read_bytes())
        (repo / ".agents" / "skills" / "ph-init" / "release.json").write_text(
            json.dumps({"version": "9.9.9", "required_skills": TARGET_SKILLS}) + "\n",
            encoding="utf-8",
        )
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("ph-init", err)

        (repo / ".agents" / "skills" / "ph-init" / "release.json").write_bytes((REPO_ROOT / "release.json").read_bytes())
        (repo / "docs/意图/_模板.md").write_text("status_dir: 进行中/新特性\n", encoding="utf-8")
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("must default status_dir", err)

    def test_verify_surfaces_sync_plan_block(self):
        repo = self.fixture_110_current()
        self.install_receipt()
        self.write_state(repo)
        blocked = ph_init.Report("sync", "portable", False)
        blocked.add("conflict", "AGENTS.md", "destination is a symlink", ph_init.PROBLEM_DEST_SYMLINK)
        with mock.patch.object(ph_merge_update, "cmd_sync", return_value=blocked):
            code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("candidate sync plan", err)
        self.assertIn("AGENTS.md", err)
        self.assertIn("symlink", err)

    def test_path_safety_rejects_docs_updates_and_index_escape(self):
        repo = self.git_repo("ph-merge-path-")
        self.write_manifest(repo, names=BASE_SKILLS + NEW_INTENT)
        self.write_agents(repo)
        for name in BASE_SKILLS + NEW_INTENT:
            self.write_skill(repo, name)
        outside = self.temp_dir("ph-merge-docs-out-")
        (outside / "docs").mkdir()
        (repo / "docs").symlink_to(outside / "docs")
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.assert_real_dir(repo, repo / "docs" / "意图" / "待办", "docs/意图/待办")
        self.assertIn("symlink", str(ctx.exception))

        in_repo_docs = repo / ".agents" / "docs-target"
        in_repo_docs.mkdir()
        linked_docs = repo / "docs-inrepo"
        linked_docs.symlink_to(in_repo_docs)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.assert_real_dir(repo, linked_docs / "意图", "docs-inrepo/意图")
        self.assertIn("symlink", str(ctx.exception))

        updates_out = outside / "updates"
        updates_out.mkdir()
        (repo / ".agents" / "updates").symlink_to(updates_out)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.updates_dir(repo, CURRENT)
        self.assertIn("symlink", str(ctx.exception))
        code, _out, err = self.invoke("inspect", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("error=", err)
        self.assertIn("symlink", err)

        hops = [{"from_version": "1.1.0", "to_version": "1.1.1", "path": "migrations/../release.json", "items": ["x"]}]
        with mock.patch.object(ph_merge_update, "read_json", side_effect=lambda path: {"format_version": 1, "migrations": hops} if path.name == "index.json" else ph_init.read_json(path)):
            with self.assertRaises(ph_init.PHError) as ctx:
                ph_merge_update.load_index()
        self.assertIn("path", str(ctx.exception))

        hops = [
            {"from_version": "1.0.0", "to_version": "1.1.0", "path": "migrations/1.0.0-to-1.1.0.md", "items": ["a"]},
            {"from_version": "1.1.0", "to_version": "1.0.0", "path": "migrations/1.1.0-to-1.1.1.md", "items": ["b"]},
        ]
        with mock.patch.object(ph_merge_update, "read_json", side_effect=lambda path: {"format_version": 1, "migrations": hops} if path.name == "index.json" else ph_init.read_json(path)):
            with self.assertRaises(ph_init.PHError) as ctx:
                ph_merge_update.load_index()
        self.assertTrue("increase" in str(ctx.exception) or "unique" in str(ctx.exception), str(ctx.exception))

    def test_dump_json_uses_unique_temp_and_trash_on_failure(self):
        dest = self.temp_dir("ph-merge-dump-") / "state.json"
        dest.write_text("{}\n", encoding="utf-8")
        seen = []
        real_mkstemp = tempfile.mkstemp

        def fake_mkstemp(prefix, suffix, dir):
            fd, name = real_mkstemp(prefix=prefix, suffix=suffix, dir=dir)
            seen.append(name)
            return fd, name

        with mock.patch.object(tempfile, "mkstemp", side_effect=fake_mkstemp):
            ph_merge_update.dump_json(dest, {"ok": True})
        self.assertTrue(seen)
        self.assertEqual(json.loads(dest.read_text())["ok"], True)
        self.assertTrue(Path(seen[0]).name.startswith(".state.json."))

        def fail_replace(*_a, **_k):
            raise OSError("replace failed")

        dest2 = self.temp_dir("ph-merge-dump-fail-") / "state.json"
        with mock.patch.object(os, "replace", side_effect=fail_replace):
            with self.assertRaises(OSError):
                ph_merge_update.dump_json(dest2, {"ok": False})
        leftovers = list(dest2.parent.glob(".state.json.*.tmp"))
        self.assertEqual(leftovers, [])

    def test_failed_regular_check_does_not_keep_complete(self):
        repo = self.fixture_110_current()
        self.install_receipt()
        self.write_state(repo, status="complete")
        original = (repo / ".agents" / "ph.json").read_bytes()
        ok = ph_init.Report("check", "portable", False)
        blocked = ph_init.Report("check", "portable", False)
        blocked.add("error", ".agents/ph.json", "regular check failed")
        calls = {"n": 0}

        def check(_repo, _mode, *, candidate=None):
            calls["n"] += 1
            return ok if candidate is not None else blocked

        with mock.patch.object(ph_merge_update, "cmd_check", side_effect=check):
            with mock.patch.object(ph_merge_update, "cmd_sync", return_value=ph_init.Report("sync", "portable", False)):
                with mock.patch.object(ph_merge_update, "load_repo_manifest", return_value={}):
                    code, _out, err = self.invoke("finalize", "--apply", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("regular check", err)
        self.assertEqual(json.loads((self.update_dir(repo) / "state.json").read_text())["status"], "in_progress")
        self.assertNotEqual((repo / ".agents" / "ph.json").read_bytes(), original)

    def test_source_receipt_requires_git_objects(self):
        fake_root = self.temp_dir("ph-merge-prepared-")
        receipt = self.receipt()
        (fake_root / ".ph-source.json").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        (fake_root / "release.json").write_text("{}\n", encoding="utf-8")
        with mock.patch.object(ph_merge_update, "SOURCE_ROOT", fake_root):
            status = ph_merge_update.source_status(CURRENT)
        self.assertFalse(status["verified"])
        self.assertIn("prepared git objects", status["reason"])

        workspace = self.temp_dir("ph-merge-workspace-")
        git_dir = workspace / "git"
        root = workspace / "root"
        git_dir.mkdir()
        copy_tree(REPO_ROOT, root)
        run(["git", "init", "--bare", "--template="], cwd=git_dir)
        (root / ".ph-source.json").write_text(json.dumps(self.receipt("9.9.9")) + "\n", encoding="utf-8")
        with mock.patch.object(ph_merge_update, "SOURCE_ROOT", root):
            status = ph_merge_update.source_status(CURRENT)
        self.assertFalse(status["verified"])

    def test_receipt_identity_keeps_historical_source_across_rename(self):
        """Receipts and state keep the historical URL; downloads moved to the new repo.

        The 1.1.9 repository rename must not change receipt identity: the
        upgrade tool keeps validating FIXED_SOURCE, release.json keeps
        declaring it, and only ph_release's network access (DOWNLOAD_SOURCE)
        follows the renamed project-harness repository. Pre-rename receipts
        and update state therefore keep verifying without any rewrite.
        """
        self.assertEqual(FIXED_SOURCE, "https://github.com/chenweixuanJokes/ph-init.git")
        self.assertEqual(ph_merge_update.FIXED_SOURCE, FIXED_SOURCE)
        self.assertEqual(ph_release.FIXED_SOURCE, FIXED_SOURCE)
        self.assertEqual(
            ph_release.DOWNLOAD_SOURCE,
            "https://github.com/chenweixuanJokes/project-harness.git",
        )
        release = json.loads((REPO_ROOT / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(release["repository"], FIXED_SOURCE)

    def test_state_source_rejects_foreign_commit_and_repository(self):
        """state.source must match the receipt exactly; the historical URL stays valid.

        Interruption recovery relies on the state being bound to one target:
        a different commit or tag than the verified receipt is rejected, and
        so is any repository other than the historical FIXED_SOURCE - even the
        renamed download URL is not a receipt identity. Only the exact same
        tag/commit/source verifies.
        """
        repo = self.fixture_110_current()
        self.install_receipt()
        state = self.write_state(repo)

        state["source"]["commit"] = "b" * 40
        self.write_json(self.update_dir(repo) / "state.json", state)
        with self.assertRaisesRegex(ph_init.PHError, "does not match source receipt"):
            ph_merge_update.verify_payload(repo)

        state["source"]["tag"] = "v9.9.9"
        state["source"]["commit"] = COMMIT
        self.write_json(self.update_dir(repo) / "state.json", state)
        with self.assertRaisesRegex(ph_init.PHError, "does not match source receipt"):
            ph_merge_update.verify_payload(repo)

        state["source"]["tag"] = f"v{CURRENT}"
        state["source"]["repository"] = "https://github.com/chenweixuanJokes/project-harness.git"
        self.write_json(self.update_dir(repo) / "state.json", state)
        with self.assertRaisesRegex(ph_init.PHError, "fixed GitHub source"):
            ph_merge_update.verify_payload(repo)

        # The historical URL written before the rename keeps verifying as-is.
        state["source"]["repository"] = FIXED_SOURCE
        self.write_json(self.update_dir(repo) / "state.json", state)
        self.assertTrue(ph_merge_update.verify_payload(repo)["ok"])

    def _seed_release_tree(self, root: Path, version=None) -> None:
        version = version or CURRENT
        files = {
            "release.json": json.dumps({"version": version}) + "\n",
            "SKILL.md": "# skill\n",
            "scripts/ph_init.py": "print(1)\n",
            "scripts/ph_release.py": "print(2)\n",
            "scripts/ph_merge_update.py": "print(3)\n",
            "migrations/index.json": '{"format_version":1,"migrations":[]}\n',
            "assets/scaffold/.agents/ph.json": "{}\n",
            "assets/scaffold/.agents/ph.schema.json": "{}\n",
            "assets/scaffold/docs/意图/_模板.md": "status_dir: 待办/新特性\n",
            "README.md": "extra\n",
        }
        for rel, text in files.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")

    def test_prepared_root_receipt_matches_bare_tree(self):
        workspace = self.temp_dir("ph-merge-prepared-ok-")
        src = workspace / "src"
        src.mkdir()
        self._seed_release_tree(src)
        for argv in (
            ["git", "init"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "ph-merge-test"],
        ):
            self.assertEqual(run(argv, cwd=src).returncode, 0)
        self.assertEqual(run(["git", "add", "."], cwd=src).returncode, 0)
        self.assertEqual(run(["git", "commit", "-m", f"v{CURRENT}"], cwd=src).returncode, 0)
        self.assertEqual(run(["git", "tag", f"v{CURRENT}"], cwd=src).returncode, 0)
        commit = run(["git", "rev-parse", "HEAD"], cwd=src).stdout.strip()
        git_dir = workspace / "git"
        cloned = run(["git", "clone", "--bare", "--template=", str(src), str(git_dir)])
        self.assertEqual(cloned.returncode, 0, cloned.stderr)
        root = workspace / "root"
        copy_tree(src, root)
        receipt = {"version": CURRENT, "tag": f"v{CURRENT}", "commit": commit, "source": FIXED_SOURCE}
        (root / ".ph-source.json").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        with mock.patch.object(ph_merge_update, "SOURCE_ROOT", root):
            status = ph_merge_update.source_status(CURRENT)
            self.assertTrue(status["verified"], status["reason"])
            (root / "assets/scaffold/docs/意图/_模板.md").write_text('status_dir: 已废弃\n', encoding="utf-8")
            status = ph_merge_update.source_status(CURRENT)
        self.assertFalse(status["verified"])
        self.assertIn("does not match commit", status["reason"])

    def test_development_root_receipt_matches_head_and_tag(self):
        src = self.git_repo("ph-merge-devsrc-")
        self._seed_release_tree(src)
        self.assertEqual(run(["git", "add", "."], cwd=src).returncode, 0)
        self.assertEqual(run(["git", "commit", "-m", f"v{CURRENT}"], cwd=src).returncode, 0)
        self.assertEqual(run(["git", "tag", f"v{CURRENT}"], cwd=src).returncode, 0)
        commit = run(["git", "rev-parse", "HEAD"], cwd=src).stdout.strip()
        receipt = {"version": CURRENT, "tag": f"v{CURRENT}", "commit": commit, "source": FIXED_SOURCE}
        (src / ".ph-source.json").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
        with mock.patch.object(ph_merge_update, "SOURCE_ROOT", src):
            status = ph_merge_update.source_status(CURRENT)
            self.assertTrue(status["verified"], status["reason"])
            (src / "SKILL.md").write_text("# dirty\n", encoding="utf-8")
            status = ph_merge_update.source_status(CURRENT)
        self.assertFalse(status["verified"])
        self.assertIn("does not match commit", status["reason"])


if __name__ == "__main__":
    unittest.main()
