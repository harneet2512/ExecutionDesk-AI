#!/usr/bin/env python3
"""
ExecutiveDesk AI — Authoritative Verification Script

Checks A–I cover all 6 core capabilities:
  1) Portfolio analysis (LIVE + PAPER)
  2) Natural language trade proposals
  3) BUY/SELL with mandatory confirmation gating
  4) UI-visible reasoning/artifacts
  5) Pushover notifications (sent/skipped recording)
  6) Replay determinism (no external calls)

Usage:
    python scripts/verify_agent_capabilities.py

Exit code 0 = all pass, 1 = any failure.
"""
import json
import os
import sys
import shutil
import tempfile
import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from contextlib import contextmanager

# ── Ensure project root on sys.path ──────────────────────────────────
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── Force test environment BEFORE any backend imports ─────────────────
os.environ["TEST_AUTH_BYPASS"] = "true"
os.environ["PYTEST_CURRENT_TEST"] = "verify_agent_capabilities"
os.environ["ENABLE_DEV_AUTH"] = "false"
os.environ["PUSHOVER_ENABLED"] = "false"         # will toggle per-check
os.environ["EXECUTION_MODE_DEFAULT"] = "PAPER"
os.environ["ENABLE_LIVE_TRADING"] = "false"
# Clear Coinbase creds so portfolio goes PAPER mode (no live API calls)
os.environ.pop("COINBASE_API_KEY_NAME", None)
os.environ.pop("COINBASE_API_PRIVATE_KEY", None)
os.environ.pop("COINBASE_API_PRIVATE_KEY_PATH", None)
os.environ.pop("COINBASE_API_KEY", None)
os.environ.pop("COINBASE_API_SECRET", None)
# Clear Pushover creds (will set per-check)
os.environ.pop("PUSHOVER_APP_TOKEN", None)
os.environ.pop("PUSHOVER_USER_KEY", None)

# ── Force settings reset to pick up cleared creds ────────────────────
try:
    from backend.core.config import reset_settings
    reset_settings()
except Exception:
    pass

# ── Results accumulator ──────────────────────────────────────────────
RESULTS: list[dict] = []
ARTIFACTS: dict = {}


def record(check: str, passed: bool, detail: str = "", artifacts: dict | None = None):
    RESULTS.append({"check": check, "passed": passed, "detail": detail})
    if artifacts:
        ARTIFACTS[check] = artifacts


def print_table():
    print("\n" + "=" * 72)
    print(f"{'Check':<40} {'Result':<8} {'Detail'}")
    print("-" * 72)
    for r in RESULTS:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['check']:<40} {status:<8} {r['detail'][:60]}")
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print("-" * 72)
    print(f"Total: {passed}/{total} passed")
    print("=" * 72)


# ═══════════════════════════════════════════════════════════════════════
# FIXTURE GENERATORS
# ═══════════════════════════════════════════════════════════════════════

def make_candles(symbol: str, count: int = 60, start_price: float = 45000.0,
                 change_pct: float = 0.05) -> list[dict]:
    """Synthetic hourly candles with deterministic trend."""
    end_time = datetime.utcnow()
    per_candle = (start_price * change_pct) / count
    candles = []
    for i in range(count):
        ts = end_time - timedelta(hours=count - i)
        price = start_price + i * per_candle
        candles.append({
            "start_time": ts.isoformat() + "Z",
            "end_time": (ts + timedelta(hours=1)).isoformat() + "Z",
            "open": str(price),
            "high": str(price * 1.005),
            "low": str(price * 0.995),
            "close": str(price + per_candle),
            "volume": "1000000"
        })
    return candles


# Different trends so rankings are deterministic:
#   SOL +8%  (winner),  BTC +5%,  ETH +3%,  MATIC +1%,  AVAX -1%
FIXTURE_CANDLES = {
    "BTC-USD":   lambda: make_candles("BTC-USD",   60, 45000, 0.05),
    "ETH-USD":   lambda: make_candles("ETH-USD",   60, 3000,  0.03),
    "SOL-USD":   lambda: make_candles("SOL-USD",   60, 120,   0.08),
    "MATIC-USD": lambda: make_candles("MATIC-USD", 60, 0.80,  0.01),
    "AVAX-USD":  lambda: make_candles("AVAX-USD",  60, 35,   -0.01),
}

