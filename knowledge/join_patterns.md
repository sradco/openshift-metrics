# Telemeter PromQL join patterns

Telemeter series are keyed by cluster id label `_id`. Fleet analysis
almost always joins usage metrics onto subscription / account metadata.

Follow [Prometheus binary operators / vector matching](https://prometheus.io/docs/prometheus/latest/querying/operators/):
use `on(_id)`, prefer set operators for filters, and `group_left` only when
copying labels or doing many-to-one matches.

Operator precedence: arithmetic (`*`, `+`) binds tighter than set operators
(`and`, `or`, `unless`). When combining a presence filter with a label join,
parenthesize explicitly:

```promql
(
  metric_name
    and on (_id) group by (_id) (id_version_ebs_account_internal:cluster_subscribed{internal=""})
)
  * on (_id) group_left(ebs_account, email_domain)
    group by (_id, ebs_account, email_domain) (ocm_subscription{})
```

## External vs internal customers

External (default for fleet stats):

```promql
id_version_ebs_account_internal:cluster_subscribed{internal=""}
```

Internal:

```promql
id_version_ebs_account_internal:cluster_subscribed{internal="true"}
```

All subscribed (external + internal) — recipe `scope=all`. This is **not**
“every series in Telemeter”; it is all subscribed clusters:

```promql
id_version_ebs_account_internal:cluster_subscribed
```

## Telemeter-native / enrichment metrics

Some series used in fleet joins are present in Telemeter but are **not** in
the CMO customer allowlist (they are platform/OCM enrichment). Examples:

- `id_version_ebs_account_internal:cluster_subscribed`
- `ocm_subscription`
- `id_primary_host_type`

`is_telemetry_metric` may return false for these even though recipes query
them successfully. Treat allowlist checks as answering “is this a
customer-facing telemetered product metric?”, not “does this label exist
in RHOBS?”.

## Filter by presence (preferred)

To keep left-hand series only when a matching `_id` exists on the right,
use the set operator `and`. Aggregate the right side with `group by (_id)`
so matching is one series per cluster (avoids many-to-many errors):

```promql
metric_name
  and on (_id)
    group by (_id) (id_version_ebs_account_internal:cluster_subscribed{internal=""})
```

Do **not** invent dummy labels like `group_left(_blah)` for presence
filters. Empty `group_left()` is only needed for many-to-one arithmetic
joins, not for `and`/`or`/`unless`.

For allowlisted metrics without a named recipe, MCP tools
`render_scoped_promql` / `query_scoped_metric` apply these joins for
`sum`, `count_clusters`, and `sum_by` aggregations.

## Attach labels (preferred)

Info-style join: multiply by a right-hand vector that is **1 per match**
(`group` always yields 1), and list the labels to copy in `group_left`:

```promql
metric_name
  * on (_id) group_left(ebs_account, email_domain)
    group by (_id, ebs_account, email_domain) (ocm_subscription{})
```

If `ocm_subscription` can have multiple series per `_id`, keep one before
joining (still producing a safe multiplier of 1 via `group`):

```promql
metric_name
  * on (_id) group_left(ebs_account, email_domain)
    group by (_id, ebs_account, email_domain) (
      topk by (_id) (1, ocm_subscription{})
    )
```

## Legacy Telemeter idiom (still valid)

Older CNV Telemeter reports often use `+` with `0 *` so the right-hand
value cannot change the left-hand sample, plus a dummy
`group_left(_blah)` when no labels are copied:

```promql
metric_name
  + on (_id) group_left(_blah)
    (0 * group by (_id) (id_version_ebs_account_internal:cluster_subscribed{internal=""}))
```

This is **correct** and widely deployed, but prefer `and on (_id)` /
`* on (_id) group_left(...)` in new recipes. MCP recipe helpers use the
preferred forms.

## Runtime account / domain / cluster filters

Parameters only — never hardcode real customer identifiers in git:

```promql
metric_name
  and on (_id) group by (_id) (ocm_subscription{ebs_account="ACCOUNT"})
```

```promql
metric_name
  and on (_id) group by (_id) (ocm_subscription{email_domain="DOMAIN"})
```

```promql
metric_name
  and on (_id) group by (_id) (
    id_version_ebs_account_internal:cluster_subscribed{_id="CLUSTER_ID"}
  )
```

## CNV installed

```promql
csv_succeeded{name=~".*hyperconverged.*"}
```

## Running VMs

```promql
cnv:vmi_status_running:count
```

Prefer named recipes in `knowledge/recipes/cnv.yaml` over hand-rolling
these joins.

## OKD cohort

Identify OKD via the version label (not OCM subscription):

```promql
cluster_version{type="current",version=~".*-okd-.*"}
```

Prefer `knowledge/recipes/okd.yaml` (`okd_running_vms`,
`okd_clusters_with_running_vms`, `okd_firing_alerts_with_vms`, …).
Those recipes **omit** `{scope_join}` because OKD is usually outside
subscribed external/internal scope.

## Host OS family vs OS major version

Telemeter exposes node OS **family** on:

```promql
node_role_os_version_machine:cpu_capacity_cores:sum
```

via `label_node_openshift_io_os_id` (`rhcos`, `scos`, `fedora`, `rhel`,
`centos`, …). Recipe: `worker_os_id_distribution`.

`mcd_host_os_and_version` (RHCOS/FCOS version string) is **not** on the
CMO Telemetry allowlist — Telemeter cannot distinguish RHCOS/FCOS 9 vs
10. Say so instead of inventing proxies beyond TechPreview feature-set
heuristics (weak; not a recipe).

## Cluster age (not VM uptime)

```promql
time() - cluster_version{type="cluster"}
```

Value is unix age of the cluster version object. Recipes:
`median_cluster_age_days_with_vms`,
`okd_median_cluster_age_days_with_vms`.

## Adverse effects (alerts / degraded operators)

Prefer recipes over ad-hoc joins:

- `firing_alerts_on_clusters_with_vms` / `okd_firing_alerts_with_vms`
- `degraded_operators_on_clusters_with_vms`

Use `alerts{alertstate="firing",severity=~"critical|warning"}` (allowlisted
severities) — never blanket `alertname=~".*"`. RHOBS Telemeter exposes the
series as lowercase `alerts` (with `_id`); the CMO allowlist still lists
the upstream name `ALERTS`. Do not query uppercase `ALERTS` for fleet
joins — that only hits a few platform test series without `_id`.

## Other packs (dashboard harvest)

| Pack | Source | Notes |
|------|--------|-------|
| `knowledge/recipes/coo.yaml` | `rhobs/observability-operator` `/dashboards` | CSV install / failure / channel |
| `knowledge/recipes/ocp-builds.yaml` | `redhat-openshift-builds/telemetry` `/dashboards` | `openshift:build_by_strategy:sum` |
| `knowledge/recipes/rhacs.yaml` | app-interface RHACS telemeter ConfigMap | Central / Sensor / secured counts |
| `knowledge/recipes/cnv.yaml` | also [`rhobs/monitoring`](https://github.com/rhobs/monitoring/tree/main/resources/dashboards) CNV overview | virt fleet; many panels already covered |

### `rhobs/monitoring` triage

High value for **fleet recipes**: `grafana-dashboard-cnv-overview`,
`…-cnv-alerts-overview`, `…-cnv-single-alert-overview`.

Low value for this MCP (RHOBS **platform** SLIs / in-cluster ops):
`telemeter`, `thanos-*`, `loki-*`, `observatorium-api`,
`rhobs-metrics-collection`, `rosa-observability-meta-monitoring`.

These dashboards answer “is the RHOBS/Observatorium stack healthy?”
(upload latency, Thanos store memory, Loki chunk rates, API 5xx). They
query **platform** metrics (`thanos_*`, `loki_*`, `haproxy_*`,
`job="telemeter-server"`, …), not customer-cluster Telemetry allowlist
series. This MCP’s recipes target fleet questions over telemetered
product metrics (`cnv:*`, `csv_*`, `openshift:build_*`, …) joined on
`_id` / subscription scope — different audience and datasource shape.

Per-cluster SRE views (`sbr-*-by-cluster-id`) need `$cluster_id` — use
recipe `cluster_id` filter, not new fleet-wide recipes.

Grafana dashboards often inject `$version`, `$source`, `$build` vars —
strip those and use recipe `scope` / filters instead. Prefer
`{subscribed_selector}` for utilization denominators over raw
`cluster_version` (builds dashboard pattern).

## `group_right` (product → cluster metadata)

RHACS panels attach subscribed / version labels onto product series with
`group_right` (many Centrals/Sensors → one cluster metadata series):

```promql
max by (_id) (rhacs:telemetry:rox_sensor_info)
  * on (_id) group_right
    id_version_ebs_account_internal:cluster_subscribed
```

For MCP recipes we usually keep the **left** vector as the product metric
and filter with `{scope_join}` (`and on (_id)`), then copy account labels
with `* on (_id) group_left(...)` + `ocm_subscription` (same as CNV).

## Label-only arithmetic with `0 *`

When multiplying/adding only to copy labels (and keep the left sample),
dashboards use `0 * right_hand`:

```promql
metric
  + on (_id) group_right
    0 * id_version_ebs_account_internal:cluster_subscribed
```

Prefer `and` / `* … group_left` in new recipes; keep this form when
matching an existing dashboard exactly.

## Skipped / caution from harvest

- Fleet firing alerts: query lowercase `alerts` on RHOBS Telemeter (not
  CMO allowlist name `ALERTS`). COO panel
  `alerts{namespace="openshift-observability-operator"}` is a different
  in-cluster series — do not confuse with telemetered fleet `alerts`.
- RHACS `ebs_account_account_type_email_domain_internal` — enrichment
  metric used in Grafana; recipes use `ocm_subscription` instead.
- Dense per-`_id` tables (`Builds by Cluster`) — prefer account rollups
  or require filters / low `max_series`.
