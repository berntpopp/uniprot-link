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
    # `bogus_arg` is neither a real param nor a known alias -> pure routing case.
    result = await mcp.call_tool("find_proteins", {"bogus_arg": "9606"})
    env = _structured(result)
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
    assert env["field"] == "bogus_arg"
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
async def test_alias_normalized_and_disclosed() -> None:
    """taxon -> organism_taxon lands on the right (typed) param and is disclosed."""
    import uniprot_link.mcp.service_adapters as service_adapters

    seen: dict[str, Any] = {}

    class _Svc:
        async def find_proteins(self, **kw: Any) -> dict[str, Any]:
            seen.update(kw)
            return {"count": 0, "proteins": []}

    service_adapters.set_sparql_service(_Svc())  # type: ignore[arg-type]
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool("find_proteins", {"gene": "PNKP", "taxon": "9606"})
        env = _structured(result)
        assert env["success"] is True
        assert env["_meta"]["argument_aliases_applied"] == [["taxon", "organism_taxon"]]
        assert seen["organism_taxon"] == 9606  # alias landed + coerced str->int
    finally:
        service_adapters.set_sparql_service(None)
