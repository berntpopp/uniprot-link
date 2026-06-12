# Design — Argument Contract & Discoverability Uplift (v0.7.0)

**Goal:** Take the cold-consumer assessment score from **7.5/10 to >9.5/10** by
closing the two early-friction findings that share one root cause — *argument
validation is not wrapped in the product's own error contract* — plus the
discovery-surface and latency findings that compound them.

Source assessment: [`docs/mcp-assessment-v0.5.0-consumer-session.md`](../../mcp-assessment-v0.5.0-consumer-session.md).

## Background & Root Cause (verified in code)

The server is a **FastMCP 3.4.2** app. Every tool body is wrapped by
`run_mcp_tool` (`uniprot_link/mcp/envelope.py`), which converts exceptions into a
structured envelope (`success:false`, `error_code`, `message`, `recovery_action`,
`_meta.next_commands`). This makes **value-level** errors best-in-class.

But an **argument-name / argument-type** mistake never reaches that wrapper.
FastMCP validates call arguments with `pydantic`'s `validate_python` **inside
`FunctionTool.run()` — before the registered tool body runs**. A wrong keyword
(`taxon=`) raises a `pydantic.ValidationError`
(`type='unexpected_keyword_argument'`) that propagates up through the middleware
chain and is surfaced raw, with a `pydantic.dev` docs URL. This is the error an
LLM hits *most often* in a cold session, so it is the worst place to drop the
contract.

Empirically confirmed end-to-end (real server + probe middleware):

| Call | pydantic `errors()[0]` | Reaches `run_mcp_tool`? |
|------|------------------------|--------------------------|
| `find_proteins(taxon="9606", ...)` | `unexpected_keyword_argument`, loc `('taxon',)` | **No** — raised in `run()`, leaks raw |
| `find_proteins(organism_taxon="notanint")` | `int_parsing`, loc `('organism_taxon',)` | **No** — leaks raw (assessment missed this; same root cause) |
| `find_proteins(organism_taxon=9606)` (no anchor) | n/a — passes binding | **Yes** — already enveloped correctly |

**Key architectural fact (verified):** an `on_call_tool` **FastMCP middleware**
wraps `call_next`, and the binding `ValidationError` propagates up to it
*unmasked* (it is caught-and-re-raised in the server core, not converted to a
`ToolResult`). A middleware can therefore catch it and return a normal
`ToolResult` carrying our envelope. **One middleware fixes the leak for all 14
tools uniformly** — far better than per-tool try/except.

## Scope — Findings Addressed

| # | Finding | Fix | Dimension lifted |
|---|---------|-----|------------------|
| F1 | Arg-name discoverability (4 calls → 1) | Canonical signature in every tool description + curated alias acceptance + did-you-mean | Discoverability, Token efficiency |
| F2 | Arg errors bypass the envelope (raw pydantic) | `ArgValidationMiddleware` reshapes binding errors into the standard envelope | Error handling |
| F3 | Capabilities is the only discovery path, and it's heavy | `uniprot://tools` resource + `detail=summary\|full` on `get_server_capabilities` (heavy blocks behind `full`) | Token efficiency, Discoverability |
| F4 | Slow path is the entry path | Largely *absorbed by F1/F2* (the failed pre-calls vanish) + accession-first nudge in the `find_proteins` blurb | Speed/latency |
| F5 | Deploy drift (0.5.0 deployed vs 0.6.0 disk) | Version bump to 0.7.0 + documented redeploy in the closure record (operational; cannot self-deploy) | (operational) |

