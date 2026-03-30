"""Import smoke tests.

Ensures all key backend modules can be imported without errors.
Catches broken imports (e.g., the historical ``backend.core.time_utils``
issue) before they reach production.
"""
import importlib
import pytest


# All modules that must be importable for the platform to function.
REQUIRED_MODULES = [
    # Core
    "backend.core.config",
    "backend.core.time",
    "backend.core.ids",
    "backend.core.logging",
    "backend.core.error_codes",
    "backend.core.symbols",
    "backend.core.security",
    "backend.core.redaction",
    # State machine
    "backend.orchestrator.state_machine",
    "backend.orchestrator.runner",
    "backend.orchestrator.event_emitter",
    "backend.orchestrator.event_pubsub",
    # Execution nodes
    "backend.orchestrator.nodes.execution_node",
    "backend.orchestrator.nodes.news_node",
    "backend.orchestrator.nodes.research_node",
    "backend.orchestrator.nodes.signals_node",
    "backend.orchestrator.nodes.risk_node",
    "backend.orchestrator.nodes.proposal_node",
    "backend.orchestrator.nodes.policy_check_node",
    "backend.orchestrator.nodes.approval_node",
    "backend.orchestrator.nodes.post_trade_node",
    "backend.orchestrator.nodes.eval_node",
    # Services
    "backend.services.pre_confirm_insight",
    "backend.services.news_brief",
    "backend.services.market_data",
    "backend.services.market_metadata",
    "backend.services.conversation_state",
    # DB
    "backend.db.connect",
    "backend.db.repo.trade_confirmations_repo",
    "backend.db.repo.runs_repo",
    "backend.db.repo.orders_repo",
    # Agents
    "backend.agents.schemas",
    "backend.agents.intent_parser",
    "backend.agents.trade_parser",
    # Providers
    "backend.providers.paper",
    "backend.providers.coinbase_provider",
    "backend.providers.news.rss_provider",
    "backend.providers.news.gdelt_provider",
    # API
    "backend.api.main",
    "backend.api.routes.chat",
    "backend.api.routes.confirmations",
    "backend.api.routes.runs",
    "backend.api.routes.news",
    "backend.api.routes.ops",
    "backend.api.routes.evals",
    # Evals
    "backend.evals.rag_evals",
]


@pytest.mark.parametrize("module_path", REQUIRED_MODULES)
def test_import_module(module_path: str):
    """Each required module should import without ImportError."""
    mod = importlib.import_module(module_path)
    assert mod is not None, f"Module {module_path} imported as None"


def test_no_time_utils_module():
    """backend.core.time_utils must NOT exist (historical regression)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("backend.core.time_utils")


def test_state_machine_enums():
    """Verify state machine enums are importable and have expected values."""
    from backend.orchestrator.state_machine import (
        RunStatus,
        ConfirmationStatus,
        NodeStatus,
        TERMINAL_RUN_STATUSES,
    )
    assert RunStatus.COMPLETED in TERMINAL_RUN_STATUSES
    assert RunStatus.FAILED in TERMINAL_RUN_STATUSES
    assert ConfirmationStatus.PENDING.value == "PENDING"
    assert ConfirmationStatus.CONFIRMED.value == "CONFIRMED"
    assert NodeStatus.RUNNING.value == "RUNNING"
