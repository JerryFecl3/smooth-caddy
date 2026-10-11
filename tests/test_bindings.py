from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from cryptography import x509
from textual.widgets import TextArea
from app.network.application import Application
from app.network.models import Configuration, Listen, Node, Region, binding_addresses, configuration_errors
from app.network.generator import generate
from app.network.releases import sha
from tests.ui_helpers import ReadyTerminal


class BindingTests(unittest.TestCase):
    def test_address_parsing_and_normalization(self):
        self.assertEqual(binding_addresses([' 0.0.0.0 ', '::', '', '::0', '::ffff:192.0.2.1', '192.0.2.1']),
                         ['0.0.0.0', '::', '192.0.2.1'])
        for values in ([], ['host.test'], ['224.0.0.1'], ['ff02::1'], ['fe80::1%eth0'], ['127.0.0.1:80']):
            with self.subTest(values=values), self.assertRaises(ValueError): binding_addresses(values)

    def test_conflicts_include_both_regions_and_protocols(self):
        regions = [Region('a', '内网'), Region('b', '外网', ['8080', '9443', '443'])]
        node = Node('n', 'Node', platform='debian_13', arch='amd64', ssh_hops=[['192.0.2.1']])
        config = Configuration(regions=regions, nodes=[node])
        for first, second, conflict in [('0.0.0.0', '192.0.2.1', True), ('::', '::1', True),
                                        ('0.0.0.0', '::', False), ('192.0.2.1', '192.0.2.2', False),
                                        ('2001:db8::1', '2001:db8:0:0::1', True)]:
            with self.subTest(first=first, second=second):
                node.areas = {'a': Listen(True, [first]), 'b': Listen(True, [second])}
                errors = configuration_errors(config)
                self.assertEqual(bool(errors), conflict)
                if conflict:
                    a = errors[('nodes', 'n', 'area:a')]
                    self.assertEqual(a, errors[('nodes', 'n', 'area:b')])
                    self.assertIn('内网 HTTPS', a[0]); self.assertIn('外网 中继 HTTPS', a[0])
                node.areas['b'].enabled = False
                self.assertEqual(configuration_errors(config), {})
        node.areas = {'a': Listen(True, ['0.0.0.0', '192.0.2.1'])}
        self.assertIn(('nodes', 'n', 'area:a'), configuration_errors(config))
        node.areas = {'a': Listen(True, ['::', '0.0.0.0'])}
        self.assertFalse(configuration_errors(config))
        node.areas['a'].overrides = ['443', None, None]
        self.assertIn('HTTP', configuration_errors(config)[('nodes', 'n', 'area:a')][0])

    def test_generation_and_v5_database_metadata_migration(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test'); app.certificates.initialize('Test')
            rid = app.create('regions', 'LAN'); nid = app.create('nodes', 'Node')
            app.create('sites', 'Web')
            cfg = app.snapshot(); node = cfg.nodes[0]
            node.platform = 'debian_13'; node.arch = 'amd64'; node.ssh_hops = [['192.0.2.1']]
            node.areas[rid] = Listen(True, ['0.0.0.0', '::'])
            cfg.sites[0].domain = 'test.example'; cfg.sites[0].source = 'http://127.0.0.1:9000'; cfg.sites[0].areas[rid] = 'https'
            materials = generate(cfg, app.certificates, 'test')[nid]
            servers = json.loads(materials['caddy.json'])['apps']['http']['servers']
            for kind, port in [('http', '80'), ('https', '443'), ('relay', '8443')]:
                self.assertEqual(servers[rid+'-'+kind]['listen'], ['tcp4/0.0.0.0:'+port, 'tcp6/[::]:'+port])
            cert = x509.load_pem_x509_certificate(materials[f'certificates/relay-{nid}-{rid}.pem'])
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            self.assertEqual(san.get_values_for_type(x509.IPAddress), [])
            self.assertEqual(san.get_values_for_type(x509.DNSName), ['relay.smooth-caddy.internal'])
            node.areas[rid].ips = ['192.0.2.1', '2001:db8::1']
            materials = generate(cfg, app.certificates, 'test')[nid]
            cert = x509.load_pem_x509_certificate(materials[f'certificates/relay-{nid}-{rid}.pem'])
            self.assertEqual([str(ip) for ip in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)], node.areas[rid].ips)
            node.areas[rid].ips = ['192.0.2.1']
            app.save_configuration(cfg)
            batch = app.releases.create(); folder = app.releases.directory(batch)
            metadata = json.loads((folder/'metadata.json').read_bytes())
            self.assertEqual(metadata['format'], 5)
            old = deepcopy(metadata['configuration'])
            old['nodes'][0]['areas'][rid]['ip'] = old['nodes'][0]['areas'][rid].pop('ips')[0]
            metadata['format'] = 4; metadata['configuration'] = old
            payload = json.dumps(metadata).encode(); (folder/'metadata.json').write_bytes(payload)
            batch.metadata_sha256 = sha(payload); app.releases._index([batch])
            before = {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            loaded, _ = app.releases.load(batch)
            self.assertEqual(loaded.nodes[0].areas[rid].ips, ['192.0.2.1'])
            self.assertEqual(before, {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()})
            app.store.db.execute('UPDATE configuration SET payload=?', (json.dumps(old),))
            app.store.db.execute('PRAGMA user_version=5')
            with closing(Application(directory)) as upgraded:
                self.assertEqual(upgraded.snapshot().nodes[0].areas[rid].ips, ['192.0.2.1'])
                self.assertEqual(upgraded.store.db.execute('PRAGMA user_version').fetchone()[0], 6)
            backups = list((Path(directory)/'backups').glob('smooth-caddy-v5-*.db'))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as db:
                self.assertEqual(json.loads(db.execute('SELECT payload FROM configuration').fetchone()[0]), old)
            with closing(Application(directory)): pass
            self.assertEqual(list((Path(directory)/'backups').glob('*.db')), backups)


class BindingUITests(unittest.IsolatedAsyncioTestCase):
    async def test_multiline_conflict_rejection_and_default_port_repair(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test')
            a = app.create('regions', '内网'); b = app.create('regions', '外网'); nid = app.create('nodes', 'Node')
            cfg = app.snapshot(); cfg.nodes[0].areas = {a: Listen(True, ['0.0.0.0']), b: Listen(True, ['::'])}
            app.save_configuration(cfg)
            ui = ReadyTerminal(app)
            async with ui.run_test(size=(130, 40)) as pilot:
                await pilot.press('f3'); await pilot.pause()
                table = ui.query_one('#matrix'); table.move_cursor(row=0, column=ui.col_keys.index('area:'+b))
                await pilot.press('enter'); await pilot.pause()
                editor = ui.screen.query_one('#ips', TextArea)
                self.assertEqual(editor.content_size.height, 4)
                editor.load_text('192.0.2.2')
                await pilot.press('ctrl+s'); await pilot.pause()
                self.assertEqual(len(ui.screen_stack), 2)
                error = str(ui.screen.query_one('#form-error').content)
                self.assertIn('内网', error); self.assertIn('外网', error)
                self.assertEqual(app.snapshot().nodes[0].areas[b].ips, ['::'])
                editor.load_text('::1\n2001:db8::1\n::1')
                await pilot.press('ctrl+s'); await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0].areas[b].ips, ['::1', '2001:db8::1'])
                self.assertIn('(+1)', ui.cell_value(ui.demo.nodes[0], 'area:'+b))
                # A default-port edit may introduce conflicts, and is allowed to save.
                await pilot.press('f4'); await pilot.pause()
                table.move_cursor(row=0, column=ui.col_keys.index('p1'))
                await pilot.press('enter'); await pilot.pause()
                ui.screen.query_one('#value').value = '80'
                await pilot.press('ctrl+s'); await pilot.pause()
                self.assertEqual(app.snapshot().regions[0].ports[1], '80')
                self.assertIn(('nodes', nid, 'area:'+a), app.errors())
                await pilot.press('f3'); await pilot.pause()
                table.move_cursor(row=0, column=ui.col_keys.index('area:'+a))
                await pilot.press('enter'); await pilot.pause()
                self.assertIn('监听冲突', ui.screen.note)
                ui.screen.query_one('#override1').value = True
                await pilot.pause(); ui.screen.query_one('#port1').value = '443'
                await pilot.press('ctrl+s'); await pilot.pause()
                self.assertNotIn(('nodes', nid, 'area:'+a), app.errors())