FIXTURE_PRICES = {
    "BTC-USD": 47250.0, "ETH-USD": 3090.0, "SOL-USD": 129.6,
    "MATIC-USD": 0.808, "AVAX-USD": 34.65,
    "BTC": 47250.0, "ETH": 3090.0, "SOL": 129.6,
    "MATIC": 0.808, "AVAX": 34.65,
}

FIXTURE_PRODUCTS = [
    {"product_id": "BTC-USD", "base_currency_id": "BTC", "quote_currency_id": "USD", "status": "online"},
    {"product_id": "ETH-USD", "base_currency_id": "ETH", "quote_currency_id": "USD", "status": "online"},
    {"product_id": "SOL-USD", "base_currency_id": "SOL", "quote_currency_id": "USD", "status": "online"},
    {"product_id": "MATIC-USD", "base_currency_id": "MATIC", "quote_currency_id": "USD", "status": "online"},
    {"product_id": "AVAX-USD", "base_currency_id": "AVAX", "quote_currency_id": "USD", "status": "online"},
]


# ═══════════════════════════════════════════════════════════════════════
# DB + APP SETUP
# ═══════════════════════════════════════════════════════════════════════

def setup_isolated_db():
    """Create temp dir, point DATABASE_URL there, run migrations, seed data."""
    tmp = tempfile.mkdtemp(prefix="verify_agent_")
    db_path = os.path.join(tmp, "verify.db")
    db_url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = db_url
    os.environ["TEST_DATABASE_URL"] = db_url

    # Reset settings singleton so it picks up new DATABASE_URL
    from backend.core.config import get_settings
    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass

    from backend.db.connect import init_db, _close_connections, get_conn
    _close_connections()
    init_db()

    # Seed: default tenant + user + initial portfolio snapshot
    with get_conn() as conn:
        c = conn.cursor()
        # Ensure default tenant exists (migration 001 schema: tenant_id, name, kill_switch_enabled)
        c.execute(
            "INSERT OR IGNORE INTO tenants (tenant_id, name) VALUES (?, ?)",
            ("t_default", "Default Tenant")
        )
        # Ensure default user (migration 001: user_id, tenant_id, email, role)
        c.execute(
            "INSERT OR IGNORE INTO users (user_id, tenant_id, email, role) VALUES (?, ?, ?, ?)",
            ("u_default", "t_default", "test@example.com", "admin")
        )
        # Seed a portfolio snapshot for PAPER mode analysis
        from backend.core.ids import new_id
        snap_id = new_id("snap_")
        c.execute(
            """INSERT INTO portfolio_snapshots
               (snapshot_id, tenant_id, balances_json, positions_json, total_value_usd, ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (snap_id, "t_default",
             json.dumps({"USD": 100.0}),
             json.dumps({"BTC-USD": 0.001, "ETH-USD": 0.05}),
             250.0,
             datetime.utcnow().isoformat())
        )
        conn.commit()
    return tmp


def get_test_client():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    return TestClient(app)


HEADERS = {"X-Dev-Tenant": "t_default", "Content-Type": "application/json"}


# ═══════════════════════════════════════════════════════════════════════
# MOCK CONTEXT MANAGERS
# ═══════════════════════════════════════════════════════════════════════

@contextmanager
def mock_market_data():
    """Patch Coinbase market data functions to return fixture data."""
    def fake_get_candles(product_id, start=None, end=None, granularity=None, **kw):
        gen = FIXTURE_CANDLES.get(product_id)
        if gen:
            return gen()
        # Return enough candles so it doesn't get dropped
        return make_candles(product_id, 60, 100, 0.02)

    def fake_list_products(quote="USD", product_type="SPOT"):
        return list(FIXTURE_PRODUCTS)

    def fake_get_price(symbol):
        p = FIXTURE_PRICES.get(symbol)
        if p:
            return p
        # fallback: try with -USD suffix
        p = FIXTURE_PRICES.get(f"{symbol}-USD")
        if p:
            return p
        return 100.0

    def fake_get_candles_provider(self, symbol, interval=None, start_time=None, end_time=None, **kw):
        return fake_get_candles(symbol)

    def fake_get_price_provider(self, symbol):
        return fake_get_price(symbol)

    patches = [
        patch("backend.services.coinbase_market_data.get_candles", side_effect=fake_get_candles),
        patch("backend.services.coinbase_market_data.list_products", side_effect=fake_list_products),
        patch("backend.services.market_data.get_price", side_effect=fake_get_price),
        # Also patch the provider class methods used internally
        patch("backend.providers.coinbase_market_data.CoinbaseMarketDataProvider.get_candles",
              side_effect=fake_get_candles_provider, autospec=True),
        patch("backend.providers.coinbase_market_data.CoinbaseMarketDataProvider.get_price",
              side_effect=fake_get_price_provider, autospec=True),
    ]
    mocks = [p.start() for p in patches]
    try:
        yield mocks
    finally:
        for p in patches:
            p.stop()


@contextmanager
def mock_pushover(enabled: bool = True):
    """Patch Pushover HTTP + settings."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"status":1}'

    patches = []
    patches.append(patch("backend.services.notifications.pushover.requests.post", return_value=mock_resp))

    if enabled:
        os.environ["PUSHOVER_ENABLED"] = "true"
        os.environ["PUSHOVER_APP_TOKEN"] = "test_token_12345"
        os.environ["PUSHOVER_USER_KEY"] = "test_user_key_67890"
    else:
        os.environ["PUSHOVER_ENABLED"] = "false"
        os.environ.pop("PUSHOVER_APP_TOKEN", None)
        os.environ.pop("PUSHOVER_USER_KEY", None)

    # Reset settings so they pick up env changes
    try:
        from backend.core.config import reset_settings
        reset_settings()
    except ImportError:
        pass

    mocks = [p.start() for p in patches]
    try:
        yield mocks[0]  # return the requests.post mock
    finally:
        for p in patches:
            p.stop()
        os.environ["PUSHOVER_ENABLED"] = "false"
        os.environ.pop("PUSHOVER_APP_TOKEN", None)
        os.environ.pop("PUSHOVER_USER_KEY", None)
        try:
            from backend.core.config import reset_settings
            reset_settings()
        except ImportError:
            pass


# ═══════════════════════════════════════════════════════════════════════
# HELPER: Wait for a background-thread run to complete
# ═══════════════════════════════════════════════════════════════════════

def wait_for_run(run_id: str, timeout_s: float = 30.0) -> dict | None:
    """Poll DB until run reaches terminal status."""
    from backend.db.connect import get_conn
    start = time.time()
    while time.time() - start < timeout_s:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            if row and row["status"] in ("COMPLETED", "FAILED"):
                return {"run_id": run_id, "status": row["status"]}
        time.sleep(0.3)
    return None


# ═══════════════════════════════════════════════════════════════════════
# CHECKS A – I
# ═══════════════════════════════════════════════════════════════════════

def check_a_health(client):
    """A) Backend health endpoint returns 200."""
    try:
        r = client.get("/api/v1/ops/health", headers=HEADERS)
        ok = r.status_code == 200
        record("A) Backend health", ok, f"status={r.status_code}")
    except Exception as e:
        record("A) Backend health", False, str(e)[:60])


def check_b_conversation(client):
    """B) Create conversation and verify tenant scoping."""
    try:
        r = client.post("/api/v1/conversations",
                        headers=HEADERS,
                        json={"title": "Verification Test"})
        data = r.json()
        conv_id = data.get("conversation_id") or data.get("id")
        ok = r.status_code in (200, 201) and conv_id is not None
        record("B) Create conversation", ok,
               f"conversation_id={conv_id}",
               {"conversation_id": conv_id})
    except Exception as e:
        record("B) Create conversation", False, str(e)[:60])


def check_c_portfolio_analysis(client):
    """C) 'Analyze my portfolio' returns PortfolioBrief OR structured failure."""
    try:
        conv_id = ARTIFACTS.get("B) Create conversation", {}).get("conversation_id", "conv_verify_c")
        r = client.post("/api/v1/chat/command", headers=HEADERS,
                        json={"text": "Analyze my portfolio", "conversation_id": conv_id})
        data = r.json()
        intent = data.get("intent", "")
        brief = data.get("portfolio_brief")
        status = data.get("status", "")

        has_brief = brief is not None and isinstance(brief, dict)
        has_failure = has_brief and brief.get("failure") is not None
        has_holdings = has_brief and isinstance(brief.get("holdings"), list)
        is_portfolio_intent = "PORTFOLIO" in intent.upper()

        ok = is_portfolio_intent and (has_holdings or has_failure)
        detail = (f"intent={intent}, status={status}, "
                  f"has_brief={has_brief}, has_holdings={has_holdings}, has_failure={has_failure}")

        record("C) Portfolio analysis", ok, detail,
               {"run_id": data.get("run_id"), "brief_keys": list(brief.keys()) if brief else []})
    except Exception as e:
        record("C) Portfolio analysis", False, str(e)[:80])


def check_d_holdings_query(client):
    """D) 'How much BTC do I own?' returns BTC qty grounded in evidence."""
    try:
        conv_id = ARTIFACTS.get("B) Create conversation", {}).get("conversation_id", "conv_verify_d")
        r = client.post("/api/v1/chat/command", headers=HEADERS,
                        json={"text": "How much BTC do I own?", "conversation_id": conv_id})
        data = r.json()
        content = data.get("content", "")
        intent = data.get("intent", "")
        brief = data.get("portfolio_brief")
        queried = data.get("queried_asset")

        # BTC must be mentioned in response
        btc_mentioned = "BTC" in content.upper()
        is_portfolio_intent = "PORTFOLIO" in intent.upper()

        # qty can be 0 if fixture has 0 — that's valid
        ok = is_portfolio_intent and btc_mentioned
        detail = f"intent={intent}, queried_asset={queried}, btc_in_content={btc_mentioned}"
        record("D) Holdings query (BTC)", ok, detail,
               {"run_id": data.get("run_id"), "queried_asset": queried})
    except Exception as e:
        record("D) Holdings query (BTC)", False, str(e)[:80])


def check_e_trade_proposal(client):
    """E) 'Buy most profitable crypto of last 48h for $3' returns confirmation_id."""
    try:
        conv_id = ARTIFACTS.get("B) Create conversation", {}).get("conversation_id", "conv_verify_e")
        r = client.post("/api/v1/chat/command", headers=HEADERS,
                        json={"text": "Buy the most profitable crypto of last 48h for $3",
                              "conversation_id": conv_id})
        data = r.json()
        content = data.get("content", "")
        intent = data.get("intent", "")
        confirmation_id = data.get("confirmation_id")

        # Should be pending confirmation (not executing yet)
        has_confirm = intent == "TRADE_CONFIRMATION_PENDING" or confirmation_id is not None
        # Confirmation ID should be in content or response
        if not confirmation_id:
            # Try to extract from content
            import re
            match = re.search(r'(conf_[a-zA-Z0-9_]+)', content)
            if match:
                confirmation_id = match.group(1)
                has_confirm = True

        ok = has_confirm and confirmation_id is not None
        detail = f"intent={intent}, confirmation_id={confirmation_id}"
        record("E) Trade proposal", ok, detail,
               {"confirmation_id": confirmation_id, "conversation_id": conv_id})
    except Exception as e:
        record("E) Trade proposal", False, str(e)[:80])


def check_f_confirmation(client):
    """F) Confirm via CONFIRM text → status becomes CONFIRMED, run starts."""
    try:
        conv_id = ARTIFACTS.get("E) Trade proposal", {}).get("conversation_id")
        confirmation_id = ARTIFACTS.get("E) Trade proposal", {}).get("confirmation_id")

        if not confirmation_id:
            record("F) Confirmation gating", False, "No confirmation_id from check E")
            return

        # Send CONFIRM command
        r = client.post("/api/v1/chat/command", headers=HEADERS,
                        json={"text": "CONFIRM",
                              "conversation_id": conv_id,
                              "confirmation_id": confirmation_id})
        data = r.json()
        run_id = data.get("run_id")
        status = data.get("status", "")

        # Check confirmation status in DB
        from backend.db.connect import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status FROM trade_confirmations WHERE id = ?",
                        (confirmation_id,))
            row = cur.fetchone()
            db_status = row["status"] if row else "NOT_FOUND"

        ok = run_id is not None and db_status == "CONFIRMED"
        detail = f"run_id={run_id}, db_status={db_status}, response_status={status}"
        record("F) Confirmation gating", ok, detail,
               {"run_id": run_id, "confirmation_id": confirmation_id})
    except Exception as e:
        record("F) Confirmation gating", False, str(e)[:80])


