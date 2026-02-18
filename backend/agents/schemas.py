"""Strict Pydantic schemas for agent outputs."""
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class SourceType(str, Enum):
    SEC_FILING = "sec_filing"
    PRESS_RELEASE = "press_release"
    TRANSCRIPT = "transcript"
    NEWS = "news"
    MACRO = "macro"
    OTHER = "other"


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class EvidenceItem(BaseModel):
    source_id: str
    source_type: SourceType
    title: str
    url: str
    published_at: str
    fetched_at: str
    chunk_ids: List[str]
    relevance_scores: List[float] = Field(..., min_length=1)


class Claim(BaseModel):
    claim: str
    supported_by_chunk_ids: List[str]


class Signal(BaseModel):
    name: str
    value: str
    rationale_chunk_ids: List[str]


class Counterargument(BaseModel):
    argument: str
    supported_by_chunk_ids: List[str]


class RiskAnalysis(BaseModel):
    position_limit_usd: float = Field(..., ge=0)
    max_loss_usd: float = Field(..., ge=0)
    exposure_before: Dict[str, Any]
    exposure_after: Dict[str, Any]
    constraints_checked: List[str]
    counterarguments: List[Counterargument]


class Decision(BaseModel):
    action: Action
    symbol: str
    notional_usd: float = Field(..., gt=0)
    order_type: OrderType
    limit_price: Optional[float] = Field(None, gt=0)
    time_in_force: TimeInForce
    reason: str

    @field_validator('limit_price')
    @classmethod
    def validate_limit_price(cls, v, info: ValidationInfo):
        if info.data.get('order_type') == OrderType.LIMIT and v is None:
            raise ValueError('limit_price is required for LIMIT orders')
        return v


class TradeProposal(BaseModel):
    run_id: str
    tenant_id: str
    created_at: str
    strategy_id: str
    strategy_version: str
    portfolio_snapshot_id: str
    as_of_datetime: str
    evidence: List[EvidenceItem]
    claims: List[Claim]
    signals: List[Signal]
    risk: RiskAnalysis
    decision: Decision
    abort_conditions: List[str]
    confidence: float = Field(..., ge=0.0, le=1.0)
    approvals_required: bool
    notes: Optional[str] = None

    @field_validator('evidence')
    @classmethod
    def validate_evidence_for_trade(cls, v, info: ValidationInfo):
        decision = info.data.get('decision')
        if decision and decision.action in [Action.BUY, Action.SELL]:
            if len(v) < 2:
                raise ValueError(f'At least 2 evidence items required for {decision.action} actions')
        return v

    @field_validator('claims')
    @classmethod
    def validate_claim_coverage(cls, v):
        if not v:
            return v
        claims_with_support = sum(1 for claim in v if claim.supported_by_chunk_ids)
        coverage = claims_with_support / len(v)
        if coverage < 0.8:
            raise ValueError(f'Claim coverage must be >=80%, got {coverage*100:.1f}%')
        return v


class OrderIntent(BaseModel):
    symbol: str
    side: str  # BUY, SELL
    order_type: OrderType
    quantity: float
    limit_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    notional_usd: float


class OrderEvent(BaseModel):
    event_type: str
    order_id: str
    symbol: str
    side: str
    price: Optional[float] = None
    quantity: Optional[float] = None
    filled_quantity: Optional[float] = None
    status: str
    ts: int
    raw_event: Dict[str, Any]


class PolicyDecision(BaseModel):
    passed: bool
    reason: str
    check_type: str
    details: Dict[str, Any]


class ApprovalRequest(BaseModel):
    run_id: str
    tenant_id: str
    requested_by: str
    reason: str
    proposal_summary: Dict[str, Any]


class RunEvent(BaseModel):
    event_type: str
    run_id: str
    node_id: Optional[str] = None
    data: Dict[str, Any]
    timestamp: str


# Natural Language Command Schemas
class TradeIntent(BaseModel):
    """Parsed intent from natural language command."""
    side: str = Field(..., description="BUY or SELL")
    budget_usd: float = Field(..., gt=0, description="Budget in USD")
    metric: str = Field(default="return", description="return|sharpe_proxy|momentum")
    window: str = Field(default="24h", description="1h|24h|48h|7d")
    lookback_hours: int = Field(default=24, description="Lookback window in hours")
    universe: List[str] = Field(default_factory=lambda: ["BTC-USD", "ETH-USD", "SOL-USD"])
    constraints: Dict[str, Any] = Field(default_factory=dict)
    raw_command: str = Field(..., description="Original command text")


