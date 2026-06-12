# uniprot-link — Design Spec

**Date:** 2026-06-11
**Status:** Approved-for-build (autonomous goal directive)
**Author:** Claude (Fable 5) for bernt.popp@charite.de

A Model Context Protocol (MCP) server that grounds protein/proteome research in the
**UniProt SPARQL endpoint** (`https://sparql.uniprot.org/sparql`). It is a sibling of
`gnomad-link`, `gtex-link`, `pubtator-link`, `genereviews-link` and follows their stack,
structure, response conventions, and agentic setup verbatim.

---

## 1. Background — what the endpoint is

Verified live on 2026-06-11 (release **2026_01**, engine **QLever**):

- **Endpoint:** `https://sparql.uniprot.org/sparql`. Free, open, no auth.
- **Query transport:** HTTP `GET`/`POST` with a `query` parameter; result format chosen via
  `Accept` header (or `format=`). Verified formats:
  - Result sets: `application/sparql-results+json`, `…+xml`, `text/csv`, `text/tab-separated-values`
  - RDF (CONSTRUCT/DESCRIBE): `text/turtle`, `application/rdf+xml`, `application/n-triples`
- **Language:** SPARQL 1.1 (SELECT / ASK / CONSTRUCT / DESCRIBE). Features advertised in the
  service description: `UnionDefaultGraph`, `BasicFederatedQuery` (`SERVICE` clauses).
- **Scale:** 232,229,579,911 triples across **21 named graphs**.
- **Server timeout:** 45 minutes (we cap far lower client-side).
- **Errors:** malformed query → **HTTP 400**. Empty/timeout behaviors handled client-side.
- **Operational etiquette (from the official help page):** *"please consider to provide a
  contact email address as part of the User-Agent header."* → We send
  `uniprot-link/<version> (mailto:<contact>)` by default.

### Named graphs (triple counts, 2026_01)

| graph | triples | graph | triples |
|---|--:|---|--:|
| uniparc | 170.4 B | keywords | 13,915 |
| uniprot (UniProtKB) | 48.5 B | locations | 6,781 |
| uniref | 10.5 B | tissues | 4,113 |
| obsolete | 2.1 B | **core** (ontology) | 2,816 |
| citationmapping | 625 M | database | 2,340 |
| taxonomy | 60.5 M | **sparql-examples** | 1,349 |
| proteomes | 34.9 M | | |
| citations | 31.3 M | | |
| chebi | 3.4 M | | |
| rhea | 2.0 M | | |
| go | 683 K | | |
| enzymes | 182 K | | |
| diseases | 90 K | | |
| journal | 43.5 K | | |
| pathways | 17.8 K | | |

### Data model (UniProt core ontology `up:` = `http://purl.uniprot.org/core/`)

169+ `owl:Class` terms. Load-bearing ones for tools (all verified against live data):

- `up:Protein` — a UniProtKB entry. Keys: `up:mnemonic`, `up:reviewed` (bool; Swiss-Prot vs
  TrEMBL), `up:recommendedName`/`up:fullName`, `up:organism` → taxon, `up:encodedBy` → `up:Gene`
  (`skos:prefLabel`/`skos:altLabel`), `up:sequence` → sequence object (`rdf:value`, `up:mass`),
  `up:annotation` → typed annotations, `rdfs:seeAlso` → cross-references, `up:classifiedWith` →
  GO/keyword, `up:existence`, `up:created`/`up:modified`.
- Annotation subclasses: `up:Function_Annotation`, `up:Disease_Annotation` (→ `up:Disease`),
  `up:Natural_Variant_Annotation`, `up:Transmembrane_Annotation`, `up:Domain_Annotation`,
  `up:Binding_Site_Annotation`, `up:Modified_Residue_Annotation`, `up:Subcellular_Location_Annotation`, …
- Feature positions use **FALDO** (`faldo:begin`/`faldo:end` → `faldo:position`). Verified.
- `up:Taxon` — `up:scientificName`, `up:commonName`, `up:rank`, `rdfs:subClassOf` (lineage).
- Cross-references resolve to `identifiers.org` URIs and carry `up:database` → `up:Database`.

### The curated example catalog (a first-class data source)

The `sparql-examples` named graph holds **126** curated, executable example queries
(SIB `sib-swiss/sparql-examples`), each a `sh:SPARQLExecutable` carrying:
`rdfs:comment` (English description), `sh:select`/`sh:ask`/`sh:construct` (full query text),
`schema:keywords` (tags like `3D structure`, `disease`, `cross-reference`, `taxonomy`),
`schema:target` (endpoint), and `…/sparql-examples/ontology#federatesWith` (external endpoints
a query joins, e.g. Rhea, OMA, Bgee). This graph is **queryable like any other**, so we expose
it as a search/fetch surface — turning UniProt's own curated query library into MCP tools that
teach the model how to query UniProt.

