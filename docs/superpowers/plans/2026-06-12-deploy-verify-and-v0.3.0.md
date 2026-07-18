# Deploy/Verify v0.2.0 + v0.3.0 Uplift Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Realize the already-implemented `v0.2.0` correctness milestone on the
running server (the deployed process is stale `v0.1.0`), prove it live, then ship a
small validated `v0.3.0` delta — variant wild-type/notation, a genuinely-focused
`map_identifiers`, an actionable SPARQL syntax-error, and a deployment-freshness
guard so this drift cannot recur silently.

**Architecture:** Two waves. **Wave 0** = deploy + live verification + a
freshness guard (the dominant lever; mostly ops + a self-check). **Wave 1** = the
`v0.3.0` code delta — four small, independently-testable changes, each a
query/shaping/wiring change with a mocked unit test plus a live integration
assertion. Every SPARQL change in this plan was executed against
`https://sparql.uniprot.org/sparql` (release 2026_01, QLever) during spec research.

**Tech Stack:** Python 3.12, `uv`, FastMCP, FastAPI, httpx, SPARQL 1.1 (QLever),
pytest + `respx`, Ruff, mypy strict. Reference spec:
`docs/superpowers/specs/2026-06-12-assessment-review-and-v0.3.0-spec.md`.

---

## Conventions for every task

- **Repo is not git-initialized.** Each task ends with a **Checkpoint**
  (`make ci-local`) instead of a commit. To get atomic history, `git init` first
  and commit at each checkpoint.
- **Unit tests:** `make test` (or `uv run pytest tests/unit/<file> -v`). Mocking
  uses `service_factory` + `make_select_json` from `tests/conftest.py` (routes by
  query substring, first match wins).
- **Integration tests:** `make test-integration` (live; not in default CI). Use the
  existing `live_service` fixture pattern in `tests/integration/test_live.py`.
- **After any `queries.py` change:** re-run `python research/verify_queries.py` per
  `CLAUDE.md` (QLever timing re-validation).
- **Before handoff:** `make ci-local` green; `make lint-loc` under the 600-line cap.

---

## File structure (what changes and why)

| File | Responsibility / change |
|---|---|
| `uniprot_link/buildinfo.py` | **New.** `build_info()` — version + git sha + build time from env, so the running server reports its provenance. |
| `uniprot_link/mcp/capabilities.py` | Add `"build": build_info()` to the capabilities payload. |
| `uniprot_link/app.py` | `/health` reports `git_sha`/`built_at` (version already present). |
| `scripts/check_deployed_version.py` | **New.** Release gate: GET `/health`, fail if deployed version ≠ `__version__`. |
| `uniprot_link/services/queries.py` | `protein_variants`: add canonical-sequence `OPTIONAL` + `?wildType` `BIND`. |
| `uniprot_link/services/shaping.py` | `shape_variants`: derive `wild_type` / `variant_type` / `notation`. |
| `uniprot_link/services/sparql_service.py` | `map_identifiers`: default to the curated mapping DB set; add `requested_databases`. |
| `uniprot_link/mcp/tools/query.py` | `run_sparql_query` error context gains a `search_example_queries` fallback. |
| `uniprot_link/mcp/tools/proteins.py` | Tool-description tweaks (variants notation; map vs xref division). |
| `uniprot_link/__init__.py` | Version bump `0.2.0` → `0.3.0`. |
| `CHANGELOG.md` | `v0.3.0` entry. |
| `tests/integration/test_live.py` | Live assertions for v0.2.0 fixes (verification) + v0.3.0 delta. |

---

# WAVE 0 — Deploy & verify v0.2.0 (the dominant lever)

> The on-disk code is `v0.2.0` with 81 passing unit tests; the running server is
> `v0.1.0`. Deploying it resolves 9 of the assessment's 12 findings. This wave
> proves the fixes live and makes staleness self-evident.

### Task 0.1: Prove the v0.2.0 fixes against the live endpoint

**Files:**
- Modify: `tests/integration/test_live.py` (ensure the verification assertions exist)

- [ ] **Step 1: Add/confirm the live verification assertions.** Append any of these
  that are missing to `tests/integration/test_live.py` (mirror the existing
  `live_service` fixture). These encode the assessment's exact reproductions,
  inverted to assert the fix:

