"""Shared test configuration.

Integration tests create a throwaway database (``ngsirs_test``), migrate it,
seed the NGSIRS tenant, load the synthetic fixture through the real import
pipeline and run one evaluation. A second, test-only organisation exists only
here, to prove tenant isolation; it never appears in the application seed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ngsirs-test-"))
ADMIN_URL = os.environ.get("NGSIRS_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5432/postgres")
DB_HOST = os.environ.get("NGSIRS_TEST_DB_HOST", "127.0.0.1:5432")
TEST_DB = "ngsirs_test"

os.environ.update(
    {
        "NGSIRS_ENVIRONMENT": "test",
        "NGSIRS_DATABASE_URL": f"postgresql+psycopg://ngsirs_app:ngsirs_app@{DB_HOST}/{TEST_DB}",
        "NGSIRS_OWNER_DATABASE_URL": f"postgresql+psycopg://ngsirs_owner:ngsirs_owner@{DB_HOST}/{TEST_DB}",
        "NGSIRS_STORAGE_PATH": str(_TMP / "objects"),
        "NGSIRS_SIGNING_KEY_PATH": str(_TMP / "keys" / "evidence.pem"),
        "NGSIRS_JWT_KEY_PATH": str(_TMP / "keys" / "jwt.pem"),
        "NGSIRS_RATE_LIMIT_PER_MINUTE": "100000",
    }
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures" / "ngsirs"
