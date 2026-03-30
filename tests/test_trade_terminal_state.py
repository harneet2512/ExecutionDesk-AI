"""Tests for trade state: fill columns populated, terminal status clean."""
import pytest
import json
from unittest.mock import patch


class TestPaperProviderFills:
    """PaperProvider.place_order must set filled_qty, avg_fill_price, total_fees."""

    def test_place_order_sets_fill_columns(self, test_db):
        """After place_order, filled_qty/avg_fill_price/total_fees are NOT NULL."""
        from backend.providers.paper import PaperProvider
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        # Create a run first
        run_id = new_id("run_")
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, "t_default", "RUNNING", "PAPER", now_iso())
            )
            conn.commit()

        provider = PaperProvider()
        with patch("backend.providers.paper.get_price", return_value=50000.0):
            order_id = provider.place_order(
                run_id=run_id,
                tenant_id="t_default",
                symbol="BTC",
                side="BUY",
                notional_usd=10.0
            )

        # Verify fill columns are set
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            order = cursor.fetchone()

        assert order is not None
        assert order["filled_qty"] is not None, "filled_qty must not be NULL"
        assert order["avg_fill_price"] is not None, "avg_fill_price must not be NULL"
        assert order["total_fees"] is not None, "total_fees must not be NULL"
        assert order["status_updated_at"] is not None, "status_updated_at must not be NULL"

        # Verify values are correct
        assert float(order["filled_qty"]) == pytest.approx(10.0 / 50000.0)
        assert float(order["avg_fill_price"]) == pytest.approx(50000.0)
        assert float(order["total_fees"]) == 0.0

    def test_place_order_status_is_filled(self, test_db):
        """PAPER orders are immediately FILLED."""
        from backend.providers.paper import PaperProvider
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        run_id = new_id("run_")
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, "t_default", "RUNNING", "PAPER", now_iso())
            )
            conn.commit()

        provider = PaperProvider()
        with patch("backend.providers.paper.get_price", return_value=3000.0):
            order_id = provider.place_order(
                run_id=run_id,
                tenant_id="t_default",
                symbol="ETH",
                side="SELL",
                notional_usd=5.0
            )

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
            order = cursor.fetchone()

        assert order["status"] == "FILLED"

    def test_place_order_creates_portfolio_snapshot(self, test_db):
        """place_order creates a portfolio_snapshot row."""
        from backend.providers.paper import PaperProvider
        from backend.db.connect import get_conn
        from backend.core.ids import new_id
        from backend.core.time import now_iso

        run_id = new_id("run_")
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, "t_default", "RUNNING", "PAPER", now_iso())
            )
            conn.commit()

        provider = PaperProvider()
        with patch("backend.providers.paper.get_price", return_value=50000.0):
            provider.place_order(
                run_id=run_id,
                tenant_id="t_default",
                symbol="BTC",
                side="BUY",
                notional_usd=10.0
            )

        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM portfolio_snapshots WHERE run_id = ?", (run_id,))
            snap = cursor.fetchone()

        assert snap is not None
        positions = json.loads(snap["positions_json"])
        assert "BTC" in positions
