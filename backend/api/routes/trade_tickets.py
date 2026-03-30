"""Trade tickets API routes for ASSISTED_LIVE execution mode (stocks).

Users receive order tickets, execute manually in their brokerage, then submit receipts.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from backend.db.repo.trade_tickets_repo import TradeTicketsRepo
from backend.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/trade_tickets", tags=["trade_tickets"])

# Hardcoded tenant for demo (matches chat.py)
DEFAULT_TENANT_ID = "t_default"


class ReceiptSubmission(BaseModel):
    """Receipt from user's manual brokerage execution."""
    broker_order_id: Optional[str] = None
    filled_qty: Optional[float] = None
    filled_price: Optional[float] = None
    fees: Optional[float] = None
    fill_time: Optional[str] = None
    notes: Optional[str] = None

    model_config = {"extra": "allow"}  # Allow additional fields from brokers


class TicketResponse(BaseModel):
    """Trade ticket response."""
    ticket_id: str
    run_id: str
    asset_class: str
    symbol: str
    side: str
    notional_usd: float
    est_qty: Optional[float] = None
    suggested_limit: Optional[float] = None
    tif: str
    expires_at: str
    status: str
    receipt_json: Optional[Dict[str, Any]] = None
    created_at: str


@router.get("/by-run/{run_id}", response_model=Optional[TicketResponse])
async def get_ticket_for_run(run_id: str):
    """Get trade ticket for a specific run.

    Returns the most recent ticket associated with the run, or None if no ticket exists.
    """
    repo = TradeTicketsRepo()
    ticket = repo.get_by_run(run_id)

    if not ticket:
        return None

    return TicketResponse(
        ticket_id=ticket["id"],
        run_id=ticket["run_id"],
        asset_class=ticket["asset_class"],
        symbol=ticket["symbol"],
        side=ticket["side"],
        notional_usd=ticket["notional_usd"],
        est_qty=ticket.get("est_qty"),
        suggested_limit=ticket.get("suggested_limit"),
        tif=ticket["tif"],
        expires_at=ticket["expires_at"],
        status=ticket["status"],
        receipt_json=ticket.get("receipt_json"),
        created_at=ticket["created_at"]
    )


@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: str):
    """Get a specific trade ticket by ID."""
    repo = TradeTicketsRepo()
    ticket = repo.get_by_id(DEFAULT_TENANT_ID, ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return TicketResponse(
        ticket_id=ticket["id"],
        run_id=ticket["run_id"],
        asset_class=ticket["asset_class"],
        symbol=ticket["symbol"],
        side=ticket["side"],
        notional_usd=ticket["notional_usd"],
        est_qty=ticket.get("est_qty"),
        suggested_limit=ticket.get("suggested_limit"),
        tif=ticket["tif"],
        expires_at=ticket["expires_at"],
        status=ticket["status"],
        receipt_json=ticket.get("receipt_json"),
        created_at=ticket["created_at"]
    )


@router.get("/", response_model=List[TicketResponse])
async def list_pending_tickets():
    """List all pending trade tickets for the current tenant."""
    repo = TradeTicketsRepo()
    tickets = repo.get_pending_for_tenant(DEFAULT_TENANT_ID)

    return [
        TicketResponse(
            ticket_id=t["id"],
            run_id=t["run_id"],
            asset_class=t["asset_class"],
            symbol=t["symbol"],
            side=t["side"],
            notional_usd=t["notional_usd"],
            est_qty=t.get("est_qty"),
            suggested_limit=t.get("suggested_limit"),
            tif=t["tif"],
            expires_at=t["expires_at"],
            status=t["status"],
            receipt_json=t.get("receipt_json"),
            created_at=t["created_at"]
        )
        for t in tickets
    ]


@router.post("/{ticket_id}/receipt")
async def submit_execution_receipt(ticket_id: str, receipt: ReceiptSubmission):
    """Submit execution receipt for a trade ticket.

    User executes order manually in their brokerage (Schwab, Fidelity, etc.),
    then submits the execution confirmation here.
    """
    repo = TradeTicketsRepo()

    # Verify ticket exists and is pending
    ticket = repo.get_by_id(DEFAULT_TENANT_ID, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket["status"] != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Ticket is {ticket['status']}, cannot submit receipt"
        )

    # Mark as executed with receipt
    receipt_json = receipt.model_dump(exclude_unset=True)
    repo.mark_executed(DEFAULT_TENANT_ID, ticket_id, receipt_json)

    logger.info(
        "Trade ticket %s marked as executed: %s %s $%s",
        ticket_id, ticket["side"], ticket["symbol"], ticket["notional_usd"]
    )

    return {
        "status": "success",
        "message": f"Ticket {ticket_id} marked as executed",
        "ticket_id": ticket_id,
        "receipt": receipt_json
    }


@router.post("/{ticket_id}/cancel")
async def cancel_ticket(ticket_id: str):
    """Cancel a pending trade ticket."""
    repo = TradeTicketsRepo()

    ticket = repo.get_by_id(DEFAULT_TENANT_ID, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket["status"] != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Ticket is {ticket['status']}, cannot cancel"
        )

    repo.mark_cancelled(DEFAULT_TENANT_ID, ticket_id)

    logger.info(f"Trade ticket {ticket_id} cancelled")

    return {
        "status": "success",
        "message": f"Ticket {ticket_id} cancelled",
        "ticket_id": ticket_id
    }
