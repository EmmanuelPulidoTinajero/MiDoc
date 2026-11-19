"""Pruebas unitarias e integración para Stripe Checkout, confirmación, webhooks y secretos."""
import base64
import copy
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import app  # noqa: E402
from lambda_function import handler  # noqa: E402
import flujos  # noqa: E402
import pagos_stripe  # noqa: E402
import reglas  # noqa: E402

DB_ORIGINAL = copy.deepcopy(app.DB)


def _firmar_stripe(payload_bytes: bytes, secret: str, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + payload_bytes, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


class ConfiguracionStripeTests(unittest.TestCase):
    def setUp(self):
        pagos_stripe.limpiar_cache()

    def tearDown(self):
        pagos_stripe.limpiar_cache()

    def test_validacion_consistencia_payment_mode(self):
        with patch.dict(os.environ, {"PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_live_12345"}, clear=True):
            with self.assertRaises(reglas.ErrorApi) as ctx:
                pagos_stripe.validar_config_stripe(pagos_stripe.obtener_config())
            self.assertEqual(ctx.exception.status, 500)

        with patch.dict(os.environ, {"PAYMENT_MODE": "live", "STRIPE_SECRET_KEY": "sk_test_12345"}, clear=True):
            with self.assertRaises(reglas.ErrorApi) as ctx:
                pagos_stripe.validar_config_stripe(pagos_stripe.obtener_config())
            self.assertEqual(ctx.exception.status, 500)

        with patch.dict(os.environ, {"PAYMENT_MODE": "test"}, clear=True):
            with self.assertRaises(reglas.ErrorApi) as ctx:
                pagos_stripe.validar_config_stripe(pagos_stripe.obtener_config())
            self.assertEqual(ctx.exception.status, 503)

    def test_secrets_manager_fallback_y_cache(self):
        secret_payload = json.dumps({
            "payment_mode": "live",
            "stripe_secret_key": "sk_live_from_sm",
            "stripe_webhook_secret": "whsec_from_sm",
        })
        sm_client = MagicMock()
        sm_client.get_secret_value.return_value = {"SecretString": secret_payload}
        boto3_mock = MagicMock()
        boto3_mock.client.return_value = sm_client

        with patch.dict(os.environ, {"STRIPE_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:1:secret:stripe"}, clear=True), \
                patch.dict(sys.modules, {"boto3": boto3_mock}):
            cfg1 = pagos_stripe.obtener_config()
            cfg2 = pagos_stripe.obtener_config()
            self.assertEqual(cfg1["payment_mode"], "live")
            self.assertEqual(cfg1["secret_key"], "sk_live_from_sm")
            self.assertEqual(cfg2["webhook_secret"], "whsec_from_sm")
            sm_client.get_secret_value.assert_called_once()

            pagos_stripe.limpiar_cache()
            pagos_stripe.obtener_config()
            self.assertEqual(sm_client.get_secret_value.call_count, 2)

    def test_construir_urls_retorno_seguras(self):
        s, c = pagos_stripe.construir_urls_retorno("https://midoc.s3.us-east-1.amazonaws.com/index.html")
        self.assertEqual(
            s,
            "https://midoc.s3.us-east-1.amazonaws.com/index.html#/panel/suscripcion?stripe_status=success&session_id={CHECKOUT_SESSION_ID}",
        )
        self.assertEqual(
            c,
            "https://midoc.s3.us-east-1.amazonaws.com/index.html#/panel/suscripcion?stripe_status=cancel",
        )
        with self.assertRaises(reglas.ErrorApi):
            pagos_stripe.construir_urls_retorno("https://midoc.s3.amazonaws.com/index.html", success_url="javascript:alert(1)")
        with patch.dict(os.environ, {"NODE_ENV": "production"}):
            with self.assertRaises(reglas.ErrorApi):
                pagos_stripe.construir_urls_retorno(
                    "https://midoc.s3.amazonaws.com/index.html",
                    success_url="https://evil.example/steal",
                )

    def test_stripe_api_base_en_no_produccion_y_bloqueado_en_produccion(self):
        urls_llamadas = []

        def fake_urlopen(req, timeout=15):
            urls_llamadas.append(req.full_url)
            resp = MagicMock()
            resp.read.return_value = json.dumps({"id": "cs_test_1", "url": "https://checkout.stripe.com/1"}).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with patch.dict(os.environ, {"NODE_ENV": "test", "STRIPE_API_BASE": "http://127.0.0.1:18080/v1/"}, clear=False):
                pagos_stripe._stripe_request("POST", "/checkout/sessions", "sk_test_123", form_params={"mode": "payment"})
            with patch.dict(os.environ, {"NODE_ENV": "production", "STRIPE_API_BASE": "https://evil.example.com/v1"}, clear=False):
                pagos_stripe._stripe_request("POST", "/checkout/sessions", "sk_live_123", form_params={"mode": "payment"})

        self.assertEqual(urls_llamadas[0], "http://127.0.0.1:18080/v1/checkout/sessions")
        self.assertEqual(urls_llamadas[1], "https://api.stripe.com/v1/checkout/sessions")


class StripeCheckoutConfirmWebhookTests(unittest.TestCase):
    def setUp(self):
        app.DB.clear()
        app.DB.update(copy.deepcopy(DB_ORIGINAL))
        flujos.reset_rate_limits(app.DB)
        pagos_stripe.limpiar_cache()

    def _registrar_doctor(self):
        resp = app.handle("POST", "/api/auth/register", body={
            "email": "stripe.doc@midoc.mx",
            "password": "Segura123",
            "role": "DOCTOR",
            "name": "Dr. Stripe",
            "specialty": "Cardiología",
            "location": "CDMX",
            "price": 700,
        })
        self.assertEqual(resp["statusCode"], 201)
        return json.loads(resp["body"])

    def test_checkout_http_y_confirm_con_latest_charge_fallback(self):
        doc = self._registrar_doctor()
        token = doc["token"]
        doctor_id = doc["user"]["doctorId"]

        captured = {}

        def fake_urlopen(req, timeout=15):
            captured["url"] = req.full_url
            captured["auth"] = req.get_header("Authorization")
            captured["data"] = req.data.decode("utf-8") if req.data else None
            resp = MagicMock()
            if req.get_method() == "POST":
                resp.read.return_value = json.dumps({
                    "id": "cs_test_http_999999",
                    "url": "https://checkout.stripe.com/c/pay/cs_test_http_999999",
                }).encode("utf-8")
            else:
                resp.read.return_value = json.dumps({
                    "id": "cs_test_http_999999",
                    "payment_status": "paid",
                    "status": "complete",
                    "amount_total": 2000,
                    "livemode": False,
                    "metadata": {"doctorId": doctor_id},
                    "payment_intent": {
                        "id": "pi_http_999",
                        "latest_charge": {"payment_method_details": {"card": {"brand": "amex", "last4": "0005"}}},
                    },
                }).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp

        env = {
            "PAYMENT_MODE": "test",
            "STRIPE_SECRET_KEY": "sk_test_1234567890",
            "FRONTEND_BASE_URL": "https://frontend.example.com/index.html",
        }
        with patch.dict(os.environ, env, clear=False), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ck = app.handle(
                "POST",
                "/api/subscriptions/checkout",
                headers={"authorization": f"Bearer {token}", "Idempotency-Key": "ck-1"},
                body={},
            )
            self.assertEqual(ck["statusCode"], 201)
            self.assertEqual(captured["auth"], "Bearer sk_test_1234567890")
            parsed_form = urllib.parse.parse_qs(captured["data"])
            self.assertEqual(parsed_form["line_items[0][price_data][unit_amount]"], ["2000"])
            self.assertEqual(parsed_form["line_items[0][price_data][currency]"], ["usd"])

            # Idempotency-Key replay no llama otra vez a Stripe
            ck_rep = app.handle(
                "POST",
                "/api/subscriptions/checkout",
                headers={"authorization": f"Bearer {token}", "Idempotency-Key": "ck-1"},
                body={},
            )
            self.assertEqual(ck_rep["statusCode"], 201)
            self.assertEqual(json.loads(ck_rep["body"])["data"]["sessionId"], "cs_test_http_999999")

            conf = app.handle(
                "POST",
                "/api/subscriptions/confirm",
                headers={"authorization": f"Bearer {token}"},
                body={"sessionId": "cs_test_http_999999"},
            )
            self.assertEqual(conf["statusCode"], 200)
            data = json.loads(conf["body"])["data"]
            self.assertEqual(data["payment"]["cardBrand"], "AMEX")
            self.assertEqual(data["payment"]["cardLast4"], "0005")
            self.assertTrue(data["subscription"]["active"])

    def test_confirm_rechaza_sesion_de_otro_doctor_o_modo_cruzado_o_error_red(self):
        doc = self._registrar_doctor()
        otro = app.handle("POST", "/api/auth/register", body={
            "email": "otro.doc@midoc.mx",
            "password": "Segura123",
            "role": "DOCTOR",
            "name": "Otro Doc",
            "specialty": "Dermatología",
            "location": "CDMX",
            "price": 500,
        })
        otro_token = json.loads(otro["body"])["token"]

        env = {"PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_test_1234567890"}
        with patch.dict(os.environ, env, clear=False):
            # Otro doctor
            with patch.object(pagos_stripe, "_stripe_request", return_value={
                "id": "cs_test_ajeno_12345",
                "payment_status": "paid",
                "livemode": False,
                "metadata": {"doctorId": doc["user"]["doctorId"]},
            }):
                r = app.handle("POST", "/api/subscriptions/confirm", {"authorization": f"Bearer {otro_token}"}, {"sessionId": "cs_test_ajeno_12345"})
                self.assertEqual(r["statusCode"], 403)

            # Modo cruzado (livemode=True en test)
            with patch.object(pagos_stripe, "_stripe_request", return_value={
                "id": "cs_live_123456789",
                "payment_status": "paid",
                "livemode": True,
                "metadata": {"doctorId": doc["user"]["doctorId"]},
            }):
                r = app.handle("POST", "/api/subscriptions/confirm", {"authorization": f"Bearer {doc['token']}"}, {"sessionId": "cs_live_123456789"})
                self.assertEqual(r["statusCode"], 400)

            # Error de red Stripe -> 502
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
                r = app.handle("POST", "/api/subscriptions/checkout", {"authorization": f"Bearer {doc['token']}"}, {})
                self.assertEqual(r["statusCode"], 502)

    def test_webhook_stripe_raw_body_rotacion_e_idempotencia(self):
        doc = self._registrar_doctor()
        doctor_id = doc["user"]["doctorId"]
        wh_secret = "whsec_test_secret_123"

        # Payload con espacios no canónicos para probar que se verifica el raw_body exacto
        raw_str = (
            '{\n  "id": "evt_1",\n  "type": "checkout.session.completed",\n  "data": {\n'
            f'    "object": {{ "id": "cs_test_wh_123456", "payment_status": "paid", "amount_total": 2000, '
            f'"livemode": false, "payment_intent": "pi_wh_1", "metadata": {{ "doctorId": "{doctor_id}" }} }}\n'
            "  }\n}"
        )
        raw_bytes = raw_str.encode("utf-8")
        ts = int(time.time())
        sig_valid = hmac.new(wh_secret.encode(), f"{ts}.".encode() + raw_bytes, hashlib.sha256).hexdigest()
        # Múltiples v1 (rotación de secretos)
        sig_header = f"t={ts},v1=deadbeef0000,v1={sig_valid}"

        env = {"PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_test_12345", "STRIPE_WEBHOOK_SECRET": wh_secret}
        with patch.dict(os.environ, env, clear=False), \
                patch.object(pagos_stripe, "consultar_sesion_checkout", side_effect=reglas.ErrorApi(502, "skip expand")):
            event = {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": "/api/webhooks/stripe",
                "headers": {"Stripe-Signature": sig_header},
                "body": base64.b64encode(raw_bytes).decode("ascii"),
                "isBase64Encoded": True,
            }
            res1 = handler(event, None)
            self.assertEqual(res1["statusCode"], 200)
            self.assertTrue(json.loads(res1["body"])["data"]["processed"])

            # Reintento del mismo webhook -> idempotente (processed=False, no duplica 30 días)
            res2 = handler(event, None)
            self.assertEqual(res2["statusCode"], 200)
            self.assertFalse(json.loads(res2["body"])["data"]["processed"])

            # Confirm posterior del frontend también es idempotente
            conf = app.handle("POST", "/api/subscriptions/confirm", {"authorization": f"Bearer {doc['token']}"}, {"sessionId": "cs_test_wh_123456"})
            self.assertEqual(conf["statusCode"], 200)
            subs = [s for s in app.DB["subscriptions"] if s["doctor_id"] == doctor_id and s["status"] == "ACTIVA"]
            self.assertEqual(len(subs), 1)

            # Firma manipulada -> 401
            bad_event = dict(event, headers={"Stripe-Signature": f"t={ts},v1=0000"})
            self.assertEqual(handler(bad_event, None)["statusCode"], 401)

            # Timestamp expirado (>300s) -> 400
            old_ts = ts - 400
            old_sig = _firmar_stripe(raw_bytes, wh_secret, ts=old_ts)
            expired_event = dict(event, headers={"Stripe-Signature": old_sig})
            self.assertEqual(handler(expired_event, None)["statusCode"], 400)

            # Sin cabecera -> 400
            missing_event = dict(event, headers={})
            self.assertEqual(handler(missing_event, None)["statusCode"], 400)

    def test_webhook_expired_marca_pendiente_inactiva(self):
        doc = self._registrar_doctor()
        wh_secret = "whsec_test_secret_123"
        env = {"PAYMENT_MODE": "test", "STRIPE_SECRET_KEY": "sk_test_12345", "STRIPE_WEBHOOK_SECRET": wh_secret}

        with patch.dict(os.environ, env, clear=False), \
                patch.object(pagos_stripe, "_stripe_request", return_value={"id": "cs_test_exp_12345", "url": "https://checkout.stripe.com/x"}):
            app.handle("POST", "/api/subscriptions/checkout", {"authorization": f"Bearer {doc['token']}"}, {})

        raw_bytes = json.dumps({
            "id": "evt_exp",
            "type": "checkout.session.expired",
            "data": {"object": {"id": "cs_test_exp_12345"}},
        }).encode("utf-8")
        with patch.dict(os.environ, env, clear=False):
            r = app.handle(
                "POST",
                "/api/webhooks/stripe",
                headers={"Stripe-Signature": _firmar_stripe(raw_bytes, wh_secret)},
                body=json.loads(raw_bytes),
                raw_body=raw_bytes,
            )
            self.assertEqual(r["statusCode"], 200)
        sub = next(s for s in app.DB["subscriptions"] if s.get("stripeSessionId") == "cs_test_exp_12345")
        self.assertEqual(sub["status"], "INACTIVA")

    def test_webhook_rechaza_livemode_false_en_modo_live(self):
        doc = self._registrar_doctor()
        doctor_id = doc["user"]["doctorId"]
        wh_secret = "whsec_live_secret_123"
        raw_bytes = json.dumps({
            "id": "evt_cross_mode",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_cross_mode_1",
                    "payment_status": "paid",
                    "amount_total": 2000,
                    "livemode": False,
                    "metadata": {"doctorId": doctor_id},
                }
            },
        }).encode("utf-8")

        env = {"PAYMENT_MODE": "live", "STRIPE_SECRET_KEY": "sk_live_12345", "STRIPE_WEBHOOK_SECRET": wh_secret}
        with patch.dict(os.environ, env, clear=False):
            res = app.handle(
                "POST",
                "/api/webhooks/stripe",
                headers={"Stripe-Signature": _firmar_stripe(raw_bytes, wh_secret)},
                body=json.loads(raw_bytes),
                raw_body=raw_bytes,
            )
        self.assertEqual(res["statusCode"], 400)
        subs = [s for s in app.DB["subscriptions"] if s["doctor_id"] == doctor_id and s["status"] == "ACTIVA"]
        self.assertEqual(subs, [])

    def test_webhook_y_confirm_emiten_payment_succeeded_una_sola_vez(self):
        import contextlib
        import io

        doc = self._registrar_doctor()
        doctor_id = doc["user"]["doctorId"]
        wh_secret = "whsec_test_secret_123"
        raw_bytes = json.dumps({
            "id": "evt_once_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_once_123456",
                    "payment_status": "paid",
                    "amount_total": 2000,
                    "livemode": False,
                    "payment_intent": "pi_once_1",
                    "metadata": {"doctorId": doctor_id},
                }
            },
        }).encode("utf-8")
        env = {
            "PAYMENT_MODE": "test",
            "STRIPE_SECRET_KEY": "sk_test_12345",
            "STRIPE_WEBHOOK_SECRET": wh_secret,
            "METRICS_ENABLED": "true",
            "NODE_ENV": "test",
        }
        salida = io.StringIO()
        with patch.dict(os.environ, env, clear=False), \
                patch.object(pagos_stripe, "consultar_sesion_checkout", side_effect=reglas.ErrorApi(502, "skip")), \
                contextlib.redirect_stdout(salida):
            r1 = handler(
                {
                    "requestContext": {"http": {"method": "POST"}},
                    "rawPath": "/api/webhooks/stripe",
                    "headers": {"Stripe-Signature": _firmar_stripe(raw_bytes, wh_secret)},
                    "body": raw_bytes.decode("utf-8"),
                },
                None,
            )
            r2 = handler(
                {
                    "requestContext": {"http": {"method": "POST"}},
                    "rawPath": "/api/subscriptions/confirm",
                    "headers": {"authorization": f"Bearer {doc['token']}"},
                    "body": json.dumps({"sessionId": "cs_test_once_123456"}),
                },
                None,
            )
        self.assertEqual(r1["statusCode"], 200)
        self.assertEqual(r2["statusCode"], 200)
        eventos = [json.loads(line) for line in salida.getvalue().splitlines() if line.startswith("{")]
        succeeded = [e for e in eventos if "PaymentSucceeded" in e]
        self.assertEqual(len(succeeded), 1)
        self.assertEqual(succeeded[0]["PaymentSucceeded"], 1)