```python
import pytest
from uniprot_link.exceptions import InvalidInputError, NotFoundError


@pytest.mark.integration
async def test_v020_get_protein_bogus_is_not_found(live_service):
    with pytest.raises(NotFoundError):
        await live_service.get_protein("ZZZ999")


@pytest.mark.integration
async def test_v020_go_aspects_are_real(live_service):
    res = await live_service.get_go_terms("P05067")
    assert {"biological_process", "molecular_function", "cellular_component"} <= set(res["by_aspect"])
    assert "unknown" not in res["by_aspect"]


@pytest.mark.integration
async def test_v020_taxon_direct_parent_is_homo(live_service):
    res = await live_service.get_taxon("9606", include_lineage=True)
    assert res["parent_taxon_id"] == "9605"
    assert res["lineage"][0]["scientific_name"] == "Homo"


@pytest.mark.integration
async def test_v020_domain_filter_matches_extent(live_service):
    res = await live_service.get_features("Q96T60", ["domain"])
    assert res["count"] >= 1
    assert all(f["type"] == "domain" for f in res["features"])


@pytest.mark.integration
async def test_v020_variants_have_diseases(live_service):
    res = await live_service.get_variants("Q96T60", 200)
    assert any(v.get("diseases") for v in res["variants"])


@pytest.mark.integration
async def test_v020_writes_rejected(live_service):
    with pytest.raises(InvalidInputError):
        await live_service.run_query("INSERT DATA { <a> <b> <c> }")
```

- [ ] **Step 2: Run the live suite.**

Run: `make test-integration`
Expected: PASS (these are the v0.2.0 fixes proven against the live endpoint).

- [ ] **Step 3: Checkpoint** — `make ci-local`. Expected: green.

---

### Task 0.2: Add `build_info()` provenance

**Files:**
- Create: `uniprot_link/buildinfo.py`
- Test: `tests/unit/test_buildinfo.py`

- [ ] **Step 1: Write the failing test** in `tests/unit/test_buildinfo.py`:

```python
def test_build_info_reports_version_and_env(monkeypatch):
    from uniprot_link import __version__
    from uniprot_link.buildinfo import build_info

    monkeypatch.setenv("UNIPROT_LINK_GIT_SHA", "abc1234")
    monkeypatch.setenv("UNIPROT_LINK_BUILT_AT", "2026-06-12T00:00:00Z")
    info = build_info()
    assert info["version"] == __version__
    assert info["git_sha"] == "abc1234"
    assert info["built_at"] == "2026-06-12T00:00:00Z"

    monkeypatch.delenv("UNIPROT_LINK_GIT_SHA", raising=False)
    assert build_info()["git_sha"] == "unknown"
```

- [ ] **Step 2: Run it, expect FAIL** (`ModuleNotFoundError`).

Run: `uv run pytest tests/unit/test_buildinfo.py -v`

- [ ] **Step 3: Create `uniprot_link/buildinfo.py`:**

```python
"""Build/version stamp so a running server can report its own provenance."""

from __future__ import annotations

import os

from uniprot_link import __version__


def build_info() -> dict[str, str | None]:
    """Return version + git sha + build time (env-injected at image build)."""
    return {
        "version": __version__,
        "git_sha": os.environ.get("UNIPROT_LINK_GIT_SHA", "unknown"),
        "built_at": os.environ.get("UNIPROT_LINK_BUILT_AT"),
    }
```

- [ ] **Step 4: Run test, expect PASS.**
- [ ] **Step 5: Checkpoint** — `make ci-local`.

---

### Task 0.3: Surface `build` in capabilities and `/health`

**Files:**
- Modify: `uniprot_link/mcp/capabilities.py` (`build_capabilities`)
- Modify: `uniprot_link/app.py` (`/health`)
- Test: `tests/unit/test_capabilities.py`

- [ ] **Step 1: Write the failing test** in `tests/unit/test_capabilities.py`:

```python
def test_capabilities_carries_build_stamp():
    from uniprot_link import __version__
    from uniprot_link.mcp.capabilities import build_capabilities
    cap = build_capabilities()
    assert cap["build"]["version"] == __version__
    assert "git_sha" in cap["build"]
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Add `build` to `build_capabilities()`** in `capabilities.py`. Add the
  import near the top:

```python
from uniprot_link.buildinfo import build_info
```

  and add this key inside the returned dict (next to `server_version`):

```python
        "build": build_info(),
