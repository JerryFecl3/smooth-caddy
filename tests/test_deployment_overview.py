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
                self.assertEqual(row[1].plain,'0.0.0.0:(80/444)·中继\n[::]:(80/444)·中继')
                self.assertEqual(row[2].plain,'未启用')
                self.assertFalse(ui.query_one('#page-summary').display)
                node=ui.demo.nodes[0];area=node.areas[cfg.regions[0].id]
                area.ports=['80','443','8443']
                self.assertEqual(ui.deployment_cells(node,{})[1].plain.splitlines()[:2],['0.0.0.0·中继','[::]·中继'])
                area.ports=['80','444','8443']
                sites=ui.query_one('#deployment-sites')
                self.assertEqual(sites.row_count,3)
                self.assertEqual([sites.get_row_at(i)[0].plain for i in range(3)],['Z site','Hidden','A site'])
                self.assertEqual(sites.get_row_at(1)[1].plain,label('disabled'))
                first=ui.demo.sites[0];first.name='首页'
                ui.render_deployment_sites({('sites',first.id,'source'):['error']})
                self.assertEqual(sites.get_row_at(0)[0].plain,'! 首页')
                self.assertEqual(table.get_row_at(1)[0].plain.splitlines()[0],'A node')
                self.assertEqual(next(iter(table.rows.values())).height,2)
                table.focus();await pilot.press('enter');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),1)
                # Reordering configuration drives both the overview and settings pages.
                cfg=app.snapshot();cfg.nodes.reverse();cfg.regions.reverse();cfg.sites.reverse();app.save_configuration(cfg)
                ui.demo.reload();ui.render_page();await pilot.pause()
                self.assertEqual([column.label.plain for column in table.columns.values()][1:],['A zone','Z zone'])
                self.assertEqual(table.get_row_at(0)[0].plain.splitlines()[0],'A node')
                self.assertEqual([sites.get_row_at(i)[0].plain for i in range(3)],['A site','Hidden','Z site'])
                for page in ('sites','nodes'):
                    ui.page=page;ui.render_page();await pilot.pause()
                    self.assertEqual([key for key in ui.col_keys if key.startswith('area:')],['area:'+r.id for r in cfg.regions])
                    self.assertEqual(ui.row_ids,[item.id for item in getattr(cfg,page)])
                ui.page='regions';ui.render_page();await pilot.pause()
                self.assertEqual(ui.row_ids,[r.id for r in cfg.regions])
