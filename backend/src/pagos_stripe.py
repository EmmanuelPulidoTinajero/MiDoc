"""Integración real con Stripe Checkout Sessions v1 y webhooks firmados.

Usa únicamente la biblioteca estándar de Python (urllib, hmac, hashlib, json)
y boto3 diferido para Secrets Manager, evitando dependencias binarias extra en Lambda.
"""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from reglas import ErrorApi

STRIPE_API_BASE = "https://api.stripe.com/v1"
_SESSION_ID_RE = re.compile(r"^cs_[A-Za-z0-9_]{8,240}$")
_SECRET_CACHE: dict[str, dict] = {}


def limpiar_cache() -> None:
    """Limpia la caché de secretos de Secrets Manager (útil en pruebas)."""
    _SECRET_CACHE.clear()


def _cargar_secreto(secret_id: str) -> dict:
    if not secret_id:
        return {}
    if secret_id in _SECRET_CACHE:
        return _SECRET_CACHE[secret_id]
    import boto3

    raw = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
    datos = json.loads(raw)
    if not isinstance(datos, dict):
        datos = {}
    _SECRET_CACHE[secret_id] = datos
    return datos


def _resolver_valor(secretos: list[dict], *nombres: str) -> str | None:
    for nombre in nombres:
        valor = os.environ.get(nombre)
        if valor is not None and str(valor).strip():
            return str(valor).strip()
    for secreto in secretos:
        for nombre in nombres:
            valor = secreto.get(nombre)
            if valor is not None and str(valor).strip():
                return str(valor).strip()
    return None


def obtener_config(force_refresh: bool = False) -> dict:
    """Resuelve la configuración de Stripe desde env vars o Secrets Manager."""
    if force_refresh:
        limpiar_cache()

    secretos = []
    # Sólo consulta Secrets Manager si alguna clave falta en variables de entorno directas.
    faltan_directas = not (
        os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("PAYMENT_MODE")
    )
    if faltan_directas or not os.environ.get("STRIPE_WEBHOOK_SECRET"):
        for env_arn in ("STRIPE_SECRET_ARN", "SECRETS_MANAGER_SECRET_ID", "APP_SECRET_ARN"):
            secret_id = os.environ.get(env_arn, "").strip()
            if secret_id:
                try:
                    secretos.append(_cargar_secreto(secret_id))
                except Exception:
                    # Si falla la lectura de un secreto opcional se intenta el siguiente;
                    # validar_config_stripe fallará explícitamente si falta la llave requerida.
                    continue

    payment_mode = (_resolver_valor(secretos, "PAYMENT_MODE", "payment_mode") or "test").lower()
    if payment_mode not in ("test", "live", "simulado"):
        raise ErrorApi(500, "PAYMENT_MODE debe ser 'test', 'live' o 'simulado'")

    secret_key = _resolver_valor(secretos, "STRIPE_SECRET_KEY", "stripe_secret_key") or ""
    webhook_secret = _resolver_valor(secretos, "STRIPE_WEBHOOK_SECRET", "stripe_webhook_secret") or ""

    amount_raw = _resolver_valor(secretos, "STRIPE_PRICE_AMOUNT_CENTS", "stripe_price_amount_cents") or "2000"
    try:
        amount_cents = int(amount_raw)
    except ValueError as error:
        raise ErrorApi(500, "STRIPE_PRICE_AMOUNT_CENTS debe ser un entero positivo") from error
    if amount_cents <= 0:
        raise ErrorApi(500, "STRIPE_PRICE_AMOUNT_CENTS debe ser mayor a cero")

    frontend_base_url = (
        _resolver_valor(secretos, "FRONTEND_BASE_URL", "frontend_base_url")
        or "http://localhost:4200/index.html"
    )

    return {
        "payment_mode": payment_mode,
        "secret_key": secret_key,
        "webhook_secret": webhook_secret,
        "amount_cents": amount_cents,
        "frontend_base_url": frontend_base_url,
    }


def es_sesion_simulada(session_id: object) -> bool:
    """Indica si la sesión pertenece al modo de pago simulado (sin llave real)."""
    return isinstance(session_id, str) and session_id.startswith("cs_sim_")


def validar_config_stripe(cfg: dict) -> None:
    secret_key = cfg.get("secret_key") or ""
    mode = cfg.get("payment_mode") or "test"
    if mode == "simulado":
        # Único modo que opera sin llave real: el pago queda simulado de punta a punta.
        return
    if not secret_key:
        raise ErrorApi(503, "Stripe no está configurado en el servidor")
    if mode == "test" and not secret_key.startswith("sk_test_"):
        raise ErrorApi(500, "Inconsistencia de configuración: PAYMENT_MODE=test requiere una llave sk_test_")
    if mode == "live" and not secret_key.startswith("sk_live_"):
        raise ErrorApi(500, "Inconsistencia de configuración: PAYMENT_MODE=live requiere una llave sk_live_")


