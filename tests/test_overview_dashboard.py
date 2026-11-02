"""Portable overview dashboard structure and signal-boundary regression tests."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OverviewDashboardTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = json.loads((ROOT / 'observability/dashboards/grot-emporium-overview.json').read_text())

    def test_panel_ids_and_grid_are_valid(self):
        panels = self.dashboard['panels']
        self.assertEqual(len(panels), len({p['id'] for p in panels}))
        for panel in panels:
            grid = panel['gridPos']
            self.assertGreater(grid['h'], 0)
            self.assertGreater(grid['w'], 0)
            self.assertLessEqual(grid['x'] + grid['w'], 24)
        text = next(p for p in panels if p['title'] == 'Reading this demo')
        self.assertGreaterEqual(text['gridPos']['h'], 8)

    def test_portable_deployment_selectors(self):
        variables = {v['name']: v for v in self.dashboard['templating']['list']}
        for name in ('metrics', 'logs', 'traces', 'profiles'):
            self.assertEqual(variables[name]['type'], 'datasource')
        for name in ('cluster', 'namespace'):
            self.assertFalse(variables[name].get('current', {}).get('value'))
        serialized = json.dumps(self.dashboard)
        self.assertNotIn('spslab.grafana.net', serialized)
        self.assertNotIn('grot-aws-quick', serialized)

    def test_business_counters_and_optional_signal_semantics(self):
        queries = '\n'.join(t.get('expr', '') for p in self.dashboard['panels'] for t in p.get('targets', []))
        for metric in ('grot_orders_total', 'grot_orders_items_total', 'grot_orders_value_total'):
            self.assertIn(metric, queries)
        self.assertNotIn('or vector(0)', queries)
        self.assertIn('agento11y_tag_cluster', queries)


if __name__ == '__main__':
    unittest.main()
