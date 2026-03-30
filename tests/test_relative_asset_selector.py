import pytest

from backend.services.executable_state import ExecutableBalance, ExecutableState
from backend.services.relative_asset_selector import select_relative_asset


def _state(bals):
    return ExecutableState(balances=bals, fetched_at="2026-02-22T00:00:00Z", source="test")


@pytest.mark.asyncio
async def test_select_biggest_mover_last_hour_from_holdings(monkeypatch):
    state = _state(
        {
            "USD": ExecutableBalance("USD", 10.0, 0.0, None, None),
            "BTC": ExecutableBalance("BTC", 0.01, 0.0, None, None),
            "ETH": ExecutableBalance("ETH", 0.2, 0.0, None, None),
        }
    )

    async def _mock_return_pct(symbol, lookback_hours):
        return {"BTC": 1.0, "ETH": 3.5}.get(symbol)

    monkeypatch.setattr(
        "backend.services.relative_asset_selector._return_pct",
        _mock_return_pct,
    )

    res = await select_relative_asset(
        command_text="buy $1.00 of the biggest mover in the last hour",
        lookback_hours=1.0,
        executable_state=state,
        product_catalog={"BTC-USD": {}, "ETH-USD": {}},
    )

    assert res is not None
    assert res.symbol == "ETH"
    assert "2 holdings" in res.rationale
    assert res.product_id == "ETH-USD"


@pytest.mark.asyncio
async def test_select_biggest_loser_from_holdings(monkeypatch):
    state = _state(
        {
            "BTC": ExecutableBalance("BTC", 0.01, 0.0, None, None),
            "ETH": ExecutableBalance("ETH", 0.2, 0.0, None, None),
        }
    )

    async def _mock_return_pct(symbol, lookback_hours):
        return {"BTC": -4.2, "ETH": -1.3}.get(symbol)

    monkeypatch.setattr(
        "backend.services.relative_asset_selector._return_pct",
        _mock_return_pct,
    )

    res = await select_relative_asset(
        command_text="sell whichever of my holdings is down the most",
        lookback_hours=1.0,
        executable_state=state,
        product_catalog={"BTC-USD": {}, "ETH-USD": {}},
    )

    assert res is not None
    assert res.symbol == "BTC"
    assert res.metric_value == -4.2

