"""Command-line entry point and composition root: the only module that names concrete adapters."""

import argparse
import asyncio
import logging
import math
import os
import secrets
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

import httpx

from compass_bench.adapters.files.export_writer import write_document
from compass_bench.adapters.files.source_files import SourceFiles
from compass_bench.adapters.postgres.connection import InvalidDatabaseUrl, create_engine, upgrade_to_head
from compass_bench.adapters.postgres.ledger_store import PostgresLedgerStore
from compass_bench.adapters.terminal.plan_view import render_findings, render_plan
from compass_bench.adapters.terminal.progress import LogProgress
from compass_bench.adapters.terminal.report_view import render_pooled_text, render_text
from compass_bench.adapters.terminal.run_view import render_overview, render_overviews
from compass_bench.adapters.terminal.signals import install_stop
from compass_bench.adapters.transport.openrouter import OpenRouterTransport
from compass_bench.adapters.transport.openrouter_listings import OpenRouterListings
from compass_bench.app.analyze import analyze_run
from compass_bench.app.collect import EndpointRuntime, ExperimentChanged, PromptsChanged, collect, start_run
from compass_bench.app.compile import InvalidExperiment, compile_experiment, read_questionnaire
from compass_bench.app.export import export_reports
from compass_bench.app.pool import pooled_export_name, pooled_reports
from compass_bench.app.runs import run_overview, run_overviews
from compass_bench.contract.v2 import PooledReportDocument
from compass_bench.domain.design.endpoint import EndpointSettings
from compass_bench.domain.design.preflight import plan_findings, summarize_plan
from compass_bench.domain.findings import has_errors
from compass_bench.domain.ids import EndpointId, QuestionnaireHash, RunId
from compass_bench.domain.instrument.questionnaire import questionnaire_hash
from compass_bench.domain.listing import listing_findings
from compass_bench.domain.pooling import ModelSettingsDiffer
from compass_bench.domain.run import CollectionEnd, NoRecordedBudget, latest_budget
from compass_bench.ports.ledger_store import RunLocked, UnknownRun
from compass_bench.ports.listings import ModelListings
from compass_bench.ports.sources import InvalidSource
from compass_bench.ports.transport import Transport
from compass_bench.settings import MissingSetting, Settings, load_api_keys, load_settings

NONCE_BYTES: Final = 16
PROGRESS_LOGGER: Final = "compass_bench.progress"
INVALID_INPUT_ERRORS: Final = (
    InvalidExperiment,
    InvalidSource,
    MissingSetting,
    InvalidDatabaseUrl,
    UnknownRun,
    NoRecordedBudget,
)


class ExitCode(IntEnum):
    OK = 0
    FAILED = 1
    INVALID_INPUT = 2
    RESUMABLE = 3


@dataclass(frozen=True)
class PlanCommand:
    experiment: Path


@dataclass(frozen=True)
class RunCommand:
    experiment: Path
    budget_usd: float


@dataclass(frozen=True)
class ResumeCommand:
    run: RunId
    budget_usd: float | None


@dataclass(frozen=True)
class RunsListCommand:
    pass


@dataclass(frozen=True)
class RunsShowCommand:
    run: RunId


@dataclass(frozen=True)
class AnalyzeCommand:
    run: RunId


@dataclass(frozen=True)
class ExportCommand:
    runs: tuple[RunId, ...]
    out: Path


@dataclass(frozen=True)
class PoolCommand:
    """`out` None prints the reports as text; a directory receives them as JSON."""

    questionnaire: Path
    out: Path | None


@dataclass(frozen=True)
class DbMigrateCommand:
    pass


type Command = (
    PlanCommand
    | RunCommand
    | ResumeCommand
    | RunsListCommand
    | RunsShowCommand
    | AnalyzeCommand
    | ExportCommand
    | PoolCommand
    | DbMigrateCommand
)


