"""Unit and integration tests for Phase 2: Market Research Pipeline.

Verifies:
1. Configurable Source Registry with retrieval methods, auth, rate limits, and parser mappings.
2. Normalized Evidence Records containing all 11 required fields.
3. URL normalization, timestamp normalization, and deduplication.
4. Parser error handling and incomplete-data detection.
5. Bounded retries and domain rate limiting.
6. Acceptance criteria: A research run retrieves real permitted source material, saves evidence records, and produces an auditable report.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marketpulse.research.collectors import DomainRateLimiter, SourceCollector
from marketpulse.research.parsers import OfficialDisclosureParser, ParsedItem, RSSFeedParser, get_parser_for_source
from marketpulse.research.pipeline import ResearchPipeline
from marketpulse.storage.artifacts import MarketPulseArtifactStore
from marketpulse.storage.database import init_db, seed_initial_registry
from marketpulse.storage.models import ArtifactRecord, EvidenceRecord, ResearchJob, ResearchReport, SourceRegistry
from marketpulse.storage.normalizer import (
    classify_data_freshness,
    compute_evidence_hash,
    detect_incomplete_data,
    normalize_financial_text,
    normalize_timestamp,
    normalize_url,
    save_normalized_evidence_record,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database session fixture with seeded registry."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    seed_initial_registry(session)
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 1. Source Registry Tests
# ---------------------------------------------------------------------------
def test_source_registry_configuration(db_session):
    """Verify all required source metadata fields exist and are seeded properly."""
    sources = db_session.query(SourceRegistry).all()
    assert len(sources) >= 5

    source_ids = {s.id for s in sources}
    assert "bse_disclosures" in source_ids
    assert "nse_circulars" in source_ids
    assert "sebi_press_releases" in source_ids
    assert "rbi_press_releases" in source_ids
    assert "permitted_financial_rss" in source_ids

    for s in sources:
        assert s.name
        assert s.source_type in ("OFFICIAL_DISCLOSURE", "REGULATORY_FEED", "PERMITTED_NEWS_RSS")
        assert s.base_url.startswith("http")
        assert s.retrieval_method in ("HTTP_GET", "RSS_FEED", "BROWSER_PLAYWRIGHT", "REST_API")
        assert s.auth_required in ("NONE", "API_KEY", "SESSION_COOKIE")
        assert s.rate_limit_per_minute > 0
        assert s.parser_name
        assert s.reliability_score > 0.0
        assert s.freshness_max_age_hours > 0


# ---------------------------------------------------------------------------
# 2. URL, Timestamp & Financial Text Normalization Tests
# ---------------------------------------------------------------------------
def test_url_normalization():
    """Verify URL canonicalization, tracking parameter stripping, and casing."""
    dirty_url = (
        "https://WWW.Example.com/News/Story-123/?utm_source=twitter&utm_medium=social"
        "&fbclid=IwAR29&id=987&utm_campaign=brand#comments"
    )
    clean_url = normalize_url(dirty_url)

    assert "utm_source" not in clean_url
    assert "utm_medium" not in clean_url
    assert "fbclid" not in clean_url
    assert "#comments" not in clean_url
    assert "id=987" in clean_url
    assert clean_url.startswith("https://www.example.com/News/Story-123")


def test_timestamp_normalization_and_freshness():
    """Verify multi-format date parsing and freshness classifications."""
    # RFC 2822
    rfc_date = "Tue, 18 Oct 2026 04:30:00 GMT"
    dt1 = normalize_timestamp(rfc_date)
    assert dt1 is not None
    assert dt1.year == 2026 and dt1.month == 10 and dt1.day == 18

    # Indian DD-MM-YYYY format
    in_date = "15-10-2026 14:30:00"
    dt2 = normalize_timestamp(in_date)
    assert dt2 is not None
    assert dt2.year == 2026 and dt2.month == 10 and dt2.day == 15

    # Freshness
    now_utc = datetime.now(timezone.utc)
    assert classify_data_freshness(now_utc - timedelta(hours=2)) == "REALTIME"
    assert classify_data_freshness(now_utc - timedelta(hours=12)) == "RECENT"
    assert classify_data_freshness(now_utc - timedelta(hours=48)) == "STALE"
    assert classify_data_freshness(None) == "STALE"


def test_financial_text_normalization():
    """Verify Indian currency notation (Rs., ₹) and numeric unit standardizations."""
    raw = "The company reported profit of Rs. 450 cr compared to ₹320 cr in Q2, with Rs 1500 lk capex."
    normalized = normalize_financial_text(raw)
    assert "INR 450 Crore" in normalized
    assert "INR 320 Crore" in normalized
    assert "INR 1500 Lakh" in normalized
    assert "Rs." not in normalized
    assert "₹" not in normalized


# ---------------------------------------------------------------------------
# 3. Parsers & Incomplete-Data Detection Tests
# ---------------------------------------------------------------------------
def test_rss_parser_and_incomplete_detection():
    """Verify RSS parser handles clean and malformed XML, and flags incomplete data."""
    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>Indian Markets Feed</title>
            <link>https://example.com/markets</link>
            <item>
                <title>TCS signs landmark INR 8,000 Crore BFSI Cloud Contract</title>
                <link>https://example.com/news/tcs-contract?utm_source=rss</link>
                <description>Tata Consultancy Services announced a major 5-year engagement with leading bank.</description>
                <pubDate>Mon, 17 Oct 2026 09:00:00 GMT</pubDate>
                <category>IT Services</category>
            </item>
            <item>
                <title>Short</title>
                <link></link>
                <description>Truncated content...</description>
            </item>
        </channel>
    </rss>"""

    parser = RSSFeedParser()
    items = parser.parse(sample_rss)
    assert len(items) == 2

    valid_item = items[0]
    assert "TCS signs" in valid_item.title
    assert "INR 8,000 Crore" in valid_item.title
    assert "utm_source" not in valid_item.url
    assert valid_item.is_incomplete is False

    incomplete_item = items[1]
    assert incomplete_item.is_incomplete is True
    assert len(incomplete_item.incomplete_reasons) > 0


