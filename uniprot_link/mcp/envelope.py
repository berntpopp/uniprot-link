"""MCP envelope boundary: success/_meta injection and structured errors.

Tools return a plain dict; :func:`run_mcp_tool` injects ``success`` and
``_meta`` on success, and converts any exception into a structured error dict
(returned, never raised) so the LLM sees a typed failure rather than an opaque
masked message.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from uniprot_link.exceptions import (
    InvalidInputError,
    NotFoundError,
    ObsoleteEntryError,
    QuerySyntaxError,
    QueryTimeoutError,
    RateLimitError,
    ServiceUnavailableError,
)
from uniprot_link.mcp.next_commands import cmd, default_error_next_commands
from uniprot_link.mcp.untrusted_content import UntrustedTextLimitError, sanitize_message

logger = logging.getLogger(__name__)

# Per-call _meta carries dynamic fields (tool, request_id, next_commands) plus
# the fleet-standard unsafe_for_clinical_use disclaimer, which per the
# GeneFoundry Response-Envelope Standard v1 (2026-07-03 fleet decision) must be
# stamped on EVERY tool response -- success and error, at all response_modes --
# not declared once via get_server_capabilities. Static provenance (research-use
# restriction, citation DOI, UniProt release) still lives only in
# get_server_capabilities to conserve context tokens.
_RETRYABLE = {"rate_limited", "upstream_unavailable"}
_UNSAFE_FOR_CLINICAL_USE = True


@dataclass
class McpErrorContext:
    """Per-call context so envelopes can name the failing tool and recovery."""

    tool_name: str
    fallback: dict[str, Any] | None = field(default=None)
    arguments: dict[str, Any] = field(default_factory=dict)


class McpToolError(Exception):
    """Raised inside a tool body to emit a specific error code/message."""

    def __init__(self, *, error_code: str, message: str) -> None:
        """Store an error code and client-safe message."""
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _request_id() -> str:
    return uuid.uuid4().hex[:12]


def _safe_message(exc: BaseException) -> str:
    # Sanitize every exception-derived message: upstream response bodies are
    # severed at the API client (never interpolated into an exception), but strip
    # the fence's forbidden control/zero-width/bidi/NUL code points as a defensive
    # backstop so nothing hostile can reach the caller-visible error frame.
    return sanitize_message(str(exc) or exc.__class__.__name__)


def _classify(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_code, client_safe_message)`` for an exception.

    ``error_code`` is the closed fleet enum (Response-Envelope Standard v1):
    ``invalid_input`` / ``not_found`` / ``ambiguous_query`` /
    ``upstream_unavailable`` / ``rate_limited`` / ``internal``. UniProt's own
    finer-grained conditions map ONTO the canon: a malformed SPARQL query or an
    over-broad response is ``invalid_input`` (the caller reformulates); a query
    timeout is an ``upstream_unavailable`` (the endpoint did not answer in time);
    an unclassified fault is ``internal``.
    """
    if isinstance(exc, McpToolError):
        return exc.error_code, exc.message
    # Exceeding an untrusted-text ceiling means the request was too broad -> the
    # caller must narrow it (invalid_input), never a masked internal fault. Checked
    # before the ValueError fallthrough (UntrustedTextLimitError subclasses it).
    if isinstance(exc, UntrustedTextLimitError):
        return "invalid_input", _safe_message(exc)
    if isinstance(exc, NotFoundError):
        return "not_found", _safe_message(exc)
    if isinstance(exc, InvalidInputError):
        return "invalid_input", _safe_message(exc)
    if isinstance(exc, QuerySyntaxError):
        # A malformed SPARQL query the caller must fix -> invalid_input.
        return "invalid_input", _safe_message(exc)
    if isinstance(exc, QueryTimeoutError):
        return (
            "upstream_unavailable",
            "The query timed out. Add filters/LIMIT or anchor on an accession, then retry.",
        )
    if isinstance(exc, RateLimitError):
        return "rate_limited", "UniProt SPARQL rate limit hit. Retry shortly."
    if isinstance(exc, ServiceUnavailableError):
        return "upstream_unavailable", "The UniProt SPARQL endpoint is temporarily unavailable."
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "input"
        return "invalid_input", f"Invalid input -- `{loc}`: {first['msg']}"
    return "internal", "An internal error occurred. The request was not completed."


