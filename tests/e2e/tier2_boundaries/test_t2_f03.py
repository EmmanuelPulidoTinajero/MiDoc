"""Tier 2 F03: Schedule & Appointment Boundaries (5 tests)."""
from __future__ import annotations

from datetime import timedelta
import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_patient,
    utc6_now,
)


class TestTier2F03AppointmentBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f03_01_booking_over_90_days_rejected(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        dt_91 = (utc6_now() + timedelta(days=91)).replace(hour=10, minute=0, second=0, microsecond=0)
        resp = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": dt_91.isoformat()}, token=p_tok)
        self.assertEqual(resp.status, 400, resp.text)

    def test_t2_f03_02_booking_in_past_or_unscheduled_hour_rejected(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        yesterday = (utc6_now() - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        self.assertEqual(
            self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": yesterday.isoformat()}, token=p_tok).status,
            400,
        )
        past = (utc6_now() - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        self.assertIn(
            self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": past.isoformat()}, token=p_tok).status,
            (400, 409),
        )
        unsched = (utc6_now() + timedelta(days=3)).replace(hour=3, minute=0, second=0, microsecond=0)
        self.assertIn(
            self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": unsched.isoformat()}, token=p_tok).status,
            (400, 409),
        )

    def test_t2_f03_03_role_violations_doctor_booking_and_patient_confirming(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        slot = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"][0]
        doc_book = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot}, token=d_tok)
        self.assertEqual(doc_book.status, 403)
        aid = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot}, token=p_tok).data["id"]
        pat_conf = self.client.put(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}, token=p_tok)
        self.assertEqual(pat_conf.status, 403)

    def test_t2_f03_04_reschedule_with_zero_slots_or_occupied_slot_fails(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p1_tok, _ = register_patient(self.client)
        p2_tok, _ = register_patient(self.client)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        a1 = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p1_tok).data
        self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[1]}, token=p2_tok)
        occ = self.client.put(f"/api/appointments/{a1['id']}/reschedule", {"dateTime": slots[1]}, token=p1_tok)
        self.assertIn(occ.status, (400, 409))
        self.client.put("/api/doctor/schedule", {"blocks": []}, token=d_tok)
        zero = self.client.put(f"/api/appointments/{a1['id']}/reschedule", {"dateTime": slots[2]}, token=p1_tok)
        self.assertIn(zero.status, (400, 409))
        got = self.client.get(f"/api/appointments/{a1['id']}", token=p1_tok)
        self.assertEqual(got.data["dateTime"], a1["dateTime"])

    def test_t2_f03_05_third_party_cannot_access_or_modify_other_patient_appointment(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p1_tok, _ = register_patient(self.client)
        p2_tok, _ = register_patient(self.client)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        aid = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p1_tok).data["id"]
        self.assertIn(self.client.get(f"/api/appointments/{aid}", token=p2_tok).status, (403, 404))
        self.assertIn(
            self.client.put(f"/api/appointments/{aid}/status", {"status": "CANCELADA"}, token=p2_tok).status,
            (403, 404),
        )
        self.assertIn(
            self.client.put(f"/api/appointments/{aid}/reschedule", {"dateTime": slots[1]}, token=p2_tok).status,
            (403, 404),
        )
