"""Unit tests for the service layer and MCP tool envelope (fake client)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import make_select_json
from uniprot_link.exceptions import NotFoundError
from uniprot_link.mcp import service_adapters
from uniprot_link.mcp.envelope import McpErrorContext, McpToolError, run_mcp_tool

_SUMMARY = make_select_json(
    ["mnemonic", "reviewed", "fullName", "genes", "organism", "taxid", "mass", "length"],
    [
        {
            "mnemonic": "A4_HUMAN",
            "reviewed": True,
            "fullName": "Amyloid-beta precursor protein",
            "genes": "APP",
            "organism": "Homo sapiens",
            "taxid": "http://purl.uniprot.org/taxonomy/9606",
            "mass": 86943,
            "length": 770,
        }
    ],
)
_EMPTY = make_select_json([], [])


@pytest.mark.asyncio
async def test_get_protein_shapes_summary(service_factory: Any) -> None:
    svc = service_factory([("up:recommendedName", _SUMMARY)])
    out = await svc.get_protein("P05067")
    assert out["accession"] == "P05067"
    assert out["recommended_name"] == "Amyloid-beta precursor protein"
    assert out["genes"] == ["APP"]


@pytest.mark.asyncio
async def test_get_protein_response_mode_minimal_drops_function(service_factory: Any) -> None:
    body = make_select_json(
        ["mnemonic", "reviewed", "fullName", "function"],
        [{"mnemonic": "A4_HUMAN", "reviewed": True, "fullName": "APP", "function": "long..."}],
    )
    svc = service_factory([("up:recommendedName", body)])
    full = await svc.get_protein("P05067", response_mode="full")
    assert "function" in full
    minimal = await svc.get_protein("P05067", response_mode="minimal")
    assert "function" not in minimal
    assert minimal["mnemonic"] == "A4_HUMAN"


@pytest.mark.asyncio
async def test_get_sequence_dedupes_canonical_and_minimal_strips_sequence(
    service_factory: Any,
) -> None:
    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 770,
                "mass": 86943,
                "value": "MLPCANON",
            },
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-2",
                "length": 365,
                "mass": 40000,
                "value": "MABISO2",
            },
        ],
    )
    svc = service_factory([("up:sequence", body)])
    res = await svc.get_sequence("P05067")
    assert res["canonical"]["isoform"] == "P05067-1"
    assert all(s["isoform"] != "P05067-1" for s in res["isoforms"])  # canonical excluded
    assert res["isoform_count"] == 2
    assert res["canonical"]["sequence"] == "MLPCANON"  # default keeps sequence
    minimal = await svc.get_sequence("P05067", response_mode="minimal")
    assert "sequence" not in minimal["canonical"]
    assert minimal["canonical"]["length"] == 770
    assert all("sequence" not in s for s in minimal["isoforms"])


@pytest.mark.asyncio
async def test_get_sequence_single_isoform_has_empty_isoforms(service_factory: Any) -> None:
    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 770,
                "mass": 86943,
                "value": "MLPCANON",
            }
        ],
    )
    svc = service_factory([("up:sequence", body)])
    res = await svc.get_sequence("P05067")
    assert res["isoforms"] == []
    assert res["isoform_count"] == 1


@pytest.mark.asyncio
async def test_get_protein_not_found_raises(service_factory: Any) -> None:
    svc = service_factory([("up:recommendedName", _EMPTY)])
    with pytest.raises(NotFoundError):
        await svc.get_protein("P00000")


@pytest.mark.asyncio
async def test_get_protein_bogus_accession_raises_not_found(service_factory: Any) -> None:
    # Empty result set for the summary query -> not found.
    svc = service_factory([("a up:Protein", {"head": {"vars": []}, "results": {"bindings": []}})])
    with pytest.raises(NotFoundError):
        await svc.get_protein("Q9ZZZ9")


@pytest.mark.asyncio
async def test_get_features_zero_match_echoes_accepted_keys(service_factory: Any) -> None:
    # empty result for the features query -> filter_hint with accepted keys
    svc = service_factory(
        [
            ("ASK", {"head": {}, "boolean": True}),
            ("up:annotation", {"head": {"vars": []}, "results": {"bindings": []}}),
        ]
    )
    res = await svc.get_features("P38398", ["domain"])
    assert res["count"] == 0
    assert "domain" in res["filter_hint"]["accepted_feature_types"]


@pytest.mark.asyncio
async def test_typed_tools_report_elapsed_ms_and_cached(service_factory: Any) -> None:
    routes = [
        ("ASK", {"head": {}, "boolean": True}),
        ("up:annotation", make_select_json(["type", "begin", "end", "comment"], [])),
    ]
    svc = service_factory(routes)
    first = await svc.get_features("P38398")
    assert first["elapsed_ms"] == 1.0
    assert first["cached"] is False
    # second identical call hits the TTL cache for the data query
    second = await svc.get_features("P38398")
    assert second["cached"] is True
    assert second["elapsed_ms"] == 0.0


@pytest.mark.asyncio
async def test_get_variants_truncated_when_limit_reached(service_factory: Any) -> None:
    from tests.conftest import make_select_json

    rows = [
        {"begin": i, "end": i, "substitution": "A", "comment": "x", "disease": "D"}
        for i in range(2)
    ]
    routes = [
        ("ASK", {"head": {}, "boolean": True}),
        (
            "Natural_Variant_Annotation",
            make_select_json(["begin", "end", "substitution", "comment", "disease"], rows),
        ),
    ]
    service = service_factory(routes)
    res = await service.get_variants("P38398", limit=2)
    assert "truncated" in res


@pytest.mark.asyncio
async def test_get_variants_truncation_uses_raw_row_count(service_factory: Any) -> None:
    from tests.conftest import make_select_json

    # Three raw rows that all merge into ONE variant (same position+substitution).
    # The SPARQL LIMIT caps pre-merge rows, so truncation must flag even though
    # the merged variant count (1) is below the limit (3).
    rows = [
        {"begin": 10, "end": 10, "substitution": "K", "comment": "x", "disease": d}
        for d in ("D1", "D2", "D3")
    ]
    routes = [
        ("ASK", {"head": {}, "boolean": True}),
        (
            "Natural_Variant_Annotation",
            make_select_json(["begin", "end", "substitution", "comment", "disease"], rows),
        ),
    ]
    service = service_factory(routes)
    res = await service.get_variants("P38398", limit=3)
    assert res["count"] == 1
    assert "truncated" in res


@pytest.mark.asyncio
async def test_annotation_tools_not_found_when_entry_absent(service_factory: Any) -> None:
    routes = [("ASK", {"head": {}, "boolean": False})]
    service = service_factory(routes)
    for call in (
        service.get_features,
        service.get_variants,
        service.get_diseases,
        service.get_go_terms,
        service.get_cross_references,
    ):
        with pytest.raises(NotFoundError):
            await call("Q9ZZZ9")


@pytest.mark.asyncio
async def test_cross_references_short_by_default_full_on_request(service_factory: Any) -> None:
    body = make_select_json(
        ["db", "database", "xref"],
        [
            {
                "db": "http://purl.uniprot.org/database/PDB",
                "database": "PDB",
                "xref": "http://rdf.wwpdb.org/pdb/1AAP",
            }
        ],
    )
    routes = [("ASK", {"head": {}, "boolean": True}), ("rdfs:seeAlso", body)]
    svc = service_factory(routes)
    compact = await svc.get_cross_references("P05067")
    assert compact["by_database"]["PDB"] == ["1AAP"]
    full = await svc.get_cross_references("P05067", response_mode="full")
    assert full["by_database"]["PDB"] == ["http://rdf.wwpdb.org/pdb/1AAP"]


@pytest.mark.asyncio
async def test_run_query_select_truncation(service_factory: Any) -> None:
    rows = make_select_json(["s"], [{"s": f"http://x/{i}"} for i in range(2)])
    svc = service_factory([("SELECT", rows)])
    out = await svc.run_query("SELECT ?s WHERE { ?s ?p ?o }", limit=2)
    assert out["query_type"] == "SELECT"
    assert out["row_count"] == 2
    assert out["limit_injected"] is True
    assert "truncated" in out


@pytest.mark.asyncio
async def test_run_query_ask(service_factory: Any) -> None:
    svc = service_factory([("ASK", {"head": {"link": []}, "boolean": True})])
    out = await svc.run_query("ASK { ?s ?p ?o }")
    assert out["query_type"] == "ASK"
    assert out["boolean"] is True


@pytest.mark.asyncio
async def test_run_query_invalid_format(service_factory: Any) -> None:
    from uniprot_link.exceptions import InvalidInputError

    svc = service_factory([])
    with pytest.raises(InvalidInputError):
        await svc.run_query("SELECT ?s WHERE {?s ?p ?o}", result_format="yaml")


@pytest.mark.asyncio
async def test_run_query_rejects_insert(service_factory: Any) -> None:
    from uniprot_link.exceptions import InvalidInputError

    service = service_factory([])
    with pytest.raises(InvalidInputError):
        await service.run_query("INSERT DATA { <a> <b> <c> }")


@pytest.mark.asyncio
async def test_envelope_success_injects_meta() -> None:
    async def call() -> dict[str, Any]:
        return {"hello": "world"}

    out = await run_mcp_tool("demo", call, context=McpErrorContext("demo"))
    assert out["success"] is True
    assert out["_meta"]["tool"] == "demo"
    assert out["_meta"]["uniprot_release"]


@pytest.mark.asyncio
async def test_provenance_is_compact() -> None:
    from uniprot_link.mcp.envelope import _provenance_meta

    meta = _provenance_meta()
    assert meta["citation"] == "doi:10.1093/nar/gkae1010"
    assert "recommended_citation" not in meta  # full text only in capabilities/resource
    assert meta["unsafe_for_clinical_use"] is True
    assert meta["uniprot_release"]
    assert meta["endpoint"]


@pytest.mark.asyncio
async def test_envelope_classifies_not_found() -> None:
    async def call() -> dict[str, Any]:
        raise NotFoundError("nope")

    out = await run_mcp_tool("demo", call, context=McpErrorContext("demo"))
    assert out["success"] is False
    assert out["error_code"] == "not_found"
    assert out["recovery_action"] == "reformulate_input"


@pytest.mark.asyncio
async def test_envelope_mcp_tool_error_code() -> None:
    async def call() -> dict[str, Any]:
        raise McpToolError(error_code="rate_limited", message="slow down")

    out = await run_mcp_tool("demo", call)
    assert out["error_code"] == "rate_limited"
    assert out["retryable"] is True


@pytest.mark.asyncio
async def test_tool_call_through_facade(service_factory: Any) -> None:
    """End-to-end tool dispatch with a faked service singleton."""
    from uniprot_link.mcp.facade import create_uniprot_mcp

    svc = service_factory([("up:recommendedName", _SUMMARY)])
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool("get_protein", {"accession": "P05067"})
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is True
        assert payload["mnemonic"] == "A4_HUMAN"
        assert payload["_meta"]["next_commands"][0]["tool"] == "get_protein_sequence"
    finally:
        service_adapters.set_sparql_service(None)


@pytest.mark.asyncio
async def test_annotation_tool_attaches_next_commands(service_factory: Any) -> None:
    """A decorated annotation tool attaches the entry-subresource chain."""
    from uniprot_link.mcp.facade import create_uniprot_mcp

    routes = [
        ("ASK", {"head": {}, "boolean": True}),
        ("Disease_Annotation", make_select_json(["disease", "diseaseLabel", "comment"], [])),
    ]
    svc = service_factory(routes)
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool("get_protein_diseases", {"accession": "P38398"})
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is True
        next_commands = payload["_meta"]["next_commands"]
        assert len(next_commands) == 3
        assert all(c["arguments"]["accession"] == "P38398" for c in next_commands)
        assert all(c["tool"] != "get_protein_diseases" for c in next_commands)
        assert next_commands[0]["tool"] == "get_protein_variants"
    finally:
        service_adapters.set_sparql_service(None)


@pytest.mark.asyncio
async def test_run_sparql_query_error_offers_examples_fallback() -> None:
    from uniprot_link.exceptions import QuerySyntaxError
    from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from uniprot_link.mcp.next_commands import cmd

    async def boom() -> dict[str, Any]:
        raise QuerySyntaxError("Malformed SPARQL query.")

    env = await run_mcp_tool(
        "run_sparql_query",
        boom,
        context=McpErrorContext("run_sparql_query", fallback=cmd("search_example_queries")),
    )
    assert env["success"] is False
    assert env["error_code"] == "query_syntax_error"
    assert any(c["tool"] == "search_example_queries" for c in env["_meta"]["next_commands"])


@pytest.mark.asyncio
async def test_map_identifiers_defaults_to_curated_dbs(service_factory: Any) -> None:
    from tests.conftest import make_select_json
    from uniprot_link.services.constants import COMMON_XREF_DATABASES

    body = make_select_json(
        ["db", "database", "xref"],
        [
            {
                "db": "http://purl.uniprot.org/database/Ensembl",
                "database": "Ensembl",
                "xref": "http://purl.uniprot.org/ensembl/ENSP00000269305",
            },
        ],
    )
    service = service_factory([("rdfs:seeAlso", body), ("ASK", {"head": {}, "boolean": True})])
    res = await service.map_identifiers("P38398")
    assert res["requested_databases"] == COMMON_XREF_DATABASES
    assert "by_database" in res and "mapped_databases" in res


@pytest.mark.asyncio
async def test_error_envelope_surfaces_allowed_and_request_id() -> None:
    from uniprot_link.exceptions import InvalidInputError

    async def boom() -> dict[str, Any]:
        raise InvalidInputError(
            "Unknown feature type 'x'. See allowed_values.",
            field="feature_types",
            allowed=["domain", "region"],
            hint="call get_server_capabilities",
        )

    out = await run_mcp_tool(
        "get_protein_features", boom, context=McpErrorContext("get_protein_features")
    )
    assert out["success"] is False
    assert out["error_code"] == "invalid_input"
    assert out["field"] == "feature_types"
    assert out["allowed_values"] == ["domain", "region"]
    assert out["hint"] == "call get_server_capabilities"
    assert out["_meta"]["request_id"]


@pytest.mark.asyncio
async def test_error_envelope_always_has_next_commands() -> None:
    async def boom() -> dict[str, Any]:
        raise NotFoundError("nope")

    out = await run_mcp_tool(
        "get_protein_features", boom, context=McpErrorContext("get_protein_features")
    )
    assert out["_meta"]["next_commands"]
    assert out["_meta"]["next_commands"][0]["tool"] == "get_server_capabilities"


@pytest.mark.asyncio
async def test_success_meta_has_request_id() -> None:
    async def ok() -> dict[str, Any]:
        return {"value": 1}

    out = await run_mcp_tool("get_protein", ok, context=McpErrorContext("get_protein"))
    assert out["_meta"]["request_id"]
    assert out["success"] is True
