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
        "OpenShift metrics catalog and Telemetry (Telemeter) query tools for "
        "any Telemetry user — not limited to one product domain. "
        "knowledge/recipes/fleet.yaml has cross-domain fleet recipes; "
        "knowledge/recipes/cnv.yaml is an optional example pack (virt-seeded). "
        "Add more packs as knowledge/recipes/<domain>.yaml. Join patterns are "
        "reusable across domains. "
        "Prefer search_metrics/describe_metric for metric and label docs from "
        "committed catalogs (partial). Do not assume automatic live label "
        "discovery — query_telemeter only for explicit live PromQL. "
        "General catalog metrics are NOT all telemetered — use is_telemetry_metric. "
        "Never commit credentials or query results containing customer identifiers. "
        "Treat Cursor/Claude chat transcripts as sensitive: Telemeter results may "
        "include ebs_account, email_domain, and cluster _id. "
        "CRITICAL: When run_recipe, query_scoped_metric, or query_telemeter succeeds "
        "(or returns an error after building PromQL), your user-facing reply MUST "
        "include the PromQL from the query_used field (or promql/query). Never "
        "answer with only a number or summary — always show the query that was used. "
        "Tool order for live fleet data: (1) run_recipe if a named recipe fits, "
        "(2) query_scoped_metric / render_scoped_promql for an allowlisted metric "
        "with sum|count_clusters|sum_by + scope/filters, (3) query_telemeter only "
        "for custom PromQL those tools cannot express. Default scope is external. "
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
def list_recipes(topic: str = "", pack: str = "") -> str:
    """List named PromQL recipes (fleet pack + any domain packs).

    Optional topic (e.g. cnv, fleet, builds) and/or pack to reduce the list.
    pack is the recipe YAML filename stem (NOT the MCP server name):
      fleet | cnv | coo | ocp-builds | rhacs
    Omit pack to list all packs. Omit topic to list all topics.
    """
    return _json(
        {
            "recipes": recipes.list_recipes(
                topic=topic or None,
                pack=pack or None,
            )
        }
    )


@mcp.tool()
def run_recipe(
    recipe_id: str,
    scope: str = "external",
    ebs_account: str = "",
    email_domain: str = "",
    cluster_id: str = "",
    mode: str = "instant",
    hours: float = 3.0,
    step: str = "1h",
    max_series: int = 50,
) -> str:
    """Render and execute a named Telemeter recipe.

    scope: external | internal | all
    Optional filters: ebs_account, email_domain, cluster_id (_id).
    step applies only when mode=range (default 1h).
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
            step=step,
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
def render_scoped_promql(
    metric_name: str,
    aggregation: str = "sum",
    scope: str = "external",
    ebs_account: str = "",
    email_domain: str = "",
    cluster_id: str = "",
    label_equals: str = "",
    by: str = "",
    require_telemetry: bool = True,
) -> str:
    """Build scoped fleet PromQL for an allowlisted metric (no named recipe).

    Use when list_recipes has no matching recipe. Prefer run_recipe when one fits.

    aggregation: sum | count_clusters | sum_by (sum_by requires by=)
    scope: external | internal | all
    label_equals: plain key=value pairs (no quotes), e.g.
      resource=virtualmachines.kubevirt.io
    by: comma-separated labels ON THE METRIC for sum_by (e.g. strategy).
      Do not use ebs_account/email_domain here — use filters or run_recipe.
    require_telemetry: leave true (default). Set false only for known
      Telemeter enrichment metrics such as ocm_subscription — almost never.

    Returns promql / query_used; does not execute. Use query_scoped_metric to run.
    """
    try:
        result = recipes.render_scoped_promql(
            metric_name,
            aggregation=aggregation,
            scope=scope,
            ebs_account=ebs_account or None,
            email_domain=email_domain or None,
            cluster_id=cluster_id or None,
            label_equals=label_equals or None,
            by=by or None,
            require_telemetry=require_telemetry,
        )
        return _json(_ensure_query_used(result, result.get("promql")))
    except ValueError as exc:
        return _json(
            {
                "error": str(exc),
                "error_code": "INVALID_SCOPED_QUERY",
                "metric_name": metric_name,
                "aggregation": aggregation,
            }
        )


@mcp.tool()
def query_scoped_metric(
    metric_name: str,
    aggregation: str = "sum",
    scope: str = "external",
    ebs_account: str = "",
    email_domain: str = "",
    cluster_id: str = "",
    label_equals: str = "",
    by: str = "",
    require_telemetry: bool = True,
    mode: str = "instant",
    hours: float = 3.0,
    step: str = "1h",
    max_series: int = 50,
) -> str:
    """Render scoped PromQL for an allowlisted metric and query Telemeter.

    Prefer run_recipe when a named recipe matches. Prefer this over raw
    query_telemeter for simple fleet sum / count_clusters / sum_by questions.

    Same parameters as render_scoped_promql, plus mode/hours/step/max_series.
    step applies only when mode=range (default 1h).
    require_telemetry: leave true unless querying known enrichment metrics.
    Requires CLIENTID/CLIENTSECRET. Always include query_used in the reply.
    """
    try:
        result = recipes.query_scoped_metric(
            metric_name,
            aggregation=aggregation,
            scope=scope,
            ebs_account=ebs_account or None,
            email_domain=email_domain or None,
            cluster_id=cluster_id or None,
            label_equals=label_equals or None,
            by=by or None,
            require_telemetry=require_telemetry,
            hours=hours,
            mode=mode,
            step=step,
            max_series=max_series,
        )
        return _json(
            _ensure_query_used(result, result.get("query_used") or result.get("promql"))
        )
    except ValueError as exc:
        return _json(
            {
                "error": str(exc),
                "error_code": "INVALID_SCOPED_QUERY",
                "metric_name": metric_name,
                "aggregation": aggregation,
            }
        )
    except Exception as exc:  # noqa: BLE001
        payload: dict[str, Any] = {
            "error": str(exc),
            "error_code": getattr(exc, "code", "QUERY_FAILED"),
            "metric_name": metric_name,
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
