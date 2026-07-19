# uniprot-link v0.6.0 Assessment Uplift — Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every finding in `docs/mcp-assessment-v0.5.0.md` (F-OBS, F-ISO, F-VERB, F-SORT, F-ECO, F-MAP + the two nits) plus the static-chaining gap, lifting the consumer score from 8.7 to > 9.5.

**Architecture:** A single obsolete-aware `entry_status` SPARQL probe replaces the bare existence `ASK`, giving every tool a three-state (active / obsolete / absent) gate; `get_protein` returns a flagged obsolete record while data sub-tools raise an obsolete-flagged `not_found`. Heavy projection logic (entry-status shaping, obsolete-record building, lean-compact xref, go-term aspect/limit) lives in `shaping.py` to keep `sparql_service.py` under the 600-line cap. Content-aware `next_commands` are driven by three zero-latency `EXISTS` presence flags folded into the summary query.

**Tech Stack:** Python 3.12, FastMCP 3.4.2, httpx + respx, pytest/pytest-asyncio, Ruff, mypy (strict), `uv`. SPARQL 1.1 over QLever.

**Spec:** `docs/superpowers/specs/2026-06-12-mcp-assessment-uplift-v0.6.0-design.md`

---

## File map

| File | Responsibility / change |
|------|--------------------------|
| `uniprot_link/exceptions.py` | + `ObsoleteEntryError(NotFoundError)` |
| `uniprot_link/mcp/envelope.py` | obsolete branch: `obsolete` + `replaced_by` + replacement `next_commands` |
| `uniprot_link/services/queries/proteins.py` | `entry_status` (replaces `entry_exists_ask`); summary presence-flags; `protein_features(limit=...)` |
| `uniprot_link/services/queries/__init__.py` | export `entry_status` (drop `entry_exists_ask`) |
| `uniprot_link/services/shaping.py` | `EntryStatus` + `shape_entry_status`; `build_obsolete_record`; presence flags in `shape_protein_summary`; sorted + lean-compact xref; go aspect/limit/counts helper |
| `uniprot_link/services/sparql_service.py` | obsolete-aware `require_entry`; `get_protein` (status ∥ summary, obsolete/isoform); parallel-gated `get_sequence`; `get_features(limit)`; `get_go_terms(aspect,limit)`; lean `get_cross_references` |
| `uniprot_link/services/constants.py` | ECO map backfill + honest comment; `MAP_IDENTIFIER_DATABASES` |
| `uniprot_link/mcp/next_commands.py` | content-aware `after_get_protein`; `after_obsolete_entry` |
| `uniprot_link/mcp/tools/proteins.py` | `_ACC` drop `min_length`; go `aspect`/`limit`; features `limit`; doc fixes; wire content-aware chaining |
| `uniprot_link/mcp/schemas.py` | extend PROTEIN / CROSS_REFERENCES / MAP_IDENTIFIERS / GO_TERMS / FEATURES |
| `uniprot_link/mcp/capabilities.py` | obsolete contract, map-id dbs, ordering note |
| `uniprot_link/__init__.py` | version → 0.6.0 |
| `research/verify_queries.py` | live cases: entry_status (4 fixtures), enriched summary, features(limit) |
| `tests/unit/*`, `tests/integration/test_live.py` | new unit + one integration regression |

**Fixtures (live-verified):** `P05067` active; `Z9Z9Z9` obsolete (no replacement); `A0A009K1D9` demerged → `A0A9P2UQ24`; `A0A075B5G1` demerged → 3 replacements; `P05067-2` real isoform; `P05067-99` bogus isoform.

---

## Task 1: ObsoleteEntryError + envelope branch

**Files:**
- Modify: `uniprot_link/exceptions.py`
- Modify: `uniprot_link/mcp/envelope.py`
- Test: `tests/unit/test_exceptions.py`, `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Write failing test** (append to `tests/unit/test_service_and_tools.py`)

```python
@pytest.mark.asyncio
async def test_obsolete_entry_error_envelope_carries_replaced_by() -> None:
    from uniprot_link.exceptions import ObsoleteEntryError

    async def boom() -> dict[str, Any]:
        raise ObsoleteEntryError("A0A009K1D9", replaced_by=["A0A9P2UQ24"])

    out = await run_mcp_tool(
        "get_protein_features", boom,
        context=McpErrorContext("get_protein_features"),
    )
    assert out["success"] is False
    assert out["error_code"] == "not_found"
    assert out["obsolete"] is True
    assert out["replaced_by"] == ["A0A9P2UQ24"]
    nxt = out["_meta"]["next_commands"]
    assert nxt[0] == {"tool": "get_protein", "arguments": {"accession": "A0A9P2UQ24"}}
```

- [ ] **Step 2: Run, expect fail** — `uv run pytest tests/unit/test_service_and_tools.py::test_obsolete_entry_error_envelope_carries_replaced_by -q` → ImportError/Fail.

- [ ] **Step 3: Add exception** (append to `uniprot_link/exceptions.py`)

```python
class ObsoleteEntryError(NotFoundError):
    """A UniProtKB entry exists but is obsolete (demerged/deleted)."""

    def __init__(
        self,
        accession: str,
        replaced_by: list[str] | None = None,
        message: str | None = None,
    ) -> None:
        """Store the obsolete accession and any replacement accessions."""
        self.accession = accession
        self.replaced_by = replaced_by or []
        if message is None:
            if self.replaced_by:
                message = (
                    f"UniProtKB entry {accession} is obsolete (demerged). "
                    f"Replaced by: {', '.join(self.replaced_by)}."
                )
            else:
                message = (
                    f"UniProtKB entry {accession} is obsolete (deleted) "
                    "and has no replacement entry."
                )
        super().__init__(message)
```

- [ ] **Step 4: Wire envelope** — in `uniprot_link/mcp/envelope.py`:
  - Import `ObsoleteEntryError` from `uniprot_link.exceptions`.
  - Import `cmd` from `uniprot_link.mcp.next_commands` (already imports `default_error_next_commands` from there).
  - In `_error_envelope`, after the `InvalidInputError` block, add:

```python
    if isinstance(exc, ObsoleteEntryError):
        envelope["obsolete"] = True
        envelope["replaced_by"] = exc.replaced_by
        if exc.replaced_by:
            envelope["_meta"]["next_commands"] = [
                cmd("get_protein", accession=acc) for acc in exc.replaced_by[:2]
            ]
            return envelope  # explicit replacement chain wins over defaults
