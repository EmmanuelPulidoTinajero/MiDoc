"""Tier 1 F05: Explicit Consent Grant/Revoke & Access Log (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_and_subscribe_doctor,
    register_patient,
)


class TestTier1F05Consents(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f05_01_grant_explicit_consent(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        con = self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.assertEqual(con.status, 200, con.text)
        self.assertTrue(con.data["granted"])
        rec = self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok)
        self.assertEqual(rec.status, 200, rec.text)

    def test_t1_f05_02_list_authorized_providers(self) -> None:
        p_tok, _ = register_patient(self.client)
        _, _, d1 = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Alfa")
        _, _, d2 = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Beta")
        self.client.post("/api/consents", {"doctorId": d1, "granted": True}, token=p_tok)
        self.client.post("/api/consents", {"doctorId": d2, "granted": False}, token=p_tok)
        lst = self.client.get("/api/consents", token=p_tok)
        self.assertEqual(lst.status, 200, lst.text)
        by_doc = {item["doctorId"]: item["granted"] for item in lst.data}
        self.assertTrue(by_doc.get(d1))
        self.assertFalse(by_doc.get(d2, False))

    def test_t1_f05_03_revoke_consent_blocks_subsequent_read(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 200)
        rev = self.client.post("/api/consents", {"doctorId": d_id, "granted": False}, token=p_tok)
        self.assertEqual(rev.status, 200)
        self.assertFalse(rev.data["granted"])
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 403)

    def test_t1_f05_04_doctor_access_recorded_in_access_log(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Auditor")
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 200)
        log = self.client.get("/api/records/access-log", token=p_tok)
        self.assertEqual(log.status, 200, log.text)
        self.assertTrue(len(log.data) >= 1)
        entry = log.data[0]
        self.assertTrue(entry.get("accessedAt"))
        self.assertTrue(entry.get("actorId") == d_user["id"] or entry.get("doctorId") == d_id)

    def test_t1_f05_05_consent_toggle_generates_provider_notification(self) -> None:
        p_tok, _ = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        notices = self.client.get("/api/notifications", token=d_tok)
        self.assertEqual(notices.status, 200, notices.text)
        self.assertTrue(any("CONSENT" in str(n.get("type", "")).upper() for n in notices.data))
