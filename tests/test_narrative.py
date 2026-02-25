"""Tests for the shared narrative formatter/validator.

Asserts the enterprise-grounded narrative contract:
  - 3-6 lines separated by double newlines.
  - No forbidden tokens (snake_case internals).
  - Evidence line has 2-4 clickable links with approved schemes.
  - Missing fields render as 'unavailable', not invented.
  - Line length <= 200 characters.
"""
import re
import pytest
from backend.agents.narrative import (
    format_portfolio_narrative,
    format_asset_holdings_narrative,
    format_simple_portfolio_narrative,
    format_no_snapshot_narrative,
    format_snapshot_failed_narrative,
    format_trade_confirmation_narrative,
    format_trade_execution_narrative,
    format_multi_execution_narrative,
    format_trade_blocked_narrative,
    format_no_parse_narrative,
    format_missing_amount_narrative,
    build_trade_narrative,
    build_narrative_structured,
    PARAGRAPH_SEP,
    MAX_LINE_LENGTH,
    FORBIDDEN_TOKENS,
)

EVIDENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
ALLOWED_SCHEMES = ("run:", "url:")


def _check_contract(text: str) -> list:
    """Return a list of violations (empty = pass)."""
    violations = []
    lines = text.split(PARAGRAPH_SEP)
    if not (3 <= len(lines) <= 6):
        violations.append(f"Expected 3-6 lines, got {len(lines)}")
    for i, line in enumerate(lines):
        if len(line) > MAX_LINE_LENGTH:
            violations.append(f"Line {i+1} exceeds {MAX_LINE_LENGTH} chars ({len(line)})")
        if FORBIDDEN_TOKENS.search(line):
            violations.append(f"Line {i+1} contains forbidden token")
    evidence_links = EVIDENCE_LINK_RE.findall(lines[-1]) if lines else []
    if not (2 <= len(evidence_links) <= 4):
        violations.append(f"Evidence line must have 2-4 links, found {len(evidence_links)}")
    for label, href in evidence_links:
        if not any(href.startswith(s) for s in ALLOWED_SCHEMES):
            violations.append(f"Evidence href {href!r} uses unsupported scheme")
    return violations


# ── Portfolio narratives ────────────────────────────────────────────────


class TestPortfolioNarrative:

    BRIEF = {
        "mode": "PAPER",
        "as_of": "2026-02-19T10:30:00Z",
        "total_value_usd": 12500.0,
        "cash_usd": 2500.0,
        "holdings": [
            {"asset_symbol": "BTC", "qty": 0.1, "usd_value": 9000.0, "current_price": 90000.0},
            {"asset_symbol": "ETH", "qty": 2.0, "usd_value": 1000.0, "current_price": 500.0},
        ],
        "risk": {
            "risk_level": "MEDIUM",
            "concentration_pct_top1": 72.0,
            "concentration_pct_top3": 80.0,
            "diversification_score": 0.45,
        },
        "recommendations": [
            {"priority": "HIGH", "description": "Consider diversifying beyond BTC."},
            {"priority": "LOW", "description": "Portfolio looks healthy overall."},
        ],
        "evidence_refs": {
            "accounts_call_id": "tc_acct_123",
            "prices_call_ids": ["tc_price_1"],
            "orders_call_id": None,
        },
    }

    def test_passes_contract(self):
        result = format_portfolio_narrative(self.BRIEF)
        violations = _check_contract(result)
        assert violations == [], violations

    def test_line1_interpretation(self):
        result = format_portfolio_narrative(self.BRIEF)
        first_line = result.split(PARAGRAPH_SEP)[0]
        assert "$12,500.00" in first_line
        assert "PAPER" in first_line

    def test_holdings_present(self):
        result = format_portfolio_narrative(self.BRIEF)
        assert "BTC" in result
        assert "@ $90,000.00" in result

    def test_risk_present(self):
        result = format_portfolio_narrative(self.BRIEF)
        assert "MEDIUM" in result
        assert "72.0%" in result
        assert "Consider diversifying" in result

    def test_evidence_clickable(self):
        result = format_portfolio_narrative(self.BRIEF)
        last_line = result.split(PARAGRAPH_SEP)[-1]
        links = EVIDENCE_LINK_RE.findall(last_line)
        assert 2 <= len(links) <= 4
        for label, href in links:
            assert any(href.startswith(s) for s in ALLOWED_SCHEMES)

    def test_missing_risk_shows_unavailable(self):
        brief = {**self.BRIEF, "risk": {}}
        result = format_portfolio_narrative(brief)
        assert "unavailable" in result

    def test_no_holdings(self):
        brief = {**self.BRIEF, "holdings": []}
        result = format_portfolio_narrative(brief)
        assert "no open positions" in result.lower()

    def test_missing_price_shows_unavailable(self):
        brief = {**self.BRIEF, "holdings": [
            {"asset_symbol": "SOL", "qty": 10, "usd_value": 500.0, "current_price": None}
        ]}
        result = format_portfolio_narrative(brief)
        assert "@ unavailable" in result

    def test_no_forbidden_tokens(self):
        result = format_portfolio_narrative(self.BRIEF)
        for line in result.split(PARAGRAPH_SEP):
            assert not FORBIDDEN_TOKENS.search(line), f"Forbidden token in: {line!r}"

    def test_never_starts_with_pulled(self):
        result = format_portfolio_narrative(self.BRIEF)
        assert not result.startswith("Pulled the latest")

    def test_no_artifact_scheme(self):
        result = format_portfolio_narrative(self.BRIEF)
        assert "artifact:" not in result


