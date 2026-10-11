"""Synthetic pre-archive batch files for read-only compatibility tests."""
from datetime import datetime
import json
from uuid import uuid4
from app.network.generator import generate
from app.network.releases import Release, sha
from app.network.files import atomic


def legacy_batch(app):
    config=app.snapshot();version=datetime.now().strftime('%Y%m%d-%H%M%S')
    if (app.releases.root/version).exists():version+='-'+uuid4().hex[:8]
    files=[];materials=generate(config,app.certificates,version)
    for node,contents in materials.items():
        for name,data in contents.items():
            path=node+'/'+name
            atomic(app.releases.root/version/path,app.security.batch_cipher().encrypt(data))
            files.append({'path':path,'size':len(data),'sha256':sha(data)})
    created=datetime.now().astimezone().isoformat(timespec='seconds')
    metadata={'format':5,'version':version,'created_at':created,'configuration':legacy_configuration(config),'files':files}
    payload=json.dumps(metadata,ensure_ascii=False).encode();atomic(app.releases.root/version/'metadata.json',payload)
    batch=Release(version,'releases/'+version,created,{k:[o.name for o in getattr(config,k)] for k in ('nodes','sites','regions')},sha(payload))
    app.releases._index([batch]+app.releases.list())
    return batch


def legacy_configuration(config):
    """Construct a v6/v7 fixture from current policies (one source per test site)."""
    from app.network.models import service_policy
    value=config.to_dict()
    value['verify_origin_https']=value['sites'][0]['verify_origin_https'] if value['sites'] else False
    for site in value['sites']:site.pop('verify_origin_https')
    for region in value['regions']:
        region.pop('tls_source');region.pop('mtls');region['ports']=['80','443','8443']
    for node in value['nodes']:
        for area in node['areas'].values():area['overrides']=area.pop('ports')
    for site,obj in zip(value['sites'],config.sites):
        policies={r.id:service_policy(obj,r) for r in config.regions}
        site['tls_source']=next((p.tls_source for p in policies.values() if p.enabled),'private_ca')
        site['areas']={rid:'https_mtls' if p.enabled and p.mtls else 'https' if p.enabled else 'disabled' for rid,p in policies.items()}
    return value
