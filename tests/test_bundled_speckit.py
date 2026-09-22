import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ph_speckit
import ph_init


class BundledSpecKitTests(unittest.TestCase):
    def test_install_and_retry_without_generator_or_cache(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ph_speckit, 'run_checked', side_effect=AssertionError('external generation forbidden')):
            repo = Path(tmp)
            (repo / '.agents').mkdir()
            (repo / '.agents/ph.json').write_text('{}')
            prepared = ph_speckit.cmd_prepare(argparse.Namespace(cache=str(repo / 'absent-cache'), force=True))
            self.assertEqual(prepared['source'], 'ph-bundle')
            for _ in range(2):
                result = ph_speckit.cmd_install(repo, True, str(repo / 'absent-cache'))
                self.assertFalse(result['blocked'], result)
            self.assertFalse((repo / 'absent-cache').exists())
            self.assertTrue((repo / '.agents/skills/ph-implement/SKILL.md').is_file())

    def test_missing_or_damaged_bundle_fails(self):
        original = ph_speckit.SOURCE_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(original / 'assets', root / 'assets')
            shutil.copy2(original / 'speckit.json', root / 'speckit.json')
            with patch.object(ph_speckit, 'SOURCE_ROOT', root):
                target = root / 'assets/scaffold/.agents/skills/ph-plan/SKILL.md'
                target.write_text(target.read_text() + '\ncorrupted\n')
                with self.assertRaises(ph_init.PHError):
                    ph_speckit.bundled_source()

    def test_installer_payload_includes_bundle_manifest(self):
        self.assertIn(ph_init.skill_root() / 'assets/speckit-bundle.json', ph_init.ph_init_payload_files())

    def test_project_test_contracts(self):
        root = ph_speckit.bundled_source()
        for core, rel in ph_speckit.SKILL_BASELINE_RELS.items():
            text = (root / rel).read_text()
            self.assertIn('PH 项目测试规范联动', text, core)
            self.assertIn('不自动调用其它技能', text, core)
            self.assertNotIn('Tests are OPTIONAL', text, core)
        implement = (root / ph_speckit.SKILL_BASELINE_RELS['implement']).read_text()
        for evidence in ('verification.md', '未执行', '无关既有失败', '代码及环境状态', '合入前回归'):
            self.assertIn(evidence, implement)
        tasks = (root / ph_speckit.SKILL_BASELINE_RELS['tasks']).read_text()
        self.assertIn('不以用户是否明确要求测试', tasks)


if __name__ == '__main__':
    unittest.main()
