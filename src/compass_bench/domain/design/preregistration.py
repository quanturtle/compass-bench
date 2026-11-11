"""Whether a report's claims are confirmatory or exploratory.

A run whose stored spec names a preregistration committed before any reply was seen is confirmatory; every other run
is exploratory, which includes every run stored before the field existed. A pool is confirmatory only when every
run in it is.
"""

from collections.abc import Iterable
from enum import StrEnum

from compass_bench.domain.design.experiment import ExperimentSpec


class ReportStatus(StrEnum):
    EXPLORATORY = "exploratory"
    CONFIRMATORY = "confirmatory"


def run_status(spec: ExperimentSpec) -> ReportStatus:
    return ReportStatus.CONFIRMATORY if spec.preregistration is not None else ReportStatus.EXPLORATORY


def pool_status(specs: Iterable[ExperimentSpec]) -> ReportStatus:
    """Confirmatory only when every run of the pool names a preregistration."""
    statuses = {run_status(spec) for spec in specs}
    return ReportStatus.CONFIRMATORY if statuses == {ReportStatus.CONFIRMATORY} else ReportStatus.EXPLORATORY
