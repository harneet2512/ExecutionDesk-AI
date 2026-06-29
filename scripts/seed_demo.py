#!/usr/bin/env python3
"""Seed the database with realistic demo data.

Populates tenants, runs, DAG nodes, orders, fills, evals, portfolio snapshots,
client profiles/issues, news items, and conversations so every page of the app
shows real content.

Idempotent: skips if runs already exist.

Usage:
    python -m scripts.seed_demo          # from project root
    python scripts/seed_demo.py          # direct invocation
"""

import hashlib
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so imports work when invoked directly
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.db.connect import get_conn, init_db
from backend.core.ids import new_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

random.seed(42)  # deterministic for reproducibility

NOW = datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _rand_ts(days_ago_min: int, days_ago_max: int, business_hours: bool = True) -> datetime:
    """Random timestamp between days_ago_max..days_ago_min days in the past."""
    delta_days = random.uniform(days_ago_min, days_ago_max)
    dt = NOW - timedelta(days=delta_days)
    if business_hours:
        dt = dt.replace(hour=random.randint(9, 17), minute=random.randint(0, 59),
                        second=random.randint(0, 59))
    return dt


def _uid(prefix: str) -> str:
    return new_id(prefix)


# ---------------------------------------------------------------------------
# Static data definitions
# ---------------------------------------------------------------------------

TENANTS = [
    ("t_whale", "Meridian Capital", 0),
    ("t_retail", "Alex Chen", 0),
    ("t_default", "Demo Trader", 0),
]

ASSETS = [
    {"symbol": "BTC-USD", "product_id": "BTC-USD", "price": 68000.0, "vol": 0.03},
    {"symbol": "ETH-USD", "product_id": "ETH-USD", "price": 3800.0, "vol": 0.04},
    {"symbol": "SOL-USD", "product_id": "SOL-USD", "price": 180.0, "vol": 0.06},
]

DAG_NODE_NAMES = [
    "research", "signals", "news", "risk", "strategy",
    "proposal", "policy_check", "approval", "execution", "eval",
]

EVAL_NAMES = [
    "schema_validity", "policy_compliance", "citation_coverage",
    "execution_correctness", "budget_compliance", "action_grounding",
    "intent_parse_correctness", "latency_threshold",
]

COMMANDS = [
    "Buy $200 of BTC",
    "Buy $150 of ETH",
    "Sell $100 of SOL",
    "Buy $300 of BTC-USD",
    "Buy $250 of ETH-USD",
    "Sell $80 of BTC",
    "Buy $500 of SOL",
    "Buy $100 of ETH",
    "Buy $120 of BTC",
    "Sell $200 of ETH-USD",
    "Buy $350 of BTC-USD",
    "Buy $175 of SOL-USD",
    "Sell $90 of SOL",
    "Buy $400 of BTC",
    "Buy $60 of ETH",
    "Buy $220 of SOL",
    "Sell $150 of BTC",
    "Buy $180 of ETH-USD",
    "Buy $75 of SOL-USD",
    "Buy $280 of BTC-USD",
]

NEWS_HEADLINES = [
    ("Bitcoin Surges Past $68,000 Amid Institutional Demand", "BTC-USD", 0.92, "positive"),
    ("Ethereum Layer-2 Networks See Record Transaction Volume", "ETH-USD", 0.88, "positive"),
    ("Solana DeFi TVL Hits New All-Time High of $12B", "SOL-USD", 0.95, "positive"),
    ("Federal Reserve Holds Rates Steady, Crypto Markets Rally", "BTC-USD", 0.75, "positive"),
    ("Bitcoin ETF Inflows Reach $500M in Single Day", "BTC-USD", 0.90, "positive"),
    ("Ethereum Foundation Announces Major Protocol Upgrade", "ETH-USD", 0.85, "positive"),
    ("Solana Validator Count Surpasses 3,000 Milestone", "SOL-USD", 0.80, "positive"),
    ("SEC Commissioner Signals Supportive Stance on Crypto", "BTC-USD", 0.70, "positive"),
    ("Bitcoin Mining Difficulty Reaches New Record High", "BTC-USD", 0.65, "neutral"),
    ("Ethereum Gas Fees Drop to Multi-Year Lows", "ETH-USD", 0.78, "positive"),
    ("Major Exchange Reports Record Trading Volumes", "BTC-USD", 0.72, "positive"),
    ("Solana NFT Marketplace Volume Doubles Month-over-Month", "SOL-USD", 0.82, "positive"),
    ("Bitcoin Whale Transfers $200M to Cold Storage", "BTC-USD", 0.60, "neutral"),
    ("Ethereum Staking Yields Compress as Participation Grows", "ETH-USD", 0.55, "neutral"),
    ("Crypto Market Cap Exceeds $2.5 Trillion", "BTC-USD", 0.85, "positive"),
    ("Solana Phone Reaches 100K Pre-Orders", "SOL-USD", 0.70, "positive"),
    ("Bitcoin Network Hash Rate Hits All-Time High", "BTC-USD", 0.68, "neutral"),
    ("Regulatory Uncertainty in EU Could Impact Crypto Exchanges", "ETH-USD", 0.45, "negative"),
    ("Major Bank Launches Institutional Crypto Custody Service", "BTC-USD", 0.80, "positive"),
    ("Solana Experiences Brief Network Congestion During Memecoin Rush", "SOL-USD", 0.40, "negative"),
]