```

  Note: `ObsoleteEntryError` is a subclass of `NotFoundError`, so the existing
  `isinstance(exc, NotFoundError)` branch in `_classify` already yields
  `error_code="not_found"`. Keep the `_classify` order (NotFoundError check stays).
  The early `return` only fires when there is a replacement; the no-replacement
  case falls through to the default `not_found` next_commands
  (`get_server_capabilities`).

- [ ] **Step 5: Run** — same test → PASS.

- [ ] **Step 6: Commit**

```bash
git add uniprot_link/exceptions.py uniprot_link/mcp/envelope.py tests/unit/test_service_and_tools.py
git commit -m "feat(obsolete): ObsoleteEntryError + envelope replaced_by/next_commands (F-OBS)"
```

---

## Task 2: entry_status query + EntryStatus shaping

**Files:**
- Modify: `uniprot_link/services/queries/proteins.py` (replace `entry_exists_ask`)
- Modify: `uniprot_link/services/queries/__init__.py`
- Modify: `uniprot_link/services/shaping.py`
- Test: `tests/unit/test_queries.py`, `tests/unit/test_shaping.py`

- [ ] **Step 1: Failing shaping test** (append to `tests/unit/test_shaping.py`)

```python
def test_shape_entry_status_active_obsolete_absent_isoform() -> None:
    from uniprot_link.services.shaping import shape_entry_status

    active = make_select_json(["obsolete"], [{"obsolete": False}])
    st = shape_entry_status(active, "P05067")
    assert st.exists and not st.obsolete and st.replaced_by == []

    obsolete = make_select_json(
        ["obsolete", "replacedBy"],
        [
            {"obsolete": True, "replacedBy": "http://purl.uniprot.org/uniprot/A0A9P2UQ24"},
            {"obsolete": True, "replacedBy": "http://purl.uniprot.org/uniprot/B0B0B0"},
        ],
    )
    st = shape_entry_status(obsolete, "A0A009K1D9")
    assert st.exists and st.obsolete
    assert st.replaced_by == ["A0A9P2UQ24", "B0B0B0"]  # sorted, deduped

    absent = make_select_json([], [])
    st = shape_entry_status(absent, "Q9ZZZ9")
    assert not st.exists and not st.obsolete

    iso = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": True}]
    )
    st = shape_entry_status(iso, "P05067-2")
    assert st.isoform_exists is True
```

- [ ] **Step 2: Failing query test** (append to `tests/unit/test_queries.py`)

```python
def test_entry_status_builds_obsolete_aware_gate() -> None:
    from uniprot_link.services.queries import entry_status

    q = entry_status("P05067")
    assert "a up:Protein" in q
    assert "up:obsolete ?obsolete" in q
    assert "up:replacedBy ?replacedBy" in q
    assert "isoform_exists" not in q  # no suffix -> no isoform probe

    qi = entry_status("P05067-2")
    assert "isoform:P05067-2" in qi
    assert "isoform_exists" in qi
```

- [ ] **Step 3: Run both, expect fail.**

- [ ] **Step 4: Replace `entry_exists_ask` in `queries/proteins.py`**

```python
def entry_status(accession: str) -> str:
    """Build a SELECT classifying an entry as active / obsolete / absent.

    0 rows -> absent. A row with ``up:obsolete true`` -> obsolete (with any
    ``up:replacedBy`` accessions). Otherwise active. When the accession carries a
    ``-N`` isoform suffix, an ``EXISTS`` probe reports whether that isoform is
    real (so get_protein can reject a typo'd index, F-ISO). Obsolete entries keep
    ``a up:Protein`` (verified live on Z9Z9Z9 / A0A009K1D9), so the bare
    existence ASK could not distinguish them -- this query can.
    """
    acc = validate_accession(accession)
    base = acc.split("-")[0]
    iso_select = ""
    iso_bind = ""
    if "-" in acc:
        iso_select = " ?isoform_exists"
        iso_bind = (
            f"\n  BIND(EXISTS {{ uniprotkb:{base} up:sequence isoform:{acc} }} "
            "AS ?isoform_exists)"
        )
    return f"""{prefix_block()}
SELECT ?obsolete ?replacedBy{iso_select} WHERE {{
  uniprotkb:{base} a up:Protein .
  OPTIONAL {{ uniprotkb:{base} up:obsolete ?obsolete }}
  OPTIONAL {{ uniprotkb:{base} up:replacedBy ?replacedBy }}{iso_bind}
}}"""
```

- [ ] **Step 5: Export** — in `queries/__init__.py` replace any `entry_exists_ask` export with `entry_status` (check the `from .proteins import (...)` group and `__all__`).

- [ ] **Step 6: Add `EntryStatus` + `shape_entry_status` to `shaping.py`** (near the top-level shapers; add `from dataclasses import dataclass` import)

```python
@dataclass(frozen=True)
class EntryStatus:
    """Three-state result of the entry_status probe."""

    exists: bool
    obsolete: bool
    replaced_by: list[str]
    isoform_exists: bool | None


def shape_entry_status(result_json: dict[str, Any] | None, requested: str) -> EntryStatus:
    """Classify entry_status rows into active / obsolete / absent (+ isoform)."""
    data = rows(result_json)
    if not data:
        return EntryStatus(exists=False, obsolete=False, replaced_by=[], isoform_exists=None)
    obsolete = any(r.get("obsolete") is True for r in data)
    replaced = sorted(
        {accession_from_uri(r["replacedBy"]) for r in data if r.get("replacedBy")}
    )
    iso = None
    if "-" in requested:
        iso = any(r.get("isoform_exists") is True for r in data)
    return EntryStatus(
        exists=True, obsolete=obsolete, replaced_by=replaced, isoform_exists=iso
    )
