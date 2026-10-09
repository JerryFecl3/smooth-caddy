"""Reusable form, password and read-only dialogs."""
import sqlite3
from rich.text import Text
from dataclasses import dataclass
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static
from .widgets import Button, Checkbox, Input, Select

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

class Form(ModalScreen):
    BINDINGS = [Binding('escape', 'cancel', '取消'), Binding('ctrl+s', 'save', '确认'), Binding('ctrl+y', 'confirm_danger', '确认危险操作'), Binding('enter', 'danger_enter', '', priority=True, show=False)]
    def __init__(self, title, fields, validate=None, note='', confirm=False, return_only=False):
        super().__init__()
        self.caption, self.fields, self.validate = title, fields, validate
        self.note, self.confirm = note, confirm
        self.return_only = return_only

    def compose(self):
        with Vertical(id='dialog'):
            yield Static(self.caption, id='dialog-title', markup=False)
            yield Static(self.note, id='dialog-note', markup=False)
            with VerticalScroll(id='form-fields'):
                for f in self.fields:
                    if f.key.startswith('port') and any(x.key == 'enabled' for x in self.fields):
                        continue
                    if f.key.startswith('override'):
                        port = next(x for x in self.fields if x.key == 'port' + f.key[-1])
                        with Horizontal(classes='port-row'):
                            yield Checkbox(f.label, bool(f.value), id=f.key)
                            yield Input(str(port.value), id=port.key)
                    elif f.boolean:
                        yield Checkbox(f.label, bool(f.value), id=f.key)
                    else:
                        yield Label(f.label)
                        if f.readonly:
                            yield Static(str(f.value), id=f.key, markup=False)
                        elif f.choices is not None:
                            yield Select(f.choices, value=f.value, allow_blank=False, id=f.key)
                        else:
                            yield Input(str(f.value), password=f.secret, placeholder=f.placeholder, id=f.key)
            yield Static('', id='form-error', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield from self.compose_actions()

    def compose_actions(self):
        yield Button('返回 · Esc', id='cancel')
        if not self.return_only:
            yield Button('确认 · ^y' if self.confirm else ('保存 · ^s' if self.fields else '确认 · ^s'), id='save', variant='error' if self.confirm else 'primary')

    def on_mount(self):
        self.query_one('#dialog-note').display = bool(self.note)
        controls = list(self.query('Input, Select, Checkbox'))
        self.set_focus(controls[0] if controls else self.query_one('#cancel' if self.return_only else '#save'))
        if len(self.fields) == 1 and controls and isinstance(controls[0], Input):
            controls[0].action_select_all()
        self.sync_enabled()

    def sync_enabled(self):
        if not any(f.key == 'enabled' for f in self.fields):
            return
        enabled = self.query_one('#enabled', Checkbox).value
        self.query_one('#ip', Input).disabled = not enabled
        for i in range(3):
            check = self.query_one(f'#override{i}', Checkbox)
            check.disabled = not enabled
            self.query_one(f'#port{i}', Input).disabled = not enabled or not check.value

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
            values[f.key] = control.value if not isinstance(control, Input) or f.secret else control.value.strip()
        problem = self.validate(values) if self.validate else None
        if problem:
            self.query_one('#form-error', Static).update(problem)
            return
        if self.confirm:
            def verified(answer):
                if answer is not None:
                    self.dismiss(values)
            self.app.push_screen(PasswordDialog(
                '验证危险操作', self.app.application.security.verify_password,
                note=self.caption, submit_label='验证'), verified)
            return
        self.dismiss(values)

class SSHGuide(Form):
    def __init__(self, public_key):
        super().__init__('SSH 公钥与手动初始化', [], return_only=True)
        self.public_key = public_key
        self.add_class('ssh-guide-dialog')

    def compose(self):
        with Vertical(id='dialog'):
            yield Static(self.caption, id='dialog-title', markup=False)
            yield Static('', id='dialog-note')
            with VerticalScroll(id='form-fields'):
                yield Label('公钥')
                with HorizontalScroll(id='public-key-scroll'):
                    yield Static(Text(self.public_key, no_wrap=True, overflow='ignore'), id='public-key')
                yield Static('\nDebian / OpenSSH\n将公钥追加到 ~/.ssh/authorized_keys。\n'
                             '\nOpenWrt / Dropbear\n将公钥追加到 /etc/dropbear/authorized_keys。\n'
                             '\n确保授权登录的用户具备所需权限，并确保 SSHD 允许跳板转发。', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('返回 · Esc', id='cancel')


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
    def __init__(self, title, operation, *, repeat=False, note='', path=None, submit_label='保存', visible=False):
        self.operation = operation
        self.submit_label = submit_label
        self.mask_password = not (repeat or visible)
        fields = []
        if path is not None: fields.append(Field('path', '保存路径', str(path.resolve()), readonly=True))
        fields.append(Field('password', '口令', secret=True))
        if repeat: fields.append(Field('repeat', '确认口令', secret=True))
        def validate(values):
            if not values['password']: return '口令不能为空'
            if repeat and values['password'] != values['repeat']: return '两次口令不一致'
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
            if not values['password']: return '口令不能为空'
            if values['password'] != values['repeat']: return '两次口令不一致'
            try: operation(values['password'], values['name'])
            except (ValueError, OSError, sqlite3.Error) as error: return str(error)
        super().__init__('初始化', [
            Field('password', '初始化口令', secret=True),
            Field('repeat', '确认口令', secret=True),
            Field('name', '初始化根CA名称', placeholder='例如：Personal WEB'),
        ], validate, '使用本软件前，必须设置一个口令。\n'
           '本程序将生成SSH密钥及根CA私钥，私钥均将受到以上口令保护。\n'
           '请妥善保管本程序的口令及data目录。')

    def compose_actions(self):
        yield Button('退出 · Esc', id='cancel')
        yield Button('保存 · ^s', id='save', variant='primary')

    def on_mount(self):
        super().on_mount()
        for key in ('password', 'repeat'):
            self.query_one('#'+key, Input).password = False
