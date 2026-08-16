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

# Load XDG env + repo .env once (exported values win). Launchers do not
# load env files — that would duplicate this.
from mcp_server.runtime_env import load_runtime_env

load_runtime_env(_REPO_ROOT)

from mcp.server.mcpserver import MCPServer

from mcp_server import catalog, recipes, telemeter_client
from mcp_server.guardrails import rate_limit_status

mcp = MCPServer(
    name="openshift-metrics",
    instructions=(
        "OpenShift metrics catalog and Telemetry (Telemeter) query tools for "
        "any Telemetry user — not limited to one product domain. "
        "knowledge/recipes/fleet.yaml has cross-domain fleet recipes; "
        "optional packs include cnv.yaml and okd.yaml. "
        "Add more packs as knowledge/recipes/<domain>.yaml. "
        "RESEARCH BUDGET: plan 2–5 queries; prefer run_recipe; at most one "
        "list_recipes (topic/pack) and ≤2 catalog lookups; watch "
        "queries_remaining_in_window and stop exploring when low. "
        "Cohort playbook: observability check → cohort recipe → measure → "
        "age → adverse-effects recipes → stop. "
        "RHCOS/FCOS 9 vs 10 is NOT telemetered (mcd_host_os_and_version). "
        "Prefer search_metrics/describe_metric for metric docs (partial). "
        "General catalog metrics are NOT all telemetered — use is_telemetry_metric. "
        "Never commit credentials or query results containing customer identifiers. "
        "Treat chat transcripts as sensitive (ebs_account, email_domain, _id). "
        "CRITICAL: Always include query_used PromQL in the user-facing reply. "
        "Tool order: (1) run_recipe, (2) query_scoped_metric / render_scoped_promql, "
        "(3) query_telemeter only for custom PromQL. Default scope is external; "
        "okd pack omits OCM scope_join. Guardrails: blanket regex, unrestricted "
        "selectors, rate limits (adapted from rhobs/obs-mcp)."
    ),
)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _with_rate_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach rate-limit remaining so agents can self-throttle."""
    out = dict(payload)
    status = rate_limit_status()
    out["queries_remaining_in_window"] = status.get("queries_remaining_in_window")
    out["queries_used_in_window"] = status.get("queries_used_in_window")
    out["rate_limit"] = status
    return out


def _ensure_query_used(payload: dict[str, Any], promql: str | None) -> dict[str, Any]:
    """Attach query_used so agents always have a single field to show users."""
    out = _with_rate_status(payload)
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
def list_telemetry_metrics(
    query: str = "",
    limit: int = 25,
    detail: bool = False,
) -> str:
    """List metrics/selectors from the Telemetry allowlist (CMO-derived).

    Default limit=25 and detail=false (truncated descriptions, no owners).
    Pass detail=true only when full allowlist text is required.
    Prefer a tight query= filter over browsing the whole allowlist.
    """
    return _json(
        {
            "allowlist": catalog.allowlist_source_info(),
            "detail": detail,
            "matches": catalog.list_telemetry_metrics(
                query=query or None, limit=limit, detail=detail
            ),
            "note": (
                "Slim listing by default. Use detail=true for full descriptions/"
                "owners. Prefer is_telemetry_metric for a single name."
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
def list_recipes(topic: str = "", pack: str = "", detail: bool = False) -> str:
    """List named PromQL recipes (fleet pack + any domain packs).

    Optional topic (e.g. cnv, fleet, okd, builds) and/or pack to reduce the list.
    pack is the recipe YAML filename stem (NOT the MCP server name):
      fleet | cnv | okd | coo | ocp-builds | rhacs
    Omit pack to list all packs. Omit topic to list all topics.
    detail=false (default) omits long descriptions — id/title/topics only.
    """
    return _json(
        {
            "detail": detail,
            "recipes": recipes.list_recipes(
                topic=topic or None,
                pack=pack or None,
                detail=detail,
            ),
            "note": (
                "Slim listing by default. Pass detail=true for descriptions. "
                "Prefer run_recipe with a known id over re-listing."
            ),
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
            _with_rate_status(
                {
                    "error": str(exc),
                    "error_code": "UNKNOWN_RECIPE",
                    "available": [r["id"] for r in recipes.list_recipes()],
                }
            )
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
        return _json(_with_rate_status(payload))


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
        return _json(_with_rate_status(payload))


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

    Never returns secret values. Includes queries_remaining_in_window.
    """
    return _json(_with_rate_status(telemeter_client.auth_status()))


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any) -> Any:
    """Liveness for HTTP/container deployments (not used on stdio)."""
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "name": "openshift-metrics"})


_TRANSPORTS = ("stdio", "streamable-http")


def _parse_http_port(raw: str) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        print(f"invalid HTTP port {raw!r} (--port / MCP_PORT)", file=sys.stderr)
        raise SystemExit(2) from exc
    if not (1 <= port <= 65535):
        print(f"invalid HTTP port {port} (--port / MCP_PORT)", file=sys.stderr)
        raise SystemExit(2)
    return port


def _run_streamable_http(host: str, port: int, path: str) -> None:
    import os

    import uvicorn

    from mcp_server.http_auth import (
        BearerAuthMiddleware,
        ensure_http_token,
        is_loopback_host,
    )

    token = (os.environ.get("MCP_HTTP_TOKEN") or "").strip()
    try:
        ensure_http_token(token)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    if not is_loopback_host(host):
        print(
            "openshift-metrics: HTTP MCP is cleartext. Put a TLS gateway "
            f"in front of {host}:{port} before exposing it on a network.",
            file=sys.stderr,
        )
    print(
        f"openshift-metrics: HTTP MCP on http://{host}:{port}{path}",
        file=sys.stderr,
    )
    print(f"Health: http://{host}:{port}/health", file=sys.stderr)

    app: Any = BearerAuthMiddleware(
        mcp.streamable_http_app(
            streamable_http_path=path,
            host=host,
        ),
        token,
    )
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uvicorn.Server(config).run()


def main(argv: list[str] | None = None) -> None:
    """Run the MCP server (stdio default; HTTP requires MCP_HTTP_TOKEN)."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="OpenShift metrics MCP server")
    parser.add_argument(
        "--transport",
        choices=_TRANSPORTS,
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="MCP transport (default: stdio, or MCP_TRANSPORT)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
        help="HTTP bind host (streamable-http only; default 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        default=os.environ.get("MCP_PORT", "8000"),
        help="HTTP bind port (streamable-http only)",
    )
    parser.add_argument(
        "--path",
        default=os.environ.get("MCP_PATH", "/mcp"),
        help="HTTP MCP path (streamable-http only; default /mcp)",
    )
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    _run_streamable_http(args.host, _parse_http_port(args.port), args.path)


if __name__ == "__main__":
    main()
