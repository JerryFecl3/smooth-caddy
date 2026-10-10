"""Public TLS inventory and issuance; batch orchestration is owned separately."""
from ..i18n import tr
from dataclasses import dataclass
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from uuid import uuid4
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from .task_progress import TaskStep, TaskCancelled
from .plans import certificate_plan

from .certificate_policy import RENEW_DAYS, requested_domains, certificate_expiry, renewal_status

PREFIX='public-tls/'
SECRET='public-tls-secret/'
SERVERS={True:'https://acme-staging-v02.api.letsencrypt.org/directory',False:'https://acme-v02.api.letsencrypt.org/directory'}
PROVIDERS={'alidns':(tr('阿里云'),'ALICLOUD_ACCESS_KEY','ALICLOUD_SECRET_KEY'),
           'tencentcloud':('DNSPod','TENCENTCLOUD_SECRET_ID','TENCENTCLOUD_SECRET_KEY')}

@dataclass(frozen=True)
class CertificateResult:
    state: str
    note: str

SAVED = CertificateResult('success',tr('已保存'))
REUSED = CertificateResult('skipped',tr('无需申请'))

class PublicTLS:
    def __init__(self, app):
        self.app=app;self.store=app.store;self.security=app.security
        self.locks={}
        from .lego_tool import LegoTool
        self.tool=LegoTool(self.store.directory)

    def _get(self,name,default=None):
        row=self.store.db.execute('SELECT value FROM secrets WHERE name=?',(name,)).fetchone()
        return json.loads(row[0]) if row else default

    def _put(self,name,value):
        self.store.db.execute('INSERT OR REPLACE INTO secrets VALUES (?,?)',(name,json.dumps(value,ensure_ascii=False)))

    def settings(self):return self._get(PREFIX+'settings',{'staging':True,'email':''})

    def configure(self,staging,email):
        self.security.require()
        email=email.strip()
        if email and ('@' not in email or any(c.isspace() for c in email)):raise ValueError(tr('联系邮箱格式无效'))
        with self.security._mutex,self.store.transaction():self._put(PREFIX+'settings',{'staging':bool(staging),'email':email})

    def list(self):
        with self.security._mutex:
            rows=self.store.db.execute('SELECT value FROM secrets WHERE name LIKE ? ORDER BY rowid',(PREFIX+'item/%',)).fetchall()
            identities = [json.loads(row[0])['id'] for row in rows]
            order = self._get(PREFIX+'order', [])
            identities = [identity for identity in order if identity in identities] + [identity for identity in identities if identity not in order]
            return [self.get(identity) for identity in identities]

    def move(self, identity, offset):
        if offset not in (-1, 1): raise ValueError('Invalid move')
        with self.security._mutex, self.store.transaction():
            self.security.require()
            order = [item['id'] for item in self.list()]
            index = order.index(identity)
            target = index + offset
            if not 0 <= target < len(order): return False
            order[index], order[target] = order[target], order[index]
            self._put(PREFIX+'order', order)
            return True

    def environment(self, staging=None):
        return 'staging' if (self.settings()['staging'] if staging is None else staging) else 'production'

    def get(self,identity,staging=None):
        value=self._get(PREFIX+'item/'+identity)
        if value is None:raise ValueError(tr('证书记录不存在'))
        if 'staging' in value:raise ValueError(tr('公共 TLS 数据格式不受支持，请先进行一次性转换'))
        env=self.environment(staging)
        result=self._get(PREFIX+'result/'+identity+'/'+env,{'expires':'','certificate':'','error':''})
        return dict(value,**result,staging=env=='staging')

    def secret(self,identity,staging=None):
        row=self.store.db.execute('SELECT value FROM secrets WHERE name=?',(SECRET+identity,)).fetchone()
        if not row:raise ValueError(tr('证书材料不存在'))
        shared=json.loads(self.security.decrypt(row[0]))
        row=self.store.db.execute('SELECT value FROM secrets WHERE name=?',(SECRET+identity+'/'+self.environment(staging),)).fetchone()
        result=json.loads(self.security.decrypt(row[0])) if row else {'files':{}}
        return dict(shared,**result)

    def _put_secret(self,identity,value,staging=None):
        shared={k:value[k] for k in ('credential_id','credential_key')}
        result={k:value[k] for k in ('key','files') if k in value}
        for name,material in [(SECRET+identity,shared),(SECRET+identity+'/'+self.environment(staging),result)]:
            self.store.db.execute('INSERT OR REPLACE INTO secrets VALUES (?,?)',(name,self.security.encrypt(json.dumps(material).encode())))

    def _put_result(self,identity,value,staging=None):
        self._put(PREFIX+'result/'+identity+'/'+self.environment(staging),
                  {k:value[k] for k in ('expires','certificate','error')})

    def save(self,domain,wildcard,provider,credential_id,credential_key,identity=None):
        self.security.require()
        domain=domain.strip().rstrip('.').lower()
        try:domain=domain.encode('idna').decode('ascii')
        except UnicodeError:raise ValueError(tr('域名格式无效')) from None
        import re
        if len(domain)>253 or '.' not in domain or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in domain.split('.')):
            raise ValueError(tr('请输入域名，不含协议、路径或 *'))
        if provider not in PROVIDERS:raise ValueError(tr('请选择 DNS 服务商'))
        with self.security._mutex,self.store.transaction():
            order = [item['id'] for item in self.list()]
            old=self.get(identity) if identity else None
            for item in self.list():
                if item['id']!=identity and item['domain']==domain :raise ValueError(tr('域名已存在'))
            secret=self.secret(identity) if old else {'files':{}}
            credential_id=credential_id.strip() or (secret.get('credential_id','') if old and old['provider']==provider else '')
            credential_key=credential_key.strip() or (secret.get('credential_key','') if old and old['provider']==provider else '')
            if not credential_id or not credential_key:raise ValueError(tr('请填写 DNS 凭据'))
            if old and (old['domain']!=domain or old['wildcard']!=bool(wildcard)):
                raise ValueError(tr('已有记录的域名范围不可修改，请新增记录'))
            identity=identity or uuid4().hex
            item={k:old[k] for k in ('id','domain','wildcard','provider','revision')} if old else {'id':identity}
            item.update(domain=domain,wildcard=bool(wildcard),provider=provider,revision=item.get('revision',0)+1)
            secret.update(credential_id=credential_id,credential_key=credential_key)
            self._put(PREFIX+'item/'+identity,item);self._put_secret(identity,secret)
            if identity not in order: order.append(identity)
            self._put(PREFIX+'order', order)
        return identity

    def delete(self,identity):
        with self.security._mutex,self.store.transaction():
            self.security.require();self.get(identity)
            names=[PREFIX+'item/'+identity,SECRET+identity]
            for env in ('staging','production'):names.extend([PREFIX+'result/'+identity+'/'+env,SECRET+identity+'/'+env])
            self.store.db.executemany('DELETE FROM secrets WHERE name=?',[(name,) for name in names])

    def state(self,item):
        if item['expires']:
            return tr('有效') if certificate_expiry(item['certificate'])>datetime.now(timezone.utc) else tr('已过期')
        return tr('申请失败') if item['error'] else tr('未申请')

    def issue(self,identity,force=False,progress=lambda _:None,task_progress=lambda _:None,cancel=None,*,staging=None):
        with self.security._mutex:
            lock=self.locks.setdefault(identity,threading.Lock())
        if not lock.acquire(blocking=False):raise ValueError(tr('该证书正在申请'))
        steps=(tr('准备签发工具'),tr('准备账户'),tr('申请证书'),tr('检查证书'),tr('保存证书'))
        def checkpoint():
            if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止申请'))
        def step(i,status='',state='running'):checkpoint();task_progress(TaskStep(steps,i,status,state=state))
        try:
            with self.security._mutex:
                self.security.require();settings=self.settings()
                staging=settings['staging'] if staging is None else staging
                item=self.get(identity,staging);material=self.secret(identity,staging)
            if not force and not renewal_status(item['certificate']):
                self.validate(item['certificate'].encode(),material['key'].encode(),requested_domains(item))
                for i in range(len(steps)):step(i,tr('无需申请'),'skipped')
                return REUSED
            step(0);self.tool.version(required=True);step(0,tr('已就绪'),'success')
            step(1)
            with tempfile.TemporaryDirectory(prefix='acme-',dir=self.app.store.temporary) as directory:
                home=Path(directory)
                for name,content in material.get('files',{}).items():
                    relative=Path(name)
                    if relative.is_absolute() or '..' in relative.parts:raise ValueError(tr('ACME 状态路径无效'))
                    target=home/relative;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    target.write_bytes(base64.b64decode(content));target.chmod(0o600)
                # Retain renewal resources and account state until a successful commit.
                import shutil
                domains=requested_domains(item)
                cmd=[str(self.tool.binary),'run','--path',str(home),'--accept-tos','--server',SERVERS[item['staging']],
                     '--dns',item['provider'],'--dns.propagation.disable-ans','--renew-days',str(RENEW_DAYS),'--no-random-sleep']
                if force:cmd.append('--renew-force')
                for domain in domains:cmd.extend(['--domains',domain])
                if settings['email']:cmd.extend(['--email',settings['email']])
                env={k:v for k,v in os.environ.items() if not k.startswith(('LEGO_','ALICLOUD_','TENCENTCLOUD_'))}
                _,id_env,key_env=PROVIDERS[item['provider']]
                env.update({id_env:material['credential_id'],key_env:material['credential_key']})
                step(1,tr('已就绪'),'success');step(2,tr('验证中'))
                output=self._run(cmd,env,home,cancel)
                if output[0] and 'accountDoesNotExist' in output[1]:
                    shutil.rmtree(home/'accounts',ignore_errors=True)
                    progress(tr('重新注册账户'));output=self._run(cmd,env,home,cancel)
                if output[0]:
                    message=output[1][-2500:]
                    for value in (material['credential_id'],material['credential_key']):message=message.replace(value,tr('[隐藏]'))
                    raise ValueError(tr('证书申请失败：\n')+message)
                step(2,tr('已完成'),'success');step(3)
                cert=(home/'certificates'/f"{item['domain']}.crt").read_bytes()
                key=(home/'certificates'/f"{item['domain']}.key").read_bytes()
                expires=self.validate(cert,key,domains)
                step(3,tr('已通过'),'success');step(4)
                files={p.relative_to(home).as_posix():base64.b64encode(p.read_bytes()).decode() for p in home.rglob('*') if p.is_file() and p.suffix!='.log'}
                material.update(files=files,key=key.decode())
                with self.security._mutex,self.store.transaction():
                    current=self.get(identity,staging)
                    if current['revision']!=item['revision']:raise ValueError(tr('配置已修改，请重新申请'))
                    checkpoint()
                    item.update(certificate=cert.decode(),expires=expires,error='')
                    self._put_secret(identity,material,staging);self._put_result(identity,item,staging)
                step(4,tr('已保存'),'success');return SAVED
        except TaskCancelled:raise
        except Exception as error:
            with self.security._mutex:
                current=self._get(PREFIX+'item/'+identity)
                if current:
                    result=self.get(identity,staging);result['error']=str(error)
                    with self.store.transaction():self._put_result(identity,result,staging)
            raise
        finally:lock.release()

    def issue_all(self,identities,progress=lambda _:None,task_progress=lambda _:None,cancel=None):
        from concurrent.futures import ThreadPoolExecutor
        self.security.require()
        with self.security._mutex:
            staging=self.settings()['staging']
            items=[self.get(identity) for identity in dict.fromkeys(identities)]
        if not items:raise ValueError(tr('没有可申请的证书'))
        if any(item['staging']!=staging for item in items):raise ValueError(tr('证书环境已变化，请重新确认'))
        plan=certificate_plan(items);steps=plan.steps
        cancel=cancel or threading.Event()
        if cancel.is_set():raise TaskCancelled(tr('已停止申请'))
        for index in range(len(items)):task_progress(plan.event(plan.ids[index],tr('等待中'),'pending'))
        guard=threading.Lock();pending=iter(enumerate(items));errors={}
        def report(index,status,state='running'):
            with guard:task_progress(plan.event(plan.ids[index],status,state))
        def worker():
            while True:
                with guard:
                    if cancel.is_set():return
                    entry=next(pending,None)
                if entry is None:return
                index,item=entry
                report(index,tr('申请中'))
                try:
                    result=self.issue(item['id'],cancel=cancel,staging=staging,
                        task_progress=lambda event:report(index,event.steps[event.index]))
                except TaskCancelled:
                    report(index,tr('已停止'),'stopped');return
                except Exception as error:
                    with guard:errors[index]=item['domain']+'：'+str(error)
                    report(index,tr('失败'),'failed')
                else:report(index,result.note,result.state)
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='public-tls') as executor:
            futures=[executor.submit(worker) for _ in range(min(3,len(items)))]
            for future in futures:future.result()
        if cancel.is_set():raise TaskCancelled(tr('已停止申请'))
        return {'success':not errors,'errors':[errors[i] for i in sorted(errors)]}

    @staticmethod
    def validate(cert,key,domains):
        chain=x509.load_pem_x509_certificates(cert)
        if not chain:raise ValueError(tr('证书内容无效'))
        leaf=chain[0];private=serialization.load_pem_private_key(key,password=None)
        encoding=serialization.Encoding.DER;form=serialization.PublicFormat.SubjectPublicKeyInfo
        if private.public_key().public_bytes(encoding,form)!=leaf.public_key().public_bytes(encoding,form):raise ValueError(tr('证书与私钥不匹配'))
        names=leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        if not set(domains).issubset(names):raise ValueError(tr('证书未覆盖申请域名'))
        for child,parent in zip(chain,chain[1:]):
            try:child.verify_directly_issued_by(parent)
            except Exception:raise ValueError(tr('证书链不完整或签名无效')) from None
        now=datetime.now(timezone.utc)
        if not leaf.not_valid_before_utc<=now<leaf.not_valid_after_utc:raise ValueError(tr('证书不在有效期内'))
        return leaf.not_valid_after_utc.isoformat()

    @staticmethod
    def _run(cmd,env,home,cancel):
        with tempfile.TemporaryFile(dir=home) as output:
            process=subprocess.Popen(cmd,env=env,stdout=output,stderr=subprocess.STDOUT)
            started=time.monotonic()
            try:
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():raise TaskCancelled(tr('已停止申请'))
                    if time.monotonic()-started>600:raise ValueError(tr('证书申请超时'))
                    time.sleep(.1)
                output.seek(0,2);size=output.tell();output.seek(max(0,size-65536))
                return process.returncode,output.read().decode(errors='replace')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
