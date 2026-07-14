"""Guards for hand-typed facts in the maintained docs.

GeneFoundry README Standard v1: a documented fact that no machine checks will rot.
``scripts/check_readme.py`` validates structure and Markdown ``[](...)`` links;
these two guards cover the facts it cannot see:

1. **Backticked repo-relative paths must exist.** The README's Contributing section
   once told contributors to re-validate ``uniprot_link/services/queries.py`` -- a
   file that has never existed (``queries`` is a package directory). A backticked
   path is invisible to the link checker, so it rotted silently.
2. **docs/configuration.md must document every settable env var.** The README routes
   operators there promising "every ``UNIPROT_LINK_*`` variable"; that claim is only
   true if a new setting cannot ship without a row.

Scope is the *maintained* docs. The archived ``docs/mcp-assessment-*`` snapshots
record the code as it stood at a past revision and are deliberately not enforced.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from uniprot_link.config import ServerSettings

REPO = Path(__file__).resolve().parents[2]

#: The README plus the pages its Documentation routing table points at.
LIVE_DOCS = (
    "README.md",
    "AGENTS.md",
    "docs/usage.md",
    "docs/configuration.md",
    "docs/deployment.md",
    "docs/architecture.md",
    "docs/development.md",
)

#: Any `backticked` span.
_BACKTICKED = re.compile(r"`([^`\n]+)`")

#: A trailing `:123` line number or `::symbol` reference is prose notation, not path.
_LOCATOR_SUFFIX = re.compile(r"(::.*|:\d+)$")


def _candidate_paths(text: str) -> set[str]:
    """Backticked spans that are unambiguously repo-relative paths.

    A span qualifies only if it contains a ``/``, has no spaces, is not a URL or
    URI, and its first segment names a real entry at the repo root -- so tool names,
    env vars, ``uniprot://citation`` and prose survive untouched.
    """
    top_level = {entry.name for entry in REPO.iterdir()}
    found: set[str] = set()
    for span in _BACKTICKED.findall(text):
        token = _LOCATOR_SUFFIX.sub("", span)
        if "/" not in token or " " in token or "://" in token or "*" in token:
            continue
        if token.startswith(("http", "/")):
            continue
        if token.split("/", 1)[0] in top_level:
            found.add(token)
    return found


def test_backticked_repo_paths_in_live_docs_exist() -> None:
    """Every backticked repo-relative path in a maintained doc must resolve."""
    checked = 0
    broken: list[str] = []
    for doc in LIVE_DOCS:
        path = REPO / doc
        assert path.exists(), f"LIVE_DOCS names a doc that does not exist: {doc}"
        for token in sorted(_candidate_paths(path.read_text(encoding="utf-8"))):
            checked += 1
            if not (REPO / token).exists():
                broken.append(f"{doc}: `{token}`")

    assert checked, "path guard matched nothing -- the extraction rule is broken"
    assert not broken, "docs cite repo paths that do not exist: " + "; ".join(broken)


def _env_var_names(model: type[BaseModel], prefix: str = "UNIPROT_LINK_") -> set[str]:
    """Every environment variable name the settings model actually reads."""
    names: set[str] = set()
    for field, info in model.model_fields.items():
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names |= _env_var_names(annotation, f"{prefix}{field.upper()}__")
        else:
            names.add(f"{prefix}{field.upper()}")
    return names


def test_configuration_md_documents_every_env_var() -> None:
    """docs/configuration.md must document every settable UNIPROT_LINK_* variable.

    The README promises exhaustiveness. A setting added to ``config.py`` without a
    row here turns that promise into a lie -- which is what this test exists to stop.
    """
    documented = (REPO / "docs" / "configuration.md").read_text(encoding="utf-8")
    live = _env_var_names(ServerSettings)
    assert live, "settings model exposes no env vars -- the walker is broken"

    missing = sorted(name for name in live if name not in documented)
    assert not missing, f"settable but undocumented in docs/configuration.md: {missing}"