```

- [ ] **Step 7: Run both tests → PASS.** Also run `uv run pytest tests/unit/test_queries.py tests/unit/test_shaping.py -q`.

- [ ] **Step 8: Commit**

```bash
git add uniprot_link/services/queries/proteins.py uniprot_link/services/queries/__init__.py uniprot_link/services/shaping.py tests/unit/test_queries.py tests/unit/test_shaping.py
git commit -m "feat(obsolete): entry_status query + EntryStatus shaping (F-OBS, F-ISO)"
```

---

## Task 3: Obsolete-aware `require_entry` + family consistency

**Files:**
- Modify: `uniprot_link/services/sparql_service.py` (`require_entry`, `get_sequence`)
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_data_subtools_raise_obsolete_on_obsolete_entry(service_factory: Any) -> None:
    from uniprot_link.exceptions import ObsoleteEntryError

    # entry_status returns an obsolete row with a replacement.
    status = make_select_json(
        ["obsolete", "replacedBy"],
        [{"obsolete": True, "replacedBy": "http://purl.uniprot.org/uniprot/A0A9P2UQ24"}],
    )
    svc = service_factory([("up:obsolete ?obsolete", status)])
    for call in (
        svc.get_features, svc.get_variants, svc.get_diseases,
        svc.get_go_terms, svc.get_cross_references, svc.get_sequence,
    ):
        with pytest.raises(ObsoleteEntryError) as ei:
            await call("A0A009K1D9")
        assert ei.value.replaced_by == ["A0A9P2UQ24"]
```

  Note: the route needle `"up:obsolete ?obsolete"` matches only the entry_status
  query (the data queries don't contain it), so the data query returns the empty
  default — fine, the gate raises before shaping matters. `get_sequence` runs the
  gate in parallel, so it must also raise.

- [ ] **Step 2: Run, expect fail** (current `require_entry` uses `entry_exists_ask`/ASK).

- [ ] **Step 3: Rewrite `require_entry`** in `sparql_service.py`

```python
    async def require_entry(self, accession: str) -> None:
        """Gate annotation lookups: raise on absent or obsolete entries (cached).

        Obsolete entries retain ``a up:Protein`` so a bare existence check passes
        them through; entry_status separates active / obsolete / absent and lets
        the whole tool family emit one consistent obsolete signal (F-OBS).
        """
        status = S.shape_entry_status(
            await self._select(Q.entry_status(accession)), accession
        )
        if not status.exists:
            raise NotFoundError(
                f"No UniProtKB entry found for accession '{accession}'. "
                "Resolve a gene/organism via find_proteins first."
            )
        if status.obsolete:
            raise ObsoleteEntryError(
                Q.validate_accession(accession).split("-")[0], status.replaced_by
            )
```

  Add `ObsoleteEntryError` to the `from uniprot_link.exceptions import (...)` group.

- [ ] **Step 4: Route `get_sequence` through the gate in parallel.** Change the head of `get_sequence`:

```python
    async def get_sequence(self, accession: str, response_mode: str = "compact") -> dict[str, Any]:
        """Return the canonical sequence (and additional isoforms) for an entry."""
        query = Q.protein_sequence(accession)
        _, (sequences_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        sequences = S.shape_sequences(sequences_json)
        if not sequences:
            raise NotFoundError(f"No sequence found for accession '{accession}'.")
        ...
```

  (The existing body below `sequences = ...` is unchanged.)

- [ ] **Step 5: Run** the new test + the existing `test_annotation_tools_not_found_when_entry_absent`. The absent test routes `("ASK", boolean False)` — update it: the gate no longer issues an ASK. Change that test's route to an empty entry_status result:

```python
    routes = [("up:obsolete ?obsolete", {"head": {"vars": []}, "results": {"bindings": []}})]
```

  and keep asserting `NotFoundError`. Run `uv run pytest tests/unit/test_service_and_tools.py -q`.

- [ ] **Step 6: Commit**

```bash
git add uniprot_link/services/sparql_service.py tests/unit/test_service_and_tools.py
git commit -m "feat(obsolete): obsolete-aware require_entry across the data tools (F-OBS)"
```

---

## Task 4: get_protein — obsolete record, isoform echo, presence flags

**Files:**
- Modify: `uniprot_link/services/queries/proteins.py` (`protein_summary` presence flags)
- Modify: `uniprot_link/services/shaping.py` (`shape_protein_summary` flags; `build_obsolete_record`)
- Modify: `uniprot_link/services/sparql_service.py` (`get_protein`)
- Test: `tests/unit/test_service_and_tools.py`, `tests/unit/test_shaping.py`

- [ ] **Step 1: Failing tests** (append to `tests/unit/test_service_and_tools.py`)

```python
@pytest.mark.asyncio
async def test_get_protein_obsolete_returns_flagged_record(service_factory: Any) -> None:
    status = make_select_json(
        ["obsolete", "replacedBy"],
        [{"obsolete": True, "replacedBy": "http://purl.uniprot.org/uniprot/A0A9P2UQ24"}],
    )
    summary = make_select_json(
        ["mnemonic", "reviewed"], [{"mnemonic": "A0A009K1D9_ACIBA", "reviewed": False}]
    )
    svc = service_factory(
        [("up:obsolete ?obsolete", status), ("up:recommendedName", summary)]
    )
    out = await svc.get_protein("A0A009K1D9")
    assert out["obsolete"] is True
    assert out["replaced_by"] == ["A0A9P2UQ24"]
    assert out["obsolete_reason"] == "demerged"
    assert out["mnemonic"] == "A0A009K1D9_ACIBA"
    assert "sequence_length" not in out and "mass_da" not in out  # nothing fabricated
    assert out["requested_accession"] == "A0A009K1D9"


@pytest.mark.asyncio
async def test_get_protein_bogus_isoform_is_not_found(service_factory: Any) -> None:
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": False}]
    )
    summary = make_select_json(["mnemonic"], [{"mnemonic": "A4_HUMAN"}])
    svc = service_factory(
        [("up:obsolete ?obsolete", status), ("up:recommendedName", summary)]
    )
    with pytest.raises(NotFoundError):
        await svc.get_protein("P05067-99")


@pytest.mark.asyncio
async def test_get_protein_real_isoform_echoes_request(service_factory: Any) -> None:
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": True}]
    )
    summary = make_select_json(
        ["mnemonic", "has_variants", "has_diseases", "has_structure"],
        [{"mnemonic": "A4_HUMAN", "has_variants": True, "has_diseases": True,
          "has_structure": True}],
    )
    svc = service_factory(
        [("up:obsolete ?obsolete", status), ("up:recommendedName", summary)]
    )
    out = await svc.get_protein("P05067-2")
    assert out["accession"] == "P05067"
    assert out["requested_accession"] == "P05067-2"
    assert out["isoform"] == "P05067-2"
    assert out["has_variants"] is True
```

- [ ] **Step 2: Failing shaping test** (append to `tests/unit/test_shaping.py`)

```python
def test_shape_protein_summary_carries_presence_flags() -> None:
    body = make_select_json(
        ["mnemonic", "has_variants", "has_diseases", "has_structure"],
        [{"mnemonic": "A4_HUMAN", "has_variants": True, "has_diseases": False,
          "has_structure": True}],
    )
    out = S.shape_protein_summary(body)
    assert out["has_variants"] is True
    assert out["has_diseases"] is False  # explicit False kept (presence flag)
    assert out["has_structure"] is True
```

- [ ] **Step 3: Run, expect fail.**

- [ ] **Step 4: Add presence-flag projections to `protein_summary`** in `queries/proteins.py`. Add to the SELECT list and the WHERE body (anchored on the entry IRI, bound EXISTS — verified ~206 ms live):

  In the SELECT line append:
```
       ?has_variants ?has_diseases ?has_structure
```
  Before the closing `}` of the WHERE block add:
```sparql
  BIND(EXISTS { uniprotkb:{base} up:annotation ?_v . ?_v a up:Natural_Variant_Annotation } AS ?has_variants)
  BIND(EXISTS { uniprotkb:{base} up:annotation ?_d . ?_d a up:Disease_Annotation } AS ?has_diseases)
  BIND(EXISTS { uniprotkb:{base} rdfs:seeAlso ?_x . ?_x up:database database:PDB } AS ?has_structure)
```
  (`database:` and `rdfs:` are already in the full `prefix_block()`.)

- [ ] **Step 5: Surface flags in `shape_protein_summary`.** After building `summary` (before the dict-filter return), add the three booleans bypassing the `None/[]/""` filter (a `False` flag must survive):

```python
    flags = {
        k: r[k] for k in ("has_variants", "has_diseases", "has_structure") if k in r
    }
    cleaned = {k: v for k, v in summary.items() if v not in (None, [], "")}
    return {**cleaned, **flags}
```

- [ ] **Step 6: Add `build_obsolete_record` to `shaping.py`**

```python
def build_obsolete_record(
    accession: str, status: "EntryStatus", summary: dict[str, Any] | None
) -> dict[str, Any]:
    """Build the flagged obsolete record returned by get_protein (F-OBS)."""
    record: dict[str, Any] = {
        "accession": accession,
        "obsolete": True,
        "obsolete_reason": "demerged" if status.replaced_by else "deleted",
        "notice": (
            "This UniProtKB entry is obsolete and is not a live record. "
            + (
                f"It was demerged/replaced by: {', '.join(status.replaced_by)}."
                if status.replaced_by
                else "It was deleted and has no replacement entry."
            )
        ),
    }
    if status.replaced_by:
        record["replaced_by"] = status.replaced_by
    # Carry only the sparse identity fields that survive on an obsolete entry.
    for key in ("mnemonic", "reviewed"):
        if summary and summary.get(key) is not None:
            record[key] = summary[key]
    return record
```

- [ ] **Step 7: Rewrite `get_protein`** in `sparql_service.py`

```python
    async def get_protein(self, accession: str, response_mode: str = "compact") -> dict[str, Any]:
        """Return the core summary for a single entry (obsolete/isoform aware)."""
        status_json, (summary_json, qmeta) = await asyncio.gather(
            self._select(Q.entry_status(accession)),
            self._select_timed(Q.protein_summary(accession)),
        )
        status = S.shape_entry_status(status_json, accession)
        summary = S.shape_protein_summary(summary_json)
        acc = Q.validate_accession(accession).split("-")[0]
        if not status.exists and summary is None:
            raise NotFoundError(
                f"No UniProtKB entry found for accession '{accession}'. "
                "Resolve a gene/organism via find_proteins first."
            )
        if status.obsolete:
            record = S.build_obsolete_record(acc, status, summary)
            record["requested_accession"] = accession
            return {**record, **qmeta}
        if status.isoform_exists is False:
            raise NotFoundError(
                f"No isoform '{accession}' exists for entry {acc}. "
                "Call get_protein_sequence to list the entry's isoforms."
            )
        if summary is None:
            raise NotFoundError(f"No UniProtKB entry found for accession '{accession}'.")
        payload: dict[str, Any] = {
            "accession": acc, "requested_accession": accession, **summary, **qmeta
        }
        if status.isoform_exists:
            payload["isoform"] = accession
            payload["isoform_note"] = (
                "Summary is entry-level; call get_protein_sequence for the "
                f"isoform-specific sequence and mass of {accession}."
            )
        return S.apply_response_mode(payload, response_mode, kind="protein")
```

  Note `_MODE_DROP` must not drop the new keys (it only drops created/modified/
  short_name/common_name/function) — presence flags and echoes survive all modes.

- [ ] **Step 8: Run** the Task-4 tests + existing get_protein tests. The existing
  `test_get_protein_not_found_raises` routes `("up:recommendedName", _EMPTY)` only;
  entry_status returns the empty default (absent), summary empty → NotFound. Good.
  `test_get_protein_bogus_accession_raises_not_found` routes `("a up:Protein", empty)`
  — both queries contain `a up:Protein`, both empty → absent + summary None →
  NotFound. Good. `test_tool_call_through_facade` summary now also yields presence
  flags absent (not in `_SUMMARY`) → fine. Run `uv run pytest tests/unit -q`.

- [ ] **Step 9: Commit**

```bash
git add uniprot_link/services/queries/proteins.py uniprot_link/services/shaping.py uniprot_link/services/sparql_service.py tests/unit/test_service_and_tools.py tests/unit/test_shaping.py
git commit -m "feat(get_protein): obsolete record + isoform echo + presence flags (F-OBS, F-ISO)"
```

---

## Task 5: Content-aware chaining + obsolete chaining

**Files:**
- Modify: `uniprot_link/mcp/next_commands.py`
- Modify: `uniprot_link/mcp/tools/proteins.py` (`get_protein` tool wiring)
- Test: `tests/unit/test_next_commands.py`, `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Failing test** (append to `tests/unit/test_next_commands.py`)

```python
def test_after_get_protein_is_content_aware() -> None:
    from uniprot_link.mcp.next_commands import after_get_protein

    # No diseases/variants -> only sequence + features suggested.
    plain = after_get_protein("P05067", has_variants=False, has_diseases=False,
                              has_structure=False)
    tools = [c["tool"] for c in plain]
    assert "get_protein_sequence" in tools
    assert "get_protein_diseases" not in tools

    # Disease-bearing entry surfaces diseases first among the gated suggestions.
    rich = after_get_protein("P05067", has_variants=True, has_diseases=True,
                             has_structure=True)
    rtools = [c["tool"] for c in rich]
    assert "get_protein_diseases" in rtools or "get_protein_variants" in rtools
    assert len(rich) <= 3
```

- [ ] **Step 2: Run, expect fail** (current `after_get_protein` takes only `accession`).

- [ ] **Step 3: Rewrite `after_get_protein`** in `next_commands.py`

```python
def after_get_protein(
    accession: str,
    *,
    has_variants: bool = False,
    has_diseases: bool = False,
    has_structure: bool = False,
) -> list[dict[str, Any]]:
    """Suggest sub-resources, content-gated by what the entry actually has.

    Sequence + features are always useful; the annotation tools are offered only
    when the cheap presence flags say there is something to fetch (avoids the
    static-suggestion trap the assessment flagged). Trimmed to 3 (token diet).
    """
    chain = [cmd("get_protein_sequence", accession=accession)]
    if has_diseases:
        chain.append(cmd("get_protein_diseases", accession=accession))
    if has_variants:
        chain.append(cmd("get_protein_variants", accession=accession))
    chain.append(cmd("get_protein_features", accession=accession))
    if has_structure:
        chain.append(cmd("get_protein_cross_references", accession=accession))
    return chain[:3]


def after_obsolete_entry(replaced_by: list[str]) -> list[dict[str, Any]]:
    """After an obsolete get_protein: point at the replacement entries."""
    if not replaced_by:
        return [cmd("get_server_capabilities")]
    return [cmd("get_protein", accession=a) for a in replaced_by[:2]]
```

- [ ] **Step 4: Wire the `get_protein` tool** in `tools/proteins.py`. Replace the
  `payload["_meta"]` assignment inside the `get_protein` tool body:

```python
            payload = await service.get_protein(accession, response_mode)
            if payload.get("obsolete"):
                nxt = after_obsolete_entry(payload.get("replaced_by", []))
            else:
                nxt = after_get_protein(
                    payload["accession"],
                    has_variants=bool(payload.get("has_variants")),
                    has_diseases=bool(payload.get("has_diseases")),
                    has_structure=bool(payload.get("has_structure")),
                )
            payload["_meta"] = {"next_commands": nxt}
            return payload
```

  Add `after_obsolete_entry` to the `from uniprot_link.mcp.next_commands import (...)` group.

- [ ] **Step 5: Update `test_tool_call_through_facade`** — `_SUMMARY` has no presence
  flags, so `after_get_protein` returns `[sequence, features]`; the existing assert
  `next_commands[0]["tool"] == "get_protein_sequence"` still holds. Run
  `uv run pytest tests/unit/test_next_commands.py tests/unit/test_service_and_tools.py -q`.

- [ ] **Step 6: Commit**

```bash
git add uniprot_link/mcp/next_commands.py uniprot_link/mcp/tools/proteins.py tests/unit/test_next_commands.py
git commit -m "feat(chaining): content-aware get_protein next_commands + obsolete chain"
```

---

## Task 6: F-SORT — deterministic id ordering

**Files:**
- Modify: `uniprot_link/services/shaping.py` (`shape_cross_references`)
- Test: `tests/unit/test_shaping.py`

- [ ] **Step 1: Failing test**

```python
def test_shape_cross_references_sorts_ids_and_db_keys() -> None:
    body = make_select_json(
        ["db", "database", "xref"],
        [
            {"db": "http://purl.uniprot.org/database/PDB", "database": "PDB", "xref": "http://x/7JXN"},
            {"db": "http://purl.uniprot.org/database/PDB", "database": "PDB", "xref": "http://x/1AAP"},
            {"db": "http://purl.uniprot.org/database/RefSeq", "database": "RefSeq", "xref": "http://x/NP_2"},
        ],
    )
    out = S.shape_cross_references(body)
    assert out["PDB"] == ["1AAP", "7JXN"]          # ids sorted
    assert list(out.keys()) == ["PDB", "RefSeq"]   # db keys sorted
```

- [ ] **Step 2: Run, expect fail** (currently raw row order).

- [ ] **Step 3: Sort in `shape_cross_references`.** Replace the trailing `return grouped`:

```python
    return {db: sorted(ids) for db, ids in sorted(grouped.items())}
```

- [ ] **Step 4: Run → PASS.** The existing `test_shape_cross_references_groups`
  (count==2) and `test_shape_cross_references_short_vs_full_ids` still pass.

- [ ] **Step 5: Commit**

```bash
git add uniprot_link/services/shaping.py tests/unit/test_shaping.py
git commit -m "fix(xref): sort id lists and db keys for determinism (F-SORT)"
```

---

## Task 7: F-ECO — authoritative ECO map + honest comment

**Files:**
- Modify: `uniprot_link/services/constants.py` (`ECO_TO_GO_CODE` + comment)
- Test: `tests/unit/test_shaping.py`

- [ ] **Step 1: Failing test** (append to `tests/unit/test_shaping.py`)

```python
def test_shape_go_terms_maps_high_throughput_eco_codes() -> None:
    body = make_select_json(
        ["go", "label", "aspect", "eco"],
        [
            {"go": "http://purl.obolibrary.org/obo/GO_0070062", "label": "extracellular exosome",
             "aspect": "http://purl.obolibrary.org/obo/GO_0005575",
             "eco": "http://purl.obolibrary.org/obo/ECO_0007005"},
            {"go": "http://purl.obolibrary.org/obo/GO_0070062", "label": "extracellular exosome",
             "aspect": "http://purl.obolibrary.org/obo/GO_0005575",
             "eco": "http://purl.obolibrary.org/obo/ECO_0000269"},
        ],
    )
    term = S.shape_go_terms(body)["cellular_component"][0]
    assert "HDA" in term["evidence_codes"]  # ECO_0007005
    assert "EXP" in term["evidence_codes"]  # ECO_0000269
    assert set(term["evidence"]) == {"ECO:0007005", "ECO:0000269"}  # raw ids retained
```

- [ ] **Step 2: Run, expect fail** (HDA/EXP missing).

- [ ] **Step 3: Backfill `ECO_TO_GO_CODE`** in `constants.py` — add the 11 missing
  entries to the dict and fix the comment:

```python
# Common ECO evidence-ontology codes -> GO evidence code. UniProt GO annotations
# carry an ECO IRI (e.g. ECO_0000314); these map them to the familiar
# three-letter GO codes via the evidenceontology Default mapping
# (gaf-eco-mapping-derived.txt). The raw ECO id is always reported under a term's
# `evidence` list; only mapped ids appear under `evidence_codes`.
ECO_TO_GO_CODE: dict[str, str] = {
    "ECO_0000314": "IDA",
    "ECO_0000316": "IGI",
    "ECO_0000353": "IPI",
    "ECO_0000315": "IMP",
    "ECO_0000270": "IEP",
    "ECO_0000269": "EXP",
    "ECO_0000250": "ISS",
    "ECO_0000266": "ISO",
    "ECO_0000247": "ISA",
    "ECO_0000255": "ISM",
    "ECO_0000317": "IGC",
    "ECO_0000318": "IBA",
    "ECO_0000319": "IBD",
    "ECO_0000320": "IKR",
    "ECO_0000321": "IRD",
    "ECO_0000245": "RCA",
    "ECO_0000501": "IEA",
    "ECO_0007669": "IEA",
    "ECO_0007005": "HDA",
    "ECO_0007007": "HEP",
    "ECO_0007003": "HGI",
    "ECO_0007001": "HMP",
    "ECO_0006056": "HTP",
    "ECO_0000304": "TAS",
    "ECO_0000303": "NAS",
    "ECO_0000305": "IC",
    "ECO_0000307": "ND",
}
```

- [ ] **Step 4: Run → PASS.** Existing GO evidence test (`IDA`/`IEA`) still passes.

- [ ] **Step 5: Commit**

```bash
git add uniprot_link/services/constants.py tests/unit/test_shaping.py
git commit -m "fix(go): backfill ECO->GO evidence codes from authoritative map (F-ECO)"
```

---

## Task 8: F-MAP — focused primary-id default

**Files:**
- Modify: `uniprot_link/services/constants.py` (+ `MAP_IDENTIFIER_DATABASES`)
- Modify: `uniprot_link/services/sparql_service.py` (`map_identifiers`)
- Modify: `uniprot_link/mcp/tools/proteins.py` (doc), `uniprot_link/mcp/capabilities.py`
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Failing test** — update `test_map_identifiers_defaults_to_curated_dbs`:

```python
@pytest.mark.asyncio
async def test_map_identifiers_defaults_to_primary_id_set(service_factory: Any) -> None:
    from uniprot_link.services.constants import MAP_IDENTIFIER_DATABASES

    body = make_select_json(
        ["db", "database", "xref"],
        [{"db": "http://purl.uniprot.org/database/Ensembl", "database": "Ensembl",
          "xref": "http://purl.uniprot.org/ensembl/ENSP00000269305"}],
    )
    service = service_factory(
        [("rdfs:seeAlso", body), ("up:obsolete ?obsolete", make_select_json(["obsolete"], [{"obsolete": False}]))]
    )
    res = await service.map_identifiers("P38398")
    assert res["requested_databases"] == MAP_IDENTIFIER_DATABASES
    assert "DrugBank" not in MAP_IDENTIFIER_DATABASES
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Add constant** to `constants.py` (after `COMMON_XREF_DATABASES`):

```python
# Focused primary id-mapping targets (genomic / structural / family identifiers).
# map_identifiers defaults to this set so it is genuinely distinct from the
# exhaustive get_protein_cross_references (which keeps drug/disease-assoc DBs).
MAP_IDENTIFIER_DATABASES = [
    "PDB",
    "AlphaFoldDB",
    "Ensembl",
    "RefSeq",
    "GeneID",
    "HGNC",
    "KEGG",
    "OrthoDB",
    "Pfam",
    "InterPro",
]
```

- [ ] **Step 4: Point `map_identifiers` at it.** In `sparql_service.py`, change the
  import and default:
  - import: `from uniprot_link.services.constants import (... MAP_IDENTIFIER_DATABASES ...)`
  - in `map_identifiers`: `effective = list(databases or MAP_IDENTIFIER_DATABASES)`

- [ ] **Step 5: Doc text.** In `tools/proteins.py` `map_identifiers` description,
  replace the "Defaults to primary id-mapping databases (PDB, Ensembl, RefSeq, HGNC,
  ...)" line so it names the focused intent and contrasts with cross_references. In
  `capabilities.py` add a `map_identifier_databases` key listing the set.

