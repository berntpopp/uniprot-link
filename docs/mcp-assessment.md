# uniprot-link MCP Assessment

An LLM-consumer evaluation of the uniprot-link MCP server, conducted by driving the
live tool surface and rating the experience. Two assessments are recorded:

1. **Consumer Experience Assessment** - a dimension-based rating of what it is like
   to consume this MCP as the calling model (discoverability, token efficiency,
   speed, observability, etc.).
2. **Comprehensive Tool-by-Tool Test** - a senior-tester pass exercising all 14
   tools with happy paths, every `response_mode`, filters, pagination, caching,
   and deliberate failure probes.

## Test Context

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Server | `uniprot-link` |
| Server version | 0.3.0 |
| Build | git_sha `2847382`, built_at `2026-06-12T06:36:05Z` |
| UniProt release | 2026_01 |
| Endpoint | https://sparql.uniprot.org/sparql (QLever) |
| Evaluator | Claude (LLM consumer of the MCP) |
| Method | ~30 live tool calls across 3 batches; primary anchor accession Q96T60 (PNKP_HUMAN) |
| Scope note | Single session, single endpoint state. Findings reflect observed behavior at the build above. |

---

## Part 1 - Consumer Experience Assessment

How effective and economical the server is to use as the calling model, scored 1-10
per dimension with the evidence each score rests on.

### Scores

| Dimension | Score | Basis |
|-----------|:----:|-------|
| Discoverability | 9 | `get_server_capabilities` is a single complete map: 14 tools, 21 graphs with triple counts, prefixes, feature-type and xref vocabularies, error taxonomy, limits, recommended workflows. Plus 126 searchable example queries and a `uniprot://capabilities` resource. |
| Tool / schema design | 9 | Clear names; `find_proteins` requires an anchor (prevents unbounded SPARQL scans); `feature_types` advertises a filter vocabulary; tool descriptions carry concrete examples (P05067). |
| Chaining / composability | 8 | Every success response carries `_meta.next_commands` as ready-to-call `{tool, arguments}` with the accession pre-filled. Deduction: suggestions are largely static rather than reflecting what the entry actually contains. |
| Observability | 9 | Per-call `elapsed_ms`, `cached`, `uniprot_release`, `endpoint`, `citation`, echoed `tool`; capabilities exposes `server_version` + `git_sha` + `built_at`. Deduction: no request/trace id to correlate a multi-call session. |
| Grounding / safety | 9 | Release pinned (2026_01), citation on every call, `research_use_only` + `unsafe_for_clinical_use`, documented read-only contract, build provenance. |
| Error handling | 7 | The `invalid_input` envelope is good (`error_code`, `message`, `retryable`, `recovery_action`), but truncated allowed-lists and inconsistent error `next_commands` weaken it (see Part 2). |
| Token efficiency | 6 | `response_mode` works (the long `function` text is correctly gated behind standard/full), but the `_meta` block (4 `next_commands` objects + endpoint + citation) repeats on every call including `minimal`, and minimal vs compact barely differ. |
| Speed / latency | 6 | Upstream-bound: entry-detail tools 40 ms - 1.9 s, but `find_proteins` is a hotspot (5.8-8.7 s). Caching works (warm reads 0 ms). |
| Consistency | 8 | Uniform envelope across tools. Deductions: `response_mode` only on the 4 verbose tools; error path sometimes drops `next_commands`; `get_taxon` by-name response is degraded vs by-id. |

**Part 1 overall: 8/10** - excellent at the things that make an LLM *effective*
(discoverability, grounding, chaining, observability) and merely adequate at the
things that make it *cheap and fast* (per-call token overhead, `find_proteins`
latency).

### Correction logged during testing

An early impression that **caching was not working** (`cached:false` on every call
in the first batch) was **disproved** in Part 2: warm reads of the same accession
returned `cached:true, elapsed_ms:0`. The cache keys on the accession and applies
`response_mode` as a projection over cached data - a good design. The first-batch
misses were simply cold-cache first touches.

---

## Part 2 - Comprehensive Tool-by-Tool Test

A senior-tester pass over all 14 tools. Verdict first, then the per-tool scorecard,
then prioritized defects with evidence, then improvements.

### Verdict

**Part 2 overall: 8/10** - a well-engineered, contract-disciplined server. Data
shaping (HGVS-style variant notation, taxonomy lineage, requested-vs-mapped
databases) is above average, and the `run_sparql_query` truncation / read-only
contracts are textbook. Issues cluster in two places: `get_protein_features`
(a genuinely broken contract) and inconsistent error envelopes.

### Per-tool scorecard

