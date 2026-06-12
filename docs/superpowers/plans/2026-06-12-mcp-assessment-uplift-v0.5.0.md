# v0.5.0 Assessment Uplift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the v0.4.0 LLM-consumer assessment punch-list (F1–F8) to push both scores > 9.5/10.

**Architecture:** Eight small, independent changes (C1–C8) across the MCP envelope, capabilities, shaping, service, next-commands, and constants modules. No SPARQL query-builder *semantic* changes (QLever risk surface untouched). TDD per change; atomic commits.

**Tech Stack:** Python 3.12, FastMCP 3.4.2, pytest, respx, Ruff, mypy (strict). `make ci-local` is the gate.

**Spec:** `docs/superpowers/specs/2026-06-12-mcp-assessment-uplift-v0.5.0-design.md`

---

## File map

| File | Change |
|------|--------|
| `uniprot_link/mcp/envelope.py` | C1: drop `_BASE_META`/`_provenance_meta`; lean per-call `_meta` |
| `uniprot_link/mcp/capabilities.py` | C1 `provenance_policy`+`per_call_meta`; C2 `latency_profile`; C8 `result_ordering` |
| `uniprot_link/services/constants.py` | C3 `COMMON_TAXA`+`lookup_common_taxon`; C7 residue mass table |
| `uniprot_link/services/sparql_service.py` | C3 curated taxon path; C4 domain/region hint; C8 total sort |
| `uniprot_link/services/shaping.py` | C6 variant substitution omit; C7 `average_mass`+computed isoform mass |
| `uniprot_link/services/queries/validation.py` | C5 `looks_like_accession` |
| `uniprot_link/mcp/next_commands.py` | C5 `looks_like_gene_symbol`; smarter recovery |
| `uniprot_link/mcp/tools/proteins.py` | C4 prepend region next_command; C8/C2 description |
| `uniprot_link/mcp/tools/taxonomy.py`, `query.py` | C2 latency cue in descriptions |
| `uniprot_link/__init__.py` | version 0.4.0 → 0.5.0 |
| `docs/mcp-assessment-v0.4.0.md` | v0.5.0 re-assessment note |
| `tests/...` | new + updated assertions per change |

---

## Task C1 — Trim per-call `_meta`; provenance discovery-only

**Files:** Modify `uniprot_link/mcp/envelope.py`, `uniprot_link/mcp/capabilities.py`; Test `tests/unit/test_service_and_tools.py`, `tests/unit/test_capabilities.py`.

- [ ] **Step 1 — Update test for lean per-call meta.** Replace `test_provenance_is_compact` (≈ lines 280–287) in `tests/unit/test_service_and_tools.py`:

```python
@pytest.mark.asyncio
async def test_per_call_meta_is_lean(service_factory: Any) -> None:
    """Per-call _meta carries only dynamic fields; static provenance is demoted."""
    from uniprot_link.mcp.capabilities import build_capabilities

    svc = service_factory(_protein_summary_json("P38398"))
    out = await _run_get_protein(svc, "P38398")  # helper already in this module
    meta = out["_meta"]
    assert set(meta) <= {"tool", "request_id", "next_commands"}
    assert "unsafe_for_clinical_use" not in meta
    assert "uniprot_release" not in meta
    assert "citation" not in meta
    # provenance still authoritative in capabilities
    cap = build_capabilities()
    assert cap["research_use_only"] is True
    assert cap["uniprot_release"]
    assert "Nucleic Acids Res" in cap["recommended_citation"]
    assert cap["per_call_meta"] == ["tool", "request_id", "next_commands"]
    assert "provenance_policy" in cap
```

Also update the two assertions that read `out["_meta"]["uniprot_release"]` / `["unsafe_for_clinical_use"]` (≈ lines 276, 506–507) to assert those keys are **absent** from `_meta` and present in `build_capabilities()` instead.

- [ ] **Step 2 — Run, expect FAIL.** `make test` (or `pytest tests/unit/test_service_and_tools.py -k per_call_meta -v`). Expect fail (keys still present / `per_call_meta` missing).

