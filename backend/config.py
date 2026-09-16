"""Central configuration for the application.

Loads environment variables from a `.env` file at the project root (if
present) and exposes shared settings. Secrets (API keys) must only ever live
in `.env`, which is git-ignored; `.env.example` documents the placeholders.
Importing this module loads the environment exactly once.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root: the folder that contains backend/ and frontend/.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env once for the whole application.
# Real environment variables always take precedence over the .env file.
load_dotenv(BASE_DIR / ".env")

# SQLite database location. Defaults to <project root>/it_support.db so the
# file lands in the same place no matter which directory the server is
# started from. Override with DATABASE_URL in .env.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'it_support.db'}")