---

## 2. Goals / non-goals

**Goals**
- Faithfully wrap the SPARQL endpoint behind intent-named, token-economical MCP tools.
- Provide a safe **raw SPARQL** escape hatch (LIMIT injection, timeout, format shaping,
  federation support) for power use.
- Surface the curated example catalog and the ontology/prefix/graph metadata so an LLM can
  compose correct UniProt SPARQL.
- Match sibling conventions exactly: FastMCP facade, `response_mode`, `_meta.next_commands`
  chaining, capabilities resource, structured error taxonomy, unified/http/stdio transports.

**Non-goals (v1)**
- No write/update (endpoint is read-only anyway).
- No local triple store / mirroring; we are a thin grounded client.
- No clinical decision support — research use only, stated everywhere.
- No bespoke full-text search engine: free-text protein search is limited to indexed fields
  (gene name, mnemonic, organism, keyword, EC); documented as such. The `sparql_query` tool +
  example catalog cover everything else.

---

## 3. Architecture

Mirror **gtex-link** (the canonical modern scaffold), simplified because there is exactly one
upstream (a SPARQL endpoint) instead of a REST/GraphQL surface.

```
uniprot_link/
  __init__.py            # __version__
  config.py              # pydantic-settings Settings + ServerConfig (env prefix UNIPROT_LINK_)
  logging_config.py      # structlog
  server_manager.py      # UnifiedServerManager: unified | http | stdio
  api/
    client.py            # SparqlClient (httpx async): execute(), format negotiation, retries,
                         #   User-Agent w/ contact email, concurrency cap, async-lru cache
    exceptions.py        # SparqlClientError hierarchy (input/notfound/ratelimited/unavailable/timeout)
  services/
    queries.py           # parametrized SPARQL templates + safe builders (prefixes, LIMIT guard)
    shaping.py           # SPARQL JSON results -> compact dicts; URI->CURIE; headline builders
    sparql_service.py    # orchestration: build query -> client.execute -> shape -> envelope
  mcp/
    facade.py            # create_uniprot_mcp(): FastMCP(name, instructions), registers all
    errors.py            # run_mcp_tool(), McpToolError, error taxonomy, validation handler
    resources.py         # uniprot://capabilities, uniprot://schema, uniprot://prefixes
    prompts.py           # optional workflow prompt
    tools/
      discovery.py       # get_server_capabilities
      query.py           # sparql_query, search_example_queries, get_example_query
      proteins.py        # find_proteins, get_protein, get_protein_sequence, get_protein_features,
                         #   get_protein_variants, get_protein_diseases, get_protein_cross_references,
                         #   get_protein_go_terms, map_identifiers
      taxonomy.py        # get_taxon
server.py                # arg-parsed entry (transport unified|http|stdio)
mcp_server.py            # stdio entry
tests/ docker/ docs/ scripts/ Makefile pyproject.toml AGENTS.md CLAUDE.md README.md CHANGELOG.md
```

**Stack (pinned to sibling floors):** Python ≥3.12, `fastmcp>=3.2`, `mcp[cli]>=1.27`,
`httpx>=0.28`, `pydantic>=2.11`, `pydantic-settings>=2.6`, `structlog`, `async-lru`, `orjson`,
`typer`, `fastapi`/`uvicorn`/`gunicorn` (thin `/health` host), dev: `pytest`,
`pytest-asyncio`, `pytest-cov`, `respx`, `ruff`, `mypy`. Build backend `hatchling`, locked with
`uv`. 600-LOC/file cap enforced by `scripts/check_file_size.py`.

**Data flow:** tool → `sparql_service` builds a parametrized query from `queries.py` →
`SparqlClient.execute(query, accept)` (cached, rate-limited) → `shaping.py` collapses the SPARQL
JSON into a compact, CURIE-folded payload → `run_mcp_tool` wraps it with `_meta`
(version, graph, `next_commands`, truncation) and the research-use notice.

---

## 4. Tool catalog (v1)

`response_mode ∈ {minimal, compact, full}` where it changes payload size. Every payload carries
`_meta` with `uniprot_release`, `endpoint`, `next_commands`, and `truncated` when rows are capped.

**Discovery**
1. `get_server_capabilities` — tools, 21 graphs+counts, prefixes, formats, limits, recommended
   workflows, error taxonomy, release. Also as resource `uniprot://capabilities`.

