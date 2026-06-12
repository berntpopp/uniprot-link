# uniprot-link — MCP Quality Uplift Design Spec

**Date:** 2026-06-11
**Status:** Draft-for-build (autonomous goal directive)
**Author:** Claude (Fable 5) for bernt.popp@charite.de
**Source assessment:** `MCP-TEST-REPORT.md` (senior-tester evaluation, overall **6/10**)
**Target:** overall **> 9/10** — trustworthy typed layer, unified contracts, lean payloads

---

## 1. Problem statement

A senior-tester LLM exercised all 14 tools and scored the server **6/10**. The
foundation (capabilities discovery, provenance/safety, the SPARQL escape hatch)
is excellent, but the **typed convenience tools** — the layer most agents will
actually call — carry five correctness bugs plus two systemic contract
inconsistencies. The failure mode that matters most: the server hands an LLM
**confidently-wrong data with `success:true`**, which an agent cannot catch on
its own and will propagate as fact.

Per-dimension scores to lift:

| Dimension | Now | Target | Lever |
|---|--:|--:|---|
| Functional correctness | 5 | 9–10 | Fix 5 correctness bugs |
| Error handling / robustness | 5 | 9 | Unify not-found; reject writes |
| Token efficiency | 5 | 8–9 | `response_mode`, dedup, short ids, compact citation |
| Observability | 6 | 8–9 | `elapsed_ms` + `truncated` on typed tools |
| Composability / chaining | 6 | 9 | `next_commands` everywhere; no dead ends |
| Discoverability | 7 | 9 | Fuzzy example search; feature-vocab round-trip |
| Speed | 9 | 9 | Preserve (all fixes validated < 0.5 s) |
| Safety / provenance | 9 | 9 | Preserve (keep release pin + clinical flag) |
| Input / schema ergonomics | 8 | 9 | Echo accepted keys; typed `response_mode` |

---

## 2. Verified root-cause analysis

Every bug below was reproduced **against the live endpoint** (release 2026_01,
QLever) during spec research, and the proposed fix query was validated live. This
is the load-bearing section: the fixes are not guesses.

| # | Tool | Root cause (confirmed) | Validated fix (live timing) |
|---|---|---|---|
| 1 | `get_taxon` parent | UniProt asserts `rdfs:subClassOf` to the **entire 29-ancestor closure**; `taxon_details` joins it under `OPTIONAL` + `LIMIT 1`, so `shape_taxon` reads `data[0]` — an **arbitrary** ancestor (Teleostomi for 9606). | Depth-rank the closure with `COUNT(?between)`; **depth 0 = Homo (9605, Genus)** — the true direct parent. 98 ms. |
| 2 | `get_taxon` lineage | Same closure, surfaced as an **unordered** `GROUP_CONCAT`. | Same depth-ordered query yields lineage **perfectly ordered species→root**. |
| 3 | `get_protein_go_terms` | GO terms in this endpoint carry **no** `oboInOwl:hasOBONamespace` triple, so the `OPTIONAL { ?go oboInOwl:hasOBONamespace ?aspect }` never binds → all 21 terms bucket as `"unknown"`. | `subClassOf` **is** materialized to the 3 GO roots; map term→root: `GO_0008150`/`0003674`/`0005575` → BP/MF/CC. 340 ms, all terms bucketed correctly. |
| 4 | `get_protein_features` domain | `FEATURE_TYPES["domain"] = "Domain_Annotation"` (the **textual** annotation, no FALDO range). The positional, coordinate-bearing domain class is **`Domain_Extent_Annotation`** (e.g. P38398 BRCT 1/2). Filter never matches the ranged rows → 0 hits. | Map `"domain" → "Domain_Extent_Annotation"`; add reverse map so the returned `type` **round-trips** to the filter key. |
| 5 | `get_protein_variants` diseases | Natural-variant annotations link disease via **`skos:related → diseases/NNNN`**, not `up:disease`. The current `OPTIONAL { ?a up:disease … }` never matches → `diseases:[]` always, even when the comment says "In BC". | `skos:related` + `skos:prefLabel` returns "Breast cancer", "Breast-ovarian cancer, familial, 1". 306 ms. (Bonus: `rdfs:seeAlso → dbsnp/rsNNNN` is available for a dbSNP field.) |
| 6 | `get_protein` not-found | `protein_summary` is **all-`OPTIONAL`** with no required anchor; a WHERE of only OPTIONALs always returns **one all-unbound row**, so a bogus accession (`ZZZZZZ`) yields `success:true` with `{accession: ZZZZZZ}`. | Add required `uniprotkb:{base} a up:Protein .`. `EXISTS` check: real=true, bogus=false → 0 rows → `not_found`. |
| 7 | `run_sparql_query` writes | `INSERT DATA` has no `select`, so no LIMIT injected; the endpoint returns a non-JSON body; `response.json()` throws an unclassified error → **`internal_error`**. | Pre-classify the query operation; reject UPDATE forms with **`invalid_input`** ("read-only: SELECT/ASK/CONSTRUCT/DESCRIBE only") before the network call. |

