"""Unit tests for the service layer and MCP tool envelope (fake client)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import make_select_json
from uniprot_link.exceptions import InvalidInputError, NotFoundError
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
async def test_high_volume_annotation_tools_expose_response_mode() -> None:
    """The three high-volume annotation tools offer explicit lean projections (#28)."""
    from uniprot_link.mcp.facade import create_uniprot_mcp

    mcp = create_uniprot_mcp()
    for name in ("get_protein_features", "get_protein_variants", "get_protein_diseases"):
        tool = await mcp.get_tool(name)
        assert tool is not None
        response_mode = tool.parameters["properties"]["response_mode"]
        assert response_mode["default"] == "standard"
        assert response_mode["enum"] == ["minimal", "compact", "standard", "full"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "args", "route", "collection", "prose_fields"),
    [
        (
            "get_features",
            ("P05067",),
            (
                "up:range",
                make_select_json(
                    ["type", "begin", "end", "comment"],
                    [
                        {
                            "type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
                            "begin": 4,
                            "end": 130,
                            "comment": "Paired",
                        }
                    ],
                ),
            ),
            "features",
            {"description"},
        ),
        (
            "get_variants",
            ("P05067",),
            (
                "Natural_Variant_Annotation",
                make_select_json(
                    ["begin", "end", "substitution", "comment", "disease"],
                    [
                        {
                            "begin": 176,
                            "end": 176,
                            "substitution": "F",
                            "comment": "Long prose",
                            "disease": "Example disease",
                        }
                    ],
                ),
            ),
            "variants",
            {"description"},
        ),
        (
            "get_diseases",
            ("P05067",),
            (
                "Disease_Annotation",
                make_select_json(
                    ["disease", "diseaseLabel", "comment", "definition"],
                    [
                        {
                            "disease": "http://purl.uniprot.org/diseases/123",
                            "diseaseLabel": "Example disease",
                            "comment": "Long involvement",
                            "definition": "Long definition",
                        }
                    ],
                ),
            ),
            "diseases",
            {"definition", "involvement"},
        ),
    ],
)
async def test_annotation_compact_mode_omits_repeated_fenced_prose(
    service_factory: Any,
    method: str,
    args: tuple[str],
    route: tuple[str, dict[str, Any]],
    collection: str,
    prose_fields: set[str],
) -> None:
    """Compact modes retain records while omitting their repeated text envelopes (#28)."""
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE_STATUS), route])
    result = await getattr(svc, method)(*args, response_mode="compact")
    assert result[collection]
    assert not (prose_fields & result[collection][0].keys())


@pytest.mark.asyncio
async def test_get_protein_shapes_summary(service_factory: Any) -> None:
    svc = service_factory([("up:recommendedName", _SUMMARY)])
    out = await svc.get_protein("P05067")
    assert out["accession"] == "P05067"
    assert out["recommended_name"] == "Amyloid-beta precursor protein"
    assert out["genes"] == ["APP"]


@pytest.mark.asyncio
async def test_get_protein_omits_requested_accession_when_identical(service_factory: Any) -> None:
    """F7: requested_accession is a token tax when it equals accession -- omit it."""
    svc = service_factory([("up:recommendedName", _SUMMARY)])
    out = await svc.get_protein("P05067")
    assert out["accession"] == "P05067"
    assert "requested_accession" not in out
    # Case-only difference normalizes silently -> still omitted.
    out_lower = await svc.get_protein("p05067")
    assert "requested_accession" not in out_lower


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
async def test_get_sequence_isoform_returns_specific_isoform(service_factory: Any) -> None:
    """F2: an isoform accession returns THAT isoform's specific sequence, not not_found."""
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": True}]
    )
    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 770,
                "mass": 86943,
                "value": "MCANON",
            },
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-2",
                "length": 365,
                "value": "MISO2",
            },
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", status), ("up:sequence", body)])
    res = await svc.get_sequence("P05067-2", response_mode="standard")
    assert res["accession"] == "P05067"
    assert res["requested_isoform"] == "P05067-2"
    assert res["canonical"]["isoform"] == "P05067-2"
    assert res["canonical"]["sequence"] == "MISO2"
    assert res["isoforms"] == []  # isoform-specific request returns just that isoform


