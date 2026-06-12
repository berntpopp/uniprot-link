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
# entry_status probe result for a live (non-obsolete) entry -- the gate every
# data tool now runs (replaces the old existence ASK).
_ACTIVE_STATUS = make_select_json(["obsolete"], [{"obsolete": False}])


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
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:sequence", body)])
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
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:sequence", body)])
    res = await svc.get_sequence("P05067")
    assert res["isoforms"] == []
    assert res["isoform_count"] == 1


@pytest.mark.asyncio
async def test_get_protein_obsolete_returns_flagged_record(service_factory: Any) -> None:
    status = make_select_json(
        ["obsolete", "replacedBy"],
        [{"obsolete": True, "replacedBy": "http://purl.uniprot.org/uniprot/A0A9P2UQ24"}],
    )
    summary = make_select_json(
        ["mnemonic", "reviewed"], [{"mnemonic": "A0A009K1D9_ACIBA", "reviewed": False}]
    )
    svc = service_factory([("up:obsolete ?obsolete", status), ("up:recommendedName", summary)])
    out = await svc.get_protein("A0A009K1D9")
    assert out["obsolete"] is True
    assert out["replaced_by"] == ["A0A9P2UQ24"]
    assert out["obsolete_reason"] == "demerged"
    assert out["mnemonic"] == "A0A009K1D9_ACIBA"
    assert "sequence_length" not in out and "mass_da" not in out  # nothing fabricated
    assert out["requested_accession"] == "A0A009K1D9"


@pytest.mark.asyncio
async def test_get_protein_deleted_no_replacement(service_factory: Any) -> None:
    status = make_select_json(["obsolete"], [{"obsolete": True}])
    summary = make_select_json(["mnemonic"], [{"mnemonic": "Z9Z9Z9_STAAU"}])
    svc = service_factory([("up:obsolete ?obsolete", status), ("up:recommendedName", summary)])
    out = await svc.get_protein("Z9Z9Z9")
    assert out["obsolete"] is True
    assert out["obsolete_reason"] == "deleted"
    assert "replaced_by" not in out


@pytest.mark.asyncio
async def test_get_protein_bogus_isoform_is_not_found(service_factory: Any) -> None:
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": False}]
    )
    summary = make_select_json(["mnemonic"], [{"mnemonic": "A4_HUMAN"}])
    svc = service_factory([("up:obsolete ?obsolete", status), ("up:recommendedName", summary)])
    with pytest.raises(NotFoundError):
        await svc.get_protein("P05067-99")


@pytest.mark.asyncio
async def test_get_protein_real_isoform_echoes_request(service_factory: Any) -> None:
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": True}]
    )
    summary = make_select_json(
        ["mnemonic", "has_variants", "has_diseases", "has_structure"],
        [
            {
                "mnemonic": "A4_HUMAN",
                "has_variants": True,
                "has_diseases": True,
                "has_structure": True,
            }
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", status), ("up:recommendedName", summary)])
    out = await svc.get_protein("P05067-2")
    assert out["accession"] == "P05067"
    assert out["requested_accession"] == "P05067-2"
    assert out["isoform"] == "P05067-2"
    assert out["has_variants"] is True


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
            ("up:obsolete ?obsolete", _ACTIVE_STATUS),
            ("up:annotation", {"head": {"vars": []}, "results": {"bindings": []}}),
        ]
    )
    res = await svc.get_features("P38398", ["domain"])
    assert res["count"] == 0
    assert "domain" in res["filter_hint"]["accepted_feature_types"]


@pytest.mark.asyncio
async def test_typed_tools_report_elapsed_ms_and_cached(service_factory: Any) -> None:
    routes = [
        ("up:obsolete ?obsolete", _ACTIVE_STATUS),
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
        ("up:obsolete ?obsolete", _ACTIVE_STATUS),
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
        ("up:obsolete ?obsolete", _ACTIVE_STATUS),
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
    # entry_status returns zero rows -> absent -> NotFoundError on every data tool.
    routes = [("up:obsolete ?obsolete", {"head": {"vars": []}, "results": {"bindings": []}})]
    service = service_factory(routes)
    for call in (
        service.get_features,
        service.get_variants,
        service.get_diseases,
        service.get_go_terms,
        service.get_cross_references,
        service.get_sequence,
    ):
        with pytest.raises(NotFoundError):
            await call("Q9ZZZ9")


@pytest.mark.asyncio
async def test_data_subtools_raise_obsolete_on_obsolete_entry(service_factory: Any) -> None:
    from uniprot_link.exceptions import ObsoleteEntryError

    status = make_select_json(
        ["obsolete", "replacedBy"],
        [{"obsolete": True, "replacedBy": "http://purl.uniprot.org/uniprot/A0A9P2UQ24"}],
    )
    svc = service_factory([("up:obsolete ?obsolete", status)])
    for call in (
        svc.get_features,
        svc.get_variants,
        svc.get_diseases,
        svc.get_go_terms,
        svc.get_cross_references,
        svc.get_sequence,
    ):
        with pytest.raises(ObsoleteEntryError) as ei:
            await call("A0A009K1D9")
        assert ei.value.replaced_by == ["A0A9P2UQ24"]


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
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("rdfs:seeAlso", body)]
    svc = service_factory(routes)
    compact = await svc.get_cross_references("P05067")
    assert compact["by_database"]["PDB"] == ["1AAP"]
    full = await svc.get_cross_references("P05067", response_mode="full")
    assert full["by_database"]["PDB"] == ["http://rdf.wwpdb.org/pdb/1AAP"]


