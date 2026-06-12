"""Unit tests for the SPARQL HTTP client (respx-mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from uniprot_link.api.client import SparqlClient
from uniprot_link.config import SparqlEndpointConfig
from uniprot_link.exceptions import (
    QuerySyntaxError,
    RateLimitError,
    ServiceUnavailableError,
)

ENDPOINT = "https://sparql.uniprot.org/sparql"
_OK_JSON = {
    "head": {"vars": ["s"]},
    "results": {"bindings": [{"s": {"type": "uri", "value": "http://x"}}]},
}


@pytest.fixture
def config() -> SparqlEndpointConfig:
    return SparqlEndpointConfig(timeout=5, max_retries=1, retry_delay=0.1)


@pytest.mark.asyncio
@respx.mock
async def test_execute_json_success(config: SparqlEndpointConfig) -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_OK_JSON))
    client = SparqlClient(config)
    result = await client.execute("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
    assert result.status_code == 200
    assert result.json == _OK_JSON
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_user_agent_has_contact(config: SparqlEndpointConfig) -> None:
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_OK_JSON))
    client = SparqlClient(config)
    await client.execute("ASK { ?s ?p ?o }")
    sent = route.calls.last.request
    assert "mailto:" in sent.headers["user-agent"]
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_400_maps_to_syntax_error(config: SparqlEndpointConfig) -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(400, text="Parse error near 'SELCT'"))
    client = SparqlClient(config)
    with pytest.raises(QuerySyntaxError):
        await client.execute("SELCT bad")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_429_maps_to_rate_limit(config: SparqlEndpointConfig) -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(429))
    client = SparqlClient(config)
    with pytest.raises(RateLimitError):
        await client.execute("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_500_retries_then_raises(config: SparqlEndpointConfig) -> None:
    route = respx.post(ENDPOINT).mock(return_value=httpx.Response(503))
    client = SparqlClient(config)
    with pytest.raises(ServiceUnavailableError):
        await client.execute("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
    assert route.call_count == config.max_retries + 1
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_csv_format_returns_text(config: SparqlEndpointConfig) -> None:
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, text="s\nhttp://x\n"))
    client = SparqlClient(config)
    result = await client.execute("SELECT ?s WHERE { ?s ?p ?o }", result_format="csv")
    assert result.json is None
    assert "http://x" in result.text
    await client.aclose()
