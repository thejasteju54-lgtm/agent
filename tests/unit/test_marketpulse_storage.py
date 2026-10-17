"""Unit tests for MarketPulse AI storage models, database initialization, and normalization."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marketpulse.storage.models import (
    Base,
    Company,
    Sector,
    SourceRegistry,
    Article,
    AuditEvent,
    Watchlist,
    WatchlistItem,
)
from marketpulse.storage.database import init_db, seed_initial_registry
from marketpulse.storage.normalizer import (
    normalize_financial_text,
    compute_content_hash,
    parse_published_date,
    save_normalized_article,
)


@pytest.fixture
def memory_db():
    """In-memory SQLite database fixture for testing."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_seed_initial_registry(memory_db):
    """Verify standard Indian sectors, companies, and approved sources are seeded."""
    seed_initial_registry(memory_db)

    # Verify Sectors
    sectors = memory_db.query(Sector).all()
    assert len(sectors) >= 7
    sector_codes = {s.code for s in sectors}
    assert "NIFTY_IT" in sector_codes
    assert "NIFTY_BANK" in sector_codes

    # Verify Companies
    companies = memory_db.query(Company).all()
    assert len(companies) >= 10
    symbols = {c.symbol for c in companies}
    assert "RELIANCE" in symbols
    assert "TCS" in symbols
    assert "INFY" in symbols

    # Check relation
    tcs = memory_db.query(Company).filter_by(symbol="TCS").first()
    assert tcs.sector is not None
    assert tcs.sector.code == "NIFTY_IT"

    # Verify Sources
    sources = memory_db.query(SourceRegistry).all()
    assert len(sources) >= 4
    source_ids = {s.id for s in sources}
    assert "bse_disclosures" in source_ids
    assert "nse_circulars" in source_ids


def test_normalize_financial_text():
    """Verify cleaning of HTML tags, entities, and Indian financial currency notations."""
    raw = "<p>Tata Motors reported revenue of <b>Rs. 1,05,000 cr.</b> &amp; net profit of ₹ 7,500 cr</p>"
    cleaned = normalize_financial_text(raw)

    assert "<p>" not in cleaned
    assert "<b>" not in cleaned
    assert "&amp;" not in cleaned
    assert "&" in cleaned
    assert "INR 1,05,000 Crore" in cleaned
    assert "INR 7,500 Crore" in cleaned


def test_article_deduplication(memory_db):
    """Verify that identical or cosmetically different articles are deduplicated via SHA-256."""
    seed_initial_registry(memory_db)

    title = "TCS signs $1 Billion strategic transformation deal"
    body1 = "<p>Tata Consultancy Services (TCS) today announced a major deal with European client for Rs. 8,300 cr.</p>"
    body2 = "<div>Tata Consultancy Services (TCS) today announced a major deal with European client for ₹ 8,300 cr.</div>"

    # Ingest first
    art1, is_new1 = save_normalized_article(
        session=memory_db,
        source_id="bse_disclosures",
        source_identifier="https://www.bseindia.com/ann/123",
        title=title,
        content_raw=body1,
    )
    assert is_new1 is True
    assert art1.id is not None

    # Ingest second (should detect duplicate content hash)
    art2, is_new2 = save_normalized_article(
        session=memory_db,
        source_id="bse_disclosures",
        source_identifier="https://www.bseindia.com/ann/456",
        title=title,
        content_raw=body2,
    )
    assert is_new2 is False
    assert art2.id == art1.id

    # Verify audit event logged
    audit_events = memory_db.query(AuditEvent).filter_by(entity_id=art1.id).all()
    assert len(audit_events) == 1
    assert audit_events[0].event_type == "INGESTION"


def test_parse_published_date():
    """Verify parsing of multiple date formats to UTC datetime."""
    # RFC 2822
    dt1 = parse_published_date("Mon, 17 Oct 2026 10:30:00 +0530")
    assert dt1 is not None
    assert dt1.tzinfo is not None

    # ISO 8601
    dt2 = parse_published_date("2026-10-17T12:00:00Z")
    assert dt2 is not None
    assert dt2.year == 2026

    # Indian format
    dt3 = parse_published_date("17-10-2026 15:45:00")
    assert dt3 is not None
    assert dt3.day == 17
    assert dt3.month == 10


def test_watchlist_constraints(memory_db):
    """Verify unique constraints prevent adding duplicate companies to a watchlist."""
    seed_initial_registry(memory_db)

    wl = Watchlist(name="Core Portfolio")
    memory_db.add(wl)
    memory_db.flush()

    rel = memory_db.query(Company).filter_by(symbol="RELIANCE").first()

    # Add item
    item1 = WatchlistItem(watchlist_id=wl.id, company_id=rel.id)
    memory_db.add(item1)
    memory_db.flush()

    # Add duplicate item
    item2 = WatchlistItem(watchlist_id=wl.id, company_id=rel.id)
    memory_db.add(item2)

    with pytest.raises(Exception):
        memory_db.flush()
    memory_db.rollback()