@pytest.mark.asyncio
async def test_cross_references_unknown_db_reports_unmatched(service_factory: Any) -> None:
    """F2: a typo'd database is disclosed via unmatched_databases, not silent-empty."""
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("rdfs:seeAlso", _EMPTY)]
    svc = service_factory(routes)
    res = await svc.get_cross_references("P05067", databases=["NOTADB"])
    assert res["requested_databases"] == ["NOTADB"]
    assert res["unmatched_databases"] == ["NOTADB"]
    assert res["database_count"] == 0
    assert "database_hint" in res  # explains: typo vs genuinely-absent


@pytest.mark.asyncio
async def test_cross_references_partial_match_lists_only_unmatched(service_factory: Any) -> None:
    body = make_select_json(
        ["db", "database", "xref"],
        [{"db": "http://purl.uniprot.org/database/PDB", "database": "PDB", "xref": "http://x/1AAP"}],
    )
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("rdfs:seeAlso", body)]
    svc = service_factory(routes)
    res = await svc.get_cross_references("P05067", databases=["PDB", "NOTADB"])
    assert res["requested_databases"] == ["PDB", "NOTADB"]
    assert res["unmatched_databases"] == ["NOTADB"]
    assert "PDB" in res["counts"]


@pytest.mark.asyncio
async def test_cross_references_no_filter_omits_unmatched(service_factory: Any) -> None:
    """No databases filter -> 'all' -> nothing is 'unmatched' (no noise)."""
    body = make_select_json(
        ["db", "database", "xref"],
        [{"db": "http://purl.uniprot.org/database/PDB", "database": "PDB", "xref": "http://x/1AAP"}],
    )
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("rdfs:seeAlso", body)]
    svc = service_factory(routes)
    res = await svc.get_cross_references("P05067")
    assert "unmatched_databases" not in res
    assert "requested_databases" not in res


@pytest.mark.asyncio
async def test_cross_references_case_typo_gets_did_you_mean(service_factory: Any) -> None:
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("rdfs:seeAlso", _EMPTY)]
    svc = service_factory(routes)
    res = await svc.get_cross_references("P05067", databases=["alphafolddb"])
    assert res["unmatched_databases"] == ["alphafolddb"]
    assert res["database_hint"]["did_you_mean"]["alphafolddb"] == "AlphaFoldDB"


@pytest.mark.asyncio
async def test_map_identifiers_default_set_has_no_unmatched_noise(service_factory: Any) -> None:
    """Default primary-id set: a protein legitimately lacking some is NOT an error."""
    body = make_select_json(
        ["db", "database", "xref"],
        [
            {
                "db": "http://purl.uniprot.org/database/Ensembl",
                "database": "Ensembl",
                "xref": "http://purl.uniprot.org/ensembl/ENSP00000269305",
            }
        ],
    )
    svc = service_factory([("rdfs:seeAlso", body), ("up:obsolete ?obsolete", _ACTIVE_STATUS)])
    res = await svc.map_identifiers("P38398")  # default set
    assert "unmatched_databases" not in res
    # But an EXPLICIT typo is still caught.
    typo = await svc.map_identifiers("P38398", databases=["NOTADB"])
    assert typo["unmatched_databases"] == ["NOTADB"]


@pytest.mark.asyncio
async def test_features_limit_truncates(service_factory: Any) -> None:
    feats = make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {
                "type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
                "begin": i,
                "end": i + 1,
                "comment": "d",
            }
            for i in range(5)
        ],
    )
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:range", feats)]
    svc = service_factory(routes)
    res = await svc.get_features("P05067", limit=3)
    assert res["count"] == 3
    assert res["truncated"]["total"] >= 3


