"""Seed the runbooks table with 8 pre-populated operational runbooks.

Usage:
    from backend.db.seed_runbooks import seed_runbooks
    count = seed_runbooks()  # returns number of runbooks inserted
"""
import json

from backend.core.ids import new_id
from backend.core.logging import get_logger
from backend.core.time import now_iso
from backend.db.connect import get_conn

logger = get_logger(__name__)

SEED_RUNBOOKS = [
    {
        "title": "Order Rejected - Insufficient Balance",
        "slug": "order-rejected-insufficient-balance",
        "category": "order-errors",
        "error_codes": ["INSUFFICIENT_BALANCE", "BELOW_MINIMUM_SIZE"],
        "symptoms": (
            "Order is rejected by the exchange with an insufficient balance or "
            "below-minimum-size error. The order never reaches OPEN status."
        ),
        "diagnosis_steps": (
            "1. Check the wallet/portfolio balance for the quote currency (e.g. USD).\n"
            "2. Verify the order notional (price x quantity) does not exceed available balance.\n"
            "3. Check exchange minimum order size for the product (e.g. BTC-USD min ~$1).\n"
            "4. Look at recent fills that may have reduced available balance since the run started."
        ),
        "resolution": (
            "- Deposit additional funds or reduce order size.\n"
            "- If below minimum size, increase the quantity to meet exchange requirements.\n"
            "- Use the portfolio snapshot to verify balances before retrying."
        ),
        "prevention": (
            "- Pre-check available balance in the strategy node before generating a proposal.\n"
            "- Set a minimum notional threshold in policy rules.\n"
            "- Monitor portfolio value alerts for low-balance conditions."
        ),
        "severity": "medium",
    },
    {
        "title": "Order Timeout",
        "slug": "order-timeout",
        "category": "order-errors",
        "error_codes": ["ORDER_TIMEOUT", "EXECUTION_TIMEOUT"],
        "symptoms": (
            "Order is submitted but never fills within the expected time window. "
            "The run eventually fails with a timeout error."
        ),
        "diagnosis_steps": (
            "1. Check order status on the exchange (OPEN, PENDING, CANCELLED).\n"
            "2. Verify market liquidity for the product at the time of order.\n"
            "3. Check if a limit order was placed far from market price.\n"
            "4. Review network latency and API response times in telemetry."
        ),
        "resolution": (
            "- Cancel the stale order and retry with a market order.\n"
            "- Adjust limit price closer to current market price.\n"
            "- Increase the order timeout threshold in configuration."
        ),
        "prevention": (
            "- Use market orders for time-sensitive executions.\n"
            "- Set aggressive limit prices (e.g. mid-spread) for limit orders.\n"
            "- Configure shorter timeout with automatic retry logic."
        ),
        "severity": "high",
    },
    {
        "title": "Policy Block - Symbol Not Allowed",
        "slug": "policy-block-symbol-not-allowed",
        "category": "policy",
        "error_codes": ["SYMBOL_NOT_ALLOWED", "POLICY_BLOCKED"],
        "symptoms": (
            "Run is blocked at the policy_check node because the target symbol "
            "is not in the allowed-symbols list or is explicitly denied."
        ),
        "diagnosis_steps": (
            "1. Check active policy rules via GET /api/v1/policies.\n"
            "2. Verify the symbol is in the allowed_symbols list.\n"
            "3. Check if the symbol was recently added to a deny list.\n"
            "4. Review the policy_events table for the specific block reason."
        ),
        "resolution": (
            "- Add the symbol to the allowed list via the policy management API.\n"
            "- Remove the symbol from any deny lists.\n"
            "- If intentionally blocked, inform the user about the restriction."
        ),
        "prevention": (
            "- Maintain an up-to-date allowed-symbols list.\n"
            "- Review policy rules periodically.\n"
            "- Show allowed symbols in the UI before order entry."
        ),
        "severity": "medium",
    },
    {
        "title": "API Rate Limited",
        "slug": "api-rate-limited",
        "category": "system",
        "error_codes": ["RATE_LIMITED"],
        "symptoms": (
            "API calls to the exchange or market data provider return 429 Too Many Requests. "
            "Multiple runs may be failing simultaneously with rate limit errors."
        ),
        "diagnosis_steps": (
            "1. Check telemetry for 429 response codes in recent API calls.\n"
            "2. Review the rate of API requests in the last few minutes.\n"
            "3. Check if multiple concurrent runs are hitting the same provider.\n"
            "4. Verify rate limit headers (X-RateLimit-Remaining) in responses."
        ),
        "resolution": (
            "- Wait for the rate limit window to reset (usually 1-60 seconds).\n"
            "- Reduce concurrent run count.\n"
            "- Enable request queuing/throttling in the provider layer."
        ),
        "prevention": (
            "- Implement request rate limiting in the provider layer.\n"
            "- Use caching for frequently accessed market data.\n"
            "- Stagger concurrent runs to avoid burst requests."
        ),
        "severity": "high",
    },
    {
        "title": "Stale Market Data",
        "slug": "stale-market-data",
        "category": "data-quality",
        "error_codes": [],
        "symptoms": (
            "Signals and strategy nodes use outdated price data. Candle timestamps "
            "are significantly behind current time. Decisions based on stale data "
            "may lead to poor execution."
        ),
        "diagnosis_steps": (
            "1. Check the latest candle timestamp in run artifacts.\n"
            "2. Compare candle timestamps with current UTC time.\n"
            "3. Verify the market data provider is returning fresh data.\n"
            "4. Check if the product is in a trading halt or maintenance window."
        ),
        "resolution": (
            "- Force refresh market data cache.\n"
            "- Switch to an alternative market data provider.\n"
            "- Wait for the exchange maintenance window to end."
        ),
        "prevention": (
            "- Add staleness checks in the signals node (reject data older than N minutes).\n"
            "- Monitor data freshness as an eval metric.\n"
            "- Configure alerts for stale-data conditions."
        ),
        "severity": "medium",
    },
    {
        "title": "Live Trading Disabled",
        "slug": "live-trading-disabled",
        "category": "configuration",
        "error_codes": ["LIVE_DISABLED", "DEMO_SAFE_MODE"],
        "symptoms": (
            "Attempts to execute LIVE orders are blocked. The system forces PAPER mode "
            "or returns a DEMO_SAFE_MODE error. This is expected in demo environments "
            "but may be unexpected in production."
        ),
        "diagnosis_steps": (
            "1. Check ENABLE_LIVE_TRADING environment variable (should be 'true').\n"
            "2. Check DEMO_SAFE_MODE environment variable (should be '0' or 'false').\n"
            "3. Check TRADING_DISABLE_LIVE environment variable.\n"
            "4. Verify Coinbase API credentials are configured and valid."
        ),
        "resolution": (
            "- Set ENABLE_LIVE_TRADING=true in .env.\n"
            "- Set DEMO_SAFE_MODE=0 in .env.\n"
            "- Restart the backend to pick up environment changes.\n"
            "- Verify credentials via GET /api/v1/ops/coinbase/status."
        ),
        "prevention": (
            "- Document the required environment variables for live trading.\n"
            "- Add a startup health check that warns when live trading is disabled.\n"
            "- Use the /ops/capabilities endpoint to verify configuration."
        ),
        "severity": "low",
    },
    {
        "title": "Approval Stuck in Pending",
        "slug": "approval-stuck-pending",
        "category": "workflow",
        "error_codes": [],
        "symptoms": (
            "A run is waiting for human approval but no one has acted on it. "
            "The run stays in RUNNING status indefinitely with the approval node "
            "showing PENDING."
        ),
        "diagnosis_steps": (
            "1. Check the approvals table for PENDING entries.\n"
            "2. Verify the approval notification was sent (check notifications).\n"
            "3. Check if the assigned approver is available.\n"
            "4. Review the run timeline for how long it has been pending."
        ),
        "resolution": (
            "- Approve or reject the pending approval via the UI or API.\n"
            "- POST /api/v1/approvals/{approval_id} with decision=APPROVED or REJECTED.\n"
            "- If the run is no longer needed, reject and cancel."
        ),
        "prevention": (
            "- Set approval timeout thresholds.\n"
            "- Configure approval escalation for long-pending items.\n"
            "- Use auto-approve for low-risk paper trades."
        ),
        "severity": "medium",
    },
    {
        "title": "Prediction Market Not Found",
        "slug": "prediction-market-not-found",
        "category": "market-errors",
        "error_codes": [],
        "symptoms": (
            "A prediction market query returns no results or the specified market "
            "does not exist on the prediction market platform."
        ),
        "diagnosis_steps": (
            "1. Verify the market slug/ID is correct.\n"
            "2. Check if the market has been resolved or expired.\n"
            "3. Search for the market by keyword on the prediction market platform.\n"
            "4. Check if the prediction market provider API is accessible."
        ),
        "resolution": (
            "- Correct the market identifier and retry.\n"
            "- If the market is resolved, inform the user of the outcome.\n"
            "- Search for alternative markets on the same topic."
        ),
        "prevention": (
            "- Validate market existence before starting a run.\n"
            "- Cache active market lists and refresh periodically.\n"
            "- Show market status (active/resolved/expired) in the UI."
        ),
        "severity": "low",
    },
]


