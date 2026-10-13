from app.tui.choice_row import ChoiceRow
from textual.widgets import Checkbox
from app.network.deployment import deployment_update
import tempfile, unittest, threading
from pathlib import Path
from unittest.mock import patch, AsyncMock
from contextlib import asynccontextmanager
from types import SimpleNamespace
from app.network.application import Application
from app.network.models import Service, service_policy, Listen
from app.network.task_progress import TaskState
from tests.test_public_tls import materials

class PublicBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Application(self.tmp.name);self.addCleanup(self.app.close)
        self.app.store.exports=Path(self.tmp.name)/"export"
        self.app.security.setup('secret');self.app.certificates.initialize('Network')
        self.app.create('regions','LAN');self.app.create('nodes','Router');self.app.create('sites','Web')
        c=self.app.snapshot();r=c.regions[0];n=c.nodes[0];s=c.sites[0]
        n.platform='debian_13';n.arch='amd64';n.ssh_hops=[['192.0.2.1']];n.areas[r.id]=Listen(True,['192.0.2.1'],relay_enabled=True)
        s.domain='web.example.com';s.source='http://192.0.2.2:8080';s.areas[r.id]=Service(True);s.areas[r.id].tls_source='public_ca'
        self.app.save_configuration(c);self.site=s.id
    def record(self,domain='example.com',wildcard=True):
        return self.app.public_tls.save(domain,wildcard,'alidns','dummy-id','dummy-secret')
    def store_material(self,identity,days=90):
        service=self.app.public_tls;item=service.get(identity);cert,key=materials(item['domain'],days)
        item.update(certificate=cert.decode(),expires=service.validate(cert,key,[item['domain']]))
        secret=service.secret(identity);secret['key']=key.decode()
        with service.store.transaction():
            service._put_secret(identity,secret);service._put_result(identity,item)
        return cert,key
    def test_blocking_errors_and_pending_are_distinct(self):
        key=('sites',self.site,'tls_source')
        self.assertIn(key,self.app.errors())
        identity=self.record()
        errors,matches,pending=self.app.batches.inspect(self.app.snapshot())
        self.assertFalse(errors);self.assertEqual(matches[self.site]['id'],identity)
        self.assertEqual(pending[self.site],'待申请')
        self.store_material(identity);self.assertFalse(self.app.batches.inspect(self.app.snapshot())[2])
        self.app.public_tls.configure(False,'')
        report=self.app.batches.inspect(self.app.snapshot())
        self.assertFalse(report.errors);self.assertEqual(report.pending[self.site],'待申请')
    def test_exact_before_wildcard_and_single_label(self):
        wild=self.record();exact=self.record('web.example.com',False)
        self.assertEqual(self.app.batches.inspect(self.app.snapshot())[1][self.site]['id'],exact)
        self.app.public_tls.delete(exact)
        self.assertEqual(self.app.batches.inspect(self.app.snapshot())[1][self.site]['id'],wild)
        c=self.app.snapshot();c.sites[0].domain='nested.web.example.com';self.app.save_configuration(c)
        self.assertTrue(self.app.errors())
    def test_generate_copies_public_chain_and_frozen_batch(self):
        identity=self.record();cert,key=self.store_material(identity);events=[]
        with patch.object(self.app.public_tls,'_run',side_effect=AssertionError('no issuance needed')):
            batch=self.app.batches.create(task_progress=events.append)
        config,files=self.app.releases.load(batch);node=config.nodes[0]
        self.assertEqual(files[node.id]['certificates/site-'+self.site+'-public_ca.pem'],cert)
        self.assertEqual(files[node.id]['certificates/site-'+self.site+'-public_ca.key'],key)
        self.assertTrue(all(e.steps==events[0].steps for e in events))
        self.assertEqual(set(events[0].groups),{'申请公共TLS证书','准备运行材料'})
        self.app.public_tls.delete(identity)
        with patch.object(self.app.public_tls,'issue_all',side_effect=AssertionError('immutable batch')),patch.object(self.app.releases.cache,'ensure',return_value=b'binary'):
            self.app.releases.assemble(batch,'v2.11.7',password='export')
        self.assertEqual(self.app.releases.load(batch)[1],files)
    def test_only_referenced_records_once_and_failure_blocks_batch(self):
        identity=self.record();self.record('unused.example.net')
        self.app.create('sites','Second');c=self.app.snapshot();s=c.sites[-1]
        s.domain='another.example.com';s.source='http://192.0.2.3';s.areas[c.regions[0].id]=Service(True);s.areas[c.regions[0].id].tls_source='public_ca';self.app.save_configuration(c)
        with patch.object(self.app.public_tls,'issue_all',return_value={'success':False,'errors':['申请失败']}) as issue:
            with self.assertRaisesRegex(ValueError,'申请失败'):self.app.batches.create()
            self.assertEqual(issue.call_args.args[0],[identity])
        self.assertEqual(self.app.releases.list(),[])
    def test_missing_and_bad_key_block_generation(self):
        identity=self.record();self.store_material(identity)
        service=self.app.public_tls;secret=service.secret(identity);secret['key']=materials('other.example.com')[1].decode()
        with service.store.transaction():service._put_secret(identity,secret)
        self.assertTrue(self.app.errors())
        with patch.object(service,'issue_all') as issue:
            with self.assertRaises(ValueError):self.app.batches.create()
            issue.assert_not_called()
    def test_near_expiry_renews_before_batch_generation(self):
        identity=self.record();old,_=self.store_material(identity,days=5)
        self.assertEqual(self.app.batches.inspect(self.app.snapshot())[2][self.site],'待续签')
        fresh,key=materials('example.com')
        def run(cmd,env,home,cancel):
            folder=home/'certificates';folder.mkdir(exist_ok=True)
            (folder/'example.com.crt').write_bytes(fresh);(folder/'example.com.key').write_bytes(key)
            return 0,''
        with patch.object(self.app.public_tls.tool,'version',return_value='v5.5.2'),patch.object(self.app.public_tls,'_run',side_effect=run) as issue:
            batch=self.app.batches.create()
            self.assertEqual(issue.call_count,1)
        config,files=self.app.releases.load(batch)
        self.assertEqual(files[config.nodes[0].id]['certificates/site-'+self.site+'-public_ca.pem'],fresh)
        self.assertNotEqual(old,fresh)

    def test_no_public_https_means_no_issuance_group(self):
        c=self.app.snapshot();c.sites[0].areas[c.regions[0].id]=Service(True,'private_ca',False);self.app.save_configuration(c)
        with patch.object(self.app.public_tls,'issue_all',side_effect=AssertionError('no public TLS')):
            events=[];self.app.batches.create(task_progress=events.append)
        self.assertEqual(set(events[0].groups),{'准备运行材料'})

class PublicCombinedTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_groups_with_real_generation_and_mock_deploy(self):
        fixture=PublicBatchTests();fixture.setUp()
        try:
            fixture.store_material(fixture.record());app=fixture.app;events=[]
            async def run(packages,confirm,decide,notify):
                for p in packages.packages:notify(deployment_update(p.node_id,'upload','uploaded'));notify(deployment_update(p.node_id,'install','deploying'));notify(deployment_update(p.node_id,'install','success'))
                return {p.node_id:'success' for p in packages.packages}
            @asynccontextmanager
            async def connect(*args):yield SimpleNamespace(run=AsyncMock())
            with patch.object(app.deployment,'probe_node',new=AsyncMock(return_value='v2.11.7')),patch.object(app.deployment,'run',side_effect=run),patch.object(app.ssh,'connect',connect):
                result=await app.deployment.execute(None,'v2.11.7',AsyncMock(),AsyncMock(),lambda _:None,events.append,threading.Event())
            self.assertTrue(result['success']);model=TaskState()
            for e in events:model.update(e)
            self.assertEqual([name for name,_ in model.sections()],['申请公共TLS证书','准备运行材料','部署到节点'])
            model.finish('success');self.assertEqual(model.counts(),(len(model.steps),len(model.steps)))
        finally:fixture.doCleanups()

class PublicSourceUITests(unittest.IsolatedAsyncioTestCase):
    async def test_source_column_editor_and_pending_state(self):
        from tests.ui_helpers import ReadyTerminal as Terminal
        from textual.widgets import DataTable, Select, RadioSet, RadioButton
        fixture=PublicBatchTests();fixture.setUp()
        try:
            app=fixture.app;fixture.record();ui=Terminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                await pilot.press('f2');await pilot.pause()
                table=ui.query_one('#matrix',DataTable)
                column=ui.col_keys.index('area:'+app.snapshot().regions[0].id);table.move_cursor(row=0,column=column);table.focus()
                self.assertIn('待申请',ui.cell_value(ui.demo.sites[0],'area:'+app.snapshot().regions[0].id))
                await pilot.press('enter');await pilot.pause()
                self.assertEqual(ui.screen.query_one('#tls_source',ChoiceRow).pressed_index,1)
                ui.screen.query_one('#tls_source',ChoiceRow).query(Checkbox)[0].value=True
                await pilot.pause()
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(app.snapshot().sites[0].areas[app.snapshot().regions[0].id].tls_source,'private_ca')
                self.assertFalse(app.errors())
        finally:fixture.doCleanups()
