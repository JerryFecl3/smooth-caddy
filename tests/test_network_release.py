from tests.legacy_batches import legacy_batch
import io
import json
from pathlib import Path
import subprocess
import tarfile
from unittest.mock import patch
import tempfile
import unittest
from app.network.application import Application
from app.network.models import Service, service_policy, Listen
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
            node.arch='amd64';node.ssh_hops=[['127.0.0.'+str(i+2)]];node.areas[rid]=Listen(True,['127.0.0.'+str(i+2)])
        cfg.nodes[1].upstream_url='https://127.0.0.2:8443'
        cfg.sites[0].domain='example.test';cfg.sites[0].source='http://127.0.0.1:9000';cfg.sites[0].areas[rid]=Service(True,mtls=True)
        cfg.nodes[1].ssh_hops=cfg.nodes[0].ssh_hops+cfg.nodes[1].ssh_hops
        app.save_configuration(cfg);app.certificates.initialize('Network')
        return app.snapshot(),rid,parent,child

    def test_cancel_during_batch_write_does_not_publish(self):
        import threading
        from app.network.task_progress import TaskCancelled
        self.configured();cancel=threading.Event()
        def step(event):
            if event.index==0:cancel.set()
        with self.assertRaises(TaskCancelled):self.app.releases.prepare(task_progress=step,cancel=cancel)
        self.assertEqual(self.app.releases.list(),[])
        self.assertFalse(list(self.app.releases.root.glob('.prepare-*')))

    def test_legacy_batch_load_and_package_preserve_original_files(self):
        from app.network.releases import sha
        self.configured()
        batch = legacy_batch(self.app)
        directory = self.app.releases.directory(batch)
        metadata = json.loads((directory/'metadata.json').read_bytes())
        self.assertEqual(metadata['format'], 5)
        expected, materials = self.app.releases.load(batch)
        # Reconstruct the v1 metadata persisted by released versions.
        self.legacy_nodes(metadata['configuration'])
        metadata['format'] = 1
        for node in metadata['configuration']['nodes']:
            node['ssh_ip'] = node.pop('ssh_hops')[-1][0]
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
        with self.assertRaisesRegex(ValueError,'当前设置'):
            self.app.releases.assemble(batch, 'v2.11.7', set(), destination='tasks')
        self.assertEqual((self.app.releases.root/'index.json').read_bytes(), index)
        self.assertEqual({p.relative_to(directory):p.read_bytes() for p in directory.rglob('*') if p.is_file()}, before)
        (directory/'metadata.json').write_bytes(payload + b' ')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.app.releases.load(batch)

    def test_metadata_v2_expands_ssh_without_rewriting_batch(self):
        from app.network.releases import sha
        self.configured()
        batch=legacy_batch(self.app);directory=self.app.releases.directory(batch)
        metadata=json.loads((directory/'metadata.json').read_bytes())
        self.legacy_nodes(metadata['configuration'])
        metadata['format']=2
        for node in metadata['configuration']['nodes']:
            node['ssh_ip']=node.pop('ssh_hops')[-1][0]
        payload=json.dumps(metadata).encode()
        (directory/'metadata.json').write_bytes(payload)
        batch.metadata_sha256=sha(payload);self.app.releases._index([batch])
        config,_=self.app.releases.load(batch)
        self.assertEqual(config.nodes[1].ssh_hops,[['127.0.0.2'],['127.0.0.3']])
        self.assertEqual((directory/'metadata.json').read_bytes(),payload)
        config.nodes[1].ssh_hops=[['192.0.2.99']]
        self.app.save_configuration(config)
        frozen,_=self.app.releases.load(batch)
        self.assertEqual(frozen.nodes[1].ssh_hops,[['127.0.0.2'],['127.0.0.3']])

    @staticmethod
    def legacy_nodes(value):
        parent=value['nodes'][0]['id'];rid=value['regions'][0]['id']
        for index,node in enumerate(value['nodes']):
            for area in node['areas'].values(): area['ip'] = area.pop('ips')[0]
            node.pop('upstream_url')
            node['mode']='via_upstream' if index else 'direct'
            node['upstream']=[parent,rid] if index else None

    def test_generator_shared_relay_trust_and_private_key_isolation(self):
        cfg,rid,parent,child=self.configured()
        result=generate(cfg,self.app.certificates,'20261008-120000')
        root=json.loads(result[parent]['caddy.json'])
        entry=json.loads(result[child]['caddy.json'])
        self.assertNotIn('certificates/node-'+child+'.key',result[parent])
        self.assertNotIn('certificates/relay-'+parent+'-'+rid+'.key',result[child])
        relay=root['apps']['http']['servers'][rid+'-relay']
        auth=relay['tls_connection_policies'][0]['client_authentication']
        self.assertEqual(auth['mode'],'require_and_verify')
        self.assertNotIn('verifiers',auth)
        self.assertTrue(auth['ca']['pem_files'][0].endswith('/relay-ca.pem'))
        upstream=entry['apps']['http']['servers'][rid+'-relay']['routes'][0]['handle'][0]['transport']['tls']
        self.assertEqual(len(upstream['ca']['pem_files']),1)
        self.assertTrue(upstream['ca']['pem_files'][0].endswith('/relay-ca.pem'))
        self.assertEqual(upstream['server_name'],'relay.smooth-caddy.internal')
        user=root['apps']['http']['servers'][rid+'-https']['tls_connection_policies'][0]
        self.assertEqual(user['client_authentication']['verifiers'][0]['leaf_certs_loaders'][0]['files'],[])

    def test_relay_dial_host_and_port_are_independent_of_listeners(self):
        cfg,rid,parent,child=self.configured()
        for url,dial in [('https://relay.example.net:19443','relay.example.net:19443'),
                         ('https://[2001:db8::42]:20443','[2001:db8::42]:20443')]:
            with self.subTest(url=url):
                cfg.nodes[1].upstream_url=url
                result=generate(cfg,self.app.certificates,'test')
                servers=json.loads(result[child]['caddy.json'])['apps']['http']['servers']
                proxy=servers[rid+'-relay']['routes'][0]['handle'][0]
                self.assertEqual(proxy['upstreams'],[{'dial':dial}])
                self.assertEqual(proxy['transport']['tls']['server_name'],'relay.smooth-caddy.internal')
                self.assertEqual(proxy['headers']['request']['set']['Host'],['{http.request.hostport}'])

    def test_https_plaintext_redirect_preserves_http_and_mtls_rules(self):
        cfg,rid,parent,child=self.configured()
        from app.network.models import Service, service_policy, Site
        cfg.sites.append(Site('http-site', 'Plain HTTP', 'plain.test', 'http://127.0.0.1:9000', {rid:Service(True)}))
        for mode in ('https', 'https_mtls'):
            for port in ('443', '9443'):
                with self.subTest(mode=mode, port=port):
                    cfg.sites[0].areas[rid]=Service(True,mtls=mode=='https_mtls')
                    for node in cfg.nodes:
                        node.areas[rid].ports[1]=port
                    result=generate(cfg,self.app.certificates,'20261008-120000')
                    for node in cfg.nodes:
                        servers=json.loads(result[node.id]['caddy.json'])['apps']['http']['servers']
                        https=servers[rid+'-https']
                        self.assertEqual(https['listener_wrappers'], [{'wrapper':'http_redirect'}, {'wrapper':'tls'}])
                        self.assertEqual('client_authentication' in https['tls_connection_policies'][0], mode=='https_mtls')
                        self.assertNotIn('listener_wrappers', servers[rid+'-relay'])
                        http=servers['http-0']
                        self.assertNotIn('listener_wrappers', http)
                        redirect=http['routes'][0]['handle'][0]
                        self.assertEqual(redirect['status_code'], 308)
                        self.assertEqual(redirect['headers']['Location'],
                                         ['https://example.test'+(':'+port if port!='443' else '')+'{http.request.uri}'])
                        self.assertEqual(http['routes'][1]['handle'][0]['status_code'],308)
    def test_offline_package_index_and_integrity(self):
        cfg, *_=self.configured()
        with patch('app.network.releases.fetch',side_effect=AssertionError('offline')):
            batch=self.app.releases.prepare()
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
        self.assertEqual(self.app.releases.list(),[])
        with self.assertRaises(ValueError):self.app.releases.check_packages(release)
        self.app.releases.cleanup(release)
        self.assertEqual(self.app.releases.list(),[])

    def test_export_failure_does_not_publish_partial_batch(self):
        self.configured()
        with patch('app.network.releases.generate',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.app.releases.prepare()
        self.assertEqual(self.app.releases.list(),[])
        self.assertEqual(list(self.app.releases.root.glob('.prepare-*')),[])


    def test_site_origin_tls_option_leaves_relay_verification_intact(self):
        cfg, rid, parent, child = self.configured()
        cfg.sites[0].source = 'https://10.10.10.251:8006'
        for verify in (True, False):
            cfg.sites[0].verify_origin_https = verify
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
        release=legacy_batch(self.app)
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