| # | Tool | Score | Notes from testing |
|---|------|:----:|--------------------|
| 1 | get_server_capabilities | 9 | Complete discovery surface. Only flaw: its `feature_types` list is missing types the API actually emits (Bug 1). |
| 2 | run_sparql_query | 9 | Auto-LIMIT + `truncated.reason` + recovery; `limit` override honored (LIMIT 3 -> 3 rows); ASK -> bool; CONSTRUCT -> turtle; DELETE correctly rejected. Thin syntax-error detail. |
| 3 | search_example_queries | 7 | 126 queries searchable, but duplicate `example_id` (26 twice) and federated Rhea hits with empty keywords dilute relevance. |
| 4 | get_example_query | 9 | Full text + populated keywords + ready-to-run `next_command`. Clean. |
| 5 | find_proteins | 7 | Correct anchor enforcement + offset pagination + good errors - but the latency hotspot (gene+taxon 5.8 s, keyword 8.7 s, EC 6.1 s) and a wrong tool name in its hint (Bug 4). |
| 6 | get_protein | 8 | `response_mode` gradient real; clean `not_found` on `999999`. Minor: no local format pre-check; odd recovery hint (stuffs accession into `gene`). |
| 7 | get_protein_sequence | 7 | Isoforms + caching work, but `compact` default already returns the full sequence (Bug 6). |
| 8 | get_protein_features | 6 | Core works, but this tool carries 3 defects: broken round-trip (Bug 1), truncated allowed-list (Bug 2), no error `next_commands` (Bug 3). Most-defective tool. |
| 9 | get_protein_variants | 9 | Excellent shaping: `notation` (L176F), `variant_type`, linked `diseases`, `dbsnp`; `disease_associated_only` works (10 -> 5). |
| 10 | get_protein_diseases | 7 | Correct, but `description` is the generic involvement boilerplate, not the disease definition (Bug 9). |
| 11 | get_protein_cross_references | 9 | 80 DBs; `full` correctly restores raw IRIs (`http://rdf.wwpdb.org/pdb/2W3O`); DB filtering works. |
| 12 | get_protein_go_terms | 8 | Clean aspect grouping; missing GO evidence codes (Bug 10). |
| 13 | map_identifiers | 9 | `requested_databases` vs `mapped_databases` is great observability; filtering + modes work. |
| 14 | get_taxon | 7 | Strong by-id (lineage, parent), but by-name drops `elapsed_ms`/`cached`/`next_commands` (Bug 5). |

### Bugs found (prioritized, with evidence)

**Bug 1 - HIGH: `feature_types` round-trip contract is broken.**
The full feature dump for Q96T60 emits types `natural_variant`, `alternative_sequence`,
and `sequence_conflict`, but `get_protein_features(feature_types:["natural_variant"])`
returns `invalid_input: Unknown feature type`. The tool description explicitly
promises "each returned `type` round-trips to the filter vocabulary." It does not.
Fix: add these to the filter vocabulary *and* to `capabilities.feature_types`, or
stop emitting non-filterable types. An LLM following the documented contract will
build a failing call.

**Bug 2 - MED/HIGH: allowed-values list is truncated mid-word in errors.**
Both feature-type errors end `"...np_binding, pep"` - cut off, hiding ~10 valid
types (peptide, region, repeat, signal_peptide, ... zinc_finger). A model cannot
recover to a type the message truncated away. Fix: return the complete list, a
structured `allowed: [...]` array, or a pointer to capabilities.

**Bug 3 - MED: `next_commands` inconsistently present on errors.**
Present on `run_sparql_query` and `find_proteins` error envelopes; absent on
`get_protein_features` (invalid_input) and `get_taxon` (not_found). The server's
own instructions promise next_commands "on success AND error." Make it uniform.

**Bug 4 - MED: wrong tool name in `find_proteins` error hint.**
The message says "use sparql_query or search_example_queries" - but the tool is
`run_sparql_query`. A consumer may call a non-existent `sparql_query`. One-word fix,
but actively misleading.

**Bug 5 - MED: `get_taxon` by-name response is degraded vs by-id.**
The name lookup drops `elapsed_ms`, `cached`, and - critically - `next_commands`.
Name -> id is the natural first step, so the chain breaks exactly where it is most
needed (no suggested `get_taxon(id)` or `find_proteins(organism_taxon=...)`). The
by-name matches also omit `rank`.

**Bug 6 - MED: `get_protein_sequence` default `compact` returns the entire sequence.**
Verified compact == full for sequence content (both returned the complete 521-aa
string; only `minimal` omitted it). The gradient is effectively binary. For a large
protein (titin, ~34,350 aa) the default call would dump tens of KB. Consider a
truncated/windowed `compact` (length + mass + first/last N residues) and reserve the
full string for `full`.

