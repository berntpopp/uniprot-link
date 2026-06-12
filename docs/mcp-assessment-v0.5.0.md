# uniprot-link MCP Assessment — v0.5.0

An LLM-consumer evaluation of the uniprot-link MCP server, conducted by driving
the live tool surface and rating the experience. Two assessments are recorded:

1. **Consumer Experience Assessment** — a dimension-based rating of what it is
   like to consume this MCP as the calling model (discoverability, token
   efficiency, speed, observability, etc.).
2. **Comprehensive Tool-by-Tool Test** — a senior-tester pass exercising all 14
   tools with happy paths, every `response_mode`, filters, pagination, caching,
   and deliberate failure probes.

> This is the v0.5.0 follow-up to `docs/mcp-assessment-v0.4.0.md` (v0.4.0),
> which in turn followed `docs/mcp-assessment.md` (v0.3.0) and the original
> `uniprot-link-mcp-assessment.md` (v0.1.0). The v0.5.0 build closed the
> C1–C8 / F1–F8 assessment-uplift items; this pass re-evaluates the deployed
> build and reports one new correctness finding (obsolete-entry handling) not
> covered by earlier passes.

## Test Context

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Server | `uniprot-link` |
| Server version | 0.5.0 |
| Build | git_sha `f7233d6`, built_at `2026-06-12T12:01:33Z` |
| UniProt release | 2026_01 |
| Endpoint | https://sparql.uniprot.org/sparql (QLever) |
| Evaluator | Claude (Fable 5), LLM consumer of the MCP |
| Method | ~45 live tool calls across batches; all 14 tools; happy paths, all four `response_mode`s, every `find_proteins` anchor, both `get_taxon` modes, the full `run_sparql_query` matrix (SELECT / ASK / CONSTRUCT-turtle / UPDATE-reject / syntax-error / auto-LIMIT), and deliberate error/edge probes including an obsolete accession |
| Primary fixtures | P05067 (A4_HUMAN / APP), Q96T60 (PNKP), P41227 (NAA10), taxon 9606; obsolete fixture `Z9Z9Z9` |
| Scope note | Single session, single endpoint state. Findings reflect observed behavior at the build above. |

---

## Part 1 — Consumer Experience Assessment

How effective and economical the server is to use as the calling model, scored
1–10 per dimension with the evidence each score rests on.

### Overall: 8.7 / 10

A well-built, agent-first MCP that clearly anticipates an LLM consumer:
structured errors, `next_commands` chaining on every response, per-call
provenance trimmed to a lean `_meta`, response-mode verbosity control, and a
genuinely rich discovery surface. Up from 8.5 (v0.4.0). The single thing
standing between it and a 9+ is the obsolete-entry inconsistency in Part 2
(F-OBS): `get_protein` presents a demerged entry as a near-empty success while
sibling tools 404 on the same accession. Token economy on the high-volume list
tools is the next-largest gap.

### Scores

| Dimension | Score | Basis |
|-----------|:----:|-------|
| Discoverability | 9 | `get_server_capabilities` is a single complete map: 14 tools, 21 graphs with triple counts, prefixes, feature-type + xref vocabularies, error taxonomy, limits, latency profile, recommended workflows. 126 searchable example queries via `search_example_queries` → `get_example_query`. Tool schemas carry concrete examples (P05067). |
| Tool / schema design | 8.5 | Clear names; `find_proteins` requires an anchor (prevents unbounded scans), verified by the no-anchor and organism-only rejections; `feature_types` advertises and round-trips its vocabulary; `domain_region_hint` actively steers around the domain-vs-region data-model gotcha. Deduction: `map_identifiers` overlaps `get_protein_cross_references` heavily and its "focused" default isn't focused (20 dbs / 372 ids). |
| Chaining / composability | 8 | Every response — success **and** error — carries `_meta.next_commands` as ready-to-call `{tool, arguments}` with the accession pre-filled. Deduction: suggestions are still largely static (e.g. `get_protein` always proposes sequence + features regardless of what the entry contains). |
| Observability | 9 | Per-call `elapsed_ms`, `cached`, `request_id`, `limit_injected`, and `truncated` recovery hints; capabilities exposes `server_version` + `git_sha` + `built_at`. Static provenance correctly demoted to capabilities (no per-call citation spam). |
| Grounding / safety | 8.5 | Release pinned (2026_01), citation + research-use + read-only declared in capabilities, write/UPDATE SPARQL rejected as `invalid_input`. Deduction: an obsolete/demerged entry is surfaced by `get_protein` as a live (if sparse) record with no `obsolete` flag — a grounding risk for a research tool (see F-OBS). |
| Error handling | 8 | Consistent envelope (`error_code`, `message`, `retryable`, `recovery_action`, `field`, `_meta.next_commands`); `allowed_values` returned in full on a bad `feature_types`; helpful `query_syntax_error` guidance. Deduction: schema-level failures (e.g. `accession` < minLength) bypass the envelope as raw pydantic errors; obsolete-entry inconsistency. |
| Token efficiency | 7.5 | `response_mode` works (function text gated behind compact+; `full` restores raw IRIs); compact `sequence_preview` windowing keeps large proteins cheap; lean `_meta`. Deduction: no verbosity/pagination on the high-volume list tools — `get_protein_go_terms` returned 123 terms, `get_protein_cross_references` 227 PDB ids, `get_protein_features` is unbounded. |
| Speed / latency | 7 | Entry-detail tools 40 ms – 1.9 s; warm cache reads 0 ms (`cached:true`). `find_proteins` remains the cold hotspot (~5.8–6.0 s). Upstream-bound, consistent with the published latency profile. |

