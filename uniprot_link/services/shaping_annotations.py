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


def shape_features(result_json: dict[str, Any] | None, accession: str) -> list[dict[str, Any]]:
    """Shape feature rows; emit only filterable `type` keys (Bug 1).

    A class in the registry round-trips into the feature_types filter. Any class
    absent from the registry is emitted as ``_unmapped:<Class>`` so it is
    *visibly* non-filterable rather than presenting a friendly key that the
    filter would then reject.
    """
    out: list[dict[str, Any]] = []
    fenced_objects: list[UntrustedText] = []
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
        if raw_comment:
            fenced = fence_untrusted_text(
                str(raw_comment),
                source=_UNTRUSTED_SOURCE,
                record_id=f"{accession}#feature:{i}",
            )
            fenced_objects.append(fenced)
            description = fenced.model_dump(mode="json")
        out.append(
            {
                "type": key,
                "begin": row.get("begin"),
                "end": row.get("end"),
                "description": description,
            }
        )
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects)
    return out


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
        if raw_description:
            fenced = fence_untrusted_text(
                str(raw_description),
                source=_UNTRUSTED_SOURCE,
                record_id=f"{accession}#variant:{i}",
            )
            fenced_objects.append(fenced)
            variant["description"] = fenced.model_dump(mode="json")
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects)
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
    replaced by this pair (Bug 9). ``involvement`` is fenced into a typed
    ``untrusted_text`` object. ``definition`` is out of scope for this fence per
    the inventory row (evidence names only the annotation ``rdfs:comment``, not
    the disease vocabulary's own comment).
    """
    out: list[dict[str, Any]] = []
    fenced_objects: list[UntrustedText] = []
    for i, row in enumerate(rows(result_json)):
        involvement: dict[str, Any] | None = None
        raw_involvement = row.get("comment")
        if raw_involvement:
            fenced = fence_untrusted_text(
                str(raw_involvement),
                source=_UNTRUSTED_SOURCE,
                record_id=f"{accession}#disease:{i}",
            )
            fenced_objects.append(fenced)
            involvement = fenced.model_dump(mode="json")
        disease = {
            "disease": row.get("diseaseLabel"),
            "disease_id": local_name(row["disease"]) if row.get("disease") else None,
            "mnemonic": row.get("mnemonic"),
            "mim": local_name(row["mim"]) if row.get("mim") else None,
            "definition": row.get("definition"),
            "involvement": involvement,
        }
        out.append({k: v for k, v in disease.items() if v not in (None, "")})
    if fenced_objects:
        enforce_untrusted_text_limits(fenced_objects)
    return out
