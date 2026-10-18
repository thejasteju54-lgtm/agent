"""End-to-end orchestration pipeline for the 7 specialized research agents."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from marketpulse.storage.models import Article, Company, ResearchJob
from marketpulse.research.schemas import FinalResearchReport
from marketpulse.research.agents import (
    CompanyMappingAgent,
    CounterargumentReviewAgent,
    EvidenceExtractionAgent,
    MarketContextAgent,
    NewsIntelligenceAgent,
    ReportGenerationAgent,
    ResearchSynthesisAgent,
)


from marketpulse.research.model_service import ResearchModelService
from marketpulse.research.company_research import CompanyResearchAnalyzer


class ResearchPipeline:
    """Orchestrates the 7 specialized research agents with Pydantic validation."""

    def __init__(
        self,
        session: Session,
        model_provider: Optional[str] = None,
    ):
        self.session = session
        self.model_service = ResearchModelService(provider_name=model_provider)
        self.news_agent = NewsIntelligenceAgent()
        self.mapping_agent = CompanyMappingAgent(session)
        self.context_agent = MarketContextAgent(session)
        self.evidence_agent = EvidenceExtractionAgent()
        self.synthesis_agent = ResearchSynthesisAgent(model_service=self.model_service)
        self.counterarg_agent = CounterargumentReviewAgent(model_service=self.model_service)
        self.report_agent = ReportGenerationAgent(session)
        self.company_research_analyzer = CompanyResearchAnalyzer()

    def run(
        self,
        prompt: str,
        company_symbol: Optional[str] = None,
        correlation_id: Optional[str] = None,
        articles: Optional[List[Article]] = None,
    ) -> FinalResearchReport:
        """Execute the 7-step bounded research pipeline.

        Args:
            prompt: User research query or prompt.
            company_symbol: Optional explicit NSE/BSE ticker symbol override.
            correlation_id: Correlation ID for tracking and idempotency.
            articles: Optional list of pre-fetched or filtered Article entities.

        Returns:
            Validated FinalResearchReport.
        """
        corr_id = correlation_id or str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc)

        # 1. Initialize or find ResearchJob record
        job = self.session.query(ResearchJob).filter_by(correlation_id=corr_id).first()
        if not job:
            job = ResearchJob(
                correlation_id=corr_id,
                job_type="ON_DEMAND",
                status="IN_PROGRESS",
                target_company_symbol=company_symbol,
                prompt=prompt,
                started_at=now_utc,
            )
            self.session.add(job)
            self.session.flush()
        else:
            job.status = "IN_PROGRESS"
            self.session.flush()

        try:
            # 2. Gather source articles
            article_pool = articles
            if article_pool is None:
                # Query recent articles from DB
                article_pool = (
                    self.session.query(Article)
                    .order_by(Article.retrieved_at.desc())
                    .limit(20)
                    .all()
                )
                # If still empty, collect fresh material from active approved sources
                if not article_pool:
                    from marketpulse.research.collectors import SourceCollector
                    collector = SourceCollector(session=self.session)
                    collector.collect_from_source(source_id="permitted_financial_rss", target_symbol=company_symbol)
                    article_pool = (
                        self.session.query(Article)
                        .order_by(Article.retrieved_at.desc())
                        .limit(20)
                        .all()
                    )

            # 3. Agent 1: News Intelligence
            news_output = self.news_agent.analyze(query=prompt, articles=article_pool)

            # 4. Agent 2: Company & Sector Mapping
            if company_symbol:
                comp = self.session.query(Company).filter_by(symbol=company_symbol).first()
                if comp:
                    comp_symbol = comp.symbol
                    comp_name = comp.name
                    sec_name = comp.sector.name if comp.sector else "General Sector"
                else:
                    mapping = self.mapping_agent.resolve(prompt, article_pool)
                    comp_symbol = mapping.primary_company_symbol or company_symbol
                    comp_name = mapping.primary_company_name or company_symbol
                    sec_name = mapping.primary_sector_name or "General Sector"
            else:
                mapping = self.mapping_agent.resolve(prompt, article_pool)
                comp_symbol = mapping.primary_company_symbol or "MARKET_OVERVIEW"
                comp_name = mapping.primary_company_name or "Broad Market"
                sec_name = mapping.primary_sector_name or "Diversified"

            # 5. Agent 3: Market Context
            market_ctx = self.context_agent.get_context(symbol=comp_symbol)

            # 6. Agent 4: Evidence & Provenance Extraction
            evidence_output = self.evidence_agent.extract(articles=article_pool)

            # 7. Agent 5: Research Synthesis (Bull, Base, Bear)
            scenarios = self.synthesis_agent.synthesize(
                company_name=comp_name,
                facts=evidence_output.verified_facts,
                materiality=news_output.materiality_score,
            )

            # 8. Agent 6: Counterargument & Risk Review
            counterargs = self.counterarg_agent.review(
                facts=evidence_output.verified_facts,
                materiality=news_output.materiality_score,
            )

            # 9. Agent 7: Report Assembly & Database Persistence
            report = self.report_agent.generate(
                job_id=job.id,
                company_symbol=comp_symbol,
                company_name=comp_name,
                sector_name=sec_name,
                news_intel=news_output,
                market_ctx=market_ctx,
                evidence=evidence_output,
                scenarios=scenarios,
                counterargs=counterargs,
            )

            # Mark job complete
            job.status = "COMPLETED"
            job.target_company_symbol = comp_symbol
            job.completed_at = datetime.now(timezone.utc)
            self.session.flush()

            return report

        except Exception as e:
            job.status = "FAILED"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            self.session.flush()
            raise e
