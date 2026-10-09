"""Presentation snapshots, never a second business implementation."""

class State:
    def __init__(self, application):
        self.application = application
        self.reload()

    def reload(self):
        self.config = self.application.snapshot()
        self.validation = None
        self.regions, self.nodes, self.sites = self.config.regions, self.config.nodes, self.config.sites

    def save(self):
        self.config = self.application.save_configuration(self.config)
        self.validation = None
    @property
    def clients(self): return self.application.certificates.clients()
    @property
    def releases(self): return self.application.releases.list()
    @property
    def initialized(self): return self.application.certificates.initialized
    @property
    def unlocked(self): return self.application.security.unlocked
    @property
    def ca_name(self): return self.application.certificates.name
    def refresh_validation(self):
        self.validation = self.application.batches.inspect(self.config)
        return self.validation
    def errors(self):
        if self.validation is None:self.refresh_validation()
        return self.validation.errors
    def items(self, page): return getattr(self, page)
    def find(self, page, identity): return next((x for x in self.items(page) if x.id == identity), None)
    def unique(self, page, value, object_id=None, attr='name'):
        return not any(getattr(x, attr).strip().casefold() == value.strip().casefold() for x in self.items(page) if x.id != object_id)
    def create(self, page, name, upstream=None):
        if page == 'clients': self.application.certificates.sign_client(name)
        else: self.application.create(page, name, upstream)
        self.reload()
    def delete(self, page, obj):
        self.application.delete(page, obj.id)
        self.reload()
    def upstream_label(self, value):
        if not value: return '未选择'
        node, region = self.find('nodes', value[0]), self.find('regions', value[1])
        return f'{node.name if node else "已删除节点"} / {region.name if region else "已删除区域"}'
