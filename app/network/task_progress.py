"""UI-independent state for a fixed, at most two-level task plan."""
from ..i18n import tr
from dataclasses import dataclass, field

class TaskCancelled(ValueError):
    """A cooperative stop before publishing the release."""


@dataclass(frozen=True)
class TaskStep:
    steps: tuple[str, ...]
    index: int
    status: str = ""
    groups: tuple[str, ...] = ()
    state: str = ""
    task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DownloadProgress:
    label: str
    received: int
    total: int | None
    speed: float


TERMINAL = {'success', 'skipped', 'failed', 'stopped'}

@dataclass
class TaskState:
    steps: tuple = ()
    groups: tuple = ()
    states: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    current: int = 0
    sequential: int | None = None

    def update(self, event):
        if self.steps and (self.steps != event.steps or self.groups != event.groups):
            raise ValueError(tr('任务计划执行期间不能改变'))
        if event.groups and len(event.groups) != len(event.steps):
            raise ValueError(tr('任务分组与子任务数量不符'))
        self.steps, self.groups = event.steps, event.groups
        if not 0 <= event.index < len(self.steps):raise ValueError(tr('无效任务索引'))
        # A serial producer advances one active task; concurrent producers always
        # supply explicit states and never complete another task implicitly.
        if not event.state:
            if self.sequential is not None and self.sequential != event.index:
                if self.states.get(self.sequential) == 'running':
                    self.states[self.sequential] = 'success'
                    if not self.notes.get(self.sequential):self.notes[self.sequential] = tr('已完成')
            self.sequential = event.index
        self.current = event.index
        self.states[event.index] = event.state or 'running'
        self.notes[event.index] = event.status

    def finish(self, outcome):
        for index in range(len(self.steps)):
            state = self.states.get(index, 'pending')
            if state in TERMINAL:continue
            if state == 'running':
                self.states[index] = {'success':'success','failed':'failed','stopped':'stopped','partial':'stopped'}[outcome]
                if outcome != 'success':self.notes[index] = tr('失败') if outcome == 'failed' else tr('已停止')
            else:self.notes[index] = tr('未执行')

    def sections(self):
        groups = self.groups or ('',)*len(self.steps)
        return [(name,[i for i,g in enumerate(groups) if g == name]) for name in dict.fromkeys(groups)]

    def counts(self):
        sections = self.sections()
        if len(sections) > 1:
            return sum(all(self.states.get(i) in TERMINAL for i in ids) for _,ids in sections), len(sections)
        return sum(s in TERMINAL for s in self.states.values()), len(self.steps)
