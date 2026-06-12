# uniprot-link MCP Assessment — v0.4.0

An LLM-consumer evaluation of the uniprot-link MCP server, conducted by driving
the live tool surface and rating the experience. Two assessments are recorded:

1. **Consumer Experience Assessment** — a dimension-based rating of what it is
   like to consume this MCP as the calling model (discoverability, token
   efficiency, speed, observability, etc.).
2. **Comprehensive Tool-by-Tool Test** — a senior-tester pass exercising all 14
   tools with happy paths, every `response_mode`, filters, pagination, caching,
   and deliberate failure probes.

> This is the v0.4.0 follow-up to `docs/mcp-assessment.md` (v0.3.0). The v0.4.0
> uplift closed all 12 bugs catalogued in that earlier re-assessment; this pass
> re-evaluates the current deployed build.

## Test Context

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Server | `uniprot-link` |
| Server version | 0.4.0 |
| Build | git_sha `5da02e8`, built_at `2026-06-12T10:59:17Z` |
| UniProt release | 2026_01 |
| Endpoint | https://sparql.uniprot.org/sparql (QLever) |
| Evaluator | Claude (Fable 5), LLM consumer of the MCP |
| Method | 27 live tool calls; happy paths, all four `response_mode`s, every `find_proteins` anchor, both `get_taxon` modes, the full `run_sparql_query` matrix, and 7 deliberate error cases |
| Primary fixture | accession Q96T60 (PNKP_HUMAN), taxon 9606 |
| Scope note | Single session, single endpoint state. Findings reflect observed behavior at the build above. |

---

## Part 1 — Consumer Experience Assessment

How effective and economical the server is to use as the calling model, scored
1–10 per dimension with the evidence each score rests on.

### Overall: 8.5 / 10

This is a well-built MCP. It clearly anticipates an LLM consumer rather than a
human reading docs: structured errors, next-step chaining, per-call provenance,
and a genuinely rich discovery surface. The weak spots are minor and mostly
about trimming repeated overhead and smoothing one data-model gotcha.

### Scores

| Dimension | Score | Basis |
|-----------|:-----:|-------|
| Discoverability | 9 | `get_server_capabilities` returns the full tool list, all 21 named graphs with triple counts, prefixes, the feature-type and xref vocabularies, error taxonomy, limits, and four `recommended_workflows`. Tool descriptions carry inline examples and vocab hints. 126 curated example queries to learn the data model. |
| Observability | 10 | Every response carries `request_id`, `elapsed_ms`, `cached`, `uniprot_release`, and `tool`. `capabilities` exposes `server_version`, `git_sha`, and `built_at` — exactly what's needed to detect deploy drift. |
| Error handling | 9 | Malformed accession returned `invalid_input` with a precise message, `retryable:false`, `recovery_action:"reformulate_input"`, `field:"accession"`, and the not-found contract is documented up front. |
| Agentic chaining | 9 | `_meta.next_commands` appears on **every** response including errors — ready-to-call `{tool, arguments}` steps. The standout feature; never had to guess the next call. |
| Structured output | 9 | Typed tools declare output schemas; payloads are clean, flat, and predictable. |
| Token efficiency | 7 | `response_mode` (minimal/compact/standard/full) meaningfully trims payloads; compact default with a first/last-30-residue sequence preview is smart. Dinged for repeated `_meta` boilerplate. |
| Speed / latency | 7 | Caching is excellent — a repeated `find_proteins` returned `cached:true` in 0 ms. But cold SPARQL is slow: `find_proteins` cold was 5.35 s; feature calls ~1.9 s. Warm `get_protein` was 140–630 ms. |

### Improvements (consumer view)

1. **Trim the per-call `_meta` boilerplate.** Every response repeats
   `unsafe_for_clinical_use`, the full `citation` DOI, and `uniprot_release`
   verbatim — ~30–40 tokens of identical text per call. These are already in
   `get_server_capabilities`. Keep `request_id` / `elapsed_ms` / `cached` /
   `next_commands` per call; demote the static notice/citation to discovery-only.
