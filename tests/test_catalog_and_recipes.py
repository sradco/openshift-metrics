"""Unit tests for catalog + recipe rendering (no network / no credentials)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from mcp_server.catalog import (  # noqa: E402
    describe_metric,
    is_telemetry_metric,
    list_telemetry_metrics,
)
from mcp_server.recipes import list_recipes, render_recipe_promql, run_recipe  # noqa: E402
from mcp_server.server import _ensure_query_used  # noqa: E402


def test_allowlist_contains_cnv_vmi():
    assert is_telemetry_metric("cnv:vmi_status_running:count")["in_telemetry"] is True


def test_allowlist_rejects_unknown():
    assert is_telemetry_metric("not_a_real_telemetry_metric_zzz")["in_telemetry"] is False


def test_list_telemetry_metrics_filter():
    hits = list_telemetry_metrics(query="cnv", limit=20)
    assert hits
    assert any(
        "cnv" in (h.get("metric_name") or h.get("metric_name_regex") or "").lower()
        for h in hits
    )


def test_describe_metric_telemetry_flag():
    desc = describe_metric("cnv:vmi_status_running:count")
    assert desc["in_telemetry"] is True
    assert desc.get("telemetry")


def test_list_cnv_recipes():
    recipes = list_recipes(topic="cnv")
    ids = {r["id"] for r in recipes}
    assert "total_running_vms" in ids
    assert "clusters_with_cnv_installed" in ids


def test_render_recipe_includes_external_join_and_filter():
    rendered = render_recipe_promql(
        "total_running_vms",
        scope="external",
        ebs_account="EXAMPLE_ONLY",
    )
    promql = rendered["promql"]
    assert "cnv:vmi_status_running:count" in promql
    assert "and on (_id)" in promql
    assert 'internal=""' in promql
    assert 'ebs_account="EXAMPLE_ONLY"' in promql
    # Prefer set matching over legacy dummy group_left(_blah)
    assert "group_left(_blah)" not in promql
    assert "CLIENTSECRET" not in promql


def test_ensure_query_used_attaches_fields():
    out = _ensure_query_used({"value": 1}, "sum(up)")
    assert out["query_used"] == "sum(up)"
    assert "show_query_in_reply" in out
    assert out["value"] == 1


def test_run_recipe_includes_query_used(monkeypatch):
    def fake_instant(query, max_series=50):
        return {
            "query": query,
            "query_used": query,
            "mode": "instant",
            "series_returned": 0,
            "series_total": 0,
            "truncated": False,
            "data": [],
        }

    monkeypatch.setattr(
        "mcp_server.telemeter_client.query_instant",
        fake_instant,
    )
    result = run_recipe("total_running_vms", scope="external")
    assert result["query_used"]
    assert result["query_used"] == result["promql"]
    assert "cnv:vmi_status_running:count" in result["query_used"]
    assert "show_query_in_reply" in result
    assert "result" in result


def test_run_recipe_error_still_includes_query_used(monkeypatch):
    def boom(query, max_series=50):
        raise RuntimeError("simulated telemeter failure")

    monkeypatch.setattr("mcp_server.telemeter_client.query_instant", boom)
    result = run_recipe("total_running_vms", scope="external")
    assert "error" in result
    assert result.get("error_code") == "QUERY_FAILED"
    assert result["query_used"] == result["promql"]
    assert "cnv:vmi_status_running:count" in result["query_used"]


def test_percent_clusters_scope_matrix():
    ext = render_recipe_promql("percent_clusters_with_vms", scope="external")["promql"]
    internal = render_recipe_promql("percent_clusters_with_vms", scope="internal")[
        "promql"
    ]
    all_scope = render_recipe_promql("percent_clusters_with_vms", scope="all")["promql"]

    assert 'cluster_subscribed{internal=""}' in ext
    assert ext.count('internal=""') >= 2  # numerator join + denominator
    assert 'internal="true"' in internal
    assert 'internal=""' not in internal
    # scope=all: both sides use subscribed (no internal= filter) so ratio ≤ 100%
    assert all_scope.count("cluster_subscribed") >= 2
    assert 'internal=""' not in all_scope
    assert 'internal="true"' not in all_scope
    assert "and on (_id)" in all_scope


def test_percentile_recipes_honor_scope():
    for recipe_id in (
        "median_vms_per_cluster",
        "p75_vms_per_cluster",
        "p90_vms_per_cluster",
    ):
        ext = render_recipe_promql(recipe_id, scope="external")["promql"]
        internal = render_recipe_promql(recipe_id, scope="internal")["promql"]
        all_scope = render_recipe_promql(recipe_id, scope="all")["promql"]
        assert 'internal=""' in ext
        assert 'internal="true"' in internal
        assert 'internal=""' not in internal
        # scope=all = all subscribed (external+internal), not unfiltered series
        assert "cluster_subscribed" in all_scope
        assert 'cluster_subscribed{internal=""}' not in all_scope
        assert 'cluster_subscribed{internal="true"}' not in all_scope


def test_list_recipes_reports_scope_support():
    recipes = {r["id"]: r for r in list_recipes(topic="cnv")}
    assert recipes["total_running_vms"]["supports_scope"] is True
    assert recipes["total_running_vms"]["supports_filters"] is True
    assert recipes["percent_clusters_with_vms"]["supports_scope"] is True
