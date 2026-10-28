"""Operations CLI: migrate, seed, load fixtures, evaluate, verify golden fixture, export OpenAPI."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "fixtures" / "ngsirs"


def system_principal(tenant_id: uuid.UUID, username: str, roles: tuple[str, ...]):  # type: ignore[no-untyped-def]
    from .security.auth import Principal

    return Principal(
        sub=f"system|{username}",
        username=username,
        display_name=username,
        tenant_id=tenant_id,
        tenant_code="NGSIRS",
        roles=roles,
        purposes=("data_quality",),
        kind="service",
    )


def migrate(url: str | None = None) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "apps" / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "apps" / "api" / "migrations"))
    if url:
        cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


def load_fixtures(tenant_id: uuid.UUID, directory: Path = FIXTURES) -> list[dict[str, Any]]:
    from .db import tenant_session
    from .services import imports

    manifest = json.loads((directory / "manifest.json").read_text())
    steward = system_principal(tenant_id, "system:fixture-loader", ("data_steward",))
    out = []
    for load in manifest["loads"]:
        path = directory / load["file"]
        if not path.exists():
            continue
        with tenant_session(tenant_id) as db:
            batch, created = imports.create_batch(
                db,
                steward,
                source_name=load["source"],
                feed_type=load["feed_type"],
                file_name=path.name,
                content=path.read_bytes(),
                extracted_at=datetime.fromisoformat(load["extracted_at"]),
                coverage_from=load.get("coverage_from"),
                coverage_to=load.get("coverage_to"),
            )
            if created and batch.qa_status == "validated":
                imports.commit_batch(db, steward, batch.id)
            out.append(
                {
                    "file": load["file"],
                    "status": batch.qa_status,
                    "rows": batch.row_count,
                    "accepted": batch.accepted_count,
                    "quarantined": batch.quarantined_count,
                    "rejected": batch.rejected_count,
                    "created": created,
                }
            )
    return out


def evaluate(tenant_id: uuid.UUID, as_of: datetime, period_from: str, period_to: str) -> dict[str, Any]:
    from .db import tenant_session
    from .serializers import run_out
    from .services import evaluation

    with tenant_session(tenant_id) as db:
        run, created = evaluation.run_evaluation(
            db, "system:scheduler", tenant_id, as_of=as_of, period_from=period_from, period_to=period_to
        )
        return {**run_out(db, run), "reused": not created}


def actual_findings(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    from .db import tenant_session
    from .models import RiskFinding

    with tenant_session(tenant_id) as db:
        rows = db.execute(
            select(RiskFinding).where(
                RiskFinding.superseded_by_id.is_(None), RiskFinding.status != "withdrawn"
            )
        ).scalars()
        out = []
        for f in rows:
            hold = "data_hold" if f.data_hold else "legal_hold" if f.legal_hold else None
            out.append(
                {
                    "rule_id": f.rule_code,
                    "subject": f.subject_id,
                    "period": f.period_code,
                    "status": f.status,
                    "hold": hold,
                }
            )
    return sorted(out, key=lambda r: (r["rule_id"], r["subject"], r["period"] or ""))


def compare_golden(tenant_id: uuid.UUID, directory: Path = FIXTURES) -> dict[str, Any]:
    expected = json.loads((directory / "expected_findings.json").read_text())["findings"]
    actual = actual_findings(tenant_id)

    def key(r: dict[str, Any]) -> tuple:
        return (r["rule_id"], r["subject"], r["period"], r["status"], r["hold"])

    exp, act = {key(r) for r in expected}, {key(r) for r in actual}
    return {
        "expected": len(exp),
        "actual": len(act),
        "missing": sorted(exp - act, key=str),
        "unexpected": sorted(act - exp, key=str),
        "match": exp == act,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ngsirs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    seed_p = sub.add_parser("seed")
    seed_p.add_argument("--users", default=str(FIXTURES / "users.csv"))
    sub.add_parser("load-fixtures")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--as-of")
    ev.add_argument("--from", dest="period_from")
    ev.add_argument("--to", dest="period_to")
    sub.add_parser("verify-golden")
    cr = sub.add_parser("connector-run", help="pull now from a connector, e.g. COLLECTION-PLATFORM")
    cr.add_argument("code")
    cr.add_argument("--feed", default="ngsirs_payment")
    sub.add_parser("demo", help="migrate + seed + load fixtures + evaluate (synthetic data)")
    oa = sub.add_parser("export-openapi")
    oa.add_argument("path", nargs="?", default=str(REPO / "packages" / "contracts" / "openapi.json"))
    args = parser.parse_args(argv)

    from .config import get_settings

    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "seed":
        from .seed import seed_all

        print(f"tenant {seed_all(Path(args.users))}")
    elif args.cmd in ("load-fixtures", "evaluate", "verify-golden", "demo"):
        from .db import resolve_tenant_id
        from .seed import seed_all

        if args.cmd == "demo":
            if not get_settings().is_demo():
                print("demo refuses to run outside demo/test environments", file=sys.stderr)
                return 2
            migrate()
            seed_all(FIXTURES / "users.csv")
        tid = resolve_tenant_id(get_settings().default_tenant_code)
        if tid is None:
            print("tenant not seeded; run `ngsirs seed`", file=sys.stderr)
            return 1
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        if args.cmd in ("load-fixtures", "demo"):
            for r in load_fixtures(tid):
                print(json.dumps(r))
        if args.cmd in ("evaluate", "demo"):
            as_of = datetime.fromisoformat(getattr(args, "as_of", None) or manifest["as_of"])
            result = evaluate(
                tid,
                as_of,
                getattr(args, "period_from", None) or manifest["period_from"],
                getattr(args, "period_to", None) or manifest["period_to"],
            )
            print(
                json.dumps(
                    {k: result[k] for k in ("id", "status", "counts", "reused")}, indent=2, default=str
                )
            )
        if args.cmd in ("verify-golden", "demo"):
            res = compare_golden(tid)
            print(json.dumps(res, indent=2, default=str))
            if not res["match"]:
                return 1
    elif args.cmd == "connector-run":
        from .db import resolve_tenant_id, tenant_session
        from .services import integrations

        tid = resolve_tenant_id(get_settings().default_tenant_code)
        if tid is None:
            print("tenant not seeded; run `ngsirs seed`", file=sys.stderr)
            return 1
        with tenant_session(tid) as db:
            run = integrations.run_pull(
                db, integrations.get_connector(db, args.code), args.feed, trigger="manual"
            )
            print(json.dumps(integrations.run_payload(run), indent=2))
            if run.status == "failed":
                return 1
    elif args.cmd == "export-openapi":
        from .main import app

        Path(args.path).parent.mkdir(parents=True, exist_ok=True)
        Path(args.path).write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
