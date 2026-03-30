import re
from typing import List, Dict, Tuple, Set, Any
from backend.core.logging import get_logger

logger = get_logger(__name__)

class NewsMappingService:
    """
    Deterministic asset mapping from news content.
    """

    # Static dictionary for mapping tokens to assets
    # Expand this list as needed
    ASSET_MAP = {
        "btc": "BTC",
        "bitcoin": "BTC",
        "eth": "ETH",
        "ethereum": "ETH",
        "sol": "SOL",
        "solana": "SOL",
        "link": "LINK",
        "chainlink": "LINK",
        "uni": "UNI",
        "uniswap": "UNI",
        "aave": "AAVE",
        "matic": "MATIC",
        "polygon": "MATIC",
        "dot": "DOT",
        "polkadot": "DOT",
        "ada": "ADA",
        "cardano": "ADA",
        "bnb": "BNB",
        "binance": "BNB", # Careful with "Binance" exchange vs coin
    }

    # Strict regex for tickers (e.g. $BTC)
    TICKER_REGEX = re.compile(r'\$([A-Z]{2,6})')
    
    # Common ignore list for false positive tickers like $ONE, $ART
    IGNORE_TICKERS = {"ONE", "ART", "ALL", "FOR", "GET", "NEW", "TOP", "KEY", "AND", "THE"}

    def extract_assets(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract asset mentions from text.
        Returns list of {asset_symbol, confidence, method}
        """
        mentions = {} # symbol -> {confidence, method}

        text_lower = text.lower()
        
        # Method 1: Dictionary Lookup
        # Tokenize simply/splitting by non-alphanumeric
        tokens = re.findall(r'\b[a-z]{3,}\b', text_lower)
        for token in set(tokens): # processing unique tokens
            if token in self.ASSET_MAP:
                symbol = self.ASSET_MAP[token]
                if symbol not in mentions:
                    mentions[symbol] = {"confidence": 0.9, "method": "dict"}
                else:
                    mentions[symbol]["confidence"] = max(mentions[symbol]["confidence"], 0.9)

        # Method 2: Ticker Regex ($BTC)
        regex_matches = self.TICKER_REGEX.findall(text)
        for match in regex_matches:
            symbol = match.upper()
            if symbol not in self.IGNORE_TICKERS:
                 if symbol not in mentions:
                    mentions[symbol] = {"confidence": 1.0, "method": "regex"}
        
        # Convert to list
        results = []
        for symbol, data in mentions.items():
            results.append({
                "asset_symbol": symbol,
                "confidence": data["confidence"],
                "method": data["method"]
            })
            
        return results

from typing import Any
