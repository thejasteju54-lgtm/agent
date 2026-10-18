"""Collector and ingestion engine for permitted Indian financial market sources.

Enforces:
- Configurable source registry lookups.
- Bounded retries with exponential backoff and jitter.
- Domain-level rate limiting and cooldown enforcement.
- Strict adherence to public/permitted feeds (zero paywall/CAPTCHA bypass).
- Cryptographic SHA-256 hashing, deduplication, and incomplete-data detection.
- Persistence into EvidenceRecord and Article models with full audit logging.
"""

from datetime import datetime, timezone
import random
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import httpx
from sqlalchemy.orm import Session

from marketpulse.logging.setup import get_logger
from marketpulse.research.parsers import BaseSourceParser, ParsedItem, get_parser_for_source
from marketpulse.storage.models import (
    Article,
    AuditEvent,
    Company,
    EvidenceRecord,
    SourceRegistry,
)
from marketpulse.storage.normalizer import (
    classify_data_freshness,
    compute_evidence_hash,
    detect_incomplete_data,
    normalize_financial_text,
    normalize_timestamp,
    normalize_url,
    save_normalized_article,
    save_normalized_evidence_record,
)

logger = get_logger(__name__)

# Standard Indian Listed Ticker Dictionary for automated passage tagging
STANDARD_TICKER_PATTERNS = {
    "RELIANCE": r"\b(Reliance|RIL|RELIANCE)\b",
    "TCS": r"\b(TCS|Tata Consultancy Services)\b",
    "INFY": r"\b(Infosys|INFY)\b",
    "HDFCBANK": r"\b(HDFC Bank|HDFCBANK)\b",
    "ICICIBANK": r"\b(ICICI Bank|ICICIBANK)\b",
    "SBIN": r"\b(State Bank of India|SBI|SBIN)\b",
    "BHARTIARTL": r"\b(Bharti Airtel|Airtel|BHARTIARTL)\b",
    "ITC": r"\b(ITC|ITC Limited)\b",
    "LT": r"\b(Larsen & Toubro|L&T|LT)\b",
    "MARUTI": r"\b(Maruti Suzuki|Maruti|MARUTI)\b",
    "SUNPHARMA": r"\b(Sun Pharma|Sun Pharmaceutical|SUNPHARMA)\b",
    "TATASTEEL": r"\b(Tata Steel|TATASTEEL)\b",
}


class DomainRateLimiter:
    """Enforces minimum delays between requests to the same host."""

    def __init__(self):
        self._last_access: Dict[str, float] = {}

    def wait_if_needed(self, url: str, rate_limit_per_minute: int = 30) -> None:
        domain = urlparse(url).netloc.lower()
        if not domain:
            return

        min_interval = 60.0 / max(rate_limit_per_minute, 1)
        now = time.monotonic()
        last = self._last_access.get(domain, 0.0)
        elapsed = now - last

        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            logger.debug("Rate limiting: sleeping %.2fs before accessing %s", sleep_time, domain)
            time.sleep(sleep_time)

        self._last_access[domain] = time.monotonic()


_GLOBAL_RATE_LIMITER = DomainRateLimiter()


