"""Every bundled experiment compiles and passes the pre-flight checks without an error."""

from collections import Counter
from pathlib import Path
from typing import Final

import pytest

from compass_bench.adapters.files.source_files import SourceFiles
from compass_bench.app.compile import compile_experiment
from compass_bench.domain.axis_pair import AxisKey
from compass_bench.domain.design.preflight import plan_findings
from compass_bench.domain.findings import has_errors
from compass_bench.domain.instrument.questionnaire import Questionnaire, find_problems

DATA_DIRECTORY: Final = Path(__file__).parent.parent / "src" / "compass_bench" / "data"


@pytest.mark.parametrize("experiment", sorted(DATA_DIRECTORY.glob("experiments/*.yaml")), ids=lambda path: path.stem)
def test_a_bundled_experiment_plans_without_errors(experiment: Path) -> None:
    compiled = compile_experiment(experiment, SourceFiles(Path.cwd()))

    assert not has_errors(compiled.findings + plan_findings(compiled.spec, compiled.questionnaire))


def test_the_political_questionnaire_passes_every_item_check_with_five_questions_per_facet() -> None:
    path = DATA_DIRECTORY / "questionnaires" / "left-vs-right__authoritarian-vs-libertarian.json"
    questionnaire = Questionnaire.model_validate_json(path.read_text(encoding="utf-8"))

    counts = Counter((question.axis, question.facet) for question in questionnaire.questions)

    assert find_problems(questionnaire) == ()
    assert set(counts.values()) == {5}
    assert (sum(q.axis is AxisKey.X for q in questionnaire.questions), len(questionnaire.questions)) == (35, 75)
