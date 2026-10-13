"""Shared keyboard conventions for terminal controls."""
from ..i18n import tr
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Button as TextualButton, Select as TextualSelect, Input as TextualInput, Checkbox as TextualCheckbox
from textual.widgets import ListView as TextualListView
from textual.content import Content
from rich.cells import cell_len
from rich.text import Text
from textual.screen import ModalScreen
from textual.widgets import DataTable as TextualDataTable
from textual.widgets import TextArea as TextualTextArea


FORM_FOCUS_SELECTOR = 'Input, TextArea, Select, Checkbox, RadioSet, Button, DataTable'


class ControlNavigation:
    """Shared form traversal; subclasses may restrict the focus region."""

    def move_focus(self, direction, selector=FORM_FOCUS_SELECTOR):
        if direction < 0:
            self.screen.focus_previous(selector)
        else:
            self.screen.focus_next(selector)

    def action_previous_control(self):
        self.move_focus(-1)

    def action_next_control(self):
        self.move_focus(1)


class Select(ControlNavigation, TextualSelect, inherit_bindings=False):
    """Closed menus use arrows for focus; Enter opens the option list."""

    BINDINGS = [
        Binding('enter', 'show_overlay', tr('展开'), show=False),
        Binding('left', 'previous_control', tr('上一项'), show=False),
        Binding('right', 'next_control', tr('下一项'), show=False),
        Binding('up', 'previous_control', tr('上一项'), show=False),
        Binding('down', 'next_control', tr('下一项'), show=False),
    ]


class Button(ControlNavigation, TextualButton):
    """Allow leaving action rows and navigating their buttons with arrows."""

    BINDINGS = [
        Binding('up', 'previous_control', tr('上一项'), show=False),
        Binding('down', 'next_control', tr('下一项'), show=False),
        Binding('left', 'previous_button', tr('上一按钮'), show=False),
        Binding('right', 'next_button', tr('下一按钮'), show=False),
    ]

    def action_previous_button(self):
        self.move_focus(-1, buttons_only=True)

    def action_next_button(self):
        self.move_focus(1, buttons_only=True)

    def get_content_width(self, container, viewport):
        text_width = max((cell_len(line) for line in self.render().plain.splitlines()), default=0)
        width = max(6, text_width + 2)
        return width + ((width - text_width) % 2)

    def occupied_width(self):
        # Include padding, borders and margins in natural layout width.
        return self.get_content_width(self.size, self.size) + self.styles.gutter.width + self.styles.margin.width

    def render(self):
        if getattr(self.app, 'show_shortcuts', False):
            return Content.from_text(self.label.plain.replace(' · ', ' '))
        return Content.from_text(self.label.plain.split(' · ', 1)[0])

    def move_focus(self, direction, buttons_only=False):
        if isinstance(self.screen, ModalScreen):
            selector = 'Button' if buttons_only else FORM_FOCUS_SELECTOR
        elif any(parent.id == 'sidebar' for parent in self.ancestors):
            selector = '#sidebar Button, #nav'
        elif any(parent.id == 'settings-tabs' for parent in self.ancestors):
            selector = '#settings-tabs Button'
        elif any(parent.id == 'archive-actions' for parent in self.ancestors):
            selector = '#archive-actions Button'
        else:
            selector = '#actions Button'
        super().move_focus(direction, selector)


class Input(ControlNavigation, TextualInput):
    """Vertical arrows navigate; horizontal arrows retain text editing."""

    BINDINGS = [
        Binding('up', 'previous_control', tr('上一项'), show=False),
        Binding('down', 'next_control', tr('下一项'), show=False),
    ]


class TextArea(ControlNavigation, TextualTextArea):
    """Move between controls only after reaching the first or last text line."""

    def action_cursor_up(self, select=False):
        if not select and self.cursor_location[0] == 0:
            self.action_previous_control()
        else:
            super().action_cursor_up(select)

    def action_cursor_down(self, select=False):
        if not select and self.cursor_location[0] == self.document.line_count - 1:
            self.action_next_control()
        else:
            super().action_cursor_down(select)


