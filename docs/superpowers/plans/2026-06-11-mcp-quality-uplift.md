# MCP Quality Uplift Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five correctness bugs and two systemic contract gaps in uniprot-link's typed tools, then trim token cost, to lift the server from 6/10 to >9/10.

**Architecture:** Three waves — P0 correctness (Tasks 1–5), P1 robustness/contract (Tasks 6–9), P2 efficiency/polish (Tasks 10–16). Every fix is a query-builder and/or shaping change with a unit test (mocked, default CI path) plus an integration assertion (`@pytest.mark.integration`, live endpoint). All SPARQL below was validated live against `https://sparql.uniprot.org/sparql` (release 2026_01) during spec research.

**Tech Stack:** Python 3.12, `uv`, FastMCP, httpx, SPARQL 1.1 (QLever), pytest + `respx`, Ruff, mypy strict. Reference spec: `docs/superpowers/specs/2026-06-11-mcp-quality-uplift-design.md`.

---

## Conventions for every task

- **Repo is not git-initialized.** Each task ends with a **Checkpoint** (`make ci-local`) instead of a commit. If you want atomic history, run `git init` first, then commit at each checkpoint with a conventional message.
- **Run unit tests** with `make test-fast` (or `uv run pytest tests/unit/<file> -v` for one file). Integration tests: `make test-integration` (live; not in default CI).
- **Mocking:** unit tests use `service_factory` + `make_select_json` from `tests/conftest.py` (route by query substring, first match wins).
- **Before final handoff:** `make ci-local` green (format, lint, lint-loc, mypy strict, unit tests) per `CLAUDE.md`; re-run `python research/verify_queries.py` after touching `queries.py`.
- **File-size cap:** 600 lines/module (`make lint-loc`). After Task 9, run `make lint-loc`; if `queries.py` > ~560, do Task 9b (extract split) before Wave 3.

---

## File structure (what changes and why)

| File | Responsibility / change |
|---|---|
| `uniprot_link/services/constants.py` | `FEATURE_TYPES["domain"]` fix; add `FEATURE_CLASS_TO_KEY` reverse map; add `GO_ASPECT_ROOTS`. |
| `uniprot_link/services/queries.py` | Rewrite `taxon_details` → `taxon_core` + `taxon_ancestors`; fix `protein_go_terms`, `protein_features`, `protein_variants`, `protein_summary`, `protein_diseases`, `search_example_queries`; add `entry_exists_ask`, `classify_sparql_operation`. |
| `uniprot_link/services/shaping.py` | Rewrite `shape_taxon`; fix `shape_go_terms`, `shape_features`, `shape_variants`, `shape_sequences`, `shape_cross_references`, `shape_diseases`; add `apply_response_mode`. |
| `uniprot_link/services/sparql_service.py` | `get_taxon` two-query concurrency; `require_entry` guard; `run_query` read-only check; `_select` returns elapsed/cached; thread `response_mode`; `truncated` blocks. |
| `uniprot_link/mcp/tools/proteins.py` | `response_mode` params; `disease_associated_only`; `next_commands` on annotation tools. |
| `uniprot_link/mcp/tools/taxonomy.py` | Pass `include_lineage`/`response_mode`. |
| `uniprot_link/mcp/next_commands.py` | New chaining builders for annotation tools. |
| `uniprot_link/mcp/envelope.py` | Compact inline citation; full text to capabilities. |
| `uniprot_link/mcp/capabilities.py` | Version bump; `response_modes`; corrected vocab; contract notes. |
| `CHANGELOG.md` | v0.2.0 entry. |

---

# WAVE 1 — P0 correctness

### Task 1: `get_taxon` — correct direct parent + ordered lineage

**Files:**
- Modify: `uniprot_link/services/queries.py` (`taxon_details` → `taxon_core` + `taxon_ancestors`, ~lines 348–367)
- Modify: `uniprot_link/services/shaping.py` (`shape_taxon` → `shape_taxon_core` + `shape_ancestors`, ~lines 206–220)
- Modify: `uniprot_link/services/sparql_service.py` (`get_taxon`, ~lines 229–240)
- Test: `tests/unit/test_shaping.py`, `tests/unit/test_queries.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_shaping.py`:

```python
def test_shape_ancestors_orders_species_to_root_and_picks_direct_parent():
    from uniprot_link.services.shaping import shape_ancestors
    rows = [
        {"ancestor": "http://purl.uniprot.org/taxonomy/9605", "name": "Homo",
         "rank": "http://purl.uniprot.org/core/Taxonomic_Rank_Genus", "depth": 0},
        {"ancestor": "http://purl.uniprot.org/taxonomy/9604", "name": "Hominidae",
         "rank": "http://purl.uniprot.org/core/Taxonomic_Rank_Family", "depth": 2},
        {"ancestor": "http://purl.uniprot.org/taxonomy/207598", "name": "Homininae",
         "rank": "http://purl.uniprot.org/core/Taxonomic_Rank_Subfamily", "depth": 1},
    ]
    from tests.conftest import make_select_json
    body = make_select_json(["ancestor", "name", "rank", "depth"], rows)
    parent, lineage = shape_ancestors(body)
    assert parent == {"taxon_id": "9605", "scientific_name": "Homo", "rank": "Genus"}
    assert [a["scientific_name"] for a in lineage] == ["Homo", "Homininae", "Hominidae"]
```

- [ ] **Step 2: Run it, expect ImportError/fail**

Run: `uv run pytest tests/unit/test_shaping.py::test_shape_ancestors_orders_species_to_root_and_picks_direct_parent -v`
Expected: FAIL (`cannot import name 'shape_ancestors'`).

- [ ] **Step 3: Replace `taxon_details` in `queries.py`** with two builders:

