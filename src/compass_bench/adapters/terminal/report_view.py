"""Text for `analyze` and `pool`. It reads the contract documents only and computes nothing."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Final, assert_never

from compass_bench.adapters.terminal.plan_view import render_findings
from compass_bench.contract.v2 import PooledReportDocument, ReportDocument
from compass_bench.domain.analysis import AnalysisResult, ModelUsage
from compass_bench.domain.axis_pair import AxisKey
from compass_bench.domain.claims import (
    Asserted,
    CoverageBelowFloor,
    CrossesMidpoint,
    Equivalence,
    EquivalenceClaim,
    NotEquivalent,
    NotSignificant,
    Ordering,
    OrderingClaim,
    PairOutcome,
    QuadrantClaim,
    Reason,
    RunIncomplete,
    TooFewQuestions,
    Withheld,
)
from compass_bench.domain.consistency import LevelPosition, Marginals, Spread, VarianceShares
from compass_bench.domain.design.conditions import display_order_levels, instruction_levels, numeric_mapping_levels
from compass_bench.domain.design.configuration import PairElicitation
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.experiment import (
    AnalysisSettings,
    ExperimentSpec,
    ModelSpec,
    ReasoningEffort,
    Sampling,
    effective_scale,
)
from compass_bench.domain.design.preregistration import ReportStatus
from compass_bench.domain.ids import EndpointId, ModelId
from compass_bench.domain.inference import Bounded, Estimate, NotEstimable, PairAxis
from compass_bench.domain.instrument.compass import Compass
from compass_bench.domain.instrument.questionnaire import Questionnaire
from compass_bench.domain.listing import ModelListing
from compass_bench.domain.missing import AxisUnanswered, Bound
from compass_bench.domain.pooling import RunReliability, ScaleReference
from compass_bench.domain.profile import RatingProfile, ScaleUse, ScoreSplit, StatementAgreement
from compass_bench.domain.reading.reading import FormatFailureKind
from compass_bench.domain.robustness import OrderingRobustness
from compass_bench.domain.scoring import FacetScore
from compass_bench.version import Version

INDENT: Final = "  "
# a wording is shown up to this many characters; plan prints the whole prompt
WORDING_LIMIT: Final = 60


def power_text(power: float | None) -> str:
    return "undefined power" if power is None else f"power {power:.2f}"


def reason_text(reason: Reason) -> str:
    """Exhaustive over Reason, so mypy rejects an unhandled variant."""
    match reason:
        case CrossesMidpoint(axis=axis):
            return f"axis {axis}: the interval contains 0"
        case TooFewQuestions(axis=axis, observed=observed, minimum=minimum):
            return f"axis {axis}: {observed} questions, fewer than {minimum}"
        case CoverageBelowFloor(model=model, axis=axis, observed=observed, floor=floor):
            return f"axis {axis}: {model} answered {observed:.1%} of its trials, below the {floor:.1%} floor"
        case NotSignificant(axis=axis, p_holm=p_holm, alpha=alpha):
            return f"axis {axis}: Holm p {p_holm:.3g} is not below {alpha:.3g}"
        case NotEquivalent(axis=axis, p_holm=p_holm, alpha=alpha, margin=margin, power_at_zero_gap=power):
            return (
                f"axis {axis}: equivalence Holm p {p_holm:.3g} is not below {alpha:.3g}; the test had "
                f"{power_text(power)} at a zero gap within ±{margin:.3f}"
            )
        case RunIncomplete(pending=pending):
            return f"{pending} trials are pending"
        case _:
            assert_never(reason)


def withheld_text(reasons: Sequence[Reason]) -> str:
    return "withheld: " + "; ".join(reason_text(reason) for reason in reasons)


def quadrant_text(claim: QuadrantClaim, compass: Compass) -> str:
    match claim:
        case Asserted(value=poles):
            return ", ".join(
                f"{compass.axes.get(axis).name} {compass.axes.get(axis).pole(poles.get(axis))}" for axis in AxisKey
            )
        case Withheld(reasons=reasons):
            return withheld_text(reasons)


def estimate_text(estimate: Estimate) -> str:
    match estimate:
        case Bounded(point=point, low=low, high=high, level=level, questions=questions, minimum_detectable=detectable):
            return (
                f"{point:+.3f} [{low:+.3f}, {high:+.3f}] at {level:.1%}, {questions} questions, "
                f"detects ±{detectable:.3f}"
            )
        case NotEstimable(questions=questions):
            return f"not estimable, {questions} questions"


def axis_label(compass: Compass, axis: AxisKey) -> str:
    return f"{axis} {compass.axes.get(axis).name}"


def section(title: str, lines: Sequence[str]) -> tuple[str, ...]:
    return (title, *(f"{INDENT}{line}" for line in lines))


def questionnaire_lines(questionnaire: Questionnaire) -> tuple[str, ...]:
    """The questionnaire's title and author, then each axis from its negative to its positive pole."""
    return (
        f"questionnaire: {questionnaire.title}, by {questionnaire.author}",
        *(
            f"axis {axis_label(questionnaire.compass, axis)}: from {named.negative} (-1) to {named.positive} (+1)"
            for axis in AxisKey
            for named in (questionnaire.compass.axes.get(axis),)
        ),
    )


