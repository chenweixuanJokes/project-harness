"""Explicit documentation-only fixture for structural completion tests.

This fixture is not evidence that an agent completed a real project. The test
project has no runnable application; its adopted policies are tested separately
from real-project semantic acceptance.
"""
import hashlib
import json
from pathlib import Path


def complete_documentation_project(repo: Path, release: Path) -> None:
    home = repo / '.agents/project-harness'
    root = home / 'constraints'
    source = release / 'assets/scaffold/.agents/project-harness/constraints'
    rows = {}
    for template in sorted(source.rglob('*.md')):
        relative = template.relative_to(source)
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if template.name.startswith('_'):
            if not path.exists():
                path.write_bytes(template.read_bytes())
            continue
        original = path.read_text(encoding='utf-8') if path.exists() else ''
        heading = template.read_text(encoding='utf-8').splitlines()[0]
        usage = next(line for line in template.read_text(encoding='utf-8').splitlines() if line.startswith('使用时机：'))
        is_app = relative.parts[0] in {'前端规范', '后端规范', '测试规范'}
        if is_app:
            body = ('本测试仓库仅验证 PH 文档迁移，没有应用代码、运行依赖或服务。'
                    '本篇应用实现与执行命令不适用；新增应用时重新核验。'
                    '未执行应用测试，不声称测试通过。')
            status = 'not_applicable'
        else:
            body = {
                'Git规范.md': '本测试仓库保留当前分支。交付指合入主分支；提交、推送、合并及清理仍需授权。不得 stash，不因检查失败降低门禁。',
                '安全规范.md': '本测试仓库仅使用虚构数据，不配置生产连接，不保存秘密，不访问生产服务。',
                '文档治理规范.md': '本测试仓库保持基础文件路径，允许更新正文及新增专题。旧有效定制继续生效；资料变更记录来源，未知事实不伪装已核验。',
                '对用户提问规范.md': '只询问无法查证且需要用户决定的问题；有合适问答工具时实际调用。提交问题不等于获得回答，获得回答不等于授权其它操作。',
            }[template.name]
            status = 'adopted'
        custom = []
        for line in original.splitlines():
            if '升级矩阵注入的后端约束：' in line or '本节是项目自定义治理规则：' in line:
                custom.append(line)
        text = f'{heading}\n\nLast verified: 2026-09-21\n\n{usage}\n\n{body}\n'
        if custom:
            text += '\n## 保留的项目定制\n\n' + '\n'.join(custom) + '\n'
        if template.name == '对用户提问规范.md':
            text = template.read_text(encoding='utf-8')
        if original and custom:
            archive = home / 'archive/content-before-fill' / relative
            archive.parent.mkdir(parents=True, exist_ok=True)
            if not archive.exists():
                archive.write_text(original, encoding='utf-8')
        path.write_text(text, encoding='utf-8')
        rows[relative.as_posix()] = {
            'status': status, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'evidence': 'tests/content_fixture.py：明确构造的无应用文档项目及保留定制',
            'reason': '结构性测试采用的固定项目场景，不作为真实项目语义验收证据',
            'semantic_review': True,
        }
    home.mkdir(parents=True, exist_ok=True)
    (home / 'init-report.json').write_text(json.dumps({
        'format': 'ph.content/1', 'project_kind': 'upgrade', 'documents': rows,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
