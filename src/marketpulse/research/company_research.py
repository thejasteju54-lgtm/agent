"""Company Research module for Indian corporate disclosures and earnings analysis.

Enforces:
1. Structured summarization of company filings and earnings releases.
2. Period-over-period comparisons (YoY / QoQ) when disclosure data is available.
3. Strict separation of reported financial facts from analytical interpretations.
4. Explicit identification of missing information and disclosure gaps.
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from marketpulse.storage.models import Article


class ChangeDirection(str, Enum):
    """Direction of financial metric movement."""
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    FLAT = "FLAT"
    UNSPECIFIED = "UNSPECIFIED"


class ReportedFinancialFact(BaseModel):
    """A strictly verifiable financial fact extracted directly from official filings."""
    metric_name: str
    reported_value: str
    unit: Optional[str] = None  # INR Crore, INR Lakh, %, bps
    reporting_period: Optional[str] = None  # e.g., Q2 FY25, FY24
    exact_source_passage: str
    source_url: str
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class PeriodComparison(BaseModel):
    """Period-over-period comparison extracted from company disclosures."""
    metric_name: str
    current_period: str
    current_value: str
    prior_period: Optional[str] = None
    prior_value: Optional[str] = None
    change_percentage: Optional[float] = None
    direction: ChangeDirection = ChangeDirection.UNSPECIFIED
    is_significant: bool = False
    disclosure_context: str


class MissingInformationItem(BaseModel):
    """Identified omission or gap in the available filing disclosure."""
    category: str  # SEGMENTAL, CASH_FLOW, BALANCE_SHEET, FORWARD_GUIDANCE, AUDIT_STATUS
    description: str
    analytical_impact: str


class CompanyResearchSummary(BaseModel):
    """Complete structured company research and disclosure analysis."""
    company_symbol: str
    company_name: str
    reporting_period: Optional[str] = None
    executive_overview: str
    reported_financial_facts: List[ReportedFinancialFact] = Field(default_factory=list)
    period_comparisons: List[PeriodComparison] = Field(default_factory=list)
    analytical_interpretations: List[str] = Field(default_factory=list)
    missing_information: List[MissingInformationItem] = Field(default_factory=list)
    significant_changes: List[str] = Field(default_factory=list)


class CompanyResearchAnalyzer:
    """Analyzer module implementing Capability B (Company Research)."""

    METRIC_PATTERNS = [
        (re.compile(r"(?:net\s+profit|pat)\s+(?:of|at|was|surged\s+to|rose\s+to|dropped\s+to)?\s*(inr\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|bn)?)", re.I), "Net Profit"),
        (re.compile(r"(?:revenue|sales|turnover)\s+(?:of|at|was|grew\s+to|reached)?\s*(inr\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|bn)?)", re.I), "Revenue"),
        (re.compile(r"(?:ebitda|operating\s+profit)\s+(?:of|at|was)?\s*(inr\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|bn)?)", re.I), "EBITDA"),
        (re.compile(r"(?:margin|operating\s+margin|ebitda\s+margin)\s+(?:of|at|was|expanded\s+to|compressed\s+to)?\s*([\d.]+\s*%)", re.I), "Operating Margin"),
        (re.compile(r"(?:order\s+book|contract\s+win|deal\s+value)\s+(?:of|at|worth)?\s*(inr\s*[\d,]+(?:\.\d+)?\s*(?:crore|cr|lakh|bn)?|\$[\d.]+\s*(?:million|billion|mn|bn))", re.I), "Order Win / Deal Value"),
    ]

    COMPARISON_REGEX = re.compile(
        r"(up|down|rose|grew|fell|surged|dropped|slumped|jumped)\s+by\s+([\d.]+)%\s+(yoy|qoq|year-on-year|quarter-on-quarter)",
        re.I
    )

    PERIOD_REGEX = re.compile(r"\b(Q[1-4]\s*(?:FY)?\d{2,4}|FY\d{2,4}|H[1-2]\s*(?:FY)?\d{2,4})\b", re.I)

    def analyze(
        self,
        company_symbol: str,
        company_name: str,
        articles: List[Article],
    ) -> CompanyResearchSummary:
        """Analyze disclosures, compare periods, separate facts from interpretation, and flag missing info."""
        reported_facts: List[ReportedFinancialFact] = []
        comparisons: List[PeriodComparison] = []
        interpretations: List[str] = []
        missing_info: List[MissingInformationItem] = []
        significant_changes: List[str] = []
        detected_periods = set()

        for art in articles:
            text = art.content_normalized or ""
            source_url = art.source_identifier

            # 1. Detect reporting period
            period_matches = self.PERIOD_REGEX.findall(text)
            for pm in period_matches:
                detected_periods.add(pm.upper().replace(" ", ""))

            # 2. Extract Reported Financial Facts
            sentences = re.split(r"(?<=[.!?])\s+", text)
            for sent in sentences:
                sent_clean = sent.strip()
                if not sent_clean:
                    continue

                for pattern, metric in self.METRIC_PATTERNS:
                    m = pattern.search(sent_clean)
                    if m:
                        val = m.group(1).strip()
                        reported_facts.append(
                            ReportedFinancialFact(
                                metric_name=metric,
                                reported_value=val,
                                unit="INR Crore / %" if "inr" in val.lower() or "%" in val else "Standard",
                                reporting_period=list(detected_periods)[0] if detected_periods else None,
                                exact_source_passage=sent_clean,
                                source_url=source_url,
                                confidence_score=0.95,
                            )
                        )

                # 3. Extract Period Comparisons
                comp_match = self.COMPARISON_REGEX.search(sent_clean)
                if comp_match:
                    verb, pct_str, comp_type = comp_match.groups()
                    pct = float(pct_str)
                    is_increase = verb.lower() in ("up", "rose", "grew", "surged", "jumped")
                    direction = ChangeDirection.INCREASE if is_increase else ChangeDirection.DECREASE
                    is_significant = pct >= 15.0 or (pct >= 10.0 and "profit" in sent_clean.lower())

                    # Identify what metric was compared
                    metric_label = "General Financial Metric"
                    for _, mname in self.METRIC_PATTERNS:
                        if mname.lower() in sent_clean.lower():
                            metric_label = mname
                            break

                    comp = PeriodComparison(
                        metric_name=metric_label,
                        current_period=list(detected_periods)[0] if detected_periods else "Current Period",
                        current_value=f"{'+' if is_increase else '-'}{pct}% {comp_type.upper()}",
                        prior_period=f"Prior Corresponding Period ({comp_type.upper()})",
                        prior_value="Referenced in filing disclosure",
                        change_percentage=pct if is_increase else -pct,
                        direction=direction,
                        is_significant=is_significant,
                        disclosure_context=sent_clean,
                    )
                    comparisons.append(comp)

                    if is_significant:
                        significant_changes.append(
                            f"Significant shift in {metric_label}: {sent_clean}"
                        )

        # 4. Separate Analytical Interpretations (strictly non-factual hypotheses)
        if reported_facts:
            interpretations.append(
                f"Reported figures reflect operating momentum for {company_symbol} in core business verticals."
            )
        else:
            interpretations.append(
                f"Public disclosures for {company_symbol} contain limited quantitative figures; thesis relies primarily on announced initiatives."
            )

        interpretations.append(
            "Indian macroeconomic interest rate conditions and sectoral input costs remain exogenous swing factors."
        )

        # 5. Check and Flag Missing Information
        has_cashflow = any("cash flow" in (a.content_normalized or "").lower() for a in articles)
        if not has_cashflow:
            missing_info.append(
                MissingInformationItem(
                    category="CASH_FLOW",
                    description="Cash flow statement (operating, investing, financing) not available in monitored disclosure summaries.",
                    analytical_impact="Free cash flow conversion efficiency and debt servicing capacity cannot be audited without full annual report.",
                )
            )

        has_segmental = any("segment" in (a.content_normalized or "").lower() for a in articles)
        if not has_segmental:
            missing_info.append(
                MissingInformationItem(
                    category="SEGMENTAL",
                    description="Disaggregated segmental revenue and EBIT margins were not included in the extracted text.",
                    analytical_impact="Sub-vertical growth drivers and cross-subsidies between divisions remain opaque.",
                )
            )

        has_guidance = any("guidance" in (a.content_normalized or "").lower() for a in articles)
        if not has_guidance:
            missing_info.append(
                MissingInformationItem(
                    category="FORWARD_GUIDANCE",
                    description="Formal forward management guidance for upcoming quarters is absent from the disclosure.",
                    analytical_impact="Projections must rely on trailing run-rate and historical sector multiples.",
                )
            )

        primary_period = list(detected_periods)[0] if detected_periods else "Recent Disclosure Cycle"

        overview = (
            f"Research summary for {company_name} ({company_symbol}) covering {primary_period}. "
            f"Identified {len(reported_facts)} verified financial metric statements and "
            f"{len(comparisons)} period-over-period comparisons. "
            f"{len(significant_changes)} significant financial shifts flagged. "
            f"{len(missing_info)} information gaps explicitly identified."
        )

        return CompanyResearchSummary(
            company_symbol=company_symbol,
            company_name=company_name,
            reporting_period=primary_period,
            executive_overview=overview,
            reported_financial_facts=reported_facts[:15],
            period_comparisons=comparisons[:10],
            analytical_interpretations=interpretations,
            missing_information=missing_info,
            significant_changes=significant_changes[:5],
        )
