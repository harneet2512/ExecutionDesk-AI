"""Evaluation modules."""
from backend.evals.action_grounding import evaluate_action_grounding
from backend.evals.budget_compliance import evaluate_budget_compliance
from backend.evals.ranking_correctness import evaluate_ranking_correctness
from backend.evals.numeric_grounding import evaluate_numeric_grounding
from backend.evals.execution_quality import evaluate_execution_quality
from backend.evals.tool_reliability import evaluate_tool_reliability
from backend.evals.determinism_replay import evaluate_determinism_replay
from backend.evals.policy_invariants import evaluate_policy_invariants
from backend.evals.ux_completeness import evaluate_ux_completeness
from backend.evals.intent_parse_correctness import evaluate_intent_parse_correctness
from backend.evals.plan_completeness import evaluate_plan_completeness
from backend.evals.evidence_sufficiency import evaluate_evidence_sufficiency
from backend.evals.risk_gate_compliance import evaluate_risk_gate_compliance
from backend.evals.latency_slo import evaluate_latency_slo
from backend.evals.hallucination_detection import evaluate_hallucination_detection
from backend.evals.agent_quality import evaluate_agent_quality
from backend.evals.news_freshness import evaluate_news_freshness
from backend.evals.cluster_dedup import evaluate_cluster_dedup
from backend.evals.prompt_injection_resistance import evaluate_prompt_injection_resistance

__all__ = [
    "evaluate_action_grounding",
    "evaluate_budget_compliance",
    "evaluate_ranking_correctness",
    "evaluate_numeric_grounding",
    "evaluate_execution_quality",
    "evaluate_tool_reliability",
    "evaluate_determinism_replay",
    "evaluate_policy_invariants",
    "evaluate_ux_completeness",
    "evaluate_intent_parse_correctness",
    "evaluate_plan_completeness",
    "evaluate_evidence_sufficiency",
    "evaluate_risk_gate_compliance",
    "evaluate_latency_slo",
    "evaluate_hallucination_detection",
    "evaluate_agent_quality",
    "evaluate_news_freshness",
    "evaluate_cluster_dedup",
    "evaluate_prompt_injection_resistance",
]
