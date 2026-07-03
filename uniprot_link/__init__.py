"""uniprot-link: an MCP/API server grounding protein research in UniProt SPARQL."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("uniprot-link")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