def _recovery_action(error_code: str) -> str:
    if error_code in _RETRYABLE:
        return "retry_backoff"
    if error_code in {"invalid_input", "not_found", "ambiguous_query"}:
        return "reformulate_input"
    return "switch_tool"


def _error_envelope(exc: BaseException, context: McpErrorContext) -> dict[str, Any]:
    error_code, message = _classify(exc)
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        # Defensive: no forbidden code points reach the caller, whatever the path.
        "message": sanitize_message(message),
        "retryable": error_code in _RETRYABLE,
        "recovery_action": _recovery_action(error_code),
        "_meta": {
            "tool": context.tool_name,
            "request_id": _request_id(),
            "unsafe_for_clinical_use": _UNSAFE_FOR_CLINICAL_USE,
        },
    }
    # Structured recovery data (kept OUT of the length-capped message).
    if isinstance(exc, InvalidInputError):
        if exc.field is not None:
            envelope["field"] = exc.field
        if exc.allowed is not None:
            envelope["allowed_values"] = exc.allowed
        if exc.hint is not None:
            envelope["hint"] = exc.hint
    # An obsolete/demerged entry: flag it and chain to the live replacement(s).
    # ``exc.replaced_by`` is guaranteed strictly-valid: ObsoleteEntryError validates
    # (and omits) upstream accessions at construction, so no invalid/hostile value can
    # reach the replaced_by field or the recovery ``next_commands`` accession argument.
    if isinstance(exc, ObsoleteEntryError):
        envelope["obsolete"] = True
        envelope["replaced_by"] = exc.replaced_by
        if exc.replaced_by:
            envelope["_meta"]["next_commands"] = [
                cmd("get_protein", accession=acc) for acc in exc.replaced_by[:2]
            ]
            return envelope  # explicit replacement chain wins over the defaults
    # next_commands on EVERY error: explicit fallback, else a sensible default.
    if context.fallback is not None:
        envelope["_meta"]["next_commands"] = [context.fallback]
    else:
        envelope["_meta"]["next_commands"] = default_error_next_commands(
            context.tool_name, error_code, context.arguments
        )
    return envelope


# Fixed, caller-echo-free message for an unknown/unavailable tool. Built from a
# CONSTANT only: sanitation strips forbidden code points but PRESERVES injection
# prose, so a fixed constant is the only safe source for a caller-visible frame
# (error-sanitation-sweep rule). Never interpolate the requested tool name.
_UNKNOWN_TOOL_MESSAGE = "The requested tool is not available. Call get_server_capabilities."


def build_unknown_tool_envelope() -> dict[str, Any]:
    """Fixed, name-free ``not_found`` envelope for an unknown/unavailable tool.

    FastMCP core reflects the caller's OWN requested tool name (``Unknown tool:
    '<name>'``) BEFORE this repo's middleware runs. The not-found guard's Layer-1
    preflight returns this envelope instead, so the caller-supplied name -- and any
    control/zero-width/bidi/NUL code points it carries -- never reaches the caller
    frame. ``_meta.tool`` is ``None`` so the requested name is never echoed back.
    """
    return {
        "success": False,
        "error_code": "not_found",
        "message": _UNKNOWN_TOOL_MESSAGE,
        "retryable": False,
        "recovery_action": "switch_tool",
        "_meta": {
            "tool": None,
            "request_id": _request_id(),
            "next_commands": [cmd("get_server_capabilities")],
            "unsafe_for_clinical_use": _UNSAFE_FOR_CLINICAL_USE,
        },
    }