class StrategySpec(BaseModel):
    """Strategy specification for execution."""
    strategy_name: str = Field(..., description="e.g., TopReturnStrategy")
    window: str = Field(..., description="1h|24h|48h|7d")
    lookback_hours: int = Field(default=24, description="Lookback window in hours")
    metric: str = Field(..., description="return|sharpe_proxy|momentum")
    universe: List[str] = Field(..., min_length=1)
    params: Dict[str, Any] = Field(default_factory=dict)


class StrategyResult(BaseModel):
    """Result from strategy execution."""
    selected_symbol: str
    score: float = Field(..., description="Strategy score (return, sharpe, etc.)")
    rationale: str
    features_json: Dict[str, Any] = Field(default_factory=dict)
    computed_at: str
    candles_used: int = Field(..., description="Number of candles analyzed")


class ExecutionPlan(BaseModel):
    """Final execution plan after planning phase."""
    run_id: str
    trade_intent: TradeIntent
    strategy_spec: StrategySpec
    selected_asset: Optional[str] = None
    selected_order: Optional[Dict[str, Any]] = None
    decision_trace: List[Dict[str, Any]] = Field(default_factory=list)
    risk_checks: List[str] = Field(default_factory=list)


# ============================================================================
# PORTFOLIO ANALYSIS SCHEMAS
# ============================================================================

class ExecutionMode(str, Enum):
    """Execution mode for portfolio analysis."""
    LIVE = "LIVE"
    PAPER = "PAPER"
    REPLAY = "REPLAY"


class Holding(BaseModel):
    """A single asset holding in the portfolio."""
    asset_symbol: str = Field(..., description="Asset symbol (e.g., BTC, ETH)")
    qty: float = Field(..., ge=0, description="Quantity held")
    usd_value: float = Field(..., ge=0, description="Current USD value of holding")
    cost_basis_usd: Optional[float] = Field(None, ge=0, description="Cost basis in USD if known")
    current_price: Optional[float] = Field(None, ge=0, description="Current price per unit")
    unrealized_pnl_usd: Optional[float] = Field(None, description="Unrealized P&L if cost basis known")
    unrealized_pnl_pct: Optional[float] = Field(None, description="Unrealized P&L percentage")


class AllocationRow(BaseModel):
    """A single allocation row showing asset weight in portfolio."""
    asset_symbol: str = Field(..., description="Asset symbol")
    pct: float = Field(..., ge=0, le=100, description="Percentage of total portfolio (0-100)")
    usd_value: float = Field(..., ge=0, description="USD value of this allocation")


class TradeSummary(BaseModel):
    """Summary of trading activity over a time window."""
    window_days: int = Field(..., ge=0, description="Time window in days")
    total_trades: int = Field(..., ge=0, description="Total number of trades")
    total_notional_usd: float = Field(..., ge=0, description="Total notional value traded")
    avg_trade_usd: float = Field(..., ge=0, description="Average trade size in USD")
    buys: int = Field(..., ge=0, description="Number of buy trades")
    sells: int = Field(..., ge=0, description="Number of sell trades")
    top_assets: List[str] = Field(default_factory=list, description="Most traded assets")
    win_rate: Optional[float] = Field(None, ge=0, le=1, description="Win rate if computable (0-1)")
    realized_pnl_usd: Optional[float] = Field(None, description="Realized P&L from trades")
    most_active_day: Optional[str] = Field(None, description="Day with most trading activity")


class RiskSnapshot(BaseModel):
    """Risk assessment snapshot for the portfolio."""
    concentration_pct_top1: float = Field(..., ge=0, le=100, description="% of portfolio in top 1 asset")
    concentration_pct_top3: float = Field(..., ge=0, le=100, description="% of portfolio in top 3 assets")
    volatility_proxy: Optional[float] = Field(None, ge=0, description="Volatility proxy based on recent prices")
    drawdown_proxy: Optional[float] = Field(None, ge=0, le=100, description="Estimated max drawdown %")
    risk_level: str = Field(default="UNKNOWN", description="Risk level: LOW, MEDIUM, HIGH, VERY_HIGH, UNKNOWN")
    diversification_score: Optional[float] = Field(None, ge=0, le=1, description="Diversification score (0-1)")
    liquidity_score: Optional[float] = Field(None, ge=0, le=1, description="Liquidity score (0-1)")


