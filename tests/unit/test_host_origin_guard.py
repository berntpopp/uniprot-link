"""Host/Origin boundary contracts for the unified MCP application."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from packaging.version import Version

from uniprot_link.config import ServerSettings, settings
from uniprot_link.server_manager import create_unified_app

PUBLIC_HOST = "uniprot-link.genefoundry.org"
PUBLIC_ORIGIN = f"https://{PUBLIC_HOST}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        settings,
        "allowed_hosts",
        ["localhost", "127.0.0.1", "::1", PUBLIC_HOST],
    )
    monkeypatch.setattr(settings, "allowed_origins", [PUBLIC_ORIGIN])
    monkeypatch.setattr(settings, "cors_origins", [PUBLIC_ORIGIN])
    return TestClient(create_unified_app(), raise_server_exceptions=False)


def test_fastmcp_344_strict_guard_is_installed(client: TestClient) -> None:
    assert Version(version("fastmcp")) >= Version("3.4.4")
    response = client.get("/mcp", headers={"Host": PUBLIC_HOST})
    assert response.status_code not in {403, 421}


def test_default_allowlists_are_loopback_only_and_origin_empty() -> None:
    configured = ServerSettings(_env_file=None)
    assert configured.allowed_hosts == ["localhost", "127.0.0.1", "::1"]
    assert configured.allowed_origins == []


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_hosts_are_allowed(client: TestClient, host: str) -> None:
    response = client.get("/mcp", headers={"Host": host})
    assert response.status_code not in {403, 421}


@pytest.mark.parametrize("path", ["/", "/health", "/mcp"])
def test_untrusted_host_is_rejected_on_every_route(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"Host": "evil.example"})
    assert response.status_code == 421


def test_absent_origin_is_allowed(client: TestClient) -> None:
    response = client.get("/mcp", headers={"Host": PUBLIC_HOST})
    assert response.status_code not in {403, 421}


def test_public_origin_is_allowed_by_guard_and_cors(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Host": PUBLIC_HOST,
            "Origin": PUBLIC_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code not in {403, 421}
    assert response.headers["access-control-allow-origin"] == PUBLIC_ORIGIN


@pytest.mark.parametrize("path", ["/", "/health", "/mcp"])
def test_untrusted_origin_is_rejected_on_every_route(client: TestClient, path: str) -> None:
    response = client.get(
        path,
        headers={"Host": PUBLIC_HOST, "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("wildcard", ["*", "*.example.org", "host?.example.org", "host[0]"])
def test_wildcard_host_is_rejected(wildcard: str) -> None:
    with pytest.raises(ValueError, match="wildcard"):
        ServerSettings(_env_file=None, allowed_hosts=[wildcard])


def test_json_environment_allowlists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "UNIPROT_LINK_ALLOWED_HOSTS",
        f'["localhost","{PUBLIC_HOST}"]',
    )
    monkeypatch.setenv("UNIPROT_LINK_ALLOWED_ORIGINS", f'["{PUBLIC_ORIGIN}"]')
    configured = ServerSettings(_env_file=None)
    assert configured.allowed_hosts == ["localhost", PUBLIC_HOST]
    assert configured.allowed_origins == [PUBLIC_ORIGIN]


@pytest.mark.parametrize(
    "compose_file",
    [
        "docker/docker-compose.yml",
        "docker/docker-compose.prod.yml",
        "docker/docker-compose.npm.yml",
    ],
)
def test_compose_propagates_allowlist_and_healthcheck_host(compose_file: str) -> None:
    text = Path(compose_file).read_text()
    assert "UNIPROT_LINK_ALLOWED_HOSTS" in text
    assert '"localhost","127.0.0.1","::1"' in text
    assert '"Host: localhost"' in text


@pytest.mark.parametrize(
    "compose_file", ["docker/docker-compose.prod.yml", "docker/docker-compose.npm.yml"]
)
def test_public_compose_couples_request_origin_and_cors(compose_file: str) -> None:
    text = Path(compose_file).read_text()
    assert "UNIPROT_LINK_ALLOWED_ORIGINS" in text
    assert "UNIPROT_LINK_CORS_ORIGINS" in text
    assert text.count(f'["{PUBLIC_ORIGIN}"]') >= 2
