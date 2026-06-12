# uniprot-link MCP — Consumer & QA Assessment

**Date:** 2026-06-12
**Server:** `uniprot-link` v0.1.0
**UniProt release:** 2026_01
**Endpoint:** https://sparql.uniprot.org/sparql (QLever-backed SPARQL 1.1)
**Assessor:** Claude (LLM client consuming the MCP)
**Method:** Hands-on use across two passes — (1) a real research task (PNKP
domains) rated as an LLM consumer, then (2) a systematic QA sweep exercising
all 14 tools across happy-path, edge-case, and error conditions (26 calls).

> Scope note: Part 1 is an experience rating grounded in one real task. Part 2
> is a deliberate test sweep. Where the two disagree on a score, Part 2
> supersedes — it is based on broader evidence.

---

## Part 1 — LLM-Consumer Experience Assessment

Grounded in answering a real question ("get domains for PNKP") plus the
server's own capabilities surface. Small sample (one task, six calls); read as
informed first impressions, not a benchmark.

### Headline

Overall **7/10** as a first impression. A well-built, agent-friendly server —
rich capabilities discovery, citation governance, and `next_commands` chaining
are all above average. But it has one genuinely dangerous flaw hit directly:
the `feature_types` filter silently returned an incomplete result and nearly
produced a wrong answer. Filtering features by `["domain","region"]` dropped
the FHA domain — the single most important domain in PNKP — because it is
emitted under the type `Domain_Extent` while the filter vocabulary calls it
`domain`. No error, no warning. An agent without the prior knowledge that PNKP
*should* have an FHA domain would have confidently reported "PNKP has no
domains, only regions."

### Per-dimension ratings

| Dimension | Score | Observation |
|---|---|---|
| Discoverability | 7/10 | `get_server_capabilities` is excellent (tools, 21 named graphs, prefixes, feature-type vocab, xref databases, workflows, error codes, limits — one call). 126 searchable example queries. But the documented `feature_types` vocab (lowercase `domain`) does not match emitted values (`Domain_Extent`), so the key affordance is misdocumented. |
| Token efficiency | 7/10 | Compact, well-shaped JSON. But every response repeats a `_meta` block including the ~150-char `recommended_citation`, endpoint URL, and clinical flag. No `response_mode` verbosity knob, unlike sibling servers (sysndd, hnf1b). |
| Speed / latency | 8/10 | Anchored calls return promptly; the "anchor on accession/gene" discipline pays off. Docked because the filter bug forced a 4-call task into what should have been 2. |
| Observability | 5/10 | `_meta` gives solid provenance (release, endpoint, tool, citation). But no latency/timing, no truncation flag, no request id, and — critically — no signal when a filter matches zero of N features. |
| Correctness / error handling | 6/10 | Documented 7-code error taxonomy and enforced anchor requirements are good. Deduction is entirely the silent partial result: "quietly return less than asked" manufactures false confidence in an autonomous consumer. |
| Composability / agent ergonomics | 8/10 | `_meta.next_commands` is genuinely useful for chaining; stable accessions, `recommended_workflows`, citation contract make multi-step research smooth. Strongest area. |
| Safety / governance | 9/10 | Consistent research-use-only notice, `unsafe_for_clinical_use` flag, verbatim-citation contract on every payload. Appropriate and well executed for biomedical data. |

### Improvements (prioritized)

1. **Fix the `feature_types` vocabulary mismatch (must-fix).** Input key
   `domain` does not match output type `Domain_Extent`, so filtering for
   domains drops real domains. Normalize output to the filter vocab, or fix the
   filter→type mapping; echo the resolved type set back.
2. **Fail loud on empty/partial filters.** When a filter matches 0 of N
   features, return `_meta.warning` listing the available types. Never let an
   autonomous consumer read "filtered to nothing" as "nothing exists."
3. **Make input and output vocabularies identical.** Output emits
   TitleCase-underscore (`Domain_Extent`, `Beta_Strand`); capabilities
   documents snake_case (`domain`, `beta_strand`). Pick one canonical casing.
