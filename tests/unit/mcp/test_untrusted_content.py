"""Structural untrusted-text fencing contracts."""

from __future__ import annotations

import hashlib

import pytest

from uniprot_link.mcp.untrusted_content import (
    UntrustedTextLimitError,
    enforce_untrusted_text_limits,
    fence_untrusted_text,
)


def test_fence_normalizes_and_removes_forbidden_controls() -> None:
    raw = "Café\x00​‮\nBRCA1"
    fenced = fence_untrusted_text(raw, source="uniprot", record_id="P38398")

    assert fenced.kind == "untrusted_text"
    assert fenced.text == "Café\nBRCA1"
    assert fenced.raw_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert fenced.provenance.source == "uniprot"
    assert fenced.provenance.record_id == "P38398"


def test_fence_preserves_tabs_newlines_and_scientific_symbols() -> None:
    raw = "p.Gly12Asp\t\u0394G = \u22121.2 kcal/mol\r\n"
    assert fence_untrusted_text(raw, source="uniprot", record_id="P38398").text == raw


def test_limits_reject_oversized_object() -> None:
    big = fence_untrusted_text("x" * 10, source="uniprot", record_id="P38398")
    with pytest.raises(UntrustedTextLimitError):
        enforce_untrusted_text_limits([big], max_text_bytes=5)
