"""Named PromQL recipes with optional runtime filters."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from .paths import RECIPES_DIR
from . import telemeter_client

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


def list_recipes(topic: str | None = None) -> list[dict[str, Any]]:
    topic_l = (topic or "").strip().lower()
    out = []
    for recipe in load_all_recipes():
        topics = [t.lower() for t in (recipe.get("topics") or [])]
        if topic_l and topic_l not in topics and topic_l not in recipe["id"].lower():
            if topic_l not in (recipe.get("description") or "").lower():
                continue
        out.append(
            {
                "id": recipe["id"],
                "title": recipe.get("title") or recipe["id"],
                "description": recipe.get("description") or "",
                "topics": recipe.get("topics") or [],
                "pack": recipe.get("_pack"),
                "supports_filters": "{filters}" in (recipe.get("promql") or ""),
                "supports_scope": "{scope_join}" in (recipe.get("promql") or "")
                or "{subscribed_selector}" in (recipe.get("promql") or ""),
            }
        )
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

    # Clean double spaces from empty placeholders
    while "  " in rendered:
        rendered = rendered.replace("  ", " ")
    rendered = rendered.strip()

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
                query, hours=hours, max_series=max_series
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
