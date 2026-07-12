# uniprot-link

An MCP (Model Context Protocol) + REST server that grounds protein research in the
**UniProt SPARQL endpoint** (`https://sparql.uniprot.org/sparql`). It wraps a
~232-billion-triple, QLever-backed SPARQL 1.1 service behind intent-named,
token-economical tools — and ships a safe raw-SPARQL escape hatch plus UniProt's
126 curated example queries so an LLM can learn and write its own queries.

Part of the `*-link` family of biomedical MCP servers (gnomad-link, gtex-link,
pubtator-link, genereviews-link, …) and follows their stack and conventions.

## Features

- **15 MCP tools** across discovery, raw SPARQL, the curated example catalog,
  proteins (UniProtKB), and taxonomy.
- **Typed protein tools** — `get_protein`, sequence, features (with FALDO
  coordinates), natural variants, diseases, GO terms, cross-references, id mapping.
- **`search_sparql_query`** — execute bounded SPARQL SELECT/ASK queries; graph-returning
  forms and `SERVICE` federation are rejected; auto-LIMIT on unbounded SELECTs; JSON/XML/
  CSV/TSV output.
- **Example catalog** — `search_example_queries` / `get_example_query` expose
  UniProt's 126 curated, executable queries (backed by the `sparql-examples` graph).
- **Agentic affordances** — every response carries `_meta.next_commands`
  (ready-to-run `{tool, arguments}` steps), a structured error taxonomy, and a
  `uniprot://capabilities` discovery resource.
- **Two transports** — unified (REST + MCP/HTTP) and HTTP-only. Streamable HTTP only.

## Quick start

```bash
make install                       # uv sync --group dev
make dev                           # unified server: REST on / and MCP on /mcp (port 8000)
uv run uniprot-link serve --help   # CLI: serve / config / health / version
make ci-local                      # format + lint + loc + typecheck + tests
```

### CLI

The `uniprot-link` console script is the single entry point (Streamable HTTP only):

```bash
uniprot-link serve --transport unified --host 127.0.0.1 --port 8000  # REST + MCP/HTTP
uniprot-link serve --transport http                                  # REST only
uniprot-link config --validate                                       # show + validate config
uniprot-link health --url http://127.0.0.1:8000                      # probe /health
uniprot-link version                                                 # print version
```

### Connect an MCP client

Point a Streamable-HTTP MCP client at the `/mcp` endpoint of a running server, e.g.:

```bash
claude mcp add --transport http uniprot-link --scope user http://127.0.0.1:8000/mcp
```

## Tool catalog

| Tool | Purpose |
|---|---|
| `get_server_capabilities` | Tools, 21 named graphs, prefixes, formats, workflows, limits |
| `search_sparql_query` | Execute bounded SELECT/ASK SPARQL (the power tool) |
| `search_example_queries` | Search 126 curated example queries |
| `get_example_query` | Full text + metadata of one example |
| `find_proteins` | Search UniProtKB by `gene_symbol` / organism / keyword / EC / mnemonic |
| `get_protein` | Core entry summary by accession |
| `get_protein_sequence` | Canonical + isoform sequences |
| `get_protein_features` | Sequence features with FALDO coordinates |
| `get_protein_variants` | Natural-variant annotations |
| `get_protein_diseases` | Disease annotations |
| `get_protein_cross_references` | Cross-references grouped by database |
| `get_protein_go_terms` | GO annotations by aspect |
| `resolve_identifiers` | Resolve an accession to external DB ids |
| `get_taxon` | Resolve a taxon by id or name |

> Tool names are **unprefixed** (the GeneFoundry Tool-Naming Standard v1): the
> server reports `serverInfo.name = "uniprot-link"` and its canonical gateway
> **namespace token is `uniprot`**. When federated behind the
> [`genefoundry-router`](https://github.com/berntpopp/genefoundry-router) gateway,
> tools surface as `uniprot_<tool>` (e.g. `uniprot_find_proteins`); standalone MCP
> clients already namespace them as `mcp__uniprot-link__<tool>`.

## Configuration

Environment variables (prefix `UNIPROT_LINK_`, nested with `__`):

| Variable | Default | Meaning |
|---|---|---|
| `UNIPROT_LINK_SPARQL__CONTACT_EMAIL` | `bernt.popp@charite.de` | Contact in the User-Agent (UniProt etiquette) |
| `UNIPROT_LINK_SPARQL__TIMEOUT` | `30` | End-to-end query deadline, including retries (s) |
| `UNIPROT_LINK_SPARQL__DEFAULT_LIMIT` | `50` | Auto-LIMIT for unbounded SELECTs |
| `UNIPROT_LINK_TRANSPORT` | `unified` | `unified` / `http` |
| `UNIPROT_LINK_PORT` | `8000` | Server port |
| `UNIPROT_LINK_ALLOWED_HOSTS` | loopback hosts | Exact accepted Host values; add the public proxy hostname. Wildcards are rejected. |
| `UNIPROT_LINK_ALLOWED_ORIGINS` | `[]` | Accepted browser Origins; requests without Origin remain allowed. |

Request Origin validation is separate from CORS response headers. A browser-facing
deployment must configure the same exact public HTTPS origin in both
`UNIPROT_LINK_ALLOWED_ORIGINS` and `UNIPROT_LINK_CORS_ORIGINS`.

## Development

See `AGENTS.md` for conventions (notably the **SPARQL / QLever discipline** that
keeps queries off the timeout cliff) and `docs/` for architecture and usage.
`research/verify_queries.py` validates every query builder against the live
endpoint.

## Disclaimer

Research use only; not for clinical decision support, diagnosis, treatment, or
patient management. UniProt data is licensed CC BY 4.0.

## License

MIT
