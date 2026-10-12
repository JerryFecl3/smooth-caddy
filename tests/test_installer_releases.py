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
        self.functions, self.commands = self.script.split('\ncase "${1:-}" in', 1)

    def run_shell(self, command, *args, input=None):
        # Override fixed production roots after loading definitions; no service calls.
        script = self.functions + '\nCONFIG=$1\nRELEASES=$CONFIG/releases\nshift\n' + command
        return subprocess.run(['sh', '-c', script, 'test', str(self.config), *args],
                              capture_output=True, text=True, input=input, timeout=10)

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

    def test_node_takeover_confirmation_and_ssh_bypass(self):
        identity = self.config / 'node-id'
        old, new = 'a' * 32, 'b' * 32
        command = 'STATE=$CONFIG\nnode_id=$1\ncheck_node_identity "${2:-}"'
        # No prior installation and same identity need no confirmation.
        for present in (False, True):
            if present:
                identity.write_text(new)
            result = self.run_shell(command, new, input='')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
        identity.write_text(old)
        for answer in ('n\n', '\n', '', 'unexpected\n'):
            with self.subTest(answer=answer):
                result = self.run_shell(command, new, input=answer)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('[y/N]', result.stderr)
                self.assertEqual(identity.read_text(), old)
        for answer in ('y\n', 'yes\n', 'Y\n'):
            result = self.run_shell(command, new, input=answer)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(old, result.stderr)
            self.assertIn(new, result.stderr)
        # SSH is noninteractive and does not consume input or print a prompt.
        result = self.run_shell(command, new, '--take-over', input='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(identity.read_text(), old)  # Written only by install, after checks.
        result = self.run_shell(command, new, '--unknown', input='y\n')
        self.assertNotEqual(result.returncode, 0)

    def test_run_package_forwards_explicit_takeover_only(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.network.releases import build_package, HERE
        node = SimpleNamespace(id='b' * 32, platform='debian_13', arch='amd64')
        original_read = Path.read_text
        def read_template(path, *args, **kwargs):
            if path == HERE / 'manage.sh':
                return '#!/bin/sh\nset -eu\nprintf "option=%s\\n" "${3:-}"\n'
            return original_read(path, *args, **kwargs)
        # Exercise the real .run extraction/checksum/header with a harmless installer.
        with patch.object(Path, 'read_text', read_template):
            package = build_package(node, '20261012-120000-0123abcd', 'v2.11.7', {'caddy.json': b'{}'})
        path = self.config / 'package.run'
        path.write_bytes(package)
        for args, expected in (([], 'option=\n'), (['--take-over'], 'option=--take-over\n')):
            result = subprocess.run(['sh', str(path), *args], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, expected)
        rejected = subprocess.run(['sh', str(path), '--unknown'], capture_output=True, timeout=10)
        self.assertNotEqual(rejected.returncode, 0)