2. **Nudge `domain` → `region`.** `get_protein_features(feature_types=['domain'])`
   for PNKP returns only the FHA domain (6–110). The catalytic phosphatase
   (146–337) and kinase (341–516) regions — the protein's defining "bifunctional"
   domains — are typed `region`, not `domain`. Extend the existing low-result
   `filter_hint` to point at `region`.
3. **Smarter error-recovery suggestions.** A malformed accession produced a
   `next_commands` entry of `find_proteins(gene="<bad accession>")`, which is
   unlikely to help. Suggest `get_server_capabilities` or the format help instead.
4. **Set latency expectations / pre-warm.** The 5+ s cold `find_proteins` is the
   roughest edge. Pre-warm common anchor queries, or surface a typical-latency
   note in `capabilities` so a calling agent can budget timeouts.

---

## Part 2 — Comprehensive Tool-by-Tool Test

**Scope:** all 14 tools, 27 live calls. Happy paths, every `response_mode`, all
four `find_proteins` anchors, both `get_taxon` modes, the full `run_sparql_query`
matrix (bounded/unbounded/ASK/CONSTRUCT/write/syntax), and 7 deliberate error
cases.

### Headline

Every tool works and every datum spot-checked is correct (PNKP variants
L176F/E326K→MCSZ, G375W→AOA4; sequence 521 aa / 57076 Da; 80 xref databases;
21 GO terms with ECO evidence). Error handling and observability are
best-in-class. The only real weaknesses are **cold latency on the search/scan
tools** and a handful of **minor data-representation nits**. Nothing is broken.

### Per-tool results

| # | Tool | Cases run | Rating | Verdict |
|---|------|-----------|:------:|---------|
| 1 | get_server_capabilities | full surface | 10 | Exhaustive: tools, 21 graphs w/ triple counts, vocabularies, error taxonomy, limits, build SHA. |
| 2 | run_sparql_query | SELECT bounded/unbounded, ASK, CONSTRUCT→turtle, write, syntax err | 9 | LIMIT auto-injection + `truncated` block + `limit_injected` flag all correct; write-rejection clean; empty-body-400 hint is helpful. |
| 3 | search_example_queries | text filter | 9 | Tag-based, compact, chains to `get_example_query`. |
| 4 | get_example_query | valid + bad id | 9 | Returns full query text + ready-to-run `next_command`; clean `not_found`. |
| 5 | find_proteins | gene+taxon, no-anchor, keyword+taxon, EC, cache | 7 | All anchors work, good errors, caching. Cold latency 5–10 s and opaque within-reviewed ordering drag it down. |
| 6 | get_protein | minimal, full, invalid | 9 | Response modes differentiate cleanly; tidy payload. |
| 7 | get_protein_sequence | compact preview, standard full | 8 | First/last-30 preview compaction is smart; non-canonical isoform `mass_da` is null. |
| 8 | get_protein_features | domain, region, unknown-type | 8 | Error returns `allowed_values` + `hint` (excellent). Loses a point for the domain/region trap. |
| 9 | get_protein_variants | disease_associated_only | 9 | HGVS `notation`, dbSNP rsIDs, linked diseases. Empty-string substitution nit. |
| 10 | get_protein_diseases | full | 9 | `definition` vs `involvement` split is exactly right for grounding. |
| 11 | get_protein_cross_references | full (80 dbs) | 9 | Grouped, complete, well-structured. |
| 12 | get_protein_go_terms | full | 10 | Aspect-grouped with ECO + evidence codes (IDA/IEA/…) per term — ideal for citation. |
| 13 | map_identifiers | db filter | 9 | Focused subset of xrefs; filter works; echoes requested vs mapped. |
| 14 | get_taxon | id+lineage, name, not_found | 7 | id path is great (full lineage!), but name lookup took 11 s. |

