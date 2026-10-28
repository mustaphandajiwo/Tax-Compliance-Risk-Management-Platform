from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NGSIRS_", env_file=".env", extra="ignore")

    environment: Literal["demo", "test", "staging", "production"] = "demo"
    database_url: str = "postgresql+psycopg://ngsirs_app:ngsirs_app@127.0.0.1:5432/ngsirs"
    owner_database_url: str = "postgresql+psycopg://ngsirs_owner:ngsirs_owner@127.0.0.1:5432/ngsirs"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_eager: bool = True

    # Object storage: "local" writes encrypted objects under storage_path; "s3" uses MinIO/S3.
    storage_backend: Literal["local", "s3"] = "local"
    storage_path: str = ".data/objects"
    s3_endpoint: str | None = None
    s3_bucket: str = "ngsirs-raw"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # Keys. Demo defaults are deterministic and clearly non-secret; production must inject from a vault.
    data_key_b64: str = "ZGVtby1vbmx5LWRhdGEta2V5LW5vdC1mb3ItcHJvZCE="  # 32 bytes, demo only
    token_key_b64: str = "ZGVtby1vbmx5LXRva2VuLWtleS1ub3QtZm9yLXByb2Q="  # noqa: S105 - demo only
    signing_key_path: str = ".data/keys/evidence_ed25519.pem"
    jwt_key_path: str = ".data/keys/dev_jwt_rsa.pem"

    # OIDC
    oidc_issuer: str = "ngsirs-dev-issuer"
    oidc_audience: str = "ngsirs-crm-api"
    oidc_jwks_url: str | None = None  # set for Keycloak / external IdP
    require_mfa: bool = False
    dev_auth_enabled: bool = True
    token_ttl_seconds: int = 3600

    default_tenant_code: str = "NGSIRS"
    outbound_messaging_enabled: bool = False
    rate_limit_per_minute: int = 600
    otel_exporter_endpoint: str | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    def is_demo(self) -> bool:
        return self.environment in ("demo", "test")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "production":
        insecure = [
            s.dev_auth_enabled,
            s.data_key_b64 == Settings.model_fields["data_key_b64"].default,
            s.token_key_b64 == Settings.model_fields["token_key_b64"].default,
            not s.require_mfa,
            s.oidc_jwks_url is None,
        ]
        if any(insecure):
            raise RuntimeError(
                "Refusing to start in production with demo keys, dev auth, missing JWKS or MFA disabled"
            )
    return s