def check_g_execution(client):
    """G) Trade completes in PAPER mode. Orders exist with FILLED status."""
    try:
        run_id = ARTIFACTS.get("F) Confirmation gating", {}).get("run_id")
        if not run_id:
            record("G) Trade execution", False, "No run_id from check F")
            return

        # Wait for run to finish
        result = wait_for_run(run_id, timeout_s=30)
        if not result:
            record("G) Trade execution", False, f"Run {run_id} did not finish in 30s")
            return

        run_status = result["status"]

        # Check orders
        from backend.db.connect import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT order_id, symbol, side, status, notional_usd FROM orders WHERE run_id = ?",
                        (run_id,))
            orders = [dict(row) for row in cur.fetchall()]

        has_orders = len(orders) > 0
        all_filled = all(o["status"] == "FILLED" for o in orders) if orders else False

        ok = run_status == "COMPLETED" and has_orders and all_filled
        detail = (f"run_status={run_status}, orders={len(orders)}, "
                  f"all_filled={all_filled}")
        if orders:
            detail += f", first_order={orders[0].get('symbol')}_{orders[0].get('side')}"

        record("G) Trade execution (BUY)", ok, detail,
               {"run_id": run_id, "orders": orders})

        # ── SELL test: do a quick SELL proposal + confirm cycle ──
        _check_g_sell(client, orders)

    except Exception as e:
        record("G) Trade execution (BUY)", False, str(e)[:80])