class ModoPagoSimuladoTests(unittest.TestCase):
    """Modo 'simulado': pagos sin llave real de Stripe (única función permitida como simulada)."""

    def setUp(self):
        app.DB.clear()
        app.DB.update(copy.deepcopy(DB_ORIGINAL))
        flujos.reset_rate_limits(app.DB)
        pagos_stripe.limpiar_cache()

    def tearDown(self):
        pagos_stripe.limpiar_cache()

    def _registrar_doctor(self):
        resp = app.handle("POST", "/api/auth/register", body={
            "email": "sim.doc@midoc.mx",
            "password": "Segura123",
            "role": "DOCTOR",
            "name": "Dr. Simulado",
            "specialty": "Cardiología",
            "location": "CDMX",
            "price": 700,
        })
        self.assertEqual(resp["statusCode"], 201)
        return json.loads(resp["body"])

    def test_es_sesion_simulada(self):
        self.assertTrue(pagos_stripe.es_sesion_simulada("cs_sim_abc123def456"))
        self.assertFalse(pagos_stripe.es_sesion_simulada("cs_test_abc12345"))
        self.assertFalse(pagos_stripe.es_sesion_simulada("otro"))

    def test_config_simulado_no_requiere_llave(self):
        with patch.dict(os.environ, {"PAYMENT_MODE": "simulado"}, clear=True):
            pagos_stripe.validar_config_stripe(pagos_stripe.obtener_config())

    def test_checkout_simulado_sin_llave_genera_sesion_propia(self):
        with patch.dict(os.environ, {"PAYMENT_MODE": "simulado", "FRONTEND_BASE_URL": "https://front.example/index.html"}, clear=True):
            sesion = pagos_stripe.crear_checkout_suscripcion("doc-1", "user-1", "a@b.c")
        self.assertTrue(sesion["sessionId"].startswith("cs_sim_"))
        self.assertEqual(sesion["mode"], "simulado")
        self.assertIn("#/suscripcion/pago-simulado", sesion["checkoutUrl"])
        self.assertEqual(sesion["amountUsd"], 20.0)

    def test_consulta_sesion_simulada_esta_pagada(self):
        sesion = pagos_stripe.consultar_sesion_checkout("cs_sim_abc123def456")
        self.assertEqual(sesion["paymentStatus"], "paid")
        self.assertEqual(sesion["paymentMode"], "simulado")
        self.assertEqual(sesion["amountTotal"], 2000)

    def test_flujo_checkout_confirm_simulado_activa_suscripcion(self):
        doc = self._registrar_doctor()
        token = doc["token"]
        env = {"PAYMENT_MODE": "simulado", "FRONTEND_BASE_URL": "https://front.example/index.html"}
        with patch.dict(os.environ, env, clear=False):
            ck = app.handle(
                "POST", "/api/subscriptions/checkout",
                headers={"authorization": f"Bearer {token}"}, body={},
            )
            self.assertEqual(ck["statusCode"], 201)
            data = json.loads(ck["body"])["data"]
            self.assertEqual(data["mode"], "simulado")
            session_id = data["sessionId"]
            self.assertTrue(session_id.startswith("cs_sim_"))

            conf = app.handle(
                "POST", "/api/subscriptions/confirm",
                headers={"authorization": f"Bearer {token}"},
                body={"sessionId": session_id},
            )
            self.assertEqual(conf["statusCode"], 200)
            confirmado = json.loads(conf["body"])["data"]
            self.assertTrue(confirmado["subscription"]["active"])
            self.assertEqual(confirmado["payment"]["paymentMode"], "simulado")

    def test_confirm_simulado_rechaza_sesion_de_otro_doctor(self):
        doc_a = self._registrar_doctor()
        # segundo doctor con otro correo
        resp = app.handle("POST", "/api/auth/register", body={
            "email": "sim.doc2@midoc.mx",
            "password": "Segura123",
            "role": "DOCTOR",
            "name": "Dr. Dos",
            "specialty": "Dermatología",
            "location": "CDMX",
            "price": 500,
        })
        self.assertEqual(resp["statusCode"], 201)
        doc_b = json.loads(resp["body"])
        env = {"PAYMENT_MODE": "simulado", "FRONTEND_BASE_URL": "https://front.example/index.html"}
        with patch.dict(os.environ, env, clear=False):
            ck = app.handle(
                "POST", "/api/subscriptions/checkout",
                headers={"authorization": f"Bearer {doc_a['token']}"}, body={},
            )
            session_id = json.loads(ck["body"])["data"]["sessionId"]
            conf = app.handle(
                "POST", "/api/subscriptions/confirm",
                headers={"authorization": f"Bearer {doc_b['token']}"},
                body={"sessionId": session_id},
            )
        self.assertEqual(conf["statusCode"], 403)


if __name__ == "__main__":
    unittest.main()
