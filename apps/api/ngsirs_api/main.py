"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import errors
from .config import get_settings
from .db import get_engine
from .routers import auth, cases, imports, insights, integrations, legal, risks, rules, taxpayers


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "trace_id": errors.trace_id_var.get() or None,
                **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
            }
        )


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("ngsirs")
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def _configure_tracing(app: FastAPI) -> None:
    endpoint = get_settings().otel_exporter_endpoint
    if not endpoint:
        return
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "ngsirs-crm-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


class RateLimiter:
    """Per-client sliding window. A shared store (Redis) replaces this behind a gateway in production."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def create_app() -> FastAPI:
    s = get_settings()
    _configure_logging()
    app = FastAPI(
        title="NGSIRS Compliance Risk Management Platform API",
        version="1.0.0",
        description=(
            "Compliance risk engine for Niger State Internal Revenue Service. Produces versioned, explainable "
            "risk indicators - never tax assessments or enforcement decisions. Every outward action requires "
            "human approval. All endpoints require an OIDC bearer token carrying tenant and role claims."
        ),
        responses={code: {"model": errors_model()} for code in (400, 401, 403, 404, 409, 422, 429)},
    )
    errors.install(app)
    limiter = RateLimiter(s.rate_limit_per_minute)

    @app.middleware("http")
    async def context(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("x-trace-id")
        tid = incoming if incoming and len(incoming) <= 64 else uuid.uuid4().hex
        errors.trace_id_var.set(tid)
        client = request.headers.get("authorization", "")[-24:] or (
            request.client.host if request.client else "-"
        )
        if not limiter.allow(client):
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Too many requests",
                        "details": None,
                        "trace_id": tid,
                    }
                },
            )
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if s.is_demo():
            response.headers["X-Data-Classification"] = "SYNTHETIC"
        logging.getLogger("ngsirs.access").info(
            "%s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Purpose", "X-Trace-Id"],
        expose_headers=["X-Trace-Id"],
    )

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> dict:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "environment": s.environment}

    for r in (auth, imports, integrations, legal, rules, risks, taxpayers, cases, insights):
        app.include_router(r.router)
    _configure_tracing(app)
    return app


def errors_model():  # type: ignore[no-untyped-def]
    from .schemas import ErrorResponse

    return ErrorResponse


app = create_app()
