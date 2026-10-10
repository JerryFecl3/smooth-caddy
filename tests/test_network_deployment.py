import tempfile
import unittest
from types import SimpleNamespace
from contextlib import asynccontextmanager, closing
from unittest.mock import patch
from app.network.application import Application
from app.network.releases import PackageSet, Package

class DeploymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_uploads_before_installs_retry_skip_and_stop(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('secret')
            ids=[app.create('nodes',x) for x in ('one','two','three')]
            cfg=app.snapshot()
            for i,n in enumerate(cfg.nodes):n.ssh_ip='127.0.0.'+str(i+1)
            app.save_configuration(cfg)
            packages=[Package(i,n,'debian_13','amd64',i+'.run',1,'digest') for i,n in zip(ids,('one','two','three'))]
            release=PackageSet('20261008-120000','v2.11.7','tasks/attempt',packages,cfg.to_dict())
            events=[];failures={ids[0]:1,ids[1]:2}
            class Connection:
                def __init__(self,identity):self.identity=identity
                async def run(self,command,**kwargs):
                    if command.startswith('journalctl'):return SimpleNamespace(stdout='bind: address already in use',exit_status=0)
                    if command.startswith('sha256sum'):return SimpleNamespace(stdout='digest file',exit_status=0)
                    events.append(('install',self.identity))
                    count=failures.get(self.identity,0)
                    if count:
                        failures[self.identity]-=1
                        return SimpleNamespace(exit_status=1,stderr='failed',stdout='')
                    return SimpleNamespace(exit_status=0,stderr='',stdout='')
            @asynccontextmanager
            async def connect(route,confirm):yield Connection(route[-1].id)
            async def upload(local,target):events.append(('upload',target[0].identity))
            async def decide(issue):
                self.assertIn('部署退出码：1', issue.message)
                self.assertIn('bind: address already in use', issue.message)
                return 'retry' if issue.node_id==ids[0] else 'skip'
            async def confirm(host):return True
            with patch.object(app.releases,'check_packages'),patch.object(app.ssh,'connect',connect),patch('asyncssh.scp',upload):
                result=await app.deployment.run(release,confirm,decide,lambda *args:None)
            self.assertEqual(events[:3],[('upload',i) for i in ids])
            self.assertEqual(result[ids[0]],'success')
            self.assertEqual(result[ids[1]],'skipped')
            self.assertEqual(result[ids[2]],'success')

    async def test_ssh_reset_preserves_trusted_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory)
            app.security.setup('secret')
            try:
                public=app.ssh.public()
                app.store.db.execute('INSERT INTO hosts VALUES (?,?)',('node',b'known-key'))
                app.ssh.reset()
                self.assertNotEqual(public,app.ssh.public())
                self.assertEqual(app.ssh.trusted_count(),1)
            finally:app.close()

    async def test_uncertain_install_queries_without_reinstalling(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('secret')
            identity=app.create('nodes','node')
            cfg=app.snapshot();cfg.nodes[0].ssh_ip='127.0.0.1';app.save_configuration(cfg)
            release=PackageSet('20261008-120000','v2.11.7','tasks/attempt',
                            [Package(identity,'node','debian_13','amd64','node.run',1,'digest')],cfg.to_dict())
            commands=[]
            class Connection:
                async def run(self,command,**kwargs):
                    commands.append(command)
                    if command.startswith('sha256sum'):return SimpleNamespace(stdout='digest file')
                    if command.startswith('sh '):raise OSError('connection lost')
                    return SimpleNamespace(exit_status=0,stdout='selected=20261008-120000\nstate=running\n')
            @asynccontextmanager
            async def connect(*args):yield Connection()
            async def upload(*args):pass
            async def decide(issue):
                self.assertTrue(issue.uncertain)
                return 'retry'
            with patch.object(app.releases,'check_packages'),patch.object(app.ssh,'connect',connect),patch('asyncssh.scp',upload):
                statuses=await app.deployment.run(release,None,decide,lambda *args:None)
            self.assertEqual(statuses[identity],'success')
            self.assertEqual(sum(c.startswith('sh ') for c in commands),1)
            self.assertEqual(sum(c.endswith(' status') for c in commands),1)