Supporting evidence (live): `taxon:9606 rdfs:subClassOf ?parent` → **29 rows**;
the depth-0 minimal ancestor → **Homo / Genus**; `Domain_Extent_Annotation` rows
carry begin/end (BRCT 1 = 1642–1736, BRCT 2 = 1756–1855); variant `skos:related`
resolves to `diseases/2602` "Breast cancer"; `EXISTS{ uniprotkb:ZZZZZZ a
up:Protein }` = `false`.

---

## 3. Design principles

Grounded in MCP server best practices (errors must help the **agent** decide the
next step, not just flag failure; return only essential fields to preserve the
context window; **determinism over cleverness**):

1. **Correct-or-absent, never confidently-wrong.** A field is either right or
   omitted. No arbitrary-row picks (taxon), no silently-empty structured fields
   (variant diseases), no `success:true` for nonexistent entities.
2. **One error-handling rule for the whole server.** Nonexistent input →
   `not_found` everywhere. A read-only server rejects writes with
   `invalid_input`. An agent writes the rule once.
3. **Honor advertised contracts.** If the instructions say responses carry
   `_meta.next_commands`, every tool carries it. If a filter vocabulary is
   advertised, the returned values use the **same** vocabulary.
4. **Lean by default, complete on request.** A `response_mode` knob
   (`minimal | compact | standard | full`), matching sibling servers
   (gnomad-link, hnf1b, sysndd). Default trims tokens; `full` restores raw IRIs,
   full sequence, and the full citation.
5. **Preserve the strengths.** Speed (all fixes < 0.5 s), the SPARQL escape
   hatch, and provenance/safety (release pin + `unsafe_for_clinical_use`) are
   untouched or strengthened.

---

## 4. Fixes — organized by priority

Each fix lists the **code site**, the **validated change**, the **contract
change**, and the **test**.

### Wave 1 — P0 correctness (an agent states these as fact)

#### 4.1 `get_taxon`: correct direct parent + ordered lineage

- **Sites:** `queries.py: taxon_details` (rewrite), `shaping.py: shape_taxon`
  (rewrite), `sparql_service.py: get_taxon`.
- **Change:** Replace the closure-under-OPTIONAL query with a **depth-ranked
  ancestor query** (validated, 98 ms):

  ```sparql
  SELECT ?ancestor ?name ?rank (COUNT(DISTINCT ?between) AS ?depth)
  WHERE {
    taxon:{tid} rdfs:subClassOf ?ancestor .
    ?ancestor up:scientificName ?name .
    OPTIONAL { ?ancestor up:rank ?rank }
    OPTIONAL { taxon:{tid} rdfs:subClassOf ?between .
               ?between rdfs:subClassOf ?ancestor . FILTER(?between != ?ancestor) }
  }
  GROUP BY ?ancestor ?name ?rank
  ORDER BY ?depth
  ```

  The taxon's own `scientificName`/`commonName`/`rank` stay in a small core
  query. The ancestor query runs **always** (it yields the correct parent at
  `depth = 0`); the full ordered list is surfaced as `lineage` **only when
  `include_lineage=True`**. Run core + ancestors concurrently (`asyncio.gather`)
  to keep latency ~one round trip.
- **Contract:** `parent_taxon_id`/`parent_name`/`parent_rank` come from the
  depth-0 row. `lineage` becomes an **ordered array of `{taxon_id,
  scientific_name, rank}`** (species→root) — chainable and unambiguous (was an
  unordered string-split array). Taxa with no parent (root) → parent omitted.
- **Test:** unit test feeds a canned 3-ancestor closure (depths 0/1/2) and
  asserts parent = depth-0 and lineage order; integration test asserts
  `get_taxon(9606).parent_taxon_id == "9605"` and `lineage[0]` = Homo.