def settings_text(settings: AnalysisSettings) -> str:
    return (
        f"confidence level {settings.confidence_level:.1%}, answered-share floor {settings.coverage_floor:.1%}, "
        f"equivalence margin {settings.equivalence_margin:.3f}"
    )


def system_prompt_text(system_prompt: str | None) -> str:
    return "system prompt: none" if system_prompt is None else f"system prompt: {system_prompt!r}"


def routing_text(endpoint: EndpointSettings | None) -> str:
    """The host order and precision filter the endpoint pins, or that the run stored no settings for it."""
    if endpoint is None:
        return "no stored endpoint settings"
    hosts = ", ".join(endpoint.provider_order) or "any"
    precision = ", ".join(endpoint.quantizations) or "any"
    return f"host order {hosts}, precision {precision}"


def configuration_lines(
    spec: ExperimentSpec, endpoints: Mapping[EndpointId, EndpointSettings], questionnaire: Questionnaire
) -> tuple[str, ...]:
    """The configuration a position belongs to: the scale asked on, the design's cells, the prompt, and each model
    with its sampling and routing."""
    design = spec.design
    asked = effective_scale(design, questionnaire.scale)
    wordings = instruction_levels(design.factors, design.prompt.instruction)
    layouts = len(display_order_levels(design.factors)) * len(numeric_mapping_levels(design.factors))
    return (
        f"scale asked on: {' | '.join(asked.labels)} ({design.scale})",
        f"design: wordings {len(wordings)}, layouts {layouts}, repetitions per cell {design.repetitions_per_condition}",
        f"template: {design.prompt.template!r}",
        *(f"wording: {wording!r}" for _, wording in wordings),
        *(
            f"{name}: {model.model} via {model.endpoint}, {model.answer_type}; {sampling_text(model.sampling)}; "
            f"{routing_text(endpoints.get(model.endpoint))}"
            for name, model in spec.models.items()
        ),
    )


def status_text(status: ReportStatus, preregistration: str | None) -> str:
    """Why the claims are confirmatory or exploratory; the claim rules are the current version's either way."""
    match status:
        case ReportStatus.CONFIRMATORY:
            return f"status: confirmatory, preregistered at {preregistration}"
        case ReportStatus.EXPLORATORY:
            return (
                f"status: exploratory; no preregistration is recorded, and the claim rules are those of "
                f"compass-bench {Version.CURRENT}"
            )


def pooled_status_text(status: ReportStatus) -> str:
    match status:
        case ReportStatus.CONFIRMATORY:
            return "status: confirmatory; every run names a preregistration, which must name this pool's rule"
        case ReportStatus.EXPLORATORY:
            return (
                "status: exploratory; a run names no preregistration, and a pool formed after a run was read is a "
                "second look"
            )


