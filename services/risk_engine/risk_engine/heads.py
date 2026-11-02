"""Revenue-head obligation patterns.

A *revenue head* is a tax, levy or charge the authority administers (personal income tax by direct
assessment, withholding tax, capital gains tax, stamp duties, land use charge, business premises
registration, motor vehicle licences, development levy, gaming taxes, fees and levies). Heads are
configured per authority in the jurisdiction pack. What is fixed in code is the small set of *patterns*
an obligation can follow, the legal parameters each pattern needs, and the obligation codes it uses.

Adding a head that follows an existing pattern is configuration. Adding a pattern is a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Pattern = Literal[
    "monthly_return_payment",
    "annual_return_payment",
    "annual_demand",
    "licence_renewal",
    "transaction",
    "annual_levy",
]
SubjectType = Literal["individual", "agent", "operator", "property", "premises", "vehicle", "business"]
Frequency = Literal["monthly", "annual", "event"]

HEAD_CODE_RE = r"^[A-Z][A-Z0-9]{1,11}$"


@dataclass(frozen=True)
class PatternSpec:
    pattern: str
    frequency: Frequency
    title: str
    # obligation-code suffix -> required legal parameters
    codes: dict[str, tuple[str, ...]]
    # who must act first: the taxpayer files/declares, or the authority serves a demand
    trigger: Literal["taxpayer_return", "authority_demand", "renewal", "event", "levy"]
    description: str


PATTERNS: dict[str, PatternSpec] = {
    p.pattern: p
    for p in [
        PatternSpec(
            "monthly_return_payment",
            "monthly",
            "Monthly return and remittance",
            {
                "MONTHLY_RETURN": ("due_day_of_following_month",),
                "MONTHLY_PAYMENT": ("due_day_of_following_month",),
            },
            "taxpayer_return",
            "The taxpayer or collecting agent files a return and remits by a day of the following month",
        ),
        PatternSpec(
            "annual_return_payment",
            "annual",
            "Annual self-assessment return and payment",
            {"ANNUAL_RETURN": ("due_month", "due_day"), "ANNUAL_PAYMENT": ("due_month", "due_day")},
            "taxpayer_return",
            "The taxpayer files an annual return for the tax year and pays by a date in the following year",
        ),
        PatternSpec(
            "annual_demand",
            "annual",
            "Annual demand notice",
            {"DEMAND": ("payment_days_after_service",)},
            "authority_demand",
            "The authority serves an annual demand notice; payment is due a number of days after service",
        ),
        PatternSpec(
            "licence_renewal",
            "annual",
            "Licence or registration renewal",
            {"RENEWAL": ("grace_days",)},
            "renewal",
            "A licence or registration expires on a recorded date and must be renewed within a grace period",
        ),
        PatternSpec(
            "transaction",
            "event",
            "Transaction-based declaration and payment",
            {"TRANSACTION": ("days_after_transaction",)},
            "event",
            "A recorded transaction (disposal, instrument) must be declared and paid within a number of days",
        ),
        PatternSpec(
            "annual_levy",
            "annual",
            "Annual flat levy",
            {"ANNUAL_LEVY": ("due_month", "due_day")},
            "levy",
            "A fixed annual levy payable by a date in the levy year",
        ),
    ]
}

PATTERN_SUFFIXES: dict[str, str] = {suffix: p.pattern for p in PATTERNS.values() for suffix in p.codes}


def obligation_codes(head: str, pattern: str) -> list[str]:
    return [f"{head}_{suffix}" for suffix in PATTERNS[pattern].codes]


def split_code(code: str) -> tuple[str, str] | None:
    """'LUC_DEMAND' -> ('LUC', 'DEMAND'); None when the code has no known pattern suffix."""
    for suffix in sorted(PATTERN_SUFFIXES, key=len, reverse=True):
        if code.endswith("_" + suffix) and len(code) > len(suffix) + 1:
            return code[: -(len(suffix) + 1)], suffix
    return None


def required_parameters(code: str) -> tuple[str, ...] | None:
    parts = split_code(code)
    if parts is None:
        return None
    return PATTERNS[PATTERN_SUFFIXES[parts[1]]].codes[parts[1]]
