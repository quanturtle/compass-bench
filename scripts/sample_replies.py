"""Draw a stratified sample of stored replies for a second reader.

Writes the sample with the tool's readings, and a blinded copy for the second reader to fill in; the labelled copy
goes to scripts/reader_agreement.py. Needs COMPASS_BENCH_DATABASE_URL.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from compass_bench.app.reader_sample import SAMPLE_ID_LENGTH, SampleRow, blind, sample_replies
from compass_bench.cli import open_store
from compass_bench.domain.ids import RunId
from compass_bench.domain.value import Value
from compass_bench.settings import load_settings


@dataclass(frozen=True)
class SampleArguments:
    runs: tuple[RunId, ...]
    answered: int
    out: Path
    blind_out: Path


def parse_arguments(argv: Sequence[str]) -> SampleArguments:
    parser = argparse.ArgumentParser(description="Sample stored replies for a second reader.")
    parser.add_argument("runs", nargs="+", help="run ids to sample from")
    parser.add_argument("--answered", type=int, default=100, help="plain ratings to draw per run")
    parser.add_argument("--out", type=Path, required=True, help="the sample with the tool's readings")
    parser.add_argument("--blind-out", type=Path, required=True, help="the sample without them, to label by hand")
    arguments = parser.parse_args(argv)
    return SampleArguments(
        runs=tuple(RunId(run) for run in arguments.runs),
        answered=arguments.answered,
        out=arguments.out,
        blind_out=arguments.blind_out,
    )


async def draw(arguments: SampleArguments) -> tuple[SampleRow, ...]:
    async with open_store(load_settings(os.environ)) as store:
        return await sample_replies(arguments.runs, store, arguments.answered)


def write_rows(path: Path, rows: Sequence[Value]) -> None:
    documents = [row.model_dump(mode="json") for row in rows]
    path.write_text(json.dumps(documents, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return


def main() -> None:
    arguments = parse_arguments(sys.argv[1:])
    rows = asyncio.run(draw(arguments))
    write_rows(arguments.out, rows)
    write_rows(arguments.blind_out, blind(rows))
    print(f"{len(rows)} replies sampled; ids are {SAMPLE_ID_LENGTH} hex digits")
    return


if __name__ == "__main__":
    main()
