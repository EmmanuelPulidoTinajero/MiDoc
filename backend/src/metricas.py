"""Métricas y logging estructurado JSON de MiDoc para CloudWatch.

Lambda escribe una línea JSON EMF por petición en stdout y CloudWatch Logs la
transforma en métricas del espacio de nombres ``MiDoc`` sin llamadas extra a
``PutMetricData``. Los logs estructurados de aplicación se escriben por stderr
mediante ``logging`` para no contaminar stdout ni romper los extractores EMF.
"""
import json
import logging
import os
import re
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone

logger = logging.getLogger("midoc.metricas")
http_logger = logging.getLogger("midoc.http")

NAMESPACE = "MiDoc"
SERVICIO = "midoc-api"

UNIDADES = {
    "RequestLatencyMs": "Milliseconds",
    "ServerErrors": "Count",
    "AppointmentsCreated": "Count",
    "ConsultationsRegistered": "Count",
    "LoginFailures": "Count",
}

UNIDADES_EVENTOS = {
    "RemindersJobRuns": "Count",
    "RemindersJobErrors": "Count",
    "PaymentCheckoutCreated": "Count",
    "PaymentSucceeded": "Count",
    "PaymentFailed": "Count",
    "DocumentOpsErrors": "Count",
    "DynamoAuditErrors": "Count",
}

TODAS_LAS_UNIDADES = {**UNIDADES, **UNIDADES_EVENTOS}

_CONTEXTO_ROL: ContextVar[str] = ContextVar("midoc_user_role", default="ANONYMOUS")

_RE_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._\-=]+", re.IGNORECASE)
_RE_STRIPE = re.compile(r"\b(?:sk|pk|whsec)_(?:test|live)?_?[A-Za-z0-9]+")
_RE_PASSWORD_QUOTED = re.compile(
    r"((?:current_?|new_?)?password(?:_?hash)?[\"']?\s*[:=]\s*)([\"'])(?:\\.|(?!\2).)*\2",
    re.IGNORECASE,
)
_RE_PASSWORD = re.compile(
    r"((?:current_?|new_?)?password(?:_?hash)?[\"']?\s*[:=]\s*)(?![\"'])[^\s,}\]]+",
    re.IGNORECASE,
)
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_CLAVES_SENSIBLES = {
    "password",
    "currentpassword",
    "newpassword",
    "password_hash",
    "secret",
    "stripe_secret_key",
    "stripe_webhook_secret",
    "jwt_secret",
    "authorization",
}


def _es_clave_sensible(clave: object) -> bool:
    if not isinstance(clave, str):
        return False
    norm = clave.strip().lower().replace("-", "_")
    return norm in _CLAVES_SENSIBLES or "password" in norm


def establecer_rol(role: str | None) -> None:
    _CONTEXTO_ROL.set((role or "ANONYMOUS").upper())


def obtener_rol() -> str:
    return _CONTEXTO_ROL.get()


def limpiar_contexto() -> None:
    _CONTEXTO_ROL.set("ANONYMOUS")


def redactar(texto: object) -> str:
    s = str(texto)
    s = _RE_BEARER.sub("Bearer [REDACTED]", s)
    s = _RE_STRIPE.sub("[REDACTED_STRIPE_KEY]", s)
    s = _RE_PASSWORD_QUOTED.sub(r"\1\2[REDACTED]\2", s)
    s = _RE_PASSWORD.sub(r"\1[REDACTED]", s)
    s = _RE_EMAIL.sub("[REDACTED_EMAIL]", s)
    return s


def _redactar_valor(valor: object) -> object:
    if isinstance(valor, str):
        return redactar(valor)
    if isinstance(valor, dict):
        limpio = {}
        for k, v in valor.items():
            if _es_clave_sensible(k) and not isinstance(v, (dict, list, tuple)):
                limpio[k] = "[REDACTED]"
            else:
                limpio[k] = _redactar_valor(v)
        return limpio
    if isinstance(valor, (list, tuple)):
        return [_redactar_valor(item) for item in valor]
    return valor


