# Changelog

All notable changes to uniprot-link are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning.

## [0.4.0] - 2026-06-12

An assessment-driven uplift closing the 12 residual bugs from the v0.3.0
re-assessment plus token-efficiency, latency, and consistency gaps. Targets
>9.5/10 on the LLM-consumer rubric.

### Added

- **Structured output (MCP 2025-06-18).** All 14 tools declare an `output_schema`,
  so clients receive validated `structuredContent` alongside the back-compat
  serialized `TextContent` JSON.
- **GO evidence codes.** `get_protein_go_terms` now returns ECO `evidence` ids and
  mapped GO `evidence_codes` (IDA/IEA/IMP/...) per term, for citation. (Bug 10)
- **Disease definitions.** `get_protein_diseases` returns the clinical `definition`
  (the disease vocabulary's own description) and `mnemonic`, distinct from the
  entry-specific `involvement` note (was a single boilerplate `description`). (Bug 9)
- **`request_id`** on every response `_meta` (success and error) for multi-call
  correlation.
- Structured error fields: `allowed_values`, `field`, `hint` are surfaced as
  top-level keys (never truncated in the message). (Bug 2)

### Changed

- **`find_proteins` latency.** Reviewed-first two-phase query with no pre-LIMIT
  global `ORDER BY` (the hotspot); pages are sorted by mnemonic in Python. Broad
  keyword default page drops from ~8.7s toward ~3s; selective anchors stay
  sub-second. (Improvement #3)
- **`get_protein_sequence` compact** returns a first/last-30-residue
  `sequence_preview` (not the full string); use `standard`/`full` for the complete
  sequence. (Bug 6)
- **Token diet.** Per-call `_meta` drops the static `endpoint`; `next_commands`
  trimmed to the top 2 and made content-aware (a zero-count tool points home).
- `get_taxon` by-name now reports `elapsed_ms`/`cached`, includes `rank`, and emits
  `next_commands` (id detail + protein search). (Bug 5)
- Every error envelope now carries `next_commands` (default recovery when no
  explicit fallback). (Bug 3)
- `search_example_queries` de-duplicates example ids and ranks UniProt-native
  examples above federated (Rhea) ones. (Bug 12)

### Fixed

- **`feature_types` round-trip.** The registry now includes the range-bearing
  classes the dump also emits (`natural_variant`, `alternative_sequence`,
  `sequence_conflict`); every returned `type` re-filters successfully. Unmapped
  classes surface as `_unmapped:<Class>` rather than a friendly key the filter
  would reject. (Bug 1)
- Accession validation uses the official UniProtKB grammar, so malformed input
  (e.g. `999999`) fails locally as `invalid_input` instead of round-tripping for a
  404. (Bug 7)
- `get_protein` not-found recovery no longer replays a non-gene accession as
  `find_proteins(gene=...)`. (Bug 8)
- `find_proteins` anchor hint names the real tool `run_sparql_query` (was
  `sparql_query`). (Bug 4)
- `run_sparql_query` empty-body 400s return a cause-oriented hint. (Bug 11)

### Internal

- `services/queries.py` split into a package (`validation`, `proteins`,
  `taxonomy`, `examples`) to stay under the 600-line module cap.

## [0.3.0] - 2026-06-12

### Added

- `get_protein_variants` now returns the `wild_type` residue, a `variant_type`
  (`substitution` | `other`), and an HGVS-style `notation` (e.g. `L176F`) for
  simple substitutions — so amino-acid changes are constructible without a
  separate sequence fetch. Empty `substitution` (deletion/complex) is made
  explicit via `variant_type: "other"` instead of a bare empty string.
- Deployment-freshness guard: `get_server_capabilities` and `/health` now carry a
  `build` stamp (version, git sha, build time); `scripts/check_deployed_version.py`
  gates a release on the deployed version matching the source.
- `run_sparql_query` syntax errors now include a `search_example_queries`
  recovery `next_command`.

### Changed

- `map_identifiers` defaults to a curated set of primary id-mapping databases
  (PDB, Ensembl, RefSeq, HGNC, ...) so it is genuinely a focused, smaller view
  than `get_protein_cross_references`; pass `databases` to override.

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
