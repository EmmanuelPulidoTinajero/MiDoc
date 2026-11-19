"""Tier 3: 18 Cross-Feature Pairwise Combination E2E Tests (T3-01 .. T3-18)."""
from __future__ import annotations

from datetime import date
import os
import unittest

from tests.e2e.harness.aws_inspector import (
    collect_emf_telemetry,
    fetch_frontend_config,
    get_tf_content,
    get_workflow_text,
    wait_for_cloudwatch_metrics,
)
from tests.e2e.harness.browser_driver import open_browser_page
from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    prepare_started_appointments,
    register_and_subscribe_doctor,
    register_doctor,
    register_patient,
    s3_is_configured,
    send_live_signed_webhook,
    setup_started_appointment,
    subscribe_doctor_via_stripe,
    verify_pdf_bytes,
)


class TestTier3PairwiseCombinations(unittest.TestCase):
    _prebooked: list[dict] = []

    @classmethod
    def setUpClass(cls) -> None:
        ctx = get_active_context()
        if ctx.mode == "live":
            cls._prebooked = prepare_started_appointments(ctx, ctx.client(), 5)

    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t3_01_consent_revoked_after_doc_upload_and_consultation_attempt(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, grant_consent=True, prebooked_queue=self._prebooked)
        pdf = b"%PDF-1.4\n% T3-01 lab\n%%EOF\n"
        req = self.client.post(
            "/api/records/documents",
            {"name": "lab-t3.pdf", "contentType": "application/pdf", "size": len(pdf)},
            token=bundle["patientToken"],
        )
        if s3_is_configured(self.ctx):
            self.assertEqual(req.status, 201, req.text)
            self.client.upload_presigned_post(req.data["url"], req.data["fields"], "lab-t3.pdf", "application/pdf", pdf)
            self.assertEqual(
                self.client.get("/api/records/documents", query={"patientId": bundle["patientId"]}, token=bundle["doctorToken"]).status,
                200,
            )
        else:
            self.assertEqual(req.status, 503, req.text)
        self.client.post("/api/consents", {"doctorId": bundle["doctorId"], "granted": False}, token=bundle["patientToken"])
        self.assertEqual(
            self.client.get("/api/records/documents", query={"patientId": bundle["patientId"]}, token=bundle["doctorToken"]).status,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/consultations",
                {
                    "patientId": bundle["patientId"],
                    "appointmentId": bundle["appointment"]["id"],
                    "diagnosis": "Bloqueado",
                    "treatment": "Sin acceso",
                },
                token=bundle["doctorToken"],
            ).status,
            403,
        )

    def test_t3_02_early_renewal_chaining_plus_active_promotion_visibility(self) -> None:
        d_tok, _, d_id = register_doctor(self.client, price=350, specialty="PairwiseSpec2")
        sub1 = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        self.client.post(
            "/api/doctor/promotions",
            {"title": "Promo T3", "discountPercent": 20, "start": future_date_str(0), "end": future_date_str(5)},
            token=d_tok,
        )
        sub2 = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        self.assertEqual(
            (date.fromisoformat(sub2["subscription"]["end"]) - date.fromisoformat(sub1["subscription"]["end"])).days,
            30,
        )
        listing = self.client.get("/api/doctors", query={"specialty": "PairwiseSpec2", "sort": "PRICE_ASC"}).data
        doc = next(d for d in listing if d["id"] == d_id)
        self.assertTrue(doc["promotions"])

    def test_t3_03_reschedule_notification_and_messaging_gate(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, p_user = register_patient(self.client)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        aid = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p_tok).data["id"]
        self.assertEqual(self.client.put(f"/api/appointments/{aid}/reschedule", {"dateTime": slots[1]}, token=d_tok).status, 200)
        notices = self.client.get("/api/notifications", token=p_tok).data
        self.assertTrue(any(n["type"] == "CITA_REPROGRAMADA" for n in notices))
        self.assertEqual(self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Gracias por reprogramar"}, token=p_tok).status, 201)
        convs = self.client.get("/api/messages", token=d_tok).data
        self.assertEqual(next(c for c in convs if c["userId"] == p_user["id"])["unread"], 1)
        self.assertEqual(self.client.get(f"/api/messages/{p_user['id']}", token=d_tok).status, 200)
        convs_after = self.client.get("/api/messages", token=d_tok).data
        self.assertEqual(next(c for c in convs_after if c["userId"] == p_user["id"])["unread"], 0)

    def test_t3_04_access_log_recording_and_dynamodb_resilience(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 200)
        if self.ctx.mode == "self-test":
            self.client.post("/__selftest/ddb-failure", {"enabled": True})
        try:
            self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 200)
        finally:
            if self.ctx.mode == "self-test":
                self.client.post("/__selftest/ddb-failure", {"enabled": False})
        log = self.client.get("/api/records/access-log", token=p_tok)
        self.assertEqual(log.status, 200)
        self.assertGreaterEqual(len(log.data), 2)

    def test_t3_05_stripe_webhook_idempotency_and_subscription_status(self) -> None:
        d_tok, d_user, d_id = register_doctor(self.client)
        if self.ctx.stripe_mock is not None:
            sid = self.client.post("/api/subscriptions/checkout", {}, token=d_tok).data["sessionId"]
            st1, _ = self.ctx.stripe_mock.send_webhook(self.ctx.api_url, sid)
            st2, _ = self.ctx.stripe_mock.send_webhook(self.ctx.api_url, sid)
            conf = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok)
            self.assertEqual(st1, 200)
            self.assertEqual(st2, 200)
            self.assertEqual(conf.status, 200)
            sub = conf.data["subscription"]
            self.assertEqual((date.fromisoformat(sub["end"]) - date.fromisoformat(sub["start"])).days, 29)
            return

        res = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        sid = res["sessionId"]
        wh_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        if wh_secret:
            st_dup, _ = send_live_signed_webhook(
                self.client,
                webhook_secret=wh_secret,
                session_id=sid,
                doctor_id=d_id,
                user_id=d_user["id"],
                mode=res["subscription"].get("paymentMode", "test"),
            )
            self.assertEqual(st_dup, 200)
        conf = self.client.post("/api/subscriptions/confirm", {"sessionId": sid}, token=d_tok)
        self.assertEqual(conf.status, 200, conf.text)
        sub = conf.data["subscription"]
        self.assertEqual((date.fromisoformat(sub["end"]) - date.fromisoformat(sub["start"])).days, 29)

    def test_t3_06_rx_pdf_presigned_url_and_patient_consultation_history(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": bundle["patientId"],
                "appointmentId": bundle["appointment"]["id"],
                "diagnosis": "Rinitis alérgica",
                "treatment": "Cetirizina 10mg",
            },
            token=bundle["doctorToken"],
        )
        self.assertEqual(cons.status, 201, cons.text)
        rx_id = cons.data["prescriptionId"]
        rx = self.client.get(f"/api/prescriptions/{rx_id}", token=bundle["patientToken"]).data
        if s3_is_configured(self.ctx):
            verify_pdf_bytes(self.client.download_url(rx["downloadUrl"]).body_bytes)
        else:
            self.assertFalse(rx.get("hasPdf"))
            self.assertIsNone(rx.get("downloadUrl"))
        rec = self.client.get("/api/records", token=bundle["patientToken"]).data
        self.assertTrue(any(c["prescriptionId"] == rx_id for c in rec["consultations"]))

    def test_t3_07_put_me_profile_update_reflected_in_directory_after_stripe(self) -> None:
        d_tok, _, d_id = register_doctor(self.client, specialty="OldSpecT3", price=400)
        self.client.put("/api/me", {"specialty": "NewSpecT3", "price": 750}, token=d_tok)
        subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        listing = self.client.get("/api/doctors", query={"specialty": "NewSpecT3"}).data
        doc = next(d for d in listing if d["id"] == d_id)
        self.assertEqual(float(doc["price"]), 750.0)

    def test_t3_08_jwt_refresh_mid_booking_workflow(self) -> None:
        _, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        fresh_tok = self.client.post("/api/auth/refresh", {}, token=p_tok).json_data["token"]
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        booked = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=fresh_tok)
        self.assertEqual(booked.status, 201)
        aid = booked.data["id"]
        self.assertEqual(self.client.put(f"/api/appointments/{aid}/reschedule", {"dateTime": slots[1]}, token=fresh_tok).status, 200)
        self.assertEqual(self.client.put(f"/api/appointments/{aid}/status", {"status": "CANCELADA"}, token=fresh_tok).status, 200)

    def test_t3_09_clinica_role_booking_schedule_and_promotion_parity(self) -> None:
        c_tok, _, c_id = register_and_subscribe_doctor(self.ctx, self.client, role="CLINICA", name="Clínica Integral")
        self.client.post(
            "/api/doctor/promotions",
            {"title": "Promo Clínica 25%", "discountPercent": 25, "start": future_date_str(0), "end": future_date_str(4)},
            token=c_tok,
        )
        p_tok, _ = register_patient(self.client)
        prof = self.client.get(f"/api/doctors/{c_id}").data
        self.assertEqual(prof["type"], "CLINICA")
        self.assertTrue(prof["promotions"])
        slot = self.client.get(f"/api/doctors/{c_id}/availability", query={"date": future_date_str(3)}).data["slots"][0]
        aid = self.client.post("/api/appointments", {"doctorId": c_id, "dateTime": slot}, token=p_tok).data["id"]
        self.assertEqual(self.client.put(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}, token=c_tok).status, 200)

    def test_t3_10_consultation_alongside_inventory_update(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        self.assertEqual(
            self.client.post(
                "/api/doctor/inventory", {"name": "Jeringas", "quantity": 10, "unit": "piezas"}, token=bundle["doctorToken"]
            ).status,
            201,
        )
        self.assertEqual(
            self.client.post(
                "/api/consultations",
                {
                    "patientId": bundle["patientId"],
                    "appointmentId": bundle["appointment"]["id"],
                    "diagnosis": "Inmunización",
                    "treatment": "Aplicación de vacuna",
                },
                token=bundle["doctorToken"],
            ).status,
            201,
        )
        upd = self.client.post(
            "/api/doctor/inventory", {"name": "Jeringas", "quantity": 9, "unit": "piezas"}, token=bundle["doctorToken"]
        )
        self.assertIn(upd.status, (200, 201))
        self.assertEqual(upd.data["quantity"], 9)

    def test_t3_11_revoked_consent_leaves_appointment_based_messaging_intact(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p_tok, _ = register_patient(self.client)
        slot = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"][0]
        self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot}, token=p_tok)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": False}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": self.client.get("/api/me", token=p_tok).data["id"]}, token=d_tok).status, 403)
        self.assertEqual(self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Mensaje por cita"}, token=p_tok).status, 201)

    def test_t3_12_private_s3_presigned_url_post_revocation_vs_deletion(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        raw = b"%PDF-1.4\n% S3 revocation vs deletion\n%%EOF\n"
        req = self.client.post(
            "/api/records/documents", {"name": "est.pdf", "contentType": "application/pdf", "size": len(raw)}, token=p_tok
        )
        if not s3_is_configured(self.ctx):
            self.assertEqual(req.status, 503, req.text)
            self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
            self.assertEqual(
                self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).status,
                503,
            )
            self.client.post("/api/consents", {"doctorId": d_id, "granted": False}, token=p_tok)
            self.assertEqual(
                self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).status,
                403,
            )
            return
        self.assertEqual(req.status, 201)
        self.client.upload_presigned_post(req.data["url"], req.data["fields"], "est.pdf", "application/pdf", raw)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        dl_url = self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).data[0]["downloadUrl"]
        self.assertEqual(self.client.download_url(dl_url).status, 200)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": False}, token=p_tok)
        self.assertEqual(self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).status, 403)
        self.assertEqual(self.client.delete(f"/api/records/documents/{req.data['id']}", token=p_tok).status, 200)
        self.assertEqual(self.client.download_url(dl_url).status, 404)

    def test_t3_13_stripe_checkout_and_confirm_emit_emf_telemetry(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        if self.ctx.mode == "self-test":
            metrics = collect_emf_telemetry(self.ctx)
            keys = {k for m in metrics for k in m.keys()}
            self.assertIn("PaymentCheckoutCreated", keys)
            self.assertIn("PaymentSucceeded", keys)
        elif self.ctx.target == "cloud":
            names = wait_for_cloudwatch_metrics(
                self.ctx, ("PaymentCheckoutCreated", "PaymentSucceeded"), timeout_s=90.0
            )
            self.assertIn("PaymentCheckoutCreated", names, f"Missing PaymentCheckoutCreated in CloudWatch: {sorted(names)}")
            self.assertIn("PaymentSucceeded", names, f"Missing PaymentSucceeded in CloudWatch: {sorted(names)}")
        else:
            metricas_py = (self.ctx.repo_root / "backend" / "src" / "metricas.py").read_text(encoding="utf-8")
            self.assertIn("PaymentCheckoutCreated", metricas_py)
            self.assertIn("PaymentSucceeded", metricas_py)

    def test_t3_14_appointment_consultation_and_failed_login_emit_core_emf_metrics(self) -> None:
        self.client.post("/api/auth/login", {"email": "missing@example.invalid", "password": "BadPassword1"})
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": bundle["patientId"],
                "appointmentId": bundle["appointment"]["id"],
                "diagnosis": "Control",
                "treatment": "Alta",
            },
            token=bundle["doctorToken"],
        )
        self.assertEqual(cons.status, 201, cons.text)
        required = ("LoginFailures", "AppointmentsCreated", "ConsultationsRegistered", "RequestLatencyMs")
        if self.ctx.mode == "self-test":
            metrics = collect_emf_telemetry(self.ctx)
            keys = {k for m in metrics for k in m.keys()}
            for name in required:
                self.assertIn(name, keys)
        elif self.ctx.target == "cloud":
            names = wait_for_cloudwatch_metrics(self.ctx, required, timeout_s=90.0)
            for name in required:
                self.assertIn(name, names, f"Missing {name} in CloudWatch: {sorted(names)}")
        else:
            metricas_py = (self.ctx.repo_root / "backend" / "src" / "metricas.py").read_text(encoding="utf-8")
            for name in required:
                self.assertIn(name, metricas_py)

    def test_t3_15_stripe_checkout_return_url_preserves_hash_location_route(self) -> None:
        d_tok, _, _ = register_doctor(self.client)
        chk = self.client.post("/api/subscriptions/checkout", {}, token=d_tok)
        self.assertEqual(chk.status, 201)
        if self.ctx.stripe_mock is not None:
            reqs = [r for r in self.ctx.stripe_mock.recorded_requests if r["method"] == "POST"]
            success_url = reqs[-1]["form"].get("success_url", "")
            self.assertIn("#/panel/suscripcion", success_url)
        else:
            self.assertTrue(str(chk.data.get("checkoutUrl", "")).startswith("https://"))
        if self.ctx.with_browser and self.ctx.frontend_url:
            with open_browser_page(self.ctx) as (page, errors, _):
                page.goto(f"{self.ctx.frontend_url}#/panel/suscripcion?stripe_status=cancel", wait_until="networkidle")
                self.assertFalse(errors, errors)

    def test_t3_16_terraform_payment_mode_matches_config_json_and_no_secret_exposed(self) -> None:
        vars_tf = get_tf_content(self.ctx, "variables.tf")
        cd = get_workflow_text(self.ctx, "cd.yml") or ""
        cfg = fetch_frontend_config(self.ctx)
        self.assertIn("payment_mode", vars_tf)
        self.assertIn("paymentMode", cfg)
        self.assertNotIn("stripe_secret_key", cfg)
        self.assertNotIn("sk_test_", str(cfg))
        self.assertNotIn("sk_live_", str(cfg))
        self.assertTrue(cd)

    def test_t3_17_two_doctors_sorting_and_selective_promo_booking(self) -> None:
        _, _, id_a = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Caro", specialty="PairwiseSort17", price=400)
        d_b_tok, _, id_b = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. Promo", specialty="PairwiseSort17", price=250)
        self.client.post(
            "/api/doctor/promotions",
            {"title": "15% Off", "discountPercent": 15, "start": future_date_str(0), "end": future_date_str(5)},
            token=d_b_tok,
        )
        listing = self.client.get("/api/doctors", query={"specialty": "PairwiseSort17", "sort": "PRICE_ASC"}).data
        ids = [d["id"] for d in listing]
        self.assertLess(ids.index(id_b), ids.index(id_a))
        p_tok, _ = register_patient(self.client)
        slot = self.client.get(f"/api/doctors/{id_b}/availability", query={"date": future_date_str(3)}).data["slots"][0]
        self.assertEqual(self.client.post("/api/appointments", {"doctorId": id_b, "dateTime": slot}, token=p_tok).status, 201)

    def test_t3_18_multi_doctor_isolation_across_records_docs_rx_and_consultation(self) -> None:
        bundle = setup_started_appointment(self.ctx, self.client, prebooked_queue=self._prebooked)
        d2_tok, _, _ = register_and_subscribe_doctor(self.ctx, self.client, name="Dr. No Autorizado")
        self.assertEqual(self.client.get("/api/records", query={"patientId": bundle["patientId"]}, token=bundle["doctorToken"]).status, 200)
        self.assertEqual(self.client.get("/api/records", query={"patientId": bundle["patientId"]}, token=d2_tok).status, 403)
        self.assertEqual(self.client.get("/api/records/documents", query={"patientId": bundle["patientId"]}, token=d2_tok).status, 403)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": bundle["patientId"],
                "appointmentId": bundle["appointment"]["id"],
                "diagnosis": "Válida",
                "treatment": "Reposo",
            },
            token=bundle["doctorToken"],
        )
        self.assertEqual(cons.status, 201)
        self.assertEqual(self.client.get(f"/api/prescriptions/{cons.data['prescriptionId']}", token=d2_tok).status, 404)
