"""Importer validation/quarantine, legal due-date resolution and finding state machine."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook

from importer import ParseError, ValidationContext, parse_file, validate_rows
from ngsirs_api.services.findings import path_to
from ngsirs_api.services.legal import due_date_for, period_range
from risk_engine.states import TransitionError, check_case_transition

CTX = ValidationContext(known_employers={"NGS-DEMO-EMP-0001"})
PAY_HEADER = (
    "payment_reference,employer_id,tax_type,period,paid_at,amount,reversal_status,settlement_status,"
    "allocation_status,bank_delay_dispute,credit_adjustment\n"
)


def _payments(*rows: str) -> tuple[list[str], list[dict[str, str]]]:
    return parse_file("p.csv", (PAY_HEADER + "\n".join(rows) + "\n").encode())


def test_invalid_period_is_quarantined_not_rejected() -> None:
    h, rows = _payments(
        "P1,NGS-DEMO-EMP-0001,PAYE,2026-13,2026-04-08T10:00:00+01:00,100,none,settled,,false,0"
    )
    r = validate_rows("ngsirs_payment", h, rows, None, CTX).results[0]
    assert r.status == "quarantined" and "invalid_period" in r.reasons


def test_unknown_employer_on_payment_is_accepted_as_unmatched() -> None:
    h, rows = _payments(
        "P2,NGS-DEMO-EMP-9999,PAYE,2026-03,2026-04-08T10:00:00+01:00,100,none,settled,,false,0"
    )
    r = validate_rows("ngsirs_payment", h, rows, None, CTX).results[0]
    assert r.status == "accepted" and any(m.startswith("unmatched_employer") for m in r.messages)


def test_unparseable_amount_is_rejected() -> None:
    h, rows = _payments(
        "P3,NGS-DEMO-EMP-0001,PAYE,2026-03,2026-04-08T10:00:00+01:00,abc,none,settled,,false,0"
    )
    assert validate_rows("ngsirs_payment", h, rows, None, CTX).results[0].status == "rejected"


def test_naive_timestamps_are_read_as_west_africa_time() -> None:
    h, rows = _payments("P4,NGS-DEMO-EMP-0001,PAYE,2026-03,2026-04-08T10:00:00,100,none,settled,,false,0")
    paid = validate_rows("ngsirs_payment", h, rows, None, CTX).results[0].values["paid_at"]
    assert paid.astimezone(UTC) == datetime(2026, 4, 8, 9, 0, tzinfo=UTC)


def test_duplicates_in_file() -> None:
    line = "P5,NGS-DEMO-EMP-0001,PAYE,2026-03,2026-04-08T10:00:00+01:00,100,none,settled,,false,0"
    h, rows = _payments(line, line, line.replace(",100,", ",200,"))
    statuses = [r.status for r in validate_rows("ngsirs_payment", h, rows, None, CTX).results]
    assert statuses == ["accepted", "duplicate", "quarantined"]


def test_invalid_tin_is_quarantined() -> None:
    csv_text = (
        "source_taxpayer_id,taxpayer_type,status,taxpayer_name,tin,jurisdiction\n"
        "T1,company,active,Example Demo Ltd,12345,NG-NI\n"
        "T2,company,active,Example Two Demo Ltd,NGS-DEMO-TIN-000002,NG-NI\n"
    )
    h, rows = parse_file("t.csv", csv_text.encode())
    res = validate_rows("ngsirs_taxpayer", h, rows, None, ValidationContext()).results
    assert [r.status for r in res] == ["quarantined", "accepted"]
    assert "invalid_identifier" in res[0].reasons


def test_missing_required_column_rejects_file() -> None:
    h, rows = parse_file("p.csv", b"payment_reference,amount\nP1,10\n")
    report = validate_rows("ngsirs_payment", h, rows, None, CTX)
    assert report.rejected_file and any("paid_at" in e for e in report.header_errors)


def test_field_mapping_translates_source_columns() -> None:
    h, rows = parse_file(
        "t.csv",
        b"TaxpayerNo,Type,State,Name,TIN,Juris\nT1,company,active,X Demo Ltd,NGS-DEMO-TIN-000001,NG-NI\n",
    )
    mapping = {
        "TaxpayerNo": "source_taxpayer_id",
        "Type": "taxpayer_type",
        "State": "status",
        "Name": "taxpayer_name",
        "TIN": "tin",
        "Juris": "jurisdiction",
    }
    assert (
        validate_rows("ngsirs_taxpayer", h, rows, mapping, ValidationContext()).results[0].status
        == "accepted"
    )


def test_xlsx_parsing() -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["a", "b"])
    ws.append([1, datetime(2026, 1, 2, 3, 4)])
    buf = io.BytesIO()
    wb.save(buf)
    headers, rows = parse_file("x.xlsx", buf.getvalue())
    assert headers == ["a", "b"] and rows[0]["b"].startswith("2026-01-02T03:04")


@pytest.mark.parametrize("name", ["x.exe", "x.json"])
def test_only_csv_and_xlsx(name: str) -> None:
    with pytest.raises(ParseError):
        parse_file(name, b"")


def test_due_dates_follow_legal_parameters_across_year_end() -> None:
    assert (
        due_date_for("2025-12", {"due_day_of_following_month": 10}).isoformat() == "2026-01-10T22:59:59+00:00"
    )
    assert due_date_for("2026-01", {"due_day_of_following_month": 31}).date().isoformat() == "2026-02-28"


def test_period_range() -> None:
    assert period_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_finding_paths_and_case_transitions() -> None:
    assert path_to("approved_for_treatment", "closed_confirmed") == ["treated", "closed_confirmed"]
    with pytest.raises(TransitionError):
        path_to("withdrawn", "review_required")
    with pytest.raises(TransitionError):
        check_case_transition("closed", "approved")