@pytest.mark.asyncio
async def test_go_terms_aspect_filter_limit_and_counts(service_factory: Any) -> None:
    rows_ = [
        {
            "go": f"http://purl.obolibrary.org/obo/GO_{i:07d}",
            "label": f"t{i}",
            "aspect": "http://purl.obolibrary.org/obo/GO_0008150",
        }
        for i in range(3)
    ] + [
        {
            "go": "http://purl.obolibrary.org/obo/GO_0005634",
            "label": "nucleus",
            "aspect": "http://purl.obolibrary.org/obo/GO_0005575",
        }
    ]
    body = make_select_json(["go", "label", "aspect"], rows_)
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:classifiedWith", body)]
    svc = service_factory(routes)
    res = await svc.get_go_terms("P05067")
    assert res["count"] == 4
    assert res["count_by_aspect"]["biological_process"] == 3
    bp_only = await svc.get_go_terms("P05067", aspect="biological_process")
    assert list(bp_only["by_aspect"].keys()) == ["biological_process"]
    assert bp_only["count"] == 3
    limited = await svc.get_go_terms("P05067", limit=2)
    assert limited["count"] == 2 and limited["truncated"]["total"] == 4


@pytest.mark.asyncio
async def test_cross_references_lean_compact_and_minimal(service_factory: Any) -> None:
    rows_ = [
        {
            "db": "http://purl.uniprot.org/database/PDB",
            "database": "PDB",
            "xref": f"http://x/{i:04d}",
        }
        for i in range(40)
    ]
    body = make_select_json(["db", "database", "xref"], rows_)
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("rdfs:seeAlso", body)]
    svc = service_factory(routes)
    compact = await svc.get_cross_references("P05067")  # default compact
    assert compact["counts"]["PDB"] == 40
    assert len(compact["by_database"]["PDB"]) == 25  # capped
    assert compact["truncated_databases"]["PDB"] == {"returned": 25, "total": 40}
    minimal = await svc.get_cross_references("P05067", response_mode="minimal")
    assert "by_database" not in minimal
    assert minimal["counts"]["PDB"] == 40
    full = await svc.get_cross_references("P05067", response_mode="full")
    assert len(full["by_database"]["PDB"]) == 40  # all ids
    assert "truncated_databases" not in full


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
    assert "request_id" in out["_meta"]


@pytest.mark.asyncio
async def test_per_call_meta_is_lean() -> None:
    """Per-call _meta carries only dynamic fields; static provenance is demoted."""
    from uniprot_link.mcp.capabilities import build_capabilities

    async def call() -> dict[str, Any]:
        return {"value": 1}

    out = await run_mcp_tool("demo", call, context=McpErrorContext("demo"))
    meta = out["_meta"]
    assert set(meta) <= {"tool", "request_id", "next_commands"}
    assert "unsafe_for_clinical_use" not in meta
    assert "uniprot_release" not in meta
    assert "citation" not in meta
    assert "endpoint" not in meta
    # Provenance stays authoritative in the discovery surface.
    cap = build_capabilities()
    assert cap["research_use_only"] is True
    assert cap["uniprot_release"]
    assert "Nucleic Acids Res" in cap["recommended_citation"]
    assert cap["per_call_meta"] == ["tool", "request_id", "next_commands"]
    assert "provenance_policy" in cap


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
async def test_short_accession_returns_invalid_input_envelope(service_factory: Any) -> None:
    """A too-short/garbage accession flows through the polished envelope, not raw pydantic."""
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


@pytest.mark.asyncio
async def test_annotation_tool_attaches_next_commands(service_factory: Any) -> None:
    """A decorated annotation tool attaches the entry-subresource chain."""
    from uniprot_link.mcp.facade import create_uniprot_mcp

    routes = [
        ("up:obsolete ?obsolete", _ACTIVE_STATUS),
        (
            "Disease_Annotation",
            make_select_json(
                ["disease", "diseaseLabel", "comment"],
                [
                    {
                        "disease": "http://purl.uniprot.org/diseases/100",
                        "diseaseLabel": "Example disease",
                        "comment": "involvement",
                    }
                ],
            ),
        ),
    ]
    svc = service_factory(routes)
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool("get_protein_diseases", {"accession": "P38398"})
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is True
        next_commands = payload["_meta"]["next_commands"]
        assert len(next_commands) == 2  # token diet: trimmed to the top 2
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
async def test_map_identifiers_defaults_to_primary_id_set(service_factory: Any) -> None:
    from tests.conftest import make_select_json
    from uniprot_link.services.constants import MAP_IDENTIFIER_DATABASES

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
    service = service_factory([("rdfs:seeAlso", body), ("up:obsolete ?obsolete", _ACTIVE_STATUS)])
    res = await service.map_identifiers("P38398")
    assert res["requested_databases"] == MAP_IDENTIFIER_DATABASES
    assert "by_database" in res and "mapped_databases" in res
    assert "DrugBank" not in MAP_IDENTIFIER_DATABASES  # drug/disease DBs stay in cross-refs


