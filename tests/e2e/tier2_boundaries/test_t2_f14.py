"""Tier 2 F14: CloudWatch Telemetry Failure & Alarm Threshold Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.aws_inspector import (
    collect_emf_telemetry,
    get_tf_content,
    wait_for_cloudwatch_metrics,
)
from tests.e2e.harness.config import get_active_context


class TestTier2F14ObservabilityBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f14_01_login_failure_emits_login_failures_emf_metric(self) -> None:
        resp = self.client.post("/api/auth/login", {"email": "nobody@example.invalid", "password": "BadPassword1"})
        self.assertEqual(resp.status, 401)
        if self.ctx.mode == "self-test":
            metrics = collect_emf_telemetry(self.ctx)
            self.assertTrue(any("LoginFailures" in m for m in metrics))
        elif self.ctx.target == "cloud":
            names = wait_for_cloudwatch_metrics(self.ctx, ("LoginFailures",), timeout_s=90.0)
            self.assertIn("LoginFailures", names, f"LoginFailures missing in CloudWatch: {sorted(names)}")

    def test_t2_f14_02_5xx_alarm_threshold_and_missing_data_config(self) -> None:
        mon = get_tf_content(self.ctx, "monitoring.tf")
        self.assertIn("ServerErrors", mon)
        self.assertRegex(mon, r"threshold\s*=\s*5\b")
        self.assertRegex(mon, r"period\s*=\s*300\b")
        self.assertRegex(mon, r'treat_missing_data\s*=\s*"notBreaching"')

    def test_t2_f14_03_latency_p95_alarm_configuration(self) -> None:
        mon = get_tf_content(self.ctx, "monitoring.tf")
        self.assertIn("RequestLatencyMs", mon)
        self.assertRegex(mon, r'extended_statistic\s*=\s*"p95"')
        self.assertRegex(mon, r"threshold\s*=\s*3000\b")
        self.assertRegex(mon, r"evaluation_periods\s*=\s*2\b")

    def test_t2_f14_04_webhook_rejection_emits_payment_failed_telemetry(self) -> None:
        if self.ctx.stripe_mode == "simulado":
            # Sin integración Stripe real no hay webhooks que rechazar ni telemetría asociada.
            self.skipTest("Webhooks de Stripe no aplican en modo simulado")
        bad = self.client.post(
            "/api/webhooks/stripe",
            raw_bytes=b'{"type":"checkout.session.completed"}',
            headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=bad"},
        )
        self.assertIn(bad.status, (400, 401))
        if self.ctx.mode == "self-test":
            metrics = collect_emf_telemetry(self.ctx)
            self.assertTrue(any("PaymentFailed" in m for m in metrics))
        elif self.ctx.target == "cloud":
            names = wait_for_cloudwatch_metrics(self.ctx, ("PaymentFailed",), timeout_s=90.0)
            self.assertIn("PaymentFailed", names, f"PaymentFailed missing in CloudWatch: {sorted(names)}")

    def test_t2_f14_05_metrics_emission_disabled_never_breaks_http_response(self) -> None:
        metricas = (self.ctx.repo_root / "backend" / "src" / "metricas.py").read_text(encoding="utf-8")
        self.assertIn("METRICS_ENABLED", metricas)
        health = self.client.get("/health")
        self.assertEqual(health.status, 200)
