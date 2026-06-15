"""Unit tests for the typer CLI (`uniprot_link.cli`)."""

from __future__ import annotations

import importlib.metadata

import pytest
from typer.testing import CliRunner

from uniprot_link import __version__
from uniprot_link.cli import app

runner = CliRunner()


def test_app_help_lists_all_commands() -> None:
    """`--help` shows serve, config, health, and version commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("serve", "config", "health", "version"):
        assert command in result.output


def test_no_args_shows_help() -> None:
    """Invoking with no args is help, not a bare-serve."""
    result = runner.invoke(app, [])
    # no_args_is_help exits 0 (typer) or 2 depending on version; both print help.
    assert result.exit_code in (0, 2)
    assert "Usage" in result.output


def test_version_prints_package_version() -> None:
    """`version` prints the installed package version."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_shows_settings() -> None:
    """`config` renders the resolved configuration."""
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "transport" in result.output
    assert "mcp_path" in result.output


def test_config_validate_ok() -> None:
    """`config --validate` reports a valid configuration."""
    result = runner.invoke(app, ["config", "--validate"])
    assert result.exit_code == 0
    assert "valid" in result.output.lower()


def test_serve_rejects_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    """`serve --transport stdio` is rejected (Streamable HTTP only)."""
    called = False

    def _fake_run(_coro: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("uniprot_link.cli.asyncio.run", _fake_run)
    result = runner.invoke(app, ["serve", "--transport", "stdio"])
    assert result.exit_code != 0
    assert not called, "server must not start for an invalid transport"


@pytest.mark.parametrize("transport", ["unified", "http"])
def test_serve_accepts_valid_transports(transport: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`serve` accepts both `unified` and `http` and boots the manager."""
    captured: dict[str, object] = {}

    def _fake_run(_coro: object) -> None:
        captured["ran"] = True
        # Close the coroutine to avoid 'never awaited' warnings.
        if hasattr(_coro, "close"):
            _coro.close()  # type: ignore[attr-defined]

    monkeypatch.setattr("uniprot_link.cli.asyncio.run", _fake_run)
    result = runner.invoke(app, ["serve", "--transport", transport, "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert captured.get("ran") is True


def test_console_script_entry_point_resolves() -> None:
    """The `uniprot-link` console script maps to `uniprot_link.cli:app`."""
    eps = importlib.metadata.entry_points(group="console_scripts")
    matches = [ep for ep in eps if ep.name == "uniprot-link"]
    assert matches, "uniprot-link console script is not registered"
    assert matches[0].value == "uniprot_link.cli:app"