def budget_usd(text: str) -> float:
    """A finite, non-negative dollar amount; NaN would compare false against every spend and lift the cap."""
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from error
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite amount of at least 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    """One subparser per command, so modes are mutually exclusive by construction."""
    parser = argparse.ArgumentParser(
        prog="compass-bench", description="Ask language models a value questionnaire and place them on its two axes."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="validate the inputs and print the resolved plan; no database, no key")
    plan.add_argument("experiment", type=Path, help="the experiment YAML file")

    run = commands.add_parser("run", help="create a run from the experiment, collect it, and print its id")
    run.add_argument("experiment", type=Path, help="the experiment YAML file")
    run.add_argument("--budget-usd", type=budget_usd, required=True, help="the spending cap for the whole run")

    resume = commands.add_parser("resume", help="continue a run's pending trials")
    resume.add_argument("run", help="the run id")
    resume.add_argument(
        "--budget-usd",
        type=budget_usd,
        help="a new cap for the whole run, spend so far included; the latest cap by default",
    )

    runs = commands.add_parser("runs", help="progress, spend, open circuits, and orphaned attempts")
    runs_commands = runs.add_subparsers(dest="runs_command", required=True)
    runs_commands.add_parser("list", help="every run, one line each")
    show = runs_commands.add_parser("show", help="one run")
    show.add_argument("run", help="the run id")

    analyze = commands.add_parser("analyze", help="derive a run's report and print it as text")
    analyze.add_argument("run", help="the run id")

    export = commands.add_parser("export", help="derive each run's report and write it as JSON")
    export.add_argument("runs", nargs="+", help="the run ids")
    export.add_argument("--out", type=Path, required=True, help="the directory to write the documents to")

    pool = commands.add_parser(
        "pool", help="pool every run of a questionnaire by scale, and print each pool's report as text"
    )
    pool.add_argument("questionnaire", type=Path, help="the questionnaire JSON file")
    pool.add_argument("--out", type=Path, help="write each pool's report as JSON into this directory instead")

    db = commands.add_parser("db", help="database administration")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("migrate", help="run the migrations to head")
    return parser


def command_from_arguments(arguments: argparse.Namespace) -> Command:
    match arguments.command:
        case "plan":
            return PlanCommand(experiment=arguments.experiment)
        case "run":
            return RunCommand(experiment=arguments.experiment, budget_usd=arguments.budget_usd)
        case "resume":
            return ResumeCommand(run=RunId(arguments.run), budget_usd=arguments.budget_usd)
        case "runs" if arguments.runs_command == "list":
            return RunsListCommand()
        case "runs" if arguments.runs_command == "show":
            return RunsShowCommand(run=RunId(arguments.run))
        case "analyze":
            return AnalyzeCommand(run=RunId(arguments.run))
        case "export":
            return ExportCommand(runs=tuple(RunId(run) for run in arguments.runs), out=arguments.out)
        case "pool":
            return PoolCommand(questionnaire=arguments.questionnaire, out=arguments.out)
        case "db" if arguments.db_command == "migrate":
            return DbMigrateCommand()
    raise ValueError(f"the parser produced an unknown command: {arguments}")


def parse_command(argv: Sequence[str]) -> Command:
    return command_from_arguments(build_parser().parse_args(argv))


def source_files() -> SourceFiles:
    """Relative input paths resolve against the working directory."""
    return SourceFiles(Path.cwd())


def run_plan(command: PlanCommand) -> ExitCode:
    """Validate every input, then print the plan; any error finding exits INVALID_INPUT."""
    compiled = compile_experiment(command.experiment, source_files())
    findings = compiled.findings + plan_findings(compiled.spec, compiled.questionnaire)
    if has_errors(findings):
        print(render_findings(findings), file=sys.stderr)
        return ExitCode.INVALID_INPUT
    print(render_plan(summarize_plan(compiled.spec, compiled.questionnaire, compiled.findings), compiled.endpoints))
    return ExitCode.OK


def connect_store(settings: Settings) -> PostgresLedgerStore:
    return PostgresLedgerStore(create_engine(settings.database_url))


@asynccontextmanager
async def open_store(settings: Settings) -> AsyncIterator[PostgresLedgerStore]:
    """The store for one command; its engine's connections close when the command ends."""
    store = connect_store(settings)
    try:
        yield store
    finally:
        await store.engine.dispose()


