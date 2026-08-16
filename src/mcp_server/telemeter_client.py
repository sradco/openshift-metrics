"""RHOBS Telemeter Prometheus client (env-gated credentials)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

SSO_TOKEN_URL = (
    "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"
)

# Soft limits so agents cannot accidentally dump huge fleet tables.
DEFAULT_MAX_SERIES = 50
DEFAULT_MAX_POINTS_PER_SERIES = 20
HARD_MAX_SERIES = 200

AUTH_HELP = (
    "Set PROM_URL, CLIENTID, and CLIENTSECRET (repo .env or "
    "~/.config/openshift-metrics/env), then call telemeter_auth_status. "
    "Request a RHOBS service account and Telemeter API URL in Slack "
    "#rhobs-support. MCP/recipe bugs: see OWNERS — not #rhobs-support."
)


class TelemeterConfigError(ValueError):
    """Missing or invalid Telemeter configuration."""

    def __init__(self, message: str, *, code: str = "AUTH_MISSING") -> None:
        super().__init__(message)
        self.code = code


class TelemeterAuthError(RuntimeError):
    """SSO or token acquisition failed."""

    def __init__(self, message: str, *, code: str = "AUTH_FAILED") -> None:
        super().__init__(message)
        self.code = code


def credentials_present() -> bool:
    return bool(os.environ.get("CLIENTID") and os.environ.get("CLIENTSECRET"))


def get_prom_url() -> str:
    """Telemeter Prometheus API base URL (required; never hardcoded)."""
    url = (os.environ.get("PROM_URL") or "").strip()
    if not url:
        raise TelemeterConfigError(
            "PROM_URL must be set to your Telemeter Prometheus API base URL "
            f"(trailing slash required). {AUTH_HELP}",
            code="PROM_URL_MISSING",
        )
    return url


def get_access_token() -> str:
    client_id = os.environ.get("CLIENTID")
    client_secret = os.environ.get("CLIENTSECRET")
    if not client_id or not client_secret:
        raise TelemeterConfigError(
            f"CLIENTID and CLIENTSECRET must be set. {AUTH_HELP}",
            code="AUTH_MISSING",
        )
    # Use requests body (not curl argv) so secrets are not visible in `ps`.
    try:
        resp = requests.post(
            SSO_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "profile",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise TelemeterAuthError(
            f"Failed to reach RHSSO token endpoint: {exc}. {AUTH_HELP}",
            code="AUTH_FAILED",
        ) from exc

    if resp.status_code >= 400:
        raise TelemeterAuthError(
            f"RHSSO token request failed (HTTP {resp.status_code}). {AUTH_HELP}",
            code="AUTH_FAILED",
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise TelemeterAuthError(
            f"Invalid JSON from RHSSO token endpoint. {AUTH_HELP}",
            code="AUTH_FAILED",
        ) from exc
    token = payload.get("access_token")
    if not token:
        raise TelemeterAuthError(
            f"RHSSO response did not include access_token. {AUTH_HELP}",
            code="AUTH_FAILED",
        )
    return token


def _disable_ssl() -> bool:
    """SSL verify is on by default. Set TELEMETER_DISABLE_SSL=1 only if needed."""
    return os.environ.get("TELEMETER_DISABLE_SSL", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def prometheus_connect():
    try:
        import prometheus_api_client
    except ImportError as exc:
        raise TelemeterConfigError(
            "prometheus-api-client is required for live Telemeter queries. "
            "Install deps: ./scripts/install_mcp.sh",
            code="DEP_MISSING",
        ) from exc
    url = get_prom_url()
    token = get_access_token()
    headers = {"Authorization": f"bearer {token}"}
    disable_ssl = _disable_ssl()
    if disable_ssl:
        # Avoid spamming MCP stderr (Cursor surfaces urllib3 warnings as errors).
        import warnings

        from urllib3.exceptions import InsecureRequestWarning

        warnings.simplefilter("ignore", InsecureRequestWarning)
    return prometheus_api_client.PrometheusConnect(
        url=url, headers=headers, disable_ssl=disable_ssl
    )


def auth_status() -> dict[str, Any]:
    prom_url = (os.environ.get("PROM_URL") or "").strip() or None
    status: dict[str, Any] = {
        "credentials_present": credentials_present(),
        "prom_url_configured": bool(prom_url),
        # Echo only when set so agents can confirm config; never invent a default.
        "prom_url": prom_url,
        "token_ok": False,
        "error": None,
        "error_code": None,
        "help": AUTH_HELP,
    }
    if not prom_url:
        status["error"] = "PROM_URL not set"
        status["error_code"] = "PROM_URL_MISSING"
        return status
    if not status["credentials_present"]:
        status["error"] = "CLIENTID/CLIENTSECRET not set"
        status["error_code"] = "AUTH_MISSING"
        return status
    try:
        token = get_access_token()
        status["token_ok"] = bool(token)
    except (TelemeterConfigError, TelemeterAuthError) as exc:
        status["error"] = str(exc)
        status["error_code"] = getattr(exc, "code", "AUTH_FAILED")
    except Exception as exc:  # noqa: BLE001 — surfaced to agent
        status["error"] = str(exc)
        status["error_code"] = "AUTH_FAILED"
    return status


def _truncate_result(
    series_list: list[dict[str, Any]],
    max_series: int,
    max_points: int,
) -> dict[str, Any]:
    truncated = series_list[:max_series]
    out_series = []
    for series in truncated:
        item = {
            "metric": series.get("metric") or series.get("labels") or {},
        }
        values = series.get("values")
        value = series.get("value")
        if values is not None:
            item["values"] = values[-max_points:]
        if value is not None:
            item["value"] = value
        out_series.append(item)
    return {
        "series_returned": len(out_series),
        "series_total": len(series_list),
        "truncated": len(series_list) > max_series,
        "data": out_series,
    }


def query_instant(
    query: str,
    max_series: int = DEFAULT_MAX_SERIES,
) -> dict[str, Any]:
    from . import guardrails as gr

    max_series = max(1, min(max_series, HARD_MAX_SERIES))
    gr_meta = gr.enforce(query, mode="instant")
    client = prometheus_connect()
    raw = client.custom_query(query=query)
    # prometheus-api-client returns list of {metric, value}
    return {
        "query": query,
        "query_used": query,
        "mode": "instant",
        "guardrails": gr_meta,
        **_truncate_result(list(raw or []), max_series, DEFAULT_MAX_POINTS_PER_SERIES),
    }


def query_range(
    query: str,
    hours: float = 3.0,
    step: str = "1h",
    max_series: int = DEFAULT_MAX_SERIES,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    from . import guardrails as gr

    max_series = max(1, min(max_series, HARD_MAX_SERIES))
    hours = max(0.25, min(hours, 48.0))
    gr_meta = gr.enforce(query, mode="range", hours=hours)
    end = end_time or datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(hours=hours)
    client = prometheus_connect()
    backoff = 2
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            raw = client.custom_query_range(
                query=query,
                start_time=start,
                end_time=end,
                step=step,
            )
            return {
                "query": query,
                "query_used": query,
                "mode": "range",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "step": step,
                "guardrails": gr_meta,
                **_truncate_result(
                    list(raw or []), max_series, DEFAULT_MAX_POINTS_PER_SERIES
                ),
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == 4:
                break
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"Telemeter range query failed: {last_error}")
