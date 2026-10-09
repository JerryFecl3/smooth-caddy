"""Fixed task plans with stable identities, independent of display labels."""
from dataclasses import dataclass
from .task_progress import TaskStep

@dataclass(frozen=True)
class TaskPlan:
    ids: tuple
    steps: tuple
    groups: tuple

    @classmethod
    def group(cls, name, items):
        items=tuple(items)
        return cls(tuple(key for key,_ in items),tuple(label for _,label in items),(name,)*len(items))

    def join(self, other):
        ids=self.ids+other.ids
        if len(set(ids))!=len(ids):raise ValueError('任务身份重复')
        return TaskPlan(ids,self.steps+other.steps,self.groups+other.groups)

    def event(self, identity, note='', state=''):
        return TaskStep(self.steps,self.ids.index(identity),note,self.groups,state,self.ids)

    def map(self, event):
        identity=event.task_ids[event.index]
        return self.event(identity,event.status,event.state)


def generation_plan(config):
    return TaskPlan.group('生成配置批次',[('generate','生成证书与配置'),*[(f'save:{n.id}','保存配置 / '+n.name) for n in config.nodes],('metadata','写入 metadata')])


def assembly_plan(config):
    return TaskPlan.group('部署到节点',[('binaries','准备 Caddy 文件'),*[(f'pack:{n.id}','打包 / '+n.name) for n in config.nodes]])


def deployment_plan(config):
    probes=TaskPlan.group('部署到节点',[(f'probe:{n.id}','探测版本 / '+n.name) for n in config.nodes])
    transfer=TaskPlan.group('部署到节点',[(f'{phase}:{n.id}',label+' / '+n.name) for phase,label in (('upload','上传'),('deploy','部署')) for n in config.nodes])
    return probes.join(assembly_plan(config)).join(transfer)


def certificate_plan(items):
    return TaskPlan.group('申请公共TLS证书',[(f'certificate:{i["id"]}',i['domain']+('（通配）' if i['wildcard'] else '')) for i in items])