@pytest.mark.asyncio
async def test_get_sequence_canonical_only_omits_isoforms(service_factory: Any) -> None:
    """F7: canonical_only returns just the canonical record (token economy)."""
    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 770,
                "mass": 86943,
                "value": "MCANON",
            },
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-2",
                "length": 365,
                "value": "MISO2",
            },
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:sequence", body)])
    res = await svc.get_sequence("P05067", canonical_only=True, response_mode="standard")
    assert res["isoforms"] == []
    assert res["isoform_count"] == 2  # count still truthful
    assert res["canonical"]["isoform"] == "P05067-1"


@pytest.mark.asyncio
async def test_get_protein_sequence_tool_accepts_canonical_only(service_factory: Any) -> None:
    """F7: the tool surface exposes canonical_only end-to-end via the facade."""
    from uniprot_link.mcp.facade import create_uniprot_mcp

    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 770,
                "mass": 86943,
                "value": "MCANON",
            },
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-2",
                "length": 365,
                "value": "MISO2",
            },
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:sequence", body)])
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool(
            "get_protein_sequence",
            {"accession": "P05067", "canonical_only": True, "response_mode": "standard"},
        )
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is True
        assert payload["isoforms"] == []
    finally:
        service_adapters.set_sparql_service(None)


@pytest.mark.asyncio
async def test_get_sequence_bogus_isoform_is_not_found(service_factory: Any) -> None:
    """F2: a non-existent isoform index is a clean not_found (consistent with get_protein)."""
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": False}]
    )
    body = make_select_json(
        ["isoform", "length", "mass", "value"],
        [
            {
                "isoform": "http://purl.uniprot.org/isoforms/P05067-1",
                "length": 770,
                "mass": 86943,
                "value": "MCANON",
            }
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", status), ("up:sequence", body)])
    with pytest.raises(NotFoundError):
        await svc.get_sequence("P05067-99")


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
    # F7: input equals the normalized accession -> the echo is omitted.
    assert "requested_accession" not in out


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
async def test_features_isoform_returns_base_features_with_note(service_factory: Any) -> None:
    """F1: an isoform accession returns the entry's features + an isoform note, never silent-empty."""
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": True}]
    )
    feats = make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {
                "type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
                "begin": 1,
                "end": 9,
                "comment": "d",
            }
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", status), ("up:range", feats)])
    res = await svc.get_features("P05067-2", ["domain"])
    assert res["accession"] == "P05067"
    assert res["count"] == 1
    assert res["requested_accession"] == "P05067-2"
    assert "isoform_note" in res


@pytest.mark.asyncio
async def test_features_bogus_isoform_is_not_found(service_factory: Any) -> None:
    """F1: a typo'd isoform index is rejected (never canonical data under a wrong label)."""
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": False}]
    )
    svc = service_factory(
        [("up:obsolete ?obsolete", status), ("up:range", make_select_json([], []))]
    )
    with pytest.raises(NotFoundError):
        await svc.get_features("P05067-99", ["domain"])


@pytest.mark.asyncio
async def test_entry_tools_isoform_note_is_family_wide(service_factory: Any) -> None:
    """F1: diseases/go/xref also echo a valid isoform request consistently."""
    status = make_select_json(
        ["obsolete", "isoform_exists"], [{"obsolete": False, "isoform_exists": True}]
    )
    disease_body = make_select_json(
        ["disease", "diseaseLabel", "comment"],
        [
            {
                "disease": "http://purl.uniprot.org/diseases/100",
                "diseaseLabel": "Example disease",
                "comment": "involvement",
            }
        ],
    )
    svc = service_factory([("up:obsolete ?obsolete", status), ("Disease_Annotation", disease_body)])
    res = await svc.get_diseases("P05067-2")
    assert res["accession"] == "P05067"
    assert res["requested_accession"] == "P05067-2"
    assert "isoform_note" in res


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
        [
            {
                "db": "http://purl.uniprot.org/database/PDB",
                "database": "PDB",
                "xref": "http://x/1AAP",
            }
        ],
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
        [
            {
                "db": "http://purl.uniprot.org/database/PDB",
                "database": "PDB",
                "xref": "http://x/1AAP",
            }
        ],
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
async def test_features_truncation_standard_envelope(service_factory: Any) -> None:
    """F4/F5: truncated = {returned, total, reason, recovery}; total is the TRUE count."""
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
    t = res["truncated"]
    assert t["returned"] == 3
    assert t["total"] == 5  # true total, not the page size (F4)
    assert "limit" in t["reason"]
    assert t["recovery"]