class JsonLogFormatter(logging.Formatter):
    _CAMPOS = ("requestId", "route", "method", "status", "durationMs", "userRole", "event", "job")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": redactar(record.getMessage()),
        }
        for campo in self._CAMPOS:
            valor = getattr(record, campo, None)
            if valor is not None:
                payload[campo] = _redactar_valor(valor)
        extras = getattr(record, "extra_fields", None)
        if isinstance(extras, dict):
            for k, v in extras.items():
                if k not in payload and v is not None:
                    if _es_clave_sensible(k) and not isinstance(v, (dict, list, tuple)):
                        payload[k] = "[REDACTED]"
                    else:
                        payload[k] = _redactar_valor(v)
        if record.exc_info:
            tb_texto = self.formatException(record.exc_info)
            if record.exc_info[1] is not None:
                payload["error"] = redactar(f"{type(record.exc_info[1]).__name__}: {record.exc_info[1]}")
            payload["traceback"] = redactar(tb_texto)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=redactar)


def configurar_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    raiz = logging.getLogger("midoc")
    raiz.handlers = [handler]
    raiz.setLevel(logging.INFO)
    raiz.propagate = False


def log_peticion(
    *,
    request_id: str,
    route: str,
    method: str,
    status: int,
    duration_ms: float,
    user_role: str = "ANONYMOUS",
) -> None:
    try:
        nivel = logging.ERROR if status >= 500 else logging.INFO
        http_logger.log(
            nivel,
            "http_request",
            extra={
                "requestId": request_id,
                "route": route,
                "method": method,
                "status": int(status),
                "durationMs": round(float(duration_ms), 2),
                "userRole": user_role or "ANONYMOUS",
                "event": "http_request",
            },
        )
    except Exception:
        pass


def log_evento(level: str, message: str, **fields) -> None:
    try:
        nivel = getattr(logging, str(level).upper(), logging.INFO)
        http_logger.log(nivel, message, extra={"extra_fields": fields})
    except Exception:
        pass


def habilitadas():
    """Activas en producción (Lambda); se pueden forzar con METRICS_ENABLED=true|false."""
    valor = os.environ.get("METRICS_ENABLED")
    if valor is not None:
        return valor.strip().lower() == "true"
    return os.environ.get("NODE_ENV") == "production"


def de_peticion(method, path, status, latencia_ms):
    """Valores de las métricas que corresponden a una petición ya resuelta."""
    ruta = path.split("?", 1)[0].rstrip("/") or "/"
    valores = {
        "RequestLatencyMs": round(float(latencia_ms), 2),
        "ServerErrors": 1 if status >= 500 else 0,
    }
    if method == "POST" and ruta == "/api/appointments" and status == 201:
        valores["AppointmentsCreated"] = 1
    if method == "POST" and ruta == "/api/consultations" and status == 201:
        valores["ConsultationsRegistered"] = 1
    if method == "POST" and ruta == "/api/auth/login" and status == 401:
        valores["LoginFailures"] = 1
    if method == "POST" and ruta == "/api/subscriptions/checkout":
        if status == 201:
            valores["PaymentCheckoutCreated"] = 1
        elif status >= 400 and status != 401:
            valores["PaymentFailed"] = 1
    if method == "POST" and ruta == "/api/subscriptions/confirm":
        if status >= 400 and status != 401:
            valores["PaymentFailed"] = 1
    if method == "POST" and ruta == "/api/webhooks/stripe" and status >= 400:
        valores["PaymentFailed"] = 1
    return valores


def construir_registro(valores, marca_ms=None):
    """Arma el documento EMF que CloudWatch Logs transforma en métricas."""
    return {
        "_aws": {
            "Timestamp": int(time.time() * 1000) if marca_ms is None else marca_ms,
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [["Service"]],
                "Metrics": [{"Name": nombre, "Unit": TODAS_LAS_UNIDADES[nombre]} for nombre in valores],
            }],
        },
        "Service": SERVICIO,
        **valores,
    }


def registrar_metrica(nombre: str, valor: float | int = 1) -> None:
    try:
        if not habilitadas() or nombre not in TODAS_LAS_UNIDADES:
            return
        registro = construir_registro({nombre: valor})
        print(json.dumps(registro, separators=(",", ":")), flush=True)
    except Exception:
        logger.warning("No se pudo emitir la métrica %s", nombre, exc_info=True)


def registrar_peticion(method, path, status, latencia_ms):
    try:
        if not habilitadas():
            return
        registro = construir_registro(de_peticion(method, path, status, latencia_ms))
        print(json.dumps(registro, separators=(",", ":")), flush=True)
    except Exception:  # las métricas nunca deben tumbar la API
        logger.warning("No se pudo emitir la métrica de la petición", exc_info=True)
