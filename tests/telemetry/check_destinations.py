#!/usr/bin/env python3
"""Exercise the production Docker launcher; only destination TLS plumbing is mocked."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import grot, grot_traffic, grot_activity
from prepare_destinations import certificate, mock_settings

with tempfile.TemporaryDirectory(prefix='grot-runtime-test-') as directory:
    root = Path(directory)
    certificate(root)
    original = grot.compose
    def compose(path, args, state=None):
        command, env = original(path, args, state)
        env['GROT_TEST_CONFIG_DIR'] = str(root)
        return command + ['-f', 'tests/telemetry/compose.destinations.yaml'], env
    with patch.object(grot, 'CONFIG_ROOT', root / 'state'), patch.object(grot, 'compose', side_effect=compose):
        for name in ('alpha', 'beta'):
            alias = 'runtime-test-' + name
            args = argparse.Namespace(destination=alias, port=18782, syslog_port=15141, collector_port=12346,
                context=None, namespace=None, settings_stdin=True)
            command, env = compose(None, args)
            try:
                # The extra mock service isn't part of the production launcher's service list.
                grot.run(command + ['up', '-d', 'sink'], env=env)
                inputs = grot.make_roles(mock_settings(name))
                sensitive = ['dummy-not-a-real-token', *inputs['database'].values()]
                with patch.object(sys, 'stdin', io.StringIO(json.dumps(inputs))):
                    grot.docker(args)
                automatic = grot_activity.docker_object(args, grot)
                assert automatic['State']['Status'] == 'running'
                assert automatic['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'
                assert all(value not in json.dumps(automatic['Config']) for value in sensitive)
                monitor = command + ['exec', '-T', 'postgres', 'sh', '-c',
                    '. /run/grot/database/values.sh; export PGPASSWORD="$GROT_DB_MONITOR_PASSWORD"; exec psql -h 127.0.0.1 -U db-o11y -d orders -At -v ON_ERROR_STOP=1']
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if int(grot.run(monitor, env=env, data='SELECT count(*) FROM orders;')) > 0: break
                    time.sleep(2)
                else: raise AssertionError('Automatic demo activity did not create an order')
                print('Automatic demo activity created orders without a post-deployment traffic command.', flush=True)
                grot.verify(args)
                traffic_args = argparse.Namespace(**vars(args), action='start', local_only=True, preset='low', duration='30s', rate=None, browser_rate=None)
                grot.traffic_control(traffic_args)
                traffic_exit = grot.run(['docker', 'wait', grot_traffic.docker_name(args)]).strip()
                traffic_logs = grot.run(['docker', 'logs', grot_traffic.docker_name(args)])
                if traffic_exit != '0':
                    print(traffic_logs, flush=True)
                    raise AssertionError('Sustained k6 scenario failed')
                assert 'browser_journey_success' in traffic_logs and 'journey_success' in traffic_logs
                assert all(value not in traffic_logs for value in sensitive)
                print('Sustained shopping + browser traffic passed; k6 thresholds passed.', flush=True)
                # Real application writes, and a monitor that can read but not mutate data.
                assert int(grot.run(monitor, env=env, data='SELECT count(*) FROM orders;')) > 0
                assert grot.run(monitor, env=env, data="SELECT rolsuper FROM pg_roles WHERE rolname=current_user;").strip() == 'f'
                assert grot.run(monitor, env=env, data="SELECT has_table_privilege(current_user, 'orders', 'INSERT,UPDATE,DELETE,TRUNCATE');").strip() == 'f'
                try:
                    grot.run(monitor, env=env, data='BEGIN; DELETE FROM orders; ROLLBACK;')
                    raise AssertionError('Monitoring user could delete orders')
                except grot.SafeError: pass
                grot.run(command + ['run', '--rm', 'probe', 'python', '/test/assert_destination.py', name], env=env, visible=True)
                ids = grot.run(command + ['ps', '-q'], env=env).split()
                inspected = json.loads(grot.run(['docker', 'inspect'] + ids))
                expected = {'ui': {'backend', 'ui'}, 'cart': {'backend'}, 'orders': {'backend', 'orders-db'}, 'postgres': {'database'},
                    'checkout': {'backend'}, 'catalog': {'backend'}, 'alloy': {'alloy', 'monitor-db'}, 'gateway': {'gateway'}}
                for container in inspected:
                    config = container['Config']
                    assert all(value not in json.dumps(config) for value in sensitive)
                    assert 'https://sink:18766/' not in json.dumps(config)
                    service = config['Labels']['com.docker.compose.service']
                    if service in expected:
                        mounts = {m['Destination'].split('/')[-1]: m for m in container['Mounts'] if m['Destination'].startswith('/run/grot/') and m['Type'] == 'volume'}
                        assert set(mounts) == expected[service]
                        assert not any(m['RW'] for m in mounts.values())
                        args_text = grot.run(['docker', 'exec', container['Id'], 'sh', '-c', "tr '\\000' ' ' </proc/1/cmdline"])
                        assert all(value not in args_text for value in sensitive)
                logs = grot.run(command + ['logs', '--no-color'], env=env)
                assert all(value not in logs for value in sensitive)
                # Also inspect the persistent collector buffer, not just host status files.
                audit = "import pathlib,sys,json; needles=[v.encode() for v in json.load(sys.stdin)]; assert all(all(n not in p.read_bytes() for n in needles) for p in pathlib.Path('/data').rglob('*') if p.is_file())"
                grot.run(['docker', 'run', '--rm', '-i', '--network', 'none', '-v',
                    f'grot-{alias}_alloy-data:/data:ro', 'python:3.12-alpine', 'python', '-c', audit], data=json.dumps(sensitive))
                for file in root.rglob('*'):
                    if file.is_file(): assert all(value.encode() not in file.read_bytes() for value in sensitive)
                print(f'{name}: five signals + DB health/query telemetry delivered; persisted orders and read-only monitoring verified; no credential canary in Docker configuration, process arguments, logs or host files; role mounts read-only.', flush=True)
            finally:
                state = grot.profile_path(alias) / 'run.json'
                if state.exists(): grot.stop(args)
                grot.run(command + ['down', '--volumes'], env=env)
            assert not grot_traffic.docker_object(args, grot), 'Traffic runner survived app teardown'
            assert not grot_activity.docker_object(args, grot), 'Automatic activity survived app teardown'
            assert not (grot.profile_path(alias) / 'run.json').exists()
            for volume in list(grot.runtime_volumes(alias).values()) + [f'grot-{alias}_alloy-data']:
                assert volume not in grot.run(['docker', 'volume', 'ls', '--format', '{{.Name}}']).splitlines()
print('Both runtime-only destinations verified and cleaned up.')
