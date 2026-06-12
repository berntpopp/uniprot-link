"""High-level service orchestrating SPARQL query building, execution, shaping.

Every public method returns a plain ``dict`` payload (no envelope). The MCP
tool layer wraps these with ``success``/``_meta``/``next_commands``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from uniprot_link.api.client import RESULT_FORMATS, SparqlClient
from uniprot_link.exceptions import InvalidInputError, NotFoundError
from uniprot_link.services import queries as Q
from uniprot_link.services import shaping as S
from uniprot_link.services.constants import COMMON_XREF_DATABASES, FEATURE_TYPES, UNIPROT_RELEASE

if TYPE_CHECKING:
    from uniprot_link.config import SparqlEndpointConfig


def _sort_by_mnemonic(proteins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort a (small, already-LIMITed) protein page by mnemonic, Nones last."""
    return sorted(proteins, key=lambda p: (p.get("mnemonic") is None, p.get("mnemonic") or ""))


_SEQUENCE_PREVIEW = 30


def _window_sequence(seq: dict[str, Any]) -> dict[str, Any]:
    """Replace a full sequence string with a first/last-N preview (compact mode).

    Short sequences (<= 2*N) are returned whole; longer ones become
    ``sequence_preview`` + ``sequence_truncated: True`` and drop ``sequence``.
    """
    s = seq.get("sequence") or ""
    out = {k: v for k, v in seq.items() if k != "sequence"}
    if len(s) <= 2 * _SEQUENCE_PREVIEW:
        if "sequence" in seq:
            out["sequence"] = s
        return out
    out["sequence_preview"] = f"{s[:_SEQUENCE_PREVIEW]}...{s[-_SEQUENCE_PREVIEW:]}"
    out["sequence_truncated"] = True
    return out


class _TTLCache:
    """Tiny in-process TTL cache for ``(query, format)`` -> result payloads."""

    def __init__(self, maxsize: int, ttl: int) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        if self._maxsize <= 0:
            return None
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        if self._maxsize <= 0:
            return
        if len(self._store) >= self._maxsize:
            self._store.pop(next(iter(self._store)), None)
        self._store[key] = (time.monotonic() + self._ttl, value)


