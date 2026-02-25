"""Authoritative executable balances for trading decisions.

This module fetches Coinbase account balances and derives executable quantities.
It is the source of truth for SELL sizing and sellability checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional

import httpx

from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.core.time import now_iso
from backend.db.connect import get_conn
from backend.providers.coinbase_provider import CoinbaseProvider

logger = get_logger(__name__)


@dataclass
class ExecutableBalance:
    currency: str
    available_qty: float
    hold_qty: float
    account_uuid: Optional[str]
    updated_at: Optional[str]


@dataclass
class ExecutableState:
    balances: Dict[str, ExecutableBalance]
    fetched_at: str
    source: str


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _fetch_coinbase_accounts() -> Dict[str, Any]:
    provider = CoinbaseProvider()
    path = "/api/v3/brokerage/accounts"
    headers = provider._get_headers("GET", path)
    with httpx.Client(timeout=8.0) as client:
        resp = client.get(f"https://api.coinbase.com{path}", headers=headers)
        resp.raise_for_status()
        return resp.json()


def fetch_executable_state(tenant_id: str) -> ExecutableState:
    """Fetch current executable balances.

    LIVE: reads Coinbase List Accounts and derives:
      - available_qty from available_balance.value
      - hold_qty from hold.value
    FALLBACK: if LIVE fetch is unavailable, derive from latest snapshot.
    """
    settings = get_settings()
    fetched_at = now_iso()

    if settings.enable_live_trading and settings.coinbase_api_key_name and settings.coinbase_api_private_key:
        try:
            payload = _fetch_coinbase_accounts()
            balances: Dict[str, ExecutableBalance] = {}
            for account in payload.get("accounts", []):
                currency = (account.get("currency") or "").upper().strip()
                if not currency:
                    continue
                available_qty = _as_float((account.get("available_balance") or {}).get("value"))
                hold_qty = _as_float((account.get("hold") or {}).get("value"))
                balances[currency] = ExecutableBalance(
                    currency=currency,
                    available_qty=available_qty,
                    hold_qty=hold_qty,
                    account_uuid=account.get("uuid"),
                    updated_at=account.get("updated_at"),
                )
            return ExecutableState(
                balances=balances,
                fetched_at=fetched_at,
                source="coinbase_list_accounts",
            )
        except Exception as exc:
            logger.warning("Executable LIVE state fetch failed: %s", str(exc)[:240])

    # Snapshot fallback for compatibility/testing.
    snapshot_balances: Dict[str, ExecutableBalance] = {}
    try:
        import json

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT balances_json, ts
                FROM portfolio_snapshots
                WHERE tenant_id = ?
                ORDER BY ts DESC LIMIT 1
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
            if row:
                raw = json.loads(row["balances_json"] or "{}")
                updated_at = row["ts"]
                for currency, qty in raw.items():
                    ccy = str(currency).upper().strip()
                    snapshot_balances[ccy] = ExecutableBalance(
                        currency=ccy,
                        available_qty=_as_float(qty),
                        hold_qty=0.0,
                        account_uuid=None,
                        updated_at=updated_at,
                    )
    except Exception as exc:
        logger.warning("Executable snapshot fallback failed: %s", str(exc)[:240])

    return ExecutableState(
        balances=snapshot_balances,
        fetched_at=fetched_at,
        source="portfolio_snapshot_fallback",
    )

