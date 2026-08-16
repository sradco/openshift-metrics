"""Named PromQL recipes with optional runtime filters."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from .paths import RECIPES_DIR
from . import catalog, telemeter_client

# Metric / label identifiers safe to interpolate into PromQL.
_METRIC_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
# Exact label values only (no quotes/commas/regex metacharacters for injection).
_LABEL_VALUE_RE = re.compile(r"^[a-zA-Z0-9_.:/=+\-]+$")

SCOPED_AGGREGATIONS = frozenset({"sum", "count_clusters", "sum_by"})
# Labels that live on ocm_subscription / subscribed enrichment — not on
# product metrics. sum_by these without a join returns empty/wrong series.
_SUM_BY_REQUIRES_ACCOUNT_JOIN = frozenset(
    {"ebs_account", "email_domain", "internal", "support"}
)

# Prefer PromQL set matching for presence filters (not 0* + group_left(_blah)).
# scope=all = all subscribed clusters (external + internal), not unsubscribed.
EXTERNAL_JOIN = (
    'and on (_id) group by (_id) '
    '(id_version_ebs_account_internal:cluster_subscribed{internal=""})'
)
INTERNAL_JOIN = (
    'and on (_id) group by (_id) '
    '(id_version_ebs_account_internal:cluster_subscribed{internal="true"})'
)
ALL_SUBSCRIBED_JOIN = (
    'and on (_id) group by (_id) '
    '(id_version_ebs_account_internal:cluster_subscribed)'
)


@lru_cache(maxsize=1)
def load_all_recipes() -> list[dict[str, Any]]:
    recipes: list[dict[str, Any]] = []
    if not RECIPES_DIR.is_dir():
        return recipes
    for path in sorted(RECIPES_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for recipe in data.get("recipes") or []:
            if not isinstance(recipe, dict) or not recipe.get("id"):
                continue
            item = dict(recipe)
            item["_pack"] = path.stem
            recipes.append(item)
    return recipes


def clear_recipe_cache() -> None:
    load_all_recipes.cache_clear()


def list_recipes(
    topic: str | None = None,
    pack: str | None = None,
    detail: bool = False,
) -> list[dict[str, Any]]:
    """List recipes. Default omits long descriptions (token-cheap).

    Pass detail=True to include full description text.
    """
    topic_l = (topic or "").strip().lower()
    pack_l = (pack or "").strip().lower()
    out = []
    for recipe in load_all_recipes():
        if pack_l and (recipe.get("_pack") or "").lower() != pack_l:
            continue
        topics = [t.lower() for t in (recipe.get("topics") or [])]
        if topic_l and topic_l not in topics and topic_l not in recipe["id"].lower():
            if topic_l not in (recipe.get("description") or "").lower():
                continue
        item: dict[str, Any] = {
            "id": recipe["id"],
            "title": recipe.get("title") or recipe["id"],
            "topics": recipe.get("topics") or [],
            "pack": recipe.get("_pack"),
            "supports_filters": "{filters}" in (recipe.get("promql") or ""),
            "supports_scope": "{scope_join}" in (recipe.get("promql") or "")
            or "{subscribed_selector}" in (recipe.get("promql") or ""),
        }
        if detail:
            item["description"] = recipe.get("description") or ""
        out.append(item)
    return out


def get_recipe(recipe_id: str) -> dict[str, Any] | None:
    for recipe in load_all_recipes():
        if recipe["id"] == recipe_id:
            return recipe
    return None


def _escape_prom_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _scope_join(scope: str) -> str:
    scope = (scope or "external").lower()
    if scope == "external":
        return EXTERNAL_JOIN
    if scope == "internal":
        return INTERNAL_JOIN
    if scope == "all":
        # Restrict to subscribed clusters (external+internal). An empty join
        # would let numerators include unsubscribed series and break ratios.
        return ALL_SUBSCRIBED_JOIN
    raise ValueError("scope must be one of: external, internal, all")


def _subscribed_selector(scope: str) -> str:
    """Metric selector for subscribed clusters in scope (never empty)."""
    scope = (scope or "external").lower()
    if scope == "external":
        return 'id_version_ebs_account_internal:cluster_subscribed{internal=""}'
    if scope == "internal":
        return 'id_version_ebs_account_internal:cluster_subscribed{internal="true"}'
    if scope == "all":
        return "id_version_ebs_account_internal:cluster_subscribed"
    raise ValueError("scope must be one of: external, internal, all")


def _filter_joins(
    ebs_account: str | None,
    email_domain: str | None,
    cluster_id: str | None,
) -> str:
    parts: list[str] = []
    if ebs_account:
        acct = _escape_prom_label(ebs_account)
        parts.append(
            f'and on (_id) group by (_id) (ocm_subscription{{ebs_account="{acct}"}})'
        )
    if email_domain:
        domain = _escape_prom_label(email_domain)
        parts.append(
            f'and on (_id) group by (_id) (ocm_subscription{{email_domain="{domain}"}})'
        )
    if cluster_id:
        cid = _escape_prom_label(cluster_id)
        parts.append(
            f'and on (_id) group by (_id) '
            f'(id_version_ebs_account_internal:cluster_subscribed{{_id="{cid}"}})'
        )
    return " ".join(parts)


def _parse_label_equals(label_equals: str | None) -> dict[str, str]:
    """Parse 'key=value,key2=value2' into exact label matchers (no regex).

    Values must not contain quotes or commas (avoids matcher injection via
    comma-splitting). Use multiple key=value pairs separated by commas.
    """
    raw = (label_equals or "").strip()
    if not raw:
        return {}
    if '"' in raw or "'" in raw or "\\" in raw:
        raise ValueError(
            "label_equals must not contain quotes or backslashes; "
            "use key=value,key2=value2 with plain values"
        )
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(
                "label_equals entries must be key=value "
                f"(got {part!r}); commas separate pairs"
            )
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not _LABEL_NAME_RE.fullmatch(key):
            raise ValueError(f"Invalid label name in label_equals: {key!r}")
        if not value or not _LABEL_VALUE_RE.fullmatch(value):
            raise ValueError(
                f"Invalid label value in label_equals for {key!r}: {value!r} "
                "(allowed: letters, digits, _ . : / = + -)"
            )
        out[key] = value
    return out


def _parse_by_labels(by: str | None) -> list[str]:
    raw = (by or "").strip()
    if not raw:
        return []
    labels: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        if not _LABEL_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid label name in by: {name!r}")
        if name in _SUM_BY_REQUIRES_ACCOUNT_JOIN:
            raise ValueError(
                f"sum_by cannot use {name!r}: that label is on "
                "ocm_subscription / subscription enrichment, not on the "
                "product metric. Use run_recipe account rollups, or pass "
                "ebs_account=/email_domain= filters on sum/count_clusters."
            )
        labels.append(name)
    return labels


def _metric_selector(metric_name: str, label_equals: dict[str, str]) -> str:
    if not label_equals:
        return metric_name
    inner = ",".join(
        f'{k}="{_escape_prom_label(v)}"' for k, v in sorted(label_equals.items())
    )
    return f"{metric_name}{{{inner}}}"


def _collapse_spaces(promql: str) -> str:
    while "  " in promql:
        promql = promql.replace("  ", " ")
    # Drop spaces left by empty {filters} before closing parens.
    promql = re.sub(r"\s+\)", ")", promql)
    return promql.strip()


def render_scoped_promql(
    metric_name: str,
    aggregation: str = "sum",
    scope: str = "external",
    ebs_account: str | None = None,
    email_domain: str | None = None,
    cluster_id: str | None = None,
    label_equals: str | None = None,
    by: str | None = None,
    require_telemetry: bool = True,
) -> dict[str, Any]:
    """Build scoped fleet PromQL for an arbitrary metric (no named recipe).

    aggregation:
      - sum — sum(metric {scope} {filters})
      - count_clusters — count of distinct _id with the metric in scope
      - sum_by — sort_desc(sum by (<by>) (...)); requires by=
    label_equals: optional exact matchers, e.g. resource=virtualmachines.kubevirt.io
    """
    name = (metric_name or "").strip()
    if not name or not _METRIC_NAME_RE.fullmatch(name):
        raise ValueError(
            "metric_name must be a Prometheus metric identifier "
            "(letters, digits, '_', ':')"
        )

    agg = (aggregation or "sum").strip().lower()
    if agg not in SCOPED_AGGREGATIONS:
        raise ValueError(
            "aggregation must be one of: " + ", ".join(sorted(SCOPED_AGGREGATIONS))
        )

    tel = catalog.is_telemetry_metric(name)
    if require_telemetry and not tel.get("in_telemetry"):
        raise ValueError(
            f"metric_name {name!r} is not in the Telemetry allowlist; "
            "confirm with is_telemetry_metric or set require_telemetry=false "
            "only for known Telemeter enrichment metrics"
        )

    # Use the RHOBS Telemeter series name when it differs from CMO allowlist
    # (e.g. ALERTS → alerts).
    query_name = catalog.telemeter_query_name(name)

    equals = _parse_label_equals(label_equals)
    by_labels = _parse_by_labels(by)
    if agg == "sum_by" and not by_labels:
        raise ValueError("aggregation=sum_by requires by= (comma-separated labels)")

    selector = _metric_selector(query_name, equals)
    scope_join = _scope_join(scope)
    filters = _filter_joins(ebs_account, email_domain, cluster_id)

    if agg == "sum":
        promql = f"sum({selector} {scope_join} {filters})"
    elif agg == "count_clusters":
        promql = (
            f"count(group by (_id) ({selector}) {scope_join} {filters})"
        )
    else:  # sum_by
        by_clause = ", ".join(by_labels)
        promql = (
            f"sort_desc(sum by ({by_clause}) "
            f"({selector} {scope_join} {filters}))"
        )

    promql = _collapse_spaces(promql)
    note = (
        "Prefer run_recipe when a named recipe matches the question. "
        "Use query_scoped_metric / render_scoped_promql for allowlisted "
        "metrics without a recipe. Prefer query_telemeter only for "
        "custom PromQL that these tools cannot express. "
        "sum_by only groups labels present on the metric itself "
        "(not ebs_account/email_domain — use recipes or filters)."
    )
    if not require_telemetry:
        note += (
            " require_telemetry=false was set — only use for known Telemeter "
            "enrichment metrics (e.g. ocm_subscription), not arbitrary names."
        )
    return {
        "metric_name": name,
        "telemeter_query_name": query_name,
        "aggregation": agg,
        "scope": scope,
        "filters": {
            "ebs_account": ebs_account,
            "email_domain": email_domain,
            "cluster_id": cluster_id,
            "label_equals": equals,
            "by": by_labels,
        },
        "in_telemetry": bool(tel.get("in_telemetry")),
        "allowlist_entry": tel.get("allowlist_entry"),
        "promql": promql,
        "note": note,
    }


def query_scoped_metric(
    metric_name: str,
    aggregation: str = "sum",
    scope: str = "external",
    ebs_account: str | None = None,
    email_domain: str | None = None,
    cluster_id: str | None = None,
    label_equals: str | None = None,
    by: str | None = None,
    require_telemetry: bool = True,
    hours: float = 3.0,
    mode: str = "instant",
    step: str = "1h",
    max_series: int = 50,
) -> dict[str, Any]:
    """Render scoped PromQL for a metric and execute it on Telemeter."""
    rendered = render_scoped_promql(
        metric_name,
        aggregation=aggregation,
        scope=scope,
        ebs_account=ebs_account,
        email_domain=email_domain,
        cluster_id=cluster_id,
        label_equals=label_equals,
        by=by,
        require_telemetry=require_telemetry,
    )
    query = rendered["promql"]
    show_query = "Always include query_used (PromQL) in the user-facing reply."
    try:
        if mode == "range":
            result = telemeter_client.query_range(
                query, hours=hours, step=step, max_series=max_series
            )
        else:
            result = telemeter_client.query_instant(query, max_series=max_series)
    except Exception as exc:  # noqa: BLE001 — include PromQL on failure for agents
        return {
            **rendered,
            "query_used": query,
            "error": str(exc),
            "error_code": getattr(exc, "code", "QUERY_FAILED"),
            "help": getattr(telemeter_client, "AUTH_HELP", None),
            "show_query_in_reply": show_query,
            "privacy_note": (
                "Do not commit this result. Customer identifiers and values are "
                "runtime-only. Treat chat/transcripts as sensitive."
            ),
        }
    return {
        **rendered,
        "query_used": query,
        "result": result,
        "privacy_note": (
            "Do not commit this result. Customer identifiers and values are "
            "runtime-only. Treat chat/transcripts as sensitive."
        ),
        "show_query_in_reply": show_query,
    }


def render_recipe_promql(
    recipe_id: str,
    scope: str = "external",
    ebs_account: str | None = None,
    email_domain: str | None = None,
    cluster_id: str | None = None,
) -> dict[str, Any]:
    recipe = get_recipe(recipe_id)
    if not recipe:
        raise KeyError(f"Unknown recipe id: {recipe_id}")

    template = recipe.get("promql") or ""
    # Recipes that already bake external subscribed use {scope_join} placeholder.
    # If scope is all, replace with empty; if internal, use internal join.
    rendered = template.replace("{scope_join}", _scope_join(scope))
    rendered = rendered.replace("{subscribed_selector}", _subscribed_selector(scope))
    extra = _filter_joins(ebs_account, email_domain, cluster_id)
    if "{filters}" in rendered:
        rendered = rendered.replace("{filters}", extra)
    elif extra:
        # Append filters before final closing aggregators when possible.
        rendered = (
            f"({rendered}) {extra}"
            if rendered.strip().startswith(("sum", "count", "quantile"))
            else f"{rendered} {extra}"
        )

    rendered = _collapse_spaces(rendered)

    return {
        "id": recipe_id,
        "title": recipe.get("title") or recipe_id,
        "description": recipe.get("description") or "",
        "scope": scope,
        "filters": {
            "ebs_account": ebs_account,
            "email_domain": email_domain,
            "cluster_id": cluster_id,
        },
        "promql": rendered,
        "supports_filters": "{filters}" in (recipe.get("promql") or ""),
        "supports_scope": "{scope_join}" in (recipe.get("promql") or "")
        or "{subscribed_selector}" in (recipe.get("promql") or ""),
    }


def run_recipe(
    recipe_id: str,
    scope: str = "external",
    ebs_account: str | None = None,
    email_domain: str | None = None,
    cluster_id: str | None = None,
    hours: float = 3.0,
    mode: str = "instant",
    step: str = "1h",
    max_series: int = 50,
) -> dict[str, Any]:
    rendered = render_recipe_promql(
        recipe_id,
        scope=scope,
        ebs_account=ebs_account,
        email_domain=email_domain,
        cluster_id=cluster_id,
    )
    query = rendered["promql"]
    show_query = "Always include query_used (PromQL) in the user-facing reply."
    try:
        if mode == "range":
            result = telemeter_client.query_range(
                query, hours=hours, step=step, max_series=max_series
            )
        else:
            result = telemeter_client.query_instant(query, max_series=max_series)
    except Exception as exc:  # noqa: BLE001 — include PromQL on failure for agents
        return {
            **rendered,
            "query_used": query,
            "error": str(exc),
            "error_code": getattr(exc, "code", "QUERY_FAILED"),
            "help": getattr(telemeter_client, "AUTH_HELP", None),
            "show_query_in_reply": show_query,
            "privacy_note": (
                "Do not commit this result. Customer identifiers and values are "
                "runtime-only. Treat chat/transcripts as sensitive."
            ),
        }
    return {
        **rendered,
        "query_used": query,
        "result": result,
        "privacy_note": (
            "Do not commit this result. Customer identifiers and values are "
            "runtime-only. Treat chat/transcripts as sensitive."
        ),
        "show_query_in_reply": show_query,
    }