**Out of scope (YAGNI):** gene→accession pre-warming caches; reworking the SPARQL
builders; changing the success-payload shape of any tool; protocol-level
(`isError`) error reporting (we keep errors inside the result object, per MCP
best practice and the server's existing contract).

## Architecture

Three cooperating, independently-testable units. New code is small, cohesive,
and well under the 600-line module cap.

### 1. `uniprot_link/mcp/arg_help.py` (new, pure functions — no FastMCP import)

The single source of truth for argument ergonomics. Pure and fully unit-testable.

- `ARG_ALIASES: dict[str, str]` — curated synonym → canonical map, scoped to this
  server's small param space. Seed set (highest-frequency guesses from the
  assessment): `taxon`, `organism`, `organism_id`, `taxid`, `tax_id`,
  `ncbi_taxon` → `organism_taxon`; `gene_symbol`, `gene_name` → `gene`;
  `ec` → `ec_number`; `acc`, `uniprot`, `uniprot_id`, `id` → `accession`;
  `query_text`, `q`, `text` already canonical where applicable. Alias targets are
  only applied when the canonical target is a real parameter of *that* tool.
- `normalize_alias_args(valid_params, arguments) -> tuple[dict, list[tuple[str,str]]]`
  — returns rewritten args plus the `(alias, canonical)` pairs applied. An alias is
  applied only if (a) the alias key is present, (b) the canonical key is a valid
  param of the tool, and (c) the canonical key is not already supplied. Never
  overwrites an explicit canonical value.
- `did_you_mean(unknown: str, valid: Iterable[str]) -> str | None` — alias map
  first (authoritative), then `difflib.get_close_matches` (cutoff 0.6) as fallback.
- `tool_signature(name: str, schema: dict) -> str` — renders
  `find_proteins(gene=, organism_taxon=, reviewed=, ...)` from a JSON input
  schema (required params first, then optional; omit injected/context params).

### 2. `uniprot_link/mcp/middleware.py` (new — `ArgValidationMiddleware`)

Subclasses `fastmcp.server.middleware.Middleware`, overrides `on_call_tool`:

1. Resolve the called tool's valid param names from the registry
   (`tool.parameters["properties"]`), cached per tool name.
2. **Alias normalization (F1 round-trip elimination):** rewrite
   `context.message.arguments` via `normalize_alias_args` *before* `call_next`. On
   success, annotate the returned `ToolResult`'s `_meta` with
   `argument_aliases_applied: [["taxon","organism_taxon"], ...]` (transparent, so a
   long-running consumer learns the canonical names).
3. `try: return await call_next(context)`.
4. `except PydanticValidationError as exc:` build the standard envelope via a new
   `build_arg_error_envelope(...)` helper in `envelope.py`, and return it as a
   `ToolResult(structured_content=envelope, content=[TextContent(json)])`,
   `is_error=False` (identical surface to value-level errors). The envelope:
   - `error_code: "invalid_input"`, `recovery_action: "reformulate_input"`,
     `retryable: false`
   - `message`: names the offending key, the **did-you-mean** suggestion when one
     exists, and that valid names are listed below — capped at 280 chars
   - `field`: the offending param/loc; `allowed_values`: the full valid-param list
   - `hint`: the canonical `tool_signature(...)` string
   - `_meta.next_commands`: `get_server_capabilities` (+ the corrected call when a
     single confident did-you-mean exists)

Handles `unexpected_keyword_argument` (wrong name), `missing_argument` (omitted
required), and coercion errors (`int_parsing`, `bool_parsing`, …) uniformly.

### 3. Discovery surface (F3) — `capabilities.py`, `resources.py`, `discovery.py`

- **`uniprot://tools` resource (new):** introspects the live registry and returns
  a compact JSON list — `{name, summary (first sentence), signature, required_anchor}`
  per tool. The lightweight discovery path: learn every param name without the
  heavy capabilities payload.
- **`get_server_capabilities(detail="summary"|"full")`:** `summary` (new default)
  returns identity/build/release, tool list **+ signatures**, response modes,
  recommended workflows, error codes, limits, and a one-line latency note. `full`
  restores the heavy reference blocks (21 named graphs with triple counts, full
  prefix map, full latency bands, vocabularies). `build_capabilities()` itself is
  unchanged (stays full) so `uniprot://capabilities` and existing tests keep
  working; the tool *projects* a summary view from it.

### 4. Tool descriptions (F1 primary) — each `tools/*.py`

