from tests.legacy_batches import legacy_batch
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
from app.network.models import Service, service_policy, Configuration, Listen, Node, Region, binding_addresses, configuration_errors
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
        regions = [Region('a', '内网'), Region('b', '外网')]
        node = Node('n', 'Node', platform='debian_13', arch='amd64', ssh_hops=[['192.0.2.1']])
        config = Configuration(regions=regions, nodes=[node])
        for first, second, conflict in [('0.0.0.0', '192.0.2.1', True), ('::', '::1', True),
                                        ('0.0.0.0', '::', False), ('192.0.2.1', '192.0.2.2', False),
                                        ('2001:db8::1', '2001:db8:0:0::1', True)]:
            with self.subTest(first=first, second=second):
                node.areas = {'a': Listen(True, [first],relay_enabled=True), 'b': Listen(True, [second],['80','9443','443'],relay_enabled=True)}
                errors = configuration_errors(config)
                self.assertEqual(bool(errors), conflict)
                if conflict:
                    a = errors[('nodes', 'n', 'area:a')]
                    self.assertEqual(a, errors[('nodes', 'n', 'area:b')])
                    self.assertIn('内网 HTTPS', a[0]); self.assertIn('外网 中继 HTTPS', a[0])
                node.areas['b'].enabled = False
                self.assertEqual(configuration_errors(config), {})
        node.areas = {'a': Listen(True, ['0.0.0.0', '192.0.2.1'],relay_enabled=True)}
        self.assertIn(('nodes', 'n', 'area:a'), configuration_errors(config))
        node.areas = {'a': Listen(True, ['::', '0.0.0.0'],relay_enabled=True)}
        self.assertFalse(configuration_errors(config))
        node.areas['a'].ports[0] = '443'
        self.assertIn('HTTP', configuration_errors(config)[('nodes', 'n', 'area:a')][0])

    def test_generation_and_v5_database_metadata_migration(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test'); app.certificates.initialize('Test')
            rid = app.create('regions', 'LAN'); nid = app.create('nodes', 'Node')
            app.create('sites', 'Web')
            cfg = app.snapshot(); node = cfg.nodes[0]
            node.platform = 'debian_13'; node.arch = 'amd64'; node.ssh_hops = [['192.0.2.1']]
            node.areas[rid] = Listen(True, ['0.0.0.0', '::'],relay_enabled=True)
            cfg.sites[0].domain = 'test.example'; cfg.sites[0].source = 'http://127.0.0.1:9000'; cfg.sites[0].areas[rid] = Service(True)
            materials = generate(cfg, app.certificates, 'test')[nid]
            servers = json.loads(materials['caddy.json'])['apps']['http']['servers']
            for kind, port in [('https', '443'), ('relay', '8443')]:
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
            batch = legacy_batch(app); folder = app.releases.directory(batch)
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
                self.assertEqual(upgraded.store.db.execute('PRAGMA user_version').fetchone()[0], 11)
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
            cfg = app.snapshot(); cfg.nodes[0].ssh_hops = [['192.0.2.1'], ['192.0.2.2']]; cfg.nodes[0].areas = {a: Listen(True, ['0.0.0.0'],relay_enabled=True), b: Listen(True, ['::'],relay_enabled=True)}
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
                self.assertEqual(ui.cell_value(ui.demo.nodes[0], 'area:'+b), '[::1]\n[2001:db8::1]')
                self.assertEqual(table.rows[table.ordered_rows[0].key].height, 2)
                self.assertEqual(ui.cell_value(ui.demo.nodes[0], 'ssh_hops'), '192.0.2.2\n(经1个地址跳转)')
                # Region editing now controls policy defaults only.
                await pilot.press('f6');await pilot.pause()
                self.assertEqual(ui.col_keys,['name','tls_source','mtls'])
                table.move_cursor(row=0,column=ui.col_keys.index('mtls'))
                await pilot.press('enter');await pilot.pause()
                ui.screen.query_one('#value').value=True
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertTrue(app.snapshot().regions[0].mtls)

    async def test_compact_ports_independent_http(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test')
            a=app.create('regions','A');b=app.create('regions','B');app.create('nodes','Node')
            cfg=app.snapshot();node=cfg.nodes[0]
            node.platform='debian_13';node.arch='amd64';node.ssh_hops=[['192.0.2.1']]
            node.areas={a:Listen(True,['192.168.10.1'],relay_enabled=True),b:Listen(True,['::'],relay_enabled=True)}
            app.save_configuration(cfg)
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f3');await pilot.pause()
                self.assertNotIn('http_port',ui.col_keys)
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'upstream_url'),'直连')
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'area:'+a),'192.168.10.1')
                table=ui.query_one('#matrix');table.move_cursor(row=0,column=ui.col_keys.index('area:'+a));table.focus()
                await pilot.press('enter');await pilot.pause()
                for i in range(2):
                    self.assertFalse(ui.screen.query_one('#override'+str(i)).value)
                    self.assertTrue(ui.screen.query_one('#port'+str(i)).disabled)
                ui.screen.query_one('#override0').value=True;await pilot.pause()
                ui.screen.query_one('#port0').value='81'
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0].areas[a].ports[0],'81')
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'area:'+a),'192.168.10.1:(81/443/8443)')
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'area:'+b),'[::]')
                table.move_cursor(row=0,column=ui.col_keys.index('area:'+b));table.focus()
                await pilot.press('enter');await pilot.pause()
                self.assertFalse(ui.screen.query_one('#override0').value)
                ui.screen.query_one('#override0').value=False
                ui.screen.query_one('#relay_enabled').value=True;await pilot.pause()
                ui.screen.query_one('#port2').value='9443'
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0].areas[a].ports[0],'81')
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'area:'+a),'192.168.10.1:(81/443/8443)')
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'area:'+b),'[::]:(80/443/9443)')

    async def test_two_line_node_summary(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.create('nodes','Direct');app.create('nodes','Relay')
            cfg=app.snapshot();direct,relay=cfg.nodes
            direct.platform='debian_13';direct.arch='amd64';direct.ssh_hops=[['192.0.2.1']]
            relay.platform='openwrt_25_12';relay.arch='arm64'
            relay.ssh_hops=[['192.0.2.1'],['192.0.2.2'],['2001:db8::3']]
            relay.upstream_url='https://relay.example.com:8443'
            app.save_configuration(cfg)
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f3');await pilot.pause()
                table=ui.query_one('#matrix')
                self.assertEqual([row.height for row in table.rows.values()],[2,2])
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'platform'),'Debian\namd64')
                self.assertEqual(ui.cell_value(ui.demo.nodes[1],'platform'),'OpenWrt\narm64')
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'ssh_hops'),'192.0.2.1')
                self.assertEqual(ui.cell_value(ui.demo.nodes[1],'ssh_hops'),'[2001:db8::3]\n(经2个地址跳转)')
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'upstream_url'),'直连')
                self.assertEqual(ui.cell_value(ui.demo.nodes[1],'upstream_url'),'中继\nhttps://relay.example.com:8443')
                headings=[str(c.label) for c in table.columns.values()]
                self.assertIn('SSH 地址',headings);self.assertIn('上游',headings)
                table.move_cursor(row=1,column=ui.col_keys.index('upstream_url'));table.focus()
                await pilot.press('enter');await pilot.pause()
                self.assertEqual(ui.screen.query_one('#value').value,relay.upstream_url)
                await pilot.press('escape');await pilot.pause()
