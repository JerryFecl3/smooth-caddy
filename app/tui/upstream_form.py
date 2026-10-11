"""Direct/relay editor retaining the existing optional URL data format."""
from textual import on
from .choice_row import ChoiceRow
from ..i18n import tr
from ..network.models import relay_endpoint
from .dialogs import Form, Field
from .widgets import Input

class UpstreamForm(Form):
    def __init__(self,title,address,note=''):
        fields=[Field('mode','',bool(address),[(tr('直连'),False),(tr('中继'),True)],radio=True),
                Field('value','',address,placeholder='https://relay.example.com:8443')]
        def validate(values):
            if not values['mode']:
                values['value']=''
            else:
                try:relay_endpoint(values['value'])
                except ValueError as error:return str(error)
        super().__init__(title,fields,validate,note)
        self.add_class('upstream-dialog')

    def compose_fields(self):
        yield ChoiceRow(self.fields[0].choices,self.fields[0].value,id='mode')
        yield Input(str(self.fields[1].value),id='value',placeholder=self.fields[1].placeholder)

    def sync_enabled(self):
        self.query_one('#value',Input).disabled=not self.query_one('#mode',ChoiceRow).value

    @on(ChoiceRow.Changed)
    def mode_changed(self):self.sync_enabled()