- [ ] **Step 3 — Edit `envelope.py`.** Remove `_BASE_META` and `_provenance_meta`, drop the now-unused `UNIPROT_RELEASE` import, and replace the comment block (lines 32–39) with:

```python
# Per-call _meta is kept lean: static provenance (research-use restriction,
# citation DOI, UniProt release) lives ONLY in get_server_capabilities — repeating
# it per call is non-actionable token overhead (MCP/Anthropic context economy).
# Per-call _meta carries only dynamic fields: tool, request_id, next_commands.
```

In `_error_envelope`, change the `_meta` line to:

```python
        "_meta": {"tool": context.tool_name, "request_id": _request_id()},
```

In `run_mcp_tool` success path, change the `_meta` assembly to:

```python
            result["_meta"] = {
                **existing_meta,
                "tool": tool_name,
                "request_id": _request_id(),
            }
```

- [ ] **Step 4 — Edit `capabilities.py`.** After the `"default_response_mode": "compact",` line in `build_capabilities()` add:

```python
        "provenance_policy": (
            "Static provenance (research-use restriction, citation, UniProt "
            "release) is declared here and applies to ALL tool outputs; it is "
            "not repeated per-call to conserve context tokens."
        ),
        "per_call_meta": ["tool", "request_id", "next_commands"],
```

- [ ] **Step 5 — Run, expect PASS.** `pytest tests/unit/test_service_and_tools.py -k "per_call_meta or meta" tests/unit/test_capabilities.py -v`.

- [ ] **Step 6 — Commit.** `git add -A && git commit -m "feat(mcp): demote static provenance from per-call _meta to capabilities (C1, F1)"`

## Task C2 — Advertise per-tool latency

**Files:** Modify `uniprot_link/mcp/capabilities.py`; descriptions in `uniprot_link/mcp/tools/proteins.py`, `taxonomy.py`, `query.py`; Test `tests/unit/test_capabilities.py`.

- [ ] **Step 1 — Test.** Add to `tests/unit/test_capabilities.py`:

```python
def test_capabilities_has_latency_profile() -> None:
    from uniprot_link.mcp.capabilities import TOOLS, build_capabilities

    cap = build_capabilities()
    lp = cap["latency_profile"]
    assert "note" in lp and "bands" in lp
    listed = " ".join(
        t for band in lp["bands"].values() for t in band["tools"]
    )
    # every real tool name appears somewhere in the profile
    for tool in TOOLS:
        assert tool.split("(")[0] in listed or tool in listed
```

- [ ] **Step 2 — Run, expect FAIL** (`latency_profile` missing).

- [ ] **Step 3 — Edit `capabilities.py`.** After the `per_call_meta` line add:

```python
        "latency_profile": {
            "note": (
                "Cold upstream SPARQL latency. An identical repeated call is "
                "served from a 1h in-process cache in ~0 ms (see the `cached` "
                "field on responses). Bands are coarse guidance, not promises."
            ),
            "bands": {
                "fast": {
                    "typical_ms": "0-700",
                    "tools": [
                        "get_protein", "get_protein_sequence",
                        "get_protein_features", "get_protein_variants",
                        "get_protein_diseases", "get_protein_cross_references",
                        "get_protein_go_terms", "map_identifiers",
                        "get_taxon (by id or curated name)",
                        "get_server_capabilities",
                    ],
                },
                "medium": {
                    "typical_ms": "1000-3000",
                    "tools": ["search_example_queries", "get_example_query"],
                },
                "slow_cold_scan": {
                    "typical_ms": "3000-12000",
                    "tools": [
                        "find_proteins (cold)",
                        "get_taxon (uncached name scan)",
                        "run_sparql_query (unbounded or federated)",
                    ],
                },
            },
        },
```

- [ ] **Step 4 — Add latency cue to descriptions.** Append to the `find_proteins` description (proteins.py): `" Cold search can take several seconds; an identical repeat is cached (~0 ms)."` Append to `get_taxon` description (taxonomy.py): `" Numeric-id and common-organism-name lookups are fast; an uncommon name triggers a multi-second taxonomy scan."` Append to `run_sparql_query` description (query.py): `" Unbounded or federated queries can take 10-60 s; bound lookups return in <2 s."`

