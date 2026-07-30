# Known limitations

Honest status for adopters. Update this when limitations are fixed.

## Scope of recipes

- This MCP is for **any Telemetry user**, not one product domain.
- `knowledge/recipes/fleet.yaml` — cross-domain fleet recipes (subscribed
  clusters, capacity, …).
- Domain packs (`cnv.yaml`, `coo.yaml`, …) are **optional** examples.
  Join patterns (`{scope_join}`, `{subscribed_selector}`, `{filters}`,
  account rollups) are reusable for any Telemetry metric; add
  `knowledge/recipes/<domain>.yaml` as needed.
- Recipe `scope`: `external` (default), `internal`, or `all` (all
  **subscribed** clusters — external+internal). `all` is not unfiltered
  Telemeter.
- Some recipe join metrics (`ocm_subscription`, `cluster_subscribed`,
  `id_primary_host_type`) are Telemeter/OCM enrichment series and may not
  appear in the CMO allowlist; see `knowledge/join_patterns.md`.
- For allowlisted metrics **without** a named recipe, use
  `render_scoped_promql` / `query_scoped_metric` (`sum`, `count_clusters`,
  or `sum_by` + scope/filters). Prefer `run_recipe` when a pack already
  answers the question. Use raw `query_telemeter` only for custom PromQL.
  `sum_by` only groups labels present on the metric (not `ebs_account` /
  `email_domain`). `label_equals` values must be plain (no quotes/commas).
  Leave `require_telemetry=true` unless querying known enrichment metrics.
## Catalogs

- `docs/telemetry/allowlist.yaml` is a synced snapshot of CMO (kept fresh
  via `sync_telemetry_allowlist.py --check` in CI).
- `docs/prometheus_metrics/` is a **partial, historical** general catalog
  (metric + label descriptions). Agents use it via `search_metrics` /
  `describe_metric` when docs exist. It is not complete and is not
  required for Telemeter queries. Refreshing it requires an explicit
  `--prometheus-url` / `PROMETHEUS_URL` (no embedded cluster URL).
- The MCP does **not** autonomously scrape Telemeter to invent metrics or
  walk live label sets. An agent *may* manually `query_telemeter` (e.g.
  `count by (__name__) (...)` or a series query) after catalog lookup;
  that is explicit PromQL, not automatic discovery.

## Privacy

- Telemeter series can include `ebs_account`, `email_domain`, and cluster
  `_id`. Cursor/Claude **chat transcripts retain tool results**.
- Do not paste results into public Slack/Jira/GitHub. Do not commit dumps.
- Private GitHub does not make query results safe to share broadly.

## Access

- `rhobs/openshift-metrics` is a **private** org repository. You need
  GitHub access to clone, plus a RHOBS Telemeter service account and
  `PROM_URL` (Telemeter API base — from `#rhobs-support`, not committed
  to git) for live queries.

## Testing

- CI runs offline unit tests and allowlist `--check` against live CMO.
- There is no automated Telemeter e2e in CI (credentials). Run
  `scripts/smoke_test_mcp.py` manually before relying on live queries.
- Optional **mcpchecker** agent evals live under `evals/mcpchecker/`
  (catalog tasks need no Telemeter; live suite needs creds). See that
  directory’s README. These are not obs-mcp task copies — different tools
  and backend.

## Runtime

- Results are truncated (`max_series`, default 50).
- Prefer `run_recipe`, then `query_scoped_metric`, over unconstrained
  `query_telemeter` for fleet asks.
- `list_recipes` / `list_telemetry_metrics` default to **slim** listings
  (`detail=false`; telemetry list `limit=25`) to save agent tokens.
- Live Telemeter tool responses include `queries_remaining_in_window`
  (rate-limit headroom). Agents should stop exploring when it is low.
- **PromQL guardrails** (adapted from
  [rhobs/obs-mcp](https://github.com/rhobs/obs-mcp)) run before every
  Telemeter query:
  - `disallow-blanket-regex` — reject `=~".*"` / `=~".+"` (exact)
  - `disallow-unrestricted-selectors` — reject bare `up` / `{...}` without
    a metric name
  - `rate-limit` — max queries per window
    (`TELEMETER_GUARDRAIL_MAX_QUERIES`, default 30 / 600s)
  - `max-range-hours` — range lookback cap (default 48h)
  - `require-non-name-matcher` — **off by default** (obs-mcp enables
    `require-label-matcher`; fleet `sum(metric)` recipes would fail)
  - Cardinality TSDB API checks from obs-mcp are **not** available on
    RHOBS Telemeter
  - Configure via `TELEMETER_GUARDRAILS` (see `.env.example`)

## Observability gaps (common agent traps)

- Host OS **major** version (RHCOS/FCOS 9 vs 10):
  `mcd_host_os_and_version` is **not** telemetered. Only OS **family**
  via `label_node_openshift_io_os_id` on
  `node_role_os_version_machine:cpu_capacity_cores:sum`
  (recipe `worker_os_id_distribution`).
- OKD cohorts use `cluster_version{version=~".*-okd-.*"}` and the `okd`
  recipe pack (no OCM `{scope_join}`).
- Cluster age recipes use `cluster_version{type="cluster"}` — that is
  cluster object age, not VM uptime.
