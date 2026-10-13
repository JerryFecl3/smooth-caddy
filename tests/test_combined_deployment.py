from app.network.deployment import deployment_update
import io,tarfile,tempfile,threading,unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from pathlib import Path
from app.network.application import Application

class CombinedDeploymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Application(self.tmp.name);self.addCleanup(self.app.close)
        self.app.store.exports=Path(self.tmp.name)/"export"
        self.app.security.setup('secret');self.app.certificates.initialize('Network')
        for name in ('A','B'):self.app.create('nodes',name)
        cfg=self.app.snapshot()
        for i,node in enumerate(cfg.nodes):node.platform='debian_13';node.arch='amd64';node.ssh_hops=[[f'192.0.2.{i+1}']]
        self.app.save_configuration(cfg)
        self.batch=self.app.releases.prepare()

    def contents(self,packages):
        result={}
        for package in packages.packages:
            data=(self.app.releases.directory(packages)/package.filename).read_bytes().split(b'__CADDY_PAYLOAD__\n',1)[1]
            with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:result[package.name]=archive.getnames()
        return result

    async def test_per_node_binaries_cleanup_and_frozen_configuration(self):
        cfg=self.app.snapshot();cfg.nodes[0].name='Edited';self.app.save_configuration(cfg)
        seen={};events=[];cleaned=[]
        async def run(packages,*args):
            seen.update(self.contents(packages));seen['directory']=self.app.releases.directory(packages)
            self.assertEqual(packages.configuration['nodes'][0]['name'],'Edited')
            return {p.node_id:'success' for p in packages.packages}
        @asynccontextmanager
        async def connect(route,confirm):
            cleaned.append(route[-1].name)
            yield SimpleNamespace(run=AsyncMock())
        with patch.object(self.app.deployment,'probe_node',new=AsyncMock(side_effect=['v2.11.7','v2.10.0'])),patch.object(self.app.releases.cache,'ensure',return_value=b'binary'),patch.object(self.app.deployment,'run',side_effect=run),patch.object(self.app.ssh,'connect',connect):
            result=await self.app.deployment.execute(None,'v2.11.7',AsyncMock(),AsyncMock(),lambda _:None,events.append,threading.Event())
        self.assertTrue(result['success']);self.assertNotIn('caddy',seen['Edited']);self.assertIn('caddy',seen['B'])
        self.assertFalse(seen['directory'].exists());self.assertEqual(cleaned,['Edited','B'])
        self.assertTrue(all(event.steps==events[0].steps for event in events))
        self.assertEqual(self.app.releases.list(),[])

    async def test_selected_node_limits_export_probe_transfer_and_cleanup(self):
        selected=self.app.snapshot().nodes[1].id
        before=self.app.snapshot()
        with patch.object(self.app.releases.cache,'ensure',return_value=b'binary'):
            packages=self.app.batches.export('v2.11.7','export',node_ids=(selected,))
        self.assertEqual([p.node_id for p in packages.packages],[selected])
        seen=[];cleaned=[];events=[]
        async def run(packages,*args):
            seen.extend(p.node_id for p in packages.packages)
            return {p.node_id:'success' for p in packages.packages}
        @asynccontextmanager
        async def connect(route,confirm):
            cleaned.append(route[-1].name)
            yield SimpleNamespace(run=AsyncMock())
        with patch.object(self.app.deployment,'probe_node',new=AsyncMock(return_value='v2.11.7')) as probe,patch.object(self.app.deployment,'run',side_effect=run),patch.object(self.app.ssh,'connect',connect):
            result=await self.app.deployment.execute(None,'v2.11.7',AsyncMock(),AsyncMock(),lambda _:None,events.append,threading.Event(),node_ids=(selected,))
        self.assertTrue(result['success'])
        self.assertEqual(seen,[selected]);self.assertEqual(cleaned,['B'])
        self.assertEqual(probe.await_count,1)
        self.assertEqual(probe.await_args.args[1].id,selected)
        self.assertEqual(self.app.snapshot(),before)
        self.assertNotIn('probe:'+before.nodes[0].id,events[0].task_ids)
        with self.assertRaises(ValueError):self.app.batches.export('v2.11.7','export',node_ids=('missing',))

    async def test_failed_deploy_cleans_temporary_packages(self):
        async def run(packages,*args):return {p.node_id:'failed' for p in packages.packages}
        with patch.object(self.app.deployment,'probe_node',new=AsyncMock(return_value='v2.11.7')),patch.object(self.app.deployment,'run',side_effect=run),patch.object(self.app.releases.cache,'ensure',side_effect=AssertionError('no download')):
            result=await self.app.deployment.execute(None,'v2.11.7',AsyncMock(),AsyncMock(),lambda _:None,lambda _:None,threading.Event())
        self.assertFalse(result['success']);self.assertEqual(len(list((Path(self.tmp.name)/'.tmp'/'tasks').rglob('*.run'))),0)

    async def test_probe_error_requires_retry_not_skip(self):
        from app.network.task_progress import TaskCancelled
        with patch.object(self.app.deployment,'probe_node',new=AsyncMock(side_effect=OSError('offline'))),patch.object(self.app.releases,'assemble') as assemble:
            with self.assertRaises(TaskCancelled):
                await self.app.deployment.execute(None,'v2.11.7',AsyncMock(),AsyncMock(return_value='stop'),lambda _:None,lambda _:None,threading.Event())
            assemble.assert_not_called()

    async def test_package_export_is_complete_untracked_and_uses_saved_materials(self):
        cfg,original=self.app.releases.load(self.batch)
        self.app.certificates.reset()
        with patch.object(self.app.certificates,'leaf',side_effect=AssertionError('no reissue')),patch.object(self.app.releases.cache,'ensure',return_value=b'binary'):
            packages=self.app.releases.assemble(self.batch,'v2.11.7',password='export')
        for package in packages.packages:
            payload=(self.app.releases.directory(packages)/package.filename).read_bytes()
            self.assertIn(b'openssl enc -d',payload)
            self.assertNotIn(b'PRIVATE KEY',payload)
        directory=self.app.releases.directory(packages)
        self.assertEqual(len(list(directory.iterdir())),2)
        self.assertFalse(list(directory.glob('*.json')))
        self.assertEqual(len(self.app.releases.list()),0)
        self.assertEqual(original,self.app.releases.load(self.batch)[1])
        self.assertFalse(self.app.releases.root.exists())

    async def test_legacy_batch_cannot_deploy_or_export(self):
        from tests.legacy_batches import legacy_batch
        batch=legacy_batch(self.app)
        with self.assertRaisesRegex(ValueError,'当前设置'):
            await self.app.deployment.execute(batch,'v2.11.7',AsyncMock(),AsyncMock(),lambda _:None,lambda _:None,threading.Event())
        with self.assertRaisesRegex(ValueError,'当前设置'):
            self.app.releases.assemble(batch,'v2.11.7',password='export')

    async def test_new_deployment_exposes_fixed_two_level_plan(self):
        from app.network.task_progress import TaskState
        events=[];model=TaskState()
        def progress(event):events.append(event);model.update(event)
        async def run(packages,confirm,decide,notify):
            for package in packages.packages:
                notify(deployment_update(package.node_id,'upload','uploading'));notify(deployment_update(package.node_id,'upload','uploaded'))
            for package in packages.packages:
                notify(deployment_update(package.node_id,'install','deploying'));notify(deployment_update(package.node_id,'install','success'))
            return {p.node_id:'success' for p in packages.packages}
        @asynccontextmanager
        async def connect(*args):yield SimpleNamespace(run=AsyncMock())
        with patch.object(self.app.deployment,'probe_node',new=AsyncMock(return_value='v2.11.7')),patch.object(self.app.deployment,'run',side_effect=run),patch.object(self.app.ssh,'connect',connect):
            result=await self.app.deployment.execute(None,'v2.11.7',AsyncMock(),AsyncMock(),lambda _:None,progress,threading.Event())
        self.assertTrue(result['success'])
        self.assertEqual([name for name,_ in model.sections()],['准备运行材料','部署到节点'])
        self.assertTrue(all(e.steps==events[0].steps and e.groups==events[0].groups for e in events))
        model.finish('success');self.assertEqual(model.counts(),(10,10))
        self.assertIn(result['batch'].version,model.notes.values())
