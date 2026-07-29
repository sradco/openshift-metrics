#!/usr/bin/env python3
"""Smoke-test openshift-metrics MCP tools (catalog always; Telemeter if creds set).

Usage:
  source .venv/bin/activate
  export CLIENTID=... CLIENTSECRET=...   # optional, for live queries
  PYTHONPATH=src python scripts/smoke_test_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mcp_server import catalog, recipes, telemeter_client  # noqa: E402
from mcp_server.server import mcp  # noqa: E402


def section(title: str) -> None:
    print(f"\n=== {title} ===")


async def check_tool_registration() -> None:
    tools = await mcp.list_tools()
    names = sorted(t.name for t in tools)
    expected = {
        "search_metrics",
        "list_telemetry_metrics",
        "is_telemetry_metric",
        "describe_metric",
        "list_recipes",
        "run_recipe",
        "query_telemeter",
        "telemeter_auth_status",
    }
    missing = expected - set(names)
    if missing:
        raise SystemExit(f"Missing tools: {sorted(missing)}")
    print("registered tools:", ", ".join(names))


def check_catalog() -> None:
    vmi = catalog.is_telemetry_metric("cnv:vmi_status_running:count")
    print("is_telemetry_metric(cnv:vmi_status_running:count):", vmi["in_telemetry"])
    if not vmi["in_telemetry"]:
        raise SystemExit("expected cnv:vmi_status_running:count in allowlist")

    fake = catalog.is_telemetry_metric("not_a_real_telemetry_metric_zzz")
    print("is_telemetry_metric(fake):", fake["in_telemetry"])

    hits = catalog.search_metrics("cnv", limit=5)
    print(f"search_metrics('cnv') hits: {len(hits)}")
    for h in hits[:3]:
        print(f"  - {h['metric_name']} in_telemetry={h['in_telemetry']}")

    desc = catalog.describe_metric("cnv_abnormal")
    print("describe_metric(cnv_abnormal).in_telemetry:", desc["in_telemetry"])

    info = catalog.allowlist_source_info()
    print(f"allowlist matches: {info['match_count']}")


def check_recipes() -> None:
    listed = recipes.list_recipes(topic="cnv")
    print(f"cnv recipes: {len(listed)}")
    rendered = recipes.render_recipe_promql("total_running_vms", scope="external")
    print("total_running_vms promql:")
    print(" ", rendered["promql"])
    if "and on (_id)" not in rendered["promql"]:
        raise SystemExit("recipe did not use preferred and on (_id) join")


def check_telemeter() -> None:
    status = telemeter_client.auth_status()
    # Never print secrets; status itself does not include them.
    print("auth_status:", json.dumps(status))
    if not status.get("credentials_present"):
        print("SKIP live Telemeter: set CLIENTID and CLIENTSECRET to test queries")
        return
    if not status.get("token_ok"):
        raise SystemExit(f"credentials present but token failed: {status.get('error')}")

    result = recipes.run_recipe("total_running_vms", scope="external", mode="instant")
    series = result.get("result", {}).get("data") or []
    print("run_recipe(total_running_vms) series_returned:", len(series))
    print("promql:", result.get("promql"))
    if series:
        # Print only the numeric value, not label sets that may identify clusters.
        sample = series[0]
        print("sample value field present:", "value" in sample or "values" in sample)
        if "value" in sample:
            print("sample value:", sample["value"][-1] if isinstance(sample["value"], list) else sample["value"])


async def main() -> None:
    os.chdir(REPO)
    section("MCP tool registration")
    await check_tool_registration()
    section("Catalog (no credentials required)")
    check_catalog()
    section("Recipes (render only)")
    check_recipes()
    section("Telemeter (optional)")
    check_telemeter()
    section("Done")
    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