**Overall: 8.7 / 10.**

### Bugs & inconsistencies found (ranked by value)

1. **`get_taxon` by-name is ~40× slower than by-id (11.0 s vs 0.29 s).** Name
   resolution scans; the id path is instant. An agent that resolves
   "Homo sapiens" before `find_proteins` eats an 11 s tax on the first step.
   *Fix: cache common name→id, or index the scientific/common-name columns.*
2. **`find_proteins` cold latency is 5–10 s** (keyword+taxon 9.9 s, EC 5.0 s,
   gene 5.3 s cold → 0 ms cached). Nothing in `capabilities` advertises this, so
   callers can't set timeouts intelligently. *Fix: publish a per-tool latency
   hint, and/or pre-warm the common gene+taxon+reviewed pattern.*
3. **The `domain` vs `region` trap** (reconfirmed). `get_protein_features(['domain'])`
   returns only FHA; the catalytic phosphatase/kinase domains are typed `region`.
   A "domains" question silently loses two-thirds of the architecture.
   *Fix: when `['domain']` yields few hits, append a `note` pointing at `region`.*
4. **Opaque ordering within reviewed results.** `find_proteins(ec_number=2.7.1.78,
   limit=3)` returned bovine/zebrafish orthologs and not human Q96T60, with no
   obvious sort key (not accession order). Reviewed-first is documented; the
   secondary sort isn't. *Fix: document the tiebreak (or sort by accession) so
   paginated results are deterministic.*
5. **Empty-string instead of null for inapplicable fields.** The PNKP T408
   variant (`variant_type:"other"`) returns `"substitution":""` and omits
   `notation`. Empty string reads as "substitutes to nothing." *Fix: use `null`
   for `substitution` when not a simple substitution; consider a descriptive
   `notation` like `T408del`.*
6. **Non-canonical isoform `mass_da` is null** (Q96T60-2 has length 482 but no
   mass). *Fix: compute mass from the isoform sequence, or document that UniProt
   doesn't supply it.*
7. **Repeated `_meta` boilerplate** (`unsafe_for_clinical_use` + full citation
   DOI + release on every one of the 27 responses). ~30–40 tokens/call of
   identical text. *Fix: demote the static notice/citation to discovery-only.*

### What's genuinely excellent (keep)

- **Error envelope is exemplary.** Across `invalid_input`, `not_found`, and
  `query_syntax_error` every response carried `error_code`, a human-readable
  `message`, `retryable`, `recovery_action`, the offending `field`, and — for
  enum fields — `allowed_values` + a `hint`. This is what lets an LLM
  self-correct without a round-trip to docs.
- **Observability is complete.** `request_id`, `elapsed_ms`, `cached`,
  `limit_injected`, and `truncated{reason,recovery}` on every relevant call;
  build `git_sha` / `built_at` in capabilities.
- **`next_commands` chaining on success *and* error** — never had to guess the
  next step.
- **SPARQL escape hatch is safe and well-instrumented:** LIMIT injection with an
  explicit truncation contract, write-rejection, multi-format CONSTRUCT/DESCRIBE.

### Top 3 improvements, in priority order

1. **Kill the cold-latency surprise on `get_taxon`-by-name and `find_proteins`** —
   cache/index name lookups and pre-warm common anchors; publish expected latency
   in `capabilities` so agents budget timeouts.
2. **Add the `domain` → `region` nudge** in `get_protein_features` — the single
   highest-value correctness fix for question-answering.
3. **Tidy the data-representation nits** — `null` over `""` for inapplicable
   variant fields, isoform mass, and documented deterministic ordering for
   paginated `find_proteins`.

---

## Verdict

**8.5–8.7 / 10.** These are refinements, not repairs. The architecture is ahead
of most MCPs — the error/observability/chaining design in particular is
reference-quality. The remaining work is latency on the scan/search tools and a
few minor payload-representation cleanups.