```python
def taxon_core(taxon_id: str | int) -> str:
    """Build a SELECT for a taxon's own names and rank (one row)."""
    tid = validate_taxon(taxon_id)
    return f"""{prefix_block()}
SELECT ?scientificName ?commonName ?rank
WHERE {{
  taxon:{tid} up:scientificName ?scientificName .
  OPTIONAL {{ taxon:{tid} up:commonName ?commonName }}
  OPTIONAL {{ taxon:{tid} up:rank ?rank }}
}}
LIMIT 1"""


def taxon_ancestors(taxon_id: str | int) -> str:
    """Build a depth-ranked ancestor SELECT (depth 0 = direct parent).

    UniProt asserts ``rdfs:subClassOf`` to the full ancestor closure, so the
    direct parent is the minimal element: the ancestor with no closure member
    between it and the taxon. ``COUNT(?between)`` ranks the chain species->root.
    """
    tid = validate_taxon(taxon_id)
    return f"""{prefix_block()}
SELECT ?ancestor ?name ?rank (COUNT(DISTINCT ?between) AS ?depth)
WHERE {{
  taxon:{tid} rdfs:subClassOf ?ancestor .
  ?ancestor up:scientificName ?name .
  OPTIONAL {{ ?ancestor up:rank ?rank }}
  OPTIONAL {{ taxon:{tid} rdfs:subClassOf ?between .
             ?between rdfs:subClassOf ?ancestor . FILTER(?between != ?ancestor) }}
}}
GROUP BY ?ancestor ?name ?rank
ORDER BY ?depth"""
```

- [ ] **Step 4: Replace `shape_taxon` in `shaping.py`** with:

```python
def shape_taxon_core(result_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shape a taxon's own attributes; ``None`` if the taxon does not exist."""
    data = rows(result_json)
    if not data or not data[0].get("scientificName"):
        return None
    r = data[0]
    core: dict[str, Any] = {
        "scientific_name": r.get("scientificName"),
        "common_name": r.get("commonName"),
        "rank": local_name(r["rank"]).replace("Taxonomic_Rank_", "") if r.get("rank") else None,
    }
    return {k: v for k, v in core.items() if v not in (None, "")}


def _ancestor(r: dict[str, Any]) -> dict[str, Any]:
    a = {
        "taxon_id": taxid_from_uri(r.get("ancestor", "")),
        "scientific_name": r.get("name"),
        "rank": local_name(r["rank"]).replace("Taxonomic_Rank_", "") if r.get("rank") else None,
    }
    return {k: v for k, v in a.items() if v not in (None, "")}


def shape_ancestors(
    result_json: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return ``(direct_parent, lineage)`` ordered species->root from depth rows."""
    data = sorted(rows(result_json), key=lambda r: r.get("depth", 0)
                  if isinstance(r.get("depth"), int) else 0)
    lineage = [_ancestor(r) for r in data]
    parent = lineage[0] if lineage else None
    return parent, lineage
```

Delete the old `shape_taxon`.

- [ ] **Step 5: Update `get_taxon` in `sparql_service.py`** to run both queries concurrently:

```python
import asyncio  # add at top if absent

    async def get_taxon(self, taxon: str, include_lineage: bool = False) -> dict[str, Any]:
        """Resolve a taxon by id (digits) or scientific/common name."""
        taxon = str(taxon).strip()
        if taxon.isdigit():
            core_json, anc_json = await asyncio.gather(
                self._select(Q.taxon_core(taxon)),
                self._select(Q.taxon_ancestors(taxon)),
            )
            core = S.shape_taxon_core(core_json)
            if core is None:
                raise NotFoundError(f"No taxon found for id '{taxon}'.")
            parent, lineage = S.shape_ancestors(anc_json)
            payload: dict[str, Any] = {"taxon_id": taxon, **core}
            if parent:
                payload["parent_taxon_id"] = parent["taxon_id"]
                payload["parent_name"] = parent.get("scientific_name")
                if parent.get("rank"):
                    payload["parent_rank"] = parent["rank"]
            if include_lineage and lineage:
                payload["lineage"] = lineage
            return payload
        matches = S.shape_taxon_resolutions(await self._select(Q.resolve_taxon_by_name(taxon)))
        if not matches:
            raise NotFoundError(f"No taxon matched '{taxon}'.")
        return {"query": taxon, "match_count": len(matches), "matches": matches}
```

Note: `_select` currently returns the json dict; if Task 14 changed its signature, adjust the `gather` unpacking. (Do Task 1 before Task 14.)

- [ ] **Step 6: Run unit test, expect PASS**

Run: `uv run pytest tests/unit/test_shaping.py::test_shape_ancestors_orders_species_to_root_and_picks_direct_parent -v`
Expected: PASS.

- [ ] **Step 7: Add integration assertion** in `tests/integration/test_live.py`:

```python
@pytest.mark.integration
async def test_taxon_human_direct_parent_is_homo(live_service):
    res = await live_service.get_taxon("9606", include_lineage=True)
    assert res["parent_taxon_id"] == "9605"
    assert res["parent_name"] == "Homo"
    assert res["lineage"][0]["scientific_name"] == "Homo"
    assert res["lineage"][-1]["scientific_name"] in {"Eukaryota", "cellular organisms"}
```

(If `live_service` fixture is absent, mirror the existing fixture pattern in `test_live.py`.)

- [ ] **Step 8: Checkpoint** — `make ci-local` and `python research/verify_queries.py`. Expected: green.

---

### Task 2: `get_protein_go_terms` — real aspect grouping

**Files:**
- Modify: `uniprot_link/services/constants.py` (add `GO_ASPECT_ROOTS`)
- Modify: `uniprot_link/services/queries.py` (`protein_go_terms`, ~321–335)
- Modify: `uniprot_link/services/shaping.py` (`shape_go_terms`, ~194–203)
- Test: `tests/unit/test_shaping.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Add constant** to `constants.py`:

```python
# GO top-level roots -> aspect bucket (terms carry no hasOBONamespace here).
GO_ASPECT_ROOTS: dict[str, str] = {
    "GO_0008150": "biological_process",
    "GO_0003674": "molecular_function",
    "GO_0005575": "cellular_component",
}
```

- [ ] **Step 2: Write failing unit test** in `tests/unit/test_shaping.py`:

```python
def test_shape_go_terms_buckets_by_root_aspect():
    from uniprot_link.services.shaping import shape_go_terms
    from tests.conftest import make_select_json
    body = make_select_json(["go", "label", "aspect"], [
        {"go": "http://purl.obolibrary.org/obo/GO_0003677", "label": "DNA binding",
         "aspect": "http://purl.obolibrary.org/obo/GO_0003674"},
        {"go": "http://purl.obolibrary.org/obo/GO_0005634", "label": "nucleus",
         "aspect": "http://purl.obolibrary.org/obo/GO_0005575"},
    ])
    grouped = shape_go_terms(body)
    assert grouped["molecular_function"][0]["id"] == "GO:0003677"
    assert "cellular_component" in grouped
    assert "unknown" not in grouped
