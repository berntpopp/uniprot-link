# uniprot-link v0.6.0 — Assessment Uplift Design (target > 9.5 / 10)

Design contract for closing every finding in `docs/mcp-assessment-v0.5.0.md`
(F-OBS, F-ISO, F-VERB, F-SORT, F-ECO, F-MAP + the two nits) plus the two
remaining dimension gaps the assessment named (static chaining; token economy on
the list tools). Target: lift the overall consumer score from **8.7** to **> 9.5**.

All decisions below were validated against the live UniProt SPARQL endpoint
(release 2026_01, QLever) and against current MCP design guidance (June 2026)
before writing. Product decisions were confirmed with the maintainer:

- **F-OBS:** flagged obsolete *record* on `get_protein`, obsolete-flagged
  `not_found` on the data sub-tools (chosen over uniform `not_found`).
- **F-MAP:** narrow `map_identifiers` to a primary-id core (chosen over doc-only).
- **F-VERB xref:** lean compact (counts + capped sample) is the new default.

---

## 0. Live model facts this design relies on (verified 2026-06-12)

| Fact | Evidence (live query) |
|------|-----------------------|
| Obsolete entries keep `a up:Protein` and add `up:obsolete true` | `Z9Z9Z9`, `A0A009K1D9` both carry both triples |
| Demerged entries carry `up:replacedBy <newIRI>`; pure redundant-proteome deletions do not | `A0A009K1D9 up:replacedBy A0A9P2UQ24`; `Z9Z9Z9` has none |
| A single entry can have **multiple** `up:replacedBy` | `A0A075B5G1` → 3 replacements |
| The gate `a up:Protein . FILTER NOT EXISTS { up:obsolete true }` cleanly separates active / obsolete / absent | `P05067`→true, `Z9Z9Z9`/`A0A009K1D9`→false, bogus→false; ~206 ms |
| Real isoform link `uniprotkb:{base} up:sequence isoform:{base}-{n}` exists; a bogus index does not | `P05067-2`→true, `P05067-99`→false |
| Three bound `EXISTS` presence probes (variants / diseases / PDB) add negligible latency | enriched summary returned in **206 ms** |
| Authoritative ECO→GO evidence-code map | evidenceontology `gaf-eco-mapping-derived.txt` (Default rows) |

Upstream ontology quirk to preserve verbatim: the redundant-proteome class is
misspelled **`up:Member_Of_Redudant_Proteome`** in UniProt's own data. We never
hard-code that class; we key only on `up:obsolete`.

---

## 1. F-OBS (HIGH) — obsolete-aware entry gate, family-consistent

### Problem
`entry_exists_ask` is `ASK { uniprotkb:{base} a up:Protein }`. Obsolete entries
retain `a up:Protein`, so the gate passes and `get_protein` emits a sparse record
as a live success while sibling tools 404 — inconsistent, and a grounding risk
(a deleted entry presented as valid, with no `obsolete` flag).

### Design — one status probe, three outcomes
New query builder **`entry_status(accession)`** (replaces `entry_exists_ask`):

```sparql
SELECT ?obsolete ?replacedBy ?isoform_exists WHERE {
  uniprotkb:{base} a up:Protein .
  OPTIONAL { uniprotkb:{base} up:obsolete ?obsolete }
  OPTIONAL { uniprotkb:{base} up:replacedBy ?replacedBy }
  # ?isoform_exists line emitted ONLY when the request carried a -N suffix:
  BIND(EXISTS { uniprotkb:{base} up:sequence isoform:{full} } AS ?isoform_exists)
}
```

New shaper **`shape_entry_status(json, requested) -> EntryStatus`**:

```python
@dataclass(frozen=True)
class EntryStatus:
    exists: bool                 # any row at all
    obsolete: bool               # up:obsolete true present
    replaced_by: list[str]       # sorted, de-duped accessions
    isoform_exists: bool | None  # None when no -N suffix was requested
```

- 0 rows → `exists=False` (absent).
- ≥1 row, `obsolete=True` → obsolete; collect every `replacedBy` (accession form,
  sorted, deduped — handles the multi-replacement case).
- rows with obsolete unbound/false → active.

### New exception
```python
class ObsoleteEntryError(NotFoundError):
    """Entry exists but is obsolete (demerged/deleted)."""
    def __init__(self, accession, replaced_by=None, message=None):
        ...
        self.accession = accession
        self.replaced_by = replaced_by or []
```

