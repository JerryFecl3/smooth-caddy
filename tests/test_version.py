import subprocess
import tempfile
import unittest
from pathlib import Path
from app.version import git_release

class VersionTests(unittest.TestCase):
    def test_tagged_clean_commit_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def git(*args):return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()
            git('init');git('config','user.name','Test');git('config','user.email','test@example.invalid')
            (root/'source').write_text('source');git('add','.');git('commit','-m','initial')
            with self.assertRaises(ValueError):git_release(root)
            git('tag','v0.1.0');result=git_release(root,'v0.1.0')
            self.assertEqual(result['version'],'0.1.0.'+git('rev-parse','HEAD')[:8])
            with self.assertRaises(ValueError):git_release(root,'v0.2.0')
            (root/'source').write_text('changed')
            with self.assertRaises(ValueError):git_release(root)