def header_lines(document: ReportDocument) -> tuple[str, ...]:
    return (
        f"compass-bench report: {document.experiment.name}, run {document.run.run_id}",
        status_text(document.status, document.experiment.preregistration),
        *questionnaire_lines(document.questionnaire),
        settings_text(document.experiment.analysis),
        system_prompt_text(document.experiment.design.system_prompt),
        *configuration_lines(document.experiment, document.endpoints, document.questionnaire),
    )


def bound_text(bound: Bound | None) -> str:
    match bound:
        case Bound(low=low, high=high, filled=0):
            return f"bound [{low:+.3f}, {high:+.3f}] with nothing unanswered"
        case Bound(low=low, high=high, filled=filled):
            return f"bound [{low:+.3f}, {high:+.3f}] under any answers to the {filled} unanswered trials"
        case None:
            return "bound undefined"


def flip_text(unanswered: AxisUnanswered) -> str:
    """How the unanswered trials could move the position's side of 0, or that they cannot."""
    if unanswered.trials == 0:
        return ""
    match unanswered.flip, unanswered.widening_flip:
        case None, None:
            return "; no fill of them moves the interval across 0"
        case flip, None:
            return f"; the interval crosses 0 if they averaged {flip:+.2f} or past it"
        case None, widening:
            return f"; the interval widens across 0 if they averaged {widening:+.2f} or past it"
        case flip, widening:
            return (
                f"; the interval crosses 0 if they averaged {flip:+.2f} or past it, "
                f"and widens across 0 at {widening:+.2f} or past it"
            )


def position_lines(compass: Compass, analysis: AnalysisResult) -> tuple[str, ...]:
    lines: list[str] = []
    for result in analysis.models:
        lines.append(f"{result.model}: {quadrant_text(result.quadrant, compass)}")
        for axis in AxisKey:
            position, unanswered = result.axes.get(axis), result.unanswered.get(axis)
            lines.append(
                f"{INDENT}{axis_label(compass, axis)}: {estimate_text(position.estimate)}; "
                f"{position.coverage:.1%} of trials answered"
            )
            lines.append(f"{INDENT * 2}{bound_text(unanswered.bound)}{flip_text(unanswered)}")
    return section("Positions", lines)


def signed_text(value: float | None) -> str:
    """A signed value to three places, or `undefined`."""
    return "undefined" if value is None else f"{value:+.3f}"


def count_text(count: int | None) -> str:
    return "an undefined number of" if count is None else str(count)


def spread_text(spread: Spread | None) -> str:
    match spread:
        case Spread(low=low, high=high, cells=cells):
            return f"cell positions from {low:+.3f} to {high:+.3f} over {cells} cells"
        case None:
            return "cell positions undefined"


def wording_text(wording: str) -> str:
    """The wording in quotes, cut at WORDING_LIMIT characters with an ellipsis."""
    shown = wording if len(wording) <= WORDING_LIMIT else wording[: WORDING_LIMIT - 1] + "…"
    return f'"{shown}"'


def level_text(level: LevelPosition, is_wording: bool) -> str:
    label = wording_text(level.level) if is_wording else level.level
    return f"{label} {signed_text(level.position)} ({level.questions} questions)"


def range_text(name: str, value: float | None) -> str:
    return f"{name} range undefined" if value is None else f"{name} range {value:.3f}"


def marginal_lines(marginals: Marginals) -> tuple[str, str]:
    """One line per factor family: the position at each wording, then at each layout, each with its range."""
    wordings = "; ".join(level_text(level, is_wording=True) for level in marginals.wordings)
    layouts = "; ".join(level_text(level, is_wording=False) for level in marginals.layouts)
    return (
        f"by wording: {wordings or 'none'}; {range_text('wording', marginals.wording_range)}",
        f"by layout: {layouts or 'none'}; {range_text('layout', marginals.layout_range)}",
    )


def shares_text(shares: VarianceShares | None) -> str:
    match shares:
        case VarianceShares(wording=wording, display_order=order, numeric_mapping=mapping, residual=residual, cells=n):
            return (
                f"cell variance over {n} cells: wording {wording:.1%}, display order {order:.1%}, "
                f"numbering {mapping:.1%}, residual {residual:.1%}"
            )
        case None:
            return "cell variance undefined"


