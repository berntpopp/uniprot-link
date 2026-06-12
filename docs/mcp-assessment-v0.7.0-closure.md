# uniprot-link MCP — v0.7.0 Closure Record (Arg-Contract & Discoverability Uplift)

Closes the findings of the v0.5.0 **cold-consumer** assessment
([`mcp-assessment-v0.5.0-consumer-session.md`](mcp-assessment-v0.5.0-consumer-session.md),
overall **7.5/10**). All findings shared one root cause: *argument validation was
not wrapped in the product's own error contract.* This release wraps it, makes
argument names discoverable up front, and lightens the discovery surface.

| Field | Value |
|-------|-------|
| Version | 0.6.0 → **0.7.0** |
| Spec | [`docs/superpowers/specs/2026-06-12-arg-contract-discoverability-design.md`](superpowers/specs/2026-06-12-arg-contract-discoverability-design.md) |
| Plan | [`docs/superpowers/plans/2026-06-12-arg-contract-discoverability.md`](superpowers/plans/2026-06-12-arg-contract-discoverability.md) |
| CI | `make ci-local` green (format, lint, line-budget ≤600, mypy strict, 160 unit tests) |
| Live check | PNKP cold path resolves `Q96T60` in **one** call (integration) |

---

## Root cause (verified in code)

FastMCP validates call arguments with pydantic inside `FunctionTool.run()` —
**before** the registered tool body executes. A wrong argument *name* (`taxon=`),
*type* (`organism_taxon="x"`), or a *missing required* argument therefore raised a
raw `pydantic.ValidationError` (with a `pydantic.dev` URL) that never reached
`run_mcp_tool`'s error boundary. The error an LLM hits most often in a cold
session was the one place the polished envelope did not cover.

The fix intercepts that error at a single FastMCP `on_call_tool` **middleware**
(`uniprot_link/mcp/middleware.py`), where the binding `ValidationError` propagates
unmasked, and returns a normal `ToolResult` carrying the standard envelope — one
change that covers all 14 tools and all three failure modes.

---

## Findings → Fixes → Evidence

### F1 — Argument-name discoverability (4 calls → 1) — **fixed**

- **Aliases:** curated synonyms normalize before dispatch — `taxon`, `organism`,
  `organism_id`, `taxid`, `tax_id`, `ncbi_taxon`, `species` → `organism_taxon`;
  plus `gene_symbol`→`gene`, `ec`→`ec_number`, `acc`/`uniprot_id`→`accession`, etc.
  (`uniprot_link/mcp/arg_help.py::ARG_ALIASES`). The rewrite is disclosed in
  `_meta.argument_aliases_applied`.
- **Signatures in descriptions:** every tool description ends with a canonical
  `Signature: find_proteins(gene=, organism_taxon=, reviewed=, ...)` line — the
  LLM's primary decision surface, so a competent first call needs no guessing.
- **Did-you-mean:** a non-alias near-miss gets a fuzzy suggestion (below).
- **Evidence:** `tests/integration/test_live.py::test_pnkp_resolves_in_one_call_with_taxon_alias`
  (live, one call, `argument_aliases_applied == [["taxon","organism_taxon"]]`);
  `tests/unit/test_arg_middleware.py::test_alias_normalized_and_disclosed`;
  drift guard `tests/unit/test_discovery_surface.py::test_signatures_match_live_schema_no_drift`.

### F2 — Arg errors bypass the envelope (raw pydantic) — **fixed**

`ArgValidationMiddleware` reshapes wrong-name, wrong-type, **and** missing-required
errors into the standard `invalid_input` envelope. A cold consumer now sees:

```json
{
  "success": false,
  "error_code": "invalid_input",
  "message": "Unknown argument `organism_taxa` for find_proteins. Did you mean `organism_taxon`? Valid argument names are listed in allowed_values.",
  "retryable": false,
  "recovery_action": "reformulate_input",
  "field": "organism_taxa",
  "allowed_values": ["gene", "organism_taxon", "reviewed", "keyword", "ec_number", "mnemonic", "name_contains", "limit", "offset"],
  "hint": "find_proteins(gene=, organism_taxon=, reviewed=, keyword=, ec_number=, mnemonic=, name_contains=, limit=, offset=)",
  "_meta": { "tool": "find_proteins", "request_id": "…", "next_commands": [ { "tool": "get_server_capabilities", "arguments": {} } ] }
}
```

