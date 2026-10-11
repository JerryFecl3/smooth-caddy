import tempfile
import unittest
from contextlib import closing
from app.network.application import Application
from app.network.models import Service, service_policy, relay_endpoint
from tests.ui_helpers import ReadyTerminal
from app.tui.widgets import Input
from app.tui.choice_row import ChoiceRow

class NodeUpstreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_flat_list_free_address_and_clearing(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('test')
            a=app.create('nodes','A');b=app.create('nodes','B')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f3','enter');await pilot.pause()
                self.assertEqual([f.key for f in ui.screen.fields],['value'])
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(ui.row_ids,[a,b])
                table=ui.query_one('#matrix');table.move_cursor(row=1,column=ui.col_keys.index('upstream_url'))
                await pilot.press('enter');await pilot.pause()
                ui.screen.query_one('#mode',ChoiceRow).value=True;await pilot.pause()
                ui.screen.query_one('#value',Input).value='http://relay.test:8443'
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),2)
                self.assertIn('HTTPS',str(ui.screen.query_one('#form-error').content))
                ui.screen.query_one('#value',Input).value='https://outside.example:9443'
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[1].upstream_url,'https://outside.example:9443')
                app.delete('nodes',a)
                self.assertEqual(app.snapshot().nodes[0].upstream_url,'https://outside.example:9443')
                ui.demo.reload();ui.render_page()
                ui.query_one('#matrix').move_cursor(row=0,column=ui.col_keys.index('upstream_url'))
                await pilot.press('enter');await pilot.pause()
                ui.screen.query_one('#mode',ChoiceRow).value=False;await pilot.pause()
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0].upstream_url,'')

    def test_url_validation(self):
        for value, expected in [('https://relay.test',('relay.test',443)),('https://relay.test:9443/',('relay.test',9443)),('https://[2001:db8::1]:8443',('2001:db8::1',8443))]:
            self.assertEqual(relay_endpoint(value),expected)
        for value in ('http://relay.test','https://','https://user@host','https://host/path','https://host?','https://host#','https://host:0','https://host:65536','https://host:','https://0.0.0.0','https://[::]','https://bad host','https://[fe80::1%eth0]'):
            with self.subTest(value=value),self.assertRaises(ValueError):relay_endpoint(value)