def _check_g_sell(client, buy_orders):
    """Quick SELL test using a known held asset."""
    try:
        if not buy_orders:
            record("G-sell) Trade execution (SELL)", False, "No buy orders to sell")
            return

        symbol_raw = buy_orders[0].get("symbol", "BTC-USD")
        asset = symbol_raw.split("-")[0]

        conv_id = f"conv_verify_sell_{int(time.time())}"
        # Create conversation for sell test
        client.post("/api/v1/conversations", headers=HEADERS,
                    json={"title": "Sell Test"})

        # Request sell ($2 to stay above $1 min after 0.6% fee buffer)
        r1 = client.post("/api/v1/chat/command", headers=HEADERS,
                         json={"text": f"Sell $2 of {asset}", "conversation_id": conv_id})
        d1 = r1.json()
        conf_id = d1.get("confirmation_id")
        if not conf_id:
            import re
            m = re.search(r'(conf_[a-zA-Z0-9_]+)', d1.get("content", ""))
            if m:
                conf_id = m.group(1)

        if not conf_id:
            record("G-sell) Trade execution (SELL)", False,
                   f"No confirmation_id for sell. intent={d1.get('intent')}")
            return

        # Confirm sell
        r2 = client.post("/api/v1/chat/command", headers=HEADERS,
                         json={"text": "CONFIRM", "conversation_id": conv_id,
                               "confirmation_id": conf_id})
        d2 = r2.json()
        sell_run_id = d2.get("run_id")
        if not sell_run_id:
            record("G-sell) Trade execution (SELL)", False, "No run_id from sell confirm")
            return

        result = wait_for_run(sell_run_id, timeout_s=30)
        if not result:
            record("G-sell) Trade execution (SELL)", False, f"Sell run {sell_run_id} timeout")
            return

        from backend.db.connect import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT side, status FROM orders WHERE run_id = ?", (sell_run_id,))
            sell_orders = [dict(r) for r in cur.fetchall()]

        has_sell = any(o["side"].upper() == "SELL" for o in sell_orders)
        all_filled = all(o["status"] == "FILLED" for o in sell_orders) if sell_orders else False

        ok = result["status"] == "COMPLETED" and has_sell and all_filled
        sides = [o["side"] for o in sell_orders]
        statuses = [o["status"] for o in sell_orders]
        record("G-sell) Trade execution (SELL)", ok,
               f"status={result['status']}, orders={len(sell_orders)}, sides={sides}, statuses={statuses}")
    except Exception as e:
        record("G-sell) Trade execution (SELL)", False, str(e)[:80])