CONVERSATION_SEEDS = [
    {
        "tenant": "t_whale",
        "title": "Morning BTC Analysis",
        "messages": [
            ("user", "What's the current outlook for BTC? Should I increase my position?"),
            ("assistant", "Based on current market analysis, BTC-USD is showing strong momentum at $68,200. Key indicators:\n\n- RSI at 62 (bullish, not overbought)\n- 50-day MA trending upward\n- Institutional inflows remain strong at $450M/week\n\nI'd recommend a measured increase of 5-10% to your BTC allocation given the favorable risk/reward setup."),
            ("user", "Buy $300 of BTC"),
            ("assistant", "I've initiated a buy order for $300 of BTC-USD. Here's the trade summary:\n\n- **Asset**: BTC-USD\n- **Side**: BUY\n- **Amount**: $300.00\n- **Estimated Price**: ~$68,200\n- **Mode**: PAPER\n\nThe order has been submitted and is processing through our execution pipeline."),
        ],
    },
    {
        "tenant": "t_retail",
        "title": "ETH DCA Strategy",
        "messages": [
            ("user", "I want to start dollar-cost averaging into ETH. What do you suggest?"),
            ("assistant", "Dollar-cost averaging (DCA) into ETH is a solid strategy given current market conditions. Here's what I'd recommend:\n\n- **Weekly buy**: $100-150 of ETH-USD\n- **Duration**: 12-week commitment minimum\n- **Current price**: ~$3,800\n\nThis approach smooths out volatility and builds your position over time. Would you like to start with a purchase today?"),
            ("user", "Yes, buy $150 of ETH"),
            ("assistant", "Order placed! Buying $150 of ETH-USD at approximately $3,800. Your order is being processed now."),
        ],
    },
    {
        "tenant": "t_whale",
        "title": "Portfolio Rebalancing Discussion",
        "messages": [
            ("user", "Show me my current portfolio allocation"),
            ("assistant", "Here's your current portfolio breakdown:\n\n| Asset | Value | Allocation |\n|-------|-------|------------|\n| USD | $4,200 | 38.9% |\n| BTC | $4,500 | 41.7% |\n| ETH | $1,500 | 13.9% |\n| SOL | $600 | 5.6% |\n\n**Total Value**: $10,800\n\nYour portfolio is heavily weighted toward BTC. Consider diversifying into ETH and SOL for better risk-adjusted returns."),
            ("user", "Sell $200 of BTC and buy SOL with it"),
            ("assistant", "I'll execute a rebalancing trade:\n\n1. **Sell** $200 of BTC-USD\n2. **Buy** $200 of SOL-USD\n\nThis will shift approximately 1.9% of your allocation from BTC to SOL. Processing now..."),
        ],
    },
    {
        "tenant": "t_default",
        "title": "First Trade Setup",
        "messages": [
            ("user", "Hi, I'm new here. How do I make my first trade?"),
            ("assistant", "Welcome! Making your first trade is simple. Just tell me what you'd like to do in plain English. For example:\n\n- \"Buy $100 of BTC\"\n- \"Sell $50 of ETH\"\n- \"Buy 0.5 SOL\"\n\nAll trades start in **PAPER mode** (simulated) so you can practice risk-free. When you're ready, you can switch to LIVE mode.\n\nWhat would you like to trade?"),
            ("user", "Buy $100 of BTC"),
            ("assistant", "Your first trade is underway! Buying $100 of BTC-USD in PAPER mode.\n\n- **Asset**: BTC-USD\n- **Side**: BUY\n- **Amount**: $100.00\n- **Mode**: PAPER (simulated)\n\nYou'll see the results in your portfolio shortly. Great start!"),
        ],
    },
]

