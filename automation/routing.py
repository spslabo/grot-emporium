"""Pure, offline routing policy for a future Workflow adapter; performs NO actions.
trusted_context must come from verified alert/workflow metadata, never LLM prose.
Owner names below are demo aliases, not real Jira/IRM team or recipient IDs.
"""
import hashlib
import re
from urllib.parse import urlsplit

OWNERS = {
    'grot-ui': 'demo-storefront',
    'grot-catalog': 'demo-catalog',
    'grot-cart': 'demo-cart',
    'grot-checkout': 'demo-checkout',
    'grot-orders': 'demo-orders',
}


def plan_route(finding, trusted_context, configuration=None):
    def triage(reason):
        return {'mode': 'plan-only', 'route': 'triage', 'reason': reason, 'actions': []}

    # Configuration is operator-supplied private runtime data, NEVER model output.
    if not isinstance(configuration, dict):
        return triage('routing_not_configured')
    host = configuration.get('grafana_host')
    repository = configuration.get('fix_repository')
    environment = configuration.get('environment', 'demo')
    namespace = configuration.get('namespace', 'grot-emporium')
    if (not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9.-]+', host)
            or not isinstance(repository, str)
            or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*', repository)
            or environment not in ('demo', 'test', 'development')
            or not isinstance(namespace, str)
            or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', namespace)):
        return triage('invalid_routing_configuration')
    if not isinstance(finding, dict) or not isinstance(trusted_context, dict):
        return triage('invalid_input')
    if (trusted_context.get('namespace') != namespace
            or trusted_context.get('environment') != environment):
        return triage('outside_demo_scope')
    investigation = trusted_context.get('investigation_id')
    if not isinstance(investigation, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', investigation):
        return triage('invalid_investigation_id')
    service = finding.get('root_cause_service')
    if not isinstance(service, str) or service not in OWNERS:
        return triage('unknown_service')
    # Evidence services must be derived from queried telemetry, not model claims.
    evidence_services = trusted_context.get('evidence_services')
    if not isinstance(evidence_services, list) or service not in evidence_services:
        return triage('unverified_root_cause_service')
    severity = trusted_context.get('severity')
    if severity not in ('warning', 'critical'):
        return triage('unsupported_severity')
    evidence = trusted_context.get('evidence_url', '')
    if not isinstance(evidence, str):
        return triage('invalid_evidence_url')
    try:
        url = urlsplit(evidence)
        valid = (url.scheme == 'https' and url.hostname == host.lower()
                 and url.port in (None, 443) and not url.username and not url.password
                 and url.path.startswith(('/a/', '/explore')) and not url.fragment)
    except ValueError:
        valid = False
    if not valid:
        return triage('invalid_evidence_url')
    return {
        'mode': 'plan-only', 'route': 'known-owner', 'owner_alias': OWNERS[service],
        'service': service, 'severity': severity, 'evidence_url': evidence,
        'correlation_key': 'grot-' + hashlib.sha256(f'{host.lower()}:{namespace}:{environment}:{investigation}'.encode()).hexdigest()[:24],
        'actions': [
            {'kind': 'jira-upsert', 'requires_approved_sandbox_mapping': True},
            {'kind': 'irm-test-route', 'requires_human_approval': True, 'production_paging': False},
            {'kind': 'coding-agent-pr', 'repository': repository,
             'requires_human_approval': True, 'auto_merge': False, 'auto_deploy': False},
        ],
    }
