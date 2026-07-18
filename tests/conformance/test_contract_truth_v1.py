"""Contract Truth v1 gate against the live UniProt MCP registry."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

EXPECTED_HELPER_SHA256 = "e6c12b087c8231f5324c6388abd01afaeffa305a84d0b7c0e3629e17993d3674"


async def test_documentation_matches_live_mcp_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    service_factory: Any,
) -> None:
    """Lint repository documentation against the production MCP registry."""
    helper_path = Path(__file__).with_name("contract_truth.py")
    pin_path = Path(__file__).with_name("contract_truth.sha256")

    vendored_pin = pin_path.read_text(encoding="utf-8").strip()
    assert vendored_pin == EXPECTED_HELPER_SHA256
    assert sha256(helper_path.read_bytes()).hexdigest() == vendored_pin

    from .contract_truth import (
        active_markdown_files,
        historical_markdown_files,
        lint_repository,
    )

    monkeypatch.setenv("UNIPROT_LINK_SPARQL__BASE_URL", "https://127.0.0.1:1/must-not-connect")
    monkeypatch.chdir(tmp_path)

    from uniprot_link.mcp import service_adapters
    from uniprot_link.mcp.facade import create_uniprot_mcp

    service_adapters.set_sparql_service(service_factory([]))
    try:
        tools = await create_uniprot_mcp().list_tools()
    finally:
        service_adapters.set_sparql_service(None)
    assert tools, "the live MCP registry must not be empty"

    catalog: dict[str, dict[str, object]] = {}
    for tool in tools:
        assert isinstance(tool.parameters, dict)
        catalog[tool.name] = {"inputSchema": tool.parameters}

    repo_root = Path(__file__).resolve().parents[2]
    assert active_markdown_files(repo_root), "active Markdown discovery must not be empty"
    assert historical_markdown_files(repo_root), "historical Markdown discovery must not be empty"

    findings = lint_repository(repo_root, catalog)
    rendered = "\n".join(
        f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in findings
    )
    assert not findings, rendered