def facet_text(facet: FacetScore) -> str:
    mean = "undefined" if facet.mean is None else f"{facet.mean:+.3f}"
    return f"{facet.facet} {mean} ({facet.questions} questions)"


def facet_lines(compass: Compass, analysis: AnalysisResult) -> tuple[str, ...]:
    """Each model's mean score per facet of each axis; facets gate nothing."""
    lines: list[str] = []
    for result in analysis.models:
        lines.append(f"{result.model}")
        for axis in AxisKey:
            facets = ", ".join(facet_text(facet) for facet in result.facets if facet.axis is axis)
            lines.append(f"{INDENT}{axis_label(compass, axis)}: {facets}")
    return section("Facets", lines)


def consistency_lines(compass: Compass, analysis: AnalysisResult) -> tuple[str, ...]:
    """Each model's pole means, lean to agree, pole correlation, consistent questions, and spread across cells."""
    lines: list[str] = []
    for result in analysis.models:
        lines.append(f"{result.model}")
        for axis in AxisKey:
            consistency = result.consistency.get(axis)
            lines.append(
                f"{INDENT}{axis_label(compass, axis)}: toward {compass.axes.get(axis).negative} "
                f"{signed_text(consistency.poles.negative)}, toward {compass.axes.get(axis).positive} "
                f"{signed_text(consistency.poles.positive)}; lean to agree {signed_text(consistency.agreement_lean)}; "
                f"pole correlation {signed_text(consistency.pole_correlation)}"
            )
            lines.append(
                f"{INDENT * 2}{consistency.consistent_questions} of {consistency.questions} questions consistent, "
                f"{consistency.midpoint_questions} with a statement at the midpoint, "
                f"{consistency.same_side_questions} on the same side; "
                f"{spread_text(consistency.spread)}, {consistency.unstable_questions} questions unstable"
            )
            lines.extend(f"{INDENT * 2}{line}" for line in marginal_lines(consistency.marginals))
            lines.append(f"{INDENT * 2}{shares_text(consistency.variance_shares)}")
    return section("Diagnostics", lines)


def ordering_text(claim: OrderingClaim, first: ModelId, second: ModelId) -> str:
    match claim:
        case Asserted(value=ordering):
            return f"{first if ordering is Ordering.FIRST_HIGHER else second} higher"
        case Withheld(reasons=reasons):
            return withheld_text(reasons)


def d_z_text(d_z: float | None) -> str:
    """d_z with its sign, or `undefined` below two shared questions or when every gap is equal."""
    return "undefined" if d_z is None else f"{d_z:+.2f}"


def elicitation_text(pair: PairElicitation) -> str:
    """The fields on which the two models' elicitations differ, each with both values, or that they share one."""
    if not pair.differs:
        return "same elicitation"
    listed = ", ".join(f"{d.field} {d.first} against {d.second}" for d in pair.differs)
    return f"elicitations differ: {listed}"


def family_step_text(gap: PairAxis) -> str:
    """The detectable gap at the Holm family's first step, the threshold the family's smallest p must clear."""
    if gap.minimum_detectable_family is None:
        return ""
    return f", ±{gap.minimum_detectable_family:.3f} at the family's first step"


def family_text(analysis: AnalysisResult) -> str:
    sizes = {gap.family_size for pair in analysis.pairs for gap in (pair.axes.x, pair.axes.y)}
    return f"Holm family: {', '.join(str(size) for size in sorted(sizes))} gaps over every pair and both axes"


