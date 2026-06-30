"""Tool-name compliance with the GeneFoundry Tool-Naming Standard v1.1.

Every registered tool must be unprefixed, snake_case, <= 50 chars, and start with
a canonical verb so it composes cleanly behind the ``genefoundry-router`` gateway,
which mounts this server under the ``uniprot`` namespace (tools surface as
``uniprot_<tool>``). Guards against future drift. See issue berntpopp/uniprot-link#1.

Adopts the ratified two-tier verb canon (2026-06-30):
  Tier-1 -- universal read/query: get, search, list, resolve, find, compare, compute, map
  Tier-2 -- sanctioned domain action/compute: predict, annotate, recode, liftover, analyze,
            score, submit, export, generate, download
  ops/meta carve-out -- tools tagged 'ops' or 'meta' skip the verb rule (charset/length
  and no-self-prefix still apply). See docs/TOOL-NAMING-STANDARD-v1.md Q3.
"""

from __future__ import annotations

import re

from uniprot_link.mcp.facade import create_uniprot_mcp

_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")

#: Tier-1 -- universal read/query canon (Tool-Naming Standard v1.1).
_TIER1_VERBS = frozenset({"get", "search", "list", "resolve", "find", "compare", "compute", "map"})

#: Tier-2 -- sanctioned domain action/compute verbs (fleet-wide, Standard v1.1).
_TIER2_VERBS = frozenset(
    {
        "predict",
        "annotate",
        "recode",
        "liftover",
        "analyze",
        "score",
        "submit",
        "export",
        "generate",
        "download",
    }
)

#: Union of all canonical verbs (Tier-1 + Tier-2).
_CANONICAL_VERBS = _TIER1_VERBS | _TIER2_VERBS

#: Tags that exempt a tool from the verb rule (Standard v1.1 Q3 ops/meta carve-out).
_OPS_META_TAGS = frozenset({"ops", "meta"})

_NAMESPACE = "uniprot"


async def test_tool_names_conform_to_standard_v1_1() -> None:
    """Each tool must be charset/length-valid, un-self-prefixed, and verb-canonical.

    Tools tagged 'ops' or 'meta' are exempt from the verb rule but still subject
    to charset/length and no-self-prefix checks (Standard v1.1 Q3 carve-out).
    """
    mcp = create_uniprot_mcp()
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    assert tools, "no tools registered on the facade"
    for t in tools:
        assert _NAME_RE.match(t.name), f"{t.name!r} must match ^[a-z0-9_]{{1,50}}$"
        assert not t.name.startswith(f"{_NAMESPACE}_"), (
            f"{t.name!r} must not self-prefix the '{_NAMESPACE}' namespace "
            "token -- the gateway adds it"
        )
        tags = frozenset(getattr(t, "tags", None) or ())
        if tags & _OPS_META_TAGS:
            continue  # ops/meta carve-out: verb rule does not apply
        assert t.name.split("_", 1)[0] in _CANONICAL_VERBS, (
            f"{t.name!r} must start with a canonical verb {sorted(_CANONICAL_VERBS)}"
        )