def _validar_url_retorno(url: str, base_url: str, campo: str) -> str:
    parsed = urllib.parse.urlparse(url)
    en_prod = os.environ.get("NODE_ENV") == "production"
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ErrorApi(400, f"El campo '{campo}' debe ser una URL válida")
    if parsed.scheme == "http":
        if en_prod or parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ErrorApi(400, f"El campo '{campo}' debe usar HTTPS")
    if en_prod:
        base_parsed = urllib.parse.urlparse(base_url)
        if base_parsed.netloc and parsed.netloc != base_parsed.netloc:
            raise ErrorApi(400, f"El campo '{campo}' no pertenece al dominio configurado de la aplicación")
    return url


def construir_urls_retorno(
    frontend_base_url: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> tuple[str, str]:
    base = frontend_base_url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if not base.endswith(".html"):
        base = f"{base}/index.html"

    if success_url:
        success = _validar_url_retorno(success_url, frontend_base_url, "successUrl")
        if "{CHECKOUT_SESSION_ID}" not in success:
            sep = "&" if "?" in success else "?"
            success = f"{success}{sep}session_id={{CHECKOUT_SESSION_ID}}"
    else:
        success = f"{base}#/panel/suscripcion?stripe_status=success&session_id={{CHECKOUT_SESSION_ID}}"

    if cancel_url:
        cancel = _validar_url_retorno(cancel_url, frontend_base_url, "cancelUrl")
    else:
        cancel = f"{base}#/panel/suscripcion?stripe_status=cancel"

    return success, cancel


def _resolver_api_base() -> str:
    if os.environ.get("NODE_ENV") == "production":
        return STRIPE_API_BASE
    return (os.environ.get("STRIPE_API_BASE") or STRIPE_API_BASE).strip().rstrip("/") or STRIPE_API_BASE


def _stripe_request(
    method: str,
    path: str,
    secret_key: str,
    form_params: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    url = f"{_resolver_api_base()}{path}"
    headers = {"Authorization": f"Bearer {secret_key}"}
    data = None
    if form_params is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form_params).encode("utf-8")
    if idempotency_key and method == "POST":
        headers["Idempotency-Key"] = idempotency_key

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        mensaje = "Error al comunicarse con Stripe"
        try:
            cuerpo = json.loads(error.read().decode("utf-8"))
            err = cuerpo.get("error") or {}
            if isinstance(err, dict) and err.get("message"):
                mensaje = str(err["message"])
        except Exception:
            pass
        if error.code == 404:
            raise ErrorApi(404, "Sesión de pago no encontrada en Stripe") from error
        if error.code == 402:
            raise ErrorApi(402, mensaje) from error
        if error.code == 400:
            raise ErrorApi(400, mensaje) from error
        if error.code in (401, 403):
            raise ErrorApi(502, "Credenciales de Stripe rechazadas") from error
        raise ErrorApi(502, "Error al comunicarse con Stripe") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ErrorApi(502, "No se pudo conectar con Stripe; intenta nuevamente") from error


def crear_checkout_suscripcion(
    doctor_id: str,
    user_id: str,
    email: str | None,
    success_url: str | None = None,
    cancel_url: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    cfg = obtener_config()
    validar_config_stripe(cfg)
    # La validación de URLs de retorno aplica también en modo simulado (endurecimiento).
    success, cancel = construir_urls_retorno(cfg["frontend_base_url"], success_url, cancel_url)
    if cfg["payment_mode"] == "simulado":
        base = (cfg.get("frontend_base_url") or "").rstrip("/")
        return {
            "sessionId": f"cs_sim_{uuid.uuid4().hex}",
            "checkoutUrl": f"{base}/#/suscripcion/pago-simulado" if base else "#/suscripcion/pago-simulado",
            "mode": "simulado",
            "amountUsd": round(cfg["amount_cents"] / 100, 2),
        }

    params = {
        "mode": "payment",
        "success_url": success,
        "cancel_url": cancel,
        "payment_method_types[0]": "card",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(cfg["amount_cents"]),
        "line_items[0][price_data][product_data][name]": "Suscripción mensual MiDoc (30 días)",
        "line_items[0][quantity]": "1",
        "client_reference_id": doctor_id,
        "metadata[doctorId]": doctor_id,
        "metadata[userId]": user_id,
        "metadata[paymentMode]": cfg["payment_mode"],
    }
    if email:
        params["customer_email"] = email

    data = _stripe_request(
        "POST",
        "/checkout/sessions",
        cfg["secret_key"],
        form_params=params,
        idempotency_key=idempotency_key,
    )
    return {
        "sessionId": data["id"],
        "checkoutUrl": data["url"],
        "mode": cfg["payment_mode"],
        "amountUsd": round(cfg["amount_cents"] / 100, 2),
    }


def _extraer_tarjeta(payment_intent: object) -> tuple[str | None, str | None, str | None]:
    if not isinstance(payment_intent, dict):
        return (payment_intent if isinstance(payment_intent, str) else None), None, None
    pi_id = payment_intent.get("id")
    card = None
    pm = payment_intent.get("payment_method")
    if isinstance(pm, dict):
        card = pm.get("card")
    if not isinstance(card, dict):
        charge = payment_intent.get("latest_charge")
        if isinstance(charge, dict):
            pmd = charge.get("payment_method_details") or {}
            if isinstance(pmd, dict):
                card = pmd.get("card")
    if isinstance(card, dict):
        brand = str(card.get("brand") or "").strip().upper()[:32] or None
        last4 = str(card.get("last4") or "").strip()[:4] or None
        return pi_id, brand, last4
    return pi_id, None, None


def consultar_sesion_checkout(session_id: str) -> dict:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        raise ErrorApi(400, "Identificador de sesión Stripe inválido")
    cfg = obtener_config()
    if es_sesion_simulada(session_id):
        # Las sesiones simuladas son autosuficientes: deben confirmarse incluso
        # si la configuración de Stripe cambió después de crearlas.
        return {
            "id": session_id,
            "paymentStatus": "paid",
            "status": "complete",
            "amountTotal": cfg.get("amount_cents", 2000),
            "currency": "usd",
            "clientReferenceId": None,
            "metadata": {},
            "paymentIntentId": None,
            "cardBrand": "SIMULADA",
            "cardLast4": "4242",
            "paymentMode": "simulado",
        }
    validar_config_stripe(cfg)

    path = (
        f"/checkout/sessions/{session_id}"
        "?expand[]=payment_intent.payment_method"
        "&expand[]=payment_intent.latest_charge"
    )
    data = _stripe_request("GET", path, cfg["secret_key"])
    if "livemode" in data and bool(data.get("livemode")) != (cfg["payment_mode"] == "live"):
        raise ErrorApi(400, "La sesión de Stripe no corresponde al modo de pago configurado")

    pi_id, card_brand, card_last4 = _extraer_tarjeta(data.get("payment_intent"))
    return {
        "id": data.get("id", session_id),
        "paymentStatus": data.get("payment_status"),
        "status": data.get("status"),
        "amountTotal": data.get("amount_total"),
        "currency": data.get("currency"),
        "clientReferenceId": data.get("client_reference_id"),
        "metadata": data.get("metadata") or {},
        "paymentIntentId": pi_id,
        "cardBrand": card_brand,
        "cardLast4": card_last4,
        "paymentMode": "live" if data.get("livemode") else "test",
    }


def verificar_webhook(
    raw_body_bytes: bytes,
    signature_header: str | None,
    ahora_ts: int | None = None,
    tolerancia_seg: int = 300,
) -> dict:
    cfg = obtener_config()
    webhook_secret = cfg.get("webhook_secret") or ""
    if not webhook_secret:
        raise ErrorApi(503, "STRIPE_WEBHOOK_SECRET no está configurado")
    if not isinstance(signature_header, str) or not signature_header.strip():
        raise ErrorApi(400, "Cabecera Stripe-Signature faltante")

    timestamp = None
    v1_signatures = []
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "t":
            try:
                timestamp = int(v)
            except ValueError as error:
                raise ErrorApi(400, "Cabecera Stripe-Signature inválida") from error
        elif k == "v1" and v:
            v1_signatures.append(v)

    if timestamp is None or not v1_signatures:
        raise ErrorApi(400, "Cabecera Stripe-Signature inválida")

    actual = int(time.time() if ahora_ts is None else ahora_ts)
    if abs(actual - timestamp) > tolerancia_seg:
        raise ErrorApi(400, "Firma de webhook Stripe expirada")

    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body_bytes
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in v1_signatures):
        raise ErrorApi(401, "Firma de webhook Stripe inválida")

    try:
        evento = json.loads(raw_body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorApi(400, "El cuerpo del webhook no es JSON válido") from error
    if not isinstance(evento, dict):
        raise ErrorApi(400, "El cuerpo del webhook debe ser un objeto JSON")
    return evento
