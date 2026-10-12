"""SSH transport and sequential two-phase deployment with explicit decisions."""
from ..i18n import tr
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import shlex
import re
import asyncssh
from .models import ssh_route
from .plans import deployment_plan

@dataclass(frozen=True)
class HostIdentity:
    node_id: str
    name: str
    address: str
    fingerprint: str
    previous: str | None

@dataclass(frozen=True)
class DeploymentIssue:
    node_id: str
    name: str
    stage: str
    message: str
    uncertain: bool = False

@dataclass(frozen=True)
class DeploymentUpdate:
    node_id: str
    stage: str
    state: str
    note: str


def deployment_update(node_id, stage, status):
    notes={'waiting':tr('未部署'),'uploading':tr('上传中'),'uploaded':tr('已上传'),'deploying':tr('部署中'),
           'checking':tr('确认部署结果'),'success':tr('部署成功'),'failed':tr('失败'),'skipped':tr('已跳过'),'uncertain':tr('结果待确认')}
    states={'uploaded':'success','success':'success','failed':'failed','skipped':'skipped','waiting':'pending'}
    return DeploymentUpdate(node_id,'deploy' if stage=='install' else stage,states.get(status,'running'),notes[status])

class Stopped(Exception): pass

class SSH:
    def __init__(self, store, security):
        self.store=store
        self.security=security

    def reset(self):
        self.security.require()
        key=asyncssh.generate_private_key('ssh-ed25519').export_private_key()
        with self.store.transaction():
            self.store.db.executemany('INSERT OR REPLACE INTO secrets VALUES (?,?)',
                [('ssh-key',self.security.encrypt(key)),('ssh-public',asyncssh.import_private_key(key).export_public_key())])

    @property
    def initialized(self):
        return all(self.store.db.execute('SELECT value FROM secrets WHERE name=?',(name,)).fetchone()
                   for name in ('ssh-key','ssh-public'))

    def ensure_identity(self):
        self.security.require()
        row=self.store.db.execute("SELECT value FROM secrets WHERE name='ssh-key'").fetchone()
        if row:
            public=self.private().export_public_key()
            with self.store.transaction():
                self.store.db.execute('INSERT OR REPLACE INTO secrets VALUES (?,?)',('ssh-public',public))
        else:
            self.reset()

    def private(self):
        self.security.require()
        return asyncssh.import_private_key(self.security.decrypt(self.store.db.execute("SELECT value FROM secrets WHERE name='ssh-key'").fetchone()[0]))
    def public(self):
        row=self.store.db.execute("SELECT value FROM secrets WHERE name='ssh-public'").fetchone()
        return row[0].decode().strip() if row else tr('设置程序口令后生成 SSH 公钥')
    def trusted_count(self):return self.store.db.execute('SELECT count(*) FROM ssh_hosts').fetchone()[0]

    @asynccontextmanager
    async def connect(self, route, confirm):
        self.security.require()
        connections=[]
        try:
            tunnel=None
            for node in route:
                key=await asyncio.wait_for(asyncssh.get_server_host_key(node.address,22,tunnel=tunnel,config=None),30)
                if key is None:raise ValueError(tr('SSH 未提供主机密钥'))
                public=key.export_public_key()
                row=self.store.db.execute('SELECT key FROM ssh_hosts WHERE route_id=?',(node.trust_id,)).fetchone()
                if row is None or row[0]!=public:
                    previous=asyncssh.import_public_key(row[0]).get_fingerprint() if row else None
                    identity=HostIdentity(node.id,node.name,node.address,key.get_fingerprint(),previous)
                    if not await confirm(identity):raise Stopped(tr('未确认主机身份'))
                    with self.store.transaction():self.store.db.execute('INSERT OR REPLACE INTO ssh_hosts VALUES (?,?)',(node.trust_id,public))
                # Pin the just-approved key on the authenticated connection too.
                conn=await asyncio.wait_for(asyncssh.connect(node.address,22,username='root',tunnel=tunnel,
                    client_keys=[self.private()],known_hosts=([key],[],[]),agent_path=None,
                    preferred_auth=['publickey'],config=None,keepalive_interval=15,keepalive_count_max=3),30)
                connections.append(conn);tunnel=conn
            yield connections[-1]
        finally:
            for conn in reversed(connections):
                conn.close();await conn.wait_closed()