4. **Cut per-call boilerplate and/or add `response_mode`.** Move static
   citation/notice to session scope; add `minimal|compact|standard|full`.
5. **Add lightweight observability.** `_meta.elapsed_ms`, a
   `limit_applied`/`truncated` flag, and (for `run_sparql_query`) the effective
   SPARQL and row count.
6. **Enrich domain features for cross-linking.** Add `evidence` and an
   InterPro/Pfam/PROSITE xref on domain features.

Highest payoff-per-effort: **#2** — a small `_meta` addition that converts the
most dangerous silent-correctness failure into a self-healing one.

---

## Part 2 — Senior MCP Tester: Full Test Report

**Verdict: 6/10.** The architecture is sound and the `run_sparql_query` escape
hatch is genuinely excellent, but the *typed convenience tools* carry a cluster
of correctness bugs that would actively mislead an autonomous consumer — most
importantly, the recommended entrypoint (`get_protein`) reports **success on a
nonexistent accession**. Error envelopes and discovery are well above average;
data-shaping fidelity is the weak spot.

### Coverage

All 14 tools tested across 26 calls: happy path on every tool, plus filtering,
lowercase/normalization, nonexistent accessions, no-anchor calls, invalid enum
values, name vs. id resolution, ASK/SELECT paths, LIMIT auto-injection, and a
malformed query.

### Findings by severity

#### 🔴 Critical

**C1 — `get_protein` returns `success: true` for a nonexistent accession.**
`get_protein("ZZZ999")` returned `{"accession":"ZZZ999","success":true,
_meta:{next_commands:[...]}}` — no error, no data fields, and it even suggested
follow-up calls for the phantom entry. This is the recommended cold-start
entrypoint, so an agent gets a green light and proceeds as if the protein
exists. It is **inconsistent**: the same bogus accession returns a proper
`not_found` 404 from `get_protein_sequence` and `get_taxon`. Two tools, same
input, opposite contracts. Highest-impact issue.

#### 🟠 High

**H1 — GO aspect grouping is completely broken.** `get_protein_go_terms`
promises grouping by `biological_process / molecular_function /
cellular_component`, but **every** term lands under `"unknown"`. Reproduced on
two unrelated proteins: Q96T60 (21 terms) and P05067 (123 terms). "ATP binding"
(MF), "DNA repair" (BP), and "nucleus" (CC) all share one bucket — the aspect
mapping is not wired up.

**H2 — `get_taxon` reports the wrong parent and an unordered lineage.** For
`get_taxon(9606)` (Homo sapiens) it returned `parent_taxon_id: "117570",
parent_name: "Teleostomi"`. The immediate parent of Homo sapiens is genus
*Homo* (9605); Teleostomi is a distant ancestor. The `lineage` array is also
returned **unordered**, so it cannot establish hierarchy. Both symptoms point
to the same cause: ancestor triples read in arbitrary order, with "parent"
picking whichever comes first.

**H3 — Variant→disease links are dead, and substitutions are sometimes blank.**
`get_protein_variants` advertises "any linked disease(s)", but `diseases: []`
is empty for *every* variant — including ones whose free-text `description`
says "In MCSZ" and "In AOA4". The structured field never populates; disease is
only recoverable by parsing prose. Separately, the position-408 AOA4 variant
returned `substitution: ""` (empty). Variants also omit the wild-type residue,
so `R176F`-style notation cannot be formed without separately fetching the
sequence.

**H4 — `feature_types` filter silently drops real domains.** Filtering features
by the documented-valid type `domain` returns nothing for PNKP, yet the entry's
FHA domain is present in the unfiltered output under type `Domain_Extent`. A
valid filter + a real domain + zero results + no warning = a confidently wrong
"no domains" answer. (An invalid type such as `nonexistent_feature` *does* hard-
error, so the gap is specifically the input-vocab/output-vocab mismatch, not
validation.)