def build_arg_error_envelope(
    *,
    tool_name: str,
    loc: str,
    error_type: str,
    valid_params: list[str],
    signature: str,
    suggestion: str | None,
    enum_values: list[Any] | None = None,
    value_message: str | None = None,
) -> dict[str, Any]:
    """Standard invalid-input envelope for an argument-binding failure.

    Used by :class:`~uniprot_link.mcp.middleware.ArgValidationMiddleware` so a wrong
    argument *name*, *type*, *missing required* argument, or invalid enum *value*
    routes through the same contract instead of leaking a raw pydantic
    ``ValidationError``.

    Three categories, each with the correct ``allowed_values`` semantics (F1):

    - missing required / unknown name -> ``allowed_values`` are the argument
      *names* ("Valid argument names are listed in allowed_values").
    - invalid enum *value* (``enum_values`` given) -> ``allowed_values`` are the
      field's valid *values* ("Valid values are listed in allowed_values").
    - other value error (``value_message`` given, no enum) -> no fabricated value
      list; the pydantic reason is folded into the message.
    """
    # ``loc`` is the caller-supplied argument NAME (unknown/invalid arg) -- it is
    # attacker-influenceable and is surfaced BOTH inside ``message`` and verbatim in
    # the ``field`` key. Sanitize it once, up front, so no forbidden control/
    # zero-width/bidi/NUL code point reaches either representation.
    loc = sanitize_message(loc)
    allowed: list[Any] | None = valid_params
    if error_type in {"missing_argument", "missing"}:
        head = f"Missing required argument `{loc}` for {tool_name}."
        tail = " Valid argument names are listed in allowed_values."
    elif enum_values is not None:
        head = f"Invalid value for argument `{loc}` of {tool_name}."
        tail = " Valid values are listed in allowed_values."
        allowed = enum_values
    elif value_message is not None:
        head = f"Invalid value for argument `{loc}` of {tool_name}: {value_message.rstrip('.')}."
        tail = ""
        allowed = None  # no enum -> never invent a value list
    else:
        head = f"Unknown argument `{loc}` for {tool_name}."
        tail = " Valid argument names are listed in allowed_values."
    dym = f" Did you mean `{suggestion}`?" if suggestion else ""
    message = f"{head}{dym}{tail}"
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": "invalid_input",
        # The pydantic reason (value_message) can echo caller-influenced input;
        # sanitize + length-cap it like every other caller-visible message.
        "message": sanitize_message(message),
        "retryable": False,
        "recovery_action": "reformulate_input",
        "field": loc,
        "hint": signature,
        "_meta": {
            "tool": tool_name,
            "request_id": _request_id(),
            "next_commands": [cmd("get_server_capabilities")],
            "unsafe_for_clinical_use": _UNSAFE_FOR_CLINICAL_USE,
        },
    }
    if allowed is not None:
        envelope["allowed_values"] = allowed
    return envelope


def promote_error_result(result: Any) -> Any:
    """Set MCP ``isError: true`` on a ToolResult whose envelope is a domain error.

    ``run_mcp_tool`` returns error envelopes as a plain ``dict`` (``success:
    false`` / ``error_code``), which FastMCP serialises into a ``ToolResult`` with
    ``isError: false`` -- so a client that branches on ``isError`` reads the error
    as a SUCCESSFUL call (Response-Envelope Standard v1: "``isError: true`` is
    REQUIRED so clients surface the error to the model for self-correction"). This
    promotes any such result. Import lazily so this module stays free of a hard
    FastMCP dependency at import time; a non-ToolResult (or an already-error one)
    is returned unchanged.
    """
    from fastmcp.tools.tool import ToolResult

    if not isinstance(result, ToolResult) or result.is_error:
        return result
    structured = result.structured_content
    if isinstance(structured, dict) and (
        structured.get("success") is False or structured.get("error_code")
    ):
        result.is_error = True
    return result


async def run_mcp_tool(
    tool_name: str,
    call: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: McpErrorContext | None = None,
) -> dict[str, Any]:
    """Execute a tool body, returning the result dict or a structured error dict."""
    ctx = context or McpErrorContext(tool_name=tool_name)
    try:
        result = await call()
        if isinstance(result, dict):
            result.setdefault("success", True)
            existing_meta: dict[str, Any] = result.get("_meta") or {}
            result["_meta"] = {
                **existing_meta,
                "tool": tool_name,
                "request_id": _request_id(),
                "unsafe_for_clinical_use": _UNSAFE_FOR_CLINICAL_USE,
            }
        return result
    except Exception as exc:  # broad catch is the error-boundary contract
        envelope = _error_envelope(exc, ctx)
        logger.warning(
            "mcp_tool_error tool=%s code=%s exc=%s",
            tool_name,
            envelope["error_code"],
            exc.__class__.__name__,
        )
        return envelope
