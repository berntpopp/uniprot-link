# uniprot-link

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/berntpopp/uniprot-link/actions/workflows/ci.yml/badge.svg)](https://github.com/berntpopp/uniprot-link/actions/workflows/ci.yml)
[![Conformance](https://github.com/berntpopp/uniprot-link/actions/workflows/conformance.yml/badge.svg)](https://github.com/berntpopp/uniprot-link/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An MCP server (Streamable HTTP) that grounds protein research in the **UniProt SPARQL
endpoint** (`https://sparql.uniprot.org/sparql`) — a QLever-backed SPARQL 1.1 service
over ~232 billion triples in 21 named graphs. It exposes intent-named, token-economical
tools, a guarded raw-SPARQL escape hatch, and UniProt's curated example queries.

> [!IMPORTANT]
> Research use only. Not clinical decision support. Do not use for diagnosis,
> treatment, triage, or patient management.

## Why

UniProt's SPARQL endpoint can answer questions no REST route can — cross-graph joins
over sequence features, variants, diseases, GO terms, taxonomy and cross-references —
but it is a hostile surface to write against. QLever is very fast on *bound* joins and
falls off a cliff on shapes that look harmless: property paths inside `OPTIONAL`,
`GROUP_CONCAT` over large literals, `ORDER BY` before `LIMIT`. The failure mode is not
an error, it is a 45-minute server timeout.

This server carries that discipline so the model does not have to. The typed tools
compile to anchored, timeout-safe queries; `search_sparql_query` admits only bounded
`SELECT`/`ASK` (`CONSTRUCT`/`DESCRIBE` and `SERVICE` federation are rejected, and a
`LIMIT` is auto-injected into unbounded SELECTs); and UniProt's curated example queries
are searchable and executable, so an agent learns the data model instead of guessing
IRIs. Every response carries `_meta.next_commands` — ready-to-run `{tool, arguments}`
steps — plus a structured error taxonomy.

## Quick start

The GeneFoundry instance is hosted — no install required:

```bash
claude mcp add --transport http uniprot-link https://uniprot-link.genefoundry.org/mcp
```

To run your own (Python 3.12+, [uv](https://docs.astral.sh/uv/)):

```bash
make install    # uv sync --group dev
make dev        # unified: REST on / and MCP on /mcp, port 8000
claude mcp add --transport http uniprot-link --scope user http://127.0.0.1:8000/mcp
```

There is **no data build step** — every call queries the live endpoint, which needs no
authentication. Do set `UNIPROT_LINK_SPARQL__CONTACT_EMAIL` to a mailbox you read:
UniProt asks programmatic clients to identify themselves in the `User-Agent`.

## Tools

| Tool | Purpose |
|---|---|
| `get_server_capabilities` | Discovery surface: tool inventory, named graphs, prefixes, formats, workflows, limits |
| `search_sparql_query` | Execute a bounded SELECT/ASK SPARQL query (the power tool) |
| `search_example_queries` | Search UniProt's curated, executable example queries |
| `get_example_query` | Full SPARQL text and metadata of one curated example |
| `find_proteins` | Search UniProtKB by gene symbol / organism / keyword / EC number / mnemonic |
| `find_proteins_batch` | Resolve several gene symbols to entries concurrently in one call |
| `get_protein` | Core entry summary for one accession |
| `get_protein_sequence` | Canonical and isoform sequences |
| `get_protein_features` | Sequence features with FALDO begin/end coordinates |
| `get_protein_variants` | Natural-variant annotations |
| `get_protein_diseases` | Disease annotations |
| `get_protein_cross_references` | Cross-references grouped by database (PDB, Ensembl, RefSeq, …) |
| `get_protein_go_terms` | GO annotations grouped by aspect, with evidence codes |
| `resolve_identifiers` | Resolve an accession to its primary external database ids |
| `get_taxon` | Resolve an organism by NCBI taxon id or name |

Leaf names are **unprefixed** per the GeneFoundry [Tool-Naming Standard v1](https://github.com/berntpopp/genefoundry-router/blob/main/docs/TOOL-NAMING-STANDARD-v1.md):
`serverInfo.name` is `uniprot-link` and the canonical gateway namespace token is
`uniprot`, so behind the
[genefoundry-router](https://github.com/berntpopp/genefoundry-router) the tools surface
as `uniprot_<tool>` (e.g. `uniprot_find_proteins`). Standalone MCP clients namespace
them as `mcp__uniprot-link__<tool>`.

## Data & provenance

All data comes live from the [UniProt](https://www.uniprot.org/) SPARQL endpoint —
there is no local mirror and no snapshot, so freshness tracks UniProt's release cycle
directly. The release the query builders and the named-graph inventory were validated
against is pinned in `uniprot_link/services/constants.py` and reported by
`get_server_capabilities`. The curated examples come from UniProt's upstream
`sparql-examples` graph.

UniProt data is licensed **CC BY 4.0**. Cite it, verbatim (also served at
`uniprot://citation`):

> The UniProt Consortium. UniProt: the Universal Protein Knowledgebase in 2025.
> Nucleic Acids Res. 2025;53(D1):D609-D617. doi:10.1093/nar/gkae1010

## Documentation

- [Usage](docs/usage.md) — the CLI, typical workflows, `search_sparql_query` rules, and the `uniprot://` discovery resources.
- [Configuration](docs/configuration.md) — every `UNIPROT_LINK_*` variable, the two transports, and the Host / Origin / CORS allowlists.
- [Deployment](docs/deployment.md) — containers, the production overlays, the reverse-proxy boundary, and the build-provenance release gate.
- [Architecture](docs/architecture.md) — the layer map, the response contract, and why QLever shapes the design.
- [Development](docs/development.md) — setup, quality gates, and re-validating a query builder live.
- [AGENTS.md](AGENTS.md) — engineering conventions, including the SPARQL / QLever discipline.

## Contributing

See [`AGENTS.md`](AGENTS.md) for conventions. `make ci-local` is the
definition-of-done gate: format, lint, line budget, README standard, mypy, and tests.
Changes to the query builders in `uniprot_link/services/queries/` must be re-validated
against the live endpoint with `research/verify_queries.py`.

## License

Code: [MIT](LICENSE) © Bernt Popp. Data: UniProt is licensed **CC BY 4.0** by the
UniProt Consortium and requires the citation above.