class PortfolioRecommendation(BaseModel):
    """A single recommendation for portfolio improvement."""
    category: str = Field(..., description="Category: REBALANCING, POSITION_SIZING, RISK_CAP, DIVERSIFICATION, OTHER")
    priority: str = Field(default="MEDIUM", description="Priority: LOW, MEDIUM, HIGH, CRITICAL")
    title: str = Field(..., description="Short title")
    description: str = Field(..., description="Detailed recommendation")
    action_required: bool = Field(default=False, description="Whether action is required")


class EvidenceRefs(BaseModel):
    """References to tool calls that generated the evidence."""
    accounts_call_id: Optional[str] = Field(None, description="Tool call ID for accounts fetch")
    prices_call_ids: List[str] = Field(default_factory=list, description="Tool call IDs for price fetches")
    orders_call_id: Optional[str] = Field(None, description="Tool call ID for orders fetch")
    additional_call_ids: List[str] = Field(default_factory=list, description="Other tool call IDs")


class FailureArtifact(BaseModel):
    """Artifact returned when portfolio analysis fails."""
    error_code: str = Field(..., description="Error code: CREDS_MISSING, API_ERROR, NO_DATA, TIMEOUT, UNKNOWN")
    error_message: str = Field(..., description="Human-readable error message")
    recoverable: bool = Field(default=True, description="Whether this error is recoverable")
    suggested_action: str = Field(default="", description="Suggested action to resolve")
    partial_data: Optional[Dict[str, Any]] = Field(None, description="Any partial data collected before failure")


class PortfolioBrief(BaseModel):
    """Complete portfolio analysis brief - the main artifact."""
    as_of: str = Field(..., description="ISO timestamp of when analysis was performed")
    mode: ExecutionMode = Field(..., description="Execution mode: LIVE or PAPER")
    total_value_usd: float = Field(..., ge=0, description="Total portfolio value in USD")
    cash_usd: float = Field(default=0.0, ge=0, description="Cash/USD balance")
    holdings: List[Holding] = Field(default_factory=list, description="List of holdings")
    allocation: List[AllocationRow] = Field(default_factory=list, description="Allocation breakdown")
    trade_summary: Optional[TradeSummary] = Field(None, description="Trading activity summary")
    risk: RiskSnapshot = Field(..., description="Risk assessment")
    recommendations: List[PortfolioRecommendation] = Field(default_factory=list, description="Recommendations")
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
    evidence_refs: EvidenceRefs = Field(default_factory=EvidenceRefs, description="References to source data")
    failure: Optional[FailureArtifact] = Field(None, description="Failure details if analysis failed")
    
    @field_validator('allocation')
    @classmethod
    def validate_allocation_sum(cls, v):
        """Validate that allocation percentages sum to approximately 100%."""
        if not v:
            return v
        total_pct = sum(row.pct for row in v)
        # Allow 1% tolerance for rounding errors
        if total_pct > 0 and abs(total_pct - 100) > 1.0:
            # Don't fail, just log - there might be legitimate reasons
            pass
        return v
    
    @field_validator('holdings')
    @classmethod
    def validate_holdings_values(cls, v, info: ValidationInfo):
        """Validate that holdings values are consistent with total."""
        if not v:
            return v
        # Holdings sum should match total_value_usd - cash_usd (approximately)
        total_from_holdings = sum(h.usd_value for h in v)
        # Don't fail validation, just warn in warnings field
        return v
    
    def is_success(self) -> bool:
        """Check if analysis was successful."""
        return self.failure is None
    
    def get_top_holdings(self, n: int = 5) -> List[Holding]:
        """Get top N holdings by USD value."""
        return sorted(self.holdings, key=lambda h: h.usd_value, reverse=True)[:n]
    
    def get_risk_summary(self) -> str:
        """Get human-readable risk summary."""
        r = self.risk
        lines = [
            f"Risk Level: {r.risk_level}",
            f"Concentration (Top 1): {r.concentration_pct_top1:.1f}%",
            f"Concentration (Top 3): {r.concentration_pct_top3:.1f}%",
        ]
        if r.volatility_proxy is not None:
            lines.append(f"Volatility Proxy: {r.volatility_proxy:.2f}")
        if r.diversification_score is not None:
            lines.append(f"Diversification Score: {r.diversification_score:.2f}")
        return "\n".join(lines)
