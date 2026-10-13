"""Release allocation, immutable identities and partial-upload recovery."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.auto_release import plan, packages, publish


class FakeGitHub:
    def __init__(self):
        self.tag = None
        self.release = None
        self.assets = []
        self.writes = []
        self.fail_upload = False

    def tag_commit(self, tag):
        return self.tag

    def request(self, method, path, data=None, **kwargs):
        if method == 'GET':
            return self.assets if '/assets?' in path else self.release
        self.writes.append((method, path))
        if path == '/git/refs':
            self.tag = data['sha']
        elif path == '/releases':
            self.release = dict(data, id=1, html_url='https://example.invalid/release')
            return self.release
        elif '/assets?' in path:
            if self.fail_upload:
                self.fail_upload = False
                raise RuntimeError('upload interrupted')
            self.assets.append({'name': path.split('name=')[1], 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()})
        elif method == 'PATCH':
            self.release.update(data)
            return self.release


class AutoReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('commit', '--allow-empty', '-qm', 'initial')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True, encoding='utf-8', stderr=subprocess.DEVNULL).strip()

    def test_patch_default_explicit_version_and_existing_tag(self):
        self.assertEqual(plan(self.root)[0], 'v0.1.0')
        self.git('tag', 'v0.6.2')
        self.git('commit', '--allow-empty', '-qm', 'normal change')
        self.assertEqual(plan(self.root)[0], 'v0.6.3')
        self.git('commit', '--allow-empty', '-qm', 'explicit release\n\nRelease-Version: 0.7.0')
        self.assertEqual(plan(self.root)[0], 'v0.7.0')
        self.git('tag', '-a', 'v0.7.0', '-m', 'release')
        self.assertEqual(plan(self.root)[0], 'v0.7.0')

    def test_bad_duplicate_and_older_explicit_versions(self):
        self.git('tag', 'v0.6.2')
        for trailer in ('0.6.2', '0.5.9', '01.7.0', 'v0.7.0', '0.7.0\nRelease-Version: 0.8.0', 'anything'):
            self.git('commit', '--allow-empty', '-qm', 'change\n\nRelease-Version: ' + trailer)
            with self.subTest(trailer=trailer), self.assertRaises(ValueError):
                plan(self.root)

    def test_old_commit_and_conflicting_tag_rejected(self):
        old = self.git('rev-parse', 'HEAD')
        self.git('commit', '--allow-empty', '-qm', 'newer')
        self.git('tag', 'v0.6.3')
        self.git('checkout', '--detach', old)
        with self.assertRaises(subprocess.CalledProcessError):
            plan(self.root)
        self.git('tag', 'v0.6.2')
        with self.assertRaises(ValueError):
            plan(self.root)

    def make_packages(self):
        commit = self.git('rev-parse', 'HEAD')
        tag = 'v0.6.3'
        self.git('tag', tag)
        directory = self.root / 'dist'
        directory.mkdir()
        for suffix in ('linux-amd64.tar.gz', 'windows-amd64.zip'):
            path = directory / f'smooth-caddy-0.6.3.{commit[:8]}-{suffix}'
            path.write_bytes(b'synthetic archive ' + suffix.encode())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.with_name(path.name + '.sha256').write_text(f'{digest}  {path.name}\n')
        return directory, tag, commit

    def test_both_platforms_and_checksums_required_before_remote_writes(self):
        directory, tag, commit = self.make_packages()
        self.assertEqual(len(packages(directory, tag, commit)), 4)
        archive = next(directory.glob('*.zip'))
        archive.write_bytes(b'corrupt')
        api = FakeGitHub()
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            publish(api, self.root, directory, tag, commit, 'owner/repo')
        self.assertFalse(api.writes)
        archive.unlink()
        with self.assertRaisesRegex(ValueError, 'exactly'):
            packages(directory, tag, commit)

    def test_publish_and_retry_without_overwriting_published_assets(self):
        directory, tag, commit = self.make_packages()
        api = FakeGitHub()
        api.fail_upload = True
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            publish(api, self.root, directory, tag, commit, 'owner/repo')
        self.assertTrue(api.release['draft'])
        self.assertEqual(api.tag, commit)
        publish(api, self.root, directory, tag, commit, 'owner/repo')
        self.assertFalse(api.release['draft'])
        self.assertEqual(len(api.assets), 4)
        writes = list(api.writes)
        publish(api, self.root, directory, tag, commit, 'owner/repo')
        self.assertEqual(api.writes, writes)

    def test_reuse_partial_upload_and_reject_different_assets_or_tag(self):
        directory, tag, commit = self.make_packages()
        api = FakeGitHub()
        publish(api, self.root, directory, tag, commit, 'owner/repo')
        api.release['draft'] = True
        api.assets.pop()
        publish(api, self.root, directory, tag, commit, 'owner/repo')
        self.assertEqual(len(api.assets), 4)
        api.release['draft'] = True
        api.assets[0]['digest'] = 'different'
        with self.assertRaisesRegex(ValueError, 'asset differs'):
            publish(api, self.root, directory, tag, commit, 'owner/repo')
        api.tag = '0' * 40
        with self.assertRaisesRegex(ValueError, 'existing tag'):
            publish(api, self.root, directory, tag, commit, 'owner/repo')
