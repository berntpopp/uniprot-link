# uniprot-link v0.6.0 — Assessment-Uplift Closure

Resolution record for every finding in `docs/mcp-assessment-v0.5.0.md` (overall
**8.7 / 10**). Each item below maps the finding to the change, the commit, and the
evidence (unit + live). All UniProt RDF model facts were verified against the live
endpoint (release 2026_01, QLever) before implementation; the three public
API-contract decisions were confirmed with the maintainer.

Design: `docs/superpowers/specs/2026-06-12-mcp-assessment-uplift-v0.6.0-design.md`
Plan: `docs/superpowers/plans/2026-06-12-mcp-assessment-uplift-v0.6.0.md`

## Findings → resolution

| Finding | Sev | Resolution | Evidence |
|---|---|---|---|
| **F-OBS** obsolete entries inconsistent / silently "live" | HIGH | New `entry_status` 3-state probe (active/obsolete/absent) replaces the bare existence ASK. `get_protein` returns a **flagged obsolete record** (`obsolete:true`, `obsolete_reason`, `replaced_by:[...]`, no fabricated fields); every data sub-tool raises an obsolete-flagged `not_found` carrying `replaced_by` + a `next_command` to the live replacement. `replaced_by` is a list (a demerge can split into many). | Unit: obsolete record, deleted-vs-demerged, family consistency, envelope. Live: `test_obsolete_entry_is_flagged_live`, `test_demerged_entry_reports_replacement_live` (Z9Z9Z9, A0A009K1D9→A0A9P2UQ24). |
| **F-ISO** isoforms silently collapse to parent | MED | `get_protein` always echoes `requested_accession`; an `-N` suffix is validated via `entry_status` isoform probe — a real isoform echoes `isoform` + a sequence pointer, a bogus index returns `not_found`. | Unit: real/bogus isoform, echo. Live: `test_bogus_isoform_index_is_not_found_live` (P05067-2 real, P05067-99 rejected). |
| **F-VERB** no verbosity/pagination on list tools | MED | `get_protein_go_terms`: `aspect` filter + `limit` + `count_by_aspect` + `truncated`. `get_protein_features`: `limit` (clamped 1–1000) + `truncated`. `get_protein_cross_references`/`map_identifiers`: response-mode-driven — `counts` always present; `minimal` = counts only; `compact` caps each db at 25 sorted ids + `truncated_databases`; `standard`/`full` = all ids. | Unit: go aspect/limit/counts, features limit, xref lean-compact/minimal/full. Live: `protein_features(limit=5)` returns exactly 5. |
| **F-SORT** non-deterministic id ordering | LOW | `shape_cross_references` sorts ids **and** db keys → stable, diff/cache friendly, identical between the two tools. | Unit: `test_shape_cross_references_sorts_ids_and_db_keys`. |
| **F-ECO** ECO→GO evidence map gaps | LOW | Backfilled `ECO_TO_GO_CODE` from the authoritative evidenceontology `gaf-eco-mapping-derived.txt` (added EXP, HDA, HEP, HGI, HMP, HTP, IBD, IGC, IKR, IRD, RCA); comment corrected (raw ECO id always in `evidence`; only mapped ids in `evidence_codes`). | Unit: `test_shape_go_terms_maps_high_throughput_eco_codes` (ECO_0007005→HDA, ECO_0000269→EXP). |
| **F-MAP** map_identifiers vs cross_references overlap | LOW | New `MAP_IDENTIFIER_DATABASES` primary-id core (PDB, AlphaFoldDB, Ensembl, RefSeq, GeneID, HGNC, KEGG, OrthoDB, Pfam, InterPro); drug/disease-assoc DBs stay in the exhaustive cross-references. Docs/capabilities updated. | Unit: `test_map_identifiers_defaults_to_primary_id_set`. |
| **Nit** schema-level pydantic errors bypass envelope | — | Dropped `min_length` from the accession schema so a bad value reaches `validate_accession` → `InvalidInputError` → the polished envelope (`field:"accession"` + example + recovery). | Unit: `test_short_accession_returns_invalid_input_envelope` (via facade). |
| **Nit** "full restores raw IRIs" doc imprecision | — | `get_protein` description corrected (standard/full add created/modified; raw-IRI claim reserved for xref/map). | — |

## Beyond the findings (dimension lifts the assessment named)

- **Static chaining → content-aware.** `get_protein` now carries cheap bound
  `EXISTS` presence flags (`has_variants`/`has_diseases`/`has_structure`, ~206 ms,
  same single query) that gate `next_commands` — diseases/variants are proposed
  only when the entry has them; obsolete entries chain to their replacement.
  Live: `test_get_protein_presence_flags_live`.

## Verification

- `make ci-local`: ruff-format clean, ruff clean, file-size budget OK (all modules
  < 600 lines), mypy strict clean, **141 unit tests pass**.
- `make test-integration`: **38 live tests pass** against the UniProt endpoint
  (~49 s), incl. the four new obsolete/isoform/presence-flag regressions.
- `research/verify_queries.py`: every changed builder re-validated live
  (entry_status active/obsolete/demerged/absent/isoform; enriched summary;
  `protein_features(limit=5)`), per the CLAUDE.md QLever discipline.

## Projected dimension impact

| Dimension | v0.5.0 | Driver of the lift |
|---|:--:|---|
| Discoverability | 9 | obsolete/map-db/ordering now documented in capabilities |
| Tool / schema design | 8.5 | F-MAP focus; F-ISO echo; richer typed schemas |
| Chaining / composability | 8 | content-aware, presence-gated next_commands |
| Observability | 9 | counts everywhere; sorted, reproducible ids |
| Grounding / safety | 8.5 | obsolete entries never presented as live; replaced_by |
| Error handling | 8 | pydantic→envelope; obsolete-flagged not_found |
| Token efficiency | 7.5 | aspect/limit + lean-compact xref (counts + capped sample) |
| Speed / latency | 7 | unchanged (upstream-bound; out of scope) |

The only finding that was a correctness bug (F-OBS) is closed and regression-
guarded live; the token-economy gap (F-VERB) is addressed across all three
high-volume tools. Speed remains the single upstream-bound dimension. A fresh
independent assessment against a deployed v0.6.0 build is the confirmation step.