- [ ] **Step 5 — Run, expect PASS.** `pytest tests/unit/test_capabilities.py -v`.

- [ ] **Step 6 — Commit.** `git commit -am "feat(mcp): advertise per-tool latency_profile + description cues (C2, F2)"`

## Task C3 — Curated common-organism name index for `get_taxon`

**Files:** Modify `uniprot_link/services/constants.py`, `uniprot_link/services/sparql_service.py`; Test `tests/unit/test_service_and_tools.py`, `tests/integration/test_live.py`.

> Before coding: verify each curated taxon id live via `get_taxon(<id>)` and confirm the scientific name matches. Only keep ids confirmed against the endpoint.

- [ ] **Step 1 — Add `COMMON_TAXA` + `lookup_common_taxon` to `constants.py`:**

```python
# Curated name -> taxon-id index for model organisms (the overwhelming majority
# of real name lookups). A hit lets get_taxon resolve a name with ZERO network
# round-trips; misses fall through to the endpoint scan. Each record's taxon_id
# is the one UniProt reviewed entries use (so it feeds find_proteins directly).
_COMMON_TAXA_RECORDS: list[dict[str, Any]] = [
    {"taxon_id": "9606", "scientific_name": "Homo sapiens", "common_name": "Human", "rank": "Species", "aliases": ["human"]},
    {"taxon_id": "10090", "scientific_name": "Mus musculus", "common_name": "Mouse", "rank": "Species", "aliases": ["mouse", "house mouse"]},
    {"taxon_id": "10116", "scientific_name": "Rattus norvegicus", "common_name": "Rat", "rank": "Species", "aliases": ["rat", "brown rat"]},
    {"taxon_id": "9913", "scientific_name": "Bos taurus", "common_name": "Bovine", "rank": "Species", "aliases": ["cow", "cattle", "bovine"]},
    {"taxon_id": "9823", "scientific_name": "Sus scrofa", "common_name": "Pig", "rank": "Species", "aliases": ["pig"]},
    {"taxon_id": "9031", "scientific_name": "Gallus gallus", "common_name": "Chicken", "rank": "Species", "aliases": ["chicken"]},
    {"taxon_id": "9615", "scientific_name": "Canis lupus familiaris", "common_name": "Dog", "rank": "Subspecies", "aliases": ["dog"]},
    {"taxon_id": "9544", "scientific_name": "Macaca mulatta", "common_name": "Rhesus macaque", "rank": "Species", "aliases": ["rhesus macaque", "rhesus monkey"]},
    {"taxon_id": "9598", "scientific_name": "Pan troglodytes", "common_name": "Chimpanzee", "rank": "Species", "aliases": ["chimpanzee", "chimp"]},
    {"taxon_id": "7955", "scientific_name": "Danio rerio", "common_name": "Zebrafish", "rank": "Species", "aliases": ["zebrafish"]},
    {"taxon_id": "8364", "scientific_name": "Xenopus tropicalis", "common_name": "Western clawed frog", "rank": "Species", "aliases": ["xenopus tropicalis"]},
    {"taxon_id": "7227", "scientific_name": "Drosophila melanogaster", "common_name": "Fruit fly", "rank": "Species", "aliases": ["fruit fly", "drosophila"]},
    {"taxon_id": "6239", "scientific_name": "Caenorhabditis elegans", "rank": "Species", "aliases": ["c. elegans", "c elegans", "roundworm"]},
    {"taxon_id": "3702", "scientific_name": "Arabidopsis thaliana", "common_name": "Thale cress", "rank": "Species", "aliases": ["arabidopsis", "thale cress", "mouse-ear cress"]},
    {"taxon_id": "4577", "scientific_name": "Zea mays", "common_name": "Maize", "rank": "Species", "aliases": ["maize", "corn"]},
    {"taxon_id": "39947", "scientific_name": "Oryza sativa subsp. japonica", "common_name": "Rice", "rank": "Subspecies", "aliases": ["rice", "oryza sativa"]},
    {"taxon_id": "559292", "scientific_name": "Saccharomyces cerevisiae (strain ATCC 204508 / S288C)", "common_name": "Baker's yeast", "rank": "Strain", "aliases": ["saccharomyces cerevisiae", "baker's yeast", "bakers yeast", "brewer's yeast", "yeast", "budding yeast"]},
    {"taxon_id": "284812", "scientific_name": "Schizosaccharomyces pombe (strain 972 / ATCC 24843)", "common_name": "Fission yeast", "rank": "Strain", "aliases": ["schizosaccharomyces pombe", "fission yeast", "s. pombe"]},
    {"taxon_id": "83333", "scientific_name": "Escherichia coli (strain K12)", "common_name": "E. coli K-12", "rank": "Strain", "aliases": ["escherichia coli", "e. coli", "e coli", "ecoli"]},
    {"taxon_id": "2697049", "scientific_name": "Severe acute respiratory syndrome coronavirus 2", "common_name": "SARS-CoV-2", "rank": "Species", "aliases": ["sars-cov-2", "sars cov 2", "sars-cov2", "covid", "covid-19"]},
]
COMMON_TAXA: dict[str, dict[str, str]] = {}
for _rec in _COMMON_TAXA_RECORDS:
    _names = [_rec["scientific_name"], _rec.get("common_name"), *_rec.get("aliases", [])]
    _record = {
        k: _rec[k] for k in ("taxon_id", "scientific_name", "common_name", "rank") if _rec.get(k)
    }
    for _name in _names:
        if _name:
            COMMON_TAXA[_name.lower()] = _record


def lookup_common_taxon(name: str) -> dict[str, str] | None:
    """Return a curated taxon record for a common organism name, else None."""
    return COMMON_TAXA.get(name.strip().lower())
```