CLIENT_ISSUES = [
    {
        "tenant_id": "t_whale",
        "title": "API rate limiting during high volume",
        "description": "During peak trading hours (9-10am EST), API requests are being throttled at 50 req/min. Enterprise tier should support 200 req/min. Affecting automated trading strategies.",
        "status": "resolved",
        "priority": "high",
        "category": "api",
        "assigned_to": "ops_team",
        "resolved_at_offset": 3,
    },
    {
        "tenant_id": "t_whale",
        "title": "Order fills delayed >5s",
        "description": "Paper mode order fills are taking 5-8 seconds instead of the expected <1s. This is impacting backtesting accuracy and strategy evaluation. Started occurring after the last deployment.",
        "status": "in_progress",
        "priority": "high",
        "category": "execution",
        "assigned_to": "eng_team",
    },
    {
        "tenant_id": "t_retail",
        "title": "Policy engine blocking valid trades",
        "description": "Attempted to buy $400 of SOL-USD but got a policy violation error citing 'position concentration limit exceeded'. My SOL allocation is only 5% which should be well within limits.",
        "status": "open",
        "priority": "medium",
        "category": "policy",
    },
    {
        "tenant_id": "t_default",
        "title": "Portfolio value not updating after trade",
        "description": "Completed a BTC purchase 2 hours ago but portfolio snapshot still shows pre-trade balance. Refresh button doesn't help.",
        "status": "open",
        "priority": "low",
        "category": "general",
    },
]


# ---------------------------------------------------------------------------
# Data generation functions
# ---------------------------------------------------------------------------

