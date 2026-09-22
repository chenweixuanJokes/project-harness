import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ph_layout


class ConstraintCompletionTests(unittest.TestCase):
    def test_scaffold_is_not_completed_content(self):
        result = ph_layout.verify_constraints(ROOT / 'assets/scaffold', ROOT)
        self.assertFalse(result['ok'])
        self.assertTrue(any('report' in p for p in result['problems']))

    def test_missing_tree_cannot_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = ph_layout.verify_constraints(Path(tmp), ROOT)
            self.assertFalse(result['ok'])
            self.assertTrue(any('missing' in p for p in result['problems']))

    def test_completed_fixture_and_stale_evidence(self):
        from content_fixture import complete_documentation_project
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            complete_documentation_project(repo, ROOT)
            self.assertTrue(ph_layout.verify_constraints(repo, ROOT)['ok'])
            path = repo / ph_layout.CONSTRAINTS / '工程规范/Git规范.md'
            path.write_text(path.read_text() + '\n未复核的新规则。\n')
            self.assertFalse(ph_layout.verify_constraints(repo, ROOT)['ok'])

    def test_bullet_placeholder_and_extra_document_cannot_pass(self):
        from content_fixture import complete_documentation_project
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            complete_documentation_project(repo, ROOT)
            path = repo / ph_layout.CONSTRAINTS / '工程规范/Git规范.md'
            path.write_text(path.read_text() + '\n- 基线：<填写：分支>\n')
            report_path = repo / ph_layout.HOME / 'init-report.json'
            report = json.loads(report_path.read_text())
            report['documents']['工程规范/Git规范.md']['sha256'] = ph_layout.digest(path.read_bytes())
            report_path.write_text(json.dumps(report))
            self.assertTrue(any('unfilled' in p for p in ph_layout.verify_constraints(repo, ROOT)['problems']))
            extra = path.parent / '发布规范.md'
            extra.write_text('# 发布规范\n使用时机：发布前。\n')
            self.assertTrue(any('发布规范.md' in p for p in ph_layout.verify_constraints(repo, ROOT)['problems']))
            self.assertFalse(ph_layout.verify_constraints(repo, repo / 'missing-release')['ok'])

    def test_refresh_preserves_principles_and_rejects_drift(self):
        import ph_speckit
        from content_fixture import complete_documentation_project
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            complete_documentation_project(repo, ROOT)
            path = repo / ph_layout.CONSTITUTION
            original = '# 原则\n不可丢失。\n\n' + ph_speckit.PH_OVERRIDE_MARKER + ' test -->\n## 约束导航\n\n- [旧规则](constraints/旧规则.md)\n  使用时机：旧描述\n\n## 项目备注\n保留这段。\n'
            path.write_text(original)
            sha = ph_layout.digest(path.read_bytes())
            ph_speckit.refresh_live_navigation(repo, sha, True)
            self.assertIn('不可丢失。', path.read_text())
            self.assertIn('保留这段。', path.read_text())
            self.assertNotIn('constraints/旧规则.md', path.read_text())
            with self.assertRaises(ph_speckit.PHError):
                ph_speckit.refresh_live_navigation(repo, sha, True)

    def test_navigation_groups_records_but_not_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            base = repo / ph_layout.CONSTRAINTS
            (base / '架构决策').mkdir(parents=True)
            (base / '架构决策/0001-storage.md').write_text('# Storage')
            (base / '工程规范').mkdir()
            (base / '工程规范/Git规范.md').write_text('# Git\n使用时机：提交时读取。')
            entries = ph_layout.constraint_entries(repo)
            self.assertEqual({p.relative_to(base).as_posix() for p in entries}, {'架构决策', '工程规范/Git规范.md'})


if __name__ == '__main__':
    unittest.main()
