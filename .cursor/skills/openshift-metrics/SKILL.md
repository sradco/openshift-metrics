---
name: openshift-metrics
description: >-
  Query OpenShift metrics documentation and Telemetry (Telemeter) fleet
  data via the openshift-metrics MCP server. Use when asking what metrics
  exist, whether a metric is telemetered, or for fleet Telemeter stats
  (any domain — Virtualization/CNV and OKD are example packs).
---

# OpenShift Metrics / Telemetry

## When to use

- "Is metric X in Telemetry?"
- "What metrics do we collect to Telemetry?"
- Fleet Telemeter questions (subscribed clusters, capacity, installs, …)
- Per-account / per-cluster Telemeter questions
- Domain packs (CNV, OKD, …) when those recipes exist

## Scope

This MCP is for **all Telemetry users**, not one product.

- `knowledge/recipes/fleet.yaml` — cross-domain fleet recipes
- `knowledge/recipes/cnv.yaml`, `okd.yaml`, … — optional packs
- Add more packs as `knowledge/recipes/<domain>.yaml`
- Join patterns are reusable across domains

## Research budget (live asks)

Do **not** explore by dumping allowlists or issuing dozens of custom
`query_telemeter` calls. Default Telemeter rate limit is **30 / 600s**.

1. Plan 2–5 questions (cohort / measure / age / adverse / observable?).
2. ≤2 catalog tools (`is_telemetry_metric` preferred over broad lists).
3. One `list_recipes` with `topic=` or `pack=` (slim by default).
4. Prefer `run_recipe` → `query_scoped_metric` → raw `query_telemeter`.
5. Web/docs only if Telemetry cannot answer the premise.
6. Watch `queries_remaining_in_window`; if low or rate-limited, answer now.
7. Skip cursor-memory create/load unless the user asks to save notes.

Typical cohort research target: **~8–15 tool calls**.

## Cohort → measure → effects

1. Can Telemetry see X? (`is_telemetry_metric`)
2. Cohort recipe (e.g. `okd_clusters_count`)
3. Measure (e.g. `okd_running_vms` / `total_running_vms`)
4. Tenure (median cluster age recipes — not VM uptime)
5. Adverse effects (firing alerts / degraded operators recipes)
6. Stop; show every `query_used`

RHCOS/FCOS **9 vs 10** is **not** in Telemetry (`mcd_host_os_and_version`
not allowlisted). Use `worker_os_id_distribution` and state the gap.

## Learning about metrics

Use `search_metrics` / `describe_metric` for committed metric and label
descriptions. Catalogs are partial. The MCP does not auto-probe live
Telemeter labels; use `query_telemeter` only for explicit live queries.
`list_telemetry_metrics` defaults to slim rows and `limit=25`; pass
`detail=true` only when you need full allowlist text.

## Privacy

Never commit credentials, customer IDs, or query dumps.
Runtime filters (`ebs_account`, `email_domain`, `_id`) are OK in chat only.
Treat chat transcripts as sensitive — they retain Telemeter labels.

## Tool order

1. `list_recipes` / `run_recipe` for known fleet questions
   (pass `pack=` / `topic=` when many packs exist)
2. `query_scoped_metric` / `render_scoped_promql` when no recipe fits
   (allowlisted metric + `sum` | `count_clusters` | `sum_by` + scope;
   `sum_by` only for labels on the metric — not ebs_account)
3. `is_telemetry_metric` / `list_telemetry_metrics` / `describe_metric`
4. `search_metrics` for general catalog (not all are Telemetry)
5. `query_telemeter` for custom PromQL scoped tools cannot express
6. `telemeter_auth_status` if live queries fail

Telemeter calls reject blanket `=~".*"`, empty `{}`, and are rate-limited.
Prefer recipes, then scoped tools. See `docs/KNOWN_LIMITATIONS.md`.

## Rules

- Do not claim Telemetry membership without allowlist confirmation
- Default scope is **external** customers (`okd` pack omits OCM scope)
- Always show the PromQL used (`query_used` from tool results). Never
  answer with only a number or summary — include the query in the reply.
- Catalog tools work without credentials; live Telemeter needs
  `PROM_URL` / `CLIENTID` / `CLIENTSECRET` (no hardcoded Telemeter URL)
- Credentials: `#rhobs-support`. MCP bugs: repo OWNERS.
- Optional agent evals: `make run-mcpchecker-eval` (see `evals/mcpchecker/`)