#### 4.2 `get_protein_go_terms`: real aspect grouping

- **Sites:** `queries.py: protein_go_terms`, `shaping.py: shape_go_terms`,
  `constants.py` (GO root → aspect map).
- **Change:** Replace the `hasOBONamespace` OPTIONAL with a root-class join
  (validated, all terms bucketed):

  ```sparql
  OPTIONAL { ?go rdfs:subClassOf ?aspectRoot .
             FILTER(?aspectRoot IN (obo:GO_0008150, obo:GO_0003674, obo:GO_0005575)) }
  ```

  `shape_go_terms` maps the root IRI → bucket name
  (`biological_process`/`molecular_function`/`cellular_component`); terms that
  reach no root fall back to `"unknown"`.
- **Contract:** `by_aspect` now contains the three real buckets. (Tool
  description already promises this — it becomes true.)
- **Test:** unit test with canned rows (one per aspect root) asserts three
  buckets; integration test asserts P38398 has non-empty BP/MF/CC and no
  `"unknown"` bucket.

#### 4.3 `get_protein_features`: domain filter + vocabulary round-trip

- **Sites:** `constants.py: FEATURE_TYPES`, `shaping.py: shape_features`,
  `sparql_service.py: get_features`, `queries.py: protein_features`.
- **Change:**
  - Remap `"domain" → "Domain_Extent_Annotation"` (the FALDO-ranged class).
    Keep `Domain_Annotation`-style textual classes out of the positional tool.
  - Build a **reverse map** (class local-name → friendly key) from
    `FEATURE_TYPES`. `shape_features` emits the **friendly key**
    (e.g. `"domain"`), not the raw `Domain_Extent` — so returned `type` values
    are valid filter inputs (round-trip). Unknown classes fall back to a
    slugified local-name.
  - On a filter that matches **zero** rows, the service attaches a
    `filter_hint` listing the accepted feature-type keys (from capabilities) so
    the agent self-corrects instead of concluding "no domains".
- **Contract:** `feature_types=["domain"]` returns the BRCT extents; returned
  `type` round-trips to the filter vocabulary; zero-match echoes accepted keys.
- **Test:** unit test asserts reverse-map round-trip and the zero-match hint;
  integration test asserts `get_protein_features("P38398",
  ["domain"]).count >= 2`.

#### 4.4 `get_protein_variants`: populate structured diseases

- **Sites:** `queries.py: protein_variants`, `shaping.py: shape_variants`.
- **Change:** Replace `OPTIONAL { ?a up:disease ?d . ?d skos:prefLabel ?disease }`
  with the **correct linkage** (validated, 306 ms):

  ```sparql
  OPTIONAL { ?a skos:related ?diseaseIri . ?diseaseIri skos:prefLabel ?disease }
  OPTIONAL { ?a rdfs:seeAlso ?dbsnp . FILTER(STRSTARTS(STR(?dbsnp),
             "http://purl.uniprot.org/dbsnp/")) }
  ```

  `shape_variants` keeps its merge-by-`(begin,end,substitution)` logic
  (multiple `skos:related` rows per variant fold into the `diseases` list) and
  adds an optional `dbsnp` field.
- **Contract:** `diseases` is **populated** (`["Breast cancer", …]`) and
  consistent with `description`. A non-functional field becomes a functional
  one. New optional `dbsnp` rsID.
- **Test:** unit test feeds two canned rows (same position, two diseases) and
  asserts they merge into one variant with `len(diseases)==2`; integration test
  asserts P38398 has ≥1 variant with a non-empty `diseases`.

#### 4.5 `get_protein`: existence anchor → `not_found`

- **Site:** `queries.py: protein_summary` (add one required triple).
- **Change:** Add `uniprotkb:{base} a up:Protein .` as the first **required**
  pattern. Nonexistent accession → 0 rows → `shape_protein_summary` returns
  `None` → existing `NotFoundError` path fires.
- **Contract:** Bogus accession returns the `not_found` envelope (with a
  `find_proteins` fallback `next_command`) instead of `success:true` + empty
  body. **This is the highest-leverage fix** (report §"Highest-leverage fix").
- **Test:** unit test with empty canned result asserts `NotFoundError`;
  integration test asserts `get_protein("ZZZZZZ").error_code == "not_found"`.

### Wave 2 — P1 robustness & contract

#### 4.6 Unify not-found across all `get_protein*` tools

