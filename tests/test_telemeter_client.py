"""Unit tests for Telemeter client helpers (no live network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from mcp_server import telemeter_client  # noqa: E402


def test_get_access_token_requires_creds(monkeypatch):
    monkeypatch.delenv("CLIENTID", raising=False)
    monkeypatch.delenv("CLIENTSECRET", raising=False)
    with pytest.raises(telemeter_client.TelemeterConfigError) as exc:
        telemeter_client.get_access_token()
    assert exc.value.code == "AUTH_MISSING"
    assert "rhobs-support" in str(exc.value)


def test_get_access_token_uses_requests_not_curl(monkeypatch):
    monkeypatch.setenv("CLIENTID", "example-id")
    monkeypatch.setenv("CLIENTSECRET", "example-secret")

    class FakeResp:
        status_code = 200

        def json(self):
            return {"access_token": "tok"}

    called = {}

    def fake_post(url, data=None, timeout=None):
        called["url"] = url
        called["data"] = data
        called["timeout"] = timeout
        # Ensure secret is in POST body, not constructed as shell argv.
        assert data["client_secret"] == "example-secret"
        return FakeResp()

    monkeypatch.setattr(telemeter_client.requests, "post", fake_post)
    assert telemeter_client.get_access_token() == "tok"
    assert "openid-connect/token" in called["url"]


def test_auth_status_requires_prom_url(monkeypatch):
    monkeypatch.delenv("PROM_URL", raising=False)
    monkeypatch.delenv("CLIENTID", raising=False)
    monkeypatch.delenv("CLIENTSECRET", raising=False)
    status = telemeter_client.auth_status()
    assert status["prom_url_configured"] is False
    assert status["prom_url"] is None
    assert status["error_code"] == "PROM_URL_MISSING"
    assert "rhobs-support" in status["help"]


def test_auth_status_includes_help(monkeypatch):
    monkeypatch.setenv("PROM_URL", "https://example.invalid/telemeter/")
    monkeypatch.delenv("CLIENTID", raising=False)
    monkeypatch.delenv("CLIENTSECRET", raising=False)
    status = telemeter_client.auth_status()
    assert status["credentials_present"] is False
    assert status["prom_url_configured"] is True
    assert status["error_code"] == "AUTH_MISSING"
    assert "rhobs-support" in status["help"]


def test_get_prom_url_required(monkeypatch):
    monkeypatch.delenv("PROM_URL", raising=False)
    with pytest.raises(telemeter_client.TelemeterConfigError) as exc:
        telemeter_client.get_prom_url()
    assert exc.value.code == "PROM_URL_MISSING"
