# Docker

The container files live here; the runbook lives in
[`../docs/deployment.md`](../docs/deployment.md) — local stack, the digest-pinned
`docker-compose.prod.yml` and Nginx-Proxy-Manager `docker-compose.npm.yml` overlays,
the Host/Origin boundary, and the release gate.

Build and run uniprot-link in the unified transport (REST `/health` + MCP `/mcp`).

```bash
# from the repo root
make docker-build      # docker compose -f docker/docker-compose.yml build
make docker-up         # start (loopback-bound; UNIPROT_LINK_HOST_PORT, default 8013)
make docker-url        # print the MCP URL
make docker-logs
make docker-down
```

The MCP streamable-HTTP endpoint is served at `/mcp`; `GET /health` is the
liveness probe used by the container `HEALTHCHECK`.

Set `UNIPROT_LINK_SPARQL__CONTACT_EMAIL` to your own mailbox — UniProt asks
programmatic clients to include a contact address in the User-Agent.

HTTP requests use exact Host and Origin allowlists. Add the public proxy hostname
to `UNIPROT_LINK_ALLOWED_HOSTS`; browser deployments must set the same HTTPS origin
in `UNIPROT_LINK_ALLOWED_ORIGINS` and `UNIPROT_LINK_CORS_ORIGINS`.
