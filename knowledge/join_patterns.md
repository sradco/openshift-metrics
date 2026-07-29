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
