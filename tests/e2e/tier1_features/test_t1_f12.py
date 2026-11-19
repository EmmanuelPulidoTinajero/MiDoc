"""Tier 1 F12: Relational Integrity, ACID Atomicity, Idempotency & DDB Resilience (5 tests)."""
from __future__ import annotations

from datetime import date
import os
import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_doctor,
    register_patient,
    send_live_signed_webhook,
    setup_started_appointment,
    subscribe_doctor_via_stripe,
)


class TestTier1F12IntegrityAndResilience(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f12_01_concurrent_double_booking_yields_one_201_and_one_409(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p1_tok, _ = register_patient(self.client)
        p2_tok, _ = register_patient(self.client)
        slot = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"][0]

        def book(tok: str):
            return self.ctx.client().post("/api/appointments", {"doctorId": d_id, "dateTime": slot}, token=tok)

        resps = self.client.run_concurrent([lambda: book(p1_tok), lambda: book(p2_tok)], max_workers=2)
        statuses = sorted(r.status for r in resps)
        self.assertEqual(statuses, [201, 409], f"Expected [201, 409], got {statuses}")

    def test_t1_f12_02_stripe_confirm_and_webhook_idempotency(self) -> None:
        d_tok, d_user, d_id = register_doctor(self.client)
        if self.ctx.stripe_mock is not None:
            chk = self.client.post("/api/subscriptions/checkout", {}, token=d_tok)
            self.assertEqual(chk.status, 201)
            sid = chk.data["sessionId"]
            self.ctx.stripe_mock.complete_session(sid)
            c1 = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok)
            c2 = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok)
            w_status, _ = self.ctx.stripe_mock.send_webhook(self.ctx.api_url, sid)
            self.assertEqual(c1.status, 200)
            self.assertEqual(c2.status, 200)
            self.assertEqual(w_status, 200)
            end1 = date.fromisoformat(c1.data["subscription"]["end"])
            end2 = date.fromisoformat(c2.data["subscription"]["end"])
            self.assertEqual(end1, end2)
            self.assertEqual((end1 - date.fromisoformat(c1.data["subscription"]["start"])).days, 29)
            return

        res = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        sid = res["sessionId"]
        c1 = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok)
        c2 = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok)
        self.assertEqual(c1.status, 200, c1.text)
        self.assertEqual(c2.status, 200, c2.text)
        wh_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        if wh_secret:
            w_status, _ = send_live_signed_webhook(
                self.client,
                webhook_secret=wh_secret,
                session_id=sid,
                doctor_id=d_id,
                user_id=d_user["id"],
                mode=res["subscription"].get("paymentMode", "test"),
            )
            self.assertEqual(w_status, 200)
        end1 = date.fromisoformat(c1.data["subscription"]["end"])
        end2 = date.fromisoformat(c2.data["subscription"]["end"])
        self.assertEqual(end1, end2)
        self.assertEqual((end1 - date.fromisoformat(c1.data["subscription"]["start"])).days, 29)

    def test_t1_f12_03_consultation_rx_and_completion_atomicity(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client)
        payload = {
            "patientId": bundle["patientId"],
            "appointmentId": bundle["appointment"]["id"],
            "diagnosis": "Bronquitis leve",
            "treatment": "Líquidos y seguimiento",
        }
        c1 = self.client.post("/api/consultations", payload, token=bundle["doctorToken"])
        self.assertEqual(c1.status, 201, c1.text)
        c2 = self.client.post("/api/consultations", payload, token=bundle["doctorToken"])
        self.assertEqual(c2.status, 409, c2.text)
        appt = self.client.get(f"/api/appointments/{bundle['appointment']['id']}", token=bundle["patientToken"])
        self.assertEqual(appt.data["status"], "COMPLETADA")

    def test_t1_f12_04_postgresql_migration_and_schema_parity(self) -> None:
        schema_path = self.ctx.repo_root / "backend" / "src" / "schema.sql"
        self.assertTrue(schema_path.is_file(), f"Missing {schema_path}")
        schema_text = schema_path.read_text(encoding="utf-8", errors="replace")
        for tbl in ("usuario", "perfil_doctor", "cita", "expediente", "consulta", "receta", "suscripcion"):
            self.assertIn(tbl, schema_text)
        mig_dir = self.ctx.repo_root / "backend" / "migrations"
        migs = sorted(p.name for p in mig_dir.glob("*.sql"))
        self.assertTrue(any(m.startswith("001_") for m in migs))
        if not self.ctx.use_self_test_fixtures:
            self.assertTrue(any(m.startswith("004_") for m in migs), f"Missing 004 migration: {migs}")

    def test_t1_f12_05_dynamodb_audit_fault_tolerance_on_record_read(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.put("/api/records", {"notes": "Lectura tolerante a fallos"}, token=p_tok)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        if self.ctx.mode == "self-test":
            self.client.post("/__selftest/ddb-failure", {"enabled": True})
        try:
            rec = self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok)
            self.assertEqual(rec.status, 200, rec.text)
            self.assertEqual(rec.data["notes"], "Lectura tolerante a fallos")
        finally:
            if self.ctx.mode == "self-test":
                self.client.post("/__selftest/ddb-failure", {"enabled": False})
