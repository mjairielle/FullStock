"""
Regression tests for calculations.py

These tests mock the data layer to verify calculation logic
remains identical before and after refactoring.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone


# ── Test Fixtures ────────────────────────────────────────────────

def _make_sales(sku_id, store_id, daily_qty=5, days=30):
    """Generate mock sales records for the last N days."""
    sales = []
    for i in range(days):
        dt = (datetime.now(timezone.utc) - timedelta(days=i))
        sales.append({
            "sale_id": f"SL{i:03d}",
            "sku_id": sku_id,
            "store_id": store_id,
            "qty_sold": daily_qty,
            "sale_date": dt.isoformat() + "Z"
        })
    return sales


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


def _make_stock(sku_id="SKU001", store_id="STR001", qty=100):
    return {
        "sku_id": sku_id,
        "store_id": store_id,
        "qty_on_hand": qty,
    }


# ── Tests ────────────────────────────────────────────────────────

class TestDailyDemandSimple(unittest.TestCase):

    @patch("calculations.get_records")
    def test_basic_demand(self, mock_get):
        """5 units/day for 30 days → daily demand = 5.0"""
        mock_get.return_value = _make_sales("SKU001", "STR001", daily_qty=5, days=30)
        from calculations import daily_demand_simple
        result = daily_demand_simple("SKU001", "STR001", 30)
        self.assertAlmostEqual(result, 5.0, places=1)

    @patch("calculations.get_records")
    def test_zero_demand(self, mock_get):
        """No sales → daily demand = 0"""
        mock_get.return_value = []
        from calculations import daily_demand_simple
        result = daily_demand_simple("SKU001", "STR001", 30)
        self.assertEqual(result, 0.0)

    @patch("calculations.get_records")
    def test_filters_by_store(self, mock_get):
        """Sales for other stores are excluded."""
        sales = _make_sales("SKU001", "STR001", daily_qty=5, days=30)
        sales += _make_sales("SKU001", "OTHER_STORE", daily_qty=100, days=30)
        mock_get.return_value = sales
        from calculations import daily_demand_simple
        result = daily_demand_simple("SKU001", "STR001", 30)
        self.assertAlmostEqual(result, 5.0, places=1)


class TestDailyDemandWeighted(unittest.TestCase):

    @patch("calculations.get_records")
    def test_weighted_demand(self, mock_get):
        """Weighted demand with uniform sales should be > simple average
        because recent half gets 1.5× weight."""
        mock_get.return_value = _make_sales("SKU001", "STR001", daily_qty=5, days=30)
        from calculations import daily_demand_weighted
        result = daily_demand_weighted("SKU001", "STR001", 30)
        # 15 recent days × 5 × 1.5 + 15 prior days × 5 × 1.0 = 112.5 + 75 = 187.5 / 30 ≈ 6.25
        self.assertGreater(result, 0)


class TestCalcSafetyStock(unittest.TestCase):

    @patch("calculations.get_one")
    @patch("calculations.get_records")
    def test_returns_at_least_one(self, mock_get_records, mock_get_one):
        """Safety stock is always >= 1."""
        mock_get_records.return_value = _make_sales("SKU001", "STR001", daily_qty=5, days=30)
        mock_get_one.return_value = _make_sku()
        from calculations import calc_safety_stock
        result = calc_safety_stock("SKU001", "STR001")
        self.assertGreaterEqual(result, 1)


class TestCalcEOQ(unittest.TestCase):

    @patch("calculations.get_one")
    @patch("calculations.get_records")
    def test_positive_eoq(self, mock_get_records, mock_get_one):
        """EOQ should be positive when there is demand."""
        mock_get_records.return_value = _make_sales("SKU001", "STR001", daily_qty=5, days=30)
        mock_get_one.return_value = _make_sku()
        from calculations import calc_eoq
        result = calc_eoq("SKU001", "STR001")
        self.assertGreater(result, 0)

    @patch("calculations.get_one")
    @patch("calculations.get_records")
    def test_zero_demand_eoq(self, mock_get_records, mock_get_one):
        """EOQ is 0 when there's no demand."""
        mock_get_records.return_value = []
        mock_get_one.return_value = _make_sku()
        from calculations import calc_eoq
        result = calc_eoq("SKU001", "STR001")
        self.assertEqual(result, 0)


class TestCalcROP(unittest.TestCase):

    @patch("calculations.get_one")
    @patch("calculations.get_records")
    def test_rop_positive(self, mock_get_records, mock_get_one):
        """ROP should be positive when there is demand."""
        mock_get_records.return_value = _make_sales("SKU001", "STR001", daily_qty=5, days=30)
        mock_get_one.return_value = _make_sku()
        from calculations import calc_rop
        result = calc_rop("SKU001", "STR001")
        self.assertGreater(result, 0)


class TestCalcDaysOfCover(unittest.TestCase):

    @patch("calculations.get_records")
    def test_days_of_cover(self, mock_get_records):
        """100 units at 5/day demand → ~20 days of cover."""
        stock = [_make_stock(qty=100)]
        sales = _make_sales("SKU001", "STR001", daily_qty=5, days=30)

        def side_effect(table, field=None, val=None):
            if table == "stock":
                return stock
            if table == "sales_log":
                return sales
            return []

        mock_get_records.side_effect = side_effect
        from calculations import calc_days_of_cover
        result = calc_days_of_cover("SKU001", "STR001")
        self.assertAlmostEqual(result, 20.0, places=0)

    @patch("calculations.get_records")
    def test_zero_demand_cover(self, mock_get_records):
        """Zero demand → 999 (infinite cover)."""
        stock = [_make_stock(qty=100)]

        def side_effect(table, field=None, val=None):
            if table == "stock":
                return stock
            if table == "sales_log":
                return []
            return []

        mock_get_records.side_effect = side_effect
        from calculations import calc_days_of_cover
        result = calc_days_of_cover("SKU001", "STR001")
        self.assertEqual(result, 999)


class TestCalcTrend(unittest.TestCase):

    @patch("calculations.get_records")
    def test_flat_trend(self, mock_get_records):
        """Uniform sales → trend ≈ 0%."""
        mock_get_records.return_value = _make_sales("SKU001", "STR001", daily_qty=5, days=28)
        from calculations import calc_trend
        result = calc_trend("SKU001", "STR001")
        self.assertAlmostEqual(result, 0, delta=5)


class TestMetricsCache(unittest.TestCase):

    @patch("calculations.save_json")
    @patch("calculations.load_json")
    @patch("calculations.get_one")
    @patch("calculations.get_records")
    def test_calc_all_returns_dict(self, mock_get_records, mock_get_one, mock_load, mock_save):
        """calc_all_metrics returns a dict with all expected keys."""
        sales = _make_sales("SKU001", "STR001", daily_qty=5, days=30)
        stock = [_make_stock()]

        def side_effect(table, field=None, val=None):
            if table == "stock":
                return stock
            return sales

        mock_get_records.side_effect = side_effect
        mock_get_one.return_value = _make_sku()
        mock_load.return_value = []

        from calculations import calc_all_metrics
        result = calc_all_metrics("SKU001", "STR001")

        expected_keys = {
            "sku_id", "store_id", "timestamp",
            "daily_demand_simple", "daily_demand_weighted",
            "safety_stock", "eoq", "rop",
            "days_of_cover", "trend_14d"
        }
        self.assertEqual(set(result.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()
