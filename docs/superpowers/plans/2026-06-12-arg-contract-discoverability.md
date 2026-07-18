# Argument Contract & Discoverability Uplift — Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape FastMCP argument-binding validation errors into the product's
own error envelope, accept curated argument aliases, embed canonical signatures
in tool descriptions, and add a lightweight discovery surface — lifting the
v0.5.0 cold-consumer assessment from 7.5/10 to >9.5/10.

**Architecture:** A single `on_call_tool` FastMCP middleware intercepts the
`pydantic.ValidationError` that fires in `FunctionTool.run()` (before the tool
body) and returns a normal `ToolResult` carrying the standard envelope. Pure
helper functions (`arg_help.py`) own aliases, did-you-mean, and signature
rendering. Tool descriptions and a new `uniprot://tools` resource expose param
names without a heavy capabilities read.

**Tech Stack:** Python 3.12, FastMCP 3.4.2, pydantic v2, pytest + respx, uv, Ruff,
mypy (strict).

**Spec:** [`docs/superpowers/specs/2026-06-12-arg-contract-discoverability-design.md`](../specs/2026-06-12-arg-contract-discoverability-design.md)

**Verified facts (do not re-derive):**
- Wrong keyword → `ValidationError`, `errors()[0]={type:'unexpected_keyword_argument', loc:('taxon',)}`; propagates **unmasked** up to `on_call_tool`.
- Wrong type → `type:'int_parsing'`; missing required → `type:'missing_argument'`. Same path.
- Inside middleware: valid params = `(await context.fastmcp_context.fastmcp.get_tool(name)).parameters["properties"].keys()`.
- All-tools listing: `await mcp.list_tools()` → `list[Tool]` with `.name`, `.parameters`, `.description`.
- `ToolResult(structured_content=env, content=[TextContent(type="text", text=json.dumps(env))])` is the return shape.
- `context.message` is `CallToolRequestParams` with mutable `.arguments: dict`.
- Live signatures (current): `find_proteins(gene=, organism_taxon=, reviewed=, keyword=, ec_number=, mnemonic=, name_contains=, limit=, offset=)`, `get_protein(accession, response_mode=)`, etc. (see Task 5).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `uniprot_link/mcp/arg_help.py` | Aliases, alias-normalization, did-you-mean, signature rendering (pure) | Create |
| `uniprot_link/mcp/middleware.py` | `ArgValidationMiddleware` (`on_call_tool`) | Create |
| `uniprot_link/mcp/envelope.py` | Add `build_arg_error_envelope()` | Modify |
| `uniprot_link/mcp/facade.py` | Register middleware | Modify |
| `uniprot_link/mcp/tools/*.py` | Append `Signature:` line to descriptions; F4 nudge | Modify |
| `uniprot_link/mcp/capabilities.py` | `detail` projection + `tool_signatures` + `argument_aliases` | Modify |
| `uniprot_link/mcp/resources.py` | (constant text only, if needed) | Maybe |
| `uniprot_link/mcp/tools/discovery.py` | `detail` param + `uniprot://tools`-style signatures | Modify |
| `uniprot_link/__init__.py`, `pyproject.toml`, `uv.lock` | Version 0.6.0 → 0.7.0 | Modify |
| `tests/unit/test_arg_help.py` | Unit tests for helpers | Create |
| `tests/unit/test_arg_middleware.py` | End-to-end middleware tests via facade | Create |
| `tests/unit/test_discovery_surface.py` | tools resource + capabilities detail | Create |
| `tests/unit/test_capabilities.py`, `test_service_and_tools.py` | Version assertion updates | Modify |
| `tests/integration/test_live.py` | PNKP one-call cold path | Modify |
| `docs/mcp-assessment-v0.5.0-consumer-session.md` (closure) | Findings→fixes→evidence record | Create/Modify |

---

## Task 1: Pure argument-help functions