```

- [ ] **Step 3: Run it, expect FAIL** (everything buckets under `unknown`).

Run: `uv run pytest tests/unit/test_shaping.py::test_shape_go_terms_buckets_by_root_aspect -v`

- [ ] **Step 4: Update `protein_go_terms` query** — replace the `hasOBONamespace` OPTIONAL:

```python
def protein_go_terms(accession: str) -> str:
    """Build a SELECT for Gene Ontology annotations grouped by aspect root."""
    acc = validate_accession(accession)
    return f"""{prefix_block()}
PREFIX obo: <http://purl.obolibrary.org/obo/>
SELECT ?go ?label ?aspect
WHERE {{
  uniprotkb:{acc} up:classifiedWith ?go .
  FILTER(STRSTARTS(STR(?go), "http://purl.obolibrary.org/obo/GO_"))
  OPTIONAL {{ ?go rdfs:label ?label }}
  OPTIONAL {{ ?go rdfs:subClassOf ?aspect .
             FILTER(?aspect IN (obo:GO_0008150, obo:GO_0003674, obo:GO_0005575)) }}
}}
ORDER BY ?aspect ?label
LIMIT 1000"""
```

- [ ] **Step 5: Update `shape_go_terms`** to map root IRI → bucket name:

```python
def shape_go_terms(result_json: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Group GO annotations into biological_process / molecular_function /
    cellular_component via their top-level root class."""
    from uniprot_link.services.constants import GO_ASPECT_ROOTS
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows(result_json):
        go = row.get("go", "")
        root = local_name(row["aspect"]) if row.get("aspect") else ""
        bucket = GO_ASPECT_ROOTS.get(root, "unknown")
        grouped.setdefault(bucket, []).append(
            {"id": local_name(go).replace("GO_", "GO:"), "label": row.get("label")}
        )
    return grouped
```

- [ ] **Step 6: Run unit test, expect PASS.**

- [ ] **Step 7: Add integration assertion** in `tests/integration/test_live.py`:

```python
@pytest.mark.integration
async def test_go_terms_real_aspects(live_service):
    res = await live_service.get_go_terms("P38398")
    assert {"biological_process", "molecular_function", "cellular_component"} <= set(res["by_aspect"])
    assert "unknown" not in res["by_aspect"]
```

- [ ] **Step 8: Checkpoint** — `make ci-local`. Expected: green.

---

### Task 3: `get_protein_features` — domain filter + vocabulary round-trip

**Files:**
- Modify: `uniprot_link/services/constants.py` (`FEATURE_TYPES["domain"]`; add reverse map)
- Modify: `uniprot_link/services/shaping.py` (`shape_features`, ~130–144)
- Modify: `uniprot_link/services/sparql_service.py` (`get_features`, ~172–179)
- Test: `tests/unit/test_shaping.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Fix the mapping + add reverse map** in `constants.py`:

Change the `"domain"` entry:

```python
    "domain": "Domain_Extent_Annotation",
```

Add after the `FEATURE_TYPES` dict:

```python
# Reverse: annotation class local-name -> friendly key (for round-tripping the
# returned `type` back into a valid feature_types filter input).
FEATURE_CLASS_TO_KEY: dict[str, str] = {cls: key for key, cls in FEATURE_TYPES.items()}
```

- [ ] **Step 2: Write failing unit test** in `tests/unit/test_shaping.py`:

```python
def test_shape_features_round_trips_type_to_filter_key():
    from uniprot_link.services.shaping import shape_features
    from tests.conftest import make_select_json
    body = make_select_json(["type", "begin", "end", "comment"], [
        {"type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
         "begin": 1642, "end": 1736, "comment": "BRCT 1"},
    ])
    out = shape_features(body)
    assert out[0]["type"] == "domain"   # round-trips to the filter key
    assert out[0]["begin"] == 1642
```

- [ ] **Step 3: Run it, expect FAIL** (returns `"Domain_Extent"`).

- [ ] **Step 4: Update `shape_features`** to use the reverse map:

```python
def shape_features(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape feature rows; emit `type` in the feature_types filter vocabulary."""
    from uniprot_link.services.constants import FEATURE_CLASS_TO_KEY
    out: list[dict[str, Any]] = []
    for row in rows(result_json):
        cls = local_name(row["type"]) if row.get("type") else None
        out.append(
            {
                "type": FEATURE_CLASS_TO_KEY.get(cls, cls.replace("_Annotation", "").lower())
                if cls else None,
                "begin": row.get("begin"),
                "end": row.get("end"),
                "description": row.get("comment"),
            }
        )
    return out
```

- [ ] **Step 5: Add the zero-match hint** in `get_features` (`sparql_service.py`):

```python
    async def get_features(
        self, accession: str, feature_types: list[str] | None = None
    ) -> dict[str, Any]:
        """Return sequence features with coordinates."""
        query = Q.protein_features(accession, feature_types)
        features = S.shape_features(await self._select(query))
        acc = Q.validate_accession(accession).split("-")[0]
        payload: dict[str, Any] = {"accession": acc, "count": len(features), "features": features}
        if feature_types and not features:
            from uniprot_link.services.constants import FEATURE_TYPES
            payload["filter_hint"] = {
                "message": "No features matched the requested types for this entry.",
                "accepted_feature_types": sorted(FEATURE_TYPES.keys()),
            }
        return payload
```

- [ ] **Step 6: Run unit test, expect PASS.**

- [ ] **Step 7: Add integration assertion**:

```python
@pytest.mark.integration
async def test_features_domain_filter_matches_extent(live_service):
    res = await live_service.get_features("P38398", ["domain"])
    assert res["count"] >= 2
    assert all(f["type"] == "domain" for f in res["features"])
```

- [ ] **Step 8: Checkpoint** — `make ci-local` + `python research/verify_queries.py`.

---

### Task 4: `get_protein_variants` — populate structured diseases

**Files:**
- Modify: `uniprot_link/services/queries.py` (`protein_variants`, ~265–284)
- Modify: `uniprot_link/services/shaping.py` (`shape_variants`, ~147–167)
- Test: `tests/unit/test_shaping.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_shaping.py`:

```python
def test_shape_variants_merges_diseases_via_skos_related():
    from uniprot_link.services.shaping import shape_variants
    from tests.conftest import make_select_json
    body = make_select_json(["begin", "end", "substitution", "comment", "disease", "dbsnp"], [
        {"begin": 10, "end": 10, "substitution": "K", "comment": "In BC and BROVCA1.",
         "disease": "Breast-ovarian cancer, familial, 1",
         "dbsnp": "http://purl.uniprot.org/dbsnp/rs80357017"},
        {"begin": 10, "end": 10, "substitution": "K", "comment": "In BC and BROVCA1.",
         "disease": "Breast cancer", "dbsnp": "http://purl.uniprot.org/dbsnp/rs80357017"},
    ])
    out = shape_variants(body)
    assert len(out) == 1
    assert sorted(out[0]["diseases"]) == ["Breast cancer", "Breast-ovarian cancer, familial, 1"]
    assert out[0]["dbsnp"] == "rs80357017"
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Fix the `protein_variants` query** — replace the disease OPTIONAL and add dbSNP:

```python
    acc = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
SELECT ?begin ?end ?substitution ?comment ?disease ?dbsnp
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Natural_Variant_Annotation ; up:range ?r .
  ?r faldo:begin ?b . ?b faldo:position ?begin .
  ?r faldo:end ?e . ?e faldo:position ?end .
  OPTIONAL {{ ?a up:substitution ?substitution }}
  OPTIONAL {{ ?a rdfs:comment ?comment }}
  OPTIONAL {{ ?a skos:related ?d . ?d skos:prefLabel ?disease }}
  OPTIONAL {{ ?a rdfs:seeAlso ?dbsnp .
             FILTER(STRSTARTS(STR(?dbsnp), "http://purl.uniprot.org/dbsnp/")) }}
}}
LIMIT {limit}"""
```

- [ ] **Step 4: Update `shape_variants`** to read `disease` + `dbsnp` and sort disease-first:

```python
def shape_variants(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape natural-variant rows, merging rows that differ only by disease."""
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for row in rows(result_json):
        key = (row.get("begin"), row.get("end"), row.get("substitution"))
        entry = merged.setdefault(
            key,
            {
                "begin": row.get("begin"),
                "end": row.get("end"),
                "substitution": row.get("substitution"),
                "description": row.get("comment"),
                "diseases": [],
            },
        )
        disease = row.get("disease")
        if disease and disease not in entry["diseases"]:
            entry["diseases"].append(disease)
        dbsnp = row.get("dbsnp")
        if dbsnp and "dbsnp" not in entry:
            entry["dbsnp"] = local_name(dbsnp)
    out = list(merged.values())
    out.sort(key=lambda v: (
        not v["diseases"],                       # disease-associated first
        v["begin"] is None,
        v["begin"] if isinstance(v["begin"], int) else 0,
    ))
    return out
```

- [ ] **Step 5: Run unit test, expect PASS.**

- [ ] **Step 6: Add integration assertion**:

```python
@pytest.mark.integration
async def test_variants_have_populated_diseases(live_service):
    res = await live_service.get_variants("P38398", 200)
    assert any(v.get("diseases") for v in res["variants"])
```

- [ ] **Step 7: Checkpoint** — `make ci-local` + `python research/verify_queries.py`.

---

### Task 5: `get_protein` — existence anchor → `not_found`

**Files:**
- Modify: `uniprot_link/services/queries.py` (`protein_summary`, ~197–219)
- Test: `tests/unit/test_service_and_tools.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_service_and_tools.py`:

```python
async def test_get_protein_bogus_accession_raises_not_found(service_factory):
    from uniprot_link.exceptions import NotFoundError
    # Empty result set for the summary query -> not found.
    service = service_factory([("a up:Protein",
                               {"head": {"vars": []}, "results": {"bindings": []}})])
    with pytest.raises(NotFoundError):
        await service.get_protein("ZZZZZZ")
```

- [ ] **Step 2: Run it, expect FAIL** (currently returns `{"accession": "ZZZZZZ"}`).

- [ ] **Step 3: Add the required anchor** as the first pattern inside the `WHERE` of `protein_summary`:

```python
WHERE {{
  uniprotkb:{base} a up:Protein .
  OPTIONAL {{ uniprotkb:{base} up:mnemonic ?mnemonic }}
  ...
```

(Insert the `a up:Protein .` line immediately after `WHERE {{`; leave the rest of the OPTIONAL block unchanged.)

- [ ] **Step 4: Run unit test, expect PASS.**

- [ ] **Step 5: Add integration assertion**:

```python
@pytest.mark.integration
async def test_get_protein_bogus_is_not_found_live(live_service):
    from uniprot_link.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        await live_service.get_protein("ZZZZZZ")
```

- [ ] **Step 6: Checkpoint** — `make ci-local` + `python research/verify_queries.py`.

---

# WAVE 2 — P1 robustness & contract

### Task 6: Unify not-found across all `get_protein*` tools

**Files:**
- Modify: `uniprot_link/services/queries.py` (add `entry_exists_ask`)
- Modify: `uniprot_link/services/sparql_service.py` (add `require_entry`; guard annotation methods)
- Test: `tests/unit/test_service_and_tools.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Add the ASK builder** in `queries.py`:

```python
def entry_exists_ask(accession: str) -> str:
    """Build an ASK that is true iff the UniProtKB entry exists."""
    base = validate_accession(accession).split("-")[0]
    return f"""{prefix_block()}
ASK {{ uniprotkb:{base} a up:Protein }}"""
```

- [ ] **Step 2: Write failing unit test** in `tests/unit/test_service_and_tools.py`:

```python
async def test_annotation_tools_not_found_when_entry_absent(service_factory):
    from uniprot_link.exceptions import NotFoundError
    routes = [("ASK", {"head": {}, "boolean": False})]
    service = service_factory(routes)
    for call in (service.get_features, service.get_variants, service.get_diseases,
                 service.get_go_terms, service.get_cross_references):
        with pytest.raises(NotFoundError):
            await call("ZZZZZZ")
```

- [ ] **Step 3: Run it, expect FAIL.**

- [ ] **Step 4: Add `require_entry` + guard each annotation method.** In `sparql_service.py`:

```python
    async def require_entry(self, accession: str) -> None:
        """Raise NotFoundError if the UniProtKB entry does not exist (cached)."""
        ask_json = await self._select(Q.entry_exists_ask(accession))
        if not (ask_json or {}).get("boolean", False):
            raise NotFoundError(
                f"No UniProtKB entry found for accession '{accession}'. "
                "Resolve a gene/organism via find_proteins first."
            )
```

Then, in each of `get_features`, `get_variants`, `get_diseases`, `get_go_terms`,
`get_cross_references`, fetch existence concurrently with the data query, e.g. for `get_variants`:

```python
    async def get_variants(self, accession: str, limit: int = 200,
                           disease_associated_only: bool = False) -> dict[str, Any]:
        limit = Q.clamp_limit(limit, default=200, maximum=2000)
        query = Q.protein_variants(accession, limit=limit,
                                   disease_associated_only=disease_associated_only)
        _, data_json = await asyncio.gather(self.require_entry(accession), self._select(query))
        variants = S.shape_variants(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        payload = {"accession": acc, "count": len(variants), "variants": variants}
        if len(variants) >= limit:
            payload["truncated"] = {
                "reason": f"limit {limit} reached",
                "recovery": "raise `limit` or set disease_associated_only=true.",
            }
        return payload
```

Apply the same `asyncio.gather(self.require_entry(accession), self._select(query))`
pattern to `get_features`, `get_diseases`, `get_go_terms`, `get_cross_references`.
(`map_identifiers` calls `get_cross_references`, so it inherits the guard.)

- [ ] **Step 5: Run unit test, expect PASS.**

- [ ] **Step 6: Add integration assertion**:

```python
@pytest.mark.integration
async def test_features_bogus_is_not_found_live(live_service):
    from uniprot_link.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        await live_service.get_features("ZZZZZZ")
```

- [ ] **Step 7: Checkpoint** — `make ci-local`.

---

### Task 7: `run_sparql_query` — reject writes as `invalid_input`

**Files:**
- Modify: `uniprot_link/services/queries.py` (add `classify_sparql_operation`)
- Modify: `uniprot_link/services/sparql_service.py` (`run_query`, ~71–94)
- Test: `tests/unit/test_queries.py`, `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_queries.py`:

```python
import pytest
from uniprot_link.exceptions import InvalidInputError

def test_classify_rejects_update_allows_select():
    from uniprot_link.services.queries import classify_sparql_operation
    assert classify_sparql_operation("PREFIX up: <x> SELECT * WHERE {?s ?p ?o}") == "SELECT"
    assert classify_sparql_operation("# c\nASK { ?s ?p ?o }") == "ASK"
    # a literal 'insert' must not trip detection
    assert classify_sparql_operation('SELECT ?x WHERE { ?x rdfs:label "insert" }') == "SELECT"
    for bad in ("INSERT DATA { <a> <b> <c> }", "DELETE WHERE {?s ?p ?o}",
                "WITH <g> DELETE {?s ?p ?o} WHERE {?s ?p ?o}", "LOAD <http://x>",
                "CLEAR GRAPH <g>", "DROP GRAPH <g>"):
        with pytest.raises(InvalidInputError):
            classify_sparql_operation(bad)
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Implement `classify_sparql_operation`** in `queries.py`:

```python
_COMMENT_RE = re.compile(r"#[^\n]*")
_PREFIX_RE = re.compile(r"^\s*(?:PREFIX\s+[^:]*:\s*<[^>]*>|BASE\s*<[^>]*>)\s*", re.IGNORECASE)
_READ_OPS = {"SELECT", "ASK", "CONSTRUCT", "DESCRIBE"}
_WRITE_OPS = {"INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
              "ADD", "MOVE", "COPY", "WITH"}


def classify_sparql_operation(query: str) -> str:
    """Return the leading query form; raise InvalidInputError on UPDATE/write forms."""
    stripped = _COMMENT_RE.sub("", query)
    while True:
        new = _PREFIX_RE.sub("", stripped, count=1)
        if new == stripped:
            break
        stripped = new
    token = (stripped.strip().split(None, 1) or [""])[0].upper()
    if token in _READ_OPS:
        return token
    if token in _WRITE_OPS:
        raise InvalidInputError(
            "read-only: only SELECT/ASK/CONSTRUCT/DESCRIBE queries are allowed.",
            field="query",
        )
    return token  # unknown -> let the endpoint return a 400 (query_syntax_error)
```

- [ ] **Step 4: Call it first in `run_query`** (`sparql_service.py`), right after the
`result_format` check:

```python
        Q.classify_sparql_operation(query)  # raises InvalidInputError on writes
```

- [ ] **Step 5: Add a service-level test** in `tests/unit/test_service_and_tools.py`:

```python
async def test_run_query_rejects_insert(service_factory):
    from uniprot_link.exceptions import InvalidInputError
    service = service_factory([])
    with pytest.raises(InvalidInputError):
        await service.run_query("INSERT DATA { <a> <b> <c> }")
```

- [ ] **Step 6: Run both tests, expect PASS.**

- [ ] **Step 7: Checkpoint** — `make ci-local`.

---

### Task 8: `get_protein_variants` — `disease_associated_only` + tool param

**Files:**
- Modify: `uniprot_link/services/queries.py` (`protein_variants` signature)
- Modify: `uniprot_link/mcp/tools/proteins.py` (`get_protein_variants` tool, ~182–191)
- Test: `tests/unit/test_queries.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_queries.py`:

```python
def test_protein_variants_disease_only_requires_skos_related():
    from uniprot_link.services.queries import protein_variants
    q = protein_variants("P38398", limit=50, disease_associated_only=True)
    assert "OPTIONAL { ?a skos:related" not in q
    assert "?a skos:related ?d . ?d skos:prefLabel ?disease" in q
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Add the parameter** to `protein_variants`:

```python
def protein_variants(accession: str, limit: int = 200,
                     disease_associated_only: bool = False) -> str:
    acc = validate_accession(accession).split("-")[0]
    if disease_associated_only:
        disease_block = "  ?a skos:related ?d . ?d skos:prefLabel ?disease ."
    else:
        disease_block = "  OPTIONAL { ?a skos:related ?d . ?d skos:prefLabel ?disease }"
    return f"""{prefix_block()}
SELECT ?begin ?end ?substitution ?comment ?disease ?dbsnp
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Natural_Variant_Annotation ; up:range ?r .
  ?r faldo:begin ?b . ?b faldo:position ?begin .
  ?r faldo:end ?e . ?e faldo:position ?end .
  OPTIONAL {{ ?a up:substitution ?substitution }}
  OPTIONAL {{ ?a rdfs:comment ?comment }}
{disease_block}
  OPTIONAL {{ ?a rdfs:seeAlso ?dbsnp .
             FILTER(STRSTARTS(STR(?dbsnp), "http://purl.uniprot.org/dbsnp/")) }}
}}
LIMIT {limit}"""
```

- [ ] **Step 4: Add the tool param** in `proteins.py` `get_protein_variants`:

```python
    async def get_protein_variants(
        accession: _ACC,
        limit: Annotated[int, Field(description="Max variants to return.", ge=1, le=2000)] = 200,
        disease_associated_only: Annotated[
            bool, Field(description="Return only variants linked to a disease.")
        ] = False,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            return await get_sparql_service().get_variants(
                accession, limit, disease_associated_only)
        ...
```

(Keep the existing `run_mcp_tool` wrapper; just thread the new arg.)

- [ ] **Step 5: Run unit test, expect PASS.**

- [ ] **Step 6: Integration assertion**:

```python
@pytest.mark.integration
async def test_variants_disease_only(live_service):
    res = await live_service.get_variants("P38398", 200, disease_associated_only=True)
    assert res["variants"] and all(v["diseases"] for v in res["variants"])
```

- [ ] **Step 7: Checkpoint** — `make ci-local` + `python research/verify_queries.py`.

---

### Task 9: `next_commands` on every tool

**Files:**
- Modify: `uniprot_link/mcp/next_commands.py` (new builders)
- Modify: `uniprot_link/mcp/tools/proteins.py` (annotation tools attach `_meta`)
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Add builders** in `next_commands.py`:

```python
def after_entry_subresource(accession: str, current: str) -> list[dict[str, Any]]:
    """Chain back to entry context from any annotation tool (never a dead end)."""
    chain = [
        cmd("get_protein_variants", accession=accession),
        cmd("get_protein_diseases", accession=accession),
        cmd("get_protein_features", accession=accession),
        cmd("get_protein", accession=accession),
    ]
    return [c for c in chain if c["arguments"].get("accession") and c["tool"] != current][:3]
```

- [ ] **Step 2: Write failing unit test** in `tests/unit/test_service_and_tools.py`:

```python
async def test_annotation_tools_attach_next_commands(registered_tools_payloads):
    # registered_tools_payloads: helper that invokes each annotation tool against a
    # canned service and returns its payload dict. (Mirror existing tool tests.)
    for name in ("get_protein_features", "get_protein_variants", "get_protein_go_terms",
                 "get_protein_cross_references", "get_protein_sequence"):
        payload = await registered_tools_payloads(name, "P38398")
        assert payload["_meta"]["next_commands"]
        assert all("tool" in c and "arguments" in c for c in payload["_meta"]["next_commands"])
```

(If no such helper exists, assert directly in the tool-layer test style already in
`test_service_and_tools.py`.)

- [ ] **Step 3: Attach `_meta.next_commands`** in each annotation tool body in `proteins.py`.
For example `get_protein_features`:

```python
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_features(accession, feature_types)
            payload["_meta"] = {"next_commands":
                                after_entry_subresource(payload["accession"], "get_protein_features")}
            return payload
```

Repeat for `get_protein_sequence`, `_variants`, `_diseases`, `_cross_references`,
`_go_terms`, `map_identifiers` (import `after_entry_subresource`).

- [ ] **Step 4: Run unit test, expect PASS.**

- [ ] **Step 5: Checkpoint** — `make ci-local`.

---

### Task 9b (conditional): split `queries.py` if over budget

- [ ] **Step 1:** Run `make lint-loc`. If `queries.py` ≤ 560 lines, **skip this task.**
- [ ] **Step 2:** If over: create `uniprot_link/services/queries_catalog.py` and move
  `taxon_core`, `taxon_ancestors`, `resolve_taxon_by_name`, `search_example_queries`,
  `get_example_query`, and `classify_sparql_operation` into it (keep the validation
  helpers and shared `prefix_block` import). Re-export from `queries.py` if needed
  (`from uniprot_link.services.queries_catalog import *`) or update import sites in
  `sparql_service.py`.
- [ ] **Step 3:** `make ci-local` — expect green, `lint-loc` under cap.

---

# WAVE 3 — P2 efficiency & polish

### Task 10: `response_mode` enum + projection helper

**Files:**
- Modify: `uniprot_link/services/shaping.py` (add `apply_response_mode`)
- Modify: `uniprot_link/mcp/tools/proteins.py` (add `response_mode` param to data tools)
- Modify: `uniprot_link/services/sparql_service.py` (thread `response_mode`)
- Test: `tests/unit/test_shaping.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_shaping.py`:

```python
def test_apply_response_mode_projects_protein_payload():
    from uniprot_link.services.shaping import apply_response_mode
    full = {"accession": "P38398", "mnemonic": "BRCA1_HUMAN", "function": "long text...",
            "created": "1994-10-01", "modified": "2024-01-01"}
    minimal = apply_response_mode(full, "minimal", kind="protein")
    assert "function" not in minimal and minimal["accession"] == "P38398"
    assert apply_response_mode(full, "full", kind="protein") == full
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Implement `apply_response_mode`** in `shaping.py`:

```python
# Fields dropped per (kind, mode). 'standard'/'full' keep everything by default.
_MODE_DROP: dict[tuple[str, str], set[str]] = {
    ("protein", "minimal"): {"function", "created", "modified", "short_name", "common_name"},
    ("protein", "compact"): {"created", "modified"},
}


def apply_response_mode(payload: dict[str, Any], mode: str, *, kind: str) -> dict[str, Any]:
    """Project a payload for a response_mode. 'full' is identity."""
    if mode in ("standard", "full"):
        return payload
    drop = _MODE_DROP.get((kind, mode), set())
    return {k: v for k, v in payload.items() if k not in drop}
```

- [ ] **Step 4: Add the param** to data tools in `proteins.py` (use a shared annotation):

```python
from typing import Literal
ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Verbosity: minimal|compact|standard|full (default compact)."),
]
```

Add `response_mode: ResponseMode = "compact"` to `get_protein` (and the other data
tools as you extend coverage), and apply in the service method, e.g. `get_protein`:

```python
    async def get_protein(self, accession: str, response_mode: str = "compact") -> dict[str, Any]:
        ...
        payload = {"accession": acc, **summary}
        return S.apply_response_mode(payload, response_mode, kind="protein")
```

- [ ] **Step 5: Run unit test, expect PASS.**

- [ ] **Step 6: Checkpoint** — `make ci-local`.

---

### Task 11: De-duplicate the canonical sequence

**Files:**
- Modify: `uniprot_link/services/sparql_service.py` (`get_sequence`, ~157–170)
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Write failing unit test** asserting `isoforms` excludes the canonical:

```python
async def test_get_sequence_does_not_duplicate_canonical(service_factory):
    from tests.conftest import make_select_json
    body = make_select_json(["isoform", "length", "mass", "value"], [
        {"isoform": "http://purl.uniprot.org/isoforms/P05067-1", "length": 770,
         "mass": 86943, "value": "MLP..."},
        {"isoform": "http://purl.uniprot.org/isoforms/P05067-2", "length": 365,
         "mass": 40000, "value": "MAB..."},
    ])
    service = service_factory([("up:sequence", body)])
    res = await service.get_sequence("P05067")
    assert res["canonical"]["isoform"] == "P05067-1"
    assert all(s["isoform"] != "P05067-1" for s in res["isoforms"])
    assert res["isoform_count"] == 2
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Update `get_sequence`** so `isoforms` holds non-canonical only:

```python
        canonical = next((s for s in sequences if s["canonical"]), sequences[0])
        others = [s for s in sequences if s is not canonical]
        return {
            "accession": acc,
            "canonical": canonical,
            "isoform_count": len(sequences),
            "isoforms": others,
        }
```

- [ ] **Step 4: Run unit test, expect PASS.**
- [ ] **Step 5: Checkpoint** — `make ci-local`.

---

### Task 12: Short ids for xrefs / mapping (mode-aware)

**Files:**
- Modify: `uniprot_link/services/shaping.py` (`shape_cross_references` gains a `short` flag)
- Modify: `uniprot_link/services/sparql_service.py` (`get_cross_references`, `map_identifiers`)
- Test: `tests/unit/test_shaping.py`

- [ ] **Step 1: Write failing unit test**:

```python
def test_shape_cross_references_short_ids():
    from uniprot_link.services.shaping import shape_cross_references
    from tests.conftest import make_select_json
    body = make_select_json(["db", "database", "xref"], [
        {"db": "http://purl.uniprot.org/database/PDB", "database": "PDB",
         "xref": "http://rdf.wwpdb.org/pdb/1AAP"},
    ])
    assert shape_cross_references(body, short=True)["PDB"] == ["1AAP"]
    assert shape_cross_references(body, short=False)["PDB"] == ["http://rdf.wwpdb.org/pdb/1AAP"]
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Add the `short` parameter** to `shape_cross_references`:

```python
def shape_cross_references(result_json: dict[str, Any] | None,
                           *, short: bool = True) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for row in rows(result_json):
        db = row.get("database") or local_name(row.get("db", ""))
        xref = row.get("xref", "")
        grouped.setdefault(db, []).append(local_name(xref) if short else xref)
    return grouped
```

- [ ] **Step 4: Thread mode** in `get_cross_references` (`short = response_mode != "full"`).
- [ ] **Step 5: Run unit test, expect PASS.**
- [ ] **Step 6: Checkpoint** — `make ci-local`.

---

### Task 13: Compact, non-redundant provenance

**Files:**
- Modify: `uniprot_link/mcp/envelope.py` (`_BASE_META`, ~31–36)
- Modify: `uniprot_link/mcp/capabilities.py` (ensure full citation present there)
- Test: `tests/unit/test_capabilities.py`, `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_service_and_tools.py`:

```python
def test_provenance_is_compact():
    from uniprot_link.mcp.envelope import _provenance_meta
    meta = _provenance_meta()
    assert meta["citation"] == "doi:10.1093/nar/gkae1010"
    assert "recommended_citation" not in meta  # full text only in capabilities/full mode
    assert meta["unsafe_for_clinical_use"] is True and meta["uniprot_release"]
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Update `_BASE_META`** in `envelope.py`:

```python
_BASE_META: dict[str, Any] = {
    "unsafe_for_clinical_use": True,
    "uniprot_release": UNIPROT_RELEASE,
    "endpoint": "https://sparql.uniprot.org/sparql",
    "citation": "doi:10.1093/nar/gkae1010",
}
```

- [ ] **Step 4: Confirm capabilities still carries the full citation** (it already does via
`RECOMMENDED_CITATION`); add an assertion in `tests/unit/test_capabilities.py`:

```python
def test_capabilities_has_full_citation():
    from uniprot_link.mcp.capabilities import build_capabilities
    assert "Nucleic Acids Res" in build_capabilities()["recommended_citation"]
```

- [ ] **Step 5: Run both tests, expect PASS.** Fix any existing tests that asserted the long
citation in `_meta`.
- [ ] **Step 6: Checkpoint** — `make ci-local`.

---

### Task 14: Propagate `elapsed_ms` + `cached` to typed tools

**Files:**
- Modify: `uniprot_link/services/sparql_service.py` (`_select` returns timing; typed methods add `_meta`)
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Write failing unit test** asserting `_meta.elapsed_ms` on a typed payload:

```python
async def test_typed_tool_reports_elapsed_ms(service_factory):
    from tests.conftest import make_select_json
    body = make_select_json(["scientificName"], [{"scientificName": "Homo sapiens"}])
    service = service_factory([("up:scientificName", body),
                               ("subClassOf", {"head": {"vars": []}, "results": {"bindings": []}})])
    res = await service.get_taxon("9606")
    assert "elapsed_ms" in res["_meta"]
```

(Adjust routes to your `_select` change; the key assertion is `_meta.elapsed_ms`.)

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Change `_select`** to return `(json, elapsed_ms, cached)` and have typed
methods stamp `_meta`. Minimal approach — keep `_select` returning json, add a sibling
`_select_timed` returning the tuple, and use it where you want timing; OR add an instance
attribute `self._last_elapsed_ms`. Simplest that satisfies the contract:

```python
    async def _select(self, query: str, *, timeout: float | None = None) -> dict[str, Any] | None:
        cache_key = f"json::{query}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._last_meta = {"elapsed_ms": 0.0, "cached": True}
            return cached
        result = await self.client.execute(query, result_format="json", timeout=timeout)
        self._last_meta = {"elapsed_ms": round(result.elapsed_ms, 1), "cached": False}
        self._cache.put(cache_key, result.json)
        return result.json
```

Then in typed methods, merge `self._last_meta` into the returned `_meta` (preserving
`next_commands`). Initialise `self._last_meta: dict[str, Any] = {}` in `__init__`.

- [ ] **Step 4: Run unit test, expect PASS.** (Re-check Task 1's `gather` still unpacks json,
not the tuple — `_select` signature is unchanged here.)
- [ ] **Step 5: Checkpoint** — `make ci-local`.

---

### Task 15: Fuzzy example search + surface MIM in diseases

**Files:**
- Modify: `uniprot_link/services/queries.py` (`search_example_queries`, `protein_diseases`)
- Modify: `uniprot_link/services/shaping.py` (`shape_diseases` MIM already wired — verify)
- Test: `tests/unit/test_queries.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_queries.py`:

```python
def test_search_examples_multiword_builds_or_filter():
    from uniprot_link.services.queries import search_example_queries
    q = search_example_queries("protein domain architecture")
    # one CONTAINS per token, OR-combined
    assert q.count('CONTAINS(LCASE(?comment)') >= 3 or q.count("||") >= 2
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Tokenize the text filter** in `search_example_queries`:

```python
    text_filter = ""
    if text:
        tokens = [escape_literal(t) for t in text.strip().split() if t][:6]
        if tokens:
            clauses = " || ".join(
                f'CONTAINS(LCASE(?comment), LCASE("{t}")) || '
                f'EXISTS {{ ?ex schema:keywords ?k2 . FILTER(CONTAINS(LCASE(?k2), LCASE("{t}"))) }}'
                for t in tokens
            )
            text_filter = f"    FILTER({clauses})\n"
```

- [ ] **Step 4: Add MIM to `protein_diseases`** query:

```python
SELECT ?disease ?diseaseLabel ?comment ?mim
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Disease_Annotation .
  OPTIONAL {{ ?a rdfs:comment ?comment }}
  OPTIONAL {{ ?a up:disease ?disease . ?disease skos:prefLabel ?diseaseLabel .
             OPTIONAL {{ ?disease rdfs:seeAlso ?mim .
                        FILTER(STRSTARTS(STR(?mim), "http://purl.uniprot.org/mim/")) }} }}
}}
ORDER BY ?diseaseLabel"""
```

(`shape_diseases` already reads `row.get("mim")` and applies `local_name` — no shaping
change needed; verify with a unit test.)

- [ ] **Step 5: Run unit test, expect PASS.**

- [ ] **Step 6: Integration assertions**:

```python
@pytest.mark.integration
async def test_multiword_example_search_returns_hits(live_service):
    res = await live_service.search_examples("protein domain architecture", 25)
    assert res["count"] > 0

@pytest.mark.integration
async def test_disease_carries_mim(live_service):
    res = await live_service.get_diseases("P38398")
    assert any(d.get("mim") for d in res["diseases"])
```

- [ ] **Step 7: Checkpoint** — `make ci-local` + `python research/verify_queries.py`.

---

### Task 16: Capabilities, instructions & changelog

**Files:**
- Modify: `uniprot_link/mcp/capabilities.py` (`build_capabilities`)
- Modify: `uniprot_link/__init__.py` (`__version__` → `0.2.0`)
- Modify: server `instructions` string (locate via `grep -rn "next_commands, a ready-to-call" uniprot_link`)
- Modify: `CHANGELOG.md`
- Test: `tests/unit/test_capabilities.py`

- [ ] **Step 1: Write failing unit test** in `tests/unit/test_capabilities.py`:

```python
def test_capabilities_advertises_response_modes_and_contracts():
    from uniprot_link.mcp.capabilities import build_capabilities
    cap = build_capabilities()
    assert cap["server_version"] == "0.2.0"
    assert cap["response_modes"] == ["minimal", "compact", "standard", "full"]
    assert cap["default_response_mode"] == "compact"
    assert "domain" in cap["feature_types"]
    assert cap["read_only"] is True
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Update `build_capabilities`** — add:

```python
        "response_modes": ["minimal", "compact", "standard", "full"],
        "default_response_mode": "compact",
        "read_only": True,
        "not_found_contract": (
            "Nonexistent accessions/taxa return error_code 'not_found' on every "
            "get_protein*/get_taxon tool; run_sparql_query rejects writes as 'invalid_input'."
        ),
```

Bump `__version__` to `0.2.0`.

- [ ] **Step 4: Update the server `instructions`** so the `next_commands` line is accurate
(now universal) and add a `response_mode` + read-only sentence. Update
`get_protein_variants` / `get_protein_features` / `get_taxon` tool descriptions to match the
new contracts (diseases populated; domain = positional extents; direct parent + ordered
lineage).

- [ ] **Step 5: Add a `CHANGELOG.md` v0.2.0 entry** enumerating Tasks 1–15.

- [ ] **Step 6: Run unit test, expect PASS.**

- [ ] **Step 7: Final checkpoint** — `make ci-local` (green) and a full
`make test-integration` run against the live endpoint to confirm every P0/P1 integration
assertion passes.

---

## Self-review — spec coverage

- Spec §4.1 → Task 1; §4.2 → Task 1 (lineage); §4.3 → Task 3; §4.4 → Task 4; §4.5 → Task 5.
- §4.6 → Task 6; §4.7 → Task 7; §4.8 → Tasks 4+8; §4.9 → Task 9.
- §4.10 → Task 10; §4.11 → Task 11; §4.12 → Task 12; §4.13 → Task 13; §4.14 → Task 14; §4.15 → Task 15.
- §6 (file-size) → Task 9b; §7 (docs/capabilities) → Task 16.
- §8 (testing) → unit + integration steps in every task; `verify_queries.py` re-run at each `queries.py` checkpoint.

All spec requirements map to a task. No placeholders; method/field names
(`shape_ancestors`, `taxon_core`/`taxon_ancestors`, `require_entry`,
`classify_sparql_operation`, `apply_response_mode`, `FEATURE_CLASS_TO_KEY`,
`GO_ASPECT_ROOTS`, `disease_associated_only`) are consistent across tasks.
