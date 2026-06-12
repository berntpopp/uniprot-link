"""Taxonomy result shapers (split from :mod:`shaping` for the 600-line cap).

Re-exported by :mod:`shaping`, so callers keep using ``shaping.shape_taxon_core``
etc. unchanged. Imports the shared primitives from :mod:`shaping`; that module
performs the re-export only after those primitives are defined, so the import
order is safe.
"""

from __future__ import annotations

from typing import Any

from uniprot_link.services.shaping import local_name, rows, taxid_from_uri


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


def rank_taxon_matches(matches: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Rank name-scan matches so the best (exact) hit is first (F3).

    Tiers (best first): exact scientific_name, exact common_name,
    scientific_name prefix, then substring. Within a tier, non-hybrids (no
    " x ") rank before hybrids, then shorter names, then alphabetical -- so a
    plain binomial ("Takifugu rubripes") wins over a hybrid or a virus that also
    contains the query. The endpoint's alphabetical ORDER BY otherwise buries the
    exact hit and the next_command chains to the wrong organism.
    """
    q = (query or "").strip().lower()

    def sort_key(match: dict[str, Any]) -> tuple[int, bool, int, str]:
        sci = (match.get("scientific_name") or "").lower()
        common = (match.get("common_name") or "").lower()
        if sci == q:
            tier = 0
        elif common == q:
            tier = 1
        elif sci.startswith(q):
            tier = 2
        else:
            tier = 3
        return (tier, " x " in sci, len(sci), sci)

    return sorted(matches, key=sort_key)
