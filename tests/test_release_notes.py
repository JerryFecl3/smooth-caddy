import subprocess
import tempfile
import unittest
from pathlib import Path
from tools.release_notes import generate


class ReleaseNotesTests(unittest.TestCase):
    def test_tag_history_and_commit_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, text=True, encoding='utf-8').strip()
            git('init', '-q')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            git('commit', '--allow-empty', '-qm', '首次发布')
            git('tag', 'v0.1.0')
            self.assertIn('首次发布', generate(root, 'v0.1.0', 'owner/repo'))
            git('commit', '--allow-empty', '-qm', '新增证书 OU', '-m', '已有证书不自动重签。')
            git('tag', '-a', 'v0.1.1', '-m', 'version')
            git('commit', '--allow-empty', '-qm', '后续改动')
            git('tag', 'v0.1.2')
            git('checkout', '-qb', 'unrelated', 'v0.1.0')
            git('commit', '--allow-empty', '-qm', '其他分支改动')
            git('tag', 'v0.1.9')
            notes = generate(root, 'v0.1.1', 'owner/repo')
            self.assertIn('新增证书 OU', notes)
            self.assertIn('已有证书不自动重签。', notes)
            self.assertIn('/compare/v0.1.0...v0.1.1', notes)
            for excluded in ('首次发布', '后续改动', '其他分支改动'):
                self.assertNotIn(excluded, notes)
            with self.assertRaises(ValueError):
                generate(root, 'invalid', 'owner/repo')
