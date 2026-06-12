# Changelog

All notable changes to uniprot-link are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning.

## [0.9.0] - 2026-06-12

Closes every finding (F1–F9 + the untested obsolete path) of the v0.8.0
consumer/tester assessment
([`mcp-assessment-v0.8.0-consumer-tester.md`](docs/mcp-assessment-v0.8.0-consumer-tester.md),
overall **8.0/10**, docked for a silent isoform correctness defect). Each finding
was reproduced live before the fix and re-verified live after; grounded in
2025–2026 MCP best-practice research. Design + plan:
[`docs/superpowers/specs/2026-06-12-v0.9.0-assessment-remediation-design.md`](docs/superpowers/specs/2026-06-12-v0.9.0-assessment-remediation-design.md).

### Fixed

- **Isoform handling is now correct and consistent across the whole
  `get_protein_*` family (F1/F2 — the correctness defect that capped the score).**
  - `get_protein_features` no longer **silently returns 0 features** for an
    isoform accession (e.g. `P05067-2`). The query builders for features,
    cross-references, **and GO terms** (the latter two an untested latent twin)
    now anchor on the base entry like variants/diseases already did. Live:
    `P05067-2` → 12 domain/region features (was 0). (F1)
  - `get_protein_sequence` no longer returns `not_found` for a valid isoform.
    An isoform accession returns **that isoform's specific sequence** (its own
    length + a computed mass, since `up:mass` is canonical-only). This restores
    the cross-tool contract `get_protein(P05067-2)` advertises. (F2)
  - Every entry-level tool now **rejects a typo'd isoform index** (clean
    `not_found`) and, for a valid isoform request, echoes `requested_accession` +
    an `isoform_note` — matching `get_protein`'s model. (F1)
- **`run_sparql_query` reports the true `query_type`** (SELECT/ASK/CONSTRUCT/
  DESCRIBE) for non-JSON serializations, with the serialization in a separate
  `serialization` field — a SELECT projected to CSV is no longer mislabeled
  `RDF/raw`. (F8)
- **`latency_profile` no longer under-states reality.** `get_protein_features`
  and `get_protein_diseases` (measured ~1.6–2.3 s cold) move out of the `fast`
  (0–700 ms) band into a `medium` (700–2500 ms) band; bands now describe the
  query class, not a single number. (F4)

### Added

- **`canonical_only` flag on `get_protein_sequence`** returns just the canonical
  isoform (skips the additional-isoform list) — avoids dumping every isoform's
  full sequence when only the canonical is wanted. Plus a `requested_isoform`
  field on isoform-specific responses. (F7)
- **`reviewed_count` (+ a `reviewed_hint`) on `find_proteins`** discloses how many
  of a (reviewed-first) gene page are Swiss-Prot, so a page dominated by TrEMBL is
  never mistaken for "all there is". (F9)
- **`query`/`q` accepted as aliases for `search_example_queries`'s `text`** — a
  natural wrong guess now succeeds instead of erroring. (F6)
- **Documented `find_proteins` paging** in capabilities `limits`:
  `find_proteins_page_size: 25`, `find_proteins_max_limit: 200`, the cross-ref
  compact id cap, and a note clarifying `default_select_limit` is the
  `run_sparql_query` auto-LIMIT (not the find_proteins page size). (F5)

### Changed

- **`find_proteins` latency** (F3): an exact `mnemonic` anchor is fast-pathed to a
  single bound query (~7.9 s → ~3.9 s live, and the redundant TrEMBL scan is
  gone); the common `offset==0` reviewed-first page now issues its COUNT +
  reviewed-fill + unreviewed-fill **concurrently** (wall-clock = slowest leg, not
  the sum). Semantics (reviewed-first ordering, paging) unchanged.
- The `find_proteins` family moved into `services/service_find.py`
  (`FindProteinsServiceMixin`) to keep modules within the 600-line cap.

### Note

The deployed server runs v0.8.0 until redeployed; these fixes are on disk/branch.

## [0.8.0] - 2026-06-12

Closes every finding (F1–F8 + Part 1) of the v0.7.0 tester assessment
([`mcp-assessment-v0.7.0-tester.md`](docs/mcp-assessment-v0.7.0-tester.md),
overall **8/10**). Research-backed against the MCP spec, Anthropic's tool-writing
and code-execution guidance, FastMCP, and Datadog's production lessons. Targets a
re-rated **>9.5/10**. See
[`docs/mcp-assessment-v0.8.0-closure.md`](docs/mcp-assessment-v0.8.0-closure.md).

### Added

- **`find_proteins_batch`** (15th tool): resolve several gene symbols to entries
  in one call, running the lookups **concurrently** so N genes cost ~one cold
  round-trip instead of N sequential ones. Returns `by_gene`, a gene-tagged flat
  `proteins` list, `resolved_genes`, and `unresolved_genes` (no silent empty).
  The canonical "domains for PNKP and NAA10" task drops from ~11 s to ~5 s. (Part 1)
- **Enum value discoverability.** `get_server_capabilities` now carries
  `argument_value_sets` ({tool: {arg: [valid values]}}) so an LLM can pick a valid
  `aspect`/`detail`/`result_format`/`response_mode` before a failed call. (F1)
- **`truncation_contract`** documented in capabilities; the standardized envelope
  is `{returned, total, reason, recovery}`. (F4/F5)

### Changed

- **Invalid enum *value* errors** now list the field's valid **values** with
  "Valid values are listed in allowed_values", instead of the argument **names**
  with the wrong "argument names" wording. Routed through a value-error branch in
  the arg-binding middleware. (F1)
- **`get_protein_cross_references`** with an explicit `databases` filter echoes
  `requested_databases` and flags any name that matched nothing under
  `unmatched_databases` + `database_hint` (with a case-insensitive did-you-mean),
  so a typo'd database no longer reads as a valid "no data" answer. (F2)
- **`get_taxon`** name scan ranks an exact scientific/common-name hit first
  (tagged `match_quality:"exact"`), so `matches[0]` and `next_commands` land on the
  right organism. (F3)
- **Truncation envelope standardized** to `{returned, total, reason, recovery}`
  across `get_protein_features` (true total via fetch-at-cap), `get_protein_go_terms`
  (adds `reason`), `get_protein_variants` and `find_proteins` (exact `total` via a
  cheap COUNT, run only on a full page), and `run_sparql_query` (adds `returned`;
  `total` omitted by design). (F4/F5)
- **`find_proteins(name_contains=)`** matches per word (AND of `CONTAINS`), so
  "polynucleotide kinase" matches "Bifunctional polynucleotide phosphatase/kinase"
  instead of returning zero. Single-word input is unchanged. (F6)
- **`get_protein_features`** hides secondary-structure (helix/strand/turn) by
  default and discloses the count under `excluded_secondary_structure`; pass
  `include_secondary_structure=true` (or name them in `feature_types`) to include
  them — roughly halves the most common feature query's tokens. (Part 1)
- **`get_protein`** echoes `requested_accession` only when it differs from the
  resolved base accession (isoform/redirect); the identical echo is dropped. (F7)
- **`run_sparql_query`** success now carries `_meta.next_commands` like every other
  tool. (F8)

### Internal

- Split `ServiceBase` (cache + execution primitives) into `service_base.py`, the
  `get_taxon` resolver into `service_taxonomy.py`, and the taxon shapers into
  `shaping_taxonomy.py` to keep every module within the 600-line cap.

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
