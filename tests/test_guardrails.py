"""Unit tests for Telemeter PromQL guardrails (obs-mcp–inspired)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from mcp_server import guardrails as gr


class GuardrailsParseTest(unittest.TestCase):
    def test_default_all(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEMETER_GUARDRAILS", None)
            g = gr.parse_guardrails()
        assert g is not None
        self.assertTrue(g.disallow_blanket_regex)
        self.assertTrue(g.disallow_unrestricted_selectors)
        self.assertTrue(g.rate_limit_enabled)
        self.assertFalse(g.require_non_name_matcher)

    def test_none(self) -> None:
        with mock.patch.dict(os.environ, {"TELEMETER_GUARDRAILS": "none"}):
            self.assertIsNone(gr.parse_guardrails())

    def test_explicit_list(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TELEMETER_GUARDRAILS": "disallow-blanket-regex,rate-limit"},
        ):
            g = gr.parse_guardrails()
        assert g is not None
        self.assertTrue(g.disallow_blanket_regex)
        self.assertFalse(g.disallow_unrestricted_selectors)
        self.assertTrue(g.rate_limit_enabled)


class BlanketRegexTest(unittest.TestCase):
    def test_rejects_exact_dot_star(self) -> None:
        with mock.patch.dict(
            os.environ, {"TELEMETER_GUARDRAILS": "disallow-blanket-regex"}
        ):
            with self.assertRaises(gr.GuardrailViolation) as ctx:
                gr.enforce('up{job=~".*"}', mode="instant")
        self.assertEqual(ctx.exception.guardrail, "disallow-blanket-regex")

    def test_allows_scoped_regex(self) -> None:
        with mock.patch.dict(
            os.environ, {"TELEMETER_GUARDRAILS": "disallow-blanket-regex"}
        ):
            meta = gr.enforce(
                'cluster:usage:workload:capacity_physical_cpu_cores:max{name=~".*hyperconverged.*"}',
                mode="instant",
            )
        self.assertEqual(meta["guardrails"], "enforced")

    def test_allows_metric_only(self) -> None:
        with mock.patch.dict(
            os.environ, {"TELEMETER_GUARDRAILS": "disallow-blanket-regex"}
        ):
            gr.enforce("sum(cnv:vmi_status_running:count)", mode="instant")


class UnrestrictedTest(unittest.TestCase):
    def test_rejects_empty_selector(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TELEMETER_GUARDRAILS": "disallow-unrestricted-selectors"},
        ):
            with self.assertRaises(gr.GuardrailViolation):
                gr.enforce("count({})", mode="instant")

    def test_rejects_unrestricted_name(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TELEMETER_GUARDRAILS": "disallow-unrestricted-selectors"},
        ):
            with self.assertRaises(gr.GuardrailViolation):
                gr.enforce('{__name__=~".*"}', mode="instant")

    def test_allows_named_metric(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TELEMETER_GUARDRAILS": "disallow-unrestricted-selectors"},
        ):
            gr.enforce(
                "sum(cnv:vmi_status_running:count)",
                mode="instant",
            )


class RequireMatcherTest(unittest.TestCase):
    def test_rejects_metric_only_when_enabled(self) -> None:
        with mock.patch.dict(
            os.environ, {"TELEMETER_GUARDRAILS": "require-non-name-matcher"}
        ):
            with self.assertRaises(gr.GuardrailViolation):
                gr.enforce(
                    "sum(cnv:vmi_status_running:count)",
                    mode="instant",
                )

    def test_allows_with_label(self) -> None:
        with mock.patch.dict(
            os.environ, {"TELEMETER_GUARDRAILS": "require-non-name-matcher"}
        ):
            gr.enforce(
                'sum(cnv:vmi_status_running:count{namespace="openshift-cnv"})',
                mode="instant",
            )


class RateLimitTest(unittest.TestCase):
    def test_rate_limit(self) -> None:
        gr.reset_rate_limit_for_tests()
        with mock.patch.dict(
            os.environ,
            {
                "TELEMETER_GUARDRAILS": "rate-limit",
                "TELEMETER_GUARDRAIL_MAX_QUERIES": "2",
                "TELEMETER_GUARDRAIL_WINDOW_SECONDS": "60",
            },
        ):
            gr.enforce("sum(up)", mode="instant")
            status = gr.rate_limit_status()
            self.assertEqual(status["queries_used_in_window"], 1)
            self.assertEqual(status["queries_remaining_in_window"], 1)
            gr.enforce("sum(up)", mode="instant")
            with self.assertRaises(gr.GuardrailViolation) as ctx:
                gr.enforce("sum(up)", mode="instant")
            self.assertEqual(ctx.exception.guardrail, "rate-limit")
            self.assertEqual(gr.rate_limit_status()["queries_remaining_in_window"], 0)
        gr.reset_rate_limit_for_tests()


class MaxRangeTest(unittest.TestCase):
    def test_rejects_long_range(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "TELEMETER_GUARDRAILS": "rate-limit",
                "TELEMETER_GUARDRAIL_MAX_RANGE_HOURS": "24",
                "TELEMETER_GUARDRAIL_MAX_QUERIES": "1000",
            },
        ):
            gr.reset_rate_limit_for_tests()
            with self.assertRaises(gr.GuardrailViolation) as ctx:
                gr.enforce("sum(up)", mode="range", hours=48)
            self.assertEqual(ctx.exception.guardrail, "max-range-hours")
        gr.reset_rate_limit_for_tests()


class RecipeQueriesPassDefault(unittest.TestCase):
    """Curated pack queries must pass static guardrails (rate limit off)."""

    def test_cnv_recipe_queries(self) -> None:
        from mcp_server.recipes import list_recipes, render_recipe_promql

        with mock.patch.dict(
            os.environ,
            {
                "TELEMETER_GUARDRAILS": (
                    "disallow-blanket-regex,disallow-unrestricted-selectors"
                ),
            },
        ):
            for r in list_recipes():
                for scope in ("external", "internal", "all"):
                    q = render_recipe_promql(r["id"], scope=scope)["promql"]
                    gr.enforce(q, mode="instant")


if __name__ == "__main__":
    unittest.main()
