"""Métricas de MiDoc en Embedded Metric Format (EMF) para CloudWatch.

Lambda escribe una línea JSON por petición en stdout y CloudWatch Logs la
convierte en métricas del espacio de nombres ``MiDoc``. No hay llamadas a
``PutMetricData`` ni permisos IAM adicionales: basta con que LabRole ya pueda
escribir logs.

Métricas (dimensión ``Service``):

* ``RequestLatencyMs``         duración de cada petición HTTP
* ``ServerErrors``             1 si la respuesta fue 5xx, 0 en caso contrario
* ``AppointmentsCreated``      citas agendadas (POST /api/appointments → 201)
* ``ConsultationsRegistered``  consultas guardadas (POST /api/consultations → 201)
* ``LoginFailures``            inicios de sesión rechazados (POST /api/auth/login → 401)

Emitir métricas nunca debe romper una petición: cualquier error se registra
como advertencia y se ignora.
"""
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

NAMESPACE = "MiDoc"
SERVICIO = "midoc-api"

UNIDADES = {
    "RequestLatencyMs": "Milliseconds",
    "ServerErrors": "Count",
    "AppointmentsCreated": "Count",
    "ConsultationsRegistered": "Count",
    "LoginFailures": "Count",
}


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
    return valores


def construir_registro(valores, marca_ms=None):
    """Arma el documento EMF que CloudWatch Logs transforma en métricas."""
    return {
        "_aws": {
            "Timestamp": int(time.time() * 1000) if marca_ms is None else marca_ms,
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [["Service"]],
                "Metrics": [{"Name": nombre, "Unit": UNIDADES[nombre]} for nombre in valores],
            }],
        },
        "Service": SERVICIO,
        **valores,
    }


def registrar_peticion(method, path, status, latencia_ms):
    if not habilitadas():
        return
    try:
        registro = construir_registro(de_peticion(method, path, status, latencia_ms))
        print(json.dumps(registro, separators=(",", ":")), flush=True)
    except Exception:  # las métricas nunca deben tumbar la API
        logger.warning("No se pudo emitir la métrica de la petición", exc_info=True)