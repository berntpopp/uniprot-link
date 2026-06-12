"""Unit tests for the exception taxonomy's structured fields."""

from __future__ import annotations

from uniprot_link.exceptions import InvalidInputError


def test_invalid_input_carries_structured_fields() -> None:
    exc = InvalidInputError("bad", field="feature_types", allowed=["a", "b"], hint="see caps")
    assert exc.field == "feature_types"
    assert exc.allowed == ["a", "b"]
    assert exc.hint == "see caps"


def test_invalid_input_defaults_are_none() -> None:
    exc = InvalidInputError("bad")
    assert exc.field is None
    assert exc.allowed is None
    assert exc.hint is None