@pytest.mark.asyncio
async def test_obsolete_entry_error_envelope_carries_replaced_by() -> None:
    from uniprot_link.exceptions import ObsoleteEntryError

    async def boom() -> dict[str, Any]:
        raise ObsoleteEntryError("A0A009K1D9", replaced_by=["A0A9P2UQ24"])

    out = await run_mcp_tool(
        "get_protein_features",
        boom,
        context=McpErrorContext("get_protein_features"),
    )
    assert out["success"] is False
    assert out["error_code"] == "not_found"
    assert out["obsolete"] is True
    assert out["replaced_by"] == ["A0A9P2UQ24"]
    nxt = out["_meta"]["next_commands"]
    assert nxt[0] == {"tool": "get_protein", "arguments": {"accession": "A0A9P2UQ24"}}


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


@pytest.mark.asyncio
async def test_get_taxon_by_name_has_timing_and_matches(service_factory: Any) -> None:
    from tests.conftest import make_select_json

    body = make_select_json(
        ["taxon", "scientificName", "commonName", "rank"],
        [
            {
                "taxon": "http://purl.uniprot.org/taxonomy/9606",
                "scientificName": "Homo sapiens",
                "commonName": "Human",
                "rank": "",
            }
        ],
    )
    svc = service_factory([("a up:Taxon", body)])
    out = await svc.get_taxon("Homo sapiens")
    assert "elapsed_ms" in out and "cached" in out
    assert out["matches"][0]["taxon_id"] == "9606"


@pytest.mark.asyncio
async def test_get_sequence_compact_is_windowed(service_factory: Any) -> None:
    from tests.conftest import make_select_json

    seq = "M" + "A" * 600 + "K"
    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": len(seq),
                "mass": 1,
                "value": seq,
            }
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:sequence", body)])
    compact = await svc.get_sequence("P05067", response_mode="compact")
    assert "sequence" not in compact["canonical"]
    assert compact["canonical"]["sequence_truncated"] is True
    assert compact["canonical"]["sequence_preview"].startswith("M")
    assert compact["canonical"]["sequence_preview"].endswith("K")
    standard = await svc.get_sequence("P05067", response_mode="standard")
    assert standard["canonical"]["sequence"] == seq


@pytest.mark.asyncio
async def test_success_meta_is_lean() -> None:
    async def ok() -> dict[str, Any]:
        return {"value": 1}

    out = await run_mcp_tool("get_protein", ok, context=McpErrorContext("get_protein"))
    assert "endpoint" not in out["_meta"]
    assert "uniprot_release" not in out["_meta"]
    assert "unsafe_for_clinical_use" not in out["_meta"]
    assert out["_meta"]["tool"] == "get_protein"
    assert "request_id" in out["_meta"]


def test_sort_by_mnemonic_is_total_with_accession_tiebreak() -> None:
    """Entries sharing (or lacking) a mnemonic order by accession, stably."""
    from uniprot_link.services.sparql_service import _sort_by_mnemonic

    page = [
        {"accession": "P00002", "mnemonic": "DUP_HUMAN"},
        {"accession": "P00001", "mnemonic": "DUP_HUMAN"},
        {"accession": "P00003", "mnemonic": None},
    ]
    out = _sort_by_mnemonic(page)
    assert [p["accession"] for p in out] == ["P00001", "P00002", "P00003"]
    # Deterministic across repeated calls regardless of input order.
    assert _sort_by_mnemonic(list(reversed(page))) == out


@pytest.mark.asyncio
async def test_features_domain_without_region_hints(service_factory: Any) -> None:
    """Requesting ['domain'] (not region) attaches a domain->region nudge."""
    feats = make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {
                "type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
                "begin": 6,
                "end": 110,
                "comment": "FHA",
            }
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:range", feats)])
    out = await svc.get_features("Q96T60", ["domain"])
    hint = out["domain_region_hint"]
    assert hint["suggestion"]["arguments"]["feature_types"] == ["domain", "region"]
    assert hint["suggestion"]["arguments"]["accession"] == "Q96T60"
    # When region is already requested, no nudge.
    out2 = await svc.get_features("Q96T60", ["domain", "region"])
    assert "domain_region_hint" not in out2
    # Unfiltered query: no nudge either.
    out3 = await svc.get_features("Q96T60")
    assert "domain_region_hint" not in out3


