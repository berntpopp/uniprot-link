# Usage

## Run the server (Streamable HTTP)

```bash
make dev    # unified: REST on / and MCP (streamable-http) on /mcp, port 8000
# or, directly:
uniprot-link serve --transport unified --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
```

The server exposes its tool surface and a `uniprot://capabilities` resource at `/mcp`.

## CLI

The `uniprot-link` console script is the single entry point. Streamable HTTP only —
there is no SSE and no stdio transport.

```bash
uniprot-link serve --transport unified --host 127.0.0.1 --port 8000  # REST + MCP/HTTP
uniprot-link serve --transport http                                  # REST host only
uniprot-link config --validate                                       # show + validate config
uniprot-link health --url http://127.0.0.1:8000                      # probe /health
uniprot-link version                                                 # print version
```

`--transport http` serves the FastAPI host (`/health`, `/`) **without** the MCP
endpoint; MCP clients need `unified`. See [configuration.md](configuration.md) for
every environment variable.

## Connect an MCP client

Point any Streamable-HTTP MCP client at the running `/mcp` endpoint:

```bash
claude mcp add --transport http uniprot-link --scope user http://127.0.0.1:8000/mcp
```

## Typical workflows

**Look up an entry and drill in**

1. `get_protein` `{ "accession": "P05067" }`
2. follow `_meta.next_commands` → `get_protein_sequence`, `get_protein_features`,
   `get_protein_diseases`, `get_protein_cross_references`.

**Resolve a gene to an accession**

1. `find_proteins` `{ "gene_symbol": "BRCA1", "organism_taxon": 9606, "reviewed": true }`
2. `get_protein` with the returned accession (Swiss-Prot ranked first).

**Resolve an organism first**

1. `get_taxon` `{ "taxon": "Homo sapiens" }` → taxon id 9606
2. `find_proteins` `{ "gene_symbol": "TP53", "organism_taxon": 9606 }`

**Write your own SPARQL**

1. `search_example_queries` `{ "text": "disease" }`
2. `get_example_query` `{ "example_id": "<iri from step 1>" }`
3. `search_sparql_query` `{ "query": "<the example, edited>" }`

`search_example_queries` / `get_example_query` expose UniProt's 126 curated, executable
example queries, backed by the upstream `sparql-examples` graph
(`https://sparql.uniprot.org/.well-known/sparql-examples`). They are the fastest way to
learn the data model without guessing IRIs.

## search_sparql_query notes

- `result_format`: `json` (SELECT/ASK), or `csv`/`tsv`/`xml` for SELECT results.
- A `LIMIT` is auto-injected into unbounded SELECTs (see `_meta.limit_injected`
  and `truncated`). Pass `limit` to control it, or include your own `LIMIT`.
- `CONSTRUCT`, `DESCRIBE`, and `SERVICE` federation are rejected. Curated examples
  that use them are reference material, not directly executable through this tool.
- Anchor queries on an accession/gene/organism/keyword to stay within timeouts.

## Discovery resources

`uniprot://capabilities` (JSON), `uniprot://usage`, `uniprot://reference`,
`uniprot://prefixes` (the canonical PREFIX block), `uniprot://research-use`,
`uniprot://citation`.
