# uniprot-link MCP Assessment — v0.7.0 (tester session)

Two evaluations of the **deployed and now-current** uniprot-link MCP server,
captured in one document:

- **Part 1 — LLM consumer-experience scorecard.** A naturalistic UX rating across
  discoverability, token efficiency, speed, observability, error handling, and
  grounding, driven from a real domain task (*"get domains for PNKP and NAA10"*).
- **Part 2 — Systematic senior-tester pass.** A deliberate tool-by-tool sweep of
  all 14 tools exercising every verbosity mode, documented filter, alias, SPARQL
  form, result format, and the reachable error taxonomy — to surface defects the
  UX pass does not reach.

> Unlike the v0.5.0 sessions, the deployed server here **matches disk HEAD**
> (v0.7.0 / `0e7ff51`) — the multi-version deploy drift recorded in earlier
> assessments is resolved as of this session. Both parts below evaluate that same
> live build.

## Test Context

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Server | `uniprot-link` |
| Server version (deployed) | 0.7.0 |
| Build | git_sha `0e7ff51`, built_at `2026-06-12T14:09:03Z` |
| Repo HEAD (disk) | v0.7.0 (`0e7ff51`) — **deployed == disk (no drift)** |
| UniProt release | 2026_01 |
| Endpoint | https://sparql.uniprot.org/sparql (QLever) |
| Evaluator | Claude (Fable 5), LLM consumer of the MCP |
| Method | Part 1: real task (PNKP + NAA10 → domains) + targeted probes. Part 2: ~40 live calls across all 14 tools, all enum args, all filters, full error taxonomy. |
| Primary fixtures | Q96T60 (PNKP), P41227 (NAA10), P05067 (APP), 9606 / 10090 / 31033 (taxa), Q00000 / 99999999 (not-found probes) |
| Scope note | Single live session against the deployed build. Part 1 scores reflect UX; Part 2 revises error-handling down after deeper coverage (see F1). |

---

## Part 1 — LLM Consumer Experience Assessment

Scored 1-10 per dimension, with the evidence each score rests on.

### Overall: 8 / 10

A server I would trust and recommend. Its discoverability, error design, and
observability are top-decile among MCPs I have tested — the embedded
`argument_aliases`, `recommended_workflows`, `next_commands` chaining, and build
provenance are genuinely best-in-class. Held back by two things: cold gene-search
latency (the cost a user actually feels) and one noisy default
(`get_protein_features` dumps secondary-structure features). Note that the
systematic pass in Part 2 later found an error-handling gap (enum-value errors)
that this UX pass did not hit, which revises the 9.5 below down toward 8 — see F1.

### Scores

| Dimension | Score | Basis |
|-----------|:----:|-------|
| Discoverability | 9 | Rich embedded server instructions; `get_server_capabilities` returns tool list, signatures, response modes, error codes, limits, `recommended_workflows`, and `argument_aliases` (taxon/organism/species → `organism_taxon`); 126 example queries; `next_commands` on every response. |
| Error handling / recovery | 9.5 → 8 | Bad arg name → `error_code:invalid_input` + offending `field` + full `allowed_values` + `hint` + recovery hop in one turn; `not_found` → "resolve via find_proteins first." **Revised down in Part 2**: invalid enum *values* fall through to a generic handler that lists argument *names* instead of valid values (F1). |
| Observability | 9.5 | Every response carries `request_id`, `elapsed_ms`, `cached`; capabilities exposes `server_version` + `build{git_sha, built_at}` + `uniprot_release`. Sufficient to verify deploy state (this is how the deploy-drift note was retired). |
| Output quality / grounding | 9 | Typed structured output; `recommended_citation`; release tag for freshness; `function` with inline PubMed refs; ECO + GO evidence codes; research-use-only notice. |
| Token efficiency | 7.5 | `response_mode` ladder (minimal/compact/standard/full); sequence preview default; counts-only minimal xref. Deduction: `get_protein_features` returns secondary-structure noise by default (~18 of 35 features were `beta_strand`/`turn`/`helix` for the domains task); `requested_accession` echoed even when identical. |
| Speed / latency | 5.5 | Honest `latency_note` + real 1h cache (`cached` flag). Observed: accession `get_protein` ~0.7 s, features ~2.3 s — but gene-anchored `find_proteins` ~5.6 s cold, mnemonic ~8.3 s, live taxon-name scan ~11 s. The natural gene→accession entry point is the slow path. |

### The three highest-leverage UX improvements

