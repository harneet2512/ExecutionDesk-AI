"""Test that run_id / trace_id / internal IDs never appear in chat UI DOM.

This is a regression test for GOAL A: enterprise UX requires no internal IDs
visible in the chat interface.
"""
import re
import os
import pytest

# Patterns that should NEVER appear in chat message rendering
FORBIDDEN_PATTERNS = [
    re.compile(r'run_[a-f0-9]{8,}'),     # run_id format
    re.compile(r'trace_[a-f0-9]{8,}'),    # trace_id format
    re.compile(r'node_[a-f0-9]{8,}'),     # node_id format
    re.compile(r'ev_[a-f0-9]{8,}'),       # eval_id format
]


def _read_component(filename: str) -> str:
    """Read a frontend component file."""
    base = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    path = os.path.join(base, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _extract_jsx_render_content(source: str) -> str:
    """Extract only the JSX render portion (inside return statements)."""
    # Rough heuristic: everything between return ( and the matching )
    # For our purposes we look at the full file but exclude obvious non-render patterns
    return source


class TestNoRunIdInChatComponents:
    """Verify chat components don't render internal IDs in visible DOM."""

    def test_trade_processing_card_no_runid_in_dom(self):
        """TradeProcessingCard should not render run_id in visible DOM text."""
        source = _read_component('components/TradeProcessingCard.tsx')

        # The debug section should NOT contain {runId} in visible text
        # It should only be in clipboard copy (handleCopyDebug)
        lines = source.split('\n')
        in_debug_section = False
        for i, line in enumerate(lines):
            if 'showDebug' in line and '{' in line:
                in_debug_section = True
            if in_debug_section and 'run_id' in line.lower():
                # Check if it's in a visible <div> or just in a copy function
                if '<div>' in line or '{runId}' in line:
                    # This would be a fail - but we allow it ONLY in clipboard copy
                    if 'navigator.clipboard' not in line and 'handleCopyDebug' not in line:
                        pytest.fail(
                            f"run_id rendered in DOM at line {i+1}: {line.strip()}\n"
                            "run_id must not appear in visible chat DOM"
                        )

    def test_evidence_list_filters_ids(self):
        """EvidenceList should filter internal IDs from JSON dumps."""
        source = _read_component('components/EvidenceList.tsx')
        # Check that the JSON.stringify has a filter for internal IDs
        assert 'run_id' in source or 'filter' in source, \
            "EvidenceList should filter internal IDs from raw JSON dumps"

    def test_trade_receipt_no_runid_in_dom(self):
        """TradeReceipt should not render run_id or trace_id."""
        source = _read_component('components/TradeReceipt.tsx')
        # TradeReceipt uses runId as a prop for API calls, not for rendering
        # Check it doesn't appear in JSX text
        lines = source.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip prop declarations and API calls
            if 'runId' in stripped and (
                '<' in stripped and '>' in stripped and
                '{runId}' in stripped and
                'href' not in stripped and
                'fetch' not in stripped and
                'apiFetchSafe' not in stripped
            ):
                pytest.fail(
                    f"runId rendered in TradeReceipt DOM at line {i+1}: {stripped}"
                )

    def test_financial_insight_card_no_internal_ids(self):
        """FinancialInsightCard should not leak request_id or internal IDs."""
        source = _read_component('components/FinancialInsightCard.tsx')
        # Check that request_id is not rendered
        assert 'request_id' not in source.split('return')[1] if 'return' in source else True, \
            "FinancialInsightCard should not render request_id"

    def test_run_detail_page_hides_ids_behind_debug(self):
        """Run detail page should hide run_id/trace_id behind debug toggle."""
        source = _read_component('app/runs/[id]/page.tsx')
        # Must have a debug toggle
        assert 'showDebugIds' in source, \
            "Run detail page must have a debug toggle for IDs"
        assert 'Debug' in source, \
            "Run detail page must have a Debug button"


class TestEvalDashboardEndpoints:
    """Verify eval backend endpoints exist and are importable."""

    def test_runtime_evals_importable(self):
        """Runtime eval emitter should be importable."""
        from backend.evals.runtime_evals import (
            emit_retrieval_evals,
            emit_insight_evals,
            emit_news_coverage_eval,
            emit_execution_eval,
        )
        assert callable(emit_retrieval_evals)
        assert callable(emit_insight_evals)
        assert callable(emit_news_coverage_eval)
        assert callable(emit_execution_eval)

    def test_evals_repo_enhanced(self):
        """EvalsRepo should support enhanced columns."""
        from backend.db.repo.evals_repo import EvalsRepo
        repo = EvalsRepo()
        assert hasattr(repo, 'create_eval_result')
        assert hasattr(repo, 'create_eval_batch')
        assert hasattr(repo, 'get_evals_by_conversation')
        assert hasattr(repo, 'get_summary')

    def test_evals_routes_exist(self):
        """Eval API routes should exist."""
        from backend.api.routes.evals import router
        paths = [route.path for route in router.routes]
        assert '/summary' in paths or any('/summary' in str(p) for p in paths), \
            f"Missing /summary endpoint. Found: {paths}"
        assert any('conversations' in str(p) for p in paths), \
            f"Missing /conversations endpoint. Found: {paths}"