def _generate_run_data(run_index: int, total_runs: int):
    """Generate a single run with all associated data."""
    # Assign to tenants using round-robin so each tenant gets recent runs.
    # whale gets ~9, retail ~5, default ~4
    tenant_cycle = [
        "t_whale", "t_retail", "t_whale", "t_default", "t_whale",
        "t_retail", "t_whale", "t_default", "t_whale",
        "t_retail", "t_whale", "t_retail", "t_whale",
        "t_retail", "t_default", "t_whale", "t_default", "t_whale",
    ]
    tenant_id = tenant_cycle[run_index % len(tenant_cycle)]

    # Pick asset
    asset = random.choice(ASSETS)
    symbol = asset["symbol"]
    base_price = asset["price"]

    # Determine status: 2-3 FAILED, rest COMPLETED
    if run_index in (4, 10, 16):
        status = "FAILED"
    else:
        status = "COMPLETED"

    # Execution mode: mostly PAPER, 2-3 LIVE
    if run_index in (2, 8):
        execution_mode = "LIVE"
    else:
        execution_mode = "PAPER"

    # Timestamps spread over 30 days
    days_ago = 30 - (run_index * 30 / total_runs)
    created_at = NOW - timedelta(days=days_ago)
    created_at = created_at.replace(
        hour=random.randint(9, 17),
        minute=random.randint(0, 59),
        second=random.randint(0, 59),
        microsecond=0,
    )
    started_at = created_at + timedelta(seconds=random.randint(1, 3))
    duration_s = random.randint(8, 45)
    completed_at = started_at + timedelta(seconds=duration_s)

    # Trade size
    notional_usd = round(random.uniform(50, 500), 2)
    side = random.choice(["BUY", "BUY", "BUY", "SELL"])  # bias toward buys

    # Realistic price with small spread
    price_delta = base_price * random.uniform(-0.02, 0.02)
    fill_price = round(base_price + price_delta, 2)
    qty = round(notional_usd / fill_price, 8)

    command_text = random.choice(COMMANDS)

    # Failure details
    failure_reason = None
    failure_code = None
    if status == "FAILED":
        failures = [
            ("EXECUTION_INSUFFICIENT_FUNDS", "Insufficient balance to execute order"),
            ("POLICY_BLOCK", "Trade blocked by position concentration policy"),
            ("EXECUTION_TIMEOUT", "Order execution timed out after 30s"),
        ]
        fc = failures[run_index % len(failures)]
        failure_code = fc[0]
        failure_reason = json.dumps({
            "code": fc[0],
            "summary": fc[1],
            "root_cause": fc[1],
            "recommended_fix": "Adjust trade size or check account balance",
        })

    run_id = _uid("run_")
    run = {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "status": status,
        "execution_mode": execution_mode,
        "created_at": _iso(created_at),
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at),
        "command_text": command_text,
        "intent_json": json.dumps({
            "action": side.lower(),
            "asset": symbol,
            "amount_usd": notional_usd,
        }),
        "parsed_intent_json": json.dumps({
            "intent_type": "trade",
            "action": side.lower(),
            "symbol": symbol,
            "notional_usd": notional_usd,
            "confidence": round(random.uniform(0.85, 0.99), 3),
        }),
        "metadata_json": json.dumps({
            "source": "chat",
            "user_agent": "ExecutionDesk-Web/1.0",
        }),
        "execution_plan_json": json.dumps({
            "nodes": DAG_NODE_NAMES,
            "parallel_groups": [["research", "signals", "news"], ["risk"], ["strategy", "proposal"],
                                ["policy_check"], ["approval"], ["execution"], ["eval"]],
        }),
        "failure_reason": failure_reason,
        "failure_code": failure_code,
        "news_enabled": 1,
        "asset_class": "CRYPTO",
        "trade_proposal_json": json.dumps({
            "symbol": symbol,
            "side": side,
            "notional_usd": notional_usd,
            "order_type": "MARKET",
        }) if status == "COMPLETED" else None,
    }

    # DAG nodes
    nodes = []
    node_start = started_at
    for i, name in enumerate(DAG_NODE_NAMES):
        node_id = _uid("node_")
        node_duration = random.uniform(0.5, 3.0)
        node_completed = node_start + timedelta(seconds=node_duration)

        # For failed runs, fail at a specific node
        if status == "FAILED" and name in ("execution", "policy_check"):
            node_status = "FAILED"
            error_json = json.dumps({"error": failure_code, "message": failure_reason})
        else:
            if status == "FAILED" and i >= DAG_NODE_NAMES.index("execution"):
                node_status = "SKIPPED"
                error_json = None
            else:
                node_status = "COMPLETED"
                error_json = None

        nodes.append({
            "node_id": node_id,
            "run_id": run_id,
            "name": name,
            "node_type": "dag_step",
            "status": node_status,
            "started_at": _iso(node_start),
            "completed_at": _iso(node_completed) if node_status != "SKIPPED" else None,
            "inputs_json": json.dumps({"step_index": i}),
            "outputs_json": json.dumps({"result": f"{name}_output"}) if node_status == "COMPLETED" else None,
            "error_json": error_json,
        })
        node_start = node_completed

    # Order & fill (only for completed runs)
    order = None
    fill = None
    if status == "COMPLETED":
        order_id = _uid("ord_")
        fee = round(notional_usd * 0.001, 4)  # 0.1% fee
        order = {
            "order_id": order_id,
            "run_id": run_id,
            "tenant_id": tenant_id,
            "provider": "paper" if execution_mode == "PAPER" else "coinbase",
            "symbol": symbol,
            "side": side,
            "order_type": "MARKET",
            "qty": qty,
            "notional_usd": notional_usd,
            "status": "FILLED",
            "created_at": _iso(completed_at - timedelta(seconds=2)),
            "filled_qty": qty,
            "avg_fill_price": fill_price,
            "total_fees": fee,
            "status_reason": "Filled at market price",
            "status_updated_at": _iso(completed_at),
        }

        fill = {
            "fill_id": _uid("fill_"),
            "order_id": order_id,
            "run_id": run_id,
            "tenant_id": tenant_id,
            "product_id": asset["product_id"],
            "price": fill_price,
            "size": qty,
            "fee": fee,
            "trade_id": _uid("trade_"),
            "liquidity_indicator": random.choice(["TAKER", "MAKER"]),
            "filled_at": _iso(completed_at),
        }

    # Eval results (only for completed runs, 6-8 per run)
    evals = []
    if status == "COMPLETED":
        eval_count = random.randint(6, 8)
        chosen_evals = random.sample(EVAL_NAMES, eval_count)
        for eval_name in chosen_evals:
            # Most scores above 0.8, some lower
            if random.random() < 0.15:
                score = round(random.uniform(0.5, 0.72), 3)
                passed = False
            else:
                score = round(random.uniform(0.80, 1.0), 3)
                passed = True

            threshold = 0.75
            evals.append({
                "eval_id": _uid("eval_"),
                "run_id": run_id,
                "tenant_id": tenant_id,
                "eval_name": eval_name,
                "score": score,
                "reasons_json": json.dumps([
                    f"{eval_name} {'passed' if passed else 'failed'}: score={score}",
                    f"Threshold: {threshold}",
                ]),
                "ts": _iso(completed_at + timedelta(seconds=random.randint(1, 5))),
                "eval_category": "quality",
                "evaluator_type": "heuristic",
                "thresholds_json": json.dumps({"pass": threshold}),
                "details_json": json.dumps({
                    "passed": passed,
                    "threshold": threshold,
                    "notes": f"Automated {eval_name} evaluation",
                }),
            })

    # Portfolio snapshots for this run (only completed) -- pre-trade and post-trade
    # The analytics code groups by date: PnL = end_value - start_value
    # We need 2 snapshots on the same date with different values for non-zero PnL
    snapshots_for_run = []
    if status == "COMPLETED":
        base_portfolio = 10000.0 + run_index * 50  # slowly growing portfolio
        pnl_for_trade = round(random.uniform(-30, 80), 2)  # per-trade PnL

        # Pre-trade snapshot (slightly before execution)
        pre_ts = completed_at - timedelta(seconds=10)
        snapshots_for_run.append({
            "snapshot_id": _uid("snap_"),
            "run_id": run_id,
            "tenant_id": tenant_id,
            "balances_json": json.dumps({
                "USD": round(base_portfolio * 0.4, 2),
                "BTC": 0.06, "ETH": 0.4, "SOL": 3.5,
            }),
            "positions_json": json.dumps({
                "BTC-USD": {"qty": 0.06, "value_usd": 4080.0},
                "ETH-USD": {"qty": 0.4, "value_usd": 1520.0},
                "SOL-USD": {"qty": 3.5, "value_usd": 630.0},
            }),
            "total_value_usd": round(base_portfolio, 2),
            "ts": _iso(pre_ts),
        })

        # Post-trade snapshot (at completion)
        snapshots_for_run.append({
            "snapshot_id": _uid("snap_"),
            "run_id": run_id,
            "tenant_id": tenant_id,
            "balances_json": json.dumps({
                "USD": round((base_portfolio + pnl_for_trade) * 0.4, 2),
                "BTC": 0.06, "ETH": 0.4, "SOL": 3.5,
            }),
            "positions_json": json.dumps({
                "BTC-USD": {"qty": 0.06, "value_usd": 4080.0 + pnl_for_trade * 0.4},
                "ETH-USD": {"qty": 0.4, "value_usd": 1520.0 + pnl_for_trade * 0.3},
                "SOL-USD": {"qty": 3.5, "value_usd": 630.0 + pnl_for_trade * 0.3},
            }),
            "total_value_usd": round(base_portfolio + pnl_for_trade, 2),
            "ts": _iso(completed_at),
        })

    return run, nodes, order, fill, evals, snapshots_for_run