---

## Part 2 — Comprehensive Tool-by-Tool Test

A senior-tester pass. All 14 tools exercised against the deployed v0.5.0 build.

### Coverage matrix

| Tool | Probes run | Result |
|------|-----------|--------|
| `get_server_capabilities` | full capabilities map | ✅ complete; version/build match HEAD |
| `find_proteins` | gene, keyword (KW-0007), ec_number, no-anchor, organism-only, pagination | ✅ incl. correct `invalid_input` on missing/insufficient anchor; deterministic reviewed→mnemonic order; `truncated`/offset hint |
| `get_protein` | minimal / compact / full; obsolete; bad-format; isoform | ⚠️ obsolete + isoform issues (F-OBS, F-ISO) |
| `get_protein_sequence` | compact preview, isoforms, obsolete | ✅ preview windowing; `mass_computed:true` on non-canonical isoforms; correct `not_found` on obsolete |
| `get_protein_features` | `domain` filter, zero-match, invalid-type | ✅ filter works; `domain_region_hint`; `filter_hint` on zero-match; `invalid_input` + full `allowed_values` on bad type |
| `get_protein_variants` | `disease_associated_only` | ✅ HGVS `notation` on simple substitutions; empty `substitution` correctly omitted on multi-residue variants |
| `get_protein_diseases` | P05067; obsolete | ✅ `definition` + `involvement` + MIM; ⚠️ obsolete returns empty success (F-OBS) |
| `get_protein_cross_references` | PDB filter; `full` IRI mode | ✅ filter + raw-IRI restore; ⚠️ unsorted id lists (F-SORT) |
| `get_protein_go_terms` | P05067 (123), P41227 (14) | ✅ aspect grouping + ECO/GO codes; ⚠️ ECO map gap + no pagination (F-ECO, F-VERB) |
| `map_identifiers` | default | ✅ 20 dbs; ⚠️ overlap with cross-refs + unsorted (F-MAP, F-SORT) |
| `get_taxon` | id, name, lineage, not_found id, not_found name | ✅ dual-mode; full lineage; curated common-name index (0 ms); consistent `not_found` |
| `run_sparql_query` | SELECT, ASK, CONSTRUCT-turtle, UPDATE, syntax-error, unbounded | ✅ all correct; auto-LIMIT with `truncated`; write rejected; syntax guidance |
| `search_example_queries` | text="disease" | ✅ ids + descriptions + keyword tags |
| `get_example_query` | example 121 | ✅ full query text + `federates_with` + run `next_command` |

### Findings (by severity)

#### F-OBS — HIGH — Obsolete entries handled inconsistently across the tool family

For the demerged accession `Z9Z9Z9` (`up:obsolete = true`, rdf:type
`Member_Of_Redundant_Proteome` **and** `up:Protein`, no sequence/organism/name):

| Tool | Behavior | Correct? |
|------|----------|:--------:|
| `get_protein` | `success:true`, body = `{accession, mnemonic, reviewed}` only | ✗ misleading |
| `get_protein_diseases` | `success:true`, `count:0` | ✗ (passes the gate) |
| `get_protein_sequence` | `not_found` ("[404] No sequence found") | ✓ |

This contradicts the capabilities `not_found_contract` and, worse for a
research-grounding tool, silently presents a **deleted entry as a valid one**.

**Root cause:** `entry_exists_ask` (`uniprot_link/services/queries/proteins.py:149`)
is `ASK { uniprotkb:{base} a up:Protein }`. Obsolete entries retain
`a up:Protein`, so `require_entry` (`uniprot_link/services/sparql_service.py:283`)
never raises `NotFoundError`, and `shape_protein_summary` emits whatever sparse
fields survive. Tools that instead rely on their own data query returning zero
rows (e.g. sequence) correctly 404.

**Fix** — exclude obsolete in the single gate, which unifies `get_protein` /
`get_protein_features` / `get_protein_diseases` / `get_protein_variants` with
`get_protein_sequence`:

```python
def entry_exists_ask(accession: str) -> str:
    base = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
ASK {{ uniprotkb:{base} a up:Protein .
       FILTER NOT EXISTS {{ uniprotkb:{base} up:obsolete true }} }}"""
```

*Alternative* (if demerged lookups should still resolve): keep returning data
but add `obsolete:true` + `replaced_by`. Either way, make the family consistent
and add a regression test with an obsolete accession.

