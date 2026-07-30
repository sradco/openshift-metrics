# Agent instructions — OpenShift Metrics / Telemetry MCP

This repository documents OpenShift Prometheus metrics and provides
an MCP server for catalog lookup and (optionally) live Telemeter queries.

## Scope

- This MCP is for **any Telemetry / Telemeter user**, not one product domain.
- `knowledge/recipes/fleet.yaml` — cross-domain fleet recipes (preferred
  starting point).
- `knowledge/recipes/cnv.yaml` is an **optional example pack** (many
  metrics are Virtualization-related). Join patterns are reusable; other
  teams can copy recipes or add `knowledge/recipes/<domain>.yaml`.
- See `docs/KNOWN_LIMITATIONS.md`.

## Learning about metrics

- Prefer `search_metrics` / `describe_metric` / allowlist tools — these read
  committed YAML descriptions (including label descriptions when present).
- Catalogs are **partial**. Absence from the general catalog does not mean
  the metric does not exist.
- Do **not** assume the MCP auto-discovers live series or label values.
  Only run `query_telemeter` when the user needs live fleet data, after
  checking allowlist membership when claiming Telemetry.

## Privacy

- Never commit credentials, tokens, or customer identifiers
  (`ebs_account`, `email_domain`, cluster `_id`).
- Never commit CSV/HTML dumps or query result samples.
- Per-account / per-cluster filters are runtime parameters only.
- Do not write tool results into the git tree.
- **Chat transcripts retain tool output** — treat Telemeter sessions as
  sensitive; do not paste customer identifiers into public channels.

## Two catalogs (do not confuse them)

1. **General metrics** — `docs/prometheus_metrics/`
   Partial/historical. Not all are sent to Telemetry. Optional for
   Telemeter questions.
2. **Telemetry allowlist** — `docs/telemetry/allowlist.yaml`
   Canonical list of what Telemeter forwards (from CMO).

Only treat a metric as Telemetry if the allowlist (or
`is_telemetry_metric`) says so.

## Tool preference order

1. `list_recipes` / `run_recipe` for known fleet questions (named packs).
   Use `pack=` / `topic=` to narrow when many packs are present.
2. `query_scoped_metric` / `render_scoped_promql` for an allowlisted metric
   when no recipe fits (`sum` / `count_clusters` / `sum_by` + scope/filters).
   `sum_by` only groups labels on the metric (not account enrichment labels).
3. `is_telemetry_metric` / `list_telemetry_metrics` / `describe_metric`
   for “what do we collect?” / metric+label docs.
4. `search_metrics` for general OpenShift metric metadata.
5. `query_telemeter` for custom PromQL that scoped tools cannot express.

Always show the PromQL used (`query_used` from tool results).
Never answer Telemeter questions with only a number — include the query.
Default fleet scope is **external** customers unless the user asks otherwise.
`scope=all` means all **subscribed** clusters (external+internal), not
unfiltered Telemeter series.

Telemeter queries are **guardrailed** (blanket regex, unrestricted
selectors, rate limits) so agents cannot blast the API. Prefer recipes,
then scoped metric tools. Do not craft `=~".*"` / empty `{}` selectors.
See `docs/KNOWN_LIMITATIONS.md`.

## Auth

Live Telemeter tools need `PROM_URL`, `CLIENTID`, and `CLIENTSECRET`
in the environment (no hardcoded Telemeter API URL in the repo).
Catalog tools work without credentials.
On auth failure, suggest `telemeter_auth_status` and `#rhobs-support`
for credentials; MCP bugs go to repo OWNERS (not that channel).

## Agent evals

Optional mcpchecker suite: `evals/mcpchecker/` (`make run-mcpchecker-eval`).
Catalog tasks are offline; Telemeter tasks need credentials and respect
rate limits.
