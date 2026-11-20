"""Gene symbol or HGNC / NCBI Gene id in an accession slot -> reviewed human accession.

Router #319 / #343, Envelope 2b.

Accession-shaped input takes the unchanged path. A strictly symbol-shaped value is
resolved through the existing find_proteins search (exact prefLabel/altLabel
match, reviewed Swiss-Prot, taxon 9606); exactly one entry -> the tool runs on it
and echoes ``resolved_from``; zero or several -> GeneSymbolResolutionError.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, Concatenate

from uniprot_link.exceptions import GeneSymbolResolutionError
from uniprot_link.mcp.next_commands import looks_like_gene_symbol
from uniprot_link.services.queries.validation import (
    GENE_XREF_DATABASES,
    foreign_gene_form,
    unsupported_gene_identifier,
)
from uniprot_link.services.service_find import FindProteinsServiceMixin

_HUMAN_TAXON = 9606
_MAX_CANDIDATES = 10

type _Method[S, **P] = Callable[Concatenate[S, str, P], Awaitable[dict[str, Any]]]


def accepts_gene_symbol[S: FindProteinsServiceMixin, **P](method: _Method[S, P]) -> _Method[S, P]:
    """Let an accession-taking service method also take a human gene symbol."""

    @functools.wraps(method)
    async def wrapper(self: S, accession: str, /, *args: P.args, **kwargs: P.kwargs) -> Any:
        form = (foreign_gene_form(accession) or ("symbol",))[0]
        if form not in ("symbol", *GENE_XREF_DATABASES):
            # A gene id this backend cannot anchor on (router #343): name the converter.
            raise unsupported_gene_identifier(accession, "accession")
        if form == "symbol" and not looks_like_gene_symbol(accession):
            return await method(self, accession, *args, **kwargs)
        symbol = accession.strip()
        found = await self.find_proteins(
            gene=symbol, organism_taxon=_HUMAN_TAXON, reviewed=True, limit=_MAX_CANDIDATES
        )
        hits = {p["accession"]: p for p in found["proteins"] if p.get("accession")}
        if len(hits) != 1:
            raise GeneSymbolResolutionError(
                symbol,
                [
                    {"accession": a, "mnemonic": p.get("mnemonic"), "name": p.get("name")}
                    for a, p in hits.items()
                ],
            )
        (resolved,) = hits
        payload = await method(self, resolved, *args, **kwargs)
        payload["resolved_from"] = {"input": symbol, "form": form, "resolved_to": resolved}
        return payload

    return wrapper
