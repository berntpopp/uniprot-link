"""Feature/variant/disease annotation shapers (split from :mod:`shaping` for the
600-line cap).

Re-exported by :mod:`shaping`, so callers keep using ``shaping.shape_features``
etc. unchanged. Imports the shared primitives from :mod:`shaping`; that module
performs the re-export only after those primitives are defined, so the import
order is safe.

``description``/``involvement`` fields here are curator-authored
``rdfs:comment`` free-text literals served verbatim by the UniProt SPARQL
endpoint -- Response-Envelope Standard v1.1 untrusted-content fencing: each is
emitted as a typed ``untrusted_text`` object (never a bare string) so a host
never confuses retrieved prose with instructions.
"""

from __future__ import annotations

from typing import Any

from uniprot_link.mcp.untrusted_content import (
    UntrustedText,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)
from uniprot_link.services.constants import FEATURE_CLASS_TO_KEY
from uniprot_link.services.shaping import local_name, rows

_UNTRUSTED_SOURCE = "uniprot"

# These three shapers return uncapped embedded lists: a large protein (TTN, TP53,
# BRCA1) legitimately carries well over the v1.1 default 128-object ceiling of
# description-bearing feature/variant/disease annotations. Enforcing the default
# max_objects here would raise UntrustedTextLimitError on a real query, so we lift
# the count ceiling to a generous 10000; the per-object 2 MiB and 8 MiB total byte
# limits remain the real DoS backstop (10000 real descriptions hit 8 MiB first).
_MAX_UNTRUSTED_OBJECTS = 10_000

_ANNOTATION_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "features": {
        "compact": ("type", "begin", "end"),
        "minimal": ("type", "begin", "end"),
    },
    "variants": {
        "compact": (
            "begin",
            "end",
            "wild_type",
            "substitution",
            "notation",
            "variant_type",
            "diseases",
            "dbsnp",
        ),
        "minimal": ("begin", "end", "notation", "variant_type", "dbsnp"),
    },
    "diseases": {
        "compact": ("disease", "disease_id", "mnemonic", "mim"),
        "minimal": ("disease", "disease_id", "mim"),
    },
}


def project_annotation_records(
    records: list[dict[str, Any]], *, kind: str, mode: str
) -> list[dict[str, Any]]:
    """Project high-volume annotations without dropping their stable record identity.

    ``standard`` and ``full`` retain the prior complete records. ``compact``
    removes only fenced curator prose (and its repeated provenance/hash frame);
    ``minimal`` retains each record's position or stable identifiers so it cannot
    turn a non-empty result into a misleading empty list.
    """
    if mode in {"standard", "full"}:
        return records
    fields = _ANNOTATION_FIELDS[kind][mode]
    return [
        {field: value for field, value in record.items() if field in fields} for record in records
    ]


def shape_features(result_json: dict[str, Any] | None, accession: str) -> list[dict[str, Any]]:
    """Shape feature rows; emit only filterable `type` keys (Bug 1).

    A class in the registry round-trips into the feature_types filter. Any class
    absent from the registry is emitted as ``_unmapped:<Class>`` so it is
    *visibly* non-filterable rather than presenting a friendly key that the
    filter would then reject.

    ``description`` (curator ``rdfs:comment``) is fenced into a typed
    ``untrusted_text`` object. Limit enforcement is deferred to the service via
    :func:`enforce_emitted_feature_limits`, which runs AFTER secondary-structure
    hiding and the display slice -- so ceilings bind the returned subset, not
    features that are fetched but never emitted.
    """
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows(result_json)):
        cls = local_name(row["type"]) if row.get("type") else None
        key: str | None
        if cls is None:
            key = None
        else:
            mapped = FEATURE_CLASS_TO_KEY.get(cls)
            key = mapped if mapped is not None else f"_unmapped:{cls.replace('_Annotation', '')}"
        description: dict[str, Any] | None = None
        raw_comment = row.get("comment")
        # isinstance(str), not truthiness: fence even an empty "" comment.
        if isinstance(raw_comment, str):
            description = fence_untrusted_text(
                raw_comment,
                source=_UNTRUSTED_SOURCE,
                record_id=f"{accession}#feature:{i}",
            ).model_dump(mode="json")
        out.append(
            {
                "type": key,
                "begin": row.get("begin"),
                "end": row.get("end"),
                "description": description,
            }
        )
    return out


