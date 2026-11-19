"""Tier 1 F17: Traceability Docs & Cloud Lifecycle Contracts (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.aws_inspector import get_doc_text, resolve_markdown_links
from tests.e2e.harness.config import get_active_context


class TestTier1F17DocsAndLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f17_01_evaluacion_integral_exists_with_r1_r2_matrix(self) -> None:
        text = get_doc_text(self.ctx, "docs/EVALUACION-INTEGRAL.md")
        self.assertIsNotNone(text, "Missing docs/EVALUACION-INTEGRAL.md")
        assert text is not None
        self.assertIn("REQ-F1", text)
        self.assertIn("REQ-T2", text)

    def test_t1_f17_02_pagos_stripe_justifies_stripe_and_test_live_switch(self) -> None:
        text = get_doc_text(self.ctx, "docs/PAGOS-STRIPE.md")
        self.assertIsNotNone(text, "Missing docs/PAGOS-STRIPE.md")
        assert text is not None
        self.assertIn("PayPal", text)
        self.assertIn("Stripe", text)
        self.assertIn("sk_test_", text)
        self.assertIn("sk_live_", text)

    def test_t1_f17_03_cierre_and_observability_docs_exist_and_links_resolve(self) -> None:
        cierre = get_doc_text(self.ctx, "docs/CIERRE-AWS.md")
        obs = get_doc_text(self.ctx, "docs/OBSERVABILIDAD-Y-CICD.md")
        self.assertIsNotNone(cierre, "Missing docs/CIERRE-AWS.md")
        self.assertIsNotNone(obs, "Missing docs/OBSERVABILIDAD-Y-CICD.md")
        broken = resolve_markdown_links(
            self.ctx,
            ["README.md", "docs/API.md", "docs/DEPLOYMENT.md", "docs/CIERRE-AWS.md", "docs/OBSERVABILIDAD-Y-CICD.md"],
        )
        self.assertEqual(broken, [], f"Broken relative markdown links: {broken}")

    def test_t1_f17_04_api_and_readme_document_real_stripe_endpoints(self) -> None:
        api_md = get_doc_text(self.ctx, "docs/API.md") or ""
        readme = get_doc_text(self.ctx, "README.md") or ""
        self.assertIn("/api/subscriptions/checkout", api_md)
        self.assertIn("/api/subscriptions/confirm", api_md)
        self.assertIn("/api/webhooks/stripe", api_md)
        self.assertNotIn("pago simulado", readme.lower())

    def test_t1_f17_05_health_and_report_schema_ready(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status, 200, health.text)
        self.assertEqual(health.json_data.get("status"), "ok")
        self.assertEqual(health.json_data.get("service"), "midoc-api")
