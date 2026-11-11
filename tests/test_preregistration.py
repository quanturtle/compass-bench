"""A report is confirmatory only when the run's stored spec names a preregistration."""

from compass_bench.contract.examples import example_runs
from compass_bench.domain.design.preregistration import ReportStatus, pool_status, run_status


def test_a_spec_without_a_preregistration_is_exploratory_and_one_naming_a_file_is_confirmatory() -> None:
    planned, _ = example_runs()["asserted"]
    named = planned.spec.model_copy(update={"preregistration": "../preregistrations/example-2026-01-01.md"})

    assert run_status(planned.spec) is ReportStatus.EXPLORATORY
    assert run_status(named) is ReportStatus.CONFIRMATORY


def test_a_pool_is_confirmatory_only_when_every_run_names_a_preregistration() -> None:
    planned, _ = example_runs()["asserted"]
    named = planned.spec.model_copy(update={"preregistration": "../preregistrations/example-2026-01-01.md"})

    assert pool_status([named, named]) is ReportStatus.CONFIRMATORY
    assert pool_status([named, planned.spec]) is ReportStatus.EXPLORATORY
    assert pool_status([]) is ReportStatus.EXPLORATORY
