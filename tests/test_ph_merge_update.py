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
import ph_speckit  # noqa: E402
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))
import _speckit_seed  # noqa: E402

TRASH_ROOT = Path.home() / "trash"
FIXED_SOURCE = ph_merge_update.FIXED_SOURCE
COMMIT = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CURRENT, TARGET_SKILLS_TUPLE = ph_merge_update.release_contract()
TARGET_SKILLS = list(TARGET_SKILLS_TUPLE)
BASE_SKILLS = list(ph_merge_update.BASE_SKILLS)
OLD_ALIASES = list(ph_merge_update.OLD_ALIASES)
NEW_INTENT = list(ph_merge_update.NEW_INTENT)
RETIRED_SKILLS = list(ph_merge_update.RETIRED_SKILLS)
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
    "worktree-wip-confirm",
    "retire-legacy-skills",
    "speckit-core-integration",
    "constitution-governance-zone",
    "intent-to-spec",
    "speckit-integrity-gates",
    "memory-skills",
    "ph-home-restructure",
    "constitution-materialization",
    "intent-retirement", "bundled-speckit-acceptance",
    "user-entry-refresh", "human-readable-companion", "speckit-next-step-hints",
]
CHAIN_100 = ["intent-domain", *CHAIN_110]
CHAIN_111 = CHAIN_110[6:]  # everything after the 1.1.0 -> 1.1.1 hop
CHAIN_117 = ["single-ph-version", "worktree-auto-branch", "tool-neutral-adapters", "repository-rename", "docs-sync-skill", "current-branch-defaults", "adopt-mode-docs", "question-execution-contract", "explicit-invocation-rules", "intent-verify-skill", "worktree-wip-confirm", "retire-legacy-skills", "speckit-core-integration", "constitution-governance-zone", "intent-to-spec", "speckit-integrity-gates", "memory-skills", "ph-home-restructure", "constitution-materialization", "intent-retirement", "bundled-speckit-acceptance", "user-entry-refresh", "human-readable-companion", "speckit-next-step-hints"]
CHAIN_118 = ["worktree-auto-branch", "tool-neutral-adapters", "repository-rename", "docs-sync-skill", "current-branch-defaults", "adopt-mode-docs", "question-execution-contract", "explicit-invocation-rules", "intent-verify-skill", "worktree-wip-confirm", "retire-legacy-skills", "speckit-core-integration", "constitution-governance-zone", "intent-to-spec", "speckit-integrity-gates", "memory-skills", "ph-home-restructure", "constitution-materialization", "intent-retirement", "bundled-speckit-acceptance", "user-entry-refresh", "human-readable-companion", "speckit-next-step-hints"]
CHAIN_119 = ["docs-sync-skill", "current-branch-defaults", "adopt-mode-docs", "question-execution-contract", "explicit-invocation-rules", "intent-verify-skill", "worktree-wip-confirm", "retire-legacy-skills", "speckit-core-integration", "constitution-governance-zone", "intent-to-spec", "speckit-integrity-gates", "memory-skills", "ph-home-restructure", "constitution-materialization", "intent-retirement", "bundled-speckit-acceptance", "user-entry-refresh", "human-readable-companion", "speckit-next-step-hints"]
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
    @classmethod
    def setUpClass(cls):
        # One real pinned-generation spec-kit install (cache or network),
        # shared by every fixture: it simulates the Agent-executed
        # speckit-core-integration migration item, whose artifacts the
        # upgrade verify/finalize steps require on disk.
        cls._speckit_seed = _speckit_seed.ensure_seed()

    def seed_speckit(self, repo: Path) -> None:
        """Copy the real pinned-generation artifacts into the fixture.

        The real `ph_speckit.py install --apply` also renders the constitution
        override for THIS repo (its navigation zone references this repo's
        docs/约束规范, so the seed's own override does not fit) and records
        the per-file content baselines into .agents/ph.json (the ownership
        proof the next upgrade compares a differing file against)."""
        src = self._speckit_seed
        for name in ph_init.SPECKIT_SKILL_NAMES:
            copy_tree(src / ".agents/skills" / name, repo / ".agents/skills" / name)
        # 1.2.1 layout: the seed's .specify tree installs through the layout
        # mapping (runtime relocation + materialized constitution), so the
        # fixture matches what a real install produces on a fresh repo.
        import ph_layout as _layout
        # The seed itself is built through the real install, so its runtime
        # and materialized constitution already sit at the 1.2.1 layout.
        for source in sorted(((src / _layout.HOME) / "runtime").rglob("*")):
            if not source.is_file():
                continue
            dest = repo / source.relative_to(src).as_posix()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        shutil.copy2(src / _layout.CONSTITUTION, repo / _layout.CONSTITUTION)
        constraints = repo / _layout.CONSTRAINTS
        constraints.mkdir(parents=True, exist_ok=True)
        from content_fixture import complete_documentation_project
        complete_documentation_project(repo, REPO_ROOT)
        (repo / _layout.HOME / "documents").mkdir(parents=True, exist_ok=True)
        (repo / _layout.HOME / "documents" / "README.md").write_text("# 项目资料\n", encoding="utf-8")
        archive_memory = repo / _layout.HOME / "archive" / "memory"
        archive_memory.mkdir(parents=True, exist_ok=True)
        (archive_memory / "README.md").write_text("# 记忆归档原件\n", encoding="utf-8")
        live = repo / _layout.CONSTITUTION
        scripts = repo / ".agents" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            REPO_ROOT / "assets/scaffold/.agents/scripts/ph_worktree.py",
            scripts / "ph_worktree.py",
        )
        # 1.2.2: the shared human-companion script is part of the managed
        # scaffold payload the candidate check requires on disk.
        shutil.copy2(
            REPO_ROOT / "assets/scaffold/.agents/scripts/ph_human.py",
            scripts / "ph_human.py",
        )
        contract = ph_speckit.speckit_contract()
        staging = ph_speckit.resolve_staging(None, contract)
        override = repo / ph_speckit.CONSTITUTION_OVERRIDE_REL
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_bytes(ph_speckit.render_constitution_override(repo, staging, contract))
        live.write_bytes(ph_speckit.render_live_constitution(repo, staging, contract))
        ph_speckit.cmd_record_baselines(
            repo, None, refresh_override_sha=ph_init.sha256_file(override), refresh_constitution_sha=ph_init.sha256_file(live)
        )

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
        disk = repo / ".agents" / "ph.json"
        if disk.is_file():
            # Simulate an upgrade: the project manifest keeps its installed
            # speckit section (baselines + provenance) instead of the blank
            # template section wiping it.
            try:
                existing = json.loads(disk.read_text(encoding="utf-8"))
            except Exception:
                existing = None
            if isinstance(existing, dict) and isinstance(existing.get("speckit"), dict):
                data["speckit"] = existing["speckit"]
        self.write_json(disk, data)
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

    def apply_114_migration(self, repo: Path) -> None:
        """Simulate the Agent-executed 1.1.14 semantic merge steps on disk.

        The retirement item archives the retired skills out of the managed
        install (mirrors included) and the speckit item installs the ten
        upstream skills plus the .specify shared infrastructure. The 1.2.1
        target re-ships ph-memory-ask and ph-memory-archive with a new
        contract and ships the new ph-memory-learning, so this helper folds
        that later hop's install in as the merged final operation: archive
        the old copies, then install the release-byte memory skills (the
        memory-skills item's own work). ph-memory-capture stays retired -
        nothing installs it again.
        """
        for name in set(RETIRED_SKILLS) | {"ph-sure"}:
            for rel in (
                Path(".agents") / "skills" / name,
                Path(".claude") / "skills" / name,
            ):
                target = repo / rel
                if target.exists() and not target.is_symlink():
                    shutil.rmtree(target)
                elif target.is_symlink() or target.exists():
                    target.unlink()
        # the tool-neutral adapters item (1.1.9) archived .codex before the
        # retirement item runs, so the post-merge state has no .codex left
        codex_root = repo / ".codex"
        if codex_root.exists():
            shutil.rmtree(codex_root)
        self.seed_speckit(repo)
        self.install_memory_skills(repo)

    def install_memory_skills(self, repo: Path) -> None:
        """The 1.2.1 memory-skills item: install the three release-byte skills."""
        for name in ("ph-memory-ask", "ph-memory-learning", "ph-memory-archive"):
            copy_tree(SCAFFOLD / ".agents" / "skills" / name, repo / ".agents" / "skills" / name)

    def apply_speckit_with_retire_na(self, repo: Path) -> None:
        """The 1.1.8-era codex tests keep the retired skills canonical (the
        codex mirror archive compares against them), so the retirement item
        stays not_applicable while the spec-kit item is applied."""
        state_path = self.update_dir(repo) / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for item in state["items"]:
            if item["id"] == "retire-legacy-skills":
                item["status"] = "not_applicable"
                item["evidence"] = "codex-archive scenario: canonical kept for mirror comparison"
        self.write_json(state_path, state)
        self.seed_speckit(repo)

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
        # 1.2.1: retired codex adapters land in the unified project-harness
        # archive, not a top-level .agents/archived directory
        root = repo / ".agents" / "project-harness" / "archive" / "legacy-backup"
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
        if "intent-to-spec" in ids:
            # The mandatory migration item's on-disk artifacts (ledger,
            # migrated specs, history index) are part of the applied state the
            # verify gate checks; produce them the way the real item does.
            ph_merge_update.migrate_intents_payload(repo, True)
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
        index = repo / ".agents/project-harness/documents/README.md"
        custom = index.read_text(encoding="utf-8") + "\n[项目定制规则](../constraints/custom-rule.md)\n"
        index.write_text(custom, encoding="utf-8")
        intent = repo / ".agents/project-harness/constraints/custom-rule.md"
        intent.write_text("# 项目定制规则\n使用时机：触及本项目定制规则的工作前阅读。\n", encoding="utf-8")
        report_path = repo / ".agents/project-harness/init-report.json"
        report = json.loads(report_path.read_text())
        report["documents"]["custom-rule.md"] = {
            "status": "adopted", "sha256": ph_init.sha256_file(intent),
            "evidence": "本测试新增的项目定制规则", "reason": "验证新增专题不会在升级中丢失",
            "semantic_review": True,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False))
        # A new constraints file must enter the constitution navigation before
        # finalize: the complete-index contract refuses an uncovered file.
        constitution = repo / ".agents/project-harness/constitution.md"
        text = constitution.read_text(encoding="utf-8")
        marker = text.index(ph_speckit.PH_OVERRIDE_MARKER)
        head, zone = text[:marker], text[marker:]
        zone = zone.replace(
            "## 约束导航\n\n",
            "## 约束导航\n\n- [项目定制规则](constraints/custom-rule.md)\n  使用时机：触及本项目定制规则的工作前阅读。\n",
            1,
        )
        constitution.write_text(head + zone, encoding="utf-8")
        ph_merge_update.finalize_payload(repo, True)
        result = ph_merge_update.inspect_payload(repo)
        self.assertTrue(result["up_to_date"])
        self.assertFalse(result["can_finalize"])
        self.assertIsNone(result["suggested_state"])
        self.assertEqual(index.read_text(encoding="utf-8"), custom)
        self.assertEqual(intent.read_text(encoding="utf-8"), "# 项目定制规则\n使用时机：触及本项目定制规则的工作前阅读。\n")
        self.assertIn("constraints/custom-rule.md", constitution.read_text(encoding="utf-8"))

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
                               "intent-verify-skill", "worktree-wip-confirm", "retire-legacy-skills",
                               "speckit-core-integration", "constitution-governance-zone",
                               "intent-to-spec", "speckit-integrity-gates", "memory-skills", "ph-home-restructure", "constitution-materialization", "intent-retirement", "bundled-speckit-acceptance", "user-entry-refresh", "human-readable-companion", "speckit-next-step-hints"])
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
        (repo / ".agents/project-harness/constitution.md").unlink()
        with self.assertRaisesRegex(ph_init.PHError, "constitution"):
            ph_merge_update.inspect_payload(repo)

    def fixture_110_current(self, mode="portable"):
        """The post-merge state: the four scaffold skills plus the ten
        spec-kit skills the Agent-executed migration items installed."""
        repo = self.git_repo(f"ph-merge-{mode}-")
        names = list(ph_init.ALL_REQUIRED_SKILL_NAMES)
        self.write_manifest(repo, mode=mode, names=BASE_SKILLS + NEW_INTENT + ["ph-merge-update"])
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.seed_speckit(repo)
        self.write_intent_layout(repo, in_progress=True)
        self.seed_adapters(repo, mode, names)
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
        for name in names:
            if not (repo / ".agents" / "skills" / name / "SKILL.md").is_file():
                self.write_skill(repo, name)
        self.write_intent_layout(repo, in_progress=True)
        self.seed_adapters(repo, mode, names + list(ph_init.SPECKIT_SKILL_NAMES))
        self.seed_gitignore(repo)
        return repo

    def fixture_at_119(self, mode="portable"):
        """A 1.1.9 install: single version, three-adapter topology, ten skills."""
        repo = self.git_repo(f"ph-merge-v119-{mode}-")
        names = BASE_SKILLS + NEW_INTENT + ["ph-merge-update"]
        self.write_manifest(repo, mode=mode, version="1.1.9", names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        # 1.1.9-1.1.13 installs carried the docs-sync and intent-verify
        # skills on top of the base ten; materialize them for realism.
        for name in (*names, "ph-docs-sync", "ph-intent-verify"):
            if not (repo / ".agents" / "skills" / name / "SKILL.md").is_file():
                self.write_skill(repo, name)
        self.write_intent_layout(repo, in_progress=True)
        # 1.1.9 installs carry no codex adapters (tool-neutral topology).
        self.seed_adapters(repo, mode, names, codex=False)
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
                self.apply_114_migration(repo)
                # The simulated Agent-executed migration items legitimately
                # rewrote the manifest (speckit install records the per-file
                # content baselines); from here on nothing may change it.
                post_merge_bytes = manifest_path.read_bytes()
                verified = ph_merge_update.verify_payload(repo)
                self.assertTrue(verified["ok"])
                self.assertEqual(verified["from"], from_version)
                self.assertEqual(manifest_path.read_bytes(), post_merge_bytes, "verify must stay read-only")
                self.assertEqual((repo / ".agents" / "AGENTS.md").read_bytes(), agents_bytes)

                old = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(old["schema_version"], "1.1.1")
                self.assertIn("codex_skills", old["adapters"])
                cand = ph_merge_update.build_candidate(old, CURRENT, tuple(TARGET_SKILLS))
                self.assertNotIn("schema_version", cand)
                self.assertNotIn("codex_skills", cand["adapters"])
                self.assertEqual(cand["template_version"], CURRENT)
                self.assertEqual(cand["skills"]["required_names"], list(ph_init.ALL_REQUIRED_SKILL_NAMES))
                self.assertEqual(cand["project_note"], "keep-user-field")
                self.assertEqual(cand["worktree"], old["worktree"])
                self.assertEqual(cand["memory"], old["memory"])
                ph_init.load_repo_manifest(repo, candidate=cand)

                # dry-run finalize writes nothing
                result = ph_merge_update.finalize_payload(repo, False)
                self.assertFalse(result["apply"])
                self.assertFalse(result["complete"])
                self.assertEqual(manifest_path.read_bytes(), post_merge_bytes)

                # a pending migration item blocks apply and never falsely completes
                state["items"][-1]["status"] = "pending"
                self.write_json(self.update_dir(repo) / "state.json", state)
                with self.assertRaises(ph_init.PHError):
                    ph_merge_update.finalize_payload(repo, True)
                self.assertEqual(manifest_path.read_bytes(), post_merge_bytes)
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
                self.assertEqual(written["skills"]["required_names"], list(ph_init.ALL_REQUIRED_SKILL_NAMES))
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

    def fixture_at_115(self, mode="portable"):
        """A 1.1.15 install: four PH skills plus the ten spec-kit skills and
        no memory skills (PH shipped none between 1.1.14 and 1.1.15)."""
        repo = self.git_repo(f"ph-merge-v115-{mode}-")
        names = ["ph-init", "ph-merge-update", "ph-worktree-enter", "ph-worktree-exit"]
        self.write_manifest(repo, mode=mode, version="1.1.15", names=names)
        self.write_agents(repo)
        for name in names:
            if name == "ph-init":
                copy_tree(REPO_ROOT, repo / ".agents" / "skills" / "ph-init")
            else:
                self.write_skill(repo, name)
        self.seed_speckit(repo)
        self.write_intent_layout(repo, in_progress=True)
        self.seed_adapters(repo, mode, names + list(ph_init.SPECKIT_SKILL_NAMES), codex=False)
        self.seed_gitignore(repo)
        return repo

    def test_memory_same_name_custom_skill_blocks_inspect(self):
        # 1.1.14+ projects live in a window where no PH release ships the
        # memory names: a same-named directory there is project content on a
        # PH-reserved name and blocks the memory-skills item instead of being
        # overwritten by the 1.1.16 install.
        self.install_receipt()
        repo = self.fixture_at_115()
        custom = repo / ".agents/skills/ph-memory-ask/SKILL.md"
        custom.parent.mkdir(parents=True, exist_ok=True)
        custom_body = (
            "---\nname: ph-memory-ask\ndescription: team custom memory lookup\n---\n"
            "# our own memory skill\n项目自建记忆查询，升级不得覆盖。\n"
        )
        custom.write_text(custom_body, encoding="utf-8")
        before = self.tree_snapshot(repo)

        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.15")
        self.assertEqual(inspected["to"], CURRENT)
        self.assertEqual(inspected["profile"], "speckit-current")
        self.assertTrue(
            # 1.2.1 is the arrival version of the memory names, not CURRENT:
            # the conflict window keeps its fixed floor across later releases.
            any("ph-memory-ask" in conflict and "1.2.1" in conflict for conflict in inspected["conflicts"]),
            inspected["conflicts"],
        )
        self.assertFalse(inspected["can_finalize"])
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

    def test_capture_residual_above_114_blocks_memory_item(self):
        # ph-memory-capture is retired since 1.1.14 and the 1.2.1 target folds
        # its duty into ph-memory-learning without re-shipping the name: a
        # live directory at 1.1.14+ is user content on a PH-reserved retired
        # name and blocks the memory-skills item; nothing deletes it silently.
        self.install_receipt()
        repo = self.fixture_at_115()
        residual = repo / ".agents/skills/ph-memory-capture/SKILL.md"
        residual.parent.mkdir(parents=True, exist_ok=True)
        residual.write_text(
            "---\nname: ph-memory-capture\ndescription: user-restored copy\n---\n"
            "# manually restored capture\n用户手动恢复的旧记录技能。\n",
            encoding="utf-8",
        )
        before = self.tree_snapshot(repo)

        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.15")
        self.assertTrue(
            any("ph-memory-capture" in conflict for conflict in inspected["conflicts"]),
            inspected["conflicts"],
        )
        self.assertFalse(inspected["can_finalize"])
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertTrue(residual.read_text(encoding="utf-8").startswith("---\n"))

    def test_memory_historical_copy_below_114_is_not_a_conflict(self):
        # Below 1.1.14 PH shipped the old same-named memory skills as scaffold
        # content: the live copies are the official historical skill, the
        # retire-legacy-skills item archives them, and the memory-skills item
        # installs the new contract - no same-name conflict may fire.
        self.install_receipt()
        repo = self.fixture_at_119()
        for name in ("ph-memory-ask", "ph-memory-capture", "ph-memory-archive", "ph-memory-learning"):
            self.assertTrue((repo / ".agents" / "skills" / name / "SKILL.md").is_file(), name)
        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.9")
        self.assertEqual(inspected["profile"], "1.1.0-current-names")
        # the fixture also carries a synthetic docs-sync placeholder that
        # conflicts on its own; the memory names must NOT appear at all
        self.assertFalse(
            any("ph-memory" in conflict for conflict in inspected["conflicts"]),
            inspected["conflicts"],
        )

    def test_memory_pin_rejects_drifted_install(self):
        # While the disk is below 1.2.1 an applied memory-skills item pins the
        # installed memory skills to the release bytes: a drifted (customized)
        # ph-memory-ask must not pass as the installed one.
        self.install_receipt()
        repo = self.fixture_at_119()
        self.write_state(repo, from_version="1.1.9", items=CHAIN_119)
        self.apply_114_migration(repo)
        # the re-shipped memory skills are live while retire-legacy-skills is
        # applied: the 1.2.1 target ships them, so the retirement gate must
        # NOT reject them as leftovers; ph-memory-capture is retired and not
        # re-shipped, so it must be gone from the managed install instead.
        for name in ("ph-memory-ask", "ph-memory-learning", "ph-memory-archive"):
            self.assertTrue((repo / ".agents" / "skills" / name / "SKILL.md").is_file(), name)
        self.assertFalse((repo / ".agents" / "skills" / "ph-memory-capture").exists())
        self.assertTrue(ph_merge_update.verify_payload(repo)["ok"])

        drifted = repo / ".agents/skills/ph-memory-ask/SKILL.md"
        drifted.write_text(
            "---\nname: ph-memory-ask\ndescription: drifted body\n---\n# drifted\n",
            encoding="utf-8",
        )
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("ph-memory-ask", str(ctx.exception))
        self.assertIn("does not match the release skill", str(ctx.exception))

    def test_docs_sync_same_name_custom_skill_blocks_inspect(self):
        self.install_receipt()
        repo = self.fixture_at_119()
        custom = repo / ".agents/skills/ph-docs-sync/SKILL.md"
        custom.parent.mkdir(parents=True, exist_ok=True)
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
        custom.parent.mkdir(parents=True, exist_ok=True)
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
        # the state marks intent-to-spec applied; its on-disk artifacts are
        # part of that state and precede the retirement gate in verify
        ph_merge_update.migrate_intents_payload(repo, True)

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

        # Marking every item applied while the custom skill stays in place
        # must not pass verify either: the retirement gate rejects the live
        # retired skill even when the byte pin no longer applies to it.
        for item in state["items"]:
            item["status"] = "applied"
            item["evidence"] = "fixture already contains the target skill defaults"
        docs_sync["status"] = "applied"
        docs_sync["evidence"] = "falsely claims the release skill was installed"
        self.write_json(dest / "state.json", state)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("retired skills still live", str(ctx.exception))
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
        self.apply_114_migration(repo)
        verified = ph_merge_update.verify_payload(repo)
        self.assertTrue(verified["ok"])

        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        self.assertEqual(result["from"], "1.1.9")
        written = json.loads((repo / ".agents/ph.json").read_text(encoding="utf-8"))
        self.assertEqual(written["template_version"], CURRENT)
        self.assertNotIn("ph-docs-sync", written["skills"]["required_names"])
        self.assertEqual(written["adapter_mode"], "portable")
        # the 1.1.10 hop installed docs-sync, but the 1.1.14 retirement item
        # removed it again from the managed install (mirrors included)
        self.assertFalse((repo / ".agents/skills/ph-docs-sync").exists())
        self.assertFalse((repo / ".claude/skills/ph-docs-sync").exists())
        self.assertEqual(wiki.read_bytes(), wiki_bytes)
        self.assertEqual(governance.read_bytes(), governance_bytes)
        # the upgraded repo's own installer validates the fourteen-skill layout
        installed = repo / ".agents/skills/ph-init/scripts/ph_init.py"
        proc = run([sys.executable, str(installed), "check", "--repo", str(repo)])
        self.assertIn("status=ok", proc.stdout, proc.stdout)
        self.assertIn(".agents/skills/ph-analyze/SKILL.md", proc.stdout)
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

    def test_retired_intent_verify_blocks_verify_while_live(self):
        # Marking retire-legacy-skills applied while a retired
        # ph-intent-verify skill stays in place must not pass verify: since
        # 1.1.14 the retirement item requires the skill to be gone from the
        # managed install instead of matching a release scaffold copy.
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
        (dest / "report.md").write_text("# report\nretire-legacy-skills applied\n", encoding="utf-8")
        # applied intent-to-spec carries its on-disk artifacts with it
        ph_merge_update.migrate_intents_payload(repo, True)

        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("retired skills still live", str(ctx.exception))
        self.assertIn("ph-intent-verify", str(ctx.exception))
        # a failing verify never advances the version or rewrites the state
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(
            json.loads((dest / "state.json").read_text())["status"], "in_progress"
        )
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

        # Executing the retirement item removes the retired skill (custom
        # content included) and unblocks verify and finalize; the release
        # contract never lists the retired name again.
        self.apply_114_migration(repo)
        verified = ph_merge_update.verify_payload(repo)
        self.assertTrue(verified["ok"])
        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("ph-intent-verify", written["skills"]["required_names"])
        self.assertFalse(custom.exists())
        installed_check = run([sys.executable,
                               str(repo / ".agents/skills/ph-init/scripts/ph_init.py"),
                               "check", "--repo", str(repo)])
        self.assertIn("status=ok", installed_check.stdout, installed_check.stdout)

    def test_retired_sure_skill_is_not_a_release_skill(self):
        # ph-sure never shipped and 1.1.14 retires it: a live same-named
        # directory is retired project content, inspect stays read-only and
        # does not name it as a scaffold conflict, and the executed
        # retirement item removes it together with the other retired skills.
        self.install_receipt()
        repo = self.fixture_at_119()
        custom = repo / ".agents/skills/ph-sure/SKILL.md"
        custom_body = (
            "---\nname: ph-sure\ndescription: team custom wrap-up checks\n---\n"
            "# our own sure skill\n项目自建收尾核查，升级按退役语义处理。\n"
        )
        custom.parent.mkdir(parents=True, exist_ok=True)
        custom.write_text(custom_body, encoding="utf-8")
        before = self.tree_snapshot(repo)

        inspected = ph_merge_update.inspect_payload(repo)
        self.assertEqual(inspected["from"], "1.1.9")
        self.assertEqual(inspected["to"], CURRENT)
        self.assertEqual(inspected["profile"], "1.1.0-current-names")
        self.assertFalse(
            any("ph-sure" in conflict for conflict in inspected["conflicts"]),
            inspected["conflicts"],
        )
        # inspect stays read-only and the custom body survives byte-for-byte
        self.assertEqual(self.tree_snapshot(repo), before)
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

    def test_retired_sure_skill_blocks_verify_while_live(self):
        # Marking retire-legacy-skills applied while a live ph-sure (the
        # unshipped draft sibling) stays in place must not pass verify: the
        # retirement item requires it gone from the managed install.
        self.install_receipt()
        repo = self.fixture_at_119()
        custom = repo / ".agents/skills/ph-sure/SKILL.md"
        custom_body = "---\nname: ph-sure\ndescription: drift\n---\n# drifted sure skill\n"
        custom.parent.mkdir(parents=True, exist_ok=True)
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
        (dest / "report.md").write_text("# report\nretire-legacy-skills applied\n", encoding="utf-8")
        # applied intent-to-spec carries its on-disk artifacts with it
        ph_merge_update.migrate_intents_payload(repo, True)

        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.verify_payload(repo)
        self.assertIn("retired skills still live", str(ctx.exception))
        self.assertIn("ph-sure", str(ctx.exception))
        # a failing verify never advances the version or rewrites the state
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(
            json.loads((dest / "state.json").read_text())["status"], "in_progress"
        )
        self.assertEqual(custom.read_text(encoding="utf-8"), custom_body)

        # Executing the retirement item removes the live ph-sure and
        # unblocks verify and finalize; required_names never gains it.
        self.apply_114_migration(repo)
        verified = ph_merge_update.verify_payload(repo)
        self.assertTrue(verified["ok"])
        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("ph-sure", written["skills"]["required_names"])
        self.assertFalse(custom.exists())
        installed_check = run([sys.executable,
                               str(repo / ".agents/skills/ph-init/scripts/ph_init.py"),
                               "check", "--repo", str(repo)])
        self.assertIn("status=ok", installed_check.stdout, installed_check.stdout)

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
        historical_names = sorted(BASE_SKILLS + NEW_INTENT + ["ph-merge-update"])
        self.assertEqual(
            sorted(i["name"] for i in inspected["codex_retirement"]["retirable"]),
            historical_names,
        )
        self.assertEqual(inspected["codex_retirement"]["blocked"], [])

        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        self.apply_114_migration(repo)
        verified = ph_merge_update.verify_payload(repo)
        self.assertTrue(verified["ok"])
        # the simulated Agent phase already archived the whole .codex tree
        self.assertEqual(verified["codex_retirement"]["retirable"], [])
        result = ph_merge_update.finalize_payload(repo, True)
        self.assertTrue(result["complete"])
        archived = {i["name"] for i in result["retired_codex"]}
        self.assertEqual(archived, set())
        self.assertTrue(all(i["result"] == "archived" for i in result["retired_codex"]))
        written = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(written["template_version"], CURRENT)
        self.assertNotIn("schema_version", written)
        self.assertNotIn("codex_skills", written["adapters"])
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        # the simulated Agent phase removed the whole .codex tree during the
        # tool-neutral retirement, so finalize has no mirror left to archive
        self.assertFalse((repo / ".codex").exists())
        self.assertIsNone(self.archived_codex_dir(repo))

    def test_codex_symlink_leftovers_archive_and_finalize_is_idempotent(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8", mode="symlink")
        my_tool = repo / ".codex" / "skills" / "my-tool"
        my_tool.mkdir(parents=True, exist_ok=True)
        (my_tool / "SKILL.md").write_text("# my-tool\n", encoding="utf-8")
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        self.apply_speckit_with_retire_na(repo)

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
            if name == "ph-memory-learning":
                # learning never existed in a 1.1.8 install: no historical
                # codex mirror ever pointed at it, so there is no record
                self.assertFalse((repo / ".codex" / "skills" / name).exists())
                continue
            if name == "ph-human":
                # ph-human arrives in 1.2.2: a 1.1.8 install has no such
                # skill, so no historical codex mirror or record exists
                self.assertFalse((repo / ".codex" / "skills" / name).exists())
                continue
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
            sorted(p.name for p in (repo / ".agents" / "project-harness" / "archive" / "legacy-backup").iterdir()),
            [archived_dir.parent.name],
            "a repeated finalize must not create a second archive directory",
        )

    def test_codex_portable_drift_blocks_and_stays_in_place(self):
        self.install_receipt()
        repo = self.fixture_at_version("1.1.8")  # no commit: no pre-upgrade git snapshot exists
        drifted = repo / ".codex" / "skills" / "ph-intent-new" / "SKILL.md"
        drifted.write_bytes(drifted.read_bytes() + b"\nuser customization\n")
        self.write_state(repo, from_version="1.1.8", items=CHAIN_118)
        self.apply_speckit_with_retire_na(repo)
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
        self.apply_speckit_with_retire_na(repo)

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
                self.apply_speckit_with_retire_na(repo)
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
        self.apply_speckit_with_retire_na(repo)
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
        self.apply_speckit_with_retire_na(repo)
        # Simulate a crash after the retirement pass but before sync/write.
        first_pass = ph_merge_update.retire_codex_adapters(repo)
        # The .codex mirror predates the spec-kit install, so the archived
        # adapters are exactly the historical PH skills, not the four-name
        # release contract of 1.1.14.
        historical = set(BASE_SKILLS + NEW_INTENT + ["ph-merge-update"])
        self.assertEqual({i["name"] for i in first_pass}, historical)
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
        self.apply_speckit_with_retire_na(repo)
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
        # Symlink adapters exist for every seeded name regardless of when the
        # canonical target appeared, so the audit covers the historical PH
        # skills plus the ten spec-kit skills the speckit item installed.
        self.assertEqual(
            set(audited),
            set(BASE_SKILLS + NEW_INTENT + ["ph-merge-update"])
            | set(ph_init.SPECKIT_SKILL_NAMES),
        )
        for name, item in audited.items():
            self.assertEqual(
                item["dest"],
                f".agents/project-harness/archive/legacy-backup/{archived_dir.parent.name}/codex-skills/{name}",
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
        names = list(ph_init.ALL_REQUIRED_SKILL_NAMES)
        self.write_manifest(repo, version=CURRENT, names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.seed_speckit(repo)
        self.write_intent_layout(repo)
        # A repo already at CURRENT must not keep live codex adapters around.
        self.seed_adapters(repo, "portable", names, codex=True)
        self.seed_gitignore(repo)
        with self.assertRaises(ph_init.PHError) as ctx:
            ph_merge_update.inspect_payload(repo)
        self.assertIn("still live", str(ctx.exception))
        with self.assertRaises(ph_init.PHError):
            ph_merge_update.finalize_payload(repo, True)
        self.assertEqual(
            ph_merge_update.codex_leftover_names(repo),
            sorted(ph_init.ALL_REQUIRED_SKILL_NAMES),
        )
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
            sorted(data["codex_retirement"]["retirable"]), sorted(TARGET_SKILLS + list(ph_init.SPECKIT_SKILL_NAMES))
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
        self.assertEqual(written["skills"]["required_names"], list(ph_init.ALL_REQUIRED_SKILL_NAMES))
        self.assertEqual(json.loads((self.update_dir(repo) / "state.json").read_text())["status"], "complete")
        self.assertIn("keep-me", (repo / ".agents" / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(ph_merge_update.codex_leftover_names(repo), [])
        self.assertIsNotNone(self.archived_codex_dir(repo))

        # complete rerun must re-verify live files
        constraint = repo / ".agents/project-harness/constraints/工程规范/Git规范.md"
        original = constraint.read_bytes()
        retained = repo / "git-rule-test-backup"
        constraint.rename(retained)
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("Git规范.md", err)

        # versions written, state not complete -> recover
        retained.rename(constraint)
        self.assertEqual(constraint.read_bytes(), original)
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
        self.assertEqual(cand["skills"]["required_names"], list(ph_init.ALL_REQUIRED_SKILL_NAMES))
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
        for name in names:
            if not (repo / ".agents" / "skills" / name / "SKILL.md").is_file():
                self.write_skill(repo, name)
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
        names = list(ph_init.ALL_REQUIRED_SKILL_NAMES)
        self.write_manifest(repo, version=CURRENT, names=names)
        self.write_agents(repo)
        self.seed_target_skills(repo)
        self.seed_speckit(repo)
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
        for name in NEW_INTENT:
            self.write_skill(repo, name)
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
        (repo / ".agents/project-harness/constitution.md").write_text("# [PROJECT_NAME] Constitution\n", encoding="utf-8")
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("skeleton", err)

    def test_verify_blocks_unresolvable_active_feature_pointer(self):
        repo = self.fixture_110_current()
        self.install_receipt()
        self.write_state(repo)
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 0, err)
        runtime = repo / ".agents" / "project-harness" / "runtime"
        feature_json = runtime / "feature.json"
        # a pointer still at the retired root specs/ tree resolves nowhere
        feature_json.write_text(json.dumps({"feature_directory": "specs/001-gone"}) + "\n", encoding="utf-8")
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 2)
        self.assertIn("feature.json", err)
        self.assertIn("001-gone", err)
        # an adapted pointer at the home specs root passes
        feature_json.write_text(
            json.dumps({"feature_directory": ".agents/project-harness/specs/001-live"}) + "\n",
            encoding="utf-8",
        )
        (runtime.parent / "specs" / "001-live").mkdir(parents=True, exist_ok=True)
        code, _out, err = self.invoke("verify", "--repo", str(repo))
        self.assertEqual(code, 0, err)

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
