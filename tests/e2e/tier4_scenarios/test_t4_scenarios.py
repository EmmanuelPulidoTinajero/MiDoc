"""Tier 4: 9 Complete Multi-Actor End-to-End Application Scenarios (T4-01 .. T4-09)."""
from __future__ import annotations

from datetime import date
import json
import unittest

from tests.e2e.harness.aws_inspector import (
    check_terraform_fmt_and_validate,
    collect_emf_telemetry,
    get_doc_text,
    get_tf_content,
    get_workflow_text,
    invoke_reminders_lambda,
    resolve_markdown_links,
    wait_for_cloudwatch_metrics,
)
from tests.e2e.harness.browser_driver import assert_no_horizontal_overflow, open_browser_page
from tests.e2e.harness.config import get_active_context
from tests.e2e.harness.data_factory import (
    future_date_str,
    next_slot_window,
    register_and_subscribe_doctor,
    register_doctor,
    register_patient,
    s3_is_configured,
    setup_slot_within_24h,
    subscribe_doctor_via_stripe,
    verify_pdf_bytes,
    wait_until_slot_started,
)


class TestTier4EndToEndScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = get_active_context()
        self.client = self.ctx.client()

    def test_t4_01_complete_first_time_patient_consultation_lifecycle(self) -> None:
        p_tok, p_user = register_patient(self.client, name="Carlos Paciente")
        self.assertEqual(
            self.client.put(
                "/api/records",
                {"bloodType": "O+", "allergies": ["Penicilina"], "notes": "Primer ingreso"},
                token=p_tok,
            ).status,
            200,
        )
        lab_pdf = b"%PDF-1.4\n% Biometria hematica\n%%EOF\n"
        doc_req_resp = self.client.post(
            "/api/records/documents",
            {"name": "biometria.pdf", "contentType": "application/pdf", "size": len(lab_pdf)},
            token=p_tok,
        )
        s3_ready = s3_is_configured(self.ctx)
        if s3_ready:
            self.assertEqual(doc_req_resp.status, 201, doc_req_resp.text)
            doc_req = doc_req_resp.data
            self.client.upload_presigned_post(doc_req["url"], doc_req["fields"], "biometria.pdf", "application/pdf", lab_pdf)
        else:
            self.assertEqual(doc_req_resp.status, 503, doc_req_resp.text)

        d_tok, d_user, d_id = register_and_subscribe_doctor(
            self.ctx, self.client, name="Dra. Sofía T4", specialty="InternaT4", price=600, duration_min=10, with_schedule=False
        )
        start_dt, end_dt = next_slot_window(self.ctx, min_buffer_s=15, block_minutes=20)
        self.assertEqual(
            self.client.put(
                "/api/doctor/schedule",
                {"blocks": [{"day": start_dt.isoweekday(), "start": start_dt.strftime("%H:%M"), "end": end_dt.strftime("%H:%M")}]},
                token=d_tok,
            ).status,
            200,
        )

        directory = self.client.get("/api/doctors", query={"specialty": "InternaT4", "sort": "PRICE_ASC"}).data
        self.assertTrue(any(d["id"] == d_id for d in directory))
        slot = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": start_dt.date().isoformat()}).data["slots"][0]
        appt = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot, "reason": "Dolor torácico"}, token=p_tok).data
        self.assertEqual(self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok).status, 200)
        self.assertEqual(self.client.put(f"/api/appointments/{appt['id']}/status", {"status": "CONFIRMADA"}, token=d_tok).status, 200)

        rec_doc = self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok)
        self.assertEqual(rec_doc.status, 200)
        if s3_ready:
            docs_doc = self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).data
            self.assertEqual(self.client.download_url(docs_doc[0]["downloadUrl"]).body_bytes, lab_pdf)

        wait_until_slot_started(self.ctx, slot)
        cons = self.client.post(
            "/api/consultations",
            {
                "patientId": p_user["id"],
                "appointmentId": appt["id"],
                "diagnosis": "Reflujo gastroesofágico",
                "treatment": "Omeprazol 20mg por 14 días",
            },
            token=d_tok,
        )
        self.assertEqual(cons.status, 201, cons.text)
        rx = self.client.get(f"/api/prescriptions/{cons.data['prescriptionId']}", token=p_tok).data
        if s3_ready:
            verify_pdf_bytes(self.client.download_url(rx["downloadUrl"]).body_bytes)
        else:
            self.assertFalse(rx.get("hasPdf"))
            self.assertIsNone(rx.get("downloadUrl"))
        access_log = self.client.get("/api/records/access-log", token=p_tok).data
        self.assertTrue(
            any(e.get("actorId") == d_user["id"] or e.get("doctorId") == d_id for e in access_log),
            f"Doctor access not recorded in access_log: {access_log}",
        )

    def test_t4_02_clinic_onboarding_stripe_webhook_and_discovery(self) -> None:
        c_tok, _, c_id = register_doctor(
            self.client, role="CLINICA", name="Clínica Horizonte", specialty="Diagnóstico", city="Monterrey", price=900
        )
        subscribe_doctor_via_stripe(self.ctx, self.client, c_tok, via_webhook=True)
        self.assertEqual(self.client.put("/api/me", {"price": 790, "city": "San Pedro"}, token=c_tok).status, 200)
        self.assertEqual(
            self.client.put(
                "/api/doctor/schedule",
                {"blocks": [{"day": d, "start": "09:00", "end": "14:00"} for d in range(1, 8)]},
                token=c_tok,
            ).status,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/doctor/promotions",
                {"title": "Apertura 20%", "discountPercent": 20, "start": future_date_str(0), "end": future_date_str(7)},
                token=c_tok,
            ).status,
            201,
        )
        p_tok, _ = register_patient(self.client)
        found = self.client.get("/api/doctors", query={"location": "San Pedro", "specialty": "Diagnóstico"}).data
        clinic = next(d for d in found if d["id"] == c_id)
        self.assertEqual(float(clinic["price"]), 790.0)
        self.assertTrue(clinic["promotions"])
        slot = self.client.get(f"/api/doctors/{c_id}/availability", query={"date": future_date_str(2)}).data["slots"][0]
        aid = self.client.post("/api/appointments", {"doctorId": c_id, "dateTime": slot}, token=p_tok).data["id"]
        self.assertEqual(self.client.put(f"/api/appointments/{aid}/status", {"status": "CONFIRMADA"}, token=c_tok).status, 200)

    def test_t4_03_consent_revocation_mid_treatment_and_audit_trail(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.put("/api/records", {"notes": "Seguimiento oncológico"}, token=p_tok)
        dcm = b"DICM-T4-03"
        req_resp = self.client.post(
            "/api/records/documents", {"name": "tac.dcm", "contentType": "application/dicom", "size": len(dcm)}, token=p_tok
        )
        s3_ready = s3_is_configured(self.ctx)
        if s3_ready:
            self.assertEqual(req_resp.status, 201, req_resp.text)
            req = req_resp.data
            self.client.upload_presigned_post(req["url"], req["fields"], "tac.dcm", "application/dicom", dcm)
        else:
            self.assertEqual(req_resp.status, 503, req_resp.text)

        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 200)
        if s3_ready:
            docs = self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).data
            self.assertEqual(self.client.download_url(docs[0]["downloadUrl"]).body_bytes, dcm)

        self.client.post("/api/consents", {"doctorId": d_id, "granted": False}, token=p_tok)
        self.assertEqual(self.client.get("/api/records", query={"patientId": p_user["id"]}, token=d_tok).status, 403)
        self.assertEqual(self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).status, 403)
        log = self.client.get("/api/records/access-log", token=p_tok).data
        self.assertTrue(len(log) >= 1)
        if s3_ready:
            self.assertEqual(self.client.delete(f"/api/records/documents/{req['id']}", token=p_tok).status, 200)
            self.assertEqual(self.client.download_url(docs[0]["downloadUrl"]).status, 404)

    def test_t4_04_appointment_reschedule_cascade_and_messaging_gate(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        p1_tok, p1 = register_patient(self.client, name="Paciente 1")
        p2_tok, _ = register_patient(self.client, name="Paciente 2")
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        a1 = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p1_tok).data["id"]
        self.assertEqual(self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p2_tok).status, 409)
        self.assertEqual(self.client.put(f"/api/appointments/{a1}/reschedule", {"dateTime": slots[1]}, token=d_tok).status, 200)
        self.assertTrue(any(n["type"] == "CITA_REPROGRAMADA" for n in self.client.get("/api/notifications", token=p1_tok).data))
        a2 = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p2_tok)
        self.assertEqual(a2.status, 201)
        self.assertEqual(self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Confirmado"}, token=p1_tok).status, 201)
        self.assertEqual(self.client.get(f"/api/messages/{p1['id']}", token=d_tok).status, 200)
        self.assertEqual(self.client.put(f"/api/appointments/{a2.data['id']}/status", {"status": "CANCELADA"}, token=p2_tok).status, 200)
        free_again = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": future_date_str(3)}).data["slots"]
        self.assertIn(slots[0], free_again)

    def test_t4_05_early_renewal_inventory_and_multi_consultation_evolution(self) -> None:
        d_tok, _, d_id = register_doctor(self.client, duration_min=10)
        sub1 = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        sub2 = subscribe_doctor_via_stripe(self.ctx, self.client, d_tok)
        self.assertEqual((date.fromisoformat(sub2["subscription"]["end"]) - date.fromisoformat(sub1["subscription"]["start"])).days, 59)

        start_dt, end_dt = next_slot_window(self.ctx, min_buffer_s=15, block_minutes=30)
        self.client.put(
            "/api/doctor/schedule",
            {"blocks": [{"day": start_dt.isoweekday(), "start": start_dt.strftime("%H:%M"), "end": end_dt.strftime("%H:%M")}]},
            token=d_tok,
        )
        self.client.post("/api/doctor/inventory", {"name": "Abatelenguas", "quantity": 50, "unit": "piezas"}, token=d_tok)

        p_tok, p_user = register_patient(self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        slots = self.client.get(f"/api/doctors/{d_id}/availability", query={"date": start_dt.date().isoformat()}).data["slots"]
        a1 = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[0]}, token=p_tok).data["id"]

        if self.ctx.mode == "self-test":
            # In self-test, advance virtual clock cleanly between two sequential slots on the same doctor
            a2 = self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slots[1]}, token=p_tok).data["id"]
            wait_until_slot_started(self.ctx, slots[0])
            c1 = self.client.post(
                "/api/consultations",
                {"patientId": p_user["id"], "appointmentId": a1, "diagnosis": "Visita 1", "treatment": "Tratamiento 1"},
                token=d_tok,
            ).data
            self.client.put("/api/records", {"notes": "Evolución favorable"}, token=p_tok)
            wait_until_slot_started(self.ctx, slots[1])
            c2 = self.client.post(
                "/api/consultations",
                {"patientId": p_user["id"], "appointmentId": a2, "diagnosis": "Visita 2", "treatment": "Alta médica"},
                token=d_tok,
            ).data
        else:
            # In live mode, book a second specialist at the same slot window T0 to avoid an 11-minute sleep
            d2_tok, _, d2_id = register_and_subscribe_doctor(
                self.ctx, self.client, name="Dr. Seguimiento T4", duration_min=10, with_schedule=False
            )
            self.client.put(
                "/api/doctor/schedule",
                {"blocks": [{"day": start_dt.isoweekday(), "start": start_dt.strftime("%H:%M"), "end": end_dt.strftime("%H:%M")}]},
                token=d2_tok,
            )
            self.client.post("/api/consents", {"doctorId": d2_id, "granted": True}, token=p_tok)
            slots2 = self.client.get(f"/api/doctors/{d2_id}/availability", query={"date": start_dt.date().isoformat()}).data["slots"]
            a2 = self.client.post("/api/appointments", {"doctorId": d2_id, "dateTime": slots2[0]}, token=p_tok).data["id"]
            wait_until_slot_started(self.ctx, max(slots[0], slots2[0]))
            c1 = self.client.post(
                "/api/consultations",
                {"patientId": p_user["id"], "appointmentId": a1, "diagnosis": "Visita 1", "treatment": "Tratamiento 1"},
                token=d_tok,
            ).data
            self.client.put("/api/records", {"notes": "Evolución favorable"}, token=p_tok)
            c2 = self.client.post(
                "/api/consultations",
                {"patientId": p_user["id"], "appointmentId": a2, "diagnosis": "Visita 2", "treatment": "Alta médica"},
                token=d2_tok,
            ).data

        self.assertNotEqual(c1["prescriptionId"], c2["prescriptionId"])
        rec = self.client.get("/api/records", token=p_tok).data
        self.assertEqual(len(rec["consultations"]), 2)

    def test_t4_06_multi_role_browser_ui_desktop_and_mobile_journey(self) -> None:
        if self.ctx.with_browser and self.ctx.frontend_url:
            if self.ctx.stripe_mock is not None:
                d_tok, d_user, _ = register_doctor(self.client)
                chk = self.client.post("/api/subscriptions/checkout", {}, token=d_tok)
                self.assertEqual(chk.status, 201, chk.text)
                sid = chk.data["sessionId"]
                self.ctx.stripe_mock.complete_session(sid)
                stripe_query = f"stripe_status=success&session_id={sid}"
            else:
                d_tok, d_user, _ = register_and_subscribe_doctor(self.ctx, self.client)
                stripe_query = "stripe_status=cancel"

            session_user = {k: d_user[k] for k in ("id", "email", "role", "name", "doctorId") if k in d_user}
            session_json = json.dumps({"token": d_tok, "user": session_user})
            for w, h in ((1280, 800), (390, 844), (320, 640)):
                with open_browser_page(self.ctx, width=w, height=h) as (page, errors, dialogs):
                    page.add_init_script(
                        f"window.localStorage.setItem('midoc.session', {json.dumps(session_json)});"
                        f"window.localStorage.setItem('midoc_token', {json.dumps(d_tok)});"
                    )
                    page.goto(f"{self.ctx.frontend_url}#/buscar", wait_until="networkidle")
                    assert_no_horizontal_overflow(page)
                    page.goto(
                        f"{self.ctx.frontend_url}#/panel/suscripcion?{stripe_query}",
                        wait_until="networkidle",
                    )
                    page.locator("midoc-panel-doctor, #route-label").first.wait_for(state="visible", timeout=15000)
                    page.wait_for_load_state("networkidle")
                    self.assertIn("#/panel/suscripcion", page.url)
                    assert_no_horizontal_overflow(page)
                    self.assertEqual(dialogs, [])
                    self.assertFalse(errors, errors)
            return
        tokens = (self.ctx.repo_root / "frontend" / "src" / "styles" / "_tokens.css").read_text(encoding="utf-8")
        self.assertIn("--color-primary: #246b59", tokens)

    def test_t4_07_private_clinical_document_all_formats_lifecycle(self) -> None:
        p_tok, p_user = register_patient(self.client)
        d_tok, _, d_id = register_and_subscribe_doctor(self.ctx, self.client)
        self.client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)

        self.assertIn(
            self.client.post("/api/records/documents", {"name": "bad.exe", "contentType": "application/x-msdownload", "size": 500}, token=p_tok).status,
            (400, 415),
        )
        self.assertIn(
            self.client.post("/api/records/documents", {"name": "big.pdf", "contentType": "application/pdf", "size": 11 * 1024 * 1024}, token=p_tok).status,
            (400, 413),
        )
        files = [
            ("doc.pdf", "application/pdf", b"%PDF-1.4\n% T4-07\n%%EOF\n"),
            ("img.jpg", "image/jpeg", b"\xff\xd8\xff\xe0T4JPG"),
            ("img.png", "image/png", b"\x89PNG\r\n\x1a\nT4PNG"),
            ("scan.dcm", "application/dicom", b"DICM-T4-07"),
        ]
        if not s3_is_configured(self.ctx):
            for fname, mime, data in files:
                req = self.client.post("/api/records/documents", {"name": fname, "contentType": mime, "size": len(data)}, token=p_tok)
                self.assertEqual(req.status, 503, req.text)
            return

        created = []
        for fname, mime, data in files:
            req = self.client.post("/api/records/documents", {"name": fname, "contentType": mime, "size": len(data)}, token=p_tok)
            self.assertEqual(req.status, 201, req.text)
            up = self.client.upload_presigned_post(req.data["url"], req.data["fields"], fname, mime, data)
            self.assertIn(up.status, (200, 201, 204))
            created.append((req.data["id"], data))

        listed = self.client.get("/api/records/documents", query={"patientId": p_user["id"]}, token=d_tok).data
        self.assertEqual(len(listed), 4)
        for doc_id, expected in created:
            row = next(d for d in listed if d["id"] == doc_id)
            self.assertEqual(self.client.download_url(row["downloadUrl"]).body_bytes, expected)
            self.assertEqual(self.client.delete(f"/api/records/documents/{doc_id}", token=p_tok).status, 200)
        self.assertEqual(self.client.get("/api/records/documents", token=p_tok).data, [])

    def test_t4_08_eventbridge_reminder_and_cross_actor_inbox(self) -> None:
        d_tok, d_user, d_id = register_and_subscribe_doctor(self.ctx, self.client, with_schedule=False)
        p_tok, p_user = register_patient(self.client)
        slot_24h = setup_slot_within_24h(self.ctx, self.client, d_tok, d_id)
        self.assertEqual(
            self.client.post("/api/appointments", {"doctorId": d_id, "dateTime": slot_24h}, token=p_tok).status,
            201,
        )
        if self.ctx.mode == "self-test":
            self.assertEqual(self.client.post("/__reminders/run", {}).status, 200)
            self.assertEqual(self.client.post("/__reminders/run", {}).status, 200)
        elif self.ctx.target == "cloud":
            res1 = invoke_reminders_lambda(self.ctx)
            res2 = invoke_reminders_lambda(self.ctx)
            self.assertEqual(res1["payload"].get("status"), "ok", res1)
            self.assertEqual(res2["payload"].get("status"), "ok", res2)
        else:
            rem_tf = get_tf_content(self.ctx, "reminders.tf")
            self.assertIn("rate(15 minutes)", rem_tf)
            self.assertIn("midoc.reminders", rem_tf)

        n_p = self.client.get("/api/notifications", token=p_tok).data
        rems = [n for n in n_p if n["type"] == "RECORDATORIO_CITA"]
        self.assertEqual(len(rems), 1, f"Expected 1 deduplicated RECORDATORIO_CITA, got {n_p}")
        self.assertEqual(self.client.post("/api/messages", {"recipientId": d_user["id"], "content": "Nos vemos mañana"}, token=p_tok).status, 201)
        self.assertEqual(self.client.get(f"/api/messages/{p_user['id']}", token=d_tok).status, 200)
        n_d = self.client.get("/api/notifications", token=d_tok).data
        self.assertTrue(any(n["type"] in ("CITA_NUEVA", "MENSAJE_NUEVO") for n in n_d))
        self.assertEqual(self.client.put(f"/api/notifications/{rems[0]['id']}/read", {}, token=p_tok).status, 200)

    def test_t4_09_production_cloud_readiness_observability_and_governance(self) -> None:
        ok, msg = check_terraform_fmt_and_validate(self.ctx)
        self.assertTrue(ok, msg)
        self.assertIn("MiDoc", get_tf_content(self.ctx, "monitoring.tf"))
        self.assertIn("unittest", get_workflow_text(self.ctx, "ci.yml") or "")
        self.assertIn("main", get_workflow_text(self.ctx, "cd.yml") or "")
        for doc_path in ("docs/EVALUACION-INTEGRAL.md", "docs/PAGOS-STRIPE.md", "docs/OBSERVABILIDAD-Y-CICD.md", "docs/CIERRE-AWS.md"):
            self.assertIsNotNone(get_doc_text(self.ctx, doc_path), f"Missing {doc_path}")
        self.assertEqual(resolve_markdown_links(self.ctx, ["README.md", "docs/API.md", "docs/DEPLOYMENT.md"]), [])
        if self.ctx.mode == "self-test":
            self.assertTrue(collect_emf_telemetry(self.ctx))
        elif self.ctx.target == "cloud":
            names = wait_for_cloudwatch_metrics(self.ctx, ("RequestLatencyMs",), timeout_s=60.0)
            self.assertIn("RequestLatencyMs", names)
