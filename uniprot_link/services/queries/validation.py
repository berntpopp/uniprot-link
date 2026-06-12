"""Input validation, escaping, and LIMIT/operation helpers for query builders.

User input is validated and escaped before interpolation: accessions/taxa are
pattern-checked, and free-text values are escaped for safe inclusion in SPARQL
string literals.
"""

from __future__ import annotations

import re

from uniprot_link.exceptions import InvalidInputError

_ACCESSION_RE = re.compile(r"^[A-Z0-9]{6,10}(-\d+)?$", re.IGNORECASE)
_TAXON_RE = re.compile(r"^\d+$")
_SELECT_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_COMMENT_RE = re.compile(r"#[^\n]*")
_PREFIX_RE = re.compile(r"^\s*(?:PREFIX\s+[^:]*:\s*<[^>]*>|BASE\s*<[^>]*>)\s*", re.IGNORECASE)
_READ_OPS = {"SELECT", "ASK", "CONSTRUCT", "DESCRIBE"}
_WRITE_OPS = {"INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP", "ADD", "MOVE", "COPY", "WITH"}


def escape_literal(value: str) -> str:
    """Escape a string for safe use inside a SPARQL double-quoted literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def validate_accession(accession: str) -> str:
    """Validate and normalise a UniProtKB accession (uppercased)."""
    acc = accession.strip().upper()
    if not _ACCESSION_RE.match(acc):
        raise InvalidInputError(
            f"'{accession}' is not a valid UniProtKB accession "
            "(e.g. P05067, P38398, or an isoform like P05067-2).",
            field="accession",
        )
    return acc


def validate_taxon(taxon_id: str | int) -> str:
    """Validate an NCBI taxon id (digits only)."""
    tid = str(taxon_id).strip()
    if not _TAXON_RE.match(tid):
        raise InvalidInputError(
            f"'{taxon_id}' is not a valid NCBI taxon id (digits only, e.g. 9606).",
            field="taxon_id",
        )
    return tid


def clamp_limit(limit: int, *, default: int, maximum: int) -> int:
    """Clamp a requested LIMIT to ``[1, maximum]`` (falling back to ``default``)."""
    if limit is None or limit <= 0:
        limit = default
    return min(limit, maximum)


def inject_limit(query: str, *, default: int, maximum: int) -> tuple[str, bool]:
    """Ensure a SELECT query carries a LIMIT; return ``(query, was_injected)``.

    Existing LIMITs are left untouched (the endpoint still enforces them). Only
    SELECT queries without a LIMIT get one appended. ASK/CONSTRUCT/DESCRIBE are
    returned unchanged.
    """
    lowered = query.lower()
    if "select" not in lowered:
        return query, False
    if _SELECT_LIMIT_RE.search(query):
        return query, False
    return f"{query.rstrip().rstrip(';')}\nLIMIT {min(default, maximum)}", True


def classify_sparql_operation(query: str) -> str:
    """Return the leading query form; raise InvalidInputError on UPDATE/write forms.

    Detection keys on the first significant keyword after comments and PREFIX/BASE
    declarations, never a substring match anywhere — so a SELECT containing the
    literal "insert" is unaffected. Unknown leading tokens pass through (the
    endpoint will return a 400 -> query_syntax_error).

    This is a UX guard (clean invalid_input vs opaque internal_error), not a
    security boundary — the endpoint is read-only regardless. Limitation: a ``#``
    inside a same-line IRI fragment is treated as a comment, so a write whose verb
    shares a physical line with a ``<...#frag>`` IRI may classify as unknown and be
    rejected by the endpoint instead; the conventional one-declaration-per-line
    form is always caught here.
    """
    stripped = _COMMENT_RE.sub("", query)
    while True:
        new = _PREFIX_RE.sub("", stripped, count=1)
        if new == stripped:
            break
        stripped = new
    token = (stripped.strip().split(None, 1) or [""])[0].upper()
    if token in _READ_OPS:
        return token
    if token in _WRITE_OPS:
        raise InvalidInputError(
            "read-only: only SELECT/ASK/CONSTRUCT/DESCRIBE queries are allowed.",
            field="query",
        )
    return token  # unknown -> let the endpoint return a 400 (query_syntax_error)
