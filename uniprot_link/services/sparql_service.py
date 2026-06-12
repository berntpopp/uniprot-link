"""High-level service orchestrating SPARQL query building, execution, shaping.

Every public method returns a plain ``dict`` payload (no envelope). The MCP
tool layer wraps these with ``success``/``_meta``/``next_commands``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from uniprot_link.api.client import RESULT_FORMATS
from uniprot_link.exceptions import InvalidInputError, NotFoundError, ObsoleteEntryError
from uniprot_link.services import queries as Q
from uniprot_link.services import shaping as S
from uniprot_link.services.constants import (
    FEATURE_TYPES,
    MAP_IDENTIFIER_DATABASES,
    SECONDARY_STRUCTURE_TYPES,
    UNIPROT_RELEASE,
)
from uniprot_link.services.service_base import (
    _FEATURE_FETCH_CAP,
    _sort_by_mnemonic,
    _window_sequence,
    attach_isoform_context,
)
from uniprot_link.services.service_taxonomy import TaxonomyServiceMixin


class SparqlService(TaxonomyServiceMixin):
    """Coordinate query builders, the SPARQL client, and result shaping."""

    # --- Raw / power query --------------------------------------------------

    async def run_query(
        self,
        query: str,
        *,
        result_format: str = "json",
        limit: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute an arbitrary SPARQL query (the power tool)."""
        if result_format not in RESULT_FORMATS:
            raise InvalidInputError(
                f"Unknown result_format '{result_format}'. "
                f"Choose one of: {', '.join(RESULT_FORMATS)}.",
                field="result_format",
            )
        Q.classify_sparql_operation(query)  # raises InvalidInputError on writes
        effective_limit = Q.clamp_limit(
            limit or self.config.default_limit,
            default=self.config.default_limit,
            maximum=self.config.max_limit,
        )
        prepared, injected = Q.inject_limit(
            query, default=effective_limit, maximum=self.config.max_limit
        )
        result = await self.client.execute(prepared, result_format=result_format, timeout=timeout)

        meta: dict[str, Any] = {
            "result_format": result_format,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "limit_injected": injected,
        }
        if result_format == "json" and result.json is not None:
            if "boolean" in result.json:
                return {"query_type": "ASK", "boolean": result.json["boolean"], **meta}
            data = S.rows(result.json)
            variables = result.json.get("head", {}).get("vars", [])
            payload: dict[str, Any] = {
                "query_type": "SELECT",
                "columns": variables,
                "row_count": len(data),
                "rows": data,
                **meta,
            }
            if injected and len(data) >= effective_limit:
                # `total` is intentionally omitted: an arbitrary query's full count
                # is not cheaply computable without re-running it.
                payload["truncated"] = {
                    "returned": len(data),
                    "reason": f"auto LIMIT {effective_limit} applied",
                    "recovery": "re-run with an explicit higher LIMIT in the query, "
                    "or pass a larger `limit`.",
                }
            return payload
        return {
            "query_type": "RDF/raw",
            "content_type": result.content_type,
            "data": result.text,
            "byte_length": len(result.text),
            **meta,
        }

    # --- Proteins -----------------------------------------------------------

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
        if reviewed is not None:
            query = Q.find_proteins(limit=limit, offset=offset, reviewed=reviewed, **kwargs)
            result, qmeta = await self._select_timed(query)
            proteins = _sort_by_mnemonic(S.shape_find_proteins(result))
        else:
            proteins, qmeta = await self._find_reviewed_first(kwargs, limit, offset)
        payload: dict[str, Any] = {"count": len(proteins), "proteins": proteins, **qmeta}
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

    async def _find_reviewed_first(
        self, anchors: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Two-phase paginate: Swiss-Prot (reviewed) segment, then TrEMBL fill.

        A cheap bound COUNT of the reviewed segment locates the boundary so the
        offset maps across the two segments. Most selective anchors are fully
        served by the reviewed segment in a single fill query.
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
        return collected, {"elapsed_ms": round(elapsed, 1), "cached": cached}

    async def get_protein(self, accession: str, response_mode: str = "compact") -> dict[str, Any]:
        """Return the core summary for a single entry (obsolete/isoform aware).

        Runs the obsolete-aware status probe in parallel with the summary so an
        obsolete accession returns a flagged record (never a sparse "live" one,
        F-OBS) and a typo'd isoform index is rejected rather than silently
        collapsed to the parent (F-ISO).
        """
        status_json, (summary_json, qmeta) = await asyncio.gather(
            self._select(Q.entry_status(accession)),
            self._select_timed(Q.protein_summary(accession)),
        )
        status = S.shape_entry_status(status_json, accession)
        summary = S.shape_protein_summary(summary_json)
        acc = Q.validate_accession(accession).split("-")[0]
        if not status.exists and summary is None:
            raise NotFoundError(
                f"No UniProtKB entry found for accession '{accession}'. "
                "Resolve a gene/organism via find_proteins first."
            )
        if status.obsolete:
            record = S.build_obsolete_record(acc, status, summary)
            if accession.strip().upper() != acc:
                record["requested_accession"] = accession
            return {**record, **qmeta}
        if status.isoform_exists is False:
            raise NotFoundError(
                f"No isoform '{accession}' exists for entry {acc}. "
                "Call get_protein_sequence to list the entry's isoforms."
            )
        if summary is None:
            raise NotFoundError(f"No UniProtKB entry found for accession '{accession}'.")
        payload: dict[str, Any] = {"accession": acc, **summary, **qmeta}
        # F7: echo requested_accession ONLY when it differs from the resolved base
        # (isoform suffix / redirect) -- omit the pure-token-tax identity echo.
        if accession.strip().upper() != acc:
            payload["requested_accession"] = accession
        if status.isoform_exists:
            payload["isoform"] = accession
            payload["isoform_note"] = (
                "Summary is entry-level; call get_protein_sequence for the "
                f"isoform-specific sequence and mass of {accession}."
            )
        return S.apply_response_mode(payload, response_mode, kind="protein")

    async def get_sequence(self, accession: str, response_mode: str = "compact") -> dict[str, Any]:
        """Return the canonical sequence (and additional isoforms) for an entry.

        Runs the obsolete-aware gate in parallel so an obsolete accession yields
        the family-consistent obsolete error instead of a bare "no sequence" 404.
        """
        query = Q.protein_sequence(accession)
        _, (sequences_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        sequences = S.shape_sequences(sequences_json)
        if not sequences:
            raise NotFoundError(f"No sequence found for accession '{accession}'.")
        acc = Q.validate_accession(accession).split("-")[0]
        canonical = next((s for s in sequences if s["canonical"]), sequences[0])
        others = [s for s in sequences if s is not canonical]
        if response_mode == "minimal":
            canonical = {k: v for k, v in canonical.items() if k != "sequence"}
            others = [{k: v for k, v in s.items() if k != "sequence"} for s in others]
        elif response_mode == "compact":
            # Default: a windowed preview, not the full string. A large protein
            # (titin, ~34,350 aa) otherwise dumps tens of KB on every call (Bug 6).
            canonical = _window_sequence(canonical)
            others = [_window_sequence(s) for s in others]
        # standard / full keep the full `sequence` string unchanged.
        return {
            "accession": acc,
            "canonical": canonical,
            "isoform_count": len(sequences),
            "isoforms": others,
            **qmeta,
        }

    async def require_entry(self, accession: str) -> S.EntryStatus:
        """Gate annotation lookups: raise on absent/obsolete/typo'd-isoform; return status.

        Obsolete entries retain ``a up:Protein`` so a bare existence check passes
        them through; entry_status separates active / obsolete / absent and (for an
        accession carrying a ``-N`` suffix) whether that isoform is real -- so the
        whole tool family rejects a bogus isoform consistently (F1) and emits one
        obsolete signal (F-OBS).
        """
        status = S.shape_entry_status(await self._select(Q.entry_status(accession)), accession)
        if not status.exists:
            raise NotFoundError(
                f"No UniProtKB entry found for accession '{accession}'. "
                "Resolve a gene/organism via find_proteins first."
            )
        if status.obsolete:
            raise ObsoleteEntryError(
                Q.validate_accession(accession).split("-")[0], status.replaced_by
            )
        if status.isoform_exists is False:
            base = Q.validate_accession(accession).split("-")[0]
            raise NotFoundError(
                f"No isoform '{accession}' exists for entry {base}. "
                "Call get_protein_sequence to list the entry's isoforms."
            )
        return status

    async def get_features(
        self,
        accession: str,
        feature_types: list[str] | None = None,
        limit: int = 200,
        include_secondary_structure: bool = False,
    ) -> dict[str, Any]:
        """Return sequence features with coordinates (token-lean via limit)."""
        display_limit = Q.clamp_limit(limit, default=200, maximum=1000)
        # Fetch up to the cap (not the display limit) so the true total is known.
        query = Q.protein_features(accession, feature_types, limit=_FEATURE_FETCH_CAP)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        all_features = S.shape_features(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        # P1b: hide secondary-structure (helix/strand/turn) by default -- it
        # dominates an unfiltered dump and is rarely the answer. Excluded only when
        # not explicitly requested (via the flag or a secondary type in the filter).
        requested = {ft.strip().lower() for ft in (feature_types or [])}
        excluded_ss = 0
        if not include_secondary_structure and not (requested & SECONDARY_STRUCTURE_TYPES):
            kept = [f for f in all_features if f.get("type") not in SECONDARY_STRUCTURE_TYPES]
            excluded_ss = len(all_features) - len(kept)
            all_features = kept
        features = all_features[:display_limit]
        payload: dict[str, Any] = {
            "accession": acc,
            "count": len(features),
            "features": features,
            **qmeta,
        }
        if excluded_ss:
            payload["excluded_secondary_structure"] = {
                "count": excluded_ss,
                "types": sorted(SECONDARY_STRUCTURE_TYPES),
                "hint": (
                    "Secondary-structure features (helix/strand/turn) are hidden "
                    "by default; pass include_secondary_structure=true, or name them "
                    "in feature_types, to include them."
                ),
            }
        if len(all_features) > display_limit:
            payload["truncated"] = {
                "returned": len(features),
                "total": len(all_features),
                "reason": f"limit {display_limit} reached",
                "recovery": "raise `limit` or pass feature_types to narrow.",
            }
        if feature_types and not features:
            payload["filter_hint"] = {
                "message": "No features matched the requested types for this entry.",
                "accepted_feature_types": sorted(FEATURE_TYPES.keys()),
            }
        # The domain/region trap: UniProt types catalytic/binding/interaction
        # domain-scale architecture as `region`, not `domain`. A ['domain'] query
        # silently misses it, so nudge toward `region` whenever domain was asked
        # for without it (independent of count -- the partial-hit case is the trap).
        requested = {ft.strip().lower() for ft in (feature_types or [])}
        if "domain" in requested and "region" not in requested:
            payload["domain_region_hint"] = {
                "message": (
                    "UniProt types some domain-scale architecture as 'region' "
                    "(catalytic, binding, or interaction regions), not 'domain'. "
                    "Re-request with feature_types including 'region' to capture "
                    "the full domain architecture."
                ),
                "suggestion": {
                    "tool": "get_protein_features",
                    "arguments": {"accession": acc, "feature_types": ["domain", "region"]},
                },
            }
        return attach_isoform_context(payload, accession, acc)

    async def get_variants(
        self, accession: str, limit: int = 200, disease_associated_only: bool = False
    ) -> dict[str, Any]:
        """Return natural-variant annotations."""
        limit = Q.clamp_limit(limit, default=200, maximum=2000)
        query = Q.protein_variants(
            accession, limit=limit, disease_associated_only=disease_associated_only
        )
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        variants = S.shape_variants(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        payload: dict[str, Any] = {
            "accession": acc,
            "count": len(variants),
            "variants": variants,
            **qmeta,
        }
        # The SPARQL LIMIT caps pre-merge rows; compare against the raw row count
        # (not the merged variant count) so truncation is never under-reported.
        if len(S.rows(data_json)) >= limit:
            total = await self._count(Q.protein_variants_count(accession, disease_associated_only))
            payload["truncated"] = {
                "returned": len(variants),
                **({"total": total} if total is not None else {}),
                "reason": f"limit {limit} reached",
                "recovery": "raise `limit`, or set disease_associated_only=true to focus on "
                "disease-linked variants.",
            }
        return attach_isoform_context(payload, accession, acc)

    async def get_diseases(self, accession: str) -> dict[str, Any]:
        """Return disease annotations."""
        query = Q.protein_diseases(accession)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        diseases = S.shape_diseases(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        return attach_isoform_context(
            {"accession": acc, "count": len(diseases), "diseases": diseases, **qmeta},
            accession,
            acc,
        )

    async def get_cross_references(
        self,
        accession: str,
        databases: list[str] | None = None,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return cross-references grouped by database (token-lean by mode)."""
        query = Q.protein_cross_references(accession, databases)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        grouped = S.shape_cross_references(data_json, short=response_mode != "full")
        projected = S.project_cross_references(grouped, mode=response_mode)
        acc = Q.validate_accession(accession).split("-")[0]
        payload: dict[str, Any] = {"accession": acc, **projected, **qmeta}
        # F2: an explicit `databases` filter must never silently read as "no data".
        # Echo the request and flag any requested name that matched nothing, so a
        # typo is distinguishable from a genuinely-absent (but valid) database.
        if databases is not None:
            payload["requested_databases"] = list(databases)
            matched = set(projected.get("counts", {}))
            unmatched = [d for d in databases if d not in matched]
            if unmatched:
                payload["unmatched_databases"] = unmatched
                hint: dict[str, Any] = {
                    "message": (
                        "These requested database names matched no cross-reference "
                        "for this entry. Names are case-sensitive (e.g. PDB, "
                        "AlphaFoldDB) -- see common_xref_databases in "
                        "get_server_capabilities. A valid name simply means the "
                        "entry has no such cross-reference."
                    ),
                    "unmatched_databases": unmatched,
                }
                did_you_mean = {
                    d: match for d in unmatched if (match := S.suggest_xref_database(d))
                }
                if did_you_mean:
                    hint["did_you_mean"] = did_you_mean
                payload["database_hint"] = hint
        return attach_isoform_context(payload, accession, acc)

    async def get_go_terms(
        self, accession: str, aspect: str | None = None, limit: int = 0
    ) -> dict[str, Any]:
        """Return GO annotations grouped by aspect (aspect/limit, token-lean)."""
        query = Q.protein_go_terms(accession)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        grouped = S.shape_go_terms(data_json)
        projected = S.project_go_terms(grouped, aspect=aspect, limit=max(0, int(limit)))
        acc = Q.validate_accession(accession).split("-")[0]
        return attach_isoform_context(
            {"accession": acc, **projected, **qmeta}, accession, acc
        )

    async def map_identifiers(
        self,
        accession: str,
        databases: list[str] | None = None,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Map a UniProt accession to its primary external identifiers.

        Unlike get_cross_references (every xref database, incl. drug/disease
        associations), map_identifiers defaults to the genomic/structural/family
        identifier core (MAP_IDENTIFIER_DATABASES) so the payload is small and
        mapping-oriented; pass ``databases`` to override.
        """
        user_supplied = databases is not None
        effective = list(databases or MAP_IDENTIFIER_DATABASES)
        result = await self.get_cross_references(accession, effective, response_mode)
        result["requested_databases"] = effective
        # `counts` is present in every mode (by_database is omitted in minimal).
        result["mapped_databases"] = list(result.get("counts", {}).keys())
        if not user_supplied:
            # Default primary-id set: a protein legitimately lacking some default
            # database is not an error, so drop the unmatched-name noise (the
            # typo-catch stays active when the caller passes `databases`).
            result.pop("unmatched_databases", None)
            result.pop("database_hint", None)
        return result

    # --- Example catalog ----------------------------------------------------

    async def search_examples(self, text: str | None = None, limit: int = 25) -> dict[str, Any]:
        """Search the curated SPARQL example catalog."""
        limit = Q.clamp_limit(limit, default=25, maximum=126)
        examples = S.shape_example_list(await self._select(Q.search_example_queries(text, limit)))
        return {"count": len(examples), "query_text": text, "examples": examples}

    async def get_example(self, example_iri: str) -> dict[str, Any]:
        """Fetch one curated example's full query text and metadata."""
        detail = S.shape_example_detail(await self._select(Q.get_example_query(example_iri)))
        if detail is None:
            raise NotFoundError(
                f"No example found for '{example_iri}'. "
                "Use search_example_queries to list valid example ids."
            )
        return {"example_id": example_iri, **detail}

    @staticmethod
    def release() -> str:
        """Return the bundled UniProt release tag."""
        return UNIPROT_RELEASE
