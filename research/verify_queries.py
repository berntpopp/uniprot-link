"""Run every query builder against the live UniProt endpoint and report rows."""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uniprot_link.services import queries as q  # noqa: E402

ENDPOINT = "https://sparql.uniprot.org/sparql"


def run(query: str) -> tuple[int, object]:
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": "uniprot-link-verify/0.1 (mailto:bernt.popp@charite.de)",
        },
    )
    import time as _time

    started = _time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return exc.code, exc.read()[:200].decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__} after {_time.monotonic() - started:.1f}s"
    if "boolean" in payload:
        return 200, {"boolean": payload["boolean"]}
    rows = payload.get("results", {}).get("bindings", [])
    sample = {k: v["value"][:60] for k, v in rows[0].items()} if rows else {}
    return 200, {"rows": len(rows), "sample": sample}


CASES = {
    "find_proteins(gene=BRCA1, tax=9606)": q.find_proteins(gene="BRCA1", organism_taxon=9606),
    "find_proteins(keyword=KW-0005)": q.find_proteins(keyword="KW-0005", organism_taxon=9606),
    "find_proteins(ec=2.7.11.1)": q.find_proteins(ec_number="2.7.11.1", reviewed=True, limit=5),
    "protein_summary(P05067)": q.protein_summary("P05067"),
    "protein_sequence(P05067)": q.protein_sequence("P05067"),
    "protein_features(P05067, [disulfide_bond])": q.protein_features("P05067", ["disulfide_bond"]),
    "protein_variants(P38398)": q.protein_variants("P38398", limit=10),
    "protein_diseases(P38398)": q.protein_diseases("P38398"),
    "protein_cross_references(P05067, [PDB])": q.protein_cross_references("P05067", ["PDB"]),
    "protein_go_terms(P05067)": q.protein_go_terms("P05067"),
    "taxon_core(9606)": q.taxon_core(9606),
    "taxon_ancestors(9606)": q.taxon_ancestors(9606),
    "resolve_taxon_by_name(Homo sapiens)": q.resolve_taxon_by_name("Homo sapiens"),
    "search_example_queries(disease)": q.search_example_queries("disease", limit=5),
}


def main() -> None:
    example_iri = None
    for name, query in CASES.items():
        status, result = run(query)
        print(f"[{status}] {name}: {result}")
        if name.startswith("search_example_queries") and isinstance(result, dict):
            sample = result.get("sample", {})
            example_iri = sample.get("ex")
    # Resolve a full example IRI then test get_example_query.
    full = run(q.search_example_queries("disease", limit=1))[1]
    if isinstance(full, dict) and full.get("sample", {}).get("ex"):
        # sample is truncated to 60 chars; re-fetch untruncated IRI.
        raw = run(q.search_example_queries("disease", limit=1))
        print("note: example IRI (truncated sample):", full["sample"].get("ex"))
    if example_iri:
        status, result = run(q.get_example_query(example_iri))
        print(f"[{status}] get_example_query({example_iri}): {result}")


if __name__ == "__main__":
    main()
