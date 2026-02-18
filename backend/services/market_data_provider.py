"""Market data provider factory.

Supports multiple asset classes:
- CRYPTO: Coinbase market data (default)
- STOCK: Polygon.io market data (EOD)

For tests, mock the HTTP layer or use pytest fixtures.
"""
from backend.providers.market_data_base import MarketDataProvider
from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.core.test_utils import is_pytest

logger = get_logger(__name__)


class MarketDataCredentialsError(Exception):
    """Raised when market data credentials are missing."""
    pass


def has_coinbase_creds() -> bool:
    """Check if Coinbase credentials are present."""
    settings = get_settings()
    # Check for CDP credentials (new format)
    if settings.coinbase_api_key_name and settings.coinbase_api_private_key:
        return True
    # Check for legacy credentials
    if settings.coinbase_api_key and settings.coinbase_api_secret:
        return True
    return False


def has_polygon_creds() -> bool:
    """Check if Polygon credentials are present."""
    settings = get_settings()
    return bool(settings.polygon_api_key)


def get_market_data_provider(asset_class: str = "CRYPTO") -> MarketDataProvider:
    """
    Get market data provider based on asset class.

    Args:
        asset_class: "CRYPTO" (default) or "STOCK"

    Rules:
    - CRYPTO: Returns CoinbaseMarketDataProvider (requires Coinbase credentials)
    - STOCK: Returns PolygonMarketDataProvider (requires Polygon API key)
    - In pytest, allows provider creation but tests must mock HTTP calls
    - Fails with explicit error if credentials missing

    Raises:
        MarketDataCredentialsError: If required credentials are missing (outside pytest)
    """
    settings = get_settings()
    asset_class = asset_class.upper()

    # === STOCK path (Polygon.io) ===
    if asset_class == "STOCK":
        from backend.providers.polygon_market_data import PolygonMarketDataProvider

        # In pytest, allow provider creation but tests must mock HTTP
        if is_pytest():
            logger.info("Creating PolygonMarketDataProvider in pytest (tests must mock HTTP)")
            return PolygonMarketDataProvider()

        # Production: require Polygon API key
        if not has_polygon_creds():
            error_msg = (
                "Polygon API key required for stock market data. "
                "Set POLYGON_API_KEY in .env file. "
                "Free tier: 5 API calls/min, EOD data only."
            )
            logger.error(error_msg)
            raise MarketDataCredentialsError(error_msg)

        logger.info("Using PolygonMarketDataProvider with credentials")
        return PolygonMarketDataProvider()

    # === CRYPTO path (Coinbase) - default ===
    from backend.providers.coinbase_market_data import CoinbaseMarketDataProvider

    # In pytest, allow provider creation but tests must mock HTTP calls
    if is_pytest():
        logger.info("Creating CoinbaseMarketDataProvider in pytest (tests must mock HTTP)")
        return CoinbaseMarketDataProvider()

    # Production: require credentials
    if not has_coinbase_creds():
        error_msg = (
            "Coinbase credentials required for market data. "
            "Set COINBASE_API_KEY_NAME and COINBASE_API_PRIVATE_KEY in .env file. "
            "See .env.example for format."
        )
        logger.error(error_msg)
        raise MarketDataCredentialsError(error_msg)

    logger.info("Using CoinbaseMarketDataProvider with credentials")
    return CoinbaseMarketDataProvider()
