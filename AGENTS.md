# Agent instructions — OpenShift Metrics / Telemetry MCP

This repository documents OpenShift Prometheus metrics and provides
an MCP server for catalog lookup and (optionally) live Telemeter queries.

## Scope

- This MCP is for **any Telemetry / Telemeter user**, not one product domain.
- `knowledge/recipes/fleet.yaml` — cross-domain fleet recipes (preferred
  starting point).
- Domain packs (`cnv.yaml`, `okd.yaml`, …) are **optional** examples.
  Join patterns are reusable; add `knowledge/recipes/<domain>.yaml` as needed.
- See `docs/KNOWN_LIMITATIONS.md`.

## Research budget (live Telemeter) — CRITICAL

Open-ended fleet research burns tokens and hits the rate limit
(default **30 queries / 600s**). Stay lean:

1. **Plan first** — list the 2–5 PromQL questions you need (cohort, measure,
   age, adverse effects, “is X observable?”). Do not discover by blasting.
2. **Catalog budget** — at most **2** of
   `is_telemetry_metric` / `describe_metric` / `list_telemetry_metrics`
   (use `list_telemetry_metrics` with a tight `query` and default slim
   output; set `detail=true` only when needed).
3. **Recipe list once** — one `list_recipes` with `topic=` / `pack=`
   (default listing omits long descriptions; `detail=true` if needed).
4. **Prefer `run_recipe`** — then `query_scoped_metric`, then raw
   `query_telemeter` only for joins recipes cannot express.
5. **Web search / docs fetch** — only after Telemetry cannot answer the
   premise (e.g. product docs for a TP that has no allowlisted signal).
6. **Rate limit** — live tools return `queries_remaining_in_window`. If it
   is low (<5) or you get `GUARDRAIL_VIOLATION` / `rate-limit`, **stop
   exploring and answer with what you have**.
7. **cursor-memory** — unrelated to this MCP. Do not create/load
   cursor-memory topics for one-shot Telemeter questions unless the user
   asks to save session notes.

Target for a typical “cohort + count + age + adverse effects” ask:
**~8–15 tool calls**, mostly `run_recipe`.

## Cohort → measure → effects playbook

For questions like “on clusters with X, how many Y, for how long, any pain?”:

1. **Observability** — `is_telemetry_metric` for the signal that defines X
   (if not telemetered, say so and pick the best proxy).
2. **Cohort recipe** — e.g. OKD via `okd_*` pack; subscribed fleet via
   `{scope_join}` recipes.
3. **Measure** — e.g. `okd_running_vms`, `total_running_vms`.
4. **Tenure** — e.g. `okd_median_cluster_age_days_with_vms` or
   `median_cluster_age_days_with_vms` (cluster age, not VM uptime).
5. **Adverse effects** — e.g. `okd_firing_alerts_with_vms`,
   `firing_alerts_on_clusters_with_vms`,
   `degraded_operators_on_clusters_with_vms`.
6. **Stop** — summarize with every `query_used`; do not keep probing.

OS major version (RHCOS/FCOS 9 vs 10): `mcd_host_os_and_version` is **not**
telemetered. `node_role_os_version_machine:cpu_capacity_cores:sum` only
exposes `label_node_openshift_io_os_id` (`rhcos`/`scos`/`fedora`/…).
Use recipe `worker_os_id_distribution` and state the limitation.

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

OKD recipes (`pack=okd`) intentionally **omit** OCM `{scope_join}` —
OKD clusters are usually outside subscribed external scope.

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
rate limits. Lean-research / guardrail tasks enforce low `maxToolCalls`.
