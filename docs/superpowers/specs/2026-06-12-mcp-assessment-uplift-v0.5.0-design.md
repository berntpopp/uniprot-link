# uniprot-link v0.5.0 — Assessment Uplift (8.5/8.7 → >9.5) Design

**Date:** 2026-06-12

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

**Author:** MCP engineering pass (Claude Fable 5)
**Target version:** 0.5.0
**Source assessment:** `docs/mcp-assessment-v0.4.0.md`
**Status:** Design — proceeding to implementation plan

---

## 1. Problem

The v0.4.0 assessment (an LLM consumer driving the live tool surface) scores the
server **8.5/10** (consumer experience) and **8.7/10** (tool-by-tool). The
architecture is already reference-quality: structured errors, per-call
observability, `next_commands` chaining on success *and* error, typed output
schemas, and a 126-query example catalogue. The remaining gap is a short,
concrete punch-list — verified live against build `5da02e8` on 2026-06-12:

| # | Finding | Live evidence (this build) |
|---|---------|----------------------------|
| F1 | Per-call `_meta` repeats static provenance | Every response carries `unsafe_for_clinical_use` + `uniprot_release` + `citation` (~30–40 tok/call) |
| F2 | No advertised latency; cold scans surprise callers | Capabilities has no latency hint; `find_proteins` cold 5–10 s, `get_taxon` by-name ~11 s |
| F3 | `get_taxon` by-name ~40× slower than by-id | Name path is a QLever FILTER scan; id path is a bound anchor |
| F4 | `domain`/`region` trap | `get_protein_features(Q96T60, ['domain'])` → only FHA (count=1); catalytic/kinase domains are typed `region`. The empty-only `filter_hint` never fires |
| F5 | Unhelpful error recovery for a malformed accession | `get_protein("Q96T60XYZ")` → `invalid_input`, but `next_commands` suggests `find_proteins(gene="Q96T60XYZ")` |
| F6 | Empty string for an inapplicable field | T408 variant → `"substitution":""`, `variant_type:"other"`, no notation |
| F7 | Non-canonical isoform `mass_da` is null | `Q96T60-2` length 482, `mass_da:null` |
| F8 | Opaque/undocumented ordering in `find_proteins` | Reviewed-first is documented; the within-segment tiebreak (mnemonic) is not, and there is no final unique tiebreak |

These are refinements, not repairs — nothing is broken, and every datum is
correct.

## 2. Goal & success criteria

