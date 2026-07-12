"""F-19: the Docker build must bootstrap uv reproducibly (no floating installer).

A `pip install --upgrade pip uv` pulls whatever versions PyPI serves at build
time, so two builds of the same source can differ. Pin uv to the exact
digest-addressed image the router itself uses (fleet-shared anchor) and drop the
floating upgrade.

Research use only; not clinical decision support."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # tests/unit/ -> repo root
_UV_COPY_PIN = (
    "ghcr.io/astral-sh/uv:0.8.7@sha256:"
    "1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab"
)


def test_dockerfile_pins_uv_and_has_no_floating_pip_upgrade() -> None:
    text = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install --upgrade" not in text, "floating pip/uv upgrade must be removed (F-19)"
    assert _UV_COPY_PIN in text, "uv must be COPY-pinned to the digest-addressed image (F-19)"
