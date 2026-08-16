"""Runtime env file precedence (exported > repo .env > XDG)."""

from __future__ import annotations

import os

import pytest

from mcp_server.runtime_env import load_runtime_env, reset_runtime_env_for_tests


@pytest.fixture(autouse=True)
def _isolate_environ():
    reset_runtime_env_for_tests()
    saved = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(saved)
    reset_runtime_env_for_tests()


def _write(path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_env_precedence_exported_beats_dotenv_beats_xdg(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("PROM_URL", "https://exported.example/")
    monkeypatch.delenv("CLIENTID", raising=False)
    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.delenv("MCP_PORT", raising=False)

    _write(
        xdg / "openshift-metrics" / "env",
        "PROM_URL=https://xdg.example/\nCLIENTID=xdg-id\nMCP_HOST=10.0.0.1\n",
    )
    _write(
        repo / ".env",
        "PROM_URL=https://dotenv.example/\nCLIENTID=dotenv-id\nMCP_PORT=9999\n",
    )

    load_runtime_env(repo)

    assert os.environ["PROM_URL"] == "https://exported.example/"
    assert os.environ["CLIENTID"] == "dotenv-id"
    assert os.environ["MCP_HOST"] == "10.0.0.1"
    assert os.environ["MCP_PORT"] == "9999"


def test_load_runtime_env_is_idempotent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CLIENTSECRET", raising=False)
    _write(repo / ".env", "CLIENTSECRET=first\n")

    load_runtime_env(repo)
    _write(repo / ".env", "CLIENTSECRET=second\n")
    load_runtime_env(repo)
    assert os.environ["CLIENTSECRET"] == "first"
