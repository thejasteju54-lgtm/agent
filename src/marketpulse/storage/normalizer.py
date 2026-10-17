"""Article normalization, deduplication, and provenance hashing."""

import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from email.utils import parsedate_to_datetime

from sqlalchemy.orm import Session
from marketpulse.storage.models import Article, AuditEvent


def normalize_financial_text(text: str) -> str:
    """Clean and normalize raw financial news/disclosure text.

    - Unescapes HTML entities.
    - Strips unwanted HTML tags.
    - Normalizes Indian numeric and currency notations.
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


def parse_published_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse publication date from various RSS/ISO formats into UTC datetime."""
    if not date_str:
        return None

    date_str = date_str.strip()

    # Try RFC 2822 (common in RSS feeds)
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Try ISO 8601
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # Common Indian date formats: DD-MM-YYYY, DD/MM/YYYY
    for fmt in ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


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
    content_hash = compute_content_hash(normalized_title, normalized_body)

    # 1. Check for existing article with identical content hash
    existing = session.query(Article).filter_by(content_hash=content_hash).first()
    if existing:
        return existing, False

    # 2. Insert new article
    now_utc = datetime.now(timezone.utc)
    article = Article(
        source_id=source_id,
        source_identifier=source_identifier,
        title=normalized_title,
        content_raw=content_raw,
        content_normalized=normalized_body,
        content_hash=content_hash,
        author=author,
        materiality_score=materiality_score,
        published_at=published_at,
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