def pair_lines(
    compass: Compass, analysis: AnalysisResult, elicitations: Sequence[PairElicitation], alone: str
) -> tuple[str, ...]:
    """Each pair's elicitation, gaps, and orderings; `alone` says why there is no pair."""
    by_pair = {(pair.first, pair.second): pair for pair in elicitations}
    lines: list[str] = [family_text(analysis)] if analysis.pairs else []
    for pair in analysis.pairs:
        lines.append(f"{pair.first} vs {pair.second}, gap = {pair.second} minus {pair.first}")
        lines.append(f"{INDENT}{elicitation_text(by_pair[(pair.first, pair.second)])}")
        for axis in AxisKey:
            gap = pair.axes.get(axis)
            ordering = ordering_text(pair.orderings.get(axis), pair.first, pair.second)
            lines.append(f"{INDENT}{axis_label(compass, axis)}: {ordering}")
            lines.append(
                f"{INDENT * 2}gap {estimate_text(gap.gap)}{family_step_text(gap)}; d_z {d_z_text(gap.d_z)}; "
                f"p {gap.p_raw:.3g}, Holm p {gap.p_holm:.3g}"
            )
            lines.append(
                f"{INDENT * 2}score correlation {signed_text(gap.correlation)}; "
                f"{count_text(gap.opposed_questions)} questions oppose the gap"
            )
            lines.append(
                f"{INDENT * 2}equivalence: {equivalence_text(pair.equivalences.get(axis))}; "
                f"p {gap.p_equivalence_raw:.3g}, Holm p {gap.p_equivalence_holm:.3g}"
            )
            lines.append(
                f"{INDENT * 2}gap {bound_text(pair.bounds.get(axis))}; {robustness_text(pair.robustness.get(axis))}"
            )
            lines.extend(f"{INDENT * 2}{line}" for line in scale_use_lines(pair.scale_use.get(axis)))
            lines.append(f"{INDENT * 2}reading: {outcome_text(pair.outcomes.get(axis))}")
    return section("Comparisons", lines or [f"none: {alone}"])


def sd_text(sd: float | None) -> str:
    return "undefined" if sd is None else f"{sd:.2f}"


def scale_use_lines(use: ScaleUse) -> tuple[str, ...]:
    """A warning line when the two models use the scale unequally; nothing otherwise."""
    if not use.differs:
        return ()
    return (
        f"scale use differs: rating sd {sd_text(use.sd_first)} against {sd_text(use.sd_second)}; "
        "the gap is partly one of scale use",
    )


def robustness_text(robustness: OrderingRobustness | None) -> str:
    match robustness:
        case OrderingRobustness(cells=cells, same_sign=same_sign):
            return f"the gap keeps its sign in {same_sign} of {cells} cells"
        case None:
            return "the gap has no sign to keep"


def outcome_text(outcome: PairOutcome) -> str:
    """Exhaustive over PairOutcome; the undetermined reading says what it is not."""
    match outcome:
        case PairOutcome.DIFFERENT_NOT_EQUIVALENT:
            return "different, and not shown to be within the margin"
        case PairOutcome.DIFFERENT_AND_EQUIVALENT:
            return "different, and within the margin"
        case PairOutcome.EQUIVALENT_NOT_DIFFERENT:
            return "within the margin, and not shown to differ"
        case PairOutcome.UNDETERMINED:
            return "undetermined: neither shown to differ nor shown to be within the margin"
        case _:
            assert_never(outcome)


def shares_line(profile: RatingProfile) -> str:
    shares = ", ".join(f"{share:.0%}" for share in profile.shares)
    midpoint = "no midpoint" if profile.midpoint_share is None else f"midpoint {profile.midpoint_share:.0%}"
    deviation = "undefined" if profile.rating_sd is None else f"{profile.rating_sd:.2f}"
    return (
        f"ratings {shares} over {profile.answered} answers; {midpoint}, ends {profile.ends_share:.0%}, sd {deviation}"
    )


def split_line(split: ScoreSplit) -> str:
    absolute = "undefined" if split.mean_absolute is None else f"{split.mean_absolute:.3f}"
    return (
        f"question scores: {split.positive} above 0, {split.negative} below, {split.zero} at 0; "
        f"mean |score| {absolute}; {split.opposing_facets} facets oppose the position; "
        f"facet-balanced position {signed_text(split.facet_balanced)}"
    )


