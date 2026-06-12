# uniprot-link MCP — Senior Tester Evaluation

**Date:** 2026-06-11
**Server:** uniprot-link v0.1.0 (UniProt release 2026_01, QLever endpoint)
**Method:** All 14 tools exercised across ~25 calls — happy path, edge cases,
error/abuse cases, and contract conformance (does behavior match the schema and
the advertised `_meta` contract). Findings verified against the live endpoint via
`run_sparql_query` where a correctness claim was made.

---

## Overall verdict: 6 / 10

A genuinely strong foundation — excellent capabilities discovery, airtight
provenance/safety, and a fast, well-instrumented SPARQL escape hatch. But the
*typed convenience tools* (the layer most agents will actually call) carry
multiple correctness and contract bugs that an LLM will silently propagate as
fact. The SPARQL layer is more trustworthy than the typed layer wrapping it,
which is backwards from what you'd want.

---

## Tool-by-tool results

| # | Tool | Verdict | Finding |
|---|------|---------|---------|
| 1 | `get_server_capabilities` | Pass | Rich, accurate discovery surface |
| 2 | `run_sparql_query` | Mostly | Best-instrumented tool (`elapsed_ms`, `limit_injected`, `truncated`); ASK / SELECT / auto-LIMIT all correct. **But** a write attempt (`INSERT DATA`) returns `internal_error` / `switch_tool` instead of a clear read-only rejection |
| 3 | `search_example_queries` | Partial | `"disease"` works; `"protein domain architecture"` returns 0. Brittle literal matching |
| 4 | `get_example_query` | Pass | Full text, `federates_with`, runnable `next_commands` |
| 5 | `find_proteins` | Pass | Anchor enforcement returns clean `invalid_input` |
| 6 | `get_protein` | **Bug** | Bogus accession `ZZZZZZ` -> `success:true` with an empty body and `next_commands` chaining into more dead calls |
| 7 | `get_protein_sequence` | Minor | Canonical sequence duplicated (`canonical` **and** `isoforms[0]`); isoform-2 `mass_da:null` |
| 8 | `get_protein_features` | **Bug** | `feature_types=["domain"]` returns 0 despite a `Domain_Extent` ("FHA") present — vocab key mismatch; bogus accession -> silent empty |
| 9 | `get_protein_variants` | **Bug** | Structured `diseases` field is **always `[]`** even when `description` says "In MCSZ" / "In AOA4"; low `limit` + ascending-position sort silently hides disease variants in the tail; one `substitution:""` |
| 10 | `get_protein_diseases` | Pass | Clean; `mim` always null (not surfaced) |
| 11 | `get_protein_cross_references` | Minor | Correct, but returns full IRIs |
| 12 | `get_protein_go_terms` | **Bug** | `by_aspect` dumps **all 21 terms under `"unknown"`** — the BP/MF/CC grouping the description promises is broken |
| 13 | `map_identifiers` | Minor | Correct, but returns full IRIs not short IDs |
| 14 | `get_taxon` | **Bug** | `parent_taxon_id` is an arbitrary ancestor (Teleostomi) not the direct parent (Homo / 9605, **verified**); `lineage` array is unordered |

---

## Ratings by dimension

| Dimension | Score | Evidence |
|---|---|---|
| Functional correctness | 5 | 5 real bugs in typed tools (GO aspect, taxon parent, domain filter, variant->disease link, silent not-found) |
| Discoverability | 7 | Capabilities excellent; example search brittle; feature-type vocab mismatch is a trap |
| Token efficiency | 5 | Citation (~160 chars) repeated every call; full IRIs; duplicated sequence; no `response_mode` |
| Speed / performance | 9 | 97-99 ms simple calls, 394 ms for a 29-row join; sub-second throughout |
| Observability | 6 | Superb on `run_sparql_query`, absent on typed tools; clean error envelopes; inconsistent `next_commands` |
| Error handling / robustness | 5 | Good envelopes for syntax / taxon / anchor; **but** silent success on bogus accessions and `internal_error` on writes |
| Composability / chaining | 6 | `next_commands` is a great pattern, inconsistently applied, and chains into dead ends for invalid IDs |
| Safety / grounding / provenance | 9 | Citation + release pin + `unsafe_for_clinical_use` + research-use notice, consistently |
| Input / schema ergonomics | 8 | Typed, modern, documented anchor rules |