No `pydantic.dev` URL; `error_code`, `recovery_action`, `field`, `allowed_values`,
`hint` (the signature), and `next_commands` are all present — identical surface to
value-level errors. **Note:** the wrong-*type* and missing-required cases also
leaked raw before this release (same code path); the assessment only caught the
wrong-name case, so this fix covers more than reported.

- **Evidence:** `tests/unit/test_arg_middleware.py` (`test_wrong_keyword_routes_through_envelope`,
  `test_wrong_type_routes_through_envelope`, `test_missing_required_routes_through_envelope`,
  `test_non_alias_near_miss_gets_did_you_mean`); `tests/unit/test_arg_help.py`
  (`build_arg_error_envelope`).

### F3 — Capabilities is the only discovery path, and it's heavy — **fixed**

- `get_server_capabilities(detail="summary"|"full")` — **summary is the new
  default** and is light: identity/build/release, the tool list **with
  signatures**, accepted argument aliases, response modes, workflows, error
  taxonomy, and limits. The heavy reference blocks (21 named graphs with triple
  counts, full prefix map, full latency bands, vocabularies) move behind
  `detail="full"`.
- New `uniprot://tools` resource — name + one-line summary + signature per tool,
  the lightest discovery surface.
- `build_capabilities()` and `uniprot://capabilities` remain full (back-compat).
- **Evidence:** `tests/unit/test_discovery_surface.py`
  (`test_capabilities_summary_is_default_and_light`,
  `test_capabilities_full_restores_heavy_blocks`,
  `test_tools_resource_lists_all_with_signatures`).

### F4 — The slow path is the entry path — **mitigated**

Largely *absorbed by F1/F2*: the three failed parameter guesses that used to sit
in front of the cold `find_proteins` call are gone, so the consumer pays the
one cold search latency, not four round-trips of friction plus it. The
`find_proteins` description also adds an explicit accession-first nudge ("if you
already know the accession, call get_protein directly — it is far faster"). The
underlying cold-QLever latency is inherent and remains documented (latency bands).

### F5 — Deploy drift (operational) — **version bumped; redeploy required**

The repo is now at **0.7.0**; the live server must be redeployed to catch up
(`server_version`/`git_sha` are exposed precisely so this drift is detectable).

**Redeploy steps (operator):**

```bash
make docker-build           # build the 0.7.0 image with a fresh build stamp
make docker-down && make docker-up   # recreate the container
make docker-url             # confirm; then re-read get_server_capabilities -> build.version == 0.7.0
```

---

## Projected score impact

| Dimension | Was | Now (projected) | Why |
|-----------|:---:|:---------------:|-----|
| Discoverability | 7 | **9.5** | signatures in descriptions + aliases + did-you-mean + `uniprot://tools`; PNKP 1 call |
| Token efficiency | 7 | **9** | summary capabilities default; param names visible without the heavy payload |
| Speed / latency | 7.5 | **8.5** | failed pre-calls removed; accession-first nudge (cold-QLever floor remains) |
| Observability | 9 | **9.5** | `argument_aliases_applied` disclosure; arg errors now carry `request_id` |
| Error handling / recovery | 6.5 | **9.5** | every binding failure (name/type/missing) routes through the envelope |
| Output quality / grounding | 9 | **9** | unchanged (already excellent) |
| **Overall** | **7.5** | **>9.5** | the shared root cause is closed; discovery is light and self-documenting |

## Changed/added modules

- New: `uniprot_link/mcp/arg_help.py`, `uniprot_link/mcp/middleware.py`.
- Modified: `mcp/envelope.py` (`build_arg_error_envelope`), `mcp/facade.py`
  (register middleware), `mcp/capabilities.py` (signatures + summary projection +
  `uniprot://tools`), `mcp/tools/discovery.py` (`detail` param),
  `mcp/tools/{proteins,query,taxonomy}.py` (signature lines + F4 nudge),
  `__init__.py`/`pyproject.toml`/`uv.lock` (0.7.0).
- Tests: `tests/unit/test_arg_help.py`, `test_arg_middleware.py`,
  `test_discovery_surface.py`; `tests/integration/test_live.py` (PNKP one-call).
