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
from urllib.parse import urlsplit

import httpx


class DisallowedURLError(Exception):
    """An outbound request/redirect targeted a non-allowlisted URL. NON-RETRYABLE."""


class ResponseTooLargeError(Exception):
    """A response body exceeded the streamed byte cap. NON-RETRYABLE (never truncated)."""


def build_host_allowlist(*base_urls: str) -> frozenset[str]:
    """Derive an exact host allowlist from configured base URL(s).

    Hosts are lower-cased for case-insensitive comparison. Never hardcode a host
    literal -- every base URL is operator-overridable, so the allowlist must track
    the configured endpoint.
    """
    hosts: set[str] = set()
    for url in base_urls:
        host = urlsplit(url).hostname
        if host:
            hosts.add(host.lower())
    return frozenset(hosts)


def make_url_guard(
    allowed_hosts: frozenset[str],
) -> Callable[[httpx.Request], Awaitable[None]]:
    """Build an httpx async request event-hook validating each outgoing hop."""

    async def _guard(request: httpx.Request) -> None:
        url = request.url
        if url.scheme != "https":
            raise DisallowedURLError(f"non-https request scheme: {url.scheme!r}")
        if url.username or url.password:
            raise DisallowedURLError("userinfo (user:pass@) is not permitted in the target URL")
        host = (url.host or "").lower()
        if host not in allowed_hosts:
            raise DisallowedURLError(f"host not allowlisted: {host!r}")

    return _guard


async def read_body_capped(response: httpx.Response, *, max_bytes: int) -> bytes:
    """Stream ``response`` into memory, raising past ``max_bytes`` (never truncating)."""
    total = 0
    chunks: list[bytes] = []
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(
                f"SPARQL response exceeded the {max_bytes}-byte cap; refusing to "
                "truncate (a partial result set is unparseable). Narrow the query "
                "or lower the LIMIT."
            )
        chunks.append(chunk)
    return b"".join(chunks)
