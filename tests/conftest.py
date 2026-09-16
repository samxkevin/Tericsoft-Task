"""Shared pytest configuration.

Sets a throwaway SQLite database BEFORE the backend modules are imported, so
tests never touch the real it_support.db. API-key variables are emptied so no
test can accidentally call a real LLM provider.
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TEST_DB = Path(tempfile.gettempdir()) / f"it_support_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

# Empty strings count as "not configured" in backend/llm.py, and real
# environment variables always win over values loaded from a .env file.
os.environ["GEMINI_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ["LLM_PROVIDER"] = "gemini"


def pytest_sessionfinish(session, exitstatus):
    _TEST_DB.unlink(missing_ok=True)
