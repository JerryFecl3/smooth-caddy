"""Three-row HTTPS service policy editor with grouped inheritance."""
from textual.containers import Horizontal
from .choice_row import ChoiceRow
from ..i18n import tr
from .dialogs import Form, Field
from .widgets import Checkbox
from ..network.models import service_policy


class ServiceForm(Form):
    def __init__(self,title,site,region,note=''):
        self.defaults=(region.tls_source,region.mtls)
        policy=service_policy(site,region)
        own=site.areas.get(region.id)
        custom=own is not None and (own.tls_source is not None or own.mtls is not None)
        fields=[Field('enabled',tr('启用此区域'),policy.enabled,boolean=True),
                Field('custom',tr('自定义配置'),custom,boolean=True),
                Field('tls_source','',policy.tls_source,[(tr('私有CA'),'private_ca'),(tr('公共CA'),'public_ca')],radio=True),
                Field('mtls','',policy.mtls,[(tr('关闭mTLS'),False),(tr('开启mTLS'),True)],radio=True)]
        super().__init__(title,fields,note=note)
        self.add_class('service-policy-dialog')

    def compose_fields(self):
        with Horizontal(classes='choice-row'):
            for f in self.fields[:2]:yield Checkbox(f.label,bool(f.value),id=f.key)
        for f in self.fields[2:]:yield ChoiceRow(f.choices,f.value,id=f.key)

    def sync_enabled(self):
        enabled=self.query_one('#enabled',Checkbox).value
        custom=self.query_one('#custom',Checkbox)
        custom.disabled=not enabled
        for key,default in zip(('tls_source','mtls'),self.defaults):
            control=self.query_one('#'+key,ChoiceRow)
            if not custom.value:
                control.value=default
            control.disabled=not(enabled and custom.value)
