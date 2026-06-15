# Architecture

uniprot-link is a thin, stateless MCP server in front of a single upstream: the
UniProt SPARQL endpoint. There is no local database — every tool call builds a
parametrized SPARQL query, executes it, and shapes the result.

```
MCP client (Claude, …)
        │  streamable-HTTP (/mcp)
        ▼
FastMCP facade  (uniprot_link/mcp/facade.py)
        │  @mcp.tool functions -> run_mcp_tool envelope
        ▼
SparqlService   (uniprot_link/services/sparql_service.py)
   build query (queries.py) → execute (api/client.py) → shape (shaping.py)
        │  HTTPS POST  (query=…, Accept: …)
        ▼
https://sparql.uniprot.org/sparql   (QLever, SPARQL 1.1, 21 named graphs)
```

## Layers

| Layer | Module | Responsibility |
|---|---|---|
| CLI / Transport | `cli.py`, `server_manager.py` | `uniprot-link serve` → unified / http boot |
| Host | `app.py` | FastAPI `/health` + `/` (thin) |
| Facade | `mcp/facade.py` | build FastMCP, register tools + resources |
| Tools | `mcp/tools/*` | typed tool signatures, `_meta.next_commands` |
| Envelope | `mcp/envelope.py` | `success`/`_meta` injection, error taxonomy |
| Discovery | `mcp/capabilities.py`, `mcp/resources.py` | capabilities + `uniprot://` resources |
| Service | `services/sparql_service.py` | orchestrate build → execute → shape, caching |
| Queries | `services/queries.py` | parametrized SPARQL builders + validation |
| Shaping | `services/shaping.py` | SPARQL-JSON → compact payloads |
| Client | `api/client.py` | httpx, rate limiting, retries, format negotiation |
| Config | `config.py` | pydantic-settings (`UNIPROT_LINK_` env prefix) |

## Why a SPARQL backend shapes the design

UniProt's endpoint runs on **QLever**, which is extremely fast for *bound* joins
but can hit the 45-minute server timeout on a few query shapes. The query
builders deliberately avoid those shapes:

- **Anchor every query** on an accession, gene, organism, or keyword — never scan
  `?p a up:Protein` unbounded.
- **Required joins over OPTIONAL** for universally-present fields (mnemonic,
  reviewed, organism) so the planner does bound joins.
- **Expand FALDO ranges to explicit hops** instead of `range/faldo:begin/position`
  property paths inside `OPTIONAL`.
- **Isolate aggregation** (`GROUP_CONCAT`) in sub-SELECTs; never `GROUP BY` over
  large literals (sequences, comments).
- **Sort small result sets in Python** (`shaping.py`) rather than `ORDER BY` over
  a large pre-LIMIT set.

These rules are encoded throughout `queries.py` and documented in `AGENTS.md`.
`research/verify_queries.py` re-validates every builder against the live endpoint.

## Response contract

Every tool returns a dict with `success` and `_meta`. `_meta.next_commands` is a
ready-to-run list of `{tool, arguments}` so an agent can advance without guessing.
Errors are returned (not raised) as `{success: false, error_code, message,
retryable, recovery_action}`.
