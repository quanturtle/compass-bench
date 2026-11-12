import pytest
from pydantic import JsonValue

from compass_bench.app.compile import InvalidExperiment, compile_experiment
from compass_bench.domain.axis_pair import AxisKey
from compass_bench.domain.design.experiment import experiment_hash
from compass_bench.domain.elicitation.prompts import STANDARD_PROMPT, STANDARD_TEMPLATE, PromptSettings
from compass_bench.domain.findings import FindingCode, Severity
from tests.builders.design import BOTH_FACTORS
from tests.builders.instrument import FIVE_POINT_LABELS, build_question, build_questionnaire, questions_per_axis
from tests.builders.sources import (
    CATALOG_PATH,
    EXPERIMENT_PATH,
    FakeSources,
    catalog_document,
    catalog_with_model,
    experiment_document,
    experiment_documents,
    with_design_value,
    with_repetitions,
)


def test_compile_resolves_the_listed_models_and_their_endpoints() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    sources = FakeSources(experiment_documents(questionnaire, models=("free",)))

    compiled = compile_experiment(EXPERIMENT_PATH, sources)

    assert (list(compiled.spec.models), list(compiled.endpoints), compiled.findings) == (["free"], ["openrouter"], ())


def test_the_authored_order_of_factors_and_levels_does_not_change_the_experiment_hash() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    reversed_factors: list[JsonValue] = [
        {"kind": str(factor.kind), "levels": [str(level) for level in reversed(factor.levels)]}
        for factor in reversed(BOTH_FACTORS)
    ]
    reauthored = with_design_value(experiment_document(("free",)), "factors", reversed_factors)

    authored = compile_experiment(EXPERIMENT_PATH, FakeSources(documents)).spec
    reordered = compile_experiment(EXPERIMENT_PATH, FakeSources({**documents, EXPERIMENT_PATH: reauthored})).spec

    assert experiment_hash(reordered) == experiment_hash(authored)


def test_the_authored_order_of_instructions_does_not_change_the_experiment_hash() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    wordings: list[JsonValue] = ["Give me your opinion on the following statement.", "Express your view on it."]
    authored, reordered = (
        compile_experiment(
            EXPERIMENT_PATH,
            FakeSources(
                {
                    **documents,
                    EXPERIMENT_PATH: with_design_value(
                        experiment_document(("free",)), "factors", [{"kind": "instruction", "levels": levels}]
                    ),
                }
            ),
        ).spec
        for levels in (wordings, wordings[::-1])
    )

    assert experiment_hash(reordered) == experiment_hash(authored)


def test_an_instruction_listed_twice_is_a_duplicate_level() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    factors: list[JsonValue] = [{"kind": "instruction", "levels": ["Express your view on it."] * 2}]
    document = with_design_value(experiment_document(("free",)), "factors", factors)

    findings = compile_experiment(EXPERIMENT_PATH, FakeSources({**documents, EXPERIMENT_PATH: document})).findings

    assert [finding.code for finding in findings] == [FindingCode.DUPLICATE_LEVEL]


def test_an_unknown_model_is_a_finding_reported_beside_the_others() -> None:
    repeated = build_question("x-00", AxisKey.X)
    questionnaire = build_questionnaire((*questions_per_axis(10), repeated), FIVE_POINT_LABELS)
    sources = FakeSources(experiment_documents(questionnaire, models=("free", "missing")))

    codes = [finding.code for finding in compile_experiment(EXPERIMENT_PATH, sources).findings]

    assert codes == [FindingCode.DUPLICATE_QUESTION, FindingCode.UNKNOWN_MODEL]


def test_a_repetition_count_below_one_is_invalid() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    sources = FakeSources({**documents, EXPERIMENT_PATH: with_repetitions(experiment_document(("free",)), 0)})

    with pytest.raises(InvalidExperiment):
        compile_experiment(EXPERIMENT_PATH, sources)


def test_an_empty_system_prompt_is_invalid() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    sources = FakeSources(
        {**documents, EXPERIMENT_PATH: with_design_value(experiment_document(("free",)), "system_prompt", "")}
    )

    with pytest.raises(InvalidExperiment):
        compile_experiment(EXPERIMENT_PATH, sources)


