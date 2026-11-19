"""Tier 1 F10: Provider Promotions CRUD & Marketplace Discount Display (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
)


class TestTier1F10Promotions(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f10_01_create_promotion(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.post(
            "/api/doctor/promotions",
            {
                "title": "Check-up 20%",
                "description": "Descuento de temporada",
                "discountPercent": 20,
                "start": future_date_str(0),
                "end": future_date_str(7),
            },
            token=d_tok,
        )
        self.assertEqual(resp.status, 201, resp.text)
        self.assertTrue(resp.data.get("id"))
        self.assertTrue(resp.data.get("active"))

    def test_t1_f10_02_list_own_promotions(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        p_act = self.client.post(
            "/api/doctor/promotions",
            {"title": "Activa", "discountPercent": 15, "start": future_date_str(0), "end": future_date_str(3)},
            token=d_tok,
        ).data
        p_past = self.client.post(
            "/api/doctor/promotions",
            {"title": "Pasada", "discountPercent": 15, "start": future_date_str(-10), "end": future_date_str(-5)},
            token=d_tok,
        ).data
        lst = self.client.get("/api/doctor/promotions", token=d_tok)
        self.assertEqual(lst.status, 200)
        ids = {p["id"] for p in lst.data}
        self.assertIn(p_act["id"], ids)
        self.assertIn(p_past["id"], ids)

    def test_t1_f10_03_active_promotion_displayed_publicly(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_act = self.client.post(
            "/api/doctor/promotions",
            {"title": "Visible Hoy", "discountPercent": 25, "start": future_date_str(0), "end": future_date_str(5)},
            token=d_tok,
        ).data
        p_past = self.client.post(
            "/api/doctor/promotions",
            {"title": "Expirada", "discountPercent": 25, "start": future_date_str(-10), "end": future_date_str(-2)},
            token=d_tok,
        ).data
        prof = self.client.get(f"/api/doctors/{d_id}")
        self.assertEqual(prof.status, 200)
        pub_ids = {p["id"] for p in prof.data.get("promotions", [])}
        self.assertIn(p_act["id"], pub_ids)
        self.assertNotIn(p_past["id"], pub_ids)

    def test_t1_f10_04_delete_promotion_removes_from_public_profile(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        promo = self.client.post(
            "/api/doctor/promotions",
            {"title": "Temporal", "discountPercent": 10, "start": future_date_str(0), "end": future_date_str(2)},
            token=d_tok,
        ).data
        dele = self.client.delete(f"/api/doctor/promotions/{promo['id']}", token=d_tok)
        self.assertEqual(dele.status, 200)
        prof = self.client.get(f"/api/doctors/{d_id}")
        self.assertFalse(any(p["id"] == promo["id"] for p in prof.data.get("promotions", [])))

    def test_t1_f10_05_clinica_promotion_discount_boundaries_1_and_90(self) -> None:
        c_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, role="CLINICA", name="Clínica Promos")
        r1 = self.client.post(
            "/api/doctor/promotions",
            {"title": "Min 1%", "discountPercent": 1, "start": future_date_str(0), "end": future_date_str(1)},
            token=c_tok,
        )
        r90 = self.client.post(
            "/api/doctor/promotions",
            {"title": "Max 90%", "discountPercent": 90, "start": future_date_str(0), "end": future_date_str(1)},
            token=c_tok,
        )
        self.assertEqual(r1.status, 201, r1.text)
        self.assertEqual(r90.status, 201, r90.text)
