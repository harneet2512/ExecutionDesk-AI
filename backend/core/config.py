"""Configuration management."""
import os
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv(override=False)


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Ignore extra environment variables
    )
    
    # Database
    database_url: str = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL", "sqlite:///./enterprise.db")
    test_database_url: Optional[str] = os.getenv("TEST_DATABASE_URL")
    
    # API
    api_secret_key: str = os.getenv("API_SECRET_KEY", "dev-secret-key-change-in-production")
    
    # JWT Authentication
    jwt_secret: str = os.getenv("JWT_SECRET", os.getenv("API_SECRET_KEY", "dev-jwt-secret-change-in-production"))
    jwt_issuer: str = os.getenv("JWT_ISSUER", "executivedesk-ai")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "executivedesk-ai")
    jwt_exp_minutes: int = int(os.getenv("JWT_EXP_MINUTES", "60"))
    
    # Dev Auth (demo-only)
    enable_dev_auth: bool = os.getenv("ENABLE_DEV_AUTH", "false").lower() == "true"
    
    # Test Auth Bypass (pytest only)
    test_auth_bypass: bool = os.getenv("PYTEST_CURRENT_TEST", "").strip() != "" and os.getenv("TEST_AUTH_BYPASS", "false").lower() == "true"
    
    # Governance
    kill_switch_enabled: bool = os.getenv("KILL_SWITCH_ENABLED", "false").lower() == "true"
    symbol_allowlist: str = os.getenv("SYMBOL_ALLOWLIST", "BTC,ETH,SOL")
    max_notional_per_order_usd: float = float(os.getenv("MAX_NOTIONAL_PER_ORDER_USD", "10.0"))
    max_trades_per_run: int = int(os.getenv("MAX_TRADES_PER_RUN", "3"))
    min_citations_required: int = int(os.getenv("MIN_CITATIONS_REQUIRED", "1"))
    
    # Execution
    execution_mode_default: str = os.getenv("EXECUTION_MODE_DEFAULT", "PAPER")
    force_paper_mode: bool = os.getenv("FORCE_PAPER_MODE", "false").lower() == "true"
    execution_timeout_seconds: int = int(os.getenv("EXECUTION_TIMEOUT_SECONDS", "60"))  # Hard timeout for run execution
    
    # Market Data (Coinbase only - stub mode removed)
    market_data_mode: str = os.getenv("MARKET_DATA_MODE", "coinbase")  # Only "coinbase" supported

    def validate_market_data_mode(self) -> None:
        """Validate market_data_mode is 'coinbase'. Called at startup."""
        if self.market_data_mode != "coinbase":
            raise ValueError(
                f"Invalid MARKET_DATA_MODE='{self.market_data_mode}'. "
                f"Only 'coinbase' is supported. Stub/mock modes have been removed."
            )
    polygon_api_key: Optional[str] = os.getenv("POLYGON_API_KEY")

    # Stock Data Provider (Polygon.io Free Tier)
    stock_data_provider: str = os.getenv("STOCK_DATA_PROVIDER", "polygon")
    stock_rate_limit_per_minute: int = int(os.getenv("STOCK_RATE_LIMIT_PER_MINUTE", "5"))
    stock_watchlist: str = os.getenv("STOCK_WATCHLIST", "AAPL,MSFT,NVDA,TSLA,SPY")
    stock_max_symbols_per_run: int = int(os.getenv("STOCK_MAX_SYMBOLS_PER_RUN", "5"))
    stock_execution_mode: str = os.getenv("STOCK_EXECUTION_MODE", "ASSISTED_LIVE")
    stock_ticket_ttl_hours: int = int(os.getenv("STOCK_TICKET_TTL_HOURS", "24"))
    stock_lookback_days_default: int = int(os.getenv("STOCK_LOOKBACK_DAYS_DEFAULT", "10"))

    @property
    def stock_watchlist_list(self) -> list:
        """Parse stock watchlist into list of symbols."""
        return [s.strip().upper() for s in self.stock_watchlist.split(",") if s.strip()]

    coinbase_api_key: Optional[str] = os.getenv("COINBASE_API_KEY")  # Legacy (deprecated)
    coinbase_api_secret: Optional[str] = os.getenv("COINBASE_API_SECRET")  # Legacy (deprecated)
    
    # Coinbase CDP (Advanced Trade)
    coinbase_api_key_name: Optional[str] = os.getenv("COINBASE_API_KEY_NAME")  # CDP API key name/ID
    coinbase_api_private_key: Optional[str] = os.getenv("COINBASE_API_PRIVATE_KEY")  # CDP private key (PEM, ES256)
    coinbase_api_private_key_path: Optional[str] = os.getenv("COINBASE_API_PRIVATE_KEY_PATH")  # Path to PEM file (recommended)
    
    # Live Trading
    enable_live_trading: bool = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
    live_max_notional_usd: float = float(os.getenv("LIVE_MAX_NOTIONAL_USD", "20.0"))  # Hard cap for LIVE orders

    # S1: Master LIVE trading kill switch (default ON = LIVE trades disabled)
    # Set TRADING_DISABLE_LIVE=false to allow LIVE trades (requires enable_live_trading too)
    trading_disable_live: bool = os.getenv("TRADING_DISABLE_LIVE", "true").lower() != "false"
    
    # Demo Safe Mode - BLOCKS ALL LIVE EXECUTIONS (crypto and stocks)
    # When enabled, the system will:
    # - Block any LIVE crypto order with reason_code=DEMO_MODE_LIVE_BLOCKED
    # - Allow PAPER trades and ASSISTED_LIVE ticket generation
    # - Still exercise the full NLP pipeline end-to-end
    demo_safe_mode: bool = os.getenv("DEMO_SAFE_MODE", "0") in ("1", "true", "True", "TRUE")
    
    def is_live_execution_allowed(self) -> bool:
        """Check if LIVE execution is allowed. Returns False in DEMO_SAFE_MODE."""
        if self.demo_safe_mode:
            return False
        return self.enable_live_trading
    
    # Pushover Notifications
    pushover_enabled: bool = os.getenv("PUSHOVER_ENABLED", "false").lower() == "true"
    pushover_app_token: Optional[str] = os.getenv("PUSHOVER_APP_TOKEN")
    pushover_user_key: Optional[str] = os.getenv("PUSHOVER_USER_KEY")
    
    # OpenTelemetry
    service_name: str = os.getenv("SERVICE_NAME", "executivedesk-ai")
    service_version: str = os.getenv("SERVICE_VERSION", "0.1.0")
    otlp_endpoint: Optional[str] = os.getenv("OTLP_ENDPOINT")
    
    # OpenAI (optional, for LLM features)
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # Cheapest cost-effective model

    # E2E diagnostics: prints run_id/request_id to logs for Playwright correlation
    debug_trade_diagnostics: bool = os.getenv("DEBUG_TRADE_DIAGNOSTICS", "0").lower() in ("1", "true", "yes")


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings singleton. Used for test isolation."""
    global _settings
    _settings = None


settings = get_settings()
