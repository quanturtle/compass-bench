from compass_bench.domain.design.factors import (
    DisplayOrder,
    DisplayOrderFactor,
    FactorKind,
    NumericMapping,
    NumericMappingFactor,
    canonical_rating,
    displayed_rating,
    factor_findings,
)
from compass_bench.domain.findings import FindingCode
from compass_bench.domain.instrument.scale import CanonicalRating, Scale
from tests.builders.instrument import FIVE_POINT_LABELS, FOUR_POINT_LABELS


def test_factor_findings_report_an_empty_factor_a_repeated_level_and_a_repeated_kind() -> None:
    factors = (
        DisplayOrderFactor(kind=FactorKind.DISPLAY_ORDER, levels=()),
        NumericMappingFactor(kind=FactorKind.NUMERIC_MAPPING, levels=(NumericMapping.AGREE_LOW,) * 2),
        DisplayOrderFactor(kind=FactorKind.DISPLAY_ORDER, levels=(DisplayOrder.ASCENDING,)),
    )

    codes = [finding.code for finding in factor_findings(factors)]

    assert codes == [FindingCode.EMPTY_FACTOR, FindingCode.DUPLICATE_LEVEL, FindingCode.DUPLICATE_FACTOR]


def test_canonical_rating_inverts_displayed_rating() -> None:
    for labels in (FOUR_POINT_LABELS, FIVE_POINT_LABELS):
        scale = Scale(labels=labels)
        for mapping in NumericMapping:
            for rating in range(1, len(labels) + 1):
                shown = displayed_rating(scale, mapping, CanonicalRating(rating))
                assert canonical_rating(scale, mapping, shown) == rating


def test_agree_low_numbers_strongly_agree_one() -> None:
    scale = Scale(labels=FIVE_POINT_LABELS)
    assert displayed_rating(scale, NumericMapping.AGREE_LOW, CanonicalRating(5)) == 1
