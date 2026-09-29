import argparse
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from scripts import grot, grot_cloud


class CloudVerificationTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(destination='team-demo', grafana_context='test-cloud', cloud_cluster=None)
        self.commands = []
        self.missing_logs = False

    def execute(self, command):
        self.commands.append(command)
        if 'config' in command: return ''
        if 'datasources' in command:
            return json.dumps({'datasources': [{'uid': uid, 'type': kind} for kind, uid in grot_cloud.DATASOURCES.values()]})
        if 'series' in command:
            return json.dumps({'labelsSet': [{'labels': [{'name': 'service_name', 'value': s}, {'name': '__profile_type__', 'value': 'wall:wall:nanoseconds:wall:nanoseconds'}]} for s in grot_cloud.SERVICES]})
        if 'metrics' in command or 'logs' in command:
            names = [] if 'logs' in command and self.missing_logs else grot_cloud.SERVICES
            return json.dumps({'data': {'result': [{'metric': {'service_name': s}, 'value': [100, '1']} for s in names]}})
        if 'traces' in command: return '{"traces":[{"traceID":"synthetic"}]}'
        if 'profiles' in command: return '{"flamegraph":{"total":"12"}}'
        raise AssertionError('Unexpected command')

    def test_all_signals_and_services_with_explicit_context(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            grot_cloud.verify(self.args, self.execute, grot.SafeError)
        self.assertIn('not exact probe correlation', output.getvalue())
        self.assertTrue(all(cmd[:3] == ['gcx', '--context', 'test-cloud'] for cmd in self.commands))
        profile_queries = [c for c in self.commands if 'profiles' in c and 'query' in c]
        self.assertEqual(5, len(profile_queries))
        self.assertTrue(all('wall:wall:nanoseconds:wall:nanoseconds' in c for c in profile_queries))
        self.assertTrue(any('cluster="team-demo"' in ' '.join(c) for c in self.commands))

    def test_only_fixed_read_only_gcx_operations_are_used(self):
        with contextlib.redirect_stdout(io.StringIO()):
            grot_cloud.verify(self.args, self.execute, grot.SafeError)
        allowed = {('config', 'check'), ('datasources', 'list'),
                   ('metrics', 'query'), ('logs', 'query'), ('traces', 'query'),
                   ('profiles', 'series'), ('profiles', 'query')}
        for command in self.commands:
            self.assertEqual(['gcx', '--context', 'test-cloud', '--agent=false'], command[:4])
            self.assertIn(tuple(command[4:6]), allowed)

    def test_missing_logs_does_not_skip_other_signals(self):
        self.missing_logs = True
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(grot.SafeError, 'logs: this deployment'):
            grot_cloud.verify(self.args, self.execute, grot.SafeError)
        self.assertEqual(5, len([c for c in self.commands if 'profiles' in c and 'query' in c]))

    def test_quiet_services_are_reported_without_failing_working_log_ingestion(self):
        def execute(command):
            if 'logs' in command:
                return '{"data":{"result":[{"stream":{"service_name":"grot-catalog"},"values":[{"timestamp":"123","line":"3"}]}]}}'
            return self.execute(command)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            grot_cloud.verify(self.args, execute, grot.SafeError)
        self.assertIn('Recent logs from: grot-catalog', output.getvalue())
        self.assertIn('quiet services do not imply failed ingestion', output.getvalue())

    def test_empty_or_zero_samples_do_not_pass(self):
        for sample in ('0', 'NaN'):
            data = {'data': {'result': [{'metric': {'service_name': 'grot-ui'}, 'value': [100, sample]}]}}
            self.assertEqual(set(), grot_cloud.positive_services(data))
        self.assertEqual(set(), grot_cloud.positive_services({'status': 'success', 'data': {'result': []}}))

    def test_gcx_loki_normalized_counts_are_recognized(self):
        response = {'data': {'result': [
            {'stream': {'service_name': 'grot-ui'}, 'values': [{'timestamp': '123', 'line': '3'}]},
            {'stream': {'service_name': 'grot-cart'}, 'values': [{'timestamp': '123', 'line': '0'}]},
        ]}}
        self.assertEqual({'grot-ui'}, grot_cloud.positive_services(response))

    def test_format_error_is_not_reported_as_authentication_failure(self):
        def execute(command):
            if 'logs' in command: return '{"data":{"result":[{"stream":{},"values":[{"timestamp":"123","line":"invalid-canary"}]}]}}'
            return self.execute(command)
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(grot.SafeError):
            grot_cloud.verify(self.args, execute, grot.SafeError)
        self.assertIn('response', output.getvalue())
        self.assertIn('verifier compatibility error', output.getvalue())
        self.assertNotIn('invalid-canary', output.getvalue())

    def test_query_errors_do_not_print_private_output(self):
        def execute(command):
            if 'traces' in command: raise ValueError('private-query-canary')
            return self.execute(command)
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(grot.SafeError) as error:
            grot_cloud.verify(self.args, execute, grot.SafeError)
        self.assertNotIn('private-query-canary', output.getvalue() + str(error.exception))

    def test_cloud_stage_still_runs_after_transport_failure(self):
        with patch.object(grot, 'verify_local', side_effect=grot.SafeError('transport failed')), patch.object(grot, 'verify_cloud') as cloud, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(grot.SafeError):
            grot.verify(self.args)
        cloud.assert_called_once_with(self.args)