#### F-ISO — MEDIUM — `get_protein` silently collapses isoforms to parent with no echo

`get_protein("P05067-2")` (real isoform) and `get_protein("P05067-99")`
(nonexistent isoform) both return the canonical P05067 record with
`accession:"P05067"` — identical, with no `requested_accession` echo and no
`not_found` for the bogus index. `protein_summary` does `acc.split("-")[0]`
(`proteins.py:164`) and discards the suffix. A caller cannot distinguish a real
isoform request from a typo.

**Fix:** echo `requested_accession`, and reject/notate nonexistent isoform
indices rather than returning the parent as if it were the request.

#### F-VERB — MEDIUM — No verbosity/pagination on high-volume list tools

`get_protein_go_terms` returned 123 terms for P05067 (no `limit`, no `aspect`
filter, no `response_mode`); `get_protein_cross_references` returned 227 PDB
ids; `get_protein_features` is unbounded. Only `get_protein_variants` has a
`limit`. These are large, unavoidable token payloads.

**Fix:** add an `aspect` filter (+ optional `limit`) to `get_protein_go_terms`,
and a `limit`/top-N to `get_protein_features` and (count-wise)
`get_protein_cross_references`.

#### F-SORT — LOW — Non-deterministic id ordering in cross-refs / map_identifiers

The same accession returns PDB/RefSeq/InterPro id lists **unsorted and in a
different order between `get_protein_cross_references` and `map_identifiers`**
(QLever result order is not stable). Hurts reproducibility, diffing, and cache
friendliness. `shape_cross_references` (`uniprot_link/services/shaping.py:264`)
appends in raw row order.

**Fix (one line):**

```python
return {db: sorted(ids) for db, ids in grouped.items()}
```

#### F-ECO — LOW — ECO → GO evidence-code map has gaps

GO terms with `ECO:0007005` (e.g. P05067 "extracellular exosome", P41227
"membrane") return `evidence` but omit `evidence_codes` — systematic, not a
one-off. `ECO_TO_GO_CODE` (`uniprot_link/services/constants.py:250`) is missing
`ECO_0007005` → `HDA` and `ECO_0000269` → `EXP` (both common). The accompanying
comment ("Unmapped ECO ids pass through as the raw id") is also inaccurate —
unmapped ids are dropped from `evidence_codes`, not passed through.

**Fix:** add the missing entries (and/or honor the documented pass-through).

#### F-MAP — LOW — `map_identifiers` vs `get_protein_cross_references` differentiation is thin

Docs frame `map_identifiers` as "focused primary-id mapping" vs the "exhaustive"
cross-references, but its default returned 20 databases / 372 ids (incl.
DrugBank, ChEMBL, OpenTargets, DisGeNET) — heavily overlapping and not obviously
focused.

**Fix:** either default `map_identifiers` to a true primary subset (PDB,
Ensembl, RefSeq, HGNC, GeneID) or align the docs to the actual behavior.

#### Nits

- Schema-level failures (e.g. `accession:"ABC"` below minLength 6) return a raw
  pydantic validation error rather than the polished envelope — inherent to MCP
  schema validation, but inconsistent with the server's own error style.
- "`full` restores raw IRIs" is a no-op for `get_protein` specifically (it only
  adds `created`/`modified`) — minor doc imprecision.

### Regression confirmations (prior-version fixes still holding)

- C4 `domain_region_hint` present and correct on a `domain`-only feature query.
- C6 empty variant `substitution` omitted (verified on the KM670–671NL Swedish
  variant: `variant_type:"other"`, no `substitution`/`notation`).
- C7 non-canonical isoform mass computed (`mass_computed:true` on all 10
  P05067 non-canonical isoforms).
- C8 deterministic `find_proteins` reviewed → mnemonic ordering (verified across
  keyword and EC anchors).
- Lean `_meta` (`{tool, request_id, next_commands}`) with static provenance in
  capabilities; `cached`/`elapsed_ms`/`limit_injected`/`truncated` all present.

### Prioritized recommendations

1. **F-OBS (HIGH):** fix the obsolete-entry gate (`entry_exists_ask`) + add a
   regression test. Only correctness bug found; highest risk of misleading a
   downstream consumer.
2. **F-ISO (MEDIUM):** echo `requested_accession` and handle nonexistent isoform
   indices in `get_protein`.
3. **F-VERB (MEDIUM):** add `aspect`/`limit` controls to the high-volume list
   tools for token economy.
4. **F-SORT (LOW):** sort id lists in `shape_cross_references` for determinism
   (one-liner).
5. **F-ECO (LOW):** backfill `ECO_TO_GO_CODE` (`ECO_0007005` → HDA,
   `ECO_0000269` → EXP).
6. **F-MAP (LOW):** clarify or narrow `map_identifiers` defaults vs
   `get_protein_cross_references`.

> Per `CLAUDE.md`, any change to `uniprot_link/services/queries/*` (F-OBS) must
> be re-validated against the live endpoint via `research/verify_queries.py`,
> followed by `make ci-local`.
