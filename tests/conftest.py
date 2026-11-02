"""Shared test configuration.

Integration tests create a throwaway database (``taxrisk_test``), migrate it,
seed the demo authority tenant, load the synthetic fixture through the real import
pipeline and run one evaluation. A second, test-only organisation exists only
here, to prove tenant isolation; it never appears in the application seed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="taxrisk-test-"))
ADMIN_URL = os.environ.get("TAXRISK_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5432/postgres")
DB_HOST = os.environ.get("TAXRISK_TEST_DB_HOST", "127.0.0.1:5432")
TEST_DB = "taxrisk_test"

os.environ.update(
    {
        "TAXRISK_ENVIRONMENT": "test",
        "TAXRISK_DATABASE_URL": f"postgresql+psycopg://taxrisk_app:taxrisk_app@{DB_HOST}/{TEST_DB}",
        "TAXRISK_OWNER_DATABASE_URL": f"postgresql+psycopg://taxrisk_owner:taxrisk_owner@{DB_HOST}/{TEST_DB}",
        "TAXRISK_STORAGE_PATH": str(_TMP / "objects"),
        "TAXRISK_SIGNING_KEY_PATH": str(_TMP / "keys" / "evidence.pem"),
        "TAXRISK_JWT_KEY_PATH": str(_TMP / "keys" / "jwt.pem"),
        "TAXRISK_RATE_LIMIT_PER_MINUTE": "100000",
    }
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures" / "demo"