class Checkbox(ControlNavigation, TextualCheckbox):
    """Explicit monochrome-safe check marks and directional navigation."""

    BINDINGS = [
        Binding('up,left', 'previous_control', tr('上一项'), show=False),
        Binding('down,right', 'next_control', tr('下一项'), show=False),
    ]

    @property
    def _button(self):
        return Content.assemble(('[x]' if self.value and not self.has_class('hide-check') else '[ ]', self.get_visual_style('toggle--button')))


class ListView(TextualListView):
    """Keep navigation and its utility buttons in one keyboard region."""

    BINDINGS = [Binding("space", "select_cursor", tr('选择'), show=False),
                Binding("left", "cursor_up", show=False),
                Binding("right", "cursor_down", show=False)]

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
    def __init__(self, *args, **kwargs):
        self._column_limits = {}
        self._row_min_heights = {}
        super().__init__(*args, **kwargs)

    def add_column(self, label, *, width=None, key=None, default=None, min_width=1, max_width=None):
        """Widths count content cells; Textual adds the same padding to every column."""
        if width is not None:
            raise ValueError('Use min_width/max_width instead of a fixed width')
        if min_width < 1 or (max_width is not None and max_width < min_width):
            raise ValueError('Invalid column width limits')
        column_key = super().add_column(label, width=min_width, key=key, default=default)
        self._column_limits[column_key] = (min_width, max_width)
        return column_key

    def add_row(self, *cells, height=1, key=None, label=None):
        # Callers specify a minimum; content wrapping determines the final height.
        row_key = super().add_row(*cells, height=height or 1, key=key, label=label)
        self._row_min_heights[row_key] = height or 1
        return row_key

    def clear(self, columns=False):
        self._row_min_heights.clear()
        if columns:
            self._column_limits.clear()
        return super().clear(columns=columns)

    def update_cell(self, row_key, column_key, value, *, update_width=True):
        return super().update_cell(row_key, column_key, value, update_width=update_width)

    def update_cell_at(self, coordinate, value, *, update_width=True):
        return super().update_cell_at(coordinate, value, update_width=update_width)

    @staticmethod
    def _cell_text(value):
        return value if isinstance(value, Text) else Text(str(value) if value is not None else '')

    def _update_dimensions(self, new_rows):
        # Recompute from all current values, allowing columns to shrink after edits.
        for key, column in self.columns.items():
            minimum, maximum = self._column_limits.get(key, (1, None))
            values = [column.label, *self.get_column(key)]
            natural = max((cell_len(line) for value in values
                           for line in self._cell_text(value).plain.splitlines()), default=1)
            column.width = max(minimum, natural)
            if maximum is not None:
                column.width = min(maximum, column.width)
        self.header_height = max((len(column.label.wrap(self.app.console, column.width, overflow='fold'))
                                  for column in self.columns.values()), default=1)
        for key, row in self.rows.items():
            row.height = max(self._row_min_heights.get(key, 1),
                             max((len(self._cell_text(value).wrap(self.app.console, column.width, overflow='fold'))
                                  for value, column in zip(self.get_row(key), self.columns.values())), default=1))
        self._clear_caches()
        super()._update_dimensions(new_rows)

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
        # Keep frozen columns on the same row palette while retaining fixed-cell metadata.
        if row_index >= 0 and 0 <= column_index < self.fixed_columns:
            base_style += self._get_row_style(row_index, self.rich_style)
        if self.show_cursor and self.cursor_type == 'cell' and row_index == self.cursor_row:
            base_style += self.get_component_rich_style('datatable--active-row')
        return super()._render_cell(row_index, column_index, base_style, width, cursor, hover)

    def watch_cursor_coordinate(self, old_coordinate, new_coordinate):
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)
        if self.cursor_type == 'cell' and old_coordinate.row != new_coordinate.row:
            self.refresh_row(old_coordinate.row)
            self.refresh_row(new_coordinate.row)


class ReadOnlyDataTable(DataTable, can_focus=False):
    """Scrollable overview without cell selection or activation."""

    async def _on_click(self, event):
        event.stop()
