"""Shared service primitives: the TTL cache, timed SELECT execution, and the
small stateless helpers used across the SPARQL service.

Split out of :mod:`sparql_service` to keep each module within the repo's
600-line discipline (see AGENTS.md). ``SparqlService`` subclasses
:class:`ServiceBase` so every domain method keeps calling ``self._select`` /
``self._select_timed`` / ``self._count`` unchanged.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from uniprot_link.services import shaping as S

if TYPE_CHECKING:
    from uniprot_link.api.client import SparqlClient
    from uniprot_link.config import SparqlEndpointConfig

# Features are fetched up to this cap (bound on one accession -- a single QLever
# plan regardless of the integer), then sliced to the caller's display `limit` in
# Python, so the truncation envelope can report the TRUE total (F4).
_FEATURE_FETCH_CAP = 1000
_SEQUENCE_PREVIEW = 30


def _sort_by_mnemonic(proteins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort a (small, already-LIMITed) page by mnemonic then accession.

    Accession is the unique final tiebreak, making the order total and the page
    deterministic across identical calls (pagination stability) even when two
    entries share -- or lack -- a mnemonic.
    """
    return sorted(
        proteins,
        key=lambda p: (
            p.get("mnemonic") is None,
            p.get("mnemonic") or "",
            p.get("accession") or "",
        ),
    )


def attach_isoform_context(
    payload: dict[str, Any], requested: str, base_acc: str
) -> dict[str, Any]:
    """Annotate an entry-level payload when the caller passed a valid isoform suffix.

    Entry annotations (features/variants/diseases/go/xref/map) are reported at the
    canonical-entry level; when the request carried a real ``-N`` isoform suffix we
    echo it under ``requested_accession`` and add an ``isoform_note``, matching
    ``get_protein``'s model (F1). The caller validates the isoform exists first
    (via ``require_entry``), so this only fires for genuine isoforms. A pure case
    difference (``p05067`` -> ``P05067``) normalises silently and is not echoed.
    """
    if requested.strip().upper() != base_acc:
        payload["requested_accession"] = requested
        payload["isoform_note"] = (
            f"Annotations are reported at the canonical-entry level for {base_acc}; "
            f"the requested isoform {requested} maps to this entry."
        )
    return payload


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


class ServiceBase:
    """Cache + SPARQL-execution primitives shared by the SPARQL service."""

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

    async def _count(self, count_query: str) -> int | None:
        """Run a ``COUNT(... AS ?n)`` query and return the integer, or ``None``."""
        rows = S.rows(await self._select(count_query))
        return int(rows[0]["n"]) if rows and "n" in rows[0] else None