**Files:**
- Create: `uniprot_link/mcp/arg_help.py`
- Test: `tests/unit/test_arg_help.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_arg_help.py
"""Unit tests for argument-help pure functions."""

from __future__ import annotations

from uniprot_link.mcp.arg_help import (
    did_you_mean,
    normalize_alias_args,
    tool_signature,
)


def test_normalize_applies_alias_when_canonical_valid_and_absent() -> None:
    valid = ["gene", "organism_taxon", "reviewed"]
    args, applied = normalize_alias_args(valid, {"taxon": "9606", "gene": "PNKP"})
    assert args == {"organism_taxon": "9606", "gene": "PNKP"}
    assert applied == [("taxon", "organism_taxon")]


def test_normalize_does_not_overwrite_explicit_canonical() -> None:
    valid = ["organism_taxon"]
    args, applied = normalize_alias_args(valid, {"taxon": "1", "organism_taxon": "9606"})
    assert args == {"organism_taxon": "9606"}  # explicit value wins; alias dropped
    assert applied == []


def test_normalize_ignores_alias_when_canonical_not_a_param() -> None:
    valid = ["gene"]  # organism_taxon is not a param of this tool
    args, applied = normalize_alias_args(valid, {"taxon": "9606"})
    assert args == {"taxon": "9606"}  # untouched -> will become a clean did-you-mean
    assert applied == []


def test_did_you_mean_prefers_alias_map() -> None:
    assert did_you_mean("organism", ["gene", "organism_taxon"]) == "organism_taxon"


def test_did_you_mean_falls_back_to_fuzzy() -> None:
    assert did_you_mean("organism_taxa", ["gene", "organism_taxon"]) == "organism_taxon"


def test_did_you_mean_returns_none_when_no_match() -> None:
    assert did_you_mean("zzz", ["gene", "organism_taxon"]) is None


def test_tool_signature_required_first_then_optional() -> None:
    schema = {
        "properties": {"accession": {}, "response_mode": {}},
        "required": ["accession"],
    }
    assert tool_signature("get_protein", schema) == "get_protein(accession, response_mode=)"


def test_tool_signature_all_optional() -> None:
    schema = {"properties": {"gene": {}, "organism_taxon": {}}}
    assert tool_signature("find_proteins", schema) == "find_proteins(gene=, organism_taxon=)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_arg_help.py -q`
Expected: FAIL — `ModuleNotFoundError: uniprot_link.mcp.arg_help`

- [ ] **Step 3: Write the implementation**

```python
# uniprot_link/mcp/arg_help.py
"""Argument ergonomics for MCP tools: aliases, did-you-mean, signatures.

Pure functions with no FastMCP dependency so they unit-test in isolation. The
:mod:`middleware` module and the discovery surface both consume them, keeping a
single source of truth for what a "valid argument" looks like.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from typing import Any

# Curated synonym -> canonical map, scoped to this server's small parameter space.
# An alias only ever resolves to a canonical name that is a *real* parameter of the
# tool being called (see ``normalize_alias_args``), so a shared map is safe.
ARG_ALIASES: dict[str, str] = {
    # organism_taxon: the assessment's headline miss (taxon / organism / organism_id)
    "taxon": "organism_taxon",
    "taxon_id": "organism_taxon",
    "taxid": "organism_taxon",
    "tax_id": "organism_taxon",
    "organism": "organism_taxon",
    "organism_id": "organism_taxon",
    "ncbi_taxon": "organism_taxon",
    "species": "organism_taxon",
    # gene
    "gene_symbol": "gene",
    "gene_name": "gene",
    "symbol": "gene",
    # accession
    "acc": "accession",
    "uniprot": "accession",
    "uniprot_id": "accession",
    "uniprot_accession": "accession",
    "id": "accession",
    # ec / keyword / query text
    "ec": "ec_number",
    "ec_no": "ec_number",
    "kw": "keyword",
    "query_string": "query",
    "sparql": "query",
}


def normalize_alias_args(
    valid_params: Iterable[str], arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Rewrite known alias keys to their canonical parameter names.

    An alias is applied only when (a) the alias key is present, (b) the canonical
    target is a real parameter of the called tool, and (c) the canonical key is not
    already supplied explicitly. Returns ``(new_arguments, applied_pairs)`` where
    ``applied_pairs`` is a list of ``(alias, canonical)`` for transparency.
    """
    valid = set(valid_params)
    result = dict(arguments)
    applied: list[tuple[str, str]] = []
    for alias, canonical in ARG_ALIASES.items():
        if alias in result and canonical in valid:
            if canonical in result:
                # Explicit canonical value wins; drop the redundant alias quietly.
                result.pop(alias)
            else:
                result[canonical] = result.pop(alias)
                applied.append((alias, canonical))
    return result, applied


def did_you_mean(unknown: str, valid: Iterable[str]) -> str | None:
    """Best canonical suggestion for an unknown argument name, or ``None``.

    The alias map is authoritative; otherwise fall back to close string matches.
    """
    valid_list = list(valid)
    aliased = ARG_ALIASES.get(unknown)
    if aliased is not None and aliased in valid_list:
        return aliased
    matches = difflib.get_close_matches(unknown, valid_list, n=1, cutoff=0.6)
    return matches[0] if matches else None


def tool_signature(name: str, schema: Mapping[str, Any]) -> str:
    """Render ``name(req, opt=, ...)`` from a JSON input schema.

    Required parameters are listed first (bare); optional parameters follow with a
    trailing ``=`` to signal they take a value but may be omitted.
    """
    props = list(schema.get("properties", {}).keys())
    required = set(schema.get("required") or [])
    parts = [p for p in props if p in required]
    parts += [f"{p}=" for p in props if p not in required]
    return f"{name}(" + ", ".join(parts) + ")"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_arg_help.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add uniprot_link/mcp/arg_help.py tests/unit/test_arg_help.py
git commit -m "feat(args): pure alias/did-you-mean/signature helpers"
```

