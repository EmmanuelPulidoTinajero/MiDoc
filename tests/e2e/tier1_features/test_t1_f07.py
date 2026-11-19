"""Tier 1 F07: Real Stripe $20/mo Subscription Checkout, Confirm & Webhook (5 tests)."""
from __future__ import annotations

from datetime import date
import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_doctor,
    subscribe_doctor_via_stripe,
)


class TestTier1F07StripeSubscriptions(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f07_01_create_stripe_checkout_session(self) -> None:
        d_tok, _, d_id = register_doctor(self.client)
        chk = self.client.post("/api/subscriptions/checkout", {}, token=d_tok)
        self.assertEqual(chk.status, 201, chk.text)
        data = chk.data
        self.assertTrue(str(data.get("sessionId", "")).startswith("cs_"))
        self.assertTrue(str(data.get("checkoutUrl", "")).startswith("http"))
        self.assertIn(data.get("mode"), ("test", "live"))
        self.assertEqual(float(data.get("amountUsd")), 20.0)
        if self.ctx.stripe_mock is not None:
            reqs = [
                r
                for r in self.ctx.stripe_mock.recorded_requests
                if r["method"] == "POST"
                and r["path"] == "/v1/checkout/sessions"
                and r["form"].get("metadata[doctorId]") == d_id
            ]
            self.assertTrue(reqs, "Backend did not call Stripe POST /v1/checkout/sessions")
            self.assertEqual(reqs[-1]["form"].get("line_items[0][price_data][unit_amount]"), "2000")

    def test_t1_f07_02_confirm_paid_stripe_session(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        res = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok, brand="mastercard", last4="5555")
        sub = res["subscription"]
        self.assertEqual(sub["status"], "ACTIVA")
        self.assertTrue(sub["active"])
        start_d = date.fromisoformat(sub["start"])
        end_d = date.fromisoformat(sub["end"])
        self.assertEqual((end_d - start_d).days, 29)
        if self.ctx.stripe_mode == "mock":
            self.assertEqual(sub["cardLast4"], "5555")

    def test_t1_f07_03_signed_stripe_webhook_activates_subscription(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        subscribe_doctor_via_stripe(self.ctx, self.client, d_tok, via_webhook=True)
        subs = self.client.get("/api/subscriptions", token=d_tok)
        self.assertEqual(subs.status, 200, subs.text)
        self.assertIsInstance(subs.data, dict)
        latest = subs.data.get("subscription")
        self.assertIsNotNone(latest)
        self.assertTrue(latest["active"])
        self.assertEqual(latest["status"], "ACTIVA")

    def test_t1_f07_04_clinica_subscription_status_and_payment_history(self) -> None:
        c_tok, _, _ = register_doctor(self.client, role="CLINICA", name="Clínica Stripe")
        subscribe_doctor_via_stripe(self.ctx, self.client, c_tok)
        subs = self.client.get("/api/subscriptions", token=c_tok)
        self.assertEqual(subs.status, 200, subs.text)
        self.assertIsInstance(subs.data, dict)
        latest = subs.data.get("subscription")
        self.assertIsNotNone(latest)
        self.assertTrue(latest["active"])
        self.assertIn(subs.data.get("paymentMode"), ("test", "live"))
        self.assertTrue(subs.data.get("history") or latest.get("paymentRef"))

    def test_t1_f07_05_early_renewal_chains_30_days_onto_existing_end(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        first = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        end1 = date.fromisoformat(first["subscription"]["end"])
        second = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        end2 = date.fromisoformat(second["subscription"]["end"])
        self.assertEqual((end2 - end1).days, 30)
