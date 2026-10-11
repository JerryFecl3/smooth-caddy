"""Presentation snapshots, never a second business implementation."""
from ..i18n import tr

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
    def create(self, page, name):
        if page == 'clients': self.application.certificates.sign_client(name)
        else: self.application.create(page, name)
        self.reload()
    def delete(self, page, obj):
        self.application.delete(page, obj.id)
        self.reload()
