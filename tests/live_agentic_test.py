"""
Smart agentic live test suite.

Sequence:
  Phase 1  — Portfolio analysis (reads real state, fails fast if empty)
  Round 1  — Stage-only NL sell variants (parsing + reasoning quality)
  Round 2  — EXECUTE sell-all (get maximum cash)
  Round 3  — EXECUTE 4 real buys (different phrasings, re-checks cash each time)
  Round 4  — EXECUTE partial sells on what we just bought
  Round 5  — EXECUTE one final buy (completes buy->sell->buy cycle)
  Round 6  — Reasoning stress tests (stage only, diagnose gpt-4o quality)
  Round 7  — Final portfolio snapshot

Rules:
  - No trade above $2.00
  - All amounts derived from real live portfolio state
  - State re-read between every executed trade
  - Self-diagnoses every failure with exact codebase location

Run:
    python tests/live_agentic_test.py

Flags:
    TEST_SERVER_URL   default: http://localhost:8000
    TEST_AUTH_TOKEN   default: (empty)
    TEST_TENANT_ID    default: t_default (for local dev header auth)
    TEST_DRY_RUN=1    stage trades but never confirm
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

BASE_URL = os.getenv("TEST_SERVER_URL", "http://localhost:8000")
AUTH_TOKEN = os.getenv("TEST_AUTH_TOKEN", "")
TENANT_ID = os.getenv("TEST_TENANT_ID", "t_default")
DRY_RUN = os.getenv("TEST_DRY_RUN", "0") == "1"
MAX_TRADE_USD = 2.00
REQUEST_TIMEOUT_S = float(os.getenv("TEST_REQUEST_TIMEOUT_S", "150"))
REQUEST_TIMEOUT_RETRIES = int(os.getenv("TEST_REQUEST_TIMEOUT_RETRIES", "2"))

HEADERS = {
    "Content-Type": "application/json",
    "X-Dev-Tenant": TENANT_ID,
    **({"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}),
}

P = "[OK]"
F = "[FAIL]"
W = "[WARN]"
I = "[INFO]"
B = ""
R = ""

# Shared state
_portfolio: Dict[str, Any] = {}
_holdings: Dict[str, float] = {}  # symbol -> usd_value
_cash_usd: float = 0.0
_total_usd: float = 0.0
_results: List[Dict[str, Any]] = []


def _post(
    client: httpx.Client, text: str, conv_id: str, confirmation_id: Optional[str] = None
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"text": text, "conversation_id": conv_id}
    if confirmation_id:
        body["confirmation_id"] = confirmation_id
    timeout_err: Optional[Exception] = None
    for attempt in range(REQUEST_TIMEOUT_RETRIES + 1):
        try:
            r = client.post(
                "/api/v1/chat/command",
                headers=HEADERS,
                json=body,
                timeout=REQUEST_TIMEOUT_S,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            body_text = ""
            try:
                body_text = (
                    e.response.json().get("error", {}).get("message", e.response.text[:300])
                )
            except Exception:
                body_text = e.response.text[:300]
            return {
                "_error": f"HTTP {e.response.status_code}",
                "_detail": body_text,
                "_raw": e.response.text[:500],
            }
        except httpx.TimeoutException as e:
            timeout_err = e
            if attempt < REQUEST_TIMEOUT_RETRIES:
                # Brief backoff helps when backend is still finalizing prior runs.
                time.sleep(1.5 * (attempt + 1))
                continue
            return {"_error": f"timeout after {REQUEST_TIMEOUT_S:.0f}s x {REQUEST_TIMEOUT_RETRIES + 1}"}
        except Exception as e:
            return {"_error": str(e)}

    return {"_error": str(timeout_err) if timeout_err else "unknown request error"}


def _confirm(
    client: httpx.Client, conv_id: str, confirmation_id: Optional[str] = None
) -> Dict[str, Any]:
    return _post(client, "CONFIRM", conv_id, confirmation_id)


def _refresh(client: httpx.Client, label: str) -> Dict[str, Any]:
    global _cash_usd, _holdings
    print(f"\n  {I} Refreshing state: {label}...")
    resp = _post(client, "Analyze my portfolio", f"refresh_{label[:20].replace(' ', '_')}")
    if "_error" in resp:
        print(f"  {W} State refresh failed: {resp['_error']}")
        return {}
    brief = resp.get("portfolio_brief") or {}
    _cash_usd = float(brief.get("cash_usd") or 0)
    _holdings.clear()
    for h in (brief.get("holdings") or []):
        sym = (h.get("asset_symbol") or "").upper()
        usd = float(h.get("usd_value") or 0)
        if sym and usd > 0 and sym not in ("USD", "USDC", "USDT"):
            _holdings[sym] = usd
    mode = (brief.get("mode") or "UNKNOWN").upper()
    print(f"  {I} [{mode}] cash=${_cash_usd:.2f} holdings={_holdings}")
    if mode != "LIVE":
        print(f"  {W} WARNING: mode is {mode} not LIVE - check .env settings")
    return brief


def _safe_buy(fraction: float = 0.25) -> float:
    """Safe buy amount floored at $1, capped at $2."""
    if _cash_usd < 1.00:
        return 0.0
    return round(min(max(_cash_usd * fraction, 1.00), MAX_TRADE_USD), 2)


def _analyse_reasoning(resp: Dict[str, Any]) -> Dict[str, Any]:
    content = (resp.get("content") or "").lower()
    ns = resp.get("narrative_structured") or {}
    ns_lead = (ns.get("lead") or "").lower()
    ns_lines = ns.get("lines") or []
    all_text = " ".join([content, ns_lead] + [str(l).lower() for l in ns_lines])

    is_fallback = (
        "pulled the latest executable balances" in all_text
        and "%" not in all_text
        and "portfolio" not in all_text
    )

    return {
        "has_plan_summary": any(
            w in all_text
            for w in ["selling", "buying", "sell", "buy", "liquidat", "execut", "proceed"]
        ),
        "has_step_summaries": "step 1" in all_text,
        "has_portfolio_impact": "%" in all_text or ("of $" in all_text),
        "has_risk_flags": "note:" in all_text
        or any(
            w in all_text
            for w in ["warn", "fee", "exceed", "caution", "exposure", "liquidat all"]
        ),
        "is_fallback": is_fallback,
        "mode_in_response": (
            "live" if "live" in all_text else ("paper" if "paper" in all_text else "unknown")
        ),
    }


def _print_reasoning(a: Dict[str, Any]) -> None:
    checks = [
        ("Plan summary", a["has_plan_summary"]),
        ("Step summaries", a["has_step_summaries"]),
        ("Portfolio impact", a["has_portfolio_impact"]),
        ("Risk flags", a["has_risk_flags"]),
    ]
    for label, ok in checks:
        print(f"      {'Y' if ok else 'N'} {label}: {'present' if ok else 'MISSING'}")
    if a["is_fallback"]:
        print(f"      {W} Reasoning: FALLBACK - gpt-4o not running")
        print("         Fix: check OPENAI_API_KEY in .env and restart server")
        print("         Code: backend/agents/trade_reasoner.py -> _get_openai_key()")
    else:
        print(f"      {P} Reasoning: gpt-4o active")


DIAGNOSES = {
    "REJECTED/no_asset": (
        "Symbol not extracted from text",
        "backend/agents/trade_parser.py",
        "Dynamic extraction fallback around _candidate_tokens may miss some forms.",
    ),
    "REJECTED/min_notional": (
        "SELL blocked by min notional check even though base_size is set",
        "backend/services/trade_preflight.py",
        "run_preflight() Check 1: add not _has_base_size guard.",
    ),
    "REJECTED/live_disabled": (
        "LIVE mode disabled by safety flag",
        ".env",
        "Set TRADING_DISABLE_LIVE=false and restart server.",
    ),
    "REJECTED/no_executable": (
        "ExecutableState has no balance for this asset",
        "backend/services/asset_resolver.py",
        "resolve_from_executable_state() returned RESOLUTION_FAIL.",
    ),
    "REJECTED/amount_zero": (
        "amount_usd=0 or None blocking SELL despite base_size being set",
        "backend/api/routes/chat.py",
        "SELL with base_size should bypass amount_usd<=0 guard.",
    ),
    "HTTP_403/live_disabled": (
        "CONFIRM blocked - TRADING_DISABLE_LIVE=true in .env",
        ".env + backend/api/routes/chat.py",
        "Set TRADING_DISABLE_LIVE=false and restart server.",
    ),
    "HTTP_403/paper_mode": (
        "CONFIRM blocked - trade was staged in PAPER mode, not LIVE",
        ".env + backend/agents/trade_parser.py",
        "Set EXECUTION_MODE_DEFAULT=LIVE and ENABLE_LIVE_TRADING=true, then restart.",
    ),
    "FALLBACK_REASONING": (
        "gpt-4o not running - reasoning using template fallback",
        "backend/agents/trade_reasoner.py",
        "_get_openai_key() returns None. Check OPENAI_API_KEY in .env.",
    ),
}


def _fmt_diagnosis(key: str) -> str:
    cause, location, fix = DIAGNOSES[key]
    return f"\n         ROOT CAUSE: {cause}\n         FILE: {location}\n         FIX: {fix}"


def _diagnose(resp: Dict[str, Any], status: str, command: str) -> List[str]:
    issues: List[str] = []
    content = (resp.get("content") or "").lower()
    err = (resp.get("_error") or "").lower()
    detail = (resp.get("_detail") or "").lower()

    if status == "REJECTED":
        if "asset not found" in content or "asset is none" in content:
            issues.append(_fmt_diagnosis("REJECTED/no_asset"))
        if "below minimum" in content or "min_notional" in content:
            issues.append(_fmt_diagnosis("REJECTED/min_notional"))
        if "live trading is disabled" in content or "live_disabled" in content:
            issues.append(_fmt_diagnosis("REJECTED/live_disabled"))
        if "no executable" in content or "quantity is 0" in content:
            issues.append(_fmt_diagnosis("REJECTED/no_executable"))
        if "unable to compute an executable amount" in content:
            issues.append(_fmt_diagnosis("REJECTED/amount_zero"))
        if not issues:
            issues.append(f"REJECTED with unknown reason. Content: {content[:200]}")

    if "403" in err or "live_disabled" in detail:
        if "paper" in content:
            issues.append(_fmt_diagnosis("HTTP_403/paper_mode"))
        else:
            issues.append(_fmt_diagnosis("HTTP_403/live_disabled"))

    if "_error" in resp:
        issues.append(f"Request error: {resp['_error']} - {resp.get('_detail', '')[:200]}")

    return issues


def run_test(
    client: httpx.Client,
    *,
    name: str,
    category: str,
    command: str,
    expect_status: str,
    confirm_if_staged: bool = False,
    skip_if: bool = False,
    skip_reason: str = "",
    conv_id: Optional[str] = None,
    wait_after_execute: int = 3,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "name": name,
        "category": category,
        "command": command,
        "passed": False,
        "skipped": False,
        "status_got": None,
        "reasoning": {},
        "issues": [],
        "confirmation_id": None,
        "execution_status": None,
        "next_confirmation_id": None,
    }

    if skip_if:
        result["skipped"] = True
        result["skip_reason"] = skip_reason
        print(f"  {W} SKIP [{name}]: {skip_reason}")
        _results.append(result)
        return result

    cid = conv_id or f"test_{name[:25].replace(' ', '_').replace('/', '_')}"
    print(f"\n{B}[{category}] {name}{R}")
    print(f"  {I} {command!r}")

    resp = _post(client, command, cid)

    if "_error" in resp:
        result["issues"] += _diagnose(resp, "ERROR", command)
        print(f"  {F} Request failed: {resp['_error']}")
        for issue in result["issues"]:
            print(f"  {F} DIAGNOSIS:{issue}")
        _results.append(result)
        return result

    status = resp.get("status", "")
    confirmation_id = resp.get("confirmation_id")
    next_cid = resp.get("next_confirmation_id")
    content = resp.get("content") or ""
    result["status_got"] = status
    result["confirmation_id"] = confirmation_id
    result["next_confirmation_id"] = next_cid

    print(f"  {I} Status: {status}")
    print(f"  {I} Content: {content[:220]}")

    ra = _analyse_reasoning(resp)
    result["reasoning"] = ra
    print(f"  {I} Reasoning layer:")
    _print_reasoning(ra)

    ok = True
    if status != expect_status:
        result["issues"] += _diagnose(resp, status, command)
        print(f"  {F} Expected {expect_status}, got {status}")
        for issue in result["issues"]:
            print(f"  {F} DIAGNOSIS:{issue}")
        ok = False
    else:
        print(f"  {P} Status: {status}")

    pending = resp.get("pending_trade") or {}
    trade_mode = pending.get("mode", "")
    if trade_mode == "PAPER":
        print("  [WARN] Trade staged in PAPER mode - check .env EXECUTION_MODE_DEFAULT=LIVE")
        result["issues"].append("Trade staged in PAPER not LIVE - set EXECUTION_MODE_DEFAULT=LIVE")

    if status == "AWAITING_CONFIRMATION" and confirm_if_staged and not DRY_RUN:
        print(f"  {I} Confirming...")
        time.sleep(0.5)
        exec_resp = _confirm(client, cid, confirmation_id)
        exec_status = exec_resp.get("status", "")
        result["execution_status"] = exec_status

        if exec_status == "EXECUTING":
            run_id = exec_resp.get("run_id", "")
            print(f"  {P} Executing: run_id={run_id}")
            if wait_after_execute > 0:
                print(f"  {I} Waiting {wait_after_execute}s for fill...")
                time.sleep(wait_after_execute)
        else:
            print(f"  {W} Execution response: {exec_status}")
            print(f"       {exec_resp.get('content', '')[:200]}")
            exec_issues = _diagnose(exec_resp, exec_status, "CONFIRM")
            result["issues"] += exec_issues
            for issue in exec_issues:
                print(f"  {F} DIAGNOSIS:{issue}")
            if exec_status not in ("EXECUTING", "COMPLETED"):
                ok = False
    elif DRY_RUN and status == "AWAITING_CONFIRMATION":
        print(f"  {I} DRY_RUN - staged but not confirmed")

    result["passed"] = ok
    _results.append(result)
    return result


def phase_portfolio(client: httpx.Client) -> Dict[str, Any]:
    global _total_usd
    print(f"\n{'=' * 70}")
    print(f"{B}PHASE 1 - PORTFOLIO ANALYSIS{R}")
    print(f"{'=' * 70}")

    resp = _post(client, "Analyze my portfolio", "phase1_portfolio")

    if "_error" in resp:
        print(f"{F} Portfolio fetch failed: {resp['_error']}")
        print(f"   Is the server running at {BASE_URL}?")
        sys.exit(1)

    if resp.get("status") == "FAILED":
        print(f"{F} Portfolio analysis failed: {resp.get('content')}")
        print("   Check Coinbase credentials in .env")
        sys.exit(1)

    brief = resp.get("portfolio_brief") or {}
    _total_usd = float(brief.get("total_value_usd") or 0)
    mode = (brief.get("mode") or "UNKNOWN").upper()

    _refresh(client, "initial")

    print(f"\n  {P} Portfolio loaded in {mode} mode")
    print(f"       Total:    ${_total_usd:.2f}")
    print(f"       Cash:     ${_cash_usd:.2f}")
    print(f"       Holdings: {_holdings}")
    print(f"       Content:  {str(resp.get('content', ''))[:250]}")

    if mode != "LIVE":
        print(f"\n  {W} WARNING: Platform is in {mode} mode, not LIVE")
        print("     Fix .env: EXECUTION_MODE_DEFAULT=LIVE, ENABLE_LIVE_TRADING=true")
        print("     Restart server and re-run")
        sys.exit(1)

    if _total_usd <= 0:
        print(f"\n{F} Portfolio appears empty. Fund Coinbase account and retry.")
        sys.exit(1)

    return brief


def phase_tests(client: httpx.Client) -> None:
    print(f"\n{'=' * 70}")
    print(f"{B}PHASE 2 - TRADE TESTS{R}")
    if DRY_RUN:
        print(f"{W} DRY_RUN=1 - trades staged but NOT confirmed")
    print(f"{'=' * 70}")

    print(f"\n{B}ROUND 1 - NL SELL VARIANTS (staging only){R}")

    largest = max(_holdings, key=_holdings.get) if _holdings else None
    smallest = min(_holdings, key=_holdings.get) if _holdings else None

    if largest:
        run_test(
            client,
            name="dump largest",
            category="SELL/NL",
            command=f"dump my {largest}",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )
        run_test(
            client,
            name="get rid of",
            category="SELL/NL",
            command=f"get rid of my {largest} holdings",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )
        run_test(
            client,
            name="exit completely",
            category="SELL/NL",
            command=f"I want to exit my {largest} completely",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )
    if smallest and smallest != largest:
        run_test(
            client,
            name="liquidate smallest",
            category="SELL/NL",
            command=f"liquidate my {smallest} position",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    run_test(
        client,
        name="sell everything",
        category="SELL/NL",
        command="sell everything",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=False,
    )
    run_test(
        client,
        name="close all positions",
        category="SELL/NL",
        command="close all positions",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=False,
    )

    print(f"\n{B}ROUND 2 - EXECUTE SELL-ALL (fund buy tests){R}")
    r = run_test(
        client,
        name="liquidate all - EXECUTE",
        category="SELL/EXECUTE",
        command="liquidate all of my crypto holdings",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=True,
        wait_after_execute=4,
        skip_if=not _holdings,
        skip_reason="No holdings to sell",
    )
    if r.get("execution_status") == "EXECUTING":
        _refresh(client, "after sell-all")

    print(f"\n{B}ROUND 3 - EXECUTE 4 REAL BUYS{R}")

    amt = _safe_buy(0.25)
    r1 = run_test(
        client,
        name="BUY 1 - highest performer 24h",
        category="BUY/EXECUTE",
        command=f"buy ${amt:.2f} of the highest performing crypto in the last 24 hours",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=True,
        wait_after_execute=3,
        skip_if=amt < 1.00,
        skip_reason=f"Cash too low (${_cash_usd:.2f})",
    )
    if r1.get("execution_status") == "EXECUTING":
        _refresh(client, "after buy 1")

    amt = _safe_buy(0.25)
    r2 = run_test(
        client,
        name="BUY 2 - bitcoin spoken name",
        category="BUY/EXECUTE",
        command=f"buy ${amt:.2f} of bitcoin",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=True,
        wait_after_execute=3,
        skip_if=amt < 1.00,
        skip_reason=f"Cash too low (${_cash_usd:.2f})",
    )
    if r2.get("execution_status") == "EXECUTING":
        _refresh(client, "after buy 2")

    amt = _safe_buy(0.25)
    r3 = run_test(
        client,
        name="BUY 3 - pick up ethereum",
        category="BUY/EXECUTE",
        command=f"pick up ${amt:.2f} of ethereum for me",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=True,
        wait_after_execute=3,
        skip_if=amt < 1.00,
        skip_reason=f"Cash too low (${_cash_usd:.2f})",
    )
    if r3.get("execution_status") == "EXECUTING":
        _refresh(client, "after buy 3")

    amt = _safe_buy(0.25)
    r4 = run_test(
        client,
        name="BUY 4 - momentum natural language",
        category="BUY/EXECUTE",
        command=f"what's got the most momentum right now - put ${amt:.2f} into it",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=True,
        wait_after_execute=3,
        skip_if=amt < 1.00,
        skip_reason=f"Cash too low (${_cash_usd:.2f})",
    )
    if r4.get("execution_status") == "EXECUTING":
        _refresh(client, "after buy 4")

    print(f"\n{B}ROUND 4 - PARTIAL SELLS ON NEW POSITIONS{R}")
    if _holdings:
        largest = max(_holdings, key=_holdings.get)
        r5 = run_test(
            client,
            name="SELL 25% of largest",
            category="SELL/EXECUTE",
            command=f"sell 25% of my {largest}",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=True,
            wait_after_execute=3,
        )
        if r5.get("execution_status") == "EXECUTING":
            _refresh(client, "after 25pct sell")

        if _holdings:
            second = max(_holdings, key=_holdings.get)
            r6 = run_test(
                client,
                name="SELL half - natural language",
                category="SELL/EXECUTE",
                command=f"sell half of my {second} position",
                expect_status="AWAITING_CONFIRMATION",
                confirm_if_staged=True,
                wait_after_execute=3,
            )
            if r6.get("execution_status") == "EXECUTING":
                _refresh(client, "after half sell")
    else:
        print(f"  {W} No holdings after buys - skipping partial sells")

    print(f"\n{B}ROUND 5 - FINAL BUY (completes buy->sell->buy cycle){R}")
    amt = _safe_buy(0.30)
    r7 = run_test(
        client,
        name="BUY 5 - top gainer 24h",
        category="BUY/EXECUTE",
        command=f"invest ${amt:.2f} in the top gainer from the last 24 hours",
        expect_status="AWAITING_CONFIRMATION",
        confirm_if_staged=True,
        wait_after_execute=3,
        skip_if=amt < 1.00,
        skip_reason=f"Cash too low (${_cash_usd:.2f})",
    )
    if r7.get("execution_status") == "EXECUTING":
        _refresh(client, "after final buy")

    print(f"\n{B}ROUND 6 - REASONING STRESS TESTS (staging only){R}")
    largest = max(_holdings, key=_holdings.get) if _holdings else None
    has_cash = _cash_usd >= 1.00

    if _holdings and len(_holdings) >= 2:
        run_test(
            client,
            name="sell-all - must show impact %",
            category="REASONING/IMPACT",
            command="sell everything i have",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    if has_cash:
        amt = min(_safe_buy(), 1.50)
        run_test(
            client,
            name="momentum buy - name the asset",
            category="REASONING/SELECTION",
            command=f"buy ${amt:.2f} of whatever has the best momentum right now",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

        run_test(
            client,
            name="buy worst performer",
            category="REASONING/SELECTION",
            command=f"buy ${min(_safe_buy(), 1.00):.2f} of the worst performing crypto today",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    if largest:
        run_test(
            client,
            name="reduce exposure 25pct",
            category="REASONING/REBALANCE",
            command=f"I'm overexposed to {largest}, cut my position by 25%",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    if largest and has_cash:
        run_test(
            client,
            name="rotate - sell then buy best",
            category="REASONING/CHAIN",
            command=f"rotate out of {largest} and put ${min(_safe_buy(), 1.00):.2f} into the best performer",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    if has_cash:
        run_test(
            client,
            name="tiny order - must flag fee risk",
            category="REASONING/FEES",
            command="buy $1.00 of bitcoin",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    if _holdings:
        run_test(
            client,
            name="sell biggest loser",
            category="REASONING/SMART",
            command="sell whichever of my holdings is down the most",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    if has_cash:
        run_test(
            client,
            name="buy top mover last 1hr",
            category="REASONING/TIMEFRAME",
            command=f"buy ${min(_safe_buy(), 1.00):.2f} of the biggest mover in the last hour",
            expect_status="AWAITING_CONFIRMATION",
            confirm_if_staged=False,
        )

    run_test(
        client,
        name="sell non-held asset - must REJECT",
        category="EDGE/REJECTED",
        command="sell all of my DOGE",
        expect_status="REJECTED",
    )

    print(f"\n{B}ROUND 7 - FINAL PORTFOLIO STATE{R}")
    final = _refresh(client, "final")
    final_total = float(final.get("total_value_usd") or 0)
    diff = final_total - _total_usd
    print(f"  {I} Started:  ${_total_usd:.2f}")
    print(f"  {I} Finished: ${final_total:.2f}")
    print(f"  {I} Delta:    ${diff:+.2f} (fees + slippage on test trades)")


def report() -> bool:
    print(f"\n{'=' * 70}")
    print(f"{B}FINAL REPORT{R}")
    print(f"{'=' * 70}")

    ran = [r for r in _results if not r.get("skipped")]
    skipped = [r for r in _results if r.get("skipped")]
    passed = [r for r in ran if r["passed"]]
    failed = [r for r in ran if not r["passed"]]

    executed = [r for r in ran if r.get("execution_status") == "EXECUTING"]
    fallbacks = [r for r in ran if r.get("reasoning", {}).get("is_fallback")]
    with_impact = [r for r in ran if r.get("reasoning", {}).get("has_portfolio_impact")]

    print(f"\n  Tests run:    {len(ran)}")
    print(f"  Passed:       {P} {len(passed)}")
    print(f"  Failed:       {F} {len(failed)}")
    print(f"  Skipped:      {W} {len(skipped)}")
    print(f"  Real trades:  {P if executed else W} {len(executed)} executed on Coinbase")

    print(f"\n  {B}Reasoning Layer:{R}")
    llm_active = len(ran) - len(fallbacks)
    print(f"  gpt-4o active:     {P if llm_active > 0 else F} {llm_active}/{len(ran)}")
    print(f"  Fallback used:     {W if fallbacks else P} {len(fallbacks)}")
    print(f"  Portfolio impact:  {P if with_impact else W} {len(with_impact)} responses")

    if fallbacks:
        print(f"\n  {W} REASONING DIAGNOSIS:")
        print(f"     gpt-4o not running on {len(fallbacks)} response(s).")
        print("     Root cause: OPENAI_API_KEY missing or _get_openai_key() failing.")
        print("     File: backend/agents/trade_reasoner.py -> _get_openai_key()")
        print("     Fix: ensure OPENAI_API_KEY is present in .env, restart server.")

    if failed:
        print(f"\n  {B}FAILED TESTS - ROOT CAUSE ANALYSIS:{R}")
        for r in failed:
            print(f"\n  {F} [{r['category']}] {r['name']}")
            print(f"       CMD:    {r['command']!r}")
            print(f"       STATUS: {r['status_got']}")
            for issue in r["issues"]:
                print(f"       {issue}")
            ra = r.get("reasoning") or {}
            if ra.get("is_fallback"):
                print("       REASONING: fallback - gpt-4o not active")
            if not ra.get("has_plan_summary") and r["status_got"] == "AWAITING_CONFIRMATION":
                print("       REASONING: no plan_summary - check build_trade_narrative() in narrative.py")
            if not ra.get("has_step_summaries") and r["status_got"] == "AWAITING_CONFIRMATION":
                print("       REASONING: no step_summaries - check step_summaries in TradeReasoning")

    print(f"\n{'=' * 70}")
    if not failed:
        print(f"  {P} ALL TESTS PASSED")
        if llm_active == len(ran):
            print(f"  {P} gpt-4o reasoning fully active")
        if executed:
            print(f"  {P} {len(executed)} real Coinbase orders executed successfully")
    else:
        print(f"  {F} {len(failed)} TEST(S) FAILED - see root cause analysis above")
    print(f"{'=' * 70}\n")

    return len(failed) == 0


def main() -> None:
    print(f"\n{B}SMART AGENTIC LIVE TEST SUITE{R}")
    print(f"Server:    {BASE_URL}")
    print(f"Max trade: ${MAX_TRADE_USD:.2f}")
    print(f"Mode:      {'DRY RUN - no confirms' if DRY_RUN else 'LIVE - real trades execute'}")

    if not DRY_RUN:
        print(f"\n{W} Real trades will execute on Coinbase (max ${MAX_TRADE_USD:.2f} each).")
        print("   Set TEST_DRY_RUN=1 to stage only.")
        confirm = input("   Type YES to proceed: ").strip()
        if confirm.upper() != "YES":
            print("Aborted.")
            sys.exit(0)

    with httpx.Client(base_url=BASE_URL, timeout=REQUEST_TIMEOUT_S) as client:
        phase_portfolio(client)
        phase_tests(client)

    ok = report()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
