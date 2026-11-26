"""Response-Envelope Standard v1.2: every data tool's result validates against the
published JSON Schema (berntpopp/genefoundry-envelope, tag v1.2.0, vendored here)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema

from tests.conftest import make_select_json
from uniprot_link.mcp import service_adapters
from uniprot_link.mcp.facade import create_uniprot_mcp

_HERE = Path(__file__).parent
_SCHEMA_FILE = _HERE / "envelope-v1.2.schema.json"
SCHEMA = json.loads(_SCHEMA_FILE.read_text())
PROVENANCE = ("source", "data_version", "retrieved_at")
# Orient a client and return no upstream data: outside the v1.2 provenance rule.
OPS_TOOLS = {"get_server_capabilities"}

# One row that satisfies every query builder's shaper, served for any query.
_ROW = {
    "obsolete": False,
    "mnemonic": "A4_HUMAN",
    "reviewed": True,
    "fullName": "Amyloid-beta precursor protein",
    "n": 1,
    "scientificName": "Homo sapiens",
    "description": "d",
    "query": "SELECT 1",
}
_ROUTES = [("", make_select_json(list(_ROW), [_ROW]))]


def test_vendored_schema_matches_pinned_sha256() -> None:
    pinned = (_HERE / "envelope-v1.2.schema.sha256").read_text().split()[0]
    assert hashlib.sha256(_SCHEMA_FILE.read_bytes()).hexdigest() == pinned


async def _call_every_data_tool(
    service_factory: Callable[[list[tuple[str, dict[str, Any]]]], Any],
) -> dict[str, dict[str, Any]]:
    """Call each data tool in-process with its own schema examples."""
    service_adapters.set_sparql_service(service_factory(_ROUTES))
    try:
        mcp = create_uniprot_mcp()
        out: dict[str, dict[str, Any]] = {}
        for tool in await mcp.list_tools():
            if tool.name in OPS_TOOLS:
                continue
            props = tool.parameters.get("properties", {})
            args = {k: props[k]["examples"][0] for k in tool.parameters.get("required", [])}
            result = await mcp.call_tool(tool.name, args)
            assert result.structured_content is not None, tool.name
            assert json.loads(result.content[0].text) == result.structured_content, tool.name
            out[tool.name] = result.structured_content
        return out
    finally:
        service_adapters.set_sparql_service(None)


async def test_every_data_tool_result_validates_against_schema(service_factory: Any) -> None:
    envelopes = await _call_every_data_tool(service_factory)
    assert len(envelopes) >= 14
    for name, envelope in envelopes.items():
        assert envelope["success"] is True, f"{name}: {envelope.get('message')}"
        jsonschema.validate(envelope, SCHEMA)


async def test_every_data_tool_carries_provenance(service_factory: Any) -> None:
    for name, envelope in (await _call_every_data_tool(service_factory)).items():
        for field in PROVENANCE:
            value = envelope["_meta"].get(field)
            assert isinstance(value, str) and value.strip(), f"{name}: _meta.{field}"
        assert envelope["_meta"]["source"] == "uniprot"


async def test_error_envelope_validates_against_schema(service_factory: Any) -> None:
    service_adapters.set_sparql_service(service_factory([]))
    try:
        result = await create_uniprot_mcp().call_tool("get_protein", {"accession": "P05067"})
    finally:
        service_adapters.set_sparql_service(None)
    assert result.structured_content["success"] is False
    jsonschema.validate(result.structured_content, SCHEMA)


async def test_cache_hit_keeps_the_original_retrieved_at(
    service_factory: Any, monkeypatch: Any
) -> None:
    """v1.2: a cached result reports the fetch that filled the entry, not the read."""
    from datetime import UTC, datetime

    from uniprot_link import provenance
    from uniprot_link.services import service_base

    class _Clock(datetime):
        current = datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return cls.current

    monkeypatch.setattr(service_base, "datetime", _Clock)
    monkeypatch.setattr(provenance, "datetime", _Clock)
    service_adapters.set_sparql_service(service_factory(_ROUTES))
    try:
        mcp = create_uniprot_mcp()
        first = await mcp.call_tool("get_taxon", {"taxon": "9606"})
        _Clock.current = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
        second = await mcp.call_tool("get_taxon", {"taxon": "9606"})
    finally:
        service_adapters.set_sparql_service(None)
    assert second.structured_content["result"]["cached"] is True
    assert first.structured_content["_meta"]["retrieved_at"] == "2026-01-01T08:00:00Z"
    assert second.structured_content["_meta"]["retrieved_at"] == "2026-01-01T08:00:00Z"
