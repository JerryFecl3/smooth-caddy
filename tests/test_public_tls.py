import asyncio
import os
from types import SimpleNamespace
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from app.network.application import Application
from app.network.public_tls import SECRET, SAVED, REUSED
from app.network.task_progress import TaskCancelled


def materials(domain,days=90):
    key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,domain)])
    now=datetime.now(timezone.utc)
    cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=days)).add_extension(x509.SubjectAlternativeName([x509.DNSName(domain),x509.DNSName('*.'+domain)]),critical=False).sign(key,hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM),key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())

class PublicTLSTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name);self.app.security.setup('secret');self.service=self.app.public_tls
    def tearDown(self):self.app.close();self.tmp.cleanup()
    def create(self,domain='example.com'):return self.service.save(domain,True,'alidns','account-id','private-token')
    def issue(self,identity,force=False):
        def run(cmd,env,home,cancel):
            self.assertIn('https://acme-staging-v02.api.letsencrypt.org/directory',cmd)
            self.assertEqual(env['ALICLOUD_SECRET_KEY'],'private-token')
            self.assertEqual('--renew-force' in cmd,force)
            cert,key=materials(self.service.get(identity)['domain']);folder=home/'certificates';folder.mkdir(exist_ok=True)
            domain=self.service.get(identity)['domain'];(folder/(domain+'.crt')).write_bytes(cert);(folder/(domain+'.key')).write_bytes(key)
            (home/'accounts').mkdir(exist_ok=True);(home/'accounts'/'account.json').write_text('{"account":"saved"}')
            return 0,''
        with patch.object(self.service.tool,'version',return_value='v5.1.0'),patch.object(self.service,'_run',side_effect=run):
            return self.service.issue(identity,force)
    def test_independent_records_and_environment(self):
        a=self.create();b=self.create('other.com')
        self.service.save('example.com',True,'alidns','different-id','different-key',a)
        self.assertEqual(self.service.secret(b)['credential_key'],'private-token')
        self.service.configure(False,'')
        self.assertEqual(len(self.service.list()),2)
        self.assertEqual(self.service.secret(a)['credential_key'],'different-key')
        with self.assertRaisesRegex(ValueError,'域名已存在'):self.create()
        self.service.configure(True,'')
        self.assertEqual(len(self.service.list()),2)
    def test_shared_credentials_and_isolated_results(self):
        identity=self.create()
        self.issue(identity)
        test_cert=self.service.get(identity)['certificate']
        test_key=self.service.secret(identity)['key']
        self.service.configure(False,'')
        self.assertEqual(self.service.get(identity)['certificate'],'')
        self.assertNotIn('key',self.service.secret(identity))
        cert,key=materials('example.com')
        def run(cmd,env,home,cancel):
            self.assertIn('https://acme-v02.api.letsencrypt.org/directory',cmd)
            self.assertFalse((home/'accounts').exists())
            folder=home/'certificates';folder.mkdir()
            (folder/'example.com.crt').write_bytes(cert)
            (folder/'example.com.key').write_bytes(key)
            # A concurrent environment switch must not redirect this result.
            self.service.configure(True,'')
            return 0,''
        with patch.object(self.service.tool,'version',return_value='v5.1.0'),patch.object(self.service,'_run',side_effect=run):
            self.service.issue(identity)
        self.assertEqual(self.service.get(identity)['certificate'],test_cert)
        self.assertEqual(self.service.secret(identity)['key'],test_key)
        self.service.configure(False,'')
        self.assertEqual(self.service.get(identity)['certificate'],cert.decode())
        self.service.save('example.com',True,'alidns','new-id','new-secret',identity)
        self.app.security.change_password('changed')
        self.app.security.lock();self.app.security.unlock('changed')
        self.service.configure(True,'')
        self.assertEqual(self.service.secret(identity)['credential_key'],'new-secret')
        self.assertEqual(self.service.secret(identity)['key'],test_key)
        self.service.configure(False,'')
        self.assertEqual(self.service.secret(identity)['key'],key.decode())
        self.service.delete(identity)
        self.assertFalse(self.service.list())
        self.assertFalse(self.app.store.db.execute("SELECT name FROM secrets WHERE name LIKE ?",('%'+identity+'%',)).fetchall())

    def test_issue_encryption_password_rotation_and_failure_preserves_material(self):
        identity=self.create();self.assertEqual(self.issue(identity),SAVED)
        old=self.service.get(identity)['certificate'];secret=self.service.secret(identity)
        blob=self.app.store.db.execute('SELECT value FROM secrets WHERE name=?',(SECRET+identity,)).fetchone()[0]
        self.assertNotIn(b'private-token',blob);self.assertNotIn(b'PRIVATE KEY',blob)
        self.app.security.change_password('new');self.app.security.lock();self.app.security.unlock('new')
        self.assertEqual(self.service.secret(identity),secret)
        self.assertEqual(self.service.issue(identity),REUSED)
        with patch.object(self.service.tool,'version',return_value='v5.1.0'),patch.object(self.service,'_run',return_value=(1,'denied private-token')):
            with self.assertRaisesRegex(ValueError,'隐藏'):self.service.issue(identity,True)
        self.assertEqual(self.service.get(identity)['certificate'],old)
        self.assertEqual(self.service.state(self.service.get(identity)),'有效')
        self.assertEqual(self.service.secret(identity),secret)
    def test_bad_key_or_domain_rejected_and_cancel_does_not_save(self):
        cert,key=materials('example.com');_,other=materials('other.com')
        with self.assertRaisesRegex(ValueError,'私钥'):self.service.validate(cert,other,['example.com'])
        with self.assertRaisesRegex(ValueError,'域名'):self.service.validate(cert,key,['else.com'])
        identity=self.create();cancel=threading.Event();cancel.set()
        with self.assertRaises(TaskCancelled):self.service.issue(identity,cancel=cancel)
        self.assertEqual(self.service.get(identity)['certificate'],'')
    def test_tool_uses_flat_executable_path(self):
        tool=self.service.tool
        self.assertEqual(tool.binary,Path(self.tmp.name).resolve()/'tool_lego'/('lego.exe' if os.name=='nt' else 'lego'))
        tool.root.mkdir(parents=True)
        tool.binary.write_text('#!/bin/sh\necho lego version 5.1.0\n')
        tool.binary.chmod(0o700)
        with patch('app.network.lego_tool.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='lego version 5.1.0')):
            self.assertEqual(tool.version(),'v5.1.0')

    def test_tool_install_checks_hash_and_preserves_old_on_failure(self):
        tool=self.service.tool;version='v5.1.0';name='lego_v5.1.0_linux_amd64.tar.gz';base='https://github.com/go-acme/lego/releases/download/'+version+'/'
        archive=io.BytesIO()
        with tarfile.open(fileobj=archive,mode='w:gz') as tar:
            payload=b'#!/bin/sh\necho lego version 5.1.0\n';entry=tarfile.TarInfo('lego');entry.size=len(payload);tar.addfile(entry,io.BytesIO(payload))
        data=archive.getvalue();checksum=(hashlib.sha256(data).hexdigest()+'  '+name).encode()
        release={'tag_name':version,'assets':[{'name':n,'browser_download_url':base+n} for n in (name,'lego_v5.1.0_checksums.txt')]}
        with patch('app.network.lego_tool.platform.system',return_value='Linux'),patch('app.network.lego_tool.platform.machine',return_value='x86_64'),patch('app.network.lego_tool.fetch',side_effect=[checksum,data]),patch('app.network.lego_tool.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='lego version 5.1.0')):
            self.assertEqual(tool.install(release),version)
        old=tool.binary.read_bytes()
        with patch('app.network.lego_tool.platform.system',return_value='Linux'),patch('app.network.lego_tool.platform.machine',return_value='x86_64'),patch('app.network.lego_tool.fetch',side_effect=[b'bad  '+name.encode(),data]):
            with self.assertRaisesRegex(ValueError,'校验失败'):tool.install(release)
        self.assertEqual(tool.binary.read_bytes(),old)

    def test_windows_lego_zip(self):
        import zipfile
        from app.network.lego_tool import LegoTool
        with patch('app.network.lego_tool.platform.system',return_value='Windows'),patch('app.network.lego_tool.platform.machine',return_value='AMD64'):
            tool=LegoTool(self.tmp.name)
            self.assertEqual(tool.binary.name,'lego.exe')
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as archive:archive.writestr('lego.exe',b'fake executable')
            data=buffer.getvalue();name='lego_v5.1.0_windows_amd64.zip'
            base='https://github.com/go-acme/lego/releases/download/v5.1.0/'
            release={'tag_name':'v5.1.0','assets':[{'name':n,'browser_download_url':base+n} for n in (name,'lego_checksums.txt')]}
            checks=(hashlib.sha256(data).hexdigest()+'  '+name).encode()
            with patch('app.network.lego_tool.fetch',side_effect=[checks,data]),patch('app.network.lego_tool.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='lego version 5.1.0')):
                self.assertEqual(tool.install(release),'v5.1.0')
            self.assertEqual(tool.binary.read_bytes(),b'fake executable')

class PublicTLSUITests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_page_create_details_settings_tool(self):
        from tests.ui_helpers import ReadyTerminal as Terminal
        from app.tui.widgets import Input,Select
        with tempfile.TemporaryDirectory() as directory:
            service=Application(directory);service.security.setup('secret');ui=Terminal(service)
            try:
                async with ui.run_test(size=(140,40)) as pilot:
                    await pilot.press('f6');await pilot.pause()
                    self.assertEqual(ui.page,'public_tls')
                    self.assertEqual(len(ui.screen_stack),1)
                    page=ui.screen
                    await pilot.press('ctrl+n');await pilot.pause()
                    for key,value in [('domain','example.com'),('credential_id','id'),('credential_key','key')]:ui.screen.query_one('#'+key,Input).value=value
                    await pilot.press('ctrl+s');await pilot.pause()
                    self.assertEqual(len(service.public_tls.list()),1)
                    await pilot.press('ctrl+o');await pilot.pause()
                    self.assertIn('example.com',ui.screen.caption)
                    await pilot.press('escape');await pilot.click('#pub-settings');await pilot.pause()
                    await pilot.press('space','ctrl+s');await pilot.pause()
                    self.assertEqual(len(service.public_tls.list()),1)
                    await pilot.click('#pub-tool');await pilot.pause()
                    self.assertEqual(ui.screen.caption,'lego 管理')
                    self.assertTrue(ui.screen.query_one('#lego-install').disabled)
                    await pilot.press('escape','escape');await pilot.pause()
                    self.assertEqual(ui.page,'public_tls')
                    self.assertEqual(service.snapshot().sites,[])
            finally:service.close()

class PublicTLSBatchTests(unittest.TestCase):
    def test_batch_continues_errors_and_pins_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.security.setup('secret');service=app.public_tls
            try:
                a=service.save('a.example.com',False,'alidns','id','key')
                b=service.save('b.example.com',False,'alidns','id','key')
                service.configure(False,'')
                c=service.save('c.example.com',False,'alidns','id','key')
                service.configure(True,'')
                steps=[]
                def outcome(identity,**kwargs):
                    if identity==a:raise ValueError('DNS 错误')
                    return REUSED
                with patch.object(service,'issue',side_effect=outcome) as issue:
                    result=service.issue_all([a,b],task_progress=steps.append)
                self.assertFalse(result['success'])
                self.assertEqual({call.args[0] for call in issue.call_args_list},{a,b})
                self.assertEqual({s.index:s.status for s in steps},{0:'失败',1:'无需申请'})
                with patch.object(service,'issue',return_value=REUSED) as issue:
                    self.assertTrue(service.issue_all([c])['success'])
                    self.assertTrue(issue.call_args.kwargs['staging'])
                cancel=threading.Event();cancel.set()
                with patch.object(service,'issue') as issue:
                    with self.assertRaises(TaskCancelled):service.issue_all([a,b],cancel=cancel)
                    issue.assert_not_called()
            finally:app.close()


class PublicTLSConcurrencyTests(unittest.TestCase):
    def test_domain_unique_regardless_of_wildcard(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.security.setup('secret')
            try:
                app.public_tls.save('Example.com',False,'alidns','id','key')
                with self.assertRaisesRegex(ValueError,'域名已存在'):
                    app.public_tls.save('example.com.',True,'alidns','id','key')
            finally:app.close()

    def test_three_workers_and_cancellation_leaves_queue_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);app.security.setup('secret');service=app.public_tls
            try:
                ids=[service.save(f'n{i}.example.com',False,'alidns','id','key') for i in range(6)]
                barrier=threading.Barrier(3);guard=threading.Lock();seen=[];cancel=threading.Event()
                def issue(identity,**kwargs):
                    with guard:seen.append(identity)
                    barrier.wait(timeout=5)
                    cancel.set()
                    raise TaskCancelled()
                with patch.object(service,'issue',side_effect=issue):
                    with self.assertRaises(TaskCancelled):service.issue_all(ids,cancel=cancel)
                self.assertEqual(set(seen),set(ids[:3]))
                self.assertEqual(len(seen),3)
            finally:app.close()

class PublicTLSConcurrentUITests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_rows_do_not_imply_earlier_rows_completed(self):
        from tests.ui_helpers import ReadyTerminal as Terminal
        from app.tui.public_tls import PublicTLSBatchProgress
        from app.network.task_progress import TaskStep
        with tempfile.TemporaryDirectory() as directory:
            app=Application(directory);ui=Terminal(app)
            finished=asyncio.Event()
            async def operation(*args):
                await finished.wait()
                return {'success':True,'errors':[]}
            try:
                async with ui.run_test(size=(140,40)) as pilot:
                    panel=PublicTLSBatchProgress('全部申请',operation,lambda _: '',asynchronous=True)
                    ui.push_screen(panel);await pilot.pause()
                    steps=('a.example.com','b.example.com','c.example.com','d.example.com')
                    panel.show_step(TaskStep(steps,0,'验证中',state='running'))
                    panel.show_step(TaskStep(steps,2,'已保存',state='success'))
                    lines=panel.query_one('#task-step-list').render().plain.splitlines()
                    self.assertTrue(lines[0].startswith('●'))
                    self.assertTrue(lines[1].startswith('○'))
                    self.assertTrue(lines[2].startswith('✓'))
                    self.assertTrue(lines[3].endswith('等待中'))
                    self.assertIn('1 / 4',panel.query_one('#task-summary').render().plain)
                    finished.set();await pilot.pause()
            finally:app.close()