#### 🟡 Medium

**M1 — Typed tools truncate silently.** `get_protein_variants(limit=2)`
returned 2 of 10 with no `truncated` flag and no "total available" count.
`get_protein_go_terms` has no `limit` at all and returned 123 terms in one
blob. Contrast `run_sparql_query`, which signals truncation cleanly:
`limit_injected: true, truncated: {reason: "auto LIMIT 50 applied", recovery:
"..."}`. Relatedly, annotation tools return `count: 0` for a nonexistent
accession (`get_protein_diseases("ZZZ999")`), indistinguishable from "exists
but has no diseases."

**M2 — `map_identifiers` and `get_protein_cross_references` are
near-duplicates.** Unfiltered, both return an identical `by_database` block (80
databases, 115 entries, ~3.5 KB); `map_identifiers` only adds a
`mapped_databases` name list. The docs call `map_identifiers` "a focused
id-mapping view," but it is not more focused by default.

**M3 — Observability and chaining are inconsistent across tools.** Only
`run_sparql_query` returns `elapsed_ms`/`limit_injected`. `_meta.next_commands`
appears on `get_protein`, `get_taxon`, `find_proteins`, the example-query
tools, and capabilities — but is absent on
`get_protein_sequence/features/variants/diseases/cross_references/go_terms/map_identifiers`,
despite server instructions claiming "responses carry `_meta.next_commands`."

**M4 — Cross-reference values are full IRIs, not bare ids.** PDB comes back as
`http://rdf.wwpdb.org/pdb/2W3O` rather than `2W3O`. Every consumer wanting "the
PDB ids" must string-parse the IRI, inflating tokens across 80 databases.

#### 🟢 Low

- **L1** — Every response repeats the full `_meta` boilerplate (~150-char
  `recommended_citation`, endpoint URL, clinical flag). No `response_mode` knob.
- **L2** — `query_syntax_error` is a bare passthrough (`[400] Malformed SPARQL
  query.`) with no position or hint.
- **L3** — Non-canonical isoform returns `mass_da: null` while `length` is
  populated (inconsistent completeness).

### What works well

- **Error envelopes are excellent and the documented taxonomy is real.**
  `invalid_input`, `not_found`, `query_syntax_error` all surfaced with
  `{error_code, message, retryable, recovery_action, next_commands}`. The
  no-anchor `find_proteins` rejection is a model error response.
- **`run_sparql_query` is the standout** — ASK→boolean, SELECT→columns/rows,
  LIMIT auto-injection capped at 50 with a clear truncation+recovery block, and
  per-call `elapsed_ms`.
- **Discovery surface is strong** — `get_server_capabilities` plus 126
  searchable, fetchable, runnable example queries with chaining.
- **Input handling** — lowercase accession normalization works; taxon resolves
  by id, exact name, and fuzzy name; database/feature filters narrow correctly.

### Per-tool scorecard

| Tool | Works | Notes |
|---|---|---|
| get_server_capabilities | ✅ | Rich, single-call orientation |
| run_sparql_query | ✅✅ | Best-in-class: timing, LIMIT injection, truncation contract |
| search_example_queries / get_example_query | ✅ | Clean, good chaining |
| find_proteins | ✅ | Solid; exemplary no-anchor error |
| get_protein | ⚠️ | **C1: success on nonexistent accession** |
| get_protein_sequence | ✅ | Correct `not_found`; isoform mass null (L3) |
| get_protein_features | ⚠️ | **H4: `domain` filter misses FHA (`Domain_Extent`)** |
| get_protein_variants | ⚠️ | **H3: dead disease links, blank substitution; M1 silent truncation** |
| get_protein_diseases | ⚠️ | Works for real entries; count:0 ambiguous for nonexistent (M1) |
| get_protein_cross_references | ⚠️ | Works; full-IRI values (M4); overlaps map_identifiers (M2) |
| get_protein_go_terms | ❌ | **H1: aspect grouping entirely broken** |
| map_identifiers | ⚠️ | Filter works; redundant with cross_references (M2); IRIs (M4) |
| get_taxon | ⚠️ | **H2: wrong parent + unordered lineage**; name/fuzzy resolution good |

