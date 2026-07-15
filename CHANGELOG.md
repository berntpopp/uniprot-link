# Changelog

All notable changes to uniprot-link are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning.

## [Unreleased]

### Changed

- Re-vendored the behaviour conformance gate from genefoundry-router `56db958`
  (`docs/conformance/behaviour.py` blob `c69801687`) so live MCP contract checks
  treat not-found example probes as inconclusive and keep empty auxiliary objects from hiding counted rows.

## [5.0.0] - 2026-07-15

Security fix for the SPARQL operation-guard bypass (#29) plus the fleet MCP
contract-hardening sweep, together. Major because the error-code wire values
change, `find_proteins` now requires `gene_symbol`, and `outputSchema` is dropped.

### Security

- **The SPARQL operation guard no longer falls open to a no-whitespace leading
  keyword (#29, R-03 / F-08 residual).** `_leading_token` split the query on
  whitespace, so `SELECT*{...}` tokenised as `SELECT*{?s` and matched neither the
  read-op set nor the write/graph set — defeating the auto-LIMIT injection, the
  `SERVICE`-federation reject, and the `CONSTRUCT`/`DESCRIBE` reject all at once.
  The keyword is now extracted on a real **token boundary** (`^\s*[A-Za-z]+`, skipping
  a leading BOM / zero-width / Unicode-whitespace run) against the comment/string/IRI
  blanked view, so `SELECT*` → `SELECT` and `CONSTRUCT{` → `CONSTRUCT`. The
  `SERVICE` reject now runs for read-form **and unknown** queries (**fail-closed**):
  a query the guard cannot classify can no longer fall through to execute while
  carrying a federation clause. Bounded before by the #16/#17 caps, so contained,
  but the advertised `search_sparql_query` contract is now actually enforced. This
  changes no MCP tool contract (name/description/schema/annotations), so **no router
  drift-baseline recapture** is needed for it.
- **A `#` comment now terminates on CR as well as LF** (`_blank_noncode`, SPARQL 1.1
  §19.4). It previously stopped only on `\n`, so a lone `\r` (`# c\rSELECT*{ SERVICE
  … }`) blanked the whole tail in the guard's view while the endpoint still executed
  it after the CR — the same operation-guard desync, via a carriage return. Re-audited
  the blanker against block-comment, `SER/**/VICE`, literal/IRI-decoy, and preamble-CR
  vectors.

### Changed (breaking)

- **`error_code` is closed to the fleet six-value enum** (Response-Envelope v1):
  `invalid_input`, `not_found`, `ambiguous_query`, `upstream_unavailable`,
  `rate_limited`, `internal`. UniProt's finer codes map onto it —
  `query_syntax_error` and `limit_exceeded` → `invalid_input`, `query_timeout` →
  `upstream_unavailable`, `internal_error` → `internal`. A client branching on the
  old codes must update.
- **`find_proteins` now requires `gene_symbol`.** Its schema previously advertised
  every filter as optional while the runtime refused an anchorless call — a schema
  more permissive than the runtime (the harmful direction). It is now a gene-centric
  search; EC-only, keyword-only, mnemonic-only, and organism-only searches move to
  `search_sparql_query` / `search_example_queries` (the documented escape hatches).
- **`outputSchema` is suppressed on every tool** (Tool-Surface Budget v1). It was
  ~39% of the advertised surface (8,578t → 5,595t), is optional in MCP, and no model
  reads it. `structuredContent` is unaffected — FastMCP still emits it for every dict
  envelope — and this also removed a latent bug where a null `query_text` failed the
  declared output schema and the not-found backstop masked it as "tool not available".

### Fixed

- **Every error envelope now sets MCP `isError: true`** (Response-Envelope v1). A
  returned dict envelope (`success:false`) was wrapped by FastMCP with
  `isError:false`, so a client branching on `isError` saw the failure as a
  successful call. The dispatch middleware now promotes any error envelope, and the
  arg-validation and unknown-tool results set it directly.
- **`get_protein_cross_references` / `resolve_identifiers` at `response_mode=minimal`
  no longer discard the id collection** — the ids ARE the stable identifiers minimal
  must retain — and a capped view now declares `has_more` so a partial page is never
  read as complete.
- **`find_proteins` rejects a malformed `mnemonic` or `keyword`** with a named
  `invalid_input` instead of splicing it into the query to silently match nothing.
- **`find_proteins` rejects a blank/whitespace `gene_symbol`** (named `gene_symbol`)
  instead of splicing an empty `prefLabel` that matched nothing with `success:true`.
- **The not-found backstop no longer masks a KNOWN tool's dispatch fault as
  `not_found`.** A registered tool whose raw dispatch raised now returns `internal`
  (name never reflected); only a genuinely unknown name gets `not_found` — masking a
  real tool as not_found told the model the tool did not exist.
- **`error_code` is clamped to the closed enum at the emit boundary**, so a stray
  value can never reach the wire; discovery/instructions advertise the full six-value
  enum and no longer claim tools publish `outputSchema`.

### Documentation

- Every input property already carried a description; every **required** and
  **array** parameter now also carries `examples`, and the `feature_types` closed
  vocabulary is declared as a schema enum (Tool-Schema Documentation v1). This makes
  the fleet behaviour gate report **0 UNGATED** tools.
- `FastMCP(dereference_schemas=False)` (surface amplifier off).
- Vendored the Behaviour Conformance v1 gate (`tests/conformance/behaviour.py` +
  `test_behaviour_v1.py`, byte-identical from the router) and wired the behaviour
  probe into `conformance.yml`. The gate is CONFORMANT: 0 fail, 0 UNGATED.

## [4.0.3] - 2026-07-14

### Changed

- **The NPM deployment pulls the released image instead of building from source.**
  `docker/docker-compose.npm.yml` carried `build:`, so a deploy rebuilt the image on the
  server even though CI had already published an attested, digest-addressable image to
  GHCR — the released image was never consumed. It now requires `UNIPROT_LINK_IMAGE`
  pinned to a digest and fails closed when it is unset. Nothing else in the overlay
  changed: `container_name` (NPM routes to it), the Compose project name, the healthcheck,
  networks and tmpfs are all preserved, so the deployed topology is untouched.

## [4.0.2] - 2026-07-13

### Fixed

- Re-pin the reusable container CI and container release callers to the corrected
  GeneFoundry container release standard, which fixes latent defects in the shared
  release pipeline (notably GHCR authentication before the version alias is
  pushed). No runtime behaviour change. Research use only.

## [4.0.1] - 2026-07-13

### Added

- Adopt the GeneFoundry container release standard with SHA-pinned reusable
  container CI/release callers, release metadata, digest-only production Compose,
  and complete OCI image labels. Research use only.

## [4.0.0] - 2026-07-12

### Changed (BREAKING)

- `search_sparql_query` now permits only the documented read-only SPARQL query
  forms and output formats. Federated (`SERVICE`) queries and unbounded or
  policy-disallowed query shapes are rejected before execution; redirects are
  followed only through approved UniProt endpoints and stop at the configured
  redirect limit. Clients relying on previously accepted federated SPARQL,
  disallowed query forms, or unsupported result formats must reformulate their
  requests.

### Security

- Bound SPARQL request execution, apply HTTP Policy v1 outbound URL and
  redirect controls, and keep policy failures in the typed error envelope.

## [3.0.2] - 2026-07-11

### Security

- **Guard the FastMCP-core not-found reflection surface (Response-Envelope
  Standard v1.1 §Error-message sanitation fast-follow).** FastMCP core reflects the
  caller's OWN requested tool name / resource URI / prompt name -- and any
  control/zero-width/bidi/NUL code points it carries -- back to the caller and to
  framework logs (at DEBUG as well as WARNING) BEFORE this project's middleware runs.
  A new `uniprot_link/mcp/notfound_guard.py` closes it with fixed, input-free
  constants only (never interpolating the requested name/URI):
  - Layer 1 `on_call_tool` registry preflight: an unknown tool returns a fixed,
    name-free `not_found` envelope (both `structured_content` and the TextContent
    mirror; `_meta.tool` is never the caller-supplied name).
  - Layer 2 `on_read_resource` boundary: any read failure re-raises a fixed URI-free
    `ResourceError` (never `str(exc)`).
  - Layer 3 protocol backstop: wraps the raw CallTool/ReadResource/GetPrompt handlers
    as the outermost layer -- covers the unknown-tool *return* path and the
    unknown-**prompt** echo (`Unknown prompt: '<name>'`).
  - Layer 5 validation-log scrub filter: neutralizes the FastMCP-core / MCP-SDK
    records that echo the caller name/URI on their own (non-propagating) loggers and
    handlers at any level.
  Caller self-reflection surface (lower-risk than upstream injection); no success or
  error-envelope schema changed. Research use only.

## [3.0.1] - 2026-07-11

### Security

- **Defense in depth (error-path text):** caller-visible error messages are
  sanitized of control/zero-width/bidi/NUL code points, the arg-validation field
  name is sanitized, obsolete-entry replacement accessions are validated (invalid
  values omitted so upstream text can't become a recovery argument), and the
  QLever 400 body is no longer echoed. Research use only.

## [3.0.0] - 2026-07-11

### Changed

- **BREAKING: fence every UniProtKB `rdfs:comment` free-text surface as the
  Response-Envelope Standard v1.1 `untrusted_text` object.** Each externally
  sourced comment literal is now emitted as a typed object
  (`kind`/`text`/`provenance`/`raw_sha256`) instead of a bare string, so a
  downstream host can never confuse retrieved curator prose with instructions:
  - `get_protein` `/function`
  - `get_protein_features` `/features/*/description`
  - `get_protein_variants` `/variants/*/description`
  - `get_protein_diseases` `/diseases/*/involvement` **and**
    `/diseases/*/definition` (the disease vocabulary's own clinical comment)
  - `search_example_queries` `/examples/*/description` **and**
    `get_example_query` `/description` (curated SPARQL-example comments)
  - `search_sparql_query` — this power tool returns ARBITRARY upstream text, so
    **every string cell** of a SELECT result (`/rows/*/<var>`) and the raw
    CSV/RDF/XML/turtle **`/data`** blob are now fenced as `untrusted_text`
    objects (`record_id` = executed-query hash + row/binding position).
    Numeric/boolean cells and the ASK `boolean` pass through unchanged.

  The nested-array output schemas (`features[]`/`variants[]`/`diseases[]`/
  `examples[]`) declare the `untrusted_text` object (with the `kind` const) in
  their `items`; `search_sparql_query`'s `rows` items declare each cell as the
  fenced object or a numeric/boolean scalar, and `data` as the fenced object —
  so the typed literal is visible to schema-aware clients, not only at the top
  level. The example `query` text (executable SPARQL, not prose) and controlled
  labels/names (protein names, disease/GO labels) are intentionally left as
  plain strings. A present-but-empty upstream literal (`""`) is fenced too — it
  becomes the typed object with `text: ""` and its digest, never a bare `""`
  that would contradict the schema; only an absent field stays `null`. Consumers
  that read any fenced field as a plain string must update to read `.text` from
  the typed object. Defense in depth; research use only, not clinical decision
  support.

- Exceeding a Response-Envelope v1.1 untrusted-text ceiling now surfaces as an
  explicit typed `error_code: "limit_exceeded"` envelope (recovery
  `reformulate_input`), never a masked generic `internal_error`. The
  object-count ceiling is the tool's real result cap: single-record tools use
  the default 128; the uncapped embedded lists (`features`/`variants`/
  `diseases`) use a generous 10000 so a legitimately large protein never
  errors; `search_example_queries` uses its 126-entry catalog cap;
  `search_sparql_query` pins the count ceiling to the 8 MiB byte-total so a
  large SELECT is bounded by bytes, not an arbitrary count. `get_protein_features`
  enforces limits over the **emitted** feature subset (after secondary-structure
  hiding and the display slice), so a hidden/large annotation that is never
  returned cannot raise `limit_exceeded`. The per-object 2 MiB and 8 MiB-total
  byte limits remain the DoS backstop.

### Fixed

- Emit `_meta.unsafe_for_clinical_use: true` on every tool response (success and
  error, all response_modes) per the fleet-wide Response-Envelope Standard v1
  disclaimer decision (2026-07-03). Purely additive: no envelope restructuring,
  no `_meta` key removed. `get_server_capabilities`'s `provenance_policy` /
  `per_call_meta` are updated to document the new key.

## [2.0.4] - 2026-07-11

### Security

- Re-enabled FastMCP 3.4.4 strict Host/Origin protection with configurable
  allowlists.

## [2.0.3] - 2026-07-07

### Security

- **Close a SPARQL IRIREF-injection vector (finding M1).** `escape_literal`
  guards double-quoted string-literal contexts but not `<...>` IRIREF contexts,
  so user input spliced into an IRI — the cross-reference database name
  (`protein_cross_references`) and the curated-example IRI (`get_example_query`)
  — could carry IRI terminators (`>`, whitespace, `{}` …) and break out of the
  `<...>` to inject graph patterns. Both call sites now validate with IRI-aware
  validators (`validate_database_name`, `validate_example_iri`) before the
  splice: a database key is restricted to its real shape and an example IRI must
  be an http(s) IRI with a non-empty host and no SPARQL metacharacters. The
  IRI validator also wraps `urllib.parse.urlsplit`, which itself raises
  `ValueError` on a malformed host such as `http://[`, so every malformed IRI is
  rejected cleanly as `InvalidInputError` instead of surfacing as an unhandled
  error.

### Fixed

- **Loopback-bind the base `docker-compose.yml` host port.** The base compose
  uses Compose long-syntax `ports` (`target`/`published`/`protocol`), which
  publishes the unauthenticated backend on `0.0.0.0`; the short-form
  `127.0.0.1:` prefix trick does not apply. Add `host_ip: 127.0.0.1` so copying
  this file to a server never exposes the backend on the public IP (Docker
  otherwise binds `0.0.0.0` and bypasses the host firewall). Production is
  unaffected — the prod/npm overlays reset `ports` (expose-only, fronted by a
  reverse proxy). A `yaml.safe_load` guard test asserts every published port is
  loopback-bound.

## [2.0.2] - 2026-07-03

### Fixed

- **Single-source the package version.** `uniprot_link.__version__` now derives
  from installed package metadata (`importlib.metadata.version`) instead of a
  hardcoded literal, so `pyproject.toml [project].version` is the one source of
  truth for `__version__`, `/health`, and MCP `serverInfo`.

### Changed

- **MCP `serverInfo.version` now advertises the package version.** The
  `FastMCP(...)` constructor in `uniprot_link/mcp/facade.py` was missing
  `version=`, so `initialize` responses reported the FastMCP framework version
  instead of the `uniprot-link` release. Clients now see the correct package
  version in `serverInfo.version` (matching `/health`).

## [2.0.1] - 2026-06-29

### Security

- Adopt GeneFoundry Container & Deployment Hardening Standard v1: digest-pinned base
  image, new `.dockerignore`, hardened `prod` compose overlay (read-only rootfs,
  `cap_drop: ALL`, `no-new-privileges`, `init`, resource limits, expose-only), CORS no
  longer combines wildcard origins with credentials, and a CI container scan (Trivy) +
  SBOM workflow.

## [2.0.0] - 2026-06-15

Adopts the **GeneFoundry Logging & CLI Standard v1**
([#2](https://github.com/berntpopp/uniprot-link/issues/2)). This is a front-end
(CLI) change: the **MCP tool surface, services, and `/health`/`/mcp` endpoints are
unchanged**, so the `genefoundry-router` gateway is unaffected. Pre-alpha — shipped
as a breaking change with no shims/aliases.

### Changed (BREAKING)

- **CLI migrated from `argparse` to `typer`** (`uniprot_link/cli.py`): a single
  `typer.Typer(no_args_is_help=True)` app with `rich` output and explicit
  commands `serve` / `config` / `health` / `version`. There is **no bare-serve** —
  the server now boots via `uniprot-link serve …`.
- **Single console script** `uniprot-link = "uniprot_link.cli:app"`. The previous
  `uniprot-link = "server:main"` and `uniprot-link-mcp = "mcp_server:main"` entry
  points are removed, along with the root `server.py` and `mcp_server.py`.
- **stdio transport removed** (Streamable HTTP only): dropped from the
  `transport` config Literal, `UnifiedServerManager.start_stdio_server`, the
  Docker image, and the docs. `/mcp` and `/health` are unchanged.

### Confirmed

- `uniprot_link/logging_config.py` confirmed on the fleet **structlog** canon
  (byte-identical to the `mgi-link` reference): `filter_by_level →
  add_logger_name → add_log_level → TimeStamper(iso) → StackInfoRenderer →
  static fields`; JSON in prod / `ConsoleRenderer` in dev via `LOG_FORMAT`.

### Migration

- Replace `python server.py --transport unified …` (or the `uniprot-link` /
  `uniprot-link-mcp` scripts) with **`uniprot-link serve --transport unified …`**.
- The `stdio` transport is gone; connect MCP clients over Streamable HTTP at
  `/mcp` (e.g. `claude mcp add --transport http uniprot-link <url>/mcp`).

## [1.0.0] - 2026-06-15

Adopts the **GeneFoundry Tool-Naming & Normalization Standard v1**
([#1](https://github.com/berntpopp/uniprot-link/issues/1)) ahead of federation
behind the [`genefoundry-router`](https://github.com/berntpopp/genefoundry-router)
MCP gateway. The canonical gateway **namespace token for this server is `uniprot`**
(tools surface as `uniprot_<tool>` once mounted). Leaf tool names stay unprefixed.

### Changed (BREAKING)

- **Tool renames** (no deprecation aliases — drop immediately, per the standard):
  - `run_sparql_query` → **`search_sparql_query`** (`run` is not a canonical verb;
    the tool executes a query and returns rows, so `search` is the closest fit).
  - `map_identifiers` → **`resolve_identifiers`** (`map` is not a canonical verb;
    the tool resolves an accession to its external identifiers).
- **Argument canonicalization** to the fleet canon (`gene_symbol`):
  - `find_proteins(gene=…)` → **`find_proteins(gene_symbol=…)`**.
  - `find_proteins_batch(genes=…)` → **`find_proteins_batch(gene_symbols=…)`**.
  - The legacy `gene` / `genes` (and `gene_name` / `symbol`) names are still
    accepted as **inbound aliases** and transparently normalized + disclosed via
    `_meta.argument_aliases_applied`.

### Migration

- Replace `run_sparql_query` → `search_sparql_query` and `map_identifiers` →
  `resolve_identifiers` at all call sites.
- Prefer `gene_symbol` / `gene_symbols` over `gene` / `genes` (the old names keep
  working as aliases, but the canonical names are reported in signatures and
  capabilities).

### Added

- CI guard `tests/unit/test_tool_names.py` asserting every registered tool name
  matches `^[a-z0-9_]{1,50}$`, starts with a canonical verb
  (`get`/`search`/`list`/`resolve`/`find`/`compare`/`compute`), and does not
  self-prefix the `uniprot` namespace token.
- README documents `serverInfo.name` and the `uniprot` namespace token.

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