---

## Task 2: `build_arg_error_envelope` in envelope.py

**Files:**
- Modify: `uniprot_link/mcp/envelope.py`
- Test: `tests/unit/test_arg_help.py` (append) — pure-dict assertions

- [ ] **Step 1: Write the failing test (append to tests/unit/test_arg_help.py)**

```python
def test_build_arg_error_envelope_unexpected_keyword() -> None:
    from uniprot_link.mcp.envelope import build_arg_error_envelope

    env = build_arg_error_envelope(
        tool_name="find_proteins",
        loc="species",
        error_type="unexpected_keyword_argument",
        valid_params=["gene", "organism_taxon"],
        signature="find_proteins(gene=, organism_taxon=)",
        suggestion="organism_taxon",
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["recovery_action"] == "reformulate_input"
    assert env["retryable"] is False
    assert env["field"] == "species"
    assert env["allowed_values"] == ["gene", "organism_taxon"]
    assert env["hint"] == "find_proteins(gene=, organism_taxon=)"
    assert "organism_taxon" in env["message"]  # did-you-mean surfaced
    assert env["_meta"]["tool"] == "find_proteins"
    assert env["_meta"]["request_id"]
    assert env["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"


def test_build_arg_error_envelope_missing_argument_wording() -> None:
    from uniprot_link.mcp.envelope import build_arg_error_envelope

    env = build_arg_error_envelope(
        tool_name="get_protein",
        loc="accession",
        error_type="missing_argument",
        valid_params=["accession", "response_mode"],
        signature="get_protein(accession, response_mode=)",
        suggestion=None,
    )
    assert "missing" in env["message"].lower()
    assert env["field"] == "accession"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_arg_help.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_arg_error_envelope'`

- [ ] **Step 3: Add the helper to `uniprot_link/mcp/envelope.py`**

Add after the existing `_error_envelope` function (reuse `_request_id`, `_recovery_action`, and `cmd`):

```python
def build_arg_error_envelope(
    *,
    tool_name: str,
    loc: str,
    error_type: str,
    valid_params: list[str],
    signature: str,
    suggestion: str | None,
) -> dict[str, Any]:
    """Standard invalid-input envelope for an argument-binding failure.

    Used by :class:`~uniprot_link.mcp.middleware.ArgValidationMiddleware` so a wrong
    argument *name*, *type*, or a *missing required* argument routes through the same
    contract as value-level errors instead of leaking a raw pydantic ``ValidationError``.
    """
    if error_type == "missing_argument":
        head = f"Missing required argument `{loc}` for {tool_name}."
    elif error_type == "unexpected_keyword_argument":
        head = f"Unknown argument `{loc}` for {tool_name}."
    else:
        head = f"Invalid value for argument `{loc}` of {tool_name}."
    dym = f" Did you mean `{suggestion}`?" if suggestion else ""
    message = f"{head}{dym} Valid argument names are listed in allowed_values."
    next_commands: list[dict[str, Any]] = [cmd("get_server_capabilities")]
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": "invalid_input",
        "message": message[:280],
        "retryable": False,
        "recovery_action": "reformulate_input",
        "field": loc,
        "allowed_values": valid_params,
        "hint": signature,
        "_meta": {
            "tool": tool_name,
            "request_id": _request_id(),
            "next_commands": next_commands,
        },
    }
    return envelope
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_arg_help.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add uniprot_link/mcp/envelope.py tests/unit/test_arg_help.py
git commit -m "feat(errors): build_arg_error_envelope for binding failures"
```

---

## Task 3: `ArgValidationMiddleware`