def agreement_line(agreement: StatementAgreement) -> str:
    icc = "undefined" if agreement.icc is None else f"{agreement.icc:+.3f}"
    return (
        f"statements: {agreement.one_sided} of {agreement.statements} answered on one side throughout, "
        f"{agreement.identical} rated the same in every cell, {agreement.wide} spread {agreement.wide_range} or more "
        f"points; ICC between statements {icc}"
    )


def farthest_line(split: ScoreSplit) -> str:
    """The question scores farthest from the position, as the profile names them; undefined without an interval."""
    named = ", ".join(f"{score.question} {score.score:+.3f}" for score in split.farthest)
    return f"farthest from the position: {named or 'undefined'}"


def profile_lines(compass: Compass, analysis: AnalysisResult) -> tuple[str, ...]:
    """Each model's use of the scale, split of question scores, and statement agreement per axis; gates nothing."""
    lines: list[str] = []
    for result in analysis.models:
        lines.append(f"{result.model}")
        for axis in AxisKey:
            profile = result.profile.get(axis)
            lines.append(f"{INDENT}{axis_label(compass, axis)}: {shares_line(profile.ratings)}")
            lines.append(f"{INDENT * 2}{split_line(profile.scores)}")
            lines.append(f"{INDENT * 2}{farthest_line(profile.scores)}")
            lines.append(f"{INDENT * 2}{agreement_line(profile.statements)}")
    return section("Profile", lines)


def dropped_text(unanswered: AxisUnanswered) -> str:
    dropped = ", ".join(f"{dropped.question} ({dropped.unanswered} unanswered)" for dropped in unanswered.dropped)
    return f"questions dropped: {dropped or 'none'}"


def unanswered_lines(compass: Compass, analysis: AnalysisResult) -> tuple[str, ...]:
    """Each model's unanswered trials per axis, the declines toward each pole, and the questions they drop."""
    lines: list[str] = []
    for result in analysis.models:
        lines.append(f"{result.model}")
        for axis in AxisKey:
            unanswered = result.unanswered.get(axis)
            named = compass.axes.get(axis)
            lines.append(
                f"{INDENT}{axis_label(compass, axis)}: {unanswered.trials} unanswered trials; declined "
                f"{unanswered.declined.negative} toward {named.negative}, "
                f"{unanswered.declined.positive} toward {named.positive}; {dropped_text(unanswered)}"
            )
    return section("Unanswered", lines)


def equivalence_text(claim: EquivalenceClaim) -> str:
    match claim:
        case Asserted(value=Equivalence(margin=margin)):
            return f"within ±{margin:.3f}"
        case Withheld(reasons=reasons):
            return withheld_text(reasons)


def counts_text[K: StrEnum](counts: Mapping[K, int]) -> str:
    """The non-zero counts, as `kind count`, or `none`."""
    return ", ".join(f"{kind} {count}" for kind, count in counts.items() if count) or "none"


def outcome_lines(analysis: AnalysisResult) -> tuple[str, ...]:
    return section(
        "Outcomes",
        [
            f"{result.model}: {outcomes.answered} answered, {outcomes.hedged} of them hedged, "
            f"{outcomes.declined} declined, {outcomes.pending} pending; "
            f"format failures: {counts_text(outcomes.format_failed)}; lost: {counts_text(outcomes.lost)}"
            for result in analysis.models
            for outcomes in (result.outcomes,)
        ],
    )


def counted_text(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in counts.items()) or "none"


def span_text(first: datetime | None, last: datetime | None, review_after: datetime | None) -> str:
    if first is None or last is None or review_after is None:
        return "no reply received"
    return (
        f"replies received from {first.isoformat(timespec='seconds')} to {last.isoformat(timespec='seconds')}; "
        f"re-check after {review_after.date().isoformat()}"
    )