@pytest.mark.asyncio
async def test_variants_truncation_reports_true_total(service_factory: Any) -> None:
    """F5: variants truncation carries the exact total via a cheap count query."""
    rows = [
        {"begin": i, "end": i, "substitution": "A", "comment": "x", "disease": "D"}
        for i in range(2)
    ]
    routes = [
        ("up:obsolete ?obsolete", _ACTIVE_STATUS),
        ("COUNT(DISTINCT ?a)", make_select_json(["n"], [{"n": 7}])),
        (
            "Natural_Variant_Annotation",
            make_select_json(["begin", "end", "substitution", "comment", "disease"], rows),
        ),
    ]
    svc = service_factory(routes)
    res = await svc.get_variants("P38398", limit=2)
    t = res["truncated"]
    assert t["returned"] == res["count"]
    assert t["total"] == 7
    assert "reason" in t and "recovery" in t


@pytest.mark.asyncio
async def test_find_proteins_truncation_reports_total(service_factory: Any) -> None:
    data = make_select_json(
        ["protein", "mnemonic", "reviewed", "taxid", "organism"],
        [
            {
                "protein": f"http://purl.uniprot.org/uniprot/P0000{i}",
                "mnemonic": f"M{i}_HUMAN",
                "reviewed": True,
                "taxid": "http://purl.uniprot.org/taxonomy/9606",
                "organism": "Homo sapiens",
            }
            for i in range(2)
        ],
    )
    routes = [
        ("COUNT(DISTINCT ?protein)", make_select_json(["n"], [{"n": 42}])),
        ("up:reviewed true", data),
    ]
    svc = service_factory(routes)
    res = await svc.find_proteins(gene="TP53", reviewed=True, limit=2)
    t = res["truncated"]
    assert t["returned"] == 2
    assert t["total"] == 42
    assert "reason" in t and "recovery" in t


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
    # F5: standardized envelope carries returned + reason too.
    assert limited["truncated"]["returned"] == 2
    assert "reason" in limited["truncated"] and "recovery" in limited["truncated"]


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
    # minimal retains the id collection (capped), never destroys it: the ids ARE
    # the stable identifiers Response-Envelope v1 requires minimal to keep. It only
    # drops the truncated_databases cap-flag (compact keeps that).
    assert len(minimal["by_database"]["PDB"]) == 25  # capped, still present
    assert "truncated_databases" not in minimal
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
    # F5: standardized envelope carries `returned`; `total` is intentionally
    # omitted for an arbitrary query (not cheaply computable).
    assert out["truncated"]["returned"] == 2
    assert "reason" in out["truncated"] and "recovery" in out["truncated"]


@pytest.mark.asyncio
async def test_run_query_csv_select_labels_query_type_select(service_factory: Any) -> None:
    """F8: a SELECT projected to CSV is query_type SELECT (not RDF/raw) + serialization."""
    svc = service_factory([])  # non-json returns empty text; classification is structural
    out = await svc.run_query("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1", result_format="csv")
    assert out["query_type"] == "SELECT"
    assert out["serialization"] == "csv"


