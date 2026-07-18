# uniprot-link MCP Assessment — v0.5.0 (cold-consumer session)

An independent, naturalistic LLM-consumer evaluation of the deployed uniprot-link
MCP server. Unlike the systematic tool-by-tool pass in
[`mcp-assessment-v0.5.0.md`](mcp-assessment-v0.5.0.md) (which reads
`get_server_capabilities` up front and exercises all 14 tools deliberately), this
pass simulates the **realistic cold path**: a model handed a domain task
(*"get domains for PNKP"*) that reaches for tools the way an LLM actually does —
without pre-reading the capabilities map. That methodology difference is why some
scores here are lower than the comprehensive pass; the friction recorded below is
exactly what the up-front-capabilities approach skips past.

> Companion to the comprehensive v0.5.0 pass. Both evaluate the same deployed
> build; this one captures argument-level discoverability and error-surface
> friction that a cold consumer hits in the first few calls.

## Test Context

| Field | Value |
|-------|-------|
| Date | 2026-06-12 |
| Server | `uniprot-link` |
| Server version (deployed) | 0.5.0 |
| Build | git_sha `f7233d6`, built_at `2026-06-12T12:01:33Z` |
| Repo HEAD (disk) | v0.6.0 (`62954de`) — **deployed server is one minor version behind** |
| UniProt release | 2026_01 |
| Endpoint | https://sparql.uniprot.org/sparql (QLever) |
| Evaluator | Claude (Fable 5), LLM consumer of the MCP |
| Method | A real task (PNKP → domains) driven cold, plus targeted error/verbosity probes — ~8 live calls, no up-front capabilities read |
| Primary fixtures | Q96T60 (PNKP), Q99999999 (bad-format accession), P00000 (DEFGA_MYTGA) |
| Scope note | Single naturalistic session. Scores reflect the cold-consumer experience, not a systematic coverage pass. |

---

## Part 1 — Consumer Experience Assessment

Scored 1–10 per dimension, with the evidence each score rests on.

### Overall: 7.5 / 10

A genuinely well-engineered, agent-first research MCP — observability and
grounding well above the typical bar, with clever touches (the region-vs-domain
hint, `next_commands` chaining, once-only provenance). Pulled down almost
entirely by two early-friction items that share **one root cause**: argument
validation is not wrapped in the product's own error contract. Fix that and this
is a 9.

> The comprehensive v0.5.0 pass scored 8.7 because it read capabilities first and
> never guessed an argument name. This pass is lower precisely because it didn't —
> which is the more realistic LLM-consumer scenario.

### Scores

| Dimension | Score | Basis |
|-----------|:----:|-------|
| Discoverability | 7 | `get_server_capabilities` is a complete map and the proactive hints are excellent — but resolving PNKP's accession took **4 calls instead of 1**: `taxon`, `organism`, and `organism_id` were all rejected before capabilities revealed the parameter is `organism_taxon`. The server instructions say "organism (taxon id)" but never give the literal argument name. |
| Token efficiency | 7 | Compact default `response_mode`; static provenance declared once in capabilities (`provenance_policy`) rather than per-call; `next_commands`/hints save round-trips. Deduction: capabilities is the only discovery path and it's heavy (21 graphs with triple counts, full prefix map, latency bands) — I had to read all of it to learn one parameter name. |
| Speed / latency | 7.5 | Honestly documented latency bands + a real 1h cache with a `cached` flag. Observed: `get_protein` 916 ms, features 1.75–2.0 s, `find_proteins` cold 5.9 s. Deduction: the natural entry point (gene → accession via `find_proteins`) is the slow path, and each failed parameter guess also sat in front of it. |
| Observability | 9 | Every response carries `_meta.request_id`; data responses carry `elapsed_ms` + `cached`; capabilities exposes `server_version` + `build{version, git_sha, built_at}` + `uniprot_release`. Good enough that I could *detect* the deployed server (0.5.0/`f7233d6`) lags the repo (0.6.0). |
| Error handling / recovery | 6.5 | Value-level errors are best-in-class (see below). But argument-name errors bypass the envelope and leak a **raw pydantic `ValidationError`** with a `pydantic.dev` docs URL — no `error_code`, no `recovery_action`, no `next_commands`. This is the error an LLM hits *most often*, so it's the worst place to drop the contract. |
| Output quality / grounding | 9 | Typed structured output, no raw IRIs in compact mode, `recommended_name`, `function` with inline PubMed/evidence refs, ECO/GO evidence codes, `recommended_citation`. The `domain_region_hint` bakes real domain expertise into the tool. |

---

## Part 2 — Findings & Recommended Improvements

Ordered by leverage (highest first).

### F1 — Argument-name discoverability (the biggest real cost)

Getting PNKP's accession took four calls instead of one. I tried `taxon`,
`organism`, and `organism_id` (all rejected) before `get_server_capabilities`
revealed the parameter is `organism_taxon`. The one-line tool blurbs say
"organism (taxon id)" but never give the literal argument name, so a model
reaches for the obvious synonyms first.

**Fixes (cheapest first):**

- Accept aliases: `taxon` / `organism` / `organism_id` → `organism_taxon`.
- Put canonical signatures in the tool blurbs, listing the then-current `gene`
  argument followed by `organism_taxon`, `reviewed`, `keyword`, `ec_number`, `mnemonic`,
  and `name_contains`.

