# OpenShift Metrics

Centralized documentation for OpenShift Prometheus metrics, plus an MCP
server for catalog lookup and optional live **Telemetry (Telemeter)** queries
from Cursor or Claude Code.

**Home:** [rhobs/openshift-metrics](https://github.com/rhobs/openshift-metrics)
(**private** RHOBS org repo — request GitHub access if you cannot clone).

**Honest scope:** This MCP is for **any Telemetry user**. Cross-domain
fleet recipes live in `knowledge/recipes/fleet.yaml`.
`knowledge/recipes/cnv.yaml` is an **optional example pack** (Virtualization
metrics). Join patterns are reusable — copy, swap the metric, or add
`knowledge/recipes/<domain>.yaml`. See
[docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Before you start

1. GitHub access to `rhobs/openshift-metrics` (private).
2. Python 3.10+.
3. For live Telemeter: `PROM_URL` plus RHOBS SA (`CLIENTID` / `CLIENTSECRET`)
   via Slack [#rhobs-support](https://redhat.enterprise.slack.com/archives/C052XEAU63E)
   (credentials only — MCP/recipe bugs → [OWNERS](OWNERS)).

## Two catalogs (important)

| Catalog | Path | Meaning |
|---------|------|---------|
| General metrics | `docs/prometheus_metrics/` | Partial/historical cluster metrics. **Not all are telemetered.** Optional for MCP Telemeter use. |
| Telemetry allowlist | `docs/telemetry/allowlist.yaml` | What Telemeter forwards (from [CMO](https://github.com/openshift/cluster-monitoring-operator/blob/main/Documentation/data-collection.md)). |

## Privacy and data handling

This repo may be private on GitHub, but **Telemeter results are still
customer-sensitive**.

**Never commit:**

- `CLIENTID` / `CLIENTSECRET` / tokens
- Real `ebs_account`, `email_domain`, or cluster `_id` values
- CSV/HTML reports or query result dumps

**Also never** paste those into public Slack, Jira, or GitHub. Cursor/Claude
**chat transcripts retain tool output** — treat chats that ran Telemeter
queries as sensitive.

Use `.env` locally (gitignored). See `.env.example`.

## Features

- General Prometheus metrics metadata (YAML, partial)
- Telemetry allowlist sync from CMO (+ CI drift check)
- Fleet PromQL recipes (`knowledge/recipes/fleet.yaml` + optional domain packs)
- MCP server for Cursor / Claude Code
- Optional script to refresh general metrics from a cluster Prometheus

## Installation

```bash
git clone https://github.com/rhobs/openshift-metrics.git
cd openshift-metrics
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill CLIENTID/CLIENTSECRET for live queries
```

For development tests: `pip install -r requirements-dev.txt`.

## Sync Telemetry allowlist

The committed `docs/telemetry/allowlist.yaml` is a normalized snapshot of
the CMO telemeter ConfigMap (not a git submodule). Refresh it when CMO
changes:

```bash
python src/sync_telemetry_allowlist.py
# or from a local CMO manifest:
python src/sync_telemetry_allowlist.py --source-file /path/to/config.yaml
```

Detect drift without writing (also run in CI):

```bash
python src/sync_telemetry_allowlist.py --check
```

If `--check` fails, re-run the sync command and commit the updated
`docs/telemetry/allowlist.yaml`.

## MCP server (Cursor / Claude Code) — easy setup

Other users only need **three steps**:

### 1. Clone and credentials

```bash
git clone https://github.com/rhobs/openshift-metrics.git
cd openshift-metrics

# Option A (repo-local, gitignored):
umask 077
cat > .env <<'EOF'
PROM_URL=https://YOUR-TELEMETER-API-BASE/
CLIENTID=your-client-id
CLIENTSECRET=your-client-secret
EOF

# Option B (shared machine / no secrets in checkout):
mkdir -p ~/.config/openshift-metrics
umask 077
cat > ~/.config/openshift-metrics/env <<'EOF'
PROM_URL=https://YOUR-TELEMETER-API-BASE/
CLIENTID=your-client-id
CLIENTSECRET=your-client-secret
EOF
```

Catalog tools work without credentials. Live Telemeter needs `PROM_URL`
(ask `#rhobs-support`) plus the SA credentials. Do not commit real API
endpoints. Precedence in `run_mcp.sh`: already-exported env >
repo `.env` > `~/.config/openshift-metrics/env`.

### 2. Point Cursor / Claude Code at the launcher

Copy `mcp.json.example` into your Cursor MCP config (user or project) and
replace the path:

```json
{
  "mcpServers": {
    "openshift-metrics": {
      "command": "/ABS/PATH/TO/openshift-metrics/scripts/run_mcp.sh"
    }
  }
}
```

`scripts/run_mcp.sh` handles venv creation, dependency refresh when
`requirements.txt` changes, `PYTHONPATH`, and loading `.env` /
`~/.config/openshift-metrics/env`. No secrets in JSON.

### 3. Restart MCP and ask

Reload Cursor MCP (or the window), then ask e.g. “How many external running
VMs?” or “Is `cnv:vmi_status_running:count` in Telemetry?”

### Updating to the latest MCP

Cursor does not pull this repo for you. Your MCP config only points at a
local checkout. To get server, recipe, allowlist, and instruction updates:

```bash
cd /ABS/PATH/TO/openshift-metrics
git pull
```

Then **restart the openshift-metrics MCP** (or reload the Cursor window).

- Code, recipes, allowlist, and agent guidance load from the checkout on
  the next MCP start.
- If `requirements.txt` changed, `scripts/run_mcp.sh` reinstalls deps
  automatically (stamp under `.venv/`).
- You usually do **not** need to edit your Cursor MCP JSON unless
  `mcp.json.example` gains new fields (rare).

### Manual run (optional)

```bash
./scripts/run_mcp.sh
```

### MCP tools

| Tool | Purpose |
|------|---------|
| `search_metrics` | Search general catalog (+ Telemetry flag) |
| `list_telemetry_metrics` | Allowlist search (slim by default; `detail=true` for full) |
| `is_telemetry_metric` | Membership check |
| `describe_metric` | Merge catalog + allowlist metadata |
| `list_recipes` / `run_recipe` | Named fleet PromQL (`fleet`, `cnv`, `okd`, …) |
| `render_scoped_promql` / `query_scoped_metric` | Scoped sum/count/sum_by for any allowlisted metric |
| `query_telemeter` | Raw PromQL |
| `telemeter_auth_status` | Credential/token check (no secrets echoed) |

`search_metrics` / `describe_metric` read **committed catalog YAML**
(metric and label descriptions when present). They do not auto-probe live
Telemeter label values. Use `query_telemeter` only when you need live data
that recipes / scoped tools cannot express.

`list_recipes` / `list_telemetry_metrics` return **slim** rows by default
(omit long descriptions; telemetry `limit` defaults to 25). Pass
`detail=true` when full text is required.

`run_recipe`, `query_scoped_metric`, and `query_telemeter` always return
`query_used` (the PromQL executed) and `queries_remaining_in_window`.
Agents should include the query in user-facing answers and stop
exploring when remaining queries are low.

Before every Telemeter call, PromQL **guardrails** (adapted from
[rhobs/obs-mcp](https://github.com/rhobs/obs-mcp)) reject blanket regex,
unrestricted selectors, and enforce a query rate limit. See
`docs/KNOWN_LIMITATIONS.md` and `.env.example` (`TELEMETER_GUARDRAILS`).

Agent research budget + cohort playbook: `AGENTS.md` and
`.cursor/skills/openshift-metrics/SKILL.md`.

## Refresh general metrics from a cluster

Optional and **not required** for Telemeter MCP use. Pass your own cluster
Prometheus URL (no default is embedded in the repo):

```bash
python src/main.py --token YOUR_PROMETHEUS_TOKEN \
  --prometheus-url https://prometheus.example.invalid
# or: export PROMETHEUS_URL=...
```

See `data/label_descriptions.yaml` for label description overrides.

## Tests

```bash
pip install -r requirements-dev.txt
PYTHONPATH=src pytest tests/
python src/sync_telemetry_allowlist.py --check
# Optional live Telemeter (needs credentials):
PYTHONPATH=src python scripts/smoke_test_mcp.py
```

### Agent evals (mcpchecker)

Optional LLM-agent verification (pattern from rhobs/obs-mcp; **custom
tasks** for this MCP’s tools — not a copy of obs-mcp PromQL tasks):

```bash
export OPENAI_API_KEY=...
make install-mcpchecker
make run-mcpchecker-eval                          # catalog + guardrails
make run-mcpchecker-eval EVAL_CONFIG=eval-telemeter.yaml  # live Telemeter
```

See [`evals/mcpchecker/README.md`](evals/mcpchecker/README.md).

CI runs unit tests and allowlist `--check` on pull requests
(`.github/workflows/ci.yml`).

## Join patterns & recipes

- `knowledge/join_patterns.md` — Telemeter `_id` join idioms (+ harvest notes)
- `knowledge/recipes/fleet.yaml` — cross-domain subscribed / capacity (any user)
- `knowledge/recipes/cnv.yaml` — optional CNV / virt example pack
- `knowledge/recipes/coo.yaml` — Cluster Observability Operator
- `knowledge/recipes/ocp-builds.yaml` — OpenShift Builds
- `knowledge/recipes/rhacs.yaml` — RHACS / ACS
- Add more packs as `knowledge/recipes/<domain>.yaml`

## Support

| Topic | Where |
|-------|--------|
| RHOBS SA / Telemeter access | Slack `#rhobs-support` |
| MCP, recipes, docs, allowlist | [OWNERS](OWNERS) / GitHub issues on this repo |
| Known gaps | [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) |

## Contributing

1. Do not commit secrets or customer data (see Privacy above).
2. Prefer PRs against `rhobs/openshift-metrics`.
3. Keep Telemetry allowlist updates via `sync_telemetry_allowlist.py`
   (CI fails on `--check` when the snapshot is stale).
4. New recipe packs: add YAML under `knowledge/recipes/` and tests for
   scope rendering.

## License

Apache License 2.0.
