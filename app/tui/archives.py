"""Settings archives: explicit save/restore, JSON interchange, no deployment."""
from pathlib import Path
from ..i18n import tr
from .dialogs import Field, Form


def scope_note():
    return tr('仅包含站点、节点、区域及顺序，不含 TLS / mTLS 配置与材料。')


class ArchivesPage:
    def __init__(self, app): self.app=app;self.records=[]
    @property
    def service(self): return self.app.application.archives

    def render(self, table):
        self.records=self.service.list()
        table.add_columns(tr('名称'),tr('保存时间'),tr('节点数'),tr('站点数'),tr('区域数'))
        for item in self.records:
            c=item['configuration']
            table.add_row(item['name'],item['created_at'],str(len(c['nodes'])),str(len(c['sites'])),str(len(c['regions'])),key=item['id'])
        pos=self.app.positions.get('archives',(0,0))
        table.move_cursor(row=min(pos[0],max(0,len(self.records)-1)))
        for key in ('archive-restore','archive-export','archive-delete'):
            self.app.query_one('#'+key).disabled=not self.records

    def selected(self):
        row=self.app.query_one('#matrix').cursor_row
        return self.records[row] if 0<=row<len(self.records) else None

    def save(self):
        def opened():
            def validate(v):
                try:self.service.save(v['name'])
                except (ValueError,OSError) as error:return str(error)
            self.app.push_screen(Form(tr('新增存档'),[Field('name',tr('名称'))],validate,note=scope_note()),lambda _:self.app.after_change(''))
        self.app.require_unlock(opened)

    def confirm_restore(self, document):
        revision=self.app.application.snapshot().revision
        def done(answer):
            if answer is not None:
                self.service.restore(document,expected_revision=revision)
                self.app.after_change('')
        self.app.push_screen(Form(tr('替换当前设置？'),[],note=document['name']+'\n'+scope_note()+'\n'+tr('将替换当前配置，不自动保存旧设置，也不创建新存档。')),done)

    def restore(self):
        item=self.selected()
        if item:self.app.require_unlock(lambda:self.confirm_restore(self.service.get(item['id'])))

    def import_json(self):
        def opened():
            documents=[]
            def validate(v):
                try: documents[:]=[self.service.read_json(v['path'])]
                except (ValueError,OSError) as error:return str(error)
            def loaded(answer):
                if answer is not None:self.confirm_restore(documents[0])
            self.app.push_screen(Form(tr('导入配置'),[Field('path',tr('JSON 文件路径'))],validate,note=scope_note()+'\n'+tr('确认后直接应用于当前配置，不创建新存档。')),loaded)
        self.app.require_unlock(opened)

    def export(self, selected=False):
        item=self.selected() if selected else None
        if selected and not item:return
        def opened():
            document=self.service.get(item['id']) if selected else self.service.current_document()
            def validate(values):
                if not values['path']: return tr('请输入保存路径')
                if Path(values['path']).expanduser().is_dir(): return tr('保存路径不能是目录')
            def confirmed(answer):
                if answer is None:return
                path=Path(answer['path']).expanduser().resolve()
                def write():
                    self.service.export_json(document,path)
                    self.app.show_info(tr('设置已导出'),str(path))
                if path.exists():
                    self.app.push_screen(Form(tr('覆盖现有文件？'),[],note=str(path)),
                        lambda result:write() if result is not None else None)
                else:write()
            self.app.push_screen(Form(tr('导出存档'),
                [Field('path',tr('保存路径'),str(self.service.default_export_path().resolve()))],
                validate,note=document['name']+'\n'+scope_note()),confirmed)
        self.app.require_unlock(opened)

    def delete(self):
        item=self.selected()
        if item:
            def opened():
                def done(answer):
                    if answer is not None:self.service.delete(item['id']);self.app.after_change('')
                self.app.push_screen(Form(tr('删除存档？'),[],note=item['name']),done)
            self.app.require_unlock(opened)
