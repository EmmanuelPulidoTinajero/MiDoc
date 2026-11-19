"""Tier 2 F08: Consultations & Prescriptions Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    prepare_started_appointments,
    register_and_subscribe_doctor,
    register_patient,
    setup_started_appointment,
)


class TestTier2F08ConsultationBoundaries(unittest.TestCase):
    _prebooked: list[dict] = []

    @classmethod
    def setUpClass(cls) -> None:
        ctx = get_active_context()
        if ctx.mode == "live":
            cls._prebooked = prepare_started_appointments(ctx, ctx.client(), 3)

    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f08_01_consultation_on_future_appointment_returns_409(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, p_user = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        slot = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(2)}).data["slots"][0]
        aid = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot}, token=p_tok).data["id"]
        resp = self.client.post(
            "/api/consultations",
            {"patientId": p_user["id"], "appointmentId": aid, "diagnosis": "Prematura", "treatment": "Ninguno"},
            token=d_tok,
        )
        self.assertEqual(resp.status, 409, resp.text)

    def test_t2_f08_02_duplicate_consultation_returns_409(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        payload = {
            "patientId": bundle["patientId"],
            "appointmentId": bundle["appointment"]["id"],
            "diagnosis": "Resfriado común",
            "treatment": "Reposo 48h",
        }
        self.assertEqual(self.client.post("/api/consultations", payload, token=bundle["doctorToken"]).status, 201)
        dup = self.client.post("/api/consultations", payload, token=bundle["doctorToken"])
        self.assertEqual(dup.status, 409)

    def test_t2_f08_03_consultation_on_cancelled_or_other_doctors_appointment_rejected(self) -> None:
        d1_tok, _, d1_id = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. A")
        d2_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. B")
        p_tok, p_user = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d1_id, "granted": True}, token=p_tok)
        slot = self.client.get(f"/api/doctors/{d1_id}/availability", query={"date": future_date_str(2)}).data["slots"][0]
        aid = self.client.post("/api/appointments", {"doctorId": d1_id, "dateTime": slot}, token=p_tok).data["id"]
        wrong_doc = self.client.post(
            "/api/consultations",
            {"patientId": p_user["id"], "appointmentId": aid, "diagnosis": "Ajeno", "treatment": "N/A"},
            token=d2_tok,
        )
        self.assertIn(wrong_doc.status, (403, 404))
        self.client.put(f"/api/appointments/{aid}/status", {"status": "CANCELADA"}, token=p_tok)
        canc = self.client.post(
            "/api/consultations",
            {"patientId": p_user["id"], "appointmentId": aid, "diagnosis": "Cancelada", "treatment": "N/A"},
            token=d1_tok,
        )
        self.assertEqual(canc.status, 409)

    def test_t2_f08_04_consultation_with_revoked_consent_or_empty_diagnosis_rejected(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        short_diag = self.client.post(
            "/api/consultations",
            {"patientId": bundle["patientId"], "appointmentId": bundle["appointment"]["id"], "diagnosis": "a", "treatment": "Reposo"},
            token=bundle["doctorToken"],
        )
        self.assertEqual(short_diag.status, 400)
        self.client.post("/api/consents", {"doctorId": bundle["doctorId"], "granted": False}, token=bundle["patientToken"])
        no_cons = self.client.post(
            "/api/consultations",
            {"patientId": bundle["patientId"], "appointmentId": bundle["appointment"]["id"], "diagnosis": "Gripe", "treatment": "Reposo"},
            token=bundle["doctorToken"],
        )
        self.assertEqual(no_cons.status, 403)

    def test_t2_f08_05_unauthorized_third_party_and_revoked_doctor_blocked_from_prescription(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        cons = self.client.post(
            "/api/consultations",
            {"patientId": bundle["patientId"], "appointmentId": bundle["appointment"]["id"], "diagnosis": "Otitis", "treatment": "Gotas"},
            token=bundle["doctorToken"],
        )
        rx_id = cons.data["prescriptionId"]
        other_tok, _ = register_patient(self.client)
        self.assertEqual(self.client.get(f"/api/prescriptions/{rx_id}", token=other_tok).status, 404)
        self.client.post("/api/consents", {"doctorId": bundle["doctorId"], "granted": False}, token=bundle["patientToken"])
        self.assertEqual(self.client.get(f"/api/prescriptions/{rx_id}", token=bundle["doctorToken"]).status, 403)
