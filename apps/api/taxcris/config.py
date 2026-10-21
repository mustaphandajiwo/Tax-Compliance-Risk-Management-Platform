from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAXCRIS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://taxcris:taxcris@localhost:5432/taxcris"
    # Signing key for access tokens. Must come from a secrets vault in any shared environment.
    jwt_secret: str = "dev-only-change-me-0123456789abcdef"
    jwt_ttl_minutes: int = 480
    # When true, background jobs (imports, risk runs) execute in-process right after being queued.
    # Production deployments set this to false and run `taxcris-worker`.
    inline_jobs: bool = True
    # Fixed "today" for reproducible demos and tests; None means the real current date.
    as_of: date | None = None
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def today() -> date:
    s = get_settings()
    return s.as_of or date.today()
