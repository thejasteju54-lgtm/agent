"""News Intelligence module for Indian financial market events.

Performs:
1. Event categorization (Earnings, Corporate Actions, Regulatory Changes, Management Changes, Macroeconomic).
2. Materiality scoring tailored for Indian listed equities.
3. Story syndication and wire-copy deduplication detection.
4. Source provenance preservation and prompt injection neutralization.
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from marketpulse.storage.models import Article


class NewsEventCategory(str, Enum):
    """Standardized financial market event classifications."""
    EARNINGS = "EARNINGS"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    REGULATORY_CHANGES = "REGULATORY_CHANGES"
    MANAGEMENT_CHANGES = "MANAGEMENT_CHANGES"
    MACROECONOMIC = "MACROECONOMIC"
    GENERAL_BUSINESS = "GENERAL_BUSINESS"


# India-first keyword dictionary for event categorization and materiality scoring
EVENT_CATEGORY_KEYWORDS: Dict[NewsEventCategory, Dict[str, float]] = {
    NewsEventCategory.REGULATORY_CHANGES: {
        "sebi order": 0.95,
        "show cause": 0.90,
        "sebi circular": 0.85,
        "rbi circular": 0.90,
        "rbi penalty": 0.95,
        "nclt insolvency": 0.95,
        "ed notice": 0.95,
        "cci investigation": 0.90,
        "statutory audit": 0.80,
        "usfda observation": 0.90,
        "usfda 483": 0.90,
        "warning letter": 0.90,
    },
    NewsEventCategory.EARNINGS: {
        "q1 results": 0.85,
        "q2 results": 0.85,
        "q3 results": 0.85,
        "q4 results": 0.85,
        "financial results": 0.80,
        "net profit": 0.80,
        "net loss": 0.85,
        "revenue growth": 0.75,
        "ebitda": 0.75,
        "operating margin": 0.75,
        "quarterly earnings": 0.80,
    },
    NewsEventCategory.CORPORATE_ACTIONS: {
        "merger": 0.90,
        "acquisition": 0.90,
        "dividend": 0.75,
        "interim dividend": 0.75,
        "bonus issue": 0.80,
        "stock split": 0.80,
        "buyback": 0.85,
        "rights issue": 0.80,
        "delisting": 0.90,
        "amalgamation": 0.85,
        "demerger": 0.85,
    },
    NewsEventCategory.MANAGEMENT_CHANGES: {
        "ceo resignation": 0.90,
        "cfo resignation": 0.90,
        "managing director resigned": 0.90,
        "appointment of ceo": 0.85,
        "appointment of cfo": 0.85,
        "auditor resignation": 0.95,
        "independent director resignation": 0.80,
        "board reshuffle": 0.80,
    },
    NewsEventCategory.MACROECONOMIC: {
        "repo rate": 0.85,
        "rbi monetary policy": 0.90,
        "cpi inflation": 0.80,
        "gdp growth": 0.80,
        "union budget": 0.85,
        "forex reserves": 0.70,
        "crude oil": 0.75,
        "gst collection": 0.75,
    },
    NewsEventCategory.GENERAL_BUSINESS: {
        "contract win": 0.75,
        "joint venture": 0.80,
        "expansion": 0.70,
        "new plant": 0.75,
        "credit rating upgrade": 0.80,
        "credit rating downgrade": 0.90,
        "default": 0.95,
    },
}

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
    re.compile(r"disregard\s+(?:guidelines|rules)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in\s+developer\s+mode", re.IGNORECASE),
]


def quarantine_text(text: Optional[str]) -> str:
    """Neutralize potential prompt injection embedded in external news text."""
    if not text:
        return ""
    safe = text
    for p in INJECTION_PATTERNS:
        safe = p.sub("[FLAGGED_EXTERNAL_INSTRUCTION_NEUTRALIZED]", safe)
    return safe


class CategorizedNewsEvent(BaseModel):
    """A single categorized financial event identified in news text."""
    article_id: str
    title: str
    snippet: str
    source_url: str
    category: NewsEventCategory
    materiality_score: float = Field(default=0.3, ge=0.0, le=1.0)
    matched_keyword: Optional[str] = None
    published_at: Optional[str] = None
    is_syndicated: bool = False
    syndication_cluster_id: Optional[str] = None


class SyndicatedStoryGroup(BaseModel):
    """Cluster of repeated or syndicated reporting covering the exact same event."""
    cluster_id: str
    canonical_title: str
    canonical_source_url: str
    publisher_count: int
    publishers: List[str] = Field(default_factory=list)
    articles: List[Dict[str, Any]] = Field(default_factory=list)


class NewsIntelligenceOutput(BaseModel):
    """Structured output from NewsIntelligenceAnalyzer."""
    relevant_articles: List[Dict[str, Any]] = Field(default_factory=list)
    categorized_events: List[CategorizedNewsEvent] = Field(default_factory=list)
    syndicated_story_groups: List[SyndicatedStoryGroup] = Field(default_factory=list)
    materiality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    primary_category: NewsEventCategory = NewsEventCategory.GENERAL_BUSINESS
    key_headline_summary: str
    detected_corporate_action: Optional[str] = None


class SyndicationDetector:
    """Detects repeated or syndicated news coverage across multiple publishers."""

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        words = re.findall(r"\b[a-zA-Z0-9]{3,}\b", text.lower())
        stopwords = {
            "the", "and", "for", "with", "from", "that", "this", "were", "been",
            "have", "has", "will", "share", "shares", "stock", "stocks", "market",
            "india", "limited", "ltd", "says", "said", "after", "into", "over",
        }
        return {w for w in words if w not in stopwords}

    @classmethod
    def find_syndicated_groups(cls, articles: List[Article]) -> List[SyndicatedStoryGroup]:
        """Group articles that represent identical or syndicated wire coverage."""
        if len(articles) < 2:
            return []

        clusters: List[List[Article]] = []
        assigned = set()

        for i, art_a in enumerate(articles):
            if i in assigned:
                continue
            current_cluster = [art_a]
            tokens_a = cls._tokenize(art_a.title)
            if not tokens_a:
                continue

            for j, art_b in enumerate(articles[i + 1:], start=i + 1):
                if j in assigned:
                    continue
                tokens_b = cls._tokenize(art_b.title)
                if not tokens_b:
                    continue

                # Compute Jaccard token overlap between headlines
                intersection = tokens_a.intersection(tokens_b)
                union = tokens_a.union(tokens_b)
                jaccard = len(intersection) / len(union) if union else 0.0

                if jaccard >= 0.55:
                    current_cluster.append(art_b)
                    assigned.add(j)

            if len(current_cluster) > 1:
                assigned.add(i)
                clusters.append(current_cluster)

        result: List[SyndicatedStoryGroup] = []
        for idx, cluster in enumerate(clusters):
            canonical = cluster[0]
            publishers = list(dict.fromkeys([
                (a.source.name if a.source else "Unknown Publisher") for a in cluster
            ]))
            group = SyndicatedStoryGroup(
                cluster_id=f"syn_cluster_{idx + 1}",
                canonical_title=canonical.title,
                canonical_source_url=canonical.source_identifier,
                publisher_count=len(cluster),
                publishers=publishers,
                articles=[
                    {
                        "article_id": a.id,
                        "title": a.title,
                        "source_url": a.source_identifier,
                        "source_name": a.source.name if a.source else None,
                    }
                    for a in cluster
                ],
            )
            result.append(group)

        return result


class NewsIntelligenceAnalyzer:
    """Analyzer module implementing Capability A (News Intelligence)."""

    def analyze(self, query: str, articles: List[Article]) -> NewsIntelligenceOutput:
        """Classify events, score materiality, detect syndication, and summarize news pool."""
        categorized_events: List[CategorizedNewsEvent] = []
        relevant_dicts: List[Dict[str, Any]] = []
        max_materiality = 0.0
        primary_category = NewsEventCategory.GENERAL_BUSINESS
        detected_action = None

        # 1. Run syndication clustering
        syndicated_groups = SyndicationDetector.find_syndicated_groups(articles)
        syndicated_article_ids: Dict[str, str] = {}
        for grp in syndicated_groups:
            for item in grp.articles:
                syndicated_article_ids[item["article_id"]] = grp.cluster_id

        # 2. Analyze each article
        for art in articles:
            safe_title = quarantine_text(art.title)
            safe_text = quarantine_text(art.content_normalized)
            full_text = f"{safe_title} {safe_text}".lower()

            art_category = NewsEventCategory.GENERAL_BUSINESS
            art_materiality = 0.3  # Baseline for financial articles
            matched_kw = None

            # Check keywords across all categories
            for cat, kw_dict in EVENT_CATEGORY_KEYWORDS.items():
                for kw, score in kw_dict.items():
                    if kw in full_text:
                        if score > art_materiality:
                            art_materiality = score
                            art_category = cat
                            matched_kw = kw
                        if detected_action is None and cat in (
                            NewsEventCategory.CORPORATE_ACTIONS,
                            NewsEventCategory.EARNINGS,
                            NewsEventCategory.REGULATORY_CHANGES,
                            NewsEventCategory.MANAGEMENT_CHANGES,
                        ):
                            detected_action = kw.title()

            if art_materiality > max_materiality:
                max_materiality = art_materiality
                primary_category = art_category

            cluster_id = syndicated_article_ids.get(art.id)
            is_syndicated = cluster_id is not None

            event = CategorizedNewsEvent(
                article_id=art.id,
                title=safe_title,
                snippet=safe_text[:300] + ("..." if len(safe_text) > 300 else ""),
                source_url=art.source_identifier,
                category=art_category,
                materiality_score=round(art_materiality, 2),
                matched_keyword=matched_kw,
                published_at=art.published_at.isoformat() if art.published_at else None,
                is_syndicated=is_syndicated,
                syndication_cluster_id=cluster_id,
            )
            categorized_events.append(event)

            relevant_dicts.append({
                "article_id": art.id,
                "title": safe_title,
                "snippet": safe_text[:300] + ("..." if len(safe_text) > 300 else ""),
                "source_identifier": art.source_identifier,
                "published_at": art.published_at.isoformat() if art.published_at else None,
                "materiality_score": round(art_materiality, 2),
                "category": art_category.value,
                "is_syndicated": is_syndicated,
            })

        syndication_summary = (
            f"Detected {len(syndicated_groups)} syndicated story cluster(s)."
            if syndicated_groups
            else "No syndicated duplicate stories detected."
        )

        summary = (
            f"Analyzed {len(articles)} documents across permitted sources. "
            f"Primary Category: {primary_category.value}. "
            f"Highest Materiality Index: {round(max_materiality, 2)}/1.0. "
            f"Key Event Focus: {detected_action or 'General Corporate Disclosures'}. "
            f"{syndication_summary}"
        )

        return NewsIntelligenceOutput(
            relevant_articles=relevant_dicts,
            categorized_events=categorized_events,
            syndicated_story_groups=syndicated_groups,
            materiality_score=round(max_materiality, 2),
            primary_category=primary_category,
            key_headline_summary=summary,
            detected_corporate_action=detected_action,
        )
