"""Catalog loaders for general metrics and Telemetry allowlist."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from .paths import PROMETHEUS_METRICS_DIR, TELEMETRY_ALLOWLIST_PATH


@lru_cache(maxsize=1)
def load_general_metrics() -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    if not PROMETHEUS_METRICS_DIR.is_dir():
        return metrics
    for path in sorted(PROMETHEUS_METRICS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for item in data.get("metrics") or []:
            if not isinstance(item, dict) or not item.get("metric_name"):
                continue
            entry = dict(item)
            entry["_source_file"] = path.name
            metrics.append(entry)
    return metrics


@lru_cache(maxsize=1)
def load_telemetry_allowlist() -> dict[str, Any]:
    if not TELEMETRY_ALLOWLIST_PATH.is_file():
        return {"matches": [], "source": "", "note": "allowlist missing"}
    data = yaml.safe_load(TELEMETRY_ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"matches": [], "source": "", "note": "invalid allowlist"}
    data.setdefault("matches", [])
    return data


def clear_catalog_caches() -> None:
    load_general_metrics.cache_clear()
    load_telemetry_allowlist.cache_clear()


def _telemetry_match_for_name(metric_name: str) -> dict[str, Any] | None:
    allowlist = load_telemetry_allowlist()
    exact: dict[str, Any] | None = None
    regex_hit: dict[str, Any] | None = None
    for entry in allowlist.get("matches") or []:
        if entry.get("metric_name") == metric_name:
            exact = entry
            break
        pattern = entry.get("metric_name_regex")
        if pattern and re.fullmatch(pattern, metric_name):
            regex_hit = entry
    return exact or regex_hit


def is_telemetry_metric(metric_name: str) -> dict[str, Any]:
    match = _telemetry_match_for_name(metric_name)
    return {
        "metric_name": metric_name,
        "in_telemetry": match is not None,
        "allowlist_entry": match,
    }


def list_telemetry_metrics(query: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    matches = list(load_telemetry_allowlist().get("matches") or [])
    if query:
        q = query.lower()
        matches = [
            m
            for m in matches
            if q in (m.get("metric_name") or "").lower()
            or q in (m.get("metric_name_regex") or "").lower()
            or q in (m.get("description") or "").lower()
            or q in (m.get("selector") or "").lower()
        ]
    return matches[: max(1, min(limit, 500))]


def search_metrics(query: str, limit: int = 25, telemetry_only: bool = False) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return []
    results: list[dict[str, Any]] = []
    for metric in load_general_metrics():
        name = metric.get("metric_name") or ""
        desc = metric.get("metric_description") or ""
        label_blob = " ".join(
            f"{lab.get('label_name') or ''} {lab.get('label_description') or ''}"
            for lab in (metric.get("labels") or [])
            if isinstance(lab, dict)
        )
        if (
            q not in name.lower()
            and q not in str(desc).lower()
            and q not in label_blob.lower()
        ):
            continue
        tel = is_telemetry_metric(name)
        if telemetry_only and not tel["in_telemetry"]:
            continue
        results.append(
            {
                "metric_name": name,
                "metric_description": desc,
                "type": metric.get("type"),
                "labels": [
                    {
                        "label_name": lab.get("label_name"),
                        "label_description": lab.get("label_description"),
                    }
                    for lab in (metric.get("labels") or [])
                    if isinstance(lab, dict)
                ],
                "source_file": metric.get("_source_file"),
                "in_telemetry": tel["in_telemetry"],
            }
        )
        if len(results) >= limit:
            break

    # Also surface allowlist-only names not present in general catalog.
    if len(results) < limit:
        seen = {r["metric_name"] for r in results}
        for entry in list_telemetry_metrics(query=query, limit=limit):
            name = entry.get("metric_name") or entry.get("metric_name_regex")
            if not name or name in seen:
                continue
            results.append(
                {
                    "metric_name": name,
                    "metric_description": entry.get("description"),
                    "type": None,
                    "labels": [],
                    "source_file": "docs/telemetry/allowlist.yaml",
                    "in_telemetry": True,
                    "match_type": entry.get("match_type"),
                    "selector": entry.get("selector"),
                }
            )
            seen.add(name)
            if len(results) >= limit:
                break
    return results[:limit]


def describe_metric(metric_name: str) -> dict[str, Any]:
    general = next(
        (m for m in load_general_metrics() if m.get("metric_name") == metric_name),
        None,
    )
    tel = is_telemetry_metric(metric_name)
    result: dict[str, Any] = {
        "metric_name": metric_name,
        "in_telemetry": tel["in_telemetry"],
        "telemetry": tel.get("allowlist_entry"),
        "general_catalog": None,
    }
    if general:
        result["general_catalog"] = {
            "metric_description": general.get("metric_description"),
            "type": general.get("type"),
            "labels": general.get("labels") or [],
            "source_file": general.get("_source_file"),
        }
    if not general and not tel["in_telemetry"]:
        result["note"] = (
            "Metric not found in general catalog or Telemetry allowlist. "
            "It may still exist on some clusters; catalogs are partial."
        )
    elif not tel["in_telemetry"] and general:
        result["note"] = (
            "Present in general metrics catalog but NOT confirmed in Telemetry allowlist."
        )
    elif tel["in_telemetry"] and not general:
        result["note"] = (
            "Present in Telemetry allowlist; no entry in general prometheus_metrics catalog."
        )
    return result


def allowlist_source_info() -> dict[str, Any]:
    data = load_telemetry_allowlist()
    return {
        "source": data.get("source"),
        "note": data.get("note"),
        "match_count": len(data.get("matches") or []),
        "path": str(TELEMETRY_ALLOWLIST_PATH),
    }
