import json
from pathlib import Path, PurePath

import pytest

from compass_bench.adapters.files.source_files import SourceFiles
from compass_bench.ports.sources import InvalidSource


def test_a_repeated_yaml_key_is_invalid(tmp_path: Path) -> None:
    (tmp_path / "experiment.yaml").write_text("name: a\nname: b\n")

    with pytest.raises(InvalidSource):
        SourceFiles(tmp_path).read_yaml(PurePath("experiment.yaml"))


@pytest.mark.parametrize("text", ["? [a, b]\n: 1\n", "1: one\n'1': two\n"], ids=["list key", "integer key"])
def test_a_non_string_yaml_key_is_invalid(tmp_path: Path, text: str) -> None:
    (tmp_path / "catalog.yaml").write_text(text)

    with pytest.raises(InvalidSource):
        SourceFiles(tmp_path).read_yaml(PurePath("catalog.yaml"))


def test_a_key_may_override_one_a_merge_brought_in(tmp_path: Path) -> None:
    text = "base: &base {max_tokens: 8, temperature: 0}\nmodel:\n  <<: *base\n  max_tokens: 32\n"
    (tmp_path / "catalog.yaml").write_text(text)

    parsed = json.loads(SourceFiles(tmp_path).read_yaml(PurePath("catalog.yaml")))

    assert parsed["model"] == {"max_tokens": 32, "temperature": 0}


def test_a_repeated_merge_key_is_invalid(tmp_path: Path) -> None:
    text = "a: &a {max_tokens: 8}\nb: &b {max_tokens: 32}\nmodel:\n  <<: *a\n  <<: *b\n"
    (tmp_path / "catalog.yaml").write_text(text)

    with pytest.raises(InvalidSource):
        SourceFiles(tmp_path).read_yaml(PurePath("catalog.yaml"))


def test_only_true_and_false_are_booleans(tmp_path: Path) -> None:
    (tmp_path / "catalog.yaml").write_text("reasoning: off\nanswer: yes\nallow_fallbacks: true\n")

    text = SourceFiles(tmp_path).read_yaml(PurePath("catalog.yaml"))

    assert json.loads(text) == {"reasoning": "off", "answer": "yes", "allow_fallbacks": True}
