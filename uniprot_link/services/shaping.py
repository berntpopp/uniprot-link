"""Shape SPARQL-JSON result sets into compact, LLM-friendly payloads."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from uniprot_link.mcp.untrusted_content import (
    UntrustedText,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)
from uniprot_link.services.constants import (
    AVERAGE_RESIDUE_MASS,
    COMMON_XREF_DATABASES,
    ECO_TO_GO_CODE,
    GO_ASPECT_ROOTS,
    PREFIXES,
    WATER_MASS,
)
from uniprot_link.services.queries.validation import is_valid_accession

_UNTRUSTED_SOURCE = "uniprot"


def suggest_xref_database(name: str) -> str | None:
    """Best case-insensitive match for an unmatched xref database name, else ``None``.

    Cross-reference DB names are case-sensitive (``PDB``, ``AlphaFoldDB``); a case
    slip or near-miss (``alphafolddb``) is mapped to the canonical common-DB
    spelling so an unmatched filter can carry a did-you-mean (F2).
    """
    if not name:
        return None
    lowered = {db.lower(): db for db in COMMON_XREF_DATABASES}
    if name.lower() in lowered:
        return lowered[name.lower()]
    matches = difflib.get_close_matches(name.lower(), list(lowered), n=1, cutoff=0.7)
    return lowered[matches[0]] if matches else None


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


@dataclass(frozen=True)
class EntryStatus:
    """Three-state result of the entry_status probe (active / obsolete / absent)."""

    exists: bool
    obsolete: bool
    replaced_by: list[str]
    isoform_exists: bool | None


def shape_entry_status(result_json: dict[str, Any] | None, requested: str) -> EntryStatus:
    """Classify entry_status rows into active / obsolete / absent (+ isoform).

    ``isoform_exists`` is ``None`` unless the request carried a ``-N`` suffix.
    ``replaced_by`` collects every ``up:replacedBy`` accession (sorted, deduped) --
    a demerged entry can have more than one (verified live on A0A075B5G1).
    """
    data = rows(result_json)
    if not data:
        return EntryStatus(exists=False, obsolete=False, replaced_by=[], isoform_exists=None)
    obsolete = any(r.get("obsolete") is True for r in data)
    # up:replacedBy is unvalidated endpoint data. Keep ONLY strictly-valid UniProt
    # accessions: an invalid/hostile value is OMITTED, never surfaced as data or
    # spliced into a recovery next_commands argument (it would otherwise reach the
    # obsolete record + ObsoleteEntryError.replaced_by verbatim). Validate/omit is
    # required here -- sanitizing an executable recovery argument is not enough.
    replaced = sorted(
        {
            acc
            for r in data
            if r.get("replacedBy")
            and is_valid_accession(acc := accession_from_uri(r["replacedBy"]))
        }
    )
    iso: bool | None = None
    if "-" in requested:
        iso = any(r.get("isoform_exists") is True for r in data)
    return EntryStatus(exists=True, obsolete=obsolete, replaced_by=replaced, isoform_exists=iso)


def build_obsolete_record(
    accession: str, status: EntryStatus, summary: dict[str, Any] | None
) -> dict[str, Any]:
    """Build the flagged obsolete record returned by get_protein (F-OBS).

    Never fabricates sequence/function fields; carries only the sparse identity
    fields (mnemonic, reviewed) that survive on an obsolete entry, plus an
    explicit ``obsolete: true`` flag and any ``replaced_by`` accessions.
    """
    record: dict[str, Any] = {
        "accession": accession,
        "obsolete": True,
        "obsolete_reason": "demerged" if status.replaced_by else "deleted",
        "notice": (
            "This UniProtKB entry is obsolete and is not a live record. "
            + (
                f"It was demerged/replaced by: {', '.join(status.replaced_by)}."
                if status.replaced_by
                else "It was deleted and has no replacement entry."
            )
        ),
    }
    if status.replaced_by:
        record["replaced_by"] = status.replaced_by
    for key in ("mnemonic", "reviewed"):
        if summary and summary.get(key) is not None:
            record[key] = summary[key]
    return record


def shape_protein_summary(
    result_json: dict[str, Any] | None, accession: str
) -> dict[str, Any] | None:
    """Shape the single-row protein summary; ``None`` if no row.

    ``function`` is a curator-authored ``rdfs:comment`` free-text literal
    served verbatim by the SPARQL endpoint -- Response-Envelope Standard v1.1
    untrusted-content fencing: it is emitted as a typed ``untrusted_text``
    object (never a bare string) so a host never confuses retrieved prose
    with instructions.
    """
    data = rows(result_json)
    if not data:
        return None
    r = data[0]
    fenced_objects: list[UntrustedText] = []
    function_field: dict[str, Any] | None = None
    raw_function = r.get("function")
    # isinstance(str), not truthiness: fence even an empty "" function literal so
    # it is the typed object, never a bare "". Absent (None) stays omitted.
    if isinstance(raw_function, str):
        fenced = fence_untrusted_text(raw_function, source=_UNTRUSTED_SOURCE, record_id=accession)
        fenced_objects.append(fenced)
        function_field = fenced.model_dump(mode="json")
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
        "function": function_field,
        "created": r.get("created"),
        "modified": r.get("modified"),
    }
    cleaned = {k: v for k, v in summary.items() if v not in (None, [], "")}
    # Presence flags bypass the empty-value filter: an explicit ``False`` is
    # meaningful (the entry has no variants/diseases/structure) and drives
    # content-aware chaining.
    flags = {k: r[k] for k in ("has_variants", "has_diseases", "has_structure") if k in r}
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects)
    return {**cleaned, **flags}


def average_mass(sequence: str) -> int | None:
    """Average molecular mass (Da) from a residue sequence.

    Returns ``None`` if the sequence contains a residue with no defined average
    mass (e.g. ambiguous B/Z/X) rather than guessing.
    """
    if not sequence:
        return None
    total = WATER_MASS
    for residue in sequence:
        mass = AVERAGE_RESIDUE_MASS.get(residue)
        if mass is None:
            return None
        total += mass
    return round(total)


def shape_sequences(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape sequence rows; mark the canonical isoform (IRI ending in -1).

    UniProt asserts ``up:mass`` only on the canonical sequence, so a non-canonical
    isoform's mass is derived from its sequence (``mass_computed: True``) rather
    than left null.
    """
    out: list[dict[str, Any]] = []
    for row in rows(result_json):
        iso = row.get("isoform", "")
        mass = row.get("mass")
        seq = row.get("value")
        entry: dict[str, Any] = {
            "isoform": accession_from_uri(iso),
            "canonical": iso.endswith("-1"),
            "length": row.get("length"),
            "mass_da": mass,
            "sequence": seq,
        }
        if mass is None and seq:
            computed = average_mass(seq)
            if computed is not None:
                entry["mass_da"] = computed
                entry["mass_computed"] = True
        out.append(entry)
    out.sort(key=lambda s: (not s["canonical"], s["isoform"]))
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
    # Sort ids and database keys: QLever row order is not stable, so an unsorted
    # payload hurt diffing/caching and differed between cross_references and
    # map_identifiers for the same accession (F-SORT).
    return {db: sorted(ids) for db, ids in sorted(grouped.items())}


