"""Background jobs (Celery): scheduled evaluations and large import commits.

Each task receives an explicit tenant id and opens a tenant-bound session, so a
job can never read another tenant's rows (row-level security applies to
workers exactly as to API requests).

Run:  celery -A ngsirs_api.worker worker --beat --loglevel=info
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from celery import Celery
from celery.schedules import crontab

from .config import get_settings
from .db import resolve_tenant_id, tenant_session

settings = get_settings()
celery_app = Celery("ngsirs", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_eager,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="Africa/Lagos",
    beat_schedule={
        # Nightly operational evaluation as at the latest committed extracts (shadow mode stays internal).
        "nightly-evaluation": {"task": "ngsirs.evaluate_latest", "schedule": crontab(hour=2, minute=17)},
        # Pull connectors whose schedule is due (each connector sets its own interval).
        "connector-poll": {"task": "ngsirs.poll_connectors", "schedule": crontab(minute="*/5")},
    },
)


@celery_app.task(name="ngsirs.evaluate", bind=True, max_retries=2)
def evaluate(self: Any, tenant_id: str, as_of: str, period_from: str, period_to: str) -> dict[str, Any]:
    from .services.evaluation import run_evaluation

    with tenant_session(uuid.UUID(tenant_id)) as db:
        run, created = run_evaluation(
            db,
            "system:scheduler",
            uuid.UUID(tenant_id),
            as_of=datetime.fromisoformat(as_of),
            period_from=period_from,
            period_to=period_to,
        )
        return {"run_id": str(run.id), "created": created, "counts": run.counts}


@celery_app.task(name="ngsirs.evaluate_latest")
def evaluate_latest() -> dict[str, Any] | None:
    """Evaluate the trailing 12 due periods for the configured tenant as at now."""
    from .services.legal import period_range

    tid = resolve_tenant_id(settings.default_tenant_code)
    if tid is None:
        return None
    now = datetime.now(UTC)
    end = now.year * 12 + now.month - 1 - 2  # latest period whose due dates have normally passed

    def code(i: int) -> str:
        return f"{i // 12:04d}-{i % 12 + 1:02d}"

    periods = period_range(code(end - 11), code(end))
    result: dict[str, Any] = evaluate(str(tid), now.isoformat(), periods[0], periods[-1])
    return result


@celery_app.task(name="ngsirs.poll_connectors")
def poll_connectors() -> list[dict[str, Any]]:
    from .services import integrations

    tid = resolve_tenant_id(settings.default_tenant_code)
    if tid is None:
        return []
    out = []
    with tenant_session(tid) as db:
        for c in integrations.due_connectors(db):
            for feed in (c.config or {}).get("feeds", {}):
                run = integrations.run_pull(db, c, feed, trigger="schedule")
                out.append({"connector": c.code, "feed": feed, "status": run.status})
    return out