```

- [ ] **Step 4: Report version provenance from `/health`** in `app.py`. Add the
  import:

```python
from uniprot_link.buildinfo import build_info
```

  and change the `/health` body to:

```python
    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Liveness probe (reports build provenance for deploy checks)."""
        return {"status": "ok", "service": "uniprot-link", **build_info()}
```

- [ ] **Step 5: Run test, expect PASS.**
- [ ] **Step 6: Checkpoint** — `make ci-local`.

---

### Task 0.4: Release gate — `check_deployed_version.py`

**Files:**
- Create: `scripts/check_deployed_version.py`

- [ ] **Step 1: Create the script** (stdlib only, so it runs anywhere):

```python
#!/usr/bin/env python3
"""Fail (exit 1) if the deployed server's version lags the source __version__.

Usage:
    python scripts/check_deployed_version.py [BASE_URL]
    # BASE_URL default: http://localhost:8000 ; reads /health.

A release is not "shipped" until this passes against the running endpoint.
"""

from __future__ import annotations

import json
import sys
import urllib.request

from uniprot_link import __version__


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=10) as resp:  # noqa: S310
            health = json.load(resp)
    except Exception as exc:  # pragma: no cover - network failure path
        print(f"ERROR: could not reach {base}/health: {exc}", file=sys.stderr)
        return 2
    deployed = health.get("version")
    if deployed != __version__:
        print(
            f"STALE DEPLOYMENT: source __version__={__version__} "
            f"but {base} reports version={deployed} (git_sha={health.get('git_sha')}).",
            file=sys.stderr,
        )
        return 1
    print(f"OK: deployed version {deployed} matches source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-test it** against a locally-running server (optional, manual):

Run: `make dev &` then `uv run python scripts/check_deployed_version.py`
Expected: `OK: deployed version 0.2.0 matches source.`

- [ ] **Step 3: Document the runbook.** In `docs/development.md`, add a short
  "Deploying / release gate" section: rebuild the image with
  `UNIPROT_LINK_GIT_SHA=$(git rev-parse --short HEAD)` and
  `UNIPROT_LINK_BUILT_AT=$(date -u +%FT%TZ)` build args/env; redeploy; then run
  `python scripts/check_deployed_version.py <prod-url>` and require exit 0 before
  closing the release.

- [ ] **Step 4: Checkpoint** — `make ci-local`.

- [ ] **Step 5: DEPLOY.** Rebuild and restart the running MCP server from current
  `main` (so `get_server_capabilities().server_version` becomes `0.2.0`). Confirm
  with `python scripts/check_deployed_version.py <url>` (exit 0) and a live
  `get_server_capabilities` showing `server_version: "0.2.0"`, `read_only: true`,
  and `response_modes`. **This step resolves assessment findings C1/H1/H2/H4/M1/M3/
  M4/L1 and the disease half of H3.**

---

# WAVE 1 — v0.3.0 delta

### Task 1: Variant wild-type residue + constructible notation (D1 / H3 residual)

**Files:**
- Modify: `uniprot_link/services/queries.py` (`protein_variants`)
- Modify: `uniprot_link/services/shaping.py` (`shape_variants`)
- Test: `tests/unit/test_shaping.py`, `tests/integration/test_live.py`

- [ ] **Step 1: Write the failing unit test** in `tests/unit/test_shaping.py`:

```python
def test_shape_variants_adds_wildtype_and_notation():
    from uniprot_link.services.shaping import shape_variants
    from tests.conftest import make_select_json
    body = make_select_json(
        ["begin", "end", "substitution", "wildType", "comment", "disease", "dbsnp"],
        [
            # simple substitution -> wild_type + notation
            {"begin": 176, "end": 176, "substitution": "F", "wildType": "L",
             "comment": "In MCSZ.", "disease": "Microcephaly, seizures, and developmental delay",
             "dbsnp": "http://purl.uniprot.org/dbsnp/rs267606957"},
            # empty substitution (deletion/complex) -> variant_type 'other', no notation
            {"begin": 408, "end": 408, "substitution": "", "wildType": "T",
             "comment": "In AOA4.", "disease": "Ataxia-oculomotor apraxia 4"},
        ],
    )
    out = {(v["begin"]): v for v in shape_variants(body)}
    assert out[176]["wild_type"] == "L"
    assert out[176]["variant_type"] == "substitution"
    assert out[176]["notation"] == "L176F"
    assert out[408]["wild_type"] == "T"
    assert out[408]["variant_type"] == "other"
    assert "notation" not in out[408]
```

- [ ] **Step 2: Run it, expect FAIL.**

Run: `uv run pytest tests/unit/test_shaping.py::test_shape_variants_adds_wildtype_and_notation -v`

- [ ] **Step 3: Add `?wildType` to the `protein_variants` query** in `queries.py`.
  Change the `SELECT` line and add the canonical-sequence `OPTIONAL` + top-level
  `BIND` just before the closing `}}` (validated live: graceful when the sequence
  is absent; returns one residue per row, not the whole sequence):

```python
    return f"""{prefix_block()}
