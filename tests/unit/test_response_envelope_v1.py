"""Locks the ratified GeneFoundry Response-Envelope Standard v1 (flat banner).

Adapted from clingen-link (fleet exemplar, PR #20:
https://github.com/berntpopp/clingen-link/pull/20) for this repo's actual
``uniprot_link.mcp.envelope`` pattern (Pattern B: a ``run_mcp_tool`` wrapper
plus a private ``_error_envelope`` builder and a public
``build_arg_error_envelope`` builder -- there is no ``run_mcp_tool``/
``mcp/errors.py`` combo like clingen-link and no ``build_meta`` function).

Ratified contract under test:

- SUCCESS: ``{"success": True, <payload>, "_meta": {...}}``.
- FAILURE: a FLAT in-band dict -- ``{"success": False, "error_code": <str>,
  "message": <str>, "retryable": <bool>, "recovery_action": <str>,
  "_meta": {...}}`` -- NEVER a bare exception, NEVER a nested ``error: {}``
  object.

Fleet decision (2026-07-03): ``_meta.unsafe_for_clinical_use`` must appear on
EVERY tool response -- success AND error, at all response_modes -- not once
via ``get_server_capabilities``. uniprot-link now stamps that key on every
per-call ``_meta`` dict (see ``uniprot_link/mcp/envelope.py``); the static
``research_use_only`` / ``research_use_notice`` fields in
``get_server_capabilities`` (see
``uniprot_link/mcp/capabilities.py::build_capabilities``) remain the source
of the full disclaimer text and citation/release provenance, which are still
declared once to conserve tokens -- see ``provenance_policy`` /
``per_call_meta`` in ``mcp/capabilities.py``. This is covered by the
pre-existing ``test_per_call_meta_is_lean`` / ``test_success_meta_is_lean``
tests in ``test_service_and_tools.py``, updated alongside this file rather
than duplicated here.

Other ground-truth drift vs the fleet-wide contract text (asserted here, not
papered over):

- Success payloads are NOT wrapped in a ``"results": [...]`` or
  ``"result": {...}`` envelope key. ``run_mcp_tool`` merges the tool's
  returned dict keys directly into the top-level envelope alongside
  ``success``/``_meta`` (see ``run_mcp_tool``'s ``result.setdefault(...)`` /
  ``result["_meta"] = ...`` mutation-in-place). This file asserts that
  ground truth rather than the wrapped shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from uniprot_link.exceptions import InvalidInputError, NotFoundError, RateLimitError
from uniprot_link.mcp.envelope import (
    McpErrorContext,
    McpToolError,
    build_arg_error_envelope,
    run_mcp_tool,
)


@pytest.mark.asyncio
async def test_success_envelope_is_flat_banner_no_wrapper_key() -> None:
    """Success: {"success": True, <payload merged flat>, "_meta": {...}}.

    No "results"/"result" wrapper key -- the tool's own payload keys land at
    the top level next to "success" and "_meta".
    """

    async def call() -> dict[str, Any]:
        return {"accession": "P05067", "mnemonic": "A4_HUMAN"}

    out = await run_mcp_tool("get_protein", call, context=McpErrorContext("get_protein"))

    assert out["success"] is True
    assert out["accession"] == "P05067"
    assert out["mnemonic"] == "A4_HUMAN"
    assert "results" not in out
    assert "result" not in out
    assert "error" not in out


@pytest.mark.asyncio
async def test_success_meta_guarantees_and_documented_drift() -> None:
    """Success _meta carries its documented dynamic keys.

    Fleet Response-Envelope Standard v1 (2026-07-03): every success envelope
    stamps the clinical-safety disclaimer per-call.
    """

    async def call() -> dict[str, Any]:
        return {"value": 1}

    out = await run_mcp_tool("get_protein", call, context=McpErrorContext("get_protein"))
    meta = out["_meta"]

    assert meta["tool"] == "get_protein"
    assert isinstance(meta["request_id"], str) and meta["request_id"]
    assert set(meta) <= {"tool", "request_id", "next_commands", "unsafe_for_clinical_use"}
    assert meta["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_error_envelope_is_flat_dict_never_raised() -> None:
    """A raised domain exception is CAUGHT and returned as a flat error dict.

    Never a bare exception, never a nested "error": {} object.
    """

    async def call() -> dict[str, Any]:
        raise NotFoundError("No records found for accession.")

    out = await run_mcp_tool("get_protein", call, context=McpErrorContext("get_protein"))

    assert out["success"] is False
    assert out["error_code"] == "not_found"
    assert isinstance(out["message"], str) and out["message"]
    assert out["retryable"] is False
    assert out["recovery_action"] == "reformulate_input"
    assert "error" not in out
    assert out["_meta"]["tool"] == "get_protein"
    assert isinstance(out["_meta"]["request_id"], str) and out["_meta"]["request_id"]
    assert "next_commands" in out["_meta"]
    # Fleet Response-Envelope Standard v1 (2026-07-03): error envelopes stamp
    # the clinical-safety disclaimer per-call too, not just on success.
    assert out["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_error_envelope_retryable_classification() -> None:
    """retryable/recovery_action are derived from the classified error_code."""

    async def call() -> dict[str, Any]:
        raise RateLimitError("UniProt SPARQL rate limit hit.")

    out = await run_mcp_tool("search_sparql_query", call)

    assert out["success"] is False
    assert out["error_code"] == "rate_limited"
    assert out["retryable"] is True
    assert out["recovery_action"] == "retry_backoff"
    assert "error" not in out
    assert out["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_error_envelope_unclassified_exception_becomes_internal_error() -> None:
    """An unrecognised exception never escapes -- it is classified as internal_error."""

    async def call() -> dict[str, Any]:
        raise RuntimeError("boom")

    out = await run_mcp_tool("get_protein", call, context=McpErrorContext("get_protein"))

    assert out["success"] is False
    assert out["error_code"] == "internal_error"
    assert out["retryable"] is False
    assert out["recovery_action"] == "switch_tool"
    assert "error" not in out
    assert out["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_error_envelope_mcp_tool_error_carries_custom_code() -> None:
    """McpToolError lets a tool body raise a specific code/message pair."""

    async def call() -> dict[str, Any]:
        raise McpToolError(error_code="invalid_input", message="bad accession shape")

    out = await run_mcp_tool("get_protein", call, context=McpErrorContext("get_protein"))

    assert out["success"] is False
    assert out["error_code"] == "invalid_input"
    assert out["message"] == "bad accession shape"
    assert out["retryable"] is False
    assert out["recovery_action"] == "reformulate_input"
    assert "error" not in out
    assert out["_meta"]["unsafe_for_clinical_use"] is True


@pytest.mark.asyncio
async def test_error_envelope_invalid_input_surfaces_field_and_hint() -> None:
    """InvalidInputError's field/allowed/hint are flat top-level keys, not nested."""

    async def call() -> dict[str, Any]:
        raise InvalidInputError(
            "Accession must be 6-10 characters.",
            field="accession",
            allowed=None,
            hint="e.g. P05067",
        )

    out = await run_mcp_tool("get_protein", call, context=McpErrorContext("get_protein"))

    assert out["success"] is False
    assert out["error_code"] == "invalid_input"
    assert out["field"] == "accession"
    assert out["hint"] == "e.g. P05067"
    assert "error" not in out
    assert out["_meta"]["unsafe_for_clinical_use"] is True


def test_build_arg_error_envelope_is_flat_dict() -> None:
    """The argument-binding error path (ArgValidationMiddleware) is also flat."""
    out = build_arg_error_envelope(
        tool_name="get_protein",
        loc="accession",
        error_type="missing_argument",
        valid_params=["accession", "response_mode"],
        signature="get_protein(accession: str, response_mode: str = 'compact')",
        suggestion=None,
    )

    assert out["success"] is False
    assert out["error_code"] == "invalid_input"
    assert isinstance(out["message"], str) and out["message"]
    assert out["retryable"] is False
    assert out["recovery_action"] == "reformulate_input"
    assert out["allowed_values"] == ["accession", "response_mode"]
    assert "error" not in out
    assert out["_meta"]["tool"] == "get_protein"
    assert isinstance(out["_meta"]["request_id"], str) and out["_meta"]["request_id"]
    assert "next_commands" in out["_meta"]
    assert out["_meta"]["unsafe_for_clinical_use"] is True
