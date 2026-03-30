"""E2E-style regressions for status messaging and enterprise sell handling."""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.ids import new_id
from backend.core.time import now_iso
from backend.db.connect import get_conn
from backend.services.executable_state import ExecutableBalance, ExecutableState

client = TestClient(app)


def _seed_conversation(conversation_id: str = "conv_e2e") -> str:
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO conversations (conversation_id, tenant_id, title) VALUES (?, ?, ?)",
            (conversation_id, "t_default", "E2E Conversation"),
        )
        conn.commit()
    return conversation_id


def _tiny_btc_state() -> ExecutableState:
    return ExecutableState(
        balances={
            "BTC": ExecutableBalance(
                currency="BTC",
                available_qty=0.0001,  # ~$2.28 when price mocked to 22,800
                hold_qty=0.0,
                account_uuid="acc_btc",
                updated_at=now_iso(),
            )
        },
        fetched_at=now_iso(),
        source="test",
    )


def _seed_portfolio_snapshot(
    *,
    tenant_id: str = "t_default",
    positions_json: str = '{"BTC": 0.0001}',
    balances_json: str = '{"USD": 100.0}',
    total_value_usd: float = 102.28,
) -> None:
    with get_conn() as conn:
        cursor = conn.cursor()
        run_id = new_id("run_")
        cursor.execute(
            "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, tenant_id, "COMPLETED", "PAPER", now_iso()),
        )
        cursor.execute(
            """INSERT INTO portfolio_snapshots
               (snapshot_id, tenant_id, run_id, ts, total_value_usd, positions_json, balances_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id("snap_"),
                tenant_id,
                run_id,
                now_iso(),
                total_value_usd,
                positions_json,
                balances_json,
            ),
        )
        conn.commit()


@pytest.fixture
def allow_live_preconfirm(monkeypatch):
    """Allow pre-confirm trade staging in tests (without enabling live execution)."""
    monkeypatch.setenv("TRADING_DISABLE_LIVE", "false")
    from backend.core.config import reset_settings
    reset_settings()
    yield
    monkeypatch.setenv("TRADING_DISABLE_LIVE", "true")
    reset_settings()


def test_sell_more_than_holdings_offers_sell_max(test_db, monkeypatch, allow_live_preconfirm):
    """Sell request larger than holdings should offer enterprise sell-max adjustment."""
    conversation_id = _seed_conversation("conv_sell_max")
    _seed_portfolio_snapshot()

    monkeypatch.setattr("backend.api.routes.chat._fetch_executable_state", lambda _tenant: _tiny_btc_state())
    monkeypatch.setattr(
        "backend.api.routes.chat._build_product_catalog",
        lambda _symbols: {"BTC-USD": {"is_disabled": False, "trading_disabled": False, "limit_only": False, "cancel_only": False}},
    )
    async def _min_notional(_asset: str) -> float:
        return 1.0

    monkeypatch.setattr("backend.services.trade_preflight.get_min_notional_for_asset", _min_notional)
    monkeypatch.setattr("backend.services.market_data.get_price", lambda _sym: 22800.0)
    async def _preview_ok(**_kwargs):
        return True, True, "ok", None
    monkeypatch.setattr("backend.services.trade_preflight._validate_via_coinbase_preview", _preview_ok)

    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={"text": "sell $10 of BTC", "conversation_id": conversation_id},
    )
    assert response.status_code == 200
    data = response.json()

    assert data.get("intent") == "TRADE_CONFIRMATION_PENDING"
    assert data.get("confirmation_id")
    assert "CONFIRM SELL MAX" in (data.get("suggestions") or [])
    assert "CANCEL" in (data.get("suggestions") or [])

    pending_actions = ((data.get("pending_trade") or {}).get("actions") or [])
    assert pending_actions, "Expected staged actions in pending trade payload"
    # Adjusted to max executable notional (~$2.28), not original $10.
    assert float(pending_actions[0]["amount_usd"]) < 10.0


def test_sell_below_minimum_is_blocked_before_confirm(test_db, monkeypatch, allow_live_preconfirm):
    """Below-minimum sell should be rejected at preflight and never create confirmation."""
    conversation_id = _seed_conversation("conv_sell_block")
    _seed_portfolio_snapshot()

    monkeypatch.setattr("backend.api.routes.chat._fetch_executable_state", lambda _tenant: _tiny_btc_state())
    monkeypatch.setattr(
        "backend.api.routes.chat._build_product_catalog",
        lambda _symbols: {"BTC-USD": {"is_disabled": False, "trading_disabled": False, "limit_only": False, "cancel_only": False}},
    )
    async def _min_notional(_asset: str) -> float:
        return 1.0

    monkeypatch.setattr("backend.services.trade_preflight.get_min_notional_for_asset", _min_notional)
    monkeypatch.setattr("backend.services.market_data.get_price", lambda _sym: 22800.0)

    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={"text": "sell $0.25 of BTC", "conversation_id": conversation_id},
    )
    assert response.status_code == 200
    data = response.json()

    assert data.get("status") == "REJECTED"
    assert data.get("confirmation_id") is None
    assert data.get("intent") == "TRADE_EXECUTION"


def test_sell_all_dust_blocked_with_preview_guidance(test_db, monkeypatch, allow_live_preconfirm):
    """Sell-all dust should be blocked pre-confirm with explicit Coinbase minimum guidance."""
    conversation_id = _seed_conversation("conv_sell_dust_preview")
    _seed_portfolio_snapshot()

    monkeypatch.setattr("backend.api.routes.chat._fetch_executable_state", lambda _tenant: _tiny_btc_state())
    monkeypatch.setattr(
        "backend.api.routes.chat._build_product_catalog",
        lambda _symbols: {"BTC-USD": {"is_disabled": False, "trading_disabled": False, "limit_only": False, "cancel_only": False}},
    )
    monkeypatch.setattr("backend.services.market_data.get_price", lambda _sym: 22800.0)

    async def _preview_reject(**_kwargs):
        return True, False, "minimum sell size is $1.00", 1.0

    monkeypatch.setattr("backend.services.trade_preflight._validate_via_coinbase_preview", _preview_reject)

    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={"text": "sell all BTC", "conversation_id": conversation_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "REJECTED"
    assert data.get("confirmation_id") is None
    assert "below Coinbase's minimum sell size".lower() in (data.get("content") or "").lower()
    suggestions = data.get("suggestions") or []
    assert any("Cancel" in s for s in suggestions)
    assert any("Buy more BTC" in s for s in suggestions)
    assert any("convert/dust options" in s for s in suggestions)


def test_buy_two_dollars_keeps_preconfirm_news_payload(test_db, allow_live_preconfirm):
    """Regression: BUY $2 still returns pre-confirm smart-news payload."""
    conversation_id = _seed_conversation("conv_buy_news")
    _seed_portfolio_snapshot(
        positions_json='{"BTC": 0.0}',
        balances_json='{"USD": 200.0}',
        total_value_usd=200.0,
    )
    response = client.post(
        "/api/v1/chat/command",
        headers={"X-Dev-Tenant": "t_default"},
        json={"text": "buy $2 of BTC", "conversation_id": conversation_id, "news_enabled": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("intent") == "TRADE_CONFIRMATION_PENDING"
    assert data.get("preconfirm_insight") is not None


@pytest.mark.parametrize("seed_status,provider_status", [
    ("SUBMITTED", "OPEN"),
    ("OPEN", "OPEN"),
    ("PENDING", "PENDING"),
])
def test_fill_status_endpoint_never_claims_filled_for_open_order(test_db, monkeypatch, seed_status, provider_status):
    """Pending/open/submitted statuses with zero fills must never be reported as filled."""
    run_id = new_id("run_")
    order_id = new_id("ord_")
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO runs (run_id, tenant_id, status, execution_mode, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, "t_default", "COMPLETED", "LIVE", now_iso()),
        )
        cursor.execute(
            """INSERT INTO orders (
                order_id, run_id, tenant_id, provider, symbol, side, order_type,
                qty, notional_usd, status, filled_qty, avg_fill_price, total_fees, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                run_id,
                "t_default",
                "COINBASE",
                "BTC-USD",
                "BUY",
                "MARKET",
                None,
                2.0,
                seed_status,
                0.0,
                0.0,
                0.0,
                now_iso(),
            ),
        )
        conn.commit()

    class _FakeCoinbaseProvider:
        def _get_order_status(self, _order_id, run_id=None):
            return {"status": provider_status}

        def _fetch_and_store_fills(self, _order_id, _run_id, _tenant_id):
            return []

    monkeypatch.setattr("backend.providers.coinbase_provider.CoinbaseProvider", _FakeCoinbaseProvider)

    response = client.get(
        f"/api/v1/orders/{order_id}/fill-status",
        headers={"X-Dev-Tenant": "t_default"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["fill_confirmed"] is False
    assert data["status"] in {"OPEN", "SUBMITTED", "PENDING", "PENDING_FILL", "PARTIALLY_FILLED"}
    assert "order submitted" in data["message"].lower()
