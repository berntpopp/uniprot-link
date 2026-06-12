# uniprot-link MCP — v0.8.0 Closure Record (LLM-Consumer Uplift)

Closes every finding of the v0.7.0 **tester** assessment
([`mcp-assessment-v0.7.0-tester.md`](mcp-assessment-v0.7.0-tester.md), overall
**8/10**, with error-handling revised 9.5 → 8 after the systematic pass). The
findings clustered in three areas — enum-value discoverability (F1),
silent/misleading edges (F2–F4), envelope consistency (F5) — plus felt latency
and token noise (Part 1). No core-correctness defect was found in v0.7.0; this
release removes the edges around correct data.

| Field | Value |
|-------|-------|
| Version | 0.7.0 → **0.8.0** |
| Spec | [`docs/superpowers/specs/2026-06-12-mcp-v0.8.0-uplift-design.md`](superpowers/specs/2026-06-12-mcp-v0.8.0-uplift-design.md) |
| Tools | 14 → **15** (`find_proteins_batch`) |
| CI | `make ci-local` green (format, lint, line-budget ≤600, mypy strict, 202 unit tests) |
| Live check | F6 PNKP resolves via `name_contains="polynucleotide kinase"`; variants count, batch legs, feature cap re-validated against the live endpoint |
| Research basis | MCP spec 2025-06-18; Anthropic *Writing effective tools for agents* + *Code execution with MCP*; FastMCP docs; Datadog production lessons |

---

## Findings → fixes

### F1 — Invalid enum *value* returned argument *names* (High)

**Root cause.** `ArgValidationMiddleware` caught every pydantic binding error —
including `Literal`/enum value failures (`aspect="function"`) — and routed them
through `build_arg_error_envelope`, which always put the **argument names** in
`allowed_values` and printed "Valid argument **names** are listed in
allowed_values." Wrong category; the valid values appeared nowhere.

**Fix.** The middleware now classifies the binding error into *missing* /
*unknown-name* / *bad-value*. A value error on a known param surfaces the field's
valid **values** (new `arg_help.enum_values_for`, handling a direct `enum` and the
`anyOf` branch FastMCP emits for `Literal[...] | None`) with "Valid values are
listed in allowed_values"; a numeric-constraint value error folds the pydantic
reason in and omits any fabricated list. `get_server_capabilities` gains
`argument_value_sets` so the value sets are discoverable *before* a failed call.
Matches the research's #1 takeaway: an invalid enum must return the field's valid
values in a result the LLM can read (this server's structured envelope is the
`isError:true` equivalent).

### F2 — `get_protein_cross_references` silently returned empty for an unknown DB (High)

**Fix.** With an explicit `databases` filter, the tool echoes
`requested_databases` and flags any name that matched nothing under
`unmatched_databases` + `database_hint` (case-insensitive did-you-mean). Hard
rejection was rejected as a design: UniProt has ~180 xref databases and only ~20
are curated, so validating against the curated list would false-reject legitimate
ones — the echo mirrors the praised `map_identifiers` contract while staying safe
for the open vocabulary. `map_identifiers` inherits the typo-catch for explicit
filters and suppresses the noise for its default primary-id set.

### F3 — `get_taxon` name scan didn't rank exact first (High)

**Fix.** `shaping_taxonomy.rank_taxon_matches` ranks an exact scientific/common-name
hit first (then prefix, then substring; non-hybrid and shorter names win ties),
per the QLever "sort small sets in Python" discipline. The top exact hit is tagged
`match_quality:"exact"`, so `matches[0]` and the `next_commands` chain land on the
right organism (e.g. *Takifugu rubripes* / 31033, no longer a hybrid).

### F4/F5 — Truncation envelope: wrong total, inconsistent shape (Medium)

**Fix.** One standard shape `{returned, total, reason, recovery}` everywhere.
`get_protein_features` fetches up to a 1000 cap and slices in Python so `total` is
the true count, not the page size (F4). `get_protein_go_terms` gains `reason`.
`get_protein_variants` and `find_proteins` compute an exact `total` via a cheap
COUNT query run **only on a full page** (no cost on the common path).
`run_sparql_query` adds `returned`; `total` is omitted by design (an arbitrary
query's count is not computable without re-running it), and that is documented in
the `truncation_contract`.

### F6 — `name_contains` was a literal substring (Medium)

**Fix.** Multi-word `name_contains` is matched per word (AND of `CONTAINS`), so
"polynucleotide kinase" matches "Bifunctional polynucleotide phosphatase/kinase".
Single-word input is unchanged; capped at 6 tokens; the `organism_taxon` pairing
keeps the query bound. **Re-validated live**: the reviewed segment returns Q96T60
(PNKP).

### F7 — `requested_accession` echoed when identical (Low)

**Fix.** Echoed only when it differs from the resolved base accession
(isoform/redirect); the identical echo (a pure token tax) is dropped.

### F8 — `run_sparql_query` success omitted `next_commands` (Low)

**Fix.** Success now carries `_meta.next_commands` (offer `get_protein` when a
SELECT row exposes an accession, else `search_example_queries`) — the chaining
contract is now universal.

### Part 1 — Felt latency + token noise

- **Cold multi-gene latency → `find_proteins_batch`.** Resolves N gene symbols
  **concurrently**; the canonical "domains for PNKP and NAA10" task drops from ~11 s
  (two sequential lookups) to ~5 s (verified: PNKP 5.0 s, NAA10 4.8 s cold, run in
  parallel). Grounding-safe (live queries, no static gene map). `unresolved_genes`
  removes another false-empty edge. The single `find_proteins` path is untouched.
- **Leaner `get_protein_features` default.** Secondary structure (helix/strand/turn)
  is hidden by default and disclosed under `excluded_secondary_structure` —
  roughly halving the most common feature query's token cost.

---

## What was deliberately *not* done

- **No static gene→accession cache** for latency: it would drift from the UniProt
  release and risk mis-grounding. Concurrency is the grounding-safe lever.
- **No hard rejection of unknown xref databases**: the open ~180-DB vocabulary
  makes a curated allow-list a false-reject hazard; echo + did-you-mean is safer.
- **`next_commands` is framed as a community convention**, not an MCP requirement
  (the research found no spec mandate; Anthropic leans toward *consolidating*
  multi-step work, which `find_proteins_batch` also does).

## Verification

`make ci-local` green (ruff format + lint, ≤600-line modules, mypy strict, 202
unit tests). Builder changes re-validated against the live endpoint
(`research/verify_queries.py`, extended with the variants-count and per-word
`name_contains` cases): F6 returns PNKP, `protein_variants_count(P38398)=170`
(119 disease-linked), and both batch legs resolve.
