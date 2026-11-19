"""Tier 1 F08: Authorized Patients, Consultations & S3 Rx PDF (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    prepare_started_appointments,
    register_and_subscribe_doctor,
    register_patient,
    s3_is_configured,
    setup_started_appointment,
    verify_pdf_bytes,
)


class TestTier1F08ConsultationsAndRx(unittest.TestCase):
    _prebooked: list[dict] = []

    @classmethod
    def setUpClass(cls) -> None:
        ctx = get_active_context()
        if ctx.mode == "live":
            cls._prebooked = prepare_started_appointments(ctx, ctx.client(), 4)

    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f08_01_authorized_patients_list(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p1_tok, p1 = register_patient(self.client, name="Paciente Autorizado")
        _, p2 = register_patient(self.client, name="Paciente Sin Permiso")
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p1_tok)
        pts = self.client.get("/api/doctor/patients", token=d_tok)
        self.assertEqual(pts.status, 200, pts.text)
        ids = {p["patientId"] for p in pts.data}
        self.assertIn(p1["id"], ids)
        self.assertNotIn(p2["id"], ids)

    def test_t1_f08_02_register_consultation_atomically_completes_appointment(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": bundle["patientId"],
                "appointmentId": bundle["appointment"]["id"],
                "diagnosis": "Faringitis aguda viral",
                "treatment": "Reposo e hidratación oral",
                "notes": "Control en 7 días",
            },
            token=bundle["doctorToken"],
        )
        self.assertEqual(cons.status, 201, cons.text)
        self.assertTrue(cons.data.get("prescriptionId"))
        appt = self.client.get(f"/api/appointments/{bundle['appointment']['id']}", token=bundle["patientToken"])
        self.assertEqual(appt.status, 200)
        self.assertEqual(appt.data["status"], "COMPLETADA")

    def test_t1_f08_03_generated_rx_pdf_stored_and_downloadable(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": bundle["patientId"],
                "appointmentId": bundle["appointment"]["id"],
                "diagnosis": "Cefalea tensional",
                "treatment": "Paracetamol 500mg cada 8h",
            },
            token=bundle["doctorToken"],
        )
        self.assertEqual(cons.status, 201, cons.text)
        rx_id = cons.data["prescriptionId"]
        rx = self.client.get(f"/api/prescriptions/{rx_id}", token=bundle["patientToken"])
        self.assertEqual(rx.status, 200, rx.text)
        if not s3_is_configured(self.ctx):
            self.assertFalse(rx.data.get("hasPdf"))
            self.assertIsNone(rx.data.get("downloadUrl"))
            return
        self.assertTrue(rx.data.get("downloadUrl"), f"Missing presigned downloadUrl: {rx.data}")
        dl = self.client.download_url(rx.data["downloadUrl"])
        self.assertEqual(dl.status, 200)
        verify_pdf_bytes(dl.body_bytes)

    def test_t1_f08_04_consultation_appears_in_patient_clinical_history(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": bundle["patientId"],
                "appointmentId": bundle["appointment"]["id"],
                "diagnosis": "Gastritis leve",
                "treatment": "Omeprazol 20mg diario",
            },
            token=bundle["doctorToken"],
        )
        self.assertEqual(cons.status, 201)
        rec = self.client.get("/api/records", token=bundle["patientToken"])
        self.assertEqual(rec.status, 200)
        rx_ids = {c["prescriptionId"] for c in rec.data.get("consultations", [])}
        self.assertIn(cons.data["prescriptionId"], rx_ids)

    def test_t1_f08_05_authorized_doctor_retrieves_issued_prescription(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": bundle["patientId"],
                "appointmentId": bundle["appointment"]["id"],
                "diagnosis": "Dermatitis de contacto",
                "treatment": "Hidrocortisona tópica",
            },
            token=bundle["doctorToken"],
        )
        rx_id = cons.data["prescriptionId"]
        rx_p = self.client.get(f"/api/prescriptions/{rx_id}", token=bundle["patientToken"])
        rx_d = self.client.get(f"/api/prescriptions/{rx_id}", token=bundle["doctorToken"])
        self.assertEqual(rx_p.status, 200)
        self.assertEqual(rx_d.status, 200)
        self.assertEqual(rx_d.data["diagnosis"], rx_p.data["diagnosis"])
        self.assertEqual(rx_d.data["treatment"], rx_p.data["treatment"])