- [ ] **Step 6: Run → PASS** (`uv run pytest tests/unit/test_service_and_tools.py -q`).

- [ ] **Step 7: Commit**

```bash
git add uniprot_link/services/constants.py uniprot_link/services/sparql_service.py uniprot_link/mcp/tools/proteins.py uniprot_link/mcp/capabilities.py tests/unit/test_service_and_tools.py
git commit -m "feat(map): focus map_identifiers on a primary-id core (F-MAP)"
```

---

## Task 9: F-VERB — lean-compact cross-references + counts

**Files:**
- Modify: `uniprot_link/services/shaping.py` (`shape_cross_references` → counts + cap)
- Modify: `uniprot_link/services/sparql_service.py` (`get_cross_references`)
- Modify: `uniprot_link/mcp/schemas.py`
- Test: `tests/unit/test_shaping.py`, `tests/unit/test_service_and_tools.py`

Design: a new shaper that returns counts + (mode-capped) id lists. Keep
`shape_cross_references` (sorted) as the raw grouper; add a projection helper.

- [ ] **Step 1: Failing test** (append to `tests/unit/test_service_and_tools.py`)

```python
@pytest.mark.asyncio
async def test_cross_references_lean_compact_and_minimal(service_factory: Any) -> None:
    rows_ = [
        {"db": "http://purl.uniprot.org/database/PDB", "database": "PDB",
         "xref": f"http://x/{i:04d}"} for i in range(40)
    ]
    body = make_select_json(["db", "database", "xref"], rows_)
    routes = [
        ("up:obsolete ?obsolete", make_select_json(["obsolete"], [{"obsolete": False}])),
        ("rdfs:seeAlso", body),
    ]
    svc = service_factory(routes)
    compact = await svc.get_cross_references("P05067")  # default compact
    assert compact["counts"]["PDB"] == 40
    assert len(compact["by_database"]["PDB"]) == 25       # capped
    assert compact["truncated_databases"]["PDB"] == {"returned": 25, "total": 40}
    minimal = await svc.get_cross_references("P05067", response_mode="minimal")
    assert "by_database" not in minimal
    assert minimal["counts"]["PDB"] == 40
    full = await svc.get_cross_references("P05067", response_mode="full")
    assert len(full["by_database"]["PDB"]) == 40          # all ids
    assert "truncated_databases" not in full
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Add the projection helper** to `shaping.py`

```python
_XREF_COMPACT_ID_CAP = 25


