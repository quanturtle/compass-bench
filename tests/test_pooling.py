"""Pools: which runs combine, and what combining them does to a model's results."""

import asyncio
from collections.abc import Mapping
from datetime import timedelta

import pytest

from compass_bench.app.pool import pooled_reports
from compass_bench.contract.examples import (
    ENDPOINT,
    EXAMPLE_ENDPOINT,
    example_endpoints,
    example_runs,
    pooled_example_runs,
)
from compass_bench.contract.v2 import PooledReportDocument
from compass_bench.domain.analysis import REVIEW_AFTER_DAYS
from compass_bench.domain.axis_pair import AxisPair
from compass_bench.domain.budget import Price
from compass_bench.domain.design.experiment import ScaleChoice
from compass_bench.domain.findings import FindingCode
from compass_bench.domain.ids import ModelId, PoolId, QuestionnaireHash
from compass_bench.domain.pooling import (
    MIDPOINT_SHARE_FLOOR,
    ModelSettingsDiffer,
    check_model_settings,
    pool_findings,
    pool_id,
    pooled_analyses,
    pools,
    routing_findings,
    scale_reference,
    scale_references,
)
from compass_bench.domain.run import PlannedRun
from compass_bench.domain.stats.icc import ReliabilityBand
from tests.builders.examples import analyzed_example, store_example
from tests.builders.fakes import FakeLedgerStore

ALPHA = ModelId("alpha")


def with_alpha(planned: PlannedRun, update: Mapping[str, object]) -> PlannedRun:
    """The run with alpha's model settings updated."""
    models = {**planned.spec.models, ALPHA: planned.spec.models[ALPHA].model_copy(update=dict(update))}
    return planned.model_copy(update={"spec": planned.spec.model_copy(update={"models": models})})


def test_a_rerun_pools_a_models_answers_without_moving_its_scores() -> None:
    ((_, members, result, reliability),) = pooled_analyses(pooled_example_runs()["pooled"])
    alone = {model.model: model for model in analyzed_example("asserted").models}[ALPHA]

    pooled = {model.model: model for model in result.models}[ALPHA]

    assert [model.model for model in result.models] == ["alpha", "beta", "gamma"]
    assert pooled.questions == alone.questions
    assert pooled.outcomes.answered == 2 * alone.outcomes.answered
    assert len(members) == 2


def test_a_model_asked_in_two_runs_carries_its_reliability_between_them_and_one_asked_once_carries_none() -> None:
    ((_, _, _, reliability),) = pooled_analyses(pooled_example_runs()["pooled"])

    alpha, beta = reliability[ALPHA], reliability[ModelId("beta")]
    # alpha's scripted answers repeat exactly across its two runs, so its scores agree perfectly
    assert alpha.x is not None and alpha.x.icc == pytest.approx(1.0)
    assert (alpha.x.band, alpha.x.questions, alpha.x.runs) == (ReliabilityBand.EXCELLENT, 12, 2)
    assert (beta.x, beta.y) == (None, None)


def test_a_run_on_another_scale_system_prompt_or_template_forms_its_own_pool() -> None:
    planned, _ = example_runs()["asserted"]
    rerun, _ = pooled_example_runs()["pooled"][1]
    design = planned.spec.design.model_copy(update={"scale": ScaleChoice.FORCED_CHOICE})
    forced = planned.model_copy(update={"spec": planned.spec.model_copy(update={"design": design})})
    prompted_design = planned.spec.design.model_copy(update={"system_prompt": "You are a voter."})
    prompted = planned.model_copy(update={"spec": planned.spec.model_copy(update={"design": prompted_design})})
    reasoned_prompt = planned.spec.design.prompt.model_copy(
        update={"template": "{instruction} Explain, then end with a number.\n{scale}\n{statement}"}
    )
    reasoned_design = planned.spec.design.model_copy(update={"prompt": reasoned_prompt})
    reasoned = planned.model_copy(update={"spec": planned.spec.model_copy(update={"design": reasoned_design})})

    grouped = pools([planned, rerun, forced, prompted, reasoned])

    assert sorted(len(members) for members in grouped.values()) == [1, 1, 1, 2]


