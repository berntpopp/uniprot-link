"""Custom exceptions for uniprot-link."""

from __future__ import annotations


class SparqlClientError(Exception):
    """Base exception for SPARQL client/endpoint errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Store a human-readable message and optional HTTP status code."""
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        """Return the message (with status code when present)."""
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class QuerySyntaxError(SparqlClientError):
    """The endpoint rejected the query as malformed (HTTP 400)."""

    def __init__(self, message: str = "The SPARQL query is malformed.") -> None:
        """Initialise with a 400 status code."""
        super().__init__(message, status_code=400)


class QueryTimeoutError(SparqlClientError):
    """The query exceeded the client-side timeout."""

    def __init__(self, message: str = "The SPARQL query timed out.") -> None:
        """Initialise with a 504 status code."""
        super().__init__(message, status_code=504)


class RateLimitError(SparqlClientError):
    """The endpoint signalled rate limiting (HTTP 429)."""

    def __init__(self, message: str = "UniProt SPARQL rate limit hit.") -> None:
        """Initialise with a 429 status code."""
        super().__init__(message, status_code=429)


class ServiceUnavailableError(SparqlClientError):
    """The endpoint is temporarily unavailable (HTTP 5xx / network error)."""

    def __init__(self, message: str = "UniProt SPARQL endpoint is unavailable.") -> None:
        """Initialise with a 503 status code."""
        super().__init__(message, status_code=503)


class InvalidInputError(SparqlClientError):
    """A tool/service argument failed validation before any query ran."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        *,
        allowed: list[str] | None = None,
        hint: str | None = None,
    ) -> None:
        """Initialise with the offending field and optional recovery data.

        ``allowed`` and ``hint`` are surfaced as structured top-level keys on the
        error envelope (``allowed_values``/``hint``) so a consumer never has to
        parse them out of a (length-capped) message.
        """
        super().__init__(message)
        self.field = field
        self.allowed = allowed
        self.hint = hint


class NotFoundError(SparqlClientError):
    """A lookup returned no rows for an otherwise valid identifier."""

    def __init__(self, message: str = "No records found.") -> None:
        """Initialise with a 404 status code."""
        super().__init__(message, status_code=404)
