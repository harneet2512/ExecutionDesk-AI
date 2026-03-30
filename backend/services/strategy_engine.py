"""Strategy engine - computes returns and selects top assets."""
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from backend.core.logging import get_logger
from backend.agents.schemas import StrategyResult
from backend.core.time import now_iso

logger = get_logger(__name__)


def compute_returns(candles: List[Dict[str, Any]]) -> float:
    """Compute return from candles (last close - first open) / first open.
    
    Uses first_open as the baseline price since that's what you would have
    paid at the start of the period. This is consistent with 
    coinbase_market_data.compute_return_24h and asset_selection_engine._compute_return.
    """
    if len(candles) < 2:
        return 0.0
    
    first_open = float(candles[0]["open"])
    last_close = float(candles[-1]["close"])
    
    if first_open == 0:
        return 0.0
    
    return (last_close - first_open) / first_open


def compute_sharpe_proxy(candles: List[Dict[str, Any]]) -> float:
    """Compute simplified Sharpe proxy: return / volatility."""
    if len(candles) < 2:
        return 0.0
    
    returns = []
    for i in range(1, len(candles)):
        prev_close = float(candles[i-1]["close"])
        curr_close = float(candles[i]["close"])
        if prev_close > 0:
            ret = (curr_close - prev_close) / prev_close
            returns.append(ret)
    
    if not returns:
        return 0.0
    
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    volatility = variance ** 0.5
    
    if volatility == 0:
        return 0.0
    
    # Annualized Sharpe proxy (simplified)
    return mean_return / volatility


def compute_momentum(candles: List[Dict[str, Any]]) -> float:
    """Compute momentum: rate of change over window."""
    if len(candles) < 2:
        return 0.0
    
    first_close = float(candles[0]["close"])
    last_close = float(candles[-1]["close"])
    
    if first_close == 0:
        return 0.0
    
    # Normalized by number of candles
    return (last_close - first_close) / first_close / len(candles)


def select_top_asset(
    universe: List[str],
    window: str,
    metric: str,
    candles_by_symbol: Dict[str, List[Dict[str, Any]]]
) -> Optional[StrategyResult]:
    """
    Select top asset based on metric.
    
    Args:
        universe: List of symbols to evaluate
        window: Time window (1h, 24h, 7d)
        metric: return|sharpe_proxy|momentum
        candles_by_symbol: Dict mapping symbol -> list of candles
    
    Returns:
        StrategyResult with selected symbol and score
    """
    scores = []
    
    for symbol in universe:
        candles = candles_by_symbol.get(symbol, [])
        if len(candles) < 2:
            logger.warning(f"Insufficient candles for {symbol}: {len(candles)}")
            continue
        
        # Compute metric
        if metric == "return":
            score = compute_returns(candles)
        elif metric == "sharpe_proxy":
            score = compute_sharpe_proxy(candles)
        elif metric == "momentum":
            score = compute_momentum(candles)
        else:
            logger.warning(f"Unknown metric: {metric}, using return")
            score = compute_returns(candles)
        
        scores.append({
            "symbol": symbol,
            "score": score,
            "candles_count": len(candles)
        })
    
    if not scores:
        logger.error("No valid scores computed")
        return None
    
    # Sort by score (descending)
    scores.sort(key=lambda x: x["score"], reverse=True)
    
    top = scores[0]
    top_symbol = top["symbol"]
    top_score = top["score"]
    top_candles = candles_by_symbol.get(top_symbol, [])
    
    # Generate rationale
    rationale = f"Selected {top_symbol} based on {metric} metric (score: {top_score:.4f}). "
    rationale += f"Analyzed {len(scores)} assets over {window} window. "
    if top_candles:
        first_price = float(top_candles[0]["close"])
        last_price = float(top_candles[-1]["close"])
        rationale += f"Price moved from ${first_price:.2f} to ${last_price:.2f}."
    
    features = {
        "scores": scores[:5],  # Top 5
        "metric": metric,
        "window": window,
        "universe_size": len(universe)
    }
    
    return StrategyResult(
        selected_symbol=top_symbol,
        score=top_score,
        rationale=rationale,
        features_json=features,
        computed_at=now_iso(),
        candles_used=len(top_candles)
    )