- **Sites:** `sparql_service.py` (shared `require_entry`), `queries.py`
  (`entry_exists_ask`).
- **Change:** Add a cached `ASK { uniprotkb:{base} a up:Protein }` helper.
  `get_features`/`get_variants`/`get_diseases`/`get_go_terms`/
  `get_cross_references`/`map_identifiers` run the ASK **concurrently** with
  their data SELECT (`asyncio.gather`); if the entry does not exist, raise
  `NotFoundError`. The TTL cache (already present) makes repeat calls free, and
  concurrency keeps latency ~one round trip. `get_protein`/`get_sequence`
  already 404 via required joins (4.5 closes `get_protein`).
- **Contract:** One rule: nonexistent entity → `not_found` on **every**
  `get_protein*` tool, matching `get_taxon`.
- **Test:** parametrized unit test across all annotation methods asserts
  `NotFoundError` when the ASK route returns `false`.

#### 4.7 `run_sparql_query`: reject writes as `invalid_input`

- **Sites:** `queries.py` (`classify_sparql_operation`),
  `sparql_service.py: run_query`.
- **Change:** Strip comments + `PREFIX`/`BASE` declarations, read the first
  significant keyword. Allow `SELECT|ASK|CONSTRUCT|DESCRIBE`; reject
  `INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|ADD|MOVE|COPY|WITH…(DELETE|INSERT)` with
  `InvalidInputError("read-only: SELECT/ASK/CONSTRUCT/DESCRIBE only")`.
  Unrecognized leading tokens pass through (endpoint 400 → `query_syntax_error`,
  unchanged). Detection keys on the **leading** keyword, never substring-anywhere
  (so a SELECT with the literal `"insert"` is unaffected).
- **Contract:** Writes → clean `invalid_input` + `reformulate_input`, not
  `internal_error`. Matches the read-only annotation already on the tool.
- **Test:** unit test asserts `INSERT DATA {…}` → `invalid_input` and that a
  SELECT containing `"insert"` in a literal still runs.

#### 4.8 `get_protein_variants`: stop hiding disease variants in the tail

- **Sites:** `queries.py: protein_variants`, `sparql_service.py: get_variants`,
  `proteins.py` (new param), `shaping.py: shape_variants`.
- **Change:**
  - Add `disease_associated_only: bool = False`. When true, the
    `skos:related ?diseaseIri` join becomes **required** — returns only
    disease-linked variants (typically few; fits any limit).
  - When the LIMIT is reached, attach a `truncated` block (like
    `run_sparql_query`) with a recovery hint (raise `limit` or set
    `disease_associated_only`).
  - Within the returned set, `shape_variants` sorts **disease-associated first**,
    then by position — so truncated output still surfaces the clinically salient
    rows.
- **Contract:** An agent asking for disease variants can get them all; partial
  results are flagged, never silent.
- **Test:** unit test asserts disease-first ordering and the `truncated` block at
  the limit; integration test asserts `disease_associated_only=True` returns only
  variants with non-empty `diseases`.

#### 4.9 Honor the `next_commands` contract on every tool

- **Sites:** `next_commands.py` (new builders), `proteins.py`, `taxonomy.py`.
- **Change:** Add chaining to the tools that currently omit it —
  `get_protein_sequence`, `_features`, `_variants`, `_diseases`,
  `_cross_references`, `_go_terms`, `map_identifiers`. Each chains back to
  **entry context** (e.g. features → variants → diseases → get_protein), never
  into dead ends. `find_proteins` with zero hits suggests `get_taxon` /
  refinement rather than a generic example search.
- **Contract:** The instruction "responses carry `_meta.next_commands`" becomes
  universally true (or the instruction is softened — see §7). Error envelopes
  already carry a fallback; keep it.
- **Test:** unit test asserts each tool's success payload includes
  `_meta.next_commands` with valid `{tool, arguments}` shapes.

### Wave 3 — P2 efficiency & polish

#### 4.10 `response_mode` (minimal | compact | standard | full)

- **Sites:** new `shaping.py` projection helpers; `proteins.py`/`query.py`
  params; `service` threading; `capabilities.py` docs.
- **Change:** Add a shared `response_mode` enum to the data-returning tools.
  - `minimal` — ids/counts only (e.g. accession + counts; GO ids without labels).
  - `compact` — **default**: short ids, labels, no large blobs, no full
    sequence, compact citation.
  - `standard` — adds descriptions/comments and the canonical sequence.
  - `full` — raw IRIs, all isoform sequences, full citation text.
  Implemented as a post-shaping projection so query logic stays single-path
  (determinism). Default **`compact`** maximizes the token win the report asks
  for while `full` preserves today's verbosity for callers who want it.
