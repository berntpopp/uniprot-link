# uniprot-link — Assessment Review + v0.3.0 Uplift Spec

**Date:** 2026-06-12

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

**Author:** Claude (Fable 5) for bernt.popp@charite.de
**Reviews:** `uniprot-link-mcp-assessment.md` (LLM-consumer + senior-tester, scored 6–7/10)
**Method:** Every claim re-verified against the **live** endpoint (release 2026_01,
QLever) *and* against the on-disk source. SPARQL for each proposed change was run
live before it was written down.
**Target:** deployed server **> 9/10**.

---

## 0. TL;DR — the assessment is real, but it measured the wrong build

The assessment is careful and its reproductions are accurate. But it tested the
**deployed `v0.1.0` server**, and the repository on disk is already **`v0.2.0`**,
a correctness milestone that **already fixes 9 of the 12 findings** (C1, H1, H2,
H3-disease, H4, M1, M3, M4, L1). `v0.2.0` ships with 81 passing unit tests and a
full CHANGELOG; it is simply **not deployed**.

Proof (collected this session):

| Probe | Deployed `v0.1.0` (live MCP tool) | On-disk `v0.2.0` query (run via `run_sparql_query`) |
|---|---|---|
| `get_server_capabilities().server_version` | `"0.1.0"`, no `response_modes`/`read_only` | `__version__ == "0.2.0"`, capabilities advertise both |
| `get_protein("ZZZ999")` | `success:true`, empty body (**C1**) | `protein_summary` now requires `a up:Protein` → `NotFoundError` |
| `get_protein_go_terms` aspects | 100% `unknown` (**H1**) | single-hop `subClassOf`→roots buckets **all 123** P05067 terms (361 ms) |
| `get_taxon(9606).parent` | `Teleostomi` (**H2**) | depth-ranked query → **Homo / 9605** at depth 0 (303 ms) |
| variant `diseases` | `[]` always (**H3**) | `skos:related`→`prefLabel` → "Microcephaly, seizures..." (209 ms) |
| `features(["domain"])` | 0 hits (**H4**) | `domain→Domain_Extent_Annotation` matches the FHA extent (6–110) |

**The single highest-leverage action is not a code change — it is to deploy
`v0.2.0` and prove it against the live endpoint.** That alone lifts the deployed
server from ~6/10 to ~9/10. This spec then defines a small, validated **`v0.3.0`
delta** that closes the genuine residual gaps and clears 9 comfortably, plus a
**systemic guard** so a stale deployment can never again silently score the
product down.

---

## 1. Finding-by-finding triage (verified)

Legend: ✅ fixed in on-disk `v0.2.0` (deploy to realize) · 🔶 partially addressed,
delta needed · ⬜ open · ❌ not feasible as written (data-model reason).

| # | Finding | Status | Notes / evidence |
|---|---|---|---|
| **C1** | `get_protein` `success:true` on nonexistent | ✅ | `protein_summary` now has required `uniprotkb:{base} a up:Protein .`; `shape_protein_summary→None`→`NotFoundError`. |
| **H1** | GO aspect all `unknown` | ✅ | GO `subClassOf` closure **is materialized** (deep terms e.g. `GO:0006303` carry a direct edge to `GO_0008150`). Single-hop `subClassOf`→3 roots is correct **and** fast (361 ms / 123 terms). *Note: `subClassOf*` (transitive path) **times out** — keep the single hop.* |
| **H2** | taxon wrong parent + unordered lineage | ✅ | `rdfs:subClassOf` returns the **full 29-ancestor closure**; depth-rank by `COUNT(?between)` → depth 0 = direct parent. Verified Homo/9605, lineage ordered species→root. |
| **H3** | variant disease links dead; blank substitution; no wild-type | 🔶 | `diseases` + `dbsnp` fixed in `v0.2.0`. **Still open:** no `wild_type` residue (so `R176F`-style notation impossible) and blank `substitution` (e.g. AOA4 p.408) is surfaced as `""` with no signal. → **`v0.3.0` D1.** |
| **H4** | `domain` filter drops FHA | ✅ | `FEATURE_TYPES["domain"]="Domain_Extent_Annotation"` + `filter_hint` on zero match. Live: FHA is `Domain_Extent_Annotation` 6–110. |
| **M1** | silent truncation; `count:0` ambiguous | ✅ | `truncated` block on variants/find; `require_entry` makes nonexistent → `not_found` on every annotation tool. |
| **M2** | `map_identifiers` ≈ `cross_references` | ⬜ | Still a near-duplicate: `map_identifiers` = `get_cross_references` + a `mapped_databases` name list. → **`v0.3.0` D2.** |
| **M3** | observability/chaining uneven | ✅ | `elapsed_ms`/`cached` via `qmeta` on every typed payload; `next_commands` via `after_entry_subresource` everywhere. |
| **M4** | full-IRI xref values | ✅ | `shape_cross_references(short=True)` default → local ids; `full` restores IRIs. |
| **L1** | repeated boilerplate; no `response_mode` | ✅ | `_BASE_META.citation = "doi:..."` (short); `response_mode` on protein/sequence/xref/map. |
| **L2** | bare `query_syntax_error` | 🔶 | Disk client already surfaces `response.text[:240]`; still lacks a recovery `next_command`. → **`v0.3.0` D3** (small). |
| **L3** | isoform `mass_da: null` | ❌ | Data limitation — UniProt does not assert `up:mass` on every isoform. Out of scope (correctly noted YAGNI in the prior spec). |
| **P1 #6** | enrich features with evidence + InterPro/Pfam xref | ❌ | **Not in the RDF.** A `Domain_Extent_Annotation` carries only `up:range`, `rdf:type`, `rdfs:comment` (verified on Q96T60 FHA: 3 triples, no evidence, no xref). InterPro/Pfam are **entry-level** `rdfs:seeAlso`, not per-feature. Reframed below as an optional, clearly-labeled join, not "evidence on the feature." |

