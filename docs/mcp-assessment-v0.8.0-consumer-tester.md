# uniprot-link MCP Assessment — v0.8.0 (consumer + tester session)

Two evaluations of the **deployed and now-current** uniprot-link MCP server,
captured in one document:

- **Part 1 — LLM consumer-experience scorecard.** A naturalistic UX rating across
  discoverability, token efficiency, speed, observability, and error handling,
  driven from a real domain task (*"get domains for PNKP and NAA10"*).
- **Part 2 — Systematic senior-tester pass.** A deliberate tool-by-tool sweep of
  all 15 tools exercising verbosity modes, documented filters, aliases, SPARQL
  forms, result formats, isoform accessions, and the reachable error taxonomy —
  to surface defects the UX pass does not reach.

> The deployed server here **matches disk HEAD** (v0.8.0 / `10159dc`) — the
> multi-version deploy drift recorded in earlier assessments is resolved as of
> this session. Both parts below evaluate that same live build.

## Test Context

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Server | `uniprot-link` |
| Server version (deployed) | 0.8.0 |
| Build | git_sha `10159dc`, built_at `2026-06-12T18:57:25Z` |
| Repo HEAD (disk) | v0.8.0 (`10159dc`) — **deployed == disk (no drift)** |
| UniProt release | 2026_01 |
| Endpoint | https://sparql.uniprot.org/sparql (QLever) |
| Evaluator | Claude (Fable 5), LLM consumer of the MCP |
| Method | Part 1: real task (PNKP + NAA10 -> domains) + targeted probes. Part 2: ~30 live calls across all 15 tools, verbosity modes, filters, aliases, SPARQL forms, result formats, isoform accessions, full reachable error taxonomy. |
| Primary fixtures | Q96T60 (PNKP), P41227 (NAA10), P05067 (APP), P38398 (BRCA1), 9606 / 10090 (taxa), P05067-2 / P05067-3 (isoforms), ZZZ999 / BRCA1-as-accession / 999999999 / NOTADB (error probes) |
| Scope note | Single live session against the deployed build. Part 2 revises the overall score down after a correctness defect in isoform handling (F1/F2). |

---

## Part 1 — LLM Consumer Experience Assessment

Scored 1-10 per dimension, with the evidence each score rests on. Driven from a
real task: resolve PNKP + NAA10 to human accessions and report their domain
architecture.

| Dimension | Rating | One-line basis |
|-----------|:---:|----------------|
| Discoverability | 9/10 | Rich capabilities dump + `next_commands` chaining on every response |
| Token efficiency | 9/10 | `response_mode` tiers, secondary structure hidden by default, sequence previews |
| Observability | 9/10 | `request_id`, `elapsed_ms`, `cached`, version/git_sha/build on every surface |
| Error handling | 9/10 | Every induced error returned an actionable, typed envelope |
| Speed / latency | 6/10 | 2-10 s per live call; the one genuinely weak area |
| **Overall (UX)** | **8.5/10** | LLM-native design throughout; latency is the only real drag |

### Discoverability — 9/10

`get_server_capabilities` returns tool signatures, argument aliases, enum
value-sets, the error-code taxonomy, limits, recommended workflows, a truncation
contract, response modes, and a latency profile in one call. More importantly,
**every response — success and error — carries `_meta.next_commands`** with
ready-to-call `{tool, arguments}` steps. After `find_proteins_batch` the response
told me what to call next; I did not have to guess. This is the single biggest
LLM-ergonomics win and it measurably reduces wrong-tool round-trips. 126 curated
example queries (`search_example_queries` / `get_example_query`) round out the
data-model learning path.

### Token efficiency — 9/10

