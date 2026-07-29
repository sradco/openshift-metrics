#!/usr/bin/env python3
"""Sync Telemetry allowlist from cluster-monitoring-operator config.

Parses the telemeter client ConfigMap (metrics.yaml matches) and writes
docs/telemetry/allowlist.yaml. No credentials or customer data involved.

Use --check to verify the committed allowlist matches CMO (CI / drift
detection) without writing.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import yaml

DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/openshift/cluster-monitoring-operator/"
    "main/manifests/0000_50_cluster-monitoring-operator_04-config.yaml"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "telemetry" / "allowlist.yaml"

MATCH_LINE_RE = re.compile(r"^\s*-\s*'(?P<select>.+)'\s*$")
OWNERS_RE = re.compile(r"owners:\s*(.+)", re.IGNORECASE)
CONSUMERS_RE = re.compile(r"consumers:\s*(.+)", re.IGNORECASE)
NAME_EQ_RE = re.compile(r'__name__\s*=\s*"([^"]+)"')
NAME_RE_RE = re.compile(r'__name__\s*=~\s*"([^"]+)"')


def extract_metrics_yaml_block(configmap_text: str) -> str:
    """Return the embedded metrics.yaml string from a ConfigMap manifest."""
    data = yaml.safe_load(configmap_text)
    if not isinstance(data, dict):
        raise ValueError("ConfigMap root must be a mapping")
    metrics_yaml = (data.get("data") or {}).get("metrics.yaml")
    if not metrics_yaml or not isinstance(metrics_yaml, str):
        raise ValueError("ConfigMap data.metrics.yaml missing or not a string")
    return metrics_yaml


def _comment_body(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    return stripped.lstrip("#").strip()


def parse_matches_with_comments(metrics_yaml_text: str) -> list[dict[str, Any]]:
    """Parse matches entries and associate preceding comment metadata."""
    entries: list[dict[str, Any]] = []
    owners = ""
    consumers = ""
    desc_lines: list[str] = []

    for raw_line in metrics_yaml_text.splitlines():
        comment = _comment_body(raw_line)
        if comment is not None:
            if not comment:
                continue
            owners_match = OWNERS_RE.search(comment)
            if owners_match:
                owners = owners_match.group(1).strip()
                continue
            consumers_match = CONSUMERS_RE.search(comment)
            if consumers_match:
                consumers = consumers_match.group(1).strip()
                continue
            desc_lines.append(comment)
            continue

        match = MATCH_LINE_RE.match(raw_line)
        if not match:
            continue

        selector = match.group("select")
        name_eq = NAME_EQ_RE.search(selector)
        name_re = NAME_RE_RE.search(selector)
        entry: dict[str, Any] = {
            "selector": selector,
            "description": " ".join(desc_lines).strip(),
        }
        if owners:
            entry["owners"] = owners
        if consumers:
            entry["consumers"] = consumers
        if name_eq:
            entry["metric_name"] = name_eq.group(1)
            entry["match_type"] = "exact"
        elif name_re:
            entry["metric_name_regex"] = name_re.group(1)
            entry["match_type"] = "regex"
        else:
            entry["match_type"] = "selector"
        entries.append(entry)
        owners = ""
        consumers = ""
        desc_lines = []

    return entries


def build_allowlist_document(
    entries: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "note": (
            "Canonical Telemetry allowlist derived from cluster-monitoring-operator. "
            "General metrics under docs/prometheus_metrics/ are NOT all telemetered."
        ),
        "matches": entries,
    }


def dump_allowlist_yaml(document: dict[str, Any]) -> str:
    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )


def load_source(path: str | None, url: str | None) -> tuple[str, str]:
    if path:
        text = Path(path).read_text(encoding="utf-8")
        return text, str(Path(path).resolve())
    source_url = url or DEFAULT_SOURCE_URL
    with urlopen(source_url, timeout=60) as resp:  # noqa: S310 — fixed upstream URL or user-provided
        text = resp.read().decode("utf-8")
    return text, source_url


def render_allowlist(
    path: str | None = None,
    url: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Parse CMO source and return (document, dumped YAML text)."""
    configmap_text, source = load_source(path, url)
    metrics_yaml = extract_metrics_yaml_block(configmap_text)
    entries = parse_matches_with_comments(metrics_yaml)
    if not entries:
        raise ValueError("No Telemetry matches parsed from source")
    document = build_allowlist_document(entries, source)
    return document, dump_allowlist_yaml(document)


def sync_allowlist(
    output: Path,
    path: str | None = None,
    url: str | None = None,
) -> Path:
    _, rendered = render_allowlist(path=path, url=url)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return output


def check_allowlist(
    output: Path,
    path: str | None = None,
    url: str | None = None,
) -> tuple[bool, str]:
    """Return (ok, message). ok is False when committed allowlist is stale."""
    if not output.is_file():
        return False, f"Missing allowlist file: {output}"

    _, expected = render_allowlist(path=path, url=url)
    actual = output.read_text(encoding="utf-8")
    if actual == expected:
        return True, f"Allowlist is up to date with source ({output})"

    diff = "".join(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(output),
            tofile="allowlist.from_cmo",
            n=3,
        )
    )
    message = (
        "Telemetry allowlist is stale relative to CMO source.\n"
        "Refresh with:\n"
        "  python src/sync_telemetry_allowlist.py\n"
        f"\n{diff}"
    )
    return False, message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-url",
        default=DEFAULT_SOURCE_URL,
        help="URL of the CMO telemeter ConfigMap manifest",
    )
    parser.add_argument(
        "--source-file",
        default=None,
        help="Local ConfigMap manifest path (overrides --source-url)",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Allowlist YAML path (write target or check target)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 0 if allowlist matches source; 1 if stale (no write)",
    )
    args = parser.parse_args(argv)
    output = Path(args.output)
    source_kwargs = {
        "path": args.source_file,
        "url": None if args.source_file else args.source_url,
    }

    if args.check:
        ok, message = check_allowlist(output, **source_kwargs)
        print(message)
        return 0 if ok else 1

    written = sync_allowlist(output, **source_kwargs)
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