**Net:** deploy `v0.2.0` → C1, H1, H2, H4, M1, M3, M4, L1 and the disease half of
H3 are all resolved. Remaining true work: **D1 (variant wild-type/notation), D2
(map_identifiers), D3 (syntax-error hint), D4 (deploy-freshness guard)**.

---

## 2. Root-cause of the *meta*-failure: deployment drift

The reason a 6/10 server was re-rated 6–7/10 after a 15-fix milestone is that the
**running process lagged the source with no visible signal**. `get_server_capabilities`
*did* report `server_version: 0.1.0`, but nothing forced anyone (human or agent) to
compare it against the shipped version. This is the failure to design out, because
it is the one that silently negates all other work.

**Principle for `v0.3.0`:** *the running server must make its own staleness
observable and CI must refuse to call a release "shipped" until the deployed
`server_version` matches the tag.*

---

## 3. The `v0.3.0` delta — design

Every change below was validated live this session. Timings are p50 single-call.

### D1 — `get_protein_variants`: wild-type residue + constructible notation

**Why:** UniProt stores only the **variant** residue in `up:substitution` (and it
is empty for non-substitution variants, e.g. AOA4 p.408). An agent cannot form
`L176F`-style notation, and a blank `substitution` reads as missing data rather
than "not a simple substitution." HGVS lists the **wild-type residue first**, so
the wild-type is the missing half.

**Validated approach:** the canonical sequence is in the graph; index it with
`SUBSTR`. This scales — on TP53 (`P04637`, the most variant-dense human entry) the
join returns **1,363 rows in 404 ms**.

```sparql
# add to protein_variants(...) body
isoform:{base}-1 rdf:value ?seq .
...
?r faldo:begin ?b . ?b faldo:position ?begin .
?r faldo:end   ?e . ?e faldo:position ?end .
BIND(SUBSTR(?seq, ?begin, 1 + ?end - ?begin) AS ?wildType)
```

**Contract change** (per variant):
- add `wild_type` (string, the reference residue(s) at the range; e.g. `"L"`).
- keep `substitution` (the variant residue; may be `""`).
- add `variant_type`: `"substitution"` when `substitution` is a non-empty single
  residue and `begin == end`; otherwise `"other"` (deletion/insertion/complex —
  this is what a blank `substitution` *means*, made explicit).
- add `notation`: `f"{wild_type}{begin}{substitution}"` (e.g. `"L176F"`) **only**
  when `variant_type == "substitution"`; omitted otherwise (never emit a
  misleading `"T408"`).

`shape_variants` keeps its merge-by-`(begin,end,substitution)` and disease-first
sort. `wild_type`/`variant_type`/`notation` are derived during shaping from the new
`?wildType` column.

**Edge cases handled:** empty `substitution` (→ `variant_type:"other"`, no
`notation`); multi-residue range (`wild_type` is the full slice, still
`variant_type:"other"`); `wild_type` may be absent if the isoform sequence join is
empty (defensive — omit the field, never crash).

### D2 — `map_identifiers`: make it genuinely the *focused* id-mapping view

**Why (M2):** today `map_identifiers(acc)` returns the same ~80-database, ~115-id
`by_database` block as `get_protein_cross_references(acc)` plus a `mapped_databases`
name list — not "focused" by default, just heavier.

**Design:** `map_identifiers` is an **id-mapping** tool (UniProt → other primary
DBs), not a full xref dump. Default it to the curated, mapping-relevant set already
in `constants.COMMON_XREF_DATABASES` (PDB, AlphaFoldDB, Ensembl, RefSeq, GeneID,
KEGG, HGNC, MIM, Reactome, STRING, InterPro, Pfam, …) when the caller passes no
`databases`. Output stays the grouped short-id shape; add `requested_databases`
(the effective filter) and keep `mapped_databases`. Callers wanting the exhaustive
list use `get_protein_cross_references` (unchanged). Update both tool descriptions
to state the division of labor.

**Validated:** restricting `protein_cross_references` to a `VALUES ?db {…}` set is
already supported by the existing builder (the `databases` path) and returns in
~100 ms; D2 is wiring the default, not new SPARQL.

