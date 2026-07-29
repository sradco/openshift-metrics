#!/usr/bin/env python3
"""MCP server for OpenShift metrics catalog + Telemeter queries."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Allow `python src/mcp_server/server.py` and package imports.
_SRC = Path(__file__).resolve().parents[1]
_REPO_ROOT = _SRC.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Load gitignored .env before reading CLIENTID/CLIENTSECRET.
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from mcp.server.mcpserver import MCPServer

from mcp_server import catalog, recipes, telemeter_client

mcp = MCPServer(
    name="openshift-metrics",
    instructions=(
        "OpenShift metrics catalog and Telemetry (Telemeter) query tools. "
        "knowledge/recipes/cnv.yaml is an example fleet recipe pack (often "
        "Virtualization metrics); join patterns are reusable for any domain. "
        "Prefer search_metrics/describe_metric for metric and label docs from "
        "committed catalogs (partial). Do not assume automatic live label "
        "discovery — query_telemeter only for explicit live PromQL. "
        "General catalog metrics are NOT all telemetered — use is_telemetry_metric. "
        "Never commit credentials or query results containing customer identifiers. "
        "Treat Cursor/Claude chat transcripts as sensitive: Telemeter results may "
        "include ebs_account, email_domain, and cluster _id. "
        "CRITICAL: When run_recipe or query_telemeter succeeds (or returns an error "
        "after building PromQL), your user-facing reply MUST include the PromQL from "
        "the query_used field (or promql/query). Never answer with only a number or "
        "summary — always show the query that was used. "
        "Prefer recipes over raw query_telemeter. Default scope is external. "
        "Telemeter queries are guarded (blanket regex, unrestricted selectors, "
        "rate limits) — adapted from rhobs/obs-mcp. Prefer run_recipe."
    ),
)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _ensure_query_used(payload: dict[str, Any], promql: str | None) -> dict[str, Any]:
    """Attach query_used so agents always have a single field to show users."""
    out = dict(payload)
    if promql:
        out["query_used"] = promql
        out.setdefault(
            "show_query_in_reply",
            "Always include query_used (PromQL) in the user-facing reply.",
        )
    return out


@mcp.tool()
def search_metrics(
    query: str,
    limit: int = 25,
    telemetry_only: bool = False,
) -> str:
    """Search general OpenShift metrics catalog (and Telemetry allowlist).

    Marks each hit with in_telemetry. Set telemetry_only=true to restrict to
    allowlisted Telemetry metrics.
    """
    return _json(
        {
            "query": query,
            "results": catalog.search_metrics(
                query, limit=limit, telemetry_only=telemetry_only
            ),
        }
    )


@mcp.tool()
def list_telemetry_metrics(query: str = "", limit: int = 100) -> str:
    """List metrics/selectors from the Telemetry allowlist (CMO-derived)."""
    return _json(
        {
            "allowlist": catalog.allowlist_source_info(),
            "matches": catalog.list_telemetry_metrics(
                query=query or None, limit=limit
            ),
        }
    )


@mcp.tool()
def is_telemetry_metric(metric_name: str) -> str:
    """Return whether a metric name is in the Telemetry allowlist."""
    return _json(catalog.is_telemetry_metric(metric_name))


@mcp.tool()
def describe_metric(metric_name: str) -> str:
    """Describe a metric from general catalog and/or Telemetry allowlist."""
    return _json(catalog.describe_metric(metric_name))


@mcp.tool()
def list_recipes(topic: str = "") -> str:
    """List named PromQL recipes (CNV fleet recipes first)."""
    return _json({"recipes": recipes.list_recipes(topic=topic or None)})


@mcp.tool()
def run_recipe(
    recipe_id: str,
    scope: str = "external",
    ebs_account: str = "",
    email_domain: str = "",
    cluster_id: str = "",
    mode: str = "instant",
    hours: float = 3.0,
    max_series: int = 50,
) -> str:
    """Render and execute a named Telemeter recipe.

    scope: external | internal | all
    Optional filters: ebs_account, email_domain, cluster_id (_id).
    Requires CLIENTID/CLIENTSECRET. Do not commit the result.

    Always include the returned query_used PromQL in the user-facing reply.
    """
    try:
        result = recipes.run_recipe(
            recipe_id,
            scope=scope,
            ebs_account=ebs_account or None,
            email_domain=email_domain or None,
            cluster_id=cluster_id or None,
            hours=hours,
            mode=mode,
            max_series=max_series,
        )
        return _json(
            _ensure_query_used(result, result.get("query_used") or result.get("promql"))
        )
    except KeyError as exc:
        return _json(
            {
                "error": str(exc),
                "error_code": "UNKNOWN_RECIPE",
                "available": [r["id"] for r in recipes.list_recipes()],
            }
        )
    except Exception as exc:  # noqa: BLE001
        payload: dict[str, Any] = {
            "error": str(exc),
            "error_code": getattr(exc, "code", "QUERY_FAILED"),
            "recipe_id": recipe_id,
            "help": getattr(telemeter_client, "AUTH_HELP", None),
        }
        if getattr(exc, "guardrail", None):
            payload["guardrail"] = exc.guardrail
        return _json(payload)


@mcp.tool()
def query_telemeter(
    promql: str,
    mode: str = "instant",
    hours: float = 3.0,
    step: str = "1h",
    max_series: int = 50,
) -> str:
    """Run raw PromQL against RHOBS Telemeter.

    Prefer recipes when available. Requires CLIENTID/CLIENTSECRET.
    Results are truncated; do not commit them. Fleet queries can return
    customer identifiers in labels — treat chat transcripts as sensitive.

    Guardrails (TELEMETER_GUARDRAILS, default all) reject blanket regex,
    unrestricted selectors, and enforce a query rate limit — adapted from
    rhobs/obs-mcp so agents cannot blast Telemeter.

    Always include the returned query_used PromQL in the user-facing reply.
    """
    try:
        if mode == "range":
            result = telemeter_client.query_range(
                promql, hours=hours, step=step, max_series=max_series
            )
        else:
            result = telemeter_client.query_instant(promql, max_series=max_series)
        result["privacy_note"] = (
            "Do not commit this result. Customer identifiers and values are "
            "runtime-only. Treat chat/transcripts as sensitive."
        )
        return _json(_ensure_query_used(result, result.get("query") or promql))
    except Exception as exc:  # noqa: BLE001
        payload: dict[str, Any] = {
            "error": str(exc),
            "error_code": getattr(exc, "code", "QUERY_FAILED"),
            "query": promql,
            "help": getattr(telemeter_client, "AUTH_HELP", None),
        }
        if getattr(exc, "guardrail", None):
            payload["guardrail"] = exc.guardrail
        return _json(_ensure_query_used(payload, promql))


@mcp.tool()
def telemeter_auth_status() -> str:
    """Check whether Telemeter credentials are present and a token can be obtained.

    Never returns secret values.
    """
    return _json(telemeter_client.auth_status())


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