class SourceCollector:
    """Collects and normalizes market intelligence from approved registry sources."""

    def __init__(
        self,
        session: Session,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        user_agent: str = "MarketPulse-AI/0.1.0 (Indian-Market-Research; +https://marketpulse.ai)",
    ):
        self.session = session
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.rate_limiter = _GLOBAL_RATE_LIMITER

    def _fetch_url_with_retries(self, url: str, rate_limit_per_minute: int = 30) -> Tuple[int, str]:
        """Fetch URL content with bounded retries and exponential backoff.

        Never attempts to bypass authentication or access restricted content.
        """
        self.rate_limiter.wait_if_needed(url, rate_limit_per_minute)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    resp = client.get(url, headers=headers)
                    if resp.status_code == 200:
                        return resp.status_code, resp.text
                    elif resp.status_code in (401, 403, 429):
                        # Restricted, unauthorized or rate limited: do not blindly hammer server
                        logger.warning(
                            "Source returned %d for %s. Respecting access restriction.",
                            resp.status_code,
                            url,
                        )
                        return resp.status_code, ""
                    else:
                        logger.warning("Attempt %d returned status %d for %s", attempt, resp.status_code, url)
            except Exception as e:
                last_error = str(e)
                logger.warning("Attempt %d failed fetching %s: %s", attempt, url, e)

            if attempt < self.max_retries:
                backoff = (2 ** (attempt - 1)) + random.uniform(0.1, 0.5)
                time.sleep(backoff)

        raise RuntimeError(f"Failed to fetch {url} after {self.max_retries} attempts: {last_error}")

    def detect_company_symbols(self, text: str) -> List[str]:
        """Identify listed Indian tickers referenced within a financial text passage."""
        import re
        detected: List[str] = []
        for symbol, pattern in STANDARD_TICKER_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                detected.append(symbol)
        return detected

    def collect_from_source(
        self,
        source_id: str,
        target_symbol: Optional[str] = None,
        max_items: int = 25,
    ) -> Dict[str, Any]:
        """Execute end-to-end collection for a registered source.

        Args:
            source_id: Unique ID in mp_sources (e.g. 'rbi_press_releases', 'permitted_financial_rss').
            target_symbol: Optional ticker to filter or prioritize.
            max_items: Maximum items to process.

        Returns:
            Collection metrics summary dict.
        """
        source = self.session.query(SourceRegistry).filter_by(id=source_id, is_active=True).first()
        if not source:
            raise ValueError(f"Active approved source with ID '{source_id}' not found in registry")

        fetch_url = source.feed_url or source.base_url
        logger.info("Collecting from source '%s' (%s) -> %s", source.name, source.source_type, fetch_url)

        # 1. Fetch raw payload with bounded retries & rate limits
        status_code, raw_text = self._fetch_url_with_retries(
            fetch_url, rate_limit_per_minute=source.rate_limit_per_minute
        )
        if status_code != 200 or not raw_text:
            return {
                "source_id": source_id,
                "status": "FAILED_HTTP",
                "status_code": status_code,
                "items_parsed": 0,
                "new_evidence_records": 0,
                "duplicates_skipped": 0,
            }

        # 2. Parse payload using configured parser
        parser: BaseSourceParser = get_parser_for_source(source.parser_name)
        parsed_items: List[ParsedItem] = parser.parse(raw_text, base_url=source.base_url)
        logger.info("Parsed %d items from %s", len(parsed_items), source.name)

        new_evidence_count = 0
        duplicates_skipped = 0
        incomplete_count = 0
        collected_records: List[EvidenceRecord] = []

        now_utc = datetime.now(timezone.utc)
        source.last_retrieved_at = now_utc

        # 3. Process, normalize, tag, and persist
        for item in parsed_items[:max_items]:
            if item.is_incomplete:
                incomplete_count += 1

            # Match company symbol
            passage_text = f"{item.title}\n{item.content}".strip()
            detected_symbols = self.detect_company_symbols(passage_text)
            assigned_symbol = target_symbol if target_symbol else (detected_symbols[0] if detected_symbols else None)

            # Filter if target_symbol explicitly requested
            if target_symbol and target_symbol not in detected_symbols and target_symbol.upper() not in passage_text.upper():
                continue

            # Persist Evidence Record
            evidence_rec, is_new_ev = save_normalized_evidence_record(
                session=self.session,
                source_id=source.id,
                source_url=item.url or fetch_url,
                publisher=source.name,
                extracted_passage=passage_text,
                published_at=item.published_at,
                company_symbol=assigned_symbol,
                retrieval_status="SUCCESS" if not item.is_incomplete else "PARTIAL",
                verification_status="VERIFIED" if source.reliability_score >= 0.95 else "UNVERIFIED",
                metadata_json=f'{{"categories": {item.categories}, "incomplete": {item.is_incomplete}}}',
            )

            # Persist Article for search and news intelligence
            _, is_new_art = save_normalized_article(
                session=self.session,
                source_id=source.id,
                source_identifier=item.url or fetch_url,
                title=item.title,
                content_raw=item.content,
                published_at=item.published_at,
                author=item.author,
                materiality_score=source.reliability_score,
            )

            if is_new_ev:
                new_evidence_count += 1
                collected_records.append(evidence_rec)
            else:
                duplicates_skipped += 1

        self.session.commit()

        # Audit collection event
        audit = AuditEvent(
            event_type="COLLECTION_RUN",
            entity_type="SourceRegistry",
            entity_id=source.id,
            details_json=f'{{"items_parsed": {len(parsed_items)}, "new_evidence": {new_evidence_count}, "duplicates": {duplicates_skipped}}}',
            actor="research_pipeline",
            timestamp=now_utc,
        )
        self.session.add(audit)
        self.session.commit()

        return {
            "source_id": source_id,
            "source_name": source.name,
            "status": "COMPLETED",
            "items_parsed": len(parsed_items),
            "new_evidence_records": new_evidence_count,
            "duplicates_skipped": duplicates_skipped,
            "incomplete_flagged": incomplete_count,
            "evidence_records": collected_records,
        }

    def collect_all_active_sources(self, target_symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Run collection across all approved active sources in the registry."""
        sources = self.session.query(SourceRegistry).filter_by(is_active=True).all()
        results = []
        for s in sources:
            try:
                res = self.collect_from_source(source_id=s.id, target_symbol=target_symbol)
                results.append(res)
            except Exception as e:
                logger.error("Error collecting from source %s: %s", s.id, e)
                results.append({"source_id": s.id, "status": "ERROR", "error": str(e)})
        return results
