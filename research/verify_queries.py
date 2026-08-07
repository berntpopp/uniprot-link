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
RANGE_DATA_CASE = "protein_variants(P38398, range=100-200)"
RANGE_COUNT_CASE = "protein_variants_count(P38398, range=100-200)"
RANGE_LIMIT = 2


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
    elapsed_ms = round((_time.monotonic() - started) * 1000)
    if "boolean" in payload:
        return 200, {"boolean": payload["boolean"], "ms": elapsed_ms}
    rows = payload.get("results", {}).get("bindings", [])
    sample = {k: v["value"][:60] for k, v in rows[0].items()} if rows else {}
    return 200, {"rows": len(rows), "ms": elapsed_ms, "sample": sample}


CASES = {
    "find_proteins(gene=BRCA1, tax=9606)": q.find_proteins(gene="BRCA1", organism_taxon=9606),
    "find_proteins(keyword=KW-0005)": q.find_proteins(keyword="KW-0005", organism_taxon=9606),
    "find_proteins(ec=2.7.11.1)": q.find_proteins(ec_number="2.7.11.1", reviewed=True, limit=5),
    "entry_status(P05067 active)": q.entry_status("P05067"),
    "entry_status(Z9Z9Z9 obsolete)": q.entry_status("Z9Z9Z9"),
    "entry_status(A0A009K1D9 demerged)": q.entry_status("A0A009K1D9"),
    "entry_status(Q1ZZZ1 absent)": q.entry_status("Q1ZZZ1"),
    "entry_status(P05067-2 isoform)": q.entry_status("P05067-2"),
    "protein_summary(P05067 +flags)": q.protein_summary("P05067"),
    "protein_sequence(P05067)": q.protein_sequence("P05067"),
    "protein_features(P05067, [disulfide_bond])": q.protein_features("P05067", ["disulfide_bond"]),
    "protein_features(P05067, limit=5)": q.protein_features("P05067", limit=5),
    # F1: an isoform accession must anchor on the base entry (was a silent 0).
    "protein_features(P05067-2, [domain,region]) F1": q.protein_features(
        "P05067-2", ["domain", "region"]
    ),
    "protein_go_terms(P05067-2) F1-twin": q.protein_go_terms("P05067-2"),
    "protein_cross_references(P05067-2) F1-twin": q.protein_cross_references("P05067-2"),
    # F2: an isoform accession must return the full isoform set (base-anchored).
    "protein_sequence(P05067-2) F2": q.protein_sequence("P05067-2"),
    # F3: an exact mnemonic anchor is a single bound query (fast-path).
    "find_proteins(mnemonic=NAA10_HUMAN) F3": q.find_proteins(mnemonic="NAA10_HUMAN", limit=5),
    "protein_variants(P38398)": q.protein_variants("P38398", limit=10),
    "protein_variants_count(P38398)": q.protein_variants_count("P38398"),  # F5 true total
    RANGE_DATA_CASE: q.protein_variants(
        "P38398", limit=RANGE_LIMIT, position_start=100, position_end=200
    ),
    RANGE_COUNT_CASE: q.protein_variants_count("P38398", position_start=100, position_end=200),
    "find_proteins(tax=9606, name='polynucleotide kinase')": q.find_proteins(  # F6 per-word
        organism_taxon=9606, name_contains="polynucleotide kinase", limit=5
    ),
    "protein_diseases(P38398)": q.protein_diseases("P38398"),
    "protein_cross_references(P05067, [PDB])": q.protein_cross_references("P05067", ["PDB"]),
    "protein_go_terms(P05067)": q.protein_go_terms("P05067"),
    "taxon_core(9606)": q.taxon_core(9606),
    "taxon_ancestors(9606)": q.taxon_ancestors(9606),
    "resolve_taxon_by_name(Homo sapiens)": q.resolve_taxon_by_name("Homo sapiens"),
    "search_example_queries(disease)": q.search_example_queries("disease", limit=5),
}


def validate_range_results(outcomes: dict[str, tuple[int, object]]) -> list[str]:
    """Validate only the new required live range probes.

    Legacy cases remain observational because transient upstream failures in
    unrelated queries must not mask the bounded range gate.
    """
    errors: list[str] = []
    data_status, data_result = outcomes.get(RANGE_DATA_CASE, (0, None))
    count_status, count_result = outcomes.get(RANGE_COUNT_CASE, (0, None))
    if data_status != 200:
        errors.append(f"{RANGE_DATA_CASE} returned HTTP {data_status}")
    if count_status != 200:
        errors.append(f"{RANGE_COUNT_CASE} returned HTTP {count_status}")
    if errors:
        return errors
    if not isinstance(data_result, dict) or not isinstance(count_result, dict):
        return ["range verifier results were not structured dictionaries"]
    returned = data_result.get("rows")
    raw_total = (count_result.get("sample") or {}).get("n")
    try:
        total = int(raw_total)
    except (TypeError, ValueError):
        return ["filtered range count did not return an integer n"]
    if returned != RANGE_LIMIT:
        errors.append(
            f"filtered data returned {returned!r} rows; expected forced page limit {RANGE_LIMIT}"
        )
    if not isinstance(returned, int) or total <= returned:
        errors.append(f"filtered total {total} did not exceed returned page {returned!r}")
    return errors


def main() -> None:
    example_iri = None
    outcomes: dict[str, tuple[int, object]] = {}
    for name, query in CASES.items():
        status, result = run(query)
        outcomes[name] = (status, result)
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
    errors = validate_range_results(outcomes)
    if errors:
        raise SystemExit("range verification failed: " + "; ".join(errors))


if __name__ == "__main__":
    main()
