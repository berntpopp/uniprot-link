"""Input validation, escaping, and LIMIT/operation helpers for query builders.

User input is validated and escaped before interpolation: accessions/taxa are
pattern-checked, and free-text values are escaped for safe inclusion in SPARQL
string literals.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from uniprot_link.exceptions import InvalidInputError

# Official UniProtKB accession grammar (uniprot.org/help/accession_numbers),
# plus an optional ``-N`` isoform suffix. Rejects digit blobs like "999999".
_ACCESSION_RE = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})(-\d+)?$",
    re.IGNORECASE,
)
_TAXON_RE = re.compile(r"^\d+$")
# The accession interior signature: a letter, a digit, then 4+ alnum chars (e.g.
# ``Q96T60XYZ``). Catches a *mangled* accession the strict grammar above rejects.
_ACCESSION_LIKE_RE = re.compile(r"^[A-Za-z][0-9][A-Za-z0-9]{4,}(-\d+)?$")
_SELECT_LIMIT_RE = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_COMMENT_RE = re.compile(r"#[^\n]*")
_PREFIX_RE = re.compile(r"^\s*(?:PREFIX\s+[^:]*:\s*<[^>]*>|BASE\s*<[^>]*>)\s*", re.IGNORECASE)
_READ_OPS = {"SELECT", "ASK", "CONSTRUCT", "DESCRIBE"}
_WRITE_OPS = {"INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP", "ADD", "MOVE", "COPY", "WITH"}
# A UniProt cross-reference database key (e.g. PDB, HGNC, AlphaFoldDB): starts
# alnum, then alnum/._- up to 64 chars total. Anything else -- notably an IRIREF
# terminator (``>``, ``{``, whitespace) or a path/scheme separator (``/``, ``:``,
# ``@``, ``%``) -- is rejected before the value reaches an ``<...>`` IRI.
_DATABASE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
# Characters that must never appear inside an IRIREF ``<...>``: SPARQL forbids the
# ASCII controls/space plus ``<>"{}|^`\`` in that production, so any of them lets
# a spliced value break out of the IRI and inject graph patterns.
_IRI_FORBIDDEN_RE = re.compile(r'[\x00-\x20<>"{}|^`\\]')


def escape_literal(value: str) -> str:
    """Escape a string for safe use inside a SPARQL double-quoted literal.

    NOTE: literal-only. This does NOT make a value safe to splice into an
    ``<...>`` IRIREF -- use :func:`validate_database_name` /
    :func:`validate_example_iri` for IRI contexts (M1).
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def validate_database_name(name: str) -> str:
    """Validate a cross-reference database name for safe splicing into an IRI.

    The xref filter splices the name into
    ``<http://purl.uniprot.org/database/{name}>``. ``escape_literal`` only guards
    *string-literal* contexts, so a name carrying IRIREF terminators could break
    out and inject graph patterns (finding M1). Restrict to the shape real
    UniProt database keys take (``PDB``, ``HGNC``, ``AlphaFoldDB`` ...).
    """
    db = name.strip()
    if not _DATABASE_NAME_RE.match(db):
        raise InvalidInputError(
            f"'{name}' is not a valid cross-reference database name "
            "(letters/digits then '.', '_' or '-'; e.g. PDB, HGNC, Ensembl).",
            field="databases",
        )
    return db


def validate_example_iri(value: str) -> str:
    """Validate a curated-example IRI for safe splicing into an ``<...>`` IRIREF.

    ``get_example_query`` splices ``example_id`` directly into ``<{iri}>``. A
    scheme-prefix check alone is insufficient (finding M1): require an http(s)
    scheme and non-empty host, and reject any character SPARQL forbids inside an
    IRIREF so a value cannot terminate the ``<...>`` and inject graph patterns.
    """
    iri = value.strip()
    try:
        parts = urlsplit(iri)
    except ValueError:
        # urlsplit itself raises ValueError on malformed input (e.g. an invalid
        # IPv6 literal like ``http://[``); surface it as the intended
        # InvalidInputError rather than letting it escape as an unhandled error.
        parts = None
    if (
        parts is None
        or parts.scheme not in ("http", "https")
        or not parts.netloc
        or _IRI_FORBIDDEN_RE.search(iri)
    ):
        raise InvalidInputError(
            "example_id must be a full http(s) IRI as returned by "
            "search_example_queries (no spaces or SPARQL metacharacters).",
            field="example_id",
        )
    return iri


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


def is_valid_accession(value: str) -> bool:
    """True only if ``value`` is a strictly-valid UniProtKB accession.

    Unlike :func:`looks_like_accession` (which also accepts near-miss shapes for
    error recovery), this enforces the official accession grammar EXACTLY via
    ``fullmatch`` (so a trailing newline or any control/zero-width/bidi character
    fails). Used to keep unvalidated upstream ``up:replacedBy`` values from being
    surfaced as data or spliced into a recovery ``next_commands`` argument -- such
    values are OMITTED, never sanitized into an executable argument.
    """
    return bool(_ACCESSION_RE.fullmatch(value))


def looks_like_accession(value: str) -> bool:
    """True if ``value`` is a real OR near-miss UniProtKB accession (not a gene).

    Used by error recovery to keep a mangled accession (e.g. ``Q96T60XYZ``) from
    being replayed as ``find_proteins(gene=...)``, while still letting a genuine
    gene symbol typed into the accession slot (``BRCA1``) redirect to a search.
    """
    v = value.strip()
    return bool(_ACCESSION_RE.match(v.upper()) or _ACCESSION_LIKE_RE.match(v))


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
