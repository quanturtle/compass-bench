"""Data migrations, run on stored documents without a database."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from pydantic import JsonValue

from compass_bench.adapters.postgres.ledger_store import ATTEMPT_RESULT, ENDPOINTS
from compass_bench.domain.design.experiment import AnswerType, ExperimentSpec, design_prompt, experiment_hash
from compass_bench.domain.design.factors import DisplayOrder, NumericMapping
from compass_bench.domain.elicitation.prompts import STANDARD_INSTRUCTION, STANDARD_TEMPLATE, PromptSettings
from compass_bench.domain.ids import EndpointId, ModelId
from compass_bench.domain.instrument.questionnaire import Questionnaire, questionnaire_hash
from compass_bench.domain.instrument.scale import Scale
from compass_bench.domain.ledger import Completed, TransportError
from tests.builders.design import BOTH_FACTORS, build_condition, build_design, build_model_spec, build_spec
from tests.builders.instrument import FIVE_POINT_LABELS, build_questionnaire, questions_per_axis
from tests.builders.ledger import failed_result, replied_result
from tests.builders.stores import ENDPOINT
from tests.builders.transport import REPLY_BODY

PROVENANCE_FIELDS: Final = ("response_id", "created_at", "system_fingerprint", "native_finish_reason")

VERSIONS: Final = Path(__file__).parent.parent / "src/compass_bench/adapters/postgres/migrations/versions"
PROMPT_MIGRATION: Final = "0003_store_each_experiments_prompt"
ANSWER_TYPE_MIGRATION: Final = "0004_name_the_answer_type"
SAME_PROMPT_MIGRATION: Final = "0005_send_every_answer_type_the_same_prompt"
MARGIN_MIGRATION: Final = "0006_set_each_experiments_equivalence_margin"
FACET_MIGRATION: Final = "0007_name_each_questions_facet"
QUANTIZATION_MIGRATION: Final = "0008_record_each_endpoints_quantizations"
PROVENANCE_MIGRATION: Final = "0009_record_each_replys_provenance"
PREREGISTRATION_MIGRATION: Final = "0011_record_each_experiments_preregistration"
QUESTIONNAIRES: Final = Path(__file__).parent.parent / "src/compass_bench/data/questionnaires"
# revised for version 2.9 under the same file name; its retired revision is what migration 0007 holds a table for
POLITICAL_QUESTIONNAIRE: Final = "left-vs-right__authoritarian-vs-libertarian"
# the template revisions 0003 and 0004 stored, which filled its second field with the answer type's sentence
TEMPLATE_BEFORE_0005: Final = "{instruction} {answer_instruction}\n\nScale:\n{scale}\n\nStatement: {statement}"
STRUCTURED_SENTENCE: Final = 'Reply with a JSON object whose "rating" member is a single number from the scale below.'


def load_migration(name: str) -> ModuleType:
    """A migration module by file name; its name starts with a digit, so it cannot be imported directly."""
    location = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    assert location is not None and location.loader is not None
    module = importlib.util.module_from_spec(location)
    location.loader.exec_module(module)
    return module


def stored_spec(prompt: PromptSettings | None, *answer_types: AnswerType) -> ExperimentSpec:
    """A spec with one model per answer type, a free-text one when none is given."""
    design = build_design(BOTH_FACTORS, repetitions=1)
    questionnaire = build_questionnaire(questions_per_axis(10), FIVE_POINT_LABELS)
    models = {
        ModelId(f"model-{answer_type}"): build_model_spec(answer_type)
        for answer_type in answer_types or (AnswerType.FREE_TEXT,)
    }
    spec = build_spec(questionnaire, models, design)
    return spec if prompt is None else spec.model_copy(update={"design": design.model_copy(update={"prompt": prompt})})


def spec_before_0003(spec: ExperimentSpec) -> dict[str, JsonValue]:
    """The spec as revision 0002 stored it: no prompt, and each model's answer type under `format`."""
    document = spec.model_dump(mode="json")
    models = {
        name: {("format" if key == "answer_type" else key): value for key, value in model.items()}
        for name, model in document["models"].items()
    }
    design = {key: value for key, value in document["design"].items() if key != "prompt"}
    return {**document, "models": models, "design": design}