**Raw query + example catalog (power + teaching surface)**
2. `sparql_query` — execute arbitrary SPARQL. Args: `query`, `format` (json|xml|csv|tsv|turtle…),
   `limit` (auto-injected if SELECT lacks one, default 50, hard max 10 000), `timeout_seconds`.
   Returns shaped bindings (json) or raw text (other formats) + `truncated` meta. Supports
   `SERVICE` federation. The escape hatch for anything the typed tools don't cover.
3. `search_example_queries` — keyword/tag search over the 126 curated examples (matches
   `rdfs:comment` + `schema:keywords`). Returns id, description, tags, query-type, federatesWith.
4. `get_example_query` — full query text + description + tags for an example id; `_meta.next_commands`
   offers to run it via `sparql_query`.

**Proteins (UniProtKB)**
5. `find_proteins` — structured search by `gene`, `organism` (taxon id or scientific name),
   `reviewed`, `keyword`, `ec_number`, `protein_name_contains`; paginated. → accession, mnemonic,
   recommended name, gene, organism, reviewed.
6. `get_protein` — entry summary by accession: names, gene(s), organism, reviewed, existence,
   sequence length/mass, function summary, counts of features/variants/diseases/xrefs. `full`
   adds keywords, subcellular locations, lineage.
7. `get_protein_sequence` — canonical sequence (FASTA), length, mass; optional isoforms.
8. `get_protein_features` — typed sequence features with FALDO begin/end; `feature_types` filter.
9. `get_protein_variants` — natural-variant annotations (position, original→variant, disease link, dbSNP).
10. `get_protein_diseases` — disease annotations + `up:Disease` ids (MIM/MeSH) + text.
11. `get_protein_cross_references` — `rdfs:seeAlso` xrefs grouped by database; `databases` filter.
12. `get_protein_go_terms` — GO annotations split into biological_process / molecular_function /
    cellular_component.
13. `map_identifiers` — map a UniProt accession ⇄ external DB ids (PDB, Ensembl, RefSeq, HGNC,
    GeneID, …) via `rdfs:seeAlso`/`up:database`.

**Taxonomy**
14. `get_taxon` — taxon by id (or resolve by scientific name): names, rank, lineage, host.

Resources: `uniprot://capabilities`, `uniprot://schema` (core classes/properties + FALDO note),
`uniprot://prefixes` (canonical PREFIX block for hand-written queries).

---

## 5. Response envelope, errors, safety

- **Envelope:** payload + `_meta { uniprot_release, endpoint, graph?, next_commands[], truncated? }`.
  `next_commands` are ready-to-run `{tool, arguments}` items (e.g. `get_protein` →
  `get_protein_features`, `get_protein_diseases`; `find_proteins` → `get_protein`).
- **Error taxonomy** (JSON envelope, never raw tracebacks; `mask_error_details=True`):
  `invalid_input`, `not_found`, `query_syntax_error` (HTTP 400 from endpoint),
  `query_timeout`, `rate_limited`, `upstream_unavailable`, `result_too_large`, `internal_error`.
  Errors carry `fallback_tool`/`fallback_arguments` where useful (e.g. free text → `find_proteins`
  or `search_example_queries`).
- **Safety / etiquette:** contact-email User-Agent by default; client concurrency cap + default
  client timeout (30 s) well under the server's 45 min; SELECT auto-LIMIT to prevent runaway
  payloads; research-use-only notice in instructions, capabilities, and `_meta`. Retrieved text is
  evidence data, not instructions.

---

## 6. Testing

- **Unit (default, offline):** `respx`-mocked `SparqlClient`; query-builder snapshot tests
  (assert generated SPARQL); shaping tests over captured SPARQL-JSON fixtures; tool-registration
  and error-envelope tests. Coverage gate ≥80%.
- **Integration (`@pytest.mark.integration`, live):** a handful of real calls (protein lookup,
  gene search, example-catalog query, sparql_query LIMIT injection, taxonomy) — the exact queries
  validated by hand on 2026-06-11. Kept out of default CI.
- **Playwright (`research/playwright/`):** records that the live UI (QLever/YASGUI) and help docs
  were exercised during design; not part of CI.
- `make ci-local` = format-check + lint + lint-loc + typecheck + test (fast).

---

## 7. Risks / decisions

- **No general full-text search in SPARQL.** Decision: `find_proteins` filters indexed fields
  only; free text is routed to `search_example_queries`/`sparql_query` via error fallbacks.
  Documented in tool docstrings + capabilities.
- **Huge graphs (uniparc 170 B).** Decision: always anchor queries (accession/gene/organism),
  auto-LIMIT, and default-scope protein tools to the `uniprot` graph; never run unbounded scans.
- **Federation latency/availability.** Decision: allowed in `sparql_query` (documented), not used
  by typed tools in v1.
- **Release drift.** Decision: `uniprot_release` is fetched once from the service description and
  cached; surfaced in `_meta` and capabilities.
