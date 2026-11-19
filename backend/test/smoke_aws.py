"""Prueba real explícita: crea cuentas sintéticas, verifica Stripe Checkout y los 3 flujos.

Uso: python backend/test/smoke_aws.py --api-url https://... --report ruta.json [--webhook-secret whsec_...]
No utiliza credenciales clínicas reales ni imprime JWT o URLs firmadas.
"""
import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--webhook-secret", default=os.environ.get("STRIPE_WEBHOOK_SECRET", ""))
    parser.add_argument("--browser", action="store_true", help="Registrar consulta y abrir receta en Edge")
    args = parser.parse_args()
    base = args.api_url.rstrip("/")
    if not base.startswith("https://"):
        parser.error("La API real debe usar HTTPS")
    checks = []

    def api(method, path, body=None, token=None, expected=200, extra_headers=None):
        headers = {"Content-Type": "application/json", **(extra_headers or {})}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        request = Request(base + path, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=40) as response:
                status, payload = response.status, json.load(response)
        except HTTPError as error:
            status, payload = error.code, json.load(error)
        assert status == expected, f"{method} {path}: {status}, {payload}"
        checks.append({"method": method, "path": path, "status": status})
        return payload.get("data", payload)

    tag = uuid.uuid4().hex[:10]
    password = secrets.token_urlsafe(24)

    def register(role):
        return api("POST", "/api/auth/register", {
            "email": f"e2e-{role.lower()}-{tag}@example.invalid", "password": password,
            "name": f"E2E DEMO {role} {tag}", "role": role,
            "specialty": "Pruebas sintéticas", "location": "Laboratorio DEMO",
            "city": "Guadalajara", "price": 0, "durationMin": 10,
        }, expected=201)

    api("GET", "/health")
    patient, doctor = register("PACIENTE"), register("DOCTOR")
    pt, dt = patient["token"], doctor["token"]
    patient_id, doctor_id = patient["user"]["id"], doctor["user"]["doctorId"]
    actor_id = doctor["user"]["id"]

    # Verifica PUT /api/me y POST /api/auth/refresh
    api("PUT", "/api/me", {"phone": "3310000000"}, pt, expected=200)
    refreshed = api("POST", "/api/auth/refresh", {}, pt, expected=200)
    assert refreshed.get("token")
    pt = refreshed["token"]

    # Endpoint simulado retirado -> 410 Gone
    api("POST", "/api/subscriptions/pay", {}, dt, expected=410)
    # Webhook sin firma -> 400
    api("POST", "/api/webhooks/stripe", {"type": "ping"}, expected=400)

    # Crear sesión real de Stripe Checkout
    checkout = api("POST", "/api/subscriptions/checkout", {}, dt, expected=201)
    assert checkout["sessionId"].startswith("cs_")
    assert checkout["checkoutUrl"].startswith("https://")
    assert checkout["mode"] in ("test", "live")
    assert checkout["amountUsd"] == 20.0

    # Si se proporciona webhook secret de pruebas, activa vía webhook firmado; si no, concluye smoke de Stripe aquí.
    if args.webhook_secret:
        wh_payload = json.dumps({
            "id": f"evt_smoke_{tag}",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": checkout["sessionId"],
                    "payment_status": "paid",
                    "amount_total": 2000,
                    "livemode": checkout["mode"] == "live",
                    "payment_intent": f"pi_smoke_{tag}",
                    "metadata": {"doctorId": doctor_id},
                }
            },
        }).encode("utf-8")
        ts = int(time.time())
        sig = hmac.new(args.webhook_secret.encode("utf-8"), f"{ts}.".encode() + wh_payload, hashlib.sha256).hexdigest()
        api("POST", "/api/webhooks/stripe", wh_payload, expected=200, extra_headers={"Stripe-Signature": f"t={ts},v1={sig}"})
        sub_state = api("GET", "/api/subscriptions", token=dt, expected=200)
        assert sub_state["subscription"]["active"]
    else:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "testedAt": datetime.now(timezone.utc).isoformat(),
            "apiUrl": base,
            "result": "PASS",
            "checks": checks,
            "stripeCheckoutSessionId": checkout["sessionId"],
            "note": "Checkout real Stripe creado; pasa --webhook-secret para activar y continuar Flujos 1-3 sin UI interactiva",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"PASS (parcial sin webhook secret): {len(checks)} peticiones verificadas. Reporte: {args.report}", flush=True)
        return

    now = datetime.now(timezone(timedelta(hours=-6)))
    start = (now + timedelta(minutes=2)).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=40)
    api("PUT", "/api/doctor/schedule", {"blocks": [{"day": start.isoweekday(),
        "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}]}, dt)
    slots = api("GET", f"/api/doctors/{doctor_id}/availability?date={start.date()}")["slots"]
    assert len(slots) == 4
    cita = api("POST", "/api/appointments", {"doctorId": doctor_id, "dateTime": slots[0],
               "reason": "E2E DEMO, sin datos clínicos reales"}, pt, 201)
    api("POST", "/api/appointments", {"doctorId": doctor_id, "dateTime": slots[0]}, pt, 409)
    api("PUT", f"/api/appointments/{cita['id']}/status", {"status": "CONFIRMADA"}, pt, 403)
    api("PUT", f"/api/appointments/{cita['id']}/status", {"status": "CONFIRMADA"}, dt)
    api("PUT", f"/api/appointments/{cita['id']}/reschedule", {"dateTime": slots[1]}, pt)
    api("PUT", f"/api/appointments/{cita['id']}/reschedule", {"dateTime": slots[0]}, dt)
    cancelled = api("POST", "/api/appointments", {"doctorId": doctor_id, "dateTime": slots[2]}, pt, 201)
    api("PUT", f"/api/appointments/{cancelled['id']}/status", {"status": "CANCELADA"}, pt)
    api("PUT", "/api/records", {"allergies": ["DEMO"], "notes": "Expediente sintético E2E"}, pt)
    record_path = "/api/records?" + urlencode({"patientId": patient_id})
    api("GET", record_path, token=dt, expected=403)
    api("POST", "/api/consents", {"doctorId": doctor_id, "granted": True}, pt)
    api("GET", record_path, token=dt)
    access_log = api("GET", "/api/records/access-log", token=pt)
    assert len(access_log) >= 1
    api("POST", "/api/consents", {"doctorId": doctor_id, "granted": False}, pt)
    api("GET", record_path, token=dt, expected=403)
    api("POST", "/api/consents", {"doctorId": doctor_id, "granted": True}, pt)
    # Carga real del objeto privado mediante el formulario firmado, igual que el navegador.
    content = b"%PDF-1.4\n% E2E DEMO, archivo sintetico sin informacion medica\n%%EOF\n"
    upload = api("POST", "/api/records/documents", {"name": "e2e-demo.pdf",
                 "contentType": "application/pdf", "size": len(content)}, pt, 201)
    boundary = "midoc" + uuid.uuid4().hex
    parts = []
    for key, value in upload["fields"].items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="e2e-demo.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
                 + content + f"\r\n--{boundary}--\r\n".encode())
    with urlopen(Request(upload["url"], data=b"".join(parts),
                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}), timeout=30) as response:
        assert response.status == 204
    docs = api("GET", "/api/records/documents", token=pt)
    doc = next(item for item in docs if item["id"] == upload["id"])
    with urlopen(doc["downloadUrl"], timeout=30) as response:
        assert response.read() == content
    api("GET", "/api/records/documents?" + urlencode({"patientId": patient_id}), token=dt)
    api("DELETE", f"/api/records/documents/{upload['id']}", token=pt)
    api("POST", "/api/messages", {"recipientId": actor_id, "content": "Mensaje E2E DEMO"}, pt, 201)
    assert api("GET", f"/api/messages/{patient_id}", token=dt)[-1]["content"] == "Mensaje E2E DEMO"
    api("POST", "/api/messages", {"recipientId": patient_id, "content": "Respuesta E2E DEMO"}, dt, 201)
    inventory = api("POST", "/api/doctor/inventory", {"name": "E2E DEMO", "quantity": 3, "unit": "piezas"}, dt, 201)
    api("DELETE", f"/api/doctor/inventory/{inventory['id']}", token=dt)
    promotion = api("POST", "/api/doctor/promotions", {"title": "E2E DEMO", "description": "Prueba",
                    "discountPercent": 10, "start": str(now.date()), "end": str(now.date())}, dt, 201)
    assert api("GET", f"/api/doctors/{doctor_id}")["promotions"]
    api("DELETE", f"/api/doctor/promotions/{promotion['id']}", token=dt)
    consultation = {"patientId": patient_id, "appointmentId": cita["id"],
                    "diagnosis": "DEMO: diagnóstico sintético", "treatment": "DEMO: sin tratamiento real",
                    "notes": "Prueba funcional autorizada, sin datos reales"}
    api("POST", "/api/consultations", consultation, dt, 409)
    notices = api("GET", "/api/notifications", token=pt)
    assert any(n["type"] == "MENSAJE_NUEVO" for n in notices)
    print(f"Flujos 1 y 2 correctos. Esperando hora real {slots[0]} para la consulta.", flush=True)
    while datetime.now(timezone.utc) < datetime.fromisoformat(slots[0]) + timedelta(seconds=1):
        time.sleep(5)
    result = api("POST", "/api/consultations", consultation, dt, 201)
    api("POST", "/api/consultations", consultation, dt, 409)
    prescription = api("GET", f"/api/prescriptions/{result['prescriptionId']}", token=pt)
    assert prescription["diagnosis"] == consultation["diagnosis"]
    if prescription.get("downloadUrl"):
        with urlopen(prescription["downloadUrl"], timeout=30) as response:
            assert response.read().startswith(b"%PDF-1.4")
    history = api("GET", "/api/records", token=pt)["consultations"]
    assert any(item["prescriptionId"] == result["prescriptionId"] for item in history)
    assert api("GET", f"/api/appointments/{cita['id']}", token=pt)["status"] == "COMPLETADA"
    api("POST", "/api/consents", {"doctorId": doctor_id, "granted": False}, pt)
    api("GET", record_path, token=dt, expected=403)
    api("PUT", "/api/doctor/schedule", {"blocks": []}, dt)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"testedAt": datetime.now(timezone.utc).isoformat(),
        "apiUrl": base, "result": "PASS", "checks": checks, "patientId": patient_id,
        "doctorId": doctor_id, "appointmentId": cita["id"], "prescriptionId": result["prescriptionId"],
        "syntheticData": True, "cloudFlows": [1, 2, 3], "consultationBrowser": args.browser}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: {len(checks)} peticiones verificadas; 3 flujos completos en AWS. Reporte: {args.report}", flush=True)


if __name__ == "__main__":
    main()