---

## Two systemic inconsistencies

These are worth fixing structurally, not per-tool.

1. **Not-found handling is split-brain.** `get_taxon(999999999)` and
   `run_sparql_query` return proper `not_found` / error envelopes.
   `get_protein`, `get_protein_features`, `get_protein_sequence` etc. return
   `success:true` with empty/absent fields for nonexistent input. Same server,
   two contradictory contracts — an agent can't write one error-handling rule.

2. **The advertised `next_commands` contract is only ~half-true.** The MCP
   instructions say "responses carry `_meta.next_commands`," but
   `get_protein_sequence`, `_variants`, `_diseases`, `_cross_references`,
   `_go_terms`, `map_identifiers`, and `get_protein_features` all omit it.

---

## Verification note (taxon parent)

`get_taxon(9606)` reported `parent_taxon_id: 117570` (Teleostomi). Querying the
endpoint directly:

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX taxon: <http://purl.uniprot.org/taxonomy/>
PREFIX up: <http://purl.uniprot.org/core/>
SELECT ?parent ?name ?rank WHERE {
  taxon:9606 rdfs:subClassOf ?parent .
  ?parent up:scientificName ?name .
  OPTIONAL { ?parent up:rank ?rank }
}
```

returns the **full transitive closure** (29 ancestors). The true direct parent —
taxon **9605 *Homo*, rank Genus** — is present in that set. The tool is picking
an arbitrary row rather than the minimal (direct) ancestor, and the same
unordered set is surfaced as `lineage`.

---

## Prioritized improvements

### P0 — correctness (an agent will state these as fact)

1. **`get_taxon`:** compute the **direct** parent (the minimal element of the
   `subClassOf` closure, or the nearest rank), and return `lineage` ordered
   species -> root. Today's parent is simply wrong.
2. **`get_protein_go_terms`:** populate `biological_process` /
   `molecular_function` / `cellular_component` by joining the GO graph's
   namespace — stop bucketing everything as `"unknown"`.
3. **`get_protein_features`:** make `feature_types=["domain"]` actually match
   `Domain_Extent`. Normalize the filter vocabulary to the returned `type`
   values (or map server-side), and on a zero-match filter echo the accepted keys.
4. **`get_protein_variants`:** either populate the structured `diseases` field
   (parse the `In <DISEASE>` linkage that already exists in `description`) or
   remove the field and document that disease is free-text only. A
   non-functional field is worse than none.

### P1 — robustness & contract

5. Make non-existent accessions return `not_found` across all `get_protein*`
   tools, matching `get_taxon`. Add a `resolved` boolean if you want to keep
   `success:true`.
6. **`run_sparql_query`:** pre-validate query form and reject UPDATE / write
   queries with `invalid_input` ("read-only: SELECT/ASK/CONSTRUCT/DESCRIBE
   only"), not `internal_error`.
7. **`get_protein_variants`:** don't let `limit` + position-sort silently hide
   disease variants — sort disease-associated first, or surface a `truncated`
   block like `run_sparql_query` does.
8. Honor the `next_commands` contract on every tool, or stop advertising it as
   universal.

### P2 — efficiency & polish

9. Add `response_mode` (minimal | compact | standard | full); stop duplicating
   the canonical sequence; return short IDs by default in `map_identifiers` /
   `get_protein_cross_references` (full IRI behind a flag); emit the long
   citation once in capabilities rather than in every `_meta`.
10. Strengthen `search_example_queries` with fuzzy / multi-word matching;
    compute isoform mass; surface `mim` in diseases.
11. Propagate `run_sparql_query`'s `elapsed_ms` (and a `truncated` block) to the
    typed tools so agents can reason about latency and completeness everywhere.

---

## Highest-leverage fix

Unify not-found handling (P1.5) and ship the four P0 correctness fixes. Those are
the cases where the server currently hands an LLM confidently-wrong data with
`success:true` — exactly the failure mode an agent cannot catch on its own.
