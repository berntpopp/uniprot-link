"""Shared pytest fixtures for uniprot-link tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from uniprot_link.api.client import RESULT_FORMATS, SparqlResult
from uniprot_link.config import SparqlEndpointConfig
from uniprot_link.services.sparql_service import SparqlService


def make_select_json(variables: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a SPARQL-results JSON body from simple ``{var: cell}`` rows."""
    bindings = []
    for row in rows:
        binding: dict[str, Any] = {}
        for var, cell in row.items():
            if isinstance(cell, bool):
                binding[var] = {
                    "type": "literal",
                    "datatype": "http://www.w3.org/2001/XMLSchema#boolean",
                    "value": "true" if cell else "false",
                }
            elif isinstance(cell, int):
                binding[var] = {
                    "type": "literal",
                    "datatype": "http://www.w3.org/2001/XMLSchema#int",
                    "value": str(cell),
                }
            elif isinstance(cell, str) and cell.startswith("http"):
                binding[var] = {"type": "uri", "value": cell}
            else:
                binding[var] = {"type": "literal", "value": str(cell)}
        bindings.append(binding)
    return {"head": {"vars": variables}, "results": {"bindings": bindings}}


class FakeSparqlClient:
    """A stand-in for SparqlClient that routes queries to canned responses."""

    def __init__(self, routes: list[tuple[str, dict[str, Any]]]) -> None:
        """Initialise with ``(substring, response_json)`` routes (first match wins)."""
        self.routes = routes
        self.calls: list[str] = []
        self.closed = False

    async def execute(
        self, query: str, *, result_format: str = "json", timeout: float | None = None
    ) -> SparqlResult:
        """Return the first canned response whose substring is in the query."""
        self.calls.append(query)
        accept = RESULT_FORMATS.get(result_format, RESULT_FORMATS["json"])[0]
        body: dict[str, Any] = {"head": {"vars": []}, "results": {"bindings": []}}
        for needle, response in self.routes:
            if needle in query:
                body = response
                break
        text = "" if result_format != "json" else "{}"
        return SparqlResult(
            format=result_format,
            content_type=accept,
            text=text,
            status_code=200,
            elapsed_ms=1.0,
            json=body if result_format == "json" else None,
        )

    async def aclose(self) -> None:
        """Mark the client closed."""
        self.closed = True


@pytest.fixture
def test_config() -> SparqlEndpointConfig:
    """A fast test endpoint configuration."""
    return SparqlEndpointConfig(timeout=5, max_retries=1, retry_delay=0.1)


@pytest.fixture
def service_factory(
    test_config: SparqlEndpointConfig,
) -> Callable[[list[tuple[str, dict[str, Any]]]], SparqlService]:
    """Return a factory building a SparqlService backed by a FakeSparqlClient."""

    def build(routes: list[tuple[str, dict[str, Any]]]) -> SparqlService:
        client = FakeSparqlClient(routes)
        return SparqlService(client, test_config)  # type: ignore[arg-type]

    return build
