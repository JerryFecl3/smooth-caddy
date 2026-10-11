from tests.legacy_batches import legacy_batch
"""Shared relay identity, versioned topology migration, and optional real Caddy traffic."""
from contextlib import closing
from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID
from app.network.application import Application
from app.network.models import Service, service_policy, Listen, RELAY_SERVER_NAME, configuration_errors
from app.network.migrations import configuration_v4
from app.network.generator import generate
from app.network.releases import sha


class RelayMigrationTests(unittest.TestCase):
    def test_v4_backup_url_resolution_and_legacy_metadata(self):
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            app.security.setup('secret');app.certificates.initialize('Test')
            rid=app.create('regions','LAN')
            app.create('nodes','A');app.create('nodes','B')
            cfg=app.snapshot()
            for node in cfg.nodes:
                node.platform='debian_13';node.arch='amd64';node.ssh_hops=[['192.0.2.1']]
            cfg.nodes[0].areas[rid]=Listen(True,['2001:db8::1'],['80','443','9443'])
            cfg.nodes[1].upstream_url='https://[2001:db8::1]:9443'
            app.save_configuration(cfg)
            batch=legacy_batch(app);folder=app.releases.directory(batch)
            metadata=json.loads((folder/'metadata.json').read_bytes())
            value=metadata['configuration']
            for index,node in enumerate(value['nodes']):
                for area in node['areas'].values(): area['ip'] = area.pop('ips')[0]
                node.pop('upstream_url');node['mode']='via_upstream' if index else 'direct'
                node['upstream']=[cfg.nodes[0].id,rid] if index else None
            original=deepcopy(value)
            converted=configuration_v4(value)
            self.assertEqual(converted.nodes[1].upstream_url,'https://[2001:db8::1]:9443')
            self.assertEqual(converted.nodes[1].ssh_hops,[['192.0.2.1']])
            self.assertEqual(value,original)
            broken=deepcopy(value);broken['nodes'][1]['upstream'][0]='deleted'
            invalid=configuration_v4(broken)
            self.assertEqual(invalid.nodes[1].upstream_url,'https://')
            self.assertIn(('nodes',cfg.nodes[1].id,'upstream_url'),configuration_errors(invalid))
            metadata['format']=3
            payload=json.dumps(metadata).encode();(folder/'metadata.json').write_bytes(payload)
            batch.metadata_sha256=sha(payload);app.releases._index([batch])
            self.assertEqual(app.releases.load(batch)[0].nodes[1].upstream_url,converted.nodes[1].upstream_url)
            self.assertEqual((folder/'metadata.json').read_bytes(),payload)
            app.store.db.execute('UPDATE configuration SET payload=?',(json.dumps(value),))
            app.store.db.execute('PRAGMA user_version=4')
            with closing(Application(directory)) as upgraded:
                self.assertEqual(upgraded.snapshot().nodes[1].upstream_url,converted.nodes[1].upstream_url)
                self.assertEqual(upgraded.store.db.execute('PRAGMA user_version').fetchone()[0],10)
            backup=next((Path(directory)/'backups').glob('smooth-caddy-v4-*.db'))
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(json.loads(db.execute('SELECT payload FROM configuration').fetchone()[0]),original)