SELECT ?begin ?end ?substitution ?wildType ?comment ?disease ?dbsnp
WHERE {{
  uniprotkb:{acc} up:annotation ?a .
  ?a a up:Natural_Variant_Annotation ; up:range ?r .
  ?r faldo:begin ?b . ?b faldo:position ?begin .
  ?r faldo:end ?e . ?e faldo:position ?end .
  OPTIONAL {{ ?a up:substitution ?substitution }}
  OPTIONAL {{ ?a rdfs:comment ?comment }}
{disease_block}
  OPTIONAL {{ ?a rdfs:seeAlso ?dbsnp . ?dbsnp up:database database:dbSNP }}
  OPTIONAL {{ isoform:{acc}-1 rdf:value ?seq }}
  BIND(SUBSTR(?seq, ?begin, 1 + ?end - ?begin) AS ?wildType)
}}
LIMIT {limit}"""
```

> Note: the `BIND` is **top-level after** the `OPTIONAL`, not inside it — QLever
> does not bind a `SUBSTR` that lives inside an `OPTIONAL` and references outer
> variables. Keep it as written.

- [ ] **Step 4: Derive the fields in `shape_variants`** in `shaping.py`. Capture
  `wildType` in the merged entry, then classify each variant after the merge loop:

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
                "wild_type": row.get("wildType") or None,
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
    out = [_classify_variant(v) for v in merged.values()]
    out.sort(
        key=lambda v: (
            not v["diseases"],  # disease-associated first
            v["begin"] is None,
            v["begin"] if isinstance(v["begin"], int) else 0,
        )
    )
    return out


def _classify_variant(v: dict[str, Any]) -> dict[str, Any]:
    """Add variant_type and (for simple substitutions) HGVS-style notation."""
    sub, wt, begin, end = v.get("substitution"), v.get("wild_type"), v.get("begin"), v.get("end")
    is_substitution = (
        isinstance(sub, str) and len(sub) == 1 and begin == end and begin is not None
    )
    v["variant_type"] = "substitution" if is_substitution else "other"
    if is_substitution and wt:
        v["notation"] = f"{wt}{begin}{sub}"
    if v.get("wild_type") is None:
        v.pop("wild_type", None)
    return v
```

- [ ] **Step 5: Run unit test, expect PASS.**

- [ ] **Step 6: Add a live integration assertion** in `tests/integration/test_live.py`:

```python
@pytest.mark.integration
async def test_variants_wildtype_and_notation(live_service):
    res = await live_service.get_variants("Q96T60", 200)
    by_pos = {v["begin"]: v for v in res["variants"]}
    assert by_pos[176]["wild_type"] == "L"
    assert by_pos[176]["notation"] == "L176F"
    assert by_pos[408]["variant_type"] == "other"  # empty substitution
    assert "notation" not in by_pos[408]
```

- [ ] **Step 7: Update the tool description** in `proteins.py` `get_protein_variants`
  to mention the new fields (replace the description string):

```python
        description=(
            "Return natural-variant annotations for an entry: position, wild-type "
            "residue, amino-acid substitution, an HGVS-style `notation` (e.g. "
            "`L176F`) for simple substitutions, `variant_type` (substitution|other), "
            "free-text description, structured linked `diseases`, and `dbsnp` rsIDs. "
            "Set disease_associated_only=true to keep only disease-linked variants."
        ),
```

- [ ] **Step 8: Checkpoint** — `make ci-local` + `python research/verify_queries.py`.

---

### Task 2: `map_identifiers` becomes the focused id-mapping view (D2 / M2)

**Files:**
- Modify: `uniprot_link/services/sparql_service.py` (`map_identifiers`)
- Modify: `uniprot_link/mcp/tools/proteins.py` (tool descriptions)
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Write the failing unit test** in `tests/unit/test_service_and_tools.py`:

```python
async def test_map_identifiers_defaults_to_curated_dbs(service_factory):
    from tests.conftest import make_select_json
    from uniprot_link.services.constants import COMMON_XREF_DATABASES
    body = make_select_json(["db", "database", "xref"], [
        {"db": "http://purl.uniprot.org/database/Ensembl", "database": "Ensembl",
         "xref": "http://purl.uniprot.org/ensembl/ENSP00000269305"},
    ])
    # Route the xref SELECT and the existence ASK.
    service = service_factory([("rdfs:seeAlso", body), ("ASK", {"head": {}, "boolean": True})])
    res = await service.map_identifiers("P38398")  # no databases -> curated default
    assert res["requested_databases"] == COMMON_XREF_DATABASES
    assert "by_database" in res and "mapped_databases" in res
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Default to the curated set in `map_identifiers`** (`sparql_service.py`).
  Add the import at the top of the file (with the other `constants` imports):

```python
from uniprot_link.services.constants import COMMON_XREF_DATABASES, FEATURE_TYPES, UNIPROT_RELEASE
```

  and rewrite the method:

```python
    async def map_identifiers(
        self,
        accession: str,
        databases: list[str] | None = None,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Map a UniProt accession to a curated set of external id databases.

        Unlike get_cross_references (every xref database), map_identifiers focuses
        on primary id-mapping targets by default (COMMON_XREF_DATABASES) so the
        payload is small and mapping-oriented; pass `databases` to override.
        """
        effective = databases or COMMON_XREF_DATABASES
        result = await self.get_cross_references(accession, effective, response_mode)
        result["requested_databases"] = effective
        result["mapped_databases"] = list(result["by_database"].keys())
        return result