class Deployment:
    def __init__(self, application): self.app=application

    async def run(self, release, confirm_host, decide, progress):
        self.app.security.require()
        from .models import Configuration
        self.app.releases.check_packages(release)
        config=Configuration.from_dict(release.configuration)
        routes={p.node_id:ssh_route(config,p.node_id) for p in release.packages}
        statuses={p.node_id:'waiting' for p in release.packages}
        uploaded=set();stopped=False
        def notify(identity,status):progress(deployment_update(identity,stage,status))
        for stage in ('upload','install'):
            for package in release.packages:
                if stage=='install' and package.node_id not in uploaded:continue
                uncertain=False
                while True:
                    notify(package.node_id,'uploading' if stage=='upload' else 'checking' if uncertain else 'deploying')
                    remote=f'/tmp/smooth-caddy-{package.node_id}-{release.version}.run'
                    helper='/usr/local/lib/smooth-caddy/manage' if package.platform=='debian_13' else '/usr/lib/smooth-caddy/manage'
                    try:
                        async with self.app.ssh.connect(routes[package.node_id],confirm_host) as conn:
                            if stage=='upload':
                                local=str(self.app.releases.directory(release)/package.filename)
                                # SCP protocol works with Dropbear without requiring an SFTP server.
                                await asyncssh.scp(local,(conn,remote))
                                result=await conn.run('sha256sum '+shlex.quote(remote),check=True)
                                if result.stdout.split()[0]!=package.digest:raise ValueError(tr('上传文件哈希不符'))
                                uploaded.add(package.node_id);statuses[package.node_id]='uploaded'
                            else:
                                if uncertain:
                                    result=await conn.run(shlex.quote(helper)+' status',check=False)
                                    if result.exit_status==0 and 'selected='+release.version in result.stdout and 'state=running' in result.stdout:
                                        statuses[package.node_id]='success';notify(package.node_id,'success');break
                                    # A query that cannot prove completion is a decision, not permission to rerun.
                                    raise ValueError(tr('部署结果未确认。请在节点检查后选择跳过或停止；不会自动重复部署'))
                                result=await conn.run('sh '+shlex.quote(remote)+' --take-over',check=False)
                                if result.exit_status != 0:
                                    message = tr('部署退出码：{0}', result.exit_status)
                                    for label, output in [(tr('标准输出'), result.stdout), (tr('标准错误'), result.stderr)]:
                                        if output: message += '\n' + label + '：\n' + output[-2000:]
                                    command = ('journalctl -u smooth-caddy.service -n 20 --no-pager'
                                               if package.platform == 'debian_13'
                                               else "logread -e caddy | tail -n 20")
                                    try:
                                        diagnostics = await asyncio.wait_for(conn.run(command, check=False), 10)
                                        if diagnostics.stdout: message += tr('\n服务日志：\n') + diagnostics.stdout[-5000:]
                                    except Exception:
                                        message += tr('\n无法读取服务日志')
                                    raise ValueError(message)
                                statuses[package.node_id]='success'
                            notify(package.node_id,statuses[package.node_id]);break
                    except Stopped:
                        stopped=True;break
                    except Exception as error:
                        if stage=='install' and isinstance(error,(asyncssh.ConnectionLost,asyncssh.DisconnectError,OSError,asyncio.TimeoutError)):
                            uncertain=True
                        statuses[package.node_id]='uncertain' if uncertain else 'failed'
                        notify(package.node_id,statuses[package.node_id])
                        choice=await decide(DeploymentIssue(package.node_id,package.name,stage,str(error),uncertain))
                        if choice=='retry':continue
                        if choice=='skip':statuses[package.node_id]='skipped';notify(package.node_id,'skipped');break
                        stopped=True;break
                if stopped:break
            if stopped:break
        return statuses

    async def probe_node(self,config,node,confirm_host):
        import re
        from .models import ARCHES
        async with self.app.ssh.connect(ssh_route(config,node.id),confirm_host) as conn:
            result=await asyncio.wait_for(conn.run(
                "if [ -e /etc/smooth-caddy/current ] || [ -L /etc/smooth-caddy/current ]; then cat /etc/smooth-caddy/current/manifest; else printf '__NOT_INSTALLED__'; fi",check=False),30)
            if result.exit_status!=0:raise ValueError(tr('读取节点部署信息失败：')+result.stderr)
            installed=None
            if result.stdout.strip()!='__NOT_INSTALLED__':
                fields=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
                declared=fields.get('caddy_version','');arch=fields.get('arch','')
                if not re.fullmatch(r'v\d+\.\d+\.\d+',declared) or arch not in ARCHES:
                    raise ValueError(tr('节点部署信息无效'))
                directory='/usr/local/lib/smooth-caddy' if node.platform=='debian_13' else '/usr/lib/smooth-caddy'
                binary=f'{directory}/binaries/{declared}/{arch}/caddy'
                command=f'if [ ! -e {shlex.quote(binary)} ]; then printf __NOT_INSTALLED__; else {shlex.quote(binary)} version; fi'
                result=await asyncio.wait_for(conn.run(command,check=False),30)
                if result.exit_status!=0:raise ValueError(tr('查询 Caddy 版本失败：')+result.stderr)
                if result.stdout.strip()!='__NOT_INSTALLED__':
                    found=re.match(r'^(v\d+\.\d+\.\d+)(?:\s|$)',result.stdout.strip())
                    if not found:raise ValueError(tr('Caddy 返回了无法识别的版本'))
                    installed=found.group(1)
                if arch!=node.arch:installed=None
        return installed

    async def execute(self,batch,version,confirm_host,decide,progress,task_progress,cancel,on_batch=lambda _:None,*,node_ids=None):
        """Generate if requested, probe, assemble per-node binaries, deploy and clean."""
        from .task_progress import TaskCancelled
        self.app.security.require()
        if not re.fullmatch(r'v\d+\.\d+\.\d+',version):raise ValueError(tr('版本须为 vX.Y.Z'))
        if batch is not None: raise ValueError(tr('部署和导出仅支持当前设置'))
        source_config=self.app.snapshot()
        config=self.app.batches.select_nodes(source_config,node_ids)
        nodes=config.nodes
        if not nodes:raise ValueError(tr('请先添加节点'))
        batch_plan=self.app.batches.plan(config)
        plan=batch_plan.tasks.join(deployment_plan(config))
        def checkpoint():
            if cancel.is_set():raise TaskCancelled(tr('已停止后续工作'))
        def step(i,status=''):
            checkpoint();task_progress(plan.event(i,status,'success' if status else ''))
        loop=asyncio.get_running_loop()
        async def deliver(callback,value):callback(value)
        def report(callback,value):asyncio.run_coroutine_threadsafe(deliver(callback,value),loop).result()
        step(plan.ids[0])
        batch=await asyncio.to_thread(self.app.batches.create,
              lambda value:report(progress,value),task_progress=lambda update:report(task_progress,plan.map(update)),cancel=cancel,config=config,plan=batch_plan,source_config=source_config)
        try:
            on_batch(batch)
            return await self._execute_prepared(batch,version,config,nodes,plan,checkpoint,step,report,confirm_host,decide,progress,task_progress,cancel)
        finally:
            batch.materials.clear()

    async def _execute_prepared(self,batch,version,config,nodes,plan,checkpoint,step,report,confirm_host,decide,progress,task_progress,cancel):
        from .task_progress import TaskCancelled
        include=set()
        for i,node in enumerate(nodes):
            while True:
                step('probe:'+node.id)
                try:
                    installed=await self.probe_node(config,node,confirm_host)
                    if installed!=version:include.add(node.id)
                    step('probe:'+node.id,installed or tr('未部署'))
                    progress(node.name+'：'+(installed or tr('未部署'))+(tr('，需要二进制') if node.id in include else tr('，仅更新配置')))
                    break
                except Stopped:raise TaskCancelled(tr('未确认主机身份')) from None
                except Exception as error:
                    if await decide(DeploymentIssue(node.id,node.name,'probe',str(error)))!='retry':raise TaskCancelled(tr('已停止版本探测'))
        checkpoint()
        packages=await asyncio.to_thread(self.app.releases.assemble,batch,version,include,destination='tasks',
            progress=lambda value:report(progress,value),
            task_progress=lambda event:report(task_progress,plan.map(event)),cancel=cancel)
        statuses={n.id:'waiting' for n in nodes}
        def deployment_progress(update):
            if cancel.is_set() and update.state=='running':raise Stopped()
            statuses[update.node_id]='uploaded' if update.stage=='upload' and update.state=='success' else update.state
            task_progress(plan.event(update.stage+':'+update.node_id,update.note,update.state))
            progress(update.note)
        try:
            statuses=await self.run(packages,confirm_host,decide,deployment_progress)
        except Stopped:
            pass
        finally:
            self.app.releases.cleanup(packages)
        succeeded=all(s=='success' for s in statuses.values())
        warnings=[]
        if succeeded:
            # Remove uploaded archives as well as the local temporary build.
            for node in nodes:
                remote=f'/tmp/smooth-caddy-{node.id}-{batch.version}.run'
                try:
                    async with self.app.ssh.connect(ssh_route(config,node.id),confirm_host) as conn:
                        await conn.run('rm -f '+shlex.quote(remote),check=True)
                except Exception as error:warnings.append(node.name+tr('：临时文件清理失败 ')+str(error))
        return {'batch':batch,'statuses':statuses,'nodes':nodes,'success':succeeded,'warnings':warnings}
