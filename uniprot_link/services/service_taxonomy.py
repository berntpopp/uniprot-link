"""Taxonomy resolution for the SPARQL service (split for the 600-line cap).

``SparqlService`` mixes this in, so ``get_taxon`` keeps using the shared
``ServiceBase`` primitives (``self._select_timed`` / ``self._select``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from uniprot_link.exceptions import NotFoundError
from uniprot_link.services import queries as Q
from uniprot_link.services.constants import lookup_common_taxon
from uniprot_link.services.service_base import ServiceBase
from uniprot_link.services.shaping_taxonomy import (
    rank_taxon_matches,
    shape_ancestors,
    shape_taxon_core,
    shape_taxon_resolutions,
)


class TaxonomyServiceMixin(ServiceBase):
    """The ``get_taxon`` resolver (by id, curated common name, or endpoint scan)."""

    async def get_taxon(self, taxon: str, include_lineage: bool = False) -> dict[str, Any]:
        """Resolve a taxon by id (digits) or scientific/common name."""
        taxon = str(taxon).strip()
        if taxon.isdigit():
            (core_json, core_m), (anc_json, anc_m) = await asyncio.gather(
                self._select_timed(Q.taxon_core(taxon)),
                self._select_timed(Q.taxon_ancestors(taxon)),
            )
            core = shape_taxon_core(core_json)
            if core is None:
                raise NotFoundError(f"No taxon found for id '{taxon}'.")
            parent, lineage = shape_ancestors(anc_json)
            payload: dict[str, Any] = {"taxon_id": taxon, **core}
            if parent:
                payload["parent_taxon_id"] = parent["taxon_id"]
                payload["parent_name"] = parent.get("scientific_name")
                if parent.get("rank"):
                    payload["parent_rank"] = parent["rank"]
            if include_lineage and lineage:
                payload["lineage"] = lineage
            # The two queries run in parallel: wall-clock is the slower leg (max),
            # and the result is only fully cached if both legs hit the cache.
            payload["elapsed_ms"] = max(core_m["elapsed_ms"], anc_m["elapsed_ms"])
            payload["cached"] = core_m["cached"] and anc_m["cached"]
            return payload
        # Curated fast path: a model-organism name resolves with NO network round
        # trip (the by-name scan is the ~40x latency offender). The long tail and
        # disambiguation (e.g. subspecies) still fall through to the scan.
        record = lookup_common_taxon(taxon)
        if record is not None:
            return {
                "query": taxon,
                "match_count": 1,
                "matches": [record],
                "match_source": "curated_common_index",
                "elapsed_ms": 0.0,
                "cached": True,
            }
        rows_json, qmeta = await self._select_timed(Q.resolve_taxon_by_name(taxon))
        matches = rank_taxon_matches(shape_taxon_resolutions(rows_json), taxon)
        if not matches:
            raise NotFoundError(f"No taxon matched '{taxon}'.")
        # Tag the best hit when it is an exact name match so a consumer (and the
        # next_command that chains off matches[0]) lands on the right organism.
        q = taxon.strip().lower()
        top = matches[0]
        if q in {
            (top.get("scientific_name") or "").lower(),
            (top.get("common_name") or "").lower(),
        }:
            top["match_quality"] = "exact"
        return {
            "query": taxon,
            "match_count": len(matches),
            "matches": matches,
            "match_source": "endpoint_scan",
            **qmeta,
        }
