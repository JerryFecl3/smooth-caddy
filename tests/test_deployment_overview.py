from contextlib import closing
import tempfile
import unittest
from app.network.application import Application
from app.network.models import Service, service_policy, Listen
from app.tui.labels import label
from tests.ui_helpers import ReadyTerminal


class OverviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_bindings_sites_and_final_ssh(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test')
            for kind,names in (('nodes',('Z node','A node')),('regions',('Z zone','A zone')),('sites',('Z site','Hidden','A site'))):
                for name in names:app.create(kind,name)
            cfg=app.snapshot()
            for node in cfg.nodes:
                node.platform='debian_13';node.arch='amd64';node.ssh_hops=[['192.0.2.1'],['2001:db8::2']]
                node.areas={cfg.regions[0].id:Listen(True,['0.0.0.0','::'],['80','444','8443'],relay_enabled=True)}
            for i,site in enumerate(cfg.sites):
                site.domain=f's{i}.example.com';site.source='http://127.0.0.1:8000'
                site.areas={cfg.regions[0].id:Service(i!=1)}
            app.save_configuration(cfg)
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                table=ui.query_one('#matrix')
                self.assertEqual([column.label.plain for column in table.columns.values()][1:],['Z zone','A zone'])
                self.assertEqual(next(iter(table.columns.values())).label.plain,'节点')
                row=table.get_row_at(0)
                self.assertEqual(row[0].plain,'Z node\n[2001:db8::2]')
                self.assertEqual(row[1].plain,'0.0.0.0:(80/444/8443)\n[::]:(80/444/8443)\n  Z site  '+ui.service_label(cfg.sites[0],cfg.regions[0])+'\n  A site  '+ui.service_label(cfg.sites[0],cfg.regions[0]))
                self.assertEqual(row[2].plain,'未启用')
                self.assertFalse(ui.query_one('#page-summary').display)
                node=ui.demo.nodes[0];area=node.areas[cfg.regions[0].id]
                area.ports=['80','443','8443']
                self.assertEqual(ui.deployment_cells(node,{})[1].plain.splitlines()[:2],['0.0.0.0','[::]'])
                area.ports=['80','444','8443']
                # Align by terminal cells, including Chinese names and error markers.
                from rich.cells import cell_len
                first,last=ui.demo.sites[0],ui.demo.sites[2]
                old_names=(first.name,last.name)
                first.name='首页';last.name='Dashboard'
                lines=ui.deployment_cells(node,{('sites',first.id,'source'):['error']})[1].plain.splitlines()[2:]
                self.assertEqual([cell_len(line.split('TLS(')[0]) for line in lines],[13,13])
                self.assertTrue(lines[0].startswith('  首页'))
                self.assertTrue(lines[0].endswith(' !'))
                first.name,last.name=old_names
                self.assertEqual(table.get_row_at(1)[0].plain.splitlines()[0],'A node')
                self.assertEqual(next(iter(table.rows.values())).height,4)
                table.focus();await pilot.press('enter');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),1)
                # Reordering configuration drives both the overview and settings pages.
                cfg=app.snapshot();cfg.nodes.reverse();cfg.regions.reverse();cfg.sites.reverse();app.save_configuration(cfg)
                ui.demo.reload();ui.render_page();await pilot.pause()
                self.assertEqual([column.label.plain for column in table.columns.values()][1:],['A zone','Z zone'])
                self.assertEqual(table.get_row_at(0)[0].plain.splitlines()[0],'A node')
                self.assertEqual(table.get_row_at(0)[2].plain.splitlines()[2:],[ '  A site  '+ui.service_label(cfg.sites[0],cfg.regions[1]),'  Z site  '+ui.service_label(cfg.sites[0],cfg.regions[1])])
                for page in ('sites','nodes'):
                    ui.page=page;ui.render_page();await pilot.pause()
                    self.assertEqual([key for key in ui.col_keys if key.startswith('area:')],['area:'+r.id for r in cfg.regions])
                    self.assertEqual(ui.row_ids,[item.id for item in getattr(cfg,page)])
                ui.page='regions';ui.render_page();await pilot.pause()
                self.assertEqual(ui.row_ids,[r.id for r in cfg.regions])