def enforce_emitted_feature_limits(features: list[dict[str, Any]]) -> None:
    """Enforce v1.1 untrusted-text ceilings over the EMITTED features only.

    ``get_protein_features`` fetches up to a cap, hides secondary structure, then
    slices to the display limit. Enforcing over every fetched/fenced description
    (as done at shaping time) could raise ``UntrustedTextLimitError`` on
    annotations that are dropped and never returned. Callers pass the final
    emitted feature list so the ceilings bind exactly what the response contains.
    """
    emitted = [
        UntrustedText.model_validate(f["description"])
        for f in features
        if isinstance(f.get("description"), dict)
    ]
    if emitted:
        enforce_untrusted_text_limits(emitted, max_objects=_MAX_UNTRUSTED_OBJECTS)


def shape_variants(result_json: dict[str, Any] | None, accession: str) -> list[dict[str, Any]]:
    """Shape natural-variant rows, merging rows that differ only by disease.

    ``description`` is fenced into a typed ``untrusted_text`` object once the
    final (merged, sorted) variant order is known, so ``record_id`` reflects
    the returned array position.
    """
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
    fenced_objects: list[UntrustedText] = []
    for i, variant in enumerate(out):
        raw_description = variant.get("description")
        # Guard on isinstance(str), not truthiness: a present-but-empty upstream
        # comment ("") is still external text and MUST be the typed object with
        # its raw digest, never a bare "". Absent (None) stays null per the schema.
        if isinstance(raw_description, str):
            fenced = fence_untrusted_text(
                raw_description,
                source=_UNTRUSTED_SOURCE,
                record_id=f"{accession}#variant:{i}",
            )
            fenced_objects.append(fenced)
            variant["description"] = fenced.model_dump(mode="json")
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects, max_objects=_MAX_UNTRUSTED_OBJECTS)
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


def shape_diseases(result_json: dict[str, Any] | None, accession: str) -> list[dict[str, Any]]:
    """Shape disease-annotation rows.

    ``definition`` is the disease's clinical definition (disease ``rdfs:comment``);
    ``involvement`` is the entry-specific note (annotation ``rdfs:comment``). The
    old single ``description`` (which carried only the involvement boilerplate) is
    replaced by this pair (Bug 9). BOTH are curator-authored ``rdfs:comment``
    free-text served verbatim by the endpoint, so BOTH are fenced into typed
    ``untrusted_text`` objects (never a bare string) -- fence every rdfs:comment
    surface we serve. ``record_id`` identifies the disease record; the JSON key
    (definition vs involvement) distinguishes the two comment sources.
    """
    out: list[dict[str, Any]] = []
    fenced_objects: list[UntrustedText] = []
    for i, row in enumerate(rows(result_json)):
        record_id = f"{accession}#disease:{i}"
        definition = _fence_comment(row.get("definition"), record_id, fenced_objects)
        involvement = _fence_comment(row.get("comment"), record_id, fenced_objects)
        disease = {
            "disease": row.get("diseaseLabel"),
            "disease_id": local_name(row["disease"]) if row.get("disease") else None,
            "mnemonic": row.get("mnemonic"),
            "mim": local_name(row["mim"]) if row.get("mim") else None,
            "definition": definition,
            "involvement": involvement,
        }
        out.append({k: v for k, v in disease.items() if v not in (None, "")})
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects, max_objects=_MAX_UNTRUSTED_OBJECTS)
    return out


def _fence_comment(raw: Any, record_id: str, sink: list[UntrustedText]) -> dict[str, Any] | None:
    """Fence one optional rdfs:comment literal, appending it to ``sink``.

    Guards on ``isinstance(str)``, not truthiness: a present-but-empty upstream
    comment ("") is still external text and is returned as the typed object with
    its raw digest. Only an absent field (``None``) returns ``None`` (null/absent
    per the schema).
    """
    if not isinstance(raw, str):
        return None
    fenced = fence_untrusted_text(raw, source=_UNTRUSTED_SOURCE, record_id=record_id)
    sink.append(fenced)
    return fenced.model_dump(mode="json")