def test_rss_parser_malformed_xml_resilience():
    """Verify parser does not crash on malformed XML and uses fallback."""
    broken_xml = """
    <rss version="2.0">
        <channel>
            <item>
                <title>Reliance Jio Expands 5G Spectrum</title>
                <link>https://example.com/jio</link>
                <description>Jio rolls out ultra-fast connectivity across 500 Indian cities.</description>
                <!-- unclosed tags and invalid entities & -->
            </item>
    """
    parser = RSSFeedParser()
    items = parser.parse(broken_xml)
    assert len(items) >= 1
    assert "Reliance Jio" in items[0].title


# ---------------------------------------------------------------------------
# 4. Rate Limiter and Evidence Record Persistence Tests
# ---------------------------------------------------------------------------
def test_rate_limiter():
    """Verify domain rate limiter tracks intervals without errors."""
    limiter = DomainRateLimiter()
    limiter.wait_if_needed("https://economictimes.indiatimes.com/markets", rate_limit_per_minute=120)
    assert "economictimes.indiatimes.com" in limiter._last_access


def test_evidence_record_model_persistence(db_session):
    """Verify EvidenceRecord saves all 11 required fields with deduplication."""
    passage = "Reliance Industries announced green hydrogen investment worth INR 75,000 Crore."
    url = "https://www.bseindia.com/corporates/ann.html?id=10293&utm_medium=feed"

    rec1, is_new1 = save_normalized_evidence_record(
        session=db_session,
        source_id="bse_disclosures",
        source_url=url,
        publisher="BSE Corporate Announcements",
        extracted_passage=passage,
        published_at=datetime.now(timezone.utc),
        company_symbol="RELIANCE",
        retrieval_status="SUCCESS",
        verification_status="VERIFIED",
    )
    db_session.commit()

    assert is_new1 is True
    assert rec1.id is not None
    assert rec1.publisher == "BSE Corporate Announcements"
    assert rec1.company_symbol == "RELIANCE"
    assert "utm_medium" not in rec1.source_url
    assert len(rec1.content_hash) == 64
    assert rec1.retrieval_status == "SUCCESS"
    assert rec1.data_freshness in ("REALTIME", "RECENT")
    assert rec1.verification_status == "VERIFIED"
    assert rec1.is_incomplete is False

    # Test deduplication: identical passage and URL
    rec2, is_new2 = save_normalized_evidence_record(
        session=db_session,
        source_id="bse_disclosures",
        source_url=url,
        publisher="BSE Corporate Announcements",
        extracted_passage=passage,
    )
    assert is_new2 is False
    assert rec2.id == rec1.id


# ---------------------------------------------------------------------------
# 5. Acceptance Criteria: Real Permitted Source Research Run
# ---------------------------------------------------------------------------
def test_real_permitted_source_research_run(db_session):
    """Acceptance Criteria: Test research run retrieves real permitted source material,
    saves the evidence records, and produces an auditable report."""
    collector = SourceCollector(session=db_session, timeout_seconds=10.0, max_retries=2)

    # Collect from real live permitted source (RBI Press Releases or Economic Times RSS)
    # Using 'rbi_press_releases' or 'permitted_financial_rss'
    collect_res = collector.collect_from_source(
        source_id="permitted_financial_rss",
        max_items=5,
    )

    assert collect_res["status"] == "COMPLETED"
    assert collect_res["items_parsed"] > 0
    assert collect_res["new_evidence_records"] > 0

    # Verify evidence records exist in SQLite
    records = db_session.query(EvidenceRecord).all()
    assert len(records) >= collect_res["new_evidence_records"]

    # Run research pipeline on the collected evidence
    pipeline = ResearchPipeline(session=db_session)
    report = pipeline.run(
        prompt="Analyze current market developments and macroeconomic indicators",
        company_symbol="RELIANCE",
        correlation_id="acceptance-test-corr-001",
    )

    assert report.report_id is not None
    assert report.title
    assert report.executive_summary
    assert len(report.verified_facts) >= 1

    # Verify report is saved as an auditable markdown artifact in artifacts store
    job = db_session.query(ResearchJob).filter_by(correlation_id="acceptance-test-corr-001").first()
    assert job is not None
    assert job.status == "COMPLETED"

    artifact_records = db_session.query(ArtifactRecord).filter_by(job_id=job.id).all()
    assert len(artifact_records) >= 1
    report_artifact = artifact_records[0]
    assert report_artifact.artifact_type == "REPORT"
    assert Path(report_artifact.file_path).exists()

    # Verify artifact content integrity
    store = MarketPulseArtifactStore()
    assert store.verify_artifact_integrity(report_artifact) is True
