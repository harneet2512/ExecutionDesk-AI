"""Tests for unified NLP - trade parser with crypto and stock support."""
import pytest
from backend.agents.trade_parser import (
    parse_trade_command,
    ParsedTradeCommand,
    CRYPTO_SYMBOLS,
    STOCK_SYMBOLS,
    CRYPTO_KEYWORDS,
    STOCK_KEYWORDS
)


class TestAssetClassDetection:
    """Test asset class detection from symbols and keywords.

    Note: In pytest environment, mode defaults to PAPER for safety.
    Asset class detection is independent of execution mode.
    """

    def test_crypto_by_symbol(self):
        """Crypto symbols should be detected as CRYPTO."""
        result = parse_trade_command("Buy $50 of BTC")
        assert result.asset == "BTC"
        assert result.asset_class == "CRYPTO"
        # In pytest, mode defaults to PAPER (safety first)
        assert result.mode == "PAPER"

    def test_crypto_by_full_name(self):
        """Crypto full names should map to symbols."""
        result = parse_trade_command("Buy $50 of Bitcoin")
        assert result.asset == "BTC"
        assert result.asset_class == "CRYPTO"

    def test_stock_by_symbol(self):
        """Stock symbols should be detected as STOCK."""
        result = parse_trade_command("Buy $50 of AAPL")
        assert result.asset == "AAPL"
        assert result.asset_class == "STOCK"
        # In pytest, mode defaults to PAPER (overrides ASSISTED_LIVE)
        assert result.mode == "PAPER"

    def test_stock_by_company_name(self):
        """Company names should map to stock symbols."""
        result = parse_trade_command("Buy $100 of Apple")
        assert result.asset == "AAPL"
        assert result.asset_class == "STOCK"

    def test_stock_with_keyword(self):
        """'stock' keyword should force STOCK classification."""
        result = parse_trade_command("Buy $50 of NVDA stock")
        assert result.asset == "NVDA"
        assert result.asset_class == "STOCK"
        # In pytest, mode defaults to PAPER
        assert result.mode == "PAPER"

    def test_crypto_with_keyword(self):
        """'crypto' keyword should force CRYPTO classification."""
        result = parse_trade_command("Buy $50 of ETH crypto")
        assert result.asset == "ETH"
        assert result.asset_class == "CRYPTO"

    def test_ambiguous_both_keywords(self):
        """Both crypto and stock keywords present should be AMBIGUOUS."""
        result = parse_trade_command("Buy $50 crypto stock")
        assert result.asset_class == "AMBIGUOUS"

    def test_unknown_symbol_defaults_to_crypto(self):
        """Unknown symbol with no keyword defaults to CRYPTO."""
        result = parse_trade_command("Buy $50 of XYZ123")
        assert result.asset is None
        assert result.asset_class == "CRYPTO"  # Default


class TestExecutionMode:
    """Test execution mode assignment.

    Note: In pytest environment, mode defaults to PAPER for safety.
    This is by design to prevent accidental live trading in tests.

    To test non-pytest mode assignment, we verify that:
    1. Explicit 'paper' keyword works
    2. Asset class detection is correct (independent of mode)
    """

    def test_pytest_defaults_to_paper(self):
        """Pytest environment should default to PAPER mode."""
        result = parse_trade_command("Buy $50 of BTC")
        assert result.mode == "PAPER"  # pytest safety default

    def test_crypto_paper_mode(self):
        """Crypto with paper keyword should be PAPER."""
        result = parse_trade_command("Buy $50 of BTC paper")
        assert result.mode == "PAPER"

    def test_stock_in_pytest(self):
        """Stocks in pytest also default to PAPER."""
        result = parse_trade_command("Buy $50 of AAPL")
        assert result.mode == "PAPER"  # pytest safety default
        assert result.asset_class == "STOCK"  # But asset class is still STOCK

    def test_stock_paper_still_paper(self):
        """Stocks with paper keyword should still be PAPER."""
        result = parse_trade_command("Buy $50 of AAPL paper")
        assert result.mode == "PAPER"  # Paper keyword overrides

    def test_simulation_keyword(self):
        """'simulation' keyword should trigger PAPER mode."""
        result = parse_trade_command("Buy $50 of BTC simulation")
        assert result.mode == "PAPER"


