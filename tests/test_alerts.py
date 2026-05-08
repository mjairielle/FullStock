"""
Regression tests for alerts.py

Verifies alert severity classification and buy recommendations
remain identical before and after refactoring.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone


# ── Fixtures ─────────────────────────────────────────────────────

def _make_metrics(rop=50, eoq=100, trend=0, days_of_cover=20):
    return {
        "sku_id": "SKU001",
        "store_id": "STR001",
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "daily_demand_simple": 5.0,
        "daily_demand_weighted": 6.25,
        "safety_stock": 10,
        "eoq": eoq,
        "rop": rop,
        "days_of_cover": days_of_cover,
        "trend_14d": trend,
    }


def _make_stock_records(sku_id="SKU001", store_id="STR001", qty=100):
    return [{
        "sku_id": sku_id,
        "store_id": store_id,
        "qty_on_hand": qty,
    }]


def _make_sku(sku_id="SKU001", store_id="STR001"):
    return {
        "sku_id": sku_id,
        "store_id": store_id,
        "product_name": "Test Product",
        "category": "electronics",
        "unit_cost": 100,
        "order_cost": 50,
        "hold_cost_annual": 25,
        "lead_time_days": 7,
    }


# ── Tests ────────────────────────────────────────────────────────

class TestCheckStockAlert(unittest.TestCase):

    @patch("alerts.get_metrics")
    @patch("alerts.get_records")
    def test_critical_when_zero_stock(self, mock_records, mock_metrics):
        mock_records.return_value = _make_stock_records(qty=0)
        mock_metrics.return_value = _make_metrics(rop=50)
        from alerts import check_stock_alert
        self.assertEqual(check_stock_alert("SKU001", "STR001"), "critical")

    @patch("alerts.get_metrics")
    @patch("alerts.get_records")
    def test_warning_when_below_rop(self, mock_records, mock_metrics):
        mock_records.return_value = _make_stock_records(qty=30)
        mock_metrics.return_value = _make_metrics(rop=50)
        from alerts import check_stock_alert
        self.assertEqual(check_stock_alert("SKU001", "STR001"), "warning")

    @patch("alerts.get_metrics")
    @patch("alerts.get_records")
    def test_info_when_below_2x_rop(self, mock_records, mock_metrics):
        mock_records.return_value = _make_stock_records(qty=70)
        mock_metrics.return_value = _make_metrics(rop=50)
        from alerts import check_stock_alert
        self.assertEqual(check_stock_alert("SKU001", "STR001"), "info")

    @patch("alerts.get_metrics")
    @patch("alerts.get_records")
    def test_ok_when_sufficient(self, mock_records, mock_metrics):
        mock_records.return_value = _make_stock_records(qty=200)
        mock_metrics.return_value = _make_metrics(rop=50)
        from alerts import check_stock_alert
        self.assertEqual(check_stock_alert("SKU001", "STR001"), "ok")


class TestGetBuyRecommendation(unittest.TestCase):

    @patch("alerts.check_stock_alert")
    @patch("alerts.get_metrics")
    def test_no_buy_when_ok(self, mock_metrics, mock_alert):
        mock_metrics.return_value = _make_metrics(trend=5)
        mock_alert.return_value = "ok"
        from alerts import get_buy_recommendation
        rec = get_buy_recommendation("SKU001", "STR001")
        self.assertFalse(rec["should_buy"])
        self.assertEqual(rec["qty_to_buy"], 0)

    @patch("alerts.check_stock_alert")
    @patch("alerts.get_metrics")
    def test_buy_when_critical(self, mock_metrics, mock_alert):
        mock_metrics.return_value = _make_metrics(eoq=100)
        mock_alert.return_value = "critical"
        from alerts import get_buy_recommendation
        rec = get_buy_recommendation("SKU001", "STR001")
        self.assertTrue(rec["should_buy"])
        self.assertEqual(rec["qty_to_buy"], 100)
        self.assertIn("Critical", rec["reason"])

    @patch("alerts.check_stock_alert")
    @patch("alerts.get_metrics")
    def test_buy_when_warning(self, mock_metrics, mock_alert):
        mock_metrics.return_value = _make_metrics(eoq=100)
        mock_alert.return_value = "warning"
        from alerts import get_buy_recommendation
        rec = get_buy_recommendation("SKU001", "STR001")
        self.assertTrue(rec["should_buy"])
        self.assertIn("ROP", rec["reason"])

    @patch("alerts.check_stock_alert")
    @patch("alerts.get_metrics")
    def test_low_demand_flag(self, mock_metrics, mock_alert):
        mock_metrics.return_value = _make_metrics(trend=-15)
        mock_alert.return_value = "ok"
        from alerts import get_buy_recommendation
        rec = get_buy_recommendation("SKU001", "STR001")
        self.assertTrue(rec["low_demand_flag"])
        self.assertFalse(rec["should_buy"])


class TestBuildAlert(unittest.TestCase):

    @patch("alerts.get_buy_recommendation")
    @patch("alerts.check_stock_alert")
    @patch("alerts.get_metrics")
    @patch("alerts.get_records")
    @patch("alerts.get_one")
    def test_build_alert_keys(self, mock_one, mock_records, mock_metrics, mock_alert, mock_rec):
        mock_one.return_value = _make_sku()
        mock_records.return_value = _make_stock_records(qty=100)
        mock_metrics.return_value = _make_metrics()
        mock_alert.return_value = "ok"
        mock_rec.return_value = {
            "should_buy": False,
            "qty_to_buy": 0,
            "low_demand_flag": False,
            "reason": "Sufficient stock",
        }
        from alerts import build_alert
        result = build_alert("SKU001", "STR001")

        expected_keys = {
            "sku_id", "store_id", "product_name", "qty_on_hand",
            "rop", "eoq", "days_of_cover", "trend_14d",
            "severity", "should_buy", "qty_to_buy",
            "low_demand_flag", "reason", "timestamp",
        }
        self.assertEqual(set(result.keys()), expected_keys)
        self.assertEqual(result["product_name"], "Test Product")


if __name__ == "__main__":
    unittest.main()