def spec_before_0005(spec: ExperimentSpec) -> dict[str, JsonValue]:
    """The spec as revision 0004 stored it: the template asks for the answer type's sentence in a field."""
    document = spec.model_dump(mode="json")
    prompt = {**document["design"]["prompt"], "template": TEMPLATE_BEFORE_0005}
    return {**document, "design": {**document["design"], "prompt": prompt}}


def spec_before_0006(spec: ExperimentSpec) -> dict[str, JsonValue]:
    """The spec as revision 0005 stored it: no equivalence margin in its analysis settings."""
    document = spec.model_dump(mode="json")
    analysis = {key: value for key, value in document["analysis"].items() if key != "equivalence_margin"}
    return {**document, "analysis": analysis}


def test_0006_gives_a_stored_spec_the_standard_margin_under_the_hash_the_package_computes() -> None:
    migration = load_migration(MARGIN_MIGRATION)
    current = stored_spec(None)

    upgraded = migration.with_standard_margin(spec_before_0006(current))

    assert ExperimentSpec.model_validate_json(json.dumps(upgraded)) == current
    assert migration.spec_hash(upgraded) == experiment_hash(current)
    assert migration.without_standard_margin(upgraded, "stored") == spec_before_0006(current)


def spec_before_0011(spec: ExperimentSpec) -> dict[str, JsonValue]:
    """The spec as revision 0010 stored it: no preregistration field."""
    return {key: value for key, value in spec.model_dump(mode="json").items() if key != "preregistration"}


def test_0011_gives_a_stored_spec_a_null_preregistration_under_the_hash_the_package_computes() -> None:
    migration = load_migration(PREREGISTRATION_MIGRATION)
    current = stored_spec(None)

    upgraded = migration.with_preregistration_field(spec_before_0011(current))

    assert ExperimentSpec.model_validate_json(json.dumps(upgraded)) == current
    assert migration.spec_hash(upgraded) == experiment_hash(current)
    assert migration.without_preregistration_field(upgraded, "stored") == spec_before_0011(current)


def test_0011_refuses_to_downgrade_a_spec_that_names_a_preregistration() -> None:
    migration = load_migration(PREREGISTRATION_MIGRATION)
    named = stored_spec(None).model_dump(mode="json")
    named["preregistration"] = "../preregistrations/political-compass-2026-11-03.md"

    with pytest.raises(migration.NamedPreregistration, match="names a preregistration"):
        migration.without_preregistration_field(named, "stored")


def test_0006_refuses_to_downgrade_a_spec_with_its_own_margin() -> None:
    migration = load_migration(MARGIN_MIGRATION)
    own = stored_spec(None).model_dump(mode="json")
    own["analysis"]["equivalence_margin"] = 0.2

    with pytest.raises(migration.CustomMargin, match="sets its own equivalence margin"):
        migration.without_standard_margin(own, "stored")


@pytest.mark.parametrize(
    "path",
    sorted(path for path in QUESTIONNAIRES.glob("*.json") if path.stem != POLITICAL_QUESTIONNAIRE),
    ids=lambda path: path.stem[:24],
)
def test_0007_gives_each_bundled_questionnaire_as_stored_before_facets_the_facets_the_file_has(path: Path) -> None:
    migration = load_migration(FACET_MIGRATION)
    current = Questionnaire.model_validate_json(path.read_text())
    stored = migration.without_facets(current.model_dump(mode="json"))
    stored_hash = migration.document_hash(stored)

    upgraded = migration.with_facets(stored, stored_hash)

    assert stored_hash in migration.FACETS
    assert Questionnaire.model_validate_json(json.dumps(upgraded)) == current
    assert migration.document_hash(upgraded) == questionnaire_hash(current)