### D3 — `run_sparql_query`: actionable `query_syntax_error`

**Why (L2):** the disk client already surfaces the endpoint's 400 body
(`response.text[:240]`), but the envelope offers no next step. Add a fallback
`next_command` so a stuck agent has a route: re-seed from a working example.

**Design:** in `query.py`'s `McpErrorContext` for `run_sparql_query`, set
`fallback=cmd("search_example_queries", text="")` (or a `get_example_query` hint).
No SPARQL change. Keep the endpoint detail message verbatim.

### D4 — deployment-freshness guard (the systemic fix)

**Why:** §2 — make staleness self-evident and CI-enforced.

**Design (three small, independent pieces):**
1. **Build stamp in capabilities.** Add `build` to `build_capabilities()`:
   `{"version": __version__, "git_sha": <env UNIPROT_LINK_GIT_SHA or "unknown">,
   "built_at": <env UNIPROT_LINK_BUILT_AT or null>}`. Surfaced on
   `get_server_capabilities` and `/health`.
2. **`/health` reports the version.** Extend the FastAPI `/health` payload with
   `server_version` and `git_sha` so a deploy check is a single GET.
3. **Release gate (doc + script).** A `scripts/check_deployed_version.py` that GETs
   the deployed `/health` (or `uniprot://capabilities`) and exits non-zero if
   `server_version != __version__`. Document a redeploy runbook in
   `docs/development.md` ("a release is not done until `check_deployed_version`
   passes against the running endpoint").

This does not require a code change to fix a data bug; it ensures the *next*
fix-milestone cannot be silently negated by a stale process.

---

## 4. Explicitly out of scope (with reasons)

- **Feature-level evidence / InterPro / Pfam on domains (P1 #6).** Not present in
  the RDF (verified). Reframed only if wanted: a separate, clearly-labeled
  `get_protein_cross_references(acc, ["InterPro","Pfam","PROSITE"])` is the honest
  way to get domain-family ids; do **not** imply they annotate a specific
  `Domain_Extent`.
- **Isoform mass backfill (L3).** UniProt data gap; computing mass from sequence is
  error-prone (PTMs, non-standard residues). Surface UniProt's value or `null`.
- **MCP structured output (`outputSchema` / `structuredContent`).** Genuinely
  current best practice (2025-06-18 MCP spec) and worth doing — but a larger,
  schema-per-tool effort that is **not required to clear 9/10**. Recommended as a
  separate **`v0.4.0`** milestone (see §6).

---

## 5. Success criteria

1. Deployed `get_server_capabilities().server_version == "0.2.0"` (then `0.3.0`),
   with `read_only`/`response_modes`/`not_found_contract` present.
2. `make test-integration` green against the live endpoint — the P0/P1 fixes are
   *proven* live, not just unit-mocked: `get_taxon(9606).parent_taxon_id=="9605"`,
   GO buckets non-empty + no `unknown`, `features("P38398",["domain"]).count>=2`,
   a variant with non-empty `diseases`, `get_protein("ZZZ999")→not_found`,
   `INSERT…→invalid_input`.
3. `get_protein_variants` returns `wild_type` + `notation` for simple substitutions
   and `variant_type:"other"` (no misleading notation) for the rest.
4. `map_identifiers` default payload is materially smaller than
   `get_protein_cross_references` and documents the difference.
5. `get_server_capabilities` carries a `build` stamp; `/health` reports the
   version; `scripts/check_deployed_version.py` exists and gates release.
6. `make ci-local` green; `make lint-loc` under the 600-line cap; provenance/safety
   unchanged. A re-run of the tester rubric lands **correctness 9–10, error 9,
   token 8–9, observability 9, composability 9** → **> 9/10**.

---

## 6. Forward look (v0.4.0, not now)

- **Structured output:** declare `outputSchema` per typed tool and return
  `structuredContent` (plus the serialized JSON `TextContent` for back-compat), per
  the 2025-06-18 MCP spec. Highest future ergonomics win; design as its own spec.
- **Capabilities content-hash** (mirroring sibling servers like hnf1b's
  `capabilities_version`) so warm agents skip re-fetch when unchanged.

---

## 7. Sources

- MCP 2025-06-18 spec — structured tool output (`outputSchema`/`structuredContent`),
  typed/discoverable tools, documented failure modes:
  [modelcontextprotocol.io/specification/2025-06-18/server/tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools),
  [The New Stack — 15 best practices](https://thenewstack.io/15-best-practices-for-building-mcp-servers-in-production/).
- HGVS protein substitution (wild-type residue first, e.g. `Gly56Ala`):
  [hgvs-nomenclature.org](https://hgvs-nomenclature.org/stable/recommendations/protein/substitution/).
- UniProt RDF / SPARQL model:
  [uniprot.org/help/sparql](https://www.uniprot.org/help/sparql),
  [sib-swiss/sparql-training](https://github.com/sib-swiss/sparql-training/tree/master/uniprot).
- All bug reproductions and fix validations: **live** `https://sparql.uniprot.org/sparql`
  (release 2026_01), this session.
