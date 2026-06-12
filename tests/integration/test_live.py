"""Integration tests against the live UniProt SPARQL endpoint.

Run with: `make test-integration` (or `pytest -m integration`). Skipped by the
default unit-test path. These confirm the query builders still match the live
data model and stay within timeouts.
"""

from __future__ import annotations

import pytest

from uniprot_link.api.client import SparqlClient
from uniprot_link.config import SparqlEndpointConfig
from uniprot_link.services.sparql_service import SparqlService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def service():  # type: ignore[no-untyped-def]
    config = SparqlEndpointConfig(timeout=40)
    client = SparqlClient(config)
    svc = SparqlService(client, config)
    yield svc
    await client.aclose()


async def test_get_protein_app(service: SparqlService) -> None:
    out = await service.get_protein("P05067")
    assert out["mnemonic"] == "A4_HUMAN"
    assert out["genes"] == ["APP"]
    assert out["sequence_length"] == 770


async def test_get_protein_bogus_is_not_found_live(service: SparqlService) -> None:
    from uniprot_link.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await service.get_protein("Q1ZZZ1")


async def test_features_bogus_is_not_found_live(service: SparqlService) -> None:
    from uniprot_link.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await service.get_features("Q1ZZZ1")


async def test_find_proteins_brca1(service: SparqlService) -> None:
    out = await service.find_proteins(gene="BRCA1", organism_taxon=9606, reviewed=True, limit=5)
    assert out["count"] >= 1
    assert any(p["accession"] == "P38398" for p in out["proteins"])


async def test_sequence_canonical(service: SparqlService) -> None:
    out = await service.get_sequence("P05067")
    assert out["canonical"]["length"] == 770
    # compact (default) returns a preview; the full string is in standard/full.
    assert out["canonical"]["sequence_preview"].startswith("MLPGLALL")
    full = await service.get_sequence("P05067", response_mode="standard")
    assert full["canonical"]["sequence"].startswith("MLPGLALL")


async def test_diseases_brca1(service: SparqlService) -> None:
    out = await service.get_diseases("P38398")
    assert out["count"] >= 1
    assert any("cancer" in (d.get("disease") or "").lower() for d in out["diseases"])


async def test_disease_carries_mim(service: SparqlService) -> None:
    res = await service.get_diseases("P38398")
    assert any(d.get("mim") for d in res["diseases"])


async def test_multiword_example_search_returns_hits(service: SparqlService) -> None:
    res = await service.search_examples("protein domain architecture", 25)
    assert res["count"] > 0


async def test_variants_brca1(service: SparqlService) -> None:
    out = await service.get_variants("P38398", limit=50)
    assert out["count"] >= 1
    assert all("begin" in v for v in out["variants"])


async def test_variants_have_populated_diseases(service: SparqlService) -> None:
    res = await service.get_variants("P38398", 200)
    assert any(v.get("diseases") for v in res["variants"])


async def test_variants_disease_only(service: SparqlService) -> None:
    res = await service.get_variants("P38398", 200, disease_associated_only=True)
    assert res["variants"]
    assert all(v["diseases"] for v in res["variants"])


async def test_features_domain_filter_matches_extent(service: SparqlService) -> None:
    res = await service.get_features("P38398", ["domain"])
    assert res["count"] >= 2
    assert all(f["type"] == "domain" for f in res["features"])


async def test_run_query_limit_injection(service: SparqlService) -> None:
    out = await service.run_query(
        "PREFIX up: <http://purl.uniprot.org/core/> SELECT ?t WHERE { ?t a up:Taxon }",
        limit=3,
    )
    assert out["query_type"] == "SELECT"
    assert out["row_count"] <= 3
    assert out["limit_injected"] is True


async def test_taxon_resolution(service: SparqlService) -> None:
    out = await service.get_taxon("9606", include_lineage=False)
    assert out["scientific_name"] == "Homo sapiens"


async def test_taxon_human_direct_parent_is_homo(service: SparqlService) -> None:
    res = await service.get_taxon("9606", include_lineage=True)
    assert res["parent_taxon_id"] == "9605"
    assert res["parent_name"] == "Homo"
    assert res["lineage"][0]["scientific_name"] == "Homo"
    assert res["lineage"][-1]["scientific_name"] in {"Eukaryota", "cellular organisms"}


async def test_example_catalog(service: SparqlService) -> None:
    found = await service.search_examples("disease", limit=3)
    assert found["count"] >= 1
    example_id = found["examples"][0]["example_id"]
    detail = await service.get_example(example_id)
    assert detail["query"]
    assert "SELECT" in detail["query"].upper() or "ASK" in detail["query"].upper()


