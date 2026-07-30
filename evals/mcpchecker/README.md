# MCPChecker evals for openshift-metrics
#
# Pattern adapted from rhobs/obs-mcp (evals/mcpchecker). Tasks are **not**
# copies of obs-mcp tasks — tool names and backend (catalog + Telemeter)
# differ. We reuse the mcpchecker framework and task YAML shape.

## Prerequisites

1. Install mcpchecker (from repo root):

   ```bash
   make install-mcpchecker
   ```

2. LLM API key for agent + judge (default: OpenAI):

   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

3. Repo `.venv` / deps via `scripts/run_mcp.sh` (auto-created on first run).

4. **Catalog evals** need no Telemeter credentials.
5. **Telemeter evals** need `PROM_URL`, `CLIENTID`, `CLIENTSECRET` in `.env`
   (gitignored). Live tasks hit Telemeter — keep concurrency low.

## Run

From repo root:

```bash
# Catalog + guardrail tasks (default)
make run-mcpchecker-eval

# Single task
make run-mcpchecker-eval TASK=catalog-is-telemetry-metric

# Category filter
make run-mcpchecker-eval CATEGORY=catalog
make run-mcpchecker-eval CATEGORY=guardrails

# Live Telemeter suite (credentials required)
make run-mcpchecker-eval EVAL_CONFIG=eval-telemeter.yaml

# Consistency (costs more tokens)
make run-mcpchecker-eval RUNS=3
```

Output JSON (name follows eval metadata): under `evals/mcpchecker/` after a run.
Summarize with:

```bash
make summary-mcpchecker-eval
```

## Task map

| Category | Tasks | Telemeter? |
|----------|--------|------------|
| `catalog` | allowlist check, missing metric, search, list recipes, scoped PromQL | No |
| `guardrails` | refuse blanket dump; lean research budget (≤8 tools) | No |
| `telemeter` | auth; subscribed_clusters; lean `okd_running_vms` recipe | Yes |

## Relationship to obs-mcp / openshift-mcp-server

- Framework: [mcpchecker](https://github.com/mcpchecker/mcpchecker)
- Inspiration: [rhobs/obs-mcp evals](https://github.com/rhobs/obs-mcp/tree/main/evals/mcpchecker)
- Do **not** sync obs-mcp PromQL/cluster tasks here — different tools (`list_metrics`
  vs `search_metrics` / `run_recipe`) and backend (in-cluster Prometheus vs Telemeter).

## Notes

- Rate limit is per MCP process (default 30/10min). Parallel Telemeter evals
  can burn the budget quickly — prefer `EVAL_CONFIG=eval-telemeter.yaml`
  without high `--parallel` unless you raise limits locally.
- Never commit eval transcripts that contain customer identifiers from live queries.
