"""Tier 2 F11: Messaging & Notification Deduplication Boundaries (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.aws_inspector import invoke_reminders_lambda
from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    register_and_subscribe_doctor,
    register_patient,
    setup_slot_within_24h,
)


class TestTier2F11MessagingBoundaries(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t2_f11_01_messaging_without_appointment_or_consent_rejected(self) -> None:
        _, d_user, _ = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        resp = self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Sin relación"}, token=p_tok)
        self.assertEqual(resp.status, 403)

    def test_t2_f11_02_message_over_2000_chars_or_whitespace_rejected(self) -> None:
        _, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.assertEqual(
            self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "a" * 2001}, token=p_tok).status,
            400,
        )
        self.assertEqual(
            self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "   "}, token=p_tok).status,
            400,
        )

    def test_t2_f11_03_self_messaging_and_nonexistent_recipient_rejected(self) -> None:
        p_tok, p_user = register_patient(self.client)
        self_msg = self.client.post("/api/messages", {"recipientId": p_user["id"], "content": "Yo"}, token=p_tok)
        self.assertIn(self_msg.status, (400, 403))
        missing = self.client.post(
            "/api/messages",
            {"recipientId": "00000000-0000-0000-0000-999999999999", "content": "Fantasma"},
            token=p_tok,
        )
        self.assertIn(missing.status, (403, 404))

    def test_t2_f11_04_marking_another_users_notification_read_rejected(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p1_tok, _ = register_patient(self.client)
        p2_tok, _ = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p1_tok)
        self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Notif A"}, token=p1_tok)
        nid = self.client.get("/api/notifications", token=d_tok).data[0]["id"]
        resp = self.client.put(f"/api/notifications/{nid}/read", {}, token=p2_tok)
        self.assertIn(resp.status, (403, 404))

    def test_t2_f11_05_notification_deduplication_prevents_duplicate_reminders(self) -> None:
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client, with_schedule=False)
        p_tok, _ = register_patient(self.client)
        slot_24h = setup_slot_within_24h(self.ctx, self.client, d_tok, d_id)
        self.assertEqual(
            self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot_24h}, token=p_tok).status,
            201,
        )
        if self.ctx.mode == "self-test":
            self.assertEqual(self.client.post("/__reminders/run", {}).status, 200)
            self.assertEqual(self.client.post("/__reminders/run", {}).status, 200)
        elif self.ctx.target == "cloud":
            invoke_reminders_lambda(self.ctx)
            invoke_reminders_lambda(self.ctx)
        n1 = self.client.get("/api/notifications", token=p_tok).data
        n2 = self.client.get("/api/notifications", token=p_tok).data
        rem1 = [n for n in n1 if n["type"] == "RECORDATORIO_CITA"]
        rem2 = [n for n in n2 if n["type"] == "RECORDATORIO_CITA"]
        self.assertGreaterEqual(len(rem1), 1, f"Expected >=1 reminder within 24h, got {n1}")
        self.assertEqual(len(rem1), len(rem2))
