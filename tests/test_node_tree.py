import tempfile
import unittest
from app.network.application import Application
from app.network.models import node_tree, ssh_route, Listen
from tests.ui_helpers import ReadyTerminal
from app.tui.widgets import Input, Select

class NodeTreeTests(unittest.IsolatedAsyncioTestCase):
    async def test_relay_cell_and_options(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.security.setup('test')
            rid=app.create('regions','LAN');a=app.create('nodes','A');b=app.create('nodes','B',a)
            config=app.snapshot();config.nodes[0].areas[rid]=Listen(True,'10.0.0.1');app.save_configuration(config)
            try:
                ui=ReadyTerminal(app)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f3');await pilot.pause()
                    table=ui.query_one('#matrix');table.move_cursor(row=0,column=len(ui.col_keys)-1)
                    await pilot.pause();app.security.lock()
                    self.assertEqual(ui.cell_value(ui.demo.nodes[0],'upstream'),'')
                    self.assertTrue(ui.query_one('#edit').disabled)
                    await pilot.press('enter','ctrl+o');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),1)
                    app.security.unlock('test');table.move_cursor(row=1,column=len(ui.col_keys)-1)
                    await pilot.press('enter');await pilot.pause()
                    choices=next(f.choices for f in ui.screen.fields if f.key=='region')
                    self.assertIn(('A-LAN-10.0.0.1',rid),choices)
                    ui.screen.query_one('#region',Select).value=rid
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(ui.cell_value(ui.demo.nodes[1],'upstream'),'10.0.0.1')
            finally:app.close()

    async def test_edit_parent_rejects_cycle_and_clears_region(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.security.setup('test')
            a=app.create('nodes','A');b=app.create('nodes','B',a);c=app.create('nodes','C',b)
            try:
                self.assertEqual([(n.name,p) for n,p in node_tree(app.snapshot().nodes)],[('A',''),('B','└─ '),('C','   └─ ')])
                config=app.snapshot();config.nodes[0].upstream=(c,'');config.nodes[0].mode='via_upstream'
                with self.assertRaisesRegex(ValueError,'循环'):app.save_configuration(config)
                self.assertIsNone(app.snapshot().nodes[0].upstream)
                config=app.snapshot();config.nodes[1].upstream=(a,'old-region');app.save_configuration(config)
                ui=ReadyTerminal(app)
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f3','enter');await pilot.pause()
                    ui.screen.query_one('#parent',Select).value=c
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(len(ui.screen_stack),2)
                    self.assertIn('循环',str(ui.screen.query_one('#form-error').content))
                    await pilot.press('escape')
                    ui.query_one('#matrix').move_cursor(row=1,column=0)
                    await pilot.press('enter');await pilot.pause()
                    ui.screen.query_one('#parent',Select).value=''
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertIsNone(app.snapshot().nodes[1].upstream)
                    self.assertEqual(app.snapshot().nodes[1].mode,'direct')
                    self.assertEqual(ui.col_keys[-1],'upstream')
                config=app.snapshot()
                for n in config.nodes:n.ssh_ip='10.0.0.1'
                self.assertEqual([n.name for n in ssh_route(config,c)],['B','C'])
                app.delete('nodes',b)
                self.assertEqual(app.snapshot().find('nodes',c).upstream,(b,''))
            finally:app.close()
