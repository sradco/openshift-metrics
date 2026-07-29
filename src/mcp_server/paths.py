"""Repository path helpers."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMETHEUS_METRICS_DIR = REPO_ROOT / "docs" / "prometheus_metrics"
TELEMETRY_ALLOWLIST_PATH = REPO_ROOT / "docs" / "telemetry" / "allowlist.yaml"
RECIPES_DIR = REPO_ROOT / "knowledge" / "recipes"
