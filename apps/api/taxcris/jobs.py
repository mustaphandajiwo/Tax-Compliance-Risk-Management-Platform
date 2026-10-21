"""Database-backed job queue for ingestion and scoring workers (ADR-0003).

Jobs are idempotent: handlers can safely be retried after a crash. Workers claim jobs with
``SELECT … FOR UPDATE SKIP LOCKED`` so several can run side by side.
"""

import argparse
import logging
import time
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import session_factory
from .models import ImportBatch, Job, RiskRun

log = logging.getLogger("taxcris.jobs")
MAX_ATTEMPTS = 3


def _import_process(db: Session, payload: dict) -> None:
    from .domain import entity_resolution, ingestion

    batch = ingestion.process_batch(db, uuid.UUID(payload["batch_id"]))
    if batch.dataset == "taxpayers":
        entity_resolution.find_candidates(db, batch.tenant_id)


def _risk_run(db: Session, payload: dict) -> None:
    from .domain import scoring

    scoring.execute_run(db, uuid.UUID(payload["run_id"]))


HANDLERS = {"import.process": _import_process, "risk.run": _risk_run}
QUEUES = {"ingestion": ["import.process"], "risk": ["risk.run"], "all": list(HANDLERS)}


def enqueue(db: Session, tenant_id: uuid.UUID, kind: str, payload: dict) -> Job:
    job = Job(tenant_id=tenant_id, kind=kind, payload=payload)
    db.add(job)
    db.flush()
    return job


def _start(job: Job) -> None:
    job.status, job.attempts, job.started_at = "running", job.attempts + 1, datetime.now(timezone.utc)


def run_job(job_id: uuid.UUID, claimed: bool = False) -> Job:
    """Execute one job in its own transaction; failures are recorded, not raised."""
    Session_ = session_factory()
    if not claimed:
        with Session_() as db:
            job = db.get(Job, job_id)
            if job is None or job.status not in ("queued", "failed"):
                return job
            _start(job)
            db.commit()
    with Session_() as db:
        try:
            HANDLERS[job.kind](db, job.payload)
            job = db.get(Job, job_id)
            job.status, job.finished_at, job.error = "completed", datetime.now(timezone.utc), None
            db.commit()
        except Exception as exc:  # noqa: BLE001 - recorded for operators
            db.rollback()
            log.exception("job %s failed", job_id)
            job = db.get(Job, job_id)
            job.status = "failed" if job.attempts < MAX_ATTEMPTS else "dead"
            job.error = f"{type(exc).__name__}: {exc}"[:2000]
            job.finished_at = datetime.now(timezone.utc)
            _mark_target_failed(db, job, job.error)
            db.commit()
            if get_settings().inline_jobs and job.status == "dead":
                log.error(traceback.format_exc())
    return job


def _mark_target_failed(db: Session, job: Job, error: str) -> None:
    if job.kind == "import.process":
        b = db.get(ImportBatch, uuid.UUID(job.payload["batch_id"]))
        if b is not None:
            b.status, b.error = "failed", error
    elif job.kind == "risk.run":
        r = db.get(RiskRun, uuid.UUID(job.payload["run_id"]))
        if r is not None:
            r.status, r.error = "failed", error


def dispatch(job: Job) -> None:
    """Call after the enqueuing transaction commits."""
    if get_settings().inline_jobs:
        run_job(job.id)


def claim_next(kinds: list[str]) -> uuid.UUID | None:
    with session_factory()() as db:
        job = db.execute(
            select(Job)
            .where(Job.kind.in_(kinds), Job.status.in_(["queued", "failed"]), Job.attempts < MAX_ATTEMPTS)
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalars().first()
        if job is None:
            return None
        _start(job)
        db.commit()
        return job.id


def main() -> None:
    parser = argparse.ArgumentParser(description="TaxCRIS background worker")
    parser.add_argument("--queue", choices=sorted(QUEUES), default="all")
    parser.add_argument("--once", action="store_true", help="Drain the queue and exit")
    parser.add_argument("--poll", type=float, default=2.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    kinds = QUEUES[args.queue]
    log.info("worker started for %s", kinds)
    while True:
        job_id = claim_next(kinds)
        if job_id is None:
            if args.once:
                return
            time.sleep(args.poll)
            continue
        job = run_job(job_id, claimed=True)
        log.info("job %s %s -> %s", job_id, job.kind, job.status)


if __name__ == "__main__":
    main()
