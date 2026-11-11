"""The statistical audit's rates, their errors, and its simulated populations."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from compass_bench.domain.axis_pair import Polarity
from compass_bench.domain.design.factors import DisplayOrder
from compass_bench.domain.outcome import Replied
from compass_bench.domain.reading.reading import RatingRead
from compass_bench.domain.scoring import phrasing_values, question_scores
from tests.builders.analysis import pending_record, position, rated_record

SCRIPT: Final = Path(__file__).parent.parent / "scripts" / "statistical_audit.py"


def load_audit() -> ModuleType:
    """The audit script as a module; it lives outside the package."""
    location = importlib.util.spec_from_file_location("statistical_audit", SCRIPT)
    assert location is not None and location.loader is not None
    module = importlib.util.module_from_spec(location)
    location.loader.exec_module(module)
    return module


AUDIT: Final = load_audit()


def test_wilson_interval_stays_inside_the_unit_interval_and_narrows_with_more_trials() -> None:
    low, high = AUDIT.wilson_interval(0, 10)
    assert 0.0 <= low < 1e-12 and high == pytest.approx(0.2775, abs=1e-4)
    narrow = AUDIT.wilson_interval(950, 1000)
    wide = AUDIT.wilson_interval(95, 100)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]


def test_monte_carlo_error_is_the_binomial_standard_error() -> None:
    assert AUDIT.monte_carlo_error(1900, 2000) == pytest.approx(0.004873, abs=1e-6)
    assert AUDIT.monte_carlo_error(0, 2000) == 0.0


def test_an_interval_misses_its_target_on_one_side_only() -> None:
    below = position(-0.5, -0.1, 10, 1.0)
    above = position(0.1, 0.5, 10, 1.0)
    across = position(-0.1, 0.1, 10, 1.0)

    assert (AUDIT.misses_below(below, 0.0), AUDIT.misses_above(below, 0.0), AUDIT.covers(below, 0.0)) == (
        True,
        False,
        False,
    )
    assert (AUDIT.misses_below(above, 0.0), AUDIT.misses_above(above, 0.0), AUDIT.covers(above, 0.0)) == (
        False,
        True,
        False,
    )
    assert (AUDIT.misses_below(across, 0.0), AUDIT.misses_above(across, 0.0), AUDIT.covers(across, 0.0)) == (
        False,
        False,
        True,
    )
    assert AUDIT.covers(above, 0.3) and AUDIT.misses_below(above, 0.6)


def test_only_a_rating_at_either_end_of_the_scale_is_extreme() -> None:
    assert AUDIT.is_extreme(rated_record("model", "x-00", Polarity.POSITIVE, 1))
    assert AUDIT.is_extreme(rated_record("model", "x-00", Polarity.POSITIVE, 5))
    assert not AUDIT.is_extreme(rated_record("model", "x-00", Polarity.POSITIVE, 4))
    assert not AUDIT.is_extreme(pending_record("model", "x-00", Polarity.POSITIVE))


def quiet_scenario(lean: int, wordings: int = 1, wording_sd: float = 0.0) -> Any:
    """No question, statement or repetition effects, so only the lean and a shared wording shift move a rating."""
    return AUDIT.null_scenario(
        "quiet",
        2,
        1,
        0.0,
        0.0,
        0.0,
        lean,
        wordings=wordings,
        wording_sd=wording_sd,
        model_wording_sd=0.0,
        question_wording_sd=0.0,
        noise=AUDIT.NoiseKind.GAUSSIAN,
    )


def test_every_null_scenarios_population_position_is_zero_for_both_models() -> None:
    null = [
        scenario
        for scenario in AUDIT.scenarios()
        if scenario.position_points == 0 and scenario.negative_statement_lean == 0 and scenario.second_shift_share == 0
    ]

    assert len(null) >= 16
    for scenario in null:
        for model in AUDIT.MODELS:
            assert AUDIT.population_position(scenario, model) == pytest.approx(0.0, abs=1e-12), scenario.name


def test_a_stance_without_spread_reads_as_half_a_point_per_point_and_clamping_pulls_a_spread_stance_toward_zero() -> (
    None
):
    clean = quiet_scenario(0).model_copy(update={"position_points": 1})
    spread = clean.model_copy(update={"question_sd": 2.0})

    assert AUDIT.population_position(clean, AUDIT.MODELS[0]) == pytest.approx(0.5)
    assert AUDIT.stance_position(clean, AUDIT.MODELS[0]) == pytest.approx(0.5)
    assert 0.0 < AUDIT.population_position(spread, AUDIT.MODELS[0]) < 0.5
    assert AUDIT.run_errors(clean, 0).covered == 1.0


def test_a_lean_on_the_negative_pole_statements_moves_the_population_position_but_not_the_stance() -> None:
    leaning = quiet_scenario(0).model_copy(update={"negative_statement_lean": 1})

    assert AUDIT.stance_position(leaning, AUDIT.MODELS[0]) == 0.0
    assert AUDIT.population_position(leaning, AUDIT.MODELS[0]) == pytest.approx(-0.25)
    assert AUDIT.run_errors(leaning, 0).stance_covered < 1.0


def test_the_second_models_shift_share_and_spread_apply_to_it_alone() -> None:
    gapped = quiet_scenario(0).model_copy(update={"second_shift_share": 1.0})
    broad = AUDIT.observed_scenario("broad", 0.0, 0.0, 0.0).model_copy(update={"second_spread": 2.0})

    assert AUDIT.population_position(gapped, AUDIT.MODELS[0]) == 0.0
    assert AUDIT.population_position(gapped, AUDIT.MODELS[1]) == pytest.approx(0.5)
    assert AUDIT.stance_position(gapped, AUDIT.MODELS[1]) == pytest.approx(0.5)
    assert AUDIT.own_question_sd(broad, AUDIT.MODELS[1]) == 2 * AUDIT.own_question_sd(broad, AUDIT.MODELS[0])


def test_models_sharing_every_question_effect_draw_the_same_question_scores() -> None:
    shared = AUDIT.observed_scenario("shared", 0.0, 0.0, 0.0).model_copy(
        update={"question_correlation": 1.0, "statement_sd": 0.0, "repetition_sd": 0.0, "questions_per_axis": 4}
    )
    questionnaire = AUDIT.audit_questionnaire(4)

    records = AUDIT.simulate_records(shared, 0)
    scores = question_scores(phrasing_values(records, questionnaire.scale), questionnaire, AUDIT.MODELS)

    assert [score.score for score in scores[AUDIT.MODELS[0]]] == [score.score for score in scores[AUDIT.MODELS[1]]]


def test_facet_offsets_name_the_facets_in_turn_and_weigh_them_by_their_questions() -> None:
    offsets = quiet_scenario(0).model_copy(update={"questions_per_axis": 5, "facet_offsets": (1, -1)})

    questionnaire = AUDIT.audit_questionnaire(5, 2)

    assert [question.facet for question in questionnaire.questions[:5]] == ["facet 0"] * 0 + [
        "facet 0",
        "facet 1",
        "facet 0",
        "facet 1",
        "facet 0",
    ]
    assert AUDIT.facet_weights(offsets) == {"facet 0": 0.6, "facet 1": 0.4}
    assert AUDIT.stance_position(offsets, AUDIT.MODELS[0]) == pytest.approx(0.1)


def test_per_run_shares_give_the_single_model_error_when_the_two_models_miss_together() -> None:
    together = [1.0, 0.0] * 10
    apart = [0.5] * 20

    mean, interval, error = AUDIT.share_statistics(together)

    assert mean == 0.5
    assert error == pytest.approx(AUDIT.monte_carlo_error(10, 20) * (20 / 19) ** 0.5)
    assert interval[0] < 0.5 < interval[1]
    assert AUDIT.share_statistics(apart) == (0.5, (0.5, 0.5), 0.0)


def test_a_midpoint_responder_scores_zero_on_every_question_and_is_always_covered() -> None:
    midpoint = AUDIT.responder_scenario("always midpoint", AUDIT.NoiseKind.GAUSSIAN)
    questionnaire = AUDIT.audit_questionnaire(midpoint.questions_per_axis)

    records = AUDIT.simulate_records(midpoint, 0)
    scores = question_scores(phrasing_values(records, questionnaire.scale), questionnaire, AUDIT.MODELS)

    assert {score.score for model_scores in scores.values() for score in model_scores} == {0.0}
    assert AUDIT.run_errors(midpoint, 0).covered == 1.0


def test_a_uniform_responders_ratings_cover_the_scale_and_ignore_the_lean() -> None:
    uniform = AUDIT.responder_scenario("uniform", AUDIT.NoiseKind.UNIFORM).model_copy(update={"first_option_lean": 2})

    records = AUDIT.simulate_records(uniform, 0)
    ratings = [
        record.outcome.reading.canonical
        for record in records
        if isinstance(record.outcome, Replied) and isinstance(record.outcome.reading, RatingRead)
    ]

    assert len(ratings) == len(records)
    assert set(ratings) == set(range(1, len(AUDIT.LABELS) + 1))


def test_a_stored_result_agrees_with_its_own_re_run_and_disagrees_with_a_moved_rate(tmp_path: Path) -> None:
    scenario = AUDIT.scenarios()[0]
    provenance = AUDIT.Provenance(code_revision="test", command="test")
    stored = AUDIT.run_scenario(scenario, 20, 0, provenance)
    AUDIT.write_results((stored,), tmp_path / "audit.json")

    assert AUDIT.load_results(tmp_path / "audit.json") == (stored,)
    assert AUDIT.check_results((stored,), None, provenance) == ()
    moved = stored.model_copy(update={"coverage": stored.coverage - 0.5})
    assert len(AUDIT.check_results((moved,), None, provenance)) == 1
    assert AUDIT.table_row(stored).startswith(f"| {scenario.name} | 10 | +0.00 | {stored.coverage:.3f} ± ")


def test_a_lean_toward_the_first_listed_choice_moves_the_displayed_rating_toward_the_top_of_the_list() -> None:
    assert AUDIT.first_option_shift(DisplayOrder.ASCENDING, 2) == -2
    assert AUDIT.first_option_shift(DisplayOrder.DESCENDING, 2) == 2


def test_a_first_option_lean_cancels_exactly_across_the_four_conditions() -> None:
    questionnaire = AUDIT.audit_questionnaire(2)
    records = AUDIT.simulate_records(quiet_scenario(1), 0)

    scores = question_scores(phrasing_values(records, questionnaire.scale), questionnaire, AUDIT.MODELS)

    assert {score.score for model_scores in scores.values() for score in model_scores} == {0.0}
    assert not any(AUDIT.is_extreme(record) for record in records)


def test_a_lean_past_the_scale_end_is_clamped_counted_as_extreme_and_still_cancels() -> None:
    outcome = AUDIT.run_errors(quiet_scenario(3), 0)

    assert outcome.extreme_ratings == outcome.ratings
    assert outcome.covered == 1.0


def test_three_wordings_are_asked_as_twelve_conditions_and_one_as_four() -> None:
    assert len(AUDIT.audit_conditions(1)) == 4
    assert len(AUDIT.audit_conditions(3)) == 12
    assert {condition.instruction for condition in AUDIT.audit_conditions(3)} == {"wording 1", "wording 2", "wording 3"}


def test_a_shared_wording_shift_moves_every_question_alike_so_the_interval_over_questions_cannot_see_it() -> None:
    questionnaire = AUDIT.audit_questionnaire(2)
    records = AUDIT.simulate_records(quiet_scenario(0, wordings=3, wording_sd=3.0), 0)

    scores = question_scores(phrasing_values(records, questionnaire.scale), questionnaire, AUDIT.MODELS)

    # every question carries the same mean shift over the three wordings, so the scores agree and the interval
    # is a point; it covers 0 only when the three integer shifts happen to sum to 0
    for model_scores in scores.values():
        assert len({score.score for score in model_scores}) == 1
    outcome = AUDIT.run_errors(quiet_scenario(0, wordings=3, wording_sd=3.0), 0)
    assert outcome.covered < 1.0


def test_a_scenario_result_carries_its_rates_errors_and_miss_sides() -> None:
    scenario = AUDIT.scenarios()[0]
    provenance = AUDIT.Provenance(code_revision="test", command="test")

    result = AUDIT.run_scenario(scenario, 20, 0, provenance)

    shares = [AUDIT.run_errors(scenario, index).covered for index in range(20)]
    assert (result.coverage, result.coverage_mcse) == AUDIT.share_statistics(shares)[::2]
    assert result.misses_below + result.misses_above <= 2 * (40 - round(result.coverage * 40))
    assert 0.0 <= result.extreme_share <= 1.0
    assert (result.population_position, result.stance, result.bias) == (0.0, 0.0, 0.0)
    assert result.ordering_mcse == AUDIT.monte_carlo_error(round(result.ordering_rate * 20), 20)
