import argparse
import base64
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from scripts import grot, grot_agent


class AgentSetupTests(unittest.TestCase):
    def test_credentials_only_in_secret_stdin_and_model_unchanged(self):
        args = argparse.Namespace(destination='demo', context='test', namespace='grot-demo', metadata_only=True)
        ledger = {'data': {'destination': 'demo', 'owner': 'owner'}}
        existing = {'RETAIL_UI_CHAT_ENABLED': 'true', 'RETAIL_UI_CHAT_PROVIDER': 'bedrock',
                    'RETAIL_UI_CHAT_MODEL': 'us.amazon.nova-lite-v1:0', 'RETAIL_UI_CHAT_BEDROCK_REGION': 'us-east-2'}
        secret = {'metadata': {'resourceVersion': '7'}, 'data': {k: base64.b64encode(v.encode()).decode() for k,v in existing.items()}}
        with patch.object(grot_agent.sys.stdin, 'isatty', return_value=True), patch.object(grot, 'get_object', side_effect=[ledger, secret]), patch.object(grot, 'owned', return_value=True), patch.object(grot, 'prompt_setting', side_effect=['https://ingest.example.test', '123', 'token-canary']), patch.object(grot, 'run', autospec=True) as run, contextlib.redirect_stdout(io.StringIO()) as output:
            grot_agent.configure(args, grot)
        calls = run.call_args_list
        payload = json.loads(calls[0].kwargs['data'])
        values = {k: base64.b64decode(v).decode() for k,v in payload['data'].items()}
        self.assertEqual('token-canary', values['AGENTO11Y_AUTH_TOKEN'])
        self.assertEqual('http', values['AGENTO11Y_PROTOCOL'])
        self.assertEqual('otlp', values['OTEL_METRICS_EXPORTER'])
        self.assertFalse(any(k.startswith('RETAIL_UI_CHAT') for k in values))
        self.assertNotIn('token-canary', output.getvalue())
        self.assertNotIn('token-canary', json.dumps([c.args[0] for c in calls]))
        self.assertEqual('7', payload['metadata']['resourceVersion'])

    def existing(self):
        return {'RETAIL_UI_CHAT_ENABLED': 'true', 'RETAIL_UI_CHAT_PROVIDER': 'bedrock',
                'RETAIL_UI_CHAT_MODEL': 'us.amazon.nova-lite-v1:0', 'RETAIL_UI_CHAT_BEDROCK_REGION': 'us-east-2',
                'AGENTO11Y_ENDPOINT': 'https://ingest.example.test', 'AGENTO11Y_AUTH_TENANT_ID': '123',
                'AGENTO11Y_AUTH_TOKEN': 'token-canary'}

    def test_capture_consent_and_labels_reuse_credentials(self):
        existing = self.existing(); existing['AGENTO11Y_TAGS'] = 'team=demo'
        with patch('builtins.input', return_value='yes'), patch.object(grot, 'prompt_setting') as prompt:
            values = grot_agent.setup_values(argparse.Namespace(destination='demo'), existing, grot)
        prompt.assert_not_called()
        self.assertEqual('full_with_metadata_spans', values['AGENTO11Y_CONTENT_CAPTURE_MODE'])
        self.assertIn('cluster=demo', values['AGENTO11Y_TAGS'])
        self.assertIn('team=demo', values['AGENTO11Y_TAGS'])
        self.assertEqual('otlp', values['OTEL_METRICS_EXPORTER'])

    def test_no_consent_keeps_metadata_only(self):
        with patch('builtins.input', return_value=''):
            values = grot_agent.setup_values(argparse.Namespace(destination='demo'), self.existing(), grot)
        self.assertEqual('metadata_only', values['AGENTO11Y_CONTENT_CAPTURE_MODE'])

    def test_openai_provider_collects_key_privately(self):
        args = argparse.Namespace(destination='demo', provider='openai', model='approved-model', capture_content=True)
        with patch.object(grot, 'prompt_setting', return_value='provider-canary') as prompt:
            values = grot_agent.setup_values(args, self.existing(), grot)
        self.assertEqual('https://api.openai.com', values['RETAIL_UI_CHAT_OPENAI_BASE_URL'])
        self.assertEqual('provider-canary', values['RETAIL_UI_CHAT_OPENAI_API_KEY'])
        self.assertEqual('openai', values['RETAIL_UI_CHAT_PROVIDER'])
        self.assertEqual(1, prompt.call_count)

    def test_verify_requires_consent_before_reading_or_writing(self):
        with patch.object(grot_agent.sys.stdin, 'isatty', return_value=True), patch.object(grot, 'get_object') as get:
            with self.assertRaises(grot.SafeError):
                grot_agent.configure(argparse.Namespace(verify=True), grot)
        get.assert_not_called()

    def test_verify_one_request_then_generation_trace_and_metrics(self):
        cid = '12345678-1234-4234-8234-123456789abc'
        prompt = 'Suggest a Grot desk companion in one short sentence.'
        generation = {'model': {'name': 'us.amazon.nova-lite-v1:0', 'provider': 'bedrock'}, 'system_prompt': 'test',
                      'input': [{'parts': [{'text': prompt}]}], 'output': [{'parts': [{'text': 'Hello'}]}], 'trace_id': 'a'*32, 'span_id': 'b'*16}
        values = self.existing(); values['AGENTO11Y_CONTENT_CAPTURE_MODE'] = 'full_with_metadata_spans'
        replies = ['data:{"text":"Hello"}\n\n', json.dumps({'generations': [generation]}),
                   json.dumps({'trace': {'resourceSpans': [{'scopeSpans': [{'spans': [{'spanId': 'b'*16}]}]}]}}), json.dumps({'data': {'result': [1]}})]
        with patch.object(grot_agent.uuid, 'uuid4', return_value=cid), patch.object(grot, 'run', side_effect=replies) as run:
            grot_agent.verify(argparse.Namespace(destination='demo', grafana_context='test'), ['kubectl'], values, grot)
        self.assertEqual(1, sum('exec' in c.args[0] for c in run.call_args_list))
        self.assertFalse(any('evaluators' in c.args[0] or 'experiments' in c.args[0] for c in run.call_args_list))

    def test_trace_verification_requires_generation_span(self):
        span_id = 'abcd1234abcd1234'
        encoded = base64.b64encode(bytes.fromhex(span_id)).decode()
        trace = {'trace': {'resourceSpans': [{'scopeSpans': [{'spans': [{'spanId': encoded}]}]}]}}
        self.assertTrue(grot_agent.trace_has_span(trace, span_id))
        self.assertFalse(grot_agent.trace_has_span(trace, 'a'*16))
        self.assertFalse(grot_agent.trace_has_span({'trace': {'resourceSpans': []}}, span_id))

    def test_verify_rejects_old_metadata_only_image(self):
        values = self.existing(); values['AGENTO11Y_CONTENT_CAPTURE_MODE'] = 'full_with_metadata_spans'
        generation = {'model': {'name': values['RETAIL_UI_CHAT_MODEL'], 'provider': 'bedrock'}}
        with patch.object(grot, 'run', side_effect=['data:{"text":"Hello"}\n\n', json.dumps({'generations': [generation]})]):
            with self.assertRaisesRegex(grot.SafeError, 'updated UI image'):
                grot_agent.verify(argparse.Namespace(destination='demo', grafana_context='test'), ['kubectl'], values, grot)

    def test_optional_image_upgrade_is_one_rollout(self):
        args = argparse.Namespace(destination='demo', context='test', namespace='grot-demo', capture_content=True,
                                  ui_image='registry.example.test/ui@sha256:' + 'a'*64)
        ledger = {'data': {'destination': 'demo', 'owner': 'owner'}}
        secret = {'metadata': {'resourceVersion': '7'}, 'data': {k: base64.b64encode(v.encode()).decode() for k,v in self.existing().items()}}
        with patch.object(grot_agent.sys.stdin, 'isatty', return_value=True), patch.object(grot, 'get_object', side_effect=[ledger, secret]), patch.object(grot, 'owned', return_value=True), patch.object(grot, 'run') as run:
            grot_agent.configure(args, grot)
        self.assertEqual(3, run.call_count)
        template = json.loads(run.call_args_list[1].kwargs['data'])['spec']['template']
        self.assertEqual(args.ui_image, template['spec']['containers'][0]['image'])
        self.assertEqual(args.ui_image, template['spec']['containers'][0]['env'][0]['value'])
        self.assertIn('grot-agento11y-revision', template['metadata']['annotations'])
        self.assertFalse(any('restart' in c.args[0] for c in run.call_args_list))

    def test_external_secret_is_not_modified(self):
        args = argparse.Namespace(destination='demo', context='test', namespace='grot-demo')
        ledger = {'data': {'destination': 'demo', 'owner': 'owner'}}
        with patch.object(grot_agent.sys.stdin, 'isatty', return_value=True), patch.object(grot, 'get_object', side_effect=[ledger, {}]), patch.object(grot, 'owned', return_value=True), patch.object(grot, 'run') as run:
            with self.assertRaises(grot.SafeError): grot_agent.configure(args, grot)
        run.assert_not_called()

    def test_verification_failure_does_not_retry_model(self):
        with patch.object(grot, 'run', side_effect=grot.SafeError('private error')) as run:
            with self.assertRaisesRegex(grot.SafeError, 'No model request was retried'):
                grot_agent.verify(argparse.Namespace(destination='demo', grafana_context='test'), ['kubectl'], self.existing(), grot)
        self.assertEqual(1, run.call_count)

    def test_capture_modes_are_explicit_and_validated(self):
        for mode in ['metadata_only', 'full', 'no_tool_content', 'full_with_metadata_spans']:
            grot.validate('ui', {'AGENTO11Y_CONTENT_CAPTURE_MODE': mode}, partial=True)
        with self.assertRaises(grot.SafeError):
            grot.validate('ui', {'AGENTO11Y_CONTENT_CAPTURE_MODE': 'typo'}, partial=True)

    def test_noninteractive_input_is_rejected_before_access(self):
        with patch.object(grot_agent.sys.stdin, 'isatty', return_value=False), patch.object(grot, 'get_object') as get:
            with self.assertRaises(grot.SafeError): grot_agent.configure(argparse.Namespace(), grot)
        get.assert_not_called()
