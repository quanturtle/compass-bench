"""Text for `runs list` and `runs show`."""

from collections.abc import Sequence

from compass_bench.domain.run import RunOverview, RunProgress


def trial_totals(progress: RunProgress) -> str:
    finished = sum(model.finished for model in progress.models)
    total = finished + sum(model.pending for model in progress.models)
    return f"{finished}/{total} trials finished"


def circuit_text(progress: RunProgress) -> str:
    """Open endpoint circuits, then open model circuits marked `model`."""
    opened = [*progress.open_circuits, *(f"model {model}" for model in progress.open_model_circuits)]
    return ", ".join(opened) if opened else "none"


def render_overview(overview: RunOverview) -> str:
    run, progress = overview.run, overview.progress
    lines = [
        f"run {run.run_id}",
        f"  created: {run.created_at.isoformat(timespec='seconds')}",
        f"  experiment: {run.experiment}",
        f"  code revision: {run.code_revision}",
        f"  progress: {trial_totals(progress)}",
        *(f"    {model.model}: {model.finished} finished, {model.pending} pending" for model in progress.models),
        f"  spent: ${progress.spent_usd:.4f}",
        f"  orphaned attempts: {progress.orphaned}",
        f"  open circuits: {circuit_text(progress)}",
    ]
    return "\n".join(lines)


def render_overviews(overviews: Sequence[RunOverview]) -> str:
    """One line per run."""
    if not overviews:
        return "no runs"
    return "\n".join(
        f"{overview.run.run_id}  {overview.run.created_at.isoformat(timespec='seconds')}  "
        f"{trial_totals(overview.progress)}  ${overview.progress.spent_usd:.4f}  "
        f"open circuits: {circuit_text(overview.progress)}"
        for overview in overviews
    )
