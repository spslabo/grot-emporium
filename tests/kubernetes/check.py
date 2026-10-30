"""Live acceptance, restricted to the disposable cluster created by check.sh.

The production installer/verifier are used unchanged except for public test CA
trust in the collector/gateway images. All credentials are synthetic fixtures.
"""
import argparse, base64, io, json, os, sys, time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/telemetry')]
from scripts import grot, grot_infrastructure
from prepare_destinations import certificate, mock_settings
from identity import SERVICES, assert_identities
work=Path(os.environ['GROT_K3S_TEST_DIR'])
cluster=os.environ['GROT_K3S_TEST_CLUSTER']
assert cluster.startswith('grot-acceptance-')
os.environ['KUBECONFIG']=str(work/'kubeconfig')
context='k3d-'+cluster
kube=['kubectl','--context',context]
original=grot.run
host='sink.grot-target.svc.cluster.local'
test_images={role:'grot-test/'+role+':'+cluster for role in ('alloy','gateway')}

def run(command, **kwargs):
    if command[0]=='helm' and 'upgrade' in command and 'grot-telemetry' in command:
        command=command+['--set-string','collectorImage='+test_images['alloy'],'--set-string','gatewayImage='+test_images['gateway']]
    if command[0]=='helm' and 'upgrade' in command and grot_infrastructure.RELEASE in command:
        command=command+['--set-string','collectors.infrastructure.image.registry=docker.io',
            '--set-string','collectors.infrastructure.image.repository=grot-test/alloy',
            '--set-string','collectors.infrastructure.image.tag='+cluster]
    return original(command, **kwargs)

def create(obj, ns='grot-target', manager='grot-acceptance'):
    run(kube+['-n',ns,'create','--field-manager='+manager,'-f','-'],data=json.dumps(obj))

def secret(name, values, ns, manager='external-test-manager'):
    obj={'apiVersion':'v1','kind':'Secret','metadata':{'name':name},'type':'Opaque','data':{k:base64.b64encode(v.encode()).decode() for k,v in values.items()}}
    create(obj,ns,manager)

def settings(name):
    obj=mock_settings(name)
    for role in obj.values():
        for key,value in role.items(): role[key]=value.replace('https://sink:',f'https://{host}:')
    return obj

def args(alias, mode='quick'):
    return argparse.Namespace(destination=alias,context=context,namespace='grot-'+alias,image_prefix='grot',image_tag='local',mode=mode,settings_stdin=(mode=='quick'),pull_secret=None)

def install(a, inputs=None):
    with patch.object(sys,'stdin',io.StringIO(json.dumps(inputs or settings('alpha')))):
        grot.k8s(a)

def stats(endpoint='stats'):
    code="import urllib.request,ssl; print(urllib.request.urlopen('https://"+host+":18766/"+endpoint+"',context=ssl.create_default_context(cafile='/certs/cert.pem')).read().decode())"
    return json.loads(run(kube+['-n','grot-target','exec','deployment/sink','--','python','-c',code]))

def snapshot(a):
    return {role:grot.get_object(kube+['-n',a.namespace],'secret',name) for role,name in grot.SECRET_NAMES.items()}

