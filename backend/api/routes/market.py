"""Market data API routes."""
from fastapi import APIRouter, Query, HTTPException
from backend.services.market_data import get_price, MarketDataError

router = APIRouter()


@router.get("/price")
async def get_market_price(symbol: str = Query(...)):
    """Get market price."""
    try:
        price = get_price(symbol)
        return {"symbol": symbol, "price": price}
    except MarketDataError as e:
        raise HTTPException(status_code=400, detail=str(e))
