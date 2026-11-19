"""Tier 2 F10: Promotions Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_doctor,
    register_patient,
)


class TestTier2F10PromotionsBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f10_01_promotion_discount_out_of_range_rejected(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        for bad in (0, 91, -10):
            resp = self.client.post(
                "/api/doctor/promotions",
                {"title": "Bad", "discountPercent": bad, "start": future_date_str(0), "end": future_date_str(2)},
                token=d_tok,
            )
            self.assertEqual(resp.status, 400, f"Discount {bad} should fail 400")

    def test_t2_f10_02_inverted_promotion_date_range_rejected(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.post(
            "/api/doctor/promotions",
            {"title": "Invertida", "discountPercent": 20, "start": future_date_str(10), "end": future_date_str(2)},
            token=d_tok,
        )
        self.assertEqual(resp.status, 400)

    def test_t2_f10_03_unsubscribed_doctor_and_paciente_cannot_manage_promotions(self) -> None:
        p_tok, _ = register_patient(self.client)
        unsub_tok, _, _ = register_doctor(self.client)
        payload = {"title": "Promo", "discountPercent": 15, "start": future_date_str(0), "end": future_date_str(2)}
        self.assertEqual(self.client.post("/api/doctor/promotions", payload, token=p_tok).status, 403)
        self.assertEqual(self.client.post("/api/doctor/promotions", payload, token=unsub_tok).status, 402)

    def test_t2_f10_04_cross_doctor_promotion_deletion_blocked(self) -> None:
        d1_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. P1")
        d2_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. P2")
        promo = self.client.post(
            "/api/doctor/promotions",
            {"title": "Propia", "discountPercent": 20, "start": future_date_str(0), "end": future_date_str(2)},
            token=d1_tok,
        ).data
        resp = self.client.delete(f"/api/doctor/promotions/{promo['id']}", token=d2_tok)
        self.assertIn(resp.status, (403, 404))

    def test_t2_f10_05_expired_promotion_excluded_from_public_directory_and_profile(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        promo = self.client.post(
            "/api/doctor/promotions",
            {"title": "Vencida Ayer", "discountPercent": 30, "start": future_date_str(-7), "end": future_date_str(-1)},
            token=d_tok,
        ).data
        own = self.client.get("/api/doctor/promotions", token=d_tok).data
        self.assertTrue(any(p["id"] == promo["id"] for p in own))
        prof = self.client.get(f"/api/doctors/{d_id}").data
        self.assertFalse(any(p["id"] == promo["id"] for p in prof.get("promotions", [])))
        listing = self.client.get("/api/doctors").data
        doc_row = next(d for d in listing if d["id"] == d_id)
        self.assertFalse(any(p["id"] == promo["id"] for p in doc_row.get("promotions", [])))