@unittest.skipUnless(os.environ.get('CADDY_TEST_BINARY'), 'Set CADDY_TEST_BINARY for native Caddy integration')
class CaddyRelayTests(unittest.TestCase):
    def test_arbitrary_relay_client_host_routing_and_authentication_boundaries(self):
        binary=os.environ['CADDY_TEST_BINARY']
        with tempfile.TemporaryDirectory() as directory, closing(Application(directory)) as app:
            root=Path(directory)
            app.security.setup('secret');app.certificates.initialize('Relay test')
            rid=app.create('regions','LAN')
            app.create('nodes','A');app.create('nodes','B')
            app.create('sites','Web');app.create('sites','Protected')
            class Origin(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200);self.end_headers()
                    self.wfile.write((self.headers['Host']+self.path).encode())
                def log_message(self,*args):pass
            origin=ThreadingHTTPServer(('127.0.0.1',0),Origin)
            thread=threading.Thread(target=origin.serve_forever,daemon=True);thread.start()
            self.addCleanup(origin.server_close);self.addCleanup(origin.shutdown)
            def port():
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));return str(sock.getsockname()[1])
            cfg=app.snapshot()
            for node in cfg.nodes:
                node.platform='debian_13';node.arch='amd64';node.ssh_hops=[['127.0.0.1']]
                node.areas[rid]=Listen(True,['127.0.0.1'],[port(),port(),port()])
            cfg.nodes[0].areas[rid].ips=['0.0.0.0','::']
            relay_port=int(cfg.nodes[1].areas[rid].ports[2])
            cfg.nodes[0].upstream_url=f'https://127.0.0.1:{relay_port}'
            for i,site in enumerate(cfg.sites):
                site.domain=('web.test','protected.test')[i]
                site.source=f'http://127.0.0.1:{origin.server_port}'
                site.areas[rid]=Service(True,mtls=bool(i))
            materials=generate(cfg,app.certificates,'test')
            processes=[];logs=[]
            try:
                for node in cfg.nodes:
                    folder=root/node.id;folder.mkdir()
                    for name,data in materials[node.id].items():
                        path=folder/name;path.parent.mkdir(exist_ok=True)
                        if name=='caddy.json':data=data.replace(b'/etc/smooth-caddy/releases/test',str(folder).encode())
                        path.write_bytes(data)
                    log=(folder/'log').open('w+');logs.append(log)
                    process=subprocess.Popen([binary,'run','--config',str(folder/'caddy.json')],stdout=log,stderr=log,
                        env=dict(os.environ,XDG_DATA_HOME=str(root/'caddy-data'),XDG_CONFIG_HOME=str(root/'caddy-config')))
                    processes.append(process)
                for node,process,log in zip(cfg.nodes,processes,logs):
                    deadline=time.monotonic()+10
                    while True:
                        if process.poll() is not None:
                            log.seek(0);self.fail(log.read())
                        try:
                            with socket.create_connection(('127.0.0.1',int(node.areas[rid].ports[0])),timeout=.2):break
                        except OSError:
                            if time.monotonic()>deadline:raise
                            time.sleep(.05)
                for host in ('127.0.0.1','::1'):
                    conn=http.client.HTTPConnection(host,int(cfg.nodes[0].areas[rid].ports[0]),timeout=3)
                    try:
                        conn.request('GET','/check?q=1',headers={'Host':'web.test:18443'})
                        response=conn.getresponse();body=response.read()
                        self.assertEqual(response.status,308,body)
                        self.assertIn('https://web.test:',response.getheader('Location'))
                    finally:conn.close()
                # A valid client not represented by any configured node is accepted.
                external=app.certificates.leaf('relay','Unlisted relay client',client=True)
                user=app.certificates.leaf('client','User',client=True)
                wrong_role=app.certificates.leaf('relay','Server only',dns=RELAY_SERVER_NAME)
                for label,material in [('external',external),('user',user),('wrong-role',wrong_role)]:
                    (root/(label+'.pem')).write_bytes(material.certificate+app.certificates.public('relay' if label!='user' else 'client'))
                    (root/(label+'.key')).write_bytes(material.private_key)
                def request(port, client=None, hostname=RELAY_SERVER_NAME, host='protected.test'):
                    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.load_verify_locations(cadata=app.certificates.public('root').decode())
                    if client:context.load_cert_chain(str(root/(client+'.pem')),str(root/(client+'.key')))
                    with socket.create_connection(('127.0.0.1',port),timeout=3) as raw:
                        with context.wrap_socket(raw,server_hostname=hostname) as sock:
                            sock.sendall(f'GET /relay HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
                            response=http.client.HTTPResponse(sock);response.begin()
                            return response.status,response.read()
                self.assertEqual(request(relay_port,'external'),(200,b'protected.test/relay'))
                for client in (None,'user','wrong-role'):
                    with self.subTest(client=client),self.assertRaises((ssl.SSLError,ConnectionError,http.client.HTTPException)):
                        request(relay_port,client)
                with self.assertRaises(ssl.SSLError):request(relay_port,'external','wrong.test')
                with self.assertRaises((ssl.SSLError,ConnectionError,http.client.HTTPException)):
                    request(int(cfg.nodes[1].areas[rid].ports[1]),'external','protected.test')
                cert=x509.load_pem_x509_certificate(materials[cfg.nodes[1].id][f'certificates/relay-{cfg.nodes[1].id}-{rid}.pem'])
                self.assertIn(RELAY_SERVER_NAME,cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName))
                self.assertEqual(list(cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value),[ExtendedKeyUsageOID.SERVER_AUTH])
            finally:
                for process in processes:
                    process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                for log in logs:log.close()