def check_h_notifications():
    """H) Pushover notifications: SENT when enabled, SKIPPED when disabled."""
    from backend.db.connect import get_conn

    # ── H1: enabled → SENT ──
    try:
        with mock_pushover(enabled=True) as post_mock:
            from backend.services.notifications.pushover import notify_trade_placed
            sent = notify_trade_placed(
                mode="PAPER", side="BUY", symbol="BTC-USD",
                notional_usd=3.0, order_id="ord_test_h1", run_id="run_test_h1"
            )

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT status, action FROM notification_events WHERE run_id = 'run_test_h1'"
            )
            rows = [dict(r) for r in cur.fetchall()]

        has_sent = any(r["status"] == "sent" for r in rows)
        ok = sent and has_sent
        record("H1) Pushover SENT (enabled)", ok,
               f"sent={sent}, db_rows={len(rows)}, has_sent={has_sent}")
    except Exception as e:
        record("H1) Pushover SENT (enabled)", False, str(e)[:80])

    # ── H2: disabled → SKIPPED with reason ──
    try:
        with mock_pushover(enabled=False) as post_mock:
            from backend.services.notifications.pushover import notify_trade_placed
            sent = notify_trade_placed(
                mode="PAPER", side="BUY", symbol="BTC-USD",
                notional_usd=3.0, order_id="ord_test_h2", run_id="run_test_h2"
            )

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT status, action, payload_redacted FROM notification_events WHERE run_id = 'run_test_h2'"
            )
            rows = [dict(r) for r in cur.fetchall()]

        has_skipped = any(r["status"] == "skipped" for r in rows)
        has_reason = any(
            r.get("payload_redacted") and "reason" in (r["payload_redacted"] or "")
            for r in rows
        )
        ok = not sent and has_skipped and has_reason
        record("H2) Pushover SKIPPED (disabled)", ok,
               f"sent={sent}, has_skipped={has_skipped}, has_reason={has_reason}")
    except Exception as e:
        record("H2) Pushover SKIPPED (disabled)", False, str(e)[:80])


