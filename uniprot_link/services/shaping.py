"""Shape SPARQL-JSON result sets into compact, LLM-friendly payloads."""

from __future__ import annotations

from typing import Any

from uniprot_link.services.constants import (
    ECO_TO_GO_CODE,
    FEATURE_CLASS_TO_KEY,
    GO_ASPECT_ROOTS,
    PREFIXES,
)

_UNIPROT_ACC_PREFIXES = (
    "http://purl.uniprot.org/uniprot/",
    "http://purl.uniprot.org/isoforms/",
)
_INT_DATATYPES = {
    "http://www.w3.org/2001/XMLSchema#int",
    "http://www.w3.org/2001/XMLSchema#integer",
    "http://www.w3.org/2001/XMLSchema#long",
    "http://www.w3.org/2001/XMLSchema#nonNegativeInteger",
}
_BOOL_DATATYPE = "http://www.w3.org/2001/XMLSchema#boolean"


def _coerce(binding: dict[str, Any]) -> Any:
    """Coerce a single SPARQL binding value to a Python scalar."""
    value = binding.get("value", "")
    datatype = binding.get("datatype")
    if datatype == _BOOL_DATATYPE:
        return value == "true"
    if datatype in _INT_DATATYPES:
        try:
            return int(value)
        except ValueError:
            return value
    return value


