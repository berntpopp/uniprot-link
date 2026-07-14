# Development

## Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
make install          # uv sync --group dev (creates .venv, writes uv.lock)
```

## Run

```bash
make dev              # unified server (REST + MCP/HTTP) on 127.0.0.1:8000
# or, directly via the console script:
uv run uniprot-link serve --transport unified --host 127.0.0.1 --port 8000
```

## Quality gates

```bash
make ci-local         # format-check + lint + lint-loc + typecheck + tests
make format           # apply ruff formatting
make lint-fix         # ruff autofix
make typecheck        # mypy strict
make lint-loc         # enforce 600 lines/module
```

## Tests

```bash
make test             # unit tests (offline, respx-mocked) — the default
make test-integration # live UniProt SPARQL endpoint (pytest -m integration)
make test-cov         # coverage report (gate 80%)
```

Unit tests mock the upstream with a `FakeSparqlClient` (`tests/conftest.py`) or
`respx` (`tests/unit/test_client.py`); no network. Integration tests hit the real
endpoint and are excluded from `ci-local`.

## Changing SPARQL queries

The query builders in `uniprot_link/services/queries/` (`proteins.py`,
`taxonomy.py`, `examples.py`, `validation.py`) are the riskiest code in the repo.
After editing a builder, re-validate it live:

```bash
python research/verify_queries.py
```

This runs every builder against the endpoint and prints row counts + timings, so
you catch QLever timeouts before they reach a tool. See `AGENTS.md`
("SPARQL / QLever Discipline") for the query patterns that stay fast.

## Project layout

See `docs/architecture.md` for the layer map. Hard rules live in `AGENTS.md`
(600-LOC modules, `respx` mocking, research-use scope, ASCII, no `pip`).

## Deploying / release gate

Containers, the production overlays, the Host/Origin boundary, and the
build-provenance release gate (`scripts/check_deployed_version.py`) are documented
in [`deployment.md`](deployment.md). Configuration variables are in
[`configuration.md`](configuration.md).

A release is not done until the deployed `/health` version equals
`uniprot_link.__version__` — the running server can otherwise silently lag the
source.
