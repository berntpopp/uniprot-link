"""UniProtKB discovery (find_proteins) for the SPARQL service.

Split out of :mod:`sparql_service` for the 600-line cap. ``SparqlService`` mixes
this in, so ``find_proteins`` keeps using the shared ``ServiceBase`` primitives
(``self._select_timed`` / ``self._count``). Houses the reviewed-first pagination
and the F3 latency paths (mnemonic fast-path + concurrent reviewed-first legs).
"""

from __future__ import annotations

import asyncio
from typing import Any

from uniprot_link.exceptions import InvalidInputError
from uniprot_link.services import queries as Q
from uniprot_link.services import shaping as S
from uniprot_link.services.service_base import ServiceBase, _sort_by_mnemonic


class FindProteinsServiceMixin(ServiceBase):
    """find_proteins / find_proteins_batch and their reviewed-first pagination."""

    async def find_proteins(self, **kwargs: Any) -> dict[str, Any]:
        """Search UniProtKB by structured filters.

        Reviewed-first by default: when ``reviewed`` is unset, the Swiss-Prot
        segment is queried (and ranked) before TrEMBL. Each returned page is
        sorted by mnemonic in Python — the builder emits no SPARQL ORDER BY (a
        pre-LIMIT global sort was the latency hotspot).
        """
        limit = Q.clamp_limit(kwargs.pop("limit", 25), default=25, maximum=200)
        offset = max(0, int(kwargs.pop("offset", 0)))
        reviewed = kwargs.pop("reviewed", None)
        reviewed_count: int | None = None
        if reviewed is not None:
            query = Q.find_proteins(limit=limit, offset=offset, reviewed=reviewed, **kwargs)
            result, qmeta = await self._select_timed(query)
            proteins = _sort_by_mnemonic(S.shape_find_proteins(result))
        elif kwargs.get("mnemonic"):
            # F3 fast-path: a mnemonic is unique -> one bound query, no reviewed-first
            # split and no redundant TrEMBL scan (~8s -> ~4.5s, live-verified).
            query = Q.find_proteins(limit=limit, offset=offset, **kwargs)
            result, qmeta = await self._select_timed(query)
            proteins = _sort_by_mnemonic(S.shape_find_proteins(result))
            reviewed_count = sum(1 for p in proteins if p.get("reviewed"))
        elif offset == 0:
            proteins, qmeta, reviewed_count = await self._find_reviewed_first_concurrent(
                kwargs, limit
            )
        else:
            proteins, qmeta, reviewed_count = await self._find_reviewed_first(kwargs, limit, offset)
        payload: dict[str, Any] = {"count": len(proteins), "proteins": proteins, **qmeta}
        if reviewed is None and reviewed_count is not None:
            # F9: disclose how many of the (reviewed-first) results are Swiss-Prot,
            # so a gene page dominated by TrEMBL is never mistaken for "all there is".
            payload["reviewed_count"] = reviewed_count
            if len(proteins) > reviewed_count:
                payload["reviewed_hint"] = (
                    f"{reviewed_count} of the returned entries are reviewed (Swiss-Prot); "
                    "pass reviewed=true to exclude unreviewed TrEMBL entries."
                )
        if len(proteins) >= limit:
            # A grand COUNT (anchors only; reviewed honored) gives the true total --
            # run only on a full page, so the common single-page call pays nothing.
            total = await self._count(Q.find_proteins(reviewed=reviewed, count=True, **kwargs))
            payload["truncated"] = {
                "returned": len(proteins),
                **({"total": total} if total is not None else {}),
                "reason": f"page limit {limit} reached",
                "recovery": f"call again with offset={offset + limit}.",
            }
        return payload

    async def find_proteins_batch(
        self,
        genes: list[str],
        organism_taxon: int | None = None,
        reviewed: bool | None = None,
        limit_per_gene: int = 5,
    ) -> dict[str, Any]:
        """Resolve several gene symbols to entries CONCURRENTLY (Part 1 latency).

        N genes cost ~one cold round-trip instead of N sequential ones (the felt
        cost of a multi-gene task). Returns a gene->accessions map, a flat
        gene-tagged protein list, and the genes that resolved to nothing (so an
        unresolved symbol is never a silent empty).
        """
        unique: list[str] = []
        seen: set[str] = set()
        for raw in genes:
            g = (raw or "").strip()
            if g and g.lower() not in seen:
                seen.add(g.lower())
                unique.append(g)
        if not unique:
            raise InvalidInputError(
                "find_proteins_batch needs at least one gene symbol.", field="genes"
            )
        per_gene = Q.clamp_limit(limit_per_gene, default=5, maximum=25)
        results = await asyncio.gather(
            *(
                self.find_proteins(
                    gene=g, organism_taxon=organism_taxon, reviewed=reviewed, limit=per_gene
                )
                for g in unique
            )
        )
        by_gene: dict[str, list[str]] = {}
        proteins: list[dict[str, Any]] = []
        resolved: list[str] = []
        unresolved: list[str] = []
        elapsed = 0.0
        cached = True
        for gene, result in zip(unique, results, strict=True):
            hits = result.get("proteins", [])
            accessions = [p["accession"] for p in hits if p.get("accession")]
            by_gene[gene] = accessions
            (resolved if accessions else unresolved).append(gene)
            proteins.extend({**p, "matched_gene": gene} for p in hits)
            # Legs run concurrently: wall-clock is the slowest leg; the batch is
            # only fully cached when every leg hit the cache.
            elapsed = max(elapsed, float(result.get("elapsed_ms", 0.0)))
            cached = cached and bool(result.get("cached", False))
        return {
            "gene_count": len(unique),
            "count": len(proteins),
            "by_gene": by_gene,
            "proteins": proteins,
            "resolved_genes": resolved,
            "unresolved_genes": unresolved,
            "elapsed_ms": round(elapsed, 1),
            "cached": cached,
        }

    async def _find_reviewed_first_concurrent(
        self, anchors: dict[str, Any], limit: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        """offset==0 reviewed-first with the three legs run CONCURRENTLY (F3).

        The reviewed COUNT, the reviewed fill, and a speculative unreviewed fill are
        issued together, so wall-clock is the slowest single leg rather than their
        sum (the gene "no reviewed" worst case ~10s -> ~slowest-leg, live-verified).
        The unreviewed leg is only consumed when the reviewed segment does not fill
        the page; for the common spill case (1 Swiss-Prot + many TrEMBL) the same
        three queries ran sequentially before, so this adds a leg only when the
        reviewed segment alone already fills the page.
        """
        (count_json, m_c), (rev_json, m_r), (unrev_json, m_u) = await asyncio.gather(
            self._select_timed(Q.find_proteins(reviewed=True, count=True, **anchors)),
            self._select_timed(Q.find_proteins(reviewed=True, limit=limit, offset=0, **anchors)),
            self._select_timed(Q.find_proteins(reviewed=False, limit=limit, offset=0, **anchors)),
        )
        cr_rows = S.rows(count_json)
        cr = int(cr_rows[0]["n"]) if cr_rows and "n" in cr_rows[0] else 0
        collected = _sort_by_mnemonic(S.shape_find_proteins(rev_json))
        cached = m_c["cached"] and m_r["cached"]
        remaining = limit - len(collected)
        if remaining > 0:
            collected.extend(_sort_by_mnemonic(S.shape_find_proteins(unrev_json))[:remaining])
            cached = cached and m_u["cached"]
        elapsed = round(max(m_c["elapsed_ms"], m_r["elapsed_ms"], m_u["elapsed_ms"]), 1)
        return collected, {"elapsed_ms": elapsed, "cached": cached}, cr

    async def _find_reviewed_first(
        self, anchors: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        """Two-phase paginate (offset>0): Swiss-Prot (reviewed) segment, then TrEMBL fill.

        A cheap bound COUNT of the reviewed segment locates the boundary so the
        offset maps across the two segments. Most selective anchors are fully
        served by the reviewed segment in a single fill query. Returns the reviewed
        segment size ``cr`` for the F9 reviewed_count disclosure.
        """
        cr_json, m_count = await self._select_timed(
            Q.find_proteins(reviewed=True, count=True, **anchors)
        )
        cr_rows = S.rows(cr_json)
        cr = int(cr_rows[0]["n"]) if cr_rows and "n" in cr_rows[0] else 0
        elapsed = m_count["elapsed_ms"]
        cached = m_count["cached"]
        collected: list[dict[str, Any]] = []
        if offset < cr:
            r_limit = min(limit, cr - offset)
            rj, m_r = await self._select_timed(
                Q.find_proteins(reviewed=True, limit=r_limit, offset=offset, **anchors)
            )
            collected.extend(_sort_by_mnemonic(S.shape_find_proteins(rj)))
            elapsed += m_r["elapsed_ms"]
            cached = cached and m_r["cached"]
        remaining = limit - len(collected)
        if remaining > 0:
            u_offset = max(0, offset - cr)
            uj, m_u = await self._select_timed(
                Q.find_proteins(reviewed=False, limit=remaining, offset=u_offset, **anchors)
            )
            collected.extend(_sort_by_mnemonic(S.shape_find_proteins(uj)))
            elapsed += m_u["elapsed_ms"]
            cached = cached and m_u["cached"]
        return collected, {"elapsed_ms": round(elapsed, 1), "cached": cached}, cr
