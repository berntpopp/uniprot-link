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
# A ``LIMIT n`` solution modifier. Matched only against a *code-only* view of the
# query (see ``_blank_noncode``) so LIMIT-like text in comments/literals/IRIs is
# never mistaken for a real clause. The lookbehind requires a real token boundary:
# a leading ``?``/``$`` (variable), ``:`` (prefixed name), word char, ``.`` or ``-``
# means it is an identifier like ``?limit``/``ex:limit`` -- a data token, NOT the
# ``LIMIT`` keyword -- so its numeric object is never mistaken for a clause value.
_LIMIT_CLAUSE_RE = re.compile(r"(?<![\w?$:.-])limit\s+(\d+)", re.IGNORECASE)
# An IRIREF ``<...>`` per the SPARQL grammar (no spaces / forbidden chars inside).
# Lets ``_blank_noncode`` skip a whole IRI as one unit -- so a ``#frag`` inside it
# is not read as a comment, and a bare ``<`` (less-than operator) is left as code.
_IRIREF_AT_RE = re.compile(r"<[^<>\"{}|^`\\\x00-\x20]*>")
_STRING_DELIMS = ('"""', "'''", '"', "'")
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


def _blank_noncode(query: str) -> str:
    """Return ``query`` with comments, string literals, and IRIs blanked to spaces.

    The result has the SAME length as the input (offsets are preserved), so a
    match found in it maps 1:1 back onto the original. This is what makes LIMIT
    detection *structural*: a ``LIMIT`` hidden in a ``#`` comment, a string
    literal, or an ``<...#frag>`` IRI becomes invisible, while a bare ``<``
    (the less-than operator) is left intact as code.
    """
    out = list(query)
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch == "#":  # a comment runs to end of line
            j = i
            while j < n and query[j] != "\n":
                out[j] = " "
                j += 1
            i = j
            continue
        if ch == "<":
            m = _IRIREF_AT_RE.match(query, i)
            if m:  # a real IRI -- blank it as one unit (its text is never code)
                for k in range(m.start(), m.end()):
                    out[k] = " "
                i = m.end()
                continue
            i += 1  # a bare ``<`` is the comparison operator; keep it as code
            continue
        delim = next((d for d in _STRING_DELIMS if query.startswith(d, i)), None)
        if delim:
            dl = len(delim)
            for k in range(dl):
                out[i + k] = " "
            j = i + dl
            while j < n:
                if query[j] == "\\" and j + 1 < n:  # escaped char inside the literal
                    out[j] = out[j + 1] = " "
                    j += 2
                    continue
                if query.startswith(delim, j):  # closing delimiter
                    for k in range(dl):
                        out[j + k] = " "
                    j += dl
                    break
                out[j] = " "
                j += 1
            i = j
            continue
        i += 1
    return "".join(out)


def _leading_token(query: str) -> str:
    """Return the query's leading keyword (SELECT/ASK/CONSTRUCT/DESCRIBE/...), upper-cased.

    Detection runs on the IRI/string/comment-blanked view (:func:`_blank_noncode`),
    so a ``#`` inside a same-line ``<...#frag>`` prefix IRI is NEVER read as a
    comment that swallows the query body (the F-08 bypass). Leading ``PREFIX`` and
    ``BASE`` declarations are skipped -- their ``<...>`` IRI is already blanked to
    whitespace in that view, so only the ``PREFIX``/``BASE`` keyword and the
    prefix-name token remain to step over -- leaving the real query form. Returns
    ``""`` when no token remains. Never raises; write-form rejection is
    :func:`classify_sparql_operation`'s job.
    """
    words = _blank_noncode(query).split()
    i, n = 0, len(words)
    while i < n:
        word = words[i].upper()
        if word == "PREFIX":  # ``PREFIX`` + ``<name>:`` token (IRI already blanked)
            i += 2
            continue
        if word == "BASE":  # ``BASE`` (its IRI is already blanked away)
            i += 1
            continue
        return word
    return ""


def inject_limit(query: str, *, default: int, maximum: int) -> tuple[str, bool]:
    """Structurally bound a query's result set; return ``(query, was_injected)``.

    Closes the result-cap bypass (F-08) with two independent, structural clamps
    (comments/string-literals/IRIs are ignored via :func:`_blank_noncode`, so
    LIMIT-like decoy text can no longer fool the guard):

    * Every *real* ``LIMIT n`` clause with ``n > maximum`` is rewritten DOWN to
      ``maximum`` -- a huge explicit LIMIT can no longer request an unbounded row
      count from the endpoint.
    * A top-level ``SELECT`` carrying no real *outer* (brace-depth-0) LIMIT gets
      one appended (``min(default, maximum)``). An unbounded SELECT -- or one whose
      only ``LIMIT`` hides in a comment, a literal, or a sub-query -- never reaches
      the endpoint uncapped.

    ``ASK`` returns a single boolean and ``CONSTRUCT``/``DESCRIBE`` are
    graph-returning forms bounded by the streamed response byte cap (F-17), so
    none of those is LIMIT-injected; any oversized LIMIT they carry is still
    clamped.
    """
    sanitized = _blank_noncode(query)
    clauses: list[tuple[int, int, int, int]] = []
    for m in _LIMIT_CLAUSE_RE.finditer(sanitized):
        pos = m.start()
        depth = sanitized.count("{", 0, pos) - sanitized.count("}", 0, pos)
        clauses.append((m.start(1), m.end(1), int(m.group(1)), depth))

    # Clamp oversized LIMITs right-to-left so earlier offsets stay valid.
    out = query
    for num_start, num_end, value, _depth in sorted(clauses, reverse=True):
        if value > maximum:
            out = out[:num_start] + str(maximum) + out[num_end:]

    has_outer_limit = any(depth == 0 for *_head, depth in clauses)
    if _leading_token(query) == "SELECT" and not has_outer_limit:
        return f"{out.rstrip().rstrip(';')}\nLIMIT {min(default, maximum)}", True
    return out, False


def classify_sparql_operation(query: str) -> str:
    """Return the leading query form; raise InvalidInputError on UPDATE/write forms.

    Detection keys on the first significant keyword after comments and PREFIX/BASE
    declarations (found on the IRI/string/comment-blanked view via
    :func:`_leading_token`, so a ``#`` inside a same-line ``<...#frag>`` IRI is not
    read as a comment), never a substring match anywhere — so a SELECT containing
    the literal "insert" is unaffected. Unknown leading tokens pass through (the
    endpoint will return a 400 -> query_syntax_error).

    This is a UX guard (clean invalid_input vs opaque internal_error), not a
    security boundary — the endpoint is read-only regardless.
    """
    token = _leading_token(query)
    if token in _READ_OPS:
        return token
    if token in _WRITE_OPS:
        raise InvalidInputError(
            "read-only: only SELECT/ASK/CONSTRUCT/DESCRIBE queries are allowed.",
            field="query",
        )
    return token  # unknown -> let the endpoint return a 400 (query_syntax_error)
