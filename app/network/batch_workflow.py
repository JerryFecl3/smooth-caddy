"""Compose public certificate preparation and immutable batch generation."""
from .models import canonical_domain, configuration_errors
from .plans import TaskPlan, certificate_plan, generation_plan
from typing import NamedTuple
from .certificate_policy import renewal_status, requested_domains

class ValidationReport(NamedTuple):
    errors: dict
    matches: dict
    pending: dict

class BatchPlan(NamedTuple):
    tasks: TaskPlan
    items: list

class BatchWorkflow:
    def __init__(self, app):self.app=app

    def inspect(self, config):
        errors=configuration_errors(config);matches={};pending={}
        inventory=self.app.public_tls.list()
        checked={}
        for site in config.sites:
            if site.tls_source not in ('私有 CA','公共 CA'):
                errors[('sites',site.id,'tls_source')]=['请选择 TLS 来源'];continue
            if site.tls_source!='公共 CA' or not any(m in ('HTTPS','HTTPS + mTLS') for m in site.areas.values()):continue
            try:domain=canonical_domain(site.domain)
            except ValueError:continue
            exact=[i for i in inventory if i['domain']==domain]
            wildcard=[i for i in inventory if i['wildcard'] and domain.partition('.')[2]==i['domain']]
            item=next(iter(exact or wildcard),None)
            key=('sites',site.id,'tls_source')
            if item is None:errors[key]=['没有匹配的公共证书配置'];continue
            matches[site.id]=item
            if item['id'] not in checked:
                status='';problem=''
                try:
                    status=renewal_status(item['certificate'])
                    if self.app.security.unlocked:
                        secret=self.app.public_tls.secret(item['id'],item['staging'])
                        if not secret.get('credential_id') or not secret.get('credential_key'):raise ValueError('DNS 凭据缺失')
                        if not status:self.app.public_tls.validate(item['certificate'].encode(),secret['key'].encode(),requested_domains(item))
                except (ValueError,KeyError) as error:problem=str(error) or '公共证书材料无效'
                checked[item['id']]=(status,problem)
            status,problem=checked[item['id']]
            if status:pending[site.id]=status
            if problem:errors[key]=[problem]
        return ValidationReport(errors,matches,pending)

    def plan(self,config):
        if not config.nodes:raise ValueError('请先添加节点')
        errors,matches,pending=self.inspect(config)
        if errors:raise ValueError('\n'.join(f'{config.find(page,identity).name}：'+ '；'.join(messages) for (page,identity,_),messages in errors.items()))
        items=list({item['id']:item for item in matches.values()}.values())
        return BatchPlan(certificate_plan(items).join(generation_plan(config)),items)

    def create(self,progress=lambda _:None,*,task_progress=lambda _:None,cancel=None,config=None,plan=None):
        self.app.security.require()
        if not self.app.certificates.initialized:raise ValueError('请先初始化 CA')
        config=config or self.app.snapshot()
        tasks,items=plan or self.plan(config)
        environment=self.app.public_tls.settings()['staging']
        def mapped(event):task_progress(tasks.map(event))
        if items:
            result=self.app.public_tls.issue_all([i['id'] for i in items],progress,mapped,cancel)
            if not result['success']:raise ValueError('\n'.join(result['errors']))
        if self.app.snapshot().to_dict()!=config.to_dict():raise ValueError('配置已变化，请重新生成')
        if self.app.public_tls.settings()['staging']!=environment:raise ValueError('公共 TLS 环境已变化，请重新生成')
        errors,matches,_=self.inspect(config)
        if errors:raise ValueError('公共证书校验失败：'+'；'.join(m for messages in errors.values() for m in messages))
        if {i['id'] for i in matches.values()} != {i['id'] for i in items}:
            raise ValueError('公共证书匹配已变化，请重新生成')
        materials={}
        for site_id,item in matches.items():
            secret=self.app.public_tls.secret(item['id'],item['staging'])
            certificate=item['certificate'].encode();key=secret.get('key','').encode()
            self.app.public_tls.validate(certificate,key,requested_domains(item))
            materials[site_id]=(certificate,key)
        return self.app.releases.create(progress,task_progress=mapped,cancel=cancel,config=config,public_materials=materials)
