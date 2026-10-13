from contextlib import closing
from copy import deepcopy
import json
import tempfile
import unittest
from app.network.application import Application
from app.network.archives import encode, decode
from app.network.migrations import configuration_v10
from app.network.models import Listen, configuration_errors
from app.network.generator import generate
from tests.test_site_paths import setup
from tests.ui_helpers import ReadyTerminal


class RelayToggleTests(unittest.TestCase):
    def test_default_off_and_outgoing_relay_remains_available(self):
        self.assertFalse(Listen().relay_enabled)
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            cfg,rid=setup(app)
            for node in cfg.nodes:node.areas[rid].relay_enabled=False
            materials=generate(cfg,app.certificates,'test')
            for node in cfg.nodes:
                files=materials[node.id];servers=json.loads(files['caddy.json'])['apps']['http']['servers']
                self.assertNotIn(rid+'-relay',servers)
                self.assertIn(rid+'-https',servers)
                self.assertNotIn(f'certificates/relay-{node.id}-{rid}.key',files)
            node=cfg.nodes[1]
            self.assertIn('certificates/node-'+node.id+'.key',materials[node.id])
            servers=json.loads(materials[node.id]['caddy.json'])['apps']['http']['servers']
            proxy=servers[rid+'-https']['routes'][1]['handle'][0]
            self.assertIn('client_certificate_file',proxy['transport']['tls'])
            self.assertEqual(decode(encode(cfg,'Disabled')).to_dict(),{**cfg.to_dict(),'revision':0})

    def test_enabled_port_validation_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            cfg,rid=setup(app);area=cfg.nodes[0].areas[rid]
            key=('nodes',cfg.nodes[0].id,'area:'+rid)
            for port in ('','invalid','0','65536','443','80'):
                area.ports[2]=port;area.relay_enabled=False
                self.assertNotIn(key,configuration_errors(cfg))
                area.relay_enabled=True
                self.assertIn(key,configuration_errors(cfg))
            area.ports[2]='9443'
            files=generate(cfg,app.certificates,'test')[cfg.nodes[0].id]
            servers=json.loads(files['caddy.json'])['apps']['http']['servers']
            self.assertEqual(servers[rid+'-relay']['listen'],['tcp4/127.0.0.1:9443'])

    def test_legacy_configs_and_archives_preserve_relay(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            cfg,rid=setup(app);cfg.nodes[0].areas[rid].ports[2]='9443'
            old=deepcopy(cfg.to_dict())
            for node in old['nodes']:
                for area in node['areas'].values():area.pop('relay_enabled')
            for site in old['sites']:
                site.pop('homepage_redirect');site.pop('allowed_paths')
            migrated=configuration_v10(old)
            self.assertTrue(migrated.nodes[0].areas[rid].relay_enabled)
            self.assertEqual(migrated.nodes[0].areas[rid].ports[2],'9443')
            document=encode(cfg,'Old');document['format']=4;old.pop('revision');document['configuration']=old
            self.assertTrue(decode(document).nodes[0].areas[rid].relay_enabled)


class RelayToggleFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkbox_port_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            cfg,rid=setup(app);cfg=app.snapshot();node=cfg.nodes[0];node.areas[rid]=Listen(True,['127.0.0.1']);app.save_configuration(cfg)
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                ui.page='nodes';ui.render_page();await pilot.pause()
                table=ui.query_one('#matrix');table.move_cursor(row=0,column=ui.col_keys.index('area:'+rid));table.focus()
                await pilot.press('enter');await pilot.pause()
                form=ui.screen;check=form.query_one('#relay_enabled');port=form.query_one('#port2')
                self.assertFalse(check.value);self.assertTrue(port.disabled);self.assertEqual(port.value,'8443')
                check.value=True;await pilot.pause();self.assertFalse(port.disabled)
                port.value='';await pilot.press('ctrl+s');await pilot.pause();self.assertIs(ui.screen,form)
                port.value='9443';await pilot.press('ctrl+s');await pilot.pause()
                area=app.snapshot().nodes[0].areas[rid]
                self.assertTrue(area.relay_enabled);self.assertEqual(area.ports[2],'9443')
                table.focus();await pilot.press('enter');await pilot.pause()
                ui.screen.query_one('#relay_enabled').value=False;await pilot.pause()
                self.assertTrue(ui.screen.query_one('#port2').disabled)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertFalse(app.snapshot().nodes[0].areas[rid].relay_enabled)
                self.assertEqual(ui.cell_value(ui.demo.nodes[0],'area:'+rid),'127.0.0.1')
