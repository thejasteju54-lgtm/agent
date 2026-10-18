"""Unit and integration tests for MarketPulse AI FastAPI backend endpoints."""

import pytest
from fastapi.testclient import TestClient
from marketpulse.api.app import app
from marketpulse.storage.database import get_session, init_db, seed_initial_registry


@pytest.fixture(scope="module")
def client():
    """TestClient fixture with initialized database."""
    init_db()
    with get_session() as session:
        seed_initial_registry(session)
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_readiness_endpoints(client):
    """Verify system health and readiness endpoints."""
    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200
    data = res_health.json()
    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert data["database"] == "CONNECTED"
    assert "n8n_status" in data

    res_ready = client.get("/api/v1/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["ready"] is True


def test_n8n_endpoints(client):
    """Verify n8n status inspection and workflow registry."""
    res = client.get("/api/v1/n8n/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("CONNECTED", "DISCONNECTED", "UNAUTHORIZED", "MISCONFIGURED")

    res_wf = client.get("/api/v1/n8n/workflows")
    assert res_wf.status_code == 200
    workflows = res_wf.json()
    assert len(workflows) >= 5
    workflow_ids = [w["id"] for w in workflows]
    assert "MP-01" in workflow_ids
    assert "MP-02" in workflow_ids
    assert "MP-03" in workflow_ids


def test_companies_and_sectors(client):
    """Verify company lookup and sector categorization."""
    res_comp = client.get("/api/v1/companies?q=RELIANCE")
    assert res_comp.status_code == 200
    companies = res_comp.json()
    assert len(companies) >= 1
    assert companies[0]["ticker"] == "RELIANCE"

    res_single = client.get("/api/v1/companies/RELIANCE")
    assert res_single.status_code == 200
    assert res_single.json()["name"] == "Reliance Industries Limited"

    res_sec = client.get("/api/v1/sectors")
    assert res_sec.status_code == 200
    sectors = res_sec.json()
    assert len(sectors) >= 7
    codes = [s["code"] for s in sectors]
    assert "NIFTY_IT" in codes
    assert "NIFTY_BANK" in codes


def test_watchlists_lifecycle(client):
    """Verify watchlist creation, item addition, and item deletion."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    # 1. Create Watchlist
    res_create = client.post(
        "/api/v1/watchlists",
        json={"name": f"Test Energy Watchlist {uid}", "description": "Tracking top energy players"},
    )
    assert res_create.status_code == 201
    wl = res_create.json()
    wl_id = wl["id"]

    # 2. Add Item
    res_item = client.post(
        f"/api/v1/watchlists/{wl_id}/items",
        json={"ticker": "RELIANCE", "notes": "Heavyweight energy and telecom"},
    )
    assert res_item.status_code == 201
    item = res_item.json()
    assert item["ticker"] == "RELIANCE"
    item_id = item["id"]

    # 3. List Watchlists
    res_list = client.get("/api/v1/watchlists")
    assert res_list.status_code == 200
    found = [w for w in res_list.json() if w["id"] == wl_id]
    assert len(found) == 1
    assert len(found[0]["items"]) == 1

    # 4. Remove Item
    res_del = client.delete(f"/api/v1/watchlists/{wl_id}/items/{item_id}")
    assert res_del.status_code == 204


def test_article_ingestion_and_deduplication(client):
    """Verify article normalization, deduplication, and search."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    payload = {
        "articles": [
            {
                "title": f"TCS Reports Strong Q3 Deal Wins in BFSI Sector {uid}",
                "content": f"Tata Consultancy Services (TCS) announced new client contracts worth INR 8,000 Crore in cycle {uid}.",
                "url": f"https://example.com/news/tcs-q3-deal-wins-{uid}",
                "source_name": "permitted_financial_rss",
                "published_at": "2026-10-15T09:00:00Z",
            }
        ],
        "correlation_id": f"test-ingest-corr-{uid}",
    }

    # First Ingest: Ingested = 1, Duplicate = 0
    res1 = client.post("/api/v1/articles/ingest", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["ingested_count"] == 1
    assert data1["duplicates_skipped"] == 0

    # Second Ingest (identical content): Ingested = 0, Duplicate = 1
    res2 = client.post("/api/v1/articles/ingest", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["ingested_count"] == 0
    assert data2["duplicates_skipped"] == 1

    # Query Articles
    res_search = client.get("/api/v1/articles?q=TCS")
    assert res_search.status_code == 200
    articles = res_search.json()
    assert len(articles) >= 1
    assert "TCS" in articles[0]["associated_tickers"]


def test_research_jobs_and_sync_execution(client):
    """Verify research job submission, 7-agent execution, and report retrieval."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    exec_payload = {
        "query": f"Assess valuation impact of cloud transformation deals on TCS {uid}",
        "ticker": "TCS",
        "correlation_id": f"test-research-corr-{uid}",
    }
    res_exec = client.post("/api/v1/research/execute", json=exec_payload)
    assert res_exec.status_code == 200
    report = res_exec.json()

    assert report["ticker"] == "TCS"
    assert report["executive_summary"]
    assert report["bull_scenario"]
    assert report["base_scenario"]
    assert report["bear_scenario"]
    assert len(report["risks_and_counterarguments"]) > 0

    # Retrieve report by ID
    report_id = report["id"]
    res_get = client.get(f"/api/v1/research/reports/{report_id}")
    assert res_get.status_code == 200
    assert res_get.json()["ticker"] == "TCS"

    # List recent reports
    res_reports = client.get("/api/v1/research/reports")
    assert res_reports.status_code == 200
    assert len(res_reports.json()) >= 1


def test_alert_rules_and_evaluation(client):
    """Verify alert rule creation and evaluation."""
    # List or create alert rule
    res_rules = client.get("/api/v1/alert-rules")
    assert res_rules.status_code == 200

    # Evaluate alerts
    res_eval = client.post("/api/v1/alerts/evaluate")
    assert res_eval.status_code == 200
    data = res_eval.json()
    assert data["status"] == "EVALUATED"

    # List alerts
    res_alerts = client.get("/api/v1/alerts")
    assert res_alerts.status_code == 200


def test_audit_and_approvals(client):
    """Verify audit event queries and human approval workflows."""
    # 1. Audit trail
    res_audit = client.get("/api/v1/audit")
    assert res_audit.status_code == 200
    events = res_audit.json()
    assert len(events) >= 1

    # 2. Approvals list
    res_app = client.get("/api/v1/approvals")
    assert res_app.status_code == 200
