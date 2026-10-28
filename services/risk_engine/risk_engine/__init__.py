"""NGSIRS deterministic compliance risk engine.

Pure functions only: no I/O, no clock, no randomness. Everything the engine
needs arrives in fact records and rule definitions, so any score can be
reproduced from a stored snapshot and rule-set hash.
"""

from .dsl import RuleDefinition, RuleValidationError, validate_rule
from .evaluator import Outcome, evaluate
from .rulepack import load_pilot_pack

__all__ = ["Outcome", "RuleDefinition", "RuleValidationError", "evaluate", "load_pilot_pack", "validate_rule"]