def test_a_pool_warns_about_mixed_served_model_strings_and_runs_far_apart() -> None:
    ((_, members, result, _),) = pooled_analyses(pooled_example_runs()["pooled"])
    alpha = next(model for model in result.models if model.model == ALPHA)
    mixed = result.model_copy(
        update={"models": (alpha.model_copy(update={"served": {"example/alpha": 100, "example/alpha-2": 92}}),)}
    )
    first, rerun = (planned.run for planned in members)
    sooner = rerun.model_copy(
        update={"created_at": first.created_at + timedelta(days=REVIEW_AFTER_DAYS) - timedelta(seconds=1)}
    )

    assert pool_findings([first, sooner], result) == ()
    codes = [finding.code for finding in pool_findings([first, rerun], mixed)]
    assert codes == [FindingCode.MIXED_SERVED_MODELS, FindingCode.RUNS_FAR_APART]


def test_a_pool_warns_about_a_model_whose_runs_pinned_different_hosts_or_precisions() -> None:
    ((_, members, _, _),) = pooled_analyses(pooled_example_runs()["pooled"])
    first, second = (planned.run.run_id for planned in members)
    alike = {first: example_endpoints(), second: example_endpoints()}
    repinned = EXAMPLE_ENDPOINT.model_copy(update={"provider_order": ("Other",), "quantizations": ("fp8",)})
    differing = {first: example_endpoints(), second: {ENDPOINT: repinned}}

    assert routing_findings(members, alike) == ()
    (finding,) = routing_findings(members, differing)
    assert finding.code is FindingCode.MIXED_ROUTING
    assert finding.message.startswith(
        f"model 'alpha' was asked through different host orders or precision filters in runs {first}, {second}"
    )


async def pool_stored_examples(questionnaire: QuestionnaireHash) -> tuple[PooledReportDocument, ...]:
    """The pooled reports of a store holding the asserted and withheld examples."""
    store = FakeLedgerStore()
    for name in ("asserted", "withheld"):
        await store_example(store, name)
    return await pooled_reports(questionnaire, store)


def test_pooled_reports_pool_the_stored_runs_of_the_questionnaire_only() -> None:
    planned, _ = example_runs()["asserted"]

    (document,) = asyncio.run(pool_stored_examples(planned.spec.questionnaire))

    assert [model.model for model in document.models] == ["alpha", "beta", "gamma"]
    assert len(document.runs) == 2
    assert asyncio.run(pool_stored_examples(QuestionnaireHash("absent"))) == ()


def test_a_model_pools_across_prices_but_not_across_other_settings() -> None:
    planned, _ = example_runs()["asserted"]
    sampling = planned.spec.models[ALPHA].sampling.model_copy(update={"max_tokens": 64})
    repriced = with_alpha(planned, {"price": Price(prompt_usd_per_million=9.0, completion_usd_per_million=9.0)})

    check_model_settings([planned, repriced])
    with pytest.raises(ModelSettingsDiffer, match="model alpha has different settings"):
        check_model_settings([planned, with_alpha(planned, {"sampling": sampling})])


def test_a_forced_choice_pool_reads_each_shared_model_against_its_native_pool_and_a_native_pool_reads_nothing() -> None:
    analyses = pooled_analyses(pooled_example_runs()["cross-scale"])

    references = scale_references(analyses)

    (forced_key,) = [key for key, _, _, _ in analyses if key.scale is ScaleChoice.FORCED_CHOICE]
    (native_key,) = [key for key, _, _, _ in analyses if key.scale is ScaleChoice.NATIVE]
    assert set(references) == {forced_key}
    assert set(references[forced_key]) == {ALPHA, ModelId("beta")}
    alpha = references[forced_key][ALPHA]
    assert alpha.native_pool == pool_id(native_key)
    assert alpha.midpoint_share.x is not None and 0 < alpha.midpoint_share.x < MIDPOINT_SHARE_FLOOR
    assert alpha.forced_not_held == AxisPair(x=False, y=False)


def test_a_forced_choice_position_is_not_held_once_the_native_midpoint_share_reaches_the_floor() -> None:
    at_floor = scale_reference(PoolId("native"), AxisPair(x=MIDPOINT_SHARE_FLOOR, y=MIDPOINT_SHARE_FLOOR - 0.01))
    unscored = scale_reference(PoolId("native"), AxisPair(x=None, y=0.9))

    assert at_floor.forced_not_held == AxisPair(x=True, y=False)
    assert unscored.forced_not_held == AxisPair(x=False, y=True)