def build_transport(endpoint: EndpointSettings, environ: Mapping[str, str], client: httpx.AsyncClient) -> Transport:
    api_key = load_api_keys(environ, (endpoint.api_key_env,))[endpoint.api_key_env]
    return OpenRouterTransport(endpoint, api_key, client)


def build_endpoints(
    endpoints: Mapping[EndpointId, EndpointSettings], environ: Mapping[str, str], client: httpx.AsyncClient
) -> dict[EndpointId, EndpointRuntime]:
    """One runtime per endpoint; every key variable is checked first, so all missing keys show in one error."""
    load_api_keys(environ, [endpoint.api_key_env for endpoint in endpoints.values()])
    return {
        name: EndpointRuntime(
            transport=build_transport(endpoint, environ, client), slots=asyncio.Semaphore(endpoint.max_concurrency)
        )
        for name, endpoint in endpoints.items()
    }


def build_listings(
    endpoints: Mapping[EndpointId, EndpointSettings], client: httpx.AsyncClient
) -> dict[EndpointId, ModelListings]:
    """One listing reader per endpoint, at the endpoint's base URL; the listing route needs no key."""
    return {name: OpenRouterListings(endpoint.base_url, client) for name, endpoint in endpoints.items()}


def new_nonce() -> str:
    """A fresh run nonce from `secrets`: the only random value a run draws."""
    return secrets.token_hex(NONCE_BYTES)


def progress_logger() -> logging.Logger:
    """Collection progress on stderr, one line per event; httpx's own request logging stays off."""
    logger = logging.getLogger(PROGRESS_LOGGER)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


async def collect_until_stopped(
    run: RunId, budget_usd: float, store: PostgresLedgerStore, endpoints: Mapping[EndpointId, EndpointRuntime]
) -> CollectionEnd:
    """Collect with the stop event wired to SIGINT and SIGTERM."""
    stop = asyncio.Event()
    install_stop(asyncio.get_running_loop(), stop)
    return await collect(run, budget_usd, store, endpoints, LogProgress(progress_logger()), stop)


def collection_exit_code(end: CollectionEnd) -> ExitCode:
    """An interrupt, the budget cap, or open circuits are RESUMABLE; a run another process took over FAILED here."""
    match end:
        case CollectionEnd.COMPLETE:
            return ExitCode.OK
        case CollectionEnd.TAKEN_OVER:
            return ExitCode.FAILED
        case CollectionEnd.INTERRUPTED | CollectionEnd.BUDGET_EXHAUSTED | CollectionEnd.CIRCUITS_OPEN:
            return ExitCode.RESUMABLE


async def run_run(command: RunCommand, environ: Mapping[str, str]) -> ExitCode:
    """Create the run and collect it; the run id prints first, so an interrupted run can be resumed."""
    settings = load_settings(environ)
    compiled = compile_experiment(command.experiment, source_files())
    findings = compiled.findings + plan_findings(compiled.spec, compiled.questionnaire)
    if has_errors(findings):
        print(render_findings(findings), file=sys.stderr)
        return ExitCode.INVALID_INPUT
    async with httpx.AsyncClient() as client, open_store(settings) as store:
        endpoints = build_endpoints(compiled.endpoints, environ, client)
        listings = build_listings(compiled.endpoints, client)
        record = await start_run(compiled, store, listings, new_nonce(), settings.code_revision)
        print(record.run_id, flush=True)
        warnings = listing_findings(compiled.spec, record.listings, record.created_at)
        if warnings:
            print(render_findings(warnings), file=sys.stderr)
        end = await collect_until_stopped(record.run_id, command.budget_usd, store, endpoints)
    return collection_exit_code(end)


