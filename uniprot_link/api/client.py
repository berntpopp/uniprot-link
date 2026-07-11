"""Async HTTP client for the UniProt SPARQL endpoint.

A thin, rate-limited wrapper over httpx that POSTs a SPARQL query to the
endpoint, negotiates the result format via the ``Accept`` header, and maps
HTTP failures onto the project's exception taxonomy.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import httpx

from uniprot_link.exceptions import (
    QuerySyntaxError,
    QueryTimeoutError,
    RateLimitError,
    ServiceUnavailableError,
)

if TYPE_CHECKING:
    import types

    from structlog.typing import FilteringBoundLogger

    from uniprot_link.config import SparqlEndpointConfig

# Friendly format name -> (Accept MIME type, is_json result set).
RESULT_FORMATS: dict[str, tuple[str, bool]] = {
    "json": ("application/sparql-results+json", True),
    "xml": ("application/sparql-results+xml", False),
    "csv": ("text/csv", False),
    "tsv": ("text/tab-separated-values", False),
    "turtle": ("text/turtle", False),
    "rdfxml": ("application/rdf+xml", False),
    "ntriples": ("application/n-triples", False),
}

_HTTP_BAD_REQUEST = 400
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500


@dataclass(slots=True)
class SparqlResult:
    """The outcome of a single SPARQL request."""

    format: str
    content_type: str
    text: str
    status_code: int
    elapsed_ms: float
    json: dict[str, Any] | None = None


class TokenBucketRateLimiter:
    """A simple async token-bucket limiter."""

    def __init__(self, rate: float, burst: int) -> None:
        """Initialise with a refill ``rate`` (per second) and ``burst`` capacity."""
        self.rate = rate
        self.burst = float(burst)
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.last_update) * self.rate)
                self.last_update = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            await asyncio.sleep(wait)


class SparqlClient:
    """HTTP client that executes SPARQL queries against the UniProt endpoint."""

    def __init__(
        self,
        config: SparqlEndpointConfig,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        """Build a client from endpoint configuration."""
        self.config = config
        self.logger = logger
        self._rate_limiter = TokenBucketRateLimiter(config.rate_limit_per_second, config.burst_size)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the shared httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                follow_redirects=True,
                headers={"User-Agent": self.config.user_agent},
            )
        return self._client

    async def execute(
        self,
        query: str,
        *,
        result_format: str = "json",
        timeout: float | None = None,
    ) -> SparqlResult:
        """Execute a SPARQL query and return a :class:`SparqlResult`.

        Args:
            query: The SPARQL query string.
            result_format: One of :data:`RESULT_FORMATS` keys.
            timeout: Optional per-call timeout override (seconds).

        Raises:
            QuerySyntaxError: The endpoint returned HTTP 400.
            RateLimitError: The endpoint returned HTTP 429.
            ServiceUnavailableError: The endpoint returned HTTP 5xx.
            QueryTimeoutError: The request exceeded the timeout.
        """
        accept, is_json = RESULT_FORMATS.get(result_format, RESULT_FORMATS["json"])
        request_timeout = httpx.Timeout(timeout if timeout is not None else self.config.timeout)
        last_exc: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            await self._rate_limiter.acquire()
            started = time.monotonic()
            try:
                client = await self._get_client()
                response = await client.post(
                    self.config.base_url,
                    data={"query": query},
                    headers={"Accept": accept},
                    timeout=request_timeout,
                )
            except httpx.TimeoutException as exc:
                raise QueryTimeoutError(
                    f"Query exceeded the {request_timeout.read}s client timeout."
                ) from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                raise ServiceUnavailableError(
                    "Could not reach the UniProt SPARQL endpoint."
                ) from exc

            elapsed_ms = (time.monotonic() - started) * 1000.0
            status = response.status_code

            if status == _HTTP_BAD_REQUEST:
                # Never echo the QLever 400 response BODY: a caller-influenced
                # malformed query can make the endpoint reflect hostile prose (incl.
                # control/zero-width/bidi/NUL code points) into that body, which would
                # then reach the model through the MCP error envelope. Raise a fixed,
                # body-free message with a static cause-oriented hint (the HTTP status
                # is the only safe upstream-derived scalar); the raw body is
                # deliberately neither surfaced nor logged (no-PII-in-logs invariant).
                raise QuerySyntaxError(
                    "Malformed SPARQL query (endpoint rejected it as invalid). Common "
                    "causes: unbalanced {}/() , a missing PREFIX, or an incomplete "
                    "FILTER/expression. Re-seed from a working example."
                )
            if status == _HTTP_TOO_MANY_REQUESTS:
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                raise RateLimitError()
            if status >= _HTTP_SERVER_ERROR:
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_delay * (2**attempt))
                    continue
                raise ServiceUnavailableError(f"Endpoint returned HTTP {status}.")
            if status >= _HTTP_BAD_REQUEST:
                raise QuerySyntaxError(f"Endpoint returned HTTP {status}.")

            if self.logger is not None:
                self.logger.debug(
                    "sparql_request",
                    status=status,
                    format=result_format,
                    elapsed_ms=round(elapsed_ms, 1),
                )

            parsed = response.json() if is_json else None
            return SparqlResult(
                format=result_format,
                content_type=response.headers.get("content-type", accept),
                text=response.text,
                status_code=status,
                elapsed_ms=elapsed_ms,
                json=parsed,
            )

        # Unreachable: loop either returns or raises.
        raise ServiceUnavailableError(str(last_exc) if last_exc else "Unknown error.")

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        """Enter an async context."""
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: types.TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        await self.aclose()
