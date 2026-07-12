"""Outbound-URL allowlisting + streamed response byte cap for the SPARQL client.

The UniProt SPARQL client keeps httpx's ``follow_redirects=True`` (a manual
redirect loop would silently mishandle the POST method/body on a 307/308), and
instead *validates every hop* with an httpx request event-hook: each outgoing
request URL -- the initial POST and any auto-followed redirect -- must be
``https``, target an exact-allowlisted host derived from the configured base URL,
and carry no userinfo. A violating hop raises :class:`DisallowedURLError`.

Responses are read with a streamed byte cap: past the cap the read is aborted and
:class:`ResponseTooLargeError` is raised. It NEVER truncates -- a truncated SPARQL
JSON/turtle/CSV body is unparseable, so failing closed is the only safe choice.

Both guard exceptions are plain :class:`Exception` subclasses (NOT ``httpx``
transport/timeout errors), so the client's retry loop never swallows or retries
them -- a validation/cap failure is non-retryable by construction.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class DisallowedURLError(Exception):
    """An outbound request/redirect targeted a non-allowlisted URL. NON-RETRYABLE."""


class ResponseTooLargeError(Exception):
    """A response body exceeded the streamed byte cap. NON-RETRYABLE (never truncated)."""


OUTBOUND_POLICY_ERROR = "outbound request rejected by policy"


@dataclass(frozen=True, slots=True)
class AllowedOrigin:
    """A normalized configured HTTPS origin."""

    host: str
    port: int


def build_allowed_origins(*base_urls: str) -> frozenset[AllowedOrigin]:
    """Derive exact normalized origins from configured base URL(s).

    An omitted port and ``:443`` are the same origin. A configured non-443 port
    remains explicit, so a redirect cannot silently pivot to another service on
    an otherwise allowlisted host.
    """
    origins: set[AllowedOrigin] = set()
    for url in base_urls:
        parsed = urlsplit(url)
        host = parsed.hostname
        if host:
            origins.add(AllowedOrigin(host.lower(), parsed.port or 443))
    return frozenset(origins)


def build_host_allowlist(*base_urls: str) -> frozenset[str]:
    """Compatibility view for callers that only need the configured hosts."""
    return frozenset(origin.host for origin in build_allowed_origins(*base_urls))


def make_url_guard(
    allowed_origins: frozenset[AllowedOrigin] | frozenset[str],
) -> Callable[[httpx.Request], Awaitable[None]]:
    """Build an httpx async request event-hook validating each outgoing hop."""

    normalized = frozenset(
        AllowedOrigin(origin, 443) if isinstance(origin, str) else origin
        for origin in allowed_origins
    )

    async def _guard(request: httpx.Request) -> None:
        url = request.url
        if url.scheme != "https":
            raise DisallowedURLError(OUTBOUND_POLICY_ERROR)
        # ``url.userinfo`` is the raw bytes (``b''`` when absent), so this also
        # rejects the empty ``:@`` form (username==password=="" but userinfo==b':')
        # that a ``username or password`` check would miss. Subsumes both.
        if url.userinfo:
            raise DisallowedURLError(OUTBOUND_POLICY_ERROR)
        host = (url.host or "").lower()
        if AllowedOrigin(host, url.port or 443) not in normalized:
            raise DisallowedURLError(OUTBOUND_POLICY_ERROR)

    return _guard


async def read_body_capped(response: httpx.Response, *, max_bytes: int) -> bytes:
    """Stream ``response`` into memory, raising past ``max_bytes`` (never truncating)."""
    total = 0
    chunks: list[bytes] = []
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(OUTBOUND_POLICY_ERROR)
        chunks.append(chunk)
    return b"".join(chunks)
