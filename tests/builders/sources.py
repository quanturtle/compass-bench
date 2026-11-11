"""Input documents for compile and plan: an experiment, its catalog, and its questionnaire."""

import json
from collections.abc import Mapping
from pathlib import Path, PurePath
from typing import Final

from pydantic import JsonValue

from compass_bench.domain.design.experiment import AnswerType
from compass_bench.domain.instrument.questionnaire import Questionnaire
from tests.builders.design import BOTH_FACTORS, build_design, build_model_spec

EXPERIMENT_PATH: Final = PurePath("experiments/experiment.yaml")
CATALOG_NAME: Final = "catalog.yaml"
CATALOG_PATH: Final = EXPERIMENT_PATH.parent / CATALOG_NAME
QUESTIONNAIRE_NAME: Final = "questionnaire.json"


class FakeSources:
    """SourceReader serving each document's JSON text by path, for YAML and JSON alike."""

    def __init__(self, documents: Mapping[PurePath, JsonValue]) -> None:
        self.documents = documents
        return

    def read_yaml(self, path: PurePath) -> str:
        return json.dumps(self.documents[path])

    def read_json(self, path: PurePath) -> str:
        return json.dumps(self.documents[path])

    def exists(self, path: PurePath) -> bool:
        return path in self.documents


def experiment_document(models: tuple[str, ...]) -> dict[str, JsonValue]:
    return {
        "name": "test experiment",
        "questionnaire": QUESTIONNAIRE_NAME,
        "catalog": CATALOG_NAME,
        "models": list(models),
        "design": build_design(BOTH_FACTORS, repetitions=2).model_dump(mode="json"),
        "analysis": {"confidence_level": 0.95, "coverage_floor": 0.8, "equivalence_margin": 0.1},
    }


def catalog_document(pinned: bool = True) -> dict[str, JsonValue]:
    """One OpenRouter endpoint and one free-text model named `free` on it.

    A pinned endpoint names one host and allows no fallback; an unpinned one lets OpenRouter pick."""
    return {
        "endpoints": {
            "openrouter": {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "max_concurrency": 4,
                "timeout_seconds": 60,
                "provider_order": ["example"] if pinned else [],
                "allow_fallbacks": not pinned,
                "require_parameters": True,
                "quantizations": [],
            }
        },
        "models": {"free": build_model_spec(AnswerType.FREE_TEXT).model_dump(mode="json")},
    }


def catalog_with_model(name: str, endpoint: str) -> dict[str, JsonValue]:
    """catalog_document with one more free-text model, `name`, on `endpoint`."""
    catalog = catalog_document()
    models = catalog["models"]
    assert isinstance(models, dict)
    model = {**build_model_spec(AnswerType.FREE_TEXT).model_dump(mode="json"), "endpoint": endpoint}
    return {**catalog, "models": {**models, name: model}}


def experiment_documents(questionnaire: Questionnaire, models: tuple[str, ...]) -> dict[PurePath, JsonValue]:
    """The three documents, keyed by path; the experiment sits at EXPERIMENT_PATH."""
    directory = EXPERIMENT_PATH.parent
    return {
        EXPERIMENT_PATH: experiment_document(models),
        directory / CATALOG_NAME: catalog_document(),
        directory / QUESTIONNAIRE_NAME: questionnaire.model_dump(mode="json"),
    }


def repeated_key_text(document: dict[str, JsonValue]) -> str:
    """The document as a YAML flow mapping that lists `name` twice."""
    return json.dumps(document)[:-1] + ', "name": "again"}'


def with_design_value(document: dict[str, JsonValue], key: str, value: JsonValue) -> dict[str, JsonValue]:
    """The experiment document with `value` under the design's `key`."""
    design = document["design"]
    assert isinstance(design, dict)
    return {**document, "design": {**design, key: value}}


def with_repetitions(document: dict[str, JsonValue], repetitions: JsonValue) -> dict[str, JsonValue]:
    """The experiment document with `repetitions` as the design's repetition count."""
    return with_design_value(document, "repetitions_per_condition", repetitions)


def wrong_type_text(document: dict[str, JsonValue]) -> str:
    """The document with a word where the design's repetition count goes."""
    return json.dumps(with_repetitions(document, "many"))


def write_documents(root: Path, documents: Mapping[PurePath, JsonValue]) -> None:
    """Write each document as JSON under `root`; a YAML reader reads JSON as it is."""
    for path, document in documents.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(document))
    return
