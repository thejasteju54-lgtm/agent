"""News intelligence ingestion, article search, and evidence retrieval endpoints."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import (
    ArticleIngestRequest,
    ArticleIngestResponse,
    ArticleResponse,
    EvidenceResponse,
)
from marketpulse.storage.models import (
    Article,
    ArticleCompanyMapping,
    Company,
    EvidenceItem,
    SourceRegistry,
)
from marketpulse.storage.normalizer import (
    compute_content_hash,
    normalize_financial_text,
    parse_published_date,
    save_normalized_article,
)

router = APIRouter(tags=["News & Evidence"])


@router.get("/articles", response_model=List[ArticleResponse])
def list_articles(
    q: Optional[str] = Query(None, description="Search keyword in title or content"),
    source: Optional[str] = Query(None, description="Filter by source ID"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[ArticleResponse]:
    """Search and list normalized financial articles and disclosures."""
    query = db.query(Article)
    if source:
        query = query.filter(Article.source_id.ilike(f"%{source}%"))
    if q:
        query = query.filter(
            (Article.title.ilike(f"%{q}%")) | (Article.content_normalized.ilike(f"%{q}%"))
        )

    articles = query.order_by(Article.retrieved_at.desc()).limit(limit).all()
    results = []
    for a in articles:
        tickers = [m.company.symbol for m in a.company_mappings if m.company]
        content_snippet = a.content_normalized[:300] + ("..." if len(a.content_normalized) > 300 else "")
        results.append(
            ArticleResponse(
                id=a.id,
                title=a.title,
                url=a.source_identifier,
                source_type=a.source_id,
                published_at=a.published_at,
                retrieved_at=a.retrieved_at,
                content_snippet=content_snippet,
                associated_tickers=tickers,
            )
        )
    return results


@router.post("/articles/ingest", response_model=ArticleIngestResponse, status_code=200)
def ingest_articles(
    payload: ArticleIngestRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> ArticleIngestResponse:
    """Normalize, deduplicate, and persist raw financial articles or disclosures."""
    correlation_id = payload.correlation_id or str(uuid.uuid4())
    ingested_ids = []
    duplicates = 0

    # Ensure fallback default source exists
    default_source = db.query(SourceRegistry).first()
    default_source_id = default_source.id if default_source else "permitted_financial_rss"

    all_companies = db.query(Company).all()

    for item in payload.articles:
        pub_dt = parse_published_date(item.published_at)

        # Use canonical save_normalized_article
        article, is_new = save_normalized_article(
            session=db,
            source_id=default_source_id,
            source_identifier=item.url,
            title=item.title,
            content_raw=item.content,
            published_at=pub_dt,
        )

        if not is_new:
            duplicates += 1
            continue

        # Map mentioned companies
        for comp in all_companies:
            if comp.symbol in article.content_normalized or comp.name.lower() in article.content_normalized.lower():
                mapping = ArticleCompanyMapping(
                    article_id=article.id,
                    company_id=comp.id,
                    relevance_score=0.85,
                )
                db.add(mapping)

        ingested_ids.append(article.id)

    db.commit()

    return ArticleIngestResponse(
        ingested_count=len(ingested_ids),
        duplicates_skipped=duplicates,
        article_ids=ingested_ids,
        correlation_id=correlation_id,
    )


@router.get("/evidence", response_model=List[EvidenceResponse])
def list_evidence(
    ticker: Optional[str] = Query(None, description="Filter evidence by company ticker"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[EvidenceResponse]:
    """Retrieve verified evidence items with provenance quotes and source links."""
    query = db.query(EvidenceItem)
    items = query.order_by(EvidenceItem.created_at.desc()).limit(limit).all()

    results = []
    for e in items:
        sym = None
        if e.article and e.article.company_mappings:
            first_mapping = e.article.company_mappings[0]
            if first_mapping.company:
                sym = first_mapping.company.symbol

        if ticker and sym != ticker.upper():
            continue

        results.append(
            EvidenceResponse(
                id=e.id,
                claim=e.fact_statement,
                source_quote=e.fact_statement,
                source_url=e.source_url,
                confidence_score=e.confidence_score,
                ticker=sym,
            )
        )
    return results[:limit]