class SparqlService:
    """Coordinate query builders, the SPARQL client, and result shaping."""

    def __init__(self, client: SparqlClient, config: SparqlEndpointConfig) -> None:
        """Build the service around a client and endpoint configuration."""
        self.client = client
        self.config = config
        self._cache = _TTLCache(maxsize=512, ttl=3600)

    async def _select_timed(
        self, query: str, *, timeout: float | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Execute a SELECT/ASK; return (json, {elapsed_ms, cached})."""
        cache_key = f"json::{query}"
        cached: dict[str, Any] | None = self._cache.get(cache_key)
        if cached is not None:
            return cached, {"elapsed_ms": 0.0, "cached": True}
        result = await self.client.execute(query, result_format="json", timeout=timeout)
        self._cache.put(cache_key, result.json)
        return result.json, {"elapsed_ms": round(result.elapsed_ms, 1), "cached": False}

    async def _select(self, query: str, *, timeout: float | None = None) -> dict[str, Any] | None:
        """Execute a SELECT/ASK and return its parsed JSON (cached)."""
        json_result, _ = await self._select_timed(query, timeout=timeout)
        return json_result

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
                payload["truncated"] = {
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
            payload["truncated"] = {
                "reason": f"page limit {limit} reached",
                "recovery": f"call again with offset={offset + limit}.",
            }
        return payload

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
        """Return the core summary for a single entry."""
        query = Q.protein_summary(accession)
        summary_json, qmeta = await self._select_timed(query)
        summary = S.shape_protein_summary(summary_json)
        if summary is None:
            raise NotFoundError(
                f"No UniProtKB entry found for accession '{accession}'. "
                "Resolve a gene/organism via find_proteins first."
            )
        acc = Q.validate_accession(accession).split("-")[0]
        payload = {"accession": acc, **summary, **qmeta}
        return S.apply_response_mode(payload, response_mode, kind="protein")

    async def get_sequence(self, accession: str, response_mode: str = "compact") -> dict[str, Any]:
        """Return the canonical sequence (and additional isoforms) for an entry."""
        query = Q.protein_sequence(accession)
        sequences_json, qmeta = await self._select_timed(query)
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

    async def require_entry(self, accession: str) -> None:
        """Raise NotFoundError if the UniProtKB entry does not exist (cached)."""
        ask_json = await self._select(Q.entry_exists_ask(accession))
        if not (ask_json or {}).get("boolean", False):
            raise NotFoundError(
                f"No UniProtKB entry found for accession '{accession}'. "
                "Resolve a gene/organism via find_proteins first."
            )

    async def get_features(
        self, accession: str, feature_types: list[str] | None = None
    ) -> dict[str, Any]:
        """Return sequence features with coordinates."""
        query = Q.protein_features(accession, feature_types)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        features = S.shape_features(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        payload: dict[str, Any] = {
            "accession": acc,
            "count": len(features),
            "features": features,
            **qmeta,
        }
        if feature_types and not features:
            payload["filter_hint"] = {
                "message": "No features matched the requested types for this entry.",
                "accepted_feature_types": sorted(FEATURE_TYPES.keys()),
            }
        return payload

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
            payload["truncated"] = {
                "reason": f"limit {limit} reached",
                "recovery": "raise `limit`, or set disease_associated_only=true to focus on "
                "disease-linked variants.",
            }
        return payload

    async def get_diseases(self, accession: str) -> dict[str, Any]:
        """Return disease annotations."""
        query = Q.protein_diseases(accession)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        diseases = S.shape_diseases(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        return {"accession": acc, "count": len(diseases), "diseases": diseases, **qmeta}

    async def get_cross_references(
        self,
        accession: str,
        databases: list[str] | None = None,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Return cross-references grouped by database."""
        query = Q.protein_cross_references(accession, databases)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        grouped = S.shape_cross_references(data_json, short=response_mode != "full")
        acc = Q.validate_accession(accession).split("-")[0]
        total = sum(len(v) for v in grouped.values())
        return {
            "accession": acc,
            "database_count": len(grouped),
            "total": total,
            "by_database": grouped,
            **qmeta,
        }

    async def get_go_terms(self, accession: str) -> dict[str, Any]:
        """Return Gene Ontology annotations grouped by aspect."""
        query = Q.protein_go_terms(accession)
        _, (data_json, qmeta) = await asyncio.gather(
            self.require_entry(accession), self._select_timed(query)
        )
        grouped = S.shape_go_terms(data_json)
        acc = Q.validate_accession(accession).split("-")[0]
        total = sum(len(v) for v in grouped.values())
        return {"accession": acc, "count": total, "by_aspect": grouped, **qmeta}

    async def map_identifiers(
        self,
        accession: str,
        databases: list[str] | None = None,
        response_mode: str = "compact",
    ) -> dict[str, Any]:
        """Map a UniProt accession to a curated set of external id databases.

        Unlike get_cross_references (every xref database), map_identifiers focuses
        on primary id-mapping targets by default (COMMON_XREF_DATABASES) so the
        payload is small and mapping-oriented; pass ``databases`` to override.
        """
        effective = list(databases or COMMON_XREF_DATABASES)
        result = await self.get_cross_references(accession, effective, response_mode)
        result["requested_databases"] = effective
        result["mapped_databases"] = list(result["by_database"].keys())
        return result

    # --- Taxonomy -----------------------------------------------------------

    async def get_taxon(self, taxon: str, include_lineage: bool = False) -> dict[str, Any]:
        """Resolve a taxon by id (digits) or scientific/common name."""
        taxon = str(taxon).strip()
        if taxon.isdigit():
            (core_json, core_m), (anc_json, anc_m) = await asyncio.gather(
                self._select_timed(Q.taxon_core(taxon)),
                self._select_timed(Q.taxon_ancestors(taxon)),
            )
            core = S.shape_taxon_core(core_json)
            if core is None:
                raise NotFoundError(f"No taxon found for id '{taxon}'.")
            parent, lineage = S.shape_ancestors(anc_json)
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
        rows_json, qmeta = await self._select_timed(Q.resolve_taxon_by_name(taxon))
        matches = S.shape_taxon_resolutions(rows_json)
        if not matches:
            raise NotFoundError(f"No taxon matched '{taxon}'.")
        return {"query": taxon, "match_count": len(matches), "matches": matches, **qmeta}

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
