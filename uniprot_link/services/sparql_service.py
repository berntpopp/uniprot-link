"""High-level service orchestrating SPARQL query building, execution, shaping.

Every public method returns a plain ``dict`` payload (no envelope). The MCP
tool layer wraps these with ``success``/``_meta``/``next_commands``.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from uniprot_link.api.client import RESULT_FORMATS
from uniprot_link.exceptions import InvalidInputError, NotFoundError, ObsoleteEntryError
from uniprot_link.mcp.untrusted_content import (
    UntrustedText,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)
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
    _window_sequence,
    attach_isoform_context,
)
from uniprot_link.services.service_find import FindProteinsServiceMixin
from uniprot_link.services.service_taxonomy import TaxonomyServiceMixin

# shape_features/shape_variants/shape_diseases live in a sibling module (600-line
# cap, see shaping.py's bottom re-export) -- imported directly here (not via the
# S. alias) so mypy strict's implicit_reexport=False does not flag S.shape_features
# et al. as an unexported attribute (mirrors service_taxonomy.py's direct import).
from uniprot_link.services.shaping_annotations import (
    enforce_emitted_feature_limits,
    shape_diseases,
    shape_features,
    shape_variants,
)

_UNTRUSTED_SOURCE = "uniprot"

# search_sparql_query is a power tool: a legitimate SELECT can return up to
# max_limit (10000) rows, each with several string columns, so the per-object
# 2 MiB and 8 MiB-total BYTE ceilings are the real DoS backstop. The object-count
# ceiling is pinned to the 8 MiB total so a normal large SELECT never trips the
# count check before the byte total does (every fenced object is >= 1 byte).
_SPARQL_MAX_OBJECTS = 8_388_608


class SparqlService(FindProteinsServiceMixin, TaxonomyServiceMixin):
    """Coordinate query builders, the SPARQL client, and result shaping."""

    @staticmethod
    def _fence_sparql_rows(data: list[dict[str, Any]], query_hash: str) -> list[dict[str, Any]]:
        """Fence every string cell of an arbitrary SELECT result set.

        search_sparql_query returns ARBITRARY upstream text: a query can SELECT
        ``rdfs:comment`` or any label into any binding, so each string scalar is
        external prose and is wrapped as a typed ``untrusted_text`` object
        (never a bare string). Numeric/boolean scalars are coerced values, not
        prose, and pass through unchanged. ``record_id`` ties the cell to the
        executed query hash + its row/binding position.
        """
        fenced_objects: list[UntrustedText] = []
        fenced_rows: list[dict[str, Any]] = []
        for i, row in enumerate(data):
            frow: dict[str, Any] = {}
            for var, val in row.items():
                if isinstance(val, str):
                    obj = fence_untrusted_text(
                        val,
                        source=_UNTRUSTED_SOURCE,
                        record_id=f"sparql:{query_hash}#row{i}.{var}",
                    )
                    fenced_objects.append(obj)
                    frow[var] = obj.model_dump(mode="json")
                else:
                    frow[var] = val
            fenced_rows.append(frow)
        if fenced_objects:
            enforce_untrusted_text_limits(fenced_objects, max_objects=_SPARQL_MAX_OBJECTS)
        return fenced_rows

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
        op = Q.classify_sparql_operation(query)  # raises InvalidInputError on writes
        effective_limit = Q.clamp_limit(
            limit or self.config.default_limit,
            default=self.config.default_limit,
            maximum=self.config.max_limit,
        )
        prepared, injected = Q.inject_limit(
            query, default=effective_limit, maximum=self.config.max_limit
        )
        result = await self.client.execute(prepared, result_format=result_format, timeout=timeout)
        query_hash = hashlib.sha256(prepared.encode("utf-8")).hexdigest()[:16]

        # The raw-query policy permits SELECT/ASK only; serialization is reported
        # separately so a SELECT projected to CSV is never mislabeled.
        known = op in {"SELECT", "ASK"}
        meta: dict[str, Any] = {
            "serialization": result_format,
            "result_format": result_format,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "limit_injected": injected,
        }
        if result_format == "json" and result.json is not None:
            if "boolean" in result.json:
                # ASK returns only a boolean -- no upstream prose to fence.
                return {"query_type": "ASK", "boolean": result.json["boolean"], **meta}
            data = S.rows(result.json)
            variables = result.json.get("head", {}).get("vars", [])
            payload: dict[str, Any] = {
                "query_type": op if known else "SELECT",
                "columns": variables,
                "row_count": len(data),
                # Every string cell is fenced as an untrusted_text object (v1.1).
                "rows": self._fence_sparql_rows(data, query_hash),
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
        # Raw RDF/CSV/XML/turtle serialization is arbitrary upstream text -- fence
        # the whole blob as a single untrusted_text object (byte_length stays the
        # raw serialized length for the caller).
        fenced_data = fence_untrusted_text(
            result.text, source=_UNTRUSTED_SOURCE, record_id=f"sparql:{query_hash}"
        )
        enforce_untrusted_text_limits([fenced_data], max_objects=_SPARQL_MAX_OBJECTS)
        return {
            "query_type": op if known else "RDF/raw",
            "content_type": result.content_type,
            "data": fenced_data.model_dump(mode="json"),
            "byte_length": len(result.text),
            **meta,
        }

    # --- Proteins -----------------------------------------------------------
    # find_proteins / find_proteins_batch live in FindProteinsServiceMixin
    # (services/service_find.py) for the 600-line cap.

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
        acc = Q.validate_accession(accession).split("-")[0]
        summary = S.shape_protein_summary(summary_json, acc)
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

    async def get_sequence(
        self, accession: str, response_mode: str = "compact", canonical_only: bool = False
    ) -> dict[str, Any]:
        """Return the canonical sequence (and isoforms), or a requested isoform (F2/F7).

        Runs the obsolete-aware gate first so an obsolete accession yields the
        family-consistent obsolete error and a typo'd isoform a clean not_found. An
        isoform accession (``P05067-2``) returns THAT isoform's specific sequence and
        mass (canonical-only ``up:mass`` is computed when absent); ``canonical_only``
        suppresses the additional-isoform list (token economy, F7).
        """
        query = Q.protein_sequence(accession)
        await self.require_entry(accession)
        sequences_json, qmeta = await self._select_timed(query)
        sequences = S.shape_sequences(sequences_json)
        if not sequences:
            raise NotFoundError(f"No sequence found for accession '{accession}'.")
        acc = Q.validate_accession(accession).split("-")[0]
        requested = accession.strip().upper()
        is_isoform_request = requested != acc
        if is_isoform_request:
            canonical = next((s for s in sequences if s["isoform"] == requested), None)
            if canonical is None:
                raise NotFoundError(
                    f"No isoform '{accession}' exists for entry {acc}. "
                    "Call get_protein_sequence on the entry to list its isoforms."
                )
            others: list[dict[str, Any]] = []
        else:
            canonical = next((s for s in sequences if s["canonical"]), sequences[0])
            others = [s for s in sequences if s is not canonical]
        if canonical_only:
            others = []
        if response_mode == "minimal":
            canonical = {k: v for k, v in canonical.items() if k != "sequence"}
            others = [{k: v for k, v in s.items() if k != "sequence"} for s in others]
        elif response_mode == "compact":
            # Default: a windowed preview, not the full string. A large protein
            # (titin, ~34,350 aa) otherwise dumps tens of KB on every call (Bug 6).
            canonical = _window_sequence(canonical)
            others = [_window_sequence(s) for s in others]
        # standard / full keep the full `sequence` string unchanged.
        payload: dict[str, Any] = {
            "accession": acc,
            "canonical": canonical,
            "isoform_count": len(sequences),
            "isoforms": others,
            **qmeta,
        }
        if is_isoform_request:
            payload["requested_isoform"] = requested
        return payload

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
        acc = Q.validate_accession(accession).split("-")[0]
        all_features = shape_features(data_json, acc)
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
        # Enforce untrusted-text ceilings over the EMITTED features only: the fetch
        # cap, secondary-structure hiding, and display slice above all drop features
        # that are never returned, so enforcing over the full fetched set could raise
        # limit_exceeded on content the caller never sees.
        enforce_emitted_feature_limits(features)
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
        acc = Q.validate_accession(accession).split("-")[0]
        variants = shape_variants(data_json, acc)
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
        acc = Q.validate_accession(accession).split("-")[0]
        diseases = shape_diseases(data_json, acc)
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
        return attach_isoform_context({"accession": acc, **projected, **qmeta}, accession, acc)

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
        detail = S.shape_example_detail(
            await self._select(Q.get_example_query(example_iri)), example_iri
        )
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