1. **Cut or hide gene-search latency.** Cold `find_proteins` (5-13 s) dominates
   the felt cost. Pre-warm/cache common gene symbols the way `COMMON_TAXA` already
   short-circuits organism names, and/or add a batch form so N genes do not cost
   N x 5 s of sequential round-trips. (Your domain task for PNKP + NAA10 spent
   ~11 s purely in two sequential gene lookups.)
2. **Add `response_mode` (or a domains-only default) to `get_protein_features`.**
   Excluding `beta_strand`/`turn`/`helix` unless requested would roughly halve the
   token cost of the most common feature query. The `feature_types=` filter exists
   and works, but correctness currently depends on the caller knowing to reach for
   it.
3. **Drop redundant echoes.** Omit `requested_accession` when it equals
   `accession` — a free token win on the most-called tools.

---

## Part 2 — Systematic Tool-by-Tool Test

All 14 tools exercised. Error codes forced: `invalid_input` (bad arg name, bad
enum value, no-anchor, write-query), `not_found` (bad accession, bad taxon),
`query_syntax_error`. **Not forceable safely this session**: `query_timeout`,
`rate_limited`, `upstream_unavailable`. Note: an attempt to induce a timeout
(`rdfs:subClassOf*` over `up:Enzyme`, `timeout_seconds=3`) returned in 1.1 s
because auto-LIMIT injection neutralized it — so the `timeout_seconds` parameter's
effect remains **unverified**.

### Findings (ordered by leverage, highest first)

#### F1 — Invalid enum *value* returns argument *names*, not valid values (High)

The single biggest defect, and systemic. For three enum-valued arguments, passing
an invalid value falls through to a generic handler:

| Call | Returned `allowed_values` | Should be |
|------|---------------------------|-----------|
| `get_protein_go_terms(aspect="function")` | `["accession","aspect","limit"]` (arg names) | `["molecular_function","biological_process","cellular_component"]` |
| `get_server_capabilities(detail="banana")` | `["detail"]` (arg name) | `["summary","full"]` |
| `run_sparql_query(result_format="banana")` | `["query","result_format","limit","timeout_seconds"]` (arg names) | the valid format set (e.g. `json`, `csv`, ...) |

The message even reads *"Valid argument **names** are listed in allowed_values"* —
wrong category for a value error. Worse, the valid values appear **nowhere**: not
in the error, not in the `tool_signatures` (`aspect=`, `detail=` show no enum),
not elsewhere in capabilities. I had to brute-force the GO aspect vocabulary
(`molecular_function` works; `function` and `C` are rejected).

Contrast `get_protein_features(feature_types=["notatype"])`, which **does it
right**: it rejects with the full 32-value `allowed_values` list. The fix is to
route `aspect`, `detail`, `result_format` (and any other `Literal`/enum arg)
through that same handler, and to surface these value sets in
`get_server_capabilities` so they are discoverable before a failed call.

#### F2 — `get_protein_cross_references` silently returns empty for an unknown database (High)

`databases=["NOTADB"]` → `success:true, database_count:0, counts:{}` with no
`unmatched_databases` field. A typo'd database name reads as *"this protein has no
such cross-reference."* This is the most dangerous failure mode tested, because it
looks like a valid "no data" answer. Two inconsistencies compound it:

- `get_protein_features` **rejects** an unknown `feature_types` value (F1's good
  path), but xref **silently accepts** an unknown `databases` value.
- `map_identifiers` echoes `requested_databases` / `mapped_databases` so a caller
  can diff for unmatched names; `get_protein_cross_references` echoes neither.

Fix: validate `databases` against the known set (like `feature_types`), or at
minimum echo `requested_databases` + `unmatched_databases`.

#### F3 — `get_taxon` name scan: exact match not ranked first; chaining points to the wrong taxon (High)

`get_taxon("Takifugu rubripes")` (`match_source:endpoint_scan`, ~11 s) returned 10
matches including hybrids and viruses, with the exact hit (31033) buried at
position 5. `next_commands[0]` then suggested `2506766` (*Takifugu chinensis x
Takifugu rubripes*, a hybrid) — not the exact species. An agent following the
chain lands on the wrong organism. Fix: sort exact `scientific_name` equality
first, and point `next_commands` at the best match rather than `matches[0]`.

#### F4 — `get_protein_features` reports `truncated.total` = page size, not true total (Medium)

`get_protein_features(limit=3)` → `truncated:{"reason":"limit 3 reached",
"total":3}` when 35 features exist. The `total` should be 35. `get_protein_go_terms`
does it correctly (`truncated:{"returned":3,"total":38}`), proving the right value
is computable.

