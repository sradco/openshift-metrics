"""PromQL guardrails adapted from rhobs/obs-mcp for Telemeter.

Static checks (no TSDB endpoint required):
- disallow-blanket-regex: reject label=~".*" / ".+"
- disallow-unrestricted-selectors: reject {} and __name__=~".*" / ".+"
- require-non-name-matcher: optional; every selector needs a non-__name__
  label (too strict for fleet recipes — off by default)

Operational limits:
- rate-limit: max Telemeter queries per rolling window
- max-range-hours: already enforced in query_range; re-checked here

TSDB-based max-metric-cardinality from obs-mcp is not available on RHOBS
Telemeter; series truncation remains the post-query backstop.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


class GuardrailViolation(ValueError):
    """Query rejected by a guardrail."""

    def __init__(self, message: str, *, guardrail: str) -> None:
        super().__init__(message)
        self.guardrail = guardrail
        self.code = "GUARDRAIL_VIOLATION"


# Blanket regex values (exact), matching obs-mcp ExtractBlanketRegexLabels.
_BLANKET_REGEX_VALUE = re.compile(
    r"""(?:=~|!~)\s*(['"])(\.\*|\.\+)\1"""
)
# Empty vector selector {}
_EMPTY_SELECTOR = re.compile(r"(?<![A-Za-z0-9_:])\{\s*\}")
# Unrestricted __name__ regex
_UNRESTRICTED_NAME = re.compile(
    r"""__name__\s*(?:=~|!~)\s*(['"])(\.\*|\.\+)\1"""
)
# A label matcher that is not __name__ (rough): foo="...", foo=~"..."
_NON_NAME_MATCHER = re.compile(
    r"""(?<![A-Za-z0-9_])(?!__name__)([A-Za-z_][A-Za-z0-9_]*)\s*(?:=~?|!~?)\s*['"]"""
)


@dataclass
class Guardrails:
    disallow_blanket_regex: bool = True
    disallow_unrestricted_selectors: bool = True
    require_non_name_matcher: bool = False
    rate_limit_enabled: bool = True
    max_queries: int = 30
    window_seconds: float = 600.0  # 10 minutes
    max_range_hours: float = 48.0

    def check_query(self, query: str, *, mode: str = "instant", hours: float = 0.0) -> None:
        """Raise GuardrailViolation if the query is unsafe."""
        q = (query or "").strip()
        if not q:
            raise GuardrailViolation("empty PromQL query", guardrail="empty-query")

        if self.disallow_unrestricted_selectors:
            if _EMPTY_SELECTOR.search(q):
                raise GuardrailViolation(
                    'query uses unrestricted selector "{}", which is disallowed',
                    guardrail="disallow-unrestricted-selectors",
                )
            if _UNRESTRICTED_NAME.search(q):
                raise GuardrailViolation(
                    'query uses unrestricted __name__ regex (".*" or ".+"), which is disallowed',
                    guardrail="disallow-unrestricted-selectors",
                )

        if self.disallow_blanket_regex:
            m = _BLANKET_REGEX_VALUE.search(q)
            if m:
                raise GuardrailViolation(
                    'query uses blanket regex ".*" or ".+" on a label, which is disallowed '
                    "(from obs-mcp disallow-blanket-regex)",
                    guardrail="disallow-blanket-regex",
                )

        if self.require_non_name_matcher:
            # Heuristic: if the query has a metric-like token / selector block
            # without any non-__name__ matcher, reject. Fleet recipes should
            # leave this guardrail off.
            if not _NON_NAME_MATCHER.search(q):
                raise GuardrailViolation(
                    "query has no non-__name__ label matchers, which is required",
                    guardrail="require-non-name-matcher",
                )

        if mode == "range" and hours > self.max_range_hours:
            raise GuardrailViolation(
                f"range query hours={hours} exceeds maximum allowed {self.max_range_hours}",
                guardrail="max-range-hours",
            )


_RATE_LOCK = threading.Lock()
_RATE_HITS: deque[float] = deque()


def _rate_limit_check(g: Guardrails) -> None:
    if not g.rate_limit_enabled:
        return
    now = time.monotonic()
    with _RATE_LOCK:
        while _RATE_HITS and now - _RATE_HITS[0] > g.window_seconds:
            _RATE_HITS.popleft()
        if len(_RATE_HITS) >= g.max_queries:
            raise GuardrailViolation(
                f"Telemeter query rate limit exceeded "
                f"({g.max_queries} queries / {int(g.window_seconds)}s). "
                "Prefer run_recipe, wait, or raise TELEMETER_GUARDRAIL_MAX_QUERIES.",
                guardrail="rate-limit",
            )
        _RATE_HITS.append(now)


def reset_rate_limit_for_tests() -> None:
    with _RATE_LOCK:
        _RATE_HITS.clear()


def parse_guardrails(value: str | None = None) -> Guardrails | None:
    """Parse TELEMETER_GUARDRAILS like obs-mcp --guardrails.

    Values:
      all / "" / unset → all static + rate-limit (default)
      none → disabled
      comma list → enable named rails
      !name,... → all except named
    """
    raw = (value if value is not None else os.environ.get("TELEMETER_GUARDRAILS", "all")).strip().lower()
    if raw in {"none", "off", "0", "false"}:
        return None
    if raw in {"all", ""}:
        return _from_env_thresholds(Guardrails())

    negative = "!" in raw
    names = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if negative != part.startswith("!"):
            raise ValueError(
                "cannot mix positive and negative guardrail names; "
                "use names to enable, or !name to disable from the full set"
            )
        names.append(part.lstrip("!"))

    g = Guardrails(
        disallow_blanket_regex=negative,
        disallow_unrestricted_selectors=negative,
        require_non_name_matcher=False,
        rate_limit_enabled=negative,
    )
    for name in names:
        on = not negative
        if name == "disallow-blanket-regex":
            g.disallow_blanket_regex = on
        elif name == "disallow-unrestricted-selectors":
            g.disallow_unrestricted_selectors = on
        elif name == "require-non-name-matcher":
            g.require_non_name_matcher = on
        elif name == "rate-limit":
            g.rate_limit_enabled = on
        elif name in {"tsdb", "max-metric-cardinality"}:
            # Telemeter has no TSDB status API; ignore / no-op for compatibility.
            continue
        else:
            raise ValueError(
                f"unknown guardrail: {name!r} (valid: disallow-blanket-regex, "
                "disallow-unrestricted-selectors, require-non-name-matcher, rate-limit)"
            )
    return _from_env_thresholds(g)


def _from_env_thresholds(g: Guardrails) -> Guardrails:
    if os.environ.get("TELEMETER_GUARDRAIL_MAX_QUERIES"):
        g.max_queries = max(1, int(os.environ["TELEMETER_GUARDRAIL_MAX_QUERIES"]))
    if os.environ.get("TELEMETER_GUARDRAIL_WINDOW_SECONDS"):
        g.window_seconds = max(1.0, float(os.environ["TELEMETER_GUARDRAIL_WINDOW_SECONDS"]))
    if os.environ.get("TELEMETER_GUARDRAIL_MAX_RANGE_HOURS"):
        g.max_range_hours = max(0.25, float(os.environ["TELEMETER_GUARDRAIL_MAX_RANGE_HOURS"]))
    return g


def enforce(query: str, *, mode: str = "instant", hours: float = 0.0) -> dict[str, Any]:
    """Run configured guardrails; return metadata. Raises GuardrailViolation."""
    g = parse_guardrails()
    if g is None:
        return {"guardrails": "none"}
    g.check_query(query, mode=mode, hours=hours)
    _rate_limit_check(g)
    return {
        "guardrails": "enforced",
        "disallow_blanket_regex": g.disallow_blanket_regex,
        "disallow_unrestricted_selectors": g.disallow_unrestricted_selectors,
        "require_non_name_matcher": g.require_non_name_matcher,
        "rate_limit": g.rate_limit_enabled,
        "max_queries": g.max_queries,
        "window_seconds": g.window_seconds,
    }
