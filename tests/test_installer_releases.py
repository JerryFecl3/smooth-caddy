"""Execute release lifecycle shell code in an isolated, unprivileged directory."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipIf(os.name == 'nt', 'Target release symlinks and shell behavior require Linux')
class InstallerReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name)
        self.releases = self.config / 'releases'
        (self.releases / '.objects').mkdir(parents=True)
        self.script = Path('app/network/templates/manage.sh').read_text().replace('@PLATFORM@', 'debian')
        self.functions, self.commands = self.script.split('case "${1:-}" in', 1)

    def run_shell(self, command, *args):
        # Override fixed production roots after loading definitions; no service calls.
        script = self.functions + '\nCONFIG=$1\nRELEASES=$CONFIG/releases\nshift\n' + command
        return subprocess.run(['sh', '-c', script, 'test', str(self.config), *args],
                              capture_output=True, text=True, timeout=10)

    def add_release(self, name, successful=True):
        target = self.releases / '.objects' / (name + '-123')
        target.mkdir()
        (target / 'caddy.json').write_text('{}')
        if successful:
            (target / '.success').touch()
        (self.releases / name).symlink_to(target.relative_to(self.releases))
        return target

    def test_name_validation_legacy_current_and_unsafe(self):
        for name in ('20261011-123456', '20261011-123456-0123abcd'):
            with self.subTest(name=name):
                result = self.run_shell('valid_release "$1"', name)
                self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('', '../20261011-123456', '20261011-123456-abcd',
                     '20261011-123456-0123ABCD', '20261011-123456-0123abcd/..',
                     '20261011-123456\n../../outside', '20261011-123456\n'):
            with self.subTest(name=name):
                result = self.run_shell('valid_release "$1"', name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Invalid release name', result.stderr)

    def test_list_prune_and_cleanup_preserve_referenced_materials(self):
        # Interleave legacy/current identities; keep an older release active.
        names = [f'20261011-12000{i}' + ('-0123abcd' if i % 2 else '') for i in range(8)]
        objects = {name: self.add_release(name) for name in names}
        failed = '20261011-130000-deadbeef'
        failed_object = self.add_release(failed, successful=False)
        (self.config / 'current').symlink_to('releases/' + names[0])
        orphan = self.releases / '.objects' / 'abandoned'
        orphan.mkdir()
        listed = self.run_shell('case "${1:-}" in' + self.commands, 'list')
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(listed.stdout.splitlines(),
                         [name + ' successful' for name in names] + [failed + ' failed-or-unconfirmed'])
        result = self.run_shell('prune\ncleanup_objects')
        self.assertEqual(result.returncode, 0, result.stderr)
        retained = {names[0], *names[-4:]}
        for name, target in objects.items():
            self.assertEqual((self.releases / name).exists(), name in retained, name)
            self.assertEqual(target.exists(), name in retained, name)
        self.assertTrue(failed_object.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue((self.config / 'current' / 'caddy.json').is_file())
        selected = self.run_shell('valid_release "$1"\nselect_release "$1"', names[-1])
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual((self.config / 'current').resolve(), objects[names[-1]])
