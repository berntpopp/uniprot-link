# Configuration

All settings load from environment variables with the `UNIPROT_LINK_` prefix. Nested
models use a double underscore (e.g. `UNIPROT_LINK_SPARQL__TIMEOUT=45`). A `.env` file
in the working directory is read automatically; `.env.example` is the annotated
template. Defaults live in `uniprot_link/config.py` and are the source of truth.

`uniprot-link config --validate` prints the effective configuration and validates it.

## Upstream (SPARQL)

The UniProt SPARQL endpoint is free and requires **no authentication**. UniProt
etiquette does, however, ask programmatic clients to identify themselves with a
contact mailbox in the `User-Agent` — set `UNIPROT_LINK_SPARQL__CONTACT_EMAIL` to a
mailbox you actually read. The User-Agent is built as
`uniprot-link/<version> (mailto:<contact_email>)`.

| Variable | Default | Meaning |
|---|---|---|
| `UNIPROT_LINK_SPARQL__BASE_URL` | `https://sparql.uniprot.org/sparql` | Endpoint URL (trailing slash stripped) |
| `UNIPROT_LINK_SPARQL__CONTACT_EMAIL` | `bernt.popp@charite.de` | Contact mailbox in the User-Agent (UniProt etiquette) |
| `UNIPROT_LINK_SPARQL__TIMEOUT` | `30` | End-to-end query deadline in seconds — includes rate limiting, retries, time-to-first-byte, and response reading |
| `UNIPROT_LINK_SPARQL__RATE_LIMIT_PER_SECOND` | `3.0` | Client-side token-bucket rate |
| `UNIPROT_LINK_SPARQL__BURST_SIZE` | `5` | Token-bucket burst |
| `UNIPROT_LINK_SPARQL__MAX_RETRIES` | `2` | Retries on transient 429/5xx/network failures |
| `UNIPROT_LINK_SPARQL__RETRY_DELAY` | `1.0` | Base delay (s) for exponential backoff |
| `UNIPROT_LINK_SPARQL__DEFAULT_LIMIT` | `50` | `LIMIT` auto-injected into unbounded SELECTs |
| `UNIPROT_LINK_SPARQL__MAX_LIMIT` | `10000` | Hard cap on any SELECT `LIMIT` |
| `UNIPROT_LINK_SPARQL__MAX_RESPONSE_BYTES` | `33554432` (32 MiB) | Hard cap on a streamed response body; the request **errors** past it and never truncates (a partial result set is unparseable). Keep it **above** the 8 MiB untrusted-text fence |

## Server & transport

Streamable HTTP only — there is no SSE and no stdio entry point.

| Variable | Default | Meaning |
|---|---|---|
| `UNIPROT_LINK_TRANSPORT` | `unified` | `unified` (FastAPI `/health` + `/` **and** MCP at `/mcp`) or `http` (REST host only) |
| `UNIPROT_LINK_HOST` | `127.0.0.1` | Bind address (the container sets `0.0.0.0` behind its own boundary) |
| `UNIPROT_LINK_PORT` | `8000` | Bind port |
| `UNIPROT_LINK_MCP_PATH` | `/mcp` | MCP endpoint path |
| `UNIPROT_LINK_RELOAD` | `false` | Auto-reload on code change. Development only — never set it in a container |
| `UNIPROT_LINK_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `UNIPROT_LINK_LOG_FORMAT` | `console` | `console` or `json` (containers use `json`) |
| `UNIPROT_LINK_CACHE__SIZE` | `512` | Max cached query results (`0` disables) |
| `UNIPROT_LINK_CACHE__TTL` | `3600` | Cache TTL in seconds |

Build provenance — `UNIPROT_LINK_GIT_SHA` and `UNIPROT_LINK_BUILT_AT` — surfaces in
`GET /health` and `get_server_capabilities().build`. See
[deployment.md](deployment.md) for the release gate that uses it.

## Host / Origin / CORS

Every HTTP route is gated by **exact** allowlists. These three knobs are distinct and
are a common source of confusion:

| Variable | Default | Meaning |
|---|---|---|
| `UNIPROT_LINK_ALLOWED_HOSTS` | `["localhost","127.0.0.1","::1"]` | Exact `Host` header values the request guard accepts. **Wildcards are rejected** (`*`, `?`, `[`, `]` raise at startup) |
| `UNIPROT_LINK_ALLOWED_ORIGINS` | `[]` | Exact browser `Origin` values the request guard accepts. Requests with **no** `Origin` header (i.e. non-browser clients) remain allowed |
| `UNIPROT_LINK_CORS_ORIGINS` | `["http://localhost:3000","http://127.0.0.1:3000"]` | Origins echoed in CORS **response** headers |

Request-`Origin` validation is **separate** from CORS response headers. A
browser-facing deployment must configure the same exact public HTTPS origin in
**both** `UNIPROT_LINK_ALLOWED_ORIGINS` and `UNIPROT_LINK_CORS_ORIGINS`, and add the
public reverse-proxy hostname to `UNIPROT_LINK_ALLOWED_HOSTS` — otherwise the guard
rejects proxied requests before any handler runs.

The lists accept either a JSON array (`'["localhost","::1"]'`, used by the Compose
files) or a comma-separated string.
