"""Reusable form, password and read-only dialogs."""
from ..i18n import tr
import sqlite3
from rich.text import Text
from dataclasses import dataclass
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static, RadioSet, RadioButton
from .widgets import Button, Checkbox, Input, Select, TextArea
from .choice_row import ChoiceRow

@dataclass
class Field:
    key: str
    label: str
    value: object = ''
    choices: list | None = None
    boolean: bool = False
    secret: bool = False
    readonly: bool = False
    placeholder: str = ''
    multiline: bool = False
    radio: bool = False
    checkbox_label: str | None = None

class FormFields(VerticalScroll):
    def on_resize(self):
        self.call_after_refresh(self.screen.reveal_field)


class Form(ModalScreen):
    BINDINGS = [Binding('escape', 'cancel', tr('取消')), Binding('ctrl+s', 'save', tr('确认')), Binding('ctrl+y', 'confirm_danger', tr('确认危险操作')), Binding('enter', 'danger_enter', '', priority=True, show=False)]
    def __init__(self, title, fields, validate=None, note='', confirm=False, return_only=False):
        super().__init__()
        self.caption, self.fields, self.validate = title, fields, validate
        self.note, self.confirm = note, confirm
        self.return_only = return_only

    def compose(self):
        with Vertical(id='dialog'):
            yield Static(self.caption, id='dialog-title', markup=False)
            yield Static(self.note, id='dialog-note', markup=False)
            with FormFields(id='form-fields'):
                yield from self.compose_fields()
            yield Static('', id='form-error', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield from self.compose_actions()

    def compose_fields(self):
        for f in self.fields:
            if f.key=='port2' and any(x.key=='relay_enabled' for x in self.fields):continue
            if f.key=='relay_enabled':
                port=next(x for x in self.fields if x.key=='port2')
                with Horizontal(classes='port-row'):
                    yield Checkbox(f.label,bool(f.value),id=f.key)
                    yield Input(str(port.value),id=port.key,placeholder='8443')
            elif f.key.startswith('port') and any(x.key=='override'+f.key[4:] for x in self.fields):continue
            elif f.key.startswith('override'):
                port=next(x for x in self.fields if x.key=='port'+f.key[8:])
                with Horizontal(classes='port-row'):
                    yield Checkbox(f.label,bool(f.value),id=f.key)
                    yield Input(str(port.value),id=port.key)
            elif f.boolean:
                if f.checkbox_label is not None:
                    yield Label(f.label)
                with Horizontal(classes='choice-row'):
                    yield Checkbox(f.checkbox_label if f.checkbox_label is not None else f.label,bool(f.value),id=f.key)
            else:
                yield Label(f.label)
                if f.multiline:
                    yield TextArea(str(f.value), id=f.key, soft_wrap=False, tab_behavior='focus', placeholder=f.placeholder, classes='ssh-path-input')
                elif f.readonly:
                    yield Static(str(f.value), id=f.key, markup=False)
                elif f.choices is not None and f.radio:
                    yield ChoiceRow(f.choices,f.value,id=f.key)
                elif f.choices is not None:
                    yield Select(f.choices, value=f.value, allow_blank=False, id=f.key)
                else:
                    yield Input(str(f.value), password=f.secret, placeholder=f.placeholder, id=f.key)

    def compose_actions(self):
        yield Button(tr('返回 · Esc'), id='cancel')
        if not self.return_only:
            yield Button(tr('确认 · ^y') if self.confirm else (tr('保存 · ^s') if self.fields else tr('确认 · ^s')), id='save', variant='error' if self.confirm else 'default')

    def on_mount(self):
        self.query_one('#dialog-note').display = bool(self.note)
        for error in self.query('#form-error'):
            error.display = False
        self.call_after_refresh(self.fit_fields)
        controls = list(self.query('Input, Select, Checkbox, TextArea, RadioSet'))
        self.set_focus(controls[0] if controls else self.query_one('#cancel' if self.return_only else '#save'))
        if len(self.fields) == 1 and controls and isinstance(controls[0], Input):
            controls[0].action_select_all()
        self.sync_enabled()

    def on_resize(self):
        self.call_after_refresh(self.fit_fields)

    def fit_fields(self):
        if not self.is_mounted or not self.is_current or isinstance(self, HelpGuide):
            return
        dialog = self.query_one('#dialog')
        fields = self.query_one('#form-fields')
        if fields.parent is not dialog:
            return
        reserved = dialog.styles.gutter.height
        for child in dialog.children:
            if child is not fields and child.display:
                reserved += child.outer_size.height + child.styles.margin.height
        fields.styles.max_height = max(1, self.size.height - reserved)
        self.call_after_refresh(self.reveal_field)

    def reveal_field(self):
        if not self.is_current:
            return
        fields = self.query_one('#form-fields')
        if self.focused is not None and fields in self.focused.ancestors:
            fields.scroll_to_widget(self.focused, animate=False, immediate=True)

    def sync_enabled(self):
        if not any(f.key == 'enabled' for f in self.fields):
            return
        enabled = self.query_one('#enabled', Checkbox).value
        for field in self.fields:
            if field.key!='enabled':self.query_one('#'+field.key).disabled=not enabled
        for field in self.fields:
            if field.key.startswith('override'):
                self.query_one('#port'+field.key[8:]).disabled=not enabled or not self.query_one('#'+field.key,Checkbox).value

        if any(f.key=='relay_enabled' for f in self.fields):
            self.query_one('#port2').disabled=not enabled or not self.query_one('#relay_enabled',Checkbox).value

    @on(Checkbox.Changed)
    @on(Select.Changed)
    def changed(self):
        self.sync_enabled()

    def action_cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, '#cancel')
    def cancel(self):
        self.action_cancel()

    @on(Button.Pressed, '#save')
    def save(self):
        self.submit_form()

    @on(Input.Submitted)
    def submitted(self):
        self.action_save()

    def check_action(self, action, parameters):
        if action == 'danger_enter': return self.confirm and getattr(self.focused, 'id', None) != 'cancel'
        return True

    def action_danger_enter(self):
        pass

    def action_confirm_danger(self):
        if self.confirm: self.submit_form()

    def action_save(self):
        if not self.confirm and not self.return_only: self.submit_form()

    def submit_form(self):
        values = {}
        for f in self.fields:
            if f.readonly:
                values[f.key] = f.value
                continue
            control = self.query_one('#' + f.key)
            if isinstance(control,RadioSet):
                values[f.key]=f.choices[control.pressed_index][1] if control.pressed_index>=0 else f.value
                continue
            if isinstance(control, TextArea):
                values[f.key] = control.text
                continue
            values[f.key] = control.value if not isinstance(control, Input) or f.secret else control.value.strip()
        problem = self.validate(values) if self.validate else None
        if problem:
            self.query_one('#form-error', Static).update(problem)
            self.query_one('#form-error').display = True
            self.call_after_refresh(self.fit_fields)
            return
        if self.confirm:
            def verified(answer):
                if answer is not None:
                    self.dismiss(values)
            self.app.push_screen(PasswordDialog(
                tr('验证危险操作'), self.app.application.security.verify_password,
                note=self.caption, submit_label=tr('验证')), verified)
            return
        self.dismiss(values)

