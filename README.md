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
- **`search_sparql_query`** — execute any SPARQL 1.1 query (SELECT/ASK/CONSTRUCT/
  DESCRIBE, with `SERVICE` federation); auto-LIMIT on unbounded SELECTs; JSON/XML/
  CSV/TSV/Turtle/RDF-XML/N-Triples output.
- **Example catalog** — `search_example_queries` / `get_example_query` expose
  UniProt's 126 curated, executable queries (backed by the `sparql-examples` graph).
- **Agentic affordances** — every response carries `_meta.next_commands`
  (ready-to-run `{tool, arguments}` steps), a structured error taxonomy, and a
  `uniprot://capabilities` discovery resource.
- **Three transports** — unified (REST + MCP/HTTP), HTTP-only, and stdio.

## Quick start

```bash
make install          # uv sync --group dev
make dev              # unified server: REST on / and MCP on /mcp (port 8000)
make mcp-serve        # stdio MCP server (for Claude Desktop)
make ci-local         # format + lint + loc + typecheck + tests
```

### Connect Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "uniprot-link": {
      "command": "uv",
      "args": ["--project", "/path/to/uniprot-link", "run", "python", "mcp_server.py"]
    }
  }
}
```

## Tool catalog

| Tool | Purpose |
|---|---|
| `get_server_capabilities` | Tools, 21 named graphs, prefixes, formats, workflows, limits |
| `search_sparql_query` | Execute any SPARQL 1.1 query (the power tool / federation) |
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
| `UNIPROT_LINK_SPARQL__TIMEOUT` | `30` | Per-request timeout (s) |
| `UNIPROT_LINK_SPARQL__DEFAULT_LIMIT` | `50` | Auto-LIMIT for unbounded SELECTs |
| `UNIPROT_LINK_TRANSPORT` | `unified` | `unified` / `http` / `stdio` |
| `UNIPROT_LINK_PORT` | `8000` | Server port |

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
