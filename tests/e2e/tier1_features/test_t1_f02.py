"""Tier 1 F02: Provider Directory Search, Sorting, Profile & UTC-6 Availability (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_doctor,
)


class TestTier1F02Directory(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f02_01_public_directory_lists_subscribed_providers_only(self) -> None:
        _, _, sub_id = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Visible E2E")
        _, _, unsub_id = register_doctor(self.client, name="Dr. Oculto E2E")
        resp = self.client.get("/api/doctors")
        self.assertEqual(resp.status, 200, resp.text)
        ids = {d["id"] for d in resp.data}
        self.assertIn(sub_id, ids)
        self.assertNotIn(unsub_id, ids)

    def test_t1_f02_02_search_filtering_specialty_location_and_q(self) -> None:
        _, _, id1 = register_and_subscribe_doctor(
            self.ctx,
            self.client,
            name="Dra. Cardio Norte",
            specialty="Cardiología",
            location="Monterrey Centro",
            city="Monterrey",
        )
        _, _, id2 = register_and_subscribe_doctor(
            self.ctx,
            self.client,
            name="Dr. Derma Sur",
            specialty="Dermatología",
            location="Coyoacán",
            city="CDMX",
        )
        resp = self.client.get(
            "/api/doctors",
            query={"specialty": "Cardiología", "location": "Monterrey", "q": "Cardio"},
        )
        self.assertEqual(resp.status, 200, resp.text)
        ids = {d["id"] for d in resp.data}
        self.assertIn(id1, ids)
        self.assertNotIn(id2, ids)

    def test_t1_f02_03_directory_sorting_by_price_and_availability(self) -> None:
        _, _, cheap_id = register_and_subscribe_doctor(
            self.ctx, self.client, name="Dr. Económico", specialty="SortSpecX", price=300
        )
        _, _, pricey_id = register_and_subscribe_doctor(
            self.ctx, self.client, name="Dr. Costoso", specialty="SortSpecX", price=800
        )
        resp = self.client.get("/api/doctors", query={"specialty": "SortSpecX", "sort": "PRICE_ASC"})
        self.assertEqual(resp.status, 200, resp.text)
        ordered = [d["id"] for d in resp.data]
        self.assertIn(cheap_id, ordered)
        self.assertIn(pricey_id, ordered)
        self.assertLess(ordered.index(cheap_id), ordered.index(pricey_id))

    def test_t1_f02_04_public_profile_includes_schedule_and_active_promotions(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        today = future_date_str(0)
        end_d = future_date_str(5)
        promo = self.client.post(
            "/api/doctor/promotions",
            {"title": "Descuento E2E", "description": "Primera visita", "discountPercent": 15, "start": today, "end": end_d},
            token=d_tok,
        )
        self.assertEqual(promo.status, 201, promo.text)
        prof = self.client.get(f"/api/doctors/{d_id}")
        self.assertEqual(prof.status, 200, prof.text)
        self.assertTrue(len(prof.data.get("schedule", [])) >= 1)
        self.assertTrue(any(p["id"] == promo.data["id"] for p in prof.data.get("promotions", [])))

    def test_t1_f02_05_utc_minus_6_availability_slots(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(
            self.ctx, self.client, duration_min=30, with_schedule=False
        )
        blocks = [{"day": d, "start": "09:00", "end": "11:00"} for d in range(1, 8)]
        sch = self.client.put("/api/doctor/schedule", {"blocks": blocks}, token=d_tok)
        self.assertEqual(sch.status, 200, sch.text)

        target_date = future_date_str(3)
        avail = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": target_date})
        self.assertEqual(avail.status, 200, avail.text)
        slots = avail.data["slots"]
        self.assertEqual(len(slots), 4)
        for s in slots:
            self.assertTrue(s.endswith("-06:00"), f"Expected UTC-6 slot, got {s}")