### Dimension ratings (1–10)

| Dimension | Score | Driver |
|---|---|---|
| Correctness / reliability | 4 | C1 + H1/H2/H3/H4 — a cluster of real bugs in the typed tools |
| Error handling | 7 | Envelopes excellent, but `get_protein`/annotation tools bypass `not_found` |
| Observability | 6 | `run_sparql_query` great; typed tools lack timing + truncation |
| Token efficiency | 6 | Full-IRI values, xref/map duplication, unpaginated GO, repeated boilerplate |
| Discoverability | 7 | Capabilities + examples strong; GO/feature filters mislead; chaining uneven |
| Speed | 8 | ~100–120 ms SPARQL; parallel-friendly |
| Composability | 7 | `next_commands` useful where present; stable ids; example→run path |
| Safety / governance | 9 | Consistent research-use notice, clinical flag, verbatim citation |
| **Overall** | **6** | Strong bones, great SPARQL layer, undermined by typed-tool data fidelity |

### Prioritized recommendations

1. **(C1)** Make `get_protein` and all annotation tools return `not_found` for
   nonexistent accessions — match `get_protein_sequence`/`get_taxon`. One
   consistent existence check at the entrypoint. Most important fix.
2. **(H1)** Fix GO `by_aspect` — populate BP/MF/CC from the GO aspect; today the
   bucket is always `unknown`.
3. **(H2)** Fix taxon hierarchy — return the immediate parent (one
   `rdfs:subClassOf` hop) and emit `lineage` ordered species→root.
4. **(H3)** Populate the variant `diseases` field, fix the blank-substitution
   extraction, and add the wild-type residue so HGVS-style notation is
   constructible.
5. **(H4)** Reconcile feature input/output vocabularies (`domain` ↔
   `Domain_Extent`) and warn when a valid filter matches zero of N features.
6. **(M1)** Extend the truncation contract to typed tools — add
   `total`/`truncated` to variants, GO, features; give GO a `limit`.
7. **(M2/M4)** Differentiate or merge `map_identifiers` vs `cross_references`,
   and return bare ids alongside IRIs.
8. **(M3)** Make observability uniform — `elapsed_ms` on every tool;
   `next_commands` everywhere, or stop advertising it as universal.

Highest payoff-per-effort remains recommendation **1**: a single existence
check closes the one bug that turns a typo into a silently-wrong research
answer.

---

## Appendix — Evidence highlights

- `get_protein("ZZZ999")` → `success: true`, empty body (C1).
- `get_protein_sequence("ZZZ999")` → `not_found` 404 (correct; proves C1 is an
  inconsistency, not an endpoint limitation).
- `get_protein_go_terms` on Q96T60 (21 terms) and P05067 (123 terms) → 100% of
  terms under `by_aspect.unknown` (H1).
- `get_taxon(9606)` → `parent_name: "Teleostomi"` (should be *Homo*); `lineage`
  unordered (H2).
- `get_protein_variants(Q96T60)` → all `diseases: []` despite "In MCSZ"/"In
  AOA4" descriptions; pos-408 `substitution: ""` (H3).
- `get_protein_features(Q96T60, ["domain"])` → 0 domains; FHA present as
  `Domain_Extent` in unfiltered output (H4).
- `run_sparql_query` unbounded SELECT → `limit_injected: true`,
  `truncated: {reason, recovery}`, `elapsed_ms: 122.3` (the model the typed
  tools should follow).

*Research use only; not for clinical decision support, diagnosis, treatment, or
patient management. Source: The UniProt Consortium, Nucleic Acids Res.
2025;53(D1):D609–D617. doi:10.1093/nar/gkae1010.*
