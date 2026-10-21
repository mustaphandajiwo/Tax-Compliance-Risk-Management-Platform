import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import get_settings
from .routers import auth, cases, imports, reporting, risk, rules, taxpayers

log = logging.getLogger("taxcris")


def create_app() -> FastAPI:
    app = FastAPI(
        title="TaxCRIS API",
        version=__version__,
        description=(
            "Integrated Compliance Risk Management & Intelligence Platform for State Internal Revenue Services. "
            "Risk signals are indicators for human review — the platform makes no autonomous adverse decisions."
        ),
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
        # Never echo internals (which may include taxpayer values) back to the client.
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    for r in (auth, imports, taxpayers, rules, risk, cases, reporting):
        app.include_router(r.router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
