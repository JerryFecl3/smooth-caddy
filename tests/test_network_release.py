import io
import json
from pathlib import Path
import subprocess
import tarfile
from unittest.mock import patch
import tempfile
import unittest
from app.network.application import Application
from app.network.models import Listen
from app.network.generator import generate

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Application(self.tmp.name);self.addCleanup(self.app.close)
        self.app.security.setup('secret')

    def configured(self):
        app=self.app
        rid=app.create('regions','内网')
        parent=app.create('nodes','网关');child=app.create('nodes','入口')
        site=app.create('sites','站点')
        cfg=app.snapshot()
        for i,node in enumerate(cfg.nodes):
            node.platform='debian_13' if i==0 else 'openwrt_25_12'
            node.arch='amd64';node.areas[rid]=Listen(True,'127.0.0.'+str(i+2))
        cfg.nodes[1].mode='via_upstream';cfg.nodes[1].upstream=(parent,rid)
        cfg.sites[0].domain='example.test';cfg.sites[0].source='http://127.0.0.1:9000';cfg.sites[0].areas[rid]='https_mtls'
        app.save_configuration(cfg);app.certificates.initialize('Network')
        return app.snapshot(),rid,parent,child

    def test_cancel_during_batch_write_does_not_publish(self):
        import threading
        from app.network.task_progress import TaskCancelled
        self.configured();cancel=threading.Event()
        def step(event):
            if event.index==1:cancel.set()
        with self.assertRaises(TaskCancelled):self.app.releases.create(task_progress=step,cancel=cancel)
        self.assertEqual(self.app.releases.list(),[])
        self.assertFalse(list(self.app.releases.root.glob('.prepare-*')))

    def test_legacy_batch_load_and_package_preserve_original_files(self):
        from app.network.releases import sha
        self.configured()
        batch = self.app.releases.create()
        directory = self.app.releases.directory(batch)
        metadata = json.loads((directory/'metadata.json').read_bytes())
        self.assertEqual(metadata['format'], 2)
        expected, materials = self.app.releases.load(batch)
        # Reconstruct the v1 metadata persisted by released versions.
        metadata['format'] = 1
        for node in metadata['configuration']['nodes']:
            node['mode'] = {'direct':'直连源头','via_upstream':'经上游转发'}[node['mode']]
            node['platform'] = {'debian_13':'Debian 13','openwrt_25_12':'OpenWrt 25.12'}[node['platform']]
        for site in metadata['configuration']['sites']:
            site['tls_source'] = {'private_ca':'私有 CA','public_ca':'公共 CA'}[site['tls_source']]
            site['areas'] = {rid: {'disabled':'不提供服务','http':'HTTP','https':'HTTPS','https_mtls':'HTTPS + mTLS'}[mode]
                             for rid, mode in site['areas'].items()}
        payload = json.dumps(metadata, ensure_ascii=False).encode()
        (directory/'metadata.json').write_bytes(payload)
        batch.metadata_sha256 = sha(payload)
        self.app.releases._index([batch])
        before = {p.relative_to(directory):p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        index = (self.app.releases.root/'index.json').read_bytes()
        loaded, loaded_materials = self.app.releases.load(self.app.releases.list()[0])
        self.assertEqual(loaded.to_dict(), expected.to_dict())
        self.assertEqual(loaded_materials, materials)
        packages = self.app.releases.assemble(batch, 'v2.11.7', set(), destination='tasks')
        self.app.releases.check_packages(packages)
        self.assertEqual([p.platform for p in packages.packages], ['debian_13','openwrt_25_12'])
        self.assertEqual((self.app.releases.root/'index.json').read_bytes(), index)
        self.assertEqual({p.relative_to(directory):p.read_bytes() for p in directory.rglob('*') if p.is_file()}, before)
        (directory/'metadata.json').write_bytes(payload + b' ')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.app.releases.load(batch)

    def test_generator_peer_pinning_and_private_key_isolation(self):
        cfg,rid,parent,child=self.configured()
        result=generate(cfg,self.app.certificates,'20261008-120000')
        root=json.loads(result[parent]['caddy.json'])
        entry=json.loads(result[child]['caddy.json'])
        self.assertNotIn('certificates/node-'+child+'.key',result[parent])
        self.assertNotIn('certificates/relay-'+parent+'-'+rid+'.key',result[child])
        relay=root['apps']['http']['servers'][rid+'-relay']
        verifier=relay['tls_connection_policies'][0]['client_authentication']['verifiers'][0]
        self.assertTrue(verifier['leaf_certs_loaders'][0]['files'][0].endswith(child+'.leaf.pem'))
        upstream=entry['apps']['http']['servers'][rid+'-relay']['routes'][0]['handle'][0]['transport']['tls']
        self.assertEqual(len(upstream['ca']['pem_files']),1)
        self.assertTrue(upstream['ca']['pem_files'][0].endswith('.leaf.pem'))
        user=root['apps']['http']['servers'][rid+'-https']['tls_connection_policies'][0]
        self.assertEqual(user['client_authentication']['verifiers'][0]['leaf_certs_loaders'][0]['files'],[])

    def test_offline_package_index_and_integrity(self):
        cfg, *_=self.configured()
        with patch('app.network.releases.fetch',side_effect=AssertionError('offline')):
            batch=self.app.releases.create()
            release=self.app.releases.assemble(batch,'v2.11.7',set(),destination='tasks')
        self.assertEqual(len(release.packages),2)
        self.app.releases.check_packages(release)
        payload=(self.app.releases.directory(release)/release.packages[0].filename).read_bytes()
        marker=b'__CADDY_PAYLOAD__\n'
        self.assertIn(marker,payload)
        header,archive=payload.split(marker,1)
        with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
            self.assertNotIn('caddy',tar.getnames())
            self.assertIn('release/caddy.json',tar.getnames())
            script=tar.extractfile('manage.sh').read()
            checked=subprocess.run(['sh','-n'],input=script,capture_output=True)
            self.assertEqual(checked.returncode,0,checked.stderr)
        package=(self.app.releases.directory(release)/release.packages[0].filename)
        package.write_bytes(b'broken')
        self.assertEqual(self.app.releases.list()[0].version,release.version)
        with self.assertRaises(ValueError):self.app.releases.check_packages(release)
        self.app.releases.delete(release.version)
        self.assertEqual(self.app.releases.list(),[])

    def test_export_failure_does_not_publish_partial_batch(self):
        self.configured()
        with patch('app.network.releases.generate',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.app.releases.create()
        self.assertEqual(self.app.releases.list(),[])
        self.assertEqual(list(self.app.releases.root.glob('.prepare-*')),[])


    def test_global_origin_tls_option_leaves_relay_verification_intact(self):
        cfg, rid, parent, child = self.configured()
        cfg.sites[0].source = 'https://10.10.10.251:8006'
        for verify in (True, False):
            cfg.verify_origin_https = verify
            result = generate(cfg, self.app.certificates, '20261008-120000')
            def transport(node):
                return json.loads(result[node]['caddy.json'])['apps']['http']['servers'][rid+'-relay']['routes'][0]['handle'][0]['transport']
            origin, relay = transport(parent), transport(child)
            self.assertEqual(origin['tls'].get('insecure_skip_verify', False), not verify)
            self.assertNotIn('insecure_skip_verify', relay['tls'])
            self.assertIn('ca', relay['tls'])
            self.assertIn('client_certificate_file', relay['tls'])
        cfg.sites[0].source = 'http://10.10.10.251:8006'
        result = generate(cfg, self.app.certificates, '20261008-120000')
        self.assertNotIn('tls', transport(parent))


    def test_release_survives_move(self):
        import shutil
        self.configured()
        release=self.app.releases.create()
        self.assertEqual(release.directory,'releases/'+release.version)
        root=self.app.releases.directory(release)
        with tempfile.TemporaryDirectory() as target:
            moved=Path(target)/'copied-data'
            shutil.copytree(self.tmp.name,moved)
            other=Application(moved)
            try:
                record=other.releases.list()[0]
                self.assertEqual(record.directory,'releases/'+release.version)
                other.security.unlock('secret')
                other.releases.check(record)
                self.assertNotIn(self.tmp.name,(other.releases.root/'index.json').read_text(encoding='utf-8'))
                self.assertNotIn(self.tmp.name,(other.releases.directory(record)/'metadata.json').read_text(encoding='utf-8'))
                other.security.unlock('secret')
                other.releases.delete(record.version)
                self.assertTrue(root.exists())
            finally:other.close()


class BinaryVersionTests(unittest.TestCase):
    def test_official_metadata_larger_than_two_mib(self):
        from app.network.releases import BinaryCache
        payload=json.dumps([
            {'tag_name':'v2.11.7','draft':False,'prerelease':False,'body':'x'*(2*1024*1024)},
            {'tag_name':'v2.12.0-beta.1','draft':False,'prerelease':True},
        ]).encode()
        with tempfile.TemporaryDirectory() as directory:
            cache=BinaryCache(directory)
            response=io.BytesIO(payload)
            response.headers={'ETag':'\"version-list-1\"'}
            with patch('app.network.releases.urlopen',return_value=response):
                self.assertEqual(cache.online_versions(),['v2.11.7'])
            self.assertEqual(cache.catalog.read_bytes(),payload)
            self.assertEqual(BinaryCache(directory).cached_versions(),['v2.11.7'])
            with patch('app.network.releases.urlopen',side_effect=OSError('offline')):
                with self.assertRaises(OSError):cache.online_versions()
            self.assertEqual(cache.cached_versions(),['v2.11.7'])


    def test_unchanged_catalog_uses_conditional_request_without_rewrite(self):
        from urllib.error import HTTPError
        from app.network.releases import BinaryCache
        with tempfile.TemporaryDirectory() as directory:
            cache=BinaryCache(directory)
            payload=json.dumps([{'tag_name':'v2.11.7','draft':False,'prerelease':False}]).encode()
            response=io.BytesIO(payload)
            response.headers={'ETag':'"abc"','Last-Modified':'Thu, 08 Oct 2026 00:00:00 GMT'}
            with patch('app.network.releases.urlopen',return_value=response): cache.online_versions()
            timestamp=cache.catalog.stat().st_mtime_ns
            def unchanged(request, **kwargs):
                self.assertEqual(request.get_header('If-none-match'),'"abc"')
                self.assertEqual(request.get_header('If-modified-since'),response.headers['Last-Modified'])
                raise HTTPError(request.full_url,304,'Not Modified',{},None)
            with patch('app.network.releases.urlopen',side_effect=unchanged):
                self.assertEqual(cache.online_versions(),['v2.11.7'])
            self.assertEqual(cache.catalog.stat().st_mtime_ns,timestamp)

class DownloadProgressTests(unittest.TestCase):
    def test_streamed_download_reports_bytes_and_rejects_incomplete_data(self):
        import io
        from unittest.mock import patch
        from app.network.downloads import fetch
        data=b'x'*(600*1024)
        for length in (str(len(data)),None):
            response=io.BytesIO(data);response.headers={} if length is None else {'Content-Length':length}
            events=[]
            with patch('app.network.downloads.urlopen',return_value=response):
                self.assertEqual(fetch('https://example.test/file',progress=events.append),data)
            self.assertEqual(events[0].received,0)
            self.assertEqual(events[-1].received,len(data))
            self.assertEqual(events[-1].total,len(data) if length else None)
            self.assertGreater(events[-1].speed,0)
        response=io.BytesIO(b'short');response.headers={'Content-Length':'100'}
        with patch('app.network.downloads.urlopen',return_value=response),self.assertRaisesRegex(ValueError,'不完整'):
            fetch('https://example.test/file')
        response=io.BytesIO(b'too big');response.headers={}
        with patch('app.network.downloads.urlopen',return_value=response),self.assertRaisesRegex(ValueError,'大小限制'):
            fetch('https://example.test/file',limit=3)