**Files:**
- Create: `uniprot_link/mcp/middleware.py`
- Test: `tests/unit/test_arg_middleware.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_arg_middleware.py
"""End-to-end tests for ArgValidationMiddleware via the real facade.

These calls fail at argument binding *before* any tool body runs, so no network
call happens and no respx mocking is needed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from uniprot_link.mcp.facade import create_uniprot_mcp


def _structured(result: Any) -> dict[str, Any]:
    sc = result.structured_content
    return sc if isinstance(sc, dict) else json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_wrong_keyword_routes_through_envelope() -> None:
    mcp = create_uniprot_mcp()
    result = await mcp.call_tool("find_proteins", {"species": "9606"})
    env = _structured(result)
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "species"
    assert "organism_taxon" in env["allowed_values"]
    assert env["hint"].startswith("find_proteins(")
    assert env["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"
    # never leak the pydantic docs URL
    assert "pydantic.dev" not in json.dumps(env)


@pytest.mark.asyncio
async def test_non_alias_near_miss_gets_did_you_mean() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("find_proteins", {"organism_taxa": "9606"}))
    assert "organism_taxon" in env["message"]


@pytest.mark.asyncio
async def test_wrong_type_routes_through_envelope() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("find_proteins", {"organism_taxon": "notanint"}))
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "organism_taxon"


@pytest.mark.asyncio
async def test_missing_required_routes_through_envelope() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_protein", {}))
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "accession"
    assert "missing" in env["message"].lower()


@pytest.mark.asyncio
async def test_alias_normalized_and_disclosed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """taxon -> organism_taxon succeeds and is disclosed in _meta."""
    import uniprot_link.mcp.service_adapters as sa

    class _Svc:
        async def find_proteins(self, **kw: Any) -> dict[str, Any]:
            assert kw["organism_taxon"] == 9606  # alias landed on the right param
            return {"count": 0, "proteins": []}

    monkeypatch.setattr(sa, "get_sparql_service", lambda: _Svc())
    mcp = create_uniprot_mcp()
    result = await mcp.call_tool("find_proteins", {"gene": "PNKP", "taxon": "9606"})
    env = _structured(result)
    assert env["success"] is True
    assert env["_meta"]["argument_aliases_applied"] == [["taxon", "organism_taxon"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_arg_middleware.py -q`
Expected: FAIL — wrong-keyword/type/missing tests raise raw `ValidationError`
(middleware not yet registered); alias test fails on missing `_meta` key.

- [ ] **Step 3: Write `uniprot_link/mcp/middleware.py`**

```python
# uniprot_link/mcp/middleware.py
"""FastMCP middleware that wraps argument-binding failures in the error envelope.

FastMCP validates call arguments with pydantic inside ``FunctionTool.run()`` —
before the registered tool body executes — so a wrong argument *name*/*type* or a
*missing required* argument raises a ``pydantic.ValidationError`` that never reaches
``run_mcp_tool``'s error boundary. This middleware catches that error at the
``on_call_tool`` hook and returns a normal ``ToolResult`` carrying the standard
``invalid_input`` envelope (with valid names + a did-you-mean), so every failure
mode speaks the product's own contract.

It also normalizes a curated set of argument aliases (e.g. ``taxon`` ->
``organism_taxon``) before dispatch, eliminating the most common cold-start round
trips, and discloses any rewrite under ``_meta.argument_aliases_applied``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.types import TextContent
from pydantic import ValidationError

from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

from uniprot_link.mcp.arg_help import did_you_mean, normalize_alias_args, tool_signature
from uniprot_link.mcp.envelope import build_arg_error_envelope

logger = logging.getLogger(__name__)


class ArgValidationMiddleware(Middleware):
    """Reshape argument-binding errors and apply argument aliases."""

    def __init__(self) -> None:
        """Initialise the per-tool parameter-schema cache."""
        self._schema_cache: dict[str, dict[str, Any]] = {}

    async def _schema(self, context: MiddlewareContext, name: str) -> dict[str, Any]:
        if name not in self._schema_cache:
            server = context.fastmcp_context.fastmcp
            tool = await server.get_tool(name)
            self._schema_cache[name] = dict(tool.parameters or {})
        return self._schema_cache[name]

    async def on_call_tool(self, context: MiddlewareContext, call_next: Any) -> ToolResult:
        """Normalize aliases, then convert binding errors into the envelope."""
        name = context.message.name
        try:
            schema = await self._schema(context, name)
        except Exception:  # registry miss: let core handle it untouched
            return await call_next(context)

        valid = list(schema.get("properties", {}).keys())
        args = context.message.arguments or {}
        new_args, applied = normalize_alias_args(valid, args)
        context.message.arguments = new_args

        try:
            result = await call_next(context)
        except ValidationError as exc:
            return self._error_result(name, valid, schema, exc)

        if applied and isinstance(result, ToolResult) and isinstance(
            result.structured_content, dict
        ):
            meta = result.structured_content.setdefault("_meta", {})
            meta["argument_aliases_applied"] = [list(p) for p in applied]
        return result

    def _error_result(
        self,
        name: str,
        valid: list[str],
        schema: dict[str, Any],
        exc: ValidationError,
    ) -> ToolResult:
        first = exc.errors(include_url=False)[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "input"
        error_type = str(first.get("type", "value_error"))
        suggestion = did_you_mean(loc, valid) if loc not in valid else None
        envelope = build_arg_error_envelope(
            tool_name=name,
            loc=loc,
            error_type=error_type,
            valid_params=valid,
            signature=tool_signature(name, schema),
            suggestion=suggestion,
        )
        logger.warning("mcp_arg_error tool=%s loc=%s type=%s", name, loc, error_type)
        return ToolResult(
            structured_content=envelope,
            content=[TextContent(type="text", text=json.dumps(envelope))],
        )
```

