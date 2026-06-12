"""Self-test harness: exercise the NEW uniprot-link MCP in-process against the
live endpoint, as an LLM consumer would, for the task 'get domains for PNKP'.

Throwaway research script (not shipped/typed). Run: `uv run python research/self_test_pnkp.py`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from uniprot_link.api.client import SparqlClient
from uniprot_link.config import SparqlEndpointConfig
from uniprot_link.mcp import service_adapters
from uniprot_link.mcp.facade import create_uniprot_mcp
from uniprot_link.services.sparql_service import SparqlService


def _size(obj: Any) -> int:
    """Char length of the compact-JSON serialization (token proxy)."""
    return len(json.dumps(obj, separators=(",", ":")))


def _unwrap(result: Any) -> Any:
    return getattr(result, "structured_content", None) or result


async def main() -> None:
    config = SparqlEndpointConfig(timeout=40)
    client = SparqlClient(config)
    service_adapters.set_sparql_service(SparqlService(client, config))
    mcp = create_uniprot_mcp()

    # --- Discoverability: the tool surface an LLM reads up front ---
    tools = await mcp.list_tools()
    print("=" * 70)
    print(f"DISCOVERABILITY: {len(tools)} tools")
    desc_total = 0
    for t in tools:
        d = getattr(t, "description", "") or ""
        desc_total += len(d)
    print(f"  total tool-description chars: {desc_total}")
    caps = await mcp.call_tool("get_server_capabilities", {})
    cap = _unwrap(caps)
    print(f"  capabilities payload chars: {_size(cap)}")
    print(f"  capabilities keys: {sorted(cap.keys())}")

    async def call(name: str, args: dict[str, Any]) -> Any:
        res = _unwrap(await mcp.call_tool(name, args))
        em = res.get("_meta", {}) if isinstance(res, dict) else {}
        print("-" * 70)
        print(f"CALL {name}({args})")
        print(f"  payload chars: {_size(res)}  elapsed_ms: {res.get('elapsed_ms')}  "
              f"cached: {res.get('cached')}")
        nc = em.get("next_commands")
        print(f"  next_commands: {[c['tool'] for c in nc] if nc else None}")
        print(f"  _meta keys: {sorted(em.keys())}")
        return res

    # --- The task: get domains for PNKP ---
    print("\n" + "#" * 70)
    print("# TASK: get domains for PNKP")
    print("#" * 70)

    found = await call("find_proteins", {"gene": "PNKP", "organism_taxon": 9606, "reviewed": True})
    print("  ", json.dumps(found.get("proteins"), separators=(",", ":"))[:300])
    acc = found["proteins"][0]["accession"] if found.get("proteins") else "Q96T60"

    summary = await call("get_protein", {"accession": acc})
    print("  summary:", json.dumps(summary, separators=(",", ":"))[:400])

    feats = await call("get_protein_features", {"accession": acc, "feature_types": ["domain"]})
    print("  domains:", json.dumps(feats.get("features"), separators=(",", ":"))[:500])

    # --- Probes across dimensions ---
    print("\n" + "#" * 70)
    print("# DIMENSION PROBES")
    print("#" * 70)

    # token efficiency: compact vs full
    s_min = await call("get_protein", {"accession": acc, "response_mode": "minimal"})
    s_full = await call("get_protein", {"accession": acc, "response_mode": "full"})
    print(f"  get_protein sizes -> minimal:{_size(s_min)} compact:{_size(summary)} full:{_size(s_full)}")

    # all features (unfiltered) — token cost + vocab round-trip
    allf = await call("get_protein_features", {"accession": acc})
    types = sorted({f["type"] for f in allf.get("features", [])})
    print(f"  all feature types returned: {types}")

    # error handling
    nf = await call("get_protein", {"accession": "ZZZZZZ"})
    print(f"  bogus get_protein -> success:{nf.get('success')} code:{nf.get('error_code')} "
          f"recovery:{nf.get('recovery_action')} next:{[c['tool'] for c in nf.get('_meta',{}).get('next_commands',[])]}")
    wr = await call("run_sparql_query", {"query": "INSERT DATA { <a> <b> <c> }"})
    print(f"  write -> success:{wr.get('success')} code:{wr.get('error_code')}")

    # variants disease linkage (the headline correctness fix)
    var = await call("get_protein_variants", {"accession": acc, "limit": 50})
    with_dis = [v for v in var.get("variants", []) if v.get("diseases")]
    print(f"  variants:{var.get('count')} with_disease:{len(with_dis)} sample:"
          f"{json.dumps(with_dis[0], separators=(',',':')) if with_dis else 'none'}")

    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
