"""Generate complete node JSON and ephemeral TLS material from one snapshot."""
from ..i18n import tr
import json
from ipaddress import ip_address
from urllib.parse import urlsplit
from .models import Listen, canonical_domain, configuration_errors, relay_endpoint, RELAY_SERVER_NAME, binding_addresses, service_policy, http_bindings


def address(host, port): return f'[{host}]:{port}' if ':' in host else f'{host}:{port}'


def generate(config, certificates, version, public_materials=None):
    if configuration_errors(config): raise ValueError(tr('配置存在错误，不能生成'))
    if not config.nodes: raise ValueError(tr('请先添加节点'))
    if not certificates.unlocked: raise ValueError(tr('请先初始化 CA 并解锁程序'))
    base = f'/etc/smooth-caddy/releases/{version}'
    shared = {'tls-ca.pem': certificates.public('tls'), 'client-ca.pem': certificates.public('client'),
              'relay-ca.pem': certificates.public('relay')}
    def add_material(files, name, material, role):
        files[name+'.pem'] = material.certificate + certificates.public(role)
        files[name+'.leaf.pem'] = material.certificate
        files[name+'.key'] = material.private_key
    for site in config.sites:
        domain = canonical_domain(site.domain)
        sources={service_policy(site,r).tls_source for r in config.regions if service_policy(site,r).enabled}
        for source in sources:
            name='site-'+site.id+'-'+source
            if source=='public_ca':
                if not public_materials or site.id not in public_materials:raise ValueError(tr('缺少公共证书：')+site.name)
                cert,key=public_materials[site.id]
                shared[name+'.pem']=cert;shared[name+'.key']=key
            else:
                add_material(shared,name,certificates.leaf('tls','site-'+site.id,dns=domain),'tls')
    for node in config.nodes:
        for rid, area in node.areas.items():
            if area.enabled:
                identity = f'relay-{node.id}-{rid}'
                add_material(shared, identity, certificates.leaf('relay', 'relay-'+node.id, dns=RELAY_SERVER_NAME, ips=[ip for ip in binding_addresses(area.ips) if not ip_address(ip).is_unspecified]), 'relay')
        if node.upstream_url:
            add_material(shared,'node-'+node.id,certificates.leaf('relay','node-'+node.id,client=True),'relay')
    for i, cert in enumerate(certificates.enabled_certificates()): shared[f'client-{i}.pem'] = cert
    result = {}
    for node in config.nodes:
        # Only distribute this node's private identities and explicit public trust material.
        files = {}; servers = {}; loads = {}
        def file(name):
            files['certificates/'+name] = shared[name]
            return base+'/certificates/'+name
        def pool(name): return {'provider':'file','pem_files':[file(name)]}
        def auth(ca, leaves):
            return {'mode':'require_and_verify','ca':pool(ca),
                    'verifiers':[{'verifier':'leaf','leaf_certs_loaders':[{'loader':'file','files':[file(n) for n in leaves]}]}]}
        def certificate(name):
            loads[name] = {'certificate':file(name+'.pem'),'key':file(name+'.key'),'tags':[name]}
            return {'certificate_selection':{'any_tag':[name]}}
        def deny(): return {'handler':'static_response','status_code':403}
        def route(domain, handler):
            r={'handle':[handler],'terminal':True}
            if domain: r['match']=[{'host':[domain]}]
            return r
        def proxy(site):
            transport={'protocol':'http','versions':['1.1','2']}
            if node.upstream_url:
                host, port = relay_endpoint(node.upstream_url)
                dial=address(host,port)
                transport['tls']={'ca':pool('relay-ca.pem'),'server_name':RELAY_SERVER_NAME,
                    'client_certificate_file':file('node-'+node.id+'.pem'),
                    'client_certificate_key_file':file('node-'+node.id+'.key')}
            else:
                upstream=urlsplit(site.source)
                dial=address(upstream.hostname,upstream.port or (443 if upstream.scheme=='https' else 80))
                if upstream.scheme=='https':
                    transport['tls']={'server_name':upstream.hostname}
                    if not site.verify_origin_https: transport['tls']['insecure_skip_verify']=True
            return {'handler':'reverse_proxy','upstreams':[{'dial':dial}],'transport':transport,
                    'headers':{'request':{'set':{'Host':['{http.request.hostport}']}}}}
        for region in config.regions:
            area=node.areas.get(region.id,Listen())
            if not area.enabled: continue
            ports=area.ports[1:]
            def server(kind, port, routes, policies=None, strict=True):
                entry={'listen':[f'tcp{ip_address(ip).version}/'+address(ip,port) for ip in binding_addresses(area.ips)],'routes':routes+[route(None,deny())],
                       'automatic_https':{'disable':True},'protocols':['h1','h2'],'strict_sni_host':strict}
                if policies is not None: entry['tls_connection_policies']=policies
                servers[region.id+'-'+kind]=entry
                return entry
            http=[];https=[];policies=[]
            for site in config.sites:
                service=service_policy(site,region);domain=canonical_domain(site.domain)
                if service.enabled:
                    https.append(route(domain,proxy(site)))
                    policy=certificate('site-'+site.id+'-'+service.tls_source);policy['match']={'sni':[domain]}
                    if service.mtls:
                        policy['client_authentication']=auth('client-ca.pem',[n for n in shared if n.startswith('client-') and n!='client-ca.pem'])
                    policies.append(policy)
            if policies:
                entry = server('https',ports[0],https,policies)
                # Detect plaintext before TLS; relay listeners must remain TLS-only.
                entry['listener_wrappers'] = [{'wrapper':'http_redirect'}, {'wrapper':'tls'}]
            identity=f'relay-{node.id}-{region.id}'
            policy=certificate(identity)
            policy['client_authentication']={'mode':'require_and_verify','ca':pool('relay-ca.pem')}
            relay=server('relay',ports[1],[route(canonical_domain(s.domain),proxy(s)) for s in config.sites],[policy],strict=False)
            # Authenticated relay peers may forward original request headers. Their TCP
            # addresses can differ from listener addresses due to network routing/NAT.
            relay['trusted_proxies']={'source':'static','ranges':['0.0.0.0/0','::/0']}
        for index,(host,http_port,targets) in enumerate(http_bindings(config,node)):
            redirects=[]
            for (local,domain),port in targets.items():
                target='https://'+domain+(':'+port if port!='443' else '')+'{http.request.uri}'
                entry=route(domain,{'handler':'static_response','status_code':308,'headers':{'Location':[target]}})
                if ip_address(host).is_unspecified and not ip_address(local).is_unspecified:
                    entry['match'][0]['expression']='{http.request.local.host} == "'+local+'"'
                redirects.append(entry)
            servers['http-'+str(index)]={'listen':[f'tcp{ip_address(host).version}/'+address(host,http_port)],
                'routes':redirects+[route(None,deny())], 'automatic_https':{'disable':True},'protocols':['h1']}
        document={'admin':{'disabled':True},'apps':{'http':{'servers':servers},'tls':{'certificates':{'load_files':list(loads.values())}}}}
        files['caddy.json']=(json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode()
        result[node.id]=files
    return result
