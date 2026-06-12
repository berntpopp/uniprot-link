# Changelog

All notable changes to uniprot-link are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning.

## [0.2.0] - 2026-06-11

A correctness and ergonomics milestone: 15 fixes across the typed protein and
taxonomy tools, plus a server-wide `response_mode` knob and a universal chaining
and not-found contract.

### Fixed

- `get_taxon` now returns the correct DIRECT parent (previously an arbitrary
  ancestor) and an ordered lineage from species up to root, each entry an object
  with `taxon_id` / `scientific_name` / `rank`.
- `get_protein_go_terms` groups annotations into real
  `biological_process` / `molecular_function` / `cellular_component` aspects
  (previously every term landed under `unknown`).
- `get_protein_features` with `feature_types=["domain"]` now matches the
  coordinate-bearing `Domain_Extent` class, and each returned `type` round-trips
  to the filter vocabulary.
- `get_protein_variants` now populates structured `diseases` (via
  `skos:related`).
- `get_protein` returns `not_found` for a nonexistent accession (previously
  `success: true` with an empty body).
- Unified `not_found` handling across all `get_protein*` tools.
- `run_sparql_query` rejects write/UPDATE queries as `invalid_input` (previously
  surfaced as `internal_error`).

### Added

- `response_mode` (`minimal` | `compact` | `standard` | `full`, default
  `compact`) on `get_protein`, `get_protein_sequence`,
  `get_protein_cross_references`, and `map_identifiers`.
- `disease_associated_only` option on `get_protein_variants`, plus `dbsnp`
  rsIDs and a `truncated` block.
- MIM id surfaced on `get_protein_diseases`.
- `elapsed_ms` and `cached` on typed-tool payloads.
- Universal `_meta.next_commands` on every tool, on success AND error.
- `filter_hint` echoing accepted keys when a `get_protein_features` filter
  matches nothing.
- Fuzzy multi-word example-query search.
- Capabilities advertise `response_modes`, `default_response_mode`, `read_only`,
  and a `not_found_contract`.

### Changed

- Compact provenance: short `citation` (DOI) inline; the full citation lives in
  capabilities and `uniprot://citation`.
- Cross-reference and mapped ids are short by default; `response_mode=full`
  restores raw IRIs.
- `get_taxon` lineage is now a list of objects instead of bare ids.
- `get_protein_sequence` no longer duplicates the canonical isoform inside the
  `isoforms` list; `minimal` mode returns metadata only.

### Performance

- `get_protein_features` with a `feature_types` filter binds `?type` via
  `VALUES` instead of `FILTER(?type IN …)`, a bound join that is ~5x faster on
  QLever (e.g. a single domain filter dropped from ~11s to ~2s).
- `find_proteins` no longer leads with a redundant `?protein a up:Protein`
  triple (a 48-billion-triple scan); the required mnemonic/organism joins
  already imply protein-hood.
- An unknown `feature_types` value now lists the accepted keys inline in the
  error, so an agent self-corrects without a capabilities round trip.

## [0.1.0] - 2026-06-11

### Added

- Initial release: an MCP + FastAPI server wrapping the UniProt SPARQL endpoint
  (`https://sparql.uniprot.org/sparql`, release 2026_01, QLever engine).
- **14 MCP tools**:
  - Discovery: `get_server_capabilities`.
  - SPARQL: `run_sparql_query` (SELECT/ASK/CONSTRUCT/DESCRIBE, federation,
    auto-LIMIT, 7 result formats), `search_example_queries`, `get_example_query`
    (backed by UniProt's 126 curated examples in the `sparql-examples` graph).
  - Proteins: `find_proteins`, `get_protein`, `get_protein_sequence`,
    `get_protein_features`, `get_protein_variants`, `get_protein_diseases`,
    `get_protein_cross_references`, `get_protein_go_terms`, `map_identifiers`.
  - Taxonomy: `get_taxon`.
- **Discovery resources**: `uniprot://capabilities`, `uniprot://usage`,
  `uniprot://reference`, `uniprot://prefixes`, `uniprot://research-use`,
  `uniprot://citation`.
- Structured response envelope (`success`/`_meta`/`next_commands`) and error
  taxonomy (`invalid_input`, `not_found`, `query_syntax_error`, `query_timeout`,
  `rate_limited`, `upstream_unavailable`, `internal_error`).
- Async SPARQL client with token-bucket rate limiting, retries, format
  negotiation, and a contact-email User-Agent per UniProt etiquette.
- Three transports (unified / http / stdio), Docker image, Makefile, 600-LOC
  per-file budget, and a unit + live-integration test suite.

### Notes

- Query builders are tuned for QLever's timeout characteristics (bound joins
  over OPTIONAL property paths, aggregation isolated in sub-SELECTs, app-side
  sorting). See `AGENTS.md` and `research/verify_queries.py`.
