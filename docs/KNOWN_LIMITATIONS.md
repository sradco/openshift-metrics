# Known limitations

Honest status for adopters. Update this when limitations are fixed.

## Scope of recipes

- `knowledge/recipes/cnv.yaml` is an **example fleet recipe pack**, seeded
  with OpenShift Virtualization / CNV metrics. The join patterns
  (`{scope_join}`, `{subscribed_selector}`, `{filters}`, account rollups)
  are reusable for any Telemetry metric.
- Recipe `scope`: `external` (default), `internal`, or `all` (all
  **subscribed** clusters — external+internal). `all` is not unfiltered
  Telemeter.
- Some recipe join metrics (`ocm_subscription`, `cluster_subscribed`,
  `id_primary_host_type`) are Telemeter/OCM enrichment series and may not
  appear in the CMO allowlist; see `knowledge/join_patterns.md`.

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

## Runtime

- Results are truncated (`max_series`, default 50).
- Prefer `run_recipe` over unconstrained `query_telemeter` for fleet asks.
- **PromQL guardrails** (adapted from
  [rhobs/obs-mcp](https://github.com/rhobs/obs-mcp)) run before every
  Telemeter query:
  - `disallow-blanket-regex` — reject `=~".*"` / `=~".+"` (exact)
  - `disallow-unrestricted-selectors` — reject bare `up` / `{...}` without
    a metric name
  - `rate-limit` — max queries per window
    (`TELEMETER_GUARDRAIL_MAX_QUERIES`, default 30 / 600s)
  - `require-non-name-matcher` — **off by default** (obs-mcp enables
    `require-label-matcher`; fleet `sum(metric)` recipes would fail)
  - Cardinality TSDB API checks from obs-mcp are **not** available on
    RHOBS Telemeter
  - Configure via `TELEMETER_GUARDRAILS` (see `.env.example`)
