"""Tests for the eval definitions registry."""
import pytest
from backend.evals.eval_definitions import (
    EVAL_DEFINITIONS,
    get_definition,
    get_all_definitions,
)

REQUIRED_FIELDS = {"title", "description", "category", "rubric", "how_to_improve", "threshold", "evaluator_type"}
VALID_CATEGORIES = {"rag", "safety", "quality", "compliance", "performance", "data"}


def test_all_definitions_have_required_fields():
    for name, defn in EVAL_DEFINITIONS.items():
        missing = REQUIRED_FIELDS - set(defn.keys())
        assert not missing, f"{name} missing fields: {missing}"


def test_thresholds_in_valid_range():
    for name, defn in EVAL_DEFINITIONS.items():
        t = defn["threshold"]
        assert 0.0 <= t <= 1.0, f"{name} threshold {t} out of [0, 1]"


def test_categories_are_valid():
    for name, defn in EVAL_DEFINITIONS.items():
        assert defn["category"] in VALID_CATEGORIES, (
            f"{name} has invalid category '{defn['category']}'"
        )


def test_how_to_improve_is_list():
    for name, defn in EVAL_DEFINITIONS.items():
        assert isinstance(defn["how_to_improve"], list), (
            f"{name} how_to_improve must be list, got {type(defn['how_to_improve'])}"
        )


def test_get_definition_known():
    defn = get_definition("schema_validity")
    assert defn["title"] == "Schema Validity"
    assert defn["category"] == "data"


def test_get_definition_unknown_fallback():
    defn = get_definition("some_unknown_eval")
    assert "Unknown" in defn["title"] or "unknown" in defn["title"].lower() or "Some" in defn["title"]
    assert "threshold" in defn
    assert defn["evaluator_type"] == "unknown"


def test_get_all_definitions_returns_dict():
    all_defs = get_all_definitions()
    assert isinstance(all_defs, dict)
    assert len(all_defs) >= 30  # We have 40+ definitions


def test_eval_node_names_have_definitions():
    """All eval names from eval_node.py should have definitions."""
    known_names = [
        "schema_validity", "policy_compliance", "citation_coverage",
        "execution_correctness", "tool_error_rate", "end_to_end_latency",
        "policy_decision_present", "action_grounding", "budget_compliance",
        "ranking_correctness", "numeric_grounding", "execution_quality",
        "tool_reliability", "determinism_replay", "policy_invariants",
        "ux_completeness", "intent_parse_correctness", "plan_completeness",
        "evidence_sufficiency", "risk_gate_compliance", "latency_slo",
        "hallucination_detection", "agent_quality", "news_freshness",
        "cluster_dedup_score", "prompt_injection_resistance",
        "market_evidence_integrity", "data_freshness", "rate_limit_resilience",
        "portfolio_grounding", "news_evidence_integrity",
        "faithfulness", "answer_relevance", "retrieval_relevance",
        "news_coverage", "news_freshness_eval", "sentiment_consistency",
        "profit_ranking_correctness", "time_window_correctness",
        "live_trade_truthfulness", "confirm_trade_idempotency",
        "coinbase_data_integrity",
    ]
    for name in known_names:
        defn = get_definition(name)
        assert defn["evaluator_type"] != "unknown", (
            f"{name} not in EVAL_DEFINITIONS registry"
        )
