"""Tests for oracle artifacts system."""
import json
import pytest
from backend.evals.oracle_artifacts import (
    compute_oracle_profit_ranking,
    compute_oracle_time_window,
    save_oracle_artifacts,
)
from backend.db.connect import get_conn
from backend.core.ids import new_id
from backend.core.time import now_iso


def _ensure_tenant(conn, tenant_id="test_tenant"):
    """Insert tenant if not present."""
    existing = conn.execute(
        "SELECT tenant_id FROM tenants WHERE tenant_id = ?", (tenant_id,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO tenants (tenant_id, name) VALUES (?, ?)",
            (tenant_id, "Test Tenant"),
        )
        conn.commit()


def _seed_run(conn, run_id, tenant_id="test_tenant", command="buy profitable"):
    """Insert a minimal run row."""
    _ensure_tenant(conn, tenant_id)
    conn.execute(
        """INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at, command_text)
           VALUES (?, ?, 'COMPLETED', 'PAPER', ?, ?)""",
        (run_id, tenant_id, now_iso(), command),
    )
    conn.commit()


def _seed_candles(conn, run_id, symbol, candles, window="168h"):
    """Insert a candle batch."""
    batch_id = new_id("batch_")
    conn.execute(
        """INSERT INTO market_candles_batches
           (batch_id, run_id, symbol, window, candles_json, query_params_json, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (batch_id, run_id, symbol, window, json.dumps(candles), "{}", now_iso()),
    )
    conn.commit()


def _seed_intent(conn, run_id, intent):
    """Insert an intent row."""
    intent_id = new_id("intent_")
    conn.execute(
        """INSERT INTO intents (intent_id, run_id, command, intent_json, ts)
           VALUES (?, ?, 'test', ?, ?)""",
        (intent_id, run_id, json.dumps(intent), now_iso()),
    )
    conn.commit()


def test_oracle_profit_ranking_basic(test_db):
    run_id = new_id("run_")
    with get_conn() as conn:
        _seed_run(conn, run_id)
        # BTC: 50000 -> 52000 = +4%
        _seed_candles(conn, run_id, "BTC-USD", [
            {"close": 50000, "start_time": "2026-02-06T00:00:00Z"},
            {"close": 52000, "start_time": "2026-02-13T00:00:00Z"},
        ])
        # ETH: 3000 -> 3300 = +10%
        _seed_candles(conn, run_id, "ETH-USD", [
            {"close": 3000, "start_time": "2026-02-06T00:00:00Z"},
            {"close": 3300, "start_time": "2026-02-13T00:00:00Z"},
        ])
        # SOL: 100 -> 97 = -3%
        _seed_candles(conn, run_id, "SOL-USD", [
            {"close": 100, "start_time": "2026-02-06T00:00:00Z"},
            {"close": 97, "start_time": "2026-02-13T00:00:00Z"},
        ])

    result = compute_oracle_profit_ranking(run_id)
    assert result is not None
    assert result["oracle_top_symbol"] == "ETH-USD"
    assert abs(result["oracle_top_return"] - 0.1) < 0.001
    assert len(result["rankings"]) == 3
    # Verify ordering: ETH > BTC > SOL
    symbols = [r["symbol"] for r in result["rankings"]]
    assert symbols == ["ETH-USD", "BTC-USD", "SOL-USD"]


def test_oracle_profit_ranking_no_candles(test_db):
    run_id = new_id("run_")
    with get_conn() as conn:
        _seed_run(conn, run_id)

    result = compute_oracle_profit_ranking(run_id)
    assert result is None


def test_oracle_time_window(test_db):
    run_id = new_id("run_")
    with get_conn() as conn:
        _seed_run(conn, run_id)
        _seed_intent(conn, run_id, {"window": "168h", "side": "BUY"})

    result = compute_oracle_time_window(run_id)
    assert result is not None
    assert result["lookback_hours"] == 168
    assert result["expected_start"] is not None
    assert result["expected_end"] is not None


def test_save_and_load_oracle_artifacts(test_db):
    run_id = new_id("run_")
    with get_conn() as conn:
        _seed_run(conn, run_id)

    artifacts = {
        "oracle_profit_ranking": {"oracle_top_symbol": "ETH-USD", "rankings": []},
        "oracle_time_window": {"lookback_hours": 168},
    }
    save_oracle_artifacts(run_id, artifacts)

    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT artifact_type, artifact_json FROM run_artifacts WHERE run_id = ? AND step_name = 'oracle'",
            (run_id,),
        )
        rows = cursor.fetchall()

    types = {r["artifact_type"] for r in rows}
    assert "oracle_profit_ranking" in types
    assert "oracle_time_window" in types
