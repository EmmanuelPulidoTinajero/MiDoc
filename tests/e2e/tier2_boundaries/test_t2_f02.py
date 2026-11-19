"""Tier 2 F02: Directory Search & Availability Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import register_and_subscribe_doctor, register_doctor


class TestTier2F02DirectoryBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f02_01_xss_and_sqli_in_search_query_safe(self) -> None:
        resp = self.client.get(
            "/api/doctors",
            query={"q": "' OR 1=1--", "specialty": "<script>alert(1)</script>", "location": "'; DROP TABLE cita;--"},
        )
        self.assertEqual(resp.status, 200, resp.text)
        self.assertIsInstance(resp.data, list)

    def test_t2_f02_02_unsubscribed_doctor_hidden_from_directory_and_profile(self) -> None:
        _, _, unsub_id = register_doctor(self.client, name="Dr. Sin Pago")
        listing = self.client.get("/api/doctors")
        self.assertEqual(listing.status, 200)
        self.assertFalse(any(d["id"] == unsub_id for d in listing.data))
        prof = self.client.get(f"/api/doctors/{unsub_id}")
        self.assertEqual(prof.status, 404)

    def test_t2_f02_03_nonexistent_doctor_uuid_returns_404(self) -> None:
        resp = self.client.get("/api/doctors/00000000-0000-0000-0000-999999999999")
        self.assertEqual(resp.status, 404)
        self.assertTrue(resp.error)

    def test_t2_f02_04_invalid_date_format_on_availability(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.assertEqual(self.client.get(f"/api/doctors/{d_id}/availability", query={"date": "18-11-2026"}).status, 400)
        self.assertEqual(self.client.get(f"/api/doctors/{d_id}/availability", query={"date": "invalid"}).status, 400)

    def test_t2_f02_05_past_date_availability_empty_or_400(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": "2020-01-01"})
        self.assertIn(resp.status, (200, 400), resp.text)
        if resp.status == 200:
            self.assertEqual(resp.data["slots"], [])