(Add `from typing import Any` to constants.py imports if absent.)

- [ ] **Step 2 — Unit test.** Add to `tests/unit/test_service_and_tools.py`:

```python
@pytest.mark.asyncio
async def test_get_taxon_common_name_is_curated() -> None:
    """A model-organism name resolves with no SPARQL call."""
    from uniprot_link.services.sparql_service import SparqlService

    class _NoCallClient:
        async def execute(self, *a: Any, **k: Any) -> Any:
            raise AssertionError("curated path must not hit the endpoint")

    svc = SparqlService(_NoCallClient(), _config())  # _config() helper in module
    out = await svc.get_taxon("Homo sapiens")
    assert out["match_source"] == "curated_common_index"
    assert out["match_count"] == 1
    assert out["matches"][0]["taxon_id"] == "9606"
    assert out["elapsed_ms"] == 0.0
    out2 = await svc.get_taxon("human")
    assert out2["matches"][0]["taxon_id"] == "9606"
```

(If a `_config()`/fake-client helper does not already exist in the test module, reuse the existing `service_factory` fixture pattern; adapt the no-call client to it.)

- [ ] **Step 3 — Run, expect FAIL** (`match_source` missing / endpoint called).

- [ ] **Step 4 — Edit `get_taxon` in `sparql_service.py`.** Import `lookup_common_taxon`; insert at the top of the by-name branch (after the `taxon.isdigit()` block, before the scan):

```python
        record = S_lookup_common_taxon(taxon)
        if record is not None:
            return {
                "query": taxon,
                "match_count": 1,
                "matches": [record],
                "match_source": "curated_common_index",
                "elapsed_ms": 0.0,
                "cached": True,
            }
        rows_json, qmeta = await self._select_timed(Q.resolve_taxon_by_name(taxon))
        matches = S.shape_taxon_resolutions(rows_json)
        if not matches:
            raise NotFoundError(f"No taxon matched '{taxon}'.")
        return {
            "query": taxon, "match_count": len(matches), "matches": matches,
            "match_source": "endpoint_scan", **qmeta,
        }
```

Import line: `from uniprot_link.services.constants import (..., lookup_common_taxon as S_lookup_common_taxon)` (or import the name directly and call it).

- [ ] **Step 5 — Run, expect PASS.** `pytest tests/unit/test_service_and_tools.py -k taxon -v`.

