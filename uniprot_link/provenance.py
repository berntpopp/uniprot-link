"""Upstream fetch times of the current tool call (Response-Envelope Standard v1.2).

The envelope reports ``_meta.retrieved_at`` as the oldest upstream fetch behind a
result. The SPARQL client notes every fetch, the TTL cache re-notes the original
fetch time on a hit, and ``run_mcp_tool`` opens the log and reads it.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import UTC, datetime

# A shared list, not a value: tasks spawned by asyncio.gather copy the context
# but still append to the same list.
_FETCHES: ContextVar[list[datetime] | None] = ContextVar("uniprot_fetches", default=None)


def begin_fetch_log() -> list[datetime]:
    """Start a fresh fetch log for the current tool call and return it."""
    log: list[datetime] = []
    _FETCHES.set(log)
    return log


def note_fetch(at: datetime | None = None) -> datetime:
    """Record an upstream fetch (now, or the original time of a cached one)."""
    at = at or datetime.now(UTC)
    log = _FETCHES.get()
    if log is not None:
        log.append(at)
    return at


def retrieved_at(log: list[datetime]) -> str:
    """Oldest fetch in ``log`` as RFC 3339 UTC; now when nothing was fetched."""
    return min(log, default=datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