- [ ] **Step 4: Register the middleware — edit `uniprot_link/mcp/facade.py`**

Add the import and the registration call (after the existing `register_*` calls,
before `return mcp`):

```python
from uniprot_link.mcp.middleware import ArgValidationMiddleware
```

```python
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    return mcp
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_arg_middleware.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Run the full unit suite — confirm no regressions**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS (existing value-level error and happy-path tests unaffected).

- [ ] **Step 7: Commit**

```bash
git add uniprot_link/mcp/middleware.py uniprot_link/mcp/facade.py tests/unit/test_arg_middleware.py
git commit -m "feat(mcp): ArgValidationMiddleware reshapes binding errors + aliases (F1/F2)"
```

---

## Task 4: Canonical signatures in tool descriptions (F1) + accession-first nudge (F4)

**Files:**
- Modify: `uniprot_link/mcp/tools/proteins.py`, `query.py`, `taxonomy.py`, `discovery.py`
- Test: `tests/unit/test_discovery_surface.py` (drift guard — created in Task 5)

For each tool, append a `Signature:` sentence to the END of the existing
`description=` string. Use these EXACT signatures (verified against the live
schema; `get_server_capabilities` gains `detail=` in Task 5):

```
find_proteins:               Signature: find_proteins(gene=, organism_taxon=, reviewed=, keyword=, ec_number=, mnemonic=, name_contains=, limit=, offset=).
get_protein:                 Signature: get_protein(accession, response_mode=).
get_protein_sequence:        Signature: get_protein_sequence(accession, response_mode=).
get_protein_features:        Signature: get_protein_features(accession, feature_types=, limit=).
get_protein_variants:        Signature: get_protein_variants(accession, limit=, disease_associated_only=).
get_protein_diseases:        Signature: get_protein_diseases(accession).
get_protein_cross_references:Signature: get_protein_cross_references(accession, databases=, response_mode=).
get_protein_go_terms:        Signature: get_protein_go_terms(accession, aspect=, limit=).
map_identifiers:             Signature: map_identifiers(accession, databases=, response_mode=).
get_taxon:                   Signature: get_taxon(taxon, include_lineage=).
run_sparql_query:            Signature: run_sparql_query(query, result_format=, limit=, timeout_seconds=).
search_example_queries:      Signature: search_example_queries(text=, limit=).
get_example_query:           Signature: get_example_query(example_id).
```

- [ ] **Step 1: Edit `find_proteins` description in `proteins.py`**

In the `find_proteins` `description=(...)`, after the final
`"... repeat is cached (~0 ms)."` change the closing of that string to add the
accession-first nudge (F4) and the signature line:

```python
            "across pages). Cold search can take several seconds; an identical "
            "repeat is cached (~0 ms). If you already know the accession, call "
            "get_protein directly -- it is far faster than a cold search. "
            "Signature: find_proteins(gene=, organism_taxon=, reviewed=, keyword=, "
            "ec_number=, mnemonic=, name_contains=, limit=, offset=)."
```

- [ ] **Step 2: Append the signature sentence to the other protein tools in `proteins.py`**

`get_protein`: append to the description string:
```python
            " Signature: get_protein(accession, response_mode=)."
```
`get_protein_sequence`: ` " Signature: get_protein_sequence(accession, response_mode=)."`
`get_protein_features`: ` " Signature: get_protein_features(accession, feature_types=, limit=)."`
`get_protein_variants`: ` " Signature: get_protein_variants(accession, limit=, disease_associated_only=)."`
`get_protein_diseases`: ` " Signature: get_protein_diseases(accession)."`
`get_protein_cross_references`: ` " Signature: get_protein_cross_references(accession, databases=, response_mode=)."`
`get_protein_go_terms`: ` " Signature: get_protein_go_terms(accession, aspect=, limit=)."`
`map_identifiers`: ` " Signature: map_identifiers(accession, databases=, response_mode=)."`

- [ ] **Step 3: Append signature sentences in `query.py` and `taxonomy.py`**

`run_sparql_query`: ` " Signature: run_sparql_query(query, result_format=, limit=, timeout_seconds=)."`
`search_example_queries`: ` " Signature: search_example_queries(text=, limit=)."`
`get_example_query`: ` " Signature: get_example_query(example_id)."`
`get_taxon`: ` " Signature: get_taxon(taxon, include_lineage=)."`

- [ ] **Step 4: Verify descriptions render and tools still load**

Run:
```bash
.venv/bin/python -c "import asyncio; from uniprot_link.mcp.facade import create_uniprot_mcp; \
m=create_uniprot_mcp(); ts=asyncio.run(m.list_tools()); \
fp=[t for t in ts if t.name=='find_proteins'][0]; \
assert 'Signature: find_proteins(gene=, organism_taxon=' in fp.description; \
print('OK: signature in find_proteins description')"
```
Expected: `OK: signature in find_proteins description`

- [ ] **Step 5: Commit**

```bash
git add uniprot_link/mcp/tools/proteins.py uniprot_link/mcp/tools/query.py uniprot_link/mcp/tools/taxonomy.py
git commit -m "feat(tools): canonical signatures in descriptions + accession-first nudge (F1/F4)"
```

---

## Task 5: Lighter discovery surface — `uniprot://tools` + `detail` mode (F3)