async def run_resume(command: ResumeCommand, environ: Mapping[str, str]) -> ExitCode:
    """Collect the run's pending trials under the latest budget, or under --budget-usd when it is given."""
    settings = load_settings(environ)
    async with httpx.AsyncClient() as client, open_store(settings) as store:
        endpoints = build_endpoints(await store.load_endpoints(command.run), environ, client)
        events = await store.load_events(command.run)
        budget_usd = latest_budget(events) if command.budget_usd is None else command.budget_usd
        end = await collect_until_stopped(command.run, budget_usd, store, endpoints)
    return collection_exit_code(end)


async def run_runs_list(environ: Mapping[str, str]) -> ExitCode:
    async with open_store(load_settings(environ)) as store:
        print(render_overviews(await run_overviews(store)))
    return ExitCode.OK


async def run_runs_show(command: RunsShowCommand, environ: Mapping[str, str]) -> ExitCode:
    async with open_store(load_settings(environ)) as store:
        print(render_overview(await run_overview(command.run, store)))
    return ExitCode.OK


async def run_analyze(command: AnalyzeCommand, environ: Mapping[str, str]) -> ExitCode:
    """Print the run's report as text."""
    async with open_store(load_settings(environ)) as store:
        print(render_text(await analyze_run(command.run, store)))
    return ExitCode.OK


async def run_export(command: ExportCommand, environ: Mapping[str, str]) -> ExitCode:
    """Write each run's document into --out and print each path; nothing is written if any run is unknown."""
    async with open_store(load_settings(environ)) as store:
        documents = await export_reports(command.runs, store)
    for name, document in documents.items():
        print(write_document(command.out, name, document))
    return ExitCode.OK


def print_pooled_reports(
    questionnaire: QuestionnaireHash, documents: Sequence[PooledReportDocument], out: Path | None
) -> None:
    """Each report as text, or with `out` each written as JSON and its path printed; a line when no run qualifies."""
    if not documents:
        print(f"no run asked questionnaire {questionnaire}")
        return
    if out is None:
        print("\n\n\n".join(render_pooled_text(document) for document in documents))
        return
    for document in documents:
        print(write_document(out, pooled_export_name(document), document.model_dump(mode="json")))
    return


async def run_pool(command: PoolCommand, environ: Mapping[str, str]) -> ExitCode:
    """Pool every run that asked the questionnaire file's questionnaire, by scale and analysis settings."""
    questionnaire = questionnaire_hash(read_questionnaire(command.questionnaire, source_files()))
    async with open_store(load_settings(environ)) as store:
        documents = await pooled_reports(questionnaire, store)
    print_pooled_reports(questionnaire, documents, command.out)
    return ExitCode.OK


def run_db_migrate(environ: Mapping[str, str]) -> ExitCode:
    upgrade_to_head(load_settings(environ).database_url)
    return ExitCode.OK


def execute(command: Command, environ: Mapping[str, str]) -> ExitCode:
    """Dispatch to the command's handler; domain errors become an exit code and one stderr line here."""
    try:
        match command:
            case PlanCommand():
                return run_plan(command)
            case RunCommand():
                return asyncio.run(run_run(command, environ))
            case ResumeCommand():
                return asyncio.run(run_resume(command, environ))
            case RunsListCommand():
                return asyncio.run(run_runs_list(environ))
            case RunsShowCommand():
                return asyncio.run(run_runs_show(command, environ))
            case AnalyzeCommand():
                return asyncio.run(run_analyze(command, environ))
            case ExportCommand():
                return asyncio.run(run_export(command, environ))
            case PoolCommand():
                return asyncio.run(run_pool(command, environ))
            case DbMigrateCommand():
                return run_db_migrate(environ)
    except INVALID_INPUT_ERRORS as error:
        print(f"compass-bench: {error}", file=sys.stderr)
        return ExitCode.INVALID_INPUT
    except (RunLocked, ExperimentChanged, PromptsChanged, ModelSettingsDiffer) as error:
        print(f"compass-bench: {error}", file=sys.stderr)
        return ExitCode.FAILED


def main() -> None:
    """The environment is copied once, here; every later read, API keys included, reads that copy."""
    raise SystemExit(execute(parse_command(sys.argv[1:]), MappingProxyType(dict(os.environ))))


if __name__ == "__main__":
    main()