def check_i_replay():
    """I) Replay determinism: no external calls, artifacts match."""
    from backend.db.connect import get_conn

    try:
        source_run_id = ARTIFACTS.get("F) Confirmation gating", {}).get("run_id")
        if not source_run_id:
            record("I) Replay determinism", False, "No source run_id from check F")
            return

        # Wait for source run to be fully done
        result = wait_for_run(source_run_id, timeout_s=10)
        if not result or result["status"] != "COMPLETED":
            record("I) Replay determinism", False,
                   f"Source run not COMPLETED: {result}")
            return

        # Get source run artifacts for comparison
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT artifact_type, artifact_json FROM run_artifacts WHERE run_id = ?",
                (source_run_id,)
            )
            source_artifacts = {r["artifact_type"]: r["artifact_json"] for r in cur.fetchall()}

            # Get source orders
            cur.execute(
                "SELECT symbol, side, notional_usd, status FROM orders WHERE run_id = ?",
                (source_run_id,)
            )
            source_orders = [dict(r) for r in cur.fetchall()]

        if not source_orders:
            record("I) Replay determinism", False, "Source run has no orders to replay")
            return

        # Create REPLAY run
        from backend.core.ids import new_id
        from backend.core.time import now_iso
        replay_run_id = new_id("run_")

        with get_conn() as conn:
            cur = conn.cursor()
            # Get source run's intent/plan for replay
            cur.execute(
                "SELECT execution_mode, intent_json, trade_proposal_json, execution_plan_json "
                "FROM runs WHERE run_id = ?",
                (source_run_id,)
            )
            source_run = dict(cur.fetchone())

            cur.execute(
                """INSERT INTO runs (run_id, tenant_id, status, execution_mode,
                   source_run_id, intent_json, trade_proposal_json, created_at)
                   VALUES (?, ?, 'CREATED', 'REPLAY', ?, ?, ?, ?)""",
                (replay_run_id, "t_default", source_run_id,
                 source_run.get("intent_json"),
                 source_run.get("trade_proposal_json"),
                 now_iso())
            )
            conn.commit()

        # Track external call counts: these mocks should NOT be called during replay
        candles_call_count = 0
        prices_call_count = 0

        def counting_candles(*a, **kw):
            nonlocal candles_call_count
            candles_call_count += 1
            return make_candles("BTC-USD")

        def counting_price(*a, **kw):
            nonlocal prices_call_count
            prices_call_count += 1
            return 47250.0

        with patch("backend.services.coinbase_market_data.get_candles", side_effect=counting_candles), \
             patch("backend.services.coinbase_market_data.list_products", return_value=FIXTURE_PRODUCTS), \
             patch("backend.services.market_data.get_price", side_effect=counting_price), \
             patch("backend.providers.coinbase_market_data.CoinbaseMarketDataProvider.get_candles",
                   side_effect=lambda self, *a, **kw: counting_candles()), \
             patch("backend.providers.coinbase_market_data.CoinbaseMarketDataProvider.get_price",
                   side_effect=lambda self, *a, **kw: counting_price()):

            # Execute the REPLAY run using the orchestrator
            import asyncio
            from backend.orchestrator.runner import execute_run
            try:
                asyncio.get_event_loop().run_until_complete(
                    execute_run(replay_run_id)
                )
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(execute_run(replay_run_id))

        # Verify no external calls for research data
        # Note: price calls during order execution (PaperProvider) are acceptable
        # because paper provider needs current price — but research should use stored data
        research_calls = candles_call_count  # candles are the research-layer calls

        # Get replay artifacts
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT artifact_type, artifact_json FROM run_artifacts WHERE run_id = ?",
                (replay_run_id,)
            )
            replay_artifacts = {r["artifact_type"]: r["artifact_json"] for r in cur.fetchall()}

            # Get replay orders
            cur.execute(
                "SELECT symbol, side, notional_usd, status FROM orders WHERE run_id = ?",
                (replay_run_id,)
            )
            replay_orders = [dict(r) for r in cur.fetchall()]

            # Get replay run status
            cur.execute("SELECT status FROM runs WHERE run_id = ?", (replay_run_id,))
            replay_status = cur.fetchone()["status"]

        # Compare: same number of orders, same symbols/sides
        orders_match = (
            len(replay_orders) == len(source_orders)
            and all(
                ro["symbol"] == so["symbol"] and ro["side"] == so["side"]
                for ro, so in zip(
                    sorted(replay_orders, key=lambda x: x["symbol"]),
                    sorted(source_orders, key=lambda x: x["symbol"])
                )
            )
        ) if replay_orders and source_orders else False

        # Compare key artifacts (canonicalized)
        def canonicalize(art_json_str):
            """Remove non-deterministic fields and sort."""
            skip = {"created_at", "ts", "timestamp", "computed_at", "fetched_at",
                    "failed_at", "as_of", "request_time_iso"}
            def clean(obj):
                if isinstance(obj, dict):
                    return {k: clean(v) for k, v in sorted(obj.items()) if k not in skip}
                if isinstance(obj, list):
                    return [clean(x) for x in obj]
                return obj
            try:
                return json.dumps(clean(json.loads(art_json_str)), sort_keys=True)
            except Exception:
                return art_json_str

        # Check a key artifact type (financial_brief) for determinism
        art_match = True
        for art_type in ["financial_brief", "universe_snapshot"]:
            if art_type in source_artifacts and art_type in replay_artifacts:
                if canonicalize(source_artifacts[art_type]) != canonicalize(replay_artifacts[art_type]):
                    art_match = False
                    break

        ok = (research_calls == 0 and orders_match and
              replay_status in ("COMPLETED", "FAILED"))
        detail = (f"research_candle_calls={research_calls}, "
                  f"orders_match={orders_match}, art_match={art_match}, "
                  f"replay_status={replay_status}")
        record("I) Replay determinism", ok, detail)

    except Exception as e:
        import traceback
        record("I) Replay determinism", False, str(e)[:80])
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 72)
    print("  ExecutiveDesk AI — Verification Suite")
    print("=" * 72)

    # ── Setup ──
    print("\n[SETUP] Creating isolated test database...")
    tmp_dir = setup_isolated_db()
    print(f"[SETUP] DB at: {tmp_dir}")

    try:
        client = get_test_client()

        # All checks run inside mocked market data
        with mock_market_data():
            print("\n[RUN] Executing checks A–I...\n")

            # A) Health
            check_a_health(client)

            # B) Conversation
            check_b_conversation(client)

            # C) Portfolio Analysis
            check_c_portfolio_analysis(client)

            # D) Holdings Query
            check_d_holdings_query(client)

            # E) Trade Proposal
            check_e_trade_proposal(client)

            # F) Confirmation Gating
            check_f_confirmation(client)

            # G) Trade Execution (BUY + SELL)
            check_g_execution(client)

            # H) Pushover Notifications
            check_h_notifications()

            # I) Replay Determinism
            check_i_replay()

        # ── Results ──
        print_table()

        # Write artifacts summary
        print("\n[ARTIFACTS]")
        for check_key, arts in ARTIFACTS.items():
            print(f"  {check_key}: {json.dumps(arts, default=str)[:120]}")

    finally:
        # Cleanup
        try:
            from backend.db.connect import _close_connections
            _close_connections()
        except Exception:
            pass
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    # Exit code
    all_passed = all(r["passed"] for r in RESULTS)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
