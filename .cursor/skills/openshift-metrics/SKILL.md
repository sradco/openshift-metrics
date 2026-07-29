---
name: openshift-metrics
description: >-
  Query OpenShift metrics documentation and Telemetry (Telemeter) fleet
  data via the openshift-metrics MCP server. Use when asking what metrics
  exist, whether a metric is telemetered, or for CNV/fleet Telemeter stats.
---

# OpenShift Metrics / Telemetry

## When to use

- "Is metric X in Telemetry?"
- "What CNV metrics do we collect to Telemetry?"
- "How many external running VMs?"
- Per-account / per-cluster Telemeter questions

## Scope

`cnv.yaml` is an example fleet recipe pack (often virt metrics). Patterns
are reusable — copy/adapt or add `knowledge/recipes/<domain>.yaml`.

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
2. `is_telemetry_metric` / `list_telemetry_metrics` / `describe_metric`
3. `search_metrics` for general catalog (not all are Telemetry)
4. `query_telemeter` for ad-hoc PromQL (guardrailed — see below)
5. `telemeter_auth_status` if live queries fail

Telemeter calls reject blanket `=~".*"`, empty `{}`, and are rate-limited.
Prefer recipes. See `docs/KNOWN_LIMITATIONS.md`.

## Rules

- Do not claim Telemetry membership without allowlist confirmation
- Default scope is **external** customers
- Always show the PromQL used (`query_used` from tool results). Never
  answer with only a number or summary — include the query in the reply.
- Catalog tools work without credentials; live Telemeter needs
  `PROM_URL` / `CLIENTID` / `CLIENTSECRET` (no hardcoded Telemeter URL)
- Credentials: `#rhobs-support`. MCP bugs: repo OWNERS.
