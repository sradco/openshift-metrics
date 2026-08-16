# Build: podman build -t openshift-metrics-mcp -f Containerfile .
# Run:   podman run --rm -p 8000:8000 --env-file .env \
#          -e MCP_HTTP_TOKEN=... openshift-metrics-mcp
FROM registry.access.redhat.com/ubi9/python-312:latest@sha256:5b4afe134433cca259f0726204dc8103db6a71c9c5ffe6f5f14aba86d78f3f4d

USER 0
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY knowledge ./knowledge
COPY docs/telemetry ./docs/telemetry
COPY docs/prometheus_metrics ./docs/prometheus_metrics

RUN uv sync --frozen --no-dev --no-cache \
  && rm -f /usr/local/bin/uv \
  && chown -R 1001:0 /app

USER 1001
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_PATH=/mcp \
    HOME=/tmp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["/app/.venv/bin/python", "-m", "mcp_server", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--path", "/mcp"]
