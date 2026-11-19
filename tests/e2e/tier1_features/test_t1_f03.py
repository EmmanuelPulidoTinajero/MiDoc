"""Tier 1 F03: Weekly Schedule & Appointments Lifecycle (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_patient,
)


class TestTier1F03Appointments(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f03_01_configure_weekly_schedule(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client, with_schedule=False)
        blocks = [{"day": 1, "start": "10:00", "end": "12:00"}, {"day": 3, "start": "15:00", "end": "17:00"}]
        resp = self.client.put("/api/doctor/schedule", {"blocks": blocks}, token=d_tok)
        self.assertEqual(resp.status, 200, resp.text)
        self.assertEqual(len(resp.data), 2)
        prof = self.client.get(f"/api/doctors/{d_id}")
        self.assertEqual(prof.status, 200)
        self.assertEqual(len(prof.data["schedule"]), 2)

    def test_t1_f03_02_patient_books_available_slot(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        day = future_date_str(3)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": day}).data["slots"]
        booked = self.client.post(
            "/api/appointments",
            {"doctorId": d_id, "dateTime": slots[0], "reason": "Chequeo anual"},
            token=p_tok,
        )
        self.assertEqual(booked.status, 201, booked.text)
        self.assertEqual(booked.data["status"], "PENDIENTE")
        aid = booked.data["id"]
        self.assertEqual(self.client.get(f"/api/appointments/{aid}", token=p_tok).status, 200)
        self.assertEqual(self.client.get(f"/api/appointments/{aid}", token=d_tok).status, 200)

    def test_t1_f03_03_doctor_confirms_appointment(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        day = future_date_str(3)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": day}).data["slots"]
        aid = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p_tok).data["id"]
        conf = self.client.put(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}, token=d_tok)
        self.assertEqual(conf.status, 200, conf.text)
        self.assertEqual(conf.data["status"], "CONFIRMADA")

    def test_t1_f03_04_reschedule_frees_old_slot_and_occupies_new_slot(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        day = future_date_str(3)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": day}).data["slots"]
        s0, s1 = slots[0], slots[1]
        aid = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": s0}, token=p_tok).data["id"]
        res = self.client.put(f"/api/appointments/{aid}/reschedule", {"dateTime": s1}, token=p_tok)
        self.assertEqual(res.status, 200, res.text)
        after = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": day}).data["slots"]
        self.assertIn(s0, after)
        self.assertNotIn(s1, after)

    def test_t1_f03_05_cancel_appointment_frees_slot(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        day = future_date_str(3)
        s0 = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": day}).data["slots"][0]
        aid = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": s0}, token=p_tok).data["id"]
        canc = self.client.put(f"/api/appointments/{aid}/status", {"status": "CANCELADA"}, token=p_tok)
        self.assertEqual(canc.status, 200, canc.text)
        self.assertEqual(canc.data["status"], "CANCELADA")
        after = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": day}).data["slots"]
        self.assertIn(s0, after)
