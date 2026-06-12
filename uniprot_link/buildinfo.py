"""Build/version stamp so a running server can report its own provenance."""

from __future__ import annotations

import os

from uniprot_link import __version__


def build_info() -> dict[str, str | None]:
    """Return version + git sha + build time (env-injected at image build)."""
    return {
        "version": __version__,
        "git_sha": os.environ.get("UNIPROT_LINK_GIT_SHA", "unknown"),
        "built_at": os.environ.get("UNIPROT_LINK_BUILT_AT"),
    }
