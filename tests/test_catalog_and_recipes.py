"""Unit tests for catalog + recipe rendering (no network / no credentials)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from mcp_server.catalog import (  # noqa: E402
    clear_catalog_caches,
    describe_metric,
    is_telemetry_metric,
    list_telemetry_metrics,
)
from mcp_server.recipes import (  # noqa: E402
    clear_recipe_cache,
    list_recipes,
    query_scoped_metric,
    render_recipe_promql,
    render_scoped_promql,
    run_recipe,
)
from mcp_server.server import _ensure_query_used, _with_rate_status  # noqa: E402

clear_catalog_caches()
clear_recipe_cache()


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
    # Slim default: no owners key
    assert "owners" not in hits[0]


def test_list_telemetry_metrics_detail():
    slim = list_telemetry_metrics(query="cluster_version", limit=5, detail=False)
    full = list_telemetry_metrics(query="cluster_version", limit=5, detail=True)
    assert slim and full
    assert "owners" not in slim[0] or slim[0].get("owners") is None
    # Detail rows keep full allowlist fields when present on the entry.
    assert any("description" in row for row in full)


def test_describe_metric_telemetry_flag():
    desc = describe_metric("cnv:vmi_status_running:count")
    assert desc["in_telemetry"] is True
    assert desc.get("telemetry")


def test_list_cnv_recipes():
    recipes = list_recipes(topic="cnv")
    ids = {r["id"] for r in recipes}
    assert "total_running_vms" in ids
    assert "clusters_with_cnv_installed" in ids
    assert "cnv_clusters_by_minor_version" in ids
    assert "cnv_clusters_with_additional_network" in ids
    assert "running_vms_by_guest_os" in ids
    assert "cnv_abnormal_by_reason" in ids


def test_list_fleet_recipes():
    recipes = list_recipes(topic="fleet")
    ids = {r["id"] for r in recipes}
    assert "subscribed_clusters_count" in ids
    assert "total_cpu_capacity_cores" in ids
    assert "total_memory_capacity_bytes" in ids
    assert "median_cluster_age_days_with_vms" in ids
    assert "firing_alerts_on_clusters_with_vms" in ids
    assert "degraded_operators_on_clusters_with_vms" in ids
    assert "worker_os_id_distribution" in ids
    # Slim default omits description
    assert "description" not in recipes[0]


def test_list_recipes_detail_includes_description():
    recipes = list_recipes(topic="fleet", detail=True)
    assert recipes
    assert recipes[0].get("description")


def test_list_okd_recipes():
    recipes = list_recipes(pack="okd")
    ids = {r["id"] for r in recipes}
    assert "okd_running_vms" in ids
    assert "okd_clusters_with_running_vms" in ids
    assert "okd_firing_alerts_with_vms" in ids
    assert "okd_median_cluster_age_days_with_vms" in ids
    assert all(r["supports_scope"] is False for r in recipes)


def test_render_fleet_subscribed_clusters():
    rendered = render_recipe_promql("subscribed_clusters_count", scope="external")
    promql = rendered["promql"]
    assert "id_version_ebs_account_internal:cluster_subscribed" in promql
    assert 'internal=""' in promql


def test_render_okd_running_vms_omits_subscribed_join():
    rendered = render_recipe_promql("okd_running_vms", scope="external")
    promql = rendered["promql"]
    assert "cnv:vmi_status_running:count" in promql
    assert 'version=~".*-okd-.*"' in promql
    assert "cluster_subscribed" not in promql
    assert rendered["supports_scope"] is False


def test_render_okd_vms_by_minor():
    promql = render_recipe_promql("okd_running_vms_by_minor")["promql"]
    assert "label_replace" in promql
    assert "minor" in promql
    assert 'version=~".*-okd-.*"' in promql


def test_render_worker_os_id_and_adverse_recipes():
    os_q = render_recipe_promql("worker_os_id_distribution", scope="external")["promql"]
    assert "label_node_openshift_io_os_id" in os_q
    assert 'label_node_role_kubernetes_io_master=""' in os_q
    assert "and on (_id)" in os_q

    alerts = render_recipe_promql(
        "firing_alerts_on_clusters_with_vms", scope="external"
    )["promql"]
    assert 'alerts{alertstate="firing"' in alerts
    assert "cnv:vmi_status_running:count" in alerts
    assert "ALERTS{" not in alerts


def test_with_rate_status_attaches_remaining():
    payload = _with_rate_status({"ok": True})
    assert "queries_remaining_in_window" in payload
    assert "rate_limit" in payload


def test_allowlist_contains_platform_metric():
    assert is_telemetry_metric("cluster:capacity_cpu_cores:sum")["in_telemetry"] is True


def test_alerts_telemeter_query_name_alias():
    """CMO allowlist says ALERTS; RHOBS Telemeter series is lowercase alerts."""
    assert is_telemetry_metric("ALERTS")["in_telemetry"] is True
    assert is_telemetry_metric("alerts")["in_telemetry"] is True
    alerts_entry = is_telemetry_metric("alerts")["allowlist_entry"]
    assert alerts_entry.get("telemeter_query_name") == "alerts"
    assert alerts_entry.get("allowlist_metric_name") == "ALERTS"

    desc = describe_metric("ALERTS")
    assert desc["in_telemetry"] is True
    assert desc.get("telemeter_query_name") == "alerts"

    rendered = render_scoped_promql("ALERTS", aggregation="sum", scope="external")
    assert rendered["telemeter_query_name"] == "alerts"
    assert "sum(alerts" in rendered["promql"]
    assert "ALERTS{" not in rendered["promql"]

    okd = render_recipe_promql("okd_firing_alerts_with_vms")["promql"]
    assert 'alerts{alertstate="firing"' in okd
    assert "ALERTS{" not in okd


def test_render_cnv_minor_version_recipe():
    rendered = render_recipe_promql("cnv_clusters_by_minor_version", scope="external")
    promql = rendered["promql"]
    assert "label_replace" in promql
    assert "major_minor_version" in promql
    assert "hyperconverged" in promql
    assert "and on (_id)" in promql


def test_list_harvested_recipe_packs():
    coo = {r["id"] for r in list_recipes(topic="coo")}
    builds = {r["id"] for r in list_recipes(topic="builds")}
    rhacs = {r["id"] for r in list_recipes(topic="rhacs")}
    assert "clusters_with_coo_installed" in coo
    assert "clusters_with_openshift_builds" in builds
    assert "rhacs_central_instances" in rhacs


def test_render_coo_recipe_includes_scope_join():
    rendered = render_recipe_promql("clusters_with_coo_installed", scope="external")
    promql = rendered["promql"]
    assert "cluster-observability-operator" in promql
    assert "and on (_id)" in promql
    assert 'internal=""' in promql


def test_render_builds_utilization_uses_subscribed_selector():
    rendered = render_recipe_promql(
        "openshift_builds_cluster_utilization",
        scope="all",
    )
    promql = rendered["promql"]
    assert "openshift:build_by_strategy:sum" in promql
    assert "id_version_ebs_account_internal:cluster_subscribed" in promql
    assert "cluster_version" not in promql


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


def test_render_scoped_promql_sum():
    rendered = render_scoped_promql(
        "cnv:vmi_status_running:count",
        aggregation="sum",
        scope="external",
        ebs_account="EXAMPLE_ONLY",
    )
    promql = rendered["promql"]
    assert promql.startswith("sum(")
    assert "cnv:vmi_status_running:count" in promql
    assert "and on (_id)" in promql
    assert 'internal=""' in promql
    assert 'ebs_account="EXAMPLE_ONLY"' in promql
    assert rendered["in_telemetry"] is True


def test_render_scoped_promql_count_clusters_and_sum_by():
    count_q = render_scoped_promql(
        "openshift:build_by_strategy:sum",
        aggregation="count_clusters",
        scope="all",
    )["promql"]
    assert count_q.startswith("count(group by (_id)")
    assert "openshift:build_by_strategy:sum" in count_q
    assert "cluster_subscribed" in count_q
    assert 'internal=""' not in count_q

    by_q = render_scoped_promql(
        "openshift:build_by_strategy:sum",
        aggregation="sum_by",
        by="strategy",
        scope="external",
    )["promql"]
    assert "sum by (strategy)" in by_q
    assert by_q.startswith("sort_desc(")


def test_render_scoped_promql_label_equals_and_rejects():
    with_labels = render_scoped_promql(
        "cluster:usage:resources:sum",
        aggregation="sum",
        label_equals="resource=virtualmachines.kubevirt.io",
        scope="external",
    )["promql"]
    assert 'cluster:usage:resources:sum{resource="virtualmachines.kubevirt.io"}' in (
        with_labels
    )

    try:
        render_scoped_promql("not_a_real_metric_zzz", aggregation="sum")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "allowlist" in str(exc).lower()

    try:
        render_scoped_promql(
            "cnv:vmi_status_running:count",
            aggregation="sum_by",
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "by=" in str(exc)

    try:
        render_scoped_promql("metric;drop", aggregation="sum", require_telemetry=False)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "identifier" in str(exc).lower()

    # Quote/comma injection must be rejected (not parsed into extra matchers).
    try:
        render_scoped_promql(
            "cnv:vmi_status_running:count",
            label_equals='os=rhel9",job="x',
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "quote" in str(exc).lower()

    try:
        render_scoped_promql(
            "cnv:vmi_status_running:count",
            aggregation="sum_by",
            by="ebs_account",
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "ebs_account" in str(exc)
        assert "ocm_subscription" in str(exc) or "enrichment" in str(exc).lower()


def test_list_recipes_pack_filter():
    fleet = list_recipes(pack="fleet")
    assert fleet
    assert all(r["pack"] == "fleet" for r in fleet)
    assert {r["id"] for r in fleet} >= {"subscribed_clusters_count"}


def test_query_scoped_metric_includes_query_used(monkeypatch):
    def fake_instant(query, max_series=50):
        return {
            "query": query,
            "mode": "instant",
            "series_returned": 0,
            "data": [],
        }

    monkeypatch.setattr("mcp_server.telemeter_client.query_instant", fake_instant)
    result = query_scoped_metric(
        "cnv:vmi_status_running:count",
        aggregation="sum",
        scope="external",
    )
    assert result["query_used"] == result["promql"]
    assert "cnv:vmi_status_running:count" in result["query_used"]
    assert "result" in result


def test_run_recipe_range_passes_step(monkeypatch):
    seen: dict[str, object] = {}

    def fake_range(query, hours=3.0, step="1h", max_series=50):
        seen["step"] = step
        seen["query"] = query
        return {"query": query, "mode": "range", "data": []}

    monkeypatch.setattr("mcp_server.telemeter_client.query_range", fake_range)
    result = run_recipe(
        "total_running_vms",
        scope="external",
        mode="range",
        step="15m",
        hours=1.0,
    )
    assert seen["step"] == "15m"
    assert "cnv:vmi_status_running:count" in result["query_used"]


def test_query_scoped_metric_range_passes_step(monkeypatch):
    seen: dict[str, object] = {}

    def fake_range(query, hours=3.0, step="1h", max_series=50):
        seen["step"] = step
        seen["query"] = query
        return {"query": query, "mode": "range", "data": []}

    monkeypatch.setattr("mcp_server.telemeter_client.query_range", fake_range)
    result = query_scoped_metric(
        "cnv:vmi_status_running:count",
        aggregation="sum",
        mode="range",
        step="15m",
        hours=1.0,
    )
    assert seen["step"] == "15m"
    assert "cnv:vmi_status_running:count" in result["query_used"]