def seed_runbooks() -> int:
    """Insert seed runbooks into the database.

    Skips runbooks whose slug already exists (idempotent).

    Returns:
        Number of runbooks actually inserted.
    """
    inserted = 0
    now = now_iso()

    from backend.db.migration_compat import placeholder
    ph = placeholder()
    val_phs = ", ".join([ph] * 14)

    with get_conn() as conn:
        cursor = conn.cursor()

        for rb in SEED_RUNBOOKS:
            cursor.execute(f"SELECT 1 FROM runbooks WHERE slug = {ph}", (rb["slug"],))
            if cursor.fetchone():
                continue

            runbook_id = new_id("rb_")
            cursor.execute(
                f"""
                INSERT INTO runbooks
                    (runbook_id, title, slug, category, error_codes, symptoms,
                     diagnosis_steps, resolution, prevention, severity,
                     times_used, created_by, created_at, updated_at)
                VALUES ({val_phs})
                """,
                (
                    runbook_id,
                    rb["title"],
                    rb["slug"],
                    rb["category"],
                    json.dumps(rb["error_codes"]),
                    rb["symptoms"],
                    rb["diagnosis_steps"],
                    rb["resolution"],
                    rb["prevention"],
                    rb["severity"],
                    0,
                    "system",
                    now,
                    now,
                ),
            )
            inserted += 1
            logger.info("Seeded runbook: %s", rb["slug"])

    logger.info("Seed runbooks complete: %d inserted", inserted)
    return inserted