@pytest.mark.asyncio
async def test_run_query_rejects_construct(service_factory: Any) -> None:
    """The raw power query policy permits bounded SELECT/ASK only."""
    svc = service_factory([])
    with pytest.raises(InvalidInputError, match="only SELECT and ASK"):
        await svc.run_query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "# harmless prologue comment\nPREFIX ex: <https://example.org/>\nCoNsTrUcT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "# another harmless comment\nBASE <https://example.org/>\ndEsCrIbE <protein/P05067>",
        "SELECT ?s WHERE { { OPTIONAL { sErViCe ?endpoint { ?s ?p ?o } } } }",
    ],
)
async def test_run_query_rejects_forbidden_forms_before_client_execution(
    service_factory: Any, query: str
) -> None:
    """Policy validation must reject obfuscated forms before an HTTP-capable client runs."""
    svc = service_factory([])
    with pytest.raises(InvalidInputError):
        await svc.run_query(query)
    assert svc.client.calls == []


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
    """Per-call _meta carries only dynamic fields (+ the clinical-use disclaimer);
    static provenance (citation/release/endpoint) is demoted to capabilities."""
    from uniprot_link.mcp.capabilities import build_capabilities

    async def call() -> dict[str, Any]:
        return {"value": 1}

    out = await run_mcp_tool("demo", call, context=McpErrorContext("demo"))
    meta = out["_meta"]
    assert set(meta) <= {"tool", "request_id", "next_commands", "unsafe_for_clinical_use"}
    assert meta["unsafe_for_clinical_use"] is True
    assert "uniprot_release" not in meta
    assert "citation" not in meta
    assert "endpoint" not in meta
    # Provenance stays authoritative in the discovery surface.
    cap = build_capabilities()
    assert cap["research_use_only"] is True
    assert cap["uniprot_release"]
    assert "Nucleic Acids Res" in cap["recommended_citation"]
    assert cap["per_call_meta"] == [
        "tool",
        "request_id",
        "next_commands",
        "unsafe_for_clinical_use",
    ]
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
async def test_default_feature_and_variant_tools_complete_through_facade(
    service_factory: Any,
) -> None:
    """Default annotation calls remain serializable and successful (#28)."""
    from uniprot_link.mcp.facade import create_uniprot_mcp

    feature_body = make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {
                "type": "http://purl.uniprot.org/core/Domain_Extent_Annotation",
                "begin": 4,
                "end": 130,
                "comment": "Paired",
            }
        ],
    )
    variant_body = make_select_json(
        ["begin", "end", "substitution", "comment", "disease"],
        [
            {
                "begin": 176,
                "end": 176,
                "substitution": "F",
                "comment": "Long prose",
                "disease": "Example disease",
            }
        ],
    )
    svc = service_factory(
        [
            ("up:obsolete ?obsolete", _ACTIVE_STATUS),
            ("Natural_Variant_Annotation", variant_body),
            ("up:range", feature_body),
        ]
    )
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        for name in ("get_protein_features", "get_protein_variants"):
            result = await mcp.call_tool(name, {"accession": "P05067"})
            payload = result.structured_content if hasattr(result, "structured_content") else result
            assert payload["success"] is True
            assert payload["count"] == 1
            assert payload["_meta"]["tool"] == name
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
async def test_search_sparql_query_success_has_next_commands(service_factory: Any) -> None:
    """F8: search_sparql_query success carries _meta.next_commands like every tool."""
    from uniprot_link.mcp.facade import create_uniprot_mcp

    rows = make_select_json(["protein"], [{"protein": "http://purl.uniprot.org/uniprot/P05067"}])
    svc = service_factory([("SELECT", rows)])
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool(
            "search_sparql_query", {"query": "SELECT ?protein WHERE { ?protein ?p ?o }"}
        )
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is True
        nxt = payload["_meta"]["next_commands"]
        assert nxt and nxt[0] == {"tool": "get_protein", "arguments": {"accession": "P05067"}}
    finally:
        service_adapters.set_sparql_service(None)


@pytest.mark.asyncio
async def test_search_sparql_query_error_offers_examples_fallback() -> None:
    from uniprot_link.exceptions import QuerySyntaxError
    from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
    from uniprot_link.mcp.next_commands import cmd

    async def boom() -> dict[str, Any]:
        raise QuerySyntaxError("Malformed SPARQL query.")

    env = await run_mcp_tool(
        "search_sparql_query",
        boom,
        context=McpErrorContext("search_sparql_query", fallback=cmd("search_example_queries")),
    )
    assert env["success"] is False
    assert env["error_code"] == "invalid_input"
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
    assert out["_meta"]["unsafe_for_clinical_use"] is True
    assert out["_meta"]["tool"] == "get_protein"
    assert "request_id" in out["_meta"]


