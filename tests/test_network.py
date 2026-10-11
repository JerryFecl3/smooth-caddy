"""Formal application tests: actual persistence and certificates, no TUI."""
from copy import deepcopy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.serialization import pkcs12
from app.network.application import Application
from app.network.models import Service, service_policy, Listen
from app.network.storage import ConflictError, Store

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = Application(self.tmp.name); self.addCleanup(self.app.close)
        self.app.security.setup('secret')

    def test_persistence_invalid_drafts_unique_and_revision(self):
        i = self.app.create('nodes','网关')
        self.assertTrue(self.app.errors())
        stale = self.app.snapshot()
        self.app.create('regions','内网')
        with self.assertRaises(ConflictError): self.app.save_configuration(stale)
        with self.assertRaises(ValueError): self.app.create('nodes',' 网关 ')
        other = Application(self.tmp.name)
        try: self.assertEqual(other.snapshot().nodes[0].id, i)
        finally: other.close()

    def test_delete_preserves_upstream_and_removes_region_cells(self):
        rid = self.app.create('regions','内网'); parent = self.app.create('nodes','父'); child = self.app.create('nodes','子')
        cfg = self.app.snapshot(); cfg.nodes[1].upstream_url='https://relay.example.test:8443'
        cfg.nodes[1].areas[rid]=Listen(True,['10.0.0.2']);self.app.save_configuration(cfg)
        self.app.delete('regions',rid)
        cfg=self.app.snapshot()
        self.assertNotIn(rid,cfg.nodes[1].areas)
        self.assertEqual(cfg.nodes[1].upstream_url,'https://relay.example.test:8443')
        self.assertNotIn(('nodes',child,'upstream_url'),self.app.errors())

    def test_old_database_rejected_without_mutation(self):
        d=Path(self.tmp.name)/'old';d.mkdir();p=d/'smooth-caddy.db'
        db=sqlite3.connect(p)
        db.execute('CREATE TABLE legacy (id INTEGER)');db.commit();db.close()
        before=p.read_bytes()
        with self.assertRaises(ValueError): Store(d)
        self.assertEqual(before,p.read_bytes())

    def test_real_ca_client_p12_and_reset(self):
        self.app.create('regions','内网'); config=self.app.snapshot()
        ca=self.app.certificates;ca.initialize('Private network')
        root=ca.public('root');client=ca.sign_client('Phone')
        with self.assertRaises(ValueError): ca.sign_client('Phone')
        ca.set_enabled(client,False);self.assertEqual(ca.enabled_certificates(),[])
        self.app.security.lock()
        with self.assertRaises(ValueError): ca.export_p12(client,'export')
        self.app.security.unlock('secret')
        private,cert,chain=pkcs12.load_key_and_certificates(ca.export_p12(client,'export'),'export'.encode())
        self.assertIsNotNone(private);self.assertEqual(len(chain),2)
        self.assertEqual(cert.not_valid_after_utc.year,2099)
        self.app.security.change_password('changed');self.assertTrue(ca.unlocked)
        self.app.security.lock()
        with self.assertRaises(ValueError): self.app.security.unlock('secret')
        self.app.security.unlock('changed');self.assertEqual(ca.public('root'),root)
        leaf=ca.leaf('tls','example.test',dns='example.test')
        parsed=x509.load_pem_x509_certificate(leaf.certificate)
        self.assertEqual(parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName),['example.test'])
        certificates = [(cert, 'Phone'), (parsed, 'example.test')]
        for role, name in ca.names.items():
            certificates.append((x509.load_pem_x509_certificate(ca.public(role)), name))
        for client_role in (False, True):
            relay = ca.leaf('relay', 'Relay', client=client_role)
            certificates.append((x509.load_pem_x509_certificate(relay.certificate), 'Relay'))
        for certificate, name in certificates:
            with self.subTest(name=name):
                self.assertEqual(certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value, name)
                self.assertEqual([a.value for a in certificate.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)], ['Smooth Caddy'])
        cert.verify_directly_issued_by(chain[0])
        chain[0].verify_directly_issued_by(chain[1])
        ca.reset();self.assertEqual(ca.clients(),[]);self.assertFalse(ca.initialized)
        self.assertEqual(config,self.app.snapshot())


    def test_origin_verification_strict_format_and_persistence(self):
        from app.network.models import Service, service_policy, Configuration
        self.app.create('sites','Origin')
        value = self.app.snapshot().to_dict()
        value['sites'][0].pop('verify_origin_https')
        with self.assertRaises(ValueError): Configuration.from_dict(value)
        cfg = self.app.snapshot()
        cfg.sites[0].verify_origin_https = True
        self.app.save_configuration(cfg)
        self.assertTrue(self.app.snapshot().sites[0].verify_origin_https)
        cfg = self.app.snapshot()
        cfg.sites[0].verify_origin_https = 'false'
        with self.assertRaises(ValueError): self.app.save_configuration(cfg)
