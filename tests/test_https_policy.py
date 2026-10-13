from contextlib import closing
from copy import deepcopy
import json
import tempfile
import unittest
from app.network.application import Application
from app.network.models import Region, Node, Site, Listen, Service, Configuration, service_policy, configuration_errors
from app.network.generator import generate
from app.network.archives import encode, decode
from tests.legacy_batches import legacy_configuration


class HTTPSPolicyTests(unittest.TestCase):
    def config(self):
        regions=[Region('a'*32,'Private'),Region('b'*32,'Public','public_ca',True)]
        node=Node('c'*32,'Node',areas={r.id:Listen(True,['127.0.0.'+str(i+1)],relay_enabled=True) for i,r in enumerate(regions)},platform='debian_13',arch='amd64',ssh_hops=[['127.0.0.1']])
        site=Site('d'*32,'Web','example.test','http://127.0.0.1:9000',{r.id:Service(True) for r in regions})
        return Configuration(regions,[node],[site])

    def test_inheritance_override_and_archive_roundtrip(self):
        cfg=self.config();site=cfg.sites[0];r=cfg.regions[1]
        self.assertEqual(service_policy(site,r),Service(True,'public_ca',True))
        site.areas[r.id].mtls=False
        r.tls_source='private_ca'
        self.assertEqual(service_policy(site,r),Service(True,'private_ca',False))
        self.assertEqual(decode(encode(cfg,'draft')),cfg)
        doc=encode(cfg,'draft');doc['configuration']['sites'][0]['areas'][r.id]['mtls']=1
        with self.assertRaises(ValueError):decode(doc)

    def test_http_union_ambiguity_and_dual_certificates(self):
        cfg=self.config();node=cfg.nodes[0];site=cfg.sites[0]
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.certificates.initialize('Test')
            public=app.certificates.leaf('tls','Public test',dns=site.domain)
            files=generate(cfg,app.certificates,'test',{site.id:(public.certificate,public.private_key)})[node.id]
            servers=json.loads(files['caddy.json'])['apps']['http']['servers']
            self.assertEqual(len([key for key in servers if key.startswith('http-')]),2)
            tags=[]
            for r in cfg.regions:
                policy=servers[r.id+'-https']['tls_connection_policies'][0]
                tags.append(policy['certificate_selection']['any_tag'][0])
                self.assertEqual('client_authentication' in policy,r.mtls)
            self.assertNotEqual(*tags)
            node.areas[cfg.regions[1].id]=Listen(True,['127.0.0.1'],['80','9443','9444'],relay_enabled=True)
            self.assertIn('HTTP 跳转目标不唯一',str(configuration_errors(cfg)))
            site.areas[cfg.regions[1].id].enabled=False
            self.assertFalse(configuration_errors(cfg))
            files=generate(cfg,app.certificates,'test')[node.id]
            servers=json.loads(files['caddy.json'])['apps']['http']['servers']
            self.assertEqual(len([key for key in servers if key.startswith('http-')]),1)
            self.assertTrue(all(route['handle'][0]['handler']=='static_response' for route in servers['http-0']['routes']))

    def test_v7_migration_preserves_ports_and_http_becomes_private_https(self):
        cfg=self.config();cfg.nodes[0].areas[cfg.regions[0].id].ports=['80','9443','9444']
        cfg.nodes[0].areas[cfg.regions[0].id].ports[0]='8080'
        old=legacy_configuration(cfg)
        old['sites'][0]['areas'][cfg.regions[0].id]='http'
        with tempfile.TemporaryDirectory() as directory:
            with closing(Application(directory)) as app:
                app.store.db.execute('UPDATE configuration SET payload=?',(json.dumps(old),))
                app.store.db.execute('PRAGMA user_version=7')
            with closing(Application(directory)) as app:
                current=app.snapshot();site=current.sites[0]
                self.assertEqual(site.areas[cfg.regions[0].id],Service(True,'private_ca',False))
                self.assertEqual(current.nodes[0].areas[cfg.regions[0].id].ports[0],'8080')
                self.assertEqual(current.nodes[0].areas[cfg.regions[0].id].ports,['8080','9443','9444'])
                self.assertEqual(app.store.db.execute('PRAGMA user_version').fetchone()[0],11)
                self.assertEqual(len(list(app.store.directory.glob('backups/smooth-caddy-v7-*.db'))),1)
        from app.network.migrations import configuration_v7
        old['nodes'][0]['areas'][cfg.regions[1].id]['overrides'][0]='8081'
        self.assertEqual(configuration_v7(old).nodes[0].areas[cfg.regions[1].id].ports[0],'8081')

    def test_native_caddy_accepts_shared_wildcard_redirects(self):
        import os,subprocess
        from pathlib import Path
        binary=os.environ.get('CADDY_TEST_BINARY')
        if not binary:self.skipTest('CADDY_TEST_BINARY not set')
        cfg=self.config();node=cfg.nodes[0]
        cfg.regions[1].tls_source='private_ca'
        node.areas[cfg.regions[0].id].ips=['0.0.0.0']
        node.areas[cfg.regions[1].id].ports=['80','9443','9444']
        cfg.sites[0].areas[cfg.regions[1].id].enabled=False
        cfg.sites.append(Site('e'*32,'Other','other.test','http://127.0.0.1:9000',{cfg.regions[1].id:Service(True)}))
        with tempfile.TemporaryDirectory() as directory,closing(Application(directory)) as app:
            app.security.setup('test');app.certificates.initialize('Test')
            files=generate(cfg,app.certificates,'test')[node.id]
            root=Path(directory)/'runtime'
            for name,data in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(data.replace(b'/etc/smooth-caddy/releases/test',str(root).encode()) if name=='caddy.json' else data)
            result=subprocess.run([binary,'validate','--config',str(root/'caddy.json')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_v8_migration_and_format2_json_copy_shared_port(self):
        cfg=self.config();value=cfg.to_dict()
        value['verify_origin_https']=False
        for site in value['sites']:site.pop('verify_origin_https');site.pop('homepage_redirect');site.pop('allowed_paths')
        for node in value['nodes']:
            node['http_port']='8080'
            for area in node['areas'].values():
                area['ports']=area['ports'][1:];area.pop('relay_enabled')
        with tempfile.TemporaryDirectory() as directory:
            with closing(Application(directory)) as app:
                app.store.db.execute('UPDATE configuration SET payload=?',(json.dumps(value),))
                app.store.db.execute('PRAGMA user_version=8')
            with closing(Application(directory)) as app:
                migrated=app.snapshot()
                self.assertEqual([a.ports for a in migrated.nodes[0].areas.values()],[['8080','443','8443']]*2)
                self.assertNotIn('http_port',migrated.to_dict()['nodes'][0])
                self.assertEqual(len(list(app.store.directory.glob('backups/smooth-caddy-v8-*.db'))),1)
        document=encode(cfg,'Old');document['format']=2
        value.pop('revision');document['configuration']=value
        self.assertEqual([a.ports[0] for a in decode(document).nodes[0].areas.values()],['8080','8080'])

    def test_distinct_http_ports_allow_distinct_https_targets_on_same_ip(self):
        from app.network.models import http_bindings
        cfg=self.config();node=cfg.nodes[0]
        node.areas[cfg.regions[1].id]=Listen(True,['127.0.0.1'],['81','9443','9444'],relay_enabled=True)
        self.assertFalse(configuration_errors(cfg))
        groups=http_bindings(cfg,node)
        self.assertEqual([port for _,port,_ in groups],['80','81'])
        self.assertEqual([next(iter(routes.values())) for _,_,routes in groups],['443','9443'])