- **Contract:** Opt-in verbosity; defaults are lean. Documented in capabilities
  and the server instructions.
- **Test:** unit tests assert field presence per mode for `get_protein` and
  `get_protein_sequence`.

#### 4.11 Stop duplicating the canonical sequence; isoform polish

- **Site:** `sparql_service.py: get_sequence`, `shaping.py: shape_sequences`.
- **Change:** `canonical` holds the canonical isoform; `isoforms` lists the
  **additional** (non-canonical) isoforms only — no more `canonical` ==
  `isoforms[0]` duplication. `isoform_count` stays. Sequence strings appear only
  in `standard`/`full` modes. (Isoform-mass computation is **out of scope** —
  YAGNI; surface UniProt's mass where present, else `null`.)
- **Test:** unit test asserts no duplicate sequence string and correct
  `isoform_count`.

#### 4.12 Short ids by default for xrefs / mapping

- **Site:** `shaping.py: shape_cross_references`, `service.map_identifiers`.
- **Change:** In `minimal`/`compact`/`standard`, return short ids
  (`local_name` of the xref IRI, grouped by db); `full` returns the raw IRIs.
- **Test:** unit test asserts short ids in compact, IRIs in full.

#### 4.13 Compact, non-redundant provenance

- **Site:** `envelope.py: _provenance_meta` / `_BASE_META`.
- **Change:** Keep `unsafe_for_clinical_use`, `uniprot_release`, `endpoint`, and
  a **short** `citation: "doi:10.1093/nar/gkae1010"` inline on every response;
  move the full citation text to `capabilities` and the `uniprot://citation`
  resource (and `full` mode). Saves ~140 chars/call **without** weakening
  grounding (release pin + clinical flag remain on every call).
- **Test:** unit test asserts the short citation inline and full text in
  capabilities.

#### 4.14 Propagate `elapsed_ms` + `truncated` to typed tools

- **Site:** `sparql_service.py: _select` (return elapsed + cached flag),
  typed methods (thread into `_meta`).
- **Change:** `_select` returns `(json, elapsed_ms, cached)`; typed tools add
  `_meta.elapsed_ms` and `_meta.cached`. Add `truncated` to `get_features`
  (LIMIT 1000) and `get_variants` when the cap is hit.
- **Test:** unit test asserts `_meta.elapsed_ms` present; `truncated` appears at
  the limit.

#### 4.15 Fuzzy example search; surface MIM

- **Sites:** `queries.py: search_example_queries`, `queries.py: protein_diseases`
  + `shaping.py: shape_diseases`.
- **Change:**
  - Tokenize the search text into words; match **any** token across
    `rdfs:comment` + `schema:keywords` (OR of `CONTAINS`), so "protein domain
    architecture" returns hits. (Optional: rank by token-match count in Python.)
  - Add the MIM cross-reference to the disease query
    (`?disease rdfs:seeAlso ?mim` filtered to the MIM namespace) so
    `shape_diseases`' already-present `mim` field is populated.
- **Test:** unit test asserts multi-word query builds an OR filter; integration
  test asserts a multi-word example search returns > 0 and that a disease row
  carries a `mim`.

---

## 5. Response-contract & schema summary

Net external changes an agent will observe:

- **New, correct fields:** taxon `parent_rank`, ordered `lineage[]` objects;
  GO `by_aspect` real buckets; variant `diseases[]` populated + `dbsnp`;
  feature `type` in filter vocabulary; disease `mim`.
- **New optional inputs:** `response_mode` (data tools), `disease_associated_only`
  (variants).
- **Behavior changes:** bogus accessions → `not_found`; SPARQL writes →
  `invalid_input`; `next_commands` on all tools; `elapsed_ms`/`truncated` on
  typed tools; default payloads leaner (`compact`).
- **Breaking-ish:** `lineage` shape (string-array → object-array); sequence
  `isoforms` excludes the canonical; xref/mapping ids shortened by default;
  inline citation shortened. Mitigated by `response_mode=full` restoring verbose
  output, and by this being a pre-1.0 (`v0.1.0`) server. Bump to **v0.2.0**.

---

## 6. Architecture & file-size impact

Hard cap: **600 lines/module** (`make lint-loc`, in `make ci-local`).

| Module | Now | Est. after | Risk |
|---|--:|--:|---|
| `services/queries.py` | 443 | ~510–540 | **tight** |
| `services/shaping.py` | 272 | ~370 | ok |
| `services/sparql_service.py` | 263 | ~340 | ok |
| `mcp/tools/proteins.py` | 282 | ~360 | ok |
| `mcp/next_commands.py` | 37 | ~75 | ok |
| `services/constants.py` | 227 | ~250 | ok |

**Contingency (only if `queries.py` crosses ~560):** extract the taxonomy +
example-catalog builders + `classify_sparql_operation` into
`services/queries_catalog.py`, leaving `queries.py` focused on protein/feature
builders and validation. This is a clean responsibility split, not a refactor of
behavior. Decide by running `make lint-loc` after Wave 1–2.

---

## 7. Documentation & capabilities updates

- `capabilities.py`: bump version; add `response_modes`, corrected
  `feature_types`, `default_response_mode`, a `not_found` contract note, and a
  `read_only` note for `run_sparql_query`.
- Server `instructions` (the `_meta` instruction string): make `next_commands`
  universality accurate; document `response_mode`; note the read-only guarantee.
- Tool descriptions: `get_protein_variants` (diseases now populated +
  `disease_associated_only`), `get_protein_features` (domain = positional
  extents; accepted keys), `get_taxon` (direct parent + ordered lineage).
- `CHANGELOG.md`: v0.2.0 entry enumerating the fixes.

---

## 8. Testing strategy

- **Unit (default path, mocked via `respx`/`FakeSparqlClient`):** every fix gets
  a shaping/query-builder test using `make_select_json` canned bodies. No live
  calls. This is where correctness of shaping (aspect buckets, depth-0 parent,
  disease merge, reverse-map round-trip, not-found) is locked.
- **Integration (`@pytest.mark.integration`, live endpoint):** assert the
  high-value end-to-end facts — `get_taxon(9606).parent == 9605`, GO buckets
  non-empty, `features(["domain"]) ≥ 2`, a variant with populated `diseases`,
  `get_protein("ZZZZZZ") → not_found`, `INSERT → invalid_input`. Kept out of the
  default CI path per AGENTS.md.
- **`research/verify_queries.py`:** extend with the new/changed query builders
  per CLAUDE.md (re-validate QLever timing after touching `queries.py`).
- **Gate:** `make ci-local` (format, lint, lint-loc, mypy strict, unit tests)
  must pass before handoff.

---

## 9. Out of scope (YAGNI)

- Isoform-mass computation from sequence (error-prone; surface UniProt's value).
- Splitting the 14-tool server into multiple servers (14 is within the
  "reasonable" 8–15 band; cohesive domain).
- MCP `outputSchema`/`structuredContent` migration (larger, separate effort;
  note as a future enhancement).
- New tools/data sources (federation, proteomes, pathways) — not regressions.

---

## 10. Success criteria

1. All five P0 correctness bugs fixed and proven by integration tests against the
   live endpoint.
2. One uniform not-found contract across every `get_protein*` and `get_taxon`;
   writes rejected as `invalid_input`.
3. `next_commands` present on every tool; `elapsed_ms`/`truncated` on typed
   tools.
4. Default payloads measurably leaner (short ids, no duplicated sequence, compact
   citation) with `response_mode=full` restoring verbose output.
5. `make ci-local` green; `lint-loc` under cap (with the contingency split if
   needed); provenance/safety unchanged.
6. A re-run of the tester rubric should land **correctness 9–10, error-handling
   9, token-efficiency 8–9, composability 9, observability 8–9** → overall
   **> 9/10**.

---

## 11. Sources

- MCP best practices (agent-centric errors; return only essential fields;
  determinism over cleverness): [philschmid](https://www.philschmid.de/mcp-best-practices),
  [Docker](https://www.docker.com/blog/mcp-server-best-practices/),
  [awslabs/mcp DESIGN_GUIDELINES](https://github.com/awslabs/mcp/blob/main/DESIGN_GUIDELINES.md).
- UniProt RDF schema (core ontology, SKOS-based annotation modeling):
  [UniProt RDF schema](https://purl.uniprot.org/html/index-en.html).
- All bug reproductions and fix validations: **live** `https://sparql.uniprot.org/sparql`
  (release 2026_01), executed during spec research on 2026-06-11.
