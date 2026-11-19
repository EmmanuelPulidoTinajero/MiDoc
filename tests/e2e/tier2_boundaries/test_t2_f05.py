"""Tier 2 F05: Consent & Access Log Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import register_and_subscribe_doctor, register_patient


class TestTier2F05ConsentBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f05_01_grant_consent_to_nonexistent_doctor_returns_404(self) -> None:
        p_tok, _ = register_patient(self.client)
        resp = self.client.post(
            "/api/consents",
            {"doctorId": "00000000-0000-0000-0000-999999999999", "granted": True},
            token=p_tok,
        )
        self.assertEqual(resp.status, 404)

    def test_t2_f05_02_doctor_cannot_grant_or_revoke_consents(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=d_tok)
        self.assertEqual(resp.status, 403)

    def test_t2_f05_03_revoked_consent_immediately_blocks_record_and_documents(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 200)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": False}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 403)
        self.assertEqual(
            self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).status, 403
        )

    def test_t2_f05_04_doctor_cannot_view_patient_access_log(self) -> None:
        d_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client)
        resp = self.client.get("/api/records/access-log", token=d_tok)
        self.assertEqual(resp.status, 403)

    def test_t2_f05_05_access_log_isolated_between_patients(self) -> None:
        p1_tok, p1 = register_patient(self.client, name="Paciente Uno")
        p2_tok, _ = register_patient(self.client, name="Paciente Dos")
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p1_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p1["id"]}, token=d_tok).status, 200)
        log2 = self.client.get("/api/records/access-log", token=p2_tok)
        self.assertEqual(log2.status, 200)
        self.assertEqual(log2.data, [])
