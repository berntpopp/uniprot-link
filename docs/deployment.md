# Deployment

uniprot-link is stateless: there is no database, no data bundle, and no build step.
The container starts serving immediately and queries the live UniProt SPARQL endpoint
on every call. Every variable named here is documented in
[configuration.md](configuration.md).

The public GeneFoundry instance is `https://uniprot-link.genefoundry.org/mcp`.

## Local container

```bash
make docker-build      # docker compose -f docker/docker-compose.yml build
make docker-up         # start (loopback-bound)
make docker-url        # print the MCP URL + a ready-to-paste `claude mcp add` line
make docker-logs
make docker-down
```

The base Compose file publishes container port 8000 on host port
`${UNIPROT_LINK_HOST_PORT:-8013}` and binds it to `127.0.0.1` — copying that file to a
server therefore never publishes the unauthenticated backend on the public IP (Docker
otherwise binds `0.0.0.0` and bypasses the host firewall). `make docker-url` discovers
the effective port. The Compose project is explicitly named `uniprot-link` so it does
not pool with sibling `-link` stacks that also root their Compose at
`docker/docker-compose.yml`.

Set `UNIPROT_LINK_SPARQL__CONTACT_EMAIL` to your own mailbox — UniProt asks
programmatic clients to include a contact address in the User-Agent.

## Production overlays

Two overlays sit on top of the base file, both hardened per the fleet
Container & Deployment Hardening Standard (non-root, `read_only` rootfs,
`cap_drop: ALL`, `no-new-privileges`, `init`, pids/memory/cpu limits) and both
**unpublished** (`ports: !reset []` / `expose` only) — the backend is unauthenticated
by design and must be reachable only through the reverse proxy or the router.

- `docker/docker-compose.prod.yml` — runs a **digest-pinned** image:
  `UNIPROT_LINK_IMAGE=ghcr.io/berntpopp/uniprot-link@sha256:<digest>` is required and
  the stack fails to start without it.
- `docker/docker-compose.npm.yml` — the Nginx-Proxy-Manager variant; joins the shared
  external proxy network (`NPM_SHARED_NETWORK_NAME`, default `npm_default`) plus an
  internal bridge network.

Both overlays set the production boundary explicitly:

```yaml
UNIPROT_LINK_ALLOWED_HOSTS:   '["localhost","127.0.0.1","::1","uniprot-link.genefoundry.org"]'
UNIPROT_LINK_ALLOWED_ORIGINS: '["https://uniprot-link.genefoundry.org"]'
UNIPROT_LINK_CORS_ORIGINS:    '["https://uniprot-link.genefoundry.org"]'
```

Substitute your own public hostname. The allowlists are **exact** — wildcards are
rejected at startup — so the public reverse-proxy hostname must be listed in
`UNIPROT_LINK_ALLOWED_HOSTS` or every proxied request is refused. TLS terminates at
the proxy.

## Health

`GET /health` is the liveness probe used by the container `HEALTHCHECK` (the check
sends an explicit `Host:` header so it satisfies the Host guard). It reports the
running version and the build provenance below.

## Release gate

The running MCP server can silently lag the source — the typed tools serving old
behaviour while the SPARQL endpoint is fresh. To prevent a release being considered
"done" while the deployed process is stale:

1. Build with provenance:
   `UNIPROT_LINK_GIT_SHA=$(git rev-parse --short HEAD)` and
   `UNIPROT_LINK_BUILT_AT=$(date -u +%FT%TZ)`. Both surface in `GET /health` and in
   `get_server_capabilities().build`.
2. Redeploy.
3. Gate the release: `python scripts/check_deployed_version.py <prod-url>` must exit 0
   — the deployed `/health` version must equal `uniprot_link.__version__`. Do not
   close the release until it passes.
