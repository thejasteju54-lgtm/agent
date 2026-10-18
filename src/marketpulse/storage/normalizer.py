"""Article and evidence normalization, deduplication, and provenance hashing."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import re
from typing import List, Optional, Tuple, Union
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.orm import Session
from marketpulse.storage.models import Article, AuditEvent, EvidenceRecord


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "_ga",
    "ref",
    "subid",
    "ncid",
}


def normalize_url(url: str) -> str:
    """Normalize URL by stripping tracking parameters, fragments, and standardizing host."""
    if not url:
        return ""

    parsed = urlparse(url.strip())
    # Lowercase scheme and netloc
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Filter out tracking query parameters
    query_tuples = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_query = [
        (k, v) for k, v in query_tuples if k.lower() not in TRACKING_PARAMS
    ]
    # Sort query params for consistent canonical URL
    filtered_query.sort(key=lambda x: x[0])
    new_query = urlencode(filtered_query)

    # Normalize path (strip redundant trailing slash if path > 1 char)
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Exclude fragment (#)
    normalized = urlunparse((scheme, netloc, path, parsed.params, new_query, ""))
    return normalized


def normalize_financial_text(text: str) -> str:
    """Clean and normalize raw financial news/disclosure text.

    - Unescapes HTML entities.
    - Strips unwanted HTML tags.
    - Normalizes Indian numeric and currency notations (Rs., ₹ -> INR).
    - Standardizes Crore and Lakh notations.
    - Standardizes whitespaces.
    """
    if not text:
        return ""

    # 1. Unescape HTML entities (&amp;, &nbsp;, etc.)
    cleaned = html.unescape(text)

    # 2. Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)

    # 3. Standardize Indian currency notations
    cleaned = re.sub(r"\bRs\.?\s*", "INR ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"₹\s*", "INR ", cleaned)

    # 4. Standardize Crore / Lakh abbreviations
    cleaned = re.sub(r"\bcr(?:\.|\b)", " Crore", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\blk(?:\.|\b)", " Lakh", cleaned, flags=re.IGNORECASE)

    # 5. Collapse multiple whitespaces and trim
    cleaned = re.sub(r"[ \t\r\f]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()


def compute_content_hash(title: str, text: str) -> str:
    """Generate SHA-256 fingerprint for deduplication."""
    norm_title = normalize_financial_text(title).lower()
    norm_body = normalize_financial_text(text).lower()
    combined = f"{norm_title}\n{norm_body}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def compute_evidence_hash(passage: str, source_url: str) -> str:
    """Generate SHA-256 fingerprint for evidence items linking passage and canonical URL."""
    norm_passage = normalize_financial_text(passage).lower()
    norm_url = normalize_url(source_url).lower()
    combined = f"{norm_url}:::{norm_passage}".encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def parse_published_date(date_str: Optional[Union[str, datetime]]) -> Optional[datetime]:
    """Parse publication date from various RSS/ISO formats into UTC datetime."""
    if not date_str:
        return None

    if isinstance(date_str, datetime):
        if date_str.tzinfo is None:
            return date_str.replace(tzinfo=timezone.utc)
        return date_str.astimezone(timezone.utc)

    cleaned_str = str(date_str).strip()

    # Try RFC 2822 (common in RSS feeds, e.g. 'Tue, 18 Oct 2026 09:30:00 GMT')
    try:
        dt = parsedate_to_datetime(cleaned_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Try ISO 8601
    try:
        dt = datetime.fromisoformat(cleaned_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Common Indian / European date formats: DD-MM-YYYY, DD/MM/YYYY
    for fmt in (
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(cleaned_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def normalize_timestamp(date_val: Optional[Union[str, datetime]]) -> Optional[datetime]:
    """Alias for parse_published_date."""
    return parse_published_date(date_val)


def classify_data_freshness(
    published_at: Optional[datetime],
    max_age_hours: int = 24,
) -> str:
    """Classify data freshness into REALTIME, RECENT, or STALE."""
    if not published_at:
        return "STALE"

    now_utc = datetime.now(timezone.utc)
    pub_utc = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)

    age_hours = (now_utc - pub_utc).total_seconds() / 3600.0
    if age_hours < 0:
        return "REALTIME"  # Future dated or minor clock drift
    if age_hours <= 4:
        return "REALTIME"
    if age_hours <= max_age_hours:
        return "RECENT"
    return "STALE"


def detect_incomplete_data(
    title: Optional[str],
    passage: Optional[str],
    url: Optional[str],
) -> Tuple[bool, List[str]]:
    """Detect whether retrieved source data is incomplete, truncated, or lacks required fields."""
    reasons: List[str] = []

    if not url or len(url.strip()) < 8:
        reasons.append("Missing or invalid source URL")

    if not title or len(title.strip()) < 5:
        reasons.append("Title missing or excessively short (< 5 chars)")

    if not passage or len(passage.strip()) < 40:
        reasons.append("Passage missing or excessively short (< 40 chars)")
    else:
        # Detect common web scraping truncation markers
        p_strip = passage.strip()
        if p_strip.endswith("...") or p_strip.endswith("…") or "[Read more]" in p_strip or "[+]" in p_strip:
            reasons.append("Content appears truncated by paywall or excerpt marker")

    return (len(reasons) > 0, reasons)


def save_normalized_article(
    session: Session,
    source_id: str,
    source_identifier: str,
    title: str,
    content_raw: str,
    published_at: Optional[datetime] = None,
    author: Optional[str] = None,
    materiality_score: float = 0.0,
) -> Tuple[Article, bool]:
    """Normalize and persist an article with strict SHA-256 deduplication.

    Returns:
        (Article, is_new): A tuple of the persisted/existing Article and a boolean
        indicating whether it was newly inserted.
    """
    normalized_body = normalize_financial_text(content_raw)
    normalized_title = normalize_financial_text(title)
    canonical_url = normalize_url(source_identifier)
    content_hash = compute_content_hash(normalized_title, normalized_body)

    # 1. Check for existing article with identical content hash
    existing = session.query(Article).filter_by(content_hash=content_hash).first()
    if existing:
        return existing, False

    # 2. Insert new article
    now_utc = datetime.now(timezone.utc)
    pub_utc = normalize_timestamp(published_at)
    article = Article(
        source_id=source_id,
        source_identifier=canonical_url or source_identifier,
        title=normalized_title,
        content_raw=content_raw,
        content_normalized=normalized_body,
        content_hash=content_hash,
        author=author,
        materiality_score=materiality_score,
        published_at=pub_utc,
        retrieved_at=now_utc,
    )
    session.add(article)
    session.flush()

    # 3. Record Audit Event for provenance tracking
    audit = AuditEvent(
        event_type="INGESTION",
        entity_type="Article",
        entity_id=article.id,
        details_json=f'{{"source_id": "{source_id}", "title": "{normalized_title[:80]}", "content_hash": "{content_hash}"}}',
        actor="system_ingestion",
        timestamp=now_utc,
    )
    session.add(audit)
    session.flush()

    return article, True


def save_normalized_evidence_record(
    session: Session,
    source_id: str,
    source_url: str,
    publisher: str,
    extracted_passage: str,
    published_at: Optional[datetime] = None,
    company_symbol: Optional[str] = None,
    retrieval_status: str = "SUCCESS",
    verification_status: str = "UNVERIFIED",
    metadata_json: Optional[str] = None,
) -> Tuple[EvidenceRecord, bool]:
    """Normalize and persist an EvidenceRecord with deduplication and incomplete-data detection."""
    norm_url = normalize_url(source_url)
    norm_passage = normalize_financial_text(extracted_passage)
    content_hash = compute_evidence_hash(norm_passage, norm_url)

    # Deduplication check
    existing = session.query(EvidenceRecord).filter_by(content_hash=content_hash).first()
    if existing:
        return existing, False

    pub_utc = normalize_timestamp(published_at)
    freshness = classify_data_freshness(pub_utc)
    is_inc, _ = detect_incomplete_data(publisher, norm_passage, norm_url)
    now_utc = datetime.now(timezone.utc)

    record = EvidenceRecord(
        source_id=source_id,
        source_url=norm_url,
        publisher=publisher,
        retrieved_at=now_utc,
        published_at=pub_utc,
        company_symbol=company_symbol.upper() if company_symbol else None,
        extracted_passage=norm_passage,
        content_hash=content_hash,
        retrieval_status=retrieval_status,
        data_freshness=freshness,
        verification_status=verification_status,
        is_incomplete=is_inc,
        metadata_json=metadata_json,
        created_at=now_utc,
    )
    session.add(record)
    session.flush()

    return record, True
