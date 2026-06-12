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
        await service.get_protein("ZZZZZZ")


async def test_features_bogus_is_not_found_live(service: SparqlService) -> None:
    from uniprot_link.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await service.get_features("ZZZZZZ")


async def test_find_proteins_brca1(service: SparqlService) -> None:
    out = await service.find_proteins(gene="BRCA1", organism_taxon=9606, reviewed=True, limit=5)
    assert out["count"] >= 1
    assert any(p["accession"] == "P38398" for p in out["proteins"])


async def test_sequence_canonical(service: SparqlService) -> None:
    out = await service.get_sequence("P05067")
    assert out["canonical"]["length"] == 770
    assert out["canonical"]["sequence"].startswith("MLPGLALL")


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