def host_lines(analysis: AnalysisResult) -> tuple[str, ...]:
    """Each model's replies per upstream host, per served model string, and per system fingerprint, with when
    they arrived; several hosts, strings, or fingerprints in one run mean its replies may come from different
    backends."""
    lines: list[str] = []
    for result in analysis.models:
        lines.append(f"{result.model}: hosts {counted_text(result.hosts)}")
        lines.append(
            f"{INDENT}served as {counted_text(result.served)}; fingerprints {counted_text(result.fingerprints)}"
        )
        lines.append(f"{INDENT}{span_text(result.first_reply_at, result.last_reply_at, result.review_after)}")
    return section("Hosts", lines)


def sampling_text(sampling: Sampling) -> str:
    """Every sampling value as sent; an unset top_p leaves the host's default in force, unrecorded."""
    top_p = "host default" if sampling.top_p is None else f"{sampling.top_p}"
    return (
        f"temperature {sampling.temperature}, top_p {top_p}, max_tokens {sampling.max_tokens}, "
        f"reasoning {sampling.reasoning}"
    )


def reasoning_text(sampling: Sampling, usage: ModelUsage) -> str:
    """How many completed replies carried reasoning tokens, said only when the endpoint asked for reasoning."""
    if sampling.reasoning is ReasoningEffort.OFF:
        return ""
    return f"; reasoning requested: {usage.reasoning_replies} of {usage.completed} completed replies carry it"


def usage_lines(models: Mapping[ModelId, ModelSpec], analysis: AnalysisResult) -> tuple[str, ...]:
    lines: list[str] = []
    for result in analysis.models:
        usage, sampling = result.usage, models[result.model].sampling
        lines.append(
            f"{result.model}: {usage.attempts} attempts, {usage.retries} of them retries, {usage.completed} completed; "
            f"{usage.prompt_tokens} prompt, {usage.completion_tokens} completion, "
            f"{usage.reasoning_tokens} reasoning tokens; ${usage.cost_usd:.4f} reported, "
            f"{usage.unpriced_attempts} attempts without a reported cost"
        )
        lines.append(
            f"{INDENT}{result.outcomes.format_failed[FormatFailureKind.TRUNCATED]} replies truncated at max_tokens"
            f"{reasoning_text(sampling, usage)}"
        )
    return section("Usage", lines)


def listing_text(listing: ModelListing | None) -> str:
    match listing:
        case None:
            return "no listing"
        case ModelListing(listed_at=listed_at, host=host, supported_parameters=parameters):
            listed = "listed at an unknown date" if listed_at is None else f"listed {listed_at.date().isoformat()}"
            if host is None:
                return f"{listed}; no host pinned, so no parameter list"
            if parameters is None:
                return f"{listed}; host {host!r} not among the slug's hosts"
            return f"{listed}; host {host!r} supports {', '.join(parameters) or 'nothing'}"


def listing_lines(document: ReportDocument) -> tuple[str, ...]:
    """Each model's provider listing when the run started, then the warnings the listings raise."""
    warnings = render_findings(document.findings).splitlines() or ["none"]
    return (
        *(f"{name}: {listing_text(document.run.listings.get(name))}" for name in document.experiment.models),
        "warnings:",
        *(f"{INDENT}{warning}" for warning in warnings),
    )


def provenance_lines(document: ReportDocument) -> tuple[str, ...]:
    run = document.run
    return section(
        "Provenance",
        [
            f"run {run.run_id}, created {run.created_at.isoformat(timespec='seconds')}, "
            f"code revision {run.code_revision}",
            f"experiment hash {run.experiment}",
            f"questionnaire hash {document.experiment.questionnaire}",
            f"compass-bench {document.version}",
            *listing_lines(document),
        ],
    )


def render_text(document: ReportDocument) -> str:
    compass, analysis = document.questionnaire.compass, document.result
    sections = (
        header_lines(document),
        position_lines(compass, analysis),
        facet_lines(compass, analysis),
        consistency_lines(compass, analysis),
        profile_lines(compass, analysis),
        pair_lines(compass, analysis, document.elicitations, "the run has one model"),
        unanswered_lines(compass, analysis),
        outcome_lines(analysis),
        host_lines(analysis),
        usage_lines(document.experiment.models, analysis),
        provenance_lines(document),
    )
    return "\n\n".join("\n".join(lines) for lines in sections)