def _generate_portfolio_curve(tenant_id: str, days: int = 30):
    """Generate daily portfolio snapshots showing a natural equity curve."""
    snapshots = []
    start_value = 10000.0
    value = start_value

    for day_offset in range(days, -1, -1):
        dt = NOW - timedelta(days=day_offset)
        dt = dt.replace(hour=23, minute=59, second=0, microsecond=0)

        # Natural-looking walk: slight upward bias + noise + occasional drawdown
        daily_return = random.gauss(0.003, 0.015)  # ~0.3% daily mean, 1.5% std
        if random.random() < 0.1:
            daily_return -= 0.02  # occasional drawdown

        value *= (1 + daily_return)
        value = max(value, start_value * 0.85)  # floor at -15%

        # Build realistic balances
        btc_alloc = random.uniform(0.35, 0.45)
        eth_alloc = random.uniform(0.12, 0.18)
        sol_alloc = random.uniform(0.04, 0.08)
        usd_alloc = 1.0 - btc_alloc - eth_alloc - sol_alloc

        btc_val = value * btc_alloc
        eth_val = value * eth_alloc
        sol_val = value * sol_alloc
        usd_val = value * usd_alloc

        btc_qty = btc_val / 68000.0
        eth_qty = eth_val / 3800.0
        sol_qty = sol_val / 180.0

        snapshots.append({
            "snapshot_id": _uid("snap_"),
            "run_id": None,
            "tenant_id": tenant_id,
            "balances_json": json.dumps({
                "USD": round(usd_val, 2),
                "BTC": round(btc_qty, 8),
                "ETH": round(eth_qty, 8),
                "SOL": round(sol_qty, 8),
            }),
            "positions_json": json.dumps({
                "BTC-USD": {"qty": round(btc_qty, 8), "avg_cost": 67500.0, "value_usd": round(btc_val, 2)},
                "ETH-USD": {"qty": round(eth_qty, 8), "avg_cost": 3750.0, "value_usd": round(eth_val, 2)},
                "SOL-USD": {"qty": round(sol_qty, 8), "avg_cost": 175.0, "value_usd": round(sol_val, 2)},
            }),
            "total_value_usd": round(value, 2),
            "ts": _iso(dt),
        })

    return snapshots


