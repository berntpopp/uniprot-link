"""Lazily-constructed singleton SparqlService for MCP tools."""

from __future__ import annotations

from uniprot_link.api.client import SparqlClient
from uniprot_link.config import settings
from uniprot_link.services.sparql_service import SparqlService

_service: SparqlService | None = None


def get_sparql_service() -> SparqlService:
    """Return a process-wide :class:`SparqlService` (built on first use)."""
    global _service
    if _service is None:
        client = SparqlClient(settings.sparql)
        _service = SparqlService(client, settings.sparql)
    return _service


def set_sparql_service(service: SparqlService | None) -> None:
    """Override the singleton (used by tests)."""
    global _service
    _service = service
