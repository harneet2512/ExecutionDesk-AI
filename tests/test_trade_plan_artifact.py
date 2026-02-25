"""Tests for trade_plan and trade_receipt artifact invariants.

Validates:
1. trade_plan artifact has required fields
2. Portfolio snapshots >= 2 invariant (required for chart)
3. trade_receipt artifact has venue field
"""
import json
import pytest
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso

TENANT_ID = "t_default"


def _ensure_tenant(cursor):
    cursor.execute(
        "INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?, 'Test Tenant')",
        (TENANT_ID,),
    )


def _insert_run(cursor, run_id):
    cursor.execute(
        "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, TENANT_ID, "COMPLETED", "PAPER", now_iso()),
    )


def test_trade_plan_has_required_fields(test_db):
    """trade_plan artifact must contain strategy, selected_asset, metric, window, constraints."""
    run_id = new_id("run_")
    trade_plan = {
        "strategy": "user_direct",
        "metric": "n/a",
        "window": {"label": "spot", "hours": None},
        "selected_asset": "BTC-USD",
        "rationale": "User-directed trade",
        "constraints": {
            "mode": "PAPER",
            "slippage_guard_bps": None,
            "time_in_force": "GTC",
        },
        "computed_at": now_iso(),
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        _ensure_tenant(cursor)
        _insert_run(cursor, run_id)
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
               VALUES (?, 'plan', 'trade_plan', ?, ?)""",
            (run_id, json.dumps(trade_plan), now_iso()),
        )
        conn.commit()

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'trade_plan'",
            (run_id,),
        )
        row = cursor.fetchone()

    assert row is not None, "trade_plan artifact not found"
    data = json.loads(row["artifact_json"])
    assert "strategy" in data, "Missing 'strategy' key"
    assert "selected_asset" in data, "Missing 'selected_asset' key"
    assert "metric" in data, "Missing 'metric' key"
    assert "window" in data, "Missing 'window' key"
    assert "constraints" in data, "Missing 'constraints' key"
    assert data["strategy"] == "user_direct"
    assert data["selected_asset"] == "BTC-USD"


def test_portfolio_snapshots_ge_two_for_paper_run(test_db):
    """Chart invariant: portfolio_snapshots count must be >= 2 for a line chart to render."""
    run_id = new_id("run_")

    with get_conn() as conn:
        cursor = conn.cursor()
        _ensure_tenant(cursor)
        _insert_run(cursor, run_id)
        # Insert 2 snapshots (pre-trade and post-trade)
        for i in range(2):
            cursor.execute(
                """INSERT INTO portfolio_snapshots
                   (snapshot_id, run_id, tenant_id, balances_json, positions_json, total_value_usd, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id("snap_"),
                    run_id,
                    TENANT_ID,
                    "{}",
                    "{}",
                    10000.0 + i * 100,
                    now_iso(),
                ),
            )
        conn.commit()

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM portfolio_snapshots WHERE run_id = ?",
            (run_id,),
        )
        row = cursor.fetchone()

    assert row["cnt"] >= 2, f"Expected >= 2 portfolio snapshots, got {row['cnt']}"


def test_trade_receipt_has_venue(test_db):
    """trade_receipt artifact must contain a venue object with a name field."""
    run_id = new_id("run_")
    receipt = {
        "run_id": run_id,
        "execution_mode": "PAPER",
        "asset_class": "crypto",
        "orders": [],
        "fills": [],
        "total_orders": 0,
        "total_fills": 0,
        "venue": {
            "name": "Paper (simulated)",
            "execution_mode": "PAPER",
            "order_type": "market",
        },
        "submitted_at": now_iso(),
        "created_at": now_iso(),
    }

    with get_conn() as conn:
        cursor = conn.cursor()
        _ensure_tenant(cursor)
        _insert_run(cursor, run_id)
        cursor.execute(
            """INSERT INTO run_artifacts (run_id, step_name, artifact_type, artifact_json, created_at)
               VALUES (?, 'execution', 'trade_receipt', ?, ?)""",
            (run_id, json.dumps(receipt), now_iso()),
        )
        conn.commit()

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artifact_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'trade_receipt'",
            (run_id,),
        )
        row = cursor.fetchone()

    assert row is not None, "trade_receipt artifact not found"
    data = json.loads(row["artifact_json"])
    assert "venue" in data, "Missing 'venue' key in trade_receipt"
    assert data["venue"].get("name"), "venue.name must be non-empty"
    assert data["venue"]["name"] == "Paper (simulated)"
