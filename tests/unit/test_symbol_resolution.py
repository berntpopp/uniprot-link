"""Gene symbol in an accession slot resolves via find_proteins (router #319, Envelope 2b)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import make_select_json
from uniprot_link.mcp import service_adapters
from uniprot_link.mcp.facade import create_uniprot_mcp

_ACTIVE = make_select_json(["obsolete"], [{"obsolete": False}])
_SUMMARY = make_select_json(
    ["mnemonic", "reviewed", "fullName", "genes", "organism", "taxid", "length"],
    [
        {
            "mnemonic": "P53_HUMAN",
            "reviewed": True,
            "fullName": "Cellular tumor antigen p53",
            "genes": "TP53",
            "organism": "Homo sapiens",
            "taxid": "http://purl.uniprot.org/taxonomy/9606",
            "length": 393,
        }
    ],
)


def _hits(*entries: tuple[str, str, str]) -> dict[str, Any]:
    return make_select_json(
        ["protein", "mnemonic", "reviewed", "name"],
        [
            {
                "protein": f"http://purl.uniprot.org/uniprot/{a}",
                "mnemonic": m,
                "reviewed": True,
                "name": n,
            }
            for a, m, n in entries
        ],
    )


async def _call(svc: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    service_adapters.set_sparql_service(svc)
    try:
        result = await create_uniprot_mcp().call_tool(tool, args)
        return result.structured_content  # type: ignore[no-any-return]
    finally:
        service_adapters.set_sparql_service(None)


@pytest.mark.asyncio
async def test_get_protein_accepts_gene_symbol(service_factory: Any) -> None:
    """TP53 -> P04637 in ONE call, echoing resolved_from."""
    svc = service_factory(
        [
            ('skos:prefLabel "TP53"', _hits(("P04637", "P53_HUMAN", "Cellular tumor antigen p53"))),
            ("up:obsolete ?obsolete", _ACTIVE),
            ("up:recommendedName", _SUMMARY),
        ]
    )
    out = await _call(svc, "get_protein", {"accession": "TP53"})
    assert out["success"] is True
    assert out["result"]["accession"] == "P04637"
    assert out["result"]["resolved_from"] == {
        "input": "TP53",
        "form": "symbol",
        "resolved_to": "P04637",
    }
    # The resolution search is reviewed-only and human-scoped.
    search = next(q for q in svc.client.calls if 'prefLabel "TP53"' in q)
    assert "up:reviewed true" in search and "taxon:9606" in search


@pytest.mark.asyncio
async def test_accession_input_has_no_resolved_from(service_factory: Any) -> None:
    svc = service_factory([("up:obsolete ?obsolete", _ACTIVE), ("up:recommendedName", _SUMMARY)])
    out = await _call(svc, "get_protein", {"accession": "P04637"})
    assert out["success"] is True and "resolved_from" not in out["result"]
    assert not any("skos:altLabel" in q for q in svc.client.calls)


@pytest.mark.asyncio
async def test_ambiguous_symbol_returns_candidates(service_factory: Any) -> None:
    """Two reviewed exact matches -> ambiguous_query with candidates, never a guess."""
    svc = service_factory(
        [
            (
                'skos:prefLabel "CDKN2A"',
                _hits(
                    ("Q8N726", "ARF_HUMAN", "Tumor suppressor ARF"),
                    ("P42771", "CDN2A_HUMAN", "Cyclin-dependent kinase inhibitor 2A"),
                ),
            )
        ]
    )
    out = await _call(svc, "get_protein_features", {"accession": "CDKN2A"})
    assert out["success"] is False
    assert out["error_code"] == "ambiguous_query"
    assert out["field"] == "accession"
    assert {c["accession"] for c in out["candidates"]} == {"Q8N726", "P42771"}
    assert all(c["name"] for c in out["candidates"])
    assert "CDKN2A" not in out["message"]
    nxt = out["_meta"]["next_commands"]
    assert nxt[-1] == {"tool": "find_proteins", "arguments": {"gene_symbol": "CDKN2A"}}
    assert nxt[0]["tool"] == "get_protein_features"


@pytest.mark.asyncio
async def test_unknown_symbol_is_not_found_with_search(service_factory: Any) -> None:
    out = await _call(service_factory([]), "get_protein_go_terms", {"accession": "NOTAGENE1"})
    assert out["error_code"] == "not_found"
    assert out["candidates"] == []
    assert out["_meta"]["next_commands"] == [
        {"tool": "find_proteins", "arguments": {"gene_symbol": "NOTAGENE1"}}
    ]


@pytest.mark.asyncio
async def test_bad_shape_never_reaches_upstream(service_factory: Any) -> None:
    """A value that is neither an accession nor a symbol keeps the invalid_input path."""
    svc = service_factory([])
    out = await _call(svc, "get_protein", {"accession": 'TP53" } #'})
    assert out["error_code"] == "invalid_input"
    assert svc.client.calls == []