def rows(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return SELECT bindings as a list of ``{var: scalar}`` dicts."""
    if not result_json:
        return []
    bindings = result_json.get("results", {}).get("bindings", [])
    return [{var: _coerce(cell) for var, cell in row.items()} for row in bindings]


def accession_from_uri(uri: str) -> str:
    """Extract a UniProt accession from an entry/isoform IRI."""
    for prefix in _UNIPROT_ACC_PREFIXES:
        if uri.startswith(prefix):
            return uri[len(prefix) :]
    return uri.rsplit("/", 1)[-1]


def taxid_from_uri(uri: str) -> str:
    """Extract an NCBI taxon id from a taxonomy IRI."""
    return uri.rsplit("/", 1)[-1]


def fold_curie(uri: str) -> str:
    """Fold a full IRI into a ``prefix:local`` CURIE when a prefix matches."""
    for short, full in PREFIXES.items():
        if uri.startswith(full):
            return f"{short}:{uri[len(full) :]}"
    return uri


def local_name(uri: str) -> str:
    """Return the local part of an IRI (after the last / or #)."""
    return uri.replace("#", "/").rsplit("/", 1)[-1]


def shape_find_proteins(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape find_proteins rows into entry summaries."""
    out: list[dict[str, Any]] = []
    for row in rows(result_json):
        out.append(
            {
                "accession": accession_from_uri(row.get("protein", "")),
                "mnemonic": row.get("mnemonic"),
                "name": row.get("name"),
                "reviewed": row.get("reviewed"),
                "organism": row.get("organism"),
                "taxon_id": taxid_from_uri(row.get("taxid", "")) if row.get("taxid") else None,
            }
        )
    return out


def shape_protein_summary(result_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shape the single-row protein summary; ``None`` if no row."""
    data = rows(result_json)
    if not data:
        return None
    r = data[0]
    summary: dict[str, Any] = {
        "mnemonic": r.get("mnemonic"),
        "reviewed": r.get("reviewed"),
        "recommended_name": r.get("fullName"),
        "short_name": r.get("shortName"),
        "genes": [g.strip() for g in str(r.get("genes", "")).split(",") if g.strip()],
        "organism": r.get("organism"),
        "common_name": r.get("commonName"),
        "taxon_id": taxid_from_uri(r.get("taxid", "")) if r.get("taxid") else None,
        "sequence_length": r.get("length"),
        "mass_da": r.get("mass"),
        "protein_existence": local_name(r["existence"]) if r.get("existence") else None,
        "function": r.get("function"),
        "created": r.get("created"),
        "modified": r.get("modified"),
    }
    return {k: v for k, v in summary.items() if v not in (None, [], "")}


def shape_sequences(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape sequence rows; mark the canonical isoform (IRI ending in -1)."""
    out: list[dict[str, Any]] = []
    for row in rows(result_json):
        iso = row.get("isoform", "")
        out.append(
            {
                "isoform": accession_from_uri(iso),
                "canonical": iso.endswith("-1"),
                "length": row.get("length"),
                "mass_da": row.get("mass"),
                "sequence": row.get("value"),
            }
        )
    out.sort(key=lambda s: (not s["canonical"], s["isoform"]))
    return out


def shape_features(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape feature rows; emit only filterable `type` keys (Bug 1).

    A class in the registry round-trips into the feature_types filter. Any class
    absent from the registry is emitted as ``_unmapped:<Class>`` so it is
    *visibly* non-filterable rather than presenting a friendly key that the
    filter would then reject.
    """
    out: list[dict[str, Any]] = []
    for row in rows(result_json):
        cls = local_name(row["type"]) if row.get("type") else None
        key: str | None
        if cls is None:
            key = None
        else:
            mapped = FEATURE_CLASS_TO_KEY.get(cls)
            key = mapped if mapped is not None else f"_unmapped:{cls.replace('_Annotation', '')}"
        out.append(
            {
                "type": key,
                "begin": row.get("begin"),
                "end": row.get("end"),
                "description": row.get("comment"),
            }
        )
    return out


def shape_variants(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape natural-variant rows, merging rows that differ only by disease."""
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for row in rows(result_json):
        key = (row.get("begin"), row.get("end"), row.get("substitution"))
        entry = merged.setdefault(
            key,
            {
                "begin": row.get("begin"),
                "end": row.get("end"),
                "wild_type": row.get("wildType") or None,
                "substitution": row.get("substitution") or None,
                "description": row.get("comment"),
                "diseases": [],
            },
        )
        disease = row.get("disease")
        if disease and disease not in entry["diseases"]:
            entry["diseases"].append(disease)
        dbsnp = row.get("dbsnp")
        if dbsnp and "dbsnp" not in entry:
            entry["dbsnp"] = local_name(dbsnp)
    out = [_classify_variant(v) for v in merged.values()]
    out.sort(
        key=lambda v: (
            not v["diseases"],
            v["begin"] is None,
            v["begin"] if isinstance(v["begin"], int) else 0,
        )
    )
    return out


def _classify_variant(v: dict[str, Any]) -> dict[str, Any]:
    """Add variant_type and (for simple substitutions) HGVS-style notation."""
    sub, wt, begin, end = v.get("substitution"), v.get("wild_type"), v.get("begin"), v.get("end")
    is_substitution = isinstance(sub, str) and len(sub) == 1 and begin == end and begin is not None
    v["variant_type"] = "substitution" if is_substitution else "other"
    if is_substitution and wt:
        v["notation"] = f"{wt}{begin}{sub}"
    if v.get("wild_type") is None:
        v.pop("wild_type", None)
    # Omit an absent/empty substitution rather than emit "" (C6): an empty string
    # reads as "substitutes to nothing"; absence + variant_type:"other" is clear.
    if not v.get("substitution"):
        v.pop("substitution", None)
    return v


def shape_diseases(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape disease-annotation rows.

    ``definition`` is the disease's clinical definition (disease ``rdfs:comment``);
    ``involvement`` is the entry-specific note (annotation ``rdfs:comment``). The
    old single ``description`` (which carried only the involvement boilerplate) is
    replaced by this pair (Bug 9).
    """
    out: list[dict[str, Any]] = []
    for row in rows(result_json):
        disease = {
            "disease": row.get("diseaseLabel"),
            "disease_id": local_name(row["disease"]) if row.get("disease") else None,
            "mnemonic": row.get("mnemonic"),
            "mim": local_name(row["mim"]) if row.get("mim") else None,
            "definition": row.get("definition"),
            "involvement": row.get("comment"),
        }
        out.append({k: v for k, v in disease.items() if v not in (None, "")})
    return out


def shape_cross_references(
    result_json: dict[str, Any] | None, *, short: bool = True
) -> dict[str, list[str]]:
    """Group cross-references by database short name.

    ``short=True`` returns the local id (e.g. ``1AAP``); ``short=False`` keeps the
    full xref IRI (use response_mode='full' for the raw IRIs)."""
    grouped: dict[str, list[str]] = {}
    for row in rows(result_json):
        db = row.get("database") or local_name(row.get("db", ""))
        xref = row.get("xref", "")
        grouped.setdefault(db, []).append(local_name(xref) if short else xref)
    return grouped


def shape_go_terms(result_json: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Group GO annotations into biological_process / molecular_function /
    cellular_component via their top-level root class.

    Evidence arrives one row per (term, ECO) — it is aggregated here rather than
    via SPARQL GROUP_CONCAT (a QLever sharp edge over the reified OPTIONAL). Each
    term gains ``evidence`` (ECO ids) and ``evidence_codes`` (mapped GO codes)
    when any evidence is present.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, dict[str, Any]] = {}  # go id -> term dict (merge across rows)
    for row in rows(result_json):
        go = row.get("go", "")
        go_id = local_name(go).replace("GO_", "GO:")
        root = local_name(row["aspect"]) if row.get("aspect") else ""
        bucket = GO_ASPECT_ROOTS.get(root, "unknown")
        term = seen.get(go_id)
        if term is None:
            term = {"id": go_id, "label": row.get("label"), "_eco": []}
            seen[go_id] = term
            grouped.setdefault(bucket, []).append(term)
        eco = row.get("eco")
        if eco:
            eco_id = local_name(eco)  # e.g. ECO_0000314
            if eco_id not in term["_eco"]:
                term["_eco"].append(eco_id)
    # Finalise: turn the accumulator into public evidence fields.
    for term in seen.values():
        eco_ids: list[str] = term.pop("_eco")
        if eco_ids:
            term["evidence"] = [e.replace("ECO_", "ECO:") for e in eco_ids]
            codes = [ECO_TO_GO_CODE[e] for e in eco_ids if e in ECO_TO_GO_CODE]
            if codes:
                term["evidence_codes"] = sorted(set(codes))
    return grouped


def shape_taxon_core(result_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shape a taxon's own attributes; ``None`` if the taxon does not exist."""
    data = rows(result_json)
    if not data or not data[0].get("scientificName"):
        return None
    r = data[0]
    core: dict[str, Any] = {
        "scientific_name": r.get("scientificName"),
        "common_name": r.get("commonName"),
        "rank": local_name(r["rank"]).replace("Taxonomic_Rank_", "") if r.get("rank") else None,
    }
    return {k: v for k, v in core.items() if v not in (None, "")}


def _ancestor(r: dict[str, Any]) -> dict[str, Any]:
    """Shape one ancestor row (taxon_id, scientific_name, rank)."""
    a = {
        "taxon_id": taxid_from_uri(r.get("ancestor", "")),
        "scientific_name": r.get("name"),
        "rank": local_name(r["rank"]).replace("Taxonomic_Rank_", "") if r.get("rank") else None,
    }
    return {k: v for k, v in a.items() if v not in (None, "")}


def shape_ancestors(
    result_json: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return ``(direct_parent, lineage)`` ordered species->root from depth rows."""
    data = sorted(
        rows(result_json),
        key=lambda r: r.get("depth", 0) if isinstance(r.get("depth"), int) else 0,
    )
    lineage = [_ancestor(r) for r in data]
    parent = lineage[0] if lineage else None
    return parent, lineage


def shape_taxon_resolutions(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape taxon name-resolution rows (parity with by-id: includes rank)."""
    out: list[dict[str, Any]] = []
    for row in rows(result_json):
        match: dict[str, Any] = {
            "taxon_id": taxid_from_uri(row.get("taxon", "")),
            "scientific_name": row.get("scientificName"),
            "common_name": row.get("commonName"),
            "rank": local_name(row["rank"]).replace("Taxonomic_Rank_", "")
            if row.get("rank")
            else None,
        }
        out.append({k: v for k, v in match.items() if v not in (None, "")})
    return out


def shape_example_list(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape example-catalog search rows: dedupe by id, rank native above federated.

    An example with >1 matching rdf:type previously produced duplicate rows
    (Bug 12). Here the first row per ``example_id`` wins, and UniProt-native
    examples are stably ranked before federated (Rhea/empty-keyword) ones.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows(result_json):
        ex = row.get("ex")
        if not ex or ex in seen:
            continue
        seen.add(ex)
        # Federated = not hosted on the UniProt example graph (e.g. Rhea); these
        # often carry empty keywords and are ranked below native examples.
        federated = not str(ex).startswith("https://sparql.uniprot.org/")
        entry: dict[str, Any] = {
            "example_id": ex,
            "description": row.get("desc"),
            "query_type": local_name(row["qtype"]).replace("SPARQL", "").replace("Executable", "")
            if row.get("qtype")
            else None,
            "keywords": [k.strip() for k in str(row.get("keywords", "")).split(",") if k.strip()],
        }
        if federated:
            entry["federated"] = True
        out.append(entry)
    out.sort(key=lambda e: bool(e.get("federated")))  # stable: native first
    return out


def shape_example_detail(result_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """Shape a single example's full query text and metadata."""
    data = rows(result_json)
    if not data:
        return None
    r = data[0]
    return {
        "description": r.get("comment"),
        "query": r.get("query"),
        "query_type": local_name(r["type"]).replace("SPARQL", "").replace("Executable", "")
        if r.get("type")
        else None,
        "keywords": [k.strip() for k in str(r.get("keywords", "")).split(",") if k.strip()],
        "federates_with": [
            f.strip() for f in str(r.get("federatesWith", "")).split(",") if f.strip()
        ],
    }


RESPONSE_MODES = ("minimal", "compact", "standard", "full")

# Fields dropped per (kind, mode). 'standard'/'full' keep everything.
_MODE_DROP: dict[tuple[str, str], set[str]] = {
    ("protein", "minimal"): {"function", "created", "modified", "short_name", "common_name"},
    ("protein", "compact"): {"created", "modified"},
}


def apply_response_mode(payload: dict[str, Any], mode: str, *, kind: str) -> dict[str, Any]:
    """Project a payload for a response_mode. 'standard'/'full' are identity."""
    if mode in ("standard", "full"):
        return payload
    drop = _MODE_DROP.get((kind, mode), set())
    return {k: v for k, v in payload.items() if k not in drop}