_XREF_COMPACT_ID_CAP = 25


def project_cross_references(grouped: dict[str, list[str]], *, mode: str) -> dict[str, Any]:
    """Project sorted, grouped xrefs for a response_mode (token economy, F-VERB).

    ``counts``/``total``/``database_count`` are always present. ``by_database`` (the
    grouped ids) is the primary collection and is ALWAYS returned so no mode
    silently empties it (Response-Envelope v1: ``minimal`` is "the mandatory
    envelope plus stable identifiers" -- the ids ARE those identifiers). ``minimal``
    and ``compact`` cap each database at ``_XREF_COMPACT_ID_CAP``; ``compact`` also
    reports ``truncated_databases`` so the cap is never silent; ``standard``/``full``
    return every id.
    """
    counts = {db: len(ids) for db, ids in grouped.items()}
    out: dict[str, Any] = {
        "database_count": len(grouped),
        "total": sum(counts.values()),
        "counts": counts,
    }
    if mode in ("standard", "full"):
        out["by_database"] = grouped
        out["has_more"] = False  # every id is returned uncapped
        return out
    # minimal / compact: cap each database. compact additionally flags the cap.
    capped: dict[str, list[str]] = {}
    truncated: dict[str, dict[str, int]] = {}
    for db, ids in grouped.items():
        if len(ids) > _XREF_COMPACT_ID_CAP:
            capped[db] = ids[:_XREF_COMPACT_ID_CAP]
            truncated[db] = {"returned": _XREF_COMPACT_ID_CAP, "total": len(ids)}
        else:
            capped[db] = ids
    out["by_database"] = capped
    # A capped view returns fewer ids than `total`; declare it so a client never
    # reads the partial id set as complete (Response-Envelope pagination honesty).
    # standard/full lift the cap.
    out["has_more"] = bool(truncated)
    if truncated and mode != "minimal":
        out["truncated_databases"] = truncated
    return out


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


