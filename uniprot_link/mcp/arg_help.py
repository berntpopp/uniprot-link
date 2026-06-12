"""Argument ergonomics for MCP tools: aliases, did-you-mean, signatures.

Pure functions with no FastMCP dependency so they unit-test in isolation. The
:mod:`uniprot_link.mcp.middleware` module and the discovery surface both consume
them, keeping a single source of truth for what a "valid argument" looks like.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from typing import Any

# Curated synonym -> canonical map, scoped to this server's small parameter space.
# An alias only ever resolves to a canonical name that is a *real* parameter of the
# tool being called (see ``normalize_alias_args``), so a shared map is safe.
ARG_ALIASES: dict[str, str] = {
    # organism_taxon: the assessment's headline miss (taxon / organism / organism_id)
    "taxon": "organism_taxon",
    "taxon_id": "organism_taxon",
    "taxid": "organism_taxon",
    "tax_id": "organism_taxon",
    "organism": "organism_taxon",
    "organism_id": "organism_taxon",
    "ncbi_taxon": "organism_taxon",
    "species": "organism_taxon",
    # gene
    "gene_symbol": "gene",
    "gene_name": "gene",
    "symbol": "gene",
    # accession
    "acc": "accession",
    "uniprot": "accession",
    "uniprot_id": "accession",
    "uniprot_accession": "accession",
    "id": "accession",
    # ec / keyword / query text
    "ec": "ec_number",
    "ec_no": "ec_number",
    "kw": "keyword",
    "query_string": "query",
    "sparql": "query",
}


def normalize_alias_args(
    valid_params: Iterable[str], arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Rewrite known alias keys to their canonical parameter names.

    An alias is applied only when (a) the alias key is present, (b) the canonical
    target is a real parameter of the called tool, and (c) the canonical key is not
    already supplied explicitly. Returns ``(new_arguments, applied_pairs)`` where
    ``applied_pairs`` is a list of ``(alias, canonical)`` for transparency.
    """
    valid = set(valid_params)
    result = dict(arguments)
    applied: list[tuple[str, str]] = []
    for alias, canonical in ARG_ALIASES.items():
        if alias in result and canonical in valid:
            if canonical in result:
                # Explicit canonical value wins; drop the redundant alias quietly.
                result.pop(alias)
            else:
                result[canonical] = result.pop(alias)
                applied.append((alias, canonical))
    return result, applied


def did_you_mean(unknown: str, valid: Iterable[str]) -> str | None:
    """Best canonical suggestion for an unknown argument name, or ``None``.

    The alias map is authoritative; otherwise fall back to close string matches.
    """
    valid_list = list(valid)
    aliased = ARG_ALIASES.get(unknown)
    if aliased is not None and aliased in valid_list:
        return aliased
    matches = difflib.get_close_matches(unknown, valid_list, n=1, cutoff=0.6)
    return matches[0] if matches else None


def enum_values_for(schema: Mapping[str, Any], param: str) -> list[Any] | None:
    """Return a parameter's enum value set from a JSON input schema, else ``None``.

    Handles a direct ``enum`` and an ``anyOf``/``oneOf`` branch carrying one (the
    ``Literal[...] | None`` shape FastMCP emits for an optional enum). This is the
    single source of truth for "what values does this arg accept" -- consumed by
    both the error path (F1: list valid *values*, not argument *names*) and the
    capabilities discovery surface.
    """
    prop = (schema.get("properties") or {}).get(param)
    if not isinstance(prop, dict):
        return None
    if isinstance(prop.get("enum"), list):
        return list(prop["enum"])
    for branch in prop.get("anyOf") or prop.get("oneOf") or []:
        if isinstance(branch, dict) and isinstance(branch.get("enum"), list):
            return list(branch["enum"])
    return None


def tool_signature(name: str, schema: Mapping[str, Any]) -> str:
    """Render ``name(req, opt=, ...)`` from a JSON input schema.

    Required parameters are listed first (bare); optional parameters follow with a
    trailing ``=`` to signal they take a value but may be omitted.
    """
    props = list(schema.get("properties", {}).keys())
    required = set(schema.get("required") or [])
    parts = [p for p in props if p in required]
    parts += [f"{p}=" for p in props if p not in required]
    return f"{name}(" + ", ".join(parts) + ")"