def assert_signals(name, a, rotated=False):
    expected=[name+(':rotated' if rotated else '')+':'+signal for signal in ('metrics','logs','traces','profiles')]
    expected += [name+':'+signal for signal in ('db-health', 'db-query-metrics', 'db-query-details', 'infra-containers', 'infra-host', 'infra-kube-state', 'infra-events')]
    expected += [name+':faro'] + [name+':profile:'+service for service in ('ui','cart','orders','catalog','checkout')]
    # A receiver-level profile ACK can precede the Node profiler's first upload.
    deadline=time.monotonic()+120
    while True:
        values=stats()
        if all(values.get(key,0)>0 for key in expected): break
        assert time.monotonic()<deadline, 'Missing destination acknowledgements: '+str([key for key in expected if not values.get(key,0)])
        time.sleep(3)
    assert not values.get('credential_leak',0)
    pods = json.loads(run(kube + ['-n', a.namespace, 'get', 'pods', '-l', 'app.kubernetes.io/part-of=grot-emporium', '-o', 'json']))['items']
    current = {pod['metadata']['labels'].get('service_name'): (pod['spec']['nodeName'], pod['metadata']['uid'])
        for pod in pods if not pod['metadata'].get('deletionTimestamp') and pod['metadata']['labels'].get('service_name') in SERVICES}
    deadline = time.monotonic() + 120
    while True:
        try:
            assert_identities(stats('identities'), name, current)
            break
        except AssertionError:
            if time.monotonic() >= deadline: raise
            time.sleep(3)
    print('All five services exported their actual node name and matching pod UID in traces and runtime metrics.', flush=True)
    rows = run(kube + ['-n', a.namespace, 'exec', 'deployment/grot-postgres', '--', 'sh', '-c',
        'export PGPASSWORD="$GROT_DB_MONITOR_PASSWORD"; exec psql -h 127.0.0.1 -U db-o11y -d orders -At -c "SELECT count(*) FROM orders;"'])
    assert int(rows.strip()) > 0, 'Checkout confirmation did not persist real orders'
    print('Kubernetes checkout persisted real PostgreSQL orders.', flush=True)
    print(name+': app signals + cAdvisor/container metrics + node metrics + kube-state-metrics + Kubernetes events'+(' with rotated auth' if rotated else ''),flush=True)
    history=run(['helm','--kube-context',context,'-n',grot_infrastructure.NAMESPACE,'get','values',grot_infrastructure.RELEASE,'-o','json'])
    assert 'dummy-not-a-real-token' not in history and 'dummy-rotated-not-a-real-token' not in history
    assert 'https://'+host not in history, 'Private destination in Helm values'

if not (work/'prepared').exists():
    certificate(work,('sink',host))
    (work/'.dockerignore').write_text('*\n!cert.pem\n')
    run(['docker','build','-t',test_images['alloy'],'-f','-',str(work)],data='FROM grafana/alloy:v1.20.0\nCOPY cert.pem /test-ca.pem\nENV SSL_CERT_FILE=/test-ca.pem\n')
    run(['docker','build','-t',test_images['gateway'],'-f','-',str(work)],data='FROM nginx:1.28-alpine\nCOPY cert.pem /etc/ssl/certs/ca-certificates.crt\n')
    images=['grot/'+s+':local' for s in ('ui','cart','orders','catalog','checkout')]+list(test_images.values())
    # k3d can return success after a containerd import error. Import separately
    # and assert CRI visibility; pull public multi-platform probe images natively.
    for image in images:
        run(['k3d','image','import',image,'-c',cluster])
    imported=json.loads(run(['docker','exec','k3d-'+cluster+'-server-0','crictl','images','-o','json']))
    tags={tag for item in imported['images'] for tag in item.get('repoTags',[])}
    assert all('docker.io/'+image in tags for image in images), 'Local image import incomplete'
    for image in ('python:3.12-alpine','grafana/k6:2.3.0','grafana/k6:2.3.0-with-browser'):
        run(['docker','exec','k3d-'+cluster+'-server-0','crictl','pull',image])
    run(kube+['create','namespace','grot-target'])
    secret('sink-tls',{key:(work/key).read_text() for key in ('cert.pem','key.pem')},'grot-target')
    create({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'sink-code'},'data':{'sink.py':(ROOT/'tests/telemetry/destination_sink.py').read_text(), 'snappy_block.py':(ROOT/'tests/telemetry/snappy_block.py').read_text(), 'identity.py':(ROOT/'tests/telemetry/identity.py').read_text()}})
    create({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'sink'},'spec':{'replicas':1,'selector':{'matchLabels':{'app':'sink'}},'template':{'metadata':{'labels':{'app':'sink'}},'spec':{'automountServiceAccountToken':False,'containers':[{'name':'sink','image':'python:3.12-alpine','command':['python','/code/sink.py'],'ports':[{'containerPort':18766}],'volumeMounts':[{'name':'code','mountPath':'/code','readOnly':True},{'name':'tls','mountPath':'/certs','readOnly':True}]}],'volumes':[{'name':'code','configMap':{'name':'sink-code'}},{'name':'tls','secret':{'secretName':'sink-tls'}}]}}}})
    create({'apiVersion':'v1','kind':'Service','metadata':{'name':'sink'},'spec':{'selector':{'app':'sink'},'ports':[{'port':18766,'targetPort':18766}]}})
    run(kube+['-n','grot-target','rollout','status','deployment/sink','--timeout=90s'])
    (work/'prepared').touch()

