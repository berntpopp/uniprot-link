"""The forbidden-code-point log filter keeps hostile code points out of the app log.

FastMCP's ``fastmcp.server.server`` logger formats the raw pydantic arg-validation
error (caller-controlled). The installed filter must strip control/zero-width/bidi/NUL
code points from whatever that logger records, and it must not drop the log line.
"""

from __future__ import annotations

import logging

from uniprot_link.mcp.log_filters import ForbiddenCodepointLogFilter, install_log_sanitizer

_FORBIDDEN = ("\x00", "‍", "﻿", "‮")


def test_filter_strips_actual_codepoints_from_a_plain_message() -> None:
    filt = ForbiddenCodepointLogFilter()
    record = logging.LogRecord(
        name="fastmcp.server.server",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        # a %s of a plain string preserves ACTUAL code points (unlike a repr'd list)
        msg="Invalid arguments for tool %r: %s",
        args=("get_protein", "delete_everything‍﻿‮\x00"),
        exc_info=None,
    )
    assert filt.filter(record) is True  # never drops the record
    out = record.getMessage()
    for forbidden in _FORBIDDEN:
        assert forbidden not in out
    assert "delete_everything" in out  # prose kept; only code points removed


def test_install_log_sanitizer_is_idempotent() -> None:
    install_log_sanitizer()
    install_log_sanitizer()
    logger = logging.getLogger("fastmcp.server.server")
    installed = [f for f in logger.filters if isinstance(f, ForbiddenCodepointLogFilter)]
    assert len(installed) == 1  # exactly one, no matter how often install runs


def test_installed_filter_sanitizes_records_end_to_end() -> None:
    install_log_sanitizer()
    logger = logging.getLogger("fastmcp.server.server")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    prev_level, prev_propagate = logger.level, logger.propagate
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        logger.warning("Invalid arguments for tool %r: %s", "t", "x‍﻿‮\x00y")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        logger.propagate = prev_propagate
    assert records, "no record captured"
    msg = records[0].getMessage()
    for forbidden in _FORBIDDEN:
        assert forbidden not in msg
    assert "xy" in msg