#### F5 — Truncation envelope shape is inconsistent across tools (Medium)

Observed shapes:

| Tool | Truncation keys |
|------|-----------------|
| `get_protein_features` | `{reason, total}` (total wrong — F4) |
| `get_protein_go_terms` | `{returned, total, recovery}` |
| `get_protein_variants` | `{reason, recovery}` (no total) |
| `find_proteins` | `{reason, recovery}` (no total) |
| `run_sparql_query` | `{reason, recovery}` (no total) |

Standardize to `{returned, total, reason, recovery}` with `total` = true available
count wherever computable, so a caller can always tell how many more exist without
paging blindly.

#### F6 — `find_proteins(name_contains=)` is a literal substring match (Medium)

`organism_taxon=9606, name_contains="polynucleotide kinase"` → **0 results**,
because PNKP's real name is "Bifunctional polynucleotide **phosphatase/**kinase" —
the substring is absent. Technically correct, but surprising and undocumented.
Document the semantics (literal, case-sensitive substring) in the tool
description, or switch to per-word/token `CONTAINS` matching.

#### F7 — `requested_accession` echoed even when identical (Low)

Every typed call echoes `requested_accession` even when it equals `accession`. It
is only meaningful on isoform/redirect (e.g. `Q96T60-1` → `Q96T60`). Omit when
equal — pure token tax otherwise.

#### F8 — `run_sparql_query` success omits `next_commands` (Low)

Every other tool's `_meta` carries `next_commands` on success; `run_sparql_query`
success returns only `{tool, request_id}`. Minor inconsistency (arguably
acceptable for a power tool, but the chaining contract is otherwise universal).

### What works well (verified)

- **`feature_types` enum error is exemplary** — full 32-value `allowed_values`
  list. This is the exact pattern F1 should copy.
- **Argument-alias transparency**: `gene="PNKP", taxon=9606` worked and disclosed
  `_meta.argument_aliases_applied: [["taxon","organism_taxon"]]`.
- **Context-aware recovery hints**: variants truncation suggests
  `disease_associated_only=true`; features truncation suggests `feature_types`.
- **Safety rails**: write queries rejected (`read-only`); auto-LIMIT injected on
  unbounded SELECT (`limit_injected:true`) — it even defused the attempted
  expensive closure query. SELECT / ASK / CSV all return correctly.
- **Response-mode ladder is coherent**: minimal (flags) → compact (+`function`) →
  standard (+`created`/`modified`) → full (raw IRIs). Sequence preview default is
  smart; isoform handling (`Q96T60-1` → `isoform_note` redirect) is clean.
- **Curated taxon index** is instant and correct (`Mus musculus` → 10090,
  `match_source:curated_common_index`, 0 ms); only the live fallback is slow (F3).
- **Caching** demonstrably works (`cached:true`, 0 ms on repeat).
- **Observability** best-in-class: `request_id`, `elapsed_ms`, `cached` on every
  call; build/version provenance in capabilities.

### Consolidated recommendations (prioritized)

1. **(F1) Fix the enum-value error path** for `aspect`, `detail`, `result_format`
   (route through the `feature_types` handler; list valid *values*; change the
   "argument names" wording) **and** add these value sets to `tool_signatures` in
   `get_server_capabilities`. Highest leverage: turns brute-force guessing into
   one-shot self-correction.
2. **(F2) Validate or echo `databases`** in `get_protein_cross_references` — the
   silent-empty path is a correctness trap.
3. **(F3) Rank exact matches first in `get_taxon`** and fix `next_commands` to
   point at the best match.
4. **(F4/F5) Standardize the truncation envelope** to
   `{returned, total, reason, recovery}` and fix the features `total`.
5. **(F6) Document `name_contains` semantics** (or tokenize the match).
6. **(Part 1) Cut cold gene-search latency** (cache common gene symbols / batch
   form) and **add a leaner `get_protein_features` default**; **(F7) drop the
   redundant `requested_accession` echo**.

### Net assessment

The contract design — errors, aliases, chaining, observability, safety — is
genuinely strong and remains top-decile among MCPs tested. Every tool returned
accurate UniProt data; no core-correctness defect was found. The issues cluster in
**enum-value discoverability** (F1) and **silent/misleading edges** (F2, F3, F4)
rather than data correctness. Fixing F1-F3 would move LLM usability from good to
excellent, because all three currently cause an agent to either guess blindly or
silently accept a wrong-looking empty result.
