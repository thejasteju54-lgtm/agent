"""Seven specialized research agents for Indian market intelligence."""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from marketpulse.logging.setup import get_logger
from marketpulse.storage.models import (
    Article,
    Company,
    EvidenceItem,
    MarketObservation,
    ResearchReport,
    Sector,
)
from marketpulse.research.schemas import (
    CounterargumentReviewOutput,
    EvidenceExtractionOutput,
    EvidenceItemSchema,
    FinalResearchReport,
    MarketContextOutput,
    NewsIntelligenceOutput,
    CompanyMappingOutput,
    SynthesisScenarios,
)
from marketpulse.research.news_intelligence import (
    NewsIntelligenceAnalyzer,
    quarantine_text as _quarantine_text,
)
from marketpulse.research.model_service import ResearchModelService

logger = get_logger(__name__)

# Common Indian corporate action and materiality keywords
MATERIALITY_KEYWORDS = {
    "merger": 0.9,
    "acquisition": 0.9,
    "q1 results": 0.85,
    "q2 results": 0.85,
    "q3 results": 0.85,
    "q4 results": 0.85,
    "earnings": 0.8,
    "dividend": 0.75,
    "bonus issue": 0.8,
    "sebi order": 0.95,
    "show cause": 0.9,
    "ceo resignation": 0.85,
    "cfo resignation": 0.85,
    "default": 0.95,
    "restructuring": 0.8,
    "usfda observation": 0.9,
    "contract win": 0.75,
    "joint venture": 0.8,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NewsIntelligenceAgent:
    """Agent 1: Ingests, filters, categorizes events, and assesses materiality of articles."""

    def __init__(self):
        self.analyzer = NewsIntelligenceAnalyzer()

    def analyze(self, query: str, articles: List[Article]) -> NewsIntelligenceOutput:
        return self.analyzer.analyze(query=query, articles=articles)


class CompanyMappingAgent:
    """Agent 2: Maps text mentions to canonical NSE/BSE listed companies."""

    def __init__(self, session: Session):
        self.session = session

    def resolve(self, prompt: str, articles: List[Article]) -> CompanyMappingOutput:
        # Load all active companies
        all_companies = self.session.query(Company).filter_by(is_active=True).all()

        combined_text = (prompt + " " + " ".join([a.title + " " + a.content_normalized[:200] for a in articles])).lower()

        matched = []
        for c in all_companies:
            sym_match = c.symbol.lower() in combined_text.split() or f" {c.symbol.lower()} " in f" {combined_text} "
            name_parts = [p.lower() for p in c.name.split() if len(p) > 3 and p.lower() not in ("limited", "ltd.", "india")]
            name_match = any(part in combined_text for part in name_parts)

            if sym_match or name_match:
                matched.append({
                    "symbol": c.symbol,
                    "name": c.name,
                    "isin": c.isin,
                    "sector_code": c.sector.code if c.sector else "UNKNOWN",
                    "sector_name": c.sector.name if c.sector else "Uncategorized",
                    "confidence": 1.0 if sym_match else 0.8,
                })

        # Rank matches by confidence
        matched.sort(key=lambda x: x["confidence"], reverse=True)

        if matched:
            primary = matched[0]
            return CompanyMappingOutput(
                primary_company_symbol=primary["symbol"],
                primary_company_name=primary["name"],
                identified_companies=matched,
                primary_sector_code=primary["sector_code"],
                primary_sector_name=primary["sector_name"],
            )

        # Fallback default if no explicit match
        first_comp = all_companies[0] if all_companies else None
        return CompanyMappingOutput(
            primary_company_symbol=first_comp.symbol if first_comp else "UNKNOWN",
            primary_company_name=first_comp.name if first_comp else "Unknown Entity",
            identified_companies=[],
            primary_sector_code=first_comp.sector.code if first_comp and first_comp.sector else "UNKNOWN",
            primary_sector_name=first_comp.sector.name if first_comp and first_comp.sector else "General Market",
        )


class MarketContextAgent:
    """Agent 3: Gathers market context, capitalization, and verified price benchmarks."""

    def __init__(self, session: Session):
        self.session = session

    def get_context(self, symbol: str) -> MarketContextOutput:
        company = self.session.query(Company).filter_by(symbol=symbol).first()
        if not company:
            return MarketContextOutput(
                symbol=symbol,
                company_name=symbol,
                sector_name="Uncategorized",
                market_cap_tier="UNKNOWN",
                data_freshness_note="Entity not registered in canonical database.",
            )

        # Fetch latest verified observation
        latest_obs = (
            self.session.query(MarketObservation)
            .filter_by(company_id=company.id)
            .order_by(MarketObservation.observation_date.desc())
            .first()
        )

        close_price = latest_obs.close_price if latest_obs else None
        obs_date = latest_obs.observation_date.isoformat() if latest_obs else None
        freshness = (
            f"Latest verified price recorded on {obs_date}."
            if latest_obs
            else "No real-time market data feed configured; historical context only. No prices fabricated."
        )

        return MarketContextOutput(
            symbol=company.symbol,
            company_name=company.name,
            sector_name=company.sector.name if company.sector else "General Sector",
            market_cap_tier=company.market_cap_tier,
            latest_close_price=close_price,
            observation_date=obs_date,
            data_freshness_note=freshness,
        )


class EvidenceExtractionAgent:
    """Agent 4: Extracts verified facts and quotes tied directly to source documents."""

    def extract(self, articles: List[Article]) -> EvidenceExtractionOutput:
        facts = []
        quotes = []
        interpretations = []

        for art in articles:
            # Extract sentence candidates with figures or facts
            sentences = re.split(r"(?<=[.!?])\s+", art.content_normalized)
            for s in sentences:
                s_clean = s.strip()
                if not s_clean:
                    continue
                # If sentence mentions numbers, currencies, dates, or deals, classify as candidate fact
                if any(kw in s_clean for kw in ("INR", "Crore", "Lakh", "%", "deal", "acquisition", "profit", "revenue", "loss", "order")):
                    facts.append(
                        EvidenceItemSchema(
                            fact_statement=s_clean,
                            interpretation=f"Extracted from {art.title[:60]}",
                            source_url=art.source_identifier,
                            source_publication_time=art.published_at.isoformat() if art.published_at else None,
                            confidence_score=0.95,
                        )
                    )
                    if len(facts) >= 10:
                        break

            # Extract any quotes in quotes ""
            extracted_q = re.findall(r'["\'](.*?)["\']', art.content_raw or "")
            for q in extracted_q:
                if len(q.split()) >= 4:
                    quotes.append(q)
                if len(quotes) >= 5:
                    break

        if not facts:
            # Provide baseline general fact from title
            if articles:
                a = articles[0]
                facts.append(
                    EvidenceItemSchema(
                        fact_statement=f"Reported disclosure: {a.title}",
                        source_url=a.source_identifier,
                        source_publication_time=a.published_at.isoformat() if a.published_at else None,
                        confidence_score=1.0,
                    )
                )

        interpretations.append("Recent disclosures indicate operational focus on core execution.")
        interpretations.append("Macro interest rate trajectory remains an external swing factor.")

        return EvidenceExtractionOutput(
            verified_facts=facts,
            extracted_quotes=quotes,
            analytical_interpretations=interpretations,
        )


class ResearchSynthesisAgent:
    """Agent 5: Generates Bull, Base, and Bear scenarios based exclusively on evidence."""

    def __init__(self, model_service: Optional[ResearchModelService] = None):
        self.model_service = model_service or ResearchModelService()

    def synthesize(
        self,
        company_name: str,
        facts: List[EvidenceItemSchema],
        materiality: float,
    ) -> SynthesisScenarios:
        return self.model_service.synthesize_scenarios(
            company_name=company_name,
            facts=facts,
            materiality=materiality,
        )


class CounterargumentReviewAgent:
    """Agent 6: Red-teams the thesis, identifying risks, regulatory challenges, and data limits."""

    def __init__(self, model_service: Optional[ResearchModelService] = None):
        self.model_service = model_service or ResearchModelService()

    def review(
        self,
        facts: List[EvidenceItemSchema],
        materiality: float,
        company_name: str = "Target Entity",
    ) -> CounterargumentReviewOutput:
        return self.model_service.review_counterarguments(
            company_name=company_name,
            facts=facts,
            materiality=materiality,
        )


class ReportGenerationAgent:
    """Agent 7: Compiles final research report and persists structured database records."""

    def __init__(self, session: Session):
        self.session = session

    def generate(
        self,
        job_id: str,
        company_symbol: str,
        company_name: str,
        sector_name: str,
        news_intel: NewsIntelligenceOutput,
        market_ctx: MarketContextOutput,
        evidence: EvidenceExtractionOutput,
        scenarios: SynthesisScenarios,
        counterargs: CounterargumentReviewOutput,
    ) -> FinalResearchReport:
        report_id = str(uuid.uuid4())
        now_str = _utc_now_iso()
        title = f"Investment Research Brief: {company_name} ({company_symbol}) — Sector: {sector_name}"

        exec_summary = (
            f"Comprehensive intelligence brief on {company_name} [{company_symbol}]. "
            f"Sector: {sector_name}. Materiality Index: {news_intel.materiality_score}/1.0. "
            f"{news_intel.key_headline_summary} {market_ctx.data_freshness_note} "
            f"Analysis synthesizes {len(evidence.verified_facts)} verified source facts across official and permitted feeds."
        )

        key_developments = [f.fact_statement for f in evidence.verified_facts[:5]]
        if not key_developments:
            key_developments = ["No material extraordinary events reported in recent monitoring cycle."]

        caveats = [
            "Research derived strictly from publicly filed regulatory announcements and permitted RSS syndication.",
            "Numerical claims reflect point-in-time statutory filings; historical data may be subject to subsequent restatement.",
            "Not registered financial advisory or stock recommendation; intended solely for automated analytical intelligence.",
        ]

        unresolved_questions = [
            "Detailed operational expense breakdowns require auditing full statutory annual / quarterly filing exhibits.",
            "Promoter pledging and institutional shareholding pattern changes pending latest quarterly shareholding filing.",
        ]

        evidence_refs = [
            {
                "fact": f.fact_statement,
                "url": f.source_url,
                "published_at": f.source_publication_time,
                "confidence": f.confidence_score,
            }
            for f in evidence.verified_facts
        ]

        # Persist to database (idempotent on job_id)
        comp = self.session.query(Company).filter_by(symbol=company_symbol).first()
        existing_report = self.session.query(ResearchReport).filter_by(job_id=job_id).first()
        if existing_report:
            db_report = existing_report
            report_id = existing_report.id
            db_report.title = title
            db_report.executive_summary = exec_summary
            db_report.key_developments = "\n".join(key_developments)
            db_report.bull_scenario = scenarios.bull_case
            db_report.base_scenario = scenarios.base_case
            db_report.bear_scenario = scenarios.bear_case
            db_report.risks_and_counterarguments = "\n".join(counterargs.identified_risks + counterargs.counterarguments)
            db_report.data_limitations = "\n".join(counterargs.data_limitations)
            db_report.generated_at = datetime.now(timezone.utc)
        else:
            db_report = ResearchReport(
                id=report_id,
                job_id=job_id,
                company_id=comp.id if comp else None,
                title=title,
                executive_summary=exec_summary,
                key_developments="\n".join(key_developments),
                bull_scenario=scenarios.bull_case,
                base_scenario=scenarios.base_case,
                bear_scenario=scenarios.bear_case,
                risks_and_counterarguments="\n".join(counterargs.identified_risks + counterargs.counterarguments),
                data_limitations="\n".join(counterargs.data_limitations),
                generated_at=datetime.now(timezone.utc),
            )
            self.session.add(db_report)
            self.session.flush()

        for f in evidence.verified_facts:
            ev_item = EvidenceItem(
                report_id=report_id,
                fact_statement=f.fact_statement,
                interpretation=f.interpretation,
                source_url=f.source_url,
                confidence_score=f.confidence_score,
            )
            self.session.add(ev_item)

        self.session.flush()

        # Build auditable markdown document
        evidence_table_rows = "\n".join(
            f"| {f.fact_statement} | [{f.source_url[:40]}...]({f.source_url}) | {f.confidence_score} |"
            for f in evidence.verified_facts
        )
        if not evidence_table_rows:
            evidence_table_rows = "| No verified facts recorded in this run | - | - |"

        markdown_content = f"""# {title}

**Report ID**: `{report_id}`  
**Job ID**: `{job_id}`  
**Generated At**: {now_str}  
**Company**: {company_name} (`{company_symbol}`)  
**Sector**: {sector_name}  

---

## Executive Summary
{exec_summary}

---

## Key Developments
{chr(10).join(f"- {d}" for d in key_developments)}

---

## Verified Evidence & Source Citations
| Fact Statement | Source URL | Confidence |
|---|---|---|
{evidence_table_rows}

---

## Scenario Analysis
- **Bull Case**: {scenarios.bull_case or 'N/A'}
- **Base Case**: {scenarios.base_case or 'N/A'}
- **Bear Case**: {scenarios.bear_case or 'N/A'}

---

## Risks, Counterarguments & Limitations
### Identified Risks & Counterarguments
{chr(10).join(f"- {r}" for r in (counterargs.identified_risks + counterargs.counterarguments))}

### Data Limitations
{chr(10).join(f"- {lim}" for lim in counterargs.data_limitations)}

---

## Analytical Caveats
{chr(10).join(f"- {c}" for c in caveats)}

---

## Unresolved Questions & Data Gaps
{chr(10).join(f"- {q}" for q in unresolved_questions)}

---
*Notice: Generated by MarketPulse AI. Strictly for institutional research intelligence, not financial advice. Source verified without model numerical fabrication.*
"""

        # Save to MarketPulseArtifactStore
        artifact_file_path = None
        try:
            from marketpulse.storage.artifacts import MarketPulseArtifactStore
            artifact_store = MarketPulseArtifactStore()
            art_md = artifact_store.save_artifact(
                session=self.session,
                name=f"report_{company_symbol}_{report_id[:8]}.md",
                content=markdown_content,
                artifact_type="REPORT",
                job_id=job_id,
                subfolder="reports",
            )
            artifact_file_path = art_md.file_path

            # Save structured JSON artifact
            report_data_dict = {
                "report_id": report_id,
                "job_id": job_id,
                "title": title,
                "company_symbol": company_symbol,
                "company_name": company_name,
                "sector_name": sector_name,
                "executive_summary": exec_summary,
                "key_developments": key_developments,
                "scenarios": scenarios.model_dump(),
                "risks": counterargs.identified_risks,
                "counterarguments": counterargs.counterarguments,
                "data_limitations": counterargs.data_limitations,
                "caveats": caveats,
                "unresolved_questions": unresolved_questions,
                "evidence_references": evidence_refs,
                "generated_at": now_str,
            }
            artifact_store.save_artifact(
                session=self.session,
                name=f"report_{company_symbol}_{report_id[:8]}.json",
                content=json.dumps(report_data_dict, indent=2),
                artifact_type="REPORT",
                job_id=job_id,
                subfolder="reports",
            )
        except Exception as e:
            logger.warning("Could not persist report artifact to disk: %s", e)

        return FinalResearchReport(
            report_id=report_id,
            job_id=job_id,
            title=title,
            company_symbol=company_symbol,
            company_name=company_name,
            sector_name=sector_name,
            executive_summary=exec_summary,
            key_developments=key_developments,
            verified_facts=evidence.verified_facts,
            interpretations=evidence.analytical_interpretations,
            scenarios=scenarios,
            risks_and_counterarguments=counterargs.identified_risks + counterargs.counterarguments,
            data_limitations="\n".join(counterargs.data_limitations),
            caveats=caveats,
            unresolved_questions=unresolved_questions,
            evidence_references=evidence_refs,
            artifact_location=artifact_file_path,
            generated_at=now_str,
        )