**Files:**
- Modify: `uniprot_link/mcp/tools/discovery.py` (add `detail` param)
- Modify: `uniprot_link/mcp/capabilities.py` (summary projection + signatures generator + register `uniprot://tools`)
- Test: `tests/unit/test_discovery_surface.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_discovery_surface.py
"""Discovery-surface tests: tools resource, capabilities detail, signature drift."""

from __future__ import annotations

import json
from typing import Any

import pytest

from uniprot_link.mcp.arg_help import tool_signature
from uniprot_link.mcp.facade import create_uniprot_mcp


def _structured(result: Any) -> dict[str, Any]:
    sc = result.structured_content
    return sc if isinstance(sc, dict) else json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_capabilities_summary_is_default_and_light() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_server_capabilities", {}))
    assert env["detail"] == "summary"
    assert "tool_signatures" in env
    assert env["tool_signatures"]["find_proteins"].startswith("find_proteins(")
    # heavy reference blocks are NOT in the summary
    assert "named_graphs" not in env
    assert "prefixes" not in env


@pytest.mark.asyncio
async def test_capabilities_full_restores_heavy_blocks() -> None:
    mcp = create_uniprot_mcp()
    env = _structured(await mcp.call_tool("get_server_capabilities", {"detail": "full"}))
    assert env["detail"] == "full"
    assert env["named_graph_count"] == 21
    assert env["prefixes"]["up"] == "http://purl.uniprot.org/core/"
    assert "tool_signatures" in env


@pytest.mark.asyncio
async def test_tools_resource_lists_all_with_signatures() -> None:
    mcp = create_uniprot_mcp()
    payload = json.loads(await mcp.read_resource("uniprot://tools"))
    names = {t["name"] for t in payload["tools"]}
    assert len(names) == 14
    fp = next(t for t in payload["tools"] if t["name"] == "find_proteins")
    assert fp["signature"].startswith("find_proteins(gene=, organism_taxon=")
    assert fp["summary"]  # one-line summary present


@pytest.mark.asyncio
async def test_signatures_match_live_schema_no_drift() -> None:
    """Drift guard: hardcoded description signatures match generated ones."""
    mcp = create_uniprot_mcp()
    for tool in await mcp.list_tools():
        sig = tool_signature(tool.name, tool.parameters)
        assert sig in (tool.description or ""), f"{tool.name}: '{sig}' not in description"
```

Note: `read_resource` may return a list of contents; if so adapt `_read` to
`(await mcp.read_resource("uniprot://tools"))[0].content`. Confirm the shape in
Step 2 and adjust the helper before implementing.

- [ ] **Step 2: Run tests to verify they fail and confirm read_resource shape**

Run: `.venv/bin/python -m pytest tests/unit/test_discovery_surface.py -q`
Expected: FAIL — `detail` not in payload / `uniprot://tools` unknown.

Confirm the resource-read return shape:
```bash
.venv/bin/python -c "import asyncio; from uniprot_link.mcp.facade import create_uniprot_mcp; \
m=create_uniprot_mcp(); r=asyncio.run(m.read_resource('uniprot://capabilities')); \
print(type(r), r[0] if isinstance(r,list) else str(r)[:60])"
```
Adjust the test's resource-read helper to match (string vs list-of-contents).

- [ ] **Step 3: Add the signatures generator + summary projection to `capabilities.py`**

Add these functions and extend `register_capability_resources`:

```python
async def collect_tool_signatures(mcp: FastMCP) -> dict[str, str]:
    """Map every registered tool to its rendered signature (live schema)."""
    from uniprot_link.mcp.arg_help import tool_signature

    tools = await mcp.list_tools()
    return {t.name: tool_signature(t.name, t.parameters or {}) for t in sorted(tools, key=lambda t: t.name)}


async def build_tools_overview(mcp: FastMCP) -> dict[str, Any]:
    """Lightweight discovery payload: name, one-line summary, signature."""
    from uniprot_link.mcp.arg_help import tool_signature

    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    entries: list[dict[str, str]] = []
    for t in tools:
        summary = (t.description or "").split(". ")[0].strip()
        entries.append(
            {
                "name": t.name,
                "summary": summary[:160],
                "signature": tool_signature(t.name, t.parameters or {}),
            }
        )
    return {"server": "uniprot-link", "tool_count": len(entries), "tools": entries}


_SUMMARY_KEYS = (
    "server",
    "server_version",
    "build",
    "uniprot_release",
    "endpoint",
    "sparql_engine",
    "research_use_only",
    "research_use_notice",
    "recommended_citation",
    "tools",
    "tool_count",
    "response_modes",
    "default_response_mode",
    "recommended_workflows",
    "error_codes",
    "limits",
    "read_only",
)


def project_capabilities(detail: str, tool_signatures: dict[str, str]) -> dict[str, Any]:
    """Return the full payload (detail='full') or a light summary (default)."""
    full = build_capabilities()
    full["tool_signatures"] = tool_signatures
    full["argument_aliases"] = _ALIAS_DOC
    full["detail"] = detail
    if detail == "full":
        return full
    summary = {k: full[k] for k in _SUMMARY_KEYS if k in full}
    summary["tool_signatures"] = tool_signatures
    summary["argument_aliases"] = _ALIAS_DOC
    summary["detail"] = "summary"
    summary["latency_note"] = full["latency_profile"]["note"]
    summary["more"] = "Call get_server_capabilities(detail='full') or read uniprot://capabilities for named graphs, prefixes, and vocabularies."
    return summary
```

Add the alias-doc constant near the top of `capabilities.py` (after imports):

```python
from uniprot_link.mcp.arg_help import ARG_ALIASES

# Reverse the alias map to {canonical: [accepted synonyms]} for human-facing docs.
_ALIAS_DOC: dict[str, list[str]] = {}
for _alias, _canonical in sorted(ARG_ALIASES.items()):
    _ALIAS_DOC.setdefault(_canonical, []).append(_alias)
```

Register the `uniprot://tools` resource inside `register_capability_resources`:

```python
    @mcp.resource("uniprot://tools", mime_type="application/json")
    async def tools_overview() -> str:
        return json.dumps(await build_tools_overview(mcp), indent=2)
```

- [ ] **Step 4: Add the `detail` parameter to `get_server_capabilities` in `discovery.py`**

Replace the tool body so it projects by `detail` and includes signatures:

```python
    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=CAPABILITIES_SCHEMA,
        tags={"discovery"},
        description=(
            "Return the uniprot-link discovery surface. detail='summary' (default) "
            "is light: identity/build/release, the tool list WITH call signatures, "
            "accepted argument aliases, response modes, recommended workflows, error "
            "taxonomy, and limits -- enough to call any tool without guessing an "
            "argument name. detail='full' adds the heavy reference blocks (21 named "
            "graphs with triple counts, the full SPARQL prefix map, full latency "
            "bands, feature-type and cross-reference vocabularies). Call this first "
            "in a cold session, or read uniprot://tools (signatures only) or "
            "uniprot://capabilities (full). "
            "Signature: get_server_capabilities(detail=)."
        ),
    )
    async def get_server_capabilities(
        detail: Annotated[
            Literal["summary", "full"],
            Field(description="summary (default, light) or full (adds named graphs/prefixes)."),
        ] = "summary",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            from uniprot_link.mcp.capabilities import collect_tool_signatures, project_capabilities

            signatures = await collect_tool_signatures(mcp)
            return project_capabilities(detail, signatures)

        return await run_mcp_tool(
            "get_server_capabilities",
            call,
            context=McpErrorContext("get_server_capabilities"),
        )
```

Update `discovery.py` imports to add `Annotated`, `Literal`, and `Field`:

```python
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field
```

- [ ] **Step 5: Run the discovery tests**

Run: `.venv/bin/python -m pytest tests/unit/test_discovery_surface.py -q`
Expected: PASS (4 passed). If the drift guard fails, fix the offending tool's
description signature to match `tool_signature(name, schema)` exactly.

- [ ] **Step 6: Run full unit suite**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS — except the pre-existing version assertions (fixed in Task 6).

- [ ] **Step 7: Commit**

```bash
git add uniprot_link/mcp/capabilities.py uniprot_link/mcp/tools/discovery.py tests/unit/test_discovery_surface.py
git commit -m "feat(discovery): uniprot://tools resource + capabilities detail mode (F3)"
```

---

## Task 6: Version bump 0.6.0 → 0.7.0 (F5 prep)

**Files:**
- Modify: `uniprot_link/__init__.py`, `pyproject.toml`
- Modify: `tests/unit/test_capabilities.py` (3 assertions), `uv.lock`

