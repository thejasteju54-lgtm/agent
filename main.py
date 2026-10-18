"""Root entry point for MarketPulse AI platform on Vercel and container environments."""

import os
import sys
from pathlib import Path

# Configure cloud & production defaults for serverless environment
os.environ["VERCEL"] = "1"
os.environ.setdefault("OPERATING_MODE", "cloud")
os.environ.setdefault("ENVIRONMENT", "production")
os.environ.setdefault("AI_MODEL_PROVIDER", "mock")

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"

for p in [str(SRC_DIR), str(ROOT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from marketpulse.api.app import app
    handler = app
except Exception as exc:
    import traceback
    err_trace = traceback.format_exc()
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="MarketPulse AI - Serverless Diagnostic Handler")

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
    async def diagnostic_catch_all(full_path: str):
        return JSONResponse(
            status_code=500,
            content={
                "status": "STARTUP_ERROR",
                "error": str(exc),
                "traceback": err_trace,
                "path": full_path,
            },
        )
    handler = app