def test_sort_by_mnemonic_is_total_with_accession_tiebreak() -> None:
    """Entries sharing (or lacking) a mnemonic order by accession, stably."""
    from uniprot_link.services.service_base import _sort_by_mnemonic

    page = [
        {"accession": "P00002", "mnemonic": "DUP_HUMAN"},
        {"accession": "P00001", "mnemonic": "DUP_HUMAN"},
        {"accession": "P00003", "mnemonic": None},
    ]
    out = _sort_by_mnemonic(page)
    assert [p["accession"] for p in out] == ["P00001", "P00002", "P00003"]
    # Deterministic across repeated calls regardless of input order.
    assert _sort_by_mnemonic(list(reversed(page))) == out


def _features_body() -> dict[str, Any]:
    return make_select_json(
        ["type", "begin", "end", "comment"],
        [
            {"type": "http://purl.uniprot.org/core/Domain_Extent_Annotation", "begin": 1, "end": 9},
            {"type": "http://purl.uniprot.org/core/Helix_Annotation", "begin": 10, "end": 12},
            {"type": "http://purl.uniprot.org/core/Beta_Strand_Annotation", "begin": 13, "end": 15},
            {"type": "http://purl.uniprot.org/core/Turn_Annotation", "begin": 16, "end": 17},
        ],
    )


@pytest.mark.asyncio
async def test_features_excludes_secondary_structure_by_default(service_factory: Any) -> None:
    """P1b: helix/strand/turn are hidden by default and disclosed, not silent."""
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:range", _features_body())]
    svc = service_factory(routes)
    res = await svc.get_features("P05067")
    types = {f["type"] for f in res["features"]}
    assert types == {"domain"}  # the 3 secondary-structure rows are hidden
    assert res["count"] == 1
    assert res["excluded_secondary_structure"]["count"] == 3
    assert set(res["excluded_secondary_structure"]["types"]) == {"beta_strand", "helix", "turn"}


@pytest.mark.asyncio
async def test_features_include_secondary_structure_flag(service_factory: Any) -> None:
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:range", _features_body())]
    svc = service_factory(routes)
    res = await svc.get_features("P05067", include_secondary_structure=True)
    assert res["count"] == 4
    assert "excluded_secondary_structure" not in res


@pytest.mark.asyncio
async def test_features_explicit_secondary_type_is_returned(service_factory: Any) -> None:
    """Explicit feature_types=['helix'] beats the default exclusion."""
    helix = make_select_json(
        ["type", "begin", "end", "comment"],
        [{"type": "http://purl.uniprot.org/core/Helix_Annotation", "begin": 10, "end": 12}],
    )
    routes = [("up:obsolete ?obsolete", _ACTIVE_STATUS), ("up:range", helix)]
    svc = service_factory(routes)
    res = await svc.get_features("P05067", feature_types=["helix"])
    assert res["count"] == 1
    assert res["features"][0]["type"] == "helix"
    assert "excluded_secondary_structure" not in res


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


def _gene_hit(acc: str, mnem: str) -> dict[str, Any]:
    return make_select_json(
        ["protein", "mnemonic", "reviewed", "taxid", "organism"],
        [
            {
                "protein": f"http://purl.uniprot.org/uniprot/{acc}",
                "mnemonic": mnem,
                "reviewed": True,
                "taxid": "http://purl.uniprot.org/taxonomy/9606",
                "organism": "Homo sapiens",
            }
        ],
    )


@pytest.mark.asyncio
async def test_find_proteins_batch_resolves_each_gene(service_factory: Any) -> None:
    """P1a: several gene symbols resolve in one call, tagged by gene."""
    routes = [
        ('"PNKP"', _gene_hit("Q96T60", "PNKP_HUMAN")),
        ('"NAA10"', _gene_hit("P41227", "NAA10_HUMAN")),
    ]
    svc = service_factory(routes)
    res = await svc.find_proteins_batch(["PNKP", "NAA10"], organism_taxon=9606, reviewed=True)
    assert res["gene_count"] == 2
    assert res["by_gene"]["PNKP"] == ["Q96T60"]
    assert res["by_gene"]["NAA10"] == ["P41227"]
    assert res["unresolved_genes"] == []
    assert {p["matched_gene"] for p in res["proteins"]} == {"PNKP", "NAA10"}
    assert "elapsed_ms" in res and "cached" in res


