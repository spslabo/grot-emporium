import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('verify_purchase', Path(__file__).resolve().parents[1] / 'scripts/verify_purchase.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

ORDER = '12345678-1234-1234-1234-123456789abc'
EMAIL = 'aaif-' + 'a' * 32 + '@example.test'


class PurchaseProbeTests(unittest.TestCase):
    def test_confirmation_requires_business_marker(self):
        with self.assertRaises(ValueError):
            probe.Page('<p>Order ID</p><p>' + ORDER + '</p>').order_id()

    def test_confirmation_extracts_exact_order(self):
        page = probe.Page('<p>Order ID</p><p>' + ORDER + '</p><span id="order-subtotal">10</span>')
        self.assertEqual(page.order_id(), ORDER)

    def test_http_200_error_page_is_not_confirmation(self):
        with self.assertRaises(ValueError):
            probe.Page('<html>Something went wrong</html>').order_id()

    def test_missing_id_is_not_confirmation(self):
        with self.assertRaises(ValueError):
            probe.Page('<span id="order-subtotal">10</span>').order_id()

    def test_delivery_token(self):
        self.assertEqual(probe.Page('<input type="radio" value="shipping-token">').radios, ['shipping-token'])

    def test_query_matches_exact_order_and_item(self):
        sql = probe.persistence_sql(ORDER, ORDER, EMAIL, 15)
        self.assertIn('BEGIN READ ONLY', sql)
        self.assertIn('i.quantity=1', sql)
        self.assertIn("s.email='" + EMAIL + "'", sql)
        self.assertIn('i.unit_cost=15 AND i.total_cost=15', sql)
        self.assertIn('ROLLBACK', sql)

    def test_query_rejects_injection(self):
        for values in [("'; DROP TABLE orders;", ORDER, EMAIL), (ORDER, ORDER, "' OR true --")]:
            with self.assertRaises(ValueError):
                probe.persistence_sql(*values, 15)

    def test_query_rejects_invalid_cost(self):
        for cost in (-1, True, '15; DROP TABLE orders'):
            with self.assertRaises(ValueError):
                probe.persistence_sql(ORDER, ORDER, EMAIL, cost)


if __name__ == '__main__':
    unittest.main()
