"""Async organism-name coercion for protein discovery services."""

from __future__ import annotations

from typing import Any, Protocol, cast

from uniprot_link.exceptions import InvalidInputError, NotFoundError
from uniprot_link.services.constants import lookup_common_taxon

_RECOVERY_HINT = (
    "Call get_taxon(taxon=...) to inspect taxonomy matches, then retry with its taxon_id."
)


class _TaxonomyLookup(Protocol):
    """The existing taxonomy-service surface used for long-tail names."""

    async def get_taxon(
        self,
        taxon: str,
        include_lineage: bool = False,
        *,
        allow_curated: bool = True,
    ) -> dict[str, Any]: ...

    async def get_taxon_exact(self, name: str) -> dict[str, Any]: ...


class TaxonResolutionMixin:
    """Resolve numeric or named organism inputs to one positive NCBI taxon id."""

    async def resolve_organism_taxon(self, value: int | str | None) -> int | None:
        """Return one taxon id, requiring exact name equality for endpoint matches."""
        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            if value >= 1:
                return value
            raise InvalidInputError(
                "organism_taxon must be a positive NCBI taxon id.",
                field="organism_taxon",
                hint=_RECOVERY_HINT,
            )

        name = str(value).strip()
        if name.isdigit():
            try:
                numeric_taxon_id = int(name)
            except ValueError as exc:
                raise InvalidInputError(
                    "organism_taxon must be a positive NCBI taxon id.",
                    field="organism_taxon",
                    hint=_RECOVERY_HINT,
                ) from exc
            if numeric_taxon_id >= 1:
                return numeric_taxon_id
            raise InvalidInputError(
                "organism_taxon must be a positive NCBI taxon id.",
                field="organism_taxon",
                hint=_RECOVERY_HINT,
            )
        if not name:
            raise InvalidInputError(
                "organism_taxon must not be blank.",
                field="organism_taxon",
                hint=_RECOVERY_HINT,
            )

        curated = lookup_common_taxon(name)
        if curated is not None:
            exact_curated_names = {
                str(curated.get("scientific_name") or "").strip().casefold(),
                str(curated.get("common_name") or "").strip().casefold(),
            }
            if name.casefold() in exact_curated_names:
                return int(curated["taxon_id"])

        taxonomy = cast(_TaxonomyLookup, self)
        try:
            result = await taxonomy.get_taxon_exact(name)
        except NotFoundError as exc:
            raise InvalidInputError(
                "The organism name has no exact taxonomy match. Call get_taxon to inspect "
                "available matches, then retry with a taxon_id.",
                field="organism_taxon",
                hint=_RECOVERY_HINT,
            ) from exc

        query = name.casefold()
        exact_by_id: dict[str, dict[str, Any]] = {}
        for match in result.get("matches", []):
            scientific = str(match.get("scientific_name") or "").strip().casefold()
            common = str(match.get("common_name") or "").strip().casefold()
            match_taxon_id = str(match.get("taxon_id") or "").strip()
            if (
                query in {scientific, common}
                and match_taxon_id.isdigit()
                and int(match_taxon_id) >= 1
            ):
                exact_by_id[match_taxon_id] = match

        if len(exact_by_id) != 1:
            qualifier = "ambiguous" if len(exact_by_id) > 1 else "not exact"
            raise InvalidInputError(
                f"The organism name is {qualifier}. Call get_taxon to inspect taxonomy "
                "matches, then retry with a taxon_id.",
                field="organism_taxon",
                hint=_RECOVERY_HINT,
            )
        return int(next(iter(exact_by_id)))
