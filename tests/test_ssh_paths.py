import asyncio
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import asyncssh
from app.network.application import Application
from app.network.models import Configuration, Node, parse_ssh_path, ssh_route, configuration_errors
from app.network.migrations import configuration_v3
from app.network.storage import Store
from tests.ui_helpers import ReadyTerminal
from textual.widgets import TextArea


class SSHPathTests(unittest.TestCase):
    def test_parser_and_required_path(self):
        self.assertEqual(parse_ssh_path(' 192.0.2.1 \n\n 2001:0db8::1\n'), [['192.0.2.1'], ['2001:db8::1']])
        for value in ('', ' \n ', 'host.test', 'root@192.0.2.1', '192.0.2.1:22', '0.0.0.0', '::', 'ff02::1', 'fe80::1%eth0', '192.0.2.1 192.0.2.2'):
            with self.subTest(value=value), self.assertRaises(ValueError): parse_ssh_path(value)
        with self.assertRaisesRegex(ValueError, '第 3 行'):
            parse_ssh_path('192.0.2.1\n\ninvalid')
        node=Node('n','N')
        self.assertIn(('nodes','n','ssh_hops'), configuration_errors(Configuration(nodes=[node])))
        node.ssh_hops=[['192.0.2.1','192.0.2.2']]
        with self.assertRaises(ValueError): Configuration(nodes=[node]).to_dict()

    def test_route_is_independent_and_trust_is_scoped_by_prefix(self):
        node=Node('n','N',upstream_url='https://relay.example.test',ssh_hops=[['192.0.2.1'],['10.0.0.1']])
        config=Configuration(nodes=[node]);route=ssh_route(config,'n')
        self.assertEqual([h.address for h in route], ['192.0.2.1','10.0.0.1'])
        node.upstream_url=''
        self.assertEqual(ssh_route(config,'n'),route)
        node.ssh_hops[0]=['192.0.2.2']
        self.assertNotEqual(ssh_route(config,'n')[-1].trust_id,route[-1].trust_id)

    def test_v3_migration_backup_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            with closing(Application(directory)) as app:
                app.security.setup('secret')
                parent=app.create('nodes','Parent');child=app.create('nodes','Child')
                payload=app.snapshot().to_dict()
                for index,node in enumerate(payload['nodes']):
                    node.pop('ssh_hops');node.pop('upstream_url');node['ssh_ip']=f'192.0.2.{index+1}'
                    node['mode']='via_upstream' if index else 'direct'
                    node['upstream']=[parent,''] if index else None
                app.store.db.execute('UPDATE configuration SET payload=?',(json.dumps(payload),))
                app.store.db.execute('PRAGMA user_version=3')
                app.store.db.execute('INSERT INTO hosts VALUES (?,?)',(parent,b'old-trust'))
            original=json.loads(json.dumps(payload))
            with closing(Store(directory)) as store:
                cfg=store.load()
                self.assertEqual(cfg.nodes[1].ssh_hops,[['192.0.2.1'],['192.0.2.2']])
                self.assertEqual(cfg.revision,original['revision']+1)
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0],5)
                self.assertEqual(store.db.execute('SELECT key FROM hosts').fetchone()[0],b'old-trust')
                self.assertEqual(store.db.execute('SELECT count(*) FROM ssh_hosts').fetchone()[0],0)
            backup=next((Path(directory)/'backups').glob('smooth-caddy-v3-*.db'))
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(json.loads(db.execute('SELECT payload FROM configuration').fetchone()[0]),original)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
            with closing(Store(directory)) as store:
                self.assertEqual(store.load().revision,original['revision']+1)
            self.assertEqual(len(list((Path(directory)/'backups').glob('*.db'))),1)
            for broken in ('missing','invalid','cycle'):
                value=deepcopy(original)
                if broken=='missing': value['nodes'][1]['upstream']=['gone','']
                elif broken=='invalid': value['nodes'][0]['ssh_ip']=''
                else:
                    value['nodes'][0]['mode']='via_upstream';value['nodes'][0]['upstream']=[child,'']
                self.assertEqual(configuration_v3(value).nodes[1].ssh_hops,[])


class SSHConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_key_pinning_cleanup_and_changed_key(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('secret')
            route=ssh_route(Configuration(nodes=[Node('n','N',ssh_hops=[['192.0.2.1'],['10.0.0.1'],['2001:db8::1']])]),'n')
            keys=[asyncssh.generate_private_key('ssh-ed25519') for _ in route]
            connections=[];events=[];confirm=AsyncMock(return_value=True)
            class Connection:
                def __init__(self,index):self.index=index
                def close(self):events.append(self.index)
                async def wait_closed(self):pass
            async def probe(address,port,**kwargs):
                index=len(connections)
                self.assertEqual(address,route[index].address)
                self.assertIs(kwargs['tunnel'],connections[-1] if connections else None)
                return keys[index]
            async def connect(address,port,**kwargs):
                index=len(connections)
                self.assertEqual(kwargs['username'],'root');self.assertEqual(port,22)
                self.assertEqual(kwargs['known_hosts'][0],[keys[index]])
                self.assertIs(kwargs['tunnel'],connections[-1] if connections else None)
                conn=Connection(index);connections.append(conn);return conn
            with patch('asyncssh.get_server_host_key',side_effect=probe),patch('asyncssh.connect',side_effect=connect):
                async with app.ssh.connect(route,confirm) as conn:self.assertIs(conn,connections[-1])
                self.assertEqual(events,[2,1,0]);self.assertEqual(confirm.await_count,3)
                connections.clear();events.clear();confirm.reset_mock()
                async with app.ssh.connect(route,confirm):pass
                confirm.assert_not_awaited()
                keys[-1]=asyncssh.generate_private_key('ssh-ed25519')
                connections.clear();events.clear();confirm.reset_mock();confirm.return_value=False
                from app.network.deployment import Stopped
                with self.assertRaises(Stopped):
                    async with app.ssh.connect(route,confirm):pass
                self.assertEqual(events,[1,0])
                self.assertIsNotNone(confirm.call_args.args[0].previous)


class SSHPathUITests(unittest.IsolatedAsyncioTestCase):
    async def test_compact_multiline_edit_validation_and_cancel(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('secret');identity=app.create('nodes','Node')
            ui=ReadyTerminal(app)
            async with ui.run_test(size=(100,30)) as pilot:
                await pilot.press('f3');await pilot.pause()
                ui.query_one('#matrix').move_cursor(row=0,column=ui.col_keys.index('ssh_hops'))
                await pilot.press('enter');await pilot.pause()
                editor=ui.screen.query_one('#value',TextArea)
                self.assertIs(ui.focused,editor)
                self.assertEqual(editor.content_size.height,4)
                self.assertGreaterEqual(editor.content_size.width,45)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertIn('不能为空',str(ui.screen.query_one('#form-error').content))
                editor.load_text('192.0.2.1\nbad')
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertIn('第 2 行',str(ui.screen.query_one('#form-error').content))
                editor.load_text('192.0.2.1\n10.0.0.1\n2001:db8::1')
                await pilot.press('end','enter');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),2)
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),1)
                self.assertEqual(ui.cell_value(app.snapshot().nodes[0],'ssh_hops'),'2001:db8::1 (+2)')
                await pilot.press('enter');await pilot.pause()
                ui.screen.query_one('#value',TextArea).load_text('192.0.2.99')
                await pilot.press('escape');await pilot.pause()
                self.assertEqual(app.snapshot().nodes[0].ssh_hops[-1],['2001:db8::1'])