def test_0007_keeps_the_retired_political_revisions_table_and_knows_nothing_of_the_current_one() -> None:
    """The 2.9 revision was never stored without facets, so the migration has no table for it."""
    migration = load_migration(FACET_MIGRATION)
    current = Questionnaire.model_validate_json((QUESTIONNAIRES / f"{POLITICAL_QUESTIONNAIRE}.json").read_text())
    stored = migration.without_facets(current.model_dump(mode="json"))

    assert len(migration.FACETS[migration.LEFT_RIGHT]) == 66
    assert migration.document_hash(stored) not in migration.FACETS
    with pytest.raises(migration.UnknownQuestionnaire, match="which no bundled questionnaire has"):
        migration.with_facets(stored, "stored")


def test_0007_refuses_a_question_it_has_no_facet_for_and_keeps_one_that_has_it() -> None:
    migration = load_migration(FACET_MIGRATION)
    own = build_questionnaire(questions_per_axis(2), FIVE_POINT_LABELS).model_dump(mode="json")

    assert migration.with_facets(own, "stored") == own
    with pytest.raises(migration.UnknownQuestionnaire, match="asks 'x-00', which no bundled questionnaire has"):
        migration.with_facets(migration.without_facets(own), "stored")


def test_0007_facets_an_earlier_edition_whose_ids_lack_the_axis_prefix() -> None:
    migration = load_migration(FACET_MIGRATION)
    retired = list(migration.FACETS[migration.LEFT_RIGHT])[:3]
    stored = build_questionnaire(questions_per_axis(1), FIVE_POINT_LABELS).model_dump(mode="json")
    stored["questions"] = [
        {"id": question[2:], "axis": question[0], "statements": {"negative": "a", "positive": "b"}}
        for question in retired
    ]

    upgraded = migration.with_facets(stored, "stored")

    assert retired == [
        "y-bulk_communications_surveillance",
        "y-facial_recognition_in_public",
        "y-compelled_platform_takedowns",
    ]
    assert [question["facet"] for question in upgraded["questions"]] == ["surveillance", "surveillance", "speech"]


def test_0007_moves_a_spec_from_the_old_questionnaire_hash_to_the_new_one() -> None:
    migration = load_migration(FACET_MIGRATION)
    spec = stored_spec(None).model_dump(mode="json")

    moved = migration.respecified(spec, spec["questionnaire"], "new")

    assert moved["questionnaire"] == "new"
    assert migration.respecified(spec, "other", "new") == spec


def test_0008_gives_a_stored_endpoint_an_empty_quantization_filter_that_validates_and_round_trips() -> None:
    migration = load_migration(QUANTIZATION_MIGRATION)
    stored = {
        "openrouter": {key: value for key, value in ENDPOINT.model_dump(mode="json").items() if key != "quantizations"}
    }

    upgraded = migration.with_quantizations(stored)

    assert ENDPOINTS.validate_json(json.dumps(upgraded)) == {EndpointId("openrouter"): ENDPOINT}
    assert migration.without_quantizations(upgraded, "run") == stored


def test_0008_refuses_to_downgrade_an_endpoint_that_filters_by_precision() -> None:
    migration = load_migration(QUANTIZATION_MIGRATION)
    filtered = {"openrouter": {**ENDPOINT.model_dump(mode="json"), "quantizations": ["bf16"]}}

    with pytest.raises(migration.FilteredEndpoint, match="filters endpoint 'openrouter' by precision"):
        migration.without_quantizations(filtered, "run")


def test_0003_to_0005_give_a_stored_spec_the_standard_prompt_under_the_hash_the_package_computes() -> None:
    answer_type_migration = load_migration(ANSWER_TYPE_MIGRATION)
    current = stored_spec(None)

    renamed = answer_type_migration.renamed_spec(
        load_migration(PROMPT_MIGRATION).with_standard_prompt(spec_before_0003(current)),
        answer_type_migration.MODEL_KEYS,
        answer_type_migration.TEMPLATE_FIELDS,
    )
    upgraded = load_migration(SAME_PROMPT_MIGRATION).with_sentence(renamed, "stored")

    assert ExperimentSpec.model_validate_json(json.dumps(upgraded)) == current
    assert answer_type_migration.spec_hash(upgraded) == experiment_hash(current)


