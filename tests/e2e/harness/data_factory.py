"""Synthetic data builders and opaque-box actor setup helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import time
from typing import Any
import uuid

from .browser_driver import open_browser_page, playwright_available
from .config import ActiveContext
from .http_client import HttpClient


UTC_MINUS_6 = timezone(timedelta(hours=-6))


def unique_email(prefix: str = "e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.invalid"


def strong_password() -> str:
    return "MiDocTest2026!9"


def utc6_now() -> datetime:
    return datetime.now(UTC_MINUS_6)


def future_date_str(days_ahead: int = 3) -> str:
    return (utc6_now().date() + timedelta(days=days_ahead)).isoformat()


def s3_is_configured(ctx: ActiveContext) -> bool:
    """True in self-test, cloud, or local mode when MEDICAL_DOCUMENTS_BUCKET is configured."""
    if ctx.mode == "self-test" or ctx.target == "cloud":
        return True
    return bool(os.environ.get("MEDICAL_DOCUMENTS_BUCKET") or os.environ.get("DOCUMENTS_BUCKET"))


def sign_stripe_webhook_payload(
    payload_bytes: bytes,
    webhook_secret: str,
    timestamp: int | None = None,
) -> str:
    t = int(timestamp if timestamp is not None else time.time())
    signed = f"{t}.".encode("utf-8") + payload_bytes
    v1 = hmac.new(webhook_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def send_live_signed_webhook(
    client: HttpClient,
    *,
    webhook_secret: str,
    session_id: str,
    doctor_id: str,
    user_id: str,
    mode: str = "test",
    event_id: str | None = None,
) -> tuple[int, Any]:
    event = {
        "id": event_id or f"evt_e2e_{uuid.uuid4().hex[:24]}",
        "object": "event",
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "mode": "payment",
                "payment_status": "paid",
                "status": "complete",
                "amount_total": 2000,
                "currency": "usd",
                "livemode": (mode == "live"),
                "client_reference_id": doctor_id,
                "metadata": {
                    "doctorId": doctor_id,
                    "userId": user_id,
                    "paymentMode": mode,
                },
                "payment_intent": f"pi_e2e_{uuid.uuid4().hex[:20]}",
            }
        },
    }
    raw = json.dumps(event, ensure_ascii=False).encode("utf-8")
    sig = sign_stripe_webhook_payload(raw, webhook_secret)
    resp = client.post(
        "/api/webhooks/stripe",
        raw_bytes=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": sig},
    )
    return resp.status, resp.data


def register_patient(
    client: HttpClient,
    *,
    name: str = "Paciente E2E",
    email: str | None = None,
    password: str | None = None,
    phone: str | None = "5512345678",
) -> tuple[str, dict[str, Any]]:
    pw = password or strong_password()
    em = email or unique_email("paciente")
    resp = client.post(
        "/api/auth/register",
        {
            "email": em,
            "password": pw,
            "role": "PACIENTE",
            "name": name,
            "phone": phone,
        },
    )
    assert resp.status == 201, f"Patient register failed ({resp.status}): {resp.text}"
    return resp.json_data["token"], {**resp.json_data["user"], "password": pw}


def register_doctor(
    client: HttpClient,
    *,
    role: str = "DOCTOR",
    name: str = "Dr. E2E Prueba",
    specialty: str = "Cardiología",
    location: str = "Colonia Roma",
    city: str = "CDMX",
    price: float = 500.0,
    duration_min: int = 30,
    email: str | None = None,
    password: str | None = None,
) -> tuple[str, dict[str, Any], str]:
    pw = password or strong_password()
    em = email or unique_email(role.lower())
    resp = client.post(
        "/api/auth/register",
        {
            "email": em,
            "password": pw,
            "role": role,
            "name": name,
            "specialty": specialty,
            "location": location,
            "city": city,
            "description": "Profesional sintético para pruebas E2E.",
            "price": price,
            "durationMin": duration_min,
        },
    )
    assert resp.status == 201, f"{role} register failed ({resp.status}): {resp.text}"
    user = {**resp.json_data["user"], "password": pw}
    return resp.json_data["token"], user, user["doctorId"]


def _complete_stripe_checkout_in_browser(ctx: ActiveContext, checkout_url: str) -> None:
    with open_browser_page(ctx) as (page, _, _):
        page.goto(checkout_url, wait_until="domcontentloaded")
        # Support Stripe test Checkout page when opened interactively via Playwright
        email_inp = page.locator("input#email, input[name='email']").first
        if email_inp.count() > 0:
            email_inp.fill("e2e-stripe@example.invalid")
        card_inp = page.locator("input#cardNumber, input[name='cardNumber']").first
        if card_inp.count() > 0:
            card_inp.fill("4242424242424242")
            page.locator("input#cardExpiry, input[name='cardExpiry']").first.fill("1230")
            page.locator("input#cardCvc, input[name='cardCvc']").first.fill("424")
            name_inp = page.locator("input#billingName, input[name='billingName']").first
            if name_inp.count() > 0:
                name_inp.fill("MiDoc E2E")
            submit = page.locator("button[type='submit'], button.SubmitButton").first
            if submit.count() > 0:
                submit.click()
                page.wait_for_url("**stripe_status=success**", timeout=30000)


def subscribe_doctor_via_stripe(
    ctx: ActiveContext,
    client: HttpClient,
    doctor_token: str,
    *,
    via_webhook: bool = False,
    brand: str = "visa",
    last4: str = "4242",
) -> dict[str, Any]:
    chk = client.post("/api/subscriptions/checkout", {}, token=doctor_token)
    assert chk.status == 201, f"Checkout failed ({chk.status}): {chk.text}"
    session_id = chk.data["sessionId"]
    checkout_url = chk.data["checkoutUrl"]
    mode = chk.data.get("mode", "test")

    if ctx.stripe_mode == "mock":
        assert ctx.stripe_mock is not None
        if via_webhook:
            st, body = ctx.stripe_mock.send_webhook(ctx.api_url, session_id)
            assert st == 200, f"Webhook activation failed ({st}): {body}"
            subs = client.get("/api/subscriptions", token=doctor_token)
            assert subs.status == 200, subs.text
            return {"sessionId": session_id, "subscription": subs.data["subscription"], "webhook": body}
        ctx.stripe_mock.complete_session(session_id, brand=brand, last4=last4)
        conf = client.post("/api/subscriptions/confirm", {"sessionId": session_id}, token=doctor_token)
        assert conf.status == 200, f"Subscription confirm failed ({conf.status}): {conf.text}"
        return conf.data

    # live_cloud mode: authentic Stripe test-mode paths (no unconditional AssertionError)
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if webhook_secret:
        me = client.get("/api/me", token=doctor_token)
        assert me.status == 200, f"Failed fetching /api/me for live_cloud webhook: {me.text}"
        st, wh_body = send_live_signed_webhook(
            client,
            webhook_secret=webhook_secret,
            session_id=session_id,
            doctor_id=me.data["doctorId"],
            user_id=me.data["id"],
            mode=mode,
        )
        assert st == 200, f"live_cloud signed webhook activation failed ({st}): {wh_body}"
        subs = client.get("/api/subscriptions", token=doctor_token)
        assert subs.status == 200 and subs.data.get("subscription"), f"Subscription inactive after webhook: {subs.text}"
        return {"sessionId": session_id, "subscription": subs.data["subscription"], "webhook": wh_body}

    if ctx.with_browser and playwright_available():
        _complete_stripe_checkout_in_browser(ctx, checkout_url)
        conf = client.post("/api/subscriptions/confirm", {"sessionId": session_id}, token=doctor_token)
        assert conf.status == 200, f"live_cloud browser confirm failed ({conf.status}): {conf.text}"
        return conf.data

    raise RuntimeError(
        "live_cloud Stripe completion requires STRIPE_WEBHOOK_SECRET in env (for signed webhook activation) "
        "or `--with-browser` with Playwright installed to complete Stripe Checkout test card entry."
    )


def register_and_subscribe_doctor(
    ctx: ActiveContext,
    client: HttpClient,
    *,
    role: str = "DOCTOR",
    name: str = "Dr. E2E Suscrito",
    specialty: str = "Medicina General",
    location: str = "Polanco",
    city: str = "CDMX",
    price: float = 500.0,
    duration_min: int = 30,
    with_schedule: bool = True,
) -> tuple[str, dict[str, Any], str]:
    token, user, doctor_id = register_doctor(
        client,
        role=role,
        name=name,
        specialty=specialty,
        location=location,
        city=city,
        price=price,
        duration_min=duration_min,
    )
    subscribe_doctor_via_stripe(ctx, client, token)
    if with_schedule:
        blocks = [{"day": d, "start": "08:00", "end": "18:00"} for d in range(1, 8)]
        sch = client.put("/api/doctor/schedule", {"blocks": blocks}, token=token)
        assert sch.status == 200, f"Schedule failed ({sch.status}): {sch.text}"
    return token, user, doctor_id


def next_slot_window(
    ctx: ActiveContext,
    *,
    min_buffer_s: int = 15,
    block_minutes: int = 20,
) -> tuple[datetime, datetime]:
    """
    Pick an upcoming whole-minute slot window without 9-hour midnight rollovers.
    Near 23:50–23:59 UTC-6, rolls cleanly to tomorrow 00:00 (max ~10m wait, never 09:00).
    """
    now = ctx.self_test_server._now() if (ctx.mode == "self-test" and ctx.self_test_server) else utc6_now()
    lead_min = 2 if (ctx.mode == "live" and now.second >= (60 - min_buffer_s)) else 1
    start_dt = (now + timedelta(minutes=lead_min)).replace(second=0, microsecond=0)
    end_dt = start_dt + timedelta(minutes=block_minutes)
    if end_dt.date() != start_dt.date():
        if block_minutes <= 10 and (start_dt + timedelta(minutes=10)).date() == start_dt.date():
            end_dt = start_dt + timedelta(minutes=10)
        else:
            start_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(minutes=block_minutes)
    return start_dt, end_dt


def setup_slot_within_24h(
    ctx: ActiveContext,
    client: HttpClient,
    doctor_token: str,
    doctor_id: str,
) -> str:
    """Configure a schedule block guaranteed to yield a slot strictly within (now, now + 24h]."""
    now = ctx.self_test_server._now() if (ctx.mode == "self-test" and ctx.self_test_server) else utc6_now()
    start_dt = (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(hours=2)
    if end_dt.date() != start_dt.date():
        start_dt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(hours=2)
    sch = client.put(
        "/api/doctor/schedule",
        {
            "blocks": [
                {
                    "day": start_dt.isoweekday(),
                    "start": start_dt.strftime("%H:%M"),
                    "end": end_dt.strftime("%H:%M"),
                }
            ]
        },
        token=doctor_token,
    )
    assert sch.status == 200, f"Schedule failed: {sch.text}"
    avail = client.get(f"/api/doctors/{doctor_id}/availability", query={"date": start_dt.date().isoformat()})
    assert avail.status == 200 and avail.data["slots"], f"No <=24h slots returned: {avail.text}"
    return avail.data["slots"][0]


def wait_until_slot_started(ctx: ActiveContext, slot_iso: str) -> None:
    """
    Advance simulated clock in `--mode self-test`, or genuinely wait until slot start in `--mode live`.
    """
    slot_dt = datetime.fromisoformat(slot_iso)
    if ctx.mode == "self-test" and ctx.self_test_server is not None:
        now = ctx.self_test_server._now()
        delta = (slot_dt - now).total_seconds() + 2.0
        if delta > 0:
            resp = ctx.client().post("/__selftest/clock/advance", {"seconds": delta})
            assert resp.status == 200
        return
    # Live mode: genuine wall-clock wait (never fake/backdoor)
    while datetime.now(timezone.utc) < slot_dt.astimezone(timezone.utc) + timedelta(seconds=1):
        time.sleep(1.0)


def _book_slot_bundle(
    ctx: ActiveContext,
    client: HttpClient,
    *,
    start_dt: datetime,
    end_dt: datetime,
    grant_consent: bool = True,
    confirm_appt: bool = True,
) -> dict[str, Any]:
    d_tok, d_user, d_id = register_and_subscribe_doctor(
        ctx, client, duration_min=10, with_schedule=False
    )
    p_tok, p_user = register_patient(client)

    sch = client.put(
        "/api/doctor/schedule",
        {
            "blocks": [
                {
                    "day": start_dt.isoweekday(),
                    "start": start_dt.strftime("%H:%M"),
                    "end": end_dt.strftime("%H:%M"),
                }
            ]
        },
        token=d_tok,
    )
    assert sch.status == 200, f"Schedule failed: {sch.text}"

    avail = client.get(f"/api/doctors/{d_id}/availability", query={"date": start_dt.date().isoformat()})
    assert avail.status == 200 and avail.data["slots"], f"No slots returned: {avail.text}"
    slot = avail.data["slots"][0]

    appt_resp = client.post(
        "/api/appointments",
        {"doctorId": d_id, "dateTime": slot, "reason": "Consulta E2E"},
        token=p_tok,
    )
    assert appt_resp.status == 201, f"Book failed: {appt_resp.text}"
    appt = appt_resp.data

    if confirm_appt:
        st = client.put(f"/api/appointments/{appt['id']}/status", {"status": "CONFIRMADA"}, token=d_tok)
        assert st.status == 200, f"Confirm failed: {st.text}"

    if grant_consent:
        con = client.post("/api/consents", {"doctorId": d_id, "granted": True}, token=p_tok)
        assert con.status == 200, f"Consent failed: {con.text}"

    return {
        "doctorToken": d_tok,
        "doctorUser": d_user,
        "doctorId": d_id,
        "patientToken": p_tok,
        "patientUser": p_user,
        "patientId": p_user["id"],
        "appointment": appt,
        "slot": slot,
    }


def prepare_started_appointments(
    ctx: ActiveContext,
    client: HttpClient,
    count: int,
    *,
    grant_consent: bool = True,
    confirm_appt: bool = True,
) -> list[dict[str, Any]]:
    """
    Pre-book `count` completely independent (doctor, patient) pairs sharing ONE slot boundary
    so live-mode tests wait once (~60s) instead of `count * 60s`.
    """
    if count <= 0:
        return []
    start_dt, end_dt = next_slot_window(ctx, min_buffer_s=30, block_minutes=20)
    bundles = [
        _book_slot_bundle(
            ctx,
            client,
            start_dt=start_dt,
            end_dt=end_dt,
            grant_consent=grant_consent,
            confirm_appt=confirm_appt,
        )
        for _ in range(count)
    ]
    wait_until_slot_started(ctx, bundles[0]["slot"])
    return bundles


def setup_started_appointment(
    ctx: ActiveContext,
    client: HttpClient,
    *,
    grant_consent: bool = True,
    confirm_appt: bool = True,
    prebooked_queue: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create (or pop pre-booked) subscribed doctor + patient + started appointment."""
    if prebooked_queue:
        return prebooked_queue.pop(0)
    start_dt, end_dt = next_slot_window(ctx, min_buffer_s=15, block_minutes=20)
    bundle = _book_slot_bundle(
        ctx,
        client,
        start_dt=start_dt,
        end_dt=end_dt,
        grant_consent=grant_consent,
        confirm_appt=confirm_appt,
    )
    wait_until_slot_started(ctx, bundle["slot"])
    return bundle


def verify_pdf_bytes(raw_bytes: bytes) -> None:
    assert raw_bytes.startswith(b"%PDF-"), f"Expected %PDF- header, got {raw_bytes[:20]!r}"
    try:
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw_bytes))
        assert len(reader.pages) >= 1, "PDF has zero pages"
    except ImportError:
        assert b"%%EOF" in raw_bytes, "PDF missing %%EOF trailer"