@pytest.mark.asyncio
async def test_get_taxon_common_name_is_curated(service_factory: Any) -> None:
    """A model-organism name resolves with no SPARQL call (curated fast path)."""
    svc = service_factory([])  # any endpoint call would return empty -> not_found
    out = await svc.get_taxon("Homo sapiens")
    assert out["match_source"] == "curated_common_index"
    assert out["match_count"] == 1
    assert out["matches"][0]["taxon_id"] == "9606"
    assert out["elapsed_ms"] == 0.0
    assert out["cached"] is True
    assert svc.client.calls == []  # the endpoint was never touched
    assert (await svc.get_taxon("human"))["matches"][0]["taxon_id"] == "9606"
    assert (await svc.get_taxon("yeast"))["matches"][0]["taxon_id"] == "559292"


@pytest.mark.asyncio
async def test_get_taxon_name_scan_ranks_exact_first(service_factory: Any) -> None:
    """F3: an exact scientific-name hit is ranked first so chaining is correct."""
    body = make_select_json(
        ["taxon", "scientificName", "rank"],
        [
            {
                "taxon": "http://purl.uniprot.org/taxonomy/2506766",
                "scientificName": "Takifugu chinensis x Takifugu rubripes",
                "rank": "",
            },
            {
                "taxon": "http://purl.uniprot.org/taxonomy/31033",
                "scientificName": "Takifugu rubripes",
                "rank": "http://purl.uniprot.org/core/Species",
            },
        ],
    )
    svc = service_factory([("up:scientificName", body)])
    out = await svc.get_taxon("Takifugu rubripes")
    assert out["match_source"] == "endpoint_scan"
    assert out["matches"][0]["taxon_id"] == "31033"  # exact, not the hybrid
    assert out["matches"][0]["match_quality"] == "exact"


@pytest.mark.asyncio
async def test_get_taxon_uncommon_name_falls_through(service_factory: Any) -> None:
    """An uncommon name hits the endpoint scan and is tagged accordingly."""
    body = make_select_json(
        ["taxon", "scientificName", "rank"],
        [
            {
                "taxon": "http://purl.uniprot.org/taxonomy/63221",
                "scientificName": "Homo sapiens neanderthalensis",
                "rank": "http://purl.uniprot.org/core/Subspecies",
            }
        ],
    )
    svc = service_factory([("up:scientificName", body)])
    out = await svc.get_taxon("Homo sapiens neanderthalensis")
    assert out["match_source"] == "endpoint_scan"
    assert svc.client.calls  # the endpoint WAS queried
    assert out["matches"][0]["taxon_id"] == "63221"


@pytest.mark.asyncio
async def test_find_proteins_reviewed_first_then_spill(service_factory: Any) -> None:
    from tests.conftest import make_select_json

    count_body = make_select_json(["n"], [{"n": 1}])
    reviewed = make_select_json(
        ["protein", "mnemonic", "reviewed", "taxid", "organism"],
        [
            {
                "protein": "http://purl.uniprot.org/uniprot/P38398",
                "mnemonic": "BRCA1_HUMAN",
                "reviewed": True,
                "taxid": "http://purl.uniprot.org/taxonomy/9606",
                "organism": "Homo sapiens",
            }
        ],
    )
    unreviewed = make_select_json(
        ["protein", "mnemonic", "reviewed", "taxid", "organism"],
        [
            {
                "protein": "http://purl.uniprot.org/uniprot/A0A1",
                "mnemonic": "A0A1_HUMAN",
                "reviewed": False,
                "taxid": "http://purl.uniprot.org/taxonomy/9606",
                "organism": "Homo sapiens",
            }
        ],
    )
    # Route by the distinctive substrings the two-phase queries contain.
    svc = service_factory(
        [
            ("COUNT(DISTINCT ?protein)", count_body),
            ("up:reviewed true", reviewed),
            ("up:reviewed false", unreviewed),
        ]
    )
    out = await svc.find_proteins(gene="BRCA1", limit=25, offset=0)
    accs = [p["accession"] for p in out["proteins"]]
    assert accs[0] == "P38398"  # reviewed first
    assert "A0A1" in accs  # then the TrEMBL spill
    assert out["proteins"][0]["reviewed"] is True
