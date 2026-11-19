"""Tier 1 F04: Patient-Owned Medical Record CRUD & Clinical History (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_and_subscribe_doctor,
    register_patient,
)


class TestTier1F04MedicalRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f04_01_patient_updates_full_medical_record(self) -> None:
        p_tok, _ = register_patient(self.client)
        payload = {
            "birthDate": "1995-05-12",
            "sex": "FEMENINO",
            "bloodType": "O+",
            "allergies": ["Polen", "Sulfa"],
            "chronicConditions": ["Rinitis"],
            "medications": ["Loratadina 10mg"],
            "notes": "Sin antecedentes quirúrgicos",
        }
        resp = self.client.put("/api/records", payload, token=p_tok)
        self.assertEqual(resp.status, 200, resp.text)
        for k, v in payload.items():
            self.assertEqual(resp.data.get(k), v)

    def test_t1_f04_02_patient_reads_own_medical_record(self) -> None:
        p_tok, _ = register_patient(self.client)
        self.client.put("/api/records", {"bloodType": "A+", "notes": "Lectura propia"}, token=p_tok)
        rec = self.client.get("/api/records", token=p_tok)
        self.assertEqual(rec.status, 200, rec.text)
        self.assertEqual(rec.data["bloodType"], "A+")
        self.assertEqual(rec.data["notes"], "Lectura propia")
        self.assertIsInstance(rec.data.get("consultations"), list)

    def test_t1_f04_03_record_persists_across_fresh_login_session(self) -> None:
        p_tok, p_user = register_patient(self.client)
        self.client.put("/api/records", {"allergies": ["Látex"], "notes": "Persistencia real"}, token=p_tok)
        login = self.client.post("/api/auth/login", {"email": p_user["email"], "password": p_user["password"]})
        self.assertEqual(login.status, 200)
        rec = self.client.get("/api/records", token=login.json_data["token"])
        self.assertEqual(rec.status, 200)
        self.assertEqual(rec.data["allergies"], ["Látex"])
        self.assertEqual(rec.data["notes"], "Persistencia real")

    def test_t1_f04_04_authorized_doctor_reads_patient_record(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.put("/api/records", {"notes": "Visible con consentimiento"}, token=p_tok)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        rec = self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok)
        self.assertEqual(rec.status, 200, rec.text)
        self.assertEqual(rec.data["notes"], "Visible con consentimiento")

    def test_t1_f04_05_utf8_spanish_characters_round_trip(self) -> None:
        p_tok, _ = register_patient(self.client)
        payload = {
            "allergies": ["Penicilina", "Ácaros"],
            "chronicConditions": ["Hipertensión arterial crónica"],
            "notes": "Evaluación pediátrica y seguimiento año 2026 — ñandú",
        }
        upd = self.client.put("/api/records", payload, token=p_tok)
        self.assertEqual(upd.status, 200, upd.text)
        got = self.client.get("/api/records", token=p_tok)
        self.assertEqual(got.data["allergies"], payload["allergies"])
        self.assertEqual(got.data["chronicConditions"], payload["chronicConditions"])
        self.assertEqual(got.data["notes"], payload["notes"])
