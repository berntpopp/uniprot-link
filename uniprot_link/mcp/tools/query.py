"""SPARQL power tool and curated example-catalog tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from uniprot_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from uniprot_link.mcp.envelope import McpErrorContext, run_mcp_tool
from uniprot_link.mcp.next_commands import after_get_example, cmd
from uniprot_link.mcp.schemas import (
    EXAMPLE_DETAIL_SCHEMA,
    EXAMPLE_LIST_SCHEMA,
    SPARQL_RESULT_SCHEMA,
)
from uniprot_link.mcp.service_adapters import get_sparql_service

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_query_tools(mcp: FastMCP) -> None:
    """Register the raw-query and example-catalog tools."""

    @mcp.tool(
        name="run_sparql_query",
        output_schema=SPARQL_RESULT_SCHEMA,
        title="Run SPARQL Query",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"sparql", "power"},
        description=(
            "Execute an arbitrary SPARQL 1.1 query against the UniProt endpoint "
            "(SELECT / ASK / CONSTRUCT / DESCRIBE, including SERVICE federation to "
            "Rhea, OMA, Bgee, etc.). SELECT results come back as columns+rows JSON; "
            "ASK as a boolean; CONSTRUCT/DESCRIBE as raw RDF in the chosen format. A "
            "LIMIT is auto-injected into unbounded SELECTs (see `_meta`/`truncated`). "
            "This is the escape hatch for anything the typed tools do not cover -- "
            "seed queries from search_example_queries. Use uniprot://prefixes for the "
            "standard PREFIX block. Unbounded or federated queries can take 10-60 s; "
            "bound lookups (anchored on an accession/gene/taxon) return in <2 s."
        ),
    )
    async def run_sparql_query(
        query: Annotated[
            str,
            Field(
                description="A complete SPARQL 1.1 query string.",
                min_length=8,
                max_length=20000,
            ),
        ],
        result_format: Annotated[
            Literal["json", "xml", "csv", "tsv", "turtle", "rdfxml", "ntriples"],
            Field(description="Result serialisation. Use json for SELECT/ASK."),
        ] = "json",
        limit: Annotated[
            int | None,
            Field(description="LIMIT to inject when a SELECT lacks one (capped at 10000).", ge=1),
        ] = None,
        timeout_seconds: Annotated[
            int | None,
            Field(description="Per-call timeout override in seconds.", ge=1, le=120),
        ] = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            return await service.run_query(
                query,
                result_format=result_format,
                limit=limit,
                timeout=float(timeout_seconds) if timeout_seconds else None,
            )

        return await run_mcp_tool(
            "run_sparql_query",
            call,
            context=McpErrorContext("run_sparql_query", fallback=cmd("search_example_queries")),
        )

    @mcp.tool(
        name="search_example_queries",
        output_schema=EXAMPLE_LIST_SCHEMA,
        title="Search Example Queries",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"sparql", "examples"},
        description=(
            "Search UniProt's 126 curated, executable SPARQL example queries by "
            "free text over their descriptions and keyword tags (e.g. 'disease', "
            "'3D structure', 'cross-reference', 'taxonomy'). Returns example ids, "
            "descriptions, tags, and query types. Fetch the full query text with "
            "get_example_query, then run it via run_sparql_query. The best way to "
            "learn how to query UniProt."
        ),
    )
    async def search_example_queries(
        text: Annotated[
            str | None,
            Field(description="Free-text filter over descriptions and keywords.", max_length=200),
        ] = None,
        limit: Annotated[int, Field(description="Max examples to return.", ge=1, le=126)] = 25,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.search_examples(text, limit)
            ids = [e["example_id"] for e in payload["examples"][:3] if e.get("example_id")]
            if ids:
                payload["_meta"] = {"next_commands": [cmd("get_example_query", example_id=ids[0])]}
            return payload

        return await run_mcp_tool(
            "search_example_queries", call, context=McpErrorContext("search_example_queries")
        )

    @mcp.tool(
        name="get_example_query",
        output_schema=EXAMPLE_DETAIL_SCHEMA,
        title="Get Example Query",
        annotations=READ_ONLY_OPEN_WORLD,
        tags={"sparql", "examples"},
        description=(
            "Fetch one curated example's full SPARQL text, description, keyword tags, "
            "and any federated endpoints it joins. Pass an example_id (full IRI) from "
            "search_example_queries. `_meta.next_commands` offers to run it directly "
            "via run_sparql_query."
        ),
    )
    async def get_example_query(
        example_id: Annotated[
            str,
            Field(description="Full example IRI from search_example_queries.", min_length=10),
        ],
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            service = get_sparql_service()
            payload = await service.get_example(example_id)
            payload["_meta"] = {"next_commands": after_get_example(payload.get("query"))}
            return payload

        return await run_mcp_tool(
            "get_example_query", call, context=McpErrorContext("get_example_query")
        )
