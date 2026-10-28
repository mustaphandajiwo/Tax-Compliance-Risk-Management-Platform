"""Standard error contract: {"error": {"code", "message", "details", "trace_id"}}."""

from __future__ import annotations

import contextvars
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from risk_engine.states import TransitionError

log = logging.getLogger("ngsirs.api")
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def current_trace_id() -> str:
    tid = trace_id_var.get()
    if not tid:
        tid = uuid.uuid4().hex
        trace_id_var.set(tid)
    return tid


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def bad_request(message: str, details: Any = None) -> ApiError:
    return ApiError(400, "bad_request", message, details)


def forbidden(message: str = "Not permitted", details: Any = None) -> ApiError:
    return ApiError(403, "forbidden", message, details)


def not_found(what: str = "Resource") -> ApiError:
    # Same response whether the row is absent or belongs to another tenant: no existence leak.
    return ApiError(404, "not_found", f"{what} not found")


def conflict(message: str, details: Any = None) -> ApiError:
    return ApiError(409, "conflict", message, details)


def unprocessable(message: str, details: Any = None) -> ApiError:
    return ApiError(422, "unprocessable", message, details)


def _body(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "details": details, "trace_id": current_trace_id()}
        },
        headers={"X-Trace-Id": current_trace_id()},
    )


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return _body(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }
        return _body(exc.status_code, codes.get(exc.status_code, "error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _body(422, "validation_error", "Request failed validation", details)

    @app.exception_handler(TransitionError)
    async def _transition(_: Request, exc: TransitionError) -> JSONResponse:
        return _body(409, "invalid_transition", str(exc))

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        log.info("integrity conflict: %s", exc.orig)
        return _body(409, "conflict", "The change conflicts with existing data")

    @app.exception_handler(DBAPIError)
    async def _db(_: Request, exc: DBAPIError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == "42501":  # insufficient_privilege: immutability / append-only triggers
            return _body(409, "immutable", str(exc.orig).splitlines()[0])
        log.exception("database error")
        return _body(500, "internal_error", "Internal error")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _body(500, "internal_error", "Internal error")
