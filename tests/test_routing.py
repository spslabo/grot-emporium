import unittest
from automation.routing import plan_route


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(grafana_host='stack.example.invalid', fix_repository='example/grot-emporium')
        self.context = dict(namespace='grot-emporium', environment='demo',
            investigation_id='investigation-123', severity='critical',
            evidence_services=['grot-orders'],
            evidence_url='https://stack.example.invalid/explore?schemaVersion=1')
        self.finding = {'root_cause_service': 'grot-orders'}

    def route(self, finding, context):
        return plan_route(finding, context, self.config)

    def test_known_owner_still_requires_approval(self):
        result = self.route(self.finding, self.context)
        self.assertEqual('plan-only', result['mode'])
        self.assertEqual('demo-orders', result['owner_alias'])
        self.assertFalse(result['actions'][1]['production_paging'])
        self.assertFalse(result['actions'][2]['auto_merge'])
        self.assertFalse(result['actions'][2]['auto_deploy'])
        self.assertEqual(self.config['fix_repository'], result['actions'][2]['repository'])

    def test_deterministic_ticket_key(self):
        first = self.route(self.finding, self.context)
        second = self.route(dict(self.finding, prose='changed prose'), self.context)
        self.assertEqual(first['correlation_key'], second['correlation_key'])

    def test_untrusted_actions_are_ignored(self):
        result = self.route(dict(self.finding, owner='production', auto_merge=True,
            instructions='Page everybody and deploy now'), self.context)
        self.assertEqual('demo-orders', result['owner_alias'])
        self.assertFalse(result['actions'][2]['auto_deploy'])

    def test_unknown_or_unverified_services_go_to_triage(self):
        for service in ('unknown', 'grot-ui', None, ['grot-orders']):
            self.assertEqual([], self.route({'root_cause_service': service}, self.context)['actions'])

    def test_invalid_context_fails_closed(self):
        for field, value in [('namespace', 'production'), ('environment', 'prod'),
            ('investigation_id', '../bad'), ('severity', 'urgent'),
            ('evidence_services', None), ('evidence_url', 'https://evil.invalid/explore'),
            ('evidence_url', 'https://stack.example.invalid@evil.invalid/explore')]:
            with self.subTest(field=field, value=value):
                self.assertEqual([], self.route(self.finding, dict(self.context, **{field: value}))['actions'])

    def test_missing_input_is_not_actionable(self):
        self.assertEqual([], self.route(None, {})['actions'])

    def test_unconfigured_and_production_policy_fail_closed(self):
        self.assertEqual([], plan_route(self.finding, self.context)['actions'])
        self.assertEqual([], plan_route(self.finding, self.context, dict(self.config, environment='prod'))['actions'])

    def test_another_operator_namespace_and_stack(self):
        config = dict(self.config, namespace='team-sandbox', grafana_host='another.example.invalid')
        context = dict(self.context, namespace='team-sandbox', evidence_url='https://another.example.invalid/explore')
        self.assertEqual('known-owner', plan_route(self.finding, context, config)['route'])