Push both scores **> 9.5/10** by closing F1–F8 in line with current MCP
best-practice (MCP spec rev 2025-06-18 / 2025-11-25; Anthropic "Writing tools
for agents", "Effective context engineering"). Concretely, lift the two
dragging consumer dimensions and clear the correctness/representation nits:

- **Token efficiency 7 → 9–10** (F1)
- **Speed/latency 7 → 9** (F2, F3)
- **Error handling / chaining 9 → 10** (F5, F4)
- **Structured output 9 → 10** (F6, F7)
- **Discoverability 9 → 9–10** (F2, F4, F8 docs)
- Hold **Observability 10** (keep `request_id` / `elapsed_ms` / `cached`).

Non-goals: no new tools; no SPARQL **query-builder semantic** changes (keeps the
QLever-timeout risk surface untouched — see §6); no breaking change to the
`{tool, arguments}` `next_commands` contract the assessment praised.

## 3. Best-practice grounding (research synthesis)

Key conclusions that shaped the design (full sourcing in the implementation
plan):

- **Demote static metadata to discovery.** Anthropic: return only
  *contextually relevant, actionable* fields; the goal is "the smallest set of
  high-signal tokens." A static safety flag / DOI / release tag identical on
  every response is non-actionable per-call and belongs in the
  capabilities/discovery surface. **Strong consensus.** → C1.
- **null vs "" vs omission carry distinct semantics; never use `""` as a
  sentinel.** Pick one policy and apply it uniformly. This module's house style
  is *omit absent optionals* (e.g. `_classify_variant` already pops `wild_type`
  when None; `shape_*` filter `None/""`). → C6 follows house style (omit).
- **No standard latency field exists** in MCP (annotations are only
  `readOnly/destructive/idempotent/openWorld` hints). The de-facto convention is
  **prose + a capabilities "latency profile."** → C2.
- **Deterministic pagination needs a total order with a unique tiebreak** (the
  primary key). → C8 appends `accession`.
- **Errors should be actionable and steer self-correction**; recovery hints
  must name the *right* next step, never invite a hallucinated one. → C5.

## 4. The changes (C1–C8)

Each change names the files it touches, the behavior delta, and the test that
locks it. All payload output schemas are already permissive
(`additionalProperties:true`, nothing `required`), so field additions/omissions
never break structured-output validation.

### C1 — Trim per-call `_meta`; make provenance discovery-only

**Files:** `mcp/envelope.py`, `mcp/capabilities.py`, tests.

`_BASE_META` currently injects `unsafe_for_clinical_use`, `uniprot_release`,
`citation` into **every** success and error `_meta`. Demote all three. Per-call
`_meta` becomes exactly: `{tool, request_id, next_commands}` (plus any
tool-specific keys). `elapsed_ms` / `cached` remain top-level payload fields
(unchanged) so **Observability is fully preserved**.

The provenance is **not lost** — it is authoritative in `get_server_capabilities`
(`research_use_only`, `research_use_notice`, `recommended_citation`,
`uniprot_release`) and in the always-in-context server `instructions` block. To
make the demotion explicit and auditable, add to capabilities:

```json
"provenance_policy": "Static provenance (research-use restriction, citation,
  UniProt release) is declared here and applies to ALL tool outputs; it is not
  repeated per-call to conserve context tokens. Per-call _meta carries only
  dynamic fields.",
"per_call_meta": ["tool", "request_id", "next_commands"]
```

**Safety note:** the research-use / not-for-clinical restriction is delivered by
(a) the server `instructions` primer (always in the client context) and (b)
capabilities. Removing the per-call boolean does not weaken the contract; it
removes a redundant, non-actionable repeat. This is the assessment's #1
recommendation and the strongest best-practice consensus.

**Tests to update (intentional contract change):**
`test_service_and_tools.py::test_provenance_is_compact` (rewrite to assert the
*lean* per-call meta and that provenance now lives in capabilities), plus the
two `_meta["uniprot_release"]`/`unsafe_for_clinical_use` assertions (lines ~276,
506–507). New: `test_capabilities_declares_provenance_policy`.

**Token impact:** ~30–40 tokens saved per call × every call.

### C2 — Advertise per-tool latency

**Files:** `mcp/capabilities.py` (+ slow-tool descriptions in
`mcp/tools/proteins.py`, `taxonomy.py`, `query.py`).

Add a coarse, honest `latency_profile` to capabilities so an agent can budget
timeouts:

```json
"latency_profile": {
  "note": "Cold upstream SPARQL latency; a repeated identical call is served
    from a 1h in-process cache in ~0 ms (see _meta-adjacent `cached`).",
  "bands": {
    "fast_cached_or_anchored": {"typical_ms": "0-700", "tools": ["get_protein",
      "get_protein_sequence", "get_protein_features", "get_protein_variants",
      "get_protein_diseases", "get_protein_cross_references",
      "get_protein_go_terms", "map_identifiers", "get_taxon(by-id)",
      "get_taxon(curated name)"]},
    "medium": {"typical_ms": "1000-3000", "tools": ["search_example_queries",
      "get_example_query"]},
    "slow_cold_scan": {"typical_ms": "3000-12000", "tools": ["find_proteins(cold)",
      "get_taxon(uncached name scan)", "run_sparql_query(unbounded/federated)"]}
  }
}
```

Add a one-line latency cue to the descriptions of `find_proteins`, `get_taxon`,
and `run_sparql_query` (e.g. *"Cold search can take several seconds; an
identical repeat is cached (~0 ms)."*). Numbers are coarse bands, not promises.

**Test:** `test_capabilities_has_latency_profile` (asserts the block + that every
tool name appears in some band).

### C3 — Curated common-organism name index for `get_taxon` (the F3 fix)

**Files:** `services/constants.py` (new `COMMON_TAXA`), `services/sparql_service.py`
(`get_taxon`), tests.

Root cause: name resolution is a full-taxonomy FILTER scan (`resolve_taxon_by_name`).
An agent typically types a model-organism name only to obtain its taxon id for
`find_proteins`. Add a curated, **zero-network** name→id table for the ~30
organisms that dominate real queries (human/9606, mouse/10090, rat/10116,
S. cerevisiae/559292, E. coli K-12/83333, D. melanogaster/7227,
C. elegans/6239, zebrafish/7955, Arabidopsis/3702, bovine/9913, etc.), keyed by
lowercased scientific **and** common names.

Behavior: in `get_taxon`, before the scan, look up the normalized name in
`COMMON_TAXA`. On a hit, return the authoritative single match **with no SPARQL
call** — `match_count:1`, `matches:[{taxon_id, scientific_name, common_name,
rank}]`, plus `match_source:"curated_common_index"`, `elapsed_ms:0`,
`cached:true`. On a miss, fall through to the existing scan unchanged
(`match_source:"endpoint_scan"`).

This collapses the worst-offender (~11 s → ~0 ms, no network) for the common
case while preserving the long-tail/disambiguation path (e.g. "Homo sapiens
neanderthalensis" still scans and returns its match). The `matches[]` array
shape is unchanged, so `TAXON_SCHEMA` and the next_commands chain
(`get_taxon(id)` → `find_proteins(organism_taxon=id)`) are untouched.

Add a capabilities note that name resolution is curated-fast for common
organisms and scan-slow otherwise; for exhaustive name disambiguation, an agent
can use `run_sparql_query`.

**Tests:** `test_get_taxon_common_name_is_curated` (mocked client asserts **no**
HTTP call for "homo sapiens"/"human" and `match_source=="curated_common_index"`,
taxon_id 9606); `test_get_taxon_uncommon_name_falls_through` (asserts the scan
path runs). Live integration: assert curated path returns 9606 with
`elapsed_ms==0`.

### C4 — `domain` → `region` proactive hint (the F4 fix)

**Files:** `services/sparql_service.py` (`get_features`), tests.

The existing `filter_hint` only fires on **zero** matches. The trap is precisely
the *non-zero-but-partial* case: `['domain']` returns the FHA domain but misses
the catalytic phosphatase (146–337) and kinase (341–516) regions typed `region`.

When the request's `feature_types` includes `domain` **and not** `region`,
attach a structured, non-noisy hint regardless of count:

```json
"domain_region_hint": {
  "message": "UniProt types some domain-scale architecture as 'region' (e.g.
    catalytic, binding, or interaction regions), not 'domain'. Re-request with
    feature_types including 'region' to capture the full domain architecture.",
  "suggestion": {"tool": "get_protein_features",
    "arguments": {"accession": "<acc>", "feature_types": ["domain", "region"]}}
}
```

Also prepend that `get_protein_features(..., ['domain','region'])` call to
`next_commands` for this case so the fix is one tap away. Hint appears only when
`domain` was requested without `region` — never on unfiltered or `region`
queries, so no per-call noise.

**Test:** `test_features_domain_without_region_hints` (mocked) and a live
integration assertion on Q96T60.

### C5 — Accession-shape-aware error recovery (the F5 fix)

**Files:** `mcp/next_commands.py`, tests.

`protein_not_found_recovery` only blocks *numeric-leading* values; an
accession-shaped-but-invalid string like `Q96T60XYZ` passes `_GENE_SHAPE` and is
wrongly replayed as `find_proteins(gene=...)`. Replace the gene-shape gate with
`looks_like_gene_symbol(value)`:

- **False** if the value matches `_ACCESSION_RE` (a real or near-real accession),
  or has a digit in position 2 (accession interior signature, e.g. `Q9…`,
  `P0…`), or is empty/leading-digit.
- **True** only for genuine gene-symbol shapes (`BRCA1`, `TP53`, `CYP2D6`,
  `HLA-A`): starts with a letter, ≤10 chars, no accession signature.

So `get_protein("Q96T60XYZ")` → recovery `[get_server_capabilities,
search_example_queries(text="protein")]` (no misleading gene replay);
`get_protein("BRCA1")` (a gene typed into the accession field) → still
`[find_proteins(gene="BRCA1"), …]` — a genuinely useful redirect. Applies to
both `invalid_input` and `not_found` on `get_protein` (the envelope already
routes both through this function).

**Tests:** extend `test_next_commands.py` — `protein_not_found_recovery("Q96T60XYZ")`
must NOT contain a `find_proteins(gene=...)`; `("BRCA1")` must; `("999999")`
must not (regression).

### C6 — Variant `substitution`: omit when inapplicable (the F6 fix)

**Files:** `services/shaping.py` (`shape_variants` / `_classify_variant`), tests.

Normalize an empty `?substitution` binding to "absent": when a variant is not a
single-residue substitution (`variant_type:"other"`), **omit** the
`substitution` key entirely (house style — same as `wild_type`/`notation`
omission in the same function), rather than emitting `""`. Do **not** fabricate a
`notation` (e.g. `T408del`) — UniProt does not assert the change is a deletion,
so an invented HGVS string would be misleading. Result for T408:
`{begin:408, end:408, wild_type:"T", variant_type:"other",
description:"In AOA4.", diseases:[…]}` — no `substitution:""`, no false notation.

Substitution variants are unchanged (`substitution:"F"`, `notation:"L176F"`).

**Tests:** extend `test_shaping.py` — a row with empty substitution yields no
`substitution` key and `variant_type=="other"`; a normal row keeps both.

### C7 — Computed isoform `mass_da` (the F7 fix)

**Files:** `services/shaping.py` (new `average_mass` helper + `shape_sequences`),
`services/constants.py` (residue mass table), tests.

UniProt asserts `up:mass` only on the canonical sequence object, so
non-canonical isoforms return `mass_da:null` despite carrying a full sequence.
Compute the average molecular mass from the isoform sequence (standard average
residue masses + one water, 18.01524 Da; round to int Da like UniProt). When
`up:mass` is present, use it (source of truth). When absent and a sequence is
present, compute it and mark `mass_computed:true` so a consumer can distinguish
asserted from derived. Unknown residues (X/B/Z/U/O handling) fall back
gracefully; if the sequence has truly unknown residues, leave `mass_da` absent
rather than guess.

Correctness is **locked by test**: the computed mass of the *canonical* Q96T60-1
sequence must equal the UniProt-reported 57076 Da within ±2 Da (validates the
residue table). Compute happens in `shape_sequences` where the full `value`
string is present (before compact windowing).

**Tests:** `test_average_mass_matches_uniprot` (canonical within tolerance);
`test_isoform_mass_is_computed` (mocked: non-canonical row with sequence but no
`mass` → integer `mass_da` + `mass_computed:true`). Live: assert Q96T60-2 now has
a non-null `mass_da` ≈ expected.

### C8 — Deterministic `find_proteins` ordering (the F8 fix)

**Files:** `services/sparql_service.py` (`_sort_by_mnemonic` → total sort),
`mcp/capabilities.py` + `find_proteins` description (document the order), tests.

Mnemonics are unique per entry so the existing sort is already total in
practice, but (a) it is undocumented and (b) a missing mnemonic would be
non-deterministic. Make the key explicitly total —
`(mnemonic is None, mnemonic or "", accession)` — so `accession` is the
guaranteed unique final tiebreak. Document the contract in the tool description
and capabilities: *"Results are ordered reviewed (Swiss-Prot) first, then by
mnemonic (entry name), then accession — stable across identical calls and
pages."* This turns "opaque ordering" into a documented, deterministic contract
(the research-backed pagination-stability fix) without a SPARQL ORDER BY.

**Tests:** `test_find_proteins_sort_is_total` (two entries sharing a mnemonic
prefix order by accession; stable across repeated calls).

## 5. Deliberately rejected suggestions (engineering judgment)

- **Pre-warming `find_proteins` on startup** (assessment F2 fix-suggestion).
  Rejected: the in-process cache is keyed on the exact query, so warming gene A
  does nothing for the agent's query about gene B; it only adds startup cost and
  upstream load. The honest, high-value fix is **advertising** latency (C2) plus
  removing the worst concrete offender (C3). Documented here so the omission is
  intentional, not an oversight.
- **Fabricating `T408del`-style notation** (assessment F6 fix-suggestion).
  Rejected: we cannot prove the change is a deletion from the available
  bindings; an invented HGVS notation would be a correctness regression. C6 omits
  instead.
- **Indexing the taxonomy name columns / a text index.** Rejected: not ours to
  change (upstream QLever); the curated index (C3) captures ~all real demand.

## 6. Risk & rollback

- **SPARQL risk: none added.** No query-builder *semantics* change. C3 adds a
  pre-query lookup; C4/C6/C7/C8 are Python shaping/service/doc changes; C1/C2/C5
  are envelope/metadata/recovery changes. `research/verify_queries.py` is
  therefore not required by this change set, though `make ci-local` +
  `make test-integration` are.
- **Contract change (intentional):** per-call `_meta` loses three static fields
  (C1). Tests asserting them are updated in the same change. The
  `{tool, arguments}` next_commands shape and all output schemas are unchanged.
- **Behavior change (intentional):** `get_taxon("Homo sapiens")` returns one
  curated authoritative match instead of a 10-row scan list. The array shape is
  identical; long-tail names still scan. Net win for an LLM consumer resolving an
  id.
- **Rollback:** each C# is an atomic commit; reverting any one is independent.

## 7. Testing strategy

- **TDD per change**: failing unit test → implement → green, then refactor.
- **Unit (mocked httpx via respx / fake client)**: C1, C4, C5, C6, C7, C8, plus
  capabilities assertions for C1/C2/C3/C8.
- **Live integration (`@pytest.mark.integration`)**: extend
  `tests/integration/test_live.py` with one assertion per fix against Q96T60 /
  taxon 9606 — curated-taxon `elapsed_ms==0`, isoform mass non-null, T408 has no
  `substitution`, domain-without-region hint present, malformed-accession
  recovery has no gene replay, capabilities exposes `latency_profile` +
  `provenance_policy`.
- **Gate:** `make ci-local` (format, lint, lint-loc ≤600 LOC/module, mypy
  strict, unit tests) must pass before handoff; `make test-integration` validates
  live behavior.
- **Re-assessment note:** append a v0.5.0 results section to the assessment doc
  mapping each fix to the dimension it lifts.

## 8. Version & docs

- Bump `__version__` 0.4.0 → **0.5.0**; update any changelog/release notes.
- Update `docs/mcp-assessment-v0.4.0.md` (or a new `-v0.5.0` note) with the
  closed findings and the expected re-score rationale.

---

### Change → finding → dimension map

| C# | Closes | Lifts dimension |
|----|--------|-----------------|
| C1 | F1 | Token efficiency 7→9–10 |
| C2 | F2 | Speed/latency 7→9; Discoverability |
| C3 | F3 | Speed/latency (kills the 40× name-lookup tax) |
| C4 | F4 | Error/chaining + correctness of "domains" answers |
| C5 | F5 | Error handling 9→10 |
| C6 | F6 | Structured output 9→10 |
| C7 | F7 | Structured output 9→10 |
| C8 | F8 | Discoverability/determinism |