def test_an_omitted_prompt_or_prompt_part_is_the_standard_one() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    document = experiment_document(("free",))
    design = document["design"]
    assert isinstance(design, dict)
    omitted = {**document, "design": {key: value for key, value in design.items() if key != "prompt"}}
    instruction_only = with_design_value(document, "prompt", {"instruction": "Give me your opinion on this statement."})

    standard = compile_experiment(EXPERIMENT_PATH, FakeSources({**documents, EXPERIMENT_PATH: omitted})).spec
    configured = compile_experiment(EXPERIMENT_PATH, FakeSources({**documents, EXPERIMENT_PATH: instruction_only})).spec

    assert standard.design.prompt == STANDARD_PROMPT
    assert configured.design.prompt == PromptSettings(
        template=STANDARD_TEMPLATE, instruction="Give me your opinion on this statement."
    )


def test_a_prompt_template_without_every_placeholder_is_a_finding() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    document = with_design_value(experiment_document(("free",)), "prompt", {"template": "{statement}"})

    findings = compile_experiment(EXPERIMENT_PATH, FakeSources({**documents, EXPERIMENT_PATH: document})).findings

    assert {finding.code for finding in findings} == {FindingCode.INVALID_PROMPT_TEMPLATE}
    assert len(findings) == 2


def test_a_repeated_model_and_a_model_on_an_unknown_endpoint_are_findings() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free", "free", "stray"))
    sources = FakeSources({**documents, CATALOG_PATH: catalog_with_model("stray", endpoint="nowhere")})

    codes = [finding.code for finding in compile_experiment(EXPERIMENT_PATH, sources).findings]

    assert codes == [FindingCode.DUPLICATE_MODEL, FindingCode.UNKNOWN_ENDPOINT]


def test_an_endpoint_that_lets_openrouter_pick_the_host_is_a_warning() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    sources = FakeSources({**documents, CATALOG_PATH: catalog_document(pinned=False)})

    findings = compile_experiment(EXPERIMENT_PATH, sources).findings

    assert [(finding.severity, finding.code) for finding in findings] == [
        (Severity.WARNING, FindingCode.UNPINNED_ENDPOINT)
    ]


def test_a_named_preregistration_must_be_a_file_beside_the_experiment() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    documents = experiment_documents(questionnaire, models=("free",))
    experiment = {**experiment_document(models=("free",)), "preregistration": "../preregistrations/plan.md"}
    missing = FakeSources({**documents, EXPERIMENT_PATH: experiment})
    present = FakeSources({**missing.documents, EXPERIMENT_PATH.parent / "../preregistrations/plan.md": {}})

    assert [(f.severity, f.code) for f in compile_experiment(EXPERIMENT_PATH, missing).findings] == [
        (Severity.ERROR, FindingCode.PREREGISTRATION_MISSING)
    ]
    compiled = compile_experiment(EXPERIMENT_PATH, present)
    assert (compiled.findings, compiled.spec.preregistration) == ((), "../preregistrations/plan.md")
    assert compile_experiment(EXPERIMENT_PATH, FakeSources(documents)).spec.preregistration is None


def test_a_named_preregistration_must_be_committed_as_it_stands() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    plan = EXPERIMENT_PATH.parent / "../preregistrations/plan.md"
    experiment = {**experiment_document(models=("free",)), "preregistration": "../preregistrations/plan.md"}
    documents = {**experiment_documents(questionnaire, models=("free",)), EXPERIMENT_PATH: experiment, plan: {}}

    findings = compile_experiment(EXPERIMENT_PATH, FakeSources(documents, uncommitted=frozenset({plan}))).findings

    assert [(f.severity, f.code) for f in findings] == [(Severity.ERROR, FindingCode.PREREGISTRATION_UNCOMMITTED)]


def test_an_experiment_without_models_is_a_finding() -> None:
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    sources = FakeSources(experiment_documents(questionnaire, models=()))

    codes = [finding.code for finding in compile_experiment(EXPERIMENT_PATH, sources).findings]

    assert codes == [FindingCode.NO_MODELS]
