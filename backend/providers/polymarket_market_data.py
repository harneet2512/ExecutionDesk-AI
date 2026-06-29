"""Polymarket prediction market data provider.

Fetches market data from Polymarket's Gamma API (market discovery)
and CLOB API (order books, trades, pricing).

This provider does NOT extend MarketDataProvider because prediction
markets have a fundamentally different data model than price candles:
outcomes are binary (YES/NO), prices are probabilities (0.00-1.00),
and there are no traditional OHLCV bars.
"""
import time
import httpx
import json
from typing import List, Dict, Any, Optional
from backend.core.logging import get_logger

logger = get_logger(__name__)

# HTTP configuration
REQUEST_TIMEOUT_SECONDS = 8.0


class PolymarketMarketDataProvider:
    """Polymarket prediction market data provider.

    Uses two APIs:
    - Gamma API (gamma-api.polymarket.com): market discovery, search, metadata
    - CLOB API (clob.polymarket.com): order books, trades, pricing
    """

    def __init__(self):
        self.base_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"

    def search_markets(
        self, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search for prediction markets matching a query.

        Uses the Gamma API to discover markets by keyword.

        Args:
            query: Search term (e.g., "presidential election", "bitcoin price")
            limit: Maximum number of results to return

        Returns:
            List of market dicts sorted by volume descending, each containing:
            question, slug, condition_id, yes_price, no_price, volume,
            liquidity, active, end_date
        """
        url = f"{self.gamma_url}/markets"
        params = {
            "search": query,
            "limit": limit,
            "active": True,
        }

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                raw_markets = response.json()

            if not isinstance(raw_markets, list):
                logger.warning(
                    "Unexpected response type from Gamma search: %s",
                    type(raw_markets).__name__,
                )
                return []

            markets = []
            for m in raw_markets:
                # Parse outcomePrices (can be a JSON string or a list)
                prices_raw = m.get("outcomePrices", "[]")
                if isinstance(prices_raw, str):
                    try:
                        prices_parsed = json.loads(prices_raw)
                    except (json.JSONDecodeError, TypeError):
                        prices_parsed = []
                elif isinstance(prices_raw, list):
                    prices_parsed = prices_raw
                else:
                    prices_parsed = []

                try:
                    yes_price = float(prices_parsed[0]) if len(prices_parsed) > 0 else 0.0
                except (ValueError, IndexError, TypeError):
                    yes_price = 0.0

                try:
                    no_price = float(prices_parsed[1]) if len(prices_parsed) > 1 else 0.0
                except (ValueError, IndexError, TypeError):
                    no_price = 0.0

                volume_raw = m.get("volume", 0)
                try:
                    volume = float(volume_raw) if volume_raw is not None else 0.0
                except (ValueError, TypeError):
                    volume = 0.0

                liquidity_raw = m.get("liquidity", 0)
                try:
                    liquidity = float(liquidity_raw) if liquidity_raw is not None else 0.0
                except (ValueError, TypeError):
                    liquidity = 0.0

                markets.append({
                    "question": m.get("question", ""),
                    "slug": m.get("slug", ""),
                    "condition_id": m.get("conditionId", ""),
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "volume": volume,
                    "liquidity": liquidity,
                    "active": bool(m.get("active", False)),
                    "end_date": m.get("endDate"),
                })

            # Sort by volume descending
            markets.sort(key=lambda x: x["volume"], reverse=True)

            logger.info(
                "Polymarket search for '%s' returned %d markets",
                query, len(markets),
            )
            return markets

        except httpx.TimeoutException:
            logger.error("Timeout searching Polymarket for '%s'", query)
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                "Gamma API error searching '%s': %d - %s",
                query, e.response.status_code, e.response.text[:200],
            )
            return []
        except Exception as e:
            logger.error("Failed to search Polymarket markets: %s", e)
            return []

    def get_market_detail(
        self, condition_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific market.

        Args:
            condition_id: The market's condition ID

        Returns:
            Dict with condition_id, question, outcomes, tokens (list of
            {token_id, outcome, price}), volume, liquidity, end_date.
            Returns None on error.
        """
        url = f"{self.gamma_url}/markets"
        params = {"conditionId": condition_id}

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            # Gamma returns a list; take the first match
            if isinstance(data, list):
                if not data:
                    logger.warning(
                        "No market found for condition_id=%s", condition_id
                    )
                    return None
                market = data[0]
            elif isinstance(data, dict):
                market = data
            else:
                logger.warning(
                    "Unexpected response type for market detail: %s",
                    type(data).__name__,
                )
                return None

            # Parse outcomes and tokens
            outcomes_raw = market.get("outcomes", "[]")
            if isinstance(outcomes_raw, str):
                try:
                    outcomes = json.loads(outcomes_raw)
                except (json.JSONDecodeError, TypeError):
                    outcomes = []
            elif isinstance(outcomes_raw, list):
                outcomes = outcomes_raw
            else:
                outcomes = []

            # Parse outcome prices
            prices_raw = market.get("outcomePrices", "[]")
            if isinstance(prices_raw, str):
                try:
                    prices = json.loads(prices_raw)
                except (json.JSONDecodeError, TypeError):
                    prices = []
            elif isinstance(prices_raw, list):
                prices = prices_raw
            else:
                prices = []

            # Parse CLOB token IDs
            clob_ids_raw = market.get("clobTokenIds", "[]")
            if isinstance(clob_ids_raw, str):
                try:
                    clob_ids = json.loads(clob_ids_raw)
                except (json.JSONDecodeError, TypeError):
                    clob_ids = []
            elif isinstance(clob_ids_raw, list):
                clob_ids = clob_ids_raw
            else:
                clob_ids = []

            # Build token list
            tokens = []
            for i, outcome in enumerate(outcomes):
                token_id = clob_ids[i] if i < len(clob_ids) else None
                price = float(prices[i]) if i < len(prices) else 0.0
                tokens.append({
                    "token_id": token_id,
                    "outcome": outcome,
                    "price": price,
                })

            volume_raw = market.get("volume", 0)
            try:
                volume = float(volume_raw) if volume_raw is not None else 0.0
            except (ValueError, TypeError):
                volume = 0.0

            liquidity_raw = market.get("liquidity", 0)
            try:
                liquidity = float(liquidity_raw) if liquidity_raw is not None else 0.0
            except (ValueError, TypeError):
                liquidity = 0.0

            result = {
                "condition_id": market.get("conditionId", condition_id),
                "question": market.get("question", ""),
                "outcomes": outcomes,
                "tokens": tokens,
                "volume": volume,
                "liquidity": liquidity,
                "end_date": market.get("endDate"),
            }

            logger.info(
                "Fetched market detail for condition_id=%s: %s",
                condition_id, result["question"][:80],
            )
            return result

        except httpx.TimeoutException:
            logger.error(
                "Timeout fetching market detail for condition_id=%s",
                condition_id,
            )
            return None
        except httpx.HTTPStatusError as e:
            logger.error(
                "Gamma API error for condition_id=%s: %d - %s",
                condition_id, e.response.status_code, e.response.text[:200],
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to get market detail for condition_id=%s: %s",
                condition_id, e,
            )
            return None

    def get_current_price(self, condition_id: str) -> Optional[float]:
        """Get the current YES price for a market.

        The YES price represents the market's implied probability
        of the event occurring (0.00 = 0%, 1.00 = 100%).

        Args:
            condition_id: The market's condition ID

        Returns:
            YES price as a float (0.00-1.00), or None on error
        """
        detail = self.get_market_detail(condition_id)
        if detail is None:
            return None

        tokens = detail.get("tokens", [])
        for token in tokens:
            if token.get("outcome", "").upper() == "YES":
                return token.get("price")

        # Fallback: return first token price if no explicit YES outcome
        if tokens:
            return tokens[0].get("price")

        logger.warning(
            "No price found for condition_id=%s", condition_id
        )
        return None

    def get_order_book(
        self, token_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get the order book for a specific token from the CLOB API.

        Args:
            token_id: The CLOB token ID (from get_market_detail tokens)

        Returns:
            Dict with bids (list of {price, size}), asks (list of {price, size}),
            spread, and depth. Returns None on error.
        """
        url = f"{self.base_url}/book"
        params = {"token_id": token_id}

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            bids_raw = data.get("bids", [])
            asks_raw = data.get("asks", [])

            bids = [
                {"price": float(b.get("price", 0)), "size": float(b.get("size", 0))}
                for b in bids_raw
            ]
            asks = [
                {"price": float(a.get("price", 0)), "size": float(a.get("size", 0))}
                for a in asks_raw
            ]

            # Sort bids descending by price, asks ascending by price
            bids.sort(key=lambda x: x["price"], reverse=True)
            asks.sort(key=lambda x: x["price"])

            # Calculate spread
            best_bid = bids[0]["price"] if bids else 0.0
            best_ask = asks[0]["price"] if asks else 0.0
            spread = best_ask - best_bid if (bids and asks) else 0.0

            # Calculate total depth
            bid_depth = sum(b["size"] for b in bids)
            ask_depth = sum(a["size"] for a in asks)

            result = {
                "bids": bids,
                "asks": asks,
                "spread": round(spread, 4),
                "depth": {
                    "bid_depth": round(bid_depth, 2),
                    "ask_depth": round(ask_depth, 2),
                    "total_depth": round(bid_depth + ask_depth, 2),
                },
            }

            logger.info(
                "Fetched order book for token_id=%s: %d bids, %d asks, spread=%.4f",
                token_id, len(bids), len(asks), spread,
            )
            return result

        except httpx.TimeoutException:
            logger.error(
                "Timeout fetching order book for token_id=%s", token_id
            )
            return None
        except httpx.HTTPStatusError as e:
            logger.error(
                "CLOB API error for order book token_id=%s: %d - %s",
                token_id, e.response.status_code, e.response.text[:200],
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to get order book for token_id=%s: %s",
                token_id, e,
            )
            return None

    def get_market_trades(
        self, condition_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get recent trades for a market.

        Args:
            condition_id: The market's condition ID
            limit: Maximum number of trades to return

        Returns:
            List of trade dicts. Returns empty list on error.
        """
        url = f"{self.gamma_url}/trades"
        params = {
            "conditionId": condition_id,
            "limit": limit,
        }

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            if not isinstance(data, list):
                logger.warning(
                    "Unexpected trades response type: %s",
                    type(data).__name__,
                )
                return []

            trades = []
            for t in data:
                try:
                    price = float(t.get("price", 0))
                except (ValueError, TypeError):
                    price = 0.0

                try:
                    size = float(t.get("size", 0))
                except (ValueError, TypeError):
                    size = 0.0

                trades.append({
                    "trade_id": t.get("id", ""),
                    "condition_id": t.get("conditionId", condition_id),
                    "price": price,
                    "size": size,
                    "side": t.get("side", ""),
                    "outcome": t.get("outcome", ""),
                    "timestamp": t.get("timestamp") or t.get("createdAt"),
                })

            logger.info(
                "Fetched %d trades for condition_id=%s",
                len(trades), condition_id,
            )
            return trades

        except httpx.TimeoutException:
            logger.error(
                "Timeout fetching trades for condition_id=%s", condition_id
            )
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                "Gamma API error fetching trades for condition_id=%s: %d - %s",
                condition_id, e.response.status_code, e.response.text[:200],
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to get trades for condition_id=%s: %s",
                condition_id, e,
            )
            return []

    def get_price_history(
        self, token_id: str, fidelity: int = 60, interval: str = "all"
    ) -> List[Dict[str, Any]]:
        """Get price history timeseries from CLOB API.

        Args:
            token_id: The CLOB token ID
            fidelity: Time granularity in minutes (1, 5, 15, 60, 360, 1440)
            interval: Time range - "1d", "1w", "1m", "all"

        Returns:
            List of {"t": unix_timestamp, "p": price} dicts, sorted ascending.
        """
        url = f"{self.base_url}/prices-history"

        end_ts = int(time.time())
        interval_map = {
            "1h": 3600,
            "6h": 21600,
            "1d": 86400,
            "1w": 604800,
            "1m": 2592000,
            "all": 31536000,
        }
        seconds_back = interval_map.get(interval, 604800)
        start_ts = end_ts - seconds_back

        params = {
            "market": token_id,
            "fidelity": fidelity,
            "startTs": start_ts,
            "endTs": end_ts,
        }

        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            if not isinstance(data, dict):
                logger.warning("Unexpected price history response: %s", type(data).__name__)
                return []

            history = data.get("history", [])
            if not isinstance(history, list):
                return []

            points = []
            for point in history:
                ts = point.get("t")
                price = point.get("p")
                if ts is not None and price is not None:
                    try:
                        points.append({"t": int(ts), "p": float(price)})
                    except (ValueError, TypeError):
                        continue

            points.sort(key=lambda x: x["t"])
            logger.info(
                "Fetched %d price history points for token_id=%s (interval=%s, fidelity=%d)",
                len(points), token_id[:16], interval, fidelity,
            )
            return points

        except httpx.TimeoutException:
            logger.error("Timeout fetching price history for token_id=%s", token_id[:16])
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                "CLOB price history error for token_id=%s: %d - %s",
                token_id[:16], e.response.status_code, e.response.text[:200],
            )
            return []
        except Exception as e:
            logger.error("Failed to get price history for token_id=%s: %s", token_id[:16], e)
            return []

    def timeseries_to_ohlcv(
        self,
        timeseries: List[Dict[str, Any]],
        interval_seconds: int = 3600,
    ) -> List[Dict[str, Any]]:
        """Convert a list of timestamped price points into OHLCV bars.

        Useful for charting prediction market price history as candle-like
        bars, even though prediction markets do not natively produce OHLCV.

        Args:
            timeseries: List of {"t": unix_timestamp, "p": price} dicts
            interval_seconds: Bar width in seconds (default 3600 = 1 hour)

        Returns:
            List of OHLCV bar dicts, each with: start_time, open, high,
            low, close, volume (count of data points in the bar).
            Returns empty list for empty input.
        """
        if not timeseries:
            return []

        # Sort by timestamp ascending
        sorted_points = sorted(timeseries, key=lambda x: x.get("t", 0))

        bars: List[Dict[str, Any]] = []
        current_bar: Optional[Dict[str, Any]] = None

        for point in sorted_points:
            ts = point.get("t")
            price = point.get("p")

            if ts is None or price is None:
                continue

            try:
                ts = int(ts)
                price = float(price)
            except (ValueError, TypeError):
                continue

            # Determine which bar this point belongs to
            bar_start = (ts // interval_seconds) * interval_seconds

            if current_bar is None or current_bar["start_time"] != bar_start:
                # Finalize previous bar and start a new one
                if current_bar is not None:
                    bars.append(current_bar)

                current_bar = {
                    "start_time": bar_start,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1,
                }
            else:
                # Update existing bar
                current_bar["high"] = max(current_bar["high"], price)
                current_bar["low"] = min(current_bar["low"], price)
                current_bar["close"] = price
                current_bar["volume"] += 1

        # Append the last bar
        if current_bar is not None:
            bars.append(current_bar)

        logger.info(
            "Converted %d timeseries points into %d OHLCV bars (interval=%ds)",
            len(sorted_points), len(bars), interval_seconds,
        )
        return bars
