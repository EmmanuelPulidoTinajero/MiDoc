"""In-harness Mock Stripe HTTP Server & HMAC Webhook Signer (pure Python stdlib)."""
from __future__ import annotations

import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import uuid


def _sign_payload(payload_bytes: bytes, secret: str, timestamp: int | None = None) -> str:
    t = int(timestamp if timestamp is not None else time.time())
    signed = f"{t}.".encode("utf-8") + payload_bytes
    v1 = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def _post_json_or_raw(url: str, data: bytes, headers: dict[str, str], method: str = "POST") -> tuple[int, Any]:
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw.strip() else None
    except HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace") if err.fp else ""
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except ValueError:
            parsed = raw
        return err.code, parsed


class StripeMockServer:
    """Local HTTP simulator of the Stripe Checkout & Webhook boundary."""

    def __init__(
        self,
        secret_key: str = "sk_test_midoc_mock_0000000000000000",
        webhook_secret: str = "whsec_midoc_mock_0000000000000000",
        require_auth: bool = True,
        port: int = 0,
    ) -> None:
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret
        self.require_auth = require_auth
        self._bind_port = int(port)
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self.recorded_requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, port: int | None = None) -> "StripeMockServer":
        parent = self
        bind_port = self._bind_port if port is None else int(port)

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _check_auth(self) -> bool:
                if not parent.require_auth:
                    return True
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {parent.secret_key}":
                    self._send_json(
                        401,
                        {"error": {"type": "authentication_error", "message": "Invalid API Key provided"}},
                    )
                    return False
                return True

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0") or "0")
                return self.rfile.read(length) if length > 0 else b""

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                parts = [p for p in parsed.path.split("/") if p]
                raw = self._read_body()
                body_str = raw.decode("utf-8", errors="replace")

                if parts in (["v1", "checkout", "sessions"], ["checkout", "sessions"]):
                    if not self._check_auth():
                        return
                    form = {k: v[-1] for k, v in parse_qs(body_str, keep_blank_values=True).items()}
                    with parent._lock:
                        parent.recorded_requests.append(
                            {
                                "method": "POST",
                                "path": "/v1/checkout/sessions",
                                "rawPath": parsed.path,
                                "query": parsed.query,
                                "form": dict(form),
                                "timestamp": time.time(),
                            }
                        )
                    mode = form.get("mode", "")
                    unit_amount = (
                        form.get("line_items[0][price_data][unit_amount]")
                        or form.get("line_items[0][amount]")
                        or ""
                    )
                    currency = (
                        form.get("line_items[0][price_data][currency]")
                        or form.get("line_items[0][currency]")
                        or ""
                    ).lower()
                    if mode != "payment" or str(unit_amount) != "2000" or currency != "usd":
                        self._send_json(
                            400,
                            {
                                "error": {
                                    "type": "invalid_request_error",
                                    "message": "Expected mode=payment, unit_amount=2000, currency=usd",
                                }
                            },
                        )
                        return
                    metadata: dict[str, str] = {}
                    for k, v in form.items():
                        if k.startswith("metadata[") and k.endswith("]"):
                            metadata[k[len("metadata[") : -1]] = v
                    session_id = f"cs_test_{uuid.uuid4().hex[:24]}"
                    pi_id = f"pi_test_{uuid.uuid4().hex[:24]}"
                    auto_pay = metadata.get("mockAutoPay", "").lower() == "true"
                    session = {
                        "id": session_id,
                        "object": "checkout.session",
                        "mode": "payment",
                        "status": "complete" if auto_pay else "open",
                        "payment_status": "paid" if auto_pay else "unpaid",
                        "amount_total": 2000,
                        "currency": "usd",
                        "livemode": False,
                        "client_reference_id": form.get("client_reference_id") or metadata.get("doctorId"),
                        "success_url": form.get("success_url", ""),
                        "cancel_url": form.get("cancel_url", ""),
                        "url": f"{parent.base_url}/__checkout/{session_id}",
                        "payment_intent": pi_id,
                        "metadata": metadata,
                        "_card": {"brand": "visa", "last4": "4242"},
                    }
                    with parent._lock:
                        parent._sessions[session_id] = session
                    self._send_json(200, parent._public_session(session, expand_pi=False))
                    return

                if len(parts) == 4 and parts[0] == "__mock" and parts[1] == "sessions" and parts[3] == "complete":
                    sid = parts[2]
                    payload = json.loads(body_str) if body_str.strip() else {}
                    ok = parent.complete_session(
                        sid,
                        brand=payload.get("brand", "visa"),
                        last4=payload.get("last4", "4242"),
                    )
                    if not ok:
                        self._send_json(404, {"error": {"message": "Session not found"}})
                        return
                    self._send_json(200, {"completed": True, "sessionId": sid})
                    return

                if len(parts) == 4 and parts[0] == "__mock" and parts[1] == "sessions" and parts[3] == "fail":
                    sid = parts[2]
                    ok = parent.fail_session(sid)
                    if not ok:
                        self._send_json(404, {"error": {"message": "Session not found"}})
                        return
                    self._send_json(200, {"failed": True, "sessionId": sid})
                    return

                self._send_json(404, {"error": {"type": "invalid_request_error", "message": "Not found"}})

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                parts = [p for p in parsed.path.split("/") if p]

                if (len(parts) == 4 and parts[:3] == ["v1", "checkout", "sessions"]) or (
                    len(parts) == 3 and parts[:2] == ["checkout", "sessions"]
                ):
                    if not self._check_auth():
                        return
                    sid = parts[-1]
                    qs = parse_qs(parsed.query)
                    expands = qs.get("expand[]", []) + qs.get("expand", [])
                    with parent._lock:
                        parent.recorded_requests.append(
                            {
                                "method": "GET",
                                "path": f"/v1/checkout/sessions/{sid}",
                                "rawPath": parsed.path,
                                "query": parsed.query,
                                "expands": list(expands),
                                "timestamp": time.time(),
                            }
                        )
                        session = parent._sessions.get(sid)
                    if session is None:
                        self._send_json(
                            404,
                            {"error": {"type": "invalid_request_error", "message": f"No such checkout.session: {sid}"}},
                        )
                        return
                    expand_pi = any("payment_intent" in e for e in expands)
                    self._send_json(200, parent._public_session(session, expand_pi=expand_pi))
                    return

                if parts == ["__mock", "requests"]:
                    with parent._lock:
                        self._send_json(200, {"requests": list(parent.recorded_requests)})
                    return

                if len(parts) == 3 and parts[0] == "__mock" and parts[1] == "sessions":
                    session_obj = parent.get_session(parts[2])
                    if session_obj is None:
                        self._send_json(404, {"error": {"message": "Session not found"}})
                        return
                    self._send_json(200, session_obj)
                    return

                if len(parts) == 2 and parts[0] == "__checkout":
                    sid = parts[1]
                    html = f"<!doctype html><html><body><h1>Stripe Mock Checkout</h1><p>{sid}</p></body></html>".encode(
                        "utf-8"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return

                self._send_json(404, {"error": {"message": "Not found"}})

        self._server = ThreadingHTTPServer(("127.0.0.1", bind_port), Handler)
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

    def _public_session(self, session: dict[str, Any], *, expand_pi: bool, force_paid: bool = False) -> dict[str, Any]:
        out = {k: v for k, v in session.items() if not k.startswith("_")}
        if force_paid:
            out["payment_status"] = "paid"
            out["status"] = "complete"
        if expand_pi:
            card = session.get("_card", {"brand": "visa", "last4": "4242"})
            pi_id = session["payment_intent"]
            if out["payment_status"] == "paid":
                out["payment_intent"] = {
                    "id": pi_id,
                    "object": "payment_intent",
                    "status": "succeeded",
                    "payment_method": {
                        "id": f"pm_test_{pi_id[-12:]}",
                        "type": "card",
                        "card": {
                            "brand": card["brand"],
                            "last4": card["last4"],
                            "exp_month": 12,
                            "exp_year": 2030,
                        },
                    },
                }
            else:
                out["payment_intent"] = {
                    "id": pi_id,
                    "object": "payment_intent",
                    "status": "requires_payment_method",
                    "payment_method": None,
                }
        return out

    def complete_session(self, session_id: str, brand: str = "visa", last4: str = "4242") -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session["payment_status"] = "paid"
            session["status"] = "complete"
            session["_card"] = {"brand": brand, "last4": last4}
            return True

    def fail_session(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session["payment_status"] = "unpaid"
            session["status"] = "expired"
            return True

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            s = self._sessions.get(session_id)
            return self._public_session(s, expand_pi=True) if s else None

    def sign_webhook_payload(
        self,
        payload_bytes: bytes,
        secret: str | None = None,
        timestamp: int | None = None,
    ) -> str:
        return _sign_payload(
            payload_bytes,
            secret if secret is not None else self.webhook_secret,
            timestamp=timestamp,
        )

    def build_checkout_completed_event(
        self,
        session_id: str,
        event_id: str | None = None,
        *,
        mark_paid: bool = False,
    ) -> bytes:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                raise KeyError(f"Unknown mock Stripe session: {session_id}")
            if mark_paid:
                s["payment_status"] = "paid"
                s["status"] = "complete"
            session_obj = self._public_session(s, expand_pi=True, force_paid=True)
        event = {
            "id": event_id or f"evt_test_{uuid.uuid4().hex[:24]}",
            "object": "event",
            "type": "checkout.session.completed",
            "created": int(time.time()),
            "data": {"object": session_obj},
        }
        return json.dumps(event, ensure_ascii=False).encode("utf-8")

    def send_webhook(
        self,
        api_base_url: str,
        session_id: str,
        *,
        secret_override: str | None = None,
        timestamp_override: int | None = None,
        tamper_body: bool = False,
        omit_signature: bool = False,
        event_id: str | None = None,
        mark_paid: bool | None = None,
    ) -> tuple[int, Any]:
        is_positive = (
            not omit_signature
            and not tamper_body
            and secret_override is None
            and timestamp_override is None
        )
        should_mark_paid = is_positive if mark_paid is None else bool(mark_paid)
        payload_bytes = self.build_checkout_completed_event(
            session_id,
            event_id=event_id,
            mark_paid=should_mark_paid,
        )
        sig = self.sign_webhook_payload(
            payload_bytes,
            secret=secret_override,
            timestamp=timestamp_override,
        )
        wire_bytes = payload_bytes + b" " if tamper_body else payload_bytes
        headers = {"Content-Type": "application/json"}
        if not omit_signature:
            headers["Stripe-Signature"] = sig
        url = f"{api_base_url.rstrip('/')}/api/webhooks/stripe"
        return _post_json_or_raw(url, wire_bytes, headers, method="POST")


class ExternalStripeMockClient:
    """Adapter attaching to an already-running external StripeMockServer (E2E_STRIPE_MOCK_URL)."""

    def __init__(
        self,
        base_url: str,
        *,
        secret_key: str = "sk_test_midoc_mock_0000000000000000",
        webhook_secret: str = "whsec_midoc_mock_0000000000000000",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret

    @property
    def recorded_requests(self) -> list[dict[str, Any]]:
        req = Request(f"{self.base_url}/__mock/requests", method="GET")
        with urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return list(data.get("requests") or [])

    def complete_session(self, session_id: str, brand: str = "visa", last4: str = "4242") -> bool:
        body = json.dumps({"brand": brand, "last4": last4}).encode("utf-8")
        st, _ = _post_json_or_raw(
            f"{self.base_url}/__mock/sessions/{session_id}/complete",
            body,
            {"Content-Type": "application/json"},
            method="POST",
        )
        return st == 200

    def fail_session(self, session_id: str) -> bool:
        st, _ = _post_json_or_raw(
            f"{self.base_url}/__mock/sessions/{session_id}/fail",
            b"{}",
            {"Content-Type": "application/json"},
            method="POST",
        )
        return st == 200

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        req = Request(f"{self.base_url}/__mock/sessions/{session_id}", method="GET")
        try:
            with urlopen(req, timeout=10.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as err:
            if err.code == 404:
                return None
            raise

    def sign_webhook_payload(
        self,
        payload_bytes: bytes,
        secret: str | None = None,
        timestamp: int | None = None,
    ) -> str:
        return _sign_payload(
            payload_bytes,
            secret if secret is not None else self.webhook_secret,
            timestamp=timestamp,
        )

    def build_checkout_completed_event(
        self,
        session_id: str,
        event_id: str | None = None,
        *,
        mark_paid: bool = False,
    ) -> bytes:
        if mark_paid:
            self.complete_session(session_id)
        session_obj = self.get_session(session_id)
        if session_obj is None:
            raise KeyError(f"Unknown mock Stripe session: {session_id}")
        session_obj = dict(session_obj)
        session_obj["payment_status"] = "paid"
        session_obj["status"] = "complete"
        event = {
            "id": event_id or f"evt_test_{uuid.uuid4().hex[:24]}",
            "object": "event",
            "type": "checkout.session.completed",
            "created": int(time.time()),
            "data": {"object": session_obj},
        }
        return json.dumps(event, ensure_ascii=False).encode("utf-8")

    def send_webhook(
        self,
        api_base_url: str,
        session_id: str,
        *,
        secret_override: str | None = None,
        timestamp_override: int | None = None,
        tamper_body: bool = False,
        omit_signature: bool = False,
        event_id: str | None = None,
        mark_paid: bool | None = None,
    ) -> tuple[int, Any]:
        is_positive = (
            not omit_signature
            and not tamper_body
            and secret_override is None
            and timestamp_override is None
        )
        should_mark_paid = is_positive if mark_paid is None else bool(mark_paid)
        payload_bytes = self.build_checkout_completed_event(
            session_id,
            event_id=event_id,
            mark_paid=should_mark_paid,
        )
        sig = self.sign_webhook_payload(
            payload_bytes,
            secret=secret_override,
            timestamp=timestamp_override,
        )
        wire_bytes = payload_bytes + b" " if tamper_body else payload_bytes
        headers = {"Content-Type": "application/json"}
        if not omit_signature:
            headers["Stripe-Signature"] = sig
        url = f"{api_base_url.rstrip('/')}/api/webhooks/stripe"
        return _post_json_or_raw(url, wire_bytes, headers, method="POST")

    def stop(self) -> None:
        return


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Standalone MiDoc StripeMockServer")
    parser.add_argument("--port", type=int, default=4242)
    args = parser.parse_args()
    srv = StripeMockServer(port=args.port).start()
    print(f"StripeMockServer listening at {srv.base_url}", flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        srv.stop()