Append a `Signature: name(arg=, arg=, ...)` line to every tool's `description`
(the LLM's primary decision surface). `find_proteins` is the critical one;
`find_proteins` also gains an accession-first nudge (F4): *"If you already know
the accession, call get_protein directly — it is far faster than a cold search."*

### Wiring — `facade.py`

`create_uniprot_mcp()` calls `mcp.add_middleware(ArgValidationMiddleware())` after
tool registration.

## Data Flow (the fixed cold path)

```
LLM: find_proteins(gene="PNKP", taxon="9606", reviewed=true)
  → ArgValidationMiddleware.on_call_tool
      → normalize_alias_args: taxon → organism_taxon  (canonical free)
      → call_next succeeds → result._meta.argument_aliases_applied=[["taxon","organism_taxon"]]
  → Q96T60 in ONE call (was 4)

LLM (alias not in map): find_proteins(species="9606")
  → call_next raises ValidationError(unexpected_keyword_argument, 'species')
  → envelope: invalid_input, did_you_mean? none → lists valid params + signature,
    next_commands→get_server_capabilities  (was raw pydantic; now 2 calls, self-correcting)
```

## Error Handling

- Middleware catches only `pydantic.ValidationError` from `call_next`; all other
  exceptions propagate unchanged (body errors are already enveloped inside
  `run_mcp_tool` and returned as dicts, so they never reach the middleware as
  exceptions — no double-handling).
- Alias normalization never overwrites an explicit canonical value and only maps
  to real params of the called tool — so it cannot silently change intent.
- `mask_error_details=True` is unaffected: the middleware returns a `ToolResult`
  (no exception), so masking never engages on the arg-error path.

## Testing Strategy (TDD)

Unit (no network; `respx` for any upstream):
- `arg_help`: alias normalization (applied / not-overwriting / wrong-tool-param
  ignored), did-you-mean (alias hit, fuzzy hit, no hit), signature rendering.
- Middleware via the real facade (`create_uniprot_mcp().call_tool(...)`):
  - wrong name, non-alias near-miss (`organism_taxa`) → enveloped `invalid_input`
    with `allowed_values`, `hint` signature, fuzzy did-you-mean
    `organism_taxa→organism_taxon`, `next_commands`. (A name *in* the alias map,
    e.g. `taxon`, is normalized instead — covered by the alias-success test.)
  - wrong type (`organism_taxon="x"`) → enveloped, not raw.
  - missing required (`get_protein()` with no accession) → enveloped.
  - alias success (`taxon="9606"`) → resolves + `_meta.argument_aliases_applied`.
  - explicit canonical + alias both present → canonical wins, no clobber.
  - happy paths and existing value-level error tests still pass unchanged.
- Discovery: `uniprot://tools` lists all 14 with signatures; `detail=summary`
  omits `named_graphs`/`prefixes`; `detail=full` includes them; signatures match
  the live schema (a drift guard).
- Version bump 0.6.0 → 0.7.0 (update 3 existing assertions).

Integration (`@pytest.mark.integration`, live endpoint): the PNKP cold path now
resolves `Q96T60` in one `find_proteins` call using `taxon=`.

`make ci-local` must pass (format, lint, lint-loc ≤600, mypy strict, tests).

## Success Criteria

1. No tool surfaces a raw pydantic `ValidationError` for any wrong name, wrong
   type, or missing required argument — all route through the envelope with valid
   names + a did-you-mean + `next_commands`.
2. The assessment's PNKP cold path resolves in **one** `find_proteins` call (via
   alias or signature-informed first call), not four.
3. Param names are discoverable without reading the heavy capabilities payload:
   visible in `tools/list` signatures and the `uniprot://tools` resource.
4. `make ci-local` green; version 0.7.0; closure record maps findings→fixes→evidence.
5. Projected dimension scores: Discoverability ≥9.5, Error handling ≥9.5, Token
   efficiency ≥9, Speed ≥8.5 → **overall >9.5**.
