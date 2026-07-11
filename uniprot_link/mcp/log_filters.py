"""Logging filters that keep untrusted code points out of the app log.

FastMCP logs argument-validation failures itself, before this project's middleware
catches them: ``fastmcp.server.server`` emits ``"Invalid arguments for tool %r: %s"``
with the raw pydantic error (which embeds the caller's argument names/values). A
hostile caller can therefore write control/zero-width/bidi/NUL code points into the
process log verbatim. This filter rewrites each record's fully-formatted message with
the fence's forbidden code points removed, so nothing hostile is ever recorded.

Defense-in-depth secondary surface: the log is not model-visible, but a poisoned log
line can corrupt terminals, log viewers, or downstream SIEM pipelines.
"""

from __future__ import annotations

import logging

from uniprot_link.mcp.untrusted_content import FORBIDDEN_CODEPOINTS

# Loggers that format third-party / caller-influenced text we do not control.
_SANITIZED_LOGGERS = ("fastmcp.server.server",)


def _strip_forbidden(text: str) -> str:
    return "".join(char for char in text if ord(char) not in FORBIDDEN_CODEPOINTS)


class ForbiddenCodepointLogFilter(logging.Filter):
    """Rewrite a record's formatted message with the fence's forbidden code points removed."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Strip forbidden code points from the record, then always allow it through."""
        try:
            message = record.getMessage()
        except Exception:  # never let log sanitation break the emitting call
            message = str(record.msg)
        record.msg = _strip_forbidden(message)
        record.args = ()
        return True


def install_log_sanitizer(logger_names: tuple[str, ...] = _SANITIZED_LOGGERS) -> None:
    """Attach the forbidden-code-point filter to the named loggers (idempotent)."""
    for name in logger_names:
        target = logging.getLogger(name)
        if not any(isinstance(f, ForbiddenCodepointLogFilter) for f in target.filters):
            target.addFilter(ForbiddenCodepointLogFilter())
