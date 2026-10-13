"""Site entry rules, settings compatibility and real Caddy path matching."""
from contextlib import closing
from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from app.network.application import Application
from app.network.archives import encode, decode
from app.network.models import Configuration, Site, Listen, Service, validate_site_paths, configuration_errors
from app.network.generator import generate
from tests.ui_helpers import ReadyTerminal


def setup(app):
    app.security.setup('test');app.certificates.initialize('Test')
    rid=app.create('regions','LAN');app.create('nodes','Origin');app.create('nodes','Relay');app.create('sites','Web')
    cfg=app.snapshot()
    for node in cfg.nodes:
        node.platform='debian_13';node.arch='amd64';node.ssh_hops=[['127.0.0.1']]
        node.areas[rid]=Listen(True,['127.0.0.1'],relay_enabled=True)
    cfg.nodes[1].upstream_url='https://127.0.0.1:8443'
    site=cfg.sites[0];site.domain='example.test';site.source='http://127.0.0.1:9999';site.areas[rid]=Service(True)
    site.homepage_redirect='/s/start';site.allowed_paths=['/s/','/assets/']
    app.save_configuration(cfg)
    return cfg,rid


class PathTests(unittest.TestCase):
    def test_validation_and_archives(self):
        for redirect,paths in [('',[]),('/ui/',[]),('/s/start',['/s/']),('/s',['/s/']),('/ui/',['/'])]:
            validate_site_paths(redirect,paths)
        for redirect,paths in [('/',[]),('//elsewhere',[]),('/ui?secret=x',[]),('/s/../admin',[]),
                               ('/ui/', ['/s/']),('', ['s/']),('', ['/s*']),('', ['/s/%2e']),
                               ('', ['/s/../']),('', ['/s\\admin']),('', ['/s/{query}']),('', ['/s/\n'])]:
            with self.subTest(redirect=redirect,paths=paths),self.assertRaises(ValueError):validate_site_paths(redirect,paths)
        cfg=Configuration(sites=[Site('a'*32,'Web',homepage_redirect='/s/start',allowed_paths=['/s/'])])
        current=encode(cfg,'Test');self.assertEqual(current['format'],5);self.assertEqual(decode(current),cfg)
        old=deepcopy(current);old['format']=4
        for site in old['configuration']['sites']:
            site.pop('homepage_redirect');site.pop('allowed_paths')
        loaded=decode(old);self.assertEqual(loaded.sites[0].homepage_redirect,'');self.assertEqual(loaded.sites[0].allowed_paths,[])
        broken=deepcopy(current);broken['configuration']['sites'][0]['allowed_paths']='bad'
        with self.assertRaises(ValueError):decode(broken)
        # Invalid drafts may be archived but block generation.
        cfg.sites[0].homepage_redirect='/other'
        self.assertIn(('sites','a'*32,'source'),configuration_errors(decode(encode(cfg,'Draft'))))

    def test_database_v10_backup_and_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            with closing(Application(directory)) as app:
                cfg=Configuration(sites=[Site('a'*32,'Web')]);old=cfg.to_dict()
                for site in old['sites']:
                    site.pop('homepage_redirect');site.pop('allowed_paths')
                app.store.db.execute('UPDATE configuration SET payload=?',(json.dumps(old),))
                app.store.db.execute('PRAGMA user_version=10')
            with closing(Application(directory)) as app:
                self.assertEqual(app.snapshot(),Configuration(sites=[Site('a'*32,'Web')],revision=1))
                self.assertEqual(app.store.db.execute('PRAGMA user_version').fetchone()[0],11)
                backup=next(app.store.directory.glob('backups/smooth-caddy-v10-*.db'))
                with closing(sqlite3.connect(backup)) as db:
                    self.assertEqual(json.loads(db.execute('SELECT payload FROM configuration').fetchone()[0]),old)
            with closing(Application(directory)) as app:self.assertEqual(len(list(app.store.directory.glob('backups/*.db'))),1)

    def test_rules_only_on_public_https_and_no_rewrite(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            cfg,rid=setup(app)
            materials=generate(cfg,app.certificates,'test')
            for node in cfg.nodes:
                servers=json.loads(materials[node.id]['caddy.json'])['apps']['http']['servers']
                routes=servers[rid+'-https']['routes']
                self.assertEqual(routes[0]['handle'][0]['status_code'],302)
                self.assertEqual(routes[1]['match'][0]['path'],['/s','/s/*','/assets','/assets/*'])
                self.assertEqual(routes[2]['handle'][0]['status_code'],404)
                self.assertEqual(servers[rid+'-relay']['routes'][0]['handle'][0]['handler'],'reverse_proxy')
                self.assertNotIn('path',servers[rid+'-relay']['routes'][0]['match'][0])
                self.assertNotIn('rewrite',json.dumps(servers))


class PathFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_persist_and_reject_outside_redirect(self):
        from textual.widgets import Input,TextArea
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            cfg,rid=setup(app);ui=ReadyTerminal(app)
            async with ui.run_test(size=(140,40)) as pilot:
                ui.page='sites';ui.render_page();await pilot.pause()
                table=ui.query_one('#matrix');table.move_cursor(row=0,column=ui.col_keys.index('source'));table.focus()
                await pilot.press('enter');await pilot.pause()
                form=ui.screen
                form.query_one('#redirect',Input).value='/blocked'
                await pilot.press('ctrl+s');await pilot.pause();self.assertIs(ui.screen,form)
                form.query_one('#redirect',Input).value='/assets/home'
                form.query_one('#paths',TextArea).load_text('/assets/\n/s/\n/assets/')
                await pilot.press('ctrl+s');await pilot.pause()
                self.assertEqual(len(ui.screen_stack),1)
                site=app.snapshot().sites[0]
                self.assertEqual(site.homepage_redirect,'/assets/home');self.assertEqual(site.allowed_paths,['/assets/','/s/'])


@unittest.skipUnless(os.environ.get('CADDY_TEST_BINARY'),'Set CADDY_TEST_BINARY for real routing tests')
class LivePathTests(unittest.TestCase):
    def test_generated_routes_forward_only_allowed_paths(self):
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            cfg,rid=setup(app)
            seen=[]
            class Origin(BaseHTTPRequestHandler):
                def do_GET(self):
                    seen.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(self.path.encode())
                def log_message(self,*args):pass
            origin=ThreadingHTTPServer(('127.0.0.1',0),Origin)
            thread=threading.Thread(target=origin.serve_forever,daemon=True);thread.start()
            self.addCleanup(origin.server_close);self.addCleanup(origin.shutdown)
            cfg.sites[0].source=f'http://127.0.0.1:{origin.server_port}'
            routes=json.loads(generate(cfg,app.certificates,'test')[cfg.nodes[0].id]['caddy.json'])['apps']['http']['servers'][rid+'-https']['routes']
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            # Use the exact generated routes without TLS to isolate HTTP matching.
            document={'admin':{'disabled':True},'apps':{'http':{'servers':{'test':{'listen':[f'127.0.0.1:{port}'],'routes':routes,'automatic_https':{'disable':True}}}}}}
            path=Path(directory)/'caddy.json';path.write_text(json.dumps(document))
            proc=subprocess.Popen([os.environ['CADDY_TEST_BINARY'],'run','--config',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            def stop():proc.terminate();proc.wait(timeout=10)
            self.addCleanup(stop)
            for attempt in range(100):
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                except OSError:time.sleep(.05)
            for target,status in [('/',302),('/?x=1',302),('/s',200),('/s/key?x=1',200),('/assets/a.js',200),
                                  ('/admin',404),('/something',404),('/s/../admin',404),('/s/%2e%2e/admin',404)]:
                with self.subTest(target=target):
                    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                    try:
                        conn.request('GET',target,headers={'Host':'example.test'});response=conn.getresponse();body=response.read()
                        self.assertEqual(response.status,status)
                        if status==302:self.assertEqual(response.getheader('Location'),'/s/start')
                        if status==200:self.assertEqual(body.decode(),target)
                    finally:conn.close()
            self.assertEqual(seen,['/s','/s/key?x=1','/assets/a.js'])
