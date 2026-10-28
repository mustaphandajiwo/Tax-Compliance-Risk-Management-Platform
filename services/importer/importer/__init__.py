"""NGSIRS importer: feed profiles, parsing and row validation (no database access)."""

from .feeds import FEEDS, SCHEMA_VERSION, FeedProfile
from .parsing import ParseError, parse_file
from .validation import ValidationContext, ValidationReport, unmapped_columns, validate_rows

__all__ = [
    "FEEDS",
    "SCHEMA_VERSION",
    "FeedProfile",
    "ParseError",
    "ValidationContext",
    "ValidationReport",
    "parse_file",
    "unmapped_columns",
    "validate_rows",
]