@pytest.mark.asyncio
async def test_find_proteins_batch_reports_unresolved_genes(service_factory: Any) -> None:
    """An unresolved gene is disclosed, not silently dropped."""
    routes = [('"PNKP"', _gene_hit("Q96T60", "PNKP_HUMAN"))]
    svc = service_factory(routes)
    res = await svc.find_proteins_batch(["PNKP", "ZZZ9"], organism_taxon=9606, reviewed=True)
    assert res["by_gene"]["PNKP"] == ["Q96T60"]
    assert res["unresolved_genes"] == ["ZZZ9"]
    assert res["resolved_genes"] == ["PNKP"]


@pytest.mark.asyncio
async def test_find_proteins_batch_dedupes_genes(service_factory: Any) -> None:
    routes = [('"PNKP"', _gene_hit("Q96T60", "PNKP_HUMAN"))]
    svc = service_factory(routes)
    res = await svc.find_proteins_batch(["PNKP", "pnkp", " PNKP "], reviewed=True)
    assert res["gene_count"] == 1


@pytest.mark.asyncio
async def test_find_proteins_batch_empty_is_invalid_input(service_factory: Any) -> None:
    from uniprot_link.exceptions import InvalidInputError

    svc = service_factory([])
    with pytest.raises(InvalidInputError):
        await svc.find_proteins_batch([], organism_taxon=9606)


@pytest.mark.asyncio
async def test_find_proteins_batch_facade_fans_out_next_commands(service_factory: Any) -> None:
    from uniprot_link.mcp.facade import create_uniprot_mcp

    routes = [
        ('"PNKP"', _gene_hit("Q96T60", "PNKP_HUMAN")),
        ('"NAA10"', _gene_hit("P41227", "NAA10_HUMAN")),
    ]
    svc = service_factory(routes)
    service_adapters.set_sparql_service(svc)
    try:
        mcp = create_uniprot_mcp()
        result = await mcp.call_tool(
            "find_proteins_batch",
            {"gene_symbols": ["PNKP", "NAA10"], "organism_taxon": 9606, "reviewed": True},
        )
        payload = result.structured_content if hasattr(result, "structured_content") else result
        assert payload["success"] is True
        accs = {c["arguments"]["accession"] for c in payload["_meta"]["next_commands"]}
        assert {"Q96T60", "P41227"} <= accs
    finally:
        service_adapters.set_sparql_service(None)


@pytest.mark.asyncio
async def test_find_proteins_mnemonic_uses_single_query(service_factory: Any) -> None:
    """F3: an exact mnemonic anchor issues ONE bound query (no two-phase reviewed-first)."""
    data = make_select_json(
        ["protein", "mnemonic", "reviewed", "taxid", "organism"],
        [
            {
                "protein": "http://purl.uniprot.org/uniprot/P41227",
                "mnemonic": "NAA10_HUMAN",
                "reviewed": True,
                "taxid": "http://purl.uniprot.org/taxonomy/9606",
                "organism": "Homo sapiens",
            }
        ],
    )
    svc = service_factory([('up:mnemonic "NAA10_HUMAN"', data)])
    res = await svc.find_proteins(mnemonic="NAA10_HUMAN")
    assert res["count"] == 1
    assert res["proteins"][0]["accession"] == "P41227"
    # exactly one upstream call (no COUNT, no reviewed/unreviewed split)
    assert len(svc.client.calls) == 1


@pytest.mark.asyncio
async def test_find_proteins_surfaces_reviewed_count(service_factory: Any) -> None:
    """F9: a gene anchor (reviewed unset) carries reviewed_count + a TrEMBL hint."""
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
    svc = service_factory(
        [
            ("COUNT(DISTINCT ?protein)", count_body),
            ("up:reviewed true", reviewed),
            ("up:reviewed false", unreviewed),
        ]
    )
    res = await svc.find_proteins(gene="BRCA1", limit=25, offset=0)
    assert res["reviewed_count"] == 1
    assert res["proteins"][0]["accession"] == "P38398"
    assert "A0A1" in [p["accession"] for p in res["proteins"]]
    assert "reviewed_hint" in res  # page has unreviewed entries


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