def project_go_terms(
    grouped: dict[str, list[dict[str, Any]]],
    *,
    aspect: str | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    """Filter GO terms by aspect and cap the total; always report counts (F-VERB).

    ``count_by_aspect`` reflects the pre-cap totals (after any aspect filter) so a
    consumer always sees how many terms exist before deciding to widen ``limit``.
    """
    if aspect:
        grouped = {k: v for k, v in grouped.items() if k == aspect}
    count_by_aspect = {k: len(v) for k, v in grouped.items()}
    total = sum(count_by_aspect.values())
    out: dict[str, Any] = {}
    if limit and total > limit:
        remaining = limit
        capped: dict[str, list[dict[str, Any]]] = {}
        for k, terms in grouped.items():
            if remaining <= 0:
                break
            capped[k] = terms[:remaining]
            remaining -= len(capped[k])
        grouped = capped
        out["truncated"] = {
            "returned": limit,
            "total": total,
            "reason": f"limit {limit} reached",
            "recovery": "raise `limit` or filter by `aspect`.",
        }
    returned = sum(len(v) for v in grouped.values())
    out["count"] = returned if limit else total
    out["count_by_aspect"] = count_by_aspect
    out["by_aspect"] = grouped
    return out


# The curated SPARQL-example catalog is capped at 126 entries (see the tool's
# ``limit`` maximum); each entry carries one ``rdfs:comment`` description, so the
# object-count ceiling for the fenced list is that same 126.
_EXAMPLE_CATALOG_MAX = 126


def shape_example_list(result_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Shape example-catalog search rows: dedupe by id, rank native above federated.

    An example with >1 matching rdf:type previously produced duplicate rows
    (Bug 12). Here the first row per ``example_id`` wins, and UniProt-native
    examples are stably ranked before federated (Rhea/empty-keyword) ones.

    ``description`` is the example's ``rdfs:comment`` -- upstream free text served
    verbatim, so it is fenced into a typed ``untrusted_text`` object (never a bare
    string); ``record_id`` is the example IRI.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    fenced_objects: list[UntrustedText] = []
    for row in rows(result_json):
        ex = row.get("ex")
        if not ex or ex in seen:
            continue
        seen.add(ex)
        # Federated = not hosted on the UniProt example graph (e.g. Rhea); these
        # often carry empty keywords and are ranked below native examples.
        federated = not str(ex).startswith("https://sparql.uniprot.org/")
        description: dict[str, Any] | None = None
        raw_desc = row.get("desc")
        # isinstance(str), not truthiness: fence even an empty "" description.
        if isinstance(raw_desc, str):
            fenced = fence_untrusted_text(raw_desc, source=_UNTRUSTED_SOURCE, record_id=str(ex))
            fenced_objects.append(fenced)
            description = fenced.model_dump(mode="json")
        entry: dict[str, Any] = {
            "example_id": ex,
            "description": description,
            "query_type": local_name(row["qtype"]).replace("SPARQL", "").replace("Executable", "")
            if row.get("qtype")
            else None,
            "keywords": [k.strip() for k in str(row.get("keywords", "")).split(",") if k.strip()],
        }
        if federated:
            entry["federated"] = True
        out.append(entry)
    out.sort(key=lambda e: bool(e.get("federated")))  # stable: native first
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects, max_objects=_EXAMPLE_CATALOG_MAX)
    return out


def shape_example_detail(
    result_json: dict[str, Any] | None, example_iri: str
) -> dict[str, Any] | None:
    """Shape a single example's full query text and metadata.

    ``description`` is the example's ``rdfs:comment`` -- fenced into a typed
    ``untrusted_text`` object (``record_id`` = the example IRI). ``query`` is the
    executable SPARQL text (from ``sh:select``/``sh:ask``/``sh:construct``), not a
    comment, and is intentionally left as a raw string so it stays runnable.
    """
    data = rows(result_json)
    if not data:
        return None
    r = data[0]
    fenced_objects: list[UntrustedText] = []
    description: dict[str, Any] | None = None
    raw_comment = r.get("comment")
    # isinstance(str), not truthiness: fence even an empty "" comment.
    if isinstance(raw_comment, str):
        fenced = fence_untrusted_text(raw_comment, source=_UNTRUSTED_SOURCE, record_id=example_iri)
        fenced_objects.append(fenced)
        description = fenced.model_dump(mode="json")
    detail = {
        "description": description,
        "query": r.get("query"),
        "query_type": local_name(r["type"]).replace("SPARQL", "").replace("Executable", "")
        if r.get("type")
        else None,
        "keywords": [k.strip() for k in str(r.get("keywords", "")).split(",") if k.strip()],
        "federates_with": [
            f.strip() for f in str(r.get("federatesWith", "")).split(",") if f.strip()
        ],
    }
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects)
    return detail


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


# Feature/variant/disease annotation shapers live in a sibling module (600-line
# cap) and are re-exported here so callers keep using ``shaping.shape_features``
# etc. unchanged. Imported last, after the primitives above that the sibling
# depends on (mirrors the shaping_taxonomy split below).
from uniprot_link.services.shaping_annotations import (  # noqa: E402,F401
    shape_diseases,
    shape_features,
    shape_variants,
)

# Taxonomy shapers live in a sibling module (600-line cap) and are re-exported
# here so callers keep using ``shaping.shape_taxon_core`` / ``rank_taxon_matches``.
# Imported last, after the primitives above that the sibling depends on.
from uniprot_link.services.shaping_taxonomy import (  # noqa: E402,F401
    rank_taxon_matches,
    shape_ancestors,
    shape_taxon_core,
    shape_taxon_resolutions,
)
