"""Start the backend for the end-to-end tests on a fresh database."""

import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).parent.parent
DB = Path(__file__).parent / "test.db"

DB.unlink(missing_ok=True)
os.environ["UNDERCOVER_DB"] = str(DB)
sys.path.insert(0, str(ROOT))
uvicorn.run("backend.main:app", port=8100)