- [ ] **Step 1: Bump the package version**

In `uniprot_link/__init__.py`: `__version__ = "0.7.0"`.
In `pyproject.toml`: `version = "0.7.0"`.

- [ ] **Step 2: Update the version assertions in `tests/unit/test_capabilities.py`**

Change the three `cap["server_version"] == "0.6.0"` assertions (lines ~23, ~43)
to `"0.7.0"`. Search for any other `0.6.0` literal in tests and update:

```bash
grep -rn '"0\.6\.0"' tests/
```
Expected after edit: no matches.

- [ ] **Step 3: Sync the lockfile**

Run: `make lock` (or `uv lock`)
Expected: `uv.lock` updates the `uniprot-link` version to 0.7.0.

- [ ] **Step 4: Run the capabilities + full unit suite**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add uniprot_link/__init__.py pyproject.toml uv.lock tests/unit/test_capabilities.py
git commit -m "chore: bump 0.7.0; sync version assertions and lock"
```

---

## Task 7: Integration test — PNKP one-call cold path

**Files:**
- Modify: `tests/integration/test_live.py`

- [ ] **Step 1: Add a marked live test**

Append (match the file's existing fixture/marker style — adapt the service entry
point if the file uses a fixture instead of the facade):

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_pnkp_resolves_in_one_call_with_taxon_alias() -> None:
    """The assessment's cold path: find PNKP via the `taxon` alias in ONE call."""
    import json

    from uniprot_link.mcp.facade import create_uniprot_mcp

    mcp = create_uniprot_mcp()
    result = await mcp.call_tool(
        "find_proteins", {"gene": "PNKP", "taxon": "9606", "reviewed": True}
    )
    sc = result.structured_content
    env = sc if isinstance(sc, dict) else json.loads(result.content[0].text)
    assert env["success"] is True
    assert env["_meta"]["argument_aliases_applied"] == [["taxon", "organism_taxon"]]
    accs = [p["accession"] for p in env["proteins"]]
    assert "Q96T60" in accs
```

- [ ] **Step 2: Run the integration test (live endpoint)**

Run: `.venv/bin/python -m pytest tests/integration/test_live.py::test_pnkp_resolves_in_one_call_with_taxon_alias -q -m integration`
Expected: PASS (resolves `Q96T60`). If the endpoint is slow/unavailable, re-run;
this is the only network-dependent step.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_live.py
git commit -m "test(integration): PNKP cold path resolves in one call via alias"
```

---

## Task 8: CI gate + closure record

**Files:**
- Create: `docs/mcp-assessment-v0.7.0-closure.md`
- Run: `make ci-local`

- [ ] **Step 1: Run the full local CI gate**

Run: `make ci-local`
Expected: PASS — format-check, lint-ci, lint-loc (all modules ≤600), mypy strict,
test-fast. Fix any failures before proceeding (common: line length, an unused
import, a mypy `Any` needing annotation in `middleware.py`).

- [ ] **Step 2: Write the closure record**

Create `docs/mcp-assessment-v0.7.0-closure.md` mapping each finding to its fix and
the evidence (test names + the one-call cold path). Include the F5 redeploy
instruction: after merge, run `make docker-build` and recreate the container so
the deployed `server_version`/`git_sha` catch up to 0.7.0.

- [ ] **Step 3: Final full-suite run**

Run: `.venv/bin/python -m pytest tests/unit -q && make lint-loc`
Expected: all green; no module over 600 lines.

- [ ] **Step 4: Commit**

```bash
git add docs/mcp-assessment-v0.7.0-closure.md
git commit -m "docs: v0.7.0 closure record (arg-contract & discoverability uplift)"
```

---

## Self-Review (completed during planning)

- **Spec coverage:** F1 → Task 4 (signatures) + Task 3 (aliases/did-you-mean);
  F2 → Tasks 2–3 (middleware + envelope); F3 → Task 5 (tools resource + detail
  mode); F4 → Task 4 (accession-first nudge; failed pre-calls removed by F1/F2);
  F5 → Task 6 (version bump) + Task 8 (documented redeploy). All covered.
- **Placeholder scan:** none — every code step shows complete code.
- **Type consistency:** `normalize_alias_args`/`did_you_mean`/`tool_signature`
  signatures match across Tasks 1, 3, 5; `build_arg_error_envelope` keyword args
  match between Task 2 (def) and Task 3 (call). `project_capabilities` /
  `collect_tool_signatures` / `build_tools_overview` names match between Task 5's
  definitions and the `discovery.py` call site.
- **Risk note:** `read_resource` return shape is confirmed empirically in Task 5
  Step 2 before the test helper is finalized (string vs content-list).
```
