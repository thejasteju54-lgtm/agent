"""Watchlist management endpoints for MarketPulse AI."""

from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import (
    WatchlistCreateRequest,
    WatchlistItemAddRequest,
    WatchlistItemResponse,
    WatchlistResponse,
)
from marketpulse.storage.models import Company, Watchlist, WatchlistItem

router = APIRouter(prefix="/watchlists", tags=["Watchlists"])


@router.get("", response_model=List[WatchlistResponse])
def list_watchlists(
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[WatchlistResponse]:
    """Retrieve all watchlists along with tracked items."""
    watchlists = db.query(Watchlist).all()
    results = []
    for wl in watchlists:
        items = []
        for item in wl.items:
            items.append(
                WatchlistItemResponse(
                    id=item.id,
                    ticker=item.company.symbol if item.company else "UNKNOWN",
                    company_name=item.company.name if item.company else None,
                    added_at=item.created_at,
                    notes=item.notes,
                )
            )
        results.append(
            WatchlistResponse(
                id=wl.id,
                name=wl.name,
                description=wl.description,
                created_at=wl.created_at,
                items=items,
            )
        )
    return results


@router.post("", response_model=WatchlistResponse, status_code=201)
def create_watchlist(
    payload: WatchlistCreateRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> WatchlistResponse:
    """Create a new watchlist."""
    existing = db.query(Watchlist).filter(Watchlist.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Watchlist with name '{payload.name}' already exists")

    wl = Watchlist(name=payload.name, description=payload.description)
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return WatchlistResponse(
        id=wl.id,
        name=wl.name,
        description=wl.description,
        created_at=wl.created_at,
        items=[],
    )


@router.post("/{watchlist_id}/items", response_model=WatchlistItemResponse, status_code=201)
def add_watchlist_item(
    watchlist_id: str,
    payload: WatchlistItemAddRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> WatchlistItemResponse:
    """Add a company ticker to an existing watchlist."""
    wl = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    company = db.query(Company).filter(Company.symbol == payload.ticker.upper()).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company with ticker '{payload.ticker}' not found")

    existing_item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.company_id == company.id)
        .first()
    )
    if existing_item:
        raise HTTPException(status_code=400, detail="Ticker is already on this watchlist")

    item = WatchlistItem(
        watchlist_id=watchlist_id,
        company_id=company.id,
        notes=payload.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return WatchlistItemResponse(
        id=item.id,
        ticker=company.symbol,
        company_name=company.name,
        added_at=item.created_at,
        notes=item.notes,
    )


@router.delete("/{watchlist_id}/items/{item_id}", status_code=204)
def remove_watchlist_item(
    watchlist_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Remove an item from a watchlist."""
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == watchlist_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    db.delete(item)
    db.commit()
    return None
