"""HTTP client layer for the UniProt SPARQL endpoint."""

from __future__ import annotations

from uniprot_link.api.client import RESULT_FORMATS, SparqlClient, SparqlResult

__all__ = ["RESULT_FORMATS", "SparqlClient", "SparqlResult"]