- [ ] **Step 6 — Live integration test.** Add to `tests/integration/test_live.py`:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_common_taxa_ids_resolve_live(service: Any) -> None:
    """Every curated taxon id resolves and its scientific name is consistent."""
    from uniprot_link.services.constants import _COMMON_TAXA_RECORDS

    for rec in _COMMON_TAXA_RECORDS:
        out = await service.get_taxon(rec["taxon_id"])
        got = out["scientific_name"].lower()
        # curated scientific name shares its leading binomial with the endpoint's
        assert rec["scientific_name"].lower().split(" (")[0][:12] in got
```

- [ ] **Step 7 — Commit.** `git commit -am "feat(taxon): curated common-organism name index (C3, F3)"`

## Task C4 — `domain` → `region` proactive hint

**Files:** Modify `uniprot_link/services/sparql_service.py`, `uniprot_link/mcp/tools/proteins.py`; Test `tests/unit/test_service_and_tools.py`, `tests/integration/test_live.py`.

- [ ] **Step 1 — Test (service).** Add to `tests/unit/test_service_and_tools.py` a test that calls `get_features` with a mocked feature result containing a single `domain` and asserts `payload["domain_region_hint"]["suggestion"]["arguments"]["feature_types"] == ["domain", "region"]`; and a second call with `feature_types=["region"]` (or `None`) asserts no `domain_region_hint` key.

- [ ] **Step 2 — Run, expect FAIL.**

- [ ] **Step 3 — Edit `get_features`.** Before `return payload`:

```python
        requested = {ft.strip().lower() for ft in (feature_types or [])}
        if "domain" in requested and "region" not in requested:
            payload["domain_region_hint"] = {
                "message": (
                    "UniProt types some domain-scale architecture as 'region' "
                    "(catalytic, binding, or interaction regions), not 'domain'. "
                    "Re-request with feature_types including 'region' to capture "
                    "the full domain architecture."
                ),
                "suggestion": {
                    "tool": "get_protein_features",
                    "arguments": {
                        "accession": acc,
                        "feature_types": ["domain", "region"],
                    },
                },
            }
```

- [ ] **Step 4 — Edit the tool to surface the hint in next_commands** (`proteins.py`, `get_protein_features` body):

```python
            payload = await get_sparql_service().get_features(accession, feature_types)
            nxt = after_entry_subresource(
                payload["accession"], "get_protein_features", count=payload.get("count")
            )
            hint = payload.get("domain_region_hint")
            if hint and hint.get("suggestion"):
                nxt = [hint["suggestion"], *nxt][:2]
            payload["_meta"] = {"next_commands": nxt}
            return payload
```

- [ ] **Step 5 — Run, expect PASS.**

- [ ] **Step 6 — Live test.** Add to `test_live.py`: `get_features("Q96T60", ["domain"])` → assert `domain_region_hint` present and its suggestion targets `["domain","region"]`.

- [ ] **Step 7 — Commit.** `git commit -am "feat(features): domain->region hint when region omitted (C4, F4)"`

## Task C5 — Accession-shape-aware error recovery

**Files:** Modify `uniprot_link/services/queries/validation.py`, `uniprot_link/mcp/next_commands.py`; Test `tests/unit/test_next_commands.py`.

- [ ] **Step 1 — Add `looks_like_accession` to `validation.py`:**

```python
_ACCESSION_LIKE_RE = re.compile(r"^[A-Za-z][0-9][A-Za-z0-9]{4,}(-\d+)?$")


def looks_like_accession(value: str) -> bool:
    """True if value is a real OR near-miss UniProtKB accession (not a gene).

    A near-miss is the accession interior signature: a letter, a digit, then 4+
    alnum chars (e.g. ``Q96T60XYZ``). Used to keep a mangled accession from being
    replayed as a gene symbol in error recovery.
    """
    v = value.strip()
    return bool(_ACCESSION_RE.match(v.upper()) or _ACCESSION_LIKE_RE.match(v))
