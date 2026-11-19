"""Tier 2 F12: Malformed Inputs & Concurrency Race Boundaries (5 tests)."""
from __future__ import annotations

from datetime import date
import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_doctor,
    register_patient,
    subscribe_doctor_via_stripe,
)


class TestTier2F12IntegrityBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f12_01_malformed_json_body_returns_400_not_500(self) -> None:
        resp = self.client.post(
            "/api/auth/login",
            raw_bytes=b"{bad json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400, resp.text)

    def test_t2_f12_02_malformed_uuid_path_param_returns_400_or_404_not_500(self) -> None:
        p_tok, _ = register_patient(self.client)
        self.assertIn(self.client.get("/api/doctors/not-a-uuid").status, (400, 404))
        self.assertIn(self.client.get("/api/appointments/not-a-uuid", token=p_tok).status, (400, 404))

    def test_t2_f12_03_concurrent_reschedule_race_on_same_target_slot(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p1_tok, _ = register_patient(self.client)
        p2_tok, _ = register_patient(self.client)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        a1 = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p1_tok).data["id"]
        a2 = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[1]}, token=p2_tok).data["id"]
        target = slots[3]

        resps = self.client.run_concurrent(
            [
                lambda: self.ctx.client().put(f"/api/appointments/{a1}/reschedule", {"dateTime": target}, token=p1_tok),
                lambda: self.ctx.client().put(f"/api/appointments/{a2}/reschedule", {"dateTime": target}, token=p2_tok),
            ],
            max_workers=2,
        )
        statuses = sorted(r.status for r in resps)
        self.assertEqual(statuses, [200, 409], f"Expected [200, 409], got {statuses}")

    def test_t2_f12_04_concurrent_cancel_vs_confirm_atomic_state_transition(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        appt_resp = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p_tok)
        self.assertEqual(appt_resp.status, 201, appt_resp.text)
        aid = appt_resp.data["id"]

        # Barrier-synchronized race on a future PENDIENTE appointment:
        # patient cancels vs doctor confirms.
        resps = self.client.run_concurrent(
            [
                lambda: self.ctx.client().put(
                    f"/api/appointments/{aid}/status", {"status": "CANCELADA"}, token=p_tok
                ),
                lambda: self.ctx.client().put(
                    f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}, token=d_tok
                ),
            ],
            max_workers=2,
        )
        statuses = [r.status for r in resps]
        for st in statuses:
            self.assertIn(st, (200, 409), f"Unexpected status in concurrent transition: {statuses}")
        self.assertIn(200, statuses, f"At least one valid transition must succeed: {statuses}")

        appt = self.client.get(f"/api/appointments/{aid}", token=p_tok).data
        self.assertIn(appt["status"], ("CANCELADA", "CONFIRMADA"))
        if appt["status"] == "CANCELADA":
            # Once cancelled, neither confirm nor reschedule may succeed
            self.assertEqual(
                self.client.put(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}, token=d_tok).status,
                409,
            )
            self.assertEqual(
                self.client.put(f"/api/appointments/{aid}/reschedule", {"dateTime": slots[1]}, token=p_tok).status,
                409,
            )
        else:
            # Confirming an already-confirmed appointment must reject 409
            self.assertEqual(
                self.client.put(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}, token=d_tok).status,
                409,
            )

    def test_t2_f12_05_concurrent_stripe_confirms_serialize_cleanly(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        if self.ctx.stripe_mock is not None:
            chk = self.client.post("/api/subscriptions/checkout", {}, token=d_tok)
            self.assertEqual(chk.status, 201)
            sid = chk.data["sessionId"]
            self.ctx.stripe_mock.complete_session(sid)
        else:
            res = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
            sid = res["sessionId"]

        resps = self.client.run_concurrent(
            [
                lambda: self.ctx.client().post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok),
                lambda: self.ctx.client().post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok),
            ],
            max_workers=2,
        )
        for r in resps:
            self.assertEqual(r.status, 200, r.text)
        s0 = resps[0].data["subscription"]
        s1 = resps[1].data["subscription"]
        self.assertEqual(s0["end"], s1["end"])
        self.assertEqual((date.fromisoformat(s0["end"]) - date.fromisoformat(s0["start"])).days, 29)