`get_protein_features` hid 10-52 secondary-structure features by default (with an
opt-in hint) — exactly the noise an LLM does not want. `minimal` mode on
`get_protein` returned a lean ~15-field record. Cross-reference `compact` caps
each database at 25 ids and reports per-database counts. The four `response_mode`
tiers genuinely differ. (One caveat surfaced in Part 2: `full`/`standard`
sequence mode dumps every isoform's full sequence — see F7.)

### Observability — 9/10

Every response carries `elapsed_ms`, `cached`, `request_id`, and `_meta.tool`.
`get_server_capabilities` reports `server_version` + `git_sha` + `built_at` +
`uniprot_release`, which let me confirm the live server matches repo HEAD and
resolve a stale deploy-drift note. (Part 2 docks nothing here directly, but see
F4: the advertised latency bands under-state reality for two tools.)

### Error handling — 9/10

I made a real mistake — `search_example_queries(query=...)` when it wants
`text=`. The server returned `invalid_input` with `allowed_values: [text, limit]`,
the correct signature as a `hint`, and a `next_commands` pointer. A bogus
accession `ZZZ999` came back with a concrete valid example. Best-in-class.

### Speed / latency — 6/10

Live SPARQL calls ran 2.2 s (features) to 10.4 s (`find_proteins`). The endpoint
is upstream-bound (QLever) and the server is honest about it (`latency_note`,
1 h cache that serves repeats in ~0 ms), but first-touch latency is what an
interactive agent feels. The discovery path (`find_proteins`) is the worst
offender — see F3.

---

## Part 2 — Systematic Senior-Tester Pass

~30 live calls covering all 15 tools, every verbosity mode, documented filters,
aliases, all SPARQL query forms and result formats, isoform accessions, and the
reachable error taxonomy.

### Tool-by-tool results

| Tool | Status | Notes |
|------|:---:|-------|
| get_server_capabilities | PASS | summary + full both excellent; full adds graphs/prefixes/contracts |
| run_sparql_query | PASS | SELECT/ASK ok, write rejected, syntax error clean, CSV ok, LIMIT auto-inject correct (not injected for ASK) |
| search_example_queries | MINOR | works; rejects `query=` (wants `text=`) — F6 |
| get_example_query | PASS | returns query text + runnable next_command |
| find_proteins | SLOW | all anchors correct; 2.9-10.4 s latency (F3); page = 25 not 50 (F5) |
| find_proteins_batch | PASS | concurrent resolve; `unresolved_genes` reported |
| get_protein | PASS | handles isoform gracefully; gene-symbol redirect; content-aware chaining |
| get_protein_sequence | **BUG** | isoform accession -> `not_found` despite sequence existing — F2 |
| get_protein_features | **BUG** | isoform accession -> silently returns 0 features — F1 |
| get_protein_variants | PASS | truncation contract clean; `disease_associated_only` works |
| get_protein_diseases | PASS | definition + involvement; ~1.6 s (over advertised band — F4) |
| get_protein_cross_references | PASS | unmatched-db did-you-mean; `full` uncaps + restores IRIs |
| get_protein_go_terms | PASS | aspect filter + ECO evidence; bad enum lists valid values |
| map_identifiers | PASS | curated primary-id core; db filter works |
| get_taxon | PASS | id / name / common-name + lineage; curated index 0 ms |

### Latency evidence (observed this session)

| Call | elapsed_ms | Note |
|------|---:|------|
| run_sparql_query (bound SELECT) | 98 | fast |
| run_sparql_query (CSV) | 39 | fast |
| run_sparql_query (ASK) | 205 | LIMIT correctly not injected |
| get_protein (cold) | 626 | within band |
| get_protein_sequence (full, 11 isoforms) | 552 | fast but heavy payload (F7) |
| get_protein_variants | 245-332 | within band |
| get_protein_go_terms | 233 | within band |
| get_protein_cross_references | 137-279 | within band |
| map_identifiers | 95-192 | within band |
| get_protein_diseases | 1595 | **over "fast 0-700" band (F4)** |
| get_protein_features (all / filtered) | 1690-1894 | **over "fast 0-700" band (F4)** |
| get_taxon (id + lineage) | 426 | within band |
| get_taxon (name / common-name) | 0 | curated index, cached |
| find_proteins (name_contains) | 2857 | slow_cold_scan |
| find_proteins_batch (2 genes) | 5819 | slow_cold_scan |
| find_proteins (gene + reviewed, 1 hit) | 6035 | **exact-ish anchor, still a scan (F3)** |
| find_proteins (keyword) | 6166 | slow_cold_scan |
| find_proteins (mnemonic exact) | 7983 | **exact key, full scan (F3)** |
| find_proteins (ec_number) | 9217 | slow_cold_scan |
| find_proteins (gene, no reviewed) | 10380 | slowest; 248 total, 24 TrEMBL/page (F9) |

### Findings (severity-ranked)

#### F1 — HIGH — `get_protein_features` silently returns 0 features for an isoform accession

`get_protein_features(P05067-2)` returns `count: 0` (for all types, and for a
`["domain","region"]` filter), while echoing accession `P05067`. The canonical
`get_protein_features(P05067)` returns **12** domain/region features. The response
even attaches `filter_hint: "No features matched the requested types for this
entry."`, which actively reinforces the false conclusion. For a tool whose purpose
is grounding research in evidence, silently returning empty-as-fact is the most
dangerous failure mode. **Evidence:** `P05067-2` -> 0; `P05067` -> 12
(request_ids `3e2885f5fa6d`, `003d25333f8a`).

**Fix:** Normalize isoform accessions at the entry boundary — strip `-N` ->
canonical and return canonical features with an `isoform` note (matching
`get_protein`'s model), or return an explicit error. Never return empty for a
valid isoform without an isoform-context flag.

#### F2 — HIGH — `get_protein_sequence` returns `not_found` for valid isoforms, breaking a cross-tool contract

`get_protein_sequence(P05067-2)` and `(P05067-3)` return `not_found`, even though
those isoform sequences exist and are listed inside `get_protein_sequence(P05067,
full).isoforms[]`. Worse, `get_protein(P05067-2)` explicitly advises *"call
get_protein_sequence for the isoform-specific sequence and mass of P05067-2"* — a
next-step that then fails. One tool advertises a path another tool rejects.
**Evidence:** request_ids `2b60949fe8c5`, `685787e3fb5e`; contradicting advice in
`get_protein(P05067-2)` (`c9d52912c6f4`).

**Fix:** Resolve the isoform IRI (`http://purl.uniprot.org/isoforms/P05067-2`) and
return that specific isoform's sequence/mass. The data is isoform-specific, so
mapping to canonical is not appropriate here — fetch the real isoform sequence.

> F1 + F2 together = **inconsistent isoform handling across the `get_protein*`
> family**: `get_protein` handles it gracefully (`requested_accession` + `isoform`
> + `isoform_note`); `get_protein_sequence` and `get_protein_features` do not.
> `get_protein` is the correct model the other two should copy.

#### F3 — MEDIUM — `find_proteins` exact-key lookups run as cold scans

Anchored lookups resolving to a single entry are slow: `mnemonic="PNKP_HUMAN"`
(exact entry name) 8.0 s; `gene=BRCA1 + reviewed=true` (1 hit) 6.0 s; EC-anchored
9.2 s. The `latency_profile` honestly buckets `find_proteins` as `slow_cold_scan
(3-12 s)`, so this is documented — but an exact mnemonic or accession-shaped
anchor should be a bound IRI lookup, not a scan. This is the biggest drag on the
primary discovery path (gene -> protein), which an LLM hits constantly.

**Fix:** Fast-path exact `mnemonic`/accession anchors to bound lookups; revisit
the gene-name reviewed+unreviewed join (likely the cost driver).

#### F4 — MEDIUM — `latency_profile` under-states reality for two "fast" tools

`latency_profile.bands.fast` advertises `0-700 ms` for `get_protein_features` and
`get_protein_diseases`, but both measured **1.6-1.9 s repeatedly** (2-3x over).
Observability that mis-predicts is worse than none. **Fix:** widen the band to
~2 s or move these two to a `medium` bucket.

#### F5 — MEDIUM — `default_select_limit: 50` contradicts actual `find_proteins` paging

Capabilities advertises `default_select_limit: 50`, but `find_proteins` returns
**25 per page** (BRCA1 `{returned: 25, total: 248}`; Apoptosis `{returned: 25,
total: 1553}`), and xref/map cap id-lists at 25. The 25 is internally consistent
but undocumented. **Fix:** add `find_proteins_page_size: 25` to capabilities (or
align behavior to 50).

#### F6 — LOW — `search_example_queries` lacks a `query`/`q` alias

It rejects `query=` (wants `text=`), even though `query` is a documented alias for
`run_sparql_query`'s `sparql`. A natural wrong guess (hit twice across sessions).
**Fix:** accept `query`/`q` -> `text` on the search tool.

#### F7 — LOW — No canonical-only full sequence mode (token sink)

`standard` and `full` both dump every isoform's full sequence (APP = 11
sequences, ~10 KB) when the caller often wants only the canonical. **Fix:** add a
`canonical_only` flag, or make `standard` = canonical-full-only and reserve `full`
for all-isoforms.

#### F8 — LOW — CSV/TSV SELECT mislabeled `query_type: "RDF/raw"`

A SELECT projected to CSV reports `query_type: "RDF/raw"` (it is a SELECT, not a
graph query). Cosmetic. **Fix:** preserve the original query type and report the
serialization separately.

#### F9 — LOW — Gene-anchor page dominated by TrEMBL noise

`find_proteins(BRCA1)` returns 24 unreviewed TrEMBL fragments behind 1 Swiss-Prot
entry (248 total). Sorting already puts reviewed first (good), but the page is
mostly noise. **Fix:** default `reviewed=true` on gene anchors, or surface a
`reviewed_count`.

### What is genuinely strong (do not regress)

- **Error handling is best-in-class and consistent.** Every induced failure
  returned a typed envelope with actionable recovery: bad arg name
  (`allowed_values`), bad enum value (lists the 3 valid aspects), bad accession
  (with example), **gene-symbol-as-accession redirected to `find_proteins`**,
  write query rejected, malformed SPARQL -> `query_syntax_error` with causes, and
  **unmatched xref DB -> `database_hint` with did-you-mean**. The isoform
  silent-empty (F1) is the one place this discipline lapses — which is exactly why
  it stands out.
- **`next_commands` chaining on every response**, success and error.
- **Truncation contract** `{returned, total, reason, recovery}` consistent across
  features/variants/find_proteins, with per-database `{returned, total}` for xrefs.
- **Token economy:** secondary structure hidden by default with opt-in; compact
  sequence preview; xref compact caps + counts; meaningful `response_mode` tiers.
- **`domain_region_hint`** fires when filtering to `domain` only — directly serves
  the common "get domains" question.
- **Curated taxon index** resolves names/common-names ("human", "Mus musculus")
  in 0 ms.
- **`get_protein` isoform handling** (the correct model) and content-aware
  chaining gated by `has_variants`/`has_diseases`/`has_structure`.
- **Deterministic ordering** (reviewed-first, mnemonic, accession) and SPARQL
  write-protection + LIMIT auto-injection.

### Untested in this session

- **Obsolete / demerged accession handling** (`obsolete:true` + `replaced_by`).
  The contract reads correctly in `detail='full'` capabilities, but I had no known
  obsolete accession on hand. Worth a dedicated test with a real demerged
  accession.

### Prioritized recommendations

1. **Fix the isoform cluster (HIGH, F1/F2).** Make `get_protein_sequence` resolve
   isoform IRIs; make `get_protein_features` map to canonical (with an isoform
   note) or error explicitly — never silent-empty. Align both with `get_protein`.
   Add a per-tool regression test for an isoform accession.
2. **Fast-path exact `find_proteins` anchors (MEDIUM, F3).**
3. **Re-calibrate `latency_profile` (MEDIUM, F4)** so features/diseases are not
   advertised as sub-700 ms.
4. **Document `find_proteins` page size = 25 (MEDIUM, F5).**
5. **Polish (LOW):** `query`/`q` alias (F6); canonical-only sequence mode (F7);
   CSV `query_type` label (F8); default `reviewed=true` on gene anchors (F9).

### Score summary

| | Part 1 (UX) | Part 2 (tester) |
|--|:--:|:--:|
| Discoverability | 9 | 9 |
| Token efficiency | 9 | 8.5 (F7) |
| Observability | 9 | 8.5 (F4) |
| Error handling | 9 | 8.5 (F1 silent-empty) |
| Speed / latency | 6 | 6 (F3) |
| Correctness | (not separately scored) | 6 (F1/F2 isoform bugs) |
| **Overall** | **8.5** | **8.0** |

The tester pass revises the overall down from 8.5 to **8.0**: the contract design,
error hygiene, and token discipline are top-decile, but the isoform handling
(F1/F2) is a genuine correctness defect — a silent wrong answer in an
evidence-grounding tool — that should block before the next release.