class TestSideAndAmount:
    """Test side and amount parsing."""

    def test_buy_side(self):
        """'buy' should set side to buy."""
        result = parse_trade_command("Buy $50 of BTC")
        assert result.side == "buy"

    def test_sell_side(self):
        """'sell' should set side to sell."""
        result = parse_trade_command("Sell $50 of ETH")
        assert result.side == "sell"

    def test_purchase_as_buy(self):
        """'purchase' should be treated as buy."""
        result = parse_trade_command("Purchase $100 of SOL")
        assert result.side == "buy"

    def test_amount_parsing(self):
        """Dollar amounts should be parsed correctly."""
        result = parse_trade_command("Buy $123.45 of BTC")
        assert result.amount_usd == 123.45

    def test_no_amount(self):
        """Missing amount should result in None."""
        result = parse_trade_command("Buy BTC")
        assert result.amount_usd is None


class TestLookbackPeriod:
    """Test lookback period parsing."""

    def test_24h_lookback(self):
        """24h lookback variants."""
        result = parse_trade_command("Buy $50 of BTC last 24h")
        assert result.lookback_hours == 24

    def test_48h_lookback(self):
        """48h lookback variants."""
        result = parse_trade_command("Buy $50 of BTC last 48 hours")
        assert result.lookback_hours == 48

    def test_1_week_lookback(self):
        """1 week lookback."""
        result = parse_trade_command("Buy $50 of BTC 1 week")
        assert result.lookback_hours == 168


class TestMostProfitable:
    """Test 'most profitable' detection."""

    def test_most_profitable_crypto(self):
        """'most profitable' should set is_most_profitable flag."""
        result = parse_trade_command("Buy $50 of the most profitable crypto")
        assert result.is_most_profitable is True
        assert result.asset_class == "CRYPTO"

    def test_best_performing(self):
        """'best performing' should also trigger most profitable."""
        result = parse_trade_command("Buy $50 of best performing crypto")
        assert result.is_most_profitable is True

    def test_top_gainer(self):
        """'top gainer' should also trigger most profitable."""
        result = parse_trade_command("Buy $50 of top gainer")
        assert result.is_most_profitable is True


class TestStockSymbolCoverage:
    """Test stock symbol coverage."""

    def test_tech_stocks(self):
        """Major tech stocks should be recognized."""
        for symbol in ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]:
            result = parse_trade_command(f"Buy $50 of {symbol}")
            assert result.asset == symbol
            assert result.asset_class == "STOCK"

    def test_etf_tickers(self):
        """ETF tickers should be recognized as stocks."""
        for symbol in ["SPY", "QQQ", "DIA"]:
            result = parse_trade_command(f"Buy $50 of {symbol}")
            assert result.asset == symbol
            assert result.asset_class == "STOCK"

    def test_company_aliases(self):
        """Company name aliases should map correctly."""
        test_cases = [
            ("Microsoft", "MSFT"),
            ("Google", "GOOGL"),
            ("Amazon", "AMZN"),
            ("Tesla", "TSLA"),
            ("nvidia", "NVDA"),
        ]
        for alias, expected in test_cases:
            result = parse_trade_command(f"Buy $50 of {alias}")
            assert result.asset == expected, f"Expected {alias} to map to {expected}"


class TestCryptoSymbolCoverage:
    """Test crypto symbol coverage."""

    def test_major_cryptos(self):
        """Major crypto symbols should be recognized."""
        for symbol in ["BTC", "ETH", "SOL", "ADA", "DOT"]:
            result = parse_trade_command(f"Buy $50 of {symbol}")
            assert result.asset == symbol
            assert result.asset_class == "CRYPTO"

    def test_crypto_aliases(self):
        """Crypto full names should map correctly."""
        test_cases = [
            ("bitcoin", "BTC"),
            ("ethereum", "ETH"),
            ("solana", "SOL"),
            ("cardano", "ADA"),
            ("polkadot", "DOT"),
        ]
        for alias, expected in test_cases:
            result = parse_trade_command(f"Buy $50 of {alias}")
            assert result.asset == expected, f"Expected {alias} to map to {expected}"