# ---------------------------------------------------------------------------
# Main seeding logic
# ---------------------------------------------------------------------------

def seed():
    print("[1/9] Initializing database schema...")
    init_db()

    with get_conn() as conn:
        cursor = conn.cursor()

        # Idempotency check
        cursor.execute("SELECT COUNT(*) as cnt FROM runs")
        existing = cursor.fetchone()["cnt"]
        if existing > 5:
            print(f"  Database already has {existing} runs. Skipping seed.")
            return

        # ------------------------------------------------------------------
        # 1. Tenants
        # ------------------------------------------------------------------
        print("[2/9] Seeding tenants...")
        for tid, name, ks in TENANTS:
            cursor.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, name, kill_switch_enabled) VALUES (?, ?, ?)",
                (tid, name, ks),
            )
        conn.commit()
        print(f"  Inserted {len(TENANTS)} tenants")

        # ------------------------------------------------------------------
        # 2. Runs + DAG nodes + orders + fills + evals
        # ------------------------------------------------------------------
        print("[3/9] Seeding runs, DAG nodes, orders, fills...")
        total_runs = 18
        run_snapshots = []
        runs_created = 0
        orders_created = 0
        fills_created = 0
        evals_created = 0

        for i in range(total_runs):
            run, nodes, order, fill, evals, snapshots_for_run = _generate_run_data(i, total_runs)

            # Insert run
            cursor.execute(
                """INSERT OR IGNORE INTO runs
                   (run_id, tenant_id, status, execution_mode, created_at, started_at,
                    completed_at, command_text, intent_json, parsed_intent_json,
                    metadata_json, execution_plan_json, failure_reason, failure_code,
                    news_enabled, asset_class, trade_proposal_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run["run_id"], run["tenant_id"], run["status"], run["execution_mode"],
                    run["created_at"], run["started_at"], run["completed_at"],
                    run["command_text"], run["intent_json"], run["parsed_intent_json"],
                    run["metadata_json"], run["execution_plan_json"],
                    run["failure_reason"], run["failure_code"],
                    run["news_enabled"], run["asset_class"], run["trade_proposal_json"],
                ),
            )
            runs_created += 1

            # Insert DAG nodes
            for node in nodes:
                cursor.execute(
                    """INSERT OR IGNORE INTO dag_nodes
                       (node_id, run_id, name, node_type, status, started_at,
                        completed_at, inputs_json, outputs_json, error_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        node["node_id"], node["run_id"], node["name"], node["node_type"],
                        node["status"], node["started_at"], node["completed_at"],
                        node["inputs_json"], node["outputs_json"], node["error_json"],
                    ),
                )

            # Insert order
            if order:
                cursor.execute(
                    """INSERT OR IGNORE INTO orders
                       (order_id, run_id, tenant_id, provider, symbol, side, order_type,
                        qty, notional_usd, status, created_at, filled_qty, avg_fill_price,
                        total_fees, status_reason, status_updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order["order_id"], order["run_id"], order["tenant_id"],
                        order["provider"], order["symbol"], order["side"], order["order_type"],
                        order["qty"], order["notional_usd"], order["status"], order["created_at"],
                        order["filled_qty"], order["avg_fill_price"], order["total_fees"],
                        order["status_reason"], order["status_updated_at"],
                    ),
                )
                orders_created += 1

            # Insert fill
            if fill:
                cursor.execute(
                    """INSERT OR IGNORE INTO fills
                       (fill_id, order_id, run_id, tenant_id, product_id,
                        price, size, fee, trade_id, liquidity_indicator, filled_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fill["fill_id"], fill["order_id"], fill["run_id"],
                        fill["tenant_id"], fill["product_id"], fill["price"],
                        fill["size"], fill["fee"], fill["trade_id"],
                        fill["liquidity_indicator"], fill["filled_at"],
                    ),
                )
                fills_created += 1

            # Insert evals
            for ev in evals:
                cursor.execute(
                    """INSERT OR IGNORE INTO eval_results
                       (eval_id, run_id, tenant_id, eval_name, score, reasons_json,
                        ts, eval_category, evaluator_type, thresholds_json, details_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ev["eval_id"], ev["run_id"], ev["tenant_id"], ev["eval_name"],
                        ev["score"], ev["reasons_json"], ev["ts"],
                        ev["eval_category"], ev["evaluator_type"],
                        ev["thresholds_json"], ev["details_json"],
                    ),
                )
                evals_created += 1

            # Collect run-linked snapshots (pre-trade + post-trade)
            run_snapshots.extend(snapshots_for_run)

        conn.commit()
        print(f"  Created {runs_created} runs, {orders_created} orders, {fills_created} fills, {evals_created} evals")

        # ------------------------------------------------------------------
        # 3. Portfolio snapshots (daily curve + run-linked)
        # ------------------------------------------------------------------
        print("[4/9] Seeding portfolio snapshots (30-day curve + run snapshots)...")
        snap_count = 0
        for tid in ["t_whale", "t_retail", "t_default"]:
            daily_snaps = _generate_portfolio_curve(tid, days=30)
            for snap in daily_snaps:
                cursor.execute(
                    """INSERT OR IGNORE INTO portfolio_snapshots
                       (snapshot_id, run_id, tenant_id, balances_json, positions_json,
                        total_value_usd, ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snap["snapshot_id"], snap["run_id"], snap["tenant_id"],
                        snap["balances_json"], snap["positions_json"],
                        snap["total_value_usd"], snap["ts"],
                    ),
                )
                snap_count += 1

        # Insert run-linked snapshots (pre-trade and post-trade for PnL)
        for snap in run_snapshots:
            cursor.execute(
                """INSERT OR IGNORE INTO portfolio_snapshots
                   (snapshot_id, run_id, tenant_id, balances_json, positions_json,
                    total_value_usd, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap["snapshot_id"], snap["run_id"], snap["tenant_id"],
                    snap["balances_json"], snap["positions_json"],
                    snap["total_value_usd"], snap["ts"],
                ),
            )
            snap_count += 1

        conn.commit()
        print(f"  Created {snap_count} portfolio snapshots")

        # ------------------------------------------------------------------
        # 4. Client profiles
        # ------------------------------------------------------------------
        print("[5/9] Seeding client profiles...")
        client_profiles = [
            {
                "tenant_id": "t_whale",
                "display_name": "Meridian Capital",
                "health_score": 92.5,
                "health_classification": "healthy",
                "total_runs": 9,
                "successful_runs": 8,
                "failed_runs": 1,
                "total_orders": 8,
                "total_volume_usd": 2450.0,
                "metadata_json": json.dumps({"tier": "enterprise", "contact": "ops@meridian.cap"}),
            },
            {
                "tenant_id": "t_retail",
                "display_name": "Alex Chen",
                "health_score": 78.0,
                "health_classification": "at_risk",
                "total_runs": 5,
                "successful_runs": 4,
                "failed_runs": 1,
                "total_orders": 4,
                "total_volume_usd": 980.0,
                "metadata_json": json.dumps({"tier": "pro", "contact": "alex.chen@email.com"}),
            },
            {
                "tenant_id": "t_default",
                "display_name": "Demo Trader",
                "health_score": 65.0,
                "health_classification": "new",
                "total_runs": 4,
                "successful_runs": 3,
                "failed_runs": 1,
                "total_orders": 3,
                "total_volume_usd": 320.0,
                "metadata_json": json.dumps({"tier": "starter", "contact": "demo@executiondesk.ai"}),
            },
        ]

        now_str = _iso(NOW)
        for cp in client_profiles:
            cursor.execute(
                """INSERT OR REPLACE INTO client_profiles
                   (tenant_id, display_name, health_score, health_classification,
                    total_runs, successful_runs, failed_runs, total_orders,
                    total_volume_usd, last_activity_at, first_seen_at,
                    metadata_json, computed_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cp["tenant_id"], cp["display_name"], cp["health_score"],
                    cp["health_classification"], cp["total_runs"], cp["successful_runs"],
                    cp["failed_runs"], cp["total_orders"], cp["total_volume_usd"],
                    _iso(NOW - timedelta(hours=random.randint(1, 24))),
                    _iso(NOW - timedelta(days=random.randint(30, 90))),
                    cp["metadata_json"], now_str, now_str, now_str,
                ),
            )
        conn.commit()
        print(f"  Created {len(client_profiles)} client profiles")

        # ------------------------------------------------------------------
        # 5. Client issues
        # ------------------------------------------------------------------
        print("[6/9] Seeding client issues...")
        for issue in CLIENT_ISSUES:
            issue_id = _uid("issue_")
            created_at = _iso(_rand_ts(2, 15))
            resolved_at = None
            if issue["status"] == "resolved" and "resolved_at_offset" in issue:
                resolved_at = _iso(
                    _rand_ts(0, issue["resolved_at_offset"])
                )

            cursor.execute(
                """INSERT OR IGNORE INTO client_issues
                   (issue_id, tenant_id, title, description, status, priority,
                    category, assigned_to, created_by, resolved_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    issue_id, issue["tenant_id"], issue["title"],
                    issue["description"], issue["status"], issue["priority"],
                    issue["category"], issue.get("assigned_to"),
                    "system", resolved_at, created_at, now_str,
                ),
            )
        conn.commit()
        print(f"  Created {len(CLIENT_ISSUES)} client issues")

        # ------------------------------------------------------------------
        # 6. News items
        # ------------------------------------------------------------------
        print("[7/9] Seeding news items...")
        news_count = 0
        for idx, (title, asset_symbol, confidence, sentiment) in enumerate(NEWS_HEADLINES):
            item_id = _uid("news_")
            pub_at = _iso(_rand_ts(0, 14))
            content_hash = hashlib.sha256(title.encode()).hexdigest()[:16]
            domain = random.choice(["coindesk.com", "cointelegraph.com", "decrypt.co", "bitcoinmagazine.com"])
            source_id = random.choice(["src_coindesk", "src_cointelegraph", "src_decrypt", "src_bitcoinmag"])
            url = f"https://{domain}/article/{content_hash}"

            cursor.execute(
                """INSERT OR IGNORE INTO news_items
                   (id, source_id, published_at, retrieved_at, url, canonical_url,
                    title, summary, content_hash, lang, domain)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id, source_id, pub_at, pub_at, url, url,
                    title, f"Summary: {title}", content_hash, "en", domain,
                ),
            )

            # Asset mention
            cursor.execute(
                """INSERT OR IGNORE INTO news_asset_mentions
                   (item_id, asset_symbol, confidence, method)
                   VALUES (?, ?, ?, ?)""",
                (item_id, asset_symbol, confidence, "dict"),
            )
            news_count += 1

        conn.commit()
        print(f"  Created {news_count} news items with asset mentions")

        # ------------------------------------------------------------------
        # 7. Conversations + messages
        # ------------------------------------------------------------------
        print("[8/9] Seeding conversations and messages...")
        conv_count = 0
        msg_count = 0
        for conv_seed in CONVERSATION_SEEDS:
            conv_id = _uid("conv_")
            tenant_id = conv_seed["tenant"]
            created_at = _rand_ts(1, 20)

            cursor.execute(
                """INSERT OR IGNORE INTO conversations
                   (conversation_id, tenant_id, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (conv_id, tenant_id, conv_seed["title"], _iso(created_at), _iso(NOW)),
            )
            conv_count += 1

            msg_time = created_at
            for role, content in conv_seed["messages"]:
                msg_id = _uid("msg_")
                msg_time = msg_time + timedelta(seconds=random.randint(5, 120))
                cursor.execute(
                    """INSERT OR IGNORE INTO messages
                       (message_id, conversation_id, tenant_id, role, content, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (msg_id, conv_id, tenant_id, role, content, _iso(msg_time)),
                )
                msg_count += 1

        conn.commit()
        print(f"  Created {conv_count} conversations with {msg_count} messages")

        # ------------------------------------------------------------------
        # 8. Run events (a few per completed run)
        # ------------------------------------------------------------------
        print("[9/9] Seeding run events...")
        event_count = 0
        cursor.execute("SELECT run_id, tenant_id, created_at, status FROM runs")
        all_runs = cursor.fetchall()
        for run_row in all_runs:
            rid = run_row["run_id"]
            tid = run_row["tenant_id"]
            ts_base = run_row["created_at"]

            for evt_type in ["run.started", "run.step.completed", "run.completed"]:
                cursor.execute(
                    """INSERT OR IGNORE INTO run_events
                       (id, run_id, tenant_id, event_type, payload_json, ts)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        _uid("evt_"), rid, tid, evt_type,
                        json.dumps({"status": run_row["status"]}),
                        ts_base,
                    ),
                )
                event_count += 1

        conn.commit()
        print(f"  Created {event_count} run events")

    print("\nSeed complete!")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify():
    """Print verification counts."""
    tables = [
        "tenants", "runs", "dag_nodes", "orders", "fills",
        "eval_results", "portfolio_snapshots", "client_profiles",
        "client_issues", "news_items", "conversations", "messages",
        "run_events",
    ]
    print("\n--- Verification ---")
    with get_conn() as conn:
        cursor = conn.cursor()
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                count = cursor.fetchone()["cnt"]
                print(f"  {table:30s} {count:>6d} rows")
            except Exception as e:
                print(f"  {table:30s} ERROR: {e}")


if __name__ == "__main__":
    seed()
    verify()
