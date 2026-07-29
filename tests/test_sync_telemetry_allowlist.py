"""Unit tests for Telemetry allowlist sync (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sync_telemetry_allowlist import (  # noqa: E402
    check_allowlist,
    extract_metrics_yaml_block,
    main,
    parse_matches_with_comments,
    sync_allowlist,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cmo_telemetry_configmap.yaml"


def test_parse_fixture_entries():
    text = FIXTURE.read_text(encoding="utf-8")
    metrics_yaml = extract_metrics_yaml_block(text)
    entries = parse_matches_with_comments(metrics_yaml)
    assert len(entries) == 3

    usage = entries[0]
    assert usage["match_type"] == "regex"
    assert usage["metric_name_regex"] == "cluster:usage:.*"
    assert "cluster:usage recording rules" in usage["description"]
    assert "@openshift/openshift-team-monitoring" in usage["owners"]

    vmi = entries[1]
    assert vmi["match_type"] == "exact"
    assert vmi["metric_name"] == "cnv:vmi_status_running:count"
    assert "VM instances" in vmi["description"]

    abnormal = entries[2]
    assert abnormal["metric_name"] == "cnv_abnormal"
    assert "reason=~" in abnormal["selector"]
    assert abnormal["consumers"] == "(@example/consumers)"


def test_sync_allowlist_writes_yaml(tmp_path: Path):
    out = tmp_path / "allowlist.yaml"
    sync_allowlist(out, path=str(FIXTURE))
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["source"].endswith("cmo_telemetry_configmap.yaml")
    assert len(doc["matches"]) == 3
    names = {m.get("metric_name") for m in doc["matches"]}
    assert "cnv:vmi_status_running:count" in names


def test_check_allowlist_ok(tmp_path: Path):
    out = tmp_path / "allowlist.yaml"
    sync_allowlist(out, path=str(FIXTURE))
    ok, message = check_allowlist(out, path=str(FIXTURE))
    assert ok is True
    assert "up to date" in message


def test_check_allowlist_detects_stale(tmp_path: Path):
    out = tmp_path / "allowlist.yaml"
    sync_allowlist(out, path=str(FIXTURE))
    out.write_text("source: stale\nmatches: []\n", encoding="utf-8")
    ok, message = check_allowlist(out, path=str(FIXTURE))
    assert ok is False
    assert "stale" in message.lower()
    assert "sync_telemetry_allowlist.py" in message


def test_main_check_exit_codes(tmp_path: Path):
    out = tmp_path / "allowlist.yaml"
    sync_allowlist(out, path=str(FIXTURE))
    assert main(["--check", "--source-file", str(FIXTURE), "--output", str(out)]) == 0
    out.write_text("source: stale\nmatches: []\n", encoding="utf-8")
    assert main(["--check", "--source-file", str(FIXTURE), "--output", str(out)]) == 1