### Service wiring
- **`require_entry`** (the shared gate for sequence/features/variants/diseases/
  go/xref/map) now runs `entry_status`:
  - absent → `NotFoundError` (unchanged message).
  - obsolete → `ObsoleteEntryError(accession, replaced_by)`.
  - active → return.
  `get_sequence` keeps its own "no sequence" path but runs the gate **in
  parallel** (`require_entry` ∥ `protein_sequence`) so an obsolete accession gets
  the family-consistent obsolete-flagged error rather than a bare "no sequence"
  — at no extra wall-clock cost.
- **`get_protein`** runs `entry_status` ∥ `protein_summary` (parallel, like the
  sub-tools), then branches:
  - absent → `NotFoundError`.
  - obsolete → return a **flagged obsolete record** (success), see below.
  - active → normal summary + presence flags + `requested_accession` echo.

### Obsolete record shape (get_protein success on an obsolete accession)
```json
{
  "accession": "A0A009K1D9",
  "obsolete": true,
  "obsolete_reason": "demerged",        // "demerged" if replaced_by, else "deleted"
  "replaced_by": ["A0A9P2UQ24"],
  "mnemonic": "A0A009K1D9_ACIBA",        // whatever sparse fields survive
  "reviewed": false,
  "notice": "This UniProtKB entry is obsolete and is not a live record. ...",
  "_meta": { "next_commands": [ {get_protein: A0A9P2UQ24}, ... ] }
}
```
No `sequence_length`/`mass_da`/`function` are fabricated. The explicit
`obsolete:true` top-level flag is the grounding fix.

### Sub-tool obsolete error (envelope)
`ObsoleteEntryError` classifies as `error_code:"not_found"` (taxonomy unchanged)
but the envelope is enriched:
```json
{
  "success": false,
  "error_code": "not_found",
  "obsolete": true,
  "replaced_by": ["A0A9P2UQ24"],
  "message": "UniProtKB entry A0A009K1D9 is obsolete (demerged). Replaced by: A0A9P2UQ24.",
  "recovery_action": "switch_tool",
  "_meta": { "next_commands": [ {get_protein: A0A9P2UQ24} ] }
}
```
`envelope._classify` / `_error_envelope` gain an `ObsoleteEntryError` branch that
attaches `obsolete`, `replaced_by`, and replacement-targeted `next_commands`.
When `replaced_by` is empty (pure deletion, e.g. `Z9Z9Z9`) the next_command falls
back to `get_server_capabilities`.