```

- [ ] **Step 2 — Update `tests/unit/test_next_commands.py`** (the `protein_not_found_recovery` test, ≈ lines 35–39):

```python
def test_protein_recovery_excludes_mangled_accession() -> None:
    from uniprot_link.mcp.next_commands import protein_not_found_recovery

    bad = protein_not_found_recovery("Q96T60XYZ")  # accession-shaped, invalid
    assert not any(c["tool"] == "find_proteins" for c in bad)
    numeric = protein_not_found_recovery("999999")
    assert not any(c["tool"] == "find_proteins" for c in numeric)
    gene = protein_not_found_recovery("BRCA1")      # a gene in the accession slot
    assert gene[0] == {"tool": "find_proteins", "arguments": {"gene": "BRCA1"}}
    g6pd = protein_not_found_recovery("G6PD")        # real gene, digit at pos 2
    assert any(c["tool"] == "find_proteins" for c in g6pd)
```

- [ ] **Step 3 — Run, expect FAIL.**

- [ ] **Step 4 — Edit `next_commands.py`.** Add import + new logic; replace `protein_not_found_recovery`:

```python
from uniprot_link.services.queries.validation import looks_like_accession

# A gene-symbol shape: starts with a letter, short, alnum/.-_ only (e.g. BRCA1).
_GENE_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,11}$")


def looks_like_gene_symbol(value: str) -> bool:
    """True only for a genuine gene-symbol shape (never an accession attempt)."""
    v = (value or "").strip()
    if not v or not _GENE_SHAPE.match(v):
        return False
    return not looks_like_accession(v)


def protein_not_found_recovery(value: str) -> list[dict[str, Any]]:
    """Recovery for a failed get_protein lookup.

    A genuine gene symbol typed into the accession slot (e.g. ``BRCA1``) is
    redirected to find_proteins(gene=...). A mangled/near-miss accession
    (``Q96T60XYZ``) or digit blob is NOT — it points at discovery instead.
    """
    if looks_like_gene_symbol(value):
        return [cmd("find_proteins", gene=value.strip()), cmd("get_server_capabilities")]
    return [cmd("get_server_capabilities"), cmd("search_example_queries", text="protein")]
```

- [ ] **Step 5 — Run, expect PASS.** `pytest tests/unit/test_next_commands.py -v`.

- [ ] **Step 6 — Commit.** `git commit -am "fix(recovery): never replay a mangled accession as gene= (C5, F5)"`

## Task C6 — Variant `substitution`: omit when inapplicable

**Files:** Modify `uniprot_link/services/shaping.py`; Test `tests/unit/test_shaping.py`.

- [ ] **Step 1 — Test.** Add to `tests/unit/test_shaping.py`:

```python
def test_variant_empty_substitution_is_omitted() -> None:
    from uniprot_link.services.shaping import shape_variants

    res = {"results": {"bindings": [
        {"begin": {"value": "408", "datatype": "http://www.w3.org/2001/XMLSchema#int"},
         "end": {"value": "408", "datatype": "http://www.w3.org/2001/XMLSchema#int"},
         "wildType": {"value": "T"}, "substitution": {"value": ""},
         "comment": {"value": "In AOA4."}},
    ]}}
    v = shape_variants(res)[0]
    assert "substitution" not in v
    assert v["variant_type"] == "other"
    assert "notation" not in v
```

(Confirm an existing happy-path substitution test still asserts `substitution`+`notation` present; if none, add one.)

- [ ] **Step 2 — Run, expect FAIL** (`substitution` is `""`).

- [ ] **Step 3 — Edit `shape_variants` merge** (`shaping.py`): change `"substitution": row.get("substitution"),` to `"substitution": row.get("substitution") or None,`. In `_classify_variant`, after setting `variant_type`, add:

```python
    if not v.get("substitution"):
        v.pop("substitution", None)