def runs_text(count: int) -> str:
    return f"{count} run" if count == 1 else f"{count} runs"


def pooled_header_lines(document: PooledReportDocument) -> tuple[str, ...]:
    return (
        f"compass-bench pooled report: pool {document.pool}, {runs_text(len(document.runs))} "
        f"on the {document.scale} scale",
        pooled_status_text(document.status),
        *questionnaire_lines(document.questionnaire),
        settings_text(document.analysis),
        system_prompt_text(document.system_prompt),
    )


def pooled_run_lines(document: PooledReportDocument) -> tuple[str, ...]:
    """Each run with its experiment, then each model with the runs its answers come from."""
    runs = [
        line
        for pooled in document.runs
        for line in (
            f"run {pooled.run.run_id}: {pooled.experiment.name}, created "
            f"{pooled.run.created_at.isoformat(timespec='seconds')}, code revision {pooled.run.code_revision}",
            *(
                f"{INDENT}{line}"
                for line in configuration_lines(pooled.experiment, pooled.endpoints, document.questionnaire)
            ),
        )
    ]
    compass = document.questionnaire.compass
    models = [
        line
        for model in document.models
        for line in (
            f"{model.model}: {runs_text(len(model.runs))}, {', '.join(model.runs)}; between runs "
            + ", ".join(
                f"{axis_label(compass, axis)} {reliability_text(model.reliability.get(axis))}" for axis in AxisKey
            ),
            *scale_reference_lines(compass, model.scale_reference),
        )
    ]
    return (*section("Runs", runs), "", *section("Models", models))


def scale_reference_lines(compass: Compass, reference: ScaleReference | None) -> tuple[str, ...]:
    """How the model answered the native scale's midpoint, per axis, and whether its forced-choice position is held."""
    if reference is None:
        return ()
    readings = []
    for axis in AxisKey:
        share = reference.midpoint_share.get(axis)
        if share is None:
            readings.append(f"{axis_label(compass, axis)} unscored")
            continue
        held = "forced, not held" if reference.forced_not_held.get(axis) else "held"
        readings.append(f"{axis_label(compass, axis)} {share:.0%} at the midpoint, so {held}")
    return (f"{INDENT}on the native scale (pool {reference.native_pool}): {'; '.join(readings)}",)


def reliability_text(reliability: RunReliability | None) -> str:
    match reliability:
        case RunReliability(icc=icc, band=band, questions=questions, runs=runs):
            return f"ICC {icc:+.3f} ({band}) over {questions} questions in {runs} runs"
        case None:
            return "ICC undefined"


def pooled_models(document: PooledReportDocument) -> dict[ModelId, ModelSpec]:
    """Each model's spec from the runs that asked it; a pool's runs agree on every setting but the price."""
    return {model: spec for pooled in document.runs for model, spec in pooled.experiment.models.items()}


def pooled_provenance_lines(document: PooledReportDocument) -> tuple[str, ...]:
    warnings = render_findings(document.findings).splitlines() or ["none"]
    return section(
        "Provenance",
        [
            f"pool {document.pool}",
            f"questionnaire hash {document.runs[0].experiment.questionnaire}",
            f"compass-bench {document.version}",
            "warnings:",
            *(f"{INDENT}{warning}" for warning in warnings),
        ],
    )


def render_pooled_text(document: PooledReportDocument) -> str:
    compass, analysis = document.questionnaire.compass, document.result
    sections = (
        pooled_header_lines(document),
        pooled_run_lines(document),
        position_lines(compass, analysis),
        facet_lines(compass, analysis),
        consistency_lines(compass, analysis),
        profile_lines(compass, analysis),
        pair_lines(compass, analysis, document.elicitations, "the pool has one model"),
        unanswered_lines(compass, analysis),
        outcome_lines(analysis),
        host_lines(analysis),
        usage_lines(pooled_models(document), analysis),
        pooled_provenance_lines(document),
    )
    return "\n\n".join("\n".join(lines) for lines in sections)