### F2 — Error-handling inconsistency (most fixable; shares F1's root cause)

Value-level errors are excellent. `get_protein("Q99999999")` returned:

```json
{
  "success": false,
  "error_code": "invalid_input",
  "message": "'Q99999999' is not a valid UniProtKB accession (e.g. P05067, P38398, or an isoform like P05067-2).",
  "retryable": false,
  "recovery_action": "reformulate_input",
  "field": "accession",
  "_meta": { "tool": "get_protein", "request_id": "5a2bdd05ce7f", "next_commands": [ ... ] }
}
```

But an *argument-name* mistake bypasses that envelope entirely:

```
1 validation error for call[find_proteins]
taxon
  Unexpected keyword argument [type=unexpected_keyword_argument, input_value='9606', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/unexpected_keyword_argument
```

No `error_code`, no recovery hint, no `next_commands`, and a pydantic-docs URL
that is useless to an LLM consumer.

**Fix:** catch the validation error at the MCP boundary and reshape it into the
standard envelope — `error_code: invalid_input`, a message **listing the valid
parameter names**, a did-you-mean suggestion, `recovery_action: reformulate_input`,
and `next_commands → get_server_capabilities`. This single change resolves both
F1 and F2 and is the highest-leverage fix available.

> Note: v0.6.0's closure notes mention dropping the accession-schema `min_length`
> so a bad accession **value** routes through the envelope — but the raw-pydantic
> case here is a wrong argument **name** (`Unexpected keyword argument`), a
> distinct failure mode that the value-level fix does not cover.

### F3 — Capabilities is the only discovery path, and it's heavy

I had to pull the entire capabilities payload (21 named graphs with triple
counts, the full prefix map, latency bands) just to learn one parameter name.

**Fix:** a lighter discovery surface — a `uniprot://tools` resource or a
`tools`-only capabilities mode returning just tool signatures — and move bulky
reference blocks (triple counts, prefix map) behind `full`/a dedicated resource.

### F4 — The slow path is the entry path

`find_proteins` cold was ~5.9 s, vs `get_protein`-by-accession at ~0.9 s. Since
gene → accession is the usual first hop, it's the latency users feel first.
Inherent to the live QLever backend; softened by the cache and documented bands.
Pre-warming common gene lookups, or nudging consumers toward accession-first when
the accession is known, would help.

### F5 — Deploy drift (operational, not code)

The connected MCP reports **v0.5.0 / `f7233d6`** while the repo is at **v0.6.0**
(`62954de`). To the server's credit, this is *detectable at all* only because
`server_version`/`git_sha` are exposed. Redeploy (`make docker-build` + container
recreate) is the fix.

---

## Part 3 — Worked Session Evidence

The scores above rest on this real task: *"get domains for PNKP."*

1. **`find_proteins` with the then-canonical `gene="PNKP"` and rejected
   `taxon="9606"` arguments** → rejected,
   raw pydantic `Unexpected keyword argument: taxon`.
2. **`organism="9606"`** → rejected (raw pydantic).
3. **`organism_id="9606"`** → rejected (raw pydantic).
4. **`get_server_capabilities()`** → learned the parameter is `organism_taxon`;
   confirmed deployed build 0.5.0 / `f7233d6`.
5. **`find_proteins` with the then-canonical `gene="PNKP"`,
   `organism_taxon="9606"`, and `reviewed=true` arguments** →
   `Q96T60` (PNKP_HUMAN, "Bifunctional polynucleotide phosphatase/kinase"),
   `elapsed_ms` 5935.5, `cached` false.
6. **`get_protein_features("Q96T60", feature_types=["domain"])`** → 1 feature
   (FHA domain, 6–110), plus a `domain_region_hint` advising a re-query with
   `region` to capture catalytic architecture. `elapsed_ms` 2040.2.
7. **`get_protein_features("Q96T60", feature_types=["domain","region"])`** →
   full architecture, `elapsed_ms` 1750.2:

   | Region | Residues | Type |
   |--------|----------|------|
   | FHA (forkhead-associated) | 6–110 | domain |
   | Disordered linker | 109–143 | region |
   | Phosphatase | 146–337 | region |
   | Kinase | 341–516 | region |

   The `domain_region_hint` was the single best UX moment: UniProt types only the
   FHA as a formal `domain`; the catalytic phosphatase and kinase modules are
   `region` features. The hint taught the data model exactly when needed.

**Error/verbosity probes:**

- `get_protein("Q99999999")` → clean `invalid_input` envelope (see F2).
- `get_protein("P00000")` → a real entry (DEFGA_MYTGA, a *Mytilus
  galloprovincialis* defensin); compact mode returned `recommended_name`,
  organism, `mass_da`, and `function` with inline PubMed evidence in ~916 ms —
  good evidence for the token-efficiency and grounding scores.

---

## Bottom line

**7.5 / 10.** Thoughtfully engineered, research-grade, with observability and
grounding above the typical bar. Held back almost entirely by argument-level
discoverability and error handling — the same root issue: argument validation
isn't wrapped in the product's own error contract. Reshape arg-validation
failures into the existing envelope with valid-name suggestions, and this is a 9.
Independently: **redeploy** — the live server is a version behind the repo.