```

- [ ] **Step 4 — Run, expect PASS.** `pytest tests/unit/test_shaping.py -k variant -v`.

- [ ] **Step 5 — Commit.** `git commit -am "fix(variants): omit empty substitution instead of '' (C6, F6)"`

## Task C7 — Computed isoform `mass_da`

**Files:** Modify `uniprot_link/services/constants.py`, `uniprot_link/services/shaping.py`; Test `tests/unit/test_shaping.py`.

- [ ] **Step 1 — Add residue mass table to `constants.py`:**

```python
# Average isotopic residue masses (Da) — standard ExPASy/UniProt values. Sum of
# residue masses + one water gives the average molecular mass UniProt reports as
# up:mass. Used to derive mass for non-canonical isoforms (UniProt asserts up:mass
# only on the canonical sequence).
AVERAGE_RESIDUE_MASS: dict[str, float] = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886, "C": 103.1388,
    "E": 129.1155, "Q": 128.1307, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "L": 113.1594, "K": 128.1741, "M": 131.1926, "F": 147.1766, "P": 97.1167,
    "S": 87.0782, "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
    "U": 150.0388, "O": 237.3018,
}
WATER_MASS = 18.01524
```

- [ ] **Step 2 — Add `average_mass` to `shaping.py`** (import the two constants):

```python
def average_mass(sequence: str) -> int | None:
    """Average molecular mass (Da) from a residue sequence.

    Returns None if the sequence contains a residue with no defined average mass
    (e.g. ambiguous B/Z/X) rather than guessing.
    """
    if not sequence:
        return None
    total = WATER_MASS
    for aa in sequence:
        residue = AVERAGE_RESIDUE_MASS.get(aa)
        if residue is None:
            return None
        total += residue
    return round(total)
```

- [ ] **Step 3 — Tests.** Add to `tests/unit/test_shaping.py`:

```python
def test_average_mass_matches_uniprot_canonical() -> None:
    from uniprot_link.services.shaping import average_mass

    q96t60_1 = (
        "MGEVEAPGRLWLESPPGGAPPIFLPSDGQALVLGRGPLTQVTDRKCSRTQVELVADPETRTVAVKQLGVNPST"
        "TGTQELKPGLEGSLGVGDTLYLVNGLHPLTLRWEETRTPESQPDTPPGTPLVSQDEKRDAELPKKRMRKSNPG"
        "WENLEKLLVFTAAGVKPQGKVAGFDLDGTLITTRSGKVFPTGPSDWRILYPEIPRKLRELEAEGYKLVIFTNQ"
        "MSIGRGKLPAEEFKAKVEAVVEKLGVPFQVLVATHAGLYRKPVTGMWDHLQEQANDGTPISIGDSIFVGDAAG"
        "RPANWAPGRKKKDFSCADRLFALNLGLPFATPEEFFLKWPAAGFELPAFDPRTVSRSGPLCLPESRALLSASP"
        "EVVVAVGFPGAGKSTFLKKHLVSAGYVHVNRDTLGSWQRCVTTCETALKQGKRVAIDNTNPDAASRARYVQCA"
        "RAAGVPCRCFLFTATLEQARHNNRFREMTDSSHIPVSDMVMYGYRKQFEAPTLAEGFSAILEIPFRLWVEPRL"
        "GRLYCQFSEG"
    )
    assert abs(average_mass(q96t60_1) - 57076) <= 2


def test_isoform_mass_is_computed_when_absent() -> None:
    from uniprot_link.services.shaping import shape_sequences

    res = {"results": {"bindings": [
        {"isoform": {"value": "http://purl.uniprot.org/isoforms/Q96T60-2"},
         "length": {"value": "5", "datatype": "http://www.w3.org/2001/XMLSchema#int"},
         "value": {"value": "ACDEF"}},
    ]}}
    iso = shape_sequences(res)[0]
    assert isinstance(iso["mass_da"], int)
    assert iso["mass_computed"] is True
```

- [ ] **Step 4 — Run, expect FAIL.**

- [ ] **Step 5 — Edit `shape_sequences`** to compute mass when absent:

```python
    for row in rows(result_json):
        iso = row.get("isoform", "")
        mass = row.get("mass")
        seq = row.get("value")
        entry: dict[str, Any] = {
            "isoform": accession_from_uri(iso),
            "canonical": iso.endswith("-1"),
            "length": row.get("length"),
            "mass_da": mass,
            "sequence": seq,
        }
        if mass is None and seq:
            computed = average_mass(seq)
            if computed is not None:
                entry["mass_da"] = computed
                entry["mass_computed"] = True
        out.append(entry)
