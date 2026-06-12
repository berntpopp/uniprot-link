# uniprot-link v0.9.0 — Assessment Closure Record

Closes every finding in
[`mcp-assessment-v0.8.0-consumer-tester.md`](mcp-assessment-v0.8.0-consumer-tester.md)
(overall **8.0/10**, docked for a silent isoform correctness defect). Each
finding was **reproduced live before the fix and re-verified live after**, on the
real UniProt QLever endpoint (release 2026_01). Grounded in 2025–2026 MCP
best-practice research (Anthropic tool-writing guidance, MCP spec 2025-06-18,
FastMCP). Spec + plan:
[`docs/superpowers/specs/2026-06-12-v0.9.0-assessment-remediation-design.md`](superpowers/specs/2026-06-12-v0.9.0-assessment-remediation-design.md)
·
[`docs/superpowers/plans/2026-06-12-v0.9.0-assessment-remediation.md`](superpowers/plans/2026-06-12-v0.9.0-assessment-remediation.md).

## Findings closed

| ID | Sev | Finding | Resolution | Live evidence |
|----|-----|---------|------------|---------------|
| F1 | HIGH | `get_protein_features` silently returns 0 for an isoform accession | features/xref/**go** builders anchor on the base entry; `require_entry` rejects typo'd isoforms; entry tools attach `requested_accession`+`isoform_note` (matches `get_protein`) | `features(P05067-2,[domain,region])` → **12** (was 0) |
| F2 | HIGH | `get_protein_sequence` `not_found` for valid isoforms | `protein_sequence` anchors on base; service returns the **requested isoform's** specific sequence (mass computed, `up:mass` is `-1`-only) | `sequence(P05067-2)` → that isoform (was `not_found`) |
| F3 | MED | exact-key `find_proteins` runs as cold scans | mnemonic fast-path = single bound query; offset-0 reviewed-first legs run concurrently | mnemonic single query **3.9 s** vs prior 3-query **7.9 s** |
| F4 | MED | `latency_profile` under-states two tools | features/diseases moved `fast`→`medium` (700–2500 ms); bands reframed by query class | measured features 2.2 s / diseases 2.1 s cold |
| F5 | MED | `default_select_limit:50` contradicts 25-per-page paging | `find_proteins_page_size:25` + `find_proteins_max_limit:200` + xref cap documented; `default_select_limit` scoped to run_sparql_query | capabilities self-consistent |
| F6 | LOW | `search_example_queries` lacks `query`/`q` alias | `query`/`q` → `text` aliases (no-op where `query` is the canonical param) | alias unit + facade tests |
| F7 | LOW | no canonical-only full sequence mode | `canonical_only` flag on `get_protein_sequence` + `requested_isoform` field | `canonical_only=True` omits isoforms |
| F8 | LOW | CSV/TSV SELECT mislabeled `query_type:"RDF/raw"` | report true query form + separate `serialization` field | CSV SELECT → `query_type:"SELECT"` |
| F9 | LOW | gene page dominated by TrEMBL noise | `reviewed_count` + `reviewed_hint` on `find_proteins` | BRCA1 page surfaces reviewed_count |
| — | — | obsolete/demerged path untested | live regression tests retained + isoform-family live coverage added | 45 live integration tests green |

## Verification

- **`make ci-local` green:** ruff format + check, 600-line cap, mypy strict (40
  source files), **221 unit tests**.
- **45 live integration tests** pass against the real endpoint (incl. the new
  F1/F2/F3/F7/F9 isoform/latency regressions and the obsolete/demerged path).
- **`research/verify_queries.py`** confirms every query builder live, including
  the isoform anchors and the mnemonic fast-path timing.

## Projected re-score

| Dimension | v0.8.0 | v0.9.0 (projected) | Why |
|-----------|:------:|:------:|-----|
| Discoverability | 9 | 9.5 | documented paging/limits; honest bands |
| Token efficiency | 8.5 | 9.5 | `canonical_only` removes the isoform-sequence sink (F7) |
| Observability | 8.5 | 9.5 | latency bands now match reality (F4) |
| Error handling | 8.5 | 9.5 | isoform silent-empty eliminated; the one discipline lapse closed (F1) |
| Speed / latency | 6 | 7.5 | mnemonic fast-path + concurrent legs (F3); endpoint floor remains |
| Correctness | 6 | 9.5 | the F1/F2 isoform defect — the score cap — is fixed and live-verified |
| **Overall** | **8.0** | **>9.5** | the blocking correctness defect is gone; every other finding closed |

Speed stays the one sub-9.5 dimension: it is upstream-bound (QLever cold
gene-join ~6 s) and we deliberately do **not** add an `ORDER BY` or restructure
joins in ways that risk the 45-min timeout (AGENTS.md QLever discipline). The
mnemonic fast-path and concurrent legs take the worst cases from ~8–10 s to
~4–6 s without that risk.

## Deployment note

The deployed/connected MCP server still reports **v0.8.0** until redeployed; these
fixes are on branch `feat/v0.9.0-assessment-remediation`. Per the standing
deploy-drift rule, confirm `get_server_capabilities().server_version` before
trusting a live re-test. Redeploy = merge to `main` + `make docker-build` +
recreate the container with `UNIPROT_LINK_GIT_SHA`.
