# Docker

Build and run uniprot-link in the unified transport (REST `/health` + MCP `/mcp`).

```bash
# from the repo root
make docker-build      # docker compose -f docker/docker-compose.yml build
make docker-up         # start on http://localhost:8000
make docker-logs
make docker-down
```

The MCP streamable-HTTP endpoint is served at `/mcp`; `GET /health` is the
liveness probe used by the container `HEALTHCHECK`.

Set `UNIPROT_LINK_SPARQL__CONTACT_EMAIL` to your own mailbox — UniProt asks
programmatic clients to include a contact address in the User-Agent.
