"""Company and sector endpoints for MarketPulse AI."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import CompanyResponse, SectorResponse
from marketpulse.storage.models import Company, Sector

router = APIRouter(tags=["Companies & Sectors"])


@router.get("/companies", response_model=List[CompanyResponse])
def list_companies(
    q: Optional[str] = Query(None, description="Search by ticker or company name"),
    sector: Optional[str] = Query(None, description="Filter by sector code"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[CompanyResponse]:
    """Retrieve list of registered Indian listed companies."""
    query = db.query(Company)
    if sector:
        sec = db.query(Sector).filter(Sector.code == sector.upper()).first()
        if sec:
            query = query.filter(Company.sector_id == sec.id)
    if q:
        search_pattern = f"%{q}%"
        query = query.filter(
            (Company.symbol.ilike(search_pattern)) | (Company.name.ilike(search_pattern))
        )
    companies = query.limit(limit).all()
    return [
        CompanyResponse(
            id=c.id,
            ticker=c.symbol,
            name=c.name,
            isin=c.isin,
            bse_code=c.bse_code,
            sector_code=c.sector.code if c.sector else None,
            market_cap_category=c.market_cap_tier,
        )
        for c in companies
    ]


@router.get("/companies/{ticker}", response_model=CompanyResponse)
def get_company(
    ticker: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> CompanyResponse:
    """Retrieve company details by ticker symbol."""
    company = db.query(Company).filter(Company.symbol == ticker.upper()).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company with ticker '{ticker}' not found")
    return CompanyResponse(
        id=company.id,
        ticker=company.symbol,
        name=company.name,
        isin=company.isin,
        bse_code=company.bse_code,
        sector_code=company.sector.code if company.sector else None,
        market_cap_category=company.market_cap_tier,
    )


@router.get("/sectors", response_model=List[SectorResponse])
def list_sectors(
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[SectorResponse]:
    """Retrieve standard Indian market sectors."""
    sectors = db.query(Sector).all()
    res = []
    for s in sectors:
        count = db.query(Company).filter(Company.sector_id == s.id).count()
        res.append(
            SectorResponse(
                id=str(s.id),
                code=s.code,
                name=s.name,
                description=s.description,
                companies_count=count,
            )
        )
    return res
