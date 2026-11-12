"""A small compiled experiment to collect, the endpoint runtime it uses, and the outcomes a collection leaves."""

import asyncio
from typing import Final

from compass_bench.app.collect import EndpointRuntime, next_attempt
from compass_bench.app.compile import CompiledExperiment
from compass_bench.domain.analysis import trial_records
from compass_bench.domain.design.experiment import AnswerType
from compass_bench.domain.design.schedule import build_schedule
from compass_bench.domain.ids import EndpointId, ModelId, RunId, run_id
from compass_bench.domain.outcome import TrialOutcome
from compass_bench.ports.listings import ModelListings
from compass_bench.ports.transport import Transport
from tests.builders.design import BOTH_FACTORS, build_design, build_model_spec, build_spec
from tests.builders.fakes import FakeLedgerStore, FakeModelListings
from tests.builders.instrument import FIVE_POINT_LABELS, build_questionnaire, questions_per_axis
from tests.builders.stores import ENDPOINT

ENDPOINT_ID: Final = EndpointId("openrouter")
# one model, 2 questions per axis, 2 phrasings, 4 conditions, 1 repetition
TRIAL_COUNT: Final = 32


def compiled_experiment() -> CompiledExperiment:
    questionnaire = build_questionnaire(questions_per_axis(2), FIVE_POINT_LABELS)
    models = {ModelId("model"): build_model_spec(AnswerType.FREE_TEXT)}
    spec = build_spec(questionnaire, models, build_design(BOTH_FACTORS, repetitions=1))
    return CompiledExperiment(questionnaire=questionnaire, spec=spec, endpoints={ENDPOINT_ID: ENDPOINT}, findings=())


def two_model_experiment(slugs: tuple[str, str]) -> CompiledExperiment:
    """Models `first` and `second` on one endpoint, asking for the two slugs; otherwise compiled_experiment."""
    compiled = compiled_experiment()
    spec = build_model_spec(AnswerType.FREE_TEXT)
    names = (ModelId("first"), ModelId("second"))
    models = {name: spec.model_copy(update={"model": slug}) for name, slug in zip(names, slugs, strict=True)}
    two_models = build_spec(compiled.questionnaire, models, compiled.spec.design)
    return compiled.model_copy(update={"spec": two_models})


def largest_reservation() -> float:
    """The largest first-attempt reservation among compiled_experiment's trials."""
    compiled = compiled_experiment()
    trials = build_schedule(run_id("nonce"), compiled.spec, compiled.questionnaire, seed=0)
    attempts = (next_attempt(trial, (), compiled.spec, compiled.questionnaire) for trial in trials)
    return max(attempt.reserved_usd for attempt in attempts if attempt is not None)


def runtimes(transport: Transport) -> dict[EndpointId, EndpointRuntime]:
    """The one endpoint, with 2 slots."""
    return {ENDPOINT_ID: EndpointRuntime(transport=transport, slots=asyncio.Semaphore(2))}


def slotted_runtimes(transport: Transport, slots: int) -> dict[EndpointId, EndpointRuntime]:
    """The one endpoint, with `slots` slots."""
    return {ENDPOINT_ID: EndpointRuntime(transport=transport, slots=asyncio.Semaphore(slots))}


def no_listings() -> dict[EndpointId, ModelListings]:
    """The one endpoint's provider, listing nothing."""
    return {ENDPOINT_ID: FakeModelListings({})}


async def outcomes(store: FakeLedgerStore, run: RunId) -> tuple[TrialOutcome, ...]:
    planned = await store.load_run(run)
    entries = await store.load_entries(run)
    records = trial_records(planned.trials, entries, planned.questionnaire, planned.spec)
    return tuple(record.outcome for record in records)
