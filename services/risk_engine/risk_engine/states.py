"""Controlled finding and case states (PRD section 14).

Transitions are explicit. Anything not listed is refused; callers map the
refusal to HTTP 409.
"""

from __future__ import annotations

FINDING_STATES = [
    "candidate",
    "validated",
    "review_required",
    "approved_for_treatment",
    "treated",
    "outcome_pending",
    "closed_confirmed",
    "closed_not_substantiated",
    "corrected",
    "withdrawn",
]
TERMINAL_FINDING_STATES = {"closed_confirmed", "closed_not_substantiated", "corrected", "withdrawn"}
OPEN_FINDING_STATES = set(FINDING_STATES) - TERMINAL_FINDING_STATES

FINDING_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"validated", "withdrawn"},
    "validated": {"review_required", "withdrawn"},
    "review_required": {"approved_for_treatment", "closed_not_substantiated", "corrected", "withdrawn"},
    "approved_for_treatment": {"treated", "review_required", "withdrawn", "corrected"},
    "treated": {"outcome_pending", "closed_confirmed", "corrected", "closed_not_substantiated"},
    "outcome_pending": {"closed_confirmed", "closed_not_substantiated", "corrected", "review_required"},
    "closed_confirmed": set(),
    "closed_not_substantiated": set(),
    "corrected": set(),
    "withdrawn": set(),
}

CASE_STAGES = [
    "pending_approval",
    "approved",
    "in_progress",
    "awaiting_response",
    "outcome_recorded",
    "closed",
    "rejected",
]
CASE_TRANSITIONS: dict[str, set[str]] = {
    "pending_approval": {"approved", "rejected"},
    "approved": {"in_progress", "closed"},
    "in_progress": {"awaiting_response", "outcome_recorded", "closed"},
    "awaiting_response": {"in_progress", "outcome_recorded", "closed"},
    "outcome_recorded": {"closed", "in_progress"},
    "closed": set(),
    "rejected": set(),
}

# Review decisions officers can record on a finding, and the state they lead to.
REVIEW_DECISIONS: dict[str, str | None] = {
    "confirm": "approved_for_treatment",
    "not_substantiated": "closed_not_substantiated",
    "corrected": "corrected",
    "withdraw": "withdrawn",
    "suppress": "withdrawn",
    "return_to_review": "review_required",
    "mark_disputed": None,
    "clear_disputed": None,
    "set_legal_hold": None,
    "clear_legal_hold": None,
    "refer_audit": None,
    "escalate": None,
}


class TransitionError(Exception):
    pass


def check_finding_transition(current: str, target: str) -> None:
    if target not in FINDING_TRANSITIONS.get(current, set()):
        raise TransitionError(f"finding cannot move from {current} to {target}")


def check_case_transition(current: str, target: str) -> None:
    if target not in CASE_TRANSITIONS.get(current, set()):
        raise TransitionError(f"case cannot move from {current} to {target}")