def project_cross_references(
    grouped: dict[str, list[str]], *, mode: str
) -> dict[str, Any]:
    """Project sorted, grouped xrefs for a response_mode (token economy, F-VERB).

    counts/total/database_count are always present. minimal omits id lists;
    compact caps each db at _XREF_COMPACT_ID_CAP (with truncated_databases);
    standard/full return every id.
    """
    counts = {db: len(ids) for db, ids in grouped.items()}
    out: dict[str, Any] = {
        "database_count": len(grouped),
        "total": sum(counts.values()),
        "counts": counts,
    }
    if mode == "minimal":
        return out
    if mode in ("standard", "full"):
        out["by_database"] = grouped
        return out
    # compact: cap per database, flag truncation.
    capped: dict[str, list[str]] = {}
    truncated: dict[str, dict[str, int]] = {}
    for db, ids in grouped.items():
        if len(ids) > _XREF_COMPACT_ID_CAP:
            capped[db] = ids[:_XREF_COMPACT_ID_CAP]
            truncated[db] = {"returned": _XREF_COMPACT_ID_CAP, "total": len(ids)}
        else:
            capped[db] = ids
    out["by_database"] = capped
    if truncated:
        out["truncated_databases"] = truncated
    return out
```

- [ ] **Step 4: Rewrite `get_cross_references`** in `sparql_service.py`

```python
    async def get_cross_references(
        self,
        accession: str,
        databases: list[str] | None = None,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return cross-references grouped by database (token-lean by mode)."""
        query = Q.protein_cross_references(accession, databases)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        grouped = S.shape_cross_references(data_json, short=response_mode != "full")
        projected = S.project_cross_references(grouped, mode=response_mode)
        acc = Q.validate_accession(accession).split("-")[0]
        return {"accession": acc, **projected, **qmeta}
```

- [ ] **Step 5: Update `map_identifiers`** so it keeps `requested_databases` /
  `mapped_databases` (derive `mapped_databases` from `counts` keys now):

```python
        result = await self.get_cross_references(accession, effective, response_mode)
        result["requested_databases"] = effective
        result["mapped_databases"] = list(result.get("counts", {}).keys())
        return result
```

- [ ] **Step 6: Schemas** — in `schemas.py` extend:

```python
CROSS_REFERENCES_SCHEMA = _envelope(
    accession=_STR, database_count=_INT, total=_INT, counts=_OBJ,
    by_database=_OBJ, truncated_databases=_OBJ,
)
MAP_IDENTIFIERS_SCHEMA = _envelope(
    accession=_STR, database_count=_INT, counts=_OBJ, by_database=_OBJ,
    requested_databases=_ARR, mapped_databases=_ARR, truncated_databases=_OBJ,
)
```

- [ ] **Step 7: Fix existing xref tests.** `test_cross_references_short_by_default_full_on_request`
  and `test_shape_cross_references_short_vs_full_ids` assert `by_database` directly
  on small lists — they still hold (1 id < cap). Update
  `test_map_identifiers_defaults_to_primary_id_set` route already added in Task 8.
  Run `uv run pytest tests/unit -q`.

- [ ] **Step 8: Commit**

```bash
git add uniprot_link/services/shaping.py uniprot_link/services/sparql_service.py uniprot_link/mcp/schemas.py tests/unit
git commit -m "feat(xref): lean-compact counts + per-db cap; minimal=counts-only (F-VERB)"
```

---

## Task 10: F-VERB — go_terms aspect / limit / counts

**Files:**
- Modify: `uniprot_link/services/sparql_service.py` (`get_go_terms`)
- Modify: `uniprot_link/services/shaping.py` (helper to count/filter/limit grouped terms)
- Modify: `uniprot_link/mcp/schemas.py`, `uniprot_link/mcp/tools/proteins.py`
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_go_terms_aspect_filter_limit_and_counts(service_factory: Any) -> None:
    rows_ = [
        {"go": f"http://purl.obolibrary.org/obo/GO_{i:07d}", "label": f"t{i}",
         "aspect": "http://purl.obolibrary.org/obo/GO_0008150"} for i in range(3)
    ] + [
        {"go": "http://purl.obolibrary.org/obo/GO_0005634", "label": "nucleus",
         "aspect": "http://purl.obolibrary.org/obo/GO_0005575"}
    ]
    body = make_select_json(["go", "label", "aspect"], rows_)
    routes = [
        ("up:obsolete ?obsolete", make_select_json(["obsolete"], [{"obsolete": False}])),
        ("up:classifiedWith", body),
    ]
    svc = service_factory(routes)
    res = await svc.get_go_terms("P05067")
    assert res["count"] == 4
    assert res["count_by_aspect"]["biological_process"] == 3
    bp_only = await svc.get_go_terms("P05067", aspect="biological_process")
    assert list(bp_only["by_aspect"].keys()) == ["biological_process"]
    assert bp_only["count"] == 3
    limited = await svc.get_go_terms("P05067", limit=2)
    assert limited["count"] == 2 and limited["truncated"]["total"] == 4
```

- [ ] **Step 2: Run, expect fail** (`get_go_terms` takes only `accession`).

- [ ] **Step 3: Add a grouped-projection helper** to `shaping.py`

```python
def project_go_terms(
    grouped: dict[str, list[dict[str, Any]]],
    *,
    aspect: str | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    """Filter by aspect and cap total terms; always report counts (F-VERB)."""
    if aspect:
        grouped = {k: v for k, v in grouped.items() if k == aspect}
    count_by_aspect = {k: len(v) for k, v in grouped.items()}
    total = sum(count_by_aspect.values())
    out: dict[str, Any] = {}
    if limit and total > limit:
        remaining = limit
        capped: dict[str, list[dict[str, Any]]] = {}
        for k, terms in grouped.items():
            if remaining <= 0:
                break
            capped[k] = terms[:remaining]
            remaining -= len(capped[k])
        grouped = capped
        out["truncated"] = {"returned": limit, "total": total,
                            "recovery": "raise `limit` or filter by `aspect`."}
    returned = sum(len(v) for v in grouped.values())
    out["count"] = returned if limit else total
    out["count_by_aspect"] = count_by_aspect
    out["by_aspect"] = grouped
    return out
```

- [ ] **Step 4: Rewrite `get_go_terms`** in `sparql_service.py`

```python
    async def get_go_terms(
        self, accession: str, aspect: str | None = None, limit: int = 0
    ) -> dict[str, Any]:
        """Return GO annotations grouped by aspect (aspect/limit, token-lean)."""
        query = Q.protein_go_terms(accession)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        grouped = S.shape_go_terms(data_json)
        projected = S.project_go_terms(grouped, aspect=aspect, limit=max(0, int(limit)))
        acc = Q.validate_accession(accession).split("-")[0]
        return {"accession": acc, **projected, **qmeta}
```

- [ ] **Step 5: Tool params + schema.** In `tools/proteins.py` `get_protein_go_terms`,
  add params:

```python
    async def get_protein_go_terms(
        accession: _ACC,
        aspect: Annotated[
            Literal["biological_process", "molecular_function", "cellular_component"] | None,
            Field(description="Restrict to one GO aspect (omit for all)."),
        ] = None,
        limit: Annotated[int, Field(description="Max terms to return (0 = all).", ge=0, le=500)] = 0,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = await get_sparql_service().get_go_terms(accession, aspect, limit)
            ...
```

  In `schemas.py`: `GO_TERMS_SCHEMA = _envelope(accession=_STR, count=_INT, by_aspect=_OBJ, count_by_aspect=_OBJ, truncated=_OBJ)`.

- [ ] **Step 6: Run → PASS** (`uv run pytest tests/unit -q`).

- [ ] **Step 7: Commit**

```bash
git add uniprot_link/services/shaping.py uniprot_link/services/sparql_service.py uniprot_link/mcp/schemas.py uniprot_link/mcp/tools/proteins.py tests/unit/test_service_and_tools.py
git commit -m "feat(go): aspect filter + limit + count_by_aspect (F-VERB)"
```

---

## Task 11: F-VERB — features limit

**Files:**
- Modify: `uniprot_link/services/queries/proteins.py` (`protein_features` LIMIT param)
- Modify: `uniprot_link/services/sparql_service.py` (`get_features`)
- Modify: `uniprot_link/mcp/schemas.py`, `uniprot_link/mcp/tools/proteins.py`
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_features_limit_truncates(service_factory: Any) -> None:
    feats = make_select_json(
        ["type", "begin", "end", "comment"],
        [{"type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
          "begin": i, "end": i + 1, "comment": "d"} for i in range(5)],
    )
    routes = [
        ("up:obsolete ?obsolete", make_select_json(["obsolete"], [{"obsolete": False}])),
        ("up:range", feats),
    ]
    svc = service_factory(routes)
    res = await svc.get_features("P05067", limit=3)
    assert res["count"] == 3
    assert res["truncated"]["total"] >= 3
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Parametrize `protein_features` LIMIT** in `queries/proteins.py`
  (integer-only change — no join-shape change):

```python
def protein_features(
    accession: str, feature_types: list[str] | None = None, limit: int = 1000
) -> str:
    ...
    # at the end:
    ...
ORDER BY ?begin
LIMIT {limit}"""
```

  Clamp via the caller; default stays 1000.

- [ ] **Step 4: Add `limit` to `get_features`** in `sparql_service.py`

```python
    async def get_features(
        self, accession: str, feature_types: list[str] | None = None, limit: int = 200
    ) -> dict[str, Any]:
        """Return sequence features with coordinates (token-lean via limit)."""
        limit = Q.clamp_limit(limit, default=200, maximum=1000)
        query = Q.protein_features(accession, feature_types, limit=limit)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        features = S.shape_features(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        payload: dict[str, Any] = {
            "accession": acc, "count": len(features), "features": features, **qmeta,
        }
        if len(features) >= limit:
            payload["truncated"] = {
                "reason": f"limit {limit} reached", "total": len(features),
                "recovery": "raise `limit` or pass feature_types to narrow.",
            }
        # ... (existing filter_hint + domain_region_hint blocks unchanged) ...
        return payload
```

  Keep the existing `filter_hint` and `domain_region_hint` blocks between the
  `payload` creation and `return`.

- [ ] **Step 5: Tool param + schema.** In `tools/proteins.py` `get_protein_features`
  add `limit: Annotated[int, Field(description="Max features (default 200).", ge=1, le=1000)] = 200`
  and pass it through. In `schemas.py`: add `truncated=_OBJ` to `FEATURES_SCHEMA`.

- [ ] **Step 6: Run → PASS.** Existing `test_get_features_zero_match_echoes_accepted_keys`
  and `test_features_domain_without_region_hints` still pass (they don't hit the cap).

- [ ] **Step 7: Commit**

```bash
git add uniprot_link/services/queries/proteins.py uniprot_link/services/sparql_service.py uniprot_link/mcp/schemas.py uniprot_link/mcp/tools/proteins.py tests/unit/test_service_and_tools.py
git commit -m "feat(features): limit + truncated hint (F-VERB)"
```

---

## Task 12: Nits — pydantic→envelope + doc fix

**Files:**
- Modify: `uniprot_link/mcp/tools/proteins.py` (`_ACC`, `get_protein` description)
- Test: `tests/unit/test_service_and_tools.py`

- [ ] **Step 1: Failing test** (end-to-end through the facade)

```python
@pytest.mark.asyncio
async def test_short_accession_returns_invalid_input_envelope(service_factory: Any) -> None:
    from uniprot_link.mcp.facade import create_uniprot_mcp

    svc = service_factory([])
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool("get_protein", {"accession": "ABC"})
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is False
        assert payload["error_code"] == "invalid_input"
        assert payload["field"] == "accession"
    finally:
        service_adapters.set_sparql_service(None)
```

- [ ] **Step 2: Run, expect fail** (raw pydantic ValidationError today — min_length=6).

- [ ] **Step 3: Drop `min_length`** from `_ACC` in `tools/proteins.py`

```python
_ACC = Annotated[
    str,
    Field(description="UniProtKB accession, e.g. P05067 (isoforms like P05067-2 accepted)."),
]
```

  Now `validate_accession("ABC")` raises `InvalidInputError(field="accession")`
  inside the body → the polished envelope.

- [ ] **Step 4: Doc fix** — in the `get_protein` tool description replace
  "response_mode (default compact) controls verbosity; full restores raw IRIs."
  with "response_mode (default compact) controls verbosity; standard/full add
  created/modified dates."

- [ ] **Step 5: Run → PASS.** Confirm the obsolete/isoform get_protein tests (Task 4)
  still pass through the facade.

- [ ] **Step 6: Commit**

```bash
git add uniprot_link/mcp/tools/proteins.py tests/unit/test_service_and_tools.py
git commit -m "fix(errors): route short-accession failures through the envelope; doc fix (nits)"
```

---

## Task 13: Capabilities + version bump + schema finalization

**Files:**
- Modify: `uniprot_link/mcp/capabilities.py`
- Modify: `uniprot_link/mcp/schemas.py` (`PROTEIN_SCHEMA`)
- Modify: `uniprot_link/__init__.py`
- Test: `tests/unit/test_capabilities.py`

- [ ] **Step 1: Failing test** (append to `tests/unit/test_capabilities.py`)

```python
def test_capabilities_documents_obsolete_and_map_dbs() -> None:
    from uniprot_link.mcp.capabilities import build_capabilities

    cap = build_capabilities()
    assert cap["server_version"] == "0.6.0"
    assert "obsolete" in cap["not_found_contract"].lower()
    assert "PDB" in cap["map_identifier_databases"]
    assert "DrugBank" not in cap["map_identifier_databases"]
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Version bump** — `uniprot_link/__init__.py`: `__version__ = "0.6.0"`.

- [ ] **Step 4: Capabilities edits** — in `build_capabilities()`:
  - extend `not_found_contract` with the obsolete clause (get_protein → flagged
    record; data tools → obsolete-flagged not_found with `replaced_by`).
  - add `"map_identifier_databases": MAP_IDENTIFIER_DATABASES` (import it).
  - add a `result_ordering["cross_references"]` note (sorted ids + db keys; compact
    caps each db at 25 with truncated_databases).
  - add an `obsolete_handling` short note.

- [ ] **Step 5: Extend `PROTEIN_SCHEMA`** in `schemas.py`:

```python
PROTEIN_SCHEMA = _envelope(
    accession=_STR, requested_accession=_STR, mnemonic=_STR, reviewed=_BOOL,
    recommended_name=_STR, genes=_ARR, organism=_STR, taxon_id=_STR,
    sequence_length=_INT, mass_da=_INT,
    obsolete=_BOOL, replaced_by=_ARR,
    has_variants=_BOOL, has_diseases=_BOOL, has_structure=_BOOL, isoform=_STR,
)
```

- [ ] **Step 6: Run → PASS** (`uv run pytest tests/unit/test_capabilities.py -q`).
  Check `test_buildinfo.py` doesn't pin a version string (grep `0.5.0` in tests).

- [ ] **Step 7: Commit**

```bash
git add uniprot_link/mcp/capabilities.py uniprot_link/mcp/schemas.py uniprot_link/__init__.py tests/unit/test_capabilities.py
git commit -m "feat(caps): document obsolete handling + map-id dbs; bump 0.6.0"
```

---

## Task 14: Live re-validation + ci-local + integration regression

**Files:**
- Modify: `research/verify_queries.py`
- Modify: `tests/integration/test_live.py`

- [ ] **Step 1: Add live cases** to `research/verify_queries.py` `CASES`:

```python
    "entry_status(P05067 active)": q.entry_status("P05067"),
    "entry_status(Z9Z9Z9 obsolete)": q.entry_status("Z9Z9Z9"),
    "entry_status(A0A009K1D9 demerged)": q.entry_status("A0A009K1D9"),
    "entry_status(Q9ZZZ9 absent)": q.entry_status("Q9ZZZ9"),
    "entry_status(P05067-2 isoform)": q.entry_status("P05067-2"),
    "protein_summary(P05067 +flags)": q.protein_summary("P05067"),
    "protein_features(P05067, limit=5)": q.protein_features("P05067", limit=5),
```

- [ ] **Step 2: Run live verification** (per CLAUDE.md — query builders changed):

```bash
uv run python research/verify_queries.py
```

  Expected: entry_status P05067 → 1 row obsolete unbound; Z9Z9Z9/A0A009K1D9 →
  obsolete true (A0A009K1D9 with replacedBy); Q9ZZZ9 → 0 rows; P05067-2 →
  isoform_exists true; summary returns has_variants/has_diseases/has_structure;
  features returns ≤5 rows. All bound queries return < ~2 s.

- [ ] **Step 3: Add an integration regression** to `tests/integration/test_live.py`
  (guarded `@pytest.mark.integration`):

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_obsolete_entry_is_flagged_live(live_service) -> None:
    out = await live_service.get_protein("Z9Z9Z9")
    assert out["obsolete"] is True
    with pytest.raises(Exception):  # ObsoleteEntryError (NotFoundError subclass)
        await live_service.get_sequence("Z9Z9Z9")
```

  (Reuse whatever `live_service` fixture pattern the file already uses; if none,
  build a real `SparqlService` like `research/self_test_pnkp.py` does.)

- [ ] **Step 4: Full gate**

```bash
make ci-local
```

  Expected: format clean, ruff clean, `lint-loc` under 600/module, mypy strict
  clean, all unit tests green. Fix any line-cap overflow by moving projection
  helpers fully into `shaping.py` (it has the most headroom).

- [ ] **Step 5: Commit**

```bash
git add research/verify_queries.py tests/integration/test_live.py
git commit -m "test(obsolete): live entry_status/summary re-validation + integration regression"
```

---

## Self-review notes (gaps to watch during execution)

- **Line cap:** `sparql_service.py` starts at 496/600. After Tasks 3,4,9,10,11 it
  must stay < 600 — keep projection logic in `shaping.py` (Tasks 9,10) and the
  obsolete-record builder in `shaping.py` (Task 4). Run `make lint-loc` before the
  final commit; if over, move more into `shaping.py`.
- **Route-needle collisions in `FakeSparqlClient`:** the gate query contains
  `up:obsolete ?obsolete`; the summary contains `up:recommendedName`; the data
  queries contain their distinctive class names — choose needles that don't
  collide (the plan's test routes already do).
- **`_MODE_DROP`** must not list any new key (presence flags / echoes survive every
  response_mode).
- **`entry_status` export:** ensure `queries/__init__.py` and any `Q.`-prefixed
  reference no longer name `entry_exists_ask` (grep for it before the final gate).
- **mypy strict:** `EntryStatus` is a frozen dataclass; `project_*` helpers return
  `dict[str, Any]`; annotate accordingly.