**Lower severity:**

- **Bug 7:** no client-side accession format check - malformed `999999` round-trips
  to the endpoint for a 404 rather than a cheap local `invalid_input`.
- **Bug 8:** `get_protein` not_found recovery suggests `find_proteins(gene:"999999")`,
  blindly reusing the bad accession as a gene.
- **Bug 9:** `get_protein_diseases.description` is involvement boilerplate, not the
  `skos:definition` available in the diseases graph.
- **Bug 10:** `get_protein_go_terms` omits evidence codes (IDA/IEA), which matter for
  trusting and citing annotations.
- **Bug 11:** SPARQL syntax errors return only `[400] Malformed SPARQL query` -
  QLever usually reports a parse position worth passing through.
- **Bug 12:** example search has duplicate IDs / empty keywords.

### What works well (credit)

- Uniform response envelope; `elapsed_ms` / `cached`; release pinning; citation on
  every call; research-use safety flags; build provenance in capabilities.
- Excellent truncation contract on `run_sparql_query` (`limit_injected` +
  `truncated.reason` + `recovery`) and `find_proteins` pagination (offset recovery).
- Read-only enforcement works (DELETE rejected as `invalid_input`).
- Caching works and is implemented as mode-projection over cached data.
- `next_commands` chaining (on success) is genuinely useful.
- `map_identifiers` `requested_databases` vs `mapped_databases` is great observability.
- `get_protein_variants` shaping (HGVS-style `notation` + `variant_type` + linked
  `diseases` + `dbsnp`) is high value.

### Suggested improvements, ranked by impact

1. **Fix the `feature_types` vocabulary mismatch (Bug 1)** and stop truncating the
   allowed-list (Bug 2). Highest ROI: `get_protein_features` is the most-used shaping
   tool and currently misrepresents its own filter set.
2. **Make the error envelope uniform** - always include `next_commands` and the full
   `allowed`/recovery payload (Bugs 3, 4, 5). Consistency is what an LLM consumer
   optimizes against.
3. **Attack `find_proteins` latency** - 6-9 s is the worst experience in the suite and
   matches the AGENTS.md QLever anti-pattern (alphabetical `ORDER BY` over a large
   pre-LIMIT set). Sort in Python post-LIMIT or anchor tighter.
4. **Rework the `response_mode` gradient for sequence (Bug 6)** so `compact` is
   actually compact, now that multi-KB sequences are reachable.
5. **Enrich the high-value record tools** - disease definitions (Bug 9) and GO
   evidence codes (Bug 10) are cheap joins that materially improve trust and citation.
6. **Polish discovery** - de-dup `search_example_queries`, populate keywords, and rank
   UniProt examples above federated ones.

Net: the core retrieval and SPARQL paths are production-quality. The fixes above are
mostly contract-consistency plus one genuine vocabulary bug, not architecture. Bugs
1-5 likely live in the feature-type vocabulary and the error-envelope builder under
`uniprot_link/mcp/`.

---

## Appendix - Probe Coverage

| Tool | Probes exercised |
|------|------------------|
| get_server_capabilities | full discovery surface |
| run_sparql_query | unbounded SELECT (auto-LIMIT 50), explicit `limit` override (LIMIT 3), ASK -> bool, CONSTRUCT -> turtle, DELETE (read-only reject), malformed query (syntax error) |
| search_example_queries | free-text search "domain" |
| get_example_query | fetch example 108 by IRI |
| find_proteins | gene+taxon, keyword+taxon, ec_number, no-anchor (error), name_contains-only (error) |
| get_protein | minimal, full, not_found (`999999`), real TrEMBL hits (`Q9ZZZ9`, `Q1Q1Q1`) |
| get_protein_sequence | minimal, compact, full, cache warm-hit |
| get_protein_features | domain, region, all (35 features), multi-filter (active_site+binding_site), unknown-type (error), round-trip probe (`natural_variant`) |
| get_protein_variants | disease_associated_only=true (5), default (10) |
| get_protein_diseases | Q96T60 (AOA4, MCSZ) |
| get_protein_cross_references | compact (80 DBs), full + DB filter (PDB, raw IRIs) |
| get_protein_go_terms | Q96T60 (21 terms, 3 aspects) |
| map_identifiers | default set, restricted (PDB, Ensembl) |
| get_taxon | by id + lineage (9606), by name ("Homo sapiens"), not_found (`999999999`) |
