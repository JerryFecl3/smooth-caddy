"""Shared keyboard conventions for terminal controls."""
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Button as TextualButton, Select as TextualSelect, Input as TextualInput, Checkbox as TextualCheckbox
from textual.widgets import ListView as TextualListView
from textual.content import Content
from rich.cells import cell_len
from textual.screen import ModalScreen
from textual.widgets import DataTable as TextualDataTable


class Select(TextualSelect, inherit_bindings=False):
    """Closed menus use arrows for focus; Enter opens the option list."""

    BINDINGS = [
        Binding('enter', 'show_overlay', '展开', show=False),
        Binding('left', 'previous_control', '上一项', show=False),
        Binding('right', 'next_control', '下一项', show=False),
        Binding('up', 'previous_control', '上一项', show=False),
        Binding('down', 'next_control', '下一项', show=False),
    ]

    def action_previous_control(self):
        self.screen.focus_previous('Input, Select, Checkbox, Button, DataTable')

    def action_next_control(self):
        self.screen.focus_next('Input, Select, Checkbox, Button, DataTable')


class Button(TextualButton):
    """Allow leaving action rows and navigating their buttons with arrows."""

    BINDINGS = [
        Binding('up', 'previous_control', '上一项', show=False),
        Binding('down', 'next_control', '下一项', show=False),
        Binding('left', 'previous_button', '上一按钮', show=False),
        Binding('right', 'next_button', '下一按钮', show=False),
    ]

    def action_previous_control(self):
        self.move_focus(-1)

    def action_next_control(self):
        self.move_focus(1)

    def action_previous_button(self):
        self.move_focus(-1, buttons_only=True)

    def action_next_button(self):
        self.move_focus(1, buttons_only=True)

    def get_content_width(self, container, viewport):
        text_width = max((cell_len(line) for line in self.render().plain.splitlines()), default=0)
        width = max(16, text_width + 2)
        return width + ((width - text_width) % 2)

    def render(self):
        if self.id == 'help' or getattr(self.app, 'show_shortcuts', False):
            return super().render()
        return Content.from_text(self.label.plain.split(' · ', 1)[0])

    def move_focus(self, direction, buttons_only=False):
        if isinstance(self.screen, ModalScreen):
            selector = 'Button' if buttons_only else 'Input, Select, Checkbox, Button, DataTable'
        elif any(parent.id == 'sidebar' for parent in self.ancestors):
            selector = '#sidebar Button, #nav'
        else:
            selector = '#actions Button'
        if direction < 0:
            self.screen.focus_previous(selector)
        else:
            self.screen.focus_next(selector)


class Input(TextualInput):
    """Vertical arrows navigate; horizontal arrows retain text editing."""

    BINDINGS = [
        Binding('up', 'previous_control', '上一项', show=False),
        Binding('down', 'next_control', '下一项', show=False),
    ]

    def action_previous_control(self):
        self.screen.focus_previous('Input, Select, Checkbox, Button, DataTable')

    def action_next_control(self):
        self.screen.focus_next('Input, Select, Checkbox, Button, DataTable')


class Checkbox(TextualCheckbox):
    """Explicit monochrome-safe check marks and directional navigation."""

    BINDINGS = [
        Binding('up,left', 'previous_control', '上一项', show=False),
        Binding('down,right', 'next_control', '下一项', show=False),
    ]

    @property
    def _button(self):
        return Content.assemble(('[x]' if self.value else '[ ]', self.get_visual_style('toggle--button')))

    def action_previous_control(self):
        self.screen.focus_previous('Input, Select, Checkbox, Button, DataTable')

    def action_next_control(self):
        self.screen.focus_next('Input, Select, Checkbox, Button, DataTable')


class ListView(TextualListView):
    """Keep navigation and its utility buttons in one keyboard region."""

    BINDINGS = [Binding("space", "select_cursor", "选择", show=False)]

    def action_cursor_down(self):
        if self.index == len(self.children) - 1:
            self.screen.focus_next('#sidebar Button, #nav')
        else:
            super().action_cursor_down()

    def action_cursor_up(self):
        if self.index == 0:
            self.screen.focus_previous('#sidebar Button, #nav')
        else:
            super().action_cursor_up()


class DataTable(TextualDataTable):
    class LayoutChanged(Message):
        pass

    def on_resize(self):
        if self.id == 'matrix':self.post_message(self.LayoutChanged())

    """Keep the active row visible behind the more prominent cell cursor."""
    COMPONENT_CLASSES = TextualDataTable.COMPONENT_CLASSES | {"datatable--active-row"}

    def _get_row_style(self, row_index, base_style):
        style = super()._get_row_style(row_index, base_style)
        if self.show_cursor and self.cursor_type == 'cell' and row_index == self.cursor_row:
            style += self.get_component_rich_style('datatable--active-row')
        return style

    def _render_cell(self, row_index, column_index, base_style, width, cursor=False, hover=False):
        # Fixed columns use a separate base style, so apply the row accent here too.
        if self.show_cursor and self.cursor_type == 'cell' and row_index == self.cursor_row:
            base_style += self.get_component_rich_style('datatable--active-row')
        return super()._render_cell(row_index, column_index, base_style, width, cursor, hover)

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate):
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if self.cursor_type == 'cell' and old_coordinate.row != new_coordinate.row:
            self.refresh_row(old_coordinate.row)
            self.refresh_row(new_coordinate.row)
