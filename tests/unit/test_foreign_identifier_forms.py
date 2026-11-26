"""Gene ids from another namespace: resolved or named a converter (router #343, Envelope 2b)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.test_symbol_resolution import _ACTIVE, _SUMMARY, _call, _hits
from uniprot_link.services.queries.validation import foreign_gene_form

_KRAS = _hits(("P01116", "RASK_HUMAN", "GTPase KRas"))
_HGNC_XREF = "rdfs:seeAlso <http://purl.uniprot.org/hgnc/6407>"
_GENEID_XREF = "rdfs:seeAlso <http://purl.uniprot.org/geneid/3845>"
_SYMBOL_CALL = {"tool": "hgnc_resolve_symbol", "arguments": {"query": "ENSG00000133703"}}
_ENTREZ_CALL = {
    "tool": "hgnc_resolve_gene_by_xref",
    "arguments": {"source": "entrez_id", "value": "3845"},
}
_ACCESSION_TOOLS = [
    "get_protein",
    "get_protein_sequence",
    "get_protein_features",
    "get_protein_variants",
    "get_protein_diseases",
    "get_protein_cross_references",
    "get_protein_go_terms",
    "resolve_identifiers",
]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HGNC:6407", ("hgnc_id", "6407")),
        ("ncbigene:3845", ("ncbi_gene_id", "3845")),
        ("ENSG00000133703.15", ("ensembl_gene_id", "ENSG00000133703.15")),
        ("ENST00000311936", ("ensembl_other_id", "ENST00000311936")),
        ("ENSP00000256078", ("ensembl_other_id", "ENSP00000256078")),
        ("ENSMUSG00000030265", ("ensembl_other_id", "ENSMUSG00000030265")),
        ("NM_004985.5", ("refseq_accession", "NM_004985.5")),
        ("NG_007524", ("refseq_other_accession", "NG_007524")),
        ("XM_011520653.2", ("refseq_other_accession", "XM_011520653.2")),
        ("3845", ("bare_number", "3845")),
        # Leading zeros never reach the IRI; non-ASCII digits are not an id.
        ("HGNC:06407", ("hgnc_id", "6407")),
        ("HGNC:\uff16\uff14\uff10\uff17", ("malformed_id", "HGNC:\uff16\uff14\uff10\uff17")),
        ("\uff13\uff18\uff14\uff15", None),
        ("KRAS", None),
        ("P01116", None),
        ('HGNC:6407" } #', ("malformed_id", 'HGNC:6407" } #')),
    ],
)
def test_foreign_gene_form(value: str, expected: tuple[str, str] | None) -> None:
    assert foreign_gene_form(value) == expected


@pytest.mark.asyncio
async def test_find_proteins_resolves_hgnc_and_ncbi_ids(service_factory: Any) -> None:
    """Rule 1: UniProt carries these cross-references, so they resolve in the same query."""
    svc = service_factory([(_HGNC_XREF, _KRAS), (_GENEID_XREF, _KRAS)])
    for given, form in (("HGNC:6407", "hgnc_id"), ("NCBIGene:3845", "ncbi_gene_id")):
        args = {"gene_symbol": given, "organism_taxon": 9606, "reviewed": True}
        out = await _call(svc, "find_proteins", args)
        assert out["success"] is True and out["result"]["proteins"][0]["accession"] == "P01116"
        assert out["result"]["resolved_from"] == {
            "input": given,
            "form": form,
            "resolved_to": "P01116",
        }
    assert not any("skos:prefLabel" in q for q in svc.client.calls)


@pytest.mark.asyncio
async def test_find_proteins_ensembl_id_names_the_converter(service_factory: Any) -> None:
    """Rule 2: no silent empty, no upstream call, converter first."""
    svc = service_factory([])
    out = await _call(svc, "find_proteins", {"gene_symbol": "ENSG00000133703"})
    assert out["success"] is False and out["error_code"] == "invalid_input"
    assert out["field"] == "gene_symbol"
    assert "HGNC:6407" in out["allowed_values"] and out["hint"]
    assert "ENSG00000133703" not in out["message"]
    assert out["_meta"]["next_commands"] == [_SYMBOL_CALL]
    assert svc.client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args", "field"),
    [
        ("find_proteins", {"gene_symbol": "ENST00000311936"}, "gene_symbol"),
        ("find_proteins", {"gene_symbol": "ENSP00000256078"}, "gene_symbol"),
        ("find_proteins", {"gene_symbol": "ENSMUSG00000030265"}, "gene_symbol"),
        ("find_proteins", {"gene_symbol": "NG_007524"}, "gene_symbol"),
        ("find_proteins", {"gene_symbol": "HGNC:\uff16\uff14\uff10\uff17"}, "gene_symbol"),
        ("get_protein", {"accession": "ENST00000311936.8"}, "accession"),
    ],
)
async def test_transcript_id_names_no_converter(
    service_factory: Any, tool: str, args: dict[str, str], field: str
) -> None:
    """No fleet converter is guaranteed for a transcript id: say what it is, name none."""
    svc = service_factory([])
    out = await _call(svc, tool, args)
    assert out["error_code"] == "invalid_input" and out["field"] == field
    assert out["hint"] and "HGNC:6407" in out["allowed_values"]
    assert out["_meta"]["next_commands"] == [{"tool": "get_server_capabilities", "arguments": {}}]
    assert svc.client.calls == []


@pytest.mark.asyncio
async def test_batch_transcript_id_is_unsupported_without_converter(service_factory: Any) -> None:
    svc = service_factory([(_HGNC_XREF, _KRAS)])
    out = await _call(
        svc,
        "find_proteins_batch",
        {"gene_symbols": ["ENST00000311936", "HGNC:6407"], "reviewed": True},
    )
    assert out["success"] is True
    assert out["result"]["unresolved_reasons"] == {"ENST00000311936": "unsupported_identifier"}
    assert out["_meta"]["next_commands"] == [
        {"tool": "get_protein", "arguments": {"accession": "P01116"}}
    ]


@pytest.mark.asyncio
async def test_find_proteins_bare_number_without_hits_is_not_a_silent_empty(
    service_factory: Any,
) -> None:
    out = await _call(service_factory([]), "find_proteins", {"gene_symbol": "3845"})
    assert out["error_code"] == "invalid_input" and out["field"] == "gene_symbol"
    assert out["_meta"]["next_commands"] == [
        _ENTREZ_CALL,
        {"tool": "find_proteins", "arguments": {"gene_symbol": "NCBIGene:3845"}},
    ]


@pytest.mark.asyncio
async def test_bare_number_that_is_a_gene_name_still_matches(service_factory: Any) -> None:
    """Phage genes are numbered: a bare number that names a gene keeps working."""
    svc = service_factory([('skos:prefLabel "1"', _hits(("P00573", "RPOL_BPT7", "T7 RNAP")))])
    out = await _call(svc, "find_proteins", {"gene_symbol": "1", "reviewed": True})
    assert (
        out["success"] is True
        and out["result"]["count"] == 1
        and "resolved_from" not in out["result"]
    )
    assert "NCBIGene:<n>" in out["result"]["hint"]


@pytest.mark.asyncio
async def test_id_naming_several_reviewed_entries_resolves_to_none(service_factory: Any) -> None:
    """GNAS has four reviewed entries: no single resolved_to, in find and in the batch."""
    gnas = _hits(("P84996", "ALEX_HUMAN", "ALEX"), ("P63092", "GNAS2_HUMAN", "Gs alpha"))
    svc = service_factory([("rdfs:seeAlso <http://purl.uniprot.org/hgnc/4392>", gnas)])
    out = await _call(svc, "find_proteins", {"gene_symbol": "HGNC:4392", "reviewed": True})
    assert out["result"]["count"] == 2
    assert out["result"]["resolved_from"] == {"input": "HGNC:4392", "form": "hgnc_id"}
    out = await _call(svc, "find_proteins_batch", {"gene_symbols": ["HGNC:4392"], "reviewed": True})
    assert out["result"]["resolved_from"] == [{"input": "HGNC:4392", "form": "hgnc_id"}]


@pytest.mark.asyncio
async def test_leading_zeros_do_not_reach_the_query(service_factory: Any) -> None:
    svc = service_factory([(_HGNC_XREF, _KRAS)])
    out = await _call(svc, "find_proteins", {"gene_symbol": "HGNC:06407", "reviewed": True})
    assert out["result"]["count"] == 1 and out["result"]["resolved_from"]["resolved_to"] == "P01116"


@pytest.mark.asyncio
async def test_accession_in_gene_slot_without_hits_points_at_get_protein(
    service_factory: Any,
) -> None:
    out = await _call(service_factory([]), "find_proteins", {"gene_symbol": "p01116"})
    assert out["error_code"] == "invalid_input" and out["field"] == "gene_symbol"
    assert out["_meta"]["next_commands"] == [
        {"tool": "get_protein", "arguments": {"accession": "P01116"}}
    ]


@pytest.mark.asyncio
async def test_accession_shaped_symbol_with_hits_is_a_normal_result(service_factory: Any) -> None:
    svc = service_factory([('skos:prefLabel "P2RY10"', _hits(("O00398", "P2Y10_HUMAN", "P2Y10")))])
    out = await _call(svc, "find_proteins", {"gene_symbol": "P2RY10", "reviewed": True})
    assert out["success"] is True and out["result"]["count"] == 1 and "hint" not in out["result"]


@pytest.mark.asyncio
async def test_batch_next_commands_are_deduplicated_and_uncapped(service_factory: Any) -> None:
    svc = service_factory([(_HGNC_XREF, _KRAS), ('skos:prefLabel "KRAS"', _KRAS)])
    ensg = [f"ENSG{n:011d}" for n in range(1, 6)]
    out = await _call(
        svc,
        "find_proteins_batch",
        {"gene_symbols": ["KRAS", "HGNC:6407", *ensg], "reviewed": True},
    )
    nxt = out["_meta"]["next_commands"]
    assert [c["arguments"]["query"] for c in nxt[:5]] == ensg
    assert nxt[5:] == [{"tool": "get_protein", "arguments": {"accession": "P01116"}}]


@pytest.mark.asyncio
async def test_ambiguous_id_message_names_the_id(service_factory: Any) -> None:
    gnas = _hits(("P84996", "ALEX_HUMAN", "ALEX"), ("P63092", "GNAS2_HUMAN", "Gs alpha"))
    svc = service_factory([("rdfs:seeAlso <http://purl.uniprot.org/hgnc/4392>", gnas)])
    out = await _call(svc, "get_protein", {"accession": "HGNC:4392"})
    assert out["error_code"] == "ambiguous_query"
    assert out["message"].startswith("The gene symbol or gene id matches several")


@pytest.mark.asyncio
async def test_real_symbol_without_data_keeps_the_honest_empty(service_factory: Any) -> None:
    out = await _call(service_factory([]), "find_proteins", {"gene_symbol": "NOTAGENE1"})
    assert (
        out["success"] is True
        and out["result"]["count"] == 0
        and "resolved_from" not in out["result"]
    )


@pytest.mark.asyncio
async def test_batch_reports_a_reason_per_unresolved_item(service_factory: Any) -> None:
    svc = service_factory([(_HGNC_XREF, _KRAS)])
    out = await _call(
        svc,
        "find_proteins_batch",
        # reviewed=True: one query per gene (the mock answers every leg alike).
        {"gene_symbols": ["ENSG00000133703", "HGNC:6407", "3845", "NOTAGENE1"], "reviewed": True},
    )
    assert out["success"] is True
    assert out["result"]["resolved_genes"] == ["HGNC:6407"]
    assert out["result"]["by_gene"]["HGNC:6407"] == ["P01116"]
    assert out["result"]["resolved_from"] == [
        {"input": "HGNC:6407", "form": "hgnc_id", "resolved_to": "P01116"}
    ]
    assert out["result"]["unresolved_reasons"] == {
        "ENSG00000133703": "unsupported_identifier",
        "3845": "unsupported_identifier",
        "NOTAGENE1": "not_found",
    }
    assert "converters" not in out["result"]
    assert out["_meta"]["next_commands"] == [
        _SYMBOL_CALL,
        _ENTREZ_CALL,
        {"tool": "get_protein", "arguments": {"accession": "P01116"}},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _ACCESSION_TOOLS)
async def test_accession_slot_names_the_converter(service_factory: Any, tool: str) -> None:
    svc = service_factory([])
    out = await _call(svc, tool, {"accession": "ENSG00000133703"})
    assert out["error_code"] == "invalid_input" and out["field"] == "accession"
    assert out["allowed_values"][0].startswith("UniProtKB accession")
    assert out["_meta"]["next_commands"] == [_SYMBOL_CALL]
    assert svc.client.calls == []
    out = await _call(svc, tool, {"accession": "3845"})
    assert out["error_code"] == "invalid_input"
    assert out["_meta"]["next_commands"][0] == _ENTREZ_CALL


@pytest.mark.asyncio
async def test_accession_slot_resolves_an_hgnc_id(service_factory: Any) -> None:
    svc = service_factory(
        [(_HGNC_XREF, _KRAS), ("up:obsolete ?obsolete", _ACTIVE), ("up:recommendedName", _SUMMARY)]
    )
    out = await _call(svc, "get_protein", {"accession": "HGNC:6407"})
    assert out["success"] is True and out["result"]["accession"] == "P01116"
    assert out["result"]["resolved_from"] == {
        "input": "HGNC:6407",
        "form": "hgnc_id",
        "resolved_to": "P01116",
    }


@pytest.mark.asyncio
async def test_find_proteins_description_names_the_batch_tool() -> None:
    from uniprot_link.mcp.facade import create_uniprot_mcp

    tool = await create_uniprot_mcp().get_tool("find_proteins")
    rest = " ".join((tool.description or "").split()).split(". ", 1)[1]
    assert rest.startswith(
        "For 2 or more genes, call find_proteins_batch once instead of calling this tool per item."
    )


@pytest.mark.asyncio
async def test_batch_of_only_unsupported_ids_is_invalid_input_not_an_empty_success(
    service_factory: Any,
) -> None:
    """Nothing was looked up, so the batch answers as the single-gene tool does."""
    svc = service_factory([])
    out = await _call(
        svc, "find_proteins_batch", {"gene_symbols": ["ENSG00000133703", "ENST00000311936"]}
    )
    assert out["error_code"] == "invalid_input" and out["field"] == "gene_symbols"
    assert "HGNC:6407" in out["allowed_values"]
    assert out["_meta"]["next_commands"] == [
        {"tool": "hgnc_resolve_symbol", "arguments": {"query": "ENSG00000133703"}}
    ]
    assert svc.client.calls == []
