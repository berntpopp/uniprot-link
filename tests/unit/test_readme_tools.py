"""The README '## Tools' table must list exactly the registered tools.

GeneFoundry README Standard v1, Rule 6: the tool table is machine-verified, not
hand-maintained. Adding, removing, or renaming a tool without updating the README
fails CI.

The live tool list is obtained the same way ``test_tool_names.py`` obtains it --
from the real facade (``create_uniprot_mcp``) -- so the two guards cannot disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

from uniprot_link.mcp.facade import create_uniprot_mcp

README = Path(__file__).resolve().parents[2] / "README.md"

#: A leading `| \`tool_name\` |` cell in a Markdown table row.
_ROW_RE = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|")


def _readme_tools() -> set[str]:
    """Tool names in the README '## Tools' table (up to the next H2)."""
    lines = README.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## Tools")
    except ValueError as exc:  # pragma: no cover - guarded by the section test below
        raise AssertionError("README.md has no '## Tools' section") from exc

    names: set[str] = set()
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        match = _ROW_RE.match(line)
        if match:
            names.add(match.group(1))
    return names


async def test_readme_tool_table_matches_registered_tools() -> None:
    """The table's tool names must equal the server's registered tools exactly."""
    mcp = create_uniprot_mcp()
    registered = {t.name for t in await mcp.list_tools()}
    assert registered, "no tools registered on the facade"

    documented = _readme_tools()
    assert documented, "README '## Tools' table lists no tools"

    missing = registered - documented
    extra = documented - registered
    assert not missing, f"tools registered but absent from the README table: {sorted(missing)}"
    assert not extra, f"tools in the README table but not registered: {sorted(extra)}"
