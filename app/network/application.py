"""Public Python command boundary, shared by TUI and future shell commands."""
from ..i18n import tr
from copy import deepcopy
from uuid import uuid4
from .models import Region, Node, Site, Listen, validate_uniqueness
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
            raise ValueError(tr('CA 名称过长，请缩短名称前缀'))
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
                platform='openwrt_25_12', arch='armv7', ssh_hops=[['192.168.1.1']])]
            for index, arch in ((1, 'amd64'), (2, 'arm64')):
                ip = f'192.168.100.{100 + index}'
                config.nodes.append(Node(uuid4().hex, f'CloudServer{index}',
                    upstream_url='https://192.168.1.1:8443',
                    areas={private: Listen(True, ip), public: Listen(True, '192.168.8.100')},
                    platform='debian_13', arch=arch, ssh_hops=[['192.168.1.1'], [ip]]))
            config.sites = [
                Site(uuid4().hex, 'Blog', 'blog.myabc.com', 'http://192.168.1.50:80',
                     {private: 'https', public: 'https'}),
                Site(uuid4().hex, 'Dashboard', 'dash.myabc.com', 'http://192.168.1.60:8000',
                     {private: 'https', public: 'https_mtls'}, 'public_ca'),
            ]
            self.save_configuration(config)

    def snapshot(self): return self.store.load()

    def save_configuration(self, configuration):
        self.security.require()
        candidate = deepcopy(configuration)
        validate_uniqueness(candidate)
        return self.store.save(candidate)

    def create(self, collection, name):
        if collection not in ('regions', 'nodes', 'sites'): raise ValueError(tr('不支持的配置类型'))
        config = self.snapshot()
        item = {'regions': Region, 'nodes': Node, 'sites': Site}[collection](uuid4().hex, name.strip())
        getattr(config, collection).append(item)
        self.save_configuration(config)
        return item.id

    def move(self, collection, identity, offset):
        if collection not in ('regions', 'nodes', 'sites') or offset not in (-1, 1):
            raise ValueError('Invalid move')
        config = self.snapshot()
        items = getattr(config, collection)
        index = next(i for i, item in enumerate(items) if item.id == identity)
        target = index + offset
        if not 0 <= target < len(items): return False
        items[index], items[target] = items[target], items[index]
        self.save_configuration(config)
        return True

    def delete(self, collection, identity):
        if collection not in ('regions', 'nodes', 'sites'): raise ValueError(tr('不支持删除此对象'))
        config = self.snapshot(); item = config.find(collection, identity)
        if item is None: raise ValueError(tr('对象不存在'))
        getattr(config, collection).remove(item)
        if collection == 'regions':
            for obj in config.nodes + config.sites: obj.areas.pop(identity, None)
        return self.save_configuration(config)

    def errors(self): return self.batches.inspect(self.snapshot())[0]

    def close(self):
        self.security.lock()
        self.store.close()
