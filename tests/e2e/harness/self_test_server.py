"""In-harness stateful contract fixture server for `--mode self-test` ONLY.

STRICT INTEGRITY RULE:
This module MUST NEVER be imported or executed when `--mode live` is active.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, time as dtime, timedelta, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import uuid

from .self_test_fixtures import SELF_TEST_HTML_SHELL, get_self_test_config_json


UTC_MINUS_6 = timezone(timedelta(hours=-6))
VALID_ROLES = {"PACIENTE", "DOCTOR", "CLINICA"}
VALID_SEX = {"FEMENINO", "MASCULINO", "OTRO"}
VALID_BLOOD = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}
VALID_APPT_STATUS = {"PENDIENTE", "CONFIRMADA", "CANCELADA", "COMPLETADA"}
ALLOWED_DOC_EXT_MIME = {
    ".pdf": {"application/pdf"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".dcm": {"application/dicom"},
    ".dicom": {"application/dicom"},
}
MAX_DOC_SIZE = 10 * 1024 * 1024  # 10 MB


class ApiErr(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    s = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=s, n=16384, r=8, p=1)
    return f"scrypt${s.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$", 2)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _is_valid_uuid_or_id(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    v = value.strip()
    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False


def _minimal_pdf_bytes(title: str, diagnosis: str, treatment: str) -> bytes:
    safe = f"{title} - {diagnosis} - {treatment}".encode("ascii", errors="replace").decode("ascii")
    safe = safe.replace("(", "[").replace(")", "]")[:120]
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("ascii")
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def _parse_multipart_file(content_type: str, raw: bytes) -> tuple[dict[str, str], bytes]:
    match = re.search(r"boundary=([^\s;]+)", content_type or "")
    if not match:
        raise ApiErr(400, "Missing multipart boundary")
    boundary = match.group(1).strip('"').encode("utf-8")
    parts = raw.split(b"--" + boundary)
    fields: dict[str, str] = {}
    file_bytes = b""
    for part in parts:
        if not part or part.strip() in (b"", b"--"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if b"\r\n\r\n" not in part:
            continue
        header_blob, body = part.split(b"\r\n\r\n", 1)
        if body.endswith(b"\r\n"):
            body = body[:-2]
        header_text = header_blob.decode("utf-8", errors="replace")
        name_m = re.search(r'name="([^"]+)"', header_text)
        if not name_m:
            continue
        field_name = name_m.group(1)
        if "filename=" in header_text:
            file_bytes = body
        else:
            fields[field_name] = body.decode("utf-8", errors="replace")
    return fields, file_bytes


class SelfTestServer:
    """Stateful contract fixture server strictly isolated to `--mode self-test`."""

    def __init__(
        self,
        *,
        stripe_base_url: str,
        stripe_secret_key: str,
        stripe_webhook_secret: str,
        payment_mode: str = "test",
        allow_demo_seed: bool = True,
        frontend_base_url: str | None = None,
    ) -> None:
        self.stripe_base_url = stripe_base_url.rstrip("/")
        self.stripe_secret_key = stripe_secret_key
        self.stripe_webhook_secret = stripe_webhook_secret
        self.payment_mode = payment_mode
        self.allow_demo_seed = allow_demo_seed
        self._frontend_base_url_override = frontend_base_url
        self._jwt_secret = "selftest-jwt-secret-key"
        self._s3_secret = b"selftest-s3-presign-secret"
        self._lock = threading.RLock()
        self._clock_offset = timedelta(0)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

        self.users: dict[str, dict[str, Any]] = {}
        self.users_by_email: dict[str, str] = {}
        self.doctors: dict[str, dict[str, Any]] = {}
        self.schedules: dict[str, list[dict[str, Any]]] = {}
        self.subscriptions: dict[str, list[dict[str, Any]]] = {}
        self.stripe_sessions_seen: dict[str, dict[str, Any]] = {}
        self.appointments: dict[str, dict[str, Any]] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.consents: dict[tuple[str, str], dict[str, Any]] = {}
        self.access_log: list[dict[str, Any]] = []
        self.s3_objects: dict[str, dict[str, Any]] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.consultations: dict[str, dict[str, Any]] = {}
        self.prescriptions: dict[str, dict[str, Any]] = {}
        self.inventory: dict[str, dict[str, Any]] = {}
        self.promotions: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self.login_failures: dict[str, list[float]] = {}
        self.emf_metrics: list[dict[str, Any]] = []
        self.structured_logs: list[dict[str, Any]] = []
        self.simulate_ddb_failure: bool = False

        if self.allow_demo_seed:
            self._seed_demo()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def frontend_base_url(self) -> str:
        return self._frontend_base_url_override or f"{self.base_url}/index.html"

    def _now(self) -> datetime:
        return datetime.now(UTC_MINUS_6) + self._clock_offset

    def _today(self) -> date:
        return self._now().date()

    def _emit_emf(self, metric_name: str, value: float, unit: str = "Count") -> None:
        self.emf_metrics.append(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "MiDoc",
                            "Dimensions": [["Service"]],
                            "Metrics": [{"Name": metric_name, "Unit": unit}],
                        }
                    ],
                },
                "Service": "midoc-api",
                metric_name: value,
            }
        )

    def _log_request(self, method: str, path: str, status: int, latency_ms: float) -> None:
        self.structured_logs.append(
            {
                "timestamp": self._now().isoformat(),
                "service": "midoc-api",
                "method": method,
                "path": path,
                "status": status,
                "latencyMs": round(latency_ms, 2),
            }
        )
        self._emit_emf("RequestLatencyMs", latency_ms, "Milliseconds")
        if status >= 500:
            self._emit_emf("ServerErrors", 1, "Count")

    def _seed_demo(self) -> None:
        p_id = str(uuid.uuid4())
        self.users[p_id] = {
            "id": p_id,
            "email": "paciente@midoc.local",
            "passwordHash": _hash_password("paciente-demo"),
            "role": "PACIENTE",
            "name": "Paciente Demo",
            "phone": None,
            "doctorId": None,
        }
        self.users_by_email["paciente@midoc.local"] = p_id

        d_uid = str(uuid.uuid4())
        d_id = str(uuid.uuid4())
        self.users[d_uid] = {
            "id": d_uid,
            "email": "doctor@midoc.local",
            "passwordHash": _hash_password("doctor-demo"),
            "role": "DOCTOR",
            "name": "Dra. Ana López",
            "phone": None,
            "doctorId": d_id,
        }
        self.users_by_email["doctor@midoc.local"] = d_uid
        self.doctors[d_id] = {
            "id": d_id,
            "userId": d_uid,
            "name": "Dra. Ana López",
            "specialty": "Medicina General",
            "location": "Consultorio Centro",
            "city": "CDMX",
            "description": "Atención integral de primer contacto.",
            "price": 500.0,
            "durationMin": 30,
            "type": "DOCTOR",
        }
        self.schedules[d_id] = [
            {"dia_semana": d, "hora_inicio": "09:00", "hora_fin": "18:00"} for d in range(1, 6)
        ]
        today = self._today()
        self.subscriptions[d_id] = [
            {
                "id": str(uuid.uuid4()),
                "doctor_id": d_id,
                "status": "ACTIVA",
                "amount": 20.0,
                "start": today.isoformat(),
                "end": (today + timedelta(days=29)).isoformat(),
                "cardBrand": "visa",
                "cardLast4": "4242",
                "paymentRef": "cs_test_demo_seed",
                "paymentMode": self.payment_mode,
            }
        ]

    def _make_jwt(self, user: dict[str, Any], ttl_seconds: int = 3600) -> str:
        header = _b64u_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
        now_ts = int(time.time())
        payload = _b64u_encode(
            json.dumps(
                {
                    "sub": user["id"],
                    "email": user["email"],
                    "role": user["role"],
                    "name": user["name"],
                    "doctorId": user.get("doctorId"),
                    "iat": now_ts,
                    "exp": now_ts + ttl_seconds,
                }
            ).encode("utf-8")
        )
        signing_input = f"{header}.{payload}".encode("ascii")
        sig = _b64u_encode(hmac.new(self._jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
        return f"{header}.{payload}.{sig}"

    def _verify_jwt(self, auth_header: str | None) -> dict[str, Any]:
        if not auth_header or not auth_header.startswith("Bearer "):
            raise ApiErr(401, "Sesión no iniciada o token faltante")
        token = auth_header[7:].strip()
        parts = token.split(".")
        if len(parts) != 3:
            raise ApiErr(401, "Token JWT inválido")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        expected = _b64u_encode(hmac.new(self._jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(parts[2], expected):
            raise ApiErr(401, "Firma JWT inválida")
        try:
            claims = json.loads(_b64u_decode(parts[1]))
        except Exception as err:
            raise ApiErr(401, "Payload JWT corrupto") from err
        if int(claims.get("exp", 0)) <= int(time.time()):
            raise ApiErr(401, "La sesión expiró")
        user = self.users.get(claims.get("sub", ""))
        if not user:
            raise ApiErr(401, "Usuario no encontrado")
        return user

    def _sign_s3_key(self, key: str, exp: int) -> str:
        msg = f"{key}:{exp}".encode("utf-8")
        return hmac.new(self._s3_secret, msg, hashlib.sha256).hexdigest()

    def _presigned_get_url(self, key: str, ttl: int = 300) -> str:
        exp = int(time.time()) + ttl
        sig = self._sign_s3_key(key, exp)
        return f"{self.base_url}/__s3/download?{urlencode({'key': key, 'exp': exp, 'sig': sig})}"

    def _sub_summary(self, doctor_id: str) -> dict[str, Any] | None:
        subs = self.subscriptions.get(doctor_id, [])
        if not subs:
            return None
        latest = subs[-1]
        today = self._today()
        start_d = date.fromisoformat(latest["start"])
        end_d = date.fromisoformat(latest["end"])
        active = latest["status"] == "ACTIVA" and start_d <= today <= end_d
        return {**latest, "active": active}

    def _require_doctor(self, user: dict[str, Any]) -> str:
        if user["role"] not in ("DOCTOR", "CLINICA"):
            raise ApiErr(403, "Solo cuentas de doctor o clínica pueden realizar esta acción")
        did = user.get("doctorId")
        if not did or did not in self.doctors:
            raise ApiErr(404, "Perfil profesional no encontrado")
        return did

    def _require_active_sub(self, doctor_id: str) -> dict[str, Any]:
        sub = self._sub_summary(doctor_id)
        if not sub or not sub["active"]:
            raise ApiErr(402, "Necesitas una suscripción activa ($20 USD/mes)")
        return sub

    def _stripe_request(self, method: str, path: str, form_data: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        url = f"{self.stripe_base_url}{path}"
        headers = {"Authorization": f"Bearer {self.stripe_secret_key}"}
        raw: bytes | None = None
        if form_data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            raw = urlencode(form_data).encode("utf-8")
        req = Request(url, data=raw, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as err:
            body = err.read().decode("utf-8", errors="replace") if err.fp else "{}"
            try:
                return err.code, json.loads(body)
            except ValueError:
                return err.code, {"error": {"message": body}}

    def _activate_subscription_from_session(
        self,
        *,
        doctor_id: str,
        session_id: str,
        brand: str,
        last4: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        subs = self.subscriptions.setdefault(doctor_id, [])
        existing = next((s for s in subs if s.get("paymentRef") == session_id), None)
        if existing is not None:
            return self._sub_summary(doctor_id), {
                "reference": session_id,
                "cardBrand": existing["cardBrand"],
                "cardLast4": existing["cardLast4"],
                "paymentMode": existing["paymentMode"],
                "amountUsd": 20.0,
            }
        today = self._today()
        current = self._sub_summary(doctor_id)
        if current and current["active"]:
            prev_end = date.fromisoformat(current["end"])
            start_d = date.fromisoformat(current["start"])
            end_d = prev_end + timedelta(days=30)
        else:
            start_d = today
            end_d = today + timedelta(days=29)
        record = {
            "id": str(uuid.uuid4()),
            "doctor_id": doctor_id,
            "status": "ACTIVA",
            "amount": 20.0,
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
            "cardBrand": brand,
            "cardLast4": last4,
            "paymentRef": session_id,
            "paymentMode": self.payment_mode,
        }
        subs.append(record)
        self._emit_emf("PaymentSucceeded", 1, "Count")
        return self._sub_summary(doctor_id), {
            "reference": session_id,
            "cardBrand": brand,
            "cardLast4": last4,
            "paymentMode": self.payment_mode,
            "amountUsd": 20.0,
        }

    def _active_promos(self, doctor_id: str, *, only_active: bool) -> list[dict[str, Any]]:
        today = self._today()
        out = []
        for p in self.promotions.values():
            if p["doctorId"] != doctor_id:
                continue
            s_d = date.fromisoformat(p["start"])
            e_d = date.fromisoformat(p["end"])
            is_active = s_d <= today <= e_d
            if only_active and not is_active:
                continue
            out.append({**p, "active": is_active})
        return out

    def _available_slots(self, doctor_id: str, dia: date, exclude_appt_id: str | None = None) -> list[str]:
        doc = self.doctors[doctor_id]
        dur = int(doc["durationMin"])
        iso_day = dia.isoweekday()
        blocks = [b for b in self.schedules.get(doctor_id, []) if b["dia_semana"] == iso_day]
        occupied = {
            datetime.fromisoformat(a["dateTime"])
            for a in self.appointments.values()
            if a["doctorId"] == doctor_id
            and a["id"] != exclude_appt_id
            and a["status"] != "CANCELADA"
            and datetime.fromisoformat(a["dateTime"]).date() == dia
        }
        now = self._now()
        slots: list[str] = []
        for b in sorted(blocks, key=lambda x: x["hora_inicio"]):
            sh, sm = map(int, b["hora_inicio"].split(":"))
            eh, em = map(int, b["hora_fin"].split(":"))
            cur = datetime.combine(dia, dtime(sh, sm), tzinfo=UTC_MINUS_6)
            end_dt = datetime.combine(dia, dtime(eh, em), tzinfo=UTC_MINUS_6)
            while cur + timedelta(minutes=dur) <= end_dt:
                if cur > now and cur not in occupied:
                    slots.append(cur.isoformat())
                cur += timedelta(minutes=dur)
        return slots

    def _can_message(self, user_a: str, user_b: str) -> bool:
        if user_a == user_b:
            return False
        doc = next((d for d in self.doctors.values() if d["userId"] in (user_a, user_b)), None)
        if not doc:
            return False
        patient_id = user_b if doc["userId"] == user_a else user_a
        has_consent = self.consents.get((patient_id, doc["id"]), {}).get("granted", False)
        has_appt = any(
            a["patientId"] == patient_id and a["doctorId"] == doc["id"] for a in self.appointments.values()
        )
        return bool(has_consent or has_appt)

    def _notify(self, user_id: str, kind: str, title: str, message: str, reference: str | None = None) -> None:
        self.notifications.append(
            {
                "id": str(uuid.uuid4()),
                "userId": user_id,
                "type": kind,
                "title": title,
                "message": message,
                "reference": reference,
                "createdAt": self._now().isoformat(),
                "read": False,
            }
        )

    def _materialize_reminders_for_user(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        uid = user["id"]
        did = user.get("doctorId")
        existing_refs = {n["reference"] for n in self.notifications if n["userId"] == uid and n["reference"]}
        now = self._now()
        for appt in self.appointments.values():
            if appt["patientId"] != uid and appt["doctorId"] != did:
                continue
            if appt["status"] not in ("PENDIENTE", "CONFIRMADA"):
                continue
            dt = datetime.fromisoformat(appt["dateTime"])
            if now < dt <= now + timedelta(hours=24):
                ref = f"recordatorio-cita:{appt['id']}:{dt.isoformat()}"
                if ref not in existing_refs:
                    doc = self.doctors.get(appt["doctorId"], {})
                    self._notify(
                        uid,
                        "RECORDATORIO_CITA",
                        "Tienes una cita próximamente",
                        f"Tienes una cita con {doc.get('name', 'tu profesional')}.",
                        ref,
                    )
                    existing_refs.add(ref)
        if did:
            sub = self._sub_summary(did)
            if sub and sub["active"]:
                days_left = (date.fromisoformat(sub["end"]) - self._today()).days
                if 0 <= days_left <= 7:
                    ref = f"vencimiento-suscripcion:{sub['end']}"
                    if ref not in existing_refs:
                        self._notify(
                            uid,
                            "VENCIMIENTO_SUSCRIPCION",
                            "Tu suscripción está por vencer",
                            f"Tu suscripción vence el {sub['end']}.",
                            ref,
                        )
                        existing_refs.add(ref)
        return [
            {k: v for k, v in n.items() if k != "userId"}
            for n in reversed(self.notifications)
            if n["userId"] == uid
        ]

    def _run_reminders_job(self) -> dict[str, Any]:
        for u in list(self.users.values()):
            self._materialize_reminders_for_user(u)
        self._emit_emf("RemindersJobRuns", 1, "Count")
        return {"job": "reminders", "processedUsers": len(self.users), "status": "ok"}

    def _build_record_view(self, patient_id: str) -> dict[str, Any]:
        pat = self.users[patient_id]
        rec = self.records.get(
            patient_id,
            {
                "patient_id": patient_id,
                "allergies": [],
                "notes": "",
                "birthDate": None,
                "sex": None,
                "bloodType": None,
                "chronicConditions": [],
                "medications": [],
                "updatedAt": None,
            },
        )
        consults = [c for c in self.consultations.values() if c["patientId"] == patient_id]
        consults.sort(key=lambda x: x["dateTime"], reverse=True)
        return {
            **rec,
            "patient": {"id": pat["id"], "name": pat["name"], "email": pat["email"]},
            "consultations": [
                {
                    "prescriptionId": c["prescriptionId"],
                    "appointmentId": c["appointmentId"],
                    "dateTime": c["dateTime"],
                    "doctorId": c["doctorId"],
                    "doctorName": c["doctorName"],
                    "specialty": c["specialty"],
                    "diagnosis": c["diagnosis"],
                    "treatment": c["treatment"],
                    "notes": c["notes"],
                    "createdAt": c["createdAt"],
                }
                for c in consults
            ],
        }

    def _appt_view(self, appt: dict[str, Any]) -> dict[str, Any]:
        doc = self.doctors.get(appt["doctorId"], {})
        pat = self.users.get(appt["patientId"], {})
        rx = next((r for r in self.prescriptions.values() if r["appointmentId"] == appt["id"]), None)
        return {
            **appt,
            "patientName": pat.get("name"),
            "doctorName": doc.get("name"),
            "specialty": doc.get("specialty"),
            "location": doc.get("location"),
            "prescriptionId": rx["id"] if rx else None,
        }

    def _validate_url(self, url: str, name: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ApiErr(400, f"URL inválida en {name}")
        if parsed.scheme == "http" and not parsed.hostname in ("localhost", "127.0.0.1"):
            raise ApiErr(400, f"{name} requiere HTTPS")
        return url

    def start(self) -> "SelfTestServer":
        parent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send(self, status: int, body_bytes: bytes, content_type: str, extra_headers: dict[str, str] | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Stripe-Signature")
                if extra_headers:
                    for k, v in extra_headers.items():
                        self.send_header(k, v)
                self.end_headers()
                if body_bytes:
                    self.wfile.write(body_bytes)

            def _send_json(self, status: int, payload: Any) -> None:
                self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

            def do_OPTIONS(self) -> None:
                origin = self.headers.get("Origin", "")
                extra: dict[str, str] = {}
                if origin and ("127.0.0.1" in origin or "localhost" in origin or origin == parent.base_url):
                    extra["Access-Control-Allow-Origin"] = origin
                elif origin:
                    # Reject untrusted origin on S3 paths
                    if urlparse(self.path).path.startswith("/__s3/"):
                        self.send_response(403)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                self._send(204, b"", "text/plain", extra_headers=extra)

            def _handle(self, method: str) -> None:
                t0 = time.perf_counter()
                parsed = urlparse(self.path)
                path = parsed.path
                query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length > 0 else b""

                # Non-API routes (SPA shell, config.json, mock S3, selftest controls)
                if path in ("/", "/index.html"):
                    self._send(200, SELF_TEST_HTML_SHELL.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path == "/config.json":
                    self._send_json(200, get_self_test_config_json(parent.base_url, parent.payment_mode))
                    return
                if path.startswith("/__s3/upload/") and method == "POST":
                    key = path[len("/__s3/upload/") :].lstrip("/")
                    fields, file_bytes = _parse_multipart_file(self.headers.get("Content-Type", ""), raw)
                    exp = int(fields.get("x-amz-exp", "0") or "0")
                    sig = fields.get("x-amz-sig", "")
                    if exp < int(time.time()) or not hmac.compare_digest(sig, parent._sign_s3_key(key, exp)):
                        self._send(403, b"<Error><Code>AccessDenied</Code></Error>", "application/xml")
                        return
                    with parent._lock:
                        parent.s3_objects[key] = {
                            "bytes": file_bytes,
                            "contentType": fields.get("Content-Type", "application/octet-stream"),
                        }
                    self._send(204, b"", "text/plain")
                    return
                if path == "/__s3/download" and method == "GET":
                    key = query.get("key", "")
                    sig = query.get("sig", "")
                    try:
                        exp = int(query.get("exp", "0"))
                    except ValueError:
                        exp = 0
                    if not sig or exp < int(time.time()) or not hmac.compare_digest(sig, parent._sign_s3_key(key, exp)):
                        self._send(403, b"<Error><Code>SignatureDoesNotMatch</Code></Error>", "application/xml")
                        return
                    with parent._lock:
                        obj = parent.s3_objects.get(key)
                    if obj is None:
                        self._send(404, b"<Error><Code>NoSuchKey</Code></Error>", "application/xml")
                        return
                    self._send(200, obj["bytes"], obj["contentType"])
                    return
                if path == "/__s3/private-raw" and method == "GET":
                    self._send(403, b"<Error><Code>AccessDenied</Code></Error>", "application/xml")
                    return
                if path == "/__selftest/clock/advance" and method == "POST":
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                    secs = float(payload.get("seconds", 0))
                    with parent._lock:
                        parent._clock_offset += timedelta(seconds=secs)
                    self._send_json(200, {"now": parent._now().isoformat()})
                    return
                if path == "/__selftest/metrics" and method == "GET":
                    with parent._lock:
                        self._send_json(200, {"metrics": list(parent.emf_metrics), "logs": list(parent.structured_logs)})
                    return
                if path == "/__selftest/ddb-failure" and method == "POST":
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                    with parent._lock:
                        parent.simulate_ddb_failure = bool(payload.get("enabled", False))
                    self._send_json(200, {"simulateDdbFailure": parent.simulate_ddb_failure})
                    return
                if path == "/__reminders/run" and method == "POST":
                    with parent._lock:
                        res = parent._run_reminders_job()
                    self._send_json(200, res)
                    return

                # Public Stripe Webhook (expects raw JSON + Stripe-Signature)
                if path == "/api/webhooks/stripe" and method == "POST":
                    status = 200
                    try:
                        res = parent._handle_stripe_webhook(self.headers.get("Stripe-Signature"), raw)
                        self._send_json(200, {"data": res})
                    except ApiErr as err:
                        status = err.status
                        parent._emit_emf("PaymentFailed", 1, "Count")
                        self._send_json(err.status, {"error": err.message})
                    finally:
                        parent._log_request(method, path, status, (time.perf_counter() - t0) * 1000)
                    return

                # JSON body parse for REST API
                body: Any = {}
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        parent._log_request(method, path, 400, (time.perf_counter() - t0) * 1000)
                        self._send_json(400, {"error": "El cuerpo debe contener JSON válido"})
                        return
                    if not isinstance(body, dict):
                        parent._log_request(method, path, 400, (time.perf_counter() - t0) * 1000)
                        self._send_json(400, {"error": "El cuerpo JSON debe ser un objeto"})
                        return

                status = 200
                try:
                    status, resp_payload = parent._dispatch(method, path, query, body, self.headers)
                    self._send_json(status, resp_payload)
                except ApiErr as err:
                    status = err.status
                    self._send_json(err.status, {"error": err.message})
                except Exception as exc:
                    status = 500
                    self._send_json(500, {"error": f"Error interno: {exc}"})
                finally:
                    with parent._lock:
                        parent._log_request(method, path, status, (time.perf_counter() - t0) * 1000)

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def do_PUT(self) -> None:
                self._handle("PUT")

            def do_DELETE(self) -> None:
                self._handle("DELETE")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _handle_stripe_webhook(self, sig_header: str | None, raw_body: bytes) -> dict[str, Any]:
        if not sig_header:
            raise ApiErr(400, "Falta encabezado Stripe-Signature")
        parts: dict[str, str] = {}
        for chunk in sig_header.split(","):
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                parts[k.strip()] = v.strip()
        if "t" not in parts or "v1" not in parts:
            raise ApiErr(400, "Formato Stripe-Signature inválido")
        try:
            ts = int(parts["t"])
        except ValueError as err:
            raise ApiErr(400, "Timestamp Stripe inválido") from err
        if abs(int(time.time()) - ts) > 300:
            raise ApiErr(401, "Firma Stripe expirada")
        signed = f"{ts}.".encode("utf-8") + raw_body
        expected = hmac.new(self.stripe_webhook_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(parts["v1"], expected):
            raise ApiErr(401, "Firma Stripe inválida")
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as err:
            raise ApiErr(400, "Evento Stripe JSON inválido") from err
        if event.get("type") == "checkout.session.completed":
            obj = (event.get("data") or {}).get("object") or {}
            sid = obj.get("id")
            meta = obj.get("metadata") or {}
            doctor_id = meta.get("doctorId")
            if sid and doctor_id and doctor_id in self.doctors:
                pi = obj.get("payment_intent") or {}
                pm = (pi.get("payment_method") if isinstance(pi, dict) else {}) or {}
                card = pm.get("card") or {}
                with self._lock:
                    self._activate_subscription_from_session(
                        doctor_id=doctor_id,
                        session_id=sid,
                        brand=card.get("brand", "visa"),
                        last4=card.get("last4", "4242"),
                    )
        return {"received": True}

    def _dispatch(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        body: dict[str, Any],
        headers: Any,
    ) -> tuple[int, dict[str, Any]]:
        parts = [p for p in path.strip("/").split("/") if p]

        # Health
        if method == "GET" and parts == ["health"]:
            return 200, {"status": "ok", "service": "midoc-api"}

        # Retired Fase 2 simulated payment endpoint
        if parts == ["api", "subscriptions", "pay"]:
            raise ApiErr(410, "Endpoint de pago simulado retirado; usa /api/subscriptions/checkout")

        # Auth: register
        if method == "POST" and parts == ["api", "auth", "register"]:
            email = str(body.get("email") or "").strip().lower()
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(email) > 150:
                raise ApiErr(400, "Correo electrónico inválido")
            password = str(body.get("password") or "")
            if len(password) < 8 or len(password) > 128 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
                raise ApiErr(400, "La contraseña debe tener 8-128 caracteres con letras y números")
            role = body.get("role")
            if role not in VALID_ROLES:
                raise ApiErr(400, "Rol inválido")
            name = str(body.get("name") or "").strip()
            if len(name) < 2 or len(name) > 150:
                raise ApiErr(400, "Nombre inválido")
            phone = body.get("phone")
            if phone is not None:
                phone = str(phone).strip()[:20] or None
            with self._lock:
                if email in self.users_by_email:
                    raise ApiErr(409, "Ya existe una cuenta con ese correo")
                uid = str(uuid.uuid4())
                did: str | None = None
                if role in ("DOCTOR", "CLINICA"):
                    specialty = str(body.get("specialty") or "").strip()
                    location = str(body.get("location") or "").strip()
                    if not specialty or len(specialty) > 100 or not location or len(location) > 255:
                        raise ApiErr(400, "Especialidad y ubicación requeridas")
                    city = str(body.get("city") or location).strip()[:100]
                    desc = str(body.get("description") or "").strip()[:2000]
                    try:
                        price = float(body.get("price"))
                    except (TypeError, ValueError) as err:
                        raise ApiErr(400, "Precio inválido") from err
                    if price < 0 or price > 100000:
                        raise ApiErr(400, "Precio fuera de rango")
                    dur = int(body.get("durationMin") or 30)
                    if dur < 10 or dur > 240:
                        raise ApiErr(400, "Duración fuera de rango (10-240)")
                    did = str(uuid.uuid4())
                    self.doctors[did] = {
                        "id": did,
                        "userId": uid,
                        "name": name,
                        "specialty": specialty,
                        "location": location,
                        "city": city,
                        "description": desc,
                        "price": price,
                        "durationMin": dur,
                        "type": role,
                    }
                    self.schedules[did] = []
                user = {
                    "id": uid,
                    "email": email,
                    "passwordHash": _hash_password(password),
                    "role": role,
                    "name": name,
                    "phone": phone,
                    "doctorId": did,
                }
                self.users[uid] = user
                self.users_by_email[email] = uid
                token = self._make_jwt(user)
                return 201, {
                    "token": token,
                    "user": {k: user[k] for k in ("id", "email", "role", "name", "phone", "doctorId")},
                }

        # Auth: login
        if method == "POST" and parts == ["api", "auth", "login"]:
            email = str(body.get("email") or "").strip().lower()
            password = str(body.get("password") or "")
            now_ts = time.time()
            with self._lock:
                fails = [t for t in self.login_failures.get(email, []) if now_ts - t < 60]
                self.login_failures[email] = fails
                if len(fails) >= 5:
                    self._emit_emf("LoginFailures", 1, "Count")
                    raise ApiErr(429, "Demasiados intentos fallidos; intenta de nuevo en un minuto")
                uid = self.users_by_email.get(email)
                user = self.users.get(uid) if uid else None
                if not user or not _verify_password(password, user["passwordHash"]):
                    fails.append(now_ts)
                    self.login_failures[email] = fails
                    self._emit_emf("LoginFailures", 1, "Count")
                    raise ApiErr(401, "Correo o contraseña incorrectos")
                self.login_failures[email] = []
                return 200, {
                    "token": self._make_jwt(user),
                    "user": {k: user[k] for k in ("id", "email", "role", "name", "phone", "doctorId")},
                }

        # Public directory
        if method == "GET" and parts == ["api", "doctors"]:
            spec = str(query.get("specialty") or "").strip().lower()
            loc = str(query.get("location") or "").strip().lower()
            q = str(query.get("q") or "").strip().lower()
            sort_by = str(query.get("sort") or query.get("sortBy") or "NAME").strip().upper()
            with self._lock:
                out = []
                for did, doc in self.doctors.items():
                    sub = self._sub_summary(did)
                    if not sub or not sub["active"]:
                        continue
                    if spec and spec not in doc["specialty"].lower():
                        continue
                    if loc and loc not in doc["location"].lower() and loc not in doc["city"].lower():
                        continue
                    if q and not any(q in doc[f].lower() for f in ("name", "specialty", "location", "city", "description")):
                        continue
                    next_slot = None
                    for off in range(0, 7):
                        cand = self._available_slots(did, self._today() + timedelta(days=off))
                        if cand:
                            next_slot = cand[0]
                            break
                    out.append(
                        {
                            **doc,
                            "promotions": self._active_promos(did, only_active=True),
                            "nextAvailableSlot": next_slot,
                        }
                    )
                if sort_by in ("PRICE", "PRICE_ASC"):
                    out.sort(key=lambda d: (d["price"], d["name"].lower()))
                elif sort_by == "PRICE_DESC":
                    out.sort(key=lambda d: (-d["price"], d["name"].lower()))
                elif sort_by == "AVAILABILITY":
                    out.sort(key=lambda d: d["nextAvailableSlot"] or "9999")
                else:
                    out.sort(key=lambda d: d["name"].lower())
                return 200, {"data": out}

        if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "doctors"]:
            did = parts[2]
            if not _is_valid_uuid_or_id(did):
                raise ApiErr(400, "Identificador de profesional inválido")
            with self._lock:
                doc = self.doctors.get(did)
                sub = self._sub_summary(did) if doc else None
                if not doc or not sub or not sub["active"]:
                    raise ApiErr(404, "Profesional no encontrado")
                return 200, {
                    "data": {
                        **doc,
                        "schedule": list(self.schedules.get(did, [])),
                        "promotions": self._active_promos(did, only_active=True),
                    }
                }

        if method == "GET" and len(parts) == 4 and parts[:2] == ["api", "doctors"] and parts[3] == "availability":
            did = parts[2]
            if not _is_valid_uuid_or_id(did):
                raise ApiErr(400, "Identificador de profesional inválido")
            date_str = query.get("date")
            if not date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                raise ApiErr(400, "Parámetro date requerido en formato YYYY-MM-DD")
            try:
                target_d = date.fromisoformat(date_str)
            except ValueError as err:
                raise ApiErr(400, "Fecha inválida") from err
            with self._lock:
                doc = self.doctors.get(did)
                sub = self._sub_summary(did) if doc else None
                if not doc or not sub or not sub["active"]:
                    raise ApiErr(404, "Profesional no encontrado")
                today = self._today()
                if target_d > today + timedelta(days=90):
                    raise ApiErr(400, "Solo se puede consultar hasta 90 días adelante")
                if target_d < today:
                    return 200, {"data": {"doctorId": did, "date": date_str, "durationMin": doc["durationMin"], "slots": []}}
                slots = self._available_slots(did, target_d)
                return 200, {"data": {"doctorId": did, "date": date_str, "durationMin": doc["durationMin"], "slots": slots}}

        # Authenticated routes
        with self._lock:
            actor = self._verify_jwt(headers.get("Authorization"))

            if method == "POST" and parts == ["api", "auth", "refresh"]:
                return 200, {
                    "token": self._make_jwt(actor),
                    "user": {k: actor[k] for k in ("id", "email", "role", "name", "phone", "doctorId")},
                }

            if method == "GET" and parts == ["api", "me"]:
                prof = {k: actor[k] for k in ("id", "email", "role", "name", "phone", "doctorId")}
                if actor.get("doctorId"):
                    did = actor["doctorId"]
                    prof["doctor"] = {**self.doctors[did], "schedule": list(self.schedules.get(did, []))}
                    prof["subscription"] = self._sub_summary(did)
                return 200, {"data": prof}

            if method == "PUT" and parts == ["api", "me"]:
                # Role is immutable on PUT /api/me (ignored, matching real M2 flujos.py)
                if "newPassword" in body or "currentPassword" in body:
                    cur_pw = str(body.get("currentPassword") or "")
                    new_pw = str(body.get("newPassword") or "")
                    if not _verify_password(cur_pw, actor["passwordHash"]):
                        raise ApiErr(401, "Contraseña actual incorrecta")
                    if len(new_pw) < 8 or not re.search(r"[A-Za-z]", new_pw) or not re.search(r"\d", new_pw):
                        raise ApiErr(400, "La nueva contraseña no cumple la política")
                    actor["passwordHash"] = _hash_password(new_pw)
                new_name = body.get("name") or body.get("nombreCompleto")
                if new_name is not None:
                    n = str(new_name).strip()
                    if len(n) < 2 or len(n) > 150:
                        raise ApiErr(400, "Nombre inválido")
                    actor["name"] = n
                    if actor.get("doctorId"):
                        self.doctors[actor["doctorId"]]["name"] = n
                if "phone" in body:
                    actor["phone"] = str(body["phone"]).strip()[:20] or None
                doc_fields = (
                    "specialty", "especialidad", "location", "ubicacion", "city", "ciudad",
                    "price", "precioConsulta", "durationMin", "duracionCitaMin", "description", "biografia",
                )
                if any(k in body for k in doc_fields):
                    if actor["role"] not in ("DOCTOR", "CLINICA"):
                        raise ApiErr(403, "Los pacientes no pueden editar campos profesionales")
                    doc = self.doctors[actor["doctorId"]]
                    if "specialty" in body or "especialidad" in body:
                        doc["specialty"] = str(body.get("specialty") or body.get("especialidad")).strip()[:100]
                    if "location" in body or "ubicacion" in body:
                        doc["location"] = str(body.get("location") or body.get("ubicacion")).strip()[:255]
                    if "city" in body or "ciudad" in body:
                        doc["city"] = str(body.get("city") or body.get("ciudad")).strip()[:100]
                    if "description" in body or "biografia" in body:
                        doc["description"] = str(body.get("description") or body.get("biografia") or "").strip()[:2000]
                    if "price" in body or "precioConsulta" in body:
                        p = float(body.get("price") if "price" in body else body.get("precioConsulta"))
                        if p < 0 or p > 100000:
                            raise ApiErr(400, "Precio fuera de rango")
                        doc["price"] = p
                    if "durationMin" in body or "duracionCitaMin" in body:
                        d = int(body.get("durationMin") if "durationMin" in body else body.get("duracionCitaMin"))
                        if d < 10 or d > 240:
                            raise ApiErr(400, "Duración fuera de rango")
                        doc["durationMin"] = d
                prof = {k: actor[k] for k in ("id", "email", "role", "name", "phone", "doctorId")}
                if actor.get("doctorId"):
                    did = actor["doctorId"]
                    prof["doctor"] = {**self.doctors[did], "schedule": list(self.schedules.get(did, []))}
                    prof["subscription"] = self._sub_summary(did)
                return 200, {"data": prof}

            # Subscriptions (Stripe)
            if method == "GET" and parts == ["api", "subscriptions"]:
                did = self._require_doctor(actor)
                sub = self._sub_summary(did)
                history = list(reversed(self.subscriptions.get(did, [])))
                return 200, {
                    "data": {
                        "subscription": sub,
                        "paymentMode": self.payment_mode,
                        "history": history,
                    }
                }

            if method == "POST" and parts == ["api", "subscriptions", "checkout"]:
                did = self._require_doctor(actor)
                default_success = f"{self.frontend_base_url}#/panel/suscripcion?stripe_status=success&session_id={{CHECKOUT_SESSION_ID}}"
                default_cancel = f"{self.frontend_base_url}#/panel/suscripcion?stripe_status=cancel"
                success_url = self._validate_url(str(body.get("successUrl") or default_success), "successUrl")
                cancel_url = self._validate_url(str(body.get("cancelUrl") or default_cancel), "cancelUrl")
                form = {
                    "mode": "payment",
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "line_items[0][price_data][currency]": "usd",
                    "line_items[0][price_data][unit_amount]": "2000",
                    "line_items[0][price_data][product_data][name]": "Suscripción mensual MiDoc (30 días)",
                    "line_items[0][quantity]": "1",
                    "metadata[doctorId]": did,
                    "metadata[userId]": actor["id"],
                    "metadata[paymentMode]": self.payment_mode,
                }
                st, s_data = self._stripe_request("POST", "/v1/checkout/sessions", form)
                if st >= 400:
                    self._emit_emf("PaymentFailed", 1, "Count")
                    raise ApiErr(502, "Error creando sesión en Stripe")
                self.stripe_sessions_seen[s_data["id"]] = did
                self._emit_emf("PaymentCheckoutCreated", 1, "Count")
                return 201, {
                    "data": {
                        "sessionId": s_data["id"],
                        "checkoutUrl": s_data["url"],
                        "mode": self.payment_mode,
                        "amountUsd": 20.0,
                    }
                }

            if method == "POST" and parts == ["api", "subscriptions", "confirm"]:
                did = self._require_doctor(actor)
                sid = str(body.get("sessionId") or "").strip()
                if not sid:
                    raise ApiErr(400, "sessionId es obligatorio")
                st, s_data = self._stripe_request(
                    "GET",
                    f"/v1/checkout/sessions/{sid}?expand[]=payment_intent.payment_method",
                )
                if st >= 400:
                    self._emit_emf("PaymentFailed", 1, "Count")
                    raise ApiErr(404 if st == 404 else 502, "Sesión Stripe no encontrada")
                meta = s_data.get("metadata") or {}
                if meta.get("doctorId") != did:
                    self._emit_emf("PaymentFailed", 1, "Count")
                    raise ApiErr(403, "La sesión no pertenece a este profesional")
                if s_data.get("payment_status") != "paid":
                    self._emit_emf("PaymentFailed", 1, "Count")
                    raise ApiErr(402, "El pago en Stripe aún no está completado")
                pi = s_data.get("payment_intent") or {}
                pm = (pi.get("payment_method") if isinstance(pi, dict) else {}) or {}
                card = pm.get("card") or {}
                sub, payment = self._activate_subscription_from_session(
                    doctor_id=did,
                    session_id=sid,
                    brand=card.get("brand", "visa"),
                    last4=card.get("last4", "4242"),
                )
                return 200, {"data": {"subscription": sub, "payment": payment}}

            # Schedule
            if method == "PUT" and parts == ["api", "doctor", "schedule"]:
                did = self._require_doctor(actor)
                blocks = body.get("blocks")
                if not isinstance(blocks, list) or len(blocks) > 30:
                    raise ApiErr(400, "blocks debe ser una lista de máximo 30 elementos")
                parsed_blocks: list[dict[str, Any]] = []
                by_day: dict[int, list[tuple[str, str]]] = {}
                for b in blocks:
                    if not isinstance(b, dict):
                        raise ApiErr(400, "Bloque inválido")
                    day = b.get("day")
                    if not isinstance(day, int) or day < 1 or day > 7:
                        raise ApiErr(400, "day debe estar entre 1 y 7")
                    s_t = str(b.get("start") or "")
                    e_t = str(b.get("end") or "")
                    if not re.match(r"^\d{2}:\d{2}$", s_t) or not re.match(r"^\d{2}:\d{2}$", e_t):
                        raise ApiErr(400, "Formato de hora HH:MM requerido")
                    sh, sm = map(int, s_t.split(":"))
                    eh, em = map(int, e_t.split(":"))
                    if sh > 23 or sm > 59 or eh > 23 or em > 59 or (eh, em) <= (sh, sm):
                        raise ApiErr(400, "La hora de fin debe ser mayor a la de inicio")
                    for ps, pe in by_day.get(day, []):
                        if not (e_t <= ps or s_t >= pe):
                            raise ApiErr(400, "Bloques traslapados en el mismo día")
                    by_day.setdefault(day, []).append((s_t, e_t))
                    parsed_blocks.append({"dia_semana": day, "hora_inicio": s_t, "hora_fin": e_t})
                self.schedules[did] = parsed_blocks
                return 200, {"data": parsed_blocks}

            # Appointments
            if method == "POST" and parts == ["api", "appointments"]:
                if actor["role"] != "PACIENTE":
                    raise ApiErr(403, "Solo los pacientes pueden agendar citas")
                did = str(body.get("doctorId") or "")
                if not _is_valid_uuid_or_id(did) or did not in self.doctors:
                    raise ApiErr(404, "Profesional no encontrado")
                sub = self._sub_summary(did)
                if not sub or not sub["active"]:
                    raise ApiErr(404, "Profesional no disponible")
                raw_dt = str(body.get("dateTime") or "")
                try:
                    dt = datetime.fromisoformat(raw_dt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC_MINUS_6)
                    dt = dt.astimezone(UTC_MINUS_6)
                except ValueError as err:
                    raise ApiErr(400, "dateTime ISO-8601 inválido") from err
                reason = body.get("reason")
                if reason is not None:
                    reason = str(reason).strip()
                    if len(reason) > 500:
                        raise ApiErr(400, "Motivo excede 500 caracteres")
                today = self._today()
                if dt <= self._now():
                    raise ApiErr(400, "La cita debe ser en el futuro")
                if dt.date() > today + timedelta(days=90):
                    raise ApiErr(400, "No se puede agendar a más de 90 días")
                free = self._available_slots(did, dt.date())
                if dt.isoformat() not in free:
                    # Check if already occupied vs not in schedule
                    occupied = any(
                        a["doctorId"] == did
                        and a["status"] != "CANCELADA"
                        and datetime.fromisoformat(a["dateTime"]) == dt
                        for a in self.appointments.values()
                    )
                    if occupied:
                        raise ApiErr(409, "Ese horario ya fue ocupado")
                    raise ApiErr(400, "Ese horario no forma parte de la agenda disponible")
                aid = str(uuid.uuid4())
                appt = {
                    "id": aid,
                    "patientId": actor["id"],
                    "doctorId": did,
                    "dateTime": dt.isoformat(),
                    "status": "PENDIENTE",
                    "reason": reason,
                }
                self.appointments[aid] = appt
                self._notify(
                    self.doctors[did]["userId"],
                    "CITA_NUEVA",
                    "Nueva solicitud de cita",
                    f"{actor['name']} solicitó cita.",
                    aid,
                )
                self._emit_emf("AppointmentsCreated", 1, "Count")
                return 201, {"data": self._appt_view(appt)}

            if method == "GET" and parts == ["api", "appointments"]:
                status_filter = query.get("status")
                if status_filter and status_filter not in VALID_APPT_STATUS:
                    raise ApiErr(400, "Estado de cita inválido")
                did = actor.get("doctorId")
                items = [
                    self._appt_view(a)
                    for a in self.appointments.values()
                    if (a["patientId"] == actor["id"] or (did and a["doctorId"] == did))
                    and (not status_filter or a["status"] == status_filter)
                ]
                items.sort(key=lambda x: x["dateTime"])
                return 200, {"data": items}

            if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "appointments"]:
                aid = parts[2]
                if not _is_valid_uuid_or_id(aid):
                    raise ApiErr(400, "Identificador de cita inválido")
                appt = self.appointments.get(aid)
                if not appt or (appt["patientId"] != actor["id"] and appt["doctorId"] != actor.get("doctorId")):
                    raise ApiErr(404, "La cita no existe")
                return 200, {"data": self._appt_view(appt)}

            if method == "PUT" and len(parts) == 4 and parts[:2] == ["api", "appointments"] and parts[3] == "status":
                aid = parts[2]
                if not _is_valid_uuid_or_id(aid):
                    raise ApiErr(400, "Identificador de cita inválido")
                appt = self.appointments.get(aid)
                if not appt or (appt["patientId"] != actor["id"] and appt["doctorId"] != actor.get("doctorId")):
                    raise ApiErr(404, "La cita no existe")
                new_status = body.get("status")
                if new_status not in ("CONFIRMADA", "CANCELADA"):
                    raise ApiErr(400, "Estado destino inválido")
                if new_status == "CONFIRMADA" and actor["role"] == "PACIENTE":
                    raise ApiErr(403, "Solo el profesional puede confirmar una cita")
                if appt["status"] not in ("PENDIENTE", "CONFIRMADA"):
                    raise ApiErr(409, f"No se puede modificar una cita {appt['status']}")
                if new_status == "CONFIRMADA" and appt["status"] != "PENDIENTE":
                    raise ApiErr(409, "Solo citas pendientes pueden confirmarse")
                if datetime.fromisoformat(appt["dateTime"]) <= self._now():
                    raise ApiErr(409, "La hora de la cita ya pasó")
                appt["status"] = new_status
                return 200, {"data": self._appt_view(appt)}

            if method == "PUT" and len(parts) == 4 and parts[:2] == ["api", "appointments"] and parts[3] == "reschedule":
                aid = parts[2]
                if not _is_valid_uuid_or_id(aid):
                    raise ApiErr(400, "Identificador de cita inválido")
                appt = self.appointments.get(aid)
                if not appt or (appt["patientId"] != actor["id"] and appt["doctorId"] != actor.get("doctorId")):
                    raise ApiErr(404, "La cita no existe")
                if appt["status"] not in ("PENDIENTE", "CONFIRMADA"):
                    raise ApiErr(409, "Solo se pueden reprogramar citas activas")
                if datetime.fromisoformat(appt["dateTime"]) <= self._now():
                    raise ApiErr(409, "No se puede reprogramar una cita pasada")
                sub = self._sub_summary(appt["doctorId"])
                if not sub or not sub["active"]:
                    raise ApiErr(409, "El profesional no tiene suscripción vigente")
                try:
                    dt = datetime.fromisoformat(str(body.get("dateTime") or ""))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC_MINUS_6)
                    dt = dt.astimezone(UTC_MINUS_6)
                except ValueError as err:
                    raise ApiErr(400, "dateTime inválido") from err
                if dt <= self._now() or dt.date() > self._today() + timedelta(days=90):
                    raise ApiErr(400, "Nueva fecha fuera de rango agendable")
                free = self._available_slots(appt["doctorId"], dt.date(), exclude_appt_id=aid)
                if dt.isoformat() not in free:
                    raise ApiErr(409, "El nuevo horario no está disponible")
                appt["dateTime"] = dt.isoformat()
                counterparty = (
                    self.doctors[appt["doctorId"]]["userId"]
                    if actor["id"] == appt["patientId"]
                    else appt["patientId"]
                )
                self._notify(
                    counterparty,
                    "CITA_REPROGRAMADA",
                    "Cita reprogramada",
                    f"La cita fue movida al {dt.isoformat()}.",
                    aid,
                )
                return 200, {"data": self._appt_view(appt)}

            # Medical records & consents & access-log
            if method == "GET" and parts == ["api", "records", "access-log"]:
                if actor["role"] != "PACIENTE":
                    raise ApiErr(403, "Solo el paciente puede consultar su bitácora de acceso")
                entries = [
                    {k: v for k, v in e.items() if k != "patientId"}
                    for e in reversed(self.access_log)
                    if e["patientId"] == actor["id"]
                ]
                return 200, {"data": entries}

            if method == "GET" and parts == ["api", "records"]:
                if actor["role"] == "PACIENTE":
                    return 200, {"data": self._build_record_view(actor["id"])}
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                pid = str(query.get("patientId") or "")
                if not _is_valid_uuid_or_id(pid) or pid not in self.users:
                    raise ApiErr(400, "patientId requerido o inválido")
                if not self.consents.get((pid, did), {}).get("granted", False):
                    raise ApiErr(403, "No cuentas con consentimiento vigente del paciente")
                doc = self.doctors[did]
                # Even if simulate_ddb_failure is True, RDS access log & read succeed (F12 fault tolerance)
                self.access_log.append(
                    {
                        "id": str(uuid.uuid4()),
                        "patientId": pid,
                        "actorId": actor["id"],
                        "actorName": doc["name"],
                        "actorRole": actor["role"],
                        "specialty": doc["specialty"],
                        "event": "LECTURA_EXPEDIENTE",
                        "accessedAt": self._now().isoformat(),
                    }
                )
                return 200, {"data": self._build_record_view(pid)}

            if method == "PUT" and parts == ["api", "records"]:
                if actor["role"] != "PACIENTE":
                    raise ApiErr(403, "Solo el paciente puede modificar su expediente")
                cur = dict(
                    self.records.get(
                        actor["id"],
                        {
                            "patient_id": actor["id"],
                            "allergies": [],
                            "notes": "",
                            "birthDate": None,
                            "sex": None,
                            "bloodType": None,
                            "chronicConditions": [],
                            "medications": [],
                            "updatedAt": None,
                        },
                    )
                )
                if "birthDate" in body and body["birthDate"] is not None:
                    bd_str = str(body["birthDate"])
                    try:
                        bd = date.fromisoformat(bd_str)
                    except ValueError as err:
                        raise ApiErr(400, "birthDate inválida") from err
                    if bd > self._today():
                        raise ApiErr(400, "birthDate no puede ser futura")
                    cur["birthDate"] = bd_str
                if "sex" in body and body["sex"] is not None:
                    if body["sex"] not in VALID_SEX:
                        raise ApiErr(400, "sex inválido")
                    cur["sex"] = body["sex"]
                if "bloodType" in body and body["bloodType"] is not None:
                    if body["bloodType"] not in VALID_BLOOD:
                        raise ApiErr(400, "bloodType inválido")
                    cur["bloodType"] = body["bloodType"]
                for arr_key in ("allergies", "chronicConditions", "medications"):
                    if arr_key in body and body[arr_key] is not None:
                        val = body[arr_key]
                        if not isinstance(val, list) or len(val) > 30:
                            raise ApiErr(400, f"{arr_key} debe tener máximo 30 elementos")
                        cur[arr_key] = [str(x).strip()[:120] for x in val if str(x).strip()]
                if "notes" in body and body["notes"] is not None:
                    notes = str(body["notes"])
                    if len(notes) > 5000:
                        raise ApiErr(400, "notes excede 5000 caracteres")
                    cur["notes"] = notes
                cur["updatedAt"] = self._now().isoformat()
                self.records[actor["id"]] = cur
                return 200, {"data": self._build_record_view(actor["id"])}

            if method == "POST" and parts == ["api", "consents"]:
                if actor["role"] != "PACIENTE":
                    raise ApiErr(403, "Solo los pacientes otorgan consentimientos")
                did = str(body.get("doctorId") or "")
                if not _is_valid_uuid_or_id(did) or did not in self.doctors:
                    raise ApiErr(404, "Profesional no encontrado")
                granted = body.get("granted")
                if not isinstance(granted, bool):
                    raise ApiErr(400, "granted debe ser booleano")
                entry = {
                    "patientId": actor["id"],
                    "doctorId": did,
                    "granted": granted,
                    "updatedAt": self._now().isoformat(),
                }
                self.consents[(actor["id"], did)] = entry
                self._notify(
                    self.doctors[did]["userId"],
                    "CONSENTIMIENTO",
                    "Actualización de consentimiento",
                    f"{actor['name']} {'otorgó' if granted else 'revocó'} acceso a su expediente.",
                    did,
                )
                return 200, {"data": entry}

            if method == "GET" and parts == ["api", "consents"]:
                if actor["role"] != "PACIENTE":
                    raise ApiErr(403, "Solo los pacientes consultan sus consentimientos")
                out = []
                for (pid, did), item in self.consents.items():
                    if pid != actor["id"]:
                        continue
                    doc = self.doctors.get(did, {})
                    out.append(
                        {
                            "doctorId": did,
                            "doctorName": doc.get("name"),
                            "specialty": doc.get("specialty"),
                            "granted": item["granted"],
                            "updatedAt": item["updatedAt"],
                        }
                    )
                return 200, {"data": out}

            # Clinical Documents (S3 presigned simulation)
            if method == "POST" and parts == ["api", "records", "documents"]:
                if actor["role"] != "PACIENTE":
                    raise ApiErr(403, "Solo pacientes pueden subir documentos clínicos")
                name = str(body.get("name") or "").strip()
                ctype = str(body.get("contentType") or "").strip().lower()
                try:
                    size = int(body.get("size"))
                except (TypeError, ValueError) as err:
                    raise ApiErr(400, "size inválido") from err
                if size <= 0 or size > MAX_DOC_SIZE:
                    raise ApiErr(413 if size > MAX_DOC_SIZE else 400, "Tamaño debe ser entre 1 byte y 10 MB")
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in ALLOWED_DOC_EXT_MIME or ctype not in ALLOWED_DOC_EXT_MIME[ext]:
                    raise ApiErr(415, "Tipo de archivo o extensión no permitida")
                doc_id = str(uuid.uuid4())
                key = f"expedientes/{actor['id']}/{doc_id}-{name}"
                exp = int(time.time()) + 300
                sig = self._sign_s3_key(key, exp)
                self.documents[doc_id] = {
                    "id": doc_id,
                    "patientId": actor["id"],
                    "name": name,
                    "contentType": ctype,
                    "size": size,
                    "key": key,
                    "lastModified": self._now().isoformat(),
                }
                return 201, {
                    "data": {
                        "id": doc_id,
                        "name": name,
                        "url": f"{self.base_url}/__s3/upload/{key}",
                        "fields": {
                            "key": key,
                            "Content-Type": ctype,
                            "x-amz-meta-file-name": name,
                            "x-amz-exp": str(exp),
                            "x-amz-sig": sig,
                        },
                        "expiresIn": 300,
                    }
                }

            if method == "GET" and parts == ["api", "records", "documents"]:
                if actor["role"] == "PACIENTE":
                    target_pid = actor["id"]
                else:
                    did = self._require_doctor(actor)
                    self._require_active_sub(did)
                    target_pid = str(query.get("patientId") or "")
                    if not _is_valid_uuid_or_id(target_pid):
                        raise ApiErr(400, "patientId inválido")
                    if not self.consents.get((target_pid, did), {}).get("granted", False):
                        raise ApiErr(403, "Sin consentimiento del paciente")
                docs = []
                for d in self.documents.values():
                    if d["patientId"] != target_pid or d["key"] not in self.s3_objects:
                        continue
                    docs.append(
                        {
                            "id": d["id"],
                            "name": d["name"],
                            "contentType": d["contentType"],
                            "size": d["size"],
                            "lastModified": d["lastModified"],
                            "downloadUrl": self._presigned_get_url(d["key"], 300),
                        }
                    )
                return 200, {"data": docs}

            if method == "DELETE" and len(parts) == 4 and parts[:3] == ["api", "records", "documents"]:
                if actor["role"] != "PACIENTE":
                    raise ApiErr(403, "Solo el paciente puede eliminar documentos")
                doc_id = parts[3]
                if not _is_valid_uuid_or_id(doc_id):
                    raise ApiErr(400, "ID de documento inválido")
                doc = self.documents.get(doc_id)
                if not doc or doc["patientId"] != actor["id"]:
                    raise ApiErr(404, "Documento no encontrado")
                self.documents.pop(doc_id, None)
                self.s3_objects.pop(doc["key"], None)
                return 200, {"data": {"deleted": True}}

            # Doctor patients & Consultations & Prescriptions
            if method == "GET" and parts == ["api", "doctor", "patients"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                out = []
                for (pid, c_did), c in self.consents.items():
                    if c_did == did and c["granted"]:
                        p = self.users.get(pid, {})
                        out.append(
                            {
                                "patientId": pid,
                                "name": p.get("name"),
                                "email": p.get("email"),
                                "accessSince": c["updatedAt"],
                            }
                        )
                return 200, {"data": out}

            if method == "POST" and parts == ["api", "consultations"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                pid = str(body.get("patientId") or "")
                aid = str(body.get("appointmentId") or "")
                if not _is_valid_uuid_or_id(pid) or not _is_valid_uuid_or_id(aid):
                    raise ApiErr(400, "patientId y appointmentId requeridos")
                appt = self.appointments.get(aid)
                if not appt or appt["patientId"] != pid:
                    raise ApiErr(404, "Cita no encontrada para ese paciente")
                if appt["doctorId"] != did:
                    raise ApiErr(403, "La cita pertenece a otro profesional")
                if not self.consents.get((pid, did), {}).get("granted", False):
                    raise ApiErr(403, "Se requiere consentimiento vigente del paciente")
                if appt["status"] not in ("PENDIENTE", "CONFIRMADA"):
                    raise ApiErr(409, f"No se puede registrar consulta de una cita {appt['status']}")
                if datetime.fromisoformat(appt["dateTime"]) > self._now():
                    raise ApiErr(409, "No se puede registrar la consulta antes de la hora de la cita")
                diag = str(body.get("diagnosis") or "").strip()
                treat = str(body.get("treatment") or "").strip()
                notes = str(body.get("notes") or "").strip()
                if len(diag) < 3 or len(diag) > 5000 or len(treat) < 3 or len(treat) > 5000:
                    raise ApiErr(400, "Diagnóstico y tratamiento requieren al menos 3 caracteres")
                if len(notes) > 5000:
                    raise ApiErr(400, "Notas exceden 5000 caracteres")

                cid = str(uuid.uuid4())
                rx_id = str(uuid.uuid4())
                s3_key = f"recetas/{rx_id}.pdf"
                pdf_bytes = _minimal_pdf_bytes(self.doctors[did]["name"], diag, treat)
                self.s3_objects[s3_key] = {"bytes": pdf_bytes, "contentType": "application/pdf"}
                appt["status"] = "COMPLETADA"
                doc = self.doctors[did]
                now_iso = self._now().isoformat()
                self.consultations[cid] = {
                    "id": cid,
                    "appointmentId": aid,
                    "patientId": pid,
                    "doctorId": did,
                    "doctorName": doc["name"],
                    "specialty": doc["specialty"],
                    "diagnosis": diag,
                    "treatment": treat,
                    "notes": notes,
                    "dateTime": appt["dateTime"],
                    "prescriptionId": rx_id,
                    "createdAt": now_iso,
                }
                self.prescriptions[rx_id] = {
                    "id": rx_id,
                    "patientId": pid,
                    "doctorId": did,
                    "appointmentId": aid,
                    "diagnosis": diag,
                    "treatment": treat,
                    "notes": notes,
                    "dateTime": appt["dateTime"],
                    "doctorName": doc["name"],
                    "specialty": doc["specialty"],
                    "documentUrl": s3_key,
                }
                self._notify(pid, "RECETA_NUEVA", "Tu receta está lista", "Tu receta ya está disponible.", aid)
                self._emit_emf("ConsultationsRegistered", 1, "Count")
                return 201, {
                    "data": {
                        "id": cid,
                        "appointmentId": aid,
                        "diagnosis": diag,
                        "treatment": treat,
                        "notes": notes,
                        "prescriptionId": rx_id,
                        "documentUrl": s3_key,
                    }
                }

            if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "prescriptions"]:
                rx_id = parts[2]
                if not _is_valid_uuid_or_id(rx_id):
                    raise ApiErr(400, "ID de receta inválido")
                rx = self.prescriptions.get(rx_id)
                if not rx:
                    raise ApiErr(404, "Receta no encontrada")
                if actor["role"] == "PACIENTE":
                    if rx["patientId"] != actor["id"]:
                        raise ApiErr(404, "La receta no existe")
                else:
                    did = self._require_doctor(actor)
                    if rx["doctorId"] != did:
                        raise ApiErr(404, "La receta no existe")
                    self._require_active_sub(did)
                    if not self.consents.get((rx["patientId"], did), {}).get("granted", False):
                        raise ApiErr(403, "Se requiere consentimiento vigente")
                out = {**rx}
                if rx.get("documentUrl") and rx["documentUrl"] in self.s3_objects:
                    out["downloadUrl"] = self._presigned_get_url(rx["documentUrl"], 300)
                return 200, {"data": out}

            # Inventory
            if method == "GET" and parts == ["api", "doctor", "inventory"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                items = [i for i in self.inventory.values() if i["doctorId"] == did]
                return 200, {"data": items}

            if method == "POST" and parts == ["api", "doctor", "inventory"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                name = str(body.get("name") or "").strip()
                unit = str(body.get("unit") or "").strip()
                if not name or len(name) > 120 or not unit or len(unit) > 30:
                    raise ApiErr(400, "Nombre y unidad requeridos")
                try:
                    qty = int(body.get("quantity"))
                except (TypeError, ValueError) as err:
                    raise ApiErr(400, "Cantidad inválida") from err
                if qty < 0 or qty > 100_000_000:
                    raise ApiErr(400, "Cantidad fuera de rango")
                existing = next(
                    (i for i in self.inventory.values() if i["doctorId"] == did and i["name"].lower() == name.lower()),
                    None,
                )
                if existing:
                    existing["quantity"] = qty
                    existing["unit"] = unit
                    existing["updatedAt"] = self._now().isoformat()
                    return 200, {"data": existing}
                iid = str(uuid.uuid4())
                item = {
                    "id": iid,
                    "doctorId": did,
                    "name": name,
                    "quantity": qty,
                    "unit": unit,
                    "updatedAt": self._now().isoformat(),
                }
                self.inventory[iid] = item
                return 201, {"data": item}

            if method == "DELETE" and len(parts) == 4 and parts[:3] == ["api", "doctor", "inventory"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                iid = parts[3]
                item = self.inventory.get(iid)
                if not item or item["doctorId"] != did:
                    raise ApiErr(404, "Insumo no encontrado")
                self.inventory.pop(iid, None)
                return 200, {"data": {"deleted": True}}

            # Promotions
            if method == "GET" and parts == ["api", "doctor", "promotions"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                return 200, {"data": self._active_promos(did, only_active=False)}

            if method == "POST" and parts == ["api", "doctor", "promotions"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                title = str(body.get("title") or "").strip()
                desc = str(body.get("description") or "").strip()
                if not title or len(title) > 120 or len(desc) > 500:
                    raise ApiErr(400, "Título o descripción inválidos")
                try:
                    disc = int(body.get("discountPercent"))
                except (TypeError, ValueError) as err:
                    raise ApiErr(400, "Descuento inválido") from err
                if disc < 1 or disc > 90:
                    raise ApiErr(400, "El descuento debe ser entre 1% y 90%")
                try:
                    s_d = date.fromisoformat(str(body.get("start") or ""))
                    e_d = date.fromisoformat(str(body.get("end") or ""))
                except ValueError as err:
                    raise ApiErr(400, "Fechas start/end inválidas") from err
                if e_d < s_d:
                    raise ApiErr(400, "La fecha fin debe ser mayor o igual al inicio")
                pid = str(uuid.uuid4())
                promo = {
                    "id": pid,
                    "doctorId": did,
                    "title": title,
                    "description": desc,
                    "discountPercent": disc,
                    "start": s_d.isoformat(),
                    "end": e_d.isoformat(),
                }
                self.promotions[pid] = promo
                today = self._today()
                return 201, {"data": {**promo, "active": s_d <= today <= e_d}}

            if method == "DELETE" and len(parts) == 4 and parts[:3] == ["api", "doctor", "promotions"]:
                did = self._require_doctor(actor)
                self._require_active_sub(did)
                pid = parts[3]
                promo = self.promotions.get(pid)
                if not promo or promo["doctorId"] != did:
                    raise ApiErr(404, "Promoción no encontrada")
                self.promotions.pop(pid, None)
                return 200, {"data": {"deleted": True}}

            # Messages & Notifications
            if method == "GET" and parts == ["api", "messages"]:
                if actor["role"] in ("DOCTOR", "CLINICA"):
                    self._require_active_sub(actor["doctorId"])
                others = {
                    m["recipientId"] if m["senderId"] == actor["id"] else m["senderId"]
                    for m in self.messages
                    if actor["id"] in (m["senderId"], m["recipientId"])
                }
                convs = []
                for oid in others:
                    other = self.users.get(oid, {})
                    thread = [m for m in self.messages if {m["senderId"], m["recipientId"]} == {actor["id"], oid}]
                    last = thread[-1]
                    unread = sum(1 for m in thread if m["recipientId"] == actor["id"] and not m["read"])
                    convs.append(
                        {
                            "userId": oid,
                            "name": other.get("name") or other.get("email"),
                            "lastMessage": last["content"],
                            "updatedAt": last["createdAt"],
                            "unread": unread,
                        }
                    )
                convs.sort(key=lambda c: c["updatedAt"], reverse=True)
                return 200, {"data": convs}

            if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "messages"]:
                if actor["role"] in ("DOCTOR", "CLINICA"):
                    self._require_active_sub(actor["doctorId"])
                oid = parts[2]
                if not _is_valid_uuid_or_id(oid) or not self._can_message(actor["id"], oid):
                    raise ApiErr(404, "Conversación no encontrada")
                thread = []
                for m in self.messages:
                    if {m["senderId"], m["recipientId"]} == {actor["id"], oid}:
                        if m["recipientId"] == actor["id"]:
                            m["read"] = True
                        thread.append(dict(m))
                return 200, {"data": thread}

            if method == "POST" and parts == ["api", "messages"]:
                if actor["role"] in ("DOCTOR", "CLINICA"):
                    self._require_active_sub(actor["doctorId"])
                rid = str(body.get("recipientId") or "")
                if not _is_valid_uuid_or_id(rid):
                    raise ApiErr(400, "recipientId inválido")
                if rid == actor["id"]:
                    raise ApiErr(400, "No puedes enviarte mensajes a ti mismo")
                if rid not in self.users:
                    raise ApiErr(404, "Destinatario no encontrado")
                if not self._can_message(actor["id"], rid):
                    raise ApiErr(403, "Se requiere cita o consentimiento previo para enviar mensajes")
                content = str(body.get("content") or "").strip()
                if not content or len(content) > 2000:
                    raise ApiErr(400, "El mensaje debe tener entre 1 y 2000 caracteres")
                msg = {
                    "id": str(uuid.uuid4()),
                    "senderId": actor["id"],
                    "recipientId": rid,
                    "content": content,
                    "createdAt": self._now().isoformat(),
                    "read": False,
                }
                self.messages.append(msg)
                self._notify(rid, "MENSAJE_NUEVO", "Nuevo mensaje", f"Mensaje de {actor['name']}.", msg["id"])
                return 201, {"data": msg}

            if method == "GET" and parts == ["api", "notifications"]:
                return 200, {"data": self._materialize_reminders_for_user(actor)}

            if method == "PUT" and len(parts) == 4 and parts[:2] == ["api", "notifications"] and parts[3] == "read":
                nid = parts[2]
                target = next(
                    (n for n in self.notifications if n["id"] == nid and n["userId"] == actor["id"]),
                    None,
                )
                if not target:
                    raise ApiErr(404, "Notificación no encontrada")
                target["read"] = True
                return 200, {"data": {k: v for k, v in target.items() if k != "userId"}}

        raise ApiErr(404, f"Ruta no encontrada: {method} {path}")
