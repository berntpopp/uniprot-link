"""Service layer: SPARQL query builders, result shaping, and orchestration."""

from __future__ import annotations

__all__ = ["SparqlService"]


def __getattr__(name: str) -> object:
    """Lazily expose SparqlService without importing httpx at package load."""
    if name == "SparqlService":
        from uniprot_link.services.sparql_service import SparqlService

        return SparqlService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