def test_0005_then_0004_downgrade_to_the_spec_0003_stored() -> None:
    answer_type_migration = load_migration(ANSWER_TYPE_MIGRATION)
    current = stored_spec(None)

    downgraded = answer_type_migration.renamed_spec(
        load_migration(SAME_PROMPT_MIGRATION).with_field(current.model_dump(mode="json"), "stored"),
        tuple(reversed(answer_type_migration.MODEL_KEYS)),
        tuple(reversed(answer_type_migration.TEMPLATE_FIELDS)),
    )

    assert downgraded == load_migration(PROMPT_MIGRATION).with_standard_prompt(spec_before_0003(current))


def test_0005_keeps_the_prompt_a_structured_run_was_sent() -> None:
    stored = spec_before_0005(stored_spec(None, AnswerType.STRUCTURED))
    condition = build_condition(DisplayOrder.ASCENDING, NumericMapping.AGREE_HIGH)

    upgraded = ExperimentSpec.model_validate_json(
        json.dumps(load_migration(SAME_PROMPT_MIGRATION).with_sentence(stored, "stored"))
    )

    prompt = design_prompt(upgraded.design, "A statement.", condition, Scale(labels=FIVE_POINT_LABELS))
    assert prompt.messages[0].content.startswith(f"{STANDARD_INSTRUCTION} {STRUCTURED_SENTENCE}\n\nScale:\n1 = ")


def test_0005_refuses_a_spec_whose_models_use_two_answer_types() -> None:
    migration = load_migration(SAME_PROMPT_MIGRATION)
    stored = spec_before_0005(stored_spec(None, AnswerType.FREE_TEXT, AnswerType.STRUCTURED))

    with pytest.raises(migration.UnrenderableSpec, match="not one"):
        migration.with_sentence(stored, "stored")


def stored_result_before_0009() -> dict[str, JsonValue]:
    """A completed result as revision 0008 stored it: a reply without the four provenance fields."""
    result = ATTEMPT_RESULT.dump_python(replied_result("4"), mode="json")
    reply = {key: value for key, value in result["reply"].items() if key not in PROVENANCE_FIELDS}
    return {**result, "reply": reply}


def test_0009_reads_a_stored_replys_provenance_from_its_raw_body_and_validates() -> None:
    migration = load_migration(PROVENANCE_MIGRATION)
    body = json.dumps(REPLY_BODY).encode()

    upgraded = migration.with_provenance(stored_result_before_0009(), body)

    completed = ATTEMPT_RESULT.validate_json(json.dumps(upgraded))
    assert isinstance(completed, Completed)
    reply = completed.reply
    assert (reply.response_id, reply.system_fingerprint, reply.native_finish_reason) == ("gen-1", "fp_123", "end_turn")
    assert reply.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert migration.without_provenance(upgraded) == stored_result_before_0009()


def test_0009_leaves_the_fields_unset_without_a_body_and_a_failure_untouched() -> None:
    migration = load_migration(PROVENANCE_MIGRATION)
    failure = ATTEMPT_RESULT.dump_python(failed_result(TransportError.TIMEOUT), mode="json")

    upgraded = ATTEMPT_RESULT.validate_json(json.dumps(migration.with_provenance(stored_result_before_0009(), None)))
    unreadable = ATTEMPT_RESULT.validate_json(
        json.dumps(migration.with_provenance(stored_result_before_0009(), b"not json"))
    )

    assert isinstance(upgraded, Completed) and isinstance(unreadable, Completed)
    assert (upgraded.reply.response_id, upgraded.reply.created_at) == (None, None)
    assert unreadable.reply.system_fingerprint is None
    assert migration.with_provenance(failure, b"{}") == failure


def test_0003_refuses_to_downgrade_a_spec_with_its_own_prompt() -> None:
    migration = load_migration(PROMPT_MIGRATION)
    own = stored_spec(PromptSettings(template=STANDARD_TEMPLATE, instruction="Express your view on this statement."))

    with pytest.raises(migration.CustomPrompt, match="sets its own prompt"):
        migration.without_standard_prompt(own.model_dump(mode="json"), "stored")
