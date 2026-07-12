"""UniProt binding for the vendored GeneFoundry HTTP-policy v1 suite."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import httpx
import pytest

from uniprot_link.api.client import SparqlClient
from uniprot_link.api.url_guard import DisallowedURLError, ResponseTooLargeError
from uniprot_link.config import SparqlEndpointConfig


class _ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = tuple(chunks)

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


class _HttpPolicyAdapter:
    async def _client(self, cap: int = 64) -> SparqlClient:
        client = SparqlClient(
            SparqlEndpointConfig(base_url="https://allowed.example/sparql", max_response_bytes=cap)
        )
        session = await client._get_client()
        assert session.follow_redirects and session.max_redirects == 5
        return client

    def allow(self, url: str) -> object:
        async def check() -> None:
            client = await self._client()
            try:
                session = await client._get_client()
                session._transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
                client.config.base_url = url
                await client.execute("SELECT * WHERE {}")
            finally:
                await client.aclose()

        return asyncio.run(check())

    def request(self, url: str, redirects: list[str], max_redirects: int) -> None:
        async def send() -> None:
            client = await self._client()
            try:
                session = await client._get_client()
                if not session.follow_redirects or session.max_redirects != max_redirects:
                    raise DisallowedURLError("outbound request rejected by policy")
                index = 0

                def handler(_: httpx.Request) -> httpx.Response:
                    nonlocal index
                    if index < len(redirects):
                        location = redirects[index]
                        index += 1
                        return httpx.Response(302, headers={"Location": location})
                    return httpx.Response(200, content=b"ok")

                session._transport = httpx.MockTransport(handler)
                client.config.base_url = url
                await client.execute("SELECT * WHERE {}")
            finally:
                await client.aclose()

        asyncio.run(send())

    def read_decoded(self, chunks: Iterable[bytes], cap: int) -> None:
        async def read() -> None:
            client = await self._client(cap)
            try:
                session = await client._get_client()
                session._transport = httpx.MockTransport(
                    lambda _: httpx.Response(200, stream=_ChunkedStream(chunks))
                )
                await client.execute("SELECT * WHERE {}", result_format="csv")
            finally:
                await client.aclose()

        asyncio.run(read())

    def is_non_retryable(self, error: Exception) -> bool:
        return isinstance(error, (DisallowedURLError, ResponseTooLargeError))

    def public_message(self, error: Exception) -> str:
        return str(error)


@pytest.fixture
def http_policy_adapter() -> _HttpPolicyAdapter:
    return _HttpPolicyAdapter()
