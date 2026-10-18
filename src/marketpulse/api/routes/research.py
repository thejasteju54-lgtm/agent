"""Research job submission, execution, and report retrieval endpoints."""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from marketpulse.api.deps import get_db, verify_api_key
from marketpulse.api.schemas import (
    ResearchJobResponse,
    ResearchJobSubmitRequest,
    ResearchReportResponse,
)
from marketpulse.research.pipeline import ResearchPipeline
from marketpulse.storage.models import Company, ResearchJob, ResearchReport

router = APIRouter(prefix="/research", tags=["Research Engine"])


@router.post("/jobs", response_model=ResearchJobResponse, status_code=202)
def submit_research_job(
    payload: ResearchJobSubmitRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> ResearchJobResponse:
    """Submit a financial research job for asynchronous or immediate processing."""
    corr_id = payload.correlation_id or str(uuid.uuid4())

    # Check for existing job with correlation_id
    existing_job = db.query(ResearchJob).filter(ResearchJob.correlation_id == corr_id).first()
    if existing_job:
        report_id = existing_job.report.id if existing_job.report else None
        return ResearchJobResponse(
            id=existing_job.id,
            query=existing_job.prompt,
            ticker=existing_job.target_company_symbol,
            status=existing_job.status,
            error=existing_job.error_message,
            report_id=report_id,
            created_at=existing_job.started_at,
            completed_at=existing_job.completed_at,
            correlation_id=existing_job.correlation_id,
        )

    pipeline = ResearchPipeline(session=db)
    if payload.sync_execute:
        report = pipeline.run(
            prompt=payload.query,
            company_symbol=payload.ticker,
            correlation_id=corr_id,
        )
        db.commit()
        job = db.query(ResearchJob).filter(ResearchJob.correlation_id == corr_id).first()
        report_record = db.query(ResearchReport).filter(ResearchReport.job_id == job.id).first()
        return ResearchJobResponse(
            id=job.id,
            query=job.prompt,
            ticker=job.target_company_symbol,
            status=job.status,
            error=job.error_message,
            report_id=report_record.id if report_record else None,
            created_at=job.started_at,
            completed_at=job.completed_at,
            correlation_id=job.correlation_id,
        )

    # Queue as PENDING
    job = ResearchJob(
        correlation_id=corr_id,
        job_type="ON_DEMAND",
        status="PENDING",
        target_company_symbol=payload.ticker,
        prompt=payload.query,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return ResearchJobResponse(
        id=job.id,
        query=job.prompt,
        ticker=job.target_company_symbol,
        status=job.status,
        error=None,
        report_id=None,
        created_at=job.started_at,
        completed_at=None,
        correlation_id=job.correlation_id,
    )


@router.post("/execute", response_model=ResearchReportResponse)
def execute_research_pipeline(
    payload: ResearchJobSubmitRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> ResearchReportResponse:
    """Execute the full 7-agent research pipeline synchronously and return structured report."""
    corr_id = payload.correlation_id or str(uuid.uuid4())
    pipeline = ResearchPipeline(session=db)

    report_output = pipeline.run(
        prompt=payload.query,
        company_symbol=payload.ticker,
        correlation_id=corr_id,
    )
    db.commit()

    # Find the persisted DB report
    job = db.query(ResearchJob).filter(ResearchJob.correlation_id == corr_id).first()
    db_report = db.query(ResearchReport).filter(ResearchReport.job_id == job.id).first()

    evidence_items = []
    if db_report:
        for ev in db_report.evidence_items:
            evidence_items.append(
                {
                    "id": ev.id,
                    "fact_statement": ev.fact_statement,
                    "interpretation": ev.interpretation,
                    "source_url": ev.source_url,
                    "confidence_score": ev.confidence_score,
                }
            )

    return ResearchReportResponse(
        id=db_report.id if db_report else str(uuid.uuid4()),
        query=payload.query,
        ticker=report_output.company_symbol,
        sector=report_output.sector_name,
        executive_summary=report_output.executive_summary,
        relevant_companies=[report_output.company_name],
        relevant_sectors=[report_output.sector_name],
        key_developments=report_output.key_developments,
        verified_facts=[f.fact_statement for f in report_output.verified_facts],
        hypotheses=report_output.interpretations,
        bull_scenario=report_output.scenarios.bull_case,
        base_scenario=report_output.scenarios.base_case,
        bear_scenario=report_output.scenarios.bear_case,
        risks_and_counterarguments=report_output.risks_and_counterarguments,
        data_limitations=[report_output.data_limitations] if isinstance(report_output.data_limitations, str) else report_output.data_limitations,
        freshness_notes="Derived from verified records",
        evidence_references=evidence_items,
        generated_at=datetime.fromisoformat(report_output.generated_at),
    )


@router.get("/jobs", response_model=List[ResearchJobResponse])
def list_research_jobs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[ResearchJobResponse]:
    """List recent research jobs."""
    jobs = db.query(ResearchJob).order_by(ResearchJob.started_at.desc()).limit(limit).all()
    return [
        ResearchJobResponse(
            id=j.id,
            query=j.prompt,
            ticker=j.target_company_symbol,
            status=j.status,
            error=j.error_message,
            report_id=j.report.id if j.report else None,
            created_at=j.started_at,
            completed_at=j.completed_at,
            correlation_id=j.correlation_id,
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=ResearchJobResponse)
def get_research_job(
    job_id: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> ResearchJobResponse:
    """Retrieve details and status of a specific research job."""
    job = (
        db.query(ResearchJob)
        .filter((ResearchJob.id == job_id) | (ResearchJob.correlation_id == job_id))
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")

    return ResearchJobResponse(
        id=job.id,
        query=job.prompt,
        ticker=job.target_company_symbol,
        status=job.status,
        error=job.error_message,
        report_id=job.report.id if job.report else None,
        created_at=job.started_at,
        completed_at=job.completed_at,
        correlation_id=job.correlation_id,
    )


@router.get("/reports", response_model=List[ResearchReportResponse])
def list_research_reports(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> List[ResearchReportResponse]:
    """List recent generated research reports."""
    reports = db.query(ResearchReport).order_by(ResearchReport.generated_at.desc()).limit(limit).all()
    results = []
    for r in reports:
        evidence_items = [
            {
                "id": ev.id,
                "fact_statement": ev.fact_statement,
                "interpretation": ev.interpretation,
                "source_url": ev.source_url,
                "confidence_score": ev.confidence_score,
            }
            for ev in r.evidence_items
        ]
        results.append(
            ResearchReportResponse(
                id=r.id,
                query=r.job.prompt if r.job else r.title,
                ticker=r.company.symbol if r.company else None,
                sector=r.company.sector.code if r.company and r.company.sector else None,
                executive_summary=r.executive_summary,
                relevant_companies=[r.company.name] if r.company else [],
                relevant_sectors=[r.company.sector.code] if r.company and r.company.sector else [],
                key_developments=[r.key_developments] if r.key_developments else [],
                verified_facts=[],
                hypotheses=[],
                bull_scenario=r.bull_scenario,
                base_scenario=r.base_scenario,
                bear_scenario=r.bear_scenario,
                risks_and_counterarguments=[r.risks_and_counterarguments] if r.risks_and_counterarguments else [],
                data_limitations=[r.data_limitations] if r.data_limitations else [],
                freshness_notes="Derived from verified records",
                evidence_references=evidence_items,
                generated_at=r.generated_at,
            )
        )
    return results


@router.get("/reports/{report_id}", response_model=ResearchReportResponse)
def get_research_report(
    report_id: str,
    db: Session = Depends(get_db),
    _auth: str = Depends(verify_api_key),
) -> ResearchReportResponse:
    """Retrieve full details for a generated research report."""
    report = db.query(ResearchReport).filter(ResearchReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Research report not found")

    evidence_items = [
        {
            "id": ev.id,
            "fact_statement": ev.fact_statement,
            "interpretation": ev.interpretation,
            "source_url": ev.source_url,
            "confidence_score": ev.confidence_score,
        }
        for ev in report.evidence_items
    ]

    return ResearchReportResponse(
        id=report.id,
        query=report.job.prompt if report.job else report.title,
        ticker=report.company.symbol if report.company else None,
        sector=report.company.sector.code if report.company and report.company.sector else None,
        executive_summary=report.executive_summary,
        relevant_companies=[report.company.name] if report.company else [],
        relevant_sectors=[report.company.sector.code] if report.company and report.company.sector else [],
        key_developments=[report.key_developments] if report.key_developments else [],
        verified_facts=[],
        hypotheses=[],
        bull_scenario=report.bull_scenario,
        base_scenario=report.base_scenario,
        bear_scenario=report.bear_scenario,
        risks_and_counterarguments=[report.risks_and_counterarguments] if report.risks_and_counterarguments else [],
        data_limitations=[report.data_limitations] if report.data_limitations else [],
        freshness_notes="Generated by MarketPulse 7-Agent Engine",
        evidence_references=evidence_items,
        generated_at=report.generated_at,
    )
