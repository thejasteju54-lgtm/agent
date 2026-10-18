import os
import sys
from pathlib import Path

# Set essential serverless environment flags before importing any marketpulse modules
os.environ["VERCEL"] = "1"
os.environ.setdefault("OPERATING_MODE", "cloud")
os.environ.setdefault("ENVIRONMENT", "production")
os.environ.setdefault("AI_MODEL_PROVIDER", "mock")

# Add project root and src to sys.path so package imports resolve seamlessly
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from marketpulse.api.app import app

# Vercel's Python runtime discovers and binds to the ASGI 'app' object