```

- [ ] **Step 6 — Run, expect PASS.** `pytest tests/unit/test_shaping.py -k mass -v`.

- [ ] **Step 7 — Live test.** Add to `test_live.py`: `get_sequence("Q96T60", "standard")` → assert the non-canonical isoform's `mass_da` is a non-null int and `mass_computed` is True.

- [ ] **Step 8 — Commit.** `git commit -am "feat(sequence): compute mass for non-canonical isoforms (C7, F7)"`

## Task C8 — Deterministic `find_proteins` ordering

**Files:** Modify `uniprot_link/services/sparql_service.py`, `uniprot_link/mcp/capabilities.py`, `uniprot_link/mcp/tools/proteins.py`; Test `tests/unit/test_service_and_tools.py`, `tests/unit/test_capabilities.py`.

- [ ] **Step 1 — Test.** Add a unit test that calls `_sort_by_mnemonic` with two entries sharing a mnemonic and asserts they order by accession, stably across repeated sorts; and a capabilities test asserting `cap["result_ordering"]["find_proteins"]` exists and mentions "accession".

- [ ] **Step 2 — Run, expect FAIL.**

- [ ] **Step 3 — Edit `_sort_by_mnemonic`:**

```python
def _sort_by_mnemonic(proteins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort a (small, already-LIMITed) page by mnemonic then accession.

    A total order with accession as the unique final tiebreak makes pages
    deterministic across identical calls (pagination stability).
    """
    return sorted(
        proteins,
        key=lambda p: (
            p.get("mnemonic") is None,
            p.get("mnemonic") or "",
            p.get("accession") or "",
        ),
    )
```

- [ ] **Step 4 — Document in `capabilities.py`** (after `recommended_workflows` or near `limits`):

```python
        "result_ordering": {
            "find_proteins": (
                "Reviewed (Swiss-Prot) first, then by mnemonic (entry name), then "
                "accession — deterministic across identical calls and pages."
            ),
        },
```

- [ ] **Step 5 — Document in `find_proteins` description** (proteins.py): append `" Results are ordered reviewed-first, then by mnemonic, then accession (stable across pages)."`

- [ ] **Step 6 — Run, expect PASS.**

- [ ] **Step 7 — Commit.** `git commit -am "feat(find): deterministic reviewed->mnemonic->accession ordering (C8, F8)"`

## Task C9 — Version bump + re-assessment note

**Files:** Modify `uniprot_link/__init__.py`, `docs/mcp-assessment-v0.4.0.md`.

- [ ] **Step 1 — Bump version.** `__version__ = "0.5.0"` in `uniprot_link/__init__.py`. Update `tests/unit/test_capabilities.py` / `test_buildinfo.py` if they pin `"0.4.0"`.

- [ ] **Step 2 — Append a v0.5.0 results section** to `docs/mcp-assessment-v0.4.0.md` mapping F1–F8 → fix → expected re-score (Token efficiency 7→9–10; Speed 7→9; Error/Structured 9→10).

- [ ] **Step 3 — Commit.** `git commit -am "release: v0.5.0 — assessment uplift (C1-C8 / F1-F8)"`

## Final verification

- [ ] **Run `make ci-local`** — format, lint, lint-loc (≤600 LOC/module), mypy strict, unit tests. Expect PASS.
- [ ] **Run `make test-integration`** — live assertions for C3/C4/C7 + existing suite. Expect PASS.
- [ ] **Drive the live MCP** (if redeployed) or the service layer to re-confirm each F# is closed; summarize the re-score.

---

## Self-review

- **Spec coverage:** C1→F1, C2→F2, C3→F3, C4→F4, C5→F5, C6→F6, C7→F7, C8→F8, plus version/doc (C9). All eight findings + rejected-suggestion rationale (in spec §5) covered. ✓
- **Placeholder scan:** every code step shows real code; test helper reuse (`service_factory`, `_config`) flagged where the executor must adapt to existing fixtures. ✓
- **Type consistency:** `lookup_common_taxon`/`looks_like_accession`/`looks_like_gene_symbol`/`average_mass` signatures match call sites; `domain_region_hint.suggestion` is a `{tool, arguments}` dict consumed by the tool layer's next_commands prepend. ✓