with patch.object(grot,'run',side_effect=run), patch.object(grot,'CONFIG_ROOT',work/'state'):
    a=args('k3s-quick')
    print('INSTALL QUICK',flush=True); install(a)
    print('VERIFY QUICK',flush=True); grot.verify(a); assert_signals('alpha', a)
    before=snapshot(a)
    altered=settings('beta')
    try: install(a,altered); raise AssertionError('retarget allowed')
    except grot.SafeError: pass
    assert snapshot(a)==before
    print('Retarget rejected without Secret mutation',flush=True)
    rotated=settings('alpha')
    for key in rotated['alloy']:
        if key.endswith('_TOKEN'): rotated['alloy'][key]='dummy-rotated-not-a-real-token'
    print('ROTATE QUICK',flush=True); install(a,rotated); grot.verify(a); assert_signals('alpha', a, True)
    adopted='grot-ui-runtime'
    run(kube+['-n',a.namespace,'annotate','secret',adopted,'external-test-manager=true','--field-manager=external-test-manager'])
    adopted_before=grot.get_object(kube+['-n',a.namespace],'secret',adopted)
    grot.stop(a)
    remaining=snapshot(a)
    assert remaining['ui']==adopted_before
    assert all(obj is None for role,obj in remaining.items() if role!='ui')
    assert not grot.get_object(kube+['-n',a.namespace],'configmap',grot.LEDGER)
    print('Quick cleanup preserved adopted external Secret and removed owned ones',flush=True)
    assert not json.loads(run(kube+['-n',a.namespace,'get','pods','-o','json']))['items'], 'Cleanup returned while pods still existed'
    # App teardown leaves shared monitoring intact; remove it explicitly before changing tenants.
    assert grot.get_object(kube+['-n',grot_infrastructure.NAMESPACE], 'configmap', grot_infrastructure.LEDGER)
    grot_infrastructure.remove(a, grot)
    time.sleep(5)
    alpha_counts={key:value for key,value in stats().items() if key.startswith('alpha:')}
    b=args('k3s-long','long-term')
    run(kube+['create','namespace',b.namespace])
    for role,values in grot.make_roles(settings('beta')).items(): secret(grot.SECRET_NAMES[role],values,b.namespace)
    external_before=snapshot(b)
    print('INSTALL LONG-TERM',flush=True); install(b)
    print('VERIFY LONG-TERM',flush=True); grot.verify(b); assert_signals('beta', b)
    alpha_after={key:value for key,value in stats().items() if key.startswith('alpha:')}
    assert alpha_after==alpha_counts, 'Unexpected alpha traffic after teardown: '+str({key:value-alpha_counts.get(key,0) for key,value in alpha_after.items() if value!=alpha_counts.get(key,0)})
    # k3s enforces the namespace-local collector ingress policy.
    probe="import socket,errno\naddr=socket.gethostbyname('alloy.grot-k3s-long.svc.cluster.local')\ntry:\n socket.create_connection((addr,4318),2)\nexcept OSError as e:\n assert isinstance(e,TimeoutError) or e.errno in (errno.ECONNREFUSED,errno.EHOSTUNREACH,errno.ENETUNREACH)\nelse:\n raise AssertionError('Collector accepted traffic from another namespace')"
    run(kube+['-n','grot-target','exec','deployment/sink','--','python','-c',probe])
    run(kube+['-n','grot-target','exec','deployment/sink','--','python','-c',probe.replace('alloy.grot-k3s-long', 'postgres.grot-k3s-long').replace('4318', '5432')])
    print('Collector/database namespace ingress isolation and no cross-destination delivery verified',flush=True)
    grot.stop(b); assert snapshot(b)==external_before
    print('Long-term install and cleanup left all five external Secrets unchanged',flush=True)
    grot_infrastructure.remove(b, grot)
    c=args('k3s-failure')
    def fail(command,**kwargs):
        if command[0]=='helm' and 'upgrade' in command and '--install' in command: raise grot.SafeError('injected failure after Secret creation')
        return run(command,**kwargs)
    with patch.object(grot,'run',side_effect=fail):
        try: install(c); raise AssertionError('failure not injected')
        except grot.SafeError: pass
    assert all(snapshot(c).values())
    grot.stop(c); assert not any(snapshot(c).values())
    print('Partial-install cleanup removed owned credentials without a Helm release',flush=True)
    assert not (work/'state').exists(), 'Kubernetes unexpectedly wrote host deployment state'
print('LIVE K3S ACCEPTANCE PASSED',flush=True)
