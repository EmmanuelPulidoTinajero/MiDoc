"""Tier 2 F04: Medical Record Authorization & Validation Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_and_subscribe_doctor,
    register_doctor,
    register_patient,
)


class TestTier2F04MedicalRecordBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f04_01_doctor_cannot_read_record_without_consent(self) -> None:
        _, p_user = register_patient(self.client)
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok)
        self.assertEqual(resp.status, 403)

    def test_t2_f04_02_unsubscribed_doctor_with_consent_still_blocked(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_doctor(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        resp = self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok)
        self.assertIn(resp.status, (402, 403))

    def test_t2_f04_03_doctor_cannot_overwrite_patient_record(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.put("/api/records", {"notes": "Intento de sobrescritura"}, token=d_tok)
        self.assertEqual(resp.status, 403)

    def test_t2_f04_04_invalid_blood_type_sex_or_future_birth_date_rejected(self) -> None:
        p_tok, _ = register_patient(self.client)
        self.assertEqual(self.client.put("/api/records", {"bloodType": "ZZ+"}, token=p_tok).status, 400)
        self.assertEqual(self.client.put("/api/records", {"birthDate": "2099-01-01"}, token=p_tok).status, 400)
        self.assertEqual(self.client.put("/api/records", {"sex": "INVALIDO"}, token=p_tok).status, 400)

    def test_t2_f04_05_xss_payload_in_notes_and_allergies_stored_as_literal_text(self) -> None:
        p_tok, _ = register_patient(self.client)
        xss = "<img src=x onerror=alert(1)>"
        upd = self.client.put("/api/records", {"allergies": [xss], "notes": xss}, token=p_tok)
        self.assertEqual(upd.status, 200)
        got = self.client.get("/api/records", token=p_tok)
        self.assertEqual(got.data["notes"], xss)
        self.assertEqual(got.data["allergies"], [xss])
