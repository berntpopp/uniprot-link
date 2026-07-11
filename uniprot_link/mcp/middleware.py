"""FastMCP middleware that wraps argument-binding failures in the error envelope.

FastMCP validates call arguments with pydantic inside ``FunctionTool.run()`` --
before the registered tool body executes -- so a wrong argument *name*/*type* or a
*missing required* argument raises a ``pydantic.ValidationError`` that never reaches
``run_mcp_tool``'s error boundary. This middleware catches that error at the
``on_call_tool`` hook and returns a normal ``ToolResult`` carrying the standard
``invalid_input`` envelope (with valid names + a did-you-mean), so every failure
mode speaks the product's own contract.

It also normalizes a curated set of argument aliases (e.g. ``taxon`` ->
``organism_taxon``) before dispatch, eliminating the most common cold-start round
trips, and discloses any rewrite under ``_meta.argument_aliases_applied``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolRequestParams, TextContent
from pydantic import ValidationError as PydanticValidationError

from uniprot_link.mcp.arg_help import (
    did_you_mean,
    enum_values_for,
    normalize_alias_args,
    tool_signature,
)
from uniprot_link.mcp.envelope import build_arg_error_envelope

_MISSING_TYPES = {"missing", "missing_argument"}

logger = logging.getLogger(__name__)


class ArgValidationMiddleware(Middleware):
    """Reshape argument-binding errors into the envelope and apply argument aliases."""

    def __init__(self) -> None:
        """Initialise the per-tool parameter-schema cache."""
        self._schema_cache: dict[str, dict[str, Any]] = {}

    async def _schema(self, context: MiddlewareContext[Any], name: str) -> dict[str, Any]:
        if name not in self._schema_cache:
            fctx = context.fastmcp_context
            if fctx is None:
                raise RuntimeError("no fastmcp context")
            tool = await fctx.fastmcp.get_tool(name)
            self._schema_cache[name] = dict(getattr(tool, "parameters", None) or {})
        return self._schema_cache[name]

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Normalize aliases, then convert binding errors into the envelope."""
        name = context.message.name
        try:
            schema = await self._schema(context, name)
        except Exception:  # registry miss: let core handle the call untouched
            return await call_next(context)

        valid = list(schema.get("properties", {}).keys())
        new_args, applied = normalize_alias_args(valid, context.message.arguments or {})
        context.message.arguments = new_args

        try:
            result = await call_next(context)
        except FastMCPValidationError as exc:
            cause = exc.__cause__
            if not isinstance(cause, PydanticValidationError):
                raise
            return self._error_result(name, valid, schema, cause)
        except PydanticValidationError as exc:
            return self._error_result(name, valid, schema, exc)

        if (
            applied
            and isinstance(result, ToolResult)
            and isinstance(result.structured_content, dict)
        ):
            meta = result.structured_content.setdefault("_meta", {})
            meta["argument_aliases_applied"] = [list(pair) for pair in applied]
        return result

    def _error_result(
        self,
        name: str,
        valid: list[str],
        schema: dict[str, Any],
        exc: PydanticValidationError,
    ) -> ToolResult:
        first = exc.errors(include_url=False)[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "input"
        error_type = str(first.get("type", "value_error"))
        # Classify into missing / unknown-name / bad-value so each gets the right
        # allowed_values semantics (F1). A *value* error on a known param surfaces
        # the field's valid VALUES (enum) -- never the argument names.
        suggestion: str | None = None
        enum_values: list[Any] | None = None
        value_message: str | None = None
        if error_type in _MISSING_TYPES:
            pass  # missing required: argument-names wording
        elif loc not in valid:
            suggestion = did_you_mean(loc, valid)  # unknown name: did-you-mean
        else:
            enum_values = enum_values_for(schema, loc)  # bad value on a known param
            if enum_values is None:
                value_message = str(first.get("msg", "")) or None
        envelope = build_arg_error_envelope(
            tool_name=name,
            loc=loc,
            error_type=error_type,
            valid_params=valid,
            signature=tool_signature(name, schema),
            suggestion=suggestion,
            enum_values=enum_values,
            value_message=value_message,
        )
        logger.warning("mcp_arg_error tool=%s loc=%s type=%s", name, loc, error_type)
        return ToolResult(
            structured_content=envelope,
            content=[TextContent(type="text", text=json.dumps(envelope))],
        )
