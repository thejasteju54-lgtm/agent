"""Vercel Serverless Function entry point for MarketPulse AI FastAPI application."""

import os
import sys
import traceback
from pathlib import Path

# Configure cloud & production defaults for serverless environment
os.environ["VERCEL"] = "1"
os.environ.setdefault("OPERATING_MODE", "cloud")
os.environ.setdefault("ENVIRONMENT", "production")
os.environ.setdefault("AI_MODEL_PROVIDER", "mock")

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
SRC_DIR = ROOT_DIR / "src"

for p in [str(SRC_DIR), str(ROOT_DIR), str(CURRENT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from marketpulse.api.app import app
except Exception as e:
    err_tb = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="MarketPulse AI - Diagnostic Fallback")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def debug_error(full_path: str):
        return HTMLResponse(
            f"<!DOCTYPE html><html><head><title>MarketPulse AI - Startup Error</title></head>"
            f"<body style='font-family:monospace; background:#0d1117; color:#f85149; padding:2rem;'>"
            f"<h2>MarketPulse AI Startup Error on Vercel</h2>"
            f"<pre style='background:#161b22; border:1px solid #30363d; padding:1.5rem; border-radius:8px; color:#c9d1d9; overflow:auto;'>{err_tb}</pre>"
            f"</body></html>",
            status_code=500,
        )
