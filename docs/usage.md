# Usage

## Connect Claude Desktop (stdio)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "uniprot-link": {
      "command": "uv",
      "args": ["--project", "/path/to/uniprot-link", "run", "python", "mcp_server.py"],
      "env": { "UNIPROT_LINK_SPARQL__CONTACT_EMAIL": "you@example.org" }
    }
  }
}
```

Restart Claude. The server exposes 15 tools and a `uniprot://capabilities` resource.

## HTTP transport

```bash
make dev    # unified: REST on / and MCP (streamable-http) on /mcp, port 8000
curl http://127.0.0.1:8000/health
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

## search_sparql_query notes

- `result_format`: `json` (SELECT/ASK), or `csv`/`tsv`/`xml`, or `turtle`/`rdfxml`/
  `ntriples` for CONSTRUCT/DESCRIBE.
- A `LIMIT` is auto-injected into unbounded SELECTs (see `_meta.limit_injected`
  and `truncated`). Pass `limit` to control it, or include your own `LIMIT`.
- `SERVICE` federation works (e.g. joining Rhea or OMA); see the curated examples.
- Anchor queries on an accession/gene/organism/keyword to stay within timeouts.

## Discovery resources

`uniprot://capabilities` (JSON), `uniprot://usage`, `uniprot://reference`,
`uniprot://prefixes` (the canonical PREFIX block), `uniprot://research-use`,
`uniprot://citation`.
