"""Tier 2 F07: Stripe Subscription Negative, HMAC Webhook & Legacy Retirement (5 tests)."""
from __future__ import annotations

import time
import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import register_doctor, register_patient


class TestTier2F07StripeBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f07_01_legacy_simulated_payment_endpoint_is_retired(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        resp = self.client.post(
            "/api/subscriptions/pay",
            {"cardHolder": "Legacy Sim", "cardNumber": "4242424242424242", "expMonth": 12, "expYear": 2030, "cvv": "123"},
            token=d_tok,
        )
        self.assertIn(resp.status, (404, 410), f"Legacy /pay must be retired (410/404), got {resp.status}")
        sub = self.client.get("/api/subscriptions", token=d_tok)
        self.assertEqual(sub.status, 200)
        self.assertIsInstance(sub.data, dict)
        self.assertIsNone(sub.data["subscription"])
        self.assertEqual(sub.data["history"], [])

    def test_t2_f07_02_paciente_cannot_checkout_or_confirm_subscription(self) -> None:
        p_tok, _ = register_patient(self.client)
        self.assertEqual(self.client.post("/api/subscriptions/checkout", {}, token=p_tok).status, 403)
        self.assertEqual(self.client.post("/api/subscriptions/confirm", {"sessionId": "cs_test_123"}, token=p_tok).status, 403)

    def test_t2_f07_03_confirm_unpaid_or_other_doctors_session_rejected(self) -> None:
        d1_tok, _, _ = register_doctor(self.client, name="Dr. Uno")
        d2_tok, _, _ = register_doctor(self.client, name="Dr. Dos")
        chk = self.client.post("/api/subscriptions/checkout", {}, token=d1_tok)
        self.assertEqual(chk.status, 201)
        sid = chk.data["sessionId"]

        if self.ctx.stripe_mode != "simulado":
            # En modo simulado las sesiones nacen pagadas: el caso "no pagada" no aplica.
            unpaid = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d1_tok)
            self.assertIn(unpaid.status, (400, 402), unpaid.text)

        if self.ctx.stripe_mock is not None:
            self.ctx.stripe_mock.complete_session(sid)
        hijack = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d2_tok)
        self.assertIn(hijack.status, (403, 404), hijack.text)
        d2_sub = self.client.get("/api/subscriptions", token=d2_tok)
        self.assertEqual(d2_sub.status, 200)
        self.assertIsNone(d2_sub.data["subscription"])
        self.assertEqual(d2_sub.data["history"], [])

    def test_t2_f07_04_invalid_tampered_wrong_secret_expired_webhook_signature_rejected(self) -> None:
        if self.ctx.stripe_mode == "simulado":
            # Los webhooks firmados son una integración de Stripe real; en modo simulado no existen.
            self.skipTest("Webhooks de Stripe no aplican en modo simulado")
        d_tok, _, _ = register_doctor(self.client)
        chk = self.client.post("/api/subscriptions/checkout", {}, token=d_tok)
        self.assertEqual(chk.status, 201)
        sid = chk.data["sessionId"]
        if self.ctx.stripe_mock is not None:
            s_missing, _ = self.ctx.stripe_mock.send_webhook(self.ctx.api_url, sid, omit_signature=True)
            s_wrong, _ = self.ctx.stripe_mock.send_webhook(self.ctx.api_url, sid, secret_override="whsec_wrong_key")
            s_tamper, _ = self.ctx.stripe_mock.send_webhook(self.ctx.api_url, sid, tamper_body=True)
            s_expired, _ = self.ctx.stripe_mock.send_webhook(
                self.ctx.api_url, sid, timestamp_override=int(time.time()) - 900
            )
            for code in (s_missing, s_wrong, s_tamper, s_expired):
                self.assertIn(code, (400, 401), f"Expected 400/401 on bad webhook sig, got {code}")
            # Ensure negative webhooks did NOT mutate unpaid session into paid
            unpaid_confirm = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok)
            self.assertIn(unpaid_confirm.status, (400, 402), unpaid_confirm.text)
        else:
            resp = self.client.post(
                "/api/webhooks/stripe",
                raw_bytes=b'{"type":"checkout.session.completed"}',
                headers={"Content-Type": "application/json", "Stripe-Signature": "t=100,v1=deadbeef"},
            )
            self.assertIn(resp.status, (400, 401))

    def test_t2_f07_05_invalid_success_or_cancel_url_rejected_or_sanitized(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        bad_js = self.client.post(
            "/api/subscriptions/checkout",
            {"successUrl": "javascript:alert(1)", "cancelUrl": "https://evil.example/c"},
            token=d_tok,
        )
        bad_http = self.client.post(
            "/api/subscriptions/checkout",
            {"successUrl": "http://untrusted.example/s"},
            token=d_tok,
        )
        self.assertEqual(bad_js.status, 400)
        self.assertEqual(bad_http.status, 400)