```

- [ ] **Step 4: Run unit test, expect PASS.**

- [ ] **Step 5: Clarify the two tool descriptions** in `proteins.py`. For
  `map_identifiers`, append to the description:
  `"Defaults to primary id-mapping databases (PDB, Ensembl, RefSeq, HGNC, ...); for
  the exhaustive xref list use get_protein_cross_references."` For
  `get_protein_cross_references`, change the trailing sentence to:
  `"Returns every cross-reference database; use map_identifiers for a focused
  primary-id mapping."`

- [ ] **Step 6: Add a live integration assertion** in `tests/integration/test_live.py`:

```python
@pytest.mark.integration
async def test_map_identifiers_is_smaller_than_full_xrefs(live_service):
    mapped = await live_service.map_identifiers("P38398")
    full = await live_service.get_cross_references("P38398")
    assert mapped["database_count"] <= full["database_count"]
    assert mapped["requested_databases"]
```

- [ ] **Step 7: Checkpoint** — `make ci-local`.

---

### Task 3: Actionable `query_syntax_error` (D3 / L2)

**Files:**
- Modify: `uniprot_link/mcp/tools/query.py` (`run_sparql_query` error context)
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Write the failing unit test** in `tests/unit/test_service_and_tools.py`:

```python
async def test_run_sparql_query_syntax_error_offers_examples_fallback(registered_mcp):
    # registered_mcp: the FastMCP instance with tools registered against a service
    # whose client raises QuerySyntaxError. (Mirror the existing tool-layer tests.)
    payload = await registered_mcp.call_tool("run_sparql_query", {"query": "SELEC bad"})
    assert payload["success"] is False
    assert payload["error_code"] == "query_syntax_error"
    cmds = payload["_meta"]["next_commands"]
    assert any(c["tool"] == "search_example_queries" for c in cmds)
```