class TestAssetHoldingsNarrative:

    BRIEF = {
        "mode": "LIVE",
        "as_of": "2026-02-19T14:00:00Z",
        "total_value_usd": 50000.0,
        "cash_usd": 5000.0,
        "holdings": [
            {"asset_symbol": "BTC", "qty": 0.5, "usd_value": 45000.0, "current_price": 90000.0},
        ],
        "evidence_refs": {"accounts_call_id": "tc_1", "prices_call_ids": ["tc_2"]},
    }

    def test_passes_contract(self):
        result = format_asset_holdings_narrative("BTC", self.BRIEF)
        assert _check_contract(result) == []

    def test_contains_asset_qty_and_price(self):
        result = format_asset_holdings_narrative("BTC", self.BRIEF)
        assert "BTC" in result
        assert "0.50000000" in result
        assert "90,000" in result

    def test_zero_balance_asset(self):
        result = format_asset_holdings_narrative("SOL", self.BRIEF)
        assert "SOL" in result
        assert _check_contract(result) == []


class TestSimplePortfolioNarrative:

    def test_passes_contract(self):
        result = format_simple_portfolio_narrative(
            mode_str="PAPER", ts="2026-02-19T10:00:00Z",
            total_value=5000.0, cash_usd=1000.0,
            top_positions=[("BTC", 0.05), ("ETH", 1.0)],
        )
        assert _check_contract(result) == []

    def test_empty_positions(self):
        result = format_simple_portfolio_narrative(
            mode_str="PAPER", ts="2026-02-19T10:00:00Z",
            total_value=0.0, cash_usd=0.0, top_positions=[],
        )
        assert "no open positions" in result.lower()
        assert _check_contract(result) == []


class TestNoSnapshotNarrative:

    def test_live_passes_contract(self):
        result = format_no_snapshot_narrative("LIVE")
        assert _check_contract(result) == []
        assert "snapshot" in result.lower()

    def test_paper_passes_contract(self):
        result = format_no_snapshot_narrative("PAPER")
        assert _check_contract(result) == []


class TestSnapshotFailedNarrative:

    def test_passes_contract(self):
        result = format_snapshot_failed_narrative()
        assert _check_contract(result) == []
        assert "couldn't retrieve portfolio state" in result

    def test_with_reason(self):
        result = format_snapshot_failed_narrative("network timeout")
        assert "network timeout" in result
        assert _check_contract(result) == []


# ── Trade narratives ────────────────────────────────────────────────────


class TestTradeConfirmationNarrative:

    def test_passes_contract(self):
        result = format_trade_confirmation_narrative(
            actions_text="BUY $100.00 BTC",
            mode="PAPER",
            checks="1 valid",
            estimated_fees=0.60,
            evidence_items=[
                {"label": "Portfolio snapshot", "href": "url:/portfolio"},
                {"label": "Trade preflight", "href": "url:/runs"},
            ],
        )
        assert _check_contract(result) == []
        assert "confirm" in result.lower()
        assert "cancel" in result.lower()


