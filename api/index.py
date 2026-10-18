"""Vercel /api handler for MarketPulse AI FastAPI application."""

import os
import sys
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

from marketpulse.api.app import app
