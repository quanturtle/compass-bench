.PHONY: check schema lock audit audit-check schema-check replicate mutate

# format, lint, type-check, and test; set COMPASS_BENCH_TEST_DATABASE_URL to run the Postgres contract tests too
check:
	uv run ruff format --check src scripts tests
	uv run ruff check src scripts tests
	uv run mypy src scripts tests
	uv run pytest

# regenerate schema/report-<version>.json and schema/examples/ from the contract models
schema:
	uv run python scripts/generate_schema.py

# record every locked component's digest in version.lock.json; refuses while VERSION is unchanged and one differs
lock:
	uv run python scripts/update_lock.py

# audit interval coverage, the claim rates, and the position's bias on simulated populations, stamped with the commit;
# about 3.3 CPU-hours, spread over every core
audit:
	COMPASS_BENCH_CODE_REVISION=$$(git rev-parse --short HEAD) uv run python scripts/statistical_audit.py --runs 10000

# re-run every scenario of the committed audit with its stored seed, capped at 2000 runs, and fail when a rate moved
audit-check:
	uv run python scripts/statistical_audit.py --check audits/statistical-audit.json --check-runs 2000

# regenerate the schema and examples, and fail when the checked-in files differ; the generator never writes
# version.lock.json, which tests/test_version_lock.py holds
schema-check:
	uv run python scripts/generate_schema.py
	git diff --exit-code schema/ version.lock.json

# everything a reviewer can replicate from the repository: the schema, the examples, and the audit
replicate: schema-check audit-check

# mutation-test the statistics, the scoring, the claim gates, and the pooling; fail on a mutant that is not killed,
# unless tests/equivalent_mutants.json lists it with the reason no test can tell it from the original. The run leaves
# the Postgres tests out: mutmut's parallel workers would share the one test database, and their collisions fail tests
# no mutant broke
mutate:
	rm -rf mutants
	env -u COMPASS_BENCH_TEST_DATABASE_URL uv run mutmut run
	uv run mutmut results --all true > mutants/results.txt
	uv run python scripts/check_mutants.py mutants/results.txt
