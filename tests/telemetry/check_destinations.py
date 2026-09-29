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
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import grot
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
                with patch.object(sys, 'stdin', io.StringIO(json.dumps(mock_settings(name)))):
                    grot.docker(args)
                grot.verify(args)
                grot.run(command + ['run', '--rm', 'probe', 'python', '/test/assert_destination.py', name], env=env, visible=True)
                ids = grot.run(command + ['ps', '-q'], env=env).split()
                inspected = json.loads(grot.run(['docker', 'inspect'] + ids))
                expected = {'ui': {'backend', 'ui'}, 'cart': {'backend'}, 'orders': {'backend'},
                    'checkout': {'backend'}, 'catalog': {'backend'}, 'alloy': {'alloy'}, 'gateway': {'gateway'}}
                for container in inspected:
                    config = container['Config']
                    assert 'dummy-not-a-real-token' not in json.dumps(config)
                    assert 'https://sink:18766/' not in json.dumps(config)
                    service = config['Labels']['com.docker.compose.service']
                    if service in expected:
                        mounts = {m['Destination'].split('/')[-1]: m for m in container['Mounts'] if m['Destination'].startswith('/run/grot/') and m['Type'] == 'volume'}
                        assert set(mounts) == expected[service]
                        assert not any(m['RW'] for m in mounts.values())
                        args_text = grot.run(['docker', 'exec', container['Id'], 'sh', '-c', "tr '\\000' ' ' </proc/1/cmdline"])
                        assert 'dummy-not-a-real-token' not in args_text
                logs = grot.run(command + ['logs', '--no-color'], env=env)
                assert 'dummy-not-a-real-token' not in logs
                # Also inspect the persistent collector buffer, not just host status files.
                audit = "import pathlib,sys; needle=sys.stdin.buffer.read(); assert all(needle not in p.read_bytes() for p in pathlib.Path('/data').rglob('*') if p.is_file())"
                grot.run(['docker', 'run', '--rm', '-i', '--network', 'none', '-v',
                    f'grot-{alias}_alloy-data:/data:ro', 'python:3.12-alpine', 'python', '-c', audit], data='dummy-not-a-real-token')
                for file in root.rglob('*'):
                    if file.is_file(): assert b'dummy-not-a-real-token' not in file.read_bytes()
                print(f'{name}: five signals delivered; no credential canary in Docker configuration, process arguments, logs or host files; role mounts read-only.', flush=True)
            finally:
                state = grot.profile_path(alias) / 'run.json'
                if state.exists(): grot.stop(args)
                grot.run(command + ['down', '--volumes'], env=env)
            assert not (grot.profile_path(alias) / 'run.json').exists()
            for volume in list(grot.runtime_volumes(alias).values()) + [f'grot-{alias}_alloy-data']:
                assert volume not in grot.run(['docker', 'volume', 'ls', '--format', '{{.Name}}']).splitlines()
print('Both runtime-only destinations verified and cleaned up.')