class TestBuildTradeNarrative:

    def test_single_action(self):
        result = build_trade_narrative(
            interpretation="BUY $50 of ETH",
            actions=[{"side": "buy", "asset": "ETH", "amount_usd": 50.0}],
            mode="PAPER",
        )
        violations = _check_contract(result)
        assert violations == [], violations
        assert "BUY" in result
        assert "ETH" in result

    def test_sequential_multi_action(self):
        result = build_trade_narrative(
            interpretation="SELL full position of MOODENG and MORPHO",
            actions=[
                {"side": "sell", "asset": "MOODENG", "amount_usd": 100.0, "base_size": 50.0, "step_status": "READY"},
                {"side": "sell", "asset": "MORPHO", "amount_usd": 200.0, "base_size": 30.0, "step_status": "QUEUED"},
            ],
            is_sequential=True,
            mode="PAPER",
        )
        assert "sequential" in result.lower()
        assert "Step 1" in result
        assert "Step 2" in result
        assert "MOODENG" in result
        assert "MORPHO" in result
        violations = _check_contract(result)
        assert violations == [], violations

    def test_with_failures(self):
        result = build_trade_narrative(
            interpretation="SELL all BTC and ETH",
            actions=[{"side": "sell", "asset": "BTC", "amount_usd": 100.0}],
            failures=["Position not found in latest snapshot for ETH"],
            mode="PAPER",
        )
        assert "Skipped" in result
        assert "ETH" in result

    def test_no_forbidden_tokens(self):
        result = build_trade_narrative(
            interpretation="BUY $10 of BTC",
            actions=[{"side": "buy", "asset": "BTC", "amount_usd": 10.0}],
            mode="PAPER",
        )
        for line in result.split(PARAGRAPH_SEP):
            assert not FORBIDDEN_TOKENS.search(line)


class TestTradeExecutionNarrative:

    def test_passes_contract(self):
        result = format_trade_execution_narrative(
            side="buy", amount_usd=50.0, asset="ETH", run_id="run_abc123",
        )
        assert _check_contract(result) == []
        assert "BUY" in result
        assert "$50.00" in result
        assert "ETH" in result

    def test_no_pulled_prefix(self):
        result = format_trade_execution_narrative(
            side="sell", amount_usd=100.0, asset="BTC", run_id="run_xyz",
        )
        assert not result.startswith("Pulled the latest")


class TestMultiExecutionNarrative:

    def test_passes_contract(self):
        result = format_multi_execution_narrative(count=3, primary_run_id="run_xyz789")
        assert _check_contract(result) == []
        assert "3 orders" in result.lower()


class TestTradeBlockedNarrative:

    def test_passes_contract(self):
        result = format_trade_blocked_narrative(
            candidate_count=2,
            failures=["Position not found in latest snapshot", "Quantity unavailable"],
            evidence_items=[{"label": "Command parse trace", "href": "url:/chat"}],
        )
        assert _check_contract(result) == []

    def test_no_candidate_action_phrase(self):
        result = format_trade_blocked_narrative(
            candidate_count=1,
            failures=["Insufficient balance"],
            evidence_items=[{"label": "Details", "href": "url:/runs"}],
        )
        assert "candidate action" not in result


class TestNoParseNarrative:

    def test_passes_contract(self):
        result = format_no_parse_narrative()
        assert _check_contract(result) == []


class TestMissingAmountNarrative:

    def test_passes_contract(self):
        result = format_missing_amount_narrative("sell", "BTC")
        assert _check_contract(result) == []
        assert "SELL" in result
        assert "BTC" in result

    def test_no_asset(self):
        result = format_missing_amount_narrative("buy")
        assert _check_contract(result) == []
        assert "the asset" in result


# ── Structured output ──────────────────────────────────────────────────


class TestBuildNarrativeStructured:

    BRIEF = TestPortfolioNarrative.BRIEF

    def test_parses_valid_narrative(self):
        content = format_portfolio_narrative(self.BRIEF)
        structured = build_narrative_structured(content)
        assert "lead" in structured
        assert "lines" in structured
        assert "evidence" in structured
        assert len(structured["lines"]) >= 1
        assert len(structured["evidence"]) >= 2

    def test_evidence_has_label_and_ref(self):
        content = format_portfolio_narrative(self.BRIEF)
        structured = build_narrative_structured(content)
        for item in structured["evidence"]:
            assert "label" in item
            assert "ref" in item

    def test_fallback_from_brief(self):
        structured = build_narrative_structured("garbage text", brief=self.BRIEF)
        assert structured["lead"]
        assert len(structured["lines"]) >= 2
        assert len(structured["evidence"]) >= 2

    def test_minimal_fallback(self):
        structured = build_narrative_structured("garbage text")
        assert "lead" in structured
        assert "evidence" in structured
        assert len(structured["evidence"]) >= 2

    def test_no_artifact_refs(self):
        content = format_portfolio_narrative(self.BRIEF)
        structured = build_narrative_structured(content)
        for item in structured["evidence"]:
            ref = item["ref"]
            if isinstance(ref, str):
                assert not ref.startswith("artifact:")
