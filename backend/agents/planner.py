"""Planner agent - converts TradeIntent into StrategySpec and ExecutionPlan."""
from typing import Dict, Any
from backend.agents.schemas import TradeIntent, StrategySpec, ExecutionPlan
from backend.core.logging import get_logger
from backend.core.ids import new_id
from backend.core.time import now_iso

logger = get_logger(__name__)


def plan_execution(trade_intent: TradeIntent, run_id: str) -> ExecutionPlan:
    """
    Convert TradeIntent into ExecutionPlan with StrategySpec.
    
    Strategy selection:
    - "return" metric -> TopReturnStrategy
    - "sharpe_proxy" metric -> SharpeOptimizedStrategy
    - "momentum" metric -> MomentumStrategy
    """
    # Create strategy spec based on metric
    strategy_name = f"Top{trade_intent.metric.capitalize()}Strategy"
    if trade_intent.metric == "return":
        strategy_name = "TopReturnStrategy"
    elif trade_intent.metric == "sharpe_proxy":
        strategy_name = "SharpeOptimizedStrategy"
    elif trade_intent.metric == "momentum":
        strategy_name = "MomentumStrategy"
    
    strategy_spec = StrategySpec(
        strategy_name=strategy_name,
        window=trade_intent.window,
        lookback_hours=trade_intent.lookback_hours,
        metric=trade_intent.metric,
        universe=trade_intent.universe,
        params={
            "budget_usd": trade_intent.budget_usd,
            "side": trade_intent.side,
            **trade_intent.constraints
        }
    )
    
    # Decision trace
    decision_trace = [
        {
            "step": "parse_command",
            "input": trade_intent.raw_command,
            "output": trade_intent.dict(),
            "timestamp": now_iso()
        },
        {
            "step": "create_strategy_spec",
            "strategy": strategy_name,
            "params": strategy_spec.params,
            "timestamp": now_iso()
        }
    ]
    
    # Risk checks (basic)
    risk_checks = []
    if trade_intent.budget_usd > 1000:
        risk_checks.append("budget_exceeds_1000_usd")
    if len(trade_intent.universe) < 2:
        risk_checks.append("universe_too_small")
    
    execution_plan = ExecutionPlan(
        run_id=run_id,
        trade_intent=trade_intent,
        strategy_spec=strategy_spec,
        decision_trace=decision_trace,
        risk_checks=risk_checks
    )
    
    return execution_plan
