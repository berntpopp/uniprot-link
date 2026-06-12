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

logger = logging.getLogger(__name__)

# Per-call _meta is kept lean: static provenance (research-use restriction,
# citation DOI, UniProt release) lives ONLY in get_server_capabilities. Repeating
# it on every response is non-actionable token overhead (MCP/Anthropic context
# economy). Per-call _meta carries only dynamic fields: tool, request_id,
# next_commands.
_RETRYABLE = {"rate_limited", "upstream_unavailable", "query_timeout"}


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
    return (str(exc) or exc.__class__.__name__)[:280]


def _classify(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_code, client_safe_message)`` for an exception."""
    if isinstance(exc, McpToolError):
        return exc.error_code, exc.message
    if isinstance(exc, NotFoundError):
        return "not_found", _safe_message(exc)
    if isinstance(exc, InvalidInputError):
        return "invalid_input", _safe_message(exc)
    if isinstance(exc, QuerySyntaxError):
        return "query_syntax_error", _safe_message(exc)
    if isinstance(exc, QueryTimeoutError):
        return "query_timeout", "The query timed out. Add filters/LIMIT or anchor on an accession."
    if isinstance(exc, RateLimitError):
        return "rate_limited", "UniProt SPARQL rate limit hit. Retry shortly."
    if isinstance(exc, ServiceUnavailableError):
        return "upstream_unavailable", "The UniProt SPARQL endpoint is temporarily unavailable."
    if isinstance(exc, PydanticValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "input"
        return "invalid_input", f"Invalid input -- `{loc}`: {first['msg']}"
    return "internal_error", "An internal error occurred. The request was not completed."


def _recovery_action(error_code: str) -> str:
    if error_code in _RETRYABLE:
        return "retry_backoff"
    if error_code in {"invalid_input", "not_found", "query_syntax_error"}:
        return "reformulate_input"
    return "switch_tool"


def _error_envelope(exc: BaseException, context: McpErrorContext) -> dict[str, Any]:
    error_code, message = _classify(exc)
    envelope: dict[str, Any] = {
        "success": False,
        "error_code": error_code,
        "message": message,
        "retryable": error_code in _RETRYABLE,
        "recovery_action": _recovery_action(error_code),
        "_meta": {"tool": context.tool_name, "request_id": _request_id()},
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


def build_arg_error_envelope(
    *,
    tool_name: str,
    loc: str,
    error_type: str,
    valid_params: list[str],
    signature: str,
    suggestion: str | None,
) -> dict[str, Any]:
    """Standard invalid-input envelope for an argument-binding failure.

    Used by :class:`~uniprot_link.mcp.middleware.ArgValidationMiddleware` so a wrong
    argument *name*, *type*, or a *missing required* argument routes through the same
    contract as value-level errors instead of leaking a raw pydantic ``ValidationError``.
    """
    if error_type == "missing_argument":
        head = f"Missing required argument `{loc}` for {tool_name}."
    elif error_type == "unexpected_keyword_argument":
        head = f"Unknown argument `{loc}` for {tool_name}."
    else:
        head = f"Invalid value for argument `{loc}` of {tool_name}."
    dym = f" Did you mean `{suggestion}`?" if suggestion else ""
    message = f"{head}{dym} Valid argument names are listed in allowed_values."
    return {
        "success": False,
        "error_code": "invalid_input",
        "message": message[:280],
        "retryable": False,
        "recovery_action": "reformulate_input",
        "field": loc,
        "allowed_values": valid_params,
        "hint": signature,
        "_meta": {
            "tool": tool_name,
            "request_id": _request_id(),
            "next_commands": [cmd("get_server_capabilities")],
        },
    }


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
