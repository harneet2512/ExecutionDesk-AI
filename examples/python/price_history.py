"""Fetch historical probability data for a Polymarket market.

Demonstrates:
- CLOB prices-history endpoint
- Fidelity-based data granularity (1min to 1day)
- Interval-to-timestamp conversion
- ASCII chart rendering
- No authentication required

Usage:
    python price_history.py <token_id>
    python price_history.py <token_id> --interval 1d --fidelity 5
"""
import sys
import time
import httpx

CLOB_URL = "https://clob.polymarket.com"

INTERVAL_SECONDS = {
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
    "1w": 604800,
    "1m": 2592000,
    "all": 31536000,
}


def get_price_history(
    token_id: str,
    interval: str = "1w",
    fidelity: int = 60,
) -> list[dict]:
    """Fetch price history from the CLOB API.

    Args:
        token_id: Outcome token identifier
        interval: Time window (1h, 6h, 1d, 1w, 1m, all)
        fidelity: Granularity in minutes (1, 5, 15, 60, 360, 1440)

    Returns:
        List of {"t": unix_timestamp, "p": price} sorted ascending
    """
    now = int(time.time())
    span = INTERVAL_SECONDS.get(interval, 604800)

    resp = httpx.get(
        f"{CLOB_URL}/prices-history",
        params={
            "market": token_id,
            "fidelity": fidelity,
            "startTs": now - span,
            "endTs": now,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()

    points = data.get("history", data) if isinstance(data, dict) else data
    if not isinstance(points, list):
        return []

    return sorted(points, key=lambda p: p.get("t", 0))


def ascii_chart(points: list[dict], width: int = 60, height: int = 15):
    """Render a simple ASCII probability chart."""
    if len(points) < 2:
        print("Not enough data points to chart.")
        return

    prices = [p["p"] for p in points]
    lo, hi = min(prices), max(prices)
    rng = hi - lo or 0.01

    step = max(1, len(prices) // width)
    sampled = prices[::step][:width]

    for row in range(height, -1, -1):
        threshold = lo + (rng * row / height)
        label = f"{threshold * 100:5.1f}% |"
        line = ""
        for val in sampled:
            line += "#" if val >= threshold else " "
        if row == height or row == 0 or row == height // 2:
            print(f"{label}{line}")
        else:
            print(f"       |{line}")

    print(f"       +{'─' * len(sampled)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python price_history.py <token_id> [--interval 1w] [--fidelity 60]")
        sys.exit(1)

    token_id = sys.argv[1]
    interval = "1w"
    fidelity = 60

    if "--interval" in sys.argv:
        interval = sys.argv[sys.argv.index("--interval") + 1]
    if "--fidelity" in sys.argv:
        fidelity = int(sys.argv[sys.argv.index("--fidelity") + 1])

    print(f"Fetching {interval} price history (fidelity={fidelity}min)...\n")
    points = get_price_history(token_id, interval, fidelity)

    if not points:
        print("No data returned.")
        return

    print(f"  {len(points)} data points")
    print(f"  Current: {points[-1]['p'] * 100:.1f}%")
    print(f"  Low:     {min(p['p'] for p in points) * 100:.1f}%")
    print(f"  High:    {max(p['p'] for p in points) * 100:.1f}%")
    print()
    ascii_chart(points)


if __name__ == "__main__":
    main()
