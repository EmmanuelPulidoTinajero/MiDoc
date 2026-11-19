"""Tier 1 F11: Direct Messaging, In-App Notifications & Reminders (5 tests)."""
from __future__ import annotations

import unittest

from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    register_and_subscribe_doctor,
    register_patient,
)


class TestTier1F11MessagingAndNotifications(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t1_f11_01_direct_messaging_with_appointment_relationship(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        slot = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(2)}).data["slots"][0]
        self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot}, token=p_tok)
        msg = self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Hola doctor"}, token=p_tok)
        self.assertEqual(msg.status, 201, msg.text)
        self.assertEqual(msg.data["content"], "Hola doctor")

    def test_t1_f11_02_direct_messaging_with_consent_only_relationship(self) -> None:
        _, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        msg = self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Consulta previa"}, token=p_tok)
        self.assertEqual(msg.status, 201, msg.text)

    def test_t1_f11_03_conversation_list_and_unread_counts(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, p_user = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Msg 1"}, token=p_tok)
        self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Msg 2"}, token=p_tok)
        convs = self.client.get("/api/messages", token=d_tok)
        self.assertEqual(convs.status, 200)
        entry = next(c for c in convs.data if c["userId"] == p_user["id"])
        self.assertEqual(entry["unread"], 2)

    def test_t1_f11_04_reading_thread_marks_messages_read(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, p_user = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Leer por favor"}, token=p_tok)
        thread = self.client.get(f"/api/messages/{p_user['id']}", token=d_tok)
        self.assertEqual(thread.status, 200)
        convs = self.client.get("/api/messages", token=d_tok)
        entry = next(c for c in convs.data if c["userId"] == p_user["id"])
        self.assertEqual(entry["unread"], 0)

    def test_t1_f11_05_notifications_mark_read_and_reminder_trigger(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Notif check"}, token=p_tok)
        notices = self.client.get("/api/notifications", token=d_tok)
        self.assertEqual(notices.status, 200)
        target = next(n for n in notices.data if n["type"] == "MENSAJE_NUEVO")
        marked = self.client.put(f"/api/notifications/{target['id']}/read", {}, token=d_tok)
        self.assertEqual(marked.status, 200)
        self.assertTrue(marked.data["read"])
        if self.ctx.mode == "self-test":
            rem = self.client.post("/__reminders/run", {})
            self.assertEqual(rem.status, 200)
            self.assertEqual(rem.json_data["status"], "ok")