(If the test harness for the tool layer differs, assert the same shape using the
existing pattern in `test_service_and_tools.py`.)

- [ ] **Step 2: Run it, expect FAIL** (no `next_commands` on the error envelope).

- [ ] **Step 3: Add the fallback** in `query.py`. Change the `run_sparql_query`
  wrapper call to provide a recovery `next_command`:

```python
        return await run_mcp_tool(
            "run_sparql_query",
            call,
            context=McpErrorContext(
                "run_sparql_query", fallback=cmd("search_example_queries")
            ),
        )
```

(`cmd` is already imported in `query.py`.)

- [ ] **Step 4: Run unit test, expect PASS.**
- [ ] **Step 5: Checkpoint** — `make ci-local`.

---

### Task 4: Version bump, capabilities note, changelog (v0.3.0)

**Files:**
- Modify: `uniprot_link/__init__.py` (`__version__`)
- Modify: `uniprot_link/mcp/capabilities.py` (variant-field note)
- Modify: `CHANGELOG.md`
- Test: `tests/unit/test_capabilities.py`

- [ ] **Step 1: Write the failing test** in `tests/unit/test_capabilities.py`:

```python
def test_capabilities_version_is_030():
    from uniprot_link.mcp.capabilities import build_capabilities
    assert build_capabilities()["server_version"] == "0.3.0"
```

- [ ] **Step 2: Run it, expect FAIL.**

- [ ] **Step 3: Bump the version** in `uniprot_link/__init__.py`:

```python
__version__ = "0.3.0"
```

- [ ] **Step 4: Add a `CHANGELOG.md` `[0.3.0]` entry** above `[0.2.0]`:

```markdown
## [0.3.0] - 2026-06-12

### Added

- `get_protein_variants` now returns the `wild_type` residue, a `variant_type`
  (`substitution` | `other`), and an HGVS-style `notation` (e.g. `L176F`) for
  simple substitutions — so amino-acid changes are constructible without a
  separate sequence fetch. Empty `substitution` (deletion/complex) is made
  explicit via `variant_type: "other"` instead of a bare empty string.
- Deployment-freshness guard: `get_server_capabilities` and `/health` now carry a
  `build` stamp (version, git sha, build time); `scripts/check_deployed_version.py`
  gates a release on the deployed version matching the source.
- `run_sparql_query` syntax errors now include a `search_example_queries`
  recovery `next_command`.

### Changed

- `map_identifiers` defaults to a curated set of primary id-mapping databases
  (PDB, Ensembl, RefSeq, HGNC, ...) so it is genuinely a focused, smaller view
  than `get_protein_cross_references`; pass `databases` to override.
```

- [ ] **Step 5: Run test, expect PASS.**

- [ ] **Step 6: Final checkpoint** — `make ci-local` (green) +
  `make test-integration` (all Wave 0 + Wave 1 live assertions pass) +
  `python research/verify_queries.py`.

- [ ] **Step 7: Re-deploy** `v0.3.0` and confirm
  `python scripts/check_deployed_version.py <url>` exits 0.

---

## Self-review — spec coverage

- Spec §0/§2 (deploy drift) → Wave 0 (Tasks 0.1–0.4) + Task 4 Step 7.
- Spec §3 D1 (variant wild-type/notation/blank-sub) → Task 1.
- Spec §3 D2 (map_identifiers focus) → Task 2.
- Spec §3 D3 (syntax-error hint) → Task 3.
- Spec §3 D4 (freshness guard) → Tasks 0.2–0.4.
- Spec §5 success criteria 1–2 → Task 0.1 + Task 0.4 Step 5; 3 → Task 1; 4 → Task 2;
  5 → Tasks 0.2–0.4; 6 → final checkpoint Task 4.
- Spec §4 out-of-scope (P1#6 feature evidence, L3 isoform mass, structured output)
  → intentionally **not** tasked; recorded in the spec with data-model reasons.

**Type/name consistency:** `build_info` (Tasks 0.2/0.3/0.4), `_classify_variant` +
`wild_type`/`variant_type`/`notation` (Task 1), `requested_databases` +
`COMMON_XREF_DATABASES` (Task 2) are used identically across tasks. No placeholders;
every code step shows complete code and an exact command.
