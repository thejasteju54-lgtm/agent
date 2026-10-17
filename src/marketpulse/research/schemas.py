"""Pydantic schemas for MarketPulse research agent outputs and structured reports."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class NewsIntelligenceOutput(BaseModel):
    """Output from NewsIntelligenceAgent."""
    relevant_articles: List[Dict[str, Any]] = Field(default_factory=list)
    materiality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    key_headline_summary: str
    detected_corporate_action: Optional[str] = None


class CompanyMappingOutput(BaseModel):
    """Output from CompanyMappingAgent."""
    primary_company_symbol: Optional[str] = None
    primary_company_name: Optional[str] = None
    identified_companies: List[Dict[str, Any]] = Field(default_factory=list)
    primary_sector_code: Optional[str] = None
    primary_sector_name: Optional[str] = None


class MarketContextOutput(BaseModel):
    """Output from MarketContextAgent."""
    symbol: str
    company_name: str
    sector_name: str
    market_cap_tier: str
    latest_close_price: Optional[float] = None
    observation_date: Optional[str] = None
    data_freshness_note: str


class EvidenceItemSchema(BaseModel):
    """Single verifiable fact statement with source provenance."""
    fact_statement: str
    interpretation: Optional[str] = None
    source_url: str
    source_publication_time: Optional[str] = None
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class EvidenceExtractionOutput(BaseModel):
    """Output from EvidenceExtractionAgent."""
    verified_facts: List[EvidenceItemSchema] = Field(default_factory=list)
    extracted_quotes: List[str] = Field(default_factory=list)
    analytical_interpretations: List[str] = Field(default_factory=list)


class SynthesisScenarios(BaseModel):
    """Investment scenario breakdown."""
    bull_case: Optional[str] = None
    base_case: Optional[str] = None
    bear_case: Optional[str] = None


class CounterargumentReviewOutput(BaseModel):
    """Output from CounterargumentReviewAgent."""
    identified_risks: List[str] = Field(default_factory=list)
    counterarguments: List[str] = Field(default_factory=list)
    data_limitations: List[str] = Field(default_factory=list)
    freshness_verdict: str


class FinalResearchReport(BaseModel):
    """Complete, evidence-backed financial research report."""
    report_id: str
    job_id: str
    title: str
    company_symbol: str
    company_name: str
    sector_name: str
    executive_summary: str
    key_developments: List[str] = Field(default_factory=list)
    verified_facts: List[EvidenceItemSchema] = Field(default_factory=list)
    interpretations: List[str] = Field(default_factory=list)
    scenarios: SynthesisScenarios
    risks_and_counterarguments: List[str] = Field(default_factory=list)
    data_limitations: str
    evidence_references: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: str