### Consistency claim
Every tool now emits the same unambiguous signal — `obsolete:true` + `replaced_by`
— differing only in success vs error because `get_protein` *has* something to say
(it's the "what is this accession" tool) and the data tools do not. This resolves
the assessment's inconsistency and grounding complaints.

---

## 2. F-ISO (MEDIUM) — echo `requested_accession`, validate isoform index

- `get_protein` always echoes **`requested_accession`** (the raw input, e.g.
  `P05067-2`) alongside the normalized entry `accession` (`P05067`).
- When the request carries a `-N` suffix, `entry_status` includes the
  `isoform_exists` probe:
  - isoform exists → return the entry summary, add `isoform: "P05067-2"` and a
    `isoform_note` directing to `get_protein_sequence` for isoform-specific
    sequence/mass; first next_command becomes `get_protein_sequence`.
  - isoform does **not** exist (e.g. `P05067-99`) → `NotFoundError`
    ("No isoform -99 for P05067; the entry has N isoforms.").
- A caller can now always distinguish a real isoform request, a typo'd index, and
  a parent-entry request.

---

## 3. F-VERB (MEDIUM) — verbosity / pagination on the high-volume list tools

Guided by MCP best practice (small default pages, always expose counts, let the
agent pull more deliberately). Query builders stay untouched except a single
`LIMIT` integer (no join-shape change → no QLever re-plan risk).

### get_protein_go_terms
- New params: `aspect` (enum: `biological_process | molecular_function |
  cellular_component`) and `limit` (int, default 0 = all, max 500).
- Always include `count` (total matched) and **`count_by_aspect`** (aspect →
  count). Aspect filter + limit applied in the service/shaping layer (the query
  already bounds rows at 2000). Add `truncated` when `limit` caps the result.
- Default call is backward-compatible (returns all, now with counts).

### get_protein_features
- New param: `limit` (int, default 200, max 1000) passed into the builder's
  existing `LIMIT` (integer-only change). `count` already present; add
  `truncated` when the cap is hit. `feature_types` filter unchanged.

### get_protein_cross_references / map_identifiers — lean compact
Response-mode-driven output, counts always present:

| mode | `counts` (db→n) | `by_database` ids | `truncated_databases` |
|------|:---:|---|:---:|
| minimal | yes | omitted | — |
| compact (default) | yes | first N=25 **sorted** ids per db | yes, per capped db |
| standard / full | yes | all **sorted** ids (full = raw IRIs) | — |

- `counts`, `total`, `database_count` always present (cheap, high value).
- `truncated_databases`: `{ "PDB": {"returned": 25, "total": 227} }` so the cap is
  never silent.
- Cap constant `_XREF_COMPACT_ID_CAP = 25` in shaping.
- For `map_identifiers` the primary-id set is small, so the cap is effectively a
  no-op there — but the contract is identical.

---

## 4. F-SORT (LOW) — deterministic id ordering

`shape_cross_references` sorts both id lists and database keys:

```python
return {db: sorted(ids) for db, ids in sorted(grouped.items())}
```

Makes `get_protein_cross_references` and `map_identifiers` return identical,
diff-stable, cache-friendly ordering regardless of QLever row order.

---

## 5. F-ECO (LOW) — authoritative ECO→GO map + honest comment

- Backfill `ECO_TO_GO_CODE` from the evidenceontology Default mapping. Add the 11
  missing high-frequency codes:

  `ECO_0000269→EXP, ECO_0007005→HDA, ECO_0007007→HEP, ECO_0007003→HGI,
  ECO_0007001→HMP, ECO_0006056→HTP, ECO_0000319→IBD, ECO_0000317→IGC,
  ECO_0000320→IKR, ECO_0000321→IRD, ECO_0000245→RCA`

  (existing 16 entries retained, incl. the UniProt-specific `ECO_0007669→IEA`).
- Fix the misleading comment: unmapped ECO ids are **not** passed through into
  `evidence_codes`; they remain visible as raw ids in the `evidence` list. Reword
  to state that accurately (the raw ECO id is always in `evidence`;
  `evidence_codes` carries only mapped three-letter GO codes).

---

## 6. F-MAP (LOW) — focused primary-id default

New constant `MAP_IDENTIFIER_DATABASES` (a true primary-id core):

```python
MAP_IDENTIFIER_DATABASES = [
    "PDB", "AlphaFoldDB", "Ensembl", "RefSeq",
    "GeneID", "HGNC", "KEGG", "OrthoDB", "Pfam", "InterPro",
]
```

`map_identifiers` defaults to this set (genomic / structural / family identifiers).
The drug/disease-association DBs (DrugBank, ChEMBL, OpenTargets, DisGeNET,
GeneCards) stay in the exhaustive `get_protein_cross_references`. Tool/doc text
updated to describe the now-true distinction. `COMMON_XREF_DATABASES` is retained
for capabilities' "common xref databases" listing.

---

## 7. Content-aware chaining + presence flags (chaining 8→9.5, observability)

The assessment's chaining deduction: suggestions are static ("`get_protein`
always proposes sequence + features regardless of content"). Fix at **zero added
latency** using the three bound `EXISTS` probes already validated (206 ms):

- `protein_summary` gains `has_variants`, `has_diseases`, `has_structure` booleans
  (bound `EXISTS` on the entry IRI; query stays a single bound query).
- These surface on the `get_protein` payload (useful signals) **and** drive
  `after_get_protein`: propose `get_protein_diseases` only when `has_diseases`,
  `get_protein_variants` only when `has_variants`, etc. Sequence is always
  offered; the rest are content-gated, deduped, trimmed to the top 2 (token diet).
- Obsolete entries chain to their replacement (`get_protein` on `replaced_by[0]`).

This is the only query-builder enrichment that needs live timing re-validation
(covered in §10).

---

## 8. Nits

- **Pydantic → envelope (error-handling consistency, 8→9.5):** drop `min_length=6`
  from the `_ACC` schema annotation so a too-short/garbage accession reaches the
  tool body and flows through `validate_accession` → `InvalidInputError` → the
  polished envelope (`field:"accession"`, example-bearing message,
  `next_commands`). The bounded `ge/le` constraints on `limit`/`offset`/taxon stay
  (they carry no domain-specific message worth re-routing).
- **Doc imprecision:** `get_protein`'s description claims "full restores raw IRIs"
  — a no-op there (it only adds `created`/`modified`). Reword to
  "standard/full add created/modified" and reserve the raw-IRI claim for the xref/
  map tools where it is true.

---

## 9. Capabilities / discovery updates

- `not_found_contract`: add the obsolete clause ("an obsolete/demerged accession
  returns `obsolete:true` + `replaced_by`; `get_protein` as a flagged record,
  data tools as an obsolete-flagged `not_found`").
- Add `obsolete_handling` note + a `map_identifier_databases` listing.
- `result_ordering`: add the cross-reference/​map id-sort + per-database cap note.
- Document the new `aspect`/`limit` controls and the xref response-mode cap.
- Bump version to **0.6.0** (`uniprot_link/__init__.py`); `buildinfo` follows.

Output schemas (`schemas.py`) extended (still permissive, `additionalProperties:
true`): `PROTEIN_SCHEMA` += `requested_accession, obsolete, replaced_by,
has_variants, has_diseases, has_structure`; `CROSS_REFERENCES_SCHEMA` /
`MAP_IDENTIFIERS_SCHEMA` += `counts, truncated_databases`; `GO_TERMS_SCHEMA` +=
`count_by_aspect, truncated`; `FEATURES_SCHEMA` += `truncated`.

---

## 10. Testing & validation strategy

**Unit (mocked `FakeSparqlClient`, the default path):**
- `entry_status` shaping: active / obsolete-no-replacement / obsolete-multi-
  replacement / absent / isoform-exists / isoform-absent.
- `get_protein`: obsolete → flagged record (no fabricated seq/mass); demerged →
  `replaced_by` populated; isoform echo; bogus isoform → not_found;
  `requested_accession` always echoed.
- Family consistency: every data sub-tool raises `ObsoleteEntryError` on an
  obsolete accession; envelope carries `obsolete:true` + `replaced_by` +
  replacement `next_commands`.
- F-SORT: xref/map id lists and db keys sorted & identical across both tools.
- F-ECO: `ECO_0007005`→HDA, `ECO_0000269`→EXP present; unmapped id stays in
  `evidence`, absent from `evidence_codes`.
- F-VERB: go_terms `aspect`/`limit`/`count_by_aspect`/`truncated`; features
  `limit`/`truncated`; xref minimal=counts-only, compact caps at 25 +
  `truncated_databases`, full=all.
- F-MAP: `map_identifiers` defaults to `MAP_IDENTIFIER_DATABASES`.
- Content-aware chaining: `has_*` flags gate the suggested sub-tools.
- Nit: short accession → `invalid_input` envelope (not raw pydantic).

**Live re-validation (`research/verify_queries.py`, per CLAUDE.md):** add cases
for `entry_status` (P05067 active, Z9Z9Z9 obsolete-no-replacement, A0A009K1D9
demerged, bogus absent), the enriched `protein_summary` (presence flags +
timing < ~2 s), and `protein_features(limit=...)`. Then `make ci-local`.

**Integration (`@pytest.mark.integration`, opt-in):** one obsolete-accession
end-to-end assertion so the regression is guarded against future endpoint drift.

---

## 11. Non-goals / YAGNI

- No cursor-based opaque pagination (the result sets are small and bounded;
  offset pagination already exists where it matters, on `find_proteins`).
- No isoform-specific summary enrichment beyond the echo + sequence pointer
  (sequence tool already serves isoform sequence/mass).
- No change to the `find_proteins` two-phase pagination or the latency profile
  (speed is upstream-bound; not in scope).
- No new error code for obsolete (reuse `not_found` + `obsolete` flag to keep the
  taxonomy stable).

---

## 12. Acceptance criteria → dimensions

| Finding / gap | Change | Dimension lifted |
|---|---|---|
| F-OBS | obsolete-aware gate + flagged record + obsolete envelope | Grounding/safety, Error handling, Correctness |
| F-ISO | `requested_accession` echo + isoform validation | Tool/schema design, Grounding |
| F-VERB | aspect/limit + counts + lean-compact xref | Token efficiency |
| F-SORT | sorted ids + db keys | Observability/reproducibility |
| F-ECO | authoritative ECO map + honest comment | Grounding |
| F-MAP | focused primary-id default | Tool/schema design |
| chaining | content-aware next_commands + presence flags | Chaining/composability, Observability |
| nits | pydantic→envelope; doc fix | Error handling |

Goal: every addressable dimension ≥ 9.5; speed remains upstream-bound (~7, out of
scope). Overall target **> 9.5**.