class SSHGuide(Form):
    def __init__(self, public_key):
        super().__init__(tr('SSH 公钥与手动初始化'), [], return_only=True)
        self.public_key = public_key
        self.add_class('ssh-guide-dialog')

    def compose(self):
        with Vertical(id='dialog'):
            yield Static(self.caption, id='dialog-title', markup=False)
            yield Static('', id='dialog-note')
            with FormFields(id='form-fields'):
                yield Label(tr('公钥'))
                with HorizontalScroll(id='public-key-scroll'):
                    yield Static(Text(self.public_key, no_wrap=True, overflow='ignore'), id='public-key')
                yield Static(tr('\nDebian / OpenSSH\n将公钥追加到 ~/.ssh/authorized_keys。\n\nOpenWrt / Dropbear\n将公钥追加到 /etc/dropbear/authorized_keys。\n\n确保授权登录的用户具备所需权限，并确保 SSHD 允许跳板转发。'), markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button(tr('返回 · Esc'), id='cancel')


class HelpGuide(Form):
    BINDINGS = [Binding('up','scroll_guide(-1)',show=False),
                Binding('down','scroll_guide(1)',show=False),
                Binding('pageup','scroll_guide(-10)',show=False),
                Binding('pagedown','scroll_guide(10)',show=False)]

    def compose(self):
        with Vertical(id='dialog'):
            yield Static(self.caption,id='dialog-title',markup=False)
            with VerticalScroll(id='guide-scroll'):
                yield Static(self.note,id='dialog-note',markup=False)
            yield VerticalScroll(id='form-fields')
            yield Static('',id='form-error')
            with Horizontal(classes='dialog-actions'):
                yield from self.compose_actions()

    def action_scroll_guide(self, amount):
        self.query_one('#guide-scroll').scroll_relative(y=amount,animate=False)


class PasswordDialog(Form):
    """Shared password UI; operation callbacks own their independent semantics."""
    def __init__(self, title, operation, *, repeat=False, note='', path=None, submit_label=tr('保存'), visible=False):
        self.operation = operation
        self.submit_label = submit_label
        self.mask_password = not (repeat or visible)
        fields = []
        if path is not None: fields.append(Field('path', tr('保存路径'), str(path.resolve()), readonly=True))
        fields.append(Field('password', tr('口令'), secret=True))
        if repeat: fields.append(Field('repeat', tr('确认口令'), secret=True))
        def validate(values):
            if not values['password']: return tr('口令不能为空')
            if repeat and values['password'] != values['repeat']: return tr('两次口令不一致')
            try: operation(values['password'])
            except (ValueError, OSError, sqlite3.Error) as error: return str(error)
            return None
        super().__init__(title, fields, validate, note)

    def on_mount(self):
        super().on_mount()
        self.query_one('#save', Button).label = self.submit_label + ' · ^s'
        # Keep secret fields untrimmed even when new/export passwords are visible.
        for item in self.query(Input): item.password = self.mask_password



class InitializationDialog(Form):
    def __init__(self, operation):
        def validate(values):
            if not values['password']: return tr('口令不能为空')
            if values['password'] != values['repeat']: return tr('两次口令不一致')
            try: operation(values['password'], values['name'])
            except (ValueError, OSError, sqlite3.Error) as error: return str(error)
        super().__init__(tr('初始化'), [
            Field('password', tr('初始化口令'), secret=True),
            Field('repeat', tr('确认口令'), secret=True),
            Field('name', tr('初始化根CA名称'), placeholder=tr('例如：Personal WEB')),
        ], validate, tr('使用本软件前，必须设置一个口令。\n本程序将生成SSH密钥及根CA私钥，私钥均将受到以上口令保护。\n请妥善保管本程序的口令及数据目录。'))

    def compose_actions(self):
        yield Button(tr('退出 · Esc'), id='cancel')
        yield Button(tr('保存 · ^s'), id='save')

    def on_mount(self):
        super().on_mount()
        for key in ('password', 'repeat'):
            self.query_one('#'+key, Input).password = False
