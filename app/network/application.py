"""Public Python command boundary, shared by TUI and future shell commands."""
from copy import deepcopy
from uuid import uuid4
from .models import Region, Node, Site, Listen, validate_uniqueness, check_node_parent
from .storage import Store
from .security import Security
from .certificates import Certificates, validate_certificate_name, CA_SUFFIXES
from .releases import Releases
from .deployment import SSH, Deployment
from .public_tls import PublicTLS

class Application:
    def __init__(self, directory):
        self.store = Store(directory)
        self.security = Security(self.store)
        self.certificates = Certificates(self.store, self.security)
        self.releases = Releases(self)
        self.ssh = SSH(self.store, self.security)
        self.deployment = Deployment(self)
        self.public_tls = PublicTLS(self)
        from .batch_workflow import BatchWorkflow
        self.batches = BatchWorkflow(self)

    def initialize(self, password, ca_name):
        """Create the local identity from one validated setup request."""
        ca_name = validate_certificate_name(ca_name)
        if any(len(ca_name + ' ' + suffix) > 64 for suffix in CA_SUFFIXES.values()):
            raise ValueError('CA 名称过长，请缩短名称前缀')
        if self.security.initialized:
            self.security.unlock(password)
        else:
            self.security.setup(password)
        self.ssh.ensure_identity()
        if not self.certificates.initialized:
            self.certificates.initialize(ca_name)
        config = self.snapshot()
        if config.revision == 0 and not (config.regions or config.nodes or config.sites):
            private, public, router = (uuid4().hex for _ in range(3))
            config.regions = [Region(private, 'Private'), Region(public, 'Public')]
            config.nodes = [Node(router, 'HomeRouter',
                areas={private: Listen(True, '192.168.1.1')},
                platform='OpenWrt 25.12', arch='armv7', ssh_ip='192.168.1.1')]
            for index, arch in ((1, 'amd64'), (2, 'arm64')):
                ip = f'192.168.100.{100 + index}'
                config.nodes.append(Node(uuid4().hex, f'CloudServer{index}',
                    mode='经上游转发', upstream=(router, private),
                    areas={private: Listen(True, ip), public: Listen(True, '192.168.8.100')},
                    platform='Debian 13', arch=arch, ssh_ip=ip))
            config.sites = [
                Site(uuid4().hex, 'Blog', 'blog.myabc.com', 'http://192.168.1.50:80',
                     {private: 'HTTPS', public: 'HTTPS'}),
                Site(uuid4().hex, 'Dashboard', 'dash.myabc.com', 'http://192.168.1.60:8000',
                     {private: 'HTTPS', public: 'HTTPS + mTLS'}, '公共 CA'),
            ]
            self.save_configuration(config)

    def snapshot(self): return self.store.load()

    def save_configuration(self, configuration):
        self.security.require()
        candidate = deepcopy(configuration)
        validate_uniqueness(candidate)
        for node in candidate.nodes:
            check_node_parent(candidate,node.id,node.upstream[0] if node.upstream else None)
        return self.store.save(candidate)

    def create(self, collection, name, upstream=None):
        if collection not in ('regions', 'nodes', 'sites'): raise ValueError('不支持的配置类型')
        config = self.snapshot()
        item = {'regions': Region, 'nodes': Node, 'sites': Site}[collection](uuid4().hex, name.strip())
        if collection == "nodes" and upstream:
            item.upstream=(upstream, "");item.mode="经上游转发"
        getattr(config, collection).append(item)
        self.save_configuration(config)
        return item.id

    def delete(self, collection, identity):
        if collection not in ('regions', 'nodes', 'sites'): raise ValueError('不支持删除此对象')
        config = self.snapshot(); item = config.find(collection, identity)
        if item is None: raise ValueError('对象不存在')
        getattr(config, collection).remove(item)
        if collection == 'regions':
            for obj in config.nodes + config.sites: obj.areas.pop(identity, None)
        return self.save_configuration(config)

    def errors(self): return self.batches.inspect(self.snapshot())[0]

    def close(self):
        self.security.lock()
        self.store.close()