async def test_go_terms_real_aspects(service: SparqlService) -> None:
    res = await service.get_go_terms("P38398")
    assert {"biological_process", "molecular_function", "cellular_component"} <= set(
        res["by_aspect"]
    )
    assert "unknown" not in res["by_aspect"]


async def test_variants_wildtype_and_notation(service: SparqlService) -> None:
    res = await service.get_variants("Q96T60", 200)
    by_pos = {v["begin"]: v for v in res["variants"]}
    assert by_pos[176]["wild_type"] == "L"
    assert by_pos[176]["notation"] == "L176F"
    assert by_pos[408]["variant_type"] == "other"
    assert "notation" not in by_pos[408]


async def test_run_query_rejects_writes(service: SparqlService) -> None:
    from uniprot_link.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError):
        await service.run_query("INSERT DATA { <a> <b> <c> }")


async def test_map_identifiers_is_focused(service: SparqlService) -> None:
    mapped = await service.map_identifiers("P38398")
    full = await service.get_cross_references("P38398")
    assert mapped["database_count"] <= full["database_count"]
    assert mapped["requested_databases"]


# --- v0.4.0 uplift live assertions -------------------------------------------


async def test_features_natural_variant_round_trips_live(service: SparqlService) -> None:
    # Bug 1: a type the dump emits must re-filter successfully.
    res = await service.get_features("Q96T60", ["natural_variant"])
    assert res["count"] >= 1
    assert all(f["type"] == "natural_variant" for f in res["features"])


async def test_features_unknown_type_returns_allowed_live(service: SparqlService) -> None:
    # Bug 2: the full vocabulary is in structured `allowed`, never truncated.
    from uniprot_link.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError) as exc:
        await service.get_features("Q96T60", ["definitely_not_a_type"])
    assert exc.value.allowed and "domain" in exc.value.allowed


async def test_sequence_compact_is_windowed_live(service: SparqlService) -> None:
    # Bug 6: compact returns a preview, standard the full string.
    compact = await service.get_sequence("P05067", response_mode="compact")
    assert "sequence" not in compact["canonical"]
    assert compact["canonical"]["sequence_truncated"] is True
    standard = await service.get_sequence("P05067", response_mode="standard")
    assert len(standard["canonical"]["sequence"]) == standard["canonical"]["length"]


async def test_taxon_by_name_has_timing_and_rank_live(service: SparqlService) -> None:
    # Bug 5: by-name parity (timing + rank present).
    res = await service.get_taxon("Homo sapiens")
    assert "elapsed_ms" in res and "cached" in res
    top = next((m for m in res["matches"] if m["taxon_id"] == "9606"), None)
    assert top is not None and top.get("rank")


async def test_diseases_have_distinct_definitions_live(service: SparqlService) -> None:
    # Bug 9: definition is the clinical text, distinct per disease.
    res = await service.get_diseases("Q96T60")
    defs = {d["disease"]: d.get("definition") for d in res["diseases"]}
    assert all(defs.values())  # every disease has a definition
    assert len(set(defs.values())) == len(defs)  # and they differ


async def test_go_terms_have_evidence_codes_live(service: SparqlService) -> None:
    # Bug 10: ECO/GO evidence present on at least one term.
    res = await service.get_go_terms("Q96T60")
    terms = [t for aspect in res["by_aspect"].values() for t in aspect]
    assert any(t.get("evidence_codes") for t in terms)


async def test_find_proteins_default_page_is_responsive_live(service: SparqlService) -> None:
    # Latency: the reviewed-first default page should be well under the old
    # 6-9s hotspot. Generous bound to tolerate endpoint variance.
    res = await service.find_proteins(keyword="KW-0007", limit=10)
    assert res["count"] >= 1
    assert res["elapsed_ms"] < 6000


async def test_find_proteins_reviewed_first_live(service: SparqlService) -> None:
    res = await service.find_proteins(gene="BRCA1", organism_taxon=9606, limit=5)
    assert any(p["accession"] == "P38398" for p in res["proteins"])
    assert res["proteins"][0]["reviewed"] is True


async def test_malformed_query_gives_actionable_error_live(service: SparqlService) -> None:
    # Bug 11: a malformed query yields query_syntax_error (detail or hint).
    from uniprot_link.exceptions import QuerySyntaxError

    with pytest.raises(QuerySyntaxError):
        await service.run_query("SELECT ?x WHERE { FILTER(")


async def test_example_search_has_no_duplicate_ids_live(service: SparqlService) -> None:
    # Bug 12: dedupe by example id.
    res = await service.search_examples("domain", limit=25)
    ids = [e["example_id"] for e in res["examples"]]
    assert len(ids) == len(set(ids))
