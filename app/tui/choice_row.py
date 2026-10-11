"""Exclusive choices using the same checkbox controls as other forms."""
from textual import on
from textual.containers import Horizontal
from textual.message import Message
from .widgets import Checkbox

class ChoiceRow(Horizontal):
    class Changed(Message):
        def __init__(self,control):
            super().__init__();self.row=control

        @property
        def control(self):return self.row

    def __init__(self,choices,value,**kwargs):
        super().__init__(classes='choice-row',**kwargs)
        self.choices=choices;self._value=value

    def compose(self):
        for index,(title,value) in enumerate(self.choices):
            yield Checkbox(title,value==self._value,id=f'{self.id}-option-{index}')

    @property
    def pressed_index(self):return next(i for i,(_,value) in enumerate(self.choices) if value==self._value)

    @property
    def value(self):return self._value

    @value.setter
    def value(self,value):
        changed=value!=self._value
        self._value=value
        for button,(_,candidate) in zip(self.query(Checkbox),self.choices):button.value=candidate==value
        if changed:self.post_message(self.Changed(self))

    @on(Checkbox.Changed)
    def selected(self,event):
        event.stop()
        if event.value!=event.checkbox.value:return
        index=list(self.query(Checkbox)).index(event.checkbox)
        if event.value:self.value=self.choices[index][1]
        elif self.choices[index][1]==self._value:event.checkbox.value=True
