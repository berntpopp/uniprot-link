# AGENTS.md

Shared repository instructions for agentic coding tools working in uniprot-link.

## Project

uniprot-link is a Python MCP + FastAPI server that grounds protein research in
the UniProt SPARQL endpoint (`https://sparql.uniprot.org/sparql`, a QLever-backed
SPARQL 1.1 service). FastAPI is a thin host providing `/health` and `/` only; the
product surface is the MCP toolset.

Primary areas:

- `uniprot_link/` - Python package: SPARQL client, query builders, shaping, MCP
  tools, config, server manager
- `uniprot_link/services/queries/` - parametrized SPARQL query builders, split by
  domain (`proteins.py`, `taxonomy.py`, `examples.py`, `validation.py`) - the
  riskiest code in the repo; validate changes against the live endpoint
- `uniprot_link/mcp/` - MCP tools, facade, error envelope, capabilities, resources
- `tests/` - unit and integration tests
- `docker/` - Dockerfile and Compose
- `docs/` - architecture, usage, and design specs (`docs/superpowers/`)
- `research/` - throwaway live-endpoint verification scripts (not shipped/typed)

## Source Of Truth

- Use this file for shared repo-wide agent guidance.
- Keep `CLAUDE.md` lean and Claude-specific; it references this file.
- Prefer `Makefile` targets over ad hoc commands.
- Use `uv.lock` as the dependency lock source of truth.

## Working Rules

- Do not revert or overwrite changes you did not make unless explicitly asked.
- Keep edits scoped to the task and avoid unrelated refactors.
- Prefer existing code patterns over new abstractions.
- Put tests under `tests/`; do not create alternate test roots.
- Use ASCII unless a file already requires non-ASCII content.
- Keep MCP tools research-use scoped; never imply clinical decision support.
- Keep live upstream calls out of the default unit-test path (mark them
  `@pytest.mark.integration`).

## SPARQL / QLever Discipline

The endpoint is fast for *bound* joins but can time out (45 min server cap) on:

- property paths inside `OPTIONAL` (e.g. `?s up:range/faldo:begin/faldo:position ?x`)
- `GROUP_CONCAT` / `GROUP BY` over large literals (sequences, comments)
- `ORDER BY` over a large pre-LIMIT result set

Mitigations used throughout the query builders: anchor on an accession/gene/organism;
make universally-present fields REQUIRED joins (not OPTIONAL); expand FALDO ranges
to explicit hops; isolate aggregation in sub-SELECTs; sort small result sets in
Python (`shaping.py`) rather than in SPARQL. When you touch a query builder,
re-validate timing with `research/verify_queries.py`.

## Commands

Required check before claiming completion:

- `make ci-local`

Useful focused commands: `make install`, `make format`, `make lint`,
`make lint-loc`, `make typecheck`, `make test`, `make test-integration`,
`make dev`, `make mcp-serve`.

## Coding Standards

- Use `uv` for dependency management; never `pip install` directly.
- Modern typing: `list[str]`, `dict[str, int]`, `str | None`.
- Format and lint with Ruff; type check with mypy (strict, py3.12).
- Mock outbound httpx with `respx` in unit tests.

## File Size Discipline

Hard cap: **600 lines per Python module** in `uniprot_link/`. Enforced by
`make lint-loc` (wired into `make ci-local`). Tests are exempt. Prefer cohesive
splits by responsibility.

## UniProt Domain Notes

- Endpoint: `https://sparql.uniprot.org/sparql` (free, no auth). Provide a contact
  email in the User-Agent (configured via `UNIPROT_LINK_SPARQL__CONTACT_EMAIL`).
- 21 named graphs (~232B triples); release tag in `services/constants.py`.
- Accession examples: P05067 (APP), P38398 (BRCA1). Gene/organism: BRCA1 + taxon
  9606. Keyword IRIs use the integer id with leading zeros stripped (KW-0007 ->
  `.../keywords/7`). Canonical sequence isoform IRI ends with `-1`.
