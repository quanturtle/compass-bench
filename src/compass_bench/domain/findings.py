"""Validation and pre-flight findings: every check runs, and every finding is returned."""

from collections.abc import Sequence
from enum import StrEnum

from compass_bench.domain.value import Value


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class FindingCode(StrEnum):
    DUPLICATE_QUESTION = "duplicate_question"
    EMPTY_AXIS = "empty_axis"
    SCALE_TOO_SHORT = "scale_too_short"
    DUPLICATE_MODEL = "duplicate_model"
    NO_MODELS = "no_models"
    UNKNOWN_MODEL = "unknown_model"
    UNKNOWN_ENDPOINT = "unknown_endpoint"
    EMPTY_FACTOR = "empty_factor"
    DUPLICATE_LEVEL = "duplicate_level"
    DUPLICATE_FACTOR = "duplicate_factor"
    INVALID_PROMPT_TEMPLATE = "invalid_prompt_template"
    BELOW_QUESTION_FLOOR = "below_question_floor"
    UNVARIED_FACTOR = "unvaried_factor"
    FACET_ON_BOTH_AXES = "facet_on_both_axes"
    NEGATED_STATEMENT = "negated_statement"
    JUSTIFYING_CLAUSE = "justifying_clause"
    UNEQUAL_FACETS = "unequal_facets"
    UNPINNED_ENDPOINT = "unpinned_endpoint"
    SINGLE_WORDING = "single_wording"
    NO_LISTING = "no_listing"
    UNSUPPORTED_PARAMETER = "unsupported_parameter"
    FRESH_LISTING = "fresh_listing"
    MIXED_SERVED_MODELS = "mixed_served_models"
    RUNS_FAR_APART = "runs_far_apart"
    MIXED_ELICITATIONS = "mixed_elicitations"
    MIXED_ROUTING = "mixed_routing"
    PREREGISTRATION_MISSING = "preregistration_missing"
    PREREGISTRATION_UNCOMMITTED = "preregistration_uncommitted"


class Finding(Value):
    severity: Severity
    code: FindingCode
    message: str


def has_errors(findings: Sequence[Finding]) -> bool:
    return any(finding.severity is Severity.ERROR for finding in findings)
