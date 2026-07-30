---
name: openshift-metrics
description: >-
  Query OpenShift metrics documentation and Telemetry (Telemeter) fleet
  data via the openshift-metrics MCP server. Use when asking what metrics
  exist, whether a metric is telemetered, or for fleet Telemeter stats
  (any domain — Virtualization/CNV is one example pack).
---

# OpenShift Metrics / Telemetry

## When to use

- "Is metric X in Telemetry?"
- "What metrics do we collect to Telemetry?"
- Fleet Telemeter questions (subscribed clusters, capacity, installs, …)
- Per-account / per-cluster Telemeter questions
- Domain packs (e.g. CNV) when those recipes exist

## Scope

This MCP is for **all Telemetry users**, not one product.

- `knowledge/recipes/fleet.yaml` — cross-domain fleet recipes
- `knowledge/recipes/cnv.yaml` — optional example pack (virt-seeded)
- Add more packs as `knowledge/recipes/<domain>.yaml`
- Join patterns are reusable across domains

## Learning about metrics

Use `search_metrics` / `describe_metric` for committed metric and label
descriptions. Catalogs are partial. The MCP does not auto-probe live
Telemeter labels; use `query_telemeter` only for explicit live queries.

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
- Default scope is **external** customers
- Always show the PromQL used (`query_used` from tool results). Never
  answer with only a number or summary — include the query in the reply.
- Catalog tools work without credentials; live Telemeter needs
  `PROM_URL` / `CLIENTID` / `CLIENTSECRET` (no hardcoded Telemeter URL)
- Credentials: `#rhobs-support`. MCP bugs: repo OWNERS.
- Optional agent evals: `make run-mcpchecker-eval` (see `evals/mcpchecker/`)
