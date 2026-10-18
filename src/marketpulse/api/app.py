from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from marketpulse.api.routes import (
    alerts,
    approvals,
    articles,
    audit,
    companies,
    health,
    n8n,
    research,
    schedules,
    tasks,
    watchlists,
    webhooks,
)
from marketpulse.agent.security import recover_interrupted_tasks
from marketpulse.config import mp_settings
from marketpulse.dashboard import DASHBOARD_STATIC_DIR
from marketpulse.storage.database import get_session, init_db, seed_initial_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager for database init and seed."""
    try:
        init_db()
        with get_session() as session:
            seed_initial_registry(session)
            recover_interrupted_tasks(session)
    except Exception as e:
        import logging
        logging.getLogger("marketpulse.api").warning("Startup database initialization notice: %s", e)
    yield


def create_app() -> FastAPI:
    """Create and configure the MarketPulse AI FastAPI application."""
    app = FastAPI(
        title="MarketPulse AI",
        description="Indian Financial-Market Intelligence Platform with n8n Automation Engine",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration for local Next.js frontend development and production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://localhost:8001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global sanitized exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # Prevent any potential internal key or database credential leakage in 500s
        error_msg = str(exc)
        if mp_settings.n8n_api_key and mp_settings.n8n_api_key in error_msg:
            error_msg = error_msg.replace(mp_settings.n8n_api_key, "[REDACTED]")
        if mp_settings.api_secret_key and mp_settings.api_secret_key in error_msg:
            error_msg = error_msg.replace(mp_settings.api_secret_key, "[REDACTED]")

        return JSONResponse(
            status_code=500,
            content={
                "status": "ERROR",
                "message": "Internal processing error occurred",
                "detail": error_msg[:200],
            },
        )

    # Root level endpoints for legacy/container probe compatibility
    app.include_router(health.router)
    app.include_router(webhooks.router, prefix="/webhook")

    # Register Routers under /api/v1
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix)
    app.include_router(tasks.router, prefix=prefix)
    app.include_router(n8n.router, prefix=prefix)
    app.include_router(companies.router, prefix=prefix)
    app.include_router(watchlists.router, prefix=prefix)
    app.include_router(articles.router, prefix=prefix)
    app.include_router(research.router, prefix=prefix)
    app.include_router(alerts.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(approvals.router, prefix=prefix)
    app.include_router(schedules.router, prefix=prefix)
    app.include_router(webhooks.router, prefix=f"{prefix}/webhook")

    # Static Assets & Web Dashboard Frontend
    try:
        if DASHBOARD_STATIC_DIR.exists():
            app.mount("/static", StaticFiles(directory=str(DASHBOARD_STATIC_DIR)), name="static")
    except Exception:
        pass

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def serve_dashboard():
        index_file = DASHBOARD_STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return HTMLResponse(
            "<!DOCTYPE html><html><head><title>MarketPulse AI</title><meta charset='utf-8'></head>"
            "<body style='font-family:sans-serif; background:#0d1117; color:#c9d1d9; padding:2rem; text-align:center;'>"
            "<h1 style='color:#58a6ff;'>MarketPulse AI</h1>"
            "<p>API and Research Runtime is active.</p>"
            "<p><a href='/api/v1/health' style='color:#7ee787;'>View Health Status (/api/v1/health)</a></p>"
            "</body></html>"
        )

    return app


app = create_app()
